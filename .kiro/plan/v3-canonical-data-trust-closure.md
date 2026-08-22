# V3 Canonical 数据可信闭环执行 TODO

## 目标

使 Base `unresolved-parent-ledger.jsonl` 中的评论身份可以在后续 workbook
证据补齐父帖时，经过 importer、独立 validator 和 canonical fusion 确定性
转为 `linked`，并从 unresolved ledger 清退。

## 执行边界

- 仅修改本地代码、测试和计划证据。
- 不调用 Provider，不续采，不写数据库。
- 不构建生产包，不上传，不切换生产，不发送外部消息。
- Base 历史 `canonical_counts` 保持原合同；optional unresolved ledger 作为
  独立受治理身份锚点记录在 import manifest reconciliation 中。

## TODO

| ID | 工作项 | 验收条件 | 状态 |
|---|---|---|---|
| V3CT-01 | JSONL 夹具修复 | focused canonical regression 进入业务断言 | implemented_pending_validation |
| V3CT-02 | importer unresolved binding | bytes/SHA/schema/state/identity/duplicate 校验完整 | implemented_pending_validation |
| V3CT-03 | importer relink 分类 | unresolved overlap 为 `exact_base_overlap`，新父帖可成为 `linked_base_post` | implemented_pending_validation |
| V3CT-04 | validator 对称重算 | Base binding、classification、manifest reconciliation 与 builder 一致 | implemented_pending_validation |
| V3CT-05 | canonical ledger 生命周期 | relink 身份只进入 linked comments，并从 unresolved ledger 删除 | implemented_pending_validation |
| V3CT-06 | focused tests | importer 与 canonical 两条新增回归均通过 | in_progress |
| V3CT-07 | 模块回归 | workbook importer、validator、canonical snapshot 模块通过 | pending |
| V3CT-08 | 本地 validator | 当前 V3 import/canonical 制品独立校验通过；若无适用候选则记录阻断 | pending |
| V3CT-09 | 证据收口 | 记录命令、通过数、失败原因和生产边界 | pending |

## 状态不变量

1. 同一 canonical comment identity 在最终快照中只能处于一个终态。
2. linked overlap 必须从 unresolved ledger 清退。
3. unresolved overlap 不得被误计为 net-new comment。
4. builder 与 validator 必须独立得出相同 parent link、terminal outcome 和 counts。
5. manifest 文件绑定、receipt SHA 和统计计数必须可复算。

## 验收顺序

1. 新增 canonical focused regression。
2. 新增 importer focused regression。
3. `test_reddit_v3_canonical_snapshot` 模块。
4. `test_reddit_add_data_workbooks` 与 `test_validate_reddit_add_data_import` 模块。
5. 当前本地 import/canonical validator。

任何一步失败即停止后续候选声明，记录真实错误，不将实现状态写成通过。
