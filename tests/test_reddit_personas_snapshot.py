import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from scripts.build_reddit_personas_snapshot import build, write_snapshot
from scripts.validate_reddit_personas_snapshot import _write_receipt, validate


ROOT = Path(__file__).resolve().parents[1]
BASE_SNAPSHOT = ROOT / "data/processed/reddit_voc_site_snapshot_20260714"
INSIGHTS_SNAPSHOT = ROOT / "data/processed/reddit_voc_insights_20260714"
PERSONA_CONFIG = ROOT / "config/personas/reddit-voc-evidence-personas-v1.json"
AVATAR_DIR = ROOT / "docs/superpowers/assets/reddit-voc-evidence-personas"
TAG_REPAIR_SNAPSHOT = ROOT / "data/processed/reddit_voc_tag_repair_20260714"
TAG_REPAIR_POLICY = ROOT / "config/tagging/reddit-semantic-predicates-v1.json"


def _build_fixture(output_dir: Path, *, tag_repair_dir: Path | None = None) -> dict:
    personas, persona_tags, manifest = build(
        BASE_SNAPSHOT,
        INSIGHTS_SNAPSHOT,
        PERSONA_CONFIG,
        AVATAR_DIR,
        tag_repair_dir,
        TAG_REPAIR_POLICY if tag_repair_dir else None,
    )
    return write_snapshot(output_dir, personas, persona_tags, manifest, AVATAR_DIR)


def _rewrite_json_and_manifest(output_dir: Path, filename: str, value: dict) -> None:
    path = output_dir / filename
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )
    manifest_path = output_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][filename]["bytes"] = path.stat().st_size
    manifest["files"][filename]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path.write_text(
        json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )


def _public_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {
            key
            for nested in value.values()
            for key in _public_keys(nested)
        }
    if isinstance(value, list):
        return {key for nested in value for key in _public_keys(nested)}
    return set()


def _copy_tag_repair(tmp_path: Path) -> Path:
    destination = tmp_path / "tag-repair"
    shutil.copytree(TAG_REPAIR_SNAPSHOT, destination)
    return destination


def _rewrite_tag_repair_file(repair_dir: Path, filename: str, document: dict) -> None:
    path = repair_dir / filename
    path.write_text(
        json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )
    manifest_path = repair_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][filename] = {
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )


def test_builds_two_evidence_personas_and_validates(tmp_path: Path) -> None:
    output_dir = tmp_path / "personas"
    manifest = _build_fixture(output_dir)
    receipt = validate(
        output_dir,
        BASE_SNAPSHOT,
        INSIGHTS_SNAPSHOT,
        PERSONA_CONFIG,
        AVATAR_DIR,
    )
    personas = json.loads((output_dir / "personas.json").read_text(encoding="utf-8"))
    persona_tags = json.loads(
        (output_dir / "persona-tags.json").read_text(encoding="utf-8")
    )

    assert manifest["dataset_version"] == "reddit_voc_personas_20260714_v1"
    assert manifest["persona_count"] == 2
    assert manifest["assignment_count"] == 109
    assert manifest["tag_repair"]["applied"] is False
    assert receipt["status"] == "passed"
    assert all(receipt["checks"].values())
    assert receipt["manifest_sha256"] == hashlib.sha256(
        (output_dir / "manifest.json").read_bytes()
    ).hexdigest()
    assert receipt["base_manifest_sha256"] == hashlib.sha256(
        (BASE_SNAPSHOT / "manifest.json").read_bytes()
    ).hexdigest()
    assert receipt["insights_manifest_sha256"] == hashlib.sha256(
        (INSIGHTS_SNAPSHOT / "manifest.json").read_bytes()
    ).hexdigest()
    assert receipt["config_sha256"] == hashlib.sha256(
        PERSONA_CONFIG.read_bytes()
    ).hexdigest()
    assert receipt["tag_repair_manifest_sha256"] is None
    assert {
        row["persona_id"]: row["metrics"] for row in personas["personas"]
    } == {
        "PER-SCENE-WORK-001": {
            "matched_entities": 57,
            "matched_posts": 11,
            "matched_comments": 46,
            "distinct_pseudonyms": 51,
            "threads": 31,
        },
        "PER-BEHAVIOR-ADVOCATE-001": {
            "matched_entities": 52,
            "matched_posts": 3,
            "matched_comments": 49,
            "distinct_pseudonyms": 48,
            "threads": 33,
        },
    }
    assert len(persona_tags["assignments"]) == 109
    assert len(
        {
            (row["persona_id"], row["evidence_id"])
            for row in persona_tags["assignments"]
        }
    ) == 109
    assert not (
        _public_keys(personas)
        | _public_keys(persona_tags)
    ) & {
        "author",
        "author_pseudonym",
        "username",
        "profile_url",
        "age",
        "gender",
        "device",
    }
    assert receipt["production_unchanged"] is True
    assert receipt["provider_call"] is False
    assert receipt["database_write"] is False


