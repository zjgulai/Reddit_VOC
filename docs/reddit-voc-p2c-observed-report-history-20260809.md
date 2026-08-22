# Reddit VOC P2C 日报、周报、月报生产修复与验收

日期：2026-08-09（Asia/Shanghai）

门禁：`P2C_PASSED_PRODUCTION_ATOMIC_PROMOTION_ROLLBACK_BROWSER_ACCEPTANCE`

## 最终结论

日报、周报、月报历史不可用的问题已经在生产站完成修复。生产执行了候选端口验收、首次原子晋级、真实 previous 回滚和最终重新晋级；最终 Web 容器 healthy、restart count 0。随后以真实浏览器验收日报、周报、月报和洞察页的桌面与 360px 移动端，动态数据请求全部 200、控制台 0 error/0 warning、横向溢出为 0。

当前日报显示北京时间 `2026-08-09`，数据截至 `2026-08-09 07:00`。页面出现的 `2026-08-10` 是明确标注的“周期结束（不含）”，不是报告日期，也不是未来数据。

生产现可选择 38 个历史已观测周期：日报 14、周报 12、月报 12。加上当前周期，选择器分别为 15、13、13 个选项。

机器验收单：`output/audit/2026-08-09/p2c-observed-report-history-acceptance.json`。

## 审计与归因

| 故障面 | 已确认根因 | 本门禁处置 |
| --- | --- | --- |
| 历史报告显示不可用 | 远端/源快照中已有日、周、月历史行，但旧发布合同把“历史报告可读取”错误绑定到“历史采集覆盖已由数据所有者证明完整”；后者为 false 时历史条目被清零 | 分离“已观测历史可读取”和“全量覆盖可证明”两个能力，发布 `historical_observed_calendar_period_unattested` |
| 同环比诚实性 | 有历史行不等于所有历史窗口已经完整采集 | `comparison_contract_proven=false`、`completeness_percent=null`，同环比和趋势继续关闭 |
| 洞察谱系漂移 | 洞察版本原先没有充分绑定报告 manifest，报告历史变化可能产生同版本不同字节 | 洞察版本绑定报告 manifest SHA 前缀，并以精确 public-validation receipt 校验 |
| 历史报告审计失败 | 历史报告缺少统一的不可比较原因 | 38 个历史报告均携带 `historical_collection_coverage_not_owner_attested_complete` |
| 洞察停止渲染 | 新洞察 manifest 与独立审查回执未形成精确 bytes/SHA 对 | 登记精确 manifest 与 receipt，未使用通配 allowlist |

因此，“远端这些日期的数据都采集了”与“页面不可用”并不矛盾：数据存在于源侧，故障发生在发布投影和前端可访问合同层，不是采集器没有这些日期的数据。

## 生产发布身份

| 项 | 最终值 |
| --- | --- |
| Site current | `72f43eeddc6317a19b40ac2f6a9122efd4fc033c29bab1849839b28a63561f80` |
| Site previous | `ce929e99bc162d58a11b582ea4a4850655aaef730f97a83551c90e973add3e70` |
| Data current | `reddit_voc_release_20260809_observed_history_v2` |
| Data previous | `reddit_voc_release_20260809_honest_partial_v2` |
| Data pointer SHA-256 | `a341b7492c739bce7e76964363eeab4cd40a2ebf920fc0ca85468cd6b2882e82` |
| Reports version | `reddit_voc_reports_20260809_v3_1b563267bd6c_history4` |
| Reports manifest SHA-256 | `760316f9ee1b70305c919e0376f4eed76231aabcd7cefa617cf57918d412ed89` |
| Insights version | `reddit_voc_insights_20260809_v3_1b563267bd6c_r5ac954a8e0c7` |
| Insights manifest SHA-256 | `a3d4e5377d878219e377520f4fa87553226e13465dca075035fe8c225b1f8705` |
| Web container | `5f083c38...004589`，healthy，restart count 0 |

