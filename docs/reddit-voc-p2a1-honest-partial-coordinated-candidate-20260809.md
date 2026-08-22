# Reddit VOC P2A.1 诚实部分覆盖协调候选门禁（2026-08-09）

## 1. 门禁结论

**决策：`P2A1_PASSED_LOCAL_CANDIDATE_ONLY`**

P2A.1 已在不伪造历史完整性、不开放同环比结论的前提下，完成北京时间 2026-08-09 数据的本地协调候选。最终候选 `reddit_voc_release_20260809_honest_partial_v2` 同时绑定 Base、Reports、Insights、Personas、Brand Health、Quarter Insights 与 Casebook 七类数据集；隔离 dist 的静态投影审计、关键页面浏览器回读和控制台检查均通过。

页面原先持续显示 `2026-07-23` 的根因不是日期组件写死，而是线上 `current-release` 仍指向旧数据。新候选读取 `data_as_of_utc=2026-08-08T23:00:00Z`，按 `Asia/Shanghai` 正确展示 `2026-08-09 07:00`。本门禁没有切换线上指针，因此生产站当前仍不能被声明为已修复。

证据等级为 **L3 远端只读源冻结 + L2 本地协调候选**。本轮没有部署、远端写入、数据库写入、供应商调用、消息发送、容器重启、计划任务变更或生产指针切换。

## 2. P2A 阻断项如何被正确化解

P2A 的阻断是：新 center 没有精确绑定的数据所有者 100% 覆盖证明，而旧代码把 `completeness_percent=100` 和 `data_owner_declaration` 当作常量写入 Base、Metrics、Reports、Insights 与 UI。

P2A.1 没有绕过这个问题，而是建立了诚实的部分覆盖合同：

| 字段 | P2A.1 值 | 业务含义 |
| --- | --- | --- |
| `comparison_contract_proven` | `false` | 不支持历史方向结论 |
| `comparison_contract_basis` | `not_owner_attested` | 没有数据所有者完整性声明 |
| `completeness_percent` | `null` | 不虚构完整率 |
| `coverage_attestation` | `null` | 不冒充已获得证明 |
| 不可比较原因 | `historical_collection_coverage_not_owner_attested_complete` | 页面和导出可解释地显示不可用 |
| 历史业务入口 | 0 | 不用不可信窗口生成历史趋势 |
| 当期描述性指标 | 可用 | 仅描述当前治理样本，不外推总体 |

由此，数据门禁控制的是“结论强度”，不再因为覆盖证明缺失而把已经采集的当期数据全部挡在页面之外。

## 3. 日期、采集与发布链路

```text
远端 SQLite 2026-08-09 采集窗口
  -> canonical center
  -> honest-partial Base
  -> periodized metrics（禁止比较）
  -> reports + insights 独立公开投影
  -> brand + quarter + personas + casebook
  -> coordinated current-release
  -> isolated UI dist
```

| 层 | 当前候选证据 | 结论 |
| --- | --- | --- |
| 远端源 | `daily_collect_20260809_0700`；窗口结束 `2026-08-08T23:00:00Z` | 北京时间 8 月 9 日数据已采集 |
| 最新 run | 16 threads、74 comments、90 analyses；11 full、5 partial | 数据新鲜，但采集覆盖为 partial |
| Canonical | 3,836 posts、28,522 comments、21,569 linked、6,953 unresolved | 身份守恒与未解析账本通过 |
| Base | `reddit_voc_site_snapshot_20260809_v3_daily_partial_001` | 诚实声明“覆盖未证明” |
| Metrics | 26 indicators、863 periods | 可计算当期；历史比较合同关闭 |
| Reports | 6 current/archive documents、0 history entries | 日/周/月可展示；无可信历史入口 |
| Insights | 78 storylines | 六段洞察可展示；方向结论受门禁约束 |
| Current release | 七类数据集原子绑定 | 本地候选通过，生产未晋级 |
| UI | `2026-08-09 07:00` | 正确展示数据截至时间，不伪装为墙钟时间 |

## 4. 候选制品与独立验证

### 4.1 核心数据层

