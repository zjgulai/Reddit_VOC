# Reddit VOC V3 Complete System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将已确认的 V3 书面规格实现为可复算的 Reddit 全量身份池、双粒度 VOC、Momcozy 品牌健康与内容诚信体系、日报/周报/月报、案例/画像/导出，以及保持生产隔离的本地候选。

**Architecture:** 新增窄职责 V3 domain modules 和独立 builder/validator，不把 Excel、指标和治理逻辑继续堆入现有大型 snapshot 脚本。数据路径固定为 immutable source manifest → workbook import → canonical snapshot → VOC/facts/eligibility → metrics/integrity/casebook → reports/public projection/export bundle → local candidate；React 只消费经过 SHA 校验的预计算制品。

**Tech Stack:** Python 3.11+、stdlib、openpyxl 3.1+、现有 JSON/JSONL 静态制品、React 19、TypeScript 6、Vite 8、Vitest 3、Recharts 3、现有 Playwright/container harness。不得新增依赖。

## Global Constraints

- 唯一产品与数据目标是 `docs/superpowers/specs/2026-07-16-reddit-voc-complete-system-integrity-casebook-design.md`；V2 只保留该规格显式继承项。
- 依赖顺序固定为 `1→2→3→4→5/6→7→8→9`；前端不得先于数据合同自行定义指标。
- 所有可解析 Reddit ID 进入 canonical/provenance；`canonical_identity`、`analysis_ready`、`metric_eligible` 分层。
- 帖子形成 `post_voc`；评论只有真实根帖关联后形成 `comment_context_voc`；父帖情感、问题、严重度、推荐与画像不得复制到评论。
- 12,720 完整范围来源可进入 Momcozy 单期内部指标，但在 query/coverage/retrieval hashes 对齐前为 `provisional_source_profile`，不得生成跨品牌能见度、SOV、趋势或 RV-IN-05。
- 814 行负向来源只作 evidence；Base 独立 anchor 重合项按 Base 资格处理。
- 显式 automation 保留在 canonical 与审计导出，但必须在所有 organic VOC/品牌指标前写入 `excluded_reason=explicit_automation`。
- 品牌健康指数只含口碑健康、产品体验、推荐信任、风险韧性四维；内容诚信 C/I 独立展示。
- 38 seed 与 12 legacy 内容及 SHA 不变；默认参考案例只展示 verified 且 TTL 有效的条目。
- 公开站点无登录、无私有作者 pseudonym、无运行时案例搜索、无浏览器写数据。
- 正常 partial/provisional/unavailable 不使用 error 感叹号；真实 artifact failure 继续 fail closed。
- 不读取或输出 `.env`、私钥、token；`provider_call=false`、`database_write=false`、`remote_write=false`、`deploy=false`、`live_send=false`、`production unchanged`。
- 项目契约禁止未获 Owner 明确指令的 commit，并默认不创建 worktree；每个任务以 RED/GREEN、独立 validator、计划账更新为检查点。

---

### Task 1: Freeze and validate the V3 source manifest

**Files:**
- Create: `config/source_selection/reddit-voc-add-data-20260715-v1.json`
- Create: `config/schemas/reddit-voc-source-manifest-v1.schema.json`
- Create: `src/reddit_voc/v3_source_manifest.py`
- Create: `scripts/build_reddit_v3_source_manifest.py`
- Create: `scripts/validate_reddit_v3_source_manifest.py`
- Test: `tests/test_reddit_v3_source_manifest.py`

**Interfaces:**
- Produces: `load_source_manifest(path: Path, project_root: Path) -> SourceManifest`
- Produces: `SourceManifest.source(source_snapshot_id: str) -> SourceContract`
- Produces: canonical `manifest.json` with exact source bytes/SHA/sheet/header/row contracts and Base A2 lineage SHA.

- [x] **Step 1: Write the failing source-policy tests**

```python
def test_owner_attested_unknown_is_single_period_momcozy_only(tmp_path: Path) -> None:
    manifest = load_source_manifest(_manifest(tmp_path), tmp_path)
    source = manifest.source("reddit_add_data_full_20260715")
    assert source.query_profile_status == "owner_attested_unknown"
    assert source.allowed_metric_families == ("momcozy_internal_single_period",)
    assert "cross_brand_visibility" in source.blocked_uses
    assert "trend" in source.blocked_uses

def test_negative_selected_source_cannot_enter_business_metrics(tmp_path: Path) -> None:
    value = _value(tmp_path)
    value["sources"][1]["allowed_metric_families"] = ["momcozy_internal_single_period"]
    with pytest.raises(SourceManifestError, match="negative-selected"):
        load_source_manifest(_write(value), tmp_path)
```

- [x] **Step 2: Run RED**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_reddit_v3_source_manifest.py -q`

Expected: collection fails because `reddit_voc.v3_source_manifest` does not exist.

- [x] **Step 3: Implement the minimal typed contract and canonical builder**

```python
@dataclass(frozen=True)
class SourceContract:
    source_snapshot_id: str
    relative_path: PurePosixPath
    sha256: str
    bytes: int
    expected_sheet: str
    expected_dimension: str
    expected_headers: tuple[str, ...]
    expected_data_rows: int
    selection_class: str
    query_profile_status: str
    allowed_metric_families: tuple[str, ...]
    blocked_uses: tuple[str, ...]

@dataclass(frozen=True)
class SourceManifest:
    dataset_id: str
    base_dataset_version: str
    base_lineage_manifest_sha256: str
    sources: tuple[SourceContract, ...]

    def source(self, source_snapshot_id: str) -> SourceContract:
        return next(item for item in self.sources if item.source_snapshot_id == source_snapshot_id)
```

The config must bind the two workbook hashes
`136bbfc56d27bdcb9dde7a34894e722c09abba13209e357d615711bebd00eabb` and
`331f1dce592b622854359cb9a5ed8329913cb77d94b66fd2c5ac3c8372f7a5b5`, 21 exact headers,
dimensions `A1:U12721`/`A1:U815`, rows `12,720`/`814`, and Base lineage SHA
`de8b504da8c50588c24b3b2a9a68244864bf8ae4bba20450fcf91c3cd40d6443`.

- [x] **Step 4: Run GREEN and real-file validation**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_reddit_v3_source_manifest.py -q
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/validate_reddit_v3_source_manifest.py \
  --manifest config/source_selection/reddit-voc-add-data-20260715-v1.json \
  --project-root .
```

Expected: tests pass and validator reports both files, `source_rows=13534`, `production_unchanged=true`.

- [x] **Step 5: Record the task result without committing**

Update `.kiro/plan/progress.md` with test command, exact counts, manifest SHA and `production unchanged`.

### Task 2: Import both workbooks into a private, deterministic ledger bundle

**Files:**
- Create: `src/reddit_voc/v3_workbook_import.py`
- Create: `scripts/import_reddit_add_data_workbooks.py`
- Test: `tests/test_reddit_add_data_workbooks.py`

**Interfaces:**
- Consumes: `SourceManifest` from Task 1; Base public/private roots are derived from its two verified relative paths, never supplied as a drifting CLI override.
- Produces: `build_workbook_import(manifest, output_root, project_root=...) -> WorkbookImportSummary`.
- Produces: `posts.jsonl`, `comments.jsonl`, `row-outcomes.jsonl`, `parent-link-ledger.jsonl`, `conflict-ledger.jsonl`, `manifest.json`.

