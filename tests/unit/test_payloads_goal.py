"""Tests for ``benchmark.goal_pack`` and ``benchmark.calibration_report``
(:mod:`setspec.goal.v1`), and for the goal-sourced field group on ``capability.evidence``.

The rule under test throughout is ADR-0031's: a judged score is a measurement only when the
instrument that produced it has been characterized against ground truth. Every refusal asserted
here closes one way a subjective number could acquire authority it has not earned — a coefficient
with no holdout, a validity discount with no calibration behind it, agreement with no jury
attached, a verdict that contradicts its own figures.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError as PydanticValidationError

from setspec import DRAFT_SCHEMAS, SUPPORTED_SCHEMAS, canonical_dumps
from setspec.capability.v1 import CapabilityEvidenceOut
from setspec.goal.v1 import (
    CalibrationReportOut,
    GoalCriterionFields,
    GoalPackIn,
    GoalPackOut,
    ScoringRung,
)

_CREATED_AT = datetime(2026, 8, 14, 9, 0, 0, tzinfo=UTC)
_MEASURED_AT = datetime(2026, 8, 14, 9, 30, 0, tzinfo=UTC)
_COMPUTED_AT = datetime(2026, 8, 22, tzinfo=UTC)


def _judge_set(**overrides: Any) -> dict[str, Any]:
    """A minimal, valid judge_set: a three-model local jury."""
    return {
        "jurors": [
            "ollama/qwen3:14b@sha256:1f3a",
            "ollama/gemma3:12b@sha256:2b7c",
            "ollama/mistral-small:24b@sha256:9e41",
        ],
        "prompt_id": "goals.judge.rubric",
        "prompt_version": "1.0.0",
        "prompt_sha256": "sha256:" + "c" * 64,
        "remote": False,
    } | overrides


def _agreement(**overrides: Any) -> dict[str, Any]:
    """A calibration block at the 'good' band: usable, visibly imperfect."""
    return {
        "kappa_w": 0.71,
        "rho": 0.68,
        "mae": 0.6,
        "bias": -0.1,
        "n_anchor": 7,
        "n_holdout": 5,
        "graded_by": "Jordan",
        "measured_at": _MEASURED_AT.isoformat(),
    } | overrides


def _rule_criterion(**overrides: Any) -> dict[str, Any]:
    return {
        "key": "no_llm_tells",
        "name": "No LLM tells",
        "rung": "rule",
        "weight": 0.6,
        "is_gate": True,
        "rule_type": "forbidden_phrases",
    } | overrides


def _judged_criterion(**overrides: Any) -> dict[str, Any]:
    return {
        "key": "dry_wit",
        "name": "Dry wit, never winking",
        "rung": "judge",
        "weight": 0.4,
        "scale_points": 5,
        "has_scale_descriptors": True,
    } | overrides


def _goal_pack(**overrides: Any) -> dict[str, Any]:
    """A mixed-rung goal: 60 % rules, 40 % judged. The shape the starter packs teach."""
    return {
        "slug": "noir_tech_voice",
        "name": "Noir-ish tech essay voice",
        "intent": "Essays that sound like me: dry, concrete, unhurried.",
        "goal_pack_version": "1.2.0",
        "goal_hash": "sha256:" + "4" * 64,
        "contributes_to": "creative_writing",
        "criteria": [_rule_criterion(), _judged_criterion()],
        "tasks": [
            {
                "key": "001",
                "prompt_id": "goals.noir_tech_voice.task_001",
                "prompt_version": "1.0.0",
                "prompt_sha256": "sha256:" + "d" * 64,
                "is_starter": False,
            }
        ],
        "judge_set": _judge_set(),
        "unforked": False,
        "created_by": "Jordan",
        "created_at": _CREATED_AT.isoformat(),
    } | overrides


def _calibration_report(**overrides: Any) -> dict[str, Any]:
    return {
        "goal_slug": "noir_tech_voice",
        "goal_hash": "sha256:" + "4" * 64,
        "judge_set": _judge_set(),
        "criteria": [
            {
                "criterion_key": "dry_wit",
                "weight": 0.4,
                "agreement": _agreement(),
                "inter_juror_alpha": 0.83,
                "judge_validity_factor": 0.5,
            }
        ],
        "weighted_kappa_w": 0.71,
        "min_agreement": 0.40,
        "passed_gate": True,
        "judge_validity_factor": 0.8,
        "n_anchor": 7,
        "n_holdout": 5,
        "partition_seed": 0,
        "graded_by": "Jordan",
        "measured_at": _MEASURED_AT.isoformat(),
        "policy_version": "1.0",
    } | overrides


def _goal_evidence(**overrides: Any) -> dict[str, Any]:
    """capability.evidence for a calibrated goal, in the reserved user namespace."""
    return {
        "model": {
            "provider_kind": "ollama",
            "provider_model_name": "qwen3.5:9b-q8_0",
            "artifact_digest": None,
            "identity_confidence": "name_only",
            "canonical_id": "ollama/qwen3.5:9b-q8_0@unknown",
            "observed_at": _CREATED_AT.isoformat(),
        },
        "runtime_profile_hash": "a" * 16,
        "machine_fingerprint": "b" * 64,
        "capability_id": "user.noir_tech_voice",
        "score": 0.74,
        "confidence": 0.31,
        "sample_count": 40,
        "excluded_count": 0,
        "dispersion": 0.09,
        "measured_at": _MEASURED_AT.isoformat(),
        "computed_at": _COMPUTED_AT.isoformat(),
        "policy_version": "1.0",
        "vocabulary_version": "1.1",
        "environment": {"provider_kind": "ollama", "provider_version": "0.32.13"},
        "judge_validity_factor": 0.55,
        "goal_hash": "sha256:" + "4" * 64,
        "goal_pack_version": "1.2.0",
        "score_method_mix": {"rule": 0.6, "judge": 0.4},
        "judge_set": _judge_set(),
        "calibration": _agreement(),
        "uncalibrated": False,
    } | overrides


class TestSchemasAreRegistered:
    """A payload nobody can negotiate for is a payload that does not exist on the wire."""

    @pytest.mark.parametrize("schema", ["benchmark.goal_pack", "benchmark.calibration_report"])
    def test_the_schema_is_registered(self, schema: str) -> None:
        assert schema in SUPPORTED_SCHEMAS

    @pytest.mark.parametrize("schema", ["benchmark.goal_pack", "benchmark.calibration_report"])
    def test_the_schema_is_frozen(self, schema: str) -> None:
        """These predated FreeWeight P8A-8B producing real packs; Phase 4's pass moved no field."""
        assert schema not in DRAFT_SCHEMAS


