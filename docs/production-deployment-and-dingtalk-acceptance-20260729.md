# Reddit VOC 生产部署与钉钉三周期验收方案

日期：2026-07-29

## 1. 决策边界

本文件是部署与验收方案，不是生产变更授权。

| 动作 | 当前状态 | 证据等级 | 本轮是否执行 |
| --- | --- | --- | --- |
| Task31W namespace 阻断修复 | 修正版只读门禁通过 | L3 远端只读 | 已完成 |
| Task31W recovery | 未执行，CLI 调用 0 次 | L3 远端只读 | 否 |
| 生产 release 切换 | 未授权 | L2 本地/受控 | 否 |
| 日报 prepare | 代码与受控测试链路存在 | L2 本地/受控 | 否 |
| 日报钉钉 live send | server launcher 明确禁用 | L2 本地/受控 | 否 |
| 周报后端生成与发送 | 未发现生产后端链路，现有实现集中在 UI mock | L1/L2 | 否 |
| 月报后端生成与发送 | 未发现生产后端链路，现有实现集中在 UI mock | L1/L2 | 否 |
| 钉钉日报/周报/月报历史实发 | 用户确认均未发生 | L0 用户声明 | 否 |

禁止将 dry-run、prepared outbox、UI mock、HTTP 可达性或 webhook 配置存在表述为“已推送”或“生产验收通过”。

## 2. 已关闭的部署前阻断

Task31W 原 wrapper 使用 `/sys/class/net` 判断 `unshare --net` 是否隔离。新 network namespace 已生效，但继承的 sysfs mount 仍绑定宿主 network namespace，因此显示 Docker bridge、veth 和 `eth0`，造成假阴性。

修复后的 network-none 门禁必须同时满足：

1. 进入 `unshare --mount --net` 前记录 `/proc/self/ns/net` inode。
2. namespace 内再次读取 inode，必须与宿主不同。
3. 从 `/proc/net/dev` 读取接口，只允许 `lo`。
4. `/proc/net/route` 必须没有路由记录。
5. source database、raw、Task31T、Task31U 与全部旧 root 必须为只读 mount。
6. 仅新 recovery root 可写。
7. Provider cap 为 0。

2026-07-29 只读复验结果：

| 门禁 | 结果 |
| --- | --- |
| host net namespace | `net:[4026531840]` |
| isolated net namespace | `net:[4026534064]` |
| `/proc/net/dev` | `lo` |
| `/proc/net/route` | 0 行 |
| source/raw/Task31T/Task31U | `ro,relatime` |
| Task31W root | `rw,relatime`，仅临时 namespace |
| source SHA | `8baa66135aa58e34c83c7b1d7fd3170adf05f7fdeb342363f3cac13459c29f2f` |
| remote writes | 0 |
| recovery CLI calls | 0 |

Task31W root 继续作为证据保留，不得用于 recovery 重试。实际 recovery 必须使用新的 fresh root 和新的精确授权。

## 3. 当前报表与钉钉能力差距

### 3.1 日报

现有生产候选链路支持：

1. `scheduled-prepare` 默认调度。
2. 只读源快照校验。
3. 翻译与渲染前门禁。
4. immutable prepared artifacts。
5. 钉钉 outbox 冻结、字节上限和 required keyword 校验。
6. `live_send=false` 的 smoke/dry-run。

现有 server launcher 的 `send` 操作会以 `dingtalk_disabled_by_owner` fail closed；日报尚不能按治理链路实发。

仓库存在旧的手工 live-send 命令，但它不是 prepared outbox 的生产发送闭环，不能绕过 owner gate 用作首次上线。

### 3.2 周报

当前可见周报结构主要来自前端 mock 数据。生产后端尚缺：

1. Asia/Shanghai 自然周窗口契约。
2. 跨日报去重与可追溯聚合。
3. 周同比/环比计算与最小样本标记。
4. immutable weekly artifact/outbox。
5. 周报调度、发送授权、delivery receipt 和重放防护。

### 3.3 月报

当前可见月报结构主要来自前端 mock 数据。生产后端尚缺：

1. Asia/Shanghai 自然月窗口契约。
2. 月边界、2 月和闰年测试。
3. 日报/周报到月报的 lineage。
4. immutable monthly artifact/outbox。
5. 月报调度、发送授权、delivery receipt 和重放防护。

## 4. 完整执行 TODO

### P0：关闭数据恢复门禁

- [x] 定位 Task31W namespace 假阴性。
- [x] 使用 namespace-aware `/proc/net/*` 修复门禁并完成只读复验。
- [ ] 生成新的 recovery task/bundle/receipt，Task31W 只保留证据。
- [ ] 获得 fresh root、bundle SHA、source SHA、network-none、Provider cap 0 的精确授权。
- [ ] 执行一次 recovery，并验证 12 个候选、6 个 owner batches、166 个额外成员、Provider/raw/旧 roots。

### P1：日报生产候选

- [ ] 固化 content-addressed report release。
- [ ] 运行日报单元测试、launcher 测试、release manifest 测试和 container smoke。
- [ ] 生成一份真实 production-readonly 数据的日报 prepared artifact。
- [ ] 验证 outbox SHA、每段字节数、required keyword、artifact HTTPS URL 和敏感字段脱敏。
- [ ] 验证重复 prepare 不能覆盖已有 immutable artifact。

### P2：治理化钉钉发送器

