from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest
from urllib.error import URLError
from urllib.request import urlopen

from scripts.run_insights_e2e import (
    DEFAULT_RUNNER,
    InsightsE2EError,
    ROUTES,
    VIEWPORTS,
    canonical_bytes,
    execute_e2e,
    file_sha256,
    tree_inventory,
)


class FakeRunner:
    def __init__(self, result: dict[str, object]) -> None:
        self.result = result
        self.commands: list[list[str]] = []
        self.open_url: str | None = None

    def __call__(
        self, command: list[str] | tuple[str, ...], env: dict[str, str], timeout: float
    ) -> subprocess.CompletedProcess[str]:
        args = list(command)
        self.commands.append(args)
        if args[-1] == "--version":
            return subprocess.CompletedProcess(args, 0, "Version 0.1.17\n", "")
        if "open" in args:
            self.open_url = args[-1]
            return subprocess.CompletedProcess(args, 0, "opened\n", "")
        if "run-code" in args:
            return subprocess.CompletedProcess(args, 0, json.dumps(self.result), "")
        if args[-1] == "close":
            return subprocess.CompletedProcess(args, 0, "closed\n", "")
        return subprocess.CompletedProcess(args, 1, "", "unexpected command")


class InsightsE2ERunnerTests(unittest.TestCase):
    def test_browser_callbacks_pin_v3_business_language_and_casebook(self) -> None:
        root = Path(__file__).resolve().parents[1]
        callback = (root / "scripts/playwright_insights_e2e.js").read_text(encoding="utf-8")
        exports = (root / "scripts/playwright_insights_exports.js").read_text(encoding="utf-8")
        for marker in (
            "Momcozy 品牌健康四维雷达",
            "radarGridType === 'circle'",
            "dashboardContract.formulaStates.length === 5",
            "postVocCount: 27, totalVocCount: 142",
            "postVocCount: 145, totalVocCount: 1275",
            "postVocCount: 239, totalVocCount: 2099",
            "2026-04-25 至 2026-07-23",
            "scopeBarText.includes('9,252')",
            "scopeBarText.includes('1,865')",
            "personaCardCount === 8",
            "408 次 Momcozy 画像赋值",
            "2,830 次母婴品类语境赋值",
            "themeStates.length === 4",
            "GEO 优化机会",
            "comparison_decision_posts === 115",
            "keyValue: '344'",
            "不支持确认 Momcozy 使用机器人",
            "bg-[#17212B]",
            "Momcozy Reddit VOC 洞察",
            "历史采集完整性：数据所有者确认100%",
            "当日治理口径 Momcozy 新帖",
            "periodScopePresent",
            "reports-history-select-and-deep-link",
            "historyRequestCount === 1",
            "state.indicatorCount === state.expectedIndicatorCount",
            "state.helpButtonCount === state.indicatorCount",
            "data-report-trend=\"up\"",
            "data-report-trend=\"down\"",
            "stroke === '#E95A76'",
            "stroke === '#00A86B'",
            "参考案例",
            "运营闭环",
            "待复核",
            "洞察|证据|行动|监测|复盘",
            "8e79fe8c86e08e60b693ca93f3ca6560476bec53a979c67ed8120d00ec121126",
            "quarterBinding?.public_manifest_sha256",
        ):
            self.assertIn(marker, callback)
        self.assertIn("availablePeriodRegionCount === 1", callback)
        self.assertIn("expectedHistoricalPeriodOptionCount: periodLabel === '日报' ? 15 : 13", callback)
        self.assertIn("state.historicalPeriodOptionCount === state.expectedHistoricalPeriodOptionCount", callback)
        self.assertIn("state.latestCompleteSelected", callback)
        self.assertIn("state.historyContractVisible", callback)
        self.assertIn("previousOptionSignature", callback)
        self.assertIn("requireChangedSignature", callback)
        self.assertNotIn("states.length === 6", callback)
        self.assertNotIn("report-current-daily", exports)
        self.assertIn("report-latest-complete-daily", exports)
        self.assertIn("reportCollection: '最新完整周期'", exports)
        self.assertIn("选择历史报告周期", exports)
        self.assertIn("selectOption('current')", exports)

    def test_default_npm_exec_contract_forwards_cli_flags_after_separator(self) -> None:
        self.assertEqual(DEFAULT_RUNNER[-2:], ("--", "playwright-cli"))

    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.dist = self.root / "candidate/frontend/dist"
        self.dist.mkdir(parents=True)
        (self.dist / "index.html").write_text("<html><body>fixture</body></html>\n", encoding="utf-8")
        pointer_path = self.dist / "data/reddit-voc/current-release.json"
        pointer_path.parent.mkdir(parents=True)
        self.release_id = "reddit_voc_release_fixture_123"
        self.release_sha = "a" * 64
        self.dataset_versions = {
            "base": "reddit_voc_site_snapshot_fixture",
            "insights": "reddit_voc_insights_fixture",
            "reports": "reddit_voc_reports_fixture",
            "personas": "reddit_voc_personas_fixture",
        }
        pointer = {
            "schema_version": "reddit_voc_current_release_v1",
            "release_id": self.release_id,
            "datasets": {
                key: {"dataset_version": value}
                for key, value in self.dataset_versions.items()
            },
            "boundaries": {
                "login_required": False,
                "collector_isolation_required": True,
                "case_gallery_stock_preserved": True,
            },
        }
        pointer_path.write_bytes(canonical_bytes(pointer))
        source_casebook = (
            Path(__file__).resolve().parents[1]
            / "ref/UI/momcozy-reddit-workbench/public/data/reddit-voc"
            / "reddit_voc_casebook_20260716_public_a1"
        )
        shutil.copytree(
            source_casebook,
            self.dist
            / "data/reddit-voc/reddit_voc_casebook_20260716_public_a1",
        )
        inventory = tree_inventory(self.dist)
        release = {
            "schema_version": "reddit_voc_insights_site_release_v2",
            "release_sha256": self.release_sha,
            "authentication_enabled": False,
            "dataset_versions": self.dataset_versions,
            "current_release": {
                "path": "data/reddit-voc/current-release.json",
                "release_id": self.release_id,
                "sha256": file_sha256(pointer_path),
            },
            "file_count": len(inventory),
            "files": inventory,
        }
        self.release_manifest = self.root / "candidate/frontend/container-release/release-manifest.json"
        self.release_manifest.parent.mkdir(parents=True)
        self.release_manifest.write_bytes(canonical_bytes(release))
        self.release_manifest_sha = file_sha256(self.release_manifest)
        self.script = self.root / "callback.js"
        self.script.write_text("(async () => ({status: 'passed'}))\n", encoding="utf-8")
        self.script_sha = file_sha256(self.script)
        self.receipt = self.root / "candidate/frontend/final/browser-e2e-receipt.json"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _result(self) -> dict[str, object]:
        rows = []
        for viewport in VIEWPORTS:
            for route in ROUTES:
                rows.append(
                    {
                        "viewport": viewport,
                        "route": route,
                        "finalPath": route,
                        "status": 200,
                        "requiredTextPresent": True,
                        "horizontalOverflow": False,
                        "passwordInputs": 0,
                        "loginControls": [],
                    }
                )
        return {
            "status": "passed",
            "routes": rows,
            "release": {
                "releaseSha256": self.release_sha,
                "releaseId": self.release_id,
                "releasePointerSha256": file_sha256(
                    self.dist / "data/reddit-voc/current-release.json"
                ),
                "datasetVersions": self.dataset_versions,
                "noLogin": True,
                "collectorIsolation": True,
            },
            "dashboard": {
                "missionImageAbsent": True,
                "circularRadarAndFiveClickableFormulas": True,
                "threeUrlBackedRangesExact": True,
                "dualAxisTrendExact": True,
                "executiveDigestPresent": True,
            },
            "insights": {
                "quarterWindowAndCountsExact": True,
                "eightPersonaGroupsAndQuarterAssignmentsExact": True,
                "fourUrlBackedThemeTabsExact": True,
                "geoAndAutomationCountsExact": True,
                "automationAttributionBoundaryVisible": True,
                "caseReferencesMethodOnly": True,
                "controlledEvidence": True,
                "legacyDarkPanelsAbsent": True,
            },
            "reports": [
                {"collection": "最新完整周期", "period": period, "legacyTermsAbsent": True}
                for period in ("日报", "周报", "月报")
            ],
            "cases": {
                "threeViews": True,
                "referenceDefaultEligible": 33,
                "reviewOnly": 17,
                "operationsDossiers": 1,
                "internalFiveStageDrawer": True,
            },
            "casebook": {
                "relativeRoot": "data/reddit-voc/reddit_voc_casebook_20260716_public_a1",
                "manifestSha256": "8e79fe8c86e08e60b693ca93f3ca6560476bec53a979c67ed8120d00ec121126",
                "dataSha256": "5ad81e7af5f9744332baacd0a87ac947f1097894f4ef27c6aab692b0f90b249c",
                "dossierCount": 1,
                "externalNavigation": False,
            },
            "browserErrors": [],
            "sameOriginHttpFailures": [],
            "externalRequests": [],
        }

    def _execute(self, runner: FakeRunner) -> tuple[str, str, dict[str, object]]:
        return execute_e2e(
            dist_root=self.dist,
            release_manifest_path=self.release_manifest,
            expected_release_manifest_sha256=self.release_manifest_sha,
            expected_release_sha256=self.release_sha,
            expected_release_id=self.release_id,
            e2e_script_path=self.script,
            expected_e2e_script_sha256=self.script_sha,
            output_receipt_path=self.receipt,
            runner=runner,
        )

    def test_created_then_no_change_is_canonical_private_and_same_dist_bound(self) -> None:
        first_runner = FakeRunner(self._result())
        state, digest, receipt = self._execute(first_runner)
        self.assertEqual(state, "created")
        self.assertEqual(digest, sha256(self.receipt.read_bytes()).hexdigest())
        self.assertEqual(self.receipt.read_bytes(), canonical_bytes(receipt))
        self.assertEqual(os.stat(self.receipt).st_mode & 0o777, 0o600)
        self.assertEqual(receipt["route_matrix"]["evaluated_pages"], 26)
        self.assertEqual(receipt["evidence_grade"], "L2_local_same_dist_browser_acceptance")
        self.assertEqual(receipt["release"]["public_casebook"]["dossierCount"], 1)
        self.assertTrue(
            receipt["checks"][
                "dashboard_ranges_circular_radar_quarter_insights_and_three_reports_exact"
            ]
        )
        self.assertTrue(
            receipt["checks"]["release_pointer_and_seven_datasets_exact"]
        )
        self.assertNotIn(
            "release_pointer_and_four_datasets_exact", receipt["checks"]
        )
        self.assertTrue(receipt["boundaries"]["production_unchanged"])
        self.assertFalse(receipt["boundaries"]["deploy"])
        self.assertIn("--offline", receipt["runner"]["command_contract"])
        self.assertIn("--package=@playwright/cli@0.1.17", receipt["runner"]["command_contract"])

        second_runner = FakeRunner(self._result())
        second_state, second_digest, _ = self._execute(second_runner)
        self.assertEqual(second_state, "no_change")
        self.assertEqual(second_digest, digest)

    def test_external_request_fails_closed_and_closes_session_and_server(self) -> None:
        result = self._result()
        result["externalRequests"] = ["https://unexpected.invalid/"]
        runner = FakeRunner(result)
        with self.assertRaisesRegex(InsightsE2EError, "externalRequests_not_empty"):
            self._execute(runner)
        self.assertFalse(self.receipt.exists())
        self.assertTrue(any(command[-1] == "close" for command in runner.commands))
        self.assertIsNotNone(runner.open_url)
        with self.assertRaises((URLError, TimeoutError, ConnectionError, OSError)):
            urlopen(runner.open_url or "", timeout=0.2)

    def test_manifest_tamper_fails_before_browser_execution(self) -> None:
        self.release_manifest.write_bytes(self.release_manifest.read_bytes() + b" ")
        runner = FakeRunner(self._result())
        with self.assertRaisesRegex(InsightsE2EError, "release_manifest_sha256_mismatch"):
            self._execute(runner)
        self.assertEqual(runner.commands, [])
        self.assertFalse(self.receipt.exists())

    def test_public_casebook_tamper_fails_before_browser_execution(self) -> None:
        casebook_path = (
            self.dist
            / "data/reddit-voc/reddit_voc_casebook_20260716_public_a1/casebook.json"
        )
        casebook_path.write_bytes(casebook_path.read_bytes() + b" ")
        release = json.loads(self.release_manifest.read_text(encoding="utf-8"))
        release["files"] = tree_inventory(self.dist)
        release["file_count"] = len(release["files"])
        self.release_manifest.write_bytes(canonical_bytes(release))
        self.release_manifest_sha = file_sha256(self.release_manifest)
        runner = FakeRunner(self._result())
        with self.assertRaisesRegex(InsightsE2EError, "public_casebook_data_sha256_mismatch"):
            self._execute(runner)
        self.assertEqual(runner.commands, [])

    def test_route_failure_does_not_publish_receipt(self) -> None:
        result = self._result()
        result["routes"][0]["status"] = 500
        runner = FakeRunner(result)
        with self.assertRaisesRegex(InsightsE2EError, "route_contract_failed"):
            self._execute(runner)
        self.assertFalse(self.receipt.exists())

    def test_dashboard_contract_fails_closed(self) -> None:
        result = self._result()
        result["dashboard"]["dualAxisTrendExact"] = False
        runner = FakeRunner(result)
        with self.assertRaisesRegex(InsightsE2EError, "dashboard_contract_failed"):
            self._execute(runner)
        self.assertFalse(self.receipt.exists())

    def test_existing_different_receipt_is_collision(self) -> None:
        self.receipt.parent.mkdir(parents=True)
        self.receipt.write_bytes(canonical_bytes({"stale": True}))
        os.chmod(self.receipt, 0o600)
        runner = FakeRunner(self._result())
        with self.assertRaisesRegex(InsightsE2EError, "receipt_collision"):
            self._execute(runner)
        self.assertEqual(json.loads(self.receipt.read_text()), {"stale": True})

    def test_symlinked_dist_member_is_rejected(self) -> None:
        target = self.root / "outside.txt"
        target.write_text("outside", encoding="utf-8")
        (self.dist / "unsafe.txt").symlink_to(target)
        runner = FakeRunner(self._result())
        with self.assertRaisesRegex(InsightsE2EError, "dist_file_unsafe"):
            self._execute(runner)
        self.assertEqual(runner.commands, [])


if __name__ == "__main__":
    unittest.main()
