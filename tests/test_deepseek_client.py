from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.request import Request

from reddit_voc import deepseek_client
from reddit_voc.deepseek_client import (
    DEEPSEEK_CHAT_COMPLETIONS_URL,
    DeepSeekClient,
    DeepSeekClientError,
    UrllibHttpTransport,
)
from reddit_voc.report_contracts import AttemptBudget, MonotonicDeadline
from reddit_voc.provider_attempt_ledger import ProviderAttemptLedger, ProviderAttemptLifecycle


SYNTHETIC_KEY = "synthetic-secret-never-log"


class FakeClock:
    def __init__(self, value: float = 100.0) -> None:
        self.value = value
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.value += seconds


class FakeResponse:
    def __init__(
        self,
        status: int,
        payload: bytes | list[bytes | tuple[bytes, float]],
        *,
        clock: FakeClock | None = None,
    ) -> None:
        self.status = status
        self._chunks = list(payload if isinstance(payload, list) else [payload])
        self._clock = clock
        self.closed = False
        self.read_sizes: list[int] = []

    def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        if not self._chunks:
            return b""
        item = self._chunks.pop(0)
        if isinstance(item, tuple):
            chunk, advance = item
            if self._clock is not None:
                self._clock.value += advance
            return chunk
        return item

    def close(self) -> None:
        self.closed = True


class FakeTransport:
    def __init__(self, outcomes: list[FakeResponse | BaseException]) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[tuple[Request, float]] = []

    def open(self, request: Request, *, timeout: float) -> FakeResponse:
        self.calls.append((request, timeout))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _usage(
    *,
    prompt: int = 3,
    completion: int = 2,
    hit: int = 1,
    miss: int = 2,
) -> dict[str, int]:
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "prompt_cache_hit_tokens": hit,
        "prompt_cache_miss_tokens": miss,
        "total_tokens": prompt + completion,
    }


def _envelope(
    *,
    finish_reason: str = "stop",
    content: Any = '{"translations":[]}',
    model: str = "deepseek-v4-flash",
    request_id: str = "resp-1",
    usage: dict[str, int] | None = None,
    fingerprint: str | None = "fp-1",
) -> bytes:
    value = {
        "id": request_id,
        "model": model,
        "system_fingerprint": fingerprint,
        "choices": [
            {
                "finish_reason": finish_reason,
                "message": {"content": content},
            }
        ],
        "usage": _usage() if usage is None else usage,
    }
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


def _client(
    outcomes: list[FakeResponse | BaseException],
    *,
    clock: FakeClock | None = None,
    max_response_bytes: int = 4 * 1024 * 1024,
) -> tuple[DeepSeekClient, FakeTransport, FakeClock]:
    clock = clock or FakeClock()
    transport = FakeTransport(outcomes)
    client = DeepSeekClient(
        api_key=SYNTHETIC_KEY,
        transport=transport,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        uniform=lambda _low, _high: 0.125,
        max_response_bytes=max_response_bytes,
    )
    return client, transport, clock


