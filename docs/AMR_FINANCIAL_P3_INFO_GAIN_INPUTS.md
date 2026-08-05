# INFO-GAIN-02A：共同样本输入准备

## 任务结论

本模块只验证并封装 FIN-P3-COMBOS 已冻结的三份共同样本，形成可供后续 M/F/R 子任务消费的输入包。它不求取样本交集、不构造组合、不调用评价器、不计算指标或增量。

黄金合成夹具结果：

```text
gate_status = ready
combo_count = 3
total_common_sample_rows = 2700
exact_frozen_samples_verified = true
pit_safe = true
common_input_packages_created = true
sample_reconstructed = false
combination_constructed = false
evaluator_calls_performed = false
metrics_calculated = false
strongest_member_selected = false
information_gain_decision_made = false
production_status = not production ready
```

## 冻结样本

| 组合 | 期数 | 每期行数 | 总行数 | 共同样本指纹 |
|---|---:|---:|---:|---|
| VQ | 18 | 50 | 900 | `ab58b5b1cf5e975563838f9e5aecd367f9c70a25d10d2678c69c6fa4a2f037d1` |
| QG | 18 | 50 | 900 | `3e470edf7b8b8e065ec6f373e2e5872e1cabf42e360212928ecc7276834839ae` |
| CASHQ | 18 | 50 | 900 | `c3d21f755aae395d179e23b361948bcb232f4e52625d12e5dd98bf013ebcd4f7` |

样本指纹按 FIN-23 的 `p3_common_sample_rows` 哈希域和其冻结哈希契约版本复算；仅声明正确指纹但实际证券—日期键漂移时仍会阻断。

## 输入包内容

每个组合包包含：

- 组合 ID、定义版本和已验收共同样本引用；
- 900 条显式证券—日期清单；
- 所有冻结成员在完全相同键上的观测；
- 成员方向、公式版本和源运行引用；
- 标签、规模与行业控制及其生效日期；
- 每期行数；
- M、F、R 三轨输入准备状态；
- 数据范围和来源 provenance；
- 规范 JSON 与确定性 SHA-256。

输入包不含组合值、最佳成员、指标、差值、信息增益或准入字段。

## 三轨准备状态

```text
M:
  preparation_status = ready
  evaluation_contexts = [M:20D]
  label_reference = SYNTHETIC-FORWARD-RETURN-20D-v1
  evaluation_config_reference = FIN-P3-COMMON-SAMPLE:M20:v1.0

F:
  preparation_status = not_run
  reason_code = CONTEXT_NOT_FROZEN

R:
  preparation_status = not_run
  reason_code = CONTEXT_NOT_FROZEN
```

02A 只说明 M:20D 引用完整。它不授权或执行 INFO-GAIN-02B，也不会用 M 标签冒充 F/R 标签。F/R 只有在各自样本、标签和配置引用单独冻结后才能进入 `ready`。

## PIT 和一致性检查

所有显式共同样本行必须满足：

```text
factor_effective_date <= evaluation_date
control_effective_date <= evaluation_date
return_start_date > evaluation_date
```

每个冻结成员必须覆盖完全相同的 900 个键；同一证券—日期上的标签、规模控制和行业控制必须一致。因子值、收益和规模控制必须有限，行业代码不得为空。

以下漂移均 fail closed：前置输出、契约、组合版本、样本引用或实际键、期数/行数、成员集合/键、标签/控制、PIT 日期、公式/运行引用、三轨状态，以及任何选择、指标、差值或决策字段。

## 研究与路由边界

当前输入来自确定性合成测试夹具，只用于验证契约和流水线结构，不能解释为真实 A 股信息增益。02A 独立验收后，下一状态只能是 `INFO-GAIN-02B = AWAITING_EXPLICIT_IMPLEMENTATION_AUTHORIZATION`；不得自动运行 M 评价，更不得跳转到 02C、02D、03A 或 Research Log。