数据截至为 `2026-08-08T23:00:00Z`，即北京时间 `2026-08-09 07:00`。当前日报日期为 `2026-08-09`；报告索引的 `2026-08-10` 使用半开区间结束日期语义。

## 原子晋级与回滚证明

生产合同 SHA-256 为 `fe8dbd98c61f2c28108614c6c075364bb6efe45cbeb2d3c91c6900011e769a26`，远端回执为 `/opt/reddit-voc-insights-site/runtime/p2c-final-fe8dbd98c61f2c28.json`，本地只读副本为 `tmp/reddit-voc-v3/p2c-production-20260809/remote-p2c-final-receipt.json`，回执 SHA-256 为 `e8da2fdedd07375be5922db7fd037259125bdb07693d923284dcd3a752ed51e7`。

执行序列：

1. 候选容器在 18341 端口通过 13 路由、数据指针、CSS、sidecar 与 38 个历史 artifact digest 核验。
2. 首次晋级新 Site/Data，通过公开读回。
3. 真实回滚至 `ce929...` / `honest_partial_v2`，通过公开读回。
4. 最终重新晋级 `72f43...` / `observed_history_v2`，通过公开读回。
5. Compose SHA、共享 Nginx、四个受保护容器的身份和 restart count 均未漂移。

发布只变更受控 Site/Data release、current/previous 指针和 Web 容器；没有数据库写入、供应商调用、采集器或调度器变更、钉钉或其他 live send、共享 Nginx/TLS/DNS 变更，也没有替换或重启受保护服务。

## 测试与页面验收

- Python：1913 passed，881 subtests passed。
- 前端：46 files passed，225 tests passed，46 skipped。
- TypeScript 与 Vite production build：通过。
- Lint：退出码 0；保留 15 条既有 hooks/Fast Refresh warning。
- 公开历史 artifact：38/38 HTTP 200 且 digest 精确匹配。
- 日报：当前 `2026-08-09`；当前 + 14 个历史选项；历史深链可读取。
- 周报：当前 `2026-08-03 至 2026-08-09`；当前 + 12 个历史选项；历史深链可读取。
- 月报：当前 `2026-07`；当前 + 12 个历史选项；历史深链可读取。
- 洞察：数据口径、用户画像、季度洞察与证据模块正常加载。
- 桌面 1200px 与移动 360px：报告及洞察页面横向溢出均为 0；console error/warning 均为 0。

关键截图：

- `output/playwright/p2c-production-20260809/reports-daily-current-desktop.png`
- `output/playwright/p2c-production-20260809/reports-weekly-history-desktop.png`
- `output/playwright/p2c-production-20260809/reports-monthly-history-desktop.png`
- `output/playwright/p2c-production-20260809/insights-desktop.png`
- `output/playwright/p2c-production-20260809/reports-daily-mobile-360.png`
- `output/playwright/p2c-production-20260809/reports-weekly-mobile-360.png`
- `output/playwright/p2c-production-20260809/reports-monthly-mobile-360.png`
- `output/playwright/p2c-production-20260809/insights-mobile-360.png`

## 诚实性边界与后续 TODO

本门禁解决的是“已存在的历史数据无法从日报、周报、月报读取”，不是对历史全量采集完整性的重新认证。

当前最新源快照仍为 `partial`，有 5 个 unresolved continuations；数据所有者尚未证明历史采集 100% 完整。因此：

1. 已观测历史报告可以读取。
2. 完整率继续显示未知，不伪造百分比。
3. 同比、环比与历史趋势结论继续保持关闭。
4. 下一独立门禁应补齐 continuation 身份链和 owner attestation，再决定是否开放比较合同。
5. 应把 collect → source receipt → 七类投影 → candidate → promotion decision 固化为每日 fail-closed 自动闭环，避免再次出现“采集已成功但发布指针未前进”。
6. 15 条既有 lint warning 可在独立低风险门禁中清理，不与本次生产修复混合。
