"""Tests for :mod:`setspec.envelope` — version parsing, the envelope shape, and load/dump.

Version *negotiation* is a contract test and lives in
``tests/contract/test_version_negotiation.py``; what is asserted here is the machinery that
negotiation rests on.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from baseaicore import ValidationError

from setspec import (
    DRAFT_SCHEMAS,
    SUPPORTED_SCHEMAS,
    GeneratorInfo,
    SchemaEnvelope,
    SchemaVersion,
    dump_envelope,
    load_envelope,
)
from setspec.envelope import _SCHEMA_NAME_PATTERN

_AT = datetime(2026, 8, 22, 14, 3, 11, 250_000, tzinfo=UTC)
_SCHEMA = "demo.payload"
_V1_0 = SchemaVersion(1, 0)


def _document(generator: GeneratorInfo, **overrides: Any) -> dict[str, Any]:
    """Build a well-formed envelope as a plain mapping, with fields optionally replaced."""
    return {
        "schema": _SCHEMA,
        "schema_version": "1.0",
        "generated_at": "2026-08-22T14:03:11.250Z",
        "generator": {"name": generator.name, "version": generator.version},
        "payload": {"reading": 1.5},
    } | overrides


class TestSchemaVersion:
    """Two numbers, canonically spelled, ordered by major then minor."""

    def test_parses_and_formats_canonically(self) -> None:
        assert str(SchemaVersion.parse("1.0")) == "1.0"
        assert SchemaVersion.parse("2.13") == SchemaVersion(2, 13)

    @pytest.mark.parametrize(
        "text", ["1", "1.0.0", "v1.0", "01.0", "1.00", " 1.0", "1.0 ", "1.-1", "", "x.y"]
    )
    def test_non_canonical_spellings_are_rejected(self, text: str) -> None:
        """A version that parses two ways cannot round-trip byte-for-byte (spec §11.3-11.4)."""
        with pytest.raises(ValidationError):
            SchemaVersion.parse(text)

    def test_major_below_one_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SchemaVersion(0, 9)

    def test_negative_minor_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SchemaVersion(1, -1)

    def test_orders_by_major_then_minor(self) -> None:
        assert SchemaVersion(1, 2) < SchemaVersion(1, 10) < SchemaVersion(2, 0)

    def test_is_hashable_and_compares_by_value(self) -> None:
        assert SchemaVersion(1, 0) == SchemaVersion(1, 0)
        assert len({SchemaVersion(1, 0), SchemaVersion(1, 0)}) == 1


class TestDumpEnvelope:
    """Writing a document: canonical bytes, an injected clock, and a validated schema name."""

    def test_produces_the_adr_0009_shape(self, generator: GeneratorInfo) -> None:
        text = dump_envelope(
            {"reading": 1.5},
            schema=_SCHEMA,
            version=_V1_0,
            generator=generator,
            generated_at=_AT,
        )
        assert json.loads(text) == {
            "schema": _SCHEMA,
            "schema_version": "1.0",
            "generated_at": "2026-08-22T14:03:11.250Z",
            "generator": {"name": "setspec", "version": "0.1.0"},
            "payload": {"reading": 1.5},
        }

    def test_output_is_canonical_and_repeatable(self, generator: GeneratorInfo) -> None:
        kwargs: dict[str, Any] = {
            "schema": _SCHEMA,
            "version": _V1_0,
            "generator": generator,
            "generated_at": _AT,
        }
        assert dump_envelope({"b": 2, "a": 1}, **kwargs) == dump_envelope(
            {"a": 1, "b": 2}, **kwargs
        )

    def test_takes_its_timestamp_from_the_injected_clock(
        self, generator: GeneratorInfo, frozen_clock: Any
    ) -> None:
        text = dump_envelope(
            {"reading": 1.5}, schema=_SCHEMA, version=_V1_0, generator=generator, clock=frozen_clock
        )
        assert json.loads(text)["generated_at"] == "2026-08-22T14:03:11.250Z"

    @pytest.mark.parametrize("schema", ["", "result", "Benchmark.Result", "benchmark.", ".result"])
    def test_malformed_schema_names_are_rejected(
        self, generator: GeneratorInfo, schema: str
    ) -> None:
        with pytest.raises(ValidationError):
            dump_envelope({}, schema=schema, version=_V1_0, generator=generator, generated_at=_AT)

    def test_a_naive_generated_at_is_rejected(self, generator: GeneratorInfo) -> None:
        with pytest.raises(Exception, match="naive|timezone"):
            dump_envelope(
                {},
                schema=_SCHEMA,
                version=_V1_0,
                generator=generator,
                generated_at=datetime(2026, 8, 22),  # noqa: DTZ001
            )


class TestLoadEnvelope:
    """Reading a document: structure first, then identity, then version."""

    def test_reads_text_bytes_and_mappings_alike(self, generator: GeneratorInfo) -> None:
        document = _document(generator)
        text = json.dumps(document)
        for source in (text, text.encode(), document):
            envelope = load_envelope(source, expect=_SCHEMA, supported=[_V1_0])
            assert envelope.payload == {"reading": 1.5}

    def test_exposes_the_parsed_version(self, generator: GeneratorInfo) -> None:
        envelope = load_envelope(_document(generator), expect=_SCHEMA, supported=[_V1_0])
        assert envelope.version == _V1_0

    def test_generator_identity_survives(self, generator: GeneratorInfo) -> None:
        envelope = load_envelope(_document(generator), expect=_SCHEMA, supported=[_V1_0])
        assert envelope.generator.name == "setspec"

    def test_a_document_declaring_another_schema_is_rejected(
        self, generator: GeneratorInfo
    ) -> None:
        """Payload types are not interchangeable even when their fields line up."""
        document = _document(generator, schema="other.payload")
        with pytest.raises(ValidationError) as caught:
            load_envelope(document, expect=_SCHEMA, supported=[_V1_0])
        assert caught.value.details["expected"] == _SCHEMA
        assert caught.value.details["received"] == "other.payload"

    def test_missing_fields_are_all_named_in_one_error(self, generator: GeneratorInfo) -> None:
        """Spec §13: a structural violation lists every offending path at once."""
        with pytest.raises(ValidationError) as caught:
            load_envelope({"schema": _SCHEMA}, expect=_SCHEMA, supported=[_V1_0])
        reported = {item["field"] for item in caught.value.details["errors"]}
        assert {"schema_version", "generated_at", "generator", "payload"} <= reported

    @pytest.mark.parametrize("document", ["[1,2,3]", '"a string"', "42", "null"])
    def test_a_non_object_document_is_rejected(self, document: str) -> None:
        with pytest.raises(ValidationError, match="JSON object"):
            load_envelope(document, expect=_SCHEMA, supported=[_V1_0])

    def test_an_unparsable_version_string_is_rejected(self, generator: GeneratorInfo) -> None:
        document = _document(generator, schema_version="1")
        with pytest.raises(ValidationError):
            load_envelope(document, expect=_SCHEMA, supported=[_V1_0])

    def test_guards_apply_to_the_document(self, generator: GeneratorInfo) -> None:
        text = json.dumps(_document(generator))
        with pytest.raises(ValidationError) as caught:
            load_envelope(text, expect=_SCHEMA, supported=[_V1_0], max_bytes=10)
        assert caught.value.details["limit_bytes"] == 10


class TestEnvelopeRoundTrip:
    """`load(dump(x))` returns the same document, byte for byte."""

    def test_a_dumped_document_reloads_to_identical_bytes(self, generator: GeneratorInfo) -> None:
        original = dump_envelope(
            {"reading": 1.5, "unit": "ms"},
            schema=_SCHEMA,
            version=_V1_0,
            generator=generator,
            generated_at=_AT,
        )
        envelope = load_envelope(original, expect=_SCHEMA, supported=[_V1_0])
        redumped = dump_envelope(
            envelope.payload,
            schema=envelope.schema,
            version=envelope.version,
            generator=envelope.generator,
            generated_at=envelope.generated_at,
        )
        assert redumped == original

    def test_the_envelope_preserves_unknown_top_level_fields(
        self, generator: GeneratorInfo
    ) -> None:
        """An old reader must not strip an envelope field a newer writer added."""
        document = _document(generator, trace_id="01J9K2M")
        envelope: SchemaEnvelope[Any] = load_envelope(document, expect=_SCHEMA, supported=[_V1_0])
        assert envelope.extras["trace_id"] == "01J9K2M"
        assert envelope.model_dump()["trace_id"] == "01J9K2M"


class TestRegisteredSchemas:
    """What this build publishes, and which of those are still provisional."""

    def test_phase_2_payload_types_are_registered(self) -> None:
        assert {
            "model.identity",
            "machine.profile",
            "benchmark.result",
            "benchmark.run_summary",
            "capability.evidence",
            "benchmark.evidence_bundle",
        } <= set(SUPPORTED_SCHEMAS)

    def test_every_registered_schema_is_keyed_by_major(self) -> None:
        """ADR-0009 rule 9: majors, not exact versions — the recorded minor is documentation."""
        for majors in SUPPORTED_SCHEMAS.values():
            for major, version in majors.items():
                assert major == version.major

    def test_every_registered_schema_name_is_well_formed(self) -> None:
        """A name that `dump_envelope` would refuse must never be registered as readable."""
        for name in SUPPORTED_SCHEMAS:
            assert _SCHEMA_NAME_PATTERN.fullmatch(name) is not None

    def test_draft_schemas_are_all_actually_registered(self) -> None:
        """Marking an unregistered schema draft would describe something that cannot be read."""
        assert DRAFT_SCHEMAS <= set(SUPPORTED_SCHEMAS)

    def test_every_phase_2_schema_is_still_draft(self) -> None:
        """Phase 4 freezes these; until then the API must say so, not only the prose."""
        assert DRAFT_SCHEMAS == set(SUPPORTED_SCHEMAS)

    def test_a_draft_schema_negotiates_exactly_like_a_frozen_one(self) -> None:
        """Draft is advisory metadata, never a second acceptance rule."""
        document = _document(
            GeneratorInfo(name="freeweight", version="1.0.0"),
            schema="capability.evidence",
            payload={"anything": 1},
        )
        envelope = load_envelope(document, expect="capability.evidence")
        assert envelope.version == SchemaVersion(1, 0)
