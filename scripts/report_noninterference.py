from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sqlite3
import stat
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping
from urllib.parse import quote


_SENSITIVE_FRAGMENTS = ("secret", "webhook", "api_key", "password", "token", "credential")
_GATE_KEYS = (
    "REDDIT_VOC_TRANSLATION_MODE",
    "REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION",
    "REDDIT_VOC_DINGTALK_MODE",
    "REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND",
    "REDDIT_VOC_ENABLE_REPORT_FAILURE_ALERT",
)
_ALL_OFF_GATES = {
    "REDDIT_VOC_TRANSLATION_MODE": "dry_run",
    "REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION": "0",
    "REDDIT_VOC_DINGTALK_MODE": "dry_run",
    "REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND": "0",
    "REDDIT_VOC_ENABLE_REPORT_FAILURE_ALERT": "0",
}
_TERMINAL_GATE_PHASES = {"restored", "terminal_all_off", "recovered_all_off"}
_TERMINAL_PERMIT_STATES = {
    "consumed",
    "blocked",
    "closed_no_attempt",
    "revoked",
    "unknown",
}
_HOST_FILES = {
    "nginx_sha256": "/opt/ai-video/deploy/lighthouse/nginx.conf",
    "cron_sha256": "/etc/cron.d/reddit-voc-site",
    "collector_sha256": "/opt/reddit-voc-site/scripts/server_daily_collect.sh",
    "fixed_launcher_sha256": "/opt/reddit-voc-site/scripts/server_daily_report.sh",
}
_LAYER_ALLOWED = {
    "L4": {
        "fixed_launcher_sha256",
        "current_release",
        "report_network_exists",
        "report_network_members",
        "network_members",
        "report_containers",
        "report_gates",
        "gate_journal_ids",
        "admin_permit_ids",
        "active_permit_ids",
        "terminal_permit_ids",
        "authorization_audit_tip",
    },
    "L5": {
        "prepared_pointer",
        "projection_targets",
        "provider_attempt_counts",
        "report_gates",
        "gate_journal_ids",
        "prepare_permit_ids",
        "schedule_permit_ids",
        "active_permit_ids",
        "terminal_permit_ids",
        "authorization_audit_tip",
        "report_container",
        "report_containers",
        "report_network_members",
        "network_members",
    },
    "L6": {
        "delivery_ledger_tip",
        "delivery_records",
        "report_gates",
        "gate_journal_ids",
        "send_permit_ids",
        "active_permit_ids",
        "terminal_permit_ids",
        "authorization_audit_tip",
        "report_container",
        "report_containers",
        "report_network_members",
        "network_members",
    },
}


@dataclass(frozen=True)
class HostCapture:
    public: Mapping[str, object]
    _non_gate_env_lines: tuple[bytes, ...] = field(repr=False)


def capture_from_mapping(state: Mapping[str, object]) -> Mapping[str, object]:
    if not isinstance(state, Mapping):
        raise ValueError("noninterference_state_invalid")
    return _redact_mapping(state)


def compare_snapshots(
    *, before: Mapping[str, object], after: Mapping[str, object], layer: str
) -> Mapping[str, object]:
    if layer not in _LAYER_ALLOWED:
        raise ValueError("noninterference_layer_invalid")
    before_clean = capture_from_mapping(before)
    after_clean = capture_from_mapping(after)
    keys = set(before_clean) | set(after_clean)
    changed = sorted(key for key in keys if before_clean.get(key) != after_clean.get(key))
    unexpected = [key for key in changed if key not in _LAYER_ALLOWED[layer]]
    return {
        "schema_version": "report-noninterference-compare-v1",
        "layer": layer,
        "status": "blocked" if unexpected else "accepted",
        "changed": changed,
        "unexpected_changes": unexpected,
    }


def _mapped_host_path(host_root: Path, absolute: str) -> Path:
    if not host_root.is_absolute() or not absolute.startswith("/"):
        raise ValueError("host_path_invalid")
    return host_root / absolute.lstrip("/")


