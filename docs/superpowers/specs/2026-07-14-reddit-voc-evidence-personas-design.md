---
title: Reddit VOC 高价值标签修复与证据型聚合画像设计
doc_type: design_spec
status: implemented
implementation_status: complete
created: 2026-07-14
updated: 2026-07-14
owner: codex
decision: evidence_cohort_personas_with_synthetic_editorial_avatars
production_boundary: production_unchanged
provider_call: false
database_write: false
live_send: false
webhook_send: false
deploy: false
schedule_change: false
git_commit: false
---

# Reddit VOC 高价值标签修复与证据型聚合画像设计

## 1. 决策

采用用户于 2026-07-14 批准的方案 A：先修复四个 taxonomy 已适配、可通过
确定性关系规则收紧的 held 标签，再从通过语义门禁的标签构建证据型聚合画像。
画像配套本地、版本化、确定性绘制的合成编辑插画头像，但不对应、模仿或推断任何
Reddit 真实用户。为严格保持 `provider_call=false`，本批头像不调用外部图像模型，
也不将本地原创矢量资产误标为 AI 生成。

画像不是“一个用户的一行数据”，而是“一个经过门禁的内容证据 cohort”。首版只
发布当前证据已支持的两个画像；修复标签只有通过新的零重叠样本门禁后，才能产生
新的画像或进入现有 Insights 与报告。

UI 继续使用当前代码库的 Momcozy 设计语言，在 `/dashboard/insights` 的已晋级信号
与字典参考维度之间增加聚合画像模块。不修改已经验收的日报、周报、月报布局，
不启用旧 `audienceMock.ts` 中的年龄、设备、妈妈阶段、画像比例或行为 Mock。

## 2. 方案比较

### 2.1 方案 A：证据型聚合画像（采用）

- persona 只由当前 Insights `promoted_tag_ids` 和可回溯内容证据生成。
- 公开画像展示内容实体、帖子、评论、线程和不同伪名参与者计数。
- 每个头像是版本化的合成角色插画，并明确标注“非真实 Reddit 用户”。
- held 标签必须先经过专属 predicate、回归集、零重叠新样本和挑战样本门禁。

优点是可复算、可审计、能严格区分字典参考与真实证据；代价是首版画像数量少，
且不会为了填满 UI 而推断人口属性。

### 2.2 方案 B：直接将字典映射转成营销画像（不采用）

把 `consumer_card`、AIPL、story line 等一对一映射成多个营销 persona，能快速生成
更多卡片，但这些字段描述标签治理关系，不是用户级画像证据。该方案会把字典设计
意图冒充真实人群，不符合当前数据边界。

### 2.3 方案 C：按 Reddit 作者生成个体画像（不采用）

按 `author_pseudonym` 汇总发帖、评论和兴趣可形成更丰富的个体档案，但当前产品不
需要用户追踪，而且会放大重识别和敏感状态推断风险。作者伪名只能在构建内存中用于
聚合去重，不进入公开 `persona_tags`，也不提供作者级页面。

## 3. 当前证据基线

基础数据固定为 `reddit_voc_site_snapshot_20260714_v1`：

- 221 个唯一帖子；
- 4,549 条关联评论；
- 4,435 条进入 VOC 指标的评论；
- 18 条隔离评论；
- 三个来源层为 `tencent_production_primary`、`historical_canonical`、
  `imported_archive`。

当前 Insights 为 `reddit_voc_insights_20260714_v1`。已复核 10 个高频 aspect 标签和
100 条分层样本，仅以下两个标签晋级：

| 标签 | 内容实体 | 帖子 | 评论 | 不同伪名参与者 | 线程 |
|---|---:|---:|---:|---:|---:|
| `L0-GEN-075 工作场景` | 57 | 11 | 46 | 51 | 31 |
| `L0-GEN-103 强烈推荐` | 52 | 3 | 49 | 48 | 33 |

两标签在同一内容实体上的共现为 0，不同伪名参与者交集为 1。因此不能合并成
“职场推荐型妈妈”等复合画像。“不同伪名参与者”也不等于真实独立用户，只是快照
内的聚合质量辅助指标。

标签字典 `dim_tag_v6.3_final.csv` 共 2,346 行，`consumer_card`、`aipl_node`、
`story_lines`、`intent_type`、`problem_type` 五列均非空；它们可以作为 persona 的
字典参考维度，但不能单独创建 persona。

