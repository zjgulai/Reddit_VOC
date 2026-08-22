# Reddit VOC P1 远端只读归因审计（2026-08-09）

## 1. 门禁结论

**决策：`P1_PASS_ROOT_CAUSE_IDENTIFIED_P2_NOT_ADMITTED`**

用户判断正确：远端并没有停在 7 月 23 日。生产采集从 8 月 4 日到 8 月 9 日连续运行，最新闭合窗口为 `2026-08-07T23:00:00Z` 至 `2026-08-08T23:00:00Z`，即北京时间 8 月 8 日 07:00 至 8 月 9 日 07:00。

页面仍显示 `2026-07-23` 的直接原因是：

1. 07:00 采集和 08:00 日报链路在工作；
2. 采集后的 canonical/source snapshot、七类公开投影和 data release candidate 没有继续生成；
3. 生产数据指针仍指向 7 月 24 日发布包，包内 `data_as_of_utc` 仍是 `2026-07-22T23:00:00Z`；
4. 8 月 8 日又通过一套旁路 Compose 替换了前端容器，但没有通过受控站点发布指针，也没有更新数据发布；
5. 该旁路前端构建把未编译的 Tailwind 指令直接发布，导致全站样式工具类缺失。

因此根因不是单点，而是两个相互独立的 P0 断层：

- **数据断层：采集成功，但采集到发布之间没有运行中的日更闭环。**
- **UI 断层：前端容器被旁路替换，且 CSS 构建产物无效。**

本轮证据等级为 **L3 production read-only**。没有执行远端写入、供应商调用、补采、候选构建、容器变更、计划任务变更、发布切换或消息发送。

## 2. 事实、推断与未知

### 2.1 已确认事实

| 证据面 | 当前远端事实 |
| --- | --- |
| 观察时间 | 2026-08-09 13:55–14:02 CST |
| cron | `active`、`enabled`，主机时区 `Asia/Shanghai` |
| 采集计划 | 每日 07:00 执行 `server_daily_collect.sh` |
| 日报计划 | 每日 08:00 执行 `server_daily_report_bounded.sh` |
| 数据发布计划 | 没有已安装的 `reddit-voc` systemd service/timer；cron 也没有 candidate build/promotion |
| 最新采集批次 | `daily_collect_20260809_0700` |
| 最新闭合窗口 | `2026-08-08T23:00:00Z`，即 `2026-08-09 07:00 CST` |
| 数据库健康 | `integrity_check=ok`、外键违规 0、无 WAL/SHM/journal sidecar |
| 数据库只读身份 | 查询前后 SHA 和 stat 完全一致 |
| 当前数据库 SHA | `e6d7ca479d87e89889315aad9db00f0145d1c91d754f797bd072532f2843bed6` |
| 当前数据规模 | 43 runs、42 raw captures、440 threads、1818 comments、2258 analyses、146 delivery previews |
| 生产 data pointer | `reddit_voc_release_20260724_dashboard_fix_v1` |
| 生产数据截至 | `2026-07-22T23:00:00Z`，即 `2026-07-23 07:00 CST` |
| public/remote pointer 对账 | public response 与远端 current 文件 SHA 均为 `bc715e35...f382ca` |
| 受控 UI release pointer | 仍为 7 月发布 `8a8a5a01...5eded` |
| 实际运行 UI image | 8 月 8 日旁路镜像 `f3de7431...889` |
| 实际 UI 编排 | `/opt/reddit-voc-unified/docker-compose.yml`，不属于受控 release pointer |
| 生产 CSS | 2,033 bytes，仍含 `@tailwind`，无 `.flex/.grid/.hidden` 工具类 |
| 本地 P0 合格 CSS | 62,907 bytes，无 `@tailwind`，包含工具类，约 1,001 个规则块 |
| 全路由影响 | 13 个公开路由全部引用同一坏 CSS 和同一 JS |

### 2.2 有证据支持的归因

#### A. 采集层没有停摆

8 月 3 日历史 L3 快照中，数据库有 37 个 run、343 条 thread、1431 条 comment、1756 条 analysis。当前只读快照分别增长为 43、440、1818、2258；新增量与 8 月 4–9 日六个日批次一致。

