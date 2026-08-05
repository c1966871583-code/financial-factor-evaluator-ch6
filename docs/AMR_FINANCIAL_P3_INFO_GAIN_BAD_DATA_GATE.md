# FIN-P3-INFO-GAIN：冻结 bad-data / 对抗性 Gate

Gate 运行 15 个冻结、确定性场景：缺失字段、类型错误、重复键、多对多 Join、非有限数和不稳定分母、PIT 与修订泄漏、样本不足/常数横截面、标签/未来窗口、F 不可评价、R 无正/无负/unlabeled、共同样本漂移与契约冲突。每项以实际 payload 驱动检测，而非以 case ID 或预标注行为映射；输出输入问题、预期和实际行为、错误码、排除原因、保留失败记录、通过状态及内容哈希。

PIT、修订泄漏、共同样本漂移和契约冲突固定为 `task_blocked`；单条键、Join 或数值问题固定为 `record_isolated`；样本/标签问题为 `period_not_evaluable`；F/R 上下文问题为 `track_not_evaluable`。Gate 不填零、不修改输入对象；相同语料的状态、错误码和内容哈希必须相同。
