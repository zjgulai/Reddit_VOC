---
title: Reddit VOC Plan C - Candidate-only 编排、测试与受控提升
doc_type: implementation_plan
status: production_critical_complete_automation_debt_pending
created: 2026-07-15
updated: 2026-07-15
owner: codex
depends_on: 2026-07-15-reddit-voc-candidate-closure-data.md, 2026-07-15-reddit-voc-ui-governance.md
evidence_grade: L4_authorized_live
production_boundary: insights_current_promoted
deploy: true
remote_write: insights_site_only
schedule_change: false
---

# Plan C：Candidate-only 编排、测试与受控提升

## 2026-07-15 production promotion and acceptance

Owner 精确授权 packet
`83d5ebeaf2345bc78495ed99064d34dcb4f23d09d2c8eda5274110f50a510570` 与 release
`a5fa1e0a0a224969669d7e6ad79a9415b69f2ba4646b6e2bbca9030ff3d460f3` 后，受控提升已完成。
同一远端锁内通过 fresh L3、18339 候选 smoke、切换瞬间 CAS 和18338生产容器 smoke；公网
HTTPS、13路由、20安全404、26/26桌面/移动页面、六报告状态、案例存量和采集后台链接通过。
L4 acceptance receipt SHA为
`b5fcd6821de7f4047b1deb9bee6bd60c3d81bcaa6380fc2d8e8912f0a5a76ade`。

当前生产 pointer 为 `reddit_voc_release_20260715_70a917e5bdf0`。采集器、LibreTranslate、
shared Nginx、cron、TLS、DNS、数据库、调度与其他 Docker 均未修改；旧 release
`9e0d2313...d650` 保留且校验通过。Registry与四导出完整验收仍为显式deferred debt，
本次验收不把它们申领为完成。

## 2026-07-15 owner priority override — boss-visible production first

Owner 将当前执行顺序调整为先让新版本生产站可供老板查阅。上线前只保留不可跳过的
关键路径：Plan A/B exact inputs → manifest-only final dist/release → 核心13路由同一 dist
E2E → 安全404 → linux/amd64 local container smoke → 唯一 promotion packet。C1 registry
深度治理、四导出增强与完整 candidate automation 后移为生产可见后的债务。

此优先级调整不放宽生产边界：实际上传、`docker load`、18339、current switch 仍须 owner
对新生成的完整 promotion packet SHA 和 release SHA 作精确授权；采集器、cron、shared
Nginx、TLS、DNS、其他 Docker、Provider、DB、调度与 live send 继续不在范围内。

## 2026-07-15 production-critical local exit（提升前历史门）

首发关键路径当时停在精确授权门：唯一可提升 release 为
`a5fa1e0a0a224969669d7e6ad79a9415b69f2ba4646b6e2bbca9030ff3d460f3`，同一 dist
13 路由×desktop/mobile 为26/26，隔离 linux/amd64 容器 smoke 与20项安全404通过。
Fresh L3只读基线仍是旧 release `9e0d2313...d650`，采集器、LibreTranslate、shared
Nginx、cron、DB/report stat与完整运行容器清单稳定，18339为空。

唯一 packet SHA 为
`83d5ebeaf2345bc78495ed99064d34dcb4f23d09d2c8eda5274110f50a510570`，状态
`ready_for_owner_authorization`，有效期到 `2026-07-15T15:42:48Z`。Packet明确把registry
与四导出完整验收保留为首发上线后的deferred debt；未取得完整packet/release SHA精确授权
前仍不得上传、远端`docker load`、启动18339或切换current。

## 1. 目标与不可跨越边界

Plan C 将已验证的底层脚本组合为可重入、不可变、默认停止于 registry 的候选流水线。
它不实现无人值守生产部署。A/B/C 只能共同形成一个最终 release；任何单独 Plan 的制品
都不得独立提升生产。

Batch 5–6 完成条件：

- 静稳门、singleton lock、source/data/code/frontend freeze、五本账、四层数据、dist、
  container、E2E、export 和 receipt 均有 SHA 绑定；
- 相同输入返回同一 receipt/no-change，不制造空 release；
- candidate registry append-only 且记录 `deploy=false`；
- build/validation 失败不登记为可提升候选；
- 对同一 candidate + current baseline 生成最多一个有效、精确的 promotion packet，
  报告 packet SHA 和 release SHA 后停止；
- 未取得新授权前不上传、不 `docker load`、不启动远端 18339、不切 production current。

## 2. 预期文件范围

新增或产品化：

