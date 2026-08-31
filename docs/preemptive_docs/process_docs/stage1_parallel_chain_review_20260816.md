# Stage 1：single-channel parallel chain 审查记录

日期：2026-08-16

## 1. 审查范围与依据

本次审查只覆盖 `single_channel/parallel_chain/preemptive` 对应的一阶段问题，不审查 `complex_chain`、多 channel、LLM 特化和不可抢占算法本身。

主要依据：

- `docs/plan_docs/outline.md`
- `docs/plan_docs/stage1_parallel_chain.md`
- `src/single_channel/parallel_chain/preemptive/`
- 与该入口直接相关的公共可抢占执行器、trace validator、registry、benchmark、reference result 和测试
- 一阶段历史实验表及其当前可复现性

`experiments/` 按其真实职责作为薄的运行、汇总接口审查。它不是算法或模拟器的实现位置，因此本文不会把其中缺少算法实现认定为缺陷；只检查它是否正确调用一阶段入口并输出足以支持结论的数据。

## 2. 总体结论

目前的一阶段状态可以概括为：**公共可抢占语义已有较可信的基础，旧实验数字也能复现，但 parallel-chain 专用研究实现仍然很薄，尚未达到 `stage1_parallel_chain.md` 的阶段退出条件。**

最重要的结论有四点：

1. `parallel_chain/preemptive/solver.py` 目前主要转发到一般 DAG 的 `complex_chain` solver。它可以计算这些实例，却没有实现计划要求的 compact chain state、chain-specific Exact 和经过清晰区分的一阶段算法族。
2. 当前 FIFO 与阶段文档定义不一致；Longest-delay 与 Longest-tail 实际上是别名；Rollout 的候选排序又使用了与 Longest-tail 不同的 tail 口径。这些问题会影响算法命名和旧结果的解释。
3. parallel-chain 输入校验只限制入度和出度不超过 1，没有验证 compute/communication 交替，因此会接受不属于阶段标准形式的连续 communication 链。
4. 历史表格可以原样复现，但它只证明当前代码能重现旧数值，不证明理论结论、Exact 的 compact 性或 benchmark 的代表性已经成立。

因此，不建议推翻公共模拟器或重写整个项目；下一步应在现有公共执行语义之上补齐一阶段专用契约、Exact、算法定义、测试和实验材料。

## 3. 与计划一致、可以保留的部分

### 3.1 公共可抢占执行语义

在一阶段会经过的公共执行路径上，以下目标语义已经体现：

- compute ready 后自动开始且不可抢占；
- communication 保存剩余工作，可以在调度事件处切换和恢复；
- 单 channel 同时只运行一个 communication；
- 有 eligible communication 时不能主动 WAIT；没有 eligible communication 时只能 forced idle 到下一事件；
- 算法通过调度选择驱动公共状态转移，而不是自行推进另一套时间线；
- trace 有独立的回放/可行性检查路径。

相关定向测试通过。以一阶段公共路径为范围运行后，结果为 `11 passed, 4 deselected`。这说明公共模拟器适合作为继续建设一阶段实现的基础，但不等于其他研究阶段已经经过本次审查。

### 3.2 family 边界已有基本入口

仓库已经有对等目录：

- `src/single_channel/parallel_chain/preemptive/`
- `benchmark/single_channel/parallel_chain/preemptive/`
- `tests/single_channel/parallel_chain/preemptive/`

parallel-chain 入口会拒绝 fork/join，因为它要求每个节点入度、出度均不超过 1。这避免了一般 complex DAG 被直接当作 parallel chain 使用。问题在于该约束还不够完整，详见 4.3。

### 3.3 residual tail 的基础计算考虑了剩余工作

一般 solver 中的 residual-tail 计算会对运行中或暂停的 communication 使用剩余工作，而不是始终使用原始 duration。这一点符合可抢占模型要求，可以作为 Longest-tail/LRPT 后续澄清定义时的共同基础。

### 3.4 reference result 的现存部分自洽

本次核验了 parallel-chain/preemptive 下现有的 12 条 reference result：

- benchmark hash 全部匹配；
- 当前 Exact 重算的 makespan 全部与 reference result 一致。

