# Momcozy Reddit Historical Backfill Implementation Plan

> **Current-state note (2026-07-14):** 本文件保留 V1 实施与 Task 1–37
> 历史证据。最新完成矩阵、标签字典审计、V2 搜索候选与 Task 38–后续 TODO
> 以 [`docs/workflows/momcozy-reddit-history-coverage-v2.md`](../../workflows/momcozy-reddit-history-coverage-v2.md)
> 为当前入口；不得仅凭本文件早期未同步的 checkbox 判断真实状态。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and run a collect-only, resumable Momcozy Reddit historical backfill for Beijing-time posts from 2025-01-01 through 2026-07-11, first in an isolated SQLite database, without DingTalk delivery or unreviewed production writes.

**Architecture:** Add a separate `reddit_voc.backfill_cli` path that cannot import report or send modules. Import the known historical Reddit JSON seed into an append-safe staging store, archive raw bytes privately, then use budgeted TikHub cursor pagination for discovery, detail, and comments. Validate and replay staging before producing an insert-only production merge plan; production merge remains independently authorized.

**Tech Stack:** Python 3.11+, stdlib `argparse`, `dataclasses`, `datetime`, `gzip`, `hashlib`, `json`, `pathlib`, `sqlite3`, existing `urllib` TikHub client, existing `unittest`, and no new dependency.

## Global Constraints

- Beijing interval: `[2025-01-01T00:00:00+08:00, 2026-07-12T00:00:00+08:00)`; UTC requested interval: `[2024-12-31T16:00:00Z, 2026-07-11T16:00:00Z)`.
- The first run uses an explicit effective end no later than its start time. A later July 11 catch-up uses a new run.
- Preserve current `match_keywords` behavior and current TikHub search terms. Do not add competitor-only searches.
- Filter by post creation time, not comment creation time.
- Dynamic search uses `search_type=post`, `sort=NEW`, `time_range=all`, `after`, `need_format=false`.
- Subreddit feed and comments paginate with `after`. Detail batches contain at most 30 post IDs.
- Contract probe is hard-capped at four outbound attempts including retries.
- Each outbound attempt, including retry, atomically reserves one request before sending.
- Provider authorization is explicit: CLI flag + `REDDIT_VOC_BACKFILL_AUTHORIZE_PROVIDER_CALL=1` + `REDDIT_VOC_ENABLE_TIKHUB=1` + key. Phase names never imply authorization.
- Network/429/5xx retries wait 2, 4, and 8 seconds. HTTP 401/403/422 do not retry.
- Raw payloads are private deterministic gzip files with SHA-256 metadata. Never archive headers, API keys, env files, or webhooks.
- Staging uses one umbrella run and append-safe inserts. Exact replay may no-op; conflicting lineage fails.
- Production merge is insert-only. If a post exists in production, that post and all staging comments/analyses attached to it are conflict-skipped.
- Probe recommendations are never approvals. Full collection requires owner-supplied cumulative budget, subreddit decision, and reviewed probe SHA-256.
- `server_daily_cycle.sh`, report/translation/send commands, and `DINGTALK_*` are forbidden.
- Every summary contains `live_send=false`. `provider_call=true` appears only after a real TikHub attempt is reserved and sent.
- Do not commit unless the owner separately authorizes it; use diff/status checkpoints.
- Local verification interpreter:
  `/Users/pray/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3`.

---

## File Map

Create a dedicated staging base schema compatible with production columns, rather than calling `VocStore.migrate()`. Its `raw_captures` uniqueness is `UNIQUE(run_id, source_method, source_url, raw_payload_hash)`, so two runs may preserve independent raw lineage. Create the standard `runs`, `raw_captures`, `reddit_threads`, `reddit_comments`, `analysis_results`, and `delivery_previews` tables plus:

- `src/reddit_voc/search_config.py` — neutral TikHub search terms.
- `src/reddit_voc/backfill_models.py` — immutable manifests, checkpoints, artifacts, analyses, summaries.
- `src/reddit_voc/backfill_storage.py` — append-safe staging schema, budgets, attempt/occurrence ledgers, checkpoints, candidates, issues.
- `src/reddit_voc/backfill_archive.py` — deterministic private gzip archive.
- `src/reddit_voc/backfill_seed.py` — strict historical JSON importer.
- `src/reddit_voc/backfill_provider.py` — cursor discovery, budgeted retries, hydration.
- `src/reddit_voc/backfill_validation.py` — integrity, replay, terminal-lane acceptance.
- `src/reddit_voc/backfill_merge.py` — read-only merge plan and gated insert-only merge.
- `src/reddit_voc/backfill_cli.py` — isolated CLI.
- `scripts/run_historical_backfill.sh` and `scripts/server_historical_backfill.sh`.
- Nine corresponding `tests/test_backfill_*.py` modules.

Modify:

- `src/reddit_voc/keywords.py` — runtime rule snapshot/hash.
- `src/reddit_voc/time_window.py` — historical natural-day helper.
- `src/reddit_voc/cli.py` — import neutral search terms only.
- `pyproject.toml` — backfill entry point.
- `README.md`, `.codex/context-pack.md`, `.codex/session-thread.md`, and `.kiro/plan/*.md`.

### Task 1: Freeze Window, Search, and Keyword Contracts

**Files:**
- Create: `src/reddit_voc/search_config.py`
- Modify: `src/reddit_voc/keywords.py:1-268`
- Modify: `src/reddit_voc/time_window.py:1-74`
- Modify: `src/reddit_voc/cli.py:14-42`
- Test: `tests/test_backfill_contract.py`
- Modify test: `tests/test_time_window.py`
- Regression: `tests/test_tikhub_collector.py`

**Interfaces:**
- Produces: `DEFAULT_TIKHUB_SEARCH_TERMS: Sequence[str]` backed by an immutable tuple.
- Produces: `keyword_rules_snapshot() -> dict[str, object]`.
- Produces: `keyword_rules_sha256() -> str`.
- Produces: `historical_natural_day_window(*, start_date: date, end_date_inclusive: date, effective_end_utc: datetime | None = None, timezone_name: str = "Asia/Shanghai") -> CollectionWindow`.

- [x] **Step 1: Write failing contract tests**

```python
from datetime import date, datetime, timezone
import unittest

from reddit_voc.keywords import keyword_rules_sha256, keyword_rules_snapshot
from reddit_voc.search_config import DEFAULT_TIKHUB_SEARCH_TERMS
from reddit_voc.time_window import historical_natural_day_window


class BackfillContractTests(unittest.TestCase):
    def test_window_is_beijing_left_closed_right_open(self):
        window = historical_natural_day_window(
            start_date=date(2025, 1, 1),
            end_date_inclusive=date(2026, 7, 11),
            effective_end_utc=datetime(2026, 7, 11, 4, 17, 9, tzinfo=timezone.utc),
        )
        self.assertEqual(window.start_utc.isoformat(), "2024-12-31T16:00:00+00:00")
        self.assertEqual(window.end_utc.isoformat(), "2026-07-11T04:17:09+00:00")
        self.assertTrue(window.contains_utc(window.start_utc))
        self.assertFalse(window.contains_utc(window.end_utc))

    def test_effective_end_cannot_exceed_requested_end(self):
        with self.assertRaisesRegex(ValueError, "effective_end_utc exceeds requested end"):
            historical_natural_day_window(
                start_date=date(2025, 1, 1),
                end_date_inclusive=date(2026, 7, 11),
                effective_end_utc=datetime(2026, 7, 12, tzinfo=timezone.utc),
            )

    def test_runtime_rules_have_a_stable_hash(self):
        self.assertEqual(keyword_rules_snapshot()["brands"]["Momcozy"][0], "momcozy")
        self.assertIn('"wearable pump"', DEFAULT_TIKHUB_SEARCH_TERMS)
        self.assertEqual(len(keyword_rules_sha256()), 64)
```

- [x] **Step 2: Run and verify the missing interfaces**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. \
/Users/pray/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
-m unittest tests.test_backfill_contract tests.test_time_window -v
```

Expected: FAIL importing the new module/functions.

- [x] **Step 3: Implement the neutral search configuration**

Move the exact existing 15 terms from `cli.py`:

```python
DEFAULT_TIKHUB_SEARCH_TERMS = (
    "Momcozy", "momcozy", '"Momcozy"', '"momcozy"', '"mom cozy"',
    '"Momcozy M5"', '"Momcozy S12"', '"Momcozy M9"',
    '"Momcozy KleanPal"', '"Momcozy bottle washer"',
    '"Momcozy baby carrier"', '"Momcozy PureHug"',
    '"wearable pump"', '"breast pump"', '"bottle washer"',
)
```

Add canonical JSON hashing to `keywords.py`:

```python
import hashlib
import json


def keyword_rules_snapshot() -> dict[str, object]:
    return {
        "brands": DEFAULT_BRANDS,
        "products": DEFAULT_PRODUCTS,
        "category": DEFAULT_CATEGORY,
        "contextual_category": DEFAULT_CONTEXTUAL_CATEGORY,
        "competitors": DEFAULT_COMPETITORS,
        "excludes": DEFAULT_EXCLUDES,
        "model_context": MODEL_CONTEXT,
    }


