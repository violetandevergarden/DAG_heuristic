# 可抢占阶段 7：LLM 结构化 DAG 调度算法研究计划

## 一、研究定位

### 1.1 研究对象不变

本阶段继续研究 `260804组会.md` 中抽象出的 DAG 调度问题。输入是一个已经确定的训练 DAG：

$$
G=(V_C\cup V_F,E),
$$

其中：

- $V_C$ 是计算节点，时长由输入给定；
- $V_F$ 是通信节点，工作量由输入给定；
- $E$ 是 finish-to-start 依赖；
- GPU 上的计算顺序已经编码为 DAG 边，不由本算法重新安排；
- ready compute 自动执行；
- 调度算法只决定 ready communication 的推进顺序；
- 第一主模型是单 channel、理想可抢占、零切换成本；
- 每次在任务完成等离散事件处，根据 residual DAG 重新决策；
- 目标是最小化整个 DAG 的 makespan。

单 channel 中，根据极化结论，可以只考虑某一时刻把全部带宽给一条通信：

$$
a_t\in Ready_F(s_t).
$$

因此核心仍是一个组合优化问题：

> 在每个事件点，从当前 ready 通信中选择哪一个推进，才能最大化通信与计算的重叠并最小化
> DAG 完成时间？

多 channel 只是这一抽象的后续扩展：action 从一条 ready flow 变为资源兼容的 ready flow 集合。
本阶段不转向现实网络协议、路由、带宽控制或 framework 实现研究。

### 1.2 相比早期人工 DAG，变化在哪里

研究模型没有变化，变化的是输入 DAG 的来源和结构：

```text
人工平行链 / 随机 fork-join DAG
                  ↓
由真实 LLM workload 导出的结构化 DAG
```

真实 LLM DAG 不是任意一般 DAG。它通常具有：

- micro-batch、GA、iteration 产生的大量重复子图；
- PP 带来的 warmup、steady、cooldown 波形；
- TP/EP collective 形成的局部 fork/join；
- DP 通信汇入 optimizer 或 iteration barrier；
- 相同 stage/layer/collective 在不同 micro-batch 中近似同构；
- ready frontier 相对整个 DAG 较小；
- 不同重复单元之间仍通过依赖和共享 channel 强耦合。

本阶段要回答的是：

> 这些规律能否让我们比“把真实 DAG 当成任意一般 DAG”做得更好？

“更好”包括两种可能：

1. 在同样搜索预算下得到更小的 makespan；
2. 在保持解质量的同时显著减少状态数和运行时间。

### 1.3 明确不研究的内容

本阶段不研究：

- 重新设计 1F1B、Zero Bubble、DualPipe 的计算编排；
- 改变 F/B/W 的 compute order；
- 重新安排 micro-batch 注入；
- placement、routing、拥塞控制或 collective 协议；
- 框架层 runtime scheduler 的工程实现；
- 将现实网络的所有细节加入模型。

不同 pipeline mode 和并行配置只是生成不同结构 DAG 的方法，不是调度算法的 action。

## 二、总体研究问题

### 2.1 普适算法问题

首先保留与 LLM 标签无关的一般问题：

- Longest-tail 为什么有效，又在哪些结构上失效？
- 一步 Rollout、有限宽 Beam 和 Monte Carlo 能否稳定修复这些失效？
- optional WAIT 在什么 DAG 状态下有价值？
- join、barrier 和未来任务释放怎样进入候选生成，而不产生重复奖励？
- 是否存在比通用 2-bound 更强的算法特定近似界？

这些结论只依赖 DAG 和调度语义，应继续作为所有结构算法的安全基线。

### 2.2 LLM 结构是否能降低复杂度

重点研究以下结构参数：

$$
(k_{frontier},k_{type},k_{boundary},k_{join},k_{period}).
$$

分别表示：

- 同时 ready 的通信数；
- 规范化后的任务类型数；
- 重复单元之间的边界状态大小；
- 活跃 join/barrier 数；
- steady-state 周期长度。

目标不是证明整个问题突然变成多项式可解，而是寻找：

