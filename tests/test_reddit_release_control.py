from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
from typing import TypedDict
import unittest

from scripts import build_reddit_production_acceptance as acceptance_builder
from scripts import build_reddit_promotion_consumption as consumption_builder
from scripts import build_reddit_promotion_permit as permit_builder
from scripts import promote_reddit_candidate as promotion_wrapper
from scripts import validate_reddit_rollback_evidence as rollback_validator
from tests.test_reddit_promotion_execution import PromotionFixture


def file_sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


class UpstreamKwargs(TypedDict):
    promotion_receipt_path: Path
    public_http_observation_path: Path
    expected_public_http_observation_sha256: str
    public_browser_receipt_path: Path
    expected_public_browser_receipt_sha256: str


class ReleaseControlFixture(PromotionFixture):
    def __init__(self, workspace: Path) -> None:
        super().__init__(workspace)
        self.permit_result = self.build_permit()
        self.permit_sha = str(self.permit_result["permit_sha256"])
        self.acceptance = self.root / "private" / "acceptance.json"
        self.consumption = self.root / "private" / "consumption.json"
        self.execution = self.root / "private" / "execution.json"
        self.remote_receipt = self.root / "private" / "remote-promotion.json"
        self.public_http_receipt = self.root / "private" / "public-http.json"
        self.public_browser_receipt = self.root / "private" / "public-browser.json"
        self.remote_receipt.write_bytes(
            permit_builder.canonical_bytes(self.remote_document_v2())
        )
        self.public_http_receipt.write_bytes(
            permit_builder.canonical_bytes(self.public_http_document())
        )
        self.public_browser_receipt.write_bytes(
            permit_builder.canonical_bytes(self.public_browser_document())
        )
        for path in (
            self.remote_receipt,
            self.public_http_receipt,
            self.public_browser_receipt,
        ):
            os.chmod(path, 0o600)
        self.remote_sha = file_sha(self.remote_receipt)

    def upstream_kwargs(self) -> UpstreamKwargs:
        return {
            "promotion_receipt_path": self.remote_receipt,
            "public_http_observation_path": self.public_http_receipt,
            "expected_public_http_observation_sha256": file_sha(
                self.public_http_receipt
            ),
            "public_browser_receipt_path": self.public_browser_receipt,
            "expected_public_browser_receipt_sha256": file_sha(
                self.public_browser_receipt
            ),
        }

    def acceptance_document(self) -> dict[str, object]:
        return {
            "accepted_at_utc": "2026-07-15T10:04:00Z",
            "authorization": {
                "packet_sha256": self.packet_sha,
                "permit_sha256": self.permit_sha,
                "user_authorized": True,
            },
            "boundaries": {
                "database_write": False,
                "live_send": False,
                "provider_call": False,
                "schedule_change": False,
                "shared_nginx_modified": False,
            },
            "container": {
                "health": "healthy",
                "mount_count": 1,
                "data_mount": {
                    "contract_version": "reddit_voc_data_mount_v1",
                    "type": "bind",
                    "source": "/opt/reddit-voc-insights-data",
                    "destination": "/srv/reddit-voc-data",
                    "read_only": True,
                    "propagation": "rprivate",
                },
                "read_only_rootfs": True,
                "release_sha256": self.release,
                "restart_count": 0,
                "runtime_contract_verified": True,
                "user": "101:101",
            },
            "data_release_id": self.data_release,
            "data_pointer_sha256": self.target_data_pointer_sha,
            "data_inventory_sha256": "2" * 64,
            "data_file_count": 81,
            "data_total_bytes": 123456,
            "evidence_grade": "L4-authorized-live",
            "invariants": {
                "candidate_container_count": 0,
                "collector_health": "healthy",
                "collector_id": "d" * 64,
                "collector_restart_count": 0,
                "cron_sha256": "e" * 64,
                "database_stable": True,
                "new_release_checksums_verified": True,
                "one_shot_count": 0,
                "port_18339_listener_count": 0,
                "report_pointer_stable": True,
                "rollback_release_checksums_verified": True,
                "running_container_inventory_stable": True,
                "shared_nginx_sha256": "f" * 64,
                "translation_health": "healthy",
                "translation_id": "1" * 64,
                "translation_restart_count": 0,
            },
            "public_browser": {
                "browser_error_count": 0,
                "evaluated_pages": 26,
                "external_request_count": 0,
                "same_origin_http_failure_count": 0,
                "status": "passed",
            },
            "public_http": {
                "health_http_200": True,
                "public_artifact_200_count": 8,
                "release_marker_verified": True,
                "route_200_count": 13,
                "security_404_count": 20,
                "tls_verified": True,
            },
            "release_sha256": self.release,
            "remote_promotion_receipt": {
                "path": (
                    "/opt/reddit-voc-insights-site/evidence/"
                    f"promotion-20260715T100300Z-{self.release}.json"
                ),
                "sha256": self.remote_sha,
                "status": "promoted_pending_public_acceptance",
            },
            "rollback": {
                "ready": True,
                "target_data_pointer_sha256": (
                    self.expected_current_data_pointer_sha
                ),
                "target_data_release_id": self.expected_current_data_release,
                "target_release_sha256": self.current,
            },
            "schema_version": "reddit_voc_production_acceptance_receipt_v2",
            "site_url": "https://reddit.lute-tlz-dddd.top",
            "status": "passed_public_production_acceptance",
        }

    def remote_document(self) -> dict[str, object]:
        return {
            "candidate_18339_smoke": True,
            "collector_id": "d" * 64,
            "collector_restart_count": 0,
            "cron_sha256": "e" * 64,
            "data_release_id": self.data_release,
            "database_write": False,
            "evidence_grade": "L4-authorized-live",
            "four_exports_complete": False,
            "generated_at_utc": "2026-07-15T10:03:00Z",
            "live_send": False,
            "nginx_sha256": "f" * 64,
            "packet_sha256": self.packet_sha,
            "permit_sha256": self.permit_sha,
            "previous_release_sha256": self.current,
            "production_container_smoke": True,
            "provider_call": False,
            "release_sha256": self.release,
            "schema_version": "reddit_voc_remote_promotion_receipt_v1",
            "shared_nginx_modified": False,
            "status": "promoted_pending_public_acceptance",
            "translation_id": "1" * 64,
            "translation_restart_count": 0,
        }

    def remote_document_v2(self) -> dict[str, object]:
        value = self.remote_document()
        value.update(
            {
                "data_file_count": 81,
                "data_inventory_sha256": "2" * 64,
                "data_pointer_sha256": self.target_data_pointer_sha,
                "data_total_bytes": 123456,
                "candidate_exports_validation_bound": True,
                "four_exports_complete": False,
                "previous_data_pointer_sha256": (
                    self.expected_current_data_pointer_sha
                ),
                "previous_data_release_id": self.expected_current_data_release,
                "schema_version": "reddit_voc_remote_promotion_receipt_v2",
            }
        )
        return value

    def public_http_document(self) -> dict[str, object]:
        base = "reddit_voc_site_snapshot_test"
        insights = "reddit_voc_insights_test"
        reports = "reddit_voc_reports_test"
        personas = "reddit_voc_personas_test"
        public_paths = [
            "/release.json",
            "/data/reddit-voc/current-release.json",
            f"/data/reddit-voc/{base}/manifest-public.json",
            f"/data/reddit-voc/{insights}/public/manifest.json",
            f"/data/reddit-voc/{reports}/public/manifest.json",
            f"/data/reddit-voc/{personas}/manifest.json",
            "/data/cases/manifest.v1.json",
            "/data/cases/case-index.v1.json",
        ]
        security_paths = [
            "/.env",
            "/.env.local",
            "/frontend-source-manifest.json",
            "/candidate-ui-source-validation-receipt.json",
            "/candidate-ui-validation-receipt.json",
            "/release-manifest.json",
            f"/data/reddit-voc/{base}/manifest.json",
            f"/data/reddit-voc/{base}/aggregates.json",
            f"/data/reddit-voc/{base}/posts.json",
            f"/data/reddit-voc/{base}/comments.json",
            f"/data/reddit-voc/{base}/quarantine.json",
            f"/data/reddit-voc/{base}/tag-dictionary.json",
            f"/data/reddit-voc/{insights}/manifest.json",
            f"/data/reddit-voc/{insights}/insights.json",
            f"/data/reddit-voc/{insights}/semantic-audit.json",
            f"/data/reddit-voc/{reports}/manifest.json",
            f"/data/reddit-voc/{reports}/report-index.json",
            f"/data/reddit-voc/{reports}/current/daily.json",
            f"/data/reddit-voc/{reports}/archive/daily.json",
            f"/data/reddit-voc/{personas}/imports/private.json",
        ]

        return {
            "base_url": "https://reddit.lute-tlz-dddd.top",
            "counts": {
                "public_artifact_200_count": 8,
                "route_200_count": 13,
                "security_404_count": 20,
            },
            "data_pointer": {
                "path": "/data/reddit-voc/current-release.json",
                "release_id": self.data_release,
                "sha256": self.target_data_pointer_sha,
            },
            "evidence_grade": "L3-public-read-only",
            "expected_data_pointer_sha256": self.target_data_pointer_sha,
            "expected_data_release_id": self.data_release,
            "expected_release_sha256": self.release,
            "health": {"body": "ok", "path": "/healthz", "status": 200},
            "observed_at_utc": "2026-07-15T10:03:30Z",
            "public_artifacts": [
                {"path": path, "status": 200} for path in public_paths
            ],
            "release_marker": {"release_sha256": self.release},
            "remote_write": False,
            "routes": [
                {"path": path, "status": 200}
                for path in sorted(acceptance_builder.PUBLIC_ROUTES)
            ],
            "schema_version": "reddit_voc_public_http_acceptance_observation_v1",
            "security_paths": [
                {"path": path, "status": 404} for path in security_paths
            ],
            "status": "passed_public_http_acceptance",
            "tls_verified": True,
        }

    def public_browser_document(self) -> dict[str, object]:
        routes = [
            {
                "abnormalPromptIcons": 0,
                "finalPath": route,
                "forbiddenLegacyGateTextPresent": False,
                "horizontalOverflow": False,
                "loginControls": [],
                "passwordInputs": 0,
                "requiredTextPresent": True,
                "route": route,
                "status": 200,
                "textLength": 1000,
                "viewport": viewport,
            }
            for viewport in sorted(acceptance_builder.BROWSER_VIEWPORTS)
            for route in sorted(acceptance_builder.PUBLIC_ROUTES)
        ]
        return {
            "baseUrl": "https://reddit.lute-tlz-dddd.top",
            "browserErrors": [],
            "dashboard": {
                "circularRadarAndFiveClickableFormulas": True,
                "dualAxisTrendExact": True,
                "executiveDigestPresent": True,
                "missionImageAbsent": True,
                "threeUrlBackedRangesExact": True,
            },
            "evidenceLevel": "browser_dom_network_acceptance",
            "externalRequests": [],
            "insights": {
                "automationAttributionBoundaryVisible": True,
                "caseReferencesMethodOnly": True,
                "controlledEvidence": True,
                "eightPersonaGroupsAndQuarterAssignmentsExact": True,
                "fourUrlBackedThemeTabsExact": True,
                "geoAndAutomationCountsExact": True,
                "legacyDarkPanelsAbsent": True,
                "quarterWindowAndCountsExact": True,
            },
            "observedAtUtc": "2026-07-15T10:03:45Z",
            "release": {
                "collectorIsolation": True,
                "datasetVersions": {
                    "base": "reddit_voc_site_snapshot_test",
                    "brand_health": "reddit_voc_brand_health_test",
                    "casebook": "reddit_voc_casebook_test",
                    "insights": "reddit_voc_insights_test",
                    "personas": "reddit_voc_personas_test",
                    "quarter_insights": "reddit_voc_quarter_insights_test",
                    "reports": "reddit_voc_reports_test",
                },
                "noLogin": True,
                "releaseId": self.data_release,
                "releasePointerSha256": self.target_data_pointer_sha,
                "releaseSha256": self.release,
            },
            "reports": [
                {
                    "availablePeriodText": "数据锚点：测试完整周期",
                    "comparison": True,
                    "completeness100": True,
                    "dailyMidnightLabelAbsent": True,
                    "downTrendGreen": True,
                    "expectedHistoricalPeriodOptionCount": (
                        15 if period == "日报" else 13
                    ),
                    "expectedIndicatorCount": 7 if period == "日报" else 11,
                    "helpButtonCount": 7 if period == "日报" else 11,
                    "historicalPeriodOptionCount": (
                        15 if period == "日报" else 13
                    ),
                    "historyContractVisible": True,
                    "indicatorCount": 7 if period == "日报" else 11,
                    "latestCompleteSelected": True,
                    "legacyTermsAbsent": True,
                    "operationalBody": True,
                    "period": period,
                    "periodScopePresent": True,
                    "storyMapComplete": True,
                    "storyMapCount": 1,
                    "trendCount": 3,
                    "unavailableAbsent": True,
                    "upTrendRed": True,
                }
                for period in ("日报", "周报", "月报")
            ],
            "routes": routes,
            "sameOriginHttpFailures": [],
            "status": "passed",
        }

class ReleaseControlTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.fixture = ReleaseControlFixture(Path(temporary.name))

    def test_promotion_wrapper_only_writes_local_dry_contract(self) -> None:
        packet = json.loads(self.fixture.packet.read_text())
        transfer = packet["artifacts"]["transfer_tgz"]
        archive = self.fixture.root / transfer["path"]
        runner = self.fixture.runtime_paths["remote_promotion_runner"]
        installer = self.fixture.runtime_paths["remote_installer"]
        rollback = self.fixture.runtime_paths["remote_rollback"]

        result = promotion_wrapper.build_promotion_execution_contract(
            artifact_root=self.fixture.root,
            packet_path=self.fixture.packet,
            packet_sha256=self.fixture.packet_sha,
            permit_path=self.fixture.permit,
            permit_sha256=self.fixture.permit_sha,
            release_archive_path=archive,
            release_archive_sha256=transfer["sha256"],
            remote_runner_path=runner,
            remote_runner_sha256=file_sha(runner),
            remote_installer_path=installer,
            remote_installer_sha256=file_sha(installer),
            remote_rollback_path=rollback,
            remote_rollback_sha256=file_sha(rollback),
            release_sha256=self.fixture.release,
            expected_current_release_sha256=self.fixture.current,
            expected_current_data_release_id=(
                self.fixture.expected_current_data_release
            ),
            expected_current_data_pointer_sha256=(
                self.fixture.expected_current_data_pointer_sha
            ),
            target_data_pointer_sha256=self.fixture.target_data_pointer_sha,
            now_utc="2026-07-15T10:02:00Z",
            output=self.fixture.execution,
        )
        self.assertEqual(result["status"], "ready_for_explicit_external_execution")
        self.assertEqual(
            result["execution"],
            {
                "deploy": False,
                "executed": False,
                "mode": "local_contract_only",
                "production_switch": False,
                "remote_write": False,
                "ssh": False,
            },
        )
        self.assertEqual(len(result["runner_argv_contract"]), 12)
        self.assertEqual(oct(self.fixture.execution.stat().st_mode & 0o777), "0o600")

    def test_acceptance_and_consumption_are_bound_and_immutable(self) -> None:
        built = acceptance_builder.build_production_acceptance(
            artifact_root=self.fixture.root,
            output=self.fixture.acceptance,
            receipt=self.fixture.acceptance_document(),
            expected_release_sha256=self.fixture.release,
            expected_packet_sha256=self.fixture.packet_sha,
            expected_permit_sha256=self.fixture.permit_sha,
            expected_remote_promotion_receipt_sha256=self.fixture.remote_sha,
            **self.fixture.upstream_kwargs(),
        )
        consumed = consumption_builder.build_promotion_consumption(
            artifact_root=self.fixture.root,
            packet_path=self.fixture.packet,
            packet_sha256=self.fixture.packet_sha,
            permit_path=self.fixture.permit,
            permit_sha256=self.fixture.permit_sha,
            acceptance_receipt_path=self.fixture.acceptance,
            acceptance_receipt_sha256=built["acceptance_receipt_sha256"],
            release_sha256=self.fixture.release,
            expected_current_release_sha256=self.fixture.current,
            expected_current_data_release_id=(
                self.fixture.expected_current_data_release
            ),
            expected_current_data_pointer_sha256=(
                self.fixture.expected_current_data_pointer_sha
            ),
            target_data_pointer_sha256=self.fixture.target_data_pointer_sha,
            consumed_at_utc="2026-07-15T10:05:00Z",
            output=self.fixture.consumption,
        )
        self.assertEqual(consumed["status"], "passed")
        self.assertFalse(json.loads(self.fixture.permit.read_text())["consumed"])
        before = self.fixture.consumption.stat().st_mtime_ns
        repeated = consumption_builder.build_promotion_consumption(
            artifact_root=self.fixture.root,
            packet_path=self.fixture.packet,
            packet_sha256=self.fixture.packet_sha,
            permit_path=self.fixture.permit,
            permit_sha256=self.fixture.permit_sha,
            acceptance_receipt_path=self.fixture.acceptance,
            acceptance_receipt_sha256=built["acceptance_receipt_sha256"],
            release_sha256=self.fixture.release,
            expected_current_release_sha256=self.fixture.current,
            expected_current_data_release_id=(
                self.fixture.expected_current_data_release
            ),
            expected_current_data_pointer_sha256=(
                self.fixture.expected_current_data_pointer_sha
            ),
            target_data_pointer_sha256=self.fixture.target_data_pointer_sha,
            consumed_at_utc="2026-07-15T10:05:00Z",
            output=self.fixture.consumption,
        )
        self.assertEqual(repeated["publication_status"], "no_change")
        self.assertEqual(self.fixture.consumption.stat().st_mtime_ns, before)

    def test_consumption_can_seal_after_expiry_when_acceptance_was_in_time(self) -> None:
        built = acceptance_builder.build_production_acceptance(
            artifact_root=self.fixture.root,
            output=self.fixture.acceptance,
            receipt=self.fixture.acceptance_document(),
            expected_release_sha256=self.fixture.release,
            expected_packet_sha256=self.fixture.packet_sha,
            expected_permit_sha256=self.fixture.permit_sha,
            expected_remote_promotion_receipt_sha256=self.fixture.remote_sha,
            **self.fixture.upstream_kwargs(),
        )
        consumed = consumption_builder.build_promotion_consumption(
            artifact_root=self.fixture.root,
            packet_path=self.fixture.packet,
            packet_sha256=self.fixture.packet_sha,
            permit_path=self.fixture.permit,
            permit_sha256=self.fixture.permit_sha,
            acceptance_receipt_path=self.fixture.acceptance,
            acceptance_receipt_sha256=built["acceptance_receipt_sha256"],
            release_sha256=self.fixture.release,
            expected_current_release_sha256=self.fixture.current,
            expected_current_data_release_id=(
                self.fixture.expected_current_data_release
            ),
            expected_current_data_pointer_sha256=(
                self.fixture.expected_current_data_pointer_sha
            ),
            target_data_pointer_sha256=self.fixture.target_data_pointer_sha,
            consumed_at_utc="2026-07-15T10:45:00Z",
            output=self.fixture.consumption,
        )
        self.assertEqual(consumed["status"], "passed")

    def test_consumption_rejects_acceptance_after_permit_expiry(self) -> None:
        value = self.fixture.acceptance_document()
        value["accepted_at_utc"] = "2026-07-15T10:31:30Z"
        remote = self.fixture.remote_document_v2()
        remote["generated_at_utc"] = "2026-07-15T10:31:00Z"
        self.fixture.remote_receipt.write_bytes(
            permit_builder.canonical_bytes(remote)
        )
        os.chmod(self.fixture.remote_receipt, 0o600)
        value["remote_promotion_receipt"]["sha256"] = file_sha(  # type: ignore[index]
            self.fixture.remote_receipt
        )
        http = self.fixture.public_http_document()
        http["observed_at_utc"] = "2026-07-15T10:31:10Z"
        self.fixture.public_http_receipt.write_bytes(
            permit_builder.canonical_bytes(http)
        )
        os.chmod(self.fixture.public_http_receipt, 0o600)
        browser = self.fixture.public_browser_document()
        browser["observedAtUtc"] = "2026-07-15T10:31:20Z"
        self.fixture.public_browser_receipt.write_bytes(
            permit_builder.canonical_bytes(browser)
        )
        os.chmod(self.fixture.public_browser_receipt, 0o600)
        built = acceptance_builder.build_production_acceptance(
            artifact_root=self.fixture.root,
            output=self.fixture.acceptance,
            receipt=value,
            expected_release_sha256=self.fixture.release,
            expected_packet_sha256=self.fixture.packet_sha,
            expected_permit_sha256=self.fixture.permit_sha,
            expected_remote_promotion_receipt_sha256=file_sha(
                self.fixture.remote_receipt
            ),
            **self.fixture.upstream_kwargs(),
        )
        with self.assertRaisesRegex(
            consumption_builder.PromotionConsumptionError,
            "authorization_expired",
        ):
            consumption_builder.build_promotion_consumption(
                artifact_root=self.fixture.root,
                packet_path=self.fixture.packet,
                packet_sha256=self.fixture.packet_sha,
                permit_path=self.fixture.permit,
                permit_sha256=self.fixture.permit_sha,
                acceptance_receipt_path=self.fixture.acceptance,
                acceptance_receipt_sha256=built["acceptance_receipt_sha256"],
                release_sha256=self.fixture.release,
                expected_current_release_sha256=self.fixture.current,
                expected_current_data_release_id=(
                    self.fixture.expected_current_data_release
                ),
                expected_current_data_pointer_sha256=(
                    self.fixture.expected_current_data_pointer_sha
                ),
                target_data_pointer_sha256=self.fixture.target_data_pointer_sha,
                consumed_at_utc="2026-07-15T10:32:00Z",
                output=self.fixture.consumption,
            )

    def test_acceptance_rejects_failed_browser_evidence(self) -> None:
        value = self.fixture.acceptance_document()
        value["public_browser"]["browser_error_count"] = 1  # type: ignore[index]
        with self.assertRaisesRegex(
            acceptance_builder.ProductionAcceptanceError, "browser_error_count"
        ):
            acceptance_builder.build_production_acceptance(
                artifact_root=self.fixture.root,
                output=self.fixture.acceptance,
                receipt=value,
                expected_remote_promotion_receipt_sha256=(
                    self.fixture.remote_sha
                ),
                **self.fixture.upstream_kwargs(),
            )

    def test_v2_acceptance_requires_all_three_upstream_receipts(self) -> None:
        with self.assertRaisesRegex(
            acceptance_builder.ProductionAcceptanceError,
            "v2_acceptance_requires_three_bound_upstream_receipts",
        ):
            acceptance_builder.build_production_acceptance(
                artifact_root=self.fixture.root,
                output=self.fixture.acceptance,
                receipt=self.fixture.acceptance_document(),
                expected_remote_promotion_receipt_sha256=(
                    self.fixture.remote_sha
                ),
            )

    def test_v2_acceptance_rejects_self_reported_data_tuple_tampering(self) -> None:
        value = self.fixture.acceptance_document()
        value["data_release_id"] = "reddit_voc_release_20260715_tampered_v1"
        with self.assertRaisesRegex(
            acceptance_builder.ProductionAcceptanceError,
            "remote_promotion_upstream_binding_mismatch",
        ):
            acceptance_builder.build_production_acceptance(
                artifact_root=self.fixture.root,
                output=self.fixture.acceptance,
                receipt=value,
                expected_remote_promotion_receipt_sha256=(
                    self.fixture.remote_sha
                ),
                **self.fixture.upstream_kwargs(),
            )

    def test_v2_acceptance_reopens_and_rejects_tampered_http_evidence(self) -> None:
        built = acceptance_builder.build_production_acceptance(
            artifact_root=self.fixture.root,
            output=self.fixture.acceptance,
            receipt=self.fixture.acceptance_document(),
            expected_remote_promotion_receipt_sha256=self.fixture.remote_sha,
            **self.fixture.upstream_kwargs(),
        )
        http_value = self.fixture.public_http_document()
        http_value["tls_verified"] = False
        self.fixture.public_http_receipt.write_bytes(
            permit_builder.canonical_bytes(http_value)
        )
        os.chmod(self.fixture.public_http_receipt, 0o600)
        with self.assertRaisesRegex(
            acceptance_builder.ProductionAcceptanceError,
            "public_http_evidence_sha256_mismatch",
        ):
            acceptance_builder.validate_production_acceptance(
                artifact_root=self.fixture.root,
                receipt_path=self.fixture.acceptance,
                expected_receipt_sha256=built["acceptance_receipt_sha256"],
                expected_remote_promotion_receipt_sha256=(
                    self.fixture.remote_sha
                ),
            )

    def test_consumption_rejects_v2_acceptance_without_reopened_evidence(self) -> None:
        self.fixture.acceptance.write_bytes(
            permit_builder.canonical_bytes(self.fixture.acceptance_document())
        )
        os.chmod(self.fixture.acceptance, 0o600)
        with self.assertRaisesRegex(
            consumption_builder.PromotionConsumptionError,
            "v2_acceptance_evidence_sources_required",
        ):
            consumption_builder.build_promotion_consumption(
                artifact_root=self.fixture.root,
                packet_path=self.fixture.packet,
                packet_sha256=self.fixture.packet_sha,
                permit_path=self.fixture.permit,
                permit_sha256=self.fixture.permit_sha,
                acceptance_receipt_path=self.fixture.acceptance,
                acceptance_receipt_sha256=file_sha(self.fixture.acceptance),
                release_sha256=self.fixture.release,
                expected_current_release_sha256=self.fixture.current,
                expected_current_data_release_id=(
                    self.fixture.expected_current_data_release
                ),
                expected_current_data_pointer_sha256=(
                    self.fixture.expected_current_data_pointer_sha
                ),
                target_data_pointer_sha256=self.fixture.target_data_pointer_sha,
                consumed_at_utc="2026-07-15T10:05:00Z",
                output=self.fixture.consumption,
            )

    def test_v2_consumption_rejects_legacy_action_set(self) -> None:
        value = {
            "actions_performed": list(consumption_builder.LEGACY_SUCCESS_ACTIONS),
            "authorization_id": "reddit_voc_promotion_test",
            "consumed_at_utc": "2026-07-15T10:05:00Z",
            "data_binding": {
                "current_data_file_count": 81,
                "current_data_inventory_sha256": "2" * 64,
                "current_data_pointer_sha256": self.fixture.target_data_pointer_sha,
                "current_data_release_id": self.fixture.data_release,
                "current_data_total_bytes": 123456,
                "previous_data_pointer_sha256": (
                    self.fixture.expected_current_data_pointer_sha
                ),
                "previous_data_release_id": (
                    self.fixture.expected_current_data_release
                ),
            },
            "forbidden_actions_performed": [],
            "packet_sha256": self.fixture.packet_sha,
            "permit_sha256": self.fixture.permit_sha,
            "production_acceptance": {
                "path": "private/acceptance.json",
                "sha256": "3" * 64,
                "status": acceptance_builder.STATUS,
            },
            "release_sha256": self.fixture.release,
            "remote_promotion_receipt_sha256": self.fixture.remote_sha,
            "schema_version": consumption_builder.SCHEMA_VERSION_V2,
            "side_effects": dict(consumption_builder.SIDE_EFFECTS),
            "status": consumption_builder.STATUS,
        }
        with self.assertRaisesRegex(
            consumption_builder.PromotionConsumptionError,
            "actions_performed_invalid",
        ):
            consumption_builder.validate_promotion_consumption_document(value)

    def test_existing_v2_consumption_rebinds_all_seven_data_fields(self) -> None:
        accepted = acceptance_builder.build_production_acceptance(
            artifact_root=self.fixture.root,
            output=self.fixture.acceptance,
            receipt=self.fixture.acceptance_document(),
            expected_remote_promotion_receipt_sha256=self.fixture.remote_sha,
            **self.fixture.upstream_kwargs(),
        )
        consumption_builder.build_promotion_consumption(
            artifact_root=self.fixture.root,
            packet_path=self.fixture.packet,
            packet_sha256=self.fixture.packet_sha,
            permit_path=self.fixture.permit,
            permit_sha256=self.fixture.permit_sha,
            acceptance_receipt_path=self.fixture.acceptance,
            acceptance_receipt_sha256=accepted["acceptance_receipt_sha256"],
            release_sha256=self.fixture.release,
            expected_current_release_sha256=self.fixture.current,
            expected_current_data_release_id=(
                self.fixture.expected_current_data_release
            ),
            expected_current_data_pointer_sha256=(
                self.fixture.expected_current_data_pointer_sha
            ),
            target_data_pointer_sha256=self.fixture.target_data_pointer_sha,
            consumed_at_utc="2026-07-15T10:05:00Z",
            output=self.fixture.consumption,
        )
        forged = json.loads(self.fixture.consumption.read_text())
        forged["data_binding"]["current_data_file_count"] = 999
        forged_path = self.fixture.root / "private" / "forged-consumption.json"
        forged_path.write_bytes(permit_builder.canonical_bytes(forged))
        os.chmod(forged_path, 0o600)
        with self.assertRaisesRegex(
            consumption_builder.PromotionConsumptionError,
            "v2_consumption_data_binding_mismatch",
        ):
            consumption_builder.validate_promotion_consumption(
                artifact_root=self.fixture.root,
                receipt_path=forged_path,
                expected_receipt_sha256=file_sha(forged_path),
            )

    def test_fresh_v1_acceptance_downgrade_is_not_historical(self) -> None:
        value = self.fixture.acceptance_document()
        value["schema_version"] = acceptance_builder.SCHEMA_VERSION
        with self.assertRaisesRegex(
            acceptance_builder.ProductionAcceptanceError,
            "legacy_v1_acceptance_build_forbidden",
        ):
            acceptance_builder.build_production_acceptance(
                artifact_root=self.fixture.root,
                output=self.fixture.acceptance,
                receipt=value,
            )
        self.fixture.acceptance.write_bytes(permit_builder.canonical_bytes(value))
        os.chmod(self.fixture.acceptance, 0o600)
        with self.assertRaisesRegex(
            rollback_validator.RollbackEvidenceError,
            "legacy_v1_acceptance_not_exactly_allowlisted",
        ):
            rollback_validator.validate_rollback_evidence(
                artifact_root=self.fixture.root,
                expected_release_sha256=self.fixture.release,
                acceptance_receipt_path=self.fixture.acceptance,
                expected_acceptance_receipt_sha256=file_sha(self.fixture.acceptance),
            )

    def test_public_http_evidence_requires_exact_matrix(self) -> None:
        http_value = self.fixture.public_http_document()
        http_value["routes"] = [{"path": "/", "status": 200}]
        http_value["public_artifacts"] = [
            {"path": "/release.json", "status": 200}
        ]
        http_value["security_paths"] = [
            {"path": "/private", "status": 404}
        ]
        http_value["counts"] = {
            "public_artifact_200_count": 1,
            "route_200_count": 1,
            "security_404_count": 1,
        }
        self.fixture.public_http_receipt.write_bytes(
            permit_builder.canonical_bytes(http_value)
        )
        os.chmod(self.fixture.public_http_receipt, 0o600)
        acceptance = self.fixture.acceptance_document()
        acceptance["public_http"] = {
            "health_http_200": True,
            "public_artifact_200_count": 1,
            "release_marker_verified": True,
            "route_200_count": 1,
            "security_404_count": 1,
            "tls_verified": True,
        }
        with self.assertRaisesRegex(
            acceptance_builder.ProductionAcceptanceError,
            "public_http_upstream_binding_mismatch",
        ):
            acceptance_builder.build_production_acceptance(
                artifact_root=self.fixture.root,
                output=self.fixture.acceptance,
                receipt=acceptance,
                expected_remote_promotion_receipt_sha256=(
                    self.fixture.remote_sha
                ),
                **self.fixture.upstream_kwargs(),
            )

    def test_browser_evidence_binds_exact_code_release_and_route_matrix(self) -> None:
        browser_value = self.fixture.public_browser_document()
        release = browser_value["release"]
        assert isinstance(release, dict)
        release["releaseSha256"] = "0" * 64
        self.fixture.public_browser_receipt.write_bytes(
            permit_builder.canonical_bytes(browser_value)
        )
        os.chmod(self.fixture.public_browser_receipt, 0o600)
        with self.assertRaisesRegex(
            acceptance_builder.ProductionAcceptanceError,
            "public_browser_upstream_binding_mismatch",
        ):
            acceptance_builder.build_production_acceptance(
                artifact_root=self.fixture.root,
                output=self.fixture.acceptance,
                receipt=self.fixture.acceptance_document(),
                expected_remote_promotion_receipt_sha256=(
                    self.fixture.remote_sha
                ),
                **self.fixture.upstream_kwargs(),
            )

    def test_public_evidence_cannot_predate_remote_promotion(self) -> None:
        http_value = self.fixture.public_http_document()
        http_value["observed_at_utc"] = "2026-07-15T10:02:00Z"
        self.fixture.public_http_receipt.write_bytes(
            permit_builder.canonical_bytes(http_value)
        )
        os.chmod(self.fixture.public_http_receipt, 0o600)
        browser_value = self.fixture.public_browser_document()
        browser_value["observedAtUtc"] = "2026-07-15T10:02:30Z"
        self.fixture.public_browser_receipt.write_bytes(
            permit_builder.canonical_bytes(browser_value)
        )
        os.chmod(self.fixture.public_browser_receipt, 0o600)
        with self.assertRaisesRegex(
            acceptance_builder.ProductionAcceptanceError,
            "public_acceptance_precedes_remote_promotion",
        ):
            acceptance_builder.build_production_acceptance(
                artifact_root=self.fixture.root,
                output=self.fixture.acceptance,
                receipt=self.fixture.acceptance_document(),
                expected_remote_promotion_receipt_sha256=(
                    self.fixture.remote_sha
                ),
                **self.fixture.upstream_kwargs(),
            )

    def test_browser_report_counts_are_period_contracts_not_self_reported(self) -> None:
        browser_value = self.fixture.public_browser_document()
        reports = browser_value["reports"]
        assert isinstance(reports, list)
        for report in reports:
            assert isinstance(report, dict)
            report["expectedIndicatorCount"] = 1
            report["indicatorCount"] = 1
            report["helpButtonCount"] = 1
            report["expectedHistoricalPeriodOptionCount"] = 1
            report["historicalPeriodOptionCount"] = 1
        self.fixture.public_browser_receipt.write_bytes(
            permit_builder.canonical_bytes(browser_value)
        )
        os.chmod(self.fixture.public_browser_receipt, 0o600)
        with self.assertRaisesRegex(
            acceptance_builder.ProductionAcceptanceError,
            "public_browser_upstream_binding_mismatch",
        ):
            acceptance_builder.build_production_acceptance(
                artifact_root=self.fixture.root,
                output=self.fixture.acceptance,
                receipt=self.fixture.acceptance_document(),
                expected_remote_promotion_receipt_sha256=(
                    self.fixture.remote_sha
                ),
                **self.fixture.upstream_kwargs(),
            )

    def test_rollback_accepts_bound_promotion_and_acceptance_receipts(self) -> None:
        remote_value = self.fixture.remote_document_v2()
        self.fixture.remote_receipt.write_bytes(
            permit_builder.canonical_bytes(remote_value)
        )
        os.chmod(self.fixture.remote_receipt, 0o600)
        remote_sha = file_sha(self.fixture.remote_receipt)
        acceptance = self.fixture.acceptance_document()
        acceptance["remote_promotion_receipt"]["sha256"] = remote_sha  # type: ignore[index]
        built = acceptance_builder.build_production_acceptance(
            artifact_root=self.fixture.root,
            output=self.fixture.acceptance,
            receipt=acceptance,
            expected_remote_promotion_receipt_sha256=remote_sha,
            **self.fixture.upstream_kwargs(),
        )
        result = rollback_validator.validate_rollback_evidence(
            artifact_root=self.fixture.root,
            expected_release_sha256=self.fixture.release,
            promotion_receipt_path=self.fixture.remote_receipt,
            expected_promotion_receipt_sha256=remote_sha,
            acceptance_receipt_path=self.fixture.acceptance,
            expected_acceptance_receipt_sha256=built["acceptance_receipt_sha256"],
        )
        self.assertEqual(result["status"], "passed_local_read_only")
        self.assertEqual(
            result["evidence_types"],
            ["remote_promotion_receipt", "production_acceptance_receipt"],
        )

    def test_dual_release_rollback_rejects_acceptance_only(self) -> None:
        built = acceptance_builder.build_production_acceptance(
            artifact_root=self.fixture.root,
            output=self.fixture.acceptance,
            receipt=self.fixture.acceptance_document(),
            expected_remote_promotion_receipt_sha256=self.fixture.remote_sha,
            **self.fixture.upstream_kwargs(),
        )
        with self.assertRaisesRegex(
            rollback_validator.RollbackEvidenceError,
            "dual_rollback_requires_v2_promotion_receipt",
        ):
            rollback_validator.validate_rollback_evidence(
                artifact_root=self.fixture.root,
                expected_release_sha256=self.fixture.release,
                acceptance_receipt_path=self.fixture.acceptance,
                expected_acceptance_receipt_sha256=(
                    built["acceptance_receipt_sha256"]
                ),
            )

    def test_remote_v2_rejects_tampered_data_inventory(self) -> None:
        remote_value = self.fixture.remote_document_v2()
        remote_value["data_inventory_sha256"] = "0" * 64
        normalized = rollback_validator.validate_remote_promotion_document(
            remote_value,
            expected_release_sha256=self.fixture.release,
        )
        self.assertEqual(normalized["data_inventory_sha256"], "0" * 64)
        remote_value["data_file_count"] = 0
        with self.assertRaisesRegex(
            rollback_validator.RollbackEvidenceError,
            "data_inventory_invalid",
        ):
            rollback_validator.validate_remote_promotion_document(
                remote_value,
                expected_release_sha256=self.fixture.release,
            )

    def test_remote_v2_rejects_forbidden_live_export_completeness_claim(self) -> None:
        remote_value = self.fixture.remote_document_v2()
        remote_value["four_exports_complete"] = True
        with self.assertRaisesRegex(
            rollback_validator.RollbackEvidenceError,
            "data_projection_invalid",
        ):
            rollback_validator.validate_remote_promotion_document(
                remote_value,
                expected_release_sha256=self.fixture.release,
            )

    def test_fresh_remote_v1_cannot_create_rollback_authority(self) -> None:
        self.fixture.remote_receipt.write_bytes(
            permit_builder.canonical_bytes(self.fixture.remote_document())
        )
        os.chmod(self.fixture.remote_receipt, 0o600)
        with self.assertRaisesRegex(
            rollback_validator.RollbackEvidenceError,
            "remote_promotion_v1_not_exactly_allowlisted",
        ):
            rollback_validator.validate_rollback_evidence(
                artifact_root=self.fixture.root,
                expected_release_sha256=self.fixture.release,
                promotion_receipt_path=self.fixture.remote_receipt,
                expected_promotion_receipt_sha256=file_sha(
                    self.fixture.remote_receipt
                ),
            )

    def test_fresh_legacy_line_receipt_cannot_create_rollback_authority(self) -> None:
        path = self.fixture.root / "private" / "legacy-container.txt"
        path.write_text(
            "\n".join(
                (
                    "evidence_grade=L4-authorized-live",
                    f"release_sha={self.fixture.release}",
                    "release_marker_verified=true",
                    "image_dist_checksums_verified=true",
                    "collector_id_unchanged=true",
                    "nginx_unchanged=true",
                    "cron_unchanged=true",
                )
            )
            + "\n",
            encoding="utf-8",
        )
        os.chmod(path, 0o600)
        with self.assertRaisesRegex(
            rollback_validator.RollbackEvidenceError,
            "legacy_container_receipt_not_exactly_allowlisted",
        ):
            rollback_validator.validate_rollback_evidence(
                artifact_root=self.fixture.root,
                expected_release_sha256=self.fixture.release,
                legacy_container_receipt_path=path,
                expected_legacy_container_receipt_sha256=file_sha(path),
            )


