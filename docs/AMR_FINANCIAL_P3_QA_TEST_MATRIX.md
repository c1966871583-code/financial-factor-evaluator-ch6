# FIN-P3-QA-01：测试清单与责任映射

| 验证层 | 责任对象 | 最小证据 | 不得替代 |
| --- | --- | --- | --- |
| INFO-GAIN 单元/定向 | 01–07、05R | 契约、三轨、覆盖、真实 bad-data、E2E、任务 Gate 测试 | 不得替代财务链或 QA Gate |
| Research Log 单元/定向 | LOG-01–08 | 四区段采集、序列化、组装、Log Gate 测试 | 不得替代上游 INFO-GAIN Gate |
| Phase 3 定向 | `test_amr_financial_p3_*.py` | 已授权子任务的完整定向集合 | 不得替代财务链回归 |
| 财务链回归 | `pytest -q tests -k financial` | 上游财务语义未回归 | 不得替代权威 CI |
| 权威 CI | workflow 的 Layer 1 单元命令 | `research_core/factor_lab/` 与 `tests/` | 不得以历史或局部结果替代 |
| QA-09 负责人 Gate | QA-00–08 证据 | 同 HEAD、同控制哈希、完整报告 | 不得授予生产状态 |

报告责任：执行者必须记录实际命令、HEAD、控制哈希、通过/失败/跳过/未运行项。坏数据场景的正确阻断、隔离或不可评价是通过行为；删除记录、填零或弱化断言是失败。
