"""Contract module — canonical JSON, the wire codecs, and the guards on untrusted input.

Imports pydantic and :mod:`baseaicore`; performs no I/O and reads no clock. This module owns the
three places where a Python value and its JSON form disagree, and it resolves each one exactly
once so that no payload model has to:

* a measurement that does not exist here is the string ``"unsupported"``, never ``null``, never
  ``0`` (ADR-0016 §4);
* a timestamp is RFC 3339 UTC at millisecond precision, never naive
  ([spec §11.6](../../docs/packages/setspec/spec.md));
* byte-identical output for equal input, which is what makes a hash of a payload comparable across
  machines (spec §11.4, §16).

Canonical output is delegated to :func:`baseaicore.canonical_json` rather than reimplemented. That
is deliberate: a machine fingerprint, a runtime profile hash and an exported payload must agree
byte-for-byte, and two independent canonicalizers eventually disagree about a float or a
non-ASCII string.

Untrusted input is bounded before it is parsed, not after. :data:`MAX_PAYLOAD_BYTES` and
:data:`MAX_PAYLOAD_DEPTH` are module constants rather than configuration because the supported
limits of a build are part of what that build promises (spec §12), and a caller that needs a
tighter bound passes one per call.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Any, Final

from baseaicore import (
    UNSUPPORTED,
    Measurement,
    Unsupported,
    ValidationError,
    canonical_json,
    from_rfc3339,
    is_supported,
    to_rfc3339,
)
from pydantic import (
    BaseModel,
    BeforeValidator,
    GetCoreSchemaHandler,
    GetJsonSchemaHandler,
    PlainSerializer,
    WithJsonSchema,
)
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import core_schema

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "MAX_PAYLOAD_BYTES",
    "MAX_PAYLOAD_DEPTH",
    "UNSUPPORTED_JSON",
    "MeasurementField",
    "TimestampField",
    "canonical_dumps",
    "parse_json",
]

UNSUPPORTED_JSON: Final[str] = "unsupported"
"""The JSON form of an unavailable measurement, fixed by ADR-0016 §4."""

MAX_PAYLOAD_DEPTH: Final[int] = 64
"""Deepest container nesting accepted from untrusted JSON.

Chosen to sit far above any payload this suite defines — an evidence bundle nests about six deep,
and the most elaborate provenance block roughly ten — and far below CPython's default recursion
limit of 1000. The gap is the point: a hostile document is refused by a named limit with a useful
error, rather than by a ``RecursionError`` raised somewhere inside the JSON parser.
"""

MAX_PAYLOAD_BYTES: Final[int] = 16 * 1024 * 1024
"""Largest single document accepted from untrusted JSON, in bytes of UTF-8.

