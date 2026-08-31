# Stage 2：single-channel complex chain 审查记录

日期：2026-08-16

## 1. 审查范围

本次审查依据：

- `docs/plan_docs/outline.md`
- `docs/plan_docs/stage2_complex_chain.md`
- `src/single_channel/complex_chain/preemptive/`
- Stage 2 实际调用的公共可抢占 simulator、trace validator、benchmark loader/validator、registry 和 reference 生成路径
- `benchmark/single_channel/complex_chain/preemptive/`
- `tests/single_channel/complex_chain/preemptive/` 及与 Stage 2 直接相关的公共测试
- `experiments/preemptive/stage0_4.py` 和既有 Stage 2 历史结果

范围限定为单 channel、单个联合一般 DAG、communication 可暂停/恢复、compute 自动且不可抢占、无主动 WAIT、makespan 目标。没有审查多 channel、multi-job、LLM 特化或不可抢占算法的研究质量。

`experiments/` 仍按薄的调用和汇总接口审查。它不应实现算法、Exact 或第二套时间推进；本文只检查它是否正确路由 Stage 2 输入、是否能生成支持当前结论的分层结果。

## 2. 审查方法

除静态阅读外，本次进行了以下只读核验：

1. 运行 Stage 2 及其依赖的公共可抢占测试：`24 passed in 8.75s`。
2. 核验全部 27 个 preemptive complex-chain benchmark 的结构、类别和 metadata。
3. 核验 17 个现有 adversarial reference result 的文件 hash 和 Exact makespan，全部匹配。
4. 使用当前 Exact 在 `150,000 states / 5s` 预算下重算 27 个 Stage 2 benchmark，全部完成。
5. 对 30 个临时生成的严格交替、含 fork/join 的极小图，将 event Exact 与独立 tick Oracle 对拍，全部一致。
6. 重跑 FIFO、SPT、LPT、Longest-delay、Longest-tail、LRPT、Rollout、Join-Rollout 和 Beam，并与历史表格比较。

临时图只用于审查，没有写入 benchmark 或测试目录。

## 3. 总体结论

当前 Stage 2 可以定位为：**已有一个能处理一般 DAG 的公共事件模拟基础、通用小图 Exact 和初步 heuristic/search 原型，旧的 27 图结果能够复现；但尚未完成 Stage 2 计划要求的 family contract、可信未压缩 Exact、结构化 heuristic 消融、困难 benchmark、真实投影和独立分层实验。**

主要判断如下：

1. 公共可抢占 simulator 和独立 trace replay 可以继续使用，没有必要重写。
2. 当前 Exact 在小图上的数值可信度有积极证据，但它已经使用未书面证明的状态 key 压缩，并缺少 lower-bound、pruning、完整统计和正确的 `optimal` 状态标记，不能视为 Stage 2 Exact 研究已经完成。
3. Longest-delay 仍是 Longest-tail 的别名；FIFO 仍不是首次 eligible FIFO；Join-Rollout 只提供一个很局部的“直接 join 最后阻塞者”候选，不构成计划要求的 join-aware priority 研究。
4. 现有 27 图过小且结构覆盖不均：真正有 fork 的只有 1 图，7 个 adversarial 没有 fork/join，preemptive real/structured 为 0。这组数据不足以支撑一般 DAG 的算法结论。
5. 历史文档中“一般 DAG 仍保留 `T <= P+Q <= 2OPT`”的表述与当前 Stage 2 计划直接冲突，现阶段应撤回为“未经一般 DAG 证明的历史外推”。
6. Rollout/Beam 在当前 27 图上全部命中 Exact 仍然可以作为复现事实，但不能解释为一般 DAG 上的稳定最优性；当前攻击集没有真正检验 shortlist、有限深度、固定宽度和跨多层同步投资。

因此 Stage 2 尚不能宣布完成，也不宜在现有 27 图上继续堆叠复杂加权分数。应先修正研究契约、Exact 报告和最小反例体系。

## 4. 可以保留的基础

### 4.1 公共事件执行语义

Stage 2 经过的 `PreemptiveDAGModel` 已体现：

