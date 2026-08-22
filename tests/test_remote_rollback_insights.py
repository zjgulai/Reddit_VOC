from __future__ import annotations

import base64
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tarfile


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts/remote_rollback_insights.sh"
JOURNAL_SCHEMA = "reddit_voc_dual_resource_rollback_journal_v1"
RECEIPT_SCHEMA = "reddit_voc_dual_resource_rollback_receipt_v1"
FROM_SITE = "a" * 64
TO_SITE = "b" * 64
FROM_DATA_ID = "reddit_voc_release_current_a1"
FROM_DATA_SHA = "c" * 64
TO_DATA_ID = "reddit_voc_release_target_a1"
TO_DATA_SHA = "d" * 64
FROM_INVENTORY_SHA = "e" * 64
TO_INVENTORY_SHA = "f" * 64
ORIGINAL_DATA_TARGET = "releases/reddit_voc_release_prior_a1"
ORIGINAL_DATA_SHA = "9" * 64
EVIDENCE_MODE = "forward_previous_authorized"
RUNNER_SHA = "4" * 64
RUNNER_BYTES = "321"
FROM_RELEASE_MANIFEST_SHA = "0" * 64
FROM_RELEASE_SHA256SUMS_SHA = "1" * 64
TO_RELEASE_MANIFEST_SHA = "2" * 64
TO_RELEASE_SHA256SUMS_SHA = "3" * 64
CONTROL_BASELINE_ARGS = [
    "1" * 64,
    "0",
    "2" * 64,
    "0",
    "3" * 64,
    "0",
    "a" * 64,
    "42",
    "b" * 64,
    "1:2:3",
    "absent",
    "c" * 64,
]


def _source() -> str:
    return RUNNER.read_text(encoding="utf-8")


def _heredoc_after(marker: str) -> str:
    source = _source()
    command = source.index(marker)
    delimiter = source.index("<<'PY'", command) + len("<<'PY'")
    start = source.index("\n", delimiter) + 1
    end = source.index("\nPY\n", start)
    return source[start:end]


def _run_embedded(code: str, arguments: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-", *arguments],
        input=code,
        text=True,
        capture_output=True,
        check=False,
    )


def _journal_arguments(
    journal: Path,
    receipt: Path,
    phase: str,
    *,
    receipt_sha: str = "",
    from_site: str = FROM_SITE,
    from_manifest_sha: str = FROM_RELEASE_MANIFEST_SHA,
) -> list[str]:
    return [
        str(journal),
        JOURNAL_SCHEMA,
        phase,
        "2026-07-24T10:00:00Z",
        str(receipt),
        receipt_sha,
        from_site,
        TO_SITE,
        FROM_DATA_ID,
        FROM_DATA_SHA,
        TO_DATA_ID,
        TO_DATA_SHA,
        ORIGINAL_DATA_TARGET,
        ORIGINAL_DATA_SHA,
        EVIDENCE_MODE,
        str(receipt.parent / f"promotion-fixture-{TO_SITE}.json"),
        "8" * 64,
        "absent",
        "absent",
        str(receipt.parent / "packet-fixture.json"),
        "7" * 64,
        str(receipt.parent / "permit-fixture.json"),
        "6" * 64,
        str(receipt.parent / "baseline-fixture.json"),
        "5" * 64,
        from_manifest_sha,
        FROM_RELEASE_SHA256SUMS_SHA,
        TO_RELEASE_MANIFEST_SHA,
        TO_RELEASE_SHA256SUMS_SHA,
        RUNNER_SHA,
        RUNNER_BYTES,
        *CONTROL_BASELINE_ARGS,
    ]


