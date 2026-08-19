# Stage 3 `muti_channel/preemptive` 旧实现审查

日期：2026-08-16

## 1. 审查范围与结论

本次审查只针对 Stage 3 固定多资源、单联合 DAG、可抢占 communication 的旧实现与旧结果。依据为：

- `docs/plan_docs/outline.md`；
- `docs/plan_docs/simulator.md`；
- `docs/plan_docs/stage3_muti_channel.md`；
- `docs/result_docs/stage2_to_stage3_transferability_checklist_20260816.md`；
- 当前 `src/muti_channel/preemptive/`、公共模型、registry、loader/schema、生成器、测试、benchmark、reference result 和实验薄接口；
- `docs/old_docs/preemptive研究/preemptive进度.md` 及 2026-08-15 的迁移结果材料。

本次没有修改代码、benchmark、reference result 或旧文档，也没有重新生成正式实验文件。`experiments/` 仅按薄的可复现实验入口审查，不把其中代码当成算法实现。

总体结论是：**旧 Stage 3 已经完成了一个可运行的固定资源集合原型，并且旧的 14 图数值可以在当前代码上完整复现；但它没有达到当前 Stage 3 计划的完成门槛。** 更准确的状态应写成：

> 固定多资源的基本事件语义、maximal compatible-set 动作、逐资源 trace 和小图 Exact 原型已经存在；可信 Exact 证书、公共模拟器边界、资源感知算法研究、解释性 benchmark、中大图评价和真实/结构化投影尚未形成完整闭环。

因此，旧文档中的“多资源核心、Exact 和四个 baseline 已形成小图闭环”只能保留为“旧原型闭环”的历史描述，不能作为当前 Stage 3 已完成的验收结论。

## 2. 验收门槛逐项审查

| Stage 3 门槛 | 当前状态 | 审查结论 |
|---|---|---|
| 固定资源集、完整原子获取、暂停恢复、无动态路由 | 基本具备 | 输入为固定非空资源集合，运行区间按完整集合生成资源占用；但缺少 Stage 3 专属 family contract 文档与更完整的输入回归 |
| 兼容通信并行、同刻事件原子处理 | 基本具备 | `step()` 对所有选中 communication 和 active compute 使用同一个最小事件增量，并在推进后统一做 compute closure |
| simulator 验证 work-conserving | 基本具备但模块边界不合格 | `legal_actions()`/`step()` 拒绝非 maximal 集合；但多资源状态机位于 `solver.py`，没有成为公共执行核心 |
| Trace 验证工作量、依赖、compute 连续性、逐资源排他和完整获取 | 基本具备 | 独立回放逻辑存在，并检查 resource interval 与固定资源集相等；定向错误轨迹测试仍不完整 |
| 未压缩 Exact 与独立 set/tick Oracle 一致 | 部分具备 | 有 12 个固定 seed 极小图的独立 tick 对拍，但正式 Exact 从一开始就使用压缩 key，没有未压缩 audit Exact |
| normalized key 有逐字段 future-equivalence 证明 | 未完成 | key 只有逐任务 `(status, remaining)`；当前稳定决策边界下可能是安全的，但没有 Stage 3 书面证明或 uncompressed 交叉证据 |
| 安全 lower bound 与剪枝 | 未完成 | 文档提出 `max(L, max_r D_r)`，代码未实现、未用于 Exact、没有安全性测试 |
| 稳定 baseline 与资源感知候选 | 仅原型 | LT greedy-fill 可作为基线；resource tie-break、bottleneck 和 top-2 set Rollout 不足以覆盖计划中的资源向量、集合互补和 downstream demand 主线 |
| Rollout 有硬预算、统计与确定性 fallback | 未完成 | 只有无预算、单事件、top-2 的全程 baseline completion；无 node/time/set budget、fallback 状态或缓存统计 |
| random/adversarial/real/compatibility 分层 | 未完成 | 现有 10 random、4 adversarial、0 preemptive real；compatibility 仅存在测试期临时对拍，没有独立 benchmark/report 层 |
| small-Exact 与 large-primal 双口径 | 未完成 | 只有很小的 14 图 Exact 统计，没有中大图 primal、知识区间或逐资源指标 |
| 阶段总结不外推 Stage 2 结论 | 部分具备 | 旧总结正确指出 `P` 不再是下界且 2-bound 不能迁移，但对“闭环”和 Set-Rollout 有效性的措辞超过证据 |