- [x] **Step 1: Write RED fixtures for bad worksheet dimension, URL shapes, casefold types and floating dates**

```python
@pytest.mark.parametrize(
    ("url", "kind", "post_id", "comment_id"),
    [
        ("https://reddit.com/r/x/comments/abc123", "post", "abc123", None),
        ("https://reddit.com/r/x/comments/abc123/title", "post", "abc123", None),
        ("https://reddit.com/r/x/comments/abc123/comment/def456", "comment", "abc123", "def456"),
        ("https://reddit.com/r/x/comments/abc123/title/def456", "comment", "abc123", "def456"),
    ],
)
def test_parse_reddit_identity(url, kind, post_id, comment_id):
    assert parse_reddit_identity(url, kind) == RedditIdentity(post_id, comment_id)

def test_day_precision_never_creates_midnight_utc():
    row = normalize_row(
        {
            "舆情ID": "source-row-1",
            "舆情链接": "https://reddit.com/r/x/comments/abc123",
            "内容类型": "Forum Post",
            "标题": "Momcozy sample post",
            "发布时间": "2025-07-28 00:00:00",
        },
        source=SOURCE,
        row_ordinal=2,
    )
    assert row.source_calendar_date == "2025-07-28"
    assert row.event_time_precision == "day"
    assert "source_cutoff_utc" not in row.as_dict()
```

- [x] **Step 2: Run RED**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_reddit_add_data_workbooks.py -q`

Expected: fails because importer functions are absent.

- [x] **Step 3: Implement deterministic parsing and row dispositions**

```python
TERMINAL_PRIORITY = (
    "duplicate",
    "exact_base_overlap",
    "identity_conflict",
    "unresolved_parent",
    "incomplete_text",
    "net_new_text_ready",
)

def parse_reddit_identity(url: str, entity_type: str) -> RedditIdentity:
    path = unquote(urlsplit(url).path).casefold().rstrip("/")
    match = re.search(r"/(?:r/[^/]+/)?comments/([a-z0-9]+)(?:/(.*))?$", path)
    if not match:
        raise WorkbookImportError("reddit identity missing")
    post_id, tail = match.group(1), (match.group(2) or "")
    if entity_type == "post":
        return RedditIdentity(post_id=post_id, comment_id=None)
    tokens = [token for token in tail.split("/") if token and token != "comment"]
    if not tokens or not re.fullmatch(r"[a-z0-9]+", tokens[-1]):
        raise WorkbookImportError("comment identity missing")
    return RedditIdentity(post_id=post_id, comment_id=tokens[-1])
```

Use `load_workbook(workbook_path, read_only=False, data_only=True)` and assert calculated actual range instead of trusting cached `dimension=A1`. Normalize `内容类型` with `strip().casefold()`.

- [x] **Step 4: Run GREEN on fixtures**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. .venv/bin/python -m unittest tests.test_reddit_add_data_workbooks -v`

Expected: all importer fixture tests pass with deterministic JSONL bytes after input-order shuffle, both Base roles re-opened from the source manifest, conflict-held identities excluded, and Task 2 lifecycle fixed at `candidate_built/pending`.

- [x] **Step 5: Build the real private candidate bundle**

Run:

```bash
test ! -e tmp/reddit-voc-v3/reddit_add_data_20260715_v1/workbook-import-candidate-a1
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. .venv/bin/python scripts/import_reddit_add_data_workbooks.py \
  --source-manifest config/source_selection/reddit-voc-add-data-20260715-v1.json \
  --project-root . \
  --output-root tmp/reddit-voc-v3/reddit_add_data_20260715_v1/workbook-import-candidate-a1
```

Expected manifest counts: source rows `13,534`; distinct posts/comments `2,226/11,305`; duplicate rows `3`; Base overlap `54/738`; net-new identities `2,172/10,567`; terminal disposition sum `13,534`.
`parent-link-ledger.jsonl` has one row per distinct workbook comment (`11,305`), including governed overlap/quarantine states. The candidate remains blocked pending Task 3 independent validation.

### Task 3: Independently validate workbook import and canonical three-state conservation

**Files:**
- Create: `scripts/validate_reddit_add_data_import.py`
- Create: `src/reddit_voc/v3_canonical_identity.py`
- Create: `src/reddit_voc/v3_canonical_fusion.py`
- Create: `scripts/build_reddit_v3_canonical_snapshot.py`
- Create: `scripts/validate_reddit_v3_canonical_snapshot.py`
- Test: `tests/test_validate_reddit_add_data_import.py`
- Test: `tests/test_reddit_v3_canonical_identity.py`
- Test: `tests/test_reddit_v3_canonical_snapshot.py`
- Test: `tests/test_validate_reddit_v3_canonical_snapshot.py`

**Interfaces:**
- Consumes: validated Task 2 bundle and explicit Base manifest SHA.
- Produces: `validate_workbook_import(bundle_root: Path, source_manifest_path: Path, project_root: Path) -> ValidationReceipt` without importing the builder; both Base roots are independently derived from the source manifest.
- Produces: canonical `posts.jsonl`, `comments.jsonl`, provenance/conflict/unresolved ledgers and manifest.

- [x] **Step 1: Write RED tamper and three-state tests**

```python
def test_comment_states_are_mutually_exclusive_and_conserved(bundle: Path) -> None:
    result = validate_canonical_snapshot(bundle)
    assert result.stored_comments == 27_158
    assert result.linked_comments == 20_205
    assert result.unresolved_parent_comments == 6_943
    assert result.quarantined_comments == 10
    assert sum((result.linked_comments, result.unresolved_parent_comments, result.quarantined_comments)) == result.stored_comments

def test_changed_row_outcome_fails_closed(bundle: Path) -> None:
    _mutate_first_jsonl(bundle / "row-outcomes.jsonl", "terminal_outcome", "net_new_text_ready")
    with pytest.raises(ImportValidationError, match="row outcome"):
        validate_workbook_import(bundle, source_manifest_path, base_root)
```

- [x] **Step 2: Run RED**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_validate_reddit_add_data_import.py tests/test_reddit_v3_canonical_identity.py tests/test_reddit_v3_canonical_snapshot.py tests/test_validate_reddit_v3_canonical_snapshot.py -q`

Expected: fails on missing independent validators.

- [x] **Step 3: Implement canonical identity and governed-Base precedence**

```python
class CommentState(StrEnum):
    LINKED = "linked"
    UNRESOLVED_PARENT = "unresolved_parent"
    QUARANTINED = "quarantined"

def canonical_post_id(value: str) -> str:
    bare = value.casefold().removeprefix("t3_")
    if not re.fullmatch(r"[a-z0-9]+", bare):
        raise CanonicalIdentityError("invalid post identity")
    return bare

def merge_text(existing: FieldValue, incoming: FieldValue) -> MergeDecision:
    if existing.value:
        return MergeDecision(existing.value, "governed_base_preserved", incoming if incoming.value != existing.value else None)
    return MergeDecision(incoming.value, "workbook_fill_missing", None)
