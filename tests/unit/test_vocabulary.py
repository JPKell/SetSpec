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
    is_known_capability,
    validate_capability,
)


class TestKnownCapabilities:
    """Known roots are accepted; unknown roots are rejected in strict mode."""

    @pytest.mark.parametrize("capability_id", sorted(CAPABILITIES))
    def test_every_declared_root_validates(self, capability_id: str) -> None:
        assert validate_capability(capability_id) == CapabilityId(capability_id)

    @pytest.mark.parametrize("capability_id", sorted(CAPABILITIES))
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
