# FIN-P3-INFO-GAIN-02C：F 轨道成员共同样本基线

02C 已实现为正式、可审计的 F 轨道 `not_run` 基线包。

## 为什么是 `not_run`

已验收的 INFO-GAIN-02A 输入契约只冻结了 `M:20D`。三个组合的 F 轨道均为：

```text
preparation_status = not_run
reason_code = CONTEXT_NOT_FROZEN
evaluation_contexts = []
label_references = []
evaluation_config_reference = null
```

既有 F 评价器 `evaluate_financial_p2_f_evidence` 使用独立的 PIT 下一季度经营预测批次、同季度去年基准、60/20/20 时间切分和 80% 预测区间。共同样本中的成员因子值、20D 收益和控制变量不能合法地替代这些输入。因此 02C 不构建预测数据、不改写 02A、不调用评价器，也不填充零值或伪造 MAE、残差 Rank IC、区间覆盖率或校准误差。

## 冻结输出

为 VQ、QG、CASHQ 的 11 个“组合×成员”条目分别生成：

- `calculation_status = not_run`
- `not_run_reason = F_CONTEXT_NOT_FROZEN`
- 五项 F 指标各自 `metric_status = not_run` 且 `metric_value = null`
- 已冻结成员、方向、共同样本引用和共同样本指纹
- 既有 F 评价器引用与源码哈希，仅用于漂移核验

五项状态化指标为 `oos_mae`、`relative_mae_improvement`、`residual_rank_ic`、`interval_coverage` 和 `interval_calibration_error`。

## 门禁

运行前必须确认：02A gate 为 `ready`、02A 输出和包内容指纹一致、INFO-GAIN-01 契约哈希一致、F 评价器源码哈希一致、组合/成员/方向未漂移，且每个 F 输入仍为上述正式 `not_run` 状态。

如果 F 输入变为 `ready`、出现标签或配置引用、或者任意前置哈希漂移，模块立即 `blocked`，不会自动调用 F 评价器。真正的 F 成员预测基线需要单独冻结 F 标签、同一基准、相同时间切分、训练/校准/测试隔离及明确授权后另行实施。

## 绝对边界

本步骤不进行 F/M/R 实际评价、组合评价、成员优劣选择、信息增益比较、动态权重、最佳期限、综合总分、生产准入或任何市场/交易结论。输出继续为 `not production ready`。

## 确定性合成结果

```text
gate_status = ready
combo_count = 3
member_run_count = 11
completed_run_count = 0
not_run_count = 11
F/M/R evaluator calls = 0/0/0
output_fingerprint = 657bd843d245aa2379105612acfe0cabc7c09da538819a2abd6719352c22e64c
audit_content_hash = ba48f11804582835a4a7313bd794cf58000e351dc1af23ed2b77c4fc8cb20adb
```
