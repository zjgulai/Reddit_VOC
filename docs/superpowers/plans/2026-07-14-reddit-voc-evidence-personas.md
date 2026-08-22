---
title: Reddit VOC 高价值标签修复与证据型聚合画像实施计划
doc_type: implementation_plan
status: complete
created: 2026-07-14
updated: 2026-07-14
owner: codex
design_spec: ../specs/2026-07-14-reddit-voc-evidence-personas-design.md
production_boundary: production_unchanged
provider_call: false
database_write: false
live_send: false
webhook_send: false
deploy: false
schedule_change: false
commit: false
---

# Reddit VOC 高价值标签修复与证据型聚合画像实施计划

## 1. 目标

在不修改 `dim_tag_v6.3_final.csv`、不覆盖既有基础/Insights/reports v1 数据集的
前提下，完成两条相互隔离但可组合的本地静态管线：

1. 为四个高价值 held 标签增加 Reddit 专属关系 predicate、回归和新样本门禁；
2. 从实际通过门禁的标签生成 `dim_persona_v1 + persona_tags`，配套版本化合成头像，
   并在 `/dashboard/insights` 激活真实聚合画像。

生成器全部接收版本化快照目录参数，为未来腾讯只读快照刷新保留输入接口。本计划
不连接实时生产、不修改数据库、调度、发送或部署。

## 2. 完成标准

- 原始字典文件 SHA-256 不变，基础快照、Insights v1、reports v1 均不被覆盖。
- 四个目标标签分别输出 `confirmed / rejected / needs_review` 及稳定 reason code。
- 旧 80 条 held 样本只作为回归，新验证样本与旧样本零重叠。
- 修复标签逐标签独立过门禁；未通过者继续 held，不能进入 persona 或报告。
- 画像数据集初始严格包含 2 个 evidence cohort 和 109 条 assignment；若修复标签通过，
  仅按已审核 persona 定义增加 cohort。
- 公开 persona 文件不包含作者伪名、用户名、联系方式、人口统计或个人级画像。
- 每个 persona 使用本地、manifest 绑定、确定性绘制的合成插画头像，并显示非真实
  用户标识；不调用外部图像模型。
- `/dashboard/insights` 接入真实画像，不导入 `audienceMock.ts`，报告 UI 保持原布局。
- Python 单元/篡改/确定性测试、独立 validator、前端测试、lint、build、HTTP smoke、
  桌面和移动浏览器 QA 通过。
- 全过程保持 `production unchanged`、`provider_call=false`、
  `database_write=false`、`live_send=false`、`webhook_send=false`、`deploy=false`、
  `schedule_change=false`、`commit=false`。

## 3. 实施顺序

### Task 1：冻结输入与 RED 测试

输入：

- `dim_tag_v6.3_final.csv`；
- `data/processed/reddit_voc_site_snapshot_20260714/`；
- `data/processed/reddit_voc_insights_20260714/`；
- `docs/analysis/reddit-tag-semantic-audit-20260714/review-sample.json`；
- `docs/analysis/reddit-tag-semantic-audit-20260714/review-decisions.json`。

先新增失败测试，覆盖：

- 四个标签的 confirmed/rejected/needs_review 关系案例；
- 问句、否定、过去购买、错误品牌、比较方向和缺主体；
- predicate 配置未绑定字典/base SHA；
- held assignment 注入 persona；
- persona 输出作者伪名、年龄、设备或远程头像；
- 头像路径越界、文件缺失、SHA 篡改；
- 两个不同 `PYTHONHASHSEED` 产生不同输出。

### Task 2：实现 Reddit 标签 predicate 覆盖层

本批只覆盖以下四个已批准目标，不扩大标签范围：

- `L2-PUMP-016` 法兰尺码不合适；
- `L0-CHL-003` 物超所值；
- `L2-PUMP-030` 出奶量不输主泵/竞品；
- `L2-PUMP-007` 考虑购买配件。

新增：

- `config/tagging/reddit-semantic-predicates-v1.json`：版本、目标标签、允许关系、排除
  关系、reason code、字典/base SHA 绑定；
- `src/reddit_voc/reddit_semantic_predicates.py`：句子定位、predicate 状态机和四个标签
  的纯函数实现；
- `tests/test_reddit_semantic_predicates.py`：直接关系测试、回归和配置边界。

不修改 `TagDictionary.extract()` 的既有 v1 行为。覆盖层消费基础快照已有 lexical
assignment，保证 v1 快照可继续复算，并避免全库标签语义被本批意外改变。

### Task 3：构建标签修复审计数据集

新增：

- `scripts/build_reddit_tag_repair_snapshot.py`；
- `scripts/validate_reddit_tag_repair_snapshot.py`；
- `tests/test_reddit_tag_repair_snapshot.py`；
- `data/processed/reddit_voc_tag_repair_20260714/`；
- `docs/analysis/reddit-tag-repair-20260714/`。

数据集至少包含：

```text
manifest.json
assignments.json
regression-audit.json
review-sample.json
challenge-cases.json
semantic-audit.json
validation-receipt.json
```

构建器职责：

