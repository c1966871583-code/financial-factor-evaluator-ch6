# FIN-P2-F：F 轨 Supporting Evidence

## 1. 定位

`backend/amr/financial_p2_f_evidence.py` 提供第六章 Phase 2 的 F 轨最小
样本外增量证据。它回答一个受限问题：在严格 PIT、时间顺序切分和一次测试条件下，
稳健线性增量模型能否改善上年同期基准。

本输出的固定属性为：

```text
validation_track = F
evidence_priority = supporting
m_replacement_allowed = false
synthetic_test_only = true
```

因此它不能替代 M 轨 Primary Evidence，不是生产准入结论，也不是实际经营结果保证。
模块不预测股价，不产生买卖信号或投资建议。

## 2. 四个目标

每条样本的 `feature_report_period` 只配对同一公司的下一自然季度
`target_report_period`：

| 目标 ID | 训练和评价目标 |
|---|---|
| `next_quarter_revenue` | 下一季度营业收入 |
| `next_quarter_parent_net_profit` | 下一季度归母净利润 |
| `next_quarter_operating_cash_flow` | 下一季度经营现金流 |
| `next_quarter_gross_margin` | 下一季度毛利率 |

金额字段为单季度口径的合成 RMB 数值。金额目标的增量先除以当前总资产拟合，输出时
恢复金额；毛利率直接拟合差值。基准固定为目标季度的上年同期值
`same_quarter_last_year`。

## 3. PIT 与版本语义

必需字段为：

```text
symbol
report_period
announced_at
version_at
revenue
parent_net_profit
operating_cash_flow
operating_cost
total_assets
total_liabilities
equity
```

`report_period` 必须是自然季度末。`version_at` 不得早于 `announced_at`，且
`symbol/report_period/version_at` 必须唯一。

版本选择分两层：

1. 先排除 `announced_at > as_of` 或 `version_at > as_of` 的记录；
2. 历史预测原点取当前季度的首次可见版本时点；
3. 当前特征与上年同期基准只使用该原点已可见的最后版本；
4. 历史目标标签使用全局 `as_of` 已可见的最后版本。

这使后来修订不能回流为过去预测原点的特征。输出同时保留
`feature_visible_at`、`label_available_at`、版本策略和输入指纹。

## 4. 模型与一次测试

模型固定为 `robust_linear_incremental`。它使用训练集的中位数与 MAD 标准化，
通过 Huber 权重迭代拟合带微小固定岭惩罚的线性增量，不进行超参数搜索。

特征仅来自预测原点已可见记录：

```text
current_target_scaled
current_target_yoy_delta_scaled
revenue_yoy_delta_scaled
profit_margin
cash_margin
gross_margin
leverage
quarter_q2 / quarter_q3 / quarter_q4
```

所有目标季度去重并排序后，按季度组切分：

```text
最早 60% = train
中间 20% = calibration
最新 20% = one-shot test
```

同一目标季度不会跨分区。模型只在 train 拟合；calibration 只校准残差区间；
test 只评价一次，不选择方向、阈值、模型、特征或组合。测试标签发生变化时，冻结的
模型指纹和切分指纹不应变化。

## 5. 主证据

每个目标并列报告：

- 测试集 `oos_mae`；
- 上年同期 `baseline_mae`；
- `relative_mae_improvement`；
- 每个测试季度横截面的预测增量与真实增量 Spearman 均值
  `residual_rank_ic`；
- 模型相对基准逐季度改善的正向比例与 `direction_stability`；
- 训练、校准、测试季度及样本数；
- 模型、切分、预测和汇总内容哈希。

`direction_stability=consistent_positive` 表示每个测试季度的模型 MAE 都小于
基准 MAE；它不表示未来方向保证。

## 6. 80% 研究区间

区间半宽是 calibration 绝对残差的 80% 分位数，test 完全不参与校准。只有校准
残差数不少于 20 时才输出：

```text
[prediction - calibration_q80, prediction + calibration_q80]
```

少于 20 条时：

```text
interval_status = not_run_insufficient_calibration_residuals
interval_low_80 = null
interval_high_80 = null
status = partial
```

区间是历史校准结果，不是置信保证。可靠性标签遵循研究约束：只有经营现金流或
毛利率、校准样本不少于 100 且 OOS MAE 相对基准改善超过 5% 时，才可标记
`reliable_research`；其余可用输出为 `experimental`。

## 7. 失败关闭与审计

缺列、非法日期或数值、非季度末、重复版本键、版本早于公告、非正缩放量、
样本不足、非合成来源或输入变异均产生结构化错误并返回：

```text
gate_status = blocked
target_evidence = []
```

准备完成时，审计包含原始/可见/选中样本数、`as_of` 排除数、四目标、PIT 策略、
配置指纹、输入指纹、选中样本指纹、输出指纹和审计内容哈希。输入 DataFrame 在
构造批次时深拷贝，读取也返回副本；评价前后再执行内容守卫。

## 8. 合成验收边界

`tests/fixtures/synthetic_financial_p2_f_evidence_cases.py` 构造 20 家公司、
28 个自然季度、四目标和确定性版本时点。合成序列用于验证协议和失败语义，不得
冒充真实 A 股预测结果。定向验收位于
`tests/test_amr_financial_p2_f_evidence.py`，覆盖：

- 四目标和 60/20/20 严格切分；
- OOS MAE、基准改善、残差 Rank IC 和逐季度方向；
- 校准区间阈值；
- 未来版本隔离和测试集不调参；
- 输入不可变、顺序确定性和哈希；
- 非合成、PIT、schema、版本、样本不足等失败状态；
- F 仅为 Supporting Evidence 的边界。

未实施真实数据访问、行业或规模中性化、Fama–MacBeth、多重检验、因子准入、
生产持久化或任务 8 交接。
