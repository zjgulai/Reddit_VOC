---
title: Reddit VOC High-Risk Phase 2 Implementation Plan
doc_type: implementation_plan
status: completed_local_and_readonly_gates
created: 2026-08-23
updated: 2026-08-23
---

# Reddit VOC High-Risk Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the missing annual parent authority closure for the natural 08:00 cycle, preserve H1-R3 translation and production side-effect boundaries, and turn Git and disk pressure into exact independently authorized gates.

**Architecture:** Treat the project as four independent lanes: natural-cycle authority, public-site translation, Git traceability, and local storage. The only code-like change in the current lane is a parent-only authority installer candidate; it creates one exact immutable JSON file under the existing daily-report shared lock and leaves release/current/cron/child policy/owner/marker/credentials untouched. DeepSeek execution, public-current promotion, Git push, and deletion remain separate effect gates.

**Tech Stack:** Python 3.12 stdlib, `unittest`, canonical JSON, SHA-256, POSIX file metadata, SSH read-only diagnostics, Git/GitHub CLI. No new dependency.

**Spec:** `PROJECT_STATUS.md`; `docs/superpowers/plans/2026-08-23-reddit-voc-public-translation-risk-closure.md`.

## Global Constraints

- Only High-severity defects may change executable behavior in this phase.
- Stable reproduction for the natural-cycle defect is: after the 2026-08-23 08:00 cron invocation, `/home/ubuntu/.reddit-voc/report-control/scheduled-cycles` is absent and `cron-report.log` ends with `reason=parent_policy_invalid` followed by `reason=scheduled_cycle_reserve_failed`.
- Confirmed root cause: active `report_control.py` requires `/opt/reddit-voc-daily-report/control/authority/g6r5-annual-daily-live-policy.json` with SHA `98cbdd40b6b7ce06b15c5fd73d6f9a9329c22fc8f78cf6df114fcff3764c3cb4`; the child policy and owner bind that SHA, but the production parent path is absent.
- Do not modify or rerun the consumed G6R6 activation bundle. Build a successor parent-only hotfix with a new authorization namespace.
- One root hypothesis, one minimal implementation, then the same fake-root reproduction. If two implementation rounds do not pass the same reproduction, stop before a third modification and issue the required loss-control report.
- The current phase does not authorize remote writes, DeepSeek/TikHub/DingTalk calls, database access, cron/current/authority/credential changes, container operations, Git commit/push, or deletion.
- Never read or print credential contents. Credential and report-env checks are metadata-only.
- Preserve all existing dirty working-tree changes; do not reset, format, commit, or include them in an external effect without a separate review gate.

## Risk Order

| Priority | Risk | Current decision |
|---|---|---|
| High | Natural 08:00 cycle always fails before reservation because the annual parent authority file is absent | Build and freeze a parent-only atomic hotfix now; production install requires exact authorization |
| High | H1-R3 still has 527 untranslated public fields | Keep the already frozen continuation; refresh production preimages read-only and request a separate exact DeepSeek authorization |
| High | Dirty local worktree means local/GitHub/production versions are not identical | Run full diff/test/secret-safe admission; no commit or push in this phase |
| High | Data volume is 99% full and evidence roots occupy about 41 GiB | Build an aggregate keep/delete candidate manifest; no deletion in this phase |
| High | Public data current still points at the 2026-08-10 release | Promotion remains downstream of a validated H1-R3 candidate and gets its own CAS/current gate |
| Medium | R2 observed frequent `invalid_json_content` | Measure from existing ledgers only; do not change retry behavior in a High-only phase |

---

### Task 1: Prove the Missing-Parent Installer Contract RED

**Files:**
- Create: `tmp/reddit-voc-v3/p2e-freshness-automation-20260810/g6r6-r1-parent-authority-closure-20260823/test_g6r6_r1_parent_authority_executor.py`
- Create later: `tmp/reddit-voc-v3/p2e-freshness-automation-20260810/g6r6-r1-parent-authority-closure-20260823/g6r6_r1_parent_authority_executor.py`

**Interfaces:**
- Consumes: a fake production root containing exact current release, stable launcher, child policy, owner permit, marker, cron and dual-receipt preimages, with the annual parent path absent.
- Produces: tests for `execute(root: Path, bundle: Path, injected_failure: str | None = None) -> Mapping[str, object]` and `recover(root: Path, bundle: Path) -> Mapping[str, object]`.

