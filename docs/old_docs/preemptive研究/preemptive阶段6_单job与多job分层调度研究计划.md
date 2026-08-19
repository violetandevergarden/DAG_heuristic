# 可抢占阶段 6：单 Job 与多 Job 分层调度研究计划

## 一、核心判断

你的判断基本正确，但需要稍微修正为：

> 多 Job 并不会让单 Job 的细粒度语义完全失效，而是会改变这些语义应该被使用的位置。F/B/W、micro-batch、pipeline phase、DP slack 等细粒度信息适合留在 Job 内部决定“这个 Job 下一步最值得推进哪个 flow”；跨 Job 的全局调度器则应该主要根据更稳定的粗粒度接口决定“此刻应该给哪个 Job、哪些资源和多少服务机会”。

也就是说，不宜在全局调度器中直接比较：

```text
Job A 的 stage-2 microbatch-7 PP_GRAD
和
Job B 的 layer-31 DP bucket-4
```

因为这两个标签不在同一个语义坐标系中，模型规模、PP 策略、iteration phase 和 placement 一变，固定的跨 Job 细粒度优先级就可能失效。

更合理的比较是：

```text
Job A：当前通信位于关键 release 链，推迟 1 单位预计延迟下一个 stage
Job B：当前是有 20 单位 slack 的 deferred DP，尚可让渡
```

细粒度语义仍然有用，但应先被 Job 内控制器翻译成跨 Job 可比较的“紧迫度、边际收益、资源需求和可让渡性”。

## 二、研究问题

本阶段回答五个问题：

1. 单 Job 中有效的 fine-grained feature，在多 Job 干扰下有多少仍能预测正确决策？
2. 多 Job 全局调度最少需要看到哪些 Job-level summary，才能接近 flat Rollout/Exact？
3. 一个 Job 每次只向全局调度器暴露 1 个候选 flow 是否足够？若不够，暴露前 $K$ 个候选时，质量和复杂度如何变化？
4. 单 Job 周期策略在获得不连续服务时是否仍成立？什么情况下必须通知 Job 内控制器重新规划？
5. 面对异构 Job、动态到达和共享多资源时，makespan、平均 JCT 和公平性之间如何权衡？

## 三、模型边界与目标函数

### 3.1 执行语义

第一轮沿用阶段 5 的理想可抢占模型：

- compute 自动执行且不可抢占；
- communication 在任务事件处可暂停并保留进度；
- 零切换成本、零最小 quantum；
- 单 channel 每时刻选择一个 flow；
- 多资源场景选择固定资源集合互相兼容的 flow set。

多 Job 只是若干带 `job_id` 的 DAG 的并集，不允许跨 Job precedence。Job 之间只通过共享通信资源发生耦合。

### 3.2 目标函数分两轮研究

不能把所有多 Job 目标混在一个分数中。建议按下面顺序进行。

第一轮使用同时到达的 batch 场景，仍优化：

$$
C_{max}=\max_j C_j.
$$

它与当前研究一致，也容易用小图 Exact 校准。

第二轮再加入动态到达时间 $a_j$，分别报告：

$$
\sum_j w_j(C_j-a_j),
\qquad
\max_j \frac{C_j-a_j}{C_j^{solo}},
$$

即加权平均 JCT 和最大 slowdown。不能只优化总体 makespan，否则小 Job 可能长期得不到服务；也不能只优化平均 JCT，否则大 Job 可能被饿死。

## 四、两层调度框架

### 4.1 Job 内控制器

每个 Job 保留自己的细粒度 DAG 和状态，负责：

- residual tail；
- PP activation/gradient release；
- F/B/W 和 warmup/steady/cooldown phase；
- DP/optimizer slack；
- micro-batch 周期边界和 carry-in；
- Job 内对称状态压缩；
- 为当前 ready flows 排序并产生少量候选。

Job 内控制器不直接占用全局资源，而是向全局调度器提交候选：

