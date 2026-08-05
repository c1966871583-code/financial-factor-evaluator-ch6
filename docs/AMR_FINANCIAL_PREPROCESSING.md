# FIN-R2-PREP 财务预处理与审计契约

状态：`ACCEPTED`  
Schema：`FinancialPreprocessing-v1.0`  
审计 Schema：`FinancialPreprocessingAudit-v1.0`  
哈希契约：`FIN-R2-PREP-HASH-v1.0`

## 1. 定位

FIN-R2-PREP只为已批准的三个MVP财务因子准备受控公式输入和研究预处理值：

```text
ROE
BP
OCF_NP
```

模块不修改公共`FinancialBatch`，不修改FIN-R1A/B/C或FIN-MVP-DATA。输出通过显式
Path B记录转换进入FIN-MVP-DATA。

## 2. 冻结输入

每条输入代表一个评价日、证券和报告期的PIT安全财务截面，必须提供：

```text
evaluation_date
code
report_period
publish_date
effective_date
parent_net_profit_ytd
operating_cash_flow_ytd
parent_equity
market_cap
prior_fy_parent_net_profit
prior_fy_operating_cash_flow
prior_year_same_period_parent_net_profit_ytd
prior_year_same_period_operating_cash_flow_ytd
prior_year_same_period_parent_equity
source_snapshot_fingerprint
input_record_references
synthetic_test_only=true
```

年报不要求四个中期TTM历史流量字段，但仍要求上年同期归母权益以构造平均权益。
`market_cap`必须由上游作为评价日PIT输入提供；本模块不从价格、股本或未来数据推导。

日期必须满足：

```text
report_period <= publish_date <= effective_date <= evaluation_date
```

报告期仅允许`03-31`、`06-30`、`09-30`、`12-31`。

## 3. TTM与平均权益

非年报累计口径：

```text
TTM = 当前期累计 + 上一完整财年 - 上年同期累计
```

年报口径：

```text
TTM = 当前年报累计
```

平均归母权益：

```text
average_parent_equity =
    (current_parent_equity + prior_year_same_period_parent_equity) / 2
```

最终生成的固定公式输入：

| 因子 | 分子 | 分母 |
|---|---|---|
| `ROE` | `parent_net_profit_ttm` | `average_parent_equity` |
| `BP` | `parent_equity` | `market_cap` |
| `OCF_NP` | `operating_cash_flow_ttm` | `parent_net_profit_ttm` |

任何非有限输入、缺失历史或非正分母都会阻断完整三因子包。不插值、不填充、不自动
改变公式。负分子可以保留，因为它不是分母异常。

## 4. MAD主预处理

MAD只作用于`evaluation_factor_value`，不覆盖`raw_pit_factor_value`：

```text
M = median(x)
MAD = median(abs(x - M))
scaled_MAD = 1.4826 * MAD
lower = M - 3 * scaled_MAD
upper = M + 3 * scaled_MAD
```

冻结规则：

- 截面为`evaluation_date × factor_id`；
- 阈值`k=3`，尺度系数`1.4826`；
- `minimum_cross_section_size`必须由调用方显式给出并进入配置指纹；
- 截面不足时返回原值并记录`INSUFFICIENT_MAD_CROSS_SECTION`；
- `MAD=0`时返回原值，不回退到分位数缩尾，并记录`MAD_ZERO_NO_WINSOR`；
- 保存中位数、原始MAD、尺度MAD、上下界、截断数及输入输出指纹；
- 不产生`neutralized_factor_value`，中性化方法和控制变量尚未获批。

## 5. 数值语义

```text
raw_pit_factor_value
```

由受控固定公式直接得到，进入FIN-MVP-DATA Path B和公共`FinancialBatch`。

```text
evaluation_factor_value
```

由本任务的MAD规则得到，留在财务预处理sidecar中，供后续M轨道评价显式选择。

```text
neutralized_factor_value = null
```

FIN-R2-PREP不实施中性化。

`dedup_comparison_value`未获授权，不映射到任何上述值。

## 6. 确定性与审计

唯一输入键：

```text
evaluation_date + code + report_period
```

准备结果键：

```text
evaluation_date + code + factor_id
```

排序顺序：

```text
evaluation_date
factor_id按ROE、BP、OCF_NP
code
report_period
effective_date
```

审计至少保存：

- 配置指纹；
- 输入指纹；
- 准备结果指纹；
- MAD审计指纹；
- 每条结果的准备输入哈希和内容哈希；
- 输入数、成功数、因子观测数和阻断数；
- 结构化错误与警告。

任何输入错误均采用fail-closed策略，结果不输出部分因子。

## 7. Path B集成

`FinancialPreprocessingResult.to_mvp_path_b_records()`返回新的字典，不暴露或修改内部
对象。它只传递原始固定公式输入，不把MAD值伪装成`factor_value`。

若FIN-R1B对三个因子使用不同的已验收快照，可通过
`source_snapshot_fingerprints`显式绑定。映射必须完整覆盖`ROE`、`BP`、`OCF_NP`并
通过SHA-256格式校验；模块不会隐式选择或猜测血缘快照。

## 8. 标签隔离与禁止事项

`future_labels`参数只作为隔离探针存在，模块不会迭代、复制、哈希、序列化或读取它。

本任务禁止：

- 真实生产数据接入；
- 动态公式；
- 中性化；
- IC、收益或分组评价；
- 因子方向翻转；
- P0-5数值去重映射；
- 修改公共契约、R1A/B/C、FIN-MVP-DATA、Mock、CI或依赖；
- Git写操作及源main迁移。

## 9. 验收记录

| 入口 | 结果 |
|---|---|
| FIN-R2-PREP定向测试 | `55 passed / 0 failed` |
| R1A/B/C + MVP-DATA + R2-PREP联合测试 | `252 passed / 0 failed` |
| 权威回归 | `853 passed / 4 skipped / 0 failed / 273 warnings` |
| 宽口径回归 | `860 passed / 4 skipped / 0 failed / 273 warnings` |

新增55项测试未增加既有警告数。

固定MAD合成截面证据：

```text
gate=ready
input_fingerprint=93a803c3e15276789e96140dcdf90001ff1a9091ca2ad604a821d84dae2c2ab9
output_fingerprint=6d5f47f37e28ea2e2113c61e5aecd9bdb4c632fc2465560cdb69812be2fcfd36
mad_audit_fingerprint=43b7d392d9500b384428406d021e672caef787e8c8ef5b9e817582f89e47a5b4
audit_hash=9d9ca45fcfc04513a15463d64e1adb3d1e1f3b8b0366f2de1c3ecd55d8fcbbf7
ROE_outlier_raw=1.0
ROE_outlier_evaluation=0.16447800000000004
```

最终结论：

```text
FIN-R2-PREP = ACCEPTED
```
