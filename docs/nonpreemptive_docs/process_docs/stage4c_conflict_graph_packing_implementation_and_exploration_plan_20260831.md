# Stage 4c 不可抢占冲突图与启动集合：代码实现和算法探索方案

## 1. 文档定位

本文把以下两份正式计划落实为可执行的代码实现和算法探索步骤：

- `docs/nonpreemptive_docs/plan_docs/stage4_LLM_search.md`；
- `docs/nonpreemptive_docs/plan_docs/stage4c_conflict_graph_packing.md`。

本阶段只研究不可抢占固定多资源场景。问题不是重新选择所有正在通信的任务，而是在每个真实完成事件之后：

1. 保留全部正在运行的 communication 及其资源占用；
2. 从尚未被占用的资源上，选择一组可以同时启动的 ready communication；
3. 在 `optional_idle` 中还可以选择合法 WAIT 或非极大启动集合；
4. 在 `work_conserving` 中，新启动集合必须相对于当前剩余空闲资源达到包含意义下的极大。

本文是从当前公共不可抢占模拟器和已有 benchmark 出发的新实现方案，不是对可抢占 Stage 4c 的迁移，也不是代码审查或修正报告。可抢占 packing 的冲突图、预算记账和反例只能提供实现形式上的参考，其动作合同、极大集合和状态转移不能直接复用。

基础目标仍是最小化 makespan。Stage 4c 不在本轮引入 JCT、公平性或动态路由目标；multi-job 输入若参与，只按单一 makespan 目标报告，其他目标留给 Stage 4f。

## 2. 当前基础与证据边界

### 2.1 已有可复用基础

当前仓库已经有以下不可抢占固定多资源资产：

- `src/muti_channel/nonpreemptive/solver.py` 中的 `NonPreemptiveMultiResourceDAG`；
- `ResourceState`、`ResourceAction` 和公共 `step` 状态转移；
- `ready_flows`、`active_flows`、`occupied_resources` 和 `compatible` 查询；
- `optional_idle` 与 `work_conserving` 两套 `legal_actions`；
- 小图 `exact_oracle`、若干贪心策略和完整动作 rollout 原型；
- 17 个固定不可抢占多资源 benchmark，其中包含 random、adversarial 和手工 route 快照；
- active reservation、非极大启动和两种动作口径差异的定向测试；
- Stage 4d 已实现的不可抢占薄适配器、从可达状态求 cost-to-go 的 Exact 和独立进程硬超时设施。

这些资产负责语义回归、Exact 标签和简单基线，不自动构成 Stage 4c 的算法结论。

### 2.2 当前实现不能直接当作 Stage 4c 完成

现有代码存在以下阶段性限制：

1. `start_subsets` 会枚举全部非空兼容子集，再筛选极大集合，只适合很小的 Exact 图；
2. `legal_actions` 同样依赖上述枚举，中图不能为了验证一个动作或统计候选数而调用它；
3. `greedy_action` 只生成一个按逐通信顺序补全的极大集合，没有独立的冲突图、多个起点、局部交换和整集合评分；
4. `schedule_rollout` 是 R4 的全路径原型，使用软墙钟检查并在最后离线取 baseline 与候选日程的较优者，不是本阶段正式的在线 packing 方法；
5. `experiments/llm_structure/nonpreemptive/runtime.py` 中的 optional-idle WAIT 是基线规则的一部分，不能代替 Stage 4c 对非极大集合和 WAIT 的系统探索；
6. `src/llm_structured/packing_features.py` 导入的是可抢占多资源冲突图，不能用于不可抢占 active reservation 状态；
7. 现有可抢占 `packing.py` 默认只允许全局极大动作，而不可抢占 Stage 4c 必须分别处理“保留 active 后的新极大集合”和 optional-idle 非极大集合。

因此，本阶段新增一个语义专属实现目录，不修改可抢占 packing 的含义，也不让实验代码实现另一套时间推进。

### 2.3 Stage 4a 真实输入边界

截至 2026-08-31，不可抢占 Stage 4a 已发布 38 个真实派生样例：30 个小图、8 个中图，没有大图。其中只有 2 个是固定多资源 routed 中图，均为 2038 个任务，分别来自 Alibaba HPN 16G 和 Cassini 24G topology 投影；其余 36 个为单 channel。

这意味着 Stage 4c 的真实固定多资源证据目前只有两个 topology case：

- 可以用于冻结配置后的可运行性、动作分歧和成本检查；
- 不能把两个样例上的改善称为跨模型、跨 topology 的稳定收益；
- 不能用 30 个单 channel Exact 小图冒充多资源 packing 的 Exact 证据；
- 本阶段没有大图实验，不重新恢复 Stage 4a 已取消的大图范围。

若从两个 routed 中图提取因果闭包切片，切片只作为 `real-derived` 实验输入，必须记录源 benchmark hash、选择决策状态、保留的祖先/后继、边界 release、被删除内容和资源映射变化，不修改 Stage 4a 已发布快照。

## 3. 正式问题和动作合同

### 3.1 状态集合

在不可抢占多资源状态 `s` 中定义：

- `A(s)`：已经启动且未完成的 communication；
- `E(s)`：依赖已经满足但尚未启动的 communication；
- `O(s)`：`A(s)` 当前占用的资源并集；
- `F(s)`：全部固定资源减去 `O(s)`；
- `V(s)`：`E(s)` 中资源集合与 `O(s)` 不相交的 communication。

`A(s)` 不是候选顶点。算法无权停止、替换或重新排序 `A(s)`。`E(s)` 中与 active reservation 冲突的任务继续等待，不能因它们已 ready 就加入新启动集合。

### 3.2 冲突图

当前状态冲突图记为 `G_s=(V_s, C_s)`：

