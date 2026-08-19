# 可抢占阶段 5：利用 LLM Training DAG 重复结构的研究计划

> **后续主线说明（2026-08-13）：** 本文保留为阶段 5 的重复结构研究方案。后续研究仍基于
> `260804组会.md` 的抽象 DAG，不以 pipeline 编排或 ZB 为中心。训练 DAG 和 compute order
> 固定，算法研究 ready communication 的组合排序与状态空间压缩。新的执行计划见
> `preemptive阶段7_LLM结构化DAG调度算法研究计划.md`。

## 一、研究目标

本阶段不再继续堆叠通用 priority，而是研究下面这个问题：

> LLM training 在 micro-batch、GA、iteration、replica 和 pipeline stage 上具有高度重复的 DAG 模板。能否只搜索一个较小的“模板调度/周期策略”，再安全地扩展到完整 DAG，并在考虑重复单元之间相互影响后，取得接近通用 Rollout/Beam 的解质量和明显更低的搜索开销？

当前仍采用理想可抢占模型：通信进度可以保留、切换无开销、事件发生时可以重新选择 flow，单通道把全部带宽交给一个 flow，多资源场景选择资源兼容的 flow set。真实 collective 的最小抢占粒度和切换代价作为后续鲁棒性实验，不混入本阶段第一轮结构研究。

本阶段主要输出四类结果：

1. 不同并行维度和 PP 策略下的 DAG 重复性、差异性和耦合强度报告；
2. 可以跨 micro-batch/iteration 复用的规范化 motif 和 phase 模板；
3. 利用重复结构的压缩搜索与周期调度算法；
4. “什么时候可以复制局部编排、什么时候必须联合重规划”的判定指标和反例。

## 二、对整体思路的判断

### 2.1 有价值的部分

LLM training 的重复性确实比一般 DAG 强得多，并且存在多个尺度：

```text
layer 内 collective step
  -> 同一 stage 内的 layer 模板
  -> 多个 micro-batch / GA
  -> pipeline steady-state 周期
  -> 多个 iteration
  -> 多个 epoch
```

这种重复性可以同时用于两件事：

- **压缩问题规模**：把只差 micro-batch、replica 或 rank 编号的状态合并；
- **复用决策**：离线搜索一个 phase-conditioned 策略表或短周期，然后在后续重复位置复用。

此前结构审计也给出了直接证据：去掉 micro-batch 后，扫描过的混合 DAG 中所有任务都能归入重复模板，最大模板重复次数达到 16；ready frontier 相对总图很小。因此，对称状态压缩、周期策略和短窗口搜索是合理方向。

### 2.2 必须避免的简单化

“每个重复块独立求解，再把答案复制若干次”通常不成立。即使两个 micro-batch 子图同构，它们仍可能通过以下方式相互影响：

1. 共用同一个 channel、NIC 或链路；
2. PP 使前一个 micro-batch 的通信决定后一个 stage 的 release time；
3. DP bucket、optimizer join 和 iteration barrier 聚合多个重复单元；
4. 一个单元结束时可能留下未完成的 deferred flow，形成下一单元的 carry-in state；
5. warmup、steady、cooldown 的边界状态不同；
6. EP 的 token 路由使相同结构具有不同通信量。

因此，本阶段采用“**模板压缩 + 耦合图 + 滚动修正**”，而不是静态 DAG 分块。

## 三、按并行维度分别研究

### 3.1 PP：决定整体 release pattern 的主骨架

PP 是第一优先级，因为它决定 F/B/W、activation send、gradient send 的释放顺序以及 warmup/steady/cooldown 结构。

计划扫描 SimAI 中已有的：

- 1F1B；
- Interleaved 1F1B / VPP；
- Zero Bubble；
- Bidirectional / Chimera；
- DualPipe；
- 必要时加入 GPipe 作为结构对照。

对每种策略改变：

