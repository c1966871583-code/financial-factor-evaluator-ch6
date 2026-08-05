# AMR财务因子有效性检测：FIN-R1A交易时间治理

> **实现版本**：`FIN-R1A-CONSERVATIVE-v1.0`  
> **状态**：`FIN-R1A = COMPLETE`  
> **适用HEAD**：`f957d02f2f2d97606e2ed40d44f985b05f2ac31a`

## 1. 范围

FIN-R1A只治理财务信息何时可以进入评价截面：

```text
公告日期或可信公告时间
→ 市场时段分类
→ 公告后首个实际交易日
→ effective_date
→ timing_audit
```

本阶段不实现真实Provider、来源血缘、独立样本、财务因子公式、统计评价、Supabase
写入或准入决定。

## 2. 冻结时间策略

时区固定为`Asia/Shanghai`。CH6-G0没有批准“可信盘前公告当日生效”，所以所有
公告均采用公告日期之后的首个实际交易日：

| 场景 | `effective_date` |
|---|---|
| 交易日盘前 | 下一实际交易日 |
| 交易日盘中 | 下一实际交易日 |
| 交易日盘后 | 下一实际交易日 |
| 只有公告日期 | 公告日之后首个交易日 |
| 周末或节假日 | 公告日之后首个交易日 |
| 日历没有后续交易日 | `blocked` |
| 时间戳、时区不可核验 | `blocked` |

公告时间戳存在时必须显式声明`announcement_timezone=Asia/Shanghai`。带时区偏移的
时间戳必须与上海时区一致。

## 3. 实现接口

`backend.amr.financial_timing`提供：

```python
policy = FinancialTimingPolicy(
    trading_days=("2024-01-05", "2024-01-08", "2024-01-09"),
    trading_calendar_version="synthetic-calendar-v1",
)

audit = evaluate_financial_timing(
    FinancialTimingObservation(
        code="SYN001",
        publish_date="2024-01-05",
        announcement_timestamp="2024-01-05T16:00:00+08:00",
        announcement_timezone="Asia/Shanghai",
        statement_version="original",
        source_record_id="synthetic-001",
    ),
    policy,
)
```

审计字段包括：

```text
timing_policy_version
trading_calendar_version
timezone
publish_date
announcement_timestamp
timestamp_quality
market_session_classification
derived_effective_date
provided_effective_date
effective_date_validation_status
decision_reason_code
return_start_validation_status
overall_status
errors
```

`backend.amr.financial_source_adapter`只接受已经计算出的`factor_value`，全量记录通过
后才构造公共`FinancialBatch`。公共输出字段保持不变：

```text
code
report_period
publish_date
effective_date
factor_value
```

输入顺序不影响规范化输出、输入指纹、审计指纹或输出指纹。

## 4. 失败闭锁

以下情况不产生部分`FinancialBatch`：

- 缺少交易日历或日历没有公告后的交易日；
- 公告时间戳、时区或日期关系非法；
- 提供的生效日早于公告或与冻结策略不一致；
- 收益起点早于生效日；
- 同一来源记录ID重复；
- 多条记录映射到同一公共业务键；
- 同一报表版本重复；
- 动态公式或可执行代码字段非空；
- `synthetic_test_only`不是`true`；
- 公共`FinancialBatch`契约校验失败。

修订公告按自身公告时间重新计算。原始记录和修订记录映射到不同生效日时，两条历史
都会保留；若后续版本未形成严格更晚的生效日，则以
`REVISION_EFFECTIVE_DATE_INVALID`阻断，不静默覆盖。

## 5. 测试

定向测试：

```powershell
python -m pytest tests/test_amr_financial_timing.py -q
```

权威回归：

```powershell
python -m pytest research_core/factor_lab/ tests/ -v --tb=short
```

测试数据全部来自：

```text
tests/fixtures/synthetic_financial_timing_cases.py
synthetic_test_only=true
```

2026-07-30验收结果：

```text
定向测试:
43 passed

权威回归:
648 collected
644 passed
4 skipped
0 failed

协作指南宽口径回归:
655 collected
651 passed
4 skipped
0 failed
```

三组测试均保留原有`273 warnings`，来源为既有NumPy相关性计算和
`evaluation_alignment.py`的DataFrame索引警告；FIN-R1A没有新增失败或跳过。

## 6. 未授权边界

- 不修改源main工作树；
- 不创建或切换分支；
- 不执行commit、push、pull、merge或主仓回迁；
- 不访问生产数据；
- 不连接或写入Supabase；
- 不执行动态公式；
- 不把时间治理通过解释为因子有效或可准入。

## 7. FIN-R1A验收结论

| 验收项 | 结果 | 证据 |
|---|---|---|
| 盘前、盘中、盘后、周末、长假和仅日期场景 | `PASS` | 合成参数化测试 |
| 缺失日历、非法时间戳和未核验时区阻断 | `PASS` | 稳定原因码断言 |
| 提供生效日早于公告或与策略不一致时阻断 | `PASS` | 生效日失败测试 |
| 收益起点不早于生效日 | `PASS` | 前置阻断和同日通过测试 |
| 修订不提前且不覆盖历史 | `PASS` | 双版本保留及冲突闭锁测试 |
| 输入不被原地修改 | `PASS` | 深拷贝前后比较 |
| 输入乱序不改变输出和指纹 | `PASS` | 正序/逆序一致性测试 |
| 公共`FinancialBatch`字段不变 | `PASS` | 精确列断言 |
| 量价路径无回归 | `PASS` | 权威全量回归 |
| 无生产数据、网络、Supabase或动态执行 | `PASS` | 合成标志与AST安全测试 |
| 文件边界 | `PASS` | 5个白名单文件，0个保护文件改动 |

最终判断：

```text
FIN-R1A = COMPLETE
FIN-R1B = NOT_STARTED / REQUIRES_NEW_FILE_BOUNDARY_AUTHORIZATION
```