def _read_regular(path: Path, *, maximum: int = 16 * 1024 * 1024) -> bytes:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise ValueError("host_fact_missing") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode) or metadata.st_size > maximum:
        raise ValueError("host_fact_invalid")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_dev != metadata.st_dev
            or opened.st_ino != metadata.st_ino
        ):
            raise ValueError("host_fact_invalid")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(65_536, maximum + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > maximum:
                raise ValueError("host_fact_invalid")
        payload = b"".join(chunks)
    finally:
        os.close(descriptor)
    if len(payload) > maximum:
        raise ValueError("host_fact_invalid")
    return payload


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(_read_regular(path)).hexdigest()


def _strict_json_file(path: Path) -> Mapping[str, object]:
    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in values:
            if key in result:
                raise ValueError("duplicate")
            result[key] = value
        return result

    try:
        value = json.loads(
            _read_regular(path, maximum=4 * 1024 * 1024),
            object_pairs_hook=pairs,
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError("host_fact_invalid") from exc
    if not isinstance(value, Mapping):
        raise ValueError("host_fact_invalid")
    return value


def _parse_report_env(path: Path) -> tuple[Mapping[str, str], tuple[bytes, ...]]:
    payload = _read_regular(path, maximum=1024 * 1024)
    if b"\x00" in payload or b"\r" in payload:
        raise ValueError("report_env_invalid")
    lines = tuple(payload.splitlines(keepends=True))
    values: dict[str, str] = {}
    non_gate: list[bytes] = []
    for raw in lines:
        content = raw[:-1] if raw.endswith(b"\n") else raw
        if not content or content.startswith(b"#"):
            non_gate.append(raw)
            continue
        if b"=" not in content:
            raise ValueError("report_env_invalid")
        raw_key, raw_value = content.split(b"=", 1)
        try:
            key = raw_key.decode("ascii")
            value = raw_value.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("report_env_invalid") from exc
        if key in values:
            raise ValueError("report_env_invalid")
        values[key] = value
        if key not in _GATE_KEYS:
            non_gate.append(raw)
    if any(key not in values for key in _GATE_KEYS):
        raise ValueError("report_env_invalid")
    gates = {key: values[key] for key in _GATE_KEYS}
    if gates["REDDIT_VOC_TRANSLATION_MODE"] not in {"dry_run", "deepseek"}:
        raise ValueError("report_env_invalid")
    if gates["REDDIT_VOC_DINGTALK_MODE"] not in {"dry_run", "live"}:
        raise ValueError("report_env_invalid")
    if any(gates[key] not in {"0", "1"} for key in _GATE_KEYS if key.endswith(("TRANSLATION", "SEND", "ALERT"))):
        raise ValueError("report_env_invalid")
    return gates, tuple(non_gate)


def _database_fact(path: Path) -> Mapping[str, object]:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise ValueError("database_fact_missing") from exc
    if path.is_symlink() or not path.is_file():
        raise ValueError("database_fact_invalid")
    uri = f"file:{quote(str(path))}?mode=ro&immutable=1"
    try:
        connection = sqlite3.connect(uri, uri=True)
        try:
            connection.execute("PRAGMA query_only=ON")
            rows = connection.execute(
                "SELECT type, name, tbl_name, COALESCE(sql, '') "
                "FROM sqlite_master ORDER BY type, name, tbl_name, sql"
            ).fetchall()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise ValueError("database_fact_invalid") from exc
    schema_payload = json.dumps(
        rows, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return {
        "schema_sha256": hashlib.sha256(schema_payload).hexdigest(),
        "inode": metadata.st_ino,
        "size": metadata.st_size,
        "mtime_ns": metadata.st_mtime_ns,
    }


def _current_release(host_root: Path) -> str | None:
    current = _mapped_host_path(
        host_root, "/opt/reddit-voc-daily-report/current"
    )
    if not current.exists() and not current.is_symlink():
        return None
    if not current.is_symlink():
        raise ValueError("current_release_invalid")
    target = current.resolve(strict=True)
    releases = _mapped_host_path(
        host_root, "/opt/reddit-voc-daily-report/releases"
    ).resolve(strict=True)
    try:
        relative = target.relative_to(releases)
    except ValueError as exc:
        raise ValueError("current_release_invalid") from exc
    if len(relative.parts) != 1 or len(relative.name) != 64 or any(
        character not in "0123456789abcdef" for character in relative.name
    ):
        raise ValueError("current_release_invalid")
    return relative.name


def _prepared_pointer(host_root: Path) -> Mapping[str, object] | None:
    path = _mapped_host_path(
        host_root,
        "/opt/reddit-voc-daily-report/state/prepared-current.json",
    )
    if not path.exists() and not path.is_symlink():
        return None
    value = _strict_json_file(path)
    allowed = {
        "run_id",
        "artifact_version_id",
        "bundle_sha256",
        "outbox_sha256",
        "report_input_fingerprint",
    }
    return {key: value[key] for key in sorted(value) if key in allowed}


def _projection_targets(host_root: Path) -> Mapping[str, str]:
    root = _mapped_host_path(host_root, "/opt/reddit-voc-site/outputs")
    if not root.exists():
        return {}
    if root.is_symlink() or not root.is_dir():
        raise ValueError("projection_root_invalid")
    result: dict[str, str] = {}
    for path in sorted(root.iterdir(), key=lambda item: item.name):
        if not path.is_symlink():
            continue
        resolved = path.resolve(strict=True)
        try:
            relative = resolved.relative_to(host_root)
            result[path.name] = "/" + str(relative)
        except ValueError:
            result[path.name] = str(resolved)
    return result


def _gate_journal_facts(control_root: Path) -> tuple[Mapping[str, list[str]], set[str]]:
    root = control_root / "gates"
    if not root.exists():
        return {"active": [], "terminal": []}, set()
    active: list[str] = []
    terminal: list[str] = []
    active_snapshots: set[str] = set()
    for path in sorted(root.glob("*.json")):
        value = _strict_json_file(path)
        journal_id = value.get("journal_id")
        phase = value.get("phase")
        if not isinstance(journal_id, str) or path.stem != journal_id or not isinstance(phase, str):
            raise ValueError("gate_journal_invalid")
        if phase in _TERMINAL_GATE_PHASES:
            terminal.append(journal_id)
        else:
            active.append(journal_id)
            snapshot_id = value.get("snapshot_id")
            if isinstance(snapshot_id, str):
                active_snapshots.add(snapshot_id)
    return {"active": active, "terminal": terminal}, active_snapshots


def _permit_facts(control_root: Path) -> Mapping[str, object]:
    permits_root = control_root / "permits"
    states_root = control_root / "permit-state"
    groups: dict[str, list[str]] = {
        "prepare_permit_ids": [],
        "send_permit_ids": [],
        "schedule_permit_ids": [],
        "admin_permit_ids": [],
    }
    active: list[str] = []
    terminal: list[str] = []
    if not permits_root.exists():
        return {**groups, "active_permit_ids": active, "terminal_permit_ids": terminal}
    schema_groups = {
        "report-prepare-permit-v1": "prepare_permit_ids",
        "report-send-permit-v1": "send_permit_ids",
        "report-schedule-permit-v1": "schedule_permit_ids",
        "report-admin-permit-v1": "admin_permit_ids",
        "report-shadow-permit-v1": "prepare_permit_ids",
    }
    for permit_path in sorted(permits_root.glob("*.json")):
        permit = _strict_json_file(permit_path)
        authorization_id = permit.get("authorization_id")
        group = schema_groups.get(str(permit.get("schema_version")))
        if not isinstance(authorization_id, str) or permit_path.stem != authorization_id or group is None:
            raise ValueError("permit_fact_invalid")
        state = _strict_json_file(states_root / f"{authorization_id}.json")
        status = state.get("status")
        if (
            state.get("authorization_id") != authorization_id
            or state.get("permit_sha256")
            != hashlib.sha256(_canonical(permit)).hexdigest()
            or not isinstance(status, str)
        ):
            raise ValueError("permit_fact_invalid")
        groups[group].append(authorization_id)
        if status in {"installed", "reserved"}:
            active.append(authorization_id)
        elif status in _TERMINAL_PERMIT_STATES:
            terminal.append(authorization_id)
        else:
            raise ValueError("permit_fact_invalid")
    return {
        **groups,
        "active_permit_ids": sorted(active),
        "terminal_permit_ids": sorted(terminal),
    }


def _audit_tip(control_root: Path) -> str | None:
    path = control_root / "audit" / "authorization.jsonl"
    if not path.exists():
        return None
    lines = _read_regular(path, maximum=4 * 1024 * 1024).splitlines()
    if not lines:
        raise ValueError("authorization_audit_invalid")
    previous = "0" * 64
    for sequence, line in enumerate(lines, start=1):
        try:
            value = json.loads(line)
        except ValueError as exc:
            raise ValueError("authorization_audit_invalid") from exc
        if not isinstance(value, Mapping):
            raise ValueError("authorization_audit_invalid")
        base = {key: value[key] for key in value if key != "entry_sha256"}
        entry_sha = value.get("entry_sha256")
        if (
            value.get("sequence") != sequence
            or value.get("previous_entry_sha256") != previous
            or not isinstance(entry_sha, str)
            or entry_sha != hashlib.sha256(_canonical(base)).hexdigest()
        ):
            raise ValueError("authorization_audit_invalid")
        previous = entry_sha
    return previous


def _provider_attempt_counts(control_root: Path) -> Mapping[str, int]:
    root = control_root / "provider-attempts"
    if not root.exists():
        return {}
    result: dict[str, int] = {}
    for path in sorted(root.iterdir(), key=lambda item: item.name):
        if path.is_symlink():
            raise ValueError("provider_attempt_fact_invalid")
        if path.is_dir():
            count = sum(
                1
                for child in path.iterdir()
                if child.is_file() and not child.is_symlink()
            )
            result[path.name] = count
        elif path.is_file():
            result[path.stem] = len(_read_regular(path).splitlines())
        else:
            raise ValueError("provider_attempt_fact_invalid")
    return result


def _backfill_state(host_root: Path) -> Mapping[str, Mapping[str, int]]:
    root = _mapped_host_path(host_root, "/opt/reddit-voc-site/data")
    if not root.exists():
        return {}
    result: dict[str, Mapping[str, int]] = {}
    for path in sorted(root.iterdir(), key=lambda item: item.name):
        if "backfill" not in path.name.casefold() or path.is_symlink():
            continue
        metadata = path.stat()
        result[path.name] = {
            "inode": metadata.st_ino,
            "size": metadata.st_size,
            "mtime_ns": metadata.st_mtime_ns,
        }
    return result


def _normalize_docker_facts(value: Mapping[str, object]) -> Mapping[str, object]:
    containers = value.get("containers")
    networks = value.get("networks")
    report_containers = value.get("report_containers")
    if not isinstance(containers, Mapping) or not isinstance(networks, Mapping) or not isinstance(report_containers, list):
        raise ValueError("docker_facts_invalid")
    required_containers = {
        "reddit_voc_site_app",
        "reddit_voc_libretranslate",
        "ai_video_nginx",
    }
    required_networks = {
        "lighthouse_ai_video_net",
        "reddit_voc_site_net",
        "reddit_voc_report_net",
    }
    if set(containers) != required_containers or set(networks) != required_networks:
        raise ValueError("docker_facts_invalid")
    normalized_networks: dict[str, list[str]] = {}
    for name, members in networks.items():
        if not isinstance(name, str) or not isinstance(members, list) or any(not isinstance(member, str) for member in members):
            raise ValueError("docker_facts_invalid")
        normalized_networks[name] = sorted(members)
    normalized_containers: dict[str, object] = {}
    for name, facts in containers.items():
        if not isinstance(facts, Mapping):
            raise ValueError("docker_facts_invalid")
        normalized_containers[str(name)] = _redact_mapping(facts)
    if any(not isinstance(item, Mapping) for item in report_containers):
        raise ValueError("docker_facts_invalid")
    return {
        "containers": normalized_containers,
        "networks": normalized_networks,
        "report_containers": [_redact_mapping(item) for item in report_containers],
        "report_network_exists": bool(value.get("report_network_exists", True)),
    }


def _run_json(command: list[str]) -> object:
    completed = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=15,
        check=False,
    )
    if completed.returncode != 0 or len(completed.stdout) > 4 * 1024 * 1024:
        raise ValueError("docker_fact_read_failed")
    try:
        return json.loads(completed.stdout)
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError("docker_fact_read_failed") from exc


def _collect_docker_facts(docker_bin: str) -> Mapping[str, object]:
    containers: dict[str, object] = {}
    for name in (
        "reddit_voc_site_app",
        "reddit_voc_libretranslate",
        "ai_video_nginx",
    ):
        values = _run_json([docker_bin, "inspect", name])
        if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], Mapping):
            raise ValueError("docker_facts_invalid")
        value = values[0]
        state = value.get("State")
        if not isinstance(state, Mapping):
            raise ValueError("docker_facts_invalid")
        containers[name] = {
            "id": value.get("Id"),
            "started_at": state.get("StartedAt"),
            "restart_count": value.get("RestartCount"),
            "mounts": value.get("Mounts"),
        }
    networks: dict[str, list[str]] = {}
    report_members: list[str] = []
    report_exists = True
    for name in (
        "lighthouse_ai_video_net",
        "reddit_voc_site_net",
        "reddit_voc_report_net",
    ):
        completed = subprocess.run(
            [docker_bin, "network", "inspect", name],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=15,
            check=False,
        )
        if completed.returncode != 0 and name == "reddit_voc_report_net":
            report_exists = False
            networks[name] = []
            continue
        if completed.returncode != 0 or len(completed.stdout) > 4 * 1024 * 1024:
            raise ValueError("docker_fact_read_failed")
        try:
            values = json.loads(completed.stdout)
        except (UnicodeDecodeError, ValueError) as exc:
            raise ValueError("docker_fact_read_failed") from exc
        if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], Mapping):
            raise ValueError("docker_facts_invalid")
        members = values[0].get("Containers") or {}
        if not isinstance(members, Mapping):
            raise ValueError("docker_facts_invalid")
        networks[name] = sorted(str(member) for member in members)
        if name == "reddit_voc_report_net":
            report_members = networks[name]
    report_containers: list[Mapping[str, object]] = []
    for container_id in report_members:
        values = _run_json([docker_bin, "inspect", container_id])
        if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], Mapping):
            raise ValueError("docker_facts_invalid")
        value = values[0]
        host_config = value.get("HostConfig")
        if not isinstance(host_config, Mapping):
            raise ValueError("docker_facts_invalid")
        report_containers.append(
            {
                "id": value.get("Id"),
                "image": value.get("Image"),
                "nano_cpus": host_config.get("NanoCpus"),
                "memory": host_config.get("Memory"),
                "pids_limit": host_config.get("PidsLimit"),
                "readonly_rootfs": host_config.get("ReadonlyRootfs"),
                "mounts": value.get("Mounts"),
            }
        )
    return _normalize_docker_facts(
        {
            "containers": containers,
            "networks": networks,
            "report_containers": report_containers,
            "report_network_exists": report_exists,
        }
    )


