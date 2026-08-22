---
title: Reddit VOC Monitoring Findings
doc_type: findings
status: active
created: 2026-07-07
updated: 2026-07-16
owner: codex
production_boundary: current_v2_iteration_production_unchanged
provider_call: false
live_send: false
---

# Reddit VOC Monitoring Findings

## 2026-07-16 Owner 确认后的实施路由

- V3 书面规格已获 Owner 确认；后续每个实现包必须能回链到该规格的对象、分母资格、数据状态、
  UI 语义和验收条款，不能把“已有相近功能”视为自动满足。
- 第一实施包必须优先证明 13,534 源行的文件绑定、解析、互斥 disposition、Reddit identity 去重
  和 `27,158 = 20,205 + 6,943 + 10` 评论状态守恒；在此之前不先做品牌评分或页面数字替换。
- 项目工作契约禁止未获明确指令的 commit，并默认不创建 worktree；因此本轮在现有
  `codex/momcozy-reddit-backfill-20260711` 分支实施，用独立测试/审查证据替代自动 commit 步骤。
- 生产边界不因书面规格确认而扩大：本地候选、生产 packet 和 L4 promotion 是不同证据层，当前
  仍为 `production unchanged`。
- 现有数据实现不是空白项目：`build_reddit_v2_raw_snapshot.py`、`build_reddit_site_snapshot.py`、
  `build_reddit_candidate_ledgers.py` 与对应 validators 已具备 identity、source occurrence、ledger、
  code-freeze 和 fail-closed 模式。V3 应新增窄职责 importer/domain modules 并接入这些构建器，
  不把两千行以上脚本继续扩成新的业务本体。
- 前端已有 `features/redditSnapshot` 数据服务、治理组件、日报/周报/月报视图、RadarChart、
  AggregatePersonaPanel、CaseGallery 与路由级测试；实施计划应优先扩展 snapshot schema 和复用组件，
  不恢复 `*Mock.ts` 作为真实页面数据源。
- V3 规格共有 24 个一级章节，实施依赖顺序以第 22 节为准；第一批代码验收必须覆盖第 20.1 的
  source-row 与 canonical-identity 双守恒，而不是只证明脚本可以读取 Excel。
- 两份 workbook 在当前 `openpyxl 3.1.5` 的非只读模式下可见实际范围 `A1:U12721` 与
  `A1:U815`，表头均为 21 列；导入器仍必须显式拒绝 read-only dimension 截断并验证范围，不能
  假设所有 Excel reader 都会忽略错误 cached dimension。
- 当前 `.venv` 是 Python 3.14.4、Unicode data 16.0.0。V2 继承合同写有 Unicode 15.0.0 的
  `nfkc_ws_v1` fail-closed 约束，因此实现不能直接把运行时 `unicodedata.normalize` 标记为
  Unicode 15.0.0；计划将 normalizer 版本和实际 Unicode table 一并写入 manifest，并以固定
  code-point fixture 验证行为，若要严格锁 15.0.0 需使用已冻结表而非伪报版本。
- workbook 的 `标题` 列在 reply 样本中确为完整评论正文，`舆情ID` 是来源记录 ID；导入器应从
  `舆情链接` 解析 Reddit identity，并把 `发布时间` 保存为 floating `source_calendar_date`，
  不派生 00:00 UTC。
- 当前 `SnapshotReports.tsx` 仍把 `current/archive` 暴露为业务双切换，并使用“当前闭合期/闭合
  归档”文案；V3 必须只暴露 `最新完整周期`，但保留六个底层 artifact 供比较与审计，不能删除
  archive 数据来实现 UI 简化。
- 前端 `SnapshotComment.is_bot` 当前声明为 `boolean`，而 A2 真实公开数据含 `null`；V3 数据合同
  应改为 `boolean | null` 并让 `explicit_automation`/metric eligibility 成为权威状态，不能继续依赖
  TypeScript 的错误窄类型掩盖 428 条待排除记录。
- `SnapshotDashboard` 已有真实 snapshot 服务、DataScopeBar、ReleaseEvidenceCard 和 Recharts 组件，
  但首页仍以四张数量卡开头且品牌样本提及面板保留能见度语义；V3 应在同一路由插入使命横幅与
  四维品牌健康总览，再将能见度保留为独立对比面板。
- 案例/发布只读映射确认四个阻断：默认搜索仍混入 12 legacy；CaseReference 四态、TTL、
  `review_reason` 与运营 CaseDossier/ActionMonitoringLedger 尚不存在；四处 validator/closure 仍
  硬编码 `approved_delta_count=0`；非空 delta 因此尚不能贯穿发布链。
- 画像 builder/validator 仍硬编码 exactly two personas，当前 2 画像/323 assignments/2 头像不能
  代表 82 原子事实与 8 cohort；现有头像 SHA、512×512、隐私和 assignment 守恒代码可复用。
- 当前浏览器 CSV/PDF/PPTX/DOCX 是报告展示导出，不等于规格定义的四份数据制品；尚无原子
  `reddit_voc_export_bundle_manifest_v1`、独立 validator、跨文件外键守恒或 current export pointer。
- `tests/test_validate_reddit_candidate_registry.py` 已存在但其导入的
  `scripts/validate_reddit_candidate_registry.py` 实际缺失，这是候选控制面真实断链，必须在最终
  candidate 包前补齐，不能用旧 promotion packet 绕过。
- 当前系统 Python、项目 `.venv` 与 Codex bundled Python 均无 `pytest`；部分历史测试仍依赖 pytest，
  但 Task 1 新测试已切回 stdlib `unittest`，定向命令必须显式带 `PYTHONPATH=src:.`。全量阶段需
  使用项目既有可复现 pytest runner 或补齐开发测试环境证据，不能把“pytest 不可用”当测试通过。
- 当前 cases 公开 manifest 精确冻结为 38 seed、12 legacy、0 approved delta；任何 V3 改造必须
  保持前两组内容 SHA 不变，只通过独立 eligibility/visibility ledger 改变默认展示资格。

## 2026-07-16 方案 A 最终体系决策与门禁结论

- 方案 A 是唯一生效设计：`brand_health_index_v2` 由口碑健康、产品体验、推荐信任、风险韧性
  四维组成；竞品能见度移出总分。内容诚信使用 C0-C3/I0-I4 独立治理，不用疑似信号重复扣分。
- 数据全收口与经营分母分开：所有可解析 Reddit identity 去重后进入 canonical/provenance；帖子
  独立形成 `post_voc`；评论只有真实根帖上下文完整后形成 `comment_context_voc`；每项指标再有
  独立 `reddit_indicator_id × comparison_side` 资格账。
- 设计级融合评论向量冻结为
  `27,158 stored = 20,205 linked + 6,943 unresolved-parent + 10 quarantined`。其中 42 条虽 linked
  但根帖上下文不完整，仍不进入 comment-context 分析。`unaccounted_total=0` 不关闭 1,179 open
  coverage 与 18 pending lineage。
- 12,720 完整范围导出允许 `query_profile_status=owner_attested_unknown` 进入 Momcozy 单期内部
  指标，但状态为 provisional；未证明逐期 source/retrieval/coverage hashes 一致前不做趋势，
  未证明竞品 query 对称前不做 SOV、份额或竞品差。
- 产品问题率冻结为 AND 语义：同一实体至少存在一个 promoted negative `product_problem` fact；
  产品体验、PS-02、PS-03、PS-04 使用同一成员集合。held/unprocessed/failed 不得按健康值 0。
- 当前 bot 审计基线绑定本地 Base A2 manifest/comments SHA 与 matcher，为 540 detected、112
  excluded、428 still included。显式 automation 排除必须前置到品牌指数前，并写
  `excluded_reason=explicit_automation`；它本身不是 Momcozy 商业归属证据。
- Momcozy 版主事件链只冻结为 `C2+I3/subreddit_moderator`。首个运营 dossier 当前使用四个
  canonical roots + `1u2gvn4` external reference + 16 evidence-only comments，hydration 前保持
  `review_required`；不得命名为“已确认品牌机器人项目”。
- V3 书面规格经两轮独立对抗复审最终达到 P0=0/P1=0，可供 Owner 审阅；尚未获得详细实施、
  本地候选或生产变更的授权与证据。

## 2026-07-16 完整范围导出与治理审计新证据

- 用户提供的版主曝光线索已核实为连续事件链，而非单条普通用户传闻：
  `1kkvihg`（2025-05）描述 planted users/员工式推广与封禁；`1l2aofi`（2025-06）描述对版主
  警示帖的举报/影响感知；`1n2q1do`（2025-08）记录版主团队曾人工审核所有 Momcozy 提及；
  `1o1pqox`（2025-10）提供创作者商业邀约截图线索；`1u2gvn4`（2026-06）再次称 AI bots/
  bogus accounts 大量出现且账号已被封禁。发帖者/回复者以版主管理经历自述，帖子带社区公告
  flair。该链可证明社区版主公开指控和治理动作，不能单独证明涉事账号由 Momcozy 公司直接控制。
- 上述证据按双轴应记为 `commercial_relation=C2`（可重复商业传播模式）与
  `integrity=I3`（外部 subreddit moderation action）。只有拿到具体账号—内容—归属链、官方
  affiliate/员工关系、品牌确认或 Reddit 平台裁定并完成人工复核，才能晋级 C3/I4 并使用
  “已确认不当干预”。
- 五条根帖的本地覆盖不完整但可守恒：当前 Base 已有 `1kkvihg/1l2aofi/1o1pqox`；12,720
  完整范围工作簿新增 `1n2q1do`；814 负向工作簿只含 `1u2gvn4` 的 16 条评论，缺公开根帖。
  因此该事件链不能被一张工作簿的 source eligibility 一刀切：根帖/评论各自保留 provenance，
  814 行实体仍 evidence-only，公开根帖经独立 hydration 后可按自身来源资格评估。
- 当前自动分析对这组高价值样本存在 P0 语义错误。`1kkvihg` 的正文是在说推广账号“不断回来”，
  系统却因 `keep coming back` 命中 `L0-NPS-007` 而标为正向；`1l2aofi` 和 `1o1pqox` 均被标为
  中性低风险。需要新增 `community_governance_event`、`integrity_allegation`、
  `moderation_action`、`commercial_affiliation_claim`、`consumer_trust_impact` 原子事实，保存
  speaker role、target、evidence span、claim/observation 区别和外部验证状态。
- 未检索到 Momcozy 对该 Reddit 事件链的官方回应，也未获得 Reddit 平台对品牌归属的公开
  裁定。规格必须提供反证/回应入口和 `disputed|unanswered|confirmed|retracted` 生命周期，
  不能把“未找到回应”解释成默认承认。
- 案例广场深审确认，当前是参考外链目录而不是业务闭环。38 seed 内容应保持不可变；12 legacy
  继续保留但默认排除；新增 `verified-seed ledger` 与独立运营案例 sidecar，首个高价值案例册
  应以“社区信任与非自然推广风险”为业务问题，当前绑定四个本地 canonical 根帖、
  `1u2gvn4` external public reference、其 16 条 evidence-only 评论、报告版本、行动建议、owner、
  监测指标和复盘证据；根帖 hydration 前保持 `review_required`。
- 当前非空案例增量无法贯穿发布链：candidate closure、独立 validator、public projection 和
  frontend source manifest 都硬编码 `approved_delta_count=0`。因此“案例广场只打通增量”是
  P0 发布合同改造，不只是 UI 增加卡片。
- `ai_nlp_voc` 的核心复用边界已完成对抗确认：版本化字典、闭集 normalizer、幂等身份、
  fail-closed gates 和六段式故事线可复用；扁平 text candidate selector、旧指标 SQL、启发式
  alias、Reddit→AIPL=A、AIPL prior→画像、NPS/ROI/销售类指标禁止照搬。Reddit 原生 registry
  应为 19 项：DH 5、BR 5、PS 4、IN 5。

- Owner 已直接确认大工作簿 12,720 行未按情感、严重度、互动量或人工案例筛选。该声明解决了
  “是否按结果筛选”的业务事实，但尚需用绑定文件 SHA 的 source manifest 固化导出范围、查询
  条件、分页/覆盖、时间精度和行数守恒，避免未来批次口径漂移。
- 目标资格为：12,720 行经 identity 去重、Base overlap anchor、正文完整性和 source manifest
  validator 后进入 `eligible_scoped_observation`，从而进入品牌指数；在实现验证前不得把设计目标
  误报为已完成数据晋级。814 行全负向工作簿继续 `outcome_conditioned_negative/evidence-only`。
- “所有 Reddit 帖子进入分析池”被解释为 canonical identity/provenance 全收口，而非所有实体
  无条件进入每个指标分母。缺正文帖子仍可进入身份账本，待补正文后可重入打标；重复身份只增加
  provenance，不增加 VOC 或品牌指数分母。
- Momcozy 不当干预审计必须采用中性证据术语：单信号仅能标记 `suspected`，账号自动化、协同
  推广、未披露关联或平台操纵需要多信号一致和人工复核；来源归属和意图不可由文本相似度单独
  推断。Owner 已选择方案 A：I1/I2/C2/I3 不直接扣减品牌健康总分；真实用户对事件的负向 VOC
  仍按自身情感/推荐/风险事实进入分数，只有 C3+I4 人工确认实体从 qualified-organic 剥离。
- 案例广场的下一版目标不是扩大默认链接集合，而是让已验证高价值案例承接洞察、证据、建议
  动作、责任人/状态、监测指标和复盘结果；38 条存量继续保留，新增仍走独立准入与链接健康门禁。
- 早期 1,299/12,837 snapshot 的 494/112/382 bot 审计已被新本地 pointer supersede。当前本地
  Base `reddit_voc_site_snapshot_20260715_candidate_a2` 按冻结 regex 复算为 540 条显式 bot 自述，
  112 条已排除、428 条仍为 `is_bot=null` 且进入 VOC；manifest SHA 为
  `2d387bb4...38b1b`。这证明显式 bot/template 排除必须前置到指标资格 gate，并绑定 snapshot 与
  matcher version，不能把这些数量复制成跨 release 常量。
- 12,720 行工作簿虽然声明了 `作者/浏览量/转赞评数量/粉丝数量` 列，但本批作者全部为空，
  三个数值字段全部为 0，且发布时间只有自然日精度；因此本批无法验证账号年龄、跨社区发帖率、
  小时级爆发、投票异常或关联账号网络。任何“机器人/水军/品牌操纵”结论都超出当前证据。
- 仅作为候选筛查，商业披露/号召词典命中 175 条，其中 158 条同时提及 Momcozy；但单词
  `gifted` 本身命中 109 条且语义可能只是“收到礼物”。这些只能进入 lexical candidate queue，
  不能直接计为违规、广告或品牌关联内容。
- Reddit 2026-05-19 官方规则把重复或未经请求的大规模互动、为曝光/获利批量发布重复内容、
  用 bot 持续推广产品、多个账号/自动化操纵投票列为禁止或潜在违规；同时明确平台会组合用户
  举报、版主和内部系统信号。我们的外部数据没有这些平台内部信号，因此只能做“疑似风险分层”，
  不能替代 Reddit 的违规裁定。
- `ai_nlp_voc` 当前唯一状态入口明确区分旧产品化链与新 raw/batch 链，且指出新链仍缺字典 mapping
  与 production backflow 合同。可复用的是 manifest 闭集、输入/字典/模型/生产四层 gate、三种
  coverage、L0-L5 洞察可用性评估和六段式故事线；不可把旧 SQL、NPS、AIPL 或跨用户追踪公式原样
  搬到 Reddit。
- 当前案例对象只有标题、描述、来源、URL、分类、标签、日期和核验 provenance；没有关联洞察、
  evidence IDs、行动 owner、状态、目标指标或复盘结果。现有 manifest/同源 index/SHA/三键去重
  可保留为“内容准入层”，其上需新建独立的“业务应用层”，避免修改 38 条策展内容本体。
- 当前 `caseService` 实际把 38 条 curated seed、12 条 `legacy_unverified` 和 approved delta 合并后
  全部交给默认搜索；测试也断言当前返回 50 条。这与已审规格“12 条待核验不进入默认搜索”相冲突，
  属于实现 P0 口径差距：内容继续保留，但默认高质量视图应只消费 verified/default-eligible ledger。
- Base A2 与 `add_data` 的设计级身份并集为 3,494 个帖子与 27,158 条存储评论：Base 1,322/
  16,591 加净新增身份 2,172/10,567。该数字是去重目标账，不等于已完成融合、文本可分析量或
  品牌指数分母；仍需独立 importer/validator 复算后才能成为候选数据事实。
- “完整范围导出”只解决结果筛选偏差，不自动证明 Momcozy 与竞品的查询曝光机会对称。12,720
  行中约 70% 文本提及 Momcozy，且导出缺少可用互动/作者字段；因此可先晋级 Momcozy 范围内的
  观察量、情感、问题和画像指标，跨品牌能见度仍需 query profile 对称性门禁。建议把资格从来源级
  总开关改为 metric-family 级资格。

## 2026-07-15 V2 add_data、双粒度 VOC 与标签指标体系审计

- 两份 `add_data` workbook 已按实际 OOXML `sheetData` 只读盘点；其声明的
  `dimension=A1` 均错误，普通按 dimension 读取会得到假空结果。实际数据为
  `12,720 + 814 = 13,534` 行，其中 `2,226` 帖子行、`11,308` 评论行。
- Reddit URL 身份去重后为 `2,226` 个帖子、`11,305` 条评论；3 行评论为同 ID 重复。
  与 Base A2 精确重合 `54/738` 后，净新增身份候选为 `2,172` 个帖子与 `10,567`
  条评论。固定优先级为 `existing governed canonical > add_data workbook`，重合只补
  provenance，不用 workbook 的日精度时间、源情感或概要覆盖 Base。
- Owner 已明确双粒度事实模型：每个帖子独立形成 `post_voc`；每条评论与一个父帖形成
  `comment_context_voc`，唯一键为 `(post_id, comment_id)`。一个帖子有 N 条评论时，
  产出 `1` 条帖子 VOC 与 `N` 条评论上下文 VOC；帖子、评论上下文和线程分母分别发布。
- 父帖在评论上下文中只用于指代消解和可审计的品牌/品类/SPU 上下文继承。标签命中保存
  `evidence_scope=post_body|comment_body|cross_context`；父帖独有的问题、情感或画像标签
  不得复制成每条评论的命中。
- `parent_post_context` 固定为根帖 title/body 经 `nfkc_ws_v1` 后至少一个非空；3,582 条
  文本可用评论上下文包含 4 条 title-only 根帖，若强制 body 会错误降为 3,578。
- source-text 交叉证据同样固定为 `nfkc_ws_v1` normalized-exact：NFKC、Unicode 空白折叠、
  trim，不做 lowercase/HTML/Markdown/标点改写。raw 匹配为 24/54、688/738，归一化后才是
  39/54、731/738；hash 为归一化 UTF-8 的 SHA-256。
- 净新增帖子中 `2,105` 个已有正文、`67` 个待补正文。净新增评论中 `10,500` 条有正文、
  `67` 条待补正文；`3,624` 条身份可关联父帖，其中 `3,582` 条已具备完整父帖正文和
  评论正文，`42` 条父帖正文待补。另有 `6,943` 条评论指向 `3,859` 个尚未进入
  canonical posts 的根帖，统一显示为“暂未匹配到所属帖子”，全量留在可重入账本。
- 当前终局守恒为 `13,534 = 3 duplicate + 792 Base overlap + 5,687 text-available +
  6,943 unresolved-parent + 109 incomplete`；109 由 67 个缺少 source post text 的帖子和
  42 条已关联但根帖 title/body 为空的评论组成。
- 对 `/Users/pray/project/ai_nlp_voc/system_data/voc_data/reddit` 的 `136` 个帖子和
  `4,153` 条评论只读交叉未补出这些根帖。candidate closure 命中的 3 个根帖均仍为
  rejected/pending lineage，仅影响 4 条评论，未通过前不得伪造或强制关联。
- `发布时间` 只有自然日精度，全部标记 `event_time_precision=day`、
  `source_timezone=unknown`；可进入日/周/月，不进入小时桶。小 workbook 的 814 行源情感
  全为负向，大 workbook 源情感全空，均不得覆盖统一 governed sentiment。
- 可形成 VOC 不等于可进入经营分母。814 行已按 `outcome_conditioned_negative` 冻结为
  evidence-only；12,720 行源情感全空不能证明无筛选，在查询条件、导出范围、分页/覆盖和
  非结果筛选证据补齐前为 `pending_source_manifest`。两者均可入身份/证据/闭集打标，但
  biased/unknown-only 实体不得进入观察量、能见度、情感率、品牌指数、画像占比或跨期趋势。
- Base 精确重合的 54/738 只有在 Base 自身存在独立合格 observation lineage 时，才由 Base
  充当 metric anchor 且 canonical 实体计一次；workbook 只补 provenance，不能重复计数、
  污染字段或给 biased-only 实体“洗白”。
- Owner 附件 `dim_tag_v6.3_final.csv` 与 `ai_nlp_voc` 同名字典字节级相同：2,346 个唯一
  tag、28 字段、SHA-256 `22664c9c446ddfa17446852079f507ab75b5af3d4dde6e4e3f3e44c195582e14`。
  可复用事实源还包括 82 个原子 persona tag、8,854 条标签-指标映射、43 个 canonical
  indicator 和 43 条故事线触发规则；旧销售/ROI/NPS/用户追踪指标与旧阈值不得照搬。
- 82-tag persona dictionary 含 454 个 keyword instances、425 unique、28 shared 与 5 个
  brand/platform templates。旧 82-tag matcher 是裸子串且默认可调用 provider，存在
  `app` 命中 `happy` 风险；V1 改为 provider-free token sequence、evidence span、A/B 固定
  confidence、held 闭集与 TECH 唯一互斥组。
- 评论与根帖通常不是同一作者，因此 comment persona facts 只消费当前 comment body；
  父帖可帮助品牌/SPU/topic 消歧，但不得把身份、阶段、偏好、场景或情绪复制给 N 条评论。
- Legacy registry 的 43 canonical rows 声明 79 aliases 且当前 collision=0；mapping 26 code、
  storyline 33 code、声明 alias 后交集 19。Reddit V1 禁止启发式后缀回退，冻结 19 个原生
  指标和 daily56/weekly26/monthly24 的 nearest-rank 标定；旧固定阈值只作 reference。
- 对抗复核进一步冻结了跨实现字节合同：root post 的 link/permalink/t3-parent 候选须一致；
  analysis fields 用 canonical JSON；NFKC/whitespace 固定 Unicode 15.0.0；persona tokenizer、
  segment、overlap、A/B 聚合和所有 arrays 稳定排序；registry payload 不自哈希，calibration
  series/median/ID/canonical JSONL 可独立复算。
- 修订后的书面规格通过两轮独立门禁，最终均为 P0=0/P1=0，状态
  `ready_for_owner_review`。这仍是设计证据，不是代码、数据候选或生产验收。
- Reddit 第一阶段链路冻结为：双粒度 VOC → 品牌/品类/SPU 路由 → 闭集候选裁剪 →
  规则与证据门禁 → entity-tag facts → Reddit 专属 indicator registry → 日/周/月报告和
  六段式洞察故事线。第一版 `provider_call=false`，高风险或低证据命中 fail closed。
- 当前仅完成只读数据证据与书面规格修订；未修改前端业务代码、生产数据、采集器、cron、
  shared Nginx、TLS、DNS 或其他 Docker。旧 promotion packet 不复用，`production unchanged`。

## 2026-07-15 Plan A A3 resumed implementation checkpoint

- The resumable A3 baseline is local-only: Base A2 manifest
  `de8b504d...6443`, ledger manifest `bcc1ac74...f87639`, and the only
  consumable independent ledger receipt `5700b8e4...bc913` remain the frozen
  identity gate. The preliminary `ledger-validation-a2h` and all A2g outputs
  remain superseded.
- Semantic compatibility projection `semantic-a3b/semantic-governance.json`
  (`5997dd8a...e816`) retains 20/20 promoted assignments and 83/100 reviewed
  compatibility assignments. Configuration `config-a3` is identity-bound, but
  persona source-priority and downstream public/reconciliation work are still
  open; no A3 artifact may be called a production release.
- The next bounded work is independent competitor-context validation, persona
  source-stratum closure, and public-projection fail-closed fields. All work in
  this checkpoint has `provider_call=false`, `database_write=false`,
  `remote_write=false`, `deploy=false`, `live_send=false`, and
  `production unchanged`.
- The report builder now emits competitor-brand current metrics, ranked topic/
  pain/community/risk-tag dimensions, previous-period and year-over-year
  comparisons, and an explicit no-taxonomy boundary. The independent analytics
  validator still validates only Momcozy/report structures, so A3 must add an
  independent recomputation before rebuilding analytics; otherwise a rehashed
  competitor payload could pass validation.
- The independent validator now reconstructs competitor brand groups directly
  from Base entities and validates current observed/negative metrics, ranked
  topic/pain/community/tag dimensions, no-taxonomy boundaries, period baselines,
  deltas and trend flags for all six reports plus the Insights command center.
  A rehashed observed-count tamper is rejected. Focused proof is Python compile,
  risk/report contracts 21/21, and analytics validator 9/9 green.
- A direct analytics-builder help probe failed with
  `ModuleNotFoundError: No module named 'reddit_voc'`; the project CLI contract
  requires `PYTHONPATH=src`. Re-running with that environment exposed the
  expected snapshot/semantic/config/as-of/output arguments without changing
  any artifact. A3 plan text confirms analytics must precede Personas/public,
  with final reconciliation only after all downstream manifests exist.
- The immutable config materializer consumes the reusable coverage, risk and
  persona templates plus exact A2 ledger/r2 receipt identities. Because the
  persona source-priority template is changing, `config-a3` cannot be edited or
  reused as the final identity; a new `config-a3b` root must be generated and
  all later Personas/final manifests must bind its new persona-config SHA.
- First targeted Pyright exposed two validator narrowing errors because the
  generic `_check()` helper does not narrow `row.get()` from optional to list;
  the check was changed to an explicit fail-closed `ValueError`. The separate
  test-file Pyright error is only the global environment lacking pytest stubs,
  while the cached uv pytest runtime itself remains green; final static proof
  therefore targets production modules and reports test-import availability
  separately.
- Public projection now fails closed when a v2 report is downgraded or omits
  `observed_count_comparisons` / `product_period_analysis`; it also validates
  previous-period/year-over-year post/comment groups and category/family/SPU
  arrays before allowlisting. Agent proof: 9/9 projection tests, Pyright clean,
  py_compile clean, and six existing A3 reports validated by paths from
  `report-index.json` rather than guessed archive filenames. Cases remain
  38 selected, 12 unverified, approved delta 0.
- Persona config now includes the previously unknown-but-governed
  `tencent_existing_post_comment_hydration` stratum in source priority. The
  synthetic SVG sources are repository-governed under
  `docs/superpowers/assets/reddit-voc-evidence-personas/`; downstream builders
  should copy those exact assets and keep their synthetic/not-real-user label.
- Main-thread independent rerun confirms public projection py_compile, Pyright
  0/0/0 and 9/9 pytest green after the v2 field-gate changes.
- No implementation currently exists for the final
  `candidate-data-reconciliation-ledger.jsonl` / outer manifest/receipt. The
  approved spec requires one candidate row binding baseline, cutoffs, freeze,
  old/new identity hashes, all four detail-ledger SHAs, coverage/quarantine
  transitions and Base/Insights/Reports/Personas/public manifests. The ledger
  must not self-hash; only the outer manifest and independent receipt record its
  file SHA.
- `config-a3b` materialized with exact A2 gate and manifest SHA
  `a1136bd7...7ccf`; its persona config now has six governed source strata and
  SHA `28c3bc21...861b`, while coverage/risk hashes remain unchanged. The root
  is mode 0700 and all recorded bytes/hashes validate; 15/15 materializer tests
  pass. However, its three payload files are mode 0644, not the Plan A private
  artifact requirement 0600. Treat `config-a3b` as superseded until the writer
  enforces file modes and a fresh immutable config root is built.
- The config writer now explicitly publishes a 0700 root and 0600 files, and
  immutable equality includes root/directory/file modes so permission drift
  fails closed. A public-mode tamper test was added; py_compile and Pyright are
  clean and the materializer suite is 16/16 green. The next final config and
  dependent dataset versions therefore use the fresh `a3c` identity.
- Final consumable config candidate is `config-a3c`, manifest SHA
  `70ded635...75029`: root 0700, all four JSON files 0600, all recorded bytes/
  hashes exact, A2 ledger/r2 receipt gate exact, and risk policy remains draft.
  Its persona-config SHA is `2f0c783e...34aca`; `config-a3` and `config-a3b`
  remain superseded and must not be selected by directory scan.
- The analytics writer had the same private-artifact mode gap. It now rejects
  symlinks/unsafe entries and hardens the staging root/directories to 0700 and
  every file to 0600 before atomic publication. Writer mode assertions were
  added; py_compile/Pyright are clean and all 21 risk/report contract tests pass.
- Fresh private `analytics-a3c` was built from Base A2 + semantic-a3b +
  config-a3c: Insights manifest `fe70e2ed...0d5f4`, Reports manifest
  `237a0601...f5832`, six reports, status
  `passed_provisional_risk_threshold`. This is builder evidence only until the
  exact semantic/source/ledger/r2-bound independent validator passes.
- Persona hardening converted publication to atomic immutable/no-change output,
  0700/0600 private modes and deterministic collision-safe receipts. Its first
  targeted Pyright run exposed the same generic `_check()` non-narrowing issue
  in validator source-priority parsing; this is a static typing defect, not a
  runtime data failure, and was changed to an explicit fail-closed branch before
  rerunning tests.
- Persona hardening then passed py_compile, Pyright 0/0/0 and 27/27 tests.
  Real `personas-a3c` independently validates with manifest
  `3f5e96d4...a14cf`: two synthetic-avatar evidence cohorts, 323 assignments,
  two promoted source tags, exact Base/Insights/config lineage and private-tree
  modes. The receipt is deterministic and mode 0600; no tag-repair overlay or
  new semantic review was claimed.
- Independent analytics validation passed and wrote receipt SHA
  `34eefd33...a896f`: six closed-window report states, 42 Insights risk themes,
  17 product scopes, 46 rolling-30 competitor brands, current/archive counts
  `75/509`, `146/2845`, `250/2304`, `28/350`, `88/849`, `103/660` (posts/VOC
  comments). All report windows remain partial; daily/weekly comparisons are
  unavailable and monthly comparisons provisional, so no unsupported trend
  direction is claimed. Analytics and Personas trees are 0700/0600 exact.
- Rolling-30 competitor context is now operationally populated rather than a
  placeholder: leading observed entities include Spectra 12 posts/311 comments,
  eufy 3/197, Medela 10/65, Baby Buddha 1/65, Baby Brezza 2/33 and Elvie 2/29.
  These are same-sample observations, explicitly not market share/SOV/sales;
  competitor product taxonomy remains unavailable because no governed catalog
  exists.
- Case-store source of truth is exactly two public JSON files under
  `public/data/cases`: manifest SHA `6a233c0e...6b969` binds 38 bundled seed,
  12 legacy-unverified and 0 approved-delta cases; index SHA
  `a1da92f8...5cd68` contains the empty approved delta. The selected/unverified
  stock is bundled content rather than duplicated in the incremental index, so
  final reconciliation must validate manifest counts plus approved-delta array,
  not incorrectly expect 50 rows inside `case-index.v1.json`.
- `public-projection-a3c` was created as 21 files / 30,102,047 bytes with
  canonical path+bytes+SHA inventory `d460f8b8...a16ea`; public Base/Insights/
  Reports/Personas manifest SHAs are `2d387bb4...38b1b`,
  `58b1d7bb...eacb6`, `84e5fbd0...bbb2e`, and `3f5e96d4...a14cf`.
- An initial generic forbidden-key scan reported many `title/content/body` keys,
  but that rule was overbroad: governed public Base records intentionally
  allow Reddit title/content/body for evidence browsing, while analysis
  artifacts separately forbid copied source/author/private strategy fields.
  Final independent validation must apply those two different allowlists rather
  than erase required public evidence or mislabel it as a privacy leak.
- Analytics independent validation now also enforces 0700 dataset directories,
  0700 nested directories, 0600 files and no symlinks. A mode-tamper test was
  added; Pyright is clean and the suite is 10/10 green. The only consumable A3c
  analytics receipt is now `analytics-validation-a3c-r2`; the earlier A3c
  receipt is superseded because it predates this permission gate.
- Base A2 manifest claims `production_private_snapshot_mode=0600`, but its six
  payload files were actually 0644 (root 0700). The future snapshot writer now
  hardens the entire atomic staging tree to 0700/0600 and the v2 fusion suite is
  10/10 green. Full-module Pyright remains 29 pre-existing optional-container
  typing errors around lines 1337-1684, unrelated to this mode change; do not
  relabel that module as Pyright-clean.
- Base A2 was permission-hardened in place from 0644 to 0600 without changing
  any of its six content SHA-256 values; manifest SHA remains
  `de8b504d...d6443` and root/files are now 0700/0600. This metadata-only repair
  preserves every downstream content binding and the accepted A2h identity.
- Main-thread frontend persona contract rerun is 9/9 green. The loader now
  permits only the six governed source strata, while the currently served
  production fixture remains at its historical 233 assignments; the new 323
  candidate assignments are not claimed as deployed.
- Real immutable reruns are closed: config-a3c returned `no_change`; Personas
  returned identical 323-assignment bytes and its receipt `no_change`; public
  projection returned `no_change`; analytics r2 validation receipt returned
  `no_change`. These reruns did not rewrite the candidate content or claim any
  deployment side effect.
- Broader regression remains green: Insights/Reports/semantic pytest 19/19;
  frontend 22 files / 136 tests pass. `oxlint` exits 0 with five pre-existing
  Fast Refresh warnings in `src/components/reports/shared.tsx`; this batch did
  not hide or rewrite those unrelated warnings.
- Final closure inputs are now path-resolved without directory scanning at
  runtime: source-freeze manifest `0d7dc292...a8233`; frozen RC3 acceptance
  `deee7ec9...b787cc`; frozen baseline Base manifest `a900e6ce...ac3abd`;
  config `70ded635...75029`; analytics r2 receipt `5b237001...99906`; persona
  receipt `4ee758df...cca1b`; cases `6a233c0e...6b969` / `a1da92f8...5cd68`.
  The case files are not members of source-freeze-a1, so closure must bind their
  explicit paths and expected SHAs as a separate preserved UI-stock input.
- Structured public-candidate check confirms 1,322 posts / 16,581 linked
  comments, 42 risk themes, 46 competitor brands, 17 product scopes and all
  323 persona assignments. Every one of the six public reports retains
  `observed_count_comparisons`, `product_period_analysis` and competitor
  context; this is public artifact evidence only, not browser/deployment proof.
- Independent adversarial audit found no new P0 business-data error in A3c but
  correctly keeps final closure blocked on two evidence gaps: the reconciliation
  ledger/outer manifest/receipt do not yet exist, and public-projection-a3c has
  builder validation but no separate validator/receipt. A dedicated public
  validator is now required before final closure.
- Audit P1 is resolved by the approved thin-layer direction rather than a full
  cascade rebuild: the outer closure manifest/validator must bind config-a3c
  manifest plus coverage/risk/persona SHAs, and separately bind the Cases
  38/12/0 manifest/index. Analytics itself remains content-valid; neither gap
  justifies inventing config lineage inside already-built manifests.

## 2026-07-12 Historical Backfill Findings

- The reviewed 55-file Momcozy seed corpus is external to this repository under
  `ai_nlp_voc/system_data/voc_data/reddit/Momcozy`. That repository already has
  extensive unrelated dirty state; this task used it read-only and made no
  external-repository edits.
- Direct source parsing and a separate formal-importer run in a system temporary
  directory produced the same `55/48/7`, `48/1,894/1,942`, and `45/3/0`
  contracts and the same two data-derived hashes.
- The baseline expected values are repo-reviewed constants, not values derived
  from the future staging DB being validated.
- The release manifest exact-covers 22 reviewed runtime files; the manifest
  itself is owner-reviewed separately and intentionally contains no self hash,
  `.env`, key, pem, credential, run database, raw payload, report, or delivery
  artifact.
- Historical collection is a separate isolated lane from the existing daily
  production collector/report/send flow. Prior live operations do not authorize
  Provider calls, production merge, or sends for this backfill.
- Task 12 must enforce `lsof` availability and zero concurrent openers before
  the pinned-inode seed path. Any missing `lsof` or concurrent opener is a stop
  condition.
- Task 12 exposed an external-environment hazard: BaiduNetdisk opened the raw
  archive and created 48 upload sidecars. After owner-confirmed pause and
  cleanup authorization, the sidecars were removed; repeated inventory checks
  and independent re-audit proved a stable exact 58-file snapshot with SHA-256
  `4149f5663936fca0cab78f28140d9f94af76a36c408c7cb3d86ea557eb6bd12d`.
- Task 13 proved the real dynamic-search cursor at
  `data.search.dynamic.components.main.pageInfo.endCursor`, with schema SHA
  `5a84fbe4871635778aaf66ff75c03feb6cdaa857d1f274a8befa40038a7416dd`.
  Two pages spanned `170383.602` seconds, produced 9 unique candidates and 406
  occurrences, and used two successful Provider attempts.
- The stale repository SSH identity no longer reaches the host. Historical
  backfill server commands must require an explicitly supplied repo-external
  identity rather than silently default to the ignored project PEM.
- A UID-0 one-shot image creates new private probe artifacts as root-owned mode
  `0600`; owner review therefore used a temporary sudo-installed review copy
  and removed it afterward without changing the staging original.
- Task 14 option B froze 15 dynamic and 15 reviewed-subreddit lanes with the
  exact cumulative cap `670`. All attempts succeeded, but the first `Momcozy`
  dynamic lane consumed every page; the remaining 29 lanes committed zero
  pages. The first lane's oldest seen timestamp after 670 pages was only
  `2026-06-18T20:48:35.770000+00:00`, so the two-page probe span was not a safe
  cursor-depth budget predictor for the 2025-01-01 start.
- Task 14 cursor evidence is internally sound: `669/669` links matched, 670
  payload hashes and response cursors were distinct, and duplicate cursors were
  zero. The partial result is a real budget exhaustion, not a cursor loop.
- Replay has a confirmed occurrence-normalization defect. Collect preserves
  partial identity fields for invalid rows; replay clears those fields before
  strict equality. This dataset has 16,013 partial-identity invalid rows, so
  replay fails at page 1 and atomically removes its unpublished target. Formal
  full validation cannot run without that replay DB.
- The local 2026-07-13 repair closes that defect with one shared
  `discovery_occurrence_contract`. It preserves parsed partial identity fields,
  includes title in the invalid predicate, and keeps `[start, end)` window
  semantics. Python 3.11 backfill `261/261`, full-suite `344/344`, and
  independent review are green.
- The historical Task 14A candidate manifest SHA is
  `ec5548c6606e587ae8d9d18809ae643553a03306a44ef2371867a64659a52253`.
  The Task 14 executed SHA `471dc848...fb949e` remains historical evidence;
  neither SHA authorizes remote replacement by itself.
- The later owner-authorized versioned transfer succeeded without changing the
  historical bundle, but its single network-disabled replay still failed on
  `discovery_occurrence_mismatch`. Read-only diagnosis found page 1 ordinal 3
  has parsed `post_id` present while the frozen source occurrence stores null
  identity/time fields. The earlier interpretation as mixed persistence
  semantics was not proven because it compared rows only by ordinal.
