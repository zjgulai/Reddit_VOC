from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from scripts import build_reddit_candidate_monitor_receipt as monitor
from scripts.build_reddit_candidate_monitor_receipt import build_monitor_receipt


def _write(path: Path, value: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8") + b"\n"
    path.write_bytes(payload)
    path.chmod(0o600)
    return sha256(payload).hexdigest()


def _spec(probe: dict[str, object], *, interval: int = 0) -> dict[str, object]:
    return {
        "schema_version": "reddit_voc_candidate_monitor_spec_v1",
        "observation_interval_seconds": interval,
        "probes": [probe],
    }


def _spec_v2(
    terminal_marker: dict[str, object],
    probes: list[dict[str, object]],
    *,
    interval: int = 0,
) -> dict[str, object]:
    return {
        "schema_version": "reddit_voc_candidate_monitor_spec_v2",
        "observation_interval_seconds": interval,
        "terminal_marker": terminal_marker,
        "probes": probes,
    }


class _Response:
    def __init__(self, payload: bytes, status: int = 200, url: str | None = None) -> None:
        self.payload = payload
        self.status = status
        self.url = url

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def getcode(self) -> int:
        return self.status

    def geturl(self) -> str:
        return self.url or "http://127.0.0.1:18339/healthz"

    def read(self, limit: int) -> bytes:
        return self.payload[:limit]


class RedditCandidateMonitorTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_local_terminal_quiescence_receipt_is_immutable_and_body_free(self) -> None:
        state = self.root / "state.json"
        state_sha = _write(state, {"pipeline": {"status": "complete"}})
        spec = self.root / "spec.json"
        _write(
            spec,
            _spec(
                {
                    "id": "collector-state",
                    "kind": "file",
                    "target": str(state),
                    "expected_sha256": state_sha,
                    "expected_http_status": None,
                    "status_path": ["pipeline", "status"],
                    "terminal_values": ["complete", "failed"],
                    "timeout_seconds": None,
                }
            ),
        )
        output = self.root / "receipt/monitor.json"
        first = build_monitor_receipt(
            spec_path=spec,
            output_path=output,
            observed_at_utc="2026-07-16T12:00:00Z",
            monitor_root=self.root,
        )
        second = build_monitor_receipt(
            spec_path=spec,
            output_path=output,
            observed_at_utc="2026-07-16T12:00:00Z",
            monitor_root=self.root,
        )

        self.assertEqual(first["status"], "passed")
        self.assertEqual(first["write_status"], "created")
        self.assertEqual(second["write_status"], "no_change")
        self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
        receipt = json.loads(output.read_text(encoding="utf-8"))
        self.assertTrue(receipt["terminal"])
        self.assertTrue(receipt["quiescent"])
        self.assertNotIn("pipeline", receipt["first_observation"][0])
        self.assertNotIn("body", receipt["first_observation"][0])
        self.assertFalse(receipt["boundaries"]["deploy"])
        self.assertFalse(receipt["boundaries"]["remote_write"])
        self.assertFalse(receipt["boundaries"]["schedule_change"])

    def test_nonterminal_or_changed_state_blocks_without_side_effect_claim(self) -> None:
        state = self.root / "state.json"
        _write(state, {"status": "running"})
        spec = self.root / "spec.json"
        _write(
            spec,
            _spec(
                {
                    "id": "pipeline",
                    "kind": "file",
                    "target": str(state),
                    "expected_sha256": None,
                    "expected_http_status": None,
                    "status_path": ["status"],
                    "terminal_values": ["complete"],
                    "timeout_seconds": None,
                }
            ),
        )
        output = self.root / "blocked.json"
        result = build_monitor_receipt(
            spec_path=spec,
            output_path=output,
            observed_at_utc="2026-07-16T12:00:00Z",
            monitor_root=self.root,
        )
        receipt = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "blocked")
        self.assertIn("nonterminal_status", receipt["reason_codes"])
        self.assertFalse(receipt["terminal"])

    def test_terminal_marker_short_circuits_before_auxiliary_probe(self) -> None:
        marker = self.root / "terminal-marker.json"
        auxiliary = self.root / "auxiliary.json"
        _write(marker, {"status": "running"})
        _write(auxiliary, {"status": "complete"})
        marker_probe = {
            "id": "terminal-marker",
            "kind": "file",
            "target": str(marker),
            "expected_sha256": None,
            "expected_http_status": None,
            "status_path": ["status"],
            "terminal_values": ["complete"],
            "timeout_seconds": None,
        }
        auxiliary_probe = {**marker_probe, "id": "auxiliary", "target": str(auxiliary)}
        spec = self.root / "terminal-marker-spec.json"
        _write(spec, _spec_v2(marker_probe, [auxiliary_probe]))
        observed: list[str] = []
        original = monitor._observe

        def observe(probe, **kwargs):
            observed.append(str(probe["id"]))
            return original(probe, **kwargs)

        with mock.patch.object(monitor, "_observe", side_effect=observe):
            result = build_monitor_receipt(
                spec_path=spec,
                output_path=self.root / "terminal-marker-receipt.json",
                observed_at_utc="2026-07-18T00:00:00Z",
                monitor_root=self.root,
            )
        receipt = json.loads((self.root / "terminal-marker-receipt.json").read_text())
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(observed, ["terminal-marker"])
        self.assertTrue(receipt["terminal_marker"]["priority_short_circuit"])
        self.assertEqual(receipt["first_observation"], [])

    def test_terminal_marker_requires_two_point_quiescence_after_priority_check(self) -> None:
        marker = self.root / "terminal-marker.json"
        auxiliary = self.root / "auxiliary.json"
        _write(marker, {"status": "complete"})
        _write(auxiliary, {"status": "complete", "revision": 1})
        marker_probe = {
            "id": "terminal-marker",
            "kind": "file",
            "target": str(marker),
            "expected_sha256": None,
            "expected_http_status": None,
            "status_path": ["status"],
            "terminal_values": ["complete"],
            "timeout_seconds": None,
        }
        auxiliary_probe = {**marker_probe, "id": "auxiliary", "target": str(auxiliary)}
        spec = self.root / "terminal-marker-quiescence-spec.json"
        _write(spec, _spec_v2(marker_probe, [auxiliary_probe], interval=1))

        def mutate_auxiliary(_seconds: float) -> None:
            _write(auxiliary, {"status": "complete", "revision": 2})

        result = build_monitor_receipt(
            spec_path=spec,
            output_path=self.root / "terminal-marker-quiescence-receipt.json",
            observed_at_utc="2026-07-18T00:00:00Z",
            monitor_root=self.root,
            sleep_fn=mutate_auxiliary,
        )
        receipt = json.loads(
            (self.root / "terminal-marker-quiescence-receipt.json").read_text()
        )
        self.assertEqual(result["status"], "blocked")
        self.assertFalse(receipt["quiescent"])
        self.assertIn("observations_changed", receipt["reason_codes"])
        self.assertFalse(receipt["terminal_marker"]["priority_short_circuit"])

    def test_parameterized_http_get_is_read_only_and_hash_checked(self) -> None:
        payload = b'{"status":"idle"}\n'
        requests = []

        def opener(request, *, timeout):
            requests.append((request, timeout))
            return _Response(payload)

        spec = self.root / "http-spec.json"
        _write(
            spec,
            _spec(
                {
                    "id": "health",
                    "kind": "http",
                    "target": "http://127.0.0.1:18339/healthz",
                    "expected_sha256": sha256(payload).hexdigest(),
                    "expected_http_status": 200,
                    "status_path": ["status"],
                    "terminal_values": ["idle"],
                    "timeout_seconds": 2,
                }
            ),
        )
        result = build_monitor_receipt(
            spec_path=spec,
            output_path=self.root / "http-receipt.json",
            observed_at_utc="2026-07-16T12:00:00Z",
            urlopen_fn=opener,
            monitor_root=self.root,
        )
        self.assertEqual(result["status"], "passed")
        self.assertEqual(len(requests), 2)
        self.assertTrue(all(request.get_method() == "GET" for request, _ in requests))
        self.assertEqual([timeout for _, timeout in requests], [2, 2])

    def test_file_target_outside_monitor_root_fails_closed(self) -> None:
        outside = self.root.parent / "outside-monitor-state.json"
        _write(outside, {"status": "complete"})
        spec = self.root / "outside-spec.json"
        _write(spec, _spec({
            "id": "outside",
            "kind": "file",
            "target": str(outside),
            "expected_sha256": None,
            "expected_http_status": None,
            "status_path": ["status"],
            "terminal_values": ["complete"],
            "timeout_seconds": None,
        }))
        with self.assertRaisesRegex(ValueError, "monitor_file_target_outside_root"):
            build_monitor_receipt(
                spec_path=spec,
                output_path=self.root / "outside-receipt.json",
                observed_at_utc="2026-07-16T12:00:00Z",
                monitor_root=self.root,
            )

    def test_metadata_and_private_http_targets_fail_before_network(self) -> None:
        for target in (
            "http://169.254.169.254/latest/meta-data",
            "http://10.0.0.1/healthz",
        ):
            with self.subTest(target=target):
                spec = self.root / f"blocked-{sha256(target.encode()).hexdigest()}.json"
                _write(spec, _spec({
                    "id": "blocked",
                    "kind": "http",
                    "target": target,
                    "expected_sha256": None,
                    "expected_http_status": 200,
                    "status_path": ["status"],
                    "terminal_values": ["idle"],
                    "timeout_seconds": 2,
                }))
                with self.assertRaisesRegex(ValueError, "monitor_http_target_not_allowed"):
                    build_monitor_receipt(
                        spec_path=spec,
                        output_path=self.root / "blocked-receipt.json",
                        observed_at_utc="2026-07-16T12:00:00Z",
                        monitor_root=self.root,
                        urlopen_fn=lambda *_args, **_kwargs: self.fail("network called"),
                    )

    def test_redirect_response_is_blocked(self) -> None:
        payload = b'{"status":"idle"}\n'
        spec = self.root / "redirect-spec.json"
        _write(spec, _spec({
            "id": "redirect",
            "kind": "http",
            "target": "http://127.0.0.1:18339/healthz",
            "expected_sha256": sha256(payload).hexdigest(),
            "expected_http_status": 200,
            "status_path": ["status"],
            "terminal_values": ["idle"],
            "timeout_seconds": 2,
        }))
        result = build_monitor_receipt(
            spec_path=spec,
            output_path=self.root / "redirect-receipt.json",
            observed_at_utc="2026-07-16T12:00:00Z",
            monitor_root=self.root,
            urlopen_fn=lambda *_args, **_kwargs: _Response(
                payload, url="http://127.0.0.1:18339/redirected"
            ),
        )
        self.assertEqual(result["status"], "blocked")
        receipt = json.loads((self.root / "redirect-receipt.json").read_text())
        self.assertIn("monitor_http_redirect_forbidden", receipt["reason_codes"])

    def test_allowlisted_hostname_resolving_private_is_rejected(self) -> None:
        spec = self.root / "private-dns-spec.json"
        _write(spec, _spec({
            "id": "private-dns",
            "kind": "http",
            "target": "https://monitor.example.test/healthz",
            "expected_sha256": None,
            "expected_http_status": 200,
            "status_path": ["status"],
            "terminal_values": ["idle"],
            "timeout_seconds": 2,
        }))
        with self.assertRaisesRegex(ValueError, "monitor_http_target_not_public"):
            build_monitor_receipt(
                spec_path=spec,
                output_path=self.root / "private-dns-receipt.json",
                observed_at_utc="2026-07-16T12:00:00Z",
                monitor_root=self.root,
                public_http_allowlist=("monitor.example.test",),
                resolver=lambda *_args, **_kwargs: [
                    (2, 1, 6, "", ("10.20.30.40", 443))
                ],
                urlopen_fn=lambda *_args, **_kwargs: self.fail("network called"),
            )


if __name__ == "__main__":
    unittest.main()
