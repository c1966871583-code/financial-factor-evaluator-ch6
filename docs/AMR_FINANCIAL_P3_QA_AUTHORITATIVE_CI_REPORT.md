# FIN-P3-QA-07：权威 CI 执行报告（未验收）

## 冻结基线

- HEAD：`f957d02f2f2d97606e2ed40d44f985b05f2ac31a`
- 控制文件 SHA-256：`2c775ad97db8dd06fedbb15af5d50a1684e9251e287046f8add6aff060fe5a47`
- 依赖文件 SHA-256：`297268db3d76f10154b40ed2821b5b3f112e403088ae81372043c821957e2e72`
- 环境：源 main 对应 Python 3.11 虚拟环境。

## 权威命令与实际结果

执行了 QA-00 冻结的原始命令，未添加过滤、跳过或重试参数：

```text
python -m pytest research_core/factor_lab/ tests/ -v --tb=short
```

实际汇总：`1 failed, 1796 passed, 4 skipped, 273 warnings in 1049.49s`。

唯一失败：

```text
tests/test_amr_numeric_deduplication_api.py::TestInputAndPreconditionErrors::test_factor_version_mismatch_returns_409
```

失败发生在测试帮助函数 `_pair()` 的第一个预检请求：期望 HTTP 200，实际得到 HTTP 500。该失败不是财务 P3 测试被跳过或填零；它使权威 CI 的退出码为非零，故不能由任何局部通过结果替代。

## 只读复核

| 命令 | 结果 | 解释 |
| --- | --- | --- |
| 失败单测独立运行 | `1 passed` | 不能稳定复现 |
| 完整 `test_amr_numeric_deduplication_api.py` | `40 passed` | 文件内顺序不是充分条件 |
| `test_amr_numeric_deduplication.py` 后接 API 文件 | `73 passed` | 紧邻数值去重模块不是充分条件 |

证据表明该问题在完整套件中发生，独立与局部组合均未复现。当前可确认其具有跨文件状态或执行顺序依赖特征，但尚未定位到可安全修复的具体实现根因。

## 结论

`FIN-P3-QA-07 = NOT_ACCEPTED`。未修改实现、测试、CI、依赖、控制文件或源 main。下一步需要以单独授权的真实缺陷定位/修复任务，建立可重复复现后再重新执行完整权威 CI；不得弱化断言、跳过失败用例或以局部结果宣布通过。

## FIN-P3-QA-07R 真实整改与重新验收

根因是 AMR 文件存储的同步边界不完整：测试夹具和重载路径会重绑进程级 `_store_base_dir`，但 `get_factor()`、`read_raw_store()` 及底层 JSON 读写没有与该重绑共用锁。预检请求因而可能在共享存储状态转换期间读到不一致的路径/文件状态，并将读取异常映射为 HTTP 500。

整改将锁升级为可重入锁，并让 `set_store_dir()`、`_read_json()`、`_write_json()`、`get_factor()` 和 `read_raw_store()` 使用同一锁。可重入锁保留既有写路径的嵌套调用，不引入死锁。新增回归用例在持锁的存储转换期间启动读取；读取必须阻塞，释放后才完成。该用例在修复前会失败，未改变任一 API 的成功条件。

整改后先运行存储重绑相关集：`247 passed, 0 failed, 7.83s`；随后完整执行同一权威命令，结果为 `1798 passed, 4 skipped, 273 warnings in 1011.95s (0:16:51)`，退出码为零。故此前的 QA-07 阻断已解除。
