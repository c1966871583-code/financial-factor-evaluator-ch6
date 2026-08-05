# FIN-P3-INFO-GAIN-03A：M 轨组合相对成员增量

03A 读取已验收的 COMBOS M 共同样本结果及 02B 的 11 条成员基线，逐一输出组合相对每个成员的指标差值；不重算组合或成员，不选择最强成员，也不作总体信息增益判断。

可比指标为 Rank IC 均值、ICIR、Rank IC 正值比例、五分组收益明细、高减低收益和单调性。Pearson/HAC 仅在成员端、FM R² 仅在组合端，按 `not_evaluable` 保留，而非以零填充。五分组收益为 `detail_only`，不产生数值增量。

每条比较要求组合与成员的共同样本指纹、18 期和 900 行完全一致。输出只代表合成 M:20D 研究证据，保持 `not production ready`，不构成 F/R 证据、准入、交易或收益结论。

```text
combo_count = 3
member_count = 11
comparison_count = 143
completed_comparison_count = 66
not_evaluable_count = 77
output_fingerprint = 6a9f764b450431582b5e5955e04dcc0e05978e543648e65d980e40b188ab0c64
```
