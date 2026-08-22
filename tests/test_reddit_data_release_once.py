from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.run_reddit_data_release_once import run


ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "config/systemd/reddit-voc-data-shadow.service"
TIMER = ROOT / "config/systemd/reddit-voc-data-shadow.timer"


class RedditDataReleaseOnceTests(unittest.TestCase):
    def test_switch_without_explicit_authorization_fails_with_receipt(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt = root / "attempt.json"
            exit_code, payload, write_status = run(
                root=root,
                candidate_release_id="reddit_voc_release_fixture",
                expected_current_release_id=None,
                mode="switch",
                authorize_switch=False,
                attempt_receipt=receipt,
            )
            self.assertEqual(exit_code, 1)
            self.assertEqual(write_status, "created")
            self.assertEqual(payload["status"], "failed")
            self.assertEqual(payload["error_code"], "scheduled_switch_not_authorized")
            self.assertFalse(payload["boundaries"]["production_switch"])
            self.assertEqual(json.loads(receipt.read_text()), payload)

    def test_shadow_failure_never_claims_a_pointer_switch(self) -> None:
        with TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            receipt = workspace / "private/attempt.json"
            exit_code, payload, _ = run(
                root=workspace / "missing",
                candidate_release_id="reddit_voc_release_fixture",
                expected_current_release_id=None,
                mode="shadow",
                authorize_switch=False,
                attempt_receipt=receipt,
            )
            self.assertEqual(exit_code, 1)
            self.assertEqual(payload["status"], "failed")
            self.assertFalse(payload["boundaries"]["production_switch"])
            self.assertFalse(payload["boundaries"]["remote_write"])
            self.assertFalse(payload["boundaries"]["schedule_change"])

    def test_systemd_draft_is_shadow_only_and_networkless(self) -> None:
        service = SERVICE.read_text(encoding="utf-8")
        timer = TIMER.read_text(encoding="utf-8")
        self.assertIn("Type=oneshot", service)
        self.assertIn("--mode shadow", service)
        self.assertNotIn("--authorize-switch", service)
        self.assertIn("RestrictAddressFamilies=AF_UNIX", service)
        self.assertIn("ProtectSystem=strict", service)
        self.assertEqual(timer.count("OnCalendar="), 6)
        self.assertIn("08:25:00 Asia/Shanghai", timer)
        self.assertIn("Persistent=true", timer)


if __name__ == "__main__":
    unittest.main()
