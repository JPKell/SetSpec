"""Contract module — ``capability.evidence`` and ``benchmark.evidence_bundle`` v1.

Imports pydantic and :mod:`baseaicore`; performs no I/O. This is the suite's most load-bearing
cross-application contract — the entire FreeWeight → LoadCoach value proposition
(ADR-0022) — so
``CapabilityEvidenceFields`` reproduces
ADR-0022 §1's normative field
table verbatim rather than approximating it: every field name, type and meaning below has that
table as its direct source, not this module's own judgment.

**Status: frozen (`1.0`).** See :mod:`setspec.model.v1` for what the freeze binds this module to.
FreeWeight's real aggregation — the thing this module was written ahead of — reached
[Phase 4](../../../docs/packages/setspec/development-plan.md) needing no field reshaped, which is
what the freeze records. ``CapabilityEvidenceFields`` itself is never edited again, and neither is
its use inside :class:`EvidenceBundleFields` — both keep meaning exactly what they mean today.

[Phase 6](../../../docs/packages/setspec/development-plan.md) adds `1.1` alongside it, as
:class:`CapabilityEvidenceV1_1Fields`: an optional ``adapter`` field (ADR-0058), absent — and
therefore byte-for-byte identical to `1.0` — on every record measured on a bare base. This is the
package's first minor bump on an already-frozen payload, and a **new, version-suffixed symbol**
rather than an edit in place is the pattern future minors should follow, for a structural reason:
:class:`EvidenceBundleFields` embeds ``CapabilityEvidenceFields`` *by reference*, so generating its
JSON Schema walks into that class's own fields and docstring. Editing ``CapabilityEvidenceFields``
in place — even just its docstring — would silently change the committed
``benchmark.evidence_bundle`` `1.0` snapshot too, a schema this row does not touch and FreeWeight
does not export adapter-bearing bundles into until LA3. A sibling class, left to inherit
unchanged, is what keeps that blast radius at zero. Producers wanting the `1.1` shape import
:data:`CapabilityEvidenceV1_1Out` / :data:`CapabilityEvidenceV1_1In` explicitly;
:data:`CapabilityEvidenceOut` / :data:`CapabilityEvidenceIn` keep meaning `1.0`, exactly as today.
"""

from __future__ import annotations

from typing import Any, Self

from baseaicore import CapabilityId
from baseaicore import ValidationError as SuiteValidationError
from pydantic import Field, SerializerFunctionWrapHandler, model_serializer, model_validator

from setspec import vocabulary
from setspec.base import PayloadDefinition, WireSequence, payload_models
from setspec.model.v1 import AdapterIdentityFields, ModelIdentityFields
from setspec.provenance import EnvironmentFields
from setspec.serialization import MeasurementField, TimestampField

__all__ = [
    "CalibrationFields",
    "CapabilityEvidenceFields",
    "CapabilityEvidenceIn",
    "CapabilityEvidenceOut",
    "CapabilityEvidenceV1_1Fields",
    "CapabilityEvidenceV1_1In",
    "CapabilityEvidenceV1_1Out",
    "ContributingMetricFields",
    "EvidenceBundleFields",
    "EvidenceBundleIn",
    "EvidenceBundleOut",
    "JudgeSetFields",
]

_MINIMUM_CONFIDENCE = 0.05
_MAXIMUM_SCORE_OR_CONFIDENCE = 1.0
_GOAL_NAMESPACE_ROOT = "user"
_SCORE_METHOD_RUNGS: frozenset[str] = frozenset({"rule", "reference", "human", "judge"})
_METHOD_MIX_TOLERANCE = 1e-6


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


