# Stage 4e 不可抢占 Barrier 感知调度算法探索结果

日期：2026-09-01

## 实验口径

方法：B0 residual LT、B1 barrier-only、B2 last-missing 真并列修正、B3 10% tail margin、B5 一步完整动作反事实。所有方法分别运行 optional-idle 和 work-conserving。

数据分三组：

1. Stage 1--3 固定多资源受控图：manifest 共 19 个条目，其中 17 个小图完成，2 个 routed medium 在 5 秒硬预算下对所有方法超时；
2. Stage 4a 真实小图：30 个 real-derived/real-composed 图，均有两种 mode 的 Exact 最优证书；
3. Stage 4a 中图 pilot：严格只选计划指定的 640-task 和 838-task 单 channel 图，每个方法、mode 使用 30 秒外部硬预算。

结果文件：

- `stage4e_old_benchmarks_20260901/results.jsonl`：190 行；
- `stage4e_real_small_validation_20260901/results.jsonl`：300 行；
- `stage4e_real_medium_cost_20260901/results.jsonl`：16 行。

## Stage 1--3 受控结果

在 17 个完成的小图上，相对 B0：

| mode | 方法 | 改善/相同/退化 | makespan 差值合计 | 最好/最坏差值 |
| --- | --- | ---: | ---: | ---: |
| optional-idle | B1 barrier-only | 6/2/9 | +5 | -9 / +6 |
| optional-idle | B2 tie-break | 0/16/1 | +2 | 0 / +2 |
| optional-idle | B3 margin | 6/11/0 | -30 | -10 / 0 |
| optional-idle | B5 counterfactual | 7/10/0 | -33 | -10 / 0 |
| work-conserving | B1 barrier-only | 0/9/8 | +14 | 0 / +4 |
| work-conserving | B2/B3/B5 | 0/17/0 | 0 | 0 / 0 |

这说明受控 optional-idle 图中存在 barrier challenger 可修复 LT 的机制，但 direct last-missing 真并列并不安全：B2 仍有一个 +2 退化。B5 用 32 次 optional-idle completion call 获得 7 个图改善；B3 不用 completion call 获得 6 个图改善。该结果只能解释旧图机制。

## Stage 4a 真实小图冻结验证

B0 在 30 个真实小图上对两种 mode 都是 30/30 Exact 最优，总 gap 和最大 gap 都为 0。因此在线 barrier 修正没有真实可改善空间：

- B2、B3、B5 都是 30/30 与 B0 相同，仍为 30/30 Exact 最优；
- B5 两种 mode 各调用 34 次 completion，却没有产生一次最终改选；
- B1 各有 15/30 退化，optional-idle 总退化 11408 tick，work-conserving 总退化 10579 tick，最坏均为 +1678 tick。

这直接否定了“用 barrier 替代 LT”。旧图上 B3/B5 的改善没有迁移到当前真实小图；原因不是候选算法失败，而是这批真实小图的 LT 已无 regret。当前证据不能判断 barrier 在更困难的真实小图上是否有效，因为 Stage 4a 尚无这种有 Exact 且 LT 非最优的样本。

## Stage 4a 中图超时观察

640-task 与 838-task pilot 共 16 行（B0/B2/B3/B5 × 两种 mode × 两图），全部在 30 秒外部进程上限超时，完成率 0/16。timeout 全部保留在分母中，没有提高预算或重跑。

由于 B0 也全部超时，当前中图结果首先说明不可抢占 Python 完整回放/动态 LT 的成本瓶颈，而不能单独归因于 barrier 特征。按照实施计划的中图门槛，本轮不扩展到其余 6 个中图，也不运行 2038-task 的两个真实固定多资源图。

## 结论

本轮得到受限/否定结论：

- barrier-only 不可作为主策略；真实小图给出强负面对照。
- 10% margin 和一步反事实在 Stage 1--3 optional-idle 受控图中能修复 LT，且本轮未退化；但未迁移到 Stage 4a 真实小图，因为后者 LT 已全部最优。
- B2 真并列规则并非理论安全规则，在旧图中仍出现一次退化，不应仅凭 tie-break 名称进入综合算法。
- B5 在真实小图增加 completion 成本却没有收益，不值得作为默认在线方法。
- 中图 0/16 完成，当前不能形成真实中图收益结论。应先优化并验证公共 LT 回放成本，再考虑复杂 barrier 方法。

因此 Stage 4e 当前只保留 barrier 结构与特征作为诊断工具或未来 selective rollout 的候选触发信号，不进入默认综合调度算法。若继续研究，准入条件应是新增真实来源、存在 LT regret 且 Exact 可完成的小图，或者中图 B0 能在固定预算内稳定完成；在此之前不扩展权重、margin 网格或更深反事实。

## 尚未满足的证据项

- 没有新的 100--1000 task 受控压力图；中图 pilot 已直接暴露更优先的完整回放成本问题。
- 没有真实多资源中图质量结果，原因是前置单 channel pilot 门槛失败。
- 没有 barrier-triggered rollout 的公平调用率对照；真实小图无 regret，中图不可运行，现阶段无法提供有意义的增量收益证据。
- Stage 4a 当前真实小图不能检验“barrier 修复真实 LT 错误”，该问题保持未知，不写成 barrier 永久无效。
