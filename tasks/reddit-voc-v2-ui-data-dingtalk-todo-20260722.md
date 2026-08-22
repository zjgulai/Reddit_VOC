---
title: Reddit VOC V2.0 UI、数据日更与钉钉周期报告执行 TODO
doc_type: execution_checklist
status: daily_refresh_candidate_ready_owner_authorization_pending
created: 2026-07-22
updated: 2026-07-23
owner: product_owner
project: Reddit_VOC
production_boundary: production_unchanged
---

# Reddit VOC V2.0 UI、数据日更与钉钉周期报告执行 TODO

关联规格：`docs/reddit-voc-v2-ui-data-dingtalk-implementation-plan-20260722.md`

## Gate 0｜Owner 决策（已通过）

- [x] D1 确认 UI 代码人工提升、通过验证的数据 release 每日自动切换。
- [x] D2 确认旧日报钉钉链 shadow 7 天后由新中心报告链替换，避免双发。
- [x] D3 确认一周期一张经营摘要图 + 结论 + 完整报告链接。
- [x] D3 确认日报预计 08:30、周一 09:00、每月 1 日 09:30。
- [x] D4 确认最长 30 天、可撤销的 bounded schedule policy。
- [x] D5 确认新增深珊瑚 `#B84F37` 作为按钮、链接与 Focus 色。
- [x] D6 确认三个周期发送到同一个管理群；只记录 destination fingerprint。

退出证据：Owner 于 2026-07-22 对 D1—D6 书面确认。

## Gate 1｜建立正式设计系统

- [x] 在前端根目录建立项目级 `DESIGN.md` 九段式规范。
- [x] 清点 `design-tokens.ts`、`tailwind.config.js`、`index.css`、导出和图表色板。
- [x] 选定唯一 token 源；其他配置由源生成或只引用语义变量。
- [x] 收敛 Momcozy、竞品、正面、负面、中性和警告业务色。
- [x] 修复浅珊瑚承载白字/小字的对比度问题。
- [x] 拆分 `surface-card`、`interactive-card`、`overlay`。
- [x] 删除静态卡全局 hover 上浮。
- [ ] 统一 12/16px 圆角和受控阴影。
- [x] 增加最大内容宽度 1440px。
- [x] 统一指标帮助组件和 44px 触控区。
- [ ] 建立 desktop/tablet/390px/reduced-motion 视觉基线。
- [x] 建立报告页 desktop/tablet/390px/reduced-motion 候选视觉基线（12 个日/周/月视图）。

退出证据：token drift validator 通过；无未登记业务色；相关 UI 单测、typecheck、build、视觉基线通过。

## Gate 2｜全局框架与核心页面

### 全局

- [x] 新增数据证据条：业务截至/最新事件、run、center release、projection release、coverage；缺失 run 明示“未提供”。
- [ ] fresh/partial/stale/failed 四态与解释抽屉。
- [x] 移动端“核心五项 + 更多”覆盖所有生产模块。
- [ ] 统一 URL 状态和返回路径。

### 概览

- [x] 首要叙事按“数据证据—窗口/KPI—全历史健康度—趋势—四类决策入口—行动”重排。
- [ ] 并列窗口品牌健康度与全历史基准。
- [x] 保留帖子/VOC柱 + 负面率线的双轴趋势。
- [x] 四个决策入口分别下钻痛点、舆情、新品、GEO。
- [ ] 去除重复风险列表、重复图标和常驻展开的工程边界。

### 报告

- [x] 日报重构为行动指挥：新帖、活跃旧帖新增评论、异常、三项行动、五条证据。
- [x] 周报重构为结构诊断：WoW/YoY、驱动、竞品、行动复盘、下周资源；没有真实行动账本时显示“尚无执行回写”，不生成完成率。
- [x] 月报重构为战略取舍：四维健康构成贡献、MoM/YoY、品类/SPU、风险、机会、下月指标；构成贡献不冒充变化贡献。
- [x] 移除无选择价值的“最新完整周期”单选控件，改为真实可用周期和归档边界说明。
- [x] 当报告合同公开多个业务可见历史周期后启用真实归档选择器。
- [x] 新增独立 `reddit_voc_business_history_index_v1`，首版公开最近 14 个完整日报、12 个完整周报、12 个完整月报；内部 comparison archive 语义保持不变。
- [x] 每个 `history/{grain}/{period_id}.json` 复用完整指标、健康维度、活动拆分与故事线，并逐文件写入 manifest SHA；不存在观察时保留真实零样本，不回退当前周期。
- [x] 前端按 `period` + `period_id` 恢复 URL 状态，先校验 history index，再按 SHA 懒加载单份历史报告；补桌面/移动/刷新/返回/路径安全测试。
- [x] 不可计算指标不显示；真实 0、缺失、无比较明确区分。

报告剩余数据合同阻塞：周报尚无真实行动回写账本，因此当前只支持明确空状态。V3 `archive_policy=internal_comparison_storage_not_a_business_entry` 保持不变；业务历史已由独立 `business-history-index` 与完整 history 报告实体承载，没有把内部比较归档改成业务入口。