按当前计划的 12 项退出条件，只有基础语义和 trace 部分可以视为基本通过；Exact 可信链、算法研究和实验分层均未达到退出标准。

## 3. 公共模拟语义与代码边界

### 3.1 已正确实现的部分

`src/muti_channel/preemptive/solver.py` 的以下行为与目标语义一致：

1. `PreemptiveMultiResourceModel.__init__()` 要求每个 communication 都有非空固定资源集合，并拒绝非正 communication duration；
2. `compatible()` 以资源集合交集判定冲突；
3. `maximal_actions()` 枚举当前 eligible communication 的 inclusion-maximal compatible sets，而不是 maximum-cardinality set；
4. `step()` 对所有选中通信和 active compute 同步推进到最近完成事件；
5. 未被继续选择但未完成的 communication 保持剩余工作，不占用本区间资源；
6. compute ready 后由 `_compute_closure()` 自动启动，零时长 compute 在同一时间闭包内传播；
7. 重复 ID、非稳定排序、冲突集合、非 maximal 集合和存在 eligible 时的空动作均会被拒绝；
8. `schedule_pack()`、`rollout_sets()` 和 `exact_oracle()` 都调用同一个 `model.step()`，没有各写一套时间推进。

对所有 Stage 2 complex-chain communication 映射到同一个共享资源后，本次临时核验了当前 45 个 Stage 2 benchmark，Stage 2 Exact 与 Stage 3 Exact 的 makespan 为 **45/45 一致**。这说明“单资源是多资源特例”在当前实现上有较强的兼容性证据，但该临时核验尚未固化为回归测试和分层报告。

### 3.2 多资源模拟器仍蜗居在算法文件中

核心问题不是状态转移完全错误，而是架构边界与计划冲突：

- `TaskState`、`MultiState`、`MultiAction`、`MultiTrace`、`PreemptiveMultiResourceModel`、状态转移、trace 构造、Exact 和 heuristic 全部放在 `src/muti_channel/preemptive/solver.py`；
- `src/core/execution/preemptive.py` 的公共执行核心没有承载固定多资源动作；
- 多资源 trace validator 反向导入 `solver.MultiTrace`，使验证层仍依赖算法模块的数据类型；
- 单通道与多资源分别维护状态、闭包和事件推进代码，未来修复同刻事件或 forced-idle 时容易发生语义漂移。

这违反了“模拟器负责合法性和 transition，算法只选择动作”的仓库约束。修正不需要重写整个项目，但应把已经存在的多资源状态机提升为公共执行能力，`muti_channel/preemptive/solver.py` 只保留 set policy、search 和薄适配。

### 3.3 forced idle 仍被编码为空动作

当前所有算法在 `eligible` 为空时构造 `MultiAction()`，再调用 `step()`；`run()` 把它记录成 decision，并通过 `is_wait` 生成 forced-idle interval。该空动作只在有 active compute 时合法，所以不会产生 voluntary WAIT，最终 schedule 语义通常正确。

但目标接口要求 forced idle 是模拟器自动推进，不是 scheduler 动作。当前设计带来三个问题：

- 算法仍需实现 `if not eligible: MultiAction()` 分支；
- `decision_count` 和 `actions` 混入了非调度事件；
- `MultiAction.is_wait` 保留了容易与历史 optional-idle 混淆的术语。

因此，这一项应判为“结果语义基本正确、接口语义未完成”。

### 3.4 maximal-set 枚举正确但扩展性很弱

`maximal_actions()` 先枚举所有非空子集，过滤兼容集，再用两两严格包含关系过滤 maximal 集。其成本远高于直接在冲突图上回溯生成 maximal independent sets：

- 至少有 `2^eligible_peak` 的子集枚举；
- 每个候选重复计算资源交集；
- maximal 过滤再次比较集合包含关系；
- 没有记录 set 数量、枚举耗时、冲突图分量或 peak branch。

当前最大 Exact 仅探索 1,791 个 normalized states，所以这一问题尚未被旧 14 图暴露，不能据此判断 Stage 3 Exact 可扩展。

## 4. Trace 与测试审查