def keyword_rules_sha256() -> str:
    payload = json.dumps(
        keyword_rules_snapshot(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
```

Add the historical helper to `time_window.py`:

```python
def historical_natural_day_window(
    *,
    start_date: date,
    end_date_inclusive: date,
    effective_end_utc: datetime | None = None,
    timezone_name: str = "Asia/Shanghai",
) -> CollectionWindow:
    if end_date_inclusive < start_date:
        raise ValueError("end_date_inclusive precedes start_date")
    tz = ZoneInfo(timezone_name)
    start_local = datetime.combine(start_date, time.min, tzinfo=tz)
    requested_end_local = datetime.combine(
        end_date_inclusive + timedelta(days=1), time.min, tzinfo=tz
    )
    requested_end_utc = requested_end_local.astimezone(timezone.utc)
    if effective_end_utc is None:
        effective_end_utc = min(datetime.now(timezone.utc), requested_end_utc)
    elif effective_end_utc.tzinfo is None:
        raise ValueError("effective_end_utc must be timezone-aware")
    else:
        effective_end_utc = effective_end_utc.astimezone(timezone.utc)
    if effective_end_utc > requested_end_utc:
        raise ValueError("effective_end_utc exceeds requested end")
    start_utc = start_local.astimezone(timezone.utc)
    if effective_end_utc <= start_utc:
        raise ValueError("effective_end_utc must be after window start")
    end_local = effective_end_utc.astimezone(tz)
    return CollectionWindow(
        timezone_name=timezone_name,
        run_at_local=end_local,
        start_local=start_local,
        end_local=end_local,
        start_utc=start_utc,
        end_utc=effective_end_utc,
    )
```

- [x] **Step 4: Run contract and daily regressions**

Run Step 2, then:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. \
/Users/pray/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
-m unittest tests.test_tikhub_collector -v
```

Expected: PASS; daily term order unchanged.

- [x] **Step 5: No-commit checkpoint**

Because this repository has no `HEAD`, run `git diff --no-index --check /dev/null PATH` for every new path listed under the current task (exit `1` with no diagnostics means only that content differs from `/dev/null`), then `git status --short`. Do not treat an empty ordinary diff as evidence for untracked files.

### Task 2: Add Immutable Backfill Records and Staging Schema

**Files:**
- Create: `src/reddit_voc/backfill_models.py`
- Create: `src/reddit_voc/backfill_storage.py`
- Test: `tests/test_backfill_storage.py`

**Interfaces:**
- Produces: `BackfillManifest`, `BackfillCheckpoint`, `RawArtifactMetadata`, `ProviderAttempt`, `AnalysisRow`, `InsertCounts`.
- Produces: `BackfillStore.migrate()` and atomic `reserve_provider_request()`.

- [x] **Step 1: Write failing budget/checkpoint tests**

```python
def test_request_budget_counts_each_reservation(self):
    store.create_manifest(make_manifest(max_provider_requests=2))
    self.assertEqual(store.reserve_provider_request("backfill_test", "/search", NOW), 1)
    self.assertEqual(store.reserve_provider_request("backfill_test", "/search", NOW), 2)
    self.assertIsNone(store.reserve_provider_request("backfill_test", "/search", NOW))
    self.assertEqual(store.provider_request_count("backfill_test"), 2)


def test_checkpoint_round_trip_preserves_next_cursor(self):
    checkpoint = make_checkpoint(cursor="cursor-2", page_number=1)
    store.save_checkpoint(checkpoint)
    self.assertEqual(
        store.load_checkpoint(
            run_id="backfill_test", lane_type="dynamic_search", lane_key="Momcozy"
        ),
        checkpoint,
    )
```

- [x] **Step 2: Run and confirm missing modules**

Run the global local-verification interpreter with `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. -m unittest tests.test_backfill_storage -v`. Expected: import failure.

- [x] **Step 3: Implement frozen records with exact status vocabularies**

```python
BackfillStatus = Literal[
    "prepared", "seed_complete", "running", "partial", "success", "blocked", "failed"
]
LaneType = Literal["dynamic_search", "subreddit_feed", "detail_batch", "comments"]
ArtifactLaneType = Literal[
    "seed", "dynamic_search", "subreddit_feed", "detail_batch", "comments"
]
LaneStatus = Literal["prepared", "running", "partial", "complete", "failed"]
ProviderAttemptStatus = Literal["reserved", "sent", "succeeded", "failed"]

@dataclass(frozen=True)
class BackfillManifest:
    run_id: str
    status: BackfillStatus
    window_start_utc: str
    requested_end_utc: str
    effective_end_utc: str
    search_terms: Sequence[str]
    subreddits: Sequence[str]
    include_subreddit_sweep: bool
    required_lanes_sha256: str
    keyword_config_sha256: str
    max_provider_requests: int
    provider_request_count: int
    provider_call: bool
    live_send: bool
    created_at_utc: str
    updated_at_utc: str
```

The test module must construct full records with these exact helpers so production models do not expose test-only factories:

```python
def make_manifest(*, max_provider_requests: int) -> BackfillManifest:
    return BackfillManifest(
        run_id="backfill_test",
        status="prepared",
        window_start_utc="2024-12-31T16:00:00+00:00",
        requested_end_utc="2026-07-11T16:00:00+00:00",
        effective_end_utc="2026-07-11T04:17:09+00:00",
        search_terms=("Momcozy",),
        subreddits=("ExclusivelyPumping",),
        include_subreddit_sweep=False,
        required_lanes_sha256="1" * 64,
        keyword_config_sha256="0" * 64,
        max_provider_requests=max_provider_requests,
        provider_request_count=0,
        provider_call=False,
        live_send=False,
        created_at_utc=NOW.isoformat(),
        updated_at_utc=NOW.isoformat(),
    )


def make_checkpoint(*, cursor: str | None, page_number: int) -> BackfillCheckpoint:
    return BackfillCheckpoint(
        run_id="backfill_test",
        lane_type="dynamic_search",
        lane_key="Momcozy",
        cursor=cursor,
        previous_cursor=None,
        page_number=page_number,
        newest_seen_utc=None,
        oldest_seen_utc=None,
        discovered_count=0,
        unique_count=0,
        provider_request_count=0,
        last_success_utc=None,
        last_error=None,
        status="running",
        stop_reason=None,
        cursor_json_path=None,
        cursor_schema_sha256=None,
    )
```

`BackfillCheckpoint` must carry lane/key, current/previous cursor, page number, oldest/newest times, discovered/unique counts, request count, last success/error, status, stop reason, cursor JSON path, and cursor schema SHA-256.

`RawArtifactMetadata` must carry: `artifact_id`, `run_id`, `artifact_kind`, `lane_type: ArtifactLaneType`, `lane_key_hash`, `identity_hash`, `raw_capture_id`, `parser_kind`, `source_method`, `source_url`, `source_endpoint`, `payload_sha256`, `relative_path`, `captured_at_utc`, `page_number`, `request_cursor`, and `response_cursor`. It never carries headers or credentials.

Use exact persisted record fields:

```python
@dataclass(frozen=True)
class AnalysisRow:
    analysis_id: str
    run_id: str
    source_type: Literal["post", "comment"]
    source_id: str
    analysis_version: str
    sentiment_label: str
    sentiment_score: float
    topic: str
    severity: str
    confidence: float
    pain_points: tuple[str, ...]
    provider_call: bool = False


@dataclass(frozen=True)
class InsertCounts:
    raw_captures: int = 0
    threads: int = 0
    comments: int = 0
    analyses: int = 0


@dataclass(frozen=True)
class ProviderAttempt:
    run_id: str
    request_number: int
    endpoint: str
    status: ProviderAttemptStatus
    reserved_at_utc: str
    sent_at_utc: str | None = None
    completed_at_utc: str | None = None
    http_status: int | None = None
    error_class: str | None = None
```

`AnalysisRow` serializes `pain_points` to canonical JSON only at the SQLite boundary. Task 2 adds no standalone entity-insert public API; the two-run raw uniqueness test may use parameterized SQL through `store.connect()`. Task 3 owns `insert_entity_bundle()` and conflict behavior.

- [x] **Step 4: Implement backfill tables**

Create:

- `backfill_manifests` with `live_send CHECK(live_send=0)` and request budget/count.
- `backfill_seed_files` with one outcome per input file.
- `backfill_raw_artifacts` with unique relative path and SHA-256.
- `backfill_provider_attempts` keyed by run/request number with `reserved_at_utc`, `sent_at_utc`, `completed_at_utc`, endpoint, status, and sanitized error class.
- `backfill_checkpoints` keyed by run/lane/key.
- `backfill_candidates` keyed by run/post.
- `backfill_discovery_occurrences` keyed by run/lane/key/page/ordinal, carrying post ID, raw artifact ID, and one disposition from `new_candidate`, `duplicate_occurrence`, `outside_window`, `duplicate_existing_structured`, or `invalid`.
- `backfill_issues` with fatal flag.
- `backfill_merge_conflicts` keyed by merge/entity.

`BackfillStore.migrate()` executes only the dedicated staging schema. `create_manifest()` atomically inserts both `backfill_manifests` and the compatible `runs` row (`window_end_utc=effective_end_utc`); it never accepts `provider_call=true` before sent-attempt evidence. `mark_provider_attempt_sent()` updates both denormalized provider flags in the same transaction. Add a two-run test that imports the same source URL/payload into both runs with different `raw_capture_id` values and preserves both records.

- [x] **Step 5: Implement atomic request reservation**

```python
def reserve_provider_request(
    self, run_id: str, endpoint: str, reserved_at_utc: datetime
) -> int | None:
    with self.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT max_provider_requests, provider_request_count "
            "FROM backfill_manifests WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown backfill run: {run_id}")
        if int(row["provider_request_count"]) >= int(row["max_provider_requests"]):
            return None
        next_count = int(row["provider_request_count"]) + 1
        conn.execute(
            "INSERT INTO backfill_provider_attempts("
            "run_id, request_number, endpoint, status, reserved_at_utc"
            ") VALUES (?, ?, ?, 'reserved', ?)",
            (run_id, next_count, endpoint, reserved_at_utc.isoformat()),
        )
        conn.execute(
            "UPDATE backfill_manifests SET provider_request_count=?, updated_at_utc=? "
            "WHERE run_id=?",
            (next_count, reserved_at_utc.isoformat(), run_id),
        )
        return next_count
```

Add exact transitions:

```python
def mark_provider_attempt_sent(
    self, run_id: str, request_number: int, sent_at_utc: datetime
) -> None:
    """Atomically transition reserved -> sent and set manifest provider_call=1."""


def complete_provider_attempt(
    self,
    run_id: str,
    request_number: int,
    *,
    status: Literal["succeeded", "failed"],
    completed_at_utc: datetime,
    http_status: int | None = None,
    error_class: str | None = None,
) -> None:
    """Atomically transition sent -> succeeded|failed."""
```

Any missing/out-of-order transition raises `ValueError`. `error_class` is either null or a sanitized Python exception class name matching `[A-Za-z_][A-Za-z0-9_]{0,127}`; never persist exception messages, URLs with query strings, response bodies, or headers. Derive `provider_call` from at least one attempt with non-null `sent_at_utc`; `mark_provider_attempt_sent()` updates the manifest's denormalized flag from that evidence. An orphan `reserved` row consumes budget but does not claim a Provider call.

- [x] **Step 6: Run storage tests and diff check**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. \
/Users/pray/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
-m unittest tests.test_backfill_storage -v
```

Expected: PASS; no whitespace errors.

### Task 3: Make Entity Ingestion Append-Safe

**Files:**
- Modify: `src/reddit_voc/backfill_storage.py`
- Modify test: `tests/test_backfill_storage.py`

**Interfaces:**
- Produces: `BackfillConflictError`.
- Produces: `insert_entity_bundle(*, captures: Sequence[RawCapture], threads: Sequence[RedditThread], comments: Sequence[RedditComment], analyses: Sequence[AnalysisRow]) -> InsertCounts`.

- [x] **Step 1: Add deterministic replay and conflict tests**

First insert must return inserted counts. Exact replay must return zeros. A different run/raw lineage for an existing entity must raise:

```python
with self.assertRaisesRegex(BackfillConflictError, "reddit_threads:post1"):
    store.insert_entity_bundle(
        captures=[other_capture],
        threads=[replace(thread, run_id="other_run", raw_capture_id="raw_other")],
        comments=[],
        analyses=[],
    )
```

Also prove that identical raw bytes/source imported under two different run IDs create two raw capture rows, while replay within one run no-ops.

- [x] **Step 2: Run and confirm missing bundle insertion**

Run the bundled interpreter from Task 2 against `tests.test_backfill_storage -v`. Expected: `AttributeError` naming `insert_entity_bundle`.

- [x] **Step 3: Implement compare-before-insert in one `BEGIN IMMEDIATE` transaction**

Insert in raw → thread → comment → analysis order inside one transaction. For every raw/thread/comment/analysis primary key:

1. Select the existing row.
2. If absent, plain `INSERT`.
3. If all persisted fields match, no-op.
4. If any field differs, raise `BackfillConflictError`.
5. Never call existing upsert/replace methods from this path.

- [x] **Step 4: Run twice and verify lineage remains stable**

```bash
for pass in 1 2; do
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. \
  /Users/pray/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
  -m unittest tests.test_backfill_storage -v || exit 1
done
```

Expected: both runs PASS, same counts/IDs.

- [x] **Step 5: Diff checkpoint**

Run the no-index whitespace check described in Task 1 for Task 3 paths and inspect only those files.

### Task 4: Archive Raw Payloads Privately

**Files:**
- Create: `src/reddit_voc/backfill_archive.py`
- Modify: `src/reddit_voc/backfill_storage.py`
- Test: `tests/test_backfill_archive.py`
- Modify test: `tests/test_backfill_storage.py`

**Interfaces:**
- Produces: `PrivateRawArchive.write(*, run_id: str, artifact_kind: str, lane_type: str, lane_key: str, identity: str, payload: bytes, raw_capture_id: str, parser_kind: str, source_method: str, source_url: str, source_endpoint: str, captured_at_utc: datetime, page_number: int | None = None, request_cursor: str | None = None, response_cursor: str | None = None) -> RawArtifactMetadata`.
- Produces: `PrivateRawArchive.read_verified(artifact: RawArtifactMetadata) -> bytes`.
- Produces: `BackfillStore.insert_raw_artifact(artifact: RawArtifactMetadata) -> bool` (`True` inserted, exact replay `False`, conflicting metadata raises `BackfillConflictError`).

- [x] **Step 1: Write deterministic/path-escape/tamper tests**

```python
artifact = archive.write(
    run_id="backfill_test",
    artifact_kind="seed",
    lane_type="seed",
    lane_key="existing_json",
    identity="../../author-title",
    payload=b'{"ok":true}',
    raw_capture_id="raw_backfill_test",
    parser_kind="seed_browser_thread",
    source_method="historical_seed",
    source_url="seed://fixture.json",
    source_endpoint="seed_file",
    captured_at_utc=FIXED_NOW,
    page_number=0,
)
self.assertNotIn("author-title", artifact.relative_path)
self.assertEqual(archive.read_verified(artifact), b'{"ok":true}')
path = archive.root / artifact.relative_path
path.write_bytes(path.read_bytes() + b"x")
with self.assertRaises(ArchiveIntegrityError):
    archive.read_verified(artifact)
```

- [x] **Step 2: Run and confirm import failure**

Run the bundled interpreter with `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. -m unittest tests.test_backfill_archive -v`. Expected: missing-module import failure.

- [x] **Step 3: Implement hash-only paths and fixed gzip `mtime=0`**

Use:

```python
lane_hash = sha256(lane_key.encode()).hexdigest()[:16]
identity_hash = sha256(identity.encode()).hexdigest()
payload_sha256 = sha256(payload).hexdigest()
relative = Path(run_id) / artifact_kind / lane_hash / (
    f"page-{page_number or 0:06d}-{identity_hash[:24]}-{payload_sha256[:16]}.json.gz"
)
```

Allow only safe token values for `run_id`/`artifact_kind`/`lane_type`, resolve and verify the path stays under archive root, and ensure root/directories are mode `0700` and final files mode `0600`. Build gzip with an empty embedded filename and fixed `mtime=0`, write a temporary sibling, fsync it, and atomically replace the final path. The caller persists the full returned metadata with `BackfillStore.insert_raw_artifact()` only after the gzip atomically exists. Accept no headers/env in the API. Tests must prove two identical writes have byte-identical gzip content, exact metadata replay no-ops, conflicting artifact metadata fails, and tamper/path escape is detected.

- [x] **Step 4: Run tests and diff check**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. \
/Users/pray/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
-m unittest tests.test_backfill_archive tests.test_backfill_storage -v
```

Expected: PASS; tampering raises `ArchiveIntegrityError`.

### Task 5: Import the Existing Historical JSON Seed

**Files:**
- Create: `src/reddit_voc/backfill_seed.py`
- Modify: `src/reddit_voc/backfill_models.py`
- Modify: `src/reddit_voc/backfill_storage.py`
- Test: `tests/test_backfill_seed.py`
- Modify test: `tests/test_backfill_storage.py`

**Interfaces:**
- Produces: `make_raw_capture_id(*, run_id: str, source_method: str, source_url: str, payload_sha256: str) -> str`.
- Produces: `import_seed_directory(store: BackfillStore, archive: PrivateRawArchive, *, run_id: str, source_dir: Path, window_start_utc: datetime, effective_end_utc: datetime, captured_at_utc: datetime) -> SeedImportSummary`.

Use the exact immutable summary:

```python
@dataclass(frozen=True)
class SeedImportSummary:
    run_id: str
    status: Literal["seed_complete", "failed"]
    files_total: int
    files_imported: int
    files_outside_window: int
    files_excluded: int
    files_duplicate: int
    parse_errors: int
    threads: int
    comments: int
    analyses: int
    coverage_full: int
    coverage_partial: int
    coverage_post_only: int
    provider_call: bool = False
    live_send: bool = False
```

`BackfillStore` adds append-safe seed-ledger methods: `load_seed_file(run_id, input_path_hash) -> dict[str, object] | None`, `record_seed_file(*, run_id, input_path_hash, payload_sha256, outcome, artifact_id, post_id, error_class, processed_at_utc) -> bool`, `seed_file_count(run_id) -> int`, `seed_outcome_counts(run_id) -> dict[str, int]`, and `set_backfill_status(run_id, status, updated_at_utc) -> None` (manifest and `runs` in one transaction). The table stores only `input_path_hash`, never the source filename/path. Exact replay loads an already recorded identical file, verifies its payload hash, retains the original outcome, and makes no new entity/ledger/status-timestamp write; different payload/metadata for the same `(run_id, input_path_hash)` raises `BackfillConflictError`. Because the obsolete `input_path` schema lacks the hashes needed for a safe automatic migration, `migrate()` must detect it before DDL and raise a clear `BackfillSchemaError` instructing use of a fresh isolated staging DB; never silently reuse or guess legacy rows.

- [x] **Step 1: Write failing tests**

Cover in-window, out-of-window, comment-only Momcozy match, malformed JSON, file ledger completeness, comment time not filtered, and exact replay.

```python
summary = import_seed_directory(
    store,
    archive,
    run_id="backfill_test",
    source_dir=source,
    window_start_utc=datetime(2024, 12, 31, 16, tzinfo=timezone.utc),
    effective_end_utc=datetime(2026, 7, 11, 16, tzinfo=timezone.utc),
    captured_at_utc=FIXED_NOW,
)
self.assertEqual(store.seed_file_count("backfill_test"), summary.files_total)
self.assertFalse(summary.provider_call)
self.assertFalse(summary.live_send)
```

- [x] **Step 2: Run and confirm missing importer**

Run the bundled interpreter with `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. -m unittest tests.test_backfill_seed -v`. Expected: missing importer failure.

- [x] **Step 3: Implement file-ledger-first import**

For each sorted regular JSON file confined under `source_dir`:

1. Hash bytes and derive `input_path_hash=sha256(relative_name)` plus a secret-free `seed://<input_path_hash>` source URL. Before archiving, if the deterministic `raw_capture_id` already exists from an interrupted prior attempt, reuse its persisted `captured_at_utc` for the capture and artifact; otherwise use the supplied time. Archive bytes before parsing. Persist the raw capture/artifact even for outside-window, excluded, duplicate, or parse-error files.
2. Build run-scoped capture ID:

```python
value = "\0".join((run_id, source_method, source_url, payload_sha256)).encode()
raw_capture_id = "raw_backfill_" + sha256(value).hexdigest()[:24]
```

3. Parse with `BrowserJsonAdapter.parse_thread_payload`.
4. Apply `start <= created_at < effective_end`.
5. Match `title + selftext + all comment bodies` and use `dataclasses.replace` to store combined terms.
6. Build existing `analysis_post_*` and `analysis_comment_*` IDs with `analyze_text`.
7. If the post ID is already structured from a different seed file, retain raw provenance but record `duplicate` and do not attempt a conflicting entity insert. Otherwise append-safe insert the entity bundle.
8. Record exactly one of `imported`, `outside_window`, `excluded`, `duplicate`, or `parse_error`; store only sanitized exception class names.
9. Any parse failure makes seed status `failed`; otherwise `seed_complete`. Derive summary entity/coverage counts and outcome counts from the database so exact replay returns the identical summary rather than relabeling files as duplicates.

- [x] **Step 4: Run importer and adapter tests**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. \
/Users/pray/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
-m unittest tests.test_backfill_seed tests.test_adapters -v
```

Expected: PASS.

- [x] **Step 5: Diff checkpoint**

### Task 6: Add Budgeted TikHub Cursor Discovery

**Files:**
- Create: `src/reddit_voc/backfill_provider.py`
- Modify: `src/reddit_voc/backfill_models.py`
- Modify: `src/reddit_voc/backfill_storage.py`
- Modify: `src/reddit_voc/tikhub.py`
- Test: `tests/test_backfill_provider.py`
- Modify test: `tests/test_backfill_storage.py`
- Regression: `tests/test_tikhub_collector.py`

**Interfaces:**
- Produces: `CursorContract`, `LaneResult`, `TikHubRequestExecutor`, `TikHubBackfillDiscoverer`.

Use exact public records:

```python
@dataclass(frozen=True)
class CursorContract:
    cursor_path: tuple[str | int, ...]  # full path including cursor key
    schema_sha256: str                 # canonical type-shape of pageInfo container


@dataclass(frozen=True)
class LaneResult:
    run_id: str
    lane_type: Literal["dynamic_search", "subreddit_feed"]
    lane_key: str
    status: Literal["complete", "partial", "failed"]
    stop_reason: str
    pages: int
    discovered_occurrences: int
    unique_candidates: int
    provider_request_count: int
    provider_call: bool
    live_send: bool = False
```

Extend `BackfillCheckpoint` with `consecutive_old_pages: int` and persist it. Add `BackfillStore.record_discovery_occurrence(...) -> DiscoveryDisposition`, `discovery_occurrence_counts(run_id, lane_type, lane_key) -> dict[str, int]`, `candidate_count(run_id) -> int`, and `request_cursor_seen(run_id, lane_type, lane_key_hash, cursor) -> bool`.

`record_discovery_occurrence` takes run/lane/key/page/ordinal, post ID, source URL, post-created time, raw artifact ID, discovery time, and `base_disposition` from `eligible|outside_window|invalid`. In one `BEGIN IMMEDIATE`: exact occurrence replay returns the original disposition; conflicting replay fails; `eligible` becomes `duplicate_existing_structured` if `reddit_threads` already has the global post ID, `duplicate_occurrence` if the run candidate exists, otherwise inserts a `pending` candidate and becomes `new_candidate`; then it inserts the occurrence. Candidate schema stores first lane/key/artifact, public source URL, post-created time, first-discovered time, `status`, `status_reason`, and updated time. Predeclare later statuses `pending|duplicate_existing_structured|hydrated|excluded|outside_window_detail|failed|budget_deferred`.

- [x] **Step 1: Write failing cursor/retry/resume tests**

Use a fake client keyed by `(path, after)`. Cover saved-cursor resume, repeated cursor, two consecutive old pages, cross-page dedupe with one occurrence row per appearance, feed without undocumented `limit`, budget per retry, attempt status transitions, waits `[2,4,8]`, nonretry 401/403/422, and budget exhaustion remaining partial.

- [x] **Step 2: Run and confirm missing provider**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. \
/Users/pray/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
-m unittest tests.test_backfill_provider -v
```

Expected: import failure before implementation.

- [x] **Step 3: Implement unambiguous cursor inference**

`infer_cursor_contract(payload) -> CursorContract` recursively examines only dictionaries stored under a key exactly named `pageInfo`, and only direct keys `endCursor`, `nextCursor`, or `after`. Exactly one nonempty string cursor path succeeds. Zero or multiple paths raises `TikHubSchemaDrift`. Hash the canonical recursive type-shape of the containing `pageInfo` dict (values never enter the schema hash). `extract_next_cursor(payload, contract) -> str | None` requires the same full path and schema; empty string/null is terminal, while missing path, wrong type, or schema mismatch raises `TikHubSchemaDrift`. Persist `cursor_path` as compact JSON and its SHA-256 in the checkpoint; resume reconstructs only from those persisted fields.

- [x] **Step 4: Implement budgeted retries**

`TikHubRequestExecutor(client, store, run_id, sleep, now)` exposes `get_json(path, params)`. For at most four total attempts per logical request: reserve before every attempt, mark it sent immediately before `client.get_json`, then complete it `succeeded` or `failed` using only HTTP status and exception class. Retry only `URLError|TimeoutError|ConnectionError`, HTTP 429, and HTTP 5xx with waits exactly `2,4,8`; all other HTTP 4xx, including 401/403/422, do not retry. Never store response bodies, exception messages, params, or query strings in the attempt ledger. A missing reservation raises `ProviderBudgetExhausted`; the discoverer saves a partial checkpoint. A reserved-only attempt consumes budget but does not make `provider_call=true`.

- [x] **Step 5: Implement discovery lanes with exact params**

```python
dynamic_params = {
    "query": query, "search_type": "post", "sort": "NEW",
    "time_range": "all", "after": checkpoint.cursor or "", "need_format": "false",
}
feed_params = {
    "subreddit_name": subreddit, "sort": "NEW",
    "after": checkpoint.cursor or "", "need_format": "false",
}
```

Archive before parsing. Record every discovery occurrence before deduplication; then commit new candidates before advancing cursor. The occurrence ledger, not the candidate table, must close `discovered = new_candidate + duplicate_occurrence + outside_window + duplicate_existing_structured + invalid`. Empty cursor = `cursor_exhausted`; repeated cursor = `cursor_loop`; two consecutive pages whose newest post predates start = `older_than_window`.

`TikHubBackfillDiscoverer(executor, store, archive, run_id, now)` exposes `run_dynamic_search(query, window, max_pages=None)` and `run_subreddit_feed(subreddit, window, max_pages=None)`. Use the existing TikHub endpoint constants. Modify `_extract_discovery_posts(payload, source_method, *, dedupe=True)` so the daily path retains its current default while backfill calls `dedupe=False` to preserve occurrences.

For each response: canonicalize the returned JSON to bytes, derive the deterministic raw ID, and reuse its already persisted `captured_at_utc` after an interrupted attempt (same run/source/hash), just like seed recovery. Call `archive.write(..., response_cursor=None)` before cursor/post parsing. After parsing, use `dataclasses.replace` to put the next cursor into metadata, then persist the run-scoped `RawCapture` plus artifact metadata before occurrence rows; on parse/schema failure persist the original metadata with null response cursor. Use a secret-free hashed `tikhub://` source URL and store only the endpoint path in attempt metadata. Process occurrence rows in response order; only post timestamps determine outside-window status. Save the checkpoint only after all rows for that page commit. Partial rows from a crash are exact-replayed when the same page is retried.

Page number is completed-page count + 1. Persist cumulative oldest/newest timestamps, occurrence/new-candidate counts, global request count, cursor contract, and `consecutive_old_pages`. Empty next cursor = `complete/cursor_exhausted`; a next cursor already present as any archived request cursor for the same lane = `partial/cursor_loop`; two consecutive pages with a nonempty timestamp set whose newest post is older than `window.start_utc` = `complete/older_than_window`. `max_pages` is only for the later contract probe and returns `partial/probe_page_limit` with the next cursor saved. Budget exhaustion = `partial/budget_exhausted`; schema drift = `partial/schema_drift`; nonretry/exhausted Provider error = `failed/provider_error` before any page, otherwise `partial/provider_error`. Every result derives `provider_call` from sent-attempt evidence and hardcodes `live_send=false`.

- [x] **Step 6: Run provider and daily regressions**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. \
/Users/pray/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
-m unittest tests.test_backfill_provider tests.test_tikhub_collector -v
```

Expected: PASS, no real network.

### Task 7: Hydrate Details and Paginate Comments

**Files:**
- Modify: `src/reddit_voc/backfill_models.py`
- Modify: `src/reddit_voc/backfill_storage.py`
- Modify: `src/reddit_voc/backfill_provider.py`
- Modify test: `tests/test_backfill_storage.py`
- Modify test: `tests/test_backfill_provider.py`

**Supplemental execution contract:** `.superpowers/sdd/task-7-brief.md`. This brief fixes the storage atomicity, comment-page replay, append-only partial-data, and hydration `LaneResult` semantics required to implement the approved design without a crash window.

**Interfaces:**
- Produces: `TikHubDetailHydrator.hydrate(*, post_ids: Sequence[str], window: CollectionWindow, comment_cursor_contract: CursorContract) -> LaneResult`.

- [x] **Step 1: Add failing hydration tests**

Cover 31 IDs -> detail batches 30+1, comments following `after` to empty, comment ID dedupe, out-of-window detail, combined relevance, and unresolved `more` forcing partial.

- [x] **Step 2: Run and confirm hydration failures only**

Run the Task 6 provider test command. Expected: only the new hydration cases fail for missing behavior.

- [x] **Step 3: Implement detail/comment flow**

Use current TikHub APP parsers. Before hydration, query staging for a structured post with the same ID; if present (including a seed post), do not fetch detail/comments and mark the candidate `duplicate_existing_structured`. Archive each remaining detail batch and comment page. Parse comments page-by-page with page-specific capture IDs, dedupe IDs, recompute final counts/coverage/matches, append-safe insert, and mark every remaining candidate `hydrated`, `excluded`, `outside_window_detail`, `failed`, or `budget_deferred`. Candidate closure is `new_candidate = duplicate_existing_structured + hydrated + excluded + outside_window_detail + failed + budget_deferred`.

- [x] **Step 4: Run twice**

Run `tests.test_backfill_provider -v` twice with the Task 6 command. Expected: second run resumes/no-ops and never clears seed/probe rows.

- [x] **Step 5: Confirm `collect_daily_tikhub` is unchanged**

### Task 8: Build Validation and Replay

**Supplemental execution contract:** `.superpowers/sdd/task-8-brief.md` is the
authoritative Task 8 contract for exact schemas, invariants, replay provenance, publication
failure states, RED cases, and completion evidence.

**Files:**
- Create: `src/reddit_voc/backfill_validation.py`
- Modify: `src/reddit_voc/backfill_archive.py`
- Modify: `src/reddit_voc/backfill_models.py`
- Test: `tests/test_backfill_validation.py`
- Modify test: `tests/test_backfill_archive.py`
- Modify test if required-lane coverage needs it: `tests/test_backfill_storage.py`

**Interfaces:**
- Produces frozen `SeedBaseline` with the exact `momcozy_seed_baseline_v1` fields and fixed numeric contract defined in the supplemental brief.
- Produces: `validate_backfill(store: BackfillStore, archive: PrivateRawArchive, *, run_id: str, seed_baseline: SeedBaseline | None, scope: Literal["seed", "full"] = "full", replay_db: Path | None = None, run_root: Path | None = None) -> dict[str, object]`.
- Produces: `replay_from_archive(source_store: BackfillStore, archive: PrivateRawArchive, *, target_db: Path, run_id: str) -> dict[str, object]`.
- Produces stable `ReplayPublicationError(publication_state="target_exists_needs_review")` for the uncommitted `FileExistsError` race and post-commit publication faults.
- Task 8 neither receives nor parses a release manifest; its exact `backfill_validation_v1` result is release-manifest-free. Task 10 owns the release gate and CLI report envelope.

- [ ] **Step 1: Write failing false-success tests**

Fixtures must reject cross-run raw links, orphan comments, analysis mismatch, occurrence-accounting mismatch, nonterminal required lanes, archive hash failure, delivery rows, and live-send artifacts. A clean fixture must match replay run/raw/post/comment/analysis IDs, raw hashes, and counts.

- [ ] **Step 2: Run and confirm missing validation**

Run the Step 4 validation command. Expected: missing-module import failure.

- [ ] **Step 3: Implement query-only invariants**

Only `cursor_exhausted` and `older_than_window` satisfy required discovery lanes snapshotted in the manifest; optional subreddit lanes are required only when `include_subreddit_sweep=true`. Report occurrence and candidate accounting, provider attempt states, lineage/orphans, timestamp bounds, analysis parity, archive hashes, replay equality, delivery delta, and `live_send=false`. Validation must never migrate a database.

Replay reads the manifest plus `backfill_raw_artifacts`, verifies each gzip, and dispatches by `parser_kind`. `seed_browser_thread`, `tikhub_detail`, and `tikhub_comments` artifacts rebuild entities with their recorded `raw_capture_id`/source/capture metadata; discovery artifacts rebuild occurrence/candidate ledgers. A replay must not need original seed files or network access.

Replay publication uses successful `os.link(temp, target)` as the only commit point. A TOCTOU `FileExistsError` is uncommitted: remove the owned temp and all SQLite sidecars, fsync the parent, verify owned paths are absent, preserve the competing target bytes, then raise the stable review-required exception. Post-link fault semantics remain those in the supplemental brief.

- [ ] **Step 4: Run validation tests**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. \
/Users/pray/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
-m unittest tests.test_backfill_validation -v
```

- [ ] **Step 5: Diff checkpoint**

### Task 9: Add Merge Planning and Gated Insert-Only Merge

**Files:**
- Create: `src/reddit_voc/backfill_merge.py`
- Test: `tests/test_backfill_merge.py`

**Interfaces:**
- Produces: `plan_insert_only_merge(staging_db: Path, production_db: Path, *, run_id: str) -> dict[str, object]`.
- Produces: `merge_staging_insert_only(staging_db: Path, production_db: Path, *, run_id: str, backup_path: Path, expected_production_sha256: str, authorized: bool) -> MergeSummary`.

- [ ] **Step 1: Write failing authorization/conflict/rollback tests**

Assert unauthorized merge writes nothing; the staging `runs` row is inserted first or exact-matched; a mismatched existing run fails; an existing post and all attached staging comments/analyses are skipped; any raw/comment/analysis PK or raw uniqueness conflict causes the whole new-post dependency closure to be skipped; existing entity bytes/run/raw IDs are unchanged; injected analysis failure rolls back; backup precedes transaction; delivery delta is zero.

- [ ] **Step 2: Run and confirm missing merge**

Run the Step 5 merge command. Expected: missing-module import failure.

- [ ] **Step 3: Implement query-only merge plan**

Open both DBs with `mode=ro`. Hash files. Plan the one staging `runs` row, new posts, only comments/analyses belonging to new posts, referenced raw captures, conflicts, baseline counts, and delivery count. Before accepting a new post, validate its complete dependency closure: every required raw capture is insertable/exact, no comment or analysis PK collides, and parsed-comment/analysis parity remains true. A closure conflict skips the whole post and is recorded. The function itself writes nothing.

- [ ] **Step 4: Implement double-gated transaction**

Require `authorized=True` and `REDDIT_VOC_ENABLE_PRODUCTION_MERGE=1`. Require current production SHA-256 to equal the reviewed plan. Create backup with SQLite backup API, hash it, then `ATTACH` staging and `BEGIN IMMEDIATE`. Insert/exact-check `runs` first, then only dependency closures approved by the immutable plan. Use explicit-column insert-select statements guarded by `WHERE NOT EXISTS`. No update/delete/replace/upsert. Roll back on any invariant failure, including an entity whose `run_id` or `raw_capture_id` is absent.

- [ ] **Step 5: Run merge/validation tests**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. \
/Users/pray/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
-m unittest tests.test_backfill_merge tests.test_backfill_validation -v
```

Expected: PASS.

### Task 10: Add Isolated CLI and Collect-Only Wrappers

**Files:**
- Create: `src/reddit_voc/backfill_cli.py`
- Create: `scripts/run_historical_backfill.sh`
- Create: `scripts/server_historical_backfill.sh`
- Modify: `pyproject.toml`
- Test: `tests/test_backfill_cli.py`
- Test: `tests/test_backfill_wrappers.py`

**Interfaces:**
- Produces commands: `seed`, `probe`, `collect`, `replay`, `validate`, `merge-plan`, `merge-production`.

- [ ] **Step 1: Write failing isolation tests**

Importing `backfill_cli` must not load `reddit_voc.cli`, `daily_report`, or `dingtalk`. Missing Provider gate must print blocked JSON with both flags false. Static wrapper tests reject imports/invocations of `server_daily_cycle.sh`, `server_daily_report.sh`, translation, DingTalk, and send commands; generic backfill `--report-dir` text is allowed. Validation tests require `--seed-baseline <reviewed-json>` and `--release-manifest <reviewed-json>` for both scopes; full additionally requires `--run-root` and `--expected-release-manifest-sha256`. Missing/extra/malformed manifest, map/file SHA mismatch, wrong baseline or comment-cursor-contract path, wrong owner-approved manifest SHA, or arbitrary self-signed baseline/manifest fails closed without deriving expected values from staging. Probe failures and collect results must publish immutable content-addressed evidence snapshots rather than overwrite the owner-reviewable ready probe. CLI tests also require the exact `backfill_validation_cli_envelope_v1` key set (`schema_version`, `run_id`, `scope`, `release_manifest_sha256`, `validation`), reject extra/missing keys, and prove `validation` is the unmodified Task 8 exact result.

- [ ] **Step 2: Run and confirm missing files**

Run the Step 5 CLI/wrapper command. Expected: missing module/scripts and no Provider/network activity.

- [ ] **Step 3: Implement CLI double gates**

Provider needs `--authorize-provider-call` + `REDDIT_VOC_BACKFILL_AUTHORIZE_PROVIDER_CALL=1` + `REDDIT_VOC_ENABLE_TIKHUB=1` + key. Probe hardcodes `CONTRACT_PROBE_MAX_REQUESTS=4` and exposes no override. Collect additionally requires owner-supplied cumulative total budget, explicit subreddit-sweep decision, reviewed probe SHA-256, reviewed release-manifest SHA-256, and the fixed code-root `momcozy-comment-cursor-contract-20260711.json`; it may not read the recommended budget as approval. Probe failures and collect outcomes are published with a request-count plus canonical-payload SHA suffix, so rejected/partial evidence cannot overwrite the stable `$RUN_ID-probe.json`. The `validate` command strictly loads a frozen `SeedBaseline` from `--seed-baseline` and the fixed code-root release manifest from `--release-manifest`; seed/full both require both files. It exact-checks the manifest schema/run ID, safe relative-path map, every mapped file SHA, nested baseline path/SHA, and the reviewed comment cursor contract before validation. Full also requires explicit `--run-root` and owner-approved `--expected-release-manifest-sha256`, which must equal the manifest raw-file SHA before its contents become trusted. Arbitrary external or self-signed JSON is not accepted. Task 10 passes only the validated `SeedBaseline` plus Task 8's documented arguments into `validate_backfill`; it never passes the release manifest. It writes the exact CLI envelope with `release_manifest_sha256` beside, not inside, the unmodified nested Task 8 result, whose boundary flags remain present. Validation stays query-only and does not persist `success`. Merge admission strictly validates the full accepted Task 8 result instead of trusting top-level flags alone, requires Task 9 to observe exact `success` in both staging manifest/run rows, and exact-binds Task 8 `source_fingerprints` to the fresh Task 9 `staging_fingerprints`. Merge production additionally has separate env/flag gates and exact owner-reviewed acceptance-report/merge-plan file hashes.

- [ ] **Step 4: Implement wrappers**

Pass only `REDDIT_VOC_ENABLE_TIKHUB`, `TIKHUB_BASE_URL`, `TIKHUB_API_KEY`, `REDDIT_VOC_BACKFILL_*`, and `PYTHONPATH`. The wrapper passes `--authorize-provider-call` only when `REDDIT_VOC_BACKFILL_AUTHORIZE_PROVIDER_CALL=1`; phase alone never adds it. `server_historical_backfill.sh` must start a fresh `docker run --rm` one-shot container for every phase, mount the reviewed code bundle read-only and only the isolated backfill run directory read-write, reject symlinks in every host-mount path component before canonicalization, and never `exec`/restart the production container. Probe/collect retain container network access but receive the Provider key only through the approved secret-injection channel; replay/validate additionally use `--network none`. Collect must forward the explicit probe report/SHA, release manifest/SHA, comment cursor contract, cumulative budget, and `INCLUDE_SUBREDDIT_SWEEP` decision. Replay/validate forward the explicit source/replay DB, archive, report, run-root, seed-baseline, release-manifest, expected-manifest-SHA, run ID, scope and phase values. The validate phase must map those values to `--run-root`, `--seed-baseline`, `--release-manifest`, and `--expected-release-manifest-sha256` exactly. No phase may mount production DB, `.env`, key, pem, DingTalk/public-artifact/translation/daily-report inputs.

The accepted Task 8 `operational_accounting` check also carries a canonical SHA-256 over every source operational row not covered by the six Task 9 merge surfaces (including the complete manifest/run, seed, attempt, checkpoint, candidate, occurrence, detail, delivery and issue/conflict ledgers). Merge admission recomputes that snapshot from the current read-only staging transaction and exact-matches both check values, so same-row-count content drift cannot reuse an older acceptance report. The server wrapper re-verifies the reviewed bundle from inside the actual code bind mount before exec. Its one-time run-root marker is additionally bound to the host directory `(st_dev, st_ino)` observed at creation and those values must match the mounted directory; moving the marker into a substituted directory is rejected. A platform that does not preserve bind-source device/inode identity must fail closed rather than bypass this check.

- [ ] **Step 5: Add entry point and verify**

```toml
reddit-voc-backfill = "reddit_voc.backfill_cli:main"
```

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. \
/Users/pray/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
-m unittest tests.test_backfill_cli tests.test_backfill_wrappers -v
bash -n scripts/run_historical_backfill.sh scripts/server_historical_backfill.sh
```

Expected: PASS/no shell output.

### Task 11: Update Records and Run Full Local Verification

**Files:**
- Create: `config/backfill/momcozy-seed-baseline-20250101-20260711.json`
- Create: `config/backfill/momcozy-comment-cursor-contract-20260711.json`
- Create: `config/backfill/momcozy-backfill-release-manifest-20260711.json`
- Modify: `README.md`
- Modify: `.codex/context-pack.md`
- Modify: `.codex/session-thread.md`
- Modify: `.kiro/plan/task_plan.md`
- Modify: `.kiro/plan/progress.md`
- Modify: `.kiro/plan/findings.md`
- Modify: `.kiro/plan/acceptance.md`

- [ ] **Step 1: Document exact paths, commands, gates, and seed baseline**

Use fixed run ID `backfill_momcozy_20250101_20260711`. Produce and review the exact-key `momcozy_seed_baseline_v1` JSON outside staging, including the known counts, canonical source-inventory SHA-256, exactly-three known partial-post-ID SHA-256, reviewed default-search-term SHA-256, and reviewed subreddit snapshot/hash. Produce the fixed `tikhub_comment_cursor_contract_v1` JSON with exactly `schema_version`, `cursor_path`, and `cursor_schema_sha256`; its path is `config/backfill/momcozy-comment-cursor-contract-20260711.json`, and collect may not substitute a runtime-inferred or off-root contract. Also produce the exact-key `momcozy_backfill_release_manifest_v1` with `schema_version`, fixed `run_id`, baseline relative path/SHA, and a relative-path SHA-256 map that exactly covers every reviewed source/script/config/runtime file in the transfer bundle except the manifest itself, including the comment cursor contract. It contains no self hash, secret, `.env`, key, pem, credential or run data. Configure probe-rejected and collect evidence as immutable content-addressed snapshots named with the request count and canonical-payload SHA suffix under the isolated run's `reports/`; the stable ready probe remains `$RUN_ID-probe.json` and is never overwritten by a rejected attempt. Do not invent either data-derived hash or derive expected values from the DB being validated. Preserve `production unchanged`, `provider_call=false`, `live_send=false` until stronger evidence exists.

The numeric baseline is fixed, not user-configurable: files `55/48 imported/7 outside/0 excluded/0 duplicate/0 parse error`; entities `48 threads/1,894 comments/1,942 analyses`; coverage `45 full/3 partial/0 post_only`. Task 11 must independently calculate, record, and review `source_inventory_sha256` and `known_partial_post_ids_sha256` in the repo-reviewed baseline JSON, then record that file's SHA-256 in the release/transfer manifest. Later validation accepts only that reviewed config under the code root, never an arbitrary external self-signed JSON.

- [ ] **Step 2: Run all backfill tests**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. \
/Users/pray/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
-m unittest tests.test_backfill_contract tests.test_backfill_storage \
tests.test_backfill_archive tests.test_backfill_seed tests.test_backfill_provider \
tests.test_backfill_validation tests.test_backfill_merge tests.test_backfill_cli \
tests.test_backfill_wrappers -v
```

Expected: exit 0, all `OK`, no network.

- [ ] **Step 3: Run full suite**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. \
/Users/pray/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
-m unittest discover -s tests -v
```

Expected: exit 0, all `OK`.

- [ ] **Step 4: Static checks**

Run `bash -n`, no-index whitespace checks for every created/modified file, and `git status --short`. Do not commit.

### Task 12: Execute the Local Seed Backfill

**Runtime writes only:**
- `data/backfill/backfill_momcozy_20250101_20260711/`

- [ ] **Step 1: Run isolated seed import**

```bash
cd /Users/pray/project/Reddit_VOC
PY=/Users/pray/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3
RUN_ID=backfill_momcozy_20250101_20260711
ROOT=data/backfill/$RUN_ID
DATABASE="$ROOT/reddit_voc_backfill.sqlite3"
CODE_ROOT="$PWD"
SEED_BASELINE="$CODE_ROOT/config/backfill/momcozy-seed-baseline-20250101-20260711.json"
RELEASE_MANIFEST="$CODE_ROOT/config/backfill/momcozy-backfill-release-manifest-20260711.json"
test -f "$SEED_BASELINE"
test -f "$RELEASE_MANIFEST"
EFFECTIVE_END_UTC="2026-07-11T16:00:00Z"
mkdir -p "$ROOT"
command -v lsof >/dev/null || {
  printf '%s\n' 'Task 12 blocked: lsof is required for single-writer preflight.' >&2
  exit 1
}
if test -e "$DATABASE" && lsof "$DATABASE" >/dev/null 2>&1; then
  printf '%s\n' 'Task 12 blocked: staging database has a concurrent opener.' >&2
  exit 1
fi

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. "$PY" -m reddit_voc.backfill_cli seed \
  --run-id "$RUN_ID" \
  --database "$DATABASE" \
  --source-dir /Users/pray/project/ai_nlp_voc/system_data/voc_data/reddit/Momcozy \
  --raw-archive-dir "$ROOT/private-raw" \
  --report-dir "$ROOT/reports" \
  --window-start-utc 2024-12-31T16:00:00Z \
  --requested-window-end-utc 2026-07-11T16:00:00Z \
  --effective-window-end-utc "$EFFECTIVE_END_UTC"
```

The CLI inserts this fixed approved value into the manifest on first creation and exact-matches it thereafter. Resume/replay reads the stored value; it never derives the boundary from the current clock for this run. Both seed invocations are strict single-writer operations: the pinned-inode safety path uses a private hardlink alias, so no process may hold or open the public staging DB path during seed. Record the `lsof` preflight result with the Task 12 evidence; any concurrent opener is a stop condition.

Expected exact baseline: files `55 total/48 imported/7 outside/0 excluded/0 duplicate/0 parse error`; entities `48 threads/1,894 comments/1,942 analyses`; coverage `45 full/3 partial/0 post_only`. The runtime inventory hash and exactly-three partial-ID hash must equal the Task 11 repo-reviewed baseline JSON; both boundary flags remain false.

- [ ] **Step 2: Replay the same command**

Re-run the exact `seed` command with the same frozen `EFFECTIVE_END_UTC`. Expected: identical entity totals, no lineage migration, deterministic no-op inserts.

- [ ] **Step 3: Validate seed-only staging**

```bash
SEED_BASELINE="$PWD/config/backfill/momcozy-seed-baseline-20250101-20260711.json"
RELEASE_MANIFEST="$PWD/config/backfill/momcozy-backfill-release-manifest-20260711.json"
test -f "$SEED_BASELINE"
test -f "$RELEASE_MANIFEST"
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. "$PY" -m reddit_voc.backfill_cli validate \
  --scope seed \
  --run-id "$RUN_ID" \
  --database "$ROOT/reddit_voc_backfill.sqlite3" \
  --raw-archive-dir "$ROOT/private-raw" \
  --seed-baseline "$SEED_BASELINE" \
  --release-manifest "$RELEASE_MANIFEST" \
  --report "$ROOT/reports/$RUN_ID-seed-acceptance.json"
```

Seed acceptance passes with `replay_status=not_run` and `full_ready=false`; Provider lanes remain `not_run` rather than being mislabeled complete.
The report file is the exact `backfill_validation_cli_envelope_v1`: its `validation` member contains those Task 8 fields unchanged, while `release_manifest_sha256` is envelope metadata owned by Task 10.

- [ ] **Step 4: Record local/staging evidence only**

### Task 13: Execute the Four-Request TikHub Contract Probe

**Boundary:** Real charged Provider calls, at most four attempts; staging writes only. The approved spec authorizes this cap after local tests and seed acceptance pass.

- [ ] **Step 1: Transfer only reviewed backfill source/scripts and staging bundle to the server staging path**

Do not run the web deploy script, restart containers, modify cron, or copy production DB. Upload an isolated release bundle; do not overwrite `/opt/reddit-voc-site/src` or `/opt/reddit-voc-site/scripts`:

```bash
cd /Users/pray/project/Reddit_VOC
RUN_ID=backfill_momcozy_20250101_20260711
: "${SSH_KEY:?owner-supplied repo-external SSH identity is required}"
REMOTE="${REMOTE:-ubuntu@101.34.52.232}"
REMOTE_BUNDLE="/opt/reddit-voc-backfill/$RUN_ID/code"
ARCHIVE="/tmp/$RUN_ID-code.tgz"
SEED_BASELINE="config/backfill/momcozy-seed-baseline-20250101-20260711.json"
RELEASE_MANIFEST="config/backfill/momcozy-backfill-release-manifest-20260711.json"
FILE_LIST="/tmp/$RUN_ID-reviewed-files.txt"
test -f "$SEED_BASELINE"
test -f "$RELEASE_MANIFEST"
RELEASE_MANIFEST_SHA256="$(shasum -a 256 "$RELEASE_MANIFEST" | awk '{print $1}')"

python3 - "$RELEASE_MANIFEST" >"$FILE_LIST" <<'PY'
import json, pathlib, sys
manifest = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
for relative_path in sorted(manifest["reviewed_files_sha256"]):
    path = pathlib.PurePosixPath(relative_path)
    if path.is_absolute() or ".." in path.parts or "\n" in relative_path:
        raise SystemExit("unsafe release-manifest path")
    print(relative_path)
print(sys.argv[1])
PY
COPYFILE_DISABLE=1 tar --exclude='._*' -czf "$ARCHIVE" -T "$FILE_LIST"
scp -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new \
  "$ARCHIVE" "$REMOTE:/tmp/$RUN_ID-code.tgz"
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new "$REMOTE" \
  "test ! -e '$REMOTE_BUNDLE' && mkdir -p '$REMOTE_BUNDLE' && \
tar -xzf '/tmp/$RUN_ID-code.tgz' -C '$REMOTE_BUNDLE'"
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new "$REMOTE" \
  "python3 - '$REMOTE_BUNDLE' '$RELEASE_MANIFEST' '$RELEASE_MANIFEST_SHA256'" <<'PY'
from hashlib import sha256
from pathlib import Path, PurePosixPath
import json, sys

root = Path(sys.argv[1]).resolve(strict=True)
manifest_rel, expected_manifest_sha = sys.argv[2:]
manifest_path = root / manifest_rel
raw = manifest_path.read_bytes()
assert sha256(raw).hexdigest() == expected_manifest_sha
manifest = json.loads(raw)
assert set(manifest) == {"schema_version", "run_id", "seed_baseline", "reviewed_files_sha256"}
assert manifest["schema_version"] == "momcozy_backfill_release_manifest_v1"
assert manifest["run_id"] == "backfill_momcozy_20250101_20260711"
assert set(manifest["seed_baseline"]) == {"relative_path", "sha256"}
mapped = manifest["reviewed_files_sha256"]
assert manifest_rel not in mapped
for relative_path, expected_sha in mapped.items():
    pure = PurePosixPath(relative_path)
    assert not pure.is_absolute() and ".." not in pure.parts
    path = root.joinpath(*pure.parts)
    assert not path.is_symlink() and path.is_file()
    assert path.resolve(strict=True).is_relative_to(root)
    assert sha256(path.read_bytes()).hexdigest() == expected_sha
baseline = manifest["seed_baseline"]
assert baseline["relative_path"] == "config/backfill/momcozy-seed-baseline-20250101-20260711.json"
assert mapped[baseline["relative_path"]] == baseline["sha256"]
actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
assert actual == set(mapped) | {manifest_rel}
print(expected_manifest_sha)
PY
```

Record `RELEASE_MANIFEST_SHA256` in the reviewed release/transfer evidence. The remote check
must verify the manifest raw-file SHA, strict schema, every mapped file, exact transferred-file
set, and nested baseline path/SHA. Task 14 accepts only this extracted fixed code-root manifest
and baseline, never runtime-generated or arbitrary external JSON.

Copy the already validated local staging bundle into the production host's isolated backfill directory, never into the production database path:

```bash
rsync -a --checksum -e "ssh -i $SSH_KEY -o StrictHostKeyChecking=accept-new" \
  "data/backfill/$RUN_ID/" \
  "$REMOTE:/opt/reddit-voc-site/data/backfill/$RUN_ID/"
```

- [ ] **Step 2: Run probe**

```bash
: "${SSH_KEY:?owner-supplied repo-external SSH identity is required}"
REMOTE="${REMOTE:-ubuntu@101.34.52.232}"
RUN_ID=backfill_momcozy_20250101_20260711
REMOTE_BUNDLE="/opt/reddit-voc-backfill/$RUN_ID/code"
HOST_RUN_ROOT="/opt/reddit-voc-site/data/backfill/$RUN_ID"
CONTAINER_CODE_ROOT=/app/backfill-code
CONTAINER_RUN_ROOT="/app/data/backfill/$RUN_ID"
: "${BACKFILL_CONTAINER_IMAGE:?reviewed one-shot container image is required}"
: "${RELEASE_MANIFEST_SHA256:?locally reviewed release manifest SHA-256 is required}"

ssh -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new "$REMOTE" \
  "test -n \"\${TIKHUB_API_KEY:-}\" && \
REDDIT_VOC_BACKFILL_CONTAINER_IMAGE='$BACKFILL_CONTAINER_IMAGE' \
REDDIT_VOC_BACKFILL_CODE_ROOT='$REMOTE_BUNDLE' \
REDDIT_VOC_BACKFILL_HOST_RUN_ROOT='$HOST_RUN_ROOT' \
REDDIT_VOC_BACKFILL_CONTAINER_CODE_ROOT='$CONTAINER_CODE_ROOT' \
REDDIT_VOC_BACKFILL_RUN_ROOT='$CONTAINER_RUN_ROOT' \
REDDIT_VOC_BACKFILL_PHASE=probe \
REDDIT_VOC_BACKFILL_AUTHORIZE_PROVIDER_CALL=1 \
REDDIT_VOC_ENABLE_TIKHUB=1 \
TIKHUB_API_KEY=\"\$TIKHUB_API_KEY\" \
REDDIT_VOC_BACKFILL_RUN_ID='$RUN_ID' \
REDDIT_VOC_BACKFILL_DATABASE_PATH='$CONTAINER_RUN_ROOT/reddit_voc_backfill.sqlite3' \
REDDIT_VOC_BACKFILL_RAW_ARCHIVE_DIR='$CONTAINER_RUN_ROOT/private-raw' \
REDDIT_VOC_BACKFILL_REPORT_DIR='$CONTAINER_RUN_ROOT/reports' \
REDDIT_VOC_BACKFILL_RELEASE_MANIFEST='$CONTAINER_CODE_ROOT/config/backfill/momcozy-backfill-release-manifest-20260711.json' \
REDDIT_VOC_BACKFILL_EXPECTED_RELEASE_MANIFEST_SHA256='$RELEASE_MANIFEST_SHA256' \
'$REMOTE_BUNDLE/scripts/server_historical_backfill.sh'"
```

Before this command, the approved server secret-injection channel must make `TIKHUB_API_KEY` available to the remote noninteractive shell; never embed it in this plan, print it, or read a project `.env`. `REDDIT_VOC_ENABLE_TIKHUB=1`, the CLI authorization flag derived from `REDDIT_VOC_BACKFILL_AUTHORIZE_PROVIDER_CALL=1`, and the key are all required. The fresh one-shot container mounts `REMOTE_BUNDLE` read-only and only `HOST_RUN_ROOT` read-write. Expected: <=4 attempts, <=2 successful dynamic pages, one stable cursor contract/schema hash, `provider_call=true`, `live_send=false`, production DB unchanged.

- [ ] **Step 3: Produce exact budget authorization packet**

Include recommended cumulative request count, inputs, lanes, observed page time density, current count, cursor path/schema hash, cost uncertainty, and the remotely verified `RELEASE_MANIFEST_SHA256`. Stop for exact owner approval of the budget, subreddit flag, probe SHA, and release-manifest SHA before Task 14.

### Task 14: Run Full Staging Backfill After Exact Budget Approval

**Boundary:** Requires approval of the exact cumulative request total, whether subreddit sweep is included, the reviewed probe raw SHA-256, and the reviewed release-manifest raw SHA-256.

- [x] **Step 1: Validate independent owner approval against the reviewed probe report**

```bash
RUN_ID=backfill_momcozy_20250101_20260711
REMOTE_BUNDLE=/opt/reddit-voc-backfill/$RUN_ID/code
PROBE=/opt/reddit-voc-site/data/backfill/$RUN_ID/reports/$RUN_ID-probe.json
RELEASE_MANIFEST=$REMOTE_BUNDLE/config/backfill/momcozy-backfill-release-manifest-20260711.json
: "${APPROVED_TOTAL_BUDGET:?owner-approved cumulative integer is required}"
: "${APPROVED_SUBREDDIT_SWEEP:?owner-approved 0 or 1 is required}"
: "${APPROVED_PROBE_SHA256:?owner-reviewed probe SHA-256 is required}"
: "${APPROVED_RELEASE_MANIFEST_SHA256:?owner-reviewed release manifest SHA-256 is required}"
test "$APPROVED_TOTAL_BUDGET" -ge 4
test "$APPROVED_SUBREDDIT_SWEEP" = 0 -o "$APPROVED_SUBREDDIT_SWEEP" = 1
ACTUAL_PROBE_SHA256="$(python3 - "$PROBE" <<'PY'
from hashlib import sha256
from pathlib import Path
import sys
print(sha256(Path(sys.argv[1]).read_bytes()).hexdigest())
PY
)"
test "$ACTUAL_PROBE_SHA256" = "$APPROVED_PROBE_SHA256"
ACTUAL_RELEASE_MANIFEST_SHA256="$(sha256sum "$RELEASE_MANIFEST" | awk '{print $1}')"
test "$ACTUAL_RELEASE_MANIFEST_SHA256" = "$APPROVED_RELEASE_MANIFEST_SHA256"
```

These four approved values come from the owner's explicit authorization record, not from `recommended_max_provider_requests` in the report or from the manifest's own contents.

- [x] **Step 2: Resume full staging collection**

Use the same isolated paths, the approved cumulative total, and the separately approved subreddit flag. Resume checkpoints; never clear seed/probe:

```bash
: "${SSH_KEY:?owner-supplied repo-external SSH identity is required}"
REMOTE="${REMOTE:-ubuntu@101.34.52.232}"
RUN_ID=backfill_momcozy_20250101_20260711
REMOTE_BUNDLE="/opt/reddit-voc-backfill/$RUN_ID/code"
HOST_RUN_ROOT="/opt/reddit-voc-site/data/backfill/$RUN_ID"
CONTAINER_CODE_ROOT=/app/backfill-code
CONTAINER_RUN_ROOT="/app/data/backfill/$RUN_ID"
PROBE_REPORT="$CONTAINER_RUN_ROOT/reports/$RUN_ID-probe.json"
RELEASE_MANIFEST="$CONTAINER_CODE_ROOT/config/backfill/momcozy-backfill-release-manifest-20260711.json"
COMMENT_CURSOR_CONTRACT="$CONTAINER_CODE_ROOT/config/backfill/momcozy-comment-cursor-contract-20260711.json"
: "${BACKFILL_CONTAINER_IMAGE:?reviewed one-shot container image is required}"

ssh -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new "$REMOTE" \
  "test -n \"\${TIKHUB_API_KEY:-}\" && \
REDDIT_VOC_BACKFILL_CONTAINER_IMAGE='$BACKFILL_CONTAINER_IMAGE' \
REDDIT_VOC_BACKFILL_CODE_ROOT='$REMOTE_BUNDLE' \
REDDIT_VOC_BACKFILL_HOST_RUN_ROOT='$HOST_RUN_ROOT' \
REDDIT_VOC_BACKFILL_CONTAINER_CODE_ROOT='$CONTAINER_CODE_ROOT' \
REDDIT_VOC_BACKFILL_RUN_ROOT='$CONTAINER_RUN_ROOT' \
REDDIT_VOC_BACKFILL_PHASE=collect \
REDDIT_VOC_BACKFILL_AUTHORIZE_PROVIDER_CALL=1 \
REDDIT_VOC_ENABLE_TIKHUB=1 \
TIKHUB_API_KEY=\"\$TIKHUB_API_KEY\" \
REDDIT_VOC_BACKFILL_RUN_ID='$RUN_ID' \
REDDIT_VOC_BACKFILL_DATABASE_PATH='$CONTAINER_RUN_ROOT/reddit_voc_backfill.sqlite3' \
REDDIT_VOC_BACKFILL_RAW_ARCHIVE_DIR='$CONTAINER_RUN_ROOT/private-raw' \
REDDIT_VOC_BACKFILL_REPORT_DIR='$CONTAINER_RUN_ROOT/reports' \
REDDIT_VOC_BACKFILL_PROBE_REPORT='$PROBE_REPORT' \
REDDIT_VOC_BACKFILL_EXPECTED_PROBE_SHA256='$APPROVED_PROBE_SHA256' \
REDDIT_VOC_BACKFILL_RELEASE_MANIFEST='$RELEASE_MANIFEST' \
REDDIT_VOC_BACKFILL_EXPECTED_RELEASE_MANIFEST_SHA256='$APPROVED_RELEASE_MANIFEST_SHA256' \
REDDIT_VOC_BACKFILL_COMMENT_CURSOR_CONTRACT='$COMMENT_CURSOR_CONTRACT' \
REDDIT_VOC_BACKFILL_MAX_PROVIDER_REQUESTS_TOTAL='$APPROVED_TOTAL_BUDGET' \
REDDIT_VOC_BACKFILL_INCLUDE_SUBREDDIT_SWEEP='$APPROVED_SUBREDDIT_SWEEP' \
'$REMOTE_BUNDLE/scripts/server_historical_backfill.sh'"
```

The collect one-shot container uses the same approved remote key-injection rule as probe. The wrapper must exact-map `PROBE_REPORT`, `EXPECTED_PROBE_SHA256`, `RELEASE_MANIFEST`, `EXPECTED_RELEASE_MANIFEST_SHA256`, `COMMENT_CURSOR_CONTRACT`, and `INCLUDE_SUBREDDIT_SWEEP`; none may be inferred from a report recommendation or a runtime payload.

- [ ] **Step 3: Replay and validate — blocked after fail-closed replay failure**

```bash
: "${SSH_KEY:?owner-supplied repo-external SSH identity is required}"
REMOTE="${REMOTE:-ubuntu@101.34.52.232}"
RUN_ID=backfill_momcozy_20250101_20260711
REMOTE_BUNDLE=/opt/reddit-voc-backfill/$RUN_ID/code
HOST_RUN_ROOT=/opt/reddit-voc-site/data/backfill/$RUN_ID
CONTAINER_CODE_ROOT=/app/backfill-code
CONTAINER_RUN_ROOT=/app/data/backfill/$RUN_ID
: "${BACKFILL_CONTAINER_IMAGE:?reviewed one-shot container image is required}"
: "${APPROVED_RELEASE_MANIFEST_SHA256:?owner-reviewed release manifest SHA-256 is required}"

ssh -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new "$REMOTE" \
  "test ! -e '$HOST_RUN_ROOT/replay.sqlite3' && \
REDDIT_VOC_BACKFILL_PHASE=replay \
REDDIT_VOC_BACKFILL_CONTAINER_IMAGE='$BACKFILL_CONTAINER_IMAGE' \
REDDIT_VOC_BACKFILL_CODE_ROOT='$REMOTE_BUNDLE' \
REDDIT_VOC_BACKFILL_HOST_RUN_ROOT='$HOST_RUN_ROOT' \
REDDIT_VOC_BACKFILL_CONTAINER_CODE_ROOT='$CONTAINER_CODE_ROOT' \
REDDIT_VOC_BACKFILL_RUN_ROOT='$CONTAINER_RUN_ROOT' \
REDDIT_VOC_BACKFILL_RUN_ID='$RUN_ID' \
REDDIT_VOC_BACKFILL_SOURCE_DATABASE_PATH='$CONTAINER_RUN_ROOT/reddit_voc_backfill.sqlite3' \
REDDIT_VOC_BACKFILL_REPLAY_DATABASE_PATH='$CONTAINER_RUN_ROOT/replay.sqlite3' \
REDDIT_VOC_BACKFILL_RAW_ARCHIVE_DIR='$CONTAINER_RUN_ROOT/private-raw' \
REDDIT_VOC_BACKFILL_EXPECTED_RELEASE_MANIFEST_SHA256='$APPROVED_RELEASE_MANIFEST_SHA256' \
'$REMOTE_BUNDLE/scripts/server_historical_backfill.sh'"

ssh -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new "$REMOTE" \
  "REDDIT_VOC_BACKFILL_PHASE=validate \
REDDIT_VOC_BACKFILL_CONTAINER_IMAGE='$BACKFILL_CONTAINER_IMAGE' \
REDDIT_VOC_BACKFILL_CODE_ROOT='$REMOTE_BUNDLE' \
REDDIT_VOC_BACKFILL_HOST_RUN_ROOT='$HOST_RUN_ROOT' \
REDDIT_VOC_BACKFILL_CONTAINER_CODE_ROOT='$CONTAINER_CODE_ROOT' \
REDDIT_VOC_BACKFILL_RUN_ROOT='$CONTAINER_RUN_ROOT' \
REDDIT_VOC_BACKFILL_RUN_ID='$RUN_ID' \
REDDIT_VOC_BACKFILL_SCOPE=full \
REDDIT_VOC_BACKFILL_DATABASE_PATH='$CONTAINER_RUN_ROOT/reddit_voc_backfill.sqlite3' \
REDDIT_VOC_BACKFILL_REPLAY_DATABASE_PATH='$CONTAINER_RUN_ROOT/replay.sqlite3' \
REDDIT_VOC_BACKFILL_RAW_ARCHIVE_DIR='$CONTAINER_RUN_ROOT/private-raw' \
REDDIT_VOC_BACKFILL_SEED_BASELINE='$CONTAINER_CODE_ROOT/config/backfill/momcozy-seed-baseline-20250101-20260711.json' \
REDDIT_VOC_BACKFILL_RELEASE_MANIFEST='$CONTAINER_CODE_ROOT/config/backfill/momcozy-backfill-release-manifest-20260711.json' \
REDDIT_VOC_BACKFILL_EXPECTED_RELEASE_MANIFEST_SHA256='$APPROVED_RELEASE_MANIFEST_SHA256' \
REDDIT_VOC_BACKFILL_REPORT='$CONTAINER_RUN_ROOT/reports/$RUN_ID-acceptance.json' \
'$REMOTE_BUNDLE/scripts/server_historical_backfill.sh'"
```

Both calls must use the Task 10 wrapper's fresh `docker run --rm --network none` path: mount
`REMOTE_BUNDLE` at `CONTAINER_CODE_ROOT` read-only and only `HOST_RUN_ROOT` at
`CONTAINER_RUN_ROOT` read-write. They must never `docker exec`/restart the production container,
mount the production DB, or mix host `/opt/...` paths into container CLI arguments.

The acceptance report must be the exact `backfill_validation_cli_envelope_v1`; its
`release_manifest_sha256` equals `APPROVED_RELEASE_MANIFEST_SHA256`, and its `validation` value is
the unmodified Task 8 `backfill_validation_v1` result with matching `run_id` and `scope=full`.

Acceptance passes only when the envelope's nested `validation` proves the fixed `55/48/7/0/0/0`, `48/1,894/1,942`, `45/3/0` seed baseline and both Task 11 reviewed data hashes match; the only partial coverage is the baseline-bound exactly three `historical_seed` post IDs; manifest search terms exact-match `DEFAULT_TIKHUB_SEARCH_TERMS`; every enabled required lane has at least one committed page plus sent endpoint evidence and ends at `cursor_exhausted` or `older_than_window`; occurrence/candidate accounting closes, archive hashes and full replay row fingerprints match, no `*-live-send.json` exists under `run_root`, and delivery remains zero.

- [ ] **Step 4: Prepare read-only merge plan and stop for production-write approval — not admissible**

```bash
python3 -m reddit_voc.backfill_cli merge-plan \
  --run-id backfill_momcozy_20250101_20260711 \
  --staging-database /app/data/backfill/backfill_momcozy_20250101_20260711/reddit_voc_backfill.sqlite3 \
  --production-database /app/data/reddit_voc_daily.sqlite3 \
  --acceptance-report /app/data/backfill/backfill_momcozy_20250101_20260711/reports/backfill_momcozy_20250101_20260711-acceptance.json \
  --output /app/data/backfill/backfill_momcozy_20250101_20260711/reports/backfill_momcozy_20250101_20260711-merge-plan.json
```

Hash the acceptance report and merge plan, record the production baseline SHA-256/counts, and stop. This command opens production read-only and does not authorize merge.

**2026-07-12 Task 14 execution result:** Owner option B was exact-validated and
the collect phase reached cumulative request count `670`; all attempts
succeeded, but the immutable result was `partial/budget_exhausted`. The first
`Momcozy` dynamic lane consumed all 670 pages, the other 29 required lanes
committed zero pages, and 238 candidates remained `budget_deferred`. Offline
replay returned `failed/discovery_occurrence_mismatch` and atomically removed
its unpublished target. Without `replay.sqlite3`, the formal full-validation
CLI was not admitted and no acceptance report was generated. Step 4 was
therefore skipped. Production remained unchanged, delivery stayed zero and
`live_send=false`. Task 14 is not accepted; Task 15 remains unauthorized.

### Task 14A: Repair Replay Occurrence Contract Locally

**Boundary:** Local code/tests/manifest only. No remote transfer, Provider
request, staging write, production merge, Git push or DingTalk.

- [x] Add a RED replay regression for partial-identity and missing-title invalid
  discovery rows.
- [x] Make collector and replay share one occurrence classification/persistence
  contract.
- [x] Add collector field-level assertions for fully empty, partial-identity
  and missing-title rows.
- [x] Run Python 3.11 backfill and workspace full test suites.
- [x] Update the fixed release manifest's changed runtime hashes and obtain
  independent review.
- [x] Transfer the repaired bundle to a manifest-SHA-versioned directory and run
  exactly one network-disabled remote replay under new explicit authorization.

Local repair result on 2026-07-13:

```text
evidence_grade=L2-fixture-or-dry-run
local_only
provider_call=false
remote_transfer=false
staging_database_write=false
live_send=false
python311_backfill=261/261 OK
full_suite=344/344 OK
independent_review=APPROVED
candidate_manifest_sha256=ec5548c6606e587ae8d9d18809ae643553a03306a44ef2371867a64659a52253
ready_for_owner_authorization
```

The historical Task 14 executed manifest SHA remains
`471dc848cdadff544a8e7009e044ca2cdba03e2add81f741d0d37b4dd0fb949e`.
Any later remote replay must use a manifest-SHA-versioned code directory and
must not overwrite the historical `/code` bundle.

**2026-07-13 authorized remote replay result:** The exact 23-file bundle was
installed at `/opt/reddit-voc-backfill/backfill_momcozy_20250101_20260711/code-ec5548c6606e587ae8d9d18809ae643553a03306a44ef2371867a64659a52253`;
the historical `/code` manifest/tree hashes were unchanged. One digest-pinned
`--network none` replay still returned
`failed/discovery_occurrence_mismatch`, with `provider_attempt_made=false` and
`live_send=false`, and atomically removed its unpublished target. Read-only
diagnosis found page 1 ordinal 3 has parsed `post_id` present while the frozen
source occurrence stores null identity/time fields. This was an ordinal-level
observation; its initial interpretation as mixed persistence semantics was not
proven and is superseded by the Task 16 local root-cause work below. No full
validation, merge-plan, Provider request, production merge, Git push or DingTalk
ran. Task 14 remains unaccepted and Task 15 remains unauthorized.

### Task 16: Canonical Archive Order Replay Repair

**Boundary:** Local source/tests/manifest/evidence only. No remote transfer or
replay, Provider request, staging write, production merge, Git push or DingTalk.

- [x] Reproduce the archive-order defect as RED with non-canonical dictionary
  key insertion order.
- [x] Make discovery collection parse the exact canonical bytes written to the
  private archive.
- [x] Reconcile historical discovery pages through an exact multiset of base
  disposition and persisted fields, then reconstruct frozen source ordinal
  order.
- [x] Prove post-ID, ordinal, artifact and capture-time tampering still fails
  closed and publishes no target.
- [x] Run Python 3.11 backfill and isolated full suites, refresh the exact
  release manifest, and obtain independent review.

Local result on 2026-07-13:

```text
evidence_grade=L2-fixture-or-dry-run
local_only
production unchanged
provider_call=false
provider_attempt_made=false
remote_transfer=false
staging_database_write=false
live_send=false
python311_backfill=263/263 OK
full_suite=346/346 OK
reviewed_files=22/22
independent_review=APPROVED
candidate_manifest_sha256=0663168b890cbd858068548eb3b43ee70345e01854090f42ae0baf91ac9fe0ba
ready_for_owner_authorization
```

The exact page multiset is required; there is no null wildcard, partial-field
substitution, cross-page matching or fingerprint relaxation. The mechanism is
proven locally and explains the Task 14A ordinal mismatch. Task 17 subsequently
proved this candidate passes occurrence reconciliation against the frozen
snapshot before reaching a separate checkpoint gate.

### Task 17: SHA-Versioned Remote Replay

**Boundary:** Exact candidate transfer and at most one staging replay with
network disabled. No Provider request, full validation, merge plan, production
merge, Git push or DingTalk.

- [x] Build a `--no-xattrs` exact 23-file archive and verify all manifest hashes.
- [x] Install atomically under `code-0663168...fe0ba` without changing either
  historical bundle.
- [x] Create a permanent SHA-bound one-shot guard and run the digest-pinned
  wrapper exactly once with `--network none` and replay-only `env -i` values.
- [x] Capture pre/post source, raw archive, Provider, delivery and production
  boundaries; clean the transfer inbox.
- [x] Diagnose the new checkpoint failure with read-only aggregate fields only.

Result on 2026-07-13:

```text
evidence_grade=L4-authorized-live
remote_transfer=true
staging_replay_attempted=true
replay_attempt_count=1
status=failed
stop_reason=discovery_checkpoint_mismatch
checkpoint_lane_count=30
artifact_lane_count=1
checkpoint_without_artifact_count=29
page_number_mismatch_count=0
replay_database_published=false
provider_attempt_made=false
production unchanged
live_send=false
Task14_acceptance=false
Task15_authorized=false
```

The 29 checkpoint-only lanes are all page-zero
`partial/budget_exhausted`. The next repair must be local-only and preserve
those checkpoints without fabricating artifacts or weakening page-chain checks.
The Task 17 guard prohibits replaying this SHA again.

### Task 18: Zero-Page Checkpoint Replay Repair

**Boundary:** Local source, fixtures, tests, manifest and review only. No SSH,
remote replay, Provider call, production change, Git push or DingTalk.

- [x] Add a RED fixture with one normal artifact-bearing lane and one configured
  checkpoint-only lane that stopped before page 1 because the cumulative budget
  was exhausted.
- [x] Replay the legitimate zero-page checkpoint exactly without inventing an
  artifact or weakening checks for lanes that have pages.
- [x] Accept checkpoint-only discovery lanes only under an exact fail-closed
  contract: configured lane, page/discovered/unique/consecutive-old counts zero,
  `partial/budget_exhausted`, exhausted manifest request budget, no cursor,
  success timestamp or cursor-contract state.
- [x] Keep artifact-only lanes, unconfigured lanes, positive-page checkpoint-only
  lanes and every tampered zero-page field rejected.
- [x] Run focused RED/GREEN, the backfill family, isolated full suite, exact
  manifest refresh and independent review. The next candidate must receive a
  new SHA; `0663168...fe0ba` cannot be replayed again.

Local result on 2026-07-13:

```text
evidence_grade=L2-fixture-or-dry-run
focused_tests=5/5 OK
validation_tests=56/56 OK
offline_full_suite=351/351 OK
reviewed_files=22/22
independent_review=APPROVED
candidate_manifest_sha256=c6d289329443a92ed59c5849fa9fbfe15afc854df709497351c1b7003fd9b2dc
local_only
production unchanged
provider_call=false
provider_attempt_made=false
ssh_used=false
remote_transfer=false
remote_replay_authorized=false
staging_database_write=false
live_send=false
Task14_acceptance=false
Task15_authorized=false
```

The new candidate remains local-only. No transfer or remote replay is
authorized, and no replay DB, acceptance report or merge plan exists. See
`.superpowers/sdd/task-18-zero-page-budget-checkpoint-replay-report.md`.

### Task 19: Task 18 SHA-Versioned Remote Replay

**Boundary:** Exact Task 18 candidate transfer and one staging replay with
network disabled. No Provider request, full validation, production merge, Git
push or DingTalk.

- [x] Transfer the exact manifest SHA
  `c6d289329443a92ed59c5849fa9fbfe15afc854df709497351c1b7003fd9b2dc`
  bundle to an independent SHA-versioned directory.
- [x] Bind the frozen source DB, exact 725-file raw tree, production baseline and
  evidence outputs before creating the permanent one-shot guard.
- [x] Run exactly one digest-pinned `--network none` staging replay.
- [x] Verify source/target fingerprints, Provider/delivery state, integrity,
  sidecar cleanup and production boundary after replay.

Result on 2026-07-13:

```text
evidence_grade=L4-authorized-live
staging_only
status=complete
stop_reason=replay_complete
fingerprints_equivalent=true
replay_database_published=true
replay_database_sha256=3504190ab2b80ad1a003da27574455802f4184499eeaa7d458a6b771c3a8c638
provider_call=false
provider_attempt_made=false
production unchanged
live_send=false
Task14_acceptance=false
Task15_authorized=false
```

Task 19 proves deterministic network-disabled replay only. The frozen source is
still `partial/budget_exhausted`; formal full validation was not run and no
acceptance report or merge plan was created. See
`.superpowers/sdd/task-19-remote-replay-report.md`.

### Task 20: Local Verification Complete

**Boundary:** Local source, fixtures, tests, documentation, independent review
preparation and release-manifest preparation only. No SSH, remote transfer or
reindex, Provider request, production merge, Git push or DingTalk.

- [x] Add append-only budget-extension and hydration-resume ledgers
  with exact authorization SHA binding and fail-closed chain checks.
- [x] Add discovery/hydration budget separation, round-robin discovery
  and absolute per-lane page ceilings for a separately authorized continuation.
- [x] Add an offline `reindex-discovery` phase that binds the release
  manifest, source DB SHA, raw archive, target DB and report paths.
- [x] Complete focused RED-to-GREEN verification, including source/target SQLite
  sidecar and mutation boundaries plus multi-lane chronological provenance.
- [x] Complete the full serialized offline regression and syntax checks.
- [x] Obtain independent review and refresh the exact 22-file release manifest.

Local verification evidence:

```text
evidence_grade=L2-fixture-or-dry-run
local_only
production unchanged
provider_call=false
provider_attempt_made=false
ssh_used=false
remote_transfer=false
remote_reindex_authorized=false
database_write=local-test-only
staging_database_write=false
live_send=false
focused_tests=PASS
combined_regression=243/243 OK
validation_replay_reindex_suite=108/108 OK
offline_full_suite=445/445 OK
reviewed_files=22/22
independent_review=PASS_NO_P0_P1
local_verified_manifest_sha256=347c6ede1fe36852509dffe051fa7bf2b4d0c1e24ead8dda1af085bc44ff9d94
Task14_acceptance=false
Task15_authorized=false
Task21_authorized=false
Task22_authorized=false
```

Task 20 local verification is complete. Its machinery does not complete
historical collection and does not authorize either of the following tasks. See
`.superpowers/sdd/task-20-budget-extension-and-discovery-reindex-report.md`.

### Task 21: SHA-Versioned Remote Discovery Reindex

**Boundary:** Owner authorized one exact new-manifest bundle transfer and at
most one staging `reindex-discovery` execution with network disabled. That
single attempt has been consumed. No Provider request, full validation,
production merge, Git push or DingTalk was authorized.

- [x] Approve the final Task 20 manifest SHA and exact source DB/raw tree inputs.
- [x] Install the bundle under a new independent SHA-versioned directory without
  changing any historical bundle.
- [x] Create a permanent SHA/input-bound one-shot guard and run at most one
  digest-pinned `--network none` reindex.
- [x] Record the failure report and postflight hashes and prove Provider ledger,
  source, raw archive, delivery and production state are unchanged.

Task 21 returned exit code `1`, `failed/strict_discovery_schema_unknown`. No
target DB was published. Failure report SHA is
`9de8ca1170a9479d269fc2f6ab2421513b0cc0a01a52d530658d4e07a8ee1a62`;
postflight SHA is
`8bf8746bd0b8e29270258d2dd8abed42367824ec471947c50d658c4026dbf9b4`,
with every boundary invariant true. Read-only diagnosis found `35/670` legacy
pages rejected by the strict whole-payload wrapper uniqueness rule. The
permanent guard is consumed. Task 21 is closed as `failed_closed`, not as
full-coverage acceptance. See
`.superpowers/sdd/task-21-remote-reindex-report.md`.

The next safe batch is separately authorized local RED-to-GREEN compatibility
work, full offline regression, independent review and a new reviewed manifest.
Any second remote reindex requires a new one-shot path/guard and explicit owner
authorization.

### Task 21R: Local Legacy-Wrapper Compatibility Repair

**Boundary:** Owner approved local-only, single-agent repair. No SSH, remote
transfer, Provider request, production merge, Git push or DingTalk was
authorized. The explicit no-subagent instruction means this task has primary
agent self-review but no independent review.

- [x] Reproduce the exact reviewed telemetry and SearchCrosspost failures with
  RED fixtures.
- [x] Accept only `SearchPost` and `SearchCrosspost` content wrappers and only
  the exact nested `SearchTelemetryTrackingContext` metadata shape.
- [x] Retain fail-closed tests for unknown, drifted and misplaced `post`
  wrappers.
- [x] Add a source-SHA-bound, immutable read-only corpus audit reporting strict
  pass, wrapper, occurrence, payload, candidate and first-provenance evidence.
- [x] Run focused, related and serialized full regression and issue a new
  canonical manifest candidate.
- [x] Run the new audit against the real `670`-artifact corpus. It failed
  closed on exactly two crosspost-root lineage wrappers.
- [x] Enforce the exact gate: because the audit did not exact-pass, create no
  staging root or guard and do not invoke the reindex runner.

Local evidence: reindex `26/26`, related regression `200/200`, complete-runtime
full suite `452/452`, canonical reviewed-file map `22/22`, candidate manifest
SHA
`88f3d58c89980ed0c685796c340c6752c11f5394e61409f6beeb8a4303b3938f`.
The real DB/raw corpus was not accessed, so these values remain required remote
gate expectations rather than current Task 21R results: `670/670` artifacts,
`241/2` SearchPost/SearchCrosspost, `243` recognized, `238/5/0`
eligible/outside/invalid, zero payload mismatch and exact candidate/provenance
parity. See
`.superpowers/sdd/task-21r-legacy-wrapper-compatibility-report.md`.

```text
evidence_grade=L2-fixture-or-dry-run
local_only
production unchanged
provider_call=false
provider_attempt_made=false
ssh_used=false
remote_transfer=false
real_corpus_gate_executed=false
staging_reindex_attempted=false
database_write=local-test-only
live_send=false
independent_review=false
second_remote_reindex_authorized=false
Task22_authorized=false
```

### Task 21S: Real-Corpus Crosspost Root Lineage Repair

**Boundary:** The approved Task 21R remote batch installed manifest
`88f3d58c89980ed0c685796c340c6752c11f5394e61409f6beeb8a4303b3938f`
but the read-only real-corpus audit failed closed on exactly two
`SearchCrosspost.post.crosspostRoot={"post": ...}` lineage wrappers. No staging
root, attempt guard or reindex output was created. The owner then separately
approved manifest
`44935d6a1cacdfa6e6a5694cc9178a850f40ec770737531c13243fa00a1906e9`,
bundle SHA
`19aa332eb49757b46bb6f44b78b96887df8aa8dcbc66f5bf6811b95199b00e8e`,
one original-corpus read-only audit and, only after an exact gate, at most one
new `--network none` staging reindex. Provider, production merge, Git push and
DingTalk remained prohibited.

- [x] Prove the raw-tree permission failure was caused by `--cap-drop ALL` and
  that only `DAC_READ_SEARCH` restores read-only traversal.
- [x] Reproduce the exact crosspost-root ambiguity with a RED test.
- [x] Allow only the exact single-key lineage wrapper without adding a second
  discovery occurrence; retain strict rejection for extra keys and unknown
  wrappers.
- [x] Pass focused parser tests, read-only audit/reindex integration and the
  serialized full suite (`454/454`).
- [x] Generate canonical manifest
  `44935d6a1cacdfa6e6a5694cc9178a850f40ec770737531c13243fa00a1906e9`
  and deterministic bundle
  `19aa332eb49757b46bb6f44b78b96887df8aa8dcbc66f5bf6811b95199b00e8e`.
- [x] Obtain explicit approval for the new manifest/bundle and a new SHA
  directory.
- [x] Rerun the original-corpus read-only gate; only an exact pass may create a
  fresh frozen staging root and consume one new network-none reindex attempt.
- [x] Exact-pass `670/670`, wrapper `241/2`, recognized `243`,
  eligible/outside/invalid `238/5/0`, zero payload mismatch and exact
  candidate/provenance parity.
- [x] Atomically freeze the independent staging root and invoke the guarded
  runner exactly once.
- [x] Complete the network-none reindex and fresh postflight without changing
  source/raw/production, Provider ledger or delivery state.

Task 21S result on 2026-07-13:

```text
evidence_grade=L4-authorized-live-staging
status=complete
stop_reason=reindex_complete
target_database_sha256=2046e908dd29389fa56189184a20c17dfc53c41e7932e7781250c38a3370e3d9
preflight_sha256=a24a8c00097d116474dcad999d0675d5cfdb681828fff817ea443703495ea5b9
audit_sha256=6835a70c4bf9bce97eeded47c5f0e91e9c1b68d4bc6bd44e06547f749ff5d06b
result_report_sha256=af68d9479dae54445c72e3b100300c561151c63a1003af0446bea12c3895e4b8
postflight_sha256=0c902c15d9965738173728b020f995850b8b54f85de2b52bebd307e2f11e18e6
staging_reindex_attempt_count=1
postflight_invariants=14/14
postflight_success_checks=9/9
provider_call=false
provider_attempt_made=false
database_write=staging-reindex-only
production unchanged
live_send=false
Task22_authorized=false
```

This closes the strict discovery reindex of the existing archive, not the full
historical collection. The source remains bounded by the consumed `670/670`
Provider budget; remaining discovery lanes and hydration still require Task 22
authorization and later replay/full validation.

See `.superpowers/sdd/task-21s-crosspost-root-lineage-report.md`.

### Task 22: Provider Continuation Under Exact Budget Authorization

**Boundary:** Pending a second, separate owner authorization for a canonical
budget-extension packet. The consumed Task 21 authorization does not authorize
Task 22. Production merge, Git push and DingTalk remain prohibited.

The packet must exact-bind the run ID, current reviewed release-manifest SHA,
reviewed probe SHA, approved source/reindexed DB SHA, current request count and
maximum (`670/670` before the first extension), new cumulative maximum,
discovery request ceiling, positive hydration reserve, subreddit-sweep choice,
required-lane hash, ordered absolute lane ceilings and their canonical hash.
Its own raw-file SHA must be separately reviewed and approved.

- [x] Generate the canonical authorization packet and reproduce its hashes and
  budget arithmetic with two primary-agent local contract calculations.
- [ ] Obtain an independent human/agent review if the owner requires one; none
  was used in this single-agent batch.
- [x] Obtain explicit approval of the Task 22A packet SHA and every numeric/scope
  value; the subsequent remote preflight rejected that packet before execution.
- [x] Reproduce the Task 22A no-forward-room failure against the exact remote
  source and generate a corrected Task 22C candidate.
- [ ] Obtain explicit approval of the Task 22C packet SHA and every new
  numeric/scope value.
- [ ] Execute only the bounded collect continuation and stop again on budget,
  schema, cursor, Provider or ledger failure.
- [ ] Preserve immutable evidence for every continuation; do not infer full
  acceptance from a successful Provider phase.

Task 22A local candidate on 2026-07-14:

```text
packet_sha256=6fbec55efdd506fbfcb2376f6bbb47bbca5e7d9ede914caf7542ca6e004a106f
expected_source_database_sha256=2046e908dd29389fa56189184a20c17dfc53c41e7932e7781250c38a3370e3d9
expected_provider_requests=670/670
discovery_request_ceiling=699
hydration_request_reserve=779
new_max_provider_requests_total=1478
extension_request_cap=808
required_lanes_sha256=ac05c4ff299332c74af2c14b8dc52df510f787619c6c532b656443e737f8a817
lane_page_ceilings_sha256=4cbba1166cf6ed39cf2da5a6ce1086ed8a9cb19f4cb42d8dff209b8ae8f2fba9
related_regression=106/106
full_suite_exit_code=0
full_suite_discovered_tests=454
packet_authorized=false
provider_call=false
remote_transfer=false
production unchanged
```

This candidate gives each of the `29` unstarted lanes one calibration page and
reserves the remainder for hydration. The `145` new-candidate and `383`
total-candidate values are planning estimates, not hard result bounds; the
packet guarantees bounded spend and fail-closed stopping, not completion.
See `.superpowers/sdd/task-22-budget-extension-authorization-report.md`.

Task 22B remote preflight on 2026-07-14:

```text
authorized_task22a_packet_sha256=6fbec55efdd506fbfcb2376f6bbb47bbca5e7d9ede914caf7542ca6e004a106f
remote_preflight_status=blocked
stop_reason=budget_extension_checkpoint_state_mismatch
first_lane_remote_state=partial/budget_exhausted/page_670
first_lane_authorized_ceiling=670
remote_transfer=false
staging_created=false
provider_collect_invocation_count=0
provider_call=false
production unchanged
```

Task 22C corrected candidate:

```text
packet_sha256=4b969be4af4abf343e0dac093f4c8465ef867981009b1a5180787f318f3da24c
first_lane_page_contract=670->671
discovery_request_ceiling=700
hydration_request_reserve=789
new_max_provider_requests_total=1489
extension_request_cap=819
lane_page_ceilings_sha256=b5fee135d65c9d8bf7c7c5710cd1fd55c2063730407ab05d848fffe10d2fee0f
exact_remote_ephemeral_checkpoint_contract=true
related_regression=106/106
packet_authorized=false
provider_call=false
```

See `.superpowers/sdd/task-22b-remote-preflight-report.md`.

Task 22C was later authorized and executed once. Its `32/32` new Provider
attempts succeeded, but collect stopped `partial/candidate_failures` on two
previously unreviewed strict shapes. See
`.superpowers/sdd/task-22c-remote-execution-report.md`.

### Task 23: Reviewed Parser Repair and Fresh-Source Validation Batch

**Boundary:** Task 22C staging is evidence only. Do not migrate or continue it.
Use a fresh copy of Task 21S DB SHA
`2046e908dd29389fa56189184a20c17dfc53c41e7932e7781250c38a3370e3d9`
and the exact `725`-file raw tree.

- [x] Add RED-to-GREEN tests and strict support for the reviewed subredditV3
  organic, title-thumbnail and terminal-empty shapes.
- [x] Add the reviewed terminal-comments cursor exception only for
  `hasNextPage=false`, plus replay/reindex coverage and negative tests.
- [x] Pass focused, Provider, validation, CLI and complete-runtime regression.
- [x] Generate reviewed manifest, deterministic bundle and canonical fresh
  Task 21S-source authorization packet.
- [ ] Obtain exact owner approval of all three new SHA values.
- [ ] Transfer only the exact bundle to a new SHA-versioned directory and run a
  read-only source/raw/production preflight.
- [ ] Only on an exact preflight pass, create a fresh staging copy and execute
  at most one guarded collect invocation.
- [ ] Preserve immutable result/postflight evidence and stop on any contract,
  cursor, Provider, ledger or scanner failure.

Task 23 local candidate:

```text
release_manifest_sha256=edc6ec9b44871d9a93e9a77ca2fdaf3f91a7ede2e282d48bd3f6d1bdc91e9c51
bundle_sha256=de66baf3c76f9a69289feb43045de9c3cf7b3f4ed1dc5dc06f9fc6b89664a01e
packet_sha256=ab5386e7d2022dd1a354569bd5fa0abfadcd741549902d4cae53b90d8f17daa1
expected_provider_requests=670/670
new_max_provider_requests_total=1200
discovery_request_ceiling=700
hydration_request_reserve=500
extension_request_cap=530
full_suite=529/529
packet_authorized=false
provider_call=false
```

Complete historical collection still requires every required discovery lane
and hydration candidate to close, followed by separately admitted replay/full
validation before any Task 15 merge plan can exist. See
`.superpowers/sdd/task-23-parser-contract-repair-report.md`.

### Task 24: Archive Recovery and Existing-Budget Resume Contract

**Boundary:** local-only implementation. No SSH, remote replay, Provider call,
production merge, Git push or DingTalk.

- [x] Add exact reviewed nonempty subreddit mirror/cell fixtures and negative
  drift tests.
- [x] Preserve parseable nonterminal comments as `unresolved_more` and isolate
  candidate failures.
- [x] Add atomic source/raw-pinned offline recovery into a fresh target, with no
  target on failure and unchanged Provider ledger.
- [x] Add an append-only authorization ledger for continuing within an existing
  unexhausted cumulative budget.
- [x] Add CLI and network-none wrapper contracts for recovery and continuation.
- [x] Pass related and complete-runtime regression; publish a new canonical
  manifest, deterministic bundle and Task 25 offline-only packet candidate.

Task 24 local candidate:

```text
release_manifest_sha256=dbaf6186d45bd5a52e08177dd60ffa00f72b7e5f4f2661a38a3acd4dee6181ad
bundle_sha256=28eb1847ba9250ab1839cd6ca43d6416fc9eeba29d5e29bb3341a20c2c18e034
task25_packet_sha256=8821d64a927e5c0d83a774dbab0301cfee6bf394101dac45067cd5683cd011f5
full_suite=613/613
provider_call=false
historical_coverage_complete=false
```

Task 25 may execute only the exact-approved network-none offline recovery. A
Provider continuation packet must be generated from the resulting target SHA
and state and separately approved.

### Task 25: Remote Network-None Recovery

**Boundary:** exact owner-approved, one recovery invocation, no Provider,
production merge, Git push or DingTalk.

- [x] Exact-match packet `8821d64a...11f5`, manifest `dbaf6186...181ad`,
  bundle `28eb1847...e034`, source DB/raw, Provider `702/1200`, 252 candidates
  and nine batches.
- [x] Exact-pass remote read-only preflight and final admission; install into
  fresh SHA-versioned code/operation paths.
- [x] Consume exactly one permanent-guarded `--network none`
  `recover-collection` invocation.
- [x] Preserve immutable failure evidence and run a failure-aware read-only
  postflight.
- [ ] Publish a recovered target database.

Actual result:

```text
recovery_exit_code=1
status=failed
stop_reason=strict_discovery_page_chain_invalid
target_database_published=false
provider_request_count=702/1200
provider_call=false
provider_attempt_made=false
failure_postflight=21/21
production unchanged
```

The 14 schema-drift lanes have exact sequential extra pages, but their
checkpoint request numbers are `686-689,691-700`; none equals the final
manifest count `702`. The current recovery rule requires that equality and
therefore rejects all 14. See
`.superpowers/sdd/task-25-remote-recovery-report.md`.

### Task 26: Per-Lane Recovery Attempt Binding Repair

**Boundary:** exact owner-authorized local-only execution. No SSH, remote
recovery, Provider, production merge, Git push or DingTalk occurred.

- [x] Add a RED real-shape fixture where multiple schema-drift checkpoint
  request numbers precede the final cumulative manifest count.
- [x] Bind each checkpoint to its exact terminal successful Provider attempt
  and expected endpoint; keep missing, failed, out-of-range and endpoint drift
  fail-closed.
- [x] Add a failure-aware postflight contract that preserves a failed recovery
  as failed while proving no target/source/Provider/production residue.
- [x] Run focused, related and complete-runtime regression.
- [x] Publish a new release manifest, deterministic bundle and separately
  reviewable one-shot recovery packet.

Actual result: focused reindex/recovery `38/38`, related bundled-runtime
regression `407/407`, complete bundled-runtime suite `634/634`, and local
release review `19/19`. Release manifest SHA is
`d375b127d1e0ac282b5c714f8882e0c8db6a0792cc703273fb50e93ba2b38d17`;
deterministic 24-file bundle SHA is
`a265dc1f1334e71d592d2cc722f946ba2d1b5ed39336ee6d02bde6a1b8dadfed`;
Task 27 packet SHA is
`66f666a2183e76194abc4376ae867e3ac2ee54ca8ac1885de048f1af1c01c6b3`.
See `.superpowers/sdd/task-26-per-request-recovery-contract-report.md`.

Task 25's guard is consumed. Task 26 does not authorize a second remote
recovery or Provider continuation.

### Task 27: Remote Network-None Recovery

**Boundary:** requires separate exact owner authorization. Provider,
production merge, Git push and DingTalk remain prohibited.

- [x] Transfer the Task 26 manifest, deterministic bundle and Task 27 packet to
  a fresh manifest-SHA-versioned directory.
- [x] Exact-pass read-only preflight on source DB `f53ddf6f...ab5cb`, raw
  `757 / 8ffcc30d...339e`, Provider `702/1200`, 252 candidates, nine batches
  and all 14 per-request succeeded-attempt/endpoint bindings.
- [x] If and only if preflight remains stable, execute at most one guarded
  `--network none` recovery into a new staging target. Do not reuse the Task 25
  guard.
- [x] Run failure-aware postflight for either success or failed-closed outcome;
  preserve source/raw/Provider/production and publish no success claim on a
  failed recovery.

Actual result: preflight `7e657b94...01f8c`, admission `9e88981a...1cca2`, one
recovery invocation `rc=0`, result/report `465b4aa6...7de19`, target DB
`56d74951...8570a4`, and final postflight `95bad68f...5bb93`. The target has
258 pending candidates and seven missing batch members; Provider remains
`702/1200`. See `.superpowers/sdd/task-27-remote-recovery-report.md`.

Task 27 is complete as isolated staging recovery. Historical coverage is not
complete and Provider continuation requires a new exact authorization.

### Task 28: Provider Continuation Against Recovered Staging

**Boundary:** requires a new reviewed packet and exact owner authorization.
No production merge, Git push or DingTalk.

- [x] Freeze target DB SHA `56d74951...8570a4` and read-only candidate/batch
  inventory (`258` pending candidates, seven missing batch members).
- [x] Produce a new packet with exact recovered-target, candidate-set,
  remaining-budget and endpoint/attempt bindings; do not reuse Task 27's guard.
- [x] Obtain separate exact owner authorization for the corrected packet
  `5b0ff5af...4cd63` (the initial `a9fff5d7...43c68` packet was rejected
  before any Provider call).
- [x] After separate approval, execute bounded Provider continuation with
  its own one-shot guard and failure-aware postflight.

Task 28 local contract repair artifacts:

- release manifest SHA:
  `214577e596caffb7fe99495859b5b04c6e01771451faab7853d742e68b47136f`
- deterministic bundle SHA:
  `cf5ad3d24378016b9f6aef15fad1a90ede48f9a2da03c55877ef530a6c73a09c`
- candidate packet SHA:
  `5b0ff5afc5bac1df7907bcd8fd2fa2a3d335918f97471c378d4d405db194cd63`
- CLI resume packet SHA:
  `031e4d961e757067419fcbcc91ad20dcc65997e46b168fb98731b6c710d5002d`

At candidate-generation time the new packet was not yet authorized. It was
later authorized and admitted to new staging; the resulting one-shot
continuation is recorded below.

Task 28 execution result: the corrected packet was authorized once and ran in
isolated staging. It completed 969 successful Provider requests out of 1200,
then stopped at `candidate_failures` with 242 hydrated, 12 failed and 5
excluded candidates. Target integrity/FK postflight passed; production,
source DB and raw archive remained unchanged. Historical coverage is not
complete; see `.superpowers/sdd/task-28-provider-continuation-report.md`.

### Task 15: Production Merge Under Separate Authorization

**Boundary:** Requires reviewed acceptance/merge hashes, backup path, maintenance window, no concurrent daily collector, immutable staging/production database paths for the entire command, and explicit production-write approval. Before any future production authorization, add or independently verify connection-bound inode protection for `_open_merge_database`; path-level stat/hash alone does not close an adversarial `P -> Q(open) -> P` ABA race. Until that hardening is accepted, any concurrent path mutation is an absolute stop condition and `merge-production` remains unauthorized.

- [ ] **Step 1: Execute reviewed insert-only merge**

Derive expected production SHA-256 from the reviewed plan. Require env and flag gates. Backup first, then one transaction:

```bash
: "${APPROVED_ACCEPTANCE_REPORT_SHA256:?owner-reviewed acceptance report SHA-256 is required}"
: "${APPROVED_MERGE_PLAN_FILE_SHA256:?owner-reviewed merge-plan file SHA-256 is required}"
: "${APPROVED_PRODUCTION_SHA256:?owner-reviewed production SHA-256 is required}"
REDDIT_VOC_ENABLE_PRODUCTION_MERGE=1 \
python3 -m reddit_voc.backfill_cli merge-production \
  --run-id backfill_momcozy_20250101_20260711 \
  --staging-database /app/data/backfill/backfill_momcozy_20250101_20260711/reddit_voc_backfill.sqlite3 \
  --production-database /app/data/reddit_voc_daily.sqlite3 \
  --acceptance-report /app/data/backfill/backfill_momcozy_20250101_20260711/reports/backfill_momcozy_20250101_20260711-acceptance.json \
  --expected-acceptance-report-sha256 "$APPROVED_ACCEPTANCE_REPORT_SHA256" \
  --merge-plan /app/data/backfill/backfill_momcozy_20250101_20260711/reports/backfill_momcozy_20250101_20260711-merge-plan.json \
  --expected-merge-plan-sha256 "$APPROVED_MERGE_PLAN_FILE_SHA256" \
  --backup-database /app/data/backups/reddit_voc_daily.pre-backfill_momcozy_20250101_20260711.sqlite3 \
  --expected-production-sha256 "$APPROVED_PRODUCTION_SHA256" \
  --output /app/data/backfill/backfill_momcozy_20250101_20260711/reports/backfill_momcozy_20250101_20260711-merge-result.json \
  --authorize-production-write
```

Expected: updated=0, deleted=0, conflicts recorded, old counts never decrease, delivery unchanged.

- [ ] **Step 2: Run production read-only postchecks**

The merge command writes `$RUN_ID-merge-result.json`. With production opened `mode=ro`, verify its backup hash, planned versus actual table deltas, old-run counts, entity-to-run/raw lineage, target bounds, dependency parity, delivery delta zero, and absence of a live-send artifact. Any mismatch is a failed merge acceptance even if the transaction exited zero.

- [ ] **Step 3: Confirm no July 11 catch-up run is required**

The original run's fixed `effective_end_utc=2026-07-11T16:00:00Z` already equals the approved requested-window end, so this plan has no remaining July 11 interval and must not create the obsolete `backfill_momcozy_20260711_catchup` run. Any later extension is a new separately specified run with its own window, Provider budget, staging validation, and merge authorization; never mutate the original run.

- [ ] **Step 4: Update final evidence records**

Keep local tests, seed, probe, full staging, and merge as separate proof layers. This plan has no catch-up or DingTalk phase.
