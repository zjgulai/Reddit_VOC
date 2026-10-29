# 验证记录与证据索引

审查日期：2026-10-14；代码基线 `15b286a2a4f807023b999eec8b96333ddfce7eb7` + 审查开始时已有 dirty 修改。所有结果都属于本机当前工作区，不能代表 GitHub 最新状态或生产当前状态。

## 检查矩阵

| 检查 | 本次结果 | 证据与限制 |
|---|---|---|
| 目录/Git/AGENTS | 通过 | 项目可读；适用 `/Users/pray/AGENTS.md`；初始 17 modified + 3 untracked，完整状态见 summary |
| 原文件保护 | 通过 | 审查前后比对 4,280 个原 tracked 文件 SHA，变化为 0；只新增本目录材料 |
| Python 静态语法 | 通过 | src/scripts/webapp/tests 下 427 个 Python 文件 AST 解析，0 错误；不等于导入或运行检查 |
| 选定核心 unittest | 首轮 359 通过 / 1 环境失败 | 24 个候选模块中 22 个成功载入，执行 360 tests，0 errors；2 模块缺依赖未载入 |
| 核心失败单项复验 | 通过，1/1 | 原失败为审查 harness 仅改 sys.path、未把 PYTHONPATH 传给子进程；补充启动环境后 import-isolation 测试通过。未改业务代码，也没有重跑整个 suite |
| ops/launcher unittest | 57 通过 / 4 失败 / 2 错误 | 63 tests；5 项在过期 fixture permit 上阻断，1 项缺 Pillow；不是全绿 |
| authority reader 时钟诊断 | 单项 1/1 通过 | 仅在独立测试进程为 report_control 注入 2026-08-12 时钟，定位 fixture/真实时钟耦合；不改变正式失败记录或生产许可 |
| 前端 Vitest | 229 passed / 46 skipped / 0 failed | 共 275 tests；现有契约/fixture 条件决定的 skip，不能当作覆盖全部旧/新分支 |
| 前端 lint | 退出 0，15 warnings | 包含 hooks dependency / ref cleanup / Fast Refresh；详见 log |
| TypeScript + Vite build | 通过 | 使用现有 node_modules，输出到 `/tmp/reddit-voc-audit-20261014/frontend-dist`；不是用 fresh npm ci 重新安装，不证明所有环境复现 |
| version consistency | **失败** | `daily_source_release_mismatch`，未改 production lock |
| 本地新增复现 | 已确认 | 临时 DB、仓库 synthetic fixture、fake Provider/transport；Python socket.connect 被审查脚本拒绝 |
| 完整 repository/local-artifact pytest | 未运行 | 本机选定解释器缺 pytest/Pillow，没有下载依赖；144/38 模块分类只读取清单 |
| nginx -t / 容器拓扑启动 | 未运行 | 未连接 Docker daemon、构建镜像或启动容器。F12 为静态合同证据；F13 另有官方语义支撑 |
| 生产/真实服务验收 | 未运行 | 没有读取生产 DB、SSH、真实 TikHub/DeepSeek/DingTalk、线上 E2E 或现网压力测试 |
| CVE/依赖漏洞扫描 | 未运行 | 没有 npm audit/pip-audit 或远程漏洞库查询，不声称特定版本有已知漏洞 |

Python 核心 suite 的已选模块覆盖 daily/browser/TikHub、raw、Web payload、规则、时间窗口、DingTalk transport、DeepSeek client、Provider ledger、回填存储/验证、source batch、实体和内容完整性等。prepared、translation、dual-delivery 的完整导入/执行仍受 Pillow 影响，不能以这些已选检查替代。

## 复现映射

完整数值在 [reproductions.json](reproductions.json)；脚本在 [reproduce.py](reproduce.py)。脚本只使用临时目录，不读取项目 data/outputs 中的真实帖子。

| 字段 | 对应发现 | 结果 |
|---|---|---|
| `F01_api_fields` | F01 | author_hash/selftext/raw_capture_id/comments/db_name 均存在 |
| `F01_artifact_unlisted_file_readable` | F01 | true；临时 root 内 private/audit-marker.txt 未登记也被解析为可读文件 |
| `F02_history_after_reobserve` | F02 | A 的 threads/comments/analysis 为 0，raw 为 2 |
| `F03_browser_raw_collision` | F03 | 同 payload 跨 run 抛 raw capture identity collision |
| `F04_failed_recollect` | F04 | 有数据 run 经全失败 fake Provider 重采后，failed 且 post_count=0 |
| `F05_empty_despite_failure` | F05 | 两种 collector 都 empty；下游 empty_success，业务报告允许、失败告警不允许 |
| `F06_xlsx_formula` | F06 | 实际 XLSX cell 类型 f，内容 =1+1；未用表格软件执行 |
| `F07_media_request` | F07 | fake transport 接到 loopback URL，response.read 未带 size；无实际请求 |
| `F08_analysis_provenance` | F08 | fake DeepSeek 分析落为 local_rules_v1 / provider_call=0 |
| `F09_missed_run` | F09 | 只有 failed run，仍返回 covered |
| `F10_query_plan` | F10 | SCAN reddit_comments；不代表已做性能压测 |
| `F16_truncated_status` | F16 | candidate=2 / ingested=1 / full=1 仍 success |

