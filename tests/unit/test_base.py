"""Tests for :mod:`setspec.base` — the generator's naming contract and config precedence.

The Out/In *behavioural* split is asserted where it is used, in ``test_metrics.py``. What is
asserted here is the machinery every future payload type will lean on: that the generated classes
are named predictably, and that a definition cannot accidentally opt out of the guarantees its
base exists to make.
"""

from __future__ import annotations

import pytest
from pydantic import ConfigDict
from pydantic import ValidationError as PydanticValidationError

from setspec import PayloadDefinition, PreservingPayload, StrictPayload, payload_models
from setspec.base import WireSequence


class ThingFields(PayloadDefinition):
    """A definition using the conventional ``Fields`` suffix."""

    n: int


class ThingDefinition(PayloadDefinition):
    """A definition using the alternative ``Definition`` suffix."""

    n: int


class Bare(PayloadDefinition):
    """A definition with no recognised suffix."""

    n: int


class TestGeneratedNames:
    """The stem is derived predictably, because these names appear in error messages."""

    def test_a_fields_suffix_is_stripped(self) -> None:
        out, in_ = payload_models(ThingFields)
        assert (out.__name__, in_.__name__) == ("ThingOut", "ThingIn")

    def test_a_definition_suffix_is_stripped(self) -> None:
        out, in_ = payload_models(ThingDefinition)
        assert (out.__name__, in_.__name__) == ("ThingOut", "ThingIn")

    def test_an_unsuffixed_name_is_used_as_is(self) -> None:
        out, in_ = payload_models(Bare)
        assert (out.__name__, in_.__name__) == ("BareOut", "BareIn")

    def test_an_explicit_name_wins(self) -> None:
        out, in_ = payload_models(ThingFields, name="Renamed")
        assert (out.__name__, in_.__name__) == ("RenamedOut", "RenamedIn")


class TestGeneratedConfig:
    """A definition may carry cosmetic config; it may not weaken the contract."""

    def test_the_pair_inherits_the_right_bases(self) -> None:
        out, in_ = payload_models(ThingFields)
        assert issubclass(out, StrictPayload)
        assert issubclass(in_, PreservingPayload)

    def test_a_definition_cannot_opt_out_of_strictness(self) -> None:
        """Otherwise a payload could quietly re-enable the coercion spec §13 forbids."""

        class LaxFields(PayloadDefinition):
            model_config = ConfigDict(strict=False, extra="allow", frozen=False)
            n: int

        out, _ = payload_models(LaxFields)
        assert out.model_config["strict"] is True
        assert out.model_config["extra"] == "forbid"
        assert out.model_config["frozen"] is True
        with pytest.raises(PydanticValidationError):
            out.model_validate({"n": "1"})

    def test_cosmetic_definition_config_survives(self) -> None:
        class TitledFields(PayloadDefinition):
            model_config = ConfigDict(title="A Nice Title")
            n: int

        out, _ = payload_models(TitledFields)
        assert out.model_config["title"] == "A Nice Title"

    def test_extras_is_empty_when_nothing_was_unknown(self) -> None:
        _, in_ = payload_models(ThingFields)
        assert in_.model_validate({"n": 1}).extras == {}

    def test_extras_is_a_read_only_view(self) -> None:
        """The payload is frozen; handing out a mutable interior would make that a lie."""
        _, in_ = payload_models(ThingFields)
        payload = in_.model_validate({"n": 1, "future": 2})
        with pytest.raises(TypeError):
            payload.extras["another"] = 3  # type: ignore[index]  # read-only, asserted at runtime


class TestWireSequence:
    """A JSON array validates into an immutable tuple, never a mutable list."""

    def test_a_json_array_becomes_a_tuple(self) -> None:
        class Sequenced(PayloadDefinition):
            nums: WireSequence[int] = ()

        payload = Sequenced.model_validate({"nums": [1, 2, 3]})
        assert payload.nums == (1, 2, 3)
        assert isinstance(payload.nums, tuple)

    def test_a_python_tuple_is_still_accepted(self) -> None:
        class Sequenced(PayloadDefinition):
            nums: WireSequence[int] = ()

        assert Sequenced(nums=(1, 2)).nums == (1, 2)

    def test_elements_are_still_validated_strictly(self) -> None:
        class Sequenced(PayloadDefinition):
            nums: WireSequence[int] = ()

        with pytest.raises(PydanticValidationError):
            Sequenced.model_validate({"nums": ["1"]})

    def test_a_non_sequence_is_rejected(self) -> None:
        class Sequenced(PayloadDefinition):
            nums: WireSequence[int] = ()

        with pytest.raises(PydanticValidationError):
            Sequenced.model_validate({"nums": 5})

    def test_default_is_an_empty_tuple(self) -> None:
        class Sequenced(PayloadDefinition):
            nums: WireSequence[int] = ()

        assert Sequenced().nums == ()


class TestNestedPayloadPreservation:
    """A definition embedded directly (not through payload_models) always preserves unknown keys.

    This is the design in the ``PayloadDefinition`` docstring: nesting a bare ``*Fields`` class,
    rather than its generated ``Out``/``In``, means the nested object never loses data regardless
    of which half of the *outer* pair is in use.
    """

    def test_a_bare_definition_preserves_unknown_keys_when_nested(self) -> None:
        class InnerFields(PayloadDefinition):
            a: int

        class OuterFields(PayloadDefinition):
            inner: InnerFields

        outer = OuterFields.model_validate({"inner": {"a": 1, "b": 2}})
        assert outer.inner.extras == {"b": 2}

    def test_a_bare_definition_still_validates_its_known_fields_strictly(self) -> None:
        class InnerFields(PayloadDefinition):
            a: int

        class OuterFields(PayloadDefinition):
            inner: InnerFields

        with pytest.raises(PydanticValidationError):
            OuterFields.model_validate({"inner": {"a": "not an int"}})
