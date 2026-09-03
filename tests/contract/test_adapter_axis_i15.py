"""I15 — the LA0 exit condition (adapter-roadmap §7): the adapter axis's contract half.

*"A `setspec`-only reader validates the manifest and adapter-evidence goldens, and today's
evidence records round-trip byte-identically."*

The first half — a `setspec`-only reader validating the ``model.adapter_manifest`` and
adapter-bearing ``capability.evidence`` `1.1` goldens — is already exercised generically by every
``_EVERY_GOLDEN``-parametrized test in ``test_goldens.py``, since both schemas are registered in
``PUBLISHED_SCHEMAS`` exactly like every other payload type; nothing about I15's first half needs a
bespoke test. This file is the second half, spelled out explicitly rather than left to the general
round-trip machinery: **today's evidence records** — the committed `1.0` goldens, unchanged on
disk — **round-trip byte-identically** through the current, adapter-aware build. If any of them
changed, the `1.1` addition was not actually additive, and that is a stop (row constraint), not a
golden to update.

``test_bundle_minor_is_additive.py`` is this file's Phase 7 sibling, one payload out: it proves
the same promise for ``benchmark.evidence_bundle`` `1.1`, whose ``evidence`` field nests this
schema's `1.1` element type rather than the frozen `1.0` one (ADR-0068 rule 5). Kept separate
because this file is LA0's exit condition and should keep meaning exactly that.

Marked ``contract``.
"""

from __future__ import annotations

import json
from importlib import resources

import pytest

from setspec import SchemaVersion, canonical_dumps
from setspec.artifacts import golden_names, golden_payloads
from setspec.capability.v1 import CapabilityEvidenceOut, CapabilityEvidenceV1_1Out
from setspec.model.v1 import AdapterManifestOut

pytestmark = pytest.mark.contract

_V1_0 = SchemaVersion(1, 0)


class TestTodaysEvidenceRecordsRoundTripByteIdentically:
    """I15's second half: no committed `1.0` golden's canonical bytes may move."""

    @pytest.mark.parametrize("name", golden_names("capability.evidence", _V1_0))
    def test_a_1_0_golden_dumped_through_the_1_1_model_is_byte_identical(self, name: str) -> None:
        documents = dict(
            zip(
                golden_names("capability.evidence", _V1_0),
                golden_payloads("capability.evidence", _V1_0),
                strict=True,
            )
        )
        document = documents[name]
        via_1_0 = CapabilityEvidenceOut.model_validate(document)
        via_1_1 = CapabilityEvidenceV1_1Out.model_validate(document)
        assert via_1_1.adapter is None
        assert canonical_dumps(via_1_0) == canonical_dumps(via_1_1)

    @pytest.mark.parametrize("name", golden_names("capability.evidence", _V1_0))
    def test_a_1_0_golden_file_on_disk_is_unchanged(self, name: str) -> None:
        """The committed artifact itself, not just what the model produces from it.

        Reads the file this build ships rather than a path relative to the working directory, so
        the assertion holds the same way it would for an installed wheel.
        """
        text = (
            resources.files("setspec")
            .joinpath("goldens", "capability.evidence", "1.0", f"{name}.json")
            .read_text(encoding="utf-8")
        )
        document = json.loads(text)
        assert "adapter" not in document


class TestAManifestAndAnAdapterBearingEvidenceGoldenValidateWithSetspecAlone:
    """I15's first half, spelled out once explicitly rather than left implicit in the generic
    golden machinery — a `setspec`-only script, no other suite package imported."""

    def test_a_manifest_golden_validates(self) -> None:
        documents = dict(
            zip(
                golden_names("model.adapter_manifest", _V1_0),
                golden_payloads("model.adapter_manifest", _V1_0),
                strict=True,
            )
        )
        manifest = AdapterManifestOut.model_validate(documents["full"])
        assert manifest.base.identity_confidence.value == "digest"

    def test_an_adapter_bearing_evidence_golden_validates(self) -> None:
        v1_1 = SchemaVersion(1, 1)
        documents = dict(
            zip(
                golden_names("capability.evidence", v1_1),
                golden_payloads("capability.evidence", v1_1),
                strict=True,
            )
        )
        evidence = CapabilityEvidenceV1_1Out.model_validate(documents["full"])
        assert evidence.adapter is not None
        assert evidence.adapter.name == "factcheck"
