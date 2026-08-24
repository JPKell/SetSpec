"""Contract module — ``capability.evidence`` and ``benchmark.evidence_bundle`` v1.

Imports pydantic and :mod:`baseaicore`; performs no I/O. This is the suite's most load-bearing
cross-application contract — the entire FreeWeight → LoadCoach value proposition
(ADR-0022) — so
``CapabilityEvidenceFields`` reproduces
ADR-0022 §1's normative field
table verbatim rather than approximating it: every field name, type and meaning below has that
table as its direct source, not this module's own judgment.

**Status: draft (`1.0`).** See :mod:`setspec.model.v1` for what that means; here it means
specifically that this module predates FreeWeight actually aggregating evidence, so
[Phase 4](../../../docs/packages/setspec/development-plan.md) may still adjust a field that turns
out to be shaped wrong once real aggregation exists to shape it against.
"""

from __future__ import annotations

from typing import Self

from baseaicore import ValidationError as SuiteValidationError
from pydantic import Field, model_validator

from setspec import vocabulary
from setspec.base import PayloadDefinition, WireSequence, payload_models
from setspec.model.v1 import ModelIdentityFields
from setspec.provenance import EnvironmentFields
from setspec.serialization import MeasurementField, TimestampField

__all__ = [
    "CapabilityEvidenceFields",
    "CapabilityEvidenceIn",
    "CapabilityEvidenceOut",
    "ContributingMetricFields",
    "EvidenceBundleFields",
    "EvidenceBundleIn",
    "EvidenceBundleOut",
]

_MINIMUM_CONFIDENCE = 0.05
_MAXIMUM_SCORE_OR_CONFIDENCE = 1.0


class ContributingMetricFields(PayloadDefinition):
    """One benchmark metric's contribution to a capability score.

    Attributes:
        metric_key: The metric's identifier within its benchmark, e.g. ``"task_success"``.
        weight: This metric's weight in the score it contributed to. Positive — a zero or
            negative weight would mean the metric contributed nothing or inverted another's
            effect, either of which belongs in how the score was computed, not in a record of
            what happened.
        sample_count: Supported samples this metric contributed, matching the same
            excluded-is-not-counted rule as every other sample count in this package
            (ADR-0016 §6).
    """

    metric_key: str = Field(min_length=1)
    weight: float = Field(gt=0.0)
    sample_count: int = Field(ge=0)


