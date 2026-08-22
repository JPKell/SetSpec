# SetSpec — Development Plan

**Sequence position:** second component. Depends on BaseAiCore Phase 4.
**Target:** `setspec 0.3.0` by the end of Phase 4; `0.4.0` adds `setspec.prompts` during LoadCoach P4
([ADR-0028](../../adr/0028-prompt-pack-granularity.md)).

Note on ordering: SetSpec's *benchmark* payloads cannot be finalized before FreeWeight knows what a
result contains. This plan therefore ships the envelope and negotiation machinery first (Phase 1),
provides provisional benchmark payloads for FreeWeight to build against (Phase 2), and freezes them
only after FreeWeight has produced real results (Phase 4). That ordering is deliberate: a contract
frozen before its producer exists is a guess.

---

## Phase 1 — Envelope, versioning and serialization core

**Goal:** any payload can be wrapped, versioned, validated, serialized canonically and rejected
correctly when its major version is unsupported — demonstrated with a trivial payload type.

**Prerequisites:** `baseaicore>=0.4,<0.5`.

**Work**
* Repository skeleton (as per [Packaging Standards](../../standards/packaging-and-release-standards.md)).
* `envelope.py`: `SchemaEnvelope`, `GeneratorInfo`, `SchemaVersion`, `SUPPORTED_SCHEMAS`,
  `load_envelope`, `dump_envelope`, `SchemaVersionUnsupported`.
* `serialization.py`: canonical JSON dump, `Unsupported` codec, RFC 3339 codec, depth/size guards.
* `base.py`: the shared pydantic base classes — `StrictPayload` (`extra="forbid"`, for outbound) and
  `PreservingPayload` (`extra="allow"`, for inbound), plus the generator that produces an `Out` and an
  `In` class from one payload definition. The round-trip contract is asserted **per class**: an `In`
  model preserves unknown keys through load → dump, an `Out` model rejects them
  ([ADR-0009 rule 4](../../adr/0009-setspec-schema-strategy.md)).
* `MetricValue` model (value | `"unsupported"`, unit, aggregation, `higher_is_better`, sample count,
  dispersion).

**Files/subsystems**
```text
src/setspec/{__init__,__about__,envelope,serialization,base,metrics,errors}.py
tests/unit/{test_envelope,test_serialization,test_metrics}.py
tests/contract/test_version_negotiation.py
```

**Tests**
* Load/dump round-trip; canonical output byte-identical across repeats and across the CI matrix.
* Unknown minor accepted with unknown fields preserved through a re-dump.
* Unknown major rejected; the error names expected, received and supported versions.
* `UNSUPPORTED` ↔ `"unsupported"`; `null` never produced for a measurement.
* Naive datetime rejected; RFC 3339 millisecond precision enforced.
* Depth guard rejects a payload nested beyond the limit; size guard reports the limit.

**Acceptance criteria**
1. A payload can be dumped and re-loaded with identical bytes.
2. A v1.0 reader reads a v1.1 payload without loss and rejects v2.0 with a clear error.
3. `mypy --strict`, `ruff`, `lint-imports` clean; coverage ≥ 95 %.

**Known risks:** pydantic's `extra="allow"` interacting badly with round-trip fidelity — pinned down
by an explicit test before anything else is built on it.
**Likely failure modes:** float formatting differences; timezone handling; silently dropped unknown
fields.
**Gold standards:** deterministic serialization; version rules proven by tests in both directions.
**Deferred:** every real payload type.

---

## Phase 2 — Provisional benchmark and evidence payloads (v0 → v1.0-draft)

**Goal:** FreeWeight has concrete models to build against, explicitly marked draft.

**Prerequisites:** Phase 1.

**Work**
* `benchmark/v1.py`: `BenchmarkResult`, `BenchmarkRunSummary`, provenance sub-models
  (model identity, runtime profile, machine, suite, dataset hashes, prompt pack, effective
  parameters, reproducibility fingerprint).
