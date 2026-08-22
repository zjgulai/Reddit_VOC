# pyright: reportMissingImports=false
from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
from typing import Any

import pytest

from scripts.build_public_site_projection import build_projection
from scripts.validate_public_site_projection import (
    ExpectedHashes,
    validate_public_projection,
    write_immutable_receipt,
)
from tests.test_public_site_projection import (
    _build_v2_fixture,
    _contract,
    _write,
)


ROOT = Path(__file__).resolve().parents[1]
CASES_SOURCE = ROOT / "ref/UI/momcozy-reddit-workbench/public/data/cases"


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _prepare_fixture(tmp_path: Path) -> dict[str, Any]:
    source_root = tmp_path / "private"
    base_version, insights_version, reports_version, personas_version = (
        _build_v2_fixture(source_root)
    )

    base_manifest_sha = _sha(source_root / base_version / "manifest.json")
    insights_manifest_path = source_root / insights_version / "manifest.json"
    insights_manifest = _load(insights_manifest_path)
    insights_manifest["base_dataset_version"] = base_version
    insights_manifest["base_manifest_sha256"] = base_manifest_sha
    insights_manifest["generated_at_utc"] = "2026-07-15T00:00:00+00:00"
    _write(insights_manifest_path, insights_manifest)
    insights_manifest_sha = _sha(insights_manifest_path)
    reports_manifest_path = source_root / reports_version / "manifest.json"
    reports_manifest = _load(reports_manifest_path)
    reports_manifest["base_dataset_version"] = base_version
    reports_manifest["base_manifest_sha256"] = base_manifest_sha
    reports_manifest["insights_dataset_version"] = insights_version
    reports_manifest["insights_manifest_sha256"] = insights_manifest_sha
    _write(reports_manifest_path, reports_manifest)

    personas_dir = source_root / personas_version
    personas = _load(personas_dir / "personas.json")
    personas["personas"].append(
        {
            "persona_id": "PER-FIXTURE-002",
            "name_cn": "第二内容证据 cohort",
            "avatar": {
                "asset_path": "assets/persona-fixture-2.svg",
                "synthetic": True,
                "real_user_image": False,
            },
        }
    )
    personas["persona_count"] = 2
    _write(personas_dir / "personas.json", personas)
    second_avatar = personas_dir / "assets/persona-fixture-2.svg"
    second_avatar.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8" '
        'viewBox="0 0 8 8"><rect width="8" height="8"/></svg>\n',
        encoding="utf-8",
    )
    personas_manifest = _load(personas_dir / "manifest.json")
    personas_manifest["base_dataset_version"] = base_version
    personas_manifest["base_manifest_sha256"] = base_manifest_sha
    personas_manifest["insights_dataset_version"] = insights_version
    personas_manifest["insights_manifest_sha256"] = insights_manifest_sha
    personas_manifest["persona_count"] = 2
    personas_manifest["files"]["personas.json"] = _contract(
        personas_dir / "personas.json"
    )
    personas_manifest["files"]["assets/persona-fixture-2.svg"] = _contract(
        second_avatar
    )
    _write(personas_dir / "manifest.json", personas_manifest)

    public_root = tmp_path / "public-projection"
    build_projection(
        source_root,
        output_root=public_root,
        base_version=base_version,
        insights_version=insights_version,
        reports_version=reports_version,
        personas_version=personas_version,
    )
    cases_root = tmp_path / "cases"
    cases_root.mkdir()
    cases_manifest_path = cases_root / "manifest.v1.json"
    cases_index_path = cases_root / "case-index.v1.json"
    shutil.copyfile(CASES_SOURCE / "manifest.v1.json", cases_manifest_path)
    shutil.copyfile(CASES_SOURCE / "case-index.v1.json", cases_index_path)

    values: dict[str, Any] = {
        "source_root": source_root,
        "base_version": base_version,
        "insights_version": insights_version,
        "reports_version": reports_version,
        "personas_version": personas_version,
        "base_dir": source_root / base_version,
        "insights_dir": source_root / insights_version,
        "reports_dir": source_root / reports_version,
        "personas_dir": source_root / personas_version,
        "public_root": public_root,
        "cases_manifest": cases_manifest_path,
        "cases_index": cases_index_path,
    }
    values["expected"] = _expected(values)
    return values


