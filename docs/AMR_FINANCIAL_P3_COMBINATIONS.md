# FIN-P3-COMBOS：三组预设等权组合

## 1. 任务结论

本模块实现任务规划中的 `FIN-24`，只构造价值质量、高质量成长和盈利真实性三组
预设组合，并通过已验收的 `FIN-23` 共同样本比较器进行合成评价。黄金案例状态为：

```text
gate_status = ready
experiment_count = 3
fin24_combinations_constructed = true
exact_formulas_frozen = true
equal_weight_only = true
pit_safe = true
return_label_independent_construction = true
research_assessment = exploratory
production_status = not production ready
admission_status = not_assessed
```

这些状态只说明公式、PIT、缺失处理、共同样本和序列化契约通过。合成指标不得解释
为真实 A 股信息增益、真实收益、最佳组合、因子准入或生产批准。

## 2. 前置锚点

运行前必须绑定已验收的 `FIN-P3-COMMON-SAMPLE`：

```text
task_id = FIN-P3-COMMON-SAMPLE
status = ACCEPTED
same_sample_enforced = true
research_assessment = exploratory
production_status = not production ready
output_fingerprint = a15859003aadf685aeea6bc9941aa62133bba0cf8e5913a1289735d33d94ce6e
```

模块内部只把构造完成的预声明因子对交给 FIN-23 比较器。FIN-23 仍不承担组合
构造，因此其 `fin24_combination_construction_allowed` 约束没有被绕过或修改。

## 3. 冻结公式和参照

### 3.1 价值质量组合

```text
VQ = [z(BP) + z(EBIT_EV) + z(ROE) + z(OCF_NP)] / 4
formula_version = FIN-24-VQ-v1.0
reference_factor = BP
```

### 3.2 高质量成长组合

```text
QG = [z(SALES_GROWTH) + z(PROFIT_GROWTH) + z(ROE) + z(OCF_NP)] / 4
formula_version = FIN-24-QG-v1.0
reference_factor = ROE
```

### 3.3 盈利真实性组合

```text
CASHQ = [z(ROA) + z(OCF_SALES) - z(ACCRUALS)] / 3
formula_version = FIN-24-CASHQ-v1.0
reference_factor = OCF_NP
```

`ACCRUALS=(NP_TTM−OCF_TTM)/平均总资产` 的方向为负：应计越低，盈利真实性
组合分越高。三组都只允许等绝对权重主方案，不接受动态 IC/IR 权重、优化权重、
组合搜索或运行后改权。

参照 `BP / ROE / OCF_NP` 对应已经完成基础检测的三个 MVP 因子，且在运行前冻结。
参照不是从本次结果中选择的“最佳单因子”；最佳单因子及信息增益属于 FIN-25。

## 4. 输入与 PIT 契约

独立样本清单包含：

```text
evaluation_date, security_id, eligible
```

观测表包含九个因子值及各自生效日：

```text
BP, EBIT_EV, ROE, OCF_NP,
SALES_GROWTH, PROFIT_GROWTH,
ROA, OCF_SALES, ACCRUALS
```

同时包含控制项生效日、未来收益起始日、未来收益、规模控制和行业代码。每个非空
因子值均绑定自己的 `*_effective_date`，并满足：

```text
factor_effective_date <= evaluation_date
control_effective_date <= evaluation_date
return_start_date > evaluation_date
```

清单和观测键必须唯一，观测不得位于清单之外；清单由调用方声明哈希和配置期望
哈希双重绑定。前置锚点、来源、字段、键、哈希、日期或禁止字段漂移时 fail closed。

## 5. 标签独立的逐期标准化

每个因子在每个 `evaluation_date` 上使用 `eligible=true` 的独立清单截面计算：

```text
z(x) = [x - mean(x)] / std_population(x)
ddof = 0
minimum_cross_section = 30
```

不同因子分别在自身可用观测上标准化，不填补缺失值。小于 30 条有限观测或标准差
为零的因子—日期不生成 z 值。组合仅在全部必需分量 z 值可用时生成。

