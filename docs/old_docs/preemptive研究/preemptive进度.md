# 可抢占 DAG heuristic 研究进度

本文合并原来的阶段 0--5 记录，依次总结模型与 Oracle、并行链、一般 DAG、固定多资源拓扑，以及进入 LLM 结构研究前形成的初步方案。机器可读实验明细位于 `preemptive实验结果.json`；后续 LLM 重复结构研究使用独立的 `preemptive阶段5_LLM重复结构研究计划.md`。

## 一、阶段 0--1：模型、Benchmark 与 Exact Oracle

### 1.1 阶段目的

重新建立可抢占研究线，但不复用旧实验数字。所有结论以当前仓库 v2 benchmark 和事件驱动状态机为准。

### 1.2 正式模型

总带宽归一化为 1。通信 $i$ 在时刻 $t$ 获得比例 $x_i(t)$：

$$
x_i(t)\ge 0,\qquad \sum_i x_i(t)\le 1,
$$

其剩余通信量满足：

$$
\dot p_i(t)=-x_i(t).
$$

本研究采用与 fluid allocation 等价的极化实现：任意时刻只让一条通信得到全部带宽，即 $x_i(t)\in\{0,1\}$，但允许在事件点暂停并从剩余进度恢复。假设如下：

- compute 不可抢占，ready 后自动开始；
- communication 可暂停、恢复，已完成进度不作废；
- 抢占代价和最小时间片均为 0；
- 单通道同一时刻最多运行一条 communication；
- 依赖是 finish-to-start，只有整个通信完成才解锁后继；
- 时间和 duration 为整数，但状态转移按事件推进，不逐 tick 枚举；
- 允许主动 WAIT，但在线性零开销模型下，有 eligible communication 时 WAIT 被支配。

#### 为什么只在任务事件重新决策

假设区间 $(t_0,t_1)$ 内没有 compute/communication 完成，也没有新任务释放。若调度在该区间先服务 $A$ 一部分、再切换到早已 eligible 的 $B$，可以交换成先服务 $B$、再服务 $A$：总工作量不变，$B$ 不会更晚完成，$A$ 在区间末得到的总服务量不变。因此总能把无事件区间内的切换推到区间端点而不增大 makespan。

所以一次 `RUN(i)` 推进到：

$$
\Delta=\min\{p_i^{rem},\ \min_{c\in ActiveCompute}p_c^{rem}\}.
$$

到达事件后，调度器可以继续 $i$、切换到其它 eligible communication，或者在没有 eligible communication 时 WAIT。

该等价依赖线性吞吐、可保留进度、零切换代价、无最小 chunk，且后继不能流式消费。如果并发导致总吞吐下降、collective 只能整体推进、抢占需要重新握手，或后继可以消费部分数据，当前极化状态机便不再严格等价。

### 1.3 Benchmark v2

`dag-benchmark-v2.schema.json` 的核心语义是：

```json
{
  "preemption": "communication_resume",
  "decision_epoch": "task_event",
  "optional_idle": true,
  "compute_model": "unbounded_parallel",
  "resource_model": "exclusive_fixed_set",
  "preemption_cost": 0,
  "minimum_quantum": 0
}
```

生成器把既有随机和 adversarial DAG 结构提升为 v2，得到 64 个 v2 benchmark：单通道并行链 23 个、单通道一般 DAG 27 个、多资源 14 个。另有一个可抢占语义回归样例。真实 LLM 快照没有机械提升，因为“同一 DAG 换成可抢占标签”不能替代对 collective 可抢占粒度的审计。

### 1.4 Exact Oracle 与 Trace 校验

单通道状态记录每个任务的：

$$
(status,remaining),\qquad status\in\{pending,running,suspended,completed\}.
$$

在决策状态 $s$ 上递推：

$$
F(s)=\min_{i\in Eligible(s)}\left[\Delta(s,i)+F(f(s,i))\right].
$$

只有 `Eligible(s)` 为空且存在 active compute 时才强制 WAIT。Oracle 使用 memoization 合并相同 residual state，并提供 state limit 和 wall-clock limit。在每图 15 万状态、3 秒预算下，单通道 48 图得到精确解；`pm_fixed_beam_counterexample` 和 `pm_random_chain_6` 超时并明确排除；多资源 14 图全部得到精确解。Reference generator 只为真正完成的 Oracle 写入 optimal sidecar。

