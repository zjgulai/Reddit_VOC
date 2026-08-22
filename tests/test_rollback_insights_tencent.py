from __future__ import annotations

from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
from typing import Any, cast


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "scripts/rollback_insights_tencent.sh"
STAGER = ROOT / "scripts/stage_reddit_rollback_evidence.py"
REMOTE_TMP = "/tmp/reddit-voc-insights-rollback.TEST123"
EVIDENCE_ROOT = "/opt/reddit-voc-insights-site/evidence"
CURRENT_SITE = "a" * 64
TARGET_SITE = "b" * 64
CURRENT_DATA = "reddit_voc_release_current_fixture"
TARGET_DATA = "reddit_voc_release_target_fixture"
CURRENT_POINTER = "c" * 64
TARGET_POINTER = "d" * 64
PERSIST_ACTION = "persist_exact_rollback_authority_evidence"
ALLOWED_ACTIONS = [
    "read_only_remote_preflight",
    "upload_exact_release_artifacts_to_isolated_directory",
    "verify_exact_remote_artifact_hashes",
    "stage_exact_insights_data_release",
    "load_exact_linux_amd64_image",
    "start_only_reddit_voc_insights_candidate_18339",
    "run_candidate_runtime_smoke",
    "compare_and_swap_only_insights_current",
    "compare_and_swap_only_insights_data_current",
    "run_public_production_acceptance",
    PERSIST_ACTION,
    "rollback_only_insights_current",
    "rollback_only_insights_data_current",
]
FORBIDDEN_ACTIONS = [
    "modify_collector",
    "restart_collector",
    "modify_cron",
    "modify_shared_nginx",
    "modify_tls",
    "modify_dns",
    "modify_other_docker_environment",
    "docker_prune",
    "provider_call",
    "database_write",
    "schedule_change",
    "live_send",
    "enable_candidate_registry_automation",
    "claim_four_exports_complete",
]


def _canonical_json(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        + b"\n"
    )


def _write_evidence(path: Path, value: dict[str, Any]) -> str:
    raw = _canonical_json(value)
    path.write_bytes(raw)
    path.chmod(0o600)
    return sha256(raw).hexdigest()


def _write_executable(path: Path, source: str) -> None:
    path.write_text(source, encoding="utf-8")
    path.chmod(0o755)


