---
title: Reddit VOC Insights Site Activation and Isolated Deployment
doc_type: execution_plan
status: production_rc3_accepted_with_explicit_debt
created: 2026-07-15
updated: 2026-07-15
owner: codex
project: Reddit_VOC
production_boundary: authorized_live_operational_partial
provider_call: true
database_write: false
live_send: false
---

# Reddit VOC 洞察站真实化与隔离部署 TODO

## 1. 目标与第一性约束

目标是把 `ref/UI/momcozy-reddit-workbench` 激活为可公开访问的真实数据洞察站，
部署到 `reddit.lute-tlz-dddd.top`，并提供进入现有采集后台
`https://reddit.brand.lute-tlz-dddd.top/` 的显式入口。

任何实现必须同时满足：

- 新站只消费经过校验的不可变静态快照，不读取生产 SQLite，不实时调用采集后台。
- 新站使用独立目录、Compose project、容器、网络、镜像标签和内部端口。
- 不修改 `/opt/reddit-voc-site`、`/opt/reddit-voc-report`、采集 cron 或采集容器。
- 生产 V2 曾冻结 860 个 discovery-only 身份，其中 842 个完成 hydration；当前生产 RC3
  冻结 883 个 discovery-only 身份并激活 1,322 帖，18 个 lineage 缺口继续隔离。
  后续新版本仍只有完成全链测试和负责人精确 promotion packet SHA 授权后才能升级 current。
- 没有真实数据合同的页面必须 fail-closed；不得回退 Mock、随机数据或假 API。
- 公开站不启用登录；公开投影移除作者标识、采集运行标识和内部策略字段，并配置 CSP、
  禁止目录浏览和 noindex。当前作者字段为 `null`，不是可关联的稳定假名。
- 网站浏览本身不得触发 provider、Webhook、钉钉、数据库写入或采集动作。
- 日报、周报、月报是核心能力；保留现有 UI 和真实报告链路。
- 案例广场保留全部存量内容，只把增量更新链路真实化。

## 2. 数据与能力边界

当前正式静态版本（RC3）：

- Base：`reddit_voc_site_snapshot_20260715_6efd951e6095`
- Insights：`reddit_voc_insights_20260715_a900e6ce7b63`
- Reports：`reddit_voc_reports_20260715_a900e6ce7b63`
- Personas：`reddit_voc_personas_20260715_a900e6ce7b63`
- Release pointer：`reddit_voc_release_20260715_a900e6ce7b63`
- RC3 input freeze SHA：
  `44c2b85be53b11e92a818267a4afa75e521d1fcee5024840c2c3be775e8d93f4`
- Frontend/container release SHA：
  `9e0d23131824c9d5e195ef9e0950d62e1c89893a40bafa1ec72c53fab330d650`
- 状态：`production_accepted_with_explicit_coverage_debt`，
  `latest_collection_integrated=true`，
  `latest_collection_fully_hydrated=false`，
  `completion_claim_supported=false`

当前版本支持已观察量、分布、真实全文搜索、受治理风险洞察、证据型聚合画像、
日报/周报/月报，以及覆盖门禁下的环比、同比和观察趋势序列。当前所有趋势方向声明
仍为 false；它不支持市场份额、SOV、ROI、响应时长、真实用户画像或 UGC 授权状态。
网页必须保留这些解释边界。

公开站只发布四条经过精确文件白名单和 SHA-256 校验的数据链；原始帖子、原始评论、
原始标签字典、内部语义审计上下文和私有报告文件均不进入镜像。画像是证据型聚合画像，
头像为合成 SVG，不代表真实 Reddit 用户。

### 当前执行结论（2026-07-15）

