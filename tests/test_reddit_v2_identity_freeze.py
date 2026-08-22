from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.build_reddit_v2_identity_freeze import (
    IdentityFreezeContractError,
    build_identity_freeze,
    canonical_bytes,
    identity_hash,
    write_identity_freeze,
)


MANIFEST_CUTOFF = "2026-07-15T04:15:20.212680Z"
SEARCH_CUTOFF = "2026-07-15T04:15:20.214394Z"
WINDOW_START = "2024-12-31T16:00:00Z"
WINDOW_END = "2026-07-15T16:00:00Z"


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value) + b"\n")


def _post(
    post_id: str,
    *,
    row_typename: str = "SubredditPost",
    created_at: str = "2026-07-14T00:00:00Z",
) -> dict:
    return {
        "__typename": row_typename,
        "id": f"t3_{post_id}",
        "permalink": f"https://www.reddit.com/r/MomCozy/comments/{post_id}/fixture/",
        "createdAt": created_at,
        "postTitle": "fixture",
        "subreddit": {"name": "MomCozy"},
        "score": 1,
        "commentCount": 0,
    }


def _payload(
    children: list[dict],
    *,
    has_next_page: bool,
) -> dict:
    return {
        "data": {
            "search": {
                "dynamic": {
                    "components": {
                        "main": {
                            "edges": [{"node": {"children": children}}],
                            "pageInfo": {
                                "endCursor": "cursor" if has_next_page else None,
                                "hasNextPage": has_next_page,
                            },
                        }
                    }
                }
            }
        }
    }


def _quarantine_payload() -> dict:
    return {
        "data": {
            "search": {
                "dynamic": {
                    "components": {
                        "main": {
                            "edges": [{"node": {"__typename": "SearchErrorMessage"}}],
                            "pageInfo": {
                                "endCursor": None,
                                "hasNextPage": False,
                            },
                        }
                    }
                }
            }
        }
    }


def _report(
    payload: dict,
    *,
    lane: int,
    term: str,
    captured_at: str = "2026-07-15T04:00:00Z",
    continuation_depth: int | None = None,
    quarantine: bool = False,
) -> dict:
    report = {
        "schema_version": "reddit_voc_search_lane_probe_v1",
        "run_id": "fixture-run",
        "lane_index": lane,
        "term": term,
        "endpoint": "/api/v1/reddit/app/fetch_dynamic_search",
        "http_status": 200,
        "captured_at_utc": captured_at,
        "response_validation": "passed",
        "payload_sha256": sha256(canonical_bytes(payload)).hexdigest(),
        "parsed_post_count": 0 if quarantine else 1,
        "unique_post_count": 0 if quarantine else 1,
        "post_ids": [] if quarantine else ["intentionally-not-trusted"],
        "payload": payload,
        "provider_attempt_made": True,
        "live_send": False,
        "production_merge": False,
        "git_push": False,
        "dingtalk": False,
    }
    if continuation_depth is not None:
        report["schema_version"] = "reddit_voc_search_continuation_probe_v1"
        report["continuation_depth"] = continuation_depth
    return report


def _identity_row(set_id: str, values: list[str]) -> dict:
    return {
        "set_id": set_id,
        "count": len(values),
        "sha256": identity_hash(values),
        "post_ids": values,
    }