class JudgeSetFields(PayloadDefinition):
    """The instrument that produced a judged score — a hard-separation input (ADR-0032 §4).

    A different jury is a different instrument, and therefore a different measurement. This is
    recorded rather than summarized because a consumer must be able to decide comparability
    without asking the producer, exactly as it does for a benchmark version.

    Attributes:
        jurors: Canonical model IDs of the jury members, in the order they were polled. Two or
            more is the documented default; one is permitted and loses the inter-juror agreement
            that distinguishes bias from noise, which is why the count is visible here rather
            than folded into a summary figure.
        prompt_id: The judge prompt record's ID (ADR-0012 — a judge rubric is a prompt record).
        prompt_version: That record's semantic version.
        prompt_sha256: That record's canonical hash, so a consumer can separate on the prompt
            without holding the prompt.
        remote: Whether any juror ran outside the measuring machine. Locally-judged and
            remotely-judged results are **separated**, never merged (ADR-0031 §4), so this is a
            comparability input and not a footnote.
    """

    jurors: WireSequence[str] = ()
    prompt_id: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    prompt_sha256: str = Field(min_length=1)
    remote: bool


class CalibrationFields(PayloadDefinition):
    """How closely the judge agreed with the person whose goal this is (ADR-0031 §3).

    This is what separates an instrument from an opinion. Every field here describes the *judge's*
    error against user-supplied ground truth, not the measured model's performance.

    Attributes:
        kappa_w: Quadratic-weighted Cohen's kappa between the user's grades and the jury median
            over the holdout, weighted across judged criteria. Ordinal-aware and chance-corrected;
            legitimately negative when the judge disagrees with the user worse than chance would.
        rho: Spearman rank correlation — whether the judge ranks as the user ranks.
        mae: Mean absolute error in scale points. Non-negative, and in the units the user thinks
            in rather than a coefficient they must interpret.
        bias: Mean signed error. Negative means the judge grades harsher than the user, positive
            more generously. Unbounded here because its scale is the criterion's, which this
            payload does not carry.
        n_anchor: Graded samples embedded in the judge prompt as exemplars. May be zero: a rubric
            may be calibrated without few-shot anchoring.
        n_holdout: Graded samples the judge was **never shown**, which is the only honest basis
            for :attr:`kappa_w`. At least one, because agreement measured over nothing is not a
            measurement — and it travels with the coefficient everywhere precisely so a reader
            cannot see ``kappa_w`` without seeing what it was computed over.
        graded_by: Free text the user supplied identifying the grader. Never an account name or
            an address harvested from the environment.
        measured_at: When the calibration was measured. Ages like evidence: a rubric calibrated a
            year ago against a jury that has since changed is stale in the same sense a benchmark
            result is.
    """

    kappa_w: float = Field(ge=-1.0, le=1.0)
    rho: float = Field(ge=-1.0, le=1.0)
    mae: float = Field(ge=0.0)
    bias: float
    n_anchor: int = Field(ge=0)
    n_holdout: int = Field(ge=1)
    graded_by: str = Field(min_length=1)
    measured_at: TimestampField


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
        judge_validity_factor: The sixth confidence factor (ADR-0032 §2). **``1.0`` for every
            measurement scored at ladder rungs 1–4**, which is every native and external
            benchmark in the suite — so this field changed no existing number when it was added.
            Below ``1.0`` only for a user-defined goal's judged criteria, in proportion to the
            judge's measured agreement with the user and shrunk toward zero when the holdout is
            small. Already multiplied into :attr:`confidence`; carried separately so a consumer
            can *see* it without recomputing the formula.
        goal_hash: The measurement-defining hash of the goal that produced this record, when one
            did. A hard-separation input: a different rubric is a different measurement, exactly
            as a different benchmark version is (ADR-0032 §4).
        goal_pack_version: The goal pack's semantic version. Provenance; :attr:`goal_hash` is
            what separates.
        score_method_mix: Fraction of scored weight by ladder rung, e.g.
            ``{"rule": 0.6, "judge": 0.4}``. Keys are drawn from ``rule``, ``reference``,
            ``human`` and ``judge``; the values sum to ``1``. A ``0.82`` that is 80 % rules is a
            different kind of number from a ``0.82`` that is 80 % judgement, and a consumer that
            cannot tell them apart will eventually present them as the same thing.
        judge_set: The jury that produced any judged portion — a hard-separation input.
        calibration: The judge's measured agreement with the user. Present whenever a judged
            criterion contributed; absent for a goal scored entirely by rules.
        uncalibrated: Always ``False`` on a record that exists, and refused as ``True`` by
            :meth:`_check_goal_fields_cohere`. A goal below its calibration gate emits **no
            record at all** rather than a discounted one (ADR-0032 §3), so a ``True`` here means a
            producer bug — one worth catching on the wire, where it is one field, rather than in a
            routing decision months later, where it is a mystery.
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
    # Goal-sourced group (ADR-0032 §5). Every field is optional and absent on a non-goal record,
    # which is what makes this a minor schema change rather than a major one.
    judge_validity_factor: float = Field(
        default=1.0, ge=_MINIMUM_CONFIDENCE, le=_MAXIMUM_SCORE_OR_CONFIDENCE
    )
    goal_hash: str | None = Field(default=None, min_length=1)
    goal_pack_version: str | None = Field(default=None, min_length=1)
    score_method_mix: dict[str, float] | None = None
    judge_set: JudgeSetFields | None = None
    calibration: CalibrationFields | None = None
    uncalibrated: bool = False

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

    @model_validator(mode="after")
    def _check_goal_fields_cohere(self) -> Self:
        """Enforce the goal-sourced group's internal rules (ADR-0032 §1–§5).

        Five rules, each closing a way a subjective score could quietly acquire authority it has
        not earned:

        1. ``uncalibrated`` is never ``True``. The gate withholds the record entirely rather
           than emitting a discounted one, so a record that says it is uncalibrated is one the
           producer should not have written.
        2. A ``user.*`` capability carries a ``goal_hash``. Without it the record cannot be
           separated from a differently-defined goal of the same name.
        3. A record with no ``goal_hash`` has ``judge_validity_factor`` exactly ``1.0``. Nothing
           but a goal can discount validity, and a discount with no goal attached is unexplainable.
        4. A discounted ``judge_validity_factor`` carries the ``calibration`` it came from. The
           number is derived from measured agreement; without that agreement it is an assertion.
        5. A ``calibration`` carries the ``judge_set`` it measured. Agreement is a property of a
           particular jury, and a jury change separates results — so agreement without the jury's
           identity cannot be applied.

        Raises:
            ValueError: If any of the five rules is broken, naming which and why.
        """
        if self.uncalibrated:
            raise ValueError(
                "uncalibrated must be False on an emitted record. A goal below its calibration "
                "gate emits no capability.evidence at all — not a discounted record "
                "(ADR-0032 §3). A True here means the producer wrote a record the gate should "
                "have withheld."
            )
        root = CapabilityId(self.capability_id).root
        if root == _GOAL_NAMESPACE_ROOT and self.goal_hash is None:
            raise ValueError(
                f"capability_id {self.capability_id!r} is in the reserved 'user' namespace but "
                "carries no goal_hash. A goal's identity is its hash, not its slug: two people's "
                "'user.house_voice' are different measurements, and without the hash a consumer "
                "cannot separate them (ADR-0032 §4)."
            )
        if self.goal_hash is None and self.judge_validity_factor != 1.0:
            raise ValueError(
                f"judge_validity_factor is {self.judge_validity_factor} on a record with no "
                "goal_hash. Only a user-defined goal's judged criteria can reduce validity; "
                "every rung 1-4 measurement is exactly 1.0 (ADR-0032 §2)."
            )
        if self.judge_validity_factor < 1.0 and self.calibration is None:
            raise ValueError(
                f"judge_validity_factor is {self.judge_validity_factor} but no calibration is "
                "present. The factor is derived from measured judge-user agreement; without the "
                "calibration it came from it is an assertion, and a consumer cannot audit it."
            )
        if self.calibration is not None and self.judge_set is None:
            raise ValueError(
                "calibration is present but judge_set is not. Agreement is a property of a "
                "particular jury — change the jury and the agreement no longer applies — so the "
                "jury's identity travels with it (ADR-0032 §4)."
            )
        return self

    @model_validator(mode="after")
    def _check_score_method_mix(self) -> Self:
        """Require ``score_method_mix`` to name known ladder rungs and to sum to ``1``.

        Raises:
            ValueError: If a key is not one of ``rule``, ``reference``, ``human`` or ``judge``, if
                a fraction falls outside ``[0, 1]``, or if the fractions do not sum to ``1``. A
                mix that does not sum to one describes scored weight that went somewhere
                unaccounted for, which makes every share in it wrong rather than merely
                incomplete.
        """
        if self.score_method_mix is None:
            return self
        unknown = sorted(set(self.score_method_mix) - _SCORE_METHOD_RUNGS)
        if unknown:
            raise ValueError(
                f"score_method_mix names unknown scoring rungs {unknown}. The ladder's rungs are "
                f"{sorted(_SCORE_METHOD_RUNGS)} (benchmark catalog §1)."
            )
        out_of_range = sorted(k for k, v in self.score_method_mix.items() if not 0.0 <= v <= 1.0)
        if out_of_range:
            raise ValueError(
                f"score_method_mix values must be fractions in [0, 1]; {out_of_range} are not."
            )
        total = sum(self.score_method_mix.values())
        if abs(total - 1.0) > _METHOD_MIX_TOLERANCE:
            raise ValueError(
                f"score_method_mix sums to {total}, not 1. It describes how the scored weight was "
                "divided, so weight that is unaccounted for makes every share in the mix wrong, "
                "not merely the total."
            )
        return self