1. 从基础帖子/评论定位四个标签的 lexical candidates；
2. 执行 predicate 并保存全部三态结果；
3. 对旧样本生成回归对账；
4. 使用稳定哈希生成零重叠新样本；
5. 生成每标签至少 20 个 challenge cases；
6. 读取版本化 review decisions，计算新门禁；
7. 逐标签发布 `promoted_after_repair` 或 `held_after_repair`。

review decisions 由 Codex 基于完整公开上下文填写，必须写明
`independent_human_review=false`。生成样本前不预设四个标签一定晋级。

### Task 4：构建证据型 persona 数据集

新增：

- `scripts/build_reddit_personas_snapshot.py`；
- `scripts/validate_reddit_personas_snapshot.py`；
- `tests/test_reddit_personas_snapshot.py`；
- `data/processed/reddit_voc_personas_20260714/`。

生成器输入：

- 基础 snapshot 目录；
- 实际消费的 Insights 目录；
- 可选 tag-repair 目录；
- 本地头像资产目录。

输出：

```text
manifest.json
personas.json
persona-tags.json
assets/
validation-receipt.json
```

首版 persona 固定为：

- `PER-SCENE-WORK-001`，来源 `L0-GEN-075`；
- `PER-BEHAVIOR-ADVOCATE-001`，来源 `L0-GEN-103`。

修复标签只有同时满足 `promoted_after_repair` 和显式 persona 定义时才能加入。不得把
每个 promoted 标签自动等同于 persona，也不得无证据组合标签。

独立 validator 从基础实体重算 assignment、帖子/评论/线程、不同伪名数量、最小群体
阈值、字典参考和所有 hash；公开输出禁止作者标识。

### Task 5：生成和治理合成头像

为实际发布的 persona 生成 1:1、512 x 512 的温暖编辑插画：

- 工作场景需求群：桌面、电脑、通勤包、时钟等抽象元素；
- 显式推荐表达群：对话气泡、星标、社区分享等抽象元素；
- 其他画像只在数据门禁通过后生成；
- 无文字、Logo、Reddit 标识、婴儿照片或可识别真人；
- 每个资源复制到 persona 数据集 `assets/`，记录 SHA、media type 和身份边界。

头像生成结果必须人工可见检查构图，但不被当作真实数据证据。缺失或不合格头像不能
通过数据集 validator。

### Task 6：复制静态数据并接入前端

新增：

- `ref/UI/momcozy-reddit-workbench/public/data/reddit-voc/reddit_voc_personas_20260714_v1/`；
- `src/features/redditSnapshot/personas.ts`；
- `src/features/redditSnapshot/useRedditPersonas.ts`；
- `src/features/redditSnapshot/__tests__/personas.test.ts`；
- `src/components/personas/AggregatePersonaPanel.tsx`；
- `src/components/personas/AggregatePersonaCard.tsx`。

修改：

- `src/pages/SnapshotInsights.tsx`：在真实信号和字典参考维度之间插入画像面板；
- `src/pages/__tests__/SnapshotPages.test.tsx`：增加画像数据、边界和头像测试。

前端服务必须：

1. 校验 manifest 和基础/Insights/字典/predicate 绑定；
2. 对 JSON 和头像执行 SHA-256；
3. 拒绝 held/未知标签、隐私字段、远程 URL、data URL、路径越界和人口属性；
4. 整体数据异常时 fail closed，不回退 `audienceMock`；
5. 单个头像异常时不展示图片，使用中性占位并显示资产错误。

### Task 7：条件化接入修复后的 Insights 与报告

只有至少一个修复标签通过新门禁时才执行：

1. 生成新的 Insights 数据集版本，不覆盖
   `reddit_voc_insights_20260714_v1`；
2. 让新 signal 的计数严格来自 predicate-confirmed assignments，而不是原始 lexical
   population；
3. 生成新的 reports 数据集版本，并保持 v1 报告可回滚；
4. 更新前端静态 manifest binding；
5. 重跑报告 validator，保证 held 标签仍为 0。

如果四个标签均未通过，新 Insights/reports 版本不生成；persona 继续只消费现有两个
promoted 标签，状态如实记录为 `tag_repair_completed_no_new_promotions`。

### Task 8：腾讯只读快照兼容性准备

不连接生产，只验证 persona/tag repair 生成器对一个新的版本化 snapshot 目录无硬编码
依赖：

- 输入路径必须由 CLI 参数提供；
- manifest/schema/hash 不一致时 fail closed；
- freshness 与 collection coverage 必须显式输入，不能从当前时间推断；
- 无数据库 DSN、SSH、Provider、调度或发送依赖；
- 形成后续生产只读刷新所需的输入字段和停止条件记录。

### Task 9：全量验证与项目记录

数据层：

- predicate、repair、persona 定向测试；
- 基础、Insights、reports 既有回归；
- tag-repair 与 persona 独立 validator；
- 两种 `PYTHONHASHSEED` 字节稳定性；
- public copy 与本地产物 byte diff；
- 隐私/禁止字段/远程资产扫描。

前端：

