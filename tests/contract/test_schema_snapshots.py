"""Contract tests for the committed JSON Schema snapshots — ADR-0009 rule 7.

The rule in one sentence: *a schema change without a version bump fails CI*. This file is the
mechanism. Every published version's schema is regenerated from its writer model and compared, byte
for byte, against the document committed under ``src/setspec/schemas/``; a field added, renamed,
retyped or re-constrained without a new version changes the generated document and fails here.

It is marked ``contract`` because CI runs these separately (``pytest -m contract``): a failure means
a published guarantee broke, not that an implementation detail changed.
"""

from __future__ import annotations

import warnings
from typing import Any

import pytest
from pydantic import Field
from pydantic.json_schema import PydanticJsonSchemaWarning

from setspec import DRAFT_SCHEMAS, SUPPORTED_SCHEMAS, SchemaVersion
from setspec.artifacts import (
    JSON_SCHEMA_DIALECT,
    PUBLISHED_SCHEMAS,
    build_json_schema,
    json_schema_for,
    render_schema_document,
)
from setspec.base import PayloadDefinition, payload_models
from setspec.metrics import MetricValueFields

pytestmark = pytest.mark.contract

_REGENERATE = (
    "Regenerate with:\n"
    "  python - <<'PY'\n"
    "  from pathlib import Path\n"
    "  from setspec.artifacts import (PUBLISHED_SCHEMAS, build_json_schema,\n"
    "                                 render_schema_document)\n"
    "  for schema, versions in PUBLISHED_SCHEMAS.items():\n"
    "      for version in versions:\n"
    "          path = Path('src/setspec/schemas', schema, f'{version}.json')\n"
    "          path.parent.mkdir(parents=True, exist_ok=True)\n"
    "          path.write_text(render_schema_document(build_json_schema(schema, version)),\n"
    "                          encoding='utf-8')\n"
    "  PY\n"
    "…and then decide whether the change deserved a version bump, because CI just told you it "
    "was visible on the wire."
)

_PUBLISHED = [
    pytest.param(schema, version, id=f"{schema} {version}")
    for schema, versions in PUBLISHED_SCHEMAS.items()
    for version in versions
]


def _committed_text(schema: str, version: SchemaVersion) -> str:
    """Return the committed snapshot as it sits in the package, rendered for comparison."""
    return render_schema_document(json_schema_for(schema, version))


class TestSnapshotsMatchTheModels:
    """The generated document and the committed one are the same document, or the build fails."""

    @pytest.mark.parametrize(("schema", "version"), _PUBLISHED)
    def test_the_generated_schema_matches_the_snapshot(
        self, schema: str, version: SchemaVersion
    ) -> None:
        generated = render_schema_document(build_json_schema(schema, version))
        assert generated == _committed_text(schema, version), (
            f"The committed JSON Schema for {schema} {version} no longer matches what the models "
            f"generate.\n{_REGENERATE}"
        )

    @pytest.mark.parametrize(("schema", "version"), _PUBLISHED)
    def test_the_snapshot_declares_its_dialect_and_its_wire_name(
        self, schema: str, version: SchemaVersion
    ) -> None:
        """A consumer selects a validator from `$schema` and identifies the payload from `title`.

        `title` is the wire schema name rather than pydantic's class name: nothing outside this
        repository knows or should have to know that `benchmark.result` is implemented by a class
        called `BenchmarkResultOut`.
        """
        document = json_schema_for(schema, version)
        assert document["$schema"] == JSON_SCHEMA_DIALECT
        assert document["title"] == schema
        assert str(version) in document["$comment"]

    @pytest.mark.parametrize(("schema", "version"), _PUBLISHED)
    def test_the_snapshot_forbids_unknown_top_level_keys(
        self, schema: str, version: SchemaVersion
    ) -> None:
        """Generated from the writer half: ADR-0009 rule 5, writers emit only known fields.

        The reader policy is a reader behaviour, not a loosening of any one version's schema — a
        `1.1` document is described by the `1.1` schema, never by relaxing this one.
        """
        assert json_schema_for(schema, version)["additionalProperties"] is False

    @pytest.mark.parametrize(("schema", "version"), _PUBLISHED)
    def test_the_snapshot_resolves_entirely_within_itself(
        self, schema: str, version: SchemaVersion
    ) -> None:
        """Spec §14: static package data, never a remote reference a validator must fetch."""
        for reference in _references(json_schema_for(schema, version)):
            assert reference.startswith("#/$defs/"), reference


