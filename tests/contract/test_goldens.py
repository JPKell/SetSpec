"""Contract tests for the golden payloads — ADR-0009 rule 7, the consumer's half.

A golden is the artifact that makes cross-repository compatibility testable *without a shared
environment* ([testing standards §8](../../docs/standards/testing-standards.md)): LoadCoach's
contract tests read these files out of the installed `setspec` wheel and never import FreeWeight,
never open a database, and never run a benchmark.

Each golden is checked three ways, because each catches something the others cannot:

* against the **writer model**, which enforces every cross-field rule pydantic can express and
  JSON Schema cannot — a `runtime_profile_hash` that disagrees with its profile, a
  `score_method_mix` that does not sum to one;
* against the **published JSON Schema**, which is what a non-Python consumer actually validates
  with, and which would silently pass a golden the models happen to accept for a reason the
  document never states;
* through a **canonical round trip**, because a golden that does not survive load → dump is a
  golden that will start failing on a pydantic upgrade rather than on a real contract change.

Marked ``contract``: a failure here means a published artifact broke.
"""

from __future__ import annotations

import json
from importlib import resources
from typing import Any

import jsonschema
import pytest
from baseaicore import ValidationError

from setspec import (
    SchemaVersion,
    SchemaVersionUnsupported,
    artifacts,
    canonical_dumps,
    dump_envelope,
    load_envelope,
)
from setspec.artifacts import (
    GOLDEN_PACKAGE_DIR,
    PUBLISHED_SCHEMAS,
    SCHEMA_PACKAGE_DIR,
    golden_names,
    golden_payloads,
    json_schema_for,
    payload_pair,
)
from setspec.capability.v1 import EvidenceBundleIn

pytestmark = pytest.mark.contract

_MINIMUM_GOLDENS_PER_VERSION = 3
_UNSUPPORTED_MARKER = {"const": "unsupported"}

_PUBLISHED = [
    pytest.param(schema, version, id=f"{schema} {version}")
    for schema, versions in PUBLISHED_SCHEMAS.items()
    for version in versions
]

_EVERY_GOLDEN = [
    pytest.param(schema, version, name, id=f"{schema} {version} {name}")
    for schema, versions in PUBLISHED_SCHEMAS.items()
    for version in versions
    for name in golden_names(schema, version)
]


def _golden(schema: str, version: SchemaVersion, name: str) -> dict[str, Any]:
    """Return one golden by name, from the same accessor a consumer would use."""
    documents = dict(
        zip(golden_names(schema, version), golden_payloads(schema, version), strict=True)
    )
    return documents[name]


class TestEveryVersionPublishesEnoughGoldens:
    """Three per version is the floor ADR-0009 rule 7 sets, and the shapes are named."""

    @pytest.mark.parametrize(("schema", "version"), _PUBLISHED)
    def test_at_least_three_goldens_exist(self, schema: str, version: SchemaVersion) -> None:
        assert len(golden_names(schema, version)) >= _MINIMUM_GOLDENS_PER_VERSION

    @pytest.mark.parametrize(("schema", "version"), _PUBLISHED)
    def test_a_minimal_and_a_full_example_exist(self, schema: str, version: SchemaVersion) -> None:
        """The two ends of the range: only required fields, and every field populated."""
        names = golden_names(schema, version)
        assert "minimal" in names
        assert "full" in names

    @pytest.mark.parametrize(("schema", "version"), _PUBLISHED)
    def test_a_payload_carrying_measurements_has_an_unsupported_heavy_example(
        self, schema: str, version: SchemaVersion
    ) -> None:
        """`unsupported` is the value most likely to be mishandled, so it is exercised by name.

        Which payloads need one is derived from the published schema rather than listed here: a
        payload whose document contains no `{"const": "unsupported"}` branch has no measurement
        field to leave unsupported, and demanding a golden for a state it cannot reach would be a
        test asserting its own list.
        """
        if _UNSUPPORTED_MARKER not in _constants(json_schema_for(schema, version)):
            pytest.skip(f"{schema} {version} carries no measurement field")
        assert "unsupported" in golden_names(schema, version)

    @pytest.mark.parametrize(("schema", "version"), _PUBLISHED)
    def test_the_minimal_golden_is_actually_smaller_than_the_full_one(
        self, schema: str, version: SchemaVersion
    ) -> None:
        """Otherwise "minimal" is a name rather than a case, and the range is untested.

        Compared by serialized size, not top-level key count: a payload whose every top-level
        field is required (``governance.egress_decision``, whose optional fields all sit one
        level down, inside ``target``) has the same key count either way, and a key-count
        comparison would report no difference where a real one exists.
        """
        minimal = _golden(schema, version, "minimal")
        full = _golden(schema, version, "full")
        assert len(json.dumps(minimal)) < len(json.dumps(full))


