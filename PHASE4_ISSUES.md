# Phase 4 — issues to address

Written at the end of Phase 4 (freeze v1.0, publish schemas and goldens; `setspec 0.3.0`). Each
entry is something a later phase, a docs change, a consumer or a release step has to resolve.
Nothing here blocks Phase 4's acceptance criteria; everything here would become a defect if it were
forgotten.

---

## Status — 2026-08-28

| # | Issue | Status |
|---|---|---|
| 1 | The freeze covers eight payload types, not ADR-0009's eleven | **Open — by design.** Phases 3 and 5 own the other three. |
| 2 | Goldens are authored inputs, but a SetSpec writer emits every declared key | **Needs a decision.** |
| 3 | `ContributingMetricFields.metric_key` carries no pattern while `MetricValueFields.metric_key` does | **Needs a decision.** |
| 4 | Cross-field rules are invisible in the published JSON Schema | **Open — documented.** `docs/schemas.md` §4 lists every one. |
| 5 | `jsonschema` joined the `dev` extra; `requirements/ci.lock` regenerated | **Closed** — verify `pip-audit` in CI. |
| 6 | The release is not tagged or published yet | **Owner: you.** Commands below. |

---

## 1. The freeze covers eight payload types, not eleven

ADR-0009 lists eleven initial payload types. `event.envelope` and `error.envelope` (Phase 3) and
`prompt.record` / `prompt.manifest` (Phase 5) are not written, so they are not frozen — a schema is
frozen by being published, and an unwritten one has nothing to publish. `DRAFT_SCHEMAS` is empty
**now**; when Phase 3 or 5 lands a new payload type it should re-enter that set until its own
freeze, which is exactly the mechanism the set survives its emptiness for. The changelog's *Known
gaps* section says the same. Nothing to do until those phases start, except not to read "empty"
as "finished".

## 2. Goldens are authored inputs, but a SetSpec writer emits every declared key

`dump_envelope(CapabilityEvidenceOut(...))` serialises through `model_dump()`, which writes every
declared field — a non-goal record carries `goal_hash: null`, `uncalibrated: false`, and so on. The
`capability.evidence/1.0/full` golden was authored the other way round: it omits the goal group
entirely, because "fully populated" was read as "every field a *non-goal* record populates". Both
forms validate under both models, so the contract is not broken, but a producer's structural test
("my keys match the full golden's keys") fails against the file and passes against the file *as a
SetSpec writer would dump it*. FreeWeight's contract test compares against the latter.

**Decision needed:** should goldens be committed *as written* (every declared key present, nulls
included), so that "matches the golden structurally" is a byte-level statement? If yes, regenerate
the 25 goldens through their `Out` models once and add a contract test that a golden equals its own
writer-dumped form. If no, say so in `docs/schemas.md` §3 so consumers compare against the dumped
form, as FreeWeight now does.

## 3. `ContributingMetricFields.metric_key` has no pattern

`MetricValueFields.metric_key` is constrained to lower snake case, dot-separable
(`^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$`). `ContributingMetricFields.metric_key` — the key inside
`capability.evidence.contributing_metrics` — is only `min_length=1`. FreeWeight writes
`<suite_key>.<metric_key>` there (`native.tool_use.task_success`), `criterion.<key>` for a goal's
own record and `goal.<slug>.composite_score` for a goal contributing to a shipped capability; all
three happen to satisfy the stricter pattern. Tightening the field is a **major** change now that
`1.0` is frozen, so it can only land as `capability.evidence 2.0`, and only if a consumer ever
needs the guarantee. Recorded so the asymmetry is a decision rather than an accident.

## 4. Cross-field rules are invisible in the published JSON Schema

Pydantic renders types, ranges, patterns and required keys; it cannot render a `model_validator`.
`runtime_profile_hash` agreeing with its profile, `score_method_mix` summing to one,
`measured_at ≤ computed_at`, the goal group's five coherence rules — every one is enforced by the
models only. `docs/schemas.md` §4 tables them, and every golden is validated against *both* the
schema and the model for exactly this reason. A non-Python consumer that needs those rules needs a
second validation step this package does not ship. Nothing to do unless such a consumer appears.

## 5. `jsonschema` in the `dev` extra

Added so the golden contract test validates against the *published* document with a real
draft-2020-12 validator rather than a hand-rolled subset. Test only — nothing under `src/`
imports it and the base install pulls in no validator. `requirements/ci.lock` was regenerated with
`pip-compile --generate-hashes` (jsonschema 4.26.0, jsonschema-specifications, referencing,
rpds-py, attrs, types-jsonschema). `release.lock` is unchanged. CI's `security` job audits both
locks; the first run after this lands is the one to watch.

## 6. Tagging and publishing 0.3.0

Nothing was tagged or published. `__about__.py` says `0.3.0` and the changelog carries a dated
`[0.3.0]` section. The release procedure (packaging standards §6), from the SetSpec repository:

```bash
cd ~/ai/suite/py/SetSpec
git add -A
git commit -m "feat(setspec): freeze v1.0, publish JSON Schema and goldens (Phase 4, 0.3.0)"
git push origin main
# wait for CI to be green on main, then:
git tag -a v0.3.0 -m "setspec 0.3.0 — v1.0 contracts frozen; JSON Schema and goldens published"
git push origin v0.3.0
# release.yml builds, tests the wheel, publishes via Trusted Publishing and creates the release.
# Verify:
python -m venv /tmp/setspec-check && /tmp/setspec-check/bin/pip install setspec==0.3.0 && \
  /tmp/setspec-check/bin/python -c "from setspec import PUBLISHED_SCHEMAS, golden_payloads, SchemaVersion; \
  print(len(PUBLISHED_SCHEMAS), len(golden_payloads('capability.evidence', SchemaVersion(1, 0))))"
```

FreeWeight's `pyproject.toml` already pins `setspec>=0.3,<0.4`; its `install-check` job cannot
resolve until this release is on PyPI.