- 关于这些参数的 FPT 或伪多项式算法；
- quotient state、memoization 和 dominance；
- 小边界动态规划；
- 固定窗口 Exact/Beam；
- 可安全复用的 value/policy 条件。

### 2.3 不同特殊结构能否分别得到结论

如果无法得到一个统一的 LLM-DAG 定理，可以按子类分别研究：

1. 重复平行链；
2. 周期性 fork/join DAG；
3. backbone 加 deferred branches；
4. 多个 bucket 汇入共同 barrier；
5. 小 frontier 的 pipeline wave；
6. 多 Job DAG 的并集；
7. 固定多资源上的结构化 DAG。

每个子类至少争取得到以下一种结果：精确 DP、伪多项式算法、近似界、支配规则，或者明确的
参数化反例。

## 三、把 LLM 规律表示成算法可用的 DAG 结构

### 3.1 规范化任务类型

绝对 task ID 不具有复用价值。对每个节点建立结构签名：

```text
(kind, role, stage, local_layer, phase,
 relative_microbatch, collective_step, predecessor_types, successor_types)
```

多资源扩展时再加入 resource class；时长可以保留精确值，也可以归入 size/duration class。

需要区分三种等价：

1. **结构等价**：局部依赖和角色相同；
2. **带权等价**：结构、通信量和计算时长相同；
3. **状态等价**：除上述条件外，当前剩余量和外部边界状态也相同。

只有状态等价才能在 Exact/DP 中无损合并。结构等价只能用于共享特征或启发式 value，不能直接
合并搜索状态。

### 3.2 重复单元的接口

不能把 micro-batch 子图独立求解后直接拼接。对一个重复单元 $M_k$，定义边界接口：

$$
I_k=(In_k,Out_k,Carry_k,Barrier_k),
$$

其中：

- $In_k$：来自其它单元的未满足前驱；
- $Out_k$：完成后会解锁其它单元的节点；
- $Carry_k$：跨周期尚未完成的通信及剩余量；
- $Barrier_k$：跨多个单元的 join 状态。

如果两个单元内部同构但接口状态不同，它们不是同一个调度状态。

### 3.3 商图和计数状态

将同类型、同状态的实例折叠，得到商图状态：

$$
\bar s=(n_1^{ready},n_1^{running},n_1^{done},\ldots,z_{boundary}),
$$

其中 $n_h$ 是第 $h$ 类模板实例的计数，$z_{boundary}$ 保留无法对称化的边界任务。

阶段 5 已经证明这种方法在严格可交换 replica 上能把 6 个副本的 Exact 状态从 18,134 压到
126；但有跨 micro-batch 依赖或共享 channel 时，必须把耦合信息纳入 $z_{boundary}$。

### 3.4 Backbone、side branch 和 barrier 是 DAG 概念

为了避免变成 pipeline 编排研究，统一使用 DAG 结构定义：

- `backbone`：当前 residual DAG 中影响关键下界的路径集合；
- `side branch`：暂不在关键路径上，但最终汇入某个 milestone 的分支；
- `barrier`：入度大于 1 或由多个重复实例共同汇入的同步点；
- `release flow`：完成后会使新的计算/通信 ready 的通信节点。

PP、DP、TP、EP 只是这些结构在 LLM 中的常见来源。算法应首先依赖结构定义，而不是依赖名称。

## 四、算法主线

### 4.1 通用安全基线

保留当前已经形成闭环的算法：

- Dynamic Longest-tail：对 residual DAG 重算尾长；
- Rollout-flow：试走多个 ready flow，再用基线补全；
- Rollout-WAIT：额外考虑主动等待到下一 compute event；
- Beam：保留有限宽度的部分调度状态；
- Exact Oracle：小图或缩小窗口的 ground truth。

结构化算法必须和等预算的通用 Rollout/Beam 比较，而不能只和 Longest-tail 比较。

### 4.2 语义多样的候选生成

不设计一个固定加权总分，而是从不同角度各保留少量候选：