- finish-to-start 依赖；
- ready compute 自动启动并连续运行；
- communication 在 task event 处暂停/恢复并保存 remaining work；
- 单 channel 排他；
- eligible communication 存在时拒绝主动 WAIT；
- 没有 eligible communication 时 forced idle；
- 同一时刻完成事件先原子处理，再形成新的 ready/eligible 集合。

算法通过 `model.step` 选择合法 communication，没有在 complex-chain solver 中另写时间推进循环。这符合 Stage 2 的架构边界。

### 4.2 独立 trace validator

各 heuristic、Rollout、Beam 和 Exact 最终都会通过公共 model 生成 trace，并调用独立 validator。公共测试会拒绝缺失 event/transition、错误 interval kind/duration、compute 被拆段和依赖违规。

这部分适合继续作为 Stage 2 的可行性证据，但 Stage 2 自己仍缺 fork/join/barrier 的专用 trace regression，见 5.2。

### 4.3 Exact 的小图结果具有初步交叉验证证据

现有公共测试将 event Exact 与独立 tick Oracle 在 20 个随机极小 DAG 上比较，结果一致。本次又对 30 个严格交替的 fork/join 小图交叉核验，30/30 一致。

因此没有发现当前 Exact 在这些重叠规模上的 makespan 错误。这个结论只支持“可作为当前小图参考实现继续审查”，不证明状态压缩、规模扩展和所有一般 DAG 结构都已经验证。

### 4.4 reference sidecar 的现存部分自洽

17 个 adversarial reference sidecar：

- SHA-256 全部与对应 benchmark 匹配；
- 当前 Exact 重算 makespan 全部与 `optimal_makespan` 匹配。

这些 reference 可以保留为当前版本的回归材料。需要注意，random 10 图没有 reference，sidecar 也没有记录 Exact 状态、运行时间、完成状态或证明来源。

## 5. 代码与测试问题

### 5.1 高优先级：Stage 2 family contract 没有独立实现

`single_channel/complex_chain/preemptive/interface.py` 直接接受任何 `BenchmarkDAG`，没有 Stage 2 validator。benchmark validator 只对 `parallel_chain` 增加 family 特有约束；`complex_chain` 实际等价于“任意合法 DAG”。

这与计划中的“compute–communication 交替的一般 DAG 标准形式”没有形成可执行契约。现有 27 图中有 15 图至少包含一条相邻同类任务边。部分同类边可能表达不可安全合并的 fork、join 或计算顺序，不能简单删除，但当前代码没有说明它们属于：

- 合法的原始一般 DAG；
- 需要显式 canonicalization 的非标准输入；
- 仅供数学推导插 dummy 后处理的输入；
- 应被 Stage 2 benchmark 拒绝的输入。

计划文档本身允许在合并不安全时用 dummy 保持形式，却又不要求 benchmark 实际产生零 communication，因此实现前必须先澄清“交替标准形式”是强制输入契约还是理论规范形式。当前状态是未定义，而不是已经支持。

此外，interface 只暴露 `longest_tail/rollout2/beam8/exact` 四项，registry 又暴露更多算法；Exact 的 `max_states/time_limit_s` 也无法从 interface 传入。稳定 family 入口、CLI registry 和实验直接 solver 调用形成三套不一致的入口表面。

### 5.2 高优先级：Stage 2 专用测试几乎没有测试一般 DAG

`tests/single_channel/complex_chain/preemptive/test_algorithms.py` 的唯一 single-channel 样例是两条独立链组成的 Stage 1 图，没有 fork、join 或 barrier。该文件其余两个测试属于多 channel，却放在 Stage 2 目录中。

所以 Stage 2 自己没有直接覆盖：

- 最小 fork；
- 最小 join；
- fork 后多分支再次 join；
- 同刻多个前驱完成后的原子 ready；
- barrier 前各分支 slack；
- shared downstream；
- 多层 fork/join；
- fork/join 下的暂停、恢复与 trace 回放；
- complex family 输入契约。

公共随机 Oracle 测试是积极补充，但不能替代 Stage 2 的结构定向 regression。尤其是测试文件放置错误会造成“Stage 2 已经覆盖多种场景”的错觉。

### 5.3 高优先级：Exact 不是计划要求的“先未压缩、后证明压缩”