| 层级 | 状态 | 可核验证据 |
| --- | --- | --- |
| 本地真实化与数据投影 | 已完成 | V2 相关 Python `68/68`、发布审计 `9/9`、前端 `135/135`；动态 validator、lint、typecheck、build 与 dist 审计通过 |
| 本地浏览器 E2E | 已完成 | 最终不可变 dist：13 个路由 × 桌面/移动共 26 个页面 HTTP 200，无浏览器错误、外部请求或横向溢出；A/B/C 和 6 个报告状态通过 |
| 隔离容器 | RC3 已部署 | release `9e0d23131824c9d5e195ef9e0950d62e1c89893a40bafa1ec72c53fab330d650`，容器 healthy、UID 101、只读、零挂载 |
| HTTP 边缘入口 | 已配置 | Host 覆盖访问 `/healthz`、release、SPA、公开数据与原始路径拒绝均通过 |
| DNS / TLS / 正常公网域名验收 | 已完成 | A 精确指向 `101.34.52.232`、AAAA 为空；Let’s Encrypt 证书与正常域名 HTTPS E2E 通过 |
| 历史 V2 生产 checkpoint | 已被 RC3 替代，可回滚 | V2 global known 1,317、净新增 1,096、discovery-only 860；V2 生产浏览器直跑缺口保持历史记录 |
| task2600–2603 增量盘点 | 已完成 | 66 个 allowlisted 文件；相对生产 V2 净新增 23 帖、139 条已关联评论；增量片段仍有 7 个 cursor debt |
| 增量 Base→Insights→Reports→Personas→public | RC3 已完成 | 候选 1,322 帖、12,986 stored、12,976 linked、10 quarantine、12,825 VOC comments；四层独立 validator 通过 |
| 增量前端/容器候选 | 历史候选阶段已完成 | 55/55 dist 文件与 24/24 public data 一致；linux/amd64、UID 101、release marker/labels 离线验证 |
| RC3 promotion packet | 已完成 | packet `7d429a83...4f11` 绑定 freeze、gate、独立 E2E、manifest、SHA 列表、TGZ 与 image tar；包内 8/8 path/bytes/SHA 复核通过 |
| RC3 生产提升 | 已受控完成并验收 | current 为 `9e0d2313...d650`；容器/HTTP/生产浏览器/CSV/DOCX/不变性均通过；完整水合仍为 false |

TODO 标记规则：`[x]` 表示已有本次新鲜证据；`[ ]` 表示仍待执行，不以设计意图代替验收。

## 3. 实施 TODO

### Phase A — 前端生产门控

- [x] 在桌面侧栏和移动端页头增加采集后台外链；新标签打开，无预取、无 token。
- [x] 页面数量、标签审计计数和版本信息全部来自已验证 manifest，不保留 `221` 等硬编码。
- [x] 增加清晰的静态快照生成时间、版本、覆盖量和非实时提示。
- [x] Messages、UGC、Settings 保留路由与导航，但改为真实合同空态/只读态。
- [x] 禁止 Webhook 测试发送、假开始监控、随机通知、随机 Sankey/词云进入活动路由。
- [x] 营销页保留布局，删除或改写无法证实的实时、准确率、客户数、安全认证等声明。
- [x] 首页仪表盘示意明确标注为“功能示意，非实时数据”。

### Phase B — 案例广场增量

- [x] 将 38 条人工策展内容固化为 `cases_seed_v1`，原卡片与分类不删除。
- [x] 将 12 条模拟 web discovered 内容保留为 `legacy_unverified`，不得标为真实新增。
- [x] 移除随机排序、模拟网络延迟和不存在的 `/api/v1/search/cases` 依赖。
- [x] 新增版本化 manifest/index，记录版本、生成时间、来源状态和文件摘要。
- [x] 使用 canonical URL、内容哈希、来源 ID、标题+域名进行确定性去重。
- [x] 前端合并 seed 与 `approved` delta；delta 缺失或校验失败时只展示完整 seed 并明确状态。
- [x] 来源徽标区分“精选存量 / 待核验存量 / 已验证增量”。当前 approved delta 为 0。

### Phase C — 静态发布制品

- [x] 本地执行 test、lint、typecheck、build；服务器不运行 Node 构建。
- [x] 构建只包含 `dist`、静态 Nginx 配置和 release manifest 的版本化制品。
- [x] 扫描制品，确认不含 `.env`、PEM、key、SSH 配置、生产 DB、原始数据或私有导出。
- [x] 静态容器使用非 root、只读根文件系统、cap_drop、no-new-privileges 和资源限制。
- [x] 配置 `/healthz`、SPA fallback、静态缓存、CSP、noindex、日志轮转和禁止目录浏览。
- [x] 生成 SHA-256 清单，远端上传后逐文件校验。

### Phase D — 浏览器 E2E

