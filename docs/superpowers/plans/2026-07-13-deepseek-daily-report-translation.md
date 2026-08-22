# DeepSeek Daily Report Translation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the production daily report translation lane with a fail-closed `deepseek-v4-flash` prepared-report workflow that displays complete Chinese content first, only a bounded deterministic English excerpt afterward, and preserves exact English source text in HTML/CSV/XLSX attachments and Reddit links.

**Architecture:** Split the workflow into a read-only `prepare` phase and a frozen-byte `send` phase. Prepare filters visible source rows before any Provider call, translates and independently validates each post, and renders immutable public/private bundles. In production the networked prepare worker stops at a verified commit request; after all gates are off, a host-side Provider-neutral helper from the same immutable release re-verifies the candidate and atomically advances the pointer/projections/commit registry without mounting host control state into the container. Send never imports DeepSeek or rebuilds content; it verifies the pointer, hashes, artifact HEAD responses, delivery ledger and duplicate guards before transmitting the exact prepared DingTalk bytes. A fixed host launcher runs short-lived digest-pinned containers on a dedicated report network and leaves collector, backfill, webapp, Nginx, cron and shared networks unchanged.

**Tech Stack:** Python 3.11+, stdlib `argparse`, `concurrent.futures`, `dataclasses`, `hashlib`, `json`, `pathlib`, `sqlite3`, `urllib`, existing Pillow/openpyxl, shell wrappers, Docker CLI, and existing `unittest`. Add no dependency.

## 中文执行摘要

- 日报正文固定中文在前；英文只保留确定性节选，完整英文保留在
  HTML/CSV/XLSX 附件与 Reddit 原帖链接。
- 目标模型固定为 `deepseek-v4-flash`，翻译后再用独立请求做语义复核；
  任一结构、实体、语义、预算或产物校验失败，整份日报 fail-closed。
- `prepare` 只读生产源数据并冻结不可变产物；`send` 只发送已冻结 bytes，
  不导入 DeepSeek、不重新翻译、不重新渲染。
- Tasks 1–12 只完成本地 mock、测试、fake-host、release 候选和文档，默认
  `provider_call=false`、`live_send=false`、`production unchanged`。
- L2 真实 DeepSeek shadow 已按三个逐包授权执行且均 fail-closed；第三次 post-block
  repair 得到 4 blocked + 50 pending，semantic validation 和 L3 均未开始。后续只读
  输入诊断证明通用 `protected_entity_changed` 行原因不能解释为四项都有实体类别：
  4 项都有数字类别，只有 2 项另含型号。新的本地 protected-placeholder repair 已形成
  精确待授权 packet，但尚未触发第四次 Provider。L4 host 窄发布和
  L5 生产 prepare 仍需要各层独立授权与真实证据；owner 最新决策是不推送钉钉，
  因此固定 launcher 不执行 L6/L7 send。
- collector、backfill、主站、Nginx、cron、LibreTranslate 和共享网络不在
  本次改动范围；所有 runtime 动作使用同一 report lock 和独立一次性容器。

## 2026-07-14 实施状态记录

本节记录计划批准后的实际执行证据；下方逐步 checklist 保留原始实施说明，不以
未勾选状态覆盖本节的新鲜事实。

- Tasks 1–10 的核心代码已在当前工作区实现：固定 DeepSeek 请求、帖子级翻译、
  独立语义复核、两级 cache、响应/attempt/usage 证据、中文在前 renderer、完整
  英文附件、immutable prepared bundle、prepare/send 分离、发送账本、显式 resend、
  失败告警双门禁、wrapper 和 provider-free runtime smoke。
- protected-placeholder 聚焦回归为 `62/62`；最新独占 split full validation 为固定
  Python 3.12 unittest `654/654`、0 failure、0 error，加系统 Python 3.9 pytest-only
  模块 `3/3`。runtime smoke 精确输出
  `runtime_smoke=passed`、`translation_provider_attempt_made=false`、
  `report_live_send=false`、`live_send=false` 和
  `database_write=local-test-only`。
- Task 11 已形成通过本地 fixture/fake-host 验证的候选：release/import closure、
  exact container inspect、gate/permit recovery、
  `bootstrap|activate|rollback|recover-prepared-state|commit-prepared|commit-blocked`、
  `capture-host` 非干扰事实与一次性 `prepare_only` schedule permit。无参数 cron 只
  prepare；固定 launcher 的 send 分支无条件 `dingtalk_disabled_by_owner`。
- 当前可声明：`local_core_implementation=L1_verified`、`l2_status=blocked`。
  semantic-fix replacement 绑定 request
  `deepseek-l2-semanticfix-replacement-20260714-175924`、release
  `eec615b6...e29d4` 与复制库 `b4151728...c92d7c`，完成 9/9 个真实
  `deepseek-v4-flash` translation 响应、0 retry，但 manifest 把 54/54 项统一记为
  pending 并被 `protected_entity_changed` 阻断；后续审计证明只能确认至少一项失败。
  semantic validation 和 L3 均未开始。该历史节点为
  18/100 attempts，剩余 82。
- post-block repair 已在本地完成：跨 bundle 聚合可归因失败、pending 行不再复制逐项
  错误码、非规范型号大小写允许规范化但型号身份变化仍拒绝。候选 release
  `861a88d8...a5f54`、manifest `193035f2...4174`、validation
  `9f8f0961...0668` 与 packet `13f576a3...80a5` 已闭包验证，随后获得 owner
  明确授权并执行一次。9/9 translation 响应成功、0 retry，但 4 项被阻断，其余
  50 项 pending；`protected_entity_changed` 是通用行原因，4 项都有数字类别，只有
  2 项另含型号类别。semantic validation 未运行。
  blocked manifest `6f3ecb2b...2da4d`，终态证据 `106c2904...eb784`，累计
  27/100 attempts，剩余 73。数字表面格式合同未放宽。
- 新 protected-placeholder repair 在 Provider payload 前把每个最大受保护 span 换成
  collision-safe occurrence marker，要求逐个原样且恰好一次返回，再在本地恢复 source
  bytes 后执行原有确定性与 semantic gates。复制输入 provider-free 回放覆盖 9 帖、
  9 bundles、54 items，32 items / 157 markers，零残留、零 namespace collision、精确
  byte round-trip。release `bc51d736...340e4`、manifest `e4edef8f...9d92`、validation
  `a6be9cc3...43f2` 与 packet `7f76571b...3002` 已闭包验证。该 packet 随后获得
owner 批准并在 Provider 前以 `runtime_env_required_value_missing` fail-closed；
没有消耗新的 Provider attempt，两个 permit 已 terminal `blocked`。新的 runtime-fix
候选补齐 runner 所需五个非 secret 基础字段，绑定 validation
`e066dd14...54daa2` 与 packet `f1f9b99d...ce066`，随后获 owner 精确授权并执行一次；
该 replacement 又在 Provider 前以 `runtime_env_required_name_missing` fail-closed，
因为模板缺少 materializer 要覆盖的动态 env 名称。两个 replacement permit 已
terminal `blocked`，没有第四次 Provider request。
- A second local repair then added all 18 names required by the immutable
  materializer replacement step, in addition to the five base values. Static
  parser/replacement round-trip passed with blank webhooks and all gates off.
  New packet `deepseek-l2-protected-placeholder-runtimefix-fields-20260714-225341`
  was approved and completed exactly once, SHA
  `355d95b17702386de786dc53ed78eb49f276e0c2c9ffd79f1a6c9752c80e5ceb`, with
  validation SHA `b54b283079d380d83d9e418f71baa66c1c810fd7ec82e4ae598f070fb800240c`,
  runtime SHA `8aeb1ae50f2d2a7040630b3957b4d379dc796c5c2382aab8a72591685eaaf0c6`,
  and cap 73. Its two permits are consumed, gates are restored all-off, and
  no L3/L4/L5 action follows automatically.
- 隔离 key 仅经 stdin/no-log 路径安装/使用，内容未输出；没有真实 DingTalk、
  Docker、cron/service 或生产数据变更。permit 已 terminal `blocked`，gates all-off，
  runtime 已清理。不能声明 `host_release_ready`、L3 acceptance、L4 release 或 L5
  prepare 完成。

## Global Constraints

- Approved design source of truth:
  `docs/superpowers/specs/2026-07-13-deepseek-daily-report-translation-design.md`.
- At initial plan approval time, plan approval alone did not authorize implementation, DeepSeek calls, key reads, live sends, deployment, Docker/network mutations, cron reloads, service restarts or production writes. Later owner instructions separately authorized the exact L2 shadow packets recorded below; the latest permit pair is terminal `consumed`, earlier pairs are terminal `blocked`, and none grants L3/L4/L5 or send authority.
- Evidence layers stay separate: L1 local mock/fake-host, L2 real DeepSeek shadow,
  L3 human review, L4 narrow runtime release and L5 production prepare dry-run。
  L6/L7 send 层仍保留为历史设计层，但按 owner 最新指令不执行。
- Keep these current boundary labels literal until fresh evidence changes them:
  `implementation_started=true`, `local_core_implementation=L1_verified`,
  `host_release_ready=false`, `l2_status=blocked`, `translation_provider_call=true`,
  `translation_provider_attempt_made=true`, `provider_attempt_made=true`,
  `semantic_validation_phase_attempt_made=false`, `live_send=false`,
  `production unchanged`, `deepseek_attempts_consumed=27` and
  `deepseek_attempts_remaining=73`.
- The production model is exactly `deepseek-v4-flash`. The fixed endpoint is
  `https://api.deepseek.com/chat/completions`; production configuration may not redirect it.
- Translation failure, semantic-validator failure, schema drift, model drift, entity loss, hard-cap breach, ambiguous cache, bundle tampering, artifact HEAD failure or uncertain delivery state blocks the whole report. Do not fall back to LibreTranslate or an English-only message.
- DingTalk order is Chinese title, Chinese voice, Chinese comments, Chinese business judgment, `source_excerpt_v1`, then the Reddit URL. English excerpt compression may never remove Chinese content or the URL.
- HTML and CSV preserve exact source fields. XLSX normalized continuation rows use at most 30,000 Unicode code points and must round-trip exact title/body/comment text.
- Filter visibility from source data before constructing Provider input. Cap at 50 visible posts, 40,000 source characters per post, 250,000 per report and 100 total DeepSeek HTTP attempts including retries.
- Translation and semantic validation share one 300-second monotonic deadline; concurrency is 2; per-attempt socket timeout is at most 45 seconds.
- Prepare opens one SQLite `mode=ro` connection, sets `PRAGMA query_only=ON` and never calls `migrate()` or writes `delivery_previews`.
- Send consumes frozen canonical bytes, performs no translation/rendering, and
  imports only the neutral `prepared_bundle` verifier; it does not import
  `prepared_report`, `daily_report`, `deepseek_client` or
  `translation_pipeline`, directly or transitively.
- Host owner permits, gate journals, authorization audit and gate recovery live
  under mode-700 `/home/ubuntu/.reddit-voc/report-control/`, never under the
  container-writable prepared state and never mounted wholesale into any
  container. A live prepare receives only its exact authorization attempt-sink
  directory; send receives only its exact run-level delivery-ledger directory.
- Leave legacy `build-daily-report`, `send-daily-report-live` and LibreTranslate code in place for regression/owner-directed rollback. The new production wrapper must not call them.
- Do not modify collector, backfill, database schema/migrations, Nginx, cron content, webapp Compose, LibreTranslate Compose or `scripts/deploy_webapp_tencent.sh`.
- Do not read or print `.env`, the DeepSeek key, webhook or secret values. Tests use synthetic secrets and assert redaction.
- Do not commit unless the owner separately authorizes it. Use `git diff --check` and `git status --short` checkpoints.
- Run shared SQLite/output tests serially with:
  `/Users/pray/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3`.

---

## File Map

Create:

- `src/reddit_voc/report_contracts.py` — canonical JSON, strict schema-subset validation and safe regular-file asset loading; no Provider imports.
- `src/reddit_voc/deepseek_client.py` — fixed DeepSeek HTTP envelope, bounded reader, retry/deadline/attempt accounting and sanitized evidence.
- `src/reddit_voc/translation_pipeline.py` — stable translation bundles, prompt/terms versions, deterministic and semantic gates, source signals and two-level output/cache digests.
- `src/reddit_voc/prepared_bundle.py` — Provider-neutral prepared roots/models,
  strict immutable bundle/current verification, host-side commit transaction
  and outbox loading used by both prepare and send.
- `src/reddit_voc/prepared_report.py` — single read-only source snapshot, prefilter, cache discovery, translation/renderer orchestration, blocked evidence and immutable commit/projection transactions.
- `src/reddit_voc/daily_report_delivery.py` — prepared loader, artifact HEAD checks, hash-chain ledger, duplicate/resend admission and exact-byte sending.
- `config/translation_terms.json`.
- `config/prompts/deepseek-translation-v1.txt`.
- `config/prompts/deepseek-semantic-validator-v1.txt`.
- `config/schemas/daily-translation-manifest-v1.schema.json`.
- `config/schemas/daily-translation-attempt-v1.schema.json`.
- `config/schemas/daily-prepared-bundle-index-v1.schema.json`.
- `config/report/reddit-voc-report.env.example` — gates off and secret values empty.
- `scripts/build_daily_report_release.py` — exact release manifest builder/verifier.
- `scripts/report_runtime_smoke.py` — isolated synthetic no-key/no-network/no-send release/config/import/bundle smoke.
- `scripts/report_noninterference.py` — redacted capture and L4/L5/L6 allowlist comparison.
- `scripts/server_daily_report_admin.sh` — preflight/bootstrap/activate/rollback, all explicitly gated.
- `scripts/server_update_daily_report_runtime_env.sh` — safe metadata check,
  atomic interactive install and allowlisted recoverable gate transactions; no
  CLI secret arguments.
- `tests/test_report_contracts.py`.
- `tests/test_deepseek_client.py`.
- `tests/test_translation_pipeline.py`.
- `tests/test_prepared_report.py`.
- `tests/test_daily_report_delivery.py`.
- `tests/test_daily_report_launcher.py`.
- `tests/test_daily_report_release.py`.
- `tests/test_daily_report_ops.py`.
- `tests/test_daily_report_wrapper.py`.

Modify:

- `src/reddit_voc/daily_report.py` — add source-only selection, Provider-free Chinese-first renderer, deterministic excerpt and exact attachment rows while preserving legacy functions.
- `src/reddit_voc/dingtalk.py` — add canonical body bytes and exact-byte transport; preserve legacy API.
- `src/reddit_voc/cli.py` — add `prepare-daily-report` and `send-prepared-daily-report` with prepare-only lazy Provider import.
- `scripts/run_daily_report.sh` — new `prepare|send|smoke` dispatcher; no legacy double-build.
- `scripts/server_daily_report.sh` — fixed locked digest-pinned launcher; no Compose or sourced host env.
- `.env.example` — mark existing translation variables legacy/local and point to report-only example.
- `tests/test_daily_report.py` — Provider-free renderer and attachment contracts while retaining legacy regression tests.
- `tests/test_dingtalk_delivery.py` — frozen-byte transport contracts.
- `tests/test_webapp.py` — nested immutable URL and top-level compatibility symlink contracts.
- `README.md` and `.codex/context-pack.md` — final architecture, evidence boundary and operational pointers.

Do not modify:

- `src/reddit_voc/storage.py` or any schema/migration. The new prepared/delivery modules use their own narrow SQLite connections.
- `webapp/app.py`; its resolver already supports nested artifact paths.
- `webapp/docker-compose.yml`, `webapp/docker-compose.translation.yml` or `webapp/Dockerfile`.
- `scripts/server_daily_collect.sh`, `scripts/server_daily_cycle.sh`,
  `scripts/run_daily_collect.sh` or any backfill module/wrapper.
- `scripts/server_update_dingtalk_runtime_env.sh`.
- `scripts/deploy_webapp_tencent.sh`.

### Task 1: Freeze Runtime Contracts and Strict Schema Validation

**Files:**

- Create: `src/reddit_voc/report_contracts.py`
- Create: `config/translation_terms.json`
- Create: `config/prompts/deepseek-translation-v1.txt`
- Create: `config/prompts/deepseek-semantic-validator-v1.txt`
- Create: `config/schemas/daily-translation-manifest-v1.schema.json`
- Create: `config/schemas/daily-translation-attempt-v1.schema.json`
- Create: `config/schemas/daily-prepared-bundle-index-v1.schema.json`
- Test: `tests/test_report_contracts.py`

**Interface signatures (implemented by the steps below):**

