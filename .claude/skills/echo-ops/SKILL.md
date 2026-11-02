---
name: echo-ops
description: Echo-Agent 生产运维与验收：radar.luteos.com 日更流水线只读核验、发布代际/指针/公网字节自证、共享 nginx 与部署陷阱、故障分诊。用于“今天流水线跑成功了吗”“/data 404 或页面空”“manifest SHA 不一致”“发版前后检查”“代际/回滚”等场景；默认只读，不执行重启、发布、写入或改指针。
---

# Echo-Agent 生产运维与验收

这个 skill 把 2026-07~11 的线上事故与每日人工核对固化成可执行门禁。它回答四个问题：

1. 07:05 的日更真的成功了吗（而不是只看 `/` 返回 200）？
2. 公网 `/data/` 的字节是不是当前代际的字节（而不是缓存、SPA fallback 或旧代）？
3. 七个数据集是否各自自证（指针 SHA = manifest 字节 SHA = build.json）？
4. 失败时，上一代是否仍可服务，指针是否只被替换一次？

## 1. 何时使用

- 每天 07:30 后核对 `echo-agent-daily.timer` 的运行结果；
- 发布/热修前后确认生产代码、数据、前端同代；
- 页面出现空数据、`manifest SHA-256 不一致`、`/data/` 404、监控红卡；
- 需要判断“是数据缺陷、发布缺陷，还是缓存/挂载假象”；
- 需要给下一批修复排优先级时，先确认当前生产基线。

不适用：纯文档改动、SI-Agent 的镜像发版（用 `deploy-preflight`）、普通前端开发。

## 2. 先读权威

1. `docs/v2/GOAL.md`：北极星、K1–K11、五波退出闸门、14 天闭环定义；
2. `docs/v2/V2-PLAN.md`、`docs/v2/TICKETS.md`：施工顺序与票面验收；
3. `docs/prd/PRD-V3.0-Echo-Agent-Platform.md`：双端形态（飞书机器人 + 工作台）；
4. 本 skill 的 [事故与坑点目录](references/incidents.md)；
5. 跨会话记忆：`~/.claude/projects/-Users-lute-Project-Echo-Agent/memory/`。

`PROJECT_STATUS.md` 的证据截止是 2026-08-25；10 月之后以 `docs/v2`、ADR、git 与生产回执为准。

## 3. 铁律

1. **默认只读**。不重启容器、不 retag、不 rsync、不改 pointer、不写生产数据；任何写操作先取得用户明确同意。
2. **证据优先于 200**。`/` 返回 200 可能只是 SPA fallback；必须查 `/data/...` 的 `content-type`、字节 SHA 与 payload。
3. **公网读取要 cache-bust**。加 `?cb=<timestamp>` 并设 `Cache-Control: no-cache`；普通 `curl` 可能读到旧指针（本机 2026-11-02 实测过一次 `generated_at_utc=null` 的假象）。
4. **指针必须是相对符号链接**。绝对链接在 nginx 容器 bind mount 内悬空，会造成 `/data/` 全 404 而 `/` 假健康。
5. **manifest 三件套同批更新**：文件字节数、SHA-256、`current-release.json` binding；只改一个就会让前端拒绝渲染。
6. **共享 nginx 不可就地改**。`/opt/ai-video/deploy/lighthouse/nginx.conf` 被所有站点共用；先备份、锚定替换、容器内 `nginx -t`、diff、取得同意、重启，再验证本项目和至少一个兄弟站点。禁止 `sed -i` 整段删除。
7. **K1 计数会被人工干预重置**。任何手改 pointer、手修权限、人工重跑都使连续 14 天归零；报告时必须说明。
8. **先诊断后修复**。审计阶段只收集证据；未获授权不要顺手改代码或生产。
9. **数字带时点与出处**。四个语料基线（3,494 / 17,469 / 25,873 / 26,154+）不可混算。
10. **凭据与权限边界**：secret 只从环境变量读取，缺失即 fail-fast；不要把 secret 放进子 agent 上下文；飞书盘点只查 bot 自有 drive/wiki/已知 token allowlist，**禁止 drive search 与租户级枚举**；遇到权限拒绝立即停止并报告，不猜密钥、不扩大读取范围。
11. **报告与验收的时序**：报告如果先于生产验收生成，必须标“初步版，待验收”；验收完成后增量重写。KPI 没有测量载体时写“未测量”，不写“第 N 天”。
12. **部署必须走字节级通道**：用 `scripts/deploy_verified_files.sh`（Python 读字节 → base64 → 远端 Python read-back + NUL/UTF-8 校验 → `os.replace`）；不要用 `ssh cat > file`、`scp` + `sha256sum` 作为唯一证据。2026-11-02 实测：`ssh cat` 后两端 `sha256sum` 都“通过”，远端 Python 却读到 4,454 个 NUL；APFS 上 `sha256sum` 可能读压缩视图。

