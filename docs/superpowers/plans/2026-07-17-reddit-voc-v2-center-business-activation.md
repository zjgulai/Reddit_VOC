---
title: Reddit VOC V2 中心数据业务激活与页面闭环计划
doc_type: implementation_plan
status: ready_for_owner_authorization
created: 2026-07-17
updated: 2026-07-17
owner: codex
production_boundary: production_unchanged
provider_call: false
database_write: local-test-only
remote_write: false
deploy: false
schedule_change: false
live_send: false
---

# Reddit VOC V2 中心数据业务激活与页面闭环计划

## 1. 目标

将已通过零差异验证的 V2 中心数据集作为唯一数据版本锚点，打通：

```text
V2 center
→ post VOC + comment-context VOC
→ 标签 / 品牌 / 竞品 / 品类 / SPU / 情感 / 风险 / 画像
→ 原子指标 / 衍生指标 / 品牌健康
→ 日报 / 周报 / 月报 / 洞察 / 画像 / 概览 / 案例
→ frontend source candidate
→ local release + E2E + shadow
```

本计划不授权 Provider 调用、生产写入、cron 修改、远端传输、部署或生产切换。

## 2. 第一性完成标准

1. 数据唯一：每个页面制品都能追溯到同一 `center_state_sha256`。
2. 身份守恒：3,494 帖、27,158 存储评论、20,205 已关联、6,943 关系债务、10 隔离保持一致。
3. 业务守恒：帖子独立 VOC；评论只在具备父帖语境时形成 comment-context VOC。
4. 口径守恒：日报、周报、月报、洞察、画像和概览不得各自重算不同版本。
5. 展示真实：不能计算的指标不进入页面；可计算的同环比、同比和趋势必须使用完整历史窗口。
6. 可重放：相同输入重新执行必须得到 byte-identical 或 `no_change`。
7. 发布分层：本地候选、E2E、shadow、production promotion 分开验收。

## 3. 完整 TODO

| ID | TODO | 状态 | 退出证据 |
|---|---|---|---|
| B2B-00 | 冻结完整 V3 baseline、V2 center、bridge、零差异 receipt | complete | center counts 守恒；identity missing/unexpected 为 0 |
| B2B-01 | 建立中心数据业务激活 manifest，逐级绑定 canonical、VOC、标签、指标、画像、报告和洞察 | complete | activation SHA `67096475...a3a14`；同输入 `no_change` |
| B2B-02 | 建立独立激活 validator，不调用 builder 结论，重新核验 SHA、schema、status、lineage 和中心计数 | complete | receipt SHA `7690e978...598a8`；篡改 fail closed |
| B2B-03 | 核对帖子 VOC、评论上下文 VOC、自动化排除、标签和品牌/产品事实 | complete | 23,586 VOC、7,066 exclusions、159,044 governed facts 守恒 |
| B2B-04 | 核对 26 指标、19 个核心指标、7 个内容诚信指标和 5,678 个周期 | complete | metrics 与 center/canonical lineage 同链 |
| B2B-05 | 核对 82 原子画像、8 画像组、9 张合成头像及季度画像口径 | complete | counts 为内容实体而非人数；author-level=false |
| B2B-06 | 核对日报/周报/月报当前期与归档期、同比/环比/趋势、品类/SPU/竞品分析 | complete | 六报告文件非空；Owner 100% comparison contract 保留 |
| B2B-07 | 核对洞察四模块、季度数据集、案例证据、品牌健康和概览三窗口 | complete | reports/insights/brand-health/quarter/casebook 全部绑定真实制品 |
| B2B-08 | 将中心激活 manifest 作为受控 auxiliary artifact 纳入新 frontend source candidate | complete | source `454598e7...ebcab`；投影 manifest `0d48918c...34865` |
| B2B-09 | 构建本地 immutable release，执行前端单测、lint、typecheck、build 和静态审计 | complete | 195 passed；release `f335d9d2...25d4b`；76-file dist |
| B2B-10 | 执行 13 路由桌面/移动 E2E、非空检查、URL 状态、下载和跨页数据对账 | complete | E2E receipt `95559f0b...90ac2`；26 页面通过 |
| B2B-11 | 连续执行至少两个本地 shadow 周期，与当前生产 release 做只读差异归因 | complete | receipts `324d0263...45aec`、`d5e0fa16...bcc74` |
| B2B-12 | 冻结候选 release 与 promotion packet | ready_for_owner_authorization | packet `fa54470d...246f6`；未创建 permit、未切换生产 |

## 4. 业务激活阶段合同

业务激活 manifest 必须显式绑定以下经过验证的对象，禁止扫描 `latest`：

- V2 center state、baseline bridge 和 zero-diff receipt；
- V3 canonical manifest/receipt；
- VOC facts manifest/receipt；
- governed signals manifest/receipt；
- metrics input、metrics candidate/receipt；
- personas manifest/receipt；
- reports candidate/receipt 和 public manifest/receipt；
- insights candidate/receipt 和 public manifest/receipt；
- brand-health public manifest；
- 作为激活前置基线的 frontend source manifest 和 source-stage receipt。

激活 manifest 与承载它的 frontend source 不能互相绑定，否则形成不可解的循环哈希。正式闭环采用
`activation manifest → public projection → frontend source → release/shadow receipt` 的单向链；
release 与 shadow receipt 负责证明激活投影确实进入最终 dist。

若中心状态、任一文件 SHA、schema、passed/promotable/consumption 状态或上游 lineage 不一致，
激活必须失败，不生成页面候选。

## 5. 验证分层

```text
L1 代码与 fixture：unit / tamper / no-change
L2 完整本地数据：中心→业务制品→source candidate
L3 本地 release：build / container smoke / browser E2E
L3-shadow：两个周期只读对比
L4 production：新的精确 packet + release 授权后另行执行
```

当前仅授权推进 L1、L2 和后续本地 L3；生产保持不变。

## 6. 本轮验收结论

- activation manifest：`670964755588b9a9c7eb8a0744c0dc614090904cb1ff76459a3d99055c5a3a14`；
- frontend source：`454598e73f7bacfa9da0b68f562bf65d571aaa922cc98aff293c00ad85debcab`；
- release：`f335d9d27e168068385d99e022a9a4fc6cd5e898485845c965186e3034325d4b`；
- promotion packet：`fa54470d7e20e406875febd5315d42749d7a69bdc6742570542663b91dd246f6`；
- packet status：`ready_for_owner_authorization`，到期时间 `2026-07-17T13:08:30Z`；
- production：仍为 `9c4a45f2...84cc5`，`production unchanged`。
