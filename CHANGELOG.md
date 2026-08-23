# Changelog

All notable changes to `setspec` are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows
[Semantic Versioning](https://semver.org/), pre-1.0 per
`docs/standards/packaging-and-release-standards.md` §3.

## [Unreleased]

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
