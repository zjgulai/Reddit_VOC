"""P0 action ledger — the local source of truth for claimed actions (T8).

The PMO measuredActions endpoint is an unauthenticated counter with no
idempotency and no status updates (verified 2026-11-05, plan §0 C3), so this
module owns the state machine locally:

    claimed → done → verified

and syncs only terminal states to PMO (disabled until the X2 contract adds
auth + idempotency; the sync stub documents the mapping).

Storage is append-only JSONL under outputs/action-ledger/, one line per
transition, so any tampering is visible in the history. Idempotency key is
(event_id, action_value): replaying the same card callback updates nothing.
"""
from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("reddit_voc.action_ledger")

VALID_TRANSITIONS = {
    "claimed": {"done"},
    "done": {"verified"},
    "verified": set(),
}
TERMINAL = "verified"

# PMO measuredActions field mapping (plan §2 X2 / backup.json business_actions).
# PMO accepts these fields, status forced to 已回写, no idempotency:
#   action_type(≤40) action_title(≤240) dept_actor(≤60) receipt_ref(≤60)
#   outcome_metric(≤160) project_slug expert_name
PMO_FIELD_LIMITS = {
    "action_type": 40,
    "action_title": 240,
    "dept_actor": 60,
    "receipt_ref": 60,
    "outcome_metric": 160,
}


def _ledger_dir() -> Path:
    d = Path(os.getenv("ECHO_ACTION_LEDGER_DIR", "outputs/action-ledger"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _today_path() -> Path:
    return _ledger_dir() / f"actions-{datetime.now(timezone.utc).strftime('%Y%m%d')}.jsonl"


def _load_all() -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for path in sorted(_ledger_dir().glob("actions-*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                entries.append(json.loads(line))
    return entries


class ActionLedgerError(RuntimeError):
    pass


def _pmo_slug(value: str, limit: int) -> str:
    return value[:limit]


def _append(entry: dict[str, Any]) -> None:
    with _today_path().open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def claim(
    event_id: str,
    action_value: str,
    operator_open_id: str | None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Claim an action from a card button click. Idempotent on (event_id, action_value).

    Returns the full action record. A replayed event returns the existing
    record unchanged (and does not append a second claim line).
    """
    for entry in _load_all():
        if entry.get("event_id") == event_id and entry.get("action_value") == action_value:
            if entry.get("type") == "claim":
                return entry
    record = {
        "type": "claim",
        "action_id": f"act-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:8]}",
        "event_id": event_id,
        "action_value": action_value,
        "operator_open_id": operator_open_id,
        "status": "claimed",
        "context": context or {},
        "claimed_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "updated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    _append(record)
    return record


def advance(action_id: str, new_status: str, note: str = "") -> dict[str, Any]:
    """Move an action along claimed → done → verified. Appends a transition."""
    if new_status not in VALID_TRANSITIONS:
        raise ActionLedgerError(f"unknown status: {new_status}")
    current = get(action_id)
    if current is None:
        raise ActionLedgerError(f"unknown action_id: {action_id}")
    if current["status"] == TERMINAL:
        raise ActionLedgerError(f"action {action_id} is already terminal")
    if new_status not in VALID_TRANSITIONS[current["status"]]:
        raise ActionLedgerError(
            f"illegal transition {current['status']} -> {new_status} for {action_id}"
        )
    transition = {
        "type": "transition",
        "action_id": action_id,
        "from_status": current["status"],
        "to_status": new_status,
        "note": note,
        "at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    _append(transition)
    return {**current, "status": new_status}


def get(action_id: str) -> dict[str, Any] | None:
    """Current state of one action (claim line + last transition wins)."""
    current = None
    status = None
    for entry in _load_all():
        if entry.get("action_id") != action_id:
            continue
        if entry.get("type") == "claim":
            current = entry
        elif entry.get("type") == "transition":
            status = entry["to_status"]
    if current is None:
        return None
    return {**current, "status": status or current["status"]}


def list_actions(status: str | None = None) -> list[dict[str, Any]]:
    actions = []
    seen: dict[str, dict[str, Any]] = {}
    for entry in _load_all():
        if entry.get("type") == "claim":
            seen[entry["action_id"]] = {**entry, "status": entry["status"]}
        elif entry.get("type") == "transition":
            if entry.get("action_id") in seen:
                seen[entry["action_id"]]["status"] = entry["to_status"]
    for action in seen.values():
        if status is None or action["status"] == status:
            actions.append(action)
    return sorted(actions, key=lambda a: a["claimed_at_utc"], reverse=True)


def to_pmo_measured_action(action: dict[str, Any]) -> dict[str, str]:
    """Map a local action to the PMO measuredActions payload (terminal sync only).

    receipt_ref is the local action_id so PMO rows stay traceable to the
    ledger without importing PMO's seed rows (plan §0 C3: never reference the
    2026-11-03 seed). Truncation follows PMO's field limits.
    """
    context = action.get("context") or {}
    return {
        "event_type": "measured_action",
        "project_slug": "echo",
        "expert_name": "Echo",
        "action_type": _pmo_slug(str(context.get("action_type", "pain_claim")), PMO_FIELD_LIMITS["action_type"]),
        "action_title": _pmo_slug(str(context.get("action_title", action.get("action_value", "")))[:240], PMO_FIELD_LIMITS["action_title"]),
        "dept_actor": _pmo_slug(str(context.get("dept_actor", "品牌市场部")), PMO_FIELD_LIMITS["dept_actor"]),
        "receipt_ref": _pmo_slug(action["action_id"], PMO_FIELD_LIMITS["receipt_ref"]),
        "outcome_metric": _pmo_slug(str(context.get("outcome_metric", "")), PMO_FIELD_LIMITS["outcome_metric"]),
    }
