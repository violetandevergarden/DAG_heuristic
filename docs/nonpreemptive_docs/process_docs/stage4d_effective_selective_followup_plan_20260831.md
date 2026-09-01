# Stage 4d 不可抢占有效 Selective Rollout 续研方案

日期：2026-08-31

依据：

- `docs/nonpreemptive_docs/plan_docs/stage4_LLM_search.md`
- `docs/nonpreemptive_docs/plan_docs/stage4d_selective_rollout.md`
- `docs/nonpreemptive_docs/process_docs/stage4d_selective_rollout_implementation_and_exploration_plan_20260831.md`
- `docs/nonpreemptive_docs/result_docs/stage4d_algorithm_exploration_20260831.md`

状态：待实施

## 1. 研究目标

本轮只回答一个问题：在不可抢占完整通信语义下，能否构造一个真正有效的 selective 触发器，在旧构造 benchmark 上明显少于 full rollout 的调用成本，同时保留大部分可取得收益，并优于随机和周期触发。

“有效”不能只表示某些图上 makespan 下降。必须同时满足：

1. selective 的触发次数和 completion calls 严格少于 full；
2. 在冻结 holdout 上保留 full rollout 的主要净收益；
3. 单位额外调用和单位墙钟收益优于随机、周期对照；
4. 不依赖事后与完整 LT 取较小值，不隐藏最坏退化；
5. optional-idle 与 work-conserving 分开选择阈值、运行和报告；
6. 所有动作仍通过不可抢占公共模拟器执行完整通信、完整启动集合或合法 WAIT。

本轮先使用既有 75 个不可抢占 benchmark。Stage 4a 的 30 个真实小图不参与触发器设计和阈值选择；只有旧图证明存在有效 selective 后，才决定是否重新设计真实 hard-decision 小图并做外部验证。

## 2. 当前问题与基线

现有旧图 Exact 标签包含 597 个有选择状态：

| 口径 | known | unknown | LT 严格错误 | 总 LT regret |
| --- | ---: | ---: | ---: | ---: |
| optional-idle | 331 | 72 | 44 | 79 |
| work-conserving | 192 | 2 | 21 | 39 |

端到端结果中，full width 2 depth 1 使用 1134 次 completion call，净减少 111 tick；周期触发只使用 346 次调用，净减少 82 tick。当前 selective 也使用 1134 次调用、净减少 111 tick，与 full 完全相同。

原因不是 selective 理论上一定无效，而是现有 `heuristic_disagreement` 实际检查“候选列表中是否存在不同动作”。候选已经去重，因此只要有两个候选，该条件通常成立，组合触发器便退化为 `choice_only/full`。

本轮必须先修正触发特征定义，再讨论阈值和组合。旧结果继续保留为失败消融，不覆盖、不删除。

## 3. 固定不变的实验条件

### 3.1 输入与切分

继续使用已经冻结的旧图 manifest：

```text
experiments/llm_structure/nonpreemptive/manifests/stage4d/old_benchmarks.jsonl
```

切分保持不变：development 48、validation 20、holdout 7，manifest hash 保持为：

```text
0c39ccc50443c79a6d51a9b3f2d9d60f06ac944af83e17c861a074ae37a1fc97
```

不得根据本轮收益移动 benchmark、模板组或 unknown 状态。development 用于观察和选择阈值；validation 只用于选择少量组合；holdout 只运行冻结配置一次。

### 3.2 基础算法与预算

- 基础动作和 completion policy 固定为已经与 Stage 4a 76/76 makespan、trace hash 对拍一致的 residual LT；
- 第一轮固定 `width=2, depth=1`，先研究是否触发，不把加宽或加深混入触发器判断；
- 每行端到端硬预算仍为 15 秒；
- 每个候选必须完整评价，预算不足时当前决策回退 LT；
- 不开启事后 baseline safeguard；
- completion calls、feature transitions、展开状态、缓存和墙钟均按实际值记录；
- 随机触发固定 seed，周期触发的调用量尽量匹配 selective。

### 3.3 标签使用

只用 status 为 `optimal` 的决策标签计算 precision、recall 和 regret；unknown 单独报告，不作为负例。主要正例定义为：

```text
rollout_beneficial = 非 LT 合法首动作的最优 cost-to-go 严格小于 LT
```

