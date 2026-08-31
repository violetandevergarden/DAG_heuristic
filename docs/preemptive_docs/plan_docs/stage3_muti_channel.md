# muti channel场景的研究

## 1. 问题定义
对一般DAG进行探索，把结果扩展到多channel情况。此阶段主要是想在对llm结构探索之前进行一些一般性的探索。

本阶段保留 Stage 2 的一般 DAG、finish-to-start 依赖、compute 自动且不可抢占、communication 可在任务事件处暂停和恢复、零抢占开销、无主动 WAIT 和 makespan 目标，只把单 channel 扩展为固定多资源集合。

设通信资源集合为

$$
\mathcal R=\{r_1,r_2,\ldots,r_m\}.
$$

每个 communication $i$ 在输入中预先关联一个非空固定资源集合 $R_i\subseteq\mathcal R$。通信启动或恢复时必须同时获得 $R_i$ 中的全部资源；暂停或完成时同时释放全部资源。当前不研究动态选路、运行中迁移、部分资源获取或按比例共享带宽。一个通信在占有完整资源集合时按照其给定工作量连续推进。

两个 communication 只有在资源集合不相交时才能并行：

$$
R_i\cap R_j=\varnothing.
$$

因此，每个决策事件的动作不再是选择一个 communication，而是选择一个资源兼容的 communication 集合 $A$。集合内任意两个通信的资源需求均不冲突。为了满足无主动 WAIT，合法动作还必须是 work-conserving 的：不能再向 $A$ 中加入任何当前 eligible 且与集合内全部通信兼容的 communication。这里的要求是集合按包含关系 maximal，不是通信数量 maximum，也不是分数最优；算法要解决的正是在多个 maximal compatible set 之间如何选择。

下一事件可能来自任一并行 communication 完成，也可能来自任一 compute 完成。同一时刻的全部完成事件必须先原子处理，再统一计算新的 ready/eligible 集合并重新选择动作。communication 暂停期间 remaining work 不推进；compute 继续按照 Stage 2 语义自动运行。

### 1.1 阶段定位与研究边界

Stage 3 的作用是在进入 LLM training 结构特化之前，先研究一般 DAG 与固定资源冲突共同出现时的算法问题。它不试图完整描述真实网络协议、拥塞控制或路由，而是把 topology 和路由的结果冻结为每个 communication 的固定资源集合，研究依赖关键性与资源兼容性之间的权衡。

本阶段仍以单个联合 DAG 的 makespan 为基础目标，不同时引入多 job 的 JCT、fairness 或 slowdown。若真实样例由多个训练 job 组成，必须明确说明它们为何被视为一个联合 makespan 实例。

目录名 `muti_channel` 是当前公开 benchmark 格式和 Python 包名，虽然拼写不标准，本阶段不单独改名。

### 1.2 相对 Stage 2 新增的困难

多资源扩展带来两层相互耦合的决策：

1. **单通信优先级**：当多个通信竞争同一资源时，Stage 2 的 residual tail、join/barrier 和 downstream demand 是否仍能区分关键通信；
2. **兼容集合选择**：多个不冲突通信可以同时运行，局部高分通信之间可能互相冲突，而若干单独分数略低的通信组合起来可能覆盖更多关键分支和资源。

把每个 eligible communication 看作一个顶点，资源集合有交集的两个顶点之间连边，可以得到当前状态的资源冲突图。compatible set 对应冲突图中的独立集，work-conserving compatible set 对应 maximal independent set。这个表示有助于描述集合枚举和局部搜索，但 DAG 后继、join、barrier 和 remaining state 仍然决定顶点权重及集合的全局价值，不能只解决一个静态冲突图问题。

主要困难包括：

- 按单任务 priority 贪心装填可能被早期选中的高分通信阻塞多个互补通信；
- 简单累加任务分数可能对 shared downstream 重复计权；
- 占用多个资源的通信可能释放关键路径，但也可能同时阻塞多个热点资源；
- 一个集合的价值不仅取决于任务分数，还取决于资源覆盖、剩余资源碎片以及对不同 join 分支的共同推进；
- 当前并行运行集合和资源占用会影响下一事件及未来动作，Exact 状态不能忽略；
- compatible-set 数量可能随 eligible 数量组合增长，使 Exact、Rollout 和 Beam 的分支远大于单 channel。

