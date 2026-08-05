# FIN-P3-QA-00：QA 基线与测试命令冻结

冻结环境：HEAD `f957d02f2f2d97606e2ed40d44f985b05f2ac31a`、Python 3.11、控制文件 `.github/workflows/factor-validation.yml` 哈希 `2c775ad97db8dd06fedbb15af5d50a1684e9251e287046f8add6aff060fe5a47`。

| 层级 | 冻结命令 | 使用时点 |
| --- | --- | --- |
| 当前子任务 | `python -m pytest -q <current-test-file>` | 开发与子任务验收 |
| Phase 3 定向 | `python -m pytest -q tests/test_amr_financial_p3_*.py`（由 PowerShell 枚举文件后传入） | QA-02 |
| 财务链 | `python -m pytest -q tests -k financial` | QA-03/当前 Gate 相关回归 |
| 权威 CI 单元测试 | `python -m pytest research_core/factor_lab/ tests/ -v --tb=short` | QA-07 |

QA 结果必须区分本轮实际运行、历史参考、未运行、失败与跳过项；不得用局部通过代替全量 Gate，不得删测、降级断言、填零或修改冻结研究语义。
