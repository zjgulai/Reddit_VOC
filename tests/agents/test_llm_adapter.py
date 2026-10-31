"""The agents' LLM client must fail loudly, and parse what models actually send.

Measured failures on tokenhub/deepseek-v4-flash and friends (2026-10-31):
  * a 290-token prompt spent 493 reasoning tokens, so `max_tokens=700` returned
    `finish_reason=length` and content ending mid-string -- `json.loads` raised
    `Unterminated string`;
  * kimi-k3 returned empty content with `finish_reason=length`;
  * glm-5.3-flash returned content truncated at the cap with no closing brace.

Each of those must surface as an error, because the caller's fallback is a
template that the morning card then discloses. A half-parsed analysis that looks
real is the exact failure this project already shipped once.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from reddit_voc.agents.llm_adapter import (  # noqa: E402
    AgentLLMError,
    OpenAICompatibleAgentClient,
    build_agent_client,
    strip_code_fence,
)

VALID = {
    "defects": [
        {
            "defect_id": "d1",
            "component": "top seal",
            "symptom": "leaks when leaning forward",
            "root_cause_hypothesis": "silicone tolerance",
            "suggested_action": "tighten QC spec",
            "severity": "major",
            "category": "sealing_leakage",
            "user_quote": None,
        }
    ],
    "engineering_summary": "seal tolerance",
    "urgency_rating": "P1",
}


def _envelope(content: str, *, finish: str = "stop", model: str = "deepseek-v4-flash-0731",
              usage: dict | None = None) -> bytes:
    return json.dumps({
        "id": "resp-1",
        "model": model,
        "choices": [{"index": 0, "finish_reason": finish,
                     "message": {"role": "assistant", "content": content}}],
        "usage": usage if usage is not None else {
            "prompt_tokens": 290,
            "completion_tokens": 862,
            "total_tokens": 1152,
            "completion_tokens_details": {"reasoning_tokens": 493},
        },
    }).encode("utf-8")


def _client(payloads, **kwargs):
    calls = []

    def transport(request, timeout):
        calls.append(json.loads(request.data.decode("utf-8")))
        item = payloads.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    client = OpenAICompatibleAgentClient(
        base_url="https://example.invalid/v1", model="deepseek-v4-flash",
        api_key="test-key-not-a-secret", transport=transport, **kwargs,
    )
    return client, calls


MESSAGES = {"messages": [
    {"role": "system", "content": "只输出 JSON"},
    {"role": "user", "content": "leaks when leaning"},
]}


def test_parses_a_valid_completion_and_exposes_content() -> None:
    client, calls = _client([_envelope(json.dumps(VALID))])
    result = client.complete_json(phase="rnd_voc", user_payload=MESSAGES)

    parsed = json.loads(result.content)
    assert parsed["urgency_rating"] == "P1"
    assert result.finish_reason == "stop"
    assert result.fenced is False

    # The request carries the caller's messages unchanged, and a generous budget.
    sent = calls[0]
    assert sent["messages"] == MESSAGES["messages"]
    assert sent["model"] == "deepseek-v4-flash"
    assert sent["stream"] is False
    assert sent["max_tokens"] >= 4096, "reasoning tokens count against the budget"


def test_truncated_output_is_reported_as_truncation_not_bad_json() -> None:
    """max_tokens=700 produced exactly this on a real call."""
    truncated = '{"defects":[{"defect_id":"DEF-M5-001","component":"顶部硅胶密封圈'
    client, _ = _client([_envelope(truncated, finish="length")])

    with pytest.raises(AgentLLMError) as excinfo:
        client.complete_json(phase="rnd_voc", user_payload=MESSAGES)
    message = str(excinfo.value)
    assert "truncated" in message
    assert "max_tokens" in message


def test_empty_content_raises_rather_than_returning_a_blank_analysis() -> None:
    """kimi-k3 returned '' with finish_reason=length on a real call."""
    client, _ = _client([_envelope("", finish="length")])

    with pytest.raises(AgentLLMError):
        client.complete_json(phase="rnd_voc", user_payload=MESSAGES)


def test_markdown_fence_is_stripped_and_reported() -> None:
    fenced = "```json\n" + json.dumps(VALID) + "\n```"
    client, _ = _client([_envelope(fenced)])

    result = client.complete_json(phase="rnd_voc", user_payload=MESSAGES)
    assert result.fenced is True
    assert json.loads(result.content)["urgency_rating"] == "P1"


def test_prose_with_an_embedded_code_block_still_fails() -> None:
    """Only a fully-wrapped payload is presentation; prose is not JSON."""
    prose = "Here is the analysis:\n```json\n" + json.dumps(VALID) + "\n```\nHope this helps!"
    client, _ = _client([_envelope(prose)])

    with pytest.raises(AgentLLMError):
        client.complete_json(phase="rnd_voc", user_payload=MESSAGES)


def test_strip_code_fence_only_unwraps_a_whole_payload() -> None:
    body = json.dumps(VALID)
    assert strip_code_fence(f"```json\n{body}\n```") == (body, True)
    assert strip_code_fence(body) == (body, False)
    assert strip_code_fence(f"prefix {body}") == (f"prefix {body}", False)


def test_multiple_choices_are_rejected() -> None:
    payload = json.loads(_envelope(json.dumps(VALID)))
    payload["choices"].append(payload["choices"][0])
    client, _ = _client([json.dumps(payload).encode()])

    with pytest.raises(AgentLLMError) as excinfo:
        client.complete_json(phase="rnd_voc", user_payload=MESSAGES)
    assert "one choice" in str(excinfo.value)


def test_empty_messages_are_rejected_before_the_network() -> None:
    client, calls = _client([_envelope(json.dumps(VALID))])
    with pytest.raises(AgentLLMError):
        client.complete_json(phase="rnd_voc", user_payload={"messages": []})
    assert calls == []


def test_http_error_carries_status_and_body_excerpt() -> None:
    import urllib.error

    error = urllib.error.HTTPError(
        "https://example.invalid", 400, "Bad Request", {},
        __import__("io").BytesIO(b'{"error":"unsupported field"}'),
    )
    client, _ = _client([error])

    with pytest.raises(AgentLLMError) as excinfo:
        client.complete_json(phase="rnd_voc", user_payload=MESSAGES)
    assert "http_400" in str(excinfo.value)
    assert "unsupported field" in str(excinfo.value)


def test_non_json_transport_body_is_an_error() -> None:
    client, _ = _client([b"<html>gateway</html>"])
    with pytest.raises(AgentLLMError):
        client.complete_json(phase="rnd_voc", user_payload=MESSAGES)


def test_build_client_returns_none_when_not_configured(monkeypatch) -> None:
    """None is the honest answer: the pipeline then discloses template mode."""
    for var in ("AGENT_LLM_BASE_URL", "AGENT_LLM_MODEL", "AGENT_LLM_API_KEY",
                "AGENT_LLM_API_KEY_FILE", "AGENT_LLM_MAX_TOKENS"):
        monkeypatch.delenv(var, raising=False)
    assert build_agent_client() is None

    # Partial configuration must not produce a half-working client either.
    monkeypatch.setenv("AGENT_LLM_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("AGENT_LLM_MODEL", "deepseek-v4-flash")
    assert build_agent_client() is None, "model+url without a key must stay offline"


def test_build_client_reads_the_key_from_a_file(monkeypatch, tmp_path: Path) -> None:
    keyfile = tmp_path / "agent-llm-key"
    keyfile.write_text("  from-a-file  \n", encoding="utf-8")

    monkeypatch.setenv("AGENT_LLM_BASE_URL", "https://example.invalid/v1/")
    monkeypatch.setenv("AGENT_LLM_MODEL", "deepseek-v4-flash")
    monkeypatch.setenv("AGENT_LLM_API_KEY_FILE", str(keyfile))
    monkeypatch.delenv("AGENT_LLM_API_KEY", raising=False)

    client = build_agent_client()
    assert client is not None
    assert client.api_key == "from-a-file", "surrounding whitespace must be stripped"
    assert client.base_url == "https://example.invalid/v1", "trailing slash must not double"


def test_build_client_prefers_the_direct_key_over_the_file(monkeypatch, tmp_path: Path) -> None:
    keyfile = tmp_path / "k"
    keyfile.write_text("file-key", encoding="utf-8")
    monkeypatch.setenv("AGENT_LLM_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("AGENT_LLM_MODEL", "m")
    monkeypatch.setenv("AGENT_LLM_API_KEY", "direct-key")
    monkeypatch.setenv("AGENT_LLM_API_KEY_FILE", str(keyfile))

    assert build_agent_client().api_key == "direct-key"


def test_max_tokens_has_a_floor(monkeypatch) -> None:
    """A tiny budget is the trap that truncated real output; refuse it."""
    monkeypatch.setenv("AGENT_LLM_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("AGENT_LLM_MODEL", "m")
    monkeypatch.setenv("AGENT_LLM_API_KEY", "k")
    monkeypatch.setenv("AGENT_LLM_MAX_TOKENS", "16")

    assert build_agent_client().max_tokens == 512


# --------------------------------------------------------------- batch runner


def test_batch_runner_runs_concurrently_but_keeps_input_order() -> None:
    """Concurrency is a timeout requirement; determinism must survive it.

    Serial LLM calls measured 35s/post, about 45 minutes for a 78-post day, which
    the service timeout would kill. Results must still be ordered by the input,
    not by whichever request finished first.
    """
    import time as _time

    from reddit_voc.agents.batch_runner import AgentBatchRunner

    class SlowClient:
        """Answers after a delay that shrinks with the post id, to force reordering."""

        model = "slow"

        def complete_json(self, *, phase, user_payload, attempt_budget=None):
            text = str(user_payload)
            post = "p9" if '"p9"' in text else ("p1" if '"p1"' in text else "p5")
            _time.sleep({"p1": 0.15, "p5": 0.08, "p9": 0.02}[post])
            payload = {
                "defects": [{
                    "defect_id": post, "component": "seal", "symptom": "leaks",
                    "root_cause_hypothesis": "x", "suggested_action": "y",
                    "severity": "major", "category": "sealing_leakage",
                    "user_quote": None,
                }],
                "engineering_summary": "s", "urgency_rating": "P1",
            }

            class R:
                content = json.dumps(payload)

            return R()

    posts = [
        {"post_id": "p1", "title": "pump leaks", "selftext": "leak"},
        {"post_id": "p5", "title": "pump leaks", "selftext": "leak"},
        {"post_id": "p9", "title": "pump leaks", "selftext": "leak"},
    ]
    runner = AgentBatchRunner(client=SlowClient(), config_path=ROOT / "config/agent_settings.json")

    started = _time.time()
    out = runner.run_batch(posts, run_id="order", max_workers=3)
    elapsed = _time.time() - started

    ids = [r.source_post_id for r in out.rnd_voc_results]
    assert ids == ["p1", "p5", "p9"], f"input order lost: {ids}"
    # Serial would be >= 0.25s; concurrent finishes in about the slowest request.
    assert elapsed < 0.24, f"posts were not run concurrently ({elapsed:.2f}s)"


def test_batch_runner_without_a_client_runs_inline() -> None:
    """The template path has nothing to wait on, so it stays synchronous."""
    from reddit_voc.agents.batch_runner import AgentBatchRunner

    posts = [{"post_id": "p1", "title": "Momcozy pump leaks", "selftext": "it leaks"}]
    runner = AgentBatchRunner(client=None, config_path=ROOT / "config/agent_settings.json")
    out = runner.run_batch(posts, run_id="inline")

    assert out.total_posts_analyzed == 1
    assert [r.source_post_id for r in out.rnd_voc_results] == ["p1"]
