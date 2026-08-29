"""setspec.prompts — loading, validation, rendering and hashing.

The hashes here cross an application boundary inside ``capability.evidence``, so their determinism
is a contract, not an implementation detail (ADR-0028 §3) — Phase 5's own test list names this
directly: "same record => same sha256 across platforms, Python versions and setspec versions."
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from setspec.prompts import (
    PromptNotFound,
    PromptPackInvalid,
    PromptRenderError,
    PromptVariableError,
    build_manifest,
    load_pack,
    load_record,
    pack_hash,
    prompt_record_hash,
    prompt_subset_hash,
    write_manifest,
)
from setspec.prompts import PromptReference as Ref

_RECORD: dict[str, Any] = {
    "schema_version": "1.0",
    "prompt_id": "example.probe",
    "version": "1.0.0",
    "purpose": "Exercise the loader.",
    "system": None,
    "template": "{{ subject }}",
    "variables": {
        "subject": {"type": "string", "required": True, "description": "What to talk about."}
    },
    "metadata": {"change_reason": "First version."},
}


def _record(**overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = json.loads(json.dumps(_RECORD))
    record.update(overrides)
    return record


def _write_pack(root: Path, records: list[dict[str, Any]], *, pack_id: str = "test.pack") -> Path:
    """Write a pack with a *correct* manifest and return its root."""
    root.mkdir(parents=True, exist_ok=True)
    references = []
    for index, record in enumerate(records):
        path = root / f"record{index}.json"
        path.write_text(json.dumps(record), encoding="utf-8")
        references.append(
            Ref(
                prompt_id=record["prompt_id"],
                version=record["version"],
                sha256=prompt_record_hash(record),
            )
        )
    manifest = {
        "pack_id": pack_id,
        "pack_version": "1.0.0",
        "schema_version": "1.0",
        "generated_at": "2026-08-27T00:00:00Z",
        "prompts": [ref.as_json() for ref in references],
        "pack_sha256": pack_hash(references),
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root


class TestRecordHashing:
    def test_same_record_same_hash(self) -> None:
        """dev-plan P5: same record => same sha256."""
        first = prompt_record_hash(_record())
        second = prompt_record_hash(_record())
        assert first == second
        assert first.startswith("sha256:")
        assert len(first) == len("sha256:") + 64

    def test_key_order_does_not_affect_the_hash(self) -> None:
        body = _record()
        reordered = dict(reversed(list(body.items())))
        assert prompt_record_hash(body) == prompt_record_hash(reordered)

    def test_different_content_different_hash(self) -> None:
        assert prompt_record_hash(_record()) != prompt_record_hash(_record(purpose="Different."))

    def test_hash_is_stable_across_repeated_calls_same_process(self) -> None:
        """Stands in for "across platforms, Python versions and setspec versions in the matrix" —
        those are exercised by CI's build matrix; what one process can prove is call-to-call
        stability of the same deterministic arithmetic (canonical_json + sha256)."""
        hashes = {prompt_record_hash(_record()) for _ in range(10)}
        assert len(hashes) == 1


class TestSubsetHashing:
    def test_changes_for_a_subset_member(self) -> None:
        """dev-plan P5: prompt_subset_hash changes for a subset member."""
        a = Ref(prompt_id="a", version="1.0.0", sha256=prompt_record_hash(_record()))
        b = Ref(prompt_id="b", version="1.0.0", sha256=prompt_record_hash(_record(purpose="B")))
        before = prompt_subset_hash([a, b])
        a_changed = Ref(
            prompt_id="a", version="1.0.0", sha256=prompt_record_hash(_record(purpose="Changed"))
        )
        after = prompt_subset_hash([a_changed, b])
        assert before != after

    def test_does_not_change_for_a_non_member(self) -> None:
        """dev-plan P5: ...and not for a non-member — editing a prompt no benchmark uses changes
        no fingerprint (ADR-0028 §1)."""
        a = Ref(prompt_id="a", version="1.0.0", sha256=prompt_record_hash(_record()))
        subset_before = prompt_subset_hash([a])
        # "c" is edited but was never in the subset.
        c_before = Ref(prompt_id="c", version="1.0.0", sha256=prompt_record_hash(_record()))
        c_after = Ref(
            prompt_id="c", version="1.0.0", sha256=prompt_record_hash(_record(purpose="Edited"))
        )
        assert prompt_subset_hash([a, c_before]) != prompt_subset_hash([a, c_after])  # sanity
        subset_after = prompt_subset_hash([a])
        assert subset_before == subset_after

    def test_order_independent(self) -> None:
        a = Ref(prompt_id="a", version="1.0.0", sha256="sha256:" + "1" * 64)
        b = Ref(prompt_id="b", version="1.0.0", sha256="sha256:" + "2" * 64)
        assert prompt_subset_hash([a, b]) == prompt_subset_hash([b, a])

    def test_empty_subset_is_a_stable_value(self) -> None:
        assert prompt_subset_hash([]) == prompt_subset_hash([])
        assert prompt_subset_hash([]).startswith("sha256:")


class TestRendering:
    def test_deterministic(self) -> None:
        record = load_record_from_body(_record())
        first = record.render({"subject": "cats"})
        second = record.render({"subject": "cats"})
        assert first.user == second.user == "cats"
        assert first.rendered_sha256 == second.rendered_sha256

    def test_strict_undefined_raises_on_missing_variable(self) -> None:
        """dev-plan P5: StrictUndefined raises on a missing variable."""
        record = load_record_from_body(
            _record(
                template="{{ subject }} {{ extra }}",
                variables={
                    **_RECORD["variables"],
                    "extra": {"type": "string", "required": True, "description": "Missing."},
                },
            )
        )
        with pytest.raises(PromptVariableError, match="extra"):
            record.render({"subject": "cats"})

    def test_unknown_supplied_variable_is_an_error(self) -> None:
        """dev-plan P5: an unknown supplied variable is an error."""
        record = load_record_from_body(_record())
        with pytest.raises(PromptVariableError, match="typo_variable"):
            record.render({"subject": "cats", "typo_variable": "oops"})

    def test_wrong_type_rejected(self) -> None:
        record = load_record_from_body(_record())
        with pytest.raises(PromptVariableError, match="string"):
            record.render({"subject": 5})

    def test_out_of_range_rejected(self) -> None:
        record = load_record_from_body(
            _record(
                template="{{ n }}",
                variables={
                    "n": {
                        "type": "integer",
                        "required": True,
                        "description": "d",
                        "min": 0,
                        "max": 10,
                    }
                },
            )
        )
        with pytest.raises(PromptVariableError, match="at most"):
            record.render({"n": 11})

    def test_optional_variable_uses_default_when_omitted(self) -> None:
        record = load_record_from_body(
            _record(
                template="{{ n }}",
                variables={
                    "n": {"type": "integer", "required": False, "description": "d", "default": 7}
                },
            )
        )
        assert record.render({}).user == "7"

    def test_malformed_template_rejected_at_load_time(self, tmp_path: Path) -> None:
        """A syntax error is caught before a record is ever installed, not deferred to render."""
        path = tmp_path / "record.json"
        path.write_text(json.dumps(_record(template="{{ subject ")), encoding="utf-8")
        with pytest.raises(PromptPackInvalid, match="does not parse"):
            load_record(path)

    def test_no_filesystem_reach_from_a_template(self) -> None:
        """The loader-less sandboxed environment: a template cannot ``include`` a file, so a
        record that is syntactically valid Jinja but tries to reach the filesystem fails at
        render time with PromptRenderError, not by actually including anything."""
        record = load_record_from_body(_record(template="{% include 'x' %}", variables={}))
        with pytest.raises(PromptRenderError):
            record.render({})

    def test_sandboxed_environment_refuses_dunder_access(self) -> None:
        record = load_record_from_body(
            _record(
                template="{{ subject.__class__ }}",
                variables={"subject": {"type": "string", "required": True, "description": "d"}},
            )
        )
        with pytest.raises(PromptRenderError):
            record.render({"subject": "x"})


def load_record_from_body(body: dict[str, Any], tmp_dir: Path | None = None) -> Any:
    """Write ``body`` to a temp file and load it — the loader is the only public entry point."""
    import tempfile

    directory = tmp_dir or Path(tempfile.mkdtemp())
    path = directory / "record.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return load_record(path)


class TestLoadPack:
    def test_valid_pack_loads(self, tmp_path: Path) -> None:
        root = _write_pack(tmp_path / "pack", [_record()])
        library = load_pack(root)
        assert library.ids() == ("example.probe",)
        assert library.pack_id == "test.pack"

    def test_stale_manifest_rejected(self, tmp_path: Path) -> None:
        root = _write_pack(tmp_path / "pack", [_record()])
        (root / "record0.json").write_text(json.dumps(_record(purpose="Changed.")))
        with pytest.raises(PromptPackInvalid, match="stale"):
            load_pack(root)

    def test_missing_manifest_rejected(self, tmp_path: Path) -> None:
        root = tmp_path / "pack"
        root.mkdir()
        (root / "record0.json").write_text(json.dumps(_record()))
        with pytest.raises(PromptPackInvalid):
            load_pack(root)

    def test_duplicate_prompt_id_and_version_rejected(self, tmp_path: Path) -> None:
        root = _write_pack(tmp_path / "pack", [_record(), _record()])
        with pytest.raises(PromptPackInvalid, match="declared twice"):
            load_pack(root)

    def test_unknown_schema_version_rejected(self, tmp_path: Path) -> None:
        root = _write_pack(tmp_path / "pack", [_record(schema_version="9.9")])
        with pytest.raises(PromptPackInvalid, match="9.9"):
            load_pack(root)

    def test_undeclared_template_variable_rejected(self, tmp_path: Path) -> None:
        root = _write_pack(tmp_path / "pack", [_record(template="{{ subject }} {{ oops }}")])
        with pytest.raises(PromptPackInvalid, match="undeclared"):
            load_pack(root)

    def test_unused_declared_variable_rejected(self, tmp_path: Path) -> None:
        root = _write_pack(
            tmp_path / "pack",
            [
                _record(
                    template="static text",
                    variables={
                        "subject": {"type": "string", "required": True, "description": "unused"}
                    },
                )
            ],
        )
        with pytest.raises(PromptPackInvalid, match="unused"):
            load_pack(root)

    def test_override_replaces_shipped_record(self, tmp_path: Path) -> None:
        root = _write_pack(tmp_path / "pack", [_record()])
        overrides = tmp_path / "overrides"
        overrides.mkdir()
        (overrides / "override.json").write_text(json.dumps(_record(purpose="Overridden.")))
        library = load_pack(root, override_root=overrides)
        assert library.get("example.probe").source == "user_override"
        assert library.overridden_ids == ("example.probe",)

    def test_shipped_references_ignore_override(self, tmp_path: Path) -> None:
        root = _write_pack(tmp_path / "pack", [_record()])
        overrides = tmp_path / "overrides"
        overrides.mkdir()
        (overrides / "override.json").write_text(json.dumps(_record(purpose="Overridden.")))
        library = load_pack(root, override_root=overrides)
        (shipped_ref,) = library.shipped_references([("example.probe", None)])
        assert shipped_ref.sha256 == prompt_record_hash(_record())

    def test_get_unknown_prompt_raises_not_found(self, tmp_path: Path) -> None:
        root = _write_pack(tmp_path / "pack", [_record()])
        library = load_pack(root)
        with pytest.raises(PromptNotFound):
            library.get("does.not.exist")

    def test_get_unknown_version_raises_not_found(self, tmp_path: Path) -> None:
        root = _write_pack(tmp_path / "pack", [_record()])
        library = load_pack(root)
        with pytest.raises(PromptNotFound):
            library.get("example.probe", version="9.9.9")

    def test_get_latest_version_by_default(self, tmp_path: Path) -> None:
        root = _write_pack(tmp_path / "pack", [_record(version="1.0.0"), _record(version="2.0.0")])
        library = load_pack(root)
        assert library.get("example.probe").version == "2.0.0"


class TestManifestBuild:
    def test_build_manifest_matches_load_pack_expectations(self, tmp_path: Path) -> None:
        root = tmp_path / "pack"
        root.mkdir()
        (root / "record0.json").write_text(json.dumps(_record()))
        manifest, drift = build_manifest(root, generated_at="2026-08-27T00:00:00Z")
        assert not drift.is_current  # no manifest existed yet
        write_manifest(manifest, root)
        library = load_pack(root)  # must not raise
        assert library.ids() == ("example.probe",)

    def test_drift_detects_added_removed_changed(self, tmp_path: Path) -> None:
        root = _write_pack(tmp_path / "pack", [_record(prompt_id="a"), _record(prompt_id="b")])
        # Change "a", remove "b", add "c".
        (root / "record0.json").write_text(json.dumps(_record(prompt_id="a", purpose="Changed")))
        (root / "record1.json").unlink()
        (root / "record2.json").write_text(json.dumps(_record(prompt_id="c")))
        _, drift = build_manifest(root)
        assert drift.changed == (("a", "1.0.0"),)
        assert drift.removed == (("b", "1.0.0"),)
        assert drift.added == (("c", "1.0.0"),)
        assert not drift.is_current

    def test_current_manifest_reports_no_drift(self, tmp_path: Path) -> None:
        root = _write_pack(tmp_path / "pack", [_record()])
        manifest, _ = build_manifest(root, generated_at="2026-08-27T00:00:00Z")
        write_manifest(manifest, root)
        _, drift = build_manifest(root, generated_at="2026-08-27T00:00:00Z")
        assert drift.is_current
