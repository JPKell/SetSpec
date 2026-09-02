"""Tests for ``governance.egress_decision`` (:mod:`setspec.governance.v1`).

SetSpec's fifth owned root, added at Phase 6 because the payload has a named second reader
(ADR-0051 §4): a `setspec`-only script must be able to read a decision PromptCadence exported, with
SpotCheck not installed. Nothing here imports SpotCheck — it does not exist as code yet — so every
fixture is built from SpotCheck spec §7's field list directly.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError as PydanticValidationError

from setspec import canonical_dumps
from setspec.governance.v1 import (
    EgressRequestFields,
    EgressTargetFields,
    EgressVerdict,
    GovernanceEgressDecisionIn,
    GovernanceEgressDecisionOut,
)

_DECIDED_AT = datetime(2026, 9, 2, 9, 0, 0, tzinfo=UTC)


def _target(**overrides: Any) -> dict[str, Any]:
    return {
        "name": "ollama-local",
        "remote": False,
        "max_data_classification": None,
        "provider_kind": None,
    } | overrides


def _request(**overrides: Any) -> dict[str, Any]:
    return {
        "run_id": "run_01",
        "source_ref": "turn_1",
        "data_classification": "public",
        "target": _target(),
        "requested_at": None,
    } | overrides


def _decision(**overrides: Any) -> dict[str, Any]:
    """A minimal, valid governance.egress_decision document."""
    return {
        "decision_id": "dec_01",
        "request": _request(),
        "verdict": "approved",
        "reason": "target_not_remote",
        "policy_name": "OrderedClassificationPolicy",
        "policy_version": "1.0",
        "decided_at": _DECIDED_AT.isoformat(),
    } | overrides


class TestEgressTarget:
    """`max_data_classification` is nullable; every other field is not."""

    def test_a_local_target_needs_no_ceiling(self) -> None:
        target = EgressTargetFields.model_validate(_target())
        assert target.max_data_classification is None

    def test_a_remote_target_may_declare_a_ceiling(self) -> None:
        target = EgressTargetFields.model_validate(
            _target(remote=True, max_data_classification="internal", provider_kind="ollama")
        )
        assert target.max_data_classification is not None
        assert target.max_data_classification.value == "internal"

    def test_a_remote_target_with_no_declared_ceiling_is_still_valid(self) -> None:
        """The fail-closed case is representable, not refused by the schema (ADR-0054 rule 3)."""
        target = EgressTargetFields.model_validate(_target(remote=True))
        assert target.max_data_classification is None

    def test_an_empty_name_is_rejected(self) -> None:
        with pytest.raises(PydanticValidationError):
            EgressTargetFields.model_validate(_target(name=""))


class TestEgressRequest:
    def test_data_classification_is_required_and_not_nullable(self) -> None:
        document = _request()
        del document["data_classification"]
        with pytest.raises(PydanticValidationError, match="data_classification"):
            EgressRequestFields.model_validate(document)

    def test_requested_at_may_be_omitted_entirely(self) -> None:
        """SpotCheck spec §7 defaults it to None, so a document without it is a valid one."""
        document = _request()
        del document["requested_at"]
        assert EgressRequestFields.model_validate(document).requested_at is None

    def test_requested_at_may_be_null(self) -> None:
        assert EgressRequestFields.model_validate(_request()).requested_at is None

    def test_requested_at_survives_the_round_trip_that_justifies_it(self) -> None:
        """SpotCheck spec §11 contract 4: `from_payload(to_payload(d))` preserves every field.

        The reason this field is on the wire at all, asserted rather than assumed: a value that
        went in must come back out, not be quietly dropped by a shape that has no room for it.
        """
        request = EgressRequestFields.model_validate(
            _request(requested_at="2026-09-02T09:05:11.880Z")
        )
        reparsed = EgressRequestFields.model_validate(json.loads(canonical_dumps(request)))
        assert reparsed.requested_at == request.requested_at
        assert reparsed == request

    def test_requested_at_normalizes_to_utc_like_every_other_timestamp(self) -> None:
        request = EgressRequestFields.model_validate(
            _request(requested_at="2026-09-02T11:05:11.880+02:00")
        )
        assert request.requested_at == datetime(2026, 9, 2, 9, 5, 11, 880_000, tzinfo=UTC)

    def test_a_naive_requested_at_is_refused(self) -> None:
        """Naive means "which clock?" — refused here as everywhere else (serialization §4)."""
        with pytest.raises(PydanticValidationError, match="requested_at"):
            EgressRequestFields.model_validate(_request(requested_at="2026-09-02T09:05:11.880"))

    def test_requested_at_is_not_the_records_timestamp(self) -> None:
        """`decided_at` stays required; the two are different questions, not one duplicated."""
        document = _decision()
        del document["decided_at"]
        with pytest.raises(PydanticValidationError, match="decided_at"):
            GovernanceEgressDecisionOut.model_validate(document)


class TestGovernanceEgressDecision:
    """The three verdicts named in `EgressVerdict`, and the shape's round-trip contract."""

    def test_a_minimal_decision_round_trips(self) -> None:
        decision = GovernanceEgressDecisionOut.model_validate(_decision())
        assert (
            GovernanceEgressDecisionOut.model_validate(json.loads(canonical_dumps(decision)))
            == decision
        )

    @pytest.mark.parametrize("verdict", ["approved", "denied", "violation"])
    def test_every_verdict_validates(self, verdict: str) -> None:
        decision = GovernanceEgressDecisionOut.model_validate(_decision(verdict=verdict))
        assert decision.verdict == EgressVerdict(verdict)

    def test_an_unknown_verdict_is_rejected(self) -> None:
        with pytest.raises(PydanticValidationError):
            GovernanceEgressDecisionOut.model_validate(_decision(verdict="maybe"))

    def test_a_denied_decision_with_no_ceiling_round_trips(self) -> None:
        """ADR-0054 rule 4: a denial is as durable as an approval — the same shape holds both."""
        decision = GovernanceEgressDecisionOut.model_validate(
            _decision(
                request=_request(
                    data_classification="internal",
                    target=_target(name="tools.agent.remote_frontier", remote=True),
                ),
                verdict="denied",
                reason="no_ceiling_declared",
            )
        )
        assert decision.verdict == EgressVerdict.DENIED
        assert decision.request.target.max_data_classification is None

    def test_a_violation_carries_a_caller_supplied_reason(self) -> None:
        """ADR-0054 rule 7: VIOLATION is writable, with whatever reason the verification step
        supplies — never validated against the shipped policy's own four reasons."""
        decision = GovernanceEgressDecisionOut.model_validate(
            _decision(
                verdict="violation",
                reason="local_tier_turn_answered_by_remote_provider",
                policy_name="PostHocVerification",
            )
        )
        assert decision.verdict == EgressVerdict.VIOLATION

    def test_an_empty_decision_id_is_rejected(self) -> None:
        with pytest.raises(PydanticValidationError):
            GovernanceEgressDecisionOut.model_validate(_decision(decision_id=""))

    def test_in_preserves_an_unknown_field(self) -> None:
        decision = GovernanceEgressDecisionIn.model_validate(_decision(future_field="x"))
        assert decision.extras == {"future_field": "x"}

    def test_out_refuses_an_unknown_field(self) -> None:
        with pytest.raises(PydanticValidationError):
            GovernanceEgressDecisionOut.model_validate(_decision(future_field="x"))

    def test_in_preserves_an_unknown_field_on_the_nested_target(self) -> None:
        """A definition nested without payload_models() preserves regardless of direction."""
        decision = GovernanceEgressDecisionIn.model_validate(
            _decision(request=_request(target=_target(egress_class="cheap")))
        )
        assert decision.request.target.extras == {"egress_class": "cheap"}
