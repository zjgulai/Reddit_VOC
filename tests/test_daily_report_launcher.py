from __future__ import annotations

import ast
import os
import json
import fcntl
import stat
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.build_daily_report_release import build_release


ROOT = Path(__file__).resolve().parents[1]


class DailyReportLauncherTests(unittest.TestCase):
    def test_host_binary_contract_accepts_root_owned_0777_symlink_to_safe_executable(
        self,
    ) -> None:
        """A normal Ubuntu /usr/bin/python3 symlink must not fail before cron starts."""
        launcher = (ROOT / "scripts/server_daily_report.sh").read_text(
            encoding="utf-8"
        )
        function_start = launcher.index("verify_production_binary()")
        source_start = launcher.index("import os\n", function_start)
        source_end = launcher.index("\nPY\n}", source_start)
        embedded = launcher[source_start:source_end]
        tree = ast.parse(embedded)
        contract_module = ast.Module(
            body=[
                node
                for node in tree.body
                if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef))
            ],
            type_ignores=[],
        )
        namespace: dict[str, object] = {}
        exec(compile(contract_module, "<host-binary-contract>", "exec"), namespace)
        verify = namespace.get("verify_binary_chain")
        self.assertTrue(callable(verify), "launcher must expose its embedded validator")
        validate_metadata = namespace.get("validate_binary_metadata")
        self.assertTrue(callable(validate_metadata))
        synthetic_symlink = type(
            "SyntheticStat",
            (),
            {"st_uid": os.getuid(), "st_mode": stat.S_IFLNK | 0o777},
        )()
        self.assertTrue(
            validate_metadata(synthetic_symlink, owner_uid=os.getuid())
        )

        with tempfile.TemporaryDirectory() as tmp:
            trusted_root = Path(tmp) / "trusted"
            bin_root = trusted_root / "usr-bin"
            bin_root.mkdir(parents=True, mode=0o700)
            executable = bin_root / "python3.10"
            executable.write_bytes(b"#!/bin/sh\nexit 0\n")
            executable.chmod(0o755)
            symlink = bin_root / "python3"
            symlink.symlink_to(executable.name)

            resolved = verify(
                symlink,
                owner_uid=os.getuid(),
                trusted_root=trusted_root,
                expected_parent=bin_root,
                expected_name_prefix="python3",
                expected_exact=None,
            )
            self.assertEqual(resolved, executable.resolve(strict=True))

            executable.chmod(0o777)
            with self.assertRaises(ValueError):
                verify(
                    symlink,
                    owner_uid=os.getuid(),
                    trusted_root=trusted_root,
                    expected_parent=bin_root,
                    expected_name_prefix="python3",
                    expected_exact=None,
                )

    def _write_fake_docker(self, path: Path) -> None:
        path.write_text(
            f"#!{sys.executable}\n"
            + r'''import json
import os
import subprocess
import sys
import time
from pathlib import Path

args = sys.argv[1:]
call_log = Path(os.environ["FAKE_CALL_LOG"])
with call_log.open("a", encoding="utf-8") as handle:
    handle.write("docker " + " ".join(args) + "\n")
state_path = Path(os.environ["FAKE_DOCKER_STATE"])
log_path = Path(os.environ["FAKE_DOCKER_LOG"])
exit_path = Path(os.environ["FAKE_DOCKER_EXIT"])
container_id = "fake-cid"


def load_state():
    if not state_path.exists():
        return {"active": False, "inspect": {}}
    return json.loads(state_path.read_text(encoding="utf-8"))


def save_state(value):
    state_path.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )


if args[:2] == ["image", "inspect"]:
    format_value = args[args.index("--format") + 1]
    if format_value != "{{json .Config.Env}}":
        raise SystemExit(1)
    print(os.environ.get("FAKE_IMAGE_ENV", "[]"))
elif args[:2] == ["network", "inspect"]:
    state = load_state()
    format_value = args[args.index("--format") + 1]
    if format_value == "{{.Driver}}":
        print("bridge")
    elif format_value == "{{len .Containers}}":
        print("1" if state["active"] else "0")
    elif format_value == "{{json .Containers}}":
        print(json.dumps({container_id: {}} if state["active"] else {}))
    else:
        raise SystemExit(1)
elif args and args[0] == "run":
    value_options = {
        "--cidfile",
        "--network",
        "--user",
        "--cpus",
        "--memory",
        "--pids-limit",
        "--cap-drop",
        "--security-opt",
        "--tmpfs",
        "--mount",
        "--entrypoint",
    }
    flag_options = {"-d", "--rm", "--pull=never", "--read-only"}
    values = {}
    mount_specs = []
    index = 1
    while index < len(args):
        token = args[index]
        if token in flag_options:
            values[token] = True
            index += 1
        elif token in value_options:
            if index + 1 >= len(args):
                raise SystemExit(1)
            values.setdefault(token, []).append(args[index + 1])
            if token == "--mount":
                mount_specs.append(args[index + 1])
            index += 2
        else:
            image = token
            command = args[index + 1 :]
            break
    else:
        raise SystemExit(1)
    cidfile = Path(values["--cidfile"][0])
    cidfile.write_text(container_id + "\n", encoding="utf-8")
    mounts = []
    for specification in mount_specs:
        fields = {}
        readonly = False
        for part in specification.split(","):
            if part == "readonly":
                readonly = True
            else:
                key, value = part.split("=", 1)
                fields[key] = value
        mounts.append(
            {
                "Type": fields["type"],
                "Source": fields["src"],
                "Destination": fields["dst"],
                "RW": not readonly,
            }
        )
    if os.environ.get("FAKE_TAMPER_MOUNT") == "1" and mounts:
        mounts[0]["RW"] = not mounts[0]["RW"]
    inspect = {
        "image": image,
        "user": values["--user"][0],
        "nano_cpus": "1000000000",
        "memory": "2147483648",
        "pids": values["--pids-limit"][0],
        "read_only": "true" if values.get("--read-only") else "false",
        "network_mode": values["--network"][0],
        "cap_drop": values["--cap-drop"],
        "security_opt": values["--security-opt"],
        "tmpfs": {"/tmp": values["--tmpfs"][0].split(":", 1)[1]},
        "privileged": "false",
        "pid_mode": "",
        "mounts": mounts,
        "networks": (
            {} if values["--network"][0] == "none"
            else {values["--network"][0]: {}}
        ),
        "environment": json.loads(os.environ.get("FAKE_INSPECT_ENV", "[]")),
        "entrypoint": [values["--entrypoint"][0]],
        "command": command,
    }
    save_state({"active": True, "inspect": inspect})
    if os.environ.get("FAKE_REAL_PREPARE") == "1":
        runtime_env = next(
            Path(item["Source"])
            for item in mounts
            if item["Destination"] == "/run/secrets/reddit_voc_report.env"
        )
        payload = runtime_env.read_text(encoding="utf-8")
        payload = payload.replace(
            "REDDIT_VOC_CONFIG_ROOT=/app/config",
            f"REDDIT_VOC_CONFIG_ROOT={os.environ['FAKE_RELEASE']}/config",
        )
        runtime_env.write_text(payload, encoding="utf-8")
        runtime_env.chmod(0o600)
        command_line = [
            "bash",
            str(Path(os.environ["FAKE_RELEASE"]) / "scripts/run_daily_report.sh"),
            "prepare",
            "--prepare-action-authorization-id",
            os.environ["FAKE_ACTION_ID"],
        ]
        provider_id = os.environ.get("FAKE_PROVIDER_ID")
        if provider_id:
            command_line.extend(["--provider-authorization-id", provider_id])
        environment = {
            **os.environ,
            "REDDIT_VOC_PROJECT_ROOT": os.environ["FAKE_RELEASE"],
            "REDDIT_VOC_CLI_PYTHON_BIN": os.environ["FAKE_PYTHON"],
            "REDDIT_VOC_SYSTEM_PYTHON_BIN": os.environ["FAKE_PYTHON"],
            "REDDIT_VOC_REPORT_ENV_FILE": str(runtime_env),
            "PYTHONPATH": str(Path(os.environ["FAKE_RELEASE"]) / "src"),
        }
        with log_path.open("wb") as handle:
            completed = subprocess.run(
                command_line,
                env=environment,
                stdout=handle,
                stderr=subprocess.STDOUT,
                check=False,
            )
        exit_path.write_text(str(completed.returncode) + "\n", encoding="utf-8")
    elif os.environ.get("FAKE_BLOCKED_PREPARE") == "1":
        result = {
            "status": "blocked",
            "run_id": os.environ["FAKE_RUN_ID"],
            "attempt_id": os.environ["FAKE_ATTEMPT_ID"],
            "blocked_manifest_sha256": "0" * 64,
            "provider_authorization_id": None,
            "translation_provider_call": False,
            "translation_provider_attempt_made": False,
        }
        log_path.write_text(json.dumps(result) + "\n", encoding="utf-8")
        exit_path.write_text("1\n", encoding="utf-8")
    elif os.environ.get("FAKE_SEND_RESULT") == "dual-partial":
        result = {
            "status": "partially_sent",
            "run_id": os.environ["FAKE_RUN_ID"],
            "artifact_version_id": os.environ["FAKE_VERSION_ID"],
            "outbox_sha256": os.environ["FAKE_OUTBOX_SHA"],
            "destinations": [
                {
                    "destination_id": "primary",
                    "attempted_part_indexes": [1],
                    "sent_part_indexes": [1],
                    "rejected_part_indexes": [],
                    "ledger_tip_before": None,
                    "ledger_tip_after": "d" * 64,
                    "status": "sent",
                    "report_live_send": True,
                },
                {
                    "destination_id": "secondary",
                    "attempted_part_indexes": [1],
                    "sent_part_indexes": [],
                    "rejected_part_indexes": [1],
                    "ledger_tip_before": None,
                    "ledger_tip_after": "e" * 64,
                    "status": "rejected",
                    "report_live_send": True,
                },
            ],
            "report_live_send": True,
            "alert_live_send": False,
            "live_send": True,
        }
        log_path.write_text(json.dumps(result) + "\n", encoding="utf-8")
        exit_path.write_text("1\n", encoding="utf-8")
    elif os.environ.get("FAKE_SEND_RESULT") == "sent":
        result = {
            "status": "sent",
            "run_id": os.environ["FAKE_RUN_ID"],
            "artifact_version_id": os.environ["FAKE_VERSION_ID"],
            "outbox_sha256": os.environ["FAKE_OUTBOX_SHA"],
            "attempted_part_indexes": [1],
            "sent_part_indexes": [1],
            "rejected_part_indexes": [],
            "ledger_tip_before": None,
            "ledger_tip_after": "f" * 64,
            "report_live_send": True,
            "alert_live_send": False,
            "live_send": True,
        }
        log_path.write_text(json.dumps(result) + "\n", encoding="utf-8")
        exit_path.write_text("0\n", encoding="utf-8")
    else:
        log_path.write_bytes(b"")
        exit_path.write_text("0\n", encoding="utf-8")
    print(container_id)
elif args and args[0] == "inspect":
    state = load_state()["inspect"]
    format_value = args[args.index("--format") + 1]
    mapping = {
        "{{.Image}}": state["image"],
        "{{.Config.User}}": state["user"],
        "{{.HostConfig.NanoCpus}}": state["nano_cpus"],
        "{{.HostConfig.Memory}}": state["memory"],
        "{{.HostConfig.PidsLimit}}": state["pids"],
        "{{.HostConfig.ReadonlyRootfs}}": state["read_only"],
        "{{.HostConfig.NetworkMode}}": state["network_mode"],
        "{{json .HostConfig.CapDrop}}": json.dumps(state["cap_drop"]),
        "{{json .HostConfig.SecurityOpt}}": json.dumps(state["security_opt"]),
        "{{json .HostConfig.Tmpfs}}": json.dumps(state["tmpfs"]),
        "{{.HostConfig.Privileged}}": state["privileged"],
        "{{.HostConfig.PidMode}}": state["pid_mode"],
        "{{json .Mounts}}": json.dumps(state["mounts"]),
        "{{json .NetworkSettings.Networks}}": json.dumps(state["networks"]),
        "{{json .Config.Env}}": json.dumps(state["environment"]),
        "{{json .Config.Entrypoint}}": json.dumps(state["entrypoint"]),
        "{{json .Config.Cmd}}": json.dumps(state["command"]),
    }
    if format_value not in mapping:
        raise SystemExit(1)
    print(mapping[format_value])
elif args and args[0] == "logs":
    if os.environ.get("FAKE_LOG_DELAY"):
        time.sleep(float(os.environ["FAKE_LOG_DELAY"]))
    sys.stdout.buffer.write(log_path.read_bytes())
elif args and args[0] == "wait":
    sys.stdout.write(exit_path.read_text(encoding="utf-8"))
    state = load_state()
    state["active"] = False
    save_state(state)
elif args[:2] == ["rm", "-f"]:
    state = load_state()
    state["active"] = False
    save_state(state)
else:
    raise SystemExit(1)
''',
            encoding="utf-8",
        )
        path.chmod(0o700)

    def test_fixed_launcher_has_lock_first_and_pinned_docker_contract(self) -> None:
        path = ROOT / "scripts/server_daily_report.sh"
        text = path.read_text(encoding="utf-8")
        self.assertIn("flock -n", text)
        release_readlink = text.index('RELEASE_DIR="$(readlink')
        self.assertLess(text.index("flock -n"), release_readlink)
        self.assertLess(release_readlink, text.index('"$DOCKER_BIN" run'))
        for token in [
            '"$DOCKER_BIN" run',
            "--pull=never",
            '--network "$CONTAINER_NETWORK"',
            "--cpus 1.0",
            "--memory 2g",
            "--pids-limit 256",
            "--cap-drop ALL",
            "--security-opt no-new-privileges:true",
            "--cidfile",
            "--user \"$REPORT_UID:$REPORT_GID\"",
            "--entrypoint /bin/bash",
            "/run/report-gate/permit",
            "{{json .Mounts}}",
            "{{json .NetworkSettings.Networks}}",
            "{{json .Config.Env}}",
            "{{json .Config.Entrypoint}}",
            "{{json .HostConfig.CapDrop}}",
            "{{json .HostConfig.SecurityOpt}}",
        ]:
            self.assertIn(token, text)
        self.assertLess(
            text.index("inspected_mounts="), text.index("permit_path=")
        )
        self.assertLess(text.index("permit_path="), text.index('"logs", "-f"'))
        self.assertNotIn("docker compose", text)
        self.assertNotIn("deploy_webapp_tencent", text)
        self.assertNotIn("reddit_voc_site_net", text)
        self.assertNotIn("lighthouse_ai_video_net", text)
        self.assertNotIn("provider_authorization_id_not_distinct", text)
        self.assertIn("/opt/reddit-voc-daily-report/current", text)
        self.assertIn("/opt/reddit-voc-daily-report/releases", text)
        self.assertIn("/opt/reddit-voc-daily-report/state", text)
        self.assertIn("/opt/reddit-voc-daily-report/blocked", text)
        self.assertIn("/opt/reddit-voc-daily-report/handoff", text)
        self.assertNotIn("/opt/reddit-voc-report/current", text)
        self.assertNotIn("/opt/reddit-voc-report/state", text)
        self.assertNotIn("/opt/reddit-voc-report/blocked", text)
        self.assertNotIn("/opt/reddit-voc-report/handoff", text)

    def test_no_argument_cron_route_is_prepare_only_and_never_schedules_send(self) -> None:
        text = (ROOT / "scripts/server_daily_report.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn('operation="${1:-scheduled-prepare}"', text)
        self.assertIn('"$ADMIN" reserve-scheduled-prepare', text)
        self.assertIn('PROVIDER_AUTHORIZATION_ID="$PREPARE_ACTION_ID"', text)
        self.assertIn('if [[ "$SCHEDULED_CYCLE" == "1" ]]', text)
        self.assertNotIn('"$UPDATER" set-gates', text)
        self.assertNotIn('"$UPDATER" restore-gates', text)
        self.assertIn('"$UPDATER" verify-base-env', text)

    def test_no_argument_cron_route_reaches_lock_without_host_launch_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = root / "fake-bin"
            fake.mkdir(mode=0o700)
            marker = root / "unexpected-call"
            flock = fake / "flock"
            flock.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
            flock.chmod(0o700)
            for name in ("readlink", "docker"):
                path = fake / name
                path.write_text(
                    "#!/usr/bin/env bash\n"
                    f"printf called >{marker}\n"
                    "exit 99\n",
                    encoding="utf-8",
                )
                path.chmod(0o700)
            completed = subprocess.run(
                ["bash", str(ROOT / "scripts/server_daily_report.sh")],
                env={
                    **os.environ,
                    "REDDIT_VOC_LOCAL_TEST_MODE": "1",
                    "REDDIT_VOC_LOCAL_SCHEDULE_NOW": (
                        "2026-07-15T08:00:00+08:00"
                    ),
                    "REDDIT_VOC_REPORT_LOCK_FILE": str(root / "report.lock"),
                    "REDDIT_VOC_LOCAL_BLOCKED_ROOT": str(root / "blocked"),
                    "REDDIT_VOC_HOST_PYTHON_BIN": sys.executable,
                    "PATH": f"{fake}:{os.environ.get('PATH', '')}",
                },
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 1)
            self.assertIn("reason=lock_busy", completed.stderr)
            self.assertNotIn("host_launch_not_authorized", completed.stderr)
            self.assertFalse(marker.exists())

    def test_production_rejects_binary_uid_and_docker_environment_overrides(
        self,
    ) -> None:
        completed = subprocess.run(
            ["bash", str(ROOT / "scripts/server_daily_report.sh"), "scheduled-cycle"],
            env={
                **os.environ,
                "REDDIT_VOC_DOCKER_BIN": "/tmp/hostile-docker",
                "REDDIT_VOC_REPORT_UID": "0",
                "REDDIT_VOC_REPORT_CYCLE_LEASE_ROOT": "/tmp/hostile-lease",
                "DOCKER_HOST": "tcp://hostile.invalid:2375",
            },
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 1)
        self.assertIn(
            "reason=production_environment_override_forbidden",
            completed.stderr,
        )

    def test_local_test_flag_cannot_retarget_scheduled_cycle_at_production(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir(mode=0o700)
            flock = fake_bin / "flock"
            flock.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            flock.chmod(0o700)
            completed = subprocess.run(
                [
                    "bash",
                    str(ROOT / "scripts/server_daily_report.sh"),
                    "scheduled-cycle",
                ],
                env={
                    **os.environ,
                    "REDDIT_VOC_LOCAL_TEST_MODE": "1",
                    "REDDIT_VOC_REPORT_LOCK_FILE": str(root / "report.lock"),
                    "REDDIT_VOC_HOST_PYTHON_BIN": sys.executable,
                    "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
                },
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 1)
            self.assertIn(
                "reason=local_test_production_scope_forbidden",
                completed.stderr,
            )

    def test_stable_launcher_inherited_lock_is_reused_without_self_deadlock(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lock = root / "daily-report.lock"
            lock.write_bytes(b"")
            lock.chmod(0o600)
            shadow = root / "shadow"
            current = root / "current"
            releases = root / "releases"
            shadow.mkdir(mode=0o700)
            releases.mkdir(mode=0o700)
            descriptor = os.open(lock, os.O_RDWR)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                completed = subprocess.run(
                    [
                        "bash",
                        str(ROOT / "scripts/server_daily_report.sh"),
                        "scheduled-cycle",
                    ],
                    env={
                        **os.environ,
                        "REDDIT_VOC_LOCAL_TEST_MODE": "1",
                        "REDDIT_VOC_REPORT_LOCK_FILE": str(lock),
                        "REDDIT_VOC_REPORT_CURRENT_LINK": str(current),
                        "REDDIT_VOC_REPORT_RELEASES_ROOT": str(releases),
                        "REDDIT_VOC_LOCAL_SHADOW_ROOT": str(shadow),
                        "REDDIT_VOC_LOCAL_SCHEDULE_NOW": (
                            "2026-08-12T08:00:00+08:00"
                        ),
                        "REDDIT_VOC_DAILY_LOCK_FD": str(descriptor),
                        "REDDIT_VOC_G6R1_STABLE_VERIFIED": "1",
                    },
                    pass_fds=(descriptor,),
                    capture_output=True,
                    text=True,
                    check=False,
                )
            finally:
                os.close(descriptor)
            self.assertEqual(completed.returncode, 1)
            self.assertNotIn("reason=lock_busy", completed.stderr)
            self.assertNotIn("reason=inherited_lock_fd_invalid", completed.stderr)
            self.assertIn("reason=release_pointer_invalid", completed.stderr)

    def test_scheduled_cycle_lease_uses_runtime_root_when_lock_parent_is_read_only(
        self,
    ) -> None:
        """A protected shared-lock directory must not block an ubuntu lease FD."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lock_parent = root / "control" / "locks"
            lock_parent.mkdir(parents=True, mode=0o700)
            lock = lock_parent / "daily-report.lock"
            lock.write_bytes(b"")
            lock.chmod(0o600)
            lease_root = root / "run" / "cycle-leases"
            lease_root.mkdir(parents=True, mode=0o700)
            shadow = root / "shadow"
            current = root / "current"
            releases = root / "releases"
            shadow.mkdir(mode=0o700)
            releases.mkdir(mode=0o700)
            descriptor = os.open(lock, os.O_RDWR)
            lock_parent.chmod(0o500)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                completed = subprocess.run(
                    [
                        "bash",
                        str(ROOT / "scripts/server_daily_report.sh"),
                        "scheduled-cycle",
                    ],
                    env={
                        **os.environ,
                        "REDDIT_VOC_LOCAL_TEST_MODE": "1",
                        "REDDIT_VOC_REPORT_LOCK_FILE": str(lock),
                        "REDDIT_VOC_REPORT_CYCLE_LEASE_ROOT": str(lease_root),
                        "REDDIT_VOC_REPORT_CURRENT_LINK": str(current),
                        "REDDIT_VOC_REPORT_RELEASES_ROOT": str(releases),
                        "REDDIT_VOC_LOCAL_SHADOW_ROOT": str(shadow),
                        "REDDIT_VOC_LOCAL_SCHEDULE_NOW": (
                            "2026-08-20T08:00:00+08:00"
                        ),
                        "REDDIT_VOC_DAILY_LOCK_FD": str(descriptor),
                        "REDDIT_VOC_G6R1_STABLE_VERIFIED": "1",
                    },
                    pass_fds=(descriptor,),
                    capture_output=True,
                    text=True,
                    check=False,
                )
            finally:
                lock_parent.chmod(0o700)
                os.close(descriptor)
            self.assertEqual(completed.returncode, 1)
            self.assertNotIn("reason=cycle_lease_create_failed", completed.stderr)
            self.assertNotIn("reason=cycle_lease_root_invalid", completed.stderr)
            self.assertIn("reason=release_pointer_invalid", completed.stderr)
            self.assertEqual(list(lease_root.iterdir()), [])

    def test_scheduled_cycle_rejects_a_lease_root_with_wrong_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lock = root / "daily-report.lock"
            lock.write_bytes(b"")
            lock.chmod(0o600)
            lease_root = root / "cycle-leases"
            lease_root.mkdir(mode=0o700)
            lease_root.chmod(0o755)
            shadow = root / "shadow"
            current = root / "current"
            releases = root / "releases"
            shadow.mkdir(mode=0o700)
            releases.mkdir(mode=0o700)
            descriptor = os.open(lock, os.O_RDWR)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                completed = subprocess.run(
                    [
                        "bash",
                        str(ROOT / "scripts/server_daily_report.sh"),
                        "scheduled-cycle",
                    ],
                    env={
                        **os.environ,
                        "REDDIT_VOC_LOCAL_TEST_MODE": "1",
                        "REDDIT_VOC_REPORT_LOCK_FILE": str(lock),
                        "REDDIT_VOC_REPORT_CYCLE_LEASE_ROOT": str(lease_root),
                        "REDDIT_VOC_REPORT_CURRENT_LINK": str(current),
                        "REDDIT_VOC_REPORT_RELEASES_ROOT": str(releases),
                        "REDDIT_VOC_LOCAL_SHADOW_ROOT": str(shadow),
                        "REDDIT_VOC_LOCAL_SCHEDULE_NOW": (
                            "2026-08-20T08:00:00+08:00"
                        ),
                        "REDDIT_VOC_DAILY_LOCK_FD": str(descriptor),
                        "REDDIT_VOC_G6R1_STABLE_VERIFIED": "1",
                    },
                    pass_fds=(descriptor,),
                    capture_output=True,
                    text=True,
                    check=False,
                )
            finally:
                os.close(descriptor)
            self.assertEqual(completed.returncode, 1)
            self.assertIn("reason=cycle_lease_root_invalid", completed.stderr)
            self.assertEqual(list(lease_root.iterdir()), [])

    def test_production_cycle_lease_never_uses_the_shared_lock_parent(self) -> None:
        launcher = (ROOT / "scripts/server_daily_report.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            'PRODUCTION_CYCLE_LEASE_ROOT="/home/ubuntu/.reddit-voc/run/cycle-leases"',
            launcher,
        )
        self.assertIn(
            'mktemp "$CYCLE_LEASE_ROOT/.g6r1-cycle-lease.XXXXXX"',
            launcher,
        )
        self.assertNotIn(
            'mktemp "$(dirname "$LOCK_FILE")/.g6r1-cycle-lease.XXXXXX"',
            launcher,
        )
        self.assertIn(
            'verify_cycle_lease_root || fail "cycle_lease_root_invalid"',
            launcher,
        )

    def test_scheduled_cycle_closes_prepare_commit_derive_and_exact_send(self) -> None:
        text = (ROOT / "scripts/server_daily_report.sh").read_text(
            encoding="utf-8"
        )
        reserve = text.index('"$ADMIN" reserve-scheduled-cycle')
        commit = text.index('"$ADMIN" commit-prepared')
        derive = text.index('"$ADMIN" derive-scheduled-send-permit')
        send = text.index('"$RELEASE_DIR/scripts/server_daily_report.sh" send')
        self.assertLess(reserve, commit)
        self.assertLess(commit, derive)
        self.assertLess(derive, send)
        self.assertIn('--cycle-lease-fd "$CYCLE_LEASE_FD"', text)
        self.assertNotIn("--cycle-lease-token", text)
        self.assertIn('DELIVERY_LEDGER_ROOT="$STATE_ROOT/delivery"', text)
        gate_validation = text.index('"$ADMIN" validate-send-permit-use')
        gate_release = text.index(
            '"$PYTHON_BIN" - \\\n  "$permit_path"', gate_validation
        )
        self.assertLess(gate_validation, gate_release)

    def test_scheduled_cycle_is_admitted_by_the_prepare_branch(self) -> None:
        """The cron operation must not fall through to the smoke-only branch."""
        text = (ROOT / "scripts/server_daily_report.sh").read_text(
            encoding="utf-8"
        )
        branch_start = text.index(
            'elif [[ "$operation" == "prepare"'
        )
        branch_header_end = text.index("; then", branch_start)
        branch_header = text[branch_start:branch_header_end]
        self.assertIn(
            '"$operation" == "scheduled-cycle"',
            branch_header,
        )
        reserve = text.index('"$ADMIN" reserve-scheduled-cycle', branch_header_end)
        fallback = text.index(
            '\nelse\n  [[ "$exit_code" == "0" ]]',
            branch_header_end,
        )
        self.assertLess(reserve, fallback)

    def test_wrapper_and_launcher_never_route_to_legacy_report_send(self) -> None:
        combined = "\n".join(
            (ROOT / path).read_text(encoding="utf-8")
            for path in ["scripts/run_daily_report.sh", "scripts/server_daily_report.sh"]
        )
        for forbidden in [
            "run_daily_report_dry_run.sh",
            "build-daily-report",
            "send-daily-report-live",
            "docker compose",
        ]:
            self.assertNotIn(forbidden, combined)
        self.assertIn("--defer-host-commit", combined)

    def test_lock_contention_writes_only_sanitized_blocked_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = root / "fake-bin"
            fake.mkdir(mode=0o700)
            marker = root / "unexpected-call"
            flock = fake / "flock"
            flock.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
            for name in ("readlink", "docker"):
                path = fake / name
                path.write_text(
                    "#!/usr/bin/env bash\n"
                    f"printf called >{marker}\n"
                    "exit 99\n",
                    encoding="utf-8",
                )
                path.chmod(0o700)
            flock.chmod(0o700)
            blocked_root = root / "blocked"
            completed = subprocess.run(
                [
                    "bash",
                    str(ROOT / "scripts/server_daily_report.sh"),
                    "prepare",
                    "--authorize-host-launch",
                    "--prepare-action-authorization-id",
                    "prepare-lock-busy",
                ],
                env={
                    **os.environ,
                    "REDDIT_VOC_LOCAL_TEST_MODE": "1",
                    "REDDIT_VOC_ENABLE_HOST_LAUNCH": "1",
                    "REDDIT_VOC_RUN_ID": "daily_collect_20260714_0700",
                    "REDDIT_VOC_REPORT_LOCK_FILE": str(root / "report.lock"),
                    "REDDIT_VOC_LOCAL_BLOCKED_ROOT": str(blocked_root),
                    "REDDIT_VOC_HOST_PYTHON_BIN": sys.executable,
                    "PATH": f"{fake}:{os.environ.get('PATH', '')}",
                },
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 1)
            self.assertIn("reason=lock_busy", completed.stderr)
            self.assertFalse(marker.exists())
            manifests = list(blocked_root.rglob("blocked-manifest.json"))
            self.assertEqual(len(manifests), 1)
            manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
            self.assertEqual(manifest["reason_codes"], ["lock_busy"])
            self.assertFalse(manifest["provider_call"])
            self.assertFalse(manifest["translation_provider_attempt_made"])
            self.assertNotIn("source_text", json.dumps(manifest))

    def test_fake_send_uses_exact_permit_tuple_and_send_only_mounts(self) -> None:
        """Catches host send bypassing its permit or inheriting prepare authority."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            releases = root / "releases"
            releases.mkdir(mode=0o700)
            image_id = "sha256:" + "9" * 64
            release = build_release(
                source_root=ROOT,
                destination_root=releases,
                image_id=image_id,
            )
            current = root / "current"
            current.symlink_to(release)
            shadow = root / "shadow"
            initialized = subprocess.run(
                [
                    "bash",
                    str(ROOT / "scripts/server_daily_report_admin.sh"),
                    "init-shadow-root",
                    "--shadow-root",
                    str(shadow),
                    "--authorization-id",
                    "shadow-launcher-send",
                    "--expected-release-sha256",
                    release.name,
                    "--candidate-sha256",
                    "8" * 64,
                    "--authorize-shadow-provisioning",
                ],
                env={
                    **os.environ,
                    "REDDIT_VOC_LOCAL_TEST_MODE": "1",
                    "REDDIT_VOC_HOST_PYTHON_BIN": sys.executable,
                },
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(initialized.returncode, 0, initialized.stderr)
            shadow = shadow.resolve(strict=True)
            database = shadow / "database/reddit_voc.sqlite3"
            database.write_bytes(b"fixture")
            database.chmod(0o600)
            base_env = shadow / "secrets/reddit-voc-report.env"
            base_env.write_text(
                "REDDIT_VOC_TRANSLATION_MODE=dry_run\n"
                "REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION=0\n"
                "REDDIT_VOC_DINGTALK_MODE=dry_run\n"
                "REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND=0\n"
                "REDDIT_VOC_ENABLE_REPORT_FAILURE_ALERT=0\n",
                encoding="utf-8",
            )
            base_env.chmod(0o600)

            fake = root / "fake-control"
            fake.mkdir(mode=0o700)
            log = root / "calls.log"
            updater = fake / "updater"
            updater.write_text(
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                "printf 'updater %s\\n' \"$*\" >>\"$FAKE_CALL_LOG\"\n"
                "if [[ \"$1\" == materialize-send-env ]]; then\n"
                "  attempt=''\n"
                "  while [[ $# -gt 0 ]]; do\n"
                "    if [[ \"$1\" == --attempt-id ]]; then attempt=\"$2\"; break; fi\n"
                "    shift\n"
                "  done\n"
                "  mkdir -p \"$FAKE_SHADOW/control/runtime-env\"\n"
                "  printf 'fixture=1\\n' >\"$FAKE_SHADOW/control/runtime-env/$attempt.env\"\n"
                "  chmod 600 \"$FAKE_SHADOW/control/runtime-env/$attempt.env\"\n"
                "  printf 'destination_mode=%s\\n' \"${FAKE_DESTINATION_MODE:-single}\"\n"
                "elif [[ \"$1\" == remove-runtime-env ]]; then\n"
                "  attempt=''\n"
                "  while [[ $# -gt 0 ]]; do\n"
                "    if [[ \"$1\" == --attempt-id ]]; then attempt=\"$2\"; break; fi\n"
                "    shift\n"
                "  done\n"
                "  rm -f \"$FAKE_SHADOW/control/runtime-env/$attempt.env\"\n"
                "fi\n",
                encoding="utf-8",
            )
            admin = fake / "admin"
            admin.write_text(
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                "printf 'admin %s\\n' \"$*\" >>\"$FAKE_CALL_LOG\"\n",
                encoding="utf-8",
            )
            docker = fake / "docker"
            self._write_fake_docker(docker)
            flock = fake / "flock"
            flock.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            for path in (updater, admin, docker, flock):
                path.chmod(0o700)

            run_id = "daily_collect_20260715_0700"
            version_id = "20260715T010203456789Z-" + "9" * 32
            bundle_sha = "a" * 64
            outbox_sha = "b" * 64
            authorization_id = "send-launcher-exact"
            completed = subprocess.run(
                [
                    "bash",
                    str(ROOT / "scripts/server_daily_report.sh"),
                    "send",
                    "--authorize-host-launch",
                    "--authorization-id",
                    authorization_id,
                    "--expected-artifact-version-id",
                    version_id,
                    "--expected-bundle-sha256",
                    bundle_sha,
                    "--expected-outbox-sha256",
                    outbox_sha,
                ],
                env={
                    **os.environ,
                    "REDDIT_VOC_LOCAL_TEST_MODE": "1",
                    "REDDIT_VOC_RUN_ID": run_id,
                    "REDDIT_VOC_ENABLE_HOST_LAUNCH": "1",
                    "REDDIT_VOC_REPORT_LOCK_FILE": str(root / "daily-report.lock"),
                    "REDDIT_VOC_REPORT_CURRENT_LINK": str(current),
                    "REDDIT_VOC_REPORT_RELEASES_ROOT": str(releases),
                    "REDDIT_VOC_REPORT_CIDFILE": str(root / "report.cid"),
                    "REDDIT_VOC_LOCAL_FAKE_CONTROL_DIR": str(fake),
                    "REDDIT_VOC_DOCKER_BIN": str(docker),
                    "REDDIT_VOC_HOST_PYTHON_BIN": sys.executable,
                    "REDDIT_VOC_LOCAL_SHADOW_ROOT": str(shadow),
                    "FAKE_CALL_LOG": str(log),
                    "FAKE_DOCKER_STATE": str(root / "docker-state.json"),
                    "FAKE_DOCKER_LOG": str(root / "container.log"),
                    "FAKE_DOCKER_EXIT": str(root / "container.exit"),
                    "FAKE_SEND_RESULT": "sent",
                    "FAKE_RUN_ID": run_id,
                    "FAKE_VERSION_ID": version_id,
                    "FAKE_OUTBOX_SHA": outbox_sha,
                    "FAKE_SHADOW": str(shadow),
                    "PATH": f"{fake}:{os.environ.get('PATH', '')}",
                },
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            calls = log.read_text(encoding="utf-8")
            self.assertIn("admin reserve-send-permit", calls)
            self.assertIn(f"--authorization-id {authorization_id}", calls)
            self.assertIn(f"--expected-artifact-version-id {version_id}", calls)
            self.assertIn(f"--expected-bundle-sha256 {bundle_sha}", calls)
            self.assertIn(f"--expected-outbox-sha256 {outbox_sha}", calls)
            self.assertIn("updater materialize-send-env", calls)
            self.assertIn("admin terminalize-send-permit", calls)
            self.assertIn("--terminal-status consumed", calls)
            self.assertIn(f"src={database},dst={database}", calls)
            self.assertIn(
                f"src={shadow / 'state'},dst={shadow / 'state'},readonly", calls
            )
            ledger_run = shadow / "state" / "delivery" / run_id
            self.assertIn(
                f"src={ledger_run},dst={ledger_run}", calls
            )
            for forbidden in (
                "deepseek-api-key",
                "provider-attempts",
                "public-staging",
                "private-staging",
                "handoff",
            ):
                self.assertNotIn(forbidden, calls)
            self.assertIn("status=sent", completed.stdout)
            self.assertIn("live_send=true", completed.stdout)

    def test_fake_dual_send_routes_once_and_terminalizes_partial_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            releases = root / "releases"
            releases.mkdir(mode=0o700)
            release = build_release(
                source_root=ROOT,
                destination_root=releases,
                image_id="sha256:" + "9" * 64,
            )
            current = root / "current"
            current.symlink_to(release)
            shadow = root / "shadow"
            initialized = subprocess.run(
                [
                    "bash",
                    str(ROOT / "scripts/server_daily_report_admin.sh"),
                    "init-shadow-root",
                    "--shadow-root",
                    str(shadow),
                    "--authorization-id",
                    "shadow-launcher-dual",
                    "--expected-release-sha256",
                    release.name,
                    "--candidate-sha256",
                    "8" * 64,
                    "--authorize-shadow-provisioning",
                ],
                env={
                    **os.environ,
                    "REDDIT_VOC_LOCAL_TEST_MODE": "1",
                    "REDDIT_VOC_HOST_PYTHON_BIN": sys.executable,
                },
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(initialized.returncode, 0, initialized.stderr)
            shadow = shadow.resolve(strict=True)
            database = shadow / "database/reddit_voc.sqlite3"
            database.write_bytes(b"fixture")
            database.chmod(0o600)
            base_env = shadow / "secrets/reddit-voc-report.env"
            base_env.write_text(
                "REDDIT_VOC_TRANSLATION_MODE=dry_run\n"
                "REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION=0\n"
                "REDDIT_VOC_DINGTALK_MODE=dry_run\n"
                "REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND=0\n"
                "REDDIT_VOC_ENABLE_REPORT_FAILURE_ALERT=0\n",
                encoding="utf-8",
            )
            base_env.chmod(0o600)
            fake = root / "fake-control"
            fake.mkdir(mode=0o700)
            call_log = root / "calls.log"
            updater = fake / "updater"
            updater.write_text(
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                "printf 'updater %s\\n' \"$*\" >>\"$FAKE_CALL_LOG\"\n"
                "if [[ \"$1\" == materialize-send-env ]]; then\n"
                "  attempt=''\n"
                "  while [[ $# -gt 0 ]]; do\n"
                "    if [[ \"$1\" == --attempt-id ]]; then attempt=\"$2\"; break; fi\n"
                "    shift\n"
                "  done\n"
                "  mkdir -p \"$FAKE_SHADOW/control/runtime-env\"\n"
                "  printf 'fixture=1\\n' >\"$FAKE_SHADOW/control/runtime-env/$attempt.env\"\n"
                "  chmod 600 \"$FAKE_SHADOW/control/runtime-env/$attempt.env\"\n"
                "  printf 'destination_mode=dual\\n'\n"
                "elif [[ \"$1\" == remove-runtime-env ]]; then\n"
                "  attempt=''\n"
                "  while [[ $# -gt 0 ]]; do\n"
                "    if [[ \"$1\" == --attempt-id ]]; then attempt=\"$2\"; break; fi\n"
                "    shift\n"
                "  done\n"
                "  rm -f \"$FAKE_SHADOW/control/runtime-env/$attempt.env\"\n"
                "fi\n",
                encoding="utf-8",
            )
            admin = fake / "admin"
            admin.write_text(
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                "printf 'admin %s\\n' \"$*\" >>\"$FAKE_CALL_LOG\"\n",
                encoding="utf-8",
            )
            docker = fake / "docker"
            self._write_fake_docker(docker)
            flock = fake / "flock"
            flock.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            for path in (updater, admin, docker, flock):
                path.chmod(0o700)

            run_id = "daily_collect_20260812_0700"
            version_id = "20260812T010203456789Z-" + "9" * 32
            completed = subprocess.run(
                [
                    "bash",
                    str(ROOT / "scripts/server_daily_report.sh"),
                    "send",
                    "--authorize-host-launch",
                    "--authorization-id",
                    "send-launcher-dual",
                    "--expected-artifact-version-id",
                    version_id,
                    "--expected-bundle-sha256",
                    "a" * 64,
                    "--expected-outbox-sha256",
                    "b" * 64,
                ],
                env={
                    **os.environ,
                    "REDDIT_VOC_LOCAL_TEST_MODE": "1",
                    "REDDIT_VOC_RUN_ID": run_id,
                    "REDDIT_VOC_ENABLE_HOST_LAUNCH": "1",
                    "REDDIT_VOC_REPORT_LOCK_FILE": str(root / "daily-report.lock"),
                    "REDDIT_VOC_REPORT_CURRENT_LINK": str(current),
                    "REDDIT_VOC_REPORT_RELEASES_ROOT": str(releases),
                    "REDDIT_VOC_REPORT_CIDFILE": str(root / "report.cid"),
                    "REDDIT_VOC_LOCAL_FAKE_CONTROL_DIR": str(fake),
                    "REDDIT_VOC_DOCKER_BIN": str(docker),
                    "REDDIT_VOC_HOST_PYTHON_BIN": sys.executable,
                    "REDDIT_VOC_LOCAL_SHADOW_ROOT": str(shadow),
                    "FAKE_CALL_LOG": str(call_log),
                    "FAKE_DOCKER_STATE": str(root / "docker-state.json"),
                    "FAKE_DOCKER_LOG": str(root / "container.log"),
                    "FAKE_DOCKER_EXIT": str(root / "container.exit"),
                    "FAKE_SEND_RESULT": "dual-partial",
                    "FAKE_RUN_ID": run_id,
                    "FAKE_VERSION_ID": version_id,
                    "FAKE_OUTBOX_SHA": "b" * 64,
                    "FAKE_SHADOW": str(shadow),
                    "PATH": f"{fake}:{os.environ.get('PATH', '')}",
                },
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 1, completed.stderr)
            calls = call_log.read_text(encoding="utf-8")
            self.assertIn(
                "bash /app/scripts/run_daily_report.sh send-dual", calls
            )
            self.assertEqual(calls.count("docker run "), 1)
            self.assertIn("--terminal-status partial", calls)
            self.assertIn("--delivery-status partially_sent", calls)
            self.assertIn("--primary-delivery-status sent", calls)
            self.assertIn("--secondary-delivery-status rejected", calls)
            self.assertIn("--primary-ledger-tip " + "d" * 64, calls)
            self.assertIn("--secondary-ledger-tip " + "e" * 64, calls)
            self.assertIn("status=partially_sent", completed.stdout)
            self.assertIn("destination_mode=dual", completed.stdout)

    def test_fake_smoke_runtime_verifies_release_recovers_under_inherited_lock_and_mounts_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            releases = root / "releases"
            releases.mkdir(mode=0o700)
            image_id = "sha256:" + "7" * 64
            release = build_release(
                source_root=ROOT,
                destination_root=releases,
                image_id=image_id,
            )
            current = root / "current"
            current.symlink_to(release)
            fake = root / "fake-control"
            fake.mkdir(mode=0o700)
            log = root / "calls.log"
            updater = fake / "updater"
            updater.write_text(
                "#!/usr/bin/env bash\n"
                "printf 'updater %s\\n' \"$*\" >>\"$FAKE_CALL_LOG\"\n",
                encoding="utf-8",
            )
            admin = fake / "admin"
            admin.write_text(
                "#!/usr/bin/env bash\n"
                "printf 'admin %s\\n' \"$*\" >>\"$FAKE_CALL_LOG\"\n",
                encoding="utf-8",
            )
            docker = fake / "docker"
            self._write_fake_docker(docker)
            flock = fake / "flock"
            flock.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            for path in (updater, admin, docker, flock):
                path.chmod(0o700)
            lock_descriptor = os.open(
                root / "daily-report.lock", os.O_RDWR | os.O_CREAT, 0o600
            )
            fcntl.flock(lock_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                completed = subprocess.run(
                    [
                        "bash",
                        str(ROOT / "scripts/server_daily_report.sh"),
                        "smoke",
                        "--authorize-host-launch",
                    ],
                    env={
                        **os.environ,
                        "REDDIT_VOC_LOCAL_TEST_MODE": "1",
                        "REDDIT_VOC_RUN_ID": "daily_collect_20260714_0700",
                        "REDDIT_VOC_ENABLE_HOST_LAUNCH": "1",
                        "REDDIT_VOC_INHERITED_LOCK_FD": str(lock_descriptor),
                        "REDDIT_VOC_REPORT_LOCK_FILE": str(root / "daily-report.lock"),
                        "REDDIT_VOC_REPORT_CURRENT_LINK": str(current),
                        "REDDIT_VOC_REPORT_RELEASES_ROOT": str(releases),
                        "REDDIT_VOC_REPORT_CIDFILE": str(root / "report.cid"),
                        "REDDIT_VOC_LOCAL_FAKE_CONTROL_DIR": str(fake),
                        "REDDIT_VOC_DOCKER_BIN": str(docker),
                        "REDDIT_VOC_HOST_PYTHON_BIN": "python3",
                        "FAKE_CALL_LOG": str(log),
                        "FAKE_IMAGE_ID": image_id,
                        "FAKE_DOCKER_STATE": str(root / "docker-state.json"),
                        "FAKE_DOCKER_LOG": str(root / "container.log"),
                        "FAKE_DOCKER_EXIT": str(root / "container.exit"),
                        "FAKE_IMAGE_ENV": json.dumps(
                            ["PATH=/usr/local/bin", "GPG_KEY=base-image-key"]
                        ),
                        "FAKE_INSPECT_ENV": json.dumps(
                            ["PATH=/usr/local/bin", "GPG_KEY=base-image-key"]
                        ),
                        "PATH": f"{fake}:{os.environ.get('PATH', '')}",
                    },
                    capture_output=True,
                    text=True,
                    check=False,
                    pass_fds=(lock_descriptor,),
                )
            finally:
                os.close(lock_descriptor)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            calls = log.read_text(encoding="utf-8")
            self.assertLess(calls.index("updater verify-base-env"), calls.index("admin recover-prepared-state"))
            self.assertLess(calls.index("admin recover-prepared-state"), calls.index("docker run"))
            self.assertIn(f"--inherited-lock-fd {lock_descriptor}", calls)
            self.assertIn("--pull=never", calls)
            self.assertIn("--network none", calls)
            self.assertNotIn("docker network inspect", calls)
            self.assertIn("dst=/app/src/reddit_voc/cli.py", calls)
            self.assertIn("dst=/app/scripts/run_daily_report.sh", calls)
            self.assertNotIn(f"src={release},dst=/app", calls)
            self.assertNotIn("deepseek-api-key", calls)
            self.assertNotIn("reddit-voc-report.env", calls)
            self.assertIn("provider_call=false", completed.stdout)
            self.assertIn("live_send=false", completed.stdout)

            log.write_text("", encoding="utf-8")
            tampered = subprocess.run(
                [
                    "bash",
                    str(ROOT / "scripts/server_daily_report.sh"),
                    "smoke",
                    "--authorize-host-launch",
                ],
                env={
                    **os.environ,
                    "REDDIT_VOC_LOCAL_TEST_MODE": "1",
                    "REDDIT_VOC_RUN_ID": "daily_collect_20260714_0700",
                    "REDDIT_VOC_ENABLE_HOST_LAUNCH": "1",
                    "REDDIT_VOC_REPORT_LOCK_FILE": str(root / "daily-report.lock"),
                    "REDDIT_VOC_REPORT_CURRENT_LINK": str(current),
                    "REDDIT_VOC_REPORT_RELEASES_ROOT": str(releases),
                    "REDDIT_VOC_REPORT_CIDFILE": str(root / "report.cid"),
                    "REDDIT_VOC_LOCAL_FAKE_CONTROL_DIR": str(fake),
                    "REDDIT_VOC_DOCKER_BIN": str(docker),
                    "REDDIT_VOC_HOST_PYTHON_BIN": sys.executable,
                    "FAKE_CALL_LOG": str(log),
                    "FAKE_IMAGE_ID": image_id,
                    "FAKE_DOCKER_STATE": str(root / "docker-state.json"),
                    "FAKE_DOCKER_LOG": str(root / "container.log"),
                    "FAKE_DOCKER_EXIT": str(root / "container.exit"),
                    "FAKE_TAMPER_MOUNT": "1",
                    "PATH": f"{fake}:{os.environ.get('PATH', '')}",
                },
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(tampered.returncode, 1)
            self.assertIn("reason=report_container_mount_mismatch", tampered.stderr)
            tampered_calls = log.read_text(encoding="utf-8")
            self.assertNotIn("docker logs", tampered_calls)
            self.assertFalse((root / "report.cid").exists())

            log.write_text("", encoding="utf-8")
            timed_out = subprocess.run(
                [
                    "bash",
                    str(ROOT / "scripts/server_daily_report.sh"),
                    "smoke",
                    "--authorize-host-launch",
                ],
                env={
                    **os.environ,
                    "REDDIT_VOC_LOCAL_TEST_MODE": "1",
                    "REDDIT_VOC_RUN_ID": "daily_collect_20260714_0700",
                    "REDDIT_VOC_ENABLE_HOST_LAUNCH": "1",
                    "REDDIT_VOC_REPORT_TIMEOUT_SECONDS": "1",
                    "REDDIT_VOC_REPORT_LOCK_FILE": str(root / "daily-report.lock"),
                    "REDDIT_VOC_REPORT_CURRENT_LINK": str(current),
                    "REDDIT_VOC_REPORT_RELEASES_ROOT": str(releases),
                    "REDDIT_VOC_REPORT_CIDFILE": str(root / "report.cid"),
                    "REDDIT_VOC_LOCAL_FAKE_CONTROL_DIR": str(fake),
                    "REDDIT_VOC_DOCKER_BIN": str(docker),
                    "REDDIT_VOC_HOST_PYTHON_BIN": sys.executable,
                    "FAKE_CALL_LOG": str(log),
                    "FAKE_IMAGE_ID": image_id,
                    "FAKE_DOCKER_STATE": str(root / "docker-state.json"),
                    "FAKE_DOCKER_LOG": str(root / "container.log"),
                    "FAKE_DOCKER_EXIT": str(root / "container.exit"),
                    "FAKE_LOG_DELAY": "2",
                    "PATH": f"{fake}:{os.environ.get('PATH', '')}",
                },
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(timed_out.returncode, 1)
            self.assertIn("reason=report_container_timeout", timed_out.stderr)
            self.assertFalse((root / "report.cid").exists())

            log.write_text("", encoding="utf-8")
            argv_leak_marker = root / "metadata-secret-seen-in-argv"
            python_wrapper = fake / "python-wrapper"
            python_wrapper.write_text(
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                "for argument in \"$@\"; do\n"
                "  if [[ \"$argument\" == *argv-canary* ]]; then\n"
                f"    : >{str(argv_leak_marker)!r}\n"
                "  fi\n"
                "done\n"
                f"exec {sys.executable!r} \"$@\"\n",
                encoding="utf-8",
            )
            python_wrapper.chmod(0o700)
            sensitive_env = subprocess.run(
                [
                    "bash",
                    str(ROOT / "scripts/server_daily_report.sh"),
                    "smoke",
                    "--authorize-host-launch",
                ],
                env={
                    **os.environ,
                    "REDDIT_VOC_LOCAL_TEST_MODE": "1",
                    "REDDIT_VOC_RUN_ID": "daily_collect_20260714_0700",
                    "REDDIT_VOC_ENABLE_HOST_LAUNCH": "1",
                    "REDDIT_VOC_REPORT_LOCK_FILE": str(root / "daily-report.lock"),
                    "REDDIT_VOC_REPORT_CURRENT_LINK": str(current),
                    "REDDIT_VOC_REPORT_RELEASES_ROOT": str(releases),
                    "REDDIT_VOC_REPORT_CIDFILE": str(root / "report.cid"),
                    "REDDIT_VOC_LOCAL_FAKE_CONTROL_DIR": str(fake),
                    "REDDIT_VOC_DOCKER_BIN": str(docker),
                    "REDDIT_VOC_HOST_PYTHON_BIN": str(python_wrapper),
                    "FAKE_CALL_LOG": str(log),
                    "FAKE_IMAGE_ID": image_id,
                    "FAKE_DOCKER_STATE": str(root / "docker-state.json"),
                    "FAKE_DOCKER_LOG": str(root / "container.log"),
                    "FAKE_DOCKER_EXIT": str(root / "container.exit"),
                    "FAKE_INSPECT_ENV": json.dumps(
                        ["DINGTALK_WEBHOOK_SECRET_2=argv-canary"]
                    ),
                    "PATH": f"{fake}:{os.environ.get('PATH', '')}",
                },
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(sensitive_env.returncode, 1)
            self.assertIn(
                "reason=report_container_metadata_mismatch", sensitive_env.stderr
            )
            self.assertFalse(argv_leak_marker.exists())
            self.assertNotIn(
                "argv-canary", sensitive_env.stdout + sensitive_env.stderr
            )

    def test_blocked_prepare_is_host_committed_after_worker_exit_one(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            releases = root / "releases"
            releases.mkdir(mode=0o700)
            image_id = "sha256:" + "8" * 64
            release = build_release(
                source_root=ROOT,
                destination_root=releases,
                image_id=image_id,
            )
            current = root / "current"
            current.symlink_to(release)
            shadow = root / "shadow"
            for relative in [
                "secrets",
                "control/runtime-env",
                "database",
                "public",
                "private",
                "public-staging",
                "private-staging",
                "state",
                "blocked",
                "handoff",
                "provider-attempts",
            ]:
                path = shadow / relative
                path.mkdir(parents=True, exist_ok=True, mode=0o700)
                path.chmod(0o755 if relative == "public" else 0o700)
            database = shadow / "database/reddit_voc.sqlite3"
            database.write_bytes(b"fixture")
            database.chmod(0o600)
            report_env = shadow / "secrets/reddit-voc-report.env"
            report_env.write_text(
                "REDDIT_VOC_TRANSLATION_MODE=dry_run\n"
                "REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION=0\n"
                "REDDIT_VOC_DINGTALK_MODE=dry_run\n"
                "REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND=0\n"
                "REDDIT_VOC_ENABLE_REPORT_FAILURE_ALERT=0\n",
                encoding="utf-8",
            )
            report_env.chmod(0o600)

            fake = root / "fake-control"
            fake.mkdir(mode=0o700)
            log = root / "calls.log"
            updater = fake / "updater"
            updater.write_text(
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                "printf 'updater %s\\n' \"$*\" >>\"$FAKE_CALL_LOG\"\n"
                "if [[ \"$1\" == materialize-prepare-env ]]; then\n"
                "  attempt=''\n"
                "  while [[ $# -gt 0 ]]; do\n"
                "    if [[ \"$1\" == --attempt-id ]]; then attempt=\"$2\"; break; fi\n"
                "    shift\n"
                "  done\n"
                "  printf 'fixture=1\\n' >\"$FAKE_SHADOW/control/runtime-env/$attempt.env\"\n"
                "  chmod 600 \"$FAKE_SHADOW/control/runtime-env/$attempt.env\"\n"
                "elif [[ \"$1\" == remove-runtime-env ]]; then\n"
                "  attempt=''\n"
                "  while [[ $# -gt 0 ]]; do\n"
                "    if [[ \"$1\" == --attempt-id ]]; then attempt=\"$2\"; break; fi\n"
                "    shift\n"
                "  done\n"
                "  rm -f \"$FAKE_SHADOW/control/runtime-env/$attempt.env\"\n"
                "fi\n",
                encoding="utf-8",
            )
            admin = fake / "admin"
            admin.write_text(
                "#!/usr/bin/env bash\n"
                "printf 'admin %s\\n' \"$*\" >>\"$FAKE_CALL_LOG\"\n",
                encoding="utf-8",
            )
            docker = fake / "docker"
            self._write_fake_docker(docker)
            flock = fake / "flock"
            flock.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            for path in (updater, admin, docker, flock):
                path.chmod(0o700)

            run_id = "daily_collect_20260714_0700"
            attempt_id = "attempt-launcher-blocked"
            completed = subprocess.run(
                [
                    "bash",
                    str(ROOT / "scripts/server_daily_report.sh"),
                    "prepare",
                    "--authorize-host-launch",
                    "--prepare-action-authorization-id",
                    "prepare-action-launcher-blocked",
                ],
                env={
                    **os.environ,
                    "REDDIT_VOC_LOCAL_TEST_MODE": "1",
                    "REDDIT_VOC_RUN_ID": run_id,
                    "REDDIT_VOC_ENABLE_HOST_LAUNCH": "1",
                    "REDDIT_VOC_REPORT_LOCK_FILE": str(root / "daily-report.lock"),
                    "REDDIT_VOC_REPORT_CURRENT_LINK": str(current),
                    "REDDIT_VOC_REPORT_RELEASES_ROOT": str(releases),
                    "REDDIT_VOC_REPORT_CIDFILE": str(root / "report.cid"),
                    "REDDIT_VOC_LOCAL_FAKE_CONTROL_DIR": str(fake),
                    "REDDIT_VOC_DOCKER_BIN": str(docker),
                    "REDDIT_VOC_HOST_PYTHON_BIN": sys.executable,
                    "REDDIT_VOC_LOCAL_SHADOW_ROOT": str(shadow),
                    "REDDIT_VOC_LOCAL_ATTEMPT_ID": attempt_id,
                    "REDDIT_VOC_LOCAL_ARTIFACT_VERSION_ID": (
                        "20260714T010203456789Z-" + "8" * 32
                    ),
                    "FAKE_CALL_LOG": str(log),
                    "FAKE_IMAGE_ID": image_id,
                    "FAKE_RUN_ID": run_id,
                    "FAKE_ATTEMPT_ID": attempt_id,
                    "FAKE_BLOCKED_PREPARE": "1",
                    "FAKE_DOCKER_STATE": str(root / "docker-state.json"),
                    "FAKE_DOCKER_LOG": str(root / "container.log"),
                    "FAKE_DOCKER_EXIT": str(root / "container.exit"),
                    "FAKE_SHADOW": str(shadow),
                    "PATH": f"{fake}:{os.environ.get('PATH', '')}",
                },
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(
                completed.returncode,
                1,
                completed.stderr
                + "\nstdout:\n"
                + completed.stdout
                + "\ncalls:\n"
                + log.read_text(encoding="utf-8"),
            )
            self.assertIn("status=blocked", completed.stdout)
            self.assertIn("provider_call=false", completed.stdout)
            self.assertIn("live_send=false", completed.stdout)
            calls = log.read_text(encoding="utf-8")
            self.assertIn("admin commit-blocked", calls)
            self.assertIn("updater remove-runtime-env", calls)

    def test_fake_docker_runs_real_cache_only_prepare_and_host_commit_without_send(self) -> None:
        from tests.test_prepared_report import PreparedReportTests

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            releases = root / "releases"
            releases.mkdir(mode=0o700)
            image_id = "sha256:" + "6" * 64
            release = build_release(
                source_root=ROOT,
                destination_root=releases,
                image_id=image_id,
            )
            current = root / "current"
            current.symlink_to(release)
            action_id = "prepare-action-launcher-cache"
            provider_id = "provider-action-launcher-cache"
            run_id = "daily_collect_20260713_0700"
            attempt_id = "attempt-launcher-cache"
            version_id = "20260714T010203456789Z-" + "6" * 32
            shadow = (root / "shadow").resolve(strict=False)
            common_env = {
                **os.environ,
                "REDDIT_VOC_LOCAL_TEST_MODE": "1",
                "REDDIT_VOC_HOST_PYTHON_BIN": sys.executable,
            }
            initialized = subprocess.run(
                [
                    "bash",
                    str(ROOT / "scripts/server_daily_report_admin.sh"),
                    "init-shadow-root",
                    "--shadow-root",
                    str(shadow),
                    "--authorization-id",
                    "shadow-launcher-provision",
                    "--expected-release-sha256",
                    release.name,
                    "--candidate-sha256",
                    "5" * 64,
                    "--authorize-shadow-provisioning",
                ],
                env=common_env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(initialized.returncode, 0, initialized.stderr)
            shadow = shadow.resolve(strict=True)
            fixture_database = PreparedReportTests()._database(root, visible=False)
            database = shadow / "database" / "reddit_voc.sqlite3"
            shutil.copy2(fixture_database, database)
            database.chmod(0o600)
            runtime_env = shadow / "secrets" / "reddit-voc-report.env"
            runtime_env.write_text(
                "\n".join(
                    [
                        f"REDDIT_VOC_DATABASE_PATH={database}",
                        "REDDIT_VOC_RUN_ID=",
                        "REDDIT_VOC_ATTEMPT_ID=",
                        "REDDIT_VOC_ARTIFACT_VERSION_ID=",
                        "REDDIT_VOC_REPORT_PUBLIC_ROOT=",
                        "REDDIT_VOC_REPORT_PRIVATE_ROOT=",
                        "REDDIT_VOC_REPORT_PUBLIC_STAGING_ROOT=",
                        "REDDIT_VOC_REPORT_PRIVATE_STAGING_ROOT=",
                        "REDDIT_VOC_REPORT_STATE_ROOT=",
                        "REDDIT_VOC_REPORT_BLOCKED_ROOT=",
                        "REDDIT_VOC_REPORT_HANDOFF_ROOT=",
                        "REDDIT_VOC_PROVIDER_ATTEMPT_ROOT=",
                        "REDDIT_VOC_CONFIG_ROOT=",
                        "REDDIT_VOC_ARTIFACT_BASE_URL=https://reddit.lute-tlz-dddd.top/artifacts",
                        "DINGTALK_REQUIRED_KEYWORD=LL",
                        "REDDIT_VOC_DINGTALK_MAX_BYTES=18000",
                        "REDDIT_VOC_DINGTALK_MAX_PARTS=2",
                        "REDDIT_VOC_TRANSLATION_MODE=dry_run",
                        "REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION=0",
                        "REDDIT_VOC_DINGTALK_MODE=dry_run",
                        "REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND=0",
                        "REDDIT_VOC_ENABLE_REPORT_FAILURE_ALERT=0",
                        "DINGTALK_WEBHOOK_URL=",
                        "DINGTALK_WEBHOOK_SECRET=",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            runtime_env.chmod(0o600)
            key_path = shadow / "secrets" / "deepseek-api-key"
            key_path.write_text("sk-synthetic-launcher-only", encoding="utf-8")
            key_path.chmod(0o600)
            installed = subprocess.run(
                [
                    "bash",
                    str(ROOT / "scripts/server_daily_report_admin.sh"),
                    "install-prepare-permit",
                    "--shadow-root",
                    str(shadow),
                    "--authorization-id",
                    action_id,
                    "--expected-release-sha256",
                    release.name,
                    "--run-id",
                    run_id,
                    "--max-attempts",
                    "100",
                    "--expires-at",
                    "2030-07-14T00:00:00+00:00",
                ],
                env=common_env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(installed.returncode, 0, installed.stderr)
            provider_installed = subprocess.run(
                [
                    "bash",
                    str(ROOT / "scripts/server_daily_report_admin.sh"),
                    "install-shadow-permit",
                    "--shadow-root",
                    str(shadow),
                    "--authorization-id",
                    provider_id,
                    "--expected-release-sha256",
                    release.name,
                    "--run-id",
                    run_id,
                    "--copied-database-sha256",
                    "4" * 64,
                    "--max-attempts",
                    "100",
                    "--expires-at",
                    "2030-07-14T00:00:00+00:00",
                ],
                env=common_env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(
                provider_installed.returncode, 0, provider_installed.stderr
            )
            runtime_env_before = runtime_env.read_bytes()
            runtime_env_inode_before = runtime_env.stat().st_ino

            fake = root / "fake-bin"
            fake.mkdir(mode=0o700)
            call_log = root / "docker-calls.log"
            docker_log = root / "container.log"
            docker_exit = root / "container.exit"
            flock = fake / "flock"
            flock.write_text(
                f"#!{sys.executable}\n"
                "import fcntl\n"
                "fcntl.flock(9, fcntl.LOCK_EX | fcntl.LOCK_NB)\n",
                encoding="utf-8",
            )
            docker = fake / "docker"
            self._write_fake_docker(docker)
            flock.chmod(0o700)
            docker.chmod(0o700)
            lock_path = shadow / "lock"
            base_lock_descriptor = os.open(
                lock_path, os.O_RDWR | os.O_CREAT, 0o600
            )
            lock_descriptor = fcntl.fcntl(
                base_lock_descriptor, fcntl.F_DUPFD, 50
            )
            os.close(base_lock_descriptor)
            fcntl.flock(lock_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                completed = subprocess.run(
                    [
                        "bash",
                        str(ROOT / "scripts/server_daily_report.sh"),
                        "prepare",
                        "--authorize-host-launch",
                        "--prepare-action-authorization-id",
                        action_id,
                        "--provider-authorization-id",
                        provider_id,
                    ],
                    env={
                    **common_env,
                    "REDDIT_VOC_RUN_ID": run_id,
                    "REDDIT_VOC_ENABLE_HOST_LAUNCH": "1",
                    "REDDIT_VOC_REPORT_LOCK_FILE": str(lock_path),
                    "REDDIT_VOC_REPORT_CURRENT_LINK": str(current),
                    "REDDIT_VOC_REPORT_RELEASES_ROOT": str(releases),
                    "REDDIT_VOC_REPORT_CIDFILE": str(root / "report.cid"),
                    "REDDIT_VOC_DOCKER_BIN": str(docker),
                    "REDDIT_VOC_LOCAL_SHADOW_ROOT": str(shadow),
                    "REDDIT_VOC_LOCAL_ATTEMPT_ID": attempt_id,
                    "REDDIT_VOC_LOCAL_ARTIFACT_VERSION_ID": version_id,
                    "FAKE_CALL_LOG": str(call_log),
                    "FAKE_DOCKER_LOG": str(docker_log),
                    "FAKE_DOCKER_EXIT": str(docker_exit),
                    "FAKE_IMAGE_ID": image_id,
                    "FAKE_RELEASE": str(release),
                    "FAKE_PYTHON": sys.executable,
                    "FAKE_REAL_PREPARE": "1",
                    "FAKE_DOCKER_STATE": str(root / "docker-state.json"),
                    "FAKE_ACTION_ID": action_id,
                    "FAKE_PROVIDER_ID": provider_id,
                    "PATH": f"{fake}:{os.environ.get('PATH', '')}",
                    "REDDIT_VOC_LOCAL_INHERITED_LOCK_FD": str(lock_descriptor),
                    },
                    capture_output=True,
                    text=True,
                    check=False,
                    pass_fds=(lock_descriptor,),
                )
            finally:
                os.close(lock_descriptor)
            diagnostic = completed.stderr
            if docker_log.exists():
                diagnostic += "\ncontainer_log:\n" + docker_log.read_text(
                    encoding="utf-8"
                )
            if call_log.exists():
                diagnostic += "\ndocker_calls:\n" + call_log.read_text(
                    encoding="utf-8"
                )
            self.assertEqual(completed.returncode, 0, diagnostic)
            self.assertIn("status=complete", completed.stdout)
            self.assertIn("provider_call=false", completed.stdout)
            self.assertIn("report_live_send=false", completed.stdout)
            self.assertIn("alert_live_send=false", completed.stdout)
            self.assertIn("live_send=false", completed.stdout)
            self.assertNotIn("DINGTALK_WEBHOOK", call_log.read_text(encoding="utf-8"))
            self.assertIn(
                f"src={shadow / 'public-staging'},dst={shadow / 'public-staging'}",
                call_log.read_text(encoding="utf-8"),
            )
            self.assertIn(
                f"src={shadow / 'private-staging'},dst={shadow / 'private-staging'}",
                call_log.read_text(encoding="utf-8"),
            )
            self.assertIn(
                "dst=/run/secrets/deepseek_api_key,readonly",
                call_log.read_text(encoding="utf-8"),
            )
            current_pointer = json.loads(
                (shadow / "state" / "prepared-current.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(current_pointer["artifact_version_id"], version_id)
            permit_state = json.loads(
                shadow.joinpath(
                    "control", "permit-state", f"{action_id}.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(permit_state["status"], "consumed")
            provider_state = json.loads(
                shadow.joinpath(
                    "control", "permit-state", f"{provider_id}.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(provider_state["status"], "closed_no_attempt")
            final_env = runtime_env.read_text(encoding="utf-8")
            self.assertEqual(runtime_env.stat().st_ino, runtime_env_inode_before)
            self.assertEqual(runtime_env.read_bytes(), runtime_env_before)
            self.assertIn("REDDIT_VOC_TRANSLATION_MODE=dry_run", final_env)
            self.assertIn("REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION=0", final_env)
            self.assertIn("REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND=0", final_env)


if __name__ == "__main__":
    unittest.main()