def test_output_is_byte_stable_for_identical_inputs(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first_manifest = _build_fixture(first)
    second_manifest = _build_fixture(second)

    assert first_manifest == second_manifest
    assert (first / "manifest.json").read_bytes() == (second / "manifest.json").read_bytes()
    for relative_path in first_manifest["files"]:
        assert (first / relative_path).read_bytes() == (second / relative_path).read_bytes()


def test_output_is_byte_stable_across_python_hash_seeds(tmp_path: Path) -> None:
    outputs = []
    for seed in ("1", "2"):
        output_dir = tmp_path / f"seed-{seed}"
        environment = dict(os.environ)
        environment["PYTHONHASHSEED"] = seed
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/build_reddit_personas_snapshot.py"),
                "--snapshot-dir",
                str(BASE_SNAPSHOT),
                "--insights-dir",
                str(INSIGHTS_SNAPSHOT),
                "--config",
                str(PERSONA_CONFIG),
                "--avatar-dir",
                str(AVATAR_DIR),
                "--output-dir",
                str(output_dir),
            ],
            check=True,
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
        )
        outputs.append(output_dir)

    first, second = outputs
    manifest = json.loads((first / "manifest.json").read_text(encoding="utf-8"))
    assert (first / "manifest.json").read_bytes() == (second / "manifest.json").read_bytes()
    for relative_path in manifest["files"]:
        assert (first / relative_path).read_bytes() == (second / relative_path).read_bytes()


def test_snapshot_and_validation_receipt_are_private_and_immutable(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "personas"
    manifest = _build_fixture(output_dir)
    manifest_mtime = (output_dir / "manifest.json").stat().st_mtime_ns
    _build_fixture(output_dir)

    assert output_dir.stat().st_mode & 0o777 == 0o700
    assert all(
        path.stat().st_mode & 0o777 == (0o700 if path.is_dir() else 0o600)
        for path in output_dir.rglob("*")
    )
    assert (output_dir / "manifest.json").stat().st_mtime_ns == manifest_mtime

    result = validate(
        output_dir,
        BASE_SNAPSHOT,
        INSIGHTS_SNAPSHOT,
        PERSONA_CONFIG,
        AVATAR_DIR,
    )
    receipt = tmp_path / "receipt/personas.json"
    assert _write_receipt(receipt, result) == "created"
    receipt_mtime = receipt.stat().st_mtime_ns
    assert _write_receipt(receipt, result) == "no_change"
    assert receipt.stat().st_mtime_ns == receipt_mtime
    assert receipt.parent.stat().st_mode & 0o777 == 0o700
    assert receipt.stat().st_mode & 0o777 == 0o600
    assert manifest["dataset_version"] == result["dataset_version"]

    receipt.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="receipt collision"):
        _write_receipt(receipt, result)


