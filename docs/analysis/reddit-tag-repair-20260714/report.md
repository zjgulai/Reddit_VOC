# Reddit VOC 四标签关系修复与新样本门禁报告

日期：2026-07-14  
基础数据版本：`reddit_voc_site_snapshot_20260714_v1`  
修复数据版本：`reddit_voc_tag_repair_20260714_v1`  
结论状态：`completed_no_new_promotions`

## 1. 结论

本批已对四个高价值 held 标签完成专属关系 predicate、旧样本回归、零重叠新样本复核和 challenge cases 门禁。243 条 lexical candidates 均被重新判定为 `confirmed`、`rejected` 或 `needs_review`，但四个标签均未达到晋级所需的 Wilson 95% 下界，因此保持 `held_after_repair`，不会进入 Insights、日报/周报/月报或画像信号。

这不是语义精度失败：本批 12 条零重叠 fresh confirmed 样本逐条复核均为正确，taxonomy fit 均为 `fit`。未晋级的原因是收紧关系后各标签可验证的新鲜 confirmed 数量过少，统计证据不足，不能用 100% 的小样本表面精度替代置信下界。

## 2. 数据绑定与处理边界

修复层严格绑定以下不可变输入：

- 基础 manifest SHA-256：`f04edef8dc73c8975e4bba56cbeefd8b734fd86f2c5a95aa2a041325503720ef`
- 标签字典：`dim_tag_v6.3_final`
- 标签字典 SHA-256：`22664c9c446ddfa17446852079f507ab75b5af3d4dde6e4e3f3e44c195582e14`
- predicate policy SHA-256：`5a3d7b5e4ebcbb28ff8c5ba8148dda327e8c75910870dd73eb05869c229d69da`
- 旧审计样本 SHA-256：`59190bf019a69f4f89ba9c5d6af67b34f003e9e6b47f679185ba9feb4b972117`
- 新复核样本 SHA-256：`99be90bf85932359feedd00cd791d51329f3b43aab99901ec303007602ade5b8`

本批只新增覆盖层，不修改 `TagDictionary.extract()`、基础快照、既有 Insights、报告或 UI。

## 3. Predicate 收紧结果

| 标签 | lexical candidates | confirmed | needs_review | rejected |
|---|---:|---:|---:|---:|
| `L2-PUMP-016` 法兰尺码不合适 | 36 | 7 | 9 | 20 |
| `L0-CHL-003` 物超所值 | 96 | 10 | 56 | 30 |
| `L2-PUMP-030` 出奶量不输主泵/竞品 | 56 | 3 | 24 | 29 |
| `L2-PUMP-007` 考虑购买配件 | 55 | 0 | 3 | 52 |
| 合计 | 243 | 20 | 92 | 131 |

关键修复包括：

- 法兰标签要求明确尺码/贴合失败，或 elastic anatomy 与负面结果同句或相邻句；问他人、已消退、正确尺码、正负结果混合和材料偏好均 fail closed。
- 价值标签拒绝问句、`if/whether` 条件句、`may/might` 模态表达、单纯折扣、否定以及仅时间/移动性等非价格效用；同句对比转折后独立的无条件价值断言仍可确认。
- 出奶量标签要求 Momcozy、竞品或主泵、output/emptying 指标和相同或更优方向全部在同句完成绑定。
- 配件购买标签要求同句第一人称购买主体、主动购买意图和配件名；既往购买、免费/保险供应、建议他人及可得性担忧不确认。

## 4. 回归与 challenge 证据

- 旧 held 审计样本：80 条，仅作为回归；其中本批四标签 40 条。
- 旧样本回归失败：0。
- 已知错误再次 confirmed：0。
- 已知歧义未保留为 `needs_review`：0。
- 新复核样本与旧 80 条样本重叠：0。
- 每标签 challenge cases：20 条；四标签均达到门槛，且未添加 synthetic cases。

复核由 Codex 基于完整实体文本及可用 parent context 逐条完成，每个 sampled audit ID 均有显式 review decision；`independent_human_review=false`。

## 5. 最终门禁结果

| 标签 | fresh reviewed | correct | precision | taxonomy fit | ambiguous | Wilson 95% 下界 | 结果 |
|---|---:|---:|---:|---:|---:|---:|---|
| `L2-PUMP-016` | 2 | 2 | 100% | 100% | 0% | 34.2380% | held |
| `L0-CHL-003` | 9 | 9 | 100% | 100% | 0% | 70.0855% | held |
| `L2-PUMP-030` | 1 | 1 | 100% | 100% | 0% | 20.6549% | held |
| `L2-PUMP-007` | 0 | 0 | 0% | 0% | 0% | 0% | held |

晋级要求 Wilson 95% 下界 `>= 75%`。前三个标签仅该项失败；`L2-PUMP-007` 在收紧后没有 fresh confirmed population，同时失败于 sample plan、precision、taxonomy fit 和 Wilson 门禁。

## 6. 下游使用决策

最终结果为 `0 promoted / 4 held`。因此本快照可作为审计证据和后续迭代基线，但当前不应被 persona、Insights 或日报/周报/月报当作新增可信标签信号。下一轮若要晋级，应优先扩充独立 fresh confirmed 证据，而不是放宽 predicate 或降低 Wilson 门槛。

## 7. 验证与副作用边界

独立 validator 已完成文件哈希、全量重算、三态汇总、旧样本回归、零重叠、新挑战样本、门禁计算及副作用边界验证，结果为 `passed`。

- `production unchanged`
- `provider_call=false`
- `database_write=false`
- `live_send=false`
- `independent_human_review=false`

