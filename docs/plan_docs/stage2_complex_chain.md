# 一般DAG场景的研究

## 1. 问题定义
对一般DAG进行算法研究，仍然限制在单channel下。

本阶段沿用统一的可抢占执行语义：DAG 依赖为 finish-to-start；compute 在全部前驱完成后自动开始，且不可抢占；communication 可以在任务事件处暂停和恢复，并保留已经完成的工作；所有 communication 共享一个单位容量 channel，被选中的通信独占全部带宽；存在 eligible communication 时必须推进一个通信，不存在主动 WAIT；优化目标仍为最小化整个 DAG 的 makespan。

与阶段一相比，本阶段只放开 DAG 结构，不改变 channel、抢占事件和优化目标。输入不再要求由互相独立的链组成，而是允许：

- 一个节点具有多个后继，形成 fork；
- 一个节点具有多个前驱，形成 join；
- 多层分支在后续重新汇合；
- 多条路径受到共同同步节点或 barrier 约束；
- communication 和 compute 通过跨路径依赖相互影响。

本阶段仍以 compute–communication 交替的一般 DAG 作为标准形式。相邻同类节点在不涉及额外分支、汇合、资源变化或可观察语义时，可以合并其工作量；若一般 DAG 的局部结构使合并不安全，数学推导中可以插入零工作量 dummy 节点来保持交替形式，但不要求 benchmark 实际生成零工作量 communication。任何合并或形式化变换都必须保留节点的 ready 条件、通信工作量、后续计算释放和最终 makespan，不能为了套用阶段一算法而静默地把一般 DAG 链化。

本阶段仍只研究单个联合 DAG 的 makespan，不引入多 channel 的兼容集合选择，也不同时研究多 job 的 JCT、fairness 或 slowdown。真实 workload 中若含多个 job，只能在明确说明目标和依赖保留关系后作为一般 DAG 样例使用。

### 1.1 阶段二新增的困难

阶段一中，每个 eligible communication 都属于唯一链，其完成后的影响可以用该链的剩余后缀描述。一般 DAG 中这一性质不再成立：

- 一个 communication 可能同时推进多个后续分支；
- 一个 communication 即使完成，也可能因为 join 的其他前驱未完成而暂时不能释放任何节点；
- 两条局部形状相同的路径可能连接到不同的外部依赖，因而不具有未来等价性；
- 当前最长路径未必代表最值得优先推进的通信，因为同步点前的 slack 和其他前驱进度会改变其实际影响；
- 某个选择可能短期不释放 compute，却能避免未来 barrier starvation；
- fork 后产生的多条分支会继续竞争同一个 channel，局部的最大 tail 可能忽略后续通信总需求。

因此，阶段二的核心问题是：在当前剩余 DAG 中，如何衡量一个通信完成后对关键路径、分支释放、join 进度和同步等待的真实边际影响。

### 1.2 问题规模参数

除总节点数、communication 数和总工作量外，实验至少区分：

- DAG 深度与最大宽度；
- fork、join 和 barrier 的数量与密度；
- 节点最大入度、最大出度；
- 同时 eligible communication 的数量；
- 关键路径数量以及关键路径之间的重叠程度；
- join 前各分支的长度和 slack 差异；
- communication 与 compute 的工作量比例；
- 重复子图、近似重复子图和真正图自同构的数量；
- 从真实 workload 保留下来的同步层级和跨路径依赖数量。

只按节点数分组不足以说明一般 DAG 的调度难度。

## 2. 探索步骤
1. 进行理论上的探索，不过此部分较为复杂，可以简要探索，得不到有用结果可以暂缓
2. 进行小规模的精确求解，判断精确求解的界限
3. 进行heuristic策略的探索，这是最重要的一部分，需要给予最大的注意。这一部分可以直接测一测上一个阶段的算法，因为已知在旧的探索中上一个阶段的算法表现不错。但是注意，期望的结论仍然是能够在一般DAG上得到更为普适的算法，不要受到一阶段过多的干扰，但是因为一般DAG的信息比平行链要少，我预期不会找到更heuristic的方法，一阶段算法已经较为优异

以上三步不要求完全串行。首先用最小图和可信 Exact 建立评价基础，随后以反例驱动 heuristic 设计；理论探索主要用于确认安全下界、特殊情形和算法边界，不应阻塞主要实验路线。

### 2.1 理论探索

