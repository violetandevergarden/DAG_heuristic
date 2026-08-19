# 可抢占阶段 6：单 Job 与多 Job 分层调度初步结果

## 一、当前结论

本轮已经完成计划中的 M0--M4 最小闭环，并增加了一个多资源反例。结论是：

1. **“Job 内细粒度、Job 间粗粒度”的两层架构是可行的表示方式，但粗接口不能只暴露一个 flow。** 单 channel 小图中，$K=1$ 存在严格 gap；$K=2$ 在当前 40 个 Exact 小图上全部恢复最优。
2. **多 Job 干扰确实会改变单 Job 内部候选的价值。** 两个固定攻击例中，每个 Job 单独运行时 local top-1 都能达到各自 Exact；组合后 top-1 接口却分别从最优 14/18 恶化到 15/19。因此损失不是 Longest-tail 自己的单 Job 缺陷，而是跨 Job 竞争使本地第二候选变得重要。
3. **暴露更多候选不等于全局调度正确。** 粗粒度 priority 即使拿到 $K=2$，在攻击集上仍有与 $K=1$ 相同的最大 7.14% gap；只有用端到端 Rollout 重新评价候选，$K=2$ 才全部恢复 Exact。
4. **多资源中需要“资源多样化候选”。** 固定反例中 $K=1$ 隐藏了一个私有链路 flow，使链路空闲，makespan 为 25；$K=2$ 暴露该 flow 后与另一个 Job 的 uplink flow 并行，达到 Exact 的 18。
5. **makespan 和 JCT/fairness 必须分开优化。** 在长短 Job 小图中，两个顺序的 makespan 都为 11，但按 makespan 的确定性 tie-break 产生的 weighted JCT 比最优差 75%；带权例中可差到 4.0625 倍。
6. **当前 SimAI pipeline 双 Job probe 很容易。** 1F1B/Interleaved 四种组合中，$K=1$、粗 priority 和 flat Rollout 的 makespan 相同；这只能说明这些小图的最优动作替代性强，不能证明 $K=1$ 普遍安全。

所以对最初问题的更精确回答是：

> 单 Job 的 F/B/W、micro-batch、stage 和 phase 信息仍应保留在 Job 内部；全局层不需要理解所有绝对标签，但每个 Job 至少应暴露少量“语义多样、资源多样”的候选，并附带 critical path、milestone/slack、剩余资源负载和服务债务。全局层必须按真实目标做端到端评价，不能仅比较一个粗 priority。

## 二、已经实现的框架

### 2.1 多 Job 组合

`compose_jobs` 将每个 Job 的任务 ID 前缀化，并为 Job 增加 arrival compute：

```text
job_id::__arrival__ -> 该 Job 原 DAG 的所有 root
```

组合后满足：

- 无跨 Job precedence；
- Job 只通过共享 channel/固定资源集合冲突；
- arrival 可以在通信执行期间触发事件和抢占；
- 原 task role 被保留；
- 可从任意 task 反查 `job_id` 和原 task ID。

### 2.2 Per-job 指标

统一报告：

$$
C_j,\quad JCT_j=C_j-a_j,
\quad slowdown_j=\frac{JCT_j}{C_j^{solo}},
$$

以及 weighted mean JCT、mean JCT、最大 slowdown、候选数和候选评价次数。

### 2.3 两层候选接口

每个 ready Job 独立提名前 $K$ 个 flow：

$$
B_j^K(s)=TopK\{f\in Ready_j(s)\}.
$$

全局 action 只从 $\bigcup_j B_j^K$ 中选择。当前支持：

- tail top-$K$；
- semantic-diverse top-$K$：优先保留最高 tail、continuation 和不同 role；
- $K=1,2,4,\infty$；
- Adaptive-$K$；
- 粗 priority、end-to-end Rollout、Shortest-job、Attained-service；
- 单 channel 与固定多资源 compatible pack。

### 2.4 两种 Exact

