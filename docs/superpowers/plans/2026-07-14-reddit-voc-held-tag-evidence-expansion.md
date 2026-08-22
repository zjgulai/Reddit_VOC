---
title: Reddit VOC held 标签证据扩展与 v2 门禁实施计划
doc_type: implementation_plan
status: complete
created: 2026-07-14
updated: 2026-07-14
owner: codex
production_boundary: production_unchanged
provider_call: false
database_write: false
live_send: false
webhook_send: false
deploy: false
schedule_change: false
commit: false
---

# Reddit VOC held 标签证据扩展与 v2 门禁实施计划

## 1. 目标

在不降低既有质量门槛、不覆盖 tag-repair v1、Insights v1、日报/周报/月报 v1 和
既有 UI 的前提下，对四个 held 标签实施第二轮窄范围关系修复，并建立开发证据与
验证证据严格分离的 v2 审计链路。

本轮只使用已经纳入基础快照的本地 Reddit 数据，不连接腾讯生产、不调用外部模型、
不写数据库、不发送、不调度、不部署。

## 2. 核心证据规则

1. v1 legacy 样本继续只用于回归，不能进入 v2 发布样本。
2. v1 review sample、challenge cases 以及本轮已经阅读的全部 v1 `needs_review`
   候选统一标记为 development evidence，不能伪装成独立验证样本。
3. v2 规则先冻结，再从剩余未见候选中抽取 predicate-confirmed 样本复核。
4. 复核仍由 Codex 完成并明确记录 `independent_human_review=false`。
5. 每标签继续执行 precision、Wilson 95% 下界、taxonomy fit、ambiguity、legacy
   regression 和 challenge 门禁；任何一项不足均保持 `held_after_repair`。
6. 只有至少一个标签真实晋级，才允许生成 Insights/reports/persona 新版本；否则
   下游版本和 UI 保持不变。

## 3. 完成标准

- 新增不可变 v2 predicate policy，v1 policy 和 v1 数据集字节不变。
- 修复否定词、受控产品上下文、Momcozy 相邻句对比、第一人称配件意图四类关系。
- v2 manifest 绑定基础快照、字典、v1 repair manifest 和 development evidence SHA。
- v2 review sample 与 legacy、v1 review、v1 challenge、v1 needs-review development
  evidence 全部零重叠。
- 独立 validator 从原始基础快照重算 assignments、排除集、样本、门禁和全部哈希。
- 对未见 v2 样本逐条复核并生成显式 decisions；不使用默认判定替代逐条 override。
- 定向测试、v1 回归、v2 builder/validator、确定性与篡改测试通过。
- 若无标签晋级，明确记录本地数据证据上限，并不生成虚假的 Insights/reports v2。

## 4. 实施顺序

### Task 1：冻结开发证据边界并补 RED 测试

- 建立 development-evidence 收据，绑定 v1 repair manifest/assignments/review/challenge。
- 为四个窄修复点增加 v2 直接关系测试和反例测试。
- 增加 review sample 多集合零重叠与哈希篡改测试。

### Task 2：实现 predicate v2

- v1 缺省路径行为完全不变；v2 特性只由 v2 policy 显式开启。
- 评论 parent context 只可用于产品主体 grounding，不能替代评论中的价值断言。
- 相邻句对比只允许明确方向模板，不做任意跨句共现绑定。
- 第一人称 discourse 绑定必须与主动意图和配件词同句，第三方主体仍 fail closed。

### Task 3：扩展 builder 与独立 validator

- 数据集版本从 policy 显式读取，v1 无字段时保持原默认值。
- builder 和 validator 分别重算 development exclusion，不共享实现。
- manifest、review sample 和 validation receipt 显式记录排除来源、数量与 SHA。

### Task 4：生成、复核并验证 v2

- 先生成 pending 快照；冻结后才读取新抽中的未见上下文。
- 为每条 v2 review sample 写显式 decision 和理由。
- 重建 complete 快照并运行独立 validator。

### Task 5：条件化下游激活

- `promoted_after_repair > 0`：生成不可变 Insights/reports/persona 新版本，保持日报、
  周报、月报和既有 UI 布局；只接入真实晋级标签。
- `promoted_after_repair == 0`：不生成下游新版本，记录证据不足原因和下一步需要的
  新数据条件。

### Task 6：收尾验证与项目记录

- 运行 predicate/tag-repair v1/v2 相关 pytest、独立 validator、字节稳定性和篡改测试。
- 检查 v1 manifest SHA 不变。
- 更新本计划、分析报告、`.codex/context-pack.md` 和 `.kiro/plan/progress.md`。

## 5. 固定边界

- `production unchanged`
- `provider_call=false`
- `database_write=false`
- `live_send=false`
- `webhook_send=false`
- `deploy=false`
- `schedule_change=false`
- `git_commit=false`
- `git_push=false`
- `git_merge=false`
- `independent_human_review=false`

## 6. 实际结果

- v2 predicate 将 243 条 lexical candidates 从 v1 的
  `20 confirmed / 92 needs_review / 131 rejected` 调整为
  `46 confirmed / 65 needs_review / 132 rejected`。
- 开发证据收据绑定 v1 manifest、assignments、review sample 和 challenge cases；
  排除 92 条已阅读 `needs_review`、12 条 v1 review 和 80 条 v1 challenge 后，去重
  development exclusion 为 152 条。
- 冻结 v2 policy 后，四标签剩余未见 confirmed population 均为 0；因此没有可做
  item-level review 的新样本，不能计算有效 precision、taxonomy fit 或 Wilson 下界。
- `L2-PUMP-016` 和 `L0-CHL-003` 的剩余未见 challenge population 分别只有 9 和
  18，也低于 20 条 challenge 门槛；另两标签达到 20 条。
- 完成态为 `completed_no_new_promotions`，`0 promoted / 4 held`；按条件门禁未生成
  Insights、reports、persona v2，日报/周报/月报 v1 和 UI 均未修改。
- v2 manifest SHA-256 为
  `dc8a7518c24af6a0722ebe39c8fc5159cf7904745b66b74c88ec9392fc73ec42`；
  独立 validator 状态 `passed`。v1 manifest SHA-256 仍为
  `99dfb8bc7605ae2069822a4df99dd06b7832a4783c73c92e9d002b3e546ec8f1`。
- predicate、tag repair v1/v2、Insights、reports、persona 相关测试 `92 passed`；全仓
  `759 passed / 3 failed`，三个失败均为本批未修改的历史 backfill release manifest
  与 `backfill_cli.py`、`backfill_seed.py`、`tikhub.py` 当前 SHA 漂移。
- 前端全量 Vitest `15 files / 104 tests`、production build、HTTP route/static manifest
  smoke 通过；lint 为 0 errors、5 个既有 Fast Refresh warnings。

下一次获得有效晋级证据必须增加新的、未参与规则开发的 Reddit 实体；重复复核当前
本地数据或降低质量门槛都不能解决该问题。
