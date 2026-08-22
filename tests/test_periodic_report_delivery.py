from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from reddit_voc.daily_report_delivery import load_and_verify_delivery_ledger
from reddit_voc.dingtalk import DingTalkSendResult
from reddit_voc.periodic_report_bundle import PeriodicBundleError
from reddit_voc.periodic_report_delivery import exercise_periodic_shadow_delivery
from reddit_voc.report_contracts import sha256_hex


ROOT = Path(__file__).resolve().parents[1]
BUNDLE_ROOT = (
    ROOT
    / "output/reddit-voc-periodic-report-bundles/shadow-daily-v3-20260724-r2"
)
RELEASE_ID = "reddit_voc_release_20260723_daily_v3"
DESTINATION = sha256_hex(b"dingtalk-group-primary-v1")
MANIFEST_SHA = "658966e32a39fcff47b91f7ba0d64d7ac7f520b311e505aef3a57e113853d21b"
BUNDLE_ID = "periodic_93d555291be7aa1b71b5ccc965492a73"


class SyntheticTransport:
    transport_kind = "synthetic"

    def __init__(self, statuses: tuple[str, ...] = ("sent",)) -> None:
        self.statuses = statuses
        self.calls: list[bytes] = []

    def __call__(
        self,
        *,
        webhook_url,
        body_bytes,
        secret,
        timeout_seconds,
        request_start_sink,
    ):
        if request_start_sink is not None:
            raise AssertionError("synthetic transport received external sink")
        self.calls.append(body_bytes)
        status = self.statuses[min(len(self.calls) - 1, len(self.statuses) - 1)]
        if status == "raise":
            raise RuntimeError("synthetic_timeout")
        return DingTalkSendResult(
            status=status,
            http_status=200,
            response_hash="sha256:" + "c" * 64,
            response_text="fixture",
            live_send=False,
            external_attempt_made=False,
        )


class ExternalTransport:
    transport_kind = "external"

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, **kwargs):
        self.calls += 1
        raise AssertionError("external transport must remain unreachable")


class PeriodicReportDeliveryTests(unittest.TestCase):
    def head(self, url: str) -> dict[str, object]:
        for grain in ("daily", "weekly", "monthly"):
            if url.endswith(f"/{grain}/poster.png"):
                return {
                    "status": 200,
                    "content_length": (BUNDLE_ROOT / f"public/{grain}/poster.png").stat().st_size,
                }
        return {"status": 200, "content_length": None}

    def exercise(self, state_root: Path, transport, **overrides):
        values = {
            "bundle_root": BUNDLE_ROOT,
            "expected_release_id": RELEASE_ID,
            "expected_destination_fingerprint": DESTINATION,
            "expected_manifest_sha256": MANIFEST_SHA,
            "state_root": state_root,
            "authorization_id": "periodic-shadow:test",
            "authorize_shadow_delivery": True,
            "head_checker": self.head,
            "transport": transport,
        }
        values.update(overrides)
        return exercise_periodic_shadow_delivery(**values)

    def ledger(self, state_root: Path):
        return load_and_verify_delivery_ledger(
            state_root / "delivery" / BUNDLE_ID / "ledger.jsonl",
            run_id=BUNDLE_ID,
        )

    def test_without_shadow_authorization_makes_no_attempt_or_ledger(self) -> None:
        with TemporaryDirectory() as temporary:
            state = Path(temporary) / "state"
            transport = SyntheticTransport()
            result = self.exercise(
                state,
                transport,
                authorize_shadow_delivery=False,
            )
            self.assertEqual(result.status, "shadow_delivery_not_authorized")
            self.assertEqual(transport.calls, [])
            self.assertFalse(state.exists())

    def test_external_transport_is_rejected_before_head_or_ledger(self) -> None:
        with TemporaryDirectory() as temporary:
            state = Path(temporary) / "state"
            transport = ExternalTransport()
            result = self.exercise(state, transport)
            self.assertEqual(result.status, "external_transport_forbidden")
            self.assertEqual(transport.calls, 0)
            self.assertFalse(state.exists())

    def test_frozen_bytes_use_attempting_and_sent_hash_chain(self) -> None:
        with TemporaryDirectory() as temporary:
            state = Path(temporary) / "state"
            transport = SyntheticTransport()
            result = self.exercise(state, transport)
            self.assertEqual(result.status, "sent")
            self.assertEqual(result.sent_grains, ("daily", "weekly", "monthly"))
            self.assertFalse(result.live_send)
            expected = [
                (BUNDLE_ROOT / f"private/outbox/{grain}.json").read_bytes()
                for grain in ("daily", "weekly", "monthly")
            ]
            self.assertEqual(transport.calls, expected)
            ledger = self.ledger(state)
            self.assertEqual(
                [row["status"] for row in ledger],
                ["attempting", "sent"] * 3,
            )
            self.assertTrue(all(row["external_attempt_made"] is False for row in ledger))
            self.assertEqual(result.ledger_tip_after, ledger[-1]["entry_hash"])

    def test_replay_is_blocked_without_calling_transport(self) -> None:
        with TemporaryDirectory() as temporary:
            state = Path(temporary) / "state"
            self.exercise(state, SyntheticTransport())
            replay = SyntheticTransport()
            result = self.exercise(state, replay)
            self.assertEqual(result.status, "same_run_live_history")
            self.assertEqual(replay.calls, [])
            self.assertEqual(len(self.ledger(state)), 6)

    def test_unknown_state_blocks_automatic_retry(self) -> None:
        with TemporaryDirectory() as temporary:
            state = Path(temporary) / "state"
            first = SyntheticTransport(("raise",))
            result = self.exercise(state, first)
            self.assertEqual(result.status, "unknown_delivery_state")
            self.assertEqual(result.attempted_grains, ("daily",))
            self.assertEqual(
                [row["status"] for row in self.ledger(state)],
                ["attempting", "unknown_delivery_state"],
            )
            retry = SyntheticTransport()
            blocked = self.exercise(state, retry)
            self.assertEqual(blocked.status, "unknown_delivery_state")
            self.assertEqual(retry.calls, [])

    def test_explicit_resend_only_accepts_the_rejected_grain(self) -> None:
        with TemporaryDirectory() as temporary:
            state = Path(temporary) / "state"
            first = SyntheticTransport(("rejected", "sent", "sent"))
            result = self.exercise(state, first)
            self.assertEqual(result.status, "rejected")
            self.assertEqual(result.rejected_grains, ("daily",))
            resend = SyntheticTransport()
            result = self.exercise(
                state,
                resend,
                authorize_resend=True,
                resend_grains=("daily",),
            )
            self.assertEqual(result.status, "sent")
            self.assertEqual(result.sent_grains, ("daily",))
            self.assertEqual(len(resend.calls), 1)

    def test_manifest_identity_and_head_fail_before_ledger(self) -> None:
        with TemporaryDirectory() as temporary:
            state = Path(temporary) / "state"
            with self.assertRaisesRegex(
                PeriodicBundleError, "periodic_delivery_manifest_sha256_mismatch"
            ):
                self.exercise(
                    state,
                    SyntheticTransport(),
                    expected_manifest_sha256="0" * 64,
                )
            self.assertFalse(state.exists())

            def failed_head(url: str) -> dict[str, object]:
                return {"status": 404, "content_length": None}

            transport = SyntheticTransport()
            with self.assertRaisesRegex(PeriodicBundleError, "head_daily_poster_failed"):
                self.exercise(state, transport, head_checker=failed_head)
            self.assertEqual(transport.calls, [])
            self.assertFalse(state.exists())


if __name__ == "__main__":
    unittest.main()