- 顶点为 `V(s)`；
- 两个顶点共享任一固定资源时连边；
- 顶点保存任务 ID、完整 duration、residual tail、固定资源集合和稳定输入顺序；
- 图对象额外保存 active、occupied resources、被 active 排除的 ready communication 和构图截断状态。

冲突图只表示“此刻能否一起新启动”，不表示长期调度质量。它不能编码动态路由、带宽共享或抢占。

### 3.3 合法新启动集合

集合 `S` 合法，当且仅当：

1. `S` 非空且 `S` 是 `V(s)` 的子集；
2. `S` 内任意两个 communication 不共享资源；
3. `S` 与 `O(s)` 不冲突；
4. task ID 唯一并按稳定规则规范化。

work-conserving 还要求 `S` 为包含意义下的极大集合：不存在 `v in V(s)\S` 可以在不冲突的情况下加入 `S`。这里要求的是 maximal，不是最大基数，也不是最大权独立集。

optional-idle 允许合法非极大 `S`。只有状态中存在正在运行的 compute、communication 或正式 job arrival 等真实未来事件时，空动作 WAIT 才合法：

- `V(s)` 非空时 WAIT 是主动等待；
- `V(s)` 为空但存在未来事件时 WAIT 是 forced idle；
- 没有未来事件时不得生成 WAIT。

### 3.4 公共模拟器边界

packing 代码只负责产生和选择 `ResourceAction`。动作执行一律调用公共 `model.step(state, action)`，不得自行：

- 推进到固定 tick；
- 减少 running communication 的剩余时间；
- 释放 active reservation；
- 启动 compute；
- 处理同刻完成事件；
- 推断新的 ready 集合。

候选评分若需要观察“启动完整集合后的状态”，也必须对当前不可变状态调用公共 `step`。不能只执行部分 duration，也不能在通信中途换集合。

## 4. 代码实现总览

建议新增：

```text
src/llm_structured/nonpreemptive/packing/
├── __init__.py
├── contracts.py       # 配置、结果、统计、候选和预算合同
├── graph.py           # active-aware 冲突图和只读状态摘要
├── legality.py        # 非枚举式动作校验的薄封装
├── features.py        # residual 顶点特征和整集合并集特征
├── baselines.py       # FIFO、固定顺序、LT 的稳定补全
├── constructors.py    # 多起点、贪心补全和候选去重
├── exchanges.py       # 有界一换一、一换二
├── optional.py        # 非极大 challenger 和 WAIT 候选
├── selectors.py       # 静态选择及有限完整动作反事实
├── policy.py          # 调度循环，只调用公共 legal/step
└── metrics.py         # 决策级和全日程统计
```

建议新增实验入口：

```text
experiments/llm_structure/nonpreemptive/
├── stage4c_common.py
├── stage4c_manifest.py
├── stage4c_census.py
├── stage4c_labels.py
├── stage4c_ablation.py
├── stage4c_evaluate.py
└── stage4c_medium_check.py
```

建议新增测试：

```text
tests/llm_structured/nonpreemptive/packing/
├── test_graph.py
├── test_legality.py
├── test_constructors.py
├── test_optional_actions.py
├── test_set_features.py
├── test_exchanges.py
├── test_budget.py
├── test_exact_labels.py
└── test_policy.py
```

不新增独立模拟器，不让 `src/` 导入 `experiments/`，不让在线算法读取 benchmark metadata、provenance、manifest、reference result 或 SimAI。

## 5. 公共接口的最小补充

### 5.1 为什么需要非枚举式合法性接口

当前 `legal_actions` 为 Exact 返回完整动作空间是合理的，但在 ready communication 较多时，枚举所有兼容子集会指数增长。Stage 4c 中图策略只需要：

- 查询一个给定 START(set) 是否符合指定 mode；
- 查询 WAIT 是否有真实未来事件；
- 检查 work-conserving 集合是否极大；
- 获取与 active reservation 兼容的 ready communication。

这些检查都可以线性或按资源脚印完成，不应先生成完整动作空间。

### 5.2 建议增加的方法

在 `NonPreemptiveMultiResourceDAG` 中增加公开、只读或校验型接口：

```python
def startable_flows(self, state: ResourceState) -> tuple[str, ...]: ...
def has_future_event(self, state: ResourceState) -> bool: ...
def is_maximal_start(self, state: ResourceState, starts: Iterable[str]) -> bool: ...
def validate_action(
    self,
    state: ResourceState,
    action: ResourceAction,
    mode: OracleMode,
) -> None: ...
```

要求：

- `startable_flows` 等于 ready 且与 active reservation 单独兼容的任务；
- `is_maximal_start` 相对 `startable_flows` 判断，不把 active flow 当作待补全顶点；
- optional-idle 接受任意合法兼容非空集合和合法 WAIT；
- work-conserving 在存在 startable flow 时拒绝 WAIT，并拒绝非极大集合；
- 没有 startable flow但存在未来事件时，两种 mode 都只允许 forced WAIT；
- `legal_actions` 在小图上仍与 `validate_action` 逐项对拍；
- `step` 保持通用状态转移，不在其中隐式选择 mode。

该修改是为避免指数枚举的公共语义接口，不改变现有 Exact 的动作空间。若不修改公共模型，Stage 4c 不得在算法内部复制一份口径不一致的 legality 判定。

## 6. 数据合同、配置和预算

### 6.1 主要数据结构

`contracts.py` 至少定义：

- `PackingMode`：`optional_idle` 或 `work_conserving`；
- `ConflictGraphSnapshot`：顶点、边、脚印、active、occupied、blocked-ready；
- `SetFeatures`：整集合特征，所有集合字段使用并集或明确的 max/min；
- `PackingCandidate`：动作、来源、seed、是否极大、特征和稳定签名；
- `PackingConfig`：构造器、选择器、候选和预算参数；
- `DecisionBudget`：单决策硬计数账本；
- `PackingDecision`：baseline、候选、选择、fallback 和统计；
- `PackingScheduleResult`：makespan、trace、完整率、动作与成本指标。