$$
B_j(s)=\{(f_{j1},b_{j1}),\ldots,(f_{jK},b_{jK})\}.
$$

$f_{jk}$ 是候选 flow，$b_{jk}$ 是可跨 Job 比较的 bid/summary，而不是简单的本地 priority 数值。

### 4.2 Job 级稳定接口

建议第一版 Job summary 为：

$$
z_j=(W_j, L_{jr}, CP_j, M_j, S_j, A_j, U_j, F_j).
$$

各项含义：

- $W_j$：Job 剩余通信总量；
- $L_{jr}$：Job 在资源 $r$ 上的剩余负载；
- $CP_j$：当前 residual critical-path lower bound；
- $M_j$：下一关键 milestone，例如下一 PP release、optimizer barrier 或 iteration 完成；
- $S_j$：到该 milestone 的预测 slack；
- $A_j$：已经获得的服务量、等待时间和 slowdown，用于防止饥饿；
- $U_j$：当前 ready flows 能使用的资源 footprint；
- $F_j$：本地控制器给出的前 $K$ 个候选及其边际推进价值。

其中 `stage_id`、`microbatch_id`、`layer_id` 等不直接进入跨 Job 比较；它们只用于 Job 内生成 $M_j,S_j,F_j$。

### 4.3 全局控制器

单 channel 下，全局控制器先选 Job，再从该 Job 的候选中选 flow：

$$
j^*=\arg\max_j G(z_j,\mathcal I_j),
\qquad
f^*=\arg\max_{f\in B_{j^*}} b(f).
$$

$\mathcal I_j$ 是该 Job 与其它 Job 的资源干扰摘要。

多 channel 下不应先独立选择每个 Job，而应从所有 Job 的候选并集里选择兼容集合：

$$
A^*=\arg\max_{A\subseteq\bigcup_j B_j}
\sum_{f\in A}b(f),
\quad
R(f)\cap R(g)=\varnothing.
$$

还要加入 Job-level fairness/debt 约束，避免候选集合长期只来自同一个 Job。

## 五、候选宽度 $K$：连接细粒度与粗粒度的关键旋钮

不应只比较“完全细粒度”和“完全粗粒度”两个极端，而应定义接口宽度 $K$：

- $K=1$：每个 Job 只提名一个本地最佳 flow，最粗粒度；
- $K=2/4/8$：保留少量语义不同或资源不同的候选；
- $K=\infty$：暴露所有 ready flow，退化为 flat 全局调度。

这个设计有两个重要性质。

第一，在单 channel 中，任何全局 action 都属于某个 Job。当 $K=\infty$ 且全局状态完整时，分层框架可以表达任意 flat schedule；分层本身不造成解空间损失。

第二，真正的近似损失来自候选截断和 summary 压缩。于是可以直接画出：

$$
K\longrightarrow
(makespan\ gap, states, runtime, communication\ overhead).
$$

比起争论“细粒度还是粗粒度”，这能定量找到最小够用的接口。

候选不应只是本地排名前 $K$。至少保留不同类型的代表：

```text
最高 residual tail
最小 milestone slack
当前 continuation
最能解锁 join/release 的 flow
占用不同资源的候选
最老、等待最久的候选
```

这样 $K=4$ 可能比简单取本地 top-4 更有信息量。

## 六、干扰和“细粒度语义衰减”的量化

### 6.1 Job 对干扰矩阵

对 Job $i,j$ 定义资源重叠：

$$
I_{ij}^{load}
=\frac{\sum_r\min(L_{ir},L_{jr})}
{\sum_r\max(L_{ir},L_{jr})},
$$

以及时间重叠 $I_{ij}^{time}$：两者 ready communication 同时存在的事件比例。还要分别记录 PP/DP/TP/EP 在共享资源上的重叠，避免总负载掩盖维度差异。

### 6.2 特征稳定性

对每个 Job 比较 solo 和 colocated 状态下：