当前 `exact_oracle` 的 key 是每个 task 的 `(status, remaining)`，删除了绝对时间、started/completed time、last communication、显式 eligible 集合和其他字段。对于当前无外部 release time、零切换成本模型，这种 time-shift 归一化很可能是安全的，eligible 也可从 task 状态推导；但仓库中没有逐字段 future-equivalence 说明。

这意味着第一版 Exact 已经做了压缩，却没有：

- 未压缩 event-state baseline；
- 删除字段的安全性证明；
- 压缩/未压缩逐例比较；
- key collision 的专门反例测试；
- 对 fork/join 外部连接不同的相似子图测试。

当前 50 个独立 Oracle 小图结果支持数值正确性，但不能代替 key 的完整性论证。

### 5.4 高优先级：Exact 的结果状态和统计不符合公开契约

成功完成的 `exact_oracle` 结果仍显示：

```text
status='feasible'
deduplicated_states=0
pruned_states=0
lower_bound=0
runtime_ms=0.0
```

只有 `explored_states` 被填写。Exact 已穷举完成时应明确标记 `optimal`；timeout/state-limit 则应返回或抛出可辨别的未完成状态。reference generator 当前只因 registry 将算法标为 `exact=True` 就接受 makespan，没有检查结果的 `status`。

因此 sidecar 虽然数值能复现，生成链路却没有机器可读地证明“本次求解成功完成且为 optimal”。这与计划中 timeout 不能计 optimal 的要求存在接口漏洞。

### 5.5 高优先级：Exact 尚无 Stage 2 lower bound、剪枝和可解边界研究

当前 Exact 是 memoized exhaustive search：

- 没有 branch-and-bound incumbent；
- 没有使用 `P/L` residual lower bound；
- 没有报告 cache hit/去重数；
- 没有剪枝计数；
- 没有峰值内存；
- 没有按宽度、深度、fork/join 密度做 scaling。

公共 `core.dag.lower_bounds` 中存在 `P/Q/L/window/cut`，但其中若干定义来自早期研究，尚未按 Stage 2 当前模型逐项给出安全性说明，且 complex preemptive Exact 没有使用它们。不能仅因函数存在就认为 Stage 2 lower bound 已完成。

现有 27 图在 150,000 states/5s 内全部求解，平均约 800 states，最大 7,393 states；本次机器上的 Exact 平均约 82 ms，最大约 806 ms。这只能说明现有集合很容易，不能给出一般 DAG Exact 的可解边界。

### 5.6 高优先级：FIFO、Longest-delay、Longest-tail、LRPT 未按计划完整区分

当前 FIFO 使用 `model.task_ids` 的静态顺序，而不是 communication 第一次 eligible 的时间。它与 Stage 1 审查发现相同，不应标为 FIFO。

当前分数为：

- `longest_delay = residual_tail - current_remaining`；
- `longest_tail = residual_tail - current_remaining`；
- `lrpt = residual_tail`。

所以 Longest-delay 与 Longest-tail 完全相同。本次重跑中二者所有结果完全一致，也没有能区分三者首选动作的一般 DAG 测试。

`residual_tail` 使用当前 remaining work 并按 DAG 最长后继路径计算，作为 general-DAG residual longest path baseline 是合理的起点；但它没有表达 join slack、最后阻塞关系、多个近关键路径、共享后继边际贡献或 downstream communication demand。现阶段应准确称为 residual longest-path baseline，而不是已完成的 DAG-aware 结构 heuristic。

### 5.7 高优先级：Rollout shortlist 与 completion baseline 的分数口径不一致

`_rank_candidates` 的 tail 排序使用包含当前 communication remaining 的 `tail[item]`，更接近 LRPT；`_complete_actions` 的 Longest-tail 则排除当前 remaining。

因此 `rollout2` 并不保证把真正的 Longest-tail baseline 首选动作放入 shortlist。历史文档关于“baseline 首选动作始终进入候选，因此逐实例支配 Longest-tail”的论证不由当前代码保证。

虽然当前 27 图上 `rollout2` 没有退化，并全部达到 Exact，但这是数据集观察，不能替代候选包含关系。该口径问题也使“Rollout 修复 Longest-tail”的机制解释不够准确。

### 5.8 高优先级：Stage 2 Rollout/Beam 研究矩阵尚未实现

当前 complex-chain Rollout 只支持：