CapabilityEvidenceOut, CapabilityEvidenceIn = payload_models(CapabilityEvidenceFields)
"""The ``capability.evidence`` `1.0` payload pair: ``Out`` for writers, ``In`` for readers."""


class CapabilityEvidenceV1_1Fields(CapabilityEvidenceFields):
    """Field definitions for ``capability.evidence`` `1.1`; use
    :data:`CapabilityEvidenceV1_1Out` / :data:`CapabilityEvidenceV1_1In`.

    Adds one optional field to :class:`CapabilityEvidenceFields` (ADR-0058): a record measured on
    the bare base carries no ``adapter`` and is therefore byte-for-byte what `1.0` writes today —
    the additive proof this minor bump rests on, golden-tested in
    ``goldens/capability.evidence/1.0`` (unchanged) versus ``goldens/capability.evidence/1.1``
    (adding an adapter-bearing example).

    Attributes:
        adapter: The adapter this measurement was taken under, or ``None`` for the bare base.
            Evidence on ``(base, adapter)`` applies to that subject and nothing else — not to the
            bare base, not to a different adapter (ADR-0058 §4, ADR-0059).
    """

    adapter: AdapterIdentityFields | None = None

    @model_serializer(mode="wrap")
    def _omit_absent_adapter(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        """Drop ``adapter`` from the dump when it is absent, rather than emitting ``null``.

        Pydantic's default dump includes every declared field, so a bare ``adapter: None``
        default would still serialize as an explicit ``"adapter": null`` key — a byte this
        module's whole `1.0`/`1.1` split exists to avoid. A record with no adapter must dump
        **exactly** what `1.0` writes today, not `1.0`'s bytes plus one new null (I15, LA0 exit
        condition). No other field in this package needs this treatment: they all predate the
        freeze, so their ``null`` was already part of `1.0`'s own shape.
        """
        data: dict[str, Any] = handler(self)
        if self.adapter is None:
            data.pop("adapter", None)
        return data


CapabilityEvidenceV1_1Out, CapabilityEvidenceV1_1In = payload_models(CapabilityEvidenceV1_1Fields)
"""The ``capability.evidence`` `1.1` payload pair: ``Out`` for writers, ``In`` for readers."""


class EvidenceBundleFields(PayloadDefinition):
    """Field definitions for ``benchmark.evidence_bundle``; use :data:`EvidenceBundleOut` /
    :data:`EvidenceBundleIn`.

    The FreeWeight → LoadCoach payload: many :class:`CapabilityEvidenceFields` records, plus the
    one flag that makes incremental import possible
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
        evidence: The evidence records themselves, at the `1.0` shape this schema has always
            published — see the module docstring for why this row's `1.1` adapter field does not
            reach here.
    """

    source_id: str = Field(min_length=1)
    complete: bool
    evidence: WireSequence[CapabilityEvidenceFields] = ()


EvidenceBundleOut, EvidenceBundleIn = payload_models(EvidenceBundleFields)
"""The ``benchmark.evidence_bundle`` payload pair: ``Out`` for writers, ``In`` for readers."""
