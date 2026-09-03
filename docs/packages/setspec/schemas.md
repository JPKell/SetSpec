# Schema catalogue

Every payload type `setspec` publishes, at every version, with the artifacts that make it usable
from a repository that shares no code with this one.

**Status: frozen at `1.0`** (Phase 4, `setspec 0.3.0`), **with additive minors at Phase 6 and
Phase 7** (`setspec 0.5.0` and `0.6.0`). `DRAFT_SCHEMAS` is empty. From here every change follows
the ordinary rules: a new optional field is a **minor** bump, and a removed, renamed, retyped or
newly-tightened field is a **major**. Neither happens by editing a *published* payload module in
place — the snapshot contract test fails the build if the generated schema stops matching the
committed one, which is ADR-0009 rule 7 made mechanical. `capability.evidence` `1.1` (§2.1 below)
is the first schema to exercise the minor-bump half of that rule, and it does so with a **sibling
class** (`CapabilityEvidenceV1_1Fields`, alongside the untouched `CapabilityEvidenceFields`) rather
than an edit in place, precisely so the `1.0` snapshot keeps regenerating identically forever.
`benchmark.evidence_bundle` `1.1` (Phase 7) exercises the same rule transitively: it nests
`capability.evidence` `1.1` in place of the `1.0` element type its own frozen `1.0` still nests,
on the identical sibling-class mechanism (ADR-0068 rule 5).

---

## 1. What ships, and where it lives

| Artifact | Location in the installed package | Accessor |
|---|---|---|
| JSON Schema, one per version | `setspec/schemas/<schema>/<version>.json` | `json_schema_for(schema, version)` |
| Golden payloads, ≥ 3 per version | `setspec/goldens/<schema>/<version>/<name>.json` | `golden_payloads(schema, version)` |
| The names of those goldens | — | `golden_names(schema, version)` |
| Every published schema and version | — | `PUBLISHED_SCHEMAS` |

All four are importable from `setspec` directly. The files are **package data**, loadable through
`importlib.resources` and present in the built wheel — the `install-check` CI job asserts that
against the installed distribution, because every test in this repository passes against the source
tree whether or not the files reach the wheel.

Nothing is fetched. A published schema resolves every `$ref` inside its own `$defs`, so validating
an export never depends on a registry being reachable (spec §14).

## 2. The catalogue

| Schema | Version | Python module | Writer / reader | Goldens |
|---|---|---|---|---|
| `model.identity` | 1.0 | `setspec.model.v1` | `ModelIdentityOut` / `ModelIdentityIn` | `minimal`, `full`, `unsupported` |
| `model.adapter_manifest` | 1.0 | `setspec.model.v1` | `AdapterManifestOut` / `AdapterManifestIn` | `minimal`, `full`, `name_only` |
| `machine.profile` | 1.0 | `setspec.machine.v1` | `MachineProfileOut` / `MachineProfileIn` | `minimal`, `full`, `unsupported` |
| `benchmark.result` | 1.0 | `setspec.benchmark.v1` | `BenchmarkResultOut` / `BenchmarkResultIn` | `minimal`, `full`, `unsupported` |
| `benchmark.run_summary` | 1.0 | `setspec.benchmark.v1` | `BenchmarkRunSummaryOut` / `BenchmarkRunSummaryIn` | `minimal`, `full`, `unsupported` |
| `capability.evidence` | 1.0 | `setspec.capability.v1` | `CapabilityEvidenceOut` / `CapabilityEvidenceIn` | `minimal`, `full`, `goal`, `unsupported` |
| `capability.evidence` | 1.1 | `setspec.capability.v1` | `CapabilityEvidenceV1_1Out` / `CapabilityEvidenceV1_1In` | `minimal`, `full`, `unsupported` |
| `benchmark.evidence_bundle` | 1.0 | `setspec.capability.v1` | `EvidenceBundleOut` / `EvidenceBundleIn` | `minimal`, `full`, `unsupported` |
| `benchmark.evidence_bundle` | 1.1 | `setspec.capability.v1` | `EvidenceBundleV1_1Out` / `EvidenceBundleV1_1In` | `minimal`, `full`, `mixed`, `unsupported` |
| `benchmark.goal_pack` | 1.0 | `setspec.goal.v1` | `GoalPackOut` / `GoalPackIn` | `minimal`, `full`, `starter_unforked` |
| `benchmark.calibration_report` | 1.0 | `setspec.goal.v1` | `CalibrationReportOut` / `CalibrationReportIn` | `minimal`, `full`, `gate_failed` |
| `governance.egress_decision` | 1.0 | `setspec.governance.v1` | `GovernanceEgressDecisionOut` / `GovernanceEgressDecisionIn` | `minimal`, `full`, `denied_no_ceiling`, `violation` |

