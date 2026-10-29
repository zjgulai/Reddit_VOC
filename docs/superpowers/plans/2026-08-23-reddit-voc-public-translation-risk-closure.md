---
title: Reddit VOC Public Translation Risk Closure Implementation Plan
doc_type: implementation_plan
status: completed_local_candidate
created: 2026-08-23
updated: 2026-08-23
---

# Reddit VOC Public Translation Risk Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the public-site builder's hardcoded-only `source_equal` retry decision with one bounded, reason-bound repair request, preserve partial checkpoint salvage and fail-closed quality behavior, then freeze a provider-inert H1-R3 continuation candidate.

**Architecture:** Reuse the already validated `TranslationService` payload contract: the original protected source remains the translation input, while a `repair_context` identifies the exact failed stable ID and deterministic reason. The builder may perform one logical repair call only after a singleton `source_equal_translation` or `non_chinese_translation` failure; the call remains inside the existing `AttemptBudget`, and a second quality failure terminates without another repair. Production Provider execution, public candidate publication, Git push and disk cleanup remain separate gates.

**Tech Stack:** Python 3.12, stdlib `unittest`, existing `reddit_voc.translation_pipeline`, JSON/JSONL, SHA-256 frozen manifests, shell postflight checks. No new dependency.

**Spec:** `PROJECT_STATUS.md`, section `2026-08-23 H1-R2：公开站翻译续跑终态`.

## Global Constraints

- Only High-severity defects may change code in this iteration.
- Current root cause hypothesis: the public builder retries `source_equal_translation` only when `_source_equal_retry_override()` returns a hardcoded source mutation; an otherwise valid generic ASCII item therefore terminates without receiving the existing reason-bound repair prompt.
- One hypothesis, one minimal implementation, then the identical reproduction command. If two implementation rounds do not resolve the same reproduction, stop before a third code change and issue the required loss-control report.
- No DeepSeek/Provider call, production write, database access, TikHub/collection call, DingTalk send, cron/current/authority/credential change, container operation, Git commit/push, or file deletion is authorized by this plan.
- Tests and diagnostics must not print source text, translations, webhook data or credential material. Synthetic text is used for the regression.
- A repair call must preserve the original `stable_id`, `input_sha256` and protected source contract, must be charged to the existing `AttemptBudget`, and must not create a new cross-process retry path.
- Existing accepted translations from a partially valid batch remain append-only checkpoint evidence; only failed IDs enter the repair call.
- A repeated `source_equal_translation`, invalid response, unknown Provider state or exhausted budget remains terminal and must not be auto-allowed.
- Existing unrelated working-tree changes must not be reset, overwritten, formatted or committed.

## Risk Priority

| Priority | Risk | Decision |
|---|---|---|
| High | Generic `source_equal` item has no repair request and blocks all 527 remaining items | Fix now with TDD and one bounded repair context |
| High | No validated public candidate exists after H1-R2 | Freeze a provider-inert H1-R3 candidate after tests; stop before external execution |
| High | Local/GitHub/production cannot be consistent while the working tree is dirty | Produce a fresh read-only consistency report; commit/push/deploy require a separate explicit action |
| Medium | H1-R2 observed 5 invalid JSON responses in 9 HTTP 200 attempts | Do not change in this iteration; existing bounded same-process recovery worked and was not the terminal blocker |
| Medium | Data volume is at 99% with about 7.1 GiB available | Inventory read-only; deletion or cleanup requires explicit target approval |
| Low | Historical phrase-specific source overrides remain as optional hints | Keep for compatibility in this minimal fix; remove only in a later independently reviewed cleanup |

---

### Task 1: Freeze the Reproduction and Prove RED

**Files:**
- Modify: `tests/test_reddit_v3_translation_candidate.py`
- Read: `scripts/build_reddit_v3_translation_candidate.py`
- Read: `src/reddit_voc/translation_pipeline.py`

