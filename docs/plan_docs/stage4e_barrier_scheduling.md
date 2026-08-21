# Stage 4e：Barrier 感知调度研究规划

## 1. 阶段定位

Barrier 指 LLM training DAG 中由 pipeline、DP/TP/EP collective、optimizer join 或多个分支汇合形成的同步屏障。Barrier 感知的目标是识别重要同步点被延后的原因，帮助基础 Longest Tail 减少错误选择、降低不必要的计算开销，或为有限 rollout 提供触发信号；它不以“距离 barrier 最近”替代 Longest Tail。

本阶段保留原有计划中的三个核心问题：

1. 如何从当前剩余 DAG 中定位 barrier；
2. 如何找到真正阻塞 barrier 的 communication；
3. 如何设计合适的特征和评分，将 barrier 用作 Longest Tail 的初筛、修正或后加强。

本阶段不预设 barrier 信息必然有用。需要检验的是：它是否只描述局部同步现象，还是能够在统一模拟语义和真实 benchmark 上稳定改善最终 makespan；如果只能在少数条件下有效，也要明确限制适用范围。

现有 barrier 特征、受控 motif、调度入口和实验结果只作为下一步审查时的已有资产，不是本文问题定义和结论的来源。本次工作只编写规划，不进行代码审查或实验。

## 2. 问题定义

在当前调度状态 $s$ 中，公共模拟器给出 eligible communication 或合法的多资源兼容集合。对于候选通信或动作，需要研究其执行后是否：

- 减少某个重要 barrier 的未完成前驱；
- 完成 barrier 的最后一个有效缺口；
- 立即释放 compute 或下一层 communication；
- 缩小不同分支到达同步点的时间差；
- 改变后续关键资源竞争；
- 最终降低整个 DAG 的 makespan。

必须严格区分三个层次：

1. **局部分支推进**：某个前驱或分支更早完成；
2. **同步点推进**：某个指定 barrier 更早 ready 或完成；
3. **全局目标改善**：最终 makespan 降低。

前两个层次不能自动推出第三个。一个局部 barrier 可能不在最终关键路径上；提前完成已经有较大 slack 的分支，也可能对 barrier 到达时间没有影响。

基础目标仍是单 job makespan。multi-job 的 JCT、slowdown 和公平性属于 Stage 4f，不能直接使用本阶段结论。

## 3. 不可改变的公共语义

Barrier 特征、评分和策略必须服从公共可抢占模拟器：

- DAG 依赖采用 finish-to-start；
- ready compute 自动开始、不可抢占，可以并行并与 communication 重叠；
- communication 仅在合法离散事件处暂停和恢复，保留已经完成的工作；
- 有 eligible communication 时必须推进，不存在主动 `WAIT`；
- 单 channel 每次选择一个 communication；
- 固定多资源每次选择资源兼容且 inclusion-maximal 的 communication 集合；
- 固定资源不可迁移、拆分、部分获取或按比例共享；
- 同一时刻完成事件、依赖释放和零时长闭包由模拟器原子处理；
- 算法只能选择动作，不能自行推进时间或修改状态。

所有特征必须从当前 residual state 计算。暂停通信使用剩余工作量，已完成任务不再计入未来负载；不能用初始 DAG 的静态 duration 或静态关键路径替代当前剩余量。

## 4. Barrier 的结构定义

### 4.1 基础结构定义

最基本的 barrier 候选是 residual DAG 中仍未完成、且具有两个或更多未完成前驱分支的 join 节点。该节点可能是 compute，也可能是 communication。研究时至少区分：

- 直接多前驱 join；
- 多条路径在更深层首次汇合形成的间接同步点；
- collective 前后的显式同步结构；
- pipeline 阶段或 micro-batch 汇合；
- iteration 末尾、optimizer 或全局更新汇合；
- 仅由转换器附加顺序边造成、没有真实同步含义的结构 join。

图中多前驱节点只是结构候选，不自动等于性能关键 barrier。正式定义不能依赖任务名称中出现 `barrier`、`sync` 或特定模型字符串，metadata 标记最多用于来源核对和分层，不能改变结构计算结果。

### 4.2 Residual barrier

Barrier 必须随运行状态更新。对已完成前驱、正在运行 compute、暂停 communication 和尚未 ready 的任务分别处理。一个初始多前驱 join 在运行后可能只剩一个未完成分支，此时其含义变成“最后缺口”，而不是继续按初始前驱数评分。