### `model.identity` — which weights, plus what the provider says about them

5 required fields of 25. The identity triple (`provider_kind`, `provider_model_name`,
`artifact_digest`) plus its two derived fields, then the refreshable descriptor. `canonical_id` and
`identity_confidence` are **recomputed and checked** against the triple on validation: they are
pure functions of it, carried on the wire for convenience rather than as independent facts
(ADR-0024). Every descriptor quantity defaults to `"unsupported"`, because a provider that reports
no layer count has not reported zero layers.

### `model.adapter_manifest` — the operator-reviewed record behind one adapter

7 required of 10 (ADR-0061 rule 1). `name`, `artifact_sha256` and `source_sha256` are validated by
reconstructing a `baseaicore.AdapterIdentity` from them — the same reuse
`model.identity`'s `canonical_id` check performs, so the name pattern and digest normalization are
never implemented twice. `base` names the model this adapter was trained against, at
`digest`-or-`name_only` confidence exactly like `model.identity`'s own triple, but with no
`provider_kind` — the manifest states a base, not which provider serves it.
`declared_capabilities` is validated strictly against the current vocabulary, with no
forward-compatibility exception: a manifest carries no `vocabulary_version` to prove it was written
against a newer minor. **`data_classification` is required, with no default** — a manifest that
omits it is invalid, not defaulted closed, because ADR-0046's fail-closed default governs a caller
declaring its own data, not a manifest declaring an artifact's provenance (ADR-0065 rule 1).

### `machine.profile` — where a measurement happened

7 required of 14. A field-for-field mirror of `baseaicore.MachineProfile`, including which fields
are required-but-nullable: a producer must say it could not read the hostname rather than omit the
key. `machine_fingerprint` is the one hash-shaped field this package carries **without**
recomputing it — the policy deciding which fields feed a fingerprint may change, while a profile
read back years later must still reconstruct exactly as stored.

### `benchmark.result` — one benchmark, one subject, one machine

12 required of 23, the largest payload in the suite. Carries Machine Identity §6's minimum
provenance set as nested objects: `suite`, `execution`, `environment`, `application`,
`reproducibility`, plus the optional `machine_profile` and `telemetry_summary`.
`runtime_profile_hash` is recomputed from the embedded `runtime_profile` and must agree
(ADR-0023). Four further cross-field rules apply — see §4.

### `benchmark.run_summary` — the roll-up of many results

10 required of 15. Deliberately lighter than a result: the same subject/suite/environment building
blocks, a run state, three timestamps and `aggregate_metrics`. `INTERRUPTED` is a distinct status
from `FAILED` and means the process died and the run is resumable, not that it failed.

### `capability.evidence` — the record LoadCoach routes on

14 required of 26, and the suite's most load-bearing contract (ADR-0022). Identity, score,
confidence, the counts behind them, the hard-separation inputs (`benchmark_versions`,
`dataset_hashes`, `prompt_subset_hashes`, `goal_hash`, `judge_set`) and the two timestamps whose
order is enforced: `measured_at` is what freshness decays from and can never follow `computed_at`.