Matches the prompt-bearing request body limit in
API Standards §10, so a payload that a suite
API would accept is one this parser will also accept. Large exports are not meant to arrive as one
document: they are JSONL with one envelope per line (spec §15), which keeps both the parser and
the consumer's memory bounded regardless of how many results the file holds.
"""

_MICROSECONDS_PER_MILLISECOND = 1_000


def _validate_measurement(value: Any) -> Measurement:  # noqa: ANN401 — accepts raw JSON scalars
    """Accept a number or ``"unsupported"``; refuse anything that would fabricate a measurement."""
    # `isinstance` rather than `is UNSUPPORTED`: the sentinel is a singleton so the two are
    # equivalent at runtime, but comparing an `Any` against a constant makes mypy widen the
    # constant to `Any` too, and the narrowed form keeps the return type honest.
    if isinstance(value, Unsupported):
        return value
    if isinstance(value, str):
        if value == UNSUPPORTED_JSON:
            return UNSUPPORTED
        raise ValueError(
            f"a measurement is a number or the string {UNSUPPORTED_JSON!r}; got the string "
            f"{value!r}. A measurement is never parsed from text, because a string that looks "
            "like a number is usually a bug upstream rather than a reading."
        )
    # bool is an int in Python, and `True` reaching a metric means a flag was wired to a value.
    if isinstance(value, bool):
        raise ValueError(
            "a bool is not a measurement; use a number, or UNSUPPORTED if this environment "
            "cannot provide the value (ADR-0016)"
        )
    if isinstance(value, int | float):
        # Narrowed from `Any` by the isinstance above; the annotation restates it for mypy.
        numeric: int | float = value
        return numeric
    raise ValueError(
        f"a measurement is a number or the string {UNSUPPORTED_JSON!r}; got "
        f"{type(value).__name__}. Never null and never 0 — an absent measurement is "
        f"{UNSUPPORTED_JSON!r} (ADR-0016 §4)."
    )


def _serialize_measurement(value: Measurement) -> int | float | str:
    """Render a measurement as JSON: a number, or the string ``"unsupported"``."""
    # `is_supported` is a TypeGuard, so this narrows for the type checker; a bare
    # `value is UNSUPPORTED` test would not.
    return value if is_supported(value) else UNSUPPORTED_JSON


class _MeasurementCodec:
    """Pydantic hooks for :data:`MeasurementField`.

    A full core schema rather than a stack of ``Annotated`` validators: the underlying type is
    ``int | float | Unsupported``, and pydantic cannot build a schema for the sentinel class on its
    own — it is a plain Python object with no fields. Replacing the schema outright also keeps the
    generated JSON Schema honest, which matters because Phase 4 publishes it as package data.
    """

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source: Any, handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        """Return the validate/serialize schema for a measurement."""
        return core_schema.no_info_plain_validator_function(
            _validate_measurement,
            serialization=core_schema.plain_serializer_function_ser_schema(_serialize_measurement),
        )

    @classmethod
    def __get_pydantic_json_schema__(
        cls, schema: core_schema.CoreSchema, handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        """Return the JSON Schema form: a number, or the string ``"unsupported"``."""
        return {"anyOf": [{"type": "number"}, {"const": UNSUPPORTED_JSON}]}


MeasurementField = Annotated[Measurement, _MeasurementCodec]
"""A :data:`baseaicore.Measurement` field with its wire codec attached.

Use this for any quantity a sensor, provider or benchmark might fail to report. It accepts a
number or the string ``"unsupported"`` on the way in, emits the same two forms on the way out, and
refuses ``null``, ``0``-as-absent, bools and numeric strings — the four ways a measurement that was
never taken gets into a chart.
"""


def _validate_timestamp(value: Any) -> datetime:  # noqa: ANN401 — accepts str or datetime
    """Parse and normalize a timestamp to UTC at millisecond precision, refusing naive input."""
    if isinstance(value, str):
        try:
            value = from_rfc3339(value)
        except ValidationError as exc:
            # `from_rfc3339` raises a SuiteError, which pydantic does not wrap. Letting it escape
            # would mean a bad timestamp aborts validation immediately while every other bad field
            # is reported together — so the caller would learn about one problem per attempt.
            # Re-raised as ValueError, it joins the other field errors in one pydantic report.
            raise ValueError(str(exc)) from exc
    if not isinstance(value, datetime):
        raise ValueError(
            f"a timestamp is an RFC 3339 string or a timezone-aware datetime; got "
            f"{type(value).__name__}"
        )
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(
            "a naive datetime has no defensible UTC reading, and guessing one would shift every "
            "downstream timestamp by the local offset; attach a timezone (ADR-0016 sibling rule, "
            "coding standards §5)"
        )
    in_utc = value.astimezone(UTC)
    # Truncate to the precision `to_rfc3339` emits, so `load(dump(x)) == x` holds for a datetime
    # built from `utc_now()`, which carries microseconds. Without this the model would round-trip
    # to a *different* instant and the round-trip contract (spec §11.3) would be false.
    truncated = (
        in_utc.microsecond // _MICROSECONDS_PER_MILLISECOND
    ) * _MICROSECONDS_PER_MILLISECOND
    return in_utc.replace(microsecond=truncated)


TimestampField = Annotated[
    datetime,
    BeforeValidator(_validate_timestamp),
    PlainSerializer(to_rfc3339, return_type=str),
    WithJsonSchema({"type": "string", "format": "date-time"}),
]
"""A timezone-aware UTC timestamp field, serialized as RFC 3339 with millisecond precision.