- Task 16 traced a stronger mechanism: collector archived canonical
  `sort_keys=True` bytes but parsed the original dictionary; replay parsed the
  canonical dictionary; discovery traversal follows dictionary key order. A
  controlled `z/y/a` versus `a/y/z` fixture reproduces the ordinal-3 symptom
  while the page contract multiset remains exactly equal. Collector now parses
  the archived bytes, and replay checks an exact page-level Counter before
  reconstructing frozen source order. Tamper tests retain strict ordinal,
  artifact, capture-time and field integrity. Backfill `263/263`, full suite
  `346/346`, manifest `22/22`, and independent review are green.
- The current local candidate manifest SHA is
  `0663168b890cbd858068548eb3b43ee70345e01854090f42ae0baf91ac9fe0ba`.
  Task 17 transferred its exact bundle and used its one authorized replay.
  The occurrence mismatch was closed; replay then failed at
  `discovery_checkpoint_mismatch`.
- Read-only Task 17 diagnosis found 30 discovery checkpoints but only one
  artifact lane. The other 29 checkpoints are all page zero,
  `partial/budget_exhausted`, and legitimately have no artifact. At Task 17,
  the replay set-equality check rejected them after processing the 670-page lane;
  there is no page-count mismatch for the artifact lane.
- Task 18 replaced only that invalid set-equality assumption. Artifact-bearing
  lanes keep their existing strict page/artifact/occurrence path; a
  checkpoint-only configured lane is copied only for the exact page-zero,
  all-zero-count, all-`None` cursor/time state with partial manifest/run/lane,
  exact budget stop/error and globally exhausted request cap. No artifact is
  fabricated. Unknown lanes, positive pages without artifacts, non-partial or
  not-yet-exhausted state, empty strings, SQLite REAL values and every tested
  field drift remain rejected.
- Task 18 local evidence is focused `5/5`, validation `56/56`, offline full
  suite `351/351`, manifest `22/22`, independent review `APPROVED`, candidate
  SHA `c6d289329443a92ed59c5849fa9fbfe15afc854df709497351c1b7003fd9b2dc`.
  This layer is `provider_call=false`, `provider_attempt_made=false`,
  `remote_transfer=false`, `live_send=false` and `production unchanged`.
- Task 19 later transferred that exact SHA-versioned bundle and executed its one
  authorized network-disabled staging replay. Replay returned
  `complete/replay_complete`, source and target fingerprints were equivalent,
  and replay DB SHA is
  `3504190ab2b80ad1a003da27574455802f4184499eeaa7d458a6b771c3a8c638`.
  Source DB/raw archive, Provider `670`, delivery and production remained
  unchanged. This closes deterministic replay only; it does not establish full
  historical coverage or Task 14 acceptance.
- Task 20 is `local_verified` for an append-only budget-extension ledger,
  hydration-resume ledger, bounded round-robin discovery and strict offline
  discovery reindex. Evidence is combined regression `243/243`,
  validation/replay/reindex `108/108`, serialized offline full suite `445/445`,
  canonical reviewed files `22/22`, independent review `PASS_NO_P0_P1`, and
  manifest SHA
  `347c6ede1fe36852509dffe051fa7bf2b4d0c1e24ead8dda1af085bc44ff9d94`.
  This is local machinery evidence, not complete historical coverage.
- Task 21 transferred that exact manifest bundle and consumed its one authorized
  network-disabled staging reindex. The attempt failed closed on
  `strict_discovery_schema_unknown`; no target DB was published. Postflight
  passed every invariant and proved source/raw and production unchanged with
  Provider/live-send false.
- The remote snapshot has `670` discovery artifacts, all legacy
  `tikhub_discovery`. Pages `1–35` are non-empty and every one fails strict-v2;
  the `635` passing pages are empty. On `33` pages, whole-payload discovery
  mistakes `SearchTelemetryTrackingContext.post` metadata for extra content
  containers; pages `6` and `14` contain valid `SearchCrosspost` wrappers that
  the `SearchPost`-only whitelist rejects. Payload hashes all match.
- The explicit content path has `241` SearchPost plus `2` SearchCrosspost rows.
  It derives `238` eligible candidates and `5` outside-window rows with zero
  invalids; candidate set and first provenance exactly match the frozen source.
  Independent review classified the parser, whitelist and fixture gaps as three
  P1s, not P0s, because the remote attempt failed closed without a target or
  production/input mutation.
- Task 20 fixtures proved strict-v2 and deliberately unknown shapes, but did not
  include the two real legacy mixed-wrapper shapes. Passing local counters
  therefore established machinery behavior, not compatibility with the frozen
  remote archive. The next repair must be driven by exact structural fixtures
  and retain negative tests against genuinely ambiguous alternative containers.
- Task 21R added those exact structural fixtures and closed only the observed
  compatibility gap. Content recognition is limited to `SearchPost` and
  `SearchCrosspost`; the telemetry exception requires the exact reviewed
  typename, wrapper-key set, nested post-key set and location below an accepted
  content wrapper. Telemetry outside content, key drift and unknown nested
  wrappers remain rejected.
- The new read-only corpus audit does not derive success from fixture counts. It
  binds a single-link, sidecar-free source DB by SHA, snapshots it through a
  pinned descriptor, verifies the complete raw archive and runs the same strict
  plan that enforces candidate-set and first-provenance equality. It rechecks
  source/raw state before returning and performs no database write.
- Task 21R evidence is reindex `26/26`, related regression `200/200`, complete
  runtime full suite `452/452`, and canonical `22/22` candidate manifest SHA
  `88f3d58c89980ed0c685796c340c6752c11f5394e61409f6beeb8a4303b3938f`.
  The system Python lacked `Pillow` and `openpyxl`, causing seven import errors;
  this was an environment failure, not passing evidence, and the full suite was
  rerun under the configured complete runtime.
- The frozen DB/raw corpus is not local. Consequently, the expected remote
  `670/670`, `241/2`, `238/5/0` and exact parity values remain a future
  read-only gate, not a result of Task 21R. No subagent or independent review
  was used by explicit owner instruction.

Current historical-lane boundary is `staging_only`, `production unchanged`,
`provider_call=true`, `provider_attempt_made=true`, request count `670`,
`actor_run=false`, and `live_send=false`. Task 14 collect is partial; Task 19
replay is complete/equivalent, but formal full validation and acceptance were
not generated, so Task 15 remains unauthorized. Historical bundles and their
permanent exactly-once guards remain immutable. Task 20 itself is `local_only`,
`provider_call=false`, `ssh_used=false`, `remote_transfer=false` and
`production unchanged`. Task 21 has now used and consumed its authorized remote
attempt. Task 21R is `local_verified`, but its real-corpus gate, any second
remote reindex and Task 22 Provider continuation require separate explicit
authorization. The
earlier BaiduNetdisk sync observation remains historical
evidence and must not be rewritten as `external_network_call=false` for the
environment.

## 2026-07-09 Current Findings

- Current workspace was still not a Git repository at the start of this loop; root `.gitignore` must exist before `git init` so secrets and runtime artifacts are not accidentally staged.
- `ai_video.pem`, `data/`, `outputs/`, `logs/`, `tmp/`, and local CodeGraph databases are runtime/local-only and must stay outside Git.
- `codex` CLI is installed, but `codex init` is not a supported subcommand in this environment. Use `.codex/context-pack.md`, `.codex/session-thread.md`, and `codex doctor` as the local Codex project setup and health evidence.
- `.codegraph/` already exists, but `codegraph` is not available in the current PATH. Do not claim a fresh CodeGraph sync unless the executable is restored and `codegraph sync/status` passes.
- The production scheduler target is now two-stage: `0 7 * * *` collect-only and `0 8 * * *` report/DingTalk under `CRON_TZ=Asia/Shanghai`.

## Historical Findings

## Repository Findings

- Current workspace is not a git repository.
- No project-level `AGENTS.md` was found in `/Users/pray/project/Reddit_VOC` or parent directories checked.
- No `.codex/context-pack.md` or `.codex/session-thread.md` exists in this workspace.
- Existing semantic documents are:
  - `Reddit_VOC_Monitoring_Plan.md`
  - `Reddit_VOC_Adversarial_Audit.md`
  - `analysis-reddit-voc-flow-first-principles-draft-20260707.md`
  - `require/01-商品及同行玩家+a6a468df-f7dc-47d2-8b37-a33b655a5726.md`

## Collection Findings

- Plain backend HTTP access to Reddit `.json` should not be treated as the same thing as browser-authenticated `.json` access.
- The accepted collection priority is:
  1. Local browser login state plus Reddit `.json` or DOM.
  2. Agent-Reach/OpenCLI as command router over the local browser state.
  3. browser-harness as real Chrome CDP control and fallback probe layer.
  4. TikHub for high-value completion, fallback, or partial production collection.
  5. RSS for discovery and health fallback only.
  6. browser-use for exceptional browser diagnostics, not deterministic daily core.
  7. last30days-skill for retrospective research reports, not daily collector core.

## Boundary Findings

- `production unchanged`
- `provider_call=false` for current planning work.
- `live_send=false` for current planning work.
- Real browser collection is not yet proven in this workspace for Reddit target threads.
- TikHub live calls are not authorized in this planning step.

## 2026-07-14 Task 22C and Task 23 Findings

- Provider-level success and parser acceptance are separate evidence layers:
  Task 22C received HTTP-successful subreddit and comments payloads but stopped
  fail-closed because their concrete shapes were not in the reviewed contract.
- Real subreddit discovery uses `data.subredditV3.elements`; reviewed organic
  posts are CellGroup nodes with Metadata, Title or TitleWithThumbnail, and
  Action cells. A reviewed empty lane can return `elements=null`.
- Real terminal comments pages can place `pageInfo` under
  `data.postInfoById.commentForest` and omit `endCursor` while explicitly
  declaring `hasNextPage=false`. This exception must stay scoped to the reviewed
  comment contract; it is not a generic missing-cursor fallback.
- Salvaging the Task 22C failure database would require special migration of
  failed candidates, batches and zero-page comment checkpoints. A clean fresh
  copy of accepted Task 21S state is smaller, safer and more auditable.
- The Task 22C shell runner's mawk-incompatible process scanner demonstrated
  that scanner errors must hard-stop before Provider guard arming. Future
  runners use a tested Python scanner and must fail closed on scanner failure.

## 2026-07-14 Task 23 Remote Findings

- Task 23 proved that the first reviewed subreddit fixture was not sufficient
  to model live nonempty subreddit pages. Every one of the 114 real edges has a
  nonempty `crosspostCells` array that mirrors cell typenames; rejecting any
  nonempty value therefore rejects all live content before organic-cell checks.
- The mirror is still structurally constrainable: observed entries normally
  contain only `__typename`; the observed `CrossPostCell` mirror additionally
  contains `innerPost`. This can be fixture-driven without accepting arbitrary
  nested containers.
- Live main-cell composition is not a three-cell tuple. Organic rows retain one
  Metadata, one Title and one Action cell but add explicitly observed
  Flair/Preview/Image/Gallery/Empty/CrossPost/Margin cells. Ads and SortCell rows
  remain separable by exact typenames and key sets.
- A comment payload can be semantically parseable while pagination is not
  resumable. The archived page produced eight comments and one `more` node but
  declared `hasNextPage=true` without any cursor. It must not be accepted as a
  terminal page; it should instead preserve explicit incomplete coverage.
- Hydration failure isolation is too broad for historical recovery. One
  comments cursor failure changed all 252 selected candidates and all nine
  detail batches to failed even though the detail response contained 30 posts.
  The next repair must isolate the affected candidate/batch and keep unrelated
  work resumable.
- Provider transport, parser acceptance, pagination completeness and structured
  persistence remain four separate proof layers. Task 23 had `32/32` successful
  Provider attempts and `26/26` postflight invariants but still did not add any
  structured thread/comment/analysis rows.

## 2026-07-14 Task 24 Findings

- The 114 nonempty `crosspostCells` values are useful integrity evidence when
  treated as an exact typename mirror; accepting arbitrary nested values would
  weaken the parser and is unnecessary.
- Parseable comments and resumable pagination are separate contracts. A page
  can add valid structured comments while remaining terminally incomplete as
  `unresolved_more`.
- Task 23's database is recoverable only because its failure footprint is exact:
  all 252 candidates and nine batches share `comments_schema_drift`, only one
  detail batch and one comments page were archived, and no affected structured
  rows were committed. Any mismatch must stop recovery.
- Resuming an already approved `702/1200` budget is not a budget extension. It
  requires a separate source/candidate/lane-state authorization ledger so
  evidence does not mislabel the side effect.
- Offline recovery and Provider continuation cannot share one precomputed SHA
  packet: the recovered target SHA and candidate state are outputs of recovery.
  They must be observed first and bound into a later packet.

## 2026-07-14 Task 25 Findings

- A discovery checkpoint's `provider_request_count` records the cumulative
  request number at the time that lane stopped; it is not expected to equal the
  final manifest count after later lanes and hydration run.
- All 14 real schema-drift lanes have an exact recoverable page relationship
  (`checkpoint page 0`, one sequential archived page 1), but their request
  numbers are `686-689,691-700`. Requiring each to equal final count `702`
  rejects all 14 and produces `strict_discovery_page_chain_invalid`.
- The next repair must bind a checkpoint to its own successful Provider attempt
  and endpoint, not merely weaken the condition to `<= manifest count`. Missing,
  failed, out-of-range and endpoint-mismatched attempts must remain fail-closed.
- Recovery failure and postflight failure are separate facts. The recovery
  correctly returned a failed envelope with no target; the first operational
  postflight then incorrectly assumed a success target existed. A failure-aware
  postflight is required, but it must not convert recovery failure into success.
- Task 25 consumed its one-shot guard. Source DB/raw, Provider `702/1200` and
  production remained unchanged, so a future retry must use a new reviewed
  manifest/bundle/packet and a separate explicit authorization.

## 2026-07-14 Task 26 Findings

- Checkpoint request count is request attribution, not the final global request
  count. A safe repair needs exact attempt ownership rather than a weaker
  numeric `<= final_count` condition.
- Exact ownership includes request number, run ID, succeeded status and the
  expected endpoint. A boolean is not a valid request number even though Python
  treats `bool` as an `int` subclass.
- Recovery outcome and postflight verification are separate states. A verified
  failure postflight must preserve `status=failed`; it only proves that the
  failure was contained and left no prohibited residue.
- Realistic tests must include multiple earlier discovery attempts followed by
  later detail/comment attempts so fixtures do not accidentally encode final
  count as the discovery checkpoint count.
- The historical validation module retains a Pyright baseline of 205
  diagnostics when checked alone. Task 26 added-code ranges and its helper
  scripts are clean, but module-wide static cleanup is a separate scope.

## 2026-07-14 Task 27 Findings

- The remote code SHA directory was already installed when the approved batch
  resumed; it passed a fresh recursive 23-reviewed-file plus manifest hash
  audit. Reinstalling would have violated the fresh-directory/no-overwrite
  contract, so the existing exact directory was preserved.
- The one-shot recovery repaired 14 schema-drift discovery lanes and added
  seven candidates without calling Provider. Recovery status `complete` means
  the archive-to-staging transformation completed; it does not mean the
  historical run is complete.
- The recovered target has 258 pending candidates and seven missing detail-batch
  members. These are the measured inputs for the next Provider-continuation
  packet; they must not be inferred from the old 252-candidate failure state.
- The first postflight failed on reviewed-module bytecode residue, not on source
  or target data. A postflight-only repair removed exactly 14 `.pyc` files,
  preserved the one-shot guard, and final postflight passed all invariants.
- Provider, live-send, source DB/raw and production remained unchanged. The
  recovery target is isolated staging-only and requires a new acceptance gate
  before any Provider continuation.

## 2026-07-14 Task 28 Findings

- Provider continuation must bind the recovered target DB SHA and its full
  candidate/batch/checkpoint state; reusing the Task 27 packet would lose the
  seven candidates that are not currently assigned to a detail batch.
- The recovered target has 498 requests remaining below the approved 1200
  ceiling, but that is a ceiling, not permission to spend them. A separate
  Provider packet and owner authorization are required.
- The candidate packet records 30 lane page ceilings, pending-state SHA and
  missing-member SHA. It is not executable authorization and carries
  `provider_call=false`.
- The first continuation path must not require its own ledger row before the
  loader returns, because the CLI records that row immediately afterward. The
  loader still fails closed when an existing row does not exactly match the
  packet. The continuation packet must bind the original source DB SHA, not
  the recovered target SHA.
- The recovered state already contains 702 provider attempts, so the
  continuation packet must use `expected=702`, `discovery_ceiling=702`,
  `hydration_reserve=498`, `max=1200`; `702/700/500/1200` fails the CLI header
  before any Provider call.
- Corrected continuation completed 969 successful Provider requests and
  stopped at `candidate_failures`; 12 candidates remain failed and need a new
  read-only state freeze before any further request budget is authorized.

## Local Probe Findings

- `browser-harness` executable exists and shows help output.
- Browser-harness skill exists at `/Users/pray/.codex/skills/browser-harness/SKILL.md`.
- `browser-harness --doctor` reported Chrome running but daemon/connections failing.
- A direct `browser-harness` `page_info()` call later succeeded, but it read the user's current Gmail/TikHub tab; future Reddit validation must use `new_tab()` and avoid clobbering user work.
- `agent-reach doctor --json` reports Reddit backend `off`; OpenCLI or rdt-cli must be installed/configured before Agent-Reach can be a Reddit collector route.
- RSS backend is available through feedparser and remains a fallback/discovery route.
- Read-only sidecar analysis disagreed with the user-preferred priority and suggested RSS as MVP mainline; this project keeps the user-confirmed browser `.json`/DOM first route while preserving RSS fallback and coverage warnings.

## Loop 1 Findings

- `codex` CLI has no `init` command in this environment; project initialization must be represented by local `.codex/context-pack.md`, `.codex/session-thread.md`, plan files, and executable project scaffolding.
- CodeGraph initialization works and should be rerun with `codegraph sync .` after meaningful code changes.
- `unittest discover` does not run bare pytest-style functions; tests were converted to `unittest.TestCase` and run with `PYTHONPATH=src`.
- CLI global options originally only worked before subcommands; CLI now accepts common args on both parser and subcommands.
- Current local MVP is fixture/manual JSON only. It proves storage, analysis, dry-run delivery, and loop gates, not browser Reddit collection.

## 2026-07-14 DeepSeek L2 Semantic-Fix Execution Findings

- Formal README/context/plan status still described the earlier L1-only,
  no-key/no-provider boundary. Newer isolated evidence supersedes it: one L2
  URL-fix shadow made nine successful `deepseek-v4-flash` translation requests
  and failed closed before semantic validation on `protected_entity_changed`.
- The earlier URL-fix result exposed a local translation-contract mismatch, not
  a Provider transport error: ordinary product categories and natural-language
  units had been configured as byte-for-byte protected English values. The
  later semantic-fix attempt does not identify its exact offending value.
- The semantic-fix candidate preserves numbers, exact currency expressions,
  brands, models, competitors, URLs and Reddit references while allowing
  ordinary product categories and natural-language units to translate.
- Candidate validation passed translation `19/19`, report contracts `11/11`,
  release integration `95/95`, TikHub mapping `9/9`, release/import verification
  and copied-database preflight, all without an additional Provider call.
- The exact replacement packet is
  `deepseek-l2-semanticfix-replacement-20260714-175924`, SHA-256
  `70dba4a85d7b963120bd963baee1b78b9b623c95ec9c6938cbe46acf1d1e8940`.
  It retains a cumulative cap of 100 DeepSeek attempts, of which nine are
  already consumed, leaving at most 91 additional attempts.
- The owner approved this exact next-step plan in the current Codex task. The
  authorization covers isolated key read/copy and one L2 replacement shadow;
  it does not cover send, alert, production writes, Docker/Colima mutation,
  L4/L5, deploy, cron/service changes, commit, push or merge.
- Evidence-grade decision: `allowed-with-label` at L2 authorized shadow. A
  completed shadow cannot be promoted to human acceptance, host release-ready,
  production prepared-report acceptance or delivered-report evidence.
- The repository still has no commits and all project files are untracked, so
  Git history cannot serve as provenance. Exact content-addressed manifests,
  packet hashes and immutable evidence directories are mandatory.
- The authorized semantic-fix replacement did not reach real-provider entity
  acceptance. It received 9/9 successful `deepseek-v4-flash` responses with
  zero retry, but the manifest marked all 54 items pending under one
  `protected_entity_changed` report-level reason before semantic validation.
  Later tracing proved this is first-failure propagation, not evidence that all
  54 items failed independently: 22/54 items had no protected value. The exact
  offending entity set is not present in sanitized terminal evidence and must
  not be guessed.
- The initial release verifier mismatch came from unmanifested bytecode. Three
  older `cpython-314.pyc` files and four `cpython-312.pyc` files created by the
  provider-free smoke's deliberately minimal child environment were preserved
  in separate mode-700 quarantines. The release then exact-verified with zero
  residual `.pyc`; formal release files were not changed.
- macOS `/usr/bin/env` can stall at `_dyld_start` before a shebang script reaches
  bash. That stalled launch created no runtime, reservation, gate or attempt;
  direct `/bin/bash` execution of the same hashed runner avoided the environment
  fault without changing the candidate.
- Both replacement permits are terminal `blocked`; two L2 attempts have consumed
  18/100 requests, leaving 82. Any next action needs a new local repair,
  candidate digest, permit pair and explicit authorization. L3/L4/L5 remain
  unexecuted.

## 2026-07-14 DeepSeek L2 Post-Block Local Repair Findings

- Deterministic validation previously stopped at the first item error, then
  replaced all 54 item records with `pending/error_type=None`; blocked-manifest
  construction copied the report-level reason into every row. This caused the
  misleading 54/54 interpretation.
- The copied input has 9 bundles and 54 items. Only 32 items contain protected
  values; 22 do not. Protected checks include 93 number occurrences, 20 exact
  terms, 9 model-pattern matches, 6 case-sensitive model matches, 5 Reddit
  references and one URL; no exact currency expression occurs.
- The exact previous offender is unrecoverable because Provider translation
  content existed only in memory and neither the blocked manifest nor attempt
  ledger retained source or candidate text. Numeric/percent surface formatting
  remains an unproven hypothesis and was not relaxed.
- A reproducible local model contract defect was repaired: model patterns were
  detected with `IGNORECASE` but enforced with source-case exactness. The copied
  input contains three noncanonical model-case matches. The repair permits only
  case normalization for those matches and still rejects model identity changes.
- Deterministic failures now aggregate across bundles. Attributed rows are
  `blocked` with safe category codes; unvalidated rows remain `pending` with no
  copied item error. Blocked evidence still stores neither source text nor `zh`.
  A 9-bundle/54-item synthetic regression proves one failure produces exactly
  `1 blocked + 53 pending`; a multi-bundle regression proves multiple categories
  are returned in one pass.
- The first final-candidate closure check exposed four unmanifested
  `cpython-312.pyc` files created by runtime-smoke child imports. They were
  preserved in a mode-700 quarantine. `report_runtime_smoke.py` now forces
  `PYTHONDONTWRITEBYTECODE=1` in child environments, and a new release test proves
  smoke followed by exact release verification leaves zero `.pyc`.
- Fresh validation passed translation `23/23`, prepared report `30/30`, release
  contract `7/7`, and the Python 3.12 serialized full suite `652/652` in
  `221.614s`. Final release/import verification reports 19 modules with
  `repository_fallback=false`; post-smoke exact verification and copied-DB
  preflight pass for 9 visible posts, 9 bundles and 54 items with no Provider.
- Final candidate release is `861a88d8...a5f54`, release manifest
  `193035f2...4174`, validation manifest `9f8f0961...0668`. Request
  `deepseek-l2-postblock-repair-20260714-193359` has packet SHA
  `13f576a3...80a5`, cap 82 and status `ready_for_owner_authorization` only.

## 2026-07-14 DeepSeek L2 Post-Block Owner Authorization

- The owner explicitly approved the next step immediately after being shown
  request `deepseek-l2-postblock-repair-20260714-193359`, full packet SHA
  `13f576a3fea6b2173f372a167f850bc76fbdc3646cf5973bced8b123a09a80a5`,
  cap `82` and all prohibited side effects. This is sufficient authorization
  for exactly one isolated L2 shadow bound to that packet.
- Maximum supported evidence grade before execution is
  `allowed-with-label/L2-authorized-shadow-pending`. It does not authorize
  DingTalk, production writes, Docker/Colima, deploy, cron/service, Git,
  L3 human acceptance, L4 release or L5 production prepare.
- The pre-execution stop rule remains exact-match and fail-closed: any packet,
  release, manifest, validation manifest, copied DB, expiry, root, permit,
  gate or process mismatch stops before transport.
- The existing host-native runner is reusable only through its declared
  environment overrides. Its current SHA is exactly
  `b0e9799ea432f0fb866ee918238fc072199ab9a2921ec3ebd2ebaa088fb582ed`,
  matching the authorized packet; wrapper SHA is `e149e35e...36009` and shim
  SHA is `96fa8a7b...e82b2`. It verifies the exact release/DB/permits, reserves
  both permits under one lock, enables translation-only gates, restores gates
  in `finally`, commits either a complete or blocked terminal result and exits
  nonzero for a valid blocked terminal state.
- The runner accepts exact overrides for candidate release, copied DB,
  attempt cap, authorization IDs, shadow root and runtime root. No code change
  or ad-hoc gate mutation is needed for this packet.
- Shadow provisioning must use the immutable release admin wrapper with
  `init-shadow-root --authorize-shadow-provisioning`, exact release/candidate
  SHA and authorization ID. It creates only the canonical mode-700 isolated
  layout plus `shadow-root.json`; the copied DB, env and key are separate
  installation steps. Prepare and shadow permits are immutable new files under
  that shadow control root and begin in `installed`, not reserved, state.
- Env/key installation reads bytes only from stdin, writes the canonical
  shadow secret files atomically with mode 600, redacts output, and forcibly
  normalizes the five runtime gates to all-off. The packet binds the source key
  path, but key bytes must never enter argv, environment, stdout, logs or plan
  files. `check --check-key` validates metadata only.
- The CLI has no standalone public `preflight-only` command. The safe P01 DB
  check must import `preflight_daily_report` directly from the exact release,
  use disposable empty roots, and assert required phases before any
  `deepseek_client` import. The actual runner repeats the same source/config
  preflight again inside `prepare-daily-report` after permits are reserved.
- P01 attempt 1 proved `60/60` focused tests and release/import closure, then
  stopped before DB business preflight because browser-harness Python 3.14 saw
  Kimi Python 3.12 `PIL` first through `PYTHONPATH`, producing an `_imaging` ABI
  import error. No Provider/key/permit/root action occurred. The corrected
  route is Python 3.12 with the matching Kimi site-packages, already exercised
  by the passing focused tests; do not repeat the successful checks.
- The authorized P04 runner terminalized one blocked attempt. Initial
  postflight correctly confirmed gates all-off, then its own extra assertion
  failed because reservation ledger rows intentionally bind
  `provider_authorization_id + sequence + phase`; the runner `attempt_id` lives
  in sibling `binding.json`, not in every ledger row. Schema inspection shows
  nine contiguous translation reservations and one binding. This was a
  postflight-query defect only; no runner retry is allowed or needed.
- The new blocked manifest contains only safe per-item fields
  `stable_id,input_sha256,status,error_codes`; no source or candidate `zh` key
  exists. Its response records expose metadata/usage only, not content.
- A second read-only postflight check initially selected the complete
  `manifest_schema`, which correctly rejected the blocked document for missing
  `manifest_id`. Code inspection shows `build_blocked_translation_attempt`
  validates against `attempt_schema` (`daily-translation-attempt-v1`). The
  correction is schema selection only and cannot change the terminal artifact.
- The pre-sync audit found README, context pack, design, implementation plan
  and acceptance still presented packet `13f576a3...80a5` as merely ready and
  retained the prior
  `18/100, 82 remaining` boundary. Those statements are historical after the
  owner-authorized third L2 attempt; current truth is terminal blocked,
  `27/100, 73 remaining`, four number-category items of which two also contain
  model categories, semantic validation not run, no L3 package, gates all-off
  and runtime absent. The four copied `protected_entity_changed` row reasons
  are generic and are not four item-specific entity categories.
- Sanitized terminal evidence is
  `tmp/translation-quality/deepseek-l2-20260714-150456/postblock-repair-terminal-evidence.json`,
  SHA `106c2904816f654d2d5648246781dc470175b75d65bc071cdd3409b98c8eb784`.
  The shadow evidence root is preserved; runner-created runtime is absent;
  permits are terminal blocked and gates are all-off. `live_send=false`,
  `production unchanged`.

## 2026-07-14 DeepSeek Protected-Value Input Diagnosis

- Re-verified the terminal blocked manifest SHA
  `6f3ecb2b...2da4d`, mode `600`, and copied database SHA
  `b4151728...c92d7c`. A read-only `query_only` rebuild produced the same 9
  visible posts, 9 bundles and 54 translation items, then joined all four
  blocked rows by stable ID plus `input_sha256` without printing either field.
- The prior phrase “all four have entity and number changes” needs a category
  correction. `protected_entity_changed` is the generic deterministic failure
  reason added to each blocked manifest row. The item-specific categories show
  two body items with one model occurrence plus one integer each, one long
  comment with three number occurrences, and one comment with two distinct
  numbers across three occurrences. The latter two have no named/model entity
  category in their copied input.
- No protected spans overlap in these four inputs. Number shapes are six
  integers and one percentage across seven occurrences. The two model-bearing
  bodies are 81–200 characters; the number-only comments are 201–500 and 501+
  characters. No input contains the proposed `[[RVOC_` marker prefix.
- Exact Provider mutation remains unknowable because response content was
  intentionally not retained. The locally verifiable exposure is that
  `_run_translation_calls` sends every protected value in plain `source_text`
  and only checks preservation after parsing the model response.
- The bounded repair direction is preventative: replace every maximal
  protected span with a collision-safe, occurrence-specific opaque marker in
  Provider input; require every expected marker exactly once; reject missing,
  duplicate, altered or same-namespace unknown markers; restore exact source
  bytes before the existing deterministic and semantic gates. The existing
  entity/number contracts remain strict.

## 2026-07-14 DeepSeek Protected-Placeholder Repair Result

- The repair uses a deterministic per-item namespace derived from input bytes
  plus a collision salt and six-digit occurrence sequences. It merges
  overlapping protected spans before substitution, so repeated values remain
  occurrence-specific while currency/number, URL/number and Reddit-reference/
  entity overlaps restore from the exact original slice.
- Response validation requires the exact expected same-namespace marker set,
  each exactly once. Missing, duplicate, altered or injected markers block as
  `protected_placeholder_changed`; only exact restored source bytes reach the
  unchanged entity/number checks and semantic validator.
- RED evidence failed as intended before implementation: the success case
  returned `protected_entity_changed` and all four tamper variants returned the
  old reason, exit `1`. The repaired module passed `25/25`; focused translation,
  prepared-report and release tests passed `62/62`.
- A first combined Python 3.12 discovery ran 654 tests green but retained one
  loader error because that interpreter lacks pytest for one unrelated
  pytest-only module. The clean split verification passed 40 unittest modules
  `654/654`, 0 failures/errors, plus the pytest-only module `3/3`, both exit 0.
  A prior focused prepared-report failure was a fake Provider that did not copy
  the new markers; only that fixture was corrected, and production behavior was
  not weakened.
- Provider-free copied-input proof covered 9 visible posts, 9 bundles and 54
  items. 32 items use 157 markers, maximum 38 per item, with zero protected
  residual after marker removal, zero namespace collision, exact byte
  round-trip and unchanged copied DB SHA `b4151728...c92d7c`.
- Immutable release `bc51d736...340e4` and release manifest
  `e4edef8f...9d92` passed verify/import closure for 19 modules,
  `repository_fallback=false`, zero `.pyc`, provider-free runtime smoke and
  release-only copied-DB preflight. Runtime evidence remains
  `translation_provider_attempt_made=false`, `live_send=false`,
  `database_write=local-test-only`.
- Protected round-trip evidence SHA is `2f49e824...55c35`; validation manifest
  SHA is `a6be9cc3...43f2`. Exact request
  `deepseek-l2-protected-placeholder-repair-20260714-205534` has packet SHA
  `7f76571b...3002`, status `ready_for_owner_authorization`, expiry
  `2026-07-16T23:59:59+08:00` and cap 73 additional attempts.
- The packet is decision material only. No new permit, key read, shadow/runtime
  root, Provider process or Provider attempt exists; `production unchanged`,
  and remaining budget is not authorization.

## 2026-07-14 DeepSeek Runtime-Contract Pre-Provider Stop

- Owner approval of packet `7f76571b...3002` was honored exactly once. The
  shadow root, copied DB, all-off env, two permits and key metadata path all
  matched the packet. The key was copied through stdin/no-log and its content
  was not emitted.
- The runner stopped during `materialize-prepare-env` with
  `runtime_env_required_value_missing`, before any translation request. The
  attempt identity was `attempt-20260714T131210891567Z-8c39ed09de543958`;
  `translation_provider_attempt_made=false`, no token usage or response exists,
  and no blocked report manifest was created.
- Root cause is local artifact incompleteness: the packet's all-off runtime
  template contained only gate fields, while the immutable runner requires
  `REDDIT_VOC_DATABASE_PATH`, an HTTPS `REDDIT_VOC_ARTIFACT_BASE_URL`,
  `DINGTALK_REQUIRED_KEYWORD`, `REDDIT_VOC_DINGTALK_MAX_BYTES` and
  `REDDIT_VOC_DINGTALK_MAX_PARTS` before materialization. This is not evidence
  about DeepSeek output.
- Cleanup is verified: gate journal phase `restored`, both permits terminal
  `blocked`, empty runner runtime removed, no Provider process, no live send,
  no production change and cumulative attempts unchanged at `27/100`.
- A new local-only runtime-fix candidate adds the five non-secret fields, binds
  the database path to a new requested shadow root, keeps both webhook values
  blank, and retains all gates off. Static contract checks passed; runtime
  template SHA is `b1a317c7...afee302`, validation manifest SHA is
  `e066dd14...54daa2`.
- Replacement packet
  `deepseek-l2-protected-placeholder-runtimefix-20260714-211414` has SHA
  `f1f9b99d...ce066`, status `ready_for_owner_authorization`, and cap 73.
  It must receive fresh exact approval; terminal permits from the prior packet
  cannot be reused.

## 2026-07-14 DeepSeek Runtime-Fix Replacement Failure

- The owner approved the complete replacement Request ID
  `deepseek-l2-protected-placeholder-runtimefix-20260714-211414`, packet SHA
  `f1f9b99d696fb60ab76edb5de3b6c783ed1e734bf4f4a47fac4ee7e7f54ce066`, and
  remaining cap 73. Fresh preflight, release/import verification, DB integrity,
  shadow initialization, all-off env, exact permits and key metadata all
  passed. The key was copied via stdin/no-log and never emitted.
- The single runner invocation created attempt
  `attempt-20260714T133104260742Z-d970fb46d50debfe`, exited `1`, and failed
  closed before Provider transport with
  `runtime_env_required_name_missing`; the wrapper summarized this as
  `prepare_runtime_env_materialize_failed`. No DeepSeek request, response,
  token usage, semantic validation, blocked report manifest or artifact exists.
- The first local repair corrected only the five non-secret base values checked
  by `_materialize_prepare_env`. The next `_replace_env_values` contract also
  requires the names it overwrites at materialization: `REDDIT_VOC_RUN_ID`,
  `REDDIT_VOC_ATTEMPT_ID`, `REDDIT_VOC_ARTIFACT_VERSION_ID`, the public/private/
  staging/state/blocked/handoff roots, `REDDIT_VOC_PROVIDER_ATTEMPT_ROOT` and
  `REDDIT_VOC_CONFIG_ROOT`. The immutable runtime template did not contain
  those names. This is a local packet/runtime defect, not evidence of
  DeepSeek behavior or quality.
- Recovery passed: both permit-state documents are terminal `blocked`; the
  gate journal is `restored` with all gates off; no materialized attempt env,
  public/private/staging/blocked output, or Provider process remains; the
  empty runner-created runtime root was removed; source and shadow DB SHA are
  both `b4151728...c92d7c`; production is unchanged.
- Remaining use is still `27/100` consumed and `73` available. The 73 value is
  a cap, not authorization. The approved packet/permits are terminal and no
  retry is allowed. A future local template repair and new exact owner
  authorization are required before another attempt; no L3/L4/L5/send/deploy/
  cron/service/Git action follows this stop.

## 2026-07-14 DeepSeek Full Runtime-Template Contract Repair Candidate

- Read-only release inspection identified the second contract layer. The
  materializer first checks five non-empty base values, then
  `_replace_env_values` requires the source document to contain all 18 names it
  overwrites. Missing dynamic names caused the terminal
  `runtime_env_required_name_missing` stop.
- The required names are database path; run, attempt and artifact IDs; public,
  private, public-staging, private-staging, state, blocked and handoff roots;
  provider-attempt and config roots; the DingTalk mode/live-send/failure-alert
  names; and both webhook names. Empty dynamic values are safe because the
  materializer replaces them before prepare; base values remain non-empty and
  the webhook values remain blank.
- New local runtime template SHA is
  `8aeb1ae50f2d2a7040630b3957b4d379dc796c5c2382aab8a72591685eaaf0c6`, mode
  600. Release parser and replacement round-trip passed with 5/5 base values,
  18/18 names, blank webhooks and all-off gates.
- New validation manifest SHA is
  `b54b283079d380d83d9e418f71baa66c1c810fd7ec82e4ae598f070fb800240c`.
  New packet Request ID is
  `deepseek-l2-protected-placeholder-runtimefix-fields-20260714-225341`,
  packet SHA is
  `355d95b17702386de786dc53ed78eb49f276e0c2c9ffd79f1a6c9752c80e5ceb`, and
  cap is 73. It is `ready_for_owner_authorization` only.
- Release/import verification remains 19 modules with
  `repository_fallback=false`; no unmanifested bytecode exists. No new root,
  permit, key read, Provider call, send or production change exists. This
  candidate is not evidence of a successful future Provider run.

## 2026-07-14 DeepSeek Full-Field Replacement L2 Result

- The owner approved the exact full-field packet and it ran exactly once. The
  runner returned `complete`, attempt
  `attempt-20260714T152314241954Z-ff5dfb42df4dc5a8`, artifact version
  `20260714T152314241954Z-4b2b8140178434c842bc62181018b589`, with 9 translation
  and 9 semantic-validation requests, actual model `deepseek-v4-flash`, 0
  retries and 45,249 total tokens.
- All 54 items were accepted. Entity status is 32 accepted and 22 not
  applicable; every item has all five semantic verdict fields true; critical
  error count is zero. Translation output SHA is
  `e98d1a301d38229a39f77fba770d993249fa4b9bcc0ea61a521e5ec7b1ad7cf6` and
  validator output SHA is
  `ed868f131b8f752e45b9fa94ecf85594de38c07a29909672761196e5a346923f`.
- Prepared bundle SHA is
  `e1ce1bd16d8f49157a0258d026ea40d5c5632dfa9e5b66a1ce5535e884f1a68f`;
  outbox SHA is
  `0d0a6d055c88cb1d8e9422990da017caf6dfcea638059faa1b5bd9a96abae338`;
  8 bundle entries hash-aligned. `report_live_send=false`,
  `alert_live_send=false`, and prepare stdout records `current_advanced=false`.