- 本地候选排名的 Kendall/Spearman 相关性；
- solo 最佳 action 在多 Job teacher 中仍被选择的比例；
- 同一 phase-conditioned rule 的 regret；
- milestone/slack 预测误差；
- 周期边界 carry-in 的偏移。

按特征组做消融：

1. 纯通用：remaining、tail、资源负载；
2. Job 粗语义：milestone、slack、slowdown、资源 footprint；
3. Job 细语义：F/B/W、stage、micro-batch、phase；
4. 完整 flat 状态。

如果第 3 组在加入第 2 组后仍显著改善 teacher gap，说明细粒度语义在多 Job 下仍有跨 Job价值；否则它应只留在本地控制器。

### 6.3 服务中断对周期策略的影响

单 Job 周期策略原先假设连续获得 channel 服务。多 Job 下，一个 Job 可能经历 service vacation。定义：

$$
V_j(t)=\text{从 Job }j\text{ 上次获得服务到当前的时间},
$$

并测量 vacation 后边界状态与 solo 模板的距离：

$$
d(z_j,z_j^{template})
=\lambda_1\|remaining-rem^{template}\|_1
+\lambda_2|slack-slack^{template}|
+\lambda_3\,frontier\ mismatch.
$$

距离超过阈值时，本地周期缓存失效，必须重新运行 Job 内 Rollout；不能在恢复服务后机械接着执行旧时间表。

## 七、算法基线

### 7.1 Flat 基线

- `Flat Longest-tail`：忽略 job 层次，所有 ready flow 一起比较；
- `Flat Rollout-2/Beam`：全局细粒度 teacher；
- `Flat Exact`：小图 ground truth；
- Job-oblivious FIFO/SPT/LAS：检查简单服务纪律。

### 7.2 分层基线

- `Hierarchical LT K`：Job 内 Longest-tail 提名 $K$ 个，Job 间按 critical-path/slack 选择；
- `Hierarchical Rollout K`：Job 内生成候选，全局只在候选并集上 rollout；
- `Milestone-slack`：优先服务最接近关键 barrier/latest-start 的 Job；
- `Bottleneck-aware`：按共享瓶颈上的剩余负载和释放收益选择；
- `Attained-service aware`：在上述 score 上加入等待债务，避免饥饿；
- `Adaptive-K`：低干扰时 $K=1$，冲突或预测不确定性升高时扩大 $K$。

### 7.3 推荐优先实现的算法

第一版建议实现 `Adaptive-K Hierarchical Rollout`：

1. 每个 Job 本地用细粒度状态产生语义多样的前 $K$ 个候选；
2. 全局用粗粒度 milestone/slack、resource overlap 和 attained service 筛选 Job；
3. 只对筛选后的候选做一次真实端到端 rollout；
4. 若 top-1 与 top-2 预测差距小、干扰强或边界状态漂移，则临时增大 $K$；
5. 若 Job 重新进入稳定 phase，则缩小 $K$ 并复用本地 quotient/cache。

它不会把粗粒度 score 直接当作端到端收益，而是用粗语义缩小搜索范围，最终仍由状态机 rollout 评价。

## 八、理论问题与反例

### 8.1 可分解的充分条件

若不同 Job 的 DAG 无交叉依赖，且使用的通信资源集合两两不交，那么各 Job 调度完全独立。对 makespan：

$$
C_{max}^*=\max_j C_j^*.
$$

此时单 Job 最优策略可以直接并行组合。真实多 Job 问题的困难完全来自共享资源。

### 8.2 分层表示能力

单 channel 中，如果每个 Job 暴露全部 ready flow，并且全局控制器看到完整状态，那么分层控制器与 flat 控制器的 action space 相同。因此需要证明或构造反例的不是“分层”本身，而是：

- $K$ 候选截断；
- Job summary 丢失；
- 本地策略在 service vacation 后不重新规划。

### 8.3 必须构造的反例

