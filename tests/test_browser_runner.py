import json
import subprocess
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from reddit_voc import cli
from reddit_voc.browser_runner import BrowserHarnessRunner, CAPTURE_MARKER, build_browser_json_urls
from reddit_voc.browser_runner import BrowserJsonCaptureResult


class BrowserHarnessRunnerTests(unittest.TestCase):
    def test_capture_classifies_browser_json_text(self):
        def fake_run(*args, **kwargs):
            payload = {
                "page_url": "https://www.reddit.com/r/example/comments/abc/title/.json",
                "page_title": "json",
                "raw_text": '[{"kind":"Listing"}]',
            }
            return subprocess.CompletedProcess(args[0], 0, stdout=CAPTURE_MARKER + json.dumps(payload), stderr="")

        result = BrowserHarnessRunner(run=fake_run).capture_json_url(
            "https://www.reddit.com/r/example/comments/abc/title/.json"
        )

        self.assertTrue(result.is_usable_json)
        self.assertEqual(result.browser_status, "ok")
        self.assertFalse(result.provider_call)
        self.assertFalse(result.live_send)
        self.assertFalse(result.secrets_written)

    def test_capture_classifies_login_wall_text(self):
        def fake_run(*args, **kwargs):
            payload = {
                "page_url": "https://www.reddit.com/r/example/comments/abc/title/.json",
                "page_title": "login",
                "raw_text": "<html><body>Log in to continue</body></html>",
            }
            return subprocess.CompletedProcess(args[0], 0, stdout=CAPTURE_MARKER + json.dumps(payload), stderr="")

        result = BrowserHarnessRunner(run=fake_run).capture_json_url(
            "https://www.reddit.com/r/example/comments/abc/title/.json"
        )

        self.assertFalse(result.is_usable_json)
        self.assertEqual(result.browser_status, "login_required")
        self.assertEqual(result.blocked_reason, "html_login_wall")

    def test_capture_reports_harness_process_error(self):
        def fake_run(*args, **kwargs):
            return subprocess.CompletedProcess(args[0], 2, stdout="", stderr="boom")

        result = BrowserHarnessRunner(run=fake_run).capture_json_url(
            "https://www.reddit.com/r/example/comments/abc/title/.json"
        )

        self.assertFalse(result.is_usable_json)
        self.assertEqual(result.browser_status, "error")
        self.assertEqual(result.blocked_reason, "browser_harness_exit_2")

    def test_capture_retries_harness_process_error(self):
        calls = []

        def fake_run(*args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                return subprocess.CompletedProcess(args[0], 2, stdout="", stderr="boom")
            payload = {
                "page_url": "https://www.reddit.com/r/example/comments/abc/title/.json",
                "page_title": "json",
                "raw_text": '[{"kind":"Listing"}]',
            }
            return subprocess.CompletedProcess(args[0], 0, stdout=CAPTURE_MARKER + json.dumps(payload), stderr="")

        result = BrowserHarnessRunner(
            run=fake_run,
            max_attempts=2,
            retry_delay_seconds=0,
            sleep=lambda _: None,
        ).capture_json_url("https://www.reddit.com/r/example/comments/abc/title/.json")

        self.assertEqual(len(calls), 2)
        self.assertEqual(result.browser_status, "ok")
        self.assertEqual(result.attempt_count, 2)

    def test_capture_uses_explicit_cdp_env_and_reload(self):
        calls = []

        def fake_run(*args, **kwargs):
            calls.append((args[0], kwargs.get("env")))
            if args[0] == ["browser-harness", "--reload"]:
                return subprocess.CompletedProcess(args[0], 0, stdout="", stderr="")
            payload = {
                "page_url": "https://www.reddit.com/r/example/comments/abc/title/.json",
                "page_title": "json",
                "raw_text": '[{"kind":"Listing"}]',
            }
            return subprocess.CompletedProcess(args[0], 0, stdout=CAPTURE_MARKER + json.dumps(payload), stderr="")

        result = BrowserHarnessRunner(
            run=fake_run,
            env={"BU_CDP_URL": "http://127.0.0.1:9333", "BU_NAME": "reddit-voc-profile"},
            reload_before_capture=True,
        ).capture_json_url("https://www.reddit.com/r/example/comments/abc/title/.json")

        self.assertEqual(result.browser_status, "ok")
        self.assertEqual(calls[0][0], ["browser-harness", "--reload"])
        self.assertEqual(calls[1][0], ["browser-harness"])
        self.assertEqual(calls[1][1]["BU_CDP_URL"], "http://127.0.0.1:9333")
        self.assertEqual(calls[1][1]["BU_NAME"], "reddit-voc-profile")

    def test_capture_does_not_retry_login_wall(self):
        calls = []

        def fake_run(*args, **kwargs):
            calls.append(1)
            payload = {
                "page_url": "https://www.reddit.com/r/example/comments/abc/title/.json",
                "page_title": "login",
                "raw_text": "<html><body>Log in to continue</body></html>",
            }
            return subprocess.CompletedProcess(args[0], 0, stdout=CAPTURE_MARKER + json.dumps(payload), stderr="")

        result = BrowserHarnessRunner(
            run=fake_run,
            max_attempts=3,
            retry_delay_seconds=0,
            sleep=lambda _: None,
        ).capture_json_url("https://www.reddit.com/r/example/comments/abc/title/.json")

        self.assertEqual(len(calls), 1)
        self.assertEqual(result.browser_status, "login_required")

    def test_build_browser_json_urls_appends_json_suffix(self):
        self.assertEqual(
            build_browser_json_urls(
                [
                    "https://www.reddit.com/r/example/comments/abc/title/",
                    "https://www.reddit.com/r/example/comments/def/title/.json",
                ]
            ),
            [
                "https://www.reddit.com/r/example/comments/abc/title/.json",
                "https://www.reddit.com/r/example/comments/def/title/.json",
            ],
        )


class BrowserJsonSmokeCliTests(unittest.TestCase):
    def test_cli_writes_summary_for_json_error_object(self):
        class FakeRunner:
            def capture_json_url(self, url):
                return BrowserJsonCaptureResult(
                    target_url=url,
                    page_url=url,
                    page_title="error",
                    raw_text='{"message":"Forbidden","error":403}',
                    browser_status="ok",
                    blocked_reason=None,
                )

        with TemporaryDirectory() as tmp, patch("reddit_voc.cli.BrowserHarnessRunner", return_value=FakeRunner()):
            out_dir = Path(tmp) / "out"
            with redirect_stdout(StringIO()):
                rc = cli.main(
                    [
                        "run-browser-json-smoke",
                        "--database",
                        str(Path(tmp) / "smoke.sqlite3"),
                        "--output-dir",
                        str(out_dir),
                        "--run-id",
                        "bad_shape",
                        "--url",
                        "https://www.reddit.com/r/example/comments/abc/title/.json",
                    ]
                )

            summary = json.loads((out_dir / "bad_shape-browser-json-smoke-summary.json").read_text(encoding="utf-8"))
            self.assertEqual(rc, 1)
            self.assertEqual(summary["browser_status"], "error")
            self.assertEqual(summary["blocked_reason"], "unexpected_reddit_json_shape")
            self.assertFalse(summary["provider_call"])
            self.assertFalse(summary["live_send"])

    def test_cli_writes_summary_for_invalid_json_like_body(self):
        class FakeRunner:
            def capture_json_url(self, url):
                return BrowserJsonCaptureResult(
                    target_url=url,
                    page_url=url,
                    page_title="invalid",
                    raw_text="[not json",
                    browser_status="ok",
                    blocked_reason=None,
                )

        with TemporaryDirectory() as tmp, patch("reddit_voc.cli.BrowserHarnessRunner", return_value=FakeRunner()):
            out_dir = Path(tmp) / "out"
            with redirect_stdout(StringIO()):
                rc = cli.main(
                    [
                        "run-browser-json-smoke",
                        "--database",
                        str(Path(tmp) / "smoke.sqlite3"),
                        "--output-dir",
                        str(out_dir),
                        "--run-id",
                        "bad_json",
                        "--url",
                        "https://www.reddit.com/r/example/comments/abc/title/.json",
                    ]
                )

            summary = json.loads((out_dir / "bad_json-browser-json-smoke-summary.json").read_text(encoding="utf-8"))
            self.assertEqual(rc, 1)
            self.assertEqual(summary["browser_status"], "error")
            self.assertEqual(summary["blocked_reason"], "invalid_json_body")
            self.assertEqual(summary["counts"]["threads"], 0)

    def test_cli_passes_explicit_cdp_url_to_runner(self):
        class FakeRunner:
            def capture_json_url(self, url):
                return BrowserJsonCaptureResult(
                    target_url=url,
                    page_url=url,
                    page_title="login",
                    raw_text="Log in to your Reddit account",
                    browser_status="login_required",
                    blocked_reason="text_login_wall",
                )

        with TemporaryDirectory() as tmp, patch("reddit_voc.cli.BrowserHarnessRunner", return_value=FakeRunner()) as runner:
            out_dir = Path(tmp) / "out"
            with redirect_stdout(StringIO()):
                rc = cli.main(
                    [
                        "run-browser-json-smoke",
                        "--database",
                        str(Path(tmp) / "smoke.sqlite3"),
                        "--output-dir",
                        str(out_dir),
                        "--run-id",
                        "cdp_login_wall",
                        "--url",
                        "https://www.reddit.com/r/example/comments/abc/title/.json",
                        "--browser-cdp-url",
                        "http://127.0.0.1:9333",
                        "--browser-daemon-name",
                        "reddit-voc-profile",
                        "--max-attempts",
                        "2",
                        "--retry-delay-seconds",
                        "0",
                    ]
                )

            summary = json.loads((out_dir / "cdp_login_wall-browser-json-smoke-summary.json").read_text(encoding="utf-8"))
            self.assertEqual(rc, 1)
            self.assertEqual(runner.call_args.kwargs["env"]["BU_CDP_URL"], "http://127.0.0.1:9333")
            self.assertEqual(runner.call_args.kwargs["env"]["BU_NAME"], "reddit-voc-profile")
            self.assertTrue(runner.call_args.kwargs["reload_before_capture"])
            self.assertEqual(runner.call_args.kwargs["max_attempts"], 2)
            self.assertEqual(summary["browser_cdp_url"], "http://127.0.0.1:9333")
            self.assertEqual(summary["blocked_reason"], "text_login_wall")

    def test_cli_blocked_capture_marks_run_failed_for_status_tools(self):
        class FakeRunner:
            def capture_json_url(self, url):
                return BrowserJsonCaptureResult(
                    target_url=url,
                    page_url=url,
                    page_title="login",
                    raw_text="Log in to your Reddit account",
                    browser_status="login_required",
                    blocked_reason="text_login_wall",
                )

        with TemporaryDirectory() as tmp, patch("reddit_voc.cli.BrowserHarnessRunner", return_value=FakeRunner()):
            db = Path(tmp) / "smoke.sqlite3"
            out_dir = Path(tmp) / "out"
            with redirect_stdout(StringIO()):
                rc = cli.main(
                    [
                        "run-browser-json-smoke",
                        "--database",
                        str(db),
                        "--output-dir",
                        str(out_dir),
                        "--run-id",
                        "blocked_capture",
                        "--url",
                        "https://www.reddit.com/r/example/comments/abc/title/.json",
                    ]
                )

            status = cli.summarize_run_status(cli.VocStore(db), "blocked_capture")
            issue_summary = cli.build_run_issue_summary(status)
            self.assertEqual(rc, 1)
            self.assertEqual(status["status"], "failed")
            self.assertEqual(issue_summary["operational_state"], "attention")
            self.assertEqual(issue_summary["issues"][0]["code"], "run_failed")


if __name__ == "__main__":
    unittest.main()
