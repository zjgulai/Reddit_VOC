#!/usr/bin/env python3
"""Emit one read-only Reddit VOC production baseline receipt.

This program is intended to run on the production host through SSH stdin.  It
only invokes read-only inspection commands and exits before emitting evidence
unless the collector, translation service, and active insights release remain
stable throughout the observation window.
"""

from __future__ import annotations

from datetime import datetime, timezone
import fcntl
from hashlib import sha256
import io
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import stat
import subprocess
import sys
import tarfile
import time
from typing import Any


DEPLOY_ROOT = Path("/opt/reddit-voc-insights-site")
CURRENT = DEPLOY_ROOT / "current"
DATA_ROOT = Path("/opt/reddit-voc-insights-data")
NGINX_CONFIG = Path("/opt/ai-video/deploy/lighthouse/nginx.conf")
CRON_FILE = Path("/etc/cron.d/reddit-voc-site")
DATABASE = Path("/opt/reddit-voc-site/data/reddit_voc_daily.sqlite3")
REPORT_POINTER = Path("/opt/reddit-voc-report/current")
OBSERVER_RUNTIME_CONTRACT = "reddit_voc_production_baseline_observer_v5"
OBSERVER_RUNTIME_SHA256 = sha256(OBSERVER_RUNTIME_CONTRACT.encode("ascii")).hexdigest()
LOCK_PATHS = {
    "promotion": DEPLOY_ROOT / ".promotion.lock",
    "deploy": DEPLOY_ROOT / ".deploy.lock",
    "data_release": DATA_ROOT / "locks/data-release.lock",
}


