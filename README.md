---
title: Reddit VOC Local Operator README
doc_type: runbook
status: active
created: 2026-07-07
updated: 2026-08-23
owner: codex
project: Reddit_VOC
production_boundary: authorized_live_operational_partial
provider_call: true
live_send: true
---

# Reddit VOC Local Operator README

## 当前状态入口（2026-08-23）

当前产品状态、能力图谱、生产/本地证据边界、已知阻断和继续执行顺序统一见
[`PROJECT_STATUS.md`](PROJECT_STATUS.md)。该文档取代本 README 下方各历史章节中的
“当前 release”“当前 Owner 决策”“第二 Webhook 尚未实现”等时点性结论；下方内容继续
保留为 2026-07 的设计与操作历史，不能单独作为当前生产执行依据。

截至该交接状态：daily report current 已激活到
`7b177962...c181`，2026-08-22 双机器人补推已有两个 destination terminal `sent` 和
生产 DB 两行投影证据；2026-08-23 自然 08:00 周期已实证在 reservation 前因 annual
parent authority 文件缺失而 fail-closed。parent-only 修复仅为本地冻结候选，尚未生产安装。公开
洞察站仍运行 2026-08-10 的 site/data release，与日报 runtime 是两条独立 current 链，
日报补推不会自动刷新站点日期。

剩余 High 风险的唯一执行计划为
[`docs/superpowers/plans/2026-08-23-reddit-voc-remaining-high-risk-closure.md`](docs/superpowers/plans/2026-08-23-reddit-voc-remaining-high-risk-closure.md)。截至 15:35 BJT，G6R6-R1 parent-only 与 H1-R3
公开翻译都只完成 fresh production read-only preflight 和 exact authorization proposal；未发生
parent 安装或 DeepSeek 调用。16:05 BJT 再次复核的 18 个 production/H1 绑定点全部未漂移；
16:09 BJT fresh 只读回读进一步确认公网 data pointer 与生产
data current SHA 相同，但仍是 `data_as_of_utc=2026-08-08T23:00:00Z`、freshness=`partial`；旧日期
不是浏览器缓存，必须走独立 data candidate/current CAS。TikHub comments route/query 已与当前官方合同
逐项一致，区域域名 `.dev` 对照探针仍待精确授权。Data volume 的 `df -P` 已为 100%、available
`4078256 KiB`；四个 exact 可重建缓存目录预计仅回收 `757552 KiB`，expanded proposal 已冻结但实际
删除仍为 0，不能据此把容量风险表述为关闭。

## GitHub 与生产版本

GitHub 仓库为 `https://github.com/zjgulai/Reddit_VOC`，默认分支为 `main`。
三端版本身份、生产只读校验和后续发布顺序见
[`docs/workflows/version-consistency.md`](docs/workflows/version-consistency.md)。已提交基线
`HEAD=origin/main=15b286a2...e7` 对应 GitHub CI green，但当前 dirty 日报源码会重建为
`750cfe17...82f`，不再等于生产锁定 `7b177962...c181`；必须经 successor release、生产
postflight、version-lock 更新和 clean Git push 后才能恢复三端一致。该 successor 已完成两次
确定性构建、21-module import closure 和 56 runtime tests；正式 backend CI 口径仍只有
`daily_source_release_mismatch` 一项失败，因此它是 L2 候选，不是已部署版本。公开站只锁定旧生产
制品 manifest，尚不能把当前较新的 UI 源码表述为该旧 dist 的逐字节来源。

## Reddit VOC 洞察站部署

`ref/UI/momcozy-reddit-workbench` 的真实化、案例增量、隔离容器、腾讯云部署、
E2E 与回滚门禁统一记录在
`docs/superpowers/plans/2026-07-15-reddit-voc-insights-site-deploy.md`。
当前生产已部署到 `https://reddit.lute-tlz-dddd.top/`，release 为
`627fbab6622d73326386b57010e852a10c3d2133e2e47d941246767b2478bed4`，
pointer 为 `reddit_voc_release_20260716_v3_818f7eae7627_ui2`；公开访问不启用登录，
上一生产 release `ea15b3ef...efc1` 保留为精确回滚目标。
后续修改洞察站、部署配置或接入增量数据前必须先读取该计划；新数据必须生成独立不可变
release 并通过同一投影、隐私、回滚和公网 E2E 门禁，不能直接修改线上静态文件。

2026-07-16 19:56:43（Asia/Shanghai）完成了最新洞察站受控提升。精确授权绑定
promotion packet `ace4553d7007703e081a4a0a4a654417d332368661b357d972d1e16891de4f6e`；
生产状态为 `passed_public_production_acceptance`：26/26 桌面/移动页面、三种报告周期、
13 条公网路由、8 个公开制品、20 条安全 404 与案例 33/17/1 均通过。当前数据为
3,494 个去重帖子、27,158 条存量评论，其中 20,205 条已关联、6,943 条待父帖关联、
10 条隔离。L4 验收回执位于
`output/reddit-voc-production-acceptance/627fbab6622d73326386b57010e852a10c3d2133e2e47d941246767b2478bed4/acceptance-receipt.json`。

2026-07-16 20:31:09（Asia/Shanghai）又对同一生产 release 完成 CSV、PDF、PPTX、DOCX
四格式真实下载与内容级只读验收，浏览器错误、同源 HTTP 失败和外部请求均为 0；回执位于
`tmp/reddit-voc-production-export-acceptance/627fbab6622d73326386b57010e852a10c3d2133e2e47d941246767b2478bed4-a3/acceptance-receipt.json`。
这份回执不修改原 L4 回执，也不改变生产 current。增量 candidate registry 与自动化接入
继续作为上线后开发项；6,943 条待关联评论是关系债务，不是历史采集缺失。同一生产
release 的 `release.json` 与 `current-release.json` 又通过两次间隔观测，字节稳定且均处于
terminal/quiescent；只读 monitor 回执 SHA-256 为
`8ab8dee2d853f420c64c1d4d23d6bf45a6d3b2c66d78b14b19c1a76a0020ad88`，没有执行远端写入或安装调度。