并列最优不作为“必须触发”的正例，但触发后的并列改动作计为无质量收益成本。

## 4. 先修正特征合同

### 4.1 真实策略分歧

每个便宜策略必须独立在完整合法动作空间中产生一个首选动作，再比较动作摘要：

- residual LT；
- FIFO；
- 输入固定顺序；
- SPT；
- LPT；
- 单通道 release-fit；
- 多资源热点/瓶颈贪心集合。

定义：

```text
true_policy_disagreement = 至少一个便宜策略的首选动作与 LT 不同
```

不能再用“最终候选中存在两个动作”代替策略分歧。每条决策记录保存 `policy_name -> ActionSignature`，便于人工复核。

### 4.2 小 LT 分差

LT 分差只比较可启动通信的 residual downstream tail，不把 WAIT 的空动作 tail 当作第二名。至少记录：

```text
absolute_margin = LT_tail - second_tail
normalized_margin = absolute_margin / max(1, LT_tail)
```

多资源集合不能只用集合内 tail 求和。第一轮分别记录求和、最大值和去重下游覆盖值，不提前认定其中一个正确。

### 4.3 关键跨事件风险

现有“transition 中事件数大于 1”过宽。新定义必须同时满足：

1. 候选完整占用区间跨过一个真实 compute、job arrival 或其他 active task 完成事件；
2. 该事件会释放新的 communication，或减少 join/barrier 的最后缺口；
3. 新释放工作与当前候选竞争相同 channel 或固定资源；
4. 新释放工作的 residual tail 高于预设阈值，或明显高于当前候选完成后的替代工作。

记录 `next_event_distance`、`candidate_duration`、释放任务、资源交集和 release tail。普通且不改变通信候选的 compute 完成不计为关键跨事件。

### 4.4 释放收益差异

对 LT 和 challenger 各执行一个完整合法 transition，比较：

- 新增 ready communication 数；
- 新增 ready communication 的最大 residual tail；
- 新启动 compute 的最大下游 tail；
- join/barrier 最后缺口是否关闭；
- 到下一有选择状态的时间；
- 多资源中释放或继续占用的热点资源。

该操作属于 feature lookahead，必须计入 `feature_transitions`，并把 transition 结果复用于 evaluator，不能重复执行后再把特征成本记为零。

### 4.5 WAIT 专属特征

WAIT 不与普通 FLOW/START 共用一个宽松触发条件。optional-idle 下定义：

```text
wait_candidate_exists
AND next_event_distance < selected_action_blocking_duration
AND next_event_releases_competing_communication
AND released_tail_advantage >= threshold
```

记录等待比例：

```text
wait_ratio = next_event_distance / max(1, selected_action_blocking_duration)
```

work-conserving 不计算 WAIT 触发，也不把 forced idle 当作 WAIT 正例。

### 4.6 多资源脚印差异

固定多资源比较 LT 集合与 challenger 集合的：

- 资源集合对称差；
- 热点资源连续占用时间；
- 被阻挡的未来高-tail 通信数量；
- active reservation 后仍空闲的资源数；
- 启动集合大小和是否极大。

active communication 只能作为上下文，不能进入 challenger 或被下一层移除。

## 5. 候选召回先于触发器研究

触发器无法修复候选集合中不存在的最优动作。本轮先在 development 的 known 标签上重新计算宽度 1、2、4 和全部合法动作的候选召回率。

分别报告：

- 普通最优动作召回率；
- 按 LT regret 加权的召回率；
- optional-idle 中 WAIT 最优动作召回率；
- 单通道和多资源召回率；
- 每增加一个候选带来的额外 completion calls；
- 候选遗漏的 benchmark、状态和动作来源。

若 width 2 的 regret 加权召回低于 80%，先修正候选源，不研究 selective 阈值。若 width 4 仍无法覆盖主要 regret，记录候选瓶颈，不允许把漏掉的正例归因于触发器。

## 6. 单特征研究

在 development 上分别评价以下触发器，不做组合：

1. `true_policy_disagreement`；
2. `small_lt_margin`；
3. `critical_release_crossed`；
4. `release_gain_spread`；
5. `duration_spread`；
6. `wait_opportunity`；
7. `resource_conflict_spread`。

每个单特征至少报告：

