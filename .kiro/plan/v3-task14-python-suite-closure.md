# V3 Task 14 Python 全量回归收口 TODO

## 目标

关闭 `docs/superpowers/plans/2026-07-16-reddit-voc-v3-complete-system.md`
Task 14 Step 2，取得当前代码与受治理历史 backfill 合同一致的完整 Python
回归证据。

## 边界

- 本地只读盘点、哈希复算、测试和不可变审阅制品。
- 不机械替换历史 review SHA。
- 不调用 Provider，不续采，不写数据库。
- 不创建生产 packet，不 SSH，不上传，不部署，不切换生产。

## TODO

| ID | 工作项 | 验收条件 | 状态 |
|---|---|---|---|
| T14PY-01 | 复跑当前完整 Python suite | 得到当前精确失败集合 | complete：`1 failed, 1857 passed, 881 subtests passed` |
| T14PY-02 | 定位历史 backfill release 合同 | 明确 manifest、reviewed files、validator 与测试入口 | complete：预期 SHA 失败未复现；实际失败定位为 public projection archive 缺失 |
| T14PY-03 | 复算 5 个 SHA 差异 | 区分文件演进、损坏、缺失归档和测试陈旧 | complete：无需改历史 SHA；3 个缺失归档的候选 bytes 与 active manifest 完全匹配 |
| T14PY-04 | 盘点可恢复归档 | 若存在原审阅 bytes，验证后恢复到隔离路径，不覆盖当前源文件 | complete：3 个独立候选投影内容一致，目标 archive 目录为空 |
| T14PY-05 | 决策历史合同处理 | 仅在新审阅证据完整时创建新本地 manifest；否则保留 blocker | complete：保留 active manifest/index，恢复其已绑定的精确生成产物 |
| T14PY-06 | 运行 backfill focused regression | 历史合同测试零失败、冻结边界可复算 | complete：public projection focused regression `1 passed in 0.10s` |
| T14PY-07 | 重跑完整 Python suite | 零失败，Task 14 Step 2 可关闭 | complete：`1858 passed, 881 subtests passed in 1434.10s` |
| T14PY-08 | 记录证据与剩余边界 | 命令、测试数、SHA、未授权动作完整 | complete：本地证据已写回；无 provider、数据库、远程或生产动作 |

## 决策原则

1. 历史 release manifest 是审阅证据，不是自动同步当前文件的缓存。
2. 当前文件改变不自动意味着历史 manifest 应重签。
3. 优先寻找原始归档并在隔离目录复验，禁止覆盖当前工作树。
4. 新 manifest 必须绑定明确的新审阅范围、输入 SHA、validator 和时间边界。
5. 无真实输入或审阅证据时保持 fail-closed。

## 收口证据

- 唯一初始失败：
  `tests/test_public_site_projection.py::test_public_insights_and_reports_manifests_bind_exact_projected_files`
- 恢复来源：
  `tmp/reddit-voc-v3/candidate-orchestration/v3-governed-retry-002/frontend-dist-a2/data/reddit-voc/reddit_voc_reports_20260714_v1/public/archive/`
- 恢复目标：
  `ref/UI/momcozy-reddit-workbench/public/data/reddit-voc/reddit_voc_reports_20260714_v1/public/archive/`
- `daily-2026-07-13.json`：28,205 bytes，
  `b3b1fc9d381af7453346c99aaf297c6068857007508ff30081332a6a9bf5dabc`
- `monthly-2026-06.json`：11,225 bytes，
  `f5e90cd009a9e9fc9447102373d35deebd2dd553dfb12aa33c3f33207d33482a`
- `weekly-2026-07-06_2026-07-12.json`：32,806 bytes，
  `8b090b4ffa5a5b9177f75b91c91cd40f534da984d469df98e6cdd6fa0273f807`
- 聚焦回归：`1 passed in 0.10s`
- 完整回归：`1858 passed, 881 subtests passed in 1434.10s (0:23:54)`
