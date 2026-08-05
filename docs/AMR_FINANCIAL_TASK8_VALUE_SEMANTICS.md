# FIN-HO-8-A：Task 8 数值语义联合确认

本契约记录负责人已确认的九项共同语义，Schema 为 `FinancialTask8ValueSemantics-v1.0`。

| 项目 | 冻结定义 |
| --- | --- |
| raw | `raw_pit_factor_value`；原始 PIT 值，`effective_date <= evaluation_date`，不填补 |
| evaluation | `evaluation_factor_value`；批准的 MAD 评价值，必须有限，不回写 raw |
| neutralized | `not_available_not_substitutable`；当前不得以回归残差或其他替代值冒充 |
| 频率 | 财务值 `quarterly`；评价上下文仅 `M:20D` |
| 样本 | 键为 `evaluation_date + code + factor_id`；每组合共同样本固定 18 期、900 行 |
| 缺失/异常 | 不填零；单行问题隔离，PIT/样本/契约冲突 fail-closed |
| 陈旧 | 仅要求 `effective_date <= evaluation_date`；未冻结真实数据新鲜度阈值，不作新鲜度声明 |
| 方向 | `original_direction_only_no_posthoc_flip` |
| comparison policy | 同频率、同键、同 PIT、同标签版本、同共同样本、同评价配置 |

序列化采用 canonical JSON 和 SHA-256 内容哈希。任何字段漂移均 fail-closed。

本任务不计算指标、不加载真实数据、不选择因子/组合、不创建 `P05CandidateHandoffPackage`，也不改变 `not production ready` 状态。正式交接包必须等待后续 `FIN-HO-8-B` 的独立授权。
