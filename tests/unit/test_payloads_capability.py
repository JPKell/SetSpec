"""Tests for ``model.identity``, ``model.adapter_manifest``, ``machine.profile``,
``capability.evidence`` (`1.0` and `1.1`) and ``benchmark.evidence_bundle`` (`1.0` and `1.1`)
(:mod:`setspec.model.v1`, :mod:`setspec.machine.v1`, :mod:`setspec.capability.v1`).

``benchmark.result`` and ``benchmark.run_summary`` (:mod:`setspec.benchmark.v1`) have their own
file, ``test_payloads_benchmark.py``, since a realistic result is large enough to want its own
fixture builder. ``governance.egress_decision`` (:mod:`setspec.governance.v1`) has its own file,
``test_payloads_governance.py``, since it is a new namespace root rather than an extension of one
already tested here.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError as PydanticValidationError

from setspec import canonical_dumps
from setspec.capability.v1 import (
    CapabilityEvidenceIn,
    CapabilityEvidenceOut,
    CapabilityEvidenceV1_1In,
    CapabilityEvidenceV1_1Out,
    EvidenceBundleIn,
    EvidenceBundleOut,
    EvidenceBundleV1_1In,
    EvidenceBundleV1_1Out,
)
from setspec.machine.v1 import MachineProfileIn, MachineProfileOut
from setspec.model.v1 import (
    AdapterIdentityFields,
    AdapterManifestIn,
    AdapterManifestOut,
    ModelIdentityIn,
    ModelIdentityOut,
)

_OBSERVED_AT = datetime(2026, 8, 20, 9, 0, 0, tzinfo=UTC)


def _identity(**overrides: Any) -> dict[str, Any]:
    """A minimal, valid model.identity document, with fields optionally replaced."""
    return {
        "provider_kind": "ollama",
        "provider_model_name": "qwen3.5:9b-q8_0",
        "artifact_digest": None,
        "identity_confidence": "name_only",
        "canonical_id": "ollama/qwen3.5:9b-q8_0@unknown",
        "observed_at": _OBSERVED_AT.isoformat(),
    } | overrides


def _digest_identity(**overrides: Any) -> dict[str, Any]:
    """A minimal, valid model.identity document with a real digest."""
    digest = "sha256:" + "1f3a9c4e2b70" + "0" * 52
    base = {
        "artifact_digest": digest,
        "identity_confidence": "digest",
        "canonical_id": "ollama/qwen3.5:9b-q8_0@sha256:1f3a9c4e2b70",
    }
    return _identity(**(base | overrides))


class TestModelIdentity:
    """The identity triple plus the derived fields ADR-0022 §1 always carries alongside it."""

    def test_a_name_only_identity_round_trips(self) -> None:
        identity = ModelIdentityOut.model_validate(_identity())
        assert ModelIdentityOut.model_validate(json.loads(canonical_dumps(identity))) == identity

    def test_a_digest_identity_round_trips(self) -> None:
        identity = ModelIdentityOut.model_validate(_digest_identity())
        assert identity.identity_confidence.value == "digest"

    def test_canonical_id_must_match_the_recomputed_identity(self) -> None:
        with pytest.raises(PydanticValidationError, match="canonical_id"):
            ModelIdentityOut.model_validate(_identity(canonical_id="wrong/value@unknown"))

    def test_identity_confidence_must_match_a_present_digest(self) -> None:
        with pytest.raises(PydanticValidationError, match="identity_confidence"):
            ModelIdentityOut.model_validate(_digest_identity(identity_confidence="name_only"))

    def test_identity_confidence_must_match_an_absent_digest(self) -> None:
        with pytest.raises(PydanticValidationError, match="identity_confidence"):
            ModelIdentityOut.model_validate(_identity(identity_confidence="digest"))

    def test_a_malformed_digest_is_rejected_by_the_underlying_domain_type(self) -> None:
        """baseaicore.ModelIdentity's own validation surfaces through, not reimplemented here."""
        with pytest.raises(PydanticValidationError):
            ModelIdentityOut.model_validate(_identity(artifact_digest="not-a-digest"))

    def test_an_empty_provider_model_name_is_rejected(self) -> None:
        with pytest.raises(PydanticValidationError):
            ModelIdentityOut.model_validate(_identity(provider_model_name=""))

    def test_measurement_fields_default_to_unsupported(self) -> None:
        identity = ModelIdentityOut.model_validate(_identity())
        assert identity.model_dump()["parameter_count"] == "unsupported"

    def test_declared_capabilities_accepts_known_flags(self) -> None:
        identity = ModelIdentityOut.model_validate(
            _identity(declared_capabilities=["tools", "vision"])
        )
        assert len(identity.declared_capabilities) == 2

    def test_declared_capabilities_rejects_an_unknown_flag(self) -> None:
        with pytest.raises(PydanticValidationError):
            ModelIdentityOut.model_validate(_identity(declared_capabilities=["not_a_flag"]))

    def test_in_preserves_an_unknown_field(self) -> None:
        identity = ModelIdentityIn.model_validate(_identity(future_field="x"))
        assert identity.extras == {"future_field": "x"}

    def test_out_refuses_an_unknown_field(self) -> None:
        with pytest.raises(PydanticValidationError):
            ModelIdentityOut.model_validate(_identity(future_field="x"))