以下 2026-07-15 内容保留为历史提升记录。自动化与生产提升的单一执行计划是
`docs/superpowers/plans/2026-07-15-reddit-voc-incremental-activation.md`；管理层影响报告是
`output/reddit-voc-incremental-impact-20260715/report.html`。以下为 RC3 历史提升记录：其授权绑定
`tmp/reddit-voc-incremental-candidate-20260715/promotion-packet-rc3.json`，packet SHA-256
为 `7d429a8354be451b90f04e7609845e4b49a350256d7c48ee5cfd5b64eda64f11`；该包同时绑定
freeze、候选 gate、独立浏览器 E2E、release manifest、TGZ 和 image tar，不能只凭 release
名称执行切换。生产验收回执为
`tmp/reddit-voc-incremental-candidate-20260715/production-acceptance-receipt-rc3.json`；
当时自动候选链尚未实现、未启用；当前生产状态以本节上方的 2026-07-16 release 和回执为准。

## 2026-07-15 RC3 全源身份与增量封账

最初网站的 221 个唯一帖子只是一条历史基线，不能再把某个 daily SQLite 的少量后续
帖子表述为完整净新增。RC3 把网站、`ai_nlp_voc` 导入归档、Task 37、腾讯云生产快照、
V2 语义搜索和 task2600–2603 报告文件按 Reddit ID 交叉去重后，当前有界
`global_known=1,340`，相对 221 基线净新增 **1,119**。身份集合为
`semantic=1,156`、`materialized=369`、`discovery_only=883`、`remote_union=1,252`。
RC3 Base 已激活 1,322 个帖子，剩余 18 个 lineage gap 继续隔离。

相对提升前的生产 V2，task2600–2603 真实净新增为 23 个帖子和 139 条已关联评论，
而不是早期水位中的 `+13` 或其他局部数字。RC3 历史水位为 1,322 帖、12,986 stored
comments、12,976 linked comments 和 10 quarantine；当前生产新版本为 1,322 帖、
16,591 stored comments、16,581 linked comments 和 10 quarantine。该增量仍有 7 个片段级 reply
cursor debt；全候选债务是 348 partial threads、367 cursors、339 page continuations
和 18 lineage gaps，两者不得混用。

当前冻结与复算入口：

- `tmp/reddit-v2-identity-freeze-20260715-incremental1.json`
- `tmp/reddit-v2-raw-snapshot-20260715-incremental1.json`
- `tmp/reddit-voc-incremental-input-freeze-20260715-3.json`
- `output/reddit-voc-incremental-impact-20260715/impact-summary.json`

`docs/analysis/reddit-net-new-inventory-20260715/` 保留为更早水位的历史盘点，不再作为
RC3 当前数字的单一事实源。

该封账是 current bounded lower bound，不是 Reddit 全量穷尽证明。当前生产明确为
`latest_collection_integrated=true`、`latest_collection_fully_hydrated=false`、
`completion_claim_supported=false`。本次提升仅替换洞察站容器；`provider_call=false`、
`database_write=false`、`collector_restart=false`、`schedule_change=false`，采集器、cron、
共享 Nginx、TLS、DNS 和其他 Docker 项目未修改。

## Scope

This project is a local implementation for Momcozy Reddit VOC monitoring. It currently supports fixture-safe collection, browser `.json` smoke ingestion, TikHub Reddit provider wiring, 07:00 Beijing-time rolling 24-hour collection, structured JSONL/CSV export, a single-page Chinese HTML insight report with the detail table at the bottom, auxiliary CSV/XLSX detail exports, Chinese insight PNG generation, local rule analysis, DingTalk Markdown dry-run payload generation, gated DingTalk live send, and local operation checks.

## Boundaries

- Provider calls require `REDDIT_VOC_ENABLE_TIKHUB=1`, `TIKHUB_API_KEY`, and `--authorize-provider-call`.
- Machine translation calls require `REDDIT_VOC_TRANSLATION_MODE=libretranslate` and a runtime `LIBRETRANSLATE_BASE_URL`; optional `LIBRETRANSLATE_API_KEY` must stay outside the repo.
- DingTalk live sends require `REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND=1`, `DINGTALK_WEBHOOK_URL`, and `--authorize-live-send`.
- 洞察站 release `627fbab6...2478bed4` 已受控上线；采集/报告生产链和其他 Docker 项目不属于本次修改范围。
- DingTalk live HTML report sends require `REDDIT_VOC_ARTIFACT_BASE_URL` so links are reachable from DingTalk.
- launchd install/load requires explicit authorization.

## Historical 2026-07-14 evidence personas and tag repair checkpoint

This section records the pre-V2 checkpoint; production and RC3 counts are stated
above and supersede its version/count claims. The approved Scheme A was implemented
locally. Four held-tag semantic predicates
processed 243 candidates as 20 confirmed, 92 needs-review and 131 rejected. All
four tags remain held (`0 promoted`) because the zero-overlap sample gates were
not met; the implementation did not lower thresholds or create an Insights/
reports v2.

`reddit_voc_personas_20260714_v1` contains two aggregate evidence cohorts and
109 content assignments. At that checkpoint, `/dashboard/insights` loaded these real cohort
metrics and two manifest-bound local SVG illustrations, visibly marked
`合成头像 · 非真实 Reddit 用户`. It does not expose author identifiers,
demographics, individual profiles or population-share claims. The existing
daily/weekly/monthly report UI and `reddit_voc_reports_20260714_v1` remain
unchanged.

Design and execution evidence:

- `docs/superpowers/specs/2026-07-14-reddit-voc-evidence-personas-design.md`
- `docs/superpowers/plans/2026-07-14-reddit-voc-evidence-personas.md`
- `docs/analysis/reddit-tag-repair-20260714/report.md`

The evidence-persona data generation remained local/static:
`dataset_provider_call=false`, `database_write=false`, `live_send=false` and
`webhook_send=false`. Its minimized immutable public projection is now deployed
as part of the production insights release above. The only provider call in the
site deployment was the authorized ACME certificate issuance
(`tls_acme_provider_call=true`); it did not recollect or rewrite Reddit data.

