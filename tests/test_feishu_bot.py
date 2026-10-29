import json
import unittest
from unittest.mock import MagicMock, patch

from reddit_voc.feishu_bot import FeishuBotClient, build_feishu_daily_report_card


class FeishuBotTests(unittest.TestCase):
    def test_build_feishu_daily_report_card(self) -> None:
        card = build_feishu_daily_report_card(
            title="Momcozy VOC 测试日报",
            markdown_content="# 今日要闻\n发现漏奶反馈 3 条",
            run_id="run_test_001",
        )
        self.assertEqual(card["header"]["title"]["content"], "📊 Momcozy VOC 测试日报")
        self.assertEqual(card["elements"][0]["content"], "# 今日要闻\n发现漏奶反馈 3 条")
        self.assertIn("run_test_001", card["elements"][2]["elements"][0]["content"])

    @patch("urllib.request.urlopen")
    def test_get_tenant_access_token(self, mock_urlopen) -> None:
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "code": 0,
            "msg": "ok",
            "tenant_access_token": "test_token_123",
            "expire": 7200,
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_response

        client = FeishuBotClient(app_id="cli_test", app_secret="secret_test")
        token = client.get_tenant_access_token()
        self.assertEqual(token, "test_token_123")


if __name__ == "__main__":
    unittest.main()
