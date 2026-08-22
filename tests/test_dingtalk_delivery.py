import json
import sqlite3
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.parse import parse_qsl, urlsplit

from reddit_voc import cli, dingtalk
from reddit_voc.dingtalk import (
    DingTalkTransportError,
    canonical_dingtalk_body_bytes,
    sign_url,
    send_payload_bytes,
    validate_webhook_url,
)


class DingTalkDeliveryTests(unittest.TestCase):
    def test_webhook_url_is_exact_canonical_dingtalk_endpoint(self):
        canonical = "https://oapi.dingtalk.com/robot/send?access_token=unit"
        self.assertEqual(validate_webhook_url(canonical), canonical)

        invalid = [
            "http://oapi.dingtalk.com/robot/send?access_token=unit",
            "https://OAPI.dingtalk.com/robot/send?access_token=unit",
            "https://oapi.dingtalk.com./robot/send?access_token=unit",
            "https://evil.example/robot/send?access_token=unit",
            "https://oapi.dingtalk.com.evil.example/robot/send?access_token=unit",
            "https://evil@oapi.dingtalk.com/robot/send?access_token=unit",
            "https://oapi.dingtalk.com:443/robot/send?access_token=unit",
            "https://127.0.0.1/robot/send?access_token=unit",
            "https://[::1]/robot/send?access_token=unit",
            "https://xn--dingtalk-9za.example/robot/send?access_token=unit",
            "https://oapi.dingtalk.com/robot/send/?access_token=unit",
            "https://oapi.dingtalk.com//robot/send?access_token=unit",
            "https://oapi.dingtalk.com/robot/%73end?access_token=unit",
            "https://oapi.dingtalk.com/robot/send",
            "https://oapi.dingtalk.com/robot/send?ACCESS_TOKEN=unit",
            "https://oapi.dingtalk.com/robot/send?access_token=",
            "https://oapi.dingtalk.com/robot/send?access_token=unit&access_token=unit",
            "https://oapi.dingtalk.com/robot/send?access_token=unit&extra=1",
            "https://oapi.dingtalk.com/robot/send?access_token=unit;extra=1",
            "https://oapi.dingtalk.com/robot/send?access_token=unit%0aextra",
            "https://oapi.dingtalk.com/robot/send?access_token=unit#fragment",
            "https://oapi.dingtalk.com\\robot\\send?access_token=unit",
            "https://oapi.dingtalk。com/robot/send?access_token=unit",
            "https://oapi.dingtalk.com/robot/send?access_token=unit\n",
            "https://oapi.dingtalk.com/robot/send?access_token=" + "a" * 257,
        ]
        for candidate in invalid:
            with self.subTest(candidate=candidate), self.assertRaisesRegex(
                ValueError, "dingtalk_webhook_invalid"
            ):
                validate_webhook_url(candidate)

    def test_signing_preserves_endpoint_and_adds_only_owned_query_fields(self):
        signed = sign_url(
            "https://oapi.dingtalk.com/robot/send?access_token=unit",
            "synthetic-unit-secret",
            timestamp_ms=1_700_000_000_000,
        )
        parsed = urlsplit(signed)
        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(parsed.netloc, "oapi.dingtalk.com")
        self.assertEqual(parsed.path, "/robot/send")
        self.assertEqual(
            [key for key, _ in parse_qsl(parsed.query, keep_blank_values=True)],
            ["access_token", "timestamp", "sign"],
        )

    def test_transport_opener_disables_redirects_and_environment_proxies(self):
        redirect_handlers = [
            handler
            for handler in dingtalk._DINGTALK_OPENER.handlers
            if isinstance(handler, dingtalk._NoRedirectHandler)
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
            for handler in dingtalk._DINGTALK_OPENER.handlers
            if handler.__class__.__name__ == "ProxyHandler"
        ]
        # Passing an explicit empty ProxyHandler suppresses urllib's default
        # environment-derived handler; an empty handler exposes no open method
        # and therefore is intentionally absent from the installed chain.
        self.assertEqual(proxy_handlers, [])

    def test_invalid_webhook_blocks_before_attempt_reservation_and_transport(self):
        frozen = canonical_dingtalk_body_bytes(
            {"msgtype": "markdown", "markdown": {"title": "LL", "text": "中文"}}
        )
        sink_calls = []
        with patch("reddit_voc.dingtalk.urlopen") as mocked_open:
            with self.assertRaisesRegex(
                DingTalkTransportError, "dingtalk_webhook_invalid"
            ) as raised:
                send_payload_bytes(
                    webhook_url="https://evil.example/robot/send?access_token=unit",
                    body_bytes=frozen,
                    request_start_sink=lambda: sink_calls.append(True),
                )
        self.assertFalse(raised.exception.external_attempt_made)
        self.assertEqual(sink_calls, [])
        mocked_open.assert_not_called()

    def test_exact_byte_transport_calls_start_sink_immediately_before_urlopen(self):
        body = {
            "msgtype": "markdown",
            "markdown": {"title": "LL 日报", "text": "中文在前，English excerpt after"},
        }
        frozen = canonical_dingtalk_body_bytes(body)
        events = []
        captured = {}

        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self, size=-1):
                events.append("read")
                return b'{"errcode":0,"errmsg":"ok"}'

        def sink():
            events.append("sink")

        def fake_urlopen(request, timeout):
            events.append("urlopen")
            captured["data"] = request.data
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            return FakeResponse()

        with patch("reddit_voc.dingtalk.urlopen", side_effect=fake_urlopen):
            result = send_payload_bytes(
                webhook_url="https://oapi.dingtalk.com/robot/send?access_token=unit",
                body_bytes=frozen,
                timeout_seconds=7,
                request_start_sink=sink,
            )

        self.assertEqual(events[:2], ["sink", "urlopen"])
        self.assertEqual(captured["data"], frozen)
        self.assertEqual(result.status, "sent")
        self.assertTrue(result.external_attempt_made)
        self.assertTrue(result.live_send)

    def test_byte_transport_failures_preserve_request_start_boundary(self):
        frozen = canonical_dingtalk_body_bytes(
            {"msgtype": "markdown", "markdown": {"title": "LL", "text": "中文"}}
        )
        sink_calls = []

        class NonJsonResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self, size=-1):
                return b"not-json"

        with patch("reddit_voc.dingtalk.urlopen", return_value=NonJsonResponse()):
            with self.assertRaises(DingTalkTransportError) as raised:
                send_payload_bytes(
                    webhook_url="https://oapi.dingtalk.com/robot/send?access_token=unit",
                    body_bytes=frozen,
                    request_start_sink=lambda: sink_calls.append(True),
                )
        self.assertTrue(raised.exception.external_attempt_made)
        self.assertEqual(sink_calls, [True])

        with patch("reddit_voc.dingtalk.urlopen") as mocked_open:
            with self.assertRaises(DingTalkTransportError) as raised:
                send_payload_bytes(
                    webhook_url="https://oapi.dingtalk.com/robot/send?access_token=unit",
                    body_bytes=b'{"msgtype":"text"}',
                    request_start_sink=lambda: sink_calls.append(False),
                )
        self.assertFalse(raised.exception.external_attempt_made)
        mocked_open.assert_not_called()

    def test_byte_transport_requires_http_200_and_business_errcode_zero(self):
        frozen = canonical_dingtalk_body_bytes(
            {"msgtype": "markdown", "markdown": {"title": "LL", "text": "中文"}}
        )

        class UnexpectedStatusResponse:
            status = 202

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self, size=-1):
                return b'{"errcode":0,"errmsg":"ok"}'

        with patch(
            "reddit_voc.dingtalk.urlopen", return_value=UnexpectedStatusResponse()
        ), self.assertRaisesRegex(
            DingTalkTransportError, "dingtalk_http_status_invalid"
        ) as raised:
            send_payload_bytes(
                webhook_url="https://oapi.dingtalk.com/robot/send?access_token=unit",
                body_bytes=frozen,
                request_start_sink=lambda: None,
            )
        self.assertTrue(raised.exception.external_attempt_made)

    def test_dingtalk_dry_run_links_exports_without_live_send(self):
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "voc.sqlite3"
            out = Path(tmp) / "out"
            run_id = "dingtalk_dry_run_test"

            self.assertEqual(
                cli.main(
                    [
                        "run-adapter-fixture-loop",
                        "--database",
                        str(db),
                        "--output-dir",
                        str(out),
                        "--run-id",
                        run_id,
                    ]
                ),
                0,
            )
            self.assertEqual(
                cli.main(
                    [
                        "build-dingtalk-dry-run",
                        "--database",
                        str(db),
                        "--output-dir",
                        str(out),
                        "--run-id",
                        run_id,
                    ]
                ),
                0,
            )

            outbox = out / f"{run_id}-dingtalk-dry-run.json"
            body = json.loads(outbox.read_text(encoding="utf-8"))
            text = body["markdown"]["text"]

            self.assertEqual(body["msgtype"], "markdown")
            self.assertIn(f"{run_id}-posts.jsonl", text)
            self.assertIn(f"{run_id}-comments.jsonl", text)
            self.assertIn(f"{run_id}-analysis.jsonl", text)
            self.assertIn(f"{run_id}-posts.csv", text)
            self.assertIn(f"{run_id}-comments.csv", text)
            self.assertIn(f"{run_id}-analysis.csv", text)
            self.assertIn("## Details", text)
            self.assertIn("[Post 1fixture](https://www.reddit.com/r/ExclusivelyPumping/comments/1fixture/momcozy_m5_leaking_at_work/)", text)
            self.assertIn("[Comment t1_c1](https://www.reddit.com/r/ExclusivelyPumping/comments/1fixture/momcozy_m5_leaking_at_work/c1/)", text)
            self.assertIn("sentiment=negative", text)
            self.assertIn("provider_call=false", text)
            self.assertIn("live_send=false", text)

            with sqlite3.connect(db) as conn:
                row = conn.execute(
                    "SELECT mode, status, live_send, artifact_paths FROM delivery_previews WHERE run_id = ?",
                    (run_id,),
                ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], "dry_run")
            self.assertEqual(row[1], "created")
            self.assertEqual(row[2], 0)
            artifact_paths = json.loads(row[3])
            self.assertEqual(len(artifact_paths), 6)

    def test_dingtalk_artifacts_can_use_configured_base_url(self):
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "voc.sqlite3"
            out = Path(tmp) / "out"
            run_id = "dingtalk_artifact_url_test"

            cli.main(
                [
                    "run-adapter-fixture-loop",
                    "--database",
                    str(db),
                    "--output-dir",
                    str(out),
                    "--run-id",
                    run_id,
                ]
            )
            self.assertEqual(
                cli.main(
                    [
                        "build-dingtalk-dry-run",
                        "--database",
                        str(db),
                        "--output-dir",
                        str(out),
                        "--run-id",
                        run_id,
                        "--artifact-base-url",
                        "https://files.example/reddit-voc",
                    ]
                ),
                0,
            )

            outbox = out / f"{run_id}-dingtalk-dry-run.json"
            text = json.loads(outbox.read_text(encoding="utf-8"))["markdown"]["text"]
            self.assertIn(f"[{run_id}-analysis.csv](https://files.example/reddit-voc/{run_id}-analysis.csv)", text)
            self.assertNotIn("/var/folders/", text)

    def test_live_send_is_blocked_without_explicit_gate(self):
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "voc.sqlite3"
            out = Path(tmp) / "out"
            run_id = "dingtalk_live_blocked_test"
            cli.main(
                [
                    "run-adapter-fixture-loop",
                    "--database",
                    str(db),
                    "--output-dir",
                    str(out),
                    "--run-id",
                    run_id,
                ]
            )

            with patch.dict(
                "os.environ",
                {"DINGTALK_WEBHOOK_URL": "https://oapi.dingtalk.com/robot/send?access_token=unit"},
                clear=False,
            ), patch("reddit_voc.cli.send_payload") as mocked_send:
                stream = StringIO()
                with redirect_stdout(stream):
                    rc = cli.main(
                        [
                            "send-dingtalk-live",
                            "--database",
                            str(db),
                            "--output-dir",
                            str(out),
                            "--run-id",
                            run_id,
                            "--required-keyword",
                            "LL",
                        ]
                    )

            result = json.loads(stream.getvalue())
            self.assertEqual(rc, 1)
            self.assertEqual(result["status"], "blocked")
            self.assertFalse(result["live_send"])
            mocked_send.assert_not_called()

    def test_live_send_uses_keyword_and_records_delivery_with_mocked_transport(self):
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "voc.sqlite3"
            out = Path(tmp) / "out"
            run_id = "dingtalk_live_mock_test"
            cli.main(
                [
                    "run-adapter-fixture-loop",
                    "--database",
                    str(db),
                    "--output-dir",
                    str(out),
                    "--run-id",
                    run_id,
                ]
            )

            captured = {}

            class FakeResponse:
                status = 200

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

                def read(self, size=-1):
                    return b'{"errcode":0,"errmsg":"ok"}'

            def fake_urlopen(request, timeout):
                captured["url"] = request.full_url
                captured["timeout"] = timeout
                captured["body"] = json.loads(request.data.decode("utf-8"))
                return FakeResponse()

            with patch.dict(
                "os.environ",
                {
                    "REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND": "1",
                    "DINGTALK_WEBHOOK_URL": "https://oapi.dingtalk.com/robot/send?access_token=unit",
                    "DINGTALK_REQUIRED_KEYWORD": "LL",
                },
                clear=False,
            ), patch("reddit_voc.dingtalk.urlopen", side_effect=fake_urlopen):
                stream = StringIO()
                with redirect_stdout(stream):
                    rc = cli.main(
                        [
                            "send-dingtalk-live",
                            "--database",
                            str(db),
                            "--output-dir",
                            str(out),
                            "--run-id",
                            run_id,
                            "--authorize-live-send",
                        ]
                    )

            result = json.loads(stream.getvalue())
            text = captured["body"]["markdown"]["text"]
            title = captured["body"]["markdown"]["title"]

            self.assertEqual(rc, 0)
            self.assertEqual(result["status"], "sent")
            self.assertTrue(result["live_send"])
            self.assertTrue(result["required_keyword_present"])
            self.assertIn("LL", f"{title}\n{text}")
            self.assertNotIn("access_token", json.dumps(result))

            with sqlite3.connect(db) as conn:
                row = conn.execute(
                    "SELECT mode, status, live_send FROM delivery_previews WHERE run_id = ?",
                    (run_id,),
                ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], "live")
            self.assertEqual(row[1], "sent")
            self.assertEqual(row[2], 1)
            summary = cli.summarize_run_status(cli.VocStore(db), run_id)
            self.assertTrue(summary["live_send"])

    def test_live_send_error_does_not_echo_webhook(self):
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "voc.sqlite3"
            out = Path(tmp) / "out"
            run_id = "dingtalk_live_error_test"
            cli.main(
                [
                    "run-adapter-fixture-loop",
                    "--database",
                    str(db),
                    "--output-dir",
                    str(out),
                    "--run-id",
                    run_id,
                ]
            )

            def fake_send(**kwargs):
                raise RuntimeError("sanitized transport problem")

            with patch.dict(
                "os.environ",
                {
                    "REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND": "1",
                    "DINGTALK_WEBHOOK_URL": "https://oapi.dingtalk.com/robot/send?access_token=unit",
                    "DINGTALK_REQUIRED_KEYWORD": "LL",
                },
                clear=False,
            ), patch("reddit_voc.cli.send_payload", side_effect=fake_send):
                stream = StringIO()
                with redirect_stdout(stream):
                    rc = cli.main(
                        [
                            "send-dingtalk-live",
                            "--database",
                            str(db),
                            "--output-dir",
                            str(out),
                            "--run-id",
                            run_id,
                            "--authorize-live-send",
                        ]
                    )

            result_text = stream.getvalue()
            result = json.loads(result_text)
            self.assertEqual(rc, 1)
            self.assertEqual(result["status"], "send_error")
            self.assertEqual(result["error_type"], "RuntimeError")
            self.assertFalse(result["live_send"])
            self.assertNotIn("access_token", result_text)


if __name__ == "__main__":
    unittest.main()
