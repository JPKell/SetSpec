# Changelog

All notable changes to `setspec` are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows
[Semantic Versioning](https://semver.org/), pre-1.0 per
packaging and release standards §3.

## [Unreleased]

## [0.5.0] — 2026-09-02

### Added

- **`capability.evidence` `1.1`** (Phase 6, ADR-0058): an optional `adapter` field naming the
  adapter axis a measurement was taken under. Absent — and byte-for-byte identical to `1.0` — on
  every record measured on the bare base; a `@model_serializer` drops the field from the dump
  entirely when unset, rather than emitting `"adapter": null`, so a non-adapter record written
  through the new model is indistinguishable from what `0.4.0` writes (LA0 exit condition I15).
  Lives on a new sibling class, `CapabilityEvidenceV1_1Fields`
  (`CapabilityEvidenceV1_1Out`/`CapabilityEvidenceV1_1In`), rather than an edit to the existing
  `CapabilityEvidenceFields`/`CapabilityEvidenceOut`/`CapabilityEvidenceIn`, which keep meaning
  `1.0`: `benchmark.evidence_bundle` nests the `capability.evidence` shape by reference, so an
  edit in place would have silently moved that schema's own committed `1.0` snapshot too.
- **`model.adapter_manifest` `1.0`** (Phase 6, ADR-0061): the operator-reviewed record behind one
  adapter — `name`, `artifact_file`, `artifact_sha256`, optional `source_sha256`, `base` (a
  provider model name plus an optional artifact digest, at `digest`-or-`name_only` confidence),
  `declared_capabilities`, `data_classification`, `format`, `created_at`, `notes`. `name` and the
  two digest fields are validated by reconstructing a `baseaicore.AdapterIdentity`, reusing that
  type's own name-pattern and digest-normalization rules rather than a second implementation.
  **`data_classification` is required, with no schema default** (ADR-0065 rule 1): a manifest that
  omits it is invalid, never silently defaulted closed.
- **`governance.egress_decision` `1.0`** (Phase 6, ADR-0051 §4, ADR-0054): one recorded egress
  verdict — `decision_id`, an embedded request (`run_id`, `source_ref`, `data_classification`,
  `target{name, remote, max_data_classification, provider_kind}`), `verdict`
  (`approved`/`denied`/`violation`), `reason`, `policy_name`, `policy_version`, `decided_at`.
  SetSpec's first payload under a root other than `benchmark`/`capability`/`machine`/`model` —
  added because the shape has a named second reader (IdeaPress's S4 egress badge reads decisions
  PromptCadence exported, with SpotCheck not installed). `target.max_data_classification` is the
  only nullable field, deliberately: "remote with no declared ceiling" is the fail-closed case a
  policy must be able to deny and record. SpotCheck does not exist as code yet; nothing here
  imports it.
- JSON Schema and goldens for all three: `capability.evidence/1.1.json` (`minimal`, `full`,
  `unsupported`), `model.adapter_manifest/1.0.json` (`minimal`, `full`, `name_only`),
  `governance.egress_decision/1.0.json` (`minimal`, `full`, `denied_no_ceiling`, `violation`).
  The `capability.evidence/1.0` and `benchmark.evidence_bundle/1.0` schemas and goldens are
  byte-for-byte unchanged — asserted by a dedicated contract test (I15) rather than by inspection.

### Changed

- Five already-committed `1.0` JSON Schema snapshots (`model.identity`, `benchmark.result`,
  `benchmark.run_summary`, `capability.evidence`, `benchmark.evidence_bundle`) were regenerated to
  pick up two `baseaicore 0.4.1` enum docstring edits (`IdentityConfidence`,
  `ModelCapabilityFlag`) that this release's `baseaicore>=0.4,<0.5` upgrade surfaces in their
  nested `$defs` descriptions. **Structurally identical** — no property, type or required-field
  changed, confirmed by a description-stripped diff before committing; the regeneration is a
  byproduct of the dependency bump, not a payload change.
- Bumped to 0.5.0 for the `capability.evidence` `1.1` addition and the two new payload types
  (packaging standards §3: additive, non-breaking).

## [0.4.0] — 2026-08-29

### Added

- **`setspec.prompts`** (Phase 5): prompt records and prompt packs, moved from
  `freeweight.services.prompts` — `PromptRecord`, `PromptLibrary`, `load_record()`, `load_pack()`,
  `build_manifest()`/`write_manifest()`, and the pack's three hashes
  (`prompt_record_hash`/`prompt_subset_hash`/`pack_hash`, ADR-0028). Rendering runs through a
  sandboxed, loader-less Jinja2 `Environment` with `StrictUndefined` (prompt-management-standards
  §2.1): a referenced-but-unsupplied variable is an error, a template cannot reach the filesystem,
  and dunder attribute access is refused. `load_pack()`'s `root` parameter is required — the
  package carries no opinion about an application's pack layout; an application wanting a default
  location supplies its own thin wrapper (FreeWeight's `freeweight.services.prompts.load_pack`
  keeps its old default this way).

  FreeWeight's own prompt pack adopts this module in the same change (pulling its P12 forward):
  `freeweight.services.prompts` is now a re-export shim over `setspec.prompts`, verified to
  produce a byte-identical `pack_hash` and per-record hash for every shipped prompt before and
  after the move, with FreeWeight's own gate green afterwards. Two applications reading the same
  pack format from two processes is the scenario ADR-0028's hashes exist for; the FreeWeight move
  is the first proof of it.

- **JSON Schema for `prompt.record` and `prompt.manifest`**, committed as package data under
  `setspec/schemas/prompt.record/1.0.json` and `setspec/schemas/prompt.manifest/1.0.json`, with
  golden examples under `setspec/goldens/prompt.{record,manifest}/1.0/{full,minimal}.json`. Both
  are hand-authored rather than generated: `PromptRecord` is a plain dataclass, not a pydantic
  envelope payload — a prompt record is a pack file on disk, never wrapped in a `SchemaEnvelope` —
  so neither schema is registered in `PUBLISHED_SCHEMAS`/reachable through `json_schema_for()`,
  and the goldens are illustrative examples rather than inputs to the envelope contract-test
  matrix in `tests/contract/test_goldens.py`. Every golden round-trips through the real
  `load_pack()` loader (not just schema validation) and its `pack_sha256` is the module's own
  computed hash, not a hand-typed value.

### Changed

- Bumped to 0.4.0 for the `setspec.prompts` addition (packaging standards §3: additive,
  non-breaking).

## [0.3.0] — 2026-08-28

### Added

- **The v1.0 freeze.** `DRAFT_SCHEMAS` is now empty. Every registered payload type —
  `model.identity`, `machine.profile`, `benchmark.result`, `benchmark.run_summary`,
  `capability.evidence`, `benchmark.evidence_bundle`, `benchmark.goal_pack` and
  `benchmark.calibration_report` — is a published `1.0` that may no longer be reshaped in place.
  FreeWeight's real output (P6 onward, and P8A–8B for the two goal payloads) demanded no field
  change, so the freeze is a promotion rather than a correction; the one field the pass did add,
  `MetricValueFields.metric_key`, landed before it and is frozen *with* the schema.

  The set survives its own emptiness deliberately: it is the mechanism a future draft uses, and
  deleting it would leave the next provisional payload type either shipping silently provisional or
  inventing a second way to say so.

- **Generated JSON Schema for every published version**, committed as package data under
  `setspec/schemas/<schema>/<version>.json` and reachable through `json_schema_for()`. Generated
  from the **writer** (`extra="forbid"`) half, so a published document says
  `additionalProperties: false` — which is the contract API standards §7 rule 5 states and the one
  a producer's test suite asserts its output against. The reader policy stays where it belongs, in
  the reader: `load_envelope` accepts an unknown minor by comparing majors, never by loosening a
  version's schema to admit fields it cannot describe.

  Every `$ref` resolves inside the document's own `$defs`. Nothing is fetched (spec §14).

- **25 golden payloads**, three or more per version, under
  `setspec/goldens/<schema>/<version>/<name>.json` and reachable through `golden_payloads()` and
  `golden_names()`. Each version ships a `minimal` (only required fields), a `full` (every field
  populated) and, wherever the payload carries a measurement at all, an `unsupported`-heavy example.
  `capability.evidence` adds `goal`, a calibrated `user.noir_tech_voice` record with the whole
  goal-sourced group populated; `benchmark.goal_pack` adds `starter_unforked`; and
  `benchmark.calibration_report` adds `gate_failed` — the outcome `capability.evidence`
  deliberately cannot express, because a goal below its gate emits no evidence record at all.

  Which versions need an `unsupported` golden is derived from the published schema rather than
  listed in the test: a payload whose document contains no `{"const": "unsupported"}` branch has no
  measurement field to leave unsupported, so `benchmark.goal_pack` and
  `benchmark.calibration_report` are excused by the artifact itself rather than by an exception
  someone maintains.

- **`setspec.artifacts`** — `PUBLISHED_SCHEMAS`, `json_schema_for()`, `golden_payloads()`,
  `golden_names()`, `payload_pair()`, `build_json_schema()` and `render_schema_document()`. The
  first four are re-exported from `setspec` directly, matching spec §7's "schema artefacts" group:
  an accessor that *returns* a version's artifacts is not itself versioned.

  `PUBLISHED_SCHEMAS` records **exact** versions, unlike `SUPPORTED_SCHEMAS`, which records
  supported majors. An artifact is a file that either exists or does not, so "highest minor known"
  is the wrong shape for it — and a contract test asserts the two agree, so a schema that can be
  negotiated but not validated, or validated but not negotiated, fails the build.

- **Three contract jobs, one per published guarantee.** `schema-snapshot-diff` regenerates every
  schema from its models and diffs it against the committed snapshot — ADR-0009 rule 7, *a schema
  change without a version bump fails CI*, made mechanical and proven by a deliberate test-only
  mutation. `golden-validation` checks every golden against its writer model, its reader model, the
  published JSON Schema and a canonical round trip. `cross-version-compatibility` builds a synthetic
  `1.1` document from each `full` golden and asserts a `1.0` reader accepts it, preserves the field
  it does not know, and re-exports it intact — then builds a synthetic `2.0` and asserts the refusal
  names both versions. They are separate jobs rather than steps because the three failures are acted
  on differently: bump the version, fix the artifact, or go and warn a consumer.

- **`install-check` now asserts the package data reaches the wheel.** Every test in this repository
  passes against the source tree whether or not the schemas and goldens are built into the
  distribution, so this job is the only one that would notice. It loads all eight schemas and their
  goldens out of the *installed* wheel.

- **`docs/schemas.md`** — the human-readable catalogue: what ships and where, every payload type
  with its required-field count and its goldens, how to consume the artifacts from a repository that
  shares no code with this one, and a table of every cross-field rule the JSON Schema **cannot**
  express and the models therefore still own.

- **`jsonschema` and `types-jsonschema` in the `dev` extra.** Test-only, and justified by the
  assertion they exist for: a golden is validated against the *published document* a non-Python
  consumer receives, not only against the model that generated it. Without a real validator that
  check would be a hand-rolled subset of draft 2020-12 maintained in this repository — the thing
  under test also serving as the thing testing it. Nothing under `src/` imports either, and the base
  install still pulls in no validator. `requirements/ci.lock` regenerated.

- **`metric_key` on `MetricValueFields`.** The model declared value, unit, aggregation, direction,
  sample count and dispersion — and nothing saying *which metric it is*. Both
  `BenchmarkResultFields.metrics` and `BenchmarkRunSummaryFields.aggregate_metrics` carry sequences
  of it, so a consumer receiving a run summary got a list of numbers it could not attribute, chart,
  compare across runs, or check for the metric it was looking for. Required rather than optional:
  an unattributable number is not a measurement. Constrained to lower snake case, because a metric
  key is an identifier consumers match on and `ttft_ms` / `TTFT_ms` from two producers would be two
  metrics to every reader and one to every author.

  The payload stays at schema **1.0**: the suite is pre-freeze, no consumer outside it reads these
  documents yet, and results produced during development are not being retained. After M3 the same
  change would be a minor.

- **The release workflow can publish, and can rehearse first.** `release.yml` gained the
  `publish-testpypi` job every other package repository has — manual only, via *Actions → Release →
  Run workflow* — because packaging and release standards §6 requires a successful TestPyPI publish
  ahead of a package's **first** real release, and `0.2.0` is this one. The `release` job gained
  `environment: pypi`, which must match the Environment name configured on the PyPI trusted
  publisher; without it the OIDC exchange has nothing to match and the publish is rejected.
- **`requirements/ci.lock`, `release.in` and `release.lock`**, hash-pinned — required by packaging
  standards §4 and present in `baseaicore`, `modelrack` and `sweatmeter`, absent here. Every
  blocking CI job now installs the locked toolchain and then `pip install . --no-deps`; the build
  jobs use the release lock with `--no-isolation`, so the wheel CI checks is produced by the same
  pinned backend as the wheel that ships. Without them every run re-resolved, and a new `ruff` or
  `mypy` release could change the result with no commit to explain it.

  The 3.14 early-warning job stays unlocked on purpose: pinning versions that have no 3.14 wheels
  would defeat the point of an early warning.

  Verified by installing both locks under `--require-hashes` into a clean interpreter and running
  every CI job against them — format, lint, mypy, import-linter, tests, coverage, contracts,
  `pip-audit` and the workflow's own build and `twine check`.
- Capability vocabulary **1.1**: the reserved root `user`, whose specializations (`user.<slug>`)
  carry FreeWeight's user-authored goal evidence (ADR-0032 §1). One root added once closes the
  question permanently — the existing open-ended specialization rule accepts every goal any user
  will ever write, so no future rubric is a vocabulary change. `RESERVED_ROOTS` is exported
  alongside `CAPABILITIES`.
- `benchmark.goal_pack` and `benchmark.calibration_report` (`setspec.goal.v1`), both registered in
  `SUPPORTED_SCHEMAS` and listed in `DRAFT_SCHEMAS`. The calibration report is a payload in its own
  right rather than a field group on evidence because it is meaningful precisely when **no**
  evidence was emitted: a goal below its calibration gate produces no evidence record at all
  (ADR-0032 §3).
- The goal-sourced field group on `capability.evidence`: `judge_validity_factor`, `goal_hash`,
  `goal_pack_version`, `score_method_mix`, `judge_set`, `calibration` and `uncalibrated`
  (ADR-0032 §5). Every field is optional and absent on a non-goal record, and
  `judge_validity_factor` defaults to `1.0` — so **no previously valid document changed meaning
  and no existing confidence value changed**, which a regression test asserts directly.

### Changed

- The five payload modules' status notes read **frozen (`1.0`)** rather than **draft (`1.0`)**, and
  say what the freeze binds them to: a new optional field is a minor bump, and a removal, rename,
  retype or tightening is a major — never an edit in place.
- The two tests that asserted the draft state now assert the frozen one
  (`test_no_registered_schema_is_still_draft`, `test_the_schema_is_frozen`). They are the same
  guarantee read from the other side, and leaving them asserting `DRAFT_SCHEMAS == SUPPORTED_SCHEMAS`
  would have made the freeze a change the test suite refused.

- A bare reserved root is now refused by `validate_capability` and reported `False` by
  `is_known_capability`. `user` is a namespace, not a capability: a payload claiming
  `capability_id: "user"` has lost the identity that is the entire point of the namespace.
  This affects no term that existed before 1.1.
- **Forward-compatibility leniency narrows, as it must.** A payload declaring
  `vocabulary_version: "1.1"` with a root this build does not know was previously accepted — `1.1`
  was a newer minor than `1.0`, so the spec §13 exception applied. It is now refused, because
  `1.1` is this build's own vocabulary and there is nothing newer about it. This is what forward
  compatibility *means* rather than a regression: leniency exists to carry terms from a future
  this build has not seen, and it evaporates for a version this build has arrived at. A payload
  declaring `1.2` or later is unaffected. Producers on `1.1` must emit roots that exist at `1.1`.

### Fixed

- **Coverage measured a directory nothing imports.** `[tool.coverage.run] source` named
  `src/setspec`, the source *path*, while CI installs the built distribution — so the moment the
  jobs stopped using an editable install, coverage reported **0 %** and failed the 95 % floor for a
  reason unrelated to the tests. It now names the importable package, with `[tool.coverage.paths]`
  folding the source tree and site-packages into one name, matching `baseaicore`. Both install
  modes report 100 %.
- **`pip-audit` in CI was auditing nothing.** A bare `pip-audit` inspects the job's own
  environment, which contained only `pip-audit` itself, so that job had been reporting clean on an
  empty set. It now audits both locks.
- **`install-check` did not verify that `py.typed` reaches the wheel.** The marker is easy to add
  to the source tree and easy to leave out of the build, and the failure is silent: a consumer's
  `mypy --strict` treats an unmarked package as untyped rather than erroring. Asserted against the
  installed wheel now. (It does ship — this closes the hole, it does not fix a break.)

- The package ships a `py.typed` marker, matching every other implemented package in the suite
  (`baseaicore`, `modelrack`, `sweatmeter`). Without it, `mypy --strict` in a consuming repository
  cannot see this package's types at all and treats every import from it as untyped.

### Known gaps

- `event.envelope` and `error.envelope` (Phase 3) and `prompt.record` / `prompt.manifest`
  (Phase 5) are **not** part of this freeze, because they do not exist yet: a schema is frozen by
  being published, and an unwritten one has nothing to publish. The freeze covers the eight payload
  types that cross an application boundary today, not the eleven ADR-0009 anticipates.

## [0.2.0] — 2026-08-23

Phase 2 of the [development plan](docs/packages/setspec/development-plan.md): provisional
benchmark and evidence payloads. FreeWeight now has concrete models to build against —
`model.identity`, `machine.profile`, `benchmark.result`, `benchmark.run_summary`,
`capability.evidence` and `benchmark.evidence_bundle` — all registered in `SUPPORTED_SCHEMAS` at
`1.0` but explicitly **draft**: Phase 4 may still reshape a field once FreeWeight has produced real
results against it, per this phase's own known risk (guessing the result shape before its producer
exists).