- `PP = 2, 4, 8`；
- `GA = PP, 2PP, 4PP`，并加入少量非整数倍形状；
- local layer 数和 virtual chunk 数；
- compute/communication ratio；
- 同构 stage 与异构 stage profile。

需要提取：

- 每个 rank 的 F/B/W token 序列；
- warmup、steady、cooldown 的起止位置；
- steady-state 的最短重复周期；
- 相邻 micro-batch 模板之间的依赖边；
- backbone flow 的 release 间隔；
- deferred W/DP flow 的 slack 和 deadline；
- critical backbone 在 stage、micro-batch、phase 之间的切换次数。

PP 的目标不是只得到一个 pipeline 名称对应的固定顺序，而是得到：

$$
\pi_{PP}(phase, stage, microbatch\bmod k, residual\ summary).
$$

其中 $k$ 是检测到的周期，`residual summary` 用于处理上一个周期留下的未完成通信。

### 3.2 DP：具有 deadline 的重复 side work

DP 通常不决定前向/反向主骨架，但 gradient bucket 会在反向过程中逐步释放，并在 optimizer 或下一 iteration 前形成 barrier。

单独研究：

- `DP = 2, 4, 8`；
- bucket 数、bucket 大小和释放间隔；
- 与 backward compute 的 overlap；
- 所有 bucket 必须完成的 optimizer deadline；
- 不同 replica 间的对称性。

重点验证两个假设：

1. 同一 bucket 在不同 replica 上可以按计数压缩；
2. DP 可以作为 deferred work 填补 PP backbone 的空档，但必须在 latest-start time 前晋升。

定义动态 slack：

$$
slack_i(s)=D_{opt}(s)-t(s)-LB_i(s),
$$

其中 $D_{opt}$ 是 optimizer barrier 的预测时刻，$LB_i$ 是从当前状态完成该 DP collective 及其后继的下界。该值只用来生成候选，最终仍由端到端 rollout 评价。

### 3.3 TP：单独可调度空间较小，但不能从组合模型删除

TP collective 通常紧跟每层 compute，并位于关键路径上，单独调整顺序的自由度有限。因此不把“纯 TP 专用调度器”作为主要目标。

但 TP 必须保留在组合实验中，因为它会：

- 占用机内 NVLink/NVSwitch 资源；
- 形成 collective fan-out/fan-in join；
- 改变 PP/DP flow 的 release time；
- 在拓扑或 NIC 共享时与跨机通信产生干扰。

TP 单独分析主要输出：关键路径占比、零 slack 比例、collective 同步边界和资源占用模板。若 TP 与跨机流完全资源隔离，则把它吸收到 compute/release profile；若共享 NIC/链路，则保留为显式竞争任务。

### 3.4 EP：结构重复、流量随机

EP 具有 layer/expert-group 级重复结构，但每个 iteration 的 token-to-expert 路由可能不同，因此不能假设 duration 完全周期化。

EP 分成两层表示：

- 固定结构：dispatch、all-to-all、expert compute、combine 及其依赖；
- 随机参数：每个 expert/token group 的实际流量。

计划使用三类流量：均匀、受控偏斜、从 trace/AICB 得到的真实分布。EP 策略应复用结构策略而不是固定时间表，并在事件处根据实际 remaining work 修正。

需要额外报告负载偏斜：

$$
imbalance=\frac{\max_e bytes_e}{\operatorname{mean}_e bytes_e}.
$$

这可以判断某个周期策略失效是因为结构耦合，还是因为 MoE 路由漂移。

## 四、从单维度推广到组合配置

### 4.1 不做完整笛卡尔积扫描

完整枚举 TP×DP×PP×EP、GA、pipeline mode、placement 和模型规模会迅速爆炸。采用三层采样：

1. **单因素扫描**：固定其他维度为 1，识别每个维度自身结构；
2. **两两交互扫描**：PP×DP、PP×TP、PP×EP、DP×EP；
3. **代表性 3D/4D 配置**：固定总 GPU 数，选择若干常见与冲突较强的配置。