- top-k shortlist；
- 单个 event action 后，用 Longest-tail 完成整个后缀；
- `tail/join/hybrid` 三种候选模式。

它没有 depth 参数、节点扩展预算、墙钟预算或确定性 timeout fallback。forced idle 虽不被当作候选选择，但当前也没有正式的“通信选择深度”实现可供比较。

Beam 只有 width，没有深度、节点/时间预算和结构评分选择；运行直到首次找到完整 schedule，宽度截断后的结果与 Longest-tail incumbent 取较好者。它使用 `(status, remaining)` 去重和较早时间支配，但没有 Stage 2 future-equivalence 文档或专门测试。

因此当前代码只能称为 initial one-event rollout 和 full-horizon fixed-width beam 原型，不是计划中的 top-k × depth × budget 研究。

### 5.9 中高优先级：Join-Rollout 不是完整的 join-aware heuristic

`join_score` 只检查候选 communication 的直接 child 是否为多前驱节点，且其他前驱是否都已完成；满足时给直接 last blocker bonus。它无法表达：

- 候选后还有 compute 才到达 join；
- 距离成为 last blocker 的 slack；
- 多层 barrier；
- fork release；
- shared downstream；
- 多条近关键路径；
- 后续 channel demand。

`hybrid top_k=2` 实际取一个 inclusive-tail 候选和一个局部 join 候选，再用同一 counterfactual completion 评价。它不是独立 join-aware priority，也没有成对反例和消融。

现有 27 图中 `join_rollout2` 与普通 `rollout2` 逐例完全相同，只能说明该局部候选在当前集合上没有可观察贡献，不能说明 join 信息无用或方法已经完成。

### 5.10 中优先级：Monte Carlo 仍出现在 Stage 2 active registry 和主实验矩阵

`monte_carlo64` 仍以 `development_status='active'` 暴露，`stage0_4.py` 也将其列入 complex-chain 方法。Stage 2 计划明确要求 Monte Carlo 只保留历史状态，除非发现新用途，不进入主要算法矩阵。

这不会破坏 schedule 合法性，但公开入口传达的研究优先级与计划不一致。

## 6. Benchmark 与 reference 审查

### 6.1 当前集合统计

Stage 2 preemptive 共有 27 图：

| 类别 | 数量 |
|---|---:|
| adversarial | 17 |
| random | 10 |
| real/structured | 0 |

结构统计：

- 含 fork 或 join：20/27；
- 含 outdegree > 1 的 fork：1/27；
- 含 indegree > 1 的 join：20/27；
- 无 fork/join、实质仍是独立链或路径集合：7/27；
- 含相邻同类任务边：15/27。

这说明当前集合主要是“多分支最终汇入 join”，而不是覆盖 fork、join、多层重汇合、shared downstream 和 barrier 层级的一般 DAG 集合。

### 6.2 adversarial 集合混入 Stage 1 结构

以下 7 个 adversarial 没有 fork/join：

- `pm_combined_chain_14`
- `pm_combined_chain_70`
- `pm_combined_chain_86`
- `pm_large_flow_vs_long_tail`
- `pm_longest_tail_counterexample`
- `pm_lrpt_double_count`
- `preemption_unlock`

它们可以作为 Stage 1 compatibility/regression 集运行，但按 Stage 2 计划不能计入“一般 DAG 结构攻击证据”。

部分名称和说明还继承不可抢占或旧算法语境：

- `pm_longest_tail_counterexample` 的 description 写的是 static longest-tail，当前算法是 residual dynamic tail；
- `pm_lrpt_double_count` 在当前可抢占 LRPT 上并未产生 gap；
- `pm_last_blocker_overboost` 没有证明当前 Join-Rollout 退化；
- `pm_random_join_*` 来自随机搜索，metadata 没有逐例说明当前攻击对象、失败机制和可扩展方式。

因此现有 adversarial 更适合称为“历史回归 + 少量结构 motif”，尚未达到 Stage 2 的解释性反例标准。

### 6.3 random 生成器参数覆盖不足

`random_join_dag` 主要生成若干独立 branch，再汇入一个或两个 join。它记录 branch 数，但没有系统控制和报告：

