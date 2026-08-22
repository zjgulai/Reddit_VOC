from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from base64 import b64encode
from dataclasses import dataclass
from typing import Callable, Mapping
from urllib.parse import quote, quote_plus, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .report_contracts import canonical_json_bytes


_DINGTALK_WEBHOOK_RE = re.compile(
    r"https://oapi\.dingtalk\.com/robot/send\?access_token=[A-Za-z0-9_-]{1,256}"
)


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


_DINGTALK_OPENER = build_opener(ProxyHandler({}), _NoRedirectHandler())


def urlopen(request: Request, timeout: int):
    """Open exactly one direct request without redirects or environment proxies."""

    return _DINGTALK_OPENER.open(request, timeout=timeout)


def validate_webhook_url(webhook_url: str) -> str:
    """Return the byte-canonical DingTalk robot webhook or fail closed."""

    if not isinstance(webhook_url, str) or not webhook_url or len(webhook_url) > 1024:
        raise ValueError("dingtalk_webhook_invalid")
    try:
        webhook_url.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError("dingtalk_webhook_invalid") from exc
    if (
        _DINGTALK_WEBHOOK_RE.fullmatch(webhook_url) is None
        or "\\" in webhook_url
        or any(ord(character) <= 0x20 or ord(character) == 0x7F for character in webhook_url)
    ):
        raise ValueError("dingtalk_webhook_invalid")
    try:
        parsed = urlsplit(webhook_url)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("dingtalk_webhook_invalid") from exc
    if (
        parsed.scheme != "https"
        or parsed.netloc != "oapi.dingtalk.com"
        or parsed.hostname != "oapi.dingtalk.com"
        or port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path != "/robot/send"
        or parsed.fragment
    ):
        raise ValueError("dingtalk_webhook_invalid")
    return webhook_url


@dataclass(frozen=True)
class DingTalkPayload:
    body: dict
    message_hash: str
    signed_url: str | None
    live_send: bool


@dataclass(frozen=True)
class DingTalkSendResult:
    status: str
    http_status: int | None
    response_hash: str
    response_text: str
    live_send: bool
    external_attempt_made: bool = False

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "http_status": self.http_status,
            "response_hash": self.response_hash,
            "response_text": self.response_text,
            "live_send": self.live_send,
            "external_attempt_made": self.external_attempt_made,
        }


class DingTalkTransportError(RuntimeError):
    def __init__(self, reason_code: str, *, external_attempt_made: bool) -> None:
        self.reason_code = reason_code
        self.external_attempt_made = external_attempt_made
        super().__init__(reason_code)


def sign_url(webhook_url: str, secret: str, timestamp_ms: int | None = None) -> str:
    webhook_url = validate_webhook_url(webhook_url)
    if not isinstance(secret, str) or not secret:
        raise ValueError("dingtalk_secret_invalid")
    timestamp = timestamp_ms or int(time.time() * 1000)
    message = f"{timestamp}\n{secret}".encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), message, digestmod=hashlib.sha256).digest()
    sign = quote_plus(b64encode(digest).decode("utf-8"))
    separator = "&" if "?" in webhook_url else "?"
    return f"{webhook_url}{separator}timestamp={timestamp}&sign={sign}"


def render_markdown_digest(
    *,
    title: str,
    summary_lines: list[str],
    artifact_paths: list[str],
    detail_lines: list[str] | None = None,
    artifact_base_url: str | None = None,
) -> str:
    lines = [f"# {title}", "", "## Summary"]
    lines.extend(f"- {line}" for line in summary_lines)
    if detail_lines:
        lines.extend(["", "## Details"])
        lines.extend(detail_lines)
    if artifact_paths:
        lines.extend(["", "## Artifacts"])
        lines.extend(f"- {_format_artifact_reference(path, artifact_base_url)}" for path in artifact_paths)
    return "\n".join(lines)


