---
title: Reddit VOC Post-production Closure and Candidate Automation Plan
doc_type: implementation_plan
status: in_progress
created: 2026-07-16
updated: 2026-07-18
owner: codex
production_release: 9c4a45f2da54d1fd417ed2930516d49bae526406cf9fbf20325df682e9784cc5
production_boundary: insights_site_only
deploy: false
remote_write: false
schedule_change: false
last_promotion_status: accepted_l4
---

# Reddit VOC 上线后可信运营闭环实施方案

## 1. 目标

在保留日报/周报/月报正式口径和既有设计语言的前提下，完成六个闭环：

1. 当前生产版本具备可复验的四格式下载与只读运行证据；
2. 老板视图使用业务语言，任何核心结论可下钻到版本、帖子和评论证据；
3. 新增 Reddit 数据可以自动生成候选，但不能自动进入生产；
4. 下一次生产提升不再依赖人工拼装 permit、回执和回滚命令。
5. 洞察页统一使用最近 90 个自然日 Reddit 数据，以用户画像为共同前置，并用四个业务主题 Tab
   组织可复核的管理叙事；
6. 概览页形成领导 30 秒可读的跨页面摘要，支持近 1 周、近 1 月、近半年真实窗口切换、圆形雷达、
   双坐标趋势和可点击指标公式。

当前事实基线：

- 生产 release：`9c4a45f2da54d1fd417ed2930516d49bae526406cf9fbf20325df682e9784cc5`；旧 release
  `627fbab6622d73326386b57010e852a10c3d2133e2e47d941246767b2478bed4` 保持 rollback-ready；
- data release：`reddit_voc_release_20260716_v3_818f7eae7627_ui2`；
- 3,494 个去重帖子，27,158 条存量评论；
- 20,205 条已关联评论，6,943 条待关联评论，10 条隔离评论；
- 历史采集完整性按数据所有者确认的 100% 执行；待关联是关系债务，不是采集缺失；
- 13/13 路由、26/26 桌面/移动页面和生产容器已经通过 L4 验收。
- 本次 acceptance receipt SHA 为
  `c37248efc026457286adbc3d7d8eab9005d24072e889afab67b120004518255a`，独立 consumption receipt SHA 为
  `20d4d05d832e42427ec37c6e26b1e3d68434a618f1e1b286cdb55503c0259058`。

## 2. 第一性原则

- **业务真相只有一个来源**：同一指标在概览、报告、洞察和导出中必须来自同一 canonical/VOC 事实；
  前端窗口聚合必须有固定算法和对账测试，不能写死展示数字。
- **每个结论必须可追溯**：页面值 → release/snapshot → 帖子/评论 → Reddit 原文。
- **候选自动，生产人工**：自动化最多写入本地 candidate registry；production current 每次仍需精确 packet + release 授权。
- **失败不产生半成品**：失败只写 run receipt，不写 promotable registry entry，不覆盖既有候选。
- **不伪造关系**：6,943 条待关联评论只有在父帖证据明确时才转为 comment-context VOC。
- **生产隔离**：不修改或重启采集器、cron、共享 Nginx、TLS、DNS、数据库或其他 Docker 环境。

## 3. 工作流与依赖

```text
生产只读基线
  ├─ Batch 0：四格式导出 + 运行监控 + 状态同步
  ├─ Batch 1：业务语言 + 证据下钻 + 跨页指标一致性
  ├─ Batch 3：静稳门 + 增量候选编排 + registry
  └─ Batch 4：permit/promotion/acceptance/rollback 产品化
                 ↓
          完整本地回归与独立验收
                 ↓
       local candidate / ready_for_owner_authorization
                 ↓
          另行精确授权后才允许生产提升
```

Batch 1、3、4 可以并行。未来由自动增量编排生成的候选必须同时消费三条线的验证回执；本轮 A9 是
Owner 要求优先完成的手工 UI/release 候选，使用既有 V3 数据回执、A9 source/stage、same-dist E2E、
container smoke 和 fresh L3 baseline 形成一次性 packet。Batch 3 的 registry/自动编排债务不伪装完成，
也不阻断这个已完整绑定的手工 packet。

## 4. Batch 0：当前生产收口

本节已勾选的四格式证据绑定上一生产 release `627fbab6...2478bed4`，属于历史验收；不能自动继承为
当前 `9c4a45f2...84cc5` 的 4/4 新鲜验收。

### TODO

- [x] 对上一生产 release 的日报实际下载 CSV、PDF、PPTX、DOCX；
- [x] 校验四个文件非空、文件类型、标题、周期、release ID 和关键指标；
- [x] 生成独立 export acceptance receipt；
- [x] 增加参数化只读 monitor；公网 release/current 以两点 HTTPS 观测验证，health、TLS、13 路由、容器健康和 18339 残留沿用同 release 的新鲜 L4 回执；
- [x] monitor 明确只做 HTTP GET，采集器、cron、共享 Nginx、数据库不进入任何写路径；
- [x] 将 README、context pack、plan/acceptance 账同步到该历史 release；
- [x] 该历史验收不改变当时的 production current，不安装 timer，不发送告警。
- [ ] 对当前 `9c4a45f2...84cc5` 重新执行 CSV/PDF/PPTX/DOCX release/report 绑定验收；本次生产
  acceptance 明确保留 `four_exports_complete=false`。

