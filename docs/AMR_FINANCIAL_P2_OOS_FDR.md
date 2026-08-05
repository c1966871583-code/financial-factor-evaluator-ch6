# FIN-P2-OOS-FDR：冻结样本外验证与多重检验控制

## 1. 任务结论

FIN-P2-OOS-FDR 已在隔离工作副本中实现一套确定性、只读、一次性使用的
样本外检验协议。协议逐项执行 `FIN-EXP-00-HYP-v1.0` 注册的 23 个命名
假设，在四个预注册家族内分别实施 Benjamini–Hochberg（BH）FDR 调整，
并将无命名假设的 `ROBUSTNESS_EXPLORATORY_V1` 明确保留为 `not_run`。

本任务仅形成合成数据上的契约与执行证据。研究结论固定为
`exploratory`，生产状态固定为 `not production ready`。原始 p 值或
BH-FDR 拒绝结果都不是准入结论、生产结论、收益承诺、舞弊认定、
无风险认定或交易指令。

## 2. 权威输入与前置锚点

- 假设注册表：`FIN-EXP-00/03-主假设与多重检验注册表.md`
- 实验矩阵：`FIN-EXP-00/02-首批实验矩阵.csv`
- 注册版本：`FIN-EXP-00-HYP-v1.0`
- 矩阵版本：`FIN-EXP-00-MATRIX-v1.0`
- 前置任务：`FIN-P2-INDEP`
- 前置状态：`ACCEPTED`
- 前置输出指纹：
  `34048940ea418305b51ff36072d41ea7bd4c6220dbf47938377ed331811c9ae7`

前置锚点的任务代号、验收状态或输出指纹任一不一致，执行即
`blocked`。

## 3. 冻结分区和测试使用协议

分区固定为严格按时间排序的 60%/20%/20%：

| 分区 | 比例 | 允许用途 |
|---|---:|---|
| train | 60% | 建模、描述性分析 |
| calibration | 20% | 校准、验证 |
| test | 20% | 最新区间一次性只读检验 |

测试区固定为 `latest_20pct_one_shot_read_only`。测试区不得用于选择或
修改方向、阈值、模型、家族或样本。实现会拒绝
`selected_direction`、`selected_threshold`、`selected_model`、
`selected_family` 和 `selected_sample` 字段。训练区或校准区的数值
变化不会改变任何假设结果、家族结果、测试输入指纹或输出指纹。

分区清单使用规范化 SHA-256 指纹同时绑定到输入批次和配置。输入记录的
split、period、company_id 必须与清单逐项一致。时间顺序必须满足
`max(train) < min(calibration) < min(test)`；R 轨道公司在三个分区间
必须互斥。

## 4. 命名假设与家族冻结

| 家族 | 命名假设 | 注册数 | 调整方式 |
|---|---|---:|---|
| `F_FORECAST_PRIMARY_V1` | F-P01…F-P06 | 6 | 家族内 BH |
| `R_HARD_PRIMARY_V1` | R-H01…R-H05 | 5 | 家族内 BH |
| `R_SOFT_SECONDARY_V1` | R-S01…R-S05 | 5 | 家族内 BH |
| `M_RETURN_20D_EXPLORATORY_V1` | M-E01…M-E07 | 7 | 家族内 BH |
| `ROBUSTNESS_EXPLORATORY_V1` | 无 | 0 | `not_run` |

不得事后拆分、合并或新增家族。F 和 R-soft 的方向性均值检验沿用注册的
正向或负向尾部；M 使用双侧检验；R-hard 使用相对于基线 PR-AUC 的
固定 199 次确定性置换检验，随机种子为 `20260731`。

## 5. 失败保留与 BH 分母

每个命名假设必须产生一条结果记录。不可计算、样本不足、标签不足、
数据冲突或执行失败的条目：

- 保留原始 `run_status` 和 `failure_reason_code`；
- 原始 p 值及调整后 q 值保持为空；
- 不得标为拒绝原假设；
- 仍计入冻结家族的 BH 分母。

因此，本合成基准中 F 家族完成 5 项但分母仍为 6；R-hard 和 R-soft
各完成 4 项但分母仍各为 5。此规则避免因删除失败项而缩小分母。

## 6. R 轨道标签边界

R-hard 只允许 `hard_positive` 与 `confirmed_negative` 进入 PR-AUC
检验。`soft_positive` 和 `unlabeled` 不得被转换为负样本。每个
R-hard 假设在测试区至少需要 30 个硬阳性和 30 个确认阴性，否则以
`INSUFFICIENT_HARD_TEST_LABELS` 保留失败记录。

R-soft 属于独立的次级证据家族，不得替代 R-hard，也不得与 R-hard
合并调整。

## 7. 确定性合成验收结果

固定合成夹具产生 23 条保留记录，其中 20 条完成、3 条失败：

- F-P06：`INSUFFICIENT_TEST_OBSERVATIONS`
- R-H05：`INSUFFICIENT_HARD_TEST_LABELS`
- R-S05：`INSUFFICIENT_TEST_OBSERVATIONS`

家族结果如下：

| 家族 | 完成/注册 | FDR 分母 | 状态 | BH 后拒绝的假设 |
|---|---:|---:|---|---|
| F | 5/6 | 6 | partial | F-P01…F-P05 |
| R-hard | 4/5 | 5 | partial | R-H01…R-H04 |
| R-soft | 4/5 | 5 | partial | R-S01…R-S04 |
| M | 7/7 | 7 | completed | M-E01、M-E02、M-E04、M-E05、M-E07 |
| robustness | 0/0 | 0 | not_run | 无 |

M-E03 和 M-E06 被完整保留但未在 BH 调整后拒绝原假设。该结果是测试
夹具的预设可验证行为，不构成真实 A 股实证结论。

固定合成运行指纹：

- 分区指纹：
  `f9a35e1bfaf7b7c2a7be62e36320545f593e22291db8c58a0154cf8083752445`
- 输出指纹：
  `b55ec436712231f359976442a9364b19dfd8c017aa309d79a112df442030d53d`
- 审计内容哈希：
  `6dc83f913a23f49c97df65f5d1a252c84f9636fb1bce2db0bf6f504b2b66dd05`

## 8. Fail-closed 条件

下列情况均返回 `blocked`，且不执行任何命名假设：

- FIN-P2-INDEP 锚点不一致；
- 输入未明确标记为仅限合成测试；
- 必需字段缺失、未知假设或重复键；
- 分区比例、时间顺序、记录映射或分区指纹不一致；
- R 轨道公司跨分区重叠；
- 出现任何测试后选择字段；
- 执行期间输入批次发生变化。

批次、配置和结果均采用防御性复制、冻结数据类和规范化哈希；输入行
顺序变化不会改变分区、测试输入或输出指纹。

## 9. 验收范围与后续门禁

验收测试覆盖注册表、政策冻结、BH 分母、失败保留、方向检验、R 标签
边界、一次性测试区隔离、确定性、不可变性、哈希以及 fail-closed
路径。真实 PIT 数据接入、真实样本外结论、经济显著性、成本后绩效、
生产准入与实盘决策均不在本任务范围内。

本任务通过后，建议下一任务为 `FIN-P2-GATE`：汇总 M/F/R 增强证据、
独立性证据与本次 OOS/FDR 证据，执行 Phase 2 研究增强质量门禁。该
门禁仍不得自动升级为生产准入。