- `scripts/build_reddit_candidate.py`
- `scripts/validate_reddit_candidate_registry.py`
- `scripts/build_reddit_promotion_packet.py`
- `scripts/build_frontend_source_manifest.py`
- `scripts/run_insights_e2e.py`
- `scripts/validate_insights_exports.py`
- `scripts/smoke_local_insights_container.sh`
- `scripts/validate_reddit_promotion_permit.py`
- `scripts/promote_reddit_candidate.py`
- `scripts/remote_smoke_insights_candidate.sh`
- `scripts/build_reddit_production_acceptance.py`
- `tests/test_build_reddit_candidate.py`
- `tests/test_validate_reddit_candidate_registry.py`
- `tests/test_build_reddit_promotion_packet.py`

复用并仅在合同缺口需要时窄改：

- `scripts/freeze_reddit_incremental_inputs.py`
- `scripts/build_reddit_current_release.py`
- `scripts/validate_reddit_incremental_candidate.py`
- `scripts/build_insights_release.sh`
- `scripts/playwright_insights_e2e.js`
- `scripts/remote_install_insights_release.sh`
- 现有对应 tests

全局锁固定为 `tmp/reddit-voc-candidate-automation/candidate-build.lock`，必须在静稳探针前
获取；不同 freeze 不能使用不同锁。Promotable registry 固定为
`output/reddit-voc-candidate-registry/entries/`，events 和 runs 分别进入同级目录；
blocked/failed 只进 run ledger，不进入 promotable entries。不修改系统 cron/systemd。

## 3. Batch C1：Candidate-only orchestrator

### C1.1 RED tests

- singleton：使用稳定 inode 上的 `flock` 判断活动锁；已有活动锁时返回
  `candidate_build_already_running`。不得按 PID/owner/age 删除锁文件，这些字段仅作诊断；
- quiescence：非静稳只产出 blocked receipt；
- no-change：相同 source freeze 与完整 code/frontend freeze 返回既有 candidate receipt；
- collision：同 version 不同 bytes fail closed；
- step failure：任一步失败不生成 promotable registry entry；
- manifest：每个下游 receipt 必须绑定精确上游 SHA；
- registry：append-only、原子写入、禁止 symlink/path traversal；
- side effects：candidate 记录固定 `deploy=false/remote_write=false/provider_call=false`。

### C1.2 最小编排

```text
singleton lock
→ quiescence receipt
→ Plan A freeze/ledgers/data receipt
→ Plan B frontend source-tree/UI source-test receipt
→ independent data/frontend validators
→ Plan C final dist/container artifact
→ Plan C final same-dist browser/export/security receipts
→ immutable candidate receipt
→ append candidate registry
→ stop
```

orchestrator 通过 subprocess 调用既有 CLI 并校验其 JSON receipt，不复制 builder 逻辑，
不吞 stderr，不把命令 exit 0 单独视为业务完成。

候选身份拆成两层：

```text
candidate_input_sha256 = SHA256(
  source/data/code/config/frontend-source/toolchain/build-contract canonical SHAs
)
candidate_id = SHA256(
  candidate_input_sha256 + final release SHA + dist/release manifests
  + stable validation evidence SHAs
)
```

`stable validation evidence SHA` 对 validation receipt 去除 `generated_at`、`validated_at`、
`run_id` 等易变字段后的 canonical evidence projection 哈希。完整 receipt 文件 SHA 仍由
manifest/packet 记录，但不进入 `candidate_id`。因此时间字段不会间接进入内容身份。
no-change 先命中 input SHA，再完整复核
既有 final artifacts/receipts；只凭输入身份不能返回 promotable。数据升级、late-arriving
comment、relink 或 coverage closure 变化即使净新增帖子为 0，也不是 no-change。

交接合同固定为：

- Plan A：`<candidate-root>/data/candidate-data-validation-receipt.json`；
- Plan B：`<candidate-root>/frontend/source/frontend-source-manifest.json` 与
  `<candidate-root>/frontend/source/candidate-ui-source-validation-receipt.json`；
- Plan C：`<candidate-root>/frontend/final/candidate-ui-validation-receipt.json`；
- 每个 CLI 明确 `created/no_change/blocked`、schema、canonical serialization、上游 SHA 和退出码；
- Plan B 只交付 source 与测试 receipt，Plan C 是唯一 final dist/container owner。

## 4. Batch C2：完整本地同一制品验收

- Python focused/related 必须全绿；full regression 不得新增失败。既有失败必须绑定精确
  baseline SHA，不能描述为 full pass；
- frontend unit/lint/typecheck/build；
- 完整 React source-tree manifest 与 dist manifest 绑定；
- 同一 dist 完成 13 routes × desktop/mobile；
- CSV/DOCX/PDF/PPT 四种导出实际生成并验证结构、内容版本和非空；任一尚未实现时
  candidate 必须 blocked，不得用 `unavailable` 冒充四导出验收；
