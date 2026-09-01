# Stage 4c 不可抢占冲突图与启动集合：算法探索结果

## 1. 输入、口径和预算

主要实验使用 `benchmark/muti_channel/nonpreemptive/` 的 17 个 Stage 1–3 固定多资源 benchmark：4 个 adversarial、10 个 random、3 个手工 route 快照。optional-idle 与 work-conserving 分开运行。

辅助实验使用 Stage 4a 的两个 2038-task routed 中图，分别对应 Alibaba HPN 16G 和 Cassini 24G。它们只用于完整率和成本闸门，不参与阈值或规则选择。

小图每个 Exact 和完整策略使用 3 秒外部硬超时；routed 中图使用计划规定的 30 秒 pilot。中图只有 LT 在同预算内完成才运行 P1/P3/P4，否则记为 `not_run_budget_gate`。实验原始结果位于：

- `docs/nonpreemptive_docs/result_docs/stage4c_experiments_20260831/results.json`；
- `docs/nonpreemptive_docs/result_docs/stage4c_routed_medium_cost_20260831/results.json`；
- `experiments/llm_structure/nonpreemptive/manifests/stage4c/manifest.jsonl`。

## 2. 冲突观察

在 17 个旧图的 LT 完整路径上：

- 13/17 至少观察到一次多个 startable communication；
- 最大同时 startable 数为 4；
- 只有 `muti_random_007` 在 LT 路径上观察到 active reservation 存在时仍有多个 startable communication；
- 其余路径上的 active-aware 分支很少，说明旧图可以验证语义和小图选择，但 active reservation 下复杂 packing 的统计覆盖有限。

这些都是 `observed_on_LT_path`，不是对全部可达状态的无选择证明。

## 3. Exact 与最终 makespan

### 3.1 Work-conserving

17/17 个 Exact 均在预算内完成：

| 方法 | 完成数 | 达到 Exact | 总 gap | 最大 gap |
|---|---:|---:|---:|---:|
| 固定顺序 | 17 | 17 | 0 | 0 |
| FIFO | 17 | 16 | 5 | 5 |
| residual LT | 17 | 17 | 0 | 0 |
| P1 多起点 | 17 | 17 | 0 | 0 |
| P2 一换一 | 17 | 17 | 0 | 0 |
| P2 一换二 | 17 | 17 | 0 | 0 |
| P3 整集合评分 | 17 | 17 | 0 | 0 |
| P4 完整动作反事实 | 17 | 17 | 0 | 0 |

在这组 benchmark 上，多起点、交换和集合评分没有超过 LT；一换二相对一换一没有新增最终收益，因此没有继续扩大交换邻域。

### 3.2 Optional-idle

15/17 个 Exact 在 3 秒内完成；`muti_random_003` 和 `muti_random_008` 为 timeout，保留为 unknown。只对 15 个有最优证书的样例统计：

| 方法 | 达到 Exact | 总 gap | 最大 gap | 平均运行时间 |
|---|---:|---:|---:|---:|
| 固定/FIFO/LT/随机极大补全 | 13/15 | 6 | 4 | 约 4.1 ms |
| P1 多起点 | 13/15 | 7 | 5 | 约 11.9 ms |
| P2 一换一/一换二 | 13/15 | 7 | 5 | 约 12.1–12.3 ms |
| P3 整集合评分 | 13/15 | 7 | 5 | 约 12.6 ms |
| P4 完整动作反事实 | 15/15 | 0 | 0 | 约 25.6 ms |

两个有收益机制的样例是：

- `nonmaximal_start_np`：Exact 8，LT 极大补全 12；静态 P1/P2/P3 为 13，P4 为 8。收益来自非极大启动或等待，而不是更换极大集合。
- `muti_random_009`：Exact 20，LT/P1/P2/P3 为 22，P4 为 20。

因此，有限 optional-idle challenger 已覆盖这两个已知最终收益样例，但静态集合评分不能可靠选择它们；必须使用完整动作反事实才恢复收益。

## 4. 候选与成本消融

在有 Exact 的旧图上：

- P1 共构造 349 个候选，P2/P3/P4 共构造 363 个候选；
- 一换一只增加 14 个日程级候选计数，一换二没有进一步增加；
- 静态 P1/P2/P3 没有修复 LT 的 optional-idle gap，且在 `nonmaximal_start_np` 将 12 退化为 13；
- P4 使用 363 次 completion call，修复两个 LT 失败样例，但平均运行时间约为 LT 的 5–6 倍；
- work-conserving 中 P4 没有质量收益，说明这些调用在当前旧图上全部是额外成本。

共享下游并集的实现和单元测试证明不会重复计数，但当前 benchmark 没有提供“并集评分稳定优于 LT”的端到端证据。成员求和没有进入冻结候选，因为共享后继测试已直接暴露其计数合同错误。

## 5. Routed 中图成本闸门

两个 topology、两种 mode、固定/FIFO/LT 共 12 次 30 秒 pilot 全部 timeout，无 makespan。P1/P3/P4 共 12 次均记为 `not_run_budget_gate`。没有提高预算，也没有从统计中剔除失败项。

由此只能得到成本结论：在当前 Python 公共模拟器和 30 秒预算下，连简单完整回放都不能完成，Stage 4c 复杂 packing 不具备进入这两个完整 routed 图的运行前提。不能据此判断真实图上 LT 与 packing 的质量高低。

## 6. 假设判断

- H1 得到旧图支持：低规模 work-conserving 场景中 LT 已足够。
- H2 未得到支持：一换二没有超过一换一或 LT。
- H3 只完成合同验证，未获得端到端收益证据。
- H4 当前样本不足，无法从结果中分离 duration 与热点连续占用作用。
- H5 得到语义与测试支持：忽略 active reservation 会把被阻塞 ready task 错放入冲突图。
- H6 得到有限支持：optional-idle 收益集中在少量图，但需要完整反事实选择。
- H7 得到支持：复杂静态 packing 成本更高且无净收益；P4 有收益但实质上已接近 rollout。

## 7. 结论和适用边界

本轮不推荐把复杂 conflict-graph packing 注册为默认调度算法：

1. work-conserving 的 17 个旧图上 residual LT 已全部达到 Exact；
2. 多起点、一换一、一换二和静态整集合评分没有产生净收益；
3. optional-idle 的两个已知失败可由 P4 修复，但 P4 是完整动作前瞻，应归入 Stage 4d 的预算与触发研究；
4. 两个真实 routed 中图连简单策略都未通过 30 秒 pilot，真实质量仍未知。

因此 Stage 4c 的当前定位是“合法、受预算约束的候选构造与分析工具”；默认 online 行为仍应使用 residual LT 极大补全。后续若 Stage 4d 在有效 selective 触发下需要多资源首动作候选，可以复用本模块的 active-aware 图和有界候选；不应独立扩大交换邻域。

## 8. 未覆盖项

实施计划中的 100–1000 节点临时受控成本曲线和正式多资源 real-derived routed slice 本轮没有形成。原因分别是用户指定以已有 Stage 1–3 benchmark 为主，以及当前 Stage 4a 切片均未提供可直接使用的固定多资源选择证据。它们是证据缺口，不写成已完成结论；但不会改变当前“旧图上复杂 packing 无净收益、完整 routed 图 30 秒不可运行”的受限结论。

