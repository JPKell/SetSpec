"""Contract module — the published schema artifacts: JSON Schema and golden payloads.

Imports pydantic and reads this package's own installed files; performs no network I/O and reads
no clock. Reading package data is the one filesystem access SetSpec makes, and it is deliberate:
[spec §14](../../docs/packages/setspec/spec.md) requires the JSON Schema documents to be *static
package data rather than remote references*, so a consumer validating an export never depends on a
registry being reachable — and ``$ref`` resolution never leaves the document.

[ADR-0009 rule 7](../../docs/adr/0009-schema-and-versioning-strategy.md) is the reason this module
exists: *each version publishes generated JSON Schema plus at least three golden payloads as
package data; contract tests in producers and consumers run against them; a schema change without
a version bump fails CI.* Everything below is the machinery for those three sentences.

**Generated from the writer half, deliberately.** ``build_json_schema`` renders the ``Out``
(``extra="forbid"``) model, not the ``In`` one, so the published document says
``additionalProperties: false`` at the top level. That is the contract
[API standards §7 rule 5](../../docs/standards/api-and-contract-standards.md) states — *writers
never emit unknown fields* — and
[testing standards §8.2](../../docs/standards/testing-standards.md) asks a producer's test suite
to prove exactly that against this schema. The reader policy (rule 2: accept an unknown minor,
unknown fields and all) is a **reader behaviour**, not a property of any one version's schema: a
``1.1`` document is described by the ``1.1`` schema, and a ``1.0`` reader accepts it because
:func:`~setspec.envelope.load_envelope` compares majors — never because the ``1.0`` schema was
loosened to admit fields it cannot describe.

**What the JSON Schema cannot say.** Pydantic renders types, ranges, patterns and required keys;
it cannot render a ``model_validator``. So ``runtime_profile_hash`` agreeing with its profile,
``score_method_mix`` summing to one, ``measured_at`` preceding ``computed_at`` and every other
cross-field rule are absent from the published document and enforced only by the models. This is
why :func:`golden_payloads` is checked against **both** — the schema catches a consumer's
structural mistake, the model catches an incoherent document — and why the catalogue in
``docs/packages/setspec/schemas.md`` names the gap rather than leaving a non-Python consumer to
discover it.
"""

from __future__ import annotations

import json
import warnings
from importlib import resources
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

from pydantic.json_schema import PydanticJsonSchemaWarning

from setspec.benchmark.v1 import (
    BenchmarkResultIn,
    BenchmarkResultOut,
    BenchmarkRunSummaryIn,
    BenchmarkRunSummaryOut,
)
from setspec.capability.v1 import (
    CapabilityEvidenceIn,
    CapabilityEvidenceOut,
    EvidenceBundleIn,
    EvidenceBundleOut,
)
from setspec.envelope import SchemaVersion
from setspec.errors import SchemaVersionUnsupported, ValidationError
from setspec.goal.v1 import (
    CalibrationReportIn,
    CalibrationReportOut,
    GoalPackIn,
    GoalPackOut,
)
from setspec.machine.v1 import MachineProfileIn, MachineProfileOut
from setspec.model.v1 import ModelIdentityIn, ModelIdentityOut

if TYPE_CHECKING:
    from collections.abc import Mapping

    from setspec.base import PayloadDefinition

__all__ = [
    "JSON_SCHEMA_DIALECT",
    "PUBLISHED_SCHEMAS",
    "SCHEMA_PACKAGE_DIR",
    "build_json_schema",
    "golden_names",
    "golden_payloads",
    "json_schema_for",
    "payload_pair",
    "render_schema_document",
]

SCHEMA_PACKAGE_DIR: Final[str] = "schemas"
"""Directory inside the installed package holding one JSON Schema per published version."""

GOLDEN_PACKAGE_DIR: Final[str] = "goldens"
"""Directory inside the installed package holding the golden payloads, one folder per version."""

JSON_SCHEMA_DIALECT: Final[str] = "https://json-schema.org/draft/2020-12/schema"
"""The dialect every published document declares.

A dialect identifier, not a fetch: a validator recognises the string and selects its 2020-12
implementation. Nothing in a published schema is a remote reference — every ``$ref`` resolves
inside the document's own ``$defs`` (spec §14).
"""

_VERSION_1_0: Final[SchemaVersion] = SchemaVersion(1, 0)