def capture_host_facts(
    *,
    host_root: Path = Path("/"),
    docker_facts: Mapping[str, object] | None = None,
    docker_bin: str = "docker",
) -> HostCapture:
    root = host_root.resolve(strict=True)
    normalized_docker = (
        _normalize_docker_facts(docker_facts)
        if docker_facts is not None
        else _collect_docker_facts(docker_bin)
    )
    gates, non_gate_lines = _parse_report_env(
        _mapped_host_path(
            root, "/home/ubuntu/.reddit-voc/secrets/reddit-voc-report.env"
        )
    )
    control_root = _mapped_host_path(
        root, "/home/ubuntu/.reddit-voc/report-control"
    )
    journals, active_snapshot_refs = _gate_journal_facts(control_root)
    permit_facts = _permit_facts(control_root)
    snapshots_root = _mapped_host_path(
        root, "/home/ubuntu/.reddit-voc/secrets/report-env-snapshots"
    )
    snapshot_ids = (
        sorted(path.name for path in snapshots_root.iterdir())
        if snapshots_root.exists()
        else []
    )
    if any(path.is_symlink() or not path.is_file() for path in snapshots_root.iterdir()) if snapshots_root.exists() else False:
        raise ValueError("env_snapshot_invalid")
    snapshot_set = set(snapshot_ids)
    public: dict[str, object] = {
        "schema_version": "report-host-noninterference-v1",
        "capture_profile": "host",
        **{
            key: _sha256_file(_mapped_host_path(root, path))
            for key, path in _HOST_FILES.items()
        },
        "current_release": _current_release(root),
        "database": _database_fact(
            _mapped_host_path(
                root, "/opt/reddit-voc-site/data/reddit_voc_daily.sqlite3"
            )
        ),
        "service_containers": normalized_docker["containers"],
        "network_members": normalized_docker["networks"],
        "report_network_exists": normalized_docker["report_network_exists"],
        "report_network_members": normalized_docker["networks"][
            "reddit_voc_report_net"
        ],
        "report_containers": normalized_docker["report_containers"],
        "prepared_pointer": _prepared_pointer(root),
        "projection_targets": _projection_targets(root),
        "backfill_state": _backfill_state(root),
        "report_gates": gates,
        "gate_journal_ids": journals,
        **permit_facts,
        "authorization_audit_tip": _audit_tip(control_root),
        "provider_attempt_counts": _provider_attempt_counts(control_root),
        "env_snapshot_ids": snapshot_ids,
        "env_snapshot_reference_state": {
            "active_references": sorted(active_snapshot_refs),
            "orphan_ids": sorted(snapshot_set - active_snapshot_refs),
            "missing_ids": sorted(active_snapshot_refs - snapshot_set),
        },
    }
    return HostCapture(public=capture_from_mapping(public), _non_gate_env_lines=non_gate_lines)


