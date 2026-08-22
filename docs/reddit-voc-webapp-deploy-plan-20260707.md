---
title: Reddit VOC Website Deployment Plan
doc_type: execution_plan
status: active
created: 2026-07-07
updated: 2026-07-08
owner: codex
project: Reddit_VOC
production_boundary: authorized_live_operational_partial
provider_call: true
live_send: true
---

# Reddit VOC Website Deployment Plan

## 目标

建设一个独立的 Reddit VOC 网站，读取当前项目的配置、SQLite 数据库和输出产物，面向 Momcozy Reddit 监听运营提供三个模块：

- 采集模块：展示 07:00 北京时间采集、滚动 24 小时、08:00 钉钉推送、Provider、Subreddit、关键词和执行命令草案。
- 数据看板：展示最近批次和历史累计 Reddit 帖子、评论、情感、议题、严重度、原帖链接和同帖评论整合。
- 舆情洞察：沿用单 HTML 日报的中文洞察风格，同时增加历史累计样本洞察、分布图和最新 HTML 报告预览。

## 技术方案

- 前端：`webapp/static/index.html`、`styles.css`、`app.js`，无外部 CDN 依赖。
- 后端：`webapp/app.py`，Python 标准库 `ThreadingHTTPServer`，只读读取 `data/`、`outputs/`、`config/`。
- API：`/api/settings`、`/api/dashboard`、`/api/insights`、`/api/artifacts`、`/api/health`。
- 容器：`webapp/Dockerfile` 复制站点代码并安装 `Pillow`、`openpyxl`；运行时通过 Docker volume 挂载服务器上的 `config/`、`data/`、`outputs/`、`logs/`、`src/`、`scripts/`、`docs/`。
- 数据保留：部署包和 Docker build context 不携带 `data/`、`outputs/`；远端部署只替换代码、配置和文档，不删除服务器历史数据库与产物。
- 服务器：部署到 `/opt/reddit-voc-site`，运行 `reddit_voc_site_app` 容器，端口绑定 `127.0.0.1:18337->8080`，同时接入现有 `lighthouse_ai_video_net`。
- Nginx：在现有 `ai_video_nginx` 上为 `reddit.brand.lute-tlz-dddd.top` 增加独立 HTTP/HTTPS server block，HTTP 自动跳转 HTTPS，HTTPS 使用 Let's Encrypt 证书并继承现有 `auth_gate.conf` 登录保护。
- 自动化：服务器 `/etc/cron.d/reddit-voc-site` 使用 `CRON_TZ=Asia/Shanghai`，每天 07:00 执行采集脚本，每天 08:00 执行报告脚本。脚本读取 repo 外部 runtime env 文件；缺失密钥时只写 blocked artifact，不触发 provider call 或 DingTalk live send。

## 执行 TODO

- [x] 熟悉服务器：SSH、Docker、现有 Nginx 容器、DNS 和端口占用已核验。
- [x] 本地开发：新增只读网站、API、样式、交互和测试。
- [x] 本地验收：运行单元测试、启动本地站点、检查 API 和页面渲染。
- [x] 远端部署：上传排除密钥的部署包，在新目录构建并启动 Docker 容器。
- [x] Nginx 接入：备份并幂等追加站点配置，执行 `nginx -t` 后 reload。
- [x] HTTPS 验收：`https://reddit.brand.lute-tlz-dddd.top/` 证书签发成功，公网访问进入统一登录网关。
- [x] Cron 骨架：服务器 07:00/08:00 定时任务已安装，当前因 runtime env 缺失保持 blocked-safe。
- [x] E2E 验收：服务器内网应用页面、API、容器挂载、artifact 访问和 blocked artifact 验证通过。
- [x] 风险复盘：证书、鉴权、数据刷新、自动化密钥和后续 live activation 已记录。

## 验收证据