**Interfaces:**
- Consumes: `_request_with_split(...)`, `AttemptBudget`, `load_translation_runtime_assets(...)`.
- Produces: a regression test proving a generic ASCII source-equal item receives no second repair request in the current implementation.

- [x] **Step 1: Add a recording fake Provider**

```python
class _GenericSourceEqualRepairClient:
    def __init__(self) -> None:
        self.payloads: list[dict[str, object]] = []

    def complete_json(self, *, user_payload, attempt_budget, **_kwargs):
        sequence = attempt_budget.reserve("translation")
        self.payloads.append(user_payload)
        item = user_payload["items"][0]
        translated = item["source_text"] if len(self.payloads) == 1 else "同意"
        return _Completion(
            content=json.dumps(
                {"translations": [{"id": item["id"], "zh": translated}]},
                ensure_ascii=False,
            ),
            sequence=sequence,
        )
```

- [x] **Step 2: Add the exact regression**

```python
def test_generic_source_equal_uses_one_reason_bound_repair_without_mutating_source(self) -> None:
    items = build_translation_items(
        [{"post_id": "generic-repair", "title": "Agreed", "content": ""}],
        [],
        include_comments=False,
    )
    client = _GenericSourceEqualRepairClient()
    successes: list[dict[str, str]] = []
    _request_with_split(
        client=client,
        assets=load_translation_runtime_assets(
            Path(__file__).resolve().parents[1] / "config"
        ),
        items=(items[0],),
        budget=AttemptBudget(max_attempts=2),
        timeout_seconds=60.0,
        on_error=lambda _error: None,
        on_success=lambda translations, _completion: successes.append(translations),
    )
    self.assertEqual(successes, [{items[0].stable_id: "同意"}])
    self.assertEqual(len(client.payloads), 2)
    self.assertEqual(
        client.payloads[1]["items"][0]["source_text"],
        client.payloads[0]["items"][0]["source_text"],
    )
    self.assertEqual(
        client.payloads[1]["repair_context"],
        {
            "reason_codes_by_id": {
                items[0].stable_id: ["source_equal_translation"],
            },
            "requirements": [
                "return_a_materially_translated_chinese_value",
                "do_not_return_the_source_text_unchanged",
                "preserve_all_protected_placeholders_exactly",
            ],
        },
    )
```

- [x] **Step 3: Run the one-test RED command**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest \
  tests.test_reddit_v3_translation_candidate.RedditV3TranslationCandidateTests.test_generic_source_equal_uses_one_reason_bound_repair_without_mutating_source
```

Expected: `FAIL` or `ERROR` because the current generic item does not enter a second repair request. The failure must occur after the first deterministic `source_equal_translation`, not during import or fixture setup.

### Task 2: Implement One Bounded Reason-Bound Repair

**Files:**
- Modify: `scripts/build_reddit_v3_translation_candidate.py`
- Test: `tests/test_reddit_v3_translation_candidate.py`

**Interfaces:**
- Consumes: `_provider_batch(...)` and `ProviderBatchValidationError.reason_code`.
- Produces: optional `_provider_batch(..., repair_reason_codes_by_id=...)` payload support and one singleton repair attempt.

- [x] **Step 1: Extend `_provider_batch` without changing its default behavior**

Add the optional parameter:

```python
repair_reason_codes_by_id: Mapping[str, tuple[str, ...]] | None = None,
```

Validate that its keys exactly equal the request item IDs and every reason tuple is non-empty; otherwise raise `TranslationCandidateError("translation_repair_scope_invalid")` before any Provider call.

- [x] **Step 2: Add the established repair payload**

```python
if repair_reason_codes_by_id is not None:
    payload["repair_context"] = {
        "reason_codes_by_id": {
            item.stable_id: list(repair_reason_codes_by_id[item.stable_id])
            for item in items
        },
        "requirements": [
            "return_a_materially_translated_chinese_value",
            "do_not_return_the_source_text_unchanged",
            "preserve_all_protected_placeholders_exactly",
        ],
    }
