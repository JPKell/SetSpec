"""Tests for :mod:`setspec.vocabulary` — the capability vocabulary's contents and its rules.

BaseAiCore's :class:`~baseaicore.CapabilityId` already tests capability-ID *syntax* exhaustively;
what belongs here is *membership* — which terms this vocabulary recognises, and the
root/specialization and forward-compatibility rules that decide what happens when it does not.
"""

from __future__ import annotations

import pytest
from baseaicore import CapabilityId, ValidationError

from setspec.vocabulary import (
    CAPABILITIES,
    CAPABILITY_VOCABULARY_VERSION,
    RESERVED_ROOTS,
    is_known_capability,
    validate_capability,
)

ORDINARY_ROOTS = sorted(CAPABILITIES - RESERVED_ROOTS)
"""Roots that are capabilities in their own right, which is every root but a reserved one."""


class TestKnownCapabilities:
    """Known roots are accepted; unknown roots are rejected in strict mode."""

    @pytest.mark.parametrize("capability_id", ORDINARY_ROOTS)
    def test_every_declared_root_validates(self, capability_id: str) -> None:
        assert validate_capability(capability_id) == CapabilityId(capability_id)

    @pytest.mark.parametrize("capability_id", ORDINARY_ROOTS)
    def test_every_declared_root_is_known(self, capability_id: str) -> None:
        assert is_known_capability(capability_id) is True

    def test_an_unknown_root_is_rejected_in_strict_mode(self) -> None:
        with pytest.raises(ValidationError, match="not a known capability"):
            validate_capability("underwater_basket_weaving")

    def test_an_unknown_root_is_not_known(self) -> None:
        assert is_known_capability("underwater_basket_weaving") is False

    def test_a_syntactically_invalid_id_is_not_known(self) -> None:
        """`is_known_capability` answers False for bad syntax rather than raising."""
        assert is_known_capability("Not Valid") is False

    def test_a_syntactically_invalid_id_still_raises_from_validate(self) -> None:
        with pytest.raises(ValidationError):
            validate_capability("Not Valid")


class TestSpecializationsValidateAgainstTheirRoot:
    """A specialization is valid the moment its root is known, without being pre-enumerated."""

    def test_an_unenumerated_specialization_of_a_known_root_is_accepted(self) -> None:
        assert "coding.rust" not in CAPABILITIES  # not individually listed
        assert "coding" in CAPABILITIES  # its root is
        validated = validate_capability("coding.rust")
        assert validated.root == "coding"
        assert validated.is_specialization

    def test_an_unenumerated_specialization_of_a_known_root_is_known(self) -> None:
        assert is_known_capability("coding.python") is True

    def test_a_specialization_of_an_unknown_root_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            validate_capability("underwater_basket_weaving.advanced")

    def test_a_specialization_inherits_from_its_root(self) -> None:
        """The relationship setspec relies on is CapabilityId's own, not reimplemented here."""
        specialization = validate_capability("coding.python")
        root = validate_capability("coding")
        assert specialization.inherits_from(root)
        assert not root.inherits_from(specialization)


class TestForwardCompatibility:
    """spec §13: unknown is a hard error when strict, a preserved acceptance when the payload's
    own vocabulary is a newer minor of the same major."""

    def test_a_newer_minor_accepts_an_id_this_build_does_not_know(self) -> None:
        newer_minor = f"{CAPABILITY_VOCABULARY_VERSION.split('.')[0]}.99"
        validated = validate_capability("a_future_capability", vocabulary_version=newer_minor)
        assert validated.value == "a_future_capability"

    def test_a_newer_minor_does_not_make_is_known_capability_lie(self) -> None:
        """Leniency lives in validate_capability's forward-compat parameter, not in membership."""
        assert is_known_capability("a_future_capability") is False

    def test_the_same_version_gets_no_leniency(self) -> None:
        with pytest.raises(ValidationError):
            validate_capability(
                "a_future_capability", vocabulary_version=CAPABILITY_VOCABULARY_VERSION
            )

    def test_an_older_version_gets_no_leniency(self) -> None:
        with pytest.raises(ValidationError):
            validate_capability("a_future_capability", vocabulary_version="0.1")

    def test_a_newer_major_gets_no_leniency(self) -> None:
        """A major bump may remove or redefine a term (spec §11.8); guessing 'added' would be
        wrong exactly as often as it would be right."""
        with pytest.raises(ValidationError):
            validate_capability("a_future_capability", vocabulary_version="99.0")

    def test_no_vocabulary_version_supplied_gets_no_leniency(self) -> None:
        with pytest.raises(ValidationError):
            validate_capability("a_future_capability")

    def test_an_unparsable_vocabulary_version_gets_no_leniency(self) -> None:
        """A malformed version string cannot prove forward compatibility, so it proves nothing."""
        with pytest.raises(ValidationError):
            validate_capability("a_future_capability", vocabulary_version="not-a-version")


class TestVocabularyVersion:
    """The version string itself follows the same MAJOR.MINOR shape as every schema version."""

    def test_the_version_is_a_canonical_major_minor_string(self) -> None:
        from setspec import SchemaVersion

        assert str(SchemaVersion.parse(CAPABILITY_VOCABULARY_VERSION)) == (
            CAPABILITY_VOCABULARY_VERSION
        )


