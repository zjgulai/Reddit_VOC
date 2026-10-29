from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Mapping


_RUNTIME_FILES = [
    "src/reddit_voc/__init__.py",
    "src/reddit_voc/adapters.py",
    "src/reddit_voc/analyzer.py",
    "src/reddit_voc/browser_profile.py",
    "src/reddit_voc/browser_runner.py",
    "src/reddit_voc/cli.py",
    "src/reddit_voc/collector.py",
    "src/reddit_voc/content_entity.py",
    "src/reddit_voc/daily_report.py",
    "src/reddit_voc/dingtalk.py",
    "src/reddit_voc/exporter.py",
    "src/reddit_voc/keywords.py",
    "src/reddit_voc/models.py",
    "src/reddit_voc/ops.py",
    "src/reddit_voc/permalink.py",
    "src/reddit_voc/preflight.py",
    "src/reddit_voc/raw_artifacts.py",
    "src/reddit_voc/report_contracts.py",
    "src/reddit_voc/report_source_state.py",
    "src/reddit_voc/deepseek_client.py",
    "src/reddit_voc/translation_pipeline.py",
    "src/reddit_voc/prepared_bundle.py",
    "src/reddit_voc/prepared_report.py",
    "src/reddit_voc/daily_report_delivery.py",
    "src/reddit_voc/provider_attempt_ledger.py",
    "src/reddit_voc/search_config.py",
    "src/reddit_voc/storage.py",
    "src/reddit_voc/tikhub.py",
    "src/reddit_voc/time_window.py",
    "scripts/run_daily_report.sh",
    "scripts/server_daily_report.sh",
    "scripts/report_runtime_smoke.py",
    "config/translation_terms.json",
    "config/prompts/deepseek-translation-v1.txt",
    "config/prompts/deepseek-semantic-validator-v1.txt",
    "config/schemas/daily-translation-manifest-v1.schema.json",
    "config/schemas/daily-translation-attempt-v1.schema.json",
    "config/schemas/daily-prepared-bundle-index-v1.schema.json",
]
_ADMIN_FILES = [
    "scripts/build_daily_report_release.py",
    "scripts/report_control.py",
    "scripts/report_noninterference.py",
    "scripts/server_daily_report_admin.sh",
    "scripts/server_update_daily_report_runtime_env.sh",
]
_TEST_FILES = [
    "tests/__init__.py",
    "tests/fixtures/g6r0-task32aa-daily-live-policy-b22.json",
    "tests/fixtures/g6r5-dual-daily-live-policy-20260822-20270821.json",
    "tests/fixtures/reddit_thread_browser_json.json",
    "webapp/__init__.py",
    "webapp/app.py",
    "tests/test_report_contracts.py",
    "tests/test_deepseek_client.py",
    "tests/test_translation_pipeline.py",
    "tests/test_prepared_report.py",
    "tests/test_daily_report.py",
    "tests/test_dingtalk_delivery.py",
    "tests/test_daily_report_delivery.py",
    "tests/test_dual_destination_delivery.py",
    "tests/test_dual_destination_integration.py",
    "tests/test_provider_attempt_ledger.py",
    "tests/test_daily_report_wrapper.py",
    "tests/test_daily_report_launcher.py",
    "tests/test_daily_report_release.py",
    "tests/test_daily_report_ops.py",
    "tests/test_webapp.py",
]
RELEASE_FILE_ROLES: dict[str, str] = {
    **{path: "runtime" for path in _RUNTIME_FILES},
    **{path: "admin" for path in _ADMIN_FILES},
    **{path: "test" for path in _TEST_FILES},
}


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256(payload: bytes) -> str:
    import hashlib

    return hashlib.sha256(payload).hexdigest()


def build_release(
    *, source_root: Path, destination_root: Path, image_id: str
) -> Path:
    if re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None:
        raise ValueError("release_image_id_invalid")
    source_root = Path(source_root).resolve(strict=True)
    destination_root = Path(destination_root)
    destination_root.mkdir(parents=True, exist_ok=True)
    if destination_root.is_symlink():
        raise RuntimeError("release_destination_symlink")
    temporary = destination_root / f".building-{secrets.token_hex(16)}"
    temporary.mkdir(mode=0o700)
    try:
        entries: list[dict[str, object]] = []
        for relative in sorted(RELEASE_FILE_ROLES):
            source = source_root / relative
            metadata = source.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise RuntimeError("release_source_not_regular")
            payload = source.read_bytes()
            mode = 0o755 if relative.startswith("scripts/") else 0o644
            target = temporary / relative
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
            target.write_bytes(payload)
            target.chmod(mode)
            entries.append(
                {
                    "path": relative,
                    "role": RELEASE_FILE_ROLES[relative],
                    "mode": f"{mode:04o}",
                    "size": len(payload),
                    "sha256": "sha256:" + _sha256(payload),
                }
            )
        unsigned = {
            "schema_version": "report-release-manifest-v1",
            "image_id": image_id,
            "entries": entries,
        }
        release_sha256 = _sha256(_canonical(unsigned))
        manifest = {**unsigned, "release_sha256": release_sha256}
        manifest_path = temporary / "report-release-manifest.json"
        manifest_path.write_bytes(_canonical(manifest))
        manifest_path.chmod(0o644)
        final = destination_root / release_sha256
        if final.exists():
            verified = verify_release(final)
            if verified["image_id"] != image_id:
                raise RuntimeError("release_existing_conflict")
            shutil.rmtree(temporary)
            return final
        os.rename(temporary, final)
        _fsync_directory(destination_root)
        verify_release(final)
        return final
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise


def verify_release(release_dir: Path) -> Mapping[str, object]:
    release_dir = Path(release_dir)
    metadata = release_dir.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise RuntimeError("release_directory_invalid")
    manifest_path = release_dir / "report-release-manifest.json"
    manifest_metadata = manifest_path.lstat()
    if stat.S_ISLNK(manifest_metadata.st_mode) or not stat.S_ISREG(manifest_metadata.st_mode):
        raise RuntimeError("release_manifest_invalid")
    manifest = _load_json_strict(manifest_path.read_bytes())
    if set(manifest) != {"schema_version", "image_id", "entries", "release_sha256"}:
        raise RuntimeError("release_manifest_invalid")
    if manifest.get("schema_version") != "report-release-manifest-v1":
        raise RuntimeError("release_manifest_invalid")
    image_id = manifest.get("image_id")
    if not isinstance(image_id, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None:
        raise RuntimeError("release_manifest_invalid")
    release_sha = manifest.get("release_sha256")
    if not isinstance(release_sha, str) or re.fullmatch(r"[0-9a-f]{64}", release_sha) is None:
        raise RuntimeError("release_manifest_invalid")
    unsigned = {key: manifest[key] for key in ("schema_version", "image_id", "entries")}
    if _sha256(_canonical(unsigned)) != release_sha or release_dir.name != release_sha:
        raise RuntimeError("release_sha256_mismatch")
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        raise RuntimeError("release_manifest_invalid")
    expected_paths = sorted(RELEASE_FILE_ROLES)
    actual_paths: list[str] = []
    for entry in entries:
        if not isinstance(entry, Mapping) or set(entry) != {"path", "role", "mode", "size", "sha256"}:
            raise RuntimeError("release_manifest_invalid")
        relative = entry.get("path")
        if not isinstance(relative, str) or relative not in RELEASE_FILE_ROLES:
            raise RuntimeError("release_manifest_path_invalid")
        if Path(relative).is_absolute() or ".." in Path(relative).parts or "\\" in relative:
            raise RuntimeError("release_manifest_path_invalid")
        if entry.get("role") != RELEASE_FILE_ROLES[relative]:
            raise RuntimeError("release_entry_mismatch")
        target = release_dir / relative
        target_metadata = target.lstat()
        if stat.S_ISLNK(target_metadata.st_mode):
            raise RuntimeError("release_symlink_forbidden")
        if not stat.S_ISREG(target_metadata.st_mode):
            raise RuntimeError("release_entry_mismatch")
        payload = target.read_bytes()
        if (
            entry.get("mode") != f"{stat.S_IMODE(target_metadata.st_mode):04o}"
            or entry.get("size") != len(payload)
            or entry.get("sha256") != "sha256:" + _sha256(payload)
        ):
            raise RuntimeError("release_entry_mismatch")
        actual_paths.append(relative)
    if actual_paths != expected_paths or len(actual_paths) != len(set(actual_paths)):
        raise RuntimeError("release_manifest_entries_invalid")
    actual_files: set[str] = set()
    actual_directories: set[str] = {""}
    for current, directories, files in os.walk(release_dir, followlinks=False):
        current_path = Path(current)
        for name in directories:
            path = current_path / name
            if path.is_symlink():
                raise RuntimeError("release_symlink_forbidden")
            actual_directories.add(path.relative_to(release_dir).as_posix())
        for name in files:
            path = current_path / name
            if path.is_symlink():
                raise RuntimeError("release_symlink_forbidden")
            relative = path.relative_to(release_dir).as_posix()
            if relative != "report-release-manifest.json":
                actual_files.add(relative)
    if actual_files != set(expected_paths):
        raise RuntimeError("release_file_set_mismatch")
    expected_directories = {""}
    for relative in expected_paths:
        parent = Path(relative).parent
        while parent != Path("."):
            expected_directories.add(parent.as_posix())
            parent = parent.parent
    if actual_directories != expected_directories:
        raise RuntimeError("release_directory_set_mismatch")
    return manifest


def verify_release_imports(
    release_dir: Path,
    *,
    python_executable: Path = Path(sys.executable),
    forbidden_root: Path | None = None,
) -> Mapping[str, object]:
    release = Path(release_dir).resolve(strict=True)
    manifest = verify_release(release)
    executable = Path(python_executable).resolve(strict=True)
    forbidden = (
        str(Path(forbidden_root).resolve(strict=True))
        if forbidden_root is not None
        else ""
    )
    probe = r'''
import json
import os
import sys
from pathlib import Path

release = Path(sys.argv[1]).resolve(strict=True)
forbidden_text = sys.argv[2]
forbidden = Path(forbidden_text).resolve(strict=True) if forbidden_text else None
release_src = release / "src"
existing = [path for path in sys.path if path and Path(path).resolve() not in {Path.cwd().resolve()}]
sys.path[:] = [str(release_src), str(release), *existing]

import reddit_voc.cli
import reddit_voc.prepared_bundle
import reddit_voc.report_contracts

manifest = json.loads((release / "report-release-manifest.json").read_text(encoding="utf-8"))
runtime_entries = {
    entry["path"]
    for entry in manifest["entries"]
    if entry.get("role") == "runtime"
}
verified = []
for name, module in sorted(sys.modules.items()):
    if name != "reddit_voc" and not name.startswith("reddit_voc."):
        continue
    module_file = getattr(module, "__file__", None)
    if not isinstance(module_file, str):
        raise SystemExit("project_module_without_file")
    path = Path(module_file).resolve(strict=True)
    try:
        relative = path.relative_to(release).as_posix()
    except ValueError:
        raise SystemExit("repository_fallback_detected")
    if relative not in runtime_entries:
        raise SystemExit("runtime_module_not_manifested")
    if forbidden is not None:
        try:
            path.relative_to(forbidden)
        except ValueError:
            pass
        else:
            raise SystemExit("repository_fallback_detected")
    verified.append(name)
print(json.dumps({
    "status": "ok",
    "repository_fallback": False,
    "verified_module_count": len(verified),
    "release_sha256": manifest["release_sha256"],
}, sort_keys=True, separators=(",", ":")))
'''
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    environment.update(
        {
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    completed = subprocess.run(
        [str(executable), "-c", probe, str(release), forbidden],
        cwd=release,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    if completed.returncode != 0:
        raise RuntimeError("release_import_closure_invalid")
    try:
        evidence = json.loads(completed.stdout)
    except (UnicodeDecodeError, ValueError) as exc:
        raise RuntimeError("release_import_closure_invalid") from exc
    if (
        not isinstance(evidence, Mapping)
        or evidence.get("status") != "ok"
        or evidence.get("repository_fallback") is not False
        or evidence.get("release_sha256") != manifest["release_sha256"]
    ):
        raise RuntimeError("release_import_closure_invalid")
    return evidence


def _load_json_strict(payload: bytes) -> Mapping[str, object]:
    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in values:
            if key in result:
                raise ValueError("duplicate")
            result[key] = value
        return result

    try:
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeDecodeError, ValueError) as exc:
        raise RuntimeError("release_manifest_invalid") from exc
    if not isinstance(value, Mapping):
        raise RuntimeError("release_manifest_invalid")
    return value


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--source-root", type=Path, required=True)
    build.add_argument("--destination-root", type=Path, required=True)
    build.add_argument("--image-id", required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--release-dir", type=Path, required=True)
    verify_imports = subparsers.add_parser("verify-imports")
    verify_imports.add_argument("--release-dir", type=Path, required=True)
    verify_imports.add_argument("--python-executable", type=Path, default=Path(sys.executable))
    verify_imports.add_argument("--forbidden-root", type=Path)
    args = parser.parse_args()
    if args.command == "build":
        release = build_release(
            source_root=args.source_root,
            destination_root=args.destination_root,
            image_id=args.image_id,
        )
        manifest = verify_release(release)
    elif args.command == "verify":
        release = args.release_dir
        manifest = verify_release(release)
    else:
        release = args.release_dir
        manifest = verify_release(release)
        evidence = verify_release_imports(
            release,
            python_executable=args.python_executable,
            forbidden_root=args.forbidden_root,
        )
    manifest_sha256 = _sha256(
        Path(release).joinpath("report-release-manifest.json").read_bytes()
    )
    print(f"release_sha256={manifest['release_sha256']}")
    print(f"manifest_sha256={manifest_sha256}")
    print(f"release_dir={release}")
    if args.command == "verify-imports":
        print(f"verified_module_count={evidence['verified_module_count']}")
        print("repository_fallback=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
