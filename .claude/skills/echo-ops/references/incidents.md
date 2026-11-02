# Echo-Agent 事故与坑点目录

按“症状 → 根因 → 证据 → 修复 → 防线”记录。每条都对应一次真实运行、提交或会话；新增事故时先补证据，再补防线。

## A. 发布与数据契约

### A-01 绝对符号链接让 `/data/` 全 404，`/` 仍 200
- **症状**：radar.luteos.com 所有 `/data/` 请求 404；`/` 返回 200 text/html，看起来“站点正常”。
- **根因**：`data/reddit-voc` 指向绝对路径；nginx 容器把站点 bind mount 到 `/var/www/voc-report`，容器内没有宿主机的绝对路径，链接悬空；SPA fallback 把空壳伪装成 200。
- **证据**：2026-10-31 生产事故；`scripts/daily_release_transaction.py` 的 `_relative_link_target`；`echo-agent-production-llm-and-generations` 记忆。
- **修复**：发布事务只写相对链接；`_live_target` 用 `resolve(strict=True)`。
- **防线**：`verify_daily_run.py` 检查 `is_symlink + relative + exists`；公网必须查 `/data/` 的 `content-type` 与 payload，不能只看 `/` 200。

### A-02 manifest 字节、SHA、binding 没有同批更新
- **症状**：页面报“发布 manifest SHA-256 不一致：base”；单元测试与 `curl` 都通过，浏览器仍失败。
- **根因**：manifest 哈希、文件字节数、`current-release.json` binding 分三次更新；前端按 bundle 严格校验，任一不一致就拒绝渲染；`force-cache` 还会把旧 manifest 钉在用户浏览器。
- **证据**：`echo-agent-release-data-caching` 记忆；2026-10-27 六个页面同时失败。
- **修复**：语料定稿后同批刷新 manifest、bytes、binding；前端改 `cache: 'no-cache'`。
- **防线**：`check_site_freshness.py` 的三方自证（binding SHA = manifest 字节 SHA = build.json）；发布后用浏览器逐页验收。

### A-03 JS 四舍五入与 Python 银行家舍入不一致
- **症状**：客户端复算值与服务端值差 0.01，契约校验失败。
- **根因**：JS `Math.round` 是 half-up；Python `round()` 是 banker's rounding。
- **证据**：`echo-agent-release-data-caching` 记忆；`contribution_points = value/4`。
- **修复**：需要 half-up 时用 `math.floor(x*100+0.5)/100`。
- **防线**：任何客户端复算值必须有同一公式的对照测试。

### A-04 `JSON.stringify` 受键顺序影响
- **症状**：`aggregates.time_precision` 与 `manifest.time_precision` 值相同却比较失败。
- **根因**：两边来自不同构造路径，键插入顺序不同；`JSON.stringify` 保留顺序。
- **修复**：两边共用同一个构造函数。
- **防线**：契约测试直接比较对象，不比较序列化字符串。

### A-05 reports 是自绑定 bundle，不能局部重生成
- **症状**：报告 bundle 校验失败、history 计数漂移。
- **根因**：reports 由九个文件互相绑定；只改其中一个会破坏自证。
- **修复**：`scripts/recompute_reports_bundle.py` 整体重生成，发布诚实的 `comparison_contract_proven=false` 变体。
- **防线**：冻结/attested 数据集只读保护；`check_site_freshness.py` 逐数据集自证。

### A-06 公网指针读到旧值：一次 `curl` 不能定罪
- **症状**：2026-11-02 首次读取公网 `current-release.json` 得到 `generated_at_utc=null`；加 `?cb=` 后与宿主代际文件 SHA 完全一致。
- **根因**：`cache-control: public, max-age=60` 与 nginx/中间缓存；普通 `curl` 可能读到旧或半写指针。
- **修复**：读取时加 `?cb=<timestamp>` 与 `Cache-Control: no-cache`；对比宿主文件 SHA。
- **防线**：`verify_daily_run.py` 默认 cache-bust 并比较 SHA；单次异常先重试，不直接报事故。

## B. 运行可靠性

### B-01 10-29 权限错误导致混合代际服务 732 分钟
- **症状**：07:05 运行在 recompute 因 `PermissionError` 失败；pointer 仍指向旧代，但 live 树已被新 base 覆盖；站点呈现“新 base + 旧指标”。
- **根因**：流水线原地改写 live 树；root 属主文件不可写；失败后没有代际边界可回退。
- **证据**：2026-10-29 事故；GOAL K2 基线约 732 分钟。
- **修复**：L6-T01/T02 文件级 preflight；L6-T07/T08 代际事务；失败运行对 live 零字节。
- **防线**：`tests/test_daily_pipeline_transaction_wiring.py` 的故障注入；`verify_daily_run.py` 检查 `release_transaction.mode=symlink` 与代际数。

