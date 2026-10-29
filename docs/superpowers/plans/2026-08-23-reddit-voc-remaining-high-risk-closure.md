---
title: Reddit VOC 剩余 High 风险闭环实施计划
doc_type: implementation_plan
status: external_gates_frozen_awaiting_exact_authorizations
created: 2026-08-23
updated: 2026-08-23
evidence_scope: local_and_production_read_only_until_exact_authorization
---

# Reddit VOC Remaining High-Risk Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 2026-08-23 尚未闭合的 High 风险拆成独立证据链，立即完成本地与生产只读准入，并把生产 authority 安装、DeepSeek 外呼、TikHub 区域域名诊断、public data current、Git 发布和磁盘删除压缩为各自唯一的精确门禁。

**Architecture:** 日报 runtime/authority、公开站翻译、TikHub comments、公开站 data current、Git 版本和本地存储使用不同的 current/ledger/receipt，不允许用一条链的成功替代另一条。每条任务遵循“固定复现 → 单一根因假设 → 最小动作 → 相同复现复验”，生产副作用只在绑定 exact SHA、前像、允许项和禁止项的新授权后执行。

**Tech Stack:** Python 3、`unittest`、SHA-256 immutable release/receipt、SSH production read-only observer、Git/GitHub Actions、macOS APFS。

**Spec:** `PROJECT_STATUS.md`

## Global Constraints

- 当前工作区是用户已有的 dirty `main`，不创建 worktree、不重置、不覆盖、不格式化无关改动；本计划不自动 commit/push。
- 当前笼统的“开始执行”只授权本地写入和生产只读检查，不授权生产上传/安装、DeepSeek/TikHub 调用、钉钉发送、数据库访问或写入、cron/current/authority/credential/container 变更。
- `config/production-version-lock.json` 描述已部署生产前像；在 successor release 未部署前不得把它改成候选 SHA 来制造测试通过。
- 不读取或输出 `.env`、API key、webhook、私钥或 credential 内容；远端只允许读取路径 metadata、SHA、symlink target、非敏感 ledger 状态和终态 receipt。
- 同一问题最多两轮代码修改；连续两轮相同复现仍不通过时，停止第三次修改并执行用户要求的止损报告。
- 每条成功声明必须绑定本轮新鲜命令、exit code、测试计数和 receipt SHA；L2 本地候选、L3 生产只读、L4 授权 live 不得混写。

---

### Task 1: 固定剩余 High 风险基线和复现

**Files:**
- Read: `PROJECT_STATUS.md`
- Read: `config/production-version-lock.json`
- Read: `tests/test_version_consistency.py`
- Read: `tmp/reddit-voc-v3/p2e-freshness-automation-20260810/g6r6-r1-parent-authority-closure-20260823/production-readonly-preflight.json`
- Read: `tmp/high-severity-remediation-20260822/h1-translation-resume-20260823-r3/freeze-receipt.json`

**Interfaces:**
- Consumes: 当前 Git HEAD/dirty files、生产 version lock、G6R6-R1/H1-R3 frozen receipts。
- Produces: 六条互斥风险链和每条固定验收命令：natural authority、daily release/Git、公开翻译、磁盘、TikHub comments、公开 data current。

- [x] **Step 1: 记录 Git 和磁盘基线**

Run:

```bash
git status --short --branch
git rev-parse HEAD
git rev-parse origin/main
df -k /System/Volumes/Data
du -sk tmp output .git .venv
```

Expected: 不修改工作区；精确记录 dirty file set、HEAD、available KiB 和四个根目录大小。

- [x] **Step 2: 固定 daily release 失败复现**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest \
  tests.test_version_consistency.VersionConsistencyTests.test_local_source_rebuilds_the_locked_daily_release