def _machine(**overrides: Any) -> dict[str, Any]:
    """A minimal, valid machine.profile document, with fields optionally replaced."""
    return {
        "machine_fingerprint": "a" * 64,
        "hostname": "bench-01",
        "os_name": "Linux",
        "os_version": None,
        "kernel": None,
        "architecture": "x86_64",
        "cpu_model": "AMD Ryzen 9 9950X",
    } | overrides


class TestMachineProfile:
    """Field-for-field mirror of baseaicore.MachineProfile, including required-vs-optional."""

    def test_a_minimal_profile_round_trips(self) -> None:
        profile = MachineProfileOut.model_validate(_machine())
        assert MachineProfileOut.model_validate(json.loads(canonical_dumps(profile))) == profile

    def test_a_full_profile_with_gpus_and_storage_validates(self) -> None:
        profile = MachineProfileOut.model_validate(
            _machine(
                physical_cores=16,
                logical_cores=32,
                ram_bytes=64 * 1024**3,
                gpus=[
                    {
                        "index": 0,
                        "name": "RTX 5060 Ti",
                        "uuid": "GPU-abc",
                        "vram_total_bytes": 16 * 1024**3,
                        "vendor": "nvidia",
                    }
                ],
                storage=[{"name": "nvme0n1", "size_bytes": 10**12, "rotational": False}],
                python_version="3.13.15",
                observed_at=_OBSERVED_AT.isoformat(),
            )
        )
        assert profile.gpus[0].vendor.value == "nvidia"
        assert profile.storage[0].rotational is False

    def test_an_empty_fingerprint_is_rejected(self) -> None:
        with pytest.raises(PydanticValidationError):
            MachineProfileOut.model_validate(_machine(machine_fingerprint=""))

    def test_hostname_key_is_required_even_though_nullable(self) -> None:
        document = _machine()
        del document["hostname"]
        with pytest.raises(PydanticValidationError, match="hostname"):
            MachineProfileOut.model_validate(document)

    def test_hostname_may_be_explicitly_null(self) -> None:
        profile = MachineProfileOut.model_validate(_machine(hostname=None))
        assert profile.hostname is None

    def test_a_negative_gpu_index_is_rejected(self) -> None:
        with pytest.raises(PydanticValidationError):
            MachineProfileOut.model_validate(
                _machine(gpus=[{"index": -1, "name": None, "uuid": None}])
            )

    def test_gpus_and_storage_default_to_empty(self) -> None:
        profile = MachineProfileOut.model_validate(_machine())
        assert profile.gpus == ()
        assert profile.storage == ()

    def test_in_preserves_unknown_top_level_fields(self) -> None:
        profile = MachineProfileIn.model_validate(_machine(future_field="x"))
        assert profile.extras == {"future_field": "x"}

    def test_in_preserves_unknown_fields_on_a_nested_gpu(self) -> None:
        """A definition nested without payload_models() preserves regardless of direction."""
        profile = MachineProfileIn.model_validate(
            _machine(gpus=[{"index": 0, "name": None, "uuid": None, "power_limit_watts": 300}])
        )
        assert profile.gpus[0].extras == {"power_limit_watts": 300}


