# 单 channel parallel chain 场景的研究

## 1. 阶段定位

parallel chain 是可抢占 DAG 通信调度的第一个算法研究阶段。它保留通信与后续计算之间的耦合，但去掉 fork、join、跨链依赖和多资源冲突。

这一场景本身也具有实际建模意义。多 job 共享单一通信瓶颈时，可以尝试把每个 job 内已经固定顺序、或者能够安全收缩的部分表示为一条 compute–communication 链，再把不同 job 之间的竞争表示为多条 parallel chain 共享 channel。这个类比目前还没有完成严格抽象，但它是提出和保留阶段一的重要动机。

因此，阶段一同时承担两项任务：一是建立后续一般 DAG 和结构特化研究所需的理论、安全基线、Exact Oracle、反例构造方法和实验规范；二是判断哪些多 job 子问题能够严格或近似地归约为 parallel chain，以及这种归约会保留哪些优化目标和调度信息。

模拟器的公共语义以 `docs/plan_docs/simulator.md` 为准。本阶段只研究算法和理论，不另行定义一套执行规则。

## 2. 问题定义

### 2.1 DAG 结构

输入由 $m$ 条互相独立的有向链组成：

$$
P_k=(v_{k,1},v_{k,2},\ldots,v_{k,n_k}),\qquad 1\le k\le m.
$$

本阶段将严格的 compute–communication 交替链作为标准形式。链内使用 finish-to-start 依赖，不同链之间不存在依赖边。若两个相邻节点类型相同，并且二者之间没有额外依赖、资源变化或需要保留的可观察语义，则可以合并其工作量，因此无需把连续的同类节点作为独立结构研究。

链可以从 compute 或 communication 开始，也可以由任一类型结束。数学推导中可以加入零工作量 dummy 节点，统一链的起止类型，甚至把不同链补齐到相同的节点数。该 padding 只是一种形式化工具，不改变原问题的可行调度和 makespan，也不要求在 benchmark 中实际生成零时长 communication。现阶段没有证据表明“所有链等长”能直接改善算法或复杂性，因此不把它作为主要研究假设；只有当某个证明或状态压缩确实需要时才使用。

### 2.2 Compute

- compute 在全部前驱完成后自动开始；
- compute 一旦开始便连续运行到完成，不可抢占；
- 不同链上的 compute 默认可以并行；
- compute 可以与 channel 上的 communication 重叠；
- 若需要表达计算资源上的固定串行顺序，应直接编码在链或 DAG 依赖中。

### 2.3 Communication 与 channel

- 所有 communication 共享一个单位容量 channel；
- 任意时刻至多运行一个 communication，并独占全部 channel；
- communication 可以在任务事件处暂停，已完成工作保留；
- 暂停的 communication 之后可以从剩余工作继续；
- 只有 communication 全部完成后才能解锁后继；
- 当前不考虑抢占和恢复开销。

在存在 eligible communication 时，调度必须推进某个 communication，不允许主动 WAIT。只有所有 communication 都尚未 eligible、但仍有 compute 正在运行时，channel 才会产生 forced idle。

### 2.4 调度决策

在每个离散任务事件处，调度器从当前 eligible communication 中选择一个运行。eligible 集合包括：

- 前驱已经全部完成、但尚未启动的 communication；
- 已经执行过一部分、当前处于暂停状态的 communication。

一次选择持续到当前 communication 完成，或者某个 compute 完成并形成新的调度事件。事件发生后，可以继续当前 communication，也可以切换到其他 eligible communication。

因此，本阶段研究的核心不是连续带宽比例，而是事件点上的通信选择和切换顺序。

### 2.5 优化目标

基础目标为最小化所有链全部完成的时间：

$$
\min C_{\max}.
$$

本阶段的数学目标仍是联合实例的 makespan。即使 parallel chain 来自多个 job 的局部投影，也暂不在这一阶段同时优化 JCT、fairness 等多 job 指标；这些目标是否能由链模型保留，需要单独论证。

### 2.6 与多 job 的关系