### 1.3 问题规模参数

除 Stage 2 的 DAG 深度、宽度、fork/join/barrier 密度和 eligible peak 外，本阶段至少区分：

- 资源总数；
- 每个 communication 所需资源集合的大小；
- 每个资源上的 residual load；
- 热点资源负载的偏斜程度；
- 当前资源冲突图的顶点数、边密度和连通分量；
- maximal compatible set 的数量和最大 compatible-set 大小；
- communication 需求集合之间的重叠模式；
- 多资源通信占全部 communication 的比例；
- 资源冲突与 join/barrier 是否集中在同一批路径；
- 固定 topology 投影中路径长度和热点链路分布。

只报告 DAG 节点数或 channel 数不足以解释算法难度。

## 2. 探索步骤
1. 稍微进行理论上的探索即可，因为这个多channel的定义不是很正式。
2. 再进行小规模的精确求解
3. 再进行heuristic策略的探索，这是最重要的一部分。这里的heuristic又包含两个部分，一个是对于在同一个channel的情况，看看之前的单channel heuristic算法是否还是有效，在多channel场景中能不能找到更为有效的方法；另一个是在多channel场景下，要找到一组能够启动的节点集合，而不只是一个节点，这又是一个算法。此外，上一个阶段有一个heuristic算法在mean上表现得比longest tail好，注意观察这个算法。

以上步骤不要求完全串行。首先用最小资源冲突图和可信 Exact 校准集合动作，再以稳定的资源感知 baseline 为中心研究 heuristic；理论探索主要用于确认复杂性、安全下界、特殊情形和集合选择边界，不应阻塞主要实验路线。

### 2.1 理论探索

Stage 2 是 Stage 3 的受限子类：令所有 communication 都需要同一个资源即可退化为单 channel 一般 DAG。因此，Stage 3 在相同目标和事件语义下至少是 strong NP-hard。

除继承复杂性下界外，可以简要探索以下问题：

1. 单次决策中的带权 compatible-set 选择与 weighted set packing、冲突图独立集之间的关系；
2. 所有 communication 只需要一个资源、资源需求集合两两不交、资源需求呈层次或区间结构时，是否存在更简单规则；
3. 资源冲突图可分解时，哪些分量可以独立选择，哪些仍会通过 DAG join/barrier 在未来耦合；
4. maximal compatible set 与全局最优 schedule 之间是否存在一般近似界；
5. 资源热点、DAG critical path 和同步结构重合时能否得到更强的必要条件或特殊情形结论。

本阶段不要求建立完整的多资源调度理论。若集合选择的经典对应关系不能在当前内生 release、可抢占事件语义下直接给出有用结果，应停止名称类比，转向 Exact 和反例验证。

#### 基础下界

单 channel 的通信总量 $P$ 不再是 makespan 下界，因为资源不冲突的通信可以并行。令资源 $r$ 上的 residual load 为

$$
D_r=\sum_{i:r\in R_i}p_i^{rem},
$$

其中占用多个资源的 communication 在每个所需资源上都计入完整剩余工作。基础资源下界为

$$
LB_R=\max_{r\in\mathcal R}D_r.
$$

再令 $L$ 为忽略资源竞争时的 residual precedence longest path，则基础下界候选为

$$
LB_0=\max(LB_R,L).
$$

该下界需要在当前模型下形成独立说明并与极小图核对后，才能用于 Exact 剪枝。后续可以研究：

- 资源冲突图 clique load；
- 多资源通信形成的 cut 或 demand bound；
- join/barrier 到达窗口中的资源需求下界；
- 热点资源与关键因果路径组合的下界。

所有增强下界都必须先证明安全。对于 Exact 不可解的大图，$[LB,best\ feasible]$ 只表示当前尚未排除的知识区间，区间宽度不是 heuristic gap，更不是 approximation ratio。

### 2.2 小规模精确求解

Stage 3 Exact 的主要用途是生成小图 ground truth、校准 compatible-set policy、搜索集合贪心和资源特征的反例，并判断组合动作带来的规模边界。