def _model_identity_dict() -> dict[str, Any]:
    return _identity()


def _evidence(**overrides: Any) -> dict[str, Any]:
    """A minimal, valid capability.evidence document, with fields optionally replaced."""
    measured_at = datetime(2026, 8, 20, tzinfo=UTC)
    computed_at = datetime(2026, 8, 22, tzinfo=UTC)
    return {
        "model": _model_identity_dict(),
        "runtime_profile_hash": "a" * 16,
        "machine_fingerprint": "b" * 64,
        "capability_id": "coding.python",
        "score": 0.82,
        "confidence": 0.71,
        "sample_count": 40,
        "excluded_count": 2,
        "dispersion": 0.09,
        "measured_at": measured_at.isoformat(),
        "computed_at": computed_at.isoformat(),
        "policy_version": "1.0",
        "vocabulary_version": "1.0",
        "environment": {"provider_kind": "ollama", "provider_version": "0.32.13"},
    } | overrides


class TestCapabilityEvidence:
    """ADR-0022 §1's normative field set, enforced structurally rather than by convention."""

    def test_a_realistic_evidence_record_validates(self) -> None:
        evidence = CapabilityEvidenceOut.model_validate(_evidence())
        assert evidence.capability_id == "coding.python"

    def test_round_trips_through_canonical_json(self) -> None:
        evidence = CapabilityEvidenceOut.model_validate(_evidence())
        assert (
            CapabilityEvidenceOut.model_validate(json.loads(canonical_dumps(evidence))) == evidence
        )

    @pytest.mark.parametrize("field", ["measured_at", "policy_version", "vocabulary_version"])
    def test_missing_a_required_field_is_rejected_and_named(self, field: str) -> None:
        document = _evidence()
        del document[field]
        with pytest.raises(PydanticValidationError, match=field):
            CapabilityEvidenceOut.model_validate(document)

    def test_measured_at_later_than_computed_at_is_rejected(self) -> None:
        with pytest.raises(PydanticValidationError):
            CapabilityEvidenceOut.model_validate(
                _evidence(
                    measured_at=(datetime(2026, 8, 23, tzinfo=UTC)).isoformat(),
                    computed_at=datetime(2026, 8, 22, tzinfo=UTC).isoformat(),
                )
            )

    def test_measured_at_equal_to_computed_at_is_coherent(self) -> None:
        """Recomputing the instant it finished is the boundary case, and it is not incoherent."""
        same_instant = datetime(2026, 8, 22, tzinfo=UTC).isoformat()
        evidence = CapabilityEvidenceOut.model_validate(
            _evidence(measured_at=same_instant, computed_at=same_instant)
        )
        assert evidence.measured_at == evidence.computed_at

    @pytest.mark.parametrize("score", [-0.01, 1.01])
    def test_score_out_of_range_is_rejected(self, score: float) -> None:
        with pytest.raises(PydanticValidationError):
            CapabilityEvidenceOut.model_validate(_evidence(score=score))

    @pytest.mark.parametrize("confidence", [0.0, 0.049, 1.01])
    def test_confidence_outside_the_adr_0017_floor_and_ceiling_is_rejected(
        self, confidence: float
    ) -> None:
        with pytest.raises(PydanticValidationError):
            CapabilityEvidenceOut.model_validate(_evidence(confidence=confidence))

    def test_confidence_at_the_adr_0017_floor_is_accepted(self) -> None:
        evidence = CapabilityEvidenceOut.model_validate(_evidence(confidence=0.05))
        assert evidence.confidence == 0.05

    @pytest.mark.parametrize("field", ["sample_count", "excluded_count"])
    def test_a_negative_count_is_rejected(self, field: str) -> None:
        with pytest.raises(PydanticValidationError):
            CapabilityEvidenceOut.model_validate(_evidence(**{field: -1}))

    def test_dispersion_accepts_unsupported(self) -> None:
        evidence = CapabilityEvidenceOut.model_validate(_evidence(dispersion="unsupported"))
        assert evidence.model_dump()["dispersion"] == "unsupported"

    def test_an_unknown_capability_root_is_rejected(self) -> None:
        with pytest.raises(PydanticValidationError):
            CapabilityEvidenceOut.model_validate(_evidence(capability_id="not_a_real_capability"))

    def test_an_unenumerated_specialization_of_a_known_root_is_accepted(self) -> None:
        evidence = CapabilityEvidenceOut.model_validate(_evidence(capability_id="coding.rust"))
        assert evidence.capability_id == "coding.rust"

    def test_a_forward_compatible_vocabulary_version_accepts_an_unknown_capability(self) -> None:
        evidence = CapabilityEvidenceOut.model_validate(
            _evidence(capability_id="a_future_capability", vocabulary_version="1.99")
        )
        assert evidence.capability_id == "a_future_capability"

    def test_contributing_metrics_round_trip(self) -> None:
        evidence = CapabilityEvidenceOut.model_validate(
            _evidence(
                contributing_metrics=[
                    {"metric_key": "task_success", "weight": 1.0, "sample_count": 40}
                ]
            )
        )
        assert evidence.contributing_metrics[0].metric_key == "task_success"

    def test_a_non_positive_metric_weight_is_rejected(self) -> None:
        with pytest.raises(PydanticValidationError):
            CapabilityEvidenceOut.model_validate(
                _evidence(
                    contributing_metrics=[
                        {"metric_key": "task_success", "weight": 0.0, "sample_count": 40}
                    ]
                )
            )

    def test_source_run_ids_round_trip_as_a_tuple(self) -> None:
        evidence = CapabilityEvidenceOut.model_validate(
            _evidence(source_run_ids=["run_01", "run_02"])
        )
        assert evidence.source_run_ids == ("run_01", "run_02")

    def test_in_preserves_an_unknown_field(self) -> None:
        evidence = CapabilityEvidenceIn.model_validate(_evidence(future_field=1))
        assert evidence.extras == {"future_field": 1}