```python
@dataclass(frozen=True)
class ReportSchemaAssets:
    manifest_schema: Mapping[str, object]
    attempt_schema: Mapping[str, object]
    bundle_index_schema: Mapping[str, object]
    sha256_by_name: Mapping[str, str]

Phase = Literal["translation", "semantic_validation"]

@dataclass(frozen=True)
class TokenUsage:
    prompt_tokens: int
    completion_tokens: int
    prompt_cache_hit_tokens: int
    prompt_cache_miss_tokens: int
    total_tokens: int

@dataclass(frozen=True)
class AttemptEvidence:
    sequence: int
    phase: Phase
    http_status: int | None
    outcome: str
    retryable: bool
    duration_ms: int
    response_id: str | None
    actual_model: str | None
    system_fingerprint: str | None
    finish_reason: str | None
    usage: TokenUsage | None

@dataclass(frozen=True)
class MonotonicDeadline:
    expires_at: float

class AttemptReservationSink(Protocol):
    def __call__(self, *, sequence: int, phase: Phase) -> None: ...

class AttemptBudget:
    def __init__(
        self,
        max_attempts: int = 100,
        *,
        reservation_sink: AttemptReservationSink | None = None,
    ) -> None: ...
    def reserve(self, phase: Phase) -> int: ...
    @property
    def used(self) -> int: ...

class JsonCompletion(Protocol):
    request_id: str
    model: str
    system_fingerprint: str | None
    finish_reason: str
    content: str
    usage: TokenUsage
    attempts: tuple[AttemptEvidence, ...]

class JsonCompletionClient(Protocol):
    def complete_json(
        self,
        *,
        phase: Phase,
        system_prompt: str,
        user_payload: Mapping[str, object],
        deadline: MonotonicDeadline,
        attempt_budget: AttemptBudget,
    ) -> JsonCompletion: ...

def canonical_json_bytes(value: object) -> bytes: ...
def sha256_hex(payload: bytes) -> str: ...
def read_regular_utf8(*, trusted_root: Path, path: Path) -> str: ...
def load_regular_json(*, trusted_root: Path, path: Path) -> object: ...
def validate_schema_instance(*, schema: Mapping[str, object], value: object) -> None: ...
def load_and_validate_schema(
    *, trusted_root: Path, schema_path: Path, value: object
) -> None: ...
def load_report_schema_assets(*, config_root: Path) -> ReportSchemaAssets: ...
```

- [ ] **Step 1: Write failing asset and schema tests**

Test exact canonical bytes, duplicate JSON keys, UTF-8 errors, symlinks, unknown schema versions, extra/missing fields, wrong scalar types, unsupported schema keywords and path traversal. Assert both prompts contain lowercase `json` and the approved output examples. Assert `translation_terms.json` has exactly:

```json
{
  "schema_version": "translation-terms-v1",
  "preserve_exact": [],
  "case_sensitive_terms": [],
  "case_insensitive_terms": [],
  "model_patterns": [],
  "unit_patterns": [],
  "allow_source_equal_patterns": [],
  "source_signal_rules": {
    "negation": [],
    "comparison": [],
    "sentiment": []
  }
}
```

Populate the arrays only from reviewed project brand/product/unit/signal rules; sort and deduplicate them. Tests must reject a regex that does not compile and any unknown root/nested key.

The three schema roots are exact:

- `daily-translation-manifest-v1` requires `schema_version`, `manifest_id`,
  `run_id`, provider/model/prompt/validator versions, both cache keys and output
  digests, both input fingerprints, `status=complete`, all Provider/reuse/
  phase-attempt booleans, request/retry/duration counts, `usage`, `responses`,
  `counts`, `items` and nullable `provider_authorization_id`.
- `usage` requires prompt, completion, cache-hit, cache-miss and total tokens.
  Each response requires phase, request ID, actual model, nullable system
  fingerprint, finish reason and usage. Each item requires stable/item/post/comment
  IDs, input SHA, `zh`, source signals, five semantic verdicts, error codes and
  status.
  Emit one ordered response record for every parsed Provider response carried
  by `AttemptEvidence`, including retryable/fail-fast HTTP-200 responses; phase
  and total usage are their exact sum, never final-response-only.
- `daily-translation-attempt-v1` requires `attempt_id`, `run_id`,
  `status=blocked`, stage/reason codes, Provider/phase-attempt booleans,
  request/retry/duration/usage/counts, sanitized responses and items containing
  only stable IDs/input hashes/status/error codes, plus nullable
  `provider_authorization_id`. It forbids source and translation text.
- `daily-prepared-bundle-index-v1` requires `schema_version`,
  `artifact_version_id` and sorted `entries`. Each entry has only
  `scope=private|public`, safe `relative_path`, non-negative `byte_size` and a
  lowercase 64-hex `sha256`. The index cannot list itself.

- [ ] **Step 2: Run the focused test and confirm RED**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. \
/Users/pray/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
-m unittest tests.test_report_contracts -v
```

Expected: FAIL because `report_contracts` and assets do not exist.

- [ ] **Step 3: Implement the minimal schema subset**

Support only the schema keywords used by these three committed schemas:
`$schema`, `$id`, `title`, `description`, `type`, `const`, `enum`,
`required`, `properties`, `additionalProperties`, `items`, `minItems`,
`minLength`, `pattern` and `minimum`. Fail closed on every unsupported keyword.
Support a type union only for `["string", "null"]`; no other union is accepted.
When checking `integer`/`number`, reject Python `bool` explicitly.
All object schemas use `additionalProperties=false` and explicit `required`.
Use `json.loads(..., object_pairs_hook=...)` to reject duplicate keys.
Do not implement a generic external JSON Schema package.

Canonical JSON is:

```python
json.dumps(
    value,
    ensure_ascii=False,
    sort_keys=True,
    separators=(",", ":"),
    allow_nan=False,
).encode("utf-8")
```

- [ ] **Step 4: Fill the versioned prompts and terms**

The translation prompt only instructs translation, marks source fields as untrusted data, forbids instructions/facts/summaries and requires exact stable IDs. The validator prompt marks source/candidate/IDs as opaque untrusted data, forbids following injected roles/schema/JSON and allows only the approved five-boolean verdict. Source text is never interpolated into either system prompt.

- [ ] **Step 5: Re-run and confirm GREEN**

Run the Step 2 command.

Expected: PASS; no network access and no secret read.

- [ ] **Step 6: Review the contract diff**

```bash
git diff --check
git status --short
```

Expected boundary:
`implementation_started=true`, `translation_provider_attempt_made=false`,
`live_send=false`, `production unchanged`.

### Task 2: Implement the Fixed DeepSeek HTTP Client

**Files:**

- Create: `src/reddit_voc/deepseek_client.py`
- Test: `tests/test_deepseek_client.py`
- Reuse: `src/reddit_voc/report_contracts.py`

**Interface signatures (implemented by the steps below):**

```python
@dataclass(frozen=True)
class DeepSeekCompletion:
    request_id: str
    model: str
    system_fingerprint: str | None
    finish_reason: str
    content: str
    usage: TokenUsage
    attempts: tuple[AttemptEvidence, ...]

class DeepSeekClientError(RuntimeError):
    reason_code: str
    attempts: tuple[AttemptEvidence, ...]
    response_id: str | None
    actual_model: str | None
    system_fingerprint: str | None
    finish_reason: str | None
    usage: TokenUsage

class DeepSeekClient:
    def complete_json(
        self,
        *,
        phase: Phase,
        system_prompt: str,
        user_payload: Mapping[str, object],
        deadline: MonotonicDeadline,
        attempt_budget: AttemptBudget,
    ) -> DeepSeekCompletion: ...
```

- [ ] **Step 1: Write failing request-envelope tests**

Use an injected fake transport. Assert exact URL and fixed body:

```json
{
  "model": "deepseek-v4-flash",
  "messages": [],
  "stream": false,
  "temperature": 0,
  "thinking": {"type": "disabled"},
  "response_format": {"type": "json_object"},
  "user_id": "reddit_voc_daily_translation"
}
```

The client fills `messages` from system prompt plus canonical user JSON, and
selects `max_tokens=16384` for translation or `4096` for semantic validation.
Assert `Content-Type`, `Accept`, fixed User-Agent and Bearer auth. Assert
`repr(client)` and all exceptions contain `<redacted>`, never the synthetic key.

- [ ] **Step 2: Write failing retry/deadline tests**

Cover:

- connection errors, timeout, 429, 500, 503, empty response and the exact
  parsed HTTP-200
  `choices[0].finish_reason="insufficient_system_resource"`: initial attempt
  plus at most two retries;
- 400, 401, 402, 422, all unlisted statuses, `length`, `content_filter`,
  `tool_calls`, every unknown finish reason, model drift, `stop` with null/empty
  content and
  malformed envelope: immediate block, except that content null/empty/partial
  is ignored for the retryable `insufficient_system_resource` case;
- shared thread-safe 100-attempt budget;
- reservation sink runs durably before transport open; sink failure means zero
  HTTP request and the sequence is not silently skipped;
- timeout `min(45, remaining)`;
- no reserve/open when deadline is exhausted;
- bounded incremental response bytes;
- whitespace keep-alive chunks do not refresh the deadline;
- in-flight response closes when the deadline expires.
- every fully parsed HTTP-200 envelope contributes its non-negative `usage`,
  response ID, actual model, system fingerprint and finish reason to that
  `AttemptEvidence` even when the result is retryable or fail-fast; completion
  and raised error expose aggregate usage across all such billed responses.
- every parsed usage object must satisfy
  `prompt_tokens == prompt_cache_hit_tokens + prompt_cache_miss_tokens` and
  `total_tokens == prompt_tokens + completion_tokens`; a negative, missing or
  inconsistent value is fail-closed before it enters evidence.

Pin `max_response_bytes=4 * 1024 * 1024`, User-Agent
`Reddit-VOC-Daily-Report/1` and retry waits of
`2 ** retry_index + uniform(0, 0.25)` seconds for retry indexes 0 and 1.
Check remaining deadline before sleeping and again before reserving.
Use a no-redirect opener; every 3xx response blocks and cannot forward the
Authorization header. Recognize `insufficient_system_resource` only from the
exact parsed `choices[0].finish_reason` value documented by DeepSeek. Do not
infer it from arbitrary message/error text or undocumented `error.type`/
`error.code` values.

Pin response-classification order: first validate the envelope, exact model and
usage invariants; next classify `finish_reason`; only `finish_reason="stop"`
requires non-null, non-empty JSON content. Exact
`insufficient_system_resource` is recorded and retried regardless of null,
empty or partial `message.content`. Add all three content shapes plus invalid
single-response usage and multi-response aggregation fixtures.

- [ ] **Step 3: Run and confirm RED**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. \
/Users/pray/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
-m unittest tests.test_deepseek_client -v
```

Expected: FAIL importing `reddit_voc.deepseek_client`.

- [ ] **Step 4: Implement transport and sanitized failures**

Use `urllib.request.Request` and an injectable `HttpTransport` protocol. Reserve
an attempt immediately before `transport.open()`. The production constructor
accepts the key as a value already read by the prepare command; it never reads
env/key files. Retry sleep is exponential with injected jitter and is skipped
when it cannot fit inside the remaining monotonic deadline.
Every failure after an attempt raises `DeepSeekClientError` with sanitized
reason and all accumulated attempt/response metadata; it never discards retry
evidence or parsed usage. `DeepSeekCompletion.usage` is the aggregate over all
fully parsed HTTP-200 envelopes for that request, not only the final successful
one. Add fixtures for resource-exhausted-then-success and fail-fast
`length`/`content_filter`/model-drift responses, and assert phase/total manifest
usage equals the exact sum without double counting.

- [ ] **Step 5: Run and confirm GREEN**

Run Step 3. Expected: PASS with only fake transport calls.

- [ ] **Step 6: Static secret check**

```bash
rg -n "print\\(|logging\\.|Authorization|api_key" \
  src/reddit_voc/deepseek_client.py tests/test_deepseek_client.py
```

Review every match; only header construction and redaction-safe code may remain.

### Task 3: Build Stable Translation Bundles and Quality Gates

**Files:**

- Create: `src/reddit_voc/translation_pipeline.py`
- Test: `tests/test_translation_pipeline.py`
- Reuse: `src/reddit_voc/report_contracts.py`

**Interface signatures (implemented by the steps below):**

```python
@dataclass(frozen=True)
class SourceSignalRules:
    negation: tuple[str, ...]
    comparison: tuple[str, ...]
    sentiment: tuple[str, ...]

@dataclass(frozen=True)
class TranslationTerms:
    schema_version: str
    preserve_exact: tuple[str, ...]
    case_sensitive_terms: tuple[str, ...]
    case_insensitive_terms: tuple[str, ...]
    model_patterns: tuple[str, ...]
    unit_patterns: tuple[str, ...]
    allow_source_equal_patterns: tuple[str, ...]
    source_signal_rules: SourceSignalRules

@dataclass(frozen=True)
class TranslationRuntimeAssets:
    terms: TranslationTerms
    translation_prompt: str
    validator_prompt: str
    translation_prompt_bytes: bytes
    validator_prompt_bytes: bytes
    terms_sha256: str
    source_signal_rules_sha256: str
    prompt_version: str
    validator_prompt_version: str

@dataclass(frozen=True)
class TranslationItem:
    stable_id: str
    item_type: Literal["title", "body", "comment"]
    post_id: str
    comment_id: str | None
    source_text: str
    input_sha256: str

@dataclass(frozen=True)
class PostTranslationBundle:
    post_id: str
    items: tuple[TranslationItem, ...]

@dataclass(frozen=True)
class SourceSignals:
    negation: tuple[str, ...]
    comparison: tuple[str, ...]
    sentiment: tuple[str, ...]

@dataclass(frozen=True)
class SemanticVerdict:
    meaning_preserved: bool
    negation_preserved: bool
    comparison_preserved: bool
    sentiment_preserved: bool
    hallucination_free: bool
    critical_error_codes: tuple[str, ...]

@dataclass(frozen=True)
class ValidatedTranslationItem:
    stable_id: str
    item_type: Literal["title", "body", "comment"]
    post_id: str
    comment_id: str | None
    input_sha256: str
    zh: str
    source_signals: SourceSignals
    entity_status: str

def normalize_source_text(text: str) -> str: ...
def build_post_translation_bundle(
    post: Mapping[str, object],
    comments: Sequence[Mapping[str, object]],
) -> PostTranslationBundle: ...
def translation_input_fingerprint(
    bundles: Sequence[PostTranslationBundle],
) -> str: ...
def load_translation_runtime_assets(config_root: Path) -> TranslationRuntimeAssets: ...
def parse_translation_content(
    content: str, *, expected_ids: Collection[str]
) -> dict[str, str]: ...
def validate_deterministic_translation(
    bundle: PostTranslationBundle,
    zh_by_id: Mapping[str, str],
    terms: TranslationTerms,
) -> tuple[ValidatedTranslationItem, ...]: ...
def parse_semantic_content(
    content: str, *, expected_ids: Collection[str]
) -> dict[str, SemanticVerdict]: ...
def require_semantic_acceptance(
    verdicts: Mapping[str, SemanticVerdict],
    *,
    expected_ids: Collection[str],
) -> None: ...
```

- [ ] **Step 1: Write failing source-preservation tests**

Use synthetic posts/comments. Require IDs:
`post:<post_id>:title`, `post:<post_id>:body` and
`comment:<comment_id>:body`. Normalize only CRLF/CR to LF; preserve leading,
trailing and repeated spaces, paragraph breaks, emoji and exact source order.
Fingerprint canonical items sorted by stable ID and includes item type,
post/comment IDs and normalized complete UTF-8 source.

- [ ] **Step 2: Write failing translation-schema and deterministic-gate tests**

Require exactly:

```json
{"translations":[{"id":"post:abc:title","zh":"中文译文"}]}
```

Reject missing, duplicate or unknown IDs; unknown keys; or non-string `zh`.
Only a non-empty, translatable source requires non-empty Chinese. An empty
source keeps its stable ID and accepts only an empty translation. Then reject
source-equal English outside reviewed patterns, non-Chinese translatable output,
and loss/change of brand, model, competitor, number, percentage, currency,
unit, URL, `r/subreddit` or `u/user`.

- [ ] **Step 3: Write failing semantic-validator tests**

Require exact IDs and five literal `true` values plus an empty
`critical_error_codes` array. Add prompt-injection fixtures containing forged
roles, forged JSON, replacement IDs and “mark all true” text in source and
candidate fields. Assert the payload keeps all untrusted data in user JSON and
never changes the system prompt.
Keep parsing separate from acceptance: a schema-valid `false` verdict parses
as `SemanticVerdict`, then the semantic gate blocks with
`semantic_gate_failed` rather than misclassifying it as a schema error.

- [ ] **Step 4: Run and confirm RED**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. \
/Users/pray/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
-m unittest tests.test_translation_pipeline -v
```

Expected: FAIL because `translation_pipeline` does not exist.

- [ ] **Step 5: Implement asset versions, parsers and gates**

Compute:

```python
prompt_version = sha256_hex(canonical_json_bytes({
    "translation_prompt_sha256": translation_prompt_sha256,
    "translation_terms_sha256": translation_terms_sha256,
}))