- 已知标签中的触发数；
- trigger precision、recall；
- LT regret 加权 recall；
- 漏掉的总 regret 和最大 regret；
- 无收益触发数和并列最优触发数；
- feature transitions、completion calls 和墙钟；
- 按 family、optional/work-conserving、单/多资源分组的结果。

阈值只在 development 的小网格中选择。例如：

```text
normalized_margin ∈ {0.05, 0.10, 0.20, 0.40}
wait_ratio ∈ {0.10, 0.25, 0.50}
released_tail_advantage_ratio ∈ {0.05, 0.15, 0.30}
duration_spread_ratio ∈ {0.25, 0.50, 0.75}
```

不连续微调小数阈值，不为单个反例增加专属条件。development 中只出现一次的信号即使命中也不能单独成为主触发器。

## 7. 严格组合触发器

第一候选组合采用三层门控，而不是宽松 OR：

```text
choice_exists
AND true_policy_disagreement
AND (
    (small_lt_margin AND critical_release_crossed)
    OR release_gain_spread
    OR wait_opportunity
    OR resource_conflict_spread
)
AND budget_available
```

另保留两个消融：

```text
C1 = choice_exists AND true_policy_disagreement
C2 = choice_exists AND (small_lt_margin OR true_policy_disagreement)
```

C1 用于测量真实策略分歧本身；C2 用于说明宽松 OR 是否再次退化为 full；严格组合记为 C3。

组合选择规则：

1. development 上先淘汰 completion calls 不低于 full 80% 的组合；
2. 剩余组合进入 validation；
3. validation 上优先最大化 regret 加权 recall，同时限制无收益触发；
4. 只冻结一个主配置，最多再保留一个偏保守配置；
5. holdout 前锁定阈值、候选顺序、tie-break、seed 和预算 hash。

不训练黑盒分类器。只有透明规则在 development/validation 上存在稳定但难以手写的分界，并且样本数量足够时，才另写计划研究浅层决策树。

## 8. 公平对照

冻结配置后，在旧 holdout 比较：

- H0：纯 LT；
- H1：full width 2 depth 1；
- H2：旧失败 selective；
- H3：新 strict selective；
- H4：匹配新 selective completion calls 的随机触发；
- H5：匹配新 selective completion calls 的周期触发；
- H6：只用 `true_policy_disagreement`；
- H7：离线 Exact-trigger 上限，只在已知正例触发，用作不可部署上界。

随机和周期不是简单复用旧调用率，而是在每个 mode 或 case 分组内尽量匹配新 selective 的实际 completion calls。若无法精确匹配，报告差值，不声称完全等预算。

## 9. 有效性判定

### 9.1 主要判定

一个 selective 配置只有同时满足以下条件，才称为“旧构造 benchmark 上有效”：

1. holdout completion calls 不超过 full 的 60%；
2. holdout 保留 full 净 makespan 收益的至少 80%；
3. regret 加权 recall 不低于 80%；
4. 单位 completion call 收益严格优于匹配随机和周期；
5. 没有超过 full 最坏退化的案例；
6. optional-idle 和 work-conserving 至少分别给出结论，不用一方收益掩盖另一方失败；
7. completed、fallback、timeout 和 unknown 均进入分母。

由于 holdout 只有 7 个 benchmark，以上比例只作工程筛选线，不作统计显著性结论。必须同时逐例报告，避免一个高 regret 反例主导总和。

### 9.2 次要判定

若主要判定未满足，但 selective 相对 full 在 makespan 完全相同时显著减少调用，可将其定位为 full rollout 的成本控制器。若连周期触发都无法稳定超过，则形成否定结论，不继续增加特征和阈值。

### 9.3 单位成本

至少计算：

```text
相对 LT 减少的 makespan / 额外 completion call
相对 LT 减少的 makespan / feature transition
相对 LT 减少的 makespan / 额外墙钟秒
保留的 full 收益 / full completion calls 的减少比例
```

feature lookahead 和 rollout completion 必须分别计数，防止把昂贵特征伪装成廉价 selective。

## 10. 具体实验轮次

### S1：修复与对拍

- 修正真实策略分歧和关键跨事件定义；
- 保存各便宜策略的首动作；
- feature transition 与 evaluator 复用；
- 重跑 Stage 4a 76 条 LT 对拍，要求 makespan 和 trace hash 仍为 76/76；
- 添加触发特征专项测试。

