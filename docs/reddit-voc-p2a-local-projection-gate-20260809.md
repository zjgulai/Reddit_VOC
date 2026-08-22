# Reddit VOC P2A 本地全投影候选门禁（2026-08-09）

## 1. 门禁结论

**决策：`P2A_BLOCKED_FULL_PROJECTION_NOT_ADMITTED`**

远端确实已经采集到北京时间 2026-08-09，但当前仍不能安全生成或切换新的 `current-release`。本门禁完成了只读源冻结、核心数据链构建、三项本地代码修复、CSS fail-closed、13 路由浏览器检查和全量回归；全投影在 periodized metrics 入口按设计 fail closed。

页面仍显示 `2026-07-23` 的直接原因已经最终厘清：前端日期算法没有把日期写死，它读取 `current-release.freshness.data_as_of_utc`；当前发布仍绑定 `2026-07-22T23:00:00Z`，即北京时间 2026-07-23 07:00。新源的正确“数据截至”应为 `2026-08-08T23:00:00Z`，即北京时间 2026-08-09 07:00，而不是页面打开时的墙钟时间。

阻止本次继续生成全投影的主门禁是：仓库只有绑定 7 月 23 日 center 的 100% 数据所有者覆盖证明；它与新 center `reddit_voc_center_20260809_v3_canonical_v2` 不匹配。与此同时，Base Public 构建器和它的验证器都未经证明地硬编码 `completeness_percent=100` 与 `data_owner_declaration`。因此，即使该 Base 技术验证返回通过，也不能作为可信发布输入，本次明确不予准入。

本轮证据等级为 **L3 remote source freeze + L2 local candidate**。没有远端写入、供应商调用、数据库写入、容器重启、计划任务变更、部署、指针切换或消息发送；生产保持不变。

## 2. 日期为什么没有更新

日期链路是：

`远端采集窗口结束` → `canonical center` → `全套公开投影` → `current-release.freshness.data_as_of_utc` → `页面“发布数据截至”`

当前各节点状态如下：

| 节点 | 当前证据 | 结论 |
| --- | --- | --- |
| 远端采集 | `daily_collect_20260809_0700`，窗口结束 `2026-08-08T23:00:00Z` | 8 月 9 日日期已存在 |
| 本地 canonical | 新 center 已构建并验证 | 通过 |
| 公开投影 | 只可靠走到 personas；metrics 起被覆盖证明门禁拒绝 | 不完整 |
| 新 current-release | 未生成 | 不存在 |
| 当前 UI release | `reddit_voc_release_20260723_daily_v2`，`data_as_of_utc=2026-07-22T23:00:00Z` | 页面显示 7 月 23 日是正确回读旧发布 |
| 前端日期逻辑 | 区分当前北京时间、数据截至、预期闭合周期、recency、coverage | 逻辑正确，不应改成直接显示今天 |

所以，“远端有今天的数据”只证明 source 层已经更新，不能自动改变页面。页面只有在一套彼此绑定并通过门禁的公开投影及 `current-release` 被生成、审计和晋级后才能显示 8 月 9 日。

## 3. 远端源冻结结果

远端只读前检、后检和本地副本三者一致：

| 项目 | 值 |
| --- | --- |
| 远端路径 | `/opt/reddit-voc-site/data/reddit_voc_daily.sqlite3` |
| SHA-256 | `e6d7ca479d87e89889315aad9db00f0145d1c91d754f797bd072532f2843bed6` |
| bytes | 2,318,336 |
| SQLite integrity | `ok` |
| 外键违规 | 0 |
| WAL/SHM/journal sidecar | 无 |
| 最新 run | `daily_collect_20260809_0700` |
| 最新 run 状态 | `partial` |
| 最新 run 数量 | 16 threads、74 comments、90 analyses |
| 最新 run 覆盖 | 11 full、5 partial |
| 数据库总量 | 43 runs、42 raw captures、440 threads、1818 comments、2258 analyses、146 previews |

这证明“8 月日期的数据已采集”。它不证明评论覆盖 100%，也不等价于一份绑定新 center 的数据所有者完整性声明。

## 4. 本地候选执行结果

### 4.1 已通过并可复核的层

| 能力层 | 状态 | 关键计数/证据 |
| --- | --- | --- |
| V2 center + canonical | passed | 3,836 posts；28,522 stored comments；21,569 linked；6,953 unresolved；0 quarantine |
| Base Public | 技术验证 passed，但门禁不准入 | 产物错误声明 100% owner completeness，未绑定证明 |
| VOC facts | passed | 25,284 VOC；3,757 post VOC；21,527 comment VOC；1,238,916 eligibility rows |
| 自动化排除 | passed | 881 automation VOC 被排除 |
| Governed signals | passed/promotable | 175,802 facts；16,613 promoted；159,188 held；1 rejected |
| Personas | passed/promotable | 82 atomic；8 cohorts；25,995 persona facts；10,553 assignments |
| Periodized metrics | blocked fail closed | `coverage attestation dataset mismatch` |
| Insights / Reports / Brand / Quarter | 未构建 | 上游覆盖门禁未通过 |
| Coordinated current-release | 未构建 | 七类投影没有形成一致发布包 |