- Flat Exact：所有 ready flow 都是合法 action；
- Hierarchical Exact-$K$：每个状态只允许 Job 内 top-$K$ 候选。

二者的差值严格表示“候选接口删掉 action”造成的损失，不包含 heuristic completion policy 的误差。

Weighted JCT Exact 使用：

$$
\sum_j w_j(C_j-a_j)
=\int_0^\infty \sum_{j:\,a_j\le t<C_j}w_j\,dt.
$$

在一次状态转移 $[t,t+\Delta)$ 中，DP 即时代价为 $\Delta$ 乘当前已经到达且未完成 Job 的权重和。

## 三、数据与实验范围

Exact 数据共 40 个双 Job case：

- 30 个固定 seed 随机组合；
- 4 个 top-1 攻击例；
- 1 个候选状态压缩例；
- 5 个 LLM motif mix，包括 PP wave、1F1B、W/DP optimizer join、TP+PP 和正确 B/W fork。

分为：同构 Job、异构 Job、错峰到达、adversarial 和 LLM motif mix。

另有：

- 4 个由 SimAI builder 展开的双 pipeline probe；
- 5 个 objective/fairness 小图；
- 1 个固定多资源候选反例。

## 四、单 channel 候选宽度结果

### 4.1 总体结果

| 方法 | 平均 Exact 比 | 最大比 | 最优率 | 平均候选数/事件 | 平均运行时间 |
|---|---:|---:|---:|---:|---:|
| Exact-$K=1$ | 1.00595 | 1.07143 | 90% | 1.401 | 约 34 ms |
| Exact-$K=2$ | 1.00000 | 1.00000 | 100% | 2.005 | 约 444 ms |
| Rollout-$K=1$ | 1.00595 | 1.07143 | 90% | 1.400 | 约 17 ms |
| Rollout-$K=2$ | 1.00000 | 1.00000 | 100% | 2.013 | 约 24 ms |
| Semantic-$K=2$ | 1.00000 | 1.00000 | 100% | 2.013 | 约 24 ms |
| Adaptive-$K=1\ldots4$ | 1.00000 | 1.00000 | 100% | 1.955 | 约 24 ms |
| Flat Rollout | 1.00000 | 1.00000 | 100% | 2.049 | 约 25 ms |

运行时间依赖机器，只用于同批相对比较。当前小图每个 Job 通常只有两个 ready flow，因此 $K=2$ 经常等同 flat action space；不能从该表外推“大图中 $K=2$ 永远足够”。

### 4.2 Teacher 候选覆盖率

Exact teacher action 被该 action 所属 Job 的 top-$K$ 接口保留的平均比例：

| $K$ | 覆盖率 |
|---:|---:|
| 1 | 87.04% |
| 2 | 99.83% |
| 4 | 100% |

覆盖率小于 100% 不一定产生 gap，因为可能存在等价最优 action。候选压缩例中 $K=2$ 只覆盖 teacher trace 的 93.33%，但仍存在另一条受限最优 schedule。

### 4.3 严格 top-1 攻击

4 个攻击例中：

- Flat Exact makespan 分别为 18、14、18、18；
- Exact-$K=1$ 分别为 19、15、19、19；
- Exact-$K=2$ 全部恢复 Flat Exact。

其中第 2、3 个例子在两个 Job 各自 solo 时，top-1 接口都不损失最优值；只有 colocate 后才失败。这直接证明 Job 间冲突会改变本地候选的全局价值。

### 4.4 状态压缩例

每个 Job 有三条 ready chain：

| Action space | makespan | Exact 状态数 |
|---|---:|---:|
| $K=1$ | 23 | 230 |
| $K=2$ | 23 | 8,192 |
| Flat | 23 | 28,287 |

$K=2$ 在该例保持最优并减少约 71% 状态，说明有限接口可用于 Exact/Beam 压缩；$K=1$ 更小但不能由这一个容易例证明安全。

## 五、粗粒度全局 priority 的结果

