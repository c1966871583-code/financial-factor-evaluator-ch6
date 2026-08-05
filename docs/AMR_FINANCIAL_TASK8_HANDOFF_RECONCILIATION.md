# FIN-HO-8-B3-RECONCILE：P05 权威契约对齐

本步骤将 B1 schema、B2 数值提取结果与权威 `P05-HANDOFF-CANDIDATE-v1.0` 比较，输出结构化差异且 fail-closed。它不会猜测、填充或迁移缺失字段，也不会创建 `P05CandidateHandoffPackage`。

当前阻断项为包级必填字段、行级 PIT/样本/预处理字段，以及完整的 `comparison_policy` 状态对象。只有在这些差异经任务 8 负责人明确批准并以新版本契约冻结后，才可进入正式包生成或接收测试。