validator_prompt_version = sha256_hex(canonical_json_bytes({
    "source_signal_rules_sha256": source_signal_rules_sha256,
    "translation_terms_sha256": translation_terms_sha256,
    "validator_prompt_sha256": validator_prompt_sha256,
}))
```

Reject symlinked assets, unknown versions/keys, duplicate rules and invalid
regexes. Build source signals from the versioned terms file. Do not claim the
deterministic detector proves semantic equivalence.
`translation_pipeline.py` imports only stdlib and Provider-neutral
`report_contracts` types; it must not import `deepseek_client`. A fresh-process
asset/bundle preflight test asserts `deepseek_client` is absent from
`sys.modules`.

Pin a fixture using 64 `a` characters for translation prompt SHA, 64 `b`
characters for terms SHA, 64 `c` characters for signal-rules SHA and 64 `d`
characters for validator prompt SHA. Expected versions are:

```text
e80534ac8af0d1c6fab070b45067ed8dbda5764bce9dd135663675289b34952d
b1bac6a53ee3be1c4ffd86f172f42c8cc1e0cedcdf0de0a8ddad5cd99df78b66
```

- [ ] **Step 6: Run and confirm GREEN**

Run Step 4. Expected: PASS, with no Provider client constructed.

### Task 4: Add Two-Phase Generation, Validation and Cache Digests

**Files:**

- Modify: `src/reddit_voc/translation_pipeline.py`
- Modify test: `tests/test_translation_pipeline.py`
- Reuse: `src/reddit_voc/deepseek_client.py`

**Interface signatures (implemented by the steps below):**

```python
@dataclass(frozen=True)
class CompletionEvidence:
    phase: Phase
    response_id: str
    actual_model: str
    system_fingerprint: str | None
    finish_reason: str
    usage: TokenUsage
    attempts: tuple[AttemptEvidence, ...]

@dataclass(frozen=True)
class PhaseEvidence:
    phase: Phase
    request_count: int
    retry_count: int
    attempt_made: bool
    duration_ms: int
    usage: TokenUsage
    completions: tuple[CompletionEvidence, ...]

@dataclass(frozen=True)
class ValidatedItemEvidence:
    stable_id: str
    item_type: str
    post_id: str
    comment_id: str | None
    input_sha256: str
    zh: str | None
    source_signals: SourceSignals
    semantic_verdict: SemanticVerdict | None
    entity_status: str
    status: str
    error_type: str | None

@dataclass(frozen=True)
class VerifiedCacheManifest:
    run_id: str
    artifact_version_id: str
    bundle_sha256: str
    is_current: bool
    manifest: Mapping[str, object]

@dataclass(frozen=True)
class TranslationPipelineResult:
    translations: Mapping[str, str]
    verdicts: Mapping[str, SemanticVerdict]
    items: tuple[ValidatedItemEvidence, ...]
    translation_input_fingerprint: str
    translation_cache_key: str
    translation_output_sha256: str
    validator_cache_key: str
    validator_output_sha256: str
    translation_reused: bool
    semantic_validation_reused: bool
    attempts: tuple[AttemptEvidence, ...]
    translation_phase: PhaseEvidence
    semantic_validation_phase: PhaseEvidence
    total_usage: TokenUsage
    duration_ms: int

class TranslationPipelineBlocked(RuntimeError):
    reason_codes: tuple[str, ...]
    attempts: tuple[AttemptEvidence, ...]
    translation_phase: PhaseEvidence
    semantic_validation_phase: PhaseEvidence
    item_evidence: tuple[ValidatedItemEvidence, ...]

def translation_cache_key(
    *, translation_input_fingerprint: str, model: str, prompt_version: str
) -> str: ...
def translation_output_sha256(translations: Mapping[str, str]) -> str: ...
def validator_cache_key(
    *,
    translation_input_fingerprint: str,
    translation_output_sha256: str,
    model: str,
    validator_prompt_version: str,
) -> str: ...
def validator_output_sha256(
    *,
    bundles: Sequence[PostTranslationBundle],
    translations: Mapping[str, str],
    source_signals: Mapping[str, SourceSignals],
    verdicts: Mapping[str, SemanticVerdict],
) -> str: ...

class TranslationService:
    def __init__(
        self,
        *,
        client: JsonCompletionClient | None,
        assets: TranslationRuntimeAssets,
        attempt_reservation_sink: AttemptReservationSink | None = None,
    ) -> None: ...

    def run(
        self,
        bundles: Sequence[PostTranslationBundle],
        *,
        cached_manifests: Sequence[VerifiedCacheManifest],
        deadline_seconds: float = 300.0,
        max_attempts: int = 100,
    ) -> TranslationPipelineResult: ...
```

- [ ] **Step 1: Write failing digest/cache tests**

Pin these exact canonical JSON preimages:

```python
{
    "translation_input_fingerprint": translation_input_fingerprint,
    "model": model,
    "prompt_version": prompt_version,
}

[{"id": stable_id, "zh": translations[stable_id]} for stable_id in sorted_ids]

{
    "translation_input_fingerprint": translation_input_fingerprint,
    "translation_output_sha256": translation_output_sha256,
    "model": model,
    "validator_prompt_version": validator_prompt_version,
}

[
    {
        "id": stable_id,
        "input_sha256": input_sha256_by_id[stable_id],
        "zh_sha256": zh_sha256_by_id[stable_id],
        "source_signals": source_signals_by_id[stable_id],
        "semantic_verdict": semantic_verdict_by_id[stable_id],
        "critical_error_codes": error_codes_by_id[stable_id],
    }
    for stable_id in sorted_ids
]
```

Verify that a translation-prompt change invalidates both stages; a
validator-prompt/signal-rule change reuses translation but reruns validation;
unchanged keys/digests reuse both; and mismatched verdict/translation digests
are never combined.
Only accept typed `VerifiedCacheManifest` values created after same-run,
schema/index/current proof. Re-run exact-ID, deterministic entity and all-true
semantic gates on every reused item.

- [ ] **Step 2: Write failing two-phase orchestration tests**

Prove:

- all translation generation completes before semantic validation starts;
- at most two requests are in flight;
- both phases share one `MonotonicDeadline` and `AttemptBudget(100)`;
- one fatal result stops new submissions and cancels work that has not started;
- already-started attempts remain in evidence;
- any missing/non-true validator verdict blocks the whole result;
- retry/usage/attempt counts remain separate by phase.
- client exceptions retain all attempts/completion metadata in
  `TranslationPipelineBlocked`;
- complete and blocked results contain enough per-phase/per-item evidence to
  populate Task 1 schemas without re-reading Provider responses.
- `deadline_seconds <= 0` or `deadline_seconds > 300` is rejected before client
  construction, and `max_attempts <= 0` or `max_attempts > 100` is rejected at
  the same boundary; neither cap is raiseable through arguments or env;
- an empty bundle sequence is a successful no-VOC result: canonical `[]`
  supplies deterministic input/output/validator digests, both phases have zero
  requests/retries/usage/duration and `attempt_made=false`, both reuse flags are
  false, and no client or reservation sink is touched.

- [ ] **Step 3: Run and confirm RED**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. \
/Users/pray/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
-m unittest tests.test_translation_pipeline -v
```

Expected: new cache/orchestration tests FAIL.

- [ ] **Step 4: Implement with injected client**

`TranslationService` receives a `JsonCompletionClient`; it does not read keys,
env, paths or prepared state. Use `ThreadPoolExecutor(max_workers=2)`. Keep each
post as one translation request and one semantic request. Never truncate a
bundle to fit caps; return a typed blocked reason before any client call. Clamp
production callers to exactly `deadline_seconds=300` and `max_attempts=100`,
and fail rather than silently coercing values outside those hard bounds.

- [ ] **Step 5: Run focused client/pipeline regression**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. \
/Users/pray/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
-m unittest tests.test_deepseek_client tests.test_translation_pipeline -v
```

Expected: PASS; `translation_provider_attempt_made=false` because transport is
synthetic.

### Task 5: Extract Source-Only Selection and Chinese-First Rendering

**Files:**

- Modify: `src/reddit_voc/daily_report.py`
- Modify test: `tests/test_daily_report.py`

**Interface signatures (implemented by the steps below):**

```python
@dataclass(frozen=True)
class DailyReportSource:
    run: Mapping[str, object]
    posts: tuple[Mapping[str, object], ...]
    comments_by_post: Mapping[str, tuple[Mapping[str, object], ...]]
    analysis_by_post: Mapping[str, Mapping[str, object]]
    recent_threads: tuple[Mapping[str, object], ...]

@dataclass(frozen=True)
class ReportContentField:
    run_id: str
    post_id: str
    comment_id: str | None
    field: str
    language: str
    text: str

class DailyReportBlocked(RuntimeError):
    reason_code: str

@dataclass(frozen=True)
class PreparedRenderResult:
    report: DailyReportResult
    dingtalk_bodies: tuple[Mapping[str, object], ...]
    content_fields: tuple[ReportContentField, ...]

def select_visible_daily_report_source(
    source: DailyReportSource,
    *,
    visibility_keyword: str = "Momcozy",
    visibility_rule_version: str = "daily-visible-v1",
) -> DailyReportSource: ...
def source_excerpt_v1(
    *, title: str, body: str, comments: Sequence[str], max_bytes: int
) -> str: ...
def render_prevalidated_daily_report(
    source: DailyReportSource,
    *,
    translations: Mapping[str, str],
    output_dir: Path,
    artifact_version_url: str,
    dingtalk_max_bytes: int,
    dingtalk_required_keyword: str,
    dingtalk_max_parts: int = 2,
) -> PreparedRenderResult: ...
```

- [ ] **Step 1: Write failing visibility-order tests**

Create a visible post and a category-only hidden post. Selection must depend
only on a case-insensitive explicit `visibility_keyword` match in original
body/comments, never on title, translated fields, category, relevance or
analysis. Analysis may enrich an already visible row but cannot expand the
Provider input set. Assert downstream translation bundles contain no hidden
stable ID. Freeze `daily-visible-v1` and visibility keyword into the report
fingerprint.
Here `visibility_keyword` is fixed/versioned as `Momcozy`. It is not the
DingTalk security keyword. Add a non-interference test proving changes to
`dingtalk_required_keyword` never change visible post IDs or Provider input.

- [ ] **Step 2: Write failing Chinese-first DingTalk tests**

For every visible block assert exact order:

1. translated title;
2. translated body/user voice;
3. translated comments;
4. existing Chinese business judgment;
5. label `英文原文节选` and deterministic source excerpt;
6. exact canonical Reddit URL.

Test UTF-8 boundaries, emoji, blank fields and two-part limits. Reserve a
non-empty English title excerpt first, then body/comments. If complete Chinese
content, minimum excerpt, attachment hint and URL cannot fit in two messages,
raise `DailyReportBlocked`. Never silently omit a Chinese block or URL.
Assert `PreparedRenderResult.dingtalk_bodies` preserves part order and contains
the exact title/markdown payload objects to be frozen by Task 6; it contains no
webhook, signature, secret or bundle SHA.

Call the existing `dingtalk.with_required_keyword` while constructing each
candidate body, before final UTF-8 byte accounting and part acceptance. Budget
the complete canonical JSON body bytes, including msgtype/title/markdown JSON
escaping and keyword injection, not only visible text bytes. Reserve the
keyword's actual encoded bytes during packing. Add a boundary fixture whose
arbitrary required keyword (for example `LL`) is absent from all source and
translated text: every accepted part must contain it and remain within the byte
limit. Changing only `dingtalk_required_keyword` changes rendered body bytes and
the report fingerprint, but never visible post IDs, translation bundles or the
Provider input fingerprint.

- [ ] **Step 3: Write failing attachment round-trip tests**

HTML and CSV must recover exact original and translated title/body/combined
comments. XLSX gets normalized `content` and `comments` sheets with columns:

```text
run_id, post_id, comment_id, field, language,
part_index, part_count, text_chunk
```

Split at 30,000 Unicode code points, not bytes or UTF-16 units. Test 29,999,
30,000 and 30,001 boundaries, emoji, empty values, multiple comments and exact
ordered reconstruction. Main detail rows may contain previews only if they
reference normalized rows. HTML, CSV and XLSX must also retain the exact
canonical Reddit URL read from the source row.

- [ ] **Step 4: Run and confirm RED**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. \
/Users/pray/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
-m unittest tests.test_daily_report -v
```

Expected: new tests FAIL while the existing 10 legacy tests remain unchanged.

- [ ] **Step 5: Implement Provider-free rendering**

Do not call `translate_to_chinese` or any HTTP helper from the new renderer.
Preserve legacy `build_daily_report()` and legacy renderer behavior behind old
commands. Normalize CRLF/CR only for excerpt/display operations; attachment
source fields retain exact database strings. Required-keyword injection is
complete before this function returns; Task 6 only validates and freezes these
already budgeted bodies and must not inject or split content again.

- [ ] **Step 6: Run and confirm GREEN**

Run Step 4. Expected: all legacy and new report tests PASS.

### Task 6: Build Immutable Prepared Bundles and Atomic Projection

**Files:**

- Create: `src/reddit_voc/prepared_bundle.py`
- Create: `src/reddit_voc/prepared_report.py`
- Test: `tests/test_prepared_report.py`
- Reuse: `src/reddit_voc/report_contracts.py`
- Reuse: `src/reddit_voc/daily_report.py`
- Reuse: `src/reddit_voc/translation_pipeline.py`

**Interface signatures (implemented by the steps below):**

```python
@dataclass(frozen=True)
class PreparedReportRoots:
    public_root: Path
    private_root: Path
    public_staging_root: Path
    private_staging_root: Path
    state_root: Path
    blocked_root: Path
    handoff_root: Path

@dataclass(frozen=True)
class PreparedAttemptContext:
    attempt_id: str
    artifact_version_id: str

@dataclass(frozen=True)
class PreparedPreflight:
    run_id: str
    source: DailyReportSource
    visible_post_ids: tuple[str, ...]
    bundles: tuple[PostTranslationBundle, ...]
    cached_manifests: tuple[VerifiedCacheManifest, ...]
    translation_assets: TranslationRuntimeAssets
    schema_assets: ReportSchemaAssets
    provider_phases_required: tuple[Phase, ...]
    provider_authorization_id: str | None
    report_static_inputs: Mapping[str, object]

@dataclass(frozen=True)
class PreparedReportResult:
    run_id: str
    attempt_id: str
    artifact_version_id: str
    bundle_sha256: str
    report_input_fingerprint: str
    outbox_sha256: str
    provider_authorization_id: str | None
    prepare_action_authorization_id: str
    public_dir: Path
    private_dir: Path

@dataclass(frozen=True)
class StagedPreparedReport:
    run_id: str
    attempt_id: str
    artifact_version_id: str
    bundle_sha256: str
    report_input_fingerprint: str
    outbox_sha256: str
    provider_authorization_id: str | None
    prepare_action_authorization_id: str
    staged_public_dir: Path
    staged_private_dir: Path
    final_public_dir: Path
    final_private_dir: Path
    commit_request_path: Path
    commit_request_sha256: str

@dataclass(frozen=True)
class PreparedOutboxPart:
    index: int
    total: int
    path: Path
    body_bytes: bytes
    sha256: str
    byte_count: int

@dataclass(frozen=True)
class VerifiedPreparedReport:
    run_id: str
    artifact_version_id: str
    bundle_sha256: str
    report_input_fingerprint: str
    translation_input_fingerprint: str
    translation_output_sha256: str
    validator_output_sha256: str
    translation_status: str
    outbox_sha256: str
    parts: tuple[PreparedOutboxPart, ...]
    public_artifact_urls: tuple[str, ...]

def preflight_daily_report(
    *,
    database: Path,
    run_id: str,
    roots: PreparedReportRoots,
    config_root: Path,
    artifact_base_url: str,
    dingtalk_required_keyword: str,
    dingtalk_max_bytes: int,
    dingtalk_max_parts: int = 2,
) -> PreparedPreflight: ...
def prepare_daily_report(
    preflight: PreparedPreflight,
    *,
    attempt: PreparedAttemptContext,
    translator: TranslationService,
    roots: PreparedReportRoots,
    provider_authorization_id: str | None,
    prepare_action_authorization_id: str,
) -> PreparedReportResult: ...
def stage_daily_report(
    preflight: PreparedPreflight,
    *,
    attempt: PreparedAttemptContext,
    translator: TranslationService,
    roots: PreparedReportRoots,
    provider_authorization_id: str | None,
    prepare_action_authorization_id: str,
) -> StagedPreparedReport: ...
def commit_staged_prepared_report(
    *,
    roots: PreparedReportRoots,
    expected_run_id: str,
    expected_artifact_version_id: str,
    expected_bundle_sha256: str,
    expected_outbox_sha256: str,
    expected_commit_request_sha256: str,
    expected_provider_authorization_id: str | None,
    expected_prepare_action_authorization_id: str,
    expected_attempt_id: str,
    schema_assets: ReportSchemaAssets,
) -> PreparedReportResult: ...
def build_complete_translation_manifest(
    *,
    preflight: PreparedPreflight,
    pipeline_result: TranslationPipelineResult,
    report_input_fingerprint: str,
    provider_authorization_id: str | None,
) -> Mapping[str, object]: ...
def build_blocked_translation_attempt(
    *,
    run_id: str,
    attempt_id: str,
    preflight: PreparedPreflight | None,
    pipeline_evidence: TranslationPipelineResult | TranslationPipelineBlocked | None,
    stage: str,
    reason_codes: Sequence[str],
    provider_authorization_id: str | None,
) -> Mapping[str, object]: ...
def build_commit_blocked_attempt_from_complete_manifest(
    *,
    verified_complete_manifest: Mapping[str, object],
    attempt_id: str,
    stage: str,
    reason_codes: Sequence[str],
) -> Mapping[str, object]: ...
def load_verified_cache_manifests(
    *,
    roots: PreparedReportRoots,
    run_id: str,
    schema_assets: ReportSchemaAssets,
) -> tuple[VerifiedCacheManifest, ...]: ...
def load_verified_prepared_report(
    *,
    roots: PreparedReportRoots,
    expected_run_id: str,
    expected_artifact_version_id: str,
    expected_bundle_sha256: str,
    expected_outbox_sha256: str,
    schema_assets: ReportSchemaAssets,
) -> VerifiedPreparedReport: ...
def freeze_dingtalk_outbox(
    *,
    rendered: PreparedRenderResult,
    private_staging_dir: Path,
    dingtalk_required_keyword: str,
) -> tuple[PreparedOutboxPart, ...]: ...
def generate_artifact_version_id(
    *,
    now_utc: datetime,
    random_hex: Callable[[int], str] = secrets.token_hex,
) -> str: ...
def write_blocked_attempt(
    *,
    roots: PreparedReportRoots,
    run_id: str,
    attempt_id: str,
    manifest: Mapping[str, object],
) -> Path: ...
def recover_projection_journal(*, roots: PreparedReportRoots) -> None: ...
```