### B-02 回执嵌入 dataclass，`json.dumps` 崩溃
- **症状**：2026-10-31 07:31 定时运行 exit 1，损失 19m48s；报 `Object of type RndVocResult is not JSON serializable`。
- **根因**：回执把原始 dataclass 放进 `evidence_gate`。
- **修复**：回执只写可序列化字段；`5c506bc`。
- **防线**：回执 schema 测试；运行后立即校验 `status` 与 `errors`。

### B-03 证据门禁只改回执，不改产物
- **症状**：回执说虚构引文已 `dropped`，页面仍渲染该引文。
- **根因**：门禁返回 receipt，但调用方继续使用原始 batch。
- **修复**：门禁返回 `(receipt, scrubbed)`，调用方用清洗后的 batch 重建产物。
- **防线**：带虚构引文的测试必须同时断言回执与落盘产物。

### B-04 单写者锁的四类自伤
- **症状**：任意 flock 错误都被报成“另一轮在跑”；`with PipelineLock(...)` 实际没加锁；测试在带生产凭据的 shell 里可能发真实飞书卡；`assert x or True` 恒真。
- **根因**：错误分类过宽；`__enter__` 未 acquire；测试未隔离凭据；断言写错。
- **修复**：只把 `EWOULDBLOCK` 当争用；`__enter__` 内 acquire；测试隔离凭据；断言 `FD_CLOEXEC` 本身。
- **防线**：真实跨进程测试；代码评审专门检查“测试是否会触碰生产”。

### B-05 部署清单手工维护，连续漏文件四次
- **症状**：生产缺事务模块、observe、control 等文件；“已部署”后 ImportError。
- **根因**：部署集是手写列表，不是从运行入口推导。
- **修复**：`deploy_manifest.py` 用 AST 导入闭包推导；36 个路径 SHA 与生产逐一匹配。
- **工具自身两个 bug**：相对导入被静默丢弃；`src/reddit_voc` 映射到生产未使用的那份拷贝。
- **防线**：部署集从导入图推导；部署后做字节级比对。

### B-06 `typing.Self` 在 Python 3.10 上 ImportError
- **症状**：`product_entity_resolution.py` 在生产 3.10.12 上无法导入；L1-T05 从未真正运行。
- **根因**：`from typing import Self` 需要 3.11；此前只用 `ast.parse(feature_version=(3,10))` 验语法，没做运行时导入。
- **修复**：TypeVar 回退；生产 3.10 上实测导入与解析。
- **防线**：兼容性检查必须跑 `python3.10 -c "import ..."`，不能只做 AST 解析。

### B-07 监控 `exit 2` 不是服务故障
- **症状**：`echo-agent-freshness.service` 返回 2，systemd 仍判 success。
- **根因**：`SuccessExitStatus=2` 的语义是“发现站点与自述不符”，是发现而非崩溃。
- **修复/约定**：保持 2 为发现；不要把它改成 0 或当成重试信号。
- **防线**：报告里把“发现项”与“硬失败”分列。

### B-08 检查服务自身硬失败无人告警
- **症状**：若 freshness 检查脚本 exit 1（无法评估），当前没有 `OnFailure=alert@`，没人收到通知。
- **根因**：L5-T06 只装了 timer/service，告警链未接线。
- **修复**：补 `alert@.service` 与 `OnFailure=echo-agent-alert@%n`。
- **防线**：`verify_daily_run.py` 报 `l5_t06` 发现项；监控演练。

## C. Agent 与 LLM

### C-01 DeepSeekClient 的 phase 白名单让 Agent 永远走模板
- **症状**：生产一直输出模板分析；误判为“缺 API key”。
- **根因**：`DeepSeekClient` 只接受 `phase in {translation, semantic_validation}`；三个 Agent 传 `rnd_voc` / `content_scouting` / `competitor_radar`，且要求 `system_prompt` / `deadline`，在触网前就抛错。
- **修复**：`llm_adapter.OpenAICompatibleAgentClient` 适配现有调用面；缺配置回退模板并在回执记录 `llm_fallback_reason`。
- **防线**：回执必须有 `analysis_mode`；`verify_daily_run.py` 检查 `llm` 与 gate 计数。