```

Expected: 只允许以 `daily_source_release_mismatch` 失败；任何 import、manifest 缺失或随机错误都表示根因尚未固定。

- [x] **Step 3: 固定生产自然周期失败证据**

只读复核 production current、cron、stable、release launcher/report-control、annual parent/child/owner/marker 和当天 `cron-report.log` 终态。Expected: annual parent path absent，child/owner 仍绑定 parent SHA `98cbdd40b6b7ce06b15c5fd73d6f9a9329c22fc8f78cf6df114fcff3764c3cb4`，日志保持 `parent_policy_invalid` → `scheduled_cycle_reserve_failed`；不得读取 credential 内容或数据库。

### Task 2: 构建 daily successor release 本地一致性候选

**Files:**
- Read: `scripts/build_daily_report_release.py`
- Read: `src/reddit_voc/deepseek_client.py`
- Read: `tests/test_deepseek_client.py`
- Create: `tmp/reddit-voc-v3/p2e-freshness-automation-20260810/g6r6-r2-daily-release-consistency-20260823/releases/<release_sha>/`
- Create: `tmp/reddit-voc-v3/p2e-freshness-automation-20260810/g6r6-r2-daily-release-consistency-20260823/local-candidate-receipt.json`

**Interfaces:**
- Consumes: production-pinned image ID `sha256:2e8dbc0225c2517ba58eb6151fab95ff271471c28e270515076e1b64e5334cb1` and current dirty source.
- Produces: immutable local daily release candidate plus self-contained verify/import evidence; does not change production lock.

- [x] **Step 1: State the one root-cause hypothesis**

Hypothesis: `daily_source_release_mismatch` is deterministic because exactly the dirty release members `src/reddit_voc/deepseek_client.py` and `tests/test_deepseek_client.py` differ from production release `7b177962...c181`; rebuilding current source must produce the same successor SHA twice.

- [x] **Step 2: Build twice with the existing release builder**

Run the same build command twice against one isolated destination root:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/build_daily_report_release.py build \
  --source-root . \
  --destination-root tmp/reddit-voc-v3/p2e-freshness-automation-20260810/g6r6-r2-daily-release-consistency-20260823/releases \
  --image-id sha256:2e8dbc0225c2517ba58eb6151fab95ff271471c28e270515076e1b64e5334cb1
```

Expected: 两次输出的 `release_sha256` 和 `manifest_sha256` 完全一致，第二次复用已验证的 immutable directory。

- [x] **Step 3: Verify fileset and import closure**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/build_daily_report_release.py verify \
  --release-dir tmp/reddit-voc-v3/p2e-freshness-automation-20260810/g6r6-r2-daily-release-consistency-20260823/releases/750cfe171bdc2065b74e071fdd1d2601ca47222adc4c5bf7e20613aa6511d82f
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/build_daily_report_release.py verify-imports \
  --release-dir tmp/reddit-voc-v3/p2e-freshness-automation-20260810/g6r6-r2-daily-release-consistency-20260823/releases/750cfe171bdc2065b74e071fdd1d2601ca47222adc4c5bf7e20613aa6511d82f
```

Then use Python `tempfile.TemporaryDirectory(prefix="reddit-voc-g6r6-r2-")` to build the identical source outside `/Users/pray/project/Reddit_VOC` and run `verify-imports --forbidden-root /Users/pray/project/Reddit_VOC` against that external copy. Expected: the persistent and external builds both equal release `750cfe171bdc2065b74e071fdd1d2601ca47222adc4c5bf7e20613aa6511d82f`; manifest/fileset/mode/SHA 全通过，external copy reports `repository_fallback=false`. The external directory is automatically removed by `TemporaryDirectory`.

- [x] **Step 4: Run directly affected runtime tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest \
  tests.test_deepseek_client \
  tests.test_daily_report_release \
  tests.test_daily_report_launcher \
  tests.test_daily_report_wrapper
```

Expected: 全部通过；不修改 production lock 或硬编码测试期望。

- [x] **Step 5: Record an L2 candidate receipt**

Receipt must include source HEAD, dirty release members, image ID, release/manifest SHA, two-build determinism, verify/import/test results, `production_changed=false`, `version_lock_changed=false`, `commit_executed=false`, and `push_executed=false`.

### Task 3: 刷新 G6R6-R1 parent-only 生产准入

**Files:**
- Read: `tmp/reddit-voc-v3/p2e-freshness-automation-20260810/g6r6-r1-parent-authority-closure-20260823/gate-manifest.json`
- Read: `tmp/reddit-voc-v3/p2e-freshness-automation-20260810/g6r6-r1-parent-authority-closure-20260823/freeze-receipt.json`
- Create: `tmp/reddit-voc-v3/p2e-freshness-automation-20260810/g6r6-r1-parent-authority-closure-20260823/authorization-proposal.json`

**Interfaces:**
- Consumes: exact archive `7d4d0d72...e6547`, gate file `f64c7843...7635`, executor `74b663f1...20b3`, parent payload `98cbdd40...3cb4`, current production preimages.
- Produces: fresh L3 preflight and one exact L4 authorization proposal; no upload/install.

- [x] **Step 1: Re-run the six local executor tests and deterministic freeze**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest \
  tmp.reddit-voc-v3.p2e-freshness-automation-20260810.g6r6-r1-parent-authority-closure-20260823.test_g6r6_r1_parent_authority_executor
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python \
  tmp/reddit-voc-v3/p2e-freshness-automation-20260810/g6r6-r1-parent-authority-closure-20260823/freeze_g6r6_r1.py
