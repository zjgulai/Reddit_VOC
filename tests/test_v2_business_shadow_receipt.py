from argparse import Namespace
import hashlib
import json
from pathlib import Path

import pytest

from scripts.build_v2_business_shadow_receipt import ShadowReceiptError, build_receipt


ROOT = Path(__file__).resolve().parents[1]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def args(tmp_path: Path) -> Namespace:
    production_build = ROOT / "tmp/reddit-voc-v3/reddit_add_data_20260715_v1/insights-release-build-receipt-a10.json"
    candidate_build = ROOT / "tmp/v2-business-activation-20260717-r1/insights-release-build-receipt-a2.json"
    candidate_e2e = ROOT / "tmp/v2-business-activation-20260717-r1/insights-e2e-receipt-a1.json"
    activation = ROOT / "tmp/v2-business-activation-20260717-r1/manifest.json"
    activation_public = ROOT / "tmp/v2-business-activation-20260717-r1/frontend-source-stage-a3/public/data/reddit-voc/reddit_voc_v2-business-activation-e229fbf2901862918997/manifest.json"
    pointer_source = ROOT / "tmp/v2-business-activation-20260717-r1/frontend-source-stage-a3/public/data/reddit-voc/current-release.json"
    marker = tmp_path / "release.json"
    marker.write_text(json.dumps({"release_sha256": "9c4a45f2da54d1fd417ed2930516d49bae526406cf9fbf20325df682e9784cc5"}), encoding="utf-8")
    pointer = tmp_path / "current-release.json"
    pointer.write_bytes(pointer_source.read_bytes())
    return Namespace(
        cycle_id="cycle-1", observed_at_utc="2026-07-17T11:00:00Z",
        production_release_marker=str(marker), expected_production_release_marker_sha256=sha(marker),
        production_current_release=str(pointer), expected_production_current_release_sha256=sha(pointer),
        production_build_receipt=str(production_build), expected_production_build_receipt_sha256=sha(production_build),
        candidate_build_receipt=str(candidate_build), expected_candidate_build_receipt_sha256=sha(candidate_build),
        candidate_e2e_receipt=str(candidate_e2e), expected_candidate_e2e_receipt_sha256=sha(candidate_e2e),
        activation_manifest=str(activation), expected_activation_manifest_sha256=sha(activation),
        candidate_activation_public_manifest=str(activation_public), expected_candidate_activation_public_manifest_sha256=sha(activation_public),
        output=str(tmp_path / "receipt.json"),
    )


def test_builds_complete_read_only_shadow_receipt(tmp_path: Path) -> None:
    receipt = build_receipt(args(tmp_path))
    assert receipt["status"] == "passed_local_read_only_shadow"
    assert receipt["difference_classification"]["ui"] == "byte_identical_dist"
    assert receipt["difference_classification"]["relationship_debt"]["unresolved_parent_comments"] == 6943
    assert all(receipt["checks"].values())
    assert receipt["boundaries"]["production_unchanged"] is True


def test_rejects_candidate_dataset_drift(tmp_path: Path) -> None:
    value = args(tmp_path)
    pointer_path = Path(value.production_current_release)
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    pointer["datasets"]["base"]["dataset_version"] = "drifted"
    pointer_path.write_text(json.dumps(pointer), encoding="utf-8")
    value.expected_production_current_release_sha256 = sha(pointer_path)
    with pytest.raises(ShadowReceiptError, match="candidate_production_pointer_mismatch"):
        build_receipt(value)


def test_rejects_tampered_candidate_receipt(tmp_path: Path) -> None:
    value = args(tmp_path)
    value.expected_candidate_build_receipt_sha256 = "0" * 64
    with pytest.raises(ShadowReceiptError, match="candidate_build_receipt_sha256_mismatch"):
        build_receipt(value)
