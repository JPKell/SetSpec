"""Contract module — ``governance.egress_decision`` v1.

Imports pydantic and :mod:`baseaicore`; performs no I/O. This is SetSpec's fifth owned root
(alongside ``benchmark``, ``capability``, ``machine`` and ``model``), added at
[Phase 6](../../../docs/packages/setspec/development-plan.md) because the payload has a named
**second reader**: IdeaPress's S4 egress badge reads decisions PromptCadence exported, with
Commissioner not installed — the two-consumer test
([ADR-0011](../../../docs/adr/0011-shared-package-boundaries.md)) applied to a schema rather than a
package (ADR-0051 §4).

The field set mirrors Commissioner spec §7's ``EgressRequest``/``EgressTarget``/``EgressDecision``
value objects **field for field**, ``EgressRequest.requested_at`` included. That field earns its
place on the wire not because a consumer needs it but because Commissioner spec §11 contract 4
promises ``from_payload(to_payload(d))`` preserves every field: a value-object field with no wire
field makes that promise unkeepable, and the round trip would silently drop a value rather than
refuse it. The two timestamps answer different questions and a consumer that needs only one uses
``decided_at`` — ``requested_at`` is when the caller *built* the request, ``decided_at`` is when
the policy *answered* it, and the gap between them is the evaluation's own latency.

Commissioner does not exist as code yet (it is specified, not implemented — see the workspace
`CLAUDE.md`), so nothing here imports it and nothing here is exercised by it; this module publishes
only the shape Commissioner's own ``EgressDecision.to_payload()``/``from_payload()`` will target.
"""

from __future__ import annotations

from enum import StrEnum

from baseaicore import DataClassification
from pydantic import Field

from setspec.base import PayloadDefinition, WireEnum, payload_models
from setspec.serialization import TimestampField

__all__ = [
    "EgressRequestFields",
    "EgressTargetFields",
    "EgressVerdict",
    "GovernanceEgressDecisionFields",
    "GovernanceEgressDecisionIn",
    "GovernanceEgressDecisionOut",
]


class EgressVerdict(StrEnum):
    """The three outcomes a recorded egress decision may hold (Commissioner spec §7).

    ``VIOLATION`` is writable but never produced by the shipped policy — it is written by a
    caller's verification step after the fact, when it finds egress that policy never approved
    (ADR-0054 rule 7). A schema that could not express it would be wrong: the payload's job is to
    carry whatever was decided, not to second-guess which verdicts are plausible.
    """

    APPROVED = "approved"
    DENIED = "denied"
    VIOLATION = "violation"


class EgressTargetFields(PayloadDefinition):
    """Where a decision's data was headed.

    Attributes:
        name: The target's own name — a tier name for PromptCadence, a backend name for
            IdeaPress. Caller-defined; SetSpec imposes no vocabulary on it.
        remote: Whether this target leaves the local machine.
        max_data_classification: The declared ceiling, or ``None`` when the target declares
            none. **Nullable, deliberately**: "remote with no declared ceiling" is the fail-closed
            case ``OrderedClassificationPolicy`` must be able to deny and record, not a value this
            schema can require away (ADR-0054 rule 3).
        provider_kind: The provider kind serving this target, when known.
    """

    name: str = Field(min_length=1)
    remote: bool
    max_data_classification: WireEnum[DataClassification] | None = None
    provider_kind: str | None = None


class EgressRequestFields(PayloadDefinition):
    """What was evaluated: which run, which data, headed where.

    Attributes:
        run_id: The trajectory or stage-attempt identity this request was evaluated for.
        source_ref: A finer locator within the run — a turn id, step id or stage id.
        data_classification: How sensitive the data under evaluation is. Required and
            non-nullable: an evaluated request always declares a classification, unlike a
            target's ceiling, which may legitimately be absent.
        target: Where the data was headed.
        requested_at: When the caller built this request, or ``None`` when it did not say.
            **Nullable, deliberately**: Commissioner spec §7 gives ``EgressRequest.requested_at`` a
            default of ``None`` before its clock fills it in, so a required field here would make
            a legitimately-constructed request unrepresentable and break the round-trip contract
            this field exists to keep (§11 contract 4). It is not the record's timestamp —
            :attr:`GovernanceEgressDecisionFields.decided_at` is, and it is required.
    """

    run_id: str = Field(min_length=1)
    source_ref: str = Field(min_length=1)
    data_classification: WireEnum[DataClassification]
    target: EgressTargetFields
    requested_at: TimestampField | None = None


class GovernanceEgressDecisionFields(PayloadDefinition):
    """Field definitions for ``governance.egress_decision``; use
    :data:`GovernanceEgressDecisionOut` / :data:`GovernanceEgressDecisionIn`.

    One recorded verdict on "may this classification go to this target" (ADR-0054). A denial is as
    durable as an approval — nothing about this shape distinguishes how a record was produced, and
    a consumer reading it never needs to.

    Attributes:
        decision_id: This decision's own identity.
        request: What was evaluated.
        verdict: What was decided.
        reason: A machine-readable reason — one of ``"within_ceiling"``,
            ``"classification_exceeds_ceiling"``, ``"target_not_remote"``,
            ``"no_ceiling_declared"``, or a caller-supplied string for a ``VIOLATION`` record.
            Never validated against a closed set here: the shipped policy's four reasons are not
            the only ones a caller's own verification step may need to write.
        policy_name: Which policy produced this decision.
        policy_version: That policy's version — part of what makes the decision reproducible
            (ADR-0054 rule 3: same request and same policy version, same decision).
        decided_at: When this decision was made.
    """

    decision_id: str = Field(min_length=1)
    request: EgressRequestFields
    verdict: WireEnum[EgressVerdict]
    reason: str = Field(min_length=1)
    policy_name: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    decided_at: TimestampField


GovernanceEgressDecisionOut, GovernanceEgressDecisionIn = payload_models(
    GovernanceEgressDecisionFields
)
"""The ``governance.egress_decision`` payload pair: ``Out`` for writers, ``In`` for readers."""