### Added
- `setspec.model.v1`: `ModelIdentityOut`/`In`, the exchange form of `baseaicore.ModelIdentity` plus
  a `ModelDescriptor` snapshot. `canonical_id` and `identity_confidence` are carried on the wire
  but recomputed from the identity triple and checked on every construction — a producer that
  materializes them inconsistently is rejected, not silently trusted.
- `setspec.machine.v1`: `MachineProfileOut`/`In`, `GpuProfileFields`, `StorageDeviceFields` — a
  field-for-field mirror of `baseaicore.MachineProfile`, including which fields are required
  versus optional. `machine_fingerprint` is carried but deliberately **not** re-verified, matching
  `MachineProfile`'s own documented reason: its inclusion policy may change after the profile was
  written, and a historically valid profile must still reconstruct exactly as stored.
- `setspec.benchmark.v1`: `BenchmarkResultOut`/`In` and `BenchmarkRunSummaryOut`/`In`, built from
  Machine Identity §6's minimum
  provenance set — the one place a result's required shape was already normative before any
  FreeWeight code existed. `runtime_profile_hash` is recomputed from the embedded profile and
  checked, the same reasoning as `canonical_id`. Every other hash-shaped field (`manifest_hash`,
  `prompt_subset_hash`, `reproducibility_fingerprint`) is validated only as non-empty: this package
  cannot yet compute FreeWeight's own hashes, and guessing a format risks rejecting the first real
  result over a formatting nuance instead of the risk Phase 2's tests actually target.