```

The validator independently parses JSONL, recomputes IDs, row counts, source hashes, state disjointness and all foreign keys; it must not import `v3_canonical_fusion`.

- [x] **Step 4: Run GREEN and validate the real bundle**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_validate_reddit_add_data_import.py tests/test_reddit_v3_canonical_identity.py tests/test_reddit_v3_canonical_snapshot.py tests/test_validate_reddit_v3_canonical_snapshot.py -q
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. .venv/bin/python scripts/validate_reddit_add_data_import.py --bundle-root tmp/reddit-voc-v3/reddit_add_data_20260715_v1/workbook-import-candidate-a1 --source-manifest config/source_selection/reddit-voc-add-data-20260715-v1.json --project-root .
```

Expected: `unaccounted_source_rows=0`, `unaccounted_canonical_identities=0`, and immutable receipt written only after all checks pass.

### Task 4: Materialize post VOC, comment-context VOC and metric eligibility

**Files:**
- Create: `src/reddit_voc/v3_voc_facts.py`
- Create: `src/reddit_voc/v3_metric_eligibility.py`
- Create: `config/analytics/reddit-voc-metric-eligibility-v1.json`
- Create: `scripts/build_reddit_v3_voc_facts.py`
- Create: `scripts/validate_reddit_v3_voc_facts.py`
- Test: `tests/test_reddit_v3_voc_facts.py`
- Test: `tests/test_reddit_v3_metric_eligibility.py`
- Modify: `scripts/build_reddit_site_snapshot.py`
- Modify: `scripts/validate_reddit_site_snapshot.py`

**Interfaces:**
- Produces: `post:<post_id>` and `comment:<comment_id>` VOC records with fielded analysis payload and evidence scope.
- Produces: one eligibility row per `reddit_indicator_id × comparison_side × entity_id`.
- Preserves four separate state vectors: canonical identities, VOC facts, analysis-ready facts and metric-eligible facts; none may be substituted for another.
- Preserves event time as either timezone-bearing `instant/hour` or floating `day`; a day-precision row must keep `source_calendar_date` and must not receive a fabricated midnight UTC timestamp.

- [x] **Step 1: Write RED grain, parent-conflict and subset tests**

```python
def test_one_post_and_n_comments_make_one_plus_n_vocs():
    rows = materialize_vocs(_thread(comment_count=3))
    assert [row.voc_id for row in rows] == ["post:p1", "comment:c1", "comment:c2", "comment:c3"]

def test_parent_persona_and_sentiment_do_not_cross_into_comment():
    comment = materialize_comment_voc(_parent("I am pregnant and angry"), _comment("Which size?"))
    assert comment.analysis_fields["current_comment_body"] == "Which size?"
    assert comment.author_scope == "current_comment_author_only"

def test_metric_sets_obey_subset_contract(ledger):
    assert ledger.numerator_ids <= ledger.denominator_ids <= ledger.eligible_entity_ids
```

- [x] **Step 2: Run RED, implement minimal fielded payloads, then run GREEN**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_reddit_v3_voc_facts.py tests/test_reddit_v3_metric_eligibility.py -q`

Implementation must use canonical JSON UTF-8 bytes, separate `post_title/post_body/current_comment_body`, and reject inconsistent link/permalink/t3 candidates.

- [x] **Step 3: Integrate only the validated V3 bundle into the existing site builder**

Add explicit CLI arguments `--v3-canonical-root`, `--v3-canonical-manifest-sha256`,
`--v3-validation-receipt`, and `--v3-validation-receipt-sha256`. The four arguments are all-or-none;
the builder and validator must reopen both artifacts from the explicit paths and bind the same bytes to the
supplied SHAs. A SHA alone is not a receipt locator. Directory scanning for a “latest” bundle is prohibited.

V3 is a complete canonical union, not a delta. Build it through an isolated V3 branch and the validated
`v3_voc_facts` bridge; do not append its `.record` envelopes to the legacy Base collections. The legacy V1/V2
branch remains byte-compatible. All checks complete before any output collection is mutated.

Task 4 intentionally emits only `reddit_voc_site_state_manifest_v3`: `files={}`,
`artifact_stage=v3_state_vector_only`, `public_projection_complete=false` and `release_candidate=false`.
Explicit automation exclusion, atomic facts, metrics, personas and the governed export/public projection are
owned by Tasks 5–10; emitting five public row files here would expose an incomplete contract and violate that
dependency order. The manifest is therefore a validated private site input, not a renderable site release.

- [x] **Step 4: Verify the integrated state vector**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_reddit_site_v2_fusion.py tests/test_validate_reddit_site_snapshot.py tests/test_reddit_v3_voc_facts.py tests/test_reddit_v3_metric_eligibility.py -q`

Expected: Base V2 regression remains green; V3 fixture has no duplicated post/comment grain; unresolved,
quarantined and text-incomplete identities create no analysis-ready `comment_context_voc`; floating day values
remain stable across process timezones. The facts validator recomputes the design targets (rather than hard-coding
them) and keeps canonical, VOC, analysis-ready and metric-eligible counts distinct.

Actual: focused V1/V2/V3 regression is `95/95` green. The formal a2 state manifest SHA is
`e8c13bea4cd190ca0c9e58a8b731763f1e42531d0058cfc4da72a1141bef8078`; its atomic independent receipt SHA is
`3485a9e35c724cdd35f10742690a6aef6a58e746f1d5e859f78ba0813b496ef7` with
`status=passed_state_vector_only`. The independent gate is P0=0/P1=0/P2=2. P2 debt is retained for
`683–751 MB` observed peak RSS and the absence of a historical full-snapshot golden-byte fixture for V1/V2.

### Task 5: Exclude explicit automation before metrics and build atomic facts/personas

**Files:**
- Create: `config/analytics/reddit-voc-explicit-automation-v1.json`
- Create: `src/reddit_voc/v3_explicit_automation.py`
- Create: `src/reddit_voc/v3_atomic_facts.py`
- Create: `src/reddit_voc/v3_persona_inference.py`
- Create: `config/personas/reddit-voc-persona-cohorts-v3.json`
- Create: `data/reference/reddit-voc-v3/manifest.json`
- Modify: `scripts/build_reddit_personas_snapshot.py`
- Modify: `scripts/validate_reddit_personas_snapshot.py`
- Test: `tests/test_reddit_v3_explicit_automation.py`
- Test: `tests/test_reddit_v3_atomic_facts.py`
- Test: `tests/test_reddit_v3_persona_inference.py`
- Test: `tests/test_reddit_personas_snapshot.py`

**Interfaces:**
- Produces: deterministic `excluded_reason=explicit_automation` while preserving canonical rows.
- Produces: nine atomic fact tables with field/span/hash/status/reason.
- Produces: 82 atomic persona facts, 8 cohort bridge rows and local synthetic avatar bindings.

- [x] **Step 1: Write RED for the frozen automation baseline and P0 governance examples**

```python
def test_explicit_automation_is_retained_but_metric_ineligible(base_comments):
    rows = classify_explicit_automation(base_comments, policy=POLICY)
    assert sum(row.detected for row in rows) == 540
    assert sum(row.was_already_excluded for row in rows) == 112
    assert sum(row.newly_excluded for row in rows) == 428
    assert all(row.canonical_retained for row in rows)

def test_keep_coming_back_is_not_consumer_repurchase(governance_posts):
    facts = build_atomic_facts(governance_posts["1kkvihg"])
    assert not _promoted(facts, "explicit_recommendation")
    assert _promoted(facts, "integrity_allegation")
    assert not _promoted(facts, "consumer_trust_impact")
```

