"""Contract module — the measured value that every benchmark metric reduces to.

Imports pydantic and :mod:`baseaicore`; performs no I/O and computes nothing. SetSpec carries
statistics, it never produces them: the aggregation named here was performed by the producer, and
this model's job is to make the producer state what it did rather than hand over a bare number
(spec §3, non-goals).

The invariants below are the schema-level half of
[ADR-0016 §6](../../docs/adr/0016-unavailable-is-not-zero.md). That ADR requires unsupported
samples to be *excluded* from a statistic and the surviving sample count to be reported next to it;
a model that let a caller write ``value=0.0, sample_count=0`` would make the rule advisory. Here it
is structural — the two fields cannot disagree, so a metric that was never measured cannot be
serialized as one that measured zero.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from baseaicore import UNSUPPORTED, is_supported
from pydantic import Field, model_validator

from setspec.base import PayloadDefinition, WireEnum, payload_models
from setspec.serialization import MeasurementField

__all__ = [
    "Aggregation",
    "MetricValueFields",
    "MetricValueIn",
    "MetricValueOut",
]

_MINIMUM_SAMPLES_FOR_DISPERSION = 2


class Aggregation(StrEnum):
    """How the samples behind a metric were reduced to one number.

    A ``StrEnum`` so it serializes and logs as its own name rather than an opaque integer
    (coding standards §2). The value is what appears on the wire.

    Recording this is not bookkeeping: a mean and a p95 of the same samples answer different
    questions, and a consumer that compares one against the other is comparing nothing. The
    producer knows which it computed; the wire format makes it say so.
    """

    SINGLE = "single"
    """One observation, not aggregated. ``sample_count`` is 1 and dispersion is unsupported."""

    MEAN = "mean"
    """Arithmetic mean of the supported samples."""

    MEDIAN = "median"
    """50th percentile — the value to prefer over ``MEAN`` where outliers are expected."""

    MIN = "min"
    """Smallest supported sample."""

    MAX = "max"
    """Largest supported sample."""

    SUM = "sum"
    """Total across the supported samples."""

    COUNT = "count"
    """How many events occurred — a tally, distinct from ``sample_count``, which says how many
    observations produced this statistic."""

    STDDEV = "stddev"
    """Standard deviation of the supported samples, reported as the value in its own right."""

    P50 = "p50"
    """50th percentile — the same statistic as ``MEDIAN``, spelled the way a percentile family
    (``p50``/``p95``/``p99``) is usually reported together; both members exist so a producer never
    has to translate its own vocabulary to satisfy this one."""

    P95 = "p95"
    """95th percentile."""

    P99 = "p99"
    """99th percentile."""

    RATIO = "ratio"
    """A proportion in ``[0, 1]`` that is not a mean of pass/fail samples but a direct ratio —
    e.g. a memory-overhead ratio computed from two other measurements."""

    RAW = "raw"
    """A single unaggregated reading, kept distinct from ``SINGLE``: ``SINGLE`` still promises a
    real, comparable measurement of the metric's stated unit, while ``RAW`` marks a value passed
    through without this build knowing whether it was ever meant to be aggregated at all."""


class MetricValueFields(PayloadDefinition):
    """Field definitions for ``metric.value``; use :data:`MetricValueOut` / :data:`MetricValueIn`.

    A measured quantity, the statistic that produced it, and enough context for a consumer to know
    whether comparing it to another one is meaningful.

    Attributes:
        value: The measurement, or ``UNSUPPORTED`` when this environment could not provide one.
            Never ``null`` and never ``0`` as a stand-in for absence
            ([ADR-0016 §4](../../docs/adr/0016-unavailable-is-not-zero.md)).
        unit: The unit the value is in — ``"ms"``, ``"tokens_per_second"``, ``"bytes"``,
            ``"ratio"``. Required and non-empty: a number whose unit lives only in a field name
            somewhere upstream is a number that will eventually be compared against a different
            one (coding standards §3). Dimensionless quantities say so explicitly rather than
            passing an empty string.
        aggregation: Which statistic ``value`` is.
        higher_is_better: Whether a larger value is a better result. Carried per metric because
            the answer differs between metrics in the same payload — throughput and latency point
            in opposite directions — and a consumer ranking results cannot infer it from the unit.
        sample_count: How many **supported** samples produced ``value``. Unsupported samples are
            excluded from the statistic and from this count (ADR-0016 §6), so it is the honest
            denominator, not the number of attempts.
        dispersion: Spread of those samples, as a standard deviation in the same unit as
            ``value``. ``UNSUPPORTED`` when fewer than two supported samples exist, because the
            spread of a single observation is undefined rather than zero.
    """

    value: MeasurementField
    unit: str = Field(min_length=1)
    aggregation: WireEnum[Aggregation]
    higher_is_better: bool
    sample_count: int = Field(ge=0)
    dispersion: MeasurementField

    @model_validator(mode="after")
    def _check_sample_coherence(self) -> Self:
        """Enforce ADR-0016 §6: the value and its sample count must tell the same story.

        Raises:
            ValueError: If a real value claims no samples, if an unsupported value claims some, or
                if a dispersion is reported for fewer than two samples.
        """
        if is_supported(self.value) and self.sample_count < 1:
            raise ValueError(
                "a metric with a real value must report at least one supported sample; "
                "sample_count=0 with a number in `value` means the number came from nowhere "
                "(ADR-0016 §6)"
            )
        if not is_supported(self.value) and self.sample_count != 0:
            raise ValueError(
                f"an unsupported metric has no supported samples, but sample_count is "
                f"{self.sample_count}. A metric with no supported samples is itself unsupported — "
                "report the attempts elsewhere, not as the denominator of a statistic that was "
                "never computed (ADR-0016 §6)"
            )
        if (
            self.dispersion is not UNSUPPORTED
            and self.sample_count < _MINIMUM_SAMPLES_FOR_DISPERSION
        ):
            raise ValueError(
                f"dispersion needs at least {_MINIMUM_SAMPLES_FOR_DISPERSION} supported samples; "
                f"sample_count is {self.sample_count}. The spread of a single observation is "
                "undefined, not zero — report it as 'unsupported'"
            )
        return self


MetricValueOut, MetricValueIn = payload_models(MetricValueFields)
"""The ``metric.value`` payload pair: ``Out`` for writers, ``In`` for readers."""