建议第一批组合使用 `(TP, DP, PP, EP)`：

```text
(1, 4, 4, 1)   PP × DP
(4, 1, 4, 1)   PP × TP
(2, 2, 4, 1)   典型 3D
(4, 2, 4, 1)   更高 TP 的 3D
(2, 2, 4, 2)   含 EP 的 4D
```

配置的目的不是代表所有模型，而是分别制造：资源隔离、NIC 共享、DP 尾部拥塞、PP wave 冲突和 EP 偏斜。

### 4.2 placement 与拓扑必须作为实验变量

同一个并行配置在不同 placement 下，结构 DAG 相同但资源冲突图可能完全不同。至少比较：

- TP group 完全机内、DP/PP 跨机；
- PP 相邻 stage 同机或跨机；
- DP 与 PP 是否共用 NIC/uplink；
- EP group 是否跨机架。

对每个配置同时保存：typed DAG、flow route/resource set、无争用 critical path、每资源负载和冲突图。这样才能区分收益来自 DAG 重复还是拓扑偶然隔离。

## 五、重复结构的形式化表示

### 5.1 规范化 motif signature

任务不使用具体 ID，而使用：

```text
(parallel_dim, collective_id, stage, phase, local_layer,
 virtual_chunk, role, relative_microbatch, route_class, size_class)
```

将绝对 micro-batch、replica、rank 编号替换成相对偏移或等价类。两个子图只有在以下内容一致时才算同一个 motif：

- 节点角色和依赖结构；
- 通信资源集合或 route class；
- duration 相同或属于允许的参数化 size class；
- 对外入口/出口接口一致。

需要区分三个重复率：

$$
R_{struct},\quad R_{resource},\quad R_{timing}.
$$

分别表示结构同构、连同资源映射同构、连同 duration/release profile 也近似相同。只有 $R_{timing}$ 高时才适合直接复用时间策略；只有 $R_{struct}$ 高时，只能复用策略结构。

### 5.2 商图与耦合图

将等价任务折叠得到模板商图 $G/\sim$，同时建立重复实例之间的耦合图 $H$：

- $H$ 的节点是 motif instance；
- dependency edge 表示跨 motif 的 finish-to-start 依赖；
- conflict edge 表示共享 channel/link/NIC；
- barrier hyperedge 表示 collective/optimizer 等多方 join。

不能只看 $G/\sim$，因为复制策略是否安全主要由 $H$ 决定。

定义耦合强度：

$$
\kappa=\alpha\frac{|E_{cross}|}{|E|}
+\beta\frac{|C_{cross}|}{|C|}
+\gamma\frac{W_{carry}}{W_{period}},
$$

其中三项分别表示跨模板依赖、跨模板资源冲突和周期边界 carry-in work。第一轮先分别报告三项，不急于固定 $\alpha,\beta,\gamma$。

### 5.3 周期边界状态

一个周期不能只用“完成到第几个 micro-batch”描述，还要记录：

$$
z_k=(frontier_k, remaining_k, active\ resource\ phase_k,
optimizer\ slack_k).
$$

如果执行一个候选周期策略后满足 $z_{k+1}$ 与 $z_k$ 在平移 micro-batch 编号后等价，才能称为真正的 steady-state 循环。否则应使用滚动窗口重新规划。

## 六、核心实验：验证重复单元是否会相互影响

这是本阶段最重要的实验，不应直接默认“可以复制”。

对每个检测到的 motif/period 比较四种方式：

1. **Independent-copy**：单独求一个周期后原样复制；
2. **Boundary-aware copy**：搜索时加入前一周期 carry-in 和后一周期 terminal lower bound；
3. **Receding horizon**：每个周期或若干事件重新搜索；
4. **Full-DAG teacher**：小图 Exact，大图 Beam/Rollout。