* `capability/v1.py`: `CapabilityEvidence` with the full normative field set from
  [ADR-0022 §1](../../adr/0022-capability-evidence-record-contract.md) — including `measured_at`
  **and** `computed_at` as distinct fields, `vocabulary_version`, `dataset_hashes` and
  `prompt_subset_hashes` — and `EvidenceBundle` with its `complete` flag.
* `machine/v1.py`: `MachineProfilePayload`; `model/v1.py`: `ModelIdentityPayload`.
* `vocabulary.py`: `CAPABILITIES`, `CAPABILITY_VOCABULARY_VERSION`, validation helpers.
* Mark these versions `1.0-draft` in `SUPPORTED_SCHEMAS`, and document that draft versions may change
  until Phase 4.

**Files/subsystems**
```text
src/setspec/{benchmark/v1.py,capability/v1.py,machine/v1.py,model/v1.py,vocabulary.py}
tests/unit/test_payloads_benchmark.py  tests/unit/test_payloads_capability.py
tests/unit/test_vocabulary.py
```

**Tests**
* Round-trip for every model with all-optional and all-populated variants.
* Provenance completeness: a result missing any required provenance field is rejected, with the field
  named ([Machine Identity §6](../../architecture/machine-identity-and-reproducibility.md)).
* Score/confidence range validation; negative sample counts rejected.
* A `CapabilityEvidence` missing `measured_at`, `policy_version` or `vocabulary_version` is rejected
  with the field named; `measured_at` later than `computed_at` is rejected as incoherent.
* Capability vocabulary: known IDs accepted, unknown rejected in strict mode, specializations
  validated against their roots.