_REGISTRY: Final[
    Mapping[str, Mapping[SchemaVersion, tuple[type[PayloadDefinition], type[PayloadDefinition]]]]
] = MappingProxyType(
    {
        "model.identity": MappingProxyType({_VERSION_1_0: (ModelIdentityOut, ModelIdentityIn)}),
        "machine.profile": MappingProxyType({_VERSION_1_0: (MachineProfileOut, MachineProfileIn)}),
        "benchmark.result": MappingProxyType(
            {_VERSION_1_0: (BenchmarkResultOut, BenchmarkResultIn)}
        ),
        "benchmark.run_summary": MappingProxyType(
            {_VERSION_1_0: (BenchmarkRunSummaryOut, BenchmarkRunSummaryIn)}
        ),
        "capability.evidence": MappingProxyType(
            {_VERSION_1_0: (CapabilityEvidenceOut, CapabilityEvidenceIn)}
        ),
        "benchmark.evidence_bundle": MappingProxyType(
            {_VERSION_1_0: (EvidenceBundleOut, EvidenceBundleIn)}
        ),
        "benchmark.goal_pack": MappingProxyType({_VERSION_1_0: (GoalPackOut, GoalPackIn)}),
        "benchmark.calibration_report": MappingProxyType(
            {_VERSION_1_0: (CalibrationReportOut, CalibrationReportIn)}
        ),
    }
)
"""Every published version, mapped to the ``(Out, In)`` pair that defines it.

The single authoritative table this module works from. It is deliberately *not* derived from
:data:`~setspec.envelope.SUPPORTED_SCHEMAS`, which records supported **majors** rather than exact
versions and therefore cannot say which versions have committed artifacts; a contract test asserts
the two agree, so a schema registered for negotiation but never published — or published and never
registered — fails the build rather than being discovered by a consumer.
"""

PUBLISHED_SCHEMAS: Final[Mapping[str, tuple[SchemaVersion, ...]]] = MappingProxyType(
    {schema: tuple(sorted(versions)) for schema, versions in sorted(_REGISTRY.items())}
)
"""Every schema name with committed JSON Schema and goldens, and the versions each publishes.

Exact versions, unlike :data:`~setspec.envelope.SUPPORTED_SCHEMAS`: an artifact is a file that
either exists or does not, so "highest minor known" is the wrong shape for it. Iterate this to
regenerate the snapshots or to walk every version in a contract test.
"""


def payload_pair(
    schema: str, version: SchemaVersion
) -> tuple[type[PayloadDefinition], type[PayloadDefinition]]:
    """Return the ``(Out, In)`` model pair for one published payload version.

    Args:
        schema: The payload type name, e.g. ``"benchmark.result"``.
        version: The exact published version.

    Returns:
        The strict writer model and the preserving reader model, in that order — the order they
        are used in, matching :func:`~setspec.base.payload_models`.

    Raises:
        SchemaVersionUnsupported: If ``schema`` names no published payload type, or names one that
            publishes no such version. ``details["published"]`` lists what this build does have,
            which is the question a caller who guessed wrong is actually asking.
    """
    return _lookup(schema, version)


def build_json_schema(schema: str, version: SchemaVersion) -> dict[str, Any]:
    """Generate the JSON Schema for one published version from its writer model.

    The generated document, not the committed one: :func:`json_schema_for` reads what shipped.
    These two are compared by the snapshot contract test, which is what makes a schema change
    without a version bump a build failure (ADR-0009 rule 7).

    Args:
        schema: The payload type name.
        version: The exact published version.

    Returns:
        A fresh JSON Schema document. ``title`` is the wire schema name and ``$comment`` records
        the version, both overriding pydantic's class-derived defaults: a consumer reading
        ``benchmark.result`` should not have to know that the Python class implementing it is
        called ``BenchmarkResultOut``.

    Raises:
        SchemaVersionUnsupported: If ``schema`` or ``version`` is not published.
    """
    writer, _reader = _lookup(schema, version)
    with warnings.catch_warnings():
        # Every `MeasurementField` defaulting to UNSUPPORTED trips this: the sentinel is not JSON
        # serializable, so pydantic omits the field's `default` from the document and says so.
        # Omitting it is correct here and changes no validation outcome — `default` is an
        # annotation in JSON Schema, never a constraint — and the wire form of that default is
        # already visible in the field's own `anyOf` as `{"const": "unsupported"}`. Suppressed so
        # that generating a schema is silent; not suppressed anywhere else.
        warnings.filterwarnings("ignore", category=PydanticJsonSchemaWarning)
        generated = writer.model_json_schema()
    document: dict[str, Any] = {"$schema": JSON_SCHEMA_DIALECT, **generated}
    document["title"] = schema
    document["$comment"] = f"setspec {schema} {version} — generated from the writer model."
    return document