- DAG 宽度/深度组合；
- fork 密度；
- barrier 层数；
- 最大入度/出度；
- 同时 eligible communication；
- 关键路径重叠；
- join slack；
- compute/communication ratio；
- 相似但不对称子图。

固定 10 seed 可以保留作 smoke/random regression，但不能承担计划中的规模分层统计。

### 6.4 preemptive real/structured 被生成器主动排除

`current_cases` 已有 7 个 LLM motif，但 `export_semantic_suite` 在 preemptive 导出时明确跳过非 parallel-chain 的 `real` 类别。因此 `complex_chain/preemptive/real` 为空。

这种谨慎是可以理解的：把不可抢占 collective 机械改成可抢占标签不能替代粒度审计。但它意味着 Stage 2 的 real/structured 目标尚未开始，而不是已经由 nonpreemptive real 文件覆盖。

### 6.5 reference 覆盖和生成契约不足

17 个 adversarial sidecar 全部自洽；10 个 random 没有 sidecar。当前生成器默认只为 adversarial 生成 reference，这与“仓库不必为所有随机图保留 reference”并不冲突，但正式 Stage 2 Exact 子集应明确哪些 random/structured 图属于固定 ground truth。

更重要的是 reference generator 没有检查 `result.status == 'optimal'`。在 current Exact 成功结果仍标记 `feasible` 的情况下，sidecar 的“Exact”性质只依赖调用路径约定，不依赖机器可读完成证书。

## 7. 实验接口与历史结果审查

### 7.1 `experiments/` 的定位没有误认

`experiments/preemptive/stage0_4.py` 是薄 runner。它调用 `src` 中的 solver，并没有复制 simulator 或算法逻辑。本次不因其内部没有 heuristic 实现而提出问题。

它与 Stage 2 有关的实际缺口是：

- complex-chain 直接调用 solver，绕过 family public interface/registry；
- Stage 1、Stage 2 被合并到 `single_channel.summary`；
- 没有 Stage 2 独立 runner 或 family/category 分层 summary；
- 不记录 benchmark hash；
- 不报告 P50/P95、forced-idle、channel utilization、峰值内存；
- Exact 只记录 opt，未记录 states/runtime/status/lower bound；
- skipped Exact 只有 id/reason，缺 family/category/path/budget；
- 不比较 Longest-delay，也没有 Stage 2 depth/budget 矩阵；
- Monte Carlo 仍进入主矩阵。

修正时应保持 runner 薄，只改善路由、配置和结果 schema。

### 7.2 当前 27 图重跑结果

在本次预算下 27/27 Exact 完成。结果如下：

| 算法标签 | mean ratio | observed max | optimal |
|---|---:|---:|---:|
| FIFO | 1.059284 | 1.521739 | 19/27 |
| SPT | 1.072904 | 1.521739 | 15/27 |
| LPT | 1.162848 | 1.800000 | 5/27 |
| Longest-delay | 1.015619 | 1.125000 | 21/27 |
| Longest-tail | 1.015619 | 1.125000 | 21/27 |
| LRPT | 1.015466 | 1.125000 | 21/27 |
| Rollout-2 | 1.000000 | 1.000000 | 27/27 |
| Join-Rollout-2 | 1.000000 | 1.000000 | 27/27 |
| Beam-8 | 1.000000 | 1.000000 | 27/27 |
| Beam-32 | 1.000000 | 1.000000 | 27/27 |

按现有类别：

| 类别 | n | Longest-tail mean | Longest-tail max | Longest-tail optimal |
|---|---:|---:|---:|---:|
| adversarial | 17 | 1.015502 | 1.125000 | 14/17 |
| random | 10 | 1.015819 | 1.055556 | 7/10 |

Longest-tail 的 6 个 gap 图是：

- `pm_longest_tail_counterexample`：9/8；
- `pm_random_join_30`：24/22；
- `pm_random_join_40`：22/21；
- `pm_complex_random_003`：21/20；
- `pm_complex_random_005`：20/19；
- `pm_complex_random_006`：19/18。

其中 `pm_longest_tail_counterexample` 是 Stage 1 结构，正式 Stage 2 结构子集的 Longest-tail gap 图实际为 5 个。

这些数值与旧文档所报 Stage 2 子集 `mean=1.01562, max=1.125, optimal=77.78%` 一致，说明历史实验可以复现。

