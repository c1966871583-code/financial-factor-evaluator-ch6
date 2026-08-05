# FIN-HO-8-B2：已批准数值数据集提取

本步骤只接受已提供的冻结合成共同样本，候选顺序固定为 `VQ`、`QG`、`CASHQ`。每个候选必须有 18 期、900 行，且定义哈希、共同样本指纹、逐行源内容哈希均与冻结契约一致。

行字段严格为：`evaluation_date`、`code`、`factor_id`、`raw_pit_factor_value`、`evaluation_factor_value`、`effective_date`、`source_record_id`、`source_content_hash`。`effective_date <= evaluation_date`，任何缺失、非有限值、重复键、样本漂移、定义漂移或中性化/选择字段都会 fail-closed。

提取器只复制并审计数值行：不构造组合、不重算 MAD、不调用 M/F/R 评价器、不计算信息增益、不选择候选，也不改变 `not production ready` 状态。输出为 B2 提取结果，不是 P05 最终交接包。
