"""Tests for :mod:`setspec.metrics` — the Out/In pair and the ADR-0016 §6 invariants.

The invariant tests are the point of this module. A metric model that lets ``value`` and
``sample_count`` disagree turns "unavailable is not zero" back into a convention, and a convention
is exactly what ADR-0016 says cannot prevent this bug class.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from baseaicore import UNSUPPORTED
from pydantic import ValidationError as PydanticValidationError

from setspec import Aggregation, MetricValueIn, MetricValueOut, canonical_dumps


def _measured(**overrides: Any) -> dict[str, Any]:
    """Return a valid measured metric, with fields optionally replaced."""
    return {
        "value": 12.5,
        "unit": "ms",
        "aggregation": "mean",
        "higher_is_better": False,
        "sample_count": 40,
        "dispersion": 1.25,
    } | overrides


def _unmeasurable(**overrides: Any) -> dict[str, Any]:
    """Return a valid unsupported metric, with fields optionally replaced."""
    return _measured(value="unsupported", sample_count=0, dispersion="unsupported") | overrides


class TestValidMetrics:
    """The shapes a producer is meant to emit."""

    def test_a_measured_metric_round_trips(self) -> None:
        metric = MetricValueOut.model_validate(_measured())
        assert MetricValueOut.model_validate(json.loads(canonical_dumps(metric))) == metric

    def test_an_unsupported_metric_round_trips(self) -> None:
        metric = MetricValueOut.model_validate(_unmeasurable())
        assert metric.value is UNSUPPORTED
        assert metric.dispersion is UNSUPPORTED
        assert MetricValueOut.model_validate(json.loads(canonical_dumps(metric))) == metric

    def test_an_unsupported_metric_never_serializes_as_zero_or_null(self) -> None:
        rendered = json.loads(canonical_dumps(MetricValueOut.model_validate(_unmeasurable())))
        assert rendered["value"] == "unsupported"
        assert rendered["dispersion"] == "unsupported"

    def test_a_single_observation_has_no_dispersion(self) -> None:
        metric = MetricValueOut.model_validate(
            _measured(aggregation="single", sample_count=1, dispersion="unsupported")
        )
        assert metric.aggregation is Aggregation.SINGLE

    def test_aggregation_serializes_as_its_name(self) -> None:
        metric = MetricValueOut.model_validate(_measured(aggregation="p95"))
        assert json.loads(canonical_dumps(metric))["aggregation"] == "p95"

    @pytest.mark.parametrize("aggregation", list(Aggregation))
    def test_every_aggregation_is_accepted(self, aggregation: Aggregation) -> None:
        metric = MetricValueOut.model_validate(_measured(aggregation=aggregation.value))
        assert metric.aggregation is aggregation


class TestSampleCoherence:
    """ADR-0016 §6, enforced structurally rather than left to the producer's discipline."""

    def test_a_real_value_cannot_claim_zero_samples(self) -> None:
        """`value=0.0, sample_count=0` is the exact shape of a fabricated measurement."""
        with pytest.raises(PydanticValidationError, match="at least one supported sample"):
            MetricValueOut.model_validate(
                _measured(value=0.0, sample_count=0, dispersion="unsupported")
            )

    def test_an_unsupported_value_cannot_claim_samples(self) -> None:
        with pytest.raises(PydanticValidationError, match="no supported samples"):
            MetricValueOut.model_validate(_unmeasurable(sample_count=5))

    def test_dispersion_needs_at_least_two_samples(self) -> None:
        """The spread of one observation is undefined, not zero."""
        with pytest.raises(PydanticValidationError, match="at least 2 supported samples"):
            MetricValueOut.model_validate(_measured(sample_count=1, dispersion=0.0))

    def test_a_negative_sample_count_is_rejected(self) -> None:
        with pytest.raises(PydanticValidationError):
            MetricValueOut.model_validate(_measured(sample_count=-1))

    def test_an_empty_unit_is_rejected(self) -> None:
        """A dimensionless quantity says so — 'ratio', 'count' — rather than saying nothing."""
        with pytest.raises(PydanticValidationError):
            MetricValueOut.model_validate(_measured(unit=""))

    def test_an_unknown_aggregation_is_rejected(self) -> None:
        with pytest.raises(PydanticValidationError):
            MetricValueOut.model_validate(_measured(aggregation="average"))


class TestOutAndInDiffer:
    """The pair disagrees about unknown keys on purpose — that disagreement is the design."""

    def test_out_refuses_an_unknown_field(self) -> None:
        with pytest.raises(PydanticValidationError):
            MetricValueOut.model_validate(_measured(confidence=0.9))

    def test_in_preserves_an_unknown_field(self) -> None:
        metric = MetricValueIn.model_validate(_measured(confidence=0.9))
        assert metric.extras == {"confidence": 0.9}

    def test_in_re_emits_what_it_preserved(self) -> None:
        metric = MetricValueIn.model_validate(_measured(confidence=0.9))
        assert json.loads(canonical_dumps(metric))["confidence"] == 0.9

    def test_in_still_validates_the_fields_it_knows(self) -> None:
        """Preservation adds information; it never relaxes a rule about a known field."""
        with pytest.raises(PydanticValidationError):
            MetricValueIn.model_validate(_measured(sample_count=-1, confidence=0.9))

    def test_both_halves_are_immutable(self) -> None:
        metric = MetricValueOut.model_validate(_measured())
        with pytest.raises(PydanticValidationError):
            metric.sample_count = 99  # frozen model; the refusal is asserted at runtime
