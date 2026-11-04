"""OpenAI-compatible completion client for the three batch agents.

Why this exists
---------------
The agents call `client.complete_json(phase=..., user_payload=..., attempt_budget=...)`
and then `json.loads(response.content)`. `DeepSeekClient` — the client the rest of
the project uses — cannot serve them:

  * it only accepts `phase in {"translation", "semantic_validation"}`, and the
    agents pass "rnd_voc", "content_scouting" and "competitor_radar", so every
    call would raise `invalid_attempt_phase` before reaching the network;
  * it requires `system_prompt` and `deadline`, which the agents do not pass
    (they put the system prompt inside `user_payload.messages`);
  * it validates a DeepSeek-only usage shape (`prompt_cache_hit_tokens`,
    `prompt_cache_miss_tokens`) and an exact model echo, so a relay that omits
    or renames either is a terminal error.

That mismatch — not a missing key — is why production runs with `client=None`
and serves template analysis. This module is the missing adapter, and it is
deliberately small: one endpoint, one model, one JSON call, no retry policy
borrowed from the translation pipeline.

Design rules, each earned from a measured failure:

  * Reasoning tokens count against `max_tokens`. A 290-token prompt cost 493
    reasoning tokens on deepseek-v4-flash; with `max_tokens=700` the JSON came
    back unterminated (`Unterminated string`). The default budget is therefore
    generous and the finish_reason is checked before parsing.
  * Fenced output is repaired, not trusted. Several models wrap JSON in a
    markdown fence; stripping it is safe, silently accepting prose is not.
  * A model that returns something unparseable raises instead of returning
    empty content, so the caller falls back to templates and says so. An empty
    analysis that looks like a real one is the failure this project already had
    once.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Mapping

DEFAULT_MAX_TOKENS = 8192
DEFAULT_TIMEOUT_SECONDS = 120.0

# Reasoning is OFF by default, and that is a measured decision, not a preference.
#
# On 2026-10-31, the rnd_voc prompt against tokenhub/deepseek-v4-flash:
#   reasoning on,  max_tokens=20000 -> 35.5s, completion=2946 (2167 reasoning)
#   reasoning off, max_tokens=4000  ->  9.5s, completion= 670 (   0 reasoning)
#
# The agents do structured extraction against a schema they are handed; the
# reasoning trace buys nothing a reader of the JSON can see, and it triples
# latency while spending most of the token budget. Worse, reasoning tokens count
# against max_tokens, so a budget that looks ample returns JSON truncated
# mid-string -- `Unterminated string`, which is how the first attempt failed at
# both 700 and 4096. Turning it off removes the failure mode instead of raising
# the ceiling past it.
_REASONING_OFF = {"reasoning_effort": "none"}
_FENCE = re.compile(r"^\s*```(?:json)?\s*\n?(.*?)\n?\s*```\s*$", re.DOTALL)


class AgentLLMError(RuntimeError):
    """The model did not return usable JSON. Callers fall back to templates."""


@dataclass(frozen=True)
class AgentCompletion:
    """The subset of a completion the agents read: `.content`."""

    content: str
    model: str
    finish_reason: str
    usage: Mapping[str, Any]
    fenced: bool = False


def strip_code_fence(text: str) -> tuple[str, bool]:
    """Remove a markdown fence if the whole payload is wrapped in one.

    Returns (text, was_fenced). Models that emit a fence around otherwise valid
    JSON are common; the fence is presentation, so stripping it loses nothing.
    Text that merely contains a fence mid-body is left alone — that would be a
    model answering with prose and a code sample, which must fail parsing.
    """
    match = _FENCE.match(text or "")
    if match:
        return match.group(1).strip(), True
    return text, False


class OpenAICompatibleAgentClient:
    """Minimal JSON completion client for an OpenAI-compatible chat endpoint.

    Satisfies the interface the agents already call, so no agent file changes.
    """

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        disable_reasoning: bool = True,
        transport: Any = None,
    ) -> None:
        if not base_url or not model or not api_key:
            raise ValueError("agent_llm_config_incomplete")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.max_tokens = max_tokens
        self.timeout_seconds = timeout_seconds
        self.disable_reasoning = disable_reasoning
        self._transport = transport

    # ------------------------------------------------------------------ public

    def complete_json(
        self,
        *,
        phase: str,
        user_payload: Mapping[str, object],
        attempt_budget: object = None,
    ) -> AgentCompletion:
        messages = list((user_payload or {}).get("messages") or [])
        if not messages:
            raise AgentLLMError(f"{phase}: empty messages payload")

        body = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "temperature": 0.2,
            "stream": False,
            **(_REASONING_OFF if self.disable_reasoning else {}),
        }
        raw = self._post(body)

        try:
            payload = json.loads(raw)
        except ValueError as exc:
            raise AgentLLMError(f"{phase}: response was not JSON: {exc}") from exc

        choices = payload.get("choices") or []
        if len(choices) != 1:
            raise AgentLLMError(f"{phase}: expected exactly one choice, got {len(choices)}")

        choice = choices[0]
        finish_reason = str(choice.get("finish_reason") or "")
        content = str((choice.get("message") or {}).get("content") or "")

        # Truncation is the failure mode that produced an unterminated JSON
        # string in testing. Report it as truncation, not as bad formatting, so
        # the fix (raise max_tokens) is obvious.
        if finish_reason == "length":
            raise AgentLLMError(
                f"{phase}: output truncated at max_tokens={self.max_tokens} "
                f"(usage={payload.get('usage')})"
            )
        if not content.strip():
            raise AgentLLMError(f"{phase}: empty content, finish_reason={finish_reason!r}")

        content, fenced = strip_code_fence(content)
        try:
            # Models occasionally put a raw control character (often a newline)
            # inside a JSON string. Strict JSON rejects it, but the value is
            # recoverable; re-serialize so the agents' strict json.loads() sees
            # valid JSON instead of falling back to templates for the whole batch.
            parsed = json.loads(content, strict=False)
            content = json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))
        except ValueError as exc:
            raise AgentLLMError(f"{phase}: content is not valid JSON: {exc}") from exc

        return AgentCompletion(
            content=content,
            model=str(payload.get("model") or self.model),
            finish_reason=finish_reason,
            usage=payload.get("usage") or {},
            fenced=fenced,
        )

    # ----------------------------------------------------------------- private

    def _post(self, body: Mapping[str, object]) -> bytes:
        import urllib.error
        import urllib.request

        url = f"{self.base_url}/chat/completions"
        request = urllib.request.Request(
            url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "content-type": "application/json",
                "accept": "application/json",
            },
            method="POST",
        )
        if self._transport is not None:
            return self._post_via_transport(request)

        # No proxies: the same reason DeepSeekClient disables them. A corporate
        # or container proxy silently rewriting an LLM call is undiagnosable.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(request, timeout=self.timeout_seconds) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read()[:400].decode("utf-8", "replace")
            raise AgentLLMError(f"http_{exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise AgentLLMError(f"unreachable: {exc.reason}") from exc

    def _post_via_transport(self, request: Any) -> bytes:
        """Send through an injected transport, normalising its errors.

        An injected transport must fail the same way the real one does, or a test
        (or a caller with its own HTTP stack) would see a raw HTTPError while
        production sees AgentLLMError, and the caller's fallback would not fire.
        """
        import urllib.error

        try:
            return self._transport(request, self.timeout_seconds)
        except urllib.error.HTTPError as exc:
            body = exc.read() if hasattr(exc, "read") else b""
            detail = body[:400].decode("utf-8", "replace")
            raise AgentLLMError(f"http_{exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise AgentLLMError(f"unreachable: {exc.reason}") from exc


# Environment surface. Values live in deployment config, never in source.
ENV_BASE_URL = "AGENT_LLM_BASE_URL"
ENV_MODEL = "AGENT_LLM_MODEL"
ENV_API_KEY = "AGENT_LLM_API_KEY"
ENV_API_KEY_FILE = "AGENT_LLM_API_KEY_FILE"
ENV_MAX_TOKENS = "AGENT_LLM_MAX_TOKENS"
ENV_REASONING = "AGENT_LLM_REASONING"


def _read_key() -> str:
    direct = os.getenv(ENV_API_KEY, "").strip()
    if direct:
        return direct
    path = os.getenv(ENV_API_KEY_FILE, "").strip()
    if path:
        try:
            return open(path, encoding="utf-8").read().strip()
        except OSError:
            return ""
    return ""


def build_agent_client() -> OpenAICompatibleAgentClient | None:
    """Return a configured client, or None when the pipeline should stay offline.

    None is a legitimate answer: the pipeline then runs the deterministic
    template fallback and the morning card discloses `analysis_mode` as
    template_offline. Returning a half-configured client would be worse, because
    the card would claim LLM analysis it never received.
    """
    base_url = os.getenv(ENV_BASE_URL, "").strip()
    model = os.getenv(ENV_MODEL, "").strip()
    api_key = _read_key()
    if not (base_url and model and api_key):
        return None

    raw_max = os.getenv(ENV_MAX_TOKENS, "").strip()
    max_tokens = DEFAULT_MAX_TOKENS
    if raw_max:
        try:
            max_tokens = max(512, int(raw_max))
        except ValueError:
            pass

    # Off by default (see _REASONING_OFF). AGENT_LLM_REASONING=on turns the
    # trace back on for a deliberate experiment, with a budget that accounts for
    # it; it is not something to flip on a schedule.
    disable_reasoning = os.getenv(ENV_REASONING, "").strip().lower() not in ("on", "1", "true")

    return OpenAICompatibleAgentClient(
        base_url=base_url, model=model, api_key=api_key, max_tokens=max_tokens,
        disable_reasoning=disable_reasoning,
    )