def test_write_snapshot_uses_assets_from_the_supplied_config(tmp_path: Path) -> None:
    config = json.loads(PERSONA_CONFIG.read_text(encoding="utf-8"))
    config_path = tmp_path / "alternate-config.json"
    avatar_dir = tmp_path / "alternate-avatars"
    avatar_dir.mkdir()
    expected_assets = set()
    for index, definition in enumerate(config["personas"], start=1):
        source_name = definition["avatar"]["source_filename"]
        alternate_name = f"alternate-persona-{index}.svg"
        (avatar_dir / alternate_name).write_bytes(
            (AVATAR_DIR / source_name).read_bytes()
        )
        definition["avatar"]["source_filename"] = alternate_name
        definition["avatar"]["asset_path"] = f"assets/{alternate_name}"
        expected_assets.add(f"assets/{alternate_name}")
    config_path.write_text(
        json.dumps(config, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    output_dir = tmp_path / "personas"
    personas, persona_tags, manifest = build(
        BASE_SNAPSHOT,
        INSIGHTS_SNAPSHOT,
        config_path,
        avatar_dir,
    )
    complete_manifest = write_snapshot(
        output_dir,
        personas,
        persona_tags,
        manifest,
        avatar_dir,
    )

    assert {
        name
        for name, metadata in complete_manifest["files"].items()
        if metadata["media_type"] == "image/svg+xml"
    } == expected_assets
    assert validate(
        output_dir,
        BASE_SNAPSHOT,
        INSIGHTS_SNAPSHOT,
        config_path,
        avatar_dir,
    )["status"] == "passed"


def test_binds_optional_tag_repair_manifest(tmp_path: Path) -> None:
    output_dir = tmp_path / "personas"
    manifest = _build_fixture(output_dir, tag_repair_dir=TAG_REPAIR_SNAPSHOT)
    repair_manifest = json.loads(
        (TAG_REPAIR_SNAPSHOT / "manifest.json").read_text(encoding="utf-8")
    )
    repair_manifest_sha256 = hashlib.sha256(
        (TAG_REPAIR_SNAPSHOT / "manifest.json").read_bytes()
    ).hexdigest()

    assert manifest["tag_repair"] == {
        "applied": True,
        "schema_version": "reddit_voc_tag_repair_manifest_v1",
        "dataset_version": repair_manifest["dataset_version"],
        "manifest_sha256": repair_manifest_sha256,
        "status": "completed_no_new_promotions",
    }
    receipt = validate(
        output_dir,
        BASE_SNAPSHOT,
        INSIGHTS_SNAPSHOT,
        PERSONA_CONFIG,
        AVATAR_DIR,
        TAG_REPAIR_SNAPSHOT,
        TAG_REPAIR_POLICY,
    )
    assert receipt["checks"]["optional_tag_repair_binding"] is True
    assert receipt["tag_repair_manifest_sha256"] == repair_manifest_sha256


def test_rejects_three_field_tag_repair_manifest(tmp_path: Path) -> None:
    repair_dir = tmp_path / "repair"
    repair_dir.mkdir()
    (repair_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "reddit_voc_tag_repair_manifest_v1",
                "dataset_version": "reddit_voc_tag_repair_fixture_v1",
                "status": "completed_no_new_promotions",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="tag repair delivery mode mismatch"):
        build(
            BASE_SNAPSHOT,
            INSIGHTS_SNAPSHOT,
            PERSONA_CONFIG,
            AVATAR_DIR,
            repair_dir,
            TAG_REPAIR_POLICY,
        )

    output_dir = tmp_path / "personas"
    _build_fixture(output_dir)
    with pytest.raises(ValueError, match="tag repair delivery mode mismatch"):
        validate(
            output_dir,
            BASE_SNAPSHOT,
            INSIGHTS_SNAPSHOT,
            PERSONA_CONFIG,
            AVATAR_DIR,
            repair_dir,
            TAG_REPAIR_POLICY,
        )


@pytest.mark.parametrize(
    ("filename", "mutate", "message"),
    [
        (
            "assignments.json",
            lambda document: document.__setitem__("predicate_policy_sha256", "0" * 64),
            "tag repair file policy binding mismatch",
        ),
        (
            "semantic-audit.json",
            lambda document: document["summary"].__setitem__(
                "status", "completed_with_promotions"
            ),
            "tag repair audit summary mismatch",
        ),
    ],
)
def test_rejects_rehashed_tag_repair_content_tampering(
    tmp_path: Path,
    filename: str,
    mutate,
    message: str,
) -> None:
    repair_dir = _copy_tag_repair(tmp_path)
    document = json.loads((repair_dir / filename).read_text(encoding="utf-8"))
    mutate(document)
    _rewrite_tag_repair_file(repair_dir, filename, document)

    with pytest.raises(ValueError, match=message):
        build(
            BASE_SNAPSHOT,
            INSIGHTS_SNAPSHOT,
            PERSONA_CONFIG,
            AVATAR_DIR,
            repair_dir,
            TAG_REPAIR_POLICY,
        )

    output_dir = tmp_path / "personas"
    _build_fixture(output_dir)
    with pytest.raises(ValueError, match=message):
        validate(
            output_dir,
            BASE_SNAPSHOT,
            INSIGHTS_SNAPSHOT,
            PERSONA_CONFIG,
            AVATAR_DIR,
            repair_dir,
            TAG_REPAIR_POLICY,
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("base_manifest_sha256", "0" * 64, "tag repair base manifest hash mismatch"),
        (
            "dictionary_sha256",
            "0" * 64,
            "tag repair dictionary binding mismatch",
        ),
        ("status", "review_pending", "tag repair status is not consumable"),
    ],
)
def test_rejects_tag_repair_manifest_contract_tampering(
    tmp_path: Path,
    field: str,
    value: str,
    message: str,
) -> None:
    repair_dir = _copy_tag_repair(tmp_path)
    manifest_path = repair_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest[field] = value
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=message):
        build(
            BASE_SNAPSHOT,
            INSIGHTS_SNAPSHOT,
            PERSONA_CONFIG,
            AVATAR_DIR,
            repair_dir,
            TAG_REPAIR_POLICY,
        )

    output_dir = tmp_path / "personas"
    _build_fixture(output_dir)
    with pytest.raises(ValueError, match=message):
        validate(
            output_dir,
            BASE_SNAPSHOT,
            INSIGHTS_SNAPSHOT,
            PERSONA_CONFIG,
            AVATAR_DIR,
            repair_dir,
            TAG_REPAIR_POLICY,
        )


