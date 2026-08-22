# Reddit VOC P2E 新鲜度与自动发布闭环审计（2026-08-10）

## 结论

2026-08-10 的定时任务按北京时间 07:00 触发，但没有完成采集。直接根因不是“远端没有这一天的数据”，而是生产运行时版本混装：CLI 已传入 `raw_artifact_root`，生产 `collect_daily_tikhub()` 仍是旧签名，因此在任何 TikHub 网络请求和数据库写入之前抛出 `TypeError`。

本批先完成本地最小兼容热修、原子安装/回滚工具、运行时闭环验证器和两道分离的生产门禁合同；随后在精确授权下完成 collector-only 生产热修。生产 `tikhub.py` 已原子替换，Provider、数据库、cron、常驻容器和公开 current 指针均未改变。

## 事实（L3 只读生产证据）

- 审计时间：`2026-08-10T10:44:35.764036+00:00`。
- cron 服务为 active/enabled；`/etc/cron.d/reddit-voc-site` 仍在北京时间 07:00 采集、08:00 报告。
- `daily_collect_20260810_0700` 已触发，返回码 1，日志错误为 `collect_daily_tikhub() got an unexpected keyword argument 'raw_artifact_root'`。
- 本次失败发生在创建 TikHub client 之后、进入 collector 函数之前；`provider_call=false`、数据库无该 run 行。
- 数据库最近 run 仍是 `daily_collect_20260809_0700`，窗口止于 `2026-08-08T23:00:00Z`；数据库 integrity 为 `ok`，外键违规 0。
- 公开 current 仍是 `reddit_voc_release_20260810_observed_translation_v1`，其 `data_as_of_utc` 为 `2026-08-08T23:00:00Z`。
- 08:00 日报链因 `run_not_found` 失败；日报失败是采集失败的下游结果，不是独立根因。
- 生产 CLI 引用了 `.daily_source_batch` 和 `.schema_migration`，但远端运行时缺少对应模块；远端 `run_daily_collect.sh` 也没有构建 source-batch receipt。
- `reddit-voc-data-shadow.service/.timer` 没有安装，当前不存在 collect 到候选/发布的自动闭环。
- `reddit_voc_api` 与 `reddit_voc_site_app` 仍共同 RW 挂载同一 SQLite 数据目录。

## MECE 能力与断点

| 层 | 当前能力 | 当前断点 | 证据级别 |
|---|---|---|---|
| 调度 | 每日 07:00 采集、08:00 报告定时存在并触发 | 只证明触发，不证明业务完成 | L3 生产只读 |
| 采集 | 历史 TikHub 日采集可运行 | CLI/collector ABI 漂移使 8 月 10 日在 Provider 前失败 | L3 生产只读 |
| 原始证据 | 新 CLI 要求 raw artifact root | 旧 collector 不接受参数，也不落完整发现/详情原始文件 | L3 + 本地候选 |
| 结构化入库 | SQLite 历史 run/帖子/评论可查询 | 8 月 10 日 run 不存在 | L3 生产只读 |
| 报告 | 日报命令和既有历史数据存在 | 下游依赖缺失 run；周/月报的新鲜度同样无法前移 | L3 生产只读 |
| source receipt | 本地新代码具备设计 | 生产缺模块、缺 runner 步骤、存储 schema 合同也较旧 | L3 + 静态检查 |
| 候选构建 | 有手动候选/校验/切换工具 | 没有从当日 source receipt 自动生成候选的生产任务 | L3 生产只读 |
| 公开发布 | current/previous 原子版本机制已工作 | 没有自动 promotion 决策；网站会健康但数据继续陈旧 | L3 生产只读 |
| 监控告警 | cron 日志可追溯 | 无“今日 run 缺失/公开 freshness 落后”的 fail-closed 告警 | L3 + 代码审计 |

## 归因

### 直接根因

生产发布只更新了 CLI 的一部分依赖，没有把 collector 及其运行时闭包作为同一不可分割版本发布，形成 ABI 漂移。

### 系统性根因