需要记录：

- 当前未完成前驱及其剩余路径；
- 各前驱到达 barrier 的估计或界；
- 已经到达但被其他分支阻塞的分支；
- barrier 完成后可释放的 residual 下游；
- barrier 与后续 barrier、最终 sink 的关系。

### 4.3 Barrier 层级和去重

真实训练 DAG 中可能存在嵌套、连续或共享前驱的多个 barrier。应明确：

- 当前候选关联的是最近 barrier、所有可达 barrier，还是经过筛选的重要 barrier；
- 同一结构由多个路径发现时如何去重；
- 多个 barrier 共享下游时如何避免重复计分；
- 局部 barrier 与 iteration 末端全局 barrier 是否分层处理；
- barrier 数量过多时采用何种有界筛选。

不能简单累加所有可达 barrier 数量，因为深层共享同步点会被多次计数，且距离远的 barrier 未必受当前动作影响。

## 5. 如何识别阻塞 barrier 的通信

候选 communication 与某个 barrier 存在可达关系，并不意味着它正在阻塞该 barrier。需要逐层判断：

1. 候选是否位于某条仍未完成的 barrier 前驱路径上；
2. 候选完成是否能立即或经过确定的自动 compute 链推进该分支；
3. 该分支是否是预计最晚到达或接近最晚到达的分支；
4. 其他分支是否具有足够 slack，使推进当前分支仍然无效；
5. 候选是否还受更早的未完成任务限制，导致本次通信不是实际瓶颈；
6. barrier 本身是否位于当前 residual makespan 的关键区域；
7. 执行候选是否会抢占更重要的通信或占用关键资源，从而抵消局部收益。

“最后一个未完成前驱”是强信号，但不是充分条件：该前驱之后可能仍有长 compute，或者 barrier 下游不影响最终 sink。反之，一个不是最后缺口的通信也可能位于最慢分支上，提前推进有长期价值。

## 6. 候选特征

### 6.1 Longest Tail 基础特征

- 候选自身 remaining work；
- 包含自身剩余工作的 residual tail；
- 排除自身工作后的下游 tail；
- Longest Tail 第一、第二候选的绝对和归一化差距；
- 当前继续运行与发生抢占时的 tail 变化。

应明确 tail 是否包含候选自身，以免 communication duration 被重复计入组合分数。

### 6.2 Barrier 结构特征

- 可达 residual barrier 数量；
- 最近 barrier 的图距离或事件距离；
- 候选是否位于 barrier 的最后未完成前驱路径；
- 候选完成后减少的未完成前驱数；
- barrier 下游 residual tail；
- 候选影响的局部、iteration 末端或全局 barrier 类型；
- 多候选共享同一 barrier 或共享下游的情况。

图距离只能表示结构距离，不能直接解释为时间紧迫性。

### 6.3 分支到达与 slack 特征

- 各未完成分支到达 barrier 的剩余时间估计；
- 最晚和次晚分支的估计差；
- 候选所在分支的 slack；
- 候选完成后预计缩小的到达时间跨度；
- 分支上仍需竞争的 communication 数和固定资源需求；
- 正在运行 compute 的剩余时间对到达估计的影响。

到达时间在存在未来资源竞争时通常只是 heuristic estimate，必须与结构精确量分开标记。不得把估计值写成真实完成时间。

### 6.4 立即释放特征

- 完成候选后立即 ready 的 compute 数和工作量；
- 通过零时长闭包进一步释放的任务；
- 是否立即完成 join 的最后缺口；
- 新增 eligible communication 数；
- 释放任务的 residual tail 和资源需求。

立即释放量需要按下游并集统计，避免同一任务经多条路径重复计分。

### 6.5 资源和抢占特征

- 候选固定资源脚印；
- 所需资源的 residual 负载和热点程度；
- 执行该候选会阻塞的其他 eligible communication；
- 暂停当前通信造成的剩余 tail 增量；
- 预计新增抢占和通信执行区间；
- 多资源动作内部候选的资源互补程度。

热点资源和抢占代价只是解释变量，不自动决定最终关键路径。

## 7. 特征证据等级

每个特征需标注其性质：

