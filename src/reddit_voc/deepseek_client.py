from __future__ import annotations

import hashlib
import json
import random
import time
from dataclasses import dataclass
from typing import Callable, Mapping, Protocol
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .report_contracts import (
    AttemptBudget,
    AttemptEvidence,
    MonotonicDeadline,
    Phase,
    ProviderAttemptLifecycleSink,
    TokenUsage,
    canonical_json_bytes,
)


DEEPSEEK_CHAT_COMPLETIONS_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-v4-flash"
USER_AGENT = "Reddit-VOC-Daily-Report/1"
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
_MAX_RETRIES = 2
_RETRYABLE_HTTP_STATUSES = frozenset({429, 500, 503})
_ZERO_USAGE = TokenUsage(0, 0, 0, 0, 0)


class HttpResponse(Protocol):
    status: int

    def read(self, size: int = -1) -> bytes: ...

    def close(self) -> None: ...


class HttpTransport(Protocol):
    def open(self, request: Request, *, timeout: float) -> HttpResponse: ...


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


class UrllibHttpTransport:
    def __init__(self) -> None:
        self._opener = build_opener(ProxyHandler({}), _NoRedirectHandler())

    def open(self, request: Request, *, timeout: float) -> HttpResponse:
        try:
            return self._opener.open(request, timeout=timeout)
        except HTTPError as response:
            return response


@dataclass(frozen=True)
class DeepSeekCompletion:
    request_id: str
    model: str
    system_fingerprint: str | None
    finish_reason: str
    content: str
    usage: TokenUsage
    attempts: tuple[AttemptEvidence, ...]


class DeepSeekClientError(RuntimeError):
    def __init__(
        self,
        reason_code: str,
        *,
        attempts: tuple[AttemptEvidence, ...] = (),
        response_id: str | None = None,
        actual_model: str | None = None,
        system_fingerprint: str | None = None,
        finish_reason: str | None = None,
        usage: TokenUsage = _ZERO_USAGE,
    ) -> None:
        self.reason_code = reason_code
        self.attempts = attempts
        self.response_id = response_id
        self.actual_model = actual_model
        self.system_fingerprint = system_fingerprint
        self.finish_reason = finish_reason
        self.usage = usage
        super().__init__(f"{reason_code}:<redacted>")

    def __repr__(self) -> str:
        return f"DeepSeekClientError(reason_code={self.reason_code!r}, detail=<redacted>)"


@dataclass(frozen=True)
class _ParsedEnvelope:
    request_id: str
    model: str
    system_fingerprint: str | None
    finish_reason: str
    content: object
    usage: TokenUsage