def render_schema_document(document: Mapping[str, Any]) -> str:
    """Render a schema document exactly as the committed snapshot stores it.

    Indented and key-sorted rather than canonical-compact, because this file is read by people in
    a review diff far more often than it is hashed. Sorting is what makes that diff mean
    something: pydantic's property order follows declaration order, so an unsorted snapshot would
    show a whole-file rewrite whenever a field moved.

    Args:
        document: The generated schema.

    Returns:
        UTF-8 text with a trailing newline, byte-identical for equal input.
    """
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def json_schema_for(schema: str, version: SchemaVersion) -> dict[str, Any]:
    """Return the committed JSON Schema for one published version.

    Reads the document that shipped in this wheel, so a consumer validating an export is validating
    against the artifact this build promised rather than against whatever the installed models
    happen to generate today.

    Args:
        schema: The payload type name, e.g. ``"capability.evidence"``.
        version: The exact published version.

    Returns:
        A fresh mapping each call — the caller owns it and may mutate it without corrupting the
        next caller's copy.

    Raises:
        SchemaVersionUnsupported: If ``schema`` or ``version`` is not published.
        ValidationError: If the committed file is missing or unparsable, which means the wheel was
            built without its package data.
    """
    _lookup(schema, version)
    text = _read_package_file(f"{SCHEMA_PACKAGE_DIR}/{schema}/{version}.json")
    parsed: dict[str, Any] = json.loads(text)
    return parsed


def golden_names(schema: str, version: SchemaVersion) -> tuple[str, ...]:
    """Return the file stems of the golden payloads committed for one published version.

    Args:
        schema: The payload type name.
        version: The exact published version.

    Returns:
        The stems in sorted order — the same order :func:`golden_payloads` returns its documents
        in, so the two zip together. A test that fails on the fourth golden can name it.

    Raises:
        SchemaVersionUnsupported: If ``schema`` or ``version`` is not published.
    """
    _lookup(schema, version)
    directory = resources.files("setspec") / GOLDEN_PACKAGE_DIR / schema / str(version)
    return tuple(
        sorted(
            entry.name.removesuffix(".json") for entry in directory.iterdir() if _is_golden(entry)
        )
    )


def golden_payloads(schema: str, version: SchemaVersion) -> list[dict[str, Any]]:
    """Return every golden payload committed for one published version.

    A golden is a **bare payload**, not an enveloped document: the envelope carries a
    ``generated_at`` that would have to be re-frozen on every release, and what a consumer's
    contract test needs to pin is the payload's shape. Wrap one with
    :func:`~setspec.envelope.dump_envelope` to get a file.

    Args:
        schema: The payload type name.
        version: The exact published version.

    Returns:
        The payloads, ordered by golden name, as fresh mappings the caller owns.

    Raises:
        SchemaVersionUnsupported: If ``schema`` or ``version`` is not published.
        ValidationError: If a committed golden is missing or unparsable.
    """
    return [_load_golden(schema, version, name) for name in golden_names(schema, version)]


def _load_golden(schema: str, version: SchemaVersion, name: str) -> dict[str, Any]:
    """Read and parse one golden by name."""
    text = _read_package_file(f"{GOLDEN_PACKAGE_DIR}/{schema}/{version}/{name}.json")
    parsed: dict[str, Any] = json.loads(text)
    return parsed


def _is_golden(entry: Any) -> bool:  # noqa: ANN401 — importlib.resources.Traversable
    """Report whether a package-data entry is a golden payload file."""
    return bool(entry.is_file()) and entry.name.endswith(".json")


def _lookup(
    schema: str, version: SchemaVersion
) -> tuple[type[PayloadDefinition], type[PayloadDefinition]]:
    """Return the model pair for a published version, or explain what is published instead."""
    versions = _REGISTRY.get(schema)
    if versions is None or version not in versions:
        published = [
            f"{name} {candidate}"
            for name, candidates in PUBLISHED_SCHEMAS.items()
            for candidate in candidates
        ]
        raise SchemaVersionUnsupported(
            f"No published artifacts for {schema!r} version {version}. This build publishes "
            f"JSON Schema and goldens for: {', '.join(published)}.",
            details={
                "schema": schema,
                "received": str(version),
                "supported": [str(candidate) for candidate in versions] if versions else [],
                "published": published,
            },
        )
    return versions[version]


def _read_package_file(relative_path: str) -> str:
    """Read one package-data file, naming the wheel as the suspect when it is not there."""
    target = resources.files("setspec")
    for part in relative_path.split("/"):
        target = target / part
    try:
        return target.read_text(encoding="utf-8")
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise ValidationError(
            f"Package data {relative_path!r} is missing from the installed setspec. The schemas "
            "and goldens ship as package data (ADR-0009 rule 7); a wheel without them was built "
            "with the wrong include rules, and the install-check CI job exists to catch that "
            "before it reaches an index.",
            details={"path": relative_path},
        ) from exc
