# FIN-P3-QA-06：兼容性与受保护语义报告

## 冻结基线

- HEAD：`f957d02f2f2d97606e2ed40d44f985b05f2ac31a`
- 控制文件 SHA-256：`2c775ad97db8dd06fedbb15af5d50a1684e9251e287046f8add6aff060fe5a47`
- 依赖文件 SHA-256：`297268db3d76f10154b40ed2821b5b3f112e403088ae81372043c821957e2e72`
- 环境：源 main 对应 Python 3.11 虚拟环境。

## 兼容性面与受保护语义

| 边界 | 核验内容 | 结论 |
| --- | --- | --- |
| MVP → P2 | FinancialBatch、M 评价和输出接口保持可用 | PASS |
| P2 → P3 | M 评价器源哈希钉住；F/R 上下文未冻结时保持不调用其评价器 | PASS |
| P3 契约 → 输入 | 禁止能力、成员范围、PIT、共同样本及输入不可变约束 fail-closed | PASS |
| P3 → Research Log | 配置、结果与 Gate 的契约/确定性序列化可用 | PASS |
| 受保护结论 | 不产生最佳成员/组合、动态权重、真实信息增益或生产准入 | PASS |

## 实际定向执行

在同一冻结环境下运行 14 个既有测试文件，覆盖 MVP batch/M/output、P2 M/F/R、INFO-GAIN contract/inputs/M-F-R 成员基线及 Research Log contract/results/gate：

```text
401 passed, 0 failed, 273.97s
```

通过结果表示接口和拒绝路径仍兼容；不改变冻结的研究结论：总体证据为 `insufficient_evidence`，准入为 `not_assessed`，生产状态为 `not production ready`。