- persona loader 与页面定向测试；
- 全量 Vitest、lint、TypeScript production build；
- preview route、manifest、JSON 和头像 HTTP 200；
- Chromium 桌面、平板和 390px 移动端视觉/交互 QA；
- console 0 errors，网络只出现静态 GET。

记录：

- 更新设计稿实施状态；
- 更新本计划实际结果；
- 更新 `.codex/context-pack.md` 与 `.kiro/plan/progress.md`；
- 如实记录未晋级标签、未验证项与生产边界。

## 4. 验证命令基线

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. uvx --from pytest pytest \
  tests/test_reddit_semantic_predicates.py \
  tests/test_reddit_tag_repair_snapshot.py \
  tests/test_reddit_personas_snapshot.py -q

python3 scripts/validate_reddit_tag_repair_snapshot.py \
  --repair-dir data/processed/reddit_voc_tag_repair_20260714 \
  --snapshot-dir data/processed/reddit_voc_site_snapshot_20260714 \
  --policy config/tagging/reddit-semantic-predicates-v1.json \
  --legacy-sample docs/analysis/reddit-tag-semantic-audit-20260714/review-sample.json \
  --legacy-decisions docs/analysis/reddit-tag-semantic-audit-20260714/review-decisions.json \
  --review-decisions docs/analysis/reddit-tag-repair-20260714/review-decisions.json

python3 scripts/validate_reddit_personas_snapshot.py \
  --personas-dir data/processed/reddit_voc_personas_20260714 \
  --snapshot-dir data/processed/reddit_voc_site_snapshot_20260714 \
  --insights-dir data/processed/reddit_voc_insights_20260714 \
  --config config/personas/reddit-voc-evidence-personas-v1.json \
  --avatar-dir docs/superpowers/assets/reddit-voc-evidence-personas \
  --tag-repair-dir data/processed/reddit_voc_tag_repair_20260714 \
  --tag-repair-policy config/tagging/reddit-semantic-predicates-v1.json

npm test -- --run
npm run lint
npm run build
```

最终命令以实际通过的 CLI 参数为准；不得通过跳过、删除或放宽测试制造绿色结果。

## 5. 风险与停止条件

- 新样本不足或门禁失败：标签保持 held，不降低阈值。
- Predicate 需要修改标签定义或来源适用范围：停止并请求 taxonomy 决策。
- Persona 需要人口统计、作者追踪或敏感状态推断：拒绝该字段或 cohort。
- 头像看起来像真实用户、含品牌/Reddit 标识或使用帖子媒体：拒绝资产并重生成。
- 既有 v1 数据集 hash 变化：停止，检查是否发生覆盖。
- 同一验证路径连续三次失败：停止局部 patch，重新审查数据流。
- 任何步骤需要生产连接、数据库写入、外部 Provider、发送、部署、调度修改或 commit：
  停止并重新取得精确授权。

## 6. 当前执行边界

```text
evidence_grade=local_implementation_validated
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
```

## 7. 实际完成结果（2026-07-14）

- Task 1-6、8-9 已完成；Task 7 的条件不成立，按设计未执行数据版本切换。
- tag repair manifest SHA-256：
  `99dfb8bc7605ae2069822a4df99dd06b7832a4783c73c92e9d002b3e546ec8f1`。
  243 条候选分为 20 confirmed / 92 needs_review / 131 rejected；最终
  `completed_no_new_promotions`，四个目标标签全部保持 held。
- persona manifest SHA-256：
  `a06968e0bcb8b6a7b596e61b260665c5153914494cb98bbef7caeb361aa5bf41`。
  2 个 cohort、109 条 assignment，public copy 与 processed copy 业务文件一致。
- 已在 `/dashboard/insights` 激活两张真实证据聚合画像；未导入旧
  `audienceMock.ts`，单头像失败和整体数据失败分别 fail closed。
- 日报、周报、月报页面保持既有 UI 和 `reddit_voc_reports_20260714_v1` 绑定；浏览器
  实测 current/archive 六个报告 JSON 均为 200。

验证结果：

- 本批 Python 专项：`67 passed`；五类独立 validator：全部 `passed`。
- 前端定向：`17/17`；全量 Vitest：`104/104`；production build：通过；lint：
  0 error、5 个既有 warning。
- Chromium：桌面和 390px 移动端通过，头像自然尺寸 512 x 512，无横向溢出，
  console 0 error/0 warning，网络只观察到静态 GET。
- 全仓 Python：`743 passed / 4 failed`。三个稳定失败是历史 backfill release
  manifest 的当前文件哈希与冻结值不一致；另一个 fake-host launcher 在全量运行中
  返回 `inherited_lock_fd_invalid`，但精确隔离复跑 `1 passed`，根因尚未确认。没有更新
  旧 manifest 或跳过测试制造绿色。
- 独立审查的三项 P2 已关闭：persona receipt 固定五个上游 SHA；可选 tag-repair
  输入执行完整文件/hash/binding/boundary/status 校验；每个 review sample 必须有显式
  override，`default_decision` 不能补位。

未执行：生产数据接入、数据库写入、Provider 调用、发送、部署、调度修改、Git
commit/push/merge 或独立人工复核。