需要研究一种明确的映射：给定多个共享 channel 的 job DAG，在什么条件下可以把每个 job 或其中的一个区域收缩为一条或多条独立交替链。至少需要回答：

- job 内哪些固定顺序节点可以安全合并；
- fork/join、collective completion 和 optimizer barrier 是否会破坏链结构；
- job arrival 如何表示为链首的 release compute 或外部释放时间；
- 收缩后是否保留 communication 的 ready time、剩余工作和后续 compute tail；
- 不同 job 之间是否确实只通过 channel 耦合；
- 原问题的 makespan 与链模型的 makespan 是否相等，还是只能得到上界、下界或近似关系。

阶段一不预设所有多 job 问题都能转化为 parallel chain。预期结果可以是一个适用条件清楚的 restricted multi-job class，也可以是说明该类比在哪些结构上失效的反例。

### 2.7 问题规模参数

实验和复杂性分析至少区分以下参数：

- 链数 $m$；
- communication 总数 $N_c$；
- compute 总数 $N_p$；
- 最大链深；
- communication 总工作量；
- compute/communication ratio；
- 同时 eligible communication 的数量；
- 不同链之间的重复性和对称性。

只报告 DAG 总节点数不足以解释 Exact 和 heuristic 的难度。

## 3. 理论探索

### 3.1 复杂性

旧材料已经从带 delay 的两阶段 flow-shop 子问题出发，给出 parallel chain makespan 最小化的 NP-hardness 规约思路。该结果说明一般情形下不应把寻找多项式时间精确算法作为主要目标。

本阶段需要把旧证明整理为针对当前可抢占事件模型的自包含版本，明确：

- 规约中每个 operation、delay 与 compute/communication 节点的对应关系；
- 可抢占是否会改变规约实例的最优值；
- 是否允许零时长边界节点；
- 输入参数采用整数时得到的是 NP-hard 还是 strong NP-hard；
- 结论覆盖的最小链深和通信数。

完成这些说明后，再决定是否需要继续查找更接近的经典调度问题，而不是仅凭名称套用 flow-shop、coupled-task 或 preemptive single-machine 的结论。

### 3.2 Work-conserving 的 2-近似安全界

令全部 communication 的工作量为：

$$
P=\sum_{j\in V_{comm}}p_j,
$$

令任意单条因果链上的 compute 工作量最大值为 $Q$。旧研究给出的核心结论是：任意 work-conserving 调度 $H$ 满足

$$
T_H\le P+Q\le 2OPT.
$$

证明思路为：

1. channel busy 的总时间恰为 $P$；
2. channel forced idle 时不存在 eligible communication；
3. 从最后完成任务沿所在链反向追踪，可以将 forced-idle 区间归因于阻塞后继释放的 compute；
4. 这些 compute 的总长度不超过 $Q$；
5. 任意调度均满足 $OPT\ge P$ 和 $OPT\ge Q$。

该结论不依赖具体 priority，因此只要算法始终 work-conserving，就具有统一的 2-近似安全界。它不意味着任一具体算法的 tight approximation ratio 都等于 2，也不意味着有限实验中的最好方法具有小于 2 的一般保证。

本阶段需要将该证明单独整理，并逐项检查它使用的条件：单 channel、线性服务率、零抢占开销、compute 自动执行、静态有限 workload，以及全部计算顺序已经进入 DAG。

### 3.3 下界

Exact 和 heuristic 评价至少使用：

$$
LB_0=\max(P,Q,L),
$$

其中 $L$ 是忽略 channel 竞争时的最长加权因果链。后续可以继续研究：

- release/delivery-tail 下界；
- 时间窗口 demand bound；
- 基于剩余链前沿的下界；
- 对称链聚合后的计数下界；
- 适合 branch-and-bound 的增量下界。

所有下界必须先证明安全，再用于剪枝或报告 gap。

### 3.4 Restricted cases

优先确认以下特殊情形能否精确求解或获得更强保证：

1. 每条链只有一次 communication，且全部在 $t=0$ eligible；
2. 所有 compute duration 为 0；
3. 每条链至多包含两个或三个 communication；
4. communication 大小相同；
5. compute lag 沿链单调；
6. 链数或链深为常数；
7. 多条链完全相同或只存在少量类型；
8. 重复链共享相同 phase，但实例数量不同。

