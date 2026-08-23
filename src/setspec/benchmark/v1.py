"""Contract module — ``benchmark.result`` and ``benchmark.run_summary`` v1.

Imports pydantic and :mod:`baseaicore`; performs no I/O. ``BenchmarkResult`` is one benchmark, one
measurement subject, metrics plus provenance plus a samples reference;
``BenchmarkRunSummary`` is one run: subject, suite, status, timings, aggregate metrics
([spec §7](../../../docs/packages/setspec/spec.md)).

**Status: draft (`1.0`).** See :mod:`setspec.model.v1` for what that means. The known risk named
by [development plan Phase 2](../../../docs/packages/setspec/development-plan.md) is guessing the
result shape before FreeWeight exists to produce one; this module is built from the one place that
shape is already normative before any FreeWeight code exists —
[Machine Identity §6](../../../docs/architecture/machine-identity-and-reproducibility.md), "what
every measured result must carry" — plus
[ADR-0022](../../../docs/adr/0022-capability-evidence-record-contract.md) and
[ADR-0023](../../../docs/adr/0023-runtime-profile-resolution.md) for the fields those provenance
bullets expand into. A field with no normative source here is a field this module does
not invent; Phase 4 corrects any gap against FreeWeight's real output.

**Hash-shaped fields are checked, never guessed, and never both.** Two kinds of string on this
result claim to be a hash of something: ``runtime_profile_hash`` is recomputed from the embedded
``runtime_profile`` and compared, the same reasoning :mod:`setspec.model.v1` applies to
``canonical_id`` — it is a pure function with no real-world format ambiguity. Every other
hash-shaped field (``manifest_hash``, ``prompt_subset_hash``, ``reproducibility_fingerprint``, each
entry of ``dataset_hashes``) is validated only as a non-empty string: this package cannot yet
compute FreeWeight's own manifest or fingerprint hashes, and guessing a format — hex-only, with or
without an algorithm prefix — risks rejecting the first real result over a formatting nuance
instead of the risk the tests actually target.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Self

from baseaicore import ProviderKind, RuntimeProfile
from pydantic import Field, model_validator

from setspec.base import PayloadDefinition, WireEnum, WireSequence, payload_models
from setspec.machine.v1 import MachineProfileFields
from setspec.metrics import MetricValueFields
from setspec.model.v1 import ModelIdentityFields
from setspec.serialization import TimestampField

__all__ = [
    "ApplicationProvenanceFields",
    "BenchmarkResultFields",
    "BenchmarkResultIn",
    "BenchmarkResultOut",
    "BenchmarkResultStatus",
    "BenchmarkRunSummaryFields",
    "BenchmarkRunSummaryIn",
    "BenchmarkRunSummaryOut",
    "BenchmarkSuiteProvenanceFields",
    "EnvironmentFields",
    "ExecutionProvenanceFields",
    "PromptUsageFields",
    "ReproducibilityFingerprintFields",
    "RunStatus",
    "RuntimeProfileFields",
    "ServedContextSource",
]


class RuntimeProfileFields(PayloadDefinition):
    """How a provider was asked to load and serve the model — nested only, never enveloped alone.

    Mirrors :class:`baseaicore.RuntimeProfile` field for field, including that every field is
    optional: a profile with everything unset means "provider defaults" and is itself a legal,
    hashable profile ([ADR-0023](../../../docs/adr/0023-runtime-profile-resolution.md) §1).

    Attributes:
        context_size: Requested context window, in tokens.
        kv_cache_precision: KV-cache quantization, e.g. ``"f16"``, ``"q8_0"``.
        gpu_layers: Number of layers offloaded to GPU.
        flash_attention: Whether flash attention was requested.
        threads: CPU thread count requested.
        batch_size: Requested batch size.
        keep_alive: How long the provider was asked to keep the model loaded, e.g. ``"5m"``.
        provider_options: Anything provider-specific with no field of its own.
    """

    context_size: int | None = None
    kv_cache_precision: str | None = None
    gpu_layers: int | None = None
    flash_attention: bool | None = None
    threads: int | None = None
    batch_size: int | None = None
    keep_alive: str | None = None
    provider_options: dict[str, Any] = Field(default_factory=dict)

    def _rebuilt(self) -> RuntimeProfile:
        """Reconstruct the equivalent :class:`baseaicore.RuntimeProfile`, to read its hash."""
        return RuntimeProfile(
            context_size=self.context_size,
            kv_cache_precision=self.kv_cache_precision,
            gpu_layers=self.gpu_layers,
            flash_attention=self.flash_attention,
            threads=self.threads,
            batch_size=self.batch_size,
            keep_alive=self.keep_alive,
            provider_options=dict(self.provider_options),
        )


class EnvironmentFields(PayloadDefinition):
    """Provider and drift-sensitive environment facts at the moment of measurement.

    Unifies two bullets that Machine Identity §6 and ADR-0022 describe separately but with
    identical content — "provider kind + provider version" and "GPU driver, CUDA, OS version at
    measurement" — into the one nested object ADR-0022 §1 already uses for
    ``capability.evidence.environment``, so a benchmark result and the evidence aggregated from it
    carry environment facts in the same shape.

    Attributes:
        provider_kind: Which kind of provider served the model for this measurement.
        provider_version: The provider's own version string, e.g. ``"0.32.13"``.
        gpu_driver_version: A drift signal, not identity; ``None`` when no GPU was involved.
        cuda_version: A drift signal, not identity.
        os_version: A drift signal, not identity.
    """

    provider_kind: WireEnum[ProviderKind]
    provider_version: str = Field(min_length=1)
    gpu_driver_version: str | None = None
    cuda_version: str | None = None
    os_version: str | None = None


class ApplicationProvenanceFields(PayloadDefinition):
    """Which build of the producing application measured this result.

    All three fields are part of Machine Identity §6's minimum provenance set — none is optional
    enrichment — because "which code produced this number" is exactly what a regression hunt needs
    first.

    Attributes:
        name: The producing application's distribution name, e.g. ``"freeweight"``.
        version: That application's version string.
        git_commit: The commit the running build was checked out at.
    """

    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    git_commit: str = Field(min_length=1)


class PromptUsageFields(PayloadDefinition):
    """One prompt this benchmark used, identified precisely enough to reproduce it.

    Attributes:
        prompt_id: The prompt's identifier in its manifest.
        version: The prompt's own version.
        sha256: The prompt's content hash, as computed by whatever produced it — not validated
            against a fixed hex format here; see the module docstring's note on hash-shaped
            fields.
    """

    prompt_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    sha256: str = Field(min_length=1)


class BenchmarkSuiteProvenanceFields(PayloadDefinition):
    """Which benchmark suite produced this result, and at what version.

    A differing ``suite_version``, ``dataset_hashes`` entry or ``prompt_subset_hash`` is a hard
    separation for confidence purposes, never a discount
    ([ADR-0017](../../../docs/adr/0017-benchmark-confidence-and-freshness.md)) — SetSpec carries
    these values; the separation itself is LoadCoach's and FreeWeight's behaviour to apply.

    Attributes:
        suite_key: The suite's identifier, e.g. ``"native.tool_use"``.
        suite_version: The suite's own version. A version bump separates results from different
            versions; they are never averaged together.
        category: The suite's category, e.g. ``"tool_use"``.
        runner: How the suite executes, e.g. ``"native"`` or ``"external"``.
        manifest_hash: Hash of the suite's manifest, as the producer computed it.
        dataset_hashes: Hash per named dataset the suite depends on; empty when the suite uses
            none.
        prompt_subset_hash: Hash of only the prompts *this suite* declares — the fingerprint
            input, per benchmark and not per pack
            ([ADR-0028](../../../docs/adr/0028-prompt-pack-granularity.md)).
        prompts_used: Every prompt named by ``prompt_subset_hash``, individually identified.
    """

    suite_key: str = Field(min_length=1)
    suite_version: str = Field(min_length=1)
    category: str | None = None
    runner: str | None = None
    manifest_hash: str = Field(min_length=1)
    dataset_hashes: dict[str, str] = Field(default_factory=dict)
    prompt_subset_hash: str = Field(min_length=1)
    prompts_used: WireSequence[PromptUsageFields] = ()


class ServedContextSource(StrEnum):
    """Where a run's actually-served context length came from.

    Distinct from :attr:`~setspec.model.v1.ModelIdentityFields.max_context`, which is what the
    model *advertises*, not what a provider was actually configured to serve
    ([ADR-0023](../../../docs/adr/0023-runtime-profile-resolution.md) §4).
    """

    CONFIGURED = "configured"
    """An operator or the runtime profile explicitly set it."""

    REPORTED = "reported"
    """The provider reported the context it actually served."""

    ASSUMED = "assumed"
    """Neither configured nor reported; taken from the model's advertised default."""


