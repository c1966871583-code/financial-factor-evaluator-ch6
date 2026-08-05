# FIN-P3-INFO-GAIN（FIN-25）：共同样本信息增益评价

## 当前计算结论

FIN-25 已按冻结契约完成当前可用 M20 证据范围内的确定性评价：消费 FIN-P3-COMBOS 已验收结果和 M 轨成员基线，不重建样本、组合或评价器结果。依据 Phase3 路由图，这不等于父任务验收；INFO-GAIN-02C/02D 与 03B/03C 尚未完成。

```text
gate_status = ready
parent_task_gate_status = blocked_incomplete_routed_children
research_scope = synthetic_common_sample_M20_only
combo_count = 3
information_gain_assessment = insufficient_evidence
admission_status = not_assessed
production_status = not production ready
```

这里的 `gate_status=ready` 仅表示当前计算输入和输出有效。“完成”仅指 M20 评价与缺口审计已完成；父任务为 `NOT_ACCEPTED`，也不表示任何组合获得正向信息增益、因子准入或生产批准。

## M:20D 描述性结果

| 组合 | 冻结规则选出的最强成员 | M 方向评价 | Rank IC 相对最强成员 | ICIR 相对最强成员 | 单调性 | 控制后平均 R² |
|---|---|---|---|---|---|---|
| VQ | EBIT_EV | mixed | positive | negative | tie | positive |
| QG | OCF_NP | supportive | positive | positive | tie | positive |
| CASHQ | OCF_SALES | supportive | positive | positive | tie | positive |

这些是合成 M:20D 样本内方向描述。VQ 的 ICIR 恶化，三组单调性均未改善；QG/CASHQ 即使多个方向为正，也不能越过缺失证据门禁。

每个 M 指标分别与以下基准比较：

1. 按 `rank_ic_mean@20D`、成员 ID 字典序打破并列所确定的最强冻结成员；
2. 全部冻结成员在同一标量指标上的简单算术平均；
3. FIN-P3-COMBOS 运行前预指定基准：VQ→BP、QG→ROE、CASHQ→OCF_NP。

越高越好指标使用 `combo - baseline`；越低越好指标使用 `baseline - combo`；目标距离指标比较到目标的绝对距离。相对增量分母绝对值不大于 `1e-12` 时，保留绝对增量并把相对增量标记为不可评价，不填 0。

## 覆盖代价

三组均为 1044 条合格观测、900 条共同样本，绝对损失 144 条、相对损失 `0.13793103448275867`；18 期每期共同样本均为 50 条。成员原始可评价计数沿用组合构造审计逐项报告。

上游没有保留逐期合格分母、交集排除的互斥原因分解及共同样本前后的行业/规模分布，因此：

```text
per_period_coverage_ratio_status = insufficient_denominator_not_retained
coverage_explanation = partial_explanation_source_breakdown_not_retained
coverage_acceptance_threshold = not_frozen_report_facts_only
automatic_rejection_applied = false
```

## 未满足的 FIN-25 核心条件

- M:5D、M:60D 未冻结，不能评价期限一致性或自动选择最佳期限；
- 没有组合级冻结样本外结果，不能评价 OOS 方向一致性；
- 没有逐期 IC/收益序列，不能评价结果是否集中于单一时期；
- F 和 R 同共同样本结果未冻结，状态为 `not_run/insufficient`；
- 没有组合级 OOS 假设，不能运行新的多重检验/FDR；
- 核心指标“显著恶化”和“清晰改善”的材料性阈值未冻结；
- 覆盖损失只能部分归因；
- 当前全部输入为合成研究夹具，数据生产门禁未通过。

因此三组正式信息增益判断均为 `insufficient_evidence`，而不是 `positive_increment`。

## 四项生产门禁

| 门禁 | 状态 |
|---|---|
| 数据门禁 | `not_passed_synthetic_only` |
| 信号门禁 | `not_assessed_oos_and_materiality_unavailable` |
| 风险门禁 | `not_run_R_context_not_frozen` |
| 运维门禁 | `not_assessed_research_output_only` |

模块没有执行动态权重、最佳期限选择或 M/F/R 综合总分。结果不得用于收益承诺、交易指令、欺诈认定或生产发布。