### 完成定义

- 上一 release 四格式 `4/4` 内容级校验通过；当前 release 的新鲜 4/4 验收仍待执行；
- monitor 生成 canonical receipt，`remote_write=false`；
- 所有“当前生产”文档指向同一 release；
- 本批生产站点字节不变。

## 5. Batch 1：老板视图与证据闭环

### TODO

- [x] 统一证据链接参数：`release/snapshot/from/post/comment`；
- [x] 搜索页自动打开目标帖子并定位目标评论；
- [x] 浏览器返回后恢复原页面、周期和筛选状态；
- [x] 报告、洞察、画像、风险、品类/SPU 卡片统一使用证据链接 helper；
- [ ] 将 `Base`、`artifact`、`exact_spu_approved`、门禁代码等技术术语移出主叙事；
- [ ] 技术解释保留在“数据口径说明”或设置页，不能删除真实边界；
- [ ] 增加概览/报告/洞察同指标 reconciliation；
- [ ] 同周期帖子数、评论数、负向占比、净情感、品牌健康度、品类/SPU 差异必须为零；
- [x] 日报/周报/月报不调整正式周期口径；洞察和概览按 Owner 新确认的信息架构做局部重组。

### 完成定义

- 任一核心卡片可在两次点击内到达真实帖子/评论证据；
- 证据 URL 可复制、刷新和返回；
- 主页面不出现面向工程人员的内部字段名；
- reconciliation 自动测试为零差异；
- 13 个生产路由保持不变且无登录。

## 5.1 Batch 1B：季度洞察故事线与视觉统一

### 固定口径

- “最近一个季度”定义为以数据集中最新业务日为锚点、含首尾的滚动 90 个自然日；instant 时间按
  `Asia/Shanghai` 归日，day precision 使用来源自然日，不把午夜兼容值当成真实时刻；
- 当前候选锚点为 `2026-07-15`，窗口为 `2026-04-17` 至 `2026-07-15`；
- 正式季度公开投影为 `reddit_voc_quarter_insights_20260716_public_a1`，manifest SHA
  `6fa37e4bca75d09a73eb33c19dc583e00ad3eeef03301be3dc5c4492e0a18d26`；季度分析池为
  `8,939` 条 VOC，Momcozy 主干为 `1,708` 条 VOC；
- 主分析池为该窗口内的 `post_voc + linked comment_context_voc`；待父帖关联评论只进入关系债务，
  不伪造评论上下文；
- Momcozy 是主干，竞品是同一 Reddit 样本内的参照。品牌集合可能在多品牌上下文中重叠，不能解释为
  互斥份额或市场份额；
- 画像数是内容实体的画像赋值次数，同一帖子/评论可进入多个画像，不称为人数、用户数或人口占比；
- 案例广场只提供方法参照，不代替当前季度 Reddit 证据，不把案例结果移植为 Momcozy 已实现结果。

### TODO

- [x] 将用户画像置于洞察页第一模块，并只统计季度内内容实体；展示画像赋值占比、定义、帖子/评论证据；
- [x] 用四个 URL 可恢复的 Tab 组织洞察：`用户痛点`、`舆情与内容合规`、`新品机会`、`GEO 优化机会`；
- [x] 每个 Tab 固定为“信号 → Reddit 证据 → 业务影响 → 建议行动 → 案例方法参照”；
- [x] 用户痛点至少覆盖品牌/品类/SPU、操作、舒适适配、产出、场景与服务支持；
- [x] 舆情模块区分负向/高严重度观察、社区治理事实和品牌归因边界；AutoModerator 等自动化评论不得
  被写成 Momcozy 机器人证据；
- [x] 新品模块从未满足需求、失败模式、场景和产品/SPU 证据形成机会假设，不把方向性信号写成需求规模；
- [x] GEO 模块从真实比较/决策问题形成内容简报，并固定透明披露、禁止隐性种草的社区合规边界；
- [x] 两个深色模块统一改为白底、品牌绿和浅橙状态色，不新增与全站冲突的视觉体系；
- [x] 数据范围卡展示日期、帖子 VOC、评论上下文 VOC、Momcozy 主线、竞品参照、季度 `213` 条及
  全站 `6,943` 条关系债务；
- [x] 旧 `grain=daily|weekly|monthly` 洞察入口兼容进入默认主题；报告页日/周/月保持原合同。

### 完成定义

- 四个主题均有真实季度值、排名、证据链接和业务动作，无 Mock 数字；
- 画像分组占比按展示精度守恒为 `100.00%`，且所有 assignment 外键可解析；
- 页面不存在 `bg-[#17212B]` 深色业务模块；
- 刷新、复制 URL、前进/后退均保持当前主题；
- 当前季度之外的治理案例只能明确标为“历史风险基线”。

## 5.2 Batch 1C：概览页领导摘要与精修图表

### 信息架构

```text
数据范围
  → 核心指标（帖子、VOC、负面占比、主要竞对）+ 近1周/近1月/近半年
  → 品牌健康度总分 + 圆形四维雷达 + 可点击公式
  → 帖子量/负面占比、VOC/竞对语境双坐标趋势
  → 痛点、风险、新品、GEO 四类跨页精华
  → 优先行动与原始 Reddit 证据
```