class TestGoalPack:
    """A pack must define a measurement someone could actually take."""

    def test_a_realistic_pack_validates(self) -> None:
        pack = GoalPackOut.model_validate(_goal_pack())
        assert pack.slug == "noir_tech_voice"
        assert len(pack.criteria) == 2

    def test_round_trips_through_canonical_json(self) -> None:
        pack = GoalPackOut.model_validate(_goal_pack())
        assert GoalPackOut.model_validate(json.loads(canonical_dumps(pack))) == pack

    def test_a_reader_preserves_a_field_it_does_not_know(self) -> None:
        """ADR-0009 rule 4: an older reader re-exporting must not destroy a newer writer's data."""
        pack = GoalPackIn.model_validate(_goal_pack(future_field="from a later minor"))
        assert pack.extras["future_field"] == "from a later minor"

    def test_a_writer_refuses_a_field_it_does_not_know(self) -> None:
        with pytest.raises(PydanticValidationError):
            GoalPackOut.model_validate(_goal_pack(future_field="typo or undeclared version"))

    def test_a_pack_with_no_criteria_is_refused(self) -> None:
        with pytest.raises(PydanticValidationError, match="no criteria"):
            GoalPackOut.model_validate(_goal_pack(criteria=[]))

    def test_a_pack_with_no_tasks_is_refused(self) -> None:
        with pytest.raises(PydanticValidationError, match="no tasks"):
            GoalPackOut.model_validate(_goal_pack(tasks=[]))

    def test_duplicate_criterion_keys_are_refused(self) -> None:
        with pytest.raises(PydanticValidationError, match="more than once"):
            GoalPackOut.model_validate(
                _goal_pack(criteria=[_rule_criterion(weight=0.5), _rule_criterion(weight=0.5)])
            )

    def test_weights_that_do_not_sum_to_one_are_refused(self) -> None:
        with pytest.raises(PydanticValidationError, match="summing to"):
            GoalPackOut.model_validate(
                _goal_pack(criteria=[_rule_criterion(weight=0.6), _judged_criterion(weight=0.9)])
            )

    def test_judged_criteria_without_a_jury_are_refused(self) -> None:
        with pytest.raises(PydanticValidationError, match="no judge_set"):
            GoalPackOut.model_validate(_goal_pack(judge_set=None))

    def test_a_rules_only_pack_needs_no_jury(self) -> None:
        """The most deterministic rubric a user can write must be the easiest to express."""
        pack = GoalPackOut.model_validate(
            _goal_pack(criteria=[_rule_criterion(weight=1.0)], judge_set=None)
        )
        assert pack.judge_set is None

    def test_a_slug_that_is_not_a_capability_segment_is_refused(self) -> None:
        """The slug becomes `user.<slug>`, so it must be a legal capability segment."""
        with pytest.raises(PydanticValidationError):
            GoalPackOut.model_validate(_goal_pack(slug="Noir Tech Voice"))