- [ ] **Step 1: Write failing read-only snapshot tests**

Reuse the exact `mode=ro`, `uri=True`, `PRAGMA query_only=ON` and single
transaction pattern already present in `backfill_merge.py`. Assert:

- missing DB/table/required column blocks before key/client construction;
- one connection reads run/posts/comments/analysis/recent context;
- no parent directory is created;
- DB bytes, inode, mtime and `delivery_previews` rows do not change;
- `migrate()` is never imported/called;
- visibility selection, stable bundle construction, schema/prompt/terms loading,
  verified cache discovery and all hard caps complete before the Provider gate;
- `PreparedPreflight` owns the validated asset bytes/objects/digests used by
  prepare; changing a config file after preflight cannot change this run;
- `provider_phases_required` is empty when both verified cache levels hit or
  when the visible bundle sequence is empty, and equals only
  `semantic_validation` on validator-only invalidation;
- the empty-visible-set path never constructs a key/client, uses canonical
  `[]` for deterministic input/output/validator digests, requires no Provider
  phases, records zero counts/usage/attempts with both reuse flags false, and
  can still commit a complete no-VOC report;
- preflight initializes `provider_authorization_id=None`; only the gated CLI may
  pass a non-null, path-safe ID into `prepare_daily_report`. Cache-only and
  empty-visible-set results retain null.
- the host/CLI creates one path-safe `PreparedAttemptContext` before staging;
  `prepare_daily_report`, `stage_daily_report`, the staged result, commit
  request and neutral commit must use exactly those same two IDs. Neither
  prepare nor stage may regenerate or substitute either ID.

- [ ] **Step 2: Write failing version/index/tamper tests**

`artifact_version_id` is exactly:

```text
<YYYYMMDDTHHMMSSffffffZ>-<32 lowercase CSPRNG hex>
```

Reject reuse or any pre-existing final target. Production accepts only the
host-precreated exact empty staging leaves described below. Build private:

```text
translation-manifest.json
validation-report.json
outbox/part-0001.json
outbox/part-0002.json  (only when needed)
bundle-index.json
```

and public HTML/XLSX/CSV/PNG/media whose logical final targets are:

```text
<public_root>/prepared/<run_id>/<artifact_version_id>/
<private_root>/prepared/<run_id>/<artifact_version_id>/
```

The production worker may not write those served/final targets. It builds the
two complete trees under separate mode-700, website-invisible
`public_staging_root` and `private_staging_root` attempt directories, each on
the same filesystem as its corresponding final parent. The host commit helper
re-verifies device/path constraints and
atomically renames each previously non-existent candidate into the logical final
target before current/projection/registry mutation. Invalid/blocked candidates
never move into the served root. A crash after a verified public rename but
before current commit may leave only an unlinked CSPRNG-version orphan: no URL
is printed/sent/projected, and held-lock recovery must either finish the exact
verified journaled commit or retain/remove it as an auditable orphan; it is
never auto-selected as current/cache authority.

The worker then writes a canonical, mode-600, non-secret commit
request outside the bundle at
`<handoff_root>/<run_id>/<attempt_id>/commit-request.json`. It contains only
schema version, exact run/attempt/version/bundle/outbox/report/manifest hashes,
nullable Provider authorization ID, prepare-action authorization ID, immutable
public/private paths and the allowlisted projection mapping; it contains no
source, translation, webhook or key. Its SHA
is returned separately and is never part of the bundle SHA. The handoff
directory is mode 700, single-writer and immutable after rename.

The index sorts by `scope + relative_path`, hashes every immutable payload,
excludes itself, rejects symlinks/extra/missing files and prevents any payload
from embedding `bundle_sha256`. Its canonical bytes SHA is the bundle SHA.
The aggregate `outbox_sha256` is SHA-256 of canonical ordered records containing
only part index, part SHA-256 and byte count.

Add an explicit outbox-chain test:

1. `render_prevalidated_daily_report` returns ordered title/markdown bodies;
2. verify every body has the DingTalk required keyword and approved
   msgtype/title fields;
3. serialize each body once with `canonical_json_bytes`;
4. enforce per-part UTF-8 byte limits and maximum two parts;
5. write `outbox/part-0001.json`, then `part-0002.json` when present;
6. store exact bytes/path/index/total/hash/byte-count in `PreparedOutboxPart`;
7. compute aggregate outbox SHA from ordered part metadata.

No later task may regenerate or reserialize these bodies.
`freeze_dingtalk_outbox` only validates that each already-rendered body contains
the exact required keyword and approved fields, serializes it once and writes
it. It never calls `with_required_keyword`, injects text, repartitions content
or accepts an over-budget post-injection body.

- [ ] **Step 3: Write failing cache and blocked-attempt tests**

Cache discovery accepts only the same run's schema-valid, index-verified,
immutable `status=complete` manifests. Prefer current. If one translation cache
key maps to multiple output digests and current does not choose one, block with
`cache_ambiguous`. Never reuse blocked, orphan or staging files.

Former-current cache entries are trusted only through the append-only commit
registry at:

```text
<state_root>/prepared-commits/<run_id>/registry.jsonl
```

Require mode-700 directories and a mode-600 regular, non-symlink registry.
Each canonical line contains strict sequence/hash-chain fields plus run ID,
artifact version, bundle SHA, manifest ID, both cache keys and both output
digests. Append and fsync a registry entry only after `prepared-current.json`
is durably committed; crash recovery may idempotently register the exact
verified current candidate. Prefer current, then accept a former-current only
when its registry chain, bundle index and manifest all agree. Reject a valid-
looking orphan/staging candidate without a registry entry, tampered/truncated
registry chains, duplicate sequence/version entries and ambiguous outputs. The
registry lives outside the immutable bundle and is never part of bundle SHA.

Blocked attempts go to:

```text
<blocked_root>/<run_id>/<attempt_id>/blocked-manifest.json
```

with mode 700 directory/mode 600 regular file. Assert it contains only stable
IDs, input hashes, sanitized Provider evidence, usage/counts and reason codes;
it contains neither source text, translation text, API key nor webhook.
Complete manifest ID is exactly
`<run_id>.<translation_input_fingerprint>.<translation_output_sha256>.<validator_output_sha256>`.
Write blocked evidence into a same-filesystem mode-700 temporary directory,
fsync the mode-600 file and directory, then atomically rename to a previously
non-existent attempt directory and fsync its parent. Existing targets block;
committed attempts are immutable.

Test `build_complete_translation_manifest`,
`build_blocked_translation_attempt` and the neutral
`build_commit_blocked_attempt_from_complete_manifest` as the only schema-object
constructors.
The complete builder losslessly joins pipeline evidence to bundles by exact
stable ID and includes item type/post/comment IDs, all booleans/counts/usage,
per-phase and total duration, response IDs, actual model, fingerprint, finish
reason, cache keys/output digests, reuse fields, source-run collection Provider
evidence, report fingerprint and nullable Provider authorization ID. The
blocked builder includes the same sanitized completion/accounting evidence and
nullable authorization ID but omits all source and Chinese text. Validate the
complete or blocked schema before any write and canonicalize exactly once. A
schema/join mismatch is blocked and cannot advance current.

The blocked builder also covers failures before `PreparedPreflight` or before
pipeline evidence exists: accept explicit path-safe run/attempt IDs with both
optional objects null, emit empty items/responses and zero attempt/count/usage/
duration fields, and retain the exact sanitized stage/reason codes. When a
`TranslationPipelineResult` already exists and render/outbox/staging fails,
carry its real attempts/responses/usage/items into sanitized blocked evidence;
when a `TranslationPipelineBlocked` exists, carry its partial evidence. The
neutral host commit-failure builder accepts only a schema/index-verified
complete manifest, strips all `zh`/source fields and copies its exact sanitized
Provider evidence plus commit failure codes. It records the Provider
authorization ID only if that gate had already passed. Tests cover preflight,
gate, key-metadata, pipeline, pipeline-success-then-render failure and
pipeline-success-then-host-commit failure without dropping or inventing
Provider evidence.

- [ ] **Step 4: Write failing crash/projection tests**

Inject a failure after every staging/fsync/rename/pointer/projection step.
`prepared-current.json` changes only after both version directories and index
are durable. The external pointer includes `run_id`, `artifact_version_id`,
`bundle_sha256`, `report_input_fingerprint` and `outbox_sha256`, with
`schema_version=prepared-current-v1` and no extra fields. A projection journal atomically
updates top-level compatibility symlinks only after current commit and restores
the last approved pointer/links after interruption. Orphan candidates remain
auditable and are never auto-promoted.

Inject failures around current-pointer and commit-registry operations. A
candidate that never became current remains unregistered and unusable as
cache. A crash after current commit but before registry append is recoverable
only by re-verifying that exact current tuple and appending one idempotent
registry entry; conflicting recovery data blocks. A registry entry must never
precede current commit.

Test the runtime split explicitly: `stage_daily_report` may read `state_root`
but writes only immutable public/private candidates and a blocked/complete
commit candidate inside its exact staging/handoff mounts; it cannot write final
public/private/blocked paths or advance current/projections/registry.
`commit_staged_prepared_report` is Provider-neutral, opens no DB/key/network,
requires the owner-passed commit-request SHA, attempt ID, Provider authorization
ID, prepare-action authorization ID and full candidate tuple. Production host
admission verifies the action ID/attempt belongs to the still-reserved exact
prepare or schedule permit and independently checks whether nullable Provider
authorization matches actual attempt evidence before commit. A post-run request
cannot create authority. The neutral commit first atomically publishes the two
verified staged public/private trees to their exact immutable final paths, then
performs only pointer/projection/registry writes. The local convenience
`prepare_daily_report` calls stage then commit sequentially for L1 fixtures.

For production defer mode, the host generates path-safe attempt/artifact IDs
and creates previously non-existent, empty mode-700 public/private staging and
handoff attempt directories before container launch. The worker receives those
exact directories as individual bind mounts, verifies empty/owner/mode/device,
and cannot open their parents. It writes a failure as
`handoff/blocked-candidate.json`; it never mounts or writes the immutable
`blocked_root`. After gates are off, the neutral admin helper either publishes
that schema-valid blocked candidate atomically to the exact new blocked attempt
path or commits the complete staged trees—never both. Existing/non-empty paths,
unexpected files or ID/path mismatch block before key/client construction.

The projection set is derived from the committed `DailyReportResult` public
artifact basenames. Write old/new targets before replacement, update every
temporary symlink with `os.replace`, switch `daily-detail.csv` last, then write
the commit marker last. Every target must remain inside the public outputs root.
Recovery of an incomplete projection journal is mandatory before preflight,
prepare or send may read/advance `prepared-current.json`.

- [ ] **Step 5: Run and confirm RED**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. \
/Users/pray/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
-m unittest tests.test_prepared_report -v
```

Expected: FAIL importing `prepared_report`.

- [ ] **Step 6: Implement staged fsync/rename transactions**

Use same-filesystem staging directories, regular-file/no-follow checks, mode
700 state/private roots and mode 600 state files. Compute
`report_input_fingerprint` from actual translation/validator output digests and
every approved display input/version/budget/base URL. Do not include mutable
pointer or ledger data.

Keep `prepared_bundle.py` Provider-neutral: it owns roots/outbox/verified models,
strict schema/index/current verification, `commit_staged_prepared_report` and
`load_verified_prepared_report`, and imports only stdlib plus
`report_contracts`. `prepared_report.py` owns staging and may import daily
rendering and translation modules, but send never imports it.

`prepared_report.py` is the sole owner of complete/blocked manifest
construction; Provider-neutral `prepared_bundle.py` is the sole owner of
commit-registry mutation and commit-failure blocked-manifest derivation from an
already verified complete manifest. `prepare_daily_report` records the
explicit `provider_authorization_id` it receives in both returned evidence and
the selected schema object; it never infers the ID from env or state paths.

Add a report-fingerprint mutation matrix covering every approved input:
translation/validator output digests, run window/status, subreddit, source URL,
created time, score, media, comment metadata, keyword/relevance/analysis,
visibility/renderer/excerpt versions, DingTalk budgets, DingTalk required
keyword and
artifact base URL. Changing any one changes the report fingerprint; changing
only mutable pointer/ledger data does not.

- [ ] **Step 7: Run and confirm GREEN**

Run Step 5. Expected: PASS, all Provider behavior supplied by a fake translator.

### Task 7: Add the Gated Prepare CLI

**Files:**

- Modify: `src/reddit_voc/cli.py`
- Modify test: `tests/test_prepared_report.py`
- Modify test: `tests/test_daily_report.py`

**Command:**

```text
reddit-voc prepare-daily-report
  --database PATH
  --run-id RUN_ID
  --attempt-id ATTEMPT_ID
  --artifact-version-id VERSION_ID
  --public-root PATH
  --private-root PATH
  --public-staging-root PATH
  --private-staging-root PATH
  --state-root PATH
  --blocked-root PATH
  --handoff-root PATH
  --provider-attempt-root PATH
  --config-root PATH
  --artifact-base-url HTTPS_URL
  --dingtalk-required-keyword TEXT
  --dingtalk-max-bytes N
  --dingtalk-max-parts 2
  [--authorize-provider-call]
  [--provider-authorization-id ID]
  [--prepare-action-authorization-id ID]
  [--defer-host-commit]