配置必须版本化并可序列化。正式结果保存完整配置内容和 hash，不能只保存一个方法名。

### 6.2 每决策硬预算

预算在进行工作前预留，不在超额后补记。至少限制：

- `max_vertices_scored`：最多计算多少个顶点的较贵特征；
- `max_seeds`：最多使用多少个不同起点；
- `max_pack_operations`：兼容性检查、补全和交换总操作数；
- `max_candidates`：去重后保留的集合数，LT baseline 不得被挤掉；
- `max_exchanges`：局部交换尝试数；
- `max_feature_nodes`：后继并集访问节点数；
- `max_completion_calls`：完整动作反事实次数；
- `decision_time_limit_s`：单决策软墙钟边界；
- `schedule_time_limit_s`：单次完整策略外部硬墙钟边界；
- `memory_limit` 或等价的进程级峰值监测。

任何预算耗尽都回退到已经构造并验证合法的 residual LT 动作。结果记录耗尽发生在哪一层，不能统一写成 `fallback=true` 后丢失原因。

### 6.3 确定性

除明确的随机对照外，同一 benchmark、state、mode 和 config 必须得到同一动作。所有排序最终以稳定 task ID 或输入索引收尾。集合规范化为排序后的 tuple，候选按动作签名去重。

随机多起点保存 seed；随机方法不能使用更多候选或 completion call 后与确定性方法比较。

## 7. 冲突图和特征实现

### 7.1 图构建

`graph.py` 按以下顺序构造：

1. 从模型读取 `active_flows` 和 `occupied_resources`；
2. 读取 `ready_flows`；
3. 将与 occupied resources 冲突的 ready task 记入 `blocked_by_active`；
4. 其余 task 成为顶点；
5. 对顶点固定资源集合做倒排索引；
6. 只在共享资源的顶点间生成边；
7. 记录顶点数、边数、密度、最大度、连通分量和资源热点。

不使用两两任务全扫描作为中图默认实现。先建立 `resource -> vertices` 倒排，再生成去重边；仍需按 `max_pack_operations` 截断统计。截断表示图统计不完整，不能解释为无冲突。

### 7.2 顶点特征

第一版只使用公共 DAG 和 residual state 可得到的特征：

- residual Longest Tail；
- communication 完整剩余 duration；
- 固定资源脚印大小；
- 每个资源的 residual communication load；
- 当前冲突度和冲突邻居中的最大 tail；
- 完成该通信后可直接释放的 compute/communication；
- 下游可达任务集合或其有界摘要；
- 完整执行期间，下一个 active compute/communication 完成事件是否更早到达；
- 被其资源持续阻塞的高 tail ready communication。

pending communication 使用完整 duration，running communication 不进入候选。active communication 的 remaining 只用于未来事件和资源占用上下文。

### 7.3 整集合特征

整集合评分不得简单累加成员局部分数。至少计算：

- `covered_resources`：集合资源并集；
- `reachable_union`：集合成员下游任务并集；
- `immediate_release_union`：执行公共完整动作后新 ready 任务并集；
- `excluded_critical`：未入选且因集合资源而被阻塞的高 tail 顶点；
- `max_selected_tail` 和 top-k tail 摘要；
- 集合中最长 duration 和 duration spread；
- 下一事件时仍会 active 的成员数及资源并集；
- 启动后资源热点连续占用量；
- 集合大小、资源覆盖数和空闲资源数；
- 是否为极大集合、是否主动留空及留空资源。

`reachable_union` 的任务只计一次。成员共享同一 join 或下游链时，不能重复奖励。第一版不从 task role/name 猜测答案；LLM 结构特征应等 Stage 4b 得到真实证据后再作为消融加入。

### 7.4 真实启动后特征

对于保留的少量候选，可以调用一次公共 `step` 得到真实下一事件状态，并比较：

- 哪些 active task 在该事件完成；
- 哪些 compute 自动开始；
- 哪些 communication 新 ready；
- 哪些已启动 communication 仍在运行并保留资源；
- 时间推进量。

这属于“一步完整动作特征”，不是 rollout，也不是 Exact。未完成整条候选 communication 并不违反不可抢占语义：公共 `step` 推进到下一个真实事件时，尚未完成的候选仍保持 active，算法不能撤销它。

## 8. 候选集合构造

### 8.1 必须保留的简单基线

每个可启动状态至少构造：

- FIFO 顺序补全；
- 输入固定顺序补全；
- residual Longest Tail 顺序补全；
- 随机顺序补全，作为同成本对照；
- 当前 mode 下的 LT baseline。

“补全”指从空集合或合法 seed 开始，按顺序加入仍兼容的 communication。work-conserving 的结果必须继续补到极大；optional-idle 的基线也保留同样极大 LT packing，非极大和 WAIT 作为单独 challenger，避免把 WAIT 收益与基础排序变化混在一起。

### 8.2 多起点贪心

选择少量 seed 后，再用冻结的 LT/FIFO/资源热点顺序补全。seed 来源包括：

- 最大 residual tail；
- 最短/最长完整 duration；
- 最大资源热点负载；
- 最大冲突度；
- 最大“冲突邻居 tail 风险”；
- 每个较大冲突图连通分量的代表点；
- 固定 seed 的随机顶点。

seed 和补全顺序是两个独立因素，实验中分别消融。候选数到达上限后停止，不为覆盖所有 seed 继续扩张。

### 8.3 一换一

从 LT baseline 集合开始，尝试移除一个已选成员，加入一个原先被冲突排除的成员，再按冻结顺序补全。仅保留动作不同且合法的结果。