- Recovery passed: both permits are terminal `consumed`; gate journal is
  `restored`; active gates are all-off; materialized runtime and runner runtime
  are absent; source/shadow DB SHA remains
  `b415172856a336a1a00ac5118984159a4afab299fb2913d7bace3dcdc8c92d7c`; no
  Provider process remains; staging and blocked output roots are empty. No L3
  blind package or production commit was created.
- This packet used 18 requests: cumulative use is now `45/100`, leaving 55;
  the approved 73-attempt cap was not exceeded. Sanitized terminal evidence is
  `tmp/translation-quality/deepseek-l2-20260714-150456/protected-placeholder-runtimefix-fields-candidate-20260714-225341/terminal-evidence.json`,
  SHA `0befd35b3fe6147a7436c39f9f5897a95863525258ec119c24aac9786f60acc6`.

The result is L2 automatic-gate completion only. L3 human review, L4/L5
activation, DingTalk delivery, deployment, cron/service changes and Git
actions remain unexecuted.

## 2026-07-15 L4 Bootstrap Failure — Host Cron Ownership Contract

- The owner supplied `DDDD.pem` for `ubuntu@101.34.52.232` and explicitly
  authorized a report-only `bootstrap` with live send, cron change and service
  restart disabled. The key is a local mode-600 RSA private key; its content was
  never emitted.
- Candidate release staging and remote release/import verification passed. The
  first and only bootstrap attempt then failed closed at `cron_file_invalid`.
  The remote cron file is `root:root` with mode `0644`, which is normal for
  `/etc/cron.d`; `_read_host_regular` currently rejects every non-caller owner.
- Changing ownership of the cron file would be an unsafe workaround and was
  not attempted. The failed admin permit is terminal `blocked`; no retry is
  permitted. Remote recovery confirmed the legacy launcher, cron bytes,
  `current` pointer and report network were unchanged, and no Provider or
  DingTalk call occurred.

Required repair: narrow `_read_host_regular` (or a dedicated cron reader) to
allow only the expected root-owned cron file while retaining regular-file,
mode and SHA checks; add a regression test for root-owned cron metadata; build a
new immutable release and obtain a new exact L4 authorization.

## 2026-07-15 Root-Owned Cron Contract Repair Candidate

- The repair keeps `_read_host_regular` caller-owned by default and adds an
  explicit allowed-UID set only at the fixed cron read sites. UID 0 is accepted
  for the standard `/etc/cron.d/reddit-voc-site` contract; symlink, regular-file,
  mode and expected SHA checks remain unchanged.
- A mocked root-owned metadata regression test passed, and the complete report
  ops, release/import, related runtime, translation and DingTalk test evidence
  is green (`30/30`, `7/7`, `130/130`).
- New candidate: release
  `d6c97382d12bf861663b767b2592ae884c75df08e30bb6767ac4a5c01cf5f61c`, manifest
  `ec21502990fee9a3638d4803e7c7e638f7943b191a3d05b7d87972f0f77a21d5`, launcher
  `1448eafc8aa669b0aab8f870b03a251824d5b43b7f718d2ca5b9ea924aa91d8e`.
  It is locally verified only and has not been transferred to the host.

The prior L4 permit remains terminal `blocked`; no ownership workaround was
used and no new permit was installed. Fresh owner authorization must bind the
new release SHA, manifest SHA, launcher SHA, old launcher SHA, absent current
pointer and unchanged cron SHA before any remote action.

## 2026-07-15 Fresh L4 Bootstrap Failure — Relative Python Verifier Path

- The new release and permit passed remote release/import verification when the
  verifier received `/usr/bin/python3`. The authorized bootstrap then invoked
  the fixed launcher with its default `REDDIT_VOC_HOST_PYTHON_BIN=python3`.
- The launcher forwards that relative name to
  `build_daily_report_release.py verify-imports`, whose strict
  `Path(...).resolve(strict=True)` lookup fails with
  `FileNotFoundError: python3`. The admin wrapper reports the outer
  `report_smoke_failed`; this is a launcher/verifier path contract defect, not
  a Provider or DingTalk failure.
- A direct immutable-release smoke in a network-none container and a temporary
  bridge-network container both passed, so the failure is isolated to the host
  launcher’s Python executable argument handling.
- Recovery restored `current=absent`, the legacy launcher SHA
  `4de4d3f2d2ddebdacaf11bf085f623d04eb8988aea6e3e50b662c9eb4e1293e7`, cron SHA
  `eab75d9586fa43c0531123a8780dff0286d36365fd233e7d635eef36b806705c`, no
  report network, no freeze, and site app restart count `0`.

Required next repair: resolve the host Python executable to an absolute path
before passing it to release import verification, add a regression test, build
a new immutable release and obtain fresh exact L4 authorization. Do not retry
the blocked permit.

## 2026-07-15 Absolute Host Python Verifier Repair Candidate

- The launcher now resolves a command-name Python setting with `type -P` and
  rejects non-absolute/non-executable results before any host operation. This
  keeps `verify-imports` bound to a strict filesystem path while preserving
  existing absolute-path overrides.
- The fake host smoke regression uses `REDDIT_VOC_HOST_PYTHON_BIN=python3` and
  passed. Targeted control/launcher/release tests are green `45/45`; related
  report/translation/DeepSeek/DingTalk tests are green `122/122`; local import
  closure remains `19` modules with `repository_fallback=false`.
- New local candidate: release
  `463a9e17ee8e181741b0a4fd223cb9ba2e3b7e08bd9eea7032d133390f4ac5f9`, manifest
  `3b023951d9808727f9fbc6b715c040303b2383be6217af51455137104d91850f`, launcher
  `cc0340f50b3e2f9b7ae48679a998e15264c42289ed2a686ee873599aacf1025d`.

The candidate has not been transferred to the host. Fresh owner authorization
must bind these new values; neither earlier blocked permit may be reused.

## 2026-07-15 Fresh L4 Bootstrap Failure — Admin Smoke Lock Contention

- The exact authorization `reddit-voc-l4-bootstrap-20260715-011053` reached the
  remote report smoke stage after release/import verification passed. The outer
  result was `report_smoke_failed`; no Provider or DingTalk path was enabled.
- Root cause is lock ownership: the admin process held
  `/home/ubuntu/.reddit-voc/locks/daily-report.lock` while launching the smoke
  script, but the launcher had no way to reuse that already-held descriptor and
  returned `lock_busy`. A direct launcher-only diagnostic with the same release,
  `python3` resolution and a held descriptor returned `status=complete` with
  `provider_call=false`, `translation_provider_attempt_made=false`,
  `report_live_send=false`, `alert_live_send=false` and `live_send=false`.
- Recovery verified `current=absent`, legacy launcher unchanged, cron SHA
  unchanged, report network absent, freeze absent and service restart count `0`.
  The permit is terminal `blocked`.

## 2026-07-15 Admin Smoke Lock Inheritance Repair Candidate

- The repair yields the lock descriptor from the report-control context manager,
  passes it through `pass_fds` and an explicit smoke-only environment variable,
  and validates the exact held file again inside the launcher before reusing it.
  Non-smoke operations reject the variable; owner, mode, regular-file,
  device/inode and held-lock checks remain fail-closed.
- Regression evidence is green: targeted control/launcher/release `46/46`,
  related report/translation/DeepSeek/DingTalk `122/122`, shell syntax and
  compileall passed. Local import closure is `19` modules with
  `repository_fallback=false`.
- New local-only candidate: release
  `3594a09e0fce3f311a2708a6e77a1c24937d5919c3f0080b3d2377aab72e8aa4`, manifest
  `227acfd5c44a08477c7ad98ace5a80c1abc5c85c19c4d2ea1f8a8743deedd370`,
  launcher
  `ed32f3708ac1bdec446cdf7fc3d53d5f9931062311958f31777b5da592072424`.
  It has not been transferred or installed remotely.

## 2026-07-15 Momcozy P0 Next-Batch Planning Facts

- The nine P0 lanes are terminal at continuation depths `33, 2, 2, 9, 17, 8,
  24, 33, 31` in their documented lane order.
- Search lineage has 876 raw IDs: 844 match the Reddit ID filter and 32 do
  not. Invalid IDs remain source evidence only, not comment candidates.
- Valid-ID comment status is 844 reports: 838 passed and 6 failed closed with
  `comment_repair_payload_post_missing` despite HTTP 200. The failed packets
  cannot be reused.
- Reply status is 821 passed reports, 3,921 parsed comments and 572 nested
  `More` nodes; 279 candidate cursor pairs remain unprocessed. Reply expansion
  can add more candidate cursors.
- No P0 canonical/SQLite merge, production merge, Git push, DingTalk/live send
  or deployment has occurred.

### Next-Batch Decision

The first bounded reply drain reduced the candidate count from 324 to 308 after
45 fresh tasks, while nested reply expansion added cursors. Therefore the next
safe unit is another 45-packet batch, not a claim that 308 requests will close
the tree. The decision gate after each batch is the exact remote candidate
accounting, not the number of runner exits.

The second drain showed the same observed net reduction (`308 -> 292`) after
45 successful runners. R3 is therefore bounded identically but treats any
zero/negative net reduction as a diagnostic trigger rather than continuing
blindly into R4.

R3 also reduced the candidate set (`292 -> 279`) after 45 successful runners.
All observed R3 binding records retain `provider_call=true`,
`provider_invocation_limit=1`, and false forbidden-action flags, so R4 is
eligible as another bounded batch.

### Failed-Comment Reconciliation

- All six failed responses are HTTP 200 with the same
  `comment_repair_payload_post_missing` validation error. Their IDs pass the
  narrow lexical shape filter but are sequential numeric source-only values:
  `10518101/10518102` from the `baby formula maker` lane at depth 13 and
  `17718196` through `17718199` from the `lactation massager` lane at depth 25.
- Because the Provider cannot resolve the purported post object, these are
  treated as nonresolvable search-source identities rather than transient
  comment-collection failures. No fresh Provider retry is eligible; they stay
  in the excluded/raw-lineage list for the final read-only audit.

## 2026-07-15 Reddit VOC 候选闭环书面规格确认

- 用户已确认书面总规格
  `docs/superpowers/specs/2026-07-15-reddit-voc-candidate-closure-ui-governance-design.md`；
  后续实施必须拆成互不混淆的 Plan A（候选全量与融合）、Plan B（UI
  治理状态表达）和 Plan C（本地候选编排、测试与受控提升）。
- 只有 A/B/C 全部通过统一验收后才允许生成一个最终生产候选；任何单条
  Plan 都不得独立提升生产。
- 本次确认只允许立即进入实施计划与 Plan A 的 L3 只读生产静稳复核。
  `provider_call=false`、`database_write=false`、`live_send=false`、
  `production unchanged`；不修改采集器、cron、共享 Nginx、TLS、DNS 或
  其他 Docker 环境。
- 规格中的覆盖债务继续保留并结构化呈现；它们不是正常态感叹号，也不能
  因 UI 去警示化而被隐藏或改写为已闭环。
- 根仓库仍处于 `No commits yet` 且全部项目文件为 untracked 的既有状态；本轮
  不 commit、不 stage，也不把工作区状态误报为干净。规格和计划编辑只做窄范围
  文件写入。
- 已核对总规格当前 frontmatter 仍是
  `approved_design_pending_written_review` / `implementation_status: not_started`；
  书面确认后应更新为 `approved`，并在三个实施计划生成且自检通过后再标记
  `implementation_plans_created=true`。
- Plan A/B/C 已落盘，共 511 行；三个文件 code fence 均成对，未发现
  `TBD/FIXME/PLACEHOLDER`，`git diff --no-index --check` 未报告空白错误。
  Plan A 为 active，Plan B/C 分别等待数据合同和 A/B 制品。
- 证据门禁限定本阶段最大为 `L3-production-read-only`：生产 SSH/SQLite
  只读观测可证明当前事实与静稳，但不能证明数据已融合、候选已验证或生产已更新。
  所有本地构建与测试最高标为 L2；远端上传、容器启动或 current 切换仍需新的
  精确 L4 授权。
- `capture_reddit_remote_snapshot.py` 是当前更严格的数据库只读入口：SSH 使用
  `StrictHostKeyChecking=yes`，先核远端数据库 SHA，再以 SQLite `mode=ro`、
  `PRAGMA query_only=ON` 和可选 immutable 事务导出；远端只通过 stdout 返回，
  不创建文件。它要求先取得当前数据库 SHA 和 sidecar 状态。
- `capture_reddit_production_snapshot.py` 使用 `StrictHostKeyChecking=accept-new`，且必须
  先有完全匹配的 identity snapshot；本轮不直接将它作为初始静稳探针，避免弱化现有
  known-host 合同或用旧 identity 约束最新生产事实。
- 生产数据库宿主路径由现有受控脚本确认是
  `/opt/reddit-voc-site/data/reddit_voc_daily.sqlite3`，容器内路径为
  `/app/data/reddit_voc_daily.sqlite3`。下一步先执行最小 SSH 只读元数据双观测，
  再决定 active read-only transaction 或 immutable snapshot；存在 WAL/SHM 时不得强行
  使用 immutable。
- 本地 SSH key 元数据为 mode 600，`~/.ssh/known_hosts` 已有 101.34.52.232 的
  ed25519/RSA/ECDSA 记录，因此只读 SSH 必须使用 `StrictHostKeyChecking=yes`，
  无需也不应使用 `accept-new`。
- RC3 production acceptance receipt 的真实字段位于 `release`、
  `production_runtime` 和 `noninterference`（不是早期假定的 `runtime`/
  `non_interference`）；后续提取必须按当前 schema 读取，缺字段不能当作空事实。
- 旧 identity/raw snapshot 是单行大型 JSON；广泛 `rg` 会产生截断输出，后续只用
  `jq` 的目标字段和流式计数，不能基于截断的全文输出下结论。
- 三路独立计划审阅发现并已修复合同级问题：Plan A 改为
  `freeze → deterministic Base → 四明细账 → analytics → reconciliation`，消除
  Base/ledger/reconciliation 自证循环；source cutoff 与 code/frontend cutoff 分离；
  新增服务器报告和 `ai_nlp_voc` 安全冻结入口。
- Plan B 补齐真实 warning 所在组件、局部 failure-scope matrix、数据驱动状态、
  immutable artifact 与 served release/deployment source 的时间语义，并删除不可执行的
 直接 Node E2E 伪命令。
- Plan C 改为先取全局锁再静稳，定义内容寻址 candidate identity、runs/events/entries
  分账、A/B receipt 交接、唯一 final dist owner、正式 E2E/export/container wrappers
  和独立一次性 promotion permit；preview manifest 被明确禁止进入 full gate。
- Plan A 二次审阅补齐三层冻结和两个不可变层级：data reconciliation 不再绑定未来
  frontend/container；Plan C final release receipt 才做跨层绑定。候选目录身份改为
  source/baseline/config/data-code 四 SHA 的 canonical 组合，避免相同数据不同代码碰撞。
- Plan B 二次审阅为计划层 GO；修正 `insufficient` 不再统一映射 provisional，并把
  Cases manifest/fetch 失败纳入 38 seed-only 的局部 fail-closed 合同。B 实施仍等待
  Plan A governance schema。
- Plan C 二次审阅后进一步分开 candidate input identity 与 final candidate identity，
  统一 Plan B 只交付 source/test、Plan C 唯一拥有 final dist/container/E2E，并要求
  preflight 到 cutover 持有同一远端 deploy lock、实际切换时 expected-current CAS、
  immutable permit 与独立 consumption receipt。Batch C4 仍未获授权。
- Plan C 三次复审的最后两项已修：Plan B 明确只交 frontend source/UI source-test
  receipt，任何临时 build/browser 仅为 non-promotable preview；Plan C 唯一生成 final
  dist/container/same-dist E2E。Candidate identity 使用去除时间/run 字段的 stable
  validation evidence projection SHA，完整 receipt SHA 只进入外层 manifest/packet。
- Plan A 第三次独立复审结论为 GO；命名统一为
  `candidate-data-reconciliation-ledger.jsonl`，与 Plan C final release receipt 分层。
- 现有生产安装脚本确认只读基线位置：洞察站根
  `/opt/reddit-voc-insights-site`、current symlink、`.deploy.lock`、容器
  `reddit_voc_insights_web`、collector `reddit_voc_site_app`、translation
  `reddit_voc_libretranslate`、数据库
  `/opt/reddit-voc-site/data/reddit_voc_daily.sqlite3`、report current
  `/opt/reddit-voc-report/current`、共享 Nginx
  `/opt/ai-video/deploy/lighthouse/nginx.conf` 和 cron
  `/etc/cron.d/reddit-voc-site`。A1 只读探针只读取这些既有对象。
- RC3 基线 runtime 是容器 `reddit_voc_insights_web`、健康、restart 0、
  172.20.0.1:18338、UID 101、read-only rootfs、zero mounts。该旧回执只作为比较
  基线；A1 必须实时重新读取，不能假定仍未漂移。
- Plan A A1 在 `2026-07-15T08:21:00Z` 与 `08:21:11Z` 完成两点 L3 只读观测。
  collector `513f5e08...6979`、LibreTranslate `29062314...d71e`、insights
  `dab0ab66...5a00e` 均 healthy/restart 0 且两点相同；one-shot 0、report network 0、
  running containers 53、daily-report lock holders 0。
- 生产 SQLite 两点 stat 均为 `1784073890:581632:1875070`，SHA-256
  `de7ecaa360b936f854b37b2ba8fc3e2daf217656f7442f8d4a71fba6a7230c41`，
  WAL/SHM/journal 全 absent，可进入 immutable read-only capture。洞察 current 仍指向
  RC3 release `9e0d2313...0d650`；shared Nginx `fef7d187...df4b6`、cron
  `eab75d95...705c` 两点不变，report current absent。
- 此证据等级仅为 `L3-production-read-only`；没有远端写入、Provider、DB write、
  deploy、schedule 或 live send。下一步是只读导出 collector SQLite identity/content，
  再盘点服务器报告树和本地 `ai_nlp_voc` 归档。
- 首次 immutable capture 正确 fail closed 于
  `comment_linkage_policy_passed, analysis_sources_exact`，没有生成快照。只读聚合诊断
  证明生产 collector DB 为 98 posts、454 comments，其中 436 linked、18 orphan；
  analysis 恰好覆盖 98 posts + 436 linked comments，共 534，零缺失/额外/重复，
  `provider_call_true=0`，integrity/query_only 均通过。
- 这不是分析缺失漂移，而是旧 capture 默认把 18 个 quarantine/orphan comments 也视为
  必须有 analysis。脚本已有显式 `--allow-orphan-comments` 合同；下一次只读 capture 可在
  保留全部 454 comment identities 的同时，仅要求 linked comments 有 analysis。长期规则：
  quarantine/orphan comment 不进入 VOC analysis，不能用全评论一一分析假设验证生产。
- 显式 `--allow-orphan-comments` immutable capture 已通过：98 posts、454 comments、
  534 analyses，identity snapshot SHA `55ee4738...914d`、content snapshot SHA
  `961b0c33...d667`，两个本地私有文件均 mode 0600；远端写入仍为 false。
- 当前生产 release directory 和 manifest 已由 SSH 只读重新校验：current 实际解析到
  release `9e0d2313...0d650`，远端 release manifest SHA
  `9645fe76...1df37` 与 RC3 acceptance receipt 精确一致。尝试读取假定的
  `dist/data/current-release.json` 路径返回 missing；该路径未获证实，不能写入合同，
  后续从 release manifest 的真实 file list 定位。
- RC3 Base manifest 使用 `canonical_counts`、`fusion_accounting`、`files` 等 schema，
  不是 `counts/identity_sha256` 顶层旧假设。P0/L0/Q0/C0 必须从实际 posts/comments/
  quarantine 文件独立重算并与 manifest file hashes 互证。
- RC3 的远端增量选择证据已定位到
  `tmp/reddit-voc-incremental-intake-20260715/remote-selection-manifest.json`，旧 freeze
  绑定其 SHA `4148e791...1598`。该 manifest 使用 `scope/selection/cutoffs/stability`
  schema，不存在顶层 `files/summary/roots`；下一步按实际 `selection` 结构读取，
  不能沿用旧字段假设。
- `/opt/reddit-voc-staging` 全量受管 report 两点只读清单在
  `08:24:38Z/08:24:50Z` 完全一致：3,146 files、68,680,700 bytes、member/stat/SHA
  aggregate `6553aa36...4cd2`、unsafe 0，最近 mtime 为 `06:14:07Z`。
  分类为 69 search-lane、159 search-continuation、1,247 comment-repair、1,671
  comment-reply。
- 相对旧 report freeze 的 2,343 files，服务器现有受管 reports 净增加 803。
  搜索报告总数 `69+159=228` 与旧冻结 search report count 228 相同，因此这些新增
  reports 初步指向已知帖子的评论/回复水合，而不是 803 个新增帖子；最终身份影响必须
  解析内容后按 post/comment identity 集合差计算。
- 远端聚合脚本输出的 `plan_only_task_count=2531` 不可作为业务候选数：task ID 正则只
  匹配 `taskNNN`，部分 report 路径使用 `v2replyNNN` 等命名，造成 report task 归属漏配。
  该数字仅为探针诊断副产物，后续安全 capture 必须用明确 path/plan/report 绑定规则。
- `voc-nlp-enrichment` skill 确认本批应按 identity/timestamp 做增量识别、结构化输出和
  趋势分析；但其声明的 `references/workflow-detail.md` 与 `scripts/preprocess.py` 在已安装
  skill 目录中不存在。该 skill 无法提供可执行脚本，本轮回退到项目现有
  `build_reddit_*`、tag/product/risk contracts 和独立 validators，不引入新依赖或
  Provider。
- 已从当前 RC3 Base 实际文件独立重算生产 baseline：`P0=1322`，LF SHA
  `d9803f44...376e`；`L0=12976`，LF SHA `12c17071...3657`；`Q0=10`，LF SHA
  `fdbdf984...87e7`；`C0=L0∪Q0=12986`，LF SHA `6e694bc9...2e70`。
  四集合数量与 manifest `canonical_counts` 精确一致，且远端 release manifest 已证明
  当前仍服务该 RC3 bytes。
- RC3 `source_boundaries` 解释了 1,322 帖来源：archive 136、production 98、
  isolated staging 净增 223、V2 discovery hydration 净增 865；historical canonical
  只作 lineage overlap。当前 3,146 reports 必须与上述 `P0/C0` 做身份/内容集合差，
  不能再与旧 221 页面直接比较来定义本版本净新增。
- 旧 V2 report freeze 为 2,343 files / 55,568,500 bytes，分类为 69 search-lane、
  159 search-continuation、1,150 comment-repair、965 comment-reply；当前远端稳定清单
  相比之下精确增加 97 comment-repair 与 706 comment-reply，search 两类均无新增。
  这强化了“新增报告主要是已知帖子的评论/回复水合”假说，但只有解析后对身份集合做差
  才能把它升级为事实。
- 旧 V2 raw snapshot 记录 discovery target 883、canonical posts 865、comments 7,183、
  analyses 8,048，以及 18 个 first-page/lineage blockers；它只能作为旧冻结基线，不能
  替代当前 3,146 reports 的重新解析。旧 identity freeze 记录 global known 1,340、
  production 1,322、lineage gaps 18，与该 865/18 结构互证。
- `ai_nlp_voc/system_data/voc_data/reddit` 已完成独立只读内容核验：排除 `.DS_Store`
  后 145 个允许文件 / 18,450,589 bytes，与现有 immutable import 的路径、size、SHA
  145/145 精确一致；source new/changed/missing 均为 0，symlink/special 均为 0。
  内部可识别唯一身份为 136 posts / 4,153 comments，另有 28 个 `more` 节点；本轮该
  来源必须登记为 `no_change`，不能再次计入净新增，也不能把已物化评论数误报为线程穷尽。
- Plan C 最终独立计划复审结论为 implementation GO，但不包含 Batch C4；受控提升仍需
  独立 immutable owner permit、consumption receipt、远端同一 deploy lock 与
  expected-current CAS。Plan B 的计划证据标签已从误导性的 `L2_local_same_dist`
  更正为 `L2_local_source_contract`，final same-dist 仍仅由 Plan C 产生。
- V2 identity freeze 的真实 schema 是顶层 `sets` 数组，旧 raw snapshot 通过
  `set_id=discovery_only`、`count=883`、post IDs SHA `a5815737...a98e` 绑定；不能从
  大型单行 JSON 的截断全文推导集合。现有 report import 将每个远端任务目录保留在
  `private/reports/<task-and-digest>/` 下，并由 `private/report-file-manifest.json`
  约束；当前全量 capture 必须保留同等相对路径语义，才能复用既有 parser。
- 旧 raw snapshot 的 scanner 实际看见 228 个 search report 与 2,115 个 comment report，
  合计正好 2,343；其 `source_reports` 仅有 1,701 条接受/去重后的语义来源记录，不能把
  `source_reports|length` 当作物理文件覆盖数。
- 当前根仓库仍是 `codex/momcozy-reddit-backfill-20260711` 且 `No commits yet` 语义下的
  全量 untracked 工作区；因此本轮只能以明确路径和内容校验约束窄改动，不能把
  `git diff` 为空误解为无用户工作，也不 stage/commit。当前三计划 SHA 为 Plan A
  `17f2fa84...9f51`、Plan B `fcd68e6e...b825`、Plan C `41dabdf7...d9e1`；Plan B SHA
  的变化仅来自证据等级语义清理。
- `build_reddit_v2_identity_freeze.py` 会先验证 report manifest 的每个物理成员、完整
  filesystem set、bytes/SHA/aggregate/cutoff，再只从两类 search report 计算 post
  identity；所以“search reports 无变化”可以支持身份结果应保持不变的预测，但仍不能
  跳过对新增 803 个 comment reports 的完整 archive freeze。当前 manifest 必须重建并
  绑定 3,146 个物理文件，随后 identity freeze 才能把该预测升级为可审计事实。
- 仓库已有 `freeze_reddit_v2_report_archive.py` 负责生成
  `reddit_voc_v2_report_file_manifest_v1`，`build_reddit_v2_identity_freeze.py` 负责消费；
  新 capture 工具不应另造不兼容的 archive schema。A1 的正确组合是先做安全、不可变的
  source capture，再由现有 freezer 生成兼容 manifest，最后运行 identity/raw builders。
- 现有 report freezer 会对 archive 做 hash 前后双 scan、拒绝非四类报告名和 symlink，
  并以 manifest 内容不可变写入；但 `freeze_cutoff_utc` 也是 manifest 内容的一部分，故同一
  destination 用不同观察时间重跑会正确报 collision。A1 必须把 source capture 的固定
  cutoff 传给 freezer，并把输出放在内容/冻结身份唯一的私有目录，不能用“现在时间”覆盖。
- `ai_nlp_voc` immutable import 的 145 个允许文件实际分为 136 JSON 数据文件与 9 个
  documentation files；当前 Base 只计 136 JSON / 18,442,334 bytes，正好比来源允许集少
  9 个文档的 8,255 bytes。A1 可冻结全部 145 个文件作为来源完整性证据，但 deterministic
  fusion 只能消费 136 JSON；9 个文档必须在 occurrence/accounting 中显式归类，不能被
  静默忽略或当成数据记录。
- 旧 Task2600 selection manifest 混合四类 report 与 plan JSON，且明确
  `freeze_complete=false`；它不能复用为当前 source freeze。新 capture 若保留 governed
  plans，必须放在独立 namespace/manifest；report-only archive 仍只含 freezer 允许的四个
  report basename，避免破坏现有 identity/raw parser 合同。
- 本地数据卷尚有约 48 GiB 可用；当前全量远端 reports 约 68.7 MB，A1 的私有只读导入
  没有磁盘容量阻塞。已有 production collector identity/content captures 共不足 1 MB，
  均为 mode 0600；复制报告仍必须使用新私有根和 immutable collision 合同，不能写入旧
  58 MB report import。
- 当前严格 capture 已生成正确的 `reddit_voc_remote_content_snapshot_v1`，但调用时把
  `source.environment` 设为 `tencent_production_current_collector`；现有
  `build_reddit_site_snapshot.py` 明确只接受 `tencent_production`。严格 capture CLI 本身
  支持受控 `--environment`，所以正式 A1 输入应在相同 DB SHA 门禁下重新只读 capture 为
  `tencent_production`，而不是手改 snapshot 元数据。
- 旧 `capture_reddit_production_snapshot.py` 不适合作为替代：它使用
  `StrictHostKeyChecking=accept-new`，且输出旧 schema
  `reddit_voc_production_content_snapshot_v1`，同样过不了当前 Base builder 的精确合同。
- 已在相同数据库 SHA 门禁下重新执行严格 SSH/SQLite immutable 只读 capture，正式 A1
  生产输入现为 `source.environment=tencent_production`、dataset
  `tencent_production_daily_20260715_a1`。结果仍是 98 posts / 454 comments / 534 analyses，
  全部 checks=true，DB SHA 仍为 `de7ecaa3...0c41`；identity/content SHA 分别为
  `b41c0d06...8f1a` 与 `0757e1d6...23e5`，文件均 mode 0600。
- 该重抓只从远端 stdout 读取，`remote_write=false`、`database_write=false`、
  `provider_call=false`、`deploy=false`、`production unchanged`；它修复的是本地输入合同，
  不是生产数据变更，也不改变 P0/C0 数量。
- 旧 `freeze_reddit_incremental_inputs.py` 只绑定 previous/candidate V2 identity、V2 raw
  snapshot 与附加 artifacts，并要求 identity monotonic；它不是 Plan A 所需的全来源
  occurrence freeze，不能替代新 source freeze manifest。
- 当前 Base builder 的确定性输入合同仍是 archive dir、historical DB、production snapshot、
  isolated staging snapshot、V2 raw/identity、tag dictionary 与 product ledger；production
  新快照现在已满足其精确 schema/environment/check gate。Builder 仍对 product ledger SHA
  做硬门禁，并把 historical 仅作 lineage、staging 作 overlay、V2 作 disjoint append；A2
  应复用这条顺序，不能让后生成 ledger 反向决定准入。
- 新 `capture_reddit_candidate_sources.py` 前 620 行主线审阅通过：本地 allowlist 做两次
  lstat/fstat/hash 观察、O_NOFOLLOW 和 drift 检查；`.json` 标为 fusion eligible，`.md`
  明确只作 documentation。远端固定 `/opt/reddit-voc-staging`，reports/plans 分 namespace，
  仅四类 report 和 governed plan regex，双观察比较 member/stat/inode/SHA，stdout-only
  base64 content，member/total/count 上限分别为 100 MB / 250 MB / 20,000。
- 当前 reports 68.7 MB，base64 后仍远低于脚本 350 MB stdout 上限；但 remote helper 会对
  staging root 下任何 symlink/special file fail closed（包括非 allowlisted 文件），真实运行
  可能因与目标无关的不安全成员而停止。若发生只能记录 blocker，不能放宽后继续。
- 新 capture 工具后半与 6 个测试已完整主线审阅：输出 root/所有子目录要求 mode 0700，
  文件和 manifest mode 0600；写入使用临时文件 + hard-link 原子发布，同内容返回
  `no_change`、异内容 collision。Manifest 按 namespace/path 排序并绑定 bytes、mtime_ns、
  SHA、fusion eligibility；真实 report archive 可直接取
  `sources/tencent_v2_reports`，plans 位于独立 `sources/tencent_v2_plans`。
- 现有 focused tests 覆盖 local allowlist/immutable、traversal/symlink/FIFO/drift、四 report
  与 governed plan、远端 special/drift、pinned known-host/stdout-only、manifest/member
  collision；尚未覆盖真实 CLI、全量上限、nested parent 自动创建和 145-file allowlist。
  A1 真实运行后必须补 CLI 实证与独立 manifest/filesystem 复核，不能仅用 6 tests 声称完成。
- `source_cutoff_utc` 由调用者传入而非工具自动测得。正式首次冻结将使用已保存且哈希稳定的
  L3 两点 observation 截止 `2026-07-15T08:24:50Z`；新 capture 必须复现同一 member/stat/SHA
  才能沿用该 cutoff。若内容漂移则停止并建立新观察，不得把任意当前时间写成证据。
- 独立复算确认 current identity/raw 必须重建，不能复用旧文件：identity freeze 绑定完整
  report manifest 与 baseline/site sets，raw snapshot 又实际消费新增 comment reports 并绑定
  新 identity SHA。若 228 个 search reports 与 baseline inventory 保持不变，新 identity 的
  预期断言仍是 discovery-only 883 / SHA `a5815737...a98e`；以 RC3 1,322-post Base 作为
  current site 时 `net_new_vs_site=18`，这 18 仍是 lineage pending，不等于已准入净新增。
- 新 source capture 当前只允许 local `.json/.md`，不足以单独冻结 Plan A 的全部本地输入：
  `dim_tag_v6.3_final.csv`、historical canonical SQLite、YAML 配置等仍需进入外层 source/data
  manifest 或扩展受控 local artifact role。不能因为 remote+ai_nlp capture 成功就声称 A1
  全来源 freeze 已完成。
- Base 所需的 historical DB 已定位为
  `data/backfill/backfill_momcozy_20250101_20260711/reddit_voc_backfill.sqlite3`，product ledger 为
  `config/product_entities/momcozy-product-entity-ledger-v1.json`；config 下还含 analytics、
  persona、tagging、keywords/subreddits 等版本化输入。A1 必须选择实际构建依赖的最小集合，
  不能把整个 config 树无差别当作业务输入。
- Source capture 已做最小合同补齐：显式 allowlist 现在可冻结 CSV/JSON/JSONL/YAML/SQLite
  等受控数据类型，Markdown 仍只作 documentation；`capture-complete` 在全部双观察完成后
  生成首次 cutoff，精确重跑从既有 immutable manifest 复用同一 cutoff。Focused tests
  更新为 7/7 通过。
- 当前确定性 staging 输入是
  `data/imports/tencent_production_20260715/private/task37-content-snapshot.json`，environment
  `tencent_isolated_staging`、301 posts/3,225 comments、SHA `ee754636...dc81`；historical DB
  SHA `f8cfa072...2c43`。两者与 RC3 Base source boundaries 精确互证，可继续冻结而无需重抓。
- 本地经营配置候选 SHA 已盘点：tag dictionary `22664c9c...2e14`、product ledger
  `cc66f565...51ab`、period coverage v2 `af1c6cd1...5b4b`、risk theme gate v2
  `53e22c68...5aed`、personas v2 `ba28ff3b...f727`、semantic predicates v2
  `27bbef9e...6f9`。正式 source manifest 只纳入后续实际 CLI 消费的版本，不把旧 v1/模板
  或采集调度配置混入离线 candidate identity。
- 计划纳入 A1 的核心本地 governed artifacts（historical DB、staging content/identity、tag
  CSV、product ledger、baseline inventory、RC3 Base manifest/posts/comments/quarantine）合计
  约 37 MB；连同 18.45 MB `ai_nlp_voc` 与远端 reports/plans，仍在 250 MB 总上限内。
- 下游 CLI 的真实输入边界进一步收窄：Insights builder 还需要 semantic `sample` 与
  `decisions`；Reports 只消费 Base+Insights；Personas 明确消费 personas config、avatar dir，
  可选 tag-repair dir/policy。A1 不能仅冻结四个 analytics/persona config 文件就声称下游
  输入齐全，A3 实际选择 sample/decisions/tag-repair 后须补入同一 data/config freeze 或
  建立后续 code/config freeze 绑定。
- `ai_nlp_voc` 145 路径全部唯一且无 traversal/backslash/NUL，但 64 个相对路径含空格；
  真实 CLI 必须用 quoted shell array 逐项传参，不能用未加引号的 command substitution，
  否则会静默拆分 allowlist 并破坏 145/145 覆盖。
- 旧 V2 identity/raw artifacts 分别约 67 KB / 8.13 MB，可作为 previous freeze/provenance
  纳入 governed inputs；RC3 生产基线的 acceptance receipt 位于
  `tmp/reddit-voc-incremental-candidate-20260715/production-acceptance-receipt-rc3.json`，当前
  container release manifest 位于同候选根的
  `frontend/container-release/9e0d2313...0d650/release-manifest.json`。这些是 production
  baseline 证据，不是新候选输出。
- Source capture 首轮独立复审曾判 NO-GO，两个 blocker 是既有 manifest 下输出树可被静默
  修复/残留，以及首次显式 cutoff 可任意回标。现已改为写前生成 proposed manifest：既有
  manifest 必须 canonical bytes 相同且目录/文件/mode/content 精确一致，缺失/额外/篡改均
  只失败不修复；无 manifest 的非空树也拒绝。首次 cutoff 只能 `capture-complete`，重跑复用
  已有 immutable cutoff，显式不同 cutoff 报 collision。
- 新增 missing member、extra member、partial tree、cutoff reuse/collision 和本地受控数据
  suffix 测试后，focused suite 从 7 增至 9。第一次 GREEN 后因旧测试仍期望旧错误码而出现
  1 个失败；这不是实现回归，而是 tamper 现改由更精确的
  `destination_member_content_mismatch` 拒绝。同步测试断言后 9/9 GREEN，未降低门禁。
- `.txt` 未加入 source-freeze component：P0/L0/Q0/C0 LF 清单将在 sibling baseline
  artifact 中由专用生成器产生，并由外层 candidate manifest 绑定；不能把身份清单笼统标成
  fusion data，也不能往已经 exact-set 冻结的 source tree 追加文件。
- 首次真实 remote capture 正确 fail closed 且 output root 保持 absent；安全 reason code 后
  定位为 `remote_capture_empty`。根因由复跑证实是普通 `ubuntu` 对 staging tree 的遍历权限：
  reader 改为与既有 DB snapshot 相同的 `sudo -n python3` 后成功。`os.walk` 也新增显式
  `remote_directory_unreadable`，不再把权限错误静默降成 empty。Safe diagnostic 测试加入后
  capture suite 为 10/10 GREEN。
- 真实 combined source freeze 已创建：cutoff `2026-07-15T08:47:22.379946Z`，manifest SHA
  `0d7dc292...a8233`，manifest LF aggregate SHA `5e8c850b...12c4c`。共 5,928 source files /
  137,215,820 bytes：`ai_nlp_reddit` 145 / 18,450,589，governed inputs 24 /
  48,364,397，Tencent reports 3,146 / 68,680,700，Tencent plans 2,613 / 1,720,134。
- 真实 plan 物理文件数为 2,613；此前正则探针的 `plan_only_task_count=2531` 少计 82，现已
  由固定 governed plan basename + 内容冻结取得物理事实。Fusion eligible 3,306 = 136
  ai_nlp JSON + 24 governed inputs + 3,146 reports；9 Markdown 与 2,613 plans 明确不进入
  fusion。
- 首次输出树独立 stat 复核：5,929 regular files（5,928 sources + 1 manifest）、symlink 0、
  非 0700 目录 0、非 0600 文件 0，磁盘占用约 149 MB。边界仍为
  `remote_write=false`、`database_write=false`、`provider_call=false`、`deploy=false`、
  `production unchanged`。
- 独立于 capture 实现的只读复算已逐一验证 5,928 个 destination 的 exact set、bytes、
  SHA，重算 manifest canonical bytes 与 LF aggregate，全部通过；实际文件总数含 manifest
  为 5,929。
- 完全相同参数第二次真实 SSH capture 返回 `status=no_change`，复用相同 cutoff 与 manifest
  SHA。输出树 path/mtime/ctime/size metadata aggregate 前后均为
  `570f324a...06d3`，manifest mtime 不变，证明该重跑没有本地写入；远端始终
  stdout-only/read-only。
- Capture/archive/identity/raw 合并 focused regression 当前为 31/31 GREEN；后续追加安全
  reason 与 sudo command 测试后 capture module 单独为 10/10 GREEN。真实执行的两次早期
  fail-closed（泛化错误、随后 `remote_capture_empty`）均未创建 output root，未遗留 partial
  tree，也未触及生产状态。
