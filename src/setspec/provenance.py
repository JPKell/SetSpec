"""Contract module — provenance building blocks shared by more than one versioned payload.

Imports pydantic and :mod:`baseaicore`; performs no I/O.

This module exists for the same reason :mod:`setspec.metrics` does. A sub-model used by two
payload types belongs to neither of them: if ``EnvironmentFields`` lived in
:mod:`setspec.benchmark.v1`, then the day ``benchmark.result`` needs a changed environment shape,
whoever edits that class would silently change ``capability.evidence`` v1 too — a frozen contract
mutating because someone edited a different payload's module, which is precisely the drift
ADR-0009 exists to prevent. A shared block gets
a neutral home so that changing it is an obviously cross-cutting act rather than an accident.

Nothing here is a wire payload in its own right: none of these names appears in
:data:`~setspec.envelope.SUPPORTED_SCHEMAS`, and none is generated into an ``Out``/``In`` pair.
They are field groups that versioned payloads embed, which is why they carry no version of their
own — their version is whichever payload's version they appear inside.
"""

from __future__ import annotations

from baseaicore import ProviderKind
from pydantic import Field

from setspec.base import PayloadDefinition, WireEnum

__all__ = ["EnvironmentFields"]


class EnvironmentFields(PayloadDefinition):
    """Provider and drift-sensitive environment facts at the moment of measurement.

    Unifies two bullets that
    Machine Identity §6 and
    ADR-0022 §1 describe separately
    but with identical content — "provider kind + provider version" and "GPU driver, CUDA, OS
    version at measurement" — into the one nested object ADR-0022 already names ``environment`` on
    ``capability.evidence``, so a benchmark result and the evidence aggregated from it carry
    environment facts in the same shape rather than two shapes a consumer has to reconcile.

    Every field but the provider's own identity is a **drift signal, not identity**: a driver
    upgrade or an OS patch must never re-identify a machine (that is the machine fingerprint's
    job, and it deliberately excludes all of these), but it does reduce confidence in performance
    evidence measured before it
    (ADR-0017's
    ``environment_factor``). Recording them is what makes that reduction computable at all.

    Attributes:
        provider_kind: Which kind of provider served the model for this measurement.
        provider_version: The provider's own version string, e.g. ``"0.32.13"``.
        gpu_driver_version: A drift signal; ``None`` when no GPU was involved.
        cuda_version: The CUDA/ROCm toolkit version. A drift signal.
        os_version: A drift signal.
    """

    provider_kind: WireEnum[ProviderKind]
    provider_version: str = Field(min_length=1)
    gpu_driver_version: str | None = None
    cuda_version: str | None = None
    os_version: str | None = None