为分别复现 F02 和 F03，F02 的第二次 JSON 仅增加无语义换行以改变 raw hash；F03 则保持 payload 完全相同。`F03_browser_raw_second_run=2` 表示换行后 B 的有效 raw 计数，不表示原始碰撞已经修复。

XLSX/媒体复现从原 `daily_report.py` 提取指定函数 AST 后执行，绕开无关的 PIL 顶层导入。函数体未改写；依赖和 transport 由诊断脚本明确注入。因此这两项是函数级复现，不是 renderer 的全路径集成验收。

## 可重放命令与日志

从仓库根目录运行，使用本机已安装的 Python3.12/openpyxl：

```bash
PYTHONDONTWRITEBYTECODE=1 /opt/homebrew/bin/python3.12 docs/analysis/reddit-voc-deep-audit-20261014/reproduce.py
PYTHONDONTWRITEBYTECODE=1 /opt/homebrew/bin/python3.12 docs/analysis/reddit-voc-deep-audit-20261014/run_safe_tests.py
PYTHONDONTWRITEBYTECODE=1 /opt/homebrew/bin/python3.12 docs/analysis/reddit-voc-deep-audit-20261014/run_runtime_tests.py
```

前两个脚本保留本次启动行为以便解释首轮结果；`run_safe_tests.py` 的 sys.path 不传播到 child，重跑时可在命令前显式设置 `PYTHONPATH="$PWD/src:$PWD"` 消除已定位的单项环境失败。所有脚本的输出目标都在 `/tmp/reddit-voc-audit-20261014`，本目录的日志是审查结束时的冻结副本，重跑不会覆盖它们。脚本带 Python socket.connect 拒绝钩子，不能替代系统级网络 namespace；shell/子进程安全性来自已选用 fixture/fake 的测试范围。

前端命令在 `ref/UI/momcozy-reddit-workbench` 执行：

```bash
npm test -- --reporter=json --outputFile=/tmp/reddit-voc-audit-20261014/frontend-tests.json
npm run lint
REDDIT_VOC_BUILD_OUT_DIR=/tmp/reddit-voc-audit-20261014/frontend-dist npm run build
```

裸 Vite build 拷贝了本地 public 中历史制品，临时 dist 约 342 MiB。它仅证明代码可构建，不能替代 `audit_insights_dist.py --prepare-dist` 以及正式投影/隐私/发布门禁。没有把临时 build 移入当前 dist 或部署。

主要证据文件：

- [verification-summary.json](verification-summary.json)：机器可读结论、原工作区状态、保护检查、未运行项。
- [backend-tests.json](backend-tests.json)、[backend-tests.log](backend-tests.log)：360 项首轮详细结果。
- [backend-isolation-recheck.log](backend-isolation-recheck.log)：PYTHONPATH 修正后单项通过。
- [runtime-tests.json](runtime-tests.json)、[runtime-tests.log](runtime-tests.log)：63 项调度/launcher 结果和六项失败堆栈。
- [runtime-clock-recheck.log](runtime-clock-recheck.log)：单项测试时钟注入后的诊断结果。
- [frontend-test-summary.json](frontend-test-summary.json)、[frontend-lint.log](frontend-lint.log)、[frontend-build.log](frontend-build.log)：前端结果；完整 Vitest JSON 保留在临时目录，未复制大型逐项报告。
- [syntax-check.json](syntax-check.json)、[backend-lane-list.log](backend-lane-list.log)、[version-check.log](version-check.log)：语法、测试分类和失败的版本一致性检查。

Nginx 的 location 优先级参考了 [官方 ngx_http_core_module 文档](https://nginx.org/en/docs/http/ngx_http_core_module.html#location)。该文档读取是唯一为此问题进行的外部技术资料核验；它不是生产站点或业务 Provider 调用。

向源父线程 `01a1110c-7269-77ad-9170-2c0f0686d01c` 投递首批重要发现时，工具返回 **thread not found**；没有成功发送消息。完整交付仍通过本任务终态返回。未发生用量限制或代码访问阻塞；余下限制是缺 pytest/Pillow、未获新鲜生产事实及本次明确不执行的真实服务/部署范围。