class CapabilityEvidenceFields(PayloadDefinition):
    """Field definitions for ``capability.evidence``; use :data:`CapabilityEvidenceOut` /
    :data:`CapabilityEvidenceIn`.

    Attributes:
        model: The measured weights (ADR-0024).
        runtime_profile_hash: The profile the measurement was taken under (ADR-0023).
        machine_fingerprint: Where it was measured.
        capability_id: A term in the SetSpec vocabulary; checked against
            :func:`setspec.vocabulary.validate_capability` using :attr:`vocabulary_version` for
            the forward-compatibility exception — see :meth:`_check_capability_id`.
        score: The capability score, ``0`` to ``1`` inclusive.
        confidence: Computed by FreeWeight per
            ADR-0017; floored at
            ``0.05`` by that formula's own clamp, never truly zero.
        sample_count: Supported samples that produced ``score``.
        excluded_count: Samples excluded, with the exclusion visible rather than folded silently
            into a lower ``sample_count``.
        dispersion: Coefficient of variation for a continuous metric, or disagreement rate for a
            pass/fail one — ADR-0017 defines which applies from the metric's own kind, not from a
            flag carried here.
        measured_at: The **latest ``completed_at`` among the contributing runs** — what
            ``freshness_factor`` decays from. Never the aggregation time.
        computed_at: When this aggregation ran. Provenance and the incremental-export filter
            input; never a confidence input — recomputing evidence must not make it look fresher
            (ADR-0022 §2), and
            :meth:`_check_measured_before_computed` enforces the one shape that rule requires:
            ``measured_at`` cannot be later than the aggregation that used it.
        policy_version: The confidence-policy version this evidence was computed under.
        vocabulary_version: The capability-vocabulary version ``capability_id`` was validated
            against when this evidence was produced.
        benchmark_versions: Suite key to version — a hard-separation input.
        dataset_hashes: A hard-separation input.
        prompt_subset_hashes: Hash **per benchmark key, not per pack**
            (ADR-0028) — a hard-separation
            input.
        contributing_metrics: Which benchmark metrics fed this score, with what weight and how
            many samples.
        source_run_ids: Producer-local run IDs. A consumer stores these opaquely and never
            resolves them.
        environment: Provider kind and version, GPU driver, CUDA, OS version at measurement.
    """

    model: ModelIdentityFields
    runtime_profile_hash: str = Field(min_length=1)
    machine_fingerprint: str = Field(min_length=1)
    capability_id: str = Field(min_length=1)
    score: float = Field(ge=0.0, le=_MAXIMUM_SCORE_OR_CONFIDENCE)
    confidence: float = Field(ge=_MINIMUM_CONFIDENCE, le=_MAXIMUM_SCORE_OR_CONFIDENCE)
    sample_count: int = Field(ge=0)
    excluded_count: int = Field(ge=0)
    dispersion: MeasurementField
    measured_at: TimestampField
    computed_at: TimestampField
    policy_version: str = Field(min_length=1)
    vocabulary_version: str = Field(min_length=1)
    benchmark_versions: dict[str, str] = Field(default_factory=dict)
    dataset_hashes: dict[str, str] = Field(default_factory=dict)
    prompt_subset_hashes: dict[str, str] = Field(default_factory=dict)
    contributing_metrics: WireSequence[ContributingMetricFields] = ()
    source_run_ids: WireSequence[str] = ()
    environment: EnvironmentFields

    @model_validator(mode="after")
    def _check_capability_id(self) -> Self:
        """Validate ``capability_id`` against the vocabulary at ``vocabulary_version``.

        Raises:
            ValueError: If ``capability_id`` is syntactically invalid, or its root is unrecognized
                and :attr:`vocabulary_version` does not prove forward compatibility.
        """
        try:
            vocabulary.validate_capability(
                self.capability_id, vocabulary_version=self.vocabulary_version
            )
        except SuiteValidationError as exc:
            raise ValueError(str(exc)) from exc
        return self

    @model_validator(mode="after")
    def _check_measured_before_computed(self) -> Self:
        """Require ``measured_at`` not to be later than ``computed_at``.

        Raises:
            ValueError: If ``measured_at`` follows ``computed_at`` — incoherent, since
                ``computed_at`` is when the aggregation ran and cannot precede what it aggregated
                (ADR-0022 §2).
        """
        if self.measured_at > self.computed_at:
            raise ValueError(
                f"measured_at ({self.measured_at.isoformat()}) is later than computed_at "
                f"({self.computed_at.isoformat()}). computed_at is when this aggregation ran and "
                "cannot precede the measurement it aggregated — freshness decays from "
                "measured_at, never computed_at, precisely so this cannot be gamed by "
                "recomputing (ADR-0022 §2)."
            )
        return self


CapabilityEvidenceOut, CapabilityEvidenceIn = payload_models(CapabilityEvidenceFields)
"""The ``capability.evidence`` payload pair: ``Out`` for writers, ``In`` for readers."""


class EvidenceBundleFields(PayloadDefinition):
    """Field definitions for ``benchmark.evidence_bundle``; use :data:`EvidenceBundleOut` /
    :data:`EvidenceBundleIn`.

    The FreeWeight → LoadCoach payload: many :class:`CapabilityEvidenceFields`, plus the one flag
    that makes incremental import possible
    (ADR-0022 §5).
    ``generated_at`` is **not** repeated here: it lives on the enclosing
    :class:`~setspec.envelope.SchemaEnvelope`, and a client stores *that* value to send back as its
    next ``?since=`` — duplicating it on the payload would create two timestamps that could
    disagree about when this bundle was produced.

    Attributes:
        source_id: Which FreeWeight instance produced this bundle — part of a consumer's
            uniqueness key alongside ``canonical_id``, ``runtime_profile_hash``,
            ``machine_fingerprint``, ``capability_id`` and ``policy_version``.
        complete: ``True`` only for a full export. Only a complete bundle lets a consumer infer
            removal: evidence present locally for this ``source_id`` and absent from a complete
            bundle is marked superseded — never deleted, and never inferred from a partial one.
        evidence: The evidence records themselves.
    """

    source_id: str = Field(min_length=1)
    complete: bool
    evidence: WireSequence[CapabilityEvidenceFields] = ()


EvidenceBundleOut, EvidenceBundleIn = payload_models(EvidenceBundleFields)
"""The ``benchmark.evidence_bundle`` payload pair: ``Out`` for writers, ``In`` for readers."""