- [x] **Step 2: Run RED, implement deterministic matchers, then run GREEN**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_reddit_v3_explicit_automation.py tests/test_reddit_v3_atomic_facts.py tests/test_reddit_v3_persona_inference.py -q`

The five fixed root posts and three fixed comment IDs must save body-local evidence spans. Shared-keyword, token-boundary and TECH mutual-exclusion failures become `held`, never silent promotions.

- [x] **Step 3: Copy and bind ai_nlp_voc reference assets by SHA**

Copy the frozen persona/mapping/registry/storyline assets into `data/reference/reddit-voc-v3/`, then build a manifest containing original path labels, bytes and the exact SHAs from the V3 spec. Runtime code must consume project-local copies, never absolute paths or symlinks.

- [x] **Step 4: Upgrade persona builder/validator from exactly two to 82+8**

Remove `len(personas) == 2` and single `source_tag_id` assumptions. Validate many-to-many atom→cohort bridge, `assignment_count`, `unique_entity_count`, post/comment scopes, availability status, 8 local avatar assets and one fallback; never label the count as users.

Actual: explicit automation/fixed-governance/persona regression is `47/47` green; the five-table full-corpus
closed-set matcher and independent exact-decision validator are `13/13` green. Reference manifest SHA is
`f899cd2fcb4562b70255515a4ec7c3280060f7e1027e694dd8cd9264f3994bcf`. Persona candidate a3 manifest SHA is
`2389cc1a18d3f085509452441445047b00680c4b789f61c7b429e617ee17a332`; receipt SHA is
`e8a47929acac7120acefb3eb504ce357f75d2200b86ab12f80485bc2e499ed2e`. It is correctly
`passed_candidate_only`, `promotable=false`, pending the governed eight-table signal snapshot. Counts are
23,586 analysis-ready VOCs, 737 excluded automation VOCs, 82 atomic persona definitions, 23,919 persona facts,
9,220 cohort assignments and 6,548 unique content entities; none are claimed as users.

The governed eight-table signal candidate has now also passed its one full independent validation run. Its
manifest SHA is `44c66b198f3dc33873036912c239f89d28fabe36ed2aaacc5662c7686dd4c24a` and receipt SHA is
`135d9f4a78dd772f5feae193783d98f78969d8b68d3cf6bf2b368f6fee98d9db`. It contains 159,044 facts
(15,180 promoted / 143,863 held / 1 rejected) over 22,849 organic VOCs after excluding 737 automation VOCs;
`validated_tables=8`, `unaccounted_facts=0` and `unaccounted_vocs=0`.

Persona a4 has now consumed that exact manifest/receipt and passed full independent replay. Its manifest SHA is
`bc366c0579029e8e1afb3705d8a3865d15cbdff5948634519abc43ea77a6c72b` and receipt SHA is
`784e8b1cfd35368f3407a0cc2d22281c93afa89e6e288ac890f581dda8830816`; it is
`eligible_for_downstream_consumption` and `promotable=true`. All eight cohorts are available: seven stable and
`fit_output_optimizer` directional at 23 content entities. The snapshot contains 9,760 assignments over 6,791
content entities. It loads 12,627 promoted brand/problem/tag facts, injects 5,711, and accounts for all 6,916
facts rejected by the comment direct-evidence gate. These counts remain content evidence, not people.

- [x] **Step 5: Run the persona and automation regression set**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_reddit_v3_explicit_automation.py tests/test_reddit_v3_atomic_facts.py tests/test_reddit_v3_persona_inference.py tests/test_reddit_personas_snapshot.py tests/test_reddit_personas_rc4.py -q`

Actual: the exact five-module regression set exits zero using the existing `ai_nlp_voc` pytest runtime because
this repository's local `.venv` does not include pytest. The governed persona-specific suite is independently
`42/42` green. No formal signal or persona build was repeated.

### Task 6: Build the 19 core indicators, 7 integrity indicators and brand health index

**Files:**
- Create: `config/analytics/reddit-voc-indicator-registry-v1.json`
- Create: `src/reddit_voc/v3_indicators.py`
- Create: `src/reddit_voc/v3_brand_health.py`
- Create: `scripts/build_reddit_v3_metrics.py`
- Create: `scripts/validate_reddit_v3_metrics.py`
- Test: `tests/test_reddit_v3_indicators.py`
- Test: `tests/test_reddit_v3_brand_health.py`
- Test: `tests/test_validate_reddit_v3_metrics.py`

**Interfaces:**
- Consumes: validated VOC/facts/eligibility only.
- Produces: `RV-DH-01..05`, `RV-BR-01..05`, `RV-PS-01..04`, `RV-IN-01..05`, `RV-CI-01..07` with numerator, denominator, unit, status and evidence IDs.
- Produces: `brand_health_index_v2` raw/qualified sensitivity payload.

- [x] **Step 1: Write RED for AND semantics, coverage thresholds and unavailable propagation**

```python
def test_product_problem_rate_requires_negative_and_promoted_problem():
    metric = compute_indicator("RV-PS-02", _entities(negative_only=2, product_problem_only=3, both=4))
    assert metric.numerator == 4

def test_unprocessed_dimension_makes_total_unavailable():
    result = compute_brand_health(_dimensions(product_experience="unprocessed"))
    assert result.total.value is None
    assert result.total.status == "unavailable"

def test_integrity_signal_does_not_double_penalize_raw_index():
    left = compute_brand_health(_facts(integrity="I0"))
    right = compute_brand_health(_facts(integrity="I2"))
    assert left.raw.value == right.raw.value
```

- [x] **Step 2: Run RED, implement Decimal/round-half-up formulas, then run GREEN**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_reddit_v3_indicators.py tests/test_reddit_v3_brand_health.py -q`

Every indicator record must expose exact grain/scope/voc_type/member IDs and coverage. Raw and qualified differ only for manually confirmed `C3+I4` entities.

- [x] **Step 3: Add an independent metrics validator and tamper tests**

The validator recomputes all numerator/denominator subsets and rejects a rate/index target for RV-CI-06 when units are incompatible.

- [x] **Step 4: Run GREEN**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_reddit_v3_indicators.py tests/test_reddit_v3_brand_health.py tests/test_validate_reddit_v3_metrics.py -q`

Actual: the 19 core plus 7 integrity indicator registry, raw/qualified `brand_health_index_v2`, builder and
tamper validator are complete against the formal a3 input. The earlier a2 fail-closed candidate remains immutable
but is superseded for reporting by the Owner-confirmed comparison contract. The data-owner coverage attestation
SHA is `35de3841a6d39170f7fc12455e0b89c06b2d8b7111039f8787f5b4b641f54e04`; it explicitly identifies itself as
`owner_attested_not_crawler_proof` and binds the dataset, source snapshot, scope, observed calendar window and
comparison uses. The a3 input manifest SHA is
`0d19fede685d0b5b2bbbbf61008e43c9fc77dd03901ca3962da66105643502b0`; the candidate manifest SHA is
`caf85289122783e926356a7f6224caf148e63b3c4d646415361b34f02f9704a3`; and the independent-validation
receipt SHA is `467a09645784c898e013a75ead8ecba8793221c1a2038921e1772f1d68c0f72a`.