class _ResponseReadError(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


class _UsageError(ValueError):
    pass


class DeepSeekClient:
    def __init__(
        self,
        *,
        api_key: str,
        transport: HttpTransport | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        uniform: Callable[[float, float], float] = random.uniform,
        max_response_bytes: int = MAX_RESPONSE_BYTES,
        attempt_lifecycle_sink: ProviderAttemptLifecycleSink | None = None,
    ) -> None:
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("missing_deepseek_credential:<redacted>")
        if isinstance(max_response_bytes, bool) or not 1 <= max_response_bytes <= MAX_RESPONSE_BYTES:
            raise ValueError("max_response_bytes_out_of_range")
        self._credential = api_key
        self._transport = transport or UrllibHttpTransport()
        self._monotonic = monotonic
        self._sleep = sleep
        self._uniform = uniform
        self._max_response_bytes = max_response_bytes
        self._attempt_lifecycle_sink = attempt_lifecycle_sink

    def __repr__(self) -> str:
        return (
            "DeepSeekClient("
            f"url={DEEPSEEK_CHAT_COMPLETIONS_URL!r}, model={DEEPSEEK_MODEL!r}, "
            "credential=<redacted>)"
        )

    def complete_json(
        self,
        *,
        phase: Phase,
        system_prompt: str,
        user_payload: Mapping[str, object],
        deadline: MonotonicDeadline,
        attempt_budget: AttemptBudget,
    ) -> DeepSeekCompletion:
        if phase not in {"translation", "semantic_validation"}:
            raise ValueError("invalid_attempt_phase")
        if not isinstance(system_prompt, str) or not system_prompt.strip():
            raise ValueError("system_prompt_required")
        request_body = self._request_body(
            phase=phase,
            system_prompt=system_prompt,
            user_payload=user_payload,
        )
        request_data = canonical_json_bytes(request_body)
        request_payload_sha256 = hashlib.sha256(request_data).hexdigest()
        attempts: list[AttemptEvidence] = []
        billed_usage: list[TokenUsage] = []
        last_response_id: str | None = None
        last_model: str | None = None
        last_fingerprint: str | None = None
        last_finish_reason: str | None = None

        def record_terminal(evidence: AttemptEvidence) -> None:
            if self._attempt_lifecycle_sink is not None:
                self._attempt_lifecycle_sink.terminal(
                    sequence=evidence.sequence,
                    phase=evidence.phase,
                    request_payload_sha256=request_payload_sha256,
                    evidence=evidence,
                )
            attempts.append(evidence)

        def record_unknown(evidence: AttemptEvidence) -> None:
            if self._attempt_lifecycle_sink is not None:
                self._attempt_lifecycle_sink.unknown(
                    sequence=evidence.sequence,
                    phase=evidence.phase,
                    request_payload_sha256=request_payload_sha256,
                )
            attempts.append(evidence)

        for retry_index in range(_MAX_RETRIES + 1):
            if self._remaining(deadline) <= 0:
                raise self._error(
                    "deadline_exhausted",
                    attempts,
                    billed_usage,
                    last_response_id,
                    last_model,
                    last_fingerprint,
                    last_finish_reason,
                )
            request = Request(
                DEEPSEEK_CHAT_COMPLETIONS_URL,
                data=request_data,
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Accept": "application/json",
                    "User-Agent": USER_AGENT,
                    "Authorization": f"Bearer {self._credential}",
                },
                method="POST",
            )
            remaining = self._remaining(deadline)
            if remaining <= 0:
                raise self._error(
                    "deadline_exhausted",
                    attempts,
                    billed_usage,
                    last_response_id,
                    last_model,
                    last_fingerprint,
                    last_finish_reason,
                )
            timeout = min(120.0, remaining)
            try:
                sequence = attempt_budget.reserve(phase)
            except RuntimeError as exc:
                if str(exc) != "attempt_budget_exhausted":
                    raise
                raise self._error(
                    "attempt_budget_exhausted",
                    attempts,
                    billed_usage,
                    last_response_id,
                    last_model,
                    last_fingerprint,
                    last_finish_reason,
                ) from exc
            if self._attempt_lifecycle_sink is not None:
                self._attempt_lifecycle_sink.reserve(
                    sequence=sequence,
                    phase=phase,
                    request_payload_sha256=request_payload_sha256,
                )
            started_at = self._monotonic()
            if self._attempt_lifecycle_sink is not None:
                self._attempt_lifecycle_sink.start(
                    sequence=sequence,
                    phase=phase,
                    request_payload_sha256=request_payload_sha256,
                )
            try:
                response = self._transport.open(request, timeout=timeout)
            except (OSError, TimeoutError) as exc:
                record_unknown(
                    AttemptEvidence(
                        sequence=sequence,
                        phase=phase,
                        http_status=None,
                        outcome="unknown_external_state",
                        retryable=False,
                        duration_ms=self._duration_ms(started_at),
                        response_id=None,
                        actual_model=None,
                        system_fingerprint=None,
                        finish_reason=None,
                        usage=None,
                    )
                )
                raise self._error(
                    "provider_attempt_unknown",
                    attempts,
                    billed_usage,
                    last_response_id,
                    last_model,
                    last_fingerprint,
                    last_finish_reason,
                ) from exc

            status = _response_status(response)
            try:
                try:
                    raw_response = self._read_response(response, deadline=deadline)
                except _ResponseReadError as exc:
                    evidence = AttemptEvidence(
                        sequence=sequence,
                        phase=phase,
                        http_status=status,
                        outcome=(
                            "unknown_external_state"
                            if exc.reason_code == "deadline_exhausted"
                            else exc.reason_code
                        ),
                        retryable=False,
                        duration_ms=self._duration_ms(started_at),
                        response_id=None,
                        actual_model=None,
                        system_fingerprint=None,
                        finish_reason=None,
                        usage=None,
                    )
                    if exc.reason_code == "deadline_exhausted":
                        record_unknown(evidence)
                        reason_code = "provider_attempt_unknown"
                    else:
                        record_terminal(evidence)
                        reason_code = exc.reason_code
                    raise self._error(
                        reason_code,
                        attempts,
                        billed_usage,
                        last_response_id,
                        last_model,
                        last_fingerprint,
                        last_finish_reason,
                    ) from exc
                except (OSError, TimeoutError) as exc:
                    record_unknown(
                        AttemptEvidence(
                            sequence=sequence,
                            phase=phase,
                            http_status=status,
                            outcome="unknown_external_state",
                            retryable=False,
                            duration_ms=self._duration_ms(started_at),
                            response_id=None,
                            actual_model=None,
                            system_fingerprint=None,
                            finish_reason=None,
                            usage=None,
                        )
                    )
                    raise self._error(
                        "provider_attempt_unknown",
                        attempts,
                        billed_usage,
                        last_response_id,
                        last_model,
                        last_fingerprint,
                        last_finish_reason,
                    ) from exc

                if status != 200:
                    retryable = status in _RETRYABLE_HTTP_STATUSES
                    record_terminal(
                        AttemptEvidence(
                            sequence=sequence,
                            phase=phase,
                            http_status=status,
                            outcome=f"http_status_{status}",
                            retryable=retryable,
                            duration_ms=self._duration_ms(started_at),
                            response_id=None,
                            actual_model=None,
                            system_fingerprint=None,
                            finish_reason=None,
                            usage=None,
                        )
                    )
                    if retryable:
                        self._retry_or_raise(
                            retry_index=retry_index,
                            deadline=deadline,
                            attempts=attempts,
                            billed_usage=billed_usage,
                            metadata=(last_response_id, last_model, last_fingerprint, last_finish_reason),
                        )
                        continue
                    raise self._error(
                        "http_status_blocked",
                        attempts,
                        billed_usage,
                        last_response_id,
                        last_model,
                        last_fingerprint,
                        last_finish_reason,
                    )

                if not raw_response.strip():
                    record_terminal(
                        AttemptEvidence(
                            sequence=sequence,
                            phase=phase,
                            http_status=200,
                            outcome="empty_response",
                            retryable=True,
                            duration_ms=self._duration_ms(started_at),
                            response_id=None,
                            actual_model=None,
                            system_fingerprint=None,
                            finish_reason=None,
                            usage=None,
                        )
                    )
                    self._retry_or_raise(
                        retry_index=retry_index,
                        deadline=deadline,
                        attempts=attempts,
                        billed_usage=billed_usage,
                        metadata=(last_response_id, last_model, last_fingerprint, last_finish_reason),
                    )
                    continue

                try:
                    parsed = _parse_envelope(raw_response)
                except _UsageError as exc:
                    response_id, model, fingerprint, finish_reason = _best_effort_metadata(raw_response)
                    last_response_id = response_id
                    last_model = model
                    last_fingerprint = fingerprint
                    last_finish_reason = finish_reason
                    record_terminal(
                        AttemptEvidence(
                            sequence=sequence,
                            phase=phase,
                            http_status=200,
                            outcome="invalid_usage",
                            retryable=False,
                            duration_ms=self._duration_ms(started_at),
                            response_id=response_id,
                            actual_model=model,
                            system_fingerprint=fingerprint,
                            finish_reason=finish_reason,
                            usage=None,
                        )
                    )
                    raise self._error(
                        "invalid_usage",
                        attempts,
                        billed_usage,
                        last_response_id,
                        last_model,
                        last_fingerprint,
                        last_finish_reason,
                    ) from exc
                except ValueError as exc:
                    record_terminal(
                        AttemptEvidence(
                            sequence=sequence,
                            phase=phase,
                            http_status=200,
                            outcome="invalid_response_envelope",
                            retryable=False,
                            duration_ms=self._duration_ms(started_at),
                            response_id=None,
                            actual_model=None,
                            system_fingerprint=None,
                            finish_reason=None,
                            usage=None,
                        )
                    )
                    raise self._error(
                        "invalid_response_envelope",
                        attempts,
                        billed_usage,
                        last_response_id,
                        last_model,
                        last_fingerprint,
                        last_finish_reason,
                    ) from exc

                last_response_id = parsed.request_id
                last_model = parsed.model
                last_fingerprint = parsed.system_fingerprint
                last_finish_reason = parsed.finish_reason
                billed_usage.append(parsed.usage)

                if parsed.model != DEEPSEEK_MODEL:
                    record_terminal(
                        self._attempt(
                            sequence=sequence,
                            phase=phase,
                            status=200,
                            outcome="model_mismatch",
                            retryable=False,
                            started_at=started_at,
                            parsed=parsed,
                        )
                    )
                    raise self._error(
                        "model_mismatch",
                        attempts,
                        billed_usage,
                        last_response_id,
                        last_model,
                        last_fingerprint,
                        last_finish_reason,
                    )

                if parsed.finish_reason == "insufficient_system_resource":
                    record_terminal(
                        self._attempt(
                            sequence=sequence,
                            phase=phase,
                            status=200,
                            outcome="insufficient_system_resource",
                            retryable=True,
                            started_at=started_at,
                            parsed=parsed,
                        )
                    )
                    self._retry_or_raise(
                        retry_index=retry_index,
                        deadline=deadline,
                        attempts=attempts,
                        billed_usage=billed_usage,
                        metadata=(last_response_id, last_model, last_fingerprint, last_finish_reason),
                    )
                    continue

                if parsed.finish_reason != "stop":
                    reason = {
                        "length": "finish_reason_length",
                        "content_filter": "finish_reason_content_filter",
                        "tool_calls": "finish_reason_tool_calls",
                    }.get(parsed.finish_reason, "finish_reason_unknown")
                    record_terminal(
                        self._attempt(
                            sequence=sequence,
                            phase=phase,
                            status=200,
                            outcome=reason,
                            retryable=False,
                            started_at=started_at,
                            parsed=parsed,
                        )
                    )
                    raise self._error(
                        reason,
                        attempts,
                        billed_usage,
                        last_response_id,
                        last_model,
                        last_fingerprint,
                        last_finish_reason,
                    )

                if not isinstance(parsed.content, str) or not parsed.content.strip():
                    record_terminal(
                        self._attempt(
                            sequence=sequence,
                            phase=phase,
                            status=200,
                            outcome="empty_content",
                            retryable=False,
                            started_at=started_at,
                            parsed=parsed,
                        )
                    )
                    raise self._error(
                        "empty_content",
                        attempts,
                        billed_usage,
                        last_response_id,
                        last_model,
                        last_fingerprint,
                        last_finish_reason,
                    )
                try:
                    content_value = json.loads(parsed.content)
                except (TypeError, ValueError, json.JSONDecodeError) as exc:
                    record_terminal(
                        self._attempt(
                            sequence=sequence,
                            phase=phase,
                            status=200,
                            outcome="invalid_json_content",
                            retryable=True,
                            started_at=started_at,
                            parsed=parsed,
                        )
                    )
                    self._retry_or_raise(
                        retry_index=retry_index,
                        deadline=deadline,
                        attempts=attempts,
                        billed_usage=billed_usage,
                        metadata=(
                            last_response_id,
                            last_model,
                            last_fingerprint,
                            last_finish_reason,
                        ),
                        exhausted_reason_code="invalid_json_content",
                    )
                    continue
                if not isinstance(content_value, Mapping):
                    record_terminal(
                        self._attempt(
                            sequence=sequence,
                            phase=phase,
                            status=200,
                            outcome="json_content_not_object",
                            retryable=False,
                            started_at=started_at,
                            parsed=parsed,
                        )
                    )
                    raise self._error(
                        "json_content_not_object",
                        attempts,
                        billed_usage,
                        last_response_id,
                        last_model,
                        last_fingerprint,
                        last_finish_reason,
                    )

                record_terminal(
                    self._attempt(
                        sequence=sequence,
                        phase=phase,
                        status=200,
                        outcome="success",
                        retryable=False,
                        started_at=started_at,
                        parsed=parsed,
                    )
                )
                return DeepSeekCompletion(
                    request_id=parsed.request_id,
                    model=parsed.model,
                    system_fingerprint=parsed.system_fingerprint,
                    finish_reason=parsed.finish_reason,
                    content=parsed.content,
                    usage=_sum_usage(billed_usage),
                    attempts=tuple(attempts),
                )
            finally:
                try:
                    response.close()
                except (OSError, TimeoutError):
                    # Closing an already-consumed response must not erase the
                    # durable attempt/result evidence established above.
                    pass

        raise self._error(
            "retry_exhausted",
            attempts,
            billed_usage,
            last_response_id,
            last_model,
            last_fingerprint,
            last_finish_reason,
        )

    def _request_body(
        self,
        *,
        phase: Phase,
        system_prompt: str,
        user_payload: Mapping[str, object],
    ) -> Mapping[str, object]:
        return {
            "model": DEEPSEEK_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": canonical_json_bytes(user_payload).decode("utf-8")},
            ],
            "stream": False,
            "temperature": 0,
            "thinking": {"type": "disabled"},
            "response_format": {"type": "json_object"},
            "user_id": "reddit_voc_daily_translation",
            "max_tokens": 16384 if phase == "translation" else 4096,
        }

    def _read_response(self, response: HttpResponse, *, deadline: MonotonicDeadline) -> bytes:
        chunks: list[bytes] = []
        byte_count = 0
        while True:
            if self._remaining(deadline) <= 0:
                raise _ResponseReadError("deadline_exhausted")
            read_size = min(65536, self._max_response_bytes - byte_count + 1)
            chunk = response.read(read_size)
            if not isinstance(chunk, bytes):
                raise _ResponseReadError("invalid_response_bytes")
            if not chunk:
                break
            byte_count += len(chunk)
            if byte_count > self._max_response_bytes:
                raise _ResponseReadError("response_too_large")
            chunks.append(chunk)
            if self._remaining(deadline) <= 0:
                raise _ResponseReadError("deadline_exhausted")
        return b"".join(chunks)

    def _retry_or_raise(
        self,
        *,
        retry_index: int,
        deadline: MonotonicDeadline,
        attempts: list[AttemptEvidence],
        billed_usage: list[TokenUsage],
        metadata: tuple[str | None, str | None, str | None, str | None],
        exhausted_reason_code: str = "retry_exhausted",
    ) -> None:
        if retry_index >= _MAX_RETRIES:
            raise self._error(exhausted_reason_code, attempts, billed_usage, *metadata)
        wait_seconds = (2**retry_index) + self._uniform(0, 0.25)
        if self._remaining(deadline) <= wait_seconds:
            raise self._error("deadline_exhausted", attempts, billed_usage, *metadata)
        self._sleep(wait_seconds)
        if self._remaining(deadline) <= 0:
            raise self._error("deadline_exhausted", attempts, billed_usage, *metadata)

    def _remaining(self, deadline: MonotonicDeadline) -> float:
        return deadline.expires_at - self._monotonic()

    def _duration_ms(self, started_at: float) -> int:
        return max(0, int((self._monotonic() - started_at) * 1000))

    def _attempt(
        self,
        *,
        sequence: int,
        phase: Phase,
        status: int,
        outcome: str,
        retryable: bool,
        started_at: float,
        parsed: _ParsedEnvelope,
    ) -> AttemptEvidence:
        return AttemptEvidence(
            sequence=sequence,
            phase=phase,
            http_status=status,
            outcome=outcome,
            retryable=retryable,
            duration_ms=self._duration_ms(started_at),
            response_id=parsed.request_id,
            actual_model=parsed.model,
            system_fingerprint=parsed.system_fingerprint,
            finish_reason=parsed.finish_reason,
            usage=parsed.usage,
        )

    @staticmethod
    def _error(
        reason_code: str,
        attempts: list[AttemptEvidence],
        billed_usage: list[TokenUsage],
        response_id: str | None,
        actual_model: str | None,
        system_fingerprint: str | None,
        finish_reason: str | None,
    ) -> DeepSeekClientError:
        return DeepSeekClientError(
            reason_code,
            attempts=tuple(attempts),
            response_id=response_id,
            actual_model=actual_model,
            system_fingerprint=system_fingerprint,
            finish_reason=finish_reason,
            usage=_sum_usage(billed_usage),
        )


