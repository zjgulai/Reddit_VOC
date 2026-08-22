---
title: Reddit VOC Online Actions Runbook
doc_type: runbook
status: active
created: 2026-07-07
updated: 2026-07-09
owner: codex
project: Reddit_VOC
production_boundary: production unchanged
provider_call: false
live_send: false
---

# Reddit VOC Online Actions Runbook

## 1. 当前未执行的线上动作

| 动作 | 当前状态 | 需要什么 | 成功验收 | 失败停止条件 |
|---|---|---|---|---|
| TikHub Reddit provider 采集 | blocked | `TIKHUB_API_KEY`, `REDDIT_VOC_ENABLE_TIKHUB=1`, `--authorize-provider-call` | 07:00 窗口内有 collector summary，`provider_call=true` 只出现在真实 provider run | key 缺失、额度/鉴权失败、返回结构不匹配 |
| Artifact hosting | blocked | 可从钉钉端访问的 `REDDIT_VOC_ARTIFACT_BASE_URL` | HTML/XLSX/CSV/PNG 链接在钉钉移动端可打开 | base URL 不可访问或链接仍指向本地路径 |
| DingTalk 08:00 live send | blocked | `DINGTALK_WEBHOOK_URL`, 可选 `DINGTALK_WEBHOOK_SECRET`, `REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND=1`, `REDDIT_VOC_DINGTALK_MODE=live`, `--authorize-live-send` | DingTalk 返回 `errcode=0`，本地 delivery row 记录 `live_send=true` | 无真实数据、无 artifact base URL、webhook 缺失、非 0 errcode |
| launchd 定时安装 | not_installed | owner 明确授权，外部 env 文件已准备好 | 07:00 collect 和 08:00 report 均被 launchd 触发，`missed-run-check=covered` | 未准备 secret、机器睡眠、权限或 plist 校验失败 |
| Reddit browser read-only fallback | unverified | 专用 Chrome profile 完成 Reddit 登录，CDP 可用 | `.json` smoke 返回 `browser_status=ok` 并可入库 | login wall、CAPTCHA、非 JSON、评论树不完整 |
| 翻译 provider | implemented_pending_runtime_config | `REDDIT_VOC_TRANSLATION_MODE=libretranslate`, `LIBRETRANSLATE_BASE_URL`, 可选 `LIBRETRANSLATE_API_KEY` | 未知英文正文/评论进入 `正文中文` 与 `评论整合中文` | endpoint 缺失、服务异常、翻译质量不可控 |

## 2. API key 和 webhook 给我的安全方式

不要把真实 key、webhook、secret 直接写进仓库文件、Markdown、测试、日志或聊天总结。推荐使用仓库外的本机 env 文件：

```bash
mkdir -p ~/.reddit-voc/secrets
chmod 700 ~/.reddit-voc ~/.reddit-voc/secrets
umask 077
cat > ~/.reddit-voc/secrets/reddit-voc-live.env <<'EOF'
export REDDIT_VOC_ENABLE_TIKHUB=1
export TIKHUB_BASE_URL='https://api.tikhub.io'
export TIKHUB_API_KEY='在这里填 TikHub API key'

export REDDIT_VOC_ARTIFACT_BASE_URL='https://你的文件服务/reddit-voc'

export REDDIT_VOC_DINGTALK_MODE=live
export REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND=1
export DINGTALK_REQUIRED_KEYWORD='LL'
export DINGTALK_WEBHOOK_URL='在这里填钉钉机器人 webhook URL'
export DINGTALK_WEBHOOK_SECRET='如果机器人启用加签就在这里填，否则留空'
EOF
chmod 600 ~/.reddit-voc/secrets/reddit-voc-live.env
```

然后告诉我：

```text
请使用 REDDIT_VOC_ENV_FILE=~/.reddit-voc/secrets/reddit-voc-live.env 执行线上 TikHub 采集和钉钉 live-send 验收。
```

如果只想做一次临时命令，也可以在同一个 shell 里 `export TIKHUB_API_KEY=...`、`export DINGTALK_WEBHOOK_URL=...` 后让我执行；但长期定时任务建议使用 `REDDIT_VOC_ENV_FILE`。