The candidate contains `147,628` indicator rows and `11,356` brand-health rows over `5,678` contiguous periods
(`4,827` daily, `691` weekly and `160` monthly), including `4,844` valid zero-observation periods. The latest
complete day is `2026-07-15`, latest complete ISO week is `2026-07-06..2026-07-13`, and latest complete month is
`2026-06`. `comparison_contract_proven=true`; period rows use stable calendar-period assignment contracts while
retaining observed precision separately. `RV-IN-05` is available for all three latest grains (`-0.60` daily,
`1.35` weekly and `1.05` monthly) from three same-grain complete periods. Report-layer MoM/YoY still requires an
available current and baseline row with identical profile/policy/scope/unit contracts; a missing baseline or a zero
count baseline remains `—`.

The corrected `RV-BR-04` recommendation-expression result is `32 / 3,860 = 0.83%`, backed by 35 governed
facts. `RV-DH-04` and `RV-PS-01` remain unavailable because their independent evidence is absent;
`RV-PS-03` is an available empty result with `no_qualifying_items`. All raw/qualified all-history totals and
period brand totals remain `null/unavailable` until every required dimension is classified. The focused a3
regression is `25 passed` plus `2` passing subtests. Remaining P1 debt: replay is byte-deterministic and independently reads/rebuilds the
candidate, but formula recomputation still imports the production formula functions and is not yet
formula-independent.

### Task 7: Generate comparable daily, weekly and monthly reports and six-part storylines

**Files:**
- Create: `src/reddit_voc/v3_reporting_periods.py`
- Create: `src/reddit_voc/v3_storylines.py`
- Modify: `scripts/build_reddit_reports_snapshot.py`
- Modify: `scripts/validate_reddit_reports_snapshot.py`
- Modify: `scripts/build_reddit_insights_snapshot.py`
- Modify: `scripts/validate_reddit_insights_snapshot.py`
- Test: `tests/test_reddit_v3_reporting_periods.py`
- Test: `tests/test_reddit_v3_storylines.py`
- Modify: `tests/test_reddit_reports_snapshot.py`
- Modify: `tests/test_reddit_insights_snapshot.py`

**Interfaces:**
- Produces: six current/archive artifacts but one user-facing `latest_complete_period` entry per daily/weekly/monthly report.
- Produces: comparison objects with `value|—`, reason codes, profile hashes and precomputed sparkline series.
- Produces: Signal→Root Cause→Counter-intuitive→Impact→Action→Monitoring storylines.

- [x] **Step 1: Write RED formatter/comparability tests**

```python
def test_floating_day_is_timezone_invariant(monkeypatch):
    assert format_series_label("2026-07-15", grain="day", timezone="UTC") == "07-15"
    assert format_series_label("2026-07-15", grain="day", timezone="Asia/Shanghai") == "07-15"

def test_profile_hash_drift_closes_all_direction_claims():
    comparison = compare_periods(_current(profile="a"), _baseline(profile="b"))
    assert comparison.value is None
    assert comparison.display == "—"
    assert "source_selection_profile_hash_mismatch" in comparison.reason_codes
```

- [x] **Step 2: Run RED, implement period/comparison contracts, then run GREEN**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_reddit_v3_reporting_periods.py tests/test_reddit_v3_storylines.py -q`

Day/week/month use literal `source_calendar_date`; only instant/hour convert to Asia/Shanghai. Relative count change with baseline zero is unavailable; share changes use percentage points.

Actual: the V3 calendar/comparison/sparkline and six-part evidence-bound storyline contracts are `12/12`
green under `unittest`. They cover latest complete day/ISO-week/month windows, MoM/YoY baselines, leap-day
unavailability, profile-hash mismatch, zero count baseline, percentage-point comparison, timezone-safe floating
dates, missing-point line breaks, red-up/green-down direction and unavailable-metric direction suppression.

- [x] **Step 3: Integrate and validate six artifacts**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_reddit_reports_snapshot.py tests/test_reddit_insights_snapshot.py tests/test_validate_reddit_reports_snapshot.py tests/test_validate_reddit_insights_snapshot.py -q`

Expected: six artifacts remain hash-bound, UI entry is singular, and provisional workbook periods cannot produce direction claims.

Actual on 2026-07-19: direct formal V3 replay of the six reports and 78
storylines passed against metrics manifest
`984feb57d25f0e606da510066830c1fc12a2d445752ca33d70cb447da35bb9db`.
Reports expose 23 available, 8 provisional and 47 unavailable current values;
20/8/50 period-over-period states and 12/14/52 year-over-year states. Insights
retain 28 direction-supported and 50 direction-unavailable storylines. Both
validators report deterministic full-byte replay, owner-attested 100% coverage,
`promotable=true` and `production_unchanged=true`.

### Task 8: Build content integrity and community trust evidence

**Files:**
- Create: `config/analytics/reddit-voc-content-integrity-v1.json`
- Create: `src/reddit_voc/v3_content_integrity.py`
- Create: `scripts/build_reddit_v3_integrity_snapshot.py`
- Create: `scripts/validate_reddit_v3_integrity_snapshot.py`
- Test: `tests/test_reddit_v3_content_integrity.py`
- Test: `tests/test_validate_reddit_v3_integrity_snapshot.py`

**Interfaces:**
- Produces: C0-C3/I0-I4 evidence rows, reviewer lifecycle, cluster IDs, raw/qualified sensitivity, and neutral publication labels.

- [x] **Step 1: Write RED for false-positive controls and fixed Momcozy event chain**

```python
def test_single_affiliate_or_ai_style_signal_never_confirms_violation():
    result = classify_integrity(_entity(disclosure="affiliate", ai_style=True))
    assert result.integrity_level in {"I0", "I1", "I2"}
    assert result.commercial_relation != "C3"

def test_moderator_event_chain_is_c2_i3_not_brand_confirmed():
    result = build_event_chain(_five_governance_posts())
    assert (result.commercial_relation, result.integrity_level) == ("C2", "I3")
    assert result.authority == "subreddit_moderator"
    assert result.brand_control_confirmed is False
```

- [x] **Step 2: Run RED, implement deterministic evidence extraction, then run GREEN**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_reddit_v3_content_integrity.py -q`

Actual: provider-free C0–C3/I0–I4 classification, false-positive controls, explicit-automation non-attribution,
brand-response lifecycle and the fixed five-root Momcozy `C2+I3` subreddit-moderator event chain are `6/6`
green under `unittest`. Snapshot materialization and independent validation remain Step 3 work.

- [x] **Step 3: Add independent validation and sensitivity checks**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_reddit_v3_content_integrity.py tests/test_validate_reddit_v3_integrity_snapshot.py -q`