```

- [ ] **Step 1: Write failing four-gate and import-isolation tests**

Real translation requires all of:

```text
REDDIT_VOC_TRANSLATION_MODE=deepseek
REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION=1
regular mode-600 /run/secrets/deepseek_api_key
--authorize-provider-call
```

When the Provider flag is present, require a path-safe non-empty
`--provider-authorization-id` and record it in sanitized complete/blocked
evidence. Before the first possible HTTP request, durably reserve that
authorization under
`<provider_attempt_root>/<id>/provider-attempts.jsonl`; each retry appends
and fsyncs its phase/sequence reservation through `AttemptReservationSink`.
The path is mode 700/600, owner-checked and contains no source/secret. In
production it is the exact authorization-specific child of host-only
`/home/ubuntu/.reddit-voc/report-control/provider-attempts/`, mounted alone;
the parent control root, permits, gate journals and audit are never mounted.

The local convenience path calls `recover_projection_journal` first. The
production `--defer-host-commit` path has read-only state and instead requires
the host neutral admin helper to finish recovery under the lock before launch;
it verifies a clean journal/current snapshot and blocks rather than writing
recovery state. Then run source/asset/schema/cache/cap preflight. When
`provider_phases_required` is non-empty, run fresh-process tests
for every missing combination. Assert no key read, `deepseek_client` absent
from `sys.modules`, no HTTP attempt, no DB write and no current-pointer change.
Preflight must finish before reading the key or lazy-importing/constructing
`DeepSeekClient`.

When both verified cache levels hit or the visible bundle set is empty, require
no key file, Provider flag or DeepSeek client import; instantiate
`TranslationService(client=None, ...)` and re-run all cached gates when present.
The empty path commits a complete no-VOC report with null Provider authorization
ID and deterministic empty digests. When only semantic validation is missing,
all four Provider gates are required and only the semantic phase may call the
client.

Production `--defer-host-commit` always requires a separate path-safe
`--prepare-action-authorization-id` bound to the host prepare/schedule permit.
It authorizes only staging/commit admission, not key read or Provider calls.
`provider_authorization_id` remains null on cache-only/zero-visible paths even
though the action authorization is present; when a Provider call is permitted,
the owner may issue the same literal ID for both roles but the evidence fields
and checks remain distinct.

- [ ] **Step 2: Write failing prepare-success integration test**

With a synthetic key file and fake client, assert exactly one source snapshot,
one translation+validation pipeline, one immutable bundle and one current
advance. No `delivery_previews` row is written. Output summary distinguishes:
`translation_provider_call`, generation/validator attempt flags, reuse flags,
overall `provider_attempt_made` and `report_live_send=false`.

With `--defer-host-commit`, success returns the exact run/version/bundle/outbox/
commit-request hashes and `current_advanced=false`; it never writes mutable
state/projections. Without the flag, the L1/local convenience path invokes the
neutral commit helper and returns `current_advanced=true`. Production launcher
tests require the defer flag and reject a networked prepare container that has
write access to `state_root`.

After the four Provider gates pass, pass the exact CLI authorization ID into
`prepare_daily_report` and both complete/blocked manifest builders, and require
`PreparedReportResult.provider_authorization_id` to match. A failure before
authorization records null; a failure after authorization records the exact
sanitized ID. Invoke the pipeline with exactly `deadline_seconds=300` and
`max_attempts=100`; no CLI/env option may raise either hard cap.
Also require the exact prepare-action ID in staged result/commit request/host
commit result; a missing or mismatched action ID blocks regardless of Provider
cache state.

Task 7 writes blocked evidence only. It does not send failure alerts because
the exact-byte transport and ledger are implemented in Task 8; Task 9 adds the
separately gated alert integration.

- [ ] **Step 3: Run and confirm RED**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. \
/Users/pray/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
-m unittest tests.test_prepared_report tests.test_daily_report -v
```

Expected: parser/command tests FAIL because the command does not exist.

- [ ] **Step 4: Implement local import after preflight**

Keep `deepseek_client` and `translation_pipeline` out of `cli.py` top-level
imports. Construct the service from `preflight.translation_assets` and never
reopen `config_root` after authorization. Read the key using a
regular/non-symlink/mode check, strip one terminal
newline, reject empty/multiline content and never retain it in result objects.
No production base-URL override is accepted.

- [ ] **Step 5: Run and confirm GREEN**

Run Step 3. Expected: PASS with fake transport only.

- [ ] **Step 6: Prove legacy commands still pass**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. \
/Users/pray/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
-m unittest tests.test_daily_report tests.test_storage_dingtalk -v
```

Expected: PASS; old commands remain available but are not used by the new lane.

### Task 8: Freeze DingTalk Bytes and Implement the Delivery Ledger

**Files:**

- Modify: `src/reddit_voc/dingtalk.py`
- Create: `src/reddit_voc/daily_report_delivery.py`
- Modify test: `tests/test_dingtalk_delivery.py`
- Test: `tests/test_daily_report_delivery.py`

**Interface signatures (implemented by the steps below):**

```python
class ArtifactHeadChecker(Protocol):
    def __call__(self, url: str, *, timeout_seconds: int) -> int: ...

TransportKind = Literal["synthetic", "external"]

class ExternalAttemptStartSink(Protocol):
    def __call__(self) -> None: ...

class DingTalkByteTransport(Protocol):
    transport_kind: TransportKind

    def __call__(
        self,
        *,
        webhook_url: str,
        body_bytes: bytes,
        secret: str | None,
        timeout_seconds: int,
        request_start_sink: ExternalAttemptStartSink | None,
    ) -> DingTalkSendResult: ...

@dataclass(frozen=True)
class DingTalkSendResult:
    status: str
    http_status: int | None
    response_hash: str
    response_text: str
    live_send: bool
    external_attempt_made: bool

class DingTalkTransportError(RuntimeError):
    external_attempt_made: bool

@dataclass(frozen=True)
class DeliveryDecision:
    sendable_part_indexes: tuple[int, ...]
    blocked_reason: str | None

@dataclass(frozen=True)
class DeliverySummary:
    run_id: str
    artifact_version_id: str | None
    outbox_sha256: str | None
    attempted_part_indexes: tuple[int, ...]
    sent_part_indexes: tuple[int, ...]
    rejected_part_indexes: tuple[int, ...]
    ledger_tip_before: str | None
    ledger_tip_after: str | None
    status: str
    report_live_send: bool
    alert_live_send: bool
    live_send: bool

def canonical_dingtalk_body_bytes(body: Mapping[str, object]) -> bytes: ...
def send_payload_bytes(
    *,
    webhook_url: str,
    body_bytes: bytes,
    secret: str | None = None,
    timeout_seconds: int = 10,
    request_start_sink: ExternalAttemptStartSink,
) -> DingTalkSendResult: ...

def load_same_run_delivery_records(
    *, database: Path, run_id: str
) -> tuple[Mapping[str, object], ...]: ...

def load_and_verify_delivery_ledger(
    path: Path, *, run_id: str
) -> tuple[Mapping[str, object], ...]: ...
def append_delivery_event(
    path: Path, *, event: Mapping[str, object]
) -> Mapping[str, object]: ...
def evaluate_duplicate_guard(
    *,
    ledger_entries: Sequence[Mapping[str, object]],
    db_records: Sequence[Mapping[str, object]],
    expected_outbox_sha256: str,
    authorize_resend: bool,
    requested_part_indexes: Sequence[int],
) -> DeliveryDecision: ...
def send_prepared_daily_report(
    *,
    database: Path,
    run_id: str,
    expected_artifact_version_id: str,
    expected_bundle_sha256: str,
    expected_outbox_sha256: str,
    authorization_id: str,
    roots: PreparedReportRoots,
    config_root: Path,
    webhook_url: str,
    webhook_secret: str | None,
    timeout_seconds: int,
    authorize_live_send: bool,
    authorize_resend: bool = False,
    resend_part_indexes: tuple[int, ...] = (),
    head_checker: ArtifactHeadChecker,
    transport: DingTalkByteTransport,
) -> DeliverySummary: ...
def send_report_failure_alert(
    *,
    roots: PreparedReportRoots,
    run_id: str,
    attempt_id: str,
    stage: str,
    reason_code: str,
    occurred_at: datetime,
    webhook_url: str,
    webhook_secret: str | None,
    timeout_seconds: int,
    authorize_failure_alert: bool,
    transport: DingTalkByteTransport,
) -> DeliverySummary: ...
```

- [ ] **Step 1: Write failing frozen-byte transport tests**

Assert the SHA recorded in the prepared part is the SHA of the exact UTF-8 body
passed to `urlopen`. Signing may change only the webhook URL at send time.
Reject invalid JSON bodies, non-object bodies, wrong message type, non-JSON 2xx
responses and every response whose parsed `errcode` is not numeric zero.
Preserve the existing dict-based `send_payload` for legacy callers.

The production transport declares `transport_kind="external"`; every injected
fake declares `transport_kind="synthetic"`. After validation, signing and
`Request` construction, `send_payload_bytes` invokes the mandatory
`request_start_sink` immediately before `urlopen`. The sink durably appends the
single part `attempting` ledger event with
`external_attempt_made=true` and fsyncs it; no earlier production `attempting`
event is written, and sink failure means no `urlopen`. From that boundary
onward, return or `DingTalkTransportError`
preserves `external_attempt_made=true`. Validation/signing/request construction
that fails before the sink records false. A synthetic transport receives a
null sink and must return false; invoking it is not evidence of a live send.
Pre-sink validation/signing/request-construction failure writes no `attempting`
event, returns terminal `local_pre_request_blocked`, keeps all live flags false
and consumes/closes the owner action; retry requires a new explicit
authorization rather than automatic reuse.

- [ ] **Step 2: Write failing ledger integrity tests**

Ledger path:

```text
<state_root>/delivery/<run_id>/ledger.jsonl
```

Require mode 700 directories and a mode 600 regular, non-symlink file.
Require ubuntu owner on every ledger directory/file; runtime tests inject the
expected UID/GID and the launcher runs the report container as that UID/GID.
Each canonical line has strictly increasing `sequence`, `previous_entry_hash`,
`entry_hash`, run/version/bundle/outbox/part hashes, timestamp and status.
Open with no-follow and append semantics, write one complete line, fsync the
file and parent directory. Reject truncation, duplicate sequence, broken chain,
unexpected keys, non-canonical lines and replacement with a symlink.

- [ ] **Step 3: Write failing state-machine tests**

For each part:

1. durable `attempting` with expected part hash;
2. exact-byte HTTP call;
3. durable `sent`, `rejected` or `unknown_delivery_state`;
4. only after `sent`, a strict one-time DB delivery record.

A dangling `attempting` becomes `unknown_delivery_state` and is never retried
automatically. If part 1 is `sent` and part 2 is `rejected`, a later owner-gated
resend may send only part 2 with matching `--expected-outbox-sha256`. Never
resend `sent` or `unknown` parts. Different outbox/restart-all requires new
explicit authorization.

Only a parsed DingTalk business response is determinate: `errcode=0` is sent;
a parsed nonzero `errcode` is rejected. Timeout, disconnect, malformed/non-JSON
response, process interruption or any transport failure after request start is
unknown, not rejected, and cannot be resent even with owner resend authority.

Failure-alert events use a separate `failure-alert` part kind in the same
run-level hash-chain ledger, receive `roots` and `attempt_id` explicitly, and
never reuse a report delivery ID. They follow the same
attempting/sent/rejected/unknown state machine. Tests assert an actual external
alert attempt changes `live_send` evidence even though the report outbox itself
was not sent.
Any evidenced real external report attempt sets `report_live_send=true` even
when rejected or unknown; any evidenced real external alert attempt sets
`alert_live_send=true`. Overall `live_send` is their logical OR, not a
success-only flag. Thus a real alert-only attempt reports
`report_live_send=false, alert_live_send=true, live_send=true`. Synthetic fake
transports keep all three flags false while still exercising the state machine.
Persist that `attempting + external_attempt_made=true` event immediately before
invoking `urlopen` through the production transport's request-start sink so
process interruption cannot erase this evidence. A synthetic transport writes
its own `attempting + external_attempt_made=false` fixture event and never
receives the external sink. If interruption happens after the durable sink and before
an HTTP outcome, classify it as `unknown_delivery_state`, keep live evidence
true and block retry. Reconcile declared transport kind, sink event and the
returned/error `external_attempt_made` field; any contradiction is unknown and
fail-closed, never permission to retry.

Follow the approved run-level rule literally: any `sent` or `unknown` live-send
event for the run, including a failure alert, blocks the whole report outbox and
all later candidates. A determinate `rejected` alert does not. Alert/report part
kinds remain distinct for evidence, but cannot be used to bypass the run-level
duplicate guard. Tests make this consequence visible before an owner authorizes
a failure alert.

- [ ] **Step 4: Write failing DB and artifact preflight tests**

Use a narrow SQLite connection in `daily_report_delivery.py`:

- read required `delivery_previews` columns before the first network call;
- load every existing successful `delivery_previews` record for the same
  `run_id`, across all candidate versions, outboxes and legacy delivery IDs,
  before artifact HEAD or transport;
- do not call migrate or alter schema;
- use strict `INSERT`, never `INSERT OR REPLACE`;
- duplicate/conflicting delivery IDs block;
- each successful part gets exactly one DB row; rejected/unknown parts get none;
- schema mismatch blocks before artifact HEAD/DingTalk;
- every immutable public URL must return HTTP 200 to a fake HEAD checker before
  the first DingTalk attempt.

Reconcile the complete same-run DB set with the run-level ledger. Any existing
DB success for the run blocks the whole outbox even when it names another
candidate/part/hash. Any ledger `sent` or `unknown_delivery_state` also blocks.
A missing/conflicting DB or ledger counterpart is fail-closed rather than
treated as permission to send. Tests include a legacy DB row for a different
candidate, a dangling/unknown ledger entry, and DB/ledger mismatches; each must
block before HEAD and transport.

Top-level compatibility symlinks are not a send trust source.

- [ ] **Step 5: Run and confirm RED**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. \
/Users/pray/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
-m unittest tests.test_dingtalk_delivery tests.test_daily_report_delivery -v
```

Expected: new interfaces/tests FAIL.

- [ ] **Step 6: Implement exact-byte send and durable state**

Load and verify `prepared-current.json` once, then revalidate its immutable
private/public bundle and outbox. Before HEAD/webhook, require exact owner-
authorized run, artifact version, bundle SHA and outbox SHA; require
`translation_status=complete` and manifest translation/report fingerprints to
match current/index/payloads. A normal first send blocks if any historical
candidate for the run has a `sent` or `unknown` ledger event or any same-run DB
success exists. Load and reconcile both evidence stores before any HEAD or
webhook access.

The delivery module imports `report_contracts` and `prepared_bundle` only. A
fresh-process test must prove it never imports `prepared_report`,
`deepseek_client`, `translation_pipeline` or `daily_report`.

- [ ] **Step 7: Run and confirm GREEN**

Run Step 5. Expected: PASS with fake HEAD and DingTalk transports only.

### Task 9: Add the Gated Send-Prepared CLI

**Files:**

- Modify: `src/reddit_voc/cli.py`
- Modify test: `tests/test_daily_report_delivery.py`
- Modify test: `tests/test_prepared_report.py`

**Command:**

```text
reddit-voc send-prepared-daily-report
  --database PATH
  --run-id RUN_ID
  --expected-artifact-version-id VERSION_ID
  --expected-bundle-sha256 SHA256
  --expected-outbox-sha256 SHA256
  --authorization-id ID
  --public-root PATH
  --private-root PATH
  --state-root PATH
  --config-root PATH
  --timeout-seconds N
  [--authorize-live-send]
  [--authorize-resend --resend-part-index N]
```

- [ ] **Step 1: Write failing send-boundary tests**

Live send requires:

```text
REDDIT_VOC_DINGTALK_MODE=live
REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND=1
valid DingTalk webhook from the mounted report env
--authorize-live-send
```

Every missing combination returns blocked before artifact HEAD or send. Resend
also requires `--authorize-resend`. First send and resend both require exact
expected artifact version, bundle SHA and outbox SHA; they are never inferred
only from a mutable current pointer. A path-safe owner-issued authorization ID
is also required and written to the ledger. The parser has no DeepSeek
key/model/provider argument.
Resend requires one or more explicit `--resend-part-index` values that exactly
match the owner permit and ledger-proven rejected parts. Unknown or sent
indexes are never accepted.

- [ ] **Step 2: Write a fresh-process import/call graph test**

Run the command in a subprocess with fake loader/transport. Assert:

- `deepseek_client` and `translation_pipeline` are absent from `sys.modules`;
- no `build_daily_report`, renderer or translation function is called;
- no DeepSeek key path is opened;
- verified outbox bytes are read once and the same bytes reach the transport.

Add the failure-alert integration to `prepare-daily-report` in this task:
`--authorize-failure-alert` plus
`REDDIT_VOC_ENABLE_REPORT_FAILURE_ALERT=1` are both required. The command may
call `send_report_failure_alert` only after an immutable blocked attempt exists,
using that run/attempt ID and a body containing only run ID, stage, reason code
and time. With either gate missing there is no alert transport call. Any actual
external alert attempt records `alert_live_send=true` and overall
`live_send=true`, including rejected/unknown outcomes. The subprocess fake is
explicitly synthetic and keeps those flags false; a separate mocked-urlopen
fixture crosses the real request-start boundary and expects them true without
internet access.

