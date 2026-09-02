"""Cross-version compatibility, run over the published goldens rather than over a synthetic model.

[Testing standards §8.3](../../docs/standards/testing-standards.md) states the consumer's side of
the contract: *the consumer's test suite asserts that it can read every golden payload for every
supported major version, and that it rejects the next major with `SCHEMA_VERSION_UNSUPPORTED`.*
This file is that suite, written here so the promise is proven by the repository that makes it —
LoadCoach and FreeWeight then run the same two assertions against the same shipped files.

`tests/unit/test_version_negotiation.py` already exercises the policy against a purpose-built
model. The difference is what breaks each one: that file fails when the negotiation logic is wrong,
this one fails when a **published artifact** stops surviving the version gap it was published to
survive. A synthetic minor is built by adding a field to a real golden, which is exactly the shape
of the additive change ADR-0009 rule 2 permits without a major bump — so if a `1.0` reader ever
loses that field, a golden is what proves it.

Marked ``contract``.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from setspec import (
    SUPPORTED_SCHEMAS,
    GeneratorInfo,
    SchemaVersion,
    SchemaVersionUnsupported,
    canonical_dumps,
    dump_envelope,
    load_envelope,
)
from setspec.artifacts import PUBLISHED_SCHEMAS, golden_names, golden_payloads, payload_pair

pytestmark = pytest.mark.contract

_UNKNOWN_FIELD = "measured_under_moonlight"
"""A field no version of any payload declares, added to make a synthetic newer minor.

