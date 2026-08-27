"""Contract module — the suite's capability vocabulary: which terms exist, and their version.

Imports :mod:`baseaicore` for :class:`~baseaicore.CapabilityId`'s syntax rules; performs no I/O.

BaseAiCore owns only the *shape* of a capability ID (dotted, lowercase, `[a-z][a-z0-9_]*` segments)
so that adding a term never forces a BaseAiCore release. This module owns the *contents*: which
terms are real, what a specialization must specialize, and how strictly an unrecognized term is
treated ([spec §4](../../docs/packages/setspec/spec.md), traceability matrix "who owns the
capability vocabulary").

**Versioning** ([spec §11.8](../../docs/packages/setspec/spec.md)): additions are minor, a removal
or a redefinition is major. ``CAPABILITY_VOCABULARY_VERSION`` reuses the same ``MAJOR.MINOR`` shape
as every schema version in this package, via :class:`~setspec.envelope.SchemaVersion`, so "is this
payload's vocabulary newer than mine" is the same comparison as everywhere else, not a second
version format to reason about.
"""

from __future__ import annotations

from typing import Final

from baseaicore import CapabilityId
from baseaicore import ValidationError as SuiteValidationError

from setspec.envelope import SchemaVersion

__all__ = [
    "CAPABILITIES",
    "CAPABILITY_VOCABULARY_VERSION",
    "RESERVED_ROOTS",
    "is_known_capability",
    "validate_capability",
]

CAPABILITY_VOCABULARY_VERSION: Final[str] = "1.1"
"""The vocabulary's own version, independent of every schema and package version in this build."""

CAPABILITIES: Final[frozenset[str]] = frozenset(
    {
        "reasoning",
        "coding",
        "code_review",
        "auditing",
        "debugging",
        "instruction_following",
        "structured_output",
        "tool_use",
        "agentic",
        "summarization",
        "creative_writing",
        "judging",
        "critiquing",
        "long_context",
        "speed",
        "latency",
        "memory_efficiency",
        "token_efficiency",
        "energy_efficiency",
        "reliability",
        # 1.1 — reserved; valid only as a specialization. See RESERVED_ROOTS.
        "user",
    }
)
"""Every known **root** as of :data:`CAPABILITY_VOCABULARY_VERSION`, drawn from the capabilities
FreeWeight's benchmark catalog already maps results onto.

Roots only — never a specialization. A specialization is valid whenever its own root is a member
of this set: ``coding.python`` and ``coding.rust`` are both accepted the moment ``coding`` is
known, because :class:`~baseaicore.CapabilityId` already defines ``coding.rust`` as inheriting
from ``coding`` (its root), and asking a maintainer to pre-enumerate every language, framework or
task variant a root might be specialized into would make the vocabulary permanently incomplete by
construction. :func:`validate_capability` checks a candidate's *root* against this set, never the
full dotted string, so a root's specializations are open-ended while an unknown root is still
rejected outright.

This is a starting vocabulary, not a closed one — Phase 2's own risk note is "guessing the result
shape," and a root FreeWeight's real benchmarks need that is missing here is exactly the kind of
gap Phase 4's freeze against real output is meant to find and correct with a minor version bump.

``user`` was added at ``1.1`` and is a member of this set only so that the root rule above accepts
its specializations; it is refused in its bare form. See :data:`RESERVED_ROOTS`.
"""

RESERVED_ROOTS: Final[frozenset[str]] = frozenset({"user"})
"""Roots that are valid **only** as a specialization; the bare root is refused.

``user`` is the sole member. It carries FreeWeight's user-authored goal evidence as
``user.<slug>`` (ADR-0032 §1), and one root added once closes the question permanently: the
open-ended specialization rule already accepts ``user.noir_tech_voice`` and every other goal any
user will ever write, so no future rubric is a vocabulary change.

The bare form is refused because it would mean nothing. Every other root in
:data:`CAPABILITIES` names a real, measurable capability that a benchmark maps onto; ``user``
names only the fact that a user defined something. A payload claiming ``capability_id: "user"``
has lost the identity that is the entire point of the namespace, and accepting it would let that
loss pass silently into a routing decision.

Membership in this set is checked *in addition to* :data:`CAPABILITIES`, not instead of it, so a
reserved root's specializations follow exactly the same rule as ``coding.rust``.
"""


