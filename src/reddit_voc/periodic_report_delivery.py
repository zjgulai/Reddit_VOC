from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Callable, Mapping, Sequence
from urllib.parse import parse_qsl, urlsplit

from .daily_report_delivery import (
    DingTalkByteTransport,
    deliver_one_frozen_part,
    evaluate_duplicate_guard,
    load_and_verify_delivery_ledger,
)
from .periodic_report_bundle import (
    PERIODS,
    PeriodicBundleError,
    preflight_periodic_report_bundle,
    verify_periodic_report_bundle,
)
from .prepared_bundle import PreparedOutboxPart
from .report_contracts import sha256_hex


@dataclass(frozen=True)
class PeriodicShadowDeliverySummary:
    bundle_id: str
    attempted_grains: tuple[str, ...]
    sent_grains: tuple[str, ...]
    rejected_grains: tuple[str, ...]
    status: str
    ledger_tip_before: str | None
    ledger_tip_after: str | None
    external_attempt_made: bool
    live_send: bool

    def as_dict(self) -> Mapping[str, object]:
        return {
            "bundle_id": self.bundle_id,
            "attempted_grains": list(self.attempted_grains),
            "sent_grains": list(self.sent_grains),
            "rejected_grains": list(self.rejected_grains),
            "status": self.status,
            "ledger_tip_before": self.ledger_tip_before,
            "ledger_tip_after": self.ledger_tip_after,
            "external_attempt_made": self.external_attempt_made,
            "live_send": self.live_send,
        }


@dataclass(frozen=True)
class PeriodicLiveCanarySummary:
    bundle_id: str
    grain: str
    period_id: str
    status: str
    ledger_tip_before: str | None
    ledger_tip_after: str | None
    external_attempt_made: bool
    http_status: int | None
    response_hash: str | None
    live_send: bool

    def as_dict(self) -> Mapping[str, object]:
        return {
            "bundle_id": self.bundle_id,
            "grain": self.grain,
            "period_id": self.period_id,
            "status": self.status,
            "ledger_tip_before": self.ledger_tip_before,
            "ledger_tip_after": self.ledger_tip_after,
            "external_attempt_made": self.external_attempt_made,
            "http_status": self.http_status,
            "response_hash": self.response_hash,
            "live_send": self.live_send,
            "webhook_send": self.live_send,
        }