class RedditV2IdentityFreezeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.reports_root = self.root / "reports"
        self.manifest_path = self.root / "report-file-manifest.json"
        self.inventory_path = self.root / "inventory.json"
        self.site_posts_path = self.root / "site-posts.json"

    def _write_inventory(
        self,
        *,
        materialized: list[str] | None = None,
        semantic: list[str] | None = None,
    ) -> None:
        _write_json(
            self.inventory_path,
            {
                "schema_version": "fixture-inventory-v1",
                "target_window_utc": {
                    "start": WINDOW_START,
                    "end": WINDOW_END,
                },
                "identity_sets": [
                    _identity_row("materialized", materialized or ["mat01"]),
                    _identity_row("baseline-semantic", semantic or ["base1"]),
                ],
            },
        )

    def _write_site(self, post_ids: list[str] | None = None) -> None:
        _write_json(
            self.site_posts_path,
            [{"post_id": post_id} for post_id in (post_ids or ["site1"])],
        )

    def _write_report(
        self, relative_path: str, report: dict
    ) -> Path:
        path = self.reports_root / relative_path
        _write_json(path, report)
        return path

    def _write_manifest(self) -> None:
        rows = []
        for path in sorted(self.reports_root.rglob("*")):
            if not path.is_file():
                continue
            rows.append(
                {
                    "relative_path": path.relative_to(self.reports_root).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": sha256(path.read_bytes()).hexdigest(),
                }
            )
        aggregate = "".join(
            f"{row['relative_path']}|{row['bytes']}|{row['sha256']}\n"
            for row in rows
        ).encode("utf-8")
        _write_json(
            self.manifest_path,
            {
                "schema_version": "reddit_voc_v2_report_file_manifest_v1",
                "freeze_cutoff_utc": MANIFEST_CUTOFF,
                "raw_payload_embedded_in_manifest": False,
                "file_count": len(rows),
                "total_bytes": sum(row["bytes"] for row in rows),
                "file_manifest_lf_sha256": sha256(aggregate).hexdigest(),
                "files": rows,
            },
        )

    def _build(self) -> dict:
        return build_identity_freeze(
            self.reports_root,
            self.manifest_path,
            self.inventory_path,
            self.site_posts_path,
            materialized_set_id="materialized",
            baseline_semantic_set_id="baseline-semantic",
            target_start_utc=WINDOW_START,
            target_end_utc=WINDOW_END,
            manifest_cutoff_utc=MANIFEST_CUTOFF,
            search_cutoff_utc=SEARCH_CUTOFF,
        )

    def test_crosspost_profile_quarantine_debt_and_set_relations(self) -> None:
        valid = _payload(
            [
                {"__typename": "SearchCrosspost", "post": _post("fresh1")},
                {
                    "__typename": "SearchPost",
                    "post": _post("end001", created_at=WINDOW_END),
                },
                {
                    "__typename": "SearchPost",
                    "post": _post("prof01", row_typename="ProfilePost"),
                },
            ],
            has_next_page=True,
        )
        self._write_report(
            "lane-1/search-lane-probe.json",
            _report(valid, lane=1, term="raw term must not survive"),
        )
        self._write_report(
            "lane-2/search-lane-probe.json",
            _report(
                _quarantine_payload(),
                lane=2,
                term="another raw term",
                quarantine=True,
            ),
        )
        self._write_inventory(
            materialized=["mat01", "fresh1"], semantic=["base1"]
        )
        self._write_site(["site1", "mat01"])
        self._write_manifest()

        snapshot = self._build()

        sets = {row["set_id"]: row for row in snapshot["identity_sets"]}
        self.assertEqual(sets["semantic"]["post_ids"], ["base1", "fresh1"])
        self.assertEqual(sets["materialized"]["post_ids"], ["fresh1", "mat01"])
        self.assertEqual(sets["discovery_only"]["post_ids"], ["base1"])
        self.assertEqual(
            sets["remote_union"]["post_ids"], ["base1", "fresh1", "mat01"]
        )
        self.assertEqual(
            sets["global_known"]["post_ids"],
            ["base1", "fresh1", "mat01", "site1"],
        )
        self.assertEqual(snapshot["net_new_vs_site"]["count"], 2)
        self.assertTrue(all(snapshot["set_relations"].values()))
        self.assertEqual(snapshot["search_semantics"]["profile_post_rows_excluded"], 1)
        self.assertEqual(snapshot["target_window_utc"]["interval"], "[start,end)")
        self.assertEqual(
            snapshot["search_semantics"]["v2_unique_strict_post_count_outside_window"],
            1,
        )
        self.assertNotIn("end001", sets["semantic"]["post_ids"])
        self.assertEqual(len(snapshot["quarantine"]), 1)
        self.assertEqual(
            snapshot["quarantine"][0]["reason"],
            "post_ids_zero_children_missing",
        )
        ledger = {row["lane_index"]: row for row in snapshot["coverage_ledger"]}
        self.assertTrue(ledger[1]["debt"])
        self.assertFalse(ledger[1]["terminal"])
        self.assertFalse(ledger[2]["debt"])
        self.assertTrue(ledger[2]["terminal"])
        rendered = canonical_bytes(snapshot).decode("utf-8")
        self.assertNotIn("raw term must not survive", rendered)
        self.assertNotIn("another raw term", rendered)
        self.assertNotIn("prof01", rendered)
        self.assertTrue(snapshot["boundaries"]["provider_call"] is False)
        self.assertTrue(snapshot["boundaries"]["database_write"] is False)

        output = self.root / "private" / "identity-freeze.json"
        first_sha = write_identity_freeze(snapshot, output)
        second_sha = write_identity_freeze(snapshot, output)
        self.assertEqual(first_sha, second_sha)
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)

    def test_rejects_report_captured_after_cutoff(self) -> None:
        payload = _payload(
            [{"__typename": "SearchPost", "post": _post("fresh1")}],
            has_next_page=False,
        )
        self._write_report(
            "lane-1/search-lane-probe.json",
            _report(
                payload,
                lane=1,
                term="fixture",
                captured_at="2026-07-15T04:15:20.214395Z",
            ),
        )
        self._write_inventory()
        self._write_site()
        self._write_manifest()

        with self.assertRaisesRegex(
            IdentityFreezeContractError, "search_report_after_freeze_cutoff"
        ):
            self._build()

    def test_rejects_report_byte_or_sha_drift(self) -> None:
        payload = _payload(
            [{"__typename": "SearchPost", "post": _post("fresh1")}],
            has_next_page=False,
        )
        report_path = self._write_report(
            "lane-1/search-lane-probe.json",
            _report(payload, lane=1, term="fixture"),
        )
        self._write_inventory()
        self._write_site()
        self._write_manifest()
        report_path.write_bytes(report_path.read_bytes() + b" ")

        with self.assertRaisesRegex(
            IdentityFreezeContractError, "report_manifest_file_bytes_mismatch"
        ):
            self._build()

    def test_rejects_manifest_aggregate_hash_drift(self) -> None:
        payload = _payload(
            [{"__typename": "SearchPost", "post": _post("fresh1")}],
            has_next_page=False,
        )
        self._write_report(
            "lane-1/search-lane-probe.json",
            _report(payload, lane=1, term="fixture"),
        )
        self._write_inventory()
        self._write_site()
        self._write_manifest()
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        manifest["file_manifest_lf_sha256"] = "0" * 64
        _write_json(self.manifest_path, manifest)

        with self.assertRaisesRegex(
            IdentityFreezeContractError,
            "report_manifest_aggregate_sha256_mismatch",
        ):
            self._build()

    def test_rejects_profile_row_if_it_is_not_exact_reviewed_typename(self) -> None:
        payload = _payload(
            [
                {
                    "__typename": "SearchPost",
                    "post": _post("other1", row_typename="OtherPost"),
                }
            ],
            has_next_page=False,
        )
        self._write_report(
            "lane-1/search-lane-probe.json",
            _report(payload, lane=1, term="fixture"),
        )
        self._write_inventory()
        self._write_site()
        self._write_manifest()

        with self.assertRaisesRegex(
            IdentityFreezeContractError, "search_row_typename_unreviewed"
        ):
            self._build()


if __name__ == "__main__":
    unittest.main()