2026-07-22 下一批本地闭环：新增 `reddit_voc_period_activity_v1` 扩展，按 Asia/Shanghai 完整周期分别输出全 observation 池与治理后 Momcozy 口径的新增帖子、新增评论、当期新帖评论、历史帖新增评论、被重新激活的历史帖和未关联父帖评论。当前完整日报为全池 `7/25/11/4`、Momcozy `2/14/9/2`（依次为新帖/新增评论/历史帖新增评论/历史活跃帖）。新 metrics manifest SHA `a71a3a723bd9cc1ad1b7cc4a55424598e7ff07e27e6f16c4444a38bfab9ffbf9` 通过独立全字节重算；公开 reports 数据集 `reddit_voc_reports_20260716_v3_a71a3a723bd9` manifest SHA `216532b6b724fdadae3a248225d8337b03487c2a144937a39ef1aaaf14ec0d13` 通过隐私安全重放并已激活到本地 current-release。生产、采集器、调度和钉钉未变化。

2026-07-22 月报/周报本地闭环：新增 `reddit_voc_brand_health_dimension_contribution_v1`，每个完整周期输出原始观察与治理后有机两种口径各四维，维度由帖子/评论各 50% 合成，四维对总指数各贡献 25%。月报展示治理后四维当前分及指数构成贡献，并明确它不是环比变化贡献。周报新增 `reddit_voc_action_review_v1` 真实空状态：`ledger_available=false`、`completion_supported=false`、零记录、原因 `action_ledger_not_supplied`。metrics manifest SHA `382d621ae075ed2519b51d59947cd40f3f228b978fc1f921047610abbddd3902`、reports manifest SHA `1e2c0e73bc1d20faf75a179e717aba24254e7f79393bc15370aa70df24526217`、public manifest SHA `580517a1c524ecb752db083e90568f5da5d961d5e1acf85bfb9e2a85af1a6a35` 均通过独立重放/隐私投影；本地 pointer SHA `671709b00f30cea311dbacfd4fbfb7d4ec38b7621310aae2ba1210c7920367c0`。生产、采集器、调度和钉钉仍未变化。

2026-07-23 业务历史报告本地闭环：`reddit_voc_business_history_index_v1` 独立公开 14 个完整日报、12 个完整周报和 12 个完整月报；加上 3 个最新完整周期，共 41 个业务入口。3 份内部 comparison archive 仍不可见，因此报告文档总数为 44。公开 manifest 声明 47 个文件，但前端首屏只加载 9 个报告 bootstrap 文件；选中周期后才按 history index 路径和 manifest SHA 加载单份正文。首版 `history1` 因公开 manifest 内容修订未继续复用；正式本地版本已提升为不可变 `reddit_voc_reports_20260723_v3_382d621ae075_history2`，candidate manifest SHA `3240005aec33b9e519674797eb5265c9f8a1ce7e94011446fdce3b9d71ead2c6`、公开 manifest SHA `637a955282fa4eed78efee682a967978702104a1de2c9cd52ce522d0ed62e72f`、本地 current-release SHA `5207fcdc85c0e21c555b16a87e43718e3a8ad93caa8582f383bc5ce42af55669`。真实周期指标全字节重放通过；Python 相关与 dist 审计测试 49 项通过，前端全量 212 项通过、46 项既有合同门禁跳过，typecheck/build 和真实 dist 审计通过。历史加载中、失败或快速切换时导出保持禁用；生成器、验证器和 current-release builder 均拒绝祖先 symlink 与递归未声明文件；dist 审计额外强制周期 ID、日期跨度和规范路径一致。Chrome 验收确认首屏 0 个 history 请求、选择和深链各 1 个请求、移动端横向溢出 0、浏览器错误 0。生产、采集器、调度、钉钉和其他 Docker 环境未变化。

发布操作约束：裸 `vite build` 仍会复制 `public/data` 中用于回滚的历史版本，不能直接作为部署目录；必须沿用发布脚本中的 `audit_insights_dist.py --prepare-dist` 精确收敛步骤，并在收敛后执行第二次只读审计。

### 洞察、分析、搜索与运营模块

- [ ] 洞察口径面板压缩为范围条；用户画像保持首模块。
- [ ] 四个洞察 Tab 使用统一“判断—证据—解释—行动—案例”协议。
- [ ] 收敛洞察页任意圆角、渐变、毛玻璃与写死色。
- [ ] 分析页增加时间/品牌/品类/SPU 全局过滤和图表下钻。
- [ ] 搜索页实现帖子/评论粒度切换和移动筛选。
- [ ] 修复案例页无效页头搜索，保留存量与批准增量边界。
- [ ] 高价值内容切换为四维评分列表。
- [ ] 舆情信号切换为风险排序/时间线。

退出证据：核心任务 E2E、13 条生产路由候选 smoke、桌面与移动视觉验收通过。

本批本地证据（2026-07-22）：