$$
\mathcal C(s)=
\mathcal C_{tail}\cup
\mathcal C_{release}\cup
\mathcal C_{barrier}\cup
\mathcal C_{slack}\cup
\mathcal C_{repeat}.
$$

候选含义：

- `tail`：当前 residual tail 最大；
- `release`：完成后预计释放最长或最多的新任务；
- `barrier`：可能成为某个 join 的最后 blocker；
- `slack`：侧分支距共同 milestone 的余量最小；
- `repeat`：同一 phase 的历史/对称状态中 value 最好。

最终仍用真实状态转移和 completion policy 评价：

$$
\widehat C(s,a)=\Delta(s,a)+\widehat J(f(s,a)).
$$

因此结构特征只负责避免漏掉重要 action，不被直接解释为真实 makespan 收益。

### 4.3 Quotient-state Exact/Beam

对重复模板进行规范化，搜索 key 不保存绝对 micro-batch ID，而保存：

```text
(template counts, boundary frontier, remaining classes,
 active compute events, barrier counters)
```

需要证明 canonicalization 保持：

- ready 集合；
- 合法状态转移；
- 每一步耗时；
- 最终 makespan。

只有满足这些条件的状态才能无损合并。其余相似状态只允许共享 heuristic value，不能用于 Exact。

### 4.4 小边界动态规划

将 DAG 按 micro-batch wave、GA group、iteration phase 或同步 barrier 划分为连续区域：

```text
Region_1 -- Interface_1 -- Region_2 -- ... -- Region_m
```

对每个区域不只输出一个局部最优 makespan，而是输出一张接口代价表：

$$
DP_k[z_{in},z_{out}]
=\text{区域 }k\text{ 从边界状态 }z_{in}
\text{ 转移到 }z_{out}\text{ 的最小代价}.
$$

全局解通过接口 DP 组合。这样可以保留跨区域 carry-in，而不是错误地把局部最优调度直接拼接。

该方法是否可行，关键取决于接口宽度而不是整个 DAG 节点数。需要测量真实 LLM DAG 的
$k_{boundary}$ 是否足够小。

### 4.5 Rolling-window Exact/Rollout

当完整 DAG 太大时，在当前 frontier 周围建立事件窗口：

- 当前所有 ready communication；
- 下一批可能完成的 compute；
- 候选到最近 barrier/release milestone 的必要后继；
- 少量跨窗口 carry state。

窗口内部用 Exact、DP 或 Beam；窗口外用 residual lower bound/value approximation。执行一个事件后
重新建窗。这与 `260804组会.md` 的 runtime-adaptive 思路一致，但当前只研究算法，不涉及框架实现。

### 4.6 周期 value 复用，而不是固定 action 复制

对于重复 micro-batch/iteration：

- 缓存规范化状态的 value、候选排名或 rollout 后缀；
- 状态再次出现时复用计算结果；
- 若 boundary/carry 状态不同，则重新规划；
- 不直接复制孤立周期的动作序列。

阶段 5 的反例表明，复制单周期局部最优的近似比可趋近 1.5。因此 repetition 的第一用途应是
压缩搜索和 warm start，而不是固定周期排程。

### 4.7 多 Job 分层搜索

多 Job 是多个无跨 Job 依赖 DAG 的并集，但通信共享 channel。每个 Job 内部使用自己的结构化
状态产生 $K$ 个候选，全局层对候选并集做 Rollout：

$$
\mathcal C_{global}(s)=\bigcup_j\mathcal C_j^K(s_j).
$$

细粒度的 stage/micro-batch/phase 只在 Job 内产生候选；跨 Job 比较使用 residual lower bound、
milestone、slack、剩余工作和目标函数。已有实验说明 K=1 会遗漏多 Job 最优 action，K=2 在当前
40 个双 Job Exact 小图上恢复全部最优，但还需在真实缩小窗口和 3--4 Job 中验证。

## 五、按 LLM 并行维度提取 DAG 规律

这里分析的是“它们生成了什么 DAG 子结构”，不是它们在真实网络中如何实现。

### 5.1 PP：周期 release 与小 frontier

比较 1F1B、Interleaved、ZB、Bidirectional、DualPipe 生成的 DAG，提取：

