from datetime import datetime, timedelta, timezone
import fcntl
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tarfile


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts/remote_promote_insights_v6.sh"
INSTALLER = ROOT / "scripts/remote_install_insights_release.sh"


def _source() -> str:
    return RUNNER.read_text(encoding="utf-8")


def _heredoc_after(marker: str) -> str:
    source = _source()
    command = source.index(marker)
    start = source.index("<<'PY'", command) + len("<<'PY'")
    if source[start] == "\n":
        start += 1
    end = source.index("\nPY\n", start)
    return source[start:end]


def _installer_heredoc_after(marker: str) -> str:
    source = INSTALLER.read_text(encoding="utf-8")
    command = source.index(marker)
    start = source.index("<<'PY'", command) + len("<<'PY'")
    if source[start] == "\n":
        start += 1
    end = source.index("\nPY\n", start)
    return source[start:end]


def _shell_slice(start_marker: str, end_marker: str) -> str:
    source = _source()
    start = source.index(start_marker)
    end = source.index(end_marker, start)
    return source[start:end]


def _installer_shell_slice(start_marker: str, end_marker: str) -> str:
    source = INSTALLER.read_text(encoding="utf-8")
    start = source.index(start_marker)
    end = source.index(end_marker, start)
    return source[start:end]


def _canonical_json(path: Path, value: object) -> None:
    path.write_bytes(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        + b"\n"
    )


def _canonical_sha256(value: object) -> str:
    return sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def _production_baseline_cas(observed_at_utc: str) -> dict[str, object]:
    return {
        "collector": {
            "container_id": "7" * 64,
            "health": "healthy",
            "restart_count": 0,
        },
        "container_inventory": {
            "count": 3,
            "protected_count": 2,
            "protected_sha256": "9" * 64,
            "sha256": "8" * 64,
        },
        "cron_sha256": "9" * 64,
        "database_identity": "1:2:3",
        "insights": {
            "container_id": "a" * 64,
            "health": "healthy",
            "image_id": "sha256:" + "b" * 64,
            "network_id": "c" * 64,
            "restart_count": 0,
        },
        "lock_identities": {
            name: {
                "device": 1,
                "inode": index + 10,
                "mode": "0600",
                "nlink": 1,
                "path": path,
                "uid": os.getuid(),
            }
            for index, (name, path) in enumerate(
                {
                    "promotion": "/opt/reddit-voc-insights-site/.promotion.lock",
                    "deploy": "/opt/reddit-voc-insights-site/.deploy.lock",
                    "data_release": (
                        "/opt/reddit-voc-insights-data/locks/data-release.lock"
                    ),
                }.items()
            )
        },
        "observed_at_utc": observed_at_utc,
        "report_pointer_identity": "absent",
        "shared_nginx_sha256": "a" * 64,
        "translation": {
            "container_id": "b" * 64,
            "health": "healthy",
            "restart_count": 0,
        },
    }


