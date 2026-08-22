---
title: Reddit VOC held 标签 v2 证据扩展审计报告
doc_type: analysis_report
status: complete
created: 2026-07-14
updated: 2026-07-14
production_boundary: production_unchanged
provider_call: false
database_write: false
live_send: false
deploy: false
---

# Reddit VOC held 标签 v2 证据扩展审计报告

## 1. 结论

第二轮关系修复已完成，但本地现有数据无法为四个 held 标签提供新的独立正例。

v2 规则把 confirmed 总数从 20 提高到 46；新增的 26 条全部位于已经阅读、用于规则
开发或已进入 v1 review/challenge 的证据集合中。严格排除这些开发证据后，四个标签
的未见 confirmed population 都是 0。因此最终仍为 `0 promoted / 4 held`，状态
`completed_no_new_promotions`。

这不是“v2 没识别到更多语义”，而是“识别到的更多语义不能再作为独立验证证据”。
如果把这些开发样本重复当成验证样本，统计门禁会产生数据泄漏。

## 2. v1 与 v2 predicate 变化

| 标签 | v1 confirmed | v2 confirmed | 变化 | v2 needs_review | v2 rejected |
|---|---:|---:|---:|---:|---:|
| `L2-PUMP-016` 法兰尺码不合适 | 7 | 8 | +1 | 8 | 20 |
| `L0-CHL-003` 物超所值 | 10 | 33 | +23 | 33 | 30 |
| `L2-PUMP-030` 出奶量不输主泵/竞品 | 3 | 4 | +1 | 22 | 30 |
| `L2-PUMP-007` 考虑购买配件 | 0 | 1 | +1 | 2 | 52 |
| 合计 | 20 | 46 | +26 | 65 | 132 |

四个窄修复点分别是：

- 识别 `don't/dont` 等否定词，避免把“不舒适”中的 `comfortable` 当成正向反证；
- 允许评论中的明确无条件价值断言从受控相邻句或父帖获得产品主体，但继续拒绝问句、
  条件、模态、传闻和非产品价值；
- 只对明确 equal-or-better 模板允许一条相邻句的 Momcozy 主体延续；
- 当主动购买意图和配件词同句时，允许从同句较早位置绑定第一人称 discourse，第三方
  主体、既往购买、保险/免费供应和可得性担忧继续 fail closed。

## 3. 开发证据与验证证据分离

v2 review sample 排除了：

| 排除来源 | 原始数量 |
|---|---:|
| v1 `needs_review`，本轮规则开发前已阅读 | 92 |
| v1 review sample | 12 |
| v1 challenge cases | 80 |
| 三者去重后的 development exclusion | 152 |

此外继续排除旧 semantic audit legacy samples。development evidence 收据分别绑定
基础 manifest、v1 repair manifest、assignments、review sample 和 challenge cases
的 SHA-256；builder 与 validator 各自独立重算排除集合。

冻结 v2 policy 后的未见证据结果：

| 标签 | 未见 confirmed | 未见 nonconfirmed challenge population | challenge 20 条门槛 |
|---|---:|---:|---|
| `L2-PUMP-016` | 0 | 9 | 未通过 |
| `L0-CHL-003` | 0 | 18 | 未通过 |
| `L2-PUMP-030` | 0 | 21 | 通过 |
| `L2-PUMP-007` | 0 | 35 | 通过 |

由于没有未见 confirmed，四标签的 sample plan、precision、taxonomy fit 和 Wilson
95% 下界均不能成立；这四项保持失败而不是用开发样本填充。复核执行者仍记录为
`independent_human_review=false`。

## 4. 下游决策

既定条件是只有至少一个标签达到 `promoted_after_repair`，才生成新的 Insights、
日报/周报/月报和 persona 数据版本。当前为 0 个晋级标签，因此：

- 不生成 Insights v2；
- 不生成 reports v2；
- 不生成 persona v2；
- 不修改报告 UI、画像 UI 或现有静态数据绑定；
- v1 日报、周报、月报继续作为当前已验证版本。

## 5. 验证证据

- v2 manifest SHA-256：
  `dc8a7518c24af6a0722ebe39c8fc5159cf7904745b66b74c88ec9392fc73ec42`
- v2 policy SHA-256：
  `27bbef9e662a4e524f8c944c83bad7030c2273c66cf8aa180932feb740a5c6f9`
- development evidence SHA-256：
  `20b3c11e499e8327758ed357c43448419d592af49b88251d865a8c384631b9b0`
- v1 manifest SHA-256 保持：
  `99dfb8bc7605ae2069822a4df99dd06b7832a4783c73c92e9d002b3e546ec8f1`
- 独立 validator：`passed`
- 定向数据链测试：`92 passed`
- 全仓测试：`759 passed / 3 failed`；三个失败均来自历史 backfill release manifest
  对 `backfill_cli.py`、`backfill_seed.py`、`tikhub.py` 的既有 SHA 不一致，本批未修改
  这些文件，也未修改 manifest 来制造通过。
- 前端：Vitest `15 files / 104 tests` 通过，production build 通过，lint `0 errors /`
  `5 existing warnings`；`/`、`/dashboard`、`/dashboard/insights`、
  `/dashboard/reports` 和 reports/personas v1 manifest HTTP smoke 均为 200。

validator 已检查文件哈希、基础/字典/policy/v1/development evidence 绑定、243 条
assignment 重算、legacy regression、多集合零重叠、challenge、门禁和副作用边界。
两个不同 `PYTHONHASHSEED` 的 v2 pending 输出逐字节一致。

## 6. 下一步需要决策

要继续晋级，必须引入新的、未参与规则开发的 Reddit 实体。推荐下一批使用腾讯生产
环境的新增数据，但应先做版本化只读导出或只读快照，再走同一 v2 排除和门禁流程；
不能直接写生产数据库，也不能把当前样本重新抽一次。

需要用户决定是否授权“腾讯生产只读快照/导出”这一独立步骤。未经该授权，本轮停在
本地完成态，不连接生产。

## 7. 固定边界

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