一换一用于发现“一个大资源脚印任务阻塞一个更关键任务”的错误，不枚举全部成对组合。优先尝试：

- 被排除任务 tail 更高；
- 被排除任务 duration 更短；
- 被排除任务资源脚印更小；
- 被移除任务与多个高 tail 顶点冲突。

### 8.4 一换二

从一个已选成员出发，只考虑两个彼此兼容且都与该成员冲突的未选顶点。移除该成员、加入这两个顶点后再补全。

该操作专门检查“一个宽通信与两个窄通信”的 packing 反例。候选对按边界分数预筛，计入 `max_exchanges` 和 `max_pack_operations`，不得对全部未选点做无界二次枚举。

### 8.5 小图枚举

只在顶点数和图分量规模低于冻结阈值时进行：

- work-conserving：枚举全极大兼容集合；
- optional-idle：枚举全合法非空兼容集合，并在合法时加入 WAIT；
- 每个连通分量可先枚举，再以有界方式组合分量结果；
- 达到状态、候选或墙钟限制时返回 `truncated`，不能称为全枚举。

正式中图方法不得调用 `model.start_subsets`。该方法只留给 Exact、小图交叉验证和测试。

### 8.6 optional-idle challenger

optional-idle 候选空间不能靠枚举所有非极大子集覆盖。第一版只保留有明确来源的有限 challenger：

- WAIT：仅当模拟器确认存在真实未来事件；
- LT baseline 的前缀或删除一个宽脚印成员后的集合；
- 为下一个更早到达的高 tail communication 保留其资源的集合；
- 一换一/一换二后不做极大补全的集合；
- 小图 Exact 标记过有价值的结构模板，但模板只能基于公共图和状态特征。

每个非极大候选记录主动留空的资源、当前可补却未补的 communication 以及所等待的真实事件。不能把“空闲可能有用”作为合法 WAIT 的依据。

## 9. 集合选择方法

### 9.1 P0：简单基线

P0 包括 FIFO、固定顺序、LT 和随机顺序补全。它们既是质量基线，也是所有复杂方法的安全 fallback。

### 9.2 P1：LT 多起点

用不同 seed 生成多个集合，仍按 LT 补全，最终使用静态整集合词典序选择。此方法用于隔离“候选覆盖”是否已经足够，不引入复杂加权模型。

建议第一版词典序优先保持：

1. 不显著损失集合最大 residual tail；
2. 减少被排除的高 tail 风险；
3. 减少热点资源的长时间连续占用；
4. 增加去重后的立即释放；
5. 最后按 LT baseline 和稳定动作签名处理并列。

阈值必须由 validation 冻结，不直接在两个真实 routed 中图上调整。

### 9.3 P2：LT 加局部交换

在 P1 基础上加入一换一，再单独加入一换二。分别统计：

- 新增多少不同候选；
- 修复多少 LT 首动作；
- 破坏多少 LT 首动作；
- 每次交换的构造成本；
- 哪类冲突图结构触发收益。

若一换二没有超过一换一，或成本显著上升，则不继续增加更大邻域。

### 9.4 P3：整集合并集评分

比较以下三种评分形式：

- 成员分数求和，作为明确的负面对照；
- 仅使用集合最大值、最小值和资源并集；
- 使用下游并集、立即释放并集和 excluded risk 的完整集合评分。

P3 的目标是检验去重和资源整体风险是否修复成员求和错误，不预设它一定优于 LT。

### 9.5 P4：一步完整动作反事实

对最多 `max_completion_calls` 个候选：

1. 执行一个完整合法 START(set) 或 WAIT 动作；
2. 保留仍 active 的全部通信；
3. 从下一事件状态使用同一冻结 LT completion policy 跑到结束；
4. 比较 `当前推进时间 + LT suffix makespan`；
5. 预算不足、异常或未完整评估时选择 LT baseline。

P4 是有界候选选择器，不是 Stage 4d selective rollout 的替代实现。若后续与 Stage 4d 联动，Stage 4c 只提供候选构造器，rollout 深度、触发和总预算由 Stage 4d 统一管理。

### 9.6 P5：optional-idle 有限选择

在 P1/P2 的极大候选之外加入有限非极大集合和 WAIT，并用同一 P4 完整动作反事实评价。静态分数不足以支持主动 WAIT；没有完整反事实或 Exact 证据时，online 默认选择 LT 极大集合。

optional-idle 的探索必须回答：

- 是 WAIT 有价值，还是只需非极大但非空的集合；
- 收益是否来自保留某个具体资源；
- 等待的事件是否真的释放了更关键 communication；
- 主动空闲时间是否被 makespan 收益覆盖；
- work-conserving 下同一状态的最优极大集合是什么。

## 10. Exact 标签与中图反事实

### 10.1 小图 Exact

对旧 17 个多资源 benchmark 和新提取的很小 real-derived routed slice，分别运行：

- `optional_idle` Exact；
- `work_conserving` Exact；
- 从有选择的可达状态求各合法首动作 cost-to-go。

每个状态保存：

- active、occupied、startable 和冲突图摘要；
- 全部合法首动作；
- 对应 mode 的最优动作集合；
- FIFO、固定顺序、LT 和各 packing 方法动作；
- 首动作 regret；
- Exact 状态数、runtime、status 和 termination reason。

只有 `status=optimal` 才作为标签。time limit、state limit 和截断枚举均标记 unknown，不当作错误动作或负样本。

Stage 4d 的 `cost_to_go` 已能从模拟器可达状态求值。实施时优先把真正通用的适配和 state Exact 接口以兼容方式提取到不可抢占共享目录，Stage 4d 保留导入兼容层；若提取会扩大改动，则 Stage 4c 标签脚本可以暂时调用现有薄适配器，但核心 packing 算法不得依赖 selective rollout 策略模块。

