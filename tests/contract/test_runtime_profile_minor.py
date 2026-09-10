"""``benchmark.result`` and ``benchmark.run_summary`` `1.1` — row WA1's additive proof and limit.

ADR-0135. Three claims, over the committed goldens:

1. **Today's `1.0` goldens, unchanged on disk, dump byte-identically through the `1.1` writers** —
   I15's analogue for the runtime profile. If one moved, the minor was not additive, and that is a
   stop, not a golden to update.
2. **The `1.1` goldens cover the field's three states** — ``minimal`` unstated, ``unsupported``
   ``false``, ``full`` ``true`` — each with the hash BaseAiCore computes for its profile.
3. **A `1.0` reader accepts an unstated `1.1` document and refuses a stated one.** The limit
   ADR-0135 rule 2 names, asserted so that it cannot change in either direction unnoticed.

Marked ``contract``.
"""

from __future__ import annotations

import json
from importlib import resources
from typing import Any

import pytest
from baseaicore import RuntimeProfile
from pydantic import ValidationError as PydanticValidationError

from setspec import SchemaVersion, canonical_dumps
from setspec.artifacts import golden_names, golden_payloads, payload_pair

pytestmark = pytest.mark.contract

_V1_0 = SchemaVersion(1, 0)
_V1_1 = SchemaVersion(1, 1)
_SCHEMAS = ("benchmark.result", "benchmark.run_summary")
_STATES: dict[str, bool | None] = {"minimal": None, "unsupported": False, "full": True}
_STATED = ("unsupported", "full")


def _goldens(schema: str, version: SchemaVersion) -> dict[str, dict[str, Any]]:
    """Every golden of one version, by name."""
    return dict(zip(golden_names(schema, version), golden_payloads(schema, version), strict=True))


@pytest.mark.parametrize("schema", _SCHEMAS)
@pytest.mark.parametrize("name", list(_STATES))
class TestTodaysGoldensDoNotMove:
    """Claim 1: no committed `1.0` golden's canonical bytes may move."""

    def test_a_1_0_golden_dumped_through_the_1_1_writer_is_byte_identical(
        self, schema: str, name: str
    ) -> None:
        document = _goldens(schema, _V1_0)[name]
        writer_1_0, _ = payload_pair(schema, _V1_0)
        writer_1_1, _ = payload_pair(schema, _V1_1)
        assert canonical_dumps(writer_1_0.model_validate(document)) == canonical_dumps(
            writer_1_1.model_validate(document)
        )

    def test_a_1_0_golden_file_on_disk_does_not_state_the_field(
        self, schema: str, name: str
    ) -> None:
        text = (
            resources.files("setspec")
            .joinpath("goldens", schema, "1.0", f"{name}.json")
            .read_text(encoding="utf-8")
        )
        assert "adapters_registered" not in text


@pytest.mark.parametrize("schema", _SCHEMAS)
class TestThe1_1GoldensCoverTheThreeStates:
    """Claim 2: one golden per state, each hash computed by BaseAiCore, never by hand."""

    def test_each_golden_states_the_field_as_its_name_says(self, schema: str) -> None:
        goldens = _goldens(schema, _V1_1)
        assert "adapters_registered" not in goldens["minimal"]["runtime_profile"]
        for name in _STATED:
            assert goldens[name]["runtime_profile"]["adapters_registered"] is _STATES[name]

    @pytest.mark.parametrize("name", list(_STATES))
    def test_its_hash_is_what_baseaicore_computes(self, schema: str, name: str) -> None:
        document = _goldens(schema, _V1_1)[name]
        profile = RuntimeProfile(**document["runtime_profile"])
        assert document["runtime_profile_hash"] == profile.profile_hash


@pytest.mark.parametrize("schema", _SCHEMAS)
class TestA1_0ReaderAtTheLimit:
    """Claim 3: ADR-0135 rule 2, both halves."""

    def test_it_accepts_a_1_1_document_that_leaves_the_field_unstated(self, schema: str) -> None:
        _, reader_1_0 = payload_pair(schema, _V1_0)
        reader_1_0.model_validate(_goldens(schema, _V1_1)["minimal"])

    @pytest.mark.parametrize("name", _STATED)
    def test_it_refuses_a_1_1_document_that_states_the_field(self, schema: str, name: str) -> None:
        _, reader_1_0 = payload_pair(schema, _V1_0)
        with pytest.raises(PydanticValidationError, match="runtime_profile_hash"):
            reader_1_0.model_validate(_goldens(schema, _V1_1)[name])

    @pytest.mark.parametrize("name", _STATED)
    def test_the_1_1_reader_accepts_it_and_keeps_the_field_through_a_round_trip(
        self, schema: str, name: str
    ) -> None:
        _, reader_1_1 = payload_pair(schema, _V1_1)
        parsed = reader_1_1.model_validate(_goldens(schema, _V1_1)[name])
        assert parsed.model_dump()["runtime_profile"]["adapters_registered"] is _STATES[name]
        assert reader_1_1.model_validate(json.loads(canonical_dumps(parsed))) == parsed