旧材料已经记录两个 restricted result：

- 每条链只有一次、且通信均在 $t=0$ eligible 时，按后续 compute delivery tail 非增排序可由交换论证得到最优解；
- 所有 compute lag 为 0 时，任意 work-conserving 调度的 makespan 都等于 $P$。

这些结论需要在新模拟器和手算样例上重新确认，并补充清晰的适用条件。

### 3.5 理论探索的边界

阶段一不要求必须得到优于 2 的一般近似比。可接受的理论成果包括：

- 整理并确认 2-近似安全界；
- 给出特定 heuristic 的参数化反例；
- 证明某个 restricted class 上的最优规则；
- 得到由链数、链深或链类型数参数化的算法；
- 说明某类改进不可能仅依赖局部 priority 完成。

## 4. 精确求解

### 4.1 目标

Exact 的主要用途是：

- 为随机和 adversarial 小图生成 ground truth；
- 评价 heuristic 的真实 gap；
- 自动搜索 priority、Rollout 和 Beam 的反例；
- 验证理论构造；
- 判断哪些结构参数真正决定求解难度。

Exact 不是面向大图的在线调度器。

### 4.2 状态表示

parallel chain 应优先使用比一般 DAG 更紧凑的状态。一个状态至少需要表达：

- 每条链已经完成到哪个位置；
- 当前 communication 的剩余工作；
- 各链上正在运行 compute 的剩余时间；
- 哪些 communication 已经 eligible 或暂停；
- 当前时间的平移等价信息。

应研究能否只保留每条链的 frontier 和剩余时间，而不保存完整任务状态。任何压缩都必须保证两个合并状态具有完全相同的未来可行动作和最优剩余 makespan。

### 4.3 候选精确方法

依次探索：

1. memoized event-state DP；
2. branch-and-bound；
3. 结合安全下界的 A* 或 best-first search；
4. 对称链计数压缩；
5. 目标 makespan 的二分可行性判定；
6. 在适用时使用 MILP/CP-SAT 作为独立交叉验证。

二分或流模型必须证明可行性判定与当前可抢占、内生 release 的链模型等价。旧材料中已经出现过“必要条件成立但实际不可调度”的假阳性，因此不能只依据 max-flow 条件宣称 Exact。

### 4.4 Exact 正确性

每个 Exact 结果必须满足：

- action path 可以在公共模拟器中完整回放；
- Trace 通过工作量、依赖、compute 连续性和 channel 排他验证；
- 与手算极小图一致；
- 在重叠可解规模上，不同 Exact 方法得到相同 makespan；
- timeout、state limit 和未完成结果不会写成 optimal reference。

### 4.5 规模实验

分别改变链数、链深、duration 范围、compute/communication ratio 和对称链数量，报告：

- explored states；
- candidate actions；
- peak memory；
- runtime；
- timeout 比例；
- 状态压缩率；
- 能稳定求解的边界规模。

## 5. Heuristic 与有限搜索

这是阶段一的主要研究内容。理论和 Exact 提供安全边界及评价工具，但主要精力应放在能扩展到中大规模 DAG 的决策方法上。

### 5.1 基础对照

至少保留以下简单策略：

- FIFO：按通信首次 eligible 时间和稳定 ID 选择；
- SPT：优先剩余通信工作较小者；
- LPT：优先剩余通信工作较大者；
- Longest-delay：优先后续 compute delay 较长者；
- LRPT：优先包含当前剩余通信在内的最长剩余路径；
- Longest-tail：优先当前 communication 完成后的 residual tail 较长者。

这些策略既是性能对照，也是构造反例和理解调度困难来源的工具。必须明确每个分数是否包含当前 communication 的 remaining work，避免 Longest-tail、Longest-delay 和 LRPT 概念混用。

### 5.2 Residual Longest-tail

Longest-tail 应基于当前剩余状态动态计算，而不是只在初始 DAG 上计算一次。对每个 eligible communication，分数应反映完成它以后所在链尚未完成的 compute/communication tail。