- 从真实 source freeze 生成的兼容 report-only manifest 为 3,146 files / 68,680,700 bytes，
  SHA `2528c90b...6d2a`，LF aggregate `1f7f2b0e...a2b6`。Current identity freeze SHA
  `58498923...6f59`；semantic 1,156、materialized 369、discovery-only 883、remote union
  1,252、global known 1,340 均与预测一致。以 RC3 Base 1,322 帖为 site baseline 时
  `net_new_vs_site=18`，18 个仍全部是 lineage/first-page pending。
- Current V2 raw snapshot SHA `b37e6ca3...2f16`、mode 0600：865 admitted posts、8,225
  comments、9,090 analyses；相对 RC3 raw 新增 1,042 个 target-thread comments，cursor debt
  `367→306`（减少 61），page pagination debt 仍为 339。`status=blocked` 只因允许保留的
  coverage debt，fatal parser/conflict/failed-report blockers 均为 0。
- 新增 803 comment report 中，只有 209 条进入 discovery-only reachable source reports，
  另有 594 条新增为 non-target；累计 1,236 个 comment reports 被当前 raw builder 标成
  `ignored_non_target`（旧值 642）。因此现在只能确认 target threads 的 +1,042 comments，
  不能把它当成“全候选净新增”。这 1,236 个报告必须进入专门的 existing-post hydration/
  occurrence reconciliation，或者逐一说明 rejected reason，才能满足 `unaccounted=0`。
- Raw CLI 已按合同写出 blocked snapshot 并返回 2；外层 zsh 随后误用只读变量名 `status`
  导致 wrapper exit 1。该 shell 错误发生在 snapshot 写完后，不影响其 bytes/SHA；后续包装
  必须使用 `exit_code` 并显式接受 0/2，不能把 wrapper 错误误报为 parser 失败。
- 使用现有严格 comment parser 对 RC3 `P0=1,322` 做全量只读 hydration 复算，首次揭示
  gross identity 规模：2,918 comment reports 中，1,944 条可达报告产出 9,842 个唯一评论；
  其中 8,103 已在 C0，**1,739 个是相对 C0 的新评论身份候选**，comment conflict=0、
  parent outside P0=0。该 1,739 高于 discovery-only 的 1,042，证明旧 target 口径确实漏掉
  existing-post hydration。
- 1,739 目前仍是 gross candidates，不是最终 release net-new：P0-target scan 同时出现 441
  parse failures、533 reports outside P0、309 个 P0 first-page missing、450 cursor outstanding、
  431 pagination-outstanding posts。必须先按 failure/outside identity/reason 分类并与 18 gaps、
  quarantine/bot/deleted/precedence 规则对账，才能决定 admitted/rejected/pending。
- P0 hydration 中 9,842 comments 与 C0 的交集为 8,103，C0 另有 4,883 未在本次 hydration
  可达图出现；这不代表删除。Base append-only 合同要求保留全部 C0，hydration 只能新增或
  受控升级，不能用“本轮未观察到”删除旧评论。
- 1,739 gross new comments 的父帖来源拆分为：V2 discovery 1,042、production primary 687、
  production+staging overlap 8、staging-only 2；因此 existing-post hydration 额外贡献 697
  个 gross comment identities。它们仍需 bot/deleted/quarantine/precedence 审核。
- 441 P0-target parse failures 已精确归因：440 个 reply reports 为
  `comment_reply_source_sha256_invalid`，1 个 first-page report 为
  `report_response_validation_failed`。这不是 441 个身份丢失的同义词；440 说明当前 reply
  schema/lineage binding 与 P0 产物不兼容，必须检查其 plan/report 合同后再决定修 parser
  还是逐项 rejected，不能放宽 SHA 门禁。
- 533 outside-P0 reports 归属于 233 个唯一 post IDs；这 233 个全部不在 current
  `global_known=1,340`，也不属于 18 个 lineage gaps。它们是目前最重要的“未入账新帖子
  候选”，但在取得 search/plan/source lineage 与正文前只能标 `pending_lineage`，不能仅凭
  comment report ID 直接准入 Base。
- 一次过宽 `rg` 在单行大型 report JSON 上输出了被截断的 raw payload/公开用户名与正文；
  后续已停止该检索方式。长期规则：对 frozen reports 只用文件名清单、`jq`/Python 目标字段
  聚合和计数，绝不对 payload 文件做广泛全文 `rg`，也不在汇报中复述原文或用户名。
- 2,613 frozen plan files 的 schema 已完整聚合：69 search-lane、159 search-continuation、
  1,151 comment-repair、1,231 comment-reply、3 legacy v2-comment plans。233 个 unknown post
  candidates 全部能在 governed plans 找到：repair plan `candidates[].post_id` 覆盖 233/233，
  其 533 个 reports 又分别由 233 repair + 300 reply plans 的顶层 `post_id` 绑定。
- 该 plan linkage 证明 233 不是孤立/伪造的 comment-report IDs，但仍只证明“被受控评论任务
  选中”。当前尚未证明它们属于哪一 search lane，也未证明有完整正文、event time 和严格
  search lineage；下一步应沿 repair plan 的 `source_payload_sha256` / `source_database_sha256`
  反查 frozen search reports 或只读源数据库，不能从 comment payload 的 title 猜正文。
- 书面规格确认后的断点复核表明，A1 source freeze 与 current identity/raw 已有新鲜证据，
  但 `task_plan.md` 的 A1 摘要仍停留在“source freeze 待完成”，属于文档状态滞后；在 233 个
  `pending_lineage` 与 440 个 reply SHA 失败闭环前，不能把 Plan A 整体升级为 Base fusion。
- 当前实施入口优先复用 `build_reddit_v2_raw_snapshot.py` 的严格 report scan/reachable/merge
  逻辑，并新增 sibling existing-post hydration ledger；不修改 frozen source component，也不
  用 discovery-only builder 承载 P0 existing-post 语义。该选择保持 Base append-only 与
  `unaccounted_total=0` 两个书面合同同时可验证。
- Reply 生成器的当前正式字段是 `source_first_page_payload_sha256`，raw parser 也只接受该
  字段；仓库仍存在更早期 plan 使用 `source_payload_sha256` 的历史 schema。440 个失败是否
  全部属于该兼容性分支，必须用冻结报告的“字段存在性/类型 + plan schema”聚合确认；不能
  因看到少量旧文档样本就直接改 parser，也不能输出 cursor 或正文来诊断。
- 本轮一次仓库级 schema 检索因命中单行 plan JSON 而输出了长 cursor 字段并被截断；后续
  再次收紧：对 report/plan payload 只运行结构化聚合，终端只输出计数、字段名、schema、SHA
  和路径类别，禁止直接对 `docs/analysis` 或 frozen payload 做宽泛全文检索。
- 1,671 个 reply reports 的结构化复核确认：1,231 个有合法
  `source_first_page_payload_sha256`，440 个该字段为 null；440 个全部属于旧 `task139..579`
  namespace，schema 仍为 `reddit_voc_comment_reply_probe_v1`。远端 governed plan freeze 没有
  对应这 440 个旧计划，故当前失败不是 payload 本身 440 次损坏，而是旧报告缺显式父绑定。
- 本地历史审计目录中有 442 个旧 reply plans；440 个缺绑定报告均能按 task 号找到计划，且
  report/plan 的 post 与 cursor 440/440 一致。对缺绑定子集，439 个计划有合法旧字段
  `source_payload_sha256`，其中 435 个与“同 post + cursor 由已验证父 payload 的 more 节点
  唯一产生”精确一致；1 个计划 source 无效但图中仍有唯一父；4 个计划 source 合法但父
  first-page report 本身 `response_validation` 不通过，图中没有合法父。
- 对全部 2,918 comment reports 独立解析 payload，2,911 个通过、7 个因
  `report_response_validation_failed` 拒绝。缺绑定的 440 个 reply 中，436 个可由已验证图
  唯一反推父 payload，4 个无合法父；因此正确兼容方向是“唯一图父派生 + 显式绑定一致性”，
  不是接受空 SHA。4 个无父 reply 必须保持 fail closed/orphan，不能因 reply payload 可读而
  绕过其失败的 first-page lineage。
- 对现有 1,231 个显式 source SHA 的 reply 做反向门禁验证，1,231/1,231 都恰好有一个直接
  父 payload，且显式 SHA 全部等于该直接父；其中仅 403 个父是 first page，828 个父是上级
  reply。字段名虽叫 `source_first_page_payload_sha256`，实际受管合同是“直接父 payload”，
  因而新兼容实现可同时加强所有显式报告的 direct-parent 一致性，而不会破坏现有有效数据。
- 第一版兼容 RED 测试按“唯一直接父即可”设计，独立复审指出孤立链/环会互相背书；实现据此
  收紧为 direct parent 唯一后仍须 fixed-point rooted 到合法 first-page。测试覆盖单级、多级、
  无父、多父、同 payload 多语义父、错误显式父、字段缺失/畸形和孤立环，最终 22/22 GREEN。
- P0 真实严格回放得到精确兼容分解：440 legacy-null = 412 rooted derived + 24
  `legacy_reply_source_chain_incomplete` + 4 `legacy_reply_source_predecessor_missing`；931 个
  native reply 全部 direct-parent verified，其他 native failure 为 0。总失败从 441 降为 29
  （另含 1 个 first-page `report_response_validation_failed`），不是通过忽略失败实现。
- 恢复后的 P0 图有 1,013 first pages、1,343 accepted replies、2,356 reachable reports、
  11,731 canonical comments；cursor outstanding 306、page has-next 431、first-page missing 309、
  orphan/cycle/conflict 均为 0。
- 新 comment identity 规模被再次校正：相对 C0=12,986，hydration 交集 8,126、gross new
  **3,605**、C0 retained-not-reobserved 4,860，新增覆盖 156 个父帖；其中 13 deleted/removed、
  72 author_hash null。Base 仍必须保留全部 C0，并在 bot/deleted/quarantine/precedence 审核后
  才能从 3,605 得到 admitted net-new。
- 533 个 Base 外 reports 的 233-post 集合已闭环为 governed exclusions：225 属于 9-lane
  collection-P0/844 但不在 RC3 Base，8 来自 5 份非 P0 首页搜索报告；233 中 189 是窗口外
  `SubredditPost`、15 是窗口内 `ProfilePost`、20 是窗口外 `ProfilePost`、9 只有 raw ID 无
  strict row，**当前可准入 0**。因此它们解释了“候选很多”，但不构成当前窗口的净新增帖子。
- 233 exclusions 的冻结字段覆盖为 title 227、timestamp 224、subreddit 192、payload body
  173、四字段齐全 145；现有 raw builder 会把 search selftext 置空，故 173 条正文尚只是 frozen
  payload 可恢复证据，不能在未审阅正文合同时进入 Base。若未来扩展 2025 年前历史分册，189
  个旧 `SubredditPost` 可单独评估；35 个 `ProfilePost` 和 9 个 raw-only 仍需隔离。
- RC3 Base manifest 已确认精确绑定 5 个文件，canonical counts 为 1,322 posts、12,976 linked、
  10 quarantine、12,986 stored；existing-post hydration 不能伪装成 V2 discovery raw，因为
  `_append_v2_raw_snapshot` 要求 posts/comments 与已融合 Base 全部 disjoint。正确实现需要新增
  sibling hydration snapshot 及 after-base append adapter，且只能添加 `C1-C0` comments。
- 新 rooted parser 对 discovery-only 883 集合重建后输出 SHA 仍为
  `b37e6ca3...2f16`，与原 current raw 9,196,413 bytes 完全 byte-identical、mode 0600；证明
  440 legacy-null cohort 不属于 discovery-only 分区，native 路径没有输出回归。
- P0 按 raw admitted posts 精确拆分为 865 discovery + 457 existing，交集空、并集 1,322。
  existing 分区严格 hydration 为 3,506 observed comments，其中 943 已在 C0、**2,563 gross
  new**；它与 discovery raw 相对 C0 的 1,042 net-new 合计恰为全 P0 的 3,605，两个增量分区
  父帖互斥，不会在 Base append 时重复。
- existing 分区的 457 帖中 first page observed 148、missing 309；accepted replies 526（412
  legacy derived +114 native）、reachable reports 674、cursor outstanding 0、page has-next 92、
  failures 29、orphan/cycle/conflict 0。它适合独立 sibling hydration snapshot，并以明确 coverage
  debt 被 Base adapter 接受，而不是要求虚假的 `complete`。
- 一次只读分区聚合因对 tuple 与 set 使用 `|` 触发 TypeError，未写任何文件；修正为显式
  `set(target)` 后复跑得到上述精确分区。长期规则：集合守恒探针先统一容器类型，再输出计数。
- `build_reddit_existing_post_hydration.py` 已实现 exact Base file hash、discovery partition、
  source-freeze comment member set/bytes/SHA、严格 report graph、C0 集合差、coverage debt 与
  0600/0700 immutable output。真实 snapshot SHA `6a02b7c0...dd4c9`，status 保持
  `blocked_with_explicit_coverage_debt`，不为后续融合伪造 complete。
- 首次 direct CLI 因新脚本只写 `from scripts...` 而在脚本执行路径触发
  `ModuleNotFoundError: No module named 'scripts'`，没有创建输出。按仓库既有 dual-import 模式
  增加 direct/imported 两条导入路径后，focused 5/5 GREEN 且真实构建成功；这是脚本入口合同
  修复，不涉及数据规则变化。
- Hydration immutable writer 初版对同字节重跑仍执行相同 chmod，可能改变 ctime；已改为既有
  输出必须 bytes、file mode 0600、parent mode 0700 全部匹配后直接返回，权限错误只失败不
  修复。单测同时断言第二次调用 mtime_ns/ctime_ns 不变。
- Hydration contract 独立复审判 GO，但指出两个必须项：每个物理 report 必须有 outcome 且
  `unaccounted=0`；Base adapter 必须在 V2 append 后、`_enrich()` 前执行，并验证 P0/C0 都是
  adapter 前 canonical 的子集，不能把 2,563/3,605 硬编码成实际插入数。
- Builder 已补 report outcome conservation：148 accepted first-page +526 accepted reply +0
  duplicate +29 rejected invalid +2,215 excluded non-target =2,918，unaccounted 0；允许失败原因
  仅为 24 chain incomplete、4 predecessor missing、1 response validation failure。新 artifact
  SHA `1fd4d7bb...cf259`、2,087,268 bytes、file 0600/parent 0700，identity conservation 均 true。
- Coverage 分级为 56 full、92 partial、309 not-observed；这些是独立 coverage work facts，
  adapter 不得据此改写既有帖子的 `structural_coverage_grade`，只在 manifest/coverage ledger
  保留，避免将增量观察错误解释为完整线程状态。
- `build_reddit_site_snapshot.py` 当前 V2 adapter 强制新 posts/comments 与 preceding sources
  disjoint，manifest schema/source set/load order 也是封闭 v1 合同。新 hydration lane 应在有
  hydration 参数时产出 manifest v2，同时保留无参数 v1 的 byte/行为兼容；validators 后续双读。
- Existing-post Base adapter 已按 RED→GREEN 实现：先验证 snapshot boundary/privacy、P0/C0
  arrays/count/LF SHA、P0/C0 均为 adapter 前 canonical 子集、coverage/failure reason、N 与 C0
  disjoint；随后仅插入尚未被前序来源带入的评论，same-ID preceding canonical 永远获胜，帖子
  与其 structural coverage 不变。focused adapter 4/4、相关四模块合并 41/41 GREEN。
- 有 hydration 参数时 Base manifest 升级为 v2，source boundary/load order 新增
  `tencent_existing_post_comment_hydration`；无参数仍保持 v1。fusion accounting 同时记录 V2、
  hydration 和按 work-item key 去重的 coverage debt union，避免配置继续只报 V2 debt。
- 为寻找旧 Base 构建命令进行的一次仓库级 `rg` 再次命中单行大型 Insights/report JSON，工具
  输出包含了被截断的 evidence text。已立即停止，后续只从 source-freeze manifest 结构化筛选
  路径/SHA，不再对 `tmp` payload JSON 做全文搜索；最终汇报不得复述该输出。
- 书面规格确认后的断点恢复已重新读取 `task_plan.md`、`progress.md` 与 Plan A；当前批准范围
  仍是 A2 本地候选闭环，生产 L3 只读证据只作为冻结输入，不授予新的远端写入、部署或
  Provider 权限。工作区根没有实体 `AGENTS.md`，本轮以会话中提供的项目契约和 `.kiro/plan`
  为实际治理入口；所有后续输出继续保持 `production unchanged`。
- Existing-post adapter 的二次 fail-closed 加固已完成：物理 report outcome 必须与总文件数
  守恒；first-page/page/partial/not-observed 工单必须与逐帖 coverage 精确同集且 hash 一致；
  cursor/failed-report 逐帖计数、唯一键和 reason Counter 也必须与 accounting 完全一致。
  新增两条 tamper 测试后，V2/raw/hydration 四模块合并回归由 41 扩为 **43/43 GREEN**。
- 新不可变 A2c hydration snapshot 已生成：SHA `56c4c1ed...c958b`、2,284,969 bytes、
  file 0600/parent 0700；457 个 existing posts、2,563 gross-new comments、2,918/2,918
  physical reports accounted、unaccounted 0。coverage 仍为 56 full / 92 partial / 309
  not-observed，29 个失败精确拆为 24 chain-incomplete + 4 predecessor-missing + 1 response
  validation。相同输入重跑返回同 SHA，mtime/ctime/bytes/mode 全部不变。
- Base v2 的九项冻结输入已逐一复核存在、mode 与 SHA：archive 145 files/136 JSON；历史 DB
  `f8cfa072...82c43`；production `0757e1d6...23e5d`；staging `ee754636...5dc81`；V2 raw
  `b37e6ca3...2f16`；identity `58498923...6f59`；tag `22664c9c...82e14`；product ledger
  `cc66f565...51ab`；hydration A2c `56c4c1ed...c958b`。产品 ledger 与 builder 的 pinned SHA
  精确一致，可以进入确定性 Base 构建，不需要读取任何密钥或远端状态。
- 首次 Base v2 构建在 hydration comment field gate fail closed，输出目录未发布。结构化诊断
  证明 2,563 行的 ID/父帖/正文类型/时间/source hashes 均合法，唯一失败项是 author_hash：
  2,521 个合法非空值长度为 30，42 个为 null，而 adapter 错误地只接受 64 位 bare SHA。
- `materialize_reddit_incremental_configs.py` 的本地配置物化仍待补齐 manifest v2 合同：v2
  必须直接消费 `fusion_accounting.comment_coverage_debt_union`，v1 才允许回退到
  `v2_comment_coverage_debt`；本子任务将以字段缺失/类型错误 fail-closed 的 RED 用例约束，
  不做数值相加或缺失补零，且不触碰 validator 与生产环境。
- 当前 materializer 实际只读取 source boundary 中 V2 自身的两项 debt，既不检查 Base manifest
  schema，也不读取 `fusion_accounting`；而 Base builder 的 v2 分支已把去重后的权威并集写为
  `comment_coverage_debt_union`。因此修复点应是按 manifest schema 选择一份已物化 debt 对象并
  严格校验，而不是在 materializer 中重新合并 V2/hydration 数字。
- Base v2 union 的完整合同包含 6 个非负计数、对应 6 个 LF SHA-256、`source_counts` 两个来源
  和 `key_union_not_numeric_sum=true`；Base v1 的兼容 debt 只有 `cursor_outstanding`、
  `page_pagination_outstanding`、`partial_threads`。materializer 的状态判断实际只需 cursor/page，
  但必须先验证所选 schema 对应的整份字段合同，避免接受被截断或零填的对象。
- Materializer RED 已稳定复现：新增 11 个直接测试中的 8 个断言按预期失败，覆盖 v1 错读
  source boundary、v1 缺字段未失败、v2 缺 union 仍回退、v2 union 缺计数/hash/source/去重标志
  未失败，以及 v2 未直接采用 union。其余既有 6 个行为保持通过，说明失败范围集中在新 schema
  选择与完整性合同。
- 最小实现已使 materializer focused **11/11 GREEN**：v1 仅取 fusion 中的三字段 debt；v2
  仅取完整 union，并对 6 个计数、6 个 LF SHA、两份来源计数、hydration failure reason map、
  `coverage_debt_is_not_zero_filled=true` 与 `key_union_not_numeric_sum=true` fail closed。状态判断
  直接使用选中对象的 cursor/page，不做来源相加，也不为缺失字段补零。
- Materializer 脚本与直接测试的 `py_compile` 通过，targeted Pyright 为 **0 errors / 0
  warnings**。该证据仍是本地 L2 代码合同，不等同于 Base validator、候选全链或生产验收。
- 结构化只读检查发现本地 Base A2 候选已存在且 `all_checks_passed=true`；其 manifest v2 union
  精确包含实现要求的 6 个计数、6 个 LF SHA、`source_counts` 和 key-union 标志。项目现有
  coverage/risk/persona 三份模板路径也已定位，可用于不落盘的真实 manifest materialize smoke。
- 不落盘真实 manifest smoke 已双向通过：本地 Base A2 manifest v2 由 union 产出 `mixed/true`，
  RC3 Base manifest v1 由 `v2_comment_coverage_debt` fallback 同样产出 `mixed/true`；两者风险
  policy 均保持 `draft`。smoke 未写候选目录、未调用 validator、未触发远端或生产动作。
- 直接测试最终扩为 **12/12 GREEN**，并补齐 v2 两个 source 子对象和 hydration failure reason
  map 的字段缺失、以及 no-zero-fill 标志缺失的 fail-closed 覆盖；`py_compile` 与 targeted
  Pyright 复跑仍为通过/0 errors。当前无已知 materializer 层 blocker。
- 收尾语义自审新增一组 RED：当 cursor/page 均为 0、但 v1 `partial_threads` 或 v2 union 的
  first-page/failed/partial/not-observed debt 非零时，旧状态逻辑错误给出 `thread_complete`；2/2
  精确用例失败。`search_has_next_truncates_window` 仍只应由 cursor/page 决定，评论 coverage
  状态则必须检查所选 debt 对象的全部计数字段。
- 该语义缺口已 GREEN：直接测试现为 **13/13**，comment coverage 按所选 v1/v2 debt 的全部
  必填计数字段做布尔 `any`，不相加；search truncation 仍只看 cursor/page。`py_compile`、
  targeted Pyright 0 errors/0 warnings，且真实 Base A2 v2 与 RC3 v1 不落盘 smoke 复跑均为
  `mixed / search_has_next=true / risk=draft`。
  `_pseudonym()` 和其他既有 source adapters 已明确支持 colon/非 64 位 opaque author hash；
  因此这是新 adapter 合同过窄，不是源数据损坏，修复必须验证 opaque-token 语法而非放弃校验。
- 源实现 `_hash_author()` 已给出唯一正式格式：`author_sha256:` + 16 位小写 hex。Hydration
  adapter 已改为只接受该 exact token 或 null，并新增“合法 token 生成稳定 pseudonym”与“64 位
  裸 SHA 仍拒绝”测试；没有接受任意字符串，也没有削弱作者隐私合同。
- Author token 修复后相关回归 **44/44 GREEN**；同一 Base 构建命令随后通过全部内置 checks
  并原子发布本地 manifest-v2 候选：1,322 posts、16,581 linked comments、10 quarantine，
  即 16,591 stored comments；analysis covered 17,903 entities，tagged 553 posts / 4,990 comments。
  与 C0 对比的 stored-comment 集合增长为 3,605，帖子净新增仍为 0；这些是 Base 构建事实，
  尚未等同于独立 validator 或五本账验收。
- Base v2 的 coverage debt key-union 已结构化复核：327 first-page/not-observed、306 cursor、
  431 page continuation、438 partial、29 failed reports；source 维度分别保留 V2 与 existing
  hydration 数字，且 `key_union_not_numeric_sum=true`。候选根 mode 0700，六个 Base 文件当前
  沿用 builder 的 0644 发布合同。
- 旧 `validate_reddit_site_snapshot.py` 对同一候选按预期 RED，精确停在
  `ValueError: manifest schema mismatch`；未进入内容误判。这证明下一步必须实现 v1/v2
  双读和 v2 source/debt 合同，不能通过改回 v1 manifest 来隐藏 hydration 来源。
- 本轮站点 validator 适配边界已收窄：仅修改 `validate_reddit_site_snapshot.py` 与其直接
  单测，v1 的五来源 schema/load-order 行为保持不变；v2 必须新增 existing-post hydration
  来源，并从实际 canonical `source_occurrences` 与 work-item key 集合复算增量/coverage
  守恒，不能只相信 manifest 中的汇总数字。
- 改动前基线已新鲜复现：v1 validator 直接测试 19/19 GREEN；真实 A2 Base 候选用旧
  validator 返回 exit 1，首个且唯一暴露的阻断仍是 `manifest schema mismatch`。这建立了
  v2 RED，同时证明现有 v1 合同尚未被本轮改动影响。
- v2 manifest 的 hydration boundary 足以从 canonical 复算实际 materialized comment
  occurrence、0 帖增量、父帖集合和 coverage work-item 的去重/集合计数；V2 first-missing 可由
  18 个 lineage gaps 复算，V2 partial 可由实际 V2 posts 的结构覆盖等级复算。当前 manifest
  没有携带 V2 cursor/page/failed 的逐项 key，因此 validator 可独立复算它们的 union count
  （两个 post partition 已可证明互斥），但无法从 Base 单体重新生成这三类 union LF hash；这些
  hash 只能做格式/存在门禁。后续五本账若要求 LF hash 独立重算，需把 V2 work-item keys 纳入
  私有 manifest 或向 validator 显式提供冻结 V2 raw 输入，不能伪称现有字段已支持。
- 新增 8 条 v2 直接测试后 RED 已固定：原 19 条 v1 仍全绿；v2 正常样例和七类 tamper
  全部先在旧代码的 `manifest schema mismatch` 失败。后续 GREEN 必须分别抵达第六来源、
  load-order、canonical occurrence、hydration disjointness、work-item uniqueness、union count
  与可重算 union hash 的专用门禁，不能只放宽 schema 常量。
- 站点 validator 的 focused RED→GREEN 已完成：27/27。v2 现在要求六来源和精确 load-order，
  hydration comment 必须是独占来源且父帖不属于 V2 discovery，boundary 的 input/materialized/
  overlap/net-new 必须与 canonical source occurrences 守恒；coverage work items 会做字段、身份、
  唯一性、partition、failure reason 与 debt 数量复算。v1 fixture 和原 19 条行为保持通过。
- 真实 A2 Base 已由新 validator 只读通过：status `passed_release_candidate`，1,322 posts、
  16,581 linked、10 quarantine、16,591 stored、16,417 进入 VOC metrics；无 receipt 文件写入。
  审计同时补上 stale-receipt 防线：仅 manifest-v2 receipt 新增 exact `manifest_sha256`
  `de8b504d...d6443`，v1 receipt 明确不新增该字段，validation schema 仍保持 v2。focused
  27/27 重跑与真实候选 CLI 均 exit 0。
- 静态验证补充：focused 两文件 Pyright `0 errors / 0 warnings`，`py_compile` exit 0；当前 Python
  环境没有安装 `ruff`，因此不把 lint 宣称为已跑。一次 Pyright 首跑准确暴露 hydration debt
  字典的窄类型推断，已用显式 `dict[str, Any]` 修复后转绿，不涉及运行时合同放宽。
- 最终合并复验 exit 0：直接测试 27/27、Pyright 0/0、`py_compile` 通过；真实 RC3 manifest-v1
  仍以 1,322/12,986 stored/12,976 linked/10 quarantine 通过且 receipt 不含新 SHA 字段，真实
  A2 manifest-v2 以 1,322/16,591/16,581/10 通过且 receipt 精确绑定 manifest SHA。两次回放
  均为内存返回、没有写正式 receipt，`production unchanged`。
- Base v2 manifest 的真实结构已核对：`source_boundaries` 有六个来源，fusion load order 明确
  把 existing hydration 放在 V2 后；`expected_from_source_net_new` 与 `actual_canonical` 同为
  1,322 posts / 16,591 stored comments，actual 再拆 16,581 linked + 10 quarantine。仓库目前
  不存在 candidate-ledger builder/validator 文件，A2 四本账仍需按批准计划新增，不能把现有
  incremental validator 冒充五本账。
- Canonical Base 的 source occurrences 已结构化计数：post occurrences 为 archive136、
  historical48、staging301、production98、V2 865；linked-comment occurrences 为 archive4153、
  historical1894、staging3225、production444、V2 8225、existing hydration2563。它们是
  canonical provenance，可多源重叠，不能与身份净新增直接相加。
- Source-freeze manifest 是 5,928 行文件 occurrence（每行含 namespace/kind/path/bytes/SHA/
  fusion eligibility），而非 component summary；它适合作为 occurrence ledger 的完整物理输入。
  生产 baseline snapshot 则直接包含 posts/comments/identity evidence，可用于 P0/C0 集合差。
- 进一步校正“生产 baseline”语义：`production-content-a1.json` 只是 DB primary 的 98 posts /
  454 comments 输入来源，不能当作发布集合 P0/C0。Plan A 的动态发布基线必须使用当前 RC3
  Base manifest `a900e6ce...c3abd`：P0/L0/Q0/C0 = 1322/12976/10/12986。
- 以 RC3 Base 与新 Base v2 做独立集合差，得到 P1=1322、C1=16591，`P1-P0=0`、
  `C1-C0=3605`、`P0-P1=0`、`C0-C1=0`、L1/Q1 overlap=0，且所有 16,581 linked comments
  父帖存在。这才是 release net-new 的正确集合事实；此前 DB-primary 的 1,224/16,137 差值
  只是 source-layer 增量，不得写入发布账本。
- A2 账本写入可复用 `capture_reddit_candidate_sources.py` 已验证的 canonical UTF-8、0700/0600、
  `created/no_change/collision` 原子写模式，但账本 builder/validator 必须保持独立聚合，不能直接
  信任彼此的 summary。现有 incremental candidate gate 面向完整 release，不等价于 A2 ledger gate。
- Source freeze 的 occurrence partition 精确为：3,306 fusion-eligible（3,146 remote reports +
  160 local data）和 2,622 governed non-fusion（2,613 plans + 9 documentation），合计 5,928。
  当前私有根中没有已物化的 233-post exclusion/lineage ledger，不能用先前口头聚合代替 A2 明细账。
- 既有 strict search parser 会保留每个 row 的 wrapper/typename，并将非 `SubredditPost` 作为明确
  row rejection；comment scanner 则会把 target 外 reports 计为 excluded。A2 可复用这些严格
  envelope/payload 规则来构造 233-post governed exclusions，但必须新增可重复验证的明细制品。
- Current identity 的 event window 为 `[2024-12-31T16:00:00Z, 2026-07-15T16:00:00Z)`；228 份
  search reports 全部通过严格 envelope，包含 1,516 rows：1,425 SubredditPost、91 ProfilePost。
  两类都只有 `createdAt` 作为事件时间字段，可据此做确定性窗口分类。
- Search coverage ledger 是 69 行 lane 明细，而非 dict：19 terminal/non-debt、50 has-next/debt；
  row stable key 可用 lane_index + term_sha256。A2 coverage ledger 应保留这 69 行 search_lane
  work items，并另行加入 lineage/cursor/comment_page/failed-report，不能只抄 Base 的 summary。
- 233-post governed exclusion 已用 strict parser 独立复现且守恒：533 comment reports = 233
  first-page + 300 reply；233 unique external post IDs 精确分类为 189 window-outside strict
  SubredditPost、15 in-window ProfilePost、20 out-of-window ProfilePost、9 raw-ID/no-strict-row。
  Search occurrence 是 190/15/20（其中 1 个外窗 SubredditPost 有两次一致 occurrence）；当前
  窗口 strict SubredditPost 准入数仍为 0，所有 search/report envelope failures 均为 0。
- RC3 与 Base v2 的 managed-source fields 对比显示 1,322 posts 和 12,976 existing linked comments
  全部 unchanged；3,605 新 linked comments 中 13 deleted/removed 且 `include_in_voc=false`，其余
  3,592 进入 VOC。父帖全部存在，但 parent-comment 状态为 linked1495 / missing6 / unknown2104；
  这属于 parent-depth metadata debt，不影响 post foreign-key 守恒，账本必须显式保留。
- A2 四本账 builder 已按先 RED 后 GREEN 实现：Import RED 后 6/6 纯合同测试通过，覆盖
  managed-hash、外部帖子分类、append-only、relink、coverage key 和 0700/0600 immutable collision。
- 首次真实账本 artifact 已生成于 `tmp/reddit-voc-plan-a1-20260715/ledgers-a2d`：occurrence
  5,928、post 1,555（1,322 canonical +233 exclusions）、comment 16,591、coverage 1,618；
  release net-new posts/comments = 0/3,605，manifest SHA `4e67cb79...bb443`，四类 unaccounted
  与 total 均为 0。该结果仍等待独立 validator 与对抗复审，尚不升级为 A2 accepted。
- A2d 相同输入重跑 bytes/SHA 和全部文件 mtime/ctime/mode 不变；root 0700、五个文件均 0600。
  明细守恒：occurrence 3306 fusion +2622 control；post 1322 unchanged +233 rejected；comment
  12976 unchanged +10 quarantine-retained +3605 new（3592 VOC /13 excluded）；coverage 19 closed
  +1570 open-carried +29 rejected-accounted，类型恰为 search69/lineage18/first327/cursor306/
  page431/partial438/failed29。233 个 rejection reason 分解与独立 probe 完全一致。
- Site validator 已完成 v1/v2 双读并在真实 RC3/A2 上通过；v2 receipt 新增 exact Base manifest
  SHA，v1 receipt 不变。Incremental validator 同步要求该 v2 exact binding；materializer 对 v2
  只消费 coverage union、v1 只消费旧 V2 debt，不回退、不相加、不零填。三条变更仍需主线程
  合并回归后才作为最终证据引用。
- 独立 ledger validator/reviewer 指出 A2d 与批准规格不一致：occurrence/comment/coverage 状态
  被压缩、stable key 缺 bytes/cutoff、八个 P/L/Q/C identity SHA 缺失，且 18 个 lineage gaps
  只在 coverage 而未进入 post ledger。A2d 因此明确 superseded；未把“unaccounted=0”误报为
  规格通过。
- Builder 已升级为 manifest v2 并生成 A2e（SHA `fc8ae767...f5c2a`）：四本账每行都绑定同一
  canonical input-evidence SHA 与 source cutoff；八个 P0/L0/Q0/C0/P1/L1/Q1/C1 count/LF-SHA
  完整。Occurrence 为 3306 accepted-new +1 accepted-duplicate +2621 quarantined-input；post 为
  1320 unchanged +2 upgraded +18 pending-lineage +233 rejected；comment 为 12976 unchanged +10
  existing-quarantine-retained +3605 new-linked；coverage 为 19 closed-no-more +1570 open-carried
  +29 nonretryable-rejected。所有文件 0600、root 0700、unaccounted total 0，等待独立 validator。
- 增量候选 validator 的 v1/v2 双读已作为独立窄任务启动；本轮只允许修改
  `validate_reddit_incremental_candidate.py` 及其直接测试。验收重点是 v1 行为不变、v2
  hydration source/load-order fail closed，并优先消费 Base 的
  `fusion_accounting.comment_coverage_debt_union`；证据等级限于本地 L2，`production unchanged`。
- 现有 `_validate_base()` 将 Base manifest schema 硬编码为 v1，并直接把 freeze 的 cursor/page
  与 `tencent_v2_search_hydrated.comment_coverage_debt` 绑定，同时只要求
  `fusion_accounting.v2_comment_coverage_debt == v2 debt`。因此它既无法读取 manifest v2，也会
  在 hydration 已形成 key-union 时错误地继续输出 V2-only debt；需要以 schema 分支保持 v1
  原路径，并为 v2 增加 source/load-order/union 精确门禁。
- Base builder 的 v2 生成位置已定位：仅在 hydration 输入存在时 schema 升为 v2，新增
  source boundary `tencent_existing_post_comment_hydration`，并在既有 V2 append 之后追加
  `tencent_existing_post_comment_hydration_append`；fusion 新增
  `comment_coverage_debt_union`。本轮增量 validator 必须对这三个条件整体校验，且不能改动无
  hydration 的 v1 fixture/路径。
- 真实 Base A2 v2 的安全聚合结构已确认：union 包含 first-page/cursor/page/failed/partial/
  not-observed 的计数和 LF SHA、两类 source_counts 及
  `key_union_not_numeric_sum=true`。V2-only debt 为 cursor 306/page 339/partial 346，而 union
  为 cursor 306/page 431/partial 438，并额外有 first-page 327、failed 29、not-observed 327；
  因此增量 receipt 若继续引用 freeze/V2-only page/partial 会实质低报 hydration coverage 债务。
- 增量 validator 新测试已形成预期 RED：原 15 个用例继续通过，新增 v2 正常路径因
  `base_schema_invalid` ERROR，三个 hydration/source/load-order/union tamper 用例也因旧实现只
  识别 v1 而未命中目标 fail-closed reason；总计 19 tests = 15 pass + 3 fail + 1 error。v1 receipt
  精确四字段兼容测试在 RED 阶段仍通过，说明失败范围仅位于尚未实现的 v2 分支。
- 最小实现后增量 validator focused **19/19 GREEN**：v1 receipt 仍精确为 lineage/cursor/page/
  partial 四字段；v2 强制六来源 exact set、hydration-after-V2 exact load order、existing-post
  append-only/accounting/side-effect 合同、hydration debt 双重绑定及 key-union 计数范围守恒。
  v2 receipt 直接采用完整 `comment_coverage_debt_union` 并保留 freeze lineage gap，不再从
  freeze/V2-only debt 低报 page/partial 或遗漏 first-page/failed/not-observed。
- 静态检查环境中 `python3 -m ruff` 不可用，且 `.venv/bin/ruff`/PATH 也不存在；没有重复执行
  同一失败命令。`py_compile` 已通过。人工窄审确认改动仅位于增量 validator 和直接测试，未
  触碰 site validator/materialize；下一步使用项目可用的格式化工具或纯语法/单测证据补足。
- 新增逻辑已对真实 Base A2 v2 manifest 做只读结构/全文件哈希回放并通过：1,322 posts、
  16,591 stored、16,581 linked、10 quarantine；增量 validator 选中的 debt 为 first-page 327、
  cursor 306、page 431、failed 29、partial 438、not-observed 327，证明真实候选路径确实使用
  union。该回放只配了临时本地 receipt fixture，不是完整 cross-layer candidate acceptance。
- 一次扩展 unittest 命令漏传 `PYTHONPATH=src`，导致两个 site builder 模块在收集阶段报
  `ModuleNotFoundError: reddit_voc`；增量 validator 自身 19 个仍全绿。该失败是调用环境错误，
  不是代码回归；下一次改用正确环境重跑，不重复原命令。
- 修正环境后 raw/hydration/Base builder/增量 validator 五模块合并回归 **63/63 GREEN**；
  `_validate_base` 无仓库外调用点，内部返回值扩展不会影响其他脚本。当前本地证据支持“v2
  union 校验与 receipt 投影实现完成”，不支持完整 Insights/Reports/Personas/public/dist 候选已
  重建或生产已变化。
- 跨层自审发现独立 receipt 的既有绑定债务：`reddit_voc_site_snapshot_validation_v2` 当前只含
  dataset version/counts/checks，不含 exact Base manifest SHA；同版本同 counts 的 stale receipt
  理论上可与另一 manifest 配对。增量 validator 已直接复验 v2 source/load-order/hydration/union
  以降低风险，但 exact receipt→manifest 绑定仍应由 site receipt 新增 manifest SHA 后闭合；已
  向主线程与 site-validator agent 提醒，未自行跨文件修改。
