from __future__ import annotations

import copy
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import tempfile
import tarfile
from typing import Any
import unittest

from scripts import build_reddit_promotion_packet as packet_builder
from scripts import observe_production_insights_baseline as observer


def runtime_fixture() -> tuple[dict[str, Any], dict[str, Any]]:
    release = "a" * 64
    binding = [{"HostIp": "172.20.0.1", "HostPort": "18338"}]
    container: dict[str, Any] = {
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
                        "wget -q -O /dev/null "
                        "http://127.0.0.1:8080/healthz && "
                        "wget -q -O /dev/null "
                        "http://127.0.0.1:8080/data/reddit-voc/"
                        "current-release.json"
                    ),
                ],
                "Interval": 10_000_000_000,
                "Timeout": 3_000_000_000,
                "Retries": 6,
                "StartPeriod": 5_000_000_000,
            },
            "Image": f"reddit-voc-insights:{release}",
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
            "LogConfig": {
                "Type": "json-file",
                "Config": {"max-file": "3", "max-size": "10m"},
            },
            "Memory": 268435456,
            "NanoCpus": 500000000,
            "NetworkMode": "reddit_voc_insights_net",
            "PidMode": "",
            "PidsLimit": 100,
            "PortBindings": {"8080/tcp": binding},
            "Privileged": False,
            "ReadonlyRootfs": True,
            "RestartPolicy": {
                "MaximumRetryCount": 0,
                "Name": "unless-stopped",
            },
            "Runtime": "runc",
            "SecurityOpt": ["no-new-privileges:true"],
            "Sysctls": None,
            "Tmpfs": {
                "/tmp": (
                    "rw,noexec,nosuid,nodev,size=32m,uid=101,gid=101,mode=1777"
                )
            },
            "UTSMode": "",
            "Ulimits": None,
            "UsernsMode": "",
        },
        "Image": "sha256:" + "b" * 64,
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
                "reddit_voc_insights_net": {"NetworkID": "c" * 64}
            },
            "Ports": {"8080/tcp": binding},
        },
        "State": {"Health": {"Status": "healthy"}, "Running": True},
    }
    network: dict[str, Any] = {
        "Driver": "bridge",
        "Id": "c" * 64,
        "Internal": False,
        "Name": "reddit_voc_insights_net",
        "Options": {
            "com.docker.network.bridge.enable_icc": "false",
            "com.docker.network.bridge.enable_ip_masquerade": "false",
        },
    }
    return container, network