- `setspec.capability.v1`: `CapabilityEvidenceOut`/`In` and `EvidenceBundleOut`/`In`, reproducing
  ADR-0022 §1's normative field table
  verbatim. `measured_at` later than `computed_at` is rejected as incoherent — the schema-level
  enforcement of ADR-0022 §2's rule that recomputing evidence must not make it look fresher.
- `setspec.provenance`: `EnvironmentFields`, the provider/driver/OS block shared by
  `benchmark.result`, `benchmark.run_summary` and `capability.evidence`. It gets a neutral home
  for the same reason `setspec.metrics` has one: a sub-model used by two payload types belongs to
  neither, and had it lived in `benchmark/v1.py`, the day `benchmark.result` needed a changed
  environment shape whoever edited that class would silently have changed `capability.evidence`
  v1 too — a frozen contract mutating because someone edited a different payload's module.
- `setspec.envelope.DRAFT_SCHEMAS`: which registered schemas are still provisional. The
  development plan asks for draft status to be visible *in the API*, not only in prose. It is a
  separate set rather than a `"1.0-draft"` version string because the latter would have to be
  parsed by `SchemaVersion`, whose contract is that a version is exactly two integers and
  non-canonical spellings are refused — loosening that permanently, to describe a condition that
  ends at Phase 4, would weaken the version format every frozen schema depends on. Freezing a
  schema is one deletion from this set.