`assert_preemptive_trace` 校验每个任务的执行区间总长、compute 连续性、communication 多段恢复、channel 互斥、依赖合法性和最终完成性。手工样例 `preemption_unlock` 的时间线为：

```text
A: [0,3), [5,12)
B:       [3,5)
tail_B compute: [5,15)
```

其 makespan 为 15，发生一次真正抢占。

### 1.5 阶段结论

已经形成自包含 v2 JSON、事件状态机、精确小图 Oracle、Trace validator、CLI 和 reference result 的闭环。它研究的是理想 fluid 模型的极化实现，并不代表真实 NCCL/RDMA 已支持零代价任意粒度抢占。

## 二、阶段 2：并行链算法与理论

### 2.1 问题与 2-近似界

多条独立的计算—通信交替链共享一个单位容量 channel。令全部通信工作量为：

$$
P=\sum_j p_j,
$$

令任意单条因果链上的 compute 工作量最大值为 $Q$。任意 work-conserving 调度 $H$ 满足：

$$
T_H\le P+Q\le 2OPT.
$$

证明思路是：channel busy 的总长度恰为 $P$；channel idle 时没有 eligible communication，从最后完成任务反向沿依赖追踪，每段 idle 都可以 charge 给阻塞后续释放的 compute 链，合计不超过 $Q$。同时 $OPT\ge P$ 且 $OPT\ge Q$。

这个证明不依赖具体 priority，因此 FIFO、SPT、LPT、Longest-tail、Rollout 和有限 Beam 只要 work-conserving，都继承该安全界；但它不能说明某个具体算法的 tight bound 一定为 2。

对任意 work-conserving 策略族，2 是紧的。构造：

```text
A: comm(M)
B: comm(1) -> compute(M) -> comm(1)
```

错误策略连续服务 $A$，得到 $T_H=2M+2$；先完成 $B_1$ 可让 compute 与 $A$ 重叠，得到 $OPT=M+2$，故比值趋近 2。

### 2.2 实现的算法

- `FIFO`：按稳定 DAG 顺序选择 eligible flow；
- `SPT/LPT`：选择剩余通信最短/最长者；
- `Longest-delay`：选择当前通信完成后的 residual critical tail 最长者；
- `LRPT`：把当前通信剩余量也计入 residual path；
- `Longest-tail`：默认廉价基线，动态使用下游 residual tail；
- `Rollout-2`：尝试 tail 排名前两名各运行到下一事件，再用 Longest-tail 补全；
- `Beam-8/32`：按事件层保留 8/32 个 residual state，并保留 Longest-tail incumbent；
- `Monte Carlo-64`：固定 seed 抽样 64 条 work-conserving 完整轨迹并返回最好者；
- `Exact`：memoized event-state DP。

`Longest-delay` 与当前 `Longest-tail` 使用同一分数定义，仅为对应旧术语而保留两个名字。

### 2.3 并行链实验

精确可解的并行链共 21 个，包含 random 和 adversarial；两图因 Exact 超时未进入比值统计。

| 算法 | mean ratio | observed max | 最优率 |
|---|---:|---:|---:|
| FIFO | 1.19795 | 1.86364 | 33.33% |
| SPT | 1.18734 | 1.52174 | 23.81% |
| LPT | 1.25178 | 1.86364 | 14.29% |
| Longest-tail | **1.01605** | **1.21212** | **90.48%** |
| LRPT | 1.02526 | 1.21212 | 71.43% |
| Rollout-2 | **1.00000** | **1.00000** | **100%** |
| Beam-8/32 | 1.00000 | 1.00000 | 100% |
| Monte Carlo-64 | 1.00000 | 1.00000 | 100% |

这些只是 observed result，不是 exactness 或小于 2 的理论证明。Longest-tail 的最坏已观察图是 `pm_scaled_five_four_s4`：

$$
OPT=33,\qquad T_{LT}=40,\qquad T_{LT}/OPT=1.21212.
$$

旧的 $9/8$ 反例也被复现，说明可抢占 Longest-tail 并非最优规则。

### 2.4 Restricted results 与结论

若每条链只有一次通信且都在 $t=0$ ready，按 compute delivery tail $q_j$ 非增排列最优，可以由相邻交换证明。若所有 compute lag 为 0，makespan 恒为 $P$，任意 work-conserving 调度最优。

Longest-tail 是明显优于简单 size priority 的低开销基线。Rollout-2 在当前小图上关闭全部 Longest-tail gap，平均约 10 ms；Beam/Monte Carlo 同样命中最优但开销更高，适合作为离线 teacher；Exact 只用于小图。

