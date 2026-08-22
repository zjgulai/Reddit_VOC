---
title: Reddit VOC Adversarial Audit
doc_type: adversarial_audit
status: active
created: 2026-07-07
updated: 2026-07-07
owner: codex
project: Reddit_VOC
production_boundary: production unchanged
provider_call: false
live_send: false
---

# Reddit VOC Adversarial Audit

## 1. 审计立场

本审计按“线上动作会失败、用户会从钉钉手机端打开、密钥不能写进仓库、Reddit/TikHub 返回结构可能变化、机器可能睡眠、报告会被业务用户直接阅读”的对抗式假设检查当前项目。

## 2. 结论摘要

| 编号 | 风险 | 严重度 | 现状 | 本轮动作 |
|---|---|---:|---|---|
| A1 | artifact URL 把本地绝对路径拼进钉钉链接 | 高 | 已发现 | 已修复并加测试 |
| A2 | launchd 无法安全加载 runtime secret | 高 | 已发现 | 已新增外部 env loader |
| A3 | TikHub provider call 仍未真实跑通 | 高 | blocked | 等 `TIKHUB_API_KEY` |
| A4 | DingTalk live send 依赖公网 artifact base URL | 高 | blocked | 已写 runbook |
| A5 | HTML 报告中文风格不完全统一 | 中 | 部分英文元字段 | 已将明细表、评论元信息和嵌入 PNG 中文化 |
| A6 | 翻译 provider 运行时配置缺失会导致未知文本不翻译 | 中 | 已接入 LibreTranslate-compatible provider，待生产 runtime env 配置 | 配置 `REDDIT_VOC_TRANSLATION_MODE=libretranslate` 与 `LIBRETRANSLATE_BASE_URL` 后做质量抽检 |
| A7 | P2 社区可能引入泛母婴噪音 | 中 | 配置已分层 | 待 3-5 天精度复核 |
| A8 | 本机睡眠会跳过 launchd 定时 | 中 | 未验证 | 待运行环境策略 |
| A9 | TikHub 返回结构漂移可能导致空采集 | 中 | 有部分解析 fallback | 待真实 provider smoke 扩展 fixture |
| A10 | 单 HTML 报告可读性还可继续增强 | 低 | 已可用 | 本轮先修中文化和链接 |

## 3. 已执行修复

### A1: artifact URL 不应包含本地绝对路径

问题：

- `REDDIT_VOC_ARTIFACT_BASE_URL` 存在时，旧逻辑把 `/var/folders/.../run-id.html` 或 `/Users/.../outputs/run-id.html` 拼到 URL 后面。
- 钉钉端会看到不可访问或泄漏本机路径结构的链接。

修复：

- `src/reddit_voc/dingtalk.py`：artifact URL 改为 `base_url/<filename>`。
- `src/reddit_voc/daily_report.py`：日报 HTML、XLSX、CSV、PNG 链接同样只拼文件名。
- `tests/test_dingtalk_delivery.py` 和 `tests/test_daily_report.py` 增加 `assertNotIn("/var/folders/")`。

### A2: launchd 安全加载 secret

问题：

- launchd 任务不能继承交互式 shell 的 key。
- 如果把 key 写进 plist 或 repo 配置，会违反 secret 边界。

修复：

- 新增 `scripts/load_runtime_env.sh`。
- `scripts/run_daily_collect.sh`、`scripts/run_daily_report.sh`、`scripts/run_daily_report_dry_run.sh` 已加载可选 `REDDIT_VOC_ENV_FILE`。
- env 文件必须在项目外，且 group/other 权限为 0。

### A5: HTML 报告中文化

问题：

- 明细表里有 `Subreddit`, `Post ID`, `发帖时间UTC`。
- 评论整合单元格里有 `comment_id`, `score`, `depth`。
- 嵌入 PNG 里有 `run_id=` 和 `Top 5`。

修复：