The **goal-sourced group** (ADR-0032 §5) is optional and absent on an ordinary record:
`judge_validity_factor` (exactly `1.0` for every rung 1–4 measurement), `goal_hash`,
`goal_pack_version`, `score_method_mix`, `judge_set`, `calibration`, `uncalibrated`. The `goal`
golden populates all of it; `uncalibrated: true` is **refused** rather than published, because a
goal below its calibration gate emits no record at all.

**`1.1`** (ADR-0058) adds one further optional field, `adapter` — the measurement's adapter axis,
absent on a record measured on the bare base. It is a genuine second minor on an already-frozen
payload, not folded into the `1.0` freeze the way the goal group was, so it lives on a **sibling
class** (`CapabilityEvidenceV1_1Fields(CapabilityEvidenceFields)`, in the same module) rather than
an edit to `CapabilityEvidenceFields` itself: that class is nested by reference inside
`EvidenceBundleFields`, so editing it in place would silently move `benchmark.evidence_bundle`'s
own committed `1.0` schema too. `CapabilityEvidenceV1_1Fields` also carries a `@model_serializer`
that drops `adapter` from the dump entirely when absent, rather than emitting `"adapter": null` —
the byte-level proof that a non-adapter record written through the `1.1` model is indistinguishable
from what `1.0` writes (I15, [adapter-roadmap §7](../../roadmap/adapter-roadmap.md)).
Producers wanting the `1.1` shape import `CapabilityEvidenceV1_1Out` / `CapabilityEvidenceV1_1In`
explicitly; `CapabilityEvidenceOut` / `CapabilityEvidenceIn` keep meaning `1.0`.

### `benchmark.evidence_bundle` — the FreeWeight → LoadCoach payload

2 required of 3: `source_id`, `complete`, `evidence`. `complete: true` is what lets a consumer
infer removal — evidence held locally for this `source_id` and absent from a complete bundle is
marked superseded, never deleted, and never inferred from a partial bundle. The bundle carries no
`generated_at`: that lives on the envelope, and a client stores *that* value to send back as its
next `?since=`. `1.0`'s `evidence` nests `capability.evidence` at its `1.0` shape, unchanged since
Phase 4.

**`1.1`** (Phase 7, ADR-0068 rule 5) carries the adapter axis one payload out from
`capability.evidence` `1.1`: `EvidenceBundleV1_1Fields(EvidenceBundleFields)` overrides exactly
one inherited field — `evidence` becomes `WireSequence[CapabilityEvidenceV1_1Fields]` — on a
**sibling class** rather than an edit to `EvidenceBundleFields` itself, for the same reason
`capability.evidence` `1.1` is a sibling of its own frozen class: an in-place edit would move a
committed `1.0` snapshot as a side effect of a change meant for the new minor. A bundle whose
records carry no adapter dumps byte-for-byte what `1.0` writes, because a `1.1` evidence record
with no adapter already dumps byte-identically to its `1.0` counterpart — the `mixed` golden shows
bare-base and adapter-bearing records coexisting in one bundle, which is the shape FreeWeight
1.1's actual export (adapter roadmap LA3) produces. Producers wanting the `1.1` shape import
`EvidenceBundleV1_1Out` / `EvidenceBundleV1_1In` explicitly; `EvidenceBundleOut` /
`EvidenceBundleIn` keep meaning `1.0`.

### `benchmark.goal_pack` — a user-authored goal, portable and hash-pinned

6 required of 12. Criteria with their ladder rung and weight, tasks with their prompt hashes, and
the jury when any criterion is judged. Weights must sum to `1`; a judged criterion needs an
anchored ordinal scale and a `judge_set`. The author's calibration **grades do not travel** — an
importer who wants the rubric held to their own taste recalibrates against their own grades.

### `benchmark.calibration_report` — how well the judge agreed with the author