def exercise_periodic_shadow_delivery(
    *,
    bundle_root: Path,
    expected_release_id: str,
    expected_destination_fingerprint: str,
    expected_manifest_sha256: str,
    state_root: Path,
    authorization_id: str,
    authorize_shadow_delivery: bool,
    head_checker: Callable[[str], Mapping[str, object]],
    transport: DingTalkByteTransport,
    authorize_resend: bool = False,
    resend_grains: Sequence[str] = (),
) -> PeriodicShadowDeliverySummary:
    """Exercise frozen periodic bytes through the durable delivery state machine.

    This entry point is deliberately shadow-only. It rejects external transports,
    never loads a webhook or secret, and cannot produce live-send evidence.
    """

    bundle_root = Path(bundle_root)
    manifest = verify_periodic_report_bundle(
        bundle_root,
        expected_release_id=expected_release_id,
        expected_destination_fingerprint=expected_destination_fingerprint,
    )
    bundle_id = str(manifest["bundle_id"])
    manifest_sha = sha256_hex((bundle_root / "manifest.json").read_bytes())
    if manifest_sha != expected_manifest_sha256:
        raise PeriodicBundleError("periodic_delivery_manifest_sha256_mismatch")
    if not authorize_shadow_delivery:
        return _summary(bundle_id=bundle_id, status="shadow_delivery_not_authorized")
    if getattr(transport, "transport_kind", None) != "synthetic":
        return _summary(bundle_id=bundle_id, status="external_transport_forbidden")
    if not isinstance(authorization_id, str) or not authorization_id.startswith(
        "periodic-shadow:"
    ):
        raise PeriodicBundleError("periodic_shadow_authorization_id_invalid")

    preflight_periodic_report_bundle(
        bundle_root,
        expected_release_id=expected_release_id,
        expected_destination_fingerprint=expected_destination_fingerprint,
        head_checker=head_checker,
    )
    state_root = Path(state_root)
    _ensure_state_root(state_root)
    ledger_path = state_root / "delivery" / bundle_id / "ledger.jsonl"
    ledger_before = load_and_verify_delivery_ledger(ledger_path, run_id=bundle_id)
    outbox = manifest["outbox"]
    assert isinstance(outbox, Mapping)
    expected_outbox_sha = str(outbox["aggregate_sha256"])
    records = outbox["parts"]
    assert isinstance(records, list)
    record_by_grain = {
        str(record["grain"]): record
        for record in records
        if isinstance(record, Mapping)
    }
    index_by_grain = {grain: index for index, grain in enumerate(PERIODS, start=1)}
    if any(grain not in index_by_grain for grain in resend_grains) or len(
        set(resend_grains)
    ) != len(tuple(resend_grains)):
        raise PeriodicBundleError("periodic_resend_grains_invalid")
    requested_indexes = tuple(index_by_grain[grain] for grain in resend_grains)
    synthetic_records = [
        {"message_hash": "sha256:" + str(entry["part_sha256"])}
        for entry in ledger_before
        if entry.get("part_kind") == "report"
        and entry.get("status") == "sent"
        and entry.get("outbox_sha256") == expected_outbox_sha
    ]
    decision = evaluate_duplicate_guard(
        ledger_entries=ledger_before,
        db_records=(
            synthetic_records if authorize_resend or requested_indexes else ()
        ),
        expected_outbox_sha256=expected_outbox_sha,
        authorize_resend=authorize_resend,
        requested_part_indexes=requested_indexes,
    )
    if decision.blocked_reason is not None:
        return _summary(
            bundle_id=bundle_id,
            status=decision.blocked_reason,
            ledger_tip_before=_ledger_tip(ledger_before),
            ledger_tip_after=_ledger_tip(ledger_before),
        )
    selected = decision.sendable_part_indexes or tuple(range(1, len(PERIODS) + 1))
    part_by_index: dict[int, PreparedOutboxPart] = {}
    grain_by_index: dict[int, str] = {}
    for grain, index in index_by_grain.items():
        record = record_by_grain[grain]
        path = bundle_root / str(record["relative_path"])
        payload = path.read_bytes()
        part_by_index[index] = PreparedOutboxPart(
            index=index,
            total=len(PERIODS),
            path=path,
            body_bytes=payload,
            sha256=str(record["sha256"]),
            byte_count=int(record["bytes"]),
        )
        grain_by_index[index] = grain

    attempted: list[str] = []
    sent: list[str] = []
    rejected: list[str] = []
    terminal_status = "sent"
    for index in selected:
        grain = grain_by_index[index]
        outcome = deliver_one_frozen_part(
            ledger_path=ledger_path,
            run_id=bundle_id,
            artifact_version_id=bundle_id,
            bundle_sha256=manifest_sha,
            outbox_sha256=expected_outbox_sha,
            part_kind="report",
            part=part_by_index[index],
            authorization_id=authorization_id,
            attempt_id=None,
            webhook_url="https://periodic-shadow.invalid",
            webhook_secret=None,
            timeout_seconds=10,
            transport=transport,
        )
        if outcome["attempted"]:
            attempted.append(grain)
        status = str(outcome["status"])
        if status == "sent":
            sent.append(grain)
        elif status == "rejected":
            rejected.append(grain)
            terminal_status = "rejected"
        elif status == "local_pre_request_blocked":
            terminal_status = status
            break
        else:
            terminal_status = "unknown_delivery_state"
            break
    ledger_after = load_and_verify_delivery_ledger(ledger_path, run_id=bundle_id)
    return PeriodicShadowDeliverySummary(
        bundle_id=bundle_id,
        attempted_grains=tuple(attempted),
        sent_grains=tuple(sent),
        rejected_grains=tuple(rejected),
        status=terminal_status,
        ledger_tip_before=_ledger_tip(ledger_before),
        ledger_tip_after=_ledger_tip(ledger_after),
        external_attempt_made=False,
        live_send=False,
    )