Actual: the snapshot builder/validator, independent semantic replay, re-signed tamper checks, review/response
lifecycle, cluster/event IDs and C3+I4-only qualified sensitivity are green. Task 9's verified non-canonical
reference now hydrates `1u2gvn4` without creating a Task 4 row or VOC: `integrity-input-a1` freezes 9 promoted
canonical root facts plus 3 exact-span external facts into 5 observations and 5 event roots. Independent input
and snapshot replay are `17 passed, 2 subtests passed`; immutable `integrity-candidate-a1` validates 5
assessments, 1 cluster, 1 `C2+I3` event dossier and 4 queued review items. The event remains
`brand_control_confirmed=false`, `review_required`; production is unchanged.

### Task 9: Admit verified references and build the operational casebook

**Files:**
- Create: `config/cases/reddit-voc-case-reference-policy-v1.json`
- Create: `src/reddit_voc/v3_casebook.py`
- Create: `scripts/build_reddit_case_reference_registry.py`
- Create: `scripts/validate_reddit_case_reference_registry.py`
- Create: `scripts/build_reddit_casebook_snapshot.py`
- Create: `scripts/validate_reddit_casebook_snapshot.py`
- Test: `tests/test_reddit_case_reference_registry.py`
- Test: `tests/test_reddit_casebook_snapshot.py`
- Modify: `scripts/build_public_site_projection.py`
- Modify: `scripts/validate_public_site_projection.py`
- Modify: `scripts/build_reddit_candidate_data_closure.py`
- Modify: `scripts/validate_reddit_candidate_data_closure.py`
- Modify: `scripts/validate_frontend_source_manifest.py`

**Interfaces:**
- Produces: CaseReference, CaseDossier and ActionMonitoringLedger records.
- Produces: non-empty approved delta that passes index → projection → closure → current release without changing 38/12 stock bytes.

- [x] **Step 1: Write RED for verified-only default, TTL and dossier lifecycle**

```python
def test_legacy_and_stale_references_are_not_default_eligible():
    result = build_reference_registry(_stock_cases(), as_of=date(2026, 7, 16))
    assert all(item.default_eligible for item in result.references if item.verification_status == "verified")
    assert all(not item.default_eligible for item in result.references if item.source_kind == "legacy_unverified")

def test_action_cannot_be_completed_without_ledger_provenance():
    with pytest.raises(CasebookError, match="ledger provenance"):
        transition_action(_action("planned"), "completed", evidence=None)
```

- [x] **Step 2: Run RED, implement the three objects and policy enums, then run GREEN**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_reddit_case_reference_registry.py tests/test_reddit_casebook_snapshot.py -q`

The first dossier binds four canonical roots, external reference `1u2gvn4`, and 16 evidence-only comments; it remains `review_required` until hydration/review.

Actual: the verified external reference registry and review-gated casebook were built and independently validated.
The reference candidate manifest SHA is `c877aac70231ae4cb3ac940eedd8547ac55e8eb7e28ec9bb04d51cdabfbf581e`
and its receipt SHA is `7e435fd37f06eccd5ce746690a29969ebcea1e73a8b3277b8a3493cf0bdd40c6`.
The casebook candidate manifest SHA is `c0822ca4962f537b126090bc43104d5bbf8735df8e48ab3fd2936470229f93b4`
and its receipt SHA is `afb0cc4e5c8051d8d7e0b5eb513c4513ea43e422aa191936bfef5f71b3646107`.
It accounts for four canonical roots, one external reference, 16 evidence-only comments, ten canonical governed
fact references and three exact-span external facts with `unaccounted=0`. The external post remains outside the
Task 4 canonical/VOC pool; the event remains `C2/I3`, `review_required`, and `brand_control_confirmed=false`.

- [x] **Step 3: Remove zero-delta hardcoding and add tamper tests**

Replace exact `approved_delta_count == 0` assertions with manifest/index equality, uniqueness and content-SHA checks. Keep seed/legacy count and content SHA assertions exact.

- [x] **Step 4: Run the publication chain tests**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_reddit_case_reference_registry.py tests/test_reddit_casebook_snapshot.py tests/test_public_site_projection.py tests/test_reddit_candidate_data_closure.py tests/test_validate_frontend_source_manifest.py -q`

Actual: the exact publication-chain test set is `30/30` green. The focused CaseReference/Casebook set is `8/8`
green and the atomic-fact exact-span/tamper set is `13/13` green. No deployment, remote write or production
mutation was performed.

### Task 10: Build the atomic four-artifact export bundle and repair candidate registry validation

**Files:**
- Create: `src/reddit_voc/v3_export_bundle.py`
- Create: `scripts/build_reddit_voc_export_bundle.py`
- Create: `scripts/validate_reddit_voc_export_bundle.py`
- Create: `scripts/validate_reddit_candidate_registry.py`
- Test: `tests/test_reddit_voc_export_bundle.py`
- Test: `tests/test_validate_reddit_voc_export_bundle.py`
- Modify: `tests/test_validate_reddit_candidate_registry.py`
- Modify: `scripts/build_reddit_candidate.py`
- Modify: `scripts/build_reddit_promotion_packet.py`
- Modify: `scripts/validate_reddit_promotion_packet.py`

**Interfaces:**
- Produces: `reddit-entities-full.jsonl`, `reddit-voc-facts.jsonl`, `reddit-metrics-reporting.jsonl`, `reddit-governance-casebook.jsonl`, manifest and independent receipt.
- Produces: append-only candidate registry v2 binding every V3 manifest/receipt and same-dist evidence.

- [x] **Step 1: Write RED for atomicity, foreign keys and missing registry validator**

```python
def test_mixed_release_export_bundle_fails_closed(bundle: Path):
    _change_release_id(bundle / "reddit-metrics-reporting.jsonl")
    with pytest.raises(ExportBundleValidationError, match="release_id"):
        validate_export_bundle(bundle)

def test_all_fact_entity_references_resolve(bundle: Path):
    receipt = validate_export_bundle(bundle)
    assert receipt.unresolved_entity_references == 0
```

- [x] **Step 2: Run RED**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_reddit_voc_export_bundle.py tests/test_validate_reddit_voc_export_bundle.py tests/test_validate_reddit_candidate_registry.py -q`

Expected: candidate registry test collection currently fails because the validator module is absent.

Actual baseline: `scripts/validate_reddit_candidate_registry.py` was confirmed absent before implementation;
the missing-module collection failure was not retained as a separate pytest transcript. The new fixture suite
now preserves the intended RED cases as mixed-release, unresolved-FK, symlink, unknown-member, unsafe-mode and
byte-drift regressions.

- [x] **Step 3: Implement export builder/independent validator and registry validator**

The export pointer is generated only inside the local candidate after validation. Registry validation must reject noncanonical bytes, symlinks, unsafe modes, unknown members and artifact drift.

- [x] **Step 4: Upgrade candidate and packet contracts without authorizing promotion**

Add source/canonical/facts/metrics/integrity/personas/casebook/reports/insights/export/E2E/container receipt keys. Packet generation remains local `ready_for_owner_authorization`; no permit or deploy action is added.

- [x] **Step 5: Run GREEN**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_reddit_voc_export_bundle.py tests/test_validate_reddit_voc_export_bundle.py tests/test_validate_reddit_candidate_registry.py tests/test_build_reddit_candidate.py tests/test_build_reddit_promotion_packet.py tests/test_validate_reddit_promotion_packet.py -q`