Priority-$K=1$ 和 Priority-$K=2$ 的总体最优率都为 90%，最大 gap 都为 7.14%。增加 $K$ 没有修复结果，因为粗 score 仍选择了错误候选。

相对地，Rollout-$K=2$ 在同一批 case 上全部达到 Exact。这说明分层架构应采用：

```text
粗语义：筛 Job、控制 K、保证公平与资源多样性
细粒度状态机：对最终少量候选做端到端评价
```

而不是把粗 summary score 直接当作真实收益。

## 六、SimAI pipeline 双 Job probe

使用 `PP=2, GA=2, local layers=2`，组合：

- 1F1B + 1F1B；
- 1F1B + Interleaved；
- Interleaved + Interleaved；
- 错峰到达的 1F1B + Interleaved。

结果：所有方法 makespan 与 Flat Rollout 相同。但 Flat Rollout action 的 Job 内 top-1 覆盖率只有：

```text
94.23%, 83.33%, 76.71%, 77.94%
```

top-2 均为 100%。说明这些 pipeline 小图中存在大量可替代 action，不能用“最终 makespan 相同”反推细粒度顺序不重要。

性能上：

- Rollout-$K=1$ 平均评价 89.5 个候选，Flat 为 135.25，减少约 33.8%；
- 平均运行时间约 1.33 s 对 2.04 s，减少约 34.7%；
- 当前 Adaptive-$K$ 评价 123.75 个候选，只减少约 8.5%，阈值明显过于保守；
- 粗 priority 约 37--40 ms 且在这 4 个 probe 上 makespan 相同，但没有 Exact 保证，并已在攻击集失败。

这些是 SimAI 合成输入的小图，不是完整真实 AICB 多 Job trace。

## 七、多资源反例

Job A 同时有：

```text
A::shared  使用 uplink，duration=4，tail=10
A::private 使用 private，duration=8，tail=9
```

Job B 有：

```text
B::shared 使用 uplink，duration=4，tail=11
```

$K=1$ 时 A 只提名 `A::shared`。全局先运行 `B::shared` 后，只能看到 `A::shared`，private link 连续空闲，makespan 为 25。

$K=2$ 时第一组 action 是：

```text
(A::private, B::shared)
```

随后 `(A::private, A::shared)`，makespan 为 18，与多资源 Exact 相同。

因此多资源 nomination 必须至少覆盖不同 resource footprint。简单 local top-$K$ 在资源种类较多时仍可能需要很大的 $K$；更合适的是每种关键 resource class 提名代表候选。

## 八、makespan、JCT 和公平性

### 8.1 同时到达的长短 Job

长 flow=10、短 flow=1。无论先后，makespan 都为 11：

```text
long first:  C_long=10, C_short=11, mean JCT=10.5
short first: C_short=1, C_long=11,  mean JCT=6.0
```

只优化 makespan 无法区分二者，weighted JCT 可差 1.75 倍。

### 8.2 错峰到达

短 Job 在 $t=3$ 到达时，会产生 compute completion event，当前长 flow 可被暂停。Weighted-JCT Exact 会立即切换给短 Job，而 makespan 仍为 11。这说明动态到达是合法且重要的重新规划事件。

### 8.3 带权目标

- 短 Job 权重为 5 时，忽略权重的 critical priority 比 weighted-JCT Exact 差 4.0625 倍；
- 长 Job 权重为 20 时，单纯 Shortest-job 比 weighted-JCT Exact 差约 4.74%。

所以 Job-level summary 必须携带 objective weight/SLO。Shortest-job 只能作为平均 JCT baseline，不能充当通用策略。

### 8.4 当前 attained-service 的限制

当前模型只在 task event 决策，不会为了公平主动制造任意时间 quantum。若两个 Job 在 $t=0$ 同时 ready，且被选中的长 flow 期间没有 compute/arrival event，Attained-service 无法中途切换。

要研究时间片公平性，必须显式引入 minimum/maximum quantum 或 periodic scheduling event；不能在现有事件模型中假装它已经存在。

## 九、对原始假设的回答

