"""Contract module — ``model.identity`` v1 and ``model.adapter_manifest`` v1.

Imports pydantic and :mod:`baseaicore`; performs no I/O. ``model.identity`` is the exchange form of
:class:`baseaicore.ModelIdentity` (the identity triple) and :class:`baseaicore.ModelDescriptor`
(the refreshable metadata a provider reports about those weights), combined into one payload
because ADR-0022 §1 always
carries them together as ``capability.evidence.model``.

**Status: `model.identity` frozen (`1.0`).**
[Phase 4](../../../docs/packages/setspec/development-plan.md) promoted this from draft after
FreeWeight produced real results against it, and
:data:`setspec.envelope.DRAFT_SCHEMAS` no longer names it. From here the ordinary rules apply
without exception: a new optional field is a **minor** bump, and removing, renaming, retyping or
tightening one is a **major** — never an edit to this module at `1.0`. The committed JSON Schema
in ``setspec/schemas/model.identity/1.0.json`` is what makes that enforceable rather than
aspirational: changing a field here without publishing a new version fails the snapshot contract
test (ADR-0009 rule 7).

Deliberately omitted from ``model.identity``: :attr:`baseaicore.ModelDescriptor.raw`, the
untouched provider response. It carries no contract — its own docstring says nothing above the
normalizer may read it for business logic — and freezing its presence on the wire would promise a
shape for a value this package cannot describe.

**``model.adapter_manifest`` `1.0` arrives at [Phase 6]
(../../../docs/packages/setspec/development-plan.md)**, the operator-reviewed record ADR-0061
rule 1 describes: a directory of these, not a service. It shares this module with
``model.identity`` because both are identity-exchange concerns, and it also carries
:class:`AdapterIdentityFields` — the nested shape ``capability.evidence`` v1.1 embeds as its
optional ``adapter`` field (ADR-0058) — since a wire form of :class:`baseaicore.AdapterIdentity`
is exactly what both payloads need, one flat and one nested.
"""

from __future__ import annotations

from typing import Any, Literal, Self

from baseaicore import (
    UNSUPPORTED,
    AdapterIdentity,
    DataClassification,
    IdentityConfidence,
    ModelCapabilityFlag,
    ModelIdentity,
    ProviderKind,
    normalize_digest,
)
from baseaicore import ValidationError as SuiteValidationError
from pydantic import Field, model_validator

from setspec import vocabulary
from setspec.base import PayloadDefinition, WireEnum, WireSequence, payload_models
from setspec.serialization import MeasurementField, TimestampField