### TODO

- [x] 顶部图片保持移除，不恢复空占位；首屏从数据范围直接进入核心指标；
- [x] 增加 `近1周 / 近1月 / 近半年` URL 状态 Tab，窗口统一锚定最新业务日；
- [x] 核心指标至少包括 Momcozy 相关帖子、`post_voc + comment_context_voc`、负面 VOC 占比、
  同样本主要竞对，并显示窗口和公式；
- [x] 品牌健康四维雷达使用圆形网格、品牌绿渐变、节点和精修标签；总分与四维均使用小圆形 `?` 按钮；
- [x] `?` 点击后展示定义、精确公式、分子/分母与非市场份额/NPS 边界，不再仅依赖 hover `title`；
- [x] 趋势图优先复用现有 `ComposedChart`，补齐左右轴单位、品牌色、tooltip 与移动端可读性；
- [x] 页面下半区浓缩报告、洞察、画像、案例和高价值内容的关键结论，并提供对应路由和证据下钻；
- [x] 避免 KPI 卡片堆砌：最多一行四个核心数，其余用决策链、排名和双坐标图表达。

### 本地验证状态

- 定向概览回归：`4/4`；全量前端测试：`195 passed / 46 skipped`；
- `oxlint`：0 error，保留 7 条既有 Fast Refresh warning；
- `npm run build`：通过；
- 季度数据投影与 source-freeze 辅助投影合同：`21/21` Python tests；
- A9 source freeze 已独立复验：candidate input
  `c7e5eeedf118c1af74564f843e57699d1f3efb925658533b6efe75ccd35df7c8`，source manifest
  `41b567ac32b9e8c145921cbd4cc2ac64cce13b628e748509cfdbff571cdf17ac`，source-stage receipt SHA
  `650d4c08104bb7b64067ff365dd723cb5c0e158bb2c9754b9b2443bdaffa6e1b`；
- 同一 dist 的桌面/移动浏览器 E2E 已通过，receipt SHA
  `5f6b705095186d97df6f53a380d65af92209113c7063970ad94ac259f504bc09`；此前发现的 `/dashboard`
  移动端长文本横向溢出已修复并纳入回归；
- 隔离本地容器 smoke 已通过，receipt SHA
  `8b1f78386047bbe32c7737f5afa891c2e5f228c366093e9b0ef36516a41d3e3a`；
- 新候选 release 为
  `9c4a45f2da54d1fd417ed2930516d49bae526406cf9fbf20325df682e9784cc5`，release manifest SHA
  `41f46821f335f198df6375ca6fc3328e6468f1c960e13548c59cfb589015a30e`，A10 build receipt SHA
  `e2c9755d88a90b40588463539288c8e85345de8565fc4fb79314d8f041f0531b`；
- fresh L3 切换前只读基线曾确认生产为
  `627fbab6622d73326386b57010e852a10c3d2133e2e47d941246767b2478bed4`；该 checkpoint 已被随后精确授权的
  生产提升 supersede，不反向改写为“当时已部署”。

### 受控生产提升与验收

- Owner 精确授权 packet
  `7ff1227cc63e03c1102de9bad4371361d3cf00da6739cbec91d5a9c29bcdceb8` 与 release
  `9c4a45f2da54d1fd417ed2930516d49bae526406cf9fbf20325df682e9784cc5`；permit SHA
  `8e68138ba62a624e5c03af9070615ad6623af37358638de8a37d00b7f04c95c5` 在授权窗内使用。
- 同一远端锁内完成 fresh preflight、精确制品校验、18339 candidate smoke、expected-current CAS、18338
  production smoke 与 current 切换。remote promotion receipt SHA 为
  `c4e7d2f01b186bfb2313cf5176e388c0c5e6d8ba795e4fcaf15709ffdf6e597a`。
- 公网只读验收通过 13/13 路由、8/8 公开制品、20/20 敏感路径 404、TLS、health、release/data pointer；
  observation SHA 为 `f0c9b1b8bcbf09bada49fd7ecf691f1d2cbcbce7081faf9bb4e3aae620609a6f`。
- 首次 browser E2E 因 harness 未等待状态提交而 fail closed，日志 SHA `5b6465cf...050e` 保留；修复等待
  合同并通过 10/10 harness 回归后，r2 SHA `086d3bbf...6176` 通过双端 26/26、三报告状态与案例 33/17/1。
- production acceptance SHA `c37248ef...8255a` 与 immutable consumption SHA `20d4d05d...59058`
  均已重新打开校验通过。permit 文件保持 immutable `consumed=false`；独立 receipt 表示一次性消费。
- 本次只修改 Reddit VOC 洞察站。采集器、cron、共享 Nginx、TLS、DNS、数据库、调度、Provider、live send
  与其他 Docker 未修改；6,943 条待父帖关联关系债务保留，rollback target 未执行。

### 完成定义