def _runtime_bundle_digest() -> str:
    runtime_shas = {
        "runner": sha256(
            (ROOT / "scripts/remote_rollback_insights.sh").read_bytes()
        ).hexdigest(),
        "patcher": sha256(
            (ROOT / "scripts/patch_insights_nginx.py").read_bytes()
        ).hexdigest(),
        "stager": sha256(STAGER.read_bytes()).hexdigest(),
    }
    digest = sha256()
    names = {
        "runner": "remote_rollback_insights.sh",
        "patcher": "patch_insights_nginx.py",
        "stager": "stage_reddit_rollback_evidence.py",
    }
    for label in sorted(names):
        digest.update(label.encode("ascii"))
        digest.update(b"\0")
        digest.update(names[label].encode("ascii"))
        digest.update(b"\0")
        digest.update(runtime_shas[label].encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _authority_records(
    root: Path,
    *,
    include_persist_action: bool = True,
    expiry_at: str = "2099-07-24T11:00:00Z",
) -> dict[str, tuple[Path, str]]:
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    root.chmod(0o700)
    runner_sha = sha256(
        (ROOT / "scripts/remote_rollback_insights.sh").read_bytes()
    ).hexdigest()
    baseline_path = root / "production_baseline.json"
    baseline = {
        "current_release_sha256": TARGET_SITE,
        "evidence_grade": "L3-production-read-only",
        "observations": {
            "insights": {
                "internal_pointer": TARGET_DATA,
                "internal_pointer_sha256": TARGET_POINTER,
                "internal_release_sha256": TARGET_SITE,
                "release_label": TARGET_SITE,
            },
            "site_data_tuple": {
                "data_release_id": TARGET_DATA,
                "pointer_sha256": TARGET_POINTER,
                "site_release_sha256": TARGET_SITE,
            },
        },
        "observed_at_utc": "2026-07-24T10:00:00Z",
        "production_unchanged": True,
        "remote_write": False,
        "schema_version": "reddit_voc_production_baseline_receipt_v1",
        "status": "passed",
    }
    baseline_sha = _write_evidence(baseline_path, baseline)
    actions = list(ALLOWED_ACTIONS)
    if not include_persist_action:
        actions.remove(PERSIST_ACTION)
    execution_runtime = {
        "remote_rollback": {
            "bytes": (
                ROOT / "scripts/remote_rollback_insights.sh"
            ).stat().st_size,
            "path": "scripts/remote_rollback_insights.sh",
            "sha256": runner_sha,
        }
    }
    packet_path = root / "authorization_packet.json"
    packet = {
        "artifacts": {
            "production_baseline_receipt": {
                "bytes": baseline_path.stat().st_size,
                "path": "production_baseline.json",
                "sha256": baseline_sha,
            }
        },
        "authorization": {
            "allowed_actions": actions,
            "consumed": False,
            "forbidden_actions": list(FORBIDDEN_ACTIONS),
            "permit_required": True,
            "promotion_authorized": False,
        },
        "evidence": {
            "baseline_max_age_seconds": 3600,
        },
        "execution_runtime": execution_runtime,
        "expires_at_utc": expiry_at,
        "generated_at_utc": "2026-07-24T10:01:00Z",
        "nonce": "fixture-nonce-00000001",
        "packet_id": "fixture-packet-id",
        "rollback": {
            "readiness_mode": "immediate_same_baseline_window",
            "ready": True,
            "scope": "insights_site_and_data_current",
            "shared_nginx_change_allowed": False,
            "target_data_pointer_sha256": TARGET_POINTER,
            "target_data_release_id": TARGET_DATA,
            "target_release_sha256": TARGET_SITE,
            "valid_until_utc": expiry_at,
        },
        "schema_version": "reddit_voc_promotion_packet_v4",
        "status": "ready_for_owner_authorization",
        "target": {
            "data_release_id": CURRENT_DATA,
            "expected_current_data_pointer_sha256": TARGET_POINTER,
            "expected_current_data_release_id": TARGET_DATA,
            "expected_current_release_sha256": TARGET_SITE,
            "release_sha256": CURRENT_SITE,
            "target_data_pointer_sha256": CURRENT_POINTER,
        },
    }
    packet_sha = _write_evidence(packet_path, packet)
    permit_path = root / "authorization_permit.json"
    permit = {
        "authorization": {
            "authorized_actions": actions,
            "authorized_at_utc": "2026-07-24T10:02:00Z",
            "authorized_by": "owner_explicit_confirmation",
            "forbidden_actions": list(FORBIDDEN_ACTIONS),
            "owner_confirmation": (
                "authorize_exact_reddit_voc_packet_and_release"
            ),
        },
        "authorized_actions": actions,
        "authorized_recorded_at_utc": "2026-07-24T10:02:00Z",
        "consumed": False,
        "contract": "reddit_voc_promotion_permit_exact_binding_v4",
        "expires_at_utc": expiry_at,
        "forbidden_actions": list(FORBIDDEN_ACTIONS),
        "packet": {
            "data_release_id": CURRENT_DATA,
            "execution_runtime": execution_runtime,
            "expected_current_data_pointer_sha256": TARGET_POINTER,
            "expected_current_data_release_id": TARGET_DATA,
            "expected_current_release_sha256": TARGET_SITE,
            "expires_at_utc": expiry_at,
            "nonce": packet["nonce"],
            "packet_id": packet["packet_id"],
            "packet_sha256": packet_sha,
            "release_sha256": CURRENT_SITE,
            "target_data_pointer_sha256": CURRENT_POINTER,
        },
        "packet_id": packet["packet_id"],
        "packet_sha256": packet_sha,
        "release_sha256": CURRENT_SITE,
        "schema_version": "reddit_voc_promotion_permit_v1",
        "scope": "insights_site_and_data_current",
        "status": "authorized_unconsumed",
    }
    permit_sha = _write_evidence(permit_path, permit)
    return {
        "authorization_packet": (packet_path, packet_sha),
        "authorization_permit": (permit_path, permit_sha),
        "production_baseline": (baseline_path, baseline_sha),
    }


def _fake_transport(
    tmp_path: Path,
) -> tuple[dict[str, str], Path, Path]:
    binaries = tmp_path / "fake-bin"
    binaries.mkdir()
    log = tmp_path / "transport.log"
    key = tmp_path / "DDDD.pem"
    known_hosts = tmp_path / "known_hosts"
    key.write_text("fixture-key\n", encoding="utf-8")
    key.chmod(0o600)
    known_hosts.write_text("fixture-host-key\n", encoding="utf-8")

    _write_executable(
        binaries / "ssh-keygen",
        "#!/usr/bin/env bash\nset -euo pipefail\nexit 0\n",
    )
    _write_executable(
        binaries / "stat",
        "#!/usr/bin/env bash\nset -euo pipefail\nexit 99\n",
    )
    _write_executable(
        binaries / "scp",
        """#!/usr/bin/env bash
set -euo pipefail
printf 'SCP\\t%s\\n' "$*" >>"${TRANSPORT_LOG}"
exit 0
""",
    )
    _write_executable(
        binaries / "ssh",
        f"""#!/usr/bin/env bash
set -euo pipefail
printf 'SSH\\t%s\\n' "$*" >>"${{TRANSPORT_LOG}}"
command="${{!#}}"
if [[ "${{FAIL_REMOTE_RUNTIME:-0}}" == "1" && \
      "${{command}}" == *" seal-runtime "* ]]; then
  exit 41
fi
case "${{command}}" in
  "mktemp -d /tmp/reddit-voc-insights-rollback.XXXXXXXXXX")
    printf '%s\\n' "{REMOTE_TMP}"
    ;;
  *" seal-runtime "*)
    printf '%s\\n' "${{FAKE_SEALED_RESULT:-/tmp/reddit-voc-insights-rollback-sealed.${{RUNTIME_BUNDLE_SHA}}}}"
    ;;
esac
exit 0
""",
    )
    environment = dict(os.environ)
    environment.update(
        {
            "KNOWN_HOSTS": str(known_hosts),
            "PATH": f"{binaries}:{environment['PATH']}",
            "SSH_KEY": str(key),
            "STAGER_SHA": sha256(STAGER.read_bytes()).hexdigest(),
            "RUNTIME_BUNDLE_SHA": _runtime_bundle_digest(),
            "TRANSPORT_LOG": str(log),
        }
    )
    return environment, log, binaries


def _complete_arguments(tmp_path: Path) -> tuple[list[str], dict[str, str]]:
    records = _authority_records(tmp_path / "authority")
    packet, packet_sha = records["authorization_packet"]
    permit, permit_sha = records["authorization_permit"]
    baseline, baseline_sha = records["production_baseline"]
    digests = {
        "packet": packet_sha,
        "permit": permit_sha,
        "baseline": baseline_sha,
    }
    arguments = [
        "release",
        "--expected-current",
        CURRENT_SITE,
        "--target-release",
        TARGET_SITE,
        "--expected-current-data-release",
        CURRENT_DATA,
        "--expected-current-data-pointer-sha",
        CURRENT_POINTER,
        "--target-data-release",
        TARGET_DATA,
        "--target-data-pointer-sha",
        TARGET_POINTER,
        "--promotion-receipt",
        f"{EVIDENCE_ROOT}/promotion-fixture.json",
        "--promotion-receipt-sha",
        "e" * 64,
        "--authorization-packet",
        str(packet),
        "--authorization-packet-sha",
        digests["packet"],
        "--authorization-permit",
        str(permit),
        "--authorization-permit-sha",
        digests["permit"],
        "--production-baseline",
        str(baseline),
        "--production-baseline-sha",
        digests["baseline"],
    ]
    return arguments, digests


def _run_wrapper(
    arguments: list[str],
    *,
    environment: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(WRAPPER), *arguments],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def test_wrapper_has_valid_bash_syntax() -> None:
    result = subprocess.run(
        ["bash", "-n", str(WRAPPER)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_wrapper_rejects_disable_before_transport(tmp_path: Path) -> None:
    environment, log, _ = _fake_transport(tmp_path)
    result = _run_wrapper(
        ["disable", "--expected-current", "a" * 64],
        environment=environment,
    )
    assert result.returncode != 0
    assert "disable is forbidden" in result.stderr
    assert not log.exists()


def test_wrapper_requires_the_complete_dual_resource_tuple(
    tmp_path: Path,
) -> None:
    environment, log, _ = _fake_transport(tmp_path)
    arguments, _ = _complete_arguments(tmp_path)
    missing_option = arguments.index("--target-data-pointer-sha")
    del arguments[missing_option : missing_option + 2]
    result = _run_wrapper(arguments, environment=environment)
    assert result.returncode != 0
    assert "target data pointer must be a full lowercase SHA-256" in result.stderr
    assert not log.exists()


def test_wrapper_rejects_duplicate_bindings_before_transport(
    tmp_path: Path,
) -> None:
    environment, log, _ = _fake_transport(tmp_path)
    arguments, _ = _complete_arguments(tmp_path)
    arguments.extend(["--target-release", "f" * 64])
    result = _run_wrapper(arguments, environment=environment)
    assert result.returncode != 0
    assert "duplicate rollback argument is forbidden: --target-release" in result.stderr
    assert not log.exists()


def test_wrapper_rejects_remote_receipt_escape_before_transport(
    tmp_path: Path,
) -> None:
    environment, log, _ = _fake_transport(tmp_path)
    arguments, _ = _complete_arguments(tmp_path)
    receipt_index = arguments.index("--promotion-receipt") + 1
    arguments[receipt_index] = f"{EVIDENCE_ROOT}/../promotion-fixture.json"
    result = _run_wrapper(arguments, environment=environment)
    assert result.returncode != 0
    assert "one exact JSON path" in result.stderr
    assert not log.exists()


def test_wrapper_rejects_unsafe_local_authority_before_transport(
    tmp_path: Path,
) -> None:
    environment, log, _ = _fake_transport(tmp_path)
    arguments, _ = _complete_arguments(tmp_path)
    packet_index = arguments.index("--authorization-packet") + 1
    packet = Path(arguments[packet_index])
    packet.unlink()
    real_packet = tmp_path / "real-packet.json"
    digest = _write_evidence(real_packet, {"kind": "packet"})
    packet.symlink_to(real_packet)
    arguments[arguments.index("--authorization-packet-sha") + 1] = digest

    result = _run_wrapper(arguments, environment=environment)
    assert result.returncode != 0
    assert "authorization_packet_path_contains_symlink" in result.stderr
    assert not log.exists()


def test_wrapper_rejects_noncanonical_or_wrong_mode_authority(
    tmp_path: Path,
) -> None:
    environment, log, _ = _fake_transport(tmp_path)
    arguments, _ = _complete_arguments(tmp_path)
    permit = Path(arguments[arguments.index("--authorization-permit") + 1])
    noncanonical = b'{\n  "kind": "permit"\n}\n'
    permit.write_bytes(noncanonical)
    permit.chmod(0o600)
    arguments[arguments.index("--authorization-permit-sha") + 1] = sha256(
        noncanonical
    ).hexdigest()

    noncanonical_result = _run_wrapper(arguments, environment=environment)
    assert noncanonical_result.returncode != 0
    assert "authorization_permit_json_noncanonical" in noncanonical_result.stderr
    assert not log.exists()

    permit.write_bytes(_canonical_json({"kind": "permit"}))
    permit.chmod(0o644)
    arguments[arguments.index("--authorization-permit-sha") + 1] = sha256(
        permit.read_bytes()
    ).hexdigest()
    mode_result = _run_wrapper(arguments, environment=environment)
    assert mode_result.returncode != 0
    assert "authorization_permit_mode_invalid" in mode_result.stderr
    assert not log.exists()


def test_wrapper_rejects_hardlinked_or_sha_mismatched_authority(
    tmp_path: Path,
) -> None:
    environment, log, _ = _fake_transport(tmp_path)
    arguments, _ = _complete_arguments(tmp_path)
    baseline = Path(arguments[arguments.index("--production-baseline") + 1])
    hardlink = tmp_path / "baseline-hardlink.json"
    os.link(baseline, hardlink)

    hardlink_result = _run_wrapper(arguments, environment=environment)
    assert hardlink_result.returncode != 0
    assert "production_baseline_metadata_unsafe" in hardlink_result.stderr
    assert not log.exists()

    hardlink.unlink()
    arguments[arguments.index("--production-baseline-sha") + 1] = "f" * 64
    digest_result = _run_wrapper(arguments, environment=environment)
    assert digest_result.returncode != 0
    assert "production_baseline_sha256_mismatch" in digest_result.stderr
    assert not log.exists()


def test_wrapper_rejects_missing_persist_authority_before_transport(
    tmp_path: Path,
) -> None:
    environment, log, _ = _fake_transport(tmp_path)
    arguments, _ = _complete_arguments(tmp_path)
    records = _authority_records(
        tmp_path / "authority-without-persist",
        include_persist_action=False,
    )
    replacements = {
        "--authorization-packet": records["authorization_packet"],
        "--authorization-permit": records["authorization_permit"],
        "--production-baseline": records["production_baseline"],
    }
    for option, (path, digest) in replacements.items():
        arguments[arguments.index(option) + 1] = str(path)
        arguments[arguments.index(option + "-sha") + 1] = digest

    result = _run_wrapper(arguments, environment=environment)
    assert result.returncode != 0
    assert "authorization_packet_cross_binding_invalid" in result.stderr
    assert not log.exists()


def test_wrapper_uses_only_fake_transport_and_exact_persisted_bindings(
    tmp_path: Path,
) -> None:
    environment, log, _ = _fake_transport(tmp_path)
    arguments, digests = _complete_arguments(tmp_path)
    result = _run_wrapper(arguments, environment=environment)
    assert result.returncode == 0, result.stderr

    lines = log.read_text(encoding="utf-8").splitlines()
    scp_lines = [line for line in lines if line.startswith("SCP\t")]
    ssh_lines = [line for line in lines if line.startswith("SSH\t")]
    assert len(scp_lines) == 6
    assert all(f"ubuntu@101.34.52.232:{REMOTE_TMP}/" in line for line in scp_lines)
    sealed_root = (
        "/tmp/reddit-voc-insights-rollback-sealed."
        + _runtime_bundle_digest()
    )
    assert any(
        "sudo -n /usr/bin/python3 -c" in line
        and " seal-runtime " in line
        and f"--runtime-root {sealed_root}" in line
        for line in ssh_lines
    )
    assert any(
        f"{sealed_root}/stage_reddit_rollback_evidence.py persist" in line
        and f"--authorization-packet-sha {digests['packet']}" in line
        and f"--authorization-permit-sha {digests['permit']}" in line
        and f"--production-baseline-sha {digests['baseline']}" in line
        and f"--evidence-root {EVIDENCE_ROOT}" in line
        and f"--expected-current-release {CURRENT_SITE}" in line
        and f"--target-release {TARGET_SITE}" in line
        for line in ssh_lines
    )

    runner_lines = [
        line
        for line in ssh_lines
        if f"{sealed_root}/remote_rollback_insights.sh release" in line
    ]
    assert len(runner_lines) == 1
    runner = runner_lines[0]
    assert "--expected-current " + "a" * 64 in runner
    assert "--target-release " + "b" * 64 in runner
    assert "--expected-current-data-release reddit_voc_release_current_fixture" in runner
    assert "--target-data-release reddit_voc_release_target_fixture" in runner
    assert (
        f"--authorization-packet "
        f"{EVIDENCE_ROOT}/authorization-packet-{digests['packet']}.json"
        in runner
    )
    assert (
        f"--authorization-permit "
        f"{EVIDENCE_ROOT}/authorization-permit-{digests['permit']}.json"
        in runner
    )
    assert (
        f"--production-baseline "
        f"{EVIDENCE_ROOT}/production-baseline-{digests['baseline']}.json"
        in runner
    )
    assert " disable " not in runner
    expected_order = [
        f"{sealed_root}/remote_rollback_insights.sh",
        "release",
        "--expected-current",
        "a" * 64,
        "--target-release",
        "b" * 64,
        "--expected-current-data-release",
        "reddit_voc_release_current_fixture",
        "--expected-current-data-pointer-sha",
        "c" * 64,
        "--target-data-release",
        "reddit_voc_release_target_fixture",
        "--target-data-pointer-sha",
        "d" * 64,
        "--promotion-receipt",
        f"{EVIDENCE_ROOT}/promotion-fixture.json",
        "--promotion-receipt-sha",
        "e" * 64,
        "--authorization-packet",
        f"{EVIDENCE_ROOT}/authorization-packet-{digests['packet']}.json",
        "--authorization-packet-sha",
        digests["packet"],
        "--authorization-permit",
        f"{EVIDENCE_ROOT}/authorization-permit-{digests['permit']}.json",
        "--authorization-permit-sha",
        digests["permit"],
        "--production-baseline",
        f"{EVIDENCE_ROOT}/production-baseline-{digests['baseline']}.json",
        "--production-baseline-sha",
        digests["baseline"],
        "--patch-script",
        f"{sealed_root}/patch_insights_nginx.py",
    ]
    assert runner.endswith(" ".join(expected_order))

    cleanup_lines = [line for line in ssh_lines if "rm -rf" in line]
    assert len(cleanup_lines) == 2
    assert any(f"rm -rf -- {REMOTE_TMP}" in line for line in cleanup_lines)
    assert any(f"rm -rf -- {sealed_root}" in line for line in cleanup_lines)
    assert all(f"rm -rf -- {EVIDENCE_ROOT}" not in line for line in ssh_lines)
    assert not any(
        f"{REMOTE_TMP}/stage_reddit_rollback_evidence.py persist" in line
        or f"{REMOTE_TMP}/remote_rollback_insights.sh release" in line
        for line in ssh_lines
    )


def test_remote_hash_failure_blocks_runner_and_only_cleans_tmp(
    tmp_path: Path,
) -> None:
    environment, log, _ = _fake_transport(tmp_path)
    arguments, _ = _complete_arguments(tmp_path)
    environment["FAIL_REMOTE_RUNTIME"] = "1"
    result = _run_wrapper(arguments, environment=environment)
    assert result.returncode != 0

    lines = log.read_text(encoding="utf-8").splitlines()
    assert not any(
        "/remote_rollback_insights.sh release" in line
        for line in lines
    )
    cleanup = [line for line in lines if "rm -rf" in line]
    assert len(cleanup) == 2
    assert any(f"rm -rf -- {REMOTE_TMP}" in line for line in cleanup)
    assert any(
        "/tmp/reddit-voc-insights-rollback-sealed." in line
        for line in cleanup
    )
    assert all(f"rm -rf -- {EVIDENCE_ROOT}" not in line for line in lines)


def test_remote_stager_hash_mismatch_blocks_all_authority_persistence(
    tmp_path: Path,
) -> None:
    environment, log, _ = _fake_transport(tmp_path)
    arguments, _ = _complete_arguments(tmp_path)
    environment["FAKE_SEALED_RESULT"] = "/tmp/wrong-sealed-runtime"
    result = _run_wrapper(arguments, environment=environment)
    assert result.returncode != 0
    assert "remote sealed runtime publication failed" in result.stderr

    lines = log.read_text(encoding="utf-8").splitlines()
    assert not any("/stage_reddit_rollback_evidence.py persist" in line for line in lines)
    assert not any(
        "/remote_rollback_insights.sh release" in line
        for line in lines
    )
    cleanup = [line for line in lines if "rm -rf" in line]
    assert len(cleanup) == 2
    assert any(f"rm -rf -- {REMOTE_TMP}" in line for line in cleanup)


def _run_stager(arguments: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(STAGER), *arguments],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def _load_stager_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "stage_reddit_rollback_evidence_under_test",
        STAGER,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return cast(Any, module)


def _persist_arguments(
    staging_root: Path,
    evidence_root: Path,
    records: dict[str, tuple[Path, str]],
) -> list[str]:
    arguments = [
        "persist",
        "--staging-root",
        str(staging_root),
        "--evidence-root",
        str(evidence_root),
    ]
    for label, (path, digest) in records.items():
        option = label.replace("_", "-")
        arguments.extend(
            [
                f"--{option}-source",
                str(path),
                f"--{option}-sha",
                digest,
            ]
        )
    arguments.extend(
        [
            "--expected-current-release",
            CURRENT_SITE,
            "--target-release",
            TARGET_SITE,
            "--expected-current-data-release",
            CURRENT_DATA,
            "--expected-current-data-pointer-sha",
            CURRENT_POINTER,
            "--target-data-release",
            TARGET_DATA,
            "--target-data-pointer-sha",
            TARGET_POINTER,
            "--runner-sha",
            sha256(
                (ROOT / "scripts/remote_rollback_insights.sh").read_bytes()
            ).hexdigest(),
            "--now-utc",
            "2026-07-25T00:00:00Z",
        ]
    )
    return arguments


def test_stager_rehashes_and_publishes_content_addressed_no_replace_files(
    tmp_path: Path,
) -> None:
    staging_root = tmp_path / "stage"
    evidence_root = tmp_path / "evidence"
    staging_root.mkdir(mode=0o700)
    staging_root.chmod(0o700)
    evidence_root.mkdir()
    records = _authority_records(staging_root)

    arguments = _persist_arguments(staging_root, evidence_root, records)
    first = _run_stager(arguments)
    assert first.returncode == 0, first.stderr
    second = _run_stager(arguments)
    assert second.returncode == 0, second.stderr

    prefixes = {
        "authorization_packet": "authorization-packet",
        "authorization_permit": "authorization-permit",
        "production_baseline": "production-baseline",
    }
    for label, (source, digest) in records.items():
        target = evidence_root / f"{prefixes[label]}-{digest}.json"
        assert target.read_bytes() == source.read_bytes()
        metadata = target.stat()
        assert stat.S_IMODE(metadata.st_mode) == 0o600
        assert metadata.st_nlink == 1
        assert sha256(target.read_bytes()).hexdigest() == digest
    assert not list(evidence_root.glob(".*.tmp-*"))


def test_stager_source_requires_exclusive_create_no_replace_and_fsync() -> None:
    source = STAGER.read_text(encoding="utf-8")
    assert "os.O_EXCL" in source
    assert "os.O_NOFOLLOW" in source
    assert "dir_fd=root_descriptor" in source
    assert "_validate_evidence_at(" in source
    assert "renameat2(\n            directory_descriptor," in source
    assert "renameatx_np(\n            directory_descriptor," in source
    assert "os.fsync(descriptor)" in source
    assert "os.fsync(root_descriptor)" in source
    assert "_assert_directory_path_identity(" in source
    assert "renameat2(-100" not in source
    assert "validate_authority_bundle(" in source
    assert "PRODUCTION_RUNTIME_PREFIX" in source


def test_stager_cross_binding_failure_persists_nothing(
    tmp_path: Path,
) -> None:
    staging_root = tmp_path / "stage"
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    records = _authority_records(staging_root)
    permit_path, _permit_sha = records["authorization_permit"]
    permit = json.loads(permit_path.read_text(encoding="utf-8"))
    permit["packet_sha256"] = "f" * 64
    permit["packet"]["packet_sha256"] = "f" * 64
    records["authorization_permit"] = (
        permit_path,
        _write_evidence(permit_path, permit),
    )

    result = _run_stager(
        _persist_arguments(staging_root, evidence_root, records)
    )
    assert result.returncode != 0
    assert "authorization_permit_cross_binding_invalid" in result.stderr
    assert list(evidence_root.iterdir()) == []


def test_stager_rejects_authority_at_exact_expiry_without_persistence(
    tmp_path: Path,
) -> None:
    staging_root = tmp_path / "stage"
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    expiry = "2026-07-25T00:00:00Z"
    records = _authority_records(staging_root, expiry_at=expiry)

    result = _run_stager(
        _persist_arguments(staging_root, evidence_root, records)
    )
    assert result.returncode != 0
    assert "authority_time_binding_invalid" in result.stderr
    assert list(evidence_root.iterdir()) == []


def test_stager_rejects_legacy_v3_authority_without_persistence(
    tmp_path: Path,
) -> None:
    for case in ("packet_v3", "permit_binding_v3"):
        staging_root = tmp_path / f"stage-{case}"
        evidence_root = tmp_path / f"evidence-{case}"
        evidence_root.mkdir()
        records = _authority_records(staging_root)
        if case == "packet_v3":
            path, _digest = records["authorization_packet"]
            document = json.loads(path.read_text(encoding="utf-8"))
            document["schema_version"] = "reddit_voc_promotion_packet_v3"
            records["authorization_packet"] = (
                path,
                _write_evidence(path, document),
            )
        else:
            path, _digest = records["authorization_permit"]
            document = json.loads(path.read_text(encoding="utf-8"))
            document["contract"] = (
                "reddit_voc_promotion_permit_exact_binding_v3"
            )
            records["authorization_permit"] = (
                path,
                _write_evidence(path, document),
            )

        result = _run_stager(
            _persist_arguments(staging_root, evidence_root, records)
        )
        assert result.returncode != 0
        assert list(evidence_root.iterdir()) == []


def test_runtime_seal_uses_stable_bytes_when_uploaded_source_is_replaced(
    tmp_path: Path,
) -> None:
    staging_root = tmp_path / "runtime-stage"
    staging_root.mkdir(mode=0o700)
    staging_root.chmod(0o700)
    original_payloads = {
        "runner": b"#!/usr/bin/env bash\nexit 0\n",
        "patcher": b"#!/usr/bin/env python3\nraise SystemExit(0)\n",
        "stager": b"#!/usr/bin/env python3\nraise SystemExit(0)\n",
    }
    sources: dict[str, tuple[Path, str]] = {}
    names = {
        "runner": "remote_rollback_insights.sh",
        "patcher": "patch_insights_nginx.py",
        "stager": "stage_reddit_rollback_evidence.py",
    }
    for label, name in names.items():
        path = staging_root / name
        path.write_bytes(original_payloads[label])
        path.chmod(0o700)
        sources[label] = (path, sha256(original_payloads[label]).hexdigest())

    stager = _load_stager_module()
    runtime_shas = {
        label: digest for label, (_path, digest) in sources.items()
    }
    runtime_root = tmp_path / (
        "reddit-voc-insights-rollback-sealed."
        + stager.runtime_bundle_sha256(runtime_shas)
    )
    original_reader = stager._read_stable_regular_at
    replaced = False

    def replace_after_stable_read(
        directory_descriptor: int,
        name: str,
        *,
        label: str,
        exact_mode: int | None,
        max_bytes: int | None,
        expected_uid: int | None = None,
    ) -> bytes:
        nonlocal replaced
        payload = original_reader(
            directory_descriptor,
            name,
            label=label,
            exact_mode=exact_mode,
            max_bytes=max_bytes,
            expected_uid=expected_uid,
        )
        if name == names["runner"] and not replaced:
            replacement = staging_root / ".malicious-runner"
            replacement.write_bytes(b"#!/usr/bin/env bash\nexit 91\n")
            replacement.chmod(0o700)
            os.replace(replacement, staging_root / name)
            replaced = True
        return payload

    stager._read_stable_regular_at = replace_after_stable_read
    try:
        sealed = stager.seal_runtime_bundle(
            staging_root=staging_root,
            runtime_root=runtime_root,
            sources=sources,
            source_owner_uid=os.getuid(),
            sealed_owner_uid=os.getuid(),
        )
    finally:
        stager._read_stable_regular_at = original_reader
    assert replaced
    assert (staging_root / names["runner"]).read_bytes() != original_payloads["runner"]
    assert (sealed / names["runner"]).read_bytes() == original_payloads["runner"]
    for path in sealed.iterdir():
        assert stat.S_IMODE(path.stat().st_mode) == 0o555
        assert path.stat().st_nlink == 1
    assert stat.S_IMODE(sealed.stat().st_mode) == 0o555


def test_stager_rejects_source_escape_and_existing_collision(
    tmp_path: Path,
) -> None:
    staging_root = tmp_path / "stage"
    evidence_root = tmp_path / "evidence"
    staging_root.mkdir(mode=0o700)
    staging_root.chmod(0o700)
    evidence_root.mkdir()
    records = _authority_records(staging_root)

    outside = tmp_path / "outside.json"
    outside_digest = _write_evidence(outside, {"kind": "authorization_packet"})
    escaped = dict(records)
    escaped["authorization_packet"] = (outside, outside_digest)
    escape_result = _run_stager(
        _persist_arguments(staging_root, evidence_root, escaped)
    )
    assert escape_result.returncode != 0
    assert "authorization_packet_escaped_staging_root" in escape_result.stderr

    packet_digest = records["authorization_packet"][1]
    collision = evidence_root / f"authorization-packet-{packet_digest}.json"
    collision.write_bytes(_canonical_json({"kind": "wrong"}))
    collision.chmod(0o600)
    collision_result = _run_stager(
        _persist_arguments(staging_root, evidence_root, records)
    )
    assert collision_result.returncode != 0
    assert "existing_authorization_packet_sha256_mismatch" in collision_result.stderr


def test_stager_root_replacement_after_open_fails_closed_without_polluting_replacement(
    tmp_path: Path,
) -> None:
    staging_root = tmp_path / "stage"
    evidence_root = tmp_path / "evidence"
    displaced_root = tmp_path / "evidence-displaced"
    staging_root.mkdir(mode=0o700)
    staging_root.chmod(0o700)
    evidence_root.mkdir()
    records = _authority_records(staging_root)

    stager = _load_stager_module()
    original_rename = stager._rename_noreplace
    replacement_marker = "replacement-owned"
    replaced = False

    def replace_root_then_rename(
        directory_descriptor: int,
        source_name: str,
        destination_name: str,
    ) -> None:
        nonlocal replaced
        if not replaced:
            evidence_root.rename(displaced_root)
            evidence_root.mkdir()
            (evidence_root / replacement_marker).write_text(
                "must remain untouched\n",
                encoding="utf-8",
            )
            replaced = True
        original_rename(
            directory_descriptor,
            source_name,
            destination_name,
        )

    stager._rename_noreplace = replace_root_then_rename
    try:
        stager.persist_evidence(
            staging_root=staging_root,
            evidence_root=evidence_root,
            sources=records,
            expected_current_release=CURRENT_SITE,
            target_release=TARGET_SITE,
            expected_current_data_release=CURRENT_DATA,
            expected_current_data_pointer_sha=CURRENT_POINTER,
            target_data_release=TARGET_DATA,
            target_data_pointer_sha=TARGET_POINTER,
            runner_sha=sha256(
                (ROOT / "scripts/remote_rollback_insights.sh").read_bytes()
            ).hexdigest(),
            now_utc="2026-07-25T00:00:00Z",
        )
    except stager.EvidenceStageError as exc:
        assert str(exc) == "evidence_root_path_identity_changed"
    else:
        raise AssertionError("root replacement must fail closed")
    finally:
        stager._rename_noreplace = original_rename

    assert replaced
    assert sorted(path.name for path in evidence_root.iterdir()) == [
        replacement_marker
    ]
    assert not list(evidence_root.glob("*.json"))
    assert not list(evidence_root.glob(".*.tmp-*"))