阶段一是阶段二的受限子类，因此在相同抢占事件语义和 makespan 目标下，阶段二至少是 strong NP-hard。没有必要重新寻找一个更弱的复杂性结论。

本阶段优先研究能直接帮助 Exact 或 heuristic 的性质：

1. 确认通信总工作量 $P$ 和忽略 channel 竞争时的最长加权因果路径 $L$ 是否构成安全下界，并给出当前模型下的简洁证明；
2. 研究 join、barrier 和共享后继下更强的 release/demand 下界；
3. 判断哪些特殊 DAG 可以获得最优规则，例如 out-tree、in-tree、单层 fork-join、共同 barrier 或固定宽度 DAG；
4. 为只依赖局部 tail、只依赖最长 residual path 或只依赖立即解锁量的策略构造反例；
5. 检查一般 DAG 上是否仍存在与 work-conserving 相关的统一近似界。

阶段一利用“最后完成链”得到的

$$
C_H\le P+Q\le 2OPT
$$

不能直接推广。fork/join 下的 forced idle 未必能由一条独立链上的 compute 覆盖，因此除非重新得到一般 DAG 的证明，否则不能声称任意 work-conserving 调度仍有相同的 2-近似保证。阶段一的单次 communication delivery-tail 排序、链式 compute 全零解释也只作为待复核的特殊情形，不作为阶段二起点结论。

如果短期内无法得到比安全下界和反例更强的理论结果，可以暂缓一般近似比研究，把主要精力转向 Exact、heuristic 和结构化实验。

### 2.2 小规模精确求解

Exact 的目标不是覆盖中大图，而是为 Stage 2 提供可信 ground truth、发现 heuristic 反例并确定一般 DAG 状态空间的增长边界。

第一版应使用信息完整、便于审查的事件状态，不以压缩率为首要目标。状态需要保留所有会影响未来转移的信息，包括节点完成状态、communication 剩余工作、正在运行的 compute、eligible 或 suspended communication，以及多前驱释放所需的完成信息。所有分支必须调用公共模拟器的同一状态转移，Exact 不自行实现另一套时间推进或 ready 闭包。

研究顺序为：

1. 建立未压缩的 event-state Exact，并与手工枚举或独立极小图 Oracle 对拍；
2. 使用安全的 $P$、$L$ 及经证明的一般 DAG 下界进行 branch-and-bound；
3. 分别测量 memoization、incumbent 和各下界的独立作用；
4. 在观察重复状态后再提出 compact key，并逐字段证明 future-equivalence；
5. 只对完整图自同构或已经证明可交换的模块做对称压缩；
6. 必要时使用 MILP、CP-SAT 或另一种独立 formulation 交叉验证重叠规模。

阶段一的 chain frontier key、相同链多重集压缩和链后缀状态都不能直接作为一般 DAG key。局部形状相同但外部连接不同的子图不能合并。任何时间支配、状态去重或对称规则都必须先证明安全，再进入正式 reference result 生成。

Exact 规模实验至少报告 explored states、去重状态数、剪枝数、峰值内存、runtime、timeout/state limit，以及按 fork/join 密度、宽度和深度划分的可解边界。timeout 不能计为 optimal；未得到 Exact 时，只能相对经过证明的 lower bound 报告 gap。

### 2.3 Heuristic 研究主线

Heuristic 是本阶段的主要研究内容。Stage 1 的 Longest-tail、LRPT、Rollout 和 Beam 应首先作为迁移基线复测，但它们的分数必须按一般 DAG 的当前剩余状态重新定义，不能把“唯一链后缀”换一个名称后继续使用。

#### 2.3.1 基础对照

保留 FIFO、SPT、LPT 作为简单对照，并分别定义：

- Longest-delay：候选通信完成后立即释放的 compute 或任务延迟；
- Longest-tail：候选完成后的 downstream residual tail，不包含当前 communication remaining；
- LRPT：包含当前 communication remaining 的最长 residual path。

三者必须有互不混淆的定义、稳定 tie-break 和能够区分首选动作的 fork/join 样例。所有 residual 信息都从当前状态计算，不能使用初始 DAG 的静态 critical path 冒充运行时分数。

#### 2.3.2 一般 DAG 的候选信息

在基础 residual path 之外，优先分别研究以下信息，而不是一开始就将它们混成复杂加权公式：