### 10.2 中图条件反事实

中图没有 Exact 时，只报告同一冻结 completion policy 下的条件值：

`Q_LT(s,a) = step_cost(s,a) + LT_completion(next_state)`。

它只能说明某首动作在 LT 后缀下较好，不能称为全局最优、Exact gap 或理论保证。所有候选使用相同 completion policy、tie-break、mode 和预算。

### 10.3 首个分歧状态

每个候选方法与 LT 发生第一处动作分歧时，保存可重放记录：

- benchmark hash 和 state fingerprint；
- time、active、ready、occupied、free resources；
- 冲突图和候选集合；
- LT 与候选动作及分数分解；
- 下一事件状态差异；
- 完整日程 makespan 或 unknown；
- trace 片段，不复制整个 benchmark。

该记录用于反例分析，不作为算法在线输入。

## 11. Benchmark 分层与执行顺序

### 11.1 第一层：已有 17 个多资源 benchmark

先使用 `benchmark/muti_channel/nonpreemptive/` 中现有的：

- adversarial：验证 active reservation、共享 route、非极大启动等机制；
- random：比较 Exact 首动作和候选覆盖；
- real：只作为手工 route 快照，不称为 AICB 真实训练图。

按生成 family、seed 和反例机制建立 development、validation、holdout 清单。同一 motif 的参数变体不能跨集合泄漏。

### 11.2 第二层：受控 100--1000 节点多资源图

在临时实验目录生成少量固定 seed，建议规模为 100、250、500 和 1000，每个规模覆盖：

- 稀疏冲突；
- 资源热点；
- 宽任务对多个窄任务；
- 多个冲突图连通分量；
- active reservation 在中间事件改变 startable 图；
- optional-idle 等待未来关键任务；
- LT 已足够的无收益对照。

这些图用于成本曲线、候选完整率和受控机制，不进入固定 benchmark，也不能支持真实 LLM 结论。生成器只使用固定资源模型，不加入动态路由或隐式计算串行。

### 11.3 第三层：真实 routed 切片

从两个 Stage 4a routed 中图的有选择状态提取少量因果闭包切片，优先选择：

- active reservation 存在且仍有多个 startable communication；
- 至少两个不同极大集合；
- LT、FIFO 或不同 seed 动作发生分歧；
- optional-idle 下 WAIT/非极大动作合法；
- 原 topology 资源冲突能够在切片中保留。

切片按源 topology 分组。它们可用于 Exact 或小规模反事实，但结论表述为 real-derived slice，不等同完整 routed workload。

### 11.4 第四层：两个 Stage 4a routed 中图

所有阈值、词典序、seed 数、交换数和预算在进入此层前冻结。两个 2038-task 图都不参与调参，只运行：

- FIFO、固定顺序和 residual LT；
- P1 LT 多起点；
- validation 上保留的 P2 或 P3 一种配置；
- 小图确有净收益且 pilot 通过时才运行 P4；
- optional-idle 与 work-conserving 分别执行。

当前没有真实多资源大图，不建立大图实验入口。

## 12. 算法探索轮次

### 12.1 研究假设

- H1：低冲突或冲突图分量很小时，LT 顺序补全已经足够；
- H2：star/wide-vs-narrow 冲突中，多起点和一换二可能修复 LT 的 seed 错误；
- H3：逐成员 tail 求和会因共享下游重复计分，整集合并集特征更可靠；
- H4：不可抢占完整 duration 和热点资源连续占用是集合退化的重要原因；
- H5：active reservation 会改变顶点集和极大性，忽略它会生成非法或不可执行动作；
- H6：optional-idle 的收益主要集中在少量“即将释放关键通信”的状态，而非普遍留空；
- H7：复杂构造若只带来极小 makespan 改善，可能不值得其 wall-clock 和内存成本。

### 12.2 E0：语义和冲突 census

在旧 benchmark、受控图和真实 routed 图的 FIFO/LT 路径上统计：

- 决策状态数、active 数和 occupied resource 数；
- ready、blocked-by-active 和 startable 数；
- 冲突图边数、密度、最大度和分量数；
- work-conserving 是否存在多个极大集合；
- optional-idle 是否存在非极大或 WAIT；
- 简单规则是否发生集合分歧；
- 分歧是否改变下一事件或最终 makespan；
- 构图和统计 wall-clock。

只扫描策略路径或有限前缀时标记 `observed_on_path` 或 `sampled_prefix`，不能认证其他可达状态无选择。

### 12.3 E1：基线重放与 Exact 对拍

先对 17 个旧图运行两种 mode 的 FIFO、固定顺序、LT 和 Exact：

- 验证现有结果 hash 未因接口补充而变化；
- 比较非枚举 `validate_action` 与完整 `legal_actions`；
- 建立 LT 首动作 regret 和最坏 gap；
- 定位 optional-idle 与 work-conserving 真正不同的状态。

若公共回归或 Exact 对拍失败，停止算法探索，先修复语义接口。

### 12.4 E2：候选覆盖

按以下顺序增加候选：

1. LT baseline；
2. FIFO/固定/随机顺序补全；
3. 不同 seed 的 LT 补全；
4. 一换一；
5. 一换二；
6. optional-idle 非极大和 WAIT。

每一步报告 Exact 最优首动作覆盖率、候选数、构造操作数、runtime 和新增覆盖。若候选覆盖不再增长，停止扩大 seed 或交换邻域。

### 12.5 E3：顶点特征消融

在相同候选集合上分别加入：

- residual tail；
- duration；
- 冲突度；
- 资源残余负载；
- excluded high-tail risk；
- 完整动作期间的跨事件风险。