- [x] **Step 1: Write the success-path test before the executor exists**

The test creates the literal parent payload from the tracked fixture, runs `execute`, and asserts:

```python
self.assertEqual(result["status"], "committed_parent_authority_closure")
self.assertEqual(parent.read_bytes(), EXPECTED_PARENT_BYTES)
self.assertEqual(parent.stat().st_mode & 0o777, 0o444)
self.assertEqual(self.non_target_snapshot(), before)
```

The non-target snapshot covers current symlink target, stable, release launcher, report-control, child policy, owner, marker, cron, disposition and both dual authority receipts.

- [x] **Step 2: Add fail-closed and crash-recovery tests**

Add literal assertions for:

```python
test_parent_preexists_blocks_before_journal_or_mutation
test_any_bound_preimage_drift_blocks_before_parent_install
test_failure_after_parent_install_restores_absent_preimage
test_hard_crash_after_parent_install_recovers_forward_without_rewrite
test_payload_or_gate_sha_drift_is_rejected
```

- [x] **Step 3: Run the exact RED command**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python \
  tmp/reddit-voc-v3/p2e-freshness-automation-20260810/g6r6-r1-parent-authority-closure-20260823/test_g6r6_r1_parent_authority_executor.py
```

Expected: import/loader failure naming `g6r6_r1_parent_authority_executor.py` as absent. This is the intended RED because the wished-for production component does not exist yet.

### Task 2: Implement the Parent-Only Atomic Hotfix

**Files:**
- Create: `tmp/reddit-voc-v3/p2e-freshness-automation-20260810/g6r6-r1-parent-authority-closure-20260823/g6r6_r1_parent_authority_executor.py`
- Create: `tmp/reddit-voc-v3/p2e-freshness-automation-20260810/g6r6-r1-parent-authority-closure-20260823/payload/g6r5-annual-daily-live-policy.json`

**Interfaces:**
- Consumes: an exact gate manifest and the root-owned canonical parent payload SHA `98cbdd40...3cb4`.
- Produces: one immutable parent file plus a terminal diagnostic journal; all non-target hashes remain unchanged.

- [x] **Step 1: Implement strict readers and canonical gate validation**

Use `O_NOFOLLOW`, exact owner/mode checks, canonical JSON validation, fixed allowed/forbidden effect arrays, and exact SHA checks. Reject an existing parent path, unexpected symlink, changed current target, changed authority file, changed cron, changed disposition, changed release payload or expired authorization before writing the journal.

- [x] **Step 2: Implement the single-file transaction**

Under `/opt/reddit-voc-daily-report/control/locks/daily-report.lock`:

1. Revalidate every preimage.
2. Create a new transaction journal in phase `prepared`.
3. Write the parent to a same-directory temporary file as root-owned `0444`, fsync it, atomically publish it, then fsync the authority directory.
4. Revalidate parent SHA/mode/owner and every non-target preimage.
5. Atomically replace the journal with phase `committed` and emit a terminal receipt.
6. On a caught failure after publication, remove only the exact just-installed parent, fsync, verify the original absent preimage, and write phase `rolled_back`.

- [x] **Step 3: Implement bounded forward recovery**

`recover` accepts only a `prepared` journal plus the exact installed parent and unchanged non-target preimages. It validates the postimage and commits the journal without rewriting the parent. Any other combination blocks.

- [x] **Step 4: Run the same GREEN command**

Run Task 1 Step 3 unchanged. Expected: all tests pass and no file outside the fake root changes.

### Task 3: Freeze a Provider-Free G6R6-R1 Candidate

**Files:**
- Create: `tmp/reddit-voc-v3/p2e-freshness-automation-20260810/g6r6-r1-parent-authority-closure-20260823/freeze_g6r6_r1.py`
- Generate: `gate-manifest.json`, immutable archive, and `freeze-receipt.json` under the same directory.

**Interfaces:**
- Consumes: fresh production metadata/SHA snapshot and the tested executor.
- Produces: exact archive/gate/executor/receipt SHA values and an authorization sentence; no remote installation.

- [x] **Step 1: Bind exact fresh preimages**

Bind current release `7b177962...c181`, stable `e7dcd4bd...34a6`, launcher `6dcdddc2...7284`, report-control `b5959bfe...5431`, child policy `974f8ab4...c2df`, owner `eb4658b8...3dde`, marker `c2c93212...1a46`, cron `f54ff2dd...7251`, both dual authority receipts, disposition, transaction journal and parent-absent state.

- [x] **Step 2: Build and independently inspect the archive**

Require root archive metadata, directories `0555`, files `0444`, no symlink/hardlink/bytecode, exact file set, and provider/database/send/current/cron/credential/container effect flags all false.

- [x] **Step 3: Stop before production installation**

Production installation needs a fresh exact authorization binding the new archive/gate/executor SHA values and allowing only the one parent authority file plus diagnostic journal/receipt writes.

### Task 4: Refresh H1-R3 Translation Admission Without External Effects

**Files:**
- Read-only: existing H1-R3 archive/gate/executor/freeze receipt.
- Create: a local read-only preflight receipt under the phase-2 directory.

**Interfaces:**
- Consumes: checkpoint rows `29,757`, remaining `527`, Provider ledger rows `38`, R2 consumed permit/terminal chain.
- Produces: a current exact authorization proposal or a drift blocker.

- [x] **Step 1: Recompute local frozen hashes and archive invariants**
- [x] **Step 2: Read production hashes, counts and metadata only**
- [x] **Step 3: Confirm R3 runtime/candidate/permit/terminal/validation targets remain absent**
- [x] **Step 4: Keep DeepSeek execution outside this phase**

### Task 5: Run Git Admission Without Commit or Push

**Files:**
- Read-only: all tracked diffs and `.github/workflows/`.
- Create: a local Git admission receipt under the phase-2 directory.

**Interfaces:**
- Consumes: dirty working tree based on `15b286a2a4f807023b999eec8b96333ddfce7eb7`.
- Produces: changed-file classification, test results, secret-safe scan result and the exact commit/push gate scope.

- [x] **Step 1: Classify every dirty file by feature and provenance**
- [x] **Step 2: Run `git diff --check`, affected backend tests and repository secret-pattern scan without opening ignored credential files**
- [x] **Step 3: Confirm `HEAD=origin/main` and the current GitHub CI run is green**
- [x] **Step 4: Do not commit or push until the complete diff is accepted as one coherent release candidate**

### Task 6: Produce a Deletion-Free Disk Candidate Manifest

**Files:**
- Create: a local aggregate-only storage receipt under the phase-2 directory.

**Interfaces:**
- Consumes: bounded `du`, path metadata and known audit/frozen-bundle roots.
- Produces: `must_keep`, `review_before_delete`, and `rebuildable_candidate` groups with aggregate bytes; no delete command.

- [x] **Step 1: Inventory only repository `tmp/`, `output/`, `.git` and `.venv`**
- [x] **Step 2: Mark H1-R2/R3, G6R6 production receipts and current release inputs as `must_keep`**
- [x] **Step 3: Classify large historical candidate roots by whether a tracked source and immutable receipt can rebuild them**
- [x] **Step 4: Request target-specific approval before trashing or deleting any selected root**

### Task 7: Update the Project Handoff and Stop at External Gates

**Files:**
- Modify: `PROJECT_STATUS.md`

**Interfaces:**
- Consumes: all fresh receipts from Tasks 3–6.
- Produces: corrected natural-cycle status, exact next authorization statements and unchanged Medium/Low deferrals.

- [x] **Step 1: Replace the false assumption that annual authority was fully installed**
- [x] **Step 2: Record facts, inference and unknowns separately**
- [x] **Step 3: List the next independent gates in order: parent install, next natural-cycle observation, H1-R3 DeepSeek continuation, candidate validation/public CAS, Git push, disk cleanup**

## Self-Review Checklist

- [x] Every High risk has one owner gate and one terminal evidence requirement.
- [x] The parent hotfix modifies exactly one production authority file plus its own diagnostic evidence.
- [x] The consumed G6R6 activation bundle remains byte-for-byte untouched.
- [x] The phase contains no live Provider, TikHub, DingTalk, database, cron/current, Git push or delete action.
- [x] RED and GREEN use the same command.
- [x] All claims are backed by fresh command output or a receipt SHA.