def is_known_capability(capability_id: str) -> bool:
    """Report whether ``capability_id`` is both syntactically valid and in the current vocabulary.

    Args:
        capability_id: The candidate term.

    Returns:
        ``True`` iff ``capability_id`` parses as a :class:`~baseaicore.CapabilityId` and its root
        is a member of :data:`CAPABILITIES` — so a specialization of a known root, even one never
        explicitly enumerated, reports ``True``. A bare :data:`RESERVED_ROOTS` member is
        ``False``: ``user`` is not itself a capability, only a namespace for them. A
        syntactically invalid string is ``False``, not an exception — this function answers a
        yes/no question; :func:`validate_capability` is the one that raises.
    """
    try:
        parsed = CapabilityId(capability_id)
    except SuiteValidationError:
        return False
    if parsed.root not in CAPABILITIES:
        return False
    return parsed.is_specialization or parsed.root not in RESERVED_ROOTS


def validate_capability(
    capability_id: str,
    *,
    vocabulary_version: str | None = None,
) -> CapabilityId:
    """Validate a capability ID's syntax and, by default, its membership in the vocabulary.

    Membership is enforced strictly unless ``vocabulary_version`` proves the payload comes from a
    *newer minor* of the same major than this build knows — the forward-compatibility rule in
    [spec §13](../../docs/packages/setspec/spec.md): "unknown capability ID: ``ValidationError``
    when strict; a preserved warning when the payload's vocabulary version is newer." SetSpec has
    no logging ([spec §17](../../docs/packages/setspec/spec.md)), so "preserved" is literal: the
    term is accepted and returned rather than rejected, and a caller who wants to know whether
    leniency was actually applied checks :func:`is_known_capability` itself.

    A newer *major* is not given this leniency: rule 2 says a major vocabulary change may remove
    or redefine a term, so an unrecognized ID under a newer major could just as easily be a
    genuine removal as an addition, and treating it as forward-compatible would let the wrong case
    through silently.

    Args:
        capability_id: The candidate term.
        vocabulary_version: The vocabulary version the payload declares it was written against,
            if known. Compared against :data:`CAPABILITY_VOCABULARY_VERSION` using the same
            ``MAJOR.MINOR`` rules every schema version uses.

    Returns:
        The parsed, syntactically valid :class:`~baseaicore.CapabilityId`.

    Raises:
        ValidationError: If ``capability_id`` is not syntactically valid at all; if it is a bare
            :data:`RESERVED_ROOTS` member such as ``"user"``, which is a namespace rather than a
            capability; or if its root is unrecognized and no forward-compatibility exception
            applies. A specialization of a known root — ``coding.rust`` when ``coding`` is known,
            ``user.house_voice`` when ``user`` is — is never rejected on that basis alone, even
            when the specialization itself was never explicitly enumerated.

            A bare reserved root is refused **regardless of** ``vocabulary_version``: forward
            compatibility exists so an older build accepts a term a newer one added, and no
            future minor can turn ``user`` into a capability, because what it lacks is a
            specialization rather than a vocabulary entry.
    """
    parsed = CapabilityId(capability_id)  # raises baseaicore.ValidationError on bad syntax
    if parsed.root in RESERVED_ROOTS and not parsed.is_specialization:
        raise SuiteValidationError(
            f"{capability_id!r} is a reserved namespace, not a capability. Use a specialization "
            f"such as {capability_id}.my_goal — a bare {capability_id!r} carries no identity, "
            "which is the whole reason the namespace exists.",
            details={
                "field": "capability_id",
                "value": capability_id,
                "reserved_roots": sorted(RESERVED_ROOTS),
            },
        )
    if parsed.root in CAPABILITIES:
        return parsed
    if _is_forward_compatible(vocabulary_version):
        return parsed
    raise SuiteValidationError(
        f"{capability_id!r} is not a known capability in vocabulary "
        f"{CAPABILITY_VOCABULARY_VERSION}. Known roots and specializations are listed in "
        "setspec.vocabulary.CAPABILITIES.",
        details={
            "field": "capability_id",
            "value": capability_id,
            "vocabulary_version": CAPABILITY_VOCABULARY_VERSION,
        },
    )


def _is_forward_compatible(vocabulary_version: str | None) -> bool:
    """Report whether ``vocabulary_version`` is a newer minor of this build's known major."""
    if vocabulary_version is None:
        return False
    try:
        declared = SchemaVersion.parse(vocabulary_version)
        known = SchemaVersion.parse(CAPABILITY_VOCABULARY_VERSION)
    except SuiteValidationError:
        return False
    return declared.major == known.major and declared > known
