---
title: Momcozy Reddit 竞品与品类历史采集盘点
date: 2026-07-15
---

# Momcozy Reddit 竞品与品类历史采集盘点

## 结论

本次盘点覆盖 V2 profile 中尚未被旧运行完整覆盖的 42 个 lane：17 个竞品、25 个品类。42/42 都已经执行过一次隔离的首页 discovery probe，HTTP 200 和响应校验均通过；因此严格说没有“完全没有发起采集”的竞品或品类 lane。

但 42/42 都还不能称为“历史完整采集”：搜索响应仍带有 `pageInfo.endCursor`，本轮只取一页，未继续分页到历史边界，也没有执行 canonical SQLite merge/export。

| 范围 | lane 数 | P0 零旧词法证据 | P1 仅评论旧证据 | P2 仅帖子旧证据 | P3 帖子与评论均有旧证据 | V2 首页有效帖子 ID | 已生成 V2 首屏评论报告 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 竞品 | 17 | 3 | 1 | 0 | 13 | 121 | 120 |
| 品类 | 25 | 6 | 3 | 2 | 14 | 174 | 167 |
| 合计 | 42 | 9 | 4 | 2 | 27 | 295 | 287 |

说明：`旧证据`来自离线词法审计，不等于 canonical 去重行数；`V2 首页有效帖子 ID` 已排除 UUID 形状的伪 Reddit ID；同一帖子可能命中多个 lane，因此不能将各行相加作为帖子总量。

## 当前未完成的采集范围

- P0：竞品 `boppy`、`comfelie`、`wabi baby`；品类 `baby feeding set`、`baby formula maker`、`baby humidifier`、`baby thermometer`、`diaper pail`、`lactation massager`。这些 lane 在旧本地/归档语料中没有词法证据，但 V2 首页已返回有效帖子，必须继续历史分页。
- P1：竞品 `tommee tippee`；品类 `bottle sterilizer`、`colostrum collector`、`white noise machine`。旧语料只有评论命中，没有帖子命中，首屏 discovery 已补出候选，但尚未历史闭合。
- P2：品类 `breast milk chiller`、`wearable breast pump`。旧语料只有帖子命中，评论链路仍需按游标继续验收。
- P3：其余 27 个 lane 已有旧帖子和评论证据，但仍只完成 bounded first page，不代表 2025-01-01 至今完整。

逐 lane 的旧证据、V2 首页返回量、有效帖子 ID 和首屏评论报告数见同目录的 [`competitor-category-history-inventory-20260715.csv`](./competitor-category-history-inventory-20260715.csv)。

## 证据边界

- discovery：42/42 lane，HTTP 200/校验通过 42/42，`provider_attempt_made=true`。
- V2 评论：372 个新帖子首屏报告；按 lane 归属统计时有 287 个有效候选对应到 V2 首屏评论报告，其余候选可能与旧运行重叠或需要继续补采。
- 本盘点没有新发起 Provider 请求；只读读取既有隔离 staging 报告和本地离线 coverage CSV。
- production 未变更；没有 SQLite/canonical merge、Git push 或 DingTalk/live send。