11 required of 14. A payload in its own right rather than a field group on evidence, because it is
meaningful precisely when **no** evidence was emitted: `gate_failed` is the golden that shows the
outcome `capability.evidence` deliberately cannot express (ADR-0032 §3). The verdict must follow
from the numbers — a `passed_gate` that contradicts `weighted_kappa_w` against `min_agreement` is
refused.

### `governance.egress_decision` — one recorded verdict on "may this leave the machine"

All 7 top-level fields required; the nullable ones sit one level down —
`request.target.max_data_classification` and `request.requested_at`. The first is deliberate:
"remote with no declared ceiling" is the fail-closed case Commissioner's shipped policy must be able
to deny and record, not a value this schema forbids (ADR-0054 rule 3). The second mirrors
Commissioner spec §7's own default: `requested_at` records when the *caller built* the request, and
it exists on the wire so that §11 contract 4 — `from_payload(to_payload(d))` preserves every
field — is keepable at all. It is never the record's timestamp; `decided_at` is, and that one is
required. This is SetSpec's fifth owned root — the first outside
`benchmark`/`capability`/`machine`/`model` — added because the payload has a named second reader:
IdeaPress's S4 egress badge reads decisions PromptCadence exported, with Commissioner not installed
(ADR-0051 §4). `verdict` is `approved`,
`denied` or `violation`; `violation` is writable but never produced by the shipped policy — it is
written by a caller's own verification step after the fact (ADR-0054 rule 7), and the schema
carries whatever `reason` that step supplies rather than validating it against the shipped policy's
four reasons. Commissioner does not exist as code yet; this module has no dependency on it and is
exercised only from within this repository.

## 3. Consuming these from another repository

No shared code, no import of the producing application, no database:

```python
from setspec import SchemaVersion, golden_payloads, json_schema_for, load_envelope
from setspec.capability.v1 import EvidenceBundleIn

# The contract test: read every golden this build publishes.
for payload in golden_payloads("benchmark.evidence_bundle", SchemaVersion(1, 0)):
    EvidenceBundleIn.model_validate(payload)

# The real thing: a file a producer exported.
envelope = load_envelope(exported_bytes, expect="benchmark.evidence_bundle")
bundle = EvidenceBundleIn.model_validate(envelope.payload)
```

Read with the **`In`** model, always. It preserves fields this build has not heard of, so an older
consumer in the middle of a pipeline is a relay rather than a sink (ADR-0009 rule 4). Write with the
**`Out`** model, which refuses a field the schema does not declare (rule 5).

A non-Python consumer validates against `json_schema_for(...)`, or against the file directly:

```
setspec/schemas/benchmark.evidence_bundle/1.0.json
```

The documents declare `$schema: https://json-schema.org/draft/2020-12/schema`.

## 4. What the JSON Schema does not say

The published documents are generated from the **writer** model, so they carry
`additionalProperties: false` at the top level — that is the writer's contract, and a producer's
test suite asserts its output validates against it (testing standards §8.2). The reader policy is a
*reader behaviour*: `load_envelope` accepts any minor within a supported major, including one it has
never heard of. That is not a loosening of any one version's schema. A `1.1` document is described
by the `1.1` schema; a `1.0` reader accepts it by comparing majors.

Pydantic renders types, ranges, patterns and required keys. It cannot render a `model_validator`, so
none of the following appears in the published documents and all of them are enforced by the models:

| Payload | Rule the schema cannot state |
|---|---|
| `metric.value` (nested) | A real value needs ≥ 1 supported sample; an unsupported value needs 0; dispersion needs ≥ 2 |
| `model.identity` | `canonical_id` and `identity_confidence` must agree with the identity triple |
| `model.adapter_manifest` | `name`/`artifact_sha256`/`source_sha256` must pass `baseaicore.AdapterIdentity`; `base.identity_confidence` must agree with whether `base.artifact_digest` is present; every `declared_capabilities` entry must be a known, non-bare-reserved-root vocabulary term |
| `benchmark.result` | `runtime_profile_hash` must recompute from `runtime_profile`; `completed_at ≥ started_at`; `completed_cases ≤ total_cases`; `skip_reason` iff skipped; a completed result has metrics |
| `benchmark.run_summary` | `runtime_profile_hash` agreement; timing order |
| `capability.evidence` | `capability_id` in the vocabulary; `measured_at ≤ computed_at`; the five goal-group coherence rules; `score_method_mix` sums to 1 over known rungs |
| `capability.evidence` `1.1` (nested `adapter`) | `canonical_suffix` must recompute from `name`/`artifact_digest` via `baseaicore.AdapterIdentity` |
| `benchmark.goal_pack` | Criterion weights sum to 1; no duplicate keys; rung-appropriate fields; a judged criterion needs a jury |
| `benchmark.calibration_report` | The gate verdict must follow from `weighted_kappa_w` against `min_agreement` |

This is why every golden is validated **twice** — once against the schema a non-Python consumer
uses, once against the model — and why a consumer that can run Python should use the model.

## 5. Versioning and regeneration

A schema version is `MAJOR.MINOR`, independent of this package's own version and of any HTTP API
version. `SUPPORTED_SCHEMAS` declares supported **majors**; `PUBLISHED_SCHEMAS` declares the exact
versions that have artifacts. A contract test asserts the two agree, so a schema that can be
negotiated but not validated — or validated but not negotiated — fails the build.

Adding a **major** version means adding a module (`setspec.benchmark.v2`), registering it, and
committing its schema and goldens. The old version stays importable for at least one minor release
of every consumer (ADR-0009 rule 6). Adding a **minor** to an already-frozen payload — `1.1` of
something already published — follows the narrower pattern Phase 6 established for
`capability.evidence`: a sibling field-definition class in the *same* module, subclassing the
frozen one and adding only optional fields, registered as a second entry in `artifacts._REGISTRY`
alongside the untouched original. The frozen class is never edited, so nothing that nests it by
reference (as `benchmark.evidence_bundle` nests `capability.evidence`) moves with it.

A snapshot can also move without any model here changing. Pydantic embeds a type's `__doc__` as
its JSON Schema `description`, so an upstream release that only edits a docstring on a type these
payloads nest — `baseaicore`'s `ProviderKind`, `DataClassification`, `IdentityConfidence`,
`ModelCapabilityFlag` and the adapter value objects are the ones in reach — changes the generated
bytes of every schema that embeds it, and the snapshot test fails for a reason that has nothing to
do with a payload's shape. This is **not** a version-bump trigger. Regenerate, then prove it was
only prose before committing: strip every `description` from both documents and diff what is left,
and if any property, type or `required` entry moved, the dependency changed a shape rather than a
docstring and the change needs a version, not a re-commit. First seen at Phase 6, where
`baseaicore 0.4.1` moved five already-frozen `1.0` snapshots (`model.identity`,
`benchmark.result`, `benchmark.run_summary`, `capability.evidence`,
`benchmark.evidence_bundle`) and changed nothing about any of them (spec §19).

Regenerate the snapshots after any deliberate model change — or after such a dependency bump:

```bash
python - <<'PY'
from pathlib import Path
from setspec.artifacts import PUBLISHED_SCHEMAS, build_json_schema, render_schema_document

for schema, versions in PUBLISHED_SCHEMAS.items():
    for version in versions:
        path = Path("src/setspec/schemas", schema, f"{version}.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            render_schema_document(build_json_schema(schema, version)), encoding="utf-8"
        )
PY
```

Then answer the question CI just asked: was that change additive, or did it deserve a major bump?
Goldens are **not** regenerated. They are authored, committed and left alone — a golden that is
rebuilt from the model whenever the model changes is not a golden, it is a mirror.