报告：

- makespan gap；
- 周期边界积累的 remaining work；
- 资源冲突次数与抢占次数；
- optimizer/collective barrier 延迟；
- 策略从一个周期迁移到多个周期后的 gap 增长曲线。

专门构造三类反例：

- 每个周期局部最优，但 deferred DP 在末尾不断累积；
- 两个周期争用同一 PP/DP uplink，最优优先级需要交错；
- EP 流量在周期间偏斜，固定时间表逐步失效。

若 Independent-copy 的误差随重复次数线性增长，就不能把该 motif 宣称为可直接扩展；只能使用 boundary-aware 或 receding-horizon 方法。

## 七、候选算法路线

### 7.1 Symmetry-compressed Exact/Beam

对于完全交换的 micro-batch/replica，不保存具体任务 ID，而保存每种模板的：

```text
(not_released_count, ready_count, remaining_work_multiset, completed_count)
```

先在小图上验证压缩前后 Exact makespan 完全相同，再用于 Beam 去除对称分支。这是最稳妥、最先实现的结构利用方式。

### 7.2 Phase-conditioned priority table

学习一个短策略表：

$$
score_i=	heta_{phase,role}^T\phi_i(s),
$$

特征包括 residual tail、remaining work、optimizer slack、resource conflict、micro-batch offset 和是否 continuation。参数可以由小图 Oracle/Beam 的决策拟合，也可以小规模网格搜索。

它复用的是“同类状态下如何排序”，不是固定 flow ID 顺序，因此比直接复制时间表更能承受 duration 扰动。

### 7.3 Motif macro-action Rollout

把通用 Rollout 的候选从单个 flow 扩展为短宏动作，例如：

```text
完成一个 PP gradient wave
推进一个 TP collective chunk wave
在下一 PP release 前填充某个 DP bucket
继续当前 collective，避免额外切换
```

宏动作执行到下一关键事件后，仍用真实状态机计算端到端结果：

$$
\widehat C(s,A)=\Delta(s,A)+\widehat J(T(s,A)).
$$

LLM 结构只缩小候选集，不能直接给局部 bonus 充当端到端收益。

### 7.4 Coupling-aware periodic scheduler

在 steady phase 离线搜索长度为 $k$ 的周期，但目标包含边界价值：

$$
\min_{\pi_k}\; T_k(\pi_k)+V(z_{k+1}),
$$

$V$ 由 Longest-tail lower bound、短 rollout 或相邻周期 teacher 近似。运行时若实际边界状态偏离模板超过阈值，就回退到通用 Event Rollout-2；重新进入等价 steady state 后恢复周期策略。

建议最终采用组合形式：

```text
warmup: 通用 Rollout
steady: coupling-aware periodic policy + 事件修正
cooldown/optimizer: 通用 Rollout 或 deadline policy
异常/profile 漂移: 回退 Longest-tail/Rollout
```

## 八、实验基线与评价方法

### 8.1 基线

- Residual Longest-tail；
- Event Rollout-2；
- Beam-8/32；
- Exact Oracle（缩小后的真实窗口）；
- Independent-copy（验证简单复制的风险）；
- 不利用 LLM 标签、但计算预算相同的 generic search。

### 8.2 指标

解质量：

- makespan；
- 相对 Exact/teacher gap；
- 相对 Event Rollout-2 的收益；
- optimizer barrier 和关键 collective completion time。

复杂度与可复用性：

- 状态数、展开节点数、运行时间和内存；
- motif 数/原任务数，即压缩率；
- 一个周期策略跨 GA、iteration 数和模型规模的迁移误差；
- 回退到通用策略的事件比例。

稳健性：

- duration 扰动 ±5%、±10%、±20%；
- EP 路由偏斜；
- placement 改变；
- 非零切换开销、最小 chunk、最大抢占次数。