def test_runner_has_valid_bash_syntax() -> None:
    result = subprocess.run(
        ["bash", "-n", str(RUNNER)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_runner_rejects_disable_before_any_runtime_command() -> None:
    result = subprocess.run(
        ["/bin/bash", str(RUNNER), "disable"],
        text=True,
        capture_output=True,
        check=False,
        env={"PATH": ""},
    )
    assert result.returncode != 0
    assert "only exact dual-resource release rollback is supported" in result.stderr


def test_journal_writer_persists_only_ordered_canonical_phases(tmp_path: Path) -> None:
    code = _heredoc_after("write_rollback_journal_phase()")
    journal = tmp_path / ".dual-resource-rollback-journal.json"
    receipt = tmp_path / "evidence" / "rollback-release-fixture.json"
    receipt.parent.mkdir()

    for phase in ("prepared", "data_switched", "site_switched"):
        result = _run_embedded(code, _journal_arguments(journal, receipt, phase))
        assert result.returncode == 0, result.stderr
    receipt_digest = "e" * 64
    result = _run_embedded(
        code,
        _journal_arguments(
            journal,
            receipt,
            "complete",
            receipt_sha=receipt_digest,
        ),
    )
    assert result.returncode == 0, result.stderr

    raw = journal.read_bytes()
    value = json.loads(raw)
    assert raw == (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode()
    assert stat.S_IMODE(journal.stat().st_mode) == 0o600
    assert value["schema_version"] == JOURNAL_SCHEMA
    assert value["phase"] == "complete"
    assert value["phase_history"] == [
        "prepared",
        "data_switched",
        "site_switched",
        "complete",
    ]
    assert value["site"] == {
        "acceptance_receipt_path": "absent",
        "acceptance_receipt_sha256": "absent",
        "authorization_packet_path": str(receipt.parent / "packet-fixture.json"),
        "authorization_packet_sha256": "7" * 64,
        "authorization_permit_path": str(receipt.parent / "permit-fixture.json"),
        "authorization_permit_sha256": "6" * 64,
        "evidence_mode": EVIDENCE_MODE,
        "from_release_manifest_sha256": FROM_RELEASE_MANIFEST_SHA,
        "from_release_sha256sums_sha256": FROM_RELEASE_SHA256SUMS_SHA,
        "from_release_sha256": FROM_SITE,
        "production_baseline_path": str(receipt.parent / "baseline-fixture.json"),
        "production_baseline_sha256": "5" * 64,
        "promotion_receipt_path": str(
            receipt.parent / f"promotion-fixture-{TO_SITE}.json"
        ),
        "promotion_receipt_sha256": "8" * 64,
        "rollback_runner_bytes": int(RUNNER_BYTES),
        "rollback_runner_sha256": RUNNER_SHA,
        "to_release_manifest_sha256": TO_RELEASE_MANIFEST_SHA,
        "to_release_sha256sums_sha256": TO_RELEASE_SHA256SUMS_SHA,
        "to_release_sha256": TO_SITE,
    }
    assert value["data"]["from_release_id"] == FROM_DATA_ID
    assert value["data"]["from_pointer_sha256"] == FROM_DATA_SHA
    assert value["data"]["to_release_id"] == TO_DATA_ID
    assert value["data"]["to_pointer_sha256"] == TO_DATA_SHA
    assert value["receipt_sha256"] == receipt_digest
    assert value["control_plane_baseline"]["collector_id"] == "1" * 64
    assert value["control_plane_baseline"]["database_identity"] == "1:2:3"


def test_journal_rejects_phase_skip_and_exact_tuple_mismatch(tmp_path: Path) -> None:
    code = _heredoc_after("write_rollback_journal_phase()")
    journal = tmp_path / ".dual-resource-rollback-journal.json"
    receipt = tmp_path / "evidence" / "rollback-release-fixture.json"
    receipt.parent.mkdir()
    prepared = _run_embedded(
        code, _journal_arguments(journal, receipt, "prepared")
    )
    assert prepared.returncode == 0, prepared.stderr

    skipped = _run_embedded(
        code, _journal_arguments(journal, receipt, "site_switched")
    )
    assert skipped.returncode != 0
    assert "illegal" in skipped.stderr

    mismatch = _run_embedded(
        code,
        _journal_arguments(
            journal,
            receipt,
            "data_switched",
            from_site="f" * 64,
        ),
    )
    assert mismatch.returncode != 0
    assert "tuple mismatch" in mismatch.stderr

    artifact_mismatch = _run_embedded(
        code,
        _journal_arguments(
            journal,
            receipt,
            "data_switched",
            from_manifest_sha="f" * 64,
        ),
    )
    assert artifact_mismatch.returncode != 0
    assert "tuple mismatch" in artifact_mismatch.stderr


def test_journal_recovery_rejects_cross_process_control_plane_drift(
    tmp_path: Path,
) -> None:
    writer = _heredoc_after("write_rollback_journal_phase()")
    reader = _heredoc_after("read_and_validate_rollback_journal()")
    journal = tmp_path / ".dual-resource-rollback-journal.json"
    receipt = tmp_path / "evidence" / "rollback-release-fixture.json"
    receipt.parent.mkdir()
    written = _run_embedded(
        writer, _journal_arguments(journal, receipt, "prepared")
    )
    assert written.returncode == 0, written.stderr
    reader_arguments = [
        str(journal),
        JOURNAL_SCHEMA,
        FROM_SITE,
        TO_SITE,
        FROM_DATA_ID,
        FROM_DATA_SHA,
        TO_DATA_ID,
        TO_DATA_SHA,
        RUNNER_SHA,
        RUNNER_BYTES,
        *CONTROL_BASELINE_ARGS,
    ]
    valid = _run_embedded(reader, reader_arguments)
    assert valid.returncode == 0, valid.stderr
    changed = reader_arguments.copy()
    changed[10] = "f" * 64
    rejected = _run_embedded(reader, changed)
    assert rejected.returncode != 0
    assert "exact requested site/data tuple" in rejected.stderr


def test_journal_atomic_writer_uses_nofollow_exclusive_create_and_fsync() -> None:
    code = _heredoc_after("write_rollback_journal_phase()")
    assert "os.O_EXCL" in code
    assert "os.O_NOFOLLOW" in code
    assert "os.fsync(fd)" in code
    assert "os.replace(temporary, journal)" in code
    assert "os.fsync(directory_fd)" in code


def test_full_data_projection_uses_site_dist_inventory_and_rejects_extra_or_hardlink(
    tmp_path: Path,
) -> None:
    code = _heredoc_after('python3 - "${dist_sums}"')
    public = tmp_path / "public"
    data_dir = public / "data" / "reddit-voc"
    data_dir.mkdir(parents=True)
    pointer = data_dir / "current-release.json"
    payload = data_dir / "base.json"
    pointer.write_bytes(b'{"release_id":"fixture"}\n')
    payload.write_bytes(b'{"rows":[]}\n')
    sums = tmp_path / "dist-SHA256SUMS"

    def write_sums(paths: list[Path]) -> None:
        lines = []
        for path in paths:
            relative = path.relative_to(public).as_posix()
            lines.append(f"{sha256(path.read_bytes()).hexdigest()}  dist/{relative}")
        sums.write_text("\n".join(lines) + "\n", encoding="utf-8")

    write_sums([pointer, payload])
    arguments = [str(sums), str(public), str(os.getuid())]
    valid = _run_embedded(code, arguments)
    assert valid.returncode == 0, valid.stderr

    extra = data_dir / "extra.json"
    extra.write_text("{}\n", encoding="utf-8")
    extra_result = _run_embedded(code, arguments)
    assert extra_result.returncode != 0
    assert "inventory mismatch" in extra_result.stderr
    extra.unlink()

    linked = data_dir / "linked.json"
    os.link(payload, linked)
    write_sums([pointer, payload, linked])
    hardlink_result = _run_embedded(code, arguments)
    assert hardlink_result.returncode != 0
    assert "unsafe file" in hardlink_result.stderr


def test_full_projection_contract_is_bound_at_every_data_validation_call() -> None:
    source = _source()
    body = source[
        source.index("validate_data_release_payload()") : source.index(
            "assert_expected_data_pointer()"
        )
    ]
    assert 'local site_release_sha="$3"' in body
    assert '"${site_release_sha}")/dist-SHA256SUMS"' in body
    assert "os.O_NOFOLLOW" in body
    assert "stat.S_ISREG" in body
    assert "metadata.st_nlink != 1" in body
    assert "set(actual) != set(expected)" in body
    assert "data projection checksum mismatch" in body

    assert source.count("validate_data_release_payload \\\n") == 1
    assert source.count("validate_and_bind_data_inventory from \\\n") >= 4
    assert source.count("validate_and_bind_data_inventory to \\\n") >= 6
    assert "source data inventory changed during rollback" in source
    assert "target data inventory changed during rollback" in source


def _receipt_arguments(receipt: Path, target_evidence: Path) -> list[str]:
    transaction_files = []
    for name in ("packet-fixture.json", "permit-fixture.json", "baseline-fixture.json"):
        path = receipt.parent / name
        if not path.exists():
            path.write_bytes(
                json.dumps({"fixture": name}, sort_keys=True, separators=(",", ":")).encode()
                + b"\n"
            )
        path.chmod(0o600)
        transaction_files.append(path)
    target_evidence.chmod(0o600)
    evidence_sha = sha256(target_evidence.read_bytes()).hexdigest()
    return [
        str(receipt),
        RECEIPT_SCHEMA,
        "2026-07-24T10:01:00Z",
        FROM_SITE,
        TO_SITE,
        FROM_DATA_ID,
        FROM_DATA_SHA,
        TO_DATA_ID,
        TO_DATA_SHA,
        EVIDENCE_MODE,
        str(target_evidence),
        evidence_sha,
        "absent",
        "absent",
        str(transaction_files[0]),
        sha256(transaction_files[0].read_bytes()).hexdigest(),
        str(transaction_files[1]),
        sha256(transaction_files[1].read_bytes()).hexdigest(),
        str(transaction_files[2]),
        sha256(transaction_files[2].read_bytes()).hexdigest(),
        FROM_RELEASE_MANIFEST_SHA,
        FROM_RELEASE_SHA256SUMS_SHA,
        TO_RELEASE_MANIFEST_SHA,
        TO_RELEASE_SHA256SUMS_SHA,
        RUNNER_SHA,
        RUNNER_BYTES,
        *CONTROL_BASELINE_ARGS,
        FROM_INVENTORY_SHA,
        "11",
        "111",
        TO_INVENTORY_SHA,
        "12",
        "222",
        "0",
        "0",
        "0",
        "f" * 64,
        "true",
        "true",
        JOURNAL_SCHEMA,
    ]


def test_receipt_is_immutable_canonical_and_binds_exact_site_data_tuple(
    tmp_path: Path,
) -> None:
    code = _heredoc_after("write_dual_rollback_receipt()")
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    receipt = evidence / "rollback-release-fixture.json"
    target_evidence = evidence / f"promotion-fixture-{TO_SITE}.json"
    target_evidence.write_text("fixture\n", encoding="utf-8")

    first = _run_embedded(code, _receipt_arguments(receipt, target_evidence))
    assert first.returncode == 0, first.stderr
    raw = receipt.read_bytes()
    value = json.loads(raw)
    digest = sha256(raw).hexdigest()
    assert first.stdout.strip() == digest
    assert raw == (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode()
    assert stat.S_IMODE(receipt.stat().st_mode) == 0o600
    assert receipt.stat().st_nlink == 1
    assert value["schema_version"] == RECEIPT_SCHEMA
    assert value["status"] == "dual_resource_rollback_complete"
    assert value["site"]["from_release_sha256"] == FROM_SITE
    assert value["site"]["from_release_manifest_sha256"] == FROM_RELEASE_MANIFEST_SHA
    assert value["site"]["from_release_sha256sums_sha256"] == FROM_RELEASE_SHA256SUMS_SHA
    assert value["site"]["to_release_sha256"] == TO_SITE
    assert value["site"]["to_release_manifest_sha256"] == TO_RELEASE_MANIFEST_SHA
    assert value["site"]["to_release_sha256sums_sha256"] == TO_RELEASE_SHA256SUMS_SHA
    assert value["site"]["runtime_release_sha256"] == TO_SITE
    assert value["site"]["promotion_receipt_sha256"] == sha256(
        target_evidence.read_bytes()
    ).hexdigest()
    assert value["site"]["evidence_mode"] == EVIDENCE_MODE
    assert value["site"]["acceptance_receipt_path"] == "absent"
    assert value["site"]["authorization_packet_path"].endswith("packet-fixture.json")
    assert value["control_plane_baseline"]["shared_container_inventory_sha256"] == "c" * 64
    assert value["data"] == {
        "from_file_count": 11,
        "from_inventory_sha256": FROM_INVENTORY_SHA,
        "from_pointer_sha256": FROM_DATA_SHA,
        "from_release_id": FROM_DATA_ID,
        "from_total_bytes": 111,
        "to_file_count": 12,
        "to_inventory_sha256": TO_INVENTORY_SHA,
        "to_pointer_sha256": TO_DATA_SHA,
        "to_release_id": TO_DATA_ID,
        "to_total_bytes": 222,
        "verified_current_target": f"releases/{TO_DATA_ID}",
        "verified_previous_target": f"releases/{FROM_DATA_ID}",
    }
    assert value["journal"]["phase_history"] == [
        "prepared",
        "data_switched",
        "site_switched",
        "complete",
    ]
    assert value["invariants"]["provider_call"] is False
    assert value["invariants"]["database_write"] is False
    assert value["invariants"]["live_send"] is False

    second = _run_embedded(code, _receipt_arguments(receipt, target_evidence))
    assert second.returncode != 0
    assert "already exists" in second.stderr
    assert sha256(receipt.read_bytes()).hexdigest() == digest


def test_receipt_publish_uses_atomic_noreplace_rename_and_directory_fsync() -> None:
    code = _heredoc_after("write_dual_rollback_receipt()")
    assert "os.O_EXCL" in code
    assert "os.O_NOFOLLOW" in code
    assert "renameat2" in code
    assert "renamex_np" in code
    assert "os.link(temporary, receipt" not in code
    assert "os.fsync(directory_fd)" in code


def test_receipt_validator_rejects_a_different_site_data_tuple(tmp_path: Path) -> None:
    writer = _heredoc_after("write_dual_rollback_receipt()")
    validator = _heredoc_after("validate_dual_rollback_receipt()")
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    receipt = evidence / "rollback-release-fixture.json"
    target_evidence = evidence / f"promotion-fixture-{TO_SITE}.json"
    target_evidence.write_text("fixture\n", encoding="utf-8")
    writer_arguments = _receipt_arguments(receipt, target_evidence)
    written = _run_embedded(writer, writer_arguments)
    assert written.returncode == 0, written.stderr
    digest = written.stdout.strip()
    arguments = [
        str(receipt),
        RECEIPT_SCHEMA,
        digest,
        FROM_SITE,
        TO_SITE,
        FROM_DATA_ID,
        FROM_DATA_SHA,
        TO_DATA_ID,
        TO_DATA_SHA,
        JOURNAL_SCHEMA,
        EVIDENCE_MODE,
        str(target_evidence),
        sha256(target_evidence.read_bytes()).hexdigest(),
        "absent",
        "absent",
        *writer_arguments[14:38],
        FROM_INVENTORY_SHA,
        "11",
        "111",
        TO_INVENTORY_SHA,
        "12",
        "222",
    ]
    valid = _run_embedded(validator, arguments)
    assert valid.returncode == 0, valid.stderr
    assert valid.stdout.strip() == digest

    artifact_binding = arguments.copy()
    artifact_binding[21] = "9" * 64
    artifact_mismatch = _run_embedded(validator, artifact_binding)
    assert artifact_mismatch.returncode != 0
    assert "contract mismatch" in artifact_mismatch.stderr

    arguments[8] = "e" * 64
    mismatch = _run_embedded(validator, arguments)
    assert mismatch.returncode != 0
    assert "contract mismatch" in mismatch.stderr

    arguments[8] = TO_DATA_SHA
    target_evidence.write_text("tampered\n", encoding="utf-8")
    evidence_tamper = _run_embedded(validator, arguments)
    assert evidence_tamper.returncode != 0
    assert "promotion evidence checksum mismatch" in evidence_tamper.stderr


def test_bound_release_artifact_recheck_rejects_all_four_local_tamper_cases(
    tmp_path: Path,
) -> None:
    code = _heredoc_after("reverify_bound_release_artifacts()")
    release_root = tmp_path / "releases"
    release_root.mkdir()

    artifact_paths: dict[str, Path] = {}
    arguments = [str(release_root), FROM_SITE, TO_SITE]
    for role, release in (("from", FROM_SITE), ("to", TO_SITE)):
        directory = release_root / release
        directory.mkdir()
        manifest = directory / "release-manifest.json"
        manifest.write_bytes(f'{{"release":"{release}"}}\n'.encode())
        sums = directory / "SHA256SUMS"
        sums.write_bytes(
            f"{sha256(manifest.read_bytes()).hexdigest()}  release-manifest.json\n".encode()
        )
        artifact_paths[f"{role}_manifest"] = manifest
        artifact_paths[f"{role}_sums"] = sums
        arguments.extend(
            [
                sha256(manifest.read_bytes()).hexdigest(),
                sha256(sums.read_bytes()).hexdigest(),
            ]
        )

    valid = _run_embedded(code, arguments)
    assert valid.returncode == 0, valid.stderr

    expected_labels = {
        "from_manifest": "current/from release release-manifest.json digest mismatch",
        "from_sums": "current/from release SHA256SUMS digest mismatch",
        "to_manifest": "target/to release release-manifest.json digest mismatch",
        "to_sums": "target/to release SHA256SUMS digest mismatch",
    }
    for name, expected_error in expected_labels.items():
        path = artifact_paths[name]
        original = path.read_bytes()
        path.write_bytes(original + b"tampered\n")
        rejected = _run_embedded(code, arguments)
        assert rejected.returncode != 0, name
        assert expected_error in rejected.stderr, name
        path.write_bytes(original)

    target_manifest = artifact_paths["to_manifest"]
    target_sums = artifact_paths["to_sums"]
    target_manifest.write_bytes(b'{"release":"replaced"}\n')
    target_sums.write_bytes(
        f"{sha256(target_manifest.read_bytes()).hexdigest()}  release-manifest.json\n".encode()
    )
    self_consistent_tamper = _run_embedded(code, arguments)
    assert self_consistent_tamper.returncode != 0
    assert "target/to release release-manifest.json digest mismatch" in (
        self_consistent_tamper.stderr
    )


def test_runtime_contract_rejects_tmpfs_port_image_security_and_network_drift() -> None:
    code = _heredoc_after('python3 - \\\n    "${container_json}" "${network_json}"')
    release = FROM_SITE
    image_ref = f"reddit-voc-insights:{release}"
    image_id = "sha256:" + "7" * 64
    network_id = "8" * 64
    bind_address = "172.20.0.1"
    port = "18338"
    data_root = "/opt/reddit-voc-insights-data"
    container_data_root = "/srv/reddit-voc-data"
    binding = [{"HostIp": bind_address, "HostPort": port}]
    container = {
        "Config": {
            "Cmd": ["nginx", "-g", "daemon off;"],
            "Entrypoint": ["/docker-entrypoint.sh"],
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
                    (
                        "wget -q -O /dev/null http://127.0.0.1:8080/healthz && "
                        "wget -q -O /dev/null "
                        "http://127.0.0.1:8080/data/reddit-voc/current-release.json"
                    ),
                ],
                "Interval": 10_000_000_000,
                "Timeout": 3_000_000_000,
                "Retries": 6,
                "StartPeriod": 5_000_000_000,
            },
            "Image": image_ref,
            "Labels": {
                "com.reddit-voc.component": "insights-site",
                "com.reddit-voc.release": release,
            },
            "OpenStdin": False,
            "StdinOnce": False,
            "Tty": False,
            "User": "101:101",
            "WorkingDir": "/",
        },
        "HostConfig": {
            "CapAdd": None,
            "CapDrop": ["ALL"],
            "DeviceCgroupRules": None,
            "DeviceRequests": None,
            "Devices": [],
            "IpcMode": "private",
            "Init": True,
            "Memory": 268435456,
            "NanoCpus": 500000000,
            "NetworkMode": "reddit_voc_insights_net",
            "PidMode": "",
            "PidsLimit": 100,
            "PortBindings": {"8080/tcp": binding},
            "Privileged": False,
            "ReadonlyRootfs": True,
            "RestartPolicy": {"Name": "unless-stopped"},
            "Runtime": "runc",
            "SecurityOpt": ["no-new-privileges:true"],
            "Sysctls": None,
            "Tmpfs": {
                "/tmp": (
                    "rw,noexec,nosuid,nodev,size=32m,"
                    "uid=101,gid=101,mode=1777"
                )
            },
            "UTSMode": "",
            "Ulimits": None,
            "UsernsMode": "",
        },
        "Image": image_id,
        "Mounts": [
            {
                "Destination": container_data_root,
                "Propagation": "rprivate",
                "RW": False,
                "Source": data_root,
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
    network = {
        "Driver": "bridge",
        "Id": network_id,
        "Internal": False,
        "Name": "reddit_voc_insights_net",
        "Options": {
            "com.docker.network.bridge.enable_icc": "false",
            "com.docker.network.bridge.enable_ip_masquerade": "false",
        },
    }

    def run(value: object) -> subprocess.CompletedProcess[str]:
        return _run_embedded(
            code,
            [
                json.dumps([value], separators=(",", ":")),
                json.dumps([network], separators=(",", ":")),
                release,
                image_ref,
                image_id,
                bind_address,
                port,
                "read_only_versioned_mount",
                data_root,
                container_data_root,
            ],
        )

    valid = run(container)
    assert valid.returncode == 0, valid.stderr

    absent_device_lists = json.loads(json.dumps(container))
    absent_device_lists["HostConfig"]["Devices"] = None
    absent_device_lists["HostConfig"]["DeviceRequests"] = None
    accepted_absent_device_lists = run(absent_device_lists)
    assert accepted_absent_device_lists.returncode == 0, (
        accepted_absent_device_lists.stderr
    )

    tmpfs_drift = json.loads(json.dumps(container))
    tmpfs_drift["HostConfig"]["Tmpfs"]["/tmp"] = "rw,noexec,nosuid,nodev"
    rejected = run(tmpfs_drift)
    assert rejected.returncode != 0
    assert "tmpfs exact contract mismatch" in rejected.stderr

    live_port_drift = json.loads(json.dumps(container))
    live_port_drift["NetworkSettings"]["Ports"]["8080/tcp"][0]["HostPort"] = "18339"
    rejected = run(live_port_drift)
    assert rejected.returncode != 0
    assert "live port binding mismatch" in rejected.stderr

    image_drift = json.loads(json.dumps(container))
    image_drift["Image"] = "sha256:" + "9" * 64
    rejected = run(image_drift)
    assert rejected.returncode != 0
    assert "container image ID mismatch" in rejected.stderr

    security_drift = json.loads(json.dumps(container))
    security_drift["HostConfig"]["SecurityOpt"].append("seccomp=unconfined")
    rejected = run(security_drift)
    assert rejected.returncode != 0
    assert "security options mismatch" in rejected.stderr

    entrypoint_drift = json.loads(json.dumps(container))
    entrypoint_drift["Config"]["Entrypoint"] = ["/bin/sh"]
    rejected = run(entrypoint_drift)
    assert rejected.returncode != 0
    assert "runtime entrypoint changed" in rejected.stderr

    pid_namespace_drift = json.loads(json.dumps(container))
    pid_namespace_drift["HostConfig"]["PidMode"] = "host"
    rejected = run(pid_namespace_drift)
    assert rejected.returncode != 0
    assert "runtime PID namespace changed" in rejected.stderr

    device_drift = json.loads(json.dumps(container))
    device_drift["HostConfig"]["Devices"] = [
        {"PathOnHost": "/dev/null", "PathInContainer": "/dev/null"}
    ]
    rejected = run(device_drift)
    assert rejected.returncode != 0
    assert "runtime device access changed" in rejected.stderr

    attachment_drift = json.loads(json.dumps(container))
    attachment_drift["NetworkSettings"]["Networks"]["reddit_voc_insights_net"][
        "NetworkID"
    ] = "a" * 64
    rejected = run(attachment_drift)
    assert rejected.returncode != 0
    assert "network attachment ID mismatch" in rejected.stderr

    source = _source()
    runtime_start = source.index("verify_runtime_contract() {")
    runtime_end = source.index("\n}\n\ncollector_id=", runtime_start)
    runtime = source[runtime_start:runtime_end]
    assert '"${DATA_CONTAINER_ROOT}" <<\'PY\' || return 1' in runtime
    assert 'container_json="$(docker inspect "${CONTAINER_NAME}")" || return 1' in runtime
    assert 'curl -fsS "http://${BIND_ADDRESS}:${PORT}/healthz" >/dev/null || return 1' in runtime


def test_merged_compose_contract_rejects_host_pid_devices_and_entrypoint() -> None:
    code = _heredoc_after(
        'python3 - \\\n'
        '    "${compose_json}" "${release_sha}" "${expected_image_id}"'
    )
    release = FROM_SITE
    image_id = "sha256:" + "7" * 64
    data_root = "/opt/reddit-voc-insights-data"
    data_container_root = "/srv/reddit-voc-data"
    bind_address = "172.20.0.1"
    port = "18338"
    compose = {
        "name": "reddit_voc_insights",
        "networks": {
            "insights": {
                "driver": "bridge",
                "driver_opts": {
                    "com.docker.network.bridge.enable_icc": "false",
                    "com.docker.network.bridge.enable_ip_masquerade": "false",
                },
                "ipam": {},
                "name": "reddit_voc_insights_net",
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
                        (
                            "wget -q -O /dev/null "
                            "http://127.0.0.1:8080/healthz && "
                            "wget -q -O /dev/null "
                            "http://127.0.0.1:8080/data/reddit-voc/"
                            "current-release.json"
                        ),
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
                "mem_limit": 268435456,
                "networks": {"insights": None},
                "pids_limit": 100,
                "ports": [
                    {
                        "host_ip": bind_address,
                        "mode": "ingress",
                        "protocol": "tcp",
                        "published": port,
                        "target": 8080,
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
                        "bind": {},
                        "read_only": True,
                        "source": data_root,
                        "target": data_container_root,
                        "type": "bind",
                    }
                ],
            }
        },
    }

    def run(value: object) -> subprocess.CompletedProcess[str]:
        return _run_embedded(
            code,
            [
                json.dumps(value, separators=(",", ":")),
                release,
                image_id,
                data_root,
                data_container_root,
                bind_address,
                port,
            ],
        )

    valid = run(compose)
    assert valid.returncode == 0, valid.stderr

    for key, value in (
        ("pid", "host"),
        ("devices", ["/dev/null:/dev/null"]),
    ):
        drifted = json.loads(json.dumps(compose))
        drifted["services"]["web"][key] = value
        rejected = run(drifted)
        assert rejected.returncode != 0
        assert "runtime merged compose service key set changed" in rejected.stderr

    entrypoint_drift = json.loads(json.dumps(compose))
    entrypoint_drift["services"]["web"]["entrypoint"] = ["/bin/sh"]
    rejected = run(entrypoint_drift)
    assert rejected.returncode != 0
    assert "runtime compose entrypoint changed" in rejected.stderr


def test_shared_nginx_verifier_rejects_equal_but_drifted_host_and_container() -> None:
    source = _source()
    start = source.index("assert_shared_nginx_digest_baseline() {")
    end = source.index("\n}\n\nassert_shared_service_baseline()", start) + 2
    helper = source[start:end]
    baseline = "a" * 64
    wrapper = f"""set -euo pipefail
nginx_before_sha={baseline}
{helper}
assert_shared_nginx_digest_baseline "$1" "$2"
"""

    def run(host_sha: str, container_sha: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", "-c", wrapper, "nginx-test", host_sha, container_sha],
            text=True,
            capture_output=True,
            check=False,
        )

    valid = run(baseline, baseline)
    assert valid.returncode == 0, valid.stderr
    same_drift = run("b" * 64, "b" * 64)
    assert same_drift.returncode != 0
    assert "changed from the rollback baseline" in same_drift.stderr
    container_only_drift = run(baseline, "c" * 64)
    assert container_only_drift.returncode != 0

    shared_start = source.index("assert_shared_service_baseline() {")
    shared_end = source.index("\n}\n\nCURRENT_TMP=", shared_start)
    shared = source[shared_start:shared_end]
    assert "assert_shared_nginx_digest_baseline" in shared


def test_runtime_collector_isolation_fails_closed_without_committing_evidence() -> None:
    source = _source()
    start = source.index("assert_runtime_collector_isolation() {")
    end = source.index("\n}\n\nverify_runtime_contract()", start) + 2
    helper = source[start:end]
    assert "clear_rollback_journal" not in helper
    assert "write_dual_rollback_receipt" not in helper
    wrapper = f"""set -euo pipefail
CONTAINER_NAME=reddit_voc_insights_web
BIND_ADDRESS=172.20.0.1
DOCKER_RESULT="$1"
docker() {{ return "${{DOCKER_RESULT}}"; }}
{helper}
assert_runtime_collector_isolation
"""

    isolated = subprocess.run(
        ["bash", "-c", wrapper, "isolation-test", "1"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert isolated.returncode == 0, isolated.stderr
    reachable = subprocess.run(
        ["bash", "-c", wrapper, "isolation-test", "0"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert reachable.returncode != 0
    assert "unexpectedly reached the collector" in reachable.stderr

    runtime_start = source.index("verify_runtime_contract() {")
    runtime_end = source.index("\n}\n\ncollector_id=", runtime_start)
    runtime = source[runtime_start:runtime_end]
    assert "assert_runtime_collector_isolation || return 1" in runtime


def test_protected_container_inventory_rejects_same_id_restart_drift() -> None:
    source = _source()
    start = source.index("protected_container_inventory() {")
    end = source.index("\n}\n\nassert_runtime_collector_isolation()", start) + 2
    helper = source[start:end]
    protected_id = "1" * 64
    insights_id = "2" * 64
    candidate_id = "3" * 64
    values = [
        {
            "Id": protected_id,
            "Name": "/unrelated_worker",
            "RestartCount": 0,
            "State": {
                "FinishedAt": "0001-01-01T00:00:00Z",
                "StartedAt": "2026-07-24T09:00:00Z",
                "Status": "running",
            },
        },
        {
            "Id": insights_id,
            "Name": "/reddit_voc_insights_web",
            "RestartCount": 4,
            "State": {
                "FinishedAt": "0001-01-01T00:00:00Z",
                "StartedAt": "2026-07-24T09:01:00Z",
                "Status": "running",
            },
        },
        {
            "Id": candidate_id,
            "Name": "/reddit_voc_insights_candidate_fixture",
            "RestartCount": 0,
            "State": {
                "FinishedAt": "2026-07-24T09:02:00Z",
                "StartedAt": "2026-07-24T09:01:30Z",
                "Status": "exited",
            },
        },
    ]
    wrapper = f"""set -euo pipefail
INSPECT_JSON="$1"
ROLLBACK_VERIFIER_NAME="reddit_voc_insights_rollback_verify_fixture"
ROLLBACK_VERIFIER_TRANSACTION_SHA="{"4" * 64}"
EXPECTED_CURRENT="{"5" * 64}"
TARGET_RELEASE="{"6" * 64}"
CURRENT_EXPECTED_IMAGE_ID=""
TARGET_EXPECTED_IMAGE_ID=""
docker() {{
  if [[ "$1" == "container" ]]; then
    printf '%s\\n' {protected_id} {insights_id} {candidate_id}
  elif [[ "$1" == "inspect" ]]; then
    printf '%s\\n' "${{INSPECT_JSON}}"
  else
    return 2
  fi
}}
{helper}
protected_container_inventory
"""

    def run(rows: list[dict[str, object]]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", "-c", wrapper, "inventory-test", json.dumps(rows)],
            text=True,
            capture_output=True,
            check=False,
        )

    baseline = run(values)
    assert baseline.returncode == 0, baseline.stderr
    baseline_count, baseline_sha = baseline.stdout.strip().split("\t")
    assert baseline_count == "1"
    assert len(baseline_sha) == 64

    restarted = json.loads(json.dumps(values))
    restarted[0]["RestartCount"] = 1
    restarted[0]["State"]["StartedAt"] = "2026-07-24T09:30:00Z"
    drifted = run(restarted)
    assert drifted.returncode == 0, drifted.stderr
    drifted_count, drifted_sha = drifted.stdout.strip().split("\t")
    assert drifted_count == baseline_count
    assert drifted_sha != baseline_sha

    shared_start = source.index("assert_shared_service_baseline() {")
    shared_end = source.index("\n}\n\nCURRENT_TMP=", shared_start)
    shared = source[shared_start:shared_end]
    assert "protected_container_inventory" in shared
    assert "observed_container_inventory_count" in shared
    assert "observed_container_inventory_sha" in shared
    assert "assert_authorized_protected_container_baseline || return 1" in shared


def test_candidate_container_or_listener_occupancy_fails_closed() -> None:
    source = _source()
    start = source.index("candidate_transaction_quiet_counts() {")
    end = source.index("\n}\n\nassert_runtime_collector_isolation()", start) + 2
    helper = source[start:end]
    wrapper = f"""set -euo pipefail
CANDIDATES="$1"
LISTENER="$2"
docker() {{
  [[ "$1 $2" == "container ls" ]] || return 2
  [[ -z "${{CANDIDATES}}" ]] || printf '%s\\n' "${{CANDIDATES}}"
}}
ss() {{
  [[ -z "${{LISTENER}}" ]] || printf 'LISTEN 0 128 %s\\n' "${{LISTENER}}"
}}
{helper}
assert_candidate_transaction_quiet
"""

    def run(
        candidates: str = "",
        listener: str = "",
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", "-c", wrapper, "candidate-test", candidates, listener],
            text=True,
            capture_output=True,
            check=False,
        )

    quiet = run()
    assert quiet.returncode == 0, quiet.stderr
    for label, completed in (
        ("candidate", run("reddit_voc_insights_candidate_fixture")),
        ("listener", run("", "127.0.0.1:18339")),
        (
            "both",
            run("reddit_voc_insights_candidate_fixture", "0.0.0.0:18339"),
        ),
    ):
        assert completed.returncode != 0, label
        assert "candidate transaction slot is occupied" in completed.stderr, label

    shared_start = source.index("assert_shared_service_baseline() {")
    shared_end = source.index("\n}\n\nCURRENT_TMP=", shared_start)
    shared = source[shared_start:shared_end]
    assert "assert_candidate_transaction_quiet || return 1" in shared
    baseline_start = source.index(
        'collector_id="$(docker inspect',
    )
    baseline_end = source.index("nginx_conf_mount=", baseline_start)
    assert "assert_candidate_transaction_quiet" in source[baseline_start:baseline_end]


def _write_runtime_release_fixture(
    root: Path,
    release: str,
    *,
    oci_layout: bool = False,
) -> tuple[str, str]:
    config = json.dumps(
        {
            "architecture": "amd64",
            "config": {
                "Labels": {
                    "com.reddit-voc.component": "insights-site",
                    "com.reddit-voc.release": release,
                },
                "User": "101:101",
            },
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    config_sha = sha256(config).hexdigest()
    config_name = (
        f"blobs/sha256/{config_sha}" if oci_layout else f"{config_sha}.json"
    )
    manifest = json.dumps(
        [
            {
                "Config": config_name,
                "Layers": [],
                "RepoTags": [f"reddit-voc-insights:{release}"],
            }
        ],
        separators=(",", ":"),
    ).encode()
    image = io.BytesIO()
    with tarfile.open(fileobj=image, mode="w") as archive:
        for name, payload in (
            ("manifest.json", manifest),
            (config_name, config),
        ):
            member = tarfile.TarInfo(name)
            member.size = len(payload)
            member.mode = 0o444
            archive.addfile(member, io.BytesIO(payload))
    payloads = {
        "compose.yaml": b"services:\n  web:\n    image: fixture\n",
        "dist-SHA256SUMS": b"0" * 64 + b"  dist/release.json\n",
        "release-manifest.json": json.dumps(
            {
                "release_sha256": release,
                "schema_version": "reddit_voc_insights_site_release_v2",
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        + b"\n",
        f"reddit-voc-insights-{release}.tar": image.getvalue(),
    }
    root.mkdir(mode=0o755, parents=True)
    for name, payload in payloads.items():
        path = root / name
        path.write_bytes(payload)
        path.chmod(0o644)
    sums = "".join(
        f"{sha256(payload).hexdigest()}  {name}\n"
        for name, payload in sorted(payloads.items())
    ).encode()
    (root / "SHA256SUMS").write_bytes(sums)
    (root / "SHA256SUMS").chmod(0o644)
    return (
        sha256(payloads["release-manifest.json"]).hexdigest(),
        sha256(sums).hexdigest(),
    )


def test_runtime_snapshot_is_private_exact_and_detaches_docker_inputs(
    tmp_path: Path,
) -> None:
    release = "a" * 64
    source = tmp_path / "source" / release
    manifest_sha, sums_sha = _write_runtime_release_fixture(source, release)
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir(mode=0o700)
    code = _heredoc_after(
        'expected_image_id="$(\n    python3 - \\\n'
        '      "${source_dir}" "${snapshot_dir}" "${release_sha}"'
    )
    completed = _run_embedded(
        code,
        [str(source), str(snapshot), release, manifest_sha, sums_sha],
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip().startswith("sha256:")
    assert stat.S_IMODE(snapshot.stat().st_mode) == 0o500
    for name in (
        "SHA256SUMS",
        "compose.yaml",
        "compose-image-id.yaml",
        "dist-SHA256SUMS",
        "release-manifest.json",
        f"reddit-voc-insights-{release}.tar",
    ):
        assert stat.S_IMODE((snapshot / name).stat().st_mode) == 0o400
        assert (snapshot / name).stat().st_nlink == 1

    authenticated_compose = (snapshot / "compose.yaml").read_bytes()
    (source / "compose.yaml").write_text("tampered: true\n", encoding="utf-8")
    assert (snapshot / "compose.yaml").read_bytes() == authenticated_compose

    shell = _source()
    ensure_start = shell.index("ensure_image_contract() {")
    ensure_end = shell.index("\n}\n\nassert_rollback_verifier_contract()", ensure_start)
    ensure = shell[ensure_start:ensure_end]
    assert 'directory="$(runtime_snapshot_directory "${release_sha}")"' in ensure
    assert 'docker load --input "${directory}/reddit-voc-insights-${release_sha}.tar"' in ensure
    assert "actual_image_id" in ensure
    assert "authenticated archive" in ensure
    assert 'image: {expected_image_id}' in _source()
    assert '"${expected_image_id}"' in _source()
    assert '"$(release_dir "${release_sha}")/compose.yaml"' not in shell
    assert '"$(release_dir "${TARGET_RELEASE}")/compose.yaml"' not in shell
    assert '"$(release_dir "${EXPECTED_CURRENT}")/compose.yaml"' not in shell


def test_runtime_snapshot_accepts_authenticated_oci_docker_archive(
    tmp_path: Path,
) -> None:
    release = "f" * 64
    source = tmp_path / "source" / release
    manifest_sha, sums_sha = _write_runtime_release_fixture(
        source,
        release,
        oci_layout=True,
    )
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir(mode=0o700)
    code = _heredoc_after(
        'expected_image_id="$(\n    python3 - \\\n'
        '      "${source_dir}" "${snapshot_dir}" "${release_sha}"'
    )
    completed = _run_embedded(
        code,
        [str(source), str(snapshot), release, manifest_sha, sums_sha],
    )
    assert completed.returncode == 0, completed.stderr
    assert re.fullmatch(r"sha256:[a-f0-9]{64}", completed.stdout.strip())


def test_runtime_snapshot_rejects_symlink_hardlink_and_digest_substitution(
    tmp_path: Path,
) -> None:
    release = "b" * 64
    code = _heredoc_after(
        'expected_image_id="$(\n    python3 - \\\n'
        '      "${source_dir}" "${snapshot_dir}" "${release_sha}"'
    )

    def run_case(name: str, mutation: str) -> subprocess.CompletedProcess[str]:
        case = tmp_path / name
        source = case / "source" / release
        manifest_sha, sums_sha = _write_runtime_release_fixture(source, release)
        if mutation == "symlink":
            compose = source / "compose.yaml"
            payload = compose.read_bytes()
            compose.unlink()
            outside = case / "outside-compose.yaml"
            outside.write_bytes(payload)
            compose.symlink_to(outside)
        elif mutation == "hardlink":
            os.link(source / "compose.yaml", case / "compose-hardlink.yaml")
        elif mutation == "digest":
            manifest_sha = "0" * 64
        snapshot = case / "snapshot"
        snapshot.mkdir(mode=0o700)
        return _run_embedded(
            code,
            [str(source), str(snapshot), release, manifest_sha, sums_sha],
        )

    for name in ("symlink", "hardlink", "digest"):
        rejected = run_case(name, name)
        assert rejected.returncode != 0, name
        assert (
            "unsafe" in rejected.stderr
            or "authorized digest" in rejected.stderr
        ), (name, rejected.stderr)


def test_runtime_snapshot_reverification_rejects_self_consistent_rewrite(
    tmp_path: Path,
) -> None:
    release = "c" * 64
    source = tmp_path / "source" / release
    manifest_sha, sums_sha = _write_runtime_release_fixture(source, release)
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir(mode=0o700)
    snapshot_code = _heredoc_after(
        'expected_image_id="$(\n    python3 - \\\n'
        '      "${source_dir}" "${snapshot_dir}" "${release_sha}"'
    )
    created = _run_embedded(
        snapshot_code,
        [str(source), str(snapshot), release, manifest_sha, sums_sha],
    )
    assert created.returncode == 0, created.stderr
    expected_image_id = created.stdout.strip()
    verify_code = _heredoc_after(
        'python3 - \\\n    "${snapshot_dir}" "${release_sha}" '
        '"${expected_image_id}"'
    )
    valid = _run_embedded(
        verify_code,
        [
            str(snapshot),
            release,
            expected_image_id,
            manifest_sha,
            sums_sha,
        ],
    )
    assert valid.returncode == 0, valid.stderr

    snapshot.chmod(0o700)
    compose = snapshot / "compose.yaml"
    compose.chmod(0o600)
    compose.write_text("services:\n  web:\n    privileged: true\n", encoding="utf-8")
    compose.chmod(0o400)
    sums_path = snapshot / "SHA256SUMS"
    sums_path.chmod(0o600)
    lines = []
    for line in sums_path.read_text().splitlines():
        _, name = line.split("  ", 1)
        digest = sha256((snapshot / name).read_bytes()).hexdigest()
        lines.append(f"{digest}  {name}")
    sums_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    sums_path.chmod(0o400)
    snapshot.chmod(0o500)

    rejected = _run_embedded(
        verify_code,
        [
            str(snapshot),
            release,
            expected_image_id,
            manifest_sha,
            sums_sha,
        ],
    )
    assert rejected.returncode != 0
    assert "authorized digest" in rejected.stderr


def test_pointer_cas_restores_exchange_time_concurrent_value(
    tmp_path: Path,
) -> None:
    pointer = tmp_path / "current"
    original = "releases/" + "1" * 64
    replacement = "releases/" + "2" * 64
    concurrent = "releases/" + "3" * 64
    pointer.symlink_to(original)
    code = _heredoc_after("cas_replace_symlink() {")
    injected = code.replace(
        "    os.symlink(replacement, temporary, dir_fd=parent_fd)\n",
        "    os.unlink(path.name, dir_fd=parent_fd)\n"
        f'    os.symlink("{concurrent}", path.name, dir_fd=parent_fd)\n'
        "    os.symlink(replacement, temporary, dir_fd=parent_fd)\n",
        1,
    )
    assert injected != code
    rejected = _run_embedded(
        injected,
        [
            str(pointer),
            original,
            replacement,
            "concurrent-site",
            str(os.getuid()),
        ],
    )
    assert rejected.returncode != 0
    assert os.readlink(pointer) == concurrent
    assert list(tmp_path.iterdir()) == [pointer]


def test_pointer_cas_replace_remove_and_mismatch_are_fail_closed(
    tmp_path: Path,
) -> None:
    replace = _heredoc_after("cas_replace_symlink() {")
    remove = _heredoc_after("cas_remove_symlink() {")
    old = "releases/reddit_voc_release_old"
    new = "releases/reddit_voc_release_new"

    pointer = tmp_path / "current"
    pointer.symlink_to(old)
    changed = _run_embedded(
        replace,
        [str(pointer), old, new, "data-current", str(os.getuid())],
    )
    assert changed.returncode == 0, changed.stderr
    assert os.readlink(pointer) == new

    absent_pointer = tmp_path / "previous"
    created = _run_embedded(
        replace,
        [str(absent_pointer), "absent", old, "data-previous", str(os.getuid())],
    )
    assert created.returncode == 0, created.stderr
    assert os.readlink(absent_pointer) == old

    wrong = _run_embedded(
        replace,
        [
            str(pointer),
            "releases/reddit_voc_release_wrong",
            old,
            "data-current",
            str(os.getuid()),
        ],
    )
    assert wrong.returncode != 0
    assert os.readlink(pointer) == new

    removed = _run_embedded(
        remove,
        [str(absent_pointer), old, "data-previous", str(os.getuid())],
    )
    assert removed.returncode == 0, removed.stderr
    assert not absent_pointer.exists() and not absent_pointer.is_symlink()


def _write_private_json(path: Path, value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    path.write_bytes(payload)
    path.chmod(0o600)
    return sha256(payload).hexdigest()


def _forward_transaction_arguments(tmp_path: Path) -> tuple[list[str], dict[str, Path]]:
    baseline_path = tmp_path / "baseline.json"
    baseline = {
        "current_release_sha256": TO_SITE,
        "evidence_grade": "L3-production-read-only",
        "observed_at_utc": "2026-07-24T09:59:00Z",
        "observations": {
            "collector": {
                "container_id": "1" * 64,
                "health": "healthy",
                "restart_count": 0,
            },
            "cron": {"sha256": "6" * 64, "stable": True},
            "cron_sha256": "6" * 64,
            "database": {
                "after": "1:2:3",
                "before": "1:2:3",
                "stable": True,
            },
            "insights": {
                "container_id": "3" * 64,
                "current_symlink": f"releases/{TO_SITE}",
                "data_file_count": 12,
                "data_inventory_sha256": TO_INVENTORY_SHA,
                "data_total_bytes": 222,
                "health": "healthy",
                "internal_pointer": TO_DATA_ID,
                "internal_pointer_sha256": TO_DATA_SHA,
                "internal_pointer_symlink": f"releases/{TO_DATA_ID}",
                "internal_release_sha256": TO_SITE,
                "release_label": TO_SITE,
                "restart_count": 0,
                "runtime_contract": {
                    "image_id": "sha256:" + "7" * 64,
                    "network": {"id": "8" * 64},
                },
            },
            "libretranslate": {
                "container_id": "2" * 64,
                "health": "healthy",
                "restart_count": 0,
            },
            "locks": {
                "identities": {
                    "data_release": {
                        "device": 1, "inode": 10, "mode": "0600", "nlink": 1,
                        "path": "/opt/reddit-voc-insights-data/locks/data-release.lock",
                        "uid": 1000,
                    },
                    "deploy": {
                        "device": 1, "inode": 11, "mode": "0600", "nlink": 1,
                        "path": "/opt/reddit-voc-insights-site/.deploy.lock",
                        "uid": 1000,
                    },
                    "promotion": {
                        "device": 1, "inode": 12, "mode": "0600", "nlink": 1,
                        "path": "/opt/reddit-voc-insights-site/.promotion.lock",
                        "uid": 1000,
                    },
                },
                "stable": True,
            },
            "quiet_counts_stable": True,
            "release_sha256s": {
                "sha256": TO_RELEASE_SHA256SUMS_SHA,
                "stable": True,
                "verified_after": True,
                "verified_before": True,
            },
            "release_sha256sums_verified": True,
            "report_pointer": {
                "after": "absent",
                "before": "absent",
                "stable": True,
            },
            "running_containers": {
                "count": 3,
                "inventory_sha256": "5" * 64,
                "protected_count": 2,
                "protected_inventory_sha256": "9" * 64,
                "protected_scope": "docker_ps_a_excluding_insights_transaction",
                "stable": True,
            },
            "shared_nginx": {"sha256": "0" * 64, "stable": True},
            "shared_nginx_sha256": "0" * 64,
            "site_data_tuple": {
                "data_file_count": 12,
                "data_inventory_sha256": TO_INVENTORY_SHA,
                "data_release_id": TO_DATA_ID,
                "data_total_bytes": 222,
                "pointer_sha256": TO_DATA_SHA,
                "site_manifest_sha256": TO_RELEASE_MANIFEST_SHA,
                "site_release_sha256": TO_SITE,
                "stable": True,
            },
            "site_release_manifest": {
                "data_release_id": TO_DATA_ID,
                "manifest_sha256": TO_RELEASE_MANIFEST_SHA,
                "pointer_sha256": TO_DATA_SHA,
                "release_sha256": TO_SITE,
                "served_exact": True,
                "stable": True,
            },
        },
        "production_unchanged": True,
        "remote_write": False,
        "schema_version": "reddit_voc_production_baseline_receipt_v1",
        "status": "passed",
    }
    baseline_sha = _write_private_json(baseline_path, baseline)
    observations = baseline["observations"]
    baseline_cas = {
        "collector": {
            "container_id": observations["collector"]["container_id"],
            "health": observations["collector"]["health"],
            "restart_count": observations["collector"]["restart_count"],
        },
        "container_inventory": {
            "count": observations["running_containers"]["count"],
            "protected_count": observations["running_containers"][
                "protected_count"
            ],
            "protected_sha256": observations["running_containers"][
                "protected_inventory_sha256"
            ],
            "sha256": observations["running_containers"]["inventory_sha256"],
        },
        "cron_sha256": observations["cron"]["sha256"],
        "database_identity": observations["database"]["before"],
        "insights": {
            "container_id": observations["insights"]["container_id"],
            "health": observations["insights"]["health"],
            "image_id": observations["insights"]["runtime_contract"]["image_id"],
            "network_id": observations["insights"]["runtime_contract"]["network"][
                "id"
            ],
            "restart_count": observations["insights"]["restart_count"],
        },
        "lock_identities": observations["locks"]["identities"],
        "observed_at_utc": baseline["observed_at_utc"],
        "report_pointer_identity": observations["report_pointer"]["before"],
        "shared_nginx_sha256": observations["shared_nginx"]["sha256"],
        "translation": {
            "container_id": observations["libretranslate"]["container_id"],
            "health": observations["libretranslate"]["health"],
            "restart_count": observations["libretranslate"]["restart_count"],
        },
    }
    required_actions = [
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
    runner_sha = "0" * 64
    execution_runtime = {
        "remote_rollback": {
            "bytes": 123,
            "path": "runtime/remote_rollback_insights.sh",
            "sha256": runner_sha,
        }
    }
    packet_path = tmp_path / "packet.json"
    packet = {
        "artifacts": {
            "production_baseline_receipt": {"sha256": baseline_sha},
            "release_manifest": {
                "bytes": 111,
                "path": "release/release-manifest.json",
                "sha256": FROM_RELEASE_MANIFEST_SHA,
            },
            "release_sha256sums": {
                "bytes": 222,
                "path": "release/SHA256SUMS",
                "sha256": FROM_RELEASE_SHA256SUMS_SHA,
            },
        },
        "authorization": {
            "allowed_actions": required_actions,
            "consumed": False,
            "forbidden_actions": forbidden_actions,
            "permit_required": True,
            "promotion_authorized": False,
        },
        "evidence": {"all_artifacts_reopened": True, "baseline_max_age_seconds": 900},
        "expires_at_utc": "2026-07-24T11:00:00Z",
        "execution_runtime": execution_runtime,
        "generated_at_utc": "2026-07-24T10:00:00Z",
        "nonce": "rollback-fixture-nonce",
        "packet_id": "reddit_voc_promotion_fixture",
        "production_baseline_cas": baseline_cas,
        "rollback": {
            "readiness_mode": "immediate_same_baseline_window",
            "ready": True,
            "scope": "insights_site_and_data_current",
            "shared_nginx_change_allowed": False,
            "target_data_file_count": 12,
            "target_data_inventory_sha256": TO_INVENTORY_SHA,
            "target_data_pointer_sha256": TO_DATA_SHA,
            "target_data_release_id": TO_DATA_ID,
            "target_data_total_bytes": 222,
            "target_release_manifest_sha256": TO_RELEASE_MANIFEST_SHA,
            "target_release_sha256": TO_SITE,
            "target_release_sha256s_sha256": TO_RELEASE_SHA256SUMS_SHA,
            "valid_until_utc": "2026-07-24T11:00:00Z",
        },
        "schema_version": "reddit_voc_promotion_packet_v4",
        "status": "ready_for_owner_authorization",
        "target": {
            "data_release_id": FROM_DATA_ID,
            "expected_current_data_pointer_sha256": TO_DATA_SHA,
            "expected_current_data_release_id": TO_DATA_ID,
            "expected_current_release_sha256": TO_SITE,
            "release_sha256": FROM_SITE,
            "target_data_pointer_sha256": FROM_DATA_SHA,
        },
    }
    packet_sha = _write_private_json(packet_path, packet)
    permit_path = tmp_path / "permit.json"
    permit = {
        "authorization": {
            "authorized_actions": required_actions,
            "authorized_at_utc": "2026-07-24T10:01:00Z",
            "authorized_by": "owner_explicit_confirmation",
            "forbidden_actions": forbidden_actions,
            "owner_confirmation": "authorize_exact_reddit_voc_packet_and_release",
        },
        "authorized_actions": required_actions,
        "authorized_recorded_at_utc": "2026-07-24T10:01:00Z",
        "consumed": False,
        "contract": "reddit_voc_promotion_permit_exact_binding_v4",
        "expires_at_utc": "2026-07-24T10:30:00Z",
        "forbidden_actions": forbidden_actions,
        "packet": {
            "data_release_id": FROM_DATA_ID,
            "expected_current_data_pointer_sha256": TO_DATA_SHA,
            "expected_current_data_release_id": TO_DATA_ID,
            "expected_current_release_sha256": TO_SITE,
            "execution_runtime": execution_runtime,
            "expires_at_utc": "2026-07-24T11:00:00Z",
            "nonce": packet["nonce"],
            "packet_id": packet["packet_id"],
            "packet_sha256": packet_sha,
            "release_sha256": FROM_SITE,
            "target_data_pointer_sha256": FROM_DATA_SHA,
        },
        "packet_id": packet["packet_id"],
        "packet_sha256": packet_sha,
        "release_sha256": FROM_SITE,
        "schema_version": "reddit_voc_promotion_permit_v1",
        "scope": "insights_site_and_data_current",
        "status": "authorized_unconsumed",
    }
    permit_sha = _write_private_json(permit_path, permit)
    promotion_path = tmp_path / f"promotion-fixture-{FROM_SITE}.json"
    promotion = {
        "candidate_18339_smoke": True,
        "candidate_exports_validation_bound": True,
        "collector_id": "1" * 64,
        "collector_restart_count": 0,
        "cron_sha256": "2" * 64,
        "data_file_count": 11,
        "data_inventory_sha256": FROM_INVENTORY_SHA,
        "data_pointer_sha256": FROM_DATA_SHA,
        "data_release_id": FROM_DATA_ID,
        "data_total_bytes": 111,
        "database_write": False,
        "evidence_grade": "L4-authorized-live",
        "four_exports_complete": False,
        "generated_at_utc": "2026-07-24T10:03:00Z",
        "live_send": False,
        "nginx_sha256": "3" * 64,
        "packet_sha256": packet_sha,
        "permit_sha256": permit_sha,
        "previous_data_pointer_sha256": TO_DATA_SHA,
        "previous_data_release_id": TO_DATA_ID,
        "previous_release_sha256": TO_SITE,
        "production_container_smoke": True,
        "provider_call": False,
        "release_sha256": FROM_SITE,
        "schema_version": "reddit_voc_remote_promotion_receipt_v2",
        "shared_nginx_modified": False,
        "status": "promoted_pending_public_acceptance",
        "translation_id": "6" * 64,
        "translation_restart_count": 0,
    }
    promotion_sha = _write_private_json(promotion_path, promotion)
    arguments = [
        str(tmp_path),
        "1",
        FROM_SITE,
        TO_SITE,
        FROM_DATA_ID,
        FROM_DATA_SHA,
        FROM_INVENTORY_SHA,
        "11",
        "111",
        TO_DATA_ID,
        TO_DATA_SHA,
        TO_INVENTORY_SHA,
        "12",
        "222",
        str(promotion_path),
        promotion_sha,
        str(packet_path),
        packet_sha,
        str(permit_path),
        permit_sha,
        str(baseline_path),
        baseline_sha,
        runner_sha,
        "123",
    ]
    return arguments, {
        "baseline": baseline_path,
        "packet": packet_path,
        "permit": permit_path,
        "promotion": promotion_path,
    }


def test_dual_evidence_requires_explicit_authenticated_forward_transaction(
    tmp_path: Path,
) -> None:
    code = _heredoc_after('evidence_output="$(python3 -')
    arguments, paths = _forward_transaction_arguments(tmp_path)
    valid = _run_embedded(code, arguments)
    assert valid.returncode == 0, valid.stderr
    fields = valid.stdout.strip().split("\t")
    assert fields[0] == EVIDENCE_MODE
    assert fields[1] == str(paths["promotion"])
    assert fields[3:5] == ["absent", "absent"]
    assert fields[5] == str(paths["packet"])
    assert fields[7] == str(paths["permit"])
    assert fields[9] == str(paths["baseline"])
    assert fields[11:] == [
        FROM_RELEASE_MANIFEST_SHA,
        FROM_RELEASE_SHA256SUMS_SHA,
        TO_RELEASE_MANIFEST_SHA,
        TO_RELEASE_SHA256SUMS_SHA,
        "2",
        "9" * 64,
        "6" * 64,
        "1:2:3",
        "absent",
        "0" * 64,
        fields[21],
    ]
    lock_identities = json.loads(
        base64.urlsafe_b64decode(fields[21].encode("ascii")).decode("utf-8")
    )
    baseline = json.loads(paths["baseline"].read_text())
    assert lock_identities == baseline["observations"]["locks"]["identities"]

    wrong_sha = arguments.copy()
    wrong_sha[15] = "0" * 64
    rejected = _run_embedded(code, wrong_sha)
    assert rejected.returncode != 0
    assert "SHA-256 mismatch" in rejected.stderr

    wrong_runner = arguments.copy()
    wrong_runner[-2] = "1" * 64
    rejected = _run_embedded(code, wrong_runner)
    assert rejected.returncode != 0
    assert "packet does not bind" in rejected.stderr

    baseline = json.loads(paths["baseline"].read_text())
    baseline["observations"]["site_data_tuple"]["data_release_id"] = (
        "reddit_voc_release_later"
    )
    arguments[21] = _write_private_json(paths["baseline"], baseline)
    rejected = _run_embedded(code, arguments)
    assert rejected.returncode != 0
    assert "packet does not bind" in rejected.stderr


def test_dual_evidence_rejects_nonexact_action_contracts(
    tmp_path: Path,
) -> None:
    code = _heredoc_after('evidence_output="$(python3 -')
    cases = (
        ("packet_action_order", "packet"),
        ("packet_extra_action", "packet"),
        ("permit_forbidden_order", "permit"),
    )
    for case_name, mutated_record in cases:
        case = tmp_path / case_name
        case.mkdir()
        arguments, paths = _forward_transaction_arguments(case)
        packet = json.loads(paths["packet"].read_text())
        permit = json.loads(paths["permit"].read_text())

        if case_name == "packet_action_order":
            packet["authorization"]["allowed_actions"] = list(
                reversed(packet["authorization"]["allowed_actions"])
            )
        elif case_name == "packet_extra_action":
            packet["authorization"]["allowed_actions"].append(
                "modify_shared_nginx"
            )
        else:
            permit["forbidden_actions"] = list(
                reversed(permit["forbidden_actions"])
            )

        if mutated_record == "packet":
            packet_sha = _write_private_json(paths["packet"], packet)
            arguments[17] = packet_sha
            permit["packet_sha256"] = packet_sha
            permit["packet"]["packet_sha256"] = packet_sha
        permit_sha = _write_private_json(paths["permit"], permit)
        arguments[19] = permit_sha
        promotion = json.loads(paths["promotion"].read_text())
        promotion["packet_sha256"] = arguments[17]
        promotion["permit_sha256"] = permit_sha
        arguments[15] = _write_private_json(paths["promotion"], promotion)

        rejected = _run_embedded(code, arguments)
        assert rejected.returncode != 0
        expected = (
            "packet does not bind"
            if mutated_record == "packet"
            else "permit does not authenticate"
        )
        assert expected in rejected.stderr


def test_dual_evidence_rejects_promotion_at_exact_permit_expiry(
    tmp_path: Path,
) -> None:
    code = _heredoc_after('evidence_output="$(python3 -')
    arguments, paths = _forward_transaction_arguments(tmp_path)
    permit = json.loads(paths["permit"].read_text())
    promotion = json.loads(paths["promotion"].read_text())
    promotion["generated_at_utc"] = permit["expires_at_utc"]
    arguments[15] = _write_private_json(paths["promotion"], promotion)

    rejected = _run_embedded(code, arguments)
    assert rejected.returncode != 0
    assert "transaction time ordering" in rejected.stderr


def test_remote_v2_rejects_forbidden_live_export_completeness_claim(
    tmp_path: Path,
) -> None:
    code = _heredoc_after('evidence_output="$(python3 -')
    arguments, paths = _forward_transaction_arguments(tmp_path)
    promotion = json.loads(paths["promotion"].read_text())
    promotion["four_exports_complete"] = True
    arguments[15] = _write_private_json(paths["promotion"], promotion)

    rejected = _run_embedded(code, arguments)
    assert rejected.returncode != 0
    assert "remote promotion v2 data contract invalid" in rejected.stderr


def test_packet_old_release_artifact_digests_must_equal_the_baseline(
    tmp_path: Path,
) -> None:
    code = _heredoc_after('evidence_output="$(python3 -')
    for index, field in enumerate(
        ("target_release_manifest_sha256", "target_release_sha256s_sha256")
    ):
        case = tmp_path / str(index)
        case.mkdir()
        arguments, paths = _forward_transaction_arguments(case)

        packet = json.loads(paths["packet"].read_text())
        packet["rollback"][field] = "9" * 64
        packet_sha = _write_private_json(paths["packet"], packet)

        permit = json.loads(paths["permit"].read_text())
        permit["packet_sha256"] = packet_sha
        permit["packet"]["packet_sha256"] = packet_sha
        permit_sha = _write_private_json(paths["permit"], permit)

        promotion = json.loads(paths["promotion"].read_text())
        promotion["packet_sha256"] = packet_sha
        promotion["permit_sha256"] = permit_sha
        promotion_sha = _write_private_json(paths["promotion"], promotion)

        arguments[15] = promotion_sha
        arguments[17] = packet_sha
        arguments[19] = permit_sha
        rejected = _run_embedded(code, arguments)
        assert rejected.returncode != 0, field
        assert "baseline does not prove" in rejected.stderr, field


def test_packet_production_baseline_cas_is_independently_derived_from_baseline(
    tmp_path: Path,
) -> None:
    code = _heredoc_after('evidence_output="$(python3 -')
    arguments, paths = _forward_transaction_arguments(tmp_path)
    packet = json.loads(paths["packet"].read_text())
    packet["production_baseline_cas"]["shared_nginx_sha256"] = "9" * 64
    packet_sha = _write_private_json(paths["packet"], packet)

    permit = json.loads(paths["permit"].read_text())
    permit["packet_sha256"] = packet_sha
    permit["packet"]["packet_sha256"] = packet_sha
    permit_sha = _write_private_json(paths["permit"], permit)

    promotion = json.loads(paths["promotion"].read_text())
    promotion["packet_sha256"] = packet_sha
    promotion["permit_sha256"] = permit_sha
    promotion_sha = _write_private_json(paths["promotion"], promotion)

    arguments[15] = promotion_sha
    arguments[17] = packet_sha
    arguments[19] = permit_sha
    rejected = _run_embedded(code, arguments)
    assert rejected.returncode != 0
    assert "production baseline CAS does not match explicit baseline" in rejected.stderr


def test_explicit_evidence_rejects_symlink_and_hardlink(tmp_path: Path) -> None:
    code = _heredoc_after('evidence_output="$(python3 -')
    arguments, paths = _forward_transaction_arguments(tmp_path)
    promotion = paths["promotion"]
    real = tmp_path / "promotion-real.json"
    promotion.replace(real)
    promotion.symlink_to(real)
    rejected = _run_embedded(code, arguments)
    assert rejected.returncode != 0

    promotion.unlink()
    os.link(real, promotion)
    rejected = _run_embedded(code, arguments)
    assert rejected.returncode != 0


def _run_lock_bootstrap(tmp_path: Path, code: str) -> subprocess.CompletedProcess[str]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    dummy = tmp_path / "dummy.sh"
    dummy.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    dummy.chmod(0o700)
    return _run_embedded(
        code,
        [
            str(dummy),
            "1",
            str(tmp_path / ".promotion.lock"),
            str(tmp_path / ".deploy.lock"),
            str(tmp_path / "data-release.lock"),
        ],
    )


def test_lock_bootstrap_is_ordered_nofollow_and_race_safe(tmp_path: Path) -> None:
    source = _source()
    code = _heredoc_after(
        'if [[ "${REDDIT_VOC_ROLLBACK_LOCKS_HELD:-}" != "1" ]]'
    )
    assert "os.O_NOFOLLOW" in code
    assert "targets = [200, 201, 202]" in code
    assert "opened.st_dev != linked.st_dev" in code
    assert "opened.st_ino != linked.st_ino" in code
    assert "opened.st_nlink != 1" in code
    assert "stat.S_IMODE(opened.st_mode) != 0o600" in code
    assert code.index("paths = [promotion, deploy]") < code.index("targets = [200, 201, 202]")

    valid = _run_lock_bootstrap(tmp_path / "valid", code)
    assert valid.returncode == 0, valid.stderr
    for name in (".promotion.lock", ".deploy.lock", "data-release.lock"):
        assert stat.S_IMODE((tmp_path / "valid" / name).stat().st_mode) == 0o600

    symlink_root = tmp_path / "symlink"
    symlink_root.mkdir()
    target = symlink_root / "target"
    target.write_text("", encoding="utf-8")
    target.chmod(0o600)
    (symlink_root / ".promotion.lock").symlink_to(target)
    rejected = _run_lock_bootstrap(symlink_root, code)
    assert rejected.returncode != 0

    hardlink_root = tmp_path / "hardlink"
    hardlink_root.mkdir()
    target = hardlink_root / "target"
    target.write_text("", encoding="utf-8")
    target.chmod(0o600)
    os.link(target, hardlink_root / ".promotion.lock")
    rejected = _run_lock_bootstrap(hardlink_root, code)
    assert rejected.returncode != 0
    assert "unsafe" in rejected.stderr

    race_root = tmp_path / "race"
    race_root.mkdir()
    race_code = code.replace(
        "for path, descriptor in zip(paths, descriptors, strict=True):",
        "os.unlink(paths[0])\nos.close(os.open(paths[0], os.O_RDWR | os.O_CREAT, 0o600))\n"
        "for path, descriptor in zip(paths, descriptors, strict=True):",
        1,
    )
    rejected = _run_lock_bootstrap(race_root, race_code)
    assert rejected.returncode != 0
    assert "identity is unsafe" in rejected.stderr


def test_lock_order_and_startup_recovery_are_fail_closed() -> None:
    source = _source()
    promotion_lock = source.index("paths = [promotion, deploy]")
    deploy_lock = source.index("targets = [200, 201, 202]", promotion_lock)
    data_lock = source.index("REDDIT_VOC_ROLLBACK_LOCK_FDS", deploy_lock)
    startup = source.index("recover_persistent_rollback_journal_on_startup\n")
    normal_preflight = source.index(
        "assert_expected_current_pointer\nvalidate_release_payload",
        startup,
    )
    assert promotion_lock < deploy_lock < data_lock < startup < normal_preflight
    assert "journal does not match the exact requested site/data tuple" in source
    assert "blocks site-only actions" in source
    assert "complete rollback journal has no immutable receipt" in source


def _cas_arguments(phase: str) -> list[str]:
    return [
        phase,
        f"releases/{FROM_SITE}" if phase == "prepared" else f"releases/{TO_SITE}",
        FROM_SITE if phase == "prepared" else TO_SITE,
        "healthy",
        FROM_SITE if phase == "prepared" else TO_SITE,
        f"releases/{FROM_DATA_ID}" if phase == "prepared" else f"releases/{TO_DATA_ID}",
        FROM_DATA_SHA if phase == "prepared" else TO_DATA_SHA,
        ORIGINAL_DATA_TARGET if phase == "prepared" else f"releases/{FROM_DATA_ID}",
        ORIGINAL_DATA_SHA if phase == "prepared" else FROM_DATA_SHA,
        FROM_SITE,
        TO_SITE,
        FROM_DATA_ID,
        FROM_DATA_SHA,
        TO_DATA_ID,
        TO_DATA_SHA,
        ORIGINAL_DATA_TARGET,
        ORIGINAL_DATA_SHA,
    ]


def test_phase_cas_harness_accepts_crash_states_and_rejects_later_tuples() -> None:
    code = _heredoc_after("assert_dual_recovery_phase_cas()")
    for phase in ("prepared", "site_switched", "complete"):
        result = _run_embedded(code, _cas_arguments(phase))
        assert result.returncode == 0, (phase, result.stderr)

    data_switched = _cas_arguments("data_switched")
    data_switched[1] = f"releases/{FROM_SITE}"
    result = _run_embedded(code, data_switched)
    assert result.returncode == 0, result.stderr

    runtime_missing = _cas_arguments("data_switched")
    runtime_missing[1] = f"releases/{FROM_SITE}"
    runtime_missing[2:5] = ["missing", "missing", "missing"]
    result = _run_embedded(code, runtime_missing)
    assert result.returncode == 0, result.stderr

    impossible_prepared = _cas_arguments("prepared")
    impossible_prepared[5:9] = [
        f"releases/{TO_DATA_ID}",
        TO_DATA_SHA,
        ORIGINAL_DATA_TARGET,
        ORIGINAL_DATA_SHA,
    ]
    rejected = _run_embedded(code, impossible_prepared)
    assert rejected.returncode != 0
    assert "mixed data tuple" in rejected.stderr

    later = "7" * 64
    mutations = {
        "site": (1, f"releases/{later}"),
        "runtime": (2, later),
        "http": (4, later),
        "data_current": (5, "releases/reddit_voc_release_later"),
        "data_current_sha": (6, "6" * 64),
        "data_previous": (7, "releases/reddit_voc_release_later"),
        "data_previous_sha": (8, "6" * 64),
    }
    for label, (index, replacement) in mutations.items():
        arguments = _cas_arguments("data_switched")
        arguments[index] = replacement
        rejected = _run_embedded(code, arguments)
        assert rejected.returncode != 0, label
        assert "recovery CAS rejected" in rejected.stderr, label


def test_recovery_runs_phase_cas_before_any_pointer_write() -> None:
    source = _source()
    start = source.index("recover_failed_action()")
    end = source.index("assert_target_site_data_tuple()", start)
    recovery = source[start:end]
    assert recovery.index("assert_dual_recovery_phase_cas") < recovery.index(
        "ensure_image_contract"
    )
    assert recovery.index("assert_dual_recovery_phase_cas") < recovery.index(
        "restore_original_data"
    )
    assert "docker load" not in source[
        source.index("assert_dual_recovery_phase_cas()") : start
    ]
    assert "no site/data pointer was changed and the journal is retained" in recovery


def test_release_artifact_digests_are_rechecked_before_mutation_and_at_terminal_recovery(
) -> None:
    source = _source()
    normal_start = source.index("recover_persistent_rollback_journal_on_startup\n")
    normal = source[normal_start : source.index("has_marker_start=0", normal_start)]
    evidence = normal.index('validate_target_deployment_evidence "${TARGET_RELEASE}"')
    first_recheck = normal.index("reverify_bound_release_artifacts", evidence)
    current_load = normal.index('ensure_image_contract "${EXPECTED_CURRENT}"', first_recheck)
    second_recheck = normal.index("reverify_bound_release_artifacts", current_load)
    target_load = normal.index('ensure_image_contract "${TARGET_RELEASE}"', second_recheck)
    prepared = normal.index("write_rollback_journal_phase prepared", target_load)
    pointer_recheck = normal.index("reverify_bound_release_artifacts", prepared)
    first_pointer_write = normal.index('"switch-data-previous"', pointer_recheck)
    data_switched = normal.index("write_rollback_journal_phase data_switched")
    docker_recheck = normal.index("reverify_bound_release_artifacts", data_switched)
    compose_up = normal.index("docker compose", docker_recheck)
    assert evidence < first_recheck < current_load < second_recheck < target_load
    assert prepared < pointer_recheck < first_pointer_write
    assert data_switched < docker_recheck < compose_up

    cas = source[
        source.index("assert_dual_recovery_phase_cas()") : source.index(
            "recover_failed_action()"
        )
    ]
    assert cas.index("reverify_bound_release_artifacts") < cas.index(
        'runtime_release="$(docker inspect'
    )

    terminal = source[
        source.index("revalidate_bound_rollback_evidence()") : source.index(
            "ensure_image_contract()"
        )
    ]
    assert "reverify_bound_release_artifacts" in terminal
    receipt_validator = source[
        source.index("validate_dual_rollback_receipt()") : source.index(
            "cleanup_transient()"
        )
    ]
    assert receipt_validator.index("reverify_bound_release_artifacts") < (
        receipt_validator.index("python3 -")
    )


def test_exit_recovery_verifies_old_site_and_data_before_clearing_journal() -> None:
    source = _source()
    recover_start = source.index("recover_failed_action()")
    recover_end = source.index("assert_target_site_data_tuple()", recover_start)
    recover = source[recover_start:recover_end]
    assert recover.index("restore_original_data") < recover.index(
        "restore_original_release"
    )
    assert "assert_expected_current_pointer" in recover
    assert "assert_expected_data_pointer" in recover
    assert 'ensure_image_contract "${EXPECTED_CURRENT}"' in recover
    assert 'verify_image_dist_contract "${EXPECTED_CURRENT}"' in recover

    target_start = source.index("assert_target_site_data_tuple()")
    target_end = source.index("recover_persistent_rollback_journal_on_startup()")
    target = source[target_start:target_end]
    for check in (
        'validate_release_payload "${TARGET_RELEASE}" || return 1',
        'ensure_image_contract "${TARGET_RELEASE}" || return 1',
        'verify_image_dist_contract "${TARGET_RELEASE}" || return 1',
        'wait_for_release_health "${TARGET_RELEASE}" || return 1',
        'verify_runtime_contract "${TARGET_RELEASE}" || return 1',
        "assert_shared_service_baseline || return 1",
    ):
        assert check in target

    exit_start = source.index("on_exit()")
    exit_end = source.index("trap 'on_exit $?' EXIT", exit_start)
    on_exit = source[exit_start:exit_end]
    assert on_exit.index("recover_failed_action") < on_exit.index(
        "clear_rollback_journal"
    )
    assert '"${ACTION_SUCCEEDED}" != "1"' in on_exit

    evidence_assignment = source.index('EVIDENCE_FILE="${ROLLBACK_RECEIPT_FILE}"')
    dual_success_start = source.rindex(
        "assert_target_site_data_tuple", 0, evidence_assignment
    )
    dual_success_end = source.index("  else\n", dual_success_start)
    dual_success = source[dual_success_start:dual_success_end]
    assert dual_success.index("write_rollback_journal_phase site_switched") < dual_success.index(
        "revalidate_bound_rollback_evidence"
    )
    assert dual_success.index("revalidate_bound_rollback_evidence") < dual_success.index(
        "write_dual_rollback_receipt"
    )
    assert dual_success.index("write_dual_rollback_receipt") < dual_success.index(
        "validate_dual_rollback_receipt"
    )
    assert dual_success.index("validate_dual_rollback_receipt") < dual_success.index(
        "write_rollback_journal_phase complete"
    )
    assert dual_success.index("write_rollback_journal_phase complete") < dual_success.index(
        "clear_rollback_journal"
    )
    assert dual_success.index("clear_rollback_journal") < dual_success.index(
        "ACTION_SUCCEEDED=1"
    )


def test_journal_clear_revalidates_owner_mode_and_link_count() -> None:
    code = _heredoc_after("clear_rollback_journal()")
    assert "info.st_nlink != 1" in code
    assert "info.st_uid != os.getuid()" in code
    assert "stat.S_IMODE(info.st_mode) != 0o600" in code
    assert "os.O_NOFOLLOW" in code
    assert "os.fsync(directory_fd)" in code


def test_site_and_data_pointer_renames_fsync_parent_directories() -> None:
    source = _source()
    replace_start = source.index("cas_replace_symlink() {")
    replace_end = source.index("\n}\n\ncas_remove_symlink()", replace_start)
    remove_start = replace_end
    remove_end = source.index("\n}\n\nvalidate_release_payload()", remove_start)
    assert "rename_exchange" in source[replace_start:replace_end]
    assert "rename_noreplace" in source[replace_start:replace_end]
    assert "os.fsync(parent_fd)" in source[replace_start:replace_end]
    assert "rename_noreplace" in source[remove_start:remove_end]
    assert "os.fsync(parent_fd)" in source[remove_start:remove_end]
    assert "mv -Tf" not in source
    for label in (
        "switch-data-previous",
        "switch-data-current",
        "switch-site-current",
        "restore-data-previous",
        "restore-data-current",
        "restore-site-current",
        "disable-site-current",
    ):
        assert f'"{label}"' in source


def test_site_only_release_rejects_mounted_or_data_bound_manifests(
    tmp_path: Path,
) -> None:
    code = _heredoc_after("assert_site_only_release_compatible()")
    manifest = tmp_path / "release-manifest.json"

    manifest.write_text(json.dumps({"schema_version": "legacy"}), encoding="utf-8")
    legacy = _run_embedded(code, [str(manifest)])
    assert legacy.returncode == 0, legacy.stderr

    manifest.write_text(
        json.dumps({"data_runtime": {"mode": "read_only_versioned_mount"}}),
        encoding="utf-8",
    )
    mounted = _run_embedded(code, [str(manifest)])
    assert mounted.returncode != 0
    assert "supply all four data bindings" in mounted.stderr

    manifest.write_text(
        json.dumps({"current_release": {"release_id": FROM_DATA_ID}}),
        encoding="utf-8",
    )
    bound = _run_embedded(code, [str(manifest)])
    assert bound.returncode != 0
    assert "supply all four data bindings" in bound.stderr


def test_site_only_rollback_requires_exact_allowlisted_v1_json() -> None:
    source = _source()
    assert "--promotion-receipt <path> --promotion-receipt-sha <sha256>" in source
    assert 'if [[ "${DUAL_DATA_ROLLBACK}" == "1" ]]; then' in source
    assert 'rollback-release-$(date -u +%Y%m%dT%H%M%SZ)-${EXPECTED_CURRENT}-to-${TARGET_RELEASE}.txt' in source
    assert 'echo "data_rollback=false"' in source
    assert 'rollback-disable-$(date -u +%Y%m%dT%H%M%SZ)-${EXPECTED_CURRENT}.txt' in source
    assert 'assert_site_only_release_compatible "${EXPECTED_CURRENT}"' in source
    assert 'assert_site_only_release_compatible "${TARGET_RELEASE}"' in source
    assert "v1_allowlist = {" in source
    assert "plaintext allowlist is empty" in source
    assert "HISTORICAL_LEGACY_CONTAINER_RECEIPTS" not in source
    assert 'root.glob("promotion-' not in source
    assert "accepted_target" not in source
    assert "validate_acceptance" not in source