class TestEvidenceBundle:
    """ADR-0022 §5: many evidence records plus the flag that makes incremental import possible."""

    def test_a_bundle_of_several_records_validates(self) -> None:
        bundle = EvidenceBundleOut.model_validate(
            {
                "source_id": "freeweight-main",
                "complete": True,
                "evidence": [_evidence(), _evidence(capability_id="reasoning")],
            }
        )
        assert len(bundle.evidence) == 2

    def test_an_empty_bundle_is_valid(self) -> None:
        """A source with no evidence yet is a legitimate complete export, not an error."""
        bundle = EvidenceBundleOut.model_validate(
            {"source_id": "freeweight-main", "complete": True, "evidence": []}
        )
        assert bundle.evidence == ()

    def test_complete_is_required(self) -> None:
        with pytest.raises(PydanticValidationError, match="complete"):
            EvidenceBundleOut.model_validate({"source_id": "freeweight-main", "evidence": []})

    def test_generated_at_is_not_a_bundle_field(self) -> None:
        """It lives on the envelope; duplicating it here would create two disagreeing clocks."""
        assert "generated_at" not in EvidenceBundleOut.model_fields

    def test_round_trips_through_canonical_json(self) -> None:
        bundle = EvidenceBundleOut.model_validate(
            {"source_id": "freeweight-main", "complete": False, "evidence": [_evidence()]}
        )
        assert EvidenceBundleOut.model_validate(json.loads(canonical_dumps(bundle))) == bundle

    def test_in_preserves_an_unknown_field_on_a_nested_evidence_record(self) -> None:
        bundle = EvidenceBundleIn.model_validate(
            {
                "source_id": "freeweight-main",
                "complete": True,
                "evidence": [_evidence(future_field="x")],
            }
        )
        assert bundle.evidence[0].extras == {"future_field": "x"}