class TestGoalCriterionRungShape:
    """Each rung needs the fields it actually uses, and must not carry another rung's."""

    def test_a_rule_criterion_needs_a_rule_type(self) -> None:
        with pytest.raises(PydanticValidationError, match="no rule_type"):
            GoalCriterionFields.model_validate(_rule_criterion(rule_type=None))

    def test_a_rule_criterion_may_not_declare_a_scale(self) -> None:
        with pytest.raises(PydanticValidationError, match="scale_points"):
            GoalCriterionFields.model_validate(_rule_criterion(scale_points=5))

    def test_a_judged_criterion_needs_a_scale(self) -> None:
        with pytest.raises(PydanticValidationError, match="no scale_points"):
            GoalCriterionFields.model_validate(_judged_criterion(scale_points=None))

    def test_a_judged_criterion_may_not_declare_a_rule_type(self) -> None:
        """If a rule can check it, it belongs at rung 'rule' — the ladder position must be one."""
        with pytest.raises(PydanticValidationError, match="rule_type"):
            GoalCriterionFields.model_validate(_judged_criterion(rule_type="forbidden_phrases"))

    def test_a_judged_criterion_without_scale_descriptors_is_refused(self) -> None:
        """An unanchored ordinal scale reliably produces agreement near zero (ADR-0031 §3)."""
        with pytest.raises(PydanticValidationError, match="no descriptors"):
            GoalCriterionFields.model_validate(_judged_criterion(has_scale_descriptors=False))

    def test_a_human_criterion_needs_no_descriptors(self) -> None:
        """The author is the anchor; there is nothing to anchor a model against."""
        criterion = GoalCriterionFields.model_validate(
            _judged_criterion(rung="human", has_scale_descriptors=False)
        )
        assert criterion.rung is ScoringRung.HUMAN


