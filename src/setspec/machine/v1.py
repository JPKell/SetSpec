"""Contract module — ``machine.profile`` v1: the static identity of the machine a run measured on.

Imports pydantic and :mod:`baseaicore`; performs no I/O. Exchange form of
:class:`baseaicore.MachineProfile` — a field-for-field mirror, including which fields are
required. A dataclass field with no Python default is required on the wire too; a field with a
default keeps that same default here, so a machine that could not report its core count produces
the identical payload whether it went through this schema or was read straight from BaseAiCore.

**Status: draft (`1.0`).** See :mod:`setspec.model.v1` for what that means and why.

**Deliberately not re-verified:** ``machine_fingerprint``. This is the one place a hash-shaped
field is carried without being recomputed and checked, and the asymmetry with
:mod:`setspec.model.v1` — which does recompute ``canonical_id`` — is the domain type's own
choice, not an oversight here. :class:`baseaicore.MachineProfile` documents its fingerprint as
"the *recorded* fingerprint, not a derived property... neither computed nor re-verified", because
the policy deciding which fields feed the fingerprint may change after a profile was written,
while a profile read back years later must still reconstruct exactly as stored. A ``canonical_id``
has no such caveat: it is a pure function of the identity triple under a format ADR-0024 fixes.
Recomputing a fingerprint here would therefore reject a historically valid profile the day that
policy changes, which is why this schema follows the domain type rather than its own sibling.
"""

from __future__ import annotations

from baseaicore import UNSUPPORTED, GpuVendor
from pydantic import Field

from setspec.base import PayloadDefinition, WireEnum, WireSequence, payload_models
from setspec.serialization import MeasurementField, TimestampField

__all__ = [
    "GpuProfileFields",
    "MachineProfileFields",
    "MachineProfileIn",
    "MachineProfileOut",
    "StorageDeviceFields",
]


class GpuProfileFields(PayloadDefinition):
    """Static identity of one GPU, as a collector reported it.

    Nested only — ``gpu.profile`` is not independently enveloped
    (ADR-0009 lists no such schema), so this
    is a plain :class:`~setspec.base.PayloadDefinition` rather than a generated pair; see that
    class's docstring for why an embedded definition is always preserving.

    Attributes:
        index: The device's 0-based enumeration position; also the value a benchmark result
            attributes a per-device measurement to
            (ADR-0027).
        name: The marketing name, e.g. ``"NVIDIA GeForce RTX 5060 Ti"``.
        uuid: The device's stable hardware identifier, unchanged across reboots. ``None`` when the
            collector could not read one.
        vram_total_bytes: Total device memory — never "used", which is telemetry.
        driver_version: The installed driver version. A drift signal, not identity.
        cuda_version: The CUDA/ROCm toolkit version. A drift signal, not identity.
        compute_capability: The device's compute capability, e.g. ``"12.0"``.
        vendor: Who makes the device; ``UNKNOWN`` is the honest default, not a guess.
    """

    index: int = Field(ge=0)
    name: str | None = None
    uuid: str | None = None
    vram_total_bytes: MeasurementField = UNSUPPORTED
    driver_version: str | None = None
    cuda_version: str | None = None
    compute_capability: str | None = None
    vendor: WireEnum[GpuVendor] = GpuVendor.UNKNOWN


class StorageDeviceFields(PayloadDefinition):
    """A storage device attached to the machine — provenance only, excluded from the fingerprint.

    Attributes:
        name: The device name as the OS exposes it, e.g. ``"nvme0n1"``.
        size_bytes: Total capacity.
        model: The device's model string, if the OS exposes one.
        rotational: ``True`` for spinning, ``False`` for solid state, ``None`` when the collector
            could not tell — never guessed as ``False``.
    """

    name: str = Field(min_length=1)
    size_bytes: MeasurementField = UNSUPPORTED
    model: str | None = None
    rotational: bool | None = None


class MachineProfileFields(PayloadDefinition):
    """Field definitions for ``machine.profile``; use :data:`MachineProfileOut` /
    :data:`MachineProfileIn`.

    Attributes:
        machine_fingerprint: The identity this profile was stored under.
        hostname: The machine's hostname. Required as a key (may be ``null``): a producer must say
            explicitly that it could not read one, not merely omit it — the schema-level half of
            "provenance completeness enforced by the schema" (Phase 2 gold standard).
        os_name: e.g. ``"Linux"``.
        os_version: e.g. ``"Ubuntu 26.04 LTS"``. A drift signal, not identity.
        kernel: The kernel release string. A drift signal, not identity.
        architecture: e.g. ``"x86_64"``.
        cpu_model: The CPU's model string.
        physical_cores: Physical core count.
        logical_cores: Logical core count, hyperthreads included.
        ram_bytes: Total system memory.
        gpus: Every visible GPU. Never summed or averaged by any consumer
            (ADR-0027).
        storage: Attached storage devices. Provenance only; excluded from the fingerprint.
        python_version: The interpreter that produced the measurement — application environment,
            not machine identity.
        observed_at: When this snapshot was taken.
    """

    machine_fingerprint: str = Field(min_length=1)
    hostname: str | None
    os_name: str | None
    os_version: str | None
    kernel: str | None
    architecture: str | None
    cpu_model: str | None
    physical_cores: MeasurementField = UNSUPPORTED
    logical_cores: MeasurementField = UNSUPPORTED
    ram_bytes: MeasurementField = UNSUPPORTED
    gpus: WireSequence[GpuProfileFields] = ()
    storage: WireSequence[StorageDeviceFields] = ()
    python_version: str | None = None
    observed_at: TimestampField | None = None


MachineProfileOut, MachineProfileIn = payload_models(MachineProfileFields)
"""The ``machine.profile`` payload pair: ``Out`` for writers, ``In`` for readers."""