### 7.3 旧结果应如何重新解释

可以保留的事实：

- 当前 27 图的 Exact 值可复现；
- residual longest-path 比简单 size priority 在该集合上更好；
- 一事件 Rollout、Join-Rollout 和两档 Beam 在该集合上均命中 Exact；
- 局部 join candidate 在该集合上未产生与普通 Rollout 不同的结果。

不能继续保留为当前结论的表述：

1. **“一般 DAG 仍保留 `T <= P+Q <= 2OPT`”**：当前 Stage 2 计划明确指出 Stage 1 的最后完成链 charging 不能直接推广；在新证明出现前，该说法未经支持。
2. **“Rollout shortlist 始终包含 Longest-tail baseline 动作，因此逐实例支配”**：当前 shortlist 使用 inclusive tail，completion baseline 使用 exclusive tail，代码不保证该包含关系。
3. **“27 图 100% observed optimal 表明 shallow Rollout/Beam 已形成一般 DAG 强基线”**：集合缺 fork、多层 barrier、shortlist omission 和固定宽度攻击，且规模很小。
4. **“Join-Rollout 无改进说明 join 信息价值有限”**：当前 join 特征只覆盖直接 child 的 last-blocker，且没有目标攻击集和消融。
5. **“48 个 single-channel 总体均值代表 Stage 2”**：总体表混入 Stage 1，Stage 2 必须独立分层报告。

旧表应保留为历史复现材料，但在文档上加研究边界；算法定义、benchmark 和 Exact 契约修正后，应生成新的版本化 Stage 2 报告，不能覆盖旧文件。

## 8. 理论部分审查

Stage 2 当前可以安全继承“Stage 1 是其受限子类，因此复杂性不低于 Stage 1”的研究方向，但具体 strong NP-hardness 仍应引用已审查的 Stage 1 证明及相同模型条件。

以下内容尚未形成当前模型下可审查的 Stage 2 成果：

- `P` 与无竞争最长因果路径 `L` 的正式安全下界证明稿；
- join/barrier release-demand 更强下界；
- out-tree/in-tree/单层 fork-join 等特殊情形；
- local tail、immediate release、join-only heuristic 的参数化反例；
- 一般 DAG work-conserving 统一近似界。

特别是旧文档中的一般 DAG 2-bound 应标记为历史未证外推。现有 27 图没有违反某个界，只是经验观察，不能修复证明缺口。

## 9. 阶段退出条件评估

| Stage 2 退出要求 | 当前状态 |
|---|---|
| 一般 DAG contract、fork/join/barrier/同刻事件最小验证 | 部分；公共语义存在，family 专用测试不足 |
| 所有算法复用公共 simulator/trace | 基本满足 |
| 未压缩 Exact 与独立 Oracle 一致 | 未满足；现有 Exact 已压缩，虽有小图一致证据 |
| Exact 压缩/支配/lower bound 有安全说明 | 未满足 |
| Exact 可解边界与完整统计 | 未满足，现有 27 图全部过易 |
| Longest-delay/Longest-tail/LRPT 独立定义 | 未满足 |
| join/barrier-aware priority 与消融 | 未满足 |
| Stage 2 Rollout/Beam depth、候选和预算研究 | 未满足 |
| random/adversarial/real/structured 三层 benchmark | 未满足；无 preemptive real/structured |
| 可解释的一般 DAG 失败实例 | 部分；有 5 个结构性 LT gap，但覆盖有限 |
| reference hash 与 optimal 状态契约 | hash/值匹配；status 契约不完整 |
| Stage 2 独立逐例和分层报告 | 未满足；当前是 Stage 0–4 合并 runner |
| Stage 1 结论未错误外推 | 未满足；旧进度文档外推了 2-bound |

结论：**Stage 2 尚处在“公共框架与初步原型可用、研究闭环未建立”的状态，不能进入阶段退出。**

## 10. 本次变更边界

本次只新增审查和修正方案文档，没有修改：

- simulator、solver、registry 或 public interface；
- tests、benchmark、schema、reference result；
- `experiments/` runner；
- 旧结果和历史文档。

详细修正顺序见 `stage2_complex_chain_review_modification_plan_20260816.md`。