def _expected(values: dict[str, Any]) -> ExpectedHashes:
    public_data = values["public_root"] / "data/reddit-voc"
    cases_manifest = _load(values["cases_manifest"])
    inventory_rows = []
    for path in sorted(values["public_root"].rglob("*")):
        if path.is_file() and not path.is_symlink():
            relative = path.relative_to(values["public_root"]).as_posix()
            inventory_rows.append(
                f"{relative}\t{path.stat().st_size}\t{_sha(path)}\n"
            )
    public_inventory_sha256 = sha256("".join(inventory_rows).encode("utf-8")).hexdigest()
    return ExpectedHashes(
        base_manifest_sha256=_sha(values["base_dir"] / "manifest.json"),
        insights_manifest_sha256=_sha(values["insights_dir"] / "manifest.json"),
        reports_manifest_sha256=_sha(values["reports_dir"] / "manifest.json"),
        personas_manifest_sha256=_sha(values["personas_dir"] / "manifest.json"),
        public_base_manifest_sha256=_sha(
            public_data / values["base_version"] / "manifest-public.json"
        ),
        public_insights_manifest_sha256=_sha(
            public_data / values["insights_version"] / "public/manifest.json"
        ),
        public_reports_manifest_sha256=_sha(
            public_data / values["reports_version"] / "public/manifest.json"
        ),
        public_personas_manifest_sha256=_sha(
            public_data / values["personas_version"] / "manifest.json"
        ),
        public_inventory_sha256=public_inventory_sha256,
        cases_manifest_sha256=_sha(values["cases_manifest"]),
        cases_index_sha256=_sha(values["cases_index"]),
        cases_seed_content_sha256=cases_manifest["seed"]["contentSha256"],
        cases_legacy_content_sha256=cases_manifest["legacyUnverified"][
            "contentSha256"
        ],
        cases_approved_delta_content_sha256=cases_manifest["approvedDelta"][
            "contentSha256"
        ],
    )


def _validate(values: dict[str, Any], expected: ExpectedHashes | None = None) -> dict[str, Any]:
    return validate_public_projection(
        base_dir=values["base_dir"],
        insights_dir=values["insights_dir"],
        reports_dir=values["reports_dir"],
        personas_dir=values["personas_dir"],
        public_root=values["public_root"],
        cases_manifest=values["cases_manifest"],
        cases_index=values["cases_index"],
        expected=expected or values["expected"],
    )


def test_independent_validator_writes_deterministic_immutable_receipt(
    tmp_path: Path,
) -> None:
    values = _prepare_fixture(tmp_path)
    result = _validate(values)

    assert result["schema_version"] == "reddit_voc_public_projection_validation_v1"
    assert result["status"] == "passed_release_candidate"
    assert result["public_inventory"]["file_count"] == 21
    assert result["cases"]["selected_count"] == 38
    assert result["cases"]["unverified_count"] == 12
    assert result["cases"]["approved_delta_count"] == 0
    assert result["production_unchanged"] is True

    with pytest.raises(ValueError, match="public inventory SHA mismatch"):
        _validate(
            values,
            replace(values["expected"], public_inventory_sha256="0" * 64),
        )

    receipt = tmp_path / "receipt" / "public-validation-receipt.json"
    assert write_immutable_receipt(receipt, result) == "created"
    original_stat = receipt.stat()
    assert receipt.parent.stat().st_mode & 0o777 == 0o700
    assert original_stat.st_mode & 0o777 == 0o600
    assert write_immutable_receipt(receipt, result) == "no_change"
    assert receipt.stat().st_mtime_ns == original_stat.st_mtime_ns

    receipt.write_bytes(receipt.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="immutable collision"):
        write_immutable_receipt(receipt, result)


def test_rehashed_public_analysis_tamper_is_rejected(tmp_path: Path) -> None:
    values = _prepare_fixture(tmp_path)
    public_data = values["public_root"] / "data/reddit-voc"
    insights_root = public_data / values["insights_version"] / "public"
    insights_path = insights_root / "insights.json"
    insights = _load(insights_path)
    insights["author"] = "private-author"
    _write(insights_path, insights)
    manifest_path = insights_root / "manifest.json"
    manifest = _load(manifest_path)
    manifest["files"]["insights.json"] = _contract(insights_path)
    _write(manifest_path, manifest)
    attacker_expected = replace(
        values["expected"], public_insights_manifest_sha256=_sha(manifest_path)
    )

    with pytest.raises(ValueError, match="public projection byte mismatch"):
        _validate(values, attacker_expected)