class RequestEnvelopeTests(unittest.TestCase):
    def test_default_transport_disables_redirects_and_environment_proxies(self) -> None:
        transport = UrllibHttpTransport()
        redirect_handlers = [
            handler
            for handler in transport._opener.handlers
            if isinstance(handler, deepseek_client._NoRedirectHandler)
        ]
        self.assertEqual(len(redirect_handlers), 1)
        for code in (301, 302, 303, 307, 308):
            self.assertIsNone(
                redirect_handlers[0].redirect_request(
                    None,
                    None,
                    code,
                    "redirect",
                    {"Location": "https://evil.example/capture"},
                    "https://evil.example/capture",
                )
            )
        proxy_handlers = [
            handler
            for handler in transport._opener.handlers
            if handler.__class__.__name__ == "ProxyHandler"
        ]
        self.assertEqual(proxy_handlers, [])

    def test_exact_translation_request_envelope_and_headers(self) -> None:
        response = FakeResponse(200, _envelope())
        client, transport, clock = _client([response])
        completion = client.complete_json(
            phase="translation",
            system_prompt="system json prompt",
            user_payload={"z": 1, "a": "中文"},
            deadline=MonotonicDeadline(clock.monotonic() + 60),
            attempt_budget=AttemptBudget(),
        )

        self.assertEqual(completion.content, '{"translations":[]}')
        self.assertEqual(completion.model, "deepseek-v4-flash")
        self.assertEqual(len(transport.calls), 1)
        request, timeout = transport.calls[0]
        self.assertEqual(request.full_url, DEEPSEEK_CHAT_COMPLETIONS_URL)
        self.assertEqual(timeout, 60.0)
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(
            body,
            {
                "model": "deepseek-v4-flash",
                "messages": [
                    {"role": "system", "content": "system json prompt"},
                    {"role": "user", "content": '{"a":"中文","z":1}'},
                ],
                "stream": False,
                "temperature": 0,
                "thinking": {"type": "disabled"},
                "response_format": {"type": "json_object"},
                "user_id": "reddit_voc_daily_translation",
                "max_tokens": 16384,
            },
        )
        headers = {key.lower(): value for key, value in request.header_items()}
        self.assertEqual(headers["content-type"], "application/json; charset=utf-8")
        self.assertEqual(headers["accept"], "application/json")
        self.assertEqual(headers["user-agent"], "Reddit-VOC-Daily-Report/1")
        self.assertEqual(headers["authorization"], f"Bearer {SYNTHETIC_KEY}")

    def test_transport_timeout_uses_remaining_deadline_up_to_120_seconds(self) -> None:
        client, transport, clock = _client(
            [FakeResponse(200, _envelope()), FakeResponse(200, _envelope())]
        )

        client.complete_json(
            phase="translation",
            system_prompt="system json prompt",
            user_payload={},
            deadline=MonotonicDeadline(clock.monotonic() + 90),
            attempt_budget=AttemptBudget(),
        )
        client.complete_json(
            phase="translation",
            system_prompt="system json prompt",
            user_payload={},
            deadline=MonotonicDeadline(clock.monotonic() + 300),
            attempt_budget=AttemptBudget(),
        )

        self.assertEqual([timeout for _request, timeout in transport.calls], [90.0, 120.0])

    def test_validator_uses_smaller_fixed_output_cap(self) -> None:
        client, transport, clock = _client([FakeResponse(200, _envelope(content='{"verdicts":[]}'))])
        client.complete_json(
            phase="semantic_validation",
            system_prompt="validator json",
            user_payload={"items": []},
            deadline=MonotonicDeadline(clock.monotonic() + 20),
            attempt_budget=AttemptBudget(),
        )
        body = json.loads(transport.calls[0][0].data.decode("utf-8"))
        self.assertEqual(body["max_tokens"], 4096)
        self.assertEqual(transport.calls[0][1], 20.0)

    def test_repr_and_errors_redact_key(self) -> None:
        client, _transport, clock = _client([FakeResponse(400, b'{"error":"bad"}')])
        with self.assertRaises(DeepSeekClientError) as raised:
            client.complete_json(
                phase="translation",
                system_prompt="json",
                user_payload={},
                deadline=MonotonicDeadline(clock.monotonic() + 60),
                attempt_budget=AttemptBudget(),
            )
        rendered = repr(client) + repr(raised.exception) + str(raised.exception)
        self.assertIn("<redacted>", rendered)
        self.assertNotIn(SYNTHETIC_KEY, rendered)


