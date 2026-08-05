# FIN-HO-8-B1：P05 候选交接包 Schema 冻结

Schema：`P05CandidateHandoffPackage-v1.0`。本任务只定义包结构，**不创建包实例**。

冻结字段依次为：

```text
schema_version
semantic_policy_content_hash
comparison_policy
candidate_id
candidate_kind
candidate_definition_hash
row_count
sample_fingerprint
records_fingerprint
row_lineage
manifest
content_hash
production_status
```

Schema 绑定 FIN-HO-8-A 的确定性数值语义内容哈希；候选 ID 只能由后续已授权的不可变候选输入提供，B1 不选择因子或组合。

禁止字段：`best_candidate`、`selected_candidate`、`selected_factor`、`selected_combination`、`selection_score`。任何 Schema 漂移均 fail-closed，状态恒为 `not production ready`。

后续 B2–B6 才可在独立授权下填入真实的行、样本指纹、逐行血缘、manifest 和确定性交接包；B1 不提取数据或生成 `P05CandidateHandoffPackage` 实例。
