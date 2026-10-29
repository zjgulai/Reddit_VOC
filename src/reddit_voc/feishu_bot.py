"""Feishu (Lark) Bot client and event handler for Echo-Agent."""
from __future__ import annotations

import json
import logging
import urllib.request
from typing import Any, Mapping

logger = logging.getLogger("reddit_voc.feishu")

DEFAULT_FEISHU_HOST = "https://open.feishu.cn"


class FeishuBotClient:
    """Handles communication with the Feishu Open Platform API."""

    def __init__(self, app_id: str, app_secret: str, base_url: str = DEFAULT_FEISHU_HOST) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self.base_url = base_url.rstrip("/")

    def get_tenant_access_token(self) -> str:
        """Fetch a fresh tenant access token."""
        url = f"{self.base_url}/open-apis/auth/v3/tenant_access_token/internal"
        payload = json.dumps({"app_id": self.app_id, "app_secret": self.app_secret}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("code") != 0:
            raise RuntimeError(f"Feishu token error: {data.get('msg')}")
        return str(data["tenant_access_token"])

    def send_interactive_card(self, receive_id: str, card: Mapping[str, Any], *, receive_id_type: str = "chat_id") -> dict[str, Any]:
        """Send an interactive card message to a chat or user."""
        token = self.get_tenant_access_token()
        url = f"{self.base_url}/open-apis/im/v1/messages?receive_id_type={receive_id_type}"
        payload = json.dumps({
            "receive_id": receive_id,
            "msg_type": "interactive",
            "content": json.dumps(card, ensure_ascii=False),
        }).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Authorization": f"Bearer {token}",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def send_text_reply(self, message_id: str, text: str) -> dict[str, Any]:
        """Reply directly to a specific message thread."""
        token = self.get_tenant_access_token()
        url = f"{self.base_url}/open-apis/im/v1/messages/{message_id}/reply"
        payload = json.dumps({
            "msg_type": "text",
            "content": json.dumps({"text": text}, ensure_ascii=False),
        }).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Authorization": f"Bearer {token}",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))


def build_feishu_daily_report_card(
    *,
    title: str,
    markdown_content: str,
    run_id: str,
) -> dict[str, Any]:
    """Construct an interactive card payload for the VOC daily report."""
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"📊 {title}"},
            "template": "blue",
        },
        "elements": [
            {
                "tag": "markdown",
                "content": markdown_content,
            },
            {"tag": "hr"},
            {
                "tag": "note",
                "elements": [
                    {
                        "tag": "plain_text",
                        "content": f"🤖 Echo-Agent 自动推送 · Run ID: {run_id} · 群内 @Echo-Agent 随时交互",
                    }
                ],
            },
        ],
    }
