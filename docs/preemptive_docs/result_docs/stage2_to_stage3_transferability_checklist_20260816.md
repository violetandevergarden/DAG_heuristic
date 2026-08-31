# Stage 2 → Stage 3 可迁移性清单

日期：2026-08-16

## 1. 使用方式

本文回答 Stage 2 `single_channel/complex_chain/preemptive` 的哪些成果可以进入 Stage 3 `muti_channel/preemptive`。Stage 3 保留一般 DAG、task-event 抢占、compute 自动且不可抢占、零抢占开销、无主动 WAIT 和 makespan 目标，但 communication 使用一个或多个固定资源；资源集合不冲突的 communication 可以并行。

清单分为三类：

- **直接复用**：与资源数无关的语义、验证或研究纪律；
- **复用框架但必须重新实现或证明**：概念可迁移，单 channel 公式、状态或算法不可照搬；
- **禁止外推**：依赖单 channel 排他性或单动作选择的结论。

目录名 `muti_channel` 是当前公开 schema 与 Python 包名，本阶段不顺手更名。

## 2. 可直接复用

| 项目 | 可迁移内容 | Stage 3 使用要求 | 状态 |
|---|---|---|---|
| DAG 语义 | finish-to-start、同刻事件原子处理、compute ready 后自动开始且不可抢占 | 多资源只改变 communication 并发，不改变依赖闭包 | 可直接复用 |
| communication remaining | 暂停保存剩余工作，恢复无额外开销 | 启动/暂停必须同时获取/释放完整固定资源集 | 可直接复用 |
| 无主动 WAIT | 有可加入且不冲突的 communication 时不得故意闲置可用资源 | 合法动作必须是 work-conserving compatible set | 原则直接复用 |
| Trace 审计纪律 | 工作量守恒、依赖、compute 连续性、最终完成 | 增加逐资源排他、同时占有全部需求资源的验证 | 框架直接复用 |
| Exact 纪律 | 公共 simulator 是唯一 transition；timeout/state limit 不算 optimal | 多资源 Exact 仍需 normalized/uncompressed/独立小图三方核验 | 可直接复用 |
| Residual 纪律 | 所有分数使用当前 remaining state；稳定 tie-break；不得读 metadata/reference | 资源冲突特征也必须从当前状态和固定 resource set 得到 | 可直接复用 |
| 实验分层 | random/adversarial/real 分开；raw 结果与摘要分离 | Stage 3 需要按资源冲突图、资源数和需求集合宽度再分层 | 可直接复用 |
| 大图诚实度 | primal 算法间比较；`[lower bound,best feasible]` 表示未知区间 | 区间宽度不解释为算法 gap 或 approximation ratio | 可直接复用 |
| 风险结构检查 | LT 小图失败集中在 join/barrier 和跨多次决策投资 | 在真实多资源 DAG 中检查这些结构是否与热点资源冲突叠加 | 可直接复用为告警，不是定理 |

## 3. 可迁移框架，但必须重新实现或证明

### 3.1 Simulator 与合法动作

- Stage 2 的“选择一个 eligible communication”必须改为“选择一个资源兼容通信集合”。
- 一个 communication 启动或恢复时必须原子获得全部固定资源；不允许部分获取、迁移、动态选路或比例共享。
- work-conserving 不等于任选 maximal set 后停止。需要定义：动作集合中不能再加入任何 eligible 且资源不冲突的 communication；算法负责在多个 work-conserving compatible set 间选择，simulator 负责验证。
- 下一事件可能来自任一并行 communication 完成或任一 compute 完成；同刻完成必须原子处理后再形成下一合法集合。
- Stage 2 的 forced idle 逻辑只能复用概念，不能复用“eligible 为空”的单 channel 判定。Stage 3 forced idle 是不存在任何可运行 communication 且仍有未来事件。

### 3.2 状态与 Exact

- Stage 2 normalized key 的 per-task `(status,remaining)` 证明不能直接迁移。Stage 3 必须证明它是否足以推出当前并行运行集合与资源占用；若 simulator 状态另存 active allocation，则 key 必须保留或可由 task status 唯一重建。
- 未压缩 audit key 至少保留绝对时间、所有 runtime task 字段、当前 active communications 和资源占用。
- 去重和时间支配只能发生在资源占用与全部未来释放信息等价的状态之间。
- Exact 分支从单个 task 变成 compatible set，分支数可能由 eligible 数量的线性规模变成组合规模；需要 compatible-set 枚举、支配剪枝和资源冲突图分解。
- 对资源互不相交的连通分量可研究安全分解，但必须考虑它们是否通过 DAG join/barrier 再次耦合。