def compare_host_captures(
    *, before: HostCapture, after: HostCapture, layer: str
) -> Mapping[str, object]:
    result = dict(
        compare_snapshots(before=before.public, after=after.public, layer=layer)
    )
    violations: list[str] = []
    if after.public.get("report_gates") != _ALL_OFF_GATES:
        violations.append("report_gates_not_all_off")
    journals = after.public.get("gate_journal_ids")
    if not isinstance(journals, Mapping) or journals.get("active") != []:
        violations.append("active_gate_journal_present")
    if after.public.get("active_permit_ids") != []:
        violations.append("active_permit_present")
    if after.public.get("env_snapshot_ids") != []:
        violations.append("env_snapshot_present")
    snapshot_state = after.public.get("env_snapshot_reference_state")
    if not isinstance(snapshot_state, Mapping) or snapshot_state.get("orphan_ids") != [] or snapshot_state.get("missing_ids") != []:
        violations.append("env_snapshot_reference_invalid")
    if after.public.get("report_network_members") != []:
        violations.append("report_network_not_empty")
    if after.public.get("report_containers") != []:
        violations.append("report_container_present")
    non_gate_unchanged = (
        before._non_gate_env_lines == after._non_gate_env_lines
    )
    if not non_gate_unchanged:
        violations.append("report_env_non_gate_bytes_changed")
    if result["unexpected_changes"] or violations:
        result["status"] = "blocked"
    result["terminal_violations"] = violations
    result["report_env_non_gate_bytes_unchanged"] = non_gate_unchanged
    return result


