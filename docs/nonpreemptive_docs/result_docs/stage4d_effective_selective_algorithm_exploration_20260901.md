# Stage 4d 有效 selective rollout：算法探索结果

日期：2026-09-01

## 1. 结论

本轮结论为：**透明 strict selective 在旧构造 benchmark 上不成立，应定位为否定结果；full rollout 仍只适合作为小图离线分析工具。**

optional-idle 的 C3 在 validation 达到进入 holdout 的宽松门槛，但在冻结 holdout 上没有保留 full 的收益，并且不如匹配周期触发。work-conserving 在 validation 已经失败，holdout 结果也一致。因此按计划停止，不构建真实 hard-decision 集，不继续增加特征或阈值。

## 2. S1：修复结果

旧 selective≈full 的原因被稳定复现：旧 `heuristic_disagreement` 实际检查的是去重候选是否不同，`crosses_event` 又把普通 transition 推进当作跨事件风险。修复后：

- 两个候选不同但 FIFO/LT/SPT/LPT 等首选相同时，`true_policy_disagreement=False`；
- 每条决策保存完整策略首动作映射；
- 普通推进不自动成为关键释放；
- feature lookahead transition 被 evaluator 复用并单独计费。

当前 Stage 4a real-small LT 对拍为 60/60 makespan 和 60/60 trace hash 一致。

## 3. S2：候选召回

只使用 development 的 optimal 标签：

| mode | width 1 加权召回 | width 2 加权召回 | width 4 | 全动作 |
| --- | ---: | ---: | ---: | ---: |
| optional-idle | 0% | 95.1%（39/41 regret） | 100% | 100% |
| work-conserving | 0% | 100%（28/28 regret） | 100% | 100% |

width 2 已超过 80% 门槛，且只漏掉 optional-idle 的 2 个单位 regret，因此冻结 `width=2, depth=1`。本轮失败不能归因于主要候选缺失。

## 4. S3：单特征

主要观察：

- `true_policy_disagreement` 的 development 加权召回为 optional 95.1%、work-conserving 100%，validation 两者均为 100%；但它分别触发 development 148/224 和 152/152 个 known 状态，work-conserving 完全退化为 full；
- `duration_spread` 是方向最一致的稀释信号，但 precision 低。0.25 阈值下 development 加权召回为 optional 73.2%、work-conserving 85.7%，validation 降为 38.9% 和 88.9%，不能作为跨口径稳定主触发；
- `critical_release_crossed`、`wait_opportunity` 和 `resource_conflict_spread` 太稀或没有命中主要 regret；WAIT 信号在 development/validation 均为 0；
- `release_gain_spread` 在 optional validation 有部分召回，但 work-conserving validation 为 0；
- unknown 状态没有作为负例进入 precision/recall。

因此没有一个结构信号同时在两种 mode 上稳定。后续组合只按计划验证 C1--C3，没有扩展网格或训练分类器。

## 5. S4：组合与 validation

| mode / 方法 | makespan 总和 | 相对 LT 净收益 | completion calls | full 调用占比 | full 收益保留 |
| --- | ---: | ---: | ---: | ---: | ---: |
| optional LT | 393 | 0 | 0 | 0% | — |
| optional full | 351 | 42 | 178 | 100% | 100% |
| optional C1 | 351 | 42 | 108 | 60.7% | 100% |
| optional C3 | 361 | 32 | 64 | 36.0% | 76.2% |
| WC LT | 384 | 0 | 0 | 0% | — |
| WC full | 375 | 9 | 58 | 100% | 100% |
| WC C1 | 375 | 9 | 58 | 100% | 100% |
| WC C3 | 384 | 0 | 28 | 48.3% | 0% |

optional C3 达到“减少至少 40% 调用且保留至少 70% validation 收益”的进入条件，所以冻结后进入一次 holdout。work-conserving C3 未通过，C1 又等于 full，因此该口径在 S4 即为否定。

值得注意的是，所有 v2 特征仍需要一次首层 transition：optional C3 的 validation feature transitions 为 278，略高于 full 的 275；它减少的是 completion calls，不是特征推进成本。

## 6. S5：冻结 holdout

7 个 benchmark、两种 mode 全部 completed，无 timeout/fallback。

| mode / 方法 | makespan 总和 | 相对 LT 净收益 | completion calls | feature transitions |
| --- | ---: | ---: | ---: | ---: |
| optional LT | 82 | 0 | 0 | 0 |
| optional full | 81 | 1 | 50 | 76 |
| optional 旧失败 selective | 81 | 1 | 50 | 76 |
| optional C3 strict | 82 | 0 | 6 | 77 |
| optional 匹配随机 | 82 | 0 | 12 | 77 |
| optional 匹配周期 | 81 | 1 | 12 | 76 |
| optional C1 | 81 | 1 | 24 | 76 |
| WC LT | 86 | 0 | 0 | 0 |
| WC full | 85 | 1 | 18 | 60 |
| WC C3 strict | 86 | 0 | 2 | 61 |
| WC 匹配随机 | 86 | 0 | 6 | 61 |
| WC 匹配周期 | 85 | 1 | 4 | 60 |
| WC C1 | 85 | 1 | 18 | 60 |

周期对照的调用没有与 C3 精确相等：optional 为 12 对 6，WC 为 4 对 2；即使周期使用约两倍调用，它仍以远少于 full 的成本命中唯一收益案例，而 C3 完全漏掉。不能声称 C3 优于等预算周期。

逐例看，full 和周期的全部 1 tick 收益都来自 `longest_tail_counterexample`；C3 在两个 mode 都没有触发该有效决策。没有任何方法比 LT 退化，但“无最坏退化”不能补偿零收益。

H7 仅作为离线标签上限：holdout 每种 mode 各有 2 个已知 beneficial LT-path 决策。因为首动作改变后轨迹会偏离现有标签，不能把这些标签直接拼成合法端到端 oracle；本轮没有把不可部署的事后策略伪装成 H7 调度结果。

## 7. 有效性逐项判定

| 条件 | optional C3 | work-conserving C3 |
| --- | --- | --- |
| calls ≤ full 60% | 通过（12%） | 通过（11.1%） |
| 保留 full 收益 ≥80% | 失败（0%） | 失败（0%） |
| regret 加权 recall ≥80% | 失败；漏掉 holdout 收益动作 | 失败；漏掉 holdout 收益动作 |
| 单位调用优于随机/周期 | 失败；周期有收益 | 失败；周期有收益 |
| 不超过 full 最坏退化 | 通过；均无退化 | 通过；均无退化 |
| completed/unknown 全入分母 | 通过 | 通过 |

主要判定不通过，也不能定位为成本控制器，因为 strict 与 full 的 makespan 并不相同。最终定位是**否定结论**。

## 8. 成本解释与适用范围

问题不在 width 2，而在触发信号：旧构造图的收益状态常由具体排列反例决定，关键释放、WAIT 和多资源热点等更接近真实训练结构的信号在这些图上过稀；策略分歧虽能召回，却在 work-conserving 中几乎处处成立。严格门控降低了 completion calls，却把真正收益一起筛掉。

该结论只适用于冻结的 75 个旧不可抢占 benchmark、makespan 目标、width 2/depth 1 和本轮透明特征。它不证明所有 selective rollout 都无效，也不构成真实 AICB DAG 上的结论。但依据预定停止条件，没有理由继续用扩大真实切片或增加复杂特征寻找收益。