class ProductionBaselineObserverTests(unittest.TestCase):
    def test_runtime_contract_matches_packet_validator(self) -> None:
        self.assertEqual(
            observer.OBSERVER_RUNTIME_CONTRACT,
            packet_builder.BASELINE_OBSERVER_RUNTIME_CONTRACT,
        )
        self.assertEqual(
            observer.OBSERVER_RUNTIME_SHA256,
            packet_builder.BASELINE_OBSERVER_RUNTIME_SHA256,
        )

    def test_observer_does_not_require_nonpublic_release_manifest_route(self) -> None:
        source = Path(observer.__file__).read_text(encoding="utf-8")
        self.assertNotIn(
            "http://172.20.0.1:18338/release-manifest.json",
            source,
        )
        self.assertIn(
            '"served_exact": True',
            source,
        )

    def test_site_manifest_extracts_exact_data_tuple_and_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            release = Path(temporary)
            release_sha = "a" * 64
            pointer_sha = "b" * 64
            payload = {
                "schema_version": "reddit_voc_insights_site_release_v2",
                "release_sha256": release_sha,
                "current_release": {
                    "path": "data/reddit-voc/current-release.json",
                    "release_id": "reddit_voc_release_fixture_001",
                    "sha256": pointer_sha,
                    "data_inventory_sha256": "c" * 64,
                    "data_file_count": 7,
                    "data_total_bytes": 4096,
                },
            }
            (release / "release-manifest.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )
            result = observer.site_release_manifest(
                release, release_sha256=release_sha
            )
            self.assertEqual(result["data_release_id"], "reddit_voc_release_fixture_001")
            self.assertEqual(result["pointer_sha256"], pointer_sha)
            self.assertEqual(result["data_inventory_sha256"], "c" * 64)
            self.assertEqual(result["data_file_count"], 7)
            self.assertEqual(result["data_total_bytes"], 4096)

    def test_image_id_is_derived_from_authenticated_archive_config(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            reference = "reddit-voc-insights:" + "a" * 64
            config = b'{"architecture":"amd64","os":"linux"}\n'
            digest = sha256(config).hexdigest()
            for layout, config_name in (
                ("legacy", f"{digest}.json"),
                ("oci", f"blobs/sha256/{digest}"),
            ):
                path = Path(temporary) / f"image-{layout}.tar"
                manifest = json.dumps(
                    [
                        {
                            "Config": config_name,
                            "Layers": [],
                            "RepoTags": [reference],
                        }
                    ],
                    separators=(",", ":"),
                ).encode()
                with tarfile.open(path, "w:") as archive:
                    for name, payload in (
                        ("manifest.json", manifest),
                        (config_name, config),
                    ):
                        info = tarfile.TarInfo(name)
                        info.size = len(payload)
                        archive.addfile(info, io.BytesIO(payload))
                with self.subTest(layout=layout):
                    self.assertEqual(
                        observer.expected_image_id_from_archive(path, reference),
                        f"sha256:{digest}",
                    )
                    with self.assertRaisesRegex(SystemExit, "identity mismatch"):
                        observer.expected_image_id_from_archive(
                            path, reference + "-wrong"
                        )

    def test_site_manifest_rejects_partial_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            release = Path(temporary)
            release_sha = "a" * 64
            (release / "release-manifest.json").write_text(
                json.dumps(
                    {
                        "schema_version": "reddit_voc_insights_site_release_v2",
                        "release_sha256": release_sha,
                        "current_release": {
                            "path": "data/reddit-voc/current-release.json",
                            "release_id": "reddit_voc_release_fixture_001",
                            "sha256": "b" * 64,
                            "data_inventory_sha256": "c" * 64,
                        },
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(SystemExit, "inventory is incomplete"):
                observer.site_release_manifest(release, release_sha256=release_sha)

    def test_full_runtime_contract_is_emitted(self) -> None:
        container, network = runtime_fixture()
        result = observer.validate_insights_runtime(
            container,
            network,
            release_sha256="a" * 64,
            expected_image_id="sha256:" + "b" * 64,
        )
        self.assertFalse(result["privileged"])
        self.assertEqual(result["cap_drop"], ["ALL"])
        self.assertTrue(result["no_new_privileges"])
        self.assertEqual(
            result["host_port_binding"],
            {"HostIp": "172.20.0.1", "HostPort": "18338"},
        )
        self.assertFalse(result["collector_listener_reachable"])

    def test_full_runtime_contract_accepts_absent_empty_device_lists(self) -> None:
        container, network = runtime_fixture()
        host = container["HostConfig"]
        assert isinstance(host, dict)
        host["Devices"] = None
        host["DeviceRequests"] = None
        result = observer.validate_insights_runtime(
            container,
            network,
            release_sha256="a" * 64,
            expected_image_id="sha256:" + "b" * 64,
        )
        self.assertFalse(result["device_access"])

    def test_full_runtime_contract_rejects_security_and_isolation_drift(self) -> None:
        mutations = {
            "privileged": ("HostConfig", "Privileged", True),
            "cap_add": ("HostConfig", "CapAdd", ["NET_ADMIN"]),
            "cap_drop": ("HostConfig", "CapDrop", []),
            "security_opt": ("HostConfig", "SecurityOpt", []),
            "init": ("HostConfig", "Init", False),
            "pids": ("HostConfig", "PidsLimit", 101),
            "memory": ("HostConfig", "Memory", 0),
            "cpu": ("HostConfig", "NanoCpus", 0),
            "restart": (
                "HostConfig",
                "RestartPolicy",
                {"Name": "always", "MaximumRetryCount": 0},
            ),
            "pid_namespace": ("HostConfig", "PidMode", "host"),
            "ipc_namespace": ("HostConfig", "IpcMode", "host"),
            "devices": (
                "HostConfig",
                "Devices",
                [{"PathOnHost": "/dev/null", "PathInContainer": "/dev/null"}],
            ),
            "runtime": ("HostConfig", "Runtime", "kata"),
            "logging": (
                "HostConfig",
                "LogConfig",
                {"Type": "json-file", "Config": {}},
            ),
            "tmpfs": ("HostConfig", "Tmpfs", {"/tmp": "rw"}),
            "network_mode": ("HostConfig", "NetworkMode", "bridge"),
            "user": ("Config", "User", "0:0"),
            "entrypoint": ("Config", "Entrypoint", ["/bin/sh"]),
            "command": ("Config", "Cmd", ["sleep", "infinity"]),
            "environment": ("Config", "Env", ["PATH=/usr/bin"]),
        }
        for name, (section, field, value) in mutations.items():
            with self.subTest(name=name):
                container, network = runtime_fixture()
                nested = container[section]
                assert isinstance(nested, dict)
                nested[field] = value
                with self.assertRaisesRegex(SystemExit, "runtime contract"):
                    observer.validate_insights_runtime(
                        container,
                        network,
                        release_sha256="a" * 64,
                        expected_image_id="sha256:" + "b" * 64,
                    )

        container, network = runtime_fixture()
        unsafe_network = copy.deepcopy(network)
        unsafe_network["Internal"] = True
        with self.assertRaisesRegex(SystemExit, "runtime contract"):
            observer.validate_insights_runtime(
                container,
                unsafe_network,
                release_sha256="a" * 64,
                expected_image_id="sha256:" + "b" * 64,
            )

        container, network = runtime_fixture()
        mounts = container["Mounts"]
        assert isinstance(mounts, list) and isinstance(mounts[0], dict)
        mounts[0]["RW"] = True
        with self.assertRaisesRegex(SystemExit, "mount contract"):
            observer.validate_insights_runtime(
                container,
                network,
                release_sha256="a" * 64,
                expected_image_id="sha256:" + "b" * 64,
            )

        container, network = runtime_fixture()
        with self.assertRaisesRegex(SystemExit, "runtime contract"):
            observer.validate_insights_runtime(
                container,
                network,
                release_sha256="a" * 64,
                expected_image_id="sha256:" + "d" * 64,
            )

        container, network = runtime_fixture()
        attached = container["NetworkSettings"]["Networks"][  # type: ignore[index]
            "reddit_voc_insights_net"
        ]
        assert isinstance(attached, dict)
        attached["NetworkID"] = "d" * 64
        with self.assertRaisesRegex(SystemExit, "runtime contract"):
            observer.validate_insights_runtime(
                container,
                network,
                release_sha256="a" * 64,
                expected_image_id="sha256:" + "b" * 64,
            )

    def test_all_three_lock_identities_are_bound_and_reverified(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = {
                name: root / f"{name}.lock"
                for name in packet_builder.BASELINE_LOCK_PATHS
            }
            for path in paths.values():
                path.write_bytes(b"")
                path.chmod(0o600)
            original = observer.LOCK_PATHS
            observer.LOCK_PATHS = paths
            descriptors: dict[str, int] = {}
            try:
                descriptors, identities = observer.acquire_shared_locks()
                self.assertEqual(set(identities), set(paths))
                self.assertTrue(observer.reverify_shared_locks(descriptors, identities))
                self.assertTrue(
                    all(identity["uid"] == os.getuid() for identity in identities.values())
                )
                self.assertTrue(
                    all(identity["mode"] == "0600" for identity in identities.values())
                )
            finally:
                for descriptor in descriptors.values():
                    os.close(descriptor)
                observer.LOCK_PATHS = original


if __name__ == "__main__":
    unittest.main()