### 4.1 Trace 的独立性是现有实现的重要优点

`src/muti_channel/preemptive/trace.py` 没有调用 `model.step()` 来重新执行，而是从任务区间、依赖完成时间和资源区间独立检查：

- 每个任务累计 service 等于 duration；
- compute 只有一个连续区间；
- communication 各区间不自重叠；
- 首次执行不早于全部前驱完成；
- 每个 communication interval 必须展开为其全部固定资源的 resource intervals；
- 每个资源上的区间不重叠；
- 每个 decision 的 selected set eligible、兼容且 inclusion-maximal；
- 空 decision 只能对应无 eligible 且有 future compute；
- 最终状态、makespan、事件顺序一致。

这部分可以作为后续公共 trace 层的迁移来源，不应丢弃。

### 4.2 已有测试证据

当前测试中虽然 `tests/muti_channel/preemptive/test_preemptive_muti_channel.py` 只有 3 个测试，但 `tests/core/trace/preemptive/test_contract_and_replay.py` 还覆盖了：

- 非 maximal、voluntary empty action、重复 ID 和零时长 communication 拒绝；
- resource interval 缺失和 recorded non-maximal decision 的错误 trace；
- 固定 seed 的 12 个极小多资源 DAG，event Exact 与独立 tick/set Oracle 一致。

本次运行：

```text
python -m pytest -q tests\muti_channel\preemptive tests\core\execution\preemptive tests\core\trace\preemptive tests\test_benchmark_format.py tests\test_generators.py

27 passed in 19.72s
```

### 4.3 测试仍缺少的关键面

现有 12 个随机对拍的资源生成只产生 `{r0}` 或 `{r0,r1}`，没有使用 `r2`，资源集合接近嵌套形式，不能覆盖一般重叠模式。还缺少或没有被明确隔离验证：

- 一个 communication 占有多个资源时，缺少其中任一资源的错误 trace 必须失败；
- 多资源通信暂停后全部资源释放、恢复时全部重新获得；
- 多个 communication 与 compute 同刻完成后只形成一个稳定决策点；
- 两个 maximal sets 大小不同，但二者都合法；
- 冲突图有多个连通分量、但未来通过 join 重新耦合；
- active allocation/resource occupancy 被错误从 Exact key 删除时的碰撞反例；
- 更丰富的 3 资源非层次 resource sets；
- 固化的 45 图 Stage 2 单资源退化对拍。

## 5. Exact 审查

### 5.1 当前 Exact 能做什么

当前 `exact_oracle()` 在每个稳定状态枚举全部 maximal compatible sets，通过公共 `step()` 递归，使用 memoization 返回最小 residual makespan。它有 state limit 和 wall-clock limit；超限直接抛出异常，实验与 reference generator 会跳过异常，没有把异常结果当作 optimum。

12 个极小随机多资源图与独立 tick Oracle 一致，现有 14 个 benchmark 也都能在很小预算内求完。这证明原型在已覆盖状态空间上没有发现 makespan 错误。

### 5.2 normalized key 未完成 Stage 3 证明

Exact key 为：

```python
tuple((item.status, item.remaining) for item in state.tasks)
```

它省略绝对时间、当前 active communication、资源占用和事件信息。当前实现把决策边界定义成所有未完成 communication 都是 suspended、资源占用完全由新动作重新建立，因此 active communication 与 occupancy 在规范状态中确实可能无需保存；绝对时间在平移不变 makespan 模型中也可能只作为 additive offset。

但“可能安全”不等于已经证明。缺失项包括：

1. 没有未压缩 audit Exact；
2. 没有逐字段说明 status/remaining 如何唯一决定 ready、active compute、未来 release 和合法 set；
3. 没有证明 `representatives.setdefault()` 在两个不同绝对时间的同 key 状态间保留任一代表都不改变 residual cost；
4. 没有针对资源 occupancy 或 active-set 碰撞的构造测试；
5. 独立 tick 对拍只有 12 个很小且资源结构单一的随机图。

因此，当前 Exact 可作为“有交叉证据的候选 Oracle”，尚不应称为 Stage 3 已认证 Oracle。

### 5.3 结果合同不足以生成严格 reference certificate

`MultiResult` 只有 makespan、actions、decision_count、preemptions、explored_states 和 trace，没有：