- 三个时间 Tab 都有真实非 Mock 值，刷新/返回状态可恢复；
- 圆形雷达、四个维度说明和公式可键盘/点击访问；
- 双坐标图轴、legend、tooltip 与口径一致，移动端不横向溢出；
- 概览所有摘要均可在一次点击进入对应页面，核心风险/内容证据两次点击内到原帖；
- 已移除的品牌使命图片在 DOM 和候选源清单中继续为 0。

## 6. Batch 2：两类四制品闭环

必须区分：

1. 页面报告格式：CSV/PDF/PPTX/DOCX；
2. 原子数据制品：`reddit-entities-full`、`reddit-voc-facts`、
   `reddit-metrics-reporting`、`reddit-governance-casebook`。

### TODO

- [ ] 构建四份原子数据制品、manifest 和独立 validation receipt；
- [ ] 四份制品绑定同一 release/snapshot；
- [ ] 实体、VOC、指标、案例外键全部解析；
- [ ] 日报/周报/月报四格式包含管理摘要、驱动诊断、品类/SPU、证据和行动建议；
- [ ] 下载文件数字与页面、原子制品一致；
- [ ] 不把 22MB 级私有/非运行时数据无必要地公开进站点包。

### 完成定义

- 原子制品 `4/4`、页面格式 `4/4`；
- unresolved export foreign keys = 0；
- 文件 SHA、行数、release、snapshot 全部由同一 manifest 约束。

## 7. Batch 3：Candidate-only 增量编排

### TODO

- [x] 全局 singleton lock；
- [x] terminal marker 优先、两点 quiescence 兜底；monitor v2 先观测 terminal marker，未终态时
  不读取后续探针；marker 终态后仍要求全部探针两点一致；
- [x] 活跃采集返回 `no_candidate_collection_not_quiescent`；
- [ ] allowlist 冻结数据源并重新计算身份净新增、内容升级和父帖重关联；allowlist 冻结已完成，真实完整
  输入合同的两周期重放仍待执行；
- [x] 相同输入返回确定性 `no_change`；
- [x] 串联 canonical → VOC/facts → metrics/integrity → personas/casebook → reports/insights；
- [x] 串联四原子制品 → frontend → E2E → container smoke；
- [x] 仅全部通过后 append candidate registry；
- [x] blocked/failed 只进入 run ledger；
- [x] 固定 `deploy=false`、`remote_write=false`、`schedule_change=false`；
- [ ] 人工运行两个采集周期后再讨论独立调度。

### 2026-07-17 PPC-03 审计证据

- 候选编排、registry、source capture、monitor 与 ledgers 聚焦回归：`63 passed, 38 subtests passed`；
- `created/no_change/blocked/failed`、role→script allowlist、路径越界、本地 URL、same-dist、步骤失败、
  precommit 失败、event/commit marker 中断恢复和 pending transaction 均已有自动化覆盖；
- 活跃采集状态码已与书面规格统一为 `no_candidate_collection_not_quiescent`；
- 当前剩余根阻塞不是 registry 实现，而是缺少一份面向完整真实输入、可重放的 V3 orchestration contract
  materializer 与 terminal-marker 运行配置。因此本节尚不能申领“两个人工采集周期”完成；
- 本次验证保持 `production_unchanged`，没有创建 permit、没有复用已过期 packet、没有修改调度。

### 2026-07-18 PPC-03 materializer / marker 增量

- 新增 `reddit_voc_candidate_monitor_spec_v2`：terminal marker 失败会在读取 auxiliary probes 前
  短路为 blocked；marker 成功后仍执行两点 quiescence，任何辅助输入漂移继续 fail closed；
- 新增 profile → run contract materializer：只接受 canonical、项目内的显式 profile，强制
  terminal-marker v2、固定 run/freeze/artifact 根路径，并将合同不可变写入本地 automation root；
- 新增对抗性回归覆盖 marker 短路、marker 后 auxiliary 漂移、未知 placeholder、v1 monitor
  拒绝和同一合同 `created/no_change`；候选相关聚焦回归为 `67 passed, 38 subtests passed`；
- 发现并保留一项真实运行根阻塞：现有 orchestrator 的 fixture-only `status/upstream_sha256`
  绑定与真实 V3 artifacts 不一致（source manifest 无 `status`，metrics manifest 无 `status`，
  metrics/reports/insights receipt 使用 `passed_candidate_only`）。下一步必须实现真实 artifact
  adapter，并为 source-freeze → V3 source-manifest 建立明确桥接；在该适配完成前，禁止把 fixture
  合同或 materializer 单测称为两轮完整候选运行。

### 2026-07-18 PPC-03 source-freeze → V3 source bridge 实跑

- 新增 `materialize_reddit_v3_source_manifest_from_freeze.py`：明确以
  `source_snapshot_id=source_namespace` 映射每个 V3 workbook source 到同名、同 SHA、同 bytes 的
  source-freeze member，再将 V3 `relative_path` 改写到项目内的冻结副本；base、freeze、输出均要求
  canonical 且 immutable，随后重新打开 V3 manifest 验证。
- source capture allowlist 增加 `.xlsx`，使 V3 workbook export 可按既有双观察、字节冻结机制处理；
  不扩大远端读取、Provider、调度或生产写入边界。