## 4. 四个高价值 held 标签修复

### 4.1 本批范围

本批只处理：

1. `L2-PUMP-016 法兰尺码不合适`；
2. `L0-CHL-003 物超所值`；
3. `L2-PUMP-030 出奶量不输主泵/竞品`；
4. `L2-PUMP-007 考虑购买配件`。

原始 CSV 字典保持 byte-unchanged。新增 Reddit 专属语义 predicate 覆盖层，并同时
绑定 dictionary SHA-256 和 base manifest SHA-256。覆盖层只收紧 Reddit 来源的
assignment，不改变标签名称、定义、部门、AIPL 或其他治理字段。

以下标签不在本批自动修复：

- `L0-GEN-164 功能需求驱动购买`：泛搜索和购买动机关系仍需第二批设计；
- `L0-SVC-010 客服体验`：定义限定 Zendesk，需要来源治理决策；
- `L0-GEN-020 无线免提`：字典定义与吸奶器 hands-free 场景不一致，应另行评估
  `L1-PUMP-024 可穿戴解放双手`；
- `L0-SVC-019 正面反馈`：礼貌致谢污染严重，需要标签拆分或停用决策。

### 4.2 Predicate 状态机

四个标签采用相同流程：

```text
lexical_candidate
  -> sentence_evidence_location
  -> tag_specific_relation_predicate
  -> confirmed | rejected | needs_review
```

每个 assignment 必须输出稳定 reason code、触发短语、句子范围和 predicate version。
`rejected` 与 `needs_review` 不能进入 Insights、报告或 persona，也不能静默消失，必须
保留在修复审计产物中。

### 4.3 专属规则

#### `L2-PUMP-016 法兰尺码不合适`

- 明确接受 `wrong flange size`、`flange too small/big`、`flange doesn't fit` 等直接
  尺码或贴合失败表达；
- `elastic nipples` 必须与 pain、pinching、poor/no output、still full、wrong size、
  incompatible 等负面结果位于同句或相邻句；
- 仅有解剖描述、怀疑或明确 `works well` 时不得 confirmed。

#### `L0-CHL-003 物超所值`

- 接受明确正向价格价值断言，如 `worth the money`、`good for the price`、
  `excellent value`；
- 拒绝问句、`if/whether`、否定、仅有促销，以及时间、精力或痛苦是否“值得”等
  非价格语境；
- 缺少价格或商品价值对象时进入 `needs_review`。

#### `L2-PUMP-030 出奶量不输主泵/竞品`

- 同句必须包含 Momcozy 或明确 Momcozy 型号、竞品或主泵、output/emptying 指标，
  以及 Momcozy 相同或更好的比较方向；
- 缺品牌主体、代词前件、比较对象或比较方向时不得 confirmed；
- 多品牌文本必须保存主体与比较方向，不得把竞品优于 Momcozy 反向计入。

#### `L2-PUMP-007 考虑购买配件`

- 同句必须存在第一人称或明确购买主体、主动意图动词以及配件名；
- 拒绝既往购买、保险免费供应、建议他人购买、纯可用性描述和普通配件提及；
- 仅表达配件可得性担忧但没有购买意图时进入 `needs_review`。

### 4.4 新样本门禁

现有 80 条 held 样本已经用于发现错误，只能作为回归集，不能再次充当独立验证：

1. 旧样本回归必须证明已知错误不再 confirmed，已知歧义保持 `needs_review`；
2. 每个修复标签从 predicate 后候选中抽取零重叠新样本：候选不少于 30 条时抽
   30 条，不足 30 条时全量复核；
3. 新样本按帖子/评论、三个来源层和触发短语分层；
4. 每个标签另有至少 20 条 rejected challenge cases，覆盖问句、否定、过去购买、
   错误品牌、错误比较方向和缺主体；
5. 晋级必须同时满足：样本 precision `>= 0.90`、taxonomy fit `>= 0.90`、
   ambiguous rate `<= 0.10`、Wilson 95% 下界 `>= 0.75`、governance status `fit`；
6. 本批复核者仍为 Codex 辅助语义审计，必须保留
   `independent_human_review=false`；
7. 任一标签未过门禁则继续 held，不影响其他标签独立晋级。

## 5. 画像数据产品

### 5.1 数据集身份

