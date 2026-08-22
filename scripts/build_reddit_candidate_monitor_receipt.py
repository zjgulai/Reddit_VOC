#!/usr/bin/env python3
"""Build one immutable, read-only terminal/quiescence monitor receipt.

The monitor reads only explicitly listed local files or parameterized HTTP(S)
GET endpoints.  It performs two observations, records hashes rather than body
content, installs no schedule, and never mutates the observed systems.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import time
from typing import Any, Callable, Collection, Mapping
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import urlsplit

try:
    from scripts import build_reddit_candidate as candidate
except ModuleNotFoundError:  # Direct script execution.
    import build_reddit_candidate as candidate


SPEC_SCHEMA_V1 = "reddit_voc_candidate_monitor_spec_v1"
SPEC_SCHEMA_V2 = "reddit_voc_candidate_monitor_spec_v2"
RECEIPT_SCHEMA_V1 = "reddit_voc_candidate_monitor_receipt_v1"
RECEIPT_SCHEMA_V2 = "reddit_voc_candidate_monitor_receipt_v2"
PROBE_ID_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
MAX_BODY_BYTES = 5_000_000
ROOT = Path(__file__).resolve().parents[1]


class CandidateMonitorError(ValueError):
    """The monitor specification or an observed payload is unsafe."""


def _utc(value: object) -> str:
    if not isinstance(value, str):
        raise CandidateMonitorError("monitor_observed_at_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CandidateMonitorError("monitor_observed_at_invalid") from exc
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise CandidateMonitorError("monitor_observed_at_invalid")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_file(value: object) -> bytes:
    return candidate.canonical_bytes(value) + b"\n"


def _load_spec(path: Path) -> tuple[dict[str, Any], str]:
    payload = candidate._regular_bytes(Path(path), label="monitor_spec")
    try:
        value = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CandidateMonitorError("monitor_spec_invalid_json") from exc
    if not isinstance(value, dict) or payload != _canonical_file(value):
        raise CandidateMonitorError("monitor_spec_noncanonical")
    schema = value.get("schema_version")
    required_keys = (
        {"schema_version", "observation_interval_seconds", "probes"}
        if schema == SPEC_SCHEMA_V1
        else {
            "schema_version",
            "observation_interval_seconds",
            "terminal_marker",
            "probes",
        }
    )
    if set(value) != required_keys:
        raise CandidateMonitorError("monitor_spec_contract_invalid")
    if schema not in {SPEC_SCHEMA_V1, SPEC_SCHEMA_V2}:
        raise CandidateMonitorError("monitor_spec_schema_invalid")
    interval = value.get("observation_interval_seconds")
    if isinstance(interval, bool) or not isinstance(interval, int) or not 0 <= interval <= 60:
        raise CandidateMonitorError("monitor_interval_invalid")
    probes = value.get("probes")
    if not isinstance(probes, list) or not probes or len(probes) > 64:
        raise CandidateMonitorError("monitor_probes_invalid")
    if schema == SPEC_SCHEMA_V2 and not isinstance(value.get("terminal_marker"), dict):
        raise CandidateMonitorError("monitor_terminal_marker_invalid")
    return value, sha256(payload).hexdigest()


def _inside(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath((str(path), str(root))) == str(root)
    except ValueError:
        return False


def _safe_file_target(target: str, monitor_root: Path) -> str:
    root = Path(os.path.abspath(os.fspath(monitor_root)))
    path = Path(os.path.abspath(target))
    if not _inside(path, root):
        raise CandidateMonitorError("monitor_file_target_outside_root")
    relative = path.relative_to(root)
    for index in range(len(relative.parts) + 1):
        current = root / Path(*relative.parts[:index])
        try:
            metadata = os.lstat(current)
        except FileNotFoundError:
            break
        except OSError as exc:
            raise CandidateMonitorError("monitor_file_target_unsafe") from exc
        if os.path.islink(current):
            raise CandidateMonitorError("monitor_file_target_unsafe")
        if index < len(relative.parts) and not current.is_dir():
            raise CandidateMonitorError("monitor_file_target_unsafe")
    return str(path)


def _safe_http_target(
    target: str,
    *,
    public_http_allowlist: Collection[str],
    resolver: Callable[..., Any],
) -> str:
    parsed = urlsplit(target)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise CandidateMonitorError("monitor_http_target_invalid")
    hostname = parsed.hostname.rstrip(".").lower()
    allowed_public = {item.rstrip(".").lower() for item in public_http_allowlist}
    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        literal = None
    if hostname == "localhost" or (literal is not None and literal.is_loopback):
        return target
    if literal is not None:
        raise CandidateMonitorError("monitor_http_target_not_allowed")
    if hostname not in allowed_public:
        raise CandidateMonitorError("monitor_http_target_not_allowed")
    try:
        addresses = {
            ipaddress.ip_address(item[4][0])
            for item in resolver(
                hostname,
                parsed.port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        }
    except (OSError, ValueError) as exc:
        raise CandidateMonitorError("monitor_http_target_resolution_failed") from exc
    if not addresses or any(not address.is_global for address in addresses):
        raise CandidateMonitorError("monitor_http_target_not_public")
    return target


def _probe(
    value: object,
    *,
    monitor_root: Path,
    public_http_allowlist: Collection[str],
    resolver: Callable[..., Any],
) -> dict[str, Any]:
    keys = {
        "id",
        "kind",
        "target",
        "expected_sha256",
        "expected_http_status",
        "status_path",
        "terminal_values",
        "timeout_seconds",
    }
    if not isinstance(value, dict) or set(value) != keys:
        raise CandidateMonitorError("monitor_probe_contract_invalid")
    probe_id = value.get("id")
    kind = value.get("kind")
    target = value.get("target")
    expected_sha = value.get("expected_sha256")
    expected_http_status = value.get("expected_http_status")
    status_path = value.get("status_path")
    terminal_values = value.get("terminal_values")
    timeout_seconds = value.get("timeout_seconds")
    if (
        not isinstance(probe_id, str)
        or PROBE_ID_RE.fullmatch(probe_id) is None
        or kind not in {"file", "http"}
        or not isinstance(target, str)
        or not target
        or (
            expected_sha is not None
            and (not isinstance(expected_sha, str) or candidate.SHA256_RE.fullmatch(expected_sha) is None)
        )
        or not isinstance(status_path, list)
        or not status_path
        or any(not isinstance(item, str) or not item for item in status_path)
        or not isinstance(terminal_values, list)
        or not terminal_values
        or any(not isinstance(item, str) or not item for item in terminal_values)
        or terminal_values != sorted(set(terminal_values))
    ):
        raise CandidateMonitorError("monitor_probe_contract_invalid")
    if kind == "file":
        if expected_http_status is not None or timeout_seconds is not None:
            raise CandidateMonitorError("monitor_file_probe_contract_invalid")
        value = dict(value)
        value["target"] = _safe_file_target(target, monitor_root)
    else:
        if (
            isinstance(expected_http_status, bool)
            or not isinstance(expected_http_status, int)
            or not 100 <= expected_http_status <= 599
            or isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, int)
            or not 1 <= timeout_seconds <= 30
        ):
            raise CandidateMonitorError("monitor_http_probe_contract_invalid")
        value = dict(value)
        value["target"] = _safe_http_target(
            target,
            public_http_allowlist=public_http_allowlist,
            resolver=resolver,
        )
    return value


def _status(payload: bytes, path: list[str]) -> str:
    try:
        value: object = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CandidateMonitorError("monitor_probe_body_invalid_json") from exc
    for key in path:
        if not isinstance(value, Mapping) or key not in value:
            raise CandidateMonitorError("monitor_probe_status_missing")
        value = value[key]
    if not isinstance(value, str) or not value:
        raise CandidateMonitorError("monitor_probe_status_invalid")
    return value


def _http_payload(
    target: str,
    *,
    timeout_seconds: int,
    urlopen_fn: Callable[..., Any],
) -> tuple[bytes, int]:
    request = urlrequest.Request(
        target,
        method="GET",
        headers={"Accept": "application/json", "User-Agent": "reddit-voc-candidate-monitor/1"},
    )
    try:
        with urlopen_fn(request, timeout=timeout_seconds) as response:
            final_url = response.geturl() if hasattr(response, "geturl") else target
            if final_url != target:
                raise CandidateMonitorError("monitor_http_redirect_forbidden")
            status = int(response.getcode())
            if 300 <= status < 400:
                raise CandidateMonitorError("monitor_http_redirect_forbidden")
            payload = response.read(MAX_BODY_BYTES + 1)
    except urlerror.HTTPError as exc:
        status = int(exc.code)
        if 300 <= status < 400:
            raise CandidateMonitorError("monitor_http_redirect_forbidden") from exc
        payload = exc.read(MAX_BODY_BYTES + 1)
    except (OSError, TimeoutError, urlerror.URLError) as exc:
        raise CandidateMonitorError("monitor_http_read_failed") from exc
    if len(payload) > MAX_BODY_BYTES:
        raise CandidateMonitorError("monitor_probe_body_too_large")
    return payload, status


def _observe(
    probe: Mapping[str, Any],
    *,
    urlopen_fn: Callable[..., Any],
) -> dict[str, Any]:
    try:
        if probe["kind"] == "file":
            payload = candidate._regular_bytes(Path(str(probe["target"])), label="monitor_probe")
            http_status: int | None = None
        else:
            payload, http_status = _http_payload(
                str(probe["target"]),
                timeout_seconds=int(probe["timeout_seconds"]),
                urlopen_fn=urlopen_fn,
            )
        digest = sha256(payload).hexdigest()
        observed_status = _status(payload, list(probe["status_path"]))
        expected_sha = probe["expected_sha256"]
        expected_http_status = probe["expected_http_status"]
        reasons: list[str] = []
        if expected_sha is not None and digest != expected_sha:
            reasons.append("body_sha256_mismatch")
        if expected_http_status is not None and http_status != expected_http_status:
            reasons.append("http_status_mismatch")
        terminal = observed_status in set(probe["terminal_values"])
        if not terminal:
            reasons.append("nonterminal_status")
        return {
            "probe_id": probe["id"],
            "kind": probe["kind"],
            "byte_count": len(payload),
            "body_sha256": digest,
            "http_status": http_status,
            "observed_status": observed_status,
            "terminal": terminal,
            "passed": not reasons,
            "reason_codes": sorted(reasons),
        }
    except CandidateMonitorError as exc:
        return {
            "probe_id": probe["id"],
            "kind": probe["kind"],
            "byte_count": None,
            "body_sha256": None,
            "http_status": None,
            "observed_status": None,
            "terminal": False,
            "passed": False,
            "reason_codes": [str(exc)],
        }


def build_monitor_receipt(
    *,
    spec_path: Path,
    output_path: Path,
    observed_at_utc: str,
    urlopen_fn: Callable[..., Any] | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    monitor_root: Path = ROOT,
    public_http_allowlist: Collection[str] = (),
    resolver: Callable[..., Any] = socket.getaddrinfo,
) -> dict[str, Any]:
    spec, spec_sha = _load_spec(spec_path)
    schema = str(spec["schema_version"])
    probes = [
        _probe(
            value,
            monitor_root=monitor_root,
            public_http_allowlist=public_http_allowlist,
            resolver=resolver,
        )
        for value in spec["probes"]
    ]
    terminal_marker = (
        _probe(
            spec["terminal_marker"],
            monitor_root=monitor_root,
            public_http_allowlist=public_http_allowlist,
            resolver=resolver,
        )
        if schema == SPEC_SCHEMA_V2
        else None
    )
    if urlopen_fn is None:
        class _NoRedirect(urlrequest.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None

        urlopen_fn = urlrequest.build_opener(
            urlrequest.ProxyHandler({}), _NoRedirect()
        ).open
    probe_ids = [str(value["id"]) for value in probes]
    if terminal_marker is not None:
        probe_ids.append(str(terminal_marker["id"]))
    if len(probe_ids) != len(set(probe_ids)):
        raise CandidateMonitorError("monitor_probe_id_duplicate")

    marker_first: dict[str, Any] | None = None
    marker_second: dict[str, Any] | None = None
    if terminal_marker is not None:
        marker_first = _observe(terminal_marker, urlopen_fn=urlopen_fn)
        if not marker_first["passed"]:
            receipt = {
                "schema_version": RECEIPT_SCHEMA_V2,
                "status": "blocked",
                "observed_at_utc": _utc(observed_at_utc),
                "spec_sha256": spec_sha,
                "observation_interval_seconds": int(spec["observation_interval_seconds"]),
                "probe_count": len(probes),
                "terminal": False,
                "quiescent": False,
                "reason_codes": sorted(set(marker_first["reason_codes"])),
                "terminal_marker": {
                    "first_observation": marker_first,
                    "second_observation": None,
                    "priority_short_circuit": True,
                },
                "first_observation": [],
                "second_observation": [],
                "boundaries": dict(candidate.SAFE_BOUNDARIES),
            }
            write_status = candidate._write_immutable(
                Path(output_path), receipt, label="candidate_monitor_receipt"
            )
            return {
                "schema_version": "reddit_voc_candidate_monitor_result_v1",
                "status": receipt["status"],
                "write_status": write_status,
                "receipt_path": str(Path(output_path).absolute()),
                "receipt_sha256": sha256(_canonical_file(receipt)).hexdigest(),
                "production_unchanged": True,
                "remote_write": False,
                "schedule_change": False,
            }

    first = [_observe(value, urlopen_fn=urlopen_fn) for value in probes]
    interval = int(spec["observation_interval_seconds"])
    if interval:
        sleep_fn(float(interval))
    if terminal_marker is not None:
        marker_second = _observe(terminal_marker, urlopen_fn=urlopen_fn)
        if not marker_second["passed"]:
            receipt = {
                "schema_version": RECEIPT_SCHEMA_V2,
                "status": "blocked",
                "observed_at_utc": _utc(observed_at_utc),
                "spec_sha256": spec_sha,
                "observation_interval_seconds": interval,
                "probe_count": len(probes),
                "terminal": False,
                "quiescent": False,
                "reason_codes": sorted(set(marker_second["reason_codes"])),
                "terminal_marker": {
                    "first_observation": marker_first,
                    "second_observation": marker_second,
                    "priority_short_circuit": True,
                },
                "first_observation": first,
                "second_observation": [],
                "boundaries": dict(candidate.SAFE_BOUNDARIES),
            }
            write_status = candidate._write_immutable(
                Path(output_path), receipt, label="candidate_monitor_receipt"
            )
            return {
                "schema_version": "reddit_voc_candidate_monitor_result_v1",
                "status": receipt["status"],
                "write_status": write_status,
                "receipt_path": str(Path(output_path).absolute()),
                "receipt_sha256": sha256(_canonical_file(receipt)).hexdigest(),
                "production_unchanged": True,
                "remote_write": False,
                "schedule_change": False,
            }
    second = [_observe(value, urlopen_fn=urlopen_fn) for value in probes]
    marker_quiescent = marker_first == marker_second if terminal_marker is not None else True
    quiescent = first == second and marker_quiescent
    terminal = all(bool(value["terminal"]) for value in second) and (
        bool(marker_second and marker_second["terminal"])
        if terminal_marker is not None
        else True
    )
    passed = quiescent and terminal and all(bool(value["passed"]) for value in second)
    reason_codes = {
        reason
        for value in (*first, *second)
        for reason in value["reason_codes"]
    }
    if not quiescent:
        reason_codes.add("observations_changed")
    receipt = {
        "schema_version": RECEIPT_SCHEMA_V2 if terminal_marker is not None else RECEIPT_SCHEMA_V1,
        "status": "passed" if passed else "blocked",
        "observed_at_utc": _utc(observed_at_utc),
        "spec_sha256": spec_sha,
        "observation_interval_seconds": interval,
        "probe_count": len(probes),
        "terminal": terminal,
        "quiescent": quiescent,
        "reason_codes": sorted(reason_codes),
        **(
            {
                "terminal_marker": {
                    "first_observation": marker_first,
                    "second_observation": marker_second,
                    "priority_short_circuit": False,
                }
            }
            if terminal_marker is not None
            else {}
        ),
        "first_observation": first,
        "second_observation": second,
        "boundaries": dict(candidate.SAFE_BOUNDARIES),
    }
    write_status = candidate._write_immutable(
        Path(output_path), receipt, label="candidate_monitor_receipt"
    )
    return {
        "schema_version": "reddit_voc_candidate_monitor_result_v1",
        "status": receipt["status"],
        "write_status": write_status,
        "receipt_path": str(Path(output_path).absolute()),
        "receipt_sha256": sha256(_canonical_file(receipt)).hexdigest(),
        "production_unchanged": True,
        "remote_write": False,
        "schedule_change": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--observed-at-utc", required=True)
    args = parser.parse_args()
    try:
        result = build_monitor_receipt(
            spec_path=args.spec,
            output_path=args.output,
            observed_at_utc=args.observed_at_utc,
        )
    except (CandidateMonitorError, candidate.CandidateRegistrationError) as exc:
        print(str(exc))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "passed" else 3


if __name__ == "__main__":
    raise SystemExit(main())