每次只增加一项。报告支持例、反例、首动作命中、makespan 修复/破坏和计算成本，不直接做大规模权重网格搜索。

### 12.6 E4：整集合评分

比较成员求和、简单集合摘要和下游并集评分。重点检查：

- 共享后继是否重复奖励；
- 多个小通信是否覆盖不同关键分支；
- 大脚印长通信是否阻塞多个关键短通信；
- 当前填满资源是否延迟即将到达的关键任务；
- active reservation 下同一集合评分是否正确变化。

只有整集合方法在 validation 上同时改善平均值和最坏退化，才进入真实 routed 中图。

### 12.7 E5：局部交换范围

依次比较无交换、一换一和一换二。若一换二只增加候选而没有 Exact 覆盖或 makespan 收益，不探索一换三或通用局部搜索。

同时记录每次收益对应的最小冲突子图，使“为什么改进”可以由资源集合和完整 duration 解释。

### 12.8 E6：optional-idle

在两个 mode 分开的 Exact 标签上比较：

- work-conserving 最优极大集合；
- optional-idle 最优非极大集合；
- optional-idle 最优 WAIT；
- LT 极大集合；
- P5 的有限 challenger。

统计 WAIT 和非极大动作各自的出现率、收益、主动空闲时间及最坏退化。若有限 challenger 不能覆盖 Exact 中的 optional-idle 收益状态，则记录受限结论，不通过无界枚举掩盖。

### 12.9 E7：一步完整动作反事实

固定候选构造器后比较静态选择与 P4：

- 每个修复/破坏的决策；
- completion call 数；
- 单位调用的 makespan 收益；
- fallback 和超时；
- 相同总预算下与随机候选的对照。

P4 若成本接近 Stage 4d rollout，则不在 Stage 4c 复制更深搜索，只把候选构造接口交给 Stage 4d。

### 12.10 E8：冻结真实验证

配置在旧 benchmark、受控图和 real-derived slice 上冻结后，才运行两个完整 routed 中图。按 topology 逐样例报告，不能把两行合并为稳定胜率。

最终结论可以是：

- LT packing 已足够；
- 只需多起点或一换一；
- 整集合评分在特定冲突结构有效；
- optional-idle 只在少数可识别状态有效；
- 复杂 packing 成本不值得；
- 真实样本不足，当前只保留分析工具。

## 13. 必须保留的反例

至少建立以下可手算反例，并为两种 mode 保存时间线：

1. **active reservation**：ready task 与 running communication 共享资源，不能启动也不能替换 active；
2. **宽任务对两个窄任务**：一个多资源长通信与两个互不冲突短通信竞争；
3. **最大基数不是最优**：启动任务更多但关键 tail 更差；
4. **极大不是最大**：两个集合都极大但大小不同，禁止把概念混用；
5. **成员求和重复计数**：多个成员共享同一后继；
6. **长热点占用**：高 tail 宽通信连续阻塞更关键的未来 arrival；
7. **非极大非空最优**：启动一个任务并保留另一资源优于任何极大集合；
8. **WAIT 最优**：等待真实 compute 完成释放关键通信，优于立即启动；
9. **WAIT 假收益**：没有新事件或未来事件不改变候选，等待只会退化；
10. **多个独立分量**：分量内选择会通过 DAG 下游产生全局影响；
11. **LT 已足够**：复杂候选与 LT 相同或更差；
12. **名称置换**：改变 task role/name 不应改变只依赖图和状态的结果。

每个反例记录合法集合、Exact 首动作、最终 makespan、active 区间和逐资源占用。反例用于解释机制，不替代 AICB routed 证据。

## 14. 基线、消融与公平比较

正式比较至少包括：

- FIFO 补全；
- 输入固定顺序补全；
- residual LT 补全；
- 同候选预算随机多起点；
- P1 LT 多起点；
- P2 一换一；
- validation 保留时的 P2 一换二；
- P3 整集合并集评分；
- 小图 P4 一步完整动作反事实；
- optional-idle 下 P5；
- 小图对应 mode 的 Exact。

关键消融包括：

- 是否过滤 active-conflicting ready task；
- seed 与补全顺序；
- duration；
- resource load/hotspot；
- excluded candidate risk；
- 成员求和与下游并集；
- 一换一与一换二；
- 一步真实 transition 特征；
- WAIT；
- 非极大非空集合；
- optional-idle 与 work-conserving。

“不考虑 active reservation”只能作为会被 legality 拒绝的负面测试，不能运行成一条合法对照策略。所有可比较算法最终必须输出公共模拟器接受的动作。

同一比较固定 benchmark hash、mode、模拟器版本、LT 定义、tie-break、seed、候选预算、completion policy、外部墙钟和机器环境。offline best-of-two 若用于诊断，明确计入两次完整调度成本，不能作为在线算法排名结果。

## 15. 指标和结果状态

### 15.1 图与动作指标

- active、ready、startable 和 blocked-by-active 数；
- occupied/free resource 数；
- 冲突图顶点、边、密度、最大度和分量数；
- 启动集合大小、资源覆盖、是否极大；
- 构造候选总数、去重后数量和截断状态；
- baseline 与候选动作分歧数；
- 一换一、一换二和 optional challenger 命中数；
- WAIT、非极大非空动作和极大动作次数。

### 15.2 质量指标

- makespan；
- 相对 FIFO、固定顺序和 LT 的逐样例变化；
- 小图 Exact gap、最优率和最优首动作覆盖率；
- LT 修复数、LT 破坏数和并列改选数；
- optional-idle 相对 work-conserving 的差值；
- 下一事件时间、新 ready 数和后续关键 tail；
- 最坏退化样例及第一处分歧。

### 15.3 成本与可靠性