def _response_status(response: HttpResponse) -> int:
    raw_status = getattr(response, "status", getattr(response, "code", None))
    if isinstance(raw_status, bool) or not isinstance(raw_status, int):
        return 0
    return raw_status


def _parse_envelope(raw: bytes) -> _ParsedEnvelope:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("invalid_response_envelope") from exc
    if not isinstance(value, Mapping):
        raise ValueError("invalid_response_envelope")
    request_id = value.get("id")
    model = value.get("model")
    fingerprint = value.get("system_fingerprint")
    choices = value.get("choices")
    if (
        not isinstance(request_id, str)
        or not request_id
        or not isinstance(model, str)
        or not model
        or (fingerprint is not None and not isinstance(fingerprint, str))
        or not isinstance(choices, list)
        or len(choices) != 1
        or not isinstance(choices[0], Mapping)
    ):
        raise ValueError("invalid_response_envelope")
    choice = choices[0]
    finish_reason = choice.get("finish_reason")
    message = choice.get("message")
    if not isinstance(finish_reason, str) or not isinstance(message, Mapping) or "content" not in message:
        raise ValueError("invalid_response_envelope")
    usage = _parse_usage(value.get("usage"))
    return _ParsedEnvelope(
        request_id=request_id,
        model=model,
        system_fingerprint=fingerprint,
        finish_reason=finish_reason,
        content=message.get("content"),
        usage=usage,
    )