#### B. 发布层没有消费采集结果

远端 data release 目录只有 7 月 23 日和 7 月 24 日两个 release。`current` 自 7 月 25 日后未切换。8 月 4–9 日存在完整的采集导出和日报文件，但不存在对应 site snapshot、canonical、insights、reports、personas 或统一 current-release candidate。

#### C. 8 月 3 日候选链停在“传输”，不能继续复用

- v14 包已解压，但执行脚本仍把 `WORK` 绑定到 v13，验收因此 fail closed；没有 stdout/stderr、build receipt 或 candidate manifest。
- v15 修正版 tar 已传到远端，远端 SHA 与本地一致，但目录中只有一个 tar；没有解压、执行或 candidate。
- v15 绑定的是 8 月 3 日数据库 SHA `180854ff...0595be` 和 8 月 2 日窗口。当前数据库已经是 `e6d7ca47...3bed6`，所以现在执行 v15 会主动回放过时输入，必须禁止。

#### D. UI 灾难性渲染的即时技术原因已经确定

生产 CSS 保留了原始 `@tailwind base/components/utilities`，说明 Tailwind/PostCSS 没有在构建阶段生效。浏览器不会把这些构建指令展开为布局工具类，因此 JSX 中大量 Tailwind class 没有任何样式，造成全站排版、间距、网格、显隐和响应式能力同时失效。

生产容器内 CSS 与公网 CSS SHA 完全一致，排除 CDN 或浏览器缓存单独损坏。13 个路由都引用同一文件，所以不是 `/dashboard` 单页问题。

#### E. UI 发布控制面发生 split-brain

受控目录 `/opt/reddit-voc-insights-site/current` 仍指向 7 月 release；实际运行容器却来自 `/opt/reddit-voc-unified` 的 8 月镜像。受控 release 目录中不存在该镜像的 release manifest、dist checksums 或回滚绑定。因此当前生产状态无法由受控指针完整重放或回滚。

### 2.3 尚不能唯一归因的事项

1. 没有 f3de 镜像对应的受控 build receipt，因此只能确认 PostCSS 未生效，不能从当前证据唯一断言是 `postcss.config.js` 缺失、构建 cwd 错误，还是使用了绕过标准脚本的命令。
2. 数据库在 09:33:49 CST 有一次额外修改，旧 API 容器在 09:34:36 CST 启动；两者时间相关，但不能据此断言容器启动导致数据库变更。
3. 远端同时运行两个 API 容器，均以 read-write 方式挂载同一个 SQLite 目录。当前没有 sidecar 或活动句柄，但无法从只读快照证明过去不存在并发写竞争。

## 3. 8 月 4–9 日采集逐日对账

| 北京批次 | UTC 窗口结束 | threads | comments | analyses | full / partial | 状态 |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| 2026-08-04 07:00 | 2026-08-03 23:00 | 19 | 57 | 76 | 15 / 4 | partial |
| 2026-08-05 07:00 | 2026-08-04 23:00 | 11 | 60 | 71 | 7 / 4 | partial |
| 2026-08-06 07:00 | 2026-08-05 23:00 | 15 | 32 | 47 | 13 / 2 | partial |
| 2026-08-07 07:00 | 2026-08-06 23:00 | 21 | 102 | 123 | 15 / 6 | partial |
| 2026-08-08 07:00 | 2026-08-07 23:00 | 15 | 62 | 77 | 12 / 3 | partial |
| 2026-08-09 07:00 | 2026-08-08 23:00 | 16 | 74 | 90 | 11 / 5 | partial |

六个批次 raw capture 均为 `tikhub / browser_status=ok`，collector 自身 issue 数为 0。`partial` 来自部分帖子评论覆盖不完整，不等于采集任务失败。候选和页面必须继续诚实展示 coverage=partial，不能把“日期已更新”解释成“数据完全覆盖”。

## 4. MECE 能力图谱与当前状态