def send_periodic_live_canary(
    *,
    bundle_root: Path,
    expected_release_id: str,
    expected_destination_fingerprint: str,
    expected_manifest_sha256: str,
    expected_outbox_sha256: str,
    expected_grain: str,
    expected_group_alias: str,
    required_keyword: str,
    state_root: Path,
    authorization: Mapping[str, object],
    authorize_live_send: bool,
    dingtalk_mode: str,
    enable_live_send: str,
    webhook_url: str,
    webhook_secret: str | None,
    timeout_seconds: int,
    head_checker: Callable[[str], Mapping[str, object]],
    transport: DingTalkByteTransport,
) -> PeriodicLiveCanarySummary:
    manifest = verify_periodic_report_bundle(
        bundle_root,
        expected_release_id=expected_release_id,
        expected_destination_fingerprint=expected_destination_fingerprint,
    )
    bundle_id = str(manifest["bundle_id"])
    manifest_sha = sha256_hex((Path(bundle_root) / "manifest.json").read_bytes())
    captures = manifest["captures"]
    outbox = manifest["outbox"]
    identity = manifest["identity"]
    assert isinstance(captures, list)
    assert isinstance(outbox, Mapping)
    assert isinstance(identity, Mapping)
    if expected_grain not in PERIODS:
        raise PeriodicBundleError("periodic_live_grain_invalid")
    capture = next(
        row for row in captures
        if isinstance(row, Mapping) and row.get("grain") == expected_grain
    )
    period_id = str(capture["period_id"])
    if manifest_sha != expected_manifest_sha256:
        raise PeriodicBundleError("periodic_live_manifest_sha256_mismatch")
    if outbox.get("aggregate_sha256") != expected_outbox_sha256:
        raise PeriodicBundleError("periodic_live_outbox_sha256_mismatch")
    if identity.get("required_keyword") != required_keyword or not required_keyword:
        raise PeriodicBundleError("periodic_live_required_keyword_mismatch")
    blocked = None
    if not authorize_live_send:
        blocked = "live_send_not_authorized"
    elif dingtalk_mode != "live":
        blocked = "dingtalk_mode_not_live"
    elif enable_live_send != "1":
        blocked = "dingtalk_live_send_not_enabled"
    elif getattr(transport, "transport_kind", None) != "external":
        blocked = "external_transport_required"
    if blocked is not None:
        return _live_summary(bundle_id, expected_grain, period_id, blocked)
    authorization_id = _validate_live_authorization(
        authorization,
        bundle_id=bundle_id,
        manifest_sha256=manifest_sha,
        outbox_sha256=expected_outbox_sha256,
        release_id=expected_release_id,
        destination_fingerprint=expected_destination_fingerprint,
        grain=expected_grain,
        period_id=period_id,
        group_alias=expected_group_alias,
        required_keyword=required_keyword,
    )
    _validate_live_webhook(webhook_url, expected_destination_fingerprint)
    preflight_periodic_report_bundle(
        bundle_root,
        expected_release_id=expected_release_id,
        expected_destination_fingerprint=expected_destination_fingerprint,
        head_checker=head_checker,
    )
    state_root = Path(state_root)
    _ensure_state_root(state_root)
    ledger_path = state_root / "delivery" / bundle_id / "ledger.jsonl"
    ledger_before = load_and_verify_delivery_ledger(ledger_path, run_id=bundle_id)
    decision = evaluate_duplicate_guard(
        ledger_entries=ledger_before,
        db_records=(),
        expected_outbox_sha256=expected_outbox_sha256,
        authorize_resend=False,
        requested_part_indexes=(),
    )
    if decision.blocked_reason is not None:
        return _live_summary(
            bundle_id,
            expected_grain,
            period_id,
            decision.blocked_reason,
            ledger_tip_before=_ledger_tip(ledger_before),
            ledger_tip_after=_ledger_tip(ledger_before),
        )
    records = outbox["parts"]
    assert isinstance(records, list)
    record = next(
        row for row in records
        if isinstance(row, Mapping) and row.get("grain") == expected_grain
    )
    payload_path = Path(bundle_root) / str(record["relative_path"])
    payload = payload_path.read_bytes()
    body = json.loads(payload.decode("utf-8"))
    markdown = body.get("markdown") if isinstance(body, Mapping) else None
    if not isinstance(markdown, Mapping) or required_keyword not in (
        str(markdown.get("title", "")) + "\n" + str(markdown.get("text", ""))
    ):
        raise PeriodicBundleError("periodic_live_keyword_missing_from_body")
    index = PERIODS.index(expected_grain) + 1
    part = PreparedOutboxPart(
        index=index,
        total=len(PERIODS),
        path=payload_path,
        body_bytes=payload,
        sha256=str(record["sha256"]),
        byte_count=int(record["bytes"]),
    )
    outcome = deliver_one_frozen_part(
        ledger_path=ledger_path,
        run_id=bundle_id,
        artifact_version_id=bundle_id,
        bundle_sha256=manifest_sha,
        outbox_sha256=expected_outbox_sha256,
        part_kind="report",
        part=part,
        authorization_id=authorization_id,
        attempt_id=None,
        webhook_url=webhook_url,
        webhook_secret=webhook_secret,
        timeout_seconds=timeout_seconds,
        transport=transport,
    )
    ledger_after = load_and_verify_delivery_ledger(ledger_path, run_id=bundle_id)
    terminal = next(
        (
            entry for entry in reversed(ledger_after)
            if entry.get("part_index") == index
            and entry.get("authorization_id") == authorization_id
            and entry.get("status") != "attempting"
        ),
        {},
    )
    status = str(outcome["status"])
    sent = status == "sent" and bool(outcome["external_attempt_made"])
    return PeriodicLiveCanarySummary(
        bundle_id=bundle_id,
        grain=expected_grain,
        period_id=period_id,
        status=status,
        ledger_tip_before=_ledger_tip(ledger_before),
        ledger_tip_after=_ledger_tip(ledger_after),
        external_attempt_made=bool(outcome["external_attempt_made"]),
        http_status=terminal.get("http_status") if isinstance(terminal, Mapping) else None,
        response_hash=terminal.get("response_hash") if isinstance(terminal, Mapping) else None,
        live_send=sent,
    )


