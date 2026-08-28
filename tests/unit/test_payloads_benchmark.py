"""Tests for ``benchmark.result`` and ``benchmark.run_summary`` (:mod:`setspec.benchmark.v1`).

The realistic fixture in :func:`_result` is built from FreeWeight's own ``native.tool_use``
manifest example (benchmark catalog §5), so acceptance criterion 1 — "a realistic benchmark result
validates" — is checked against FreeWeight's documented shape, not an invented one.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from baseaicore import RuntimeProfile
from pydantic import ValidationError as PydanticValidationError

from setspec import canonical_dumps
from setspec.benchmark.v1 import (
    BenchmarkResultIn,
    BenchmarkResultOut,
    BenchmarkRunSummaryOut,
    RuntimeProfileFields,
)

_STARTED_AT = datetime(2026, 8, 22, 9, 14, 0, tzinfo=UTC)
_COMPLETED_AT = datetime(2026, 8, 22, 9, 14, 12, tzinfo=UTC)
_RUNTIME_PROFILE_HASH = RuntimeProfile(
    context_size=8192, gpu_layers=99, flash_attention=True
).profile_hash


def _runtime_profile() -> dict[str, Any]:
    """A fresh runtime-profile dict per call.

    Every fixture builder below embeds this by value, not by reference: a prior version shared
    one module-level dict across every call, and a test that mutated its own copy
    (``test_a_runtime_profile_change_without_a_hash_update_is_caught``) was actually mutating the
    shared fixture in place, corrupting every test built after it in file execution order. It
    passed under 3.13 by luck of pytest-randomly's seed and failed the moment 3.14's ordering
    changed, but the bug was aliasing, not a Python-version difference.
    """
    return {"context_size": 8192, "gpu_layers": 99, "flash_attention": True}


def _model_identity() -> dict[str, Any]:
    return {
        "provider_kind": "ollama",
        "provider_model_name": "qwen3.5:9b-q8_0",
        "artifact_digest": None,
        "identity_confidence": "name_only",
        "canonical_id": "ollama/qwen3.5:9b-q8_0@unknown",
        "observed_at": _STARTED_AT.isoformat(),
    }


def _result(**overrides: Any) -> dict[str, Any]:
    """A realistic ``native.tool_use`` result, built from FreeWeight's own manifest example."""
    document: dict[str, Any] = {
        "model": _model_identity(),
        "runtime_profile": _runtime_profile(),
        "runtime_profile_hash": _RUNTIME_PROFILE_HASH,
        "machine_fingerprint": "a" * 64,
        "suite": {
            "suite_key": "native.tool_use",
            "suite_version": "1.0.0",
            "category": "tool_use",
            "runner": "native",
            "manifest_hash": "sha256:deadbeef",
            "dataset_hashes": {"fixtures": "sha256:cafef00d"},
            "prompt_subset_hash": "sha256:abc123",
            "prompts_used": [
                {
                    "prompt_id": "benchmarks.tool_use.system",
                    "version": "1.0.0",
                    "sha256": "9f2c",
                }
            ],
        },
        "execution": {
            "effective_parameters": {"temperature": 0.0},
            "repetitions": 3,
            "sample_count": 40,
            "seed": 42,
            "served_context": 8192,
            "served_context_source": "configured",
            "gpu_index": 0,
            "multi_gpu_visible": False,
        },
        "environment": {"provider_kind": "ollama", "provider_version": "0.32.13"},
        "application": {"name": "freeweight", "version": "1.2.0", "git_commit": "abcdef1"},
        "reproducibility": {
            "reproducibility_fingerprint": "sha256:reproducible",
            "fingerprint_document": {"model": "…"},
        },
        "started_at": _STARTED_AT.isoformat(),
        "completed_at": _COMPLETED_AT.isoformat(),
        "status": "completed",
        "metrics": [
            {
                "metric_key": "task_success",
                "value": 0.92,
                "unit": "ratio",
                "aggregation": "mean",
                "higher_is_better": True,
                "sample_count": 40,
                "dispersion": 0.05,
            },
            {
                "metric_key": "tool_selection_accuracy",
                "value": 0.88,
                "unit": "ratio",
                "aggregation": "mean",
                "higher_is_better": True,
                "sample_count": 40,
                "dispersion": 0.03,
            },
        ],
        "samples_ref": "run_test_01J9K2M",
    }
    document.update(overrides)
    return document