| 能力域 | 组件/证据 | 当前能力 | 当前状态 |
| --- | --- | --- | --- |
| 调度 | cron 07:00 / 08:00 | 能按日触发采集和日报 | 正常 |
| 源采集 | Tikhub collector | 连续写入帖子、评论、分析 | 正常但 coverage partial |
| 数据库存储 | SQLite | 完整性、外键和只读身份可验证 | 健康，但存在双 RW runtime 风险 |
| 日报派生 | HTML/CSV/XLSX/PNG/summary | 每日 08:00 生成 | 正常 |
| canonical/source snapshot | v3 build scripts | 仓库有能力，8 月 3 日后无成功运行 | 停滞 |
| 公开投影 | base/personas/insights/reports/brand/quarter/casebook | 仓库有构建和校验能力 | 未消费最新 source |
| data release candidate | manifest/validation/current pointer | 有受控发布协议 | 没有新候选 |
| data promotion | current/previous symlink | 支持原子指针 | 停在 7 月 |
| 前端本地构建 | Vite + Tailwind + P0 时间语义 | 本地测试、lint、build 通过 | 合格候选，未上线 |
| 前端生产构建 | f3de image | JS 可加载 | CSS 构建失败 |
| 前端发布控制 | insights-site release pointer | 有受控 manifest/rollback 协议 | 被 unified Compose 旁路 |
| 页面日期语义 | P0 `ReleaseTemporalContext` | 本地可区分 now/data-as-of/integrity/recency/coverage | 生产未上线 |
| 观测与告警 | status/issue summary、shadow 配置 | 部分存在 | 无端到端发布 attempt receipt |
| 回滚 | current/previous + site release | 协议存在 | 当前旁路镜像不在受控回滚链 |

## 5. 页面影响面

### 5.1 日期影响

八个数据工作台页面继续消费同一 7 月 `current-release.json`，所以 Dashboard、Reports、Search、Analytics、Insights、UGC、Messages、Settings 均不可能显示 8 月 9 日数据截至。正确的新候选应显示：

- 当前北京时间：实时墙钟；
- 最新发布数据截至：`2026-08-09 07:00 CST`；
- collector run：`daily_collect_20260809_0700`；
- coverage：partial；
- integrity：verified；
- recency：按 07:00 日切和 90 分钟 SLO 计算。

不得把墙钟 `2026-08-09 14:xx` 伪装成数据截至；正确日期来自最新闭合窗口。

### 5.2 UI 影响

以下 13 个路由均返回 200，但引用同一个无效 CSS：

`/`、`/dashboard`、`/dashboard/reports`、`/dashboard/analytics`、`/dashboard/insights`、`/dashboard/search`、`/dashboard/ugc-showcase`、`/dashboard/messages`、`/dashboard/settings`、`/features`、`/how-it-works`、`/faq`、`/cases`。

HTTP 200 只能证明静态文件可达，不能证明 UI 可用。本次事故说明现有健康检查缺少 CSS 语义和真实页面渲染门禁。

## 6. 脆弱点优先级

### P0

1. **采集与发布完全解耦但没有滞后告警**：源数据连续增长，公开站点可停滞数周。
2. **旁路 UI 发布**：运行容器与受控 release pointer 不一致，无法证明构建、晋级和回滚链。
3. **CSS 构建无 fail-closed**：原始 `@tailwind` 仍可进入生产，HTTP/容器健康检查全部误报绿色。

### P1

1. **双 API runtime 共写 SQLite**：`reddit_voc_api` 和 `reddit_voc_site_app` 同时 RW 挂载 `/opt/reddit-voc-site/data`。
2. **全量候选不是每周期不可变产物**：v14/v15 依赖一次性路径和手工门禁，任一步中断就没有日后自愈。
3. **所有 run 都是 partial**：虽然不是失败，但当前发布门禁需要明确允许/拒绝阈值，不能默认为完整。
4. **数据库额外修改缺少 actor receipt**：09:33 操作没有可归因 attempt receipt。
5. **共享主机监控噪声**：`voc-labeling-continuous-monitor.service` 每分钟因 `DEAD_LETTER_INCREASE`、`PROVIDER_UNKNOWN_INCREASE` 返回 2 并被 systemd 标记 failed；尚无证据证明影响 Reddit VOC，但会制造持续失败噪声。

### P2

