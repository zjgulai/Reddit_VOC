"""Reply-engine tests: one reply source for every Feishu entry point.

Four entry points previously carried near-identical keyword-branch reply
functions that had drifted (one lost the daily-report intent) and all quoted a
stale corpus figure (3,591 posts / 2026-10-26) that no production dataset
supports. These tests pin:

1. intent routing over slots (all four intents reachable),
2. release-backed corpus facts — injected profile is rendered verbatim, an
   unreachable release degrades to an explicit "unavailable" line, and no
   stale figure can come back,
3. every entry point delegates to the shared engine (import-level drift lock).
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import patch
import urllib.error
import unittest

from reddit_voc.reply_engine import (
    CorpusFacts,
    INTENTS,
    generate_agent_reply,
)

ROOT = Path(__file__).resolve().parents[1]

FACTS = CorpusFacts(
    posts=26330,
    comments=103012,
    data_as_of_utc="2026-11-04T23:00:00Z",
    release_id="reddit_voc_release_20260723_daily_v2",
)


def _reply(text: str) -> str:
    return generate_agent_reply(text, facts=FACTS)


class IntentRoutingTests(unittest.TestCase):
    def test_welcome_when_only_a_mention(self) -> None:
        reply = _reply("@_user_1")
        self.assertIn("您好！我是 Echo-Agent", reply)
        self.assertIn("26,330", reply)
        self.assertIn("103,012", reply)

    def test_all_four_intents_route(self) -> None:
        samples = {
            "content_strategy": "最近有什么好的选题",
            "product_engineering": "M5 的噪音抱怨，需要改款建议",
            "competitor": "和 Elvie 对比一下",
            "daily_report": "给我看看今天的日报",
        }
        for intent in INTENTS:
            reply = _reply(samples[intent["slot"]])
            self.assertIn(intent["body"].split("】")[0].replace("【", "【"), reply, intent["slot"])

    def test_daily_report_uses_release_backed_date(self) -> None:
        reply = _reply("今日动态")
        self.assertIn("2026-11-04 23:00", reply)
        self.assertIn("https://radar.luteos.com/dashboard", reply)
        # The stale hardcoded date must never come back.
        self.assertNotIn("2026-10-26", reply)

    def test_fallback_discloses_template_routing(self) -> None:
        reply = _reply("帮我写一首诗")
        self.assertIn("帮我写一首诗", reply)
        self.assertIn("模板路由", reply)
        # No implied corpus search.
        self.assertNotIn("已检索", reply)
        self.assertNotIn("已记录并正在检索", reply)

    def test_stale_corpus_figure_never_rendered(self) -> None:
        for text in ("", "选题", "随便聊聊", "日报"):
            self.assertNotIn("3,591", _reply(text))


class ReleaseFactsTests(unittest.TestCase):
    def test_unreachable_release_degrades_explicitly(self) -> None:
        def _boom(*args, **kwargs):
            raise urllib.error.URLError("network down")

        with patch("reddit_voc.reply_engine.urllib.request.urlopen", side_effect=_boom):
            # Welcome and fallback render the corpus line; intent bodies do not.
            welcome = generate_agent_reply("", use_cache=False)
            fallback = generate_agent_reply("帮我写一首诗", use_cache=False)
            daily = generate_agent_reply("今日日报", use_cache=False)
        self.assertIn("规模信息暂不可用", welcome)
        self.assertIn("规模信息暂不可用", fallback)
        self.assertNotIn("26,330", welcome)
        self.assertNotIn("3,591", fallback)
        # The daily-report intent degrades its date line explicitly.
        self.assertIn("未知（发布信息暂不可用）", daily)

    def test_zero_counts_do_not_imply_coverage(self) -> None:
        empty = CorpusFacts(posts=0, comments=0, data_as_of_utc="", release_id="")
        reply = generate_agent_reply("", facts=empty)
        self.assertIn("规模信息暂不可用", reply)


class EntryPointDelegationTests(unittest.TestCase):
    """Every entry point must route through the shared engine (source-level).

    Source assertions are the drift lock: module loading is not possible here
    (entry modules use relative imports and side-effectful startup checks), and
    the intent of the test is exactly "the file contains no private reply logic
    and no stale figure".
    """

    def test_ws_bot_module_delegates(self) -> None:
        source = (ROOT / "src/reddit_voc/feishu_ws_bot.py").read_text(encoding="utf-8")
        self.assertIn("from .reply_engine import generate_agent_reply", source)
        self.assertNotIn("3,591", source)

    def test_webhook_server_delegates(self) -> None:
        source = (ROOT / "src/reddit_voc/feishu_webhook_server.py").read_text(encoding="utf-8")
        self.assertIn("from .reply_engine import generate_agent_reply", source)
        self.assertNotIn("3,591", source)

    def test_prod_bot_script_delegates(self) -> None:
        source = (ROOT / "scripts/server_feishu_bot.py").read_text(encoding="utf-8")
        self.assertIn("from reddit_voc.reply_engine import generate_agent_reply", source)
        self.assertNotIn("3,591", source)

    def test_prod_ws_script_delegates(self) -> None:
        source = (ROOT / "scripts/server_feishu_ws.py").read_text(encoding="utf-8")
        self.assertIn("reply_engine", source)
        self.assertNotIn("3,591", source)
        # The leaked-secret default (caught 2026-10-29) must stay out of the repo.
        self.assertNotIn('os.getenv("FEISHU_APP_SECRET", "cli', source)

    def test_no_stale_hardcoded_corpus_figure_anywhere(self) -> None:
        offenders = []
        for rel in (
            "src/reddit_voc/feishu_ws_bot.py",
            "src/reddit_voc/feishu_webhook_server.py",
            "scripts/server_feishu_bot.py",
            "scripts/server_feishu_ws.py",
        ):
            if "3,591" in (ROOT / rel).read_text(encoding="utf-8"):
                offenders.append(rel)
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