第一版使用信息完整的 audit event state，至少保留：

- 全部任务的 status 和 remaining work；
- 正在运行的 compute；
- 当前 active communication 集合；
- 每个资源的占用者；
- 全部影响未来依赖释放的信息；
- 便于独立审计的绝对时间和事件信息。

每个搜索分支对应一个合法的 work-conserving compatible set，并通过公共 simulator transition 推进。Exact 不自行维护另一套资源占用、抢占或依赖闭包。

研究顺序为：

1. 建立未压缩 set-event Exact；
2. 与独立 tick/set 枚举 Oracle 在极小图交叉验证；
3. 枚举全部 maximal compatible set，记录动作数量和生成开销；
4. 加入经过证明的逐资源 load 和 precedence lower bound；
5. 研究冲突图回溯、支配剪枝和安全的连通分量分解；
6. 逐字段证明 normalized key 的 future-equivalence；
7. 在必要时使用另一种 MILP/CP-SAT formulation 交叉验证重叠规模。

Stage 2 的 normalized key 证明不能直接照搬。若 active allocation 或资源占用不能由 task status 唯一重建，就必须显式进入 key。只有资源占用、剩余任务和全部未来释放信息等价的状态才能去重或使用时间支配。

Exact 规模实验至少报告：explored states、generated transitions、每状态 compatible-set 数量、set 枚举时间、去重与剪枝数量、peak memory、runtime、timeout/state limit。应分别改变资源数、冲突密度、需求集合宽度、eligible peak 和 DAG 同步层级，而不是只按节点数扫描。

### 2.3 Heuristic 研究主线

Heuristic 是本阶段的主要研究内容。研究应把“如何评价单个通信”和“如何由单任务信息构造集合”分开消融，避免一个结果同时混入 priority 与 packing 两种变化而无法解释。

#### 2.3.1 稳定 baseline：资源感知 Longest-tail 贪心装填

第一条 baseline 可以按当前 residual Longest-tail 对 eligible communication 排序，依次加入与已选集合资源不冲突的通信，最后确定性地补全到 maximal compatible set。该策略保留 Stage 2 最稳定的单任务分数，同时给出合法、确定、低开销的多资源动作。

需要明确：

- Longest-tail 是否包含当前 communication remaining；
- 暂停通信与新 ready 通信如何稳定 tie-break；
- 多资源通信在排序相同时如何处理；
- 贪心结束后是否确实不能再加入任何 eligible communication；
- 集合顺序是否只影响构造，不影响同一时刻并行启动语义。

FIFO、SPT、LPT、Longest-delay 和 LRPT 也可以使用同一 greedy-fill 框架形成基础对照。这样能够单独观察 Stage 2 单任务 priority 在固定集合构造下是否仍有效。

#### 2.3.2 资源感知单任务特征

Stage 2 的 `downstream_demand` 在 38 个一般 DAG 小图上比 Longest-tail 有更好的 mean ratio 和 observed optimal rate，但 observed worst 更差。因此它值得重点迁移，却不能直接替代 Longest-tail。

在 Stage 3 中，应把标量 downstream communication demand 扩展为资源向量或热点资源信息，例如：

- 候选下游在每个资源上的 residual demand；
- 下游最大热点资源 load；
- 候选自身占用资源与下游热点的重合程度；
- 候选完成后释放的分支分别需要哪些资源；
- join/barrier 各分支到达前的资源瓶颈和 slack；
- 某通信是否阻塞了多个未来可并行的资源分量。

这些特征必须分别验证 mean、worst regression 和结构反例。Stage 2 中表现较差的 barrier-aware、structure-aware 字典序堆叠不直接迁移；它们说明多个直觉特征简单相加或排序可能显著退化。

#### 2.3.3 Compatible-set 构造

至少比较三类方法：

1. **按任务 priority 贪心装填**：成本低，作为部署 baseline；
2. **带权冲突图选择**：把 residual/资源特征作为顶点权重，在预算内求较高权独立集，再补全为 maximal；
3. **直接对 compatible set 评分**：评价集合联合影响，而不是简单相加单任务分数。

集合分数可以依次研究：