- Site-validator lane 同意仅对 manifest v2 receipt 增加 exact `manifest_sha256`，schema 名保持
  validation-v2，v1 receipt 不变。增量 lane 已用 stale-SHA 用例完成二次 RED（旧实现未抛错）
  →GREEN；现在只对 Base manifest v2 要求 receipt SHA 等于当前 `manifest.json`，direct tests
  扩为 **20/20 GREEN**，从而关闭同版本同 counts stale receipt 配对风险。
- 加入 receipt SHA 后再次对真实 Base A2 做全文件哈希/union/临时 exact-receipt 绑定回放通过；
  五模块合并回归更新为 **64/64 GREEN**。`py_compile`、AST parse 和 Pyright 均通过，Pyright 为
  **0 errors / 0 warnings / 0 informations**。没有使用网络、远端、DB 写入或生产动作。
- A3 构建入口已只读确认：Insights 消费 Base + sample + decisions；Reports 消费 Base + Insights；
  Personas 消费 Base + Insights + config + avatar dir；public projection 消费同一 data root 下四个
  version。RC3 的 materialized config 目录包含 coverage-profile、risk-gate-policy、personas-config
  与 manifest，两个 synthetic SVG avatar 可复用；A2 独立验收前尚未写 A3 输出。
# 2026-07-15 Candidate ledger validator agent findings

- 独立 validator 的事实源必须是 source freeze、RC3 baseline Base、candidate Base、V2 identity/raw、existing-post hydration 与 frozen report root；四本 JSONL 和 `candidate-ledger-manifest.json` 仅作为待核验输出，不能作为复算事实源。
- 当前 builder 输出合同为 `reddit_voc_candidate_ledger_manifest_v1`，账本四本：source occurrence、post identity delta、comment identity delta、coverage work；manifest 声明输入 SHA、逐账 rows/bytes/SHA、四类 accounting、集合关系与无副作用边界。
- 233 个 Base 外 post exclusions 必须从 comment report root 与 strict search rows 独立复算；合法原因只允许 window-outside subreddit、window-inside/outside profile、raw-id-without-strict-row，若出现当前窗口 strict `SubredditPost` 却未进入 candidate Base 必须 fail closed。
- 真实 A2D ledger root 为 `tmp/reddit-voc-plan-a1-20260715/ledgers-a2d`，root/member 权限实测为 0700/0600，manifest SHA `4e67cb79d9e02a83ed7c22b4d917178806ab507736384781f3f4d1774e8bb443`；四账行数 5928/1555/16591/1618，release net-new posts/comments 为 0/3605，post exclusions 233，`unaccounted_total=0`。这些仍是 builder 输出，独立 validator 通过前不能升级为独立验证事实。
- Builder manifest 只绑定上游 SHA，不包含路径；独立 validator CLI 必须要求显式传入所有上游路径和 candidate root，避免按 SHA 扫描工作区或信任可篡改路径。
- 已批准规格要求 managed-field hash 覆盖结构覆盖和受管分析绑定；旧 builder 的 post/comment 白名单未覆盖这些字段。用扩展白名单只读复算当前 Base：1322 个共同帖子中有 116 个发生受管变化（98 个 count completeness、2 个结构/评论覆盖、45 个讨论品牌字段，存在交叠），而旧 A2D 将 1322 全报 `existing_unchanged`，因此 A2D 必须 supersede；共同评论的扩展白名单变化为 0。
- Source freeze 提供精确 `source_cutoff_utc=2026-07-15T08:47:22.379946Z`，可作为 occurrence stable key 的 `observed_cutoff`。5928 个冻结 occurrence 分区为 3306 fusion eligible + 2622 control-only；按 `(bytes,sha256)` 只有 1 个重复组、1 个额外 occurrence，位于非融合 plan 来源。
- Parent 裁决：validator 必须严格遵循批准规格，不能为旧 A2D 放宽；A2D 标记 superseded，builder 将在新不可变目录生成修订 artifact。Validator 只接受修订后的 strict contract。
- Source freeze 自身的 `file_manifest_lf_sha256` 复算格式固定为 `namespace|relative_path|bytes|mtime_ns|sha256|fusion_eligible-lowercase\n`，并同时绑定总 bytes、eligible/documentation counts；validator 将独立校验该闭环及 report-root 精确成员集。
- Strict parser 对完整 comment-report universe 的独立聚合：1573 post outcomes（1322 P1 + 18 pending lineage + 233 external），2918 frozen reports = 1240 valid first page + 1643 valid reply + 7 invalid first page + 28 invalid reply；missing-first 333（含 7 invalid）、child cursor outstanding 306、page has-next 479，orphan/cycle/conflict/duplicate/ignored 均 0。
- 因此 coverage work ledger 的严格 universe 是 4116 行：69 search lane + 18 lineage + 1573 comment-first-page + 1977 cursor（1643 success + 28 failure + 306 outstanding）+ 479 comment-page。状态应为 `closed_success=2883`、`closed_no_more=19`、`nonretryable_rejected=35`、`open_carried=1179`；派生 `partial_thread` 和独立 `failed_report` 会重复记账，必须移除，失败挂回真实 first-page/cursor key。
- 233 个 rejected parent posts 下共有 527 reachable valid reports、2155 unique comments，均与 C1 零交叠；这些 comment identities 应以 `rejected`/`parent_post_<post_reason>` 进入 comment ledger，但不计 release net-new。35 个 invalid comment report occurrences 应在 source occurrence ledger 标 `rejected_invalid`。
- A2f 对抗复审新增一条可复现 P1：builder 虽输出 18 个 pending-lineage，但没有把该集合精确绑定到 V2 identity freeze/Base boundary；将 raw accounting 中一个 gap ID 换成合法格式假 ID 仍会被接受。修复门禁必须要求 pending set、count、LF SHA 与 `v2_boundary.lineage_gap_post_ids` 和 identity freeze accounting 精确一致，并加 RED→GREEN tamper 测试。
- Coverage ledger 的批准语义是“每个冻结工单唯一状态”，不能只列债务摘要。严格全集裁决固定为 4,116 行：search lane 69、lineage 18、comment first-page 1,573、cursor 1,977、comment page 479；状态精确为 closed-success 2,883、closed-no-more 19、nonretryable-rejected 35、open-carried 1,179。`partial_thread`/`failed_report` 是派生重复计数，必须移除，35 个失败分别落回 7 个 first-page 与 28 个 cursor 真工单。
- 冻结 comment-report root 可直接复算完整 coverage 工单，而不必拼接 V2/hydration 债务摘要：完整 post outcome universe 为 P1 1,322 + pending lineage 18 + governed external 233 = 1,573；现有 strict scanner 对该全集给出 1,240 valid first、1,643 valid reply、35 invalid、326 真 missing-first、306 outstanding cursor、479 has-next page。成功报告因此也可被稳定写入 `closed_success`，不会再被债务摘要遗漏。
- V2 identity freeze 的 `global_known` 明细为 1,340，Base v2 boundary 的 `lineage_gap_post_ids` 为 18，count 与 LF SHA `65fe7d82...b4dcd` 可独立复算一致；最强 binding 应验证 `global_known - P1 == lineage gaps`，同时要求 raw accounting、Base boundary 与 identity freeze 三者 exact set/count/hash 相等。一次只读结构探针因把 list 当 dict 排序触发 `TypeError`，已更换为显式类型分支后成功，未重复原错误动作。
- 书面规格的 coverage stable key 明确为 `lineage:<post>`、`cursor:<post>:<cursor_sha>`、`comment_page:<post>`、`search_lane:<lane>:<term_sha>`；严格复算新增 `comment_first_page:<post>` 以覆盖每个冻结 first-page 结果。状态枚举本身不变，成功报告应进入 `closed_success`，不是被债务摘要省略。
- Base 的 coverage union 实现证明 failed-report LF key 是 canonical failure row 的 SHA；因此把失败落回 first-page/cursor 真工单时，行内仍须保留 `report_failure_sha256` 以独立复算 29 个 governed failures。`partial_threads` 不是独立工单，union 校验应从 raw partial posts + hydration partial posts 的显式集合复算，不能重新加入 `partial_thread` ledger rows。
- 新 coverage/lineage RED 已按预期建立：旧实现对 `partial_thread`/`failed_report` 均未拒绝、新 failure evidence 参数不存在、lineage exact helper 不存在，focused 10 项为 3 failures +1 error；这四个失败均精确指向待实现合同，既有 6 项保持通过。
- 第一轮 GREEN 实现后 9/10 通过，lineage exact tamper、derived-type rejection、failure-on-real-work-item 均转绿；剩余 1 项是旧 union fixture 将 open first-page 的 `partial_threads` 仍填 0，与新“债务工单推导 partial”语义矛盾。合并命令因后续 `py_compile` 成功返回 shell 0，不能把整组误报为通过；必须单独修正 fixture 后重跑测试命令并读取 unittest 结果。
- 修正旧 fixture 后 focused **10/10 GREEN**，随后真实冻结输入成功生成 A2g：`tmp/reddit-voc-plan-a1-20260715/ledgers-a2g`，manifest SHA `3863c79c...297007`；四账行数 5,928 / 1,573 / 18,746 / 4,116，release net-new post/comment 为 0/3,605，`unaccounted_total=0`。CLI 明确返回 provider/database/remote/deploy/live-send false、`production_unchanged=true`。
- A2g 仅是 builder 事实，尚未接受：必须再完成独立 validator、对抗 reviewer、同输入 immutable rerun、合并回归。此前两个 sub-agent 任务已退出 live tree，不能把它们对 A2f 的部分通过当成 A2g 验收；需用现有独立 validator 文件重新启动新鲜复验。
- A2g 同参数真实重跑返回完全相同 manifest SHA；五个文件的 path/bytes/mtime/ctime/mode 组合树 SHA 前后均为 `8e0fa60c...44928`，root stat SHA 前后均为 `0c25ab2e...95edc`，证明 no-change 没有重写内容或元数据。
- 独立结构化聚合确认 A2g 五文件 manifest bytes/SHA 全部精确、root 0700/member 0600、每行 cutoff/input evidence exact。状态分解为 occurrence `1 duplicate +3256 accepted +2621 quarantined +35 invalid +15 superseded`；post `1166 unchanged +156 upgraded +18 pending +233 rejected`；comment `12976 unchanged +10 quarantine-retained +3605 new-linked +2155 rejected`；coverage `2883 success +19 no-more +35 rejected +1179 open`。Coverage 4,116 keys 全唯一，type 为 69/18/1573/1977/479，derived type 0，35 失败均有 failure evidence，2,883 成功均有 report SHA。
- A2g 生成后首轮八模块合并回归 **105/105 GREEN**：raw22、hydration5、Base hydration7、site validator27、incremental validator20、materializer13、ledger builder10、validator import-independence1。该结果证明当前本地代码合同未回归，但独立 validator 仍在执行真实 5,928/4,116 行复算，尚不能据 105/105 单测单独宣布 A2 accepted。
- Targeted Pyright 首跑为 **11 errors**：builder 9 个均是新增路径的 optional/narrowing 类型问题（external reason lookup、tuple target_ids、hydration list narrowing），测试 2 个来自 `getattr(..., None)` 的 optional-call。运行时与 105/105 未失败，但静态门禁未通过；必须最小收窄类型后复跑，不能把 py_compile 或 runtime green 代替 Pyright。
- 最小类型收窄后 targeted Pyright 已转为 **0 errors / 0 warnings / 0 informations**：显式处理 candidate quarantine impossible branch、把 strict target IDs 转为 tuple、对 raw/hydration list 做 fail-closed 类型验证，并让测试直接导入 helper。没有放宽运行时合同。
- 这些纯类型改动仍会改变 manifest 绑定的 `builder_code_sha256`，因此 A2g 不再是当前代码快照的最终候选；已通知独立 validator/reviewer 暂停 A2g 最终 receipt。必须在 focused 回归后生成新不可变 A2h，再以 A2h 做最终双重验收。
- A2g 独立预审另外揭示 canonical contract 未统一：4,116 个 key/status/type/count 均一致，但 4,029 个 comment-work rows 的 source/reason/可选 report evidence 不一致；validator 又要求 posts accounting 显式记录 `rejected_comment_candidates=2155`、`invalid_comment_report_occurrences=35`，且其 top-key 集未接受 builder 已保留的 `source_identity_universe`。因此不能仅因类型 SHA 变化重生 A2h，必须先统一并加强 builder/validator schema。
- 第一性原则裁决：不删除 `source_identity_universe`、2,155 rejected comments、35 invalid report occurrences、`report_sha256`/`report_failure_sha256`；validator 必须从事实源独立复算并加 tamper tests。Coverage `source` 统一表达物理来源/推导来源，不再用 V2/hydration/external post admission partition 复用该字段；Base union 的 governed/external 分区改由 post identity 集合独立判断。
- Builder canonical contract 已统一：first-page/reply 的成功或失败 source 为 `frozen_comment_reports`，真正未观测 first-page 为 `candidate_post_universe`，outstanding cursor/page 为 `derived_comment_coverage`；成功 reason 固定 `first_page_report_validated`/`reply_report_validated`。报告 SHA 与 failure canonical SHA 保留，union 以 candidate+pending post IDs 排除 external，而不是读取 source 标签。
- Manifest posts accounting 已显式加入 2,155 rejected comment candidates 与 35 invalid comment report occurrences；`source_identity_universe` 原样保留。新增 governed/external union 单测后 builder focused **11/11 GREEN**、targeted Pyright **0/0/0**。下一步生成 A2h，并要求独立 validator 对新增字段逐项复算/tamper，而不是只扩 allowed keys。
- 首次 A2h build 按预期 fail closed 于 `coverage_input_evidence_invalid`，原因是 canonical source 新增后 evidence allowlist 尚未同步；没有输出目录/候选写入。已补齐 `frozen_comment_reports`、`candidate_post_universe`、`derived_comment_coverage` 三类映射，未放松 SHA 规则。
- Accounting schema 再按业务语义收敛：35 invalid occurrences 放在 source-occurrences accounting 且必须等于 `rejected_invalid`；2,155 rejected candidates 只在 comments accounting；posts 不重复评论数字。Coverage helper 现在强制 success/failure first/cursor 必有 report SHA、failure 必有 canonical failure SHA、open work 不得伪造 report SHA。新增 tamper test 后 focused **12/12 GREEN**、Pyright **0/0/0**。
- 当前正式待验 A2h 已生成：`tmp/reddit-voc-plan-a1-20260715/ledgers-a2h`，manifest SHA `bcc1ac74...f87639`，四账 5,928/1,573/18,746/4,116，net-new post/comment 0/3,605，unaccounted 0。相同输入重跑 manifest SHA 不变，五文件 stat-tree SHA 前后 `94ac6019...56977b`、root stat SHA 前后 `5bb04efe...3bd4a`，证明 bytes/mtime/ctime/mode 未重写。
- A2h 结构化复核：manifest builder SHA 与当前代码 exact `f0109182...cb3e3`；coverage 2,918 report-backed rows（1,240 first success +1,643 reply success +35 failures）均带 report SHA，35 failures 另带 failure SHA；326 missing-first、306 outstanding cursor、479 page debt 不伪造 report SHA。来源分解为 frozen-report2918 / candidate-universe326 / derived785 / search69 / lineage18，4,116 keys 全唯一。Source identity universe 六组 count/hash及 candidate union true 均保留。
- Reviewer 已独立把 A2h coverage 从冻结 reports 复算到 **4,116/4,116 byte-equivalent**，八 identity sets、六个 source identity sets、candidate union 和 18 lineage 的 post/coverage/raw/Base/identity 多点绑定均一致；当前事实层没有数量 blocker。
- 正式 validator receipt 前仍需关闭两条 tamper surface：其 lineage helper 必须同时证明 `global_known - P1 == pending` 与 `current_site == P1`；governed selected SHA 必须使用固定 source-boundary/tagging/baseline allowlist，禁止 `_string_values(candidate_manifest)` 把任意无关 64hex 当作 load-order 证据。另有一处 occurrence row literal 重复 key 是无运行影响的 P2 清理项。
- A3 semantic 只读交叉验证否定了“只改旧 review sample 的 Base SHA”：旧100与A2新100只有18 audit IDs重合，其中10行完整证据一致；旧100在A2全量 population 中有83 assignments仍保持语义证据，17条旧held L2-PUMP已消失。两个已promoted tags的20/20 assignments仍存在且语义证据一致；字典 identity仍为 `dim_tag_v6.3_final` / `22664c9c...82e14`。
- A3 推荐走“旧治理结论 + 当前 Base manifest-bound projection”，不宣称A2已做新人工复核：semantic governance应取原始 v1 audit `data/processed/reddit_voc_insights_20260714/semantic-audit.json`（SHA `8747e0f2...6d5e7`），保留2 promoted/8 held结论，但四个 legacy UI fields必须按A2重算，不能把旧 `insights.json` 的221-base headline/signals直接盲拷。需新增 projection provenance `governance_projection_no_new_review`、reviewed assignments null、A2/旧audit/旧Base/字典四重绑定，并增强 analytics validator重新打开/rehash semantic source及复算carry-forward evidence。
- 若改为“新 Base 全量复核”，至少90/100新样本需重新人工审核；当前 semantic sample builder 还把15条新来源错误归入 unknown，且旧 insights snapshot builder硬编码20260714 v1。当前应先采用治理投影路线，避免把未复核样本包装成审核通过。
- A2h identity/ledger gate 最终独立双审 GO：validator/reviewer P0=0、P1=0；主线程真实 validator 复跑 exit 0，receipt stat SHA 前后 `fcd11a37...d164c`。最终唯一可消费 receipt 为 `ledger-validation-a2h-r2/candidate-ledger-validation-receipt.json`，SHA `5700b8e4...bc913`；它 exact 绑定 manifest `bcc1ac74...f87639`、builder `f0109182...cb3e3`、validator `202a7a2d...e3fff`、coverage union `44cee85a...b6d0a0`。
- 主线程最终 A2 合并回归 **115/115 GREEN**，targeted Pyright 0 errors/warnings/informations，py_compile 通过。A2 的 `unaccounted_total=0` 没有隐藏 1,179 open-carried 与 35 nonretryable；这里只接受 identity/ledger gate，不等同于 A3 analytics/public 或生产发布完成。
- 唯一 P2：旧 `ledger-validation-a2h/` preliminary receipt 仍物理存在并标 passed，但绑定旧 validator；A2g及更早 artifacts也已superseded。所有后续脚本/registry必须显式 allowlist r2 path+SHA，永不按目录或mtime自动选择 receipt。
# 2026-07-15 — A3 断点恢复

- 已从 A2h GREEN 断点恢复：下一步只进入本地 A3 经营派生与 reconciliation；A2 身份/账本结论不重做。
- 仓库根目录当前没有实体 `AGENTS.md`，本轮按用户消息内提供的完整契约执行；这不是数据或构建异常。
- 当前仍保持 `production unchanged`、`provider_call=false`、`database_write=false`、`remote_write=false`、`deploy=false`。
- `brainstorming` 的设计门禁已由已批准 umbrella spec、三个 implementation plan 和用户“书面规格确认”满足；A3 是既有 Plan A 的续做，不重新设计 UI。
- `voc-nlp-enrichment` 的主 `SKILL.md` 可读，但其列出的 `references/workflow-detail.md` 实体缺失；本轮仅采用主文件中可核实的增量识别、实体/标签、趋势和结构化输出合同。
- `evidence-grade-gate` 将 A3 最大证据等级固定为 `L2-fixture-or-dry-run` 本地候选；不得把本地 validator/build/E2E 推升为 L4 production acceptance。

## 2026-07-15 — A3 现有构建链初审

- `build_reddit_site_insights.py` 已是正确的 v2 入口：一次生成 versioned Insights + 六态 Reports；CLI 需要 Base、semantic governance、coverage/profile、risk policy、两个 dataset version、as-of 和 output root。
- 现有 semantic projection 只把 promoted/held 集合投影到新 Base，并标记 `raw_review_samples_included=false`；它尚未把原始审计的治理质量、旧 Base、证据兼容统计或本次 A2 ledger receipt 作为强校验依赖。
- `risk_report_contracts.build_contract_bundle()` 对 `--legacy-insights` 仅做四字段存在检查后深拷贝 `headline/signals/reference_dimensions/held_tags`；因此把 20260714 旧 `insights.json` 直接传入会泄漏旧 Base 数字，A3 必须禁止该路径。
- `validate_reddit_site_analytics.py` 当前 CLI 只接 Base/Insights/Reports/version/receipt，未接原始 semantic governance；现有验证只能核对投影内部一致性，不能独立重开并校验原审计 SHA 与 carry-forward 证据。
- A2 Base manifest SHA 已实测为 `de8b504d...d6443`；原始 v1 semantic audit SHA 为 `8747e0f2...6d5e7`，其结论是 10 tags / 100 reviewed / 2 promoted / 8 held，旧 Base 为 `reddit_voc_site_snapshot_20260714_v1`。
- `materialize_reddit_incremental_configs.py` 已支持 Base manifest v2 的 coverage union，可把 coverage/risk/persona 模板重绑到 A2；但当前 config manifest 未绑定最终 A2h r2 receipt，因此 A3 应新增显式 receipt 路径/SHA 门禁，禁止扫描目录或误选 preliminary receipt。
- `build_public_site_projection.py` 和 `build_reddit_current_release.py` 已具备 v2/private-to-public lineage、六态 Reports、Personas、案例 `38 + 12 + approvedDelta` 的既有合同；A3 应复用，不重写案例存量。
- 旧 `build_reddit_insights_snapshot.py` 已给出四个兼容字段的确定性计算规则：promoted tag 当前全量 population、唯一帖子/评论、字典画像参考维度、promoted signals 与 held diagnostics。该算法可以重写为“旧人工治理结论 + A2 当前全量重算”，无需复制旧 221-base payload。
- 当前 v2 builder 的 `legacy_insights=None` 会把 UI 兼容区降级为空；直接传旧文件又会污染新数字。因此 A3 需要一个独立 Base-bound compatibility projection 输出，且 v2 builder 只接受该新 schema/manifest 绑定。
- public projection 对 semantic audit v2 只公开 promoted/held/status，不暴露 raw samples；这与 `governance_projection_no_new_review` 边界一致，可继续复用。

## 2026-07-15 — 语义兼容投影数据形状

- A2 Base posts/comments 均保留 `tagging.matches[tag_id,evidence_keywords,...]`；旧 audit 每个 sample 保留 `audit_id/entity_type/entity_id/evidence_keywords/context_excerpt/review`，可以用 identity + tag assignment 建立可复算兼容集合。
- A2 当前有 1,322 posts、16,581 linked comments；aspect-tag assignment 计数为帖子 377、VOC 评论 3,292。兼容投影必须只把 `include_in_voc_metrics=true` 评论纳入 UI 数字。
- 用“excerpt/created/subreddit 全字节相同”作为兼容判据过严，只得到 27/100 exact，并错误把 promoted 样本降为 6/20；这与已完成的语义发现（83 assignments 仍有相同语义证据、promoted 20/20）冲突。A3 不采用该过严假说；兼容条件应聚焦 identity、tag assignment 与 evidence keyword 集，不把来源分层、stable rank 或正文升级后的截断 excerpt 当成治理结论变化。

## 2026-07-15 — A3 semantic compatibility TDD

- 新增 `build_reddit_semantic_compatibility.py` 与 6 个聚焦测试；首次测试 6/6 GREEN，覆盖当前 Base 重算、promoted fail-closed、held 保持 held、精确 r2 receipt SHA、字典漂移和不可变 0700/0600 输出。
- 第一次真实 A2 CLI 构建在 `candidate_ledger_manifest_invalid` fail closed，未生成候选；这是 fixture 对实际 ledger schema/字段假设不一致，需先读取精确 manifest 字段再修正，禁止原命令盲重试。
- 根因已证实：实际 A2h ledger 是 schema `reddit_voc_candidate_ledger_manifest_v2`、status `a2_identity_closed_with_explicit_coverage_debt`，并非 fixture 假设的 v1/passed；实现和 fixture 已收紧为实际精确合同。
- 修正后 6/6 再次 GREEN，真实 A2 semantic projection 已创建：`semantic-a3/semantic-governance.json`，SHA `0b49aabd...cbb3b`、21,673 bytes；边界仍为 local-only / production unchanged。
- 第一次接入 v2 builder 的合并回归为 25 passed / 1 fail / 1 error：新 projection resolver 漏定义 legacy field 常量；同时旧 manifest normalizer 被新增字段破坏 exact-compat。修复原则是旧 schema 返回结构完全不变，新字段仅限 projection v1。
- 上述两个回归已修复；semantic compatibility + risk report targeted suites 27/27 GREEN，旧 v1 normalizer exact contract 未变，新 projection resolver 只消费内嵌 Base-bound legacy fields 并拒绝同时传裸 `--legacy-insights`。
- 新代码加入 `compatibility_contract` 后，先前 `semantic-a3` artifact 已成为 superseded pre-contract artifact；不可覆盖，后续必须生成新内容身份路径（例如 `semantic-a3b`）并在最终 manifest 中只绑定新 SHA。
- Config identity-gate 首轮回归失败：测试重写 Base 后沿用旧 fixture ledger/receipt，且新外部门禁先于既有 coverage contract 报错。修复要求 fixture 与 Base 同步重建绑定，并恢复 Base 内部合同优先的 fail-fast 顺序；不能通过改测试期望掩盖。
- Config 第二轮回归已收敛到 14/15；唯一失败用例直接改写 manifest 来测试 v1 fusion debt 成功路径，却未同步其 ledger identity。该成功用例需显式重建 gate；所有预期 Base 错误用例继续在外部门禁前 fail fast。
- Config identity-gate suite 最终 15/15 GREEN；materializer 现要求显式 ledger manifest、final receipt 和 expected receipt SHA，并把三者绑定写入 config manifest。
- A3 时间身份采用 A2h r2 `source_cutoff_utc=2026-07-15T08:47:22.379946Z`，与 Base `generated_at_utc=2026-07-15T08:47:22.379946+00:00` 同一时点；报告 as-of 不得擅自改成当前墙钟。

## 2026-07-15 — A3 首次真实派生构建

- 新 semantic projection `semantic-a3b` 已创建，SHA `5997dd8a...2e816`；它 supersede `semantic-a3`，后者不得消费。
- `config-a3` 已创建并绑定 final A2h r2 receipt；coverage/risk/persona config SHAs 分别 `30979530...b29f9` / `7a09d167...b25b` / `d7a93eed...94320`，risk 仍为 draft，未伪造 threshold freeze。
- v2 builder 已从 A2 Base + semantic-a3b + config-a3 生成 6 份本地报告：Insights manifest `c0a68488...d7878`、Reports manifest `b86a8780...b76a5`，status `passed_provisional_risk_threshold`。这只是 builder 成功，analytics independent validator 尚未通过，不能标记 A3 accepted。
- Analytics validator 当前硬编码 Base manifest v1、无 semantic/ledger 输入，receipt 带 `datetime.now()` 且覆盖写；A3 必须改为 v1/v2 精确分支、projection/source audit/r2 receipt 独立重开复算、确定性不可变 receipt。既有 fixture CLI 必须继续兼容，不可把新参数无条件强加给非-projection v1 测试。
- Validator 增强代码已完成首轮并通过 `py_compile`；首次 `pytest` 命令因系统 PATH 无 pytest（exit 127）未运行测试。后续固定使用 Codex workspace Python `/Users/pray/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3`，不安装依赖、不把 exit 127 计为测试结论。
- Codex workspace Python 同样没有 pytest；仓库存在 `.venv/bin/python` 但未报告 pytest，系统已有 `/Users/pray/.local/bin/uv`。下一步先用 `uv` offline/cache 模式查找既有 pytest，避免联网安装和依赖变更。
- `UV_OFFLINE=1 uv run --with pytest` 命中本地缓存，analytics validator tests 8/8 GREEN；无依赖文件变化、无联网安装。
- 真实 A2 analytics independent validation 已通过并创建确定性 receipt：Base `de8b504d...d6443`、Insights `c0a68488...d7878`、Reports `b86a8780...b76a5`、semantic projection `5997dd8a...2e816`、source audit `8747e0f2...6d5e7`、ledger `bcc1ac74...f87639`、r2 `5700b8e4...bc913`；83 compatible / 20 promoted compatible，42 risk themes、17 Insights product scopes、6 reports。
- 当前 receipt 是 analytics GREEN，但竞品多维扩展、Personas source-stratum、public projection 和 final reconciliation 尚未完成；Plan A A3 仍 in progress。

## 2026-07-15 — 竞品同样本合同审计

- 当前 `_competitor_context()` 只对 `competitor_sentence_bound` 按品牌去重并输出 post/comment negative share 与空的 product_scope_ids；没有 observed count、主题、痛点、社区、跨期比较或趋势。
- A2 没有受治理的竞品产品 taxonomy，不能套用 Momcozy product resolver。新合同必须显式 `product_taxonomy.status=unavailable_no_competitor_taxonomy`，并保持 `comparison_is_not_market_share_sov_penetration_or_sales`。
- Insights 与 Reports 已复用同一 `CompetitorContext` 类型和现有 panel；Plan A 先扩数据合同与 validator，Plan B 可在原卡片内适配显示，不重排页面故事线。
- Reports builder 已同时持有 current/previous/YoY window entities 与 coverage，适合生成竞品 PoP/YoY；rolling-30 command center 不具备同口径 previous/YoY window，可复用 daily report 比较状态或只输出当前多维概况，不能混用不同窗口冒充比较。
- `_Entity` 已有 `topic/pain_points/subreddit/tag_ids/sentiment`，无需新 NLP；竞品主题、痛点、社区与风险标签可从同一受控实体集合确定性聚合。
- 现有 `_period_comparison()` 固定过滤 Momcozy，不能直接复用给竞品；需要一个同 coverage gate、但对已按品牌过滤实体计算的 competitor comparison helper，避免把全体或 Momcozy baseline 错配给单一竞品。
- 竞品日/周/月合同采用 current + previous-period + YoY 两组 post/comment 指标，并用 previous-period 比较形成 trend gate；command center rolling-30 只提供当前多维概况，不制造不一致窗口的趋势。
- 竞品合同首轮 `py_compile` 在带额外参数的 generator expression 处失败，错误为 `Generator expression must be parenthesized`；未进入测试、未生成候选。仅修复括号后再跑同一测试。
- 语法修复后聚焦测试仅在“整体 trend=true”期望失败；fixture 无竞品评论，帖子比较可用但评论负面占比无分母，整体 direction gate 返回 false 是正确 fail-closed 行为。修正测试为整体 false + 帖子 observed-count direction true，不放宽生产合同。

## 2026-07-15 — A3c 最终闭包并行收口

- 主线程恢复时确认两条独立收口任务仍在运行：公开投影独立 validator/receipt，以及 candidate-data reconciliation 外层 manifest/receipt；未提前生成最终闭包，也未触发任何生产写入。
- 当前工作区仍为无提交的 `codex/momcozy-reddit-backfill-20260711`，且存在大量用户既有 untracked 文件；本轮继续只做窄范围新增/修改，不 stage、commit、清理或覆盖无关文件。
- 独立对抗审计对 A3c 业务派生未发现新 P0 数据错误；剩余硬门禁仍是 public 独立 receipt 与 final reconciliation。证据等级上限保持本地 L2，`production unchanged`。
- candidate closure builder 已采用薄层收口：只消费已构建且独立验证的 A2/A3 artifacts，不重建 Base/Analytics/Personas/Public；固定 data-build code allowlist 明确包含 public validator 与 closure validator，React/package-lock 冻结仍留给 Plan C。
- closure 与 public validator 正在对齐 receipt schema；在 public receipt 字段和 inventory identity 未确定前，不猜测字段、不生成真实最终闭包。
- 书面规格要求在 A2/A3 data-build 实现稳定后、正式闭包前单独冻结 `data_build_code_freeze`；当前仓库没有独立 code-freeze builder，closure 只验证固定 14 文件 allowlist、bytes/SHA、显式 `code_cutoff_utc` 和副作用边界。应在两支收口代码稳定后用 canonical manifest 冻结一次，不能提前冻结仍在改动的 validator。
- 主线程重新逐文件校验 A3c 输入身份时，除两个路径名称误记外，已知 SHA 全部与磁盘一致。正确 config manifest 路径是 `config-a3c/manifest.json`（`70ded635...75029`），正确 cases index 路径是 `public/data/cases/case-index.v1.json`（`a1da92f...55cd68`）；后续 closure CLI 必须使用这两个实体路径，不能沿用误记名称。
- `public-projection-a3c` 的实际 21 文件全部位于 `data/reddit-voc/...` 深层树；顶层 `find -maxdepth 3` 会错误显示为空。公开 validator 必须递归盘点完整树，案例 2 文件则是独立绑定源，不应误算进这 21 文件 inventory。
- 两个 closure 脚本与 public validator 均已落盘，主线程在其测试完成前先做只读 AST parse，3/3 语法可解析；这不是功能验收。公开 validator 已主动把 `public_root` 对齐为 outer root，并把 inventory 算法收敛到既有 LF `path\tbytes\tsha256\n` 合同，避免出现第二个不兼容的 inventory identity。
- 主线程复跑新增 public-builder/public-validator/closure suites 为 **21/21 GREEN**，targeted Pyright 对三个新 production scripts 为 0/0/0。一次直接调用 `pytest` console script 因 root 未进 `sys.path` 在 collection 阶段失败，改用项目一致的 `python -m pytest` 后 closure 6/6 GREEN；前者不是代码失败，后续命令固定使用 module invocation。
- Cases manifest 使用 camelCase 合同：seed content SHA `372fa672...a48a7`、legacy-unverified `9d09b109...91de2`、approved-delta 空数组 canonical SHA `4f53cda1...2b945`；public validator CLI 对这三项和 manifest/index SHA 均要求显式 expected identity。
- 最终 public validator 在首次 receipt 创建后又新增 mandatory expected inventory gate；主线程用最终脚本和显式 `d460f8b8...a16ea` 重新运行，得到 `receipt_write_status=no_change`，因此旧写入 bytes 与最终代码产出完全一致。最终 public receipt SHA 为 `045a8440...cc6f7`，目录/文件权限 0700/0600。
- data-build code freeze 在所有收口代码稳定后创建，固定 15 个 Plan A data-build files（不是先前误记的14个）、`code_cutoff_utc=2026-07-15T11:30:28Z`、全部副作用 false；manifest SHA `ac55736c...6c14`，0700/0600。React/package lock 仍未纳入，留给 Plan C。
- 主线程对 closure 做书面规格二审时发现 P0：计划第65-83行要求最终 candidate root 至少物理包含 source-freeze manifest、四本明细账、reconciliation、outer manifest、receipt；当前薄层只允许后三项，虽有外层 SHA 绑定但不满足“至少包括”的已确认规格。已暂停真实 closure 生成，要求 builder 原字节复制前五项、manifest/validator exact 绑定并补 tamper/collision tests。
- 因 closure 两个 production scripts 将为上述 P0 修改，已创建的 `code-freeze-a3c` 立即标记 **superseded pre-fix freeze**，不得消费；修复稳定后必须用新 code cutoff 和新 SHA 生成 `code-freeze-a3d`，从而改变 candidate canonical identity。
- P0 已按书面规格闭合：builder 产出7个必需文件（source freeze + 四账 + reconciliation + outer manifest），validator 成功后写第8个 receipt；copied inputs 原字节、0600、无 symlink，outer files contracts 绑定 bytes/SHA/rows。主线程复跑 public+closure focused suites **23/23 GREEN**、三 production scripts Pyright 0/0/0。
- 新 final code freeze 为 `code-freeze-a3d/data-build-code-freeze.json`，code cutoff `2026-07-15T11:34:26Z`，manifest SHA `c87754e3...5a85c`，0700/0600；它 supersede `code-freeze-a3c`，后续只允许消费 a3d。
- 第一次真实 closure build 按预期 fail closed 为 `production_baseline_file_missing`，未生成候选：source-freeze 内的 baseline 镜像只有 manifest/posts/comments/quarantine，缺少其 manifest 声明的 aggregates 与 tag-dictionary，不能作为完整 Base root。完整、同 manifest SHA `a900e6ce...c3abd` 的只读 baseline 实体位于 `tmp/reddit-voc-incremental-candidate-20260715/base/...`，含5个数据文件；production receipt datasets 也绑定该 dataset version。下一次只改用这个完整 exact-SHA root，不改任何 identity SHA。
- 使用完整 exact-SHA baseline 后，真实 local closure 创建成功：candidate input `a61899f3...c9fab`，manifest SHA `046bbb1e...807d2`，reconciliation SHA `fc4dc149...5ec6f`。构建时7个必需文件均0600；manifest记录 source freeze、四账和reconciliation的 bytes/SHA/rows，`unaccounted_total=0`。
- 独立 closure validator 已从外部 Base/ledger/analytics/personas/public/cases/config/receipts 重开验证并写入第8个文件，receipt SHA `2f5fe7f5...48500`、status passed、目录0700/文件0600；重算 counts 为 source-occurrence5928、post1573、comment18746、coverage4116、release net-new posts0/comments3605、public21 files/30,102,047 bytes、cases38/12/0、unaccounted0。证据等级明确为 `L2_local_independent_validation`。
- Closure validator 同输入复跑为 `no_change`，builder 在第8个 receipt 已存在后复跑也为 `no_change`；manifest/reconciliation/receipt SHA 均不变，证明幂等且没有重写已验候选。
- 主线程完整相关 Python 回归 **173 passed + 7 subtests**；前端全量 Vitest **136/136**。`npm run lint` exit 0，仍只有 `src/components/reports/shared.tsx` 的5条既有 Fast Refresh warning，本轮未扩大也未把 warning 冒充清零。
- 最终独立审计对首个 closure 的8/8 inventory、0700/0600、零 symlink、5个原字节copies、candidate四哈希/root/manifest/recon/receipt、public inventory、四账唯一键/状态守恒/unaccounted0均通过，未发现数据 P0。
- 审计发现一个必须补强的 P1：closure validator 只核验 code-freeze manifest 的15项格式，没有在 receipt 路径内重哈希当前仓库代码。审计外部重哈希15/15精确匹配，故不否定旧候选当时的L2数据事实，但证明不自包含。已决定让 builder+validator 增加显式 `--code-root` 和15文件 bytes/SHA/symlink/special门禁；因此 `code-freeze-a3d` 与 candidate `a61899f3...c9fab` 将成为 superseded pre-code-rehash artifacts，不能作为最终消费身份。
- P1 已关闭：builder 与独立 validator 均新增必填 `--code-root`，对固定15文件逐层拒绝 traversal/root-or-parent symlink/special，并重算 bytes/SHA。新增 tamper 双门禁；主线程复跑 focused suites **24/24 GREEN**、Pyright 0/0/0。
- 最终 code freeze 升级为 a3e：SHA `8de68f3b...8276e`、code cutoff `2026-07-15T11:43:18Z`。最终 candidate identity 为 `70a917e5...4ac1e`，manifest `c18d313a...1cdfb7`，reconciliation `347fc37a...f957b7`，independent receipt `e2958d7d...bc9f80`；builder/validator 重跑均 `no_change`。8文件全0600，根0700，业务 counts 与前一有效数据候选相同；旧 a618 仅保留历史证据、禁止消费。
- code-root 补强后的最终相关 Python 回归为 **174 passed + 7 subtests**。Base canonical totals 仍为 1,322 posts、16,591 stored comments、16,581 linked comments、10 quarantined；语义边界仍明确 market share/ROI/response time unsupported，竞品只作同样本观察对比。
- 最终 a3e 独立 delta 审计已关闭为 **P0=0/P1=0**：8文件/modes/symlink、5个原字节copies、candidate identity、canonical documents、依赖图、15/15 current code rehash、错误 code root fail-closed、old→new预期差异及10份关联证据副作用扫描全部通过。
- 按 `project-state-doc-sync` 同步完成 `.kiro/plan/task_plan.md`、`.kiro/plan/progress.md`、`.codex/context-pack.md` 与 Plan A/B implementation plan 状态：Plan A=`completed_local_candidate`，Plan B=`ready_for_implementation`，Plan C仍pending；所有文档保持 production unchanged 与 open1179/pending18 覆盖债务，不把本地L2写成生产验收。
- 收尾重新读取最终5个关键实体 SHA，全部与状态文档一致；final closure 零 symlink，`git diff --check` exit0。没有 stage/commit、生产写入、部署、Provider、数据库、调度或 live send。