- **结构精确量**：由当前 residual DAG 可精确计算，如未完成前驱数、可达关系；
- **状态精确量**：由模拟器状态精确给出，如 remaining work、当前 eligible 集合；
- **启发式估计**：依赖未来 completion policy 或忽略未来竞争，如预计到达时间；
- **来源标签**：来自 workload/转换语义，如 collective role；
- **实验标签**：来自 Exact 或离线反事实结果，只能用于评价，不能作为在线输入。

报告中不能把启发式估计描述成精确事实，也不能让在线算法读取实验标签或 benchmark 分类答案。

## 8. Barrier 信息的三类用法

### 8.1 Longest Tail 前的初筛

先识别明显没有 barrier 影响且不会立即释放关键 compute 的候选，再在保留集合中使用 Longest Tail。初筛必须满足：

- 至少保留 Longest Tail 基础动作，或设置明确的安全保护；
- 不能因没有检测到 barrier 就排除所有候选；
- 过滤规则基于 residual state；
- 单独报告被过滤候选中是否包含最优或最佳已知动作。

初筛的目标可以是降低后续特征或 rollout 成本，即使 makespan 不改善，也可能形成“等质量、低成本”的有效结论。

### 8.2 Longest Tail 的条件修正

以 residual tail 为主排序，仅在差距较小或满足特定条件时加入 barrier 信息。候选形式包括：

- Longest Tail 相近时以最后缺口打破平局；
- 以分支 slack 或预计跨度缩小作次级排序；
- 对能立即释放关键 compute 的候选给予有限修正；
- 将 barrier 下游 tail 作为受控的次级量；
- 多资源时对整个兼容集合计算 barrier 下游并集。

修正应优先使用词典序或有界规则，避免不同量纲任意线性相加。若使用权重，必须说明归一化、调参集、敏感性和 holdout 固定方式。

### 8.3 Longest Tail 后的加强

先由 Longest Tail 产生基础动作，再用 barrier 信号决定是否进行额外比较：

- 生成一个 barrier challenger，与基础动作做深度一评价；
- 把 barrier 信号作为 Stage 4d selective rollout 的触发条件；
- 在多个 Longest Tail 近似等价候选间进行有界前瞻；
- 对多资源候选集合使用 barrier-aware 整集合评分。

额外搜索的收益必须与 barrier 信号本身分开：需要包含相同调用率的随机/周期触发，以及不使用 barrier 的 rollout 对照。

## 9. 明确不作为主算法的路线

Barrier-only 全局排序保留为诊断基线和反例对象，不作为默认候选算法。原因不是预先断言其一定失败，而是 barrier 信息缺少以下保证：

- 最近或数量最多的 barrier 就是最终瓶颈；
- 最后缺口一定比长 residual tail 更重要；
- 提前到达局部 join 一定缩短 makespan；
- 多个 barrier 信号可以安全相加；
- 局部同步收益足以抵消抢占和资源阻塞。

如果实验显示 barrier-only 在特定 motif 上有效，也只能说明该受控机制，不应越过 Longest Tail 条件修正路线直接成为综合策略。

## 10. 单 channel 与固定多资源

### 10.1 单 channel

每个事件选择一个 communication，适合隔离 barrier 信号是否改变候选顺序。首先在单 channel 小图上验证结构定义、last-missing、slack 和 residual tail，避免多资源集合效应干扰解释。

### 10.2 固定多资源

动作是合法且极大的兼容集合。Barrier 评价必须面向整个动作：

- 集合内多个通信的下游取并集；
- 同一 join 或 barrier 只计一次；
- 分别考虑集合的资源互补和阻塞关系；
- 不能先独立给每个通信加分后简单求和；
- 所有候选集合都必须满足 Stage 4c 的动作契约。

正式实验固定 Stage 4c 已验证的候选集合构造。若同时改变 packing 和 barrier 评分，采用正交消融，避免混淆收益来源。

## 11. Ground truth 与因果验证

### 11.1 小图 Exact

在 Exact 可完成的小图上，对每个决策状态记录：

- 所有合法首动作；
- 最优首动作集合及后续最优值；
- Longest Tail 是否最优；
- barrier 候选是否修复或破坏 Longest Tail；
- barrier 到达提前量与最终 makespan 改变量；
- Exact 完成状态、状态数、时间和内存。

只有 Exact 完成时才能称为最优。time limit、state limit 和 feasible completion 必须标为 unknown。

### 11.2 反事实分解

为区分局部与全局效果，在同一状态对候选动作进行统一后续策略回放，记录：