1. **Top-1 截断反例**：Job A 本地最优 flow 占用共享 uplink，但第二候选只占私有 link；Job B 此时需要 uplink。全局最优必须选择 A 的第二候选，$K=1$ 看不到它。
2. **细粒度标签误导反例**：两个 Job 都有 `PP_GRAD`，但一个位于关键 release 链，另一个有很大 slack。只按角色会错误地认为它们等价。
3. **粗 summary 冲突反例**：两个 Job 的 total work、critical path 和 slack 相同，但内部一个即将 join、一个仍有平行余量；过粗 summary 无法区分。
4. **周期恢复反例**：Job A 的周期策略被 Job B 长时间打断，恢复后旧 micro-batch offset 已不对应当前 ready frontier。
5. **公平性反例**：持续优先 critical-path 最大的长 Job，使短 Job slowdown 无界。
6. **多资源互补反例**：只选一个 Job 会浪费另一条空闲链路，而跨 Job compatible pack 能并行完成两个 flow。

### 8.4 近似比研究

对同时到达、单 channel、零成本可抢占、目标 $C_{max}$ 的第一轮，任何始终 work-conserving 的分层算法仍继承此前的通用 2 上界；但这不能说明候选截断的实际质量，也不能用于 $\sum w_jC_j$。

需要进一步研究：

- 保证每个 Job 的 critical candidate 总在候选集时，能否把 $K$ 截断损失界在某个可测 coupling 参数内；
- 对资源隔离度 $1-I_{ij}$ 较高的实例，是否能得到参数化近似；
- milestone slack 估计误差为 $\epsilon$ 时，决策 regret 是否可界；
- 多资源 maximal pack 的分层候选是否仍有常数界，或必须增加 resource-diverse nomination。

不要预先宣称比 2 更好的最坏情况界；先由 Exact 小图搜索反例。

## 九、Benchmark 设计

### 9.1 Job 组合类型

从现有单 Job benchmark 组合，不修改各自内部 DAG：

- 同构 Job：相同模型、配置、phase，但起始偏移不同；
- 异构规模：小模型 + 大模型；
- 异构 PP：1F1B + Interleaved/DualPipe；
- 异构维度：PP-heavy + DP-heavy、TP-heavy + PP-heavy、dense + EP；
- 同资源 placement 与资源隔离 placement；
- 同时到达与 staggered arrival；
- phase 对齐与 phase 错开。

第一轮 Job 数为 `2, 3, 4`；验证框架后再到 `8, 16`。不要一开始用大量 Job，使 Exact 和归因都不可行。

### 9.2 三类数据

- `random composition`：从固定单 Job 池按 seed 组合约 10 组；
- `adversarial`：对应第八节六类反例；
- `real mix`：从 AICB/SimAI 快照选择可审计的模型与 3D 配置进行组合。

多 Job benchmark 必须增加 `job_id`、arrival、weight/SLO 等显式字段。metadata 不得藏答案；reference result 仍独立保存。

### 9.3 小图 Oracle

现有 Exact 已能在 DAG 并集上优化总体完成时间，但需要扩展结果统计：

- 每个 Job 的 $C_j$；
- JCT、slowdown、service received；
- 每个 decision 的所属 Job；
- job switch 和 flow preemption；
- milestone completion；
- 每资源、每 Job 的占用时间。

对于 $\sum w_jC_j$，Exact 的终止代价和 DP value 必须按 Job completion event 累加，不能继续只返回最终 makespan。

## 十、实验矩阵

### M0：语义与数据接口

- 为 benchmark/task 增加或规范化 `job_id`；
- 定义 arrival、weight、SLO 和目标函数；
- 验证 DAG union 不产生跨 Job 边；
- 建立 per-job completion/JCT 统计。

产物：多 Job specification、loader 和 evaluator。

### M1：细粒度特征稳定性

- 对每个 Job 记录 solo teacher；
- 与 1--3 个干扰 Job colocate；
- 分析 local action rank、phase rule、slack 和周期状态漂移；
- 按 PP/DP/TP/EP、placement 和干扰强度分层。

