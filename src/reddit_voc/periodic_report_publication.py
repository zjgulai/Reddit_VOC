from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
from typing import Mapping
from urllib.parse import urlsplit

from .periodic_report_bundle import PERIODS, PeriodicBundleError, verify_periodic_report_bundle
from .report_contracts import canonical_json_bytes, sha256_hex


PUBLIC_MANIFEST_SCHEMA = "reddit-voc-periodic-report-public-manifest-v1"
PUBLICATION_RECEIPT_SCHEMA = "reddit-voc-periodic-report-publication-receipt-v1"


def materialize_periodic_public_projection(
    *,
    bundle_root: Path,
    projection_root: Path,
    expected_release_id: str,
    expected_destination_fingerprint: str,
    expected_bundle_manifest_sha256: str,
) -> tuple[Mapping[str, object], Mapping[str, object]]:
    bundle_root = Path(bundle_root)
    projection_root = Path(projection_root)
    if projection_root.exists() or projection_root.is_symlink():
        raise PeriodicBundleError("periodic_public_projection_root_exists")
    manifest = verify_periodic_report_bundle(
        bundle_root,
        expected_release_id=expected_release_id,
        expected_destination_fingerprint=expected_destination_fingerprint,
    )
    actual_bundle_sha = sha256_hex((bundle_root / "manifest.json").read_bytes())
    if actual_bundle_sha != expected_bundle_manifest_sha256:
        raise PeriodicBundleError("periodic_public_source_manifest_mismatch")
    bundle_id = str(manifest["bundle_id"])
    captures = manifest["captures"]
    assert isinstance(captures, list)
    assets: list[Mapping[str, object]] = []
    temporary_parent = projection_root.parent.resolve()
    temporary_parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{projection_root.name}.", dir=temporary_parent)
    )
    os.chmod(temporary, 0o755)
    try:
        target_root = temporary / "periodic-report-assets" / bundle_id
        target_root.mkdir(parents=True, mode=0o755)
        for grain in PERIODS:
            capture = next(
                row
                for row in captures
                if isinstance(row, Mapping) and row.get("grain") == grain
            )
            poster = capture["poster"]
            assert isinstance(poster, Mapping)
            source = bundle_root / str(poster["relative_path"])
            target = target_root / "public" / grain / "poster.png"
            target.parent.mkdir(parents=True, mode=0o755)
            payload = source.read_bytes()
            if (
                len(payload) != poster["bytes"]
                or sha256_hex(payload) != poster["sha256"]
            ):
                raise PeriodicBundleError("periodic_public_source_bytes_mismatch")
            target.write_bytes(payload)
            target.chmod(0o644)
            parsed = urlsplit(str(poster["public_url"]))
            expected_path = f"/periodic-report-assets/{bundle_id}/public/{grain}/poster.png"
            if parsed.scheme != "https" or parsed.path != expected_path:
                raise PeriodicBundleError("periodic_public_url_path_mismatch")
            assets.append(
                {
                    "grain": grain,
                    "period_id": capture["period_id"],
                    "data_as_of": capture["data_as_of"],
                    "source_freshness_status": capture["source_freshness_status"],
                    "relative_path": expected_path.lstrip("/"),
                    "public_url": poster["public_url"],
                    "bytes": poster["bytes"],
                    "sha256": poster["sha256"],
                    "width": poster["width"],
                    "height": poster["height"],
                }
            )
        public_manifest: Mapping[str, object] = {
            "schema_version": PUBLIC_MANIFEST_SCHEMA,
            "status": "publication_candidate_not_deployed",
            "bundle_id": bundle_id,
            "data_release_id": expected_release_id,
            "dataset_version": manifest["identity"]["dataset_version"],
            "data_as_of": manifest["data_as_of"],
            "assets": assets,
            "source_bundle_manifest_sha256": actual_bundle_sha,
            "boundaries": {
                "public_png_only": True,
                "private_outbox_excluded": True,
                "destination_fingerprint_excluded": True,
                "credential_material_excluded": True,
                "production_unchanged": True,
                "deploy": False,
                "remote_write": False,
                "live_send": False,
                "webhook_send": False,
            },
        }
        public_manifest_path = target_root / "manifest.json"
        public_manifest_path.write_bytes(canonical_json_bytes(public_manifest))
        public_manifest_path.chmod(0o644)
        os.replace(temporary, projection_root)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    verified_public = verify_periodic_public_projection(
        projection_root,
        expected_release_id=expected_release_id,
        expected_bundle_manifest_sha256=actual_bundle_sha,
    )
    receipt: Mapping[str, object] = {
        "schema_version": PUBLICATION_RECEIPT_SCHEMA,
        "status": "passed_local_publication_candidate",
        "bundle_id": bundle_id,
        "data_release_id": expected_release_id,
        "source_bundle_manifest_sha256": actual_bundle_sha,
        "public_manifest_sha256": sha256_hex(
            (
                projection_root
                / "periodic-report-assets"
                / bundle_id
                / "manifest.json"
            ).read_bytes()
        ),
        "asset_count": len(verified_public["assets"]),
        "boundaries": {
            "production_unchanged": True,
            "deploy": False,
            "remote_write": False,
            "schedule_change": False,
            "provider_call": False,
            "database_write": False,
            "live_send": False,
            "webhook_send": False,
        },
    }
    return verified_public, receipt


