from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import zipfile

from scripts.validate_insights_exports import (
    EXPECTED_FILES,
    InsightsExportsError,
    TEMPLATE_TOKEN,
    evidence_contract_for_url,
    render_callback_template,
    validate_callback,
    validate_downloads,
)


class InsightsExportsValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _write_downloads(self) -> None:
        (self.root / EXPECTED_FILES["csv"]).write_bytes(
            "\ufeff指标ID,指标,当前值,环比,同比,趋势\nRV-01,帖子观察量,12,10%,5%,up\n".encode("utf-8")
        )
        (self.root / EXPECTED_FILES["pdf"]).write_bytes(
            b"%PDF-1.7\n/Type /Page\n" + b"x" * 1_100 + b"\n%%EOF\n"
        )
        with zipfile.ZipFile(self.root / EXPECTED_FILES["pptx"], "w") as archive:
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr("ppt/presentation.xml", "<presentation/>")
            archive.writestr("ppt/slides/slide1.xml", "<a:t>Reddit VOC 指标</a:t>")
        with zipfile.ZipFile(self.root / EXPECTED_FILES["docx"], "w") as archive:
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr("word/document.xml", "<w:t>Reddit VOC 指标</w:t>")

    def test_template_binding_replaces_exact_token_without_process_env(self) -> None:
        source = self.root / "source.js"
        rendered = self.root / "rendered.js"
        source.write_text(
            f"(async (page) => {{ const outputDir = {TEMPLATE_TOKEN}; return outputDir; }})\n",
            encoding="utf-8",
        )
        digest = render_callback_template(source, rendered, self.root / "downloads")
        value = rendered.read_text(encoding="utf-8")
        self.assertNotIn(TEMPLATE_TOKEN, value)
        self.assertNotIn("process.env", value)
        self.assertIn(json.dumps(str(self.root / "downloads")), value)
        self.assertEqual(len(digest), 64)

    def test_evidence_grade_distinguishes_loopback_from_public_https(self) -> None:
        self.assertEqual(
            evidence_contract_for_url("http://127.0.0.1:18441"),
            ("local_loopback", "L2_local_container_readonly_browser_download_acceptance"),
        )
        self.assertEqual(
            evidence_contract_for_url("http://localhost:18441"),
            ("local_loopback", "L2_local_container_readonly_browser_download_acceptance"),
        )
        self.assertEqual(
            evidence_contract_for_url("https://reddit.example.test"),
            ("public_https", "L3_public_readonly_browser_download_acceptance"),
        )

    def test_non_loopback_http_cannot_be_classified(self) -> None:
        with self.assertRaisesRegex(InsightsExportsError, "base_url_https_required"):
            evidence_contract_for_url("http://reddit.example.test")

    def test_template_rejects_process_env_even_with_token(self) -> None:
        source = self.root / "source.js"
        source.write_text(
            f"const x = {TEMPLATE_TOKEN}; const y = process.env.BAD;\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(InsightsExportsError, "callback_template_contract_invalid"):
            render_callback_template(source, self.root / "out.js", self.root)

    def test_four_downloads_validate_structure_and_business_content(self) -> None:
        self._write_downloads()
        result = validate_downloads(self.root)
        self.assertEqual(set(result), {"csv", "pdf", "pptx", "docx"})
        self.assertEqual(result["csv"]["data_row_count"], 1)
        self.assertTrue(result["pptx"]["business_content_verified"])
        self.assertTrue(result["docx"]["business_content_verified"])
        self.assertGreaterEqual(result["pdf"]["page_marker_count"], 1)

    def test_unknown_download_file_fails_closed(self) -> None:
        self._write_downloads()
        (self.root / "unexpected.txt").write_text("unexpected", encoding="utf-8")
        with self.assertRaisesRegex(InsightsExportsError, "download_file_set_invalid"):
            validate_downloads(self.root)

    def test_callback_requires_release_and_zero_browser_failures(self) -> None:
        release_sha = "a" * 64
        release_id = "reddit_voc_release_fixture"
        callback = {
            "status": "passed",
            "route": "/dashboard/reports",
            "releaseSha256": release_sha,
            "releaseId": release_id,
            "reportCollection": "最新完整周期",
            "reportPeriod": "日报",
            "browserErrors": [],
            "sameOriginHttpFailures": [],
            "externalRequests": [],
            "downloads": {
                kind: {
                    "savedFilename": filename,
                    "suggestedFilename": f"current.{kind}",
                }
                for kind, filename in EXPECTED_FILES.items()
            },
        }
        validate_callback(
            callback,
            expected_release_sha256=release_sha,
            expected_release_id=release_id,
        )
        callback["externalRequests"] = ["https://example.invalid/"]
        with self.assertRaisesRegex(InsightsExportsError, "browser_callback_contract_invalid"):
            validate_callback(
                callback,
                expected_release_sha256=release_sha,
                expected_release_id=release_id,
            )


if __name__ == "__main__":
    unittest.main()