- 全站共享布局已接入数据证据条；Base、Reports、Insights 使用各自合同允许的时间口径，collector run 未提供时不从版本名猜测。
- `100%` 明确标注为“数据所有者声明”，报告覆盖进一步标注“非 crawler proof”；6,953 条待父帖关联评论继续展示。
- `MetricHelpPopover` 已成为概览、比较卡和报告指标的统一组件，支持 44px、Esc、点击外部、焦点恢复和未知公式不显示。
- 全量前端：45 个测试文件通过、204 项通过、46 项合同门禁跳过；`tsc -b + vite build` 通过；lint 仅保留 7 条既有 Fast Refresh warning。
- 窗口品牌健康度尚无正式窗口四维投影，禁止复制全历史 `72.54` 伪造；本项继续阻塞在数据合同。
- 日报按 Asia/Shanghai 自然日归属真实 Base 帖子，当前日召回 6 条 Momcozy 相关新帖并展示 5 条证据；日/周/月分别形成 4/4/5 步业务叙事路径。
- 报告页 12 个 desktop/tablet/390px/reduced-motion 候选视图通过：HTTP 200、无横向溢出、无浏览器错误、无无效周期按钮；截图保存在 `tmp/ui-v2-reports-visual-20260722/`。
- 13 路由 desktop/390px same-dist E2E 通过，receipt SHA `f1efb17f4ac3add2ce43c668a3661dfa369be1075d0abc8ad34d9ffe4eb27844`；本地非提升 release SHA `ebb80097f66d8968d6ecf1886597c39734b6611dc6e2e4c4e427c8a5be021827`。
- 未完成全站 tablet/reduced-motion 视觉基线、候选容器、导出复验与任何生产提升。

## Gate 3｜每日增量进入中心与全部业务投影

- [x] 冻结 07:00 `daily_collect` 的 SourceBatch exporter 和 validation receipt。
- [x] 接入过去 24 小时新帖和活跃历史帖新增评论两个 lane。
- [x] 对截至 2026-07-23 的生产采集快照做首次受控补入与去重验证。
- [x] 单写者融合 occurrence、canonical、content version、engagement snapshot 和父帖债务。
- [x] 完成 V2 center → V3 canonical bridge。
- [x] 同源重建 Base、Reports、Insights、Personas、Brand Health、Quarter；案例库保持存量版本。
- [x] 生成 data candidate、surface manifests 和独立 validation receipt。
- [x] 实现 `failed/full/partial/empty_success/no_change` 状态机。
- [x] 修复采集 failed/0 数据仍生成并发送业务报告的问题。
- [x] 相同 SourceBatch 重放验证 `no_change`。
- [x] 对帖子、评论、已关联、待关联、隔离执行守恒检查。

退出证据：两个真实日周期 shadow 与旧链对账；44 帖/183 评论增量去重结果有正式 receipt；所有 surface 指向同一 data release。

2026-07-23 首次 Jul-23 七数据集候选闭环：

- 生产采集快照 `server_snapshot_20260706_20260723` 以 partial 状态受控纳入，新增 56 帖、246 评论，另观察到 139 个存量/历史父帖；融合中心为 3,591 帖、27,562 评论，其中 20,609 已关联父帖、6,953 待父帖关联。partial 只描述分页覆盖，不阻止通过完整性与血缘门禁的正式投影。
- 统一数据指针 `reddit_voc_release_20260723_daily_v2`、SHA `2864b82ca32cfbcccc30a95298b2d65e70e7dc7b405b38d29ceeb6eb6e829d27`，业务截至 `2026-07-23 07:00 Asia/Shanghai`。七份绑定为 Base、Reports、Insights、Personas、Brand Health、Quarter Insights、Casebook；案例库仍为 `reddit_voc_casebook_20260716_public_a1`，未改存量内容。
- 日报/周报/月报数据集为 `reddit_voc_reports_20260723_v3_47c49395e785_history2`，共 44 份正文；日报按 07:00—次日 07:00 业务日计算。同环比、同比与趋势基于数据所有者确认的 100% 历史完整性执行，无法计算的指标继续隐藏。
- 概览健康度 72.55；季度洞察统一为 2026-04-25—2026-07-23。所有页面由同一指针绑定，案例广场不参与季度洞察排序或归因。
- 07:00 自动 SourceBatch exporter、两个正式采集 lane、同批重放 `no_change` 与两周期 shadow 尚未完成，不能把本次手工受控闭环表述为已启用每日自动更新。

2026-07-24 报告源状态 fail-closed 补强：prepared preflight 在渲染、provider 与制品阶段之前校验 run 状态和观察数；`failed`、未知状态、`success/partial + 0 帖子` 均不得生成业务报告，合法 `empty + 0 帖子/0 评论` 固化为 `empty_success`。发送前再次只读数据库，并与 prepared bundle 内冻结的 source state 全字段比较；失败、归零或 `success → partial` 漂移均在 HEAD、凭据读取和 transport 之前阻断。prepared validation 升级为 v2，旧 v1 bundle 因缺少 source-state proof 自动失效；runtime smoke 与 release allowlist 同步更新。相关 prepared/delivery/release 回归通过，未调用 provider、钉钉、生产数据库或远程环境。

2026-07-23 对抗审查后的 r2 重建：

- 初版 `daily_v2` 候选、code release `6b869ee8…` 及 packet `014be53b…`、`afff7924…` 因生成时间晚于实际构建时刻、raw continuation 债务未被 21 个绑定工件直接证明、七数据集校验命名仍沿用“四数据集”而作废，不得授权或提升。
- Base 重建为 `reddit_voc_site_snapshot_20260723_v3_daily_002`，manifest SHA `bc4703d87a81c96f1aa73b5d507f9e77f1af906e4f1a44ab29f45f3bc6d4e517`；Personas 重建为 `reddit_voc_personas_20260723_daily_v2`，manifest SHA `45fdcf7e38ed871196b72f0bea4ef0e447e6f3bcc817454860bb19cd64bd642c`；Quarter Insights 重建为 `reddit_voc_quarter_insights_20260723_public_v2`，manifest SHA `7382777831f3420116293426c12936d2a40096e5bc931996b2129dd04600e6b4`。三者与最终 pointer 的生成时间均固定为实际已发生的 `2026-07-23T06:08:33Z`。
- 新统一数据指针为 `reddit_voc_release_20260723_daily_v3`，SHA `0443e26cfff6d9ad3ca3f445db91f9cdb4505bf69094b0856f771863805cb5cb`；帖子、评论、父帖债务与 07:00—07:00 freshness 数值不变，`unresolved_continuations=5` 只存在于被 SHA 绑定的 pointer freshness 合同中。
- frontend source receipt 使用 `current_release_seven_datasets_exact` 与 `v3_seven_dataset_manifest_receipt_lineage_exact`；builder 与独立 validator 均拒绝未来生成时间。promotion packet 不再写入无法由绑定工件推导的 raw continuation `75`。