## DeepSeek 日报 prepared 工作流（L2 shadow 已 fail-closed）

日报新路径固定使用 `deepseek-v4-flash`，请求端点固定为
`https://api.deepseek.com/chat/completions`，关闭 thinking、关闭 stream、
`temperature=0` 并要求 JSON object。用户可见顺序固定为中文标题、中文正文、
中文评论、中文业务判断、确定性英文节选、Reddit 原帖链接；完整英文逐字保留在
HTML、CSV、XLSX 和 Reddit 链接中。新 prepared 路径不会在翻译失败时回退到
LibreTranslate、英文正文或旧报告发送。

执行被拆成两条互不重建的路径：

- `prepare-daily-report` 在一个 SQLite `mode=ro` 快照内完成可见性过滤、硬上限、
  DeepSeek 翻译、独立语义复核、结构/实体门禁和 immutable bundle staging。
  网络 prepare 使用 `--defer-host-commit`，不能直接修改 current pointer、投影或
  commit registry。
- `send-prepared-daily-report` 只校验并发送冻结的 UTF-8 bytes；不导入
  `deepseek_client`、`translation_pipeline` 或 renderer，不重新翻译、不重新渲染。
  附件 HEAD 遇到 3xx 不跟随，任一非 200 状态整份阻断。
- 旧 `build-daily-report`、`send-daily-report-live` 和 LibreTranslate 代码仍保留给
  owner 明确指定的回滚/兼容路径；`scripts/run_daily_report.sh` 的新
  `prepare|send|smoke` 分支不会调用这些旧命令。

真实 prepare 必须同时满足以下四类证据，缺一即 fail-closed：

- `REDDIT_VOC_TRANSLATION_MODE=deepseek`；
- `REDDIT_VOC_ENABLE_DEEPSEEK_TRANSLATION=1`；
- CLI `--authorize-provider-call` 与合法的 `--provider-authorization-id`；
- 通过 owner/type/mode/size 校验的独立 key 文件，以及逐次持久化的 attempt reservation。

业务报告还必须通过 `prepared-validation-v2` 的冻结 source-state 证明：`failed`、
未知状态和 `success/partial + 0 帖子` 在渲染与 provider 之前阻断；合法
`empty + 0 帖子/0 评论` 归类为 `empty_success`。send 会在 HEAD、凭据读取和
transport 之前重新只读同一 run，并与冻结状态全字段比较；状态或计数漂移时不发送。
缺少该证明的旧 `prepared-validation-v1` bundle 不再可发送。

真实 send 必须同时满足 `REDDIT_VOC_DINGTALK_MODE=live`、
`REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND=1`、CLI `--authorize-live-send` 和绑定
`run_id/artifact_version_id/bundle_sha256/outbox_sha256` 的独立 authorization。
失败告警另有 `REDDIT_VOC_ENABLE_REPORT_FAILURE_ALERT=1` 与
`--authorize-failure-alert` 双门禁；它不继承日报发送权限。常见阻断码包括
`translation_mode_not_deepseek`、`deepseek_translation_not_enabled`、
`provider_call_not_authorized`、`provider_authorization_id_required`、
`translation_pipeline_blocked`、`dingtalk_mode_not_live`、
`dingtalk_live_send_not_enabled`、`live_send_not_authorized`、
`artifact_preflight_blocked`、`blocked_duplicate` 和 `unknown_delivery_state`。
当前 owner 决策是“不推送钉钉”：固定 host launcher 的 `send` 分支无条件返回
`dingtalk_disabled_by_owner`，并固定输出 `report_live_send=false`、
`alert_live_send=false`、`live_send=false`。无参数 08:00 入口只能匹配唯一、未使用、
精确绑定 `release_sha256/run_id` 的一次性 `report-schedule-permit-v1`，且 action 固定为
`prepare_only`；它不会进入 send。

目标 host 隔离路径如下；这些路径是后续 L4 的设计目标，不代表已安装：

- report env：`/home/ubuntu/.reddit-voc/secrets/reddit-voc-report.env`；
- DeepSeek key：`/home/ubuntu/.reddit-voc/secrets/deepseek-api-key`；
- report lock/control：`/home/ubuntu/.reddit-voc/locks/daily-report.lock` 与
  `/home/ubuntu/.reddit-voc/report-control/`；
- immutable release：`/opt/reddit-voc-report/releases/<release_sha256>`，current
  pointer 为 `/opt/reddit-voc-report/current`；
- dedicated network：`reddit_voc_report_net`，不得加入主站、LibreTranslate、
  collector、backfill 或共享网络。

失败策略：翻译/语义/schema/模型/实体/预算/cache/bundle/附件任一门禁失败，整份
日报 blocked；发送前写 durable `attempting`，网络边界后无法确认结果时记录
`unknown_delivery_state`，不得自动重发。显式 resend 只允许授权中列出的、上一轮
明确 rejected 的剩余 part。回滚顺序必须先把五个 report gates 关到 all-off，
再处理 release/current/projection；不得 reload cron、重启其他服务、重新采集或自动
启用 LibreTranslate。

2026-07-14 新鲜本地证据：受保护值占位符修复的聚焦回归为 `62/62`；固定
Python 3.12 对 40 个 unittest 模块的独占串行验证为 `654/654`、0 failure、0 error，
唯一依赖 pytest 的模块由系统 Python 3.9 单独运行并通过 `3/3`。provider-free runtime
smoke 精确输出
`runtime_smoke=passed`、`translation_provider_call=false`、
`translation_provider_attempt_made=false`、`report_live_send=false`、
`live_send=false`、`database_write=local-test-only`。这些只证明本地 mock/fixture、
fake-host 和 provider-free 路径；测试中的 `live_send=true` 仅来自注入的 mock
transport，不是网络发送。

