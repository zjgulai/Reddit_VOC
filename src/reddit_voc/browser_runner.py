from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from typing import Callable, Sequence

from .adapters import BrowserJsonAdapter


CAPTURE_MARKER = "__REDDIT_VOC_CAPTURE__"


@dataclass(frozen=True)
class BrowserJsonCaptureResult:
    target_url: str
    page_url: str | None
    page_title: str | None
    raw_text: str
    browser_status: str
    blocked_reason: str | None
    provider_call: bool = False
    live_send: bool = False
    secrets_written: bool = False
    attempt_count: int = 1

    @property
    def is_usable_json(self) -> bool:
        return self.browser_status == "ok"


RunCallable = Callable[..., subprocess.CompletedProcess[str]]
SleepCallable = Callable[[float], None]


class BrowserHarnessRunner:
    def __init__(
        self,
        *,
        command: str = "browser-harness",
        timeout_seconds: int = 45,
        max_attempts: int = 1,
        retry_delay_seconds: float = 1.0,
        env: dict[str, str] | None = None,
        reload_before_capture: bool = False,
        run: RunCallable = subprocess.run,
        sleep: SleepCallable = time.sleep,
    ) -> None:
        self.command = command
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max(1, max_attempts)
        self.retry_delay_seconds = max(0.0, retry_delay_seconds)
        self.env = {**os.environ, **env} if env else None
        self.reload_before_capture = reload_before_capture
        self.run = run
        self.sleep = sleep
        self.adapter = BrowserJsonAdapter()
        self._reloaded = False

    def capture_json_url(self, url: str) -> BrowserJsonCaptureResult:
        self._reload_daemon_if_needed()
        result: BrowserJsonCaptureResult | None = None
        for attempt in range(1, self.max_attempts + 1):
            result = self._capture_once(url, attempt_count=attempt)
            if not self._should_retry(result, attempt):
                return result
            self.sleep(self.retry_delay_seconds)
        if result is None:
            raise RuntimeError("browser capture loop did not run")
        return result

    def _capture_once(self, url: str, *, attempt_count: int) -> BrowserJsonCaptureResult:
        script = self._script_for_url(url)
        completed = self.run(
            [self.command],
            input=script,
            text=True,
            capture_output=True,
            timeout=self.timeout_seconds,
            check=False,
            env=self.env,
        )
        if completed.returncode != 0:
            return BrowserJsonCaptureResult(
                target_url=url,
                page_url=None,
                page_title=None,
                raw_text="",
                browser_status="error",
                blocked_reason=f"browser_harness_exit_{completed.returncode}",
                attempt_count=attempt_count,
            )

        payload = self._extract_payload(completed.stdout)
        raw_text = payload.get("raw_text", "")
        browser_status, blocked_reason = self.adapter.classify_browser_text(raw_text)
        return BrowserJsonCaptureResult(
            target_url=url,
            page_url=payload.get("page_url"),
            page_title=payload.get("page_title"),
            raw_text=raw_text,
            browser_status=browser_status,
            blocked_reason=blocked_reason,
            attempt_count=attempt_count,
        )

    def _should_retry(self, result: BrowserJsonCaptureResult, attempt: int) -> bool:
        if attempt >= self.max_attempts:
            return False
        return result.browser_status == "error" and (result.blocked_reason or "").startswith("browser_harness_exit_")

    def _reload_daemon_if_needed(self) -> None:
        if not self.reload_before_capture or self._reloaded:
            return
        self.run(
            [self.command, "--reload"],
            text=True,
            capture_output=True,
            timeout=self.timeout_seconds,
            check=False,
            env=self.env,
        )
        self._reloaded = True

    @staticmethod
    def _extract_payload(stdout: str) -> dict[str, str | None]:
        for line in reversed(stdout.splitlines()):
            if line.startswith(CAPTURE_MARKER):
                return json.loads(line.removeprefix(CAPTURE_MARKER))
        return {
            "page_url": None,
            "page_title": None,
            "raw_text": "",
        }

    @staticmethod
    def _script_for_url(url: str) -> str:
        escaped_url = json.dumps(url)
        marker = json.dumps(CAPTURE_MARKER)
        return f"""
import json
ensure_real_tab()
new_tab({escaped_url})
wait_for_load(15)
wait(2)
info = page_info()
raw_text = js('document.body ? document.body.innerText : ""') or ""
payload = {{
    "page_url": info.get("url"),
    "page_title": info.get("title"),
    "raw_text": raw_text,
}}
print({marker} + json.dumps(payload, ensure_ascii=False))
"""


def build_browser_json_urls(permalinks: Sequence[str]) -> list[str]:
    urls: list[str] = []
    for permalink in permalinks:
        base = permalink.rstrip("/")
        if base.endswith(".json"):
            urls.append(base)
        else:
            urls.append(base + "/.json")
    return urls