这表明这些 reference 文件没有出现明显的 hash 漂移或结果漂移。不过它们只覆盖现有 benchmark 的一部分，不能替代完整的一阶段 Oracle 建设。

## 4. 主要审查发现

### 4.1 高优先级：parallel-chain solver 只是一般 DAG solver 的转发层

`src/single_channel/parallel_chain/preemptive/solver.py` 中的 Longest-tail、priority、Rollout、Beam、Monte Carlo 和 Exact 都委托给 `single_channel/complex_chain/preemptive/solver.py`。

这不是执行正确性错误：parallel chain 本来就是一般 DAG 的子集，复用公共转移也符合架构要求。但它与一阶段计划存在明显缺口：

- 没有显式的 chain/frontier 状态；
- 没有 compact Exact；
- 没有针对平行交替链的状态压缩与未来等价论证；
- 没有 compact Exact 与未压缩 Oracle 的系统交叉验证；
- 没有证明或展示一阶段 Exact 的规模扩展能力；
- 算法名称虽然位于 parallel-chain 包下，实质仍是一般 DAG 算法。

因此当前实现更准确的定位是“用通用 solver 支持 parallel-chain 输入”，而不是“阶段一专用实现已经完成”。

### 4.2 高优先级：FIFO 的实现不符合阶段定义

阶段文档定义的 FIFO 是按 communication **首次 eligible 的时间**排序，并用 task ID 做稳定 tie-break。

当前实现使用预先生成的静态拓扑/task-ID 顺序。最小反例中：

- communication `z` 在 `t=1` eligible 并开始运行；
- communication `a` 在 `t=10` 才 eligible；
- 到 `t=10`，静态顺序使新到的 `a` 抢占已经等待/运行更久的 `z`。

得到的动作序列为：

```text
t=0  forced idle -> 1
t=1  run z -> 10
t=10 run a -> 12
t=12 resume z -> 23
```

这不是阶段定义下的 FIFO。旧表中标为 FIFO 的数据只能解释为“静态 task-order baseline”，不能继续当作 arrival/eligibility FIFO 使用。

### 4.3 高优先级：parallel-chain 标准形式未被完整校验

计划中的一阶段输入是多条独立的 compute–communication 交替链；链可以从任一类型开始或结束，允许零时长 compute，但 benchmark 不应含零工作量 communication。

当前 `validate_parallel_chain` 和 benchmark validator 只检查 DAG 以及节点入度/出度不超过 1。一个最小输入：

```text
communication x -> communication y
```

能够通过 parallel-chain 校验，并被 Exact 求得 makespan 2。它虽然是路径，却不是计划中的交替链标准形式。

另一方面，旧转换辅助逻辑又比阶段定义更窄：它隐含要求 communication 后有 compute，不能自然表达“以 communication 结束”的合法链。当前缺少一个独立于不可抢占实现、且准确覆盖阶段标准形式的中立解析/规范化层。

### 4.4 高优先级：Longest-delay、Longest-tail 和 LRPT 没有按研究定义分开

当前 `longest_delay` 与 `longest_tail` 使用相同分数，registry 也把前者明确作为兼容别名。这意味着历史探索并没有独立比较两个概念。

按阶段文档，至少需要区分：

- Longest-delay：面向下一段后续 compute delay 的局部量；
- Longest-tail：当前 communication 完成之后的 residual downstream tail；
- LRPT：包含当前 communication 剩余工作的 residual path。

当前 Longest-tail 与 LRPT 的“是否包含当前剩余 communication”已有形式上的区别，但 Longest-delay 没有自己的语义。继续用三个名字报告结果会造成重复算法被误认为独立 baseline。

### 4.5 高优先级：Rollout 的候选排序与其标注的 tail baseline 不一致

completion baseline 的 Longest-tail 分数排除了当前 communication 的剩余工作；Rollout 在 `mode="tail"` 下生成 shortlist 时却按包含当前剩余工作的 tail 排序，更接近 LRPT。

构造样例可使 Longest-tail 首选 `c`、`rollout2` 首选 `a`。该样例上最终 makespan 恰好相同，所以它不是 Rollout 性能反例，但清楚证明了候选口径不一致。

因此旧的 `rollout2` 结果可以数值复现，却不能未经说明地解释为“只从 Longest-tail 前 2 个候选做 rollout”。需要先固定候选定义，再重新命名或重跑结果。

