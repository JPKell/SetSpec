"""Contract module — ``model.identity`` v1: which weights, plus what a provider says about them.

Imports pydantic and :mod:`baseaicore`; performs no I/O. Exchange form of
:class:`baseaicore.ModelIdentity` (the identity triple) and :class:`baseaicore.ModelDescriptor`
(the refreshable metadata a provider reports about those weights), combined into one payload
because ADR-0022 §1 always
carries them together as ``capability.evidence.model``.

**Status: frozen (`1.0`).**
[Phase 4](../../../docs/packages/setspec/development-plan.md) promoted this from draft after
FreeWeight produced real results against it, and
:data:`setspec.envelope.DRAFT_SCHEMAS` no longer names it. From here the ordinary rules apply
without exception: a new optional field is a **minor** bump, and removing, renaming, retyping or
tightening one is a **major** — never an edit to this module at `1.0`. The committed JSON Schema
in ``setspec/schemas/model.identity/1.0.json`` is what makes that enforceable rather than
aspirational: changing a field here without publishing a new version fails the snapshot contract
test (ADR-0009 rule 7).

Deliberately omitted: :attr:`baseaicore.ModelDescriptor.raw`, the untouched provider response.
It carries no contract — its own docstring says nothing above the normalizer may read it for
business logic — and freezing its presence on the wire would promise a shape for a value this
package cannot describe.
"""

from __future__ import annotations

from typing import Any, Self

from baseaicore import (
    UNSUPPORTED,
    IdentityConfidence,
    ModelCapabilityFlag,
    ModelIdentity,
    ProviderKind,
)
from baseaicore import ValidationError as SuiteValidationError
from pydantic import Field, model_validator

from setspec.base import PayloadDefinition, WireEnum, WireSequence, payload_models
from setspec.serialization import MeasurementField, TimestampField

__all__ = [
    "ModelIdentityFields",
    "ModelIdentityIn",
    "ModelIdentityOut",
]