class TestEvidenceBundleV1_1:
    """`benchmark.evidence_bundle` `1.1` (Phase 7, ADR-0068 rule 5): the same sibling-class
    mechanism as `capability.evidence` `1.1`, one payload out — nesting `1.1` evidence records
    rather than adding a field of its own."""

    def test_a_bundle_with_no_adapter_dumps_byte_identical_to_1_0(self) -> None:
        document = {
            "source_id": "freeweight-main",
            "complete": True,
            "evidence": [_evidence(), _evidence(capability_id="reasoning")],
        }
        old = EvidenceBundleOut.model_validate(document)
        new = EvidenceBundleV1_1Out.model_validate(document)
        assert all(record.adapter is None for record in new.evidence)
        assert canonical_dumps(old) == canonical_dumps(new)

    def test_a_bundle_with_an_adapter_bearing_record_round_trips(self) -> None:
        bundle = EvidenceBundleV1_1Out.model_validate(
            {
                "source_id": "freeweight-main",
                "complete": True,
                "evidence": [_evidence(adapter=_adapter()), _evidence(capability_id="reasoning")],
            }
        )
        assert bundle.evidence[0].adapter is not None
        assert bundle.evidence[1].adapter is None
        assert EvidenceBundleV1_1Out.model_validate(json.loads(canonical_dumps(bundle))) == bundle

    def test_adapter_absent_from_the_dump_on_the_bare_base_record_only(self) -> None:
        bundle = EvidenceBundleV1_1Out.model_validate(
            {
                "source_id": "freeweight-main",
                "complete": True,
                "evidence": [_evidence(adapter=_adapter()), _evidence(capability_id="reasoning")],
            }
        )
        dumped = json.loads(canonical_dumps(bundle))
        assert "adapter" in dumped["evidence"][0]
        assert "adapter" not in dumped["evidence"][1]

    def test_in_preserves_an_unknown_field_alongside_an_adapter_bearing_record(self) -> None:
        bundle = EvidenceBundleV1_1In.model_validate(
            {
                "source_id": "freeweight-main",
                "complete": True,
                "evidence": [_evidence(adapter=_adapter(), future_field="x")],
            }
        )
        assert bundle.evidence[0].extras == {"future_field": "x"}

    def test_a_1_0_reader_preserves_an_unknown_adapter_bearing_record(self) -> None:
        """A `1.0` reader in front of a `1.1` bundle loses nothing (ADR-0009 rule 4)."""
        document = {
            "source_id": "freeweight-main",
            "complete": True,
            "evidence": [_evidence(adapter=_adapter())],
        }
        bundle = EvidenceBundleIn.model_validate(document)
        assert bundle.evidence[0].extras["adapter"] == _adapter()


class TestSharedEnvironmentBlock:
    """`environment` is one shared definition, not two that happen to agree today.

    ADR-0022 §1 puts `environment` on `capability.evidence`; Machine Identity §4 and §6 put the
    same facts on a benchmark result. If each module defined its own copy, the two could drift
    apart field by field while every test in both files kept passing — the exact failure the
    audit behind ADR-0022 found between FreeWeight and LoadCoach on paper.
    """

    def test_both_payloads_use_the_same_definition_object(self) -> None:
        from setspec.benchmark.v1 import BenchmarkResultFields
        from setspec.provenance import EnvironmentFields

        assert CapabilityEvidenceOut.model_fields["environment"].annotation is EnvironmentFields
        assert BenchmarkResultFields.model_fields["environment"].annotation is EnvironmentFields

    def test_the_shared_block_lives_outside_both_versioned_modules(self) -> None:
        """Its home is neutral, so changing it is an obviously cross-cutting act."""
        from setspec.provenance import EnvironmentFields

        assert EnvironmentFields.__module__ == "setspec.provenance"

    def test_drift_signals_are_optional_but_the_provider_is_not(self) -> None:
        """A driver version may be absent; which provider produced the numbers may not be."""
        evidence = CapabilityEvidenceOut.model_validate(_evidence())
        assert evidence.environment.gpu_driver_version is None
        with pytest.raises(PydanticValidationError, match="provider_version"):
            CapabilityEvidenceOut.model_validate(_evidence(environment={"provider_kind": "ollama"}))

    def test_a_fully_populated_environment_round_trips(self) -> None:
        evidence = CapabilityEvidenceOut.model_validate(
            _evidence(
                environment={
                    "provider_kind": "ollama",
                    "provider_version": "0.32.13",
                    "gpu_driver_version": "580.65.06",
                    "cuda_version": "13.0",
                    "os_version": "Ubuntu 26.04 LTS",
                }
            )
        )
        assert (
            CapabilityEvidenceOut.model_validate(json.loads(canonical_dumps(evidence))) == evidence
        )