Base Public 的“不准入”非常重要：技术 validator 与 builder 使用了同一个错误常量，所以“validator passed”是相关性验证，不是独立覆盖证明。

### 4.2 三项已执行的代码修复

1. Baseline bridge 现在只接受严格配对的 canonical v1+receipt v1 或 v2+receipt v2；混合版本继续 fail closed。
2. V2 orchestrator 在消费 baseline source batch 后立即登记 baseline bridge，再消费后续增量，修复真实日更链的顺序错误。
3. 静态发布审计现在解析 HTML 中的本地 CSS，并拒绝原始 `@tailwind/@apply`、缺失 CSS、外部或可变 URL，以及缺少 `.flex/.grid/.hidden` 的构建产物。

这些修复均由新增回归覆盖；全量 Python 测试结果为 `1908 passed, 881 subtests passed`。

## 5. UI/CSS 门禁结果

隔离标准构建使用当前已审核的 7 月公开数据，只用于验证 UI 与 CSS，不作为 8 月数据发布证据。

| 项目 | 结果 |
| --- | --- |
| 前端测试 | 223 passed、46 skipped |
| lint | 通过，有既存 warnings |
| TypeScript + Vite | 通过 |
| dist public projection audit | 两次通过 |
| CSS | 62,907 bytes，SHA `487ab6d0...d270` |
| 原始 Tailwind 指令 | 0 |
| 核心布局类 | `.flex`、`.grid`、`.hidden` 均存在 |
| 浏览器路由 | 13/13 加载成功 |
| console error | 0 |
| 桌面与移动布局 | 视觉复核通过 |

检查路由为：`/`、`/dashboard`、`/dashboard/reports`、`/dashboard/analytics`、`/dashboard/insights`、`/dashboard/search`、`/dashboard/ugc-showcase`、`/dashboard/messages`、`/dashboard/settings`、`/features`、`/how-it-works`、`/faq`、`/cases`。

隔离页面正确区分“当前北京时间”和“发布数据截至”，并诚实显示旧发布为 7 月 23 日、coverage partial、chain stalled。这说明日期语义与修复后的页面渲染均正确；缺的是新的可信数据发布，不是把页面日期替换成 `new Date()`。

## 6. MECE 能力图谱

| 能力域 | 已具备能力 | 当前状态 | 缺口 |
| --- | --- | --- | --- |
| 调度/采集 | 07:00 日采集，08:00 日报 | 远端连续运行 | 与发布编排没有闭环 |
| 源身份 | SQLite 完整性、FK、sidecar、前后 SHA 可验证 | 通过 | 应自动形成不可变 source receipt |
| Center/canonical | 基线+增量融合、冲突/未解析账本、独立验证 | 本地通过 | 需要 reviewed daily profile |
| 隐私 Base | 作者/敏感信息抑制、公开投影 | 技术产物存在但不准入 | completeness 必须绑定证明 |
| VOC facts | 分析就绪、eligibility、自动化排除 | 本地通过 | 6,953 unresolved 继续 ledger-only |
| Governed signals | promoted/held/rejected 治理 | 本地通过 | 无日更入口 |
| Personas | atomic/cohort/facts/assignment | 本地通过 | 无日更入口 |
| Periodized metrics | 窗口、对比、覆盖证明校验 | 正确 fail closed | 缺 8 月 exact attestation 或 partial 合约 |
| Insights/reports | 构建与独立验证代码存在 | 本轮未到达 | 依赖 metrics 与覆盖证明 |
| Brand/quarter | 派生投影代码存在 | 本轮未到达 | 依赖一致上游 |
| Current release | 七类数据集、freshness、SHA 一次性绑定 | 当前仍是 7 月 | 缺完整 8 月候选 |
| UI 时间语义 | now / data-as-of / expected period / status 分离 | 通过 | 生产仍消费旧 release |
| UI 构建 | Vite/Tailwind、dist allowlist | 本地通过 | 生产旁路尚未治理 |
| UI 发布门禁 | 新 CSS 语义 fail-closed | 已补本地代码 | 尚未进入受控生产链 |
| 浏览器验收 | 13 路由、桌面/移动截图 | 本地通过 | 应固化为自动 E2E receipt |
| 生产拓扑/回滚 | 历史上有 current/previous 协议 | 本轮未触碰 | 旁路 Compose split-brain 仍存在 |

