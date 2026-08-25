# FIN-MVP-M-EVAL 三因子 M 轨道最小评价

状态：`ACCEPTED`

Schema：`FinancialMVPMEvaluation-v1.0`

审计 Schema：`FinancialMVPMEvaluationAudit-v1.0`

哈希契约：`FIN-MVP-M-EVAL-HASH-v2.0`

## 1. 任务定位

本任务仅评价已批准的三个财务因子：

```text
ROE
BP
OCF_NP
```

评价口径冻结为显式配置的月末评价日、20 个交易日远期收益、每个评价日最少
30 只证券、至少 12 个有效评价日、五组等权分组。模块不修改公共量价评价入口，
而是复用公共 `SecurityLevelEvaluationResult`、分组收益工具和 HAC 统计工具。

## 2. 输入契约

入口：

```python
evaluate_financial_mvp_m(
    mvp_batch_result,
    preprocessing_result,
    forward_returns,
    configuration=configuration,
)
```

必需输入：

- `MVPFinancialBatchResult`：门禁必须为 `ready`，且恰好包含
  `ROE/BP/OCF_NP` 三个公共 `FinancialBatch` 和逐评价日观察引用；
- `FinancialPreprocessingResult`：门禁必须为 `ready`，键集合必须与 MVP
  观察键完全一致；
- `ForwardReturnBatch`：必须为证券层级、包含 `horizon=20`，且当前授权只允许
  `synthetic_test_only=true`；
- `FinancialMVPMEvaluationConfig`：显式给出月末日期、日历引用、日历版本和
  `hac_max_lag`。

配置不继承量价默认值。HAC 滞后阶数必须是 `0..11` 的显式整数。

## 3. 数值与连接语义

因子值使用 FIN-R2-PREP 的：

```text
evaluation_factor_value
```

同时逐条核对：

```text
MVP observation.factor_value
    == public FinancialBatch.factor_value
    == preprocessing.raw_pit_factor_value
```

任一不一致均阻断完整三因子包。

收益标签按以下键左连接到已冻结的因子样本：

```text
evaluation_date + code
```

标签缺失、替换或扰动不得改变因子样本指纹。缺失标签只影响标签对齐指纹、有效
配对数和统计结果，不得反向删除或重塑因子样本。

## 4. 公开统计

每个配置月末输出：

- Spearman Rank IC；
- Pearson IC；
- 五组等权收益；
- 当日样本数和结构化问题码。

跨期输出：

- Rank/Pearson IC 均值、样本标准差、ICIR、正比例；
- 使用显式 `hac_max_lag` 的 HAC t 统计量；
- 五组平均收益、最高组减最低组收益；
- 分组收益的 Spearman 单调性。

若某日有效配对少于 30、因子截面为常数或收益截面为常数，该日被排除并保留
审计记录。少于 12 个有效日期时公共结果状态为 `NOT_RUN`，不报告跨期汇总
统计，但仍保留逐日结果。

## 5. 公共结果兼容

输出对象继续使用既有 `SecurityLevelEvaluationResult`，未增加、删除或重命名
任何公共字段。财务专用审计通过外层 `FinancialMVPMEvaluationResult` 提供：

```text
common_results
factor_audits
evaluation_audit
```

每个因子审计绑定配置日期数、因子样本数、标签可用数、有效日期数、因子样本
指纹、标签对齐指纹和公共结果指纹。总审计绑定配置、MVP、预处理、收益输入、
因子样本和输出指纹。

## 6. Fail-closed 边界

以下情况不输出部分因子结果：

- 上游 MVP 或预处理门禁未就绪；
- MVP 观察引用缺失或观察内容哈希失配；
- 三因子或配置评价日覆盖不完整；
- 公共批次原始值、MVP 原始值和预处理原始值不一致；
- 预处理键覆盖不一致或评价值非有限；
- 收益不是证券层级、没有 20D 标签或不是获批合成输入；
- 输入在评价过程中发生变化。

## 7. 明确不在本任务范围

本任务不实施：

- 原始值与 MAD 值稳健性比较；
- 子期间稳健性、样本外评价或滚动稳定性；
- FDR、F/R 门禁或准入决策；
- 因子方向翻转或按结果重新选择方向；
- 真实生产数据接入；
- 结果持久化、注册表变更或流水线编排；
- 公共契约、量价入口、R1A/B/C、FIN-MVP-DATA 或 FIN-R2-PREP 修改。

这些能力属于后续任务，其中下一项为 `FIN-MVP-ROBUST`。

## 8. 黄金合成验收

冻结样本包含 2024 年 12 个配置月末、每月 30 只证券和三个因子。前 8 个月
收益排序与因子同向，后 4 个月反向，因此三个因子均得到：

```text
evaluated_dates = 12
total_observations = 360
rank_ic_mean = 1/3
rank_ic_positive_ratio = 2/3
rank_ic_t_stat(hac_max_lag=1) = 0.9370425713316363
long_short_mean = 0.008
monotonicity_spearman = 1
```

验收结果：

```text
FIN-MVP-M-EVAL targeted: 38 passed / 0 failed
R1A/B/C + MVP-DATA + R2-PREP + M-EVAL: 290 passed / 0 failed
wider explicit regression: 898 passed / 4 skipped / 0 failed / 273 warnings
```

最终结论：

```text
FIN-MVP-M-EVAL = ACCEPTED
```