- `benchmark.result` gains the provenance Machine Identity §6
  calls "optional but strongly recommended, and required for any benchmark whose numbers depend on
  them": `measurement_class` (cold/warm/cache_reused/n-a), `telemetry_summary` (peak VRAM,
  peak/mean power, max temperature, throttle flag) and `raw_response_ref` — plus `error_code`,
  `error_text`, `completed_cases` and `total_cases` from FreeWeight's own `run_tests` row. These
  had to be declared rather than left out: the writer half of each pair forbids unknown keys, so a
  field this schema does not name is one a producer *cannot emit at all*. A memory or energy
  benchmark — whose numbers §6 says depend on telemetry — could not have exported a conformant
  result, and a `failed` result had no field in which to say why it failed.
- `RuntimeProfileFields.profile_hash`, a public property delegating to
  `baseaicore.RuntimeProfile`. A consumer needs the hash for the same reason a producer does —
  two results are comparable only if their profiles hash identically — and previously the only
  way to it was a private helper reached across class boundaries behind two `noqa: SLF001`
  waivers.
- `setspec.vocabulary`: `CAPABILITIES`, `CAPABILITY_VOCABULARY_VERSION` (`"1.0"`),
  `validate_capability`, `is_known_capability`. A specialization validates against its **root**
  rather than needing individual enumeration — `coding.rust` is accepted the moment `coding` is
  known — and an unknown ID is accepted leniently only when the payload declares a newer *minor*
  of the vocabulary's current major, never across a major.