| 制品 | 状态 | 关键证据 |
| --- | --- | --- |
| Remote SQLite freeze | 只读身份稳定 | SHA `e6d7ca479d87e89889315aad9db00f0145d1c91d754f797bd072532f2843bed6` |
| Canonical manifest | passed | SHA `4500ede67e3bc1425009583136567c063b1b2d7ce92db4bbab52a2e81688ea52` |
| Canonical validation | passed | SHA `e866b3e07069df736cb5e408a86a8e12b80f3d51bb459625bde78f9b55ce36c9` |
| VOC facts validation | passed | SHA `9781c45ef82bf9baad124ed6a2da74c481a9d6353c47c76681ada6fa24f30be8` |
| Governed signals validation | passed | SHA `a808f979cefcd391d64abc556ec857e365a1c35603d30531d28b4b35fe06c6d8` |
| Personas validation | passed | SHA `9556fd1edf469487475d05a61e47e31e5bb81ae59965dfc6a49c52b298b9aec3` |
| Indicator registry | bound | SHA `1d5b6bc30ac0a7ab1dc6ed4098449e93424f4ae0586d9ff288d9c56c25349a35` |

### 4.2 Honest-partial 投影层

| 制品 | 版本/摘要 | 独立结果 |
| --- | --- | --- |
| Base public | `reddit_voc_site_snapshot_20260809_v3_daily_partial_001` | manifest SHA `a547937b...81b`；验证 SHA `ad92fb49...53d` |
| Metrics input | 195,082,422 bytes；SHA `e0e6bbe8...4aed` | comparison=false；attestation=null |
| Metrics | manifest SHA `1b563267...d56c0` | 26 indicators、863 periods、确定性重放通过 |
| Reports public | `reddit_voc_reports_20260809_v3_1b563267bd6c_history2` | manifest SHA `1ab7a726...bb3d`；独立 receipt SHA `ea11d921...de9` |
| Insights public | `reddit_voc_insights_20260809_v3_1b563267bd6c` | manifest SHA `e43ac17c...2024`；独立 receipt SHA `f1a5977e...21cf` |
| Brand health | `reddit_voc_brand_health_20260809_public_v1` | manifest SHA `9e96bb...` |
| Quarter insights | `reddit_voc_quarter_insights_20260809_public_v1` | manifest SHA `bda71b...` |
| Coordinated release | `reddit_voc_release_20260809_honest_partial_v2` | pointer SHA `7598e310172da33b1effa3ca55fa1775c0645652643e124a8437cc053314cab9` |

Reports 与 Insights 的外部独立验证 sidecar 均被复制到最终 stage 和 dist，并纳入静态文件 allowlist：Reports 为 836 bytes / SHA `ea11d9213cc61a68ccc74381fde01fecb3f75f3b2bf4aca388a51ade45e63de9`；Insights 为 791 bytes / SHA `f1a5977eab86db1b1af56f54064e67f1578616d754faa58c1d4a85a004e821cf`。

## 5. 页面逐页验收

### 5.1 最终 `ui6` 关键页面回读

| 页面 | 主标题 | 日期结果 | 语义结果 |
| --- | --- | --- | --- |
| `/dashboard` | 真实数据概览 | `2026-08-09 07:00` | 当前周期部分完成；对比不适用 |
| `/dashboard/reports` | 舆情报告 | `2026-08-09` | 最新闭合周期（覆盖未证明）；0/52 同环比可用 |
| `/dashboard/insights` | Momcozy Reddit VOC 洞察 | 季度 `2026-05-12` 至 `2026-08-09` | 78 条受门禁约束的洞察故事线 |
| `/dashboard/settings` | 数据与指标口径 | 发布数据截至 `2026-08-09 07:00` | 明示“覆盖未获数据所有者完整性证明” |

四页均未出现 `2026-07-23`。关键 JSON 与图片请求均为 HTTP 200，浏览器控制台为 0 error / 0 warning。

### 5.2 全站路由与移动端

以下 13 条路由在隔离候选中均完成 DOM 激活与主标题检查：`/`、`/dashboard`、`/dashboard/reports`、`/dashboard/analytics`、`/dashboard/insights`、`/dashboard/search`、`/dashboard/ugc-showcase`、`/dashboard/messages`、`/dashboard/settings`、`/features`、`/how-it-works`、`/faq`、`/cases`。

390×844 移动端对概览、报告和洞察完成复核，无页面级横向崩坏；洞察截图位于 `output/playwright/p2a1-honest-partial/mobile-insights-390x844.png`。

