# FIN-P3-INFO-GAIN-02D：R 轨道成员共同样本基线

02D 实现为正式、可审计的 R 轨 `not_run` 成员基线。

02A 仅冻结了 M:20D 共同样本。R 轨输入仍是 `not_run / CONTEXT_NOT_FROZEN`，缺少 PIT 风险标签、标签可得时间、官方来源、公司隔离、测试切分、Top-K 和校准配置。既有 R 评价器不能用因子值或收益标签替代这些输入。

因此为 11 个组合×成员条目分别输出：

- `calculation_status = not_run`；
- `not_run_reason = R_CONTEXT_NOT_FROZEN`；
- PR-AUC、ROC-AUC、Brier、Top-K 命中率、校准误差均为 `{status: not_run, value: null}`；
- F/M/R 评价器调用数均为零。

模块会核验 02A 指纹、契约、成员方向、R 输入状态及既有 R 评价器源码哈希。任一 R 上下文变为 ready 或出现标签/配置引用时立即阻断，不会自动推造风险标签或调用评价器。

本步骤绝不输出财务造假、错报、无风险、投资或生产准入结论。任何后续实际 R 轨评价都需要单独冻结标签时点、数据来源、公司隔离、Top-K/校准配置和人工复核边界。

```text
gate_status = ready
member_run_count = 11
not_run_count = 11
R/M/F evaluator calls = 0/0/0
output_fingerprint = 91ead71b3767a31ad0fb23cdff91c9c6372a8d77bbd68d552b23ebc4cf7a2e2e
audit_content_hash = 3c6fee677ce8efcd74f88dd672254726bb0be4984572fcce68b29785dae22a95
```
