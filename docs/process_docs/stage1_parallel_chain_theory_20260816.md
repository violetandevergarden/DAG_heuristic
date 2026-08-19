# Stage 1：当前可抢占模型下的理论记录

日期：2026-08-16

## 1. 模型与符号

本文只讨论有限条彼此独立、严格 compute/communication 交替的路径，共享一个单位容量 channel。compute ready 后自动、并行、不可抢占地执行；communication 只能在任务事件处暂停/恢复，零切换开销；只要存在 eligible communication，调度必须推进其中一个。目标是联合实例的 makespan。

令：

- $P$ 为全部 communication 工作量之和；
- $Q_k$ 为第 $k$ 条链上的 compute 工作量之和，$Q=\max_k Q_k$；
- $L$ 为忽略链间 channel 竞争后的最长加权链长；
- $I_H$ 为 work-conserving 调度 $H$ 的 channel forced-idle 总时长。

## 2. Work-conserving 2-近似安全界

**定理。** 对上述 Stage 1 模型中的任意 work-conserving 调度 $H$：

$$
C_H=P+I_H\le P+Q\le 2OPT.
$$

**证明。** channel 的全部 busy 区间没有重叠，且每单位 communication 工作恰好处理一次，所以 busy 总长为 $P$。调度没有主动 WAIT，因此其余 channel 空闲时间都是 forced idle。

选择在 $C_H$ 完成的任意一条链 $k^*$。在 $C_H$ 前的任意 forced-idle 时刻，该链尚未完成。严格路径的未完成前沿只有两种可能：eligible communication，或正在执行的 compute。forced idle 的定义排除了前者，因此该时刻必被链 $k^*$ 的某个 compute 区间覆盖。链内 compute 因依赖而互不重叠，故全部 forced-idle 区间的总长度不超过该链 compute 工作量 $Q_{k^*}\le Q$。于是 $C_H=P+I_H\le P+Q$。

任意可行调度必须完成全部单 channel communication，因此 $OPT\ge P$；也必须完成任一链上的全部 compute，因此 $OPT\ge Q$。所以 $P+Q\le2\max(P,Q)\le2OPT$。证毕。

适用条件缺一不可：独立路径、单 channel、线性且守恒的 communication 服务、零抢占/恢复开销、compute 自动执行、静态有限 workload、无主动 WAIT。该证明不能直接推广到 fork/join、固定多资源 DAG 或 JCT/fairness 目标。

## 3. 安全下界

对当前模型：

$$
LB_0=\max(P,Q,L)\le OPT.
$$

- $P$：单 channel 必须串行提供全部 communication 工作量；
- $Q$：任一链内 compute 由 finish-to-start 依赖串行连接，不能早于其 compute 工作量之和完成；
- $L$：任一完整因果链上的节点必须依赖串行完成，即使忽略所有链间竞争也不能短于该链权重。

compact Exact 在每个 residual state 使用同样的剩余量版本作 admissible lower bound。它只在 lower bound 严格大于当前可行 incumbent 时剪枝；因此不会剪掉更优解或与 incumbent 同值但 tie-break 更稳定的解。

## 4. 两个受限情形

### 4.1 compute 全为零

所有 communication 在其前驱 communication 完成时立即 eligible，任意 work-conserving 调度始终让 channel busy，直至处理完 $P$。因此每个调度的 makespan 都等于 $P=OPT$。

### 4.2 每条链只有一次且在 $t=0$ eligible 的 communication

设 communication 工作量为 $p_i$，其完成后只有 delivery compute tail $q_i$。存在一个最优调度不拆分任何 communication：取最早完成的通信，把它此前获得的全部服务压缩到连续前缀，不推迟其他通信完成；重复即可得到相同或更优的非抢占排列。

对相邻顺序 $i,j$，若 $q_i<q_j$，交换为 $j,i$ 不增加二者的最大完成时刻：交换前相关上界为 $\max(t+p_i+q_i,t+p_i+p_j+q_j)$，交换后为 $\max(t+p_j+q_j,t+p_j+p_i+q_i)$；由 $q_j\ge q_i$ 可得后者不大于前者。故按 $q_i$ 非增排序最优，ID 可作为稳定同分规则。

