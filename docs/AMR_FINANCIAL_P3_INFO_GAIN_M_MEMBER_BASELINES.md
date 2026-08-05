# FIN-P3-INFO-GAIN-02B：M 轨道成员共同样本基线

## 任务边界

本步骤只在 `FIN-P3-INFO-GAIN-02A` 已验收的三个共同样本上，逐一评价组合内成员的 `M:20D` 基线。计算完全委托给既有 `FIN-MVP-M-EVAL` 单因子评价入口；本模块不重写 IC、HAC 或分组收益算法。

本步骤明确不执行：

- F 或 R 轨道评价；
- 组合因子评价；
- 最强成员选择或成员排序；
- 组合相对成员的信息增益计算；
- 动态权重、最佳期限或综合总分；
- 生产、收益承诺或交易结论。

## 冻结输入与评价配置

| 项目 | 冻结值 |
| --- | --- |
| INFO-GAIN-02A 输出指纹 | `b9e395416742f79edfd992d176582432ce644251f46cbfadb7d5a9ab661a43ef` |
| INFO-GAIN-01 契约哈希 | `e6d51313ae0fb326d4b239dbb3aefe542c8d5d623237b05e7678959436766747` |
| M 评价器源文件哈希 | `94e5c4a7808273fd4d6f5158b5cabc9dc07cdd0bd94dcbca91802a4d0bd74cea` |
| 评价上下文 | `M:20D` |
| 频率 | 月末 |
| HAC 最大滞后 | `1` |
| 分组数 | `5` |
| 每个组合样本 | `18` 期、每期 `50` 条、合计 `900` 条 |
| 输入性质 | 仅确定性合成数据 |

共同样本继续使用 02A 的原始键与指纹，不做交集重建：

- VQ：`ab58b5b1cf5e975563838f9e5aecd367f9c70a25d10d2678c69c6fa4a2f037d1`
- QG：`3e470edf7b8b8e065ec6f373e2e5872e1cabf42e360212928ecc7276834839ae`
- CASHQ：`c3d21f755aae395d179e23b361948bcb232f4e52625d12e5dd98bf013ebcd4f7`

## 成员与方向

- VQ：BP、EBIT_EV、ROE、OCF_NP，均为正向。
- QG：SALES_GROWTH、PROFIT_GROWTH、ROE、OCF_NP，均为正向。
- CASHQ：ROA、OCF_SALES 为正向；ACCRUALS 为负向。

方向在进入既有评价器前应用。负向 ACCRUALS 的评价值为原始值乘以 `-1`；原始值和共同样本本身不被修改。

同一成员即使出现在不同组合中也必须分别计算，因为它对应不同的共同样本指纹。总计形成 11 个“组合×成员”评价运行，不跨组合去重。

## 输出指标

每个运行保留既有 M 评价器的完整 `20D` 结果：

- 日度 Rank IC、Pearson IC；
- IC 均值、标准差、ICIR、HAC t、正值比例；
- 五分组收益、高减低收益和分组单调性；
- 18 期日度 IC 与日度分组明细；
- 评价状态、排除期数、样本数和 issue code。

`rank_ic_stability`、`pearson_ic_stability` 与 Fama–MacBeth R² 不由当前既有 M 入口生成，本步骤不另造算法填充；后续契约必须将其按既有状态处理，不得伪造为已计算。

## 门禁与失败语义

执行前依次核验：

1. 02A gate 为 `ready` 且没有错误；
2. 02A 输出指纹与包内容重算指纹一致；
3. INFO-GAIN-01 契约哈希一致；
4. 既有 M 评价器源文件哈希一致；
5. 三个组合顺序、样本指纹、18 期、900 行、成员集合与方向均未漂移；
6. M 输入仅为 `M:20D`，标签与配置引用完整；
7. 每个成员恰有 900 个唯一共同样本键，因子值与收益标签均有限。

任何核验失败均在调用评价器前返回 `blocked`。评价器单次异常会被保留为 `M_EVALUATOR_CALL_FAILED`，不静默丢弃，也不会触发 F/R 或信息增益计算。

## 确定性合成基线

冻结夹具的 11 个运行全部为 `completed`：

```text
combo_count = 3
member_run_count = 11
completed_run_count = 11
M evaluator calls = 11
F evaluator calls = 0
R evaluator calls = 0
output_fingerprint = 2a92a8b8896c4dc153853e0bf23c3c1dd950747d7552dd2ca5373480fe541970
audit_content_hash = d97d11240a9c93926983da05353a802bda445085bfa542fb2fccc0da365b7d7a
```

该结果只是研究级合成夹具上的成员基线证据，不代表真实样本结果或生产就绪。
