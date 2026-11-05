"""Lightweight HTTP server for handling Feishu event callbacks and bot mentions."""
from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Mapping

from .agents import AgentBatchRunner
from .feishu_bot import FeishuBotClient
from .reply_engine import generate_agent_reply

logger = logging.getLogger("reddit_voc.feishu_webhook")


class FeishuWebhookHandler(BaseHTTPRequestHandler):
    """Processes Feishu URL verification challenge and message events."""

    bot_client: FeishuBotClient | None = None
    batch_runner: AgentBatchRunner | None = None

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("content-length", 0))
        body = self.rfile.read(length).decode("utf-8")
        try:
            data = json.loads(body)
        except Exception:
            self.send_response(400)
            self.end_headers()
            return

        # 1. Feishu URL Verification Handshake
        if data.get("type") == "url_verification":
            challenge = data.get("challenge")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"challenge": challenge}).encode("utf-8"))
            return

        # 2. Event Callback Dispatch
        event = data.get("event", {})
        event_type = data.get("header", {}).get("event_type") or event.get("type")

        # Handle message received (at_bot or direct message)
        if event_type == "im.message.receive_v1":
            message = event.get("message", {})
            message_type = message.get("message_type")
            message_id = message.get("message_id")
            if message_type == "text" and message_id and self.bot_client:
                content_str = message.get("content", "{}")
                try:
                    text = json.loads(content_str).get("text", "").strip()
                except Exception:
                    text = ""

                # Answer the user query using Multi-Agent intelligence
                reply_text = self._handle_bot_question(text)
                try:
                    self.bot_client.send_text_reply(message_id, reply_text)
                except Exception as exc:
                    logger.exception("Failed to reply to message: %s", exc)

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"code": 0, "msg": "success"}')

    def _handle_bot_question(self, user_query: str) -> str:
        """Delegate to the shared reply engine (single source of reply logic)."""
        return generate_agent_reply(user_query)


def create_feishu_server(
    host: str = "0.0.0.0",
    port: int = 18342,
    bot_client: FeishuBotClient | None = None,
) -> ThreadingHTTPServer:
    """Create a configured ThreadingHTTPServer instance for Feishu callbacks."""
    handler = FeishuWebhookHandler
    handler.bot_client = bot_client
    return ThreadingHTTPServer((host, port), handler)