- 目标 barrier 的 ready/complete 时间；
- 下一个重要 barrier 的时间；
- 最终 makespan；
- 后续资源竞争和抢占变化。

使用 heuristic completion 得到的是条件观察，不是 Exact 因果真值。所有候选必须使用相同 completion policy 和预算。

### 11.3 真实大图

大图通常只比较端到端调度结果和受控反事实，不能声称最优。若完整回放超时，保留 unknown，仅报告前缀特征成本或真实切片结果。

## 12. 基线与对照组

正式实验至少包含：

- FIFO 或等价稳定简单策略；
- 固定顺序策略；
- 基础 residual Longest Tail；
- barrier-only，作为诊断下界或失败对照；
- Longest Tail + 初筛；
- Longest Tail + 条件修正；
- Longest Tail + barrier tie-break；
- Longest Tail + barrier 触发 rollout；
- 相同调用率的随机或周期 rollout；
- 小图 Exact 或全首动作枚举。

各策略使用同一模拟器、输入、tie-break、预算和超时规则。多资源策略使用相同 packing 候选规则。

## 13. 数据集分层

### 13.1 受控 motif

只用于隔离 barrier 机制，包括：

- 候选确实是 join 最后缺口；
- 最后缺口不在最慢分支；
- 局部 barrier 不影响最终 sink；
- 两个候选共享同一 barrier 下游；
- 提前 barrier 但抢占关键长通信；
- 深层 barrier 与最近 barrier 给出相反选择；
- 多资源集合共同完成多个独立缺口；
- 静态 tail 与 residual tail 在抢占后产生不同排序。

Motif 不能证明真实训练图中的出现频率或端到端收益。

### 13.2 Real-derived 小图

从 Stage 4a 真实 DAG 截取或缩减，保存来源 hash、截取规则、删除的外部依赖和结构变化。用于检查真实 barrier 形状，并尽量获得 Exact 或首动作标签。

### 13.3 中型真实图

使用统一基线可完成且竞争证据明确的真实 DAG，是正式收益比较主体。按模型族、topology、DP/TP/PP、pipeline 配置、barrier 密度和资源模型分层。

### 13.4 大型真实图

用于测量 barrier context 构建、特征计算、缓存、回放、内存和超时退化。若算法不能完整完成，不比较不完整 makespan。

### 13.5 开发集与 holdout

阈值、权重和筛选规则只在开发/validation 集确定，然后在未参与设计的 workload/topology holdout 上冻结。相同来源的重复 iteration、相邻切片或高度相似配置不得跨集合造成泄漏。

## 14. Barrier census

在算法比较前，对正式真实图统计：

- residual 运行过程中观察到的 barrier 数量和类型；
- barrier 的前驱数、层级、共享和嵌套程度；
- last-missing 状态出现次数；
- eligible communication 中具有 barrier 信号的比例；
- barrier 信号与 Longest Tail 排序分歧次数；
- 分歧状态中不同动作是否改变 barrier 时间；
- barrier 时间变化是否进一步改变 makespan；
- 特征计算时间和内存。

统计需区分完整回放、sampled prefix、真实切片和有界分析。只能在前缀观察到的现象不能写成全图频率。没有检测到 barrier 也可能是定义或预算限制，不能直接解释为真实图无同步。

## 15. 实验设计

### 15.1 定义与特征正确性

在手工图和 real-derived 小图上核对 barrier 定位、未完成前驱、last-missing、下游去重、remaining work 和状态更新。比较结构精确量与启发式估计，确认输出中明确区分。

### 15.2 小图质量

以 Exact 为参照，比较 Longest Tail、barrier-only 和三类 Longest Tail 加强方法，报告首动作最优率、最终 gap、修复次数和引入错误次数。重点计算 barrier 信息对 Longest Tail 的净贡献，而不是只统计成功修复。

### 15.3 中型真实图端到端对照

在固定 manifest 和统一预算下报告 makespan、wall-clock、抢占、forced idle、资源利用率和完整状态。按 barrier 信号是否实际导致动作分歧分层，避免大量无信号状态稀释结论。

### 15.4 减少开销实验

检验 barrier 初筛是否在保持 Longest Tail 或 rollout 质量的同时减少候选数、特征计算或 completion calls。需要同时报告错误过滤率和被过滤的最佳已知动作。

### 15.5 与 Selective Rollout 的接口实验

