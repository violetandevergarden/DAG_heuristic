# Stage 4d：Stage 1--3 受控竞争图上的 Selective Rollout 结果（2026-08-21）

## 1. 结论

此前真实 AICB DAG 的结果只能说明：以“候选首动作后完整运行 residual Longest Tail 到结束”为评价器时，1536 和 2204 节点图的单次评价无法在冻结预算内完成，因而 Selective Rollout 全部回退为 Longest Tail（LT）。这不能回答 Rollout 或选择性触发本身是否有效。

本轮改用仓库 Stage 1--3 的小型、可控竞争图重新验证。结论是：**在单通道 Stage 1/2 的 74 个样例上，depth=2 的完整 Rollout 能稳定改进 LT；冻结的 Selective Rollout 保留了几乎全部该收益，并显著少做候选 completion。** 因而“Rollout 有效、Selective Rollout 值得继续研究”的早期判断没有被推翻。真实中图的负结果应归因为当前终端评价器成本，而不是算法机制无效。

但这仍是合成/结构化受控图的机制证据，**不是**真实 LLM DAG 上已经获得同等收益的证明。

## 2. 实验对象和公平比较

所有样例均来自仓库现有的可抢占 benchmark，未新增样例，任务数为 3--30：

| 集合 | 样例数 | 任务数 | 用途 |
|---|---:|---:|---|
| Stage 1 parallel-chain | 29 | 6--30 | 独立链竞争、LT 和有限深 Rollout 反例 |
| Stage 2 complex-chain | 45 | 4--24 | fork/join、同步和跨多次决策投资 |
| Stage 3 fixed multi-resource | 22 | 3--23 | 合法极大兼容集合与资源冲突 |

随机、攻击和结构化/real-derived 子集分别统计。74 个单通道样例中有 71 个带 benchmark hash 一致的 Exact 最优参考；Stage 3 中有 12 个带 Exact 参考。运行前重新比对了所有被使用参考的 `benchmark_sha256`，没有不一致。

单通道算法统一采用：

- **FIFO** 与 **LT**：公共模拟器上的确定性基线；
- **Full Rollout**：每个 `candidate_choice` 状态均触发；候选宽度 2、分支深度 2；
- **Selective Rollout**：与 Full 完全相同的候选、深度、终端策略和严格采用规则，只改触发器；
- **周期/随机对照**：周期 4，以及概率 0.25 的三个固定种子。

`depth=2` 的含义是两个会分支的通信决策层；达到深度后，以 residual LT 补全到终点。每个候选只有在两侧 evaluation 都完整，且优于 LT 候选时才被采用。所有分支均通过公共模拟器推进，不存在主动等待或私有时间推进。

Selective 的冻结触发规则为：

```text
LT 与 LRPT 分歧
或
(LT 前两名 residual-tail 归一化分差 <= 0.25
 且候选的立即 compute 释放量不同或 join 最后缺口属性不同)
```

本轮为了测量机制而将预算设为非约束性上限（10000 次触发、100000 次 completion、500 万次展开；不设墙钟上限）。这不是在线部署预算；它保证测到的是完成的 Rollout 决策，而非 budget fallback。

## 3. 单通道总体结果：Full 和 Selective 都实际完成了评价

| 方法 | 相对 LT：胜/平/负（74） | LT 改善总量 | completion 调用 | 完整 rollout 评价 | fallback | Exact 最优（71） |
|---|---:|---:|---:|---:|---:|---:|
| FIFO | 2 / 36 / 36 | -152 | 0 | 0 | 0 | 31 / 71 |
| LT | 0 / 74 / 0 | 0 | 0 | 0 | 0 | 60 / 71 |
| Full Rollout w2,d2 | **11 / 63 / 0** | **20** | 1095 | 343 | 0 | **71 / 71** |
| Selective combined w2,d2 | **10 / 64 / 0** | **19** | **526** | 158 | 0 | **70 / 71** |
| 周期 4 w2,d2 | 7 / 67 / 0 | 14 | 365 | 119 | 0 | 67 / 71 |
| 随机 seed 0 | 0 / 74 / 0 | 0 | 0 | 0 | 0 | 60 / 71 |
| 随机 seed 1 | 7 / 67 / 0 | 14 | 314 | 99 | 0 | 67 / 71 |
| 随机 seed 2 | 1 / 73 / 0 | 1 | 291 | 91 | 0 | 61 / 71 |