class TestCalibrationReport:
    """A report's verdict must follow from the figures it carries."""

    def test_a_realistic_report_validates(self) -> None:
        report = CalibrationReportOut.model_validate(_calibration_report())
        assert report.passed_gate is True

    def test_round_trips_through_canonical_json(self) -> None:
        report = CalibrationReportOut.model_validate(_calibration_report())
        assert CalibrationReportOut.model_validate(json.loads(canonical_dumps(report))) == report

    def test_a_failed_gate_is_a_valid_report(self) -> None:
        """The case the user most needs to see, and the one evidence says nothing about."""
        report = CalibrationReportOut.model_validate(
            _calibration_report(
                weighted_kappa_w=0.25,
                passed_gate=False,
                judge_validity_factor=0.15,
                criteria=[
                    {
                        "criterion_key": "dry_wit",
                        "weight": 0.4,
                        "agreement": _agreement(kappa_w=0.25, rho=0.2, mae=1.4),
                        "inter_juror_alpha": 0.88,
                        "judge_validity_factor": 0.18,
                    }
                ],
            )
        )
        assert report.passed_gate is False
        assert report.weighted_kappa_w == 0.25

    def test_a_verdict_contradicting_its_own_numbers_is_refused(self) -> None:
        with pytest.raises(PydanticValidationError, match="passed_gate"):
            CalibrationReportOut.model_validate(
                _calibration_report(weighted_kappa_w=0.25, passed_gate=True)
            )

    def test_a_pass_claimed_below_the_threshold_is_refused_both_ways(self) -> None:
        with pytest.raises(PydanticValidationError, match="passed_gate"):
            CalibrationReportOut.model_validate(
                _calibration_report(weighted_kappa_w=0.9, passed_gate=False)
            )

    def test_judged_criteria_with_no_holdout_are_refused(self) -> None:
        """A coefficient with no holdout to stand on is the failure n_holdout exists to prevent."""
        with pytest.raises(PydanticValidationError, match="held-out"):
            CalibrationReportOut.model_validate(_calibration_report(n_holdout=0))

    def test_judged_criteria_with_no_jury_are_refused(self) -> None:
        with pytest.raises(PydanticValidationError, match="no judge_set"):
            CalibrationReportOut.model_validate(_calibration_report(judge_set=None))

    def test_per_criterion_agreement_without_a_weighted_figure_is_refused(self) -> None:
        with pytest.raises(PydanticValidationError, match="weighted_kappa_w"):
            CalibrationReportOut.model_validate(_calibration_report(weighted_kappa_w=None))

    def test_a_rules_only_goal_passes_with_nothing_to_calibrate(self) -> None:
        """Nothing needed calibrating, so nothing failed to calibrate."""
        report = CalibrationReportOut.model_validate(
            _calibration_report(
                criteria=[],
                weighted_kappa_w=None,
                judge_set=None,
                passed_gate=True,
                judge_validity_factor=1.0,
                n_anchor=0,
                n_holdout=0,
            )
        )
        assert report.judge_validity_factor == 1.0

    def test_a_rules_only_goal_cannot_report_a_failed_gate(self) -> None:
        """Marking it failed would penalize the most deterministic rubric a user can write."""
        with pytest.raises(PydanticValidationError, match="nothing to calibrate"):
            CalibrationReportOut.model_validate(
                _calibration_report(
                    criteria=[], weighted_kappa_w=None, judge_set=None, passed_gate=False
                )
            )

    def test_a_negative_kappa_is_representable(self) -> None:
        """A judge that disagrees with the author worse than chance is a real, reportable state."""
        report = CalibrationReportOut.model_validate(
            _calibration_report(
                weighted_kappa_w=-0.2,
                passed_gate=False,
                criteria=[
                    {
                        "criterion_key": "dry_wit",
                        "weight": 0.4,
                        "agreement": _agreement(kappa_w=-0.2, rho=-0.3),
                        "inter_juror_alpha": 0.7,
                        "judge_validity_factor": 0.0,
                    }
                ],
            )
        )
        assert report.weighted_kappa_w == -0.2


