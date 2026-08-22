import csv
import json
import sqlite3
from types import SimpleNamespace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from openpyxl import load_workbook

from reddit_voc import cli
from reddit_voc.dingtalk import DingTalkSendResult
from reddit_voc.daily_report import (
    DailyReportBlocked,
    DailyReportSource,
    build_daily_report,
    render_business_dingtalk_markdown,
    render_business_dingtalk_markdown_parts,
    render_prevalidated_daily_report,
    select_visible_daily_report_source,
    source_excerpt_v1,
    translate_to_chinese,
)
from reddit_voc.report_contracts import canonical_json_bytes
from reddit_voc.translation_pipeline import build_post_translation_bundle
from reddit_voc.storage import VocStore


class FakeTranslationResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


class DailyReportTests(unittest.TestCase):
    def test_libretranslate_provider_posts_expected_payload(self):
        captured = {}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            captured["body"] = json.loads(request.data.decode("utf-8"))
            return FakeTranslationResponse({"translatedText": "我喜欢这个 Momcozy 吸奶器。"})

        with patch.dict(
            "os.environ",
            {
                "LIBRETRANSLATE_BASE_URL": "https://translate.example",
                "LIBRETRANSLATE_API_KEY": "unit-test-key",
                "REDDIT_VOC_TRANSLATION_SOURCE": "auto",
                "REDDIT_VOC_TRANSLATION_TARGET": "zh",
                "REDDIT_VOC_TRANSLATION_TIMEOUT_SECONDS": "9",
            },
            clear=False,
        ), patch("reddit_voc.daily_report.urlopen", side_effect=fake_urlopen):
            result = translate_to_chinese("I like this Momcozy pump.", mode="libretranslate")

        self.assertEqual(result.text, "我喜欢这个 Momcozy 吸奶器。")
        self.assertEqual(result.status, "libretranslate")
        self.assertTrue(result.provider_call)
        self.assertEqual(captured["url"], "https://translate.example/translate")
        self.assertEqual(captured["timeout"], 9.0)
        self.assertEqual(captured["body"]["q"], "I like this Momcozy pump.")
        self.assertEqual(captured["body"]["source"], "auto")
        self.assertEqual(captured["body"]["target"], "zh")
        self.assertEqual(captured["body"]["format"], "text")
        self.assertEqual(captured["body"]["api_key"], "unit-test-key")

    def test_deepseek_translate_mode_posts_expected_payload(self):
        captured = {}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["auth"] = request.get_header("Authorization")
            captured["body"] = json.loads(request.data.decode("utf-8"))
            return FakeTranslationResponse(
                {
                    "choices": [
                        {"message": {"content": json.dumps({"zh": "我喜欢这个 Momcozy 吸奶器。"})}}
                    ]
                }
            )

        with patch.dict(
            "os.environ",
            {"DEEPSEEK_API_KEY": "sk-unit-test-key"},
            clear=False,
        ), patch("reddit_voc.daily_report.urlopen", side_effect=fake_urlopen):
            import reddit_voc.daily_report as dr
            dr._DEEPSEEK_TRANSLATE_CACHE.clear()
            result = translate_to_chinese("I like this Momcozy pump.", mode="deepseek")

        self.assertEqual(result.text, "我喜欢这个 Momcozy 吸奶器。")
        self.assertEqual(result.status, "deepseek")
        self.assertTrue(result.provider_call)
        self.assertEqual(captured["auth"], "Bearer sk-unit-test-key")
        self.assertIn("api.deepseek.com", captured["url"])
        body = captured["body"]
        self.assertEqual(body["temperature"], 0)
        self.assertEqual(body["response_format"], {"type": "json_object"})
        user_msg = next(m for m in body["messages"] if m["role"] == "user")
        self.assertEqual(user_msg["content"], "I like this Momcozy pump.")

    def test_deepseek_translate_mode_missing_key_returns_provider_missing_config(self):
        import reddit_voc.daily_report as dr
        dr._DEEPSEEK_TRANSLATE_CACHE.clear()
        env = {k: v for k, v in __import__("os").environ.items() if k != "DEEPSEEK_API_KEY"}
        with patch.dict("os.environ", env, clear=True):
            result = translate_to_chinese("Some text", mode="deepseek")
        self.assertEqual(result.status, "provider_missing_config")
        self.assertFalse(result.provider_call)

    def test_deepseek_translate_mode_provider_error_returns_error_status(self):
        from urllib.error import URLError
        import reddit_voc.daily_report as dr
        dr._DEEPSEEK_TRANSLATE_CACHE.clear()

        def fake_urlopen(request, timeout):
            raise URLError("connection refused")

        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "sk-test"}, clear=False), \
             patch("reddit_voc.daily_report.urlopen", side_effect=fake_urlopen):
            result = translate_to_chinese("Some text that fails", mode="deepseek")
        self.assertIn("provider_error", result.status)
        self.assertTrue(result.provider_call)

    def test_daily_report_uses_deepseek_for_body_and_comments(self):
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "voc.sqlite3"
            out = Path(tmp) / "out"
            run_id = "daily_report_deepseek_translation_test"
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
            unique_title = "A unique Momcozy pump title for DeepSeek. DS test."
            unique_body = "The Momcozy pump helped during a late night feed. DS test."
            unique_comment = "Momcozy was easier to clean than my older pump. DS test."
            with sqlite3.connect(db) as conn:
                conn.execute(
                    "UPDATE reddit_threads SET title = ?, selftext = ? WHERE run_id = ? AND post_id = ?",
                    (unique_title, unique_body, run_id, "1fixture"),
                )
                conn.execute(
                    "UPDATE reddit_comments SET body = ? WHERE run_id = ? AND comment_id = ?",
                    (unique_comment, run_id, "t1_c1"),
                )

            import reddit_voc.daily_report as dr
            dr._DEEPSEEK_TRANSLATE_CACHE.clear()

            def fake_urlopen(request, timeout):
                body = json.loads(request.data.decode("utf-8"))
                src = next(m["content"] for m in body["messages"] if m["role"] == "user")
                return FakeTranslationResponse(
                    {"choices": [{"message": {"content": json.dumps({"zh": "深度译文：" + src})}}]}
                )

            with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "sk-test"}, clear=False), \
                 patch("reddit_voc.daily_report.urlopen", side_effect=fake_urlopen):
                store = VocStore(db)
                result = build_daily_report(store, run_id=run_id, output_dir=out, translation_mode="deepseek")

            self.assertTrue(result.provider_call)
            self.assertIn(result.translation_status, {"translated", "deepseek"})
            with result.detail_csv.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            self.assertIn("深度译文：", rows[0]["标题中文"])
            self.assertIn("深度译文：", rows[0]["正文中文"])
            self.assertIn("深度译文：", rows[0]["评论整合中文"])

    def test_daily_report_uses_libretranslate_for_body_and_comments(self):
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "voc.sqlite3"
            out = Path(tmp) / "out"
            run_id = "daily_report_translation_provider_test"
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
            unique_body = "The Momcozy pump helped during a late night feed."
            unique_comment = "Momcozy was easier to clean than my older pump."
            with sqlite3.connect(db) as conn:
                conn.execute(
                    "UPDATE reddit_threads SET selftext = ? WHERE run_id = ? AND post_id = ?",
                    (unique_body, run_id, "1fixture"),
                )
                conn.execute(
                    "UPDATE reddit_comments SET body = ? WHERE run_id = ? AND comment_id = ?",
                    (unique_comment, run_id, "t1_c1"),
                )

            def fake_urlopen(request, timeout):
                payload = json.loads(request.data.decode("utf-8"))
                return FakeTranslationResponse({"translatedText": "译文：" + payload["q"]})

            with patch.dict(
                "os.environ",
                {"LIBRETRANSLATE_BASE_URL": "https://translate.example"},
                clear=False,
            ), patch("reddit_voc.daily_report.urlopen", side_effect=fake_urlopen):
                store = VocStore(db)
                result = build_daily_report(store, run_id=run_id, output_dir=out, translation_mode="libretranslate")

            self.assertTrue(result.provider_call)
            self.assertEqual(result.translation_status, "translated")
            with result.detail_csv.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            self.assertIn("译文：The Momcozy pump helped", rows[0]["正文中文"])
            self.assertIn("译文：Momcozy was easier to clean", rows[0]["评论整合中文"])

    def test_daily_report_builds_chinese_detail_table_and_insight_image(self):
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "voc.sqlite3"
            out = Path(tmp) / "out"
            run_id = "daily_report_test"
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

            store = VocStore(db)
            result = build_daily_report(store, run_id=run_id, output_dir=out)

            self.assertEqual(result.row_count, 1)
            self.assertEqual(result.comment_count, 2)
            self.assertFalse(result.provider_call)
            self.assertFalse(result.live_send)
            self.assertTrue(result.detail_csv.exists())
            self.assertTrue(result.detail_xlsx.exists())
            self.assertTrue(result.insight_png.exists())
            self.assertTrue(result.insight_html.exists())
            self.assertGreater(result.insight_png.stat().st_size, 1000)
            html = result.insight_html.read_text(encoding="utf-8")
            self.assertIn("核心摘要", html)
            self.assertNotIn("Executive Summary", html)
            self.assertIn("帖子核心字段表", html)
            self.assertIn("VOC 采集明细表", html)
            self.assertIn("Momcozy M5 leaking at work", html)
            self.assertIn("<summary>用户声音全文</summary>", html)
            self.assertIn("<summary>评论原文全文</summary>", html)
            self.assertIn('<summary>用户声音全文</summary><div class="full-text">I need a wearable pump', html)
            self.assertIn("My Momcozy M5 kept leaking and customer service was slow.", html)
            self.assertNotIn("【待授权翻译】", html)

            with result.detail_csv.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["标题中文"], "Momcozy M5 在工作时漏奶")
            self.assertIn("我需要一款上班时使用的可穿戴吸奶器", row["正文中文"])
            self.assertIn("[1] 评论ID=t1_c1", row["评论整合原文"])
            self.assertIn("[2] 评论ID=t1_c2", row["评论整合原文"])
            self.assertIn("我的 Momcozy M5 一直漏奶", row["评论整合中文"])
            self.assertIn("Elvie 更安静", row["评论整合中文"])
            self.assertIn(row["内容类型"], {"求助咨询", "吐槽/问题反馈", "售后/退换咨询", "竞品对比", "经验分享", "一般讨论"})
            self.assertIn(row["相关性校验"], {"强相关", "品牌相关", "品类相关", "竞品/品类线索", "待人工复核", "需排除"})
            self.assertIn("Momcozy", row["相关依据"])

            workbook = load_workbook(result.detail_xlsx)
            sheet = workbook.active
            self.assertEqual(sheet.title, "Momcozy Reddit VOC 日报")
            self.assertEqual(sheet.max_row, 2)
            headers = [cell.value for cell in sheet[1]]
            title_col = headers.index("标题中文") + 1
            self.assertEqual(sheet.cell(row=2, column=title_col).value, "Momcozy M5 在工作时漏奶")

    def test_business_dingtalk_markdown_caps_length_and_keeps_artifact_links(self):
        report = self._long_business_report()

        text = render_business_dingtalk_markdown(
            run_id="daily_collect_20260710_0700",
            report=report,
            status_summary={"counts": {"threads": report.row_count, "comments": report.comment_count}},
            artifact_base_url="https://reddit.lute-tlz-dddd.top/artifacts",
            max_bytes=4000,
        )

        self.assertLessEqual(len(text.encode("utf-8")), 4000)
        self.assertIn("因钉钉消息大小限制", text)
        self.assertIn("HTML 洞察报告", text)
        self.assertIn("采集明细表（Excel）", text)
        self.assertIn("采集明细表（CSV）", text)

    def test_business_dingtalk_markdown_can_split_into_two_messages(self):
        report = self._long_business_report()
        parts = render_business_dingtalk_markdown_parts(
            run_id="daily_collect_20260710_0700",
            report=report,
            status_summary={"counts": {"threads": report.row_count, "comments": report.comment_count}},
            artifact_base_url="https://reddit.lute-tlz-dddd.top/artifacts",
            max_bytes=4000,
            max_parts=2,
        )

        self.assertEqual(len(parts), 2)
        self.assertTrue(all(len(part.encode("utf-8")) <= 4000 for part in parts))
        self.assertIn("第 1/2 条", parts[0])
        self.assertIn("第 2/2 条", parts[1])
        self.assertIn("VOC 明细｜续", parts[1])
        self.assertIn("采集明细表（Excel）", parts[1])

    def _long_business_report(self):
        rows = []
        long_body = "Momcozy " + ("long user voice " * 120)
        long_comment = "[1] 评论ID=t1_c1 | 分数=1 | 层级=0\n原文：" + ("Momcozy comment detail " * 120)
        long_comment_zh = "[1] 评论ID=t1_c1 | 分数=1 | 层级=0\n中文：" + ("中文评论翻译 " * 120)
        for index in range(12):
            rows.append(
                {
                    "标题原文": f"Momcozy long VOC {index}",
                    "正文原文": long_body,
                    "正文中文": "这是一条很长的中文摘要。" * 80,
                    "评论整合原文": long_comment,
                    "评论整合中文": long_comment_zh,
                    "内容类型": "售后/退换咨询",
                    "情感标签": "负面",
                    "严重度": "中",
                    "主题": "竞品对比",
                    "痛点": "清洁/配件/电池/噪音",
                    "互动热度": 120 - index,
                    "评论数": 1,
                    "社区": "ExclusivelyPumping",
                    "帖子链接": f"https://www.reddit.com/r/ExclusivelyPumping/comments/post{index}/",
                    "相关性校验": "强相关",
                    "匹配关键词": "Momcozy",
                    "相关依据": "Momcozy",
                }
            )
        return SimpleNamespace(
            row_count=len(rows),
            comment_count=len(rows),
            report_summary={
                "report_date": "2026-07-10",
                "visible_post_count": len(rows),
                "sentiment_counts": {"负面": len(rows)},
                "content_type_counts": {"售后/退换咨询": len(rows)},
                "voc_posts": rows,
            },
            insight_html=Path("daily_collect_20260710_0700-insight-report.html"),
            detail_xlsx=Path("daily_collect_20260710_0700-daily-detail.xlsx"),
            detail_csv=Path("daily_collect_20260710_0700-daily-detail.csv"),
        )

    def test_daily_report_cli_writes_business_dingtalk_dry_run(self):
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "voc.sqlite3"
            out = Path(tmp) / "out"
            run_id = "daily_report_cli_test"
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
            with sqlite3.connect(db) as conn:
                conn.execute(
                    """
                    INSERT INTO reddit_threads(
                        post_id, run_id, raw_capture_id, subreddit, title, selftext, source_url,
                        created_at_utc, score, num_comments_reported, parsed_comment_count,
                        more_node_count, coverage_grade, matched_keywords, author_hash, media_urls
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "p_hot",
                        run_id,
                        "raw_hot",
                        "NewParents",
                        "Do I really need a baby bottle washer if I already have a dishwasher?",
                        (
                            "I already have a dishwasher, but I am wondering whether a Momcozy baby bottle washer "
                            "is worth it. I want to understand whether the cleaning, sterilizing, and drying flow "
                            "saves enough time during night feeds. This sentence must remain visible in the DingTalk "
                            "VOC block to prove the body is no longer truncated."
                        ),
                        "https://www.reddit.com/r/NewParents/comments/p_hot/bottle_washer/",
                        "2026-07-07T10:00:00+00:00",
                        120,
                        12,
                        0,
                        0,
                        "full",
                        "baby bottle washer,bottle washer",
                        "hash-hot",
                        "[]",
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO reddit_threads(
                        post_id, run_id, raw_capture_id, subreddit, title, selftext, source_url,
                        created_at_utc, score, num_comments_reported, parsed_comment_count,
                        more_node_count, coverage_grade, matched_keywords, author_hash, media_urls
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "p_category_only",
                        run_id,
                        "raw_category_only",
                        "unknown",
                        "Baby Bottle Washer, Sterilizer & Dryer All-in-One Cleaning USA",
                        "",
                        "https://www.reddit.com/r/unknown/comments/p_category_only/bottle_washer/",
                        "2026-07-07T11:00:00+00:00",
                        1,
                        0,
                        0,
                        0,
                        "full",
                        "baby bottle washer,bottle washer",
                        "hash-category-only",
                        "[]",
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO analysis_results(
                        analysis_id, run_id, source_type, source_id, analysis_version,
                        sentiment_label, sentiment_score, topic, severity, confidence,
                        pain_points, provider_call
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "a_category_only",
                        run_id,
                        "post",
                        "p_category_only",
                        "local_rules_v1",
                        "neutral",
                        0.0,
                        "product_evaluation",
                        "low",
                        0.6,
                        "[]",
                        0,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO analysis_results(
                        analysis_id, run_id, source_type, source_id, analysis_version,
                        sentiment_label, sentiment_score, topic, severity, confidence,
                        pain_points, provider_call
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "a_hot",
                        run_id,
                        "post",
                        "p_hot",
                        "local_rules_v1",
                        "neutral",
                        0.0,
                        "purchase_decision",
                        "medium",
                        0.8,
                        '["family_scenario"]',
                        0,
                    ),
                )
                conn.execute(
                    "UPDATE reddit_threads SET media_urls = ? WHERE run_id = ? AND post_id = ?",
                    (json.dumps(["https://example.com/static/mock-image.png"]), run_id, "p_hot"),
                )

            with patch("reddit_voc.daily_report._download_media_to_file") as mocked_download:
                mocked_download.return_value = "media/p_hot.png"
                self.assertEqual(
                    cli.main(
                        [
                            "build-daily-report",
                            "--database",
                            str(db),
                            "--output-dir",
                            str(out),
                            "--run-id",
                            run_id,
                            "--required-keyword",
                            "LL",
                            "--artifact-base-url",
                            "https://reddit.lute-tlz-dddd.top/artifacts",
                        ]
                    ),
                    0,
                )

            outbox = out / f"{run_id}-daily-dingtalk-dry-run.json"
            summary = out / f"{run_id}-daily-report-summary.json"
            body = json.loads(outbox.read_text(encoding="utf-8"))
            text = body["markdown"]["text"]
            self.assertEqual(body["msgtype"], "markdown")
            self.assertIn("LL", body["markdown"]["title"] + text)
            self.assertIn("Momcozy Reddit Post 日报", text)
            self.assertIn("今日判断", text)
            self.assertIn("VOC 明细｜按热度降序", text)
            self.assertIn("业务判断", text)
            self.assertIn("明细规则：仅展示帖子正文或评论中明确提及 Momcozy/momcozy 的帖子。", text)
            self.assertIn("标签：", text)
            self.assertIn("---", text)
            self.assertIn("品类提及", text)
            self.assertIn("品牌提及", text)
            self.assertIn("商品：Bottle Washer", text)
            self.assertIn("商品：M5", text)
            self.assertIn("帖子图片：", text)
            self.assertIn("![帖子图片 1](https://reddit.lute-tlz-dddd.top/artifacts/media/p_hot.png)", text)
            self.assertIn("[图片原图 1](https://example.com/static/mock-image.png)", text)
            self.assertIn("评论原文：", text)
            self.assertNotIn("评论摘录：", text)
            self.assertIn("This sentence must remain visible in the DingTalk VOC block to prove the body is no longer truncated.", text)
            self.assertIn("I need a wearable pump for pumping at work, but my Momcozy M5 is leaking into the collection cups.", text)
            self.assertIn("原文摘要：", text)
            self.assertIn("我需要一款上班时使用的可穿戴吸奶器", text)
            self.assertIn("完整英文原文见上方用户声音", text)
            self.assertIn("My Momcozy M5 kept leaking and customer service was slow.", text)
            self.assertIn("My Momcozy M5 kept leaking and customer service was slow. (中文翻译：我的 Momcozy M5 一直漏奶，而且客服响应很慢。)", text)
            self.assertIn("Elvie was quieter, but output was lower for me. (中文翻译：Elvie 更安静，但对我来说吸奶量更低。)", text)
            self.assertNotIn("Baby Bottle Washer, Sterilizer & Dryer All-in-One Cleaning USA", text)
            self.assertNotIn("帖子正文为空，建议结合标题、评论和原帖链接判断。", text)
            self.assertLess(text.index("Do I really need a baby bottle washer"), text.index("Momcozy M5 leaking at work"))
            self.assertIn(f"{run_id}-insight-report.html", text)
            self.assertIn(f"{run_id}-daily-detail.xlsx", text)
            self.assertIn(f"{run_id}-daily-detail.csv", text)
            self.assertIn(f"https://reddit.lute-tlz-dddd.top/artifacts/{run_id}-insight-report.html", text)
            self.assertNotIn("/var/folders/", text)
            self.assertNotIn("当日洞察长图", text)
            self.assertNotIn(f"{run_id}-insight-report-screenshot.png", text)
            self.assertIn("采集明细", text)
            self.assertNotIn("provider_call=", text)
            self.assertNotIn("live_send=", text)
            self.assertNotIn("运行状态", text)
            self.assertNotIn("翻译状态", text)

            result = json.loads(summary.read_text(encoding="utf-8"))
            self.assertEqual(result["row_count"], 2)
            self.assertFalse(result["provider_call"])
            self.assertFalse(result["live_send"])
            self.assertEqual(result["report_summary"]["voc_posts"][0]["帖子 ID"], "p_hot")
            self.assertEqual(result["report_summary"]["collected_post_count"], 3)
            self.assertEqual(result["report_summary"]["visible_post_count"], 2)
            self.assertIn("正文或评论中明确提及 Momcozy", result["report_summary"]["filter_rule"])

            with (out / f"{run_id}-daily-detail.csv").open("r", encoding="utf-8-sig", newline="") as handle:
                detail_rows = list(csv.DictReader(handle))
            self.assertEqual({row["帖子 ID"] for row in detail_rows}, {"1fixture", "p_hot"})

            with sqlite3.connect(db) as conn:
                row = conn.execute(
                    "SELECT mode, status, live_send, artifact_paths FROM delivery_previews WHERE delivery_id = ?",
                    (f"delivery_{run_id}_daily_report_dry_run",),
                ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], "dry_run")
            self.assertEqual(row[1], "created")
            self.assertEqual(row[2], 0)
            self.assertEqual(len(json.loads(row[3])), 4)


class PrevalidatedDailyReportTests(unittest.TestCase):
    def _source(self, *, long_fields=False):
        if long_fields:
            title = "T" * 29998 + "😀"
            body = "B" * 29993 + "Momcozy"
            comment = "C" * 29993 + "Momcozy😀"
        else:
            title = "Momcozy is loud 😀"
            body = "I do not like how loud my Momcozy pump is.\r\nSecond paragraph."
            comment = "Momcozy was worse than Elvie for me."
        posts = (
            {
                "post_id": "visible_body",
                "subreddit": "ExclusivelyPumping",
                "title": title,
                "selftext": body,
                "source_url": "https://www.reddit.com/r/ExclusivelyPumping/comments/visible_body/exact/",
                "created_at_utc": "2026-07-13T01:00:00+00:00",
                "score": 10,
                "coverage_grade": "full",
                "matched_keywords": "Momcozy",
            },
            {
                "post_id": "visible_comment",
                "subreddit": "NewParents",
                "title": "Category question only",
                "selftext": "No brand in this body.",
                "source_url": "https://www.reddit.com/r/NewParents/comments/visible_comment/exact/",
                "created_at_utc": "2026-07-13T02:00:00+00:00",
                "score": 5,
                "coverage_grade": "partial",
                "matched_keywords": "bottle washer",
            },
            {
                "post_id": "hidden_title_only",
                "subreddit": "NewParents",
                "title": "Momcozy appears only in the title",
                "selftext": "A category-only body.",
                "source_url": "https://www.reddit.com/r/NewParents/comments/hidden_title_only/exact/",
                "created_at_utc": "2026-07-13T03:00:00+00:00",
                "score": 999,
                "coverage_grade": "full",
                "matched_keywords": "Momcozy",
            },
        )
        comments = {
            "visible_body": (
                {
                    "comment_id": "c_body",
                    "post_id": "visible_body",
                    "body": comment,
                    "score": 2,
                    "depth": 0,
                    "source_url": "https://www.reddit.com/r/ExclusivelyPumping/comments/visible_body/exact/c_body/",
                },
            ),
            "visible_comment": (
                {
                    "comment_id": "c_visible",
                    "post_id": "visible_comment",
                    "body": "I bought a MOMCOZY washer and it helped.",
                    "score": 1,
                    "depth": 0,
                    "source_url": "https://www.reddit.com/r/NewParents/comments/visible_comment/exact/c_visible/",
                },
            ),
            "hidden_title_only": (),
        }
        return DailyReportSource(
            run={
                "run_id": "daily_collect_20260713_0700",
                "window_start_utc": "2026-07-12T23:00:00+00:00",
                "window_end_utc": "2026-07-13T23:00:00+00:00",
            },
            posts=posts,
            comments_by_post=comments,
            analysis_by_post={
                "visible_body": {
                    "sentiment_label": "negative",
                    "topic": "product_evaluation",
                    "severity": "medium",
                    "pain_points": ["operations"],
                },
                "hidden_title_only": {
                    "sentiment_label": "negative",
                    "topic": "customer_service",
                    "severity": "high",
                    "pain_points": ["support"],
                },
            },
            recent_threads=(),
        )

    def _translations(self, source):
        source = select_visible_daily_report_source(source)
        values = {}
        for post in source.posts:
            post_id = post["post_id"]
            values[f"post:{post_id}:title"] = {
                "visible_body": "Momcozy 噪音很大 😀",
                "visible_comment": "品类问题",
                "hidden_title_only": "只在标题出现 Momcozy",
            }[post_id]
            values[f"post:{post_id}:body"] = {
                "visible_body": "我不喜欢 Momcozy 吸奶器的噪音。\n第二段。",
                "visible_comment": "正文没有品牌。",
                "hidden_title_only": "一段仅涉及品类的正文。",
            }[post_id]
            for comment in source.comments_by_post.get(post_id, ()):
                values[f"comment:{comment['comment_id']}:body"] = (
                    "Momcozy 对我来说比 Elvie 更差。"
                    if comment["comment_id"] == "c_body"
                    else "我买了 MOMCOZY 清洗机，它很有帮助。"
                )
        return values

    def test_visibility_is_original_body_or_comment_only_and_precedes_provider_input(self):
        source = self._source()
        selected = select_visible_daily_report_source(source)
        self.assertEqual(
            [post["post_id"] for post in selected.posts],
            ["visible_body", "visible_comment"],
        )
        self.assertNotIn("hidden_title_only", selected.analysis_by_post)
        bundles = [
            build_post_translation_bundle(
                post,
                selected.comments_by_post[str(post["post_id"])],
            )
            for post in selected.posts
        ]
        stable_ids = {item.stable_id for bundle in bundles for item in bundle.items}
        self.assertFalse(any("hidden_title_only" in stable_id for stable_id in stable_ids))
        self.assertEqual(
            [post["post_id"] for post in select_visible_daily_report_source(source).posts],
            [post["post_id"] for post in select_visible_daily_report_source(source).posts],
        )
        with self.assertRaisesRegex(ValueError, "visibility_rule_version_unsupported"):
            select_visible_daily_report_source(source, visibility_rule_version="daily-visible-v2")
        with self.assertRaisesRegex(ValueError, "visibility_keyword_unsupported"):
            select_visible_daily_report_source(source, visibility_keyword="Other")

    def test_source_excerpt_is_utf8_safe_and_reserves_title_before_body_comments(self):
        excerpt = source_excerpt_v1(
            title="English title 😀",
            body="Body text " * 20,
            comments=["Comment text " * 20],
            max_bytes=47,
        )
        self.assertLessEqual(len(excerpt.encode("utf-8")), 47)
        self.assertTrue(excerpt.startswith("Title: English title"))
        excerpt.encode("utf-8").decode("utf-8")
        self.assertNotIn("Comment text", excerpt)

    def test_chinese_first_render_order_keyword_budget_and_fingerprint_noninterference(self):
        source = self._source()
        selected = select_visible_daily_report_source(source)
        translations = self._translations(source)
        with TemporaryDirectory() as tmp, patch(
            "reddit_voc.daily_report.translate_to_chinese",
            side_effect=AssertionError("legacy translator must not be called"),
        ), patch(
            "reddit_voc.daily_report.urlopen",
            side_effect=AssertionError("network must not be called"),
        ):
            result = render_prevalidated_daily_report(
                selected,
                translations=translations,
                output_dir=Path(tmp),
                artifact_version_url="https://files.example/prepared/run/version",
                dingtalk_max_bytes=3600,
                dingtalk_required_keyword="LL",
            )

        self.assertEqual(len(result.dingtalk_bodies), 1)
        body = result.dingtalk_bodies[0]
        self.assertEqual(set(body), {"msgtype", "markdown"})
        self.assertEqual(set(body["markdown"]), {"title", "text"})
        text = body["markdown"]["text"]
        self.assertIn("LL", body["markdown"]["title"] + text)
        self.assertLessEqual(len(canonical_json_bytes(body)), 3600)
        self.assertNotIn("webhook", json.dumps(body))
        self.assertNotIn("secret", json.dumps(body))
        self.assertNotIn("bundle_sha", json.dumps(body))
        first_url = source.posts[0]["source_url"]
        ordered = [
            "Momcozy 噪音很大 😀",
            "我不喜欢 Momcozy 吸奶器的噪音。",
            "Momcozy 对我来说比 Elvie 更差。",
            "业务判断：",
            "英文原文节选：",
            "Title: Momcozy is loud 😀",
            first_url,
        ]
        positions = [text.index(value) for value in ordered]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(text.count(first_url), 1)
        self.assertIn("完整英文原文与完整中文译文见附件", text)
        self.assertEqual(result.report.report_summary["visibility_rule_version"], "daily-visible-v1")
        self.assertEqual(result.report.report_summary["visibility_keyword"], "Momcozy")

        with TemporaryDirectory() as tmp:
            changed = render_prevalidated_daily_report(
                selected,
                translations=translations,
                output_dir=Path(tmp),
                artifact_version_url="https://files.example/prepared/run/version",
                dingtalk_max_bytes=3600,
                dingtalk_required_keyword="DIFFERENT",
            )
        self.assertNotEqual(
            result.report.report_summary["report_input_fingerprint"],
            changed.report.report_summary["report_input_fingerprint"],
        )
        self.assertEqual(
            result.report.report_summary["visible_post_ids"],
            changed.report.report_summary["visible_post_ids"],
        )
        self.assertEqual(
            {field.post_id for field in result.content_fields},
            {field.post_id for field in changed.content_fields},
        )

    def test_two_part_packing_and_fail_closed_size_limit(self):
        source = self._source()
        selected = select_visible_daily_report_source(source)
        translations = self._translations(source)
        translations["post:visible_body:body"] = "中文正文" * 20
        translations["comment:c_body:body"] = "中文评论" * 20
        translations["post:visible_comment:body"] = "另一段中文正文" * 20
        translations["comment:c_visible:body"] = "另一段中文评论" * 20
        with TemporaryDirectory() as tmp:
            result = render_prevalidated_daily_report(
                selected,
                translations=translations,
                output_dir=Path(tmp),
                artifact_version_url="https://files.example/prepared/run/version",
                dingtalk_max_bytes=2000,
                dingtalk_required_keyword="LL",
                dingtalk_max_parts=2,
            )
        self.assertEqual(len(result.dingtalk_bodies), 2)
        self.assertTrue(
            all(len(canonical_json_bytes(body)) <= 2000 for body in result.dingtalk_bodies)
        )
        self.assertTrue(
            all("LL" in body["markdown"]["title"] + body["markdown"]["text"] for body in result.dingtalk_bodies)
        )
        combined = "\n".join(body["markdown"]["text"] for body in result.dingtalk_bodies)
        for post in selected.posts:
            self.assertEqual(combined.count(post["source_url"]), 1)

        with TemporaryDirectory() as tmp, self.assertRaises(DailyReportBlocked) as raised:
            render_prevalidated_daily_report(
                selected,
                translations=translations,
                output_dir=Path(tmp),
                artifact_version_url="https://files.example/prepared/run/version",
                dingtalk_max_bytes=400,
                dingtalk_required_keyword="LL",
                dingtalk_max_parts=2,
            )
        self.assertEqual(raised.exception.reason_code, "dingtalk_body_too_large")

    def test_prevalidated_packing_omits_overflow_only_after_full_artifacts_exist(self):
        template = select_visible_daily_report_source(self._source()).posts[0]
        template_comment = select_visible_daily_report_source(
            self._source()
        ).comments_by_post["visible_body"][0]
        posts = []
        comments = {}
        analysis = {}
        translations = {}
        for index in range(7):
            post_id = f"overflow_{index}"
            comment_id = f"overflow_comment_{index}"
            posts.append(
                {
                    **template,
                    "post_id": post_id,
                    "title": f"Momcozy long translated title {index}",
                    "selftext": "Momcozy body text " * 24,
                    "source_url": (
                        "https://www.reddit.com/r/ExclusivelyPumping/comments/"
                        f"{post_id}/exact/"
                    ),
                    "score": 100 - index,
                }
            )
            comments[post_id] = (
                {
                    **template_comment,
                    "comment_id": comment_id,
                    "post_id": post_id,
                    "body": "Momcozy comment text " * 16,
                    "source_url": (
                        "https://www.reddit.com/r/ExclusivelyPumping/comments/"
                        f"{post_id}/exact/{comment_id}/"
                    ),
                },
            )
            analysis[post_id] = {
                "sentiment_label": "negative",
                "topic": "product_evaluation",
                "severity": "medium",
                "pain_points": ["operations"],
            }
            translations[f"post:{post_id}:title"] = f"Momcozy 中文长标题 {index}"
            translations[f"post:{post_id}:body"] = "完整中文正文 " * 40
            translations[f"comment:{comment_id}:body"] = "完整中文评论 " * 30
        source = DailyReportSource(
            run=self._source().run,
            posts=tuple(posts),
            comments_by_post=comments,
            analysis_by_post=analysis,
            recent_threads=(),
        )
        with TemporaryDirectory() as tmp:
            result = render_prevalidated_daily_report(
                source,
                translations=translations,
                output_dir=Path(tmp),
                artifact_version_url="https://files.example/prepared/run/version",
                dingtalk_max_bytes=5000,
                dingtalk_required_keyword="LL",
                dingtalk_max_parts=2,
            )
            html = result.report.insight_html.read_text(encoding="utf-8")
            with result.report.detail_csv.open(
                "r", encoding="utf-8-sig", newline=""
            ) as handle:
                rows = list(csv.DictReader(handle))

        self.assertEqual(len(result.dingtalk_bodies), 2)
        self.assertTrue(
            all(
                len(canonical_json_bytes(body)) <= 5000
                for body in result.dingtalk_bodies
            )
        )
        combined = "\n".join(
            body["markdown"]["text"] for body in result.dingtalk_bodies
        )
        self.assertIn("其余 VOC", combined)
        self.assertIn("已完成中文翻译", combined)
        self.assertIn("HTML 洞察报告与采集明细", combined)
        self.assertEqual(len(rows), 7)
        self.assertTrue(all(row["标题中文"] for row in rows))
        self.assertTrue(all(row["正文中文"] for row in rows))
        self.assertTrue(all(row["评论整合中文"] for row in rows))
        for index in range(7):
            self.assertIn(f"Momcozy 中文长标题 {index}", html)

    def test_html_csv_xlsx_round_trip_exact_source_translation_and_chunk_boundaries(self):
        source = self._source(long_fields=True)
        selected = select_visible_daily_report_source(source)
        selected = DailyReportSource(
            run=selected.run,
            posts=selected.posts[:1],
            comments_by_post={"visible_body": selected.comments_by_post["visible_body"]},
            analysis_by_post={"visible_body": selected.analysis_by_post["visible_body"]},
            recent_threads=(),
        )
        post = selected.posts[0]
        comment = selected.comments_by_post["visible_body"][0]
        translations = {
            "post:visible_body:title": "短中文标题",
            "post:visible_body:body": "短中文正文 Momcozy",
            "comment:c_body:body": "短中文评论 Momcozy",
        }
        with TemporaryDirectory() as tmp:
            result = render_prevalidated_daily_report(
                selected,
                translations=translations,
                output_dir=Path(tmp),
                artifact_version_url="https://files.example/prepared/run/version",
                dingtalk_max_bytes=3000,
                dingtalk_required_keyword="LL",
            )
            html = result.report.insight_html.read_text(encoding="utf-8")
            self.assertIn(post["title"], html)
            self.assertIn(post["selftext"], html)
            self.assertIn(comment["body"], html)
            self.assertIn("短中文标题", html)
            self.assertIn(post["source_url"], html)
            self.assertLess(html.index("短中文标题"), html.index(post["title"]))
            self.assertLess(html.index("短中文正文 Momcozy"), html.index(post["selftext"]))
            self.assertLess(html.index("短中文评论 Momcozy"), html.index(comment["body"]))

            with result.report.detail_csv.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                rows = list(reader)
            self.assertEqual(len(rows), 1)
            self.assertLess(reader.fieldnames.index("标题中文"), reader.fieldnames.index("标题原文"))
            self.assertLess(reader.fieldnames.index("正文中文"), reader.fieldnames.index("正文原文"))
            self.assertLess(
                reader.fieldnames.index("评论整合中文"),
                reader.fieldnames.index("评论整合原文"),
            )
            self.assertEqual(rows[0]["标题原文"], post["title"])
            self.assertEqual(rows[0]["标题中文"], "短中文标题")
            self.assertEqual(rows[0]["正文原文"], post["selftext"])
            self.assertEqual(rows[0]["正文中文"], "短中文正文 Momcozy")
            self.assertIn(comment["body"], rows[0]["评论整合原文"])
            self.assertIn("短中文评论 Momcozy", rows[0]["评论整合中文"])
            self.assertEqual(rows[0]["帖子链接"], post["source_url"])

            workbook = load_workbook(result.report.detail_xlsx, read_only=True)
            self.assertIn("content", workbook.sheetnames)
            self.assertIn("comments", workbook.sheetnames)
            detail_headers = [cell.value for cell in next(workbook["detail"].iter_rows())]
            self.assertLess(detail_headers.index("标题中文"), detail_headers.index("标题原文"))
            self.assertLess(detail_headers.index("正文中文"), detail_headers.index("正文原文"))
            reconstructed = {}
            part_counts = {}
            for sheet_name in ["content", "comments"]:
                sheet = workbook[sheet_name]
                headers = [cell.value for cell in next(sheet.iter_rows())]
                self.assertEqual(
                    headers,
                    [
                        "run_id",
                        "post_id",
                        "comment_id",
                        "field",
                        "language",
                        "part_index",
                        "part_count",
                        "text_chunk",
                    ],
                )
                for values in sheet.iter_rows(values_only=True):
                    row = dict(zip(headers, values))
                    key = (row["post_id"], row["comment_id"], row["field"], row["language"])
                    reconstructed.setdefault(key, []).append((row["part_index"], row["text_chunk"] or ""))
                    part_counts[key] = row["part_count"]
            rebuilt = {
                key: "".join(value for _, value in sorted(parts))
                for key, parts in reconstructed.items()
            }
            self.assertEqual(rebuilt[("visible_body", None, "title", "en")], post["title"])
            self.assertEqual(rebuilt[("visible_body", None, "body", "en")], post["selftext"])
            self.assertEqual(rebuilt[("visible_body", "c_body", "comment", "en")], comment["body"])
            self.assertEqual(rebuilt[("visible_body", None, "title", "zh")], "短中文标题")
            self.assertEqual(part_counts[("visible_body", None, "title", "en")], 1)
            self.assertEqual(part_counts[("visible_body", None, "body", "en")], 1)
            self.assertEqual(part_counts[("visible_body", "c_body", "comment", "en")], 2)

    def test_daily_report_prefetches_media_to_local_files_in_html(self):
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "voc.sqlite3"
            out = Path(tmp) / "out"
            run_id = "daily_report_media_test"
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

            with sqlite3.connect(db) as conn:
                conn.execute(
                    "UPDATE reddit_threads SET media_urls = ? WHERE run_id = ?",
                    (json.dumps(["https://example.com/static/mock-image.png"]), run_id),
                )

            with patch("reddit_voc.daily_report._download_media_to_file") as mocked_download:
                mocked_download.return_value = "media/dummy.png"
                store = VocStore(db)
                result = build_daily_report(store, run_id=run_id, output_dir=out)
                html = result.insight_html.read_text(encoding="utf-8")
                self.assertIn('src="media/dummy.png"', html)

    def test_daily_report_live_send_is_blocked_without_explicit_gate(self):
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "voc.sqlite3"
            out = Path(tmp) / "out"
            run_id = "daily_report_live_blocked_test"
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
                rc = cli.main(
                    [
                        "send-daily-report-live",
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

            self.assertEqual(rc, 1)
            mocked_send.assert_not_called()

    def test_daily_report_live_send_requires_artifact_base_url(self):
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "voc.sqlite3"
            out = Path(tmp) / "out"
            run_id = "daily_report_live_missing_artifact_url_test"
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
                {
                    "REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND": "1",
                    "DINGTALK_WEBHOOK_URL": "https://oapi.dingtalk.com/robot/send?access_token=unit",
                    "REDDIT_VOC_ARTIFACT_BASE_URL": "",
                },
                clear=False,
            ), patch("reddit_voc.cli.send_payload") as mocked_send:
                rc = cli.main(
                    [
                        "send-daily-report-live",
                        "--database",
                        str(db),
                        "--output-dir",
                        str(out),
                        "--run-id",
                        run_id,
                        "--required-keyword",
                        "LL",
                        "--authorize-live-send",
                    ]
                )

            self.assertEqual(rc, 1)
            mocked_send.assert_not_called()

    def test_daily_report_live_send_blocks_when_deepseek_translation_is_unavailable(self):
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "voc.sqlite3"
            out = Path(tmp) / "out"
            run_id = "daily_report_live_missing_deepseek_key_test"
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
            with sqlite3.connect(db) as conn:
                conn.execute(
                    "UPDATE reddit_threads SET selftext = ? WHERE run_id = ?",
                    ("Unique body that requires DeepSeek translation.", run_id),
                )
                conn.execute(
                    "UPDATE reddit_comments SET body = ? WHERE run_id = ?",
                    ("Unique comment that requires DeepSeek translation.", run_id),
                )

            with patch.dict(
                "os.environ",
                {
                    "REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND": "1",
                    "DINGTALK_WEBHOOK_URL": "https://oapi.dingtalk.com/robot/send?access_token=unit",
                },
                clear=True,
            ), patch(
                "reddit_voc.cli.send_payload",
                return_value=DingTalkSendResult(
                    status="sent",
                    http_status=200,
                    response_hash="sha256:unit",
                    response_text='{"errcode":0}',
                    live_send=True,
                ),
            ) as mocked_send:
                rc = cli.main(
                    [
                        "send-daily-report-live",
                        "--database",
                        str(db),
                        "--output-dir",
                        str(out),
                        "--run-id",
                        run_id,
                        "--translation-mode",
                        "deepseek",
                        "--required-keyword",
                        "LL",
                        "--artifact-base-url",
                        "https://reddit.lute-tlz-dddd.top/artifacts",
                        "--authorize-live-send",
                    ]
                )

            self.assertEqual(rc, 1)
            mocked_send.assert_not_called()

    def test_daily_report_live_send_records_delivery_with_mocked_transport(self):
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "voc.sqlite3"
            out = Path(tmp) / "out"
            run_id = "daily_report_live_mock_test"
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

            def fake_send_payload(*, webhook_url, payload, timeout_seconds):
                captured["webhook_url"] = webhook_url
                captured["payload"] = payload
                captured["timeout_seconds"] = timeout_seconds
                return DingTalkSendResult(
                    status="sent",
                    http_status=200,
                    response_hash="sha256:unit",
                    response_text='{"errcode":0}',
                    live_send=True,
                )

            with patch.dict(
                "os.environ",
                {
                    "REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND": "1",
                    "DINGTALK_WEBHOOK_URL": "https://oapi.dingtalk.com/robot/send?access_token=unit",
                },
                clear=False,
            ), patch("reddit_voc.cli.send_payload", side_effect=fake_send_payload):
                rc = cli.main(
                    [
                        "send-daily-report-live",
                        "--database",
                        str(db),
                        "--output-dir",
                        str(out),
                        "--run-id",
                        run_id,
                        "--required-keyword",
                        "LL",
                        "--artifact-base-url",
                        "https://reddit.lute-tlz-dddd.top/artifacts",
                        "--authorize-live-send",
                    ]
                )

            self.assertEqual(rc, 0)
            self.assertIn("LL", captured["payload"].body["markdown"]["title"] + captured["payload"].body["markdown"]["text"])
            self.assertNotIn("live_send=true", captured["payload"].body["markdown"]["text"])
            self.assertIn("Momcozy Reddit Post 日报", captured["payload"].body["markdown"]["text"])
            self.assertIn(f"{run_id}-insight-report.html", captured["payload"].body["markdown"]["text"])
            with sqlite3.connect(db) as conn:
                row = conn.execute(
                    "SELECT mode, status, live_send, artifact_paths FROM delivery_previews WHERE delivery_id = ?",
                    (f"delivery_{run_id}_daily_report_live",),
                ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], "live")
            self.assertEqual(row[1], "sent")
            self.assertEqual(row[2], 1)
            self.assertEqual(len(json.loads(row[3])), 4)