- `setspec.base`: `WireSequence`, an ordered-collection field type alongside `WireEnum`. Strict
  mode validates the *input Python type*, and a bare `tuple[T, ...]` under `strict=True` accepts
  only an actual `tuple` — never the `list` every JSON array deserializes to — so every
  ordered-collection field in Phase 2 needed this to accept a real document at all.
- `Aggregation` gains `P50`, `RATIO` and `RAW`, matching aggregation kinds FreeWeight's own data
  model already names that Phase 1's set did not cover.

### Changed
- `PayloadDefinition` now sets `extra="allow"` itself, rather than leaving pydantic's default
  (`extra="ignore"`). A definition nested inside another payload — `model: ModelIdentityFields`
  inside `CapabilityEvidenceFields` — is typed as the bare definition, not a generated `Out`/`In`,
  so its own default governs unknown-key handling regardless of which half of the *outer* pair is
  in use; `ignore` would have silently dropped an unrecognized field from every nested object in
  both directions, which is precisely the loss ADR-0009 rule 4
  exists to prevent. This is additive for every Phase 1 payload, which had no nested fields to
  expose the gap.

### Fixed
- `completed_cases` greater than `total_cases` is now rejected, the same arithmetic honesty the
  timestamp ordering checks already enforced: "12 of 10 cases done" is a producer bug, and a
  consumer rendering it as a percentage would show one above 100%.