固定 rollout 候选和深度，只改变触发信号，比较 barrier trigger、Longest Tail 分差、随机和周期触发。该实验只评价 barrier 作为触发器的增量价值，不把 rollout 本身的收益归因于 barrier。

### 15.6 大图成本

测量 barrier 分析随任务数、边数、reachable 子图大小、barrier 数和决策数增长的成本。比较全图重算、局部计算和安全缓存，但任何优化都不能改变动作或 trace。

## 16. 消融要求

至少包括：

1. Longest Tail 与 barrier-only；
2. Longest Tail + last-missing；
3. 加入立即 compute 释放；
4. 加入 barrier 下游 residual tail；
5. 加入分支 slack 或到达跨度估计；
6. 最近 barrier 与筛选后的重要 barrier；
7. 逐候选累加与下游并集去重；
8. 静态量与 residual 量，用于暴露状态错误；
9. 单 channel 候选评分与多资源整集合评分；
10. 初筛、tie-break、分数修正和 rollout trigger；
11. 相同 rollout 调用率的 barrier、随机和周期触发；
12. 有无缓存，验证动作和 makespan 完全一致。

每次只改变一个因素。若同时改变 barrier 定义、权重、packing 和 rollout 预算，结果不能归因于单一组件。

## 17. 失败模式与反例

必须重点检查：

- 最近的局部 barrier 不是最终瓶颈；
- 候选是最后缺口，但另一分支后续 compute 更长；
- 靠近 barrier 的短通信抢占长关键通信，导致 makespan 退化；
- 多个候选共享后继，逐点分数重复计算收益；
- barrier 数量多但全部具有较大 slack；
- 估计到达时间忽略未来通信竞争；
- 一个动作提前当前 barrier，却延迟后续更重要 barrier；
- 多资源集合中高 barrier 分通信互相冲突；
- task role 或名称标记错误地改变结构判断；
- 抢占后继续使用初始 duration，造成 stale score；
- 特征计算成本超过调度收益；
- 初筛误删 Longest Tail 或最佳已知动作。

每个退化样例记录当前 residual state、候选分数、所选动作、barrier 时间变化、最终 makespan 和资源/抢占变化。

## 18. 指标与报告

### 18.1 调度质量

- makespan 及相对 FIFO、Longest Tail 的变化；
- 小图 Exact gap、optimal rate 和首动作命中率；
- Longest Tail 错误修复数、原本正确却被破坏的次数及净值；
- 目标 barrier ready/complete 时间变化；
- barrier 提前但 makespan 不变或恶化的次数；
- 最坏退化和逐样例结果。

### 18.2 行为与资源

- 决策数、barrier 信号出现数和实际动作分歧数；
- 抢占次数、通信执行区间数和 forced-idle 时间；
- 总体及逐资源利用率；
- 多资源动作大小和候选集合数量。

### 18.3 成本与完整性

- 总 wall-clock；
- context 构建、单候选特征、整集合特征和额外 rollout 的分项耗时；
- 特征访问节点/边数量、缓存命中和峰值内存；
- 超时、未完成、fallback 次数及原因；
- 完整率和 unknown 数量。

除平均值外报告中位数、分位数、最坏值和质量—成本曲线。不能只统计发生改善或按时完成的样例。

## 19. 实验执行步骤

1. **冻结协议**：固定 Stage 4a manifest、模拟器版本、Longest Tail 定义、数据划分、预算和 tie-break。
2. **确定结构定义**：在小图上明确 barrier、层级、last-missing 和去重规则。
3. **建立小图标签**：用 Exact 或完整首动作枚举记录 barrier 时间与 makespan 的关系。
4. **完成真实 census**：统计 barrier 出现、Longest Tail 分歧和局部/全局效果链条。
5. **从简单规则开始**：依次研究初筛、tie-break、有限修正，再研究 rollout trigger。
6. **分离评分与搜索**：固定候选和预算，区分 barrier 信息与额外前瞻的收益。
7. **冻结参数做 holdout**：在真实 workload/topology holdout 上验证，保留负面与 unknown。
8. **测量大图成本**：报告时间、内存、超时和安全降级范围。
9. **形成受限结论**：决定 barrier 组件是否、以及以哪种形式进入 Stage 4g。

## 20. 现有资产的使用边界

仓库中已有 residual barrier 特征、候选/集合评分、受控 motif、单/多资源测试和实验 runner。它们可在下一步审查中帮助定位接口和复现旧观察，但本文不假设：