画像数据集固定使用版本化目录，例如：

```text
reddit_voc_personas_20260714_v1/
  manifest.json
  personas.json
  persona-tags.json
  assets/
    persona-work-scenario.svg
    persona-explicit-advocate.svg
```

manifest 必须绑定：

- 基础快照版本和 manifest SHA-256；
- 实际消费的 Insights 版本和 manifest SHA-256；
- 标签字典版本和 SHA-256；
- 通过 `tag_repair` binding 绑定 predicate/修复数据集的版本与 manifest SHA-256；
- `personas.json`、`persona-tags.json` 和每个头像文件的 byte size、SHA-256、
  media type；
- 画像、隐私、生产与副作用边界。

### 5.2 `dim_persona_v1`

`personas.json` 中每行代表一个 evidence cohort：

```json
{
  "persona_id": "PER-SCENE-WORK-001",
  "persona_kind": "content_evidence_cohort",
  "name_cn": "工作场景需求群",
  "status": "promoted",
  "definition": "内容中出现并通过语义门禁的明确工作场景需求",
  "source_tag_ids": ["L0-GEN-075"],
  "evidence_logic": "ANY promoted tag",
  "metrics": {
    "matched_entities": 57,
    "matched_posts": 11,
    "matched_comments": 46,
    "distinct_pseudonyms": 51,
    "threads": 31
  },
  "dictionary_reference": {
    "consumer_card": "场景任务卡",
    "aipl_node": "L1",
    "story_lines": ["场景使用冲突"],
    "intent_type": ["产品咨询"],
    "problem_type": ["产品性能"]
  },
  "avatar": {
    "asset_path": "assets/persona-work-scenario.svg",
    "asset_sha256": "manifest-bound-sha256",
    "media_type": "image/svg+xml",
    "width": 512,
    "height": 512,
    "synthetic": true,
    "real_user_image": false,
    "derived_from_reddit_media": false,
    "identity_claim": false,
    "alt_text": "工作场景需求群的合成编辑插画，非真实用户"
  },
  "coverage_status": "observed_corpus_only",
  "population_share_supported": false
}
```

首版至少包含：

- `PER-SCENE-WORK-001 工作场景需求群`；
- `PER-BEHAVIOR-ADVOCATE-001 显式推荐表达群`。

修复标签只有晋级后才能定义新 cohort。不得预先创建空画像，也不得把多个无共现
证据的标签拼成复合画像。

### 5.3 `persona_tags`

`persona-tags.json` 粒度为 `persona_id x evidence_id`：

```json
{
  "persona_id": "PER-SCENE-WORK-001",
  "evidence_id": "post:stable-id",
  "entity_type": "post",
  "entity_id": "stable-id",
  "post_id": "stable-id",
  "tag_id": "L0-GEN-075",
  "evidence_keywords": ["at work"],
  "source_stratum": "tencent_production_primary",
  "assignment_status": "rule_match_under_promoted_tag",
  "semantic_gate_scope": "tag_level_stratified_sample",
  "human_validated_assignment": false
}
```

公开 `persona-tags.json` 不包含 `author_pseudonym`、原始用户名、邮箱、电话、个人资料
URL 或其他用户级标识。构建过程可以在内存中用伪名去重并输出不同伪名数量，但不能
写出伪名列表或作者到 persona 的映射。

### 5.4 最小群体阈值

- 公开 persona 至少需要 10 个不同非空伪名参与者；
- 低于阈值时 persona 状态为 `insufficient_sample`，不显示头像排行或份额；
- 当前最近 30 天只有工作场景 5 个、显式推荐 3 个内容实体，不支持近期画像份额；
- 全语料 persona 只能表述为“当前已观察语料中的内容角色”，不能表述为总体人群。

## 6. 头像资产治理

### 6.1 视觉方向

头像采用温暖、克制的编辑插画风，与现有暖珊瑚、浅桃、白色卡片设计语言一致：

- 1:1 正方形，目标尺寸 512 x 512；
- 无文字、无品牌 Logo、无 Reddit 标识；
- 工作场景群以桌面、电脑、通勤包、时钟等抽象场景元素区分；
- 显式推荐表达群以对话气泡、星标、社区分享等抽象元素区分；
- 后续画像通过场景物件和构图区分，不通过种族、年龄、健康状态或母乳喂养阶段
  刻板化；
