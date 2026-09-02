# SetSpec

Every versioned data contract that crosses an application boundary: benchmark results, capability evidence, event/error envelopes, prompt records.

**Status:** `0.5.0` — Phases 1–2, 3A, 4, 5 and 6 complete, and **the v1.0 contracts are frozen**,
with the first additive minor now published on top of that freeze. Eight payload types remain
frozen at `1.0` — `model.identity`, `machine.profile`, `benchmark.result`,
`benchmark.run_summary`, `benchmark.evidence_bundle`,
`benchmark.goal_pack` and `benchmark.calibration_report`, plus `capability.evidence` itself — each
with generated JSON Schema and at least three golden payloads shipped as package data.
`setspec.DRAFT_SCHEMAS` is empty, which is where the freeze is readable at runtime rather than only
stated here; from now on a new optional field is a minor bump and anything else is a major,
enforced by a snapshot diff in CI.

Phase 6 (the adapter arc's LA0 checkpoint) adds three things without touching any of the above:
`capability.evidence` gains an additive `1.1` (an optional `adapter` field, absent — and
byte-identical to `1.0` — on every record with no adapter); `model.adapter_manifest` `1.0`
publishes the operator-reviewed record behind one adapter; and `governance.egress_decision` `1.0`
is the package's first payload under a root other than `benchmark`/`capability`/`machine`/`model`,
carrying a recorded egress verdict for a reader that has SpotCheck installed or not.

The [schema catalogue](docs/schemas.md) lists every payload type, its artifacts, and the
cross-field rules the JSON Schema cannot express. Event and error envelopes (Phase 3) are not yet
written and are therefore not part of the freeze. Prompt records (`setspec.prompts`, Phase 5,
added in 0.4.0) are shipped: prompt packs with their three content hashes and sandboxed
rendering; they carry their own record schema version rather than joining the frozen payload types.
See the [development plan](docs/packages/setspec/development-plan.md) for what each phase adds.

Part of the **Local AI Suite**.

## Install

```bash
pip install setspec
```

## Quickstart

Write a document, then read it back:

```python
from setspec import GeneratorInfo, SchemaVersion, dump_envelope, load_envelope

generator = GeneratorInfo(name="freeweight", version="1.0.0")
document = dump_envelope(
    {"tokens_per_second": 42.0},
    schema="benchmark.result",
    version=SchemaVersion(1, 0),
    generator=generator,
)

envelope = load_envelope(document, expect="benchmark.result", supported=[SchemaVersion(1, 0)])
assert envelope.payload == {"tokens_per_second": 42.0}
```

`dump_envelope` returns canonical JSON: byte-identical for equal input, on every platform and
Python version, so a document can be hashed and diffed as well as read.

Payload types come in two halves generated from one definition — a strict `Out` for writers and a
preserving `In` for readers (ADR-0009 rule 4):

```python
from setspec import PayloadDefinition, payload_models
from setspec.serialization import MeasurementField


class ResultFields(PayloadDefinition):
    reading: MeasurementField
    unit: str


ResultOut, ResultIn = payload_models(ResultFields)

# A reader keeps what a newer writer added, so a re-export loses nothing.
received = ResultIn.model_validate({"reading": 1.5, "unit": "ms", "confidence": 0.87})
assert received.extras == {"confidence": 0.87}
```

A measurement this environment cannot provide is `UNSUPPORTED`, which serializes as the string
`"unsupported"` — never `null`, never `0`
(ADR-0016).

Phase 2's payload types live in their own versioned modules, not the top-level package, so that a
future `benchmark.result 2.0` can coexist with `v1` rather than racing it for one name
(ADR-0009 rule 6):

```python
from setspec.capability.v1 import CapabilityEvidenceOut

evidence = CapabilityEvidenceOut.model_validate(
    {
        "model": {
            "provider_kind": "ollama",
            "provider_model_name": "qwen3.5:9b-q8_0",
            "artifact_digest": None,
            "identity_confidence": "name_only",
            "canonical_id": "ollama/qwen3.5:9b-q8_0@unknown",
            "observed_at": "2026-08-20T09:00:00.000Z",
        },
        "runtime_profile_hash": "a" * 16,
        "machine_fingerprint": "b" * 64,
        "capability_id": "coding.python",  # unenumerated specialization of the known root "coding"
        "score": 0.82,
        "confidence": 0.71,
        "sample_count": 40,
        "excluded_count": 2,
        "dispersion": 0.09,
        "measured_at": "2026-08-20T00:00:00.000Z",
        "computed_at": "2026-08-22T00:00:00.000Z",
        "policy_version": "1.0",
        "vocabulary_version": "1.0",
        "environment": {"provider_kind": "ollama", "provider_version": "0.32.13"},
    }
)
assert evidence.capability_id == "coding.python"
```

See [docs/packages/setspec/spec.md](docs/packages/setspec/spec.md) §7 for the full public API and
§20 for the acceptance criteria.

## Documentation

Project documentation lives under [`docs/`](docs/README.md). Start with [`docs/README.md`](docs/README.md).

| Read this | For |
|---|---|
| [docs/packages/setspec/spec.md](docs/packages/setspec/spec.md) | Purpose, scope, non-goals, public contracts, configuration, acceptance criteria |
| [docs/packages/setspec/development-plan.md](docs/packages/setspec/development-plan.md) | The phased build plan: goals, work, tests, acceptance criteria per phase |

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install
pytest -m "not live and not performance"
```

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the full workflow and [`SECURITY.md`](SECURITY.md) for
how to report a vulnerability.

## License

Apache-2.0 — see [`LICENSE`](LICENSE).
