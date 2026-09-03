"""``benchmark.evidence_bundle`` `1.1` — Phase 7's additive proof, the bundle's own I15.

*"A payload nested by reference does not move when the payload it nests gains a minor. Carrying
the new minor into the outer payload is the outer payload's own minor, decided, versioned and
scheduled separately."* (ADR-0068 rule 5). ``test_adapter_axis_i15.py`` proves that promise for
``capability.evidence`` — LA0's exit condition, one payload in. This file proves the *transitive*
half, one payload out: **today's committed ``benchmark.evidence_bundle/1.0`` goldens, unchanged on
disk, dump byte-identically through the adapter-aware ``1.1`` model.** If any of them changed, the
bundle minor was not actually additive, and that is a stop (row constraint), not a golden to
update.

Marked ``contract``.
"""

from __future__ import annotations

import json
from importlib import resources

import pytest

from setspec import SchemaVersion, canonical_dumps
from setspec.artifacts import golden_names, golden_payloads
from setspec.capability.v1 import (
    EvidenceBundleIn,
    EvidenceBundleOut,
    EvidenceBundleV1_1In,
    EvidenceBundleV1_1Out,
)

pytestmark = pytest.mark.contract

_V1_0 = SchemaVersion(1, 0)
_V1_1 = SchemaVersion(1, 1)


class TestTodaysBundlesRoundTripByteIdentically:
    """The bundle analogue of I15's second half: no committed `1.0` golden's bytes may move."""

    @pytest.mark.parametrize("name", golden_names("benchmark.evidence_bundle", _V1_0))
    def test_a_1_0_golden_dumped_through_the_1_1_model_is_byte_identical(self, name: str) -> None:
        documents = dict(
            zip(
                golden_names("benchmark.evidence_bundle", _V1_0),
                golden_payloads("benchmark.evidence_bundle", _V1_0),
                strict=True,
            )
        )
        document = documents[name]
        via_1_0 = EvidenceBundleOut.model_validate(document)
        via_1_1 = EvidenceBundleV1_1Out.model_validate(document)
        assert all(record.adapter is None for record in via_1_1.evidence)
        assert canonical_dumps(via_1_0) == canonical_dumps(via_1_1)

    @pytest.mark.parametrize("name", golden_names("benchmark.evidence_bundle", _V1_0))
    def test_a_1_0_golden_file_on_disk_is_unchanged(self, name: str) -> None:
        """The committed artifact itself, not just what the model produces from it.

        Reads the file this build ships rather than a path relative to the working directory, so
        the assertion holds the same way it would for an installed wheel.
        """
        text = (
            resources.files("setspec")
            .joinpath("goldens", "benchmark.evidence_bundle", "1.0", f"{name}.json")
            .read_text(encoding="utf-8")
        )
        document = json.loads(text)
        assert "adapter" not in json.dumps(document)


class TestAdapterBearingBundlesValidateOnlyThroughTheirOwnMinor:
    """The direction that matters: `1.0` never produces an adapter-bearing record, so the
    assertion is not "a `1.0` document with an adapter is rejected" (there is no such document a
    `1.0` writer could have made) but "an adapter-bearing document needs `1.1` to validate, and a
    bare-base document needs neither exclusively."""

    def test_an_adapter_bearing_bundle_validates_through_1_1_in(self) -> None:
        documents = dict(
            zip(
                golden_names("benchmark.evidence_bundle", _V1_1),
                golden_payloads("benchmark.evidence_bundle", _V1_1),
                strict=True,
            )
        )
        bundle = EvidenceBundleV1_1In.model_validate(documents["full"])
        assert all(record.adapter is not None for record in bundle.evidence)

    def test_a_bundle_with_no_adapter_anywhere_validates_through_both(self) -> None:
        documents = dict(
            zip(
                golden_names("benchmark.evidence_bundle", _V1_0),
                golden_payloads("benchmark.evidence_bundle", _V1_0),
                strict=True,
            )
        )
        document = documents["full"]
        via_1_0 = EvidenceBundleIn.model_validate(document)
        via_1_1 = EvidenceBundleV1_1In.model_validate(document)
        assert len(via_1_0.evidence) == len(via_1_1.evidence)
        assert all(record.adapter is None for record in via_1_1.evidence)


class TestAMixedBundlePreservesEachRecordsAdapterPresenceIndividually:
    """LA3's actual shape: bare-base and adapter-bearing evidence in the same complete export."""

    def test_a_mixed_bundle_round_trips_with_per_record_adapter_presence_preserved(self) -> None:
        documents = dict(
            zip(
                golden_names("benchmark.evidence_bundle", _V1_1),
                golden_payloads("benchmark.evidence_bundle", _V1_1),
                strict=True,
            )
        )
        document = documents["mixed"]
        bundle = EvidenceBundleV1_1Out.model_validate(document)
        adapter_presence = [record.adapter is not None for record in bundle.evidence]
        assert any(adapter_presence)
        assert not all(adapter_presence)

        reparsed = EvidenceBundleV1_1Out.model_validate(json.loads(canonical_dumps(bundle)))
        assert [record.adapter is not None for record in reparsed.evidence] == adapter_presence
        assert reparsed == bundle