_ADAPTER_DIGEST = "sha256:" + "9e2b41d07c55" + "0" * 52


def _adapter(**overrides: Any) -> dict[str, Any]:
    """A minimal, valid adapter identity, embeddable on a `1.1` evidence record."""
    return {
        "name": "factcheck",
        "artifact_digest": _ADAPTER_DIGEST,
        "source_digest": None,
        "canonical_suffix": "+factcheck@sha256:9e2b41d07c55",
    } | overrides


class TestAdapterIdentity:
    """The nested wire form of ``baseaicore.AdapterIdentity`` (ADR-0058)."""

    def test_a_minimal_adapter_identity_round_trips(self) -> None:
        identity = AdapterIdentityFields.model_validate(_adapter())
        assert AdapterIdentityFields.model_validate(json.loads(canonical_dumps(identity))) == (
            identity
        )

    def test_canonical_suffix_must_match_the_recomputed_identity(self) -> None:
        with pytest.raises(PydanticValidationError, match="canonical_suffix"):
            AdapterIdentityFields.model_validate(
                _adapter(canonical_suffix="+wrong@sha256:aaaaaaaaaaaa")
            )

    def test_a_malformed_name_is_rejected_by_the_underlying_domain_type(self) -> None:
        """baseaicore.AdapterIdentity's own validation surfaces through, not reimplemented here."""
        with pytest.raises(PydanticValidationError):
            AdapterIdentityFields.model_validate(_adapter(name="Not-Valid"))

    def test_a_malformed_digest_is_rejected(self) -> None:
        with pytest.raises(PydanticValidationError):
            AdapterIdentityFields.model_validate(_adapter(artifact_digest="not-a-digest"))

    def test_source_digest_is_optional(self) -> None:
        identity = AdapterIdentityFields.model_validate(
            _adapter(source_digest="sha256:" + "c1" * 32)
        )
        assert identity.source_digest is not None


class TestCapabilityEvidenceV1_1:
    """The optional ``adapter`` field this row adds — additive proof, not merely a new field."""

    def test_a_record_with_no_adapter_dumps_byte_identical_to_1_0(self) -> None:
        """The literal I15 promise: a `1.1` writer with no adapter reproduces `1.0`'s bytes."""
        document = _evidence()
        old = CapabilityEvidenceOut.model_validate(document)
        new = CapabilityEvidenceV1_1Out.model_validate(document)
        assert new.adapter is None
        assert canonical_dumps(old) == canonical_dumps(new)

    def test_adapter_is_absent_from_the_dump_rather_than_null(self) -> None:
        new = CapabilityEvidenceV1_1Out.model_validate(_evidence())
        assert "adapter" not in json.loads(canonical_dumps(new))

    def test_a_record_with_an_adapter_round_trips(self) -> None:
        evidence = CapabilityEvidenceV1_1Out.model_validate(_evidence(adapter=_adapter()))
        assert evidence.adapter is not None
        assert evidence.adapter.name == "factcheck"
        assert (
            CapabilityEvidenceV1_1Out.model_validate(json.loads(canonical_dumps(evidence)))
            == evidence
        )

    def test_adapter_present_in_the_dump_when_set(self) -> None:
        new = CapabilityEvidenceV1_1Out.model_validate(_evidence(adapter=_adapter()))
        assert json.loads(canonical_dumps(new))["adapter"]["name"] == "factcheck"

    def test_a_1_0_reader_preserves_an_unknown_adapter_field(self) -> None:
        """A `1.0` reader in front of a `1.1` document loses nothing (ADR-0009 rule 4)."""
        document = _evidence(adapter=_adapter())
        parsed = CapabilityEvidenceIn.model_validate(document)
        assert parsed.extras["adapter"] == _adapter()

    def test_in_preserves_an_unknown_field_alongside_adapter(self) -> None:
        evidence = CapabilityEvidenceV1_1In.model_validate(
            _evidence(adapter=_adapter(), future_field=1)
        )
        assert evidence.extras == {"future_field": 1}


_MANIFEST_CREATED_AT = datetime(2026, 9, 1, 10, 0, 0, tzinfo=UTC)