Accepts an RFC 3339 string or an aware :class:`~datetime.datetime` in any timezone, normalizes to
UTC, and truncates to milliseconds — the precision :func:`baseaicore.to_rfc3339` emits, so a value
survives a load/dump round trip unchanged. Naive datetimes are refused rather than assumed to be
UTC.
"""


def canonical_dumps(value: BaseModel | Mapping[str, Any]) -> str:
    """Serialize a model or mapping to canonical JSON.

    Canonical means byte-identical for equal input: keys sorted by code point, minimal separators,
    non-ASCII emitted as itself, floats in their shortest round-tripping form. That property is
    what lets a payload be hashed, compared across machines and diffed between releases
    (spec §11.4, §16).

    Args:
        value: A pydantic model — dumped through its own serializers first, so measurements and
            timestamps take their wire forms — or an already-plain mapping.

    Returns:
        Canonical JSON text. Encode with UTF-8 to get the bytes that were promised.

    Raises:
        ValidationError: If the structure holds something canonical JSON cannot represent
            unambiguously: a non-string mapping key, a non-finite float, a naive datetime, raw
            bytes, a :class:`~decimal.Decimal`, or a reference cycle.
    """
    plain = value.model_dump() if isinstance(value, BaseModel) else value
    return canonical_json(plain)


def parse_json(
    data: bytes | str,
    *,
    max_bytes: int = MAX_PAYLOAD_BYTES,
    max_depth: int = MAX_PAYLOAD_DEPTH,
) -> Any:  # noqa: ANN401 — returns whatever JSON structure the document held
    """Parse untrusted JSON text with both guards applied before the parser runs.

    Order matters. Size is checked first because it is O(1) and rejects the cheapest attack; depth
    is measured by scanning the text, before :func:`json.loads` is given a chance to exhaust the
    C stack on a document that is nothing but ten thousand open brackets.

    Args:
        data: JSON text, or its UTF-8 bytes.
        max_bytes: Largest document accepted, in bytes of UTF-8. Defaults to
            :data:`MAX_PAYLOAD_BYTES`; pass a smaller value when the caller knows its own bound
            (spec §14 makes size limiting the caller's prerogative).
        max_depth: Deepest container nesting accepted. Defaults to :data:`MAX_PAYLOAD_DEPTH`.

    Returns:
        The parsed structure: a mapping, list or scalar exactly as JSON defines it.

    Raises:
        ValidationError: If the document exceeds ``max_bytes``, nests deeper than ``max_depth``,
            is not valid UTF-8, or is not parsable JSON. Every message names the limit or the
            parse position, because "too big" without a number tells the caller nothing.
    """
    text = _decode(data)
    size = len(text.encode("utf-8"))
    if size > max_bytes:
        raise ValidationError(
            f"Payload is {size} bytes, over the {max_bytes}-byte limit. Large exports are "
            "JSONL — one envelope per line — so that producer and consumer both stream "
            "instead of holding the whole document in memory (spec §15).",
            details={"size_bytes": size, "limit_bytes": max_bytes},
        )
    depth = _scan_depth(text)
    if depth > max_depth:
        raise ValidationError(
            f"Payload nests {depth} containers deep, over the {max_depth}-level limit. No payload "
            "this suite defines approaches that depth, so a document that does is either "
            "corrupt or hostile.",
            details={"depth": depth, "limit_depth": max_depth},
        )
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValidationError(
            f"Not parsable JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}.",
            details={"line": exc.lineno, "column": exc.colno, "position": exc.pos},
        ) from exc


def _decode(data: bytes | str) -> str:
    """Return ``data`` as text, naming the byte offset when it is not valid UTF-8."""
    if isinstance(data, str):
        return data
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationError(
            f"Payload is not valid UTF-8 at byte {exc.start}: {exc.reason}. JSON on the wire is "
            "UTF-8 (RFC 8259 §8.1).",
            details={"position": exc.start, "reason": exc.reason},
        ) from exc


def _scan_depth(text: str) -> int:
    """Return the deepest container nesting in JSON text, counting brackets outside strings.

    Scans rather than recurses so that measuring a hostile document cannot itself overflow the
    stack — which is the whole point of checking depth before parsing.
    """
    depth = 0
    deepest = 0
    in_string = False
    escaped = False
    for character in text:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character in "{[":
            depth += 1
            deepest = max(deepest, depth)
        elif character in "}]":
            depth -= 1
    return deepest