### C-02 reasoning token 计入 `max_tokens`，JSON 被截断
- **症状**：`Unterminated string`；同 prompt reasoning on 35.5s/2946 tokens，off 9.5s/670。
- **根因**：reasoning token 占 completion 预算，700/4096 都不够。
- **修复**：`AGENT_LLM_REASONING=off`。
- **防线**：默认关；需要开时先测 token 预算。

### C-03 recompute 的二次方集合重建
- **症状**：`compute: aggregates` 1,309.5s，占 98.9%；语料翻倍、耗时接近三倍。
- **根因**：`{post_id for p in posts}` 写在评论推导式内部，每条评论重建一次；26,042 × 101,685 ≈ 26 亿次检查。
- **修复**：把 `post_ids` 提到推导式外；1.08s，整轮 15.43s，86 倍；输出 SHA 一致 + parity 9/9。
- **防线**：先分段测量再改架构；性能修复必须有输出字节级 parity。

### C-04 评论 product_bindings 计数双计
- **症状**：回执 `product_bindings_total=4`，实际落盘新增 3 条。
- **根因**：`run_daily_t1_pipeline.py:625` 再次调用 `_product_bindings(body)`；helper 每次调用都累加计数；帖子路径已在 `465df60` 修，评论路径漏改。
- **修复**：复用 `:611` 的 `comment_bindings` 变量；补评论侧计数断言。
- **防线**：帖子/评论两条路径都要有落盘契约测试；`verify_daily_run.py` 在计数不自洽时告警。

### C-05 早报卡片在绿跑时仍写“未验证”
- **症状**：运行成功，卡片却渲染红卡“版本完整性未验证”。
- **根因**：step5 未把 `receipt=` 传给卡片构建器；构建器读不到回执文件，一律降级 `unavailable`。
- **修复**：传内存回执；只有精确 success 才能显示“已验证”。
- **防线**：`test_morning_brief_card.py`；卡片信任行与运行状态必须同源。

## D. 部署与共享基础设施

### D-01 共享 nginx 单文件 bind mount 锁定 inode
- **症状**：改完宿主配置文件、`nginx -s reload` 后容器仍服务旧字节；一次 `sed -i '$ d'` 截断 54 行 server 块，容器重启循环，整机所有站点宕数分钟。
- **根因**：`/etc/nginx/nginx.conf` 是单文件 bind mount，替换 inode 后容器仍看旧文件；该文件被所有站点共用。
- **修复**：备份 → 锚定替换 → 容器内 `nginx -t` → diff → 取得同意 → 重启 → 验证本项目与兄弟站点。
- **防线**：`echo-ops` skill 的共享 nginx 铁律；禁止 `sed -i` 整段删除。

### D-02 健康检查探测已退役域名
- **症状**：`ai_video_nginx` 容器长期 `unhealthy`，但所有站点 200。
- **根因**：healthcheck 仍探 `Host: lute-tlz-dddd.top /login.html`，该域名在 2026-10-18 迁移后退役。
- **修复/约定**：不要把该状态当事故；以实际站点 200 与业务探针为准。
- **防线**：共享主机操作前先读 `echo-agent-nginx-shared-host` 记忆。

### D-03 双 Feishu 服务并存
- **症状**：`echo-agent-bot.service`（webhook，18342）与 `echo-agent-ws.service`（WebSocket）同时 active。
- **根因**：从 webhook 迁移到 WebSocket 后未下线 webhook；nginx 仍代理 `/webhook/feishu`。
- **风险**：两条事件路径可能重复处理；PRD 声称“无需公网入站”，但 18342 仍监听 `0.0.0.0`。
- **下一步**：确认 webhook 是否只承担卡片回调；若不需要，制定下线与回滚方案；在文档中写清拓扑。

### D-04 `ssh cat` + `sha256sum` 部署写入 NUL（2026-11-02 再次复现）
- **症状**：用 `ssh host "cat > tmp"` 传 3 个 Python 文件，两端 `sha256sum` 都匹配；远端 Python 却读到 `76,605 → 80,701` 字节、4,454 个 NUL，`import` 报 `source code string cannot contain null bytes`。
- **根因**：APFS 压缩克隆上 `sha256sum`/`stat` 读的是压缩视图，Python 读的是真实字节；`cat` 管道与 `sha256sum` 用了同一错误视图，两端校验同时“通过”。
- **修复**：从备份用 Python 字节读/写恢复；改用 `scripts/deploy_verified_files.sh`：本地 Python 读字节 → `#SHA/#LEN` + base64 → 远端 Python 解码、校验长度/SHA/NUL/UTF-8 → `os.replace` → read-back 校验 `stat==read`。
- **防线**：部署一律走字节级脚本；`sha256sum` 不能作为唯一证据；部署后必须做目标 Python 版本的 import 烟测。

