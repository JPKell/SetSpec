# Changelog

All notable changes to `setspec` are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows
[Semantic Versioning](https://semver.org/), pre-1.0 per
`docs/standards/packaging-and-release-standards.md` §3.

## [Unreleased]

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
  [Machine Identity §6](docs/architecture/machine-identity-and-reproducibility.md)'s minimum
  provenance set — the one place a result's required shape was already normative before any
  FreeWeight code existed. `runtime_profile_hash` is recomputed from the embedded profile and
  checked, the same reasoning as `canonical_id`. Every other hash-shaped field (`manifest_hash`,
  `prompt_subset_hash`, `reproducibility_fingerprint`) is validated only as non-empty: this package
  cannot yet compute FreeWeight's own hashes, and guessing a format risks rejecting the first real
  result over a formatting nuance instead of the risk Phase 2's tests actually target.
- `setspec.capability.v1`: `CapabilityEvidenceOut`/`In` and `EvidenceBundleOut`/`In`, reproducing
  [ADR-0022 §1](docs/adr/0022-capability-evidence-record-contract.md)'s normative field table
  verbatim. `measured_at` later than `computed_at` is rejected as incoherent — the schema-level
  enforcement of ADR-0022 §2's rule that recomputing evidence must not make it look fresher.
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
  both directions, which is precisely the loss [ADR-0009 rule 4](docs/adr/0009-setspec-schema-strategy.md)
  exists to prevent. This is additive for every Phase 1 payload, which had no nested fields to
  expose the gap.

### Fixed
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
  [ADR-0009 rule 3](docs/adr/0009-setspec-schema-strategy.md) is enforced in both directions: a
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
  [ADR-0009 rule 4](docs/adr/0009-setspec-schema-strategy.md) from one definition — so a writer
  cannot emit a field it does not know and a reader cannot strip one. The round-trip contract is
  asserted per class, never across the pair.
- `base`: `WireEnum`, for enum fields that must accept their own string values from a parsed
  document while the bases otherwise validate strictly.
- `metrics`: `MetricValueOut`/`MetricValueIn` and `Aggregation`. The
  [ADR-0016 §6](docs/adr/0016-unavailable-is-not-zero.md) invariants are structural rather than
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
