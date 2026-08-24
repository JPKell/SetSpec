"""Contract module — the two payload base classes and the generator that pairs them.

Imports pydantic; performs no I/O and reads no clock.

ADR-0009 rule 4 requires every payload type to
exist as **two** classes generated from one definition, and the reason is a specific failure this
suite refuses to ship:

* A writer must emit only fields it knows, or it silently exports garbage it cannot explain.
* A reader must not *strip* fields it does not know, or an old tool re-exporting a new document
  quietly destroys data — the sort of loss nobody notices until the original is gone.

Those two rules contradict each other in one class, so there are two: :class:`StrictPayload`
refuses unknown keys, :class:`PreservingPayload` keeps them. The round-trip contract
(``load(dump(x)) == x``, spec §11.3) is asserted **per class** — never across the pair, because
the pair is not meant to agree about unknown keys. That is the whole design.

Both bases are strict about types. Pydantic's default coercion would read ``"5"`` as ``5`` and
``5.0`` as ``5``, which is exactly the silent coercion spec §13 forbids: on a wire contract a
string where a number belongs is a producer bug, and hiding it makes the bug arrive somewhere
further away. Widening ``int`` to ``float`` is still allowed, because JSON writes ``1.0`` as ``1``
and refusing that would reject valid documents.
"""

from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Annotated, Any, Final, cast

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "PayloadDefinition",
    "PreservingPayload",
    "StrictPayload",
    "WireEnum",
    "WireSequence",
    "payload_models",
]

_SHARED_CONFIG: Final[ConfigDict] = ConfigDict(
    # No silent coercion: a wire contract that repairs its input hides the producer's defect
    # (spec §13). `int` still widens to `float`, which JSON requires.
    strict=True,
    # Payloads are documents, not state. A loaded payload that some later code mutates is a
    # document that no longer matches the bytes it came from.
    frozen=True,
    # Field order in the model is not the wire order — canonical JSON sorts keys — but a stable
    # declaration order keeps generated JSON Schema diffs readable between releases.
    populate_by_name=True,
)


class PayloadDefinition(BaseModel):
    """Base for a payload's field declarations, and the common ancestor of both generated halves.

    A definition class is not itself a payload: it carries the fields and says nothing about
    unknown keys, which is the one thing the two generated halves must disagree about. Subclass it
    to declare fields, then hand it to :func:`payload_models`::

        class MetricValueFields(PayloadDefinition):
            unit: str
            value: MeasurementField

    Both halves inherit from it as well, which is what lets :func:`payload_models` return a pair
    typed as the definition itself. Without a common ancestor a type checker would see the
    generated classes as bare bases with no fields, and every consumer of a payload — in this
    repository and in the three applications — would need a cast to read one.

    **Nesting one payload inside another.** A field can be typed directly as another definition —
    ``model: ModelIdentityFields`` inside ``CapabilityEvidenceFields`` — rather than as that
    definition's generated ``Out`` or ``In``. This is deliberate, not an oversight: the outer
    payload's own Out/In split already governs whether *the document as a whole* may carry an
    unknown field, and ADR-0009 rule 4's guarantee that matters most is that a reader never
    *loses* data. A definition's own ``extra="allow"`` (below) makes every nested payload
    preserving by default in both directions — a writer embedding a stray field one level down is
    a narrower gap than a reader silently discarding one, and accepting that narrower gap avoids
    generating a full, independently-versioned Out/In pair for every sub-structure that is never
    transmitted on its own.
    """

    model_config = ConfigDict(**_SHARED_CONFIG, extra="allow")

    @property
    def extras(self) -> Mapping[str, Any]:
        """Return the keys this build did not recognise, as a read-only mapping.

        Returns:
            Every key present in the source document that is not a declared field, in the order
            the document listed them. Always empty on a :class:`StrictPayload`, which refuses
            unknown keys outright — it is defined on both halves so that code reading a payload
            need not know which half it was handed.

            The mapping is a read-only view: the payload is frozen, and handing out a mutable
            reference to its interior would make that promise false.
        """
        return MappingProxyType(self.__pydantic_extra__ or {})


class StrictPayload(PayloadDefinition):
    """Base for the **outbound** half of a payload pair: writers use this.

    Refuses unknown keys. A writer that hands this model a field the schema does not define has
    either misspelled a name or is emitting a version it has not declared, and both are defects
    worth failing on at the point of construction rather than discovering in an export months
    later (ADR-0009 rule 5).

    Invariants:
        * Immutable after construction (``frozen``), so a serialized document always matches the
          object it came from.
        * Strictly typed: no string-to-number or float-to-int coercion.
        * ``load(dump(x)) == x`` for every instance. There are no unknown keys to preserve, so the
          contract is simply that nothing is lost or reinterpreted.

    Not hashable in general: equality is by field value, and a field holding a mapping makes the
    instance unhashable exactly as a frozen dataclass containing a dict would be.
    """

    model_config = ConfigDict(**_SHARED_CONFIG, extra="forbid")


class PreservingPayload(PayloadDefinition):
    """Base for the **inbound** half of a payload pair: readers use this.

    Keeps unknown keys instead of dropping them, and re-emits them on dump. This is what makes a
    v1.0 reader safe to put in front of a v1.1 document: it validates the fields it knows, carries
    the ones it does not, and a re-export loses nothing
    (ADR-0009 rule 4).

    The relaxation is bounded and deliberate. ``extra="allow"`` weakens strictness on input, which
    is the documented cost of preservation across a version gap; every *known* field is still
    validated strictly, so an unknown key can add information but can never change the meaning of
    a field this build already understands.

    Invariants:
        * Immutable after construction (``frozen``).
        * Known fields strictly typed; unknown keys kept verbatim and reachable through
          :attr:`extras`.
        * ``load(dump(x)) == x`` for every instance, unknown keys included.
    """

    model_config = ConfigDict(**_SHARED_CONFIG, extra="allow")