## 4. 每日运行验收

```bash
python3 .claude/skills/echo-ops/scripts/verify_daily_run.py \
  --ssh-host ubuntu@43.163.92.244 \
  --ssh-key "${ECHO_SSH_KEY:?set ECHO_SSH_KEY to the production private key}" \
  --json-out reports/evidence/verify-$(date +%Y%m%d).json
```

退出码：

| 码 | 含义 | 处理 |
|---|---|---|
| 0 | 全部硬检查通过 | 可对外说“运行成功” |
| 1 | 硬失败（运行/指针/公网字节/build stamp 不一致） | 立即按第 6 节分诊，不要只重跑 |
| 2 | 发现项（数据可服务，但已知闭环票未完成） | 记录为待办；不要谎报全绿 |
| 3 | 检查本身无法评估（SSH/解析失败） | 先修检查，不把失败当通过 |

脚本覆盖：systemd 结果、10 个步骤、LLM 模式与证据门禁、product_bindings 计数、指针相对性、代际数量、7 个 build stamp 自证、`build-receipts/`、freshness 状态、公网 content-type/SHA/run_id/generated_at/data_as_of、磁盘余量。

**当前预期结果（2026-11-02 基线）**：16 PASS / 0 FAIL / 2 FIND（K1 缺 `run_kind`、`build-receipts/` 缺失）/ 1 WARN（freshness partial）。看到这 2 个 FIND 不是新事故，是 L5-T04/L6-T05 未收尾。

## 5. 发布/代际检查

发版或数据发布后，按顺序确认：

```bash
# 1) 指针是相对链接且目标存在
readlink /opt/voc-report/html/data/reddit-voc
readlink -f /opt/voc-report/html/data/reddit-voc

# 2) 公网字节与代际文件一致（必须 cache-bust）
curl -sS -H 'Cache-Control: no-cache' \
  'https://radar.luteos.com/data/reddit-voc/current-release.json?cb='$(date +%s) \
  -o /tmp/pr.json -w '%{http_code} %{content_type}\n'
sha256sum /tmp/pr.json
sha256sum "$(readlink -f /opt/voc-report/html/data/reddit-voc)/current-release.json"

# 3) 七个数据集自证（只读，不写生产状态）
cd /opt/echo-agent-bot && \
PYTHONPATH=/opt/echo-agent-bot:/opt/echo-agent-bot/scripts \
python3 scripts/check_site_freshness.py \
  --public-root /opt/voc-report/html \
  --state-path /tmp/echo-verify-freshness.json --no-notify
```

判读：

- `state=failed` 且 `failures=["build_receipt_missing"]`：站点数据本身可服务，缺的是 L5-T04 run 级回执；
- `release_manifest_sha_mismatch:<key>`：binding 与 manifest 字节不一致，先查是哪一步写了数据集但没同步 binding；
- `build_stamp_missing:<key>`：该数据集没有 `build.json`，或路径深度不是 `find -H` 能覆盖的（insights/reports 在 `public/` 下）；
- 公网 SHA 与代际 SHA 不一致：先加 `?cb=` 重试；仍不一致再查 nginx 缓存/挂载，不要直接改数据。

## 6. 故障分诊

