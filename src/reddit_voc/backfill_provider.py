from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import datetime
from hashlib import sha256
import json
from typing import Any
from urllib.error import HTTPError, URLError

from .backfill_archive import PrivateRawArchive
from .backfill_models import (
    BackfillCheckpoint,
    CursorContract,
    DetailBatch,
    LaneResult,
    RawArtifactMetadata,
    discovery_occurrence_contract,
)
from .backfill_seed import _analysis_row, make_raw_capture_id
from .backfill_storage import BackfillConflictError, BackfillStore
from .adapters import BrowserJsonAdapter
from .analyzer import analyze_text
from .models import RawCapture, RedditComment, RedditThread
from .tikhub import (
    FETCH_DYNAMIC_SEARCH,
    FETCH_POST_COMMENTS,
    FETCH_POST_DETAILS_BATCH_LARGE,
    FETCH_SUBREDDIT_FEED,
    STRICT_SUBREDDIT_V3_CURSOR_PATH,
    STRICT_SUBREDDIT_V3_CURSOR_SCHEMA_SHA256,
    _author_name,
    _extract_backfill_discovery_posts,
    _extract_tikhub_posts_info,
    _normalize_post_id,
    _parse_tikhub_app_detail_payload,
    _parse_strict_tikhub_comment_payload,
    _is_strict_subreddit_v3_terminal_empty,
)
from .time_window import CollectionWindow


_CURSOR_KEYS = frozenset(("endCursor", "nextCursor", "after"))
_REVIEWED_COMMENT_CURSOR_PATH = (
    "data",
    "postInfoById",
    "commentForest",
    "pageInfo",
    "endCursor",
)
# TikHub's terminal zero-comment response omits endCursor and currently emits
# a nullable commentCount. This is a reviewed terminal-only schema variant;
# non-terminal or structurally different responses remain fail-closed.
_REVIEWED_TERMINAL_COMMENT_PAGE_INFO_SCHEMA_SHA256 = (
    "211cadc14d50f34c70cddef3dd91927324f544eddd016d1ed82084e75f67d9cc"
)
_RETRY_DELAYS = (2, 4, 8)
_PER_CALL_PAGE_LIMIT_STOP_REASONS = frozenset(
    ("probe_page_limit", "round_robin_yield")
)
_TERMINAL_DISCOVERY_STOP_REASONS = frozenset(
    ("provider_error", "schema_drift", "cursor_loop")
)
_RECOVERABLE_DISCOVERY_STOP_REASONS = frozenset(
    (
        "probe_page_limit",
        "round_robin_yield",
        "authorized_page_limit",
        "budget_exhausted",
        "discovery_budget_exhausted",
    )
)
_TIKHUB_DISCOVERY_STRICT_PARSER_KIND = "tikhub_discovery_strict_v2"
# Preserve the established parser fault-injection seam while routing it through
# the shared strict backfill contract.
_parse_tikhub_comment_payload = _parse_strict_tikhub_comment_payload


class TikHubSchemaDrift(RuntimeError):
    pass


class ProviderBudgetExhausted(RuntimeError):
    pass


class ProviderPhaseBudgetExhausted(RuntimeError):
    pass


class TikHubProviderError(RuntimeError):
    def __init__(self, *, error_class: str, http_status: int | None = None) -> None:
        self.error_class = error_class
        self.http_status = http_status
        status_suffix = "" if http_status is None else f" (HTTP {http_status})"
        super().__init__(f"TikHub provider request failed: {error_class}{status_suffix}")


def infer_cursor_contract(payload: Any) -> CursorContract:
    candidates: list[tuple[tuple[str | int, ...], dict[str, Any]]] = []
    _collect_cursor_candidates(payload, (), candidates)
    if len(candidates) != 1:
        raise TikHubSchemaDrift("expected exactly one nonempty TikHub cursor")
    cursor_path, page_info = candidates[0]
    return CursorContract(
        cursor_path=cursor_path,
        schema_sha256=_page_info_schema_sha256(page_info),
    )


def extract_next_cursor(
    payload: Any,
    contract: CursorContract,
    *,
    allow_terminal_without_cursor: bool = False,
) -> str | None:
    if type(allow_terminal_without_cursor) is not bool:
        raise TypeError("allow_terminal_without_cursor must be bool")
    if (
        not isinstance(contract.cursor_path, tuple)
        or len(contract.cursor_path) < 2
        or contract.cursor_path[-2] != "pageInfo"
        or contract.cursor_path[-1] not in _CURSOR_KEYS
    ):
        raise TikHubSchemaDrift("invalid persisted TikHub cursor path")

    page_info = _value_at_path(payload, contract.cursor_path[:-1])
    if not isinstance(page_info, dict):
        raise TikHubSchemaDrift("TikHub pageInfo path is missing or invalid")
    cursor_key = contract.cursor_path[-1]
    cursor_missing = cursor_key not in page_info
    if cursor_missing:
        if not (
            allow_terminal_without_cursor
            and page_info.get("hasNextPage") is False
        ):
            raise TikHubSchemaDrift("TikHub cursor path is missing")
        cursor = None
    else:
        cursor = page_info[cursor_key]
    if cursor is not None and not isinstance(cursor, str):
        raise TikHubSchemaDrift("TikHub cursor has an invalid type")
    explicit_terminal = page_info.get("hasNextPage") is False
    candidates: list[tuple[tuple[str | int, ...], dict[str, Any]]] = []
    _collect_cursor_candidates(payload, (), candidates)
    actual_nonempty_paths = {path for path, _ in candidates}
    expected_nonempty_paths = {contract.cursor_path} if cursor else set()
    if actual_nonempty_paths != expected_nonempty_paths:
        raise TikHubSchemaDrift("TikHub cursor moved to a different path")
    page_info_schema_sha256 = _page_info_schema_sha256(page_info)
    if page_info_schema_sha256 != contract.schema_sha256:
        reviewed_terminal_variant = (
            allow_terminal_without_cursor
            and contract.cursor_path == _REVIEWED_COMMENT_CURSOR_PATH
            and cursor is None
            and not actual_nonempty_paths
            and page_info.get("hasNextPage") is False
            and page_info_schema_sha256
            == _REVIEWED_TERMINAL_COMMENT_PAGE_INFO_SCHEMA_SHA256
        )
        if not reviewed_terminal_variant:
            raise TikHubSchemaDrift("TikHub pageInfo schema changed")
    return None if explicit_terminal else cursor or None


def _is_reviewed_incomplete_comment_page(
    payload: Any,
    contract: CursorContract,
    *,
    more_count: int,
) -> bool:
    if type(more_count) is not int or more_count <= 0:
        return False
    if (
        not isinstance(contract.cursor_path, tuple)
        or len(contract.cursor_path) < 2
        or contract.cursor_path[-2] != "pageInfo"
        or contract.cursor_path[-1] not in _CURSOR_KEYS
    ):
        return False
    try:
        page_info = _value_at_path(payload, contract.cursor_path[:-1])
    except TikHubSchemaDrift:
        return False
    cursor_key = contract.cursor_path[-1]
    if (
        not isinstance(page_info, dict)
        or cursor_key in page_info
        or page_info.get("hasNextPage") is not True
        or _page_info_schema_sha256(page_info) != contract.schema_sha256
    ):
        return False
    candidates: list[tuple[tuple[str | int, ...], dict[str, Any]]] = []
    _collect_cursor_candidates(payload, (), candidates)
    return not candidates


class TikHubRequestExecutor:
    def __init__(
        self,
        client: Any,
        store: BackfillStore,
        run_id: str,
        sleep: Callable[[float], Any],
        now: Callable[[], datetime],
        request_ceiling: int | None = None,
    ) -> None:
        if request_ceiling is not None and (
            type(request_ceiling) is not int or request_ceiling < 0
        ):
            raise ValueError(
                "request_ceiling must be a non-negative integer or None"
            )
        self.client = client
        self.store = store
        self.run_id = run_id
        self.sleep = sleep
        self.now = now
        self.request_ceiling = request_ceiling

    def get_json(self, path: str, params: dict[str, Any]) -> Any:
        for attempt_index in range(4):
            request_number = self.store.reserve_provider_request(
                self.run_id,
                path,
                self.now(),
                request_ceiling=self.request_ceiling,
            )
            if request_number is None:
                with self.store.connect() as conn:
                    budget = conn.execute(
                        "SELECT max_provider_requests, provider_request_count "
                        "FROM backfill_manifests WHERE run_id = ?",
                        (self.run_id,),
                    ).fetchone()
                if budget is None:
                    raise KeyError(f"unknown backfill run: {self.run_id}")
                request_count = int(budget["provider_request_count"])
                if request_count >= int(budget["max_provider_requests"]):
                    raise ProviderBudgetExhausted(
                        "TikHub provider request budget exhausted"
                    )
                if (
                    self.request_ceiling is not None
                    and request_count >= self.request_ceiling
                ):
                    raise ProviderPhaseBudgetExhausted(
                        "TikHub provider phase request budget exhausted"
                    )
                raise BackfillConflictError(
                    f"backfill_manifests:{self.run_id}/provider_request_budget"
                )
            if attempt_index:
                self.sleep(_RETRY_DELAYS[attempt_index - 1])
            self.store.mark_provider_attempt_sent(
                self.run_id, request_number, self.now()
            )
            try:
                payload = self.client.get_json(path, params)
            except HTTPError as exc:
                self.store.complete_provider_attempt(
                    self.run_id,
                    request_number,
                    status="failed",
                    completed_at_utc=self.now(),
                    http_status=exc.code,
                    error_class=type(exc).__name__,
                )
                if _retryable_http_status(exc.code) and attempt_index < 3:
                    continue
                raise TikHubProviderError(
                    error_class=type(exc).__name__, http_status=exc.code
                ) from None
            except (URLError, TimeoutError, ConnectionError) as exc:
                self.store.complete_provider_attempt(
                    self.run_id,
                    request_number,
                    status="failed",
                    completed_at_utc=self.now(),
                    error_class=type(exc).__name__,
                )
                if attempt_index < 3:
                    continue
                raise TikHubProviderError(
                    error_class=type(exc).__name__
                ) from None
            except Exception as exc:
                self.store.complete_provider_attempt(
                    self.run_id,
                    request_number,
                    status="failed",
                    completed_at_utc=self.now(),
                    error_class=type(exc).__name__,
                )
                raise TikHubProviderError(
                    error_class=type(exc).__name__
                ) from None
            self.store.complete_provider_attempt(
                self.run_id,
                request_number,
                status="succeeded",
                completed_at_utc=self.now(),
            )
            return payload
        raise AssertionError("unreachable TikHub retry state")