- [x] 桌面 1440px 与移动端 390px 检查全部 13 个活动路由。
- [x] 任意 SPA 子路由直接刷新不返回 404。
- [x] Base/Insights/Reports/Personas manifest 或受管文件被篡改时对应模块 fail-closed。
- [x] V2 风险主线、产品三层、竞品 Top 6、两张合成头像、C receipt 和
  当前/归档共 6 个日周月报告状态在同一不可变 dist 上通过 DOM/网络验收。
- [x] 日报、周报、月报及闭合归档均可加载，报告合同和切换行为测试通过。
- [x] 在正常公网 HTTPS 域名对当前 RC3 实际下载 CSV 与 DOCX；CSV 为 422 bytes、
  UTF-8 BOM、9 行，DOCX 为 11,438 bytes/ZIP 合同且 `unzip -t` 通过。
- [ ] PDF 与 PPT 菜单可见，但尚未实际下载验证；不把 CSV/DOCX 通过扩大成全部格式通过。
- [x] 案例 seed、待核验存量、approved delta 合并、来源分类与确定性去重测试通过。
- [x] 在正常公网 HTTPS 域名复核案例搜索、分类筛选和分页：`GEO=12`、
  `舆情洞察=15`、`1/2 → 2/2`，尾页 3 条且下一页禁用。
- [x] 采集后台按钮点击前零请求；目标 URL、`target`、`rel` 和 referrer policy 正确。
- [x] 浏览器网络中不存在 Webhook、provider、钉钉、未知 API 或自动采集请求。
- [x] Console 无未处理错误；页面无横向溢出和关键内容遮挡。

### Phase E — 腾讯云部署前门禁

- [x] 避开 `06:30–08:30 Asia/Shanghai` 采集/报告窗口。
- [x] 记录现有容器 ID、image、health、restart count、网络成员和端口。
- [x] 记录 Nginx 配置 SHA、cron 内容 SHA、后台 `/api/health` 和现有域名状态。
- [x] 确认不存在 `reddit_voc_site_app-run-*` 临时采集容器。
- [x] 确认采集 DB 和 `/opt/reddit-voc-report/current` 在 5 秒部署门禁观察窗口内没有并发变化。
- [x] 确认目录、容器名、网络名和内部端口 `18338` 未被占用。

### Phase F — 隔离部署

- [x] 上传到 `/opt/reddit-voc-insights-site/releases/<release_sha>/`，不覆盖旧 release。
- [x] 只启动 Compose project `reddit_voc_insights` 和容器 `reddit_voc_insights_web`。
- [x] 新容器只加入 `reddit_voc_insights_net`，不挂载采集目录，不访问 Docker socket。
- [x] 内部 `/healthz`、首页、JSON manifest 和 SPA 深链接 smoke 全部通过。
- [x] 备份共享 Nginx 配置；只增加 `reddit.lute-tlz-dddd.top` vhost。
- [x] `nginx -t` 通过后才 reload；未重启 `ai_video_nginx`。
- [x] DNS A 记录指向 `101.34.52.232`、AAAA 为空，并签发该域名独立证书。
- [x] HTTP `301` 跳转同路径 HTTPS；HTTPS 公开访问，不接 Portal Auth。

### Phase G — 公网验收与回滚

- [x] 在正常解析的公网 HTTPS 域名执行 13 路由 × 桌面/移动端共 26 页 E2E；
  证书、重定向、CSP、HSTS、noindex、错误与外部请求检查通过。
- [x] 当前 RC3 生产浏览器直跑已通过：13 路由 × 桌面/移动共 26/26，A/B/C、六个报告
  状态、画像、案例和采集后台链接合同均通过，无外部请求或浏览器错误。V2 版本曾在导航前
  被 macOS SIGKILL 的缺口仅作为历史事实保留，不冒充 V2 生产浏览器实跑。
- [x] RC3 镜像内确认无 `.env` 文件；当前 `/.env` 请求返回与根页相同的 SPA index 200，
  记为既有非阻断加固债务。三个受管私有 `/data/...` 路径仍为 404，不把 SPA fallback
  描述成秘密文件泄露，也不隐藏该行为。