def _runtime_contract_fixture(tmp_path: Path) -> tuple[list[str], Path, Path]:
    now = datetime.now(timezone.utc)
    generated = (now - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
    authorized = (now - timedelta(minutes=4)).isoformat().replace("+00:00", "Z")
    permit_expiry = (now + timedelta(minutes=30)).isoformat().replace(
        "+00:00", "Z"
    )
    packet_expiry = (now + timedelta(hours=1)).isoformat().replace(
        "+00:00", "Z"
    )
    release = "a" * 64
    current = "b" * 64
    packet_sha = "c" * 64
    permit_sha = "d" * 64
    expected_pointer = "e" * 64
    target_pointer = "f" * 64
    archive_sha = "1" * 64
    runner_sha = "2" * 64
    installer_sha = "3" * 64
    rollback_sha = "4" * 64
    data_release = "reddit_voc_release_target_a1"
    expected_data_release = "reddit_voc_release_current_a1"
    allowed_actions = [
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
        "persist_exact_rollback_authority_evidence",
        "rollback_only_insights_current",
        "rollback_only_insights_data_current",
    ]
    forbidden_actions = [
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
    execution_runtime = {
        "remote_promotion_runner": {
            "bytes": 101,
            "path": "runtime/remote_promote_insights_v6.sh",
            "sha256": runner_sha,
        },
        "remote_installer": {
            "bytes": 102,
            "path": "runtime/remote_install_insights_release.sh",
            "sha256": installer_sha,
        },
        "remote_rollback": {
            "bytes": 103,
            "path": "runtime/remote_rollback_insights.sh",
            "sha256": rollback_sha,
        },
    }
    packet_id = "reddit_voc_promotion_runtime_fixture"
    nonce = "runtime-fixture-nonce-20260724"
    packet = {
        "artifacts": {
            "transfer_tgz": {
                "bytes": 104,
                "path": f"release/reddit-voc-insights-{release}.tgz",
                "sha256": archive_sha,
            }
        },
        "authorization": {
            "allowed_actions": allowed_actions,
            "consumed": False,
            "forbidden_actions": forbidden_actions,
            "permit_required": True,
            "promotion_authorized": False,
            "required_owner_confirmation": ["packet_sha256", "release_sha256"],
        },
        "deferred_debts": {},
        "evidence": {},
        "execution_runtime": execution_runtime,
        "expires_at_utc": packet_expiry,
        "generated_at_utc": generated,
        "nonce": nonce,
        "packet_id": packet_id,
        "production_baseline_cas": _production_baseline_cas(generated),
        "rollback": {
            "readiness_mode": "immediate_same_baseline_window",
            "ready": True,
            "scope": "insights_site_and_data_current",
            "shared_nginx_change_allowed": False,
            "target_data_file_count": 2,
            "target_data_inventory_sha256": "7" * 64,
            "target_data_pointer_sha256": expected_pointer,
            "target_data_release_id": expected_data_release,
            "target_data_total_bytes": 2048,
            "target_release_manifest_sha256": "5" * 64,
            "target_release_sha256": current,
            "target_release_sha256s_sha256": "6" * 64,
            "valid_until_utc": packet_expiry,
        },
        "schema_version": "reddit_voc_promotion_packet_v4",
        "side_effects": {},
        "status": "ready_for_owner_authorization",
        "target": {
            "data_release_id": data_release,
            "expected_current_data_pointer_sha256": expected_pointer,
            "expected_current_data_release_id": expected_data_release,
            "expected_current_release_sha256": current,
            "release_sha256": release,
            "site_url": "https://reddit.lute-tlz-dddd.top",
            "target_data_pointer_sha256": target_pointer,
        },
    }
    permit_packet = {
        "data_release_id": data_release,
        "execution_runtime": execution_runtime,
        "expected_current_data_pointer_sha256": expected_pointer,
        "expected_current_data_release_id": expected_data_release,
        "expected_current_release_sha256": current,
        "expires_at_utc": packet_expiry,
        "nonce": nonce,
        "packet_id": packet_id,
        "packet_sha256": packet_sha,
        "release_sha256": release,
        "target_data_pointer_sha256": target_pointer,
    }
    permit_authorization = {
        "authorized_actions": allowed_actions,
        "authorized_at_utc": authorized,
        "authorized_by": "owner_explicit_confirmation",
        "forbidden_actions": forbidden_actions,
        "owner_confirmation": "authorize_exact_reddit_voc_packet_and_release",
    }
    permit = {
        "authorization": permit_authorization,
        "authorization_id": "owner-auth-runtime-fixture",
        "authorized_actions": allowed_actions,
        "authorized_by": "owner_explicit_confirmation",
        "authorized_recorded_at_utc": authorized,
        "consumed": False,
        "contract": "reddit_voc_promotion_permit_exact_binding_v4",
        "expires_at_utc": permit_expiry,
        "forbidden_actions": forbidden_actions,
        "packet": permit_packet,
        "packet_id": packet_id,
        "packet_sha256": packet_sha,
        "release_sha256": release,
        "schema_version": "reddit_voc_promotion_permit_v1",
        "scope": "insights_site_and_data_current",
        "side_effects": {},
        "status": "authorized_unconsumed",
    }
    packet_path = tmp_path / "packet.json"
    permit_path = tmp_path / "permit.json"
    _canonical_json(packet_path, packet)
    _canonical_json(permit_path, permit)
    arguments = [
        str(packet_path),
        str(permit_path),
        packet_sha,
        permit_sha,
        release,
        current,
        data_release,
        expected_data_release,
        expected_pointer,
        target_pointer,
        archive_sha,
        "104",
        runner_sha,
        "101",
        installer_sha,
        "102",
        rollback_sha,
        "103",
        str(tmp_path / "promotion-transaction.json"),
        str(os.getuid()),
    ]
    return arguments, packet_path, permit_path


def test_remote_promotion_runner_has_valid_bash_syntax() -> None:
    completed = subprocess.run(
        ["bash", "-n", str(RUNNER)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_remote_installer_has_valid_bash_syntax() -> None:
    completed = subprocess.run(
        ["bash", "-n", str(INSTALLER)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_subsequent_data_release_is_shadowed_before_atomic_switch() -> None:
    source = RUNNER.read_text(encoding="utf-8")

    stage = source.index("materialize_data_stage()")
    candidate = source.index('docker run -d --platform linux/amd64 --name "$CANDIDATE"')
    candidate_removed = source.index('docker rm -f "$CANDIDATE" >/dev/null', candidate)
    data_switch = source.index(
        'replace_data_pointer \\\n    "$DATA_ROOT/current" "$PREVIOUS_DATA_TARGET"',
        candidate_removed,
    )
    site_install = source.index('bash "$INSTALLER" "$ARCHIVE" "$ARCHIVE_SHA" "$RELEASE_SHA"')

    assert stage < candidate < candidate_removed < data_switch < site_install
    assert '--mount "type=bind,src=$CANDIDATE_DATA_ROOT,dst=/srv/reddit-voc-data,readonly"' in source
    assert '"$(readlink "$DATA_ROOT/current")" == "$PREVIOUS_DATA_TARGET"' in source


def test_failed_site_install_restores_data_pointer_and_removes_new_release() -> None:
    source = RUNNER.read_text(encoding="utf-8")
    cleanup = source[source.index("cleanup() {") : source.index("trap 'cleanup $?' EXIT")]

    assert "replace_data_pointer" in cleanup
    assert "remove_data_pointer" in cleanup
    assert '"$DATA_RELEASE_COMMITTED" == 1' in cleanup
    assert '"$SITE_COMMITTED" != 1' in cleanup
    assert '"$current_target" != "releases/$DATA_RELEASE_ID"' in cleanup
    assert '"$previous_target" != "releases/$DATA_RELEASE_ID"' in cleanup
    assert 'sudo rm -rf "$DATA_RELEASE_DIR"' in cleanup
    assert "verify_old_data_projection_stable" in cleanup
    assert '"$http_release" == "$EXPECTED_CURRENT"' in cleanup
    assert "data pointer CAS postcondition" in source


def test_site_commit_point_prevents_single_sided_data_rollback() -> None:
    source = RUNNER.read_text(encoding="utf-8")
    site_install = source.index('bash "$INSTALLER" "$ARCHIVE" "$ARCHIVE_SHA" "$RELEASE_SHA"')
    committed = source.index("SITE_COMMITTED=1", site_install)
    final_control_check = source.index(
        "verify_control_plane_baseline_unchanged", committed
    )
    evidence = source.rindex("reconcile_committed_promotion")

    assert site_install < committed < final_control_check < evidence


def test_data_release_pointer_is_manifest_bound_locked_and_read_only() -> None:
    source = RUNNER.read_text(encoding="utf-8")

    assert 'current.get("sha256")' in source
    assert '"$EXPECTED_DATA_POINTER_SHA" == "$TARGET_DATA_POINTER_SHA"' in source
    assert '"$(sha256sum "$POINTER"' in source
    assert '"8:${DATA_LOCK}"' in source
    assert "validate_promotion_transaction_locks" in source
    assert "fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)" in source
    assert 'find "$DATA_STAGE/releases" -type d -exec chmod 0555 {} +' in source
    assert 'data file inventory mismatch' in source
    assert 'data stage symlink forbidden' in source


def test_data_cas_is_bound_to_authorized_old_and_new_identity() -> None:
    source = RUNNER.read_text(encoding="utf-8")

    assert 'if [[ "$#" -ne 12 ]]' in source
    assert 'EXPECTED_CURRENT_DATA_RELEASE_ID="${10}"' in source
    assert 'EXPECTED_CURRENT_DATA_POINTER_SHA="${11}"' in source
    assert 'TARGET_DATA_POINTER_SHA="${12}"' in source
    assert '"$PREVIOUS_DATA_TARGET" == "releases/$EXPECTED_CURRENT_DATA_RELEASE_ID"' in source
    assert '"$(sha256sum "$CURRENT_DATA_POINTER"' in source
    assert 'reddit_voc_promotion_packet_v4' in source
    assert 'compare_and_swap_only_insights_data_current' in source


def test_locks_and_pointer_switch_state_are_fail_closed() -> None:
    source = RUNNER.read_text(encoding="utf-8")

    assert '"7:${PROMOTION_LOCK}"' in source
    assert "bootstrap_promotion_transaction_locks" in source
    assert "validate_promotion_transaction_locks" in source
    assert "opened_metadata.st_dev, opened_metadata.st_ino" in source
    assert '[[ -d "$LOCKS_DIR" && ! -L "$LOCKS_DIR"' in source
    assert '"8:${DATA_LOCK}"' in source
    previous_flag = source.index("DATA_PREVIOUS_SWITCHED=1")
    previous_move = source.index("replace_data_pointer", previous_flag)
    current_flag = source.index("DATA_CURRENT_SWITCHED=1", previous_move)
    current_move = source.index("replace_data_pointer", current_flag)

    assert previous_flag < previous_move < current_flag < current_move


def test_runtime_and_archive_bindings_execute_against_exact_remote_validator(
    tmp_path: Path,
) -> None:
    validator = _heredoc_after('python3 - "$PACKET" "$PERMIT"')
    arguments, _, _ = _runtime_contract_fixture(tmp_path)

    passed = subprocess.run(
        [sys.executable, "-c", validator, *arguments],
        check=False,
        capture_output=True,
        text=True,
    )
    assert passed.returncode == 0, passed.stderr

    archive_substitution = list(arguments)
    archive_substitution[11] = "105"
    rejected_archive = subprocess.run(
        [sys.executable, "-c", validator, *archive_substitution],
        check=False,
        capture_output=True,
        text=True,
    )
    assert rejected_archive.returncode != 0
    assert "release archive is not bound" in rejected_archive.stderr

    installer_substitution = list(arguments)
    installer_substitution[14] = "9" * 64
    rejected_installer = subprocess.run(
        [sys.executable, "-c", validator, *installer_substitution],
        check=False,
        capture_output=True,
        text=True,
    )
    assert rejected_installer.returncode != 0
    assert "execution runtime binding mismatch" in rejected_installer.stderr


def test_authorized_baseline_cas_is_strict_and_bound_before_mutation(
    tmp_path: Path,
) -> None:
    validator = _heredoc_after('python3 - "$PACKET" "$PERMIT"')
    arguments, packet_path, _ = _runtime_contract_fixture(tmp_path)
    passed = subprocess.run(
        [sys.executable, "-c", validator, *arguments],
        check=False,
        capture_output=True,
        text=True,
    )
    assert passed.returncode == 0, passed.stderr
    values = passed.stdout.strip().split("\t")
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    assert values[7] == _canonical_sha256(packet["production_baseline_cas"])
    assert values[-6:] == [
        "2",
        "9" * 64,
        "sha256:" + "b" * 64,
        "c" * 64,
        "1:2:3",
        "absent",
    ]

    del packet["production_baseline_cas"]["container_inventory"][
        "protected_sha256"
    ]
    _canonical_json(packet_path, packet)
    rejected = subprocess.run(
        [sys.executable, "-c", validator, *arguments],
        check=False,
        capture_output=True,
        text=True,
    )
    assert rejected.returncode != 0
    assert "production baseline CAS invalid" in rejected.stderr

    source = _source()
    authorization = source.index('IFS=$\'\\t\' read -r AUTHORIZATION_MODE')
    first_live_cas = source.index(
        "verify_owner_authorized_production_baseline", authorization
    )
    final_live_cas = source.rindex(
        "verify_owner_authorized_production_baseline",
        authorization,
        source.index("TRANSACTION_ARMED=1"),
    )
    journal = source.index('write_journal "prepared"', final_live_cas)
    docker_load = source.index('docker load --input "$TEMP_ROOT/', journal)
    assert authorization < first_live_cas <= final_live_cas < journal < docker_load


def test_live_control_plane_cas_binds_absent_optional_report_pointer(
    tmp_path: Path,
) -> None:
    source = _source()
    first_start = source.index("def file_identity(path: Path) -> str:")
    first_end = source.index("\ndef container_inventories()", first_start)
    first_namespace: dict[str, object] = {"Path": Path}
    exec(source[first_start:first_end], first_namespace)
    file_identity = first_namespace["file_identity"]
    assert callable(file_identity)

    missing = tmp_path / "missing-report-pointer"
    assert file_identity(missing) == "absent"
    present = tmp_path / "database"
    present.write_bytes(b"database")
    observed = file_identity(present)
    assert isinstance(observed, str)
    assert observed.split(":")[1:] == [
        str(present.stat().st_size),
        str(present.stat().st_ino),
    ]

    transaction_marker = "file_identities=\"$(python3 - <<'PY'"
    transaction_start = source.index(transaction_marker)
    second_start = source.index(
        "def identity(path: Path) -> str:", transaction_start
    )
    second_end = source.index("\n\nprint(", second_start)
    second_namespace: dict[str, object] = {"Path": Path}
    exec(source[second_start:second_end], second_namespace)
    identity = second_namespace["identity"]
    assert callable(identity)
    assert identity(missing) == "absent"


def test_transaction_cas_uses_full_protected_inventory_and_file_identities() -> None:
    source = _source()
    inventory = _shell_slice("inventory_identity() {", "\ncandidate_count() {")
    transaction = _shell_slice(
        "verify_control_plane_baseline_unchanged() {",
        "\nverify_committed_site_release_for_recovery() {",
    )
    assert '"container", "ls", "-a", "-q", "--no-trunc"' in inventory
    for field in (
        '"finished_at"',
        '"restart_count"',
        '"started_at"',
        '"state"',
    ):
        assert field in inventory
    assert 'name == "/reddit_voc_insights_web"' in inventory
    assert 'name.startswith("/reddit_voc_insights_candidate_")' in inventory
    assert '"$INVENTORY_COUNT"$\'\\t\'"$INVENTORY_SHA"' in transaction
    assert "reddit_voc_daily.sqlite3" in transaction
    assert "/opt/reddit-voc-report/current" in transaction
    assert "st_mtime_ns" in transaction

    after_candidate = source.index("CANDIDATE_STARTED=0")
    before_data_switch = source.index(
        "verify_control_plane_baseline_unchanged", after_candidate
    )
    after_install = source.index("SITE_COMMITTED=1", before_data_switch)
    final_control = source.index(
        "verify_control_plane_baseline_unchanged", after_install
    )
    reconcile = source.index("reconcile_committed_promotion", final_control)
    assert after_candidate < before_data_switch < after_install < final_control < reconcile


def test_installer_verification_container_is_packet_bound_and_recoverable() -> None:
    installer = INSTALLER.read_text(encoding="utf-8")
    source = _source()
    assert 'VERIFY_CONTAINER_NAME="reddit_voc_insights_verify_${RELEASE_SHA:0:12}"' in installer
    assert 'docker create --name "${VERIFY_CONTAINER_NAME}"' in installer
    assert "com.reddit-voc.component=insights-image-verifier" in installer
    assert "com.reddit-voc.promotion-packet=${INSIGHTS_PARENT_TRANSACTION_PACKET_SHA}" in installer
    assert 'VERIFY_CONTAINER="reddit_voc_insights_verify_${RELEASE_SHA:0:12}"' in source
    inventory = _shell_slice("inventory_identity() {", "\ncandidate_count() {")
    assert "name == verify_container" in inventory
    recovery = _shell_slice(
        "cleanup_exact_recovery_candidate_and_stage() {",
        "\nverify_target_site_transition_runtime_contract() {",
    )
    assert 'name=^/${VERIFY_CONTAINER}$' in recovery
    assert "image verifier recovery contract mismatch" in recovery
    assert 'docker rm -f "$verify_present"' in recovery

    validator = _heredoc_after(
        'python3 - "$candidate_json" "$IMAGE" "$expected_image_id" "$RELEASE_SHA" "$PACKET_SHA"'
    )
    release = "a" * 64
    packet = "b" * 64
    image_id = "sha256:" + "c" * 64
    image_ref = f"reddit-voc-insights:{release}"
    container = {
        "Config": {
            "Image": image_id,
            "Labels": {
                "com.reddit-voc.component": "insights-image-verifier",
                "com.reddit-voc.promotion-packet": packet,
                "com.reddit-voc.release": release,
            },
        },
        "HostConfig": {
            "PortBindings": {},
            "RestartPolicy": {"Name": "no"},
        },
        "Image": image_id,
        "Mounts": [],
        "State": {"Status": "created"},
    }

    def run(value: dict[str, object]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                "-c",
                validator,
                json.dumps([value], separators=(",", ":")),
                image_ref,
                image_id,
                release,
                packet,
            ],
            check=False,
            capture_output=True,
            text=True,
        )

    passed = run(container)
    assert passed.returncode == 0, passed.stderr
    wrong_packet = json.loads(json.dumps(container))
    wrong_packet["Config"]["Labels"]["com.reddit-voc.promotion-packet"] = "d" * 64
    rejected = run(wrong_packet)
    assert rejected.returncode != 0
    assert "image verifier recovery contract mismatch" in rejected.stderr


def test_old_runtime_contract_rejects_extra_network_or_wrong_attachment() -> None:
    validator = _heredoc_after(
        'python3 - "$expected_release" "$expected_image" "$image_id" "$DATA_ROOT"'
    )
    release = "a" * 64
    image_ref = f"reddit-voc-insights:{release}"
    image_id = "sha256:" + "b" * 64
    network_id = "c" * 64
    binding = [{"HostIp": "172.20.0.1", "HostPort": "18338"}]
    container = {
        "Config": {
            "Image": image_ref,
            "Entrypoint": ["/docker-entrypoint.sh"],
            "Cmd": ["nginx", "-g", "daemon off;"],
            "WorkingDir": "/",
            "OpenStdin": False,
            "StdinOnce": False,
            "Tty": False,
            "Env": [
                "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                "NGINX_VERSION=1.29.4",
                "PKG_RELEASE=1",
                "DYNPKG_RELEASE=1",
                "NJS_VERSION=0.9.4",
                "NJS_RELEASE=1",
                "NGINX_ENTRYPOINT_QUIET_LOGS=1",
            ],
            "Healthcheck": {
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
            },
            "Labels": {
                "com.reddit-voc.component": "insights-site",
                "com.reddit-voc.release": release,
            },
            "User": "101:101",
        },
        "HostConfig": {
            "CapAdd": None,
            "CapDrop": ["ALL"],
            "Init": True,
            "Memory": 268435456,
            "NanoCpus": 500000000,
            "NetworkMode": "reddit_voc_insights_net",
            "PidsLimit": 100,
            "PortBindings": {"8080/tcp": binding},
            "Privileged": False,
            "PidMode": "",
            "IpcMode": "private",
            "UTSMode": "",
            "UsernsMode": "",
            "Devices": [],
            "DeviceRequests": None,
            "DeviceCgroupRules": None,
            "Sysctls": None,
            "Ulimits": None,
            "Runtime": "runc",
            "ReadonlyRootfs": True,
            "RestartPolicy": {"Name": "unless-stopped"},
            "SecurityOpt": ["no-new-privileges:true"],
            "Tmpfs": {
                "/tmp": (
                    "rw,noexec,nosuid,nodev,size=32m,uid=101,gid=101,mode=1777"
                )
            },
        },
        "Image": image_id,
        "Mounts": [
            {
                "Destination": "/srv/reddit-voc-data",
                "Propagation": "rprivate",
                "RW": False,
                "Source": "/opt/reddit-voc-insights-data",
                "Type": "bind",
            }
        ],
        "NetworkSettings": {
            "Networks": {
                "reddit_voc_insights_net": {"NetworkID": network_id}
            },
            "Ports": {"8080/tcp": binding},
        },
        "State": {"Health": {"Status": "healthy"}, "Running": True},
    }

    def run(value: dict[str, object], required_network: str = network_id):
        return subprocess.run(
            [
                sys.executable,
                "-c",
                validator,
                release,
                image_ref,
                image_id,
                "/opt/reddit-voc-insights-data",
                "172.20.0.1",
                required_network,
                json.dumps([value], separators=(",", ":")),
            ],
            check=False,
            capture_output=True,
            text=True,
        )

    accepted = run(container)
    assert accepted.returncode == 0, accepted.stderr
    extra_network = json.loads(json.dumps(container))
    extra_network["NetworkSettings"]["Networks"]["other_net"] = {
        "NetworkID": "d" * 64
    }
    assert run(extra_network).returncode != 0
    wrong_attachment = run(container, "d" * 64)
    assert wrong_attachment.returncode != 0
    extra_port = json.loads(json.dumps(container))
    extra_port["HostConfig"]["PortBindings"]["9090/tcp"] = binding
    extra_port["NetworkSettings"]["Ports"]["9090/tcp"] = binding
    assert run(extra_port).returncode != 0
    extra_tmpfs = json.loads(json.dumps(container))
    extra_tmpfs["HostConfig"]["Tmpfs"]["/run"] = "rw,noexec"
    assert run(extra_tmpfs).returncode != 0
    runtime = _shell_slice(
        "verify_interrupted_site_runtime_contract() {",
        "\nexpected_image_id_from_archive() {",
    )
    assert "unexpectedly reached the collector listener" in runtime


def test_expired_permit_allows_only_exact_preexpiry_journal_recovery(
    tmp_path: Path,
) -> None:
    validator = _heredoc_after('python3 - "$PACKET" "$PERMIT"')
    arguments, packet_path, permit_path = _runtime_contract_fixture(tmp_path)
    now = datetime.now(timezone.utc)
    generated = now - timedelta(hours=3)
    authorized = now - timedelta(hours=2, minutes=50)
    started = now - timedelta(hours=2, minutes=40)
    permit_expiry = now - timedelta(hours=2, minutes=30)
    packet_expiry = now - timedelta(hours=2)

    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    permit = json.loads(permit_path.read_text(encoding="utf-8"))
    packet["generated_at_utc"] = generated.isoformat().replace("+00:00", "Z")
    packet["expires_at_utc"] = packet_expiry.isoformat().replace("+00:00", "Z")
    packet["rollback"]["valid_until_utc"] = packet["expires_at_utc"]
    permit["authorization"]["authorized_at_utc"] = authorized.isoformat().replace(
        "+00:00", "Z"
    )
    permit["authorized_recorded_at_utc"] = permit["authorization"][
        "authorized_at_utc"
    ]
    permit["expires_at_utc"] = permit_expiry.isoformat().replace("+00:00", "Z")
    permit["packet"]["expires_at_utc"] = packet["expires_at_utc"]
    _canonical_json(packet_path, packet)
    _canonical_json(permit_path, permit)

    journal = Path(arguments[-2])
    _canonical_json(
        journal,
        {
            "collector_id": "7" * 64,
            "collector_restart_count": 0,
            "container_inventory_sha256": "8" * 64,
            "cron_sha256": "9" * 64,
            "data_pointer_sha256": arguments[9],
            "data_release_id": arguments[6],
            "database_identity": packet["production_baseline_cas"][
                "database_identity"
            ],
            "expected_current_data_pointer_sha256": arguments[8],
            "expected_current_data_release_id": arguments[7],
            "expected_current_release_sha256": arguments[5],
            "original_previous_data_target": "absent",
            "packet_sha256": arguments[2],
            "permit_sha256": arguments[3],
            "phase": "data_committed",
            "previous_data_file_count": 2,
            "previous_data_inventory_sha256": "7" * 64,
            "previous_data_total_bytes": 2048,
            "previous_release_manifest_sha256": "5" * 64,
            "previous_release_sha256s_sha256": "6" * 64,
            "production_baseline_cas": packet["production_baseline_cas"],
            "production_baseline_cas_sha256": _canonical_sha256(
                packet["production_baseline_cas"]
            ),
            "release_sha256": arguments[4],
            "report_pointer_identity": packet["production_baseline_cas"][
                "report_pointer_identity"
            ],
            "schema_version": "reddit_voc_promotion_transaction_v3",
                "shared_nginx_sha256": "a" * 64,
                "target_image_id": "sha256:" + "d" * 64,
                "transaction_started_at_utc": started.isoformat().replace(
                "+00:00", "Z"
            ),
            "translation_id": "b" * 64,
            "translation_restart_count": 0,
            "unrelated_container_inventory_count": 2,
            "unrelated_container_inventory_sha256": "9" * 64,
        },
    )
    journal.chmod(0o600)
    exact_journal = json.loads(journal.read_text(encoding="utf-8"))
    drifted_journal = json.loads(journal.read_text(encoding="utf-8"))
    drifted_journal["collector_id"] = "0" * 64
    _canonical_json(journal, drifted_journal)
    journal.chmod(0o600)
    rejected_drift = subprocess.run(
        [sys.executable, "-c", validator, *arguments],
        check=False,
        capture_output=True,
        text=True,
    )
    assert rejected_drift.returncode != 0
    assert "recovery journal identity mismatch" in rejected_drift.stderr
    assert journal.exists()
    _canonical_json(journal, exact_journal)
    journal.chmod(0o600)
    recovered = subprocess.run(
        [sys.executable, "-c", validator, *arguments],
        check=False,
        capture_output=True,
        text=True,
    )
    assert recovered.returncode == 0, recovered.stderr
    assert recovered.stdout.split("\t", 1)[0] == "recovery"

    journal.unlink()
    fresh_attempt = subprocess.run(
        [sys.executable, "-c", validator, *arguments],
        check=False,
        capture_output=True,
        text=True,
    )
    assert fresh_attempt.returncode != 0
    assert "promotion permit expired" in fresh_attempt.stderr

    source = _source()
    recovery_only = source.index('if [[ "$AUTHORIZATION_MODE" == recovery ]]')
    recovery_exit = source.index("cleanup 0", recovery_only)
    docker_load = source.index('docker load --input "$TEMP_ROOT/reddit-voc-insights-')
    assert recovery_only < recovery_exit < docker_load


def test_forward_runner_consumes_only_root_sealed_inputs_without_user_snapshot() -> None:
    source = _source()
    installer = INSTALLER.read_text(encoding="utf-8")

    assert "/tmp/reddit-voc-promote-input" not in source
    assert "snapshot_input()" not in source
    assert 'runtime_root = Path("/opt/reddit-voc-insights-site/runtime")' in source
    assert "promotion inputs are not the exact sealed bundle" in source
    assert "root_before.st_uid != 0" in source
    assert "before.st_uid != 0" in source
    assert "stat.S_IMODE(before.st_mode) != 0o444" in source
    assert "{path.name for path in sealed_root.iterdir()} != set(expected)" in source

    assert "/tmp/reddit-voc-install-input" not in installer
    archive_validation = _installer_shell_slice(
        "snapshot_authenticated_archive() {", "\nexpected_image_id_from_archive() {"
    )
    assert "release archive is not in the sealed promotion bundle" in archive_validation
    assert "before.st_uid != 0" in archive_validation
    assert "stat.S_IMODE(before.st_mode) != 0o444" in archive_validation
    assert 'ARCHIVE="${source}"' in archive_validation


def _write_tar(path: Path, members: list[tarfile.TarInfo]) -> None:
    with tarfile.open(path, "w:gz") as archive:
        for member in members:
            payload = b"payload" if member.isfile() else b""
            archive.addfile(member, io.BytesIO(payload) if payload else None)


def test_tar_member_validator_rejects_traversal_links_and_duplicates(
    tmp_path: Path,
) -> None:
    validator = _heredoc_after('python3 - "$ARCHIVE" "$RELEASE_SHA"')
    release = "a" * 64

    safe_member = tarfile.TarInfo(f"{release}/release-manifest.json")
    safe_member.size = len(b"payload")
    safe_archive = tmp_path / "safe.tgz"
    _write_tar(safe_archive, [safe_member])
    safe = subprocess.run(
        [sys.executable, "-c", validator, str(safe_archive), release],
        check=False,
        capture_output=True,
        text=True,
    )
    assert safe.returncode == 0, safe.stderr

    traversal = tarfile.TarInfo(f"{release}/../escape")
    traversal.size = len(b"payload")
    symlink = tarfile.TarInfo(f"{release}/link")
    symlink.type = tarfile.SYMTYPE
    symlink.linkname = "/etc/passwd"
    duplicate_a = tarfile.TarInfo(f"{release}/duplicate")
    duplicate_a.size = len(b"payload")
    duplicate_b = tarfile.TarInfo(f"{release}/duplicate")
    duplicate_b.size = len(b"payload")
    for name, members in (
        ("traversal", [traversal]),
        ("symlink", [symlink]),
        ("duplicate", [duplicate_a, duplicate_b]),
    ):
        archive_path = tmp_path / f"{name}.tgz"
        _write_tar(archive_path, members)
        completed = subprocess.run(
            [sys.executable, "-c", validator, str(archive_path), release],
            check=False,
            capture_output=True,
            text=True,
        )
        assert completed.returncode != 0, name
        assert "unsafe member" in completed.stderr, name


def test_global_deploy_and_data_locks_have_one_strict_acquisition_order() -> None:
    source = _source()
    bootstrap_start = source.index("bootstrap_promotion_transaction_locks() {")
    bootstrap_end = source.index("\nwrite_journal() {", bootstrap_start)
    bootstrap = source[bootstrap_start:bootstrap_end]
    bindings = bootstrap[: bootstrap.index("<<'PY'")]
    assert bindings.index('"7:${PROMOTION_LOCK}"') < bindings.index(
        '"9:${DEPLOY_LOCK}"'
    ) < bindings.index('"8:${DATA_LOCK}"')
    assert "os.O_NOFOLLOW" in bootstrap
    assert "os.O_CREAT" in bootstrap
    assert "os.O_RDWR" in bootstrap
    assert "os.O_TRUNC" not in bootstrap
    assert "os.execve" in bootstrap
    assert "st_nlink != 1" in bootstrap
    assert "metadata.st_dev, metadata.st_ino" in bootstrap
    assert 'environment["INSIGHTS_PROMOTION_LOCKS_BOOTSTRAPPED"] = "1"' in bootstrap
    assert "touch \"$PROMOTION_LOCK\"" not in source
    assert "exec 7>>" not in source
    assert "exec 9>>" not in source
    assert "exec 8>>" not in source

    recover_call = source.index("\nrecover_stale_journal\n")
    recovery_reverify = source.rfind(
        "validate_promotion_transaction_locks", 0, recover_call
    )
    data_arm = source.index("\nTRANSACTION_ARMED=1")
    data_reverify = source.rfind(
        "validate_promotion_transaction_locks", recover_call, data_arm
    )
    assert recovery_reverify < recover_call < data_reverify < data_arm

    installer = INSTALLER.read_text(encoding="utf-8")
    assert "bootstrap_standalone_transaction_locks" not in installer
    parent_gate = installer.index("validate_parent_transaction_invocation")
    inherited = installer.index("validate_inherited_transaction_locks", parent_gate)
    assert parent_gate < inherited
    assert "standalone installer execution is disabled" in installer


def _run_inherited_lock_validator(
    paths: list[Path],
    *,
    locked: bool,
    swap_first_two: bool = False,
    runner_validator: bool = False,
    replace_first_path_after_open: bool = False,
) -> subprocess.CompletedProcess[str]:
    validator = (
        _heredoc_after("validate_promotion_transaction_locks() {")
        if runner_validator
        else _installer_heredoc_after("validate_inherited_transaction_locks() {")
    )
    descriptors: list[int] = []
    saved_targets: dict[int, int | None] = {}
    try:
        for path in paths:
            path.write_bytes(b"")
            path.chmod(0o600)
            opened = os.open(path, os.O_RDWR)
            descriptor = fcntl.fcntl(opened, fcntl.F_DUPFD, 20)
            os.close(opened)
            if locked:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            descriptors.append(descriptor)

        if replace_first_path_after_open:
            moved = paths[0].with_suffix(".locked-inode")
            paths[0].replace(moved)
            paths[0].write_bytes(b"")
            paths[0].chmod(0o600)

        for source, target in zip(descriptors, (7, 9, 8), strict=True):
            try:
                saved_targets[target] = fcntl.fcntl(target, fcntl.F_DUPFD, 40)
            except OSError:
                saved_targets[target] = None
            os.dup2(source, target, inheritable=True)

        binding_paths = list(paths)
        if swap_first_two:
            binding_paths[0], binding_paths[1] = binding_paths[1], binding_paths[0]
        return subprocess.run(
            [
                sys.executable,
                "-c",
                validator,
                f"7:{binding_paths[0]}",
                f"9:{binding_paths[1]}",
                f"8:{binding_paths[2]}",
            ],
            check=False,
            capture_output=True,
            text=True,
            pass_fds=(7, 9, 8),
        )
    finally:
        for target, saved in saved_targets.items():
            if saved is None:
                try:
                    os.close(target)
                except OSError:
                    pass
            else:
                os.dup2(saved, target, inheritable=True)
                os.close(saved)
        for descriptor in descriptors:
            os.close(descriptor)


def test_installer_inherited_transaction_fds_require_exact_locked_inodes(
    tmp_path: Path,
) -> None:
    paths = [tmp_path / name for name in ("promotion.lock", "deploy.lock", "data.lock")]
    passed = _run_inherited_lock_validator(paths, locked=True)
    assert passed.returncode == 0, passed.stderr

    unlocked = _run_inherited_lock_validator(paths, locked=False)
    assert unlocked.returncode != 0
    assert "is not locked" in unlocked.stderr

    swapped = _run_inherited_lock_validator(paths, locked=True, swap_first_two=True)
    assert swapped.returncode != 0
    assert "is invalid" in swapped.stderr


def test_runner_lock_bootstrap_rejects_symlink_and_hardlink_without_exec(
    tmp_path: Path,
) -> None:
    bootstrap = _heredoc_after("bootstrap_promotion_transaction_locks() {")
    outside = tmp_path / "outside"
    outside.write_text("unchanged\n", encoding="utf-8")
    outside.chmod(0o600)
    linked = tmp_path / "promotion.lock"
    linked.symlink_to(outside)
    deploy = tmp_path / "deploy.lock"
    data = tmp_path / "data.lock"
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            bootstrap,
            "/does/not/matter.sh",
            *[f"argument-{index}" for index in range(12)],
            f"7:{linked}",
            f"9:{deploy}",
            f"8:{data}",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode != 0
    assert outside.read_text(encoding="utf-8") == "unchanged\n"
    assert not deploy.exists()
    assert not data.exists()

    linked.unlink()
    lock = tmp_path / "promotion-hardlink.lock"
    lock.write_bytes(b"")
    lock.chmod(0o600)
    alias = tmp_path / "promotion-hardlink-alias.lock"
    os.link(lock, alias)
    hardlinked = subprocess.run(
        [
            sys.executable,
            "-c",
            bootstrap,
            "/does/not/matter.sh",
            *[f"argument-{index}" for index in range(12)],
            f"7:{lock}",
            f"9:{deploy}",
            f"8:{data}",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert hardlinked.returncode != 0
    assert "lock is unsafe" in hardlinked.stderr
    assert not deploy.exists()
    assert not data.exists()


def test_runner_revalidation_rejects_unlocked_swapped_and_raced_paths(
    tmp_path: Path,
) -> None:
    paths = [tmp_path / name for name in ("promotion.lock", "deploy.lock", "data.lock")]
    passed = _run_inherited_lock_validator(
        paths, locked=True, runner_validator=True
    )
    assert passed.returncode == 0, passed.stderr

    unlocked = _run_inherited_lock_validator(
        paths, locked=False, runner_validator=True
    )
    assert unlocked.returncode != 0
    assert "is not locked" in unlocked.stderr

    swapped = _run_inherited_lock_validator(
        paths, locked=True, swap_first_two=True, runner_validator=True
    )
    assert swapped.returncode != 0
    assert "is invalid" in swapped.stderr

    raced = _run_inherited_lock_validator(
        paths,
        locked=True,
        runner_validator=True,
        replace_first_path_after_open=True,
    )
    assert raced.returncode != 0
    assert "is invalid" in raced.stderr


def test_installer_standalone_gate_fails_closed_and_parent_marker_is_exact() -> None:
    gate = _installer_shell_slice(
        "validate_parent_transaction_invocation() {", "\n\nassert_safe_window() {"
    )
    wrapper = f"""set -euo pipefail
RELEASE_SHA={'a' * 64}
EXPECTED_ARCHIVE_SHA={'b' * 64}
TARGET_IMAGE_ID="${{INSIGHTS_PARENT_TRANSACTION_TARGET_IMAGE_ID:-}}"
{gate}
validate_parent_transaction_invocation
"""
    rejected = subprocess.run(
        ["bash", "-c", wrapper], check=False, capture_output=True, text=True
    )
    assert rejected.returncode != 0
    assert "standalone installer execution is disabled" in rejected.stderr

    environment = dict(os.environ)
    environment.update(
        {
            "INSIGHTS_PARENT_TRANSACTION_LOCKS": "1",
            "INSIGHTS_PARENT_TRANSACTION_MARKER": "reddit_voc_promotion_parent_v1",
            "INSIGHTS_PARENT_TRANSACTION_PACKET_SHA": "c" * 64,
            "INSIGHTS_PARENT_TRANSACTION_RELEASE_SHA": "a" * 64,
            "INSIGHTS_PARENT_TRANSACTION_ARCHIVE_SHA": "b" * 64,
            "INSIGHTS_PARENT_TRANSACTION_DATA_RELEASE_ID": "reddit_voc_release_target_a1",
            "INSIGHTS_PARENT_TRANSACTION_EXPECTED_SITE_RELEASE_SHA": "d" * 64,
            "INSIGHTS_PARENT_TRANSACTION_EXPECTED_DATA_RELEASE_ID": "reddit_voc_release_current_a1",
            "INSIGHTS_PARENT_TRANSACTION_TARGET_DATA_POINTER_SHA": "e" * 64,
            "INSIGHTS_PARENT_TRANSACTION_TARGET_IMAGE_ID": "sha256:" + "f" * 64,
        }
    )
    accepted = subprocess.run(
        ["bash", "-c", wrapper],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert accepted.returncode == 0, accepted.stderr


def _journal_wrapper(tmp_path: Path, commands: str) -> subprocess.CompletedProcess[str]:
    function = _shell_slice("write_journal() {", "\nremove_journal() {")
    journal = tmp_path / "promotion-transaction.json"
    baseline_cas = _production_baseline_cas("2026-07-24T00:00:00Z")
    _canonical_json(
        tmp_path / "packet.json", {"production_baseline_cas": baseline_cas}
    )
    baseline_cas_sha = _canonical_sha256(baseline_cas)
    wrapper = f"""set -euo pipefail
JOURNAL="$1/promotion-transaction.json"
PACKET="$1/packet.json"
PACKET_SHA={'1' * 64}
PERMIT_SHA={'6' * 64}
RELEASE_SHA={'2' * 64}
TARGET_IMAGE_ID=sha256:{'e' * 64}
EXPECTED_CURRENT={'3' * 64}
DATA_RELEASE_ID=reddit_voc_release_target_a1
EXPECTED_CURRENT_DATA_RELEASE_ID=reddit_voc_release_current_a1
TARGET_DATA_POINTER_SHA={'4' * 64}
EXPECTED_CURRENT_DATA_POINTER_SHA={'5' * 64}
EXPECTED_OLD_RELEASE_MANIFEST_SHA={'c' * 64}
EXPECTED_OLD_RELEASE_SHA256SUMS_SHA={'d' * 64}
EXPECTED_OLD_DATA_INVENTORY_SHA={'a' * 64}
EXPECTED_OLD_DATA_FILE_COUNT=1
EXPECTED_OLD_DATA_TOTAL_BYTES=1
PRODUCTION_BASELINE_CAS_SHA={baseline_cas_sha}
TRANSACTION_STARTED_AT_UTC=2026-07-24T00:00:00Z
COLLECTOR_ID={'7' * 64}
COLLECTOR_RESTART=0
TRANSLATION_ID={'b' * 64}
TRANSLATION_RESTART=0
NGINX_SHA={'a' * 64}
CRON_SHA={'9' * 64}
INVENTORY_COUNT=2
INVENTORY_SHA={'9' * 64}
{function}
{commands}
"""
    return subprocess.run(
        ["bash", "-c", wrapper, "journal-test", str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
    )


def test_transaction_journal_executes_all_four_canonical_phases(
    tmp_path: Path,
) -> None:
    commands = "\n".join(
        f'write_journal "{phase}" "absent"; cp "$JOURNAL" "$1/{index}-{phase}.json"'
        for index, phase in enumerate(
            ("prepared", "data_committed", "site_committed", "complete"), 1
        )
    )
    completed = _journal_wrapper(tmp_path, commands)
    assert completed.returncode == 0, completed.stderr
    for index, phase in enumerate(
        ("prepared", "data_committed", "site_committed", "complete"), 1
    ):
        path = tmp_path / f"{index}-{phase}.json"
        raw = path.read_bytes()
        value = json.loads(raw)
        assert value["phase"] == phase
        assert raw == json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode() + b"\n"
        assert stat.S_IMODE(path.stat().st_mode) == 0o600

    linked = _journal_wrapper(
        tmp_path,
        'ln "$JOURNAL" "$1/journal-hardlink.json"; write_journal "prepared" "absent"',
    )
    assert linked.returncode != 0
    assert "promotion journal is unsafe" in linked.stderr


def _run_cleanup_failure(tmp_path: Path, *, committed_site: bool) -> subprocess.CompletedProcess[str]:
    cleanup = _shell_slice("cleanup() {", "\ntrap 'cleanup $?' EXIT")
    pointer_helpers = _shell_slice(
        "pointer_state() {", "\nvalidate_promotion_transaction_locks() {"
    )
    deploy_root = tmp_path / "site"
    data_root = tmp_path / "data"
    (deploy_root / "releases").mkdir(parents=True)
    (data_root / "releases" / "reddit_voc_release_current_a1").mkdir(
        parents=True
    )
    (data_root / "releases" / "reddit_voc_release_target_a1").mkdir()
    site_release = "2" * 64 if committed_site else "3" * 64
    (deploy_root / "current").symlink_to(f"releases/{site_release}")
    (data_root / "current").symlink_to("releases/reddit_voc_release_target_a1")
    (data_root / "previous").symlink_to("releases/reddit_voc_release_current_a1")
    journal = deploy_root / ".promotion-transaction.json"
    journal.write_text("pending\n", encoding="utf-8")
    wrapper = f"""set -euo pipefail
DEPLOY_ROOT="$1/site"
DATA_ROOT="$1/data"
RELEASE_SHA={'2' * 64}
EXPECTED_CURRENT={'3' * 64}
DATA_RELEASE_ID=reddit_voc_release_target_a1
EXPECTED_CURRENT_DATA_RELEASE_ID=reddit_voc_release_current_a1
CANDIDATE=fixture-candidate
CANDIDATE_STARTED=0
DATA_EXTRACT=""
DATA_STAGE=""
INPUT_ROOT=""
TEMP_ROOT=""
DATA_CURRENT_TMP="$DATA_ROOT/.current.tmp"
DATA_PREVIOUS_TMP="$DATA_ROOT/.previous.tmp"
SITE_CURRENT_RECOVERY_TMP="$DEPLOY_ROOT/.site-current.tmp"
DATA_RELEASE_DIR="$DATA_ROOT/releases/$DATA_RELEASE_ID"
PREVIOUS_DATA_TARGET=releases/reddit_voc_release_current_a1
ORIGINAL_DATA_PREVIOUS_TARGET=absent
DATA_CURRENT_SWITCHED=1
DATA_PREVIOUS_SWITCHED=1
DATA_RELEASE_COMMITTED=1
SITE_COMMITTED=0
TRANSACTION_ARMED=1
JOURNAL="$DEPLOY_ROOT/.promotion-transaction.json"
remove_journal() {{ rm -f "$JOURNAL"; }}
fsync_directory() {{ :; }}
validate_promotion_transaction_locks() {{ :; }}
candidate_count() {{ printf '%s\n' 0; }}
port_count() {{ printf '%s\n' 0; }}
verify_old_data_projection_stable() {{ printf '%s\t%s\t%s\n' {'a' * 64} 1 1; }}
sudo() {{ command "$@"; }}
mv() {{
  if [[ "$1" == "-Tf" ]]; then
    python3 -c 'import os,sys; os.replace(sys.argv[1],sys.argv[2])' "$2" "$3"
  else
    command mv "$@"
  fi
}}
docker() {{
  if [[ "$1" == "inspect" ]]; then
    if [[ "$3" == *"Config.Labels"* ]]; then
      printf '%s\n' "{site_release}"
    elif [[ "$3" == *"State.Health"* ]]; then
      printf '%s\n' healthy
    fi
    return 0
  fi
  return 0
}}
{pointer_helpers}
live_site_tuple() {{
  printf '%s\t%s\t%s\t%s\n' \
    "releases/{site_release}" "{site_release}" healthy "{site_release}"
}}
{cleanup}
cleanup 42
"""
    return subprocess.run(
        ["bash", "-c", wrapper, "cleanup-test", str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
    )


def test_installer_nonzero_preserves_new_new_but_rolls_back_only_old_old(
    tmp_path: Path,
) -> None:
    new_new_root = tmp_path / "new-new"
    new_new_root.mkdir()
    committed = _run_cleanup_failure(new_new_root, committed_site=True)
    assert committed.returncode == 42
    assert "preserving the new site/data tuple" in committed.stderr
    assert os.readlink(new_new_root / "data/current") == (
        "releases/reddit_voc_release_target_a1"
    )
    assert (new_new_root / "data/releases/reddit_voc_release_target_a1").is_dir()
    assert (new_new_root / "site/.promotion-transaction.json").exists()

    old_old_root = tmp_path / "old-old"
    old_old_root.mkdir()
    restored = _run_cleanup_failure(old_old_root, committed_site=False)
    assert restored.returncode == 42
    assert os.readlink(old_old_root / "data/current") == (
        "releases/reddit_voc_release_current_a1"
    )
    assert not (old_old_root / "data/releases/reddit_voc_release_target_a1").exists()
    assert not (old_old_root / "site/.promotion-transaction.json").exists()


def _run_recovery_fixture(
    tmp_path: Path,
    *,
    site_release: str,
    data_current: str,
    data_previous: str | None,
    original_previous: str,
    phase: str = "prepared",
    runtime_release: str | None = None,
    runtime_health: str = "healthy",
    http_release: str | None = None,
    runtime_contract_valid: bool = True,
    committed_site_release_valid: bool = True,
    target_site_release_present: bool = False,
    target_data_inventory_valid: bool = True,
    control_baseline_valid: bool = True,
    candidate_residue: bool = False,
) -> subprocess.CompletedProcess[str]:
    release = "2" * 64
    expected = "3" * 64
    packet = "1" * 64
    target_pointer = "4" * 64
    old_pointer = "5" * 64
    baseline_cas = _production_baseline_cas("2026-07-24T00:00:00Z")
    baseline_cas_sha = _canonical_sha256(baseline_cas)
    packet_path = tmp_path / "packet.json"
    _canonical_json(packet_path, {"production_baseline_cas": baseline_cas})
    runtime_release = site_release if runtime_release is None else runtime_release
    http_release = runtime_release if http_release is None else http_release
    deploy_root = tmp_path / "site"
    data_root = tmp_path / "data"
    (deploy_root / "releases").mkdir(parents=True)
    (deploy_root / "evidence").mkdir()
    if candidate_residue:
        (deploy_root / "candidate-residue").write_text("exact\n", encoding="utf-8")
    if target_site_release_present:
        (deploy_root / "releases" / release).mkdir()
    (data_root / "releases/reddit_voc_release_current_a1/public").mkdir(
        parents=True
    )
    (data_root / "releases/reddit_voc_release_target_a1/public").mkdir(
        parents=True
    )
    (deploy_root / "current").symlink_to(f"releases/{site_release}")
    (data_root / "current").symlink_to(data_current)
    if data_previous is not None:
        (data_root / "previous").symlink_to(data_previous)
    journal_value = {
        "collector_id": "7" * 64,
        "collector_restart_count": 0,
        "container_inventory_sha256": "8" * 64,
        "cron_sha256": "9" * 64,
        "data_pointer_sha256": target_pointer,
        "data_release_id": "reddit_voc_release_target_a1",
        "database_identity": baseline_cas["database_identity"],
        "expected_current_data_pointer_sha256": old_pointer,
        "expected_current_data_release_id": "reddit_voc_release_current_a1",
        "expected_current_release_sha256": expected,
        "original_previous_data_target": original_previous,
        "packet_sha256": packet,
        "permit_sha256": "6" * 64,
        "phase": phase,
        "previous_data_file_count": 1,
        "previous_data_inventory_sha256": "a" * 64,
        "previous_data_total_bytes": 1,
        "previous_release_manifest_sha256": "c" * 64,
        "previous_release_sha256s_sha256": "d" * 64,
        "production_baseline_cas": baseline_cas,
        "production_baseline_cas_sha256": baseline_cas_sha,
        "release_sha256": release,
        "target_image_id": "sha256:" + "e" * 64,
        "report_pointer_identity": baseline_cas["report_pointer_identity"],
        "schema_version": "reddit_voc_promotion_transaction_v3",
        "shared_nginx_sha256": "a" * 64,
        "transaction_started_at_utc": "2026-07-24T00:00:00Z",
        "translation_id": "b" * 64,
        "translation_restart_count": 0,
        "unrelated_container_inventory_count": 2,
        "unrelated_container_inventory_sha256": "9" * 64,
    }
    journal = deploy_root / "promotion-transaction.json"
    _canonical_json(journal, journal_value)
    journal.chmod(0o600)
    helpers = _shell_slice(
        "pointer_state() {", "\nvalidate_promotion_transaction_locks() {"
    )
    journal_functions = _shell_slice(
        "write_journal() {", "\nfind_exact_promotion_receipt() {"
    )
    interrupted_completion = _shell_slice(
        "complete_interrupted_site_commit() {", "\nrecover_stale_journal() {"
    )
    reconciliation = _shell_slice(
        "reconcile_committed_promotion() {",
        "\ncomplete_interrupted_site_commit() {",
    )
    recovery = _shell_slice("recover_stale_journal() {", "\ncleanup() {")
    wrapper = f"""set -euo pipefail
DEPLOY_ROOT="$1/site"
DATA_ROOT="$1/data"
BIND_ADDRESS=127.0.0.1
PACKET_SHA={packet}
PERMIT_SHA={'6' * 64}
RELEASE_SHA={release}
TARGET_IMAGE_ID=sha256:{'e' * 64}
EXPECTED_CURRENT={expected}
DATA_RELEASE_ID=reddit_voc_release_target_a1
EXPECTED_CURRENT_DATA_RELEASE_ID=reddit_voc_release_current_a1
TARGET_DATA_POINTER_SHA={target_pointer}
EXPECTED_CURRENT_DATA_POINTER_SHA={old_pointer}
EXPECTED_OLD_RELEASE_MANIFEST_SHA={'c' * 64}
EXPECTED_OLD_RELEASE_SHA256SUMS_SHA={'d' * 64}
EXPECTED_OLD_DATA_INVENTORY_SHA={'a' * 64}
EXPECTED_OLD_DATA_FILE_COUNT=1
EXPECTED_OLD_DATA_TOTAL_BYTES=1
PRODUCTION_BASELINE_CAS_SHA={baseline_cas_sha}
PACKET="{packet_path}"
DATA_RELEASE_DIR="$DATA_ROOT/releases/$DATA_RELEASE_ID"
DATA_CURRENT_TMP="$DATA_ROOT/.current.tmp"
DATA_PREVIOUS_TMP="$DATA_ROOT/.previous.tmp"
SITE_CURRENT_RECOVERY_TMP="$DEPLOY_ROOT/.site-current.tmp"
JOURNAL="$DEPLOY_ROOT/promotion-transaction.json"
TEMP_ROOT="$1/archive"
ORIGINAL_DATA_PREVIOUS_TARGET=absent
RECOVERED_PROMOTION=0
RECOVERED_EVIDENCE=""
SITE_COMMITTED=0
OLD_DATA_INVENTORY_SHA=""
OLD_DATA_FILE_COUNT=""
OLD_DATA_TOTAL_BYTES=""
RUNTIME_CONTRACT_VALID={1 if runtime_contract_valid else 0}
COMMITTED_SITE_RELEASE_VALID={1 if committed_site_release_valid else 0}
TARGET_DATA_INVENTORY_VALID={1 if target_data_inventory_valid else 0}
CURRENT_COLLECTOR_ID={'7' * 64 if control_baseline_valid else 'c' * 64}
RUNTIME_RELEASE="{runtime_release}"
RUNTIME_HEALTH="{runtime_health}"
HTTP_RELEASE="{http_release}"
fail() {{ echo "$1" >&2; exit 1; }}
fsync_directory() {{ :; }}
verify_old_data_projection_stable() {{ printf '%s\t%s\t%s\n' {'a' * 64} 1 1; }}
verify_exact_data_projection() {{
  [[ "$TARGET_DATA_INVENTORY_VALID" == 1 ]] || return 1
  printf '%s\t%s\t%s\n' {'b' * 64} 2 2
}}
verify_committed_site_release_for_recovery() {{
  [[ "$COMMITTED_SITE_RELEASE_VALID" == 1 ]] || fail "committed site release differs from the exact authorized archive"
}}
verify_interrupted_site_runtime_contract() {{
  [[ "$RUNTIME_CONTRACT_VALID" == 1 ]] || fail "interrupted site runtime contract mismatch"
}}
verify_control_plane_baseline_unchanged() {{
  [[ "$COLLECTOR_ID" == "$CURRENT_COLLECTOR_ID" ]] || fail "collector changed during promotion transaction"
}}
cleanup_exact_recovery_candidate_and_stage() {{ rm -f "$DEPLOY_ROOT/candidate-residue"; }}
candidate_count() {{ [[ -e "$DEPLOY_ROOT/candidate-residue" ]] && printf '%s\n' 1 || printf '%s\n' 0; }}
port_count() {{ candidate_count; }}
verify_target_site_transition_runtime_contract() {{ printf '%s\n' "$RUNTIME_HEALTH"; }}
verify_old_site_release_for_recovery() {{ :; }}
expected_image_id_from_archive() {{ printf '%s\n' sha256:{'d' * 64}; }}
restore_old_site_runtime_for_recovery() {{
  RUNTIME_RELEASE="$EXPECTED_CURRENT"
  RUNTIME_HEALTH=healthy
  HTTP_RELEASE="$EXPECTED_CURRENT"
}}
sleep() {{ :; }}
validate_promotion_transaction_locks() {{ :; }}
sudo() {{ command "$@"; }}
sha256sum() {{ printf '%s  %s\n' "$TARGET_DATA_POINTER_SHA" "${{@: -1}}"; }}
mv() {{
  if [[ "$1" == "-Tf" ]]; then
    python3 -c 'import os,sys; os.replace(sys.argv[1],sys.argv[2])' "$2" "$3"
  else
    command mv "$@"
  fi
}}
{helpers}
{journal_functions}
live_site_tuple() {{
  printf '%s\t%s\t%s\t%s\n' \
    "$(pointer_state "$DEPLOY_ROOT/current")" "$RUNTIME_RELEASE" "$RUNTIME_HEALTH" "$HTTP_RELEASE"
}}
find_exact_promotion_receipt() {{ :; }}
write_promotion_receipt() {{ printf '%s\n' reconciled > "$EVIDENCE"; }}
{reconciliation}
{interrupted_completion}
{recovery}
recover_stale_journal
printf 'recovered=%s\n' "$RECOVERED_PROMOTION"
"""
    return subprocess.run(
        ["bash", "-c", wrapper, "recovery-test", str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
    )


def test_previous_only_crash_restores_the_exact_original_previous_pointer(
    tmp_path: Path,
) -> None:
    completed = _run_recovery_fixture(
        tmp_path,
        site_release="3" * 64,
        data_current="releases/reddit_voc_release_current_a1",
        data_previous="releases/reddit_voc_release_current_a1",
        original_previous="absent",
    )
    assert completed.returncode == 0, completed.stderr
    assert os.readlink(tmp_path / "data/current") == (
        "releases/reddit_voc_release_current_a1"
    )
    assert not (tmp_path / "data/previous").exists()
    assert not (tmp_path / "site/promotion-transaction.json").exists()
    assert not (tmp_path / "data/releases/reddit_voc_release_target_a1").exists()


def test_prepared_candidate_crash_is_recovered_before_slot_gate(
    tmp_path: Path,
) -> None:
    completed = _run_recovery_fixture(
        tmp_path,
        site_release="3" * 64,
        data_current="releases/reddit_voc_release_current_a1",
        data_previous=None,
        original_previous="absent",
        phase="prepared",
        candidate_residue=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert not (tmp_path / "site/candidate-residue").exists()
    assert os.readlink(tmp_path / "data/current") == (
        "releases/reddit_voc_release_current_a1"
    )
    assert not (tmp_path / "site/promotion-transaction.json").exists()

    source = _source()
    authorization_mode = source.index('if [[ "$AUTHORIZATION_MODE" == fresh ]]')
    recovery_call = source.index("\nrecover_stale_journal\n", authorization_mode)
    fresh_slot_gate = source.index('candidate slot is occupied', recovery_call)
    assert recovery_call < fresh_slot_gate
    recovery = _shell_slice("recover_stale_journal() {", "\ncleanup() {")
    cleanup_call = recovery.index("cleanup_exact_recovery_candidate_and_stage")
    first_pointer_write = recovery.index("replace_data_pointer", cleanup_call)
    assert cleanup_call < first_pointer_write

    candidate_cleanup = _shell_slice(
        "cleanup_exact_recovery_candidate_and_stage() {",
        "\nverify_target_site_transition_runtime_contract() {",
    )
    for required in (
        '"name=^/${CANDIDATE}$"',
        'labels.get("com.reddit-voc.promotion-packet") != packet',
        'host.get("ReadonlyRootfs") is not True',
        'host.get("Privileged") is not False',
        'host.get("CapAdd") not in (None, [])',
        'host.get("CapDrop") != ["ALL"]',
        'host.get("PidsLimit") != 100',
        'mount.get("RW") is not False',
        'bindings.get("8080/tcp") != expected_binding',
        "validate_recovery_candidate_stage",
        'docker rm -f "$CANDIDATE"',
    ):
        assert required in candidate_cleanup


def test_data_committed_orphan_site_release_is_validated_then_removed(
    tmp_path: Path,
) -> None:
    completed = _run_recovery_fixture(
        tmp_path,
        site_release="3" * 64,
        data_current="releases/reddit_voc_release_target_a1",
        data_previous="releases/reddit_voc_release_current_a1",
        original_previous="absent",
        phase="data_committed",
        target_site_release_present=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert os.readlink(tmp_path / "data/current") == (
        "releases/reddit_voc_release_current_a1"
    )
    assert not (tmp_path / "data/previous").exists()
    assert not (tmp_path / "site/releases" / ("2" * 64)).exists()
    assert not (tmp_path / "data/releases/reddit_voc_release_target_a1").exists()
    assert not (tmp_path / "site/promotion-transaction.json").exists()

    recovery = _shell_slice("recover_stale_journal() {", "\ncleanup() {")
    detected = recovery.index(
        'if [[ -e "$DEPLOY_ROOT/releases/$RELEASE_SHA" || '
        '-L "$DEPLOY_ROOT/releases/$RELEASE_SHA" ]]'
    )
    validated = recovery.index(
        "verify_committed_site_release_for_recovery", detected
    )
    removed = recovery.index(
        'rm -rf "$DEPLOY_ROOT/releases/$RELEASE_SHA"', validated
    )
    fsynced = recovery.index(
        'fsync_directory "$DEPLOY_ROOT/releases"', removed
    )
    assert detected < validated < removed < fsynced


def test_unknown_target_data_inventory_blocks_recovery_before_any_write(
    tmp_path: Path,
) -> None:
    completed = _run_recovery_fixture(
        tmp_path,
        site_release="3" * 64,
        data_current="releases/reddit_voc_release_target_a1",
        data_previous="releases/reddit_voc_release_current_a1",
        original_previous="absent",
        phase="data_committed",
        target_site_release_present=True,
        target_data_inventory_valid=False,
    )
    assert completed.returncode != 0
    assert "stale target data release inventory is unknown" in completed.stderr
    assert os.readlink(tmp_path / "data/current") == (
        "releases/reddit_voc_release_target_a1"
    )
    assert os.readlink(tmp_path / "data/previous") == (
        "releases/reddit_voc_release_current_a1"
    )
    assert (tmp_path / "data/releases/reddit_voc_release_target_a1").exists()
    assert (tmp_path / "site/promotion-transaction.json").exists()


def test_cross_invocation_control_plane_tamper_blocks_recovery_without_writes(
    tmp_path: Path,
) -> None:
    completed = _run_recovery_fixture(
        tmp_path,
        site_release="3" * 64,
        data_current="releases/reddit_voc_release_target_a1",
        data_previous="releases/reddit_voc_release_current_a1",
        original_previous="absent",
        phase="data_committed",
        control_baseline_valid=False,
    )
    assert completed.returncode != 0
    assert "collector changed during promotion transaction" in completed.stderr
    assert os.readlink(tmp_path / "data/current") == (
        "releases/reddit_voc_release_target_a1"
    )
    assert os.readlink(tmp_path / "data/previous") == (
        "releases/reddit_voc_release_current_a1"
    )
    assert (tmp_path / "site/promotion-transaction.json").exists()

    journal_function = _shell_slice("write_journal() {", "\nremove_journal() {")
    recovery = _shell_slice("recover_stale_journal() {", "\ncleanup() {")
    for field in (
        '"permit_sha256"',
        '"transaction_started_at_utc"',
        '"collector_id"',
        '"collector_restart_count"',
        '"translation_id"',
        '"translation_restart_count"',
        '"shared_nginx_sha256"',
        '"cron_sha256"',
        '"container_inventory_sha256"',
        '"previous_release_manifest_sha256"',
        '"previous_release_sha256s_sha256"',
        '"previous_data_inventory_sha256"',
        '"previous_data_file_count"',
        '"previous_data_total_bytes"',
    ):
        assert field in journal_function
    parsed = recovery.index('IFS=$\'\\t\' read -r phase original_previous')
    baseline_check = recovery.index(
        "verify_control_plane_baseline_unchanged", parsed
    )
    first_state_write = recovery.index("replace_data_pointer", baseline_check)
    assert parsed < baseline_check < first_state_write


def test_later_or_unknown_site_tuple_never_writes_recovery_state(
    tmp_path: Path,
) -> None:
    later = "7" * 64
    completed = _run_recovery_fixture(
        tmp_path,
        site_release=later,
        data_current="releases/reddit_voc_release_target_a1",
        data_previous="releases/reddit_voc_release_current_a1",
        original_previous="absent",
        phase="data_committed",
    )
    assert completed.returncode != 0
    assert "no recovery write performed" in completed.stderr
    assert os.readlink(tmp_path / "data/current") == (
        "releases/reddit_voc_release_target_a1"
    )
    assert os.readlink(tmp_path / "data/previous") == (
        "releases/reddit_voc_release_current_a1"
    )
    assert (tmp_path / "site/promotion-transaction.json").exists()
    assert "docker: command not found" not in completed.stderr
    source = _source()
    recovery_call = source.index("\nrecover_stale_journal\n")
    docker_load = source.index('docker load --input "$TEMP_ROOT/reddit-voc-insights-')
    materialize = source.index("\nmaterialize_data_stage\n", docker_load)
    assert recovery_call < docker_load < materialize


def test_crash_after_new_container_health_before_site_pointer_completes_exactly(
    tmp_path: Path,
) -> None:
    completed = _run_recovery_fixture(
        tmp_path,
        site_release="3" * 64,
        runtime_release="2" * 64,
        data_current="releases/reddit_voc_release_target_a1",
        data_previous="releases/reddit_voc_release_current_a1",
        original_previous="absent",
        phase="data_committed",
        target_site_release_present=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "recovered=1"
    assert os.readlink(tmp_path / "site/current") == f"releases/{'2' * 64}"
    assert os.readlink(tmp_path / "data/current") == (
        "releases/reddit_voc_release_target_a1"
    )
    assert os.readlink(tmp_path / "data/previous") == (
        "releases/reddit_voc_release_current_a1"
    )
    receipts = list((tmp_path / "site/evidence").glob("promotion-*.json"))
    assert len(receipts) == 1
    assert receipts[0].read_text() == "reconciled\n"
    assert not (tmp_path / "site/promotion-transaction.json").exists()
    completion = _shell_slice(
        "complete_interrupted_site_commit() {", "\nrecover_stale_journal() {"
    )
    assert "verify_committed_site_release_for_recovery" in completion
    assert "verify_old_data_projection_stable" in completion
    assert completion.count("verify_exact_data_projection") == 2
    assert "replace_data_pointer" in completion
    assert "os.fsync(parent_fd)" in _shell_slice(
        "replace_data_pointer() {", "\nremove_data_pointer() {"
    )


def test_interrupted_site_commit_rejects_wrong_runtime_contract_without_writes(
    tmp_path: Path,
) -> None:
    completed = _run_recovery_fixture(
        tmp_path,
        site_release="3" * 64,
        runtime_release="2" * 64,
        runtime_contract_valid=False,
        data_current="releases/reddit_voc_release_target_a1",
        data_previous="releases/reddit_voc_release_current_a1",
        original_previous="absent",
        phase="data_committed",
        target_site_release_present=True,
    )
    assert completed.returncode != 0
    assert "interrupted site runtime contract mismatch" in completed.stderr
    assert os.readlink(tmp_path / "site/current") == f"releases/{'3' * 64}"
    assert os.readlink(tmp_path / "data/current") == (
        "releases/reddit_voc_release_target_a1"
    )
    assert os.readlink(tmp_path / "data/previous") == (
        "releases/reddit_voc_release_current_a1"
    )
    assert (tmp_path / "site/promotion-transaction.json").exists()

    runtime_contract = _shell_slice(
        "verify_interrupted_site_runtime_contract() {",
        "\nreconcile_committed_promotion() {",
    )
    for required in (
        'config.get("User") != "101:101"',
        'host.get("ReadonlyRootfs") is not True',
        'host.get("CapDrop") != ["ALL"]',
        'host.get("SecurityOpt") != ["no-new-privileges:true"]',
        'host.get("PidsLimit") != 100',
        'host.get("Memory") != 268435456',
        'host.get("NanoCpus") != 500000000',
        'set(networks) != {"reddit_voc_insights_net"}',
        'mount.get("Destination") != "/srv/reddit-voc-data"',
        'mount.get("RW") is not False',
            'ports != {"8080/tcp": expected_binding}',
        "docker exec reddit_voc_insights_web",
    ):
        assert required in runtime_contract

    installer = INSTALLER.read_text(encoding="utf-8")
    installer_contract_start = installer.index(
        'container_contract_json="$(docker inspect "${CONTAINER_NAME}")"'
    )
    installer_contract_end = installer.index("\nPY\n", installer_contract_start)
    installer_contract = installer[
        installer_contract_start:installer_contract_end
    ]
    for required in (
        'config.get("User") != "101:101"',
        'host.get("ReadonlyRootfs") is not True',
        'host.get("Privileged") is not False',
        'host.get("CapAdd") not in (None, [])',
        'host.get("CapDrop") != ["ALL"]',
        'host.get("SecurityOpt") != ["no-new-privileges:true"]',
        'host.get("Init") is not True',
        'host.get("PidsLimit") != 100',
        'host.get("Memory") != 268435456',
        'host.get("NanoCpus") != 500000000',
            'ports != {"8080/tcp": expected_binding}',
            'bindings != {"8080/tcp": expected_binding}',
    ):
        assert required in installer_contract


def test_installer_target_starting_crash_restores_old_site_and_data_tuple(
    tmp_path: Path,
) -> None:
    completed = _run_recovery_fixture(
        tmp_path,
        site_release="3" * 64,
        runtime_release="2" * 64,
        runtime_health="starting",
        http_release="",
        data_current="releases/reddit_voc_release_target_a1",
        data_previous="releases/reddit_voc_release_current_a1",
        original_previous="absent",
        phase="data_committed",
        target_site_release_present=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "recovered=0"
    assert os.readlink(tmp_path / "site/current") == f"releases/{'3' * 64}"
    assert os.readlink(tmp_path / "data/current") == (
        "releases/reddit_voc_release_current_a1"
    )
    assert not (tmp_path / "data/previous").exists()
    assert not (tmp_path / "site/releases" / ("2" * 64)).exists()
    assert not (tmp_path / "data/releases/reddit_voc_release_target_a1").exists()
    assert not (tmp_path / "site/promotion-transaction.json").exists()

    recovery = _shell_slice("recover_stale_journal() {", "\ncleanup() {")
    transition = recovery.index(
        '"$site_pointer" == "releases/$EXPECTED_CURRENT" && '
        '"$phase" == data_committed'
    )
    runtime_validation = recovery.index(
        "verify_target_site_transition_runtime_contract", transition
    )
    old_restore = recovery.index(
        "restore_old_site_runtime_for_recovery", runtime_validation
    )
    recurse = recovery.index("recover_stale_journal", old_restore)
    assert transition < runtime_validation < old_restore < recurse


def test_installer_old_labeled_unhealthy_crash_restores_old_site_and_data(
    tmp_path: Path,
) -> None:
    completed = _run_recovery_fixture(
        tmp_path,
        site_release="3" * 64,
        runtime_release="3" * 64,
        runtime_health="unhealthy",
        http_release="",
        data_current="releases/reddit_voc_release_target_a1",
        data_previous="releases/reddit_voc_release_current_a1",
        original_previous="absent",
        phase="data_committed",
        target_site_release_present=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "recovered=0"
    assert os.readlink(tmp_path / "site/current") == f"releases/{'3' * 64}"
    assert os.readlink(tmp_path / "data/current") == (
        "releases/reddit_voc_release_current_a1"
    )
    assert not (tmp_path / "data/previous").exists()
    assert not (tmp_path / "site/releases" / ("2" * 64)).exists()
    assert not (tmp_path / "data/releases/reddit_voc_release_target_a1").exists()
    assert not (tmp_path / "site/promotion-transaction.json").exists()

    recovery = _shell_slice("recover_stale_journal() {", "\ncleanup() {")
    allowlisted = recovery.index(
        '"$container_release" == "$EXPECTED_CURRENT" && '
        '( "$container_health" != healthy || "$http_release" != "$EXPECTED_CURRENT" )'
    )
    old_tree = recovery.index("verify_old_site_release_for_recovery", allowlisted)
    old_image = recovery.index("local_old_image_id=", old_tree)
    full_runtime = recovery.index(
        'verify_target_site_transition_runtime_contract "$EXPECTED_CURRENT"',
        old_image,
    )
    restore = recovery.index("restore_old_site_runtime_for_recovery", full_runtime)
    assert allowlisted < old_tree < old_image < full_runtime < restore


def test_new_new_crash_reconciles_receipt_instead_of_claiming_acceptance(
    tmp_path: Path,
) -> None:
    completed = _run_recovery_fixture(
        tmp_path,
        site_release="2" * 64,
        data_current="releases/reddit_voc_release_target_a1",
        data_previous="releases/reddit_voc_release_current_a1",
        original_previous="absent",
        phase="site_committed",
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "recovered=1"
    receipts = list((tmp_path / "site/evidence").glob("promotion-*.json"))
    assert len(receipts) == 1
    assert receipts[0].read_text() == "reconciled\n"
    assert not (tmp_path / "site/promotion-transaction.json").exists()
    source = _source()
    assert '"status":"promoted_pending_public_acceptance"' in source
    assert "complete acceptance instead of replaying" not in source


def test_new_new_reconciliation_rejects_tampered_runtime_and_release_no_seal(
    tmp_path: Path,
) -> None:
    for name, expected_error in (
        (
            "runtime",
            "interrupted site runtime contract mismatch",
        ),
        (
            "release",
            "committed site release differs from the exact authorized archive",
        ),
    ):
        case = tmp_path / name
        case.mkdir()
        completed = _run_recovery_fixture(
            case,
            site_release="2" * 64,
            runtime_release="2" * 64,
            data_current="releases/reddit_voc_release_target_a1",
            data_previous="releases/reddit_voc_release_current_a1",
            original_previous="absent",
            phase="site_committed",
            target_site_release_present=True,
            runtime_contract_valid=name != "runtime",
            committed_site_release_valid=name != "release",
        )
        assert completed.returncode != 0, name
        assert expected_error in completed.stderr, name
        assert os.readlink(case / "site/current") == f"releases/{'2' * 64}"
        assert os.readlink(case / "data/current") == (
            "releases/reddit_voc_release_target_a1"
        )
        assert (case / "site/promotion-transaction.json").exists()
        assert not list((case / "site/evidence").glob("promotion-*.json"))

    reconciliation = _shell_slice(
        "reconcile_committed_promotion() {",
        "\ncomplete_interrupted_site_commit() {",
    )
    release_check = reconciliation.index(
        "verify_committed_site_release_for_recovery"
    )
    runtime_check = reconciliation.index(
        "verify_interrupted_site_runtime_contract", release_check
    )
    receipt_lookup = reconciliation.index(
        "find_exact_promotion_receipt", runtime_check
    )
    assert release_check < runtime_check < receipt_lookup


def _receipt_arguments(target: Path) -> list[str]:
    return [
        str(target),
        "1" * 64,
        "sha256:" + "a" * 64,
        "2" * 64,
        "3" * 64,
        "4" * 64,
        "reddit_voc_release_target_a1",
        "reddit_voc_release_current_a1",
        "5" * 64,
        "6" * 64,
        "7" * 64,
        "2",
        "1024",
        "collector-id",
        "0",
        "translation-id",
        "0",
        "8" * 64,
        "9" * 64,
    ]


def test_receipt_writer_is_exclusive_nofollow_and_durable(tmp_path: Path) -> None:
    writer = _heredoc_after('python3 - "$EVIDENCE"')
    target = tmp_path / "receipt.json"
    arguments = _receipt_arguments(target)
    created = subprocess.run(
        [sys.executable, "-c", writer, *arguments],
        check=False,
        capture_output=True,
        text=True,
    )
    assert created.returncode == 0, created.stderr
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert target.stat().st_nlink == 1
    receipt = json.loads(target.read_text(encoding="utf-8"))
    assert receipt["schema_version"] == "reddit_voc_remote_promotion_receipt_v2"
    assert receipt["data_inventory_sha256"] == "7" * 64
    assert receipt["target_image_id"] == "sha256:" + "a" * 64
    assert receipt["four_exports_complete"] is False
    assert receipt["candidate_exports_validation_bound"] is True

    duplicate = subprocess.run(
        [sys.executable, "-c", writer, *arguments],
        check=False,
        capture_output=True,
        text=True,
    )
    assert duplicate.returncode != 0
    assert "FileExistsError" in duplicate.stderr

    symlink_target = tmp_path / "outside.json"
    symlink_target.write_text("unchanged\n", encoding="utf-8")
    symlink = tmp_path / "symlink-receipt.json"
    symlink.symlink_to(symlink_target)
    symlink_attempt = subprocess.run(
        [sys.executable, "-c", writer, *_receipt_arguments(symlink)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert symlink_attempt.returncode != 0
    assert symlink_target.read_text(encoding="utf-8") == "unchanged\n"

    source = _source()
    receipt_start = source.index('python3 - "$EVIDENCE"')
    receipt_end = source.index("\nPY\n", receipt_start)
    receipt_source = source[receipt_start:receipt_end]
    assert "os.O_EXCL" in receipt_source
    assert "os.O_NOFOLLOW" in receipt_source
    assert "os.fsync(handle.fileno())" in receipt_source
    assert "os.fsync(directory_fd)" in receipt_source


def test_installer_evidence_writer_is_noreplace_nofollow_and_durable(
    tmp_path: Path,
) -> None:
    writer = _installer_heredoc_after('python3 - "${EVIDENCE_ROOT}"')
    name = f"container-deploy-20260724T010203Z-{'a' * 64}.txt"
    records = [
        "evidence_grade=L4-authorized-live",
        f"release_sha={'a' * 64}",
        "container_health=healthy",
    ]
    created = subprocess.run(
        [sys.executable, "-c", writer, str(tmp_path), name, *records],
        check=False,
        capture_output=True,
        text=True,
    )
    assert created.returncode == 0, created.stderr
    target = tmp_path / name
    assert target.read_text(encoding="utf-8") == "\n".join(records) + "\n"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert target.stat().st_nlink == 1
    assert not list(tmp_path.glob(f".{name}.*.tmp"))

    duplicate = subprocess.run(
        [sys.executable, "-c", writer, str(tmp_path), name, *records],
        check=False,
        capture_output=True,
        text=True,
    )
    assert duplicate.returncode != 0
    assert "FileExistsError" in duplicate.stderr
    assert target.read_text(encoding="utf-8") == "\n".join(records) + "\n"
    assert not list(tmp_path.glob(f".{name}.*.tmp"))

    symlink_name = f"container-deploy-20260724T010204Z-{'b' * 64}.txt"
    outside = tmp_path / "outside.txt"
    outside.write_text("unchanged\n", encoding="utf-8")
    (tmp_path / symlink_name).symlink_to(outside)
    linked = subprocess.run(
        [sys.executable, "-c", writer, str(tmp_path), symlink_name, *records],
        check=False,
        capture_output=True,
        text=True,
    )
    assert linked.returncode != 0
    assert outside.read_text(encoding="utf-8") == "unchanged\n"
    assert not list(tmp_path.glob(f".{symlink_name}.*.tmp"))

    installer = INSTALLER.read_text(encoding="utf-8")
    evidence_start = installer.index('python3 - "${EVIDENCE_ROOT}"')
    evidence_end = installer.index("\nPY\n", evidence_start)
    evidence_source = installer[evidence_start:evidence_end]
    assert "os.O_EXCL" in evidence_source
    assert "os.O_NOFOLLOW" in evidence_source
    assert "os.fsync(descriptor)" in evidence_source
    assert "os.fsync(directory_fd)" in evidence_source
    assert "renameat2" in evidence_source
    assert "renameatx_np" in evidence_source
    assert "rename_noreplace(temporary_name, name, directory_fd)" in evidence_source
    assert "verification_fd" in evidence_source
    assert '.tmp.$$' not in installer


def test_installer_exact_runtime_validator_rejects_privileged_and_capadd() -> None:
    validator = _installer_heredoc_after('container_contract_json="$(docker inspect')
    release = "a" * 64
    image_ref = f"reddit-voc-insights:{release}"
    image_id = f"sha256:{'b' * 64}"
    data_root = "/opt/reddit-voc-insights-data"
    bind_address = "172.20.0.1"
    port = "18338"
    binding = [{"HostIp": bind_address, "HostPort": port}]
    container = {
        "Config": {
            "Image": image_id,
            "Entrypoint": ["/docker-entrypoint.sh"],
            "Cmd": ["nginx", "-g", "daemon off;"],
            "WorkingDir": "/",
            "OpenStdin": False,
            "StdinOnce": False,
            "Tty": False,
            "Env": [
                "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                "NGINX_VERSION=1.29.4",
                "PKG_RELEASE=1",
                "DYNPKG_RELEASE=1",
                "NJS_VERSION=0.9.4",
                "NJS_RELEASE=1",
                "NGINX_ENTRYPOINT_QUIET_LOGS=1",
            ],
            "Healthcheck": {
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
            },
            "Labels": {
                "com.reddit-voc.component": "insights-site",
                "com.reddit-voc.release": release,
            },
            "User": "101:101",
        },
        "HostConfig": {
            "CapAdd": None,
            "CapDrop": ["ALL"],
            "Init": True,
            "Memory": 268435456,
            "NanoCpus": 500000000,
            "NetworkMode": "reddit_voc_insights_net",
            "PidsLimit": 100,
            "PortBindings": {"8080/tcp": binding},
            "Privileged": False,
            "PidMode": "",
            "IpcMode": "private",
            "UTSMode": "",
            "UsernsMode": "",
            "Devices": [],
            "DeviceRequests": None,
            "DeviceCgroupRules": None,
            "Sysctls": None,
            "Ulimits": None,
            "Runtime": "runc",
            "ReadonlyRootfs": True,
            "RestartPolicy": {"Name": "unless-stopped"},
            "SecurityOpt": ["no-new-privileges:true"],
            "Tmpfs": {
                "/tmp": "rw,noexec,nosuid,nodev,size=32m,uid=101,gid=101,mode=1777"
            },
        },
        "Image": image_id,
        "Mounts": [
            {
                "Destination": "/srv/reddit-voc-data",
                "Propagation": "rprivate",
                "RW": False,
                "Source": data_root,
                "Type": "bind",
            }
        ],
        "NetworkSettings": {
            "Networks": {
                "reddit_voc_insights_net": {"NetworkID": "c" * 64}
            },
            "Ports": {"8080/tcp": binding},
        },
        "State": {"Health": {"Status": "healthy"}, "Running": True},
    }

    def run(value: dict[str, object]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                "-c",
                validator,
                json.dumps([value], separators=(",", ":")),
                release,
                image_id,
                image_id,
                data_root,
                bind_address,
                port,
                "c" * 64,
            ],
            check=False,
            capture_output=True,
            text=True,
        )

    passed = run(container)
    assert passed.returncode == 0, passed.stderr

    absent_device_lists = json.loads(json.dumps(container))
    absent_device_lists["HostConfig"]["Devices"] = None
    absent_device_lists["HostConfig"]["DeviceRequests"] = None
    accepted_absent_device_lists = run(absent_device_lists)
    assert accepted_absent_device_lists.returncode == 0, (
        accepted_absent_device_lists.stderr
    )

    privileged = json.loads(json.dumps(container))
    privileged["HostConfig"]["Privileged"] = True
    rejected_privileged = run(privileged)
    assert rejected_privileged.returncode != 0
    assert "exact runtime contract mismatch" in rejected_privileged.stderr

    cap_added = json.loads(json.dumps(container))
    cap_added["HostConfig"]["CapAdd"] = ["SYS_ADMIN"]
    rejected_capadd = run(cap_added)
    assert rejected_capadd.returncode != 0
    assert "exact runtime contract mismatch" in rejected_capadd.stderr

    extra_port = json.loads(json.dumps(container))
    extra_port["HostConfig"]["PortBindings"]["9090/tcp"] = binding
    extra_port["NetworkSettings"]["Ports"]["9090/tcp"] = binding
    rejected_extra_port = run(extra_port)
    assert rejected_extra_port.returncode != 0
    assert "exact port contract mismatch" in rejected_extra_port.stderr

    extra_tmpfs = json.loads(json.dumps(container))
    extra_tmpfs["HostConfig"]["Tmpfs"]["/run"] = "rw,noexec"
    rejected_extra_tmpfs = run(extra_tmpfs)
    assert rejected_extra_tmpfs.returncode != 0
    assert "exact runtime contract mismatch" in rejected_extra_tmpfs.stderr

    wrong_network = json.loads(json.dumps(container))
    wrong_network["NetworkSettings"]["Networks"]["reddit_voc_insights_net"][
        "NetworkID"
    ] = "d" * 64
    rejected_network = run(wrong_network)
    assert rejected_network.returncode != 0
    assert "exact runtime contract mismatch" in rejected_network.stderr


def _run_projection_validator(
    tmp_path: Path, public_root: Path
) -> subprocess.CompletedProcess[str]:
    function = _shell_slice(
        "verify_exact_data_projection() {",
        '\n\n[[ "$DATA_RELEASE_ID"',
    )
    wrapper = f"""set -euo pipefail
TEMP_ROOT="$1"
{function}
verify_exact_data_projection "$2"
"""
    return subprocess.run(
        ["bash", "-c", wrapper, "projection-test", str(tmp_path), str(public_root)],
        check=False,
        capture_output=True,
        text=True,
    )


def test_data_projection_is_fully_rechecked_before_and_after_commit(
    tmp_path: Path,
) -> None:
    public_root = tmp_path / "public"
    data_file = public_root / "data/reddit-voc/current-release.json"
    data_file.parent.mkdir(parents=True)
    payload = b'{"release_id":"fixture"}\n'
    data_file.write_bytes(payload)
    data_file.chmod(0o444)
    data_file.parent.chmod(0o555)
    (public_root / "data").chmod(0o555)
    public_root.chmod(0o555)
    relative = "data/reddit-voc/current-release.json"
    (tmp_path / "dist-SHA256SUMS").write_text(
        f"{sha256(payload).hexdigest()}  dist/{relative}\n", encoding="utf-8"
    )

    first = _run_projection_validator(tmp_path, public_root)
    assert first.returncode == 0, first.stderr
    inventory_sha, file_count, total_bytes = first.stdout.strip().split("\t")
    assert len(inventory_sha) == 64
    assert file_count == "1"
    assert total_bytes == str(len(payload))

    data_file.chmod(0o644)
    data_file.write_bytes(b"tampered\n")
    checksum_failure = _run_projection_validator(tmp_path, public_root)
    assert checksum_failure.returncode != 0
    assert "checksum mismatch" in checksum_failure.stderr

    data_file.write_bytes(payload)
    data_file.chmod(0o444)
    outside_hardlink = tmp_path / "outside-hardlink.json"
    os.link(data_file, outside_hardlink)
    hardlink_failure = _run_projection_validator(tmp_path, public_root)
    assert hardlink_failure.returncode != 0
    assert "unsafe file" in hardlink_failure.stderr

    source = _source()
    move_commit = source.index(
        'sudo mv "$DATA_STAGE/releases/$DATA_RELEASE_ID" "$DATA_RELEASE_DIR"'
    )
    candidate_recheck = source.rindex(
        'verify_exact_data_projection "$DATA_STAGE/releases/$DATA_RELEASE_ID/public"',
        0,
        move_commit,
    )
    committed_recheck = source.index(
        'verify_exact_data_projection "$DATA_RELEASE_DIR/public"', move_commit
    )
    pointer_cas = source.index("replace_data_pointer", committed_recheck)
    assert candidate_recheck < move_commit < committed_recheck < pointer_cas


def _run_old_projection_validator(
    deploy_root: Path,
    data_root: Path,
    expected_release: str,
    expected_data_release: str,
    expected_pointer_sha: str,
    authenticated_override: tuple[str, str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    functions = _shell_slice(
        "verify_exact_data_projection() {",
        '\n\n[[ "$DATA_RELEASE_ID"',
    )
    wrapper = f"""set -euo pipefail
DEPLOY_ROOT="$1"
DATA_ROOT="$2"
EXPECTED_CURRENT="$3"
EXPECTED_CURRENT_DATA_RELEASE_ID="$4"
EXPECTED_CURRENT_DATA_POINTER_SHA="$5"
fail() {{ echo "$1" >&2; exit 1; }}
{functions}
if [[ -n "${{6:-}}" ]]; then
  EXPECTED_OLD_DATA_INVENTORY_SHA="$6"
  EXPECTED_OLD_DATA_FILE_COUNT="$7"
  EXPECTED_OLD_DATA_TOTAL_BYTES="$8"
else
  IFS=$'\t' read -r EXPECTED_OLD_DATA_INVENTORY_SHA EXPECTED_OLD_DATA_FILE_COUNT EXPECTED_OLD_DATA_TOTAL_BYTES \
    < <(verify_exact_data_projection "$DATA_ROOT/releases/$EXPECTED_CURRENT_DATA_RELEASE_ID/public" "$DEPLOY_ROOT/releases/$EXPECTED_CURRENT/dist-SHA256SUMS")
fi
verify_old_data_projection_stable
"""
    override = list(authenticated_override or ())
    return subprocess.run(
        [
            "bash",
            "-c",
            wrapper,
            "old-projection-test",
            str(deploy_root),
            str(data_root),
            expected_release,
            expected_data_release,
            expected_pointer_sha,
            *override,
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def test_old_data_recovery_uses_prior_site_inventory_and_full_toctou_recheck(
    tmp_path: Path,
) -> None:
    expected_release = "b" * 64
    expected_data_release = "reddit_voc_release_current_a1"
    site_release = tmp_path / "site/releases" / expected_release
    public = tmp_path / "data/releases" / expected_data_release / "public"
    pointer = public / "data/reddit-voc/current-release.json"
    pointer.parent.mkdir(parents=True)
    site_release.mkdir(parents=True)
    payload = b'{"release_id":"reddit_voc_release_current_a1"}\n'
    pointer.write_bytes(payload)
    pointer.chmod(0o444)
    pointer.parent.chmod(0o555)
    (public / "data").chmod(0o555)
    public.chmod(0o555)
    relative = "data/reddit-voc/current-release.json"
    dist_sums = (
        f"{sha256(payload).hexdigest()}  dist/{relative}\n".encode("utf-8")
    )
    (site_release / "dist-SHA256SUMS").write_bytes(dist_sums)
    (site_release / "SHA256SUMS").write_text(
        f"{sha256(dist_sums).hexdigest()}  dist-SHA256SUMS\n",
        encoding="utf-8",
    )

    passed = _run_old_projection_validator(
        tmp_path / "site",
        tmp_path / "data",
        expected_release,
        expected_data_release,
        sha256(payload).hexdigest(),
    )
    assert passed.returncode == 0, passed.stderr
    assert len(passed.stdout.strip().split("\t")[0]) == 64

    unauthenticated = _run_old_projection_validator(
        tmp_path / "site",
        tmp_path / "data",
        expected_release,
        expected_data_release,
        sha256(payload).hexdigest(),
        ("0" * 64, "1", str(len(payload))),
    )
    assert unauthenticated.returncode != 0
    assert "owner-authenticated baseline" in unauthenticated.stderr

    extra = public / "data/reddit-voc/unexpected.json"
    pointer.parent.chmod(0o755)
    extra.write_text("{}\n", encoding="utf-8")
    extra.chmod(0o444)
    pointer.parent.chmod(0o555)
    inventory_failure = _run_old_projection_validator(
        tmp_path / "site",
        tmp_path / "data",
        expected_release,
        expected_data_release,
        sha256(payload).hexdigest(),
    )
    assert inventory_failure.returncode != 0
    assert "inventory mismatch" in inventory_failure.stderr
    pointer.parent.chmod(0o755)
    extra.unlink()
    pointer.parent.chmod(0o555)

    (site_release / "dist-SHA256SUMS").write_text(
        f"{'0' * 64}  dist/{relative}\n", encoding="utf-8"
    )
    source_failure = _run_old_projection_validator(
        tmp_path / "site",
        tmp_path / "data",
        expected_release,
        expected_data_release,
        sha256(payload).hexdigest(),
    )
    assert source_failure.returncode != 0
    assert (
        "not bound by the active site release" in source_failure.stderr
        or "data projection checksum mismatch" in source_failure.stderr
    )

    old_function = _shell_slice(
        "verify_old_data_projection_stable() {",
        '\n\n[[ "$DATA_RELEASE_ID"',
    )
    assert old_function.count("verify_exact_data_projection") == 2


def test_old_site_recovery_artifacts_are_owner_authenticated_before_use(
    tmp_path: Path,
) -> None:
    expected_release = "b" * 64
    release_root = tmp_path / "releases" / expected_release
    release_root.mkdir(parents=True)
    manifest = release_root / "release-manifest.json"
    manifest.write_text('{"release_sha256":"fixture"}\n', encoding="utf-8")
    sums = release_root / "SHA256SUMS"
    sums.write_text(
        f"{sha256(manifest.read_bytes()).hexdigest()}  release-manifest.json\n",
        encoding="utf-8",
    )
    manifest.chmod(0o444)
    sums.chmod(0o444)
    release_root.chmod(0o555)
    function = _shell_slice(
        "verify_old_site_release_for_recovery() {",
        "\nrestore_old_site_runtime_for_recovery() {",
    )
    manifest_sha = sha256(manifest.read_bytes()).hexdigest()
    sums_sha = sha256(sums.read_bytes()).hexdigest()
    wrapper = f"""set -euo pipefail
DEPLOY_ROOT="$1"
EXPECTED_CURRENT={expected_release}
EXPECTED_OLD_RELEASE_MANIFEST_SHA="$2"
EXPECTED_OLD_RELEASE_SHA256SUMS_SHA="$3"
fail() {{ echo "$1" >&2; exit 1; }}
{function}
verify_old_site_release_for_recovery
"""
    passed = subprocess.run(
        ["bash", "-c", wrapper, "old-site-auth", str(tmp_path), manifest_sha, sums_sha],
        check=False,
        capture_output=True,
        text=True,
    )
    assert passed.returncode == 0, passed.stderr

    release_root.chmod(0o755)
    manifest.chmod(0o644)
    sums.chmod(0o644)
    manifest.write_text('{"release_sha256":"tampered"}\n', encoding="utf-8")
    sums.write_text(
        f"{sha256(manifest.read_bytes()).hexdigest()}  release-manifest.json\n",
        encoding="utf-8",
    )
    manifest.chmod(0o444)
    sums.chmod(0o444)
    release_root.chmod(0o555)
    tampered = subprocess.run(
        ["bash", "-c", wrapper, "old-site-auth", str(tmp_path), manifest_sha, sums_sha],
        check=False,
        capture_output=True,
        text=True,
    )
    assert tampered.returncode != 0
    assert "authenticated artifact digest mismatch" in tampered.stderr


def test_exact_root_sealed_rollback_release_is_supported_by_every_runtime_consumer() -> None:
    runner = _source()
    installer = INSTALLER.read_text(encoding="utf-8")
    rollback = (ROOT / "scripts/remote_rollback_insights.sh").read_text(
        encoding="utf-8"
    )

    old_release = _shell_slice(
        "verify_old_site_release_for_recovery() {",
        "\nrestore_old_site_runtime_for_recovery() {",
    )
    old_data = _shell_slice(
        "verify_old_data_projection_stable() {",
        '\n\n[[ "$DATA_RELEASE_ID"',
    )
    for source in (old_release, old_data):
        assert "metadata.st_uid == 0" in source
        assert "metadata.st_gid == 0" in source
        assert "stat.S_IMODE(metadata.st_mode) == 0o444" in source
    assert "stat.S_IMODE(metadata.st_mode) == 0o555" in old_release

    assert "def immutable_checksum(metadata)" in runner
    assert "stat.S_IMODE(metadata.st_mode) == 0o444" in runner
    assert "def immutable_directory(metadata)" in installer
    assert "def immutable_file(metadata)" in installer
    assert "stat.S_IMODE(metadata.st_mode) == 0o555" in installer
    assert "stat.S_IMODE(metadata.st_mode) == 0o444" in installer

    # The rollback authority bundled with the promotion must be able to read
    # the exact root-sealed target release after the forward switch.
    assert rollback.count("def immutable_directory(metadata):") >= 2
    assert rollback.count("def immutable_file(metadata):") >= 2
    assert rollback.count("stat.S_IMODE(metadata.st_mode) == 0o555") >= 2
    assert rollback.count("stat.S_IMODE(metadata.st_mode) == 0o444") >= 2


def test_all_committed_pointer_and_release_renames_fsync_parent_directories() -> None:
    source = _source()
    assert (
        'sudo mv "$DATA_STAGE/releases/$DATA_RELEASE_ID" "$DATA_RELEASE_DIR"\n'
        "  DATA_RELEASE_COMMITTED=1\n"
        '  fsync_directory "$DATA_ROOT/releases"'
    ) in source
    assert "os.fsync(parent_fd)" in _shell_slice(
        "replace_data_pointer() {", "\nremove_data_pointer() {"
    )
    installer = INSTALLER.read_text(encoding="utf-8")
    assert "cas_replace_site_pointer" in installer
    assert "os.fsync(parent_fd)" in _installer_shell_slice(
        "cas_replace_site_pointer() {", "\nsnapshot_authenticated_archive() {"
    )
    assert (
        'mv "${STAGING_DIR}" "${RELEASE_DIR}"\n'
        "release_committed=1\n"
        'fsync_directory "${RELEASE_ROOT}"'
    ) in installer


def _merged_compose_fixture(release: str, image_id: str) -> dict[str, object]:
    return {
        "name": "reddit_voc_insights",
        "networks": {
            "insights": {
                "name": "reddit_voc_insights_net",
                "driver": "bridge",
                "driver_opts": {
                    "com.docker.network.bridge.enable_icc": "false",
                    "com.docker.network.bridge.enable_ip_masquerade": "false",
                },
                "ipam": {},
            }
        },
        "services": {
            "web": {
                "cap_drop": ["ALL"],
                "command": None,
                "container_name": "reddit_voc_insights_web",
                "cpus": 0.5,
                "entrypoint": None,
                "environment": {"NGINX_ENTRYPOINT_QUIET_LOGS": "1"},
                "healthcheck": {
                    "test": [
                        "CMD-SHELL",
                        "wget -q -O /dev/null http://127.0.0.1:8080/healthz && "
                        "wget -q -O /dev/null "
                        "http://127.0.0.1:8080/data/reddit-voc/current-release.json",
                    ],
                    "timeout": "3s",
                    "interval": "10s",
                    "retries": 6,
                    "start_period": "5s",
                },
                "image": image_id,
                "init": True,
                "labels": {
                    "com.reddit-voc.component": "insights-site",
                    "com.reddit-voc.release": release,
                },
                "logging": {
                    "driver": "json-file",
                    "options": {"max-file": "3", "max-size": "10m"},
                },
                "mem_limit": "268435456",
                "networks": {"insights": None},
                "pids_limit": 100,
                "ports": [
                    {
                        "mode": "ingress",
                        "host_ip": "172.20.0.1",
                        "target": 8080,
                        "published": "18338",
                        "protocol": "tcp",
                    }
                ],
                "pull_policy": "never",
                "read_only": True,
                "restart": "unless-stopped",
                "security_opt": ["no-new-privileges:true"],
                "tmpfs": [
                    "/tmp:rw,noexec,nosuid,nodev,size=32m,"
                    "uid=101,gid=101,mode=1777"
                ],
                "user": "101:101",
                "volumes": [
                    {
                        "type": "bind",
                        "source": "/opt/reddit-voc-insights-data",
                        "target": "/srv/reddit-voc-data",
                        "read_only": True,
                        "bind": {},
                    }
                ],
            }
        },
    }


def test_installer_merged_compose_rejects_pid_devices_and_entrypoint_before_up() -> None:
    validator = _installer_heredoc_after('python3 - "${compose_json}"')
    release = "a" * 64
    image_id = "sha256:" + "b" * 64
    fixture = _merged_compose_fixture(release, image_id)

    def run(value: dict[str, object]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                "-c",
                validator,
                json.dumps(value, separators=(",", ":")),
                release,
                image_id,
                "/opt/reddit-voc-insights-data",
                "/srv/reddit-voc-data",
                "172.20.0.1",
                "18338",
            ],
            check=False,
            capture_output=True,
            text=True,
        )

    assert run(fixture).returncode == 0
    for key, value in (
        ("pid", "host"),
        ("devices", ["/dev/kvm:/dev/kvm"]),
        ("entrypoint", ["/bin/sh"]),
    ):
        dangerous = json.loads(json.dumps(fixture))
        dangerous["services"]["web"][key] = value
        rejected = run(dangerous)
        assert rejected.returncode != 0, key

    installer = INSTALLER.read_text(encoding="utf-8")
    commit = installer.index('mv "${STAGING_DIR}" "${RELEASE_DIR}"')
    preflight = installer.index("verify_runtime_compose_contract", commit)
    activation = installer.index(
        'docker compose -p "${COMPOSE_PROJECT}" \\\n'
        '  -f "${COMPOSE_SNAPSHOT}" -f "${COMPOSE_OVERRIDE}" \\\n'
        "  up -d",
        preflight,
    )
    assert preflight < activation


def test_exact_image_id_is_derived_and_used_for_candidate_and_install(
    tmp_path: Path,
) -> None:
    release = "a" * 64
    image_ref = f"reddit-voc-insights:{release}"
    config = b'{"architecture":"amd64","config":{}}'
    digest = sha256(config).hexdigest()
    helpers = (
        _installer_heredoc_after('python3 - "$archive_path" "$image_ref"'),
        _heredoc_after('python3 - "$archive_path" "$image_ref"'),
    )
    for layout, config_name in (
        ("legacy", f"{digest}.json"),
        ("oci", f"blobs/sha256/{digest}"),
    ):
        manifest = json.dumps(
            [{"Config": config_name, "RepoTags": [image_ref], "Layers": []}],
            separators=(",", ":"),
        ).encode()
        archive = tmp_path / f"image-{layout}.tar"
        with tarfile.open(archive, "w") as handle:
            for name, payload in (
                ("manifest.json", manifest),
                (config_name, config),
            ):
                info = tarfile.TarInfo(name)
                info.size = len(payload)
                handle.addfile(info, io.BytesIO(payload))
        for helper in helpers:
            derived = subprocess.run(
                [sys.executable, "-c", helper, str(archive), image_ref],
                check=False,
                capture_output=True,
                text=True,
            )
            assert derived.returncode == 0, (layout, derived.stderr)
            assert derived.stdout.strip() == f"sha256:{digest}"

    source = _source()
    candidate_start = source.index(
        'docker run -d --platform linux/amd64 --name "$CANDIDATE"'
    )
    candidate_end = source.index("CANDIDATE_STARTED=1", candidate_start)
    assert '"$TARGET_IMAGE_ID"' in source[candidate_start:candidate_end]
    installer = INSTALLER.read_text(encoding="utf-8")
    assert '"${TARGET_IMAGE_ID}" >/dev/null' in installer
    assert "compose-image-id.yaml" in installer
    assert "up -d --no-build --no-deps --pull never web" in installer


def test_data_pointer_cas_preserves_concurrent_pointer_and_absent_edges(
    tmp_path: Path,
) -> None:
    replace = _heredoc_after(
        'python3 - "$path" "$expected_target" "$replacement_target"'
    )
    remove = _heredoc_after(
        'python3 - "$path" "$expected_target" "$temporary_hint"'
    )
    pointer = tmp_path / "current"
    hint = tmp_path / ".hint"
    expected = "releases/reddit_voc_release_current_a1"
    replacement = "releases/reddit_voc_release_target_a1"
    concurrent = "releases/reddit_voc_release_concurrent_a1"
    pointer.symlink_to(expected)
    injected = replace.replace(
        "        exchange(temporary, path.name)\n",
        "        os.unlink(path.name, dir_fd=parent_fd)\n"
        "        os.symlink(%r, path.name, dir_fd=parent_fd)\n"
        "        exchange(temporary, path.name)\n" % concurrent,
        1,
    )
    rejected = subprocess.run(
        [
            sys.executable,
            "-c",
            injected,
            str(pointer),
            expected,
            replacement,
            str(hint),
            str(os.getuid()),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert rejected.returncode != 0
    assert os.readlink(pointer) == concurrent
    assert not list(tmp_path.glob(".current.promotion.*.tmp"))

    pointer.unlink()
    created = subprocess.run(
        [
            sys.executable,
            "-c",
            replace,
            str(pointer),
            "absent",
            replacement,
            str(hint),
            str(os.getuid()),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert created.returncode == 0, created.stderr
    assert os.readlink(pointer) == replacement

    removed = subprocess.run(
        [
            sys.executable,
            "-c",
            remove,
            str(pointer),
            replacement,
            str(hint),
            str(os.getuid()),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert removed.returncode == 0, removed.stderr
    assert not pointer.exists() and not pointer.is_symlink()
    assert not list(tmp_path.glob(".current.remove.*.tmp"))


def test_installer_site_pointer_cas_restores_exchange_time_concurrent_value(
    tmp_path: Path,
) -> None:
    validator = _installer_heredoc_after(
        'python3 - \\\n    "${DEPLOY_ROOT}/current"'
    )
    pointer = tmp_path / "current"
    expected = "releases/" + "a" * 64
    replacement = "releases/" + "b" * 64
    concurrent = "releases/" + "c" * 64
    pointer.symlink_to(expected)
    injected = validator.replace(
        "    exchange(temporary, path.name)\n",
        "    os.unlink(path.name, dir_fd=parent_fd)\n"
        "    os.symlink(%r, path.name, dir_fd=parent_fd)\n"
        "    exchange(temporary, path.name)\n" % concurrent,
        1,
    )
    rejected = subprocess.run(
        [
            sys.executable,
            "-c",
            injected,
            str(pointer),
            expected,
            replacement,
            str(os.getuid()),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert rejected.returncode != 0
    assert os.readlink(pointer) == concurrent
    assert not list(tmp_path.glob(".current.install.*.tmp"))