### 3.3 Lower bound

- 单 channel 的通信总量 `P` 不再是 makespan 下界，因为不冲突通信可以并行。
- 可迁移的候选是每个固定资源上的 residual load，下界取 `max_r load(r)`；占用多个资源的通信在每个所需资源上都计入完整 residual work。
- 忽略资源竞争的 residual precedence longest path `L` 仍是安全候选。
- 基础知识区间可使用 `[max(max_r load(r), L), best feasible]`，但只表达尚未知的空间。
- 更强的 conflict/clique、cut 或 demand bound 必须独立证明，不能把单 channel 总 demand 直接相加。
- Lower bound 主要服务小图 Exact 和知识区间，不作为大图 heuristic 优劣指标。

### 3.4 Priority 与 compatible-set 选择

- Longest-tail 可作为每个 communication 的局部分数基线，但“取分数最大的一个”不再定义完整动作。
- 需要比较至少三种集合构造：按 task priority 贪心装填、直接给 compatible set 打分、在资源冲突图上做有预算的组合选择。
- 单任务分数相加可能重复计算 shared downstream；Stage 2 的 shared-downstream 去重在 Stage 3 需扩展到集合联合可达子图。
- `downstream_demand` 应迁移为资源向量或热点资源 demand。Stage 2 中它 mean 改善但 observed worst 变差，因此只作为候选信息，不能直接宣称更稳。
- 需要显式研究集合互补性：两个单独分数一般但资源互补的 communication，可能比两个高分但冲突的 communication 更好。
- join/barrier urgency 必须结合各分支所需资源和预计到达时间，不能只累计可达 barrier tail。

### 3.5 Rollout

- Rollout 的 receding horizon、memoized residual cost、budget/fallback 和 forced-idle 不消耗决策深度可以复用。
- 每层分支单位改为 compatible set；memo key 必须使用 Stage 3 已证明的 future-equivalent key。
- baseline completion 必须是确定性的 work-conserving set policy，不能逐个调用单 channel LT。
- 主要部署研究比较应是“资源感知 LT-compatible-set baseline → 有预算 Rollout”的 primal 改善和退化率。
- Stage 2 压力实验已显示 Rollout completion 成本增长快；Stage 3 组合分支更大，必须从第一版就设置 node/time budget、结构化 fallback 和增量 completion cache。

### 3.6 Beam

- Beam-8/32 只迁移为实验上界/离线对照，不是部署候选，不主张鲁棒性，反例未穷尽。
- 不把寻找固定宽度 Beam 反例列为 Stage 3 退出条件。
- registry 中若保留 Beam，必须继续使用 `development_status=experimental` 和“非部署候选”描述。

### 3.7 Benchmark 与真实投影

- Stage 2 一般 DAG 结构可作为拓扑骨架，但每个 communication 必须增加自包含的固定资源集合。
- random 集需要控制资源数、每任务资源集合大小、热点资源 load、冲突图密度、最大 compatible-set 大小及资源需求重叠。
- adversarial 至少覆盖：高 tail 任务相互冲突而次高 tail 可并行、greedy maximal set 陷阱、多资源原子获取、join 分支落在不同热点资源、shared downstream 重复计权。
- real 投影必须显式传 topology，记录路由如何冻结为 resource set；没有 topology 时不得虚构真实多 channel 结论。

## 4. 禁止直接外推