class TestEveryGoldenValidates:
    """The three checks, one test each, against every committed golden."""

    @pytest.mark.parametrize(("schema", "version", "name"), _EVERY_GOLDEN)
    def test_the_writer_model_accepts_it(
        self, schema: str, version: SchemaVersion, name: str
    ) -> None:
        """Strict: a golden with a stray key is a golden that teaches consumers a wrong shape."""
        writer, _reader = payload_pair(schema, version)
        writer.model_validate(_golden(schema, version, name))

    @pytest.mark.parametrize(("schema", "version", "name"), _EVERY_GOLDEN)
    def test_the_reader_model_accepts_it(
        self, schema: str, version: SchemaVersion, name: str
    ) -> None:
        _writer, reader = payload_pair(schema, version)
        parsed = reader.model_validate(_golden(schema, version, name))
        assert parsed.extras == {}, "a golden has no unknown keys — it defines what is known"

    @pytest.mark.parametrize(("schema", "version", "name"), _EVERY_GOLDEN)
    def test_the_published_json_schema_accepts_it(
        self, schema: str, version: SchemaVersion, name: str
    ) -> None:
        """The check a non-Python consumer performs, run against the same file they receive."""
        jsonschema.validate(
            instance=_golden(schema, version, name),
            schema=json_schema_for(schema, version),
        )

    @pytest.mark.parametrize(("schema", "version", "name"), _EVERY_GOLDEN)
    def test_it_survives_a_canonical_round_trip(
        self, schema: str, version: SchemaVersion, name: str
    ) -> None:
        """Spec §11.3: `load(dump(x)) == x`, asserted per class over the shipped documents."""
        _writer, reader = payload_pair(schema, version)
        document = _golden(schema, version, name)
        parsed = reader.model_validate(document)
        reparsed = reader.model_validate(json.loads(canonical_dumps(parsed)))
        assert reparsed == parsed

    @pytest.mark.parametrize(("schema", "version", "name"), _EVERY_GOLDEN)
    def test_it_survives_an_envelope_round_trip(
        self, schema: str, version: SchemaVersion, name: str, generator: Any
    ) -> None:
        """A golden is a payload; this is the file a producer actually writes around it."""
        _writer, reader = payload_pair(schema, version)
        document = _golden(schema, version, name)
        text = dump_envelope(
            reader.model_validate(document),
            schema=schema,
            version=version,
            generator=generator,
        )
        envelope = load_envelope(text, expect=schema)
        assert envelope.version == version
        assert reader.model_validate(envelope.payload) == reader.model_validate(document)


class TestGoldensAreStableArtifacts:
    """A golden that drifts silently is worse than no golden: consumers pin against it."""

    @pytest.mark.parametrize(("schema", "version", "name"), _EVERY_GOLDEN)
    def test_reading_a_golden_twice_yields_equal_documents(
        self, schema: str, version: SchemaVersion, name: str
    ) -> None:
        assert _golden(schema, version, name) == _golden(schema, version, name)

    @pytest.mark.parametrize(("schema", "version", "name"), _EVERY_GOLDEN)
    def test_the_caller_owns_what_it_is_handed(
        self, schema: str, version: SchemaVersion, name: str
    ) -> None:
        """A shared mutable document is one caller's bug appearing in another caller's test."""
        first = _golden(schema, version, name)
        first["a_key_no_schema_declares"] = True
        assert "a_key_no_schema_declares" not in _golden(schema, version, name)

    @pytest.mark.parametrize(("schema", "version"), _PUBLISHED)
    def test_golden_names_and_payloads_are_returned_in_the_same_order(
        self, schema: str, version: SchemaVersion
    ) -> None:
        names = golden_names(schema, version)
        payloads = golden_payloads(schema, version)
        assert len(names) == len(payloads)

    @pytest.mark.parametrize(("schema", "version"), _PUBLISHED)
    def test_every_golden_file_on_disk_is_reachable_through_the_accessor(
        self, schema: str, version: SchemaVersion
    ) -> None:
        """An unreachable golden is a file nobody validates and everybody copies from."""
        directory = resources.files("setspec") / GOLDEN_PACKAGE_DIR / schema / str(version)
        on_disk = sorted(
            entry.name.removesuffix(".json")
            for entry in directory.iterdir()
            if entry.name.endswith(".json")
        )
        assert on_disk == sorted(golden_names(schema, version))