## 三、阶段 3：从并行链到一般 DAG

### 3.1 动态 residual DAG

一般 DAG 不进行静态链分解。每个任务事件后重新计算：

$$
q_s(v)=d_s(v)+\max_{(v,u)\in E}q_s(u),
$$

其中已完成节点 $d_s=0$，running/suspended 节点使用 remaining duration。这样 fork 后的关键分支、join 的最后阻塞输入和不断缩短的 compute 都可以动态变化。

### 3.2 Join 信息

本轮没有把 join bonus 直接加入最终 priority，而只把“其它 join 前驱已经完成”的 communication 加入 Rollout 候选。最终仍用完整 counterfactual makespan 评价：

$$
\widehat C(s,a)=\Delta(s,a)+\widehat J_{LT}(f(s,a)).
$$

`join_rollout2` 使用一个 tail 候选加一个 join 候选，但与普通 `rollout2` 在全部 48 个单通道精确图上结果完全相同。因此当前只能说明局部 last-blocker 候选没有观察到独立贡献；更强的 join 后关键尾、latest-start slack 或资源延迟仍值得研究。

### 3.3 一般 DAG 实验

一般 DAG 精确可解 27 个。整体单通道 48 图的结果如下：

| 算法 | mean ratio | observed max | 最优率 | 平均原型耗时 |
|---|---:|---:|---:|---:|
| FIFO | 1.11995 | 1.86364 | 54.17% | 1.30 ms |
| SPT | 1.12297 | 1.52174 | 41.67% | 1.31 ms |
| LPT | 1.20175 | 1.86364 | 16.67% | 1.23 ms |
| Longest-tail | **1.01581** | **1.21212** | **83.33%** | 1.27 ms |
| LRPT | 1.01975 | 1.21212 | 75.00% | 1.27 ms |
| Rollout-2 | **1.00000** | **1.00000** | **100%** | 10.47 ms |
| Join-Rollout-2 | 1.00000 | 1.00000 | 100% | 10.87 ms |
| Beam-8 | 1.00000 | 1.00000 | 100% | 73.94 ms |
| Beam-32 | 1.00000 | 1.00000 | 100% | 193.87 ms |
| Monte Carlo-64 | 1.00000 | 1.00000 | 100% | 82.37 ms |

一般 DAG 子集中 Longest-tail mean ratio 为 1.01562、observed max 为 1.125、最优率为 77.78%。主要失败图包括 `pm_random_join_30`（24/22）、`pm_random_join_40`（22/21），以及三个 gap 为 1 的随机图。

48 图中共有 8 个 Longest-tail hard instances。Rollout、Join-Rollout、Beam 和 Monte Carlo 均修复 8/8，SPT 修复 5/8，LRPT 修复 1/8。

### 3.4 理论边界与结论

单通道、work-conserving、零抢占开销下仍保留 $T\le P+Q\le2OPT$。有限 Rollout/Beam 在样例上全部最优，不能推出更好的常数界。固定 lookahead 可能看不到需要连续多个事件投资才产生的解锁，固定 beam width 也可能裁掉长期最优分支。

Rollout-2 每个状态包含 Longest-tail 基准动作，并用相同 completion policy 评价，因此可以保留完整 Longest-tail incumbent，逐实例不差于基线；这是支配性质，不是更小的 worst-case ratio。

一般 DAG 无需拆成链再拼接。动态 residual tail 加事件级 Rollout 已形成通用基线；Join 特征应继续用于候选生成和消融，而不能退回局部 bonus 直接相加。

## 四、阶段 4：固定多资源拓扑

### 4.1 模型与算法

通信 $i$ 占用固定资源集合 $R_i$。一个动作选择兼容集合 $A$：

$$
R_i\cap R_j=\varnothing,\qquad \forall i\ne j\in A.
$$

集合内通信同时以单位速率推进；未选通信暂停并释放全部资源。下一决策事件是选中通信或 active compute 中的最早完成事件。

在零开销、线性服务模型中，给当前集合加入一个资源完全不冲突的 eligible flow 不会延迟已有流，所以 Exact 只需枚举 inclusion-maximal compatible sets。若存在切换开销、最小 chunk、非线性带宽或共享容量，该支配结论不再自动成立。

实现的算法包括：