def _validate_live_authorization(
    value: Mapping[str, object],
    **expected: object,
) -> str:
    keys = {
        "schema_version", "authorization_id", "bundle_id",
        "bundle_manifest_sha256", "outbox_sha256", "release_id",
        "destination_fingerprint", "grain", "period_id", "group_alias",
        "required_keyword", "max_parts", "user_authorized_canary",
        "schedule_enable", "authorized_at_utc", "expires_at_utc",
    }
    if not isinstance(value, Mapping) or set(value) != keys:
        raise PeriodicBundleError("periodic_live_authorization_invalid")
    authorization_id = value.get("authorization_id")
    if (
        value.get("schema_version") != "reddit-voc-periodic-live-canary-authorization-v1"
        or not isinstance(authorization_id, str)
        or re.fullmatch(r"periodic-live-canary:[A-Za-z0-9._:-]{1,96}", authorization_id) is None
        or value.get("bundle_id") != expected["bundle_id"]
        or value.get("bundle_manifest_sha256") != expected["manifest_sha256"]
        or value.get("outbox_sha256") != expected["outbox_sha256"]
        or any(value.get(key) != expected[key] for key in (
            "release_id", "destination_fingerprint", "grain", "period_id",
            "group_alias", "required_keyword",
        ))
        or value.get("max_parts") != 1
        or value.get("user_authorized_canary") is not True
        or value.get("schedule_enable") is not False
    ):
        raise PeriodicBundleError("periodic_live_authorization_invalid")
    try:
        authorized = datetime.fromisoformat(str(value["authorized_at_utc"]))
        expires = datetime.fromisoformat(str(value["expires_at_utc"]))
    except ValueError as exc:
        raise PeriodicBundleError("periodic_live_authorization_time_invalid") from exc
    now = datetime.now(timezone.utc)
    if authorized.tzinfo is None or expires.tzinfo is None or not authorized <= now < expires:
        raise PeriodicBundleError("periodic_live_authorization_expired")
    return authorization_id


def _validate_live_webhook(url: str, expected_fingerprint: str) -> None:
    parsed = urlsplit(url)
    query = parse_qsl(parsed.query, keep_blank_values=True)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "oapi.dingtalk.com"
        or parsed.port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path != "/robot/send"
        or parsed.fragment
        or len(query) != 1
        or query[0][0] != "access_token"
        or not query[0][1]
        or hashlib.sha256(url.encode("utf-8")).hexdigest() != expected_fingerprint
    ):
        raise PeriodicBundleError("periodic_live_webhook_invalid")


def _live_summary(
    bundle_id: str,
    grain: str,
    period_id: str,
    status: str,
    *,
    ledger_tip_before: str | None = None,
    ledger_tip_after: str | None = None,
) -> PeriodicLiveCanarySummary:
    return PeriodicLiveCanarySummary(
        bundle_id=bundle_id,
        grain=grain,
        period_id=period_id,
        status=status,
        ledger_tip_before=ledger_tip_before,
        ledger_tip_after=ledger_tip_after,
        external_attempt_made=False,
        http_status=None,
        response_hash=None,
        live_send=False,
    )


def _ensure_state_root(path: Path) -> None:
    if not path.exists():
        path.mkdir(parents=True, mode=0o700)
        path.chmod(0o700)
    metadata = path.lstat()
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise PeriodicBundleError("periodic_delivery_state_root_invalid")


def _ledger_tip(entries: Sequence[Mapping[str, object]]) -> str | None:
    return str(entries[-1]["entry_hash"]) if entries else None


def _summary(
    *,
    bundle_id: str,
    status: str,
    ledger_tip_before: str | None = None,
    ledger_tip_after: str | None = None,
) -> PeriodicShadowDeliverySummary:
    return PeriodicShadowDeliverySummary(
        bundle_id=bundle_id,
        attempted_grains=(),
        sent_grains=(),
        rejected_grains=(),
        status=status,
        ledger_tip_before=ledger_tip_before,
        ledger_tip_after=ledger_tip_after,
        external_attempt_made=False,
        live_send=False,
    )
