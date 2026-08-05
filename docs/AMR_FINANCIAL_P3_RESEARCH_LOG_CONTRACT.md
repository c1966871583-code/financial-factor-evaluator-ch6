# FIN-P3-LOG-01：Research Log schema 冻结

Research Log 固定四个采集区：配置快照、结果引用、失败引用和血缘引用。每条未来记录都必须带 `entry_id`、来源任务、来源输出指纹、来源内容哈希、正式状态和 payload；状态词表固定为 `not_run`、`not_evaluable`、`insufficient_data`、`failed`、`completed`、`task_blocked`。

本契约不采集任何记录、不重算指标、不修改上游输出，也不连接外部持久化。后续采集器只能引用已验收输出并保留失败与未完成状态，不能填零或伪造成功。
