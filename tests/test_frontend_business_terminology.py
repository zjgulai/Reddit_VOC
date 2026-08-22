from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "ref/UI/momcozy-reddit-workbench/src"

VISIBLE_SOURCE_FILES = (
    "components/insights/SnapshotInsightsV3.tsx",
    "components/reports/RealReportView.tsx",
    "features/redditSnapshot/SnapshotBoundaryPanel.tsx",
    "features/redditSnapshot/SnapshotPageLayout.tsx",
    "features/redditSnapshot/governance/ReleaseEvidenceCard.tsx",
    "pages/FAQ.tsx",
    "pages/Features.tsx",
    "pages/HowItWorks.tsx",
    "pages/SnapshotDashboard.tsx",
    "pages/SnapshotInsights.tsx",
    "pages/SnapshotReports.tsx",
    "pages/SnapshotSearch.tsx",
    "pages/SnapshotWorkspace.tsx",
)

FORBIDDEN_VISIBLE_TERMS = (
    "fail-closed",
    "production unchanged",
    "provider_call=false",
    "database_write=false",
    "remote_write=false",
    "live_send=false",
    "artifact release",
    "evidence source",
    "无 Mock 回退",
    "按 post_id",
    "1 个 post_id",
    "1 个 comment_id",
    "父帖 post_id",
    "当前 release、数据范围",
    "新的 manifest 和校验值",
    "manifest 校验状态",
    "版本化快照及 manifest",
    "lineage 由版本化 manifest 和 hash",
)


def test_business_pages_do_not_expose_internal_engineering_terms() -> None:
    sources = {
        relative: (FRONTEND / relative).read_text(encoding="utf-8")
        for relative in VISIBLE_SOURCE_FILES
    }

    violations = {
        term: sorted(relative for relative, source in sources.items() if term in source)
        for term in FORBIDDEN_VISIBLE_TERMS
    }

    assert not {term: files for term, files in violations.items() if files}
