#!/usr/bin/env python3
"""Verify local, GitHub and production Reddit VOC version identities.

The default check is local-only.  GitHub and production checks require explicit
flags because they perform read-only network calls.  No credential file content
is opened by the production observer; it records only report-env metadata.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCK = ROOT / "config/production-version-lock.json"


class ConsistencyError(RuntimeError):
    """Raised when one version identity differs from the reviewed lock."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> Mapping[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ConsistencyError(f"duplicate_json_key:{key}")
            result[key] = value
        return result

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicates,
        )
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ConsistencyError(f"invalid_json:{path}") from exc
    if not isinstance(value, Mapping):
        raise ConsistencyError(f"invalid_json_object:{path}")
    return value


def _require_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ConsistencyError(f"invalid_mapping:{label}")
    return value


def _run(
    argv: list[str],
    *,
    cwd: Path = ROOT,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        argv,
        cwd=cwd,
        input=input_text,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise ConsistencyError(
            f"command_failed:{argv[0]}:{completed.returncode}:{detail}"
        )
    return completed


def verify_local(lock: Mapping[str, Any]) -> Mapping[str, Any]:
    daily = _require_mapping(lock.get("daily_report"), "daily_report")
    insights = _require_mapping(lock.get("insights_site"), "insights_site")
    image_id = str(daily.get("image_id", ""))
    if re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None:
        raise ConsistencyError("daily_image_id_invalid")

    for section, label in ((daily, "daily"), (insights, "insights")):
        relative = section.get("manifest_path")
        expected = section.get("manifest_sha256")
        if not isinstance(relative, str) or Path(relative).is_absolute():
            raise ConsistencyError(f"{label}_manifest_path_invalid")
        manifest_path = ROOT / relative
        if not manifest_path.is_file() or manifest_path.is_symlink():
            raise ConsistencyError(f"{label}_manifest_missing")
        if _sha256(manifest_path) != expected:
            raise ConsistencyError(f"{label}_manifest_sha256_mismatch")

    with tempfile.TemporaryDirectory(prefix="reddit-voc-version-") as temporary:
        output_root = Path(temporary) / "releases"
        completed = _run(
            [
                sys.executable,
                str(ROOT / "scripts/build_daily_report_release.py"),
                "build",
                "--source-root",
                str(ROOT),
                "--destination-root",
                str(output_root),
                "--image-id",
                image_id,
            ]
        )
        fields = dict(
            line.split("=", 1)
            for line in completed.stdout.splitlines()
            if "=" in line
        )
        if fields.get("release_sha256") != daily.get("release_sha256"):
            raise ConsistencyError("daily_source_release_mismatch")
        if fields.get("manifest_sha256") != daily.get("manifest_sha256"):
            raise ConsistencyError("daily_source_manifest_mismatch")

    launcher = ROOT / "scripts/server_daily_report.sh"
    if _sha256(launcher) != daily.get("launcher_sha256"):
        raise ConsistencyError("daily_launcher_sha256_mismatch")

    site_manifest = _load_json(ROOT / str(insights["manifest_path"]))
    inventory = _require_mapping(site_manifest.get("dist_inventory"), "dist_inventory")
    stable = _require_mapping(site_manifest.get("stable_identity"), "stable_identity")
    expected_site = {
        "release_sha256": insights.get("release_sha256"),
        "dist_inventory_sha256": insights.get("dist_inventory_sha256"),
        "dist_file_count": insights.get("dist_file_count"),
        "dist_total_bytes": insights.get("dist_total_bytes"),
        "runtime_contract": insights.get("runtime_contract"),
        "data_release_id": insights.get("data_release_id"),
        "data_pointer_sha256": insights.get("data_pointer_sha256"),
    }
    actual_site = {
        "release_sha256": site_manifest.get("release_sha256"),
        "dist_inventory_sha256": inventory.get("inventory_sha256"),
        "dist_file_count": inventory.get("file_count"),
        "dist_total_bytes": inventory.get("total_bytes"),
        "runtime_contract": stable.get("runtime_contract"),
        "data_release_id": stable.get("data_release_id"),
        "data_pointer_sha256": stable.get("data_pointer_sha256"),
    }
    if actual_site != expected_site:
        raise ConsistencyError("insights_manifest_identity_mismatch")

    return {
        "daily_release_sha256": daily["release_sha256"],
        "daily_manifest_sha256": daily["manifest_sha256"],
        "insights_release_sha256": insights["release_sha256"],
        "insights_source_alignment": insights["source_alignment"],
    }


def verify_github(lock: Mapping[str, Any]) -> Mapping[str, str]:
    github = _require_mapping(lock.get("github"), "github")
    repository = str(github.get("repository", ""))
    branch = str(github.get("default_branch", ""))
    if repository != "https://github.com/zjgulai/Reddit_VOC.git" or branch != "main":
        raise ConsistencyError("github_lock_invalid")

    status = _run(["git", "status", "--porcelain=v1", "--untracked-files=all"])
    if status.stdout:
        raise ConsistencyError("git_worktree_not_clean")
    local_branch = _run(["git", "branch", "--show-current"]).stdout.strip()
    if local_branch != branch:
        raise ConsistencyError("git_branch_mismatch")
    origin = _run(["git", "remote", "get-url", "origin"]).stdout.strip()
    accepted_origins = {
        repository,
        "git@github.com:zjgulai/Reddit_VOC.git",
    }
    if origin not in accepted_origins:
        raise ConsistencyError("git_origin_mismatch")
    head = _run(["git", "rev-parse", "HEAD"]).stdout.strip()
    remote = _run(["git", "ls-remote", "--heads", "origin", branch]).stdout.strip()
    fields = remote.split()
    if len(fields) != 2 or fields[0] != head or fields[1] != f"refs/heads/{branch}":
        raise ConsistencyError("github_head_mismatch")
    return {"branch": branch, "commit": head, "origin": origin}


_REMOTE_OBSERVER = r"""
import hashlib
import json
import os
from pathlib import Path

daily_root = Path('/opt/reddit-voc-daily-report')
site_root = Path('/opt/reddit-voc-insights-site')
data_root = Path('/opt/reddit-voc-insights-data')
report_env = Path('/home/ubuntu/.reddit-voc/secrets/reddit-voc-report.env')

def target(root):
    current = root / 'current'
    if not current.is_symlink():
        raise SystemExit('current_not_symlink')
    return os.readlink(current)

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

daily_target = target(daily_root)
site_target = target(site_root)
data_target = target(data_root)
daily_manifest_path = daily_root / daily_target / 'report-release-manifest.json'
site_manifest_path = site_root / site_target / 'release-manifest.json'
daily = json.loads(daily_manifest_path.read_text(encoding='utf-8'))
site = json.loads(site_manifest_path.read_text(encoding='utf-8'))
inventory = site['dist_inventory']
stable = site['stable_identity']
metadata = report_env.lstat()
cron = Path('/etc/cron.d/reddit-voc-site')
launcher = daily_root / daily_target / 'scripts/server_daily_report.sh'
print(json.dumps({
    'daily': {
        'current_target': daily_target,
        'release_sha256': daily['release_sha256'],
        'manifest_sha256': sha(daily_manifest_path),
        'image_id': daily['image_id'],
        'entry_count': len(daily['entries']),
        'launcher_sha256': sha(launcher),
        'cron_sha256': sha(cron),
        'report_env_metadata': {
            'inode': metadata.st_ino,
            'uid': metadata.st_uid,
            'gid': metadata.st_gid,
            'mode': f'{metadata.st_mode & 0o777:04o}',
            'size': metadata.st_size,
        },
    },
    'insights': {
        'current_target': site_target,
        'release_sha256': site['release_sha256'],
        'manifest_sha256': sha(site_manifest_path),
        'dist_inventory_sha256': inventory['inventory_sha256'],
        'dist_file_count': inventory['file_count'],
        'dist_total_bytes': inventory['total_bytes'],
        'runtime_contract': stable['runtime_contract'],
        'data_current_target': data_target,
        'data_release_id': stable['data_release_id'],
        'data_pointer_sha256': stable['data_pointer_sha256'],
    },
}, sort_keys=True, separators=(',', ':')))
"""


def verify_production(
    lock: Mapping[str, Any],
    *,
    host: str,
    identity_file: Path,
    known_hosts: Path,
) -> Mapping[str, Any]:
    if host != f"ubuntu@{lock.get('production_host')}":
        raise ConsistencyError("production_host_mismatch")
    for path, label in ((identity_file, "identity"), (known_hosts, "known_hosts")):
        if not path.is_file() or path.is_symlink():
            raise ConsistencyError(f"production_{label}_invalid")
    completed = _run(
        [
            "ssh",
            "-i",
            str(identity_file),
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            f"UserKnownHostsFile={known_hosts}",
            host,
            "sudo -n /usr/bin/python3 -",
        ],
        input_text=_REMOTE_OBSERVER,
    )
    try:
        observed = json.loads(completed.stdout)
    except ValueError as exc:
        raise ConsistencyError("production_observation_invalid") from exc
    expected_daily = dict(_require_mapping(lock.get("daily_report"), "daily_report"))
    expected_insights = dict(_require_mapping(lock.get("insights_site"), "insights_site"))
    for key in ("manifest_path", "source_alignment"):
        expected_daily.pop(key, None)
        expected_insights.pop(key, None)
    expected_daily.pop("release_sha256", None)
    expected_daily["release_sha256"] = lock["daily_report"]["release_sha256"]
    if observed.get("daily") != expected_daily:
        raise ConsistencyError("production_daily_mismatch")
    if observed.get("insights") != expected_insights:
        raise ConsistencyError("production_insights_mismatch")
    return _require_mapping(observed, "production_observation")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--check-github", action="store_true")
    parser.add_argument("--production-host")
    parser.add_argument("--identity-file", type=Path)
    parser.add_argument("--known-hosts", type=Path)
    args = parser.parse_args()
    lock = _load_json(args.lock.resolve(strict=True))
    if lock.get("schema_version") != "reddit-voc-production-version-lock-v1":
        raise ConsistencyError("version_lock_schema_invalid")

    result: dict[str, Any] = {"local": verify_local(lock)}
    if args.check_github:
        result["github"] = verify_github(lock)
    production_requested = any(
        value is not None
        for value in (args.production_host, args.identity_file, args.known_hosts)
    )
    if production_requested:
        if not all((args.production_host, args.identity_file, args.known_hosts)):
            raise ConsistencyError("production_arguments_incomplete")
        result["production"] = verify_production(
            lock,
            host=args.production_host,
            identity_file=args.identity_file.resolve(strict=True),
            known_hosts=args.known_hosts.resolve(strict=True),
        )
    print(json.dumps({"status": "passed", **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ConsistencyError as exc:
        print(f"version_consistency_failed:{exc}", file=sys.stderr)
        raise SystemExit(1) from exc