1. 缺少部署前运行时闭包校验：原有门禁没有比对 CLI 调用关键字与 collector 函数签名。
2. 采集、source receipt、候选和 promotion 分属不同年代的脚本，没有单一日批状态机和统一 receipt。
3. “进程/HTTP 健康”与“数据新鲜”没有分离；容器健康无法发现当天 run 缺失。
4. 生产代码目录采用 bind mount，局部文件更新容易形成混装运行时。

### 放大因素

- 08:00 报告任务没有在 07:00 采集失败后给出独立可见的新鲜度阻断告警。
- 两个常驻容器拥有同一 SQLite 的 RW 权限，扩大并发写入与归属不清风险。
- `REDDIT_VOC_TIKHUB_DAILY_REQUEST_LIMIT` 被传入容器，但当前 collector 未消费该变量；请求量仅由搜索词、subreddit、listing 和 detail 上限间接限制。

## 本批完成的实现

1. `scripts/validate_reddit_daily_runtime.py`：静态验证 CLI/collector ABI、raw artifact 落盘调用，以及可选的 source-receipt 运行时闭包。
2. `tests/test_validate_reddit_daily_runtime.py`：覆盖通过、ABI 漂移和 source-receipt 缺失。
3. `collector-abi-hotfix-v1.tgz`：基于生产精确 preimage 的单文件最小热修，补齐 `raw_artifact_root` 并保存 discovery/detail 原始证据。
4. `remote_install_collector_hotfix.py`：仅替换一个生产文件；锁定目标、数据库、cron、current release；在现有容器内执行无 Provider import/signature 烟测；失败自动回滚。
5. 安装器临时文件系统演练：成功路径与烟测失败回滚路径均通过；连同运行时 validator 共 6 项测试通过。
6. 两个分离合同：collector-only 热修门禁，以及后续一次性 8 月 10 日补采门禁。
7. 项目全量回归：`1944 passed, 942 subtests passed`，退出码 0。

## 尚未执行与门禁顺序

### G1：采集器兼容热修（已完成）

已按精确授权上传门禁文件、原子替换生产 `tikhub.py`、写入备份/receipt 并执行无 Provider 烟测。生产 collect-only 闭包通过；独立后检确认数据库、cron、采集/报告日志、current/freshness 和常驻容器身份未变。

### G2：8 月 10 日补采（已完成）

已使用新 run id `daily_collect_20260810_0700_retry1` 完成一次性补采，窗口固定为 `2026-08-08T23:00:00Z` 至 `2026-08-09T23:00:00Z`。结果为 11 帖、43 评论、54 条分析、31 条数据库 raw capture 与 31 个原始文件；Provider issue 为 0，覆盖为 7 full / 4 partial。未发送报告、未构建候选、未切换公开版本。

### G3：source receipt 与 schema/runtime 迁移

本地 shadow admission 已完成。稳定生产快照证明生产数据库本身已经采用当前 raw-capture 唯一键，必需表/列齐全，因此不需要、也不应执行生产 schema 写迁移。真正缺口是七项运行时闭包：三个 source/schema 模块、两个 profile、新版 `VocStore` 只读能力和 runner 步骤。

冻结候选在生产快照上生成了与首次 shadow 完全一致的 source batch：manifest SHA `f0d92ce642d139f2cda8b4b316cc7db25dbeda35e364b27112345fb499fdaada`，31 raw、11 posts、43 comments、0 issues、7 unresolved continuations，状态 `partial` 但可消费。候选包 SHA 为 `ae8766a6e43ee38247f5df5b2f01272b70577844fd6ae8dce298af377f341b23`。

当时冻结的远端门禁把七文件原子安装与该 run 的只读 source receipt 复演绑定成单一事务；任一 preimage、调度窗口、活动 one-off 容器、运行时烟测或 manifest 哈希不符都会 fail closed，复演失败则整体回滚运行时。其首次执行与修正版 retry1 结果如下。

首次精确授权执行已在运行时烟测阶段 fail closed：安装器误导入不存在的 `inspect_schema_state`，因此没有进入 source receipt。七个运行时目标已整体恢复，数据库、cron、current 与容器未变。该问题属于门禁脚本测试缺口，不是生产 source runtime 不兼容。已改用真实存在的 `sha256_file` 并新增完整候选的真实 import/schema/shell 烟测；修正版 8 项门禁测试通过。原授权已消耗，修正版重试需新的精确授权。