- 当前 join 定义覆盖真实训练中的所有 barrier；
- 当前到达时间、slack 或暂停代价估计已经验证；
- 当前特征不存在共享下游重复计分；
- 当前 barrier score 与 residual Longest Tail 的组合方式合理；
- 当前多资源集合评分始终满足 Stage 4c 契约；
- 当前 runner 的输入、阶段编号、预算和结论口径符合新总纲；
- motif 或旧小图的正结果能够推广到真实 corpus。

下一步代码审查应以本规划和公共语义为依据。本次文档续写不包含代码正确性判断、修改或实验复现。

## 21. 当前证据边界

截至 2026-08-21，能够保留的谨慎背景是：历史探索中 barrier 单独作为全局优先级的证据较弱，因此当前只把它作为 Longest Tail 的条件特征、筛选信息或 rollout 触发信号。这是研究起点，不是已经完成的正式结论。

Stage 4a 的 72-case corpus 主要只有最多 8 个决策点的 sampled-prefix 竞争信息；dp>=2 和大图完整回放受限；Stage 4b 的真实结构规律仍需按证据等级复核。因此目前不能宣称：

- barrier 信号在全部真实 DAG 中普遍存在；
- 检测到 last-missing 就会改善 makespan；
- barrier-aware 已经稳定优于 Longest Tail；
- 现有实现适用于真实大图；
- barrier 组件应进入最终综合算法。

后续文档必须区分计划、假设、观察、结论和 unknown。未完成 Exact、超时回放和前缀观察不能写成全图结论。

## 22. 预期产物

本阶段应形成：

- 固定版本的 barrier 定义、层级和证据等级说明；
- Stage 4e benchmark manifest、数据划分与实验配置；
- 真实 DAG barrier census；
- 小图 Exact/首动作和 barrier 到达时间标签；
- last-missing、slack、下游并集和资源影响的特征消融；
- 初筛、条件修正、tie-break 和 rollout trigger 的统一对照；
- 单 channel 与固定多资源的分别结果；
- 真实 holdout 的质量、成本和最坏退化报告；
- 大图特征计算、内存、超时与 fallback 报告；
- 失败案例及是否进入 Stage 4g 的受限结论。

所有结果保存输入 hash、代码和模拟器版本、机器环境、seed、预算、完成状态和 fallback 原因。benchmark 或公共语义改变后，不直接沿用旧标签、缓存和实验表格。

## 23. 阶段退出条件

只有同时满足以下条件，Stage 4e 才可以结束：

1. barrier、residual barrier、last-missing 和层级定义明确，不依赖不稳定任务名称；
2. 所有精确特征来自当前 residual state，启发式估计被单独标记；
3. 单 channel 和多资源动作均服从公共模拟器及 Stage 4c 合法集合契约；
4. 小图通过手工检查、Exact 或全首动作枚举验证局部 barrier 与最终 makespan 的关系；
5. 正式真实输入来自 Stage 4a 固定 manifest，并按证据与规模分层；
6. 完成 FIFO、固定顺序、Longest Tail、barrier-only 和三类 Longest Tail 加强方法的统一对照；
7. 初筛、条件修正、tie-break 与 rollout trigger 的贡献通过消融分开；
8. barrier 时间提前、makespan 改善和二者不一致的情况均被报告；
9. 共享下游、局部 barrier、slack、热点误导和抢占退化有明确反例；
10. 在未参与设计的真实 workload/topology holdout 上报告净收益、最坏退化和完整率；
11. 特征和额外搜索的 wall-clock、内存、超时与 fallback 未被排除；
12. 明确适用的 workload、pipeline/collective 结构、topology、资源模型、规模和预算；
13. 若只减少开销而不改善 makespan，明确写成等质量低成本结论；
14. 若没有稳定净收益，形成 barrier-only 无效、仅限 tie-break/trigger 或不进入综合算法的否定/受限结论；
15. 只有在统一预算和真实 holdout 上具有可复现净收益的形式，才可作为 Stage 4g 候选组件。

本阶段不以实现 barrier 特征、在合成 motif 上取得正收益或提前某个局部 join 为完成标志。最终必须回答：哪些同步关系真实阻塞训练进度，barrier 信息应以何种受控方式增强 Longest Tail，以及其端到端收益是否值得特征和搜索成本。
