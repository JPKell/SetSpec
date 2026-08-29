"""setspec — every versioned data contract that crosses an application boundary.

Layer 2: contract types built on :mod:`baseaicore`'s vocabulary and pydantic. No I/O, no
configuration, no logging, no HTTP, and no behaviour beyond structural and range validation. This
package answers "is this a well-formed result?" — never "is this a *good* result?", which belongs
to the application that computed it ([spec §3](../../docs/packages/setspec/spec.md)).

What is exported below is every piece of **shared, non-versioned** infrastructure as of Phase 2
(``docs/packages/setspec/development-plan.md``): the schema envelope, version parsing and the
reader policy; canonical serialization with the ``Unsupported`` and RFC 3339 codecs; the strict and
preserving payload bases with the generator that pairs them; ``MetricValue``; and the capability
vocabulary. Anything not listed in ``__all__`` is private and may change without a version bump.

Phase 4 adds the schema artifacts to that flat surface — ``json_schema_for``,
``golden_payloads``, ``golden_names`` and ``PUBLISHED_SCHEMAS``, grouped under "schema artefacts"
in [spec §7](../../docs/packages/setspec/spec.md). They belong here rather than in a versioned
module for the same reason ``MetricValue`` does: an accessor that *returns* a version's artifacts
is not itself versioned, and a consumer asking for ``benchmark.result 2.0``'s JSON Schema calls
the same function a consumer asking for ``1.0`` does.

**Payload types are not re-exported here.** ``model.identity``, ``machine.profile``,
``benchmark.result``, ``benchmark.run_summary``, ``capability.evidence`` and
``benchmark.evidence_bundle`` (Phase 2), and ``benchmark.goal_pack`` /
``benchmark.calibration_report`` (ADR-0031), live in their own versioned modules —
``setspec.model.v1``, ``setspec.machine.v1``, ``setspec.benchmark.v1``, ``setspec.capability.v1``,
``setspec.goal.v1`` — and are imported from there, e.g.
``from setspec.capability.v1 import CapabilityEvidenceOut``.
This is not an oversight: ADR-0009 rule 6
requires a v1 payload to remain importable as ``setspec.benchmark.v1`` for a deprecation window
after ``benchmark.result 2.0`` ships, which only works if ``v1`` and ``v2`` are different modules
rather than two classes racing for one flat name. ``MetricValue`` and the vocabulary helpers below
are re-exported flatly because neither is itself a versioned wire payload — they are shared
infrastructure a payload's fields are built from, exactly like the envelope and serialization
helpers above them.

    >>> from setspec import GeneratorInfo, SchemaVersion, dump_envelope
    >>> generator = GeneratorInfo(name="freeweight", version="1.0.0")
    >>> document = dump_envelope(
    ...     {"tokens_per_second": 42.0},
    ...     schema="benchmark.result",
    ...     version=SchemaVersion(1, 0),
    ...     generator=generator,
    ... )

The two halves of every payload type are the design, not an accident: a writer uses the ``Out``
class and may emit only fields it knows; a reader uses the ``In`` class and keeps fields it does
not (ADR-0009 rule 4). That is what lets a v1.0
reader carry a v1.1 document through a re-export without destroying the parts it cannot interpret.
"""

from __future__ import annotations

from setspec.__about__ import __version__
from setspec.artifacts import (
    PUBLISHED_SCHEMAS,
    golden_names,
    golden_payloads,
    json_schema_for,
)
from setspec.base import (
    PayloadDefinition,
    PreservingPayload,
    StrictPayload,
    WireEnum,
    payload_models,
)
from setspec.envelope import (
    DRAFT_SCHEMAS,
    SUPPORTED_SCHEMAS,
    GeneratorInfo,
    SchemaEnvelope,
    SchemaVersion,
    dump_envelope,
    load_envelope,
)
from setspec.errors import SchemaVersionUnsupported, ValidationError
from setspec.metrics import Aggregation, MetricValueFields, MetricValueIn, MetricValueOut
from setspec.serialization import (
    MAX_PAYLOAD_BYTES,
    MAX_PAYLOAD_DEPTH,
    UNSUPPORTED_JSON,
    MeasurementField,
    TimestampField,
    canonical_dumps,
    parse_json,
)
from setspec.vocabulary import (
    CAPABILITIES,
    CAPABILITY_VOCABULARY_VERSION,
    RESERVED_ROOTS,
    is_known_capability,
    validate_capability,
)

__all__ = [
    "CAPABILITIES",
    "CAPABILITY_VOCABULARY_VERSION",
    "DRAFT_SCHEMAS",
    "MAX_PAYLOAD_BYTES",
    "MAX_PAYLOAD_DEPTH",
    "PUBLISHED_SCHEMAS",
    "RESERVED_ROOTS",
    "SUPPORTED_SCHEMAS",
    "UNSUPPORTED_JSON",
    "Aggregation",
    "GeneratorInfo",
    "MeasurementField",
    "MetricValueFields",
    "MetricValueIn",
    "MetricValueOut",
    "PayloadDefinition",
    "PreservingPayload",
    "SchemaEnvelope",
    "SchemaVersion",
    "SchemaVersionUnsupported",
    "StrictPayload",
    "TimestampField",
    "ValidationError",
    "WireEnum",
    "__version__",
    "canonical_dumps",
    "dump_envelope",
    "golden_names",
    "golden_payloads",
    "is_known_capability",
    "json_schema_for",
    "load_envelope",
    "parse_json",
    "payload_models",
    "validate_capability",
]
