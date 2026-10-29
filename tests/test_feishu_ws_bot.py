import unittest

from reddit_voc.feishu_ws_bot import generate_agent_reply


class FeishuWsBotTests(unittest.TestCase):
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