同日，owner 授权的 semantic-fix replacement L2 shadow 已终态 fail-closed。精确
request `deepseek-l2-semanticfix-replacement-20260714-175924` 使用 release
`eec615b6...e29d4` 与复制库 `b4151728...c92d7c`，实际完成 9/9 个
`deepseek-v4-flash` translation 响应、0 retry、17,711 tokens，但 blocked manifest
把 54/54 项统一记为 pending，并返回 report-level `protected_entity_changed`；semantic
validation 未启动，prepared report 未生成。后续本地审计已证明这不等于 54 项分别失败：
其中 22 项没有任何受保护值，实际只能确认至少一项触发了门禁。blocked manifest SHA
为 `3c20a6a9...0b8ca9`，脱敏终态证据为
`tmp/translation-quality/deepseek-l2-20260714-150456/semanticfix-terminal-evidence.json`
（SHA `871d3eb5...699945`）。两轮 L2 共消耗 18/100 次，剩余 82 次；任何新 repair
或 replacement 都必须使用新候选、新 permit 与新授权，禁止重跑已终态 attempt。

同日已完成下一轮本地 repair 候选。它聚合跨 bundle 的确定性失败，只把可归因项标成
`blocked`，其余保持无逐项错误码的 `pending`；blocked manifest 仍不保存 source/`zh`。
同时修复了 model pattern 大小写合同冲突：非规范 source 型号允许规范化大小写，但型号
身份变化仍 fail-closed。最终 release 为 `861a88d8...a5f54`，manifest
`193035f2...4174`，validation manifest `9f8f0961...0668`。owner 随后明确
授权新请求
`deepseek-l2-postblock-repair-20260714-193359` 的 packet SHA 为
`13f576a3...80a5`并执行了一次隔离 L2 shadow。9/9 个
`deepseek-v4-flash` translation 响应成功、0 retry、17,650 tokens，但确定性
门禁终态为 `4 blocked + 50 pending`。后续只读输入诊断纠正了类别解释：
`protected_entity_changed` 是复制到这 4 行的通用确定性失败原因；4 项都有数字类别，
其中只有 2 项另有型号类别。semantic validation 未启动，
prepared report/L3 包未生成。blocked manifest SHA 为 `6f3ecb2b...2da4d`，
脱敏终态证据为
`tmp/translation-quality/deepseek-l2-20260714-150456/postblock-repair-terminal-evidence.json`
（SHA `106c2904...eb784`）。三轮 L2 累计消耗 27/100，剩余 73。数字表面
格式假说仍未证实，该历史候选未放宽数字合同。

随后完成了新的本地 protected-placeholder 候选。Provider 输入中的每个最大受保护
span 会先替换为 collision-safe、按 occurrence 唯一的 opaque marker；响应必须逐个原样
返回且恰好一次，否则以 `protected_placeholder_changed` fail-closed。marker 在本地恢复为
原始 UTF-8 bytes 后，既有实体、数字和语义门禁继续严格执行。复制库上的 provider-free
回放覆盖 9 帖、9 bundles、54 items：32 items 使用 157 markers，零残留受保护值、零
namespace collision、逐字节 round-trip 一致，数据库 SHA 不变。新 immutable release 为
`bc51d736...340e4`，manifest 为 `e4edef8f...9d92`，validation manifest 为
`a6be9cc3...43f2`。精确请求
`deepseek-l2-protected-placeholder-repair-20260714-205534` 的 packet SHA 为
`7f76571b...3002`，已按 owner 批准执行一次，但在 Provider transport 前因
`runtime_env_required_value_missing` fail-closed；没有消耗新的 Provider attempt。
其两个 permit 已 terminal=`blocked`，gates all-off，runtime 已清理。

该失败定位为 packet runtime template 缺少数据库路径、HTTPS artifact base URL、
required keyword、字节上限和分片上限五个非 secret 基础字段。新的精确请求
`deepseek-l2-protected-placeholder-runtimefix-20260714-211414` 已获 owner 明确批准，
packet SHA 为 `f1f9b99d...ce066`，上限为 73 次。该 replacement shadow 已初始化并
只执行一次 runner，但在 Provider transport 前再次因
`runtime_env_required_name_missing` fail-closed：模板仍缺少 materializer 要覆盖的
run/attempt/artifact ID、report roots、provider-attempt root 与 config root 名称。
本次 attempt 为 `attempt-20260714T133104260742Z-d970fb46d50debfe`，没有消耗新的
Provider attempt；两个新 permit 已 terminal=`blocked`，gates all-off，materialized env
与 runner runtime 已清理，数据库 SHA 未变。runtime SHA 为 `b1a317c7...afee302`，
validation manifest 为 `e066dd14...54daa2`。

本地 host 候选已实现 immutable release/import closure、固定 launcher、精确容器
inspect、gate/permit crash recovery、`bootstrap|activate|rollback`、
`recover-prepared-state|commit-prepared|commit-blocked`、一次性 prepare-only schedule
permit，以及 `capture-host` 只读非干扰证据。`capture-host` 覆盖主站、
LibreTranslate、Nginx、三张网络、cron/Nginx/collector SHA、DB schema/inode/size/
mtime、prepared pointer/projections 和 control-plane 终态；公开证据不保存 secret、
env 非 gate bytes 或其摘要。