class TestReservedRoots:
    """A reserved root is a namespace, not a capability: specializations only (ADR-0032 §1)."""

    @pytest.mark.parametrize("root", sorted(RESERVED_ROOTS))
    def test_a_reserved_root_is_in_the_vocabulary(self, root: str) -> None:
        """Membership is what makes its specializations validate under the ordinary root rule."""
        assert root in CAPABILITIES

    @pytest.mark.parametrize("root", sorted(RESERVED_ROOTS))
    def test_a_bare_reserved_root_is_refused(self, root: str) -> None:
        with pytest.raises(ValidationError, match="reserved namespace"):
            validate_capability(root)

    @pytest.mark.parametrize("root", sorted(RESERVED_ROOTS))
    def test_a_bare_reserved_root_is_not_known(self, root: str) -> None:
        assert is_known_capability(root) is False

    @pytest.mark.parametrize("root", sorted(RESERVED_ROOTS))
    def test_a_specialization_of_a_reserved_root_validates(self, root: str) -> None:
        validated = validate_capability(f"{root}.house_voice")
        assert validated.root == root
        assert validated.is_specialization

    @pytest.mark.parametrize("root", sorted(RESERVED_ROOTS))
    def test_a_specialization_of_a_reserved_root_is_known(self, root: str) -> None:
        assert is_known_capability(f"{root}.house_voice") is True

    def test_an_unenumerated_user_goal_validates_without_a_vocabulary_change(self) -> None:
        """The point of the namespace: no future rubric is a vocabulary bump (ADR-0032 §1)."""
        for slug in ("noir_tech_voice", "brand_voice", "brief_faithfulness", "anything_at_all"):
            assert is_known_capability(f"user.{slug}") is True

    def test_a_bare_reserved_root_is_refused_even_under_forward_compatibility(self) -> None:
        """No future minor can turn `user` into a capability: what it lacks is a specialization,
        not a vocabulary entry, so the forward-compat exception must not reach it."""
        newer_minor = f"{CAPABILITY_VOCABULARY_VERSION.split('.')[0]}.99"
        with pytest.raises(ValidationError, match="reserved namespace"):
            validate_capability("user", vocabulary_version=newer_minor)

    def test_the_refusal_names_the_reserved_roots(self) -> None:
        """A caller that hit this needs to know which roots behave this way."""
        with pytest.raises(ValidationError) as excinfo:
            validate_capability("user")
        assert excinfo.value.details["reserved_roots"] == sorted(RESERVED_ROOTS)


class TestVocabularyVersionIsOneOneOrLater:
    """`user` arrived at 1.1; a build claiming 1.0 cannot have it (ADR-0032 §1)."""

    def test_the_vocabulary_is_at_least_one_one(self) -> None:
        from setspec import SchemaVersion

        assert SchemaVersion.parse(CAPABILITY_VOCABULARY_VERSION) >= SchemaVersion(1, 1)

    def test_adding_a_root_was_a_minor_bump(self) -> None:
        """spec §11.8 rule 8: additions are minor. The major must not have moved."""
        from setspec import SchemaVersion

        assert SchemaVersion.parse(CAPABILITY_VOCABULARY_VERSION).major == 1


class TestABuildPredatingOneOne:
    """An older build must *ignore* `user.*`, never fail on it (ADR-0009 forward compatibility).

    This is the degradation the whole namespace decision rests on: a LoadCoach released before
    vocabulary 1.1 has to keep importing evidence bundles that now contain goal records. If it
    rejected them, adding one root would have broken every consumer in the suite — which is what
    "additions are minor" is supposed to guarantee it does not.

    The older build is simulated by patching the module's own constants, because the alternative
    is installing a previous release into the test environment to assert a rule about this one.
    """

    @pytest.fixture
    def build_at_one_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Patch this module to look like a build released before `user` existed."""
        import setspec.vocabulary as vocabulary_module

        monkeypatch.setattr(
            vocabulary_module, "CAPABILITIES", CAPABILITIES - {"user"}, raising=True
        )
        monkeypatch.setattr(vocabulary_module, "RESERVED_ROOTS", frozenset(), raising=True)
        monkeypatch.setattr(vocabulary_module, "CAPABILITY_VOCABULARY_VERSION", "1.0", raising=True)

    @pytest.mark.usefixtures("build_at_one_zero")
    def test_it_accepts_a_user_capability_from_a_newer_minor(self) -> None:
        validated = validate_capability("user.house_voice", vocabulary_version="1.1")
        assert validated.value == "user.house_voice"

    @pytest.mark.usefixtures("build_at_one_zero")
    def test_it_does_not_claim_to_know_the_term(self) -> None:
        """Leniency is acceptance, not knowledge — the distinction spec §13 draws."""
        assert is_known_capability("user.house_voice") is False

    @pytest.mark.usefixtures("build_at_one_zero")
    def test_it_still_refuses_a_user_capability_with_no_version_declared(self) -> None:
        """Forward compatibility is proven by the payload's declared version, never assumed."""
        with pytest.raises(ValidationError, match="not a known capability"):
            validate_capability("user.house_voice")