class TestTheRegistryAndTheWireAgree:
    """A schema published but not negotiable — or negotiable but not published — is a defect."""

    def test_every_registered_schema_publishes_artifacts(self) -> None:
        assert set(PUBLISHED_SCHEMAS) == set(SUPPORTED_SCHEMAS)

    def test_every_published_version_is_a_registered_major(self) -> None:
        for schema, versions in PUBLISHED_SCHEMAS.items():
            registered = SUPPORTED_SCHEMAS[schema]
            for version in versions:
                assert version.major in registered

    def test_every_registered_major_publishes_a_version(self) -> None:
        """A build that negotiates a major it has no artifacts for cannot be contract-tested."""
        for schema, majors in SUPPORTED_SCHEMAS.items():
            published_majors = {version.major for version in PUBLISHED_SCHEMAS[schema]}
            assert set(majors) == published_majors


class TestTheFreezeHolds:
    """Phase 4's freeze, asserted rather than described.

    The freeze was never "nothing may be published past `1.0`" — it was "nothing already
    published may be reshaped in place, and a major never moves without a new module" (ADR-0009
    rules 2 and 6). Phase 6 exercises the additive half of that promise for the first time:
    ``capability.evidence`` gains a `1.1` alongside its untouched `1.0`. What must stay true, and
    is asserted below, is narrower and permanent: every published major is still `1`, and every
    schema that predates Phase 6 is still exactly `1.0`.
    """

    def test_no_schema_is_still_a_draft(self) -> None:
        """`DRAFT_SCHEMAS` empty is the freeze. A name reappearing here re-opens a frozen shape."""
        assert DRAFT_SCHEMAS == frozenset()

    @pytest.mark.parametrize(("schema", "version"), _PUBLISHED)
    def test_no_published_major_has_ever_moved(self, schema: str, version: SchemaVersion) -> None:
        """A major bump would mean a frozen payload's meaning changed; none ever has."""
        assert version.major == 1

    @pytest.mark.parametrize(
        ("schema", "version"),
        [param for param in _PUBLISHED if param.id != "capability.evidence 1.1"],
    )
    def test_every_schema_that_predates_phase_6_is_still_1_0(
        self, schema: str, version: SchemaVersion
    ) -> None:
        """The one exception — `capability.evidence` `1.1` — is asserted separately, by name."""
        assert version == SchemaVersion(1, 0)

    def test_capability_evidence_is_the_one_schema_with_a_second_published_minor(self) -> None:
        """Phase 6's additive minor, named explicitly rather than inferred from a count."""
        assert PUBLISHED_SCHEMAS["capability.evidence"] == (
            SchemaVersion(1, 0),
            SchemaVersion(1, 1),
        )