def render_run_digest(
    *,
    title: str,
    run_status: dict,
    artifact_paths: list[str],
    extra_summary_lines: list[str] | None = None,
    detail_lines: list[str] | None = None,
    artifact_base_url: str | None = None,
) -> str:
    counts = run_status.get("counts", {}) or {}
    coverage = run_status.get("coverage", {}) or {}
    summary_lines = [
        f"run_id={run_status.get('run_id')}",
        f"status={run_status.get('status')}",
        f"threads={counts.get('threads', 0)}",
        f"comments={counts.get('comments', 0)}",
        f"analysis={counts.get('analysis', 0)}",
        f"coverage={json.dumps(coverage, ensure_ascii=False, sort_keys=True)}",
        f"provider_call={str(bool(run_status.get('provider_call'))).lower()}",
        f"live_send={str(bool(run_status.get('live_send'))).lower()}",
    ]
    if extra_summary_lines:
        summary_lines.extend(extra_summary_lines)
    return render_markdown_digest(
        title=title,
        summary_lines=summary_lines,
        artifact_paths=artifact_paths,
        detail_lines=detail_lines,
        artifact_base_url=artifact_base_url,
    )


def _format_artifact_reference(path: str, artifact_base_url: str | None = None) -> str:
    if path.startswith("http://") or path.startswith("https://"):
        return f"[{_artifact_label(path)}]({path})"
    if artifact_base_url:
        base = artifact_base_url.rstrip("/")
        label = _artifact_label(path)
        return f"[{label}]({base}/{quote(label)})"
    return f"`{path}`"


def _artifact_label(path: str) -> str:
    return path.rstrip("/").rsplit("/", 1)[-1] or path


def build_payload(
    *,
    title: str,
    markdown: str,
    webhook_url: str | None = None,
    secret: str | None = None,
    live_send: bool = False,
) -> DingTalkPayload:
    body = {
        "msgtype": "markdown",
        "markdown": {
            "title": title,
            "text": markdown,
        },
    }
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")
    signed_url = None
    if webhook_url and secret:
        signed_url = sign_url(webhook_url, secret)
    return DingTalkPayload(
        body=body,
        message_hash="sha256:" + hashlib.sha256(encoded).hexdigest(),
        signed_url=signed_url,
        live_send=live_send,
    )


def with_required_keyword(*, title: str, markdown: str, required_keyword: str | None) -> tuple[str, str]:
    keyword = (required_keyword or "").strip()
    if not keyword:
        return title, markdown
    if keyword in title or keyword in markdown:
        return title, markdown
    return title, f"{markdown}\n\n<!-- {keyword} -->"


def canonical_dingtalk_body_bytes(body: Mapping[str, object]) -> bytes:
    if not isinstance(body, Mapping) or set(body) != {"msgtype", "markdown"}:
        raise ValueError("dingtalk_body_invalid")
    markdown = body.get("markdown")
    if body.get("msgtype") != "markdown" or not isinstance(markdown, Mapping):
        raise ValueError("dingtalk_body_invalid")
    if set(markdown) != {"title", "text"}:
        raise ValueError("dingtalk_body_invalid")
    if not isinstance(markdown.get("title"), str) or not isinstance(markdown.get("text"), str):
        raise ValueError("dingtalk_body_invalid")
    return canonical_json_bytes(body)