## Gate 4｜代码 release 与数据 release 解耦

- [x] 定义 `app_release` 与 `data_release` 双身份合同。
- [x] 建立 Reddit VOC 专属版本化数据根和只读挂载。
- [x] 实现 `current-data` 原子指针和上一通过版本回滚。
- [x] publisher 只写专属数据目录，不写 collector、不改共享 Nginx。
- [x] 任一 SHA、lineage、period 或 surface 不一致时保持指针不变。
- [x] 新鲜度 SLO：采集闭合到生产数据 P95 小于 90 分钟。
- [x] 增加 stalled、stale、partial、failed 和 rollback 观测指标。
- [x] 创建专属 one-shot pipeline 与 systemd timer 草案。
- [x] 以 shadow 模式运行，不切生产指针。
- [ ] 精确授权后才启用每日自动数据切换。

退出证据：data pointer 原子性/回滚集成测试；shadow 两周期通过；生产隔离 diff 通过。

2026-07-23 发布后断点续作：确认现有 `reddit_voc_current_release_v2` 与 code
`release_sha256` 已形成独立 app/data 身份；`reddit_data_release_control.py` 已覆盖七数据集
manifest SHA、CAS switch、previous rollback 和不授权拒绝。本轮新增正式 `shadow` 命令：
在同一锁内读取 current/previous、验证候选、再次读取并要求完全不变，然后输出不可变
`reddit_voc_data_release_shadow_receipt_v1`。真实 `reddit_voc_release_20260723_daily_v3`
本地 shadow 通过，pointer SHA `0443e26cfff6d9ad3ca3f445db91f9cdb4505bf69094b0856f771863805cb5cb`，
receipt SHA `4d27d68231bf5d5b4b9ebe50ff6f505eb4d016d4a2f3d48de2a76e6b02d591c5`；
`production_switch=false`、`remote_write=false`、`schedule_change=false`、`live_send=false`。
当前只完成一个真实数据周期，Gate 4 退出条件要求的第二个真实 shadow 周期仍须等待下一次
07:00 SourceBatch 闭合；SLO、观测指标和生产自动切换仍未启用。

2026-07-23 数据/代码解耦候选实现：

- 新容器合同 `reddit_voc_insights_container_v6` 使用唯一专属数据根
  `/opt/reddit-voc-insights-data`，只读挂载到 `/srv/reddit-voc-data`；Nginx 仅将
  `/data/reddit-voc/` 映射到 `current/public/data/reddit-voc/`，不会暴露 locks、
  receipts、previous、其他 release 或宿主机路径。案例广场 `/data/cases/` 继续由代码
  release 固化，存量内容不受每日数据切换影响。
- 容器健康检查同时要求 `/healthz` 与动态 `current-release.json` 返回 200；数据根缺失、
  pointer 缺失或权限不满足时 fail closed。未来生产安装器要求恰好一个
  `bind|/opt/reddit-voc-insights-data|false|/srv/reddit-voc-data|rprivate` 挂载；
  生产验收支持新的一挂载合同，同时保留旧 release 的零挂载回滚兼容。
- 本地候选 code release `f56057672575ad70b44b61e4b9de6a65cf88ad7b44f5cd0c222c547358d64f7e`；
  manifest SHA `a0a02c2d39c97486b969b24e5ab4e6c7f33735f37323e396e7c4101e5373a640`；
  build receipt SHA `a1e6a6531480ea6f31e467a4f7a246f0c16f39f6aa506dbaf0e95052b90e0536`。
  前端 214 项测试通过，相关 Python/契约测试 59 项通过。
- Linux/amd64 隔离容器验证了真实七数据集、13 个路由、20 个敏感路径 404、UID/GID
  101、只读 rootfs、唯一只读数据挂载、无 host port、无新增权限；最终 smoke receipt
  SHA `696c0be8bd089cd461e8b63bae811eb4f03d311b06cf5ae950e35a9c0c50ef27`。
- macOS Docker Desktop 对运行中替换只读 bind mount 内的 `current` symlink 返回
  `open() ... failed (22: Invalid argument)`；该失败已保留，未写入通过回执。目标生产为
  Ubuntu 原生 Linux，因此“容器不重启即可观察 pointer switch/rollback”仍须在服务器
  专属隔离数据根做一次不连接生产流量的 shadow 验证，完成前不得启用每日自动切换。