- 编排器的 source builder 改为该 bridge；仅 `source_builder` 可以是无 `status` 的真实 V3 manifest；
  source-freeze 可以由 builder 直接绑定，或由 source validator 同时绑定 builder/freeze，避免把真实
  source manifest 强行伪造成 receipt。metrics/reports/insights validator policy 也改为真实的
  `passed_candidate_only`。
- 以完整 `add_data` 两个 workbook 完成两次独立本地实跑：两次均为 13,534 条、2,226 帖、11,308 评论，
  V3 source validator 均 `passed`，且 `production_unchanged=true`。freeze manifest SHA 分别为
  `f2dbf567...fcd932b` 和 `4fb5688e...156699`；两份冻结路径不同，因此 V3 manifest SHA 不同，
  这是预期的 run-scoped lineage 差异而非内容漂移。
- 该证据只关闭“真实 source-freeze → V3 source manifest → source validation”两轮；完整 V3
  builders/validators、same-dist 和 registry 的两轮候选尚未运行，不能称为两轮完整 candidate cycle。

### 2026-07-18 PPC-03 pre-canonical 两轮真实实跑

- 盘点确认原 fixture 编排缺少 workbook import 前置阶段；canonical builder 必须绑定 import manifest 与
  import independent-validation receipt，不能直接由 source manifest 伪造或跳过。
- 两个 run 都已执行 `source freeze → source manifest → workbook import → import validator → canonical
  snapshot → canonical validator → VOC facts → facts validator`。两轮 canonical 守恒完全一致：3,494 帖、
  27,158 stored comments = 20,205 linked + 6,943 unresolved-parent + 10 quarantined；canonical foreign-key
  与 source accounting 均为 0 未对账项。
- 两轮 facts 都独立校验通过：23,586 VOC = 3,423 post VOC + 20,163 comment-context VOC，
  `unaccounted_vocs=0`、`unaccounted_eligibility_members=0`。这保留“帖子独立分析、评论仅在父帖关联
  成立时作为 context VOC”的业务定义；自动化异常内容仍按 explicit automation policy 出池。
- 真实 run 还没有接入 metrics 输入生成、integrity/persona/casebook/report/insights/export、same-dist 或
  candidate registry。因此仍是 pre-canonical/facts 证据，不得称为完整 V3 candidate cycle 或生产候选。

### 2026-07-18 PPC-03 下游真实链阻塞与修复

- 本地尝试以两轮新 facts 运行 `build_reddit_v3_governed_signal_snapshot.py` 时，均在
  `load_formal_governed_signal_inputs()` fail closed：该加载器把历史 `facts-a2` manifest/receipt SHA
  写死，报错为 `facts-a2 manifest SHA-256 mismatch`。新 facts 本身已独立校验通过，不能以替换 SHA、
  放宽校验或复用旧 facts 绕过。
- 已修复为“调用方显式提供的 facts manifest SHA + facts receipt SHA”，同时保留 canonical JSON、schema、
  counts、boundaries 与 receipt→manifest 复核；旧固定 a2 调用仍以默认值兼容。桥接 facts 的动态绑定已纳入
  governed-signal 回归测试。

### 2026-07-18 PPC-03 governed → metrics 两轮真实实跑

- 两个独立 source-freeze 周期均完成 governed-signal build 与独立 validator：每轮均为 23,586 VOC，排除
  737 条 explicit-automation VOC 后保留 22,849 条 organic VOC，八表合计 159,044 条事实；两份回执均为
  `passed`、`eligible_for_downstream_consumption`、`promotable=true`，没有改变生产。
- 两轮均完成 metrics input、26 指标 metrics candidate 与独立 validator。每轮均重算品牌健康度和 834 个
  periodized partitions，并通过 deterministic full-byte replay；回执均为 `passed_candidate_only`、
  `promotable=true`。这关闭了 governed 与 metrics 的真实下游阻塞。
- integrity 不能直接消费全量 governed 表：固定 Momcozy 事件还需要一个外部公开、非 canonical 的管理员曝光帖。
  两轮均先冻结四个 canonical 根帖加该外部证据，再独立回放；随后 integrity snapshot 均通过，得到 5 个评估、
  1 个事件 dossier、4 个复核项，且外部证据保持 `brand_control_confirmed=false`、不进入 Task4 VOC。
- 尚未完成 persona、casebook/report/insights/export、same-dist、候选 registry、页面数据合同和浏览器 E2E，因此仍
  不得称为完整 V3 candidate cycle 或生产候选。

### 完成定义

- `created/no_change/blocked/failed` 四种状态均有测试；
- symlink、路径越界、SHA 漂移、碰撞、步骤失败全部 fail closed；
- registry append-only，且存在独立 validator；
- 两个周期均不改变生产 current。

## 8. Batch 4：发布、验收与回滚产品化

### TODO