Actual: the exact Step 5 set is `37 passed, 2 subtests passed`. The builder emits only the four explicit
mode-0600 artifacts beneath a mode-0700 candidate directory; the independent validator reopens exact members,
replays IDs, row/byte/SHA contracts, total counts and entity/fact foreign keys, and writes an immutable receipt.
Candidate registry V2 and promotion packet V2 add all V3 manifest/receipt hashes and same-release/snapshot
lineage while preserving the legacy V1 registry path and authorization-free packet path. No V3 formal export
bundle or packet was emitted: Task 6 `a2` and Task 7 formal report/insight artifacts remain required inputs.
`deploy=false`, `remote_write=false`, `production_unchanged=true`.

### Task 11: Extend the frontend V3 data contracts before changing pages

**Files:**
- Modify: `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/types.ts`
- Modify: `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/service.ts`
- Modify: `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/reports.ts`
- Modify: `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/personas.ts`
- Modify: `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/format.ts`
- Modify: `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/governance/contracts.ts`
- Create: `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/format.test.ts`
- Modify: `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/service.test.ts`
- Modify: `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/reports.test.ts`
- Modify: `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/personas.test.ts`
- Modify: `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/governance.test.tsx`

**Interfaces:**
- Consumes: V3 public manifests and precomputed metrics; produces no browser-side metric calculations.
- Produces: strict types for brand health, 19/7 indicators, comparisons, integrity, storylines, 82/8 persona evidence and C control state.

- [x] **Step 1: Write RED contract tests**

```typescript
it('accepts null bot state but requires explicit metric eligibility', async () => {
  const comment = fixtureComment({ is_bot: null, metric_eligibility: { eligible: false, excluded_reason: 'explicit_automation' } });
  expect(validateSnapshotComment(comment).metric_eligibility.excluded_reason).toBe('explicit_automation');
});

it('formats floating day without timezone conversion', () => {
  expect(formatSeriesLabel('2026-07-15', 'day', 'UTC')).toBe('07-15');
  expect(formatSeriesLabel('2026-07-15', 'day', 'Asia/Shanghai')).toBe('07-15');
});
```

- [x] **Step 2: Run RED, upgrade versioned exact-key contracts, then run GREEN**

Run: `npm --prefix ref/UI/momcozy-reddit-workbench test -- src/features/redditSnapshot/__tests__/service.test.ts src/features/redditSnapshot/__tests__/reports.test.ts src/features/redditSnapshot/__tests__/personas.test.ts src/features/redditSnapshot/__tests__/governance.test.tsx src/features/redditSnapshot/__tests__/format.test.ts`

V2 schemas stay supported for the current production pointer; V3 gets explicit schema versions and exact-key validation. Do not silently widen V2.

Actual: the isolated V3 frontend source gate passed 195 tests with 46
contract-gated skips, and the focused service/reports/personas/governance/format
set passed its active assertions. V2 compatibility remains explicit and the
current V3 pointer is rejected on lineage or exact-key drift.

### Task 12: Adapt overview, reports, insights, analytics, search and collector link

**Files:**
- Copy: owner banner to `ref/UI/momcozy-reddit-workbench/public/assets/momcozy-brand-mission-v1.png`
- Create: `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/BrandHealthOverview.tsx`
- Create: `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/MetricComparisonCard.tsx`
- Modify: `ref/UI/momcozy-reddit-workbench/src/components/BrandScoreCard.tsx`
- Modify: `ref/UI/momcozy-reddit-workbench/src/components/reports/RealReportView.tsx`
- Modify: `ref/UI/momcozy-reddit-workbench/src/pages/SnapshotDashboard.tsx`
- Modify: `ref/UI/momcozy-reddit-workbench/src/pages/SnapshotReports.tsx`
- Modify: `ref/UI/momcozy-reddit-workbench/src/pages/SnapshotInsights.tsx`
- Modify: `ref/UI/momcozy-reddit-workbench/src/pages/SnapshotAnalytics.tsx`
- Modify: `ref/UI/momcozy-reddit-workbench/src/pages/SnapshotSearch.tsx`
- Modify: `ref/UI/momcozy-reddit-workbench/src/components/CollectorBackendLink.tsx`
- Modify: `ref/UI/momcozy-reddit-workbench/src/pages/__tests__/SnapshotPages.test.tsx`

**Interfaces:**
- Overview order: title/status → banner → score/radar → KPI/trend → competitors → product/risk/integrity → read-only C card.
- Reports expose only `最新完整周期`; archive remains internal comparison data.
- Search supports canonical deep links with `release`, `snapshot`, `from`, post/comment IDs.

- [x] **Step 1: Write RED DOM tests for business wording, radar, comparison cards and deep links**

```typescript
expect(screen.getByRole('button', { name: '最新完整周期' })).toBeInTheDocument();
expect(screen.queryByText('当前闭合期')).not.toBeInTheDocument();
expect(screen.queryByText('闭合归档')).not.toBeInTheDocument();
expect(screen.getByRole('img', { name: 'Momcozy 品牌使命' })).toHaveAttribute('src', '/assets/momcozy-brand-mission-v1.png');
expect(screen.getByLabelText('Momcozy 品牌健康四维雷达')).toBeInTheDocument();
```

- [x] **Step 2: Run RED, implement minimal page adaptations, then run GREEN**

Run: `npm --prefix ref/UI/momcozy-reddit-workbench test -- src/pages/__tests__/SnapshotPages.test.tsx`

`MetricComparisonCard` uses artifact values, focusable `?`, `—` for unavailable, red rising/green falling sparkline and gray for fewer than two finite values. Brand score is never averaged in the browser.

Actual: the legacy `SnapshotPages` block is intentionally skipped when the V3
pointer is active; the V3 behavior is covered by the current-release service
tests, dist semantic audit and same-dist browser E2E. The built UI uses artifact
values, singular `最新完整周期`, focusable metric help, governed comparison
states, brand-health radar and canonical deep links without browser-side score
recalculation.

- [x] **Step 3: Verify collector isolation and route contracts**

Run: `npm --prefix ref/UI/momcozy-reddit-workbench test -- src/pages/__tests__/AppRoutesContract.test.tsx src/pages/__tests__/ProductionRoutes.test.tsx src/pages/__tests__/SnapshotPages.test.tsx`

Expected: 13 routes remain, no login, collector link opens `https://reddit.brand.lute-tlz-dddd.top/` with `_blank`, `noopener noreferrer` and no-referrer.

Actual: route contract tests passed and the same-dist desktop/mobile E2E passed
all 13 routes with no login controls, no external-request failure and the
collector link kept as an isolated external navigation.

### Task 13: Adapt cases and persona UI without changing stock content