产物：哪些 fine feature 能迁移、哪些只能留在 Job 内的实证表。

### M2：候选宽度实验

- 实现 $K=1,2,4,8,\infty$；
- 对比普通 top-$K$ 和 semantic-diverse top-$K$；
- 报告 teacher gap、候选数、状态数和运行时间；
- 自动搜索最小的 top-1/top-2 反例。

产物：最小够用接口宽度和候选构成。

### M3：分层算法

- Hierarchical LT；
- Milestone-slack；
- Hierarchical Rollout；
- Adaptive-K；
- 多资源 compatible cross-job pack。

产物：统一算法接口和消融实验。

### M4：目标与公平性

- 同时到达的 makespan；
- 动态到达的 weighted JCT；
- slowdown 和 starvation；
- attained-service/fairness debt 消融。

产物：不同目标下不能混用的策略结论。

### M5：规模与鲁棒性

- Job 数扩展到 8/16；
- arrival、duration 和 phase 扰动；
- placement 改变；
- 有限 quantum、切换成本和抢占预算；
- 本地周期 cache 命中率与失效回退率。

产物：最终多 Job 分层调度报告。

## 十一、评价指标

解质量：

- makespan / weighted JCT / slowdown；
- 对 Exact 或 flat teacher 的 gap；
- 每个 Job 的 completion time 和 tail latency；
- milestone/barrier 延迟。

复杂度：

- 全局候选数；
- rollout/beam 展开状态数；
- 调度器运行时间和内存；
- Job 内 cache/quotient 命中率；
- 调度接口每事件传递的字段和候选数量。

干扰与稳定性：

- $I_{ij}^{load}$ 和 $I_{ij}^{time}$；
- solo/colocated action rank 相关性；
- service vacation 长度；
- 边界状态漂移；
- job switch、flow preemption 和资源空闲率。

## 十二、退出条件

阶段完成至少需要满足：

1. 至少覆盖同构、异构规模、异构并行维度和两种 placement；
2. 用 Exact 给出不少于 30 个 2--4 Job 小图的 ground truth；
3. 明确量化 fine-grained feature 从 solo 到 colocated 的稳定性；
4. 找到 $K=1$ 失败反例，并给出 $K=2/4/8$ 的质量—复杂度曲线；
5. 分层算法在至少两类真实 mix 上达到 flat Rollout 近似相同的解，但显著减少候选或运行时间；
6. 或者明确证明当前 Job summary 不足，并给出不可区分状态反例；
7. 动态到达实验同时报告 JCT 和 slowdown，不出现未解释的饥饿；
8. 在 profile/arrival 扰动下能检测本地周期策略失效并安全回退；
9. 单 channel 和多资源结果分开报告，不能用资源隔离样例稀释高冲突样例。

## 十三、建议的实际执行顺序

第一轮不急于实现复杂公平策略，建议：

1. 先实现带 `job_id` 的 DAG union、per-job 指标和多 Job Exact；
2. 只选 2 个 Job，构造同构/异构以及 phase 对齐/错开的小图；
3. 跑 solo 与 colocated teacher，直接测细粒度 action rank 是否变化；
4. 实现每 Job 候选宽度 $K$，先找 $K=1$ 反例；
5. 比较 `flat Rollout`、`hierarchical K=1/2/4` 和 `semantic-diverse K=4`；
6. 确认分层压缩有效后，再加入动态到达、公平性和多资源 pack；
7. 最后才把阶段 5 的周期 cache 接到 Job 内控制器，并用 service vacation 检测失效。

这条路线首先回答最关键的问题：

> 多 Job 场景下究竟需要向全局暴露多少单 Job 细节？

如果 $K=2/4$ 的分层调度已经接近 flat teacher，就说明“Job 内细粒度、Job 间粗粒度”的架构成立；如果必须接近 $K=\infty$ 才能保持质量，则说明现有 summary 丢失了关键耦合信息，应优先改进接口，而不是继续设计全局粗粒度 priority。