## 3. 手动线上验收顺序

### Phase A: provider 采集 smoke

```bash
REDDIT_VOC_ENV_FILE=~/.reddit-voc/secrets/reddit-voc-live.env \
REDDIT_VOC_RUN_ID=provider_smoke_$(TZ=Asia/Shanghai date +%Y%m%d_%H%M) \
REDDIT_VOC_MAX_DETAIL_POSTS=5 \
scripts/run_daily_collect.sh
```

验收：

- `outputs/<run_id>-collector-summary.json` 存在。
- `provider_call=true` 只出现在 TikHub collector summary 或 run row。
- `window_start_utc` 到 `window_end_utc` 对应北京时间 `[D-1 07:00, D 07:00)`。
- 不接受旧帖新评论作为新帖。

### Phase B: artifact hosting

把当前 run 的以下文件发布到 `REDDIT_VOC_ARTIFACT_BASE_URL` 指向的位置：

- `<run_id>-insight-report.html`
- `<run_id>-daily-detail.xlsx`
- `<run_id>-daily-detail.csv`
- `<run_id>-insights.png`

验收：

- 钉钉客户端所在网络可以打开 `https://.../<run_id>-insight-report.html`。
- 链接里只有文件名，不包含 `/Users/...` 或 `/var/folders/...`。

### Phase C: 08:00 钉钉 live-send smoke

```bash
REDDIT_VOC_ENV_FILE=~/.reddit-voc/secrets/reddit-voc-live.env \
REDDIT_VOC_SOURCE_RUN_ID=<Phase-A-run-id> \
scripts/run_daily_report.sh
```

验收：

- `outputs/<run_id>-daily-report-live-send.json` 中 `status=sent`。
- DingTalk response `errcode=0`。
- 本地 `status-summary` 显示 `live_send=true`。
- 群消息首要链接是 HTML 报告，其次是 XLSX/CSV/PNG。

### Phase D: launchd 安装

仅在 Phase A-C 通过后安装：

```bash
cp config/launchd/com.reddit-voc.daily-collect.plist.template ~/Library/LaunchAgents/com.reddit-voc.daily-collect.plist
cp config/launchd/com.reddit-voc.daily-report.plist.template ~/Library/LaunchAgents/com.reddit-voc.daily-report.plist

/usr/libexec/PlistBuddy -c "Add :EnvironmentVariables:REDDIT_VOC_ENV_FILE string $HOME/.reddit-voc/secrets/reddit-voc-live.env" ~/Library/LaunchAgents/com.reddit-voc.daily-collect.plist
/usr/libexec/PlistBuddy -c "Add :EnvironmentVariables:REDDIT_VOC_ENV_FILE string $HOME/.reddit-voc/secrets/reddit-voc-live.env" ~/Library/LaunchAgents/com.reddit-voc.daily-report.plist

plutil -lint ~/Library/LaunchAgents/com.reddit-voc.daily-collect.plist ~/Library/LaunchAgents/com.reddit-voc.daily-report.plist
launchctl load ~/Library/LaunchAgents/com.reddit-voc.daily-collect.plist
launchctl load ~/Library/LaunchAgents/com.reddit-voc.daily-report.plist
```

卸载：

```bash
launchctl unload ~/Library/LaunchAgents/com.reddit-voc.daily-collect.plist || true
launchctl unload ~/Library/LaunchAgents/com.reddit-voc.daily-report.plist || true
```

## 4. 本轮已执行的本地支撑变更

- 新增 `scripts/load_runtime_env.sh`：支持 `REDDIT_VOC_ENV_FILE`，阻止项目内 secret 文件，要求 group/other 权限为 0。
- `scripts/run_daily_collect.sh`、`scripts/run_daily_report.sh`、`scripts/run_daily_report_dry_run.sh` 已接入外部 env 文件加载。
- DingTalk 和日报 artifact URL 已修正为 `base_url/<artifact_filename>`，不再把本地绝对路径拼进 URL。

## 5. 仍未执行的线上动作

截至本文档生成时，本轮未执行 TikHub provider call、未发送 DingTalk live message、未安装 launchd、未发布 artifact hosting。当前证据层级仍是 local validation / dry-run。