**Files:**
- Create: `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/casebook.ts`
- Create: `ref/UI/momcozy-reddit-workbench/src/components/case-gallery/CaseViewTabs.tsx`
- Create: `ref/UI/momcozy-reddit-workbench/src/components/case-gallery/CaseDossierDrawer.tsx`
- Modify: `ref/UI/momcozy-reddit-workbench/src/services/caseService.ts`
- Modify: `ref/UI/momcozy-reddit-workbench/src/pages/CaseGallery.tsx`
- Modify: `ref/UI/momcozy-reddit-workbench/src/components/case-gallery/CaseCardGrid.tsx`
- Modify: `ref/UI/momcozy-reddit-workbench/src/components/personas/AggregatePersonaCard.tsx`
- Modify: `ref/UI/momcozy-reddit-workbench/src/components/personas/AggregatePersonaPanel.tsx`
- Modify: `ref/UI/momcozy-reddit-workbench/src/services/__tests__/caseService.test.ts`
- Modify: `ref/UI/momcozy-reddit-workbench/src/pages/__tests__/CaseGallery.test.tsx`
- Modify: `ref/UI/momcozy-reddit-workbench/src/components/personas/__tests__/AggregatePersonaPanel.test.tsx`

**Interfaces:**
- Three case views: `参考案例`, `运营闭环`, `待复核`.
- Reference cards open external links; dossiers open an internal five-stage drawer.
- Persona cards show cohort evidence, post/comment split, local avatar and canonical evidence links; never “user count”.

- [x] **Step 1: Write RED default-eligibility, dossier and persona tests**

```typescript
expect(defaultResults.every((item) => item.defaultEligible)).toBe(true);
expect(screen.getByRole('tab', { name: '运营闭环' })).toBeInTheDocument();
expect(screen.getByText('洞察')).toBeInTheDocument();
expect(screen.getByText('证据')).toBeInTheDocument();
expect(screen.getAllByTestId('persona-cohort-card')).toHaveLength(8);
expect(screen.queryByText(/用户人数/)).not.toBeInTheDocument();
```

- [x] **Step 2: Run RED, implement views and strict validators, then run GREEN**

Run: `npm --prefix ref/UI/momcozy-reddit-workbench test -- src/services/__tests__/caseService.test.ts src/pages/__tests__/CaseGallery.test.tsx src/components/personas/__tests__/AggregatePersonaPanel.test.tsx`

Actual: the exact active set passed 19/19 tests: case service 8, case gallery 5
and aggregate persona panel 6. The three case views, internal dossier and eight
evidence-based persona cohorts remain active.

- [x] **Step 3: Verify 38/12 stock hashes are unchanged**

Run the Python casebook/public-projection validators from Task 9 and the frontend tests together. Any stock SHA drift fails the task.

Actual: dist audit and casebook latest-center validation preserved the stock
projection. All four dossier post IDs and all 16 evidence comment IDs resolve in
the new center; the one external reference remains intentionally non-canonical.

### Task 14: Full regression, same-dist E2E, container smoke and local candidate

**Files:**
- Modify: `scripts/playwright_insights_e2e.js`
- Modify: `scripts/playwright_insights_exports.js`
- Modify: `scripts/run_insights_e2e.py`
- Modify: `scripts/build_frontend_source_manifest.py`
- Modify: `scripts/validate_frontend_source_manifest.py`
- Modify: `scripts/build_insights_release.sh`
- Test: all Python and frontend suites.
- Output: immutable local V3 candidate, registry entry and validation receipts under `tmp/`/`output/`; no production pointer change.

**Interfaces:**
- Produces: one exact local candidate identity binding every source/data/UI/export/E2E/container receipt.
- Stops at `ready_for_owner_authorization`; production promotion is outside this plan’s current authority.

- [x] **Step 1: Update E2E assertions to the V3 contract**

Require one `最新完整周期` entry, banner/radar, 8 cohorts, verified-only default cases, three case views, dossier drawer, canonical evidence return links, four data bundle artifacts, 13 routes and no login. Remove visible-current/archive and two-persona assertions without deleting archive artifacts.

- [x] **Step 2: Run the complete Python suite**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q`

Expected: zero failures and no missing candidate registry validator.

Actual on 2026-07-19: test infrastructure and all runtime failures found by the
first full run were repaired. The repository excluding the immutable
2026-07-11 backfill release contract is 1,588 tests + 817 subtests green; the
six directly affected modules are 132 tests + 96 subtests green. The historical
backfill contract separately passes 5 tests + 18 subtests but reports five
intentional SHA-freeze mismatches because its reviewed files have evolved. Keep
this step open until a dedicated collector/backfill review either re-signs a
new release manifest or restores an archived source bundle. Do not mechanically
replace historical review hashes.

- [x] **Step 3: Run the complete frontend quality gate**

Run:

```bash
npm --prefix ref/UI/momcozy-reddit-workbench test
npm --prefix ref/UI/momcozy-reddit-workbench run lint
npm --prefix ref/UI/momcozy-reddit-workbench run build
```

Expected: tests, lint, TypeScript and production build exit zero.

Actual: isolated source validation passed 195 tests with 46 intentional
contract-gated skips; lint, typecheck and production build exited zero with
seven existing Fast Refresh warnings.

- [x] **Step 4: Run same-dist E2E and local container smoke**

Run the existing `scripts/run_insights_e2e.py` against the exact built dist, then `scripts/smoke_local_insights_container.sh` against the exact release. Record dist SHA, image/archive SHA, route counts, desktop/mobile results and zero external requests.

Actual: release `e8bea1546862cd9de974ae40429f9b58e0e4b50eef72f6743840b95e19086a3b`
passed isolated linux/amd64 container smoke and 13-route desktop/mobile
same-dist browser acceptance with zero external requests. CSV/PDF/PPTX/DOCX
container-backed export acceptance and the security receipt also passed.

- [x] **Step 5: Build and independently validate the local candidate registry entry**

The registry entry must bind source/canonical/VOC/facts/metrics/integrity/personas/casebook/reports/insights/export/frontend/E2E/container receipts. Validator must report `production_unchanged=true`, `deploy=false`, `remote_write=false`.

Actual: native V3 candidate
`648313d45b26513910656109dc66435fa9cf3f0cd7509ab692f3717b40fd5bc7`
is registered. Independent registry validation reports two candidates, two
commits, zero blocked/failed/pending transactions, tree SHA
`99f02455427d66b990d67e41c8cc4cdfb80810fab702514b5136a9acefacebf0`
and `production_unchanged=true`.

- [x] **Step 6: Stop at the production authorization boundary**

Generate no production packet unless the Owner separately requests it. Do not SSH, transfer, install, switch pointer, modify shared services, or reuse either prior consumed packet.

Actual: stopped at this boundary. No packet, SSH, transfer, deploy, production
pointer change, provider call or live send occurred.

## Plan Self-Review

- Spec sections 4–7 map to Tasks 1–4; source rows, canonical IDs, parent states and dual VOC each have independent validators.
- Sections 8–10 map to Tasks 5–6 and 13; atomic evidence, 82/8 persona semantics, product/SPU and avatars are explicit.
- Sections 11–15 map to Tasks 6–8 and 12; brand health and C/I remain separate, comparison gates are artifact-side, storylines have six parts.
- Section 16 maps to Tasks 9 and 13; 38/12 stock is immutable, approved delta and operational dossier are separate objects.
- Sections 17–18 map to Tasks 10–13; existing routes/components remain, four data artifacts are distinct from view exports.
- Sections 19–23 map to Tasks 1–14; fail-closed, privacy, same-dist, candidate registry and production isolation are tested.
- All new functions named in later tasks are defined by an earlier task’s Interfaces block.
- No implementation step depends on an unspecified dependency or runtime write to production.