- 新增 `reddit_voc_data_pipeline_attempt_v1` one-shot runner：默认且 systemd 草案只运行
  `shadow`，使用全局非阻塞锁；失败同样写不可变 attempt receipt；`switch` 同时要求
  `--mode switch` 与 `--authorize-switch`，systemd unit 不包含该授权参数。service 使用
  `ProtectSystem=strict`、`NoNewPrivileges`、`AF_UNIX`，timer 在 07:10—08:25 六次执行
  watchdog；当前仅为仓库草案，`schedule_change=false`，没有安装。
- 新增 `reddit_voc_data_release_observation_v1`：以最新 07:00 Asia/Shanghai 闭合期为基准，
  明确输出 `fresh/partial/awaiting/stalled/stale/failed/rollback`、90 分钟 deadline、
  当前 lag、单期 SLO 和历史 switch P95。真实 `daily_v3` 的独立本地 shadow 观测结果为
  `partial` 且 `slo_met=true`；attempt receipt SHA
  `93d6dd93813113ed40f87332589c425f472e3d03e8968fd81d57021ad3384af6`，
  observation SHA `d84eaa6250057b3a03c2841af307a899c098cf274cbeed4dd75a3ee43883f55f`。
  本批累计相关 Python/契约测试 67 项通过；生产 P95 仍需自然周期样本，不能用单次
  本地 shadow 冒充。

## Gate 5｜三周期报告截图

- [x] 新增 `capture=poster`，复用真实 V3 报告组件。
- [x] 隐藏导航、导出、刷新、Tooltip、动画和自动轮询。
- [x] 增加 `data-report-capture-root` 与 `data-report-ready=true`。
- [x] 在画面中固定 period、data release、dataset、coverage 和 data_as_of。
- [x] 日报 1440×1800；周报 1440×2000；月报 1440×2200。
- [x] 截取指定节点，不使用无限 full-page。
- [x] Playwright 失败不得发送 PIL fallback 或上一期图片。
- [x] 生成 PNG、manifest、image SHA 和视觉质量结果。
- [x] 覆盖空指标、长标题、partial、empty success、中文字体和极端数值。
- [x] 建立三周期 golden baseline 与允许差异规则。

退出证据：三张候选图在钉钉手机端人工可读；页面、截图、导出数字一致；视觉和身份门禁通过。

2026-07-24 本地 Gate 5 候选闭环：

- `capture=poster` 仅接受已校验 V3 报告；页面导航、导出、刷新、周期选择、Tooltip、动画和交互均不进入海报。画面固定显示周期 ID、数据截止、Reports dataset、data release 和 100% 报告完整性；源数据 freshness 作为机器可读身份记录，当前真实候选为 `partial`，不被伪装成 full。
- Playwright CLI 只截取 `[data-report-capture-root]`；日报、周报、月报分别严格为 1440×1800、1440×2000、1440×2200。验证器要求三次几何稳定、中文字体加载、无 loading/Tooltip/请求失败/外部请求/溢出/页脚重叠；失败时不生成发送凭证，不存在 PIL 或上一期图片 fallback。
- 最终本地证据目录 `output/reddit-voc-periodic-report-posters/gate5-local-20260724-r3/`，manifest SHA `85c4608f904f2d4d2b7e9d726b3d816a40d3f23867a913e774dba8e142da6b48`。日报 PNG SHA `9cd386b182b3b0e1efaab86b692afd41a8c36493b76cec6b8e1a7b341ae40ebf`；周报 `3d2f52c2413260df5fbeb189eb2b24b6b692240c635782ccb8fb85811065e451`；月报 `f121bf5fb46e05d7d21065e84587a3b8391827aac5f9ed613bb5b54d0c6ac907`。
- Golden 合同 `quality/reddit-voc-periodic-report-posters-golden-v1.json` 已通过三周期 exact pixel replay。相同 release/dataset/period/validator 必须逐图 SHA 完全一致；身份变化时只允许结构门禁通过，并强制重新人工视觉复核，尺寸变化必须显式升级 golden 版本。
- 当前真实图覆盖中文字体、100+ 字长文本块、源 freshness=`partial` 和月报四位数同比极端值；`empty_success` 的“保留最近闭合报告、不伪造新报告”通过单元合同。V3 组件测试同时证明海报四项关键指标、页面指标和导出数据行使用同一报告值。
- 已在本地按缩放后版面完成目视检查；真实钉钉群的手机端查看与公开 HTTPS 图片链路仍属于 Gate 6，未发送、未改调度、未改生产。

2026-07-24 `daily_v3` 身份追平：以生产同版本数据指针 `reddit_voc_release_20260723_daily_v3` 重新物化当前报告 UI，并完成两次逐像素重放。最终海报目录为 `output/reddit-voc-periodic-report-posters/gate5-daily-v3-20260724-r2/`，manifest SHA `d4d89508f01197c4fe74f6eedf932368073fb34612c1fc28d0c920a0c9c3578d`；日报、周报、月报 PNG SHA 分别为 `d900edc396e33eef9f004e1fd328451c4b8e64f09706cf8b33bb0c9db8c767f6`、`853fe58969b8fbe103c08666bbbfd2caf1a88b82345e8018270ef29195eed7e8`、`022c1bd61f5765774bc7fd66ac5a1f7f2b0408637391bd1750ae7d5e43d9589c`。Golden 已升级为 `quality/reddit-voc-periodic-report-posters-golden-v2.json`（SHA `5ea08077f0a3523c7b5b0b6c5ad189dd944f51b4c200a6c48cc84c22294fe76e`），三张图均通过 exact pixel baseline 且无需待办人工复核。