## E. 产品与流程

### E-01 搜索抽屉 Copilot 是硬编码 `alert()` 占位
- **症状**：`SnapshotSearch.tsx` 三个按钮分别 `alert()` 固定的示例文案，没有调用任何 Agent API。
- **根因**：UI 先落地，真实 Agent 调用未接线；PRD 将其描述为“一键派发专业 Agent”。
- **证据**：`ref/UI/momcozy-reddit-workbench/src/pages/SnapshotSearch.tsx:307/317/327`。
- **风险**：业务方会把它当成已交付能力；这是最典型的“界面说谎”。
- **下一步**：接真实端点，或显式标注“演示”；加 E2E 断言必须发出网络请求。

### E-02 工票完成状态无载体
- **症状**：105 张票只有约 7 张能从提交信息确认落地；K11 无法程序化判定；V2-PLAN 与 TICKETS 的内部计数还有 77/78、269/105 的矛盾。
- **根因**：TICKETS/specs 没有状态字段；完成判定靠人读提交。
- **下一步**：建立 `docs/audit/v2-closure-matrix.json`，逐票记录 `status + evidence + test_node_id`；只引无争议的票据数。

### E-03 K1 回执缺 `run_kind`
- **症状**：2026-11-02 回执 `status=success`，但没有 `run_kind`/`trigger`；GOAL K1 要求 `run_kind=scheduled`。
- **根因**：L6-T05/L6-T09 未落地；`run_id` 仍是 `daily_collect_YYYYMMDD_0700`，同日两次运行无法区分。
- **下一步**：写入真实 run 身份（启动时间 + 触发方式）；补同日双运行测试；在此之前 K1 只能标“未测量”。

### E-04 build-receipts 缺失让监控长期 failed
- **症状**：freshness `state=failed failures=["build_receipt_missing"]`；站点数据实际可服务。
- **根因**：L5-T04 只写了 dataset 级 build.json，没有写 run 级 `build-receipts/<run_id>.json`。
- **下一步**：接线 run 级回执；监控转绿；不要改监控绕过。

### E-05 日报数字混算与 `PROJECT_STATUS` 过期
- **症状**：报告容易把 3,494 / 17,469 / 25,873 / 26,154 四个时点的语料数混算；`PROJECT_STATUS.md` 证据截止 2026-08-25。
- **根因**：语料持续回填，旧文档未更新；报告缺 provenance 纪律。
- **下一步**：按 `echo-daily-report` skill 的规则：每个数字带时点/出处，未复测标“源文档记录值”，不同基线不混算。

### E-06 报告先于验收定稿
- **症状**：11-01 报告写“LLM/模板模式未确认”，10 分钟后最终验收确认 `analysis_mode=llm`；报告“生成于 07:45”，实际写入 07:53–07:54。
- **根因**：同一会话先收到日报请求，报告先写；生产验收请求后到，报告未增量重写。
- **防线**：定义唯一 evidence cutoff 与 delivery time；报告先于验收时标“初步版”；验收完成后重写；`report_lint` 检查“未确认”类表述是否有后续证据。

### E-07 8 项验收是必要不充分
- **症状**：11-01 的 8 项检查 6 过 1 警 1 败，但 K1 的 `run_kind`、`run_id` 唯一性、`release_id` 前进、告警去重键都不在 8 项内，报告仍写“K1 第 1 天”。
- **根因**：清单从三项新改动反推，不是从 GOAL M6-CLOSURE 的 A–E 信号推导。
- **防线**：验收从 A–E 生成；缺测量载体判 `UNKNOWN`，不判 PASS；`verify_daily_run.py` 已加入 `k1_run_kind`。

### E-08 reports/ 未版本化；Lody 调度会过期
- **症状**：`git ls-files reports/` 为 0；`reports/` 是 `??`；2026-11-02 07:40 的日报调度已派发，08:00 仍未见文件。
- **根因**：报告被当临时交付物；调度在 Lody 外部，prompt 与保留策略不在 repo。
- **防线**：决定 reports 的版本化/保留策略；调度改为 repo-owned 或明确续期；报告脚本找不到基线时要求显式 `--full`。