- 构图、顶点特征、集合特征、交换和 completion wall-clock；
- 兼容检查、构造操作、后继访问和 completion call 数；
- 峰值内存和缓存项；
- completed、fallback、timeout、failed、unknown、not_run_budget_gate；
- trace 验证状态；
- 主动 WAIT 次数/时间、forced idle 次数/时间；
- 总体和逐资源利用率；
- active communication 的连续区间数，每个通信必须恰为一个。

均值之外报告中位数、分位数、最大值、完整率和逐样例表。旧 benchmark、受控图、real-derived slice 和两个完整 routed 图分开，optional-idle 与 work-conserving 分开。

## 16. 预算和中图停止规则

### 16.1 初始预算建议

| 工作 | 单位 | 初始硬墙钟预算 |
| --- | --- | ---: |
| 旧小图 Exact | case × mode | 30 秒 |
| 旧图/切片在线 packing | case × mode × method | 15 秒 |
| 100--500 节点受控图 | case × mode × method | 30 秒 |
| 1000 节点受控 pilot | case × mode × method | 45 秒 |
| 2038-task routed 图简单方法 | case × mode × method | 90 秒 |
| 2038-task routed 图 P4 | case × mode × method | 90 秒 |

内部决策预算负责及时 fallback，`process_budget.py` 的独立进程负责整次运行硬超时。timeout 不能返回 completed，也不能只保留 fallback 之后的部分日程。

### 16.2 中图闸门

1. 先在 500 和 1000 节点受控多资源图上做构图、P1 和 P2 pilot；
2. 某方法在 1000 节点 pilot 超时、内存超限或候选构造无法完成，不进入完整 routed 图；
3. 真实 routed 图先在 Alibaba HPN case 上使用 30 秒 pilot，只检查能否安全完成或正常 fallback；
4. pilot 硬超时的方法不运行 Cassini case，后续行标记 `not_run_budget_gate`；
5. pilot 通过后，正式预算最多 90 秒，超时不提高预算重跑；
6. P2/P3 若比 LT 慢 5 倍以上且没有动作分歧，停止更复杂配置；
7. P4 若比 LT 慢 10 倍以上且没有任何改善，不运行第二个 routed case；
8. 候选构造若频繁 fallback，报告完成率和 fallback 前可用候选，不增加候选上限追求跑完；
9. 两个真实 case 都完成也不解除样本量限制；
10. timeout 和 `not_run_budget_gate` 保留在完整率分母中。

本阶段明确不死磕中图，更不恢复大图。算法复杂度达不到预算要求本身就是研究结果。

## 17. 测试计划

### 17.1 冲突图测试

- active communication 不进入顶点；
- 与 active reservation 冲突的 ready task 进入 blocked-by-active；
- 共享任一资源的顶点正确连边；
- 不相交资源不连边；
- 资源标签置换不改变合法集合和 makespan；
- 倒排构图与小图两两扫描结果一致；
- 构图截断明确标记，不返回“无冲突”。

### 17.2 动作合同测试

- START(set) 中 task 唯一、ready、与 active 兼容且内部兼容；
- work-conserving 拒绝非极大集合和可启动时的 WAIT；
- optional-idle 接受合法非极大集合；
- WAIT 只通向真实未来事件；
- 没有 startable flow 时的 WAIT 正确记为 forced idle；
- active flow 在中间 compute 事件后仍保留 remaining 和全部资源；
- 小图 `validate_action` 与 `legal_actions` 完整对拍。

### 17.3 构造器测试

- FIFO、固定顺序和 LT 补全结果确定；
- work-conserving 所有输出都极大；
- optional challenger 的非极大性和留空资源可解释；
- 多起点候选去重且始终保留 LT baseline；
- 一换一和一换二不产生冲突集合；
- 候选上限为零或耗尽时安全回退 LT；
- 同 seed 结果一致，不同 seed 只影响随机对照。

### 17.4 整集合特征测试

- resources、descendants 和 immediate release 使用并集；
- 共享下游只计一次；
- excluded candidate 只统计确实被所选资源阻塞的顶点；
- pending duration、active remaining 和 completed zero 正确区分；
- 一步特征来自公共 `step` 前后差，不自行推进；
- 特征访问上限达到时标记 truncated 并回退。

### 17.5 Exact 与选择器测试

- 两种 mode 分别得到正确最优值；
- unknown Exact 不进入最优率分母；
- 首动作 cost-to-go 与从该动作重放的后缀一致；
- P4 对所有候选使用相同 LT completion；
- completion 未完成或超预算时选择 LT；
- 估值并列时保留 LT；
- offline best-of-two 不注册为在线 packing 策略。

### 17.6 预算和实验合同测试

- 操作、seed、候选、交换、后继访问和 completion 均在工作前预留；
- 软预算耗尽后输出合法 fallback；
- 外部硬超时不输出 completed；
- timeout、failed 和 not_run 不被汇总过滤；
- development、validation、holdout 按 family/source group 隔离；
- 真实 routed 结果不用于返调配置；
- completed trace 可独立验证依赖、连续通信、资源排他和最终完成。

实施后至少运行当前 37 个不可抢占定向回归、Stage 4a 集成测试、Stage 4d 回归和全部 Stage 4c 新测试。若修改公共模拟器状态、Exact key、loader 或 benchmark，则运行完整测试集。

## 18. 实验入口和产物

建议入口：

```powershell
python -m experiments.llm_structure.nonpreemptive.stage4c_manifest --output <split_dir>
python -m experiments.llm_structure.nonpreemptive.stage4c_census --manifest <manifest> --output <report.jsonl>
python -m experiments.llm_structure.nonpreemptive.stage4c_labels --manifest <small_manifest> --output <labels.jsonl>
python -m experiments.llm_structure.nonpreemptive.stage4c_ablation --manifest <validation_manifest> --config <config.json> --output <results.jsonl>
python -m experiments.llm_structure.nonpreemptive.stage4c_evaluate --manifest <frozen_manifest> --config <frozen_config.json> --output <results.jsonl>
python -m experiments.llm_structure.nonpreemptive.stage4c_medium_check --manifest benchmark/llm_structure/nonpreemptive_manifest.jsonl --config <frozen_config.json> --output <results.jsonl>
```

