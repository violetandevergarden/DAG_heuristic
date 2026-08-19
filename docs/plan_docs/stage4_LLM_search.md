# Stage 4：真实 LLM Training DAG 的研究总纲

## 1. 研究目标

Stage 4 面向真实的 LLM training DAG，研究通信资源发生竞争时如何选择通信、暂停和恢复通信，以及如何利用训练图中真实存在的结构改善整体完成时间。

本阶段的输入主体必须来自 `third_party/simai-flow-scheduler`。其中的 AICB workload 描述训练通信和计算，topology 描述通信资源和路径。研究工作先把这些输入转换成项目自己的、自包含的 DAG benchmark，再在统一模拟器上比较调度方法。

Stage 4 不改变已经确定的执行语义：DAG 依赖是 finish-to-start；compute ready 后自动开始且不可抢占；communication 可以在调度事件处暂停和恢复；固定多资源通信启动或恢复时一次性取得全部资源；资源互不冲突的通信可以并行；没有主动 WAIT；默认目标是联合 DAG makespan。算法只从模拟器给出的合法通信或合法兼容集合中选择动作，不得实现另一套状态转移。

## 2. 总体原则

### 2.1 真实输入优先

4a 和 4b 的主要证据必须来自 SimAI flow scheduler 的真实 AICB workload、topology 及其转换结果。手工小图用于验证语义、制作反例和检查程序，但不能替代真实 DAG 的结构结论。

### 2.2 先确认冲突

任务很多但始终只有一个合法通信，或通信资源集合始终互不相交的 DAG，不能说明调度算法有价值。每个 benchmark 都要记录同时合法通信、资源相交、竞争持续时间、选择事件数量，以及 FIFO/Longest Tail 是否产生不同动作。无有效竞争的样例只能作为负面对照。

### 2.3 控制规模和耗时

普通样例覆盖模型、并行度、pipeline、DP、job 和 topology 的变化；超大 DAG 约保留 10 个，用于观察运行时间和规模趋势。生成、转换、扫描和算法运行都记录耗时。timeout、内存限制和 partial probe 必须单独标记，不能当作最优或完整结论。

### 2.4 结果分级

小图使用 Exact 检查最优 makespan 和首动作；真实大图通常没有 Exact，统一比较 FIFO、基础 Longest Tail 和候选算法。大图报告完成时间、相对基线变化、运行时间、抢占、forced-idle、资源利用率和未完成状态，不报告最优率或理论近似比。

## 3. 阶段关系

```text
4a 真实 benchmark 构建与竞争筛选
        ├── 4b 真实 DAG 结构理论
        ├── 4c 固定多资源 Conflict-Graph Packing
        ├── 4d Selective Rollout
        ├── 4e Barrier 感知调度
        └── 4f Multi-job 调度
                         ↓
                    4g 综合算法
```

正式分纲领为 `stage4a_benchmark.md`、`stage4b_structure_theory.md`、`stage4c_conflict_graph_packing.md`、`stage4d_selective_rollout.md`、`stage4e_barrier_scheduling.md`、`stage4f_multi_job_scheduling.md` 和 `stage4g_integrated_algorithm.md`。

## 4. 4a：真实 Benchmark 构建

使用 AICB workload、topology 和 SimAI 的解析/任务展开逻辑，保留任务依赖、任务类型、工作量、固定资源集合和来源信息。转换结果必须是自包含 JSON，记录 workload、topology、转换参数、DP/job 数量、规模和 hash。

单个 workload 可能没有足够竞争，需要增加 DP 数量，或重复同一个 workload、混合不同 workload 形成多个 job。不同 job 之间只共享资源，不共享训练依赖。每次增加 DP/job 都要检查是否真的增加了资源竞争，而不是只增加任务数。

正式集合至少包括单 job 小图、真实竞争单 job、多 iteration、多个 job 混合和约 10 个超大规模样例。4a 只有在转换语义、竞争准入、规模预算和基线运行时间都有证据后结束。

## 5. 4b：真实 DAG 结构理论

只在真实 SimAI DAG 上研究 micro-batch、iteration、pipeline phase、PP/TP/DP/EP collective、join、optimizer barrier、重复模板和资源占用。对每个结构记录出现频率、与竞争事件的重合、对调度分歧的影响、反例和适用边界。