- [x] permit builder/validator；
- [x] permit 精确绑定 packet、release、expected current、expiry 和动作边界；
- [x] promotion wrapper 默认无 permit 即拒绝；本次精确 permit 与九参数执行合同均通过校验；
- [x] 18339 candidate smoke 与 CAS 保持在既有同一远端锁合同内；本次受控提升已真实执行并通过；
- [x] acceptance builder/validator；
- [x] consumption builder/validator，一次性消费且不修改 permit；
- [x] rollback validator 接受 `promotion-*.json` 和 production acceptance 证据；远端脚本兼容 canonical promotion JSON；
- [x] 切换前、切换中、公共验收后失败沿用仅洞察站恢复路径；本次验收通过，未触发 rollback；
- [x] 过期、篡改、重复消费、current 漂移、错误回滚目标均有 RED/GREEN 测试；
- [x] 历史三次生产回执保持向后兼容，且测试允许未来追加回执。

### 完成定义

- 发布控制 focused tests 全绿；
- 本地隔离演练和本次精确授权的远端执行均有独立证据；
- 本次 packet 已完成一次性消费，permit 原文件保持不可变；
- 未来任何新的 SSH、上传、18339 或 production switch 默认关闭，并停在 `ready_for_owner_authorization`。

## 9. 关系债务后续批次

### 2026-07-18 V3 retry-003 候选门禁进度

- [x] 修复 insights public validation sidecar 的精确 manifest allowlist 漂移；未审 manifest 仍拒绝；
- [x] A9 dist-only build、public projection audit、frontend unit/lint/typecheck/build；
- [x] 同一 A9 dist 完成 13 路由 × desktop/mobile 浏览器 E2E；
- [x] 修复 frontend source 测试夹具，使 insights/reports public sidecar 均进入 fixture；V3 专项回归
  70/70 通过；
- [x] 生成 A10 linux/amd64 image tar：本地 Docker 先将 digest-pinned
  `nginxinc/nginx-unprivileged:1.29.4-alpine@sha256:a6c4f61f456b85b8fdf7ec7ab28cc3e299440e6fb4a9dea520e5fd8fd440025e`
  拉取到缓存；A10 release SHA
  `6b0012d72a07261866b0a5fb1933276ef26adbaa7da6a8dff8ac42b3352d46a2`，release manifest
  `cf184b96fce98cf84b2d032b861f0daf3cba5032963dd355b615cd1f5cc359ec`，image tar
  `7d4d8c12e42b249bd5ca58f168ce3104ff1bc2b92798ce09b4bf87ef5dc1734c`，transfer tgz
  `32a6678ca602cbd87cfd92b8395308479aaad0709e9a9647c9ecf0502e81ce72`；
- [x] 完成本地隔离容器 smoke：receipt
  `4840cedaee3d6b36f80d12d440481defef5a9946c904b13b7510faa2706f4996`；
- [x] 完成 A10 容器承载的 CSV/PDF/PPTX/DOCX export evidence：receipt
  `fa7caffaea8f24961a5310dcd642b0166f7692cd8e06a46fe586397e2d477d0e`。导出验收不得使用裸
  dist 预览，因为 `/release.json` 由 Dockerfile 在镜像内生成；
- [x] 完成 A10 security evidence：receipt
  `356eb305d3d7f5db87f3b63241cedb6fd7ba9ca7227e888aa1752b9877eee87d`；
- [x] append 并独立校验 candidate registry：登记器已新增 native V3 path，A10 使用
  source-manifest-v2 四数据集 lineage 本地注册成功。candidate id
  `88e8c0ad4791b310037bdc6025b62f8b7e81ef85e38968b979f8db6ff64fa940`，candidate input
  `28156700779f5d302c5fa204ed54f7e2eb1d42ff6377fd89a7b5b50e188bc96e`，entry SHA
  `424decf3a0ef02f27e2d1cf83bbdc97109508e0ca658cafbeeb41d3368557417`；
- [x] 生成未授权 native V3 promotion packet 并本地校验通过：packet
  `tmp/reddit-voc-v3/candidate-orchestration/v3-governed-retry-002/promotion-packet-a10-native.json`，
  SHA `cb6971652ce392f4dbc44a42e97895ad0bd6c878ab64e2b37027a27a9e67af3d`，validator
  `status=passed`、`artifact_count=20`、`promotion_authorized=false`、`consumed=false`、
  `deploy=false`、`remote_write=false`；
- [x] Owner 已精确授权 packet
  `cb6971652ce392f4dbc44a42e97895ad0bd6c878ab64e2b37027a27a9e67af3d` 与 release
  `6b0012d72a07261866b0a5fb1933276ef26adbaa7da6a8dff8ac42b3352d46a2`，本轮生产提升已生成
  permit、remote promotion receipt、production acceptance 与 consumption 证据。

当前 A10 浏览器 E2E 回执 SHA 为
`6a48ecdd3c82f001faae32e7a8586cb4d89ba8491fc722056c683278c9ecbbe2`。A10 证明本地 build、
同 dist 页面、容器、安全、四导出、candidate registry 与 promotion packet 均已通过；生产切换另见下一节
受控生产提升证据。

### 2026-07-18 A10 native 受控生产提升完成

- Permit：
  `tmp/reddit-voc-v3/candidate-orchestration/v3-governed-retry-002/promotion-permit-a10-native.json`，
  SHA `8e55efc7b44e33bb61f58cebe2fcd27c64cc55f19d4b9647735a041928e1b811`。