class TestPackageDataIsLoadable:
    """Both artifact families reach a consumer through `importlib.resources`, or they reach nobody.

    The wheel half of this is the `install-check` CI job, which installs the built distribution into
    a clean interpreter and asserts the same two directories are there. This half proves the
    *accessor* works; that half proves the *build* includes them, and a missing `include` rule
    fails only the second.
    """

    @pytest.mark.parametrize(("schema", "version"), _PUBLISHED)
    def test_the_schema_file_is_package_data(self, schema: str, version: SchemaVersion) -> None:
        target = resources.files("setspec") / SCHEMA_PACKAGE_DIR / schema / f"{version}.json"
        assert target.is_file()
        assert json.loads(target.read_text(encoding="utf-8"))["title"] == schema

    @pytest.mark.parametrize(("schema", "version"), _PUBLISHED)
    def test_the_goldens_are_package_data(self, schema: str, version: SchemaVersion) -> None:
        directory = resources.files("setspec") / GOLDEN_PACKAGE_DIR / schema / str(version)
        assert directory.is_dir()

    def test_a_consumer_needs_only_setspec_to_read_a_bundle(self) -> None:
        """Spec §20 criterion 1, in miniature: no FreeWeight, no database, no run.

        The full exit condition is FreeWeight's own export read by a `setspec`-only harness; this
        is the part SetSpec can prove on its own, and it is the part that fails first if the
        artifacts stop shipping.
        """
        bundle = _golden("benchmark.evidence_bundle", SchemaVersion(1, 0), "full")
        parsed = EvidenceBundleIn.model_validate(bundle)
        capability_ids = [record.capability_id for record in parsed.evidence]
        assert "user.noir_tech_voice" in capability_ids


class TestAskingForSomethingUnpublished:
    """The accessors answer "what does this build actually have", never an empty result."""

    def test_an_unknown_schema_names_what_is_published(self) -> None:
        with pytest.raises(SchemaVersionUnsupported) as raised:
            json_schema_for("routing.decision", SchemaVersion(1, 0))
        assert raised.value.details["schema"] == "routing.decision"
        assert "capability.evidence 1.0" in raised.value.details["published"]

    def test_an_unpublished_version_of_a_known_schema_names_the_published_ones(self) -> None:
        """The likeliest mistake: a consumer that upgraded its pin ahead of the package."""
        with pytest.raises(SchemaVersionUnsupported) as raised:
            payload_pair("benchmark.result", SchemaVersion(2, 0))
        assert raised.value.details["received"] == "2.0"
        assert raised.value.details["supported"] == ["1.0"]

    def test_goldens_for_an_unpublished_version_are_refused_the_same_way(self) -> None:
        with pytest.raises(SchemaVersionUnsupported):
            golden_payloads("benchmark.goal_pack", SchemaVersion(1, 1))

    def test_a_registered_schema_whose_file_is_missing_blames_the_wheel(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The failure mode Phase 4 names: package data left out of the build.

        Simulated by registering a payload type with no committed artifacts, because the real
        version of this — a wheel built with the wrong include rules — cannot be produced from
        inside the installed package it would be missing from.
        """
        version = SchemaVersion(1, 0)
        writer, reader = payload_pair("benchmark.goal_pack", version)
        monkeypatch.setattr(
            artifacts,
            "_REGISTRY",
            {**artifacts._REGISTRY, "ghost.payload": {version: (writer, reader)}},
        )
        with pytest.raises(ValidationError, match="missing from the installed setspec"):
            json_schema_for("ghost.payload", version)


def _constants(node: Any) -> list[dict[str, Any]]:
    """Return every ``{"const": …}`` object anywhere in a schema document."""
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        if set(node) == {"const"}:
            found.append(node)
        for value in node.values():
            found.extend(_constants(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_constants(item))
    return found
