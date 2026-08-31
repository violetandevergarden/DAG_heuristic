# Stage 4d 不可抢占 Selective Rollout 算法探索结果

日期：2026-08-31

## 1. 输入、切分与预算

旧不可抢占 benchmark 共 75 个，按 family、模板和反例机制分组后冻结为：development 48、validation 20、holdout 7；清单 hash 为 `0c39ccc50443c79a6d51a9b3f2d9d60f06ac944af83e17c861a074ae37a1fc97`。

Stage 4a 的 30 个真实小图全部作为 `real_small_external`，不参与阈值更新；8 个中图全部作为 `real_medium_cost`。optional-idle 与 work-conserving 始终分开运行。

小图端到端配置为 B0--B6：LT、full width 2 depth 1、selective width 2 depth 1、随机、周期、selective width 4 depth 1、selective width 2 depth 2。每行 15 秒硬预算。旧标签每 case×mode 10 秒、5 万状态；真实小图标签每 case×mode 30 秒、10 万状态。

## 2. 决策级 Exact 标签

旧图共记录 597 个有选择状态：

| 口径 | known | unknown | LT 严格错误 | 总 regret | 最大 regret |
| --- | ---: | ---: | ---: | ---: | ---: |
| optional-idle | 331 | 72 | 44 | 79 | 7 |
| work-conserving | 192 | 2 | 21 | 39 | 7 |

unknown 保留在结果中，没有并入负例。旧反例证明完整动作 rollout 有能力修复 LT，但 optional-idle 的 unknown 比例较高，不能据此估计总体命中率。

真实小图共记录 243 个有选择状态，全部得到 optimal 标签：optional-idle 162 个，work-conserving 81 个。两种口径下 LT 严格错误均为 0。这意味着沿冻结 LT 可达路径，真实小图没有可由首动作 rollout 修复的 LT regret。

## 3. 旧图端到端探索

1050/1050 行 completed，无 timeout、failed 或最坏退化。相对 B0 LT：

| 配置 | 严格改善 case×mode | 净减少 tick | completion calls |
| --- | ---: | ---: | ---: |
| B1 full w2 d1 | 50 | 111 | 1134 |
| B2 selective w2 d1 | 50 | 111 | 1134 |
| B3 random w2 d1 | 35 | 68 | 645 |
| B4 periodic w2 d1 | 34 | 82 | 346 |
| B5 selective w4 d1 | 50 | 116 | 1515 |
| B6 selective w2 d2 | 51 | 121 | 1909 |

观察：

1. full、加宽和 depth 2 能在旧反例上修复 LT，且没有端到端退化；
2. depth 2 比 depth 1 多净减少 10 tick，但增加 775 次 completion call，单位成本收益很低；
3. 周期触发仅用 346 次调用得到净 82 tick，比当前 selective 更接近成本控制目标；
4. 当前 selective 与 full 的触发及调用完全相同，说明组合规则没有筛掉便宜但无价值的选择状态，H1/H2 的当前实现未形成有效筛选；
5. B5/B6 的确实际评价了更多候选或达到更深层，但额外收益很小，因此 H5 只在旧图上得到弱支持。

## 4. 真实小图冻结验证

420/420 行 completed。所有 B1--B6 在 30 个真实小图、两种动作口径上的 makespan 均与 B0 LT 相同，严格改善 0、退化 0。

成本却真实增加：

| 配置 | completion calls | 子进程墙钟合计（秒） |
| --- | ---: | ---: |
| B0 LT | 0 | 12.61 |
| B1 full | 486 | 14.06 |
| B2 selective | 486 | 14.13 |
| B3 random | 280 | 13.74 |
| B4 periodic | 78 | 13.04 |
| B5 width 4 | 494 | 14.16 |
| B6 depth 2 | 731 | 15.13 |

真实 Exact 标签与端到端结果一致：LT 已经最优，rollout 没有修复空间。真实结果没有用于返调阈值。按 GPT-13B、Mixtral 和 multi-job 来源分组也没有任何 makespan 差异，因此不做伪独立显著性解释。

## 5. 中图预算边界

中图只带 B0 和 B2。严格先运行两个最小单通道 pilot，单行硬预算 30 秒；配置在 pilot 超时后，其余行均写 `not_run_budget_gate`。

结果共 32 行：

- 8 行 timeout：B0/B2 × optional/work-conserving 的 pilot；
- 24 行 `not_run_budget_gate`；
- completed 0 行。

即使纯 LT 也没有通过本阶段 30 秒 pilot，selective rollout 更无成本可行性。没有提高预算、没有重跑超时，也没有排除失败后计算平均收益。该结果与 Stage 4a 曾在负载较低环境下完成中图基线不矛盾：本阶段采用的是预先声明的独立进程 pilot 闸门，回答的是当前固定预算下能否开展 rollout 对照。

## 6. 假设判断与失败案例

- H1：当前组合触发器不成立。selective 与 full 调用量相同。
- H2：跨事件信号在旧反例上常触发，但没有在真实小图上提供额外区分，证据不足。
- H3：冻结 WAIT 规则已经修复真实 multi-job 小图中的等待机会；rollout 没有进一步收益。
- H4：正式真实小图中固定多资源样本很少，且无 LT regret，证据不足。
- H5：旧图加宽/加深确有少量额外收益，但成本明显上升；真实小图收益为零，中图无法通过闸门，未迁移。
- H6：成立于当前 Stage 4a 小图。LT 已达到 Exact，rollout 只能增加分析成本。

最重要的失败案例是初版遗漏冻结 WAIT 规则后，在 `np_multi_job_heterogeneous_staggered` 上得到 829 tick 伪收益。修正基线后该收益消失。这不是算法改善，而是基线口径错误。

## 7. 阶段结论

Selective rollout 在旧受控反例上有修复能力，但当前透明触发器没有比 full 节省调用；加宽和加深的少量收益不足以抵消额外成本。冻结配置在 30 个真实小图上没有任何 makespan 收益，且真实小图 LT 已由决策级 Exact 验证为最优。中图连 B0 的 30 秒 pilot 都未通过。

因此，本阶段结论是：**不把当前 selective rollout 作为真实 Stage 4 默认调度算法，保留为小图离线反事实分析工具和未来触发器研究基础。** 若未来 Stage 4c 或 4f 提供了新的真实候选分歧或多 job 目标，应重新建立独立标签和预算证据，不能沿用本阶段阈值宣称迁移。

结果目录：

- `stage4d_labels_20260831/`
- `stage4d_old_benchmark_exploration_20260831/`
- `stage4d_real_small_validation_20260831/`
- `stage4d_real_medium_cost_20260831/`