class TestGoalEvidenceGroup:
    """The goal-sourced group on capability.evidence, and the five rules that keep it honest."""

    def test_a_calibrated_goal_record_validates(self) -> None:
        evidence = CapabilityEvidenceOut.model_validate(_goal_evidence())
        assert evidence.capability_id == "user.noir_tech_voice"
        assert evidence.judge_validity_factor == 0.55

    def test_round_trips_through_canonical_json(self) -> None:
        evidence = CapabilityEvidenceOut.model_validate(_goal_evidence())
        assert (
            CapabilityEvidenceOut.model_validate(json.loads(canonical_dumps(evidence))) == evidence
        )

    def test_an_uncalibrated_record_is_refused(self) -> None:
        """The gate withholds the record entirely; a True here is a producer bug (ADR-0032 §3)."""
        with pytest.raises(PydanticValidationError, match="uncalibrated must be False"):
            CapabilityEvidenceOut.model_validate(_goal_evidence(uncalibrated=True))

    def test_a_user_capability_without_a_goal_hash_is_refused(self) -> None:
        """Two people's 'user.house_voice' are different measurements."""
        with pytest.raises(PydanticValidationError, match="no goal_hash"):
            CapabilityEvidenceOut.model_validate(_goal_evidence(goal_hash=None))

    def test_a_bare_user_capability_is_refused_by_the_vocabulary(self) -> None:
        with pytest.raises(PydanticValidationError, match="reserved namespace"):
            CapabilityEvidenceOut.model_validate(_goal_evidence(capability_id="user"))

    def test_a_validity_discount_with_no_goal_is_refused(self) -> None:
        """Only a goal's judged criteria can reduce validity (ADR-0032 §2)."""
        with pytest.raises(PydanticValidationError, match="no goal_hash"):
            CapabilityEvidenceOut.model_validate(
                _goal_evidence(
                    capability_id="coding.python",
                    goal_hash=None,
                    goal_pack_version=None,
                    score_method_mix=None,
                    judge_set=None,
                    calibration=None,
                )
            )

    def test_a_validity_discount_with_no_calibration_is_refused(self) -> None:
        with pytest.raises(PydanticValidationError, match="no calibration"):
            CapabilityEvidenceOut.model_validate(_goal_evidence(calibration=None))

    def test_calibration_without_a_jury_is_refused(self) -> None:
        with pytest.raises(PydanticValidationError, match="judge_set is not"):
            CapabilityEvidenceOut.model_validate(_goal_evidence(judge_set=None))

    def test_a_rules_only_goal_carries_full_validity_and_no_calibration(self) -> None:
        evidence = CapabilityEvidenceOut.model_validate(
            _goal_evidence(
                judge_validity_factor=1.0,
                score_method_mix={"rule": 1.0},
                judge_set=None,
                calibration=None,
            )
        )
        assert evidence.judge_validity_factor == 1.0
        assert evidence.calibration is None

    def test_a_blended_contributes_to_record_is_allowed(self) -> None:
        """The optional second emission keeps its goal_hash but not the user.* identity."""
        evidence = CapabilityEvidenceOut.model_validate(
            _goal_evidence(capability_id="creative_writing")
        )
        assert evidence.goal_hash is not None


class TestNonGoalEvidenceIsUnchanged:
    """ADR-0032 must provably have changed no existing number."""

    def test_a_record_omitting_the_whole_group_still_validates(self) -> None:
        document = _goal_evidence(capability_id="coding.python", vocabulary_version="1.0")
        for key in (
            "judge_validity_factor",
            "goal_hash",
            "goal_pack_version",
            "score_method_mix",
            "judge_set",
            "calibration",
            "uncalibrated",
        ):
            del document[key]
        evidence = CapabilityEvidenceOut.model_validate(document)
        assert evidence.judge_validity_factor == 1.0
        assert evidence.uncalibrated is False


class TestScoreMethodMix:
    """A mix that does not sum to one makes every share in it wrong, not merely the total."""

    def test_an_unknown_rung_is_refused(self) -> None:
        with pytest.raises(PydanticValidationError, match="unknown scoring rungs"):
            CapabilityEvidenceOut.model_validate(_goal_evidence(score_method_mix={"vibes": 1.0}))

    def test_a_mix_that_does_not_sum_to_one_is_refused(self) -> None:
        with pytest.raises(PydanticValidationError, match="sums to"):
            CapabilityEvidenceOut.model_validate(
                _goal_evidence(score_method_mix={"rule": 0.3, "judge": 0.3})
            )

    def test_a_negative_share_is_refused(self) -> None:
        with pytest.raises(PydanticValidationError, match="fractions"):
            CapabilityEvidenceOut.model_validate(
                _goal_evidence(score_method_mix={"rule": 1.4, "judge": -0.4})
            )

    def test_every_rung_may_appear(self) -> None:
        evidence = CapabilityEvidenceOut.model_validate(
            _goal_evidence(
                score_method_mix={
                    "rule": 0.4,
                    "reference": 0.2,
                    "human": 0.1,
                    "judge": 0.3,
                }
            )
        )
        assert evidence.score_method_mix is not None
        assert sum(evidence.score_method_mix.values()) == pytest.approx(1.0)