- A garbled sentence in `setspec.machine.v1`'s module docstring, left by an edit, made the
  explanation of why `machine_fingerprint` is *not* re-verified unreadable — the one place this
  package carries a hash-shaped field without checking it, so the reason it is deliberate rather
  than an oversight is exactly the thing that had to be legible.
- A test fixture (`tests/unit/test_payloads_benchmark.py`) embedded one module-level dict by
  reference into every result it built; a test that mutated its own copy was actually mutating the
  shared fixture in place, corrupting every test built after it in file execution order. It passed
  under Python 3.13 by luck of `pytest-randomly`'s seed and failed outright under 3.14, whose
  ordering exposed it — the bug was reference aliasing, not a Python-version incompatibility.
  Fixed by building the dict fresh on every call; verified stable across five randomized runs on
  both interpreters.

## [0.1.0] — 2026-08-23

Phase 1 of the [development plan](docs/packages/setspec/development-plan.md): the envelope,
versioning and serialization core. Any payload can now be wrapped, versioned, validated,
serialized canonically and rejected correctly when its major version is unsupported. No payload
type is registered yet — Phase 2 adds the first ones against this machinery, which is why
`SUPPORTED_SCHEMAS` ships empty rather than pre-declaring shapes that do not exist.

### Added
- `envelope`: `SchemaEnvelope`, `GeneratorInfo`, `SchemaVersion`, `SUPPORTED_SCHEMAS`,
  `load_envelope`, `dump_envelope`. The reader policy of
  ADR-0009 rule 3 is enforced in both directions: a
  newer minor within a supported major is accepted with its unknown fields intact, an unsupported
  major is refused with `SchemaVersionUnsupported` naming the schema, the received version and
  every supported one — and is never partially parsed.