```

If the dotted unittest path is not importable because of hyphenated directories, run the same test file by exact filesystem path with unittest discovery; do not modify code to mask an import-path issue.

- [x] **Step 2: Run a structure-only production observer**

Using strict known-host verification, read only lstat/SHA/symlink targets for daily current, stable, launcher, report-control, cron, disposition, child, owner, marker, metadata-only receipts, parent/journal/terminal existence and shared-lock metadata. Expected: every bound preimage matches gate; parent/journal/terminal remain absent.

- [x] **Step 3: Write the exact authorization proposal**

Allowed effects: upload exact frozen archive; under shared lock atomically install only `/opt/reddit-voc-daily-report/control/authority/g6r5-annual-daily-live-policy.json` as `root:root 0444`; write only G6R6-R1 journal and terminal receipt; restore absent parent on any pre-commit failure and perform forward recovery for marker-last crash evidence.

Forbidden effects: Provider/TikHub/DeepSeek, DingTalk, database, cron/current/stable/launcher/report-control/child/owner/marker/disposition/credential/container changes. Proposal status remains `awaiting_exact_user_authorization`.

### Task 4: 刷新 H1-R3 公开站翻译准入

**Files:**
- Read: `tmp/high-severity-remediation-20260822/h1-translation-resume-20260823-r3/freeze-receipt.json`
- Read: `tmp/high-severity-remediation-20260822/h1-translation-resume-20260823-r3/frozen-bundle/gate-manifest.json`
- Create: `tmp/high-severity-remediation-20260822/h1-translation-resume-20260823-r3/authorization-proposal.json`

**Interfaces:**
- Consumes: archive `aa88e752...01b5`, gate `8c2c6f64...b9d9`, executor `6e78eae1...088d`, checkpoint 29,757 rows, Provider ledger 38 rows, remaining 527.
- Produces: fresh L3 preflight and one exact Provider authorization proposal; no Provider call.

- [x] **Step 1: Re-run source and executor regressions plus deterministic freeze verification**

The freeze entrypoint is intentionally create-once and rejects pre-existing outputs. Do not delete or overwrite the frozen evidence. Re-run the exact 79 source regressions and 12 executor regressions, compare every live runtime source SHA with `runtime_payload_sha256`, and rebuild the archive bytes from the immutable `frozen-bundle` in `TemporaryDirectory`. The temporary reconstruction must reproduce the exact archive/gate/executor SHA values and is automatically removed; no Provider call is allowed.

- [x] **Step 2: Re-read only production preimages**

Verify checkpoint/ledger rows and SHA, consumed R2 permit/terminal/builder receipt, source/reuse manifests, lock/metadata and absence of R3 runtime/candidate/permit/validation/terminal. No source text, translation text, key content or database may be read.

- [x] **Step 3: Write the exact authorization proposal**

Allowed effects: upload/install the exact frozen archive; submit only remaining Reddit public title/body/comment fields to production-configured DeepSeek `deepseek-v4-flash`; maximum 71 external attempts including bounded same-process retries; one worker; write only new execution permit, isolated checkpoint, Provider ledger, candidate and validation/terminal receipts.

Forbidden effects: credential output/persistence as business content, database access/write, TikHub/collection, DingTalk, cron/current/authority/credential/container changes, cross-process retry, automatic resend or public current switch. Proposal status remains `awaiting_exact_user_authorization`.

### Task 5: Storage、Git 和文档终态验收

**Files:**
- Modify: `PROJECT_STATUS.md`
- Modify: `README.md` only if the status entry changes materially
- Read: `tmp/reddit-voc-v3/p2e-freshness-automation-20260810/g6r6-r1-parent-authority-closure-20260823/storage-candidate-receipt.json`

**Interfaces:**
- Consumes: Tasks 1–4 receipts and current worktree.
- Produces: current evidence map and remaining exact gates; no deletion/commit/push/deploy.

- [x] **Step 1: Revalidate the two rebuildable deletion candidates**

Check exact realpath, symlink status, size, adjacent package lock, active-process/open-file evidence where available, and references from current receipts. Keep deletion blocked unless the user names the exact targets; do not remove the 15 GiB mixed `candidate-orchestration` root.

- [x] **Step 2: Re-run verification**

Run `git diff --check`, directly affected tests, G6R6-R1 tests, H1-R3 tests and the full Python suite. The production-lock test may remain the single expected blocker until successor deploy; any additional failure is a regression and blocks handoff.

Result: `git diff --check` passed；本轮 57 个 fresh 受影响源码/适配器测试、G6R6-R1 6/6、H1-R3 12/12 通过。完整 discovery 运行 1776 tests / 333.317s，唯一 error 是预期的 `daily_source_release_mismatch`，没有第二个回归。

- [x] **Step 3: Update status with evidence grades**

Record L2 successor release, L3 parent/H1 preflights, exact L4 blockers, disk available KiB and Git dirty lanes. Do not call local/GitHub/production consistent, do not call automatic 08:00 restored, and do not call the remaining 527 translations complete.

- [x] **Step 4: Final self-review**

Compare every modified file against this plan, run `git status --short --branch`, and report only actual changes, test results and remaining risks. No success claim may rely on a prior-turn test alone.

### Task 6: TikHub comments 与公开站 data current 独立只读闭环

**Files:**
- Read: `src/reddit_voc/tikhub.py`
- Read: 2026-08-22 source/comment diagnostic receipts already referenced by `PROJECT_STATUS.md`
- Create: `tmp/reddit-voc-v3/p2e-freshness-automation-20260810/g6r6-r2-daily-release-consistency-20260823/public-current-and-tikhub-readonly-receipt.json`

**Interfaces:**
- Consumes: production site/data current symlinks and immutable manifests; current official TikHub comments endpoint contract; existing HTTP 400 metadata.
- Produces: a fresh L3 public-current identity and a provider-free TikHub contract decision; no API call or current switch.

- [x] **Step 1: Refresh production public current without database or container access**

Using strict known-host verification, read only `/opt/reddit-voc-insights-site/current`, `/opt/reddit-voc-insights-data/current`, their immutable manifests and non-sensitive `data_release_id`/`data_as_of` fields. Record exact site/data target and manifest SHA. Do not read database, credential or private source content.

- [x] **Step 2: Compare the implemented comments route with current official documentation**

Read `src/reddit_voc/tikhub.py` and primary TikHub documentation only. Compare route, Reddit ID shape, required query/body fields and response/error contract. Do not call TikHub, do not submit a post ID or API key, and do not infer a fix when the official contract is unavailable.

- [x] **Step 3: Freeze the next minimal diagnostic decision**

If an exact local contract mismatch is proven, add a failing adapter test in a later High-only gate before changing code. If no mismatch is proven, keep HTTP 400 classified as upstream/contract unknown and require one separately authorized bounded Provider probe. Public current remains a separate candidate/build/CAS gate after H1-R3 validation; no daily-report receipt may promote it.

Result: route/query/ID shape 与官方 Reddit APP comments 文档一致，12/12 adapter tests 通过；未证明本地 route contract mismatch。官方生产 API root 新增中国大陆 `.dev` 指引，而仓库默认仍为 `.io`，生产 env override 因 secret boundary 未读取。已生成一次 `.dev` 对照探针 proposal，状态 `awaiting_exact_user_authorization`。生产/public pointer SHA 精确相同但仍为 `data_as_of_utc=2026-08-08T23:00:00Z`、freshness=`partial`；未执行 Provider 或 current switch。

### Task 7: 刷新漂移证据并冻结外部风险执行序列

**Files:**
- Create: `tmp/reddit-voc-v3/p2e-freshness-automation-20260810/g6r6-r2-daily-release-consistency-20260823/external-risk-fresh-readonly-preflight-20260823T080555Z.json`
- Create: `tmp/reddit-voc-v3/p2e-freshness-automation-20260810/g6r6-r2-daily-release-consistency-20260823/public-current-storage-refresh-20260823T080922Z.json`
- Create: `tmp/reddit-voc-v3/p2e-freshness-automation-20260810/g6r6-r2-daily-release-consistency-20260823/storage-cleanup-expanded-authorization-proposal.json`
- Modify: `PROJECT_STATUS.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: Tasks 1–6 的冻结门禁、2026-08-23 16:03 BJT 后的新鲜生产前像、public HTTPS pointer、本机 APFS 容量。
- Produces: 可按顺序逐个授权的最小外部门禁；不把泛化授权扩展为删除、Provider、生产写入、current 切换、commit 或 push。

