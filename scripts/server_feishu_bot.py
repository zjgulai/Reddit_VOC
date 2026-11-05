#!/usr/bin/env python3
"""Production Feishu Bot Event Server for Echo-Agent.

Listens for:
1. URL Verification challenge from Feishu Open Platform.
2. im.message.receive_v1 events (messages and @Echo-Agent mentions).
3. Answers questions using local Multi-Agent intelligence (Scout, R&D, Competitor).
"""
from __future__ import annotations

import json
import logging
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("feishu_bot_service")

# Resolve project imports
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from reddit_voc.feishu_bot import FeishuBotClient
from reddit_voc.reply_engine import generate_agent_reply

# Credentials come from the environment only — no hardcoded fallback (see
# src/reddit_voc/feishu_ws_bot.py for the incident note).
APP_ID = os.getenv("FEISHU_APP_ID", "")
APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")
if not APP_ID or not APP_SECRET:
    raise SystemExit(
        "FEISHU_APP_ID and FEISHU_APP_SECRET must be set in the environment"
    )
PORT = int(os.getenv("FEISHU_PORT", "18342"))


class FeishuHandler(BaseHTTPRequestHandler):
    client = FeishuBotClient(app_id=APP_ID, app_secret=APP_SECRET)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("content-length", 0))
        body = self.rfile.read(length).decode("utf-8")
        try:
            data = json.loads(body)
        except Exception:
            self.send_response(400)
            self.end_headers()
            return

        # 1. Handle Feishu URL Verification challenge
        if data.get("type") == "url_verification":
            challenge = data.get("challenge")
            logger.info("Handling URL verification challenge")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"challenge": challenge}).encode("utf-8"))
            return

        # 2. Handle Message Event
        event = data.get("event", {})
        header = data.get("header", {})
        event_type = header.get("event_type") or event.get("type")

        if event_type == "im.message.receive_v1":
            message = event.get("message", {})
            message_type = message.get("message_type")
            message_id = message.get("message_id")

            if message_type == "text" and message_id:
                content_str = message.get("content", "{}")
                try:
                    text = json.loads(content_str).get("text", "")
                except Exception:
                    text = ""

                logger.info("Received user message: %s", text)
                reply = self._generate_agent_reply(text)
                try:
                    self.client.send_text_reply(message_id, reply)
                    logger.info("Sent reply to message %s", message_id)
                except Exception as exc:
                    logger.error("Failed to reply: %s", exc)

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"code": 0, "msg": "success"}')

    def _generate_agent_reply(self, raw_text: str) -> str:
        # Delegate to the shared reply engine (single source of reply logic).
        return generate_agent_reply(raw_text)


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", PORT), FeishuHandler)
    logger.info("Echo-Agent Feishu Bot Server started on port %d", PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Stopping server...")
        server.server_close()


if __name__ == "__main__":
    main()