### 4.6 中高优先级：Exact 正确性有小样例支持，但没有完成阶段要求

本次额外生成 30 个严格交替的小型 parallel-chain 图，将现有事件 Exact 与独立 tick Oracle 比较，30 个结果全部一致。这是积极证据，说明通用 Exact 在这些小图上没有暴露状态转移错误。

但当前测试库中没有把这种交叉验证固化为一阶段回归测试；正式的一阶段测试只有很小的 smoke test。并且通用 Exact：

- 使用一般 DAG 状态 key；
- 未使用 chain frontier 的 compact representation；
- 未把一阶段 lower bound、branch-and-bound 或对称性消除系统集成；
- 未提供压缩/未压缩状态等价验证；
- 在两个现有样例上仍达到给定 timeout/state budget。

所以应把它定位为当前可用的通用小图 Oracle/交叉验证对象，而不是阶段一 compact Exact 已完成。

### 4.7 中优先级：算法注册表超出一阶段问题边界

parallel-chain registry 当前暴露了与一般 DAG 相同的算法矩阵，其中包括：

- `join_rollout2`：parallel chain 没有 join，名称与场景无关；
- `monte_carlo64`：阶段文档将 Monte Carlo 定位为历史探索，不应与当前核心算法同等展示；
- `longest_delay`：当前只是 Longest-tail 别名。

这些入口未必会算错，但会让公开接口传达错误的研究成熟度和算法独立性。

### 4.8 中优先级：benchmark 数量存在，但阶段覆盖与来源说明不足

当前有 23 个 preemptive parallel-chain benchmark：

- `random` 10 个；
- `adversarial` 13 个；
- 没有一阶段 `real` 或 `structured` 固定集。

多个 adversarial 样例是从旧 v1/不可抢占探索直接 lift 到新格式，metadata 主要记录 `generator=parallel_chain` 和 `lifted_from`，没有说明攻击哪个算法、触发什么机制、为什么在“无主动 WAIT”的可抢占模型下仍然有效。例如含 `optional_wait` 含义的旧样例名容易把历史不可抢占问题带入当前解释。

这不表示 lift 后的 DAG 一定非法，而是它们的研究意义需要重新证明，不能仅因 validator 通过就视为当前阶段的有效攻击集。

此外还缺少：

- 明确构造逻辑的 Longest-delay/Longest-tail/LRPT/FIFO/Rollout 攻击集；
- 规模化 structured family；
- LLM workload 的 parallel-chain 投影快照；
- 多 job 到 independent chains 的适用条件和映射样例。

### 4.9 中优先级：一阶段专用测试覆盖不足

公共执行器测试对可抢占语义已有覆盖，但一阶段 family 自己需要承担的契约没有得到足够测试：

- compute/communication 必须交替；
- chain 可从任一类型开始和结束；
- 链之间不得有交叉依赖；
- FIFO 首次 eligible 时间；
- 三类 tail/delay 分数区分；
- Rollout shortlist 和 completion policy 的口径；
- compact Exact 与独立 Oracle/通用 Exact 的交叉验证；
- trace 中的暂停、恢复、工作量守恒与 tie-break。

这些不能全部依赖 complex-chain 或公共 simulator 测试间接保证。

### 4.10 中优先级：理论探索尚未形成当前模型下的可审查成果

阶段计划要求当前可抢占、无主动 WAIT、独立交替链模型下的：

- NP-hardness 结论；
- `T_H <= P + Q <= 2 OPT` 一类上界；
- `max(P,Q,L)` lower bound；
- 受限情形结论及明确适用范围。

仓库中能看到历史想法和计划，但本次范围内没有找到足以按当前模型逐条审查的正式证明材料。对 23 个现有样例的检查没有发现 Longest-tail 超过 `P+Q` 的情况，但经验检查不能替代理论证明。

因此这些内容应标为“待证明/待重新审查”，不应因实验最优率较高而视为成立。

### 4.11 `experiments/` 的准确定位及其实际问题

`experiments/preemptive/stage0_4.py` 是薄 runner，不是算法实现。这一点与仓库说明一致，本次没有因它不包含 Exact/heuristic 逻辑而提出缺陷。

它当前与一阶段相关的实际问题是接口路由和报告粒度：

