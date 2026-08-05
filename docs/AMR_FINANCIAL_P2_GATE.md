# FIN-P2-GATE：Phase 2 研究增强质量门禁

## 1. 门禁结论

FIN-P2-GATE 将已验收的 M、F、R、独立性和 OOS/FDR 五项 Phase 2
证据汇总为确定性研究完整性门禁。合成黄金证据束的结果为：

```text
gate_status = ready
research_integrity_status = complete
FIN-28 checks = 11 / 11 satisfied
production gates = 0 / 4 satisfied
research_assessment = exploratory
production_status = not production ready
admission_status = not_assessed
```

`complete` 只表示 FIN-28 规定的研究材料在当前合成范围内齐备，不表示
因子有效、正式准入、生产批准、真实收益、舞弊或错报认定、无风险认定或
交易指令。

## 2. 前置证据锚点

门禁要求下列五项任务各出现一次、状态为 `ACCEPTED`，且输出指纹与冻结
值一致：

| 前置任务 | 门禁用途 |
|---|---|
| `FIN-P2-M-ENH` | IC、分组、方向、覆盖与稳健性主证据 |
| `FIN-P2-F` | F 轨方向、PIT、数据质量与覆盖支持证据 |
| `FIN-P2-R` | R 轨方向、标签、PIT、数据质量与覆盖支持证据 |
| `FIN-P2-INDEP` | M/F/R 独立性与增量证据 |
| `FIN-P2-OOS-FDR` | 冻结一次性 OOS、原始 p 值、BH-FDR 和失败保留 |

门禁不重新计算前置任务的统计量，而是核对已验收输出的不可变指纹和明确
边界。缺失、重复、未知、未验收或指纹不符的前置项都会使门禁
`blocked`。

## 3. FIN-28 十一项研究完整性检查

| 检查 | 冻结来源 |
|---|---|
| PIT 审计 | M、F、R |
| 数据质量 | M、F、R |
| 覆盖率阈值 | M、F、R |
| IC 证据 | M |
| 分组证据 | M |
| 方向证据 | M、F、R |
| 独立性证据 | INDEP |
| 稳健性证据 | M |
| 样本外证据 | OOS/FDR |
| Research Log 归档 | 五项前置 |
| 警告解释 | 五项前置 |

质量门禁检查材料是否完整，不硬编码“收益必须大于某个值”，也不从 p 值
或 q 值推导准入结论。

合法但材料不完整时，门禁保持 `ready`，研究完整性为 `incomplete`，并
明确指出未满足项。例如：

- Research Log 未标记为 `archived_in_result`；
- 任一前置警告没有一一对应的非空解释。

契约或授权失配时则为 `blocked`，不继续形成研究完整性结论。

## 4. OOS/FDR 失败保留

OOS/FDR 锚点必须同时满足：

```text
registered_hypothesis_count = 23
completed_run_count = 20
failed_run_count = 3
failed_runs_count_in_family_denominator = true
robustness_family_status = not_run
test_use_policy = latest_20pct_one_shot_read_only
```

三项失败运行仍进入 Research Log，且继续占用冻结家族分母。门禁不会删除
失败记录、把失败改写为完成，或因某些 BH 结果显著而将证据升级为
`supportive`。

## 5. Research Log 边界

门禁为五个前置任务各生成一条不可变、可序列化的日志条目，保存：

- 前置任务与状态；
- 输出指纹；
- 研究和生产边界；
- 警告代码；
- 保留与失败运行数；
- 失败保留状态；
- 日志内容哈希。

日志只在返回结果中以 `in_result_snapshot_only` 归档，并形成统一
Research Log 指纹。当前未授权写入 Supabase、正式因子库、API 或机器
固定路径，因此：

```text
formal_persistence_performed = false
```

声明已经进行正式持久化会触发 fail closed。

## 6. 四项生产门禁

生产使用必须同时满足：

1. 独立标签或证据复核；
2. 真实实时数据契约和授权；
3. PIT 正确版本及历史股票池；
4. 成本后样本外显著性与可复现性。

当前证据全部为确定性合成证据，因此四项均为 `not_satisfied`：

| 生产门禁 | 原因 |
|---|---|
| 独立标签或证据复核 | 缺少获批的真实标签独立复核 |
| 实时数据契约与授权 | 缺少获批的真实生产数据契约 |
| PIT 版本及历史股票池 | 缺少真实 PIT 历史版本和历史股票池 |
| 成本后 OOS 显著性 | 缺少真实成本、交易状态与成本后 OOS 证据 |

任何合成输入声称其中一项已满足都会使门禁 `blocked`，而不是提升生产
状态。

## 7. 四层状态隔离

输出严格区分：

| 层次 | 黄金状态 | 含义 |
|---|---|---|
| 计算门禁 | `ready` | 输入契约有效，可以评价完整性 |
| 研究完整性 | `complete` | FIN-28 材料齐备 |
| 研究证据 | `exploratory` | 合成研究证据，不是实证结论 |
| 生产状态 | `not production ready` | 四项生产门禁未满足 |
| 人工准入 | `not_assessed` | 本模块不作准入判断 |

输入和输出禁止使用 `passed`、`conditionally_passed`、`rejected`、
`factor_admitted` 等正式准入字段或状态。

## 8. Fail-closed 条件

以下情况均阻断：

- 前置任务缺失、重复、未知或未验收；
- 前置输出指纹漂移；
- 前置研究边界不再是 `exploratory / not production ready`；
- 输入未声明为 `synthetic_test_only`；
- OOS/FDR 的 23/20/3、失败分母或一次性测试契约漂移；
- Research Log 声明指纹与计算值不一致；
- 删除已有失败运行；
- 声称已正式持久化；
- 添加准入字段；
- 合成证据声称满足生产门禁；
- 运行期间输入发生变化。

被阻断时仍返回全部 11 个检查槽位，状态均为 `not_satisfied`，避免静默
丢失门禁项。

## 9. 可复现性与测试

实现对前置记录顺序不敏感，重复运行产生相同：

- 输入指纹；
- 前置锚点指纹；
- Research Log 指纹；
- 门禁输出指纹；
- 审计内容哈希。

测试覆盖政策冻结、11 项 FIN-28 检查、四项生产门禁、OOS 失败保留、
完整与不完整状态、全部前置锚点、准入越权、生产越权、不可变性和哈希。

本阶段仍不接入真实数据，不形成真实因子有效性或生产结论。按任务规划，
Phase 2 门禁完成后，下一步应先形成 Phase 2 完成审计与负责人复核，再
决定是否单独授权 Phase 3 的三组预设组合信息增益任务；不得自动启动
Phase 3。