## Gate 6｜不可变周期包与钉钉安全发送

- [x] 将 daily-specific bundle 泛化为 periodic report bundle。
- [x] DingTalk Markdown 引用公开 HTTPS PNG，并保留完整报告与导出链接。
- [x] 发送前 HEAD、bytes、SHA、period、release 全部通过本地 fail-closed 合同与 synthetic HEAD 验证；真实公网 HEAD 留待 shadow 发布后执行。
- [x] 使用 `grain + period_id + data_release_id + destination_fingerprint` 幂等键。
- [x] 复用 frozen bytes、attempting、hash-chain ledger 和 unknown 状态治理；周期 shadow sender 已覆盖 duplicate/rejected/timeout/unknown/显式重发合同，且不加载 webhook 或 secret。
- [x] failed 不生成/不发业务报告；partial 明示覆盖；empty success 生成明确无净新增消息；真实外发仍未授权。
- [ ] 报告发送与失败告警使用不同的授权和消息模板。
- [ ] webhook/secret 保持 repo 外 mode-600，不进入前端与制品。
- [ ] 新链先 shadow 7 天，不执行外部发送。
- [ ] 完成新旧日报数据与消息差异报告。
- [ ] Owner 精确授权后，在测试群执行一次三周期 synthetic/live 验收。
- [ ] 切换日只保留一个 authoritative daily sender。

退出证据：重复、拒绝、超时、unknown、旧图、旧 release、URL 失败测试全部通过；真实测试群回执经人工确认。

2026-07-24 Gate 6 本地影子候选：新增 `periodic_report_bundle.py` 与本地 builder，将日报/周报/月报三张已校验海报复制为不可变 public bytes，并冻结三份 secret-free Markdown outbox。验证器重算 poster/outbox/aggregate SHA，强制三周期集合、1440 固定宽度、period/release/dataset/destination 身份、HTTPS 图片/完整报告/导出链接及幂等键；tamper、旧 release、HTTP URL、failed source、远端图片长度不符均 fail-closed。最终相关组合回归 73 项通过，其中周期包定向测试 9 项；provider-free runtime smoke 通过。影子包位于 `output/reddit-voc-periodic-report-bundles/shadow-20260724-a/`，manifest SHA `00a2ea66cbd418155a5b8319ed25529bf2eef3d17df63a01b52d36c547d79248`，`delivery_eligible=false`、`live_send=false`。该包绑定 Gate 5 本地海报的 `reddit_voc_release_20260723_daily_v2`，而当前生产数据指针已为 `daily_v3`，因此只作为结构验证，禁止发布或发送；必须先以最新 release 重截三张图再进入真实公网 HEAD/shadow 对账。

2026-07-24 Gate 6 `daily_v3` 续跑闭环：最终不可变周期包位于 `output/reddit-voc-periodic-report-bundles/shadow-daily-v3-20260724-r2/`，manifest SHA `658966e32a39fcff47b91f7ba0d64d7ac7f520b311e505aef3a57e113853d21b`，bundle ID `periodic_93d555291be7aa1b71b5ccc965492a73`。新增 public-only projection 仅含三张 PNG 和一份清单，显式排除 private outbox、destination fingerprint 与 credential material；public manifest SHA `6304e19dc9ca4e41509537938eee496b5504807a410e56a0343d8f3c97f7903b`，本地真实 HTTP HEAD 四项均返回 200 且长度精确。周期 shadow sender 以 synthetic transport 完成三 grain `attempting → sent`、hash-chain ledger 和不可重放验证，receipt 位于 `output/reddit-voc-periodic-report-shadow-state/daily-v3-r2/shadow-receipt.json`，`external_attempt_made=false`、`live_send=false`。真实公网 HTTPS HEAD、7 个自然日新旧链对账、测试群发送和 authoritative sender 切换仍未授权、未执行。

周期公开资产已正式纳入 V3 前端源码和发布清单的可选强绑定合同，而不是放宽 allowlist：源码 manifest `35db34e072e1595471cb66f2a693441450dd573a6389c948dfad5a11c00f8cf9`、独立校验 receipt `bbc37475e4d9598a82545b9c88187a6923b54c41c71365347f75e55ba81153b7`，最终本地容器 release `e0d57e921ffb54662f883635fb4f20a89ffde898d95293dd1e304178dace6240`、archive SHA `49bf173d6877be267323c0cf2da32e3818ae5a466c1a91123197ca931a06aa93`、build receipt SHA `694a2ff31333f879b0348e89b223be03eafa08ad1af742c2729cac6a8c158828`。隔离容器 smoke 状态为 `passed_local_isolated_container_smoke`，receipt SHA `2303898829b701ffafce2237afb38818468492482ab93bd7fdfa66ab9412c474`。候选 `deploy=false`，没有上传、远端写入或钉钉发送。

## Gate 7｜完整验证