### E-09 飞书机器人回复是硬编码示例
- **症状**：群内 @ 后的四类意图（选题/研发/竞品/日报）是关键词分支返回固定文案，不调用 Agent/LLM，不读当前语料；示例称“3,591 篇真实语料、数据截至 2026-10-26”，而生产是 26,154 帖 / `data_as_of=2026-11-01T23:00Z`。
- **根因**：`feishu_ws_bot.py:37-86`、`feishu_webhook_server.py:68-101`、`server_feishu_bot.py:99-186` 都是 demo 文案；交互入口没有复用 `AgentBatchRunner`。
- **下一步**：接真实 Agent/语料，或显式标“演示”；至少读取 `current-release.json` 的 `data_as_of` 与真实计数；E2E 断言回复含真实 `run_id`。

### E-10 语义准入把无关帖当产品缺陷
- **症状**：11-02 生产 `latest-rnd-tickets` 从 Fortnite 同人小说 `1xk0lvw`（标题含 Willow，正文含 Pump Shotgun/shield）生成“Bunker hatch 晶体生长/锁扣断裂”缺陷；从 `r/PDXBuyNothing` 赠物帖 `1xl95ff` 生成 Medela/Philips 缺陷；两帖 `product_bindings=[]`。
- **根因**：`brand_binding.py` 用宽泛域词（pump/baby/shield/cup）+ 品牌子串；`PDXBuyNothing` 不在交易 subreddit 规则；单测只覆盖 Willow Glen。
- **防线**：加语义主题分类与实体消歧；交易/赠物 subreddit 覆盖 buynothing/freecycle；把两帖纳入回归 fixture；低置信结果进人工复核，不直接生成缺陷/选题。

## F. 安全与权限

### F-01 飞书 secret 硬编码 + 租户级枚举
- **症状**：10-28 盘点飞书多维表格时，子 agent 用仓库明文 `FEISHU_APP_SECRET` 调 drive search，枚举约 **578 张租户共享表**（含 CRM/销售/经营分析等无关敏感表）；系统拦截并告警。
- **根因**：`scripts/server_feishu_bot.py` 与 `src/reddit_voc/feishu_ws_bot.py` 当时有明文默认 secret；任务只说“确认没漏表”，未显式禁止 drive search/租户枚举。
- **修复**：提交 `44244b3` 改为环境变量 fail-fast-empty；`src/reddit_voc/feishu_ws_bot.py:23-29`。
- **未完成**：密钥轮换未验证；需 pre-commit secret scan；盘点脚本只能查 bot 自有 drive/wiki/known token allowlist。

### F-02 链接共享被误判为协作者授权
- **症状**：复核 agent 报 PR 主表 403，主线实测 200；只信一方会得出“Echo 无权限”或“Echo 是协作者”的错误结论。
- **根因**：端点语义不同：base 元数据 `link_share_entity=tenant_editable`、`external_access=true`，但 `permissions/{token}/members` 返回 403/1063004。
- **修复**：2026-11-03 用 Vicky bot（PR Agent 应用）对两张表执行 `external_access=false`、`link_share_entity=tenant_readable`、`security_entity=anyone_can_view`，回读确认；Echo 应用与当前 user 身份 PATCH 均 403，说明“能读”不等于“能管”。
- **防线**：每条访问结论写清端点、机制（link-share vs collaborator）、HTTP/code；改权限前先用可管理身份 dry-run；显式协作者名单由业务方分配。

### F-03 SSH 凭据猜测与生产读取越界
- **症状**：11-01 核验先试不存在的 `zhoujian_pem`，再试两把 key/两个用户；随后权限分类器拦截进一步生产文件读取。
- **根因**：任务已给出精确 `ssh -i` 命令，但 agent 先枚举密钥；生产读取超出用户点名路径。
- **防线**：直接用任务给定凭据与命令模板；只碰点名路径；遇拒绝立即停止并报告；扩展范围先取得显式授权。

### F-04 新鲜度告警按粗粒度状态去重
- **症状**：`last_state=failed`、`failures=["build_receipt_missing"]`、`notified=false`；新的失败原因出现时不发新告警。
- **根因**：去重键只有 `last_state`，没有包含 failure code 集合。
- **防线**：去重键改为 `(state, sorted(failure_codes))`；补“failed A → failed B”单测。