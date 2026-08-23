"""Tests for :mod:`setspec.serialization` — the codecs, canonical output and the input guards.

These assert the three properties every payload model inherits without restating them: an absent
measurement is ``"unsupported"`` and never ``null`` or ``0``, a timestamp is UTC at millisecond
precision, and equal structures produce identical bytes.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from baseaicore import UNSUPPORTED, ValidationError
from pydantic import ValidationError as PydanticValidationError

from setspec import (
    MAX_PAYLOAD_BYTES,
    MAX_PAYLOAD_DEPTH,
    PayloadDefinition,
    canonical_dumps,
    parse_json,
    payload_models,
)
from setspec.serialization import MeasurementField, TimestampField


class SampleFields(PayloadDefinition):
    """A payload with one of each codec, used to exercise them through a real model."""

    reading: MeasurementField
    observed_at: TimestampField


SampleOut, SampleIn = payload_models(SampleFields)

_AT = datetime(2026, 8, 22, 14, 3, 11, 250_000, tzinfo=UTC)


class TestMeasurementCodec:
    """`UNSUPPORTED` ↔ `"unsupported"`, and nothing else gets to look like a measurement."""

    def test_unsupported_serializes_to_the_string(self) -> None:
        payload = SampleOut(reading=UNSUPPORTED, observed_at=_AT)
        assert payload.model_dump()["reading"] == "unsupported"

    def test_the_string_deserializes_to_the_sentinel(self) -> None:
        payload = SampleOut.model_validate({"reading": "unsupported", "observed_at": _AT})
        assert payload.reading is UNSUPPORTED

    @pytest.mark.parametrize("value", [0, 0.0, 42, -7, 3.5])
    def test_real_numbers_survive_unchanged(self, value: float) -> None:
        payload = SampleOut(reading=value, observed_at=_AT)
        assert payload.reading == value
        assert payload.model_dump()["reading"] == value

    def test_null_is_never_produced_for_a_measurement(self) -> None:
        """ADR-0016 §4: an absent measurement is a string, never `null`, never `0`."""
        rendered = json.loads(canonical_dumps(SampleOut(reading=UNSUPPORTED, observed_at=_AT)))
        assert rendered["reading"] == "unsupported"
        assert rendered["reading"] is not None

    def test_null_is_rejected_on_input(self) -> None:
        with pytest.raises(PydanticValidationError):
            SampleOut.model_validate({"reading": None, "observed_at": _AT})

    def test_a_bool_is_not_a_measurement(self) -> None:
        """`True` reaching a metric means a flag was wired to a value; it must not read as 1."""
        with pytest.raises(PydanticValidationError):
            SampleOut.model_validate({"reading": True, "observed_at": _AT})

    @pytest.mark.parametrize("value", ["1.5", "42", "", "unknown", "UNSUPPORTED"])
    def test_numeric_and_near_miss_strings_are_rejected(self, value: str) -> None:
        with pytest.raises(PydanticValidationError):
            SampleOut.model_validate({"reading": value, "observed_at": _AT})

    def test_round_trips_through_json(self) -> None:
        original = SampleOut(reading=UNSUPPORTED, observed_at=_AT)
        assert SampleOut.model_validate(json.loads(canonical_dumps(original))) == original


class TestTimestampCodec:
    """RFC 3339 UTC at millisecond precision, and naive input refused."""

    def test_serializes_with_millisecond_precision(self) -> None:
        payload = SampleOut(reading=1, observed_at=_AT)
        assert payload.model_dump()["observed_at"] == "2026-08-22T14:03:11.250Z"

    def test_naive_datetime_is_rejected(self) -> None:
        with pytest.raises(PydanticValidationError):
            SampleOut(reading=1, observed_at=datetime(2026, 8, 22, 14, 3, 11))  # noqa: DTZ001

    def test_sub_millisecond_precision_is_truncated_so_round_trip_holds(self) -> None:
        """Without truncation, `load(dump(x)) != x` for any datetime built from `utc_now()`."""
        precise = datetime(2026, 8, 22, 14, 3, 11, 250_999, tzinfo=UTC)
        payload = SampleOut(reading=1, observed_at=precise)
        assert payload.observed_at.microsecond == 250_000
        assert SampleOut.model_validate(payload.model_dump()) == payload

    def test_other_offsets_normalize_to_utc(self) -> None:
        elsewhere = datetime(2026, 8, 22, 16, 3, 11, 250_000, tzinfo=timezone(timedelta(hours=2)))
        payload = SampleOut(reading=1, observed_at=elsewhere)
        assert payload.observed_at == _AT
        assert payload.model_dump()["observed_at"].endswith("Z")

    def test_accepts_an_rfc_3339_string(self) -> None:
        payload = SampleOut.model_validate(
            {"reading": 1, "observed_at": "2026-08-22T14:03:11.250Z"}
        )
        assert payload.observed_at == _AT

    @pytest.mark.parametrize("value", ["not-a-time", "2026-08-22T14:03:11", 5, None])
    def test_unparsable_or_offsetless_input_is_rejected(self, value: Any) -> None:
        with pytest.raises(PydanticValidationError):
            SampleOut.model_validate({"reading": 1, "observed_at": value})


class TestCanonicalOutput:
    """Byte-identity for equal input — the property that makes a payload hashable and diffable."""

    def test_repeated_dumps_are_byte_identical(self) -> None:
        payload = SampleOut(reading=1.5, observed_at=_AT)
        assert canonical_dumps(payload) == canonical_dumps(payload)

    def test_key_order_in_the_source_does_not_change_the_output(self) -> None:
        forward = canonical_dumps({"a": 1, "b": 2})
        backward = canonical_dumps({"b": 2, "a": 1})
        assert forward == backward == '{"a":1,"b":2}'

    def test_output_has_no_incidental_whitespace(self) -> None:
        assert canonical_dumps({"a": 1, "b": [1, 2]}) == '{"a":1,"b":[1,2]}'

    def test_non_ascii_is_emitted_as_itself(self) -> None:
        assert canonical_dumps({"name": "Grüße"}) == '{"name":"Grüße"}'

    def test_negative_zero_is_normalized(self) -> None:
        """`-0.0` and `0.0` are equal, so they must not hash differently."""
        assert canonical_dumps({"v": -0.0}) == canonical_dumps({"v": 0.0})

    def test_non_finite_floats_are_refused(self) -> None:
        """A nan in a hashed structure is a measurement that was never taken."""
        with pytest.raises(ValidationError):
            canonical_dumps({"v": float("nan")})

    def test_a_mapping_dumps_the_same_as_the_model_that_holds_it(self) -> None:
        payload = SampleOut(reading=1.5, observed_at=_AT)
        assert canonical_dumps(payload) == canonical_dumps(payload.model_dump())


class TestParseGuards:
    """Untrusted input is bounded before the parser sees it, and every refusal names its limit."""

    def test_accepts_text_and_bytes_alike(self) -> None:
        assert parse_json('{"a":1}') == parse_json(b'{"a":1}') == {"a": 1}

    def test_size_guard_reports_the_limit(self) -> None:
        oversized = json.dumps({"pad": "x" * 200})
        with pytest.raises(ValidationError) as caught:
            parse_json(oversized, max_bytes=50)
        assert caught.value.details["limit_bytes"] == 50
        assert caught.value.details["size_bytes"] > 50

    def test_depth_guard_rejects_a_payload_nested_beyond_the_limit(self) -> None:
        deep = "[" * 10 + "]" * 10
        with pytest.raises(ValidationError) as caught:
            parse_json(deep, max_depth=5)
        assert caught.value.details["depth"] == 10
        assert caught.value.details["limit_depth"] == 5

    def test_depth_guard_admits_a_payload_at_exactly_the_limit(self) -> None:
        at_limit = "[" * 5 + "]" * 5
        assert parse_json(at_limit, max_depth=5) == [[[[[]]]]]

    def test_brackets_inside_strings_do_not_count_as_nesting(self) -> None:
        """The guard scans text, so it must respect string literals and their escapes."""
        assert parse_json('{"a":"[[[[[[[[","b":"\\"[["}', max_depth=1) == {
            "a": "[[[[[[[[",
            "b": '"[[',
        }

    def test_the_default_limits_are_the_documented_constants(self) -> None:
        assert MAX_PAYLOAD_DEPTH == 64
        assert MAX_PAYLOAD_BYTES == 16 * 1024 * 1024

    def test_a_deeply_nested_document_is_refused_rather_than_overflowing_the_stack(self) -> None:
        """The guard exists so that a hostile document fails our way, not with a RecursionError."""
        hostile = "[" * 5_000 + "]" * 5_000
        with pytest.raises(ValidationError) as caught:
            parse_json(hostile)
        assert caught.value.details["limit_depth"] == MAX_PAYLOAD_DEPTH

    def test_malformed_json_reports_its_position(self) -> None:
        with pytest.raises(ValidationError) as caught:
            parse_json('{"a": }')
        assert caught.value.details["line"] == 1
        assert "column" in caught.value.details

    def test_invalid_utf8_is_reported_with_its_offset(self) -> None:
        with pytest.raises(ValidationError) as caught:
            parse_json(b'{"a": "\xff"}')
        assert caught.value.details["position"] == 7


class TestGeneratedJsonSchema:
    """The codecs must describe themselves, because Phase 4 publishes the schema as package data.

    A validator that cannot produce JSON Schema would pass every test here and then block the
    freeze, so the requirement is asserted now rather than discovered later.
    """

    def test_a_measurement_is_a_number_or_the_unsupported_string(self) -> None:
        schema = SampleOut.model_json_schema()["properties"]["reading"]
        assert schema["anyOf"] == [{"type": "number"}, {"const": "unsupported"}]

    def test_a_timestamp_is_a_date_time_string(self) -> None:
        schema = SampleOut.model_json_schema()["properties"]["observed_at"]
        assert schema["type"] == "string"
        assert schema["format"] == "date-time"

    def test_both_halves_of_a_pair_generate_a_schema(self) -> None:
        assert SampleOut.model_json_schema()["properties"].keys() == {"reading", "observed_at"}
        assert SampleIn.model_json_schema()["properties"].keys() == {"reading", "observed_at"}