def _manifest(**overrides: Any) -> dict[str, Any]:
    """A minimal, valid model.adapter_manifest document with a name-only base."""
    return {
        "name": "factcheck",
        "artifact_file": "factcheck.gguf",
        "artifact_sha256": _ADAPTER_DIGEST,
        "source_sha256": None,
        "base": {
            "provider_model_name": "gemma-3-12b-it-Q4_K_M.gguf",
            "artifact_digest": None,
            "identity_confidence": "name_only",
        },
        "declared_capabilities": [],
        "data_classification": "confidential",
        "format": "gguf",
        "created_at": _MANIFEST_CREATED_AT.isoformat(),
        "notes": None,
    } | overrides


class TestAdapterManifest:
    """ADR-0061 rule 1's field list, and ADR-0065 rule 1's required-classification rule."""

    def test_a_name_only_manifest_round_trips(self) -> None:
        manifest = AdapterManifestOut.model_validate(_manifest())
        assert AdapterManifestOut.model_validate(json.loads(canonical_dumps(manifest))) == manifest
        assert manifest.base.identity_confidence.value == "name_only"

    def test_a_digest_verified_base_round_trips(self) -> None:
        digest = "sha256:" + "a1" * 32
        manifest = AdapterManifestOut.model_validate(
            _manifest(
                base={
                    "provider_model_name": "gemma-3-12b-it-Q4_K_M.gguf",
                    "artifact_digest": digest,
                    "identity_confidence": "digest",
                }
            )
        )
        assert manifest.base.artifact_digest == digest

    def test_data_classification_is_required_with_no_default(self) -> None:
        """ADR-0065 rule 1: an omitted classification is invalid, never a silent default."""
        document = _manifest()
        del document["data_classification"]
        with pytest.raises(PydanticValidationError, match="data_classification"):
            AdapterManifestOut.model_validate(document)

    def test_a_malformed_base_digest_is_rejected(self) -> None:
        with pytest.raises(PydanticValidationError, match="artifact_digest"):
            AdapterManifestOut.model_validate(
                _manifest(
                    base={
                        "provider_model_name": "gemma-3-12b-it-Q4_K_M.gguf",
                        "artifact_digest": "not-a-digest",
                        "identity_confidence": "digest",
                    }
                )
            )

    def test_base_confidence_must_match_digest_presence(self) -> None:
        with pytest.raises(PydanticValidationError, match="identity_confidence"):
            AdapterManifestOut.model_validate(
                _manifest(
                    base={
                        "provider_model_name": "gemma-3-12b-it-Q4_K_M.gguf",
                        "artifact_digest": None,
                        "identity_confidence": "digest",
                    }
                )
            )

    def test_a_malformed_name_is_refused_via_adapter_identity(self) -> None:
        """Reuses baseaicore.AdapterIdentity's own validation rather than a second one."""
        with pytest.raises(PydanticValidationError):
            AdapterManifestOut.model_validate(_manifest(name="Not-Valid"))

    def test_a_bare_reserved_capability_root_is_refused(self) -> None:
        with pytest.raises(PydanticValidationError, match="reserved"):
            AdapterManifestOut.model_validate(_manifest(declared_capabilities=["user"]))

    def test_an_unknown_capability_root_is_refused(self) -> None:
        with pytest.raises(PydanticValidationError):
            AdapterManifestOut.model_validate(
                _manifest(declared_capabilities=["not_a_real_capability"])
            )

    def test_a_known_specialization_is_accepted(self) -> None:
        manifest = AdapterManifestOut.model_validate(
            _manifest(declared_capabilities=["user.house_voice", "creative_writing"])
        )
        assert "user.house_voice" in manifest.declared_capabilities

    def test_format_defaults_to_gguf(self) -> None:
        document = _manifest()
        del document["format"]
        manifest = AdapterManifestOut.model_validate(document)
        assert manifest.format == "gguf"

    def test_in_preserves_an_unknown_field(self) -> None:
        manifest = AdapterManifestIn.model_validate(_manifest(future_field="x"))
        assert manifest.extras == {"future_field": "x"}

    def test_out_refuses_an_unknown_field(self) -> None:
        with pytest.raises(PydanticValidationError):
            AdapterManifestOut.model_validate(_manifest(future_field="x"))
