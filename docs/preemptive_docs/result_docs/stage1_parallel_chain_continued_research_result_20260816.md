# Stage 1 parallel-chain 继续研究结果

日期：2026-08-16

## 1. 理论退出条件

已将 compact key 的 future-equivalence 从 docstring 提升为独立证明草稿：在严格独立交替链、finish-to-start、compute 自动且不可抢占、communication 零开销恢复、task-event 决策、无主动 WAIT 和 makespan 目标下，链 frontier 的位置与剩余工作决定全部未来转移。相同完整链类型之间还存在保持可行性和代价的置换自同构，因此可用 frontier 多重集压缩。

NP-hardness 不再是 conjecture。理论记录给出从“单机上每个 job 含两个单位操作并具有整数最小间隔”的强 NP-hard 问题到 Stage 1 的映射：两个单位操作映射为两段 communication，中间最小间隔映射为自动 compute。整数事件和单位通信保证该构造中抢占不增加能力，阈值可行性双向保持。因此当前 Stage 1 决策问题强 NP-complete。

任意 work-conserving 调度仍有安全的 2-近似上界：通信忙时总量为 $P$；取最后完成链，其所有 forced idle 区间内必有该链 compute 在运行，故 $I\le Q$，于是 $C=P+I\le P+Q\le2OPT$。这是任意合法 work-conserving schedule 的安全界，不是 Longest-tail 的更强专属近似比。

## 2. 正式集合结果

仓库共有 145 个问题文件；Stage 1 preemptive 为 29 个：adversarial 14、random 10、structured 3、real-projection 2。Exact 在 10 秒/500,000 states 预算下完成 27 个，两个 timeout 不进入 ratio 分母。27 个完成实例均有 benchmark hash 匹配的 reference result，5 个 `real` 类实例全部覆盖。

| 算法 | n | mean ratio | P95 | observed max | optimal rate | mean runtime (ms) |
|---|---:|---:|---:|---:|---:|---:|
| Longest-tail | 27 | 1.017148 | 1.125000 | 1.212121 | 85.19% | 1.643 |
| LRPT | 27 | 1.026673 | 1.125000 | 1.212121 | 70.37% | 1.551 |
| Rollout-2 depth-1 | 27 | 1.001576 | 1.000000 | 1.042553 | 96.30% | 11.292 |
| Rollout-4 depth-1 | 27 | 1.000788 | 1.000000 | 1.021277 | 96.30% | 13.175 |
| Rollout-2 depth-2 | 27 | 1.000000 | 1.000000 | 1.000000 | 100% | 15.917 |
| Beam-8 | 27 | 1.000000 | 1.000000 | 1.000000 | 100% | 69.249 |
| Beam-32 | 27 | 1.000788 | 1.000000 | 1.021277 | 96.30% | 174.792 |

墙钟时间是本机单次观测，只用于同轮粗略比较。结构化调用计数测试才是 residual-tail 优化生效的主要证据。

分层结果中，random 的 Longest-tail、三种 rollout 和 Beam 均 observed optimal；real 五例中，三种 rollout 与 Beam 均 observed optimal，Longest-tail/LRPT mean ratio 为 1.016667、max 为 1.083333。adversarial 中 depth-2 为 13/13 observed optimal，而 depth-1 rollout2 在新增深度反例上暴露 gap。

## 3. 深度与候选数

固定 seed 搜索发现并经 Exact 核验的反例为三条链：

```text
comm=(7,4,6),   compute=(7,11,2)
comm=(1,4,3,7), compute=(0,4,10,1)
comm=(2,4,5,2), compute=(10,5,9,6)
```

其 makespan 为：rollout2 depth-1 = 49，rollout4 depth-1 = 48，rollout2 depth-2 = 47，Exact = 47（307 states，初始 lower bound 45）。所以增加候选数只能部分弥补短视；增加深度能够看到第二个通信选择后的 compute release，并在该例达到最优。

在正式 27 例上，depth-2 相对 rollout2 平均运行时间约增加 41%，rollout4 约增加 17%。样本仍小，当前只能回答“深度和宽度不等价”，不能宣称 depth-2 一般优于更宽 shortlist。

## 4. 对称压缩规模曲线

对每条链均为 `comm=(2,1), compute=(1,2)` 的 2–8 条相同链进行配对实验：

| 链数 | 未压缩 states / 状态 | 对称压缩 states / 状态 |
|---:|---:|---:|
| 2 | 14 / optimal | 8 / optimal |
| 3 | 101 / optimal | 21 / optimal |
| 4 | 838 / optimal | 56 / optimal |
| 5 | 5,317 / optimal | 110 / optimal |
| 6 | 10 s timeout | 193 / optimal |
| 7 | 10 s timeout | 305 / optimal |
| 8 | 10 s timeout | 456 / optimal |

5 条链时运行时间从约 4.99 s 降至 95 ms；6–8 条链未压缩均超时，而压缩版均在 1 s 内完成。该曲线证明实现利用了完全相同链的置换对称性，但不代表近似相同链也可合并。

## 5. 当前结论与剩余边界

Stage 1 的理论与工程闭环现在包括：目标语义、公共模拟器、可回放 trace、三方小图 Oracle 对拍、compact-key 证明、强 NP-hardness 规约、任意 work-conserving schedule 的 2-近似安全界、depth 反例和对称 Exact 规模证据。

仍未关闭的边界是两个固定实例的 Exact timeout、外部 CP-SAT/MILP 独立规模核验，以及从真实 SimAI workload 到 independent-chain projection 的可追踪删边/收缩证明。两个 pipeline projection 仍只是结构化投影，不能代表一般 LLM training DAG。
