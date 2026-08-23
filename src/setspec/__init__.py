"""setspec — every versioned data contract that crosses an application boundary.

Layer 2: contract types built on :mod:`baseaicore`'s vocabulary and pydantic. No I/O, no
configuration, no logging, no HTTP, and no behaviour beyond structural and range validation. This
package answers "is this a well-formed result?" — never "is this a *good* result?", which belongs
to the application that computed it ([spec §3](../../docs/packages/setspec/spec.md)).

What is exported below is the public API as of Phase 1
(``docs/packages/setspec/development-plan.md``): the schema envelope, version parsing and the
reader policy; canonical serialization with the ``Unsupported`` and RFC 3339 codecs; the strict and
preserving payload bases with the generator that pairs them; and ``MetricValue``. Payload types
themselves — benchmark results, capability evidence, events, errors — arrive in Phases 2 and 3.
Anything not listed in ``__all__`` is private and may change without a version bump.

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
not ([ADR-0009 rule 4](../../docs/adr/0009-setspec-schema-strategy.md)). That is what lets a v1.0
reader carry a v1.1 document through a re-export without destroying the parts it cannot interpret.
"""

from __future__ import annotations

from setspec.__about__ import __version__
from setspec.base import (
    PayloadDefinition,
    PreservingPayload,
    StrictPayload,
    WireEnum,
    payload_models,
)
from setspec.envelope import (
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

__all__ = [
    "MAX_PAYLOAD_BYTES",
    "MAX_PAYLOAD_DEPTH",
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
    "WireEnum",
    "ValidationError",
    "__version__",
    "canonical_dumps",
    "dump_envelope",
    "load_envelope",
    "parse_json",
    "payload_models",
]