- [x] 不可变 C 控制证据仍显示构建阶段字段 `production_unchanged=true`、`deploy=false`、
  `release_switch_executed=false`。它们不是当前部署状态，但上线后可能被误读；本次不改写已授权
  release，下一版本需把 artifact-build provenance 与 site-deployment status 分栏。
- [x] 使用 `curl --resolve` 完成 HTTP Host 覆盖验收：health、release、SPA、公开数据、原始路径 404 和安全头通过。
- [x] 验证采集后台外链合同和原后台公网 health；新容器无法连接采集监听端口。
- [x] 对比部署前后采集容器 ID/restart count、cron SHA、网络成员和后台 health，均保持一致。
- [x] 新容器为只读、零挂载、无 Docker socket；浏览器 E2E 无外部请求，静态部署证据记录
  `database_write=false`、`dataset_provider_call=false`、`live_send=false`；TLS 签发单独记录
  `acme_provider_call=true`。
- [x] 首次使用 `internal: true` 的部署因 Linux published port 不可达而失败，自动回滚清除了
  container/network/current，恢复端口和 Nginx，采集后台健康且 restart count 未变化。
- [x] 根因复现实验后改为普通 bridge，并显式设置 `enable_ip_masquerade=false`、
  `enable_icc=false`；验证 Host 可达、容器无法连接采集监听端口且公网 egress 超时。
- [x] 提供只切换新站 release/current 或 disable 新 Compose 并恢复 Nginx 的显式回滚脚本；
  参数拒绝、语法和本地制品合同通过。
- [ ] 对显式 release/disable 回滚脚本做一次授权的生产故障注入演练；当前未执行。
- [x] 首次失败自动回滚后再次验证原采集后台无回归。

### Phase H — 采集完成后的数据升级与独立增量候选

- [x] 冻结 content、identity、coverage ledger、manifest 与源文件 SHA；task2600+ 排除到下一增量。
- [x] 完成跨源去重、父子关联、quarantine、PII、产品实体三层模型与受治理标签重跑；
  正式 Base v2 为 1,299 帖、12,837 linked comments、10 quarantine，独立 validator 通过。
- [x] 生成新的 Base → Insights → Reports → Personas 完整版本链及公开最小投影。
- [x] 趋势、环比、同比按 coverage status 分级开放；不可比窗口返回 null+reason，不开放 SOV。
- [x] 按同一发布和回滚门禁升级静态站，不连接实时生产 DB。
- [x] 盘点并纳入 task2600–2603：23 个净新增帖子、139 条已关联评论；task14014
  为 plan-only，继续排除；不得把增量片段的 7 个 cursor debt 当成全局覆盖债务。
- [x] 生成不可变 RC3 input freeze，并以相同命令验证 `created → no_change`；RC2
  因后续代码漂移曾正确 fail-closed，保留为门禁有效性的历史证据。
- [x] 生成 task2600–2603 的 Base → Insights → Reports → Personas → public 候选，
  并完成独立 Analytics validator、完整跨层候选 gate、无变化复跑和篡改测试。
- [x] 以当前冻结源码重新构建 frontend dist 和本地 linux/amd64 容器制品；不 load、
  不 run、不创建容器，现有 7 个 Docker 容器集合和哈希保持不变。
- [x] 运行同一候选 dist 的 13 路由 × desktop/mobile 浏览器 E2E；A/B/C、产品三层、
  竞品同样本、合成头像、6 个日周月报告状态和采集后台安全外链均通过。
- [x] 负责人选择接受 `fully_hydrated=false` 的 RC3 先提升，并要求完整保留 367 cursor、
  339 page、348 partial-thread 和 18 lineage-gap 债务。
- [x] 获得精确 promotion packet SHA 与 release SHA 双重授权后，按 Phase E–G 的同等级
  隔离门禁完成生产提升与验收；生产 acceptance receipt 已固化。
- [ ] 将后续采集纳入“自动冻结/融合/验证/候选制品”链；前两次生产 promotion 保持人工
  精确 promotion packet SHA 批准，自动任务不得直接写 production current。

## 4. 完成定义

只有同时取得以下证据，才能声明部署完成：

- L1：本地测试、lint、build 和浏览器 E2E 通过。
- L3：部署前后生产只读基线一致，原采集容器未重启、cron 未变化。
- L4：经本任务授权，新静态容器/current 切换和公网验收有日志证据；只有确有配置变更且
  另有授权时才要求 Nginx reload 或 TLS 签发。本次 RC3 提升两者均未修改。