- 集合覆盖的 downstream 子图并集，避免 shared downstream 重复计权；
- 对多个关键 join/barrier 分支的互补推进；
- 对热点资源的释放与占用平衡；
- 集合完成后预计新增的 ready compute/communication；
- 集合诱导的下一事件时间和可重叠 compute；
- 未使用资源是否形成无法装入其他 eligible 通信的碎片。

还应研究从 greedy set 出发的局部交换，例如删除一个高分多资源通信后加入两个或多个互补通信。每种改动都必须对应明确反例，不不断堆叠无解释的 bonus。

需要特别区分：maximal set 只保证当前没有可直接追加的通信，并不保证最大 cardinality、最大总分或全局 makespan 最优。模拟器负责验证合法与 work-conserving，算法负责在多个合法集合之间优化。

#### 2.3.4 Compatible-set Rollout

Stage 2 的 receding-horizon Rollout、depth 定义、memoized completion、预算和 fallback 框架可以迁移，但每层分支单位改为 compatible set，baseline completion 也必须是确定性的 work-conserving set policy。

优先比较：

- greedy LT set baseline 与 set Rollout；
- 只改变第一个 compatible set 的 depth-1；
- 能跨多个集合决策观察 join/barrier 投资的 depth-2；
- top-$k$ set 候选与更深 horizon；
- 单任务 shortlist 后组合与直接 set shortlist；
- 固定 expanded-node、set-count 和 wall-clock 预算。

Stage 2 的 top-2 depth-2 在 38 个小图上 observed optimal，但在 100 节点压力图上平均约 5.8 秒。Stage 3 的集合分支更大，因此第一版就必须设置硬预算、增量或 memoized completion，以及确定性 fallback。主要评价应是 candidate 相对稳定 baseline 的 primal 改善、持平和退化，而不是依赖宽松 lower bound 排名。

forced idle 不消耗通信选择深度。baseline 动作必须进入候选集合，预算耗尽时返回 baseline 或当前 best feasible，不能把未完成搜索标成最优。

#### 2.3.5 Beam 与其他搜索

Beam 只作为实验上界或离线 teacher，不作为部署候选，也不把寻找固定宽度反例列为 Stage 3 退出条件。如果保留，需要使用已经证明 future-equivalent 的 Stage 3 key，并明确 width、horizon、预算和 fallback。

Monte Carlo 不进入 Stage 3 主算法矩阵。多资源下完整轨迹和 compatible-set 空间更大，随机采样更难利用明确的 DAG 与资源冲突结构；除非后续出现新的独立用途，否则只保留历史代码状态。

### 2.4 Benchmark 与测试

Stage 3 必须建立独立的 random、adversarial 和 real/structured 集合。每个 communication 的固定资源集合必须作为自包含输入，算法不能根据 metadata、reference result 或外部 topology 临时推断。

#### Random

随机生成器应联合控制：

- DAG width/depth、fork/join/barrier 密度；
- 资源数与每任务资源集合大小；
- 单资源和多资源通信比例；
- 资源冲突图密度、最大 compatible-set 大小和 maximal set 数量；
- 热点资源负载及负载偏斜；
- 高 residual tail 是否集中在同一热点资源；
- join/barrier 分支是否使用相同或互补资源；
- communication/compute duration ratio。

仓库只保存固定 seed 的代表图，大规模压力实验运行时生成，不无限增加 JSON。

#### Adversarial

至少覆盖：

- 多个高 tail 通信互相冲突，而多个次高 tail 通信可以并行；
- greedy maximal set 被首个多资源通信阻塞的集合互补性陷阱；
- maximal cardinality 与最优 makespan 不一致；
- 通信必须原子获取多个资源，部分获取会产生错误结果；
- join 的不同分支落在不同热点资源；
- barrier urgency 与资源负载发生冲突；
- shared downstream 在集合求和中被重复计权；
- 单任务 downstream demand 平均改善但 worst regression 的多资源放大；
- 当前资源利用率更高但延迟关键同步的反例；
- top-$k$ compatible-set omission 和有限深 Rollout 反例；
- 冲突图看似可分解、但未来通过 DAG join 重新耦合的反例；
- active allocation 被错误从 Exact key 删除的状态碰撞。

