---
title: Momcozy Reddit P0 竞品与品类采集进度
date: 2026-07-15
---

# Momcozy Reddit P0 竞品与品类采集进度

本记录只统计本轮 P0 lane：`boppy`、`comfelie`、`wabi baby`、`baby feeding set`、`baby formula maker`、`baby humidifier`、`baby thermometer`、`diaper pail`、`lactation massager`。

## 只读汇总

- discovery：9 个首页报告 + 159 个 continuation 报告；全部 HTTP 200、响应校验通过。
- 搜索 raw ID 并集：876 个，其中 844 个通过 Reddit ID 形状校验；32 个非 Reddit 形状 ID 不进入评论采集。跨 lane 重叠已保留，不能把各 lane 行数相加。
- 首屏评论：844 份有效帖子报告，838 份校验通过、6 份 fail-closed，解析 3,985 条评论，产生 555 个 `More`；有效帖子首屏评论缺口为 0。6 份失败均为 Provider 无法解析的 source-only numeric ID，不纳入重试。
- 回复：P0 相关报告 821 份，全部校验通过，解析 3,921 条评论，产生 572 个 `More`；当前候选 accounting 仍有 279 个未处理游标。
- 本批新增评论/回复 binding 均为 `provider_invocation_limit=1` 且 `provider_call=true`，forbidden flags 全为 false；没有 production merge、Git push 或 DingTalk/live send。

## lane 终点

| lane | continuation 深度 | 最新页 `hasNextPage` | 结论 |
|---|---:|---:|---|
| boppy | 33 | false | 当前搜索分页终止 |
| comfelie | 2 | false | 当前搜索分页终止 |
| wabi baby | 2 | false | 当前搜索分页终止 |
| baby feeding set | 9 | false | 当前搜索分页终止 |
| baby formula maker | 17 | false | 当前搜索分页终止 |
| baby humidifier | 8 | false | 当前搜索分页终止 |
| baby thermometer | 24 | false | 当前搜索分页终止 |
| diaper pail | 33 | false | 当前搜索分页终止 |
| lactation massager | 31 | false | 当前搜索分页终止 |

`hasNextPage=false` 只表示该 lane 当前 Provider 分页终止，不代表已经完成 canonical 去重、评论树闭合或 SQLite merge。当前搜索分页已全部终止；6 份评论响应已分类为不重试的 source-only ID，279 个回复游标仍必须新建 packet 后再继续。
