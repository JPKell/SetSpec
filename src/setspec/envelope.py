"""Contract module — the schema envelope, version parsing and the reader policy.

Imports pydantic and :mod:`baseaicore`; performs no I/O. Reads a clock only through the injected
``clock`` parameter of :func:`dump_envelope`, never by calling :func:`~datetime.datetime.now`
directly (coding standards §5).

The envelope marks a document that outlives the request that produced it — an export, an evidence
bundle, a result, an event. An HTTP API's own request and response bodies are *not* enveloped;
they are versioned by their path and documented by OpenAPI. That boundary, and the membership test
for it, is ADR-0025; the envelope's own shape and the
reader policy are ADR-0009.

The reader policy is one sentence with two halves, and both halves matter:

* A **newer minor** within a supported major is accepted, unknown fields and all. Minor means
  additive, so a v1.0 reader can read a v1.1 document without knowing what was added.
* An **unsupported major** is rejected outright, never partially parsed. Major means a field
  changed meaning, so reading "the parts we recognise" would produce confident nonsense — the one
  outcome worse than refusing to read at all.
"""

from __future__ import annotations

import re
import warnings
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final, Self

from baseaicore import Clock, ValidationError, utc_now
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from setspec.base import PreservingPayload
from setspec.errors import SchemaVersionUnsupported
from setspec.serialization import (
    MAX_PAYLOAD_BYTES,
    MAX_PAYLOAD_DEPTH,
    TimestampField,
    canonical_dumps,
    parse_json,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import datetime

__all__ = [
    "DRAFT_SCHEMAS",
    "SUPPORTED_SCHEMAS",
    "GeneratorInfo",
    "SchemaEnvelope",
    "SchemaVersion",
    "dump_envelope",
    "load_envelope",
]

_VERSION_PATTERN: Final[re.Pattern[str]] = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_SCHEMA_NAME_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")


@dataclass(frozen=True, slots=True, order=True)
class SchemaVersion:
    """A payload type's ``MAJOR.MINOR`` version.

    Two numbers, no patch component. A patch has no meaning for a data contract — either the shape
    changed or it did not — and offering one would invite writers to record a change that readers
    cannot act on (ADR-0009, rejected
    alternatives).

    Ordering is by major then minor, so versions sort and compare as a reader expects. Ordering is
    *not* the compatibility test: a higher version is not necessarily readable, and
    :func:`load_envelope` decides acceptance by major, never by comparison.

    Attributes:
        major: Incremented by a breaking change — a removed or renamed field, a changed type or
            meaning, or tightened validation. Starts at 1; a published schema has no 0.x phase.
        minor: Incremented by an additive change — a new optional field. Reset to 0 on a major
            bump.
    """

    major: int
    minor: int

    def __post_init__(self) -> None:
        """Reject versions that cannot appear on the wire.

        Raises:
            ValidationError: If ``major`` is below 1 or ``minor`` is negative.
        """
        if self.major < 1:
            raise ValidationError(
                f"Schema major version must be at least 1; got {self.major}. Version 1.0 is where "
                "a published payload type starts — there is no 0.x phase for a wire contract, "
                "because a consumer cannot pin against a shape that admits it is provisional.",
                details={"field": "major", "value": self.major},
            )
        if self.minor < 0:
            raise ValidationError(
                f"Schema minor version cannot be negative; got {self.minor}.",
                details={"field": "minor", "value": self.minor},
            )

    @classmethod
    def parse(cls, text: str) -> Self:
        """Parse a ``"MAJOR.MINOR"`` string.

        Only the canonical spelling is accepted: no leading zeros, no third component, no ``v``
        prefix, no whitespace. The strictness buys byte-stability — ``"1.00"`` and ``"1.0"`` would
        parse to the same version but re-serialize to one form, so a document that used the other
        would not survive a load/dump round trip unchanged (spec §11.3, §11.4).

        Args:
            text: The version string, e.g. ``"1.0"``.

        Returns:
            The parsed version.

        Raises:
            ValidationError: If ``text`` is not a canonical ``MAJOR.MINOR`` string, or names a
                major below 1.
        """
        match = _VERSION_PATTERN.fullmatch(text)
        if match is None:
            raise ValidationError(
                f"Not a canonical schema version: {text!r}. Expected exactly 'MAJOR.MINOR' with "
                "no leading zeros, no patch component and no 'v' prefix — for example '1.0'.",
                details={"field": "schema_version", "value": text},
            )
        return cls(major=int(match.group(1)), minor=int(match.group(2)))

    def __str__(self) -> str:
        """Return the canonical ``"MAJOR.MINOR"`` spelling, as it appears on the wire."""
        return f"{self.major}.{self.minor}"


SUPPORTED_SCHEMAS: Final[Mapping[str, Mapping[int, SchemaVersion]]] = MappingProxyType(
    {
        "model.identity": MappingProxyType({1: SchemaVersion(1, 0)}),
        "machine.profile": MappingProxyType({1: SchemaVersion(1, 0)}),
        "benchmark.result": MappingProxyType({1: SchemaVersion(1, 0)}),
        "benchmark.run_summary": MappingProxyType({1: SchemaVersion(1, 0)}),
        "capability.evidence": MappingProxyType({1: SchemaVersion(1, 1)}),
        "benchmark.evidence_bundle": MappingProxyType({1: SchemaVersion(1, 1)}),
        "benchmark.goal_pack": MappingProxyType({1: SchemaVersion(1, 0)}),
        "benchmark.calibration_report": MappingProxyType({1: SchemaVersion(1, 0)}),
        "model.adapter_manifest": MappingProxyType({1: SchemaVersion(1, 0)}),
        "governance.egress_decision": MappingProxyType({1: SchemaVersion(1, 0)}),
    }
)
"""Every payload type this build can read, as ``{schema name: {major: highest known minor}}``.

Keyed by **major**, not by exact version, because the reader policy accepts any minor within a
supported major — including a minor newer than this build has heard of. Exact-version matching
would contradict that policy and would make every additive schema change a breaking one for every
consumer (ADR-0009 rule 9). The recorded minor is
therefore documentation of what this build knows, never a ceiling on what it accepts.

``benchmark.goal_pack`` and ``benchmark.calibration_report`` were added for FreeWeight's
user-authored goal benchmarks (ADR-0031, ADR-0032). The calibration report is registered as a
payload in its own right rather than folded into ``capability.evidence`` because it is meaningful
precisely when **no** evidence was emitted: a goal below its calibration gate produces no evidence
record at all, so without a separate schema the most informative outcome a user can get would have
no wire form.

**Frozen (as of `0.3.0`, Phase 4), plus additive changes at Phases 6 and 7.** No registered major
has ever moved and none is a draft any more: :data:`DRAFT_SCHEMAS` is empty, each version has a
committed JSON Schema and at least three golden payloads under :mod:`setspec.artifacts`, and the
ordinary rules apply without exception — a new optional field is a minor bump, and a removal,
rename, retype or tightening is a major. A reader pinning to a published version is pinning to a
shape this build cannot change without publishing a new one, which is what the snapshot contract
test enforces (ADR-0009 rule 7).

Phase 6 (ADR-0058, ADR-0061, ADR-0065) adds the optional adapter axis: ``capability.evidence``
gains its first minor since the freeze — `1.1`, an optional ``adapter`` field, absent and
byte-identical to `1.0` on every record measured on a bare base — and two schemas are new outright:
``model.adapter_manifest`` `1.0`, the operator-reviewed manifest a directory of adapters is built
from, and ``governance.egress_decision`` `1.0`, SetSpec's first payload under a root other than
``benchmark``/``capability``/``machine``/``model`` (ADR-0051 §4). Phase 7 carries that same minor
one payload out: ``benchmark.evidence_bundle`` gains its own `1.1`, whose ``evidence`` field nests
`1.1` evidence records instead of `1.0` ones, so an exported bundle can now hold adapter-bearing
records — a bundle carrying none is byte-identical to what `1.0` writes today (ADR-0068 rule 5).
Every other entry is unchanged.

Two payload types remain unregistered even after Phase 6: ``event.envelope`` and ``error.envelope``
were planned for Phase 3, which was never implemented (see ``src/setspec/event/v1.py`` and
``error/v1.py``). Naming them here before their fields exist would be the same guess Phase 2's own
risk note warns against, one layer up: a schema is frozen by being published, and an unwritten one
has nothing to publish.

A :func:`load_envelope` call naming a schema that is not registered raises
:class:`~setspec.errors.SchemaVersionUnsupported` with an empty ``supported`` list, which reads as
"this build publishes no version of that schema" — the honest answer, and the same one a consumer
gets for a schema retired in a future major.
"""


DRAFT_SCHEMAS: Final[frozenset[str]] = frozenset()
"""Which registered schemas are still provisional, and may change shape without a major bump.

**Empty as of `0.3.0` — this is the freeze.** Every registered schema is a published version with a
committed JSON Schema and goldens behind it, so none may be reshaped in place any more; a payload
grows only by an additive minor (``capability.evidence`` `1.1`, Phase 6) or by a wholly new schema
starting at `1.0`, never by editing a published version in place. The set survives its own
emptiness on purpose: it is the mechanism a *future* draft uses, and deleting it would mean the
next provisional payload type either ships silently provisional or invents a second way of saying
so.

[Development plan Phase 2](../../docs/packages/setspec/development-plan.md) requires draft status
to be *visible in the API*, not only described in prose, and asks for it to be marked "in
``SUPPORTED_SCHEMAS``". It is recorded here instead of inside the version itself, because the
alternative — a ``"1.0-draft"`` version string — would have to be parsed by
:class:`SchemaVersion`, whose whole contract is that a version is exactly two integers and that
non-canonical spellings are refused. Loosening that to carry a temporary status would weaken the
version format every *frozen* schema depends on, permanently, to describe a condition that ends at
Phase 4. A separate set says the same thing, is equally machine-readable, and disappears cleanly:
freezing a schema is one deletion from this set.

A schema listed here is registered and readable — negotiation treats it exactly like any other —
but a consumer outside this repository should know that pinning to its ``1.0`` is pinning to a
shape that may still be corrected in place. Empty is the goal state, and
[Phase 4](../../docs/packages/setspec/development-plan.md) reached it.
"""


class GeneratorInfo(PreservingPayload):
    """Which component produced a document, and at which version.

    Every envelope carries one. It is what makes an exported file self-describing months later,
    and it is why an event payload needs no ``source`` field of its own — the generator already
    names the producing application
    (ADR-0025 §3).

    Preserving rather than strict, like the envelope that holds it: a future SetSpec that adds a
    field here must not make today's readers *reject* documents, which is what a strict model would
    do. Preservation degrades to carrying an unknown key; strictness degrades to refusing the file.

    Attributes:
        name: The producing component's distribution name, lowercase — ``"freeweight"``,
            ``"loadcoach"``, ``"setspec"``.
        version: That component's version string, as it reports it. Not constrained to semver: a
            development build may legitimately report a git description, and refusing to record
            what actually produced a document helps nobody.
    """

    name: str
    version: str


# `schema` is the field name ADR-0009 §1 fixes on the wire, and it shadows pydantic v2's
# deprecated `BaseModel.schema()` classmethod, which warns on class creation. The method is
# superseded by `model_json_schema()` and is never called here, so the shadowing is harmless —
# but a library that warns on import is not, and renaming the field would change the wire format
# to work around a deprecation in a dependency.
with warnings.catch_warnings():
    warnings.filterwarnings(
        "ignore",
        message=r'Field name "schema" .*shadows an attribute',
        category=UserWarning,
    )

    class SchemaEnvelope[PayloadT](PreservingPayload):
        """A versioned wrapper around one transferable payload.

        The five fields are fixed by ADR-0009 §1::

            {"schema": "benchmark.result", "schema_version": "1.0",
             "generated_at": "2026-08-21T09:14:02.318Z",
             "generator": {"name": "freeweight", "version": "1.0.0"},
             "payload": { … }}

        Generic in its payload so that a caller who knows what they are reading gets a typed
        ``payload``; :func:`load_envelope` returns ``SchemaEnvelope[Any]`` with the payload still a
        plain mapping, because deciding *which* model to validate it into is the caller's
        business and depends on which of the two — ``Out`` or ``In`` — they need.

        Preserving rather than strict, for the reason in
        ADR-0009 rule 4 applied to the wrapper: an
        old reader re-exporting a document written by a newer one must not silently drop an envelope
        field it has not heard of.

        Attributes:
            schema: The payload type name, e.g. ``"benchmark.result"``. Two or more
                lowercase segments joined by dots.
            schema_version: The canonical ``"MAJOR.MINOR"`` string. Kept as text, not as a
                :class:`SchemaVersion`, so the document round-trips byte-for-byte; read
                :attr:`version` for the parsed form.
            generated_at: When the document was produced — UTC, millisecond precision.
            generator: The component that produced it.
            payload: The document itself.
        """

        # Shadows pydantic v2's deprecated `BaseModel.schema()` classmethod. The name is fixed
        # by ADR-0009 §1 and the method is superseded by `model_json_schema()`, so the collision
        # is with something already on its way out; renaming the field would change the wire.
        schema: str  # type: ignore[assignment]  # deliberate: ADR-0009 §1 fixes this field name
        schema_version: str
        generated_at: TimestampField
        generator: GeneratorInfo
        payload: PayloadT

        @property
        def version(self) -> SchemaVersion:
            """Return :attr:`schema_version` parsed.

            Returns:
                The parsed version. Always succeeds: the string was validated on construction, so a
                constructed envelope cannot hold an unparsable version.
            """
            return SchemaVersion.parse(self.schema_version)


def load_envelope(
    data: bytes | str | Mapping[str, Any],
    *,
    expect: str,
    supported: Sequence[SchemaVersion] | None = None,
    max_bytes: int = MAX_PAYLOAD_BYTES,
    max_depth: int = MAX_PAYLOAD_DEPTH,
) -> SchemaEnvelope[Any]:
    """Parse and validate an envelope, applying the reader policy to its version.

    The payload is left as a plain mapping. Which model it belongs in — the strict ``Out`` or the
    preserving ``In`` — depends on whether the caller is about to re-export it, and this function
    does not guess.

    Args:
        data: The document, as JSON text, UTF-8 bytes, or an already-parsed mapping. Text and
            bytes go through the size and depth guards; a mapping the caller parsed itself is
            depth-checked but not size-checked, since its cost has already been paid.
        expect: The schema name the caller intends to read. A document declaring a different
            schema is rejected rather than duck-typed — two payload types with compatible fields
            are still two payload types.
        supported: The versions this caller accepts, overriding :data:`SUPPORTED_SCHEMAS`.
            Acceptance is decided by **major**: listing ``1.0`` accepts ``1.7`` as well. Defaults
            to whatever this build registers for ``expect``.
        max_bytes: Size guard for text and bytes input; see
            :func:`~setspec.serialization.parse_json`.
        max_depth: Depth guard; see :func:`~setspec.serialization.parse_json`.

    Returns:
        The validated envelope, with ``payload`` as the raw mapping the document carried.

    Raises:
        SchemaVersionUnsupported: If the document's major version is not among the supported
            majors. ``details`` names the schema, the received version and every supported one.
        ValidationError: If the document is oversized, too deeply nested, not valid UTF-8, not
            parsable JSON, not an object at the top level, missing envelope fields, or declares a
            schema other than ``expect``. Structural failures name every offending field path at
            once in ``details["errors"]``, so one call reports everything that is wrong.
    """
    document = _as_mapping(data, max_bytes=max_bytes, max_depth=max_depth)
    envelope = _validate_envelope(document)
    if envelope.schema != expect:
        raise ValidationError(
            f"Expected a {expect!r} document but the envelope declares {envelope.schema!r}. "
            "Payload types are not interchangeable even when their fields happen to line up.",
            details={"field": "schema", "expected": expect, "received": envelope.schema},
        )
    _negotiate(envelope, supported=supported)
    return envelope


def dump_envelope(
    payload: BaseModel | Mapping[str, Any],
    *,
    schema: str,
    version: SchemaVersion,
    generator: GeneratorInfo,
    generated_at: datetime | None = None,
    clock: Clock = utc_now,
) -> str:
    """Wrap a payload in an envelope and serialize it to canonical JSON.

    Canonical means byte-identical for equal input, which is what makes an exported document
    hashable, diffable between releases and comparable across the CI matrix (spec §11.4, §16).

    Args:
        payload: The document to wrap — a payload model, dumped through its own serializers so
            measurements and timestamps take their wire forms, or an already-plain mapping.
        schema: The payload type name, e.g. ``"benchmark.result"``.
        version: The version being written. This is the writer's declaration of what it emitted,
            so it must match the model actually used, not the newest version that exists.
        generator: The component doing the writing.
        generated_at: The document's timestamp. Pass this to reproduce an existing document
            byte-for-byte; leave it unset for a new one and the clock supplies it.
        clock: Where "now" comes from when ``generated_at`` is not given. Injected so that a test
            can produce a fixed document without patching the interpreter (coding standards §5).

    Returns:
        Canonical JSON text. Encode as UTF-8 for the bytes.

    Raises:
        ValidationError: If ``schema`` is not a well-formed payload type name, if ``generated_at``
            is naive, or if the payload holds something canonical JSON cannot represent
            unambiguously.
    """
    if _SCHEMA_NAME_PATTERN.fullmatch(schema) is None:
        raise ValidationError(
            f"Not a well-formed schema name: {schema!r}. Expected two or more lowercase segments "
            "joined by dots, such as 'benchmark.result' or 'capability.evidence'.",
            details={"field": "schema", "value": schema},
        )
    body = payload.model_dump() if isinstance(payload, BaseModel) else dict(payload)
    envelope = SchemaEnvelope[Any](
        schema=schema,
        schema_version=str(version),
        generated_at=generated_at if generated_at is not None else clock(),
        generator=generator,
        payload=body,
    )
    return canonical_dumps(envelope)


def _as_mapping(
    data: bytes | str | Mapping[str, Any],
    *,
    max_bytes: int,
    max_depth: int,
) -> Mapping[str, Any]:
    """Return the document as a mapping, guarding untrusted text and rejecting non-objects."""
    document = (
        parse_json(data, max_bytes=max_bytes, max_depth=max_depth)
        if isinstance(data, bytes | str)
        else data
    )
    if not isinstance(document, dict):
        raise ValidationError(
            f"An envelope is a JSON object; got {type(document).__name__}. A bare array or scalar "
            "carries no schema name or version, so there is nothing to negotiate against.",
            details={"received_type": type(document).__name__},
        )
    return document


def _validate_envelope(document: Mapping[str, Any]) -> SchemaEnvelope[Any]:
    """Validate the envelope structure, reporting every offending field path in one error."""
    try:
        return SchemaEnvelope[Any].model_validate(dict(document))
    except PydanticValidationError as exc:
        paths = [
            {
                "field": ".".join(str(part) for part in error["loc"]),
                "problem": error["msg"],
            }
            for error in exc.errors()
        ]
        summary = "; ".join(f"{item['field']}: {item['problem']}" for item in paths)
        raise ValidationError(
            f"Envelope is structurally invalid ({len(paths)} problem(s)): {summary}.",
            details={"errors": paths},
        ) from exc


def _negotiate(envelope: SchemaEnvelope[Any], *, supported: Sequence[SchemaVersion] | None) -> None:
    """Apply the reader policy, raising if the document's major version is not supported."""
    accepted = (
        tuple(supported)
        if supported is not None
        else tuple(SUPPORTED_SCHEMAS.get(envelope.schema, {}).values())
    )
    received = envelope.version
    if any(candidate.major == received.major for candidate in accepted):
        return
    formatted = [str(candidate) for candidate in sorted(accepted)]
    supported_text = ", ".join(formatted) if formatted else "no version of this schema"
    raise SchemaVersionUnsupported(
        f"Cannot read {envelope.schema!r} version {received}: this build supports "
        f"{supported_text}. A major version means fields changed meaning, so the document is not "
        "partially parsed. Upgrade the reader, or re-export from the producer at a supported "
        "major.",
        details={
            "schema": envelope.schema,
            "received": str(received),
            "supported": formatted,
        },
    )