- `Longest-tail pack`：按 residual tail 排序，贪心装入兼容通信；
- `Resource pack`：tail 优先，用剩余资源负载 tie-break；
- `Bottleneck pack`：优先占用剩余负载最大的瓶颈资源；
- `Set Rollout-2`：比较排名靠前的两个 maximal compatible sets；
- `Exact`：枚举 maximal compatible sets 的 memoized event-state DP。

### 4.2 多资源实验

14 个 random/adversarial 多资源图全部在预算内得到 Exact：

| 算法 | mean ratio | observed max | 最优率 | 平均原型耗时 |
|---|---:|---:|---:|---:|
| Longest-tail pack | **1.00661** | 1.05556 | 85.71% | 0.74 ms |
| Resource pack | 1.00661 | 1.05556 | 85.71% | 0.70 ms |
| Bottleneck pack | 1.04499 | 1.23077 | 64.29% | 0.71 ms |
| Set Rollout-2 | **1.00265** | **1.03704** | **92.86%** | 6.28 ms |

Longest-tail pack 失败的两个 hard instances 是 `pm_muti_random_003`（19/18）和 `pm_muti_random_008`（28/27）。Set Rollout-2 修复其中一个，平均关闭 50% gap。Resource pack 与 baseline 完全相同；Bottleneck pack 在 hard subset 上平均 gap closed 为 -150%，说明只看资源热点可能推迟 DAG 关键解锁。

### 4.3 与单通道的差别

多资源动作是兼容 flow 集合，总通信量 $P$ 不再是 makespan 下界，因为不冲突流可以并发。可用下界至少包括：

$$
LB=\max\left(L,\max_r P_r\right),
$$

其中 $L$ 是无资源竞争 critical path，$P_r$ 是所有使用资源 $r$ 的剩余工作量。单通道的 2-近似 charging 不能直接外推，因为多个资源 busy 区间会重叠，一条通信也可能同时占用多个资源。

### 4.4 阶段结论

多资源核心、Exact 和四个 baseline 已形成小图闭环。端到端集合 Rollout 仍然有效，简单资源负载 bonus 没有稳定价值。当前样本量较小，资源仍是固定排他集合，尚未模拟异构带宽、同一链路比例共享或 collective rank 同步。

## 五、阶段 5：进入 LLM 特殊结构研究前的初步规划

通用可抢占模型完成后，下一步不应直接添加 PP/TP/DP 名称 bonus。真实 collective 能否在任意事件暂停、不同 rank 是否必须同步、chunk 粒度和恢复开销仍需审计。

初步识别的可利用结构包括：

1. **重复 micro-batch 与 replica 对称性**：同一 `(stage, phase, layer, collective_step)` 的多个实例可能具有同构 residual state，可以按模板计数压缩 Exact/Beam；
2. **warmup/steady/cooldown 周期**：steady state 可能存在短周期带宽策略，搜索单位可提升为 `(stage, phase, microbatch_offset, collective_chunk)`；
3. **backbone 与 deferred work**：F、PP activation、B、PP gradient 构成 backbone，W、DP 和 optimizer preparation 作为带 deadline 的 deferred work，但两者不能静态拆成独立问题；
4. **B/W 解耦与 Zero Bubble**：只有 DAG 明确表示 B 和 W 彼此无依赖时，才能研究 W 填充 bubble 的价值；
5. **collective/chunk 级抢占**：需要确定真实抢占单位是 whole collective、NCCL channel、protocol step、chunk 还是 packet/work request；
6. **抢占代价与鲁棒性**：最终应考虑

$$
T'=T+N_{switch}c_{switch},
$$

以及最小 chunk $q_{min}$ 和每 flow 最大抢占次数 $K_{max}$。

LLM 候选仍应由端到端 counterfactual 评价：

$$
\widehat C(s,a)=\Delta(s,a)+\widehat J(f(s,a))
+c_{switch}\mathbf 1[a\text{ switches}],
$$

而不是把局部结构 bonus 当成真实 makespan 收益。候选可以包括 residual Longest-tail、optimizer latest-start、backbone release 后抢占 deferred、collective/chunk wave、资源互补集合，以及继续当前通信。

真实 benchmark 应覆盖不同 PP/TP/DP、GA、模型规模、pipeline schedule 和 placement，保留 collective identity、rank group、route 和 chunk 信息；从策略分歧事件中缩小 exact 小窗口，并分别报告 random、adversarial 和 real。

该初步规划现在已经被更具体的 `preemptive阶段5_LLM重复结构研究计划.md` 接替。新的计划把重点放在 motif 规范化、商图与耦合图、周期边界状态、重复策略扩展实验、对称搜索压缩和 coupling-aware periodic scheduler。

