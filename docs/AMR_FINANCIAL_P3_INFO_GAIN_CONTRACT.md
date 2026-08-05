# FIN-P3-INFO-GAIN-01 信息增益评价契约

## 1. 定位

本契约冻结 FIN-25 后续任务应当如何比较 FIN-24 预设组合与成员因子。它只包含
比较对象、共同样本锚点、基准、指标方向、覆盖代价、状态语义及确定性序列化规则。

本契约不包含组合或成员的评价值，不调用 M、F、R 评价器，不重算成员基线，不
选择最强成员或最佳持有期，也不作出信息增益、因子准入或生产结论。

```text
research_assessment = exploratory
admission_status = not_assessed
production_status = not production ready
FIN-P3-INFO-GAIN-02 = NOT_STARTED
```

契约版本为 `FIN-P3-INFO-GAIN-CONTRACT-v1.0`，当前配置内容哈希为：

```text
e6d51313ae0fb326d4b239dbb3aefe542c8d5d623237b05e7678959436766747
```

## 2. 前置锚点

```text
predecessor_task = FIN-P3-COMBOS
predecessor_status = ACCEPTED
predecessor_output_fingerprint =
7c8686b44f3842f159b3fbbc45aa9908f3bf81acd5ebec381f8ac4f5c1933fa2
```

| 组合 | 版本 | 成员及方向 | 预指定主基准 |
|---|---|---|---|
| VQ | FIN-24-VQ-v1.0 | BP+、EBIT_EV+、ROE+、OCF_NP+ | BP |
| QG | FIN-24-QG-v1.0 | SALES_GROWTH+、PROFIT_GROWTH+、ROE+、OCF_NP+ | ROE |
| CASHQ | FIN-24-CASHQ-v1.0 | ROA+、OCF_SALES+、ACCRUALS- | OCF_NP |

CASHQ 的 `OCF_NP` 是 FIN-P3-COMBOS 在构造前预声明的参照，不是 CASHQ 成员，
也不是根据结果挑选的“最佳成员”。

## 3. 共同样本

后续比较必须使用组合自己的已验收共同样本，不能合并成一个全局指纹。

| 组合 | 评价期 | 行数 | 指纹 |
|---|---:|---:|---|
| VQ | 18 | 900 | `ab58b5b1cf5e975563838f9e5aecd367f9c70a25d10d2678c69c6fa4a2f037d1` |
| QG | 18 | 900 | `3e470edf7b8b8e065ec6f373e2e5872e1cabf42e360212928ecc7276834839ae` |
| CASHQ | 18 | 900 | `c3d21f755aae395d179e23b361948bcb232f4e52625d12e5dd98bf013ebcd4f7` |

当前上游只验收了 `M:20D` 评价上下文。`M:5D`、`M:60D`、`F` 和 `R` 均保留
正式 `not_run` 引用槽；在各自样本、标签和切分指纹经单独授权冻结前不得评价，
也不得把 20D 指纹冒充其他上下文指纹。

成员与组合的正式比较结构必须是：

```text
成员因子在该组合共同样本上的结果
vs
组合在同一共同样本上的结果
```

两侧必须保持相同评价日期、证券、标签、标签版本、收益期限、时间切分、样本外
测试集和评价配置。禁止把成员全样本结果直接作为共同样本基线。

## 4. 比较基准

### 4.1 分轨最强成员

这里只冻结后续选择规则；本任务不运行该选择。

| 轨道 | 冻结主指标 | 期限 | 并列规则 |
|---|---|---|---|
| M | rank_ic_mean | 20D | factor_id 字典序 |
| F | relative_mae_improvement | 不适用 | factor_id 字典序 |
| R | pr_auc | 不适用 | factor_id 字典序 |

候选范围只能是组合的冻结成员，禁止搜索外部因子、因子子集、权重或持有期。

### 4.2 成员平均

只允许对同一轨道、同一指标、同一共同样本上的可比较标量使用简单算术平均。
所有冻结成员均为必需项；任一成员不可评价时，成员平均基准记为不可评价，不得
删除失败或表现较差的成员。分组收益向量和稳定性对象不能直接平均成标量增量。

### 4.3 预指定主基准

固定为 `VQ→BP`、`QG→ROE`、`CASHQ→OCF_NP`，沿用 FIN-P3-COMBOS 的运行前
参照。不得根据 FIN-24 或 FIN-25 结果修改。

## 5. 指标与方向

### 5.1 M 轨：Primary Evidence