## 6. MECE 能力图谱

| 能力域 | 当前能力 | P2A.1 状态 | 仍然缺失的证据/能力 |
| --- | --- | --- | --- |
| 调度与采集 | 07:00 日采集、run/窗口/partial 记录 | 远端事实已只读确认 | 尚无自动发布闭环与 shadow 运行回执 |
| 源身份治理 | SQLite integrity、FK、sidecar、前后 SHA | L3 只读通过 | 应自动生成不可变 source receipt |
| 融合与 canonical | 基线/增量融合、冲突、未解析、隔离守恒 | L2 候选通过 | 6,953 未解析父帖仍需补链 |
| 隐私公开投影 | 作者与敏感字段抑制、公开详情 allowlist | 通过 | 需生产回读证明实际消费新版本 |
| 覆盖语义 | owner-attested 与 honest-partial 双合同 | honest-partial 通过 | 没有 exact owner attestation，不能开放历史比较 |
| VOC facts | 帖子/评论上下文、资格账本、自动化排除 | 通过 | unresolved 继续 ledger-only |
| 治理信号 | promoted/held/rejected | 通过 | held 量大，需持续人工/规则治理 |
| Personas | atomic、cohort、facts、assignments | 通过 | 需要日更编排与漂移检测 |
| Periodized metrics | 26 指标、窗口、样本/比较门禁 | 描述性指标通过 | 同比、环比、趋势方向均未获准 |
| Reports | 日/周/月、导出、业务历史索引 | 当前报告可用 | 可信 history=0，不能称“全历史” |
| Insights | signal/root cause/impact/action 等六段结构 | 78 条通过 | 方向结论与因果结论必须继续 fail closed |
| Brand/Quarter | 品牌健康与滚动季度派生投影 | 通过 | 仅样本观察，不是市场份额或 ROI |
| Current release | 七数据集版本和 SHA 协调绑定 | 本地通过 | 未部署、未做线上原子晋级与回滚演练 |
| UI 时间语义 | now / data-as-of / period-end / quarter-end 分离 | 通过 | 线上仍消费旧 release |
| UI 构建 | Vite/Tailwind 编译、CSS 语义门禁 | 通过 | 生产旁路 Compose 尚未收敛 |
| 静态发布审计 | 文件精确集合、manifest/receipt/sidecar 交叉验证 | prepared true/false 均通过 | 需要纳入生产发布必跑链 |
| 浏览器验收 | 桌面、移动、13 路由、console/network | 本地通过 | 需要生产域名回读与回滚回读 |
| 外部副作用 | provider/live-send/DB-write 显式边界 | 本门禁均为 false | 仍需统一账本和双开关治理 |

## 7. 脆弱点与可优化点

### P0：进入生产前必须解决

1. **生产控制面 split-brain**：运行镜像曾绕过受控 UI release pointer。若只替换数据或只替换前端，日期和样式仍可能继续分叉。
2. **生产仍是旧版本**：本地 `ui6` 通过不等于 `reddit.lute-tlz-dddd.top` 已修复；必须以生产 pointer、容器身份、文件摘要和域名回读为证据。
3. **原子性与回滚尚未证明**：七类数据、前端资产、Nginx/Compose 消费关系必须一次晋级；任一失败应自动保持旧版本或恢复 previous。

### P1：数据可信度与持续运行

1. **最新 run 为 partial**：11 full、5 partial；页面已诚实展示，但采集器仍需补全 continuation 与预算/重试账本。
2. **6,953 条待关联评论**：它们保留在守恒账本但不进入公开事实，长期会削弱评论级洞察覆盖。
3. **无 owner attestation**：因此 history=0、0/52 comparison available 是正确结果；不能为了页面“更丰富”而放宽。
4. **Casebook 仍复用 2026-07-16 策展版本**：它是静态策展资产，不应被误读为 8 月 9 日新增案例；后续需独立刷新门禁。
5. **日更编排尚未形成生产 shadow receipt**：当前脚本链可重复构建，但还没有证明连续多个远端窗口能稳定产出一致 release。

### P2：工程质量债务