- [x] r2 本候选相关 Python unit/integration tests（148 passed）；另有生成器/校验器定向契约测试 49 项通过。
- [x] 前端 unit、typecheck（由 `tsc -b` 执行）、lint、build。
- [x] 本候选 SourceBatch、center、metric、surface 与 release validators。
- [x] same-dist 生产路由 E2E（本地同源 dist，13 路由 desktop/390px）。
- [ ] desktop/tablet/390px 视觉回归。
- [x] 报告页 desktop/tablet/390px/reduced-motion 视觉回归。
- [x] daily/weekly/monthly capture E2E 与同身份 exact pixel replay。
- [x] CSV/PDF/PPTX/DOCX 与同一日报、报告 manifest、data release 和 code release 绑定验证。
- [x] 公开 allowlist 与敏感路径 404（本地只读容器）。
- [ ] secret scan、日志脱敏和 webhook 不落盘验证。
- [ ] app rollback 和 data pointer rollback 演练。
- [x] 独立审查需求完整性、逻辑、边界、质量、覆盖和实测结果；r2 结论 PASS，P0/P1/P2 均为 0。
- [x] 主线程修复上轮三项阻塞后完成复验；仅余不阻塞授权的 P3 证据标签命名债务。

退出证据：一份签字版 acceptance packet，包含命令、SHA、截图、route matrix、data matrix、rollback 和审查回执。

## Gate 8｜受控上线与观察

- [x] UI 与 Jul-23 七数据集 candidate 完成 promotion packet；未授权前不提升。
- [ ] data publisher 单独申请每日自动切换授权；未授权前只 shadow。
- [ ] 钉钉 schedule policy 单独申请授权；未授权前只 dry-run。
- [x] 受控提升只切 Reddit VOC 洞察站。
- [x] 验证 collector、共享 Nginx、TLS、DNS 和其他 Docker 未变化。
- [ ] 观察 3 个日报周期。
- [ ] 观察 1 个完整周报周期。
- [ ] 观察 1 个完整月报周期。
- [ ] 发布 V2.0 使用手册、运行手册和已知债务。

最终退出：数据日更、三周期报告、截图与钉钉均达到 SLO；没有重复发送、旧数据冒充或跨环境污染。

## 2026-07-23 受控生产提升完成

- 候选 code release：`130e228cdf7e9d936a862b5a992533e21ae2d3df01b90889d1b5a0b9ec8571ad`。
- 候选 data release：`reddit_voc_release_20260723_daily_v3`；pointer SHA `0443e26cfff6d9ad3ca3f445db91f9cdb4505bf69094b0856f771863805cb5cb`。
- same-dist 浏览器 E2E receipt SHA：`eb6e5ca9ac4681342c2f16d90b0b1bed016b11e0a94a28a883d4c3e8528a1471`。
- 本地隔离容器 smoke receipt SHA `f11920b92d5fb0481197df8fad62f208aa074b6a72b3408dfdc81ea8b93168ff`；四格式导出 receipt SHA `3b8ccc3455652de27de4750757661191e85e1bf45ab46559462c59cc8e50fce0`；安全验收 receipt SHA `b4d4197142bc807f96ebac030c49df392c268c8b5ab9fed478325dd4c2df0aaf`。
- 提升前生产只读基线为 `ebaa5443906628145f9fbe05777d4218b1ec6d53b78e9d7f4f86fa8fbe9df313`，内部 pointer `reddit_voc_release_20260723_business_history_002`；提升后 code release 已原子切换为 `130e228cdf7e9d936a862b5a992533e21ae2d3df01b90889d1b5a0b9ec8571ad`，内部 pointer 为 `reddit_voc_release_20260723_daily_v3`。
- promotion packet SHA `74d7ce352883c024d142f7b79ec9bf309f0ffe52668e97e1e9da20435f566354` 已按 Owner 精确授权执行并消费；permit SHA `c66bc1aa44a33a8e3b9349c5f2d0b7520e470903f1996ae0b54000c24e0176e4`，production acceptance SHA `23d45bd73cd93b5c54872afd3fd4f0716a9d54ff554892886b7427d614c50473`，consumption receipt SHA `684f39057ec8017a30a61b18b8beb419dc24bdf6970d981f22e64bc5278fa1ba`。
- 公网 HTTP 验收通过：13 个业务路由和 8 个公开制品返回 200，20 个敏感路径返回 404，TLS、release marker 与 data pointer 精确一致。浏览器验收覆盖 desktop/mobile 共 26 页、日报/周报/月报历史选择及深链、洞察、概览、案例广场和采集后台安全链接，错误、同源失败与外部请求均为 0。
- 冻结浏览器脚本在生产网络下两次暴露报告周期 option 异步替换竞态；保留失败日志，并使用只位于授权证据目录、增加 option 值集合稳定等待的脚本完成同等完整矩阵。该测试修正未进入生产 release，未改变 release 哈希。
- 独立审查已给出 `PASS / APPROVE`，P0/P1/P2 为 0。审查时唯一 P3 是 same-dist E2E receipt 的检查标签仍写 `release_pointer_and_four_datasets_exact`；发布后主线已改为 `release_pointer_and_seven_datasets_exact`，并加入生产网络下报告周期 option 值集合稳定等待。复验覆盖 26 页面，receipt SHA `4efebc403ef5de3469016755ea9ea2645409d4a922e5bb397568d1c8bb468cc5`，旧检查名已不存在。
- 旧 code release `6b869ee8…` 与 packets `014be53b…`、`afff7924…` 已明确作废，不得授权使用。
- 采集器与翻译服务容器 ID、健康状态和重启次数前后不变；数据库和报告指针稳定；cron 与共享 Nginx SHA 前后一致；TLS、DNS 和其他 Docker 环境未修改。上一 code release `ebaa5443…` 的校验和已复核，可作为洞察站专用回滚目标。

## 2026-07-24 周期报告公开资产候选提升包