def verify_periodic_public_projection(
    projection_root: Path,
    *,
    expected_release_id: str,
    expected_bundle_manifest_sha256: str,
) -> Mapping[str, object]:
    root = Path(projection_root)
    if not root.is_dir() or root.is_symlink():
        raise PeriodicBundleError("periodic_public_projection_root_invalid")
    manifests = list(root.glob("periodic-report-assets/*/manifest.json"))
    if len(manifests) != 1:
        raise PeriodicBundleError("periodic_public_manifest_set_invalid")
    manifest_path = manifests[0]
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise PeriodicBundleError("periodic_public_manifest_invalid")
    payload = manifest_path.read_bytes()
    try:
        import json

        manifest = json.loads(payload.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise PeriodicBundleError("periodic_public_manifest_invalid") from exc
    if not isinstance(manifest, Mapping) or payload != canonical_json_bytes(manifest):
        raise PeriodicBundleError("periodic_public_manifest_invalid")
    assets = manifest.get("assets")
    boundaries = manifest.get("boundaries")
    bundle_id = manifest.get("bundle_id")
    if (
        manifest.get("schema_version") != PUBLIC_MANIFEST_SCHEMA
        or manifest.get("status") != "publication_candidate_not_deployed"
        or manifest.get("data_release_id") != expected_release_id
        or manifest.get("source_bundle_manifest_sha256")
        != expected_bundle_manifest_sha256
        or not isinstance(bundle_id, str)
        or manifest_path.parent.name != bundle_id
        or not isinstance(assets, list)
        or len(assets) != 3
        or {row.get("grain") for row in assets if isinstance(row, Mapping)}
        != set(PERIODS)
        or not isinstance(boundaries, Mapping)
        or boundaries.get("private_outbox_excluded") is not True
        or boundaries.get("destination_fingerprint_excluded") is not True
        or boundaries.get("credential_material_excluded") is not True
        or any(boundaries.get(key) is not False for key in ("deploy", "remote_write", "live_send", "webhook_send"))
    ):
        raise PeriodicBundleError("periodic_public_manifest_contract_invalid")
    expected_files = {
        PurePosixPath("periodic-report-assets", bundle_id, "manifest.json")
    }
    for asset in assets:
        if not isinstance(asset, Mapping):
            raise PeriodicBundleError("periodic_public_asset_invalid")
        grain = str(asset.get("grain"))
        relative = PurePosixPath(
            "periodic-report-assets", bundle_id, "public", grain, "poster.png"
        )
        if asset.get("relative_path") != str(relative):
            raise PeriodicBundleError("periodic_public_asset_invalid")
        path = root.joinpath(*relative.parts)
        metadata = path.lstat()
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_size != asset.get("bytes")
            or sha256_hex(path.read_bytes()) != asset.get("sha256")
        ):
            raise PeriodicBundleError("periodic_public_asset_mismatch")
        expected_files.add(relative)
    actual_files: set[PurePosixPath] = set()
    for directory, directory_names, file_names in os.walk(root, followlinks=False):
        base = Path(directory)
        if any((base / name).is_symlink() for name in directory_names):
            raise PeriodicBundleError("periodic_public_projection_symlink")
        for name in file_names:
            path = base / name
            if path.is_symlink() or not path.is_file():
                raise PeriodicBundleError("periodic_public_projection_file_invalid")
            actual_files.add(PurePosixPath(path.relative_to(root).as_posix()))
    if actual_files != expected_files:
        raise PeriodicBundleError("periodic_public_projection_file_set_invalid")
    return manifest