- `status=optimal/timeout/state_limit/feasible`；
- runtime；
- generated transitions、deduplicated/pruned states；
- compatible-set branch 数和枚举耗时；
- peak memory；
- lower bound、incumbent 和终止原因。

更严重的是，`benchmark_generate/reference.py` 只对 Stage 2 complex-chain 强制检查 `status == "optimal"`；多资源结果没有同样检查。当前 4 个 Stage 3 sidecar 还是旧格式，仅包含 hash、oracle 名和 optimum，没有 Oracle 状态、预算、runtime 或 states。四个 sidecar 的 hash 与本次重算 optimum 均匹配，但它们是**一致的旧结果**，不是满足当前证书合同的新 reference。

### 5.4 没有 lower bound、B&B 或规模边界实验

计划要求的 `LB_0=max(L,max_r D_r)` 只出现在文档中。Exact 实现是纯 memoized enumeration：无 incumbent、无 lower-bound pruning、无 branch ordering 统计、无 set enumeration cache、无内存统计。旧 14 图探索状态数：

- 平均 216.36；
- 最大 1,791（`pm_muti_random_008`）；
- 本机平均约 21.23 ms，最大约 188.49 ms。

这组图太容易，无法解释资源数、eligible peak、冲突密度或 resource-set 宽度如何影响 Exact。

## 6. Heuristic 与 search 审查

### 6.1 LT greedy-fill 是可保留的稳定基线

`schedule_pack(..., "longest_tail")` 每个事件从当前 remaining state 重算 residual tail，按 tail 和稳定 ID 排序，再贪心加入兼容通信。输出保证 maximal，成本低，适合作为 Stage 3 第一条 baseline。

需要补正文档定义：当前 `_residual_tail()` **包含候选 communication 自身 remaining**。Stage 3 计划要求明确 inclusive/exclusive 定义，不能只沿用名称。

### 6.2 两个“资源感知”规则的信息量有限

`resource_tail` 仍以 tail 为第一关键字，资源瓶颈 load 只在 tail 完全相同时 tie-break；因此它在全部 14 图上与 LT 完全相同。它不能支持“资源信息没有价值”的结论，只能说明这个弱 tie-break 在现有图上没有改变动作。

`bottleneck` 把最大资源 residual load 放在第一关键字，但只关注候选自身资源上的单个最大 load，没有下游资源向量、join 分支、资源碎片或集合联合影响。它在 14 图上明显更差，说明“只看热点负载”不稳定；这条负面结论可以保留，但不能否定更完整的资源感知特征。

Stage 2 迁移清单重点要求的 `downstream_demand` 资源向量当前完全没有实现。

### 6.3 Set-Rollout-2 没有形成可靠的集合互补策略

当前 `rollout_sets()`：

1. 枚举所有 maximal actions；
2. 若超过 `top_k`，按集合内各任务 residual tail 的简单总和排序；
3. 对候选执行一个事件；
4. 用 LT greedy-fill 补全至结束；
5. 选择预测 makespan 最小者。

主要问题：

- 单任务 tail 求和会重复计算 shared downstream，正是迁移清单禁止直接外推的做法；
- LT greedy baseline action 不保证进入 top-2，因此不存在逐实例不差于 baseline 的 safeguard；
- 只看一个集合事件，没有 depth 定义；
- 没有 node/time/set-count budget；
- 没有预算耗尽后的结构化 fallback；
- completion 没有 memoization 或增量 cache；
- 没有 expanded nodes、候选遗漏、fallback 次数和 set enumeration 时间；
- 没有直接 set score、weighted independent-set 或局部 `1 -> 2` 交换策略。

它确实能比较多个 maximal sets，因此不是“顺序运行单通道 policy”；但仍不足以证明已经处理了 Stage 3 的集合互补性主问题。

### 6.4 三个公开入口不一致

当前 `src/muti_channel/preemptive/interface.py` 只暴露 LT、Rollout 和 Exact；`src/registry.py` 额外暴露 resource/bottleneck pack；`experiments/preemptive/stage0_4.py` 又直接调用 solver。由此产生三套算法面：

