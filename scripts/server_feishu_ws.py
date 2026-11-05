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

logger = logging.getLogger("reddit_voc.feishu_ws")

# Credentials come from the environment only. A hardcoded fallback published the
# App Secret into a candidate commit (caught in pre-commit review 2026-10-29);
# the pattern is fail-fast-empty so a missing secret stops startup, never leaks.
APP_ID = os.getenv("FEISHU_APP_ID", "")
APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")
if not APP_ID or not APP_SECRET:
    raise SystemExit("FEISHU_APP_ID and FEISHU_APP_SECRET must be set in the environment")

# Initialize standard OpenAPI client for sending replies
lark_client = lark.Client.builder().app_id(APP_ID).app_secret(APP_SECRET).log_level(lark.LogLevel.INFO).build()


def generate_agent_reply(raw_text: str) -> str:
    """Delegate to the shared reply engine (single source of reply logic)."""
    from reddit_voc.reply_engine import generate_agent_reply as _engine_reply

    return _engine_reply(raw_text)


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
    resp = lark_client.im.v1.message.reply(req)
    if not resp.success():
        logger.error("Failed to reply message %s: code=%s, msg=%s", message_id, resp.code, resp.msg)
    else:
        logger.info("Successfully replied to message %s", message_id)


def start_ws_client() -> None:
    """Start the Feishu WebSocket long-connection event loop."""
    event_handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(handle_message)
        .build()
    )

    ws_client = lark.ws.Client(
        app_id=APP_ID,
        app_secret=APP_SECRET,
        event_handler=event_handler,
        log_level=lark.LogLevel.INFO,
    )
    logger.info("Connecting to Feishu via WebSocket Long Connection (no webhook required)...")
    ws_client.start()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    start_ws_client()