需要重点检查：

- suspended communication 的 remaining work 如何进入分数；
- 当前 communication 是否被重复计权；
- 新 compute 完成后 tail 是否正确更新；
- 相同 tail 下的 tie-break 是否稳定且不会掩盖反例；
- 静态 tail、delivery tail 和 residual critical path 是否被清楚区分。

### 5.3 Event Rollout

Rollout 对若干候选动作分别执行到下一个任务事件，再使用固定 baseline 补全，比较预测 makespan：

$$
\widehat C(s,a)=\Delta(s,a)+C_{base}(f(s,a)).
$$

优先研究 top-$k$ Event Rollout，并回答：

- 候选应按 Longest-tail、LRPT 还是混合规则产生；
- $k=2,4,8$ 的收益与开销；
- rollout 深度增加是否优于候选数增加；
- baseline incumbent 是否始终保留；
- 超时后如何确定性回退；
- 哪类反例需要连续多次选择同一通信才能被看到。

可抢占模型不存在主动 WAIT 候选，Rollout 只比较 eligible communication。

### 5.4 Beam search

Beam search 用于观察较大搜索预算能否稳定超过浅层 Rollout，并作为 Exact 无法扩展时的较强离线对照。

需要研究：

- Beam state 去重是否保持未来等价；
- 评分函数是否偏向短期完成而剪掉长期有利分支；
- 固定宽度是否存在可缩放反例；
- Beam 相对 Rollout 的质量提升是否足以覆盖额外运行时间；
- Beam 更适合作为在线算法、离线 teacher，还是仅作为实验上界。

Monte Carlo 不再作为阶段一继续投入的主要方法。该问题具有明确的事件状态、链结构、下界和候选优先级，而完整轨迹的随机采样很难命中需要连续多步保持的关键分支，也不能有效利用已有结构信息。在相同预算下，Event Rollout、Beam 或 Exact teacher 更符合问题特点。旧 Monte Carlo 结果只作为历史对照保留；除非后续出现明确的新用途，否则不继续扩展样本数、调参或维护专门实验。

### 5.5 进一步候选方向

在基础方法复核后，可以探索：

- earliest slack；
- 以人为构造的某指标为驱动的算法
- release-aware 或 phase-aware priority；
- 学习或自动调参得到的 comparator；
- 基于 Exact teacher 的 imitation/ranking；
- 对称链的批量决策；
- 由反例自动归纳的候选特征。

不要在缺少独立消融和反例的情况下不断叠加 bonus。新增特征必须说明它修复了哪类错误决策。

## 6. Benchmark 与测试

### 6.1 Random benchmark

随机生成器应分层控制：

- 链数与链深；
- communication 和 compute duration 分布；
- compute/communication ratio；
- 初始同时 eligible 的链数；
- 长通信与长 compute tail 的相关性；
- 相同链或相同 duration 的比例。

仓库只保留固定 seed 的代表样例，大规模统计通过生成器完成。不能只生成大量容易实例，再用总体最优率掩盖困难子集。

### 6.2 Adversarial benchmark

至少保留或重新构造以下类别：

- 大 communication 与短期/长期 compute tail 冲突；
- Longest-tail 反例；
- LRPT 对当前通信重复计权的反例；
- SPT/LPT/FIFO 的基本反例；
- top-2 Rollout 候选遗漏反例；
- 有限深 Rollout 的长期收益反例；
- 固定宽度 Beam 剪枝反例；
- tie-break 敏感实例；
- 大量对称链，用于状态压缩测试；
- 使 2-近似上界趋紧的参数化实例。

每个 adversarial case 必须说明攻击对象、关键机制、手算或 Exact 最优值，以及规模扩展方式。

### 6.3 多 job 投影与结构化样例

真实 LLM training DAG 通常不是天然的独立 parallel chain，但多 job 共享瓶颈的部分结构可能经过适当收缩后形成这一模型。本阶段可以使用：

