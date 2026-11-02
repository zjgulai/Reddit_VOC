import importlib
import os
import unittest
from unittest.mock import patch

from reddit_voc.feishu_ws_bot import generate_agent_reply


class FeishuWsBotTests(unittest.TestCase):
    def test_import_is_safe_without_credentials(self) -> None:
        """pytest collection must not require production secrets."""
        with patch.dict(os.environ, {}, clear=True):
            module = importlib.reload(importlib.import_module("reddit_voc.feishu_ws_bot"))
            self.assertIsNone(module.lark_client)

    def test_credentials_fail_fast_when_missing(self) -> None:
        module = importlib.import_module("reddit_voc.feishu_ws_bot")
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(SystemExit):
                module._credentials()

    def test_credentials_are_read_from_environment(self) -> None:
        module = importlib.import_module("reddit_voc.feishu_ws_bot")
        with patch.dict(
            os.environ,
            {"FEISHU_APP_ID": "cli_test", "FEISHU_APP_SECRET": "secret_test"},
            clear=True,
        ):
            self.assertEqual(module._credentials(), ("cli_test", "secret_test"))
    def test_default_greeting(self) -> None:
        reply = generate_agent_reply("")
        self.assertIn("Echo-Agent", reply)
        self.assertIn("选题", reply)
        self.assertIn("改款", reply)

    def test_scout_intent(self) -> None:
        reply = generate_agent_reply("帮我推荐一个适合 TikTok 的选题脚本")
        self.assertIn("社媒爆款选题", reply)
        self.assertIn("Hook", reply)
        self.assertIn("视觉冲突", reply)

    def test_rnd_intent(self) -> None:
        reply = generate_agent_reply("用户关于吸奶器漏奶有什么硬件缺陷和改款建议？")
        self.assertIn("产品研发改款建议", reply)
        self.assertIn("根因分析", reply)
        self.assertIn("双唇", reply)

    def test_competitor_intent(self) -> None:
        reply = generate_agent_reply("Momcozy 和 Elvie 相比有什么优势？")
        self.assertIn("竞品对比", reply)
        self.assertIn("Elvie", reply)
        self.assertIn("1/3", reply)


if __name__ == "__main__":
    unittest.main()