```

- [x] **Step 3: Change only the singleton quality-failure branch**

For `source_equal_translation` and the already-associated `non_chinese_translation`, allow the existing single fallback call even when `_source_equal_retry_override()` returns `None`. Pass the exact reason through `repair_reason_codes_by_id`. Preserve existing optional source overrides as compatibility hints, preserve raw-source placeholder handling, and do not add a loop.

- [x] **Step 4: Run the identical one-test GREEN command**

Run the Task 1 Step 3 command unchanged.

Expected: one test passes, exactly two logical Provider calls are recorded, and the second request retains the original synthetic source plus the exact `repair_context`.

### Task 3: Verify Fail-Closed and Partial-Salvage Behavior

**Files:**
- Modify only if the new behavior requires stronger assertions: `tests/test_reddit_v3_translation_candidate.py`
- Read-only verification: `tests/test_translation_pipeline.py`

**Interfaces:**
- Consumes: existing partial salvage, placeholder, invalid JSON, slang and normalized-source tests.
- Produces: evidence that the fix does not create a third repair, does not retry accepted IDs, and does not weaken deterministic validation.

- [x] **Step 1: Run the focused builder matrix**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest \
  tests.test_reddit_v3_translation_candidate.RedditV3TranslationCandidateTests.test_generic_source_equal_uses_one_reason_bound_repair_without_mutating_source \
  tests.test_reddit_v3_translation_candidate.RedditV3TranslationCandidateTests.test_batch_failure_salvages_valid_items_and_retries_only_failed_item \
  tests.test_reddit_v3_translation_candidate.RedditV3TranslationCandidateTests.test_reddit_unavailable_placeholder_source_equal_retries_once \
  tests.test_reddit_v3_translation_candidate.RedditV3TranslationCandidateTests.test_source_equal_slang_expands_before_one_raw_retry \
  tests.test_reddit_v3_translation_candidate.RedditV3TranslationCandidateTests.test_comparison_and_foreign_source_equal_get_narrow_normalized_retries \
  tests.test_reddit_v3_translation_candidate.RedditV3TranslationCandidateTests.test_single_invalid_json_retries_once_without_accepting_bad_response
```

- [x] **Step 2: Run translation-pipeline reference regressions**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest \
  tests.test_translation_pipeline.TranslationServiceTests.test_source_equal_failure_repairs_only_failed_item_before_semantic \
  tests.test_translation_pipeline.TranslationContentTests.test_deterministic_gate_blocks_source_equal_non_chinese_missing_entity_and_bad_empty
```

- [x] **Step 3: Run complete directly affected modules**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest \
  tests.test_reddit_v3_translation_candidate \
  tests.test_translation_pipeline \
  tests.test_deepseek_client
```

- [x] **Step 4: Review the diff**

Run `git diff --check` and inspect the exact diff. Reject any change outside the builder, its tests, the plan and the project status record.

### Task 4: Freeze a Provider-Inert H1-R3 Candidate

**Files:**
- Create: `tmp/high-severity-remediation-20260822/h1-translation-resume-20260823-r3/`
- Copy into the frozen runtime only after source tests pass:
  - `scripts/build_reddit_v3_translation_candidate.py`
  - `scripts/validate_reddit_v3_translation_candidate.py`
  - `src/reddit_voc/__init__.py`
  - `src/reddit_voc/deepseek_client.py`
  - `src/reddit_voc/report_contracts.py`
  - `src/reddit_voc/translation_pipeline.py`
  - `config/prompts/deepseek-translation-v1.txt`
  - `config/prompts/deepseek-semantic-validator-v1.txt`
  - `config/translation_terms.json`