## 7. 脆弱点与优先级

### P0

1. **Base 完整性伪证明**：builder 未接收 coverage attestation，却硬编码 100% 和 data-owner declaration；validator 再验证同一常量，形成相关性绿灯。
2. **采集到发布无受控日更编排**：远端数据增长不触发 canonical、七类投影或 current-release，页面可长期静默停滞。
3. **生产 UI 控制面 split-brain**：P1 已确认运行镜像绕过受控 release pointer；本轮只修了本地审计，没有修改生产。

### P1

1. **覆盖证明没有按 snapshot/window 自动绑定**：当前唯一可用声明属于 7 月 23 日，不能复用于 8 月 9 日。
2. **最新采集为 partial**：16 个 thread 中 5 个为 partial；发布必须区分“日期存在”“采集 attempt 完成”“历史可比较性已证明”。
3. **6,953 条 unresolved parent comments**：不会进入公开 facts，但会持续影响评论语义覆盖。
4. **无 reviewed orchestration profile/contract**：仓库只有 materializer 和脚本，缺一份可重复、可审计的日更参数契约。
5. **历史 baseline 兼容与登记顺序脆弱**：本轮已经修复，但尚未形成真实日更 shadow 证据。

### P2

1. 前端 lint 仍有 hooks dependency 与 Fast Refresh warnings；不阻断当前构建，但应进入质量债务清单。
2. 13 路由检查目前是一次性 CLI 证据，尚未变成发布脚本必跑的布局/console/截图回执。
3. CSS 门禁只验证三个核心工具类；后续应加入页面级关键布局断言和视觉基线阈值。

## 8. 下一门禁方案

推荐下一门禁为 **P2A.1：覆盖语义修复 + 8 月完整本地协调候选**，仍然不部署。

执行顺序：

1. 修改 Base builder/validator：必须接收并绑定 exact coverage evidence 的文件 SHA、dataset id、source snapshot id、窗口和声明主体；禁止硬编码 `100/data_owner_declaration`。
2. 二选一建立真实覆盖语义：
   - 若数据所有者能够确认完整性：提供绑定 `reddit_voc_center_20260809_v3_canonical_v2` 与截止 2026-08-09 的 100% 声明；
   - 若只能证明日期已采集：建立 `partial / comparison unavailable` 合约，允许描述性当期指标，但所有环比、趋势和历史完整性声明必须显示不可用。
3. 新增 reviewed orchestration profile，materialize 为一次性 contract；同一 contract 构建 metrics、insights、reports/history、brand、quarter 和 current-release。
4. 对七类 manifest、validation receipt、current-release、CSS 和 13 路由执行独立交叉验证，并输出单一 L2 candidate receipt。
5. 只有 L2 全绿后，才讨论单独授权的生产拓扑收敛与原子晋级门禁。

基于现有证据，推荐优先采用第二条的 honest partial 路径；除非能取得对 exact snapshot 的数据所有者声明，否则不能为了把页面日期改成 8 月 9 日而伪造 100% 可比较性。

## 9. 声明边界

### supported_claims

- 远端源包含北京时间 2026-08-09 07:00 闭合的数据窗口。
- 远端源前后身份稳定，本地副本与远端 SHA 完全一致。
- 8 月源可在本地走通 canonical、VOC facts、governed signals 和 personas。
- CSS fail-closed、隔离构建、13 路由浏览器检查与全量 Python 回归通过。
- 页面显示 7 月 23 日来自旧 `current-release`，不是日期组件写死或时区误算。

### forbidden_claims

- 不得声称 8 月 9 日数据已获 100% 数据所有者完整性证明。
- 不得声称 8 月全投影或协调 `current-release` 已完成。
- 不得声称线上 UI、数据日期或生产拓扑已经修复。
- 不得声称本轮执行过部署、重启、指针切换、供应商调用、数据库写入或消息发送。

## 10. 证据索引

- 机器回执：`output/audit/2026-08-09/p2a-local-projection/reddit-voc-p2a-local-projection-gate-receipt.json`
- 源身份：`tmp/p2a-remote-source-20260809/{remote-preflight,remote-postflight,local-snapshot-identity}.json`
- 覆盖拒绝：`tmp/reddit-voc-v3/p2a-remote-source-20260809/evidence/coverage-attestation-binding-check.stderr.log`
- 全量回归：`tmp/reddit-voc-v3/p2a-remote-source-20260809/evidence/python-pytest.stdout.log`
- UI 构建：`tmp/reddit-voc-v3/p2a-remote-source-20260809/evidence/ui-css-gate.stdout.log`
- 浏览器截图：`output/playwright/p2a-css-gate/.playwright-cli/`