def send_payload_bytes(
    *,
    webhook_url: str,
    body_bytes: bytes,
    secret: str | None = None,
    timeout_seconds: int = 10,
    request_start_sink: Callable[[], None],
) -> DingTalkSendResult:
    external_attempt_made = False
    try:
        if not isinstance(body_bytes, bytes):
            raise ValueError("dingtalk_body_bytes_required")
        try:
            body = json.loads(body_bytes.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("dingtalk_body_invalid") from exc
        if not isinstance(body, Mapping):
            raise ValueError("dingtalk_body_invalid")
        if canonical_dingtalk_body_bytes(body) != body_bytes:
            raise ValueError("dingtalk_body_not_canonical")
        webhook_url = validate_webhook_url(webhook_url)
        if isinstance(timeout_seconds, bool) or not 1 <= timeout_seconds <= 60:
            raise ValueError("dingtalk_timeout_invalid")
        if not callable(request_start_sink):
            raise ValueError("request_start_sink_required")
        target_url = sign_url(webhook_url, secret) if secret else webhook_url
        request = Request(
            target_url,
            data=body_bytes,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
    except (TypeError, ValueError, OSError) as exc:
        reason = str(exc)
        if not re_reason_code(reason):
            reason = "dingtalk_local_pre_request_blocked"
        raise DingTalkTransportError(
            reason, external_attempt_made=False
        ) from exc

    try:
        request_start_sink()
    except Exception as exc:
        raise DingTalkTransportError(
            "dingtalk_attempt_reservation_failed",
            external_attempt_made=False,
        ) from exc
    external_attempt_made = True
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            response_bytes = response.read(1024 * 1024 + 1)
            http_status = getattr(response, "status", None)
    except Exception as exc:
        raise DingTalkTransportError(
            "dingtalk_transport_error",
            external_attempt_made=external_attempt_made,
        ) from exc
    if isinstance(http_status, bool) or http_status != 200:
        raise DingTalkTransportError(
            "dingtalk_http_status_invalid",
            external_attempt_made=True,
        )
    if not isinstance(response_bytes, bytes) or len(response_bytes) > 1024 * 1024:
        raise DingTalkTransportError(
            "dingtalk_response_invalid",
            external_attempt_made=True,
        )
    try:
        response_text = response_bytes.decode("utf-8")
        response_json = json.loads(response_text)
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise DingTalkTransportError(
            "dingtalk_response_invalid",
            external_attempt_made=True,
        ) from exc
    if not isinstance(response_json, Mapping) or "errcode" not in response_json:
        raise DingTalkTransportError(
            "dingtalk_response_invalid",
            external_attempt_made=True,
        )
    errcode = response_json.get("errcode")
    if isinstance(errcode, bool) or not isinstance(errcode, (int, float)):
        raise DingTalkTransportError(
            "dingtalk_response_invalid",
            external_attempt_made=True,
        )
    status = "sent" if errcode == 0 else "rejected"
    return DingTalkSendResult(
        status=status,
        http_status=int(http_status) if isinstance(http_status, int) else None,
        response_hash="sha256:" + hashlib.sha256(response_bytes).hexdigest(),
        response_text=response_text[:500],
        live_send=True,
        external_attempt_made=True,
    )


def re_reason_code(value: str) -> bool:
    if not value or not value[0].islower():
        return False
    return all(character.islower() or character.isdigit() or character == "_" for character in value)


send_payload_bytes.transport_kind = "external"  # type: ignore[attr-defined]


def send_payload(
    *,
    webhook_url: str,
    payload: DingTalkPayload,
    timeout_seconds: int = 10,
) -> DingTalkSendResult:
    webhook_url = validate_webhook_url(webhook_url)
    target_url = payload.signed_url or webhook_url
    if payload.signed_url is not None:
        signed = urlsplit(payload.signed_url)
        if (
            signed.scheme != "https"
            or signed.netloc != "oapi.dingtalk.com"
            or signed.path != "/robot/send"
            or signed.fragment
        ):
            raise ValueError("dingtalk_webhook_invalid")
    encoded = json.dumps(payload.body, ensure_ascii=False).encode("utf-8")
    request = Request(
        target_url,
        data=encoded,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urlopen(request, timeout=timeout_seconds) as response:
        response_bytes = response.read(1024 * 1024 + 1)
        if len(response_bytes) > 1024 * 1024:
            raise ValueError("dingtalk_response_invalid")
        response_body = response_bytes.decode("utf-8", errors="replace")
        http_status = getattr(response, "status", None)
    status = "sent"
    try:
        response_json = json.loads(response_body)
        if int(response_json.get("errcode", 0)) != 0:
            status = "rejected"
    except (TypeError, ValueError, json.JSONDecodeError):
        status = "sent" if http_status and 200 <= int(http_status) < 300 else "rejected"
    return DingTalkSendResult(
        status=status,
        http_status=http_status,
        response_hash="sha256:" + hashlib.sha256(response_body.encode("utf-8")).hexdigest(),
        response_text=response_body[:500],
        live_send=True,
        external_attempt_made=True,
    )
