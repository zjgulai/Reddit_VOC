from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from reddit_voc.storage import SCHEMA
from webapp import app


class WebappPayloadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data_dir = self.root / "data"
        self.output_dir = self.root / "outputs"
        self.config_dir = self.root / "config"
        self.docs_dir = self.root / "docs"
        for path in [self.data_dir, self.output_dir, self.config_dir, self.docs_dir]:
            path.mkdir(parents=True)
        self._old_paths = (app.DATA_DIR, app.OUTPUT_DIR, app.CONFIG_DIR, app.DOCS_DIR, app.REPO_ROOT)
        app.DATA_DIR = self.data_dir
        app.OUTPUT_DIR = self.output_dir
        app.CONFIG_DIR = self.config_dir
        app.DOCS_DIR = self.docs_dir
        app.REPO_ROOT = self.root
        self.write_fixture_files()

    def tearDown(self) -> None:
        app.DATA_DIR, app.OUTPUT_DIR, app.CONFIG_DIR, app.DOCS_DIR, app.REPO_ROOT = self._old_paths
        self.temp.cleanup()

    def write_fixture_files(self) -> None:
        (self.root / ".env.example").write_text(
            "\n".join(
                [
                    "REDDIT_VOC_TIMEZONE=Asia/Shanghai",
                    "REDDIT_VOC_RUN_HOUR=07",
                    "REDDIT_VOC_REPORT_HOUR=08",
                    "REDDIT_VOC_COLLECTION_PROVIDER=tikhub",
                    "REDDIT_VOC_ENABLE_TIKHUB=0",
                    "REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND=0",
                ]
            ),
            encoding="utf-8",
        )
        (self.config_dir / "subreddits.yaml").write_text(
            """
default_window:
  timezone: Asia/Shanghai
  run_hour: 7
tiers:
  p0:
    - name: ExclusivelyPumping
      reason: Pumping-focused community.
""",
            encoding="utf-8",
        )
        (self.config_dir / "keywords.yaml").write_text(
            """
brand:
  momcozy:
    exact:
      - momcozy
products:
  momcozy:
    - M5
category:
  - wearable pump
competitors:
  - Elvie
""",
            encoding="utf-8",
        )
        (self.output_dir / "sample-daily-detail.csv").write_text(
            "\ufeff帖子 ID,帖子链接,标题中文,正文中文,评论整合中文,翻译状态\n"
            "p1,https://www.reddit.com/r/ExclusivelyPumping/comments/p1/example/,中文标题,中文正文,中文评论,done\n",
            encoding="utf-8",
        )
        db_path = self.data_dir / "sample.sqlite3"
        with sqlite3.connect(db_path) as conn:
            conn.executescript(SCHEMA)
            conn.execute(
                "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?)",
                ("run1", "partial", "2026-07-06T23:00:00+00:00", "2026-07-07T23:00:00+00:00", 0, 0),
            )
            conn.execute(
                """
                INSERT INTO reddit_threads VALUES (
                    'p1', 'run1', 'raw1', 'ExclusivelyPumping', 'Momcozy M5 leaking',
                    'Original body', 'https://www.reddit.com/r/ExclusivelyPumping/comments/p1/example/',
                    '2026-07-07T05:00:00+00:00', 3, 1, 1, 0, 'partial', 'Momcozy,M5', 'hash', '[]'
                )
                """
            )
            conn.execute(
                """
                INSERT INTO reddit_comments VALUES (
                    't1_c1', 'p1', 'run1', 'raw1', NULL, 'Comment body',
                    '2026-07-07T06:00:00+00:00', 2, 0, 0, 'leak', 'hash', 0
                )
                """
            )
            conn.execute(
                """
                INSERT INTO analysis_results VALUES (
                    'a1', 'run1', 'post', 'p1', 'local_rules_v1',
                    'negative', -0.7, 'leakage', 'medium', 0.8, '["leakage"]', 0
                )
                """
            )

    def test_dashboard_reads_sqlite_and_detail_translation(self) -> None:
        payload = app.build_dashboard_payload("latest")
        self.assertEqual(payload["totals"]["posts"], 1)
        self.assertEqual(payload["posts"][0]["title_zh"], "中文标题")
        self.assertEqual(payload["posts"][0]["comments_merged_zh"], "中文评论")
        self.assertEqual(payload["posts"][0]["sentiment_label_cn"], "负面")

    def test_settings_reflects_7am_8am_schedule(self) -> None:
        payload = app.build_settings_payload()
        self.assertEqual(payload["schedule"]["collection_time"], "07:00")
        self.assertEqual(payload["schedule"]["report_time"], "08:00")

    def test_artifact_path_rejects_traversal(self) -> None:
        self.assertIsNone(app.resolve_artifact_path("../ai_video.pem"))

    def test_artifact_path_supports_nested_files(self) -> None:
        media_dir = self.output_dir / "media"
        media_dir.mkdir()
        image = media_dir / "sample.png"
        image.write_bytes(b"\x89PNG\r\n\x1a\n")
        self.assertEqual(app.resolve_artifact_path("/media/sample.png"), image.resolve())

    def test_prepared_nested_artifact_and_top_level_projection_are_compatible(self) -> None:
        immutable = (
            self.output_dir
            / "prepared"
            / "run1"
            / ("20260713T030405678901Z-" + "a" * 32)
        )
        immutable.mkdir(parents=True)
        nested_csv = immutable / "run1-daily-detail.csv"
        nested_csv.write_text(
            "\ufeff帖子 ID,帖子链接,标题中文,正文中文,评论整合中文,翻译状态\n"
            "p2,https://www.reddit.com/r/x/comments/p2/,新中文标题,新中文正文,新中文评论,deepseek_validated\n",
            encoding="utf-8",
        )
        projection = self.output_dir / "run1-daily-detail.csv"
        projection.symlink_to(nested_csv.relative_to(self.output_dir))

        self.assertEqual(
            app.resolve_artifact_path(
                f"prepared/run1/{immutable.name}/run1-daily-detail.csv"
            ),
            nested_csv.resolve(),
        )
        translations = app.load_detail_translations()
        self.assertEqual(translations["p2"]["title_zh"], "新中文标题")
        records = app.artifact_records()
        self.assertIn("run1-daily-detail.csv", {record["name"] for record in records})

        before = nested_csv.read_bytes()
        replacement = immutable / "replacement.csv"
        replacement.write_bytes(b"replacement")
        projection.unlink()
        projection.symlink_to(replacement.relative_to(self.output_dir))
        self.assertEqual(nested_csv.read_bytes(), before)

    def test_artifact_path_rejects_symlink_escaping_outputs(self) -> None:
        outside = self.root / "outside.csv"
        outside.write_text("secret", encoding="utf-8")
        escape = self.output_dir / "escape.csv"
        escape.symlink_to(outside)
        self.assertIsNone(app.resolve_artifact_path("escape.csv"))


if __name__ == "__main__":
    unittest.main()
