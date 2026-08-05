# FIN-P2-INDEP：M/F/R 独立性与增量证据

## 1. 定位

`backend.amr.financial_p2_independence` 是 Phase 2 的附加研究模块。它在
`FIN-P2-M-ENH`、`FIN-P2-F`、`FIN-P2-R` 均已验收的前提下，回答：

1. 财务因子与同类因子的相关程度；
2. 在形成时点行业和规模控制后，因子是否仍保留条件增量；
3. M、F、R 三轨标签、覆盖、指纹、指标和结论是否保持独立。

本模块不选择最佳规格，不执行最终样本外检验或多重检验，也不产生因子准入、
收益承诺、造假/错报认定、无风险认定或交易指令。

## 2. 六文件与前序保护

本任务只写入：

```text
backend/amr/financial_p2_independence.py
tests/test_amr_financial_p2_independence.py
tests/fixtures/synthetic_financial_p2_independence_cases.py
docs/AMR_FINANCIAL_P2_INDEPENDENCE.md
CH6-G0/34-FIN-P2-INDEP实施授权与边界冻结.yaml
CH6-G0/35-FIN-P2-INDEP补丁前基线证据.md
```

M/F/R 前序模块及其测试、夹具、文档均为只读依赖。输入必须提供三个已验收任务的
审计输出指纹；任务ID、证据优先级、状态或指纹不符合冻结契约时阻断运行。

## 3. 输入契约

`FinancialP2IndependenceBatch` 保存不可变副本，主键为：

```text
evaluation_date + code + factor_id
```

因子侧字段：

```text
factor_value
peer_factor_value
industry_code
log_market_cap
control_effective_date
```

三轨标签字段：

```text
M: m_forward_return + m_label_available_at
F: f_residual + f_label_available_at
R: r_label_state + r_label_available_at
```

PIT 硬约束：

```text
control_effective_date <= evaluation_date
evaluation_date < label_available_at <= analysis_as_of
```

控制变量时间穿越、缺失标签元数据、重复主键和未验收前序锚点均阻断。尚未到
`analysis_as_of` 的标签按不可用处理，只改变该轨覆盖，不改变因子样本。

## 4. 方法

### 4.1 行业与规模中性化

每个评价日单独计算：

```text
factor_z ~ intercept + log_market_cap_z + industry_dummies
peer_z   ~ intercept + log_market_cap_z + industry_dummies
```

残差分别形成 `factor_neutral` 和 `peer_neutral`。然后：

```text
factor_neutral ~ intercept + peer_neutral
```

最终残差为 `factor_conditional`。模块同时保存中性化值和条件值的确定性指纹。

### 4.2 同类因子相关性

对每个评价日计算原始因子与同类因子的 Spearman 相关，再报告时间均值。相关性和
条件增量并列展示；高相关本身不自动形成拒绝、准入或最佳规格选择。

### 4.3 M 轨

冻结主期限为 20D。每个评价日比较：

```text
baseline:
forward_return ~ size + industry + peer

augmented:
forward_return ~ size + industry + peer + factor_conditional
```

公共证据包括：

- Fama–MacBeth 增量系数均值；
- 增量系数 Newey–West/HAC t 值；
- 平均增量 R²；
- `factor_conditional` 与基准残差的 Rank IC；
- Rank IC 正向期比例。

普通 t 值不进入任何公共对象或序列化输出。

### 4.4 F 轨

F 轨使用下一季度朴素基准/控制模型的残差作为独立标签，执行与 M 轨同构的条件
截面增量检验。它仍是 `supporting`，不能替代 M 轨 `primary`。

### 4.5 R 轨

二元增量只使用：

```text
positive = hard_positive
negative = confirmed_negative
excluded = soft_positive, unlabeled
```

比较控制基准与加入 `factor_conditional` 后的 PR-AUC、ROC-AUC，并保留确定性负
对照。hard positive 少于30个时为 `not_run`，不能填零。此处结果明确标记为
`descriptive_in_sample_only`；公司隔离的最终样本外检验属于下一任务。

## 5. 样本与轨道独立性

因子样本在标签连接前冻结。删除、置空或推迟某一轨标签：

- 不改变因子样本指纹；
- 不改变行业/规模控制指纹；
- 不改变另外两轨的标签指纹和证据对象；
- 只改变本轨覆盖、状态和标签指纹。

三轨证据优先级固定为：

```text
M = primary
F = supporting
R = risk
```

任何轨道均不能替代另一轨道。

## 6. 状态与边界

```text
calculation status: completed / not_run
gate status: ready / blocked
research conclusion: exploratory
oos_status: not_run
multiple_testing_status: not_run
production status: not production ready
```

样本不足是 `not_run`，不是零效果或正式否决。

## 7. 生产门禁

| 门禁 | 本任务状态 |
|---|---|
| 独立标签或证据复核 | 未满足：仅确定性合成标签 |
| 实时数据契约与授权 | 未满足 |
| PIT版本与历史股票池 | 仅合成契约验证 |
| 扣费后样本外显著性与复现 | 未运行 |

最终生产状态固定为：

```text
not production ready
```

## 8. 下一任务

验收通过后进入 `FIN-P2-OOS-FDR`，负责冻结测试集、一次性样本外验证、原始
p 值和 Benjamini–Hochberg FDR。不得把本任务的样本内增量结果当作该任务的替代。
