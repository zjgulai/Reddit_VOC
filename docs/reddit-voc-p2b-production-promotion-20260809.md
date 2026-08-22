# Reddit VOC P2B 生产原子晋级与 UI 热修验收（2026-08-09）

## 结论

**门禁：`P2B_PASSED_PRODUCTION_PROMOTION_ROLLBACK_BROWSER_ACCEPTANCE`**

生产站已完成数据/UI 协调晋级、previous 回滚证明、最终重新晋级和独立浏览器验收。当前八个工作台页面显示北京时间 `2026-08-09`，数据截至 `2026-08-09 07:00`；不再显示 `2026-07-23`。13 条公开路由在桌面 1440px 与移动 360px 下均返回 200，无横向溢出、console error、page error 或 request failure。

机器回执：`output/audit/2026-08-09/p2b-production-ui-hotfix-acceptance.json`。

## 归因闭环

| 故障面 | 已确认根因 | 本门禁处置 |
| --- | --- | --- |
| 日期陈旧 | 07:00 采集持续成功，但生产 data pointer 仍消费 7 月 release；不是日期组件写死，也不是 8 月数据未采集 | 晋级 `reddit_voc_release_20260809_honest_partial_v2`，公开 pointer SHA 与候选一致 |
| UI 全站失真 | 旁路镜像发布了仍含 `@tailwind` 的 2,033-byte CSS，工具类未编译 | 使用标准 Vite/PostCSS/Tailwind 构建，CSS 62,907 bytes，并以 CSS 语义门禁拒绝原始指令 |
| 发布控制分裂 | 实际 unified Compose 镜像与受控 site release pointer 不一致 | 将 Web 镜像、site current/previous 和 data current/previous 纳入同一受控事务 |
| 报告移动端溢出 | completeness card 的 flex child 缺少 `min-width: 0`，长下划线原因码不可折行 | 增加 `min-w-0` 与 `break-words`，补回归测试并重新执行 UI-only 原子晋级/回滚 |

## 生产终态

| 项 | 最终值 |
| --- | --- |
| UI current | `ce929e99...add3e70` |
| UI previous | `5d13a7f6...17fe928` |
| Data current | `reddit_voc_release_20260809_honest_partial_v2` |
| Data pointer SHA | `7598e310...14cab9` |
| 数据截至 | `2026-08-08T23:00:00Z` / 北京时间 `2026-08-09 07:00` |
| Web | healthy，restart count 0，Compose project `reddit_voc_unified` |
| 原子晋级回执 | `668e2ddb...dba40` |
| UI 热修回执 | `a5a3363c...659cc` |

两次生产事务都执行了“候选晋级 → previous 回滚 → 最终重新晋级”。最终只读回读确认 Compose、共享 Nginx 配置、数据指针和四个受保护容器均未漂移；API、站点应用、翻译服务和共享 Nginx 没有替换或重启。

## 页面验收

验收路由：`/`、`/dashboard`、`/dashboard/reports`、`/dashboard/analytics`、`/dashboard/insights`、`/dashboard/search`、`/dashboard/ugc-showcase`、`/dashboard/messages`、`/dashboard/settings`、`/features`、`/how-it-works`、`/faq`、`/cases`。

- 桌面 1440px：13/13 HTTP 200，横向溢出 0，浏览器错误 0。
- 移动 360px：13/13 HTTP 200，`scrollWidth=clientWidth=360`，浏览器错误 0。
- 八个数据工作台页面：全部出现 `2026-08-09`，全部不出现 `2026-07-23`，并继续揭示 partial/完整性未证明语义。
- 报告移动端最终截图：`output/playwright/p2b-20260809/reports-mobile-final.png`。
- 洞察移动端最终截图：`output/playwright/p2b-20260809/insights-mobile-final.png`。

## 诚实边界与剩余 TODO

当前最新采集是“新鲜但部分覆盖”：11 个 full、5 个 partial、5 个 continuation 未解析。历史采集完整性没有数据所有者证明，所以同环比、历史趋势和完整率继续关闭。本门禁不能被解释为 100% 覆盖或全历史可用。

后续按优先级执行：

1. P0：把 collect → source receipt → 七类投影 → candidate → promotion decision 固化为每日 fail-closed 闭环，并分别告警“采集成功但未发布”。
2. P0：把 13 路由双视口、CSS 语义、日期/partial 语义和 rollback proof 设为每次生产晋级的强制门禁。
3. P1：收敛两个可能共写 SQLite 的 API runtime，明确唯一 writer；这需要独立生产授权，本门禁未执行。
4. P1：补 continuation 与 6,953 条未关联评论的身份链，同时保持未解析数据不进入公开事实。
5. P1：获取 owner attestation 后再决定是否开放历史入口、同环比和方向结论；不得以代码常量绕过。
6. P2：清理 15 条既存 lint warning，并将浏览器结果、截图和视觉阈值生成版本化 E2E receipt。

## 副作用声明

浏览器验收和 UI 热修阶段没有数据库写入、供应商调用、采集器/cron/systemd 变更、钉钉或其他 live send、共享 Nginx/TLS/DNS 变更，也没有重启或替换受保护服务。