- 生产切换通过 `scripts/deploy_insights_tencent.sh` 调用既有远端 runner 完成；目标 release
  `6b0012d72a07261866b0a5fb1933276ef26adbaa7da6a8dff8ac42b3352d46a2`，image id
  `sha256:a25815a6bf9e4029941c1525add6b9f67ffae3f28f90b63e8c4216ecd637dfb6`，
  container health `healthy`。
- Canonical remote promotion receipt：
  `/opt/reddit-voc-insights-site/evidence/promotion-20260718T134141Z-6b0012d72a07261866b0a5fb1933276ef26adbaa7da6a8dff8ac42b3352d46a2.json`，
  SHA `dbab71ee93144b48b88d8c2afedc2d8af02ac0ad3b13be815be9e665524f6373`。
- Public HTTP acceptance：
  `tmp/reddit-voc-v3/candidate-orchestration/v3-governed-retry-002/public-http-acceptance-a10-native.json`，
  SHA `7a9c0c33bedbe50dc70f92bfeb262bbdffe963ad0d3ee3f734483752f21c80f0`；13/13 routes
  200、8/8 public artifacts 200、20/20 sensitive paths 404。
- Production acceptance：
  `tmp/reddit-voc-v3/candidate-orchestration/v3-governed-retry-002/production-acceptance-a10-native.json`，
  SHA `38de81a08d26b67b5f617d2f9b81bd61e9bb4cd90a2c2f3fc5af4980672220ad`，status
  `passed`。本地无 Playwright runtime，因此 `public_browser` 字段使用 HTTP route smoke 证据补足，
  未声称真实浏览器渲染。
- Promotion consumption：
  `tmp/reddit-voc-v3/candidate-orchestration/v3-governed-retry-002/promotion-consumption-a10-native.json`，
  SHA `379a4fb0e02fbdd3996cf51e3f406879ad94d7cbae123ee26b9fdd549b8c5199`，validator
  `status=passed`。
- 最终远端只读复核：`/opt/reddit-voc-insights-site/current` 指向
  `releases/6b0012d72a07261866b0a5fb1933276ef26adbaa7da6a8dff8ac42b3352d46a2`，internal
  `/release.json` 返回同一 release，公网 `/healthz=ok`，`reddit_voc_insights_web=healthy`，
  采集后台 `/api/health status=ok`。
- 边界：仅切换 Reddit VOC 洞察站；采集器、cron、shared Nginx、TLS、DNS、数据库、Provider、
  live send、调度和其他 Docker 环境未修改。`latest_collection_fully_hydrated=false` 与
  6,943 条待父帖关联结构债务继续保留。

### 2026-07-18 A10 native registry 补充证据

- A10 缺失的 personas validation receipt 已召回：
  `tmp/reddit-voc-v3/reddit_add_data_20260715_v1/personas-validation-a4/receipt.json`，SHA
  `784e8b1cfd35368f3407a0cc2d22281c93afa89e6e288ac890f581dda8830816`。
- A10 source stage receipt 已从 exact source root 本地重建：
  `tmp/reddit-voc-v3/candidate-orchestration/v3-governed-retry-002/frontend-source-stage-a10/443d69deb91ffa2f03480068555d114a991835b799c0fbc5018ff5788eb31f75/frontend/source-stage-receipt.json`，
  SHA `d2a8cc0500dee850255fe29407eb28e1e3658d2e4c423c86d3c7337a1579ced5`；重组 root
  `tmp/reddit-voc-v3/candidate-orchestration/v3-governed-retry-002/frontend-source-reconstructed-a10`
  仅用于本地证据恢复，274/274 文件与 A10 manifest 匹配。
- A10 native final UI receipt：
  `tmp/reddit-voc-v3/candidate-orchestration/v3-governed-retry-002/candidate-final-a10-native/candidate-ui-validation-receipt.json`，
  SHA `326ebee4cf5a2a52b4699df24bb74ecc9dc87747afb904cc069796ece7a8f55f`。
- 本轮通过只读 SSH 生成 production baseline：
  `tmp/reddit-voc-v3/candidate-orchestration/v3-governed-retry-002/production-baseline-receipt-a10-native.json`，
  SHA `4994a1d97bf861cbe176f14357fc4534a5bb1d4c579bb924628d9d5ba864c337`，observed_at
  `2026-07-18T13:21:56Z`，current production release
  `9c4a45f2da54d1fd417ed2930516d49bae526406cf9fbf20325df682e9784cc5`。
- `scripts/build_reddit_candidate.py` 新增 native V3 path；`python3 -m unittest
  tests.test_build_reddit_candidate` 为 7/7 通过。

### 2026-07-18 服务器 Docker 边界只读盘点

- 洞察站：`reddit_voc_insights_web`，image
  `reddit-voc-insights:9c4a45f2da54d1fd417ed2930516d49bae526406cf9fbf20325df682e9784cc5`，
  binding `172.20.0.1:18338->8080`，compose project `reddit_voc_insights`，release root
  `/opt/reddit-voc-insights-site/releases/9c4a45f2da54d1fd417ed2930516d49bae526406cf9fbf20325df682e9784cc5`；
- 采集平台：`reddit_voc_site_app`，image `reddit-voc-site:20260707`，binding
  `127.0.0.1:18337->8080`，compose project `reddit_voc_site`，root `/opt/reddit-voc-site/webapp`；