class TestBenchmarkResult:
    """Machine Identity §6's minimum provenance set, built from a real FreeWeight manifest."""

    def test_a_realistic_tool_use_result_validates(self) -> None:
        """Acceptance criterion 1: a realistic result from FreeWeight's own fixture set."""
        result = BenchmarkResultOut.model_validate(_result())
        assert result.suite.suite_key == "native.tool_use"
        assert len(result.metrics) == 2

    def test_round_trips_through_canonical_json(self) -> None:
        result = BenchmarkResultOut.model_validate(_result())
        assert BenchmarkResultOut.model_validate(json.loads(canonical_dumps(result))) == result

    def test_missing_machine_fingerprint_is_rejected_and_named(self) -> None:
        """Acceptance criterion 2, for the fingerprint half of the pair."""
        document = _result()
        del document["machine_fingerprint"]
        with pytest.raises(PydanticValidationError, match="machine_fingerprint"):
            BenchmarkResultOut.model_validate(document)

    def test_missing_suite_version_is_rejected_and_named(self) -> None:
        """Acceptance criterion 2, for the suite-version half of the pair."""
        document = _result()
        del document["suite"]["suite_version"]
        with pytest.raises(PydanticValidationError, match="suite_version"):
            BenchmarkResultOut.model_validate(document)

    @pytest.mark.parametrize(
        "field",
        [
            "model",
            "runtime_profile_hash",
            "suite",
            "execution",
            "environment",
            "application",
            "reproducibility",
            "started_at",
            "completed_at",
            "status",
        ],
    )
    def test_every_provenance_field_is_required(self, field: str) -> None:
        document = _result()
        del document[field]
        with pytest.raises(PydanticValidationError, match=field):
            BenchmarkResultOut.model_validate(document)

    def test_runtime_profile_hash_must_match_the_embedded_profile(self) -> None:
        with pytest.raises(PydanticValidationError, match="runtime_profile_hash"):
            BenchmarkResultOut.model_validate(_result(runtime_profile_hash="not-the-real-hash"))

    def test_a_runtime_profile_change_without_a_hash_update_is_caught(self) -> None:
        """The check is a real cross-field validation, not merely a non-empty-string check."""
        document = _result()
        document["runtime_profile"]["context_size"] = 4096  # hash now stale
        with pytest.raises(PydanticValidationError, match="runtime_profile_hash"):
            BenchmarkResultOut.model_validate(document)

    def test_completed_before_started_is_rejected(self) -> None:
        with pytest.raises(PydanticValidationError, match="completed_at"):
            BenchmarkResultOut.model_validate(
                _result(started_at=_COMPLETED_AT.isoformat(), completed_at=_STARTED_AT.isoformat())
            )

    def test_a_skipped_result_must_name_its_skip_reason(self) -> None:
        with pytest.raises(PydanticValidationError, match="skip_reason"):
            BenchmarkResultOut.model_validate(_result(status="skipped", metrics=[]))

    def test_a_skipped_result_with_a_reason_is_valid_with_no_metrics(self) -> None:
        result = BenchmarkResultOut.model_validate(
            _result(status="skipped", skip_reason="insufficient_vram", metrics=[])
        )
        assert result.metrics == ()

    def test_skip_reason_on_a_completed_result_is_rejected(self) -> None:
        with pytest.raises(PydanticValidationError, match="skip_reason"):
            BenchmarkResultOut.model_validate(_result(skip_reason="insufficient_vram"))

    def test_a_completed_result_with_no_metrics_is_rejected(self) -> None:
        with pytest.raises(PydanticValidationError, match="metrics"):
            BenchmarkResultOut.model_validate(_result(metrics=[]))

    def test_a_failed_result_may_have_partial_metrics(self) -> None:
        """A failure partway through may still have measured something before it failed."""
        result = BenchmarkResultOut.model_validate(_result(status="failed", metrics=[]))
        assert result.status.value == "failed"

    def test_seed_accepts_the_nondeterministic_sentinel(self) -> None:
        document = _result()
        document["execution"]["seed"] = "nondeterministic"
        result = BenchmarkResultOut.model_validate(document)
        assert result.execution.seed == "nondeterministic"

    def test_seed_rejects_any_other_string(self) -> None:
        document = _result()
        document["execution"]["seed"] = "random-ish"
        with pytest.raises(PydanticValidationError, match="seed"):
            BenchmarkResultOut.model_validate(document)

    def test_machine_profile_snapshot_is_optional(self) -> None:
        result = BenchmarkResultOut.model_validate(_result())
        assert result.machine_profile is None

    def test_a_machine_profile_snapshot_may_be_embedded(self) -> None:
        document = _result()
        document["machine_profile"] = {
            "machine_fingerprint": "a" * 64,
            "hostname": "bench-01",
            "os_name": "Linux",
            "os_version": None,
            "kernel": None,
            "architecture": "x86_64",
            "cpu_model": "AMD Ryzen 9",
        }
        result = BenchmarkResultOut.model_validate(document)
        assert result.machine_profile is not None
        assert result.machine_profile.hostname == "bench-01"

    def test_in_preserves_an_unknown_field(self) -> None:
        result = BenchmarkResultIn.model_validate(_result(future_field="x"))
        assert result.extras == {"future_field": "x"}

    def test_in_preserves_an_unknown_field_on_a_nested_metric(self) -> None:
        document = _result()
        document["metrics"][0]["confidence_interval"] = [0.85, 0.95]
        result = BenchmarkResultIn.model_validate(document)
        assert result.metrics[0].extras == {"confidence_interval": [0.85, 0.95]}


