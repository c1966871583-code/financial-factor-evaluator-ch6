# FIN-R1C 独立样本形成契约

状态：`ACCEPTED`  
样本 Schema：`FinancialSampleFormation-v1.0`  
标签连接 Schema：`FinancialLabelJoinAudit-v1.0`  
哈希契约：`FIN-R1C-HASH-v1.0`

## 1. 顺序不变量

```text
evaluation_calendar
→ historical_universe
→ PIT_snapshot
→ freshness_and_applicability
→ factor_sample_mask
→ label_left_join
→ valid_pair_mask
```

FIN-R1C 消费已经通过 FIN-R1A 的 `FinancialBatch` 和 FIN-R1B 的
`ObservationLineageReference`。它不重新计算 `effective_date`，不改写
来源血缘，不执行公式，不连接网络、数据库或真实数据。

## 2. 冻结键

- 样本键：`evaluation_date + code + factor_id`
- 标签配对键：`evaluation_date + code + factor_id + validation_track`
- 支持轨道：`M`、`F`、`R`

评价日历和历史证券池由独立输入给出。每个评价日、证券只选择当时满足
`effective_date <= evaluation_date` 的最新可见报告期和修订版本。

## 3. 标签隔离

`FactorSampleRecord` 及 `sample_fingerprint` 在读取标签前完成。删除、
置空、打乱或扰动任一标签轨道，不得改变：

- 评价日历；
- 历史证券池；
- PIT 财务版本选择；
- `factor_sample_mask`；
- 样本行内容哈希和 `sample_fingerprint`；
- 其他标签轨道的配对结果。

标签只通过左连接产生 `LabelPairingRecord`。无标签是可审计的
`label_available=false`，不会删除左侧样本。F 轨目标必须是来源报告期的
下一自然季度；未来标签的 `label_available_at` 必须严格晚于评价日。

## 4. 覆盖漏斗

每个评价日、每条轨道记录：

```text
universe_count
>= pit_available_count
>= non_stale_count
>= valid_factor_count
>= valid_pair_count
```

`label_available_count` 单独统计，不参与前四项样本形成。陈旧性使用
冻结配置中的 `freshness_max_age_days`，按评价日与 FIN-R1A
`effective_date` 的日历日差计算。完整漏斗使用
`coverage_content_hash` 固定其规范化内容。

## 5. 失败关闭

独立证券池缺失、R1B 血缘不完整或哈希不一致、来源版本冲突、标签时间
泄漏、非连续 F 目标及重复键均阻断最终输出。状态与原因码分开保存：

```text
gate_result.overall_status = "blocked"
gate_result.errors[].code = "LABEL_TIME_LEAKAGE"
```

门禁通过只表示独立 PIT 样本与标签连接语义可验证，不表示因子有效，
不构成准入、投资或真实数据运行授权。

## 6. 验收证据

补丁前与补丁后使用相同 detached HEAD、Python 3.11.9、pytest 9.1.1
及原工作副本 `.venv`，未修改依赖清单。

| 验证 | 结果 |
| --- | --- |
| FIN-R1C 定向测试 | `51 passed / 0 failed` |
| FIN-R1A + R1B + R1C 联合测试 | `140 passed / 0 failed` |
| 权威回归 `research_core/factor_lab/ tests/` | `741 passed / 4 skipped / 0 failed / 273 warnings` |
| 更宽回归（忽略 examples/submissions） | `748 passed / 4 skipped / 0 failed / 273 warnings` |
| Python 编译检查 | 通过 |

权威回归补丁前为 `690 passed / 4 skipped / 0 failed / 273 warnings`。
新增 51 项均来自 FIN-R1C，既有跳过项和警告数未增加。

合成端到端审计：

```text
gate_status=ready
sample_row_count=8
factor_sample_count=3
label_pairing_row_count=24
valid_pair_count=5
sample_fingerprint=1ece2c1ef995cb9aa04437b14422f2eb25691b8c2ed3e32fcc3e0a6f5dd107b1
sample_reference.content_hash=50fbeaba6256ea07c3df2ce46796354892a793320f082673b237405cc24c535f
label_join_audit.content_hash=21b812b052e1eca79c2ff8b87d4388477759e9a17c59e2ae41d3dad046688928
coverage_content_hash=e55f61d865e24ef76c4d18c9250b00028735318e064d07c796864708978e4d87
gate_result.content_hash=b4fed20b605edd4a78b13696c6246095b29911d85bdce7fe4ca45b9ddc7227a9
label_deletion_preserves_sample_fingerprint=true
label_deletion_preserves_sample_content_hash=true
```

文件修改限定为获批的四个工作树文件和两个 CH6-G0 治理文件。受保护
文件零修改，源 main 工作树原有状态未改变；未执行 commit、push、
pull、merge 或回退。

结论：

```text
FIN-R1C = ACCEPTED
FIN-MVP-DATA = AUTHORIZED_TO_START
```