- linux/amd64 image/tar 离线检查：architecture、non-root UID 101、labels、marker、dist SHA；
- 本地隔离容器 smoke 只绑定临时 loopback 端口，并在运行态验证 read-only rootfs、
  zero mounts、network/capabilities 和进程 UID；
- `/.env`、私有 data paths、source manifests 的安全 404 合同；
- tamper/no-change/missing/symlink/collision/failure-injection 回归。

Full gate 只能消费：

```text
candidate-root/frontend/dist
candidate-root/frontend/container-release/<release_sha>/release-manifest.json
```

禁止消费 `frontend/release-metadata-preview/release-manifest.json`。正式 manifest 必须为
`reddit_voc_insights_site_release_v2` 并绑定完整 dist、四层数据、current pointer、
build/deployment inputs 和 collection status。

本批严格本地，不上传制品，不对远端执行 `docker load`，不启动 18339。

## 5. Batch C3：唯一 promotion packet

`build_reddit_promotion_packet.py` 只接受已通过的最终 candidate receipt，并绑定：

- source freeze、五本账和 Plan A data receipt；
- Plan B frontend source/UI source-test receipt；
- Plan C final dist/container/same-dist E2E/export/security receipts；
- Base/Insights/Reports/Personas/public manifests；
- export、security、container、image tar/TGZ receipts；
- exact release SHA、current baseline SHA、expiry、允许动作和回滚目标；
- collector/cron/shared Nginx/TLS/DNS/other Docker 不变性预期；
- `promotion_authorized=false`、`deploy=false`。

packet 必须 canonical serialization，生成 SHA 后不可修改。同一 candidate + current
baseline 最多一个有效 packet；expiry 或 baseline 变化可生成新 packet，旧 packet 继续
immutable retained。完成后向负责人报告完整 packet SHA 与 release SHA，停止等待精确授权。

## 6. Batch C4：受控生产提升（本计划默认不执行）

只有用户另行明确授权完整 promotion packet SHA 和 release SHA 后才允许：

1. 重新做 L3 current/quiescence/non-interference preflight；
2. 从 preflight 开始获取并持续持有同一个远端 `.deploy.lock`，直到 18339 smoke、
   compare-and-swap cutover 或安全停止完成；
3. 用独立不可变 owner permit 校验 packet SHA、release SHA、current baseline、expiry、
   nonce 和允许动作；permit 来源必须是用户在当前任务中对完整 packet SHA + release SHA
   的明确授权，保存为
   `output/reddit-voc-promotion-authorizations/<authorization-id>/permit.json`，schema 固定、
   mode 0600、内容不可改写；
4. `promote_reddit_candidate.py` 必须显式接收 `--permit`，不存在默认 permit；一次性消费
   状态写入独立 immutable consumption receipt，不修改 permit 本身；
5. 上传至隔离 release 目录并逐字节验 SHA；
6. 才可 `docker load` 并在 18339 启动临时候选；
7. 候选 HTTP、浏览器、六报告、四导出、安全路径通过后，cutover 必须接收
   `--expected-current <sha>` 并在实际切换瞬间再次 compare-and-swap；只切洞察站 current；
8. 做公网 HTTP/browser/E2E 与 collector/cron/Nginx/其他 Docker 不变性验收；
9. 失败只回滚洞察站 current，禁止干扰采集后台；
10. 通过后生成独立 L4 production acceptance receipt。

`remote_install_insights_release.sh` 不能直接作为新版本入口，因为它不消费 permit、固定
18338 且会直接切 current。Batch C4 必须通过新的 promotion wrapper 调用 18339 candidate
smoke 和 permit validator；普通 deploy wrapper 不得绕过。

每个远端动作必须在新授权允许范围内；普通“继续”不等同于 Batch C4 授权。

## 7. 验收矩阵

| 层级 | 必须证据 | 不能宣称 |
|---|---|---|
| L2 数据 | Plan A ledgers/data receipts | 生产已更新 |
| L2 UI | unit/lint/build/same-dist E2E | 公网已验收 |
| L2 release | container/export/security/promotion packet | 已部署 |
| L3 | 当前生产只读事实与静稳 | 有远端写入 |
| L4 candidate | 另行授权后的上传/18339 smoke | production accepted |
| L4 production | current switch + public E2E + invariants + receipt | 采集绝对完整 |

## 8. 停止门

任一 SHA 漂移、baseline 变化、静稳失败、账本/data/UI receipt 不通过、registry 碰撞、
导出缺失、容器合同失败、未知外部请求或精确授权缺失时立即停止。不得通过重试生产动作、
重启采集器、修改共享 Nginx/TLS/DNS、清理其他 Docker 或跳过测试来绕过门禁。