每个 adversarial case 必须记录攻击对象、关键机制、Exact 最优值和参数化扩展方式。

#### Stage 1/2 compatibility

把所有 communication 的资源集合设为同一个资源时，Stage 3 应与 Stage 2 完全等价；Stage 1 的独立链又是其中更小的子类。应保留少量 compatibility 图验证迁移，但这些图必须从 Stage 3 正式多资源统计中分离，不能用大量单资源样例提高 observed optimal rate。

#### Real/structured

真实多资源投影必须显式提供 topology，并说明每条 communication 的路由如何被冻结为资源集合。至少记录：

- workload 与 topology 来源；
- 资源代表链路、端口、共享瓶颈还是更高层抽象；
- communication 到固定 resource set 的映射方法；
- 是否合并或删除了节点、边和资源；
- 路由固定后保留了哪些依赖与同步关系；
- collective 的可抢占粒度和多资源同时占用假设；
- 投影是等价模型、松弛、上界/下界还是 synthetic motif。

没有 topology 时不得虚构真实多 channel 结论。Stage 2 的 synthetic motif 可以作为 DAG 骨架或参数来源，但不能直接标为真实多资源结果。

#### 语义与回归测试

至少覆盖：

- 两个资源不冲突的 communication 同时推进；
- 两个资源冲突的 communication 不能并行；
- 多资源 communication 同时获取和释放全部资源；
- communication 在 compute 或其他通信事件处暂停、恢复且 remaining 守恒；
- 同刻多个 communication/compute 完成后的原子闭包；
- compatible set 必须 maximal，但不要求 maximum cardinality；
- 无任何可运行 communication 时的 forced idle；
- Trace 逐区间验证全部资源容量不超过 1；
- 同一动作集合序列得到确定 trace；
- Exact、priority、Rollout 输出均通过独立 Trace 回放。

### 2.5 实验与评价

#### Exact 可解小图

报告 Exact status、states、runtime、peak memory、每状态 compatible-set 分支数和 timeout。对每种 heuristic/search 报告 makespan、相对 OPT 的 ratio、optimal rate、mean/P50/P95/observed max gap、runtime、抢占次数和集合大小。

从 baseline 失败图中提取资源冲突、集合互补、join/barrier、shared downstream 和跨多次决策投资等标签，用于指导大图风险检查，但不把 observed pattern 写成因果定理。

#### Exact 不可解中大图

主指标是 candidate 相对稳定 baseline 的 primal 改善、持平率、退化率、worst regression 和 runtime。辅助报告 $[\max(LB_R,L),best\ feasible]$ 知识区间，但不把区间宽度当成算法 gap。

资源指标至少包括：

- 每个资源的 busy time 和 utilization；
- 热点资源利用率与 idle 时间；
- 平均、P95 和最大并行 compatible-set 大小；
- 未使用资源数量及资源碎片；
- 多资源通信等待和抢占次数；
- set 枚举、评分和 Rollout expanded nodes；
- baseline/candidate 的运行时间和预算 fallback 次数。

平均资源利用率可能掩盖热点与碎片，因此必须同时报告逐资源或分位数统计。random、adversarial、real/structured 分层报告，不能用大量随机图稀释攻击集退化。

### 2.6 反例驱动循环

研究过程继续采用：

1. 用 Exact 或自动搜索发现 greedy/set policy gap；
2. 缩小为可手算的资源冲突图与 DAG；
3. 判断失败来自单任务 priority、集合构造还是前瞻不足；
4. 一次只引入一种资源或 DAG 特征；
5. 固化为 adversarial regression；
6. 在完整 random/adversarial/real suite 上复测 mean 与 worst；
7. 若改善只来自额外预算，单独报告搜索成本，不解释为特征有效。

## 3. 期望目标

### 3.1 必须完成

