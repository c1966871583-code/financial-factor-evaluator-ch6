# FIN-P3-QA-08：扩展回归与平台质量报告

## 冻结基线

- HEAD：`f957d02f2f2d97606e2ed40d44f985b05f2ac31a`
- 控制文件 SHA-256：`2c775ad97db8dd06fedbb15af5d50a1684e9251e287046f8add6aff060fe5a47`
- 依赖文件 SHA-256：`297268db3d76f10154b40ed2821b5b3f112e403088ae81372043c821957e2e72`
- 环境：源 main 对应 Python 3.11 虚拟环境。

## 扩展回归

执行冻结命令：

```text
python -m pytest -q research_core/factor_lab/ research_core/backtest_adapter/ research_core/factor_library/ tests/
```

实际结果：`1805 passed, 4 skipped, 273 warnings in 985.90s (0:16:25)`。

## 平台质量检查

| 检查项 | 结果 | 说明 |
| --- | --- | --- |
| 扩展回归 | PASS | 1,805 通过，零失败 |
| 跳过项 | REVIEWED | 4 项为 Manual CSV 的真实样本用例；未被填零或改写为通过 |
| 警告 | BASELINE-PRESERVED | 273 项，与 QA-07R 权威 CI 相同；包括 NumPy 常数序列相关运行时警告和既有 pandas 重索引警告 |
| Python 编译 | PASS | `compileall -q backend/amr research_core` 零退出码 |
| 尾随空白 | PASS | 本轮实现、测试和报告文件未发现尾随空白 |
| 受保护文件 | PASS | CI 控制文件、依赖文件与源 main 未漂移 |

本报告是工程质量与回归证据，不重算金融研究指标，也不改变 `insufficient_evidence`、`not_assessed`、`not production ready` 的受保护研究语义。
