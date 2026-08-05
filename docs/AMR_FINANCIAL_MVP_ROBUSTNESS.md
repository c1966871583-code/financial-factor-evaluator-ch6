# FIN-MVP-ROBUST：M 轨道基础稳健性

状态：`ACCEPTED`

Schema：`FinancialMVPRobustness-v1.0`

审计 Schema：`FinancialMVPRobustnessAudit-v1.0`

哈希契约：`FIN-MVP-ROBUST-HASH-v1.0`

## 1. 任务定位

本任务是 Phase 1 MVP 的基础稳健性摘要，只覆盖：

```text
原始PIT值与获批MAD值的同口径对照
按配置月末顺序固定切分的前后半段方向对照
覆盖率、有效评价期、常数因子和常数收益退化
```

支持因子仍严格限定为 `ROE`、`BP`、`OCF_NP`。模块不改变
FIN-MVP-M-EVAL 主结果，不修改公共评价字段，也不会把任一稳健性格自动选为
主结论。

## 2. 冻结矩阵

数值口径：

```text
raw_pit_factor_value
evaluation_factor_value
```

时间区间：

```text
full
first_half
second_half
```

因此每个因子固定输出六个格子。配置日期按时间排序后：

```text
midpoint = len(evaluation_dates) // 2
first_half = dates[:midpoint]
second_half = dates[midpoint:]
```

MVP 最少 12 个评价日，前后子期各至少需要 6 个有效评价日。切分日期、数值
口径、格子顺序和最低期数全部进入配置指纹。

## 3. 同口径统计

每个可评价格子保存：

- 配置日期数、有效日期数和排除日期数；
- 因子样本数、标签可用数和配对覆盖率；
- 截面不足、常数因子和常数收益日期数；
- Rank IC、Pearson IC 的均值、标准差、ICIR、正比例和显式 HAC t 统计；
- 五组等权收益、高减低和单调性；
- 原始方向，不执行反向重测；
- 因子输入、标签和格子内容哈希。

全样本 MAD 格子的统计必须逐字段等于获批 FIN-MVP-M-EVAL 主结果，包括 IC、
HAC、分组收益、有效期和观察数。任何不一致均阻断完整三因子稳健性包。

## 4. 一致性语义

`preprocessing_consistency` 比较 raw 与 MAD 全样本 Rank IC 方向：

```text
consistent
mixed
insufficient
```

`raw_subperiod_direction_consistency` 和
`mad_subperiod_direction_consistency` 分别比较固定前后半段方向；
`subperiod_direction_consistency` 汇总两种预处理口径。

这些状态只表达稳健性证据，不是准入或生产状态。输出始终包含：

```text
best_cell_selected = false
```

不存在最佳格 ID、自动调参或主结果覆盖逻辑。

## 5. 覆盖与退化

收益标签仍按 `evaluation_date + code` 左连接到冻结因子样本。标签删除或扰动：

- 不改变 raw 或 MAD 因子样本指纹；
- 只改变标签指纹、配对覆盖率和下游统计；
- 不反向改变样本范围。

若某评价日有效配对少于 30、因子截面为常数或收益截面为常数，该日期不进入
统计，并分别累计结构化退化计数。有效期不足时格子状态为 `not_run`，统计字段
为 `null`、分组收益为空，不以零填充。

## 6. Fail-closed

以下情况阻断完整输出：

- 输入类型或合成授权不符合契约；
- FIN-MVP-M-EVAL 门禁未就绪；
- 提供的 M-EVAL 结果无法由同一输入和配置精确复算；
- MVP、预处理和评价键覆盖不一致；
- MAD 全样本统计与 M-EVAL 主结果不一致；
- 输入在评价期间发生变化。

所有输入对象只读；相同输入和配置必须得到完全相同的序列化结果及哈希。

## 7. 明确排除

本任务不实施：

- 5D/60D 或其他持有期；
- 滚动窗口、市场阶段、行业或市值分层；
- 样本外验证；
- 多重检验或 FDR；
- F/R 轨道；
- 方向重选或最佳格选择；
- 因子准入、生产状态或持久化；
- `FinancialEvaluationRun` 和 `FactorEvaluationSummary`。

运行对象和研究摘要属于下一任务 `FIN-MVP-OUTPUT`。

## 8. 黄金验收

冻结黄金样本包含 12 个配置月末、每月 30 只证券。前 6 个月 Rank IC 为正，
后 6 个月整体为负，因此：

```text
full rank_ic_mean = 1/3
first_half rank_ic_mean = 1
second_half rank_ic_mean = -1/3
preprocessing_consistency = consistent
subperiod_direction_consistency = mixed
best_cell_selected = false
```

另有 outlier、标签缺失、常数收益和常数 BP 截面用例，验证 raw/MAD 差异、
覆盖率下降和 `not_run` 退化可复现。

验收结果：

```text
FIN-MVP-ROBUST targeted: 31 passed / 0 failed
R1A/B/C + MVP-DATA + R2-PREP + M-EVAL + ROBUST: 321 passed / 0 failed
wider explicit regression: 929 passed / 4 skipped / 0 failed / 273 warnings
```

最终结论：

```text
FIN-MVP-ROBUST = ACCEPTED
```
