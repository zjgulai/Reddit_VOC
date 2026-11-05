"""Feishu card.action.trigger handler — the Stage 2 hard-gate capability (T5b).

Feishu interactive cards deliver button clicks as a card.action.trigger event
to the webhook. This module processes them with the guarantees the plan
requires (§3 T5b):

* verification: the encrypted/callback contract is validated against the
  app's verification token (FEISHU_VERIFICATION_TOKEN) before any state
  changes; a bad token is rejected with a plain 200 + error body (Feishu
  retries on non-2xx, and a rejection storm would double-apply actions on
  misconfigured retries),
* idempotency: (event_id, action_value) is the ledger key — Feishu retries
  the same event verbatim, so replay updates nothing,
* operator allowlist: only operators whose open_id appears in
  ECHO_CARD_OPERATOR_ALLOWLIST (comma-separated) may claim; empty means
  allow-all during initial pilot, and the value must be set before the
  11-13 evidence package,
* no PII retention: open_id lives in the ledger line only as the operator
  reference; question/action text is stored verbatim (action values are
  template ids, not user free-text).

Response contract: Feishu card callbacks expect a JSON body; returning
{"toast": ...} surfaces feedback in the client without a new message.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Mapping

from reddit_voc.action_ledger import ActionLedgerError, advance, claim, get

logger = logging.getLogger("reddit_voc.card_action")


class CardActionError(RuntimeError):
    """Rejectable callback: wrong token, unknown action, illegal transition."""


def _verification_token() -> str:
    return os.getenv("FEISHU_VERIFICATION_TOKEN", "").strip()


def _operator_allowlist() -> set[str]:
    raw = os.getenv("ECHO_CARD_OPERATOR_ALLOWLIST", "").strip()
    return {part.strip() for part in raw.split(",") if part.strip()}


def verify_callback(headers: Mapping[str, str], body: Mapping[str, Any]) -> None:
    """Reject callbacks that do not carry the app's verification token.

    Feishu sends the token in the body for card callbacks (header.event.token
    or token at top level) — compare to the configured value. No token
    configured means fail-closed: the 11-13 gate needs this env set anyway.
    """
    expected = _verification_token()
    if not expected:
        raise CardActionError("verification_token_unconfigured")
    provided = (
        (body.get("header") or {}).get("token")
        or (body.get("event") or {}).get("token")
        or body.get("token")
        or ""
    )
    if provided != expected:
        raise CardActionError("verification_token_mismatch")


def _operator_allowed(open_id: str | None) -> bool:
    allowlist = _operator_allowlist()
    if not allowlist:
        return True  # pilot mode; must be set before 11-13 evidence
    return bool(open_id) and open_id in allowlist


def _extract_event(body: Mapping[str, Any]) -> dict[str, Any]:
    """Feishu v2 wraps in event; card callbacks may arrive flat."""
    event = body.get("event") or body
    action = (event.get("action") or {})
    value = action.get("value") or {}
    operator = ((event.get("operator") or {}) or {}).get("open_id") or event.get("open_id")
    event_id = (
        (body.get("header") or {}).get("event_id")
        or event.get("event_id")
        or ""
    )
    return {
        "event_id": event_id,
        "action_value": str(value.get("value") or value.get("action_value") or ""),
        "action_name": str(action.get("name") or value.get("name") or ""),
        "tag": str(action.get("tag") or "button"),
        "operator_open_id": operator,
        "context": value.get("context") if isinstance(value.get("context"), dict) else {},
    }


def handle_card_action(headers: Mapping[str, str], body: Mapping[str, Any]) -> dict[str, Any]:
    """Process one card.action.trigger callback and return the card response.

    Raises CardActionError for rejectable problems (the HTTP layer turns that
    into 200 + error toast, never a retry-inviting non-2xx).
    """
    verify_callback(headers, body)
    event = _extract_event(body)

    if event["tag"] != "button" or not event["action_value"]:
        raise CardActionError("unsupported_action")

    value = event["action_value"]
    if value.startswith("claim:"):
        return _handle_claim(event)
    if value.startswith("done:") or value.startswith("verify:"):
        return _handle_transition(event)
    raise CardActionError(f"unknown_action_value:{value[:40]}")


def _handle_claim(event: dict[str, Any]) -> dict[str, Any]:
    if not _operator_allowed(event["operator_open_id"]):
        raise CardActionError("operator_not_allowed")
    action_value = event["action_value"]
    # "claim:<topic-slug>" — the slug is the claim target (pain theme/SPU).
    target = action_value.split(":", 1)[1]
    action = claim(
        event_id=event["event_id"],
        action_value=action_value,
        operator_open_id=event["operator_open_id"],
        context={
            "action_type": "pain_claim",
            "action_title": f"认领痛点 {target}",
            "target": target,
            **(event["context"] or {}),
        },
    )
    logger.info("action claimed: %s by %s (event %s)", action["action_id"], event["operator_open_id"], event["event_id"])
    return {
        "toast": {"content": f"已认领（{action['action_id']}），任务进入 claimed 状态", "type": "success"},
    }


def _handle_transition(event: dict[str, Any]) -> dict[str, Any]:
    if not _operator_allowed(event["operator_open_id"]):
        raise CardActionError("operator_not_allowed")
    action_value = event["action_value"]
    kind, _, action_id = action_value.partition(":")
    if not action_id:
        raise CardActionError("missing_action_id")
    existing = get(action_id)
    if existing is None:
        raise CardActionError(f"unknown_action:{action_id}")
    new_status = "done" if kind == "done" else "verified"
    try:
        updated = advance(action_id, new_status)
    except ActionLedgerError as exc:
        raise CardActionError(str(exc)) from exc
    return {
        "toast": {"content": f"{action_id} → {updated['status']}", "type": "success"},
    }
