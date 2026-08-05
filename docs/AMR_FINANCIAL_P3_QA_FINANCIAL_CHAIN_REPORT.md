# FIN-P3-QA-03：财务链联合回归报告

冻结命令 `python -m pytest -q tests -k financial` 超过单次工具时限，因此按同一 HEAD、Python、控制哈希和依赖哈希，将全部 40 个 `test_amr_financial_*.py` 文件按文件名排序拆为四个互斥批次运行。该拆分不改变任何测试内容；每批实际输出均保留。

| 批次 | 文件范围 | 实际结果 |
| --- | --- | --- |
| 1 | 1–10 | 443 passed，139.12s |
| 2 | 11–20 | 435 passed，245.53s |
| 3 | 21–30 | 140 passed，158.02s |
| 4 | 31–40 | 178 passed，490.38s |
| 合计 | 40 个财务文件 | 1,196 passed，0 failed |

最后一批包含 Research Log config/contract/failure/gate/lineage/results/serialization 及 financial preprocessing/sample/timing。QA-03 不替代后续单因子/批量一致性、组合与信息增益一致性、兼容性、权威 CI、扩展回归或负责人 Gate。