- 新 code release 为 `e0d57e921ffb54662f883635fb4f20a89ffde898d95293dd1e304178dace6240`，继续绑定生产当前 data release `reddit_voc_release_20260723_daily_v3`；未改采集器、cron、共享 Nginx、TLS、DNS、数据库或其他 Docker 环境。
- 生产只读基线通过：当前 code release `130e228cdf7e9d936a862b5a992533e21ae2d3df01b90889d1b5a0b9ec8571ad`，基线 receipt SHA `6f9755c3ac0fa8c59b1098eff9ae31bb630eaccb9962ea53c559a55622d0ad34`；采集器、翻译服务、58 个运行容器、cron、共享 Nginx、数据库和 18339 候选端口均保持稳定。
- 同一只读镜像完成 same-dist E2E、CSV/PDF/PPTX/DOCX 四格式真实下载和容器安全验收：E2E receipt SHA `7d336f03a6734e18c37f2db1912c36801ce851ace0cb733024e648336d55d065`，导出 receipt SHA `2114a538e5d383fc951314920ee3bad044db2bc423b21e31972337932f41ef41`，security receipt SHA `ddfcc4e8b5eac81faf65e97c7beca785c384e477ac7bcd012b6f15ae0f0d4c1e`。浏览器错误、同源 HTTP 失败和外部请求均为 0。
- 安全校验器已从旧版“零挂载”合同升级为双版本：v1 继续强制零挂载；v2 只允许唯一、精确、只读的 `${REDDIT_VOC_DATA_ROOT}:/srv/reddit-voc-data:ro`，可写或额外挂载均 fail closed。候选、promotion、packet replay、周期发布、release 与 V3 源码合同合计 74 项回归测试通过。
- 周期公开资产已纳入 native V3 promotion lineage：候选 UI validation receipt SHA `c4ebb361ca35ab7201bde7a9512b3430608c21063872f250d9e63c5cf4819905`，release manifest SHA `042e28710f92d6473f571a8dca8767ccd57cc0abf91a493c0d8584bcc13246ee`，transfer archive SHA `49bf173d6877be267323c0cf2da32e3818ae5a466c1a91123197ca931a06aa93`。
- 新 promotion packet 已生成并本地完整重放通过：packet SHA `a4ec5df32fc9a6c455904ce0f540ade29926847e1657d3bd220130c0ca8eda8b`，release SHA `e0d57e921ffb54662f883635fb4f20a89ffde898d95293dd1e304178dace6240`，有效期至 `2026-07-25T02:40:47Z`。当前 `promotion_authorized=false`、`consumed=false`、`deploy=false`、`remote_write=false`；必须由 Owner 精确确认这两个新哈希后，才允许创建 permit 和执行仅洞察站的受控提升。

## 2026-07-24 周期报告公开资产受控生产提升完成

- Owner 已精确授权 packet `a4ec5df32fc9a6c455904ce0f540ade29926847e1657d3bd220130c0ca8eda8b` 与 release `e0d57e921ffb54662f883635fb4f20a89ffde898d95293dd1e304178dace6240`；permit SHA 为 `af7b978b4c62c96f315d0f33080f136b5ccb911efa06d1709d0508634349065a`。
- 洞察站 code release 已从 `130e228cdf7e9d936a862b5a992533e21ae2d3df01b90889d1b5a0b9ec8571ad` 原子切换到 `e0d57e921ffb54662f883635fb4f20a89ffde898d95293dd1e304178dace6240`，data release 继续为 `reddit_voc_release_20260723_daily_v3`。生产容器使用唯一只读 bind mount `/opt/reddit-voc-insights-data:/srv/reddit-voc-data:ro`，只读 rootfs、UID/GID 101、健康检查均通过。
- 公网 HTTP 验收通过：13 个业务路由、8 个公开制品返回 200，20 个敏感路径返回 404；receipt SHA `62004aa5950be96d72e99f6e2210d9269d2684ef1320bafd6a7cf6d191cbeb0b`。Playwright 0.1.17 覆盖 desktop/mobile 共 26 页及三套周期报告，浏览器错误、同源 HTTP 失败和外部请求均为 0；receipt SHA `d99a4fb47df73a2e6cbe76d5ee30534b18f9f41fd0ff6b66bdec1be8981ecb12`。
- 生产只读复核确认 58 个运行容器库存稳定、候选容器与 18339 监听均为 0、数据库和报告指针稳定。采集器 ID `513f5e08…`、翻译服务 ID `29062314…`、重启次数均未变化；cron SHA `eab75d9586fa43c0531123a8780dff0286d36365fd233e7d635eef36b806705c`、共享 Nginx SHA `f466cffbcecf644f9b3107cba08872f9454280055f2f3ddfdf2db9295923cf2e` 保持不变。post-promotion baseline SHA 为 `e19005c709537c0536f2af570f3d16634eec3c4d0c70243a5e8fa1e229bb212f`。
- production acceptance SHA `ead3173a3384b45da7317e8daf98b4560ad7e12726dfc30f0585ed9dbaf98570` 已独立复验；consumption receipt SHA `2ef71fab8e1330d51f5c5bca6b732739c883da110c2d38d0cb339c59827c4599` 已封存并复验。授权已消费，远端隔离上传目录已删除，TLS、DNS、采集器、cron、共享 Nginx、其他 Docker 环境和钉钉发送均未修改。