- [ ] **Step 3: Run and confirm RED**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. \
/Users/pray/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
-m unittest tests.test_daily_report_delivery tests.test_prepared_report -v
```

Expected: command tests FAIL because the parser/dispatch does not exist.

- [ ] **Step 4: Implement the send command**

Use a command-local import of `daily_report_delivery`. Load webhook/secret only
after all local pointer/index/DB/duplicate checks that do not require them.
Print only hashes, IDs, status/reason and counts. Never print message body,
source text, webhook, signature or env contents.

- [ ] **Step 5: Run and confirm GREEN**

Run Step 3. Expected: PASS using explicitly synthetic transports whose
`external_attempt_made=false`; therefore `live_send=false` in all local tests.
Separate mocked-request-start tests exercise real-transport evidence and expect
`live_send=true` without accessing the internet.

### Task 10: Switch the Container Wrapper and Preserve Web Compatibility

**Files:**

- Modify: `scripts/run_daily_report.sh`
- Create: `scripts/report_runtime_smoke.py`
- Create: `config/report/reddit-voc-report.env.example`
- Modify: `.env.example`
- Test: `tests/test_daily_report_wrapper.py`
- Modify test: `tests/test_webapp.py`

- [ ] **Step 1: Write failing wrapper argument/gate tests**

Follow the fake-command/NUL-argv pattern in
`tests/test_backfill_wrappers.py`. Require exactly three phases:

```text
run_daily_report.sh prepare --prepare-action-authorization-id ACTION_ID \
  [--provider-authorization-id PROVIDER_ID]
run_daily_report.sh send \
  --expected-artifact-version-id VERSION_ID \
  --expected-bundle-sha256 SHA256 \
  --expected-outbox-sha256 SHA256 \
  --authorization-id ID
run_daily_report.sh smoke --config-root CONFIG_ROOT --work-root ISOLATED_TMP_ROOT
```

The wrapper reads only `/run/secrets/reddit_voc_report.env` after verifying it
is regular/non-symlink/mode 600 for `prepare` or `send`, using a strict
non-executing `KEY=literal-value` parser that splits only on the first `=`,
rejects duplicate/unknown/missing keys, NUL/CR/newlines and never uses `source`
or `eval`. `smoke` does not
inspect, source or mount report env, key or webhook. The wrapper never calls
`run_daily_report_dry_run.sh`, `build-daily-report`,
`send-daily-report-live` or Docker/Compose. It adds Provider authorization only
when the two env gates are enabled and the host supplies a verified
`--provider-authorization-id`; it never invents the ID. It adds live-send
authorization only when the two live gates and a verified exact send permit
tuple are present. `smoke` forces all gates off and needs neither key nor
webhook.
Production prepare always receives the separately verified prepare-action ID,
including cache-only/zero-visible runs; this ID never implies Provider
authorization.
It adds `--authorize-failure-alert` only when
`REDDIT_VOC_ENABLE_REPORT_FAILURE_ALERT=1`; default is no alert.
The send phase requires the exact tuple and authorization ID as argv from a
verified owner/schedule permit supplied by the host launcher. It passes them
byte-for-byte to the CLI and never reads `prepared-current.json` to invent or
approve values. NUL-argv tests cover metacharacters, missing fields and
mismatched hashes.
For a resend permit it additionally passes `--authorize-resend` and the exact
permitted `--resend-part-index` values; an initial permit may not inject resend
arguments.

For the production launcher, `prepare` always adds `--defer-host-commit`, the
isolated handoff root and the exact authorization-specific attempt-root mount.
It outputs the commit-request SHA/tuple but cannot advance mutable current or
projections. A direct L1 fixture invocation may omit defer and exercise the
local convenience commit. NUL-argv tests prove the production wrapper never
drops the defer flag or substitutes the general state/control root.

`report_runtime_smoke.py` has one deterministic operation: load and hash the
release config/prompts/schemas, import the neutral prepare/delivery modules in
separate subprocesses, create an isolated temporary synthetic SQLite fixture
and roots, render/freeze/verify one synthetic prepared bundle with an injected
no-network translation result, then remove the temporary roots. It must not
import/construct `DeepSeekClient`, inspect key/webhook paths, perform HEAD/send,
touch production DB/outputs/state or accept a live gate. Exit 0 prints only:

```text
runtime_smoke=passed
translation_provider_call=false
translation_provider_attempt_made=false
report_live_send=false
live_send=false
database_write=local-test-only
```

Any failure exits nonzero with a sanitized reason code and the same false
side-effect fields.

- [ ] **Step 2: Write failing secret-redaction tests**

`config/report/reddit-voc-report.env.example` contains empty secrets and:

```text
REDDIT_VOC_TRANSLATION_MODE=dry_run
REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION=0
REDDIT_VOC_DINGTALK_MODE=dry_run
REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND=0
REDDIT_VOC_ENABLE_REPORT_FAILURE_ALERT=0
```

Do not remove existing legacy variables from `.env.example`; label them
legacy/local so unrelated workflows keep their configuration contract.

- [ ] **Step 3: Write web compatibility tests**

Without changing `webapp/app.py`, prove:

- nested `prepared/<run>/<version>/...` URLs resolve and support HEAD;
- top-level CSV/XLSX/HTML compatibility symlinks remain discoverable by
  `load_detail_translations()` and `artifact_records()`;
- symlinks escaping the outputs root are rejected;
- changing top-level projections does not change immutable nested content.

- [ ] **Step 4: Run and confirm RED**

```bash
bash -n scripts/run_daily_report.sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. \
/Users/pray/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
-m unittest tests.test_daily_report_wrapper tests.test_webapp -v
```

Expected: wrapper tests FAIL; existing web resolver tests remain green.

- [ ] **Step 5: Implement the phase dispatcher and projection compatibility**

Use arrays for CLI argv, `set -euo pipefail` and `umask 077`. Do not use `eval`.
The prepared commit owns projection updates; the webapp remains read-only.
Tests invoke `smoke` with nonexistent env/key/webhook paths and network calls
set to fail if reached; it must still pass against isolated fixture roots.

- [ ] **Step 6: Run and confirm GREEN**

Run Step 4. Expected: PASS with no real command, network or key read.

### Task 11: Build the Report-Only Release, Launcher and Rollback Controls

**Files:**

- Modify: `scripts/server_daily_report.sh`
- Create: `scripts/build_daily_report_release.py`
- Create: `scripts/report_noninterference.py`
- Create: `scripts/server_daily_report_admin.sh`
- Create: `scripts/server_update_daily_report_runtime_env.sh`
- Test: `tests/test_daily_report_launcher.py`
- Test: `tests/test_daily_report_release.py`
- Test: `tests/test_daily_report_ops.py`

- [ ] **Step 1: Write failing release-manifest tests**

The exact release candidate allowlist contains every changed runtime file plus
the admin/evidence tests executed from the uploaded candidate:

```text
src/reddit_voc/cli.py
src/reddit_voc/daily_report.py
src/reddit_voc/dingtalk.py
src/reddit_voc/report_contracts.py
src/reddit_voc/deepseek_client.py
src/reddit_voc/translation_pipeline.py
src/reddit_voc/prepared_bundle.py
src/reddit_voc/prepared_report.py
src/reddit_voc/daily_report_delivery.py
scripts/run_daily_report.sh
scripts/server_daily_report.sh
scripts/report_runtime_smoke.py
scripts/build_daily_report_release.py
scripts/report_noninterference.py
scripts/server_daily_report_admin.sh
scripts/server_update_daily_report_runtime_env.sh
config/translation_terms.json
config/prompts/deepseek-translation-v1.txt
config/prompts/deepseek-semantic-validator-v1.txt
config/schemas/daily-translation-manifest-v1.schema.json
config/schemas/daily-translation-attempt-v1.schema.json
config/schemas/daily-prepared-bundle-index-v1.schema.json
tests/test_report_contracts.py
tests/test_deepseek_client.py
tests/test_translation_pipeline.py
tests/test_prepared_report.py
tests/test_daily_report.py
tests/test_dingtalk_delivery.py
tests/test_daily_report_delivery.py
tests/test_daily_report_wrapper.py
tests/test_daily_report_launcher.py
tests/test_daily_report_release.py
tests/test_daily_report_ops.py
tests/test_webapp.py
```

`report-release-manifest.json` records schema version, exact
`sha256:<64>` image ID, `role=runtime|admin|test`, path/mode/size/SHA for each
file and no extras.
`release_sha256` is the canonical manifest SHA and must equal the release
directory leaf name. Reject tags, missing/extra files, duplicate keys,
symlinks, traversal and wrong mode/size/hash. Mount individual files read-only;
never overlay the whole release on `/app`. Only `role=runtime` entries are
mounted into report containers; admin/test entries are verified and executed
from the immutable release path during L4.

The uploaded-candidate verifier sets the immutable release as the only project
`PYTHONPATH`/config root, disables user site packages, and asserts every
`reddit_voc.*.__file__`, test `__file__`, prompt/schema/terms hash and launcher
hash resolves to a manifest entry under that release. Any fallback to repo
checkout or base-image `/app` code blocks. Verification evidence records both
release SHA and manifest SHA.

- [ ] **Step 2: Write failing fixed-launcher ordering tests**

Using fake `flock`, `readlink`, `stat` and Docker, prove this order:

1. clear inherited secret variables and set `umask 077`;
2. acquire `/home/ubuntu/.reddit-voc/locks/daily-report.lock`;
3. validate path-safe run ID;
4. resolve `/opt/reddit-voc-report/current` exactly once;
5. verify exact release manifest/tree;
6. execute the verified immutable updater's `recover-gates` under the held lock
   plus admin `recover-prepared-state`, and require clean terminal gate and
   projection journals before permit validation, report-env/key metadata,
   client construction, HEAD or transport;
7. for Provider-enabled prepare, validate the one-shot provider authorization
   or bounded schedule permit against exact release/run/date/unused state before
   key metadata, client construction or any Provider attempt; smoke and
   send-only operations skip this Provider authorization check;
8. apply phase-sensitive secret checks after the lock: `smoke` checks neither
   report env, key nor webhook; `prepare`/`send` verify report-env metadata and
   use a strict allowlisted parser for gate names without exporting/printing
   secret values; only `prepare` with both DeepSeek gates live verifies/mounts
   the key; `send` never checks/mounts the key;
9. verify `reddit_voc_report_net` is a user bridge with no permanent members;
10. launch and inspect defer-host-commit prepare;
11. after the prepare container is gone, its network is empty and Provider
    gates are restored off, invoke the exact immutable host admin
    `commit-prepared` with the owner-passed run/version/bundle/outbox/commit-
    request hashes plus exact reserved prepare-action ID, nullable Provider
    authorization ID and attempt ID;
    verify current/projections/registry before terminalizing the
    prepare permit;
12. launch and inspect send only after commit succeeds and an exact/bounded
    send permit binds the candidate tuple.

Lock contention must invoke no `readlink`, `stat` or Docker.
`docker compose`, shared networks and mutable image tags are forbidden.
It writes only a sanitized `lock_busy` blocked-attempt record under a new
attempt ID, without resolving the release or reading report secrets.

- [ ] **Step 3: Pin the container argv contract**

Both jobs use `docker run -d --rm --pull=never` with:

```text
--network reddit_voc_report_net
--cpus 1.0
--memory 2g
--pids-limit 256
<exact image ID from the verified release manifest>
```

Prepare mounts DB/config/release and mutable prepared state read-only, mounts
the key read-only only for the live DeepSeek gate state, and mounts only
the host-precreated exact empty public-staging attempt directory, exact empty
private-staging attempt directory, exact empty handoff attempt directory, logs
and that authorization ID's provider-attempt sink read-write. Final public/
private/blocked roots are read-only and no staging/blocked parent is mounted.
It receives no
writeable current/projection/commit-registry path and no permit/gate/audit
parent. After it exits, Provider gates are off and the host-side immutable
`commit-prepared` helper alone writes current/projections/registry under the
same lock. Send mounts no DeepSeek key or handoff/attempt sink, mounts prepared
public/private, current state and release/config read-only, and mounts only its
exact run-level delivery-ledger directory, log path and DB file read-write.
Neither job mounts `/home/ubuntu/.reddit-voc/report-control/` wholesale.

Before `docker run`, the held-lock launcher generates the attempt/version IDs,
creates each exact empty directory with O_EXCL-equivalent checks and binds only
those leaves. Container inspection rejects any parent/general-root RW mount.
After exit, the leaves are unmounted before `commit-prepared` or
`commit-blocked` may atomically publish them. Failure/signal cleanup never
deletes an already published immutable path.

Before either wrapper may act, it waits on a mode-600 permit file in a
per-container mode-700 gate directory. The host reads `--cidfile`, runs
`docker inspect` and verifies exact image, single network, limits, mounts and
absence of secret values in Docker argv/env. Only then atomically create the
permit, attach logs and wait for exit. On mismatch remove the container and
leave `translation_provider_attempt_made=false`/`live_send=false`.
Run every container with the exact ubuntu UID/GID so ledger/state ownership is
preserved. Add separate argv/metadata tests for disabled/cache-only prepare,
live DeepSeek prepare, send and smoke.

- [ ] **Step 4: Write failing bootstrap/admin tests**

`server_daily_report_admin.sh bootstrap` requires:
`--authorize-bootstrap`, expected old-launcher SHA, owner-approved
`--expected-new-launcher-sha256` and expected release SHA.
It:

- runs outside the 08:00 window and writes a freeze marker;
- checks old report processes/Compose one-offs before and after freeze;
- backs up old launcher and report env outside the repo with 700/600 modes;
- atomically installs the fixed launcher/release/current pointer;
- creates/audits only `reddit_voc_report_net`;
- keeps Provider/live gates off;
- runs no-provider/no-send smoke;
- compares L4 before/after, then removes freeze.

Assert cron SHA is unchanged and no cron reload, Nginx action, main-site action,
collector action or LibreTranslate action is available in the script.
Before install and after rename, verify the new launcher is the exact expected
SHA, ubuntu-owned, regular/non-symlink and mode 0755. Bind that launcher SHA to
the release manifest and L4 evidence.

Add owner-authorization permit tests. `install-prepare-permit` atomically
installs a mode-600, ubuntu-owned, regular/non-symlink
`report-prepare-permit-v1` with exact authorization ID, release SHA, run ID,
at-most-100 attempt cap and expiry; the launcher validates
it before key metadata and passes its ID to prepare. `install-send-permit` atomically installs
a mode-600, ubuntu-owned, regular/non-symlink
`report-send-permit-v1` under the same host lock with exact authorization ID,
`action=initial|resend`, release SHA, run ID, artifact version, bundle SHA,
outbox SHA, explicit resend part indexes (empty for initial) and expiry.
`install-schedule-permit` uses a separate schema and is accepted only for the
bounded L7 contract in Task 14. Neither permit contains secrets.
`install-admin-permit` installs `report-admin-permit-v1` with exact path-safe
authorization ID, `action=bootstrap|activate|rollback`, release SHA, expected
launcher SHA when applicable and expiry. Bootstrap/activate/rollback state
changes require the matching unused admin permit; terminal gate disable itself
also has the safe exception defined below so a missing live permit can never
prevent shutdown.
All permits live under mode-700
`/home/ubuntu/.reddit-voc/report-control/permits/`; non-secret authorization
audit and per-authorization attempt sinks live in sibling `audit/` and
`provider-attempts/` directories. None is under `/opt/reddit-voc-report/state`
or mounted wholesale into a container.
All permit installs use a same-directory temporary regular file, mode/owner
checks, canonical JSON, file+parent fsync and atomic rename; existing immutable
authorization IDs cannot be overwritten.

`init-shadow-root --shadow-root ABS_PATH` first writes a non-secret immutable
`report-shadow-root-v1` descriptor under separate shadow-secret-provisioning
authority. The descriptor binds the canonical repo-external mode-700 root,
owner, candidate/release SHA and isolated path map, proves it is neither equal
to nor beneath/containing production secrets/control/state/output/release
roots, and grants no key read or Provider call. `install-env`, `install-key`,
metadata `--check` and disable-only recovery validate this descriptor rather
than requiring a Provider permit.

`install-shadow-permit --shadow-root ABS_PATH` is separate and requires that
descriptor. Its
`report-shadow-permit-v1` binds exact authorization ID, candidate/release SHA,
natural-day run ID, copied-DB SHA, canonical isolated public/private/state/
public-staging/private-staging/blocked/handoff roots, maximum 100 attempts, one report, no live send and
expiry. Reserve it before key read, make it terminal on success/block/error and
never copy it into the production control root.

After prepare, the launcher may read the current candidate tuple as facts under
the still-held lock. It may send only when an unconsumed exact permit matches
all fields, or a valid bounded schedule permit explicitly authorizes that date
and same-lock candidate. It passes the exact tuple/authorization ID to
`run_daily_report.sh send`. The mutable pointer never supplies authority.
Missing/expired/mismatched/consumed permits keep `live_send=false`.

Add `server_daily_report_admin.sh recover-prepared-state`, `commit-prepared`
and `commit-blocked`. Recovery requires the same lock/release verification, runs
the neutral projection/current recovery before any prepare/send container, and
opens no DB/key/network. `commit-prepared` accepts only exact
expected release, Provider authorization ID, attempt ID, run, artifact-version,
prepare-action authorization ID, bundle, outbox and commit-request SHAs,
revalidates that exact action permit is still reserved and that nullable
Provider authorization matches the attempt ledger for this action,
requires the still-held verified lock FD, and invokes only the immutable
Provider-neutral commit entrypoint from that release. L4 preflight pins a host
Python 3.11+ interpreter path; commit uses `PYTHONNOUSERSITE=1`, an exact
release-only `PYTHONPATH`, and verifies every loaded `reddit_voc` module path/
hash against the release manifest before state mutation. It re-verifies the
handoff and both immutable bundle trees, opens no key/DB/network, atomically
advances current/projections/registry and emits hashes/status only. Missing,
extra, stale or mismatched handoff data leaves current unchanged. Failure-
injection tests prove the prepare permit becomes terminal blocked/unknown and
the candidate remains uncommitted; success terminalizes only after pointer,
projections and registry all verify.
`commit-blocked` accepts the same authorization/attempt binding, verifies the
handoff contains only one schema-valid sanitized blocked candidate, atomically
publishes it to the previously non-existent exact blocked attempt path and
cannot touch current/final bundle/projections. It is used after a failed worker
only once gates are all off.

- [ ] **Step 5: Write failing runtime-env installer tests**

`--check` validates owner/type/mode and required variable names while printing
only `<redacted>`. Interactive install reads from stdin, rejects command-line
secret values and supports separate `install-env` and `install-key` operations.
Each operation uses no-echo terminal input or a secret-manager stdin pipe,
creates a same-directory mode-600 temporary regular file, sets ubuntu owner,
fsyncs file and parent, and atomically renames it. Initial report gates are
forced off. The key target is the separate fixed
`/home/ubuntu/.reddit-voc/secrets/deepseek-api-key`. Neither operation reads the
installed key back, prints a secret/hash, exports it to process env, or implies
Provider authorization.

`install-env|install-key|--check --shadow-root ABS_PATH` use only the
descriptor-bound isolated shadow secrets directory and shadow lock, with the same atomic/
redaction rules. They reject any root equal to, inside or containing a
production secrets/control/state/output/release path. Shadow secret provisioning
requires its own explicit authority and never mutates the fixed production
targets.

The same updater also provides only these non-secret lifecycle subcommands:

```text
set-gates --authorization-id ID --expected-release-sha256 SHA \
  --translation-mode dry_run|deepseek \
  --enable-deepseek 0|1 \
  --dingtalk-mode dry_run|live \
  --enable-dingtalk-live-send 0|1 \
  --enable-failure-alert 0|1 [--terminal-kill-switch] [--shadow-root ABS_PATH]