def test_rejects_tag_repair_policy_byte_tampering(tmp_path: Path) -> None:
    policy_path = tmp_path / "policy.json"
    policy_path.write_bytes(TAG_REPAIR_POLICY.read_bytes() + b" ")

    with pytest.raises(ValueError, match="tag repair policy hash mismatch"):
        build(
            BASE_SNAPSHOT,
            INSIGHTS_SNAPSHOT,
            PERSONA_CONFIG,
            AVATAR_DIR,
            TAG_REPAIR_SNAPSHOT,
            policy_path,
        )

    output_dir = tmp_path / "personas"
    _build_fixture(output_dir)
    with pytest.raises(ValueError, match="tag repair policy hash mismatch"):
        validate(
            output_dir,
            BASE_SNAPSHOT,
            INSIGHTS_SNAPSHOT,
            PERSONA_CONFIG,
            AVATAR_DIR,
            TAG_REPAIR_SNAPSHOT,
            policy_path,
        )


def test_rejects_held_tag_injection_even_after_rehash(tmp_path: Path) -> None:
    output_dir = tmp_path / "personas"
    _build_fixture(output_dir)
    value = json.loads((output_dir / "persona-tags.json").read_text(encoding="utf-8"))
    value["assignments"][0]["tag_id"] = "L0-SVC-019"
    _rewrite_json_and_manifest(output_dir, "persona-tags.json", value)

    with pytest.raises(ValueError, match="assignment source tag is not promoted"):
        validate(
            output_dir,
            BASE_SNAPSHOT,
            INSIGHTS_SNAPSHOT,
            PERSONA_CONFIG,
            AVATAR_DIR,
        )