这里的“改善总量”是逐图 `makespan(LT) - makespan(method)` 的和，不能解释为百分比或真实工作负载频率。Full 和 Selective 的所有 completion 都完整完成，且两者均无 fallback。因此其结果不是“超时后恰好与 LT 相同”。

与 Full 比较，Selective：

- 保留 **10/11** 个被 Full 改进的实例；
- 保留 **19/20** 单位 makespan 改善，即 **95%** 的 Full 已观察收益；
- 将 completion 调用由 1095 降至 526，减少 **52.0%**；
- 同一次运行中的算法墙钟由约 708.9 ms 降至约 478.1 ms，减少约 **32.6%**。该小图墙钟会受机器噪声影响，主要成本证据是调用数和完成评价数。

Selective 没有在 74 图中造成相对 LT 的退化，但这不是一般安全保证：有限 completion policy 只能在自己的评价下严格采用，仍可能在别的实例上造成端到端退化。

## 4. 按阶段和类别的结果

| 子集 | LT Exact 最优 | Full：胜/平/负，改善 | Selective：胜/平/负，改善 | 解释 |
|---|---:|---:|---:|---|
| Stage 1 攻击（14） | 10 / 13 | 3 / 11 / 0，10 | 3 / 11 / 0，10 | Selective 完整保留 3 个链式反例的收益 |
| Stage 1 随机（10） | 9 / 9 | 0 / 10 / 0，0 | 0 / 10 / 0，0 | LT 已足够；没有虚构收益 |
| Stage 1 real-derived（5） | 4 / 5 | 1 / 4 / 0，1 | 1 / 4 / 0，1 | 保留唯一可改善例 |
| Stage 2 攻击（22） | 18 / 22 | 4 / 18 / 0，6 | 3 / 19 / 0，5 | 有一个 join 例被触发器漏掉 |
| Stage 2 随机（20） | 16 / 19 | 3 / 17 / 0，3 | 3 / 17 / 0，3 | 与 Full 相同 |
| Stage 2 real-derived（3） | 3 / 3 | 0 / 3 / 0，0 | 0 / 3 / 0，0 | LT 已是最优 |

Full Rollout 在全部 71 个带证书的单通道图上均达到 Exact 最优；LT 为 60/71；Selective 为 70/71。这个结果限定于本轮 `width=2, depth=2, residual-LT completion` 协议和这批小图，不构成任意深度、任意候选宽度的最优性结论。

## 5. 具体改善与触发器漏例

Full Rollout 相对 LT 严格改善的 11 个实例为：

| 阶段 | 样例 | LT | Full | Selective |
|---|---|---:|---:|---:|
| Stage 1 | `pm_longest_tail_counterexample` | 9 | 8 | 8 |
| Stage 1 | `pm_rollout_depth_counterexample` | 49 | 47 | 47 |
| Stage 1 | `pm_scaled_five_four_s4` | 40 | 33 | 33 |
| Stage 1 | `pm_zero_bubble_chain_projection` | 13 | 12 | 12 |
| Stage 2 | `pm_longest_tail_counterexample` | 9 | 8 | 8 |
| Stage 2 | `pm_random_join_30` | 24 | 22 | 22 |
| Stage 2 | `pm_random_join_40` | 22 | 21 | **22** |
| Stage 2 | `pm_stage2_rollout_depth` | 23 | 21 | 21 |
| Stage 2 | `pm_complex_random_003` | 21 | 20 | 20 |
| Stage 2 | `pm_complex_random_005` | 20 | 19 | 19 |
| Stage 2 | `pm_complex_random_006` | 19 | 18 | 18 |