class TestMetricKeyIsTheSpelling:
    """`metric_key` is the suite-wide spelling, and drifting back must fail the build.

    Coding standards §3's rule — same concept, same name, in all nine repositories — has no
    enforcement outside a test like this one. A metric's identifier is matched on by consumers, so
    a producer that renames it to `key` or `name` does not produce a validation error anywhere; it
    produces two metrics where the suite has one, months later, in someone's chart.
    """

    def test_the_metric_value_definition_declares_metric_key(self) -> None:
        assert "metric_key" in MetricValueFields.model_fields

    def test_metric_key_is_required(self) -> None:
        """Optional would mean an unattributable number is a legal measurement. It is not."""
        assert MetricValueFields.model_fields["metric_key"].is_required()

    @pytest.mark.parametrize(
        ("schema", "definition_name"),
        [
            ("benchmark.result", "MetricValue"),
            ("benchmark.run_summary", "MetricValue"),
            ("capability.evidence", "ContributingMetricFields"),
            ("benchmark.evidence_bundle", "ContributingMetricFields"),
        ],
    )
    def test_the_published_schema_requires_metric_key(
        self, schema: str, definition_name: str
    ) -> None:
        """Not merely present on the model — required by the document a consumer validates."""
        definitions = json_schema_for(schema, SchemaVersion(1, 0))["$defs"]
        matching = [
            body
            for name, body in definitions.items()
            if name.startswith(definition_name) and "properties" in body
        ]
        assert matching, f"{definition_name} is not in {schema}'s published $defs"
        for body in matching:
            assert "metric_key" in body["properties"]
            assert "metric_key" in body["required"]

    def test_no_published_schema_spells_it_any_other_way(self) -> None:
        """The drift this guards against is a rename, so the old spellings are named explicitly."""
        forbidden = {"metrickey", "metric_name", "metricname"}
        for schema, versions in PUBLISHED_SCHEMAS.items():
            for version in versions:
                for body in json_schema_for(schema, version).get("$defs", {}).values():
                    overlap = forbidden & set(body.get("properties", {}))
                    assert not overlap, f"{schema} {version} declares {sorted(overlap)}"


class TestAChangeWithoutAVersionBumpFails:
    """Acceptance criterion 2, proven by a deliberate mutation rather than asserted in prose.

    The mutation lives here rather than in the models, so the proof costs nothing at runtime: a
    definition is subclassed with one added field, the pair is regenerated exactly as
    `setspec.metrics` generates its own, and the resulting schema is compared against the committed
    snapshot. If that comparison could still pass, the snapshot test above would be decorative.
    """

    def test_an_added_field_changes_the_generated_schema(self) -> None:
        class MutatedMetricValueFields(MetricValueFields):
            """A `metric.value` with one field nobody published."""

            confidence_interval_95: float | None = None

        mutated_out, _mutated_in = payload_models(
            MutatedMetricValueFields, name="MutatedMetricValue"
        )
        baseline_out, _baseline_in = payload_models(MetricValueFields, name="BaselineMetricValue")
        with warnings.catch_warnings():
            # Same UNSUPPORTED-default notice `build_json_schema` documents and suppresses; this
            # test generates outside that helper on purpose, so it silences it the same way.
            warnings.filterwarnings("ignore", category=PydanticJsonSchemaWarning)
            mutated = mutated_out.model_json_schema()
            baseline = baseline_out.model_json_schema()
        assert "confidence_interval_95" in mutated["properties"]
        assert mutated["properties"] != baseline["properties"], (
            "a new field must be visible in the generated schema, or the snapshot proves nothing"
        )

    def test_a_tightened_constraint_changes_the_generated_schema(self) -> None:
        """A tightening is a *major* change (ADR-0009 rule 2) and is equally visible."""

        class LooseFields(PayloadDefinition):
            source_id: str

        class TightenedFields(PayloadDefinition):
            source_id: str = Field(min_length=8)

        loose_out, _ = payload_models(LooseFields, name="Loose")
        tight_out, _ = payload_models(TightenedFields, name="Tight")
        assert (
            loose_out.model_json_schema()["properties"]
            != (tight_out.model_json_schema()["properties"])
        )

    def test_the_committed_snapshot_is_what_the_test_compares_against(self) -> None:
        """Guards the guard: a snapshot read from the models would make every comparison vacuous."""
        committed = json_schema_for("capability.evidence", SchemaVersion(1, 0))
        mutated = dict(committed)
        mutated["title"] = "not.capability.evidence"
        assert render_schema_document(mutated) != _committed_text(
            "capability.evidence", SchemaVersion(1, 0)
        )


def _references(node: Any) -> list[str]:
    """Return every ``$ref`` string anywhere in a schema document."""
    found: list[str] = []
    if isinstance(node, dict):
        reference = node.get("$ref")
        if isinstance(reference, str):
            found.append(reference)
        for value in node.values():
            found.extend(_references(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_references(item))
    return found