def test_extra_file_and_symlink_are_rejected(tmp_path: Path) -> None:
    values = _prepare_fixture(tmp_path)
    extra = values["public_root"] / "data/reddit-voc/extra.json"
    extra.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="path set mismatch"):
        _validate(values)
    extra.unlink()

    link = values["public_root"] / "data/reddit-voc/unsafe-link.json"
    os.symlink(values["cases_index"], link)
    with pytest.raises(ValueError, match="contains symlink"):
        _validate(values)


def test_orphan_evidence_reference_is_rejected_independently(tmp_path: Path) -> None:
    values = _prepare_fixture(tmp_path)
    insights_path = values["insights_dir"] / "insights.json"
    insights = _load(insights_path)
    reference = insights["risk_command_center"]["risk_themes"][0]["evidence_refs"][0]
    reference["entity_id"] = "missing-comment"
    _write(insights_path, insights)
    private_manifest_path = values["insights_dir"] / "manifest.json"
    private_manifest = _load(private_manifest_path)
    private_manifest["files"]["insights.json"] = _contract(insights_path)
    _write(private_manifest_path, private_manifest)

    # Rebuild an otherwise internally consistent public projection. Reports and
    # personas must follow the new private Insights manifest identity.
    new_insights_sha = _sha(private_manifest_path)
    for key in ("reports_dir", "personas_dir"):
        manifest_path = values[key] / "manifest.json"
        manifest = _load(manifest_path)
        manifest["insights_manifest_sha256"] = new_insights_sha
        _write(manifest_path, manifest)
    shutil.rmtree(values["public_root"])
    build_projection(
        values["source_root"],
        output_root=values["public_root"],
        base_version=values["base_version"],
        insights_version=values["insights_version"],
        reports_version=values["reports_version"],
        personas_version=values["personas_version"],
    )
    values["expected"] = _expected(values)
    with pytest.raises(ValueError, match="evidence ref is not in Base"):
        _validate(values)


def test_unsafe_svg_and_persona_pii_are_rejected(tmp_path: Path) -> None:
    values = _prepare_fixture(tmp_path)
    avatar = values["personas_dir"] / "assets/persona-fixture-2.svg"
    avatar.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>\n',
        encoding="utf-8",
    )
    personas_path = values["personas_dir"] / "personas.json"
    personas = _load(personas_path)
    personas["personas"][1]["name_cn"] = "contact@example.com"
    _write(personas_path, personas)
    manifest_path = values["personas_dir"] / "manifest.json"
    manifest = _load(manifest_path)
    manifest["files"]["assets/persona-fixture-2.svg"] = _contract(avatar)
    manifest["files"]["personas.json"] = _contract(personas_path)
    _write(manifest_path, manifest)
    shutil.rmtree(values["public_root"])
    build_projection(
        values["source_root"],
        output_root=values["public_root"],
        base_version=values["base_version"],
        insights_version=values["insights_version"],
        reports_version=values["reports_version"],
        personas_version=values["personas_version"],
    )
    values["expected"] = _expected(values)

    with pytest.raises(ValueError, match="unsafe SVG element"):
        _validate(values)

    avatar.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"><circle r="2"/></svg>\n',
        encoding="utf-8",
    )
    manifest = _load(manifest_path)
    manifest["files"]["assets/persona-fixture-2.svg"] = _contract(avatar)
    _write(manifest_path, manifest)
    shutil.rmtree(values["public_root"])
    build_projection(
        values["source_root"],
        output_root=values["public_root"],
        base_version=values["base_version"],
        insights_version=values["insights_version"],
        reports_version=values["reports_version"],
        personas_version=values["personas_version"],
    )
    values["expected"] = _expected(values)
    with pytest.raises(ValueError, match="email-like PII"):
        _validate(values)


def test_cases_content_hash_cannot_be_rebased_by_manifest_rehash(tmp_path: Path) -> None:
    values = _prepare_fixture(tmp_path)
    manifest = _load(values["cases_manifest"])
    manifest["seed"]["contentSha256"] = "f" * 64
    _write(values["cases_manifest"], manifest)
    attacker_expected = replace(
        values["expected"], cases_manifest_sha256=_sha(values["cases_manifest"])
    )
    with pytest.raises(ValueError, match="cases seed content SHA mismatch"):
        _validate(values, attacker_expected)