type WireEnum[EnumT: StrEnum] = Annotated[EnumT, Field(strict=False)]
"""A :class:`~enum.StrEnum` field that accepts its own member values from the wire.

Needed because the bases validate strictly, and strict mode in Python mode wants an actual enum
*instance* — while a document that has just been parsed from JSON holds the plain string
``"mean"``. Since :func:`~setspec.envelope.load_envelope` hands back exactly such a mapping, a
plainly annotated enum field would reject every real document while passing every hand-built test,
which is the worst possible place for a validation rule to be wrong.

Relaxing strictness here costs nothing: membership is still exact, so an unknown name, an integer
index and a bool are all still refused. Use it for every enum field in every payload::

    aggregation: WireEnum[Aggregation]
"""


def _coerce_to_tuple(value: object) -> object:
    """Convert a list or tuple to a tuple; pass anything else through for pydantic to reject.

    JSON has one sequence type, and it deserializes to a Python ``list``. Strict mode validates
    the *input Python type* against the annotation, and a bare ``tuple[T, ...]`` under
    ``strict=True`` accepts only an actual ``tuple`` — never the ``list`` every real document
    supplies — so every ordered-collection field would reject every real document without this.
    """
    if isinstance(value, list | tuple):
        return tuple(value)
    return value


type WireSequence[T] = Annotated[tuple[T, ...], BeforeValidator(_coerce_to_tuple)]
"""An ordered collection field that accepts a JSON array and stores it as an immutable tuple.

Needed for the same reason as :data:`WireEnum`, one layer down: JSON arrays deserialize to
``list``, but a payload is a document (frozen, and meant to stay that way all the way down), so
the field itself is a ``tuple`` — a stored ``list`` would leave a mutable object reachable through
an otherwise-immutable model. Element types are still validated strictly and individually; only
the *container's own type* is relaxed, exactly as :data:`WireEnum` relaxes only the enum's own
strictness. Use it for every ordered-collection field in every payload::

    gpus: WireSequence[GpuProfileFields] = ()
    source_run_ids: WireSequence[str] = ()
"""


def payload_models[DefinitionT: PayloadDefinition](
    definition: type[DefinitionT],
    *,
    name: str | None = None,
) -> tuple[type[DefinitionT], type[DefinitionT]]:
    """Generate the ``Out``/``In`` class pair for one payload definition.

    One definition, two classes, so the field list cannot drift between what writers emit and what
    readers accept — the drift ADR-0009 rule 4 exists to prevent. Write the fields once::

        class MetricValueFields(BaseModel):
            unit: str
            value: MeasurementField

        MetricValueOut, MetricValueIn = payload_models(MetricValueFields)

    ``MetricValueOut`` refuses unknown keys; ``MetricValueIn`` preserves them. Neither inherits the
    other, and the definition itself is never used as a payload — it carries fields, not a policy
    about unknown keys.

    Args:
        definition: A pydantic model holding the field declarations. Its own ``model_config`` is
            honoured except where it would contradict the base's guarantees: ``extra``, ``strict``
            and ``frozen`` always come from the generated class, since those three *are* the
            contract being generated.
        name: Stem for the generated class names, which become ``<stem>Out`` and ``<stem>In``.
            Defaults to the definition's own name with a trailing ``Fields`` or ``Definition``
            removed, so ``MetricValueFields`` yields ``MetricValueOut`` and ``MetricValueIn``.

    Returns:
        The ``(Out, In)`` pair, in that order — the order they are used in: a producer writes
        ``Out``, a consumer reads ``In``. Both are typed as the definition, so a type checker sees
        the declared fields; the halves differ in the one way a type cannot express, which is what
        they do with a key the definition never declared.
    """
    stem = name if name is not None else _stem_of(definition.__name__)
    return (
        _generate(definition, StrictPayload, f"{stem}Out"),
        _generate(definition, PreservingPayload, f"{stem}In"),
    )


def _stem_of(class_name: str) -> str:
    """Strip a definition class's naming suffix to get the payload's real name."""
    for suffix in ("Fields", "Definition"):
        if class_name.endswith(suffix) and len(class_name) > len(suffix):
            return class_name[: -len(suffix)]
    return class_name


def _generate[DefinitionT: PayloadDefinition](
    definition: type[DefinitionT],
    base: type[PayloadDefinition],
    class_name: str,
) -> type[DefinitionT]:
    """Build one generated class from a definition and a base, with the base's config winning."""
    # The definition's config is kept for anything cosmetic (title, json_schema_extra) but the
    # base's `extra`/`strict`/`frozen` are re-applied on top: those three are the guarantee the
    # base exists to make, and a definition must not be able to opt out of them by accident.
    # `ConfigDict` is a TypedDict, so a runtime merge of two of them is a plain dict as far as
    # the type checker is concerned; the cast restates what the merge preserves.
    merged = cast("ConfigDict", {**dict(definition.model_config), **dict(base.model_config)})
    generated = type(class_name, (definition, base), {"model_config": merged})
    return cast("type[DefinitionT]", generated)