- ready communication frontier 随事件的变化；
- warmup/steady/cooldown 的结构周期；
- 相邻 micro-batch 之间的依赖偏移；
- 重复单元的入口、出口和 carry state；
- residual critical path 在 stage/micro-batch 间如何移动。

目标是寻找统一的 pipeline-wave 状态表示，而不是为每种 pipeline 写一个固定优先级。

### 5.2 DP：共同 barrier 的重复 side branches

DP bucket 通常形成多个逐步释放、最终汇入 optimizer/iteration barrier 的分支。研究：

- common-barrier 子问题能否用伪多项式 DP；
- side branch 的 latest-start/slack 如何精确或下界估计；
- last-blocker 何时形成有效支配规则；
- 多个 bucket 同构时能否计数压缩；
- 与 backbone 交替服务是否存在交换论证。

### 5.3 TP：紧耦合的局部 fork/join

TP collective 在 DAG 中常表现为计算之间的短间隔 fork/join。研究：

- 是否存在多个 TP 通信同时 ready，从而实际产生选择；
- 若每次只有一个 ready，是否可以把该结构收缩成加权超节点；
- collective 展开后的对称 flow 是否可以商图压缩；
- TP join 是否增大 boundary width，还是只增加节点数。

### 5.4 EP：结构重复、权重变化的 fork/join

EP 子图可能结构相同但通信量随 token routing 改变。研究：

- 结构等价但带权不等价时，value/policy 能复用到什么程度；
- 对 duration 扰动的 regret；
- 大小类离散化是否支持近似 DP；
- join blocker 规则在流量偏斜下是否稳定。

### 5.5 B/W 解耦只是一个子结构

B/W 修复使部分 DAG 出现共同前驱后的并行分叉：

```text
ready condition --> B branch
                --> W/DP branch --> optimizer barrier
```

它应归入“backbone + barrier side branch”子类，与任何具有相同 DAG 结构的问题一起研究。
不单独设计 ZB 调度算法，也不改变 B/F/W compute order。

### 5.6 组合并行

不能直接把 TP、PP、DP、EP 子问题的局部最优解相加。组合 DAG 中需要显式分析：

- 不同维度子图之间的依赖边；
- 同时 ready 集合的重叠；
- 共同 barrier；
- 重复模板之间的共享状态；
- 单维度收缩后留下的接口大小。

“笛卡尔积”只有在接口可控时才有算法价值。更合适的目标是寻找小 separator、小 frontier 或小
boundary width，从而构造参数化 DP。

## 六、理论研究路线

### 6.1 继续巩固通用界

1. 明确单 channel 任意 work-conserving 调度 2-bound 的全部条件。
2. 保留趋近 2 的参数化紧例，并确认适用于当前事件级可抢占模型。
3. 分析 Dynamic Longest-tail 是否有独立于任意策略 2-bound 的更强界；若没有，给出反例。
4. 证明 Rollout 包含基线 action 且使用同一 completion policy 时的逐实例支配性质。
5. 区分 observed optimal rate、逐实例支配和 worst-case approximation ratio。

### 6.2 平行链和重复链

继续研究：

- 给定整数总时间 $T$ 的伪多项式 DP；
- 二分 makespan 加可行性 DP；
- 按链数、每链通信数或最大 lag 参数化的 FPT；
- 时长缩放能否得到 FPTAS；
- 重复链类型只有 $k$ 种时的计数 DP。

重复链类型数小可能是 LLM 结构带来的第一个严格复杂度收益。

### 6.3 Barrier/deferred 子类

建立抽象：一条或多条 backbone，不同时间释放 side jobs，所有 side jobs 在共同 sink 前完成。
尝试：

- common deadline 下的 earliest-latest-start 规则；
- 按总 side work 和 release event 的 DP；
- “先 backbone 还是先 side work”的交换条件；
- 固定深度 lookahead 的不可突破反例；
- last-blocker 候选相对普通 Rollout 的独立价值。

### 6.4 小边界分解

若区域间接口状态数为 $B$，每个区域内部状态数为 $S$，争取得到类似：

