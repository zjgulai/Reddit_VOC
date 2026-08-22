from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from reddit_voc.dingtalk import DingTalkSendResult
from reddit_voc.periodic_report_bundle import build_periodic_report_bundle
from reddit_voc.periodic_report_delivery import send_periodic_live_canary
from reddit_voc.report_contracts import canonical_json_bytes, sha256_hex


class ExternalTransport:
    transport_kind = "external"

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, *, request_start_sink, **kwargs):
        request_start_sink()
        self.calls += 1
        return DingTalkSendResult(
            status="sent",
            http_status=200,
            response_hash="sha256:" + "1" * 64,
            response_text='{"errcode":0,"errmsg":"ok"}',
            live_send=True,
            external_attempt_made=True,
        )


class PeriodicLiveDeliveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.release_id = "reddit_voc_release_test"
        self.destination_url = "https://oapi.dingtalk.com/robot/send?access_token=test-token"
        self.destination = hashlib.sha256(self.destination_url.encode()).hexdigest()
        poster_root = self.root / "posters"
        poster_root.mkdir()
        captures = []
        for index, (grain, height) in enumerate(
            (("daily", 1800), ("weekly", 2000), ("monthly", 2200)), start=1
        ):
            path = poster_root / f"{grain}.png"
            payload = bytes([index]) * 100_001
            path.write_bytes(payload)
            captures.append({
                "period": grain,
                "label": grain,
                "file": path.name,
                "bytes": len(payload),
                "sha256": sha256_hex(payload),
                "width": 1440,
                "height": height,
                "period_id": f"{grain}:test",
                "release_id": self.release_id,
                "dataset_version": "dataset_test",
                "coverage_percent": 100,
                "data_as_of": "2026-08-01",
                "source_freshness_status": "complete",
            })
        poster_manifest = {
            "schema_version": "reddit_voc_periodic_report_poster_bundle_v1",
            "status": "passed_local_poster_capture",
            "captures": captures,
            "golden_evaluation": {
                "status": "passed_exact_pixel_baseline",
                "manual_visual_review_required": False,
            },
        }
        manifest_path = poster_root / "manifest.json"
        manifest_path.write_bytes(canonical_json_bytes(poster_manifest))
        self.bundle = self.root / "bundle"
        self.manifest_sha, self.manifest = build_periodic_report_bundle(
            poster_manifest_path=manifest_path,
            output_root=self.bundle,
            artifact_base_url="https://example.com/data",
            dashboard_base_url="https://example.com",
            destination_fingerprint=self.destination,
            expected_release_id=self.release_id,
            expected_dataset_version="dataset_test",
            required_keyword="LL",
        )
        self.outbox_sha = self.manifest["outbox"]["aggregate_sha256"]

    def tearDown(self) -> None:
        self.temp.cleanup()

    def authorization(self) -> dict[str, object]:
        now = datetime.now(timezone.utc)
        return {
            "schema_version": "reddit-voc-periodic-live-canary-authorization-v1",
            "authorization_id": "periodic-live-canary:test",
            "bundle_id": self.manifest["bundle_id"],
            "bundle_manifest_sha256": self.manifest_sha,
            "outbox_sha256": self.outbox_sha,
            "release_id": self.release_id,
            "destination_fingerprint": self.destination,
            "grain": "daily",
            "period_id": "daily:test",
            "group_alias": "HighValueAsset",
            "required_keyword": "LL",
            "max_parts": 1,
            "user_authorized_canary": True,
            "schedule_enable": False,
            "authorized_at_utc": (now - timedelta(minutes=1)).isoformat(),
            "expires_at_utc": (now + timedelta(minutes=10)).isoformat(),
        }

    def call(self, transport, **overrides):
        values = dict(
            bundle_root=self.bundle,
            expected_release_id=self.release_id,
            expected_destination_fingerprint=self.destination,
            expected_manifest_sha256=self.manifest_sha,
            expected_outbox_sha256=self.outbox_sha,
            expected_grain="daily",
            expected_group_alias="HighValueAsset",
            required_keyword="LL",
            state_root=self.root / "state",
            authorization=self.authorization(),
            authorize_live_send=True,
            dingtalk_mode="live",
            enable_live_send="1",
            webhook_url=self.destination_url,
            webhook_secret=None,
            timeout_seconds=10,
            head_checker=lambda url: {
                "status": 200,
                "content_length": next(
                    (row["poster"]["bytes"] for row in self.manifest["captures"] if row["poster"]["public_url"] == url),
                    None,
                ),
            },
            transport=transport,
        )
        values.update(overrides)
        return send_periodic_live_canary(**values)

    def test_dual_gate_blocks_before_external_attempt(self):
        transport = ExternalTransport()
        summary = self.call(transport, enable_live_send="0")
        self.assertEqual("dingtalk_live_send_not_enabled", summary.status)
        self.assertEqual(0, transport.calls)

    def test_one_canary_is_sent_and_duplicate_is_blocked(self):
        transport = ExternalTransport()
        first = self.call(transport)
        self.assertEqual("sent", first.status)
        self.assertTrue(first.live_send)
        self.assertEqual(200, first.http_status)
        second = self.call(transport)
        self.assertEqual("same_run_live_history", second.status)
        self.assertEqual(1, transport.calls)

    def test_destination_mismatch_blocks_before_external_attempt(self):
        transport = ExternalTransport()
        with self.assertRaisesRegex(ValueError, "periodic_live_webhook_invalid"):
            self.call(transport, webhook_url=self.destination_url + "x")
        self.assertEqual(0, transport.calls)


if __name__ == "__main__":
    unittest.main()
