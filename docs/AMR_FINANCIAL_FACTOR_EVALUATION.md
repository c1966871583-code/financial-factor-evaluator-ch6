# AMR财务因子有效性检测

轨道 M 的冻结检验族、独立形成日历、逐行血缘和多重检验实现见
[`AMR_FINANCIAL_TRACK_M_START.md`](AMR_FINANCIAL_TRACK_M_START.md)。

## 1. 模块定位

本模块在冻结的`EvaluationInputBundle`、`FinancialBatch`和
`ForwardReturnBatch`之上补充财务因子专用PIT对齐与有效性检测。

模块只输出有效性证据，不直接作因子准入判断，也不执行用户提交的动态公式。

## 2. 接入入口

统一调度：

```python
from backend.amr.evaluation_pipeline import evaluate_bundle

run = evaluate_bundle(bundle, horizon="20")
```

调度规则：

- `price_volume`：调用原有量价对齐和评估；
- `financial`：调用财务PIT对齐，再复用公共统计和统一结果结构；
- `macro`：当前返回`not_applicable`。

## 3. 财务时点规则

### 3.1 冻结输入

`FinancialBatch`必须包含：

```text
code
report_period
publish_date
effective_date
factor_value
```

模块不修改冻结契约，不重新计算或执行因子公式。

### 3.2 评价日

首版使用月末截面。对于未来收益数据中每个自然月，选择最后一个可用日期。
这样可避免将同一份低频财务数据每日重复计入IC序列。

### 3.3 PIT选择

对于每个评价日和证券：

1. 排除`effective_date > evaluation_date`的记录；
2. 同一报告期有多个版本时，选择当时已经生效的最新版本；
3. 在可用报告期中选择最新报告期；
4. 不使用未来版本回填历史；
5. 每个证券独立选择，允许异步披露。

### 3.4 陈旧数据

```text
data_age_days = evaluation_date - report_period
```

超过`max_data_age_days`的记录不进入有效样本，并输出
`STALE_FINANCIAL_DATA_EXCLUDED`。

### 3.5 审计信息

`FinancialTimingAudit`记录：

- 原始财务行数；
- 实际月末评价日；
- 选中快照行数；
- 被排除的未来记录数；
- 被排除的陈旧记录数；
- 被折叠的旧修订行数；
- 被淘汰的旧报告期行数；
- 缺失因子值数量；
- 时点问题代码。

## 4. 首版指标

首版复用公共结果`SecurityLevelEvaluationResult`：

- Pearson IC；
- Rank IC；
- IC均值、标准差、ICIR；
- HAC调整t值；
- IC正向比例；
- IC滚动稳定性；
- 分位数组收益；
- High-Low收益；
- 分组单调性；
- 有效日期、排除日期和样本数；
- 明确的状态和问题代码。

财务因子进入公共统计前，按月度截面执行MAD缩尾，同时保留
`raw_factor_value`用于审计。

## 5. 方法选择依据

| 方法 | 选择依据 |
|---|---|
| 月末评价 | 避免低频财务值日度重复 |
| Rank IC | 适应厚尾和非线性尺度 |
| Pearson IC | 诊断线性关系与极端值影响 |
| HAC t值 | 修正IC时间序列自相关 |
| 分组收益 | 补充经济量级和单调性 |
| 覆盖率 | 反映异步披露、缺失和陈旧排除 |
| MAD | 降低财务比率极端值影响 |

## 6. 暂缓方法

| 方法 | 暂缓原因 |
|---|---|
| 行业/市值中性化 | 冻结输入当前不包含行业及市值控制序列 |
| Fama-MacBeth | 同样缺少统一控制变量契约 |
| 公告事件研究 | 异步事件与重叠窗口复杂，首版采用月末截面 |
| 动态因子权重 | 属于组合构建，不属于有效性检测 |
| 复杂非线性模型 | 首版优先可解释性和确定性 |

## 7. 状态语义

- 无未来收益：`not_run`；
- 类型不适用：`not_applicable`；
- 无PIT快照、无匹配、常数因子或样本不足：Gate为`blocked`；
- 陈旧数据、低覆盖、日期不足或截面偏小：Gate为`warning`；
- 有部分日期不可评估：结果为`partial`；
- 全部有效日期完成：结果为`completed`。