| 指标 | 方向 | 备注 |
|---|---|---|
| Rank IC mean | 越高越好 | 5D/20D/60D 分开保存 |
| Pearson IC mean | 越高越好 | 5D/20D/60D 分开保存 |
| Rank/Pearson ICIR | 越高越好 | 不自动挑期限 |
| Rank/Pearson HAC t | 越高越好 | 使用有符号 HAC t，不取绝对值 |
| Rank/Pearson IC 正向比例 | 越高越好 | 沿用原始方向 |
| 分组收益 | 明细项 | 不直接产生标量增量 |
| High-Low | 越高越好 | 沿用原始方向 |
| 分组单调性 | 越高越好 | 沿用现有 Spearman 语义 |
| 控制后平均 R² | 越高越好 | 控制规模和行业，沿用 FIN-23 语义 |
| Rank IC 滚动稳定性 | 明细项 | 保留对象，不合成为总分 |

普通 t 值不在公共 M 轨指标中。

### 5.2 F 轨：Supporting Evidence

| 指标 | 方向或目标 |
|---|---|
| 样本外 MAE | 越低越好 |
| 相对 MAE 改善 | 越高越好 |
| 残差 Rank IC | 越高越好 |
| 80% 区间覆盖率 | 越接近 0.80 越好 |
| 区间校准误差 | `abs(coverage - 0.80)`，越低越好 |

F 轨必须复用相同的同季度上年基准、时间顺序 60/20/20 切分、目标变量和一次性
测试政策。F 证据不能替代 M 轨，也不能解释为股价预测能力。

### 5.3 R 轨：Risk Evidence

| 指标 | 方向或配置 |
|---|---|
| PR-AUC | 越高越好 |
| ROC-AUC | 越高越好 |
| Brier Score | 越低越好 |
| Top-K 命中率 | 越高越好，`top_k=10` |
| ECE | 越低越好，`calibration_bins=5` |

R 轨必须维持 hard/soft/unlabeled 语义和公司隔离；unlabeled 不得视为确定负例。
输出只能用于人工复核优先级，不能形成造假、错报或法律认定。

## 6. 增量公式

本节只冻结公式字符串，不在本任务中代入任何运行结果。

越高越好：

```text
absolute_increment = combo_metric_value - baseline_metric_value
```

越低越好：

```text
absolute_increment = baseline_metric_value - combo_metric_value
```

越接近目标越好：

```text
absolute_increment =
  abs(baseline_metric_value - target_value)
  - abs(combo_metric_value - target_value)
```

一般相对增量：

```text
relative_increment = absolute_increment / abs(baseline_metric_value)
```

目标距离指标使用基准目标距离作为分母。基准缺失、非有限、未运行、不可评价、
样本不足，或分母绝对值不大于 `1e-12` 时，结果必须为正式不可评价状态，不能
静默填充 `0`、无穷或 `false`。

## 7. 覆盖代价

后续评价至少报告：

1. 成员原始可评价样本数和覆盖率；
2. 组合共同样本数和覆盖率；
3. 绝对及相对覆盖损失；
4. 逐评价期覆盖率；
5. 有效评价期损失和样本不足期；
6. 排除原因分类；
7. 数据支持时的行业和规模分布变化。

当前没有冻结可接受覆盖阈值，只允许报告事实。不得因组合表现或覆盖损失自动隐藏、
删除或拒绝组合。

## 8. 状态语义

计算状态复用项目现有值：

| 契约语义 | 项目值 | 来源 |
|---|---|---|
| success | completed | EvaluationStatus |
| not_run | not_run | EvaluationStatus |
| not_evaluable | not_applicable | EvaluationStatus |
| insufficient_data | insufficient | CommonSampleEvaluationStatus |
| failed | blocked | CombinationGateStatus |

信息增益判断是独立层：

```text
positive_increment
no_increment
negative_increment
mixed_increment
insufficient_evidence
not_assessed
```

本任务默认且仅产生 `not_assessed`。M、F、R 证据状态分别保存，禁止简单平均成
综合总分。任何未来 `positive_increment` 都不能自动把生产状态升级为 ready。

## 9. 确定性与禁止能力

契约使用冻结数据类、规范 UTF-8 JSON、排序键、冻结领域顺序和 SHA-256。成员或
组合输入顺序变化不影响输出顺序和内容哈希。契约不包含当前时间或随机值。

以下能力在配置中固定为 `false`：

```text
real_result_computation_allowed
member_baseline_recalculation_allowed
evaluation_pipeline_execution_allowed
dynamic_weighting_allowed
automatic_best_member_selection_allowed
automatic_best_horizon_selection_allowed
cross_track_composite_score_allowed
```

## 10. 后续门禁

本契约独立验收只表示评价规则已冻结。只有 `FIN-P3-INFO-GAIN-01 = ACCEPTED`
后，才可以重新启动 `FIN-P3-INFO-GAIN-02` 的只读前置核验；不会自动授权或启动
第二步。
