#!/usr/bin/env python3
"""Build, verify and materialize the pinned frontend public-data test fixture."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import stat
from typing import Any, Mapping


SCHEMA_VERSION = "reddit-voc-frontend-public-test-fixture-v1"
POINTER_PATH = PurePosixPath("data/reddit-voc/current-release.json")
MANIFEST_NAME = "fixture-manifest.json"
V3_INSIGHTS_PUBLIC_MANIFEST_SCHEMA = "reddit_voc_insights_public_manifest_v3"
V3_INSIGHTS_PUBLIC_RECEIPT_SCHEMA = (
    "reddit_voc_insights_public_validation_receipt_v3"
)


class FixtureError(RuntimeError):
    """Raised when the frontend fixture is incomplete or unsafe."""


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _load_json(path: Path) -> Mapping[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise FixtureError(f"duplicate_json_key:{key}")
            result[key] = value
        return result

    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise FixtureError(f"fixture_source_not_regular:{path}")
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicates,
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise FixtureError(f"fixture_json_invalid:{path}") from exc
    if not isinstance(value, Mapping):
        raise FixtureError(f"fixture_json_object_required:{path}")
    return value


def _safe_relative(value: object) -> PurePosixPath:
    if not isinstance(value, str) or not value:
        raise FixtureError("fixture_path_invalid")
    relative = PurePosixPath(value)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or "\\" in value
        or relative.parts[0] != "data"
    ):
        raise FixtureError("fixture_path_invalid")
    return relative


def _collect_paths(public_root: Path) -> tuple[Mapping[str, Any], list[PurePosixPath]]:
    pointer = _load_json(public_root / Path(*POINTER_PATH.parts))
    if pointer.get("schema_version") != "reddit_voc_current_release_v2":
        raise FixtureError("current_release_schema_invalid")
    release_id = pointer.get("release_id")
    if not isinstance(release_id, str) or re.fullmatch(r"[a-z0-9_-]+", release_id) is None:
        raise FixtureError("current_release_id_invalid")
    datasets = pointer.get("datasets")
    cases = pointer.get("cases")
    if not isinstance(datasets, Mapping) or not isinstance(cases, Mapping):
        raise FixtureError("current_release_bindings_invalid")

    paths: set[PurePosixPath] = {POINTER_PATH}
    for key in ("manifest_path", "index_path"):
        paths.add(_safe_relative(cases.get(key)))
    base_manifest: Mapping[str, Any] | None = None
    for name, binding in sorted(datasets.items()):
        if not isinstance(name, str) or not isinstance(binding, Mapping):
            raise FixtureError("dataset_binding_invalid")
        manifest_relative = _safe_relative(binding.get("manifest_path"))
        manifest_path = public_root / Path(*manifest_relative.parts)
        manifest_payload = manifest_path.read_bytes()
        expected_manifest_sha = binding.get("public_manifest_sha256")
        if _sha256(manifest_payload) != expected_manifest_sha:
            raise FixtureError(f"dataset_manifest_sha256_mismatch:{name}")
        manifest = _load_json(manifest_path)
        if name == "base":
            base_manifest = manifest
        paths.add(manifest_relative)
        files = manifest.get("files")
        if not isinstance(files, Mapping):
            raise FixtureError(f"dataset_files_invalid:{name}")
        for file_name, identity in files.items():
            if not isinstance(identity, Mapping):
                raise FixtureError(f"dataset_file_identity_invalid:{name}")
            child = _safe_relative(
                (manifest_relative.parent / str(file_name)).as_posix()
            )
            payload = (public_root / Path(*child.parts)).read_bytes()
            if (
                identity.get("bytes") != len(payload)
                or identity.get("sha256") != _sha256(payload)
            ):
                raise FixtureError(f"dataset_file_identity_mismatch:{child}")
            paths.add(child)

        # The V3 insights contract test independently verifies this receipt. It is
        # intentionally outside manifest.files because it attests to the manifest
        # itself, so include and bind it explicitly instead of weakening the test.
        if name == "insights" and (
            manifest.get("schema_version") == V3_INSIGHTS_PUBLIC_MANIFEST_SCHEMA
        ):
            receipt_relative = _safe_relative(
                (manifest_relative.parent / "public-validation-receipt.json").as_posix()
            )
            receipt = _load_json(
                public_root / Path(*receipt_relative.parts)
            )
            if (
                receipt.get("schema_version")
                != V3_INSIGHTS_PUBLIC_RECEIPT_SCHEMA
                or receipt.get("privacy_safe_projection") is not True
                or receipt.get("bundle_manifest_sha256")
                != _sha256(manifest_payload)
                or receipt.get("validation_receipt_sha256")
                != manifest.get("validation_receipt_sha256")
            ):
                raise FixtureError("insights_public_validation_receipt_invalid")
            paths.add(receipt_relative)

    if base_manifest is None or base_manifest.get("privacy_safe_projection") is not True:
        raise FixtureError("base_privacy_projection_not_approved")
    privacy = base_manifest.get("privacy")
    if not isinstance(privacy, Mapping) or (
        privacy.get("raw_author_fields_present") is not False
        or privacy.get("stable_pseudonym_exposed") is not False
        or privacy.get("contact_patterns_redacted") is not True
    ):
        raise FixtureError("base_privacy_contract_invalid")
    return pointer, sorted(paths, key=lambda path: path.as_posix())


def build_fixture(*, public_root: Path, fixture_root: Path) -> Mapping[str, Any]:
    public_root = public_root.resolve(strict=True)
    fixture_root = fixture_root.absolute()
    if fixture_root.exists() or fixture_root.is_symlink():
        raise FixtureError("fixture_destination_exists")
    pointer, paths = _collect_paths(public_root)
    fixture_root.parent.mkdir(parents=True, exist_ok=True)
    staging = fixture_root.parent / f".{fixture_root.name}.building-{secrets.token_hex(8)}"
    staging.mkdir(mode=0o755)
    try:
        entries: list[dict[str, object]] = []
        for relative in paths:
            source = public_root / Path(*relative.parts)
            metadata = source.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise FixtureError(f"fixture_source_not_regular:{relative}")
            payload = source.read_bytes()
            target = staging / "files" / Path(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            target.chmod(0o644)
            entries.append(
                {
                    "path": relative.as_posix(),
                    "bytes": len(payload),
                    "sha256": _sha256(payload),
                }
            )
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "fixture_id": pointer["release_id"],
            "source_pointer_sha256": entries[0]["sha256"]
            if entries[0]["path"] == POINTER_PATH.as_posix()
            else _sha256(
                (public_root / Path(*POINTER_PATH.parts)).read_bytes()
            ),
            "privacy_contract": "privacy_safe_public_projection_no_raw_author_fields",
            "file_count": len(entries),
            "total_bytes": sum(int(entry["bytes"]) for entry in entries),
            "files": entries,
        }
        (staging / MANIFEST_NAME).write_bytes(_canonical(manifest))
        (staging / MANIFEST_NAME).chmod(0o644)
        verify_fixture(staging)
        os.rename(staging, fixture_root)
        return manifest
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def verify_fixture(fixture_root: Path) -> Mapping[str, Any]:
    fixture_root = fixture_root.resolve(strict=True)
    manifest = _load_json(fixture_root / MANIFEST_NAME)
    if set(manifest) != {
        "schema_version",
        "fixture_id",
        "source_pointer_sha256",
        "privacy_contract",
        "file_count",
        "total_bytes",
        "files",
    } or manifest.get("schema_version") != SCHEMA_VERSION:
        raise FixtureError("fixture_manifest_invalid")
    entries = manifest.get("files")
    if not isinstance(entries, list) or manifest.get("file_count") != len(entries):
        raise FixtureError("fixture_entries_invalid")
    expected: set[str] = set()
    total = 0
    for entry in entries:
        if not isinstance(entry, Mapping) or set(entry) != {"path", "bytes", "sha256"}:
            raise FixtureError("fixture_entry_invalid")
        relative = _safe_relative(entry.get("path"))
        relative_text = relative.as_posix()
        if relative_text in expected:
            raise FixtureError("fixture_entry_duplicate")
        target = fixture_root / "files" / Path(*relative.parts)
        metadata = target.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise FixtureError("fixture_entry_not_regular")
        payload = target.read_bytes()
        if entry.get("bytes") != len(payload) or entry.get("sha256") != _sha256(payload):
            raise FixtureError(f"fixture_entry_mismatch:{relative_text}")
        expected.add(relative_text)
        total += len(payload)
    actual = {
        path.relative_to(fixture_root / "files").as_posix()
        for path in (fixture_root / "files").rglob("*")
        if path.is_file()
    }
    if actual != expected or manifest.get("total_bytes") != total:
        raise FixtureError("fixture_file_set_mismatch")
    return manifest


def materialize_fixture(*, fixture_root: Path, public_root: Path) -> Mapping[str, Any]:
    fixture_root = fixture_root.resolve(strict=True)
    public_root = public_root.resolve(strict=True)
    manifest = verify_fixture(fixture_root)
    destination = public_root / "data"
    if destination.exists() or destination.is_symlink():
        raise FixtureError("public_data_destination_exists")
    staging = public_root / f".data.materializing-{secrets.token_hex(8)}"
    staging.mkdir(mode=0o755)
    try:
        for entry in manifest["files"]:
            relative = _safe_relative(entry["path"])
            source = fixture_root / "files" / Path(*relative.parts)
            target = staging / Path(*relative.parts[1:])
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            target.chmod(0o644)
        os.rename(staging, destination)
        return manifest
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--public-root", type=Path, required=True)
    build.add_argument("--fixture-root", type=Path, required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--fixture-root", type=Path, required=True)
    materialize = subparsers.add_parser("materialize")
    materialize.add_argument("--fixture-root", type=Path, required=True)
    materialize.add_argument("--public-root", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "build":
        result = build_fixture(public_root=args.public_root, fixture_root=args.fixture_root)
    elif args.command == "verify":
        result = verify_fixture(args.fixture_root)
    else:
        result = materialize_fixture(
            fixture_root=args.fixture_root,
            public_root=args.public_root,
        )
    print(
        json.dumps(
            {
                "status": "passed",
                "fixture_id": result["fixture_id"],
                "file_count": result["file_count"],
                "total_bytes": result["total_bytes"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except FixtureError as exc:
        print(f"frontend_test_fixture_failed:{exc}", file=os.sys.stderr)
        raise SystemExit(1) from exc