1. `/opt` 所在文件系统使用率约 81%，虽仍有约 50 GB 空闲，但需要发布前容量门禁和清理策略。
2. `config/systemd/reddit-voc-data-shadow.*` 只在仓库存在，远端未安装；且它只验证预先存在的 candidate，不负责构建 candidate。

## 7. 最终恢复方案

### P2A：冻结当前源并构建全投影候选（下一门禁）

1. 在无 active SQLite sidecar/handle、身份前后稳定的条件下，获取当前远端源快照到隔离本地候选；不调用供应商、不改远端。
2. 绑定 `daily_collect_20260809_0700`、窗口 `2026-08-08T23:00:00Z` 和当前 source SHA；不得执行过时 v15。
3. 从同一个 canonical center 重建 base、personas、insights、reports/history、brand health、quarter insights；casebook 保持独立静态节奏并显式绑定。
4. 构建单一 `current-release.json`，把 data-as-of、collector run、coverage、版本、哈希、计数和中心快照一次性绑定。
5. 使用 P0 本地时间语义运行全量测试、构建和 13 路由浏览器验收；此阶段不部署。

### P2B：补上 UI 构建 fail-closed

1. 在 `audit_insights_dist.py` 增加 CSS 语义门禁：任一发布 CSS 含 `@tailwind` 即拒绝；必须存在关键工具类和足够的规则集合。
2. 构建 receipt 绑定 `postcss.config.js`、`tailwind.config.js`、lockfile、Node/npm 版本和最终 CSS SHA/bytes/selector count。
3. 容器 smoke 除 HTTP 200 外，必须回读 CSS 并验证无原始构建指令，再运行真实浏览器布局断言与截图对比。

### P3：统一拓扑并原子晋级

1. 在写入前选择唯一受控编排：要么迁移 unified 到 release pointer 协议，要么移除旁路；禁止两套控制面并存。
2. 选择唯一 API writer。另一容器必须停止或改为不挂载生产 SQLite；动作需要单独生产授权。
3. 同一晋级事务绑定 UI release、data release、compose/image、current/previous 和 rollback receipt。
4. 生产回读：13 路由、CSS/JS SHA、`current-release.json` SHA、数据截至 `2026-08-09 07:00 CST`、全页面三轴状态和关键截图。

### P4：建立日更闭环

1. 07:00 collect 只负责源数据；完成后生成不可变 source receipt。
2. 07:10–08:10 candidate builder 消费最新 source receipt，生成全投影候选和终态 receipt。
3. 先运行至少两个 shadow 周期；promotion 初期保持人工授权。
4. 告警分别覆盖：无采集 attempt、采集失败、无 candidate、candidate 失败、无 promotion decision、生产 pointer 回读不一致。
5. 每次 UI 构建和数据发布必须可独立回滚，但生产展示只接受相互兼容的一对版本。

## 8. P1 验收与禁止声明

### supported_claims

- 远端 8 月 4–9 日采集连续存在，最新数据窗口属于北京时间 8 月 9 日。
- 页面日期停在 7 月的主因是发布链断开，不是源采集缺失。
- 8 月 3 日 v14/v15 没有形成可晋级 candidate，v15 现在已经输入过时。
- 生产全路由 UI 故障由未编译 Tailwind CSS 直接造成。
- 运行 UI 容器与受控 UI release pointer 不一致。

### forbidden_claims

- 不能声称 8 月 4–9 日采集 coverage complete；它们均为 partial。
- 不能声称 8 月 9 日全投影候选已经构建。
- 不能声称 production pointer、UI 或日期已经修复。
- 不能声称 v15 可以安全继续执行。
- 不能声称本轮执行了部署、重启、消息发送或任何远端写入。

## 9. 下一门禁的精确边界

下一门禁应是 **P2A：远端只读源快照导出 + 本地无供应商全投影候选构建**。

允许：只读获取当前生产源、在本地隔离目录构建、增加本地 CSS fail-closed、运行测试/浏览器验收。

不允许：远端解压/执行 v15、生产数据库写入、供应商调用、容器停止/重启、cron/systemd 变更、data/UI pointer 切换、部署或消息发送。