class ExecutionProvenanceFields(PayloadDefinition):
    """The execution parameters actually in effect for this result, after precedence resolution.

    Attributes:
        effective_parameters: Resolved sampling and limit parameters, post-precedence-chain —
            what was actually used, not what any one layer requested.
        repetitions: How many repetitions this result's configuration requested.
        sample_count: How many samples this result actually produced.
        seed: The seed used, or the literal string ``"nondeterministic"`` when none was set.
        served_context: The context length actually served.
        served_context_source: Where that value came from.
        gpu_index: The device this result's metrics are attributed to.
        multi_gpu_visible: Whether more than one GPU was visible during measurement
            ([ADR-0027](../../../docs/adr/0027-multi-gpu-semantics.md)).
    """

    effective_parameters: dict[str, Any] = Field(default_factory=dict)
    repetitions: int = Field(ge=1)
    sample_count: int = Field(ge=0)
    seed: int | str
    served_context: int = Field(ge=0)
    served_context_source: WireEnum[ServedContextSource]
    gpu_index: int = Field(ge=0, default=0)
    multi_gpu_visible: bool = False

    @model_validator(mode="after")
    def _check_seed(self) -> Self:
        """Require a string seed to be exactly the documented sentinel.

        Raises:
            ValueError: If ``seed`` is a string other than ``"nondeterministic"`` — a numeric
                string masquerading as a seed is a producer bug the schema should catch, not
                silently coerce.
        """
        if isinstance(self.seed, str) and self.seed != "nondeterministic":
            raise ValueError(
                f"seed must be an integer or the literal string 'nondeterministic'; got "
                f"{self.seed!r}. A run that did not set a seed says so with the sentinel, not "
                "with any other string."
            )
        return self