- 本地测试：`PYTHONPATH=src:. python3 -m unittest discover -s tests -v`，65 tests OK。
- 最新本地测试：`PYTHONPATH=src:. python3 -m unittest discover -s tests -v`，67 tests OK。
- 本地页面：`http://127.0.0.1:18765/` Playwright 截图通过，表格 1 行，中文抽屉标题 `Momcozy M5 在工作时漏奶`。
- 远端容器：`reddit_voc_site_app Up`，端口 `127.0.0.1:18337->8080/tcp`。
- 远端 API：`http://127.0.0.1:18337/api/health` 返回 `sqlite_files=14`、`artifacts=144`。
- 数据保留回归：修复后重新部署，部署前后远端 `data=14`、`outputs=144` 保持不变；最终 Docker build context 约 `10.81kB`。
- 公网 HTTPS：`curl -I https://reddit.brand.lute-tlz-dddd.top/` 返回 HTTP/2 302，跳转到统一登录页，说明站点处于现有鉴权保护后。
- 证书：`CN=reddit.brand.lute-tlz-dddd.top`，issuer `Let's Encrypt YE1`，有效期 `2026-07-07` 到 `2026-10-05`。
- 内网页面：`http://127.0.0.1:18337/` 返回中文控制台，包含 `采集模块`、`数据看板`、`舆情洞察`。
- 内网配置 API：`/api/settings` 返回 `collection_time=07:00`、`collection_window_hours=24`、`report_time=08:00`。
- 内网数据 API：`/api/dashboard?scope=latest` 返回最近批次 1 篇帖子、2 条评论、中文标题 `Momcozy M5 在工作时漏奶`。
- 内网洞察 API：`/api/insights?scope=latest` 返回中文故事线。
- 部署版浏览器 smoke：通过 SSH tunnel 到 `127.0.0.1:18337`，三模块导航存在，数据看板 1 行，洞察故事线为中文；截图保存到 `tmp/webapp-smoke/deployed-tunnel-collection.png`、`deployed-tunnel-dashboard.png`、`deployed-tunnel-insights.png`。
- 部署版表单值：`collectionTime=07:00`、`windowHours=24`、`reportTime=08:00`、artifact placeholder `https://reddit.brand.lute-tlz-dddd.top/artifacts/`。
- Cron：`/etc/cron.d/reddit-voc-site` 包含 `0 7 * * *` 采集和 `0 8 * * *` 报告。
- Blocked-safe 验证：
  - `/opt/reddit-voc-site/scripts/server_daily_collect.sh` 写入 `reason=missing_runtime_env_file`，`provider_call=false`，`live_send=false`。
  - `/opt/reddit-voc-site/scripts/server_daily_report.sh` 写入 `reason=missing_daily_database`，`provider_call=false`，`live_send=false`。
- Artifact 访问：`http://127.0.0.1:18337/artifacts/daily_collect_20260707_0700-server-collect-blocked.json` 返回 blocked JSON。
- Secret 边界：`ai_video.pem` 未进入远端部署目录和 Docker 镜像；`.dockerignore` 与部署 tar 均排除 `*.pem` 和真实 `.env`。

## 2026-07-08 Live Activation Evidence

- Runtime env：`/home/ubuntu/.reddit-voc/secrets/reddit-voc-live.env` 已存在，权限 `600`；脱敏校验显示 TikHub 与 DingTalk 必要变量齐全。
- TikHub API 修复：
  - `fetch_dynamic_search` 使用官方参数 `query`，并补 `User-Agent` 避免 Python urllib 被 Cloudflare 1010 拦截。
  - `fetch_post_details_batch_large` 按官方文档改为 `GET`，`post_ids` 使用逗号分隔的 `t3_...` fullname。
  - `fetch_post_comments` 按官方文档改为 `GET`，逐帖拉取评论树。
  - 新增 TikHub App `SearchPost`、`postsInfoByIds`、`commentForest.trees` 解析分支。