class TikHubBackfillDiscoverer:
    def __init__(
        self,
        executor: TikHubRequestExecutor,
        store: BackfillStore,
        archive: PrivateRawArchive,
        run_id: str,
        now: Callable[[], datetime],
    ) -> None:
        self.executor = executor
        self.store = store
        self.archive = archive
        self.run_id = run_id
        self.now = now

    def run_dynamic_search(
        self,
        query: str,
        window: CollectionWindow,
        max_pages: int | None = None,
        *,
        absolute_page_ceiling: int | None = None,
        page_limit_stop_reason: str = "probe_page_limit",
    ) -> LaneResult:
        return self._run_lane(
            lane_type="dynamic_search",
            lane_key=query,
            endpoint=FETCH_DYNAMIC_SEARCH,
            window=window,
            max_pages=max_pages,
            absolute_page_ceiling=absolute_page_ceiling,
            page_limit_stop_reason=page_limit_stop_reason,
        )

    def run_subreddit_feed(
        self,
        subreddit: str,
        window: CollectionWindow,
        max_pages: int | None = None,
        *,
        absolute_page_ceiling: int | None = None,
        page_limit_stop_reason: str = "probe_page_limit",
    ) -> LaneResult:
        return self._run_lane(
            lane_type="subreddit_feed",
            lane_key=subreddit,
            endpoint=FETCH_SUBREDDIT_FEED,
            window=window,
            max_pages=max_pages,
            absolute_page_ceiling=absolute_page_ceiling,
            page_limit_stop_reason=page_limit_stop_reason,
        )

    def _run_lane(
        self,
        *,
        lane_type: str,
        lane_key: str,
        endpoint: str,
        window: CollectionWindow,
        max_pages: int | None,
        absolute_page_ceiling: int | None,
        page_limit_stop_reason: str,
    ) -> LaneResult:
        if max_pages is not None and (
            isinstance(max_pages, bool)
            or not isinstance(max_pages, int)
            or max_pages <= 0
        ):
            raise ValueError("max_pages must be a positive integer or None")
        if absolute_page_ceiling is not None and (
            type(absolute_page_ceiling) is not int
            or absolute_page_ceiling < 0
        ):
            raise ValueError(
                "absolute_page_ceiling must be a non-negative integer or None"
            )
        if (
            type(page_limit_stop_reason) is not str
            or page_limit_stop_reason not in _PER_CALL_PAGE_LIMIT_STOP_REASONS
        ):
            raise ValueError(
                "page_limit_stop_reason must be probe_page_limit "
                "or round_robin_yield"
            )
        checkpoint = self.store.load_checkpoint(
            run_id=self.run_id, lane_type=lane_type, lane_key=lane_key
        )
        if checkpoint is None:
            checkpoint = self._initial_checkpoint(lane_type, lane_key)
        if absolute_page_ceiling is not None:
            if checkpoint.page_number > absolute_page_ceiling:
                raise BackfillConflictError(
                    "backfill_checkpoints:"
                    f"{self.run_id}/{lane_type}/{lane_key}/absolute_page_ceiling"
                )
            if checkpoint.page_number == absolute_page_ceiling:
                if (
                    checkpoint.status in {"complete", "failed"}
                    or checkpoint.stop_reason in _TERMINAL_DISCOVERY_STOP_REASONS
                ):
                    return self._result(checkpoint)
                if not (
                    checkpoint.status == "running"
                    or checkpoint.stop_reason
                    in _RECOVERABLE_DISCOVERY_STOP_REASONS
                ):
                    raise BackfillConflictError(
                        "backfill_checkpoints:"
                        f"{self.run_id}/{lane_type}/{lane_key}/absolute_page_ceiling"
                    )
                checkpoint = replace(
                    checkpoint,
                    provider_request_count=self.store.provider_request_count(
                        self.run_id
                    ),
                    last_error=None,
                    status="partial",
                    stop_reason="authorized_page_limit",
                )
                self.store.save_checkpoint(checkpoint)
                return self._result(checkpoint)
        if checkpoint.status == "complete":
            return self._result(checkpoint)

        pages_this_call = 0
        while True:
            request_cursor = checkpoint.cursor
            params = self._params(
                lane_type=lane_type,
                lane_key=lane_key,
                cursor=request_cursor,
            )
            try:
                payload = self.executor.get_json(endpoint, params)
            except ProviderPhaseBudgetExhausted:
                checkpoint = replace(
                    checkpoint,
                    provider_request_count=self.store.provider_request_count(
                        self.run_id
                    ),
                    last_error="ProviderPhaseBudgetExhausted",
                    status="partial",
                    stop_reason="discovery_budget_exhausted",
                )
                self.store.save_checkpoint(checkpoint)
                return self._result(checkpoint)
            except ProviderBudgetExhausted:
                checkpoint = replace(
                    checkpoint,
                    provider_request_count=self.store.provider_request_count(
                        self.run_id
                    ),
                    last_error="ProviderBudgetExhausted",
                    status="partial",
                    stop_reason="budget_exhausted",
                )
                self.store.save_checkpoint(checkpoint)
                return self._result(checkpoint)
            except TikHubProviderError as exc:
                checkpoint = replace(
                    checkpoint,
                    provider_request_count=self.store.provider_request_count(
                        self.run_id
                    ),
                    last_error=exc.error_class,
                    status="failed" if checkpoint.page_number == 0 else "partial",
                    stop_reason="provider_error",
                )
                self.store.save_checkpoint(checkpoint)
                return self._result(checkpoint)

            payload_bytes = _canonical_json_bytes(payload)
            archived_payload = json.loads(payload_bytes)
            payload_sha256 = sha256(payload_bytes).hexdigest()
            page_number = checkpoint.page_number + 1
            source_method = f"tikhub_{lane_type}"
            source_url = _hashed_tikhub_source_url(
                run_id=self.run_id,
                lane_type=lane_type,
                lane_key=lane_key,
                endpoint=endpoint,
                page_number=page_number,
                request_cursor=request_cursor,
            )
            raw_capture_id = make_raw_capture_id(
                run_id=self.run_id,
                source_method=source_method,
                source_url=source_url,
                payload_sha256=payload_sha256,
            )
            captured_at_utc = self._capture_time(
                raw_capture_id=raw_capture_id,
                source_method=source_method,
                source_url=source_url,
                payload_sha256=payload_sha256,
            )
            capture = RawCapture(
                raw_capture_id=raw_capture_id,
                run_id=self.run_id,
                source_method=source_method,
                source_url=source_url,
                captured_at_utc=captured_at_utc,
                auth_boundary="provider_gate",
                raw_payload_hash=f"sha256:{payload_sha256}",
                payload_format="json",
            )
            artifact = self.archive.write(
                run_id=self.run_id,
                artifact_kind="discovery",
                lane_type=lane_type,
                lane_key=lane_key,
                identity=source_url.removeprefix("tikhub://"),
                payload=payload_bytes,
                raw_capture_id=raw_capture_id,
                parser_kind=_TIKHUB_DISCOVERY_STRICT_PARSER_KIND,
                source_method=source_method,
                source_url=source_url,
                source_endpoint=endpoint,
                captured_at_utc=captured_at_utc,
                page_number=page_number,
                request_cursor=request_cursor,
                response_cursor=None,
            )

            try:
                contract, next_cursor, posts = self._parse_discovery_payload(
                    checkpoint=checkpoint,
                    payload=archived_payload,
                    source_method=source_method,
                )
            except TikHubSchemaDrift:
                self._persist_raw(capture, artifact)
                checkpoint = replace(
                    checkpoint,
                    provider_request_count=self.store.provider_request_count(
                        self.run_id
                    ),
                    last_error="TikHubSchemaDrift",
                    status="partial",
                    stop_reason="schema_drift",
                )
                self.store.save_checkpoint(checkpoint)
                return self._result(checkpoint)

            artifact = replace(artifact, response_cursor=next_cursor)
            self._persist_raw(capture, artifact)

            page_times: list[datetime] = []
            for ordinal, post in enumerate(posts):
                if post.created_at_utc is not None:
                    page_times.append(post.created_at_utc)
                (
                    base_disposition,
                    post_id,
                    source_url,
                    created_at_utc,
                ) = discovery_occurrence_contract(
                    post_id=post.post_id,
                    source_url=post.source_url,
                    title=post.title,
                    created_at_utc=post.created_at_utc,
                    window_start_utc=window.start_utc,
                    window_end_utc=window.end_utc,
                )
                self.store.record_discovery_occurrence(
                    run_id=self.run_id,
                    lane_type=lane_type,
                    lane_key=lane_key,
                    page_number=page_number,
                    ordinal=ordinal,
                    post_id=post_id,
                    source_url=source_url,
                    post_created_at_utc=created_at_utc,
                    raw_artifact_id=artifact.artifact_id,
                    discovered_at_utc=captured_at_utc,
                    base_disposition=base_disposition,
                )

            occurrence_counts = self.store.discovery_occurrence_counts(
                self.run_id, lane_type, lane_key
            )
            newest_seen, oldest_seen = _cumulative_time_bounds(
                checkpoint, page_times
            )
            consecutive_old_pages = (
                checkpoint.consecutive_old_pages + 1
                if page_times and max(page_times) < window.start_utc
                else 0
            )
            cursor_path_json = json.dumps(
                list(contract.cursor_path),
                ensure_ascii=False,
                separators=(",", ":"),
            )
            pages_this_call += 1

            status = "running"
            stop_reason = None
            if next_cursor is None:
                status = "complete"
                stop_reason = "cursor_exhausted"
            elif self.store.request_cursor_seen(
                self.run_id,
                lane_type,
                artifact.lane_key_hash,
                next_cursor,
            ):
                status = "partial"
                stop_reason = "cursor_loop"
            elif consecutive_old_pages >= 2:
                status = "complete"
                stop_reason = "older_than_window"
            elif (
                absolute_page_ceiling is not None
                and page_number >= absolute_page_ceiling
            ):
                status = "partial"
                stop_reason = "authorized_page_limit"
            elif max_pages is not None and pages_this_call >= max_pages:
                status = "partial"
                stop_reason = page_limit_stop_reason

            checkpoint = BackfillCheckpoint(
                run_id=self.run_id,
                lane_type=lane_type,
                lane_key=lane_key,
                cursor=next_cursor,
                previous_cursor=request_cursor,
                page_number=page_number,
                newest_seen_utc=newest_seen,
                oldest_seen_utc=oldest_seen,
                discovered_count=sum(occurrence_counts.values()),
                unique_count=occurrence_counts.get("new_candidate", 0),
                provider_request_count=self.store.provider_request_count(
                    self.run_id
                ),
                last_success_utc=captured_at_utc.isoformat(),
                last_error=None,
                status=status,
                stop_reason=stop_reason,
                cursor_json_path=cursor_path_json,
                cursor_schema_sha256=contract.schema_sha256,
                consecutive_old_pages=consecutive_old_pages,
            )
            self.store.save_checkpoint(checkpoint)
            if status != "running":
                return self._result(checkpoint)

    def _initial_checkpoint(
        self, lane_type: str, lane_key: str
    ) -> BackfillCheckpoint:
        return BackfillCheckpoint(
            run_id=self.run_id,
            lane_type=lane_type,
            lane_key=lane_key,
            cursor=None,
            previous_cursor=None,
            page_number=0,
            newest_seen_utc=None,
            oldest_seen_utc=None,
            discovered_count=0,
            unique_count=0,
            provider_request_count=self.store.provider_request_count(self.run_id),
            last_success_utc=None,
            last_error=None,
            status="prepared",
            stop_reason=None,
            cursor_json_path=None,
            cursor_schema_sha256=None,
            consecutive_old_pages=0,
        )

    @staticmethod
    def _params(
        *, lane_type: str, lane_key: str, cursor: str | None
    ) -> dict[str, str]:
        if lane_type == "dynamic_search":
            return {
                "query": lane_key,
                "search_type": "post",
                "sort": "NEW",
                "time_range": "all",
                "after": cursor or "",
                "need_format": "false",
            }
        return {
            "subreddit_name": lane_key,
            "sort": "NEW",
            "after": cursor or "",
            "need_format": "false",
        }

    def _capture_time(
        self,
        *,
        raw_capture_id: str,
        source_method: str,
        source_url: str,
        payload_sha256: str,
    ) -> datetime:
        persisted = self.store.load_raw_capture(raw_capture_id)
        if persisted is None:
            return self.now()
        expected = (
            self.run_id,
            source_method,
            source_url,
            f"sha256:{payload_sha256}",
        )
        actual = (
            persisted.run_id,
            persisted.source_method,
            persisted.source_url,
            persisted.raw_payload_hash,
        )
        if actual != expected:
            raise BackfillConflictError(f"raw_captures:{raw_capture_id}")
        return persisted.captured_at_utc

    def _persist_raw(self, capture: RawCapture, artifact: Any) -> None:
        self.store.insert_entity_bundle(
            captures=(capture,), threads=(), comments=(), analyses=()
        )
        self.store.insert_raw_artifact(artifact)

    @staticmethod
    def _cursor_contract(
        checkpoint: BackfillCheckpoint, payload: Any
    ) -> CursorContract:
        if checkpoint.cursor_json_path is None and checkpoint.cursor_schema_sha256 is None:
            if checkpoint.page_number:
                raise TikHubSchemaDrift("persisted cursor contract is missing")
            return infer_cursor_contract(payload)
        if (
            checkpoint.cursor_json_path is None
            or checkpoint.cursor_schema_sha256 is None
        ):
            raise TikHubSchemaDrift("persisted cursor contract is incomplete")
        try:
            decoded_path = json.loads(checkpoint.cursor_json_path)
        except (TypeError, json.JSONDecodeError):
            raise TikHubSchemaDrift("persisted cursor path is invalid") from None
        if (
            not isinstance(decoded_path, list)
            or not decoded_path
            or any(
                isinstance(component, bool)
                or not isinstance(component, (str, int))
                for component in decoded_path
            )
        ):
            raise TikHubSchemaDrift("persisted cursor path is invalid")
        return CursorContract(
            cursor_path=tuple(decoded_path),
            schema_sha256=checkpoint.cursor_schema_sha256,
        )

    @classmethod
    def _parse_discovery_payload(
        cls,
        *,
        checkpoint: BackfillCheckpoint,
        payload: Any,
        source_method: str,
    ) -> tuple[CursorContract, str | None, list[Any]]:
        try:
            if source_method == "tikhub_subreddit_feed":
                reviewed_contract = CursorContract(
                    cursor_path=STRICT_SUBREDDIT_V3_CURSOR_PATH,
                    schema_sha256=STRICT_SUBREDDIT_V3_CURSOR_SCHEMA_SHA256,
                )
                if (
                    checkpoint.cursor_json_path is None
                    and checkpoint.cursor_schema_sha256 is None
                    and checkpoint.page_number == 0
                ):
                    contract = reviewed_contract
                else:
                    contract = cls._cursor_contract(checkpoint, payload)
                if contract != reviewed_contract:
                    raise TikHubSchemaDrift(
                        "persisted subredditV3 cursor contract changed"
                    )
                if _is_strict_subreddit_v3_terminal_empty(payload):
                    candidates: list[
                        tuple[tuple[str | int, ...], dict[str, Any]]
                    ] = []
                    _collect_cursor_candidates(payload, (), candidates)
                    if candidates:
                        raise TikHubSchemaDrift(
                            "TikHub subredditV3 terminal page has a remote cursor"
                        )
                    next_cursor = None
                else:
                    next_cursor = extract_next_cursor(payload, contract)
            else:
                contract = cls._cursor_contract(checkpoint, payload)
                next_cursor = extract_next_cursor(payload, contract)
            posts = _extract_backfill_discovery_posts(
                payload,
                source_method,
                dedupe=False,
                lane_key=checkpoint.lane_key,
            )
        except TikHubSchemaDrift:
            raise
        except Exception:
            raise TikHubSchemaDrift(
                "TikHub discovery payload parser failed"
            ) from None
        return contract, next_cursor, posts

    def _result(self, checkpoint: BackfillCheckpoint) -> LaneResult:
        status = checkpoint.status
        if status not in {"complete", "partial", "failed"}:
            status = "partial"
        return LaneResult(
            run_id=self.run_id,
            lane_type=checkpoint.lane_type,
            lane_key=checkpoint.lane_key,
            status=status,
            stop_reason=checkpoint.stop_reason or "incomplete",
            pages=checkpoint.page_number,
            discovered_occurrences=checkpoint.discovered_count,
            unique_candidates=checkpoint.unique_count,
            provider_request_count=self.store.provider_request_count(self.run_id),
            provider_call=self.store.provider_call_evidence(self.run_id),
            live_send=False,
        )