class ModelIdentityFields(PayloadDefinition):
    """Field definitions for ``model.identity``; use :data:`ModelIdentityOut` /
    :data:`ModelIdentityIn`.

    :attr:`canonical_id` and :attr:`identity_confidence` are materialized rather than left for a
    reader to derive, so a consumer can display or index by them without reconstructing a
    :class:`baseaicore.ModelIdentity`. Both are still validated against the identity triple on
    every construction — see :meth:`_check_identity_coherence` — so "provenance completeness
    enforced by the schema" (Phase 2 gold standard) applies to the derived fields too, not only
    the fields nothing computes.

    Attributes:
        provider_kind: Which kind of provider serves these weights ([ADR-0008]
            (0008 canonical model identity)). Reuses
            :class:`baseaicore.ProviderKind` directly rather than a shadow enum, so a new provider
            kind reaches this schema the moment BaseAiCore adds it.
        provider_model_name: Exactly as the provider names it, case and punctuation preserved.
        artifact_digest: ``"sha256:"`` + 64 lowercase hex characters, or ``None`` when the
            provider exposes none.
        identity_confidence: ``digest`` iff ``artifact_digest`` is present, ``name_only``
            otherwise — checked, not merely documented.
        canonical_id: ``{provider_kind}/{provider_model_name}@{digest_short}``
            (ADR-0024). Lossy and
            display-only; never parsed back into its parts.
        observed_at: When this descriptor snapshot was read from the provider.
        family: The model family name, e.g. ``"qwen3.5"``.
        architecture: The architecture name, e.g. ``"transformer"``, ``"mamba"``.
        parameter_count: Total parameter count.
        active_parameter_count: MoE active parameters per token; equal to
            ``parameter_count`` for a dense model.
        expert_count: Number of experts, for a mixture-of-experts model.
        quantization: Weight quantization, e.g. ``"Q8_0"``.
        weight_format: File format, e.g. ``"gguf"``, ``"safetensors"``.
        size_bytes: On-disk size of the weights.
        max_context: The context length the model *advertises* — not the context a provider is
            configured to serve, which is ``execution.served_context`` on a benchmark result
            (ADR-0023 §4).
        embedding_dim: Hidden/embedding dimension.
        layers: Transformer layer count.
        attention_heads: Attention head count.
        kv_heads: Key/value head count.
        head_dim: Dimension of each attention head.
        vocab_size: Tokenizer vocabulary size.
        rope_config: RoPE scaling configuration, in the provider's own shape.
        sliding_window: Sliding-attention window size, if the architecture uses one.
        declared_capabilities: What the provider *claims* this model can do — never conflated
            with a measured capability from ``capability.evidence``.
        license_text: The model's license, if the provider exposes one.
    """

    provider_kind: WireEnum[ProviderKind]
    provider_model_name: str = Field(min_length=1)
    artifact_digest: str | None = None
    identity_confidence: WireEnum[IdentityConfidence]
    canonical_id: str = Field(min_length=1)

    observed_at: TimestampField
    family: str | None = None
    architecture: str | None = None
    parameter_count: MeasurementField = UNSUPPORTED
    active_parameter_count: MeasurementField = UNSUPPORTED
    expert_count: MeasurementField = UNSUPPORTED
    quantization: str | None = None
    weight_format: str | None = None
    size_bytes: MeasurementField = UNSUPPORTED
    max_context: MeasurementField = UNSUPPORTED
    embedding_dim: MeasurementField = UNSUPPORTED
    layers: MeasurementField = UNSUPPORTED
    attention_heads: MeasurementField = UNSUPPORTED
    kv_heads: MeasurementField = UNSUPPORTED
    head_dim: MeasurementField = UNSUPPORTED
    vocab_size: MeasurementField = UNSUPPORTED
    rope_config: dict[str, Any] | None = None
    sliding_window: MeasurementField = UNSUPPORTED
    declared_capabilities: WireSequence[WireEnum[ModelCapabilityFlag]] = ()
    license_text: str | None = None

    @model_validator(mode="after")
    def _check_identity_coherence(self) -> Self:
        """Recompute the identity triple's derived fields and require them to agree.

        Unlike a machine fingerprint — whose inclusion policy is allowed to change under a
        profile that must still reconstruct exactly as it was written — a canonical ID and an
        identity confidence are pure functions of the triple with no such historical caveat
        (:class:`baseaicore.ModelIdentity` never re-verifies a stored fingerprint for that reason,
        but always recomputes ``canonical_id``). Recomputing here is therefore safe, not merely
        convenient, and it catches a producer that materialized the derived fields inconsistently
        with the triple that stands next to them.

        Raises:
            ValueError: If ``provider_model_name`` or ``artifact_digest`` fails
                :class:`baseaicore.ModelIdentity`'s own validation, or if ``canonical_id`` or
                ``identity_confidence`` disagrees with what the triple recomputes.
        """
        try:
            identity = ModelIdentity(
                provider_kind=self.provider_kind,
                provider_model_name=self.provider_model_name,
                artifact_digest=self.artifact_digest,
            )
        except SuiteValidationError as exc:
            # baseaicore.ValidationError is a SuiteError, not a ValueError; pydantic only
            # aggregates ValueError/AssertionError into its own report (setspec.serialization
            # hits the same seam for timestamps).
            raise ValueError(str(exc)) from exc
        if identity.canonical_id != self.canonical_id:
            raise ValueError(
                f"canonical_id {self.canonical_id!r} does not match the identity triple, which "
                f"recomputes to {identity.canonical_id!r}. canonical_id is a pure function of "
                "provider_kind, provider_model_name and artifact_digest (ADR-0024) — it is "
                "carried on the wire for convenience, not as an independent fact."
            )
        if identity.identity_confidence.value != self.identity_confidence:
            raise ValueError(
                f"identity_confidence {self.identity_confidence!r} does not match the identity "
                f"triple: artifact_digest is "
                f"{'present' if self.artifact_digest is not None else 'absent'}, which makes "
                f"this identity {identity.identity_confidence.value!r}."
            )
        return self


ModelIdentityOut, ModelIdentityIn = payload_models(ModelIdentityFields)
"""The ``model.identity`` payload pair: ``Out`` for writers, ``In`` for readers."""