def _redact_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    result: dict[str, object] = {}
    for key, child in value.items():
        key_text = str(key)
        folded = key_text.casefold()
        if any(fragment in folded for fragment in _SENSITIVE_FRAGMENTS):
            result[key_text] = "<redacted>"
        elif isinstance(child, Mapping):
            result[key_text] = _redact_mapping(child)
        elif isinstance(child, list):
            result[key_text] = [
                _redact_mapping(item) if isinstance(item, Mapping) else item
                for item in child
            ]
        elif isinstance(child, (str, int, float, bool)) or child is None:
            result[key_text] = child
        else:
            result[key_text] = str(child)
    return result


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _atomic_write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.parent / f".{path.name}.{secrets.token_hex(8)}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(temporary, flags, 0o600)
    try:
        payload = _canonical(value) + b"\n"
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("noninterference_write_failed")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    capture = subparsers.add_parser("capture")
    capture.add_argument("--state-json", type=Path, required=True)
    capture.add_argument("--output", type=Path, required=True)
    capture_host = subparsers.add_parser("capture-host")
    capture_host.add_argument("--host-root", type=Path, default=Path("/"))
    capture_host.add_argument("--docker-bin", default="docker")
    capture_host.add_argument("--docker-facts-json", type=Path)
    capture_host.add_argument("--output", type=Path, required=True)
    compare = subparsers.add_parser("compare")
    compare.add_argument("--before", type=Path, required=True)
    compare.add_argument("--after", type=Path, required=True)
    compare.add_argument("--layer", choices=sorted(_LAYER_ALLOWED), required=True)
    compare.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "capture":
        state = json.loads(args.state_json.read_text(encoding="utf-8"))
        result = capture_from_mapping(state)
    elif args.command == "capture-host":
        if args.host_root != Path("/") and os.getenv("REDDIT_VOC_LOCAL_TEST_MODE") != "1":
            raise SystemExit("host_root_override_forbidden")
        injected = None
        if args.docker_facts_json is not None:
            if os.getenv("REDDIT_VOC_LOCAL_TEST_MODE") != "1":
                raise SystemExit("docker_facts_override_forbidden")
            injected_value = json.loads(
                args.docker_facts_json.read_text(encoding="utf-8")
            )
            if not isinstance(injected_value, Mapping):
                raise SystemExit("docker_facts_invalid")
            injected = injected_value
        result = capture_host_facts(
            host_root=args.host_root,
            docker_facts=injected,
            docker_bin=args.docker_bin,
        ).public
    else:
        before = json.loads(args.before.read_text(encoding="utf-8"))
        after = json.loads(args.after.read_text(encoding="utf-8"))
        result = compare_snapshots(before=before, after=after, layer=args.layer)
    _atomic_write(args.output, result)
    print(f"status={result.get('status', 'captured')}")
    print(f"output={args.output}")
    return 1 if result.get("status") == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