`pm_random_join_40` 是当前触发器的明确反例：Full 在该状态完成了使 22 降至 21 的 Rollout，而 combined trigger 未触发，因而保留 LT 的 22。这个漏例说明不能把“节省一半调用”写成“完全等价于全量 Rollout”。它也给出下一步的直接改进目标：检查该状态的 join/释放特征，补充能识别此类收益敏感 join 的低成本条件，并在未参与设计的样例上重新冻结阈值。

## 6. Stage 3 多资源：有正面信号，但还不是 Selective 结论

Stage 3 使用的是固定资源集合、合法 inclusion-maximal compatible set。Full set Rollout 使用同样的 w2,d2 协议；但现有多资源 `TriggerFeatures` 还没有实现与单通道 combined 相当的 tail-margin、释放差和 join 差特征。因此本轮只能比较 Full 与周期/随机抽样对照，不能把周期触发称为“多资源 Selective Rollout 算法”。

| 子集 | LT Exact 最优 | Full 相对 LT：胜/平/负，改善 | 说明 |
|---|---:|---:|---|
| Stage 3 攻击（9） | 9 / 9 | 0 / 9 / 0，0 | LT packing 已在已认证图最优 |
| Stage 3 随机（10） | 无 Exact 参考 | 2 / 8 / 0，2 | `pm_muti_random_003`：19→18；`pm_muti_random_008`：28→27 |
| Stage 3 real-derived（3） | 3 / 3 | 0 / 3 / 0，0 | LT packing 已最优 |

Full multi-resource Rollout 在 22 图上完成 56 次评价、165 次 completion，未发生 fallback。周期 4 对照则出现一次改善和一次退化（总改善为 0）；随机 seed 1 也有一次退化。这表明“少量任意触发”并不自动有效，Stage 3 需要先补齐真正的低成本多资源触发特征，才能讨论 Selective 的质量—成本平衡。

## 7. 对此前真实 DAG 结论的修正

两组结果应同时成立，不能互相覆盖：

| 问题 | 当前证据 |
|---|---|
| Rollout 是否能修正 LT？ | 能。Stage 1/2 小图上 Full w2,d2 将 LT 的 60/71 Exact 最优率提升至 71/71。 |
| Selective 是否能以较少搜索接近 Full？ | 能，在该受控单通道集上保留 95% 已观察改善，调用少 52.0%，但漏掉一个已知 join 例。 |
| 真实中型 LLM DAG 上是否已经验证收益？ | 没有。此前 1536/2204 图的 completion evaluator 在预算内未完成，所有选择回退 LT。 |
| 真实中型失败是否证明算法无效？ | 不证明；它证明当前“完整 LT completion 到终点”的评价器成本不适合该规模。 |
| 是否可直接部署为通用算法？ | 不可。还需要独立 holdout、随机更大图、评价器成本优化，以及多资源触发器。 |

因此更准确的研究定位是：**Selective Rollout 的决策机制在可控竞争图上已得到正面验证；Stage 4d 的主要未解问题是如何用截断/学习/下界等低成本终端估值把这种能力带到真实中大图，而不是证明“要不要 Rollout”。**

## 8. 复现、验证与限制

- 入口：[stage4d_synthetic_rollout_evaluation.py](/D:/Code/SimAI/DAG_heuristic/experiments/preemptive/stage4d_synthetic_rollout_evaluation.py)
- 原始逐图数据：[stage4d_synthetic_rollout_evaluation_20260821.json](/D:/Code/SimAI/DAG_heuristic/docs/result_docs/stage4d_synthetic_rollout_evaluation_20260821.json)
- 运行命令：`$env:PYTHONPATH='src;.'; python experiments/preemptive/stage4d_synthetic_rollout_evaluation.py`
- 本轮针对性回归：`15 passed`（单通道和多资源 Selective Rollout 测试）。

各调度器在构造结果时都使用相应 Trace validator；本轮 96 图的算法运行均成功，且所有有限搜索方法的 fallback 数为零。基线的 `runtime_ms` 在旧求解器中未统一计时，故本报告不把 Selective 的墙钟与 LT 的零值作比；仅比较 Full 与 Selective 的同一计时路径。

本报告不改变先前真实 AICB 实验的原始文档。两类数据分开保存，避免把受控机制收益写成真实 LLM workload 的普遍收益。