- CLI/registry 能运行的算法不等于场景 public interface 能运行的算法；
- 实验配置没有经过与 CLI 相同的稳定入口；
- registry 的 Exact 使用默认 `max_states=300000` 且没有默认 wall-clock limit，结果又没有 status；
- 很难统一记录算法版本、预算和 development status。

Stage 3 推进时应以 registry/稳定 `src` interface 为唯一索引，实验只传配置和收集结果；Exact 必须显式传预算。

## 7. Benchmark 与生成器审查

### 7.1 当前数据分布

当前 `benchmark/muti_channel/preemptive/` 共有 14 图：

| 类别 | 数量 | reference | 主要来源 |
|---|---:|---:|---|
| adversarial | 4 | 4 | 从不可抢占 R4 motif 机械 lift |
| random | 10 | 0 | `random_join_dag` 加随机 NIC/fabric/uplink 固定集合 |
| real/structured | 0 | 0 | preemptive 导出被跳过 |

不存在单独的 Stage 1/2 single-resource compatibility benchmark 目录或正式统计。

### 7.2 adversarial 名称与当前语义错位

四个 adversarial 为 `pm_disjoint_routes`、`pm_shared_route`、`pm_nonmaximal_start`、`pm_active_reservation`，全部由名称带 `_np` 的不可抢占 R4 motif lift 而来。它们在当前语义下存在明显问题：

- 四图中没有任何 communication 需要两个或更多资源，不能验证完整多资源原子获取；
- `pm_nonmaximal_start` 的描述是“Non-maximal start protects a future critical flow”，但当前模型明确禁止非 maximal action；
- `pm_active_reservation` 的描述强调 active flow 保留 route，而当前可抢占稳定决策边界要求未被继续选择的 flow 释放全部资源；
- 四图对 LT、resource、bottleneck、Rollout 全部最优，没有攻击任何当前算法；
- metadata 只有 `lifted_from` 和描述，没有当前攻击对象、机制、参数化扩展或 semantic role。

它们可以保留为兼容/语义 regression，但不应继续充当 Stage 3 正式 adversarial 证据。

### 7.3 random 集控制维度不足

10 个 random 图的 communication 全部需要 2 或 3 个资源，因为生成器固定加入一个 NIC 和一个 fabric，并以 35% 概率加入 shared uplink。现有随机集没有系统控制：

- 单资源与多资源 communication 比例；
- resource-set size；
- 冲突图密度和 maximal-set 数量；
- 高 tail 是否集中在热点资源；
- join/barrier 分支使用冲突还是互补资源；
- shared downstream 与集合评分重复计权；
- DAG 宽度、同步层数和 resource-set 宽度的正交扫描。

本次静态统计中，10 个 random 图只有 4 至 10 个 communication，冲突密度约 0.533 至 0.900；它们仍属于小而高冲突的单一生成族。

### 7.4 real/structured 被导出逻辑意外排除

`manual_route_cases()` 定义了 3 个透明固定路由快照，但 `export_semantic_suite()` 对 preemptive real 且非 parallel-chain 的样例只放行三个 Stage 2 single-channel motif ID，因此所有 Stage 3 manual-route case 被跳过。结果是当前 preemptive Stage 3 没有 real/structured 图。

这份谨慎过滤避免了未经审计地把不可抢占 route case 标成真实可抢占结果，本意合理；但旧“Stage 3 已闭环”的结论没有明确说明正式数据中 real=0。后续必须完成 collective/preemption granularity 审计后再导出，不能简单取消过滤。

## 8. 旧实验结果复核

### 8.1 数值复现

本次直接从 14 个当前 benchmark 重算 Exact 和四个算法，结果与 `docs/old_docs/preemptive研究/preemptive进度.md` 的旧表完全一致：

| 算法 | n | mean ratio | observed max | observed optimal |
|---|---:|---:|---:|---:|
| Longest-tail pack | 14 | 1.006614 | 1.055556 | 12/14 |
| Resource pack | 14 | 1.006614 | 1.055556 | 12/14 |
| Bottleneck pack | 14 | 1.044995 | 1.230769 | 9/14 |
| Set-Rollout-2 | 14 | 1.002646 | 1.037037 | 13/14 |

Exact optimum 与 4 个已提交 adversarial reference 的 hash/数值为 4/4 一致。

### 8.2 分类别后证据更弱

