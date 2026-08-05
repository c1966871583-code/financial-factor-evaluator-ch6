# FIN-P2-M-ENH：M轨道研究增强

状态：`IMPLEMENTED`

模块：

```text
backend/amr/financial_p2_m_enhancement.py
```

## 1. 定位

FIN-P2-M-ENH 在已接受的 Phase 1 M 轨之上增加研究稳健性证据，同时保持：

```text
validation_track = M
evidence_priority = primary
primary_horizon = 20
factor_direction_source = original_direction_only
```

本模块是加法式适配层，不修改 `financial_mvp_m_evaluation.py`、公共量价评价器、
`FinancialEvaluationRun` 或 Phase 1 黄金快照。

## 2. 冻结研究矩阵

| 维度 | 冻结值 |
|---|---|
| 因子 | `ROE / BP / OCF_NP` |
| 评价日 | 月末配置日 |
| 期限 | `5D / 20D / 60D` |
| 主期限 | `20D` |
| 扩展股票池 | 每期同一冻结股票池，至少60只证券 |
| 最小截面 | 30 |
| 最少评价期 | 12 |
| 滚动窗口 | 6个月 |
| 分组 | 5组、等权 |
| 方向 | 只计算原始方向 |

5D 和 60D 是预注册稳健性期限，不能根据结果自动替代 20D。输出显式保存
`best_horizon_selection_status = not_run`。

## 3. 输入与 Phase 1 锚定

入口：

```python
evaluate_financial_p2_m_enhancement(
    mvp_batch_result,
    preprocessing_result,
    forward_returns,
    configuration=configuration,
)
```

输入仍为：

```text
MVPFinancialBatchResult
FinancialPreprocessingResult
ForwardReturnBatch
```

`ForwardReturnBatch` 必须同时包含 5、20、60 三个期限，保持
`security_level` 和 `synthetic_test_only=true`。入口先调用已接受的
`evaluate_financial_mvp_m` 复核 20D；增强层计算出的 20D 公共结果必须逐字段等于
Phase 1 结果，否则以 `PRIMARY_HORIZON_MISMATCH` 阻断。

## 4. 扩展股票池

每个因子、每个评价日必须具有完全一致的证券成员集合：

```text
factor_id × evaluation_date
→ frozen code set
```

成员漂移以 `UNIVERSE_MEMBERSHIP_DRIFT` 阻断；少于60只证券以
`EXPANDED_UNIVERSE_TOO_SMALL` 阻断。股票池指纹绑定：

```text
universe_reference
universe_version
sorted security codes
```

标签缺失不会反向改变股票池或因子样本，只降低对应期限的
`label_available_count` 和 `paired_coverage_rate`。

## 5. 多期限证据

每个因子、每个期限输出 `FinancialP2MHorizonEvidence`：

```text
universe_count
configured_date_count
factor_sample_count
label_available_count
paired_coverage_rate
SecurityLevelEvaluationResult
factor_sample_fingerprint
label_fingerprint
content_hash
```

公共结果继续提供 Rank IC、Pearson IC、HAC t 统计量、等权分组收益、
`long_short_mean` 和单调性。不存在第二套公共统计字段。

## 6. 滚动稳定性

对每个因子、每个期限生成固定6个月滚动窗口：

```text
window_start / window_end
effective_periods
paired_observations
paired_coverage_rate
rank_ic_mean
rank_ic_positive_ratio
direction
status
```

输出另外记录：

```text
horizon_direction_consistency
primary_rolling_direction_consistency
```

这些字段只描述方向稳定性，不把统计格子变成准入结论，也不自动挑选最佳窗口。

## 7. 冻结合成验收夹具

```text
18个月末
60只证券
3个因子
5D / 20D / 60D
1,080条因子样本 / 因子
3,240条收益标签
13个滚动窗口 / 因子 / 期限
```

冻结主统计量：

| 期限 | Rank IC mean | Long-short mean |
|---:|---:|---:|
| 5D | `0.5555555555555556` | `0.026666666666666665` |
| 20D | `0.3333333333333333` | `0.016` |
| 60D | `0.1111111111111111` | `0.005333333333333333` |

这些数值仅用于验证路由、计算和衰减展示，不构成真实市场研究结论。

## 8. 明确未实施

以下字段保持 `not_run`：

```text
neutralization_status
fama_macbeth_status
oos_status
multiple_testing_status
best_horizon_selection_status
```

本任务不实现 F/R 轨道、行业规模中性化、Fama-MacBeth、OOS、FDR、真实数据
访问、生产持久化、因子准入或任务8交接。

## 9. 测试

```powershell
python -m pytest -q tests/test_amr_financial_p2_m_enhancement.py
```

当前结果：

```text
31 passed
0 failed
```