$$
O(m\cdot S\cdot f(B))
$$

的算法，而不是随全部 micro-batch 指数增长。需要证明接口状态包含哪些信息才满足 Markov 性。

### 6.5 对称与周期

证明两类不同结果：

1. automorphism 下状态合并的 Exact 正确性；
2. 周期边界状态平移等价时，value/policy 平移成立的充分条件。

同时保留负面结果：仅子图同构而边界状态不同，不足以复制动作序列。

## 七、Benchmark 与实验设计

### 7.1 测试集层次

继续使用三类 benchmark：

- `random`：控制结构参数，观察总体趋势；
- `adversarial`：攻击某个算法或错误分解假设；
- `real`：从 AICB/SimAI 导出的固定 LLM DAG 快照或缩小窗口。

实验结果分别报告，不能用大量容易 random 图掩盖 adversarial/real 差异。

### 7.2 真实 DAG 扫描维度

选择有限但能区分结构的配置：

- TP、PP、DP、EP 的单维度和代表性组合；
- GA、micro-batch 和 layer 数；
- 1F1B、Interleaved、ZB、Bidirectional、DualPipe；
- 不同模型规模和 compute/communication ratio。

这里扫描配置是为了得到不同 DAG 结构，而不是评估真实网络部署。

### 7.3 先测“有没有选择”

对每张 DAG 先统计：

- ready frontier 的均值、最大值和分布；
- 同时 ready communication 至少为 2 的事件比例；
- 不同 action 导致不同后继 release 的事件比例；
- Longest-tail 与 Exact/teacher 分歧的事件；
- optional WAIT 可能有用的事件；
- 重复状态和可合并状态比例；
- boundary/interface 宽度。

如果一张图几乎没有选择，它只适合做语义回归，不适合评价 heuristic。

### 7.4 真实结构缩小窗口

窗口不是任意截取节点，而应保留一个真实决策的因果闭包：

1. 当前至少两个 ready communication；
2. 它们到最近 release/barrier 的必要后继；
3. 相关 active compute event；
4. 跨窗口入口和出口；
5. 足以保持两种 action 后果差异的尾部。

对缩小窗口使用 Exact；验证窗口最优 action 是否与较大上下文 teacher 一致，避免裁剪制造假结论。

### 7.5 对比算法

通用组：

- FIFO/SPT/LPT；
- Dynamic Longest-tail/LRPT；
- Rollout-flow/WAIT；
- Beam-8/32；
- Monte Carlo；
- Exact。

结构组：

- semantic-candidate Rollout；
- quotient Beam/Exact；
- boundary DP；
- rolling-window Exact/Beam；
- repeated-state value cache；
- multi-Job Adaptive-K。

所有结构算法必须与相近运行时间或相近状态数的通用搜索比较。

### 7.6 指标

解质量：

- optimal rate；
- mean/max approximation ratio；
- hard subset gap；
- 相对 Longest-tail 和等预算 Rollout 的 gap closed。

复杂度：

- explored states；
- rollout evaluations；
- runtime 和峰值内存；
- quotient/cache 命中率；
- 随 micro-batch、GA、Job 数增长的扩展曲线。

结构解释：

- frontier width；
- template 数和重复率；
- boundary width；
- cross-unit dependency/conflict；
- barrier 数和 side-work 比例。

## 八、执行阶段

### A0：LLM DAG 语义和可调度性审计

任务：

- 确认计算顺序已编码，action 只作用于通信；
- 修复或隔离错误依赖；
- 扫描真实 DAG 的 ready frontier、重复模板、barrier 和 boundary；
- 找出真正存在调度选择的 real windows。

退出条件：能够对每张图说明“有多少事件存在有效选择，以及选择可能影响什么”。

### A1：建立结构化 real-window Benchmark

任务：

- 从不同并行配置和 pipeline mode 导出 DAG；
- 自动提取 decision-centered causal windows；
- 用 Exact 验证小窗口；
- 按 parallel-chain、fork/join、barrier、periodic、mixed 分类；
- 固化能区分算法的 real/adversarial 样例。