- [x] **Step 1: 同一路径刷新 daily authority 与 H1-R3 前像**

结构化 SSH observer 在不读取 credential/数据库、不操作容器和不写远端的边界内重新核验 18 个绑定点。结果 18/18 匹配：daily current 和 11 个 authority/runtime preimage 未漂移，annual parent/G6R6-R1 journal/terminal 仍 absent；H1 checkpoint 仍为 29,757 行、Provider ledger 38 行，R3 runtime/candidate/permit/validation/terminal 仍 absent。fresh receipt SHA=`9a1fde7d6edac42d6abb2d6ff0109493426eb3ef61be802b834fa98abd53926c`。

- [x] **Step 2: 刷新 public current 与本机容量**

生产 site current 仍为 `da9b94b5...2acc`，data current 仍为 `reddit_voc_release_20260810_observed_translation_v1`；8 个 bound manifest SHA 全匹配。公网 pointer HTTP 200、body SHA=`e9c6d4aa...a824c` 与生产完全一致，`data_as_of_utc=2026-08-08T23:00:00Z`、freshness=`partial`。本机 Data volume 的 `df -P` 已为 100%，available=`4078256 KiB`。fresh receipt SHA=`36ac702cbce0ab1dacc955c854c784ca31b500f2c12775161d901cab9024ce0c`。