结果归档：

```text
docs/nonpreemptive_docs/result_docs/
├── stage4c_conflict_census_<date>/
├── stage4c_exact_labels_<date>/
├── stage4c_candidate_coverage_<date>/
├── stage4c_controlled_ablation_<date>/
├── stage4c_real_derived_validation_<date>/
└── stage4c_routed_medium_cost_<date>/
```

每个目录保存：

- 输入 manifest、benchmark hash 和分组；
- 完整配置及 hash；
- 模拟器和代码版本；
- 机器环境、时间/内存/计数预算；
- 逐样例 JSONL；
- 第一处分歧状态；
- trace 验证和失败清单；
- 汇总脚本输出；
- 明确区分 observation、unknown 和 conclusion 的结果文档。

实验输出不得混入可抢占 Stage 4c 结果，也不得用文档 metadata 作为在线算法特征。

## 19. 实施顺序与闸门

### I1：冻结当前语义和基线

- 保存 17 个旧多资源 benchmark 的两种 mode 基线与 Exact 结果；
- 固定 residual LT 定义、tie-break 和 trace hash；
- 为两个 Stage 4a routed 图保存当前 FIFO/固定/LT 基线配对。

通过条件：旧回归和 Stage 4a 基线可复现，optional-idle/work-conserving 分表。

### I2：非枚举合法性接口

- 增加 startable、future event、maximal 和 validate 接口；
- 与小图完整动作枚举对拍；
- 确认不改变 `step` 和 Exact 值。

通过条件：所有合法性和 active reservation 测试通过，中图校验不调用完整子集枚举。

### I3：冲突图与 census

- 实现 active-aware 图、倒排边构造和统计；
- 在旧图、受控图和 routed 图策略路径上扫描；
- 输出选择存在性和构图成本。

通过条件：图与手算结果一致，截断/前缀证据不被写成全图证明。

### I4：基线构造器和预算

- 实现稳定补全、候选去重和共享预算账本；
- 保证 LT baseline 永远存在；
- 实现外部硬超时和合法 fallback。

通过条件：任意预算边界下都只返回指定 mode 的合法动作。

### I5：多起点和局部交换

- 先多起点，再一换一，最后有证据时一换二；
- 生成小图 Exact 候选覆盖报告；
- 保留最小支持例和反例。

通过条件：明确每层候选新增覆盖与成本；无增量则停止扩展。

### I6：整集合特征和选择器

- 实现下游/资源/释放并集；
- 对比成员求和负面对照；
- 冻结词典序或最小阈值配置。

通过条件：共享下游反例通过，validation 上报告净收益、最坏退化和成本。

### I7：optional-idle 与一步反事实

- 加入有限非极大集合和 WAIT；
- 对少量候选执行完整动作加同一 LT 后缀；
- 与对应 mode Exact 对拍。

通过条件：WAIT/非极大收益来源可解释，预算不足时回退 LT，不与 work-conserving 混表。

### I8：real-derived 冻结验证

- 从两个 routed 图提取可追溯切片；
- 不使用切片来源 metadata 作为特征；
- 运行冻结方法和 Exact/条件反事实。

通过条件：形成按 topology/source group 的动作分歧、质量和失败案例报告。

### I9：完整 routed 中图有限检查

- 按 30 秒 pilot 和 90 秒正式闸门执行；
- 只运行少数冻结配置；
- 超时不追加预算，不运行被闸门拦截的方法。

通过条件：给出两个真实 routed 图的完整率、makespan、成本、fallback 和停止原因。

## 20. 退出条件

只有同时满足以下条件，Stage 4c 才可以结束：

1. active、ready、startable、occupied 和 free resources 的合同明确且有测试；
2. 冲突图只包含与 active reservation 兼容的待启动 communication；
3. active communication 在全部 transition 中保持运行和资源占用，直到公共模拟器判定完成；
4. work-conserving 极大新启动集合与 optional-idle 非极大/WAIT 动作空间分别实现、Exact 和报告；
5. 中图策略校验不依赖全合法子集枚举；
6. 构造器只选择动作，所有推进、依赖释放、compute 自动启动和同刻事件处理都复用公共模拟器；
7. FIFO、固定顺序、LT、随机对照、多起点和候选方法使用统一输入和预算；
8. 小图 Exact 与独立 trace 说明候选覆盖、首动作 regret 和最终 makespan；
9. 整集合评分使用资源/下游并集，成员求和重复计数反例被保留；
10. 一换一、一换二、非极大集合和 WAIT 的独立贡献可以消融；
11. 所有计数、墙钟、内存、timeout 和 fallback 是可核验的硬边界；
12. 旧 benchmark、受控图、real-derived slice 和完整 routed 中图分开报告；
13. 两个 routed 中图的样本限制被明确说明，不外推为广泛稳定收益；
14. 中图 timeout 和 `not_run_budget_gate` 未被排除，也未通过提高预算掩盖；
15. 最坏退化和第一处分歧状态有可重放记录；
16. 最终明确 Stage 4c 结果属于推荐构造器、有限结构特化、仅分析工具、成本不值得或 LT 已足够中的哪一种。

若简单 residual LT 补全在 Exact、受控反例和两个 routed 中图上已经足够，应以受限或否定结论结束，不继续堆叠更大交换邻域。若复杂方法只在旧合成反例上有效、在真实 routed 图上无分歧或频繁超时，则只保留为测试/分析工具，不进入后续综合算法。