- 从真实 DAG 中抽取的独立链窗口；
- 去除 fork/join 后的单 channel 投影；
- 模拟 micro-batch 重复产生的近似平行链；
- 多个 job 中固定顺序区域的链式投影；
- 具有不同 arrival、通信量和 compute tail 的合成多 job 链；
- 参数来自真实 workload、但结构保持为 parallel chain 的合成样例。

每个投影样例都应说明合并了哪些节点、删除了哪些依赖，以及原问题与链模型之间保留了什么关系。未经证明的投影只能用于形成研究假设，不能据此声称算法已经适用于一般 LLM DAG 或一般多 job DAG。

### 6.4 语义与回归测试

必须覆盖：

- compute 自动开始并与 communication overlap；
- communication 在 compute 事件处暂停和恢复；
- remaining work 守恒；
- 有 eligible communication 时不产生主动 idle；
- 无 eligible communication 时正确计算 forced idle；
- 多个 compute 同时完成；
- 零时长 compute 闭包；
- 同一动作序列重复运行得到相同 trace；
- heuristic schedule 均能被公共 Trace validator 接受。

## 7. 实验设计

### 7.1 算法组

至少比较：

- FIFO、SPT、LPT；
- Longest-delay、Longest-tail、LRPT；
- Event Rollout 的不同候选数和深度；
- Beam 的不同宽度；
- Exact 或严格 lower bound。

### 7.2 指标

小图报告：

- makespan；
- $T_H/OPT$；
- optimal rate；
- mean、P50、P95 和 observed max ratio；
- runtime；
- 抢占次数；
- forced-idle 时间；
- channel utilization。

Exact 无法完成的大图报告：

- makespan；
- $T_H/LB$；
- 不同 heuristic 之间的相对改善；
- runtime 和内存；
- 随规模增长的稳定性。

### 7.3 分层报告

结果至少按照以下维度分层：

- random、adversarial、real/structured；
- 链数和链深；
- compute/communication ratio；
- Exact 可解与不可解；
- 普通实例与专门攻击实例。

尤其应单独观察 $P\approx Q$ 的区域。当通信或计算一方完全占主导时，不同 work-conserving 策略本来就可能接近，不能据此判断 heuristic 已经解决核心选择问题。

### 7.4 反例驱动循环

实验过程应形成闭环：

1. 用 Exact 或自动搜索发现 heuristic gap；
2. 缩小为可手算的最小反例；
3. 解释失败机制；
4. 提出新的候选或搜索增强；
5. 加入固定 regression benchmark；
6. 在完整 random/adversarial suite 上重新评价，检查是否产生新的退化。

## 8. 期望目标

### 8.1 必须完成

1. 当前可抢占 parallel chain 语义与公共模拟器完全一致；
2. 整理 work-conserving 2-近似的正式证明和适用条件；
3. 建立可信的 compact Exact，并给出规模边界；
4. 复核主要基础 priority、Longest-tail、LRPT 和 Event Rollout；
5. 建立 random、adversarial 和结构化测试集；
6. 为主要 heuristic 保存至少一个有解释的失败实例；
7. 给出至少一种多 job 子结构到 parallel chain 的候选映射，并明确尚未证明的部分；
8. 形成可复现的实验报告，不直接复用旧结果数字。

### 8.2 争取完成

1. 得到某个 restricted class 的最优算法或优于 2 的保证；
2. 为 Longest-tail、LRPT 或 Event Rollout 找到参数化下界；
3. 通过对称状态压缩显著扩大 Exact 可解规模；
4. 找到在较低开销下稳定优于 Longest-tail 的有限搜索配置；
5. 明确哪些 parallel-chain 结论可以推广到一般 DAG，哪些不能。

### 8.3 不作为退出条件

- 不要求为一般 NP-hard 问题找到多项式时间精确算法；
- 不要求必须得到小于 2 的一般近似比；
- 不要求在阶段一证明所有多 job 或真实 LLM DAG 都能等价转化为 parallel chain；
- 不要求在阶段一证明真实 LLM workload 的端到端收益；
- 不在本阶段研究 fork/join、多资源或 LLM 特有语义。

## 9. 旧研究结果与复核清单

旧材料位于：