| 类别 | 算法 | mean ratio | observed max | observed optimal |
|---|---|---:|---:|---:|
| adversarial（4） | 四个算法全部 | 1.000000 | 1.000000 | 4/4 |
| random（10） | Longest-tail / Resource | 1.009259 | 1.055556 | 8/10 |
| random（10） | Bottleneck | 1.062993 | 1.230769 | 5/10 |
| random（10） | Set-Rollout-2 | 1.003704 | 1.037037 | 9/10 |

因此正式表中的算法差异完全来自 random 集；所谓 adversarial 集没有制造任何当前算法 gap。LT 的两个 gap 是：

- `pm_muti_random_003`：19 / 18；Rollout 修复到 18；
- `pm_muti_random_008`：28 / 27；Rollout 仍为 28。

旧“Set Rollout 平均关闭 50% gap”的算术描述可以复现，但样本只有两个 baseline gap，实际含义只是修复一图、遗漏一图，不能泛化为“集合 Rollout 仍然有效”。

### 8.3 旧结论的保留、降级与撤回建议

可以保留：

- 固定资源集合使动作变成 compatible set；
- 单通道总通信量 `P` 不是多资源下界；
- `max(L,max_r D_r)` 是值得证明和实现的基础候选；
- 只看资源热点的 bottleneck-first 在现有小图上可能明显退化；
- 14 图的原始 observed ratio 数值能够复现。

必须降级：

- “多资源核心、Exact 和四个 baseline 已形成小图闭环”改为“旧原型在 14 个很小 benchmark 上形成可运行闭环”；
- “端到端集合 Rollout 仍然有效”改为“旧 top-2、depth-1 原型在两个 LT gap 中修复一个，尚无稳定性证据”；
- “resource load bonus 没有价值”改为“当前仅作 tie-break 的实现没有改变 14 图动作”。

应明确撤回或标为历史失效：

- `pm_nonmaximal_start` 作为当前可抢占 work-conserving adversarial 的解释；
- `pm_active_reservation` 作为当前决策边界资源语义的解释；
- 任何把 14 图 observed optimal rate 当成多资源普遍性质的叙述；
- 任何把缺少 Oracle 状态的旧 sidecar 当作当前严格 certificate 的叙述。

## 9. 实验薄接口审查

`experiments/preemptive/stage0_4.py` 保持了薄入口属性：加载 benchmark、调用 `src/` 算法、聚合输出，没有被 `src/` 反向依赖。问题在于它不够支持当前 Stage 3 研究口径：

- Stage 0--4 混在一个 runner 中，没有 Stage 3 独立配置与版本；
- random 与 adversarial 混合汇总，掩盖 adversarial 全部无区分；
- 不输出 benchmark hash 和 reference hash；
- 不输出 Exact status、runtime、states、branch/set 统计或 lower bound；
- 不输出 P50/P95、候选相对 baseline 的改善/持平/退化；
- 不输出逐资源 busy/utilization、热点 idle、碎片、set size、forced idle；
- skipped 只记录 ID 和异常类型，没有 scenario/category/budget；
- 默认结果路径仍是旧的 `docs/preemptive实验结果.json`，与当前 `docs/result_docs/` 归档约定不一致。

修正方向应新增 Stage 3 专属薄 runner，而不是把算法或资源指标计算塞进 `experiments/`；指标应由 `src` 的 trace/statistics API 提供。

## 10. 最终审查判断

旧 Stage 3 的实际完成度可概括为：

- **语义原型：基本完成，但尚未提升为公共模拟器合同；**
- **Trace：主要检查已具备，是最值得保留的资产；**
- **Exact：有独立小图对拍，但缺未压缩审计、证明、状态合同和剪枝；**
- **算法：只有 LT greedy-fill 和三个弱原型，未进入当前计划的资源感知/集合互补研究；**
- **benchmark：数量小、攻击集失效、无 preemptive real/structured；**
- **实验：旧数值可复现，但分层后证据不足，不能支持阶段完成；**
- **理论：正确阻止了单通道 `P` 和 2-bound 外推，但基础下界仍未落地。**

下一步不应推倒旧实现，也不应继续在 14 图总表上堆叠 bonus。应先修正公共执行边界和 Exact 可信链，再重建能区分“单任务 priority”和“compatible-set construction”的 Stage 3 数据与实验。