当前真实边界仍是 `host_release_ready=false`：最新 full-field replacement 已获明确
批准并完成一次 L2 shadow，9 translation + 9 semantic-validation requests 全部完成，
54/54 items accepted、五项 semantic verdict 全 true、critical errors=0、0 retry。
这是 L2 automatic-gate 结果，不是 L3 人工接受，也不是 L4 release-ready 或 L5
production prepare。隔离 key 仅经 stdin/no-log 路径安装/使用，内容未输出；两个 permit
已 terminal=`consumed`，gates all-off，gate journal=`restored`，runtime 已清理，
`provider_call=true`、`live_send=false`、`current_advanced=false`、数据库未变、
`production unchanged`。累计 DeepSeek 使用为 `45/100`，剩余 55；未执行生产
host capture/activate、Docker/network、cron/service 变更或 DingTalk。2026-07-15
曾按 owner 授权尝试一次 L4 report-only bootstrap，但在主机
`root:root` cron 所有权门禁 `cron_file_invalid` 处 fail-closed；current、旧
launcher、cron 与生产网络未变化，permit 已 terminal=`blocked`。随后已在本地完成
最小修复并通过 `30/30` report ops、`7/7` release/import、`130/130` 相关套件；新候选
release `d6c97382...cf5f61c`、manifest `ec215029...a21d5` 已上传并通过远端
manifest/import 验证，但精确 L4 bootstrap 在 report smoke 阶段因 launcher 将相对
`python3` 传给严格路径校验而 fail-closed。随后已恢复 `current=absent`、旧 launcher、
cron 和 report network；site app 未重启，permit 已 terminal=`blocked`。随后已完成 host
Python 绝对路径修复，目标测试和 import closure 均通过；新的精确 L4 bootstrap
`reddit-voc-l4-bootstrap-20260715-011053` 又在 report smoke 阶段因管理员持有
daily-report lock、launcher 无法复用已持有描述符而以 `lock_busy` fail-closed。已恢复
`current=absent`、旧 launcher、cron 与 report network；没有 Provider 或 DingTalk 调用。
随后已在本地修复 smoke 锁描述符传递与严格复核，目标测试 `46/46`、相关套件 `122/122`、
import closure `19` 且 `repository_fallback=false`。新候选 release
`3594a09e...72e8aa4`、manifest `227acfd5...edd370`、launcher `ed32f370...072424`
尚未上传远端。下一步需对新 SHA 重新取得精确授权，禁止重试此前 permit。

## Momcozy Historical Backfill (No Push)

The approved historical lane uses run ID
`backfill_momcozy_20250101_20260711` and the Beijing-time half-open window
`[2025-01-01 00:00:00, 2026-07-12 00:00:00)`, equivalent to
`[2024-12-31T16:00:00Z, 2026-07-11T16:00:00Z)`. Recall remains the reviewed
Momcozy brand/product/category keyword contract in `search_config.py` and
`keywords.py`.

Reviewed local contracts:

- `config/backfill/momcozy-seed-baseline-20250101-20260711.json`
  (`SHA-256 ec3fd0aac2ba32b89348a4f98935bc1a851d9250e39304285107f671c1944abc`)
- `config/backfill/momcozy-comment-cursor-contract-20260711.json`
  (`SHA-256 f5dc8d698a4f38bfb6f49bbe4fb220ef67c8f811393576a407308921f0a997fd`)
- `config/backfill/momcozy-backfill-release-manifest-20260711.json`
  (Task 18 candidate later executed by Task 19, SHA-256
  `c6d289329443a92ed59c5849fa9fbfe15afc854df709497351c1b7003fd9b2dc`;
  current Task 21R locally verified candidate SHA-256
  `88f3d58c89980ed0c685796c340c6752c11f5394e61409f6beeb8a4303b3938f`;
  prior Task 20 / Task 21 executed SHA-256
  `347c6ede1fe36852509dffe051fa7bf2b4d0c1e24ead8dda1af085bc44ff9d94`;
  historical Task 16 / Task 17 executed candidate SHA-256
  `0663168b890cbd858068548eb3b43ee70345e01854090f42ae0baf91ac9fe0ba`;
  historical Task 14A transferred candidate SHA-256
  `ec5548c6606e587ae8d9d18809ae643553a03306a44ef2371867a64659a52253`;
  historical Task 13/14 executed bundle SHA-256
  `471dc848cdadff544a8e7009e044ca2cdba03e2add81f741d0d37b4dd0fb949e`)

The independently checked seed contract is `55` source files: `48` imported,
`7` outside the window, no exclusion/duplicate/parse error; `48` threads,
`1,894` comments, `1,942` local analyses; coverage `45 full / 3 partial /
0 post_only`. The source-inventory SHA is
`af39a40c8ed657f440f9db6595d5f4e8e4a26164f43ffa78373215b40b3e881b`;
the exactly-three partial-post-ID SHA is
`1664b77cb94992959a0dc638d25580aad41aa65e8665462490c78d5220532769`.

Commands are isolated under `python -m reddit_voc.backfill_cli` and
`scripts/run_historical_backfill.sh`; server phases use
`scripts/server_historical_backfill.sh` with a fresh digest-pinned container.
Provider phases require all four gates: the CLI authorization flag,
`REDDIT_VOC_BACKFILL_AUTHORIZE_PROVIDER_CALL=1`,
`REDDIT_VOC_ENABLE_TIKHUB=1`, and a runtime-only `TIKHUB_API_KEY`. Production
merge has a separate owner gate and is not part of the current authorization.
See `docs/superpowers/plans/2026-07-11-momcozy-reddit-historical-backfill.md`
for the exact seed/probe/collect/replay/reindex/validate/merge-plan commands and
their separate authorization gates.

Current historical-lane boundary:

```text
staging_only
production unchanged
provider_call=true
actor_run=false
provider_attempt_made=true
provider_request_count=670
live_send=false
Task13_status=complete
Task14_status=partial
Task14_acceptance=false
task16_local_replay_repair_status=reviewed
task16_candidate_manifest_sha256=0663168b890cbd858068548eb3b43ee70345e01854090f42ae0baf91ac9fe0ba
task16_remote_transfer_executed=true
task17_remote_replay_status=failed
task17_remote_replay_stop_reason=discovery_checkpoint_mismatch
task17_replay_attempt_count=1
task17_checkpoint_only_lanes=29
task18_local_replay_repair_status=reviewed
task18_candidate_manifest_sha256=c6d289329443a92ed59c5849fa9fbfe15afc854df709497351c1b7003fd9b2dc
task19_remote_transfer=true
task19_remote_replay_status=complete
task19_remote_replay_stop_reason=replay_complete
task19_fingerprints_equivalent=true
task19_replay_database_published=true
task19_replay_database_sha256=3504190ab2b80ad1a003da27574455802f4184499eeaa7d458a6b771c3a8c638
task20_local_verification=passed
task20_provider_call=false
task20_manifest_sha256=347c6ede1fe36852509dffe051fa7bf2b4d0c1e24ead8dda1af085bc44ff9d94
task21_authorization_consumed=true
task21_remote_transfer=true
task21_remote_reindex_status=failed
task21_remote_reindex_stop_reason=strict_discovery_schema_unknown
task21_reindex_attempt_count=1
task21_target_database_published=false
task21_boundary_postflight_passed=true
task21r_local_repair_status=local_verified
task21r_candidate_manifest_sha256=88f3d58c89980ed0c685796c340c6752c11f5394e61409f6beeb8a4303b3938f
task21r_reindex_tests=26/26
task21r_full_suite=452/452
task21r_real_corpus_gate_executed=false
task21r_independent_review=false
second_remote_reindex_authorized=false
Task22_authorized=false
historical_task14a_remote_replay_status=failed
historical_task14a_remote_replay_stop_reason=discovery_occurrence_mismatch
Task15_authorized=false
external_sync_observed_historical=true
```