- `docs/old_docs/preemptive研究/preemptive进度.md`；
- `docs/old_docs/preemptive研究/preemptive总结.md`；
- `docs/old_docs/preemptive研究/preemptive规划.md`；
- `docs/old_docs/260804组会.md`。

这些材料提供研究线索和历史结果，但不能替代当前语义下的重新验证。

### 9.1 已有理论结论

旧材料记录了：

1. 单 channel 极化实现与理想线性带宽分配之间的对应；
2. 有 eligible communication 时主动 WAIT 被支配；
3. parallel chain 上任意 work-conserving 调度具有 2-近似安全界；
4. 单次 communication 且共同 release 的 delivery-tail 排序最优；
5. compute lag 全为 0 时任意 work-conserving 调度最优；
6. parallel chain 一般问题的 NP-hardness 规约思路。

需要把这些结论的完整证明、假设和反例从综合旧文档中拆出，形成阶段一独立理论记录。

### 9.2 已有实验观察

旧实验中，21 个 Exact 可解的 parallel-chain 图得到过以下结果：

| 算法 | mean ratio | observed max | 最优率 |
|---|---:|---:|---:|
| FIFO | 1.19795 | 1.86364 | 33.33% |
| SPT | 1.18734 | 1.52174 | 23.81% |
| LPT | 1.25178 | 1.86364 | 14.29% |
| Longest-tail | 1.01605 | 1.21212 | 90.48% |
| LRPT | 1.02526 | 1.21212 | 71.43% |
| Rollout-2 | 1.00000 | 1.00000 | 100% |
| Beam-8/32 | 1.00000 | 1.00000 | 100% |
| Monte Carlo-64（历史对照） | 1.00000 | 1.00000 | 100% |

其中两张图因 Exact 超时没有进入比值统计；旧记录中的 Longest-tail 最坏 observed case 为 `pm_scaled_five_four_s4`：

$$
OPT=33,\qquad T_{LT}=40,\qquad T_{LT}/OPT\approx1.21212.
$$

这些数字只能作为复核目标，不能直接写入新的正式实验结论。需要在模拟器、benchmark 和 Exact 修正后重新生成，并核对：

- 21 图的具体清单和 hash；
- 两个超时图的原因；
- Longest-tail 与 Longest-delay 是否实际使用同一分数；
- Rollout 和 Beam 是否始终保留 baseline incumbent；
- 所有方法是否真正 work-conserving；
- 抢占次数和 trace 是否正确；
- 100% observed optimal 是否只是样本现象。

Monte Carlo 的旧数字如能低成本复现，可以用于确认历史记录没有读取或统计错误，但它不再是阶段一正式算法矩阵的一部分，也不作为阶段退出条件。

### 9.3 已知风险

- 旧 benchmark 和 schema 曾保留 `optional_idle` 字段，不能让它重新引入主动 WAIT；
- 旧代码可能混用静态 tail、residual tail 和包含当前通信的 LRPT；
- 旧 Exact 状态可能遗漏影响未来的 remaining/compute 信息；
- 旧反例可能来自不可抢占语义，必须先确认再迁移；
- 旧实验的随机样例比例可能过高，导致总体最优率过于乐观；
- Rollout/Beam 在有限集合全最优不能解释为 Exact 或理论保证。

## 10. 阶段退出条件

阶段一完成需要同时满足：

1. parallel chain 的输入、状态转移和 trace 通过公共语义测试；
2. NP-hardness 和 2-近似结论已有适用于当前模型的正式说明；
3. compact Exact 与至少一种独立方法或完整枚举在重叠规模一致；
4. Exact 的规模边界、timeout 和 reference 生成规则明确；
5. 主要 heuristic 已完成随机集、攻击集和结构化集实验；
6. 主要经验结论都能对应到固定 benchmark 和可回放 trace；
7. 已给出至少一种多 job 子结构到 parallel chain 的明确候选映射，并列出等价性仍需证明的条件或失败反例；
8. 旧实验结果已经被确认、修正或明确废弃；
9. 已形成阶段总结，说明哪些结论可以带入一般 DAG 阶段。

完成以上条件后，再进入 `stage2_complex_chain.md` 所描述的一般 DAG 研究。