## 六、当前总体结论

1. 理想线性、零开销、可保存进度模型可以用事件点极化调度研究；
2. 单通道任意 work-conserving 策略有 2-近似安全界，但 Longest-tail 并非最优；
3. Event Rollout-2 在当前 48 个精确单通道图上全部命中最优，但这不是理论保证；
4. Join 候选当前没有表现出独立收益；
5. 多资源必须调度兼容集合，单通道 2-bound 不能直接继承；
6. 下一阶段最值得利用的是 LLM 的重复与周期结构，但重复单元间的依赖、资源冲突和 carry-in state 必须显式验证。
# 阶段 5：LLM 重复结构研究（已完成）

阶段 5 已按照独立研究计划完成。核心结论是：真实/合成 pipeline DAG 的 micro-batch 模板高度重复，但跨 micro-batch 的资源冲突很强，不能直接复制单周期调度；严格可靠的收益来自对称状态压缩，而当前简单的 coupling-aware PP priority 尚未优于 Longest-tail 或等预算 Rollout。

详细方法、证明、实验表格、限制和复现方式见：

- `preemptive阶段5_LLM重复结构研究结论.md`
- `preemptive阶段5_实验结果.json`

阶段 5 实验当时的限制是 Zero Bubble 图仍含 `B→W` 依赖；该问题现已由下述专项修复解除。
抽样真实 EP workload 与当前 rank grouping 约束不兼容、有限抢占粒度/切换成本尚未进入模型，
这两项限制仍然存在。

---

# Zero Bubble B/W 语义修复（2026-08-13，已完成）

Zero Bubble 原始数据 DAG 中错误的同层 `B -> W` 依赖已经修复。修复仅作用于
`ZeroBubblePipelineWorkloadBuilder`：完整构图并加入 PP gradient 依赖后，让同层 B/W
共享立即前驱；W→DP 和 W/DP→optimizer 保持不变。公共 builder 及 1F1B 等其他策略不变。

236 个受控 B/W pair 全部满足“无同层 B→W 且前驱集合相同”。子模块定向测试 52 项通过；
主仓库完整测试 66 项通过。修复后的合成 ZB 网格 raw data `B→W` 均为 0，旧的 ZB 调度黑名单
已经解除。serializer 仍会编码单 GPU compute order，因此当前可研究固定 ZB compute schedule
下的通信优化，尚不能让通信 heuristic 联合发现 F/B/W compute schedule。

详细修复、验证、同步步骤和后续方案见：

- `Zero Bubble B-W语义修复记录与后续研究报告.md`
- `preemptive阶段5_ZB语义修复后实验结果.json`

---

# 阶段 7：后续主线修正为 LLM 结构化 DAG 调度算法

后续研究继续使用 `260804组会.md` 的抽象 DAG 模型：计算顺序已经编码在 DAG 中，算法只决定
ready communication 的推进顺序。研究重点不是 pipeline compute 编排，也不是现实网络系统，
而是利用真实 LLM DAG 的重复模板、小 frontier、周期 wave、fork/join、common barrier 和小边界，
改进 heuristic/search 的解质量或降低 Exact/Beam/DP 的状态复杂度。

计划分别研究普适算法结论、结构化子类结论，以及 PP/DP/TP/EP、B/W 分叉、多 Job 等特殊 DAG
族。ZB 只是其中一个测试族，不作为独立主线；多资源拓扑也只作为 DAG 资源约束的后续扩展。

详细计划见：

- `preemptive阶段7_LLM结构化DAG调度算法研究计划.md`

---

# 阶段 6：单 Job 与多 Job 分层调度（初步闭环）

已完成多 Job DAG union、arrival、per-job JCT/slowdown、Flat/Hierarchical Exact、$K$ 候选接口、Adaptive-$K$、weighted-JCT Exact 和多资源 top-1 反例。当前结论是：细粒度语义应留在 Job 内生成少量候选，全局层使用粗 summary 筛选，但必须保留候选/资源多样性并用真实目标做端到端评价。

当前 40 个 Exact 双 Job 小图中，$K=1$ 最大 gap 为 7.14%，$K=2$ 全部恢复最优；多资源反例中 $K=1/K=2$ makespan 为 25/18。详细内容见 `preemptive阶段6_单job与多job分层调度初步结果.md`。

尚未完成真实 AICB multi-job 窗口、3--4 Job 系统 Exact、placement 扫描和有限 quantum/fairness 保证。

---
