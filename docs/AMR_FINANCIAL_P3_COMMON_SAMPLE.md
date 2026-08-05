# FIN-P3-COMMON-SAMPLE：共同样本评价

## 1. 任务结论

本模块实现任务规划中的 `FIN-23`：单因子与一个预声明组合候选必须在完全相同的股票、日期和控制变量观测上评价，并同时披露共同样本损失。实现只产生可复现的合成研究证据，不构造 `FIN-24` 的三组预设组合，也不作 `FIN-25` 的信息增益、因子准入或生产批准判断。

黄金合成案例的契约状态为：

```text
gate_status = ready
evaluation_status = completed
same_sample_enforced = true
pit_safe = true
research_assessment = exploratory
production_status = not production ready
admission_status = not_assessed
```

这些状态仅说明共同样本计算契约通过。合成指标不得解释为真实 A 股有效性、真实收益、准入结论或交易指令。

## 2. 前置锚点与冻结政策

运行前必须绑定已验收的 `FIN-P2-GATE`：

```text
task_id = FIN-P2-GATE
status = ACCEPTED
research_integrity_status = complete
production_status = not production ready
output_fingerprint = 9393a240f1bc214fd30bd2815da20ba47e02dedc9c9d319c73fa42c6ada3a1fe
```

本任务冻结以下评价口径：

| 项目 | 冻结值 |
|---|---|
| 收益期 | 20 个交易日 |
| 分组数 | 5 组 |
| 组内权重 | 等权 |
| IC | 横截面 Spearman Rank IC |
| Fama–MacBeth 控制 | 规模、行业 |
| 每期最小共同样本 | 30 |
| 最少有效期数 | 12 |
| 样本政策 | 独立清单与两侧可用观测的交集 |
| 比较政策 | 仅预声明的一对单因子/组合候选 |

自动挑选最佳单因子、动态权重、组合搜索和显著性择优均被禁止。

## 3. 输入契约与 PIT 约束

独立样本清单包含：

```text
evaluation_date, security_id, eligible
```

评价观测包含：

```text
evaluation_date, security_id,
factor_effective_date, control_effective_date, return_start_date,
single_factor_value, combined_factor_value, forward_return,
size_control, industry_code
```

每个证券—日期键必须唯一，观测键必须属于独立清单；清单内容同时由调用方声明哈希和配置期望哈希双重绑定。PIT 关系必须满足：

```text
factor_effective_date <= evaluation_date
control_effective_date <= evaluation_date
return_start_date > evaluation_date
```

任何未来因子、未来控制、收益期错位、重复键、清单漂移、非合成来源或前置锚点漂移都会使任务 `blocked`，且不返回比较结果。

## 4. 共同样本算法

先在独立清单中保留 `eligible = true` 的行，再要求以下字段同时可用：

```text
single_factor_value
combined_factor_value
forward_return
size_control
industry_code
```

每期交集少于 30 个证券时，该期从两侧同时删除；单因子和组合候选随后复用同一个键集合及同一个 `common_sample_fingerprint`。因此不存在一侧使用更多股票或更多月份的路径。

样本披露包括：

- `eligible_sample_size`：独立清单中的合格观测数；
- `single_available_size`：单因子和公共结果/控制可用的观测数；
- `combined_available_size`：组合候选和公共结果/控制可用的观测数；
- `common_sample_size`：通过逐期最小截面规则后的共同观测数；
- `coverage_loss = 1 - common_sample_size / eligible_sample_size`。

若合同合法但有效期少于 12，任务保持 `ready`，评价状态为 `insufficient`，不得把统计材料不足误报为合同错误。

## 5. 输出指标

单因子与组合候选分别在同一共同样本上输出：

- Rank IC 均值、标准差、ICIR 和正 IC 比例；
- 五组等权远期收益、最高组减最低组价差和组序单调性；
- 每期横截面回归的平均 R²，解释变量为因子、规模与行业虚拟变量。

FIN-23 的比较结果固定包含：

```text
common_sample_size
single_factor_metrics
combined_factor_metrics
delta_ic
delta_icir
delta_monotonicity
delta_fm_r2
coverage_loss
```

所有 `delta_*` 均按“组合候选减单因子”计算。它们是描述性差值，不是信息增益判定。

## 6. 黄金合成样本

确定性夹具包含 18 个月、每月 60 只合成证券。独立清单每月排除 2 只，另有可控的单因子缺失、组合缺失、收益缺失、规模缺失和行业缺失。样本瀑布为：

| 项目 | 合成计数 |
|---|---:|
| 清单合格观测 | 1044 |
| 单因子侧可用观测 | 954 |
| 组合侧可用观测 | 936 |
| 最终共同观测 | 900 |
| 有效月份 | 18 |
| 覆盖损失 | 0.13793103448275867 |

黄金输出指纹为：

```text
common_sample_fingerprint = c8b47cc6cde6a2afcdda27a65cde1fbb7e9881c4454ce98b5218f75e4e6c36e0
output_fingerprint = a15859003aadf685aeea6bc9941aa62133bba0cf8e5913a1289735d33d94ce6e
comparison_content_hash = f31447e24a98a9fe1bb38eceb29079cec811481707ac0213ddf36a3ba427fbea
audit_content_hash = 79c0c97bd142450e0730e530e357d93be396ddf4444db337c2660185080273bb
```

夹具刻意使组合候选的合成信号更强，用于验证差值方向和计算路径；这不是实证结果，不能据此声称组合具有真实信息增益。

## 7. 失败闭锁、确定性与不可变性

测试覆盖以下边界：

- 前置门禁、数据来源、字段、清单哈希和键关系；
- 因子/控制 PIT 日期与远期收益对齐；
- 同一股票—日期集合和同一共同样本指纹；
- 单侧缺失、清单排除、单期小截面和全部期数不足；
- 禁止最佳单因子、组合选择、信息增益和准入字段；
- 输入顺序不敏感、重复运行一致、调用方数据防御性复制及运行期突变检测。

输入、共同样本、各侧指标、比较结果、审计结果和最终输出均有独立确定性哈希。

## 8. 明确不在本任务范围内

本任务未执行：

- `FIN-24` 三组预设等权组合的构造与评价；
- `FIN-25` 信息增益结论；
- 多重检验或新的样本外试验；
- 交易成本、停牌/涨跌停、可交易性和容量评价；
- 真实数据接入、正式持久化、因子库写入或生产发布。

因此，本任务完成后合理的下一候选任务是单独授权 `FIN-P3-COMBOS`（对应 `FIN-24`），先冻结三组预设等权组合及其公式版本，再复用本模块的共同样本契约。不得由本任务自动启动。
