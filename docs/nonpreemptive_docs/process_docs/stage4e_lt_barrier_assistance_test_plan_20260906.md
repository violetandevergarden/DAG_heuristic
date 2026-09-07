# Stage 4e：Barrier 为 LT 提供候选与触发信号的探索

日期：2026-09-06  
状态：条件性待执行计划。依赖 [公共协议](stage4_lt_followup_test_protocol_20260906.md)、[结构诊断](stage4b_lt_failure_analysis_plan_20260906.md) 和 [4d 实验](stage4d_lt_assisted_rollout_test_plan_20260906.md)。遵守 [4e 分纲](../plan_docs/stage4e_barrier_scheduling.md)。

## 1. 研究范围

Barrier 不替换 LT。只检查两种辅助用途：
- E1：提供 LT 前两名以外、值得比较的一个挑战通信。
- E2：在相同候选集合下，选择什么时候调用已有 rollout。

两者分别消融，不能把多了候选的收益归为触发器准确。现有 4f 证据未证明 barrier 能预测 LT 失败，因此先做离线诊断，不直接重开大网格搜索。

## 2. 最小特征定义

join 定义为有至少两个不同直接前驱的 DAG 节点，不依赖名字。通信 B 为 last-missing，当且仅当该 join 未完成的直接前驱集合恰好是 {B}。该特征只说明 B 完成解除最后一个直接依赖，不保证 join 位于最终关键链。

其余特征分层加入：join 的 residual tail、B 完整 duration、共享下游集合、与当前 LT 动作的 tail 差。slack 若依赖未来通信排队预测，必须标 estimated；初版不引入它。

同一候选通向多个 join 时，对共享后继去重，不把“解锁多个 barrier”的计数冒充多份独立计算收益。算法只访问 DAG/state，原始训练 role 仅作离线解释。

## 3. E1：Barrier 挑战候选

单 channel 中若存在非 LT 默认通信 B，满足 last-missing 且 T_B≥0.85*T_A，则按 join residual tail、B tail 和冻结 task 顺序选唯一 B。主配置最多2个动作：默认 LT 与 B；与“LT 默认+第二名”保持相同候选预算。没有合格 B 时直接 LT。

评估用同一 LT 后续和完整 Q，严格更好才换动作。另以3候选版本比较默认、LT第二名、barrier候选，必须对照相同3候选预算的 LT 前三名，才能判断来源特征有无价值。

多资源仅在 C1 语义测试通过后扩展：将 B 作为优先种子，再按 LT 构造合法完整集合；不能将 B 与已有冲突成员直接拼接。active 通信不能移除。

## 4. E2：Barrier 触发

固定 D1 的候选与后续策略，在开发状态池比较：
- tail/duration/可靠 arrival 基础触发；
- 基础触发加 last-missing 信号；
- 匹配调用数的随机和周期触发。

在相同冻结状态池 K={8,16,32} 调用数下，以 Q_LT 条件可修复状态为诊断正标签，unknown 不当负例。比较命中数、漏检、额外特征成本。最终仍需完整在线回放判断 makespan，不以分类指标代替收益。

准入约定：validation 池相同 K 下，相对基础触发至少多命中2个条件修复状态，且额外命中涉及至少2个来源组，特征计算总耗时不超过基线调度时间10%。若来源不足，仅给机制观察，不启动推广性调参。此门槛在最终验证前冻结；诊断未通过即可结束 E2。

## 5. 反例与测试

至少固定以下测试，不预设它们必须全部修复：
1. B 解锁长关键 compute，局部修正有价值。
2. B 解锁短分支，其他独立长链决定 makespan。
3. B 本身长，占用资源使更关键通信等待。
4. 两个 last-missing 候选共享后继，重复计分会错。
5. join 还有 active compute 前驱，B 不是 last-missing。
6. join 最后前驱已经完成或同刻完成后状态变化，特征需刷新。
7. 提前一个 barrier 延后下一 barrier。
8. 多资源 barrier 高分候选互相冲突或被 active reservation 阻挡。

对可解小图用 Exact 核对最终目标；同时记录 barrier ready/complete 时间，展示它们与 makespan 的一致及不一致。有 barrier 改善但无 makespan 改善应明确标记。

## 6. 复用、产物与结论

审查复用 src/llm_structured/nonpreemptive/barrier/ 的 graph、features、counterfactual、policies。不要根据旧实现存在就跳过准入；旧 barrier-only 只保留为失败诊断基线。

交付 feature_definition.md、diagnostic_labels.jsonl、candidate_ablation.jsonl、trigger_ablation.jsonl、counterexamples/ 和 result.md。候选贡献、触发贡献及 rollout 本身贡献分开。

结论分为：值得作为 LT 候选辅助、仅适合作低成本 tie-break/触发、没有额外价值、证据不足。没有额外价值也是完成该方向的有效结果，不要求进入综合。