| 症状 | 第一检查 | 常见根因 | 处理 |
|---|---|---|---|
| `/data/` 404，`/` 200 | `readlink` 是否绝对路径 | 绝对 symlink 在容器内悬空 | 改回相对链接；不要只改 nginx |
| 页面显示 `manifest SHA-256 不一致` | 用 cache-bust 重取公网指针 | 浏览器 `force-cache` 或发布未同步 binding | 前端 `no-cache`；同批刷新 manifest+bytes+binding |
| 页面空但接口 200 | `content-type` 是否 `application/json` | SPA fallback 把空壳伪装成健康 | 查 `/data/` 真实文件，不看 `/` |
| 流水线 exit 1 | 回执 `steps` 与 `errors` | 回执 JSON 序列化、权限、recompute | 先读回执与 journalctl；不要盲目重跑 |
| 混合代际（新 base + 旧指标） | `release_transaction.mode` 与 live 树 | 失败运行写入了 live 树 | 必须走 generation 事务；失败运行对 live 零字节 |
| 并发第二次运行 | 退出码 3 `aborted_already_running` | 单写者锁生效 | 这是正确行为；不要删锁文件 |
| 监控红卡 `build_receipt_missing` | `build-receipts/` 是否存在 | L5-T04 未接线 | 补 run 级回执，不要改监控绕过 |
| 飞书卡片“未验证” | 卡片构建器是否收到内存回执 | step5 未传 `receipt=` | 传本次运行回执；非 success 一律红标 |

## 7. 已知未完项（截至 2026-11-02）

1. **L5-T04**：代码已于 2026-11-02 接线（成功写发布代、失败写私有代），但**尚未部署**；生产仍报 `build_receipt_missing`；
2. **L5-T06**：`echo-agent-freshness.service` 缺 `OnFailure=alert@` 与 `alert@.service`，检查服务自身硬失败时无人告警；
3. **K1 口径**：代码已实现 `run_kind`/`trigger`/带秒 `run_id`，但**尚未部署**；当前生产回执仍无这些字段，11-01/11-02 报告写“第 1/2 天”没有测量载体；
4. **评论 product_bindings 双计**：代码已修（`:625` 复用 `:611`），但**尚未部署**；生产旧代码仍可能虚计；
5. **存量 product_bindings 未回填**：L1-T05 只对新合并行生效，历史回填是 Wave 5 独立 opt-in；
6. **工票完成无跟踪**：`docs/audit/v2-closure-matrix.json` 尚不存在，K11 无法程序化判定；
7. **V3 产品缺口**：飞书机器人/工作台双轨已成型，但飞书四类意图回复是硬编码示例（声称 3,591 篇/2026-10-26，生产为 26,154 帖/11-01）、搜索抽屉 Copilot 三按钮是 `alert()` 假按钮、TikTok/Instagram/Facebook/独立站博客四渠道仍是 PRD 承诺而非已交付；
8. **告警去重过粗**：freshness 只按 `last_state` 去重，`failed A → failed B` 不触发新告警；应改为 `(state, sorted(failure_codes))`；
9. **L5-T03 定时炸弹**：三个数据集校验器已放行 `build.json`（2026-11-02 代码修复，待部署）；部署前下一次离手重建仍可能因 undeclared file 失败；
10. **凭据**：`FEISHU_APP_SECRET` 曾硬编码并发生租户表枚举；代码已改 env-only，但密钥轮换未验证；PR 侧两张表仍 `tenant_editable`/`anyone_can_edit`；
11. **报告与调度**：`reports/` 未纳入 git；Lody 日报调度 7 天后是否过期待验证；11-02 日报 07:52 已生成，但仍把 K1 写成“第 2 天”（回执无 `run_kind`）。

## 8. 相关测试

```bash
# 发布事务与指针
.venv/bin/python -m pytest tests/test_daily_pipeline_transaction_wiring.py \
  tests/test_daily_release_transaction.py tests/test_daily_pipeline_lock.py -q

# 站点自证与新鲜度
.venv/bin/python -m pytest tests/test_build_receipt.py \
  tests/test_check_site_freshness.py tests/test_daily_pipeline_preflight.py -q

# 产品绑定
.venv/bin/python -m pytest tests/test_merge_product_bindings.py -q

# Agent / 证据门禁
.venv/bin/python -m pytest tests/agents -q

# 验收脚本自身（离线，无 SSH/HTTP）
.venv/bin/python -m pytest tests/test_verify_daily_run.py -q
```

只跑与改动相关的 lane；全量套件约 2,264 项，存在 1 个冻结基线失败，先看 `config/ci/known-failures.json`。

## 9. 边界

- 本 skill 不替代浏览器逐页验收；涉及前端渲染时仍要打开 `/dashboard`、`/dashboard/analytics`、`/dashboard/insights`、`/dashboard/reports`、`/dashboard/search` 并检查 `失败|不一致|不受支持|暂不可用`；
- 不执行生产写入、restart、部署、回滚；这些需要单独授权；
- 不把“脚本 exit 0”当成“业务正确”；脚本只证明它检查的那几条契约。