restore-gates --journal-id ID [--shadow-root ABS_PATH]
recover-gates [--shadow-root ABS_PATH]
```

In production they acquire
`/home/ubuntu/.reddit-voc/locks/daily-report.lock`; shadow mode acquires only
the descriptor-bound `<shadow-root>/lock`. The only alternative is an inherited,
still-locked file descriptor that the updater validates against the applicable
exact lock device/inode and confirms with nonblocking `flock`; a string/argv/
env "lock token", closed FD, unrelated FD or unlocked FD is never accepted.
Concurrency tests hold each lock from another process and require zero gate
mutation. They mutate only these five
allowlisted names in the fixed mode-600, ubuntu-owned, regular/non-symlink
`/home/ubuntu/.reddit-voc/secrets/reddit-voc-report.env`:
`REDDIT_VOC_TRANSLATION_MODE`,
`REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION`,
`REDDIT_VOC_DINGTALK_MODE`,
`REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND` and
`REDDIT_VOC_ENABLE_REPORT_FAILURE_ALERT`. Unknown keys/values or an unexpected
release/authorization blocks. Preserve every non-gate byte and secret value;
never place secrets or their hashes in argv, stdout, the journal or audit log.

Explicit `--shadow-root` always validates the immutable root descriptor and
uses only `<shadow-root>/lock`,
`<shadow-root>/secrets/reddit-voc-report.env`,
`<shadow-root>/control/gates/` and `<shadow-root>/secrets/snapshots/`. The
shadow updater must prove it did not open or mutate any production env/control/
state/output path. Production and shadow locks/journals/snapshots never mix.
Enabling `set-gates` and key read require the exact matching shadow permit in
reserved state. `restore-gates` accepts that same ID in reserved, terminal or
unknown state when its journal binds the transaction. Disable-only
`recover-gates` requires only the descriptor and must work with missing,
installed, reserved, terminal or unknown permit state so a crash can never
prevent all-off recovery. Secret installation/check requires separate
provisioning authority plus the descriptor, not a Provider permit.
Use the same non-executing literal env grammar as Task 10 and reject duplicate,
malformed or non-allowlisted assignments before making a temporary file.
An enabling `set-gates` requires all five current gates in their disabled state
and no active journal; nested/enabled-to-enabled transitions are forbidden.
`--terminal-kill-switch` is accepted only when the target is the exact all-off
state; it may move any schema-valid current gate state to all-off, is terminal
and can never restore the former enabled state. Because it can only remove side
effect authority, it is the sole no-live-permit exception: require the verified
immutable updater/release, valid locked FD and a path-safe audit authorization
ID/reason, but never require an active prepare/send/schedule permit. Repeated
same-ID all-off is idempotent; wrong release/action, reused ID with different
facts or any target containing an enabled gate blocks. Tests cover the
exception and prove it cannot be used for enable, restore or another admin
mutation.

Before replacement, write a mode-600 hash-chained journal under the host-only
`/home/ubuntu/.reddit-voc/report-control/gates/` containing journal ID, authorization ID,
release SHA, prior/target gate values, phase and timestamps only. It must not
store a digest, length or other derivative of any secret-bearing env content.
Before the first gate edit, copy the exact secret-bearing env bytes to a random,
mode-600, non-symlink opaque snapshot under
`/home/ubuntu/.reddit-voc/secrets/report-env-snapshots/`; the journal stores
only that random snapshot ID and a canonical digest of the five non-secret gate
values. Snapshot bytes/digest/length never enter argv, logs, audit or journal,
the snapshot is never mounted, and it is removed only after a verified terminal
state and parent fsync.
Use a same-directory regular temporary file, fsync, atomic
rename and parent fsync for both env and journal. `restore-gates` is idempotent
and restores the recorded prior gate values only when the current five gate
values match the recorded target state under the lock; conflict enters the
mandatory all-off recovery path below.
`recover-gates` runs before any
permit/key/provider/send operation and resolves an interrupted transaction to
the recorded all-off/prior state, never to an enabled state.

On target mismatch, missing/truncated/broken journal, missing/corrupt snapshot
or multiple active journals, remain under the lock and force the five gates to
the exact all-off state using a valid opaque snapshot where possible. If no
valid env can be safely reconstructed, atomically quarantine the unreadable
mode-600 file and install a minimal mode-600 allowlisted env with all gates off
and empty webhook/secret values. Write a sanitized terminal incident, verify
all-off with the non-executing parser, and only then release the lock. Never
restore a prior live state on a recovery/kill-switch path.

Failure-injection tests cover interruption before/after snapshot, temp write,
file fsync, rename, parent fsync, action execution and restore, plus prior-live,
target-live, env conflict, missing/truncated/hash-broken journal/snapshot and
multiple active journals. The next launcher must run
`recover-gates`, leave all five gates off or at their recorded prior disabled
state, write a terminal journal record and perform zero Provider/send attempts.
`set-gates` is not authorization: enabling accepts only a separately verified
permit and exact immutable release tuple supplied by the launcher. The only
exception is the audited all-off terminal kill switch above.

- [ ] **Step 6: Write failing noninterference/rollback tests**

`report_noninterference.py capture` records only redacted facts:

- main site/LibreTranslate container ID, StartedAt, RestartCount and mounts;
- Nginx config SHA, cron SHA and collector-wrapper SHA;
- DB schema fingerprint/inode/size/mtime;
- report container image/network/limits;
- fixed launcher SHA/current release;
- prepared pointer and projection targets;
- active backfill state plus Provider call/attempt counters;
- the five redacted report gate values, active/terminal gate-journal IDs,
  active/terminal owner-permit IDs, authorization-audit tip and per-ID attempt
  counts from the host-only control root;
- opaque env-snapshot IDs/count/reference state only (never bytes, length or
  digest): every active snapshot must be referenced by exactly one active gate
  journal, and every terminal capture requires snapshot count zero; an orphan
  snapshot blocks and triggers held-lock recovery/cleanup;
- an in-memory `report_env_non_gate_bytes_unchanged` boolean, without recording
  the secret-bearing bytes, their length or any digest;
- all three Docker network member sets at before, during and after snapshots.

`compare --layer L4|L5|L6` uses the exact allowlists from the approved design.
Each layer requires finally-all-off, zero active gate journal/permit, unchanged
non-gate env bytes and no unexpected control records. L4 allows only its
terminal bootstrap/gate records; L5 only its exact prepare authorization,
attempt and commit terminal records; L6 only its exact send authorization and
delivery terminal records. Every other control-plane delta blocks acceptance.
Rollback ordering is `recover-gates`, then an allowlisted `set-gates
--terminal-kill-switch` all-off transaction with no restore, followed by durable
terminal/revocation of every
active prepare/send/schedule permit, previous release/current, approved
prepared pointer/projection recovery, no-key/no-provider/no-send smoke, then
noninterference compare. Revocation happens under the same lock before any
release/pointer switch. With no previous release, remove `current` and stay
fail-closed. With no previous approved prepared bundle, remove
`prepared-current.json` and every top-level projection, retain immutable
candidates and every URL already referenced by a sent message. If a bad bundle
was sent, write an incident and never claim the message was withdrawn. Never
restore the old live launcher, auto-enable LibreTranslate, reload cron, restart
services, recollect or resend.

The all-off kill switch is always allowed by its disable-only exception. Every
subsequent rollback mutation requires an exact unused
`report-admin-permit-v1 action=rollback`; without it, stay all-off, write the
sanitized blocked record and stop before changing release/current/projections.

Both `activate` and `rollback` must acquire the same non-blocking host lock as
their first stateful action. Lock contention permits only a sanitized blocked
record and causes zero secret/current/network/projection mutation. Tests cover
success and every failure point after lock acquisition.
Prepare/send/schedule permit install/disable/reserve/consume operations use the
same lock and append a non-secret authorization audit record. Before any
Provider HTTP side effect, durably reserve the prepare/schedule permit and each
attempt sequence; before DingTalk, consume the send permit, then append the
durable `attempting` ledger event, then call transport. A crash after reserve or
consume makes the authorization terminal/unknown and never automatically
reusable.

- [ ] **Step 7: Run and confirm RED**

```bash
bash -n \
  scripts/server_daily_report.sh \
  scripts/run_daily_report.sh \
  scripts/server_daily_report_admin.sh \
  scripts/server_update_daily_report_runtime_env.sh

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. \
/Users/pray/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
-m unittest \
  tests.test_daily_report_launcher \
  tests.test_daily_report_release \
  tests.test_daily_report_ops \
  tests.test_daily_report_wrapper -v
```

Expected: new launcher/release/ops tests FAIL before implementation.

- [ ] **Step 8: Implement the isolated release lane**

Do not call `scripts/deploy_webapp_tencent.sh`. Do not edit Compose. Use the
existing image ID only with `--pull=never`. If the image has no RepoDigest,
pin the exact output of
`docker image inspect --format '{{.Id}}' "$REPORT_IMAGE_REFERENCE"`; never fall
back to a tag.

Network lifecycle checks require: empty valid bridge before launch; during
execution, the only member is the exact current CID; after success, non-zero
exit, timeout, inspect mismatch or signal, the container is absent and the
network is empty. Clean cidfile/gate directories on every path. A pre-existing
network with wrong driver/options/members blocks; never delete/recreate it or
any shared network as an automatic repair.

- [ ] **Step 9: Re-run and confirm GREEN**

Run Step 7. Expected: shell syntax and all fake-runtime tests PASS; no Docker or
host mutation has occurred.

### Task 12: Complete L1 Local Verification and Documentation

**Files:**

- Modify: `README.md`
- Modify: `.codex/context-pack.md`
- Review: `docs/superpowers/specs/2026-07-13-deepseek-daily-report-translation-design.md`
- Review: all files from Tasks 1-11

- [ ] **Step 1: Run focused tests serially**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. \
/Users/pray/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
-m unittest \
  tests.test_report_contracts \
  tests.test_deepseek_client \
  tests.test_translation_pipeline \
  tests.test_prepared_report \
  tests.test_daily_report \
  tests.test_dingtalk_delivery \
  tests.test_daily_report_delivery \
  tests.test_daily_report_wrapper \
  tests.test_daily_report_launcher \
  tests.test_daily_report_release \
  tests.test_daily_report_ops \
  tests.test_webapp -v
```

Expected: PASS. These are L1 mock tests only:
`translation_provider_attempt_made=false`, `live_send=false`.

- [ ] **Step 1B: Execute the real provider-free runtime smoke**

```bash
REDDIT_VOC_REPORT_ENV_FILE=/definitely/not-present/report.env \
DEEPSEEK_API_KEY_FILE=/definitely/not-present/deepseek.key \
scripts/run_daily_report.sh smoke \
  --config-root config \
  --work-root tmp/report-runtime-smoke-l1
```

Expected exit 0 and exact boundary fields:

```text
runtime_smoke=passed
translation_provider_call=false
translation_provider_attempt_made=false
report_live_send=false
live_send=false
database_write=local-test-only
```

The isolated work root is removed by the smoke command. Production DB/output/
private/state paths remain unopened.

- [ ] **Step 2: Run the full suite on one stable snapshot**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. \
/Users/pray/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
-m unittest discover -s tests -p 'test_*.py'
```

Expected: PASS with no skipped/modified tests used to manufacture success.
Do not run another test/build process concurrently against shared SQLite/output
paths. If a failure is unrelated, preserve its exact output and report it;
do not describe the full suite as passing.

- [ ] **Step 3: Run shell/static boundary checks**

```bash
bash -n \
  scripts/run_daily_report.sh \
  scripts/server_daily_report.sh \
  scripts/server_daily_report_admin.sh \
  scripts/server_update_daily_report_runtime_env.sh
```

```bash
rg -n "docker compose|reddit_voc_site_net|lighthouse_ai_video_net|deploy_webapp_tencent" \
  scripts/server_daily_report.sh scripts/run_daily_report.sh
```

Expected for the `rg` command: no matches.

```bash
rg -n "deepseek_client|translation_pipeline|build_daily_report|render_" \
  src/reddit_voc/daily_report_delivery.py
```

Expected: no matches.

```bash
rg -n "INSERT OR REPLACE|migrate\\(" \
  src/reddit_voc/prepared_report.py src/reddit_voc/daily_report_delivery.py
