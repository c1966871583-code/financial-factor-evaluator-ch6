# FIN-R1B 财务数据血缘契约

状态：`ACCEPTED`  
Schema：`FinancialObservationLineage-v1.0`  
哈希契约：`FIN-R1B-HASH-v1.0`

## 1. 边界

FIN-R1B 只消费已通过 FIN-R1A 的 `FinancialBatch` 与逐行
`TimingAudit`。本模块不会重新计算或修改 `publish_date`、
`effective_date`、生效策略版本或交易日历版本；不会执行动态公式，
不会连接网络、数据库或真实财务数据源。

## 2. 冻结键

- 财务观测键：`code + factor_id + report_period + effective_date`
- sidecar 反查键：`evaluation_date + code + factor_id`
- 不适用字段固定使用：`not_applicable`

每条 `FinancialBatch` 观测必须一一对应一条
`FinancialObservationLineage`。任一行不完整时，整个 sidecar 不发布。

## 3. 路径与版本

- 路径 A 接收上游已经计算的因子值，必须保存
  `upstream_calculation_reference`。
- 路径 B 只保存固定注册公式的引用，必须保存 `formula_reference`；
  FIN-R1B 不解释或执行公式。
- 修订记录必须通过 `supersedes_reference` 指向同一证券、因子和报告期
  内更早生效的记录。修订只能从 FIN-R1A 给出的新 `effective_date`
  开始可见。

## 4. 快照与哈希

所有哈希均使用 UTF-8、键排序、无空白 canonical JSON、SHA-256，
并把 `FIN-R1B-HASH-v1.0` 与哈希域写入待哈希载荷。空值使用 JSON
`null`，日期使用 ISO-8601；NaN 和 Infinity 被拒绝。

冻结哈希包括：

- `source_input_hash`
- `factor_value_hash`
- `source_snapshot_fingerprint`
- `configuration_hash`
- 逐行 `content_hash`
- sidecar 与 `provenance_audit` 内容哈希

同一 provider/dataset 在一次运行中只能使用同一
snapshot/as-of/fingerprint。静默快照切换、来源冲突、修订链断裂及
任何预期哈希不一致均 fail closed。

## 5. 输出和状态

`FinancialProvenanceResult` 提供：

- `provenance_audit`
- `observation_lineage_reference`（仅 ready 时存在）
- `source_snapshot_fingerprint`（可包含多个已冻结数据集快照）
- 不可变逐行 `lineage_records`

状态与原因码分开保存，例如：

```text
provenance_audit.gate_status = "blocked"
provenance_audit.errors[].code = "MULTISOURCE_CONFLICT"
```

禁止创建组合状态字符串。血缘门禁通过只证明来源、快照、版本、逐行
引用和内容哈希可验证，不代表因子有效，也不授权真实数据运行。

## 6. 验收证据

补丁前与补丁后使用相同的 detached HEAD、Python 3.11.9、pytest
9.1.1 及原工作副本 `.venv`。未修改依赖清单。

| 验证 | 结果 |
| --- | --- |
| FIN-R1B 定向测试 | `46 passed / 0 failed` |
| FIN-R1A + FIN-R1B 联合测试 | `89 passed / 0 failed` |
| 权威回归 `research_core/factor_lab/ tests/` | `690 passed / 4 skipped / 0 failed / 273 warnings` |
| 更宽回归（忽略 examples/submissions） | `697 passed / 4 skipped / 0 failed / 273 warnings` |
| Python 编译检查 | 通过 |

权威回归补丁前为 `644 passed / 4 skipped / 0 failed / 273 warnings`。
新增 46 项均来自 FIN-R1B，既有跳过项和警告数未增加。

合成端到端审计输出：

```text
gate_status=ready
total_observations=3
lineage_complete_count=3
lineage_incomplete_count=0
revision_count=1
conflict_count=0
hash_mismatch_count=0
source_snapshot_fingerprint=b43f3219ae33f43808504d750d183be853beeed0a00b5f5dba851b7c28bd62cd
observation_lineage_reference.content_hash=e576f08f00c0d3532a33ace790c2eaa32dc22affd64ce394d7cdc94608008da4
provenance_audit.content_hash=22452c6cc34a0969698b6142159c91602d96ae3a0dff186e09f0d1c5c40368c9
```

文件边界为授权的四个工作树文件和两个 CH6-G0 治理文件；受保护文件
零修改，主工作副本原有状态未被改变，未执行 commit、push、pull、
merge 或回退。

结论：

```text
FIN-R1B = ACCEPTED
FIN-R1C = AUTHORIZED_TO_START
```