该结论要求共同 release、每链恰好一次 communication、之后没有第二次 communication；不能直接作为一般 Stage 1 的 Longest-delay 最优性证明。

## 5. Strong NP-hardness

### 5.1 源问题

Yu、Hoogeveen 与 Lenstra（Journal of Scheduling 7(5), 2004, pp. 333–348，DOI `10.1023/B:JOSH.0000036858.59787.c2`）的 Theorem 24 包含如下强 NP-hard 单机子问题：每个 job 有两个单位时长 operation，二者在同一台 single server 上执行，第二个 operation 的开始与第一个 operation 的完成之间有 job-dependent integer minimum delay，目标为最小化 makespan。后续调度文献也将其记为 unit-operation single-master / minimum transfer-lag 子问题。

这里使用的是该论文的 single-machine minimum-delay 结论，不是把 two-machine flow-shop 的两台不同机器直接合并为本项目的一个 channel。

### 5.2 规约

对源问题的每个 job $i$，构造一条严格交替链：

```text
communication A_i (duration 1)
    -> compute D_i (duration l_i)
    -> communication B_i (duration 1)
```

所有 $A_i,B_i$ 使用同一个 `channel:0`，不同 job 的链之间没有依赖。该构造为线性规模，communication work 为正，compute duration 为非负整数，链以 communication 开始和结束，完全属于 Stage 1 标准输入。

### 5.3 可行调度与目标值保持

- 给定源问题调度，按相同时间在 channel 上执行 $A_i,B_i$。$A_i$ 完成后，Stage 1 compute $D_i$ 自动运行 $l_i$；它完成的时刻正是 $B_i$ 的 minimum-delay release。因此源调度满足 delay 当且仅当对应 communication 满足链依赖。
- 给定 Stage 1 调度，删除自动 compute 区间，只保留 channel 上的 $A_i,B_i$，即可得到源问题调度；$D_i$ 的完成保证 $B_i$ 与 $A_i$ 至少分隔 $l_i$。
- 两边最后完成的是某个单位 operation/communication；自动 compute 只决定 release，不额外占用 single server，所以对应调度 makespan 相同。

源问题通常允许机器 idle，而 Stage 1 禁止在存在 eligible communication 时主动 WAIT。对 makespan 这一 regular objective，源问题存在一个 non-delay optimum：若调度在某个时段 idle 且有 operation eligible，把某个后来执行的 eligible operation 左移到最早空槽，只会使它自身及其 successor 更早可用，不推迟其他 operation；重复消除全部这种 idle。因此 work-conserving 限制不改变源问题最优值。

Stage 1 虽允许 communication 抢占，但构造中的 communication 均为单位整数工作量。由 $t=0$ 开始，所有 operation start 和 compute completion 都在整数时刻；一个单位 communication 从整数时刻开始后，在下一个可能严格更晚的整数事件前已经完成。因而构造实例中不存在能在 completion 前切开的内部 task event，可抢占能力不降低最优值。

所以该规约双向保持阈值和最优 makespan，Stage 1 makespan optimization 为 strong NP-hard。其 decision version 的证书可取有限 operation 顺序并由事件模拟器多项式验证，因此相应 decision problem 为 strongly NP-complete。

该结论已经回答旧审查中的三个关键缺口：两次 operation 使用同一 server/channel；minimum delay 由自动 compute 表达；单位整数 operation 使 task-event preemption 在构造上无额外能力。

## 6. 多 job 到 parallel chain 的候选映射

多个 job 的区域只有同时满足以下条件时，才能等价表示为本阶段的 independent chains：

1. 每个区域内部已经有固定的 compute/communication 全序；
2. 可合并的相邻同类节点之间没有可观察事件、资源变化或外部依赖；
3. job 间只通过同一个 channel 竞争，没有 cross-job dependency、collective barrier 或共享 compute 上限；
4. arrival 被显式编码为链首 release compute，且该表示不改变可调度事件；
5. 优化目标仍是所有链的联合 makespan。

若原 DAG 含 fork/join、collective completion、optimizer barrier 或跨链边，删除这些边所得模型只是 projection，不保证与原问题等价。JCT、weighted completion time、slowdown 和 fairness 也不由本轮 makespan 结论保留。仓库中的 `real_projection` 样例只用于检验这一候选抽象，不构成一般 LLM DAG 有效性的证据。
