# FIN-MVP-DATA 三因子最小 FinancialBatch 接入契约

状态：`ACCEPTED`  
接入 Schema：`FinancialMVPBatch-v1.0`  
审计 Schema：`FinancialBatchAudit-v1.0`  
哈希契约：`FIN-MVP-DATA-HASH-v1.0`

## 1. 公共对象复用

本任务不创建多因子影子 Batch。仓库公共 `FinancialBatch` 的
`factor_id` 位于对象级，因此输出固定为三个真实公共对象：

```text
FinancialBatch(factor_id="ROE")
FinancialBatch(factor_id="BP")
FinancialBatch(factor_id="OCF_NP")
```

公共核心列和唯一键保持不变：

```text
columns = code, report_period, publish_date, effective_date, factor_value
key = code + report_period + effective_date
```

缺失于公共对象的 `evaluation_date`、R1B 血缘、R1C 样本掩码、路径和
快照证明保存在不可变 `MVPBatchObservationReference` 中。接入侧唯一键
为 `evaluation_date + code + factor_id`。

## 2. 路径 A

路径 A 只消费预计算值，不重新计算或覆盖 `factor_value`。每行必须同时
通过：

- FIN-R1C `factor_sample_mask=true`；
- FIN-R1B lineage ID、内容哈希和因子值哈希校验；
- `effective_date <= evaluation_date`；
- 上游计算引用、版本和 SHA-256；
- 来源快照指纹校验。

路径 A 不要求内部公式 ID。

## 3. 路径 B 固定注册表

注册表版本：`FIN-MVP-FORMULA-REGISTRY-v1.0`。

| factor_id | formula_version | 固定输入 |
| --- | --- | --- |
| `ROE` | `FIN-MVP-ROE-v1.0` | `parent_net_profit_ttm / average_parent_equity` |
| `BP` | `FIN-MVP-BP-v1.0` | `parent_equity / market_cap` |
| `OCF_NP` | `FIN-MVP-OCFNP-v1.0` | `operating_cash_flow_ttm / parent_net_profit_ttm` |

这些输入必须已经完成 TTM 或平均值构造。本任务不解释公式字符串，不执行
动态代码，也不构造 TTM、平均权益或市值时点。

零或负分母、缺失、NaN、Infinity 及其他异常不会被填充或静默处理，而是
以 `FORMULA_INPUT_REQUIRES_FIN_R2_PREP` 阻断。完整异常政策属于
FIN-R2-PREP。

## 4. 排序、重复和指纹

- 接入记录按 `ROE、BP、OCF_NP`，再按评价日、证券、报告期、生效日排序。
- 公共 Batch 按 `code、report_period、effective_date` 排序。
- 同一接入键出现两次即阻断；内容不同使用冲突原因码。
- 同一底层财务观测被多个评价日引用时，公共核心行保存一次，所有评价日级
  引用完整保存在 sidecar。
- Batch 指纹绑定配置、规范化核心行及评价日级接入记录。
- canonical JSON 使用 UTF-8、键排序、无额外空白和 SHA-256。

## 5. 未来标签隔离

`future_labels` 参数仅用于反未来函数测试，构造器不会迭代、复制、哈希、
校验或序列化它。标签删除、置空、乱序或数值扰动不得改变：

```text
三个 FinancialBatch
公共行排序
Batch 指纹
R1B 血缘引用
R1C 样本引用
```

## 6. 失败关闭

任一时间、样本、血缘、快照、公式、动态代码、重复或跨证券引用错误都会
阻断全部三个 Batch；不发布部分结果。状态与原因码分开：

```text
financial_batch_audit.gate_status = "blocked"
financial_batch_audit.errors[].code = "FINANCIAL_OBSERVATION_CONFLICT"
```

接入成功只证明三因子侧输入契约可复现，不表示因子有效、已完成异常处理或
可以运行真实数据。

## 7. 验收证据

补丁前后使用相同 detached HEAD、Python 3.11.9、pytest 9.1.1 及
原工作副本 `.venv`，未修改依赖。

| 验证 | 结果 |
| --- | --- |
| FIN-MVP-DATA 定向测试 | `57 passed / 0 failed` |
| R1A + R1B + R1C + MVP-DATA 联合测试 | `197 passed / 0 failed` |
| 权威回归 `research_core/factor_lab/ tests/` | `798 passed / 4 skipped / 0 failed / 273 warnings` |
| 更宽回归（忽略 examples/submissions） | `805 passed / 4 skipped / 0 failed / 273 warnings` |
| Python 编译检查 | 通过 |

补丁前权威回归为 `741 passed / 4 skipped / 0 failed / 273 warnings`。
新增 57 项均来自 FIN-MVP-DATA，跳过项和警告数未增加。

合成端到端审计：

```text
path_a.gate_status=ready
path_a.path_a_count=3
path_a.observation_reference.content_hash=ec857c393e22d075429ea1d73cd9c036674da97b993b54e978b81e1a04a54226
path_a.audit.content_hash=1256b7936bbea22a7070056900dd033aca7e670d870c4d738ff1f01fa15e067d

path_b.gate_status=ready
path_b.path_b_count=3
path_b.observation_reference.content_hash=39b4cf9ca7fcba3e7479e4534bc3c7c104fff9b4c2780caf3d9f8b0d197a2aa6
path_b.audit.content_hash=5958a017f961419853c7f1f825acdb16e47d49bf1fce2b4c102b32ad0b10cd9f

path_a_b_public_frames_equal=true
future_label_deletion_preserves_all_outputs=true
```

路径 A/B 的公共核心行一致，但来源和公式证明不同，因此完整接入指纹按路径
分别保存。三个路径 A Batch 指纹：

```text
ROE=a80c7d6b02ee032f8bd6cfd3ba5a3182ab808b39afb4b18c7e3c4e5c7e522dc5
BP=102efe937a5635005731cc8f9610d9558fa4afd1a6cbe401a08fc10d2bfdd573
OCF_NP=bf6a0fccac7de4f222f14f6905254a5cccce69bf459f2c30ed723171f522fba0
```

文件修改限定为获批的四个工作树文件和两个 CH6-G0 治理文件。公共
契约、R1A/B/C、Mock Provider、CI、依赖及源 main 均未修改，也未执行
任何 Git 写操作。

结论：

```text
FIN-MVP-DATA = ACCEPTED
FIN-R2-PREP = AUTHORIZED_TO_START
```