Deliberately absurd rather than plausible: a name like `notes` might one day be added for real,
and a test whose fixture collides with a future field fails for a reason that has nothing to do
with what it asserts.
"""

_EVERY_GOLDEN = [
    pytest.param(schema, version, name, id=f"{schema} {version} {name}")
    for schema, versions in PUBLISHED_SCHEMAS.items()
    for version in versions
    for name in golden_names(schema, version)
]

_ONE_GOLDEN_PER_SCHEMA = [
    pytest.param(schema, version, id=f"{schema} {version}")
    for schema, versions in PUBLISHED_SCHEMAS.items()
    for version in versions
]


def _first_golden(schema: str, version: SchemaVersion) -> dict[str, Any]:
    """Return the `full` golden — the one with the most surface for a version gap to damage."""
    documents = dict(
        zip(golden_names(schema, version), golden_payloads(schema, version), strict=True)
    )
    return documents["full"]


def _named_golden(schema: str, version: SchemaVersion, name: str) -> dict[str, Any]:
    documents = dict(
        zip(golden_names(schema, version), golden_payloads(schema, version), strict=True)
    )
    return documents[name]


def _synthetic(
    payload: dict[str, Any],
    *,
    schema: str,
    version: SchemaVersion,
    generator: GeneratorInfo,
) -> str:
    """Wrap a payload in an envelope declaring `version`, exactly as a future producer would."""
    return dump_envelope(payload, schema=schema, version=version, generator=generator)


class TestANewerMinorIsReadable:
    """ADR-0009 rule 3 over the shipped artifacts: additive means readable, not tolerated."""

    @pytest.mark.parametrize(("schema", "version"), _ONE_GOLDEN_PER_SCHEMA)
    def test_a_v1_1_document_is_accepted_by_this_build(
        self, schema: str, version: SchemaVersion, generator: GeneratorInfo
    ) -> None:
        newer = SchemaVersion(version.major, version.minor + 1)
        payload = {**_first_golden(schema, version), _UNKNOWN_FIELD: "not a field this build knows"}
        envelope = load_envelope(
            _synthetic(payload, schema=schema, version=newer, generator=generator),
            expect=schema,
        )
        assert envelope.version == newer

    @pytest.mark.parametrize(("schema", "version"), _ONE_GOLDEN_PER_SCHEMA)
    def test_the_reader_keeps_the_field_it_does_not_know(
        self, schema: str, version: SchemaVersion, generator: GeneratorInfo
    ) -> None:
        """Rule 4: preserved, not dropped — the difference between old and lossy."""
        newer = SchemaVersion(version.major, version.minor + 1)
        payload = {**_first_golden(schema, version), _UNKNOWN_FIELD: 42}
        envelope = load_envelope(
            _synthetic(payload, schema=schema, version=newer, generator=generator),
            expect=schema,
        )
        _writer, reader = payload_pair(schema, version)
        parsed = reader.model_validate(envelope.payload)
        assert parsed.extras[_UNKNOWN_FIELD] == 42

    @pytest.mark.parametrize(("schema", "version"), _ONE_GOLDEN_PER_SCHEMA)
    def test_a_re_export_by_this_build_loses_nothing(
        self, schema: str, version: SchemaVersion, generator: GeneratorInfo
    ) -> None:
        """The point of preservation: an old tool mid-pipeline is a relay, never a sink."""
        newer = SchemaVersion(version.major, version.minor + 1)
        payload = {**_first_golden(schema, version), _UNKNOWN_FIELD: {"nested": [1, 2, 3]}}
        envelope = load_envelope(
            _synthetic(payload, schema=schema, version=newer, generator=generator),
            expect=schema,
        )
        _writer, reader = payload_pair(schema, version)
        re_exported = json.loads(canonical_dumps(reader.model_validate(envelope.payload)))
        assert re_exported[_UNKNOWN_FIELD] == {"nested": [1, 2, 3]}

    @pytest.mark.parametrize(("schema", "version"), _ONE_GOLDEN_PER_SCHEMA)
    def test_the_writer_still_refuses_the_field(self, schema: str, version: SchemaVersion) -> None:
        """Rule 5 is unaffected by rule 4: this build may carry the key, never mint it."""
        writer, _reader = payload_pair(schema, version)
        payload = {**_first_golden(schema, version), _UNKNOWN_FIELD: True}
        with pytest.raises(ValueError, match=_UNKNOWN_FIELD):
            writer.model_validate(payload)


class TestANewerMajorIsRejected:
    """Rule 3's other half: never partially parsed, and the error names both versions."""

    @pytest.mark.parametrize(("schema", "version"), _ONE_GOLDEN_PER_SCHEMA)
    def test_a_v2_0_document_is_refused(
        self, schema: str, version: SchemaVersion, generator: GeneratorInfo
    ) -> None:
        next_major = SchemaVersion(version.major + 1, 0)
        document = _synthetic(
            _first_golden(schema, version),
            schema=schema,
            version=next_major,
            generator=generator,
        )
        with pytest.raises(SchemaVersionUnsupported) as raised:
            load_envelope(document, expect=schema)
        assert raised.value.details["schema"] == schema
        assert raised.value.details["received"] == str(next_major)
        # Named by SUPPORTED_SCHEMAS's recorded minor for this major, not by the specific
        # golden's own version: a major with more than one published version (capability.evidence
        # 1.0 and 1.1) still reports one "supported" entry per major (the highest known minor),
        # so a golden at an older minor is checked against that, not against itself.
        assert str(SUPPORTED_SCHEMAS[schema][version.major]) in raised.value.details["supported"]

    @pytest.mark.parametrize(("schema", "version"), _ONE_GOLDEN_PER_SCHEMA)
    def test_the_refusal_carries_the_documented_code(
        self, schema: str, version: SchemaVersion, generator: GeneratorInfo
    ) -> None:
        next_major = SchemaVersion(version.major + 1, 0)
        document = _synthetic(
            _first_golden(schema, version),
            schema=schema,
            version=next_major,
            generator=generator,
        )
        with pytest.raises(SchemaVersionUnsupported) as raised:
            load_envelope(document, expect=schema)
        assert raised.value.code == "SCHEMA_VERSION_UNSUPPORTED"


class TestEveryGoldenIsReadableAtItsOwnVersion:
    """The baseline the two cases above are measured against."""

    @pytest.mark.parametrize(("schema", "version", "name"), _EVERY_GOLDEN)
    def test_the_reader_accepts_it_through_the_envelope(
        self, schema: str, version: SchemaVersion, name: str, generator: GeneratorInfo
    ) -> None:
        document = _synthetic(
            _named_golden(schema, version, name),
            schema=schema,
            version=version,
            generator=generator,
        )
        envelope = load_envelope(document, expect=schema)
        _writer, reader = payload_pair(schema, version)
        assert reader.model_validate(envelope.payload).extras == {}

    @pytest.mark.parametrize(("schema", "version"), _ONE_GOLDEN_PER_SCHEMA)
    def test_the_build_negotiates_the_major_it_publishes(
        self, schema: str, version: SchemaVersion
    ) -> None:
        """A published version whose major is not registered is an artifact nobody can load."""
        assert version.major in SUPPORTED_SCHEMAS[schema]
