#!/usr/bin/env python3
"""Does the site a browser receives actually contain this morning's data?

Why this exists
---------------
On 2026-10-31 `data/reddit-voc` became a symlink whose target was not reachable
from the nginx container. Every `/data/` request returned 404, while
`curl https://report.luteos.com/` returned 200 — the SPA fallback. Nothing in
the tree contradicted that, and nothing alerted. It was found by hand.

Three independent questions must be answered from three different artifacts:

  1. Is the pointer fresh?             (pointer freshness vs the closed T-1 window)
  2. Does each dataset prove itself?   (build.json stamp vs manifest bytes vs binding)
  3. Does the run receipt agree?       (build-receipts/<run_id>.json vs the pointer)

None of them is allowed to answer for another. A pointer can be advanced while a
dataset is stale (the 10-29 mixed-generation incident); a dataset can be intact
while the pointer names an older run; a receipt can exist for a run whose bytes
were never published.

Exit codes: 0 fresh/partial, 2 breach (with --fail-on-breach), 1 cannot evaluate.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from observe_reddit_data_release import classify, expected_close  # noqa: E402

SCHEMA = "echo_agent_site_freshness_v1"
POINTER_SCHEMA = "reddit_voc_current_release_v2"
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
DEFAULT_SLO_MINUTES = 90
RUN_ID_SAFE = "abcdefghijklmnopqrstuvwxyz0123456789_-"

# States that mean "the site is not serving what it claims".
BREACH_STATES = frozenset({"stalled", "stale", "failed", "rollback"})
HEALTHY_STATES = frozenset({"fresh", "partial", "awaiting"})


class FreshnessError(RuntimeError):
    """The site cannot be evaluated at all (missing or malformed pointer)."""


def _utc_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_utc(value: Any, *, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise FreshnessError(f"pointer_freshness_invalid:{label}_missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FreshnessError(f"pointer_freshness_invalid:{label}_unparseable") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _sha256_file(path: Path) -> str | None:
    import hashlib

    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _relocate(manifest_path: str) -> Path:
    from release_paths import relocate_manifest_path

    return Path(str(relocate_manifest_path(manifest_path)))


def _latest_receipt(data_root: Path) -> dict | None:
    """The newest run receipt, by run id (which sorts by capture time).

    Not by mtime: a copied or restored tree resets mtimes, and picking a receipt
    by filesystem time is how a stale run gets certified as current.
    """
    receipts_dir = data_root / "build-receipts"
    if not receipts_dir.is_dir():
        return None
    candidates = sorted(
        (p for p in receipts_dir.glob("*.json") if p.is_file()),
        key=lambda p: p.stem,
    )
    if not candidates:
        return None
    return _load_json(candidates[-1])


def observe_site(
    public_root: Path,
    *,
    now_utc: datetime | None = None,
    slo_minutes: int = DEFAULT_SLO_MINUTES,
) -> dict[str, Any]:
    """Answer the three questions above and return one document.

    Deliberately does NOT use `observe_reddit_data_release.observe()`: that
    function resolves the data path through the symlink, so in the very failure
    mode this monitors it would read whatever the link happened to point at, or
    fail to read anything. Here the pointer itself is the subject.
    """
    public_root = Path(public_root)
    data_root = public_root / "data" / "reddit-voc"
    now = now_utc or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    failures: list[str] = []

    pointer_path = data_root / "current-release.json"
    pointer = _load_json(pointer_path)
    if pointer is None:
        raise FreshnessError("pointer_missing_or_unreadable")
    if pointer.get("schema_version") != POINTER_SCHEMA:
        raise FreshnessError(f"pointer_schema_invalid:{pointer.get('schema_version')!r}")

    freshness = pointer.get("freshness")
    if not isinstance(freshness, Mapping):
        raise FreshnessError("pointer_freshness_invalid:missing")
    try:
        data_as_of = _parse_utc(freshness.get("data_as_of_utc"), label="data_as_of_utc")
    except FreshnessError:
        raise
    freshness_status = str(freshness.get("status") or "")

    # --- question 2: does every dataset prove itself? -----------------------
    datasets = pointer.get("datasets") or {}
    if not isinstance(datasets, Mapping) or not datasets:
        raise FreshnessError("pointer_datasets_invalid")

    receipt = _latest_receipt(data_root)
    if receipt is None:
        failures.append("build_receipt_missing")
    receipt_run_id = str((receipt or {}).get("run_id") or "")

    dataset_report: dict[str, dict[str, Any]] = {}
    for key, binding in datasets.items():
        entry: dict[str, Any] = {"ok": True}
        if not isinstance(binding, Mapping):
            failures.append(f"dataset_binding_invalid:{key}")
            dataset_report[key] = {"ok": False, "reason": "binding_invalid"}
            continue

        try:
            manifest_rel = _relocate(str(binding.get("manifest_path") or ""))
        except Exception as exc:  # ReleasePathError and friends
            failures.append(f"dataset_binding_invalid:{key}")
            dataset_report[key] = {"ok": False, "reason": f"binding_invalid:{exc}"}
            continue

        manifest_abs = data_root / manifest_rel
        dataset_dir = manifest_abs.parent
        stamp_abs = dataset_dir / "build.json"

        actual = _sha256_file(manifest_abs)
        if actual is None:
            failures.append(f"release_manifest_sha_mismatch:{key}")
            entry.update(ok=False, reason="manifest_missing")
            dataset_report[key] = entry
            continue

        declared = str(binding.get("public_manifest_sha256") or "")
        if declared and declared != actual:
            failures.append(f"release_manifest_sha_mismatch:{key}")
            entry.update(ok=False, reason="binding_vs_manifest")

        stamp = _load_json(stamp_abs)
        if stamp is None:
            failures.append(f"build_stamp_missing:{key}")
            entry.update(ok=False, reason="stamp_missing")
        else:
            stamp_sha = str(stamp.get("manifest_sha256") or "")
            if stamp_sha != actual:
                failures.append(f"build_stamp_manifest_sha_mismatch:{key}")
                entry.update(ok=False, reason="stamp_vs_manifest")
            if str(stamp.get("dataset_version") or "") != str(
                binding.get("dataset_version") or ""
            ):
                failures.append(f"dataset_version_mismatch:{key}")
                entry.update(ok=False, reason="stamp_version")
            if receipt_run_id and str(stamp.get("run_id") or "") != receipt_run_id:
                failures.append(f"build_stamp_run_mismatch:{key}")
                entry.update(ok=False, reason="stamp_run")

        entry["manifest_sha256"] = actual
        entry["manifest_path"] = manifest_rel.as_posix()
        dataset_report[key] = entry

    # --- question 3: does the receipt agree with the pointer? ---------------
    if receipt is not None:
        if str(receipt.get("release_id") or "") != str(pointer.get("release_id") or ""):
            failures.append("receipt_release_mismatch")
        receipt_datasets = receipt.get("datasets") or {}
        for key, binding in datasets.items():
            declared = str((binding or {}).get("public_manifest_sha256") or "")
            seen = str((receipt_datasets.get(key) or {}).get("manifest_sha256") or "")
            if declared and seen and declared != seen:
                failures.append(f"receipt_manifest_sha_mismatch:{key}")

    # --- question 1: is the pointer fresh? ---------------------------------
    try:
        verdict = classify(
            observed=now,
            data_as_of=data_as_of,
            freshness_status=freshness_status,
            slo_minutes=slo_minutes,
            latest_attempt=None,
            latest_control=None,
            current_release_id=str(pointer.get("release_id") or ""),
        )
    except ValueError as exc:
        raise FreshnessError(f"pointer_freshness_invalid:{exc}") from exc

    state = verdict["state"]
    # Any dataset that cannot prove itself outranks a fresh pointer: the site is
    # being served from a run whose evidence does not check out.
    if failures and state in HEALTHY_STATES:
        state = "failed"

    return {
        "schema_version": SCHEMA,
        "evaluated_at_utc": _utc_z(now),
        "state": state,
        "release_id": str(pointer.get("release_id") or ""),
        "freshness_status": freshness_status,
        "data_as_of_utc": verdict["data_as_of_utc"],
        "expected_period_end_utc": verdict["expected_period_end_utc"],
        "deadline_utc": verdict["deadline_utc"],
        "lag_seconds": verdict["lag_seconds"],
        "slo_seconds": verdict["slo_seconds"],
        "slo_met": verdict["slo_met"],
        "run_id": receipt_run_id or None,
        "datasets": dataset_report,
        "failures": sorted(set(failures)),
        "healthy": state in HEALTHY_STATES and not failures,
    }


# --------------------------------------------------------------------- alerts


def build_alert_card(document: Mapping[str, Any], *, heartbeat: bool = False) -> dict:
    """The Feishu card for this state. Red when the site is not what it claims."""
    state = str(document.get("state") or "unknown")
    failures = list(document.get("failures") or [])
    healthy = state in HEALTHY_STATES and not failures

    template = "green" if healthy else "red"
    title = "站点新鲜度正常" if healthy else f"站点异常：{state}"

    lines = [
        f"**状态**：{state}",
        f"**发布**：{document.get('release_id') or '未知'}",
        f"**数据截至**：{document.get('data_as_of_utc') or '未知'}",
        f"**应达周期**：{document.get('expected_period_end_utc') or '未知'}",
        f"**滞后**：{int(document.get('lag_seconds') or 0) // 60} 分钟",
    ]
    if document.get("run_id"):
        lines.append(f"**run**：{document['run_id']}")
    if failures:
        lines.append("**失败项**：" + "、".join(failures[:8]))
    else:
        lines.append("**失败项**：无")

    footer = "🤖 心跳检查" if heartbeat else "🤖 Echo-Agent 站点新鲜度监控"
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": template,
        },
        "elements": [
            {"tag": "markdown", "content": "\n".join(lines)},
            {"tag": "hr"},
            {"tag": "note", "elements": [{"tag": "plain_text", "content": footer}]},
        ],
    }


def load_state(path: Path) -> dict:
    return _load_json(Path(path)) or {}


def save_state(path: Path, state: Mapping[str, Any]) -> None:
    """Write the dedup state atomically, 0600, outside the public tree."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(state, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with open(temporary, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def should_notify(
    document: Mapping[str, Any],
    state: Mapping[str, Any],
    *,
    now_utc: datetime,
    heartbeat: bool,
) -> tuple[bool, str]:
    """Send on state transition, or one heartbeat per Shanghai day.

    A monitor that alerts every run gets muted, and a muted monitor is the same
    as none. Repeated identical states stay quiet; a state that changes speaks
    immediately.
    """
    previous = str(state.get("last_state") or "")
    current = str(document.get("state") or "")

    if current != previous:
        return True, "state_changed"

    if heartbeat:
        today = now_utc.astimezone(SHANGHAI_TZ).date().isoformat()
        if str(state.get("last_heartbeat_date") or "") != today:
            return True, "heartbeat"

    return False, "unchanged"