- [x] **Step 3: 扩展但不执行可重建缓存清理门禁**

新增两个有 `package.json + package-lock.json` 的 reference UI `node_modules`，与原 preview `node_modules`、Python `__pycache__` 合并为四个 exact target；全部为 non-symlink regular directories、open-file=0，预计回收 `757552 KiB`。禁止整删约 15 GiB 的 mixed `candidate-orchestration`，也禁止触碰 output/private export/receipt/frozen bundle/`.git`/`.venv`。proposal 状态保持 `awaiting_exact_target_deletion_authorization`。

- [ ] **Step 4: G6R6-R1 parent authority 原子安装**

这是恢复自然 08:00 reservation 的第一生产写门禁。只接受 `authorization-proposal.json` 中完整 `required_user_ack`，执行时先复算 archive/gate/executor/preflight；仅安装一个 root-owned `0444` parent 文件和自身 journal/terminal。完成后只能表述 authority closure，不能表述日报已发送。

- [ ] **Step 5: TikHub `.dev` 单次对照与后续条件分支**

使用 proposal ack `g6r6_tikhub_dev_domain_probe_20260823:one_exact_comments_get_no_database` 时，只允许同一 frozen public fullname 对 `https://api.tikhub.dev/api/v1/reddit/app/fetch_post_comments` 发起一次 GET，不得回退 `.io`、输出 ID/key、访问数据库或自动重试。若 HTTP 200 且存在 comment nodes，再单独构建 domain overlay TDD/安装门禁；若仍 400，只记录脱敏 provider code/docs/detail，停止猜改代码。

- [ ] **Step 6: H1-R3 翻译续跑与 public data CAS**

先按 H1-R3 exact proposal 完成剩余最多 527 个公开字段、最多 71 次 external attempts 和 validation；candidate 未通过不得进入 current。通过后从已准入 source + translation 构建独立 public data candidate，复验日/周/月同环比、同比、六点趋势及帖子标题/正文/评论中文，再开独立 data-current CAS。禁止用 daily current 或钉钉 delivery 代替 public current 证据。

- [ ] **Step 7: daily successor Git/production 三端闭环**

对 12 个 exact dirty paths 进行 secret scan、受影响测试和完整 suite 复验后，另行冻结 Git staging allowlist/commit/push 授权；GitHub green 后才能构建生产激活 permit。生产激活成功再更新 `config/production-version-lock.json` 并复跑三端 verifier，不得先改 lock 让测试假绿。

#### 执行顺序与停止条件

1. 本机 100% 容量风险先用 exact 四路径清理门禁缓解；该动作预计只回收约 740 MiB，不能把磁盘风险标为关闭。
2. G6R6-R1 parent install 必须在下一次自然 08:00 前完成；任何 preimage 漂移都终止，不自动重冻或重试。
3. TikHub `.dev` 一次探针必须在 domain overlay 之前；没有 200/comment evidence 禁止修改生产域名。
4. 下一个自然 07:00→08:00 周期只读验收必须同时核验 source、translation/provider ledger、prepared、同一 outbox 的两个 destination terminal sent、DB projection 和 cycle=`send_consumed`。
5. H1-R3/public data 与 daily/DingTalk 是独立链，可在不触碰彼此 current 的前提下顺序执行；任一 validation failure 保持旧 public current。
6. Git commit/push、daily release activation、public data CAS 各自需要独立 exact authorization；任何一步失败都保持旧 current/lock，不用第二次代码修改碰运气。

## Self-Review Checklist

- [x] Six High-risk chains are independent and have separate completion evidence.
- [x] No plan step upgrades L2/L3 evidence to L4.
- [x] The daily release test is not weakened and the production lock is not falsified.
- [x] Parent installation and H1-R3 external execution each require a fresh exact authorization.
- [x] Disk cleanup, commit/push, deployment and public current switching remain separately gated.
- [x] There are no placeholder tasks, broad destructive targets or automatic retry/resend paths.