```

Expected: no matches.

- [ ] **Step 4: Update durable documentation**

README must state:

- Chinese-first/English-excerpt display and full-source attachments/links;
- prepare/send split and legacy-command boundary;
- exact gates and reason codes;
- report-only secret/network/release paths;
- evidence layers and what each does not prove;
- rollback and unknown-delivery behavior.

Update `.codex/context-pack.md` to point to the approved design, this plan,
test evidence and current implementation boundary. Do not change historical
backfill/collector facts.

- [ ] **Step 5: Perform independent code review**

Review the complete diff for:

- Provider input occurs only after visibility/cap/schema/gate preflight;
- prompt and terms have one versioned source;
- send import graph has no Provider or renderer path;
- networked prepare cannot mutate current/projections/registry; only the
  post-gate host neutral commit helper can, and no container receives the host
  control root;
- all failure paths are fail-closed;
- immutable hash preimages have no self-reference;
- secret data cannot enter logs/manifests/argv;
- no collector/backfill/webapp runtime/migration/Compose changes.

Resolve every P0/P1 finding and rerun the affected focused tests plus full suite.
Do not advance with an open P0/P1.

- [ ] **Step 6: Record the L1 boundary and diff**

```bash
git diff --check
git status --short
```

Historical L1 completion claim after Task 11 fake-host verification. This block
records the pre-L2 boundary and is superseded by the Task 13 terminal update
below; it must not be quoted as current state:

```text
local_implementation=L1_verified
provider_call=false
translation_provider_call=false
translation_provider_attempt_made=false
live_send=false
production unchanged
deepseek_api_key_read=false
deploy_executed=false
cron_changed=false
service_restarted=false
```

Do not commit.

### Task 13: Execute L2 Shadow and L3 Human Quality Gate Only After New Authorization

**Terminal update (2026-07-14):** the owner later granted three separate exact
DeepSeek Provider-call authorizations. The three earlier L2 shadows are terminal `blocked`;
the semantic-fix replacement blocked on `protected_entity_changed` after 9/9
successful translation responses, before semantic validation. Its permit and
attempt cannot be reused. The retained 54 pending rows are report-level cascade
evidence, not 54 independent entity failures. The local post-block repair at
release `861a88d8...a5f54`, exact packet `13f576a3...80a5`, was then explicitly
authorized and executed once. Nine translation responses succeeded, but four
items were blocked and 50 remained pending; read-only diagnosis later showed
the generic row reason was not four item-specific entity failures: all four
have number categories and only two also have model categories. Semantic
validation did not run. Its blocked manifest is `6f3ecb2b...2da4d`,
terminal evidence is `106c2904...eb784`, and cumulative budget is 27/100 with
73 remaining. L3 was not run. A later local protected-placeholder candidate is
bound to packet `7f76571b...3002` and was approved once, but stopped before
Provider transport with `runtime_env_required_value_missing`. Replacement
packet `f1f9b99d...ce066` then received exact owner approval and was executed
once. It also stopped before Provider transport with
`runtime_env_required_name_missing` while materializing the dynamic env names
that the immutable runner overwrites. Attempt
`attempt-20260714T133104260742Z-d970fb46d50debfe` is pre-Provider only;
both replacement permits are terminal `blocked`, gates are all-off, and no
fourth Provider request occurred.

**Artifacts:** a sanitized pre-call fixture may use repo-ignored
`tmp/translation-quality/<review_id>/`; the real L2 shadow DB, env, permit,
control journal and outputs must use one repo-external mode-700 shadow root.
Never commit real source, translation, username, personal link or review data.

- [ ] **Step 1: Freeze a sanitized 40-segment review set**

Use at least 10 titles, 10 bodies and 20 comments covering slang,
abbreviations, negation, comparison, numbers, units, emoji, brands and models.
Copy the production DB before shadow; use the copy read-only. Record source
inventory hashes after removing usernames, personal links and unnecessary PII.

- [ ] **Step 2: Provision/select secret material only under separate authority**

If a reviewed mode-600 key file is not already present, stop and obtain explicit
secret-provisioning authority. First run the verified `init-shadow-root` to
freeze the non-secret root descriptor; this grants no key read/Provider call.
Use
`server_update_daily_report_runtime_env.sh install-key --shadow-root ...` or an
approved secret manager with no-echo/stdin input and the atomic file contract
from Task 11. Use `install-env --shadow-root ...` separately for the isolated
shadow env with all Provider, report-send and failure-alert gates forced off,
then run redacted shadow `--check`. Neither operation may open or mutate the
production report env/key/control/state/output paths.

If using the repo updater, the authority names exact release/manifest and
updater-entry SHAs. Before reading stdin, independently verify manifest SHA and
the immutable updater's regular/non-symlink/owner/mode/hash with host
`lstat`/`sha256sum`, then execute that exact path. If using an approved secret
manager, record its separate approval/evidence and do not execute the updater.

Secret provisioning itself does not authorize reading the installed key,
calling DeepSeek or sending anything. Do not pass values through argv, process
env, stdout, logs or task memory.

- [ ] **Step 3: Obtain and record explicit L2 authorization**

Authorization must name a path-safe authorization ID, exact natural-day
`run_id`, reviewed candidate/release SHA, copied-DB SHA, canonical isolated
roots, maximum 100 DeepSeek attempts, one shadow report, key-read authority, no
live send and no production writes. Install the exact immutable
`report-shadow-permit-v1` in the isolated control root before any key metadata
read; installation is not reservation or Provider authority. Without it,
stop with:

```text
ready_for_owner_authorization
translation_provider_attempt_made=false
live_send=false
production unchanged
```

- [ ] **Step 4: Run one isolated shadow candidate**

Use a copied DB, independent public/private/state/blocked/output roots and live
DeepSeek gates. Keep DingTalk gates off. Do not recollect, overwrite production
attachments, update production current/projections or touch production DB.
Explicitly force and verify
`REDDIT_VOC_ENABLE_REPORT_FAILURE_ALERT=0` and omit
`--authorize-failure-alert`, so a blocked shadow cannot send an alert.
Enable the two DeepSeek gates only for this one command, pass the authorization
ID, and restore all gates off in a `finally` path for success, block, timeout or
process error. Concretely, under the isolated shadow lock the verified runner:
verifies candidate/updater; runs `recover-gates --shadow-root`; completes local
preflight; validates then durably reserves the exact unused shadow permit; runs
`set-gates --shadow-root` with DeepSeek on and all DingTalk/alert gates off;
performs the permitted key check/read and one action with its exact attempt
sink; calls `restore-gates --shadow-root` in `finally`; and writes a terminal
permit state before releasing the lock. It never calls the fixed production
gate path and does not edit or source env with ad-hoc shell commands. A crash
after reservation makes the shadow permit terminal/unknown, never reusable.

Expected evidence after an actual attempt:

```text
provider_call=true
translation_provider_call=true
translation_provider_attempt_made=true
live_send=false
production unchanged
```

Capture manifest/output/attempt hashes, request/retry/usage counts, actual model,
finish reasons, cache fields and all quality reason codes. Never capture secret
values or Authorization headers.

- [ ] **Step 5: Apply automatic quality acceptance**

Require:

- field mapping completeness 100%;
- protected entity/number preservation 100%;
- no source-equal output outside reviewed allow patterns;
- zero missing, duplicate, unknown or misaligned IDs;
- every semantic verdict has five true values and no critical error code.

Any failure blocks L3/production switching.

- [ ] **Step 6: Run blind human review**

For each sample record four fields: fidelity, terminology, Chinese readability
and critical error. Require no meaning reversal, sentiment reversal, omitted
negation or hallucination; at least 90% samples pass fidelity, terminology and
readability; any critical error blocks.

- [ ] **Step 7: Record owner L3 decision**

The owner approves or rejects exact shadow bundle/report hashes. Approval does
not authorize L4, L5 or L6. A rejection returns to the relevant local task with
new tests and a new candidate digest; do not mutate the reviewed candidate.

**Runtime-fix replacement terminal update (2026-07-14):** the owner explicitly
approved replacement packet `f1f9b99d...ce066` with its full Request ID and
remaining cap 73. A fresh shadow, copied DB, all-off env, exact permits and
mode-600 key metadata were verified. The single runner invocation stopped
before Provider transport with `runtime_env_required_name_missing` while the
immutable materializer attempted to replace dynamic env names omitted by the
template. Attempt `attempt-20260714T133104260742Z-d970fb46d50debfe` has
`translation_provider_attempt_made=false`; both permits are terminal
`blocked`, gates are restored all-off, runtime is cleaned, DB is unchanged and
no Provider process or output exists. This packet cannot be retried. A new
template/packet and fresh exact owner authorization are required; no L3/L4/L5/
send/deploy/cron/service/Git action is inferred.

**Full-field replacement completion update (2026-07-14):** the owner then
approved the new full-field packet and its one shadow completed with 9
translation plus 9 semantic-validation requests, 0 retries, and 54/54
accepted items. All five semantic verdicts were true and critical errors were
zero. The prepared bundle/outbox hashes are
`e1ce1bd1...f1a68f` / `0d0a6d05...ae338`; `report_live_send=false`,
`current_advanced=false`, permits are consumed, gates are restored all-off,
and cumulative use is 45/100. Sanitized evidence SHA is
`0befd35b3fe6147a7436c39f9f5897a95863525258ec119c24aac9786f60acc6`.
This closes L2 automatic gates only; L3/L4/L5 remain separately authorized.

### Task 14: Roll Out Through L4-L7 With Separate Authorization at Each Layer

**Authorization boundary:** Stop before every numbered layer below and request
the exact authority named there. Do not infer later-layer approval from an
earlier approval.

- [ ] **S1: Provision host report secrets under separate authority when needed**

This authority covers only atomic `install-env`/`install-key` to the two fixed
host paths and redacted `--check`. All DeepSeek, DingTalk report-send and
failure-alert gates remain off. It does not authorize reading the key, Provider
calls, live sends, release activation or any other backend change.
It names the reviewed release/manifest SHA. Before touching a secret, use host
`lstat`/`sha256sum` to verify the updater is the exact regular/non-symlink,
owner/mode/hash `role=admin` entry from that immutable candidate; execute no
workspace or base-image fallback copy.

- [ ] **L4: Narrow runtime release authorization**

Required authority: host file writes, atomic fixed-launcher/current replacement
and creation of `reddit_voc_report_net` for the exact release SHA plus exact
owner-approved new-launcher SHA; no key read, Provider call or live send.
Install the exact unused `report-admin-permit-v1` with
`action=bootstrap|activate` matching this operation before the first stateful
admin change.

Execute:

1. capture L4 before snapshot;
2. verify uploaded exact bytes against the release manifest/SHA and rerun shell
   syntax, fixture/mock tests and `report_runtime_smoke.py` with network/key/
   send disabled; bind this evidence to the release SHA;
3. run admin `preflight` with expected release, image, old-launcher and
   new-launcher hashes;
4. run `recover-gates`, then use the verified updater `set-gates
   --terminal-kill-switch` to force all Provider/report-send/failure-alert gates
   off and verify no key check/mount;
5. freeze and verify no active report job twice;
6. run gated `bootstrap` or `activate`;
7. run no-provider/no-send smoke;
8. capture/compare L4 after snapshot;
9. remove freeze only after the comparison passes.

Allowed changes are only fixed report launcher SHA, report release `current`,
the empty dedicated report network and the exact sanitized terminal L4
gate/bootstrap control records (zero active journal/snapshot/permit).
Cron/Nginx/main site/LibreTranslate/
collector/backfill/shared networks/DB/prepared state remain unchanged.

Expected boundary:

```text
release_layer=L4
provider_call=false
translation_provider_attempt_made=false
live_send=false
production_report_mode=disabled
cron_changed=false
service_restarted=false
```

- [ ] **L5: One production prepare authorization**

Required authority: one DeepSeek candidate for the named natural-day `run_id`,
exact release SHA and 100-attempt cap; no DingTalk send.

Install the exact `report-prepare-permit-v1`. Under the host lock, atomically
use this exact order: verify immutable release/updater and lock FD; run
`recover-gates`; complete all host/local preflight available without key;
validate the exact unused permit/release/run/expiry/cap; durably reserve it;
use `set-gates` to turn on only the two DeepSeek gates with both DingTalk/alert
gates off; perform phase key metadata/mount checks; run one defer-host-commit
prepare with its authorization ID and exact attempt sink; remove/inspect the
container; call `restore-gates` in `finally` and verify all five gates off; then
invoke host `commit-prepared` with the exact returned tuple/request SHA; finally
write the permit terminal state and run noninterference compare. The first
possible Provider attempt consumes the reservation, and every HTTP attempt
reserves a budget token before transport. Preflight/no-attempt failure closes
it as `closed_no_attempt`; commit failure closes it as terminal blocked/unknown
without advancing current. No live gate is enabled before exact permit
validation/reservation.
Force `REDDIT_VOC_ENABLE_REPORT_FAILURE_ALERT=0` and omit
`--authorize-failure-alert`.
Verify actual model, both-stage manifests, quality gates, immutable public/
private bundle, current pointer, top-level projections and all artifact HEADs.
Run L5 noninterference comparison; only new report bundle/current/projections
and commit-registry state plus that authorization's exact terminal
permit/gate/attempt/audit records may change. No active gate journal/snapshot/
permit may remain.

Expected boundary after an actual request:

```text
release_layer=L5
translation_provider_call=true
translation_provider_attempt_made=true
live_send=false
production unchanged_except_approved_prepared_report_state
```

Do not label the report delivered.

- [ ] **L6: One prepared-outbox live-send authorization**

Required authority: exact `run_id`, `artifact_version_id`, `bundle_sha256` and
`outbox_sha256` plus an authorization ID and expiry. Install the exact
`report-send-permit-v1` under the host lock. Run only
`send-prepared-daily-report`; do not prepare again.

Under the same lock use this exact order: verify immutable release/updater and
lock FD; run `recover-gates`; verify current/bundle/outbox and same-run local
ledger/DB duplicate evidence; validate the exact unused permit tuple/action/
expiry; use `set-gates` to enable only the two DingTalk report-send gates with
Provider/alert gates off; perform phase webhook metadata/mount checks; durably
consume the permit before the first `attempting` event; run the single
send/resend action; call `restore-gates` and verify all gates off in `finally`;
write terminal permit/audit state; then run noninterference compare. No live
gate is enabled before exact permit validation. Direct env edits are forbidden.

Verify every artifact HEAD before DingTalk, durable `attempting` before each
part, exact sent bytes/hash, parsed business `errcode=0`, durable `sent` and one
strict DB record per successful part; rejected/unknown parts get zero rows.
Verify row IDs, message hashes and counts against each part. Run L6
noninterference compare; only the exact run ledger, successful delivery rows
and that authorization's terminal permit/gate/audit records may change. HTTP
200 alone is not success.
If state becomes unknown, write an incident and perform manual reconciliation;
that part is never resent. Only a ledger-proven rejected part may receive a new
`action=resend` permit naming the exact part indexes and tuple.

- [ ] **L7: Observe three natural 07:00/08:00 cycles**

Monitoring authority alone is insufficient. Before this layer, obtain either
separate L5+L6 authority for each cycle or one time-bounded
`report-schedule-permit-v1` authorization naming:

- exact release and fixed-launcher SHAs;
- exactly three Beijing dates/run IDs;
- at most 100 DeepSeek attempts per date;
- whether each date authorizes same-lock report live send;
- report/alert gates, with failure alert fixed off;
- start/expiry, authorization ID and immediate kill-switch conditions.

Install the permit atomically under the host lock. Before reading key metadata,
constructing the client or any Provider attempt on each date, validate the
permit/release/date/unused status and the three side-effect gates. Missing,
expired, mismatched or consumed permit means no Provider call and no send.

After prepare, the still-held lock binds the exact new artifact version, bundle
and outbox hashes to that date's permit, and the launcher passes them explicitly
to send. Persist per-date authorization/attempt/terminal state. Any quality,
noninterference, unknown-delivery or container/network anomaly atomically turns
all Provider/report/alert gates off through the updater's recovered all-off
transaction, disables the remaining permit dates and stops the sequence. Every
date starts with `recover-gates` and exact unused-date permit validation. It
uses one prepare gate transaction (`set-gates` DeepSeek-only, action,
`restore-gates` in `finally`), verifies all-off, performs the neutral host
commit, removes/verifies the prepare container and report network, and runs a
full L5-equivalent prepare-phase noninterference capture/compare. Only a PASS
may proceed. Then—only if that date separately authorizes send—revalidate the
same-lock bound candidate/send scope and use a second send-only gate transaction
(`set-gates`, consume/send, `restore-gates` in `finally`). Prepare-phase compare
failure immediately keeps `live_send=false`, runs the terminal all-off path,
disables remaining dates and stops. Gates are all-off between phases and before
the date permit becomes terminal; a date with no send has no second transaction.

For each of three separate natural cycles, retain and compare:

- 07:00 collection run/fingerprint;
- 08:00 prepare source/translation/validator/report fingerprints;
- prepared bundle/index/pointer/projection hashes;
- outbox/ledger/business response evidence;
- collector/main-site/LibreTranslate/network/DB noninterference evidence.

Only after three passing cycles may the owner accept long-term scheduling as
stable. After the third terminal cycle, atomically restore all gates off and
disable/archive the schedule permit under the lock. Cron content is never
changed or reloaded. A single successful L6 send is not production acceptance.

---

## Definition of Done

- [ ] Tasks 1-12 pass on a clean, serial L1 run with no real Provider or send.
- [ ] There are no open P0/P1 review findings.
- [ ] Source filtering precedes Provider input and all caps are fail-closed.
- [ ] Chinese-first DingTalk and exact full-source attachments round-trip.
- [ ] Translation and semantic validator results bind through independent keys
      and output digests.
- [ ] Prepared bundles, current pointer, projections and blocked attempts meet
      path/mode/hash/atomicity contracts.
- [ ] Send proves exact bytes, artifact availability, ledger chain and duplicate
      admission without importing Provider/render code.
- [ ] Runtime tests prove dedicated network/resource/mount/secret/lock
      isolation and no shared-backend actions.
- [x] L2 was separately authorized and executed; the latest full-field shadow
      passed automatic gates, while earlier packets remain terminal `blocked`.
- [ ] L3/L4/L5/L6/L7 remain unexecuted until separately authorized.
- [ ] README/context pack match the implemented and verified evidence layer.

## Execution Handoff

After the owner separately authorizes implementation, choose one:

1. **Subagent-Driven (recommended):** use
   `superpowers:subagent-driven-development` in this task, one plan task per
   worker, with specification review then code-quality review and serial shared
   test gates.
2. **Inline Execution:** use `superpowers:executing-plans` in this task and
   execute Tasks 1-12 sequentially with review checkpoints.

Both options stop after L1. Tasks 13-14 always require their own explicit
authorizations.