Task 12 local seed/replay/validation is complete: the staging DB contains
`48` threads, `1,894` comments and `1,942` analyses, with acceptance `27/27`
and a stable 58-file run-root inventory SHA-256 of
`4149f5663936fca0cab78f28140d9f94af76a36c408c7cb3d86ea557eb6bd12d`.
BaiduNetdisk synchronization was observed and paused; 48 generated upload
sidecars were explicitly removed before the stable snapshot was revalidated.
Task 13 then transferred only the reviewed bundle and staging snapshot and ran
a real TikHub contract probe: 2/4 authorized attempts succeeded, two pages
committed, 9 unique candidates were discovered, and the report is `ready` with
SHA-256 `75abc643a745ac0a63c2e65d7c0bcda4167981594980b2c664448a1bb206e2bc`.
Task 14 option B was then explicitly authorized and executed to the cumulative
hard cap: all `670` attempts succeeded, but all budget was consumed by 670
pages of the first dynamic lane. The collect report is `partial` with
`budget_exhausted`; the other 29 lanes have zero pages and 238 candidates are
`budget_deferred`. Offline replay failed closed with
`discovery_occurrence_mismatch`, so no replay DB or acceptance report was
published and merge-plan was not run. See
`.superpowers/sdd/task-14-report.md` for the exact evidence. Production
DB/container remained byte/state unchanged and `live_send=false`. Production
merge, DingTalk, deploy and Git push remain prohibited; Task 15 is unauthorized.
The next authorized local-only step repaired the collect/replay invalid-row
contract and passed Python 3.11 backfill `261/261`, workspace full-suite
`344/344`, and independent review `APPROVED`. The repaired candidate manifest
SHA is `ec5548c6606e587ae8d9d18809ae643553a03306a44ef2371867a64659a52253`.
It was later transferred to a new manifest-SHA-versioned remote directory and
used for one authorized `--network none` staging replay. Replay still failed
closed with `discovery_occurrence_mismatch`; a read-only diagnostic proved the
ordinal-level observation where raw parsing yields a post ID but the source
occurrence stores null identity/time fields; Task 16 later superseded the
initial "second persistence shape" interpretation. No replay
DB, acceptance report or merge plan was published; Provider requests remained
unchanged and production stayed unchanged. See
`.superpowers/sdd/task-14a-remote-replay-report.md`.

Task 16 corrected the local root-cause model: collection archived canonical
`sort_keys=True` JSON but parsed the pre-serialization dictionary, while replay
parsed the canonical archive. Dictionary traversal could therefore exchange
discovery ordinals without changing the exact page multiset. Collection now
parses the archived bytes, and replay performs a strict page-level multiset
check before reconstructing the frozen source order. Tampered identity,
ordinal, artifact and capture-time cases still fail closed. Python 3.11
backfill passed `263/263`; the isolated full suite passed `346/346`; the Task 16
manifest was `22/22` exact with SHA-256
`0663168b890cbd858068548eb3b43ee70345e01854090f42ae0baf91ac9fe0ba`.
That repair remains valid local L2 evidence. Task 17 then installed its exact
23-file bundle in a new SHA-versioned directory and ran exactly one authorized
`--network none` replay. The occurrence contract passed, but replay failed
closed at `discovery_checkpoint_mismatch`: the source has 30 discovery
checkpoint lanes while only the first lane has artifacts; the other 29 are
legitimate zero-page `partial/budget_exhausted` checkpoints. No replay DB was
published. Source DB/raw archive, Provider count, production DB/container and
delivery state were unchanged. See
`.superpowers/sdd/task-17-remote-replay-report.md`.

Task 18 replaces the invalid checkpoint/artifact set-equality assumption with
an exact checkpoint-only exception for configured, page-zero, fully empty
cursor/time/count state that ended `partial/budget_exhausted` only after the
manifest request budget was exhausted. It copies the historical checkpoint
without inventing an artifact. Artifact-only, unconfigured, positive-page,
non-partial, not-yet-exhausted and field/type-tampered states remain
fail-closed. Focused tests passed `5/5`, `tests.test_backfill_validation`
passed `56/56`, and the offline isolated full suite passed `351/351`; two
independent read-only reviews returned `APPROVED`. The new exact `22/22`
manifest SHA is
`c6d289329443a92ed59c5849fa9fbfe15afc854df709497351c1b7003fd9b2dc`.
At Task 18 close this was local L2 evidence only: no SSH, transfer, remote
replay, Provider call, production change, merge, Git push or DingTalk occurred
or was authorized. See
`.superpowers/sdd/task-18-zero-page-budget-checkpoint-replay-report.md`.

Task 19 later transferred that exact Task 18 bundle to an independent
SHA-versioned directory and executed exactly one authorized `--network none`
staging replay. Replay returned `complete/replay_complete`, source and target
fingerprints were equivalent, and the published replay DB SHA is
`3504190ab2b80ad1a003da27574455802f4184499eeaa7d458a6b771c3a8c638`.
Source DB/raw archive, Provider count, delivery and production remained
unchanged. This is deterministic replay proof only: collection remains
`partial/budget_exhausted`, full validation was not run, Task 14 is not accepted
and Task 15 is unauthorized. See
`.superpowers/sdd/task-19-remote-replay-report.md`.