修正版 retry1 已在新的精确授权下通过。七个 payload 已安装，宿主机和现有应用容器均通过无 Provider 的 import/hash/只读 schema 烟测；无需容器重启。`daily_collect_20260810_0700_retry1` 的生产 source receipt 已生成，manifest SHA 为 `f0d92ce642d139f2cda8b4b316cc7db25dbeda35e364b27112345fb499fdaada`，与本地 shadow 逐字节一致。数据库前后 SHA 不变，cron、current 和容器保持保护基线。G3 已闭合，但该结论不授权 G4 候选构建或公开发布。

### G4：候选自动构建与 shadow 验证

已在精确授权下完成本地隔离构建与 shadow 验证，不改 current。冻结输入与远端 source receipt 精确一致；融合后得到 3,847 帖、28,565 存储评论，其中 21,612 linked、6,953 unresolved，净增 11 帖/43 评论。

首次构建暴露并修复了一个仅存在于本地候选代码的关系归类缺陷：TikHub 的 depth-0 评论可能没有 `parent_id`，此时应以已存在的 root `post_id` 归一化；嵌套评论缺父关系仍保持 debt。26 项聚焦回归通过，canonical 独立校验的 identity/FK 未对账数均为 0。

VOC facts、治理信号、26 指标确定性重放、报告和洞察公开投影均通过 candidate-only 独立校验。日报已前移为 8 月 10 日；日报/周报/月报的观测口径环比、同比和六点趋势组分别为 `5/5/5`、`9/9/9`、`10/10/10`。由于历史覆盖没有 owner attestation，正式 comparison contract 仍为 false，页面必须保留“观测口径/7 日替代窗口”和原因码，不能升级为完整市场趋势声明。

最终 G4 未准入。生产翻译侧写可按 identity + 规范化输入 SHA 安全复用 28,281 个非空字段，另有 961 个空源字段；新增批次仍缺 64 个非空中文字段（11 标题、10 正文、43 评论）。本门禁禁止 Provider，因此不伪造翻译、不暴露英文冒充中文，也不切换公开 current。G4 总回执 SHA 为 `c434620e85dbf642035524bfb62aaa790f4bd3ee5de26a8ff713e91c38735618`。

下一门禁为 G4T：只对这 64 个字段执行受限翻译，按 identity/input SHA 合并并重跑翻译与 G4 总验收；通过后仍需独立 G5 才能写远端正式候选或切换 public current。

### G5：promotion 策略

满足窗口、同环比历史覆盖、翻译、schema、引用完整性和 freshness SLO 后才允许原子切换；任何 unavailable 比较必须保留原因，不能伪造趋势。

## 不确定项

- G4 的数据、指标、报告与洞察候选已在冻结生产输入上验证，但 64 个新增中文字段尚未翻译，因此公开 current 仍不能切换。
- 2026-08-11 的既有 07:00 采集、08:00 钉钉定时和 bounded-live policy 已只读通过；未来 07:00 Provider 采集和 08:00 外部传输尚未发生，当前只能判定为条件就绪，不能把未来事件写成已保证送达。
- 自动 promotion 是“每次 partial 也发布”还是“仅 freshness 合格发布”：需要在 G5 选择明确策略；当前建议 partial 可发布但必须显著标注覆盖与不可用比较原因。

## 后续优化优先级

- P0：G1、G2 已完成，生产数据库已恢复至北京 8 月 10 日 07:00 窗口。
- P1：完成 G4T/G5，并加入“今日 run 缺失”“公开 data_as_of 落后”的独立告警。
- P1：让请求预算成为 collector 内部硬约束，而非未消费的环境变量。
- P1：收敛 SQLite 单写者，其他服务改 query-only/RO 挂载。
- P2：把 runtime closure manifest 纳入每次部署，禁止局部混装。
- P2：将日/周/月报告的 comparison/trend 可用性、帖子中文翻译和 freshness 统一纳入 promotion acceptance。