结果必须按 random、adversarial、real 分开报告，并按 PP mode、并行配置和 placement 分层，不能用大量容易样例稀释 hard case。

## 九、执行阶段与产物

### L0：数据与语义审计

- 确定 SimAI 每种 pipeline builder 的 F/B/W、PP、TP、DP、EP 和 optimizer 依赖；
- 明确 iteration 边界和跨 iteration 是否允许 overlap；
- 修正或隔离仍不符合真实语义的图，例如错误的 B→W 依赖；
- 保留 collective identity、rank group、route 和 chunk 信息。

产物：配置清单、语义差异表、不可用于结论的数据黑名单。

### L1：单维度结构扫描

- 分别扫描 PP、DP、TP、EP；
- 输出 motif coverage、period、frontier、slack、join 和资源冲突统计；
- 为每类维度保存 3--5 个可审计的小图快照。

产物：单维度结构报告和 benchmark。

### L2：组合配置扫描

- 做单因素、两两交互和代表性 3D/4D 配置；
- 同时改变 placement；
- 自动比较商图、耦合图和周期边界状态。

产物：配置相似性/差异性矩阵，以及“可复用模板范围”。

### L3：重复扩展有效性实验

- 实现 Independent-copy、Boundary-aware 和 Receding-horizon；
- 在重复 1、2、4、8、16 个周期时测量 gap；
- 生成跨周期资源冲突和 deferred-work 累积反例。

产物：重复结构相互影响的定量结论。

### L4：结构压缩与周期算法

- 先实现 symmetry-compressed Exact/Beam；
- 再实现 phase-conditioned priority；
- 最后实现 motif macro-action rollout 和 coupling-aware periodic scheduler。

产物：算法、统一接口、可行性测试和消融实验。

### L5：跨 iteration 迁移与鲁棒性

- 不展开完整 epoch，只生成连续若干 iteration；
- 检查 optimizer/barrier 后状态是否复位；
- 测试 profile 漂移、EP 偏斜和抢占约束；
- 评价“首个 iteration 学习、后续 iteration 复用”的摊销收益。

产物：最终 LLM 特化实验报告。

## 十、退出条件

本阶段完成至少要满足：

1. 覆盖至少 3 种 PP 策略、3 组 GA/PP 比例和 3 组混合并行配置；
2. 明确区分结构重复、资源重复和时间重复，并给出自动统计；
3. 用 Exact 证明对称压缩在可交换小图上不改变最优值；
4. 定量回答简单复制在什么条件下成立、在什么反例上失败；
5. 至少一种结构算法相对等预算 generic search 达到以下之一：更好 makespan，或近似相同 makespan但显著减少状态数/运行时间；
6. 相对 Event Rollout-2 的独立收益至少出现在两种 PP mode 或两种 placement 上；
7. 在 duration 扰动和有限抢占约束下仍能安全回退，不出现不可行 schedule。

如果只能优于 Longest-tail、却不能优于等预算通用 Rollout，说明特征只是在替代基础 tail，而没有真正利用重复结构；这不算完成 LLM 特化目标。

## 十一、建议的第一轮实际工作

第一轮先不实现复杂学习算法，按以下顺序推进：

1. 写统一的 SimAI DAG scanner，生成 motif signature、phase period、耦合指标和配置对比表；
2. 选 1F1B、Interleaved、Zero Bubble，扫描 `PP={2,4}`、`GA={PP,2PP,4PP}`；
3. 固定 PP 骨架，分别加入 TP、DP，再加入一个 EP 探针；
4. 对 steady period 做 1/2/4/8 次复制实验，先验证 Independent-copy 是否积累误差；
5. 在 exact 小窗口上实现 symmetry compression；
6. 只有确认周期边界状态近似复位后，才实现周期策略复用。

这样可以先回答最关键的科学问题——“重复结构是否真的能安全扩展”——再决定应该投入周期策略、宏动作 Rollout，还是只把重复性用于搜索状态压缩。