- **fork release**：候选完成后会新增多少分支，以及新增分支上的关键 compute/communication；
- **join progress**：候选是否是某个 join 的最后阻塞前驱，或者距离成为最后阻塞前驱还有多少 slack；
- **barrier urgency**：候选所在分支相对同一同步点其他分支的剩余工作和预计到达时间；
- **shared downstream**：多个候选是否通向同一个关键后继，避免对共享 tail 重复计权；
- **critical-path multiplicity**：候选影响一条还是多条当前近关键路径；
- **release gain**：候选完成后真正新增的 ready compute、ready communication 和可重叠计算量，而不是静态后继数量；
- **downstream communication demand**：fork 后各分支还会产生多少 channel 竞争，避免只看最大单路径。

每项信息都先用成对反例确认它能修复哪类错误决策，再进行消融。若新增特征不能在目标攻击集上解释性地改善结果，或只通过改变 tie-break 获益，则不继续堆叠。

可能的组合方式包括字典序 priority、带明确含义的少量加权项，以及先判断同步紧迫性再按 residual path 排序。权重只能通过独立训练集或规则推导确定，不能在正式测试集上反复调参。

#### 2.3.3 Event Rollout

Stage 1 的结果表明，浅层 Rollout 能显著修正单步 priority，但候选数和搜索深度不等价；depth-2 在已测 27 个 Exact 样例上 observed optimal，也仍不构成一般最优性证据。Stage 2 应把这一结果当作配置起点而不是性能结论。

需要比较：

- 由 residual path、join-aware 或混合分数产生 shortlist；
- top-$k$ 与搜索深度的收益和开销；
- baseline completion 使用简单 priority 还是 Stage 2 专用 priority；
- 一次 fork/join 释放与跨多个同步层级的长期收益；
- 固定节点扩展预算和固定墙钟预算下的表现；
- 超时后的确定性 fallback。

Rollout 深度只计算通信选择，forced idle 不占用搜索深度。baseline 首选动作应始终进入候选，避免有限 shortlist 比 baseline 退化。

#### 2.3.4 Beam search

Beam 用于判断更宽的有限搜索能否稳定超过 Rollout，并作为 Exact 不可解图上的较强离线对照。Stage 1 中 Beam-8 与 depth-2 Rollout 在已测集合上均 observed optimal，而更宽 Beam-32 并未单调改善结果且开销明显更高，因此 Stage 2 不能默认“宽度越大越好”。

需要独立研究评分函数、宽度、深度和预算，尤其检查：

- join 尚未闭合时，评分是否过早惩罚短期没有 release 的动作；
- 去重 key 是否完整保留多前驱和共享后继信息；
- 时间支配是否只在同一未来等价状态内使用；
- 固定宽度是否会系统性剪掉需要跨多个事件才能体现收益的分支；
- Beam 更适合作为在线 heuristic、离线 teacher，还是只作为实验上界。

Monte Carlo 不进入 Stage 2 的主要算法矩阵。一般 DAG 具有更强的结构信息和更大的完整轨迹空间，随机采样更难利用 join、barrier 和 residual critical structure。在没有明确新用途前，只保留历史状态，不继续投入调参和实验预算。

### 2.4 Benchmark 与反例

Stage 2 单独建立 random、adversarial 和 real/structured 三层集合，不复用 Stage 1 的 benchmark hash 或 reference result。

#### Random

生成器应控制 DAG 深度、宽度、最大入度/出度、fork/join 密度、barrier 层数、duration 分布、compute/communication ratio、同时 eligible 数量和关键路径重叠。随机图必须保证无环并满足统一语义。仓库只保留固定 seed 的代表样例，大规模统计由生成器完成。

#### Adversarial

至少覆盖：

- fork 后立即释放多段计算，但静态 tail 较短；
- 某分支长期得不到通信而造成 join starvation；
- barrier 前各分支 slack 不均衡；
- 多层 fork-join 中短期 release 与长期关键路径冲突；
- 多个候选共享同一个 downstream tail，导致简单求和重复计权；
- 静态 critical path 与 residual critical path 不一致；
- Longest-tail、LRPT、join-aware 和 release-count 各自的最小反例；
- top-$k$ shortlist 遗漏、有限深 Rollout 和固定宽度 Beam 的反例；
- 大量相似但不真正对称的子图，用于攻击错误状态合并。