- [ ] 新增 prepared-outbox send 命令，不复用旧的动态重渲染 live-send。
- [ ] 要求双门禁：CLI 明确参数和环境开关同时成立。
- [ ] 要求独立 `send_authorization_id`，不得复用 prepare/provider authorization。
- [ ] 使用 idempotency key：`cadence + period_start + period_end + outbox_sha256`。
- [ ] 发送前复验 outbox SHA、part 顺序、字节上限、required keyword 和 webhook host allowlist。
- [ ] 每个 part 记录 HTTP 状态、钉钉 `errcode`、响应 SHA、外部尝试标记和时间戳。
- [ ] 多 part 任一失败时禁止自动重发已成功 part，进入人工恢复队列。
- [ ] webhook、secret 和响应正文不得进入公共 artifact 或普通日志。

### P3：周报生产链路

- [ ] 定义 `weekly-report-v1` schema 与自然周窗口。
- [ ] 从已验收日报/源数据库聚合，保留 source run IDs 和 artifact SHAs。
- [ ] 实现真实数据 renderer、prepared artifact、outbox 和 validation receipt。
- [ ] 增加跨周边界、重复数据、空周、低样本和时区测试。
- [ ] 在 live send 之前完成一轮 shadow prepare。

### P4：月报生产链路

- [ ] 定义 `monthly-report-v1` schema 与自然月窗口。
- [ ] 保留日报/周报/source lineage，禁止使用 UI mock 作为生产输入。
- [ ] 实现真实数据 renderer、prepared artifact、outbox 和 validation receipt。
- [ ] 增加 28/29/30/31 天、跨年、空月、低样本和时区测试。
- [ ] 在 live send 之前完成一轮 shadow prepare。

### P5：生产部署

- [ ] 只读 preflight：当前 release pointer、镜像 ID、cron SHA、数据库 SHA、容器与网络、磁盘、secret 文件元数据。
- [ ] 构建候选 release，验证 allowlist、manifest SHA 和无未跟踪文件。
- [ ] 以 shadow 模式启动，Provider 0、live send 0、生产数据只读。
- [ ] 运行日报/周报/月报 prepare 与 artifact 验收。
- [ ] 获得独立 production switch 授权后原子切换 release pointer。
- [ ] 切换后先保持 send disabled，观察一个完整日报周期。
- [ ] 获得独立 DingTalk canary 授权后再执行首次真实发送。

## 5. 测试验收矩阵

| 层级 | 验收项目 | 通过标准 |
| --- | --- | --- |
| Unit | 窗口、时区、去重、聚合、schema、idempotency | 全部聚焦测试通过 |
| Contract | artifact/outbox/receipt schema | schema 校验通过，SHA 可复算 |
| Security | secret、日志、URL、脱敏 | webhook/secret 不出现在 artifact/log |
| Runtime | read-only mounts、resource limits、network | inspect 与 runtime receipt 一致 |
| Data | source SHA、run IDs、行数、时间范围 | 与 production-readonly preflight 一致 |
| Report | HTML/CSV/XLSX/Markdown 一致性 | 指标和 source lineage 可回溯 |
| DingTalk dry-run | message parts、大小、keyword | external attempt 0，live send 0 |
| Failure | 缺 secret、超长、错误 keyword、重复发送 | fail closed，无外部尝试或无重复发送 |
| Rollback | release pointer 与 send gate | 可恢复旧 release，send 默认关闭 |

## 6. 首次钉钉推送验收顺序

三种周期不得在同一批次首次实发。

1. 日报 canary：发送到指定测试群，只发送一个已冻结 outbox。
2. 日报观察：确认 HTTP 200、钉钉 `errcode=0`、消息可见、链接可访问、无重复、receipt 完整。
3. 周报 canary：仅在周报真实数据链路和 shadow prepare 通过后单独授权。
4. 月报 canary：仅在月报真实数据链路和 shadow prepare 通过后单独授权。
5. 正式调度：每种 cadence 分别启用，不共享授权 ID。

建议调度时区为 Asia/Shanghai：

| 周期 | 数据窗口 | 建议 prepare | 建议 send |
| --- | --- | --- | --- |
| 日报 | 前一自然日 | 每日 07:00 | 人工验收后 08:00 |
| 周报 | 周一至周日 | 每周一 08:00 | 人工验收后 10:00 |
| 月报 | 前一自然月 | 每月 1 日 09:00 | 人工验收后 14:00 |

首次实发必须由用户提供精确授权，至少包含 cadence、period、run/artifact ID、outbox SHA、目标群标识、最大 part 数和“一次发送、失败不自动重试”。

## 7. 回滚方案

1. 第一动作是关闭 live-send gate，不删除历史 receipt。
2. 停止对应 cadence 的 send 调度，保留 prepare-only。
3. 将 release pointer 原子恢复到部署前 release。
4. 验证 cron SHA、容器 ID、数据库 SHA 和旧 release manifest。
5. 对失败的多 part 消息只做人工补偿，不盲目整批重发。
6. 钉钉消息若已成功送达，回滚应用不会撤回消息，需在验收记录中明确。

## 8. Go/No-Go 标准

Go 必须同时满足：

1. Task31 后续 fresh-root recovery 完成并通过数据门禁。
2. 候选 release 与 production-readonly preflight 均有 SHA receipt。
3. 日报真实 prepared artifact 通过。
4. 周报/月报若要上线，必须已有真实后端链路，不能使用 mock。
5. DingTalk dry-run 通过且 external attempt 为 0。
6. production switch 与每次 live send 分别获得精确授权。
7. rollback 演练通过。

任何一项缺失均为 No-Go。
