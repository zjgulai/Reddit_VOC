"""Feishu Long Connection (WebSocket) Bot Service for Echo-Agent.

No public IP, no domain name, no Nginx, no SSL certificate required.
Connects directly to Feishu Open Platform over WSS.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    P2ImMessageReceiveV1,
    ReplyMessageRequest,
    ReplyMessageRequestBody,
)

from .reply_engine import generate_agent_reply

logger = logging.getLogger("reddit_voc.feishu_ws")

# Credentials come from the environment only. A hardcoded fallback published the
# App Secret into a candidate commit (caught in pre-commit review 2026-10-29);
# the pattern is fail-fast-empty so a missing secret stops startup, never leaks.
#
# The check runs at startup, not at import: importing this module must be safe
# for offline tests and for any process that only needs `generate_agent_reply`.
APP_ID = ""
APP_SECRET = ""
lark_client = None


def _credentials() -> tuple[str, str]:
    """Read credentials at the process boundary, never at module import."""
    app_id = os.getenv("FEISHU_APP_ID", "").strip()
    app_secret = os.getenv("FEISHU_APP_SECRET", "").strip()
    if not app_id or not app_secret:
        raise SystemExit(
            "FEISHU_APP_ID and FEISHU_APP_SECRET must be set in the environment"
        )
    return app_id, app_secret


def _client() -> "lark.Client":
    """Build the OpenAPI client on first use, after credentials are read."""
    global lark_client
    if lark_client is None:
        app_id, app_secret = _credentials()
        lark_client = (
            lark.Client.builder()
            .app_id(app_id)
            .app_secret(app_secret)
            .log_level(lark.LogLevel.INFO)
            .build()
        )
    return lark_client


def handle_message(data: P2ImMessageReceiveV1) -> None:
    """Callback when a message is received (direct or group @bot)."""
    message = data.event.message
    if message.message_type != "text":
        return

    try:
        content_obj = json.loads(message.content)
        user_text = content_obj.get("text", "")
    except Exception:
        user_text = ""

    message_id = message.message_id
    logger.info("Received message [%s]: %s", message_id, user_text)

    reply_content = generate_agent_reply(user_text)

    # Send threaded reply in Feishu
    req = (
        ReplyMessageRequest.builder()
        .message_id(message_id)
        .request_body(
            ReplyMessageRequestBody.builder()
            .msg_type("text")
            .content(json.dumps({"text": reply_content}, ensure_ascii=False))
            .build()
        )
        .build()
    )
    resp = _client().im.v1.message.reply(req)
    if not resp.success():
        logger.error("Failed to reply message %s: code=%s, msg=%s", message_id, resp.code, resp.msg)
    else:
        logger.info("Successfully replied to message %s", message_id)


def start_ws_client() -> None:
    """Start the Feishu WebSocket long-connection event loop."""
    app_id, app_secret = _credentials()
    event_handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(handle_message)
        .build()
    )

    ws_client = lark.ws.Client(
        app_id=app_id,
        app_secret=app_secret,
        event_handler=event_handler,
        log_level=lark.LogLevel.INFO,
    )
    logger.info("Connecting to Feishu via WebSocket Long Connection (no webhook required)...")
    ws_client.start()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    start_ws_client()