高重复只能作为描述性事实，不能直接推出局部 schedule 可以复制，也不能未经 future-equivalence 证明就合并状态。合成 motif 只用于隔离变量和构造反例。只有在不同 workload/topology 中重复出现、能解释策略分歧且没有明显最坏退化的结构，才进入后续算法。

## 6. 4c：固定多资源 Conflict-Graph Packing

每个通信具有固定资源集合，当前候选形成冲突图。资源集合相交的通信之间有边，合法动作是 work-conserving 的极大独立集。研究 FIFO、Longest Tail greedy-fill、冲突图评分、multi-seed、局部交换和受预算的集合级前瞻。

必须分离“单通信分数”和“集合构造”两个因素。静态资源负载、集合大小或 union downstream 不能自动代表未来 makespan。小图与 Exact 比较，大图按统一预算比较构造时间、集合质量和最终完成时间。

## 7. 4d：Selective Rollout

全量 rollout 在每个有多个候选的事件点枚举首动作，执行公共 transition，再以 Longest Tail completion 比较候选。Selective rollout 增加低成本 choice gate，只在 Longest Tail margin 小、候选立即释放 compute/join/barrier、资源冲突强或简单策略分歧时触发。平局、超时、状态限制和异常都回退 Longest Tail。

需要比较 top-2/depth-1、top-4/depth-1、top-2/depth-2 和 set-level rollout，并在相同调用、展开节点和墙钟预算下对照随机/周期触发。退出必须有触发 precision、regret recall、漏触发、成本、收益和最坏退化，而不是只报告平均 makespan。

## 8. 4e：Barrier 感知调度

Barrier 指 pipeline、DP/TP/EP collective、optimizer join 或多个分支汇合形成的同步屏障。研究候选通信是否为最后缺口、会释放哪些计算、各分支 slack 如何，以及提前完成是否真正改变最终 makespan。

Barrier 信息不作为替代 Longest Tail 的独立 priority，而作为候选筛选、分数接近时的修正或 rollout challenger 特征。必须包含“靠近 barrier 但不值得优先”和“暂停关键长通信反而变差”的反例。若收益不稳定，保留为 selective rollout 的增强信息。

## 9. 4f：Multi-job

Multi-job benchmark 必须由多个 AICB workload 混合得到。job 独立运行，只共享固定资源。分别研究 flat Longest Tail、weighted Longest Tail、shortest remaining、attained service 和有限 rollout，并明确 makespan、JCT、weighted JCT、slowdown 和 fairness 的目标差异。

先用小图 Exact 或首动作穷举判断 job-level 选择是否有价值，再在真实中型图和少量大图比较。必须报告每个 job 的完成时间和等待情况，不能只看联合 makespan。若简单 flat Longest Tail 已足够，记录这一结论；若专用策略只改善 weighted JCT，不能称为 makespan 改进。

## 10. 4g：综合算法

综合流程以 Longest Tail 为默认方向，多资源用 deterministic maximal packing；barrier 负责筛选或增强候选；Selective Rollout 只在困难状态调用；multi-job 根据声明的目标选择 job policy。逐组件消融 FIFO、Longest Tail、packing、barrier、selective rollout 和最终组合。

大图没有 Exact 时统一比较 FIFO、Longest Tail 和候选组合，报告完成时间、运行/内存成本、调用次数、抢占、forced-idle、超时和最坏退化。Stage 4g 只有在真实 holdout、组件消融、反例、成本和理论解释都完成后结束；结果可以是综合算法有效、只有部分组件有效，或 Longest Tail 加简单 packing 已足够。

## 11. 统一报告与边界

所有实验记录来源 hash、workload/topology、DP/job、任务/资源规模、是否存在竞争、算法配置、makespan 或 per-job completion、运行时间、rollout 调用、展开数、抢占、forced-idle、资源利用率、timeout 和 fallback。旧结果在 benchmark 或语义变化后必须重新核验。

不研究动态选路、迁移、部分资源获取、按比例共享带宽、协议内部 chunk 同步、拥塞控制、抢占恢复开销和没有固定 topology 的真实网络外推。不能用合成 motif 或单一 workload 推断所有 LLM DAG，也不能把大图启发式结果称为最优。