## 2026-07-15 — Plan B UI 治理开始

- 已从 final a3e Plan A closure 恢复断点；Plan B 状态为 `ready_for_implementation`，唯一允许范围是本地 UI source 变更、测试和临时编译证明，Plan C 才能生成 promotable dist/E2E receipt。
- 根仓库仍为无提交、全量 untracked 工作区；根下未发现实体 `AGENTS.md`，继续按用户消息内的工作契约执行，不 stage/commit、不清理或覆盖无关文件。
- Plan B 固定方向是不重排页面、不重做导航、不引入依赖：新增 GovernanceStatusBadge/DataScopeBar/ReleaseEvidenceCard；只有 `failed` 可用 error icon，业务 P0/P1 与 partial/provisional/unavailable 必须脱离系统错误三角语义。
- artifact build 与 site deployment 必须双对象分离；候选 dist 不得预写“已部署/已验收”。当前证据上限仍为本地 L2，`production unchanged`。
- 第一次组合命令因 `rg --files -g AGENTS.md` 在无匹配时 exit1，导致后续 `cat` 未执行；已改为独立读取 Plan B，不重复原命令。该失败不是代码或数据失败。
- 当前 `current-release.json` schema v1 只绑定 served release/datasets/cases，没有 artifact/deployment/governance 五类新字段；Plan B 必须保持 v1 严格解析兼容，通过显式 adapter 构造 UI 状态，不能改静态数据或从 build flags 推断生产部署失败。
- 当前 release 可可靠证明 `served_release_id` 与四个 public manifest SHA；没有独立 deployment acceptance source，因此 site promotion/acceptance 状态只能是 `unavailable`。artifact build 可表达 manifest-bound verified evidence，二者必须分别展示。
- A3c Insights/Reports manifests 的业务状态是 `passed_provisional_risk_threshold`，且明确 `trend_claim_supported=false`、market share/ROI unsupported；UI 只能呈现 provisional/仅观察与能力未冻结，不得使用系统 error/warning 三角。
- `SnapshotBoundaryPanel` 当前仅在 dashboard 与 analytics 两处重复，正是 DataScopeBar 收拢点。Dashboard quarantine、Analytics rule-tag、Insights P0/P1/negative metrics、Reports coverage/attention/negative cards 与 cases legacy badge 是主要页面替换面。
- 一次 `rg governance_status` 误扫到巨型 public JSON，输出被截断；后续 inventory 限制到 `src/**/*.{ts,tsx}` 和指定 manifest keys，禁止扫描/修改 Reddit 正文评论自然语言。

## 2026-07-15 — Plan B 规格缺口与失败边界

- Plan A 最终 A3c public projection 与 closure 均未输出统一 `governance_status`，也没有 `artifact_build_state`、`site_deployment_state`、`data_scope`、`comparison_scope`、`tag_maturity` 五个 UI 可消费字段；Plan B 必须拥有一个只基于结构化字段、严格枚举且不解析 `reason` 文案的适配契约，并在 source receipt 标注来源。
- `current-release.json` 可证明当前服务身份与四个版本化数据绑定，但没有独立部署验收来源，因此站点部署/生产提升/验收状态必须显示为 `unavailable`，不能由离线 receipt 反推。
- `ErrorBoundary` fallback 使用 `react-router-dom` 的 `Link`；若 `BrowserRouter` 位于错误边界子树内，渲染异常会把 Router 一并替换，fallback 可能因缺失 Router context 二次失败。需先补 RED test，再调整根组件顺序或改用普通链接。
- `SnapshotInsights` 的 C 模块当前将离线生成边界写成固定成功色块；Plan B 应替换为可核验 release evidence 组件，分别展示 served release、artifact build 与 site deployment，不把 `deploy=false` 解释成“站点未部署”。
- `validateSnapshotCore` 与 `validateReportsSnapshot` 都已经接收并严格校验 `CurrentRelease`，但返回对象没有保留 release；为避免页面二次 fetch，Plan B 可把同一已验证 release 显式附到 `RedditSnapshotCore` 和 `RedditReportsSnapshot`，现有 Insights 已经通过 `core` 间接持有。
- `ProductionFeatureGate` 当前用 warning 色表达“真实数据未接入”；这是能力状态而非系统故障，应改为 `unavailable` 治理徽章，并保留 `provider_call=false/live_send=false` 边界。
- 案例卡的 `legacy_unverified` 当前使用 `CircleAlert` + warning 色；应改为历史/待核验语义图标。`approved_delta` 的成功徽章是有显式核验时间的结构化状态，可保留 verified 语义。
- 最终 A3c Base public manifest 已升级到 `reddit_voc_site_snapshot_manifest_v2`，并包含 `structural_coverage_grade=post_only`；当前前端类型/validator 仍只接受 v1 与 `full|partial`。Plan B 需要增加精确 v1/v2 分支兼容，作为 Plan C 切换最终真实数据的前置合同，不能放宽为任意字符串。
- 页面测试已通过统一的 `validateSnapshotCore` / `validateReportsSnapshot` 构造真实 fixture；在返回对象附加已验证 release 可最小化测试改动。现有动态 fixture 多采用 spread，不会丢失新字段。
- `ProductionRoutes.test.tsx` 当前直接断言 warning 文案；Plan B 要先把期望改为 `unavailable` 状态并确认 RED，再实现组件。案例测试也应新增“不出现系统 error icon/红点”的 DOM 断言。
- Plan B 书面 failure matrix 明确：Base/Reports/Insights/release fetch/hash 失败停止对应整页，Personas 失败只停画像，Cases 失败回退 38 seed-only，单头像失败只回退该卡；临时 build 只能作为 non-promotable preview。
- A3c Base v2 结构化事实：1,322 posts、16,581 linked comments、10 quarantined，覆盖等级 859 full / 462 partial / 1 post_only；tagging 仍为 `labels_provisional=true`、`semantic_validation_run=false`，但包含受治理 product entity resolver。UI scope 可由这些结构化字段严格判定，不需解析自然语言原因。
- A3c Insights/Reports 的 `status=passed_provisional_risk_threshold`，Insights 2 promoted / 8 held，Reports `trend_claim_supported=false`；因此 tag maturity 与风险门禁应为 provisional，比较能力按各 report 的 typed `comparison_status` 呈现，而非全局宣称失败。
- 状态 inventory 明确真实失败 allowlist：全页 `SnapshotErrorPage`、全局 `ErrorBoundary`、画像模块错误、搜索评论错误、案例增量完整性错误和用户触发导出错误；这些节点必须保留错误图标并统一增加 `data-ui-severity="error"`。其余 coverage/provisional/unavailable/业务风险不得使用系统错误 glyph。
- 案例页另有无条件消息红点；消息能力未启用时必须删除。索引/hash 失败是“增量层 failed”，但允许影响范围仅为拒绝增量并保留 38 条 seed-only。
- 五个受管数据页各只允许一个 `DataScopeBar`；cases 使用 catalog status，Home/Features/HowItWorks/FAQ 和三个 gated 页面不得强塞 DataScopeBar。页面级替换必须保留 6 份报告、产品三层、竞品同样本、画像合成头像、38+12+delta、采集后台链接与覆盖债务。
- 严格状态适配未知枚举必须抛错；`reason_codes` 只用于解释，不参与状态推断。报告 mapping 固定为 complete→verified，partial/observed_records_present_but_collection_coverage_unverified→provisional，coverage_gap/coverage_missing/unavailable→unavailable；comparison comparable→verified、provisional_observed_sample→provisional、unavailable→unavailable。
- Dashboard/Analytics 的旧 `SnapshotBoundaryPanel` 是唯一两个复用点；替换时必须删除两处 import/render，旧组件不再进入活动路由。Dashboard 的负面情感红色属于内容语义可保留，隔离评论改中性图标。
- Search 当前在页级、列表与详情重复“待语义复核”；页级 DataScopeBar 统一表达 maturity 后，tag chip 仍保留规则来源，但改为中性/primary。评论加载错误是局部真失败，须加 error severity。
- 现有 `SnapshotPages.test.tsx` 仍断言旧 boundary 的 `production unchanged` 和“规则标签 · 待语义复核”；页面迁移后测试应改为五页各恰好一个 DataScopeBar、正常态无 error severity，同时在 ReleaseEvidenceCard 单独验证 artifact/deployment 边界。
- 页面治理 RED 已建立：`SnapshotPages.test.tsx` 聚焦运行 13 tests 中五个受管路由均因 DataScopeBar 数量为 0 按预期失败。另有一个 `隔离评论` 精确单元素断言是测试迁移自身造成的非目标失败，应立即放宽为“至少一个”，不把测试错误计为产品 RED。
- `ErrorBoundary` 独立 RED 已复现无 Router context 时 fallback 二次异常；最小修复已由子任务完成为普通 `<a href="/">`，错误根节点带 `data-ui-severity="error"`，聚焦测试 1/1 GREEN，待主线程复核。
- Reports 页面当前将窗口覆盖 notice、业务负面/痛点、风险 evidence gate 和离线 build receipt 混在同一 warning/error视觉中；治理迁移应把唯一 DataScopeBar 放在报告页选择器后，并由选中 descriptor/report 的 typed coverage/comparison 实时派生，而不是每个内部 section 重复状态条。
- 真失败属性首批已落到 `SnapshotErrorPage`、Persona 模块错误、Search 评论错误和 Cases 增量索引错误；CaseGallery 的无条件消息红点已删除。seed-only 仍保留 role=status 和 38 条存量，但视觉/属性明确为增量层 error scope。
- Reports 视觉子任务确认：`RealReportView.tsx` 的 coverage gap、关注项、负面实体、痛点集中仍使用系统警示三角；`RiskThemePanel.tsx` 标题仍使用红色 `ShieldAlert`，证据不足仍使用 `AlertTriangle`。这些属于业务/成熟度语义而非运行失败，应替换为中性业务图标，同时保留现有文字、等级与 reason code。
- `RiskThemePanel` 现有 P0/P1/P2/P3/insufficient 业务配色可以保留，但所有优先级徽章都缺少 `data-business-priority`；本批只补业务优先级属性，不增加 `data-ui-severity`。
- Reports 视觉源断言先按预期 RED：`RealReportView` 仍渲染 `AlertTriangle`，`RiskThemePanel` 仍渲染 `ShieldAlert`/`AlertTriangle`，且缺少 `data-business-priority`。随后仅在两个报告组件内做最小替换：coverage/provisional 改为 Eye/Clock3，关注与痛点改为 Target/Activity，风险主题标题改为 Target，证据不足改为 Clock3；业务文字、reason 与优先级颜色均保留。
- 同一 source assertion 在实现后 GREEN，且确认两个报告组件都没有 `data-ui-severity`。现有直接关联测试只有 `reports.test.ts`（数据合同）与 `SnapshotPages.test.tsx`（页面集成）；后者含主线正在建立的 DataScopeBar RED，不适合作为本子任务独立全绿门禁，先用 typecheck + 数据报告 suite 验证。
- Reports 数据合同 suite 7/7 GREEN。全量 TypeScript project check 当前被共享主线并发修改的 `service.test.ts:133` 阻断：测试故意构造的 `unknown_grade` 直接断言为 `SnapshotPost`，与现有 `full|partial` 类型不兼容；失败不在本子任务两个文件内，未越界修补，交由主线合并后统一复跑。
- 两个报告文件的定向 oxlint exit 0。页面集成测试中与本子任务最接近的是“renders V2 daily, weekly, monthly report booklets...”，但该共享测试文件当前同时承载主线 DataScopeBar RED；本子任务不改断言，主线完成治理条后再统一复跑。
- 定向运行报告页面集成用例成功避开其余 DataScopeBar RED：1 passed / 12 skipped，日报→周报→归档周报→归档月报、Top 6 竞品与离线 receipt 边界仍保持。报告视觉替换未破坏现有交互与业务文案。
- Cases legacy 12 条卡片已从 `CircleAlert` warning 改为 `History` + neutral unavailable，单头像失败已改为 neutral unavailable synthetic placeholder，stale catalog 改为 provisional；CaseGallery + persona 聚焦回归 6/6 GREEN。
- 营销页纯装饰 warning/error 已最小去除：Features 的装饰 warning 点/标签改中性，HowItWorks 的 Insights/Messages/Cases 与业务价值图标改为 primary/neutral；Navbar 在消息功能未启用时不再读取/渲染未读红点。MarketingClaims 4/4 GREEN，聚焦 oxlint 无输出。
- Insights v2 的 P0/P1 headline 目前没有可挂载业务优先级属性；`SnapshotMetricCard` 可加可选 `businessPriority` prop，并只输出 `data-business-priority`，不改变视觉/API默认。held/failure-check 是未晋级业务诊断，不是系统错误，需改 neutral/provisional。
- 治理共用组件已完成独立 RED→GREEN：严格四态、DataScopeBar 三维、ReleaseEvidenceCard artifact/deployment 分离，聚焦 3/3 GREEN；全量当时 140 pass / 12 fail，剩余为页面接线与 Base v2 RED，不能提前宣称全绿。
- 组件 API 固定为 `DataScopeBar({contract})` 与 `ReleaseEvidenceCard({contract})`，完整 `UiGovernanceContract` 使用五个 snake_case 字段。下一步需要补严格 typed factory，把已验证 snapshot/report/insights 的结构化枚举转换成该合同，未知枚举必须抛错。
- Dashboard/Analytics/Search/Insights 首轮业务语义去警报化已完成：隔离评论中性 Archive；规则提取改 neutral/primary；Search 页级重复 maturity 提示删除且 tag 可追溯保留；Insights hero/P0-P1 改中性 Shield，并为 KPI 增加 `data-business-priority=P0-P1`，held 诊断改 provisional。TypeScript、两个关键页面 DOM 用例和定向 oxlint均通过。
- Reports 独立语义批次已完成：coverage/关注/痛点/负面/insufficient/标题均换为 Eye/Clock/Target/Activity 等业务图标，P0–P3/insufficient 徽章有 `data-business-priority` 且无 error severity；reports 7/7、报告页面用例 1/1 GREEN。
- 三个受控功能路由 RED 已建立：ProductionRoutes 3/3 均因尚无“功能状态 · 未启用”的 unavailable 徽章而失败；下一步只替换旧 warning pill，不加 DataScopeBar、不发请求。
- 三个受控功能路由已 GREEN：旧 warning pill 改为 `GovernanceStatusBadge(unavailable)`，页面无 DataScopeBar、无 error severity、无 fetch，ProductionRoutes 3/3 与定向 oxlint 通过。
- Base v2 独立批次已 RED→GREEN：v1/v2 exact schema、post_only、event-time、coverage mapping、product ledger 哈希与三层守恒全部 fail-closed；service 聚焦 16/16、tsc、lint 通过，静态发布数据未改。
- Plan B typed governance factory 已新增：Base/Insights/Reports 分别从已验证 manifest、typed coverage/comparison/status 构造五字段合同；current-release 只用于 served identity 与 manifest SHA evidence，promotion/acceptance 在无独立部署源时保持 unavailable。未知状态通过 `GovernanceContractError` fail closed，不解析 reason 文案。
- Governance factory 映射与 unknown-enum fail-closed 测试已补齐，组件/mapper 聚焦 5/5、tsc、定向 oxlint 通过。
- `CaseCatalogMeta` 已有严格 `verified_index|seed_only` 与 `fresh|stale|unknown`，足以直接渲染 cases catalog badge：verified+fresh→verified、verified+stale/unknown→provisional、seed_only→failed；无需 DataScopeBar 或 reason 文本推断。
- Cases catalog 状态 RED 已建立：健康与 seed-only 两用例均因缺少 catalog badge 失败，现有 38 条 fallback 与卡片内容仍正常，失败范围符合预期。
- Cases catalog 已 GREEN：页面从结构化 meta 映射 `verified/provisional/failed` badge，健康态无 error severity/无 DataScopeBar，seed-only badge 与增量错误条均为 scoped error 且保留 38 seed；CaseGallery 2/2、定向 oxlint 通过。
- 失败范围 DOM 合同继续补强：Persona 整模块失败必须带 error severity；单头像资源/decode 仅为 unavailable placeholder 且不产生系统错误；营销四页明确禁止 DataScopeBar。等待五数据页接线后统一复跑。
- Dashboard/Analytics/Search 接线已完成并复核：三页各唯一 DataScopeBar，Dashboard 另有一个 ReleaseEvidenceCard，两个旧 SnapshotBoundaryPanel 已退出活动路由，Search 评论局部 error 保持。子任务定向页面 5/5 GREEN；Persona/Marketing 新断言 8/8 GREEN。
- 一次复核命令在 UI workdir 下仍使用仓库相对前缀，两个 `sed` 报 no such file；同一命令末尾 `tsc --noEmit` exit 0。该路径误用不是代码失败，后续在 UI workdir 使用 `src/...`。
## 2026-07-15 — Plan B 断点恢复与页面接线收敛

- 重新读取 `task_plan.md` / `progress.md` 后确认本轮唯一授权仍是 Plan B 本地 UI 治理；Plan C、生产部署、远端写入、Provider、数据库、采集器与调度均未获授权，边界保持 `production unchanged`。
- Plan B 书面规格再次确认：五个数据页各恰好一个 `DataScopeBar`；Insights/Reports 使用 `ReleaseEvidenceCard` 分离 artifact build 与 site deployment；最终只允许写源码 manifest/validation receipt，临时 build 不得作为 promotable dist。
- Reports 接线已完成但旧页面测试仍要求已删除的重复覆盖通知/固定 receipt；这是预期的测试合同迁移，下一步依据新治理组件更新断言，不恢复旧 UI。
- Insights 接线已完成：v1/v2 路径各一个 scope bar，C 区块使用 release evidence，未冻结高优先级数值改为 unavailable，业务优先级与系统错误语义分离。
- 13 路由 source contract 已实现：production path 精确集合与 wildcard 分离，三个 gated route 保留显式 metadata，未新增登录或改变路由顺序；定向 RED→GREEN 为 6/6。
- 当前页面测试源码仍固定断言 `1,299/12,837/12,688`，而 Plan A 最终闭环记录为 `1,322/16,591/16,581`；在更新 UI 断言前必须先核对 `ref/UI/public` 是否已切到最终 Plan A public projection，避免用旧 fixture 证明“最新合并数据”。
- 核验结果：`ref/UI/public/data/reddit-voc/current-release.json` 当前确为旧 `reddit_voc_release_20260715_v2`，Base manifest 是 v1 且为 1,299 posts / 12,837 linked comments。Plan A 最终公开投影位于 `tmp/reddit-voc-plan-a1-20260715/public-projection-a3c/`，21 文件 / 30,102,047 bytes，独立 receipt SHA `045a8440...cc6f7`，Base v2 为 1,322 / 16,591 / 16,581 / 10。
- Plan A 的 21 文件投影不包含 `current-release.json`；现有 `build_reddit_current_release.py` 能严格重开四个 private lineage manifest、四个 public manifests 与案例 38/12/0，再生成不可变 v1 pointer。Plan B 数据激活应复制这 21 个已验公开文件、保留旧版本目录与案例，并用该既有生成器创建新的本地 pointer；不能手写或把旧 pointer 继续当最终数据。
- 本地数据激活已执行：21 个 Plan A public files 以原字节复制到 UI public tree，目标权限规范化为目录 0755 / 文件 0644，旧 v2 版本目录和案例树均保留；checksum dry-run 无差异。严格 pointer generator 创建 `reddit_voc_release_20260715_70a917e5bdf0`，pointer SHA `4a85a420...b6c30`，生成 receipt 明确 `provider_call=false / database_write=false / deploy=false / live_send=false`。
- 激活后结构化只读核验精确得到 Base v2 `1,322 posts / 16,591 stored / 16,581 linked / 10 quarantine`，其中 16,417 comments 进入 VOC metrics；Insights 为 42 risk themes / 46 competitors，当前日报仍为8个 Momcozy帖子、4个风险主题、15个竞品，coverage partial、comparison unavailable。
- 激活后的 SnapshotPages 首轮为 10/13：三个 RED 均是旧 fixture 文案/数量断言（1,299/12,837/12,688、8/37、已删除的重复报告覆盖提示），不是运行时加载失败；五个数据页各一个 scope bar 且正常态无 `data-ui-severity=error` 已通过。全量 `tsc` 的3个错误来自新 failure tests 的强制 cast/optional 写法，需按 TypeScript 6 严格类型修正，不放宽生产类型。
- 一次用于读取 aggregates headline 的 `functions.exec` JavaScript 编排字符串发生 `Unexpected token '/'`，未执行 shell；改用 heredoc 后只读成功。这不是项目代码或数据失败。
- SnapshotPages 在第三次同套件验证仍有2条旧断言迁移问题后，按三次门禁暂停继续叠 patch，并复核数据流与组件 DOM：`ReleaseEvidenceCard` 合理地在 served identity 与展开的 artifact identity 各显示一次 release ID；high-priority unavailable 已由单一 Governance badge 承载完整可访问名称；archive monthly 的结构化状态是 `provisional_observed_sample`，旧顶层提示已按 Plan B 删除。后续测试只绑定这些结构化/可访问合同，不恢复重复文案。
- TypeScript 严格构建与定向 oxlint 在上述页面断言迁移中均为 exit 0；当前未发现生产类型或 lint 新问题。
- 页面合同迁移最终 GREEN：SnapshotPages 18/18；结合 Cases 2/2 与 Personas 4/4 为 24/24。新增失败注入证明 Base 失败仅停止 dashboard/analytics/search 对应整页，Insights/Reports 各自整页停止且无 stale 指标；Personas 继续只停止模块，Cases 继续只拒绝增量并保留 seed-only，头像 resource/decode 继续中性 placeholder。
- 同批 `tsc -b` 与定向 oxlint exit 0；真实错误节点恰好使用 `data-ui-severity=error`，失败页不渲染 `DataScopeBar`，正常五数据页仍各一个 bar。
- 最新数据激活后的首轮全量回归为 157 passed / 5 failed；5项全部是旧 release exact-fixture 数字（Base 1,299→1,322、VOC 12,688→16,417、risk themes 37→42、persona assignments 233→323、六态报告评论量）。没有生产代码异常。更新为 Plan A 最终公开投影的精确事实后，三个受影响 suite 32/32 GREEN，TypeScript 与 oxlint 仍通过。
- 一次六态报告只读脚本误用 index 的 `file` 键而非实际 `path` 键，导致读取 `public/.../undefined`；未写文件，且精确六态数量已由真实 validator/test failure diff 与随后 GREEN 复核。该错误不是网站运行失败。
- failure audit 的非阻断加强项已闭合：新增 current-release 非法 JSON fail-closed 且只发1次 pointer 请求；新增 Insights public manifest bytes tamper 在解析前以 SHA mismatch 停止；Base 三页逐页断言代表性 stale 指标消失；Cases UI 使用完整38条 seed 并验证首屏12条/4页、无 legacy/delta。
- 语义独立审计发现并修复1个 P1：高优先级阈值为 `unavailable_unfrozen_evidence_threshold` 且 value=null 时，Insights 原先仍无条件输出 `data-business-priority=P0-P1`。现在 unavailable 时两个 priority 属性均不存在；仅 status=governed 且有值时在 hero/metric 两处输出。双态测试与加强后的四套件 43/43 GREEN。
- 上述新 governed fixture 首次 TypeScript 严格检查因漏带 `included_priorities` / `unit` 两个原字段而失败；改为展开原结构后 `tsc -b` exit 0，未放宽类型。
- 语义审计第二轮 P1/P2 已闭合：Insights 与 Reports 的 `provisional_observed_sample` 从 `text-status-warning` 改为中性治理主色 `text-primary`；真实 ExportButton 失败按钮新增 `data-ui-severity=error`。DOM 回归验证所有“已观察样本”不再使用 warning token，导出异常保留真实错误语义。
- 对应定向测试 20/20 GREEN，TypeScript 与定向 oxlint exit 0；没有改变负面业务指标本身的颜色、风险优先级或真实错误的红色语义。
## 2026-07-15 — Plan B source-freeze breakpoint audit

- Independent data-integrity review passed the activated Plan A projection: final four data directories are exactly 21 files / 30,102,047 bytes, with zero path, byte, SHA, manifest, lineage, identity-set, permission, or symlink drift. Base remains 1,322 posts, 16,591 stored comments, 16,581 linked comments, 10 quarantine; cases remain 38/12/0. Evidence is local L2 and `production unchanged`.
- The checked-in-like `dist/` is stale (`reddit_voc_release_20260715_v2`) and must not be promoted. Only `public/` and the explicitly non-promotable preview contain the final A3c projection.
- `public/data/reddit-voc` intentionally retains several superseded v1/v2/A2 directories in addition to the four current A3c directories. A normal Vite build therefore copies historical datasets too. Plan B source evidence must inventory this fact explicitly; Plan C must decide the final-dist allowlist from `current-release.json` instead of treating every historical public directory as current data.
- The UI root also contains `.env.local`, `.DS_Store`, screenshots/WebBridge traces and audit notes. These are not frontend build inputs and must never enter the source manifest. The actual toolchain/build contract is the complete `src/` tree plus explicit entry/config/lock files and an explicit public allowlist.
- The current Vite config already supports isolated build inputs through `REDDIT_VOC_BUILD_PUBLIC_DIR` and `REDDIT_VOC_BUILD_OUT_DIR`. This permits Plan C to stage only current pointer-selected public data without deleting historical source directories; Plan B can therefore preserve history and still record the superseded-public debt explicitly.
- Current source surface is 179 regular files (~1.9 MiB); current `public/` is ~67 MiB because it includes historical releases. There are no symlinks inside `src/`.
- Plan A closure root remains the exact immutable eight-file contract (source freeze, four ledgers, reconciliation, manifest, validation receipt). Plan B must write to a separate sibling candidate root and bind those files by SHA; it must not add `frontend/` inside the Plan A closure.
- Frozen upstream SHAs rechecked before the source contract: Plan A manifest `c18d313a...1cdfb7`, reconciliation `347fc37a...f957b7`, independent receipt `e2958d7d...bc9f80`, public receipt `045a8440...cc6f7`, and active pointer `4a85a420...b6c30`. The pointer selects release `reddit_voc_release_20260715_70a917e5bdf0` and exactly the Base/Insights/Reports/Personas A3c projection plus the cases manifest/index.
- Actual local toolchain is Node `v22.22.0`, npm/npx `10.9.4`; package-lock SHA is `ae4f9cf6...ae241`. These are source/test evidence inputs only and do not imply a final container or production runtime.
- Plan B source manifest contract is frozen as `reddit_voc_frontend_source_manifest_v1`: deterministic POSIX-sorted allowlisted inventory, upstream Plan A/public/pointer/lockfile/toolchain binding, canonical candidate-input identity, immutable `created/no_change/collision`, private modes, and explicit `promotable_dist_included=false`. It intentionally takes no implicit include paths.
- Fresh post-fix frontend regression is `26 files / 166 tests passed`. Full lint exits 0 and reports only the five pre-existing `react(only-export-components)` Fast Refresh warnings in `src/components/reports/shared.tsx`; no lint errors were introduced.
- Final documentation sync must update existing Plan B, `.codex/context-pack.md`, `.kiro/plan/task_plan.md` and `.kiro/plan/progress.md` in place, preserve historical production checkpoints as historical, and state local L2/source evidence separately from deploy/production acceptance. No new root-level status document is needed.
- Documentation stale-state search found the active contradictions exactly where expected: Plan B frontmatter still says `ready_for_implementation`, task plan says “implementation not started”, context pack says “ready but unstarted”, and progress still ends Plan A with frontend `136/136`. These four entry points will be updated only after the immutable source receipt exists; README has no active Plan B status block requiring a change.
- Fresh final TypeScript project build (`npx tsc -b --pretty false`) exits 0 after all UI governance and semantic fixes.
- `build_frontend_source_manifest.py` is now independently re-read and locally rerun: 4/4 tests plus `py_compile` pass. It uses explicit recursive allowlists, two-pass stable inventory, selected pointer-target SHA checks, all Plan A/public/toolchain bindings, canonical content identity, immutable `created/no_change/collision`, and private 0700/0600 publication. No source path is implicit, so `.env.local` is neither read nor inventoried.
- First full read of the independent validator found three evidence-contract issues before acceptance: oxlint warnings would be miscounted as zero when no summary line exists; a check label hardcoded 21/30,102,047 without a generic asserted projection field; and the subprocess environment inherited unrelated non-VITE secrets. These are being fixed before any real receipt is generated, together with explicit upstream side-effect boundary revalidation.
- The first main-thread validator test replay exposed an environment-contract error: the new test used `pytest`, but neither the default Python nor the uv project environment provides pytest, and `pyproject.toml` does not declare it. The test is being converted to stdlib `unittest`; no dependency will be added and no earlier sub-agent “pytest green” claim will be used as evidence.
- Validator tests were converted to stdlib `unittest`. Main-thread fresh replay is now 8/8 across builder+validator, both scripts pass `py_compile`, and Pyright reports 0 errors / 0 warnings / 0 informations. The corrected validator also verifies a 27-file selected public stage, true oxlint warning counts, minimal subprocess environment, public inventory values, and upstream no-side-effect boundaries.
- Real Plan B source freeze was created at frontend candidate input `870855c1f698e838e697e6deda328f7764a21f3dc22dece6e6ae817b76d0885e`; manifest SHA is `7336aac7c5408a08967a6c5cdf35da3b172dd44bb250db8716732a0a3bb57933`. It contains 218 files / 31,942,286 bytes, including exactly 27 public files, and no `.env`, PEM, old v1/v2 site snapshot, or other forbidden selection. Candidate/source dirs are 0700 and manifest 0600; the immutable Plan A closure still has exactly eight files.
- First real validator run failed closed before receipt at `unit_tests_failed`. A same-minimal-environment probe showed all 166 tests pass, which predicted a staging-path rather than UI regression. Root cause was confirmed: a repository-relative `source_root` produced a relative `node_modules` symlink interpreted from the ephemeral stage, so the link was broken. The validator now resolves the already-lstat-verified dependency directory to an absolute target; the fixture asserts the staged link resolves to the exact source dependency directory. Builder+validator remain 8/8 and Pyright 0 after the fix.
- Second real validator run advanced through all 166 staged tests and then failed closed at lint; still no receipt. The same minimal environment against the original source runs oxlint successfully with exactly 5 warnings / 0 errors, so CI/env policy is not the cause. Diagnosis is now narrowed to the manifest-only staged tree or a test-created staged artifact; no lint rule is being disabled.
- Exact staged-tree reproduction proved the lint root cause: the source manifest omitted `.gitignore`, so oxlint followed the staged `node_modules` dependency link and scanned 16,689 dependency files instead of the project’s 187 files. The real `.gitignore` explicitly excludes `node_modules`, `dist`, `*.local` and editor artifacts and is therefore a genuine lint/build-test contract input. The receipt-less `870855c1...885e` source candidate is superseded; a new immutable identity will add `.gitignore` rather than weakening the lint command or copying an unmanifested file.
- After adding `.gitignore` as an explicit source input, builder+validator tests remain 8/8 and Pyright 0. The new only-consumable Plan B source candidate input is `c04aec93775179be20f6b5538795c647b66a2a6df36c3a898fdc6b7119eb022e`; its manifest SHA is `32afe3adb5ed7b24c62d28a76856ca509432b441941c8befe4946630a2384e6d`. Receipt-less `870855c1...885e` is superseded and must not be consumed by directory scan.
- Real independent source validation now passes and wrote receipt SHA `340e4f65c753eff75031bd129654f9faa8699366e5f76c97726e6cb1c44853ab`. Exact evidence: 219 source files / 31,942,539 bytes; Plan A public projection 21 files / 30,102,047 bytes; selected public stage 27 files; 26 Vitest files / 166 tests; lint exit 0 with 5 warnings; typecheck exit 0; ephemeral build 55 files / 32,628,328 bytes, inventory `87f61c8f...18ee8`, `promotable=false`. Receipt validator code SHA `40fb35e7...7f463` matches the current script and file mode is 0600.
- Deterministic replays completed: the builder returned `no_change` with identical candidate/source manifest identity, and the independent validator reran all four real gates then returned `no_change` with the same receipt SHA `340e4f65...853ab`. No temporary command-evidence children remain.
- Final state-doc edits are narrowly scoped: mark Plan B `complete_local_source_validated`, change its exit evidence from incorrectly Plan-C-owned same-dist E2E to the exact source manifest/receipt, mark Plan C ready but unstarted, prepend one Plan B progress checkpoint, and replace the context-pack “ready but unstarted” clause. Historical Plan A and prior production checkpoints remain unchanged.
- Final independent artifact audit closed P0/P1/P2 at 0/0/0, independently reran the real validator to `no_change`, and confirmed all 219 source files, 27 staged public files, 21 Plan A projection files, five upstream SHAs, canonical identities, validator code SHA, 0700/0600 modes, zero symlink/special files, and Plan A eight-file immutability. Only `c04aec...022e` is consumable; `870855...` has no receipt.
- Final independent UI-scope audit also closed P0/P1/P2 at 0/0/0: 13 routes/no login, five unique DataScopeBars, three release evidence cards, strict non-error normal states, page/module/card failure isolation, 1,322/16,591/16,581/10 and 16,417 VOC counts, 42 themes/46 competitors/17 product scopes/323 persona assignments, six report states, cases 38/12/0, and independent 166/166 tests. Evidence remains local L2 and `production unchanged`.
- Final consistency gate passed: both evidence files are canonical and retain exact SHAs; source candidate has no symlink/special member; Plan A root remains eight files; superseded `870855...` still has no receipt; command-evidence temp root is empty; Plan B frontmatter is complete; changed source/docs have no trailing whitespace; `git diff --check` passes. Receipt projection still states 166 tests, 5 lint warnings, typecheck 0, 55-file ephemeral build, `promotable=false`, and all no-side-effect boundaries.
## 2026-07-15 — Plan C local candidate execution start