def _send_card(card: Mapping[str, Any], chat_id: str) -> dict:
    from reddit_voc.feishu_bot import FeishuBotClient

    app_id = os.getenv("FEISHU_APP_ID", "").strip()
    app_secret = os.getenv("FEISHU_APP_SECRET", "").strip()
    if not app_id or not app_secret:
        return {"status": "skipped_no_credentials"}
    return FeishuBotClient(app_id=app_id, app_secret=app_secret).send_interactive_card(
        chat_id, dict(card)
    )


# ----------------------------------------------------------------------- main


def main() -> int:
    parser = argparse.ArgumentParser(description="Check the served site's freshness")
    parser.add_argument("--public-root", type=Path, default=Path("/opt/voc-report/html"))
    parser.add_argument("--state-path", type=Path,
                        default=Path("/opt/echo-agent-bot/state/site-freshness.json"))
    parser.add_argument("--slo-minutes", type=int, default=DEFAULT_SLO_MINUTES)
    parser.add_argument("--heartbeat", action="store_true", default=False,
                        help="send at most one green card per Shanghai day")
    parser.add_argument("--fail-on-breach", action="store_true", default=False)
    parser.add_argument("--no-notify", action="store_true", default=False)
    parser.add_argument("--now", type=str, default=None,
                        help="ISO timestamp, for reproducible runs")
    args = parser.parse_args()

    now = (
        datetime.fromisoformat(args.now.replace("Z", "+00:00"))
        if args.now
        else datetime.now(timezone.utc)
    )

    try:
        document = observe_site(args.public_root, now_utc=now, slo_minutes=args.slo_minutes)
    except FreshnessError as exc:
        # Cannot evaluate is its own outcome: 1, distinct from a breach.
        print(json.dumps({
            "schema_version": SCHEMA,
            "state": "unevaluable",
            "error": str(exc),
            "healthy": False,
        }, ensure_ascii=False, indent=2))
        return 1

    state = load_state(args.state_path)
    notify, reason = should_notify(document, state, now_utc=now, heartbeat=args.heartbeat)

    result: dict[str, Any] = {"notified": False}
    if notify and not args.no_notify:
        card = build_alert_card(document, heartbeat=(reason == "heartbeat"))
        try:
            result = {"notified": True, "reason": reason,
                      "response": _send_card(card, os.getenv(
                          "FEISHU_REPORT_CHAT_ID", "oc_919ce85a13f3e19f6ca6c99dfdc01512"))}
        except Exception as exc:  # noqa: BLE001 — monitoring must not crash on a card
            result = {"notified": False, "reason": reason, "error": str(exc)}

    state["last_state"] = document["state"]
    if notify:
        state["last_sent_at_utc"] = _utc_z(now)
        if reason == "heartbeat":
            state["last_heartbeat_date"] = now.astimezone(SHANGHAI_TZ).date().isoformat()
    state["last_evaluated_at_utc"] = _utc_z(now)
    save_state(args.state_path, state)

    print(json.dumps({**document, "notification": result}, ensure_ascii=False, indent=2))

    if document["healthy"]:
        return 0
    return 2 if args.fail_on_breach else 0


if __name__ == "__main__":
    raise SystemExit(main())