@pytest.mark.parametrize(
    ("filename", "key", "value", "message"),
    [
        ("persona-tags.json", "author_pseudonym", "anon_deadbeef00", "forbidden public key"),
        ("personas.json", "age", "30-35", "forbidden public key"),
        ("personas.json", "device", "mobile", "forbidden public key"),
    ],
)
def test_rejects_public_identity_or_demographic_fields(
    tmp_path: Path,
    filename: str,
    key: str,
    value: str,
    message: str,
) -> None:
    output_dir = tmp_path / "personas"
    _build_fixture(output_dir)
    document = json.loads((output_dir / filename).read_text(encoding="utf-8"))
    target = document["assignments"][0] if filename == "persona-tags.json" else document["personas"][0]
    target[key] = value
    _rewrite_json_and_manifest(output_dir, filename, document)

    with pytest.raises(ValueError, match=message):
        validate(
            output_dir,
            BASE_SNAPSHOT,
            INSIGHTS_SNAPSHOT,
            PERSONA_CONFIG,
            AVATAR_DIR,
        )


def test_rejects_avatar_byte_tampering(tmp_path: Path) -> None:
    output_dir = tmp_path / "personas"
    manifest = _build_fixture(output_dir)
    avatar_path = next(
        output_dir / name
        for name, metadata in manifest["files"].items()
        if metadata.get("media_type") == "image/svg+xml"
    )
    avatar_path.write_text(
        avatar_path.read_text(encoding="utf-8") + " ", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="file byte mismatch"):
        validate(
            output_dir,
            BASE_SNAPSHOT,
            INSIGHTS_SNAPSHOT,
            PERSONA_CONFIG,
            AVATAR_DIR,
        )


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda row: row["avatar"].__setitem__(
                "asset_path", "https://example.com/avatar.svg"
            ),
            "avatar path is not local",
        ),
        (
            lambda row: row["avatar"].__setitem__("identity_claim", True),
            "avatar identity boundary mismatch",
        ),
    ],
)
def test_rejects_remote_or_identity_claiming_avatar(
    tmp_path: Path,
    mutate,
    message: str,
) -> None:
    output_dir = tmp_path / "personas"
    _build_fixture(output_dir)
    document = json.loads((output_dir / "personas.json").read_text(encoding="utf-8"))
    mutate(document["personas"][0])
    _rewrite_json_and_manifest(output_dir, "personas.json", document)

    with pytest.raises(ValueError, match=message):
        validate(
            output_dir,
            BASE_SNAPSHOT,
            INSIGHTS_SNAPSHOT,
            PERSONA_CONFIG,
            AVATAR_DIR,
        )


def test_rejects_config_that_maps_a_held_tag_to_persona(tmp_path: Path) -> None:
    config = json.loads(PERSONA_CONFIG.read_text(encoding="utf-8"))
    config["personas"][0]["source_tag_ids"] = ["L0-SVC-019"]
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="persona source tag is not promoted"):
        build(BASE_SNAPSHOT, INSIGHTS_SNAPSHOT, path, AVATAR_DIR, None)


def test_rejects_generated_persona_below_privacy_threshold(tmp_path: Path) -> None:
    output_dir = tmp_path / "personas"
    _build_fixture(output_dir)
    document = json.loads((output_dir / "personas.json").read_text(encoding="utf-8"))
    document["personas"][0]["metrics"]["distinct_pseudonyms"] = 9
    _rewrite_json_and_manifest(output_dir, "personas.json", document)

    with pytest.raises(ValueError, match="persona metrics mismatch"):
        validate(
            output_dir,
            BASE_SNAPSHOT,
            INSIGHTS_SNAPSHOT,
            PERSONA_CONFIG,
            AVATAR_DIR,
        )