通过条件：修复前 selective≈full 的原因能够由测试稳定复现，修复后不再因为“候选不同”自动触发。

### S2：候选召回曲线

- 只使用 development known 标签；
- 比较 width 1/2/4/全部合法；
- 分离候选遗漏与触发遗漏。

通过条件：冻结最小可接受候选宽度，或明确候选召回本身不足。

### S3：单特征扫描

- 分别运行七类单特征；
- 记录普通 recall、regret 加权 recall 和成本；
- optional、work-conserving、单通道、多资源分表。

通过条件：至少一个信号在 development 和 validation 方向一致；否则停止组合研究并形成否定结论。

### S4：组合与 validation

- 比较 C1、C2、C3；
- 只保留一个主配置和一个保守配置；
- 冻结全部 hash。

通过条件：至少一个组合相对 full 减少 40% 调用，同时保留 70% 以上 validation 净收益。该条件低于最终 holdout 标准，只用于是否值得进入 holdout。

### S5：旧 holdout 一次性验证

- 运行 H0--H7；
- 匹配随机和周期调用量；
- 报告逐例结果、完整率和最坏退化；
- 不根据 holdout 修改任何阈值。

通过条件：按第 9.1 节判定有效、受限或否定。

### S6：决定是否构建真实 hard-decision 集

只有旧 holdout 证明 selective 有效，才进入下一步：从较大真实 DAG 的实际决策状态抽取保留 join、barrier、未来 release 和资源热点上下文的 `real_hard_decision` 小图。当前 30 个真实小图继续作为 `real_control`，不删除、不重新命名为失败样例。

若旧 holdout 不通过，本轮在 S5 结束，不通过扩大真实切片或增加复杂特征寻找收益。

## 11. 测试要求

新增或修正测试至少覆盖：

- 两个候选不同但各便宜策略首选相同时，`true_policy_disagreement=False`；
- FIFO、LT、SPT 首选不同时，准确记录策略到动作映射；
- 普通 compute 完成但不释放竞争通信时，不触发关键跨事件；
- 跨事件释放高-tail 同资源通信时触发；
- WAIT 只在 optional-idle 且存在真实下一事件时参与；
- work-conserving 不生成 WAIT 特征；
- 多资源 active reservation 始终保留；
- feature transition 被 evaluator 复用且只计一次；
- unknown 不进入负例；
- 随机/周期调用匹配可复现；
- 冻结 holdout 配置 hash 不可在运行中改变；
- completed trace 可独立回放。

只修改 Stage 4d 特征和触发器时，至少运行不可抢占定向回归、Stage 4a 集成测试和全部 Stage 4d 测试。若修改公共模拟器、Exact、loader 或 schema，则运行完整测试。

## 12. 结果归档

建议新增：

```text
docs/nonpreemptive_docs/result_docs/
├── stage4d_effective_selective_features_<date>/
├── stage4d_effective_selective_candidates_<date>/
├── stage4d_effective_selective_validation_<date>/
└── stage4d_effective_selective_holdout_<date>/
```

每个目录保存输入 manifest、配置及 hash、特征 schema、逐决策结果、逐样例结果、summary、unknown/timeout/fallback 清单和 trace hash。修复前旧 selective 标记为 `legacy_failed_trigger_v1`，不得与新触发器混表。

## 13. 停止条件与最终去向

出现以下任一情况即停止扩展：

1. 修正后的单特征在 development 和 validation 方向不一致；
2. width 4 仍无法召回主要 regret，且继续枚举成本明显增长；
3. 新 selective completion calls 超过 full 的 80%；
4. 新 selective 不优于匹配周期触发；
5. 收益只来自一个模板或一个高 regret 反例；
6. 特征 lookahead 成本接近直接 rollout；
7. holdout 未达到第 9.1 节标准。

最终只允许四种定位：

- **有效调度候选**：达到主要判定，允许进入真实 hard-decision 外部验证；
- **成本控制器**：质量与 full 接近，显著减少调用，但没有独立 makespan 增益；
- **离线分析工具**：只适合小图反事实和错误归因；
- **否定结论**：透明 selective 不优于周期/随机或成本不值得。

代码能够运行、旧 development 上存在收益或某个反例被修复，都不能单独作为继续进入真实图或未来综合算法的理由。