- 明细表头改为 `社区`, `帖子 ID`, `发帖时间（UTC）`。
- 评论元信息改为 `评论ID`, `分数`, `层级`。
- PNG 元信息改为 `运行 ID`、`采集窗口`，图表标题改为 `主题前五`、`痛点前五`。
- HTML/PNG 视觉风格由偏米色调整为更克制的浅灰蓝报表风格。

## 4. 未执行线上任务的解决方案

### Phase 1: TikHub provider smoke

TODO:

- [ ] 用户准备 `~/.reddit-voc/secrets/reddit-voc-live.env`。
- [ ] 执行 `REDDIT_VOC_ENV_FILE=... REDDIT_VOC_MAX_DETAIL_POSTS=5 scripts/run_daily_collect.sh`。
- [ ] 检查 collector summary 的 `provider_call=true`、窗口时间和采集量。
- [ ] 若失败，按 `reason` 分支处理：鉴权、额度、结构漂移、空结果。

### Phase 2: artifact hosting

TODO:

- [ ] 选择静态文件服务或对象存储。
- [ ] 发布 HTML/XLSX/CSV/PNG 到 `REDDIT_VOC_ARTIFACT_BASE_URL`。
- [ ] 从钉钉移动端或非本机网络打开 HTML。
- [ ] 验证链接只包含文件名，不包含本地路径。

### Phase 3: DingTalk live-send

TODO:

- [ ] 确认 Phase 1 有真实数据，不能用 fixture 当业务日报。
- [ ] 设置 `REDDIT_VOC_DINGTALK_MODE=live` 和 webhook env。
- [ ] 执行 `REDDIT_VOC_SOURCE_RUN_ID=<run_id> scripts/run_daily_report.sh`。
- [ ] 验证 DingTalk `errcode=0`、本地 delivery row 和 `status-summary`。

### Phase 4: launchd production-shape run

TODO:

- [ ] 复制两个 launchd plist 到 `~/Library/LaunchAgents/`。
- [ ] 通过 `PlistBuddy` 添加 `REDDIT_VOC_ENV_FILE`。
- [ ] `plutil -lint`。
- [ ] `launchctl load`。
- [ ] 次日检查 07:00 collect、08:00 report 和 `missed-run-check`。

### Phase 5: P2 社区精度复核

TODO:

- [ ] 连续 3-5 天导出命中样本。
- [ ] 标注 true positive / false positive。
- [ ] 如果 P2 false positive 高，则降低到 search-only 或加入更严格 brand/product 约束。

### Phase 6: 翻译能力

TODO:

- [ ] 确认是否使用 provider 翻译或本地模型。
- [x] 新增 LibreTranslate-compatible 翻译 provider gate：默认仍为 dry-run，生产需 runtime env 配置 endpoint。
- [ ] 对未知英文正文/评论做质量抽检，避免错误翻译进入业务报告。

## 5. HTML 报告优化建议

已完成：

- 中文故事线存在：结论、情绪主题、痛点、证据链、建议动作、可视化总览、底部明细。
- 明细表头、评论元信息和嵌入 PNG 已中文化。
- 钉钉 artifact 链接修复为公网 base URL + 文件名。

仍可优化：

- 增加“数据边界”模块：说明采集窗口、provider、coverage、是否 partial。
- 增加“行动优先级”标签：立即处理、观察、归档。
- 增加“高风险原话摘录”：只展示短摘录和链接，避免报告过长。
- 增加“竞品对比”独立模块：当 competitors 非空时自动展示。
- 对空报告设计专门的健康检查版式，避免业务方误以为系统未运行。

## 6. 当前不可声明完成的事项

- 不能声明 TikHub 线上采集完成，因为没有新鲜 provider call 证据。
- 不能声明 DingTalk 08:00 业务日报已投产，因为没有 artifact host 和 live-send 验收。
- 不能声明 launchd 已安装，因为当前只验证模板和脚本。
- 不能声明中文翻译已完整自动化，因为未知文本仍是 dry-run provider-required 状态。