class HistoricalReleaseControlCompatibilityTests(unittest.TestCase):
    def test_exact_historical_remote_v1_receipt_reopens(self) -> None:
        root = Path(__file__).resolve().parents[1]
        path = (
            root
            / "output/reddit-voc-promotion-authorizations"
            / "reddit_voc_promotion_a4ec5df32fc9a6c455904ce0"
            / "remote-promotion-receipt.json"
        )
        result = rollback_validator.validate_rollback_evidence(
            artifact_root=root,
            expected_release_sha256=(
                "e0d57e921ffb54662f883635fb4f20a89ffde898d95293dd1e304178dace6240"
            ),
            promotion_receipt_path=path,
            expected_promotion_receipt_sha256=file_sha(path),
        )
        self.assertEqual(result["status"], "passed_local_read_only")

    def test_legacy_v3_permit_compatibility_is_exactly_allowlisted(self) -> None:
        self.assertTrue(
            permit_builder.legacy_v3_native_permit_allowed(
                authorization_id="reddit_voc_promotion_85e851060befbc2692ded1e1",
                permit_sha256="34f38d536576bab7556725745b4d0efe080bd2eb169c9c617e74002fcab76040",
                packet_sha256="103efd8c7405d5dd7c5b414c93d7601297b9be9703c628737cdfa4a3583329a2",
                release_sha256="ea15b3ef0a1af7a2c9e644b2090c4d36a3dd1038e7967ba8a78402e659a0efc1",
            )
        )
        self.assertFalse(
            permit_builder.legacy_v3_native_permit_allowed(
                authorization_id="reddit_voc_promotion_new_untrusted",
                permit_sha256="1" * 64,
                packet_sha256="0b32371ea79be5e3ca75638f0625a87564c34108af123adeab4dfc3df3135057",
                release_sha256="ebaa5443906628145f9fbe05777d4218b1ec6d53b78e9d7f4f86fa8fbe9df313",
            )
        )

    def test_four_historical_permits_reopen_against_exact_packets(self) -> None:
        root = Path(__file__).resolve().parents[1]
        rows = (
            (
                "reddit_voc_promotion_5a452fa724ea9f7c1beeff22",
                "c8ca362a038338593463d7245e6d9f74b8e143a1a0672ad574d0f93b3013e482",
                "tmp/reddit-voc-plan-c-production-critical/promotion/a5fa1e0a0a224969669d7e6ad79a9415b69f2ba4646b6e2bbca9030ff3d460f3/promotion-packet.json",
                None,
                "83d5ebeaf2345bc78495ed99064d34dcb4f23d09d2c8eda5274110f50a510570",
                "a5fa1e0a0a224969669d7e6ad79a9415b69f2ba4646b6e2bbca9030ff3d460f3",
                "9e0d23131824c9d5e195ef9e0950d62e1c89893a40bafa1ec72c53fab330d650",
                "2026-07-15T13:55:00Z",
            ),
            (
                "reddit_voc_promotion_85e851060befbc2692ded1e1",
                "34f38d536576bab7556725745b4d0efe080bd2eb169c9c617e74002fcab76040",
                "tmp/reddit-voc-v3/reddit_add_data_20260715_v1/promotion-v3-a1/promotion-packet.json",
                "tmp/reddit-voc-v3/reddit_add_data_20260715_v1",
                "103efd8c7405d5dd7c5b414c93d7601297b9be9703c628737cdfa4a3583329a2",
                "ea15b3ef0a1af7a2c9e644b2090c4d36a3dd1038e7967ba8a78402e659a0efc1",
                "a5fa1e0a0a224969669d7e6ad79a9415b69f2ba4646b6e2bbca9030ff3d460f3",
                "2026-07-16T09:15:00Z",
            ),
            (
                "reddit_voc_promotion_a042c0af6056b35c89881673",
                "e6cb274ea88335b67aad915d97d0491bcb0d8b6758664d7c3fb97f673d6d56a8",
                "tmp/reddit-voc-v3/reddit_add_data_20260715_v1/promotion-v3-a2/promotion-packet.json",
                "tmp/reddit-voc-v3/reddit_add_data_20260715_v1",
                "ace4553d7007703e081a4a0a4a654417d332368661b357d972d1e16891de4f6e",
                "627fbab6622d73326386b57010e852a10c3d2133e2e47d941246767b2478bed4",
                "ea15b3ef0a1af7a2c9e644b2090c4d36a3dd1038e7967ba8a78402e659a0efc1",
                "2026-07-16T11:50:00Z",
            ),
            (
                "reddit_voc_promotion_282f91ae1c089f722e8aa963",
                "8e68138ba62a624e5c03af9070615ad6623af37358638de8a37d00b7f04c95c5",
                "tmp/reddit-voc-v3/reddit_add_data_20260715_v1/promotion-v3-a3/promotion-packet.json",
                "tmp/reddit-voc-v3/reddit_add_data_20260715_v1",
                "7ff1227cc63e03c1102de9bad4371361d3cf00da6739cbec91d5a9c29bcdceb8",
                "9c4a45f2da54d1fd417ed2930516d49bae526406cf9fbf20325df682e9784cc5",
                "627fbab6622d73326386b57010e852a10c3d2133e2e47d941246767b2478bed4",
                "2026-07-16T19:00:00Z",
            ),
        )
        for auth, permit_sha, packet, packet_root, packet_sha, release, current, now in rows:
            result = permit_builder.validate_promotion_permit(
                artifact_root=root,
                packet_artifact_root=root / packet_root if packet_root else None,
                permit_path=root / "output/reddit-voc-promotion-authorizations" / auth / "permit.json",
                expected_permit_sha256=permit_sha,
                packet_path=root / packet,
                expected_packet_sha256=packet_sha,
                expected_release_sha256=release,
                expected_current_release_sha256=current,
                now_utc=now,
            )
            self.assertEqual(result["status"], "passed")

    def test_new_permit_cannot_downgrade_to_old_v3_native_packet(self) -> None:
        root = Path(__file__).resolve().parents[1]
        packet = (
            root
            / "tmp/reddit-voc-v3/business-history-promotion-20260723/promotion-packet-r2.json"
        )
        with tempfile.TemporaryDirectory(dir=root / "tmp") as temporary:
            output = Path(temporary) / "permit.json"
            with self.assertRaisesRegex(
                permit_builder.PromotionPermitError,
                "artifacts_unexpected_fields",
            ):
                permit_builder.build_promotion_permit(
                    artifact_root=root,
                    packet_artifact_root=root,
                    packet_path=packet,
                    packet_sha256="0b32371ea79be5e3ca75638f0625a87564c34108af123adeab4dfc3df3135057",
                    release_sha256="ebaa5443906628145f9fbe05777d4218b1ec6d53b78e9d7f4f86fa8fbe9df313",
                    expected_current_release_sha256="e8bea1546862cd9de974ae40429f9b58e0e4b50eef72f6743840b95e19086a3b",
                    authorization_id="untrusted-history2-r2-attempt",
                    authorized_at_utc="2026-07-22T19:20:00Z",
                    expires_at_utc="2026-07-22T19:30:00Z",
                    owner_confirmation=permit_builder.OWNER_CONFIRMATION,
                    output=output,
                )
            self.assertFalse(output.exists())

    def test_three_historical_acceptance_and_consumption_receipts_reopen(self) -> None:
        root = Path(__file__).resolve().parents[1]
        acceptances = sorted(
            (root / "output/reddit-voc-production-acceptance").glob(
                "*/acceptance-receipt.json"
            )
        )
        consumptions = sorted(
            (root / "output/reddit-voc-promotion-authorizations").glob(
                "*/consumption-receipt.json"
            )
        )
        expected_releases = {
            "a5fa1e0a0a224969669d7e6ad79a9415b69f2ba4646b6e2bbca9030ff3d460f3",
            "ea15b3ef0a1af7a2c9e644b2090c4d36a3dd1038e7967ba8a78402e659a0efc1",
            "627fbab6622d73326386b57010e852a10c3d2133e2e47d941246767b2478bed4",
        }
        expected_authorizations = {
            "reddit_voc_promotion_5a452fa724ea9f7c1beeff22",
            "reddit_voc_promotion_85e851060befbc2692ded1e1",
            "reddit_voc_promotion_a042c0af6056b35c89881673",
        }
        self.assertTrue(expected_releases <= {path.parent.name for path in acceptances})
        self.assertTrue(
            expected_authorizations <= {path.parent.name for path in consumptions}
        )
        for path in acceptances:
            result = acceptance_builder.validate_production_acceptance(
                artifact_root=root,
                receipt_path=path,
                expected_receipt_sha256=file_sha(path),
            )
            self.assertEqual(result["status"], "passed")
            rollback = rollback_validator.validate_rollback_evidence(
                artifact_root=root,
                expected_release_sha256=path.parent.name,
                acceptance_receipt_path=path,
                expected_acceptance_receipt_sha256=file_sha(path),
            )
            self.assertEqual(rollback["status"], "passed_local_read_only")
        for path in consumptions:
            result = consumption_builder.validate_promotion_consumption(
                artifact_root=root,
                receipt_path=path,
                expected_receipt_sha256=file_sha(path),
            )
            self.assertEqual(result["status"], "passed")

    def test_remote_rollback_recognizes_current_promotion_json_contract(self) -> None:
        root = Path(__file__).resolve().parents[1]
        script = (root / "scripts/remote_rollback_insights.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn('promotion-*-${release_sha}.json', script)
        self.assertIn("reddit_voc_remote_promotion_receipt_v1", script)
        self.assertIn("reddit_voc_remote_promotion_receipt_v2", script)
        self.assertIn("--target-data-release", script)
        self.assertIn("promoted_pending_public_acceptance", script)


if __name__ == "__main__":
    unittest.main()