标准化和组合构造不读取未来收益、规模控制或行业控制。改变、删除或扰动未来收益
只能改变后续评价及配对覆盖，不得改变 `construction_fingerprint`。这条约束避免
未来标签可用性反向决定因子值或评价股票池。

## 6. 共同样本评价

每组构造完成后，参照因子和组合因子共同进入 FIN-23：

- 20 日未来收益；
- 5 组等权分组；
- Spearman Rank IC；
- 规模和行业控制的逐期横截面 R²；
- 每期最少 30 条共同观测、至少 12 个有效期；
- 同一股票—日期键集合及同一共同样本指纹。

输出沿用 FIN-23 的 `common_sample_size`、两侧指标、四项描述性差值和覆盖损失。
各组合可以因分量缺失形成不同的共同样本指纹，但同一实验内部两侧必须完全相同。

## 7. 黄金合成案例

确定性夹具包含 18 个月、每月 60 只证券，独立清单每月 58 只合格证券。分量、
收益和控制缺失均为预声明模式：

| 组合 | 构造可用观测 | 最终共同观测 | 有效期 | 覆盖损失 |
|---|---:|---:|---:|---:|
| VQ | 954 | 900 | 18 | 0.13793103448275867 |
| QG | 954 | 900 | 18 | 0.13793103448275867 |
| CASHQ | 972 | 900 | 18 | 0.13793103448275867 |

黄金指纹为：

```text
manifest_fingerprint = ef2295ef81dbc6957a0eab9cbea08250c2fa9a0b84d3651f333e366dcd349fdd
input_fingerprint = 05e5e68b8ad26446ce6ceb5c4a67bf278ca05a1996adef07f15850ae809131c7
output_fingerprint = 7c8686b44f3842f159b3fbbc45aa9908f3bf81acd5ebec381f8ac4f5c1933fa2
audit_content_hash = 7e80903dbcaeb8b90141dac20dbf8fed75807a5c8bc254f27c95bd6ac3ff210d

VQ construction_fingerprint = cc573e6eb78c9037af8251cd6ef3255beefc8f4ba7e531c060a3a18f4e84490c
QG construction_fingerprint = 8ab7d6c14392f1cec4bd2f15128d41d047333835f649666c8e576f7dbef4941e
CASHQ construction_fingerprint = 2bcae6b369b8014021c7f07a10d3bc63a6ed16902280c5e4c4521d4fb0b44b75
```

夹具刻意使组合的部分合成指标优于固定参照，也保留了 QG 和 CASHQ 的合成 ICIR
差值为负，用于验证“不能只看单一改善项”。所有差值均是测试数据上的描述性结果，
不得作 FIN-25 判断。

## 8. 失败闭锁与确定性

测试覆盖：

- 三份公式、版本、参照和权重的精确冻结；
- 应计项负方向、分量覆盖和共同样本会计；
- 标签/控制缺失不改变构造、非相关分量缺失不影响其他组合；
- 小截面和零方差产生 `insufficient`，不伪装为合同错误；
- 前置锚点、合成来源、键、清单哈希、数值、日期和 PIT；
- 禁止选择、优化、动态权重、信息增益和准入字段；
- 输入顺序不敏感、重复运行一致、防御性复制及运行期突变检测。

输入、公式、构造、FIN-23 比较、实验、总输出和审计均具有确定性 SHA-256 哈希。

## 9. 明确不在本任务范围内

本任务未执行：

- FIN-25 最佳单因子识别和信息增益判定；
- 新的样本外试验或多重检验；
- 真实数据、成本、停牌/涨跌停、容量或可交易性评价；
- 正式持久化、因子库写入、准入、生产发布或交易执行。

因此，下一候选任务是单独授权 `FIN-P3-INFO-GAIN`（对应 FIN-25）。该任务必须
预先冻结最佳单因子的确定方式、核心指标不恶化口径、时期集中度、样本外方向和
覆盖损失解释规则；不得由本任务自动启动。
