"""Contract tests for the reader policy — ADR-0009 rules 3 and 4, in both directions.

This is the file that proves the promise two independently released applications rely on: a
document written by a newer build is readable by an older one when the major matches, is refused
clearly when it does not, and survives a re-export either way without losing the parts the reader
could not interpret.

It is marked ``contract`` because CI runs these separately (``pytest -m contract``): they are the
tests whose failure means a published guarantee broke, not merely that an implementation detail
changed.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from baseaicore import ValidationError

from setspec import (
    GeneratorInfo,
    PayloadDefinition,
    SchemaVersion,
    SchemaVersionUnsupported,
    canonical_dumps,
    dump_envelope,
    load_envelope,
    payload_models,
)
from setspec.serialization import MeasurementField

pytestmark = pytest.mark.contract

_AT = datetime(2026, 8, 22, 14, 3, 11, 250_000, tzinfo=UTC)
_SCHEMA = "demo.result"

# What this build knows: major 1 only. Major 2 does not exist here, and that is the point.
_READER_SUPPORTS = [SchemaVersion(1, 0)]


class ResultV1Fields(PayloadDefinition):
    """The v1.0 shape, as this reader's build understands it."""

    reading: MeasurementField
    unit: str


ResultV1Out, ResultV1In = payload_models(ResultV1Fields)


def _document(generator: GeneratorInfo, version: str, payload: dict[str, Any]) -> str:
    """Serialize a document at an arbitrary declared version, as a newer writer would."""
    return dump_envelope(
        payload,
        schema=_SCHEMA,
        version=SchemaVersion.parse(version),
        generator=generator,
        generated_at=_AT,
    )


class TestAcceptedVersions:
    """A supported major is readable regardless of the minor it declares."""

    def test_the_exact_known_version_is_accepted(self, generator: GeneratorInfo) -> None:
        document = _document(generator, "1.0", {"reading": 1.5, "unit": "ms"})
        assert load_envelope(document, expect=_SCHEMA, supported=_READER_SUPPORTS).version == (
            SchemaVersion(1, 0)
        )

    @pytest.mark.parametrize("minor", [1, 2, 99])
    def test_a_newer_minor_is_accepted(self, generator: GeneratorInfo, minor: int) -> None:
        """Minor means additive, so a reader must not refuse a minor it has never heard of."""
        document = _document(generator, f"1.{minor}", {"reading": 1.5, "unit": "ms"})
        envelope = load_envelope(document, expect=_SCHEMA, supported=_READER_SUPPORTS)
        assert envelope.version == SchemaVersion(1, minor)


class TestRejectedVersions:
    """An unsupported major is refused outright, and the refusal says everything needed to act."""

    def test_a_newer_major_is_rejected(self, generator: GeneratorInfo) -> None:
        document = _document(generator, "2.0", {"reading": 1.5, "unit": "ms"})
        with pytest.raises(SchemaVersionUnsupported):
            load_envelope(document, expect=_SCHEMA, supported=_READER_SUPPORTS)

    def test_an_older_unsupported_major_is_rejected(self, generator: GeneratorInfo) -> None:
        """Rejection is by membership, not by ordering: older is not automatically readable."""
        document = _document(generator, "1.0", {"reading": 1.5, "unit": "ms"})
        with pytest.raises(SchemaVersionUnsupported):
            load_envelope(document, expect=_SCHEMA, supported=[SchemaVersion(2, 0)])

    def test_the_error_names_received_and_supported_versions(
        self, generator: GeneratorInfo
    ) -> None:
        document = _document(generator, "2.3", {"reading": 1.5, "unit": "ms"})
        with pytest.raises(SchemaVersionUnsupported) as caught:
            load_envelope(
                document,
                expect=_SCHEMA,
                supported=[SchemaVersion(1, 0), SchemaVersion(1, 4)],
            )
        details = caught.value.details
        assert details["schema"] == _SCHEMA
        assert details["received"] == "2.3"
        assert details["supported"] == ["1.0", "1.4"]
        assert "2.3" in str(caught.value)

    def test_the_error_carries_the_documented_code(self, generator: GeneratorInfo) -> None:
        """The code appears in API error envelopes, so it is part of the public contract."""
        document = _document(generator, "9.0", {"reading": 1.5, "unit": "ms"})
        with pytest.raises(SchemaVersionUnsupported) as caught:
            load_envelope(document, expect=_SCHEMA, supported=_READER_SUPPORTS)
        assert caught.value.code == "SCHEMA_VERSION_UNSUPPORTED"

    def test_an_unsupported_major_is_never_partially_parsed(self, generator: GeneratorInfo) -> None:
        """A v2 document whose fields still *look* like v1 must not be read as v1."""
        document = _document(generator, "2.0", {"reading": 1.5, "unit": "ms"})
        with pytest.raises(SchemaVersionUnsupported):
            load_envelope(document, expect=_SCHEMA, supported=_READER_SUPPORTS)

    def test_an_unregistered_schema_reports_that_nothing_is_supported(
        self, generator: GeneratorInfo
    ) -> None:
        """With no explicit `supported`, the answer comes from SUPPORTED_SCHEMAS.

        Empty at 0.1.0, so this also pins down what an unregistered schema reports.
        """
        document = _document(generator, "1.0", {"reading": 1.5, "unit": "ms"})
        with pytest.raises(SchemaVersionUnsupported) as caught:
            load_envelope(document, expect=_SCHEMA)
        assert caught.value.details["supported"] == []