- Owner authorized the next Plan C batch. Authorization covers only local candidate orchestration, immutable final artifacts, same-dist local validation, append-only candidate registry, and one promotion packet. It does not authorize upload, remote `docker load`, port 18339, production current switch, collector/cron/shared Nginx/TLS/DNS/other-Docker changes, Provider calls, DB writes, or live send.
- Exact consumable inputs are Plan A candidate `70a917e5...441ac1e` with manifest/reconciliation/receipt `c18d313a...1cdfb7` / `347fc37a...f957b7` / `e2958d7d...bc9f80`, and Plan B frontend input `c04aec93...eb022e` with source manifest/receipt `32afe3ad...384e6d` / `340e4f65...853ab`. Receipt-less `870855c1...d0885e` remains forbidden.
- Plan C must stage frontend bytes only from the Plan B manifest. Directly copying the workbench `public/` would wrongly include historical v1/v2/A2 data and `.env.local` is outside the source contract.
- Maximum evidence before a separately authorized remote side effect is local L2. A local container smoke, browser E2E, export proof, candidate receipt, registry entry, or promotion packet must not be described as deployed or production accepted.
- The generic release workflow is adapted to this repo's content-addressed SHA contract: no semver bump, commit, tag, push, registry publish, or GitHub release is part of Plan C. The task-specific release identity and promotion permit rules in the approved Plan C supersede generic package-release steps.
- The installed `planning-with-files` package contains only `SKILL.md`; its referenced `references/planning-rules.md` is absent, so the summarized rules in the fully read entrypoint are the maximum available instructions. No bootstrap is needed because `.kiro/plan/` already exists.
- `.omc/RELEASE_RULE.md` is absent and no `.github`/`.circleci` workflow files were found in the first release-rule probe. A repo-specific rule cache must be derived from the existing SHA-based scripts and Plan C before final artifact generation; it must not invent semver/tag/push behavior.
- Release-rule inventory confirms the repo has no commits/tags and the two package versions (`pyproject.toml 0.1.0`, UI `0.0.0`) are development metadata, not the production release identity. Existing production artifacts use `reddit_voc_insights_site_release_v2` and a content SHA, so Plan C must not bump either package version.
- Existing `build_insights_release.sh` already enforces alternate public roots below `tmp/`, isolated dist/output, pinned nginx base digest, explicit latest-collection flags, no symlinks, Docker buildx, target `linux/amd64`, and candidate-container mode. It can be reused only after closing one manifest-only gap: candidate mode currently copies top-level static assets from the live workbench `public/` before overlaying the candidate public root, which introduces bytes not sourced from the Plan B manifest.
- `deploy/insights/Dockerfile` already provides a pinned base, UID 101, static `release.json`, and the compose contract already has read-only rootfs, zero bind mounts by design, tmpfs, cap-drop, no-new-privileges and resource limits. Plan C still needs an isolated local smoke wrapper and independent receipt; existing compose defaults target the production service name/18338 and cannot be used directly for candidate smoke.
- Plan C 断点恢复时重新读取计划、进度、分支与工作区：唯一活动批次仍是 local candidate；分支仍为 `codex/momcozy-reddit-backfill-20260711`，仓库文件整体未跟踪，未获得 stage/commit/push 授权，后续只触碰本批明确文件并保留用户工作区。
- 历史经验再次约束本批验收：网站当前量、全局已知量、净新增、已物化净新增、discovery-only 与评论量不可混为一个数字；同比/环比只有在 subreddit、关键词、采集深度、时间窗口、去重与覆盖可比时才可宣称趋势。因此 Plan C 冻结的是已有 Plan A/B 数据故事线与覆盖债务，不把本地全绿包装成完整历史或市场真值。
- 前端已有单一 `ExportButton` 支持 `csv|pdf|pptx|docx`，且 Reports、Insights、Dashboard、Analytics、Search 等真实数据页已接线；Plan C 的缺口不是再造导出格式，而是从最终同一 dist 实际触发四种浏览器下载，并对 CSV、PDF、PPTX、DOCX 的文件结构、非空内容、SHA 与页面来源做独立验证。
- 现有自动化资产分层明确：`audit_insights_dist.py` 负责 dist 静态合同，`playwright_insights_e2e.js` 负责页面合同，`build_insights_release.sh` / `build-release.mjs` 负责 SHA 制品；仓库尚无候选 registry、promotion packet 与四导出整体验收入口，Plan C 应编排复用这些工具而不是复制其内部逻辑。
- `playwright_insights_e2e.js` 是接受已存在 `page` 的异步 callback，而不是可直接 `node` 运行的 CLI；它已经覆盖 13 路由×desktop/mobile、无登录、无横向溢出、零外部请求、A/B/C 故事线、产品三层、竞品同样本、画像头像、六种报告状态、案例 38/12/delta 与采集后台安全链接。Plan C 应增加一个可复现的本地 runner/receipt，不修改这份冻结的页面合同。
- Reports 页面当前日报默认态同时提供四格式导出，filename 绑定 `collection/period/dataset_version`，sections 与 CSV rows 都由当前真实报告生成。四导出 E2E 可固定在 `/dashboard/reports` 的当前日报上，先记录同一 release/dataset identity，再逐格式下载，避免跨页面或跨状态产生不可比制品。
- Plan B 书面规格明确同一 dist 浏览器反馈必须通过项目现有 Playwright CLI runner 执行，Plan C 若产品化 wrapper需单独实现和测试；旧 RC3 确有 `browser-e2e-receipt-rc3.json` 与 `promotion-packet-rc3.json` 可参考，但它们绑定旧 release，不能复制为新候选证据。
- 旧 RC3 生产只实际验收 CSV/DOCX，PDF/PPT 未申领；本批必须把 PDF/PPT 也纳入新候选的真实下载和结构校验。旧 packet/receipt 仅可提供 schema/失败边界参考，所有哈希、输入与结果都必须重新从 Plan A/B 最终身份产生。
- 旧 RC3 packet 的可复用思想是：绑定 input/candidate/E2E/release manifest/SHA256SUMS/dist sums/TGZ/image tar，显式列出授权动作、禁止动作、cutover preconditions 与 post-cutover acceptance；但新 packet 还必须补 Plan A/B/C receipts、四导出、local container/security smoke、production baseline observation 与 expiry，并保持 `promotion_authorized=false`。
- 旧浏览器 receipt 把本地浏览器验收标为 `L3`，与本批启用的 evidence-grade gate 不一致；Plan C 新 receipt 一律将同一 dist、本地 HTTP、浏览器和容器证据标为 L2。旧浏览器执行入口是 `playwright-cli 0.1.17`，URL `127.0.0.1:4188`，这说明本地 runner 可复现而无需引入新依赖。
- Plan C 最终 gate 的输入边界已再次确认：只能消费候选根下 `frontend/dist` 和正式 `frontend/container-release/<release_sha>/release-manifest.json`；`release-metadata-preview` 明确不可提升。最终 UI receipt 必须同时绑定 source manifest/receipt、release manifest、同一 dist E2E、四导出、安全与容器 smoke。
- Plan C C3 明确要求 current production baseline SHA；本地候选身份本身不依赖它，promotion packet 依赖它。若现有本地冻结的 production baseline 无法证明当前仍相同，C1/C2 可继续完成，但 C3 在 fresh read-only baseline 前必须 fail closed，不能把旧 RC3 baseline 当“当前”事实。
- Plan B source manifest 本身已经逐文件冻结219个输入，并精确包含27个 public stage 文件（21个 Plan A 数据投影 + pointer/cases + 3个静态资产）；Plan C 可直接按 `source.inventory.files` 验 SHA 后重建 source stage，再将其中 `public/` 原样作为完整 candidate public root，不再读取 workbench live public。
- Plan B receipt 字段名是 `frontend_candidate_input_sha256` 与 `frontend_source_manifest_sha256`，Plan A receipt 字段名是 `candidate_input_sha256` / `candidate_data_manifest_sha256` / `reconciliation_sha256`；新 orchestrator 必须按真实 schema 精确校验，不能依赖猜测性的通用 `manifest_sha256` 键。
- 候选 public manifest-only 边界已建立 RED：新增聚焦测试精确检测候选 stage 不得读取 `DEFAULT_PUBLIC_ROOT`，当前脚本按预期因 `find "${DEFAULT_PUBLIC_ROOT}"` + 顶层资产复制失败。下一步只删除这段隐式复制，保留显式 `PUBLIC_ROOT` 全量复制与现有数据审计。
- manifest-only 根因已最小修复：candidate mode 现在只把显式 `PUBLIC_ROOT` 复制到隔离 stage，不再读取 live UI public 的任何字节；脚本 suite 8/8 与 `bash -n` GREEN。默认非候选构建行为未改，远端脚本未触碰。
- Release-rule final inventory：无 CI workflow、无 tag、无 commit、无 changelog、无 registry push；`tmp/` 与 tar/tgz 已在根 `.gitignore` 排除，UI `dist` 也被自身 `.gitignore` 排除。分发方式是本地 content-addressed Docker tar + TGZ，触发条件是显式 Plan C CLI 与后续精确 owner authorization，不是 semver/tag/merge。
- C1 独立盘点确认不存在 candidate orchestrator/registry/promotion builder；可复用的是 Plan A/B canonical immutable writer、双观测 freeze、O_NOFOLLOW + stable-inode flock 以及 final release builder。Registry 必须固定为 entries/events/runs，blocked/failed 不得生成 promotable entry/event，所有路径禁止 latest/glob 自动选择。
- C1 发现 Plan A 没有独立命名的 quiescence receipt，但其最终 source-freeze 已记录双观测和 L3 frozen evidence。本地 Plan C 可以诚实消费“既有冻结输入”并生成 typed offline validation projection；这不等于 fresh current quiescence。任何 promotion packet/current cutover 仍须单独 fresh L3 baseline/preflight。
- C2 独立盘点新增两个真实阻断：candidate build 仍从 live `UI_ROOT` 读取 React 源（仅 public 被覆盖），且当前 Nginx SPA fallback 会让 `/.env` 返回200。Plan C 必须从 Plan B 219文件 manifest-only stage 构建、让 release identity绑定B三项身份，并在候选运行时明确返回安全404。
- 本机 Docker 是 desktop-linux 29.4.1、宿主arm64、buildx 0.33.0且支持linux/amd64；这些只是工具可用性。新 image tar的amd64离线审计和受控本地容器 smoke仍必须实际完成，不能复用旧 RC3 image或远端receipt。
- Plan A source-freeze 不是“仅文字记录”：其 canonical manifest SHA `0d7dc292...98a8233` 绑定5,928文件/137,215,820 bytes，明确 `double_observation_member_stat_sha_verified=true` 与纳秒mtime比较；Plan A data manifest 又绑定该SHA并标记 `L2_local_candidate_with_L3_readonly_baseline`。因此本地候选可消费这一既有冻结事实，但只能称 frozen-input quiescence，不称当前服务器fresh quiescence。
- E2E/export 独立盘点确认本机 npm cache 有固定 `@playwright/cli@0.1.17` 与完整 Chromium revision，可用 `npm exec --offline --package=@playwright/cli@0.1.17 playwright-cli`，无需写入项目依赖；命令必须先核版本且缓存缺失时 fail closed，禁止联网获取 latest。
- Frozen E2E callback 对 Plan B 有一个已确认 stale 断言：仍要求已删除的 `release_switch_executed=false`。Plan C 需要改为验证 served/pointer identity、promotion/acceptance unavailable，并展开 artifact details验证 `production unchanged` 与五个 false副作用；13×2、A/B/C、报告/画像/案例/后台链接其余合同保留。
- 四导出前端代码路径都已存在，唯一代码缺陷候选是 PPTX `writeFile` 未 await；但修改它会改变已冻结 Plan B source identity。本批先不改 Plan B，实际下载若暴露异步失败则 candidate fail closed并重新决策；版本证据采用同一dist页面身份、含dataset version的suggested filename、report JSON内容对账和receipt链。
- Nginx 当前只硬编码拒绝旧20260714私有路径，通用 `/` fallback会把`/.env`映射到index；安全修复应使用版本无关的隐藏/receipt/source/private路径拒绝规则，同时保留 `/data/` exact file 404，避免每次数据版本更新重写旧路径清单。
- Local container smoke 已先建立 RED：脚本缺失与 Nginx安全规则缺失均按预期失败。现已新增 isolated smoke 实现，固定loopback动态端口、独立internal network、UID101/read-only/zero mounts/cap-drop/no-new-privileges/资源限制、13 routes、7 public与19 forbidden路径、前后既有container不变、精确清理及canonical receipt；当前只剩由C2并行负责的Nginx规则RED待合并。
- Owner 最新优先级是先让生产新版本可供老板查阅。当前 critical path 缩为 exact Plan A/B → manifest-only final release → 核心13路由 E2E/安全404 → linux/amd64 local smoke → unique promotion packet；candidate registry深度治理、四导出增强和完整automation明确后移，但 exact packet SHA + release SHA生产授权门不降级。
- Manifest-only source materializer 已 RED→GREEN（2/2 + py_compile），并实际从当前UI按 Plan B manifest逐字节物化219文件到 `tmp/reddit-voc-plan-c-production-critical/frontend/source-stage`；candidate input和manifest SHA精确为 `c04aec...eb022e` / `32afe3...384e6d`，未复制任何未列出 live source/public 文件。
- 首发 same-dist E2E runner 已完成并由主线程复跑：固定 offline Playwright CLI 0.1.17、正式v2 release/dist/pointer/四数据集绑定、127.0.0.1动态SPA server、13×2结果/零错误外部请求、finally清理及canonical L2 receipt；E2E+source stage+local smoke静态合同合计11/11 GREEN，Python compile与两个JS syntax均通过。四导出callback已准备但validator按新优先级后移，未申领四导出验收。
- 老板可见生产优先的第二次断点复核保持同一边界：Plan C 仅推进 final build/E2E/local smoke/promotion packet；branch 仍为 `codex/momcozy-reddit-backfill-20260711`，工作区整体未跟踪，未 stage/commit/push。候选 registry 与四导出完整验收继续作为上线后债务，不参与首发阻断。
- C2 的最后 build-receipt 契约已进入脚本：`reddit_voc_insights_build_receipt_v1` 现已出现，并绑定 Plan B + release lineage。当前仍需等并行实现者完成 focused replay，主线程才会启动真实 Docker build；不会基于正在变化的脚本生成候选。
- 首发受控提升与验收脚本正进行只读复用盘点；在新 packet SHA、release SHA 和 fresh production baseline 完成前，不上传、不 `docker load`、不开 18339、不切 current。collector/cron/shared Nginx/TLS/DNS/其他 Docker 仍为绝对排除项。
- C2 主线程复验已通过：四个构建/制品/dist/容器合同 suite 为32/32，两个 shell 语法检查与 release builder Node 语法检查均 exit 0。真实构建输入路径逐项存在，Plan B manifest/receipt SHA 复算仍为 `32afe3...384e6d` / `340e4f...853ab`；目标 dist、container release 与 build receipt 在首次构建前均不存在。
- 一次预检因当前 shell 未从 PATH 找到 `stat` 而在首个只读 metadata 输出处退出；改用绝对 `/usr/bin/stat` 后成功，未产生写入，也不是项目故障。source stage 仍严格为0700，受控 `node_modules` 工具链链接尚不存在，等待构建前临时创建。
- 首个真实 final candidate build 已成功：release SHA `434fa96bcd32aef73865c6106ebdaa31d0fd791c30eb4a8fe91310b28a291a8a`，release manifest SHA `56c2bdfa...211e1`，image tar SHA `f3083d6a...cba34`，TGZ SHA `5f9dbc45...3f837`，private build receipt SHA `ca285056...fb837`。166/166 tests、lint 0 errors + 5 existing warnings、TypeScript/Vite、dist audit、amd64 image audit 与 SHA256SUMS 全通过；临时 `node_modules` 链接已由 trap 精确清理。
- Build receipt 的 Plan B identity、collection flags 与 data release 是结构化嵌套字段，不是顶层字段；一次只读 `jq` 顶层投影因此显示 null，随后按真实 schema 重开确认 `c04aec...eb022e` / `32afe3...384e6d` / `340e4f...853ab`、219文件，以及 `latest_collection_integrated=true` / `fully_hydrated=false`。这不是 receipt 数据缺失。
- 旧 RC3 promotion packet 只能作 schema参考；仓库没有新 Plan C packet builder/validator。现有 `deploy_insights_tencent.sh` 会绕过新 packet/permit/CAS/18339 gate，不能裸跑；`deploy_webapp_tencent.sh`、edge配置、disable rollback更会触碰明确排除的 collector/shared Nginx/TLS/cron，全部禁用。首发唯一剩余实现缺口是窄 scope deterministic packet validator + CAS promotion wrapper。
- 首次真实 same-dist E2E 在浏览器启动前 fail closed：`release_manifest_files_not_sorted`，未写 receipt。根因可预测且已定位为 JS builder 的 locale-sensitive `localeCompare` 与 Python gate 的 Unicode/code-point排序不一致；真实混合大小写 asset names 暴露了 fixture未覆盖的跨语言canonical ordering缺口。修复方向是 builder使用明确 code-point comparator并加 mixed-case RED test，然后重建全新 release identity，绝不放宽E2E gate或手改manifest。
- 公网只读基线复核仍是旧 release `9e0d2313...d650`、旧 pointer `reddit_voc_release_20260715_a900e6ce7b63`，13/13 route可达；旧版 `/.env`、`/.env.local`、`/release-manifest.json`、`/frontend-source-manifest.json` 仍返回SPA 200。这是当前生产既有安全债务，新候选必须在18339与正式生产都提升为404，不能沿用RC3旧验收预期。
- 排序修复后的唯一可提升 release 是 `a5fa1e0a0a224969669d7e6ad79a9415b69f2ba4646b6e2bbca9030ff3d460f3`；manifest SHA `fe6779b2...9f8a1`，TGZ SHA `cc94aa72...97296`，image tar SHA `4f9cb422...3a3b0`，build receipt SHA `f209b1fe...2e4dd`。旧 `434fa...` 为superseded失败证据，不得提升。
- 第二轮 E2E 首次又在浏览器前 fail closed：npm exec 未使用 `--` 参数分隔符，`--version` 被npm自身消费并返回10.9.4，而不是固定CLI 0.1.17。新增真实命令契约RED后在默认runner加入分隔符；7/7 tests与实际离线版本0.1.17通过。随后同一dist 13×2真实浏览器验收通过，receipt SHA `a24ed985...a3f86`。
- 本地容器首轮失败是direct `docker run`没有Compose healthcheck；补显式healthcheck后容器健康。第二轮进一步暴露Docker Desktop 29对internal network的动态host publish不分配端口（HostPort为空/0，NetworkSettings Ports为空）；这不是应用失败。为保持真正内部网络隔离，smoke改为不发布任何host端口，所有HTTP/404通过容器内loopback `wget`执行，并显式验证HostConfig无PortBindings。
- 一次zsh诊断循环误用保留参数名`path`，覆盖PATH后使cleanup trap找不到docker，留下一个由本轮创建且release label精确匹配的debug container/network/image；已仅按精确名称与release SHA清理并验证三者不存在。最终isolated container smoke通过，receipt已创建，生产/远端未变。
- 最小promotion packet builder/validator现已新增并由主线程复跑12/12：16项显式artifact、canonical 0600、created/no_change/collision、tamper/symlink/escape/extra-field/expiry/授权位门禁。它明确保留registry与four-exports为deferred debt；下一步只差fresh L3 baseline receipt后生成packet SHA，再向owner请求一次精确SHA授权。
## 2026-07-15 — Urgent permit-aware production wrapper implementation lane

- This lane is implementation and stdlib-test only: no SSH, upload, `docker load`,
  remote candidate, current switch, or production mutation will be executed.
- The legacy `deploy_insights_tencent.sh` / `remote_install_insights_release.sh`
  cannot be used as the new entry point because they do not consume an immutable
  owner permit and the installer targets production port 18338 directly.
- The new entry point must reopen the canonical promotion packet validator and
  every bound artifact, require an exact unconsumed permit, pass only key and
  known-hosts paths to strict SSH, and hold one remote `.deploy.lock` across
  fresh baseline, 18339 candidate smoke, compare-and-swap cutover, and L4 receipt.
- Failure before cutover cleans only the temporary candidate; failure after
  cutover reports `rollback_required=true` and never mutates shared Nginx.

## 2026-07-15 — Plan C controlled production promotion accepted

- Owner exact authorization for packet `83d5ebea...10570` and release `a5fa1e0a...d460f3` was
  recorded as immutable permit SHA `c8ca362a...3e482` and consumed once. The superseded partial
  permit/promotion wrappers were removed; the executed single-use remote runner SHA was
  `45cbb77c...31b` and was transferred only through an isolated `/tmp` directory that was removed.
- Fresh preflight matched current `9e0d2313...d650`, healthy/restart-0 insights, collector and
  LibreTranslate, stable DB/report and 53 containers, unchanged shared Nginx/cron, no one-shot,
  candidate, staging or 18339 listener. The runner held `.deploy.lock` across exact artifact
  verification, 18339 candidate smoke and CAS cutover.
- Release `a5fa1e0a...d460f3` passed remote amd64/UID101/dist verification, candidate and production
  runtime contracts, 13 routes, eight public artifacts and 20 private/security 404s. Production
  current, container label and HTTP marker all resolve to the new release; data pointer is
  `reddit_voc_release_20260715_70a917e5bdf0`.
- Public acceptance passed TLS/health, 13/13 routes, 20/20 security paths and frozen headless browser
  callback across 26/26 pages, six report states, cases 38/12/0 and two safe collector links, with
  zero browser errors, same-origin failures or external requests. L4 receipt SHA is
  `b5fcd682...76ade`; consumption receipt SHA is `5904305d...1e5c`.
- A first public HTTP harness invocation failed before site assertions because zsh reserves lowercase
  `path` as an array tied to `PATH`; the loop variable removed `curl` from command lookup. Renaming it
  to `request_path` made the exact matrix pass. Future zsh scripts must not use `path` as a variable.
- Boundaries remain exact: collector/cron/shared Nginx/TLS/DNS/other Docker unchanged,
  `provider_call=false`, `database_write=false`, `schedule_change=false`, `live_send=false`.
  Registry/four-export completion remains deferred; open coverage 1,179 and pending lineage 18 are
  not hidden, and fully hydrated remains false.

## 2026-07-15 — Report, overview, cases and personas V2 intake

- Screenshot 1 is direct production evidence of a label-granularity defect: both post and comment
  trend charts contain multiple nonzero observations but every visible x-axis label renders as
  `00:00`. This is consistent with day-level timestamps being formatted as clock time; the raw
  report schema and formatter must be joined before selecting a fix.
- Screenshot 2 shows two implementation-oriented terms, `当前闭合期` and `闭合归档`, exposed as
  equal-weight primary controls. The owner requires a single business-readable default. The design
  must preserve prior-period evidence for同比/环比 without forcing users to understand data-pipeline
  closure terminology.
- The owner also requires a brand-level radar plus overall score recalled from the prior UI, only
  evidence-qualified case links in the default gallery, and more than two aggregate personas derived
  from post/comment evidence and the tag dictionary. These are metric/data-model changes, not cosmetic
  copy edits, so they remain behind a written-design approval gate.
- Current production release remains `a5fa1e0a...d460f3`; the prior packet is consumed and cannot
  authorize this V2. Read-only analysis and local spec work are authorized; production remains unchanged
  during this design phase.

### Daily time-axis and report-scope root cause

- `RealReportView.formatTimelineLabel` selects the formatter from `identity.period`: every `daily`
  report is formatted as `HH:mm`, rather than selecting from the series' actual grain.
- The current daily report contains two different series grains: `observed_timeline` has 24 hourly
  buckets, while `trend.points` has 14 closed daily windows (2026-07-01 through 2026-07-14), all starting
  at local midnight. `TrendChart` sends the latter through the daily `HH:mm` formatter, so every label
  deterministically becomes `00:00`. This is the screenshot's exact root cause.
- The fix must make the formatter accept the series grain (or an explicit label mode), not infer it from
  report type. Tests must cover hourly observations and daily/weekly/monthly trend windows separately.
- `SnapshotReports.tsx` still exposes `current` and `archive` as equal-weight state even though both
  risk-v2 descriptors are closed calendar periods. This distinction is storage/version navigation,
  not a business analysis dimension, so it should not remain a primary toggle.
- The report identity and exact date window already provide the business anchor. The primary scope can
  become `最新完整周期`, while older closed reports move into a historical-period selector.

### Persona-count root cause

- The current builder is intentionally hard-coded to exactly two personas and exactly one promoted
  source tag per persona. The two-card output is therefore a schema/config restriction, not a data claim.
- Current governance has only two promoted tags; simply relaxing `len(persona_ids) != 2` would either
  duplicate evidence or convert held/unreviewed tags into factual personas. V2 needs a cohort model that
  separates dictionary reference dimensions from evidence-qualified assignment rules.
- The existing safety boundaries remain correct and must survive expansion: these are aggregate evidence
  cohorts, not author identities; counts are matched posts/comments, not unique people; avatars are local
  synthetic illustrations and never Reddit user images.

### Owner-specified comparison-card behavior

- Calculate period-over-period and year-over-year only when the metric contract provides a valid current
  value and baseline and the comparison gate permits presentation. Otherwise render `—`; do not replace
  unavailable values with `0`, “不可比较”, or inferred percentages.
- Each card needs a compact `?` disclosure containing metric definition, current period, baseline period,
  formula, coverage state and reason codes. The primary card stays executive-readable; governance detail
  moves into the disclosure.
- Embed a sparkline from the metric's own historical observations. Per owner instruction, an upward path
  is red and a downward path is green. Flat or insufficient series uses neutral gray, without inventing a
  direction.
- The current UI discards useful arithmetic for every `provisional_observed_sample` comparison and shows
  only `已观察样本`. The underlying contracts already contain current, baseline, absolute delta and often
  relative delta, so the requested cards can surface real sample comparisons without changing source data.
- Availability by current data: daily环比 has all four post/comment count/share values; daily同比 has
  comment count/share but no post baseline. Weekly环比 has all four; weekly同比 has no baseline. Monthly
  count环比/同比 are calculable; negative-share differences are calculable in percentage points, while
  relative rates are undefined where the baseline share is zero.
- Display contract: counts use relative `%` only when baseline > 0; negative evidence share uses percentage
  point (`pp`) difference; missing baseline renders `—`. The 14/13/12 observed trend points can power the
  daily/weekly/monthly sparklines, but because direction gates are currently false the tooltip must say
  `观察样本轨迹，不代表总体趋势` even when endpoint color is red/green.

### Tag-dictionary persona reference audit

- `dim_tag_v6.3_final.csv` contains 2,346 governed tag rows and 28 fields. Every row has `aipl_node`,
  `consumer_card`, `story_lines`, `problem_type` and `intent_type`, so the dictionary genuinely carries
  persona-adjacent business relationships.
- `consumer_card` is not synonymous with persona: only 97 rows are `画像卡`; 1,959 are `场景任务卡`
  and 290 are `决策旅程卡`. The three must remain distinct axes rather than being flattened into people.
- Reference diversity is materially greater than two: 7 AIPL nodes, 25 story lines, 7 problem types and
  11 intent types. These dimensions can enrich cohort profiles, but dictionary row counts alone are not
  Reddit population counts; current post/comment evidence must drive every displayed cohort total.
- The spreadsheet audit was read-only; no CSV values or workbook artifacts were modified or exported.

### Current evidence available for cohort recomputation

- The deployed candidate snapshot exposes 1,322 post records and the public comment corpus, each with
  deterministic `tagging.tag_ids`, post/comment identity, event time, sentiment, topic, brand binding and
  product bindings. Persona cohorts can therefore be recomputed from actual evidence rather than copied
  from dictionary row frequencies.
- The public tag dictionary is a governed projection (`rules` plus dictionary identity), while the full CSV
  remains the business-reference source. V2 must join by `tag_id`, count posts and comments separately,
  and record unmatched or unqualified assignments instead of silently dropping them.

### Persona evidence join result

- Of 97 dictionary rows marked `画像卡`, only 16 currently have any lexical assignment in the merged
  corpus. They touch 60 posts and 1,516 stored comments, with 63 post assignments and 1,547 comment
  assignments; these are entities/assignments, not people, and can overlap.
- The apparent volume is heavily distorted by held tag `L0-SVC-019 正面反馈` (1,277 assignments), whose
  governance audit says the label/theme fit is mismatched. It cannot be used to manufacture the largest
  persona cohort.
- The current two-card model mixes one `场景任务卡` source (`工作场景`) with one true `画像卡` source
  (`强烈推荐`). This confirms the page should model three related but distinct layers: audience cohort,
  decision journey and usage scenario.
- Only one currently promoted source tag is a true `画像卡`. To show more than two honest cohorts, V2
  must introduce evidence tiers and cohort rules with explicit review status; it must not silently promote
  held or lexical-only tags into verified users.
- The corpus supports an operational Momcozy-first split: 193 posts/599 comments are direct reviewed
  Momcozy bindings; 180 posts/490 comments are Momcozy multi-brand comparison context; the remaining
  949 posts/15,492 comments are category/competitor context. Every cohort card can therefore show direct
  Momcozy evidence and comparison context separately.
- Stable analysis fields already expose distinct needs at useful volume in Momcozy evidence: product
  evaluation (312 direct entities), troubleshooting (305), purchase decision (138), comparison (670
  multi-brand), operations (257 direct + 243 multi), fit/comfort (129 + 239), output/supply (61 + 184),
  support (68 + 58), family scenario (45 + 57) and work scenario (16 + 25). These are better cohort inputs
  than pretending two tags represent two people.
- The current frontend contract only accepts `status=promoted`, one source tag, and the exact assignment
  state `rule_match_under_promoted_tag`. Honest expansion therefore requires a versioned persona schema
  and validator update; a view-only loop over six cards would fail closed or misstate evidence.

### Owner-provided overview mission banner

- The supplied PNG is 2,064 × 386 (SHA-256 `c59ebf55...e40beed`), a 5.35:1 wide asset suited to a
  full-width mission banner immediately below the overview page header and above the radar/score block.
- Desktop can display the complete artwork. On narrow screens the embedded text becomes unreadable if the
  full image is merely scaled down, so responsive acceptance needs a deliberate mobile treatment (cropped
  decorative image plus accessible mission text) while preserving the same asset and site tone.

### Prior radar recall and metric-governance constraint

- The handover specifies the earlier Dashboard construct exactly: an overall `brandScore` plus six
  radar dimensions (`声量`, `口碑`, `互动`, `意向`, `竞品优势`, `危机响应`). The monthly design used a
  different six-dimension vocabulary and an unsupported hard-coded `行业基准: 70`.
- The reusable components still exist (`BrandScoreCard`, `RadarChart`, and the monthly
  `BrandHealthDashboard`), so the visual language can be recalled without redesigning the site shell.
- The project's own interaction audit records that prior scores were manually chosen and lacked a
  computation contract. Therefore the old UI is a layout reference only; none of its numeric values,
  benchmark 70, NPS, response time, ROI, market-share or conversion claims may be restored as facts.
- Current snapshot boundaries explicitly mark NPS, response time, market share, ROI and combined
  post/comment weighting as unsupported. The V2 score must be a transparent Reddit observation index,
  keep posts/comments separable, expose coverage state, and avoid calling itself an industry benchmark.
- Visual recall check: `v4_dashboard.png` establishes the current product tone (white cards, restrained
  Momcozy pink, compact metric hierarchy) but contains no radar. The radar should therefore reuse that
  card language and the existing chart component, not reintroduce the older unsupported dashboard
  numbers or change the shell/navigation.

### Case-gallery default quality gate

- The verified case catalog currently merges `38` curated seed items, `12` legacy unverified items,
  and `0` approved delta items into the default searchable catalog. Thus an empty/default search can
  expose pending links even though the page describes the output as selected cases.
- The 12 legacy entries are explicitly labelled `legacy_simulated_web_snapshot` and
  `verificationStatus = pending`; they must not be reclassified merely because a URL string exists.
- The service already has a strong approved-delta contract (HTTPS, canonical URL, content hash,
  verification timestamp, provenance, manifest SHA). The smallest safe change is to make the default
  searchable view `curated_seed + verified approved_delta`, retain the 12 pending items only in an
  explicit review queue, and add verified increments through the existing versioned index.
- User wording `高质量链接都通过` is interpreted as “all links that pass the quality gate should be
  visible by default”, not “mark every candidate as passed”. Reachability, canonical identity,
  content relevance and evidence provenance remain required before promotion.

### Fresh case-link reachability audit

- A read-only HTTP audit at `2026-07-15T14:20:00Z` found all 12 legacy simulated URLs unfit for the
  default catalog: 9 returned 404, 2 returned 403 and 1 failed at the network layer. This independently
  confirms the governance label `pending` and the need to exclude them from default search.
- The apparent 35/38 mismatch was caused by the first audit selecting only `https` literals; three seed
  URLs still use `http`. A complete `http|https` retry reconciled all 38 seeds: 37 returned 2xx after
  redirects, and the Apple Podcasts URL returned 500 to the automated request.
- Reachability is necessary but not sufficient. Title/content relevance, canonical HTTPS identity and
  provenance still require the catalog quality gate; the Apple entry remains fail-closed until a browser
  or replacement canonical link passes.

### Evidence-grounded radar recommendation

- The old six-axis score cannot be restored because its values were generated from mocks and unsupported
  proxies. Current Insights supports a four-axis `观察样本品牌指数`: Momcozy post visibility 131/(131+55)
  = 70, comment visibility 274/(274+1120) = 20, post non-negative evidence 1-17/131 = 87, and comment
  non-negative evidence 1-14/274 = 95.
- A versioned equal-weight v1 would display 68/100. Missing or below-threshold input makes the overall
  index `—`; weights are never redistributed. The number is an observed-sample index, not market share,
  NPS, health grade or industry benchmark.
- Product association 145/405 = 36% and full-thread structural coverage 859/1322 = 65% belong in a
  separate `研判基础` block, not the brand score. Current direction gates are false, so this panel must
  not show an invented increase/decrease trend.
- Spec self-check reproduced the score from the current Insights artifact: four raw dimensions are
  70.4301, 19.6557, 87.0229 and 94.8905; their fixed-weight mean is 67.9998 and rounds to 68. Competitor
  context sums are exactly 55 posts and 1,120 comments across 46 rows; product and thread inputs also
  re-open as 145/405 and 859/1,322.
- Implementation should consume named contract fields through one pure selector rather than search for
  numeric values. The current Momcozy counts are the denominators of `primary_kpis.negative_evidence_share`
  (131/274), while competitor counts are summed `competitor_context.observed_count`; tests must ensure the
  entity semantics remain aligned before scoring.
- Follow-up verification shows competitor observed counts and classified negative-share denominators are
  exactly equal (55 posts, 1,120 comments) in the current artifact. The spec now uses classified
  denominators on both sides of the visibility formula and requires an invariant check, eliminating a
  possible semantic mismatch if future unclassified entities appear.

## 2026-07-17 — Overview and quarterly-insights candidate closure findings

- Build receipt A8 produced release `33f57d...d5a2` from source A8 `067412...e5`; it proved that a source manifest can
  correctly bind an auxiliary dataset while the release audit still omits it. The 72-file dist passed the incomplete audit,
  but real same-dist browser execution caught the missing quarter artifact as a 404. The audit now treats brand health,
  casebook and quarter insights as fixed runtime dependencies; that release is superseded.
- Build receipt A9 produced release `73717c...be3c` from the same source A8 after the audit fix and correctly contained 74 files.
  Its browser run exposed the 390 px / 479 px mobile overflow. The Tab selector ambiguity fixed during this run belonged to
  the test script, not the product UI, and is not counted as a product defect.
- The remaining mobile overflow was not caused by the chart width. `RankedBarList` put an unbounded detail sentence inside a
  `shrink-0` value span, expanding the document to 479 px at a 390 px viewport. Moving the detail into a wrapping block fixed
  the root cause; the 26-route desktop/mobile E2E now reports no horizontal overflow.
- The only locally promotable identity is true source A9 `c7e5eeedf...df7c8`, materialized by source-stage receipt
  `650d4c08...fa6e1b` and built by A10 receipt `e2c9755d...f0531b` into release `9c4a45f2...84cc5`.
  Earlier A6/A7/A8 source or release identities must not be reused after the UI source changed.
- A fresh L3 read-only observation still sees production release `627fbab662...78bed4`. Packet `7ff1227c...ceb8` is validated
  but has `promotion_authorized=false`; no permit, upload, remote Docker mutation or current switch occurred. Exact packet SHA
  plus release SHA authorization remains the next boundary.

## 2026-07-17 — V2 center business activation closure findings

- The activation builder and independent validator conserve 3,494 posts and 27,158 comments, including 20,205 linked,
  6,943 unresolved-parent and 10 quarantined rows. Business outputs reconcile to 23,586 analysis-ready VOCs,
  159,044 governed facts, 26 indicators, 82 atomic persona definitions, eight cohorts, six report artifacts and 78 storylines.
- A frontend source can bind an auxiliary manifest while the release audit still removes the corresponding runtime files.
  The first B2b release reproduced this failure: source validation passed but the dist remained at 74 files. The release audit
  now admits exactly the fixed activation projection SHA/schema/count contract; the final dist has 76 files and promotion
  validation proves the auxiliary manifest is present in the release inventory.
- Snapshot-heavy Vitest files were nondeterministically timing out under file concurrency. All 24 failed/slow cases passed
  with one worker; setting `fileParallelism: false` made the default release gate deterministic. The final default run passed
  195 tests with 46 intentionally skipped and no test timeout increase.
- Activation and frontend source cannot mutually hash-bind. The non-circular chain is activation → public projection →
  frontend source → release/shadow receipt. The final two shadow receipts bind the activation projection to the candidate
  while retaining the original activation manifest as immutable upstream evidence.
- Final local candidate release is `f335d9d27e16...34325d4b`; packet `fa54470d7e20...1dd246f6` is
  `ready_for_owner_authorization`. Production remains `9c4a45f2...84cc5`; no permit or production switch occurred.

## 2026-07-23 — Business-history `history2` promotion candidate

- The exact public reports projection now carries 14 daily, 12 weekly and 12 monthly historical business periods while keeping three internal comparison archives out of the business entry count. Release `ebaa54439066...9df313` passed the isolated build, 26-page same-dist acceptance, local container smoke, four real downloads and security aggregation.
- Two acceptance callbacks were stale rather than the site: the E2E callback still expected the old daily sentence and the old no-history boundary, while the export callback still expected the removed `报告口径` button. They now validate the governed daily activity sentence, exact 15/13/13 select option counts including `current`, and the current history selector. Focused tests and both real browser paths pass.
- Candidate `fab42d1761fb...655b19` is append-only registered; independent registry validation reports three committed entries and zero failed, blocked or pending transactions. This is local evidence, not production acceptance.
- Fresh L3 read-only baseline `57488233d214...fd36a` observes production release `e8bea1546862...19086a3b` stable. Packet `b1f7d535bbb0...68eff2` binds 20 exact artifacts and validates with `promotion_authorized=false`, `consumed=false`, `deploy=false`, `remote_write=false`; it expires at `2026-07-22T20:58:00Z` and requires an exact packet SHA + release SHA owner authorization before any upload or switch.

## 2026-07-23 — `history2` independent-audit remediation and superseding packet

- Independent review correctly identified that the first history acceptance only counted dropdown options and that loopback exports were mislabeled as public L3. The E2E now really selects one daily, weekly and monthly history period, proves exactly one history JSON request and URL/data binding for each, then proves a daily direct deep link. Receipt: `a423f31fe195...d56758`.
- The four-export receipt now classifies `127.0.0.1` / `localhost` as `L2_local_container_readonly_browser_download_acceptance`; public L3 remains available only for non-loopback HTTPS. New export receipt: `b375c39c4e1b...b81e4`.
- Security aggregation now fails closed unless the release manifest binds the exact compose, release `SHA256SUMS` matches compose/dist/manifest/image, smoke binds the exact manifest/dist/image/platform, and export scope matches its evidence grade. The unsupported `collector_isolation_required` claim was removed from this local security receipt. New receipt: `005605f447b1...9458`.
- Candidate `07e83ed3cc25...475ef` supersedes `fab42d1761fb...655b19` while preserving append-only history; registry validates 4 entries and 4 commits with zero failed, blocked or pending transactions.
- Fresh read-only production baseline `c5906919ae3e...326e` still observes release `e8bea1546862...19086a3b`, healthy collector/translation/insights and stable 58-container inventory. Superseding packet `0b32371ea79b...35057` binds 20 exact artifacts, expires `2026-07-22T21:19:42Z`, and remains authorization-free with every production side-effect false. Packet `b1f7d535bbb0...68eff2` is superseded and must not be used.

## 2026-07-23 — Final audit loop: unique 21-artifact packet

- Read-only review correctly blocked the 20-artifact packet because the older packet still passed the same validator and because the final candidate receipt was not directly bound. The V3-native packet contract now requires `candidate_ui_validation_receipt` as artifact 21 and validates its release, V3 lineage, build, image, transfer, E2E and smoke bindings. Consequently both `b1f7d535...` and `0b32371e...` fail the current validator with `artifacts_unexpected_fields` even before their wall-clock expiry.
- Local export status now matches its evidence scope (`passed_local_readonly_export_acceptance`), while non-loopback HTTPS retains the public status. Security aggregation additionally requires all CSV/PDF/PPTX/DOCX content checks and `release_and_report_binding_verified` to be true; a four-download count alone cannot pass.
- Final evidence hashes are export `337cfad82828...eb1f5`, security `abb0fe2a7e39...2e24c`, candidate receipt `791d71949a1e...12379`, and baseline `b3a1f2d5aeb2...4ad46`. Final append-only candidate is `096fd5dd6d85...1e127`; registry is 5 entries / 5 commits / zero failed, blocked or pending.
- The only packet accepted by the current validator is `ec3458cbd1a4...1c2507`, with 21 exact artifacts and expiry `2026-07-22T21:30:58Z`. It remains unconsumed and unauthorized; no production mutation occurred.
- Legacy V3-native permit compatibility is now an exact four-field allowlist over authorization ID, permit SHA, packet SHA and release SHA for only the three already-issued historical permits. It is not available to the permit builder or CLI. A newly constructed permit targeting either old 20-artifact packet fails with `artifacts_unexpected_fields` before any permit is written; the current 21-artifact packet continues to validate.
- The final regression suite now reopens all three allowlisted V3 permits and asserts end-to-end that a new permit cannot downgrade to the old 20-artifact history2 packet and leaves no output. Targeted release-control tests pass 32/32; the full focused suite passes 118 tests plus two subtests.

## 2026-07-23 — `history2` authorized production promotion

- Packet `ec3458...1c2507` expired before owner authorization could be consumed and failed closed with no remote side effect. A fresh L3 baseline still observed current `e8bea154...19086a3b`; replacement packet `91a5a914...184d717` bound the same release `ebaa5443...9df313` and was explicitly authorized.
- Permit `afa01f74...9530b755` and execution contract `8699fe35...637220b9` bound the exact archive, packet, release, expected current, data release and reviewed remote runner. The locked remote runner passed 18339 candidate smoke and changed only the Insights production container/current pointer.
- Public HTTP passed 13 routes, 8 public artifacts and 20 security 404 paths. Public Playwright passed the 26-page desktop/mobile matrix with zero browser errors, same-origin failures or external requests. Acceptance `f4faf9b9...ee3ff22` and consumption `9c0f2644...7d564fc5` both reopen successfully.
- Post-promotion current, release marker and data pointer are `ebaa5443...9df313` / `reddit_voc_release_20260723_business_history_002`. Collector and translation IDs/restarts, cron, shared Nginx, database marker and 58-container count remained stable; candidate count and 18339 listener returned to zero. No collector, cron, shared Nginx, TLS, DNS, other Docker, database, provider, schedule or live-send mutation occurred.

## 2026-07-27 — V3 canonical unresolved overlap closure

- The first focused regression failed before business logic because three JSONL files
  were parsed as one JSON document. The failure is test-fixture evidence, not proof
  that canonical relinking failed.
- Canonical fusion already accepts optional `unresolved-parent-ledger.jsonl`, but
  workbook import and its independent validator did not load that Base identity
  ledger. The asymmetric contract could classify a previously unresolved identity
  as net-new on a later workbook run.
