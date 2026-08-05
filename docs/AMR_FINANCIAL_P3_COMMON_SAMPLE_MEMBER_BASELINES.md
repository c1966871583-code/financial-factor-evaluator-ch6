# FIN-P3-INFO-GAIN-02：共同样本成员基线重算

## 结论

本模块在 FIN-P3-COMBOS 已验收的三份共同样本上，独立重算组合成员的 M:20D 基线。黄金合成夹具结果为：

```text
gate_status = ready
combo_count = 3
expected_member_count = 11
completed_member_count = 11
failed_member_count = 0
information_gain_delta_calculated = false
information_gain_decision_made = false
production_status = not production ready
```

该结论只说明成员基线计算路径、共同样本绑定、PIT 约束和失败保留语义可复现，不构成真实 A 股证据或信息增益结论。

## 冻结输入

| 组合 | 成员与方向 | 期数 | 行数 | 共同样本指纹 |
|---|---|---:|---:|---|
| VQ | BP+、EBIT_EV+、ROE+、OCF_NP+ | 18 | 900 | `ab58b5b1cf5e975563838f9e5aecd367f9c70a25d10d2678c69c6fa4a2f037d1` |
| QG | SALES_GROWTH+、PROFIT_GROWTH+、ROE+、OCF_NP+ | 18 | 900 | `3e470edf7b8b8e065ec6f373e2e5872e1cabf42e360212928ecc7276834839ae` |
| CASHQ | ROA+、OCF_SALES+、ACCRUALS- | 18 | 900 | `c3d21f755aae395d179e23b361948bcb232f4e52625d12e5dd98bf013ebcd4f7` |

CASHQ 的共同样本仍包含其预指定比较基准 OCF_NP 的可用性约束；OCF_NP 不是 CASHQ 成员，因此不计入本任务的 3 个成员基线。

## 计算规则

- 调用方必须显式提供每个组合已冻结的共同样本清单和成员长表；模块不求交集、不重建组合。
- 每个成员必须具有完全相同的证券—日期键、标签和控制变量。
- 正方向成员原值进入评价器；ACCRUALS 按冻结负方向取反后进入评价器。
- 复用 `evaluate_financial_p3_common_sample`，只保留其 `single_factor_metrics`。
- M:5D、M:60D、F、R 均没有冻结的同样本标签或上下文，正式状态为 `not_run`。
- 单成员失败时保留失败记录和空指标，不以 0、无穷或删除成员代替。

内部调用为“成员与自身占位值”的同样本评价，以复用已验收指标实现；占位侧差值不对外输出，也不用于 FIN-25 判断。

## 防漂移门禁

以下任一情况均在评价前阻断：组合集合、定义版本、共同样本引用或指纹漂移；不是 18 期/900 行；键重复；成员集合或键不一致；标签/控制不一致；公式版本或运行引用不全；携带最佳成员、组合值、差值、信息增益或准入字段。

输入批次、防御性复制、输出、审计和规范 JSON 均具有确定性 SHA-256。输入组合顺序及行顺序变化不改变规范结果。

## 研究边界

当前数据是确定性合成夹具。没有调用真实 M/F/R 生产流水线，没有计算组合—成员增量，没有选择最强成员，没有作出信息增益、准入、收益、欺诈或交易结论。