这些状态仅描述检测是否可执行及证据质量，不等于准入结论。

## 8. 测试

定向测试：

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests/test_amr_financial_evaluation.py `
  tests/test_amr_financial_track_m.py -q
```

项目主测试目录回归：

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```

所有测试均使用明确标记为`synthetic_test_only`的合成数据，不连接生产数据。
2026-07-29实测结果为`24 passed`；主测试目录回归为
`611 passed, 4 skipped`。

## 9. 已知限制

- 月末由未来收益数据中的最后可用日期决定；
- 财务覆盖率以所选月末未来收益股票池为分母；
- 陈旧阈值需要结合业务口径进一步校准；
- 当前不处理盘中公告时间；
- 当前不做行业和市值中性化；
- 当前不构造财务因子，只评估冻结契约中的`factor_value`；
- 全仓无约束pytest存在项目既有收集问题，应以`tests/`为主回归入口。

## 10. 已冻结的 Financial Timing Contract

本节由 Operator 在 `FIN-RQDATA-CONTRACT-OPERATOR-FREEZE-27` 中批准，状态为
`FROZEN`。`FinancialTimingPolicy` 使用带版本与哈希的 RQData 中国市场交易日历，
并记录 provider、scope、起止日期、snapshot/version 与 SHA256。

- `effective_date` 是严格晚于 `publish_date` 的第一个市场交易日；公告日即使是交易日也不可同日生效。
- 最终不变量是 `report_period <= publish_date < effective_date`。
- 缺失 `publish_date` 的记录以 `MISSING_PUBLISH_DATE` 进入 audit，不得进入 PIT-valid batch，且不得用固定滞后代理。
- 修订、重述与更正公告各自作为新的信息事件，分别保留 `publish_date` 并计算自己的 `effective_date`；历史评价日只能选择当时已生效的最新版本。
- 日历无法覆盖公告日或下一交易日时返回 `TIMING_CALENDAR_RANGE_INSUFFICIENT`，禁止 weekday 或自然日外推。
- 评价日只有在 `effective_date <= evaluation_date` 时才能看到该版本。

## 11. 已冻结的 Financial Forward Return Contract

本节同样由 Operator 批准，状态为 `FROZEN`，用于财务因子横截面 IC / RankIC：

- 固定 horizon 为 20 个市场交易 session，entry 为评价日收盘，exit 为同一版本市场日历上的 `t+20` 收盘；entry 不计入 20 个 forward sessions。
- 不是 20 个个股有效观测行，不因停牌、缺价或退市改变 scheduled exit date，也不 roll forward/backward。
- entry 和 exit 均使用一致的公司行动调整后 `close`。RQData 3.5.2 adapter 映射冻结为 `fields=['close','volume']`、`adjust_type='pre'`、`skip_suspended=True`；builder 按版本化市场日历重新对齐，缺行保持缺失而非缩短 horizon。运行 provenance 必须记录 provider field、adjustment mode 与完整 adapter mapping。
- entry 必须有合法收盘价、明确可交易状态和正的可交易观测；不满足时返回 NaN 并记录标准原因。
- entry/exit 缺价、entry/exit 停牌均返回 NaN；中途停牌但两个固定端点有效时仍可计算。
- 禁止 ffill、bfill、插值、最近价格替代以及任何基于未来可用性的样本重选。
- 若 `entry_date < delisting_date <= scheduled_exit_date`，优先使用可审计的退市结算/终止价值；不可获得时返回 NaN 和 `DELISTING_RETURN_UNAVAILABLE`，并分别报告退市总数、可计算数与不可计算数。
- factor formation universe 必须先于 label availability 固定。IC/RankIC 仅使用 formation sample 与有效 label 的当期交集，同时报告 formation、valid、excluded、coverage 和 exclusion-reason 分布。

标准 audit reason 至少包括 `ENTRY_PRICE_MISSING`、`EXIT_PRICE_MISSING`、
`ENTRY_NOT_TRADABLE`、`ENTRY_SUSPENDED_OR_UNPRICED`、
`EXIT_SUSPENDED_OR_UNPRICED` 和 `DELISTING_RETURN_UNAVAILABLE`。