### 9.1 哪些细粒度语义应留在单 Job 内

- F/B/W 和 PP_ACT/PP_GRAD；
- stage、micro-batch offset、warmup/steady/cooldown；
- B/W 解耦、DP bucket 和 optimizer slack；
- residual tail、join release、continuation；
- 周期 cache 和对称 quotient。

### 9.2 哪些信息应暴露给多 Job 全局层

- Job 剩余通信及每资源负载；
- residual critical path；
- 下一 milestone/barrier 及 slack；
- arrival、weight、SLO、attained service 和 service vacation；
- 前 $K$ 个候选的边际推进价值；
- 候选的 resource footprint；
- 候选不确定性，即 top-1/top-2 margin 和本地 cache 是否失效。

### 9.3 哪些做法目前已被否定

- 每个 Job 永远只暴露一个本地最佳 flow；
- 全局仅用 task role 比较来自不同 Job 的 flow；
- 增大 $K$ 后仍只使用同一个粗 priority；
- 多资源中只按 tail 取 top-$K$，不保证 resource diversity；
- 用 makespan 实验代替 JCT/fairness 结论；
- Job 恢复服务后机械延续旧的周期时间表。

## 十、尚未完成的部分

本轮仍是阶段 6 的初步闭环，不代表完整多 Job 研究结束：

1. 真实 AICB 多 Job 快照尚未缩减到可审计 teacher 窗口；
2. 当前 Exact 主要是 2 Job，尚未系统覆盖 3--4 Job 的 30 个 ground truth；
3. 多资源只完成一个严格反例，尚未扫描 placement 和 3D mix；
4. Adaptive-$K$ 规则过于简单，没有用预测置信度和资源类别；
5. milestone/slack 目前只有 summary 字段和 priority 原型，尚未由 Oracle 学习；
6. weighted JCT Exact 已完成，但还没有带 starvation bound 的公平策略；
7. 尚未加入非零抢占成本、最小 quantum 和抢占预算；
8. 尚未直接测量 service vacation 后阶段 5 周期 cache 的失效率。

## 十一、下一步建议

1. 把候选接口改为 `critical + continuation + min-slack + per-resource representative`，而不是普通 top-$K$；
2. 用 Flat Exact/Beam 标注候选，在 Job summary 上学习“是否需要扩大 K”；
3. 对 3--4 Job 小图实现 Adaptive-$K$ 的 Exact regret 校准；
4. 从真实 AICB 图提取 2--3 个 phase window，组合成高冲突/资源隔离的 multi-job real benchmark；
5. 多资源全局层使用跨 Job compatible-set Rollout，而不是贪心 pack；
6. 分开训练 makespan、weighted JCT 和 slowdown/fairness policy；
7. 引入显式 quantum 后，再研究 attained-service 和最大 slowdown 保证；
8. 将 service vacation 和边界状态距离接入阶段 5 的周期 cache 失效检测。

当前最值得优先推进的是第 1、2、4 项。它们直接检验粗粒度接口能否在真实 LLM mix 上保持较小 $K$，这是分层架构是否真正有价值的关键。

## 十二、产物与复现

代码：

- `src/preemptive/multi_job.py`：组合、指标、Exact、分层单/多资源算法和反例；
- `src/preemptive/multi_job_study.py`：Exact 小图、目标函数和多资源实验；
- `benchmark_generate/simai/multi_job_study.py`：SimAI pipeline 双 Job probe；
- `tests/preemptive/test_multi_job.py`：语义、top-1、目标函数和多资源测试。

原始结果：

- `preemptive阶段6_实验结果.json`；
- `preemptive阶段6_pipeline实验结果.json`。

复现：

```powershell
$env:PYTHONPATH="src;."
python -m preemptive.multi_job_study --samples 30 --seed 260812 `
  --output "docs\preemptive研究\preemptive阶段6_实验结果.json"

python -m benchmark_generate.simai.multi_job_study `
  --output "docs\preemptive研究\preemptive阶段6_pipeline实验结果.json"
```