__all__ = [
    "AdapterIdentityFields",
    "AdapterManifestBaseFields",
    "AdapterManifestFields",
    "AdapterManifestIn",
    "AdapterManifestOut",
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


class AdapterIdentityFields(PayloadDefinition):
    """Exchange form of :class:`baseaicore.AdapterIdentity` — the optional adapter axis.

    Carried on ``capability.evidence`` v1.1 as the optional ``adapter`` field, so a record measured
    on ``(base, adapter)`` names the adapter rather than leaving the axis implicit (ADR-0058).
    Absent entirely on a record measured on the bare base — the additive proof the v1.1 minor bump
    rests on.

    Attributes:
        name: The manifest's human label, matching ``^[a-z][a-z0-9_-]{1,63}$``.
        artifact_digest: ``"sha256:"`` + 64 lowercase hex characters over the **served** GGUF
            artifact — the identity itself. Required: unlike a model identity, an adapter with no
            usable digest has no identity to be.
        source_digest: Optional ``"sha256:"`` + 64 lowercase hex over the training checkpoint, for
            lineage only — never part of identity or of :attr:`canonical_suffix`.
        canonical_suffix: The ``+{name}@{digest_short}`` suffix this adapter contributes to a
            canonical subject string (ADR-0058 §3). Materialized rather than left for a reader to
            derive, exactly as :attr:`ModelIdentityFields.canonical_id` is — see
            :meth:`_check_identity_coherence`.
    """

    name: str = Field(min_length=1)
    artifact_digest: str
    source_digest: str | None = None
    canonical_suffix: str = Field(min_length=1)

    @model_validator(mode="after")
    def _check_identity_coherence(self) -> Self:
        """Recompute the adapter identity and require ``canonical_suffix`` to agree.

        Raises:
            ValueError: If ``name``, ``artifact_digest`` or ``source_digest`` fails
                :class:`baseaicore.AdapterIdentity`'s own validation, or if ``canonical_suffix``
                disagrees with what the identity recomputes.
        """
        try:
            identity = AdapterIdentity(
                name=self.name,
                artifact_digest=self.artifact_digest,
                source_digest=self.source_digest,
            )
        except SuiteValidationError as exc:
            raise ValueError(str(exc)) from exc
        if identity.canonical_suffix != self.canonical_suffix:
            raise ValueError(
                f"canonical_suffix {self.canonical_suffix!r} does not match the adapter "
                f"identity, which recomputes to {identity.canonical_suffix!r}. canonical_suffix "
                "is a pure function of name and artifact_digest (ADR-0058 §3) — it is carried on "
                "the wire for convenience, not as an independent fact."
            )
        return self


class AdapterManifestBaseFields(PayloadDefinition):
    """The base model an adapter targets — provider model name plus an optional artifact digest.

    Unlike :class:`ModelIdentityFields`, this carries no ``provider_kind``: the manifest states
    which base an adapter was trained against, not which provider serves it, and ADR-0058 §5's
    compatibility check runs at serve time against the digest actually loaded, not against this
    field. When the digest is absent the base is *named*, not *proven* — reduced confidence rides
    the existing :class:`baseaicore.IdentityConfidence` machinery rather than a parallel flag
    (ADR-0061 rule 1).

    Attributes:
        provider_model_name: The base model's name, exactly as the provider names it.
        artifact_digest: ``"sha256:"`` + 64 lowercase hex over the base's served artifact, or
            ``None`` when the manifest's author could not verify it — a PEFT
            ``adapter_config.json`` names its base by name only, which is not a proof.
        identity_confidence: ``digest`` iff :attr:`artifact_digest` is present, ``name_only``
            otherwise — checked, not merely documented; see
            :meth:`_check_confidence_matches_digest`.
    """

    provider_model_name: str = Field(min_length=1)
    artifact_digest: str | None = None
    identity_confidence: WireEnum[IdentityConfidence]

    @model_validator(mode="after")
    def _check_confidence_matches_digest(self) -> Self:
        """Require ``identity_confidence`` to agree with whether ``artifact_digest`` is present.

        Raises:
            ValueError: If ``artifact_digest`` is present but not already normalized, or if
                ``identity_confidence`` does not match presence/absence of the digest.
        """
        if self.artifact_digest is not None and (
            normalize_digest(self.artifact_digest) != self.artifact_digest
        ):
            raise ValueError(
                f"base.artifact_digest {self.artifact_digest!r} is not in normalized 'sha256:' + "
                "64 lowercase hex form. Call normalize_digest() first."
            )
        expected = (
            IdentityConfidence.DIGEST
            if self.artifact_digest is not None
            else IdentityConfidence.NAME_ONLY
        )
        if self.identity_confidence != expected:
            raise ValueError(
                f"base.identity_confidence {self.identity_confidence!r} does not match whether "
                f"artifact_digest is present: expected {expected.value!r}."
            )
        return self


class AdapterManifestFields(PayloadDefinition):
    """Field definitions for ``model.adapter_manifest``; use :data:`AdapterManifestOut` /
    :data:`AdapterManifestIn`.

    The operator-reviewed record describing one adapter (ADR-0061 rule 1): a directory of these,
    not a service. ``declared_capabilities`` and ``data_classification`` are both claims a person
    is reviewing, not facts a scanner can honestly assert — the scan drafts, a human keeps
    (ADR-0061 rule 4).

    Attributes:
        name: The adapter's human label; also the name half of its identity (ADR-0058) — checked
            together with :attr:`artifact_sha256` and :attr:`source_sha256` against
            :class:`baseaicore.AdapterIdentity` in :meth:`_check_adapter_identity`, reusing that
            type's own validation rather than a second name/digest validator.
        artifact_file: Path to the served GGUF artifact, relative to the adapter directory. A
            locator, not an identity — a rename does not change :attr:`artifact_sha256`.
        artifact_sha256: ``"sha256:"`` + 64 lowercase hex over the served artifact — the
            adapter's identity itself, required.
        source_sha256: Optional ``"sha256:"`` + 64 lowercase hex over the training checkpoint,
            for lineage only.
        base: The model this adapter was trained against, at whatever confidence the manifest's
            author could establish.
        declared_capabilities: Namespaced vocabulary terms this adapter's author claims it
            supports — validated against :func:`setspec.vocabulary.validate_capability`; a bare
            reserved root is refused exactly as everywhere else the vocabulary is checked.
        data_classification: How sensitive this adapter's training data was. **Required, with no
            default** — a manifest omitting it is invalid and the adapter stays unavailable until
            a person supplies the value (ADR-0065 rule 1). Never defaulted here: ADR-0046's
            fail-closed default governs a caller declaring its own data, not a manifest declaring
            an artifact's provenance, and a schema default in this one field would let a
            validator silently fill in the value that governs egress.
        format: Fixed at ``"gguf"`` — training happens outside the suite in v1, and the adapter
            directory is the hand-off point after conversion (ADR-0061 rule 6).
        created_at: When this manifest was written.
        notes: Free text for the human reviewer.
    """

    name: str = Field(min_length=1)
    artifact_file: str = Field(min_length=1)
    artifact_sha256: str
    source_sha256: str | None = None
    base: AdapterManifestBaseFields
    declared_capabilities: WireSequence[str] = ()
    data_classification: WireEnum[DataClassification]
    format: Literal["gguf"] = "gguf"
    created_at: TimestampField
    notes: str | None = None

    @model_validator(mode="after")
    def _check_adapter_identity(self) -> Self:
        """Validate ``name``/``artifact_sha256``/``source_sha256`` via
        ``baseaicore.AdapterIdentity``.

        Reuses the domain type's own name-pattern and digest-normalization rules rather than a
        second implementation of either (ADR-0061 rule 1's instruction to this row).

        Raises:
            ValueError: If ``name`` does not match the manifest name shape, or
                ``artifact_sha256``/``source_sha256`` is not already in normalized digest form.
        """
        try:
            AdapterIdentity(
                name=self.name,
                artifact_digest=self.artifact_sha256,
                source_digest=self.source_sha256,
            )
        except SuiteValidationError as exc:
            raise ValueError(str(exc)) from exc
        return self

    @model_validator(mode="after")
    def _check_declared_capabilities_are_known(self) -> Self:
        """Validate every declared capability against the current vocabulary, strictly.

        No forward-compatibility exception: unlike a wire payload the vocabulary evolves
        alongside, a manifest carries no ``vocabulary_version`` field to prove it was written
        against a newer minor, so an unrecognized term here is treated as a mistake rather than a
        future addition.

        Raises:
            ValueError: If any declared capability is syntactically invalid, unknown to the
                current vocabulary, or a bare reserved root.
        """
        for capability_id in self.declared_capabilities:
            try:
                vocabulary.validate_capability(capability_id)
            except SuiteValidationError as exc:
                raise ValueError(str(exc)) from exc
        return self


AdapterManifestOut, AdapterManifestIn = payload_models(AdapterManifestFields)
"""The ``model.adapter_manifest`` payload pair: ``Out`` for writers, ``In`` for readers."""