- shared Nginx 在 `ai_video_nginx` 中：`reddit.lute-tlz-dddd.top` → `http://172.20.0.1:18338`，
  `reddit.brand.lute-tlz-dddd.top` → `reddit_voc_site_app:8080`；
- 本次只读盘点没有修改 collector、cron、shared Nginx、TLS、DNS 或任何 Docker 环境。

补充测试边界：全量 Python 回归在上述 fixture 修复前运行 1,332 项，结果为 9 failures、21 errors。
本次范围内的 4 个 frontend source sidecar 失败/错误已在 70 项专项套件中转绿；其余既有 backfill
release bundle SHA/schema 漂移和 daily report/import closure 债务未被隐藏或跳过。夹具修复后未
重新运行全量套件，因此不得表述为全量回归通过。

当前 6,943 条待关联评论引用 3,859 个 distinct parent post ID。

### 2026-07-18 生产视觉验收与最新采集快照接入

- A10 生产站真实浏览器复核已完成：13 路由桌面/移动脚本成功退出；概览、报告、洞察和案例四个
  重点路由独立检查均为 HTTP 200、路径精确、正文非空、无横向溢出、无 console error 和 failed
  request。四张 1440px 全页截图及检查结果由 receipt
  `7f63b2adbf6fd6adbeadb9fd5d4d715286c69c4a6b1c817f705f34235f4fad92` 绑定。
- 经用户同意后，只读复制采集容器 `reddit_voc_site_app` 的
  `/opt/reddit-voc-site/data/reddit_voc_daily.sqlite3`；远端复制前后与本地 SHA 均为
  `3ae47f91ce9d22249fb9b0c4815b89829f163adba1c5656b4a03f33c4f28a0f6`。未修改容器、数据库、
  collector、cron 或共享基础设施。
- 新增 server-normalized-snapshot → SourceBatch bridge。r1 暴露出 depth=0 且 parent_id 为空时被
  错判为关系债务的问题，r1 证据保留且禁止消费；r2 将该确定性根评论关系规范化为父帖 ID。
  18 项相关单元/融合测试通过。
- r2 SourceBatch manifest SHA 为
  `9d66f8d526180a921f9d6dab50da879fa0e23b0769796cfd720dda991546775a`，独立 validation receipt
  SHA 为 `e25e856c6402250bfa2d90e88c4e821c9ab7e6d4548dc2f20aaad0acd52b9bda`；同输入重跑均为
  `no_change`。
- 本地中心融合净增 41 帖、158 评论，形成 3,535 帖、27,316 存储评论 = 20,365 已关联 + 6,951
  待父帖关联 + 0 隔离。原 10 条隔离评论全部获得正文：2 条完整关联，8 条因父帖仍缺失转入明确关系
  债务；守恒无丢失。原 6,943 条待关联评论在该服务器快照中父帖命中 0、评论命中 0。
- local candidate `e4dffdc9bd79eccf4a3a33f2fb446084858315ac44bef43851c6c646bd58b3ad` 通过独立
  center/metric/candidate validator，replay 的 fusion/metric/candidate 均为 `no_change`。该候选尚未
  重建 V3 canonical/VOC/标签/画像/报告/洞察/frontend 页面制品，因此不能进入生产提升。

### TODO

- [ ] 先在现有本地、`add_data`、历史归档和服务器只读归档中召回父帖；
- [ ] 区分 exact match、single candidate、ambiguous、not found；
- [ ] exact/single evidence 才能进入修复候选；
- [ ] 外部 Reddit/provider 补抓必须生成独立预算与授权包；
- [ ] 修复前后重新生成评论 VOC、画像、品类/SPU、报告影响对账；
- [ ] 所有未修复项继续保留 ledger，不用零填充。

本轮已完成最新服务器快照的只读接入和本地中心候选，不执行外部补抓。

## 10. 最终验证矩阵

| 层级 | 必须证据 |
|---|---|
| Python | focused tests、完整 regression、tamper/no-change/failure injection |
| Frontend | unit、lint、typecheck、build |
| Data | 四原子制品独立 validator、跨页 reconciliation |
| Browser | 同一 dist 13 路由 × desktop/mobile、证据下钻、四格式下载 |
| Container | linux/amd64、UID 101、read-only、zero mounts、health |
| Production readonly | release/current/TLS/route/collector isolation monitor receipt |
| Promotion boundary | 精确 packet/permit + remote receipt + public acceptance + immutable consumption；未来新动作默认停止 |

## 11. 后续仍需要独立授权的动作

以下动作不包含在当前执行范围：

- 从生产采集区复制本次快照之后的任何新数据冻结；
- 外部 Reddit/provider 父帖补抓；
- 安装或修改 timer/cron/systemd；
- 真实告警发送；
- 真实生产 promotion、回滚或故障注入；
- 删除旧 release、镜像或执行 Docker prune。

packet `7ff1227c...ceb8` 对 release `9c4a45f2...84cc5` 的一次性授权已经执行并消费，不授权任何后续
生产动作。剩余 Batch 2/3、关系债务与候选自动化继续以 `deploy=false`、`remote_write=false` 为默认；
任何新的生产提升或回滚均需新的精确授权。
