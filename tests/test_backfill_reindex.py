from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import reddit_voc.backfill_validation as validation
from reddit_voc.backfill_archive import PrivateRawArchive
from reddit_voc.backfill_models import (
    BackfillCheckpoint,
    BackfillManifest,
    discovery_occurrence_contract,
    required_lanes_sha256,
)
from reddit_voc.backfill_storage import BackfillStore
from reddit_voc.backfill_seed import import_seed_directory
from reddit_voc.backfill_seed import make_raw_capture_id
from reddit_voc.backfill_validation import (
    reindex_discovery_from_archive,
    replay_from_archive,
)
from reddit_voc.keywords import keyword_rules_sha256
from reddit_voc.models import RawCapture
from reddit_voc.tikhub import (
    FETCH_POST_COMMENTS,
    FETCH_POST_DETAILS_BATCH_LARGE,
    TikHubDiscoveryShapeError,
    _extract_backfill_discovery_posts,
    _extract_discovery_posts,
)


WINDOW_START = datetime(2024, 12, 31, 16, tzinfo=timezone.utc)
EFFECTIVE_END = datetime(2026, 7, 11, 4, 17, 9, tzinfo=timezone.utc)
CAPTURED_AT = datetime(2026, 7, 11, 4, 18, tzinfo=timezone.utc)
DYNAMIC_ENDPOINT = "/api/v1/reddit/app/fetch_dynamic_search"
TEST_TEMP_PARENT = Path(__file__).resolve().parents[1] / ".superpowers" / "sdd"


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _raw_inventory_sha256(root: Path) -> str:
    inventory = [
        [path.relative_to(root).as_posix(), _file_sha256(path)]
        for path in sorted(root.rglob("*"))
        if path.is_file()
    ]
    return sha256(_canonical_json_bytes(inventory)).hexdigest()


def _post(post_id: str) -> dict[str, object]:
    return {
        "id": f"t3_{post_id}",
        "postTitle": "Momcozy wearable pump advice",
        "url": (
            "https://www.reddit.com/r/ExclusivelyPumping/comments/"
            f"{post_id}/momcozy_wearable_pump_advice/"
        ),
        "createdAt": (WINDOW_START + timedelta(days=30)).isoformat(),
        "subreddit": {"name": "ExclusivelyPumping"},
    }


def _seed_payload(post_id: str) -> bytes:
    created_at = WINDOW_START + timedelta(days=1)
    payload = [
        {
            "kind": "Listing",
            "data": {
                "children": [
                    {
                        "kind": "t3",
                        "data": {
                            "id": post_id,
                            "name": f"t3_{post_id}",
                            "subreddit": "ExclusivelyPumping",
                            "title": "Momcozy structured seed",
                            "selftext": "Historical structured entity fixture.",
                            "permalink": (
                                "/r/ExclusivelyPumping/comments/"
                                f"{post_id}/structured_seed/"
                            ),
                            "created_utc": created_at.timestamp(),
                            "score": 3,
                            "num_comments": 0,
                            "author": "seed-author",
                        },
                    }
                ]
            },
        },
        {"kind": "Listing", "data": {"children": []}},
    ]
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )


def _reviewed_payload(
    post_id: str, *, end_cursor: str | None = None
) -> tuple[dict[str, object], tuple[str, ...]]:
    page_info = {
        "endCursor": end_cursor,
        "hasNextPage": end_cursor is not None,
    }
    cursor_path = (
        "data",
        "search",
        "dynamic",
        "components",
        "main",
        "pageInfo",
        "endCursor",
    )
    return (
        {
            "data": {
                "search": {
                    "dynamic": {
                        "components": {
                            "main": {
                                "pageInfo": page_info,
                                "edges": [
                                    {
                                        "node": {
                                            "children": [
                                                {
                                                    "__typename": "SearchPost",
                                                    "post": _post(post_id),
                                                    # The historical recursive parser
                                                    # misclassified this provider metadata
                                                    # as another discovery occurrence.
                                                    "metadata": {
                                                        "id": "provider_metadata_only"
                                                    },
                                                }
                                            ]
                                        }
                                    }
                                ],
                            }
                        }
                    }
                }
            }
        },
        cursor_path,
    )


def _reviewed_telemetry_wrapper() -> dict[str, object]:
    return {
        "__typename": "SearchTelemetryTrackingContext",
        "actionInfo": {},
        "answers": {},
        "metaSearch": {},
        "post": {
            "id": "telemetry_post",
            "isNsfw": False,
            "isSpoiler": False,
            "title": "telemetry metadata",
            "type": "post",
        },
        "profile": {},
        "search": {},
        "subreddit": {},
    }


def _reviewed_mixed_payload(
    post_id: str, *, end_cursor: str | None = None
) -> tuple[dict[str, object], tuple[str, ...]]:
    payload, cursor_path = _reviewed_payload(
        post_id, end_cursor=end_cursor
    )
    children = payload["data"]["search"]["dynamic"]["components"]["main"][  # type: ignore[index]
        "edges"
    ][0]["node"]["children"]  # type: ignore[index]
    first = children[0]
    first["telemetry"] = _reviewed_telemetry_wrapper()
    crosspost = {
        "__typename": "SearchCrosspost",
        "post": _post(post_id),
        "telemetry": _reviewed_telemetry_wrapper(),
    }
    crosspost["post"]["crosspostRoot"] = {"post": _post("lineage_root")}
    children.append(crosspost)
    return payload, cursor_path


def _unknown_payload(post_id: str) -> tuple[dict[str, object], tuple[str, ...]]:
    return (
        {
            "legacy": [_post(post_id)],
            "pageInfo": {"endCursor": None, "hasNextPage": False},
        },
        ("pageInfo", "endCursor"),
    )


class DiscoveryReindexTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_TEMP_PARENT.mkdir(parents=True, exist_ok=True)
        self._temporary = TemporaryDirectory(dir=TEST_TEMP_PARENT)
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)

    def test_strict_parser_accepts_reviewed_telemetry_metadata(self) -> None:
        payload, _cursor_path = _reviewed_payload("telemetry_candidate")
        child = payload["data"]["search"]["dynamic"]["components"]["main"][  # type: ignore[index]
            "edges"
        ][0]["node"]["children"][0]  # type: ignore[index]
        child["telemetry"] = _reviewed_telemetry_wrapper()

        try:
            posts = _extract_backfill_discovery_posts(
                payload, "tikhub_dynamic_search", dedupe=False
            )
        except TikHubDiscoveryShapeError as exc:
            self.fail(f"reviewed telemetry must be accepted: {exc}")

        self.assertEqual(
            [post.post_id for post in posts], ["telemetry_candidate"]
        )

    def test_strict_parser_accepts_search_crosspost(self) -> None:
        payload, _cursor_path = _reviewed_payload("crosspost_candidate")
        child = payload["data"]["search"]["dynamic"]["components"]["main"][  # type: ignore[index]
            "edges"
        ][0]["node"]["children"][0]  # type: ignore[index]
        child["__typename"] = "SearchCrosspost"

        try:
            posts = _extract_backfill_discovery_posts(
                payload, "tikhub_dynamic_search", dedupe=False
            )
        except TikHubDiscoveryShapeError as exc:
            self.fail(f"SearchCrosspost must be accepted: {exc}")

        self.assertEqual(
            [post.post_id for post in posts], ["crosspost_candidate"]
        )

    def test_strict_parser_accepts_exact_crosspost_root_as_lineage_only(self) -> None:
        payload, _cursor_path = _reviewed_payload("crosspost_candidate")
        child = payload["data"]["search"]["dynamic"]["components"]["main"][  # type: ignore[index]
            "edges"
        ][0]["node"]["children"][0]  # type: ignore[index]
        child["__typename"] = "SearchCrosspost"
        child["post"]["crosspostRoot"] = {"post": _post("lineage_root")}

        try:
            posts = _extract_backfill_discovery_posts(
                payload, "tikhub_dynamic_search", dedupe=False
            )
        except TikHubDiscoveryShapeError as exc:
            self.fail(f"exact crosspost root lineage must be accepted: {exc}")

        self.assertEqual(
            [post.post_id for post in posts], ["crosspost_candidate"]
        )

    def test_strict_parser_rejects_crosspost_root_outside_exact_contract(self) -> None:
        payload, _cursor_path = _reviewed_payload("crosspost_candidate")
        child = payload["data"]["search"]["dynamic"]["components"]["main"][  # type: ignore[index]
            "edges"
        ][0]["node"]["children"][0]  # type: ignore[index]
        child["__typename"] = "SearchCrosspost"
        child["post"]["crosspostRoot"] = {
            "post": _post("lineage_root"),
            "unexpected": {},
        }

        with self.assertRaisesRegex(
            TikHubDiscoveryShapeError,
            "TikHub dynamic search post container is ambiguous",
        ):
            _extract_backfill_discovery_posts(
                payload, "tikhub_dynamic_search", dedupe=False
            )

    def test_strict_parser_rejects_unreviewed_nested_post_wrapper(self) -> None:
        payload, _cursor_path = _reviewed_payload("unknown_wrapper")
        child = payload["data"]["search"]["dynamic"]["components"]["main"][  # type: ignore[index]
            "edges"
        ][0]["node"]["children"][0]  # type: ignore[index]
        child["unknown"] = {
            "__typename": "UnknownTrackingContext",
            "post": {"id": "unknown"},
        }

        with self.assertRaisesRegex(
            TikHubDiscoveryShapeError,
            "TikHub dynamic search post container is ambiguous",
        ):
            _extract_backfill_discovery_posts(
                payload, "tikhub_dynamic_search", dedupe=False
            )

    def test_strict_parser_rejects_telemetry_shape_drift(self) -> None:
        payload, _cursor_path = _reviewed_payload("telemetry_drift")
        child = payload["data"]["search"]["dynamic"]["components"]["main"][  # type: ignore[index]
            "edges"
        ][0]["node"]["children"][0]  # type: ignore[index]
        telemetry = _reviewed_telemetry_wrapper()
        telemetry.pop("profile")
        child["telemetry"] = telemetry

        with self.assertRaisesRegex(
            TikHubDiscoveryShapeError,
            "TikHub dynamic search post container is ambiguous",
        ):
            _extract_backfill_discovery_posts(
                payload, "tikhub_dynamic_search", dedupe=False
            )

    def test_strict_parser_rejects_telemetry_outside_content_wrapper(self) -> None:
        payload, _cursor_path = _reviewed_payload("telemetry_outside")
        payload["telemetry"] = _reviewed_telemetry_wrapper()

        with self.assertRaisesRegex(
            TikHubDiscoveryShapeError,
            "TikHub dynamic search post container is ambiguous",
        ):
            _extract_backfill_discovery_posts(
                payload, "tikhub_dynamic_search", dedupe=False
            )

    def _source(
        self,
        *,
        run_id: str,
        schema: str = "reviewed",
        first_response_cursor: str | None = None,
    ) -> tuple[BackfillStore, PrivateRawArchive, Path, str]:
        source_path = self.root / f"{run_id}-source.sqlite3"
        store = BackfillStore(source_path)
        store.migrate()
        store.create_manifest(
            BackfillManifest(
                run_id=run_id,
                status="prepared",
                window_start_utc=WINDOW_START.isoformat(),
                requested_end_utc=(EFFECTIVE_END + timedelta(hours=12)).isoformat(),
                effective_end_utc=EFFECTIVE_END.isoformat(),
                search_terms=("Momcozy",),
                subreddits=("ExclusivelyPumping",),
                include_subreddit_sweep=False,
                required_lanes_sha256=required_lanes_sha256(
                    search_terms=("Momcozy",),
                    subreddits=("ExclusivelyPumping",),
                    include_subreddit_sweep=False,
                ),
                keyword_config_sha256=keyword_rules_sha256(),
                max_provider_requests=1,
                provider_request_count=0,
                provider_call=False,
                live_send=False,
                created_at_utc=CAPTURED_AT.isoformat(),
                updated_at_utc=CAPTURED_AT.isoformat(),
            )
        )

        archive_writer = PrivateRawArchive(self.root / f"{run_id}-raw")
        seed_source = self.root / f"{run_id}-seed-source"
        seed_source.mkdir()
        (seed_source / "structured-seed.json").write_bytes(
            _seed_payload("structured_seed")
        )
        import_seed_directory(
            store,
            archive_writer,
            run_id=run_id,
            source_dir=seed_source,
            window_start_utc=WINDOW_START,
            effective_end_utc=EFFECTIVE_END,
            captured_at_utc=CAPTURED_AT - timedelta(seconds=1),
        )

        post_id = "strict_candidate"
        if schema == "reviewed":
            payload, cursor_path = _reviewed_payload(
                post_id, end_cursor=first_response_cursor
            )
        elif schema == "mixed":
            payload, cursor_path = _reviewed_mixed_payload(
                post_id, end_cursor=first_response_cursor
            )
        else:
            payload, cursor_path = _unknown_payload(post_id)
        payload_bytes = _canonical_json_bytes(payload)
        payload_sha = sha256(payload_bytes).hexdigest()
        source_url = validation._replay_tikhub_source_url(
            run_id=run_id,
            lane_type="dynamic_search",
            lane_key="Momcozy",
            endpoint=DYNAMIC_ENDPOINT,
            page_number=1,
            request_cursor=None,
        )
        raw_capture_id = "raw_backfill_" + sha256(
            "\0".join(
                (run_id, "tikhub_dynamic_search", source_url, payload_sha)
            ).encode("utf-8")
        ).hexdigest()[:24]
        artifact = archive_writer.write(
            run_id=run_id,
            artifact_kind="discovery",
            lane_type="dynamic_search",
            lane_key="Momcozy",
            identity=source_url.removeprefix("tikhub://"),
            payload=payload_bytes,
            raw_capture_id=raw_capture_id,
            parser_kind="tikhub_discovery",
            source_method="tikhub_dynamic_search",
            source_url=source_url,
            source_endpoint=DYNAMIC_ENDPOINT,
            captured_at_utc=CAPTURED_AT,
            page_number=1,
            request_cursor=None,
            response_cursor=first_response_cursor,
        )
        store.persist_raw_capture_artifact(
            RawCapture(
                raw_capture_id=raw_capture_id,
                run_id=run_id,
                source_method="tikhub_dynamic_search",
                source_url=source_url,
                captured_at_utc=CAPTURED_AT,
                auth_boundary="provider_gate",
                raw_payload_hash=f"sha256:{payload_sha}",
                payload_format="json",
            ),
            artifact,
        )

        broad_posts = _extract_discovery_posts(
            payload, "tikhub_dynamic_search", dedupe=False
        )
        for ordinal, post in enumerate(broad_posts):
            disposition, normalized_id, normalized_url, created_at = (
                discovery_occurrence_contract(
                    post_id=post.post_id,
                    source_url=post.source_url,
                    title=post.title,
                    created_at_utc=post.created_at_utc,
                    window_start_utc=WINDOW_START,
                    window_end_utc=EFFECTIVE_END,
                )
            )
            store.record_discovery_occurrence(
                run_id=run_id,
                lane_type="dynamic_search",
                lane_key="Momcozy",
                page_number=1,
                ordinal=ordinal,
                post_id=normalized_id,
                source_url=normalized_url,
                post_created_at_utc=created_at,
                raw_artifact_id=artifact.artifact_id,
                discovered_at_utc=CAPTURED_AT,
                base_disposition=disposition,
            )
        request_number = store.reserve_provider_request(
            run_id, DYNAMIC_ENDPOINT, CAPTURED_AT
        )
        store.mark_provider_attempt_sent(run_id, request_number, CAPTURED_AT)
        store.complete_provider_attempt(
            run_id,
            request_number,
            status="succeeded",
            completed_at_utc=CAPTURED_AT,
            http_status=200,
        )
        page_info: object = payload
        for component in cursor_path[:-1]:
            page_info = page_info[component]  # type: ignore[index]
        store.save_checkpoint(
            BackfillCheckpoint(
                run_id=run_id,
                lane_type="dynamic_search",
                lane_key="Momcozy",
                cursor=first_response_cursor,
                previous_cursor=None,
                page_number=1,
                newest_seen_utc=(WINDOW_START + timedelta(days=30)).isoformat(),
                oldest_seen_utc=(WINDOW_START + timedelta(days=30)).isoformat(),
                discovered_count=len(broad_posts),
                unique_count=1,
                provider_request_count=1,
                last_success_utc=CAPTURED_AT.isoformat(),
                last_error=None,
                status=(
                    "complete" if first_response_cursor is None else "partial"
                ),
                stop_reason=(
                    "cursor_exhausted"
                    if first_response_cursor is None
                    else "round_robin_yield"
                ),
                cursor_json_path=json.dumps(cursor_path, separators=(",", ":")),
                cursor_schema_sha256=validation._page_info_schema_sha256(
                    page_info  # type: ignore[arg-type]
                ),
                consecutive_old_pages=0,
            )
        )

        # A terminal failed batch makes status/member preservation observable
        # without inventing a detail artifact.
        batch = store.prepare_detail_batches(
            run_id=run_id,
            post_ids=(post_id,),
            created_at_utc=CAPTURED_AT + timedelta(seconds=1),
        )[0]
        store.finish_detail_batch(
            run_id=run_id,
            batch_id=batch.batch_id,
            status="failed",
            stop_reason="provider_error",
            updated_at_utc=CAPTURED_AT + timedelta(seconds=2),
        )
        store.finalize_candidate(
            run_id=run_id,
            post_id=post_id,
            expected_statuses=("pending",),
            status="failed",
            status_reason="provider_error",
            updated_at_utc=CAPTURED_AT + timedelta(seconds=2),
        )
        return (
            store,
            PrivateRawArchive(archive_writer.root, read_only=True),
            archive_writer.root,
            post_id,
        )

    def _persist_discovery_page(
        self,
        *,
        store: BackfillStore,
        archive: PrivateRawArchive,
        run_id: str,
        lane_key: str,
        page_number: int,
        request_cursor: str | None,
        response_cursor: str | None,
        post_id: str,
        captured_at_utc: datetime,
    ) -> tuple[int, tuple[str, ...], object]:
        payload, cursor_path = _reviewed_payload(
            post_id, end_cursor=response_cursor
        )
        payload_bytes = _canonical_json_bytes(payload)
        payload_sha = sha256(payload_bytes).hexdigest()
        source_url = validation._replay_tikhub_source_url(
            run_id=run_id,
            lane_type="dynamic_search",
            lane_key=lane_key,
            endpoint=DYNAMIC_ENDPOINT,
            page_number=page_number,
            request_cursor=request_cursor,
        )
        raw_capture_id = "raw_backfill_" + sha256(
            "\0".join(
                (run_id, "tikhub_dynamic_search", source_url, payload_sha)
            ).encode("utf-8")
        ).hexdigest()[:24]
        artifact = archive.write(
            run_id=run_id,
            artifact_kind="discovery",
            lane_type="dynamic_search",
            lane_key=lane_key,
            identity=source_url.removeprefix("tikhub://"),
            payload=payload_bytes,
            raw_capture_id=raw_capture_id,
            parser_kind="tikhub_discovery",
            source_method="tikhub_dynamic_search",
            source_url=source_url,
            source_endpoint=DYNAMIC_ENDPOINT,
            captured_at_utc=captured_at_utc,
            page_number=page_number,
            request_cursor=request_cursor,
            response_cursor=response_cursor,
        )
        store.persist_raw_capture_artifact(
            RawCapture(
                raw_capture_id=raw_capture_id,
                run_id=run_id,
                source_method="tikhub_dynamic_search",
                source_url=source_url,
                captured_at_utc=captured_at_utc,
                auth_boundary="provider_gate",
                raw_payload_hash=f"sha256:{payload_sha}",
                payload_format="json",
            ),
            artifact,
        )
        broad_posts = _extract_discovery_posts(
            payload, "tikhub_dynamic_search", dedupe=False
        )
        for ordinal, post in enumerate(broad_posts):
            disposition, normalized_id, normalized_url, created_at = (
                discovery_occurrence_contract(
                    post_id=post.post_id,
                    source_url=post.source_url,
                    title=post.title,
                    created_at_utc=post.created_at_utc,
                    window_start_utc=WINDOW_START,
                    window_end_utc=EFFECTIVE_END,
                )
            )
            store.record_discovery_occurrence(
                run_id=run_id,
                lane_type="dynamic_search",
                lane_key=lane_key,
                page_number=page_number,
                ordinal=ordinal,
                post_id=normalized_id,
                source_url=normalized_url,
                post_created_at_utc=created_at,
                raw_artifact_id=artifact.artifact_id,
                discovered_at_utc=captured_at_utc,
                base_disposition=disposition,
            )
        request_number = store.reserve_provider_request(
            run_id, DYNAMIC_ENDPOINT, captured_at_utc
        )
        store.mark_provider_attempt_sent(run_id, request_number, captured_at_utc)
        store.complete_provider_attempt(
            run_id,
            request_number,
            status="succeeded",
            completed_at_utc=captured_at_utc,
            http_status=200,
        )
        page_info: object = payload
        for component in cursor_path[:-1]:
            page_info = page_info[component]  # type: ignore[index]
        return len(broad_posts), cursor_path, page_info

    @staticmethod
    def _rows(path: Path, table: str, run_id: str) -> list[tuple[object, ...]]:
        with sqlite3.connect(path) as connection:
            return connection.execute(
                f"SELECT * FROM {table} WHERE run_id=? ORDER BY rowid", (run_id,)
            ).fetchall()

    def _assert_no_reindex_residue(self) -> None:
        self.assertEqual(list(self.root.glob(".discovery-reindex-*")), [])
        self.assertEqual(list(self.root.glob(".replay-*")), [])

    def test_multi_lane_capture_order_rejects_ties_and_lane_time_reversal(self):
        run_id = "reindex_capture_order_contract"
        store, _archive, _raw_root, _post_id = self._source(run_id=run_id)
        first = store.load_raw_artifacts(
            run_id=run_id,
            lane_type="dynamic_search",
            lane_key="Momcozy",
        )[0]
        lane_a = ("dynamic_search", "Momcozy")
        lane_b = ("dynamic_search", "wearable breast pump")
        second_a = replace(
            first,
            artifact_id="raw_artifact_second_a",
            page_number=2,
            captured_at_utc=(CAPTURED_AT + timedelta(seconds=2)).isoformat(),
        )
        tied_b = replace(
            first,
            artifact_id="raw_artifact_tied_b",
            page_number=1,
        )
        with self.assertRaisesRegex(ValueError, "capture order invalid"):
            validation._ordered_discovery_artifact_ids(
                {lane_a: [first, second_a], lane_b: [tied_b]}
            )

        reversed_a = replace(
            second_a,
            captured_at_utc=(CAPTURED_AT - timedelta(seconds=1)).isoformat(),
        )
        later_b = replace(
            tied_b,
            captured_at_utc=(CAPTURED_AT + timedelta(seconds=1)).isoformat(),
        )
        with self.assertRaisesRegex(ValueError, "capture order invalid"):
            validation._ordered_discovery_artifact_ids(
                {lane_a: [first, reversed_a], lane_b: [later_b]}
            )

    def test_single_lane_capture_order_keeps_page_order_for_legacy_ties(self):
        run_id = "reindex_single_lane_capture_order"
        store, _archive, _raw_root, _post_id = self._source(run_id=run_id)
        first = store.load_raw_artifacts(
            run_id=run_id,
            lane_type="dynamic_search",
            lane_key="Momcozy",
        )[0]
        second = replace(
            first,
            artifact_id="raw_artifact_second_page",
            page_number=2,
        )

        ordered = validation._ordered_discovery_artifact_ids(
            {("dynamic_search", "Momcozy"): [second, first]}
        )

        self.assertEqual(ordered, [first.artifact_id, second.artifact_id])

    def _uncommitted_schema_drift_source(
        self, *, run_id: str
    ) -> tuple[BackfillStore, PrivateRawArchive, str]:
        store, archive, _raw_root, post_id = self._source(
            run_id=run_id,
            first_response_cursor="recovered-cursor",
        )
        with sqlite3.connect(store.path) as connection:
            connection.execute(
                "DELETE FROM backfill_detail_batch_members WHERE run_id=?",
                (run_id,),
            )
            connection.execute(
                "DELETE FROM backfill_detail_batches WHERE run_id=?",
                (run_id,),
            )
            connection.execute(
                "DELETE FROM backfill_discovery_occurrences WHERE run_id=?",
                (run_id,),
            )
            connection.execute(
                "DELETE FROM backfill_candidates WHERE run_id=?",
                (run_id,),
            )
            connection.execute(
                "UPDATE backfill_raw_artifacts SET response_cursor=NULL "
                "WHERE run_id=? AND artifact_kind='discovery'",
                (run_id,),
            )
            connection.execute(
                "UPDATE backfill_checkpoints SET cursor=NULL, "
                "previous_cursor=NULL, page_number=0, newest_seen_utc=NULL, "
                "oldest_seen_utc=NULL, discovered_count=0, unique_count=0, "
                "last_success_utc=NULL, last_error='TikHubSchemaDrift', "
                "provider_request_count=1, "
                "status='partial', stop_reason='schema_drift', "
                "cursor_json_path=NULL, cursor_schema_sha256=NULL, "
                "consecutive_old_pages=0 "
                "WHERE run_id=? AND lane_type='dynamic_search'",
                (run_id,),
            )
        return store, archive, post_id

    def _multi_lane_uncommitted_schema_drift_source(
        self, *, run_id: str
    ) -> tuple[BackfillStore, PrivateRawArchive, tuple[str, str]]:
        second_lane = "wearable breast pump"
        store, _archive, raw_root, first_post_id = self._source(
            run_id=run_id,
            first_response_cursor="recovered-cursor-a",
        )
        search_terms = ("Momcozy", second_lane)
        with sqlite3.connect(store.path) as connection:
            connection.execute(
                "UPDATE backfill_manifests SET search_terms_json=?, "
                "required_lanes_sha256=?, max_provider_requests=4 "
                "WHERE run_id=?",
                (
                    json.dumps(
                        list(search_terms),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    required_lanes_sha256(
                        search_terms=search_terms,
                        subreddits=("ExclusivelyPumping",),
                        include_subreddit_sweep=False,
                    ),
                    run_id,
                ),
            )

        second_post_id = "strict_candidate_second_lane"
        archive_writer = PrivateRawArchive(raw_root)
        discovered_count, cursor_path, page_info = self._persist_discovery_page(
            store=store,
            archive=archive_writer,
            run_id=run_id,
            lane_key=second_lane,
            page_number=1,
            request_cursor=None,
            response_cursor="recovered-cursor-b",
            post_id=second_post_id,
            captured_at_utc=CAPTURED_AT + timedelta(seconds=1),
        )
        store.save_checkpoint(
            BackfillCheckpoint(
                run_id=run_id,
                lane_type="dynamic_search",
                lane_key=second_lane,
                cursor="recovered-cursor-b",
                previous_cursor=None,
                page_number=1,
                newest_seen_utc=(
                    WINDOW_START + timedelta(days=30)
                ).isoformat(),
                oldest_seen_utc=(
                    WINDOW_START + timedelta(days=30)
                ).isoformat(),
                discovered_count=discovered_count,
                unique_count=1,
                provider_request_count=2,
                last_success_utc=(CAPTURED_AT + timedelta(seconds=1)).isoformat(),
                last_error=None,
                status="partial",
                stop_reason="round_robin_yield",
                cursor_json_path=json.dumps(cursor_path, separators=(",", ":")),
                cursor_schema_sha256=validation._page_info_schema_sha256(
                    page_info  # type: ignore[arg-type]
                ),
                consecutive_old_pages=0,
            )
        )
        for endpoint, attempted_at in (
            (FETCH_POST_DETAILS_BATCH_LARGE, CAPTURED_AT + timedelta(seconds=2)),
            (FETCH_POST_COMMENTS, CAPTURED_AT + timedelta(seconds=3)),
        ):
            request_number = store.reserve_provider_request(
                run_id, endpoint, attempted_at
            )
            self.assertIsNotNone(request_number)
            store.mark_provider_attempt_sent(run_id, request_number, attempted_at)
            store.complete_provider_attempt(
                run_id,
                request_number,
                status="succeeded",
                completed_at_utc=attempted_at,
                http_status=200,
            )

        with sqlite3.connect(store.path) as connection:
            connection.execute(
                "UPDATE backfill_raw_artifacts SET response_cursor=NULL "
                "WHERE run_id=? AND artifact_kind='discovery'",
                (run_id,),
            )
            connection.execute(
                "UPDATE backfill_checkpoints SET cursor=NULL, "
                "previous_cursor=NULL, page_number=0, newest_seen_utc=NULL, "
                "oldest_seen_utc=NULL, discovered_count=0, unique_count=0, "
                "last_success_utc=NULL, last_error='TikHubSchemaDrift', "
                "status='partial', stop_reason='schema_drift', "
                "cursor_json_path=NULL, cursor_schema_sha256=NULL, "
                "consecutive_old_pages=0 "
                "WHERE run_id=? AND lane_type='dynamic_search'",
                (run_id,),
            )
            connection.execute(
                "UPDATE backfill_checkpoints SET provider_request_count=1 "
                "WHERE run_id=? AND lane_type='dynamic_search' AND lane_key='Momcozy'",
                (run_id,),
            )
            connection.execute(
                "UPDATE backfill_checkpoints SET provider_request_count=2 "
                "WHERE run_id=? AND lane_type='dynamic_search' AND lane_key=?",
                (run_id, second_lane),
            )
            connection.execute(
                "UPDATE backfill_candidates SET status='failed', "
                "status_reason='comments_schema_drift' WHERE run_id=?",
                (run_id,),
            )

        return (
            store,
            PrivateRawArchive(raw_root, read_only=True),
            (first_post_id, second_post_id),
        )

    def _task24_recovery_source(
        self, *, run_id: str, discovery_schema_drift: bool = True
    ) -> tuple[BackfillStore, PrivateRawArchive, Path, str]:
        store, _read_only_archive, raw_root, post_id = self._source(
            run_id=run_id,
            first_response_cursor="recovered-cursor",
        )
        archive = PrivateRawArchive(raw_root)
        batch = store.load_detail_batches(run_id=run_id)[0]
        detail_payload = {
            "data": {
                "postsInfoByIds": [
                    {
                        "id": f"t3_{post_id}",
                        "createdAt": (WINDOW_START + timedelta(days=30)).isoformat(),
                        "postTitle": "Momcozy archived recovery post",
                        "url": (
                            "https://www.reddit.com/r/ExclusivelyPumping/comments/"
                            f"{post_id}/archived_recovery/"
                        ),
                        "content": {"markdown": "Archived Momcozy body."},
                        "score": 7,
                        "commentCount": 9,
                        "subreddit": {"name": "ExclusivelyPumping"},
                        "authorInfo": {"name": "submitter"},
                    }
                ]
            }
        }
        comment_page_info = {"commentCount": 2, "hasNextPage": True}
        comments_payload = {
            "data": {
                "postInfoById": {
                    "id": f"t3_{post_id}",
                    "commentForest": {
                        "__typename": "CommentForest",
                        "pageInfo": comment_page_info,
                        "trees": [
                            {
                                "depth": 0,
                                "parentId": f"t3_{post_id}",
                                "node": {
                                    "__typename": "Comment",
                                    "id": "archived-comment-1",
                                    "createdAt": (
                                        WINDOW_START + timedelta(days=31)
                                    ).isoformat(),
                                    "content": {
                                        "markdown": "Archived Momcozy comment."
                                    },
                                    "authorInfo": {"name": "helper"},
                                    "score": 3,
                                },
                            },
                            {
                                "childCount": 1,
                                "depth": 0,
                                "more": {"children": []},
                                "node": None,
                                "parentId": f"t3_{post_id}",
                            },
                        ],
                    },
                }
            }
        }

        def persist(
            *,
            artifact_kind: str,
            lane_type: str,
            lane_key: str,
            endpoint: str,
            source_method: str,
            parser_kind: str,
            page_number: int,
            payload: dict[str, object],
            captured_at: datetime,
        ):
            payload_bytes = _canonical_json_bytes(payload)
            payload_sha = sha256(payload_bytes).hexdigest()
            source_url = validation._replay_tikhub_source_url(
                run_id=run_id,
                lane_type=lane_type,
                lane_key=lane_key,
                endpoint=endpoint,
                page_number=page_number,
                request_cursor=None,
            )
            raw_capture_id = make_raw_capture_id(
                run_id=run_id,
                source_method=source_method,
                source_url=source_url,
                payload_sha256=payload_sha,
            )
            artifact = archive.write(
                run_id=run_id,
                artifact_kind=artifact_kind,
                lane_type=lane_type,
                lane_key=lane_key,
                identity=source_url.removeprefix("tikhub://"),
                payload=payload_bytes,
                raw_capture_id=raw_capture_id,
                parser_kind=parser_kind,
                source_method=source_method,
                source_url=source_url,
                source_endpoint=endpoint,
                captured_at_utc=captured_at,
                page_number=page_number,
                request_cursor=None,
                response_cursor=None,
            )
            store.persist_raw_capture_artifact(
                RawCapture(
                    raw_capture_id=raw_capture_id,
                    run_id=run_id,
                    source_method=source_method,
                    source_url=source_url,
                    captured_at_utc=captured_at,
                    auth_boundary="provider_gate",
                    raw_payload_hash=f"sha256:{payload_sha}",
                    payload_format="json",
                ),
                artifact,
            )
            return artifact

        detail_artifact = persist(
            artifact_kind="detail",
            lane_type="detail_batch",
            lane_key=batch.batch_id,
            endpoint=FETCH_POST_DETAILS_BATCH_LARGE,
            source_method="tikhub_detail",
            parser_kind="tikhub_detail",
            page_number=batch.batch_number,
            payload=detail_payload,
            captured_at=CAPTURED_AT + timedelta(seconds=3),
        )
        persist(
            artifact_kind="comments",
            lane_type="comments",
            lane_key=post_id,
            endpoint=FETCH_POST_COMMENTS,
            source_method="tikhub_comments",
            parser_kind="tikhub_comments",
            page_number=1,
            payload=comments_payload,
            captured_at=CAPTURED_AT + timedelta(seconds=4),
        )
        with sqlite3.connect(store.path) as connection:
            connection.execute(
                "UPDATE backfill_manifests SET max_provider_requests=3 "
                "WHERE run_id=?",
                (run_id,),
            )
            if discovery_schema_drift:
                connection.execute(
                    "UPDATE backfill_raw_artifacts SET response_cursor=NULL "
                    "WHERE run_id=? AND artifact_kind='discovery'",
                    (run_id,),
                )
                connection.execute(
                    "UPDATE backfill_checkpoints SET cursor=NULL, "
                    "previous_cursor=NULL, page_number=0, newest_seen_utc=NULL, "
                    "oldest_seen_utc=NULL, discovered_count=0, unique_count=0, "
                    "last_success_utc=NULL, last_error='TikHubSchemaDrift', "
                    "provider_request_count=1, "
                    "status='partial', stop_reason='schema_drift', "
                    "cursor_json_path=NULL, cursor_schema_sha256=NULL, "
                    "consecutive_old_pages=0 "
                    "WHERE run_id=? AND lane_type='dynamic_search'",
                    (run_id,),
                )
            connection.execute(
                "UPDATE backfill_candidates SET status='failed', "
                "status_reason='comments_schema_drift' WHERE run_id=?",
                (run_id,),
            )
            connection.execute(
                "UPDATE backfill_detail_batches SET status='failed', "
                "artifact_id=?, stop_reason='comments_schema_drift' "
                "WHERE run_id=?",
                (detail_artifact.artifact_id, run_id),
            )
        for endpoint, captured_at in (
            (FETCH_POST_DETAILS_BATCH_LARGE, CAPTURED_AT + timedelta(seconds=3)),
            (FETCH_POST_COMMENTS, CAPTURED_AT + timedelta(seconds=4)),
        ):
            request_number = store.reserve_provider_request(
                run_id, endpoint, captured_at
            )
            self.assertIsNotNone(request_number)
            store.mark_provider_attempt_sent(run_id, request_number, captured_at)
            store.complete_provider_attempt(
                run_id,
                request_number,
                status="succeeded",
                completed_at_utc=captured_at,
                http_status=200,
            )
        store.save_checkpoint(
            BackfillCheckpoint(
                run_id=run_id,
                lane_type="comments",
                lane_key=post_id,
                cursor=None,
                previous_cursor=None,
                page_number=0,
                newest_seen_utc=None,
                oldest_seen_utc=None,
                discovered_count=0,
                unique_count=0,
                provider_request_count=3,
                last_success_utc=None,
                last_error="TikHubSchemaDrift",
                status="partial",
                stop_reason="comments_schema_drift",
                cursor_json_path=json.dumps(
                    [
                        "data",
                        "postInfoById",
                        "commentForest",
                        "pageInfo",
                        "endCursor",
                    ],
                    separators=(",", ":"),
                ),
                cursor_schema_sha256=validation._page_info_schema_sha256(
                    comment_page_info
                ),
                consecutive_old_pages=0,
            )
        )
        store.set_backfill_status(
            run_id, "partial", CAPTURED_AT + timedelta(seconds=5)
        )
        return (
            store,
            PrivateRawArchive(raw_root, read_only=True),
            raw_root,
            post_id,
        )

    def test_recovery_plan_accepts_only_one_uncommitted_schema_drift_page(self):
        run_id = "reindex_recover_uncommitted_page"
        store, archive, post_id = self._uncommitted_schema_drift_source(
            run_id=run_id
        )
        snapshot = validation._load_reindex_snapshot(
            store.path, archive=archive, run_id=run_id
        )

        with self.assertRaisesRegex(
            validation._DiscoveryReindexDataError,
            "strict_discovery_page_chain_invalid",
        ):
            validation._plan_strict_discovery_reindex(snapshot)

        plan = validation._plan_strict_discovery_reindex(
            snapshot, allow_schema_drift_recovery=True
        )

        self.assertEqual(set(plan["candidate_first"]), {post_id})
        self.assertEqual(plan["new_candidate_ids"], {post_id})
        self.assertEqual(
            plan["artifact_response_cursors"],
            {next(iter(plan["artifact_ids"])): "recovered-cursor"},
        )
        update = plan["checkpoint_updates"][("dynamic_search", "Momcozy")]
        self.assertEqual(update["page_number"], 1)
        self.assertEqual(update["cursor"], "recovered-cursor")
        self.assertEqual(update["status"], "partial")
        self.assertEqual(update["stop_reason"], "round_robin_yield")

        drifted = dict(snapshot)
        drifted_rows = {
            table: [dict(row) for row in rows]
            for table, rows in snapshot["rows"].items()
        }
        drifted_rows["backfill_checkpoints"][0]["stop_reason"] = "provider_error"
        drifted["rows"] = drifted_rows
        with self.assertRaisesRegex(
            validation._DiscoveryReindexDataError,
            "strict_discovery_page_chain_invalid",
        ):
            validation._plan_strict_discovery_reindex(
                drifted, allow_schema_drift_recovery=True
            )

    def test_recovery_plan_binds_multiple_schema_drift_lanes_to_earlier_attempts(
        self,
    ) -> None:
        run_id = "reindex_recover_multiple_attempts"
        store, archive, post_ids = self._multi_lane_uncommitted_schema_drift_source(
            run_id=run_id
        )
        snapshot = validation._load_reindex_snapshot(
            store.path, archive=archive, run_id=run_id
        )

        plan = validation._plan_strict_discovery_reindex(
            snapshot, allow_schema_drift_recovery=True
        )

        self.assertEqual(
            plan["recovered_lanes"],
            {
                ("dynamic_search", "Momcozy"),
                ("dynamic_search", "wearable breast pump"),
            },
        )
        self.assertEqual(set(plan["candidate_first"]), set(post_ids))
        self.assertEqual(snapshot["manifest"]["provider_request_count"], 4)
        self.assertEqual(
            {
                row["provider_request_count"]
                for row in snapshot["rows"]["backfill_checkpoints"]
                if row["lane_type"] == "dynamic_search"
            },
            {1, 2},
        )

    def test_recovery_plan_rejects_invalid_schema_drift_attempt_binding(
        self,
    ) -> None:
        cases = (
            "missing",
            "failed",
            "out_of_range",
            "endpoint_mismatch",
            "boolean_request_number",
            "run_id_mismatch",
        )
        for case in cases:
            with self.subTest(case=case):
                run_id = f"reindex_recover_attempt_{case}"
                store, archive, _post_id = self._uncommitted_schema_drift_source(
                    run_id=run_id
                )
                snapshot = validation._load_reindex_snapshot(
                    store.path, archive=archive, run_id=run_id
                )
                rows = {
                    table: [dict(row) for row in table_rows]
                    for table, table_rows in snapshot["rows"].items()
                }
                manifest = dict(snapshot["manifest"])
                if case == "missing":
                    rows["backfill_provider_attempts"] = []
                elif case == "failed":
                    rows["backfill_provider_attempts"][0]["status"] = "failed"
                    rows["backfill_provider_attempts"][0][
                        "error_class"
                    ] = "TikHubProviderError"
                elif case == "out_of_range":
                    rows["backfill_checkpoints"][0]["provider_request_count"] = 0
                    manifest["provider_request_count"] = 0
                else:
                    if case == "endpoint_mismatch":
                        rows["backfill_provider_attempts"][0]["endpoint"] = (
                            FETCH_POST_DETAILS_BATCH_LARGE
                        )
                    elif case == "boolean_request_number":
                        rows["backfill_provider_attempts"][0][
                            "request_number"
                        ] = True
                    else:
                        rows["backfill_provider_attempts"][0]["run_id"] = (
                            "different_run"
                        )
                drifted = {**snapshot, "manifest": manifest, "rows": rows}

                with self.assertRaisesRegex(
                    validation._DiscoveryReindexDataError,
                    "strict_discovery_provider_attempt_invalid",
                ):
                    validation._plan_strict_discovery_reindex(
                        drifted, allow_schema_drift_recovery=True
                    )

    def test_failure_aware_recovery_postflight_preserves_failed_status(self) -> None:
        postflight = getattr(
            validation, "validate_collection_recovery_postflight", None
        )
        self.assertTrue(callable(postflight), "recovery postflight contract missing")
        report_name = "task27-collection-recovery.json"

        result = postflight(
            recovery={
                "schema_version": "backfill_collection_recovery_v1",
                "status": "failed",
                "stop_reason": "strict_discovery_page_chain_invalid",
                "provider_call": False,
                "provider_attempt_made": False,
                "database_write": False,
                "live_send": False,
                "target_db_sha256": None,
            },
            recovery_exit_code=1,
            result_report_match=True,
            source_database_unchanged=True,
            source_raw_unchanged=True,
            provider_ledger_unchanged=True,
            production_unchanged=True,
            target_database_name="recovered.sqlite3",
            target_database_present=False,
            target_database_sha256=None,
            target_residue=(report_name,),
            recovery_report_name=report_name,
            active_operation_process_count=0,
            one_shot_container_count=0,
        )

        self.assertEqual(result["postflight_status"], "verified")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(
            result["stop_reason"], "strict_discovery_page_chain_invalid"
        )
        self.assertFalse(result["target_database_published"])
        self.assertFalse(result["database_write"])
        self.assertTrue(result["all_invariants_passed"])

    def test_failure_aware_recovery_postflight_rejects_failed_target_residue(
        self,
    ) -> None:
        postflight = getattr(
            validation, "validate_collection_recovery_postflight", None
        )
        self.assertTrue(callable(postflight), "recovery postflight contract missing")

        with self.assertRaisesRegex(
            ValueError, "collection_recovery_postflight_invalid"
        ):
            postflight(
                recovery={
                    "schema_version": "backfill_collection_recovery_v1",
                    "status": "failed",
                    "stop_reason": "strict_discovery_page_chain_invalid",
                    "provider_call": False,
                    "provider_attempt_made": False,
                    "database_write": False,
                    "live_send": False,
                    "target_db_sha256": None,
                },
                recovery_exit_code=1,
                result_report_match=True,
                source_database_unchanged=True,
                source_raw_unchanged=True,
                provider_ledger_unchanged=True,
                production_unchanged=True,
                target_database_name="recovered.sqlite3",
                target_database_present=True,
                target_database_sha256="a" * 64,
                target_residue=(
                    "recovered.sqlite3",
                    "task27-collection-recovery.json",
                ),
                recovery_report_name="task27-collection-recovery.json",
                active_operation_process_count=0,
                one_shot_container_count=0,
            )

    def test_failure_aware_recovery_postflight_keeps_success_contract(self) -> None:
        postflight = getattr(
            validation, "validate_collection_recovery_postflight", None
        )
        self.assertTrue(callable(postflight), "recovery postflight contract missing")
        target_name = "recovered.sqlite3"
        report_name = "task27-collection-recovery.json"

        result = postflight(
            recovery={
                "schema_version": "backfill_collection_recovery_v1",
                "status": "complete",
                "stop_reason": "collection_recovery_complete",
                "provider_call": False,
                "provider_attempt_made": False,
                "database_write": "recovery_target_only",
                "live_send": False,
                "target_db_sha256": "b" * 64,
            },
            recovery_exit_code=0,
            result_report_match=True,
            source_database_unchanged=True,
            source_raw_unchanged=True,
            provider_ledger_unchanged=True,
            production_unchanged=True,
            target_database_name=target_name,
            target_database_present=True,
            target_database_sha256="b" * 64,
            target_residue=tuple(sorted((target_name, report_name))),
            recovery_report_name=report_name,
            active_operation_process_count=0,
            one_shot_container_count=0,
        )

        self.assertEqual(result["postflight_status"], "verified")
        self.assertEqual(result["status"], "complete")
        self.assertTrue(result["target_database_published"])
        self.assertEqual(result["database_write"], "recovery_target_only")

    def test_failure_aware_recovery_postflight_rejects_malformed_status(
        self,
    ) -> None:
        postflight = getattr(
            validation, "validate_collection_recovery_postflight", None
        )
        self.assertTrue(callable(postflight), "recovery postflight contract missing")

        with self.assertRaisesRegex(
            ValueError, "collection_recovery_postflight_invalid"
        ):
            postflight(
                recovery={
                    "schema_version": "backfill_collection_recovery_v1",
                    "status": {},
                    "stop_reason": "strict_discovery_page_chain_invalid",
                    "provider_call": False,
                    "provider_attempt_made": False,
                    "database_write": False,
                    "live_send": False,
                    "target_db_sha256": None,
                },
                recovery_exit_code=1,
                result_report_match=True,
                source_database_unchanged=True,
                source_raw_unchanged=True,
                provider_ledger_unchanged=True,
                production_unchanged=True,
                target_database_name="recovered.sqlite3",
                target_database_present=False,
                target_database_sha256=None,
                target_residue=("task27-collection-recovery.json",),
                recovery_report_name="task27-collection-recovery.json",
                active_operation_process_count=0,
                one_shot_container_count=0,
            )

    def test_recovery_apply_adds_candidate_and_commits_recovered_page(self):
        run_id = "reindex_apply_recovered_page"
        store, archive, post_id = self._uncommitted_schema_drift_source(
            run_id=run_id
        )
        snapshot = validation._load_reindex_snapshot(
            store.path, archive=archive, run_id=run_id
        )
        plan = validation._plan_strict_discovery_reindex(
            snapshot, allow_schema_drift_recovery=True
        )

        validation._apply_strict_discovery_reindex(
            store.path,
            run_id=run_id,
            plan=plan,
            allow_schema_drift_recovery=True,
        )

        with sqlite3.connect(store.path) as connection:
            candidate = connection.execute(
                "SELECT status, status_reason FROM backfill_candidates "
                "WHERE run_id=? AND post_id=?",
                (run_id, post_id),
            ).fetchone()
            checkpoint = connection.execute(
                "SELECT page_number, cursor, status, stop_reason, last_error "
                "FROM backfill_checkpoints WHERE run_id=? "
                "AND lane_type='dynamic_search' AND lane_key='Momcozy'",
                (run_id,),
            ).fetchone()
            artifact = connection.execute(
                "SELECT parser_kind, response_cursor "
                "FROM backfill_raw_artifacts WHERE run_id=? "
                "AND artifact_kind='discovery'",
                (run_id,),
            ).fetchone()
        self.assertEqual(candidate, ("pending", None))
        self.assertEqual(
            checkpoint,
            (1, "recovered-cursor", "partial", "round_robin_yield", None),
        )
        self.assertEqual(
            artifact,
            ("tikhub_discovery_strict_v2", "recovered-cursor"),
        )

    def test_collection_recovery_publishes_offline_target_without_provider_call(self):
        run_id = "collection_recovery_offline"
        store, archive, raw_root, post_id = self._task24_recovery_source(
            run_id=run_id
        )
        source_sha = _file_sha256(store.path)
        raw_sha = _raw_inventory_sha256(raw_root)
        target = self.root / "collection-recovered.sqlite3"
        recover = getattr(validation, "recover_collection_from_archive", None)
        self.assertTrue(callable(recover), "collection recovery entrypoint missing")

        result = recover(
            store,
            archive,
            target_db=target,
            run_id=run_id,
            expected_source_db_sha256=source_sha,
            recovered_at_utc=CAPTURED_AT + timedelta(seconds=6),
        )

        self.assertEqual(result["status"], "complete", result)
        self.assertEqual(result["stop_reason"], "collection_recovery_complete")
        self.assertFalse(result["provider_call"])
        self.assertFalse(result["provider_attempt_made"])
        self.assertFalse(result["live_send"])
        self.assertEqual(result["reset_candidate_count"], 1)
        self.assertEqual(result["archived_hydrated_candidate_count"], 1)
        self.assertEqual(result["source_provider_request_count"], 3)
        self.assertEqual(result["target_provider_request_count"], 3)
        self.assertEqual(_file_sha256(store.path), source_sha)
        self.assertEqual(_raw_inventory_sha256(raw_root), raw_sha)
        with sqlite3.connect(target) as connection:
            candidate = connection.execute(
                "SELECT status, status_reason FROM backfill_candidates "
                "WHERE run_id=? AND post_id=?",
                (run_id, post_id),
            ).fetchone()
            checkpoint = connection.execute(
                "SELECT status, stop_reason, page_number, discovered_count "
                "FROM backfill_checkpoints WHERE run_id=? "
                "AND lane_type='comments' AND lane_key=?",
                (run_id, post_id),
            ).fetchone()
            provider_attempts = connection.execute(
                "SELECT COUNT(*) FROM backfill_provider_attempts WHERE run_id=?",
                (run_id,),
            ).fetchone()[0]
            comment_count = connection.execute(
                "SELECT COUNT(*) FROM reddit_comments "
                "WHERE run_id=? AND post_id=?",
                (run_id, post_id),
            ).fetchone()[0]
            batch_status = connection.execute(
                "SELECT status, stop_reason FROM backfill_detail_batches "
                "WHERE run_id=?",
                (run_id,),
            ).fetchone()
        self.assertEqual(candidate, ("hydrated", "unresolved_more"))
        self.assertEqual(checkpoint, ("partial", "unresolved_more", 1, 1))
        self.assertEqual(provider_attempts, 3)
        self.assertEqual(comment_count, 1)
        self.assertEqual(batch_status, ("complete", None))
        self.assertEqual(list(self.root.glob(".collection-recovery-*")), [])

    def test_collection_recovery_supports_comment_only_schema_drift_without_discovery_rewrite(
        self,
    ):
        run_id = "collection_recovery_comment_only"
        store, archive, raw_root, post_id = self._task24_recovery_source(
            run_id=run_id,
            discovery_schema_drift=False,
        )
        source_sha = _file_sha256(store.path)
        raw_sha = _raw_inventory_sha256(raw_root)
        target = self.root / "collection-recovered-comment-only.sqlite3"
        with sqlite3.connect(store.path) as connection:
            discovery_before = {
                "occurrences": connection.execute(
                    "SELECT * FROM backfill_discovery_occurrences "
                    "WHERE run_id=? ORDER BY rowid",
                    (run_id,),
                ).fetchall(),
                "checkpoints": connection.execute(
                    "SELECT * FROM backfill_checkpoints WHERE run_id=? "
                    "AND lane_type IN ('dynamic_search', 'subreddit_feed') "
                    "ORDER BY lane_type, lane_key",
                    (run_id,),
                ).fetchall(),
                "artifacts": connection.execute(
                    "SELECT * FROM backfill_raw_artifacts WHERE run_id=? "
                    "AND artifact_kind='discovery' ORDER BY artifact_id",
                    (run_id,),
                ).fetchall(),
            }

        result = validation.recover_collection_from_archive(
            store,
            archive,
            target_db=target,
            run_id=run_id,
            expected_source_db_sha256=source_sha,
            recovered_at_utc=CAPTURED_AT + timedelta(seconds=6),
        )

        self.assertEqual(result["status"], "complete", result)
        self.assertEqual(result["stop_reason"], "collection_recovery_complete")
        self.assertEqual(result["recovered_discovery_lane_count"], 0)
        self.assertEqual(result["new_candidate_count"], 0)
        self.assertEqual(result["reset_candidate_count"], 1)
        self.assertEqual(result["archived_hydrated_candidate_count"], 1)
        self.assertFalse(result["provider_call"])
        self.assertFalse(result["provider_attempt_made"])
        self.assertEqual(result["source_provider_request_count"], 3)
        self.assertEqual(result["target_provider_request_count"], 3)
        self.assertEqual(_file_sha256(store.path), source_sha)
        self.assertEqual(_raw_inventory_sha256(raw_root), raw_sha)
        with sqlite3.connect(target) as connection:
            discovery_after = {
                "occurrences": connection.execute(
                    "SELECT * FROM backfill_discovery_occurrences "
                    "WHERE run_id=? ORDER BY rowid",
                    (run_id,),
                ).fetchall(),
                "checkpoints": connection.execute(
                    "SELECT * FROM backfill_checkpoints WHERE run_id=? "
                    "AND lane_type IN ('dynamic_search', 'subreddit_feed') "
                    "ORDER BY lane_type, lane_key",
                    (run_id,),
                ).fetchall(),
                "artifacts": connection.execute(
                    "SELECT * FROM backfill_raw_artifacts WHERE run_id=? "
                    "AND artifact_kind='discovery' ORDER BY artifact_id",
                    (run_id,),
                ).fetchall(),
            }
            candidate = connection.execute(
                "SELECT status, status_reason FROM backfill_candidates "
                "WHERE run_id=? AND post_id=?",
                (run_id, post_id),
            ).fetchone()
        self.assertEqual(discovery_after, discovery_before)
        self.assertEqual(candidate, ("hydrated", "unresolved_more"))
        self.assertEqual(list(self.root.glob(".collection-recovery-*")), [])

    def test_schema_drift_reset_ignores_unrelated_complete_historical_batches(
        self,
    ):
        run_id = "schema_drift_reset_mixed_historical_batches"
        store, _archive, _raw_root, post_id = self._task24_recovery_source(
            run_id=run_id,
            discovery_schema_drift=False,
        )
        historical_post_id = "historical_hydrated_candidate"
        historical_batch_id = "historical_complete_batch"
        with sqlite3.connect(store.path) as connection:
            connection.row_factory = sqlite3.Row
            candidate = connection.execute(
                "SELECT * FROM backfill_candidates "
                "WHERE run_id=? AND post_id=?",
                (run_id, post_id),
            ).fetchone()
            candidate_columns = tuple(candidate.keys())
            candidate_values = dict(candidate)
            candidate_values.update(
                {
                    "post_id": historical_post_id,
                    "status": "hydrated",
                    "status_reason": None,
                }
            )
            connection.execute(
                "INSERT INTO backfill_candidates("
                + ",".join(candidate_columns)
                + ") VALUES ("
                + ",".join("?" for _ in candidate_columns)
                + ")",
                tuple(candidate_values[column] for column in candidate_columns),
            )
            batch = connection.execute(
                "SELECT * FROM backfill_detail_batches WHERE run_id=?",
                (run_id,),
            ).fetchone()
            batch_columns = tuple(batch.keys())
            batch_values = dict(batch)
            batch_values.update(
                {
                    "batch_id": historical_batch_id,
                    "batch_number": int(batch["batch_number"]) + 1,
                    "status": "complete",
                    "stop_reason": None,
                }
            )
            connection.execute(
                "INSERT INTO backfill_detail_batches("
                + ",".join(batch_columns)
                + ") VALUES ("
                + ",".join("?" for _ in batch_columns)
                + ")",
                tuple(batch_values[column] for column in batch_columns),
            )
            connection.execute(
                "INSERT INTO backfill_detail_batch_members("
                "run_id, batch_id, ordinal, post_id"
                ") VALUES (?, ?, 0, ?)",
                (run_id, historical_batch_id, historical_post_id),
            )

        result = validation._reset_schema_drift_hydration_state(
            store.path,
            run_id=run_id,
            expected_failed_candidate_ids={post_id},
            recovered_at_utc=CAPTURED_AT + timedelta(seconds=6),
        )

        self.assertEqual(result["reset_candidate_count"], 1)
        self.assertEqual(result["reset_batch_count"], 1)
        with sqlite3.connect(store.path) as connection:
            failed_candidate = connection.execute(
                "SELECT status, status_reason FROM backfill_candidates "
                "WHERE run_id=? AND post_id=?",
                (run_id, post_id),
            ).fetchone()
            historical_candidate = connection.execute(
                "SELECT status, status_reason FROM backfill_candidates "
                "WHERE run_id=? AND post_id=?",
                (run_id, historical_post_id),
            ).fetchone()
            batch_states = connection.execute(
                "SELECT batch_id, status, stop_reason "
                "FROM backfill_detail_batches WHERE run_id=? ORDER BY batch_number",
                (run_id,),
            ).fetchall()
        self.assertEqual(failed_candidate, ("pending", None))
        self.assertEqual(historical_candidate, ("hydrated", None))
        self.assertEqual(
            batch_states,
            [
                (batch_states[0][0], "raw_persisted", None),
                (historical_batch_id, "complete", None),
            ],
        )

    def test_schema_drift_reset_ignores_unrelated_comment_checkpoint(self):
        run_id = "schema_drift_reset_unrelated_comment_checkpoint"
        store, _archive, _raw_root, post_id = self._task24_recovery_source(
            run_id=run_id,
            discovery_schema_drift=False,
        )
        historical_post_id = "historical_comments_checkpoint"
        with sqlite3.connect(store.path) as connection:
            connection.row_factory = sqlite3.Row
            checkpoint = connection.execute(
                "SELECT * FROM backfill_checkpoints "
                "WHERE run_id=? AND lane_type='comments' AND lane_key=?",
                (run_id, post_id),
            ).fetchone()
            checkpoint_columns = tuple(checkpoint.keys())
            checkpoint_values = dict(checkpoint)
            checkpoint_values["lane_key"] = historical_post_id
            connection.execute(
                "INSERT INTO backfill_checkpoints("
                + ",".join(checkpoint_columns)
                + ") VALUES ("
                + ",".join("?" for _ in checkpoint_columns)
                + ")",
                tuple(
                    checkpoint_values[column] for column in checkpoint_columns
                ),
            )

        result = validation._reset_schema_drift_hydration_state(
            store.path,
            run_id=run_id,
            expected_failed_candidate_ids={post_id},
            recovered_at_utc=CAPTURED_AT + timedelta(seconds=6),
        )

        self.assertEqual(result["reset_comment_checkpoint_count"], 1)
        with sqlite3.connect(store.path) as connection:
            checkpoint_states = connection.execute(
                "SELECT lane_key, status, stop_reason, last_error "
                "FROM backfill_checkpoints "
                "WHERE run_id=? AND lane_type='comments' ORDER BY lane_key",
                (run_id,),
            ).fetchall()
        self.assertEqual(
            checkpoint_states,
            [
                (
                    historical_post_id,
                    "partial",
                    "comments_schema_drift",
                    "TikHubSchemaDrift",
                ),
                (post_id, "prepared", None, None),
            ],
        )

    def test_collection_recovery_replays_complete_owner_batch_for_comment_only_failure(
        self,
    ):
        run_id = "collection_recovery_complete_owner_batch"
        store, archive, raw_root, post_id = self._task24_recovery_source(
            run_id=run_id,
            discovery_schema_drift=False,
        )
        with sqlite3.connect(store.path) as connection:
            connection.execute(
                "UPDATE backfill_detail_batches SET status='complete', "
                "stop_reason=NULL WHERE run_id=?",
                (run_id,),
            )
        source_sha = _file_sha256(store.path)
        raw_sha = _raw_inventory_sha256(raw_root)
        target = self.root / "collection-recovered-complete-owner.sqlite3"

        result = validation.recover_collection_from_archive(
            store,
            archive,
            target_db=target,
            run_id=run_id,
            expected_source_db_sha256=source_sha,
            recovered_at_utc=CAPTURED_AT + timedelta(seconds=6),
        )

        self.assertEqual(result["status"], "complete", result)
        self.assertEqual(result["stop_reason"], "collection_recovery_complete")
        self.assertEqual(result["recovered_discovery_lane_count"], 0)
        self.assertEqual(result["reset_candidate_count"], 1)
        self.assertEqual(result["reset_batch_count"], 1)
        self.assertEqual(result["archived_hydrated_candidate_count"], 1)
        self.assertFalse(result["provider_call"])
        self.assertFalse(result["provider_attempt_made"])
        self.assertEqual(result["source_provider_request_count"], 3)
        self.assertEqual(result["target_provider_request_count"], 3)
        self.assertEqual(_file_sha256(store.path), source_sha)
        self.assertEqual(_raw_inventory_sha256(raw_root), raw_sha)
        with sqlite3.connect(target) as connection:
            candidate = connection.execute(
                "SELECT status, status_reason FROM backfill_candidates "
                "WHERE run_id=? AND post_id=?",
                (run_id, post_id),
            ).fetchone()
            batch = connection.execute(
                "SELECT status, stop_reason FROM backfill_detail_batches "
                "WHERE run_id=?",
                (run_id,),
            ).fetchone()
        self.assertEqual(candidate, ("hydrated", "unresolved_more"))
        self.assertEqual(batch, ("complete", None))
        self.assertEqual(list(self.root.glob(".collection-recovery-*")), [])

    def test_collection_recovery_uses_backup_when_serialize_is_unavailable(self):
        run_id = "collection_recovery_backup_snapshot"
        store, archive, raw_root, post_id = self._task24_recovery_source(
            run_id=run_id
        )
        source_sha = _file_sha256(store.path)
        raw_sha = _raw_inventory_sha256(raw_root)
        target = self.root / "collection-recovery-backup.sqlite3"

        with patch.object(
            validation,
            "_sqlite_memory_snapshot_supports_serialize",
            return_value=False,
        ):
            result = validation.recover_collection_from_archive(
                store,
                archive,
                target_db=target,
                run_id=run_id,
                expected_source_db_sha256=source_sha,
                recovered_at_utc=CAPTURED_AT + timedelta(seconds=6),
            )

        self.assertEqual(result["status"], "complete", result)
        self.assertEqual(result["stop_reason"], "collection_recovery_complete")
        self.assertFalse(result["provider_call"])
        self.assertFalse(result["provider_attempt_made"])
        self.assertEqual(result["archived_hydrated_candidate_count"], 1)
        self.assertEqual(result["source_provider_request_count"], 3)
        self.assertEqual(result["target_provider_request_count"], 3)
        self.assertEqual(_file_sha256(store.path), source_sha)
        self.assertEqual(_raw_inventory_sha256(raw_root), raw_sha)
        with sqlite3.connect(target) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT status, status_reason FROM backfill_candidates "
                    "WHERE run_id=? AND post_id=?",
                    (run_id, post_id),
                ).fetchone(),
                ("hydrated", "unresolved_more"),
            )
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM backfill_provider_attempts "
                    "WHERE run_id=?",
                    (run_id,),
                ).fetchone()[0],
                3,
            )
        self.assertEqual(list(self.root.glob(".collection-recovery-*")), [])

    def test_collection_recovery_rejects_nonmatching_failure_state_without_target(self):
        run_id = "collection_recovery_wrong_failure"
        store, archive, raw_root, _post_id = self._task24_recovery_source(
            run_id=run_id
        )
        with sqlite3.connect(store.path) as connection:
            connection.execute(
                "UPDATE backfill_detail_batches "
                "SET stop_reason='detail_schema_drift' WHERE run_id=?",
                (run_id,),
            )
        source_sha = _file_sha256(store.path)
        raw_sha = _raw_inventory_sha256(raw_root)
        target = self.root / "collection-recovery-rejected.sqlite3"

        result = validation.recover_collection_from_archive(
            store,
            archive,
            target_db=target,
            run_id=run_id,
            expected_source_db_sha256=source_sha,
            recovered_at_utc=CAPTURED_AT + timedelta(seconds=6),
        )

        self.assertEqual(result["status"], "failed", result)
        self.assertEqual(
            result["stop_reason"], "schema_drift_recovery_batch_mismatch"
        )
        self.assertFalse(result["provider_attempt_made"])
        self.assertFalse(target.exists())
        self.assertEqual(_file_sha256(store.path), source_sha)
        self.assertEqual(_raw_inventory_sha256(raw_root), raw_sha)
        self.assertEqual(list(self.root.glob(".collection-recovery-*")), [])

    def test_reindex_removes_broad_metadata_invalid_and_is_strictly_replayable(self):
        run_id = "reindex_success"
        store, archive, raw_root, post_id = self._source(run_id=run_id)
        source_sha = _file_sha256(store.path)
        raw_sha = _raw_inventory_sha256(raw_root)
        source_batches = self._rows(store.path, "backfill_detail_batches", run_id)
        source_members = self._rows(
            store.path, "backfill_detail_batch_members", run_id
        )
        source_attempts = self._rows(
            store.path, "backfill_provider_attempts", run_id
        )
        source_manifest_budget = self._rows(
            store.path, "backfill_manifests", run_id
        )[0][10:12]
        source_threads = self._rows(store.path, "reddit_threads", run_id)
        source_comments = self._rows(store.path, "reddit_comments", run_id)
        source_analyses = self._rows(store.path, "analysis_results", run_id)
        source_candidate_status = self._rows(
            store.path, "backfill_candidates", run_id
        )[0][-3:]
        target = self.root / "reindexed.sqlite3"

        result = reindex_discovery_from_archive(
            store, archive, target_db=target, run_id=run_id
        )

        self.assertEqual(result["status"], "complete", result)
        self.assertEqual(result["stop_reason"], "reindex_complete")
        self.assertFalse(result["provider_attempt_made"])
        self.assertFalse(result["live_send"])
        self.assertRegex(result["target_db_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(result["target_db_sha256"], _file_sha256(target))
        self.assertEqual(result["source_max_provider_requests"], 1)
        self.assertEqual(result["source_provider_request_count"], 1)
        self.assertEqual(result["target_max_provider_requests"], 1)
        self.assertEqual(result["target_provider_request_count"], 1)
        self.assertEqual(
            result["target_provider_ledger_sha256"],
            result["source_provider_ledger_sha256"],
        )
        self.assertEqual(_file_sha256(store.path), source_sha)
        self.assertEqual(_raw_inventory_sha256(raw_root), raw_sha)
        self.assertTrue(target.exists())
        with sqlite3.connect(target) as connection:
            occurrences = connection.execute(
                "SELECT post_id, disposition FROM backfill_discovery_occurrences "
                "WHERE run_id=? ORDER BY page_number, ordinal",
                (run_id,),
            ).fetchall()
            parser_kinds = connection.execute(
                "SELECT DISTINCT parser_kind FROM backfill_raw_artifacts "
                "WHERE run_id=? AND artifact_kind='discovery'",
                (run_id,),
            ).fetchall()
            checkpoint_counts = connection.execute(
                "SELECT discovered_count, unique_count FROM backfill_checkpoints "
                "WHERE run_id=? AND lane_type='dynamic_search'",
                (run_id,),
            ).fetchone()
            target_provider_attempts = connection.execute(
                "SELECT COUNT(*) FROM backfill_provider_attempts WHERE run_id=?",
                (run_id,),
            ).fetchone()[0]
            additive_tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
                    "('backfill_budget_extensions','backfill_hydration_resumes',"
                    "'backfill_collection_resumes')"
                ).fetchall()
            }
        self.assertEqual(occurrences, [(post_id, "new_candidate")])
        self.assertEqual(parser_kinds, [("tikhub_discovery_strict_v2",)])
        self.assertEqual(checkpoint_counts, (1, 1))
        self.assertEqual(target_provider_attempts, len(source_attempts))
        self.assertEqual(
            additive_tables,
            {
                "backfill_budget_extensions",
                "backfill_hydration_resumes",
                "backfill_collection_resumes",
            },
        )
        self.assertEqual(
            self._rows(target, "backfill_provider_attempts", run_id),
            source_attempts,
        )
        self.assertEqual(
            self._rows(target, "backfill_manifests", run_id)[0][10:12],
            source_manifest_budget,
        )
        self.assertEqual(
            self._rows(target, "backfill_detail_batches", run_id), source_batches
        )
        self.assertEqual(
            self._rows(target, "backfill_detail_batch_members", run_id),
            source_members,
        )
        self.assertEqual(
            self._rows(target, "backfill_candidates", run_id)[0][-3:],
            source_candidate_status,
        )
        self.assertEqual(
            self._rows(target, "reddit_threads", run_id), source_threads
        )
        self.assertEqual(
            self._rows(target, "reddit_comments", run_id), source_comments
        )
        self.assertEqual(
            self._rows(target, "analysis_results", run_id), source_analyses
        )

        strict_replay = self.root / "strict-replay.sqlite3"
        replay = replay_from_archive(
            BackfillStore(target),
            archive,
            target_db=strict_replay,
            run_id=run_id,
        )
        self.assertEqual(replay["status"], "complete", replay)
        self.assertTrue(replay["fingerprints"]["equivalent"])
        self._assert_no_reindex_residue()

    def test_reindex_accepts_reviewed_telemetry_and_crosspost(self) -> None:
        run_id = "reindex_mixed_reviewed_wrappers"
        store, archive, raw_root, post_id = self._source(
            run_id=run_id, schema="mixed"
        )
        source_sha = _file_sha256(store.path)
        raw_sha = _raw_inventory_sha256(raw_root)
        source_attempts = self._rows(
            store.path, "backfill_provider_attempts", run_id
        )
        target = self.root / "mixed-reviewed.sqlite3"

        result = reindex_discovery_from_archive(
            store, archive, target_db=target, run_id=run_id
        )

        self.assertEqual(result["status"], "complete", result)
        self.assertEqual(result["stop_reason"], "reindex_complete")
        self.assertEqual(result["discovery_artifact_count"], 1)
        self.assertEqual(result["discovery_occurrence_count"], 2)
        self.assertEqual(result["candidate_count"], 1)
        self.assertFalse(result["provider_attempt_made"])
        self.assertFalse(result["live_send"])
        self.assertEqual(_file_sha256(store.path), source_sha)
        self.assertEqual(_raw_inventory_sha256(raw_root), raw_sha)
        with sqlite3.connect(target) as connection:
            occurrences = connection.execute(
                "SELECT post_id, disposition "
                "FROM backfill_discovery_occurrences WHERE run_id=? "
                "ORDER BY page_number, ordinal",
                (run_id,),
            ).fetchall()
            parser_kinds = connection.execute(
                "SELECT DISTINCT parser_kind FROM backfill_raw_artifacts "
                "WHERE run_id=? AND artifact_kind='discovery'",
                (run_id,),
            ).fetchall()
        self.assertEqual(
            occurrences,
            [(post_id, "new_candidate"), (post_id, "duplicate_occurrence")],
        )
        self.assertEqual(parser_kinds, [("tikhub_discovery_strict_v2",)])
        self.assertEqual(
            self._rows(target, "backfill_provider_attempts", run_id),
            source_attempts,
        )
        self._assert_no_reindex_residue()

    def test_read_only_corpus_audit_reports_reviewed_wrapper_contract(self) -> None:
        run_id = "audit_mixed_reviewed_wrappers"
        store, archive, raw_root, _post_id = self._source(
            run_id=run_id, schema="mixed"
        )
        source_sha = _file_sha256(store.path)
        raw_sha = _raw_inventory_sha256(raw_root)
        audit = getattr(
            validation, "audit_discovery_reindex_from_archive", None
        )
        self.assertTrue(callable(audit), "read-only corpus audit is missing")

        result = audit(
            store,
            archive,
            run_id=run_id,
            expected_source_db_sha256=source_sha,
        )

        self.assertEqual(
            result,
            {
                "schema_version": "backfill_discovery_reindex_audit_v1",
                "status": "ready",
                "stop_reason": "strict_discovery_corpus_ready",
                "run_id": run_id,
                "source_db_sha256": source_sha,
                "raw_inventory_sha256": raw_sha,
                "discovery_artifact_count": 1,
                "strict_pass_artifact_count": 1,
                "discovery_occurrence_count": 2,
                "recognized_occurrence_count": 2,
                "eligible_occurrence_count": 2,
                "outside_window_count": 0,
                "invalid_count": 0,
                "payload_sha_mismatch_count": 0,
                "candidate_count": 1,
                "wrapper_counts": {
                    "SearchCrosspost": 1,
                    "SearchPost": 1,
                },
                "disposition_counts": {
                    "duplicate_occurrence": 1,
                    "new_candidate": 1,
                },
                "candidate_set_equal": True,
                "candidate_first_provenance_match": True,
                "provider_call": False,
                "provider_attempt_made": False,
                "database_write": False,
                "live_send": False,
            },
        )
        self.assertEqual(_file_sha256(store.path), source_sha)
        self.assertEqual(_raw_inventory_sha256(raw_root), raw_sha)
        self._assert_no_reindex_residue()

    def test_reindex_preserves_round_robin_cross_lane_first_provenance(self):
        run_id = "reindex_round_robin_provenance"
        lane_b = "wearable breast pump"
        store, archive, raw_root, _post_id = self._source(
            run_id=run_id,
            first_response_cursor="cursor-a1",
        )
        with sqlite3.connect(store.path) as connection:
            connection.execute(
                "UPDATE backfill_manifests "
                "SET search_terms_json=?, required_lanes_sha256=?, "
                "max_provider_requests=? WHERE run_id=?",
                (
                    json.dumps(
                        ["Momcozy", lane_b],
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    required_lanes_sha256(
                        search_terms=("Momcozy", lane_b),
                        subreddits=("ExclusivelyPumping",),
                        include_subreddit_sweep=False,
                    ),
                    3,
                    run_id,
                ),
            )

        archive_writer = PrivateRawArchive(raw_root)
        b_count, b_cursor_path, b_page_info = self._persist_discovery_page(
            store=store,
            archive=archive_writer,
            run_id=run_id,
            lane_key=lane_b,
            page_number=1,
            request_cursor=None,
            response_cursor=None,
            post_id="cross_lane_duplicate",
            captured_at_utc=CAPTURED_AT + timedelta(seconds=1),
        )
        a_count, a_cursor_path, a_page_info = self._persist_discovery_page(
            store=store,
            archive=archive_writer,
            run_id=run_id,
            lane_key="Momcozy",
            page_number=2,
            request_cursor="cursor-a1",
            response_cursor=None,
            post_id="cross_lane_duplicate",
            captured_at_utc=CAPTURED_AT + timedelta(seconds=2),
        )
        created_at = (WINDOW_START + timedelta(days=30)).isoformat()
        a_counts = store.discovery_occurrence_counts(
            run_id, "dynamic_search", "Momcozy"
        )
        b_counts = store.discovery_occurrence_counts(
            run_id, "dynamic_search", lane_b
        )
        store.save_checkpoint(
            BackfillCheckpoint(
                run_id=run_id,
                lane_type="dynamic_search",
                lane_key=lane_b,
                cursor=None,
                previous_cursor=None,
                page_number=1,
                newest_seen_utc=created_at,
                oldest_seen_utc=created_at,
                discovered_count=b_count,
                unique_count=b_counts.get("new_candidate", 0),
                provider_request_count=2,
                last_success_utc=(CAPTURED_AT + timedelta(seconds=1)).isoformat(),
                last_error=None,
                status="complete",
                stop_reason="cursor_exhausted",
                cursor_json_path=json.dumps(
                    b_cursor_path, separators=(",", ":")
                ),
                cursor_schema_sha256=validation._page_info_schema_sha256(
                    b_page_info  # type: ignore[arg-type]
                ),
                consecutive_old_pages=0,
            )
        )
        store.save_checkpoint(
            BackfillCheckpoint(
                run_id=run_id,
                lane_type="dynamic_search",
                lane_key="Momcozy",
                cursor=None,
                previous_cursor="cursor-a1",
                page_number=2,
                newest_seen_utc=created_at,
                oldest_seen_utc=created_at,
                discovered_count=sum(a_counts.values()),
                unique_count=a_counts.get("new_candidate", 0),
                provider_request_count=3,
                last_success_utc=(CAPTURED_AT + timedelta(seconds=2)).isoformat(),
                last_error=None,
                status="complete",
                stop_reason="cursor_exhausted",
                cursor_json_path=json.dumps(
                    a_cursor_path, separators=(",", ":")
                ),
                cursor_schema_sha256=validation._page_info_schema_sha256(
                    a_page_info  # type: ignore[arg-type]
                ),
                consecutive_old_pages=0,
            )
        )
        with sqlite3.connect(store.path) as connection:
            source_first = connection.execute(
                "SELECT first_lane_type, first_lane_key, "
                "first_discovered_at_utc, source_url, post_created_at_utc, "
                "raw_artifact_id FROM backfill_candidates "
                "WHERE run_id=? AND post_id='cross_lane_duplicate'",
                (run_id,),
            ).fetchone()
        self.assertEqual(source_first[1], lane_b)

        target = self.root / "round-robin-reindexed.sqlite3"
        result = reindex_discovery_from_archive(
            store,
            archive,
            target_db=target,
            run_id=run_id,
            expected_source_db_sha256=_file_sha256(store.path),
        )

        self.assertEqual(result["status"], "complete", result)
        with sqlite3.connect(target) as connection:
            target_first = connection.execute(
                "SELECT first_lane_type, first_lane_key, "
                "first_discovered_at_utc, source_url, post_created_at_utc, "
                "raw_artifact_id FROM backfill_candidates "
                "WHERE run_id=? AND post_id='cross_lane_duplicate'",
                (run_id,),
            ).fetchone()
            dispositions = connection.execute(
                "SELECT lane_key, disposition "
                "FROM backfill_discovery_occurrences "
                "WHERE run_id=? AND post_id='cross_lane_duplicate' "
                "ORDER BY discovered_at_utc",
                (run_id,),
            ).fetchall()
        self.assertEqual(target_first, source_first)
        self.assertEqual(
            dispositions,
            [(lane_b, "new_candidate"), ("Momcozy", "duplicate_occurrence")],
        )
        self._assert_no_reindex_residue()

    def test_reindex_rejects_candidate_set_drift_without_target(self):
        run_id = "reindex_candidate_drift"
        store, archive, _raw_root, _post_id = self._source(run_id=run_id)
        with sqlite3.connect(store.path) as connection:
            connection.execute("PRAGMA foreign_keys=OFF")
            connection.execute(
                "UPDATE backfill_candidates SET post_id='drifted_candidate' "
                "WHERE run_id=?",
                (run_id,),
            )
        target = self.root / "candidate-drift.sqlite3"

        result = reindex_discovery_from_archive(
            store, archive, target_db=target, run_id=run_id
        )

        self.assertEqual(result["status"], "failed")
        self.assertIsNone(result["target_db_sha256"])
        self.assertFalse(target.exists())
        self._assert_no_reindex_residue()

    def test_reindex_rejects_candidate_first_provenance_drift(self):
        mutations = {
            "lane_type": ("first_lane_type", "subreddit_feed"),
            "lane_key": ("first_lane_key", "drifted-lane"),
            "captured_at": (
                "first_discovered_at_utc",
                (CAPTURED_AT + timedelta(seconds=9)).isoformat(),
            ),
            "source_url": (
                "source_url",
                "https://www.reddit.com/r/ExclusivelyPumping/comments/drift/source/",
            ),
            "post_created_at": (
                "post_created_at_utc",
                (WINDOW_START + timedelta(days=31)).isoformat(),
            ),
            "artifact_id": ("raw_artifact_id", "raw_artifact_drifted"),
        }
        for label, (column, value) in mutations.items():
            with self.subTest(field=label):
                run_id = f"reindex_first_drift_{label}"
                store, archive, _raw_root, post_id = self._source(run_id=run_id)
                with sqlite3.connect(store.path) as connection:
                    connection.execute(
                        f"UPDATE backfill_candidates SET {column}=? "
                        "WHERE run_id=? AND post_id=?",
                        (value, run_id, post_id),
                    )
                target = self.root / f"first-drift-{label}.sqlite3"

                result = reindex_discovery_from_archive(
                    store,
                    archive,
                    target_db=target,
                    run_id=run_id,
                    expected_source_db_sha256=_file_sha256(store.path),
                )

                self.assertEqual(result["status"], "failed", result)
                self.assertFalse(target.exists())
                self._assert_no_reindex_residue()

    def test_reindex_rejects_unknown_discovery_schema_without_target(self):
        run_id = "reindex_unknown_schema"
        store, archive, _raw_root, _post_id = self._source(
            run_id=run_id, schema="unknown"
        )
        target = self.root / "unknown-schema.sqlite3"

        result = reindex_discovery_from_archive(
            store, archive, target_db=target, run_id=run_id
        )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["stop_reason"], "strict_discovery_schema_unknown")
        self.assertIsNone(result["target_db_sha256"])
        self.assertFalse(target.exists())
        self._assert_no_reindex_residue()

    def test_reindex_rejects_raw_tamper_without_target(self):
        run_id = "reindex_raw_tamper"
        store, archive, raw_root, _post_id = self._source(run_id=run_id)
        raw_path = next(raw_root.rglob("*.json.gz"))
        raw_path.write_bytes(raw_path.read_bytes() + b"tamper")
        target = self.root / "raw-tamper.sqlite3"

        result = reindex_discovery_from_archive(
            store, archive, target_db=target, run_id=run_id
        )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["stop_reason"], "archive_integrity_failed")
        self.assertIsNone(result["target_db_sha256"])
        self.assertFalse(target.exists())
        self._assert_no_reindex_residue()

    def test_reindex_rejects_unapproved_source_sha_before_target_creation(self):
        run_id = "reindex_wrong_source_sha"
        store, archive, _raw_root, _post_id = self._source(run_id=run_id)
        target = self.root / "wrong-source-sha.sqlite3"

        with self.assertRaisesRegex(ValueError, "source database sha256 mismatch"):
            reindex_discovery_from_archive(
                store,
                archive,
                target_db=target,
                run_id=run_id,
                expected_source_db_sha256="a" * 64,
            )

        self.assertFalse(target.exists())
        self._assert_no_reindex_residue()

    def test_reindex_rejects_source_wal_added_after_sha_admission(self):
        run_id = "reindex_source_wal_race"
        store, archive, _raw_root, _post_id = self._source(run_id=run_id)
        target = self.root / "source-wal-race.sqlite3"
        with sqlite3.connect(store.path) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        for suffix in ("-wal", "-shm"):
            Path(str(store.path) + suffix).unlink(missing_ok=True)
        approved_sha256 = _file_sha256(store.path)

        writer = sqlite3.connect(store.path)
        self.addCleanup(writer.close)
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("CREATE TABLE post_admission_payload(value TEXT)")
        writer.execute("INSERT INTO post_admission_payload VALUES ('unapproved')")
        writer.commit()
        self.assertEqual(_file_sha256(store.path), approved_sha256)
        self.assertTrue(Path(str(store.path) + "-wal").exists())

        with self.assertRaisesRegex(ValueError, "source database sidecar present"):
            reindex_discovery_from_archive(
                store,
                archive,
                target_db=target,
                run_id=run_id,
                expected_source_db_sha256=approved_sha256,
            )

        self.assertFalse(target.exists())
        self._assert_no_reindex_residue()

    def test_reindex_rejects_source_wal_created_after_first_sidecar_check(self):
        run_id = "reindex_source_wal_during_copy"
        store, archive, _raw_root, _post_id = self._source(run_id=run_id)
        target = self.root / "source-wal-during-copy.sqlite3"
        with sqlite3.connect(store.path) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        for suffix in ("-wal", "-shm"):
            Path(str(store.path) + suffix).unlink(missing_ok=True)
        approved_sha256 = _file_sha256(store.path)
        original_check = validation._assert_reindex_source_sidecars_absent
        calls = 0
        writers: list[sqlite3.Connection] = []
        self.addCleanup(lambda: [writer.close() for writer in writers])

        def check_then_create_wal(path: Path) -> None:
            nonlocal calls
            original_check(path)
            if path != store.path or calls != 0:
                return
            calls += 1
            writer = sqlite3.connect(store.path)
            writers.append(writer)
            writer.execute("PRAGMA wal_autocheckpoint=0")
            writer.execute("CREATE TABLE post_check_payload(value TEXT)")
            writer.execute("INSERT INTO post_check_payload VALUES ('unapproved')")
            writer.commit()

        with patch.object(
            validation,
            "_assert_reindex_source_sidecars_absent",
            side_effect=check_then_create_wal,
        ):
            with self.assertRaisesRegex(ValueError, "source database sidecar present"):
                reindex_discovery_from_archive(
                    store,
                    archive,
                    target_db=target,
                    run_id=run_id,
                    expected_source_db_sha256=approved_sha256,
                )

        self.assertFalse(target.exists())
        self._assert_no_reindex_residue()

    def test_reindex_uses_approved_snapshot_during_transient_source_inode_swap(self):
        run_id = "reindex_source_inode_swap"
        store, archive, _raw_root, _post_id = self._source(run_id=run_id)
        target = self.root / "source-inode-swap.sqlite3"
        approved_sha256 = _file_sha256(store.path)
        malicious = self.root / "source-inode-swap-malicious.sqlite3"
        displaced = self.root / "source-inode-swap-displaced.sqlite3"
        malicious.write_bytes(store.path.read_bytes())
        with sqlite3.connect(malicious) as connection:
            connection.execute("CREATE TABLE transient_unapproved(value TEXT)")
            connection.execute(
                "INSERT INTO transient_unapproved VALUES ('must-not-enter-target')"
            )
        original_snapshot = validation._create_reindex_source_snapshot

        def snapshot_during_inode_swap(**kwargs: object) -> object:
            store.path.replace(displaced)
            malicious.replace(store.path)
            try:
                return original_snapshot(**kwargs)  # type: ignore[arg-type]
            finally:
                store.path.replace(malicious)
                displaced.replace(store.path)

        with patch.object(
            validation,
            "_create_reindex_source_snapshot",
            side_effect=snapshot_during_inode_swap,
        ):
            result = reindex_discovery_from_archive(
                store,
                archive,
                target_db=target,
                run_id=run_id,
                expected_source_db_sha256=approved_sha256,
            )

        self.assertEqual(result["status"], "complete", result)
        self.assertEqual(_file_sha256(store.path), approved_sha256)
        with sqlite3.connect(target) as connection:
            self.assertIsNone(
                connection.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name='transient_unapproved'"
                ).fetchone()
            )
        self._assert_no_reindex_residue()

    def test_reindex_pins_approved_snapshot_across_transient_path_swap(self):
        run_id = "reindex_approved_snapshot_swap"
        store, archive, _raw_root, _post_id = self._source(run_id=run_id)
        target = self.root / "approved-snapshot-swap.sqlite3"
        malicious = self.root / "approved-snapshot-malicious.sqlite3"
        displaced = self.root / "approved-snapshot-displaced.sqlite3"
        original_snapshot = validation._create_reindex_source_snapshot

        def snapshot_during_approved_swap(**kwargs: object) -> object:
            approved = Path(kwargs["resolved_source"])  # type: ignore[arg-type]
            malicious.write_bytes(approved.read_bytes())
            with sqlite3.connect(malicious) as connection:
                connection.execute("CREATE TABLE transient_unapproved(value TEXT)")
                connection.execute(
                    "INSERT INTO transient_unapproved VALUES ('entered-target')"
                )
            approved.replace(displaced)
            malicious.replace(approved)
            try:
                return original_snapshot(**kwargs)  # type: ignore[arg-type]
            finally:
                approved.replace(malicious)
                displaced.replace(approved)

        with patch.object(
            validation,
            "_create_reindex_source_snapshot",
            side_effect=snapshot_during_approved_swap,
        ):
            result = reindex_discovery_from_archive(
                store,
                archive,
                target_db=target,
                run_id=run_id,
                expected_source_db_sha256=_file_sha256(store.path),
            )

        self.assertEqual(result["status"], "complete", result)
        with sqlite3.connect(target) as connection:
            self.assertIsNone(
                connection.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name='transient_unapproved'"
                ).fetchone()
            )
        self._assert_no_reindex_residue()

    def test_reindex_uses_memory_snapshot_during_approved_inode_mutation(self):
        run_id = "reindex_approved_inode_mutation"
        store, archive, _raw_root, _post_id = self._source(run_id=run_id)
        target = self.root / "approved-inode-mutation.sqlite3"
        original_snapshot = validation._create_reindex_source_snapshot

        def snapshot_during_approved_mutation(**kwargs: object) -> object:
            approved = Path(kwargs["resolved_source"])  # type: ignore[arg-type]
            approved_identity = approved.stat().st_ino
            approved_bytes = approved.read_bytes()
            with sqlite3.connect(approved) as connection:
                connection.execute("CREATE TABLE transient_unapproved(value TEXT)")
                connection.execute(
                    "INSERT INTO transient_unapproved VALUES ('entered-target')"
                )
            try:
                return original_snapshot(**kwargs)  # type: ignore[arg-type]
            finally:
                approved.write_bytes(approved_bytes)
                self.assertEqual(approved.stat().st_ino, approved_identity)

        with patch.object(
            validation,
            "_create_reindex_source_snapshot",
            side_effect=snapshot_during_approved_mutation,
        ):
            result = reindex_discovery_from_archive(
                store,
                archive,
                target_db=target,
                run_id=run_id,
                expected_source_db_sha256=_file_sha256(store.path),
            )

        self.assertEqual(result["status"], "complete", result)
        with sqlite3.connect(target) as connection:
            self.assertIsNone(
                connection.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name='transient_unapproved'"
                ).fetchone()
            )
        self._assert_no_reindex_residue()

    def test_reindex_rejects_target_wal_created_after_publish(self):
        run_id = "reindex_target_wal_race"
        store, archive, _raw_root, _post_id = self._source(run_id=run_id)
        target = self.root / "target-wal-race.sqlite3"
        writers: list[sqlite3.Connection] = []
        self.addCleanup(lambda: [writer.close() for writer in writers])
        original_publish = validation._publish_replay_target

        def publish_with_wal(**kwargs: object) -> None:
            original_publish(**kwargs)  # type: ignore[arg-type]
            if kwargs["target_name"] != target.name:
                return
            writer = sqlite3.connect(target)
            writers.append(writer)
            writer.execute("PRAGMA journal_mode=WAL")
            writer.execute("PRAGMA wal_autocheckpoint=0")
            writer.execute("CREATE TABLE target_sidecar_payload(value TEXT)")
            writer.execute("INSERT INTO target_sidecar_payload VALUES ('unapproved')")
            writer.commit()

        with patch.object(
            validation, "_publish_replay_target", side_effect=publish_with_wal
        ):
            with self.assertRaises(validation.ReplayPublicationError):
                reindex_discovery_from_archive(
                    store,
                    archive,
                    target_db=target,
                    run_id=run_id,
                    expected_source_db_sha256=_file_sha256(store.path),
                )

        self.assertTrue(target.exists())
        self.assertTrue(Path(str(target) + "-wal").exists())

    def test_reindex_rejects_target_main_file_mutation_after_publish(self):
        run_id = "reindex_target_main_mutation"
        store, archive, _raw_root, _post_id = self._source(run_id=run_id)
        target = self.root / "target-main-mutation.sqlite3"
        original_publish = validation._publish_replay_target

        def publish_with_main_mutation(**kwargs: object) -> None:
            original_publish(**kwargs)  # type: ignore[arg-type]
            if kwargs["target_name"] != target.name:
                return
            with sqlite3.connect(target) as connection:
                connection.execute("PRAGMA journal_mode=DELETE")
                connection.execute(
                    "CREATE TABLE target_main_payload(value TEXT)"
                )
                connection.execute(
                    "INSERT INTO target_main_payload VALUES ('unapproved')"
                )

        with patch.object(
            validation,
            "_publish_replay_target",
            side_effect=publish_with_main_mutation,
        ):
            with self.assertRaises(validation.ReplayPublicationError):
                reindex_discovery_from_archive(
                    store,
                    archive,
                    target_db=target,
                    run_id=run_id,
                    expected_source_db_sha256=_file_sha256(store.path),
                )

        self.assertTrue(target.exists())
        self.assertFalse(Path(str(target) + "-journal").exists())

    def test_reindex_cleans_internal_proof_after_postcommit_failure(self):
        run_id = "reindex_internal_proof_postcommit"
        store, archive, _raw_root, _post_id = self._source(run_id=run_id)
        target = self.root / "internal-proof-postcommit.sqlite3"
        original_replay = validation.replay_from_archive

        def replay_with_proof_postcommit_failure(
            source_store: BackfillStore,
            raw_archive: PrivateRawArchive,
            *,
            target_db: Path,
            run_id: str,
            **kwargs: object,
        ) -> dict[str, object]:
            if target_db.name.startswith(".discovery-reindex-proof-"):
                target_db.write_bytes(b"committed-internal-proof")
                raise validation.ReplayPublicationError(
                    publication_state="target_exists_needs_review"
                )
            return original_replay(
                source_store,
                raw_archive,
                target_db=target_db,
                run_id=run_id,
                **kwargs,
            )

        with patch.object(
            validation,
            "replay_from_archive",
            side_effect=replay_with_proof_postcommit_failure,
        ):
            with self.assertRaises(validation.ReplayPublicationError):
                reindex_discovery_from_archive(
                    store,
                    archive,
                    target_db=target,
                    run_id=run_id,
                    expected_source_db_sha256=_file_sha256(store.path),
                )

        self.assertFalse(target.exists())
        self._assert_no_reindex_residue()

    def test_reindex_cleanup_continues_after_one_owned_name_fails(self):
        run_id = "reindex_cleanup_aggregate"
        store, archive, _raw_root, _post_id = self._source(run_id=run_id)
        target = self.root / "cleanup-aggregate.sqlite3"
        original_cleanup = validation._best_effort_cleanup_replay_names
        cleanup_calls: list[str] = []

        def cleanup_with_staging_failure(
            name: str, *, parent_fd: int
        ) -> bool:
            cleanup_calls.append(name)
            if (
                name.startswith(".discovery-reindex-")
                and not name.startswith(".discovery-reindex-proof-")
                and not name.startswith(".discovery-reindex-source-")
            ):
                return False
            return original_cleanup(name, parent_fd=parent_fd)

        with (
            patch.object(
                validation,
                "_plan_strict_discovery_reindex",
                side_effect=RuntimeError("force-final-cleanup"),
            ),
            patch.object(
                validation,
                "_best_effort_cleanup_replay_names",
                side_effect=cleanup_with_staging_failure,
            ),
        ):
            with self.assertRaises(validation._ReplayOperationalBoundaryError):
                reindex_discovery_from_archive(
                    store,
                    archive,
                    target_db=target,
                    run_id=run_id,
                    expected_source_db_sha256=_file_sha256(store.path),
                )

        self.assertTrue(
            any(
                name.startswith(".discovery-reindex-source-")
                for name in cleanup_calls
            )
        )
        self.assertEqual(
            list(self.root.glob(".discovery-reindex-source-*")), []
        )
        self.assertFalse(target.exists())

    def test_reindex_cleanup_continues_after_one_owned_name_raises(self):
        run_id = "reindex_cleanup_exception_aggregate"
        store, archive, _raw_root, _post_id = self._source(run_id=run_id)
        target = self.root / "cleanup-exception-aggregate.sqlite3"
        original_cleanup = validation._best_effort_cleanup_replay_names
        cleanup_calls: list[str] = []

        def cleanup_with_staging_exception(
            name: str, *, parent_fd: int
        ) -> bool:
            cleanup_calls.append(name)
            if (
                name.startswith(".discovery-reindex-")
                and not name.startswith(".discovery-reindex-proof-")
                and not name.startswith(".discovery-reindex-source-")
            ):
                raise validation._ReplayOperationalBoundaryError
            return original_cleanup(name, parent_fd=parent_fd)

        with (
            patch.object(
                validation,
                "_plan_strict_discovery_reindex",
                side_effect=RuntimeError("force-final-cleanup"),
            ),
            patch.object(
                validation,
                "_best_effort_cleanup_replay_names",
                side_effect=cleanup_with_staging_exception,
            ),
        ):
            with self.assertRaises(validation._ReplayOperationalBoundaryError):
                reindex_discovery_from_archive(
                    store,
                    archive,
                    target_db=target,
                    run_id=run_id,
                    expected_source_db_sha256=_file_sha256(store.path),
                )

        self.assertTrue(
            any(
                name.startswith(".discovery-reindex-source-")
                for name in cleanup_calls
            )
        )
        self.assertEqual(
            list(self.root.glob(".discovery-reindex-source-*")), []
        )
        self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