- 不使用逼真照片、Reddit 用户照片、帖子媒体、婴儿照片或可识别真人肖像。

### 6.2 资产边界

基础快照没有用户头像字段。`media_urls` 是帖子附件，不能作为头像。每个头像必须：

- 由本地确定性矢量插画流程创建，并作为版本化静态资产保存；
- 在 manifest 中记录 SHA-256 和 media type；
- 固定 `real_user_image=false`、`derived_from_reddit_media=false`、
  `identity_claim=false`；
- UI 同时展示可见 badge：`合成头像 · 非真实 Reddit 用户`；
- 缺失、远程 URL、路径越界或 SHA 不匹配时不加载图片，改用中性占位，同时保留
  已验证的文字画像和资产错误提示。

## 7. UI 接入

### 7.1 位置与信息层级

在 `/dashboard/insights` 中按以下顺序呈现：

1. 数据版本与语义门禁概览；
2. 已通过门禁的真实信号；
3. 证据型聚合画像；
4. 字典参考维度；
5. held 标签诊断；
6. 门禁与运行边界。

报告页不加入画像，避免 24 小时小样本被过度解释，也不改变日报、周报、月报布局。
`/dashboard/analytics` 可在后续增加一个只读摘要链接，本批不重新激活旧
`AudiencePersona.tsx`。

### 7.2 画像卡

- 响应式为移动端 1 列、平板 2 列、桌面最多 3 列；只有两个 persona 时保持两列；
- 头像 80 x 80，圆形裁切和浅桃 ring；
- 显示画像名称、讨论角色描述、合成头像 badge；
- 显示内容实体、帖子/评论、线程和不同伪名参与者，并解释分母；
- 展示 3 至 4 个有证据的讨论情境、意图或问题标签；
- 底部“查看证据”进入现有搜索页，不展示作者级详情；
- 不显示年龄、设备、真实职业、妈妈阶段、品牌忠诚、画像占比或人口分布。

### 7.3 可访问性

- 使用真实 `<img>`，固定 `width/height`，并设置 `loading="lazy"`、
  `decoding="async"` 和说明合成属性的 alt text；
- 合成属性必须是页面可见文本，不能只放在 alt 或 tooltip；
- 按钮和证据入口最小 44 x 44px，并提供 `focus-visible`；
- 装饰性图标 `aria-hidden="true"`；
- 避免 `transition-all`，支持 `prefers-reduced-motion`；
- 小字使用至少 `#6B6B6B` 级别对比度，不使用白字叠加浅珊瑚底。

## 8. 加载与错误处理

前端画像加载沿用现有 snapshot/Insights 服务：

1. 加载 persona manifest；
2. 校验 schema、dataset version、基础/Insights/字典/predicate hash binding；
3. 加载 `personas.json` 和 `persona-tags.json`；
4. 使用 Web Crypto 校验 JSON 与头像 SHA-256；
5. 校验 promoted tag、计数、最小群体、隐私和头像边界；
6. 数据契约失败时整个画像模块 fail closed，不回退 `audienceMock`；
7. 单个头像失败时只阻止该图片，显示中性占位和资产错误，不把未验证图片展示出来。

禁止远程头像 URL、帖子媒体 URL、data URL、路径穿越和未列入 manifest 的资源。

## 9. 腾讯生产实时同步准备边界

本批只把 tag repair 和 persona 生成器设计为版本化输入接口，使未来可消费新的基础
快照；并为腾讯只读导出定义 manifest/hash/schema 门禁。不在本批执行：

- 生产数据库写入或 migration；
- 生产实时连接切换；
- cron/launchd 调度修改；
- Provider、TikHub、DeepSeek 或其他外部调用；
- Webhook、DingTalk 或真实发送；
- 部署、服务重启、Git commit、Git push 或 merge。

未来实时接入必须作为单独授权批次，先完成只读 freshness/coverage 对账，再决定增量
同步、归档和页面切换。

## 10. 验证与完成标准

### 10.1 标签修复

- 原字典 SHA 和基础 manifest SHA 精确绑定；
- 四个 predicate 的旧样本回归、新样本和 challenge cases 全部可复现；
- 晋级状态逐标签独立计算，未通过标签保持 held；
- 任何 taxonomy 改义标签不得通过本覆盖层静默晋级；
- 两种不同 `PYTHONHASHSEED` 生成相同字节和 manifest hash。