- `serialization`: canonical JSON via `baseaicore.canonical_json` (delegated, not reimplemented, so
  a payload hashes identically to every other hashed structure in the suite); `MeasurementField`,
  mapping `UNSUPPORTED ↔ "unsupported"` and refusing `null`, bools and numeric strings; and
  `TimestampField`, RFC 3339 UTC at millisecond precision with naive datetimes rejected.
- `serialization`: `parse_json` with size and depth guards applied *before* the parser runs, so a
  hostile document is refused by a named limit rather than by a `RecursionError`. Limits are the
  module constants `MAX_PAYLOAD_BYTES` (16 MiB, matching API Standards §10) and
  `MAX_PAYLOAD_DEPTH` (64); callers may pass tighter ones per call.
- `base`: `PayloadDefinition`, `StrictPayload`, `PreservingPayload` and `payload_models`, which
  generates the `Out`/`In` pair required by
  ADR-0009 rule 4 from one definition — so a writer
  cannot emit a field it does not know and a reader cannot strip one. The round-trip contract is
  asserted per class, never across the pair.
- `base`: `WireEnum`, for enum fields that must accept their own string values from a parsed
  document while the bases otherwise validate strictly.
- `metrics`: `MetricValueOut`/`MetricValueIn` and `Aggregation`. The
  ADR-0016 §6 invariants are structural rather than
  advisory: a real value must report at least one supported sample, an unsupported value must
  report none, and dispersion needs at least two — so `value=0.0, sample_count=0` cannot be
  serialized at all.
- `errors`: `SchemaVersionUnsupported` (code `SCHEMA_VERSION_UNSUPPORTED`), with
  `baseaicore.ValidationError` re-exported so callers import both from one place.

### Changed
- Coverage floor raised from 85 % to 95 %, the number [spec §18](docs/packages/setspec/spec.md)
  and every phase's acceptance criteria actually state; the scaffold shipped 85 in both
  `pyproject.toml` and the CI job. Current coverage is 100 %.
- `.importlinter`: the second contract listed no forbidden modules at all, and its inline
  `root_packages`/`source_modules` values were read character by character — `lint-imports` failed
  with `Could not find package 's'` and therefore checked nothing. Rewritten as newline-separated
  lists with `include_external_packages`, and renamed from `no-sibling-packages` to
  `no-capability-packages`: `modelrack`, `sweatmeter`, `weightsdb` and `mirrorwall` sit in the
  layer *above* SetSpec, so they were never siblings.

### Fixed
- `ruff format --check .` failed on nine vendored documents under `docs/`. ruff 0.16 formats Python
  code blocks inside markdown, and those files are byte-identical copies of the suite's master
  documents shared with nine other repositories — reformatting them here would desync every copy.
  `docs/` is now excluded from ruff instead.

### Security
- `pytest` moved from `>=8,<9` to `>=9.0.3,<10`, excluding PYSEC-2026-1845 (vulnerable
  `/tmp/pytest-of-{user}` handling, affecting pytest through 9.0.2). Matches the pin BaseAiCore
  already moved to; the suite passes unchanged on pytest 9.