def _run_summary(**overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "model": _model_identity(),
        "runtime_profile": _runtime_profile(),
        "runtime_profile_hash": _RUNTIME_PROFILE_HASH,
        "machine_fingerprint": "a" * 64,
        "suite": {
            "suite_key": "native.tool_use",
            "suite_version": "1.0.0",
            "manifest_hash": "sha256:deadbeef",
            "prompt_subset_hash": "sha256:abc123",
        },
        "environment": {"provider_kind": "ollama", "provider_version": "0.32.13"},
        "application": {"name": "freeweight", "version": "1.2.0", "git_commit": "abcdef1"},
        "reproducibility": {
            "reproducibility_fingerprint": "sha256:reproducible",
            "fingerprint_document": {},
        },
        "status": "completed",
        "created_at": (_STARTED_AT - timedelta(seconds=5)).isoformat(),
        "started_at": _STARTED_AT.isoformat(),
        "completed_at": _COMPLETED_AT.isoformat(),
        "aggregate_metrics": [],
    }
    document.update(overrides)
    return document


class TestBenchmarkRunSummary:
    """spec §7: one run — subject, suite, status, timings, aggregate metrics."""

    def test_a_completed_run_summary_validates(self) -> None:
        summary = BenchmarkRunSummaryOut.model_validate(_run_summary())
        assert summary.status.value == "completed"

    def test_round_trips_through_canonical_json(self) -> None:
        summary = BenchmarkRunSummaryOut.model_validate(_run_summary())
        assert BenchmarkRunSummaryOut.model_validate(json.loads(canonical_dumps(summary))) == (
            summary
        )

    def test_a_queued_run_has_no_started_or_completed_time(self) -> None:
        summary = BenchmarkRunSummaryOut.model_validate(
            _run_summary(status="queued", started_at=None, completed_at=None)
        )
        assert summary.started_at is None
        assert summary.completed_at is None

    def test_an_interrupted_run_is_a_distinct_status_from_failed(self) -> None:
        """An interrupted run is resumable; the data model reserves a separate state for it."""
        summary = BenchmarkRunSummaryOut.model_validate(
            _run_summary(status="interrupted", completed_at=None)
        )
        assert summary.status.value == "interrupted"

    def test_completed_before_started_is_rejected(self) -> None:
        with pytest.raises(PydanticValidationError):
            BenchmarkRunSummaryOut.model_validate(
                _run_summary(
                    started_at=_COMPLETED_AT.isoformat(), completed_at=_STARTED_AT.isoformat()
                )
            )

    def test_runtime_profile_hash_must_match_the_embedded_profile(self) -> None:
        with pytest.raises(PydanticValidationError, match="runtime_profile_hash"):
            BenchmarkRunSummaryOut.model_validate(
                _run_summary(runtime_profile_hash="not-the-real-hash")
            )

    def test_aggregate_metrics_round_trip(self) -> None:
        summary = BenchmarkRunSummaryOut.model_validate(
            _run_summary(
                aggregate_metrics=[
                    {
                        "metric_key": "task_success",
                        "value": 0.9,
                        "unit": "ratio",
                        "aggregation": "mean",
                        "higher_is_better": True,
                        "sample_count": 80,
                        "dispersion": "unsupported",
                    }
                ]
            )
        )
        assert len(summary.aggregate_metrics) == 1

    def test_an_error_code_may_accompany_a_failed_run(self) -> None:
        summary = BenchmarkRunSummaryOut.model_validate(
            _run_summary(
                status="failed",
                completed_at=_COMPLETED_AT.isoformat(),
                error_code="PROVIDER_UNAVAILABLE",
                error_text="connection refused",
            )
        )
        assert summary.error_code == "PROVIDER_UNAVAILABLE"