class TestUnknownFieldPreservation:
    """A v1.0 reader carries a v1.1 document through a re-export without losing anything."""

    def test_the_reader_preserves_a_field_it_does_not_know(self, generator: GeneratorInfo) -> None:
        document = _document(generator, "1.1", {"reading": 1.5, "unit": "ms", "confidence": 0.87})
        envelope = load_envelope(document, expect=_SCHEMA, supported=_READER_SUPPORTS)
        payload = ResultV1In.model_validate(envelope.payload)
        assert payload.reading == 1.5
        assert payload.extras == {"confidence": 0.87}

    def test_a_re_export_loses_nothing(self, generator: GeneratorInfo) -> None:
        """The whole point of rule 4: an old tool must not silently destroy a newer field."""
        original = _document(generator, "1.1", {"reading": 1.5, "unit": "ms", "confidence": 0.87})
        envelope = load_envelope(original, expect=_SCHEMA, supported=_READER_SUPPORTS)
        payload = ResultV1In.model_validate(envelope.payload)
        re_exported = dump_envelope(
            payload,
            schema=envelope.schema,
            version=envelope.version,
            generator=envelope.generator,
            generated_at=envelope.generated_at,
        )
        assert re_exported == original
        assert json.loads(re_exported)["payload"]["confidence"] == 0.87

    def test_a_writer_cannot_emit_a_field_it_does_not_know(self) -> None:
        """The other half of rule 4: writers stay strict, so exports never carry stray fields."""
        with pytest.raises(Exception, match="[Ee]xtra"):
            ResultV1Out.model_validate({"reading": 1.5, "unit": "ms", "confidence": 0.87})

    def test_the_round_trip_contract_holds_per_class(self, generator: GeneratorInfo) -> None:
        """`load(dump(x)) == x` is asserted per class, never across the Out/In pair (spec §11.3)."""
        strict = ResultV1Out.model_validate({"reading": 1.5, "unit": "ms"})
        assert ResultV1Out.model_validate(json.loads(canonical_dumps(strict))) == strict

        preserving = ResultV1In.model_validate({"reading": 1.5, "unit": "ms", "confidence": 0.87})
        assert ResultV1In.model_validate(json.loads(canonical_dumps(preserving))) == preserving


class TestNegotiationInputs:
    """Negotiation happens after the document is known to be well formed."""

    def test_a_malformed_document_fails_validation_not_negotiation(self) -> None:
        with pytest.raises(ValidationError):
            load_envelope("{not json", expect=_SCHEMA, supported=_READER_SUPPORTS)

    def test_an_unparsable_declared_version_is_a_validation_failure(
        self, generator: GeneratorInfo
    ) -> None:
        document = json.loads(_document(generator, "1.0", {"reading": 1.5, "unit": "ms"}))
        document["schema_version"] = "1.0.0"
        with pytest.raises(ValidationError):
            load_envelope(document, expect=_SCHEMA, supported=_READER_SUPPORTS)