class RetryAndEvidenceTests(unittest.TestCase):
    def test_invalid_json_content_is_terminal_then_retried_in_process(self) -> None:
        client, transport, clock = _client(
            [
                FakeResponse(200, _envelope(content='{"translations":')),
                FakeResponse(
                    200,
                    _envelope(
                        content='{"translations":[]}',
                        request_id="valid-json-response",
                    ),
                ),
            ]
        )

        completion = client.complete_json(
            phase="translation",
            system_prompt="json",
            user_payload={},
            deadline=MonotonicDeadline(clock.monotonic() + 120),
            attempt_budget=AttemptBudget(),
        )

        self.assertEqual(completion.request_id, "valid-json-response")
        self.assertEqual(len(transport.calls), 2)
        self.assertEqual(len(completion.attempts), 2)
        self.assertEqual(completion.attempts[0].outcome, "invalid_json_content")
        self.assertTrue(completion.attempts[0].retryable)
        self.assertEqual(completion.attempts[1].outcome, "success")
        self.assertEqual(clock.sleeps, [1.125])

    def test_invalid_json_content_exhaustion_preserves_reason_for_outer_recovery(self) -> None:
        client, transport, clock = _client(
            [
                FakeResponse(200, _envelope(content='{"translations":')),
                FakeResponse(200, _envelope(content='{"translations":')),
                FakeResponse(200, _envelope(content='{"translations":')),
            ]
        )

        with self.assertRaises(DeepSeekClientError) as raised:
            client.complete_json(
                phase="translation",
                system_prompt="json",
                user_payload={},
                deadline=MonotonicDeadline(clock.monotonic() + 120),
                attempt_budget=AttemptBudget(),
            )

        self.assertEqual(raised.exception.reason_code, "invalid_json_content")
        self.assertEqual(len(transport.calls), 3)
        self.assertEqual(
            [attempt.outcome for attempt in raised.exception.attempts],
            ["invalid_json_content"] * 3,
        )
        self.assertEqual(clock.sleeps, [1.125, 2.125])

    def test_retryable_transport_status_empty_and_resource_failures_cap_at_three(self) -> None:
        cases: list[FakeResponse | BaseException] = [
            FakeResponse(429, b"{}"),
            FakeResponse(500, b"{}"),
            FakeResponse(503, b"{}"),
            FakeResponse(200, b""),
            FakeResponse(200, _envelope(finish_reason="insufficient_system_resource", content=None)),
        ]
        for first in cases:
            with self.subTest(first=type(first).__name__, status=getattr(first, "status", None)):
                client, transport, clock = _client(
                    [first, FakeResponse(200, _envelope(request_id="resp-success"))]
                )
                completion = client.complete_json(
                    phase="translation",
                    system_prompt="json",
                    user_payload={},
                    deadline=MonotonicDeadline(clock.monotonic() + 120),
                    attempt_budget=AttemptBudget(),
                )
                self.assertEqual(completion.request_id, "resp-success")
                self.assertEqual(len(transport.calls), 2)
                self.assertEqual(len(completion.attempts), 2)
                self.assertEqual(clock.sleeps, [1.125])

        client, transport, clock = _client(
            [FakeResponse(429, b"{}") for _ in range(3)]
        )
        with self.assertRaises(DeepSeekClientError) as raised:
            client.complete_json(
                phase="translation",
                system_prompt="json",
                user_payload={},
                deadline=MonotonicDeadline(clock.monotonic() + 120),
                attempt_budget=AttemptBudget(),
            )
        self.assertEqual(raised.exception.reason_code, "retry_exhausted")
        self.assertEqual(len(transport.calls), 3)
        self.assertEqual(
            [attempt.outcome for attempt in raised.exception.attempts],
            ["http_status_429"] * 3,
        )

        client, transport, clock = _client([OSError("a"), OSError("b"), OSError("c")])
        with self.assertRaises(DeepSeekClientError) as raised:
            client.complete_json(
                phase="translation",
                system_prompt="json",
                user_payload={},
                deadline=MonotonicDeadline(clock.monotonic() + 120),
                attempt_budget=AttemptBudget(),
            )
        self.assertEqual(raised.exception.reason_code, "provider_attempt_unknown")
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(clock.sleeps, [])

    def test_response_read_errors_are_recorded_as_external_attempts(self) -> None:
        class ReadErrorResponse(FakeResponse):
            def read(self, size: int = -1) -> bytes:
                raise OSError("synthetic response read failure")

        responses = [ReadErrorResponse(200, b"") for _ in range(3)]
        client, transport, clock = _client(responses)
        with self.assertRaises(DeepSeekClientError) as raised:
            client.complete_json(
                phase="translation",
                system_prompt="json",
                user_payload={},
                deadline=MonotonicDeadline(clock.monotonic() + 120),
                attempt_budget=AttemptBudget(),
            )
        self.assertEqual(raised.exception.reason_code, "provider_attempt_unknown")
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(len(raised.exception.attempts), 1)
        self.assertEqual(
            raised.exception.attempts[0].outcome, "unknown_external_state"
        )
        self.assertFalse(raised.exception.attempts[0].retryable)
        self.assertTrue(responses[0].closed)
        self.assertTrue(all(not response.closed for response in responses[1:]))

    def test_response_close_error_does_not_override_completed_attempt_evidence(self) -> None:
        class CloseErrorResponse(FakeResponse):
            def close(self) -> None:
                self.closed = True
                raise OSError("synthetic close failure")

        response = CloseErrorResponse(200, _envelope())
        client, _transport, clock = _client([response])
        completion = client.complete_json(
            phase="translation",
            system_prompt="json",
            user_payload={},
            deadline=MonotonicDeadline(clock.monotonic() + 60),
            attempt_budget=AttemptBudget(),
        )
        self.assertEqual(completion.request_id, "resp-1")
        self.assertEqual(len(completion.attempts), 1)
        self.assertTrue(response.closed)

    def test_resource_retry_ignores_null_empty_and_partial_content_and_aggregates_usage(self) -> None:
        for content in [None, "", '{"partial":']:
            with self.subTest(content=content):
                first_usage = _usage(prompt=5, completion=1, hit=2, miss=3)
                second_usage = _usage(prompt=7, completion=4, hit=1, miss=6)
                client, _transport, clock = _client(
                    [
                        FakeResponse(
                            200,
                            _envelope(
                                finish_reason="insufficient_system_resource",
                                content=content,
                                request_id="resource",
                                usage=first_usage,
                            ),
                        ),
                        FakeResponse(200, _envelope(request_id="success", usage=second_usage)),
                    ]
                )
                completion = client.complete_json(
                    phase="translation",
                    system_prompt="json",
                    user_payload={},
                    deadline=MonotonicDeadline(clock.monotonic() + 120),
                    attempt_budget=AttemptBudget(),
                )
                self.assertEqual(completion.usage.prompt_tokens, 12)
                self.assertEqual(completion.usage.completion_tokens, 5)
                self.assertEqual(completion.usage.total_tokens, 17)
                self.assertEqual(completion.attempts[0].finish_reason, "insufficient_system_resource")
                self.assertEqual(completion.attempts[0].usage.prompt_tokens, 5)

    def test_fail_fast_status_finish_model_and_content_cases(self) -> None:
        status_cases = [300, 301, 400, 401, 402, 403, 404, 409, 418, 422, 501]
        for status in status_cases:
            with self.subTest(status=status):
                client, transport, clock = _client([FakeResponse(status, b"{}")])
                with self.assertRaises(DeepSeekClientError) as raised:
                    client.complete_json(
                        phase="translation",
                        system_prompt="json",
                        user_payload={},
                        deadline=MonotonicDeadline(clock.monotonic() + 60),
                        attempt_budget=AttemptBudget(),
                    )
                self.assertEqual(raised.exception.reason_code, "http_status_blocked")
                self.assertEqual(len(transport.calls), 1)

        envelope_cases = [
            (_envelope(finish_reason="length"), "finish_reason_length"),
            (_envelope(finish_reason="content_filter"), "finish_reason_content_filter"),
            (_envelope(finish_reason="tool_calls"), "finish_reason_tool_calls"),
            (_envelope(finish_reason="mystery"), "finish_reason_unknown"),
            (_envelope(model="other-model"), "model_mismatch"),
            (_envelope(content=None), "empty_content"),
            (_envelope(content="   "), "empty_content"),
            (b"not-json", "invalid_response_envelope"),
            (json.dumps({"id": "x"}).encode(), "invalid_response_envelope"),
        ]
        for payload, reason in envelope_cases:
            with self.subTest(reason=reason):
                client, transport, clock = _client([FakeResponse(200, payload)])
                with self.assertRaises(DeepSeekClientError) as raised:
                    client.complete_json(
                        phase="translation",
                        system_prompt="json",
                        user_payload={},
                        deadline=MonotonicDeadline(clock.monotonic() + 60),
                        attempt_budget=AttemptBudget(),
                    )
                self.assertEqual(raised.exception.reason_code, reason)
                self.assertEqual(len(transport.calls), 1)

    def test_fail_fast_parsed_responses_retain_metadata_and_usage(self) -> None:
        usage = _usage(prompt=9, completion=3, hit=4, miss=5)
        for finish_reason in ["length", "content_filter"]:
            with self.subTest(finish_reason=finish_reason):
                client, _transport, clock = _client(
                    [
                        FakeResponse(
                            200,
                            _envelope(
                                finish_reason=finish_reason,
                                request_id="billed-response",
                                usage=usage,
                                fingerprint="fp-billed",
                            ),
                        )
                    ]
                )
                with self.assertRaises(DeepSeekClientError) as raised:
                    client.complete_json(
                        phase="semantic_validation",
                        system_prompt="json",
                        user_payload={},
                        deadline=MonotonicDeadline(clock.monotonic() + 60),
                        attempt_budget=AttemptBudget(),
                    )
                error = raised.exception
                self.assertEqual(error.response_id, "billed-response")
                self.assertEqual(error.actual_model, "deepseek-v4-flash")
                self.assertEqual(error.system_fingerprint, "fp-billed")
                self.assertEqual(error.finish_reason, finish_reason)
                self.assertEqual(error.usage.prompt_tokens, 9)
                self.assertEqual(error.attempts[0].usage.total_tokens, 12)

    def test_usage_is_strict_and_invalid_usage_never_enters_evidence(self) -> None:
        invalid = [
            {key: value for key, value in _usage().items() if key != "total_tokens"},
            _usage(prompt=-1, completion=2, hit=0, miss=-1),
            _usage(prompt=3, completion=2, hit=1, miss=1),
            {**_usage(), "total_tokens": 99},
            {**_usage(), "prompt_tokens": True},
        ]
        for usage in invalid:
            with self.subTest(usage=usage):
                client, _transport, clock = _client([FakeResponse(200, _envelope(usage=usage))])
                with self.assertRaises(DeepSeekClientError) as raised:
                    client.complete_json(
                        phase="translation",
                        system_prompt="json",
                        user_payload={},
                        deadline=MonotonicDeadline(clock.monotonic() + 60),
                        attempt_budget=AttemptBudget(),
                    )
                self.assertEqual(raised.exception.reason_code, "invalid_usage")
                self.assertEqual(raised.exception.usage.total_tokens, 0)
                self.assertIsNone(raised.exception.attempts[0].usage)

    def test_arbitrary_error_text_never_enables_resource_retry(self) -> None:
        payload = json.dumps(
            {"error": {"message": "insufficient_system_resource", "type": "insufficient_system_resource"}}
        ).encode()
        client, transport, clock = _client(
            [FakeResponse(400, payload), FakeResponse(200, _envelope())]
        )
        with self.assertRaises(DeepSeekClientError) as raised:
            client.complete_json(
                phase="translation",
                system_prompt="json",
                user_payload={},
                deadline=MonotonicDeadline(clock.monotonic() + 60),
                attempt_budget=AttemptBudget(),
            )
        self.assertEqual(raised.exception.reason_code, "http_status_blocked")
        self.assertEqual(len(transport.calls), 1)