class ReproducibilityFingerprintFields(PayloadDefinition):
    """The answer to "could this measurement be repeated, and is that other result the same
    thing?"
    ([Machine Identity §4](../../../docs/architecture/machine-identity-and-reproducibility.md)).

    Attributes:
        reproducibility_fingerprint: The hash itself, as the producer computed it.
        fingerprint_document: The **full input document that was hashed**, stored verbatim per
            Machine Identity §4 rule 2 — "a hash you cannot explain is useless during a regression
            hunt." Kept as a structured but untyped mapping rather than a fully modeled nested
            structure: its shape mirrors provenance already typed elsewhere on this result, and a
            second, independently-typed copy of that shape would drift from the first the moment
            either one changed.
    """

    reproducibility_fingerprint: str = Field(min_length=1)
    fingerprint_document: dict[str, Any]


class BenchmarkResultStatus(StrEnum):
    """Terminal states of one benchmark within a run (``run_tests.status`` in FreeWeight's data
    model). A failed benchmark never fails its run; a failed sample never fails its benchmark."""

    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class BenchmarkResultFields(PayloadDefinition):
    """Field definitions for ``benchmark.result``; use :data:`BenchmarkResultOut` /
    :data:`BenchmarkResultIn`.

    One benchmark, one measurement subject, metrics plus provenance plus a samples reference
    ([spec §7](../../../docs/packages/setspec/spec.md)). The provenance fields are exactly Machine
    Identity §6's minimum set — see the module docstring for how each bullet there maps onto a
    field or nested object here.

    Attributes:
        model: The measured weights, plus what the provider reports about them.
        runtime_profile: How the provider was asked to serve the model for this measurement.
        runtime_profile_hash: :attr:`runtime_profile`'s hash — checked, not merely carried; see
            :meth:`_check_runtime_profile_hash`.
        machine_fingerprint: Where this was measured.
        machine_profile: A full snapshot of the machine at measurement time, when the producer
            chose to embed one rather than carry only the fingerprint.
        suite: Which benchmark suite produced this, and at what version.
        execution: The execution parameters actually in effect.
        environment: Provider and drift-sensitive facts at measurement time.
        application: Which build of the producing application measured this.
        reproducibility: The fingerprint proving this measurement could be repeated.
        started_at: When measurement began.
        completed_at: When measurement ended; never earlier than ``started_at``.
        status: This benchmark's terminal state.
        skip_reason: Present iff ``status`` is ``skipped``.
        metrics: Every metric this benchmark measured. Empty for a skipped or cancelled result;
            a completed result with none is rejected — see :meth:`_check_status_coherence`.
        samples_ref: An opaque, producer-local pointer to the raw sample rows behind ``metrics``.
            Never resolved by a consumer; carried only for the producer's own drill-down.
    """

    model: ModelIdentityFields
    runtime_profile: RuntimeProfileFields
    runtime_profile_hash: str = Field(min_length=1)
    machine_fingerprint: str = Field(min_length=1)
    machine_profile: MachineProfileFields | None = None
    suite: BenchmarkSuiteProvenanceFields
    execution: ExecutionProvenanceFields
    environment: EnvironmentFields
    application: ApplicationProvenanceFields
    reproducibility: ReproducibilityFingerprintFields
    started_at: TimestampField
    completed_at: TimestampField
    status: WireEnum[BenchmarkResultStatus]
    skip_reason: str | None = None
    metrics: WireSequence[MetricValueFields] = ()
    samples_ref: str | None = None

    @model_validator(mode="after")
    def _check_runtime_profile_hash(self) -> Self:
        """Recompute ``runtime_profile_hash`` from the embedded profile and require agreement.

        Safe to recompute for the same reason ``canonical_id`` is: a runtime profile's hash is a
        pure function of its own fields with no historical-policy caveat, unlike a machine
        fingerprint.

        Raises:
            ValueError: If the declared hash does not match what ``runtime_profile`` recomputes.
        """
        recomputed = self.runtime_profile._rebuilt().profile_hash  # noqa: SLF001 — same module
        if recomputed != self.runtime_profile_hash:
            raise ValueError(
                f"runtime_profile_hash {self.runtime_profile_hash!r} does not match "
                f"runtime_profile, which recomputes to {recomputed!r}. The hash is a pure "
                "function of the profile's own fields (ADR-0023) and is carried on the wire for "
                "convenience, not as an independent fact."
            )
        return self

    @model_validator(mode="after")
    def _check_timing_order(self) -> Self:
        """Require ``completed_at`` not to precede ``started_at``.

        Raises:
            ValueError: If the two timestamps are out of order.
        """
        if self.completed_at < self.started_at:
            raise ValueError(
                f"completed_at ({self.completed_at.isoformat()}) precedes started_at "
                f"({self.started_at.isoformat()}); a benchmark cannot finish before it started."
            )
        return self

    @model_validator(mode="after")
    def _check_status_coherence(self) -> Self:
        """Require ``skip_reason`` and ``metrics`` to agree with ``status``.

        Raises:
            ValueError: If ``skip_reason`` is set without ``status == "skipped"``, if a skipped
                result carries no ``skip_reason``, or if a completed result reports no metrics at
                all — a completed benchmark that measured nothing is not a completed benchmark.
        """
        if self.status is BenchmarkResultStatus.SKIPPED and self.skip_reason is None:
            raise ValueError("a skipped result must name its skip_reason")
        if self.status is not BenchmarkResultStatus.SKIPPED and self.skip_reason is not None:
            raise ValueError(
                f"skip_reason is set to {self.skip_reason!r} but status is {self.status.value!r}, "
                "not 'skipped'; skip_reason is only meaningful for a skipped result"
            )
        if self.status is BenchmarkResultStatus.COMPLETED and not self.metrics:
            raise ValueError(
                "status is 'completed' but metrics is empty; a completed benchmark that measured "
                "nothing is not a completed benchmark"
            )
        return self