- 手动 07:00-style 采集：
  - 命令窗口：`REDDIT_VOC_ANCHOR_UTC=2026-07-07T23:00:00+00:00 /opt/reddit-voc-site/scripts/server_daily_collect.sh`。
  - run：`daily_collect_20260708_0700`。
  - 采集窗口：UTC `2026-07-06T23:00:00+00:00` 到 `2026-07-07T23:00:00+00:00`，即北京时间 2026-07-07 07:00 到 2026-07-08 07:00。
  - 返回：`return_code=0`、`provider_call=true`、`live_send=false`。
  - summary：`status=partial`、`discovered_posts=77`、`window_posts=25`、`relevant_posts=7`、`ingested_threads=7`、`ingested_comments=20`、`analysis_items=27`、coverage `full=6`、`partial=1`。
- 手动 08:00-style 报告：
  - `/opt/reddit-voc-site/scripts/server_daily_report.sh` 返回 `return_code=0`。
  - live-send 结果：`status=sent`、`http_status=200`、`required_keyword_present=true`、`provider_call=true`、`live_send=true`。
  - 产物：HTML `41K`、XLSX `13K`、CSV `31K`、PNG `42K`。
- DingTalk 链接验收：
  - `https://reddit.brand.lute-tlz-dddd.top/artifacts/daily_collect_20260708_0700-insight-report.html` -> HTTP 200 `text/html`。
  - `https://reddit.brand.lute-tlz-dddd.top/artifacts/daily_collect_20260708_0700-daily-detail.xlsx` -> HTTP 200。
  - `https://reddit.brand.lute-tlz-dddd.top/artifacts/daily_collect_20260708_0700-daily-detail.csv` -> HTTP 200 `text/csv`。
  - `https://reddit.brand.lute-tlz-dddd.top/artifacts/daily_collect_20260708_0700-insights.png` -> HTTP 200 `image/png`，尺寸 `1400 x 900`。
- 鉴权边界：公网根路径仍返回 302 到统一登录页；仅 `/artifacts/` 为 DingTalk 交付开放只读访问。
- 网站 API：`/api/dashboard` latest totals 为 `posts=7`、`comments=20`；`/api/settings` 显示采集 `07:00`、推送 `08:00`。

## 风险与边界

- 网站页面本身不触发 Reddit/TikHub provider call，不发送钉钉 live message；服务器 cron 脚本只有在 repo 外部 runtime env 明确开启 gate 且提供密钥时才会执行 provider/live 分支。
- `ai_video.pem` 只用于 SSH，不进入 Docker 镜像和远端部署包。
- 现有 Nginx 是多应用共享入口，修改前必须备份，reload 前必须 `nginx -t`。
- 当前已执行一次授权 TikHub Reddit 采集和一次授权 DingTalk live send；不要把这等同于未来每天 cron 已经长期稳定运行，仍需观察下一次自然 07:00/08:00 定时执行。
- 当前 `partial` 的主要原因是 TikHub subreddit feed endpoint 返回 HTTP 400；动态搜索、详情和评论接口已经跑通。
- 当前已接入 LibreTranslate-compatible 翻译 provider；生产可以通过 `webapp/docker-compose.translation.yml` 启动私网 `reddit_voc_libretranslate` sidecar，并在仓库外 runtime env 配置 `REDDIT_VOC_TRANSLATION_MODE=libretranslate` 与 `LIBRETRANSLATE_BASE_URL=http://reddit_voc_libretranslate:5000`。
- 2026-07-09 已部署私网 `reddit_voc_libretranslate` sidecar；`daily_collect_20260708_0700` 的生产 DB 副本 dry-run 验证为 `translation_status=translated`、`provider_call=true`、`live_send=false`，未触发真实钉钉推送。
- 公网入口受现有 `auth_gate.conf` 保护；`/artifacts/` 为 DingTalk 链接公开只读访问，因此报告产物 URL 具备外部可见性。