### 10.2 Persona 数据

- 当前基线严格复算两个 persona 和 109 条 persona assignment；
- 每个 `(persona_id, evidence_id)` 唯一并能回连基础快照；
- 评论 assignment 必须 `include_in_voc_metrics=true`；
- 实体、帖子、评论、线程和不同伪名数量独立复算一致；
- held 标签注入、未知 tag、`consumer_card` 冒充 `persona_id` 时验证失败；
- 公开文件不包含作者伪名、用户名、联系方式或用户 profile 字段；
- 禁止人口统计、真实头像、设备、品牌偏好、市场份额、ROI 和总体人群占比；
- 每个头像存在、路径受限、文件 SHA 匹配且三项身份边界均为 false。

### 10.3 前端

- `/dashboard/insights` 在真实信号和字典参考之间展示画像模块；
- 缺文件、篡改 hash、held 标签和隐私字段注入全部 fail closed；
- 头像损坏显示中性占位，不加载未验证或远程图片；
- 页面不导入 `audienceMock.ts` 或旧画像 Mock；
- 桌面、平板、390px 移动端无溢出，键盘焦点与触控目标通过；
- 页面加载和重新加载只有静态 GET，无 POST、Webhook、发送或写请求；
- 前端定向测试、全量 Vitest、lint、build、HTTP smoke 和浏览器 console 检查通过。

## 11. 运行边界

```text
delivery_mode=versioned_static_evidence_personas
production unchanged
provider_call=false
database_write=false
live_send=false
webhook_send=false
deploy=false
schedule_change=false
git_commit=false
git_push=false
git_merge=false
independent_human_review=false
consumer_card_is_reference_not_persona_id=true
real_user_image=false
derived_from_reddit_media=false
identity_claim=false
population_share_supported=false
```

## 12. 实施结果（2026-07-14）

方案 A 已按本设计完成本地静态实现：

- 标签修复层共处理 243 条 lexical candidates，得到 20 `confirmed`、
  92 `needs_review`、131 `rejected`；旧 80 条审计样本回归及四个标签各 20 条
  challenge cases 均通过。
- 四个目标标签的新样本虽逐条复核，但 Wilson 95% 下界或样本量不足，最终为
  `0 promoted / 4 held`。因此没有生成 Insights/reports v2，也没有放宽门禁。
- persona 数据集发布 2 个 evidence cohorts、109 条 assignment；工作场景群为
  57 个内容实体（11 帖、46 评论、51 个不同伪名、31 线程），显式推荐表达群为
  52 个内容实体（3 帖、49 评论、48 个不同伪名、33 线程）。
- 两张 512 x 512 本地原创 SVG 插画已经 manifest hash 绑定，并在 UI 明示
  `合成头像 · 非真实 Reddit 用户`。
- `/dashboard/insights` 已接入画像模块；日报、周报、月报继续使用既有
  `reddit_voc_reports_20260714_v1`，未修改报告页布局或切换数据版本。

本地证据：标签/画像专项 Python 测试 `67 passed`；基础、Insights、reports、
tag-repair、persona processed/public 五类独立 validator 均为 `passed`；前端全量
Vitest `104/104`、build 通过，lint 为 0 error（5 个既有
`react(only-export-components)` warning）；Chromium 桌面与 390px 移动端无横向
溢出，console 0 error/0 warning，画像与报告资源均为本地 GET 200。

最新全仓 Python 回归为 `743 passed / 4 failed`。其中三个稳定失败来自历史 backfill
release manifest 与当前 `backfill_cli.py`、`backfill_seed.py`、`tikhub.py` 文件哈希
不一致；本批未修改历史清单以掩盖该漂移。另一个 full-suite-only 失败为 fake-host
launcher 的 `inherited_lock_fd_invalid`，精确测试隔离复跑 `1 passed`，目前只能记录为
顺序/环境相关的未定根因，不能表述为已修复。

独立合同审查发现的三项 P2 已修复：persona 回执现绑定 persona/base/
Insights/config/tag-repair 五个 SHA；builder 与独立 validator 会完整校验可选
tag-repair 依赖；tag-repair 的每个复核样本必须存在显式 override，默认决策不能替代
逐条复核。新增的系统性篡改测试已包含在上述 67 项专项测试中。
