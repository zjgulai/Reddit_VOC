# Echo-Agent systemd 单元入库与部署 runbook

> 入库日：2026-11-05（Wave 1 D0 · T17）。来源：生产 `/etc/systemd/system/` 实拉取，secret 已替换为占位符。

## 1. 为什么入库

生产 `/opt/echo-agent-bot` 不是 git checkout（无 `.git`），单元文件此前只存在于服务器上：
任何 `ExecStart`/环境变量/重启策略的变更都无法审计、无法回滚、无法 code review。
入库后：模板在本仓库 review，经 `scripts/deploy_systemd_units.sh` 原子部署。

## 2. 单元清单

| 文件 | 生产路径 | 角色 |
|---|---|---|
| `echo-agent-ws.service` | `/etc/systemd/system/echo-agent-ws.service` | 飞书 WS 长连接 Bot（Stage 2 双通道之一） |
| `echo-agent-bot.service` | `/etc/systemd/system/echo-agent-bot.service` | 飞书 Webhook Bot :18342（双通道之二） |
| `echo-agent-daily.service` + `.timer` | 同名 | 每日 07:05 Asia/Shanghai T-1 流水线（oneshot + Persistent） |
| `echo-agent-freshness.*`（已有） | 同名 | 新鲜度监控 |
| `reddit-voc-data-shadow.*`（已有） | 同名 | 数据影子校验 |

## 3. Secret 占位符

模板中 `{{FEISHU_APP_SECRET}}`、`{{APIFY_API_KEY}}` 是占位符；部署脚本从本地
`DDDD.pem` / `zhoujian_pachong.pem` 侧环境或 `~/.reddit-voc/secrets/` 注入真实值。
**占位符值本身不进 git**（部署时替换），生产文件权限保持 root-only。

## 4. 部署流程（deploy_systemd_units.sh）

```bash
# 1) 本地渲染（占位符 → 真实值），输出到临时目录
# 2) sha256 先传后比：远端写入前先记录期望哈希
# 3) scp → /tmp，远端 sudo install -m 644 到 /etc/systemd/system/
# 4) sudo systemctl daemon-reload
# 5) 仅对变更单元执行 systemctl restart（daily.timer 用 restart，oneshot 不手动 start）
# 6) 部署后 cat 远端文件回读，sha256 与期望值比对，不一致即 fail-closed
# 7) 回执写 outputs/systemd-deploy-<ts>.json（含逐文件 sha256）
```

**冻结窗口**：禁止在 06:35-07:35 Asia/Shanghai 部署（K1 streak 保护）；ws/bot 重启
会使飞书连接短暂中断，选择业务低峰（当前 17:03 热修先例为 09:03 UTC）。

## 5. 漂移检测（后续任务，T14' 同族）

```bash
# 本地：入库模板（占位符替换后） vs 生产实文件逐行 diff
scripts/verify_systemd_units.sh   # 拉取生产单元 → 渲染模板 → diff → 不一致 exit 1
```

任何生产侧手工改动（`sudo systemctl edit`、直接 vim）都会被下一次漂移检测抓出。

## 6. 回滚

单元文件不可变部署：回滚 = 重新部署上一版模板。`git log config/systemd/` 即回滚目标清单。