Task 20 local verification is complete for append-only budget extension,
hydration resume, bounded round-robin discovery and strict offline discovery
reindex. Evidence is combined `243/243`, validation/replay/reindex `108/108`,
serialized offline full suite `445/445`, independent review with no P0/P1, and
canonical manifest `22/22` at SHA
`347c6ede1fe36852509dffe051fa7bf2b4d0c1e24ead8dda1af085bc44ff9d94`.
Task 21 later transferred that exact bundle and consumed its single authorized
`--network none` staging reindex. It failed closed on
`strict_discovery_schema_unknown`; no target DB was published and postflight
proved source/raw and production unchanged with `provider_call=false` and
`live_send=false`. A read-only aggregate found the `635` empty legacy pages pass
strict-v2 while all `35` non-empty pages fail on telemetry/Crosspost wrapper
handling.
Historical collection remains incomplete. A local RED-to-GREEN compatibility
repair has now passed for the exact reviewed `SearchPost`, `SearchCrosspost` and
nested telemetry shapes while unknown wrappers remain fail-closed. Task 21R
evidence is reindex `26/26`, related regression `200/200`, full suite `452/452`,
and canonical `22/22` candidate manifest SHA
`88f3d58c89980ed0c685796c340c6752c11f5394e61409f6beeb8a4303b3938f`.
The real frozen DB/raw corpus was not accessed locally, so a separately
authorized remote read-only `670/670` gate must pass before at most one new
network-none reindex. Task 22 Provider continuation is still unauthorized.
See `.superpowers/sdd/task-21-remote-reindex-report.md`.
Task 21R local evidence is in
`.superpowers/sdd/task-21r-legacy-wrapper-compatibility-report.md`.

## Local Commands

Run all tests:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Run the local daily dry-run wrapper:

```bash
REDDIT_VOC_RUN_ID=local_acceptance \
REDDIT_VOC_DATABASE_PATH=data/reddit_voc_local_acceptance.sqlite3 \
REDDIT_VOC_OUTPUT_DIR=outputs \
REDDIT_VOC_LOG_DIR=logs \
scripts/run_local_daily_dry_run.sh
```

Show the selected TikHub Reddit API plan without provider call:

```bash
PYTHONPATH=src python3 -m reddit_voc.cli tikhub-api-plan
```

Run the 07:00 Beijing-time TikHub collector wrapper manually:

```bash
REDDIT_VOC_ENV_FILE=~/.reddit-voc/secrets/reddit-voc-live.env \
REDDIT_VOC_RUN_DATE=20260707 \
REDDIT_VOC_DATABASE_PATH=data/reddit_voc_daily.sqlite3 \
REDDIT_VOC_OUTPUT_DIR=outputs \
REDDIT_VOC_LOG_DIR=logs \
scripts/run_daily_collect.sh
```

Run the 08:00 Beijing-time Chinese HTML report wrapper manually in default dry-run mode:

```bash
REDDIT_VOC_RUN_DATE=20260707 \
REDDIT_VOC_DATABASE_PATH=data/reddit_voc_daily.sqlite3 \
REDDIT_VOC_OUTPUT_DIR=outputs \
REDDIT_VOC_REPORT_OUTPUT_DIR=outputs \
REDDIT_VOC_LOG_DIR=logs \
scripts/run_daily_report.sh
```

Build the Chinese daily report for an existing run:

```bash
PYTHONPATH=src python3 -m reddit_voc.cli build-daily-report \
  --database data/reddit_voc_local_acceptance.sqlite3 \
  --output-dir outputs \
  --run-id local_acceptance \
  --translation-mode libretranslate
```

The authorized live-send command for the Chinese daily report is separate and gated:

```bash
REDDIT_VOC_ENV_FILE=~/.reddit-voc/secrets/reddit-voc-live.env \
PYTHONPATH=src python3 -m reddit_voc.cli send-daily-report-live \
  --database data/reddit_voc_local_acceptance.sqlite3 \
  --output-dir outputs \
  --run-id local_acceptance \
  --artifact-base-url '<reachable-artifact-base-url>' \
  --required-keyword LL \
  --authorize-live-send
```

Check one run:

```bash
PYTHONPATH=src python3 -m reddit_voc.cli status-summary \
  --database data/reddit_voc_local_acceptance.sqlite3 \
  --run-id local_acceptance
```

Check operational issues:

```bash
PYTHONPATH=src python3 -m reddit_voc.cli issue-summary \
  --database data/reddit_voc_local_acceptance.sqlite3 \
  --run-id local_acceptance
```

Check whether the expected 07:00 Beijing-time collection window has a local run:

```bash
PYTHONPATH=src python3 -m reddit_voc.cli missed-run-check \
  --database data/reddit_voc_local_acceptance.sqlite3
```

Preview artifact or log retention:

```bash
PYTHONPATH=src python3 -m reddit_voc.cli prune-artifacts \
  --path logs \
  --pattern "*.log" \
  --keep-last 30
```

Apply log retention:

```bash
PYTHONPATH=src python3 -m reddit_voc.cli prune-artifacts \
  --path logs \
  --pattern "*.log" \
  --keep-last 30 \
  --apply
```

## Expected Artifacts

For a run ID `<run_id>`, the wrapper writes:

- `outputs/<run_id>-posts.jsonl`
- `outputs/<run_id>-comments.jsonl`
- `outputs/<run_id>-analysis.jsonl`
- `outputs/<run_id>-posts.csv`
- `outputs/<run_id>-comments.csv`
- `outputs/<run_id>-analysis.csv`
- `outputs/<run_id>-dingtalk-dry-run.json`
- `outputs/<run_id>-daily-detail.xlsx`
- `outputs/<run_id>-daily-detail.csv`
- `outputs/<run_id>-insight-report.html`
- `outputs/<run_id>-insights.png`
- `outputs/<run_id>-daily-dingtalk-dry-run.json`
- `outputs/<run_id>-daily-report-summary.json`
- `outputs/<run_id>-status-summary.json`
- `outputs/<run_id>-issue-summary.json`
- `outputs/<run_id>-log-retention-summary.json`
- `logs/<run_id>.log`