退出条件：真实集不再全部是所有算法同解的容易图。

### A2：结构候选加通用 Rollout

任务：

- 实现 tail/release/barrier/slack/repeat 候选；
- 保证 Longest-tail action 始终作为 incumbent；
- 对候选做同一 completion policy 的端到端评价；
- 完成逐类 feature 消融和攻击集实验。

退出条件：明确每类候选在哪些 DAG 子类有效、在哪些情况下无效；不能只报告总平均值。

### A3：重复结构的 Exact/Beam 压缩

任务：

- 建立 canonical task/state signature；
- 识别 automorphism 和严格可交换实例；
- 实现 quotient-state Exact/Beam；
- 对一般耦合重复单元保留 boundary state；
- 比较相同最优值下的状态数和运行时间。

退出条件：给出无损压缩条件、证明、正例和错误合并反例。

### A4：小边界 DP 与滚动窗口

任务：

- 测量 PP wave、GA、barrier 分区的真实 boundary width；
- 为小边界子类实现接口 DP；
- boundary 过大时退化为 rolling-window Beam/Rollout；
- 研究窗口深度和接口摘要造成的误差。

退出条件：至少在一类真实结构上，相比 flat Beam/Exact 获得明确的复杂度下降或质量提升。

### A5：分别形成各特殊结构的结论

分别总结：

- PP 周期 wave；
- DP common barrier；
- TP local fork/join；
- EP 带权扰动重复结构；
- backbone + side branch；
- B/W 分叉；
- 多 Job DAG union。

每部分必须写清适用条件、算法、实验、反例和结论强度。不能因为某个策略名称相同就假设结构相同。

### A6：多 Job 与多资源推广

在单 Job、单 channel 结构算法明确后，再推广：

- 多 Job 使用 Job 内结构候选加全局 K-candidate 搜索；
- 多资源把 action 扩展为 compatible communication set；
- quotient 和 boundary state 加入资源占用；
- 与 flat multi-resource Exact/teacher 比较。

这里仍然是 DAG 组合算法研究，不展开网络系统实现。

## 九、近期最值得先做的工作

建议按以下顺序推进：

1. **先完成 A0/A1。** 目前最缺的是能让算法产生分歧的真实 LLM DAG 小窗口，而不是更多固定
   priority。只有找到真实选择点，才能判断 LLM 结构是否有用。
2. **随后做 A2。** 用结构特征扩大候选覆盖率，再由通用 Rollout 判断端到端 makespan；这是风险
   最小、最容易和现有代码结合的增强。
3. **优先做 A3 的 quotient-state 压缩。** 这是阶段 5 已经有严格正面证据的方向，比复制周期
   action 更可靠。
4. **根据 boundary width 决定是否投入 A4。** 如果真实接口很小，做接口 DP；如果不小，就使用
   rolling window，不强行分解。
5. **最后合并多 Job。** 重复结构作为 Job 内搜索加速器，多 Job 研究继续量化 K 候选的信息损失。

第一轮不再专门为 ZB、1F1B 或某个并行维度设计独立算法。它们首先是不同的结构测试族；只有当
某条规则能用纯 DAG 条件表达并跨多个真实 workload 生效，才将其提升为普适 heuristic。

## 十、预期成果

本阶段最终希望形成：

1. 一套忠实于 `260804组会.md` 的 LLM 结构化 DAG 调度模型；
2. 一套具有真实 LLM 来源、又能由 Exact 校准的 decision-window benchmark；
3. Dynamic Longest-tail 加结构候选、Rollout/Beam 的统一算法框架；
4. 重复结构的 quotient-state Exact/Beam 和正确性证明；
5. 小边界 DP 或其不可行性的实证结论；
6. PP、DP、TP、EP、B/W 分叉和多 Job 各自的算法性结论；
7. 普适结论、特殊子类结论和纯经验结论之间清晰的证据边界。

核心目标不是模拟更真实的网络，而是利用真实 LLM DAG 的规律，让原本 NP-hard 的通信排序问题
在解质量或搜索复杂度上得到可证明、可验证的改进。
