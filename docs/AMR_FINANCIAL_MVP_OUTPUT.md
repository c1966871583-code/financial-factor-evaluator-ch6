# FIN-MVP-OUTPUT：确定性运行对象与研究摘要

状态：`ACCEPTED`

运行对象 Schema：`FinancialEvaluationRun-v1.0`

摘要 Schema：`FactorEvaluationSummary-v1.0`

哈希契约：`FIN-MVP-OUTPUT-HASH-v1.0`

## 1. 定位

本任务把已验收的 FIN-MVP-DATA、FIN-R2-PREP、FIN-MVP-M-EVAL 和
FIN-MVP-ROBUST 结果组装为：

```text
FinancialEvaluationRun
FactorEvaluationSummary × 3
```

`FinancialEvaluationRun` 保存完整工程审计；摘要只从已校验的运行对象投影，
不读取原始输入、不重新计算统计，也不改变公共
`SecurityLevelEvaluationResult`。

## 2. FinancialEvaluationRun

运行对象保存：

- 内容寻址、无墙钟时间的确定性 `run_id`；
- 三因子公共评价结果及对齐审计；
- 统一 gate 结果；
- timing、provenance 和 observation lineage 引用；
- 覆盖报告与预处理审计；
- 完整基础稳健性证据；
- 分因子研究证据状态；
- M-EVAL、ROBUST 和输出配置快照；
- MVP、预处理、收益、M-EVAL 和 ROBUST 指纹；
- 运行对象内容哈希。

相同输入和配置必须产生相同 `run_id`、序列化内容和哈希。运行对象不保存
`created_at`、`updated_at` 或其他非确定墙钟字段。

## 3. 覆盖率语义

当前 MVP 输入只暴露已形成的因子样本，没有独立 PIT universe 分母。因此：

```text
universe_count = null
factor_coverage_rate = null
paired_coverage_rate = null
universe_denominator_status = not_available
```

同时保留可验证的：

```text
valid_factor_count
paired_count
effective_evaluation_dates
label_to_factor_alignment_rate
```

不得拿 `valid_pair_count` 或因子样本数冒充 universe 分母。运行 gate 和每份摘要
均记录 `UNIVERSE_DENOMINATOR_UNAVAILABLE`。

## 4. FactorEvaluationSummary

每个摘要严格包含规划中的字段组：

```text
factor identity
validation track and evidence priority
evaluation period/frequency/horizon
sample_summary
primary_statistics
robustness_summary
status_summary
key_findings
warnings
limitations
source_run_content_hash
```

投影前必须重新计算并核对 `FinancialEvaluationRun.content_hash`。摘要中的主统计
逐字段直接来自 run 内公共评价结果；稳健性字段直接来自 run 内稳健性证据。
`source_run_content_hash` 将每份摘要绑定到唯一运行对象。

## 5. 状态分层

四类状态互不替代：

```text
calculation_status:
completed / partial / not_run / not_applicable

gate_status:
ready / blocked

evidence_assessment:
exploratory / insufficient

production_status:
not production ready
```

MVP 合成运行完成时，证据状态固定为 `exploratory`；计算未完成时为
`insufficient`。本任务不会根据 IC 大小产生 `supportive`、`unsupportive` 或
准入结论。

未实施的样本外一致性为：

```text
oos_consistency = not_run
```

不是零，也不是不支持证据。

## 6. Fail-closed

以下情况阻断完整运行对象和所有摘要：

- 输入类型或配置不符合冻结契约；
- 任一前置 gate 未就绪；
- 因子集合不是严格的 ROE、BP、OCF_NP；
- observation lineage 引用缺失；
- ROBUST 结果不能由相同输入、M-EVAL 和配置精确复算；
- run 内容哈希失配；
- 摘要投影失败；
- 构建过程修改输入。

阻断时：

```text
financial_evaluation_run = null
factor_evaluation_summaries = []
```

不输出部分因子包。

## 7. 明确禁止

本任务不执行：

- Supabase、数据库、文件持久化或查询 API；
- Research Log 自动化；
- P0-6 人工审核或准入；
- `approved/admitted/rejected/conditionally_passed` 状态；
- OOS、多重检验、FDR、F/R 轨道；
- 因子方向重选；
- 生产就绪声明；
- Git 写操作或源 main 回迁。

## 8. 黄金验收

黄金运行：

```text
run_id =
fin-mvp-output-68150aa59b7d17c779648f5b

run_content_hash =
fcae2be3e10b74444922c8e04f7b6ea909b7e8bea05b5eb2440bf9d17f8b5c0e
```

三份摘要均为：

```text
calculation_status = completed
gate_status = ready
evidence_assessment = exploratory
production_status = not production ready
preprocessing_consistency = consistent
subperiod_direction_consistency = mixed
oos_consistency = not_run
```

常数 BP 用例确定性投影为 `not_run / insufficient`，主统计保持 `null`。

验收结果：

```text
FIN-MVP-OUTPUT targeted: 38 passed / 0 failed
financial chain joint: 359 passed / 0 failed
wider explicit regression: 967 passed / 4 skipped / 0 failed / 273 warnings
```

最终结论：

```text
FIN-MVP-OUTPUT = ACCEPTED
```