- DNS 尚未生效时，只能声明“容器已部署/内网已验收”，不能声明公网域名已完成。

## 5. 执行证据与下一动作

- 当前最终 release：`9e0d23131824c9d5e195ef9e0950d62e1c89893a40bafa1ec72c53fab330d650`；
  pointer 为 `reddit_voc_release_20260715_a900e6ce7b63`。
- 容器部署证据：
  `/opt/reddit-voc-insights-site/evidence/container-deploy-20260715T072959Z-9e0d23131824c9d5e195ef9e0950d62e1c89893a40bafa1ec72c53fab330d650.txt`，
  SHA `bed11a4e972b5458ed92544638831eab8ba0849e7eb91c9b7024baa524e80165`。
- HTTP 边缘证据：
  `/opt/reddit-voc-insights-site/evidence/edge-http-20260714T192555Z-08f54c8cf8dd6274a1ca666b87015d4375d655497246cb448120f54dd80438b6.txt`。
- 当前 `current`、容器 label、内部与公网 release marker 均指向上述 RC3 release；
  `reddit_voc_insights_web` healthy，restart count 为 0。
- 历史 HTTP 阶段曾因 DNS 未配置而阻塞；浏览器 Host resolver/临时代理尝试也没有取得可接受
  的生产 E2E 证据：分别出现
  `ERR_HTTP_RESPONSE_CODE_FAILURE`、路由 `ERR_ABORTED` 和 HTTP 非可信来源下的 COOP 错误；
  这些历史结果未被升级为验收证据。
- 当前 DNS：权威 DNS、系统解析器与 `1.1.1.1` 的 A 均仅为 `101.34.52.232`，AAAA 为空。
- HTTPS L4 证据：
  `/opt/reddit-voc-insights-site/evidence/edge-https-20260715T011301Z-08f54c8cf8dd6274a1ca666b87015d4375d655497246cb448120f54dd80438b6.txt`。
- 证书 SAN 为 `reddit.lute-tlz-dddd.top`，有效期至 `2026-10-13 00:14:26 UTC`；
  `snap.certbot.renew.timer` enabled，下一次计划运行时间已核验，deploy hook 存在。
- RC3 最终不可变 dist 的生产浏览器 E2E：13 路由 × desktop/mobile 共 26 页全部 200，
  无 console/page/request 错误、未知外部请求或横向溢出；当前/归档六个报告状态通过。
- 首次部分传输因 SHA 不符 fail-closed 并清理；首次候选因额外 `.env` 探针触发 SPA fallback
  门禁而自动移除。两次均未切换生产，随后按真实私有路径合同完成候选与正式验收。
- 交互验收：日报/周报/月报及三种闭合归档切换正确；CSV/DOCX 实际导出通过；
  案例边界保持 `38 精选 + 12 待核验 + 0 已验证增量`，搜索、分类和分页通过。
- 观察项：公开 manifest 首轮曾出现一次不可复现的 15 秒超时；随后连续 15/15 manifest
  与 5/5 health 请求成功。当前不阻断，但不宣称从未发生瞬时网络抖动。
- RC3 生产升级已完成；后续自动化仍是一条独立、未实现、未启用的候选发布链。
  “本次生产已接入”不得扩大成“后续增量已自动接入”。
- V2 生产 ID 盘点曾按该版本封账。此前 `+13`、`887` 和 `651 discovery-only` 都是更早水位；
  V2 口径为历史 site baseline 221、global known 1,317、net-new 1,096、discovery-only 860。
  当前生产 RC3 已重新封账为 global known 1,340、net-new 1,119、discovery-only 883。
- 当前生产 RC3 Base 为 1,322 个帖子；1,340 个 global known 中仍有 18 个 lineage 缺口未激活，
  不得把 1,322 扩大为 1,340。

## 6. UI 真实化盘点与后续数据需求