- 对 single-channel 输入统一直接调用 general/complex solver，而非 parallel-chain 稳定入口；
- 汇总时把多个 single-channel family 放入总体 summary，虽保留 family 字段，但不能直接形成一阶段独立报告；
- 旧指标没有完整呈现 forced-idle 时间、利用率、抢占次数和按 random/adversarial/real 分组的结果。

这些应通过保持其“薄”来修正：只改调用和汇总，不应把算法代码搬进 `experiments/`。

## 5. 历史结果再核验

使用当前 parallel-chain wrapper、每例 Exact 上限 150,000 states/5 seconds，对现有 23 个一阶段 benchmark 重跑：

- Exact 完成 21 个；
- `pm_fixed_beam_counterexample` timeout；
- `pm_random_chain_6` timeout。

对 21 个有 Exact 的样例，结果为：

| 算法标签 | 平均 ratio | 最大 ratio | 最优数/总数 |
|---|---:|---:|---:|
| FIFO | 1.197951 | 1.863636 | 7/21 |
| SPT | 1.187338 | 1.521739 | 5/21 |
| LPT | 1.251779 | 1.863636 | 3/21 |
| Longest-tail | 1.016053 | 1.212121 | 19/21 |
| LRPT | 1.025260 | 1.212121 | 15/21 |
| rollout2 | 1.000000 | 1.000000 | 21/21 |
| beam8 | 1.000000 | 1.000000 | 21/21 |
| beam32 | 1.000000 | 1.000000 | 21/21 |

Longest-tail 的两个非最优样例为：

- `pm_longest_tail_counterexample`：9 vs Exact 8；
- `pm_scaled_five_four_s4`：40 vs Exact 33。

按现有目录类别拆分：

- adversarial，12 个有 Exact：Longest-tail 平均 1.028093，最大 1.212121，最优 10/12；
- random，9 个有 Exact：Longest-tail 全部最优；
- rollout2 在这 21 个样例上全部达到 Exact。

这些数值与旧表一致，说明旧结果在当前代码路径上可复现。但必须附加以下解释限制：

1. FIFO 实际是静态 task-order，不是计划定义的 eligibility FIFO；
2. rollout2 的候选 tail 口径与 Longest-tail 不一致；
3. Exact timeout 的样例不能纳入“已知最优率”分母；
4. 21 个小样例上的 100% 不能解释为 Rollout/Beam 的理论最优性；
5. 当前集合缺少 real/structured，且 adversarial 来源说明不足；
6. 没有报告 runtime 分布、状态数、forced idle、利用率和抢占次数，不能完整支持算法比较。

因此旧表应保留为“历史实现复现基线”，在算法定义和 benchmark 语义修正后生成新的版本化表格，不应直接覆盖或继续扩展旧结论。

## 6. 阶段退出条件评估

| 计划要求 | 当前判断 |
|---|---|
| 公共可抢占语义一致 | 基本具备，一阶段相关定向测试通过 |
| parallel-chain 标准形式 | 部分具备；只限制路径结构，未验证交替类型 |
| 正式 NP-hardness/上界/lower bound | 未形成当前模型下可审查成果 |
| compact chain-specific Exact | 未实现；当前为通用 Exact 转发 |
| 独立 Oracle 交叉验证 | 临时小样例核验通过，但未固化为测试 |
| 一阶段 heuristic 定义清晰 | 未满足；FIFO、Longest-delay、Rollout 口径有偏差 |
| random/adversarial/structured/real | 只有 random/adversarial，且攻击集说明不足 |
| 多 job 映射 | 未完成 |
| 完整实验指标 | 未满足 |

结论：**Stage 1 尚不能宣布完成。** 不过现有公共模拟器、trace validator、通用 Exact 和可复现基线可以保留，适合作为下一轮有边界修正的基础。

## 7. 本次核验的边界

本次没有：

- 修改任何算法、模拟器、benchmark、schema 或测试；
- 审查 complex-chain 或多 channel 算法的研究质量；
- 把不可抢占实现当作当前语义依据；
- 把 `experiments/` 当作真正的实验算法实现；
- 将临时生成的 30 个小图或反例写入正式 benchmark。

具体建议和推进顺序另见 `stage1_parallel_chain_next_steps_20260816.md`。