## Scheduler

The legacy fixture template is `config/launchd/com.reddit-voc.daily-dry-run.plist.template`. The daily production-shape templates are:

- `config/launchd/com.reddit-voc.daily-collect.plist.template`: 07:00 Asia/Shanghai collector.
- `config/launchd/com.reddit-voc.daily-report.plist.template`: 08:00 Asia/Shanghai Chinese HTML report wrapper; default mode is dry-run, live send requires runtime gates.

They are not installed by default. Use `docs/reddit-voc-launchd-dry-run-plan-20260707.md` as the scheduler gate document before any install/load step.

## Chinese Daily Report

`build-daily-report` writes a single-page HTML report first. The HTML report contains the complete Chinese insight storyline and keeps the VOC detail table at the bottom. It also writes one row per Reddit post to CSV/XLSX. The post title/body columns include Chinese translation fields. All parsed comments under the post are merged into the same row in `评论整合原文` and `评论整合中文`, using numbered comment blocks.

Translation defaults to `dry_run`: fixture-known text uses a local glossary and unknown text is preserved without a provider call. For automated Chinese translation of post bodies and comments, set `REDDIT_VOC_TRANSLATION_MODE=libretranslate` and provide `LIBRETRANSLATE_BASE_URL` for a self-hosted or authorized LibreTranslate-compatible service. Optional `LIBRETRANSLATE_API_KEY`, `REDDIT_VOC_TRANSLATION_SOURCE`, `REDDIT_VOC_TRANSLATION_TARGET`, and `REDDIT_VOC_TRANSLATION_TIMEOUT_SECONDS` are read from runtime environment only.

Production deploys can run a free self-hosted LibreTranslate sidecar with `webapp/docker-compose.translation.yml`. It attaches only to the private `reddit_voc_site_net` Docker network and should be reached from report jobs as `http://reddit_voc_libretranslate:5000`; do not expose it through Nginx unless a separate access-control decision is made.

## TikHub Reddit API Plan

Selected endpoints:

- `/api/v1/reddit/app/fetch_dynamic_search`: brand-first Momcozy/momcozy/mom cozy broad recall, then product/category keyword recall.
- `/api/v1/reddit/app/fetch_subreddit_feed`: community feed discovery after dynamic search.
- `/api/v1/reddit/app/fetch_post_details_batch_large`: post detail enrichment in batches up to 30 IDs.
- `/api/v1/reddit/app/fetch_post_comments`: fallback comment tree endpoint when detail payload is incomplete.

The API key must stay in runtime environment only:

```bash
export REDDIT_VOC_ENABLE_TIKHUB=1
export TIKHUB_API_KEY='<runtime-only-api-key>'
```

## Reddit Chrome Profile

The dedicated Chrome profile stays outside the repo at `~/.reddit-voc/chrome-profile`.

Initialize and inspect:

```bash
PYTHONPATH=src python3 -m reddit_voc.cli browser-profile-init
PYTHONPATH=src python3 -m reddit_voc.cli browser-profile-status
```

Open the profile for manual Reddit login:

```bash
scripts/open_reddit_chrome_profile.sh
```

Open a CDP-controllable automation profile for browser-harness smoke:

```bash
REDDIT_VOC_CHROME_USER_DATA_DIR="$HOME/.reddit-voc/chrome-automation-profile" \
REDDIT_VOC_CHROME_REMOTE_DEBUG_PORT=9333 \
scripts/open_reddit_chrome_profile.sh
```

Then point the smoke command at that endpoint:

```bash
PYTHONPATH=src python3 -m reddit_voc.cli run-browser-json-smoke \
  --database data/reddit_voc.sqlite3 \
  --output-dir outputs \
  --run-id <run_id> \
  --url https://www.reddit.com/r/shopify/comments/1umbsm4/shopify_store_traffic_is_100_visitorsday_but/.json \
  --browser-cdp-url http://127.0.0.1:9333
```

`profile_present_login_unverified` means Chrome has profile storage, not that Reddit login is proven. A future read-only smoke must verify the Reddit `.json` route before scheduler use.

## DingTalk Live Send Gate

The DingTalk robot keyword is `LL`. Keep the webhook URL and secret outside repo files.

The DingTalk Markdown digest includes Reddit source links for parsed posts/comments. Export artifact links become clickable only when `REDDIT_VOC_ARTIFACT_BASE_URL` or `--artifact-base-url` points to a reachable file host; otherwise the digest keeps local artifact paths as evidence only.

Prepare runtime environment without writing secrets to tracked files:

```bash
mkdir -p ~/.reddit-voc/secrets
chmod 700 ~/.reddit-voc ~/.reddit-voc/secrets
umask 077
cat > ~/.reddit-voc/secrets/reddit-voc-live.env <<'EOF'
export REDDIT_VOC_ENABLE_TIKHUB=1
export TIKHUB_BASE_URL='https://api.tikhub.io'
export TIKHUB_API_KEY='<runtime-only-api-key>'
export REDDIT_VOC_DINGTALK_MODE=live
export REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND=1
export DINGTALK_REQUIRED_KEYWORD='LL'
export REDDIT_VOC_ARTIFACT_BASE_URL='<reachable-artifact-base-url>'
export DINGTALK_WEBHOOK_URL='<redacted-webhook-url>'
export DINGTALK_WEBHOOK_SECRET='<optional-signing-secret>'
EOF
chmod 600 ~/.reddit-voc/secrets/reddit-voc-live.env
```

Send only after explicit owner authorization for a specific run:

```bash
REDDIT_VOC_ENV_FILE=~/.reddit-voc/secrets/reddit-voc-live.env \
PYTHONPATH=src python3 -m reddit_voc.cli send-dingtalk-live \
  --database data/reddit_voc.sqlite3 \
  --output-dir outputs \
  --run-id <run_id> \
  --required-keyword LL \
  --authorize-live-send
```

The command is blocked unless both `--authorize-live-send` and `REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND=1` are present.