1. 前端 lint 仍有 15 条既存 Hooks/Fast Refresh warning，应按组件逐项消除。
2. 浏览器验收仍以 CLI 证据为主，应固化为版本化 E2E receipt，并加入视觉差异阈值。
3. CSS 门禁已有原始 Tailwind 与核心布局校验，后续应加入关键布局 selector、最小规则数和断点行为。
4. Reports 写入器曾把正式历史目录泄漏到 fixture-only 快照；现已按 manifest 声明修复，并由 8 个集成场景回归覆盖。
5. Reports/Insights 独立 sidecar 的版本与 SHA 仍通过代码 allowlist 管理；这能 fail closed，但每次新版本都需要改代码，后续应改为由受签名的 release inventory 驱动。
6. 仓库当前整体为未跟踪工作树，不能用 Git commit/SHA 作为发布身份；生产门禁必须依赖制品 SHA、精确清单和回执，后续再补版本库治理。

## 8. 本门禁已执行的实现

1. Base、Metrics、Reports、Insights 全链支持显式 `comparison_contract_proven=false`、`completeness_percent=null`、`coverage_attestation=null`。
2. 报告在覆盖未证明时不生成 business history，所有比较展示 `—` 并带原因码。
3. Insights 与前端解析器同时支持新 honest-partial 合同和旧 owner-attested 合同，避免破坏历史回滚版本。
4. Current release 与 dist audit 接受并严格核验两种覆盖语义；Reports/Insights 独立 sidecar 均进入最终发布清单。
5. UI 将“当前时间、数据截至、报告周期、季度窗口、采集覆盖、历史完整性”分开展示，移除“全历史”等越界措辞。
6. 新增 honest-partial 构建、隔离 stage 和 compose 脚本；所有副作用边界默认为关闭。
7. 修复 fixture-only 报表写入器的历史目录兼容性回归。

## 9. 下一门禁 P2B（未执行）

P2B 应是**受控生产拓扑收敛与原子晋级门禁**，需要新的明确授权。建议顺序：

1. 只读确认生产主机、容器、挂载、Nginx/Compose、当前/previous 指针和域名实际消费路径。
2. 冻结当前生产资产与数据 pointer，生成可恢复的精确备份和 SHA 清单。
3. 将 `release-dist-ui6` 与 `release-stage-v5` 作为不可变候选，重新比对本地 SHA、远端上传 SHA 和候选 release ID。
4. 在无 provider/DB-write/live-send 的边界内原子切换前端资产与数据 pointer；禁止半切换。
5. 从生产域名回读 13 路由、四个关键页面、CSS、current-release、Reports/Insights sidecar，确认日期为 8 月 9 日且 console/network 全绿。
6. 执行并证明 previous 回滚，再决定是否重新晋级；保留完整 acceptance receipt。

在 P2B 完成前，禁止宣称线上 UI、线上日期或生产拓扑已修复。

## 10. 声明边界

### supported_claims

- 远端源已采集北京时间 2026-08-09 07:00 闭合的最新窗口。
- 8 月 9 日 honest-partial 全投影与七数据集协调 release 已在本地构建并独立验证。
- 隔离候选四个关键页面显示 8 月 9 日，13 条路由和移动端检查通过，控制台无错误或警告。
- 缺少覆盖证明时，页面正确关闭历史完整性、同环比和方向结论。
- 最终静态投影在只读审计与 `--prepare-dist` 收敛审计下均通过。

### forbidden_claims

- 不得声称 8 月数据是 100% 数据所有者证明完整。
- 不得声称同比、环比、趋势方向或全历史结论可用。
- 不得声称生产站点、容器、指针、Nginx 或 Compose 已变更。
- 不得声称执行过部署、重启、远端/数据库写入、供应商调用或消息发送。

## 11. 证据索引

- 机器回执：`output/audit/2026-08-09/p2a1-honest-partial/reddit-voc-p2a1-honest-partial-gate-receipt.json`
- 协调候选：`tmp/reddit-voc-v3/p2a1-honest-partial-20260809/coordinated/coordinated-candidate-receipt.json`
- 最终 stage：`tmp/reddit-voc-v3/p2a1-honest-partial-20260809/release-stage-v5/`
- 最终 dist：`tmp/reddit-voc-v3/p2a1-honest-partial-20260809/release-dist-ui6/`
- 浏览器证据：`output/playwright/p2a1-honest-partial/`
