# `setspec.prompts` Adoption Checklist

For an application that owns a prompt pack today (its own `PromptRecord`/`load_pack`-shaped code,
or an equivalent) and wants to move onto `setspec.prompts` instead of maintaining a second copy of
prompt-record loading, hashing and rendering. Written against the first adopter, FreeWeight P12
(§5 below is that migration, completed); the steps are what the *next* adopter — IdeaPress or
LoadCoach, whichever writes its first prompt pack second — should follow.

## 1. What to delete outright

Anything that duplicates, byte-for-byte in behaviour, what `setspec.prompts` now provides:
`PromptRecord`/`VariableSpec`/`RenderedPrompt`/`PromptReference`/`PromptLibrary`, `load_record()`,
`load_pack()`, `build_manifest()`/`write_manifest()`, `prompt_record_hash()`/`prompt_subset_hash()`/
`pack_hash()`, and the sandboxed `StrictUndefined` Jinja2 environment. If your pack format matches
prompt-management-standards §2.1–§3 (schema_version/prompt_id/version/template/purpose/metadata,
a manifest with pack_id/pack_version/prompts/pack_sha256), there should be nothing left to keep.

## 2. The one thing every adopter supplies itself: pack location

`load_pack(root: Path, *, override_root: Path | None = None)` takes `root` as a required
positional argument — the package has no opinion about where an application's pack lives on disk,
and no default. If your call sites currently call a zero-argument `load_pack()`, write a one-line
wrapper in your own package that supplies your pack's fixed location and forwards everything else:

```python
from pathlib import Path
from setspec.prompts import load_pack as _setspec_load_pack, PromptLibrary

PACK_ROOT = Path(__file__).resolve().parent.parent / "prompts"

def load_pack(root: Path = PACK_ROOT, *, override_root: Path | None = None) -> PromptLibrary:
    return _setspec_load_pack(root, override_root=override_root)
```

Do this even if every current call site could be edited to pass `root` explicitly — a re-export
shim at your old import path means the migration touches one file instead of every call site, and
is the difference between a multi-file diff and a four-file one (§5).

## 3. Behaviour to re-verify, not assume

* **Hashing is over `canonical_json`, not file bytes.** If you ever hashed a record file's raw
  bytes, that is not the same value `prompt_record_hash()` produces; re-indenting a file must not
  change its hash, and canonical-JSON hashing already guarantees that here.
* **Declared-and-unused is a load-time error, same as undeclared-and-used.** A variable in the
  record's `variables` block that the template never references fails validation — not just the
  reverse. Audit existing records for this before the first `load_pack()` call in CI.
  See [`goldens/prompt.record/1.0/full.json`](../src/setspec/goldens/prompt.record/1.0/full.json)
  for a record where every declared variable — including a non-string one with `min`/`max` — is
  used in the template.
* **The Jinja2 environment has no loader.** `{% include %}` / `{% extends %}` fail at render time
  (`PromptRenderError`), not load time — a template that used either against your old environment
  needs rewriting, not just re-pointing.
* **`pack_hash()` is provenance, never a fingerprint input** (ADR-0028 §1). If your evidence
  payloads folded a pack-wide hash into a capability fingerprint, stop — only
  `prompt_subset_hash()` over the *specific prompts a benchmark declares* belongs there.

## 4. Tests that must still pass, unchanged

Whatever exercises your prompt pack today — rendering determinism, unknown-variable rejection,
sandboxing (no filesystem reach, no dunder attribute access from a template) — should still pass
against `setspec.prompts` with no change to the test's assertions, only to its imports. A test that
needed a new assertion to pass found a real behaviour difference; treat that as a bug to resolve,
not a test to relax, before shipping the migration.

## 5. Verification: FreeWeight P12 (completed)

FreeWeight adopted `setspec.prompts` in the same change that added it to `setspec` (Phase 5 pulled
FreeWeight's own P12 forward, rather than leaving `setspec.prompts` unused until a later phase).
The proof this checklist rests on:

1. **Before**: captured the pack hash and every individual record hash from FreeWeight's original,
   pre-migration `freeweight.services.prompts` — `pack_hash: sha256:b1b0ffd0a5941fee5e0013d2a826732ea02a285b229bdc006ebd6dd25ff4ceb4`
   plus 18 individual record hashes spanning `benchmarks.agent.goal` through `goals.judge.rubric`.
2. **After, direct**: loaded the same pack through `setspec.prompts.load_pack()` directly and
   recomputed every hash — identical.
3. **After, through the shim**: rewrote `freeweight/services/prompts.py` as a thin re-export over
   `setspec.prompts` (§2's pattern, `PACK_ROOT` default preserved) and recomputed through
   FreeWeight's own public import path — identical again.
4. **Full gate, unchanged**: FreeWeight's complete pre-PR gate (ruff, mypy strict over 265 files,
   import-linter, pytest) passed with no test assertions changed — 2297 passed, 28 skipped, 21
   deselected (performance). The only non-shim source edit was 3 import statements in
   `tests/security/test_goal_pack_import.py`, which reached into the module's private
   `_environment()` directly for a sandboxing assertion; every other call site needed no change.

Final diff: 4 files changed. The next adopter should expect a diff of similar shape — one shim
file, a dependency bump, and an edit only where a test reached past the public API.