BenchmarkResultOut, BenchmarkResultIn = payload_models(BenchmarkResultFields)
"""The ``benchmark.result`` payload pair: ``Out`` for writers, ``In`` for readers."""


class RunStatus(StrEnum):
    """A run's state, mirroring FreeWeight's run state machine (data model §3).

    ``INTERRUPTED`` is distinct from ``FAILED``: it means the process died, is discovered at
    startup recovery, and is resumable with completed benchmarks preserved — a run summary
    carrying it is not reporting a failure, it is reporting an unfinished run.
    """

    QUEUED = "queued"
    PREPARING = "preparing"
    WARMING = "warming"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class BenchmarkRunSummaryFields(PayloadDefinition):
    """Field definitions for ``benchmark.run_summary``; use :data:`BenchmarkRunSummaryOut` /
    :data:`BenchmarkRunSummaryIn`.

    One run: subject, suite, status, timings, aggregate metrics
    ([spec §7](../../../docs/packages/setspec/spec.md)) — deliberately lighter than
    :class:`BenchmarkResultFields`, which carries one benchmark's full per-result provenance; a run
    summary is the roll-up of many such results and reuses the same subject/suite/environment
    building blocks rather than repeating a full provenance set per aggregate metric.

    Attributes:
        model: The measurement subject's model identity.
        runtime_profile: The runtime profile every benchmark in this run measured under.
        runtime_profile_hash: Checked against ``runtime_profile``, as on a result.
        machine_fingerprint: Where this run executed.
        suite: The suite this run executed.
        environment: Provider and drift-sensitive facts for the run.
        application: Which build of the producing application ran this.
        reproducibility: The run-level reproducibility fingerprint.
        status: The run's current or terminal state.
        created_at: When the run was created (queued).
        started_at: When execution began; ``None`` if the run never left ``queued``.
        completed_at: When execution ended; ``None`` while still in progress.
        aggregate_metrics: Run-level rolled-up metrics, distinct from any one benchmark's own.
        error_code: Present iff the run ended in a state a caller should investigate.
        error_text: Human-readable detail alongside ``error_code``.
    """

    model: ModelIdentityFields
    runtime_profile: RuntimeProfileFields
    runtime_profile_hash: str = Field(min_length=1)
    machine_fingerprint: str = Field(min_length=1)
    suite: BenchmarkSuiteProvenanceFields
    environment: EnvironmentFields
    application: ApplicationProvenanceFields
    reproducibility: ReproducibilityFingerprintFields
    status: WireEnum[RunStatus]
    created_at: TimestampField
    started_at: TimestampField | None = None
    completed_at: TimestampField | None = None
    aggregate_metrics: WireSequence[MetricValueFields] = ()
    error_code: str | None = None
    error_text: str | None = None

    @model_validator(mode="after")
    def _check_runtime_profile_hash(self) -> Self:
        """Recompute ``runtime_profile_hash`` from the embedded profile and require agreement.

        Raises:
            ValueError: If the declared hash does not match what ``runtime_profile`` recomputes.
        """
        recomputed = self.runtime_profile._rebuilt().profile_hash  # noqa: SLF001 — same module
        if recomputed != self.runtime_profile_hash:
            raise ValueError(
                f"runtime_profile_hash {self.runtime_profile_hash!r} does not match "
                f"runtime_profile, which recomputes to {recomputed!r}."
            )
        return self

    @model_validator(mode="after")
    def _check_timing_order(self) -> Self:
        """Require ``completed_at`` not to precede ``started_at`` when both are present.

        Raises:
            ValueError: If both timestamps are present and out of order.
        """
        if (
            self.started_at is not None
            and self.completed_at is not None
            and self.completed_at < self.started_at
        ):
            raise ValueError(
                f"completed_at ({self.completed_at.isoformat()}) precedes started_at "
                f"({self.started_at.isoformat()})."
            )
        return self


BenchmarkRunSummaryOut, BenchmarkRunSummaryIn = payload_models(BenchmarkRunSummaryFields)
"""The ``benchmark.run_summary`` payload pair: ``Out`` for writers, ``In`` for readers."""