每个攻击样例必须含有 fork、join、barrier 或其他一般 DAG 机制，说明攻击对象、失败原因、Exact 最优值和可扩展方式。纯独立链反例继续属于 Stage 1，不应重复计入 Stage 2 的结构证据。

#### Real/structured

Stage 1 的两个 pipeline projection 删除了 cross-chain dependency，只能提供参数来源。Stage 2 的真实投影应尽量保留 micro-batch、pipeline phase、collective completion、同步 barrier 和跨路径依赖，并记录：

- 原 workload 或结构模板来源；
- 合并、删除或收缩了哪些节点和边；
- 哪些 ready time 和同步关系被保留；
- 投影与原问题是等价、上界、下界还是仅参数化类比；
- 是否适合缩小为 Exact 可解的代表子图。

阶段一实例可以作为“受限子类兼容集”运行，用于确认 Stage 2 算法没有破坏链场景，但必须与一般 DAG 的正式结果分开报告。

### 2.5 实验与反例驱动循环

正式实验至少比较简单 priority、重新定义的一般 DAG residual priority、若干经过消融的结构特征、不同深度/候选数的 Rollout、不同预算的 Beam，以及小图 Exact。

指标包括 makespan、相对 Exact 的 ratio、optimal rate、mean/P50/P95/observed max gap、runtime、峰值内存、抢占次数、forced-idle 时间和 channel utilization。结果分别报告 random、adversarial、real/structured，不用总体平均值掩盖攻击集退化。

研究过程继续采用：发现 gap、缩小反例、解释机制、提出单一改动、固化 regression、全套复测的闭环。重点不是不断增加评分项，而是判断一般 DAG 中究竟有哪些结构信息能够稳定改善通信选择。

## 3. 期望目标

### 3.1 必须完成

1. 明确并验证一般 DAG 的 fork、join、同刻事件和 barrier ready 语义；
2. 建立可信的未压缩小图 Exact，并与独立 Oracle 在重叠规模一致；
3. 给出 Exact 可解边界，明确 timeout、state limit 和 reference 生成规则；
4. 重新定义 Longest-delay、Longest-tail 和 LRPT，并为三者建立可区分测试与反例；
5. 至少研究一种 join-aware 或 barrier-aware priority，并完成独立消融；
6. 复测 Stage 1 的 Rollout/Beam 思路，但使用 Stage 2 的 residual score 和完整一般 DAG 状态；
7. 建立 random、adversarial、real/structured 三层 benchmark；
8. 为主要 heuristic 保存有解释、可回放的一般 DAG 失败实例；
9. 给出哪些 Stage 1 结论成功迁移、哪些只复用了框架、哪些被反例否定的阶段总结；
10. 形成可复现的逐例结果和分层报告，不沿用 Stage 1 的 hash、最优率或 reference result。

### 3.2 争取完成

1. 得到某类 fork-join、tree 或固定宽度 DAG 的最优规则或更强界；
2. 找到低开销且稳定优于一般 DAG residual Longest-tail 的策略；
3. 找到 Rollout 深度、候选数和 Beam 宽度的可解释选择原则；
4. 证明一种一般 DAG compact key、模块对称或安全支配关系；
5. 扩大真实 LLM training 结构投影，并找到可由 Exact 校准的代表子图；
6. 判断阶段一算法表现优异是来自 residual critical-path 信息本身，还是来自独立链结构。

### 3.3 不作为退出条件

- 不要求为一般 DAG 找到多项式时间精确算法；
- 不要求必须得到优于阶段一 2-近似界的通用近似保证；
- 不要求 Stage 2 heuristic 在所有图上严格超过 Stage 1 方法；
- 不要求 Beam 或 Rollout 在有限集合上达到 100% observed optimal；
- 不在本阶段研究多 channel 的 compatible-set 选择；
- 不在本阶段混入多 job JCT、fairness 或 LLM 结构特化算法。

## 4. 已有结论

### 4.1 可以直接作为起点的内容

从 Stage 1 可以直接复用：

- 公共可抢占执行语义和事件原子化规则；
- compute 自动闭包、communication remaining 和 forced idle；
- 无主动 WAIT 的 work-conserving 要求；
- Trace 对工作量、依赖、compute 连续性、channel 排他和最终完成的验证；
- 算法只选择合法通信、由模拟器统一执行状态转移的边界；
- random/adversarial/real 分层、timeout 不计 optimal、逐例 hash 和 raw 到 summary 的实验纪律；
- makespan、ratio、runtime、preemption、forced idle 和 utilization 等指标；
- 反例搜索、缩小、解释、固化和回归的研究方法；
- Stage 2 至少 strong NP-hard 的复杂性下界。