**Interfaces:**
- Consumes: post-H1-R2 checkpoint SHA `7f10491afbdc73805dd8ae670e566adaeaada5cce88ad701a73da30b504da610`, Provider ledger SHA `734d087f973f7c452f5b1ba8a3dfc2964769c11af62810a8642873dc04b3d849`, builder receipt SHA `7bdb416b0f67b9c7b922615bba4a3e5545444fca40ef089d9695daeab7f94a13`, terminal receipt SHA `a34e9d96eae068beecb412d83dce318f8f08805324460c48170f91832532333b`, execution permit SHA `e81780d53b6234835469fc939b7e0fecf17990c1bdfe4d3916e62adcacc651ee`, remaining item count `527`.
- Produces: a local archive, gate manifest, executor and test receipt with exact SHA values; no execution permit and no external action.

- [x] **Step 1: Recompute every source/runtime SHA and exact fileset**

Reject symlinks, unexpected files, `.pyc`, `.pyo`, `__pycache__`, group/world-writable files and any secret-like literal.

- [x] **Step 2: Bind a new non-authorized gate**

Use gate ID `h1-translation-resume-20260823-r3`; bind the exact post-R2 preimages above, including both the latest builder receipt and the consumed H1-R2 terminal/permit chain, `remaining_item_count=527`, the same public Reddit field scope, `deepseek-v4-flash`, one worker, the existing same-process retry contract, and an external-attempt cap no greater than 71. Mark the candidate as requiring fresh exact user authorization; do not install a production execution permit.

- [x] **Step 3: Run provider-free tests**

Test exact SHA mismatch, consumed-parent mismatch, checkpoint/ledger drift, candidate-exists rejection, authorization absence, attempt cap, repair scope, terminal receipt emission and all forbidden effect flags. Tests must use fake roots and fake clients only.

- [x] **Step 4: Build the immutable archive and write a local receipt**

The receipt records archive/gate/executor/runtime SHA values, file modes, test counts and `provider_call=false`, `production_unchanged=true`.

### Task 5: Stop at the Fresh External-Authorization Gate

**Files:**
- Update: `PROJECT_STATUS.md`
- Read-only: H1-R3 local receipt and archive

**Interfaces:**
- Consumes: exact frozen H1-R3 artifacts.
- Produces: an authorization proposal containing exact SHA values and explicit allowed/prohibited effects.

- [x] **Step 1: State facts, inference and unknowns separately**

Facts include local red/green output and frozen SHA values. Inference is that a generic repair context can clear ordinary source-equal items. The actual result for the remaining 527 production items stays unknown until a separately authorized Provider run.

- [x] **Step 2: Do not execute H1-R3**

Fresh explicit authorization is required before archive upload, production installation, DeepSeek use, checkpoint/ledger mutation or candidate construction.

### Task 6: Record Non-Code Operational Gates

**Files:**
- Update: `PROJECT_STATUS.md`
- No deletion, commit, push or deployment.

- [x] **Step 1: Run read-only workspace and disk checks**

Run `git status --short --branch`, `git diff --check`, `df -h /System/Volumes/Data`, and bounded `du` only within the repository and established Reddit VOC temporary roots.

- [x] **Step 2: Keep Git consistency separately gated**

Do not call the local, GitHub and production versions consistent while the worktree is dirty. A later gate must review the complete diff, commit the accepted code, push `main`, verify GitHub Actions, rebuild an immutable production release from that commit and read back its version lock.

- [x] **Step 3: Keep disk cleanup separately gated**

List explicit recoverable targets and estimated bytes. Any deletion, trash move or archive pruning requires target-specific approval because the current temporary roots contain audit receipts and frozen bundles.

## Self-Review Checklist

- [x] Every High risk maps to an executable task or a clearly separated external gate.
- [x] The plan contains no Provider call, production write, secret read, send, database operation, commit, push or delete command.
- [x] The TDD test fails for the missing repair behavior rather than import/configuration failure.
- [x] The implementation changes one control-flow decision and one payload contract only.
- [x] Same test command proves RED then GREEN.
- [x] Full affected-module tests and `git diff --check` pass before any freeze claim.
- [x] H1-R3 remains a local inert candidate until fresh exact authorization.
