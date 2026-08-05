# FIN-P3-QA-04：财务测试单文件/批量一致性报告

## 冻结基线

- HEAD：`f957d02f2f2d97606e2ed40d44f985b05f2ac31a`
- 控制文件 `.github/workflows/factor-validation.yml` SHA-256：`2c775ad97db8dd06fedbb15af5d50a1684e9251e287046f8add6aff060fe5a47`
- 依赖文件 `requirements-factor-lab.txt` SHA-256：`297268db3d76f10154b40ed2821b5b3f112e403088ae81372043c821957e2e72`
- Python：源 main 对应虚拟环境的 Python 3.11。

## 方法

对 `tests/test_amr_financial_*.py` 按文件名排序的 40 个文件逐一执行
`python -m pytest -q <单个文件>`。不使用 `--ignore`、`-k` 过滤、重试、跳过或测试修改。
执行次序与 FIN-P3-QA-03 的四个十文件批次一致；每组单文件通过数与其已验收的批量通过数逐一比较。

## 实际结果

| 排序范围 | 文件数 | 单文件逐项执行 | QA-03 批量基线 | 一致性 |
| --- | ---: | ---: | ---: | --- |
| 1–10 | 10 | 443 passed | 443 passed | PASS |
| 11–20 | 10 | 435 passed | 435 passed | PASS |
| 21–30 | 10 | 140 passed | 140 passed | PASS |
| 31–35 | 5 | 21 passed | — | PASS（第四组子集） |
| 36–40 | 5 | 157 passed | — | PASS（第四组子集） |
| 31–40 合计 | 10 | 178 passed | 178 passed | PASS |
| 全部 | 40 | 1,196 passed，0 failed | 1,196 passed，0 failed | PASS |

单文件运行未发现失败、跳过、测试污染或单文件/批量计数差异。QA-04 只验证回归执行一致性；不重算任何 M/F/R 评价、共同样本成员基线或组合信息增益，也不作生产准入结论。