这些是模型和研究方法的继承，不代表 Stage 1 的算法效果自动迁移。

### 4.2 Stage 1 提供的经验起点

Stage 1 最新正式集合中有 29 个样例，其中 27 个在既定预算内得到 Exact。动态 Longest-tail 的 mean ratio 为 1.017148，Rollout-2 depth-2 在这 27 个样例上 observed optimal；Beam-8 也 observed optimal，但运行开销更高；更宽的 Beam-32 没有保持单调改善。Stage 1 还发现，增加 rollout 深度与增加 shortlist 宽度并不等价。

这些结果说明 residual tail 与有限前瞻值得优先在 Stage 2 复测，也说明固定浅层搜索存在可构造反例。它们不支持以下说法：

- Longest-tail 在一般 DAG 上仍有相同 gap；
- depth-2 Rollout 或 Beam-8 在一般 DAG 上最优；
- 更宽搜索一定更好；
- Stage 1 的 27 个可解样例覆盖了 fork、join 或 barrier 的困难机制。

### 4.3 必须重新定义或证明的内容

- residual score：从唯一链后缀改为一般 DAG 的当前剩余结构，并处理 fork、join 和共享后继；
- Exact state/key：保留完整完成信息，任何压缩重新证明 future-equivalence；
- Rollout/Beam shortlist：使用 Stage 2 score，不默认 Longest-tail shortlist 有效；
- lower bound 与剪枝：只使用在一般 DAG 上独立证明安全的 bound；
- 对称与支配：只在完整未来等价状态或真正图自同构下使用；
- real projection：保留并标注真实 fork/join/barrier，而不是删除依赖后沿用链结论。

### 4.4 禁止直接外推的内容

- 每条链唯一 frontier 和 chain frontier compact key；
- 相同链多重集对称压缩；
- 由最后完成链推出的 forced-idle 上界与 2-近似证明；
- 单次 communication 的 delivery-tail 排序最优性；
- 阶段一 restricted case 的链式解释；
- Stage 1 heuristic 的 observed optimal rate；
- 删除 barrier 或跨路径依赖后的多 job 独立链等价性。

## 5. 推荐实施顺序

1. 用最小 fork、join、同时完成和 barrier 图确认公共语义与 Trace；
2. 建立未压缩 event Exact，并与独立枚举交叉验证；
3. 冻结三种基础 residual priority 的一般 DAG 定义；
4. 建立第一批包含明确机制的 adversarial 小图；
5. 复测简单 priority、Stage 2 Longest-tail/LRPT 和 depth-1/depth-2 Rollout；
6. 根据反例分别引入 join、barrier、release 等单一结构特征并消融；
7. 在可信 key 的基础上研究 Beam 和 Exact 扩展；
8. 建立 random 和真实投影，生成新的 reference result；
9. 完成分层实验，整理可迁移结论和失败边界。

## 6. 阶段退出条件

阶段二完成至少需要满足：

1. 一般 DAG family 的合法结构、ready 语义和事件原子性已经明确并通过最小样例验证；
2. 所有算法只通过公共模拟器执行，输出均能由独立 Trace validator 回放；
3. 未压缩 Exact 与独立 Oracle 在固定小图完全一致；
4. Exact 使用的每个压缩、支配和下界都有安全性说明；
5. Longest-delay、Longest-tail、LRPT 及新增结构分数具有独立定义、消融和反例；
6. Rollout/Beam 不包含主动 WAIT，不复用有损 chain key，并明确预算与 fallback；
7. random、adversarial、real/structured 三层结果均已报告，reference hash 完整匹配；
8. 主要结论可以追溯到固定 benchmark、Exact 或安全 lower bound 和可回放 trace；
9. Stage 1 的 2-近似、链对称和 observed optimal 结果没有被写成一般 DAG 结论；
10. 已形成阶段总结，说明可进入多 channel 阶段的公共方法，以及仍然依赖单 channel 的结论。

满足这些条件后，再进入多 channel 下的一般 DAG 研究。Stage 3 的新问题是固定资源集合上的兼容通信并行，不能在 Stage 2 尚未校准一般 DAG priority 和 Exact 时提前混入。