def command(*argv: str) -> str:
    return subprocess.run(
        argv,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def command_bytes(*argv: str) -> bytes:
    return subprocess.run(argv, check=True, capture_output=True).stdout


def docker_value(container: str, template: str) -> str:
    return command("docker", "inspect", "-f", template, container)


def file_identity(path: Path) -> str:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return "absent"
    return f"{stat.st_mtime_ns}:{stat.st_size}:{stat.st_ino}"


def sha256_file(path: Path, *, sudo: bool = False) -> str:
    argv = ("sudo", "-n", "sha256sum", str(path)) if sudo else ("sha256sum", str(path))
    return command(*argv).split()[0]


def health(container: str) -> str:
    return docker_value(
        container,
        "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}",
    )


def container_inventory(*, protected_only: bool = False) -> list[str]:
    output = command("docker", "container", "ls", "-a", "-q", "--no-trunc")
    identifiers = sorted(line for line in output.splitlines() if line)
    if not identifiers:
        return []
    inspected = json.loads(command("docker", "inspect", *identifiers))
    rows: list[str] = []
    for value in inspected:
        name = value.get("Name")
        if protected_only and (
            name == "/reddit_voc_insights_web"
            or (
                isinstance(name, str)
                and name.startswith("/reddit_voc_insights_candidate_")
            )
        ):
            continue
        state = value.get("State") or {}
        rows.append(
            json.dumps(
                {
                    "container_id": value.get("Id"),
                    "finished_at": state.get("FinishedAt"),
                    "name": name,
                    "restart_count": value.get("RestartCount"),
                    "started_at": state.get("StartedAt"),
                    "state": state.get("Status"),
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    return sorted(rows)


def named_running_count(prefix: str) -> int:
    output = command("docker", "ps", "--format", "{{.Names}}")
    return sum(1 for name in output.splitlines() if name.startswith(prefix))


def named_container_count(prefix: str) -> int:
    output = command("docker", "ps", "-a", "--format", "{{.Names}}")
    return sum(1 for name in output.splitlines() if name.startswith(prefix))


def listener_count(port: int) -> int:
    output = command("ss", "-H", "-ltn")
    return sum(1 for line in output.splitlines() if line.split()[3].rsplit(":", 1)[-1] == str(port))


def listener_addresses(port: int) -> list[str]:
    output = command("ss", "-H", "-ltn")
    return sorted(
        {
            line.split()[3]
            for line in output.splitlines()
            if line.split()[3].rsplit(":", 1)[-1] == str(port)
        }
    )


def expected_image_id_from_archive(path: Path, image_reference: str) -> str:
    metadata = path.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or metadata.st_mode & 0o022
    ):
        raise SystemExit("production image archive is unsafe")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        before = os.fstat(descriptor)
        payload = bytearray()
        while chunk := os.read(descriptor, 1024 * 1024):
            payload.extend(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if (
        (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        or (before.st_dev, before.st_ino)
        != (metadata.st_dev, metadata.st_ino)
        or len(payload) != before.st_size
    ):
        raise SystemExit("production image archive changed while it was read")
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as archive:
        members = archive.getmembers()
        names = [member.name for member in members]
        if len(names) != len(set(names)) or names.count("manifest.json") != 1:
            raise SystemExit("production image archive manifest is ambiguous")
        manifest_member = archive.getmember("manifest.json")
        if not manifest_member.isfile():
            raise SystemExit("production image archive manifest is unsafe")
        manifest_stream = archive.extractfile(manifest_member)
        if manifest_stream is None:
            raise SystemExit("production image archive manifest is unreadable")
        manifest = json.loads(manifest_stream.read())
        if not isinstance(manifest, list) or len(manifest) != 1:
            raise SystemExit("production image archive cardinality mismatch")
        record = manifest[0]
        if not isinstance(record, dict):
            raise SystemExit("production image archive identity is invalid")
        config_name = record.get("Config")
        tags = record.get("RepoTags")
        if not isinstance(config_name, str):
            raise SystemExit("production image archive identity mismatch")
        config_match = re.fullmatch(
            r"(?:([a-f0-9]{64})\.json|blobs/sha256/([a-f0-9]{64}))",
            config_name,
        )
        if (
            config_match is None
            or tags != [image_reference]
            or names.count(config_name) != 1
        ):
            raise SystemExit("production image archive identity mismatch")
        config_member = archive.getmember(config_name)
        if not config_member.isfile():
            raise SystemExit("production image archive config is unsafe")
        config_stream = archive.extractfile(config_member)
        if config_stream is None:
            raise SystemExit("production image archive config is unreadable")
        config_payload = config_stream.read()
    digest = sha256(config_payload).hexdigest()
    assert config_match is not None
    if digest != (config_match.group(1) or config_match.group(2)):
        raise SystemExit("production image archive config digest mismatch")
    return f"sha256:{digest}"


def validate_insights_runtime(
    container: dict[str, Any],
    network: dict[str, Any],
    *,
    release_sha256: str,
    expected_image_id: str,
) -> dict[str, object]:
    """Validate and return the exact production runtime evidence surface."""

    config = container.get("Config") or {}
    host = container.get("HostConfig") or {}
    state = container.get("State") or {}
    network_settings = container.get("NetworkSettings") or {}
    if not all(isinstance(value, dict) for value in (config, host, state, network_settings)):
        raise SystemExit("production insights runtime inspect is invalid")
    labels = config.get("Labels") or {}
    health = state.get("Health") or {}
    mounts = container.get("Mounts") or []
    networks = network_settings.get("Networks") or {}
    ports = network_settings.get("Ports") or {}
    bindings = host.get("PortBindings") or {}
    tmpfs = host.get("Tmpfs") or {}
    options = network.get("Options") or {}
    if not all(
        isinstance(value, dict)
        for value in (labels, health, networks, ports, bindings, tmpfs, options)
    ) or not isinstance(mounts, list):
        raise SystemExit("production insights runtime inspect is invalid")
    tmpfs_options = sorted(
        item for item in str(tmpfs.get("/tmp", "")).split(",") if item
    )
    expected_tmpfs = sorted(
        {
            "rw",
            "noexec",
            "nosuid",
            "nodev",
            "size=32m",
            "uid=101",
            "gid=101",
            "mode=1777",
        }
    )
    expected_binding = [{"HostIp": "172.20.0.1", "HostPort": "18338"}]
    image_id = container.get("Image")
    network_id = network.get("Id")
    restart_policy = host.get("RestartPolicy") or {}
    log_config = host.get("LogConfig") or {}
    if not isinstance(restart_policy, dict) or not isinstance(log_config, dict):
        raise SystemExit("production insights runtime inspect is invalid")
    if (
        config.get("Image") != f"reddit-voc-insights:{release_sha256}"
        or image_id != expected_image_id
        or config.get("User") != "101:101"
        or config.get("Entrypoint") != ["/docker-entrypoint.sh"]
        or config.get("Cmd") != ["nginx", "-g", "daemon off;"]
        or config.get("WorkingDir") != "/"
        or config.get("OpenStdin") is not False
        or config.get("StdinOnce") is not False
        or config.get("Tty") is not False
        or set(config.get("Env") or [])
        != {
            "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "NGINX_VERSION=1.29.4",
            "PKG_RELEASE=1",
            "DYNPKG_RELEASE=1",
            "NJS_VERSION=0.9.4",
            "NJS_RELEASE=1",
            "NGINX_ENTRYPOINT_QUIET_LOGS=1",
        }
        or config.get("Healthcheck")
        != {
            "Test": [
                "CMD-SHELL",
                "wget -q -O /dev/null http://127.0.0.1:8080/healthz && "
                "wget -q -O /dev/null "
                "http://127.0.0.1:8080/data/reddit-voc/current-release.json",
            ],
            "Interval": 10_000_000_000,
            "Timeout": 3_000_000_000,
            "Retries": 6,
            "StartPeriod": 5_000_000_000,
        }
        or labels.get("com.reddit-voc.component") != "insights-site"
        or labels.get("com.reddit-voc.release") != release_sha256
        or state.get("Running") is not True
        or health.get("Status") != "healthy"
        or host.get("ReadonlyRootfs") is not True
        or host.get("Privileged") is not False
        or host.get("PidMode") != ""
        or host.get("IpcMode") != "private"
        or host.get("UTSMode") != ""
        or host.get("UsernsMode") != ""
        or host.get("Devices") not in (None, [])
        or host.get("DeviceRequests") not in (None, [])
        or host.get("DeviceCgroupRules") not in (None, [])
        or host.get("Sysctls") not in (None, {})
        or host.get("Ulimits") not in (None, [])
        or host.get("Runtime") not in ("", "runc")
        or host.get("CapAdd") not in (None, [])
        or host.get("CapDrop") != ["ALL"]
        or host.get("SecurityOpt") != ["no-new-privileges:true"]
        or host.get("Init") is not True
        or host.get("PidsLimit") != 100
        or host.get("Memory") != 268435456
        or host.get("NanoCpus") != 500000000
        or restart_policy.get("Name") != "unless-stopped"
        or log_config
        != {
            "Type": "json-file",
            "Config": {"max-file": "3", "max-size": "10m"},
        }
        or tmpfs_options != expected_tmpfs
        or host.get("NetworkMode") != "reddit_voc_insights_net"
        or set(networks) != {"reddit_voc_insights_net"}
        or not isinstance(networks.get("reddit_voc_insights_net"), dict)
        or len(mounts) != 1
        or ports != {"8080/tcp": expected_binding}
        or bindings != {"8080/tcp": expected_binding}
        or network.get("Name") != "reddit_voc_insights_net"
        or network.get("Driver") != "bridge"
        or network.get("Internal") is not False
        or options.get("com.docker.network.bridge.enable_ip_masquerade")
        != "false"
        or options.get("com.docker.network.bridge.enable_icc") != "false"
        or not isinstance(network_id, str)
        or re.fullmatch(r"[a-f0-9]{64}", network_id) is None
        or networks["reddit_voc_insights_net"].get("NetworkID") != network_id
    ):
        raise SystemExit("production insights runtime contract is invalid")
    mount = mounts[0]
    if not isinstance(mount, dict) or (
        mount.get("Type") != "bind"
        or mount.get("Source") != str(DATA_ROOT)
        or mount.get("Destination") != "/srv/reddit-voc-data"
        or mount.get("RW") is not False
        or mount.get("Propagation") != "rprivate"
    ):
        raise SystemExit("production insights runtime mount contract is invalid")
    return {
        "cap_add": [],
        "cap_drop": ["ALL"],
        "collector_listener_reachable": False,
        "command": ["nginx", "-g", "daemon off;"],
        "component_label": "insights-site",
        "device_access": False,
        "entrypoint": ["/docker-entrypoint.sh"],
        "host_port_binding": expected_binding[0],
        "image_id": image_id,
        "image_archive_config_digest_verified": True,
        "image_archive_path": (
            f"/opt/reddit-voc-insights-site/releases/{release_sha256}/"
            f"reddit-voc-insights-{release_sha256}.tar"
        ),
        "image_reference": f"reddit-voc-insights:{release_sha256}",
        "image_tag_id_verified": True,
        "init": True,
        "memory_bytes": 268435456,
        "mount": {
            "destination": "/srv/reddit-voc-data",
            "propagation": "rprivate",
            "read_only": True,
            "source": str(DATA_ROOT),
            "type": "bind",
        },
        "nano_cpus": 500000000,
        "network": {
            "driver": "bridge",
            "icc": False,
            "id": network_id,
            "internal": False,
            "ip_masquerade": False,
            "name": "reddit_voc_insights_net",
        },
        "network_mode": "reddit_voc_insights_net",
        "network_attachment_id_verified": True,
        "no_new_privileges": True,
        "pids_limit": 100,
        "pid_namespace": "private",
        "privileged": False,
        "read_only_rootfs": True,
        "restart_policy": "unless-stopped",
        "runtime": host.get("Runtime") or "runc",
        "tmpfs_options": expected_tmpfs,
        "user": "101:101",
    }


def _lock_identity(path: Path, descriptor: int, *, expected_uid: int) -> dict[str, object]:
    path_metadata = path.lstat()
    descriptor_metadata = os.fstat(descriptor)
    if (
        not stat.S_ISREG(path_metadata.st_mode)
        or not stat.S_ISREG(descriptor_metadata.st_mode)
        or path_metadata.st_uid != expected_uid
        or descriptor_metadata.st_uid != expected_uid
        or stat.S_IMODE(path_metadata.st_mode) != 0o600
        or stat.S_IMODE(descriptor_metadata.st_mode) != 0o600
        or path_metadata.st_nlink != 1
        or descriptor_metadata.st_nlink != 1
        or (path_metadata.st_dev, path_metadata.st_ino)
        != (descriptor_metadata.st_dev, descriptor_metadata.st_ino)
    ):
        raise SystemExit(f"production transaction lock is unsafe: {path}")
    return {
        "device": descriptor_metadata.st_dev,
        "inode": descriptor_metadata.st_ino,
        "mode": "0600",
        "nlink": descriptor_metadata.st_nlink,
        "path": str(path),
        "uid": descriptor_metadata.st_uid,
    }


def acquire_shared_locks() -> tuple[dict[str, int], dict[str, dict[str, object]]]:
    if not hasattr(os, "O_NOFOLLOW"):
        raise SystemExit("O_NOFOLLOW is required for production lock observation")
    expected_uid = os.getuid()
    descriptors: dict[str, int] = {}
    identities: dict[str, dict[str, object]] = {}
    for name, path in LOCK_PATHS.items():
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        except OSError as exc:
            for held in descriptors.values():
                os.close(held)
            raise SystemExit(f"production transaction lock is unsafe: {path}") from exc
        try:
            _lock_identity(path, descriptor, expected_uid=expected_uid)
            fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
            identities[name] = _lock_identity(
                path, descriptor, expected_uid=expected_uid
            )
        except (BlockingIOError, OSError) as exc:
            os.close(descriptor)
            for held in descriptors.values():
                os.close(held)
            raise SystemExit(
                f"production transaction lock is active or unsafe: {path}"
            ) from exc
        except BaseException:
            os.close(descriptor)
            for held in descriptors.values():
                os.close(held)
            raise
        descriptors[name] = descriptor
    return descriptors, identities


def reverify_shared_locks(
    descriptors: dict[str, int], identities: dict[str, dict[str, object]]
) -> bool:
    for name, path in LOCK_PATHS.items():
        observed = _lock_identity(path, descriptors[name], expected_uid=os.getuid())
        if observed != identities[name]:
            return False
    return True


def secure_regular_bytes(path: Path, *, label: str) -> bytes:
    if not hasattr(os, "O_NOFOLLOW"):
        raise SystemExit(f"O_NOFOLLOW is required for {label}")
    metadata = path.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or metadata.st_mode & 0o022
    ):
        raise SystemExit(f"{label} is unsafe")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if (
        (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        or (before.st_dev, before.st_ino) != (metadata.st_dev, metadata.st_ino)
    ):
        raise SystemExit(f"{label} changed while it was read")
    payload = b"".join(chunks)
    if len(payload) != before.st_size:
        raise SystemExit(f"{label} changed while it was read")
    return payload


def site_release_manifest(
    release_dir: Path, *, release_sha256: str
) -> dict[str, object]:
    payload = secure_regular_bytes(
        release_dir / "release-manifest.json", label="production site release manifest"
    )
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit("production site release manifest is invalid") from exc
    current = value.get("current_release") if isinstance(value, dict) else None
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != "reddit_voc_insights_site_release_v2"
        or value.get("release_sha256") != release_sha256
        or not isinstance(current, dict)
        or current.get("path") != "data/reddit-voc/current-release.json"
        or not isinstance(current.get("release_id"), str)
        or not isinstance(current.get("sha256"), str)
    ):
        raise SystemExit("production site release manifest contract is invalid")
    optional_names = (
        "data_inventory_sha256",
        "data_file_count",
        "data_total_bytes",
    )
    present = [name for name in optional_names if name in current]
    if present and len(present) != len(optional_names):
        raise SystemExit("production site release manifest inventory is incomplete")
    inventory = None
    if present:
        inventory = {name: current[name] for name in optional_names}
        if (
            not isinstance(inventory["data_inventory_sha256"], str)
            or len(inventory["data_inventory_sha256"]) != 64
            or any(
                character not in "0123456789abcdef"
                for character in inventory["data_inventory_sha256"]
            )
            or isinstance(inventory["data_file_count"], bool)
            or not isinstance(inventory["data_file_count"], int)
            or inventory["data_file_count"] <= 0
            or isinstance(inventory["data_total_bytes"], bool)
            or not isinstance(inventory["data_total_bytes"], int)
            or inventory["data_total_bytes"] <= 0
        ):
            raise SystemExit("production site release manifest inventory is invalid")
    return {
        "data_file_count": None if inventory is None else inventory["data_file_count"],
        "data_inventory_sha256": (
            None if inventory is None else inventory["data_inventory_sha256"]
        ),
        "data_release_id": current["release_id"],
        "data_total_bytes": None if inventory is None else inventory["data_total_bytes"],
        "manifest_sha256": sha256(payload).hexdigest(),
        "pointer_path": current["path"],
        "pointer_sha256": current["sha256"],
        "release_sha256": release_sha256,
    }


def data_inventory(public_root: Path, *, release_id: str) -> dict[str, object]:
    pointer_path = public_root / "data/reddit-voc/current-release.json"
    pointer_bytes = pointer_path.read_bytes()
    pointer = json.loads(pointer_bytes)
    datasets = pointer.get("datasets")
    if (
        pointer.get("schema_version") != "reddit_voc_current_release_v2"
        or pointer.get("release_id") != release_id
        or not isinstance(datasets, dict)
        or set(datasets) != {
            "base", "insights", "reports", "personas", "brand_health",
            "quarter_insights", "casebook",
        }
    ):
        raise SystemExit("production data pointer contract is invalid")

    def verify_manifest(row: object) -> None:
        if not isinstance(row, dict):
            raise SystemExit("production data manifest binding is invalid")
        raw_path = row.get("manifest_path")
        expected_sha = row.get("public_manifest_sha256")
        if not isinstance(raw_path, str) or not isinstance(expected_sha, str):
            raise SystemExit("production data manifest binding is incomplete")
        relative = PurePosixPath(raw_path)
        if relative.is_absolute() or ".." in relative.parts or "." in relative.parts:
            raise SystemExit("production data manifest path is unsafe")
        target = public_root.joinpath(*relative.parts)
        if not target.is_file() or target.is_symlink():
            raise SystemExit("production data manifest is missing or unsafe")
        if sha256(target.read_bytes()).hexdigest() != expected_sha:
            raise SystemExit("production data manifest checksum mismatch")

    for row in datasets.values():
        verify_manifest(row)
    if pointer.get("cases") is not None:
        verify_manifest(pointer["cases"])

    files: list[tuple[str, str, int]] = []
    for root, directories, filenames in os.walk(public_root, followlinks=False):
        root_path = Path(root)
        root_metadata = root_path.lstat()
        if not stat.S_ISDIR(root_metadata.st_mode) or root_metadata.st_mode & 0o022:
            raise SystemExit("production data directory is mutable or unsafe")
        for name in directories:
            metadata = (root_path / name).lstat()
            if not stat.S_ISDIR(metadata.st_mode):
                raise SystemExit("production data tree contains an unsafe directory")
        for name in filenames:
            path = root_path / name
            metadata = path.lstat()
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_nlink != 1
                or metadata.st_mode & 0o022
            ):
                raise SystemExit("production data tree contains an unsafe file")
            payload = path.read_bytes()
            files.append(
                (
                    path.relative_to(public_root).as_posix(),
                    sha256(payload).hexdigest(),
                    len(payload),
                )
            )
    if not files:
        raise SystemExit("production data inventory is empty")
    digest = sha256()
    for relative, file_sha, size in sorted(files):
        digest.update(
            relative.encode("utf-8")
            + b"\0"
            + file_sha.encode("ascii")
            + b"\0"
            + str(size).encode("ascii")
            + b"\n"
        )
    return {
        "file_count": len(files),
        "inventory_sha256": digest.hexdigest(),
        "pointer_sha256": sha256(pointer_bytes).hexdigest(),
        "total_bytes": sum(row[2] for row in files),
    }


def main() -> int:
    if sys.version_info < (3, 10):
        raise SystemExit("Python 3.10 or newer is required")
    lock_descriptors, lock_identities = acquire_shared_locks()
    if not CURRENT.is_symlink():
        raise SystemExit("production current pointer is not a symlink")
    target = CURRENT.readlink().as_posix()
    prefix = "releases/"
    if not target.startswith(prefix) or len(target.removeprefix(prefix)) != 64:
        raise SystemExit("production current pointer target is invalid")
    release_sha = target.removeprefix(prefix)
    if any(character not in "0123456789abcdef" for character in release_sha):
        raise SystemExit("production current release SHA is invalid")
    release_dir = DEPLOY_ROOT / target
    if not release_dir.is_dir() or release_dir.is_symlink():
        raise SystemExit("production current release directory is unsafe")

    subprocess.run(
        ("sha256sum", "--check", "SHA256SUMS"),
        cwd=release_dir,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    release_sha256s_sha = sha256_file(release_dir / "SHA256SUMS")
    site_manifest_before = site_release_manifest(
        release_dir, release_sha256=release_sha
    )
    internal_release = json.loads(
        command("curl", "-fsS", "http://172.20.0.1:18338/release.json")
    )["release_sha256"]
    data_current = DATA_ROOT / "current"
    if not data_current.is_symlink():
        raise SystemExit("production data current pointer is not a symlink")
    data_target = data_current.readlink().as_posix()
    data_prefix = "releases/"
    if not data_target.startswith(data_prefix):
        raise SystemExit("production data current pointer target is invalid")
    data_release_id = data_target.removeprefix(data_prefix)
    if not data_release_id.startswith("reddit_voc_release_") or any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789_-"
        for character in data_release_id
    ):
        raise SystemExit("production data release id is invalid")
    data_release_dir = DATA_ROOT / data_target
    if not data_release_dir.is_dir() or data_release_dir.is_symlink():
        raise SystemExit("production data release directory is unsafe")
    if DATA_ROOT.is_symlink() or (DATA_ROOT / "releases").is_symlink():
        raise SystemExit("production data root ancestry is unsafe")
    data_pointer_path = (
        data_release_dir / "public/data/reddit-voc/current-release.json"
    )
    if not data_pointer_path.is_file() or data_pointer_path.is_symlink():
        raise SystemExit("production data pointer artifact is unsafe")
    inventory_before = data_inventory(
        data_release_dir / "public", release_id=data_release_id
    )
    internal_pointer_sha256 = str(inventory_before["pointer_sha256"])
    if (
        site_manifest_before["data_release_id"] != data_release_id
        or site_manifest_before["pointer_sha256"] != internal_pointer_sha256
    ):
        raise SystemExit("site release manifest differs from production data current")
    for manifest_name, inventory_name in (
        ("data_inventory_sha256", "inventory_sha256"),
        ("data_file_count", "file_count"),
        ("data_total_bytes", "total_bytes"),
    ):
        manifest_value = site_manifest_before[manifest_name]
        if manifest_value is not None and manifest_value != inventory_before[inventory_name]:
            raise SystemExit("site release manifest inventory differs from production data")
    served_pointer_bytes = command_bytes(
        "curl",
        "-fsS",
        "http://172.20.0.1:18338/data/reddit-voc/current-release.json",
    )
    served_pointer = json.loads(served_pointer_bytes)
    internal_pointer = served_pointer["release_id"]
    if internal_pointer != data_release_id:
        raise SystemExit("served data pointer differs from data current symlink")
    if sha256(served_pointer_bytes).hexdigest() != internal_pointer_sha256:
        raise SystemExit("served data pointer bytes differ from immutable data release")
    command("curl", "-fsS", "http://172.20.0.1:18338/healthz")
    command("curl", "-fsS", "http://127.0.0.1:18337/api/health")
    if internal_release != release_sha:
        raise SystemExit("production release marker differs from current pointer")

    collector = "reddit_voc_site_app"
    translation = "reddit_voc_libretranslate"
    insights = "reddit_voc_insights_web"
    collector_before = {
        "container_id": docker_value(collector, "{{.Id}}"),
        "health": health(collector),
        "restart_count": int(docker_value(collector, "{{.RestartCount}}")),
    }
    translation_before = {
        "container_id": docker_value(translation, "{{.Id}}"),
        "health": health(translation),
        "restart_count": int(docker_value(translation, "{{.RestartCount}}")),
    }
    insights_before = {
        "container_id": docker_value(insights, "{{.Id}}"),
        "health": health(insights),
        "restart_count": int(docker_value(insights, "{{.RestartCount}}")),
        "release_label": docker_value(insights, '{{index .Config.Labels "com.reddit-voc.release"}}'),
    }
    if (
        collector_before["health"] != "healthy"
        or translation_before["health"] != "healthy"
        or insights_before["health"] != "healthy"
        or collector_before["restart_count"] != 0
        or translation_before["restart_count"] != 0
        or insights_before["restart_count"] != 0
        or insights_before["release_label"] != release_sha
    ):
        raise SystemExit("one required Reddit VOC production container is not pristine")
    image_reference = f"reddit-voc-insights:{release_sha}"
    image_archive = release_dir / f"reddit-voc-insights-{release_sha}.tar"
    expected_image_id = expected_image_id_from_archive(
        image_archive, image_reference
    )
    image_tag_id_before = command(
        "docker", "image", "inspect", "-f", "{{.Id}}", image_reference
    )
    if image_tag_id_before != expected_image_id:
        raise SystemExit("production image tag differs from the authenticated archive")
    insights_runtime_before = json.loads(command("docker", "inspect", insights))[0]
    insights_network_before = json.loads(
        command("docker", "network", "inspect", "reddit_voc_insights_net")
    )[0]
    runtime_contract_before = validate_insights_runtime(
        insights_runtime_before,
        insights_network_before,
        release_sha256=release_sha,
        expected_image_id=expected_image_id,
    )
    listener_addresses_before = listener_addresses(18338)
    if listener_addresses_before != ["172.20.0.1:18338"]:
        raise SystemExit("production insights listener isolation is invalid")
    collector_reachable_before = subprocess.run(
        (
            "docker",
            "exec",
            insights,
            "wget",
            "-q",
            "-T",
            "3",
            "-O",
            "/dev/null",
            "http://172.20.0.1:18337/api/health",
        ),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0
    if collector_reachable_before:
        raise SystemExit("production insights runtime can reach the collector listener")

    candidate_before = named_running_count("reddit_voc_insights_candidate")
    candidate_residue_before = named_container_count("reddit_voc_insights_candidate")
    listener_before = listener_count(18339)
    one_shot_before = named_running_count("reddit_voc_site_app-run-")
    report_before_count = named_running_count("reddit_voc_report")
    if (
        candidate_before != 0
        or candidate_residue_before != 0
        or listener_before != 0
        or one_shot_before != 0
        or report_before_count != 0
    ):
        raise SystemExit("production baseline has candidate, report, or one-shot residue")

    ids_before = container_inventory()
    protected_ids_before = container_inventory(protected_only=True)
    database_before = file_identity(DATABASE)
    report_before = file_identity(REPORT_POINTER)
    if database_before == "absent":
        raise SystemExit("production database is absent")
    cron_sha = sha256_file(CRON_FILE, sudo=True)
    nginx_sha = sha256_file(NGINX_CONFIG)
    time.sleep(2)
    ids_after = container_inventory()
    protected_ids_after = container_inventory(protected_only=True)
    database_after = file_identity(DATABASE)
    report_after = file_identity(REPORT_POINTER)
    collector_after = {
        "container_id": docker_value(collector, "{{.Id}}"),
        "health": health(collector),
        "restart_count": int(docker_value(collector, "{{.RestartCount}}")),
    }
    translation_after = {
        "container_id": docker_value(translation, "{{.Id}}"),
        "health": health(translation),
        "restart_count": int(docker_value(translation, "{{.RestartCount}}")),
    }
    insights_after = {
        "container_id": docker_value(insights, "{{.Id}}"),
        "health": health(insights),
        "restart_count": int(docker_value(insights, "{{.RestartCount}}")),
        "release_label": docker_value(insights, '{{index .Config.Labels "com.reddit-voc.release"}}'),
    }
    insights_runtime_after = json.loads(command("docker", "inspect", insights))[0]
    insights_network_after = json.loads(
        command("docker", "network", "inspect", "reddit_voc_insights_net")
    )[0]
    runtime_contract_after = validate_insights_runtime(
        insights_runtime_after,
        insights_network_after,
        release_sha256=release_sha,
        expected_image_id=expected_image_id,
    )
    image_tag_id_after = command(
        "docker", "image", "inspect", "-f", "{{.Id}}", image_reference
    )
    listener_addresses_after = listener_addresses(18338)
    collector_reachable_after = subprocess.run(
        (
            "docker",
            "exec",
            insights,
            "wget",
            "-q",
            "-T",
            "3",
            "-O",
            "/dev/null",
            "http://172.20.0.1:18337/api/health",
        ),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0
    if (
        collector_after["health"] != "healthy"
        or translation_after["health"] != "healthy"
        or insights_after["health"] != "healthy"
        or collector_after["restart_count"] != 0
        or translation_after["restart_count"] != 0
        or insights_after["restart_count"] != 0
        or insights_after["release_label"] != release_sha
    ):
        raise SystemExit("a required Reddit VOC production container drifted")
    site_target_after = CURRENT.readlink().as_posix() if CURRENT.is_symlink() else "unsafe"
    data_target_after = (
        data_current.readlink().as_posix() if data_current.is_symlink() else "unsafe"
    )
    inventory_after = data_inventory(
        data_release_dir / "public", release_id=data_release_id
    )
    subprocess.run(
        ("sha256sum", "--check", "SHA256SUMS"),
        cwd=release_dir,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    release_sha256s_sha_after = sha256_file(release_dir / "SHA256SUMS")
    site_manifest_after = site_release_manifest(
        release_dir, release_sha256=release_sha
    )
    internal_release_after = json.loads(
        command("curl", "-fsS", "http://172.20.0.1:18338/release.json")
    )["release_sha256"]
    served_pointer_bytes_after = command_bytes(
        "curl",
        "-fsS",
        "http://172.20.0.1:18338/data/reddit-voc/current-release.json",
    )
    internal_pointer_sha256_after = sha256(served_pointer_bytes_after).hexdigest()
    internal_pointer_after = json.loads(served_pointer_bytes_after)["release_id"]
    candidate_after = named_running_count("reddit_voc_insights_candidate")
    candidate_residue_after = named_container_count("reddit_voc_insights_candidate")
    listener_after = listener_count(18339)
    one_shot_after = named_running_count("reddit_voc_site_app-run-")
    report_after_count = named_running_count("reddit_voc_report")
    cron_sha_after = sha256_file(CRON_FILE, sudo=True)
    nginx_sha_after = sha256_file(NGINX_CONFIG)
    locks_stable = reverify_shared_locks(lock_descriptors, lock_identities)
    stable = (
        ids_before == ids_after
        and protected_ids_before == protected_ids_after
        and database_before == database_after
        and report_before == report_after
        and collector_before == collector_after
        and translation_before == translation_after
        and insights_before == insights_after
        and runtime_contract_before == runtime_contract_after
        and image_tag_id_after == image_tag_id_before == expected_image_id
        and listener_addresses_after == listener_addresses_before
        == ["172.20.0.1:18338"]
        and collector_reachable_after is collector_reachable_before is False
        and site_target_after == target
        and data_target_after == data_target
        and site_manifest_after == site_manifest_before
        and internal_release_after == internal_release == release_sha
        and internal_pointer_after == internal_pointer
        and internal_pointer_sha256_after == internal_pointer_sha256
        and inventory_after == inventory_before
        and candidate_after == candidate_before == 0
        and candidate_residue_after == candidate_residue_before == 0
        and listener_after == listener_before == 0
        and one_shot_after == one_shot_before == 0
        and report_after_count == report_before_count == 0
        and cron_sha == cron_sha_after
        and nginx_sha == nginx_sha_after
        and release_sha256s_sha == release_sha256s_sha_after
        and locks_stable
    )
    if not stable:
        raise SystemExit("production baseline changed during read-only observation")

    inventory_sha = sha256(("\n".join(ids_before) + "\n").encode()).hexdigest()
    protected_inventory_sha = sha256(
        ("\n".join(protected_ids_before) + "\n").encode()
    ).hexdigest()
    manifest_inventory_bound = site_manifest_before["data_inventory_sha256"] is not None
    receipt = {
        "current_release_sha256": release_sha,
        "evidence_grade": "L3-production-read-only",
        "observations": {
            "candidate_container_count": candidate_before,
            "candidate_container_count_after": candidate_after,
            "candidate_container_residue_count": candidate_residue_before,
            "candidate_container_residue_count_after": candidate_residue_after,
            "candidate_listener_18339_count": listener_before,
            "candidate_listener_18339_count_after": listener_after,
            "collector": collector_before,
            "cron": {
                "sha256": cron_sha,
                "stable": True,
            },
            "cron_sha256": cron_sha,
            "database": {
                "after": database_after,
                "before": database_before,
                "stable": True,
            },
            "insights": {
                **insights_before,
                "current_symlink": target,
                "internal_pointer": internal_pointer,
                "internal_pointer_sha256": internal_pointer_sha256,
                "internal_pointer_symlink": data_target,
                "data_file_count": inventory_before["file_count"],
                "data_inventory_sha256": inventory_before["inventory_sha256"],
                "data_total_bytes": inventory_before["total_bytes"],
                "internal_release_sha256": internal_release,
                "listener": "172.20.0.1:18338",
                "mount_count": int(docker_value(insights, "{{len .Mounts}}")),
                "network": docker_value(
                    insights,
                    "{{range $name, $value := .NetworkSettings.Networks}}{{$name}}{{end}}",
                ),
                "read_only_rootfs": docker_value(insights, "{{.HostConfig.ReadonlyRootfs}}") == "true",
                "runtime_contract": runtime_contract_before,
                "user": docker_value(insights, "{{.Config.User}}"),
            },
            "locks": {
                "identities": lock_identities,
                "stable": True,
            },
            "libretranslate": translation_before,
            "one_shot_collectors_running": one_shot_before,
            "one_shot_collectors_running_after": one_shot_after,
            "observer_runtime": {
                "contract": OBSERVER_RUNTIME_CONTRACT,
                "contract_sha256": OBSERVER_RUNTIME_SHA256,
                "uid": os.getuid(),
            },
            "quiet_counts_stable": True,
            "release_sha256s": {
                "sha256": release_sha256s_sha,
                "stable": True,
                "verified_after": True,
                "verified_before": True,
            },
            "release_sha256sums_verified": True,
            "report_network_containers_running": report_before_count,
            "report_network_containers_running_after": report_after_count,
            "report_pointer": {
                "after": report_after,
                "before": report_before,
                "stable": True,
            },
            "running_containers": {
                "count": len(ids_before),
                "inventory_sha256": inventory_sha,
                "protected_count": len(protected_ids_before),
                "protected_inventory_sha256": protected_inventory_sha,
                "protected_scope": "docker_ps_a_excluding_insights_transaction",
                "scope": "docker_ps_a",
                "stable": True,
            },
            "shared_nginx": {
                "sha256": nginx_sha,
                "stable": True,
            },
            "shared_nginx_sha256": nginx_sha,
            "site_data_tuple": {
                "data_file_count": inventory_before["file_count"],
                "data_inventory_sha256": inventory_before["inventory_sha256"],
                "data_release_id": data_release_id,
                "data_total_bytes": inventory_before["total_bytes"],
                "manifest_inventory_bound": manifest_inventory_bound,
                "pointer_sha256": internal_pointer_sha256,
                "site_manifest_sha256": site_manifest_before["manifest_sha256"],
                "site_release_sha256": release_sha,
                "stable": True,
            },
            "site_release_manifest": {
                **site_manifest_before,
                # The release manifest is a host-side immutable artifact, not
                # a public Nginx route.  Exact activation is proven transitively
                # by the current symlink, SHA256SUMS, image identity/container
                # label, public release marker, and public data pointer above.
                "served_exact": True,
                "stable": True,
            },
        },
        "observed_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "production_unchanged": True,
        "remote_write": False,
        "schema_version": "reddit_voc_production_baseline_receipt_v1",
        "status": "passed",
    }
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    for descriptor in lock_descriptors.values():
        os.close(descriptor)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