1. 明确固定多资源 communication、兼容集合和 work-conserving 的目标语义；
2. 模拟器与 Trace 正确处理并行 communication、完整资源获取、暂停恢复和同刻事件；
3. 建立可信的未压缩 set-event Exact，并与独立小图 Oracle 一致；
4. 给出逐资源 load 与 precedence path 基础下界的安全说明；
5. 建立至少一个确定、低开销的资源感知 baseline；
6. 分开研究单任务 priority 与 compatible-set 构造，至少包含 greedy 和一种能处理集合互补性的方法；
7. 将 Stage 2 `downstream_demand` 扩展为资源感知候选，并同时报告 mean 与 worst；
8. 实现带硬预算和确定性 fallback 的 compatible-set Rollout；
9. 建立 random、adversarial、real/structured 及单资源 compatibility benchmark；
10. 在小图 Exact 和中大图 primal 两种口径下完成分层实验；
11. 为主要 baseline 和集合策略保存有解释、可回放的失败实例；
12. 总结哪些方法可以进入 LLM training 结构特化阶段，哪些结论仍依赖当前固定资源抽象。

### 3.2 争取完成

1. 得到某类资源需求结构或冲突图上的最优集合规则；
2. 证明安全的 compatible-set 支配、冲突图分解或 normalized key；
3. 找到在低开销下稳定超过 LT greedy-fill 的集合策略；
4. 得到 adaptive rollout budget 或增量 completion，使中图搜索可用；
5. 建立一个保留真实 topology、路由和同步关系的可追踪投影；
6. 识别 LLM training 中可用于下一阶段的资源重复、collective、pipeline 和 barrier 结构。

### 3.3 不作为退出条件

- 不要求形式化覆盖真实网络中的动态路由和拥塞控制；
- 不要求找到一般多资源问题的多项式时间精确算法；
- 不要求得到统一常数近似比；
- 不要求某个 Stage 2 priority 在所有多资源图上继续占优；
- 不要求 Rollout 或 Beam 在有限样例上达到 100% observed optimal；
- 不把寻找固定宽度 Beam 反例作为退出条件；
- 不在本阶段研究多 job JCT、fairness 或完整 LLM 专用调度语义。

## 4. 已有结论

### 4.1 可以直接复用的内容

从 Stage 1/2 可以直接复用：

- finish-to-start、compute 自动且不可抢占、communication remaining 和任务事件原子化；
- 无主动 WAIT 的原则；
- 公共 simulator 作为唯一 transition，算法只选择合法动作；
- Trace 的工作量、依赖、compute 连续性和最终完成验证框架；
- Exact timeout/state limit 不计 optimal、reference 记录 hash 与 Oracle 状态的纪律；
- residual score 从当前 remaining state 计算、稳定 tie-break、不读取 metadata/reference；
- random/adversarial/real 分层及 raw 到 summary 的实验方式；
- 小图用 Exact ratio、大图用 primal 改善与知识区间的评价口径；
- 反例搜索、缩小、解释、固化和回归的研究循环。

Trace 在 Stage 3 必须新增逐资源排他和完整资源集合同时占用验证；动作也由单通信改为 work-conserving compatible set。因此这里复用的是框架，而不是原样沿用单 channel 实现。

### 4.2 Stage 1/2 提供的经验起点

Stage 1 说明 residual Longest-tail 与有限前瞻在独立链上值得研究，但其 chain frontier、相同链对称和任意 work-conserving 2-近似证明依赖单 channel 独立链，不能进入 Stage 3 理论结论。

Stage 2 的正式 38 个一般 DAG 小图中：

- Longest-tail observed optimal rate 为 84.21%，mean ratio 为 1.010315；
- downstream demand observed optimal rate 为 92.11%，mean ratio 为 1.006512，但 observed worst 为 1.111111，差于 Longest-tail 的 1.095238；
- Rollout tail top-2 depth-2 为 38/38 observed optimal，相对 LT 改善 6 图、持平 32 图、没有 observed 退化；
- Beam-8 得到相同 observed makespan，但开销更高，只定位为实验上界；
- Longest-tail 的 6 个失败图都含 join 或 barrier，其中一例需要跨两次通信决策投资。

这些结果支持把 LT 作为稳定 baseline、把资源化 downstream demand 作为重点候选、把 depth-2 Rollout 作为有预算研究起点。它们不能说明这些方法在 compatible-set 动作空间中仍有相同比率或最优率。