class TestRecommendedProvenance:
    """Machine Identity §6's "optional but strongly recommended" set, plus the run_tests errors.

    The writer half forbids unknown keys, so an optional field this schema does not declare is one
    a producer can never send. These tests pin down that each is actually reachable — the gap they
    close was silent, because a model with the field missing passes every test that never tries to
    set it.
    """

    def test_a_cold_warm_marker_is_emittable(self) -> None:
        result = BenchmarkResultOut.model_validate(_result(measurement_class="cold"))
        assert result.measurement_class is not None
        assert result.measurement_class.value == "cold"

    @pytest.mark.parametrize("value", ["cold", "warm", "cache_reused", "n/a"])
    def test_every_measurement_class_is_accepted(self, value: str) -> None:
        result = BenchmarkResultOut.model_validate(_result(measurement_class=value))
        assert result.measurement_class is not None

    def test_an_unknown_measurement_class_is_rejected(self) -> None:
        with pytest.raises(PydanticValidationError):
            BenchmarkResultOut.model_validate(_result(measurement_class="lukewarm"))

    def test_a_telemetry_summary_is_emittable(self) -> None:
        result = BenchmarkResultOut.model_validate(
            _result(
                telemetry_summary={
                    "peak_vram_bytes": 15_000_000_000,
                    "peak_power_watts": 178.5,
                    "mean_power_watts": 141.2,
                    "max_temperature_c": 71,
                    "throttled": False,
                }
            )
        )
        assert result.telemetry_summary is not None
        assert result.telemetry_summary.peak_vram_bytes == 15_000_000_000

    def test_telemetry_figures_default_to_unsupported_not_zero(self) -> None:
        """A sensor that could not be read is not a reading of zero watts (ADR-0016)."""
        result = BenchmarkResultOut.model_validate(_result(telemetry_summary={}))
        assert result.telemetry_summary is not None
        dumped = result.model_dump()["telemetry_summary"]
        assert dumped["peak_power_watts"] == "unsupported"
        assert dumped["max_temperature_c"] == "unsupported"

    def test_an_unreadable_throttle_flag_is_none_not_false(self) -> None:
        """`None` and `False` are different claims; guessing False blames the model, not the GPU."""
        result = BenchmarkResultOut.model_validate(_result(telemetry_summary={}))
        assert result.telemetry_summary is not None
        assert result.telemetry_summary.throttled is None

    def test_a_raw_response_reference_is_emittable(self) -> None:
        result = BenchmarkResultOut.model_validate(_result(raw_response_ref="artifact_01J9K2M"))
        assert result.raw_response_ref == "artifact_01J9K2M"

    def test_a_failed_result_can_say_why(self) -> None:
        result = BenchmarkResultOut.model_validate(
            _result(
                status="failed",
                metrics=[],
                error_code="PROVIDER_TIMEOUT",
                error_text="no response after 30s",
            )
        )
        assert result.error_code == "PROVIDER_TIMEOUT"

    def test_case_counts_are_emittable(self) -> None:
        result = BenchmarkResultOut.model_validate(_result(completed_cases=8, total_cases=10))
        assert (result.completed_cases, result.total_cases) == (8, 10)

    def test_completing_more_cases_than_were_run_is_rejected(self) -> None:
        with pytest.raises(PydanticValidationError, match="completed_cases"):
            BenchmarkResultOut.model_validate(_result(completed_cases=11, total_cases=10))

    def test_equal_case_counts_are_valid(self) -> None:
        result = BenchmarkResultOut.model_validate(_result(completed_cases=10, total_cases=10))
        assert result.completed_cases == 10

    def test_a_negative_case_count_is_rejected(self) -> None:
        with pytest.raises(PydanticValidationError):
            BenchmarkResultOut.model_validate(_result(completed_cases=-1))

    def test_one_case_count_alone_is_allowed(self) -> None:
        """The pair is only cross-checked when both are present; neither implies the other."""
        assert BenchmarkResultOut.model_validate(_result(total_cases=10)).completed_cases is None

    def test_all_recommended_fields_default_to_absent(self) -> None:
        """They are optional: a benchmark whose numbers do not depend on them omits them."""
        result = BenchmarkResultOut.model_validate(_result())
        assert result.measurement_class is None
        assert result.telemetry_summary is None
        assert result.raw_response_ref is None
        assert result.error_code is None

    def test_a_fully_populated_result_round_trips(self) -> None:
        """The dev plan asks for an all-populated variant, not only the minimal one."""
        result = BenchmarkResultOut.model_validate(
            _result(
                measurement_class="warm",
                telemetry_summary={
                    "peak_vram_bytes": 15_000_000_000,
                    "peak_power_watts": 178.5,
                    "mean_power_watts": 141.2,
                    "max_temperature_c": 71,
                    "throttled": True,
                },
                raw_response_ref="artifact_01J9K2M",
                completed_cases=10,
                total_cases=10,
            )
        )
        assert BenchmarkResultOut.model_validate(json.loads(canonical_dumps(result))) == result


class TestRuntimeProfileHashProperty:
    """The hash is delegated to the domain type, never reimplemented here."""

    def test_it_matches_the_domain_types_own_hash(self) -> None:
        fields = RuntimeProfileFields.model_validate(_runtime_profile())
        assert fields.profile_hash == _RUNTIME_PROFILE_HASH

    def test_an_all_default_profile_still_hashes(self) -> None:
        """ "Provider defaults" is a legal, hashable profile, not a "no profile" state."""
        assert len(RuntimeProfileFields().profile_hash) == 16

    def test_a_changed_field_changes_the_hash(self) -> None:
        baseline = RuntimeProfileFields(context_size=8192)
        assert baseline.profile_hash != RuntimeProfileFields(context_size=4096).profile_hash