def _parse_usage(value: object) -> TokenUsage:
    required = {
        "prompt_tokens",
        "completion_tokens",
        "prompt_cache_hit_tokens",
        "prompt_cache_miss_tokens",
        "total_tokens",
    }
    if not isinstance(value, Mapping) or not required.issubset(value):
        raise _UsageError("invalid_usage")
    values: dict[str, int] = {}
    for key in required:
        item = value.get(key)
        if isinstance(item, bool) or not isinstance(item, int) or item < 0:
            raise _UsageError("invalid_usage")
        values[key] = item
    if values["prompt_tokens"] != values["prompt_cache_hit_tokens"] + values["prompt_cache_miss_tokens"]:
        raise _UsageError("invalid_usage")
    if values["total_tokens"] != values["prompt_tokens"] + values["completion_tokens"]:
        raise _UsageError("invalid_usage")
    return TokenUsage(
        prompt_tokens=values["prompt_tokens"],
        completion_tokens=values["completion_tokens"],
        prompt_cache_hit_tokens=values["prompt_cache_hit_tokens"],
        prompt_cache_miss_tokens=values["prompt_cache_miss_tokens"],
        total_tokens=values["total_tokens"],
    )


def _best_effort_metadata(raw: bytes) -> tuple[str | None, str | None, str | None, str | None]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
        return None, None, None, None
    if not isinstance(value, Mapping):
        return None, None, None, None
    request_id = value.get("id") if isinstance(value.get("id"), str) else None
    model = value.get("model") if isinstance(value.get("model"), str) else None
    fingerprint = value.get("system_fingerprint") if isinstance(value.get("system_fingerprint"), str) else None
    finish_reason: str | None = None
    choices = value.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], Mapping):
        candidate = choices[0].get("finish_reason")
        if isinstance(candidate, str):
            finish_reason = candidate
    return request_id, model, fingerprint, finish_reason


def _sum_usage(values: list[TokenUsage]) -> TokenUsage:
    return TokenUsage(
        prompt_tokens=sum(value.prompt_tokens for value in values),
        completion_tokens=sum(value.completion_tokens for value in values),
        prompt_cache_hit_tokens=sum(value.prompt_cache_hit_tokens for value in values),
        prompt_cache_miss_tokens=sum(value.prompt_cache_miss_tokens for value in values),
        total_tokens=sum(value.total_tokens for value in values),
    )