| Stage 2 成果 | 不能迁移的原因 | Stage 3 处理 |
|---|---|---|
| 单 channel 极化后的“每次选一个通信” | 多资源允许不冲突通信并行 | 选择 work-conserving compatible set |
| 通信总量 `P` 下界 | 并行通信可同时消耗不同资源 | 改为最大逐资源 residual load |
| 单 channel utilization | 多资源利用率是向量，平均值会掩盖热点和碎片 | 报告逐资源 busy、热点利用率和可用资源碎片 |
| LT/Delay/LRPT 的单任务排序结果 | 集合质量包含冲突与互补性 | 重新定义 set construction 并消融 |
| Stage 2 normalized key 证明 | active 并发集合和资源占用可能影响未来 | Stage 3 逐字段重证并与 audit Exact 对拍 |
| Stage 2 Rollout 复杂度 | compatible-set 分支是组合级 | 新预算、新 memo key、新 fallback |
| Beam-8 observed optimal | 当前集合小且反例未穷尽，且 Beam 不部署 | 只作实验上界/对照 |
| downstream-demand mean 改善 | observed worst 同时变差，且单 channel demand 是标量 | 改成资源感知特征并重新验证稳定性 |
| Stage 2 LT 84.21% / Rollout 100% | 38 图没有资源兼容集合选择 | Stage 3 重新生成 ground truth 和正式分母 |

## 5. Stage 3 评价口径

### 5.1 Exact 可解小图

- 报告 Exact status、states、runtime、resource-set branching 和 timeout；
- 报告 baseline/heuristic/rollout 相对 OPT 的 optimal rate、mean/worst gap；
- 从 baseline 失败图提取资源冲突、join/barrier、compatible-set 互补性等结构标签；
- 用失败结构指导大图风险检查，不把小图统计当理论保证。

### 5.2 Exact 不可解中大图

- 主指标是 candidate 相对稳定 baseline 的 primal 改善、持平率、退化率、worst regression 和 runtime；
- 报告 `[max(max_r load(r),L), best feasible]` 及区间宽度，区间只表示未知程度；
- 分别报告逐资源利用率、热点资源 idle、资源碎片、抢占和 compatible-set 大小；
- 在 random/adversarial/real 三层分别报告，不能用大量随机图稀释攻击集退化；
- 对含 Stage 2 LT 失败信号的真实 DAG 单列结果：join/barrier、嵌套同步、跨多次决策投资，再叠加热点资源冲突。

## 6. Stage 3 首轮实施顺序

- [ ] 冻结 fixed-resource-set family contract；拒绝动态选路、部分资源获取和资源未知的 communication。
- [ ] 用两个不冲突通信、两个冲突通信、多资源原子获取和同刻并行完成最小图复核 simulator。
- [ ] Trace 独立验证每个区间同时占有全部需求资源，且每个资源容量不超过 1。
- [ ] 定义并测试 work-conserving compatible-set 合法动作；区分 maximal 与优化意义上的 best set。
- [ ] 建立 uncompressed 小图 Exact，与独立 tick/set 枚举 Oracle 对拍。
- [ ] 逐字段证明 Stage 3 normalized key；未证明前不做有损压缩。
- [ ] 实现资源感知 LT greedy baseline，以及至少一个能处理集合互补性的 set policy。
- [ ] 把 downstream demand 扩展为逐资源/热点向量，验证 mean 与 worst，不只报告平均值。
- [ ] 实现有硬预算的 compatible-set Rollout；默认 fallback 到确定性 baseline。
- [ ] Beam 仅保留实验上界，不进入部署候选矩阵，也不搜索固定宽度反例。
- [ ] 建立 resource-conflict random/adversarial/real benchmark，并生成新的 reference hash。
- [ ] 按 primal 改善、知识区间和风险结构完成第一轮报告。

## 7. Stage 3 验收门槛

1. simulator 能原子执行固定多资源 communication，并在同刻事件后正确重算 compatible set；
2. work-conserving 合法性由 simulator 验证，算法不自行维护另一套资源占用；
3. Trace 对工作量、依赖、compute 连续性、逐资源排他和完整资源获取全部通过；
4. Exact 与独立小图 Oracle 一致，timeout 不进入 optimal 分母；
5. normalized key 对 active allocation 和 resource occupancy 的处理有书面 future-equivalence 证明；
6. 至少一个稳定 baseline 和一个资源感知候选完成 small-Exact 与 large-primal 评价；
7. 大图报告 candidate→baseline primal 改善/退化，以及 `[LB,best]` 知识区间；
8. Beam 明确为 experimental upper bound，不作为部署候选或阶段退出条件；
9. Stage 2 的单 channel `P`、单任务排序、observed optimal rate 没有被误写成多资源结论。

达到这些条件后，Stage 2 的一般 DAG 研究框架才算受控迁移到 Stage 3；仅把 resource 字段加到 benchmark、再顺序运行单 channel policy，不构成多资源算法迁移。