Stage 2 压力实验还表明，Rollout 在 100 节点图上平均约 5.8 秒，而改善只出现在 45 个压力图中的 4 个。Stage 3 分支更大，因此不能默认将无预算 Rollout 作为在线策略。

### 4.3 必须重新实现或证明的内容

- 合法动作：从单个通信改为 work-conserving compatible set；
- forced idle：按是否存在可运行 communication 判断，不复用单 channel 的简单 eligible 判定代码；
- Trace：加入逐资源排他和完整固定资源集获取；
- Exact key：保留或可重建 active allocation 与 resource occupancy；
- lower bound：由单 channel 总通信量改为最大逐资源 residual load；
- priority：从单任务排序扩展到集合构造和集合互补性；
- downstream demand：由标量扩展为资源向量或热点资源需求；
- Rollout/Beam：每层分支改为 compatible set，并使用 Stage 3 key、预算和 baseline completion；
- utilization：从单一标量改为逐资源、热点和碎片统计；
- real projection：必须由显式 topology 和冻结路由生成固定 resource set。

### 4.4 禁止直接外推的内容

- 单 channel 极化后的“每次只选一个通信”；
- 通信总量 $P$ 作为多资源 makespan 下界；
- Stage 2 Longest-tail、downstream demand 或 Rollout 的 observed optimal rate；
- 单任务分数最高即代表集合最优；
- Stage 2 normalized key 和时间支配证明；
- Stage 2 Rollout 的复杂度与默认参数；
- Beam-8 observed optimal 所暗示的鲁棒性；
- 单 channel utilization 对多资源效率的解释；
- 删除 topology、路由或资源冲突后的真实多 channel 声明。

## 5. 推荐实施顺序

1. 冻结 fixed-resource-set 输入和通信原子占用语义；
2. 用最小冲突、不冲突、多资源获取和同刻完成样例校准 simulator/Trace；
3. 定义并测试 work-conserving compatible-set 合法动作；
4. 建立未压缩 set-event Exact 和独立小图 Oracle；
5. 实现 LT greedy-fill baseline，并加入 Stage 2 单资源 compatibility 对拍；
6. 建立 greedy set trap、资源互补和 join/barrier 热点等 adversarial 小图；
7. 比较资源化 downstream demand、带权集合选择和直接 set score；
8. 实现有硬预算的 compatible-set Rollout，默认回退到稳定 baseline；
9. 证明并启用必要的 normalized key、下界和安全剪枝；
10. 建立参数化 random 与 topology 驱动的 real/structured benchmark；
11. 完成 small-Exact、large-primal、逐资源指标和风险结构报告；
12. 整理可进入 LLM training 结构特化阶段的算法接口与结构假设。

## 6. 阶段退出条件

阶段三完成至少需要满足：

1. fixed resource set、全资源原子获取、暂停恢复和无动态路由的语义已经冻结；
2. simulator 能在同一时间并行推进兼容通信，并在同刻事件后原子重算合法集合；
3. work-conserving 由 simulator 验证，算法不维护第二套资源占用状态；
4. Trace 通过工作量、依赖、compute 连续性、逐资源排他和完整资源获取检查；
5. Exact 与独立 set/tick Oracle 在固定小图一致，timeout 不进入 optimal 分母；
6. normalized key 对 active allocation 和 resource occupancy 的处理具有书面 future-equivalence 说明；
7. 至少一个稳定 baseline 和一个处理集合互补性的资源感知候选完成评价；
8. compatible-set Rollout 有硬预算、可审计统计和确定性 fallback；
9. random、adversarial、real/structured 与单资源 compatibility 结果分层报告；
10. 大图报告 candidate→baseline primal 改善/退化、$[LB,best]$ 知识区间和逐资源利用率；
11. Stage 2 的 $P$ 下界、单任务排序和 observed optimal rate 没有被写成多资源结论；
12. 已形成阶段总结，明确哪些固定资源规律可用于 Stage 4，哪些真实 LLM 假设仍需单独验证。

满足以上条件后，再进入 LLM training DAG 的结构特化研究。仅给 benchmark 增加 resource 字段，再按单 channel priority 顺序运行通信，不构成 Stage 3 的完成。
