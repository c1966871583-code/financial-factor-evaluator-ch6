# FIN-P3-QA-05：组合与信息增益一致性报告

## 冻结基线

- HEAD：`f957d02f2f2d97606e2ed40d44f985b05f2ac31a`
- 控制文件 SHA-256：`2c775ad97db8dd06fedbb15af5d50a1684e9251e287046f8add6aff060fe5a47`
- 依赖文件 SHA-256：`297268db3d76f10154b40ed2821b5b3f112e403088ae81372043c821957e2e72`
- 环境：源 main 对应 Python 3.11 虚拟环境。

## 核验范围

本轮只验证冻结的三组合与 INFO-GAIN 消费链的契约一致性，不修改实现或测试，也不重算真实研究结论。

| 对象 | 冻结关系 | 核验结论 |
| --- | --- | --- |
| VQ | `BP, EBIT_EV, ROE, OCF_NP`，等权、正向；参考 `BP` | PASS |
| QG | `SALES_GROWTH, PROFIT_GROWTH, ROE, OCF_NP`，等权、正向；参考 `ROE` | PASS |
| CASHQ | `ROA, OCF_SALES` 正向、`ACCRUALS` 负向，等权；参考 `OCF_NP` | PASS |
| 共同样本 | 每组合 18 期、900 行；两侧使用相同共同样本指纹 | PASS |
| INFO-GAIN 输入 | 三组合、冻结成员方向、成员观测、PIT 日期和 M:20D 上下文绑定 | PASS |
| M/F/R 语义 | M 为成对指标可用；F/R 因上下文未冻结而明确不可评价 | PASS |
| 覆盖、汇总、E2E、任务 Gate | 覆盖代价保留；确定性输出；不汇总为生产准入结论 | PASS |

## 实际定向执行

以同一命令运行以下 12 个既有测试文件：组合、INFO-GAIN 输入、M/F/R 成员基线、M/F/R 比较、覆盖、汇总、端到端和任务 Gate。

```text
289 passed, 0 failed, 222.37s
```

端到端黄金快照保持：summary `ready`，bad-data Gate `ready`；轨道状态为 `pairwise_metrics_available`、`not_evaluable_context_not_frozen`、`not_evaluable_context_not_frozen`。任务 Gate 仍要求总体证据 `insufficient_evidence`、准入 `not_assessed`、生产状态 `not production ready`。

本结果证明冻结组合定义与 INFO-GAIN 消费链没有契约、成员、方向、共同样本、状态或序列化漂移；它不代表真实信息增益、最优组合、投资建议或生产批准。