class DeadlineBudgetAndBoundsTests(unittest.TestCase):
    def test_lifecycle_sink_hashes_request_and_unknown_transport_never_retries(self) -> None:
        events: list[tuple[object, ...]] = []

        class LifecycleSink:
            def reserve(self, *, sequence: int, phase: str, request_payload_sha256: str) -> None:
                events.append(("reservation", sequence, phase, request_payload_sha256))

            def start(self, *, sequence: int, phase: str, request_payload_sha256: str) -> None:
                events.append(("start", sequence, phase, request_payload_sha256))

            def terminal(
                self,
                *,
                sequence: int,
                phase: str,
                request_payload_sha256: str,
                evidence: object,
            ) -> None:
                events.append(("terminal", sequence, phase, request_payload_sha256, evidence))

            def unknown(self, *, sequence: int, phase: str, request_payload_sha256: str) -> None:
                events.append(("unknown", sequence, phase, request_payload_sha256))

        clock = FakeClock()
        transport = FakeTransport([OSError("uncertain"), FakeResponse(200, _envelope())])
        client = DeepSeekClient(
            api_key=SYNTHETIC_KEY,
            transport=transport,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
            uniform=lambda _low, _high: 0,
            attempt_lifecycle_sink=LifecycleSink(),
        )
        with self.assertRaises(DeepSeekClientError) as raised:
            client.complete_json(
                phase="translation",
                system_prompt="json",
                user_payload={"items": []},
                deadline=MonotonicDeadline(clock.monotonic() + 60),
                attempt_budget=AttemptBudget(),
            )
        self.assertEqual(raised.exception.reason_code, "provider_attempt_unknown")
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual([event[0] for event in events], ["reservation", "start", "unknown"])
        expected_request_sha = hashlib.sha256(transport.calls[0][0].data).hexdigest()
        self.assertTrue(all(event[3] == expected_request_sha for event in events))
        self.assertEqual(clock.sleeps, [])

    def test_real_ledger_closes_uncertain_transport_as_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "attempt"
            root.mkdir(mode=0o700)
            ledger = ProviderAttemptLedger(
                path=root / "provider-attempts-v2.jsonl",
                authorization_id="auth-1",
                release_sha256="a" * 64,
                run_id="run-1",
                attempt_id="attempt-1",
                clock=lambda: "2026-08-11T01:02:03+00:00",
            )
            clock = FakeClock()
            transport = FakeTransport(
                [OSError("uncertain"), FakeResponse(200, _envelope())]
            )
            client = DeepSeekClient(
                api_key=SYNTHETIC_KEY,
                transport=transport,
                monotonic=clock.monotonic,
                sleep=clock.sleep,
                uniform=lambda _low, _high: 0,
                attempt_lifecycle_sink=ProviderAttemptLifecycle(ledger),
            )

            with self.assertRaises(DeepSeekClientError) as raised:
                client.complete_json(
                    phase="translation",
                    system_prompt="prompt-do-not-store",
                    user_payload={"private": "payload-do-not-store"},
                    deadline=MonotonicDeadline(clock.monotonic() + 60),
                    attempt_budget=AttemptBudget(),
                )

            self.assertEqual(raised.exception.reason_code, "provider_attempt_unknown")
            self.assertEqual(len(transport.calls), 1)
            binding = ledger.build_manifest_binding(status="blocked")
            self.assertEqual(binding["external_attempt_count"], 1)
            self.assertEqual(binding["unknown_attempt_count"], 1)
            self.assertEqual(binding["attempts"][0]["closure_event_type"], "unknown")
            ledger_bytes = ledger.path.read_bytes()
            self.assertNotIn(b"prompt-do-not-store", ledger_bytes)
            self.assertNotIn(b"payload-do-not-store", ledger_bytes)
            self.assertNotIn(SYNTHETIC_KEY.encode("utf-8"), ledger_bytes)

    def test_explicit_retryable_terminal_closes_before_next_reservation(self) -> None:
        events: list[tuple[object, ...]] = []

        class LifecycleSink:
            def reserve(self, *, sequence: int, phase: str, request_payload_sha256: str) -> None:
                events.append(("reservation", sequence))

            def start(self, *, sequence: int, phase: str, request_payload_sha256: str) -> None:
                events.append(("start", sequence))

            def terminal(
                self,
                *,
                sequence: int,
                phase: str,
                request_payload_sha256: str,
                evidence: object,
            ) -> None:
                events.append(("terminal", sequence, getattr(evidence, "outcome")))

            def unknown(self, *, sequence: int, phase: str, request_payload_sha256: str) -> None:
                events.append(("unknown", sequence))

        clock = FakeClock()
        transport = FakeTransport(
            [FakeResponse(503, b"{}"), FakeResponse(200, _envelope())]
        )
        client = DeepSeekClient(
            api_key=SYNTHETIC_KEY,
            transport=transport,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
            uniform=lambda _low, _high: 0,
            attempt_lifecycle_sink=LifecycleSink(),
        )
        client.complete_json(
            phase="translation",
            system_prompt="json",
            user_payload={},
            deadline=MonotonicDeadline(clock.monotonic() + 120),
            attempt_budget=AttemptBudget(),
        )
        self.assertEqual(
            events,
            [
                ("reservation", 1),
                ("start", 1),
                ("terminal", 1, "http_status_503"),
                ("reservation", 2),
                ("start", 2),
                ("terminal", 2, "success"),
            ],
        )

    def test_reservation_sink_precedes_open_and_sink_failure_opens_nothing(self) -> None:
        events: list[str] = []

        class RecordingTransport(FakeTransport):
            def open(self, request: Request, *, timeout: float) -> FakeResponse:
                events.append("open")
                return super().open(request, timeout=timeout)

        transport = RecordingTransport([FakeResponse(200, _envelope())])
        clock = FakeClock()

        def sink(*, sequence: int, phase: str) -> None:
            events.append(f"reserve:{sequence}:{phase}")

        client = DeepSeekClient(
            api_key=SYNTHETIC_KEY,
            transport=transport,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
            uniform=lambda _low, _high: 0,
        )
        client.complete_json(
            phase="translation",
            system_prompt="json",
            user_payload={},
            deadline=MonotonicDeadline(clock.monotonic() + 60),
            attempt_budget=AttemptBudget(reservation_sink=sink),
        )
        self.assertEqual(events[:2], ["reserve:1:translation", "open"])

        def failing_sink(*, sequence: int, phase: str) -> None:
            raise RuntimeError("durable sink unavailable")

        transport = RecordingTransport([FakeResponse(200, _envelope())])
        client = DeepSeekClient(
            api_key=SYNTHETIC_KEY,
            transport=transport,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
            uniform=lambda _low, _high: 0,
        )
        budget = AttemptBudget(reservation_sink=failing_sink)
        with self.assertRaisesRegex(RuntimeError, "durable sink unavailable"):
            client.complete_json(
                phase="translation",
                system_prompt="json",
                user_payload={},
                deadline=MonotonicDeadline(clock.monotonic() + 60),
                attempt_budget=budget,
            )
        self.assertEqual(len(transport.calls), 0)
        self.assertEqual(budget.used, 0)

    def test_deadline_exhaustion_prevents_reserve_open_and_overlong_sleep(self) -> None:
        client, transport, clock = _client([FakeResponse(200, _envelope())])
        budget = AttemptBudget()
        with self.assertRaises(DeepSeekClientError) as raised:
            client.complete_json(
                phase="translation",
                system_prompt="json",
                user_payload={},
                deadline=MonotonicDeadline(clock.monotonic()),
                attempt_budget=budget,
            )
        self.assertEqual(raised.exception.reason_code, "deadline_exhausted")
        self.assertEqual(budget.used, 0)
        self.assertEqual(transport.calls, [])

        client, transport, clock = _client([OSError("offline"), FakeResponse(200, _envelope())])
        with self.assertRaises(DeepSeekClientError) as raised:
            client.complete_json(
                phase="translation",
                system_prompt="json",
                user_payload={},
                deadline=MonotonicDeadline(clock.monotonic() + 1.0),
                attempt_budget=AttemptBudget(),
            )
        self.assertEqual(raised.exception.reason_code, "provider_attempt_unknown")
        self.assertEqual(clock.sleeps, [])
        self.assertEqual(len(transport.calls), 1)

    def test_response_size_and_inflight_deadline_are_enforced_and_closed(self) -> None:
        oversized = FakeResponse(200, [b"1234", b"56"])
        client, _transport, clock = _client([oversized], max_response_bytes=5)
        with self.assertRaises(DeepSeekClientError) as raised:
            client.complete_json(
                phase="translation",
                system_prompt="json",
                user_payload={},
                deadline=MonotonicDeadline(clock.monotonic() + 60),
                attempt_budget=AttemptBudget(),
            )
        self.assertEqual(raised.exception.reason_code, "response_too_large")
        self.assertTrue(oversized.closed)
        self.assertTrue(all(size <= 6 for size in oversized.read_sizes))

        clock = FakeClock()
        keep_alive = FakeResponse(200, [(b"   ", 0.6), (b"\n", 0.6), _envelope()], clock=clock)
        client, _transport, _clock = _client([keep_alive], clock=clock)
        with self.assertRaises(DeepSeekClientError) as raised:
            client.complete_json(
                phase="translation",
                system_prompt="json",
                user_payload={},
                deadline=MonotonicDeadline(clock.monotonic() + 1.0),
                attempt_budget=AttemptBudget(),
            )
        self.assertEqual(raised.exception.reason_code, "provider_attempt_unknown")
        self.assertTrue(keep_alive.closed)

    def test_shared_attempt_budget_is_thread_safe_and_hard_capped(self) -> None:
        budget = AttemptBudget(max_attempts=2)
        client, transport, clock = _client(
            [
                FakeResponse(503, b"{}"),
                FakeResponse(503, b"{}"),
                FakeResponse(200, _envelope()),
            ]
        )
        with self.assertRaises(DeepSeekClientError) as raised:
            client.complete_json(
                phase="translation",
                system_prompt="json",
                user_payload={},
                deadline=MonotonicDeadline(clock.monotonic() + 120),
                attempt_budget=budget,
            )
        self.assertEqual(raised.exception.reason_code, "attempt_budget_exhausted")
        self.assertEqual(budget.used, 2)
        self.assertEqual(len(transport.calls), 2)


if __name__ == "__main__":
    unittest.main()