- The selected contract treats unresolved rows as governed identity anchors without
  changing historical Base `canonical_counts`. A later row may supply a different,
  now-resolvable root post; the unresolved ledger's old missing post is not enforced
  as an immutable governed parent.
- Production, provider, remote-write and release boundaries remain outside this
  batch.
- The canonical fixture persisted mutable import comments, parent links and row
  outcomes but omitted the corresponding posts list required by its rebinding
  helper. Persisting the already-created posts list repairs fixture state without
  changing product behavior.
- The repository-local `.venv/bin/python` provides `openpyxl 3.1.5`; V3 workbook
  tests must use this interpreter instead of the dependency-incomplete system
  Python.
- The first canonical business-path execution exposed a return-type misuse:
  `canonical_comment_fullname()` already returns the canonical string, so reading
  `.fullname` from it fails before Base unresolved validation. The repair removes
  only that invalid attribute access.
- Final local evidence is two focused regressions plus five modules at `90/90`.
  Workbook import and canonical snapshot validators both pass with zero
  unaccounted identities or foreign keys. Canonical counts remain 3,494 posts,
  20,205 linked comments, 6,943 unresolved comments and 10 quarantined comments.

## 2026-07-27 — Task 14 Python suite closure routing

- The formal V3 implementation plan records Tasks 5–13 as implemented and
  independently validated. The top-level `SYS-08` Task 5 label was stale.
- Task 14 has one unchecked gate: the complete Python suite. Its recorded blocker
  is five intentional SHA-freeze mismatches in the immutable 2026-07-11 historical
  backfill release contract.
- Those hashes must not be mechanically updated. The next gate is to reproduce the
  exact current failures, then determine whether the original reviewed bytes are
  recoverable or a new review scope is justified.

## 2026-07-27 — Task 14 Python suite closure result

- Fresh full-suite evidence superseded the historical blocker hypothesis: no
  historical-backfill SHA mismatch reproduced.
- The only failure was a public projection integrity break. The active reports
  manifest and report index bound three archive files, while the destination
  archive directory was empty.
- Three independent local candidate projections supplied identical copies. Their
  bytes and SHA-256 values matched the active manifest exactly:
  `daily-2026-07-13.json` (28,205 bytes,
  `b3b1fc9d381af7453346c99aaf297c6068857007508ff30081332a6a9bf5dabc`);
  `monthly-2026-06.json` (11,225 bytes,
  `f5e90cd009a9e9fc9447102373d35deebd2dd553dfb12aa33c3f33207d33482a`);
  `weekly-2026-07-06_2026-07-12.json` (32,806 bytes,
  `8b090b4ffa5a5b9177f75b91c91cd40f534da984d469df98e6cdd6fa0273f807`).
- Restoring the exact bound artifacts preserved the manifest and history-index
  contract. The focused regression passed, followed by a zero-failure full
  Python suite.

## 2026-07-27 — PPC-03 candidate automation hardening closure

- The previously recorded `fresh_l4_authorization_required` candidate
  `3594a09e...8aa4` is historical and superseded by the later recorded L4
  production-accepted release `9c4a45f2...84cc5`. Building a fresh packet for
  the old candidate would violate the exact-current-baseline and single-valid-
  candidate contracts, so no packet or permit was created.
- Current code already enforces an exact `ROLE_SCRIPT_MAP`, rejects cross-role
  promotion and permit scripts, rejects `--runner-executable`, and binds all
  registry members through a commit marker written last.
- The newly requested cross-role regression passed `1 passed, 4 subtests
  passed`; the runner/precommit/commit-marker set passed `3 passed`; the full
  orchestrator and registry-validator focused modules passed `20 passed, 6
  subtests passed`.
- No persistent candidate, authorization packet, permit, remote write, Provider
  call, deployment, or production change was created.

## 2026-07-27 — PPC-01 business terminology closure

- Existing URL-backed theme, period, filter, evidence-open and evidence-return
  contracts were already complete. The remaining gap was visible engineering
  terminology across dashboard, search, insights, reports, workspace,
  governance and explanatory pages.
- User-facing strings no longer expose `fail-closed`, `production unchanged`,
  side-effect field assignments, `artifact release`, `evidence source`,
  `post_id`, `comment_id`, `Mock`, or raw `manifest` language in the audited
  contexts. Data fields, URL parameters and DOM contracts were unchanged.
- The new static regression initially failed on one remaining `当前 release`
  phrase in `HowItWorks`, then passed after replacing it with `当前发布版本`.
- Focused frontend evidence is `31 passed / 19 skipped` with zero failures.
  The skipped `SnapshotPages` cases remain explicit and are not counted as
  passes. Lint exited 0 with eight `only-export-components` warnings and no
  errors; TypeScript plus Vite production build completed successfully.
- The local `dist` output is validation evidence only. No candidate, packet,
  permit, remote write, Provider call, deployment, or production change was
  created.

## 2026-07-27 — PPC-02 cross-page reconciliation closure

- The previous debt was semantic rather than arithmetic: overview uses
  governed rolling 7/30/183-day windows, insights uses a governed rolling
  quarter, and reports use complete calendar day/week/month periods. Their
  values must not be forced to match when their windows differ.
- Dashboard and quarter periods use inclusive end dates, while V3 reports use
  an exclusive end date. Normalizing both to a half-open interval removes the
  boundary ambiguity without changing any governed metric.
- The stable comparison key is source snapshot + Momcozy scope +
  `post_voc+comment_context_voc` grain + normalized start/end window. The page
  name is provenance, not part of comparability.
- Each page now exposes the same reconciliation attributes and a visible rule
  that differing windows are not compared. This closes the retained PPC-02
  reconciliation debt locally without changing public data or production.

## 2026-07-27 — V2-05B real-input gate

- V3CT closed the code-path debt, not the data debt: it proves an unresolved
  comment can transition to linked when a governed imported post supplies the
  missing root identity.
- The latest local daily canonical adds 97 posts relative to the formal
  baseline, but none matches the 3,859 missing baseline parent IDs. Therefore
  zero existing unresolved comments are currently eligible for relink.
- All 6,943 baseline unresolved comment identities remain in the latest ledger;
  the latest ingest adds 10 more unresolved comments and 3 more missing parent
  IDs. The current local debt is 6,953 comments across 3,862 parents, while the
  accepted production baseline remains 6,943 until a separately governed
  candidate is authorized and promoted.
- Comment-repair probes target comment coverage under known posts and do not
  constitute parent-post evidence for these missing roots.
- The next valid input must be a source-bound parent-post snapshot with Reddit
  post identities, bytes/SHA binding, provenance, and independent validation.
  Without it, relink construction must remain blocked.

## 2026-07-27 — Current-production four-format export closure

- The task plan's `9c4a...` current-production statement had drifted. Live
  `release.json` and `current-release.json` identify `8a8a5a...5eded` /
  `reddit_voc_release_20260724_dashboard_fix_v1`, with reports dataset
  `reddit_voc_reports_20260723_v3_47c49395e785_history2`.
- A prior local loopback receipt for the same release did not satisfy the
  retained public-download debt. The new run used the existing pinned
  Playwright 0.1.17 callback and public HTTPS endpoint.
- The accepted daily report is `daily:2026-07-23:2026-07-24`, bound to report
  manifest `0a95f263...43ce7`, index `0af4521e...31b7`, and document
  `d227f27a...f623`.
- CSV contains six headers and seven business rows; PDF has two page markers;
  PPTX contains 47 package members with business content; DOCX contains 22
  package members with business content.
- `four_exports_complete=true` now applies only to current production
  `8a8a5a...5eded`. It does not apply to later unpromoted local source changes.

## 2026-07-27 — Candidate registry 当前事实（CRG-01）

- `scripts/validate_reddit_candidate_registry.py` 当前存在，且正式 registry 的现存树已通过该 validator；早期“测试存在但 validator 缺失”的记录只代表历史断点，不再是当前事实。
- 正式树包含 5 组完整 `entry/event/commit/run` 记录，validator 未发现 pending transaction、blocked run 或 failed run；当前树 SHA-256 为 `ef5c38f91801e303b91d085b58d6d80b145d7210c93c69f60764f591dc931e6b`。
- `tmp/**/candidate-registry` 属于历史 smoke/server snapshot/daily ingest 夹具，不能替代 `output/reddit-voc-candidate-registry` 的当前治理证据。
- 本地 registry correctness/governance 已闭合；剩余债务是增量自动接入的运行启用，而非 validator 或事务模型缺失。
- `registry_automation_enabled=false` 继续 fail-closed。此结论不授权 schedule、候选构建、promotion、deploy、remote write、provider、数据库或 live send 动作。

## 2026-07-27 — Candidate registry 自动接入边界（CRA-01）

- 原有 `reddit-voc-explicit-automation-v1.json` 是机器人内容分类策略，不是 candidate registry 的运行开关；本轮未复用或篡改该策略。
- 原有 orchestrator 具备 local-only、全局锁、静稳探针、allowlisted source freeze 和 append-only registry，但没有 scheduler；CRA-01 新增的 runner 只负责安全请求消费，不复制 builder 或 promotion 逻辑。
- LaunchAgent 已启用，但空 inbox 的首轮只返回 idle；“已加载调度”不等于“已创建候选”或“已集成新数据”。
- 自动请求必须同时满足 canonical bytes、受限 profile 路径、精确 profile SHA、固定安全边界和 exactly-once receipt；任一漂移在 orchestrator 前 fail closed。
- 当前没有 reviewed profile/request，故本次不产生 candidate。生产、远程、Provider、数据库与 live-send 边界保持不变。

## 2026-07-27 — Task 29 Findings

- Task 28 报告中的 12 failed 数量仍准确，但批次结构已从执行前的 9 batches + 7 missing members 变为 10 batches + 0 missing members；新 packet 必须绑定 post-Task-28 状态。
- `backfill_checkpoints.provider_request_count` 是每个 checkpoint 写入时的累计快照，不能跨 289 行求和。权威计数是 `backfill_manifests.provider_request_count=969`，并由 `backfill_provider_attempts` 的 969 行交叉验证。
- 12/12 失败均为 `comments_schema_drift`，不是网络或 Provider 传输失败。直接重试不会修复本地解析合同，因此当前不能形成可消费 Provider authorization。
- 正确下一门禁是本地 provider-free schema-shape 诊断、fixture 和 parser 回归；修复后必须重新冻结 candidate state，再决定是否申请精确调用额度。

## 2026-08-10 — P2E freshness automation findings

- August 10 is not a scheduler-missed-run problem: cron fired, but the mixed production runtime failed at the Python ABI boundary before any TikHub request.
- The daily report failure is causal fallout from the absent run row, so repairing report rendering alone cannot advance freshness.
- The smallest safe repair is a one-file backport against the exact remote `tikhub.py` preimage; replacing the whole local module would import a newer storage/runtime dependency graph.
- Source-receipt closure is a separate schema/runtime migration. Remote CLI references modules that are absent, while the old runner never builds the receipt and old raw-capture uniqueness differs from the new contract.
- HTTP/container health is insufficient evidence for data health. A public site can be healthy while `data_as_of_utc` remains stale.
- `REDDIT_VOC_TIKHUB_DAILY_REQUEST_LIMIT` is forwarded by the server wrapper but not consumed by the collector; the current request ceiling is only indirect.
- Two persistent services retain RW access to the same SQLite directory. This is not the August 10 direct cause, but remains a production fragility requiring a single-writer/RO-reader gate.

## 2026-08-10 — P2E collector-only L4 result

- The exact one-file ABI hotfix is now installed in production; direct runtime validation confirms the CLI keywords and collector keyword-only signature agree, including `raw_artifact_root`.
- This gate repairs execution compatibility and raw discovery/detail persistence only. It does not establish Provider success, August 10 data availability, source-receipt completeness or public freshness.
- Independent postflight found no database/log/cron/current/container drift, so the authorized side effect remained confined to the code file plus immutable staging/backup/receipt evidence.

## 2026-08-10 — P2E August 10 retry result

- The missing business window was recoverable from TikHub. The accepted retry contains 11 relevant posts and 43 comments with zero provider issues.
- Run status `partial` is caused by content coverage grading (7 full, 4 partial), not Provider transport failure.
- The observed 30 discovery requests, one detail batch and 11 comment requests imply 42 Provider HTTP attempts, below the conservative admission bound of 87.
- Successful database collection does not update the public site. Public `data_as_of_utc` remains `2026-08-08T23:00:00Z` until source-receipt/candidate/publication gates are separately completed.

## 2026-08-10 — P2E G3 source-receipt diagnosis

- The earlier G3 blocker was partly misclassified: the production `storage.py` text is old, but the live SQLite database already carries `UNIQUE(run_id, source_method, source_url, raw_payload_hash)` and the required tables/columns. A production database migration is unnecessary and would add risk without changing bytes.
- The actual production blocker is runtime closure: CLI already exposes source-batch commands while three modules, two profiles, runner integration and read-only storage methods are missing or stale.
- A source batch with status `partial` is still contractually consumable when its raw/entity/occurrence hashes and coverage debt are explicit. The 7 unresolved continuations must remain visible; they are not Provider transport errors.
- Installing code and proving the source receipt as separate gates would allow a half-activated runner. The frozen gate therefore treats seven-file installation plus exact read-only replay as one transaction and rolls runtime files back if replay fails.
- The frozen installer rejects preimage/absence drift, the Beijing 06:00-07:59 scheduler guard window and active Compose one-off containers. It never invokes the collector or report chain.
- Passing local shadow evidence does not prove deployed runtime or remote source-batch existence. Those remain unproven until the exact remote gate is separately authorized and executed.

## 2026-08-10 — P2E G3 first-attempt root cause

- The first authorized production transaction demonstrated that rollback works under a real smoke failure: replace targets returned to exact preimages and create-absent targets were removed.
- The smoke failure was caused by the installer contract importing `inspect_schema_state`, a symbol that does not exist in `schema_migration.py`; the source runtime itself was not reached far enough to establish incompatibility.
- Mocked success/rollback tests did not exercise the smoke import program. The corrected suite now runs that program against the full candidate and a production database snapshot, closing this test-quality gap.
- The consumed authorization does not cover a changed installer SHA or a retry. A separately frozen retry contract and fresh exact authorization are required.

## 2026-08-10 — P2E G3 production closure finding

- G3 is now closed at L4: the host runtime and already-running application container both observe the exact seven-payload closure, without restart.
- The source receipt is byte-identical to the local production-snapshot shadow, so the remote transformation is deterministic for the accepted input set.
- `partial` here means seven unresolved comment continuations remain visible; it does not mean source corruption or Provider transport failure. The batch loader accepts it as consumable.
- G3 advances source provenance only. It does not update dashboard freshness, generate comparison/trend series, complete Chinese translation, build a data candidate or switch public current.
- The next causal gate is G4 isolated candidate construction and validation from this immutable source receipt; publication must remain a later separate gate.

## 2026-08-10 — P2E G4 shadow-admission findings

- The August 10 source batch is sufficient to advance the dashboard/report date locally: the accepted daily period becomes `2026-08-10`, while the last complete weekly and monthly periods remain `2026-08-03..2026-08-10` and July 2026.
- TikHub's accepted shape permits a top-level comment with `depth=0` and null `parent_id`. Treating every null parent as unresolved is incorrect when the root `post_id` is present; normalization must be constrained to explicit depth zero so nested missing-parent debt is not hidden.
- Lowering the formal completeness gate does not require fabricating comparisons. Same-profile observed comparisons are available and explicitly labeled provisional/observed: daily has five PoP, five YoY and five six-point trend groups; weekly has 9/9/9; monthly has 10/10/10. Formal owner-attested comparison completeness remains unproven and must stay visible.
- The data/metrics/report/insights chain is not the remaining G4 blocker. All of those candidate-only validators passed, including deterministic metrics byte replay and public wrapper validation.
- Production translation sidecars are mostly reusable but are identity-and-input specific. Exact reuse covers 28,281 non-empty fields; all 64 missing non-empty fields belong to the new batch, so copying an unrelated translation or exposing English would violate the post-detail acceptance requirement.
- Therefore the only honest overall decision is blocked, even though numerical freshness and comparisons pass. The smallest next gate is a bounded translation delta for exactly 64 fields followed by deterministic merge/revalidation; promotion remains separate.
- The existing 2026-08-11 DingTalk bounded-live policy is active and the 07:00/08:00 cron path is syntactically ready. This is readiness evidence, not a guarantee of a future external event: the 07:00 Provider collection and 08:00 translation/DingTalk transports have not happened yet.

## 2026-08-10 — P2E G4T translation-delta findings

- The old Chinese sidecars were not missing; they are retained in the frozen P2D4 local data release. Reusing those exact bytes avoids an unnecessary production fetch and preserves the original translation provenance.
- The existing full-snapshot translator cannot truthfully accept the old sidecars as a checkpoint because its checkpoint contract requires per-attempt provider evidence. Synthesizing those fields would create false provenance.
- The safe bounded design is a reduced source projection: 11 parent posts plus 43 target comments produce 65 translator items, of which one post content is legitimately empty and exactly 64 require Provider translation.
- The delta merge is append-only by entity identity. It rejects any overwrite of the 3,836 old post rows or 21,569 old comment rows, any normalized-input SHA mismatch, and any extra identity.
- The fixture rehearsal proves the selection, deterministic validation, merge and final G4 accounting mechanics only. Its translations are visibly marked non-publishable and provide no semantic or production evidence.
- A real successful G4T run can close the sole G4 blocker locally, but it still cannot promote, deploy, write production data or switch public current. Those effects require later independent gates.

## 2026-08-10 — P2E G4T live-provider findings

- Provider HTTP success is not equivalent to valid model output: two HTTP-200 attempts returned invalid JSON. The bounded translator's parse/split recovery prevented either response from entering the checkpoint or merged sidecars.
- The 24-request ceiling was sufficient with 50% headroom: 12 attempts completed the exact 64-field set, and the merge accepted no extra identity.
- The two source-equal outputs are pure brand/model titles (`MomCozy Air1` and `Momcozy M5`) allowed by the frozen translation terms, not untranslated descriptive English content. The other 62 values contain CJK text and passed protected-entity validation.
- Closing translation completeness does not itself create a consumable full-site candidate. Reports, insights, base data and merged sidecars still need one coherently manifested local public candidate plus frontend/UI contract validation before any release discussion.

## 2026-08-10 — P2E G5 local public-candidate findings

- Static dataset validation alone was insufficient: the first composed candidate lacked three public-root files, the second stopped at runtime because translation usage metadata violated the frontend numeric contract, and the third failed closed because the new Insights wrapper was not in the exact allowlist.
- Each failure was preserved as a separate local candidate. The final candidate changes only the required assembly/contract bindings; translation sidecar bytes and values are unchanged by the usage repair.
- Browser validation now proves the local distribution renders all 15 audited routes on desktop and mobile, including Insights, all three report grains and a Chinese-translated post-detail dialog. This is L2 local-candidate evidence, not production publication evidence.
- The UI visibly exposes Beijing 2026-08-10 07:00 freshness and observed comparison/trend content. It does not establish an owner-attested historical comparison contract; values remain labeled observed/provisional.
- The translated Base remains intentionally non-promotable under the legacy Base validator even though the full G5 candidate is admitted by the translation-aware validator. The generic current-release builder/auditor therefore needs an explicit translation-aware promotion contract before production packaging.
- G6 should freeze the exact G5 bytes and code SHAs, inspect the production preimage read-only, and prove the deployment package can consume the translation-aware candidate. Deployment, public-current switch and DingTalk send remain later, separately authorized effects.

## 2026-08-11 — P2E G6 production-readiness findings

- The generic distribution auditor had two legacy exact-set assumptions: translated Base sidecars and the reports public-validation sidecar were rejected even when their bytes were already covered by G5. Broadening the allowlist would weaken the gate, so the repair is receipt-aware and admits only the exact reviewed G5 receipt, manifests, sidecar SHAs and policy boundaries.
- The historical dockerless builder's manifest called its label `required_ui_label`, but the value differed from the compiled UI text. Semantic similarity is insufficient for an exact release contract; a G6-specific immutable builder now binds the literal UI label and translation-admission SHA.
- Dockerless archive construction plus static-layer replay proves byte projection and target Linux/amd64 format without touching local Docker. It does not prove the image has run in production or even in a local container runtime.
- G5 remains strong on its accepted content contracts: all daily/weekly/monthly comparison and trend counts are non-zero, translations have zero missing/invalid fields, and the post-detail browser assertions include Chinese content and English original.
- G5 is nevertheless no longer the freshest available source candidate. The 2026-08-11 natural run appeared after G5 and is not in the frozen pointer. Given the product requirement that the site show today's date, artifact integrity can pass while public promotion must remain blocked.
- A code-only deployment might repair UI without claiming fresh data, but it is materially different from the frozen full candidate and requires a separately scoped authorization and its own compatibility proof. The preferred next gate is G6F: forward-port the new natural source into a local candidate, then repeat deterministic comparison, trend, translation and package admission.
## 2026-08-12 — G6R1 B5BR2 continuation checkpoint

- R4C-7 belongs to the independent `hot_article` lane and already failed closed at its sole matrix invocation; no retry is inferred from the user's continuation.
- DingTalk reconciliation remains fail closed: the observed two historical `sent` rows are message parts on the former single-destination path, not separate primary/secondary destination receipts.
- B5BR2 now contains a corrected 10-file production activation bundle and a fresh production read-only preflight receipt with status `passed_read_only`, zero blocked reasons and `dingtalk_send=false`.
- The same receipt proves production activation is still absent: no activation marker/installed owner permit/scheduled policy, old daily-current remains selected, and the fail-closed cron preimage remains active.
- No B5BR2 production execution permit or content-addressed Owner authorization draft exists in the inspected gate directory. Therefore activation remains unauthorized and no catch-up Webhook send may be attempted.
- System Python lacks `pytest`; the attempted focused test command stopped with `No module named pytest`. This is not a test failure and not a test pass. A project-managed Python runtime must be located before claiming the focused suite result.
- A locally computed bundle-tree hash is not authoritative until its ledger serialization is bound. The next draft must bind the ten individual file hashes (and, if using a tree hash, explicitly define path ordering and byte serialization).
## 2026-08-12 — B5BR2 concurrent freeze supersession and B5BR3 draft

- The earlier statement that B5BR2 had no execution permit was true for the first snapshot but was superseded seconds later by a concurrent atomic bundle freeze. The directory now contains a root-installable inactive archive, manifest and a short-lived permit.
- That short-lived file self-labels `approved_once`, but no exact content-hash Owner approval for it exists in this task. It therefore cannot be treated as authority and will not be executed.
- Production install receipt `e06169bd…bf72` proves only a root-owned inactive candidate at `/opt/reddit-voc-daily-report/control/candidates/g6r1-b5br2-20260812-r1`; it explicitly records `activation_executed=false`, `current_change=false`, `cron_change=false` and `dingtalk_send=false`.
- Project `.venv` focused B5BR2 suite passes `5/5`; the earlier system-Python result remains an environment discovery stop, not a test result.
- Pytest-generated `production-bundle/__pycache__` was moved recoverably to `/Users/pray/.Codex/release-workspaces/Reddit_VOC/g6r1-b5br2-local-test-quarantine-20260812T0948+0800/production-bundle-__pycache__`. No candidate source/evidence file was deleted.
- B5BR3 draft separates control-plane activation from external delivery. Its exact SHA is `feba95be7f5877dbf35e6d61bc4d1a16e617adcaa61a559f630ab3a0f3d20971`; live activation and catch-up send both remain blocked.
## 2026-08-12 — B5BR3 production terminal activation

- Exact Owner approval of `feba95be…0971` was consumed once. Fresh L3 at 09:55 BJT passed with the same `c8d4804a…4100` snapshot and zero blocked reasons.
- A new B5BR3 candidate preserved the B5BR2 inactive candidate and changed only fresh preflight, its bound plan and the <=15-minute permit. Executor remained `e676d7a7…702e` and the archive was `f61e3e7d…b368`.
- The single execution returned `activated_terminal`; independent verify and postflight passed. Daily current is `f67fb0b4…911`, primary cron is exact `f54ff2dd…251`, terminal marker and committed journal are root-owned mode 0444, and periodic current is unchanged.
- B5BR3 caused no DingTalk send, Provider call, production database access, container operation or periodic/public current switch. Exact upload staging was removed after postflight.
- Read-only filesystem inventory proves `daily_collect_20260812_0700` exists with collector return code 0, 84 matching artifacts and source status `partial`. It also proves there is no prepared-current and no matching 2026-08-12 cron-report line.
- Because activation happened after the 08:00/08:30 scheduled window, today's missed slot did not backfill automatically. A valid two-destination delivery cannot be authorized until a new bounded preparation-only gate produces and verifies the exact payload.

## 2026-08-12 — B5BR4A manual preparation contract

- The expired scheduled slot must not be replayed. The release exposes a separate manual `prepare` operation requiring an exact run ID and fresh one-use permit.
- The prepare container receives the production SQLite database and prior report state as read-only mounts. Its permitted writes are isolated staging, handoff, Provider-attempt evidence and an atomic `prepared-current` commit; a failed attempt commits a blocked manifest instead.
- Provider use is bounded to `deepseek-v4-flash`, 300 seconds, 45 seconds per request, at most two retries per request and at most 100 attempts for this one preparation. Cross-process retry is disabled.
- DingTalk is structurally unavailable during prepare: runtime mode is `dry_run`, live-send and failure-alert gates are zero, Webhook credentials are not mounted, and scheduled-cycle auto-send is not used.
- Non-executable draft SHA is `8118644f4cc668ec125765243049103a27e51d0c4704cb04f570bad0fb0d47cf`. It requires a new Owner digest approval before any Provider request, production read-only DB mount, container run or prepared-state write.

## 2026-08-12 — B5BR4A fresh admission attempt 1 fail-closed

- Owner approval was recorded, but the first remote observation stopped before permit installation because the ad-hoc probe assumed `/etc/cron.d/reddit-voc-daily-report` and remote `jq`; neither exists on this host.
- Verified portions still matched: current release `f67fb0b4…911`, launcher `e00628b2…5cb`, exact source manifest `c693345f…bd44`, no prepared-current, database preimage `db38305c…10df`, zero active report processes and mode-0600 non-empty DeepSeek key metadata.
- This is not a preparation invocation and made no Provider call, container run, state write or Webhook send. The retry changes approach: use the already frozen B5BR2 Python observer and its reviewed production topology instead of repeating the ad-hoc shell assumptions.

## 2026-08-12 — B5BR4A fresh admission attempt 2 topology stop

- The post-activation Python observer reached exact-image inspection but stopped read-only because `reddit-voc-report-egress` is not the production network name.
- No permit, runtime gate, container or Provider action was reached. The next probe will derive the network name from the exact production launcher and compare it to Docker's read-only network inventory before rerunning admission.

## 2026-08-12 — B5BR4A network prerequisite root cause

- The exact activated launcher hardcodes `REPORT_NETWORK=reddit_voc_report_net` and requires it to exist as an empty bridge before `docker run --pull=never`; production Docker has no network with that name.
- Release control code contains a governed bootstrap/activate path that creates this network, but the later custom B5BR3 terminal activation executor did not include that side effect. Control-plane activation therefore succeeded while the first real report preparation remains unable to start.
- The B5BR4A draft prohibits persistent network mutation. Creating the missing network under that approval would exceed authority, while launching without it would consume the prepare permit and fail before the container starts.
- B5BR4N is the minimum correction: one exact default bridge named `reddit_voc_report_net`, fresh absent preimage, empty membership, no custom IPAM/options/labels, and automatic exact removal only if its immediate postflight fails while still empty.
- B5BR4N draft SHA is `14177b4389bc346b07394ceed89bdad5bb334743104cc78fda4f28fc01dc117d`; B5BR4A approval remains unconsumed and both DingTalk destinations remain unauthorized.

## 2026-08-12 — B5BR4N executor identity correction

- Attempt 1 made no Docker network create call. Its fresh-admission code tried to hash the 0600 source manifest as `ubuntu` and received `PermissionError` before mutation.
- The correction is not a relaxed gate: execute the same one-shot host transaction as root, which is the appropriate Docker network ownership context, while retaining the exact absent preimage and all noninterference checks.

## 2026-08-12 — B5BR4N default Docker IPAM exhaustion diagnosis

- The root transaction reached its one authorized `docker network create --driver bridge reddit_voc_report_net` call and Docker rejected it without creating a network. The authorization is therefore consumed even though production state stayed unchanged.
- All pre-create CAS fields passed. Post-failure inventory shows Docker's built-in address allocation space is effectively exhausted by current networks or overlaps: 172.18–31 `/16` are occupied and the last 192.168 default `/20` conflicts with three existing `/24` networks.
- The exact daemon stderr was not retained, so `default address pool exhausted/overlapped` is an inference from complete IPAM topology, not a quoted error.
- `192.168.243.0/28` with gateway `.1` has zero overlap with 37 Docker subnets and 41 host routes, and is sufficient for the single ephemeral report container. It requires a new exact authorization because custom IPAM was explicitly prohibited by the consumed draft.
- The non-executable Retry-1 draft SHA is `0449bc35e616322098cad4243a2943245c22210f90309c2438e4a4636fc578ac`.

## 2026-08-12 — B5BR4N Retry-1 execution contract

- Exact Owner approval is bound to subnet `192.168.243.0/28`, gateway `192.168.243.1`, and one `reddit_voc_report_net` create invocation only.
- The executor independently rechecks current release, launcher, source manifest, database file hash, Docker server identity/version, lock/process/prepared/delivery preimages, exact network absence, and zero candidate overlap across current Docker IPAM plus host routes.
- If any postimage check fails after creation, only the newly created exact network may be removed while empty. Containers, images, database queries/writes, runtime gates, Provider and DingTalk remain prohibited.
- Attempt 1 stopped on the aggregate fresh-admission guard before the create call. Because `network_create_invoked=false`, the exact authorization is still available, but any retry requires a changed, evidence-backed diagnostic approach first.
- The changed diagnostic showed a race/external-state transition: the exact approved subnet and network name are now present even though this executor did not invoke create. Treat attribution and authorization consumption as `reconciliation_required` until Docker postimage and event timing are independently read back; do not retry or proceed to B5BR4A meanwhile.
- Sudo audit closes the command-attribution gap: it records the exact approved explicit-IPAM command at 11:17:32, and Docker's Created timestamp matches. Because chat-message arrival time is not available from the shell, compare this to the Owner approval statement rather than the later local receipt-generation timestamp. The safe claim is `concurrent authorized command recovered by audit`, not that this local executor performed it.

## 2026-08-12 — B5BR4A approved-draft hash defect

- The original B5BR4A draft's `immutable_inputs.report_control_sha256=ea7465aa…309` conflicts with four mutually consistent current sources: activation plan, release manifest, local frozen release and production double snapshot all equal `fcb283d6…060`.
- This is a contract-data defect, not production drift. Executing under the old digest would violate exact authorization even though the release and runtime are internally consistent.
- No prepare permit or runtime attempt material was left by the concurrent smoke. The minimum safe next gate is a JSON-patch-style correction that replaces only the bad hash and inherits every other approved B5BR4A field and hard no-send boundary.

## 2026-08-12 — Concurrent B5BR5 topology supersedes immediate B5BR4A execution

- Sudo audit shows another lane used `/home/ubuntu/.reddit-voc/report-control/runtime-hotfixes/b5br5-v5` and patched launcher v6 with authorization ID `g6r1-b5br5-supplement-prepare-20260812-r7` at 11:19.
- Shared-workspace mtimes show that lane is still developing runtime control v6, prepared-report payload v7, translation payload v8 and patched launcher v8. This is active topology drift relative to the B5BR4A-R1 contract even though daily `current` itself is unchanged.
- A second prepare would risk duplicate Provider execution and conflicting prepared-state commits. Fail closed: do not consume B5BR4A-R1 until the B5BR5 lane is terminal and its effects are read back.
- The concurrent lane is now terminal at r10 but produced ten blocked permits and at least seven restored Provider-gate journals. The absence of `prepared-current` is clear; the exact count of real Provider HTTP attempts remains unresolved until provider-attempt ledgers are read.
- Because the hotfix set and patched launcher are outside B5BR4A-R1's exact digest, the approved B5BR4A-R1 entry cannot be repurposed to retry B5BR5.
- Only r9/r10 contain actual provider-attempt JSONL. Gate journals for r4-r8 are configuration transitions, not proof of Provider HTTP; preserve that evidence distinction when counting prior attempts.
- Hash-chained r9/r10 ledgers prove 17 successful external translation attempts (5 + 12). The missing prepared commit is therefore a post-Provider orchestration/validation defect, not Provider unavailability.
- Do not spend B5BR4A-R1's Provider budget: first recover/fix the exact r10 post-processing blocker and determine whether successful outputs can be resumed without new Provider calls.
- Patched launcher v9 is an exact-byte, multi-hotfix wrapper over the active launcher. r10's 12 successful translation events prove those requests completed, but not that validation, staged bundle construction or atomic commit succeeded.
- The B5BR4A-R1 Owner approval receipt is locally valid JSON, mode `0600`, and SHA-256 `f55258d09a59b8e810d12a39774f8d77030bba96cdc154c55e43339725e9b5f8`; recording approval does not consume the execution authorization.
- The concurrent work is not an unidentified host actor: Codex task `019fe480-a37b-7032-af2d-127db68d366f` is active in the same repository and currently owns the August 12 supplemental dual-send gate. Its latest instruction is to supplement today's push only after translation verification. This strengthens the fail-closed decision not to consume B5BR4A-R1 in parallel.
- The concurrent task's latest recovered checkpoint explicitly rejects the earlier "extra response metadata" hypothesis: all 12 r10 requests completed successfully, but prepared admission stopped later at `provider_attempt_log_invalid` / deterministic translation validation. It is actively tracing the loaded payload SHA and ledger-version contract; no DingTalk semantic gate or delivery was reached.
- Read-only container replay proves payload SHA `3d32…` was actually loaded. The failure is narrowed to the final bundle returning one of several known translation-field aliases; a safe compatibility repair must accept exactly one unambiguous alias while leaving identity, type, Chinese-completeness and semantic gates unchanged. This repair belongs to B5BR5, not the already approved B5BR4A-R1 bytes.
- DWS evidence boundary remains strict: real Webhook send is an external L4 effect and requires exact content/destination parameter review immediately before execution. The present approval authorizes continuing the safe preparation/reconciliation entry, not either Webhook send.
- r11 is the first execution after the exact alias-normalization repair and is currently non-terminal. Until its external/unknown counts and complete manifest are read back, the maximum evidence grade remains `L4-authorized-live-in-progress`, not prepared success.
- r11 is now terminal `blocked`: another 12 successful external calls, zero unknowns, and no delivery. The smallest next evidence is one failing-bundle diagnostic that persists only JSON shape, field types and ID completeness—never source text, translation text, credentials or webhook data. It requires its own content-addressed authorization before any external diagnostic request.
- The diagnostic falsifies the alias/schema hypothesis: five rows used the expected `id` and `zh` string fields, but two opaque IDs were model-rewritten. Exact-ID rejection was correct. A narrow positional recovery is defensible only with exact ordered bundle cardinality and no duplicate/extra rows; content and semantic validation must still run after rebinding.
- r12 proves the one-bundle positional rule is not yet a complete repair: another 12-call run still failed translation schema before semantics, with zero unknown calls and zero sends. The minimum evidence has expanded to structure-only diagnostics for all 12 bundles, recording only keys/types/counts/known-vs-unknown IDs/parser reason and no source or translation text.
- The first all-bundle diagnostic is not reusable evidence for remaining bundles: it performed exactly one successful request, then failed local runtime admission because the latest parser SHA was not mounted. Corrective execution must be fresh and explicitly bind the parser payload; no retry may append to the old ledger.
- Full structural evidence closes the remaining parser ambiguity: 11 bundles are accepted as-is, while two rows in bundle 12 use `body` instead of the already accepted translation aliases and also contain rewritten opaque IDs. Adding only `body` to the mutually exclusive alias set is the minimal compatible repair; all content/semantic gates must execute afterward.
- r13 proves parser compatibility is closed, but not translation acceptance: exactly one of 92 fields remains non-Chinese. Preserve the 91 accepted results and repair only the rejected identity; full-field completeness and semantic checks remain downstream blockers.
- r14 is the first successful prepared commit in this lane and remains explicitly no-send. Do not promote it to DingTalk-ready until the independent acceptance binds the same artifact/outbox and verifies all 92 translations, semantic verdicts, placeholders, provider closure and human-readable Chinese payload.
- The production acceptance verifier is structurally isolated from external effects: network none plus read-only DB/prepared mounts. Its output can raise prepared evidence to independently accepted L3 read-only, but cannot itself establish DingTalk delivery.
- An auto-removed verifier container cannot supply post-hoc container exit evidence. A persisted receipt may still be authoritative if it binds the exact inputs, result and hashes; otherwise the wrapper must change (for example, retain until inspection) before a rerun. Do not rerun unchanged merely to obtain an exit code.
- The persisted acceptance receipt was sufficient to close translation quality despite the wrapper exit-code race: all 92 items and all semantic dimensions passed, both outbound parts contain Chinese, and all 25 Provider calls are terminal with zero unknown/retry. This supports prepared readiness, not delivery.
- The frozen delivery transaction preserves the required isolation: exact four-call ceiling, zero Provider, no resend and fixed existing destination IDs. A positive preflight plus terminal per-destination receipts is still required before claiming either robot delivered.
- Aggregate send failure after external start creates a reconciliation state, not a safe retry. Until each destination/part ledger and DB row is classified, supported claim is only that the live boundary was crossed; delivery may be none, partial, unknown or complete-with-summary-failure.
- Final classification is partial delivery, not unknown: both destination-specific ledgers prove part 1 sent with HTTP 200; part 2 has no start event for either; database persistence is absent. A normal retry would duplicate two already delivered messages and is forbidden.
- The recovery design must separate evidence projection from new send effects: first reconcile the two part-1 terminal ledgers into DB, then allow only the two missing part-2 calls, with per-destination one-use keys and fail-closed handling of any conflicting existing row.
- The recovery invocation itself is now consumed because it crossed its transaction boundary and failed aggregate completion. It must not be retried, even if no part-2 call occurred; only destination-specific ledgers plus DB state can determine the next safe action.
- Destination-specific evidence confirms no new sends occurred in the consumed recovery invocation; both part2 effects remain available for a fresh corrected permit. The correction must not synthesize `part_total` from a ledger field that does not exist; bind part cardinality from the already accepted outbox/manifest instead.
- SQLite ownership (`root:root 0644`) makes container-side delivery persistence structurally invalid for UID 1000. Correct separation is host-root reconciliation before/after send and a DB-free non-root sender; changing DB ownership merely to fit the container would broaden production mutation unnecessarily.
- Fresh production preflight plus isolated DB rehearsal supports executing the split transaction, but final success still requires two new terminal part2 ledgers and exact four-row DB closure; preflight alone is not delivery evidence.
- Final L4 evidence now closes both destinations: each robot accepted both parts with HTTP 200 and terminal hash-chain evidence, and the root reconciliation produced four exact DB `sent` rows sharing the accepted outbox. Human reading remains unobservable.
- B5BR4A-R1 was never consumed and is superseded by the completed B5BR5 lineage. It must not be executed later because doing so would duplicate already completed preparation/provider work.
- DWS Webhook transport contract is now reconfirmed from the product reference: `send-by-webhook` requires exact token, title and text; Markdown must contain real U+000A line breaks, and any at-target flags must have matching text placeholders. These parameters must be reviewed against the frozen outbox before either live call.
