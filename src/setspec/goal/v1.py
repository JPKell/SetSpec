"""Contract module — ``benchmark.goal_pack`` and ``benchmark.calibration_report`` v1.

Imports pydantic and :mod:`baseaicore`; performs no I/O. These two payloads carry FreeWeight's
user-authored goal benchmarks across a boundary: a goal pack so a rubric can move between machines
and be re-run verbatim, and a calibration report so the judge's measured agreement with its author
travels with — and can be audited apart from — the scores it produced
(ADR-0031, ADR-0032).

**The rule these schemas exist to make transportable.** A judged score is a measurement only when
the instrument that produced it has been characterized against ground truth. Everything in
``benchmark.calibration_report`` describes the *judge's* error, never the measured model's
performance, and ``kappa_w`` is never carried without ``n_holdout`` — a coefficient without its
sample count is a number pretending to be a fact.

**Status: frozen (`1.0`).** See :mod:`setspec.model.v1` for what the freeze binds these two
modules to. Their shapes predated FreeWeight Phases 8A–8B actually producing goal packs and
calibration reports; Phase 4's pass against that real output found no field to reshape, and
:data:`setspec.envelope.DRAFT_SCHEMAS` is now empty.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from setspec.base import PayloadDefinition, WireEnum, WireSequence, payload_models
from setspec.capability.v1 import CalibrationFields, JudgeSetFields
from setspec.serialization import TimestampField

__all__ = [
    "CalibrationReportFields",
    "CalibrationReportIn",
    "CalibrationReportOut",
    "CriterionAgreementFields",
    "GoalCriterionFields",
    "GoalPackFields",
    "GoalPackIn",
    "GoalPackOut",
    "GoalTaskFields",
    "ScoringRung",
]

_MINIMUM_WEIGHT = 0.0
_WEIGHT_SUM_TOLERANCE = 1e-6
_MINIMUM_SCALE_POINTS = 3
_MAXIMUM_SCALE_POINTS = 7


class ScoringRung(StrEnum):
    """Which rung of the scoring ladder a criterion is scored at (benchmark catalog §1).

    A ``StrEnum`` so it serializes as its own name. Recording it per criterion is not bookkeeping:
    it is what makes ``score_method_mix`` computable, and therefore what lets a consumer tell a
    score that is mostly rules from a score that is mostly judgement. Those are different kinds of
    number and presenting them identically is the failure this field prevents.
    """

    RULE = "rule"
    """Deterministic check over the output text alone. Free, exact, and never disagrees with you."""

    REFERENCE = "reference"
    """Deterministic check against user-supplied ground truth: an annotated source or claim list."""

    HUMAN = "human"
    """The author graded it themselves, blinded. Validity is 1.0 by definition."""

    JUDGE = "judge"
    """A jury of models graded it. The only rung that requires calibration to mean anything."""


class GoalCriterionFields(PayloadDefinition):
    """One measurable quality within a goal, and how it is scored.

    Attributes:
        key: Stable identifier within the goal. Never renamed — a rename is a new criterion,
            because a renamed criterion whose history merged with the old one would silently
            compare two different measurements.
        name: Human-readable label. Display only, and deliberately **not** a ``goal_hash`` input:
            renaming a criterion for readability must not separate a year of results, while
            changing what it checks must.
        rung: Which ladder rung scores it.
        weight: Its share of the composite, positive and summing to ``1`` across the goal.
        is_gate: Whether failing it zeroes the sample's composite outright. For disqualifying
            properties — a forbidden phrase, invalid JSON — rather than gradual ones.
        rule_type: For a ``rule`` or ``reference`` criterion, which check runs, e.g.
            ``"forbidden_phrases"``. ``None`` for ``human`` and ``judge``.
        scale_points: For a ``judge`` or ``human`` criterion, the ordinal scale's size — 3, 5 or
            7. ``None`` for a deterministic criterion.
        has_scale_descriptors: Whether the ordinal scale carries anchoring descriptors. Always
            ``True`` on a valid judged criterion: an unanchored scale ("rate the tone 1-5")
            reliably produces agreement near zero, so FreeWeight refuses one at authoring time.
            Carried on the wire so an importer can see the rubric was anchored without holding
            the descriptors themselves.
    """

    key: str = Field(min_length=1)
    name: str = Field(min_length=1)
    rung: WireEnum[ScoringRung]
    weight: float = Field(gt=_MINIMUM_WEIGHT, le=1.0)
    is_gate: bool = False
    rule_type: str | None = Field(default=None, min_length=1)
    scale_points: int | None = Field(
        default=None, ge=_MINIMUM_SCALE_POINTS, le=_MAXIMUM_SCALE_POINTS
    )
    has_scale_descriptors: bool = False

    @model_validator(mode="after")
    def _check_rung_shape(self) -> Self:
        """Require the fields a criterion's rung actually needs, and refuse the ones it cannot use.

        Raises:
            ValueError: If a deterministic criterion names no ``rule_type``; if a judged or human
                criterion declares no ``scale_points``; if a judged criterion has no scale
                descriptors; or if a criterion carries a field belonging to a different rung.
        """
        deterministic = self.rung in (ScoringRung.RULE, ScoringRung.REFERENCE)
        graded = self.rung in (ScoringRung.JUDGE, ScoringRung.HUMAN)
        if deterministic and self.rule_type is None:
            raise ValueError(
                f"criterion {self.key!r} is scored at rung {self.rung.value!r} but names no "
                "rule_type. A deterministic criterion is defined by the check it runs."
            )
        if deterministic and self.scale_points is not None:
            raise ValueError(
                f"criterion {self.key!r} is deterministic but declares scale_points. An ordinal "
                "scale belongs to a graded criterion; a rule returns a fraction."
            )
        if graded and self.scale_points is None:
            raise ValueError(
                f"criterion {self.key!r} is graded at rung {self.rung.value!r} but declares no "
                "scale_points. A grade with no scale cannot be compared with another grader's."
            )
        if graded and self.rule_type is not None:
            raise ValueError(
                f"criterion {self.key!r} is graded but names a rule_type. If a rule can check it, "
                "it belongs at rung 'rule' — that is what the authoring lint says, and encoding "
                "both here would make the ladder position ambiguous."
            )
        if self.rung is ScoringRung.JUDGE and not self.has_scale_descriptors:
            raise ValueError(
                f"criterion {self.key!r} is judged but its scale has no descriptors. An "
                "unanchored ordinal scale gives a jury nothing to calibrate against and reliably "
                "produces agreement near zero, so it is refused at authoring time rather than "
                "discovered after the author has graded twelve samples (ADR-0031 §3)."
            )
        return self


class GoalTaskFields(PayloadDefinition):
    """One task the candidate model answers, identified by the prompt that produced it.

    Attributes:
        key: Stable identifier within the goal.
        prompt_id: The task prompt's record ID (ADR-0012 — a task prompt is a prompt record).
        prompt_version: That record's semantic version.
        prompt_sha256: That record's canonical hash, a ``goal_hash`` input.
        is_starter: Whether this is unedited shipped starter content. A goal still running
            entirely on starter tasks measures the starter's author's work rather than the
            importer's, and carrying the flag is what lets a consumer say so.
    """

    key: str = Field(min_length=1)
    prompt_id: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    prompt_sha256: str = Field(min_length=1)
    is_starter: bool = False


class GoalPackFields(PayloadDefinition):
    """Field definitions for ``benchmark.goal_pack``; use :data:`GoalPackOut` / :data:`GoalPackIn`.

    The portable form of a user-authored goal (ADR-0031 §6): enough to re-run the same measurement
    on another machine, and enough for a consumer to decide comparability without asking the
    producer.

    The author's calibration *grades* are deliberately **not** here. They are the subjective
    ground truth and they are large; what travels is the goal's definition plus the agreement it
    achieved, in :class:`CalibrationReportFields`. An importer who wants the rubric held to their
    own taste re-calibrates against their own grades, which is the more honest default anyway.

    Attributes:
        slug: The goal's stable identifier. Its capability is ``user.<slug>``.
        name: Human-readable label.
        intent: The author's own description of what they were trying to get. Not machine-read
            and not a ``goal_hash`` input — it exists so the goal is legible in six months.
        goal_pack_version: Semantic version of this pack. A **major** bump for any change inside
            ``goal_hash``.
        goal_hash: The measurement-defining hash: criteria, weights, rungs, rule parameters, scale
            descriptors, task prompt hashes, the judge prompt hash and the jury configuration.
            Excludes display names, ``intent`` and ``contributes_to``.
        contributes_to: An existing capability root this goal also feeds, or ``None``. When set,
            FreeWeight emits evidence **twice** — once as ``user.<slug>`` keeping the goal's
            identity, once as a weighted source inside the shipped capability — and never only as
            the shipped one, which would fold one person's taste into a term other components
            believe is objective (ADR-0032 §1).
        criteria: The goal's criteria. At least one, weights summing to ``1``.
        tasks: The tasks candidates answer. At least one.
        judge_set: The jury configuration, when any criterion is judged.
        unforked: Whether the criteria and tasks are unedited starter content.
        created_by: Free text the author supplied. Never harvested from the environment.
        created_at: When the pack was authored.
    """

    slug: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(min_length=1)
    intent: str = ""
    goal_pack_version: str = Field(min_length=1)
    goal_hash: str = Field(min_length=1)
    contributes_to: str | None = Field(default=None, min_length=1)
    criteria: WireSequence[GoalCriterionFields] = ()
    tasks: WireSequence[GoalTaskFields] = ()
    judge_set: JudgeSetFields | None = None
    unforked: bool = False
    created_by: str = Field(min_length=1)
    created_at: TimestampField

    @model_validator(mode="after")
    def _check_pack_is_runnable(self) -> Self:
        """Require a pack to define a measurement that could actually be taken.

        Raises:
            ValueError: If there are no criteria or no tasks, if criterion keys collide, if the
                weights do not sum to ``1``, or if a judged criterion exists with no jury to
                score it.
        """
        if not self.criteria:
            raise ValueError(
                f"goal {self.slug!r} declares no criteria. A goal with nothing to measure is not "
                "a benchmark."
            )
        if not self.tasks:
            raise ValueError(
                f"goal {self.slug!r} declares no tasks. Criteria score outputs; with no task "
                "there is no output to score."
            )
        keys = [criterion.key for criterion in self.criteria]
        duplicates = sorted({key for key in keys if keys.count(key) > 1})
        if duplicates:
            raise ValueError(
                f"goal {self.slug!r} declares criteria {duplicates} more than once. A criterion "
                "key identifies a measurement over time, so a collision merges two of them."
            )
        total = sum(criterion.weight for criterion in self.criteria)
        if abs(total - 1.0) > _WEIGHT_SUM_TOLERANCE:
            raise ValueError(
                f"goal {self.slug!r} has criterion weights summing to {total}, not 1. The "
                "composite is a weighted mean, so weight that is unaccounted for changes every "
                "criterion's real share rather than only the total."
            )
        judged = [c.key for c in self.criteria if c.rung is ScoringRung.JUDGE]
        if judged and self.judge_set is None:
            raise ValueError(
                f"goal {self.slug!r} has judged criteria {judged} but no judge_set. A judged "
                "score is a property of the jury that produced it; without the jury's identity "
                "the result cannot be separated from one produced by a different instrument "
                "(ADR-0032 §4)."
            )
        return self


GoalPackOut, GoalPackIn = payload_models(GoalPackFields)
"""The ``benchmark.goal_pack`` payload pair: ``Out`` for writers, ``In`` for readers."""


class CriterionAgreementFields(PayloadDefinition):
    """One judged criterion's measured agreement between the jury and the goal's author.

    Attributes:
        criterion_key: Which criterion this describes.
        weight: Its share of the composite, so a reader can weight the agreement figures the same
            way the score weighted the criteria.
        agreement: The agreement statistics for this criterion, including the ``n_holdout`` that
            makes ``kappa_w`` interpretable.
        inter_juror_alpha: Krippendorff's alpha across jurors on this criterion, or ``None`` for a
            single-juror jury — where the quantity does not exist rather than being zero. This is
            what distinguishes jury bias from jury noise: high alpha with low ``kappa_w`` means
            the jurors agree with each other and not with the author.
        judge_validity_factor: This criterion's contribution to the goal's validity factor:
            ``max(0, kappa_w) * min(1, sqrt(n_holdout / n_holdout_target))`` (ADR-0032 §2).
    """

    criterion_key: str = Field(min_length=1)
    weight: float = Field(gt=_MINIMUM_WEIGHT, le=1.0)
    agreement: CalibrationFields
    inter_juror_alpha: float | None = Field(default=None, ge=-1.0, le=1.0)
    judge_validity_factor: float = Field(ge=0.0, le=1.0)


class CalibrationReportFields(PayloadDefinition):
    """Field definitions for ``benchmark.calibration_report``; use :data:`CalibrationReportOut` /
    :data:`CalibrationReportIn`.

    How well the jury agreed with the person whose goal this is, per criterion and weighted, and
    whether that was enough to let the goal emit capability evidence at all.

    This payload exists separately from ``capability.evidence`` because it is meaningful when no
    evidence was emitted. A failed gate is the case a user most needs to see and the case the
    evidence contract deliberately says nothing about: below the threshold FreeWeight emits no
    evidence record, so without this report the most informative outcome would be invisible on the
    wire (ADR-0032 §3).

    Attributes:
        goal_slug: Which goal was calibrated.
        goal_hash: The exact rubric the agreement was measured against. Agreement measured on one
            rubric says nothing about another, so this is not optional provenance.
        judge_set: The jury the agreement was measured for. Change the jury and the report no
            longer applies.
        criteria: Per-criterion agreement, for judged criteria only. Empty when a goal is scored
            entirely by rules — a legitimate and desirable state, not a failure.
        weighted_kappa_w: Weighted across judged criteria; the value the gate compares. ``None``
            when there are no judged criteria to weight.
        min_agreement: The gate threshold in force, recorded because it is configuration and a
            reader must not assume the default.
        passed_gate: Whether evidence was emitted. ``True`` for a goal with no judged criteria:
            nothing needed calibrating, so nothing failed to calibrate.
        judge_validity_factor: The goal-level factor that multiplied into confidence.
        n_anchor: Graded samples used as judge-prompt exemplars.
        n_holdout: Graded samples withheld from the jury — the basis of every figure above.
        partition_seed: The seed that produced the anchor/holdout split, so the partition is
            reproducible and a reader can verify the holdout was not chosen to flatter the result.
        graded_by: Free text identifying the grader.
        measured_at: When this calibration was measured. Ages like evidence.
        policy_version: The calibration-policy version these figures were computed under.
    """

    goal_slug: str = Field(min_length=1)
    goal_hash: str = Field(min_length=1)
    judge_set: JudgeSetFields | None = None
    criteria: WireSequence[CriterionAgreementFields] = ()
    weighted_kappa_w: float | None = Field(default=None, ge=-1.0, le=1.0)
    min_agreement: float = Field(ge=-1.0, le=1.0)
    passed_gate: bool
    judge_validity_factor: float = Field(ge=0.0, le=1.0)
    n_anchor: int = Field(ge=0)
    n_holdout: int = Field(ge=0)
    partition_seed: int
    graded_by: str = Field(min_length=1)
    measured_at: TimestampField
    policy_version: str = Field(min_length=1)

    @model_validator(mode="after")
    def _check_report_coheres(self) -> Self:
        """Require the report's verdict to follow from the figures it carries.

        Raises:
            ValueError: If a judged goal reports no weighted agreement; if the gate verdict
                contradicts the threshold comparison; if a judged report names no jury; or if a
                goal with judged criteria reports no holdout to have measured them on.
        """
        if self.criteria and self.weighted_kappa_w is None:
            raise ValueError(
                f"goal {self.goal_slug!r} reports per-criterion agreement but no "
                "weighted_kappa_w. The weighted figure is what the gate compares, so a report "
                "without it cannot explain its own verdict."
            )
        if self.criteria and self.judge_set is None:
            raise ValueError(
                f"goal {self.goal_slug!r} reports judged-criterion agreement with no judge_set. "
                "Agreement is a property of a particular jury (ADR-0032 §4)."
            )
        if self.criteria and self.n_holdout < 1:
            raise ValueError(
                f"goal {self.goal_slug!r} reports judged-criterion agreement over "
                f"{self.n_holdout} held-out samples. Agreement measured over nothing is not a "
                "measurement, and a coefficient without a holdout to stand on is the exact "
                "failure n_holdout travels everywhere to prevent."
            )
        if self.weighted_kappa_w is not None:
            expected = self.weighted_kappa_w >= self.min_agreement
            if self.passed_gate is not expected:
                raise ValueError(
                    f"goal {self.goal_slug!r} reports passed_gate={self.passed_gate} with "
                    f"weighted_kappa_w={self.weighted_kappa_w} against min_agreement="
                    f"{self.min_agreement}. The verdict is the comparison; a report whose verdict "
                    "disagrees with its own numbers cannot be audited by the person it is for."
                )
        elif not self.passed_gate:
            raise ValueError(
                f"goal {self.goal_slug!r} has no judged criteria but reports passed_gate=False. "
                "A goal scored entirely by rules has nothing to calibrate, so there is nothing "
                "for it to fail — and marking it failed would penalize the most deterministic "
                "rubric a user can write."
            )
        return self


CalibrationReportOut, CalibrationReportIn = payload_models(CalibrationReportFields)
"""The ``benchmark.calibration_report`` payload pair: ``Out`` for writers, ``In`` for readers."""