class _HydrationAbort(RuntimeError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class TikHubDetailHydrator:
    def __init__(
        self,
        executor: TikHubRequestExecutor,
        store: BackfillStore,
        archive: PrivateRawArchive,
        run_id: str,
        now: Callable[[], datetime],
    ) -> None:
        self.executor = executor
        self.store = store
        self.archive = archive
        self.run_id = run_id
        self.now = now

    def hydrate(
        self,
        *,
        post_ids: Sequence[str],
        window: CollectionWindow,
        comment_cursor_contract: CursorContract,
    ) -> LaneResult:
        if not isinstance(window, CollectionWindow):
            raise ValueError("window must be a CollectionWindow")
        if not isinstance(comment_cursor_contract, CursorContract):
            raise ValueError("comment_cursor_contract must be a CursorContract")
        if isinstance(post_ids, (str, bytes)):
            raise ValueError("post_ids must be a sequence of Reddit post IDs")
        normalized_ids: set[str] = set()
        for value in post_ids:
            if not isinstance(value, str):
                raise ValueError("post_ids must contain only strings")
            post_id = _normalize_post_id(value).strip()
            if not post_id:
                raise ValueError("post_ids must contain only non-empty IDs")
            normalized_ids.add(post_id)
        requested = tuple(sorted(normalized_ids))
        candidates = self.store.load_candidates(
            run_id=self.run_id, post_ids=requested
        )
        self._validate_batch_selection(requested, candidates)

        for candidate in candidates:
            if candidate["status"] != "pending":
                continue
            post_id = str(candidate["post_id"])
            if self.store.structured_thread_run_id(post_id) is not None:
                self._finalize_without_entities(
                    post_id,
                    status="duplicate_existing_structured",
                    reason=None,
                )

        candidates = self.store.load_candidates(
            run_id=self.run_id, post_ids=requested
        )
        self._repair_selected_terminal_batches(requested)
        pending_ids = tuple(
            str(candidate["post_id"])
            for candidate in candidates
            if candidate["status"] == "pending"
        )
        if not pending_ids:
            return self._result()

        self.store.prepare_detail_batches(
            run_id=self.run_id,
            post_ids=pending_ids,
            created_at_utc=self.now(),
        )
        batches = self.store.load_detail_batches(
            run_id=self.run_id, post_ids=pending_ids
        )

        for batch in batches:
            if batch.status == "complete":
                continue
            if batch.status == "failed":
                self._repair_failed_batch(batch)
                continue

            try:
                payload, detail_capture = self._detail_payload(batch)
            except ProviderBudgetExhausted:
                self._abort_selected(requested, batches, "budget_exhausted")
                return self._result()
            except TikHubProviderError:
                self._abort_selected(requested, batches, "provider_error")
                return self._result()
            except TikHubSchemaDrift:
                self._abort_selected(requested, batches, "detail_schema_drift")
                return self._result()

            try:
                threads, submitters, missing, unparseable = self._parse_detail_batch(
                    batch, payload, detail_capture.raw_capture_id
                )
            except TikHubSchemaDrift:
                self._abort_selected(requested, batches, "detail_schema_drift")
                return self._result()

            for post_id in batch.post_ids:
                candidate = self.store.load_candidates(
                    run_id=self.run_id, post_ids=(post_id,)
                )[0]
                if candidate["status"] != "pending":
                    continue
                if post_id in missing:
                    self._finalize_without_entities(
                        post_id, status="failed", reason="detail_missing"
                    )
                    continue
                if post_id in unparseable:
                    self._finalize_without_entities(
                        post_id, status="failed", reason="detail_unparseable"
                    )
                    continue
                thread = threads[post_id]
                if not window.contains_utc(thread.created_at_utc):
                    self._finalize_without_entities(
                        post_id,
                        status="outside_window_detail",
                        reason=None,
                    )
                    continue
                try:
                    self._hydrate_candidate(
                        thread=thread,
                        detail_capture=detail_capture,
                        submitter_name=submitters.get(post_id, ""),
                        cursor_contract=comment_cursor_contract,
                    )
                except _HydrationAbort as abort:
                    self._abort_selected(requested, batches, abort.reason)
                    return self._result()

            current = self.store.load_detail_batches(
                run_id=self.run_id, post_ids=batch.post_ids
            )[0]
            if current.status in {"prepared", "raw_persisted"}:
                self.store.finish_detail_batch(
                    run_id=self.run_id,
                    batch_id=batch.batch_id,
                    status="complete",
                    stop_reason=None,
                    updated_at_utc=self.now(),
                )

        return self._result()

    def recover_archived(
        self, *, window: CollectionWindow
    ) -> tuple[str, ...]:
        """Consume already archived detail/comment pages without Provider I/O."""
        if not isinstance(window, CollectionWindow):
            raise ValueError("window must be a CollectionWindow")
        provider_count_before = self.store.provider_request_count(self.run_id)
        recovered: list[str] = []
        for batch in self.store.load_detail_batches(run_id=self.run_id):
            if batch.artifact_id is None:
                continue
            if batch.status == "complete":
                members = self.store.load_candidates(
                    run_id=self.run_id, post_ids=batch.post_ids
                )
                if any(member["status"] == "pending" for member in members):
                    raise BackfillConflictError(
                        f"backfill_detail_batches:{self.run_id}/{batch.batch_id}"
                    )
                continue
            if batch.status != "raw_persisted":
                raise BackfillConflictError(
                    f"backfill_detail_batches:{self.run_id}/{batch.batch_id}"
                )
            payload, detail_capture = self._detail_payload(batch)
            threads, submitters, missing, unparseable = self._parse_detail_batch(
                batch, payload, detail_capture.raw_capture_id
            )
            for post_id in batch.post_ids:
                candidate = self.store.load_candidates(
                    run_id=self.run_id, post_ids=(post_id,)
                )[0]
                if candidate["status"] != "pending":
                    continue
                comment_artifacts = self.store.load_raw_artifacts(
                    run_id=self.run_id,
                    lane_type="comments",
                    lane_key=post_id,
                )
                if not comment_artifacts:
                    continue
                if post_id in missing or post_id in unparseable or post_id not in threads:
                    raise TikHubSchemaDrift(
                        "archived detail response cannot hydrate comments"
                    )
                thread = threads[post_id]
                if not window.contains_utc(thread.created_at_utc):
                    self._finalize_without_entities(
                        post_id,
                        status="outside_window_detail",
                        reason=None,
                    )
                    recovered.append(post_id)
                    continue
                checkpoint = self.store.load_checkpoint(
                    run_id=self.run_id,
                    lane_type="comments",
                    lane_key=post_id,
                )
                cursor_contract = self._persisted_comment_cursor_contract(
                    post_id, checkpoint
                )
                self._hydrate_candidate(
                    thread=thread,
                    detail_capture=detail_capture,
                    submitter_name=submitters.get(post_id, ""),
                    cursor_contract=cursor_contract,
                    archived_only=True,
                )
                updated = self.store.load_candidates(
                    run_id=self.run_id, post_ids=(post_id,)
                )[0]
                if updated["status"] != "pending":
                    recovered.append(post_id)
            current_members = self.store.load_candidates(
                run_id=self.run_id, post_ids=batch.post_ids
            )
            if not any(member["status"] == "pending" for member in current_members):
                self.store.finish_detail_batch(
                    run_id=self.run_id,
                    batch_id=batch.batch_id,
                    status="complete",
                    stop_reason=None,
                    updated_at_utc=self.now(),
                )
        if self.store.provider_request_count(self.run_id) != provider_count_before:
            raise BackfillConflictError(
                f"backfill_manifests:{self.run_id}/provider_request_budget"
            )
        return tuple(recovered)

    def _persisted_comment_cursor_contract(
        self,
        post_id: str,
        checkpoint: BackfillCheckpoint | None,
    ) -> CursorContract:
        conflict_key = f"backfill_checkpoints:{self.run_id}/comments/{post_id}"
        if (
            checkpoint is None
            or type(checkpoint.cursor_json_path) is not str
            or type(checkpoint.cursor_schema_sha256) is not str
            or len(checkpoint.cursor_schema_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in checkpoint.cursor_schema_sha256
            )
        ):
            raise BackfillConflictError(conflict_key)
        try:
            decoded = json.loads(checkpoint.cursor_json_path)
        except json.JSONDecodeError:
            raise BackfillConflictError(conflict_key) from None
        if (
            not isinstance(decoded, list)
            or len(decoded) < 2
            or any(type(component) not in {str, int} for component in decoded)
        ):
            raise BackfillConflictError(conflict_key)
        contract = CursorContract(
            cursor_path=tuple(decoded),
            schema_sha256=checkpoint.cursor_schema_sha256,
        )
        if (
            contract.cursor_path[-2] != "pageInfo"
            or contract.cursor_path[-1] not in _CURSOR_KEYS
        ):
            raise BackfillConflictError(conflict_key)
        return contract

    def _repair_selected_terminal_batches(
        self, requested: tuple[str, ...]
    ) -> None:
        if not requested:
            return
        for batch in self.store.load_detail_batches(
            run_id=self.run_id, post_ids=requested
        ):
            if batch.status in {"complete", "failed"}:
                continue
            members = self.store.load_candidates(
                run_id=self.run_id, post_ids=batch.post_ids
            )
            if any(member["status"] == "pending" for member in members):
                continue
            if batch.status == "prepared":
                artifacts = self.store.load_raw_artifacts(
                    run_id=self.run_id,
                    lane_type="detail_batch",
                    lane_key=batch.batch_id,
                )
                if not artifacts:
                    raise BackfillConflictError(
                        f"backfill_detail_batches:{self.run_id}/{batch.batch_id}"
                    )
            self._detail_payload(batch)
            self.store.finish_detail_batch(
                run_id=self.run_id,
                batch_id=batch.batch_id,
                status="complete",
                stop_reason=None,
                updated_at_utc=self.now(),
            )

    def _validate_batch_selection(
        self,
        requested: tuple[str, ...],
        candidates: tuple[dict[str, object], ...],
    ) -> None:
        if not requested:
            return
        pending_selected = {
            str(candidate["post_id"])
            for candidate in candidates
            if candidate["status"] == "pending"
        }
        requested_set = set(requested)
        for batch in self.store.load_detail_batches(
            run_id=self.run_id, post_ids=requested
        ):
            members = self.store.load_candidates(
                run_id=self.run_id, post_ids=batch.post_ids
            )
            pending_members = {
                str(member["post_id"])
                for member in members
                if member["status"] == "pending"
            }
            if pending_selected.intersection(pending_members) and not pending_members.issubset(
                requested_set
            ):
                raise ValueError(
                    "all pending members of a persisted detail batch must be selected"
                )

    def _detail_payload(
        self, batch: DetailBatch
    ) -> tuple[Any, RawCapture]:
        artifacts = self.store.load_raw_artifacts(
            run_id=self.run_id,
            lane_type="detail_batch",
            lane_key=batch.batch_id,
        )
        if batch.artifact_id is not None and (
            len(artifacts) != 1
            or artifacts[0].artifact_id != batch.artifact_id
        ):
            raise BackfillConflictError(
                f"backfill_detail_batches:{self.run_id}/{batch.batch_id}"
            )
        if batch.artifact_id is None and len(artifacts) > 1:
            raise BackfillConflictError(
                f"backfill_detail_batches:{self.run_id}/{batch.batch_id}"
            )
        if artifacts:
            artifact = artifacts[0]
            self._validate_detail_artifact(batch, artifact)
            capture = self._capture_from_artifact(artifact)
            payload_bytes = self.archive.read_verified(artifact)
            payload = self._decode_archived_json(payload_bytes, artifact)
            if batch.artifact_id is None:
                self.store.attach_detail_batch_artifact(
                    run_id=self.run_id,
                    batch_id=batch.batch_id,
                    artifact_id=artifact.artifact_id,
                    updated_at_utc=self.now(),
                )
            return payload, capture
        if batch.status == "raw_persisted" or batch.artifact_id is not None:
            raise BackfillConflictError(
                f"backfill_detail_batches:{self.run_id}/{batch.batch_id}"
            )

        params = {
            "post_ids": ",".join(f"t3_{post_id}" for post_id in batch.post_ids),
            "include_comment_id": "false",
            "comment_id": "",
            "need_format": "false",
        }
        payload = self.executor.get_json(FETCH_POST_DETAILS_BATCH_LARGE, params)
        payload_bytes = _canonical_json_bytes(payload)
        payload_sha256 = sha256(payload_bytes).hexdigest()
        source_url = _hashed_tikhub_source_url(
            run_id=self.run_id,
            lane_type="detail_batch",
            lane_key=batch.batch_id,
            endpoint=FETCH_POST_DETAILS_BATCH_LARGE,
            page_number=batch.batch_number,
            request_cursor=None,
        )
        source_method = "tikhub_detail"
        raw_capture_id = make_raw_capture_id(
            run_id=self.run_id,
            source_method=source_method,
            source_url=source_url,
            payload_sha256=payload_sha256,
        )
        captured_at_utc = self._capture_time(
            raw_capture_id=raw_capture_id,
            source_method=source_method,
            source_url=source_url,
            payload_sha256=payload_sha256,
        )
        capture = RawCapture(
            raw_capture_id=raw_capture_id,
            run_id=self.run_id,
            source_method=source_method,
            source_url=source_url,
            captured_at_utc=captured_at_utc,
            auth_boundary="provider_gate",
            raw_payload_hash=f"sha256:{payload_sha256}",
            payload_format="json",
        )
        artifact = self.archive.write(
            run_id=self.run_id,
            artifact_kind="detail",
            lane_type="detail_batch",
            lane_key=batch.batch_id,
            identity=source_url.removeprefix("tikhub://"),
            payload=payload_bytes,
            raw_capture_id=raw_capture_id,
            parser_kind="tikhub_detail",
            source_method=source_method,
            source_url=source_url,
            source_endpoint=FETCH_POST_DETAILS_BATCH_LARGE,
            captured_at_utc=captured_at_utc,
            page_number=batch.batch_number,
            request_cursor=None,
            response_cursor=None,
        )
        self.store.insert_entity_bundle(
            captures=(capture,), threads=(), comments=(), analyses=()
        )
        self.store.insert_raw_artifact(artifact)
        self.store.attach_detail_batch_artifact(
            run_id=self.run_id,
            batch_id=batch.batch_id,
            artifact_id=artifact.artifact_id,
            updated_at_utc=self.now(),
        )
        return payload, capture

    def _validate_detail_artifact(
        self, batch: DetailBatch, artifact: RawArtifactMetadata
    ) -> None:
        expected_source_url = _hashed_tikhub_source_url(
            run_id=self.run_id,
            lane_type="detail_batch",
            lane_key=batch.batch_id,
            endpoint=FETCH_POST_DETAILS_BATCH_LARGE,
            page_number=batch.batch_number,
            request_cursor=None,
        )
        expected_capture_id = make_raw_capture_id(
            run_id=self.run_id,
            source_method="tikhub_detail",
            source_url=expected_source_url,
            payload_sha256=artifact.payload_sha256,
        )
        if (
            artifact.run_id != self.run_id
            or artifact.artifact_kind != "detail"
            or artifact.lane_type != "detail_batch"
            or artifact.lane_key_hash != sha256(batch.batch_id.encode()).hexdigest()
            or artifact.parser_kind != "tikhub_detail"
            or artifact.source_method != "tikhub_detail"
            or artifact.source_url != expected_source_url
            or artifact.identity_hash
            != sha256(expected_source_url.removeprefix("tikhub://").encode()).hexdigest()
            or artifact.raw_capture_id != expected_capture_id
            or artifact.source_endpoint != FETCH_POST_DETAILS_BATCH_LARGE
            or artifact.page_number != batch.batch_number
            or artifact.request_cursor is not None
            or artifact.response_cursor is not None
        ):
            raise BackfillConflictError(
                f"backfill_raw_artifacts:{self.run_id}/{artifact.artifact_id}"
            )

    @staticmethod
    def _decode_archived_json(
        payload_bytes: bytes, artifact: RawArtifactMetadata
    ) -> Any:
        try:
            return json.loads(payload_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise BackfillConflictError(
                f"backfill_raw_artifacts:{artifact.run_id}/{artifact.artifact_id}"
            ) from None

    def _parse_detail_batch(
        self,
        batch: DetailBatch,
        payload: Any,
        raw_capture_id: str,
    ) -> tuple[dict[str, RedditThread], dict[str, str], set[str], set[str]]:
        requested = set(batch.post_ids)
        post_infos = self._validated_detail_post_infos(payload)
        returned_ids = [
            _normalize_post_id(post_info.get("id"))
            for post_info in post_infos
            if post_info.get("id")
        ]
        if len(returned_ids) != len(set(returned_ids)) or any(
            post_id not in requested for post_id in returned_ids
        ):
            raise TikHubSchemaDrift("detail response IDs do not match batch")
        try:
            parsed = _parse_tikhub_app_detail_payload(
                payload,
                comment_payloads={},
                run_id=self.run_id,
                raw_capture_id=raw_capture_id,
            )
        except Exception:
            raise TikHubSchemaDrift("detail payload parser failed") from None
        parsed_threads = [thread for thread, _comments in parsed]
        parsed_ids = [thread.post_id for thread in parsed_threads]
        if len(parsed_ids) != len(set(parsed_ids)) or any(
            post_id not in requested for post_id in parsed_ids
        ):
            raise TikHubSchemaDrift("parsed detail IDs do not match batch")
        invalid_source_ids = {
            _normalize_post_id(post_info.get("id"))
            for post_info in post_infos
            if not isinstance(
                post_info.get("url") or post_info.get("permalink"), str
            )
            or not str(
                post_info.get("url") or post_info.get("permalink") or ""
            ).strip()
        }
        threads = {
            thread.post_id: thread
            for thread in parsed_threads
            if thread.post_id not in invalid_source_ids and thread.source_url
        }
        returned = set(returned_ids)
        missing = requested - returned
        unparseable = returned - set(threads)
        submitters = {
            _normalize_post_id(post_info.get("id")): (
                _author_name(post_info.get("authorInfo"))
                or str(post_info.get("author") or "")
            )
            for post_info in post_infos
            if post_info.get("id")
        }
        return threads, submitters, missing, unparseable

    @staticmethod
    def _validated_detail_post_infos(payload: Any) -> list[dict[str, Any]]:
        containers: list[Any] = []

        def collect(value: Any) -> None:
            if isinstance(value, dict):
                if "postsInfoByIds" in value:
                    containers.append(value["postsInfoByIds"])
                for child in value.values():
                    collect(child)
            elif isinstance(value, list):
                for child in value:
                    collect(child)

        collect(payload)
        if len(containers) != 1 or not isinstance(containers[0], list):
            raise TikHubSchemaDrift("detail postsInfoByIds is missing or ambiguous")
        rows = containers[0]
        if any(not isinstance(row, dict) for row in rows):
            raise TikHubSchemaDrift("detail response contains a malformed row")
        post_infos = list(rows)
        for post_info in post_infos:
            raw_id = post_info.get("id")
            if not isinstance(raw_id, str) or not _normalize_post_id(raw_id).strip():
                raise TikHubSchemaDrift("detail response contains a malformed ID")
        extracted = _extract_tikhub_posts_info(payload)
        if extracted != post_infos:
            raise TikHubSchemaDrift("detail response rows are ambiguous")
        return post_infos

    def _repair_failed_batch(self, batch: DetailBatch) -> None:
        if not batch.stop_reason:
            raise BackfillConflictError(
                f"backfill_detail_batches:{self.run_id}/{batch.batch_id}"
            )
        status = (
            "budget_deferred"
            if batch.stop_reason == "budget_exhausted"
            else "failed"
        )
        for candidate in self.store.load_candidates(
            run_id=self.run_id, post_ids=batch.post_ids
        ):
            if candidate["status"] == "pending":
                self._finalize_without_entities(
                    str(candidate["post_id"]),
                    status=status,
                    reason=batch.stop_reason,
                )

    def _abort_selected(
        self,
        requested: tuple[str, ...],
        batches: tuple[DetailBatch, ...],
        reason: str,
    ) -> None:
        status = "budget_deferred" if reason == "budget_exhausted" else "failed"
        for batch in batches:
            current = self.store.load_detail_batches(
                run_id=self.run_id, post_ids=batch.post_ids
            )[0]
            if current.status in {"prepared", "raw_persisted"}:
                self.store.finish_detail_batch(
                    run_id=self.run_id,
                    batch_id=current.batch_id,
                    status="failed",
                    stop_reason=reason,
                    updated_at_utc=self.now(),
                )
        for candidate in self.store.load_candidates(
            run_id=self.run_id, post_ids=requested
        ):
            if candidate["status"] == "pending":
                self._finalize_without_entities(
                    str(candidate["post_id"]), status=status, reason=reason
                )

    def _finalize_without_entities(
        self, post_id: str, *, status: str, reason: str | None
    ) -> None:
        self.store.finalize_candidate(
            run_id=self.run_id,
            post_id=post_id,
            expected_statuses=("pending",),
            status=status,
            status_reason=reason,
            updated_at_utc=self.now(),
        )

    def _hydrate_candidate(
        self,
        *,
        thread: RedditThread,
        detail_capture: RawCapture,
        submitter_name: str,
        cursor_contract: CursorContract,
        archived_only: bool = False,
    ) -> None:
        if type(archived_only) is not bool:
            raise ValueError("archived_only must be a bool")
        checkpoint = self._comment_checkpoint(thread.post_id, cursor_contract)
        try:
            (
                checkpoint,
                comments,
                captures,
                more_node_count,
                conflict,
            ) = self._restore_comment_chain(
                thread=thread,
                submitter_name=submitter_name,
                checkpoint=checkpoint,
                cursor_contract=cursor_contract,
            )
        except _HydrationAbort as abort:
            if abort.reason != "comments_schema_drift":
                raise
            self._finalize_without_entities(
                thread.post_id,
                status="failed",
                reason="comments_schema_drift",
            )
            return
        if conflict:
            checkpoint = self._comment_failure_checkpoint(
                checkpoint,
                reason="comment_conflict",
                last_error="comment_conflict",
            )
            self.store.save_checkpoint(checkpoint)
            self._finalize_without_entities(
                thread.post_id, status="failed", reason="comment_conflict"
            )
            return
        if checkpoint.status == "partial" and checkpoint.stop_reason in {
            "cursor_loop",
            "comment_conflict",
        }:
            self._finalize_without_entities(
                thread.post_id,
                status="failed",
                reason=checkpoint.stop_reason,
            )
            return
        if checkpoint.status == "partial" and checkpoint.stop_reason in {
            "budget_exhausted",
            "provider_error",
        }:
            raise _HydrationAbort(checkpoint.stop_reason)
        if (
            checkpoint.status == "partial"
            and checkpoint.stop_reason == "comments_schema_drift"
        ):
            self._finalize_without_entities(
                thread.post_id,
                status="failed",
                reason="comments_schema_drift",
            )
            return

        comments_by_id = {comment.comment_id: comment for comment in comments}
        used_request_cursors = {
            artifact.request_cursor
            for artifact in self.store.load_raw_artifacts(
                run_id=self.run_id,
                lane_type="comments",
                lane_key=thread.post_id,
            )
            if artifact.page_number is not None
            and artifact.page_number <= checkpoint.page_number
            and artifact.request_cursor is not None
        }
        if archived_only and checkpoint.status not in {"complete"} and not (
            checkpoint.status == "partial"
            and checkpoint.stop_reason
            in {"unresolved_more", "post_only_coverage"}
        ):
            return
        while checkpoint.status not in {"complete"} and not (
            checkpoint.status == "partial"
            and checkpoint.stop_reason
            in {"unresolved_more", "post_only_coverage"}
        ):
            request_cursor = checkpoint.cursor
            page_number = checkpoint.page_number + 1
            params = {
                "post_id": f"t3_{thread.post_id}",
                "sort_type": "CONFIDENCE",
                "after": request_cursor or "",
                "need_format": "false",
            }
            try:
                payload = self.executor.get_json(FETCH_POST_COMMENTS, params)
            except ProviderBudgetExhausted:
                self.store.save_checkpoint(
                    self._comment_failure_checkpoint(
                        checkpoint,
                        reason="budget_exhausted",
                        last_error="ProviderBudgetExhausted",
                    )
                )
                raise _HydrationAbort("budget_exhausted") from None
            except TikHubProviderError as exc:
                self.store.save_checkpoint(
                    self._comment_failure_checkpoint(
                        checkpoint,
                        reason="provider_error",
                        last_error=exc.error_class,
                    )
                )
                raise _HydrationAbort("provider_error") from None

            try:
                payload_bytes = _canonical_json_bytes(payload)
            except TikHubSchemaDrift:
                self.store.save_checkpoint(
                    self._comment_failure_checkpoint(
                        checkpoint,
                        reason="comments_schema_drift",
                        last_error="TikHubSchemaDrift",
                    )
                )
                self._finalize_without_entities(
                    thread.post_id,
                    status="failed",
                    reason="comments_schema_drift",
                )
                return
            capture, artifact = self._write_comment_archive(
                post_id=thread.post_id,
                page_number=page_number,
                request_cursor=request_cursor,
                payload_bytes=payload_bytes,
            )
            artifact = self.store.persist_raw_capture_artifact(capture, artifact)
            try:
                page_comments, page_more, next_cursor = self._parse_comment_payload(
                    payload=payload,
                    artifact=artifact,
                    thread=thread,
                    submitter_name=submitter_name,
                    cursor_contract=cursor_contract,
                )
            except TikHubSchemaDrift:
                self.store.save_checkpoint(
                    self._comment_failure_checkpoint(
                        checkpoint,
                        reason="comments_schema_drift",
                        last_error="TikHubSchemaDrift",
                    )
                )
                self._finalize_without_entities(
                    thread.post_id,
                    status="failed",
                    reason="comments_schema_drift",
                )
                return

            artifact = self.store.complete_raw_artifact_response_cursor(
                run_id=self.run_id,
                artifact_id=artifact.artifact_id,
                response_cursor=next_cursor,
            )
            captures[capture.raw_capture_id] = capture
            page_conflict = self._merge_comments(comments_by_id, page_comments)
            more_node_count += page_more
            used_request_cursors.add(request_cursor) if request_cursor else None
            checkpoint = self._checkpoint_after_comment_page(
                checkpoint=checkpoint,
                artifact=artifact,
                occurrence_count=len(page_comments),
                unique_count=len(comments_by_id),
                next_cursor=next_cursor,
                cursor_loop=(
                    next_cursor is not None
                    and next_cursor in used_request_cursors
                ),
                conflict=page_conflict,
            )
            self.store.save_checkpoint(checkpoint)
            if page_conflict:
                self._finalize_without_entities(
                    thread.post_id, status="failed", reason="comment_conflict"
                )
                return
            if checkpoint.stop_reason == "cursor_loop":
                self._finalize_without_entities(
                    thread.post_id, status="failed", reason="cursor_loop"
                )
                return

        self._finalize_relevant_candidate(
            thread=thread,
            detail_capture=detail_capture,
            checkpoint=checkpoint,
            comments=tuple(comments_by_id.values()),
            comment_captures=captures,
            more_node_count=more_node_count,
        )

    def _comment_checkpoint(
        self, post_id: str, cursor_contract: CursorContract
    ) -> BackfillCheckpoint:
        cursor_path_json = json.dumps(
            list(cursor_contract.cursor_path),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        checkpoint = self.store.load_checkpoint(
            run_id=self.run_id, lane_type="comments", lane_key=post_id
        )
        if checkpoint is None:
            checkpoint = BackfillCheckpoint(
                run_id=self.run_id,
                lane_type="comments",
                lane_key=post_id,
                cursor=None,
                previous_cursor=None,
                page_number=0,
                newest_seen_utc=None,
                oldest_seen_utc=None,
                discovered_count=0,
                unique_count=0,
                provider_request_count=self.store.provider_request_count(self.run_id),
                last_success_utc=None,
                last_error=None,
                status="prepared",
                stop_reason=None,
                cursor_json_path=cursor_path_json,
                cursor_schema_sha256=cursor_contract.schema_sha256,
                consecutive_old_pages=0,
            )
            self.store.save_checkpoint(checkpoint)
            return checkpoint
        if (
            checkpoint.cursor_json_path != cursor_path_json
            or checkpoint.cursor_schema_sha256 != cursor_contract.schema_sha256
        ):
            raise BackfillConflictError(
                f"backfill_checkpoints:{self.run_id}/comments/{post_id}"
            )
        return checkpoint

    def _restore_comment_chain(
        self,
        *,
        thread: RedditThread,
        submitter_name: str,
        checkpoint: BackfillCheckpoint,
        cursor_contract: CursorContract,
    ) -> tuple[
        BackfillCheckpoint,
        list[RedditComment],
        dict[str, RawCapture],
        int,
        bool,
    ]:
        artifacts = self.store.load_raw_artifacts(
            run_id=self.run_id,
            lane_type="comments",
            lane_key=thread.post_id,
        )
        by_page: dict[int, list[RawArtifactMetadata]] = {}
        for artifact in artifacts:
            if artifact.page_number is None or artifact.page_number < 1:
                raise BackfillConflictError(
                    f"backfill_raw_artifacts:{self.run_id}/{artifact.artifact_id}"
                )
            by_page.setdefault(artifact.page_number, []).append(artifact)
        allowed_pages = set(range(1, checkpoint.page_number + 1))
        if any(len(by_page.get(page, ())) != 1 for page in allowed_pages):
            raise BackfillConflictError(
                f"backfill_checkpoints:{self.run_id}/comments/{thread.post_id}"
            )
        extra_pages = set(by_page) - allowed_pages
        next_page = checkpoint.page_number + 1
        if extra_pages not in (set(), {next_page}) or (
            next_page in by_page and len(by_page[next_page]) != 1
        ):
            raise BackfillConflictError(
                f"backfill_checkpoints:{self.run_id}/comments/{thread.post_id}"
            )

        comments_by_id: dict[str, RedditComment] = {}
        captures: dict[str, RawCapture] = {}
        more_node_count = 0
        occurrence_count = 0
        conflict = False
        previous_response: str | None = None
        last_artifact: RawArtifactMetadata | None = None
        used_request_cursors: set[str] = set()
        for page_number in range(1, checkpoint.page_number + 1):
            artifact = by_page[page_number][0]
            expected_request = None if page_number == 1 else previous_response
            if (
                (page_number > 1 and previous_response is None)
                or artifact.request_cursor != expected_request
            ):
                raise BackfillConflictError(
                    f"backfill_checkpoints:{self.run_id}/comments/{thread.post_id}"
                )
            page_comments, page_more, next_cursor, capture = (
                self._read_comment_artifact(
                    artifact=artifact,
                    thread=thread,
                    submitter_name=submitter_name,
                    cursor_contract=cursor_contract,
                    committed=True,
                )
            )
            if artifact.response_cursor != next_cursor:
                raise BackfillConflictError(
                    f"backfill_raw_artifacts:{self.run_id}/{artifact.artifact_id}"
                )
            occurrence_count += len(page_comments)
            conflict = self._merge_comments(comments_by_id, page_comments) or conflict
            more_node_count += page_more
            captures[capture.raw_capture_id] = capture
            if artifact.request_cursor:
                used_request_cursors.add(artifact.request_cursor)
            previous_response = next_cursor
            last_artifact = artifact

        if checkpoint.page_number == 0:
            if (
                checkpoint.cursor is not None
                or checkpoint.previous_cursor is not None
                or checkpoint.discovered_count != 0
                or checkpoint.unique_count != 0
                or checkpoint.last_success_utc is not None
            ):
                raise BackfillConflictError(
                    f"backfill_checkpoints:{self.run_id}/comments/{thread.post_id}"
                )
        elif (
            last_artifact is None
            or checkpoint.previous_cursor != last_artifact.request_cursor
            or checkpoint.cursor != last_artifact.response_cursor
            or checkpoint.discovered_count != occurrence_count
            or checkpoint.unique_count != len(comments_by_id)
            or checkpoint.last_success_utc != last_artifact.captured_at_utc
        ):
            raise BackfillConflictError(
                f"backfill_checkpoints:{self.run_id}/comments/{thread.post_id}"
            )

        self._validate_comment_checkpoint_state(
            checkpoint, used_request_cursors=used_request_cursors
        )

        if next_page in by_page:
            if checkpoint.status == "complete":
                raise BackfillConflictError(
                    f"backfill_checkpoints:{self.run_id}/comments/{thread.post_id}"
                )
            artifact = by_page[next_page][0]
            if artifact.request_cursor != checkpoint.cursor:
                raise BackfillConflictError(
                    f"backfill_checkpoints:{self.run_id}/comments/{thread.post_id}"
                )
            try:
                page_comments, page_more, next_cursor, capture = (
                    self._read_comment_artifact(
                        artifact=artifact,
                        thread=thread,
                        submitter_name=submitter_name,
                        cursor_contract=cursor_contract,
                        committed=False,
                    )
                )
            except TikHubSchemaDrift:
                self.store.save_checkpoint(
                    self._comment_failure_checkpoint(
                        checkpoint,
                        reason="comments_schema_drift",
                        last_error="TikHubSchemaDrift",
                    )
                )
                raise _HydrationAbort("comments_schema_drift") from None
            if artifact.response_cursor is None:
                artifact = self.store.complete_raw_artifact_response_cursor(
                    run_id=self.run_id,
                    artifact_id=artifact.artifact_id,
                    response_cursor=next_cursor,
                )
            elif artifact.response_cursor != next_cursor:
                raise BackfillConflictError(
                    f"backfill_raw_artifacts:{self.run_id}/{artifact.artifact_id}"
                )
            occurrence_count += len(page_comments)
            page_conflict = self._merge_comments(comments_by_id, page_comments)
            conflict = conflict or page_conflict
            more_node_count += page_more
            captures[capture.raw_capture_id] = capture
            if artifact.request_cursor:
                used_request_cursors.add(artifact.request_cursor)
            checkpoint = self._checkpoint_after_comment_page(
                checkpoint=checkpoint,
                artifact=artifact,
                occurrence_count=len(page_comments),
                unique_count=len(comments_by_id),
                next_cursor=next_cursor,
                cursor_loop=(
                    next_cursor is not None
                    and next_cursor in used_request_cursors
                ),
                conflict=page_conflict,
            )
            self.store.save_checkpoint(checkpoint)
        return (
            checkpoint,
            list(comments_by_id.values()),
            captures,
            more_node_count,
            conflict,
        )

    def _read_comment_artifact(
        self,
        *,
        artifact: RawArtifactMetadata,
        thread: RedditThread,
        submitter_name: str,
        cursor_contract: CursorContract,
        committed: bool,
    ) -> tuple[list[RedditComment], int, str | None, RawCapture]:
        expected_source_url = _hashed_tikhub_source_url(
            run_id=self.run_id,
            lane_type="comments",
            lane_key=thread.post_id,
            endpoint=FETCH_POST_COMMENTS,
            page_number=artifact.page_number or 0,
            request_cursor=artifact.request_cursor,
        )
        expected_capture_id = make_raw_capture_id(
            run_id=self.run_id,
            source_method="tikhub_comments",
            source_url=expected_source_url,
            payload_sha256=artifact.payload_sha256,
        )
        if (
            artifact.run_id != self.run_id
            or artifact.artifact_kind != "comments"
            or artifact.lane_type != "comments"
            or artifact.lane_key_hash != sha256(thread.post_id.encode()).hexdigest()
            or artifact.parser_kind != "tikhub_comments"
            or artifact.source_method != "tikhub_comments"
            or artifact.source_url != expected_source_url
            or artifact.identity_hash
            != sha256(expected_source_url.removeprefix("tikhub://").encode()).hexdigest()
            or artifact.raw_capture_id != expected_capture_id
            or artifact.source_endpoint != FETCH_POST_COMMENTS
        ):
            raise BackfillConflictError(
                f"backfill_raw_artifacts:{self.run_id}/{artifact.artifact_id}"
            )
        capture = self._capture_from_artifact(artifact)
        payload_bytes = self.archive.read_verified(artifact)
        payload = self._decode_archived_json(payload_bytes, artifact)
        try:
            comments, more_count, next_cursor = self._parse_comment_payload(
                payload=payload,
                artifact=artifact,
                thread=thread,
                submitter_name=submitter_name,
                cursor_contract=cursor_contract,
            )
        except TikHubSchemaDrift:
            if not committed:
                raise
            raise BackfillConflictError(
                f"backfill_raw_artifacts:{self.run_id}/{artifact.artifact_id}"
            ) from None
        return comments, more_count, next_cursor, capture

    def _validate_comment_checkpoint_state(
        self,
        checkpoint: BackfillCheckpoint,
        *,
        used_request_cursors: set[str],
    ) -> None:
        invalid = False
        if checkpoint.status == "prepared":
            invalid = checkpoint.page_number != 0 or checkpoint.stop_reason is not None
        elif checkpoint.status == "running":
            invalid = (
                checkpoint.page_number == 0
                or checkpoint.cursor is None
                or checkpoint.cursor in used_request_cursors
            )
        elif checkpoint.status == "complete":
            invalid = (
                checkpoint.stop_reason != "cursor_exhausted"
                or checkpoint.cursor is not None
            )
        elif checkpoint.status == "partial":
            if checkpoint.stop_reason in {"unresolved_more", "post_only_coverage"}:
                invalid = checkpoint.cursor is not None
            elif checkpoint.stop_reason == "cursor_loop":
                invalid = (
                    checkpoint.cursor is None
                    or checkpoint.cursor not in used_request_cursors
                )
        if invalid:
            raise BackfillConflictError(
                f"backfill_checkpoints:{self.run_id}/comments/{checkpoint.lane_key}"
            )

    def _parse_comment_payload(
        self,
        *,
        payload: Any,
        artifact: RawArtifactMetadata,
        thread: RedditThread,
        submitter_name: str,
        cursor_contract: CursorContract,
    ) -> tuple[list[RedditComment], int, str | None]:
        try:
            comments, more_count = _parse_tikhub_comment_payload(
                payload,
                post_id=thread.post_id,
                run_id=self.run_id,
                raw_capture_id=artifact.raw_capture_id,
                submitter_name=submitter_name,
            )
        except Exception:
            raise TikHubSchemaDrift("comment payload parser failed") from None
        try:
            next_cursor = extract_next_cursor(
                payload,
                cursor_contract,
                allow_terminal_without_cursor=True,
            )
        except TikHubSchemaDrift:
            if not _is_reviewed_incomplete_comment_page(
                payload,
                cursor_contract,
                more_count=more_count,
            ):
                raise
            next_cursor = None
        return comments, more_count, next_cursor

    def _write_comment_archive(
        self,
        *,
        post_id: str,
        page_number: int,
        request_cursor: str | None,
        payload_bytes: bytes,
    ) -> tuple[RawCapture, RawArtifactMetadata]:
        payload_sha256 = sha256(payload_bytes).hexdigest()
        source_url = _hashed_tikhub_source_url(
            run_id=self.run_id,
            lane_type="comments",
            lane_key=post_id,
            endpoint=FETCH_POST_COMMENTS,
            page_number=page_number,
            request_cursor=request_cursor,
        )
        source_method = "tikhub_comments"
        raw_capture_id = make_raw_capture_id(
            run_id=self.run_id,
            source_method=source_method,
            source_url=source_url,
            payload_sha256=payload_sha256,
        )
        captured_at_utc = self._capture_time(
            raw_capture_id=raw_capture_id,
            source_method=source_method,
            source_url=source_url,
            payload_sha256=payload_sha256,
        )
        capture = RawCapture(
            raw_capture_id=raw_capture_id,
            run_id=self.run_id,
            source_method=source_method,
            source_url=source_url,
            captured_at_utc=captured_at_utc,
            auth_boundary="provider_gate",
            raw_payload_hash=f"sha256:{payload_sha256}",
            payload_format="json",
        )
        artifact = self.archive.write(
            run_id=self.run_id,
            artifact_kind="comments",
            lane_type="comments",
            lane_key=post_id,
            identity=source_url.removeprefix("tikhub://"),
            payload=payload_bytes,
            raw_capture_id=raw_capture_id,
            parser_kind="tikhub_comments",
            source_method=source_method,
            source_url=source_url,
            source_endpoint=FETCH_POST_COMMENTS,
            captured_at_utc=captured_at_utc,
            page_number=page_number,
            request_cursor=request_cursor,
            response_cursor=None,
        )
        return capture, artifact

    def _checkpoint_after_comment_page(
        self,
        *,
        checkpoint: BackfillCheckpoint,
        artifact: RawArtifactMetadata,
        occurrence_count: int,
        unique_count: int,
        next_cursor: str | None,
        cursor_loop: bool,
        conflict: bool,
    ) -> BackfillCheckpoint:
        status = "running"
        stop_reason = None
        if conflict:
            status, stop_reason = "partial", "comment_conflict"
        elif cursor_loop:
            status, stop_reason = "partial", "cursor_loop"
        elif next_cursor is None:
            status, stop_reason = "complete", "cursor_exhausted"
        return replace(
            checkpoint,
            cursor=next_cursor,
            previous_cursor=artifact.request_cursor,
            page_number=checkpoint.page_number + 1,
            discovered_count=checkpoint.discovered_count + occurrence_count,
            unique_count=unique_count,
            provider_request_count=self.store.provider_request_count(self.run_id),
            last_success_utc=artifact.captured_at_utc,
            last_error=None,
            status=status,
            stop_reason=stop_reason,
        )

    def _comment_failure_checkpoint(
        self,
        checkpoint: BackfillCheckpoint,
        *,
        reason: str,
        last_error: str,
    ) -> BackfillCheckpoint:
        return replace(
            checkpoint,
            provider_request_count=self.store.provider_request_count(self.run_id),
            last_error=last_error,
            status="partial",
            stop_reason=reason,
        )

    @staticmethod
    def _merge_comments(
        comments_by_id: dict[str, RedditComment],
        page_comments: Sequence[RedditComment],
    ) -> bool:
        conflict = False
        for comment in page_comments:
            existing = comments_by_id.get(comment.comment_id)
            if existing is None:
                comments_by_id[comment.comment_id] = comment
            elif TikHubDetailHydrator._comment_semantic_key(
                existing
            ) != TikHubDetailHydrator._comment_semantic_key(comment):
                conflict = True
        return conflict

    @staticmethod
    def _comment_semantic_key(comment: RedditComment) -> tuple[object, ...]:
        return (
            comment.body,
            comment.post_id,
            comment.parent_id,
            comment.created_at_utc,
            comment.score,
            comment.depth,
            comment.is_submitter,
            comment.author_hash,
            comment.deleted_or_removed,
            tuple(comment.matched_keywords),
        )

    def _finalize_relevant_candidate(
        self,
        *,
        thread: RedditThread,
        detail_capture: RawCapture,
        checkpoint: BackfillCheckpoint,
        comments: tuple[RedditComment, ...],
        comment_captures: dict[str, RawCapture],
        more_node_count: int,
    ) -> None:
        combined_text = "\n".join(
            (thread.title, thread.selftext, *(comment.body for comment in comments))
        )
        combined_analysis = analyze_text(combined_text)
        if not combined_analysis.keyword_match.is_relevant:
            self._finalize_without_entities(
                thread.post_id, status="excluded", reason=None
            )
            return
        coverage_grade = BrowserJsonAdapter._coverage_grade(
            parsed_comment_count=len(comments),
            more_node_count=more_node_count,
            reported_count=thread.num_comments_reported,
        )
        status_reason = None
        if more_node_count:
            status_reason = "unresolved_more"
        elif coverage_grade == "post_only":
            status_reason = "post_only_coverage"
        if status_reason is not None:
            checkpoint = replace(
                checkpoint, status="partial", stop_reason=status_reason
            )
            self.store.save_checkpoint(checkpoint)
        final_thread = replace(
            thread,
            parsed_comment_count=len(comments),
            more_node_count=more_node_count,
            coverage_grade=coverage_grade,
            matched_keywords=combined_analysis.keyword_match.matched_terms,
        )
        required_captures = {detail_capture.raw_capture_id: detail_capture}
        for comment in comments:
            capture = comment_captures.get(comment.raw_capture_id)
            if capture is None:
                raise BackfillConflictError(
                    f"raw_captures:{comment.raw_capture_id}"
                )
            required_captures.setdefault(capture.raw_capture_id, capture)
        analyses = (
            _analysis_row(
                analysis_id=f"analysis_post_{thread.post_id}",
                run_id=self.run_id,
                source_type="post",
                source_id=thread.post_id,
                text=f"{thread.title}\n{thread.selftext}",
            ),
            *(
                _analysis_row(
                    analysis_id=f"analysis_comment_{comment.comment_id}",
                    run_id=self.run_id,
                    source_type="comment",
                    source_id=comment.comment_id,
                    text=comment.body,
                )
                for comment in comments
            ),
        )
        self.store.finalize_candidate(
            run_id=self.run_id,
            post_id=thread.post_id,
            expected_statuses=("pending",),
            status="hydrated",
            status_reason=status_reason,
            updated_at_utc=self.now(),
            captures=tuple(required_captures.values()),
            threads=(final_thread,),
            comments=comments,
            analyses=analyses,
        )

    def _capture_time(
        self,
        *,
        raw_capture_id: str,
        source_method: str,
        source_url: str,
        payload_sha256: str,
    ) -> datetime:
        persisted = self.store.load_raw_capture(raw_capture_id)
        if persisted is None:
            return self.now()
        expected = (
            self.run_id,
            source_method,
            source_url,
            f"sha256:{payload_sha256}",
        )
        actual = (
            persisted.run_id,
            persisted.source_method,
            persisted.source_url,
            persisted.raw_payload_hash,
        )
        if actual != expected:
            raise BackfillConflictError(f"raw_captures:{raw_capture_id}")
        return persisted.captured_at_utc

    def _capture_from_artifact(self, artifact: RawArtifactMetadata) -> RawCapture:
        capture = RawCapture(
            raw_capture_id=artifact.raw_capture_id,
            run_id=artifact.run_id,
            source_method=artifact.source_method,
            source_url=artifact.source_url,
            captured_at_utc=datetime.fromisoformat(artifact.captured_at_utc),
            auth_boundary="provider_gate",
            raw_payload_hash=f"sha256:{artifact.payload_sha256}",
            payload_format="json",
        )
        persisted = self.store.load_raw_capture(capture.raw_capture_id)
        if persisted != capture:
            raise BackfillConflictError(
                f"raw_captures:{capture.raw_capture_id}"
            )
        return capture

    def _result(self) -> LaneResult:
        outcomes = self.store.load_hydration_outcomes(self.run_id)
        states = [(str(row["status"]), row["status_reason"]) for row in outcomes]
        unresolved = any(
            (
                row["status"] == "hydrated"
                and row["status_reason"]
                in {"unresolved_more", "post_only_coverage"}
            )
            or row["checkpoint_status"] == "partial"
            or row["coverage_grade"] in {"partial", "post_only"}
            for row in outcomes
        )
        nonterminal_batch = any(
            batch.status in {"prepared", "raw_persisted"}
            for batch in self.store.load_detail_batches(run_id=self.run_id)
        )
        if states and all(state == ("failed", "provider_error") for state in states):
            status, reason = "failed", "provider_error"
        elif any(state == ("budget_deferred", "budget_exhausted") for state in states):
            status, reason = "partial", "budget_exhausted"
        elif any(state == ("failed", "provider_error") for state in states):
            status, reason = "partial", "provider_error"
        elif any(state[0] == "failed" for state in states):
            status, reason = "partial", "candidate_failures"
        elif unresolved:
            status, reason = "partial", "unresolved_comments"
        elif any(state[0] == "pending" for state in states) or nonterminal_batch:
            status, reason = "partial", "pending_candidates"
        else:
            status, reason = "complete", "hydration_complete"
        counts = self.store.candidate_status_counts(self.run_id)
        return LaneResult(
            run_id=self.run_id,
            lane_type="detail_batch",
            lane_key="hydration",
            status=status,
            stop_reason=reason,
            pages=self.store.raw_artifact_count(
                self.run_id, ("detail_batch", "comments")
            ),
            discovered_occurrences=self.store.discovery_occurrence_total(self.run_id),
            unique_candidates=sum(counts.values()),
            provider_request_count=self.store.provider_request_count(self.run_id),
            provider_call=self.store.provider_call_evidence(self.run_id),
            live_send=False,
        )


def _canonical_json_bytes(payload: Any) -> bytes:
    try:
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise TikHubSchemaDrift("TikHub response is not canonical JSON") from None


def _hashed_tikhub_source_url(
    *,
    run_id: str,
    lane_type: str,
    lane_key: str,
    endpoint: str,
    page_number: int,
    request_cursor: str | None,
) -> str:
    identity = json.dumps(
        [run_id, lane_type, lane_key, endpoint, page_number, request_cursor],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return "tikhub://" + sha256(identity).hexdigest()


def _cumulative_time_bounds(
    checkpoint: BackfillCheckpoint, page_times: list[datetime]
) -> tuple[str | None, str | None]:
    seen = list(page_times)
    if checkpoint.newest_seen_utc is not None:
        seen.append(datetime.fromisoformat(checkpoint.newest_seen_utc))
    if checkpoint.oldest_seen_utc is not None:
        seen.append(datetime.fromisoformat(checkpoint.oldest_seen_utc))
    if not seen:
        return None, None
    return max(seen).isoformat(), min(seen).isoformat()


def _collect_cursor_candidates(
    value: Any,
    path: tuple[str | int, ...],
    candidates: list[tuple[tuple[str | int, ...], dict[str, Any]]],
) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = (*path, key)
            if key == "pageInfo" and isinstance(child, dict):
                for cursor_key in _CURSOR_KEYS:
                    cursor = child.get(cursor_key)
                    if isinstance(cursor, str) and cursor:
                        candidates.append(((*child_path, cursor_key), child))
            _collect_cursor_candidates(child, child_path, candidates)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _collect_cursor_candidates(child, (*path, index), candidates)


def _value_at_path(value: Any, path: tuple[str | int, ...]) -> Any:
    current = value
    for component in path:
        if isinstance(component, str):
            if not isinstance(current, dict) or component not in current:
                raise TikHubSchemaDrift("TikHub cursor path is missing")
            current = current[component]
        else:
            if (
                not isinstance(current, list)
                or component < 0
                or component >= len(current)
            ):
                raise TikHubSchemaDrift("TikHub cursor path is missing")
            current = current[component]
    return current


def _page_info_schema_sha256(page_info: dict[str, Any]) -> str:
    shape = _type_shape(page_info, page_info_container=True)
    canonical = json.dumps(
        shape, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256(canonical).hexdigest()


def _type_shape(value: Any, *, page_info_container: bool = False) -> Any:
    if isinstance(value, dict):
        return {
            "type": "object",
            "properties": {
                key: (
                    "cursor"
                    if page_info_container
                    and key in _CURSOR_KEYS
                    and (value[key] is None or isinstance(value[key], str))
                    else _type_shape(value[key])
                )
                for key in sorted(value)
            },
        }
    if isinstance(value, list):
        return {"type": "array", "items": [_type_shape(item) for item in value]}
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    return type(value).__name__


def _retryable_http_status(status: int) -> bool:
    return status == 429 or 500 <= status <= 599