**Acceptance criteria**
1. A realistic benchmark result (from FreeWeight's fixture set) validates.
2. A result missing its machine fingerprint or suite version is rejected with a useful message.
3. Draft status is visible in the API and the README.

**Known risks:** guessing the result shape. Mitigated by building it from the fields the FreeWeight
spec already enumerates and by the draft marking.
**Likely failure modes:** over-constrained models that reject legitimate benchmark output; under-
constrained models that accept results with missing provenance.
**Gold standards:** provenance completeness enforced by the schema, not by convention.
**Deferred:** freezing, JSON Schema publication, goldens.

---

## Phase 3 — Event and error envelopes

**Goal:** all three applications emit identical event and error shapes over SSE and HTTP.

**Prerequisites:** Phase 1.

**Work**
* `event/v1.py`: the event **payload** (`event_id`, `sequence`, `type`, `entity`, `timestamp`,
  `message`, `progress`, `data`), carried inside the standard envelope whose `generator` identifies
  the producing application — so the payload has no separate `source` field
  ([ADR-0025 §3](../../adr/0025-envelope-boundaries.md)). Event-type naming enforced by validation.
* `error/v1.py`: `ErrorEnvelope` (`code`, `message`, `details`, `request_id`, `timestamp`) — the
  object inside `{"error": {…}}`, transported **unwrapped**; a test asserts it is never emitted inside
  a SetSpec envelope.
* Helper constructors used by MirrorWall and by every application.

**Files/subsystems**
```text
src/setspec/{event/v1.py,error/v1.py}
tests/unit/{test_events,test_errors}.py
```

**Tests**
* Event type must match `noun.verb` in past tense (pattern-validated); invalid names rejected.
* Progress consistency (`completed <= total`); sequence ≥ 1.
* Error envelope: `code` is `SCREAMING_SNAKE_CASE`; `details` never contains a secret-shaped key
  (asserted by a redaction test).
* Serialization matches the examples in
  [API Standards §4 and §8](../../standards/api-and-contract-standards.md) exactly.

**Acceptance criteria**
1. The documented example payloads in [API Standards §4 and §8](../../standards/api-and-contract-standards.md)
   and [Observability §4.1](../../standards/observability-standards.md) validate against these models
   verbatim — the check that keeps the three documents from drifting into three wire formats again.
2. A secret-shaped key in `details` fails the test suite.

**Known risks:** event vocabulary drift between applications — mitigated by registering event types
per application and testing the registry.
**Likely failure modes:** applications inventing ad-hoc event shapes; error bodies leaking internals.
**Gold standards:** one envelope, three applications, zero variants.
**Deferred:** per-application event type registries (owned by the applications).

---

## Phase 4 — Freeze v1.0, publish schemas and goldens

**Goal:** the contracts are stable, machine-readable and testable from other repositories.

**Prerequisites:** Phases 1–3, **and** FreeWeight has produced real benchmark results against the
draft models (FreeWeight P6).

**Work**
* Incorporate every correction FreeWeight's real output demands; promote `1.0-draft` → `1.0`.
* Generate JSON Schema for every payload version into `src/setspec/schemas/<schema>/<version>.json`.
* Author ≥ 3 golden payloads per version into `src/setspec/goldens/<schema>/<version>/*.json`,
  including a minimal example, a fully populated example and an `unsupported`-heavy example.
* `json_schema_for()` / `golden_payloads()` accessors.
* CI: schema snapshot diff; golden validation; cross-version compatibility job.
* Publish `setspec 0.3.0`.

**Files/subsystems**
```text
src/setspec/{schemas/**,goldens/**,artifacts.py}
tests/contract/{test_schema_snapshots,test_goldens,test_cross_version}.py
docs/schemas.md            # human-readable catalogue of every payload and version
```

**Tests**
* Every golden validates against its model and its JSON Schema.
* Generated schema matches the committed snapshot (diff fails the build).
* A v1.0 reader accepts a synthetic v1.1 golden and rejects a synthetic v2.0 golden.
* Package data is present in the built wheel and loadable via `importlib.resources`.

**Acceptance criteria**
1. LoadCoach's contract tests (written later) can consume the published goldens without importing
   FreeWeight.
2. A schema change without a version bump fails CI — proven by a deliberate test-only mutation.
3. Every §20 criterion in the [spec](spec.md) is met.

**Known risks:** freezing too early. Mitigated by requiring FreeWeight P6 as a prerequisite.
**Likely failure modes:** package data missing from the wheel (covered by the install-check job);
goldens that drift from the models.
**Gold standards:** contracts consumable from another repository with no shared code; deterministic
serialization; documented and enforced version rules.
**Deferred:** `routing.decision` export payload; compression; generated non-Python types.
**Not created:** `production.feedback` — `POST /jobs/{id}/feedback` is an ordinary body of LoadCoach's
own `/api/v1`, versioned by its path and contracted through the committed OpenAPI snapshot
([ADR-0025 §5](../../adr/0025-envelope-boundaries.md)). Recorded as a deliberate rejection.

---

## Phase 5 — `setspec.prompts` (during LoadCoach P4)

**Goal:** one implementation of the prompt record schema, loader, renderer and hashing, because those
hashes appear in cross-application evidence.

**Prerequisites:** FreeWeight P6–P7 shipping a working in-application prompt module; LoadCoach P4
needing the same.

**Work**
* Move (not copy) FreeWeight's prompt module, generalizing as it goes: `PromptRecord`,
  `PromptManifest`, `PromptLibrary.get/render`, `prompt_subset_hash`, `StrictUndefined` rendering,
  variable type and range validation.
* `prompt.record` and `prompt.manifest` schemas, JSON Schema and goldens like every other payload.
* Publish `setspec 0.4.0`; write the adoption checklist FreeWeight P12 follows.

**Tests**
* Same record ⇒ same `sha256` across platforms, Python versions and `setspec` versions in the matrix.
* `prompt_subset_hash` changes for a subset member and not for a non-member.
* Rendering determinism; `StrictUndefined` raises on a missing variable; an unknown supplied variable
  is an error.
* FreeWeight's existing pack hashes identically before and after the move (golden).

**Acceptance criteria**
1. LoadCoach and IdeaPress use it from their first prompt; neither writes a loader.
2. FreeWeight P12 adopts it with no hash change.

**Known risks:** Jinja2 entering SetSpec's dependency set. Accepted in
[ADR-0028](../../adr/0028-prompt-pack-granularity.md); the alternative was three implementations of a
determinism contract.