| UI/能力 | 当前真实化状态 | 数据边界或下一步 |
| --- | --- | --- |
| Dashboard | 当前静态快照真实 | 只代表已冻结样本，不代表 Reddit 总量或生产采集完成量 |
| Reports | 日报/周报/月报和闭合归档真实 | CSV/DOCX 公网实际导出已验收；PDF/PPT 仍无受管导出合同 |
| Analytics | 样本内数量和分布真实 | 连续趋势、速度、异常检测在 observation 时间序列门禁通过前不开放 |
| Insights | 受审计标签和有限语义信号真实 | 低样本、冲突或无上下文信号继续 held，不生成业务行动幻觉 |
| Search | 当前公开投影内全文搜索真实 | 最新生产数据冻结后重建索引；作者标识继续 suppressed |
| Personas | 标签字典映射与样本证据聚合真实；头像为合成图 | 不解释为真实个体，不做跨帖用户跟踪 |
| Case Gallery | 38 条精选 + 12 条待核验存量保留 | approved 增量当前为 0，只接收离线审核通过且可追溯的新增 |
| UGC / Messages / Settings | 真实合同空态或只读态 | UGC 权利、消息渠道和生产配置没有受管数据前保持关闭 |
| Marketing 首页 | 原 UI 保留，演示区已标注 | 不宣传实时、准确率、客户数或认证等无证据能力 |
| 采集后台入口 | 真实安全外链 | 只导航到现有后台，不共享登录、token、网络或故障域 |

采集完成后的数据升级必须按以下顺序执行：

- [x] 将网站基线、`ai_nlp_voc` 导入归档、Task 37、生产 daily SQLite 与 cutoff 内 V2 报告
  冻结为安全清单，完成集合交叉、计数与哈希复算；V2 净新增帖子为 1,096。
- [x] 对 V2 的 860 个 discovery-only 身份执行 hydration；842 个形成内容快照，18 个 non-V2 lineage
  缺口隔离，并记录来源、cutoff、文件 SHA、行数与失败原因。
- [x] 建立 coverage ledger：search lane、首屏、reply cursor、页数、成功/失败与缺口；
  未知覆盖不得解释成零讨论或市场份额。
- [x] 以 Reddit post/comment ID 做主键去重，验证父子关联、孤儿评论、删除内容、时间字段与
  跨源冲突，并将异常行送入 quarantine。
- [x] 重新应用 `dim_tag_v6.3_final.csv` 与受治理产品实体三层模型，保留正文与评论的规则命中、画像映射、证据引用和
  字典版本；低支持度结果不得晋级。
- [x] 生成新的 Base → Insights → Reports → Personas 版本链和公开最小化投影；旧版本保持
  不可变且可回滚。
- [x] 比较新旧版本的实体数、标签分布、报告指标、held/promoted 集合与隐私字段，并以
  fail-closed 风险门禁升级站点 `current`。
- [x] 在 coverage status 下开放观察趋势、环比和同比；方向结论全部受门禁约束。
- [ ] 只有连续 observation 覆盖进一步成立后，才开发速度和异常；SOV、ROI、响应时长、
  真实个体画像和 UGC 授权继续保持不可用，直到有对应事实源。
- [x] 新版本走相同 release SHA、制品审计、隔离部署和回滚门禁，不直接连接生产 DB。
- [x] 为 task2600–2603 建立独立 RC3 版本候选和同等级本地验收，不修改 V2 不可变制品。
- [x] 将 RC3 身份口径重算为 global known 1,340、net-new 1,119、discovery-only 883，
  并在候选中激活 1,322 帖；18 个 lineage gaps 继续显式隔离。
- [ ] 将同一流程推广到后续采集，自动化只产出候选；生产提升继续使用精确
  promotion packet SHA 许可。

固定非能力声明：

```text
dataset_provider_call=false
initial_site_tls_acme_provider_call=true
rc3_promotion_tls_provider_call=false
database_write=false
live_send=false
webhook_send=false
schedule_change=false
collector_restart=false
production_latest_collection_integrated=true
production_latest_collection_fully_hydrated=false
production_completion_claim_supported=false
partial_threads=348
cursor_outstanding=367
page_pagination_outstanding=339
lineage_gaps=18
incremental_candidate_validated=true
production_promotion_executed=true
incremental_automation_enabled=false
collector_changed=false
cron_changed=false
shared_nginx_changed=false
tls_changed=false
dns_changed=false
other_docker_changed=false
local_rc_base_integrated=true
v2_release_retained_for_rollback=true
```
