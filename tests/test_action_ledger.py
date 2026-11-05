"""Action ledger + card action handler tests (Wave 1 T5b/T8).

The ledger is the local source of truth for P0 actions (the PMO endpoint is
an unauthenticated counter — plan §0 C3), so its state machine, idempotency,
and PMO field mapping are contract-tested here. The card handler's Stage 2
guarantees (verification token fail-closed, operator allowlist, idempotent
claims, 200-with-toast rejection contract) are pinned at the function level.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from reddit_voc import action_ledger
from reddit_voc.card_action import (
    CardActionError,
    handle_card_action,
    verify_callback,
)


class LedgerTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        os.environ["ECHO_ACTION_LEDGER_DIR"] = self._tmp.name
        action_ledger._load_all.__wrapped__ if hasattr(action_ledger._load_all, "__wrapped__") else None

    def tearDown(self) -> None:
        os.environ.pop("ECHO_ACTION_LEDGER_DIR", None)
        self._tmp.cleanup()


class LedgerStateMachineTests(LedgerTestBase):
    def test_claim_creates_record_with_id(self) -> None:
        record = action_ledger.claim("evt-1", "claim:top_pain", "ou_123", {"run_id": "r1"})
        self.assertEqual(record["status"], "claimed")
        self.assertTrue(record["action_id"].startswith("act-"))
        self.assertEqual(record["context"]["run_id"], "r1")

    def test_claim_is_idempotent_on_event_and_value(self) -> None:
        first = action_ledger.claim("evt-1", "claim:top_pain", "ou_1")
        replay = action_ledger.claim("evt-1", "claim:top_pain", "ou_1")
        self.assertEqual(first["action_id"], replay["action_id"])
        # A different event still creates a new action.
        second = action_ledger.claim("evt-2", "claim:top_pain", "ou_1")
        self.assertNotEqual(first["action_id"], second["action_id"])

    def test_claimed_to_done_to_verified(self) -> None:
        record = action_ledger.claim("evt-1", "claim:top_pain", "ou_1")
        action_ledger.advance(record["action_id"], "done", "整改提交")
        final = action_ledger.advance(record["action_id"], "verified", "效果确认")
        self.assertEqual(final["status"], "verified")
        self.assertEqual(action_ledger.get(record["action_id"])["status"], "verified")

    def test_illegal_transitions_rejected(self) -> None:
        record = action_ledger.claim("evt-1", "claim:top_pain", "ou_1")
        with self.assertRaises(action_ledger.ActionLedgerError):
            action_ledger.advance(record["action_id"], "verified")  # claimed skips done
        action_ledger.advance(record["action_id"], "done")
        action_ledger.advance(record["action_id"], "verified")
        with self.assertRaises(action_ledger.ActionLedgerError):
            action_ledger.advance(record["action_id"], "done")  # terminal is terminal

    def test_list_filters_by_status(self) -> None:
        a = action_ledger.claim("evt-1", "claim:top_pain", "ou_1")
        b = action_ledger.claim("evt-2", "claim:leakage", "ou_2")
        action_ledger.advance(a["action_id"], "done")
        claimed = [x["action_id"] for x in action_ledger.list_actions("claimed")]
        done = [x["action_id"] for x in action_ledger.list_actions("done")]
        self.assertIn(b["action_id"], claimed)
        self.assertNotIn(a["action_id"], claimed)
        self.assertIn(a["action_id"], done)

    def test_pmo_mapping_truncates_and_uses_local_receipt_ref(self) -> None:
        record = action_ledger.claim("evt-1", "claim:top_pain", "ou_1", {
            "action_type": "pain_claim",
            "action_title": "认领晨报 Top 痛点并跟进整改",
        })
        payload = action_ledger.to_pmo_measured_action(record)
        self.assertEqual(payload["project_slug"], "echo")
        self.assertEqual(payload["receipt_ref"], record["action_id"])
        for field, limit in action_ledger.PMO_FIELD_LIMITS.items():
            self.assertLessEqual(len(payload[field]), limit, field)


class CardActionHandlerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        os.environ["ECHO_ACTION_LEDGER_DIR"] = self._tmp.name
        os.environ["FEISHU_VERIFICATION_TOKEN"] = "tok-test"

    def tearDown(self) -> None:
        for key in ("ECHO_ACTION_LEDGER_DIR", "FEISHU_VERIFICATION_TOKEN", "ECHO_CARD_OPERATOR_ALLOWLIST"):
            os.environ.pop(key, None)
        self._tmp.cleanup()

    def _body(self, value: str = "claim:top_pain", operator: str = "ou_1", event_id: str = "evt-1") -> dict:
        return {
            "header": {"event_type": "card.action.trigger", "token": "tok-test", "event_id": event_id},
            "event": {
                "operator": {"open_id": operator},
                "action": {"tag": "button", "value": {"value": value}},
            },
        }

    def test_verification_fails_closed_without_config(self) -> None:
        os.environ.pop("FEISHU_VERIFICATION_TOKEN", None)
        with self.assertRaises(CardActionError):
            verify_callback({}, {"header": {"token": "anything"}})

    def test_wrong_token_rejected(self) -> None:
        with self.assertRaises(CardActionError):
            verify_callback({}, self._body(token_override=True) if False else {
                "header": {"event_type": "card.action.trigger", "token": "wrong", "event_id": "e"}
            })

    def test_claim_happy_path_returns_success_toast(self) -> None:
        response = handle_card_action({}, self._body())
        self.assertEqual(response["toast"]["type"], "success")
        self.assertIn("act-", response["toast"]["content"])

    def test_replayed_event_does_not_double_claim(self) -> None:
        first = handle_card_action({}, self._body())
        replay = handle_card_action({}, self._body())
        self.assertEqual(first["toast"]["content"], replay["toast"]["content"])
        self.assertEqual(len(action_ledger.list_actions()), 1)

    def test_operator_allowlist_blocks_stranger(self) -> None:
        os.environ["ECHO_CARD_OPERATOR_ALLOWLIST"] = "ou_boss"
        with self.assertRaises(CardActionError):
            handle_card_action({}, self._body(operator="ou_stranger"))

    def test_unknown_action_value_rejected(self) -> None:
        with self.assertRaises(CardActionError):
            handle_card_action({}, self._body(value="self_destruct:true"))

    def test_transition_flow_through_handler(self) -> None:
        claim_response = handle_card_action({}, self._body())
        action_id = claim_response["toast"]["content"].split("（")[1].split("）")[0]
        done = handle_card_action({}, self._body(value=f"done:{action_id}", event_id="evt-2"))
        self.assertIn("done", done["toast"]["content"])
        verified = handle_card_action({}, self._body(value=f"verify:{action_id}", event_id="evt-3"))
        self.assertIn("verified", verified["toast"]["content"])

    def test_non_button_rejected(self) -> None:
        body = self._body()
        body["event"]["action"]["tag"] = "select_static"
        with self.assertRaises(CardActionError):
            handle_card_action({}, body)


class MorningBriefV5TemplateTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[1]

    def test_v5_keeps_url_buttons_and_adds_actions(self) -> None:
        card = json.loads((self.ROOT / "tools/feishu-card/templates/morning-brief-v5.json").read_text(encoding="utf-8"))
        actions = card["elements"][15]["actions"]
        url_buttons = [b for b in actions if "url" in b]
        value_buttons = [b for b in actions if "value" in b]
        self.assertEqual(len(url_buttons), 3)  # v4's three url buttons preserved
        self.assertEqual(len(value_buttons), 2)  # claim + ask
        claim = next(b for b in value_buttons if b["value"]["value"].startswith("claim:"))
        self.assertEqual(claim["value"]["context"]["action_type"], "pain_claim")
        self.assertIn("{{run_id}}", claim["value"]["context"]["run_id"])

    def test_v5_builder_points_at_v5_template(self) -> None:
        source = (self.ROOT / "tools/feishu-card/builders/build_morning_brief_v5.py").read_text(encoding="utf-8")
        self.assertIn("morning-brief-v5.json", source)
        self.assertNotIn("morning-brief-v4.json", source)


if __name__ == "__main__":
    unittest.main()
