# Stage 4d 不可抢占 Selective Rollout 详细计划

日期：2026-08-31

对应纲领：

- `docs/nonpreemptive_docs/plan_docs/stage4_LLM_search.md`
- `docs/nonpreemptive_docs/plan_docs/stage4d_selective_rollout.md`

输入依据：`docs/nonpreemptive_docs/result_docs/stage4a_result_20260831.md`

状态：待实施

## 1. 阶段定位

本阶段研究一个受预算约束的问题：不可抢占通信启动后不能撤销，哪些启动决策值得用完整动作前瞻，以及省下的前瞻预算能否换来更宽候选或更深决策层搜索。

本计划分成两个互相独立但顺序相关的部分：

1. **代码实现**：先建立动作、候选、触发、评价、预算、回退、缓存和结果记录的可靠合同；
2. **算法探索**：再用小图 Exact 标签识别困难决策，比较全量、选择性、随机、周期和无 rollout，并在冻结配置后进入 Stage 4a 真实图。

本阶段不修改不可抢占公共语义，不自行推进时间，也不重新实现 Exact。所有候选动作和状态转移均由现有不可抢占公共模拟器给出。单 channel 首动作是一个完整通信或合法 WAIT；固定多资源首动作是保留全部 active reservation 后的新启动集合，或者 optional-idle 下合法的 WAIT/非极大集合。

## 2. 当前证据与现实边界

### 2.1 可直接使用的两批输入

当前有两批性质不同的输入：

| 输入层 | 数量与规模 | Stage 4d 用途 |
| --- | --- | --- |
| 既有不可抢占 benchmark | 75 个，3--30 个任务；58 个单 channel、17 个固定多资源；33 个已有 reference result | 开发、手算、失败模式、反例、Exact 决策标签和阈值选择 |
| Stage 4a 真实图 | 38 个；30 个 6--38 任务的 real-derived/real-composed 小图，8 个 640--2038 任务的中图 | 冻结后的真实小图验证与有限中图成本检查 |

输入顺序固定为：

1. 先在既有 75 个 benchmark 上完成语义、候选、标签、触发器和预算实验；
2. 冻结特征、阈值、候选顺序和预算后，再运行 Stage 4a 的 30 个真实小图；
3. 只有小图实现与结果合同通过后，才对 Stage 4a 的 8 个中图做有限配置检查。

不能因为 Stage 4a 是真实输入就直接在中图上调参。30 个真实小图中的相邻切片来自少数共同源 workload，不能把它们随机拆开后同时用作训练和 holdout；本计划直接把它们作为旧 benchmark 调参完成后的外部验证层。

### 2.2 Stage 4a 对 4d 的约束

Stage 4a 已知事实包括：

- 30 个小图的 optional-idle 与 work-conserving Exact 共 60 行，全部 optimal；
- Exact 状态数最大 49，适合建立首动作和逐决策标签；
- 8 个中图的三基线虽全部完成，但单行 wall-clock 最大约 46.5 秒；
- Longest Tail 相对 FIFO 的已观察最大改善约 1.23%，整体差异较小；
- 只有 3 个 case 在至少一种规则下出现两种动作口径的 makespan 差异；
- 两个正式固定多资源真实图都有 2038 个任务；
- 大图已退出正式范围，本阶段不恢复大图实验。

因此，4d 不能预设真实图上必有明显收益。若真实小图上最优首动作大多已经被 LT 命中，或中图 rollout 成本远高于可能的约 1% 收益，应形成受限或否定结论，而不是继续增加预算。

### 2.3 现有 rollout 代码的使用边界

`src/single_channel/complex_chain/nonpreemptive/solver.py` 和 `src/muti_channel/nonpreemptive/solver.py` 已有 R3 时期的 rollout 原型。它们证明了“完整动作后用同一模拟器补全”可以运行，但不等于 Stage 4d 已实现：

- 当前基本上在每个决策点运行 rollout，没有独立 selective trigger；
- 单 channel 有 depth 参数，多资源只有一层完整动作评价，深度口径不统一；
- 时间限制主要是循环内软检查，没有每决策候选、completion call 和展开状态的共享账本；
- 没有完整区分触发失败、候选遗漏和估值误判；
- 结束后用完整 baseline makespan 做保护会隐藏候选算法的真实退化，并额外使用未计入的整图信息；
- 当前结果统计不足以支持等预算的全量、随机、周期和 selective 对比。

这些原型保留为回归和对照，不直接改名为正式 Stage 4d 算法。新的实现放入语义专属模块，验证稳定后再决定是否让旧入口调用新实现。

## 3. 固定算法定义

### 3.1 基础策略

默认基础策略与 terminal completion policy 均为冻结的 residual Longest Tail：

- 单 channel：在 ready communication 中选择 residual downstream tail 最大者；
- 多资源：保留 active reservation，在空闲资源上按 residual tail 排序构造合法集合；
- optional-idle：只允许使用明确版本化的合法 WAIT 规则或候选动作；
- work-conserving：存在可启动通信时不得 WAIT，且新启动集合必须满足该模式的极大要求。

Stage 4a 的基线目前实现在实验层。4d 开始前，应把需要长期复用的 residual LT、FIFO、固定顺序和 optional WAIT 规则提取到 `src/` 的不可抢占策略层；Stage 4a runner 改成薄封装并对 228 行旧基线进行结果对拍。实验代码不得成为正式算法依赖。

### 3.2 Rollout 深度

深度统一按**通信启动决策层**计数，不按 tick、任务数或内部完成事件计数：

- depth 0：不进行 rollout，直接执行基础动作；
- depth 1：对每个候选执行一个完整首动作，再用 frozen LT 补全到结束；
- depth 2：执行完整首动作后，在下一个具有可选择动作的状态再次分支，然后用 frozen LT 补全；
- 更深配置只在小图上探索，除非 depth 2 已显示稳定且可负担的增量收益。

执行完整通信时，其中发生的 compute 完成只更新等待候选，不能形成可切换点。多资源一次 `START(set)` 后，模拟器推进到下一个真实完成事件；仍在运行的通信继续保留，不因进入下一层而变成候选。

terminal completion 不计入搜索深度，但每次完整补全计为一次 completion call，其内部状态转移计入展开量。

这里的“完整动作”按资源模型解释：单 channel 的 `FLOW(i)` 连续执行到该通信完成；多资源的 `START(set)` 是一次不可撤销的完整启动决定，模拟器推进到下一真实事件，集合中尚未完成的通信继续 active 并保留资源。多资源 rollout 不等待整个集合全部完成后才允许下一层，也不能在下一层移除其中仍 active 的通信。

### 3.3 全量与选择性

- **无 rollout**：所有状态直接执行 LT；
- **全量 rollout**：每个存在非平凡合法选择的状态都尝试 rollout；
- **selective rollout**：只有触发器通过且预算预留成功时才评价候选；
- **随机触发**：在同一 case 上匹配 selective 的触发次数或 completion calls，使用固定 seed；
- **周期触发**：按固定决策间隔触发，并尽量匹配调用预算；
- **choice-only**：只判断动作数大于一，不使用结构特征，是全量触发的便宜实现对照。

“合法动作文本不同”不自动表示选择有价值。若不同动作执行后 residual state 经独立证明等价，应标记 equivalent，不计为应触发的正例。

### 3.4 安全回退

触发器未触发、预算不足、候选生成截断、任一候选估值未完成或缓存校验失败时，执行当前状态下的 frozen LT 动作，并记录具体原因。

回退只保证“从当前状态开始的后缀等于基础策略”，不能声称整条 trace 等于纯 LT，因为之前的 rollout 决策可能已经改变状态。

正式主结果不使用“整图跑完候选后再与纯 LT 取较小值”的事后保护。该保护如果保留，只能作为离线 oracle-safeguard 消融，必须计入额外完整基线成本，不能作为可部署算法结果。

## 4. 代码实现计划

### 4.1 模块布局

建议新增以下语义专属模块：

```text
src/llm_structured/nonpreemptive/selective_rollout/
├── contracts.py       # 配置、动作摘要、触发结果、评价结果、预算统计
├── adapters.py        # 单 channel/多资源公共模拟器适配，不拥有状态转移
├── baseline.py        # FIFO、固定顺序、residual LT 和冻结 WAIT 规则
├── features.py        # 只从当前 residual state 计算触发特征
├── candidates.py      # 稳定、去重、有界的合法完整动作列表
├── evaluator.py       # depth、completion、缓存和预算控制
├── triggers.py        # 单特征与组合触发器
└── policy.py          # 端到端 selective rollout 调度器

experiments/llm_structure/nonpreemptive/
├── stage4d_labels.py
├── stage4d_decision_analysis.py
├── stage4d_evaluate.py
├── stage4d_medium_check.py
└── manifests/stage4d/
```

不要让 `src/` 导入实验模块。也不直接复用 `src/llm_structured/selective_rollout.py` 中带有可抢占状态含义的触发字段；其中确实中立的预算数据结构可以抽取为共享基础，但不得顺手改变可抢占 Stage 4d 行为。

### 4.2 统一动作摘要

为两类资源模型定义稳定 `ActionSignature`：

- 单 channel：`FLOW(task_id)` 或 `WAIT(next_event_time)`；
- 多资源：按 task ID 排序的 `START(task_ids...)` 或 `WAIT(next_event_time)`。

动作摘要只用于日志、去重和 tie-break。合法性仍由模拟器检查，不能根据字符串自行判断。每次记录 active communication、occupied/free resources 和 action mode，保证回放时能发现错误移除 reservation。

### 4.3 候选生成器

候选生成与触发器分离。无论哪个候选源被启用，列表都必须：稳定排序、去重、包含 LT baseline、受 `max_candidates` 限制，并保存截断前动作数、候选来源和截断原因。

单 channel 首轮候选源：

- residual LT；
- FIFO；
- 输入固定顺序；
- SPT/LPT；
- 能在下一个真实事件前完成或最少越过该事件的 release-fit；
- optional-idle 下的合法 WAIT。

多资源首轮候选源：

- residual LT 贪心集合；
- FIFO 贪心集合；
- 固定顺序集合；
- SPT 集合；
- 资源热点/瓶颈优先集合；
- 小图上公共模拟器枚举的合法集合；
- optional-idle 下合法 WAIT 和有限个非极大集合。

多资源候选必须保留 active reservation。work-conserving 只保留在剩余空闲资源上合法且极大的新启动集合。Stage 4c 将来若输出经过验证的集合构造器，只通过候选接口接入；4d 不预设 4c 已有正面结论。

候选宽度定义为最终实际评价的不同动作数：`max_candidates=0` 关闭 rollout，`1` 只有 LT，`2+` 才可能评价 challenger。不能把候选源数量或截断前动作数冒充宽度。

### 4.4 触发特征

所有特征绑定当前 residual state 和被比较的完整动作。第一轮只使用可解释、计算便宜的信号：

1. **LT 分差**：LT 与第二候选的 residual tail 绝对差和归一化差；
2. **便宜策略分歧**：FIFO、LT、SPT、固定顺序等各自真实首选动作是否不同；
3. **duration 差异**：候选完整通信时长、集合中最长时长和总占用差；
4. **资源脚印差异**：资源数、热点资源负载、与未来 ready communication 的冲突数；
5. **跨事件风险**：候选完整执行区间内是否经过公共模拟器可见的 compute、job 或其他 active communication 完成事件；
6. **释放差异**：执行完整动作后新增 ready compute、ready communication、join 最后缺口和下游 tail 的差异；
7. **WAIT 接近度**：立即启动估计与等到下一个真实事件的估计差；
8. **多 job 风险**：仅当 benchmark 和公共状态能可靠提供 job 标识/arrival 时，记录 job 等待和潜在 starvation；否则标为 `not_available`。

跨事件和释放特征允许用一次完整合法 transition 计算，但其成本必须单列为 feature lookahead，不得伪装成零成本静态特征。特征计算若已经执行候选转移，应复用结果，避免 evaluator 再执行一次。

禁止使用“是否暂停当前通信”“当前通信切换收益”等可抢占信号。多资源中 active communication 只能作为上下文和 reservation，不能进入 challenger 列表。

特征 schema 必须版本化，并保存原始数值，而不只保存最终布尔触发结果。

### 4.5 触发器接口

统一接口：

```text
trigger(state_features, budget_snapshot) -> TriggerDecision
```

结果包含 `triggered`、原因、阈值版本、分数和预算拒绝原因。首轮实现以下透明触发器：

- `choice_only`：存在两个以上非等价候选；
- `small_lt_margin`：LT 分差低于阈值；
- `heuristic_disagreement`：便宜策略首选不同；
- `crosses_critical_event`：完整动作越过可能改变关键候选的真实事件；
- `duration_or_footprint_spread`：候选时长或资源脚印差异大；
- `wait_competition`：optional-idle 下 WAIT 与立即启动接近；
- `frozen_composite`：开发集上选定的少量规则组合。

第一轮不训练黑盒分类器。若透明规则不能取得稳定的质量—成本收益，再决定是否使用简单决策树；样本量和 workload 泄漏不足时不进入学习模型。

### 4.6 Evaluator 与缓存

Evaluator 接收 `(state, candidates, depth, completion_policy, mode, budget)`，只通过适配器调用公共 `legal_actions` 和 `step`。

每个候选值为：

```text
完整首动作经过时间 + 剩余 depth 的最小估值或 frozen LT completion cost
```

并列时稳定保留 LT，避免无质量收益的动作抖动。任一候选未完整评价时，不与已完成候选比较，整个当前决策回退 LT。

缓存键至少包含：benchmark hash、完整 residual task status/remaining、当前时间的规范化表示、active communication 及 remaining、资源 reservation、WAIT mode、剩余 depth、候选生成版本和 completion policy 版本。若要消除绝对时间，必须证明未来等价，并与未压缩状态在小图上对拍。

缓存项记录 exact/terminal/partial 来源。partial、timeout 和 budget-exhausted 结果不得进入可复用估值缓存。设置每实例最大缓存项和估算字节上限，达到上限后停止写入而不是无限增长。

### 4.7 共享预算账本

每个完整 schedule 使用一个共享账本，至少限制：

- `max_candidates_per_decision`；
- `max_triggered_decisions`；
- `max_completion_calls`；
- `max_expanded_decision_states`；
- `max_feature_transitions`；
- `search_depth`；
- `per_decision_soft_time_s`；
- `per_instance_soft_time_s`；
- `max_cache_entries` 和估算内存；
- 进程级 `hard_wall_time_s`。

启动任何 feature transition、候选分支或 completion 前先原子预留预算；完成后再记录实际消耗。到达限制时不启动下一项。内部软预算用于安全回退，外层沿用 `experiments/llm_structure/nonpreemptive/process_budget.py` 的独立子进程硬超时，确保单次 completion 卡住时父进程仍能终止。

必须满足：实际 completion calls、展开状态和候选评价数不超过配置；硬超时行状态为 timeout，不能被内部 fallback 覆盖成 completed。

### 4.8 结果对象与 trace

端到端结果至少保存：

- makespan、动作序列和 trace hash；
- mode、baseline/completion/candidate/trigger/feature 版本；
- 每个决策的 baseline、候选、触发、候选值和最终动作；
- generated/evaluated candidates；
- trigger positives、完整评价、预算拒绝和 fallback；
- completion calls、展开状态、feature transitions、缓存命中；
- voluntary WAIT、forced idle、资源利用率和 active reservation 检查；
- feature、candidate、evaluation、completion 和总 wall-clock；
- 完成、软回退、硬超时、异常和终止原因。

每个 completed 结果必须由独立 replay 验证通信连续区间、依赖、compute 连续性、单 channel 排他、多资源 reservation 和最终完成状态。

### 4.9 注册表边界

开发阶段只通过实验 runner 调用显式配置，不立即向 `src/registry.py` 添加大量算法名。只有冻结的无 rollout LT 和最终 selective 配置通过 holdout 后，才考虑增加一个稳定入口。全量、随机、周期、单特征和宽深消融保持实验配置，不成为公共算法。

### 4.10 从任意状态调用 Exact

决策标签需要求某个 reachable residual state 的最优 cost-to-go。不要在 `stage4d_labels.py` 中复制一套搜索；应在现有单 channel 和多资源 Exact 上增加受控的 `solve_from_state`/`cost_to_go` 入口，复用相同的合法动作、状态 key、下界、mode、time limit 和 state limit。

该入口返回 optimal/unknown、剩余最优成本、最优首动作集合、状态数和终止原因。必须验证：从 initial state 调用的新入口与现有整图 Exact 的 makespan 和首动作一致；对执行一个合法完整动作后的状态，`已用时间 + cost_to_go` 与手工枚举一致。该接口只接受模拟器产生且通过稳定状态检查的 state，不能由实验脚本手工拼装运行状态。

## 5. 决策级 Exact 标签

### 5.1 标签生成范围

先在既有 75 个小 benchmark 上生成标签，再在 Stage 4a 的 30 个真实小图上生成外部验证标签。现有 reference result 只给整图最优 makespan，不足以直接训练触发器，因此需要从公共 Exact 计算决策状态的 cost-to-go。

标签状态优先来自：

- 纯 LT、FIFO、固定顺序和 Exact 最优路径上访问的决策状态；
- 小图有界状态枚举中实际存在多个合法动作的状态；
- optional-idle 中立即启动与 WAIT 都合法的状态；
- 多资源中保留 active reservation 后存在多个启动集合的状态。

不要求把所有可达状态全部枚举完。超出状态或时间预算的状态标 unknown，并保留在统计中。

### 5.2 标签定义

对每个状态、每种动作口径枚举全部合法首动作，对每个动作执行完整公共 transition，再用相同口径 Exact 求最优后续值：

- `rollout_beneficial`：至少一个非 LT 动作严格优于 LT；
- `lt_optimal_unique`：LT 是唯一最优首动作；
- `lt_optimal_tie`：LT 属于并列最优动作；
- `equivalent`：不同动作 residual state 经独立等价检查相同；
- `unknown`：任一必要动作未完成 Exact 或动作枚举被截断。

保存全部首动作 cost-to-go、最优动作集合、LT regret、可取得的最大改善、Exact status、状态摘要和 benchmark hash。unknown 不得按负例处理。

### 5.3 错误归因

算法错误分成三层：

1. **触发错误**：有严格改善却未触发，或无改善却触发；
2. **候选错误**：已触发，但最优首动作不在候选列表；
3. **评价错误**：最优首动作在候选中，但有限深度/terminal completion 没有选中。

分别报告 precision、recall、候选召回率和评价命中率，并用 LT regret 加权漏触发，不把收益极小和收益很大的状态等价计数。

## 6. 数据划分与防泄漏

### 6.1 既有 75 个 benchmark

为旧 benchmark 创建不可变的 development、validation 和 holdout manifest。划分按生成模板、反例机制和 family 分组，不按单个 JSON 随机拆分：

- 同一随机生成器的相邻 seed 尽量放在同一组；
- 同一反例的缩放版、变体和直接派生图不得跨组；
- parallel chain、complex chain 和固定多资源均在 validation/holdout 保留样例；
- 阈值只在 development 选择，validation 用于选择少量候选组合，holdout 只运行冻结配置。

具体行数由决策标签可完成情况决定，但 split 在查看 Stage 4a 收益前冻结并保存 hash。不能为了提高命中率移动失败样例。

### 6.2 Stage 4a 真实图

Stage 4a 的 30 个小图全部作为 `real_small_external`，不参与阈值更新。结果按以下来源分组报告：GPT-13B 切片、Mixtral 切片和 4 个 multi-job 组合，不能把高度相似切片当作 30 个完全独立 workload 做显著性解释。

8 个中图作为 `real_medium_cost`：6 个单 channel、2 个固定多资源。它们只运行冻结后的极少数配置，并逐例报告，不用于重新选择阈值或候选顺序。

## 7. 算法探索计划

### 7.1 研究假设

依次检验以下假设：

- H1：只有 LT 分差小或便宜策略首选分歧时，rollout 才有较高改善概率；
- H2：不可抢占动作完整 duration 内跨过关键 release，比静态 LT 分差更能解释 LT 错误；
- H3：optional-idle 的有效 WAIT 主要出现在“未来事件很近且会释放更关键通信”的状态；
- H4：多资源中候选集合资源脚印差异和热点连续占用，比集合内 tail 简单求和更重要；
- H5：selective 节省的 completion calls 用于增加候选宽度或 depth 2 后，净收益高于同预算全量 depth 1；
- H6：若 LT 在真实小图上已接近 Exact，则 selective rollout 的合理结论可能只是降低分析成本，而不是改善 makespan。

### 7.2 探索轮次

#### A. 语义与上限检查

在手算小图和旧 adversarial 图上比较：无 rollout、全合法首动作 + Exact continuation、全量 depth 1、全量 depth 2。确认 rollout 可修复至少一个已知 LT 错误，也确认存在 rollout 估值错误或无收益案例。

这一步回答“候选与 completion 是否有能力改善”，不调 selective 阈值。

#### B. 候选召回探索

在旧 development 标签上逐步加入候选源，画出候选宽度 1/2/4/全部合法动作下的最优首动作召回率、completion calls 和 wall-clock。先确定最小可接受候选集合，再研究触发器。

如果宽度 2 已覆盖绝大多数有价值动作，就不继续堆叠 hybrid 候选；如果多资源合法集合枚举爆炸，固定 enumeration cap 并把遗漏单列为候选错误。

#### C. 单特征触发探索

分别运行 small margin、策略分歧、跨事件、duration/resource spread、WAIT competition。比较触发率、weighted recall、误触发成本和漏掉的 LT regret。

只保留在 development 和 validation 都有一致方向的信号。相关性很高的信号不重复叠加；对只在某一反例模板有效的信号标记适用范围。

#### D. 组合触发器

用少量可解释规则组合，例如：

```text
choice exists
AND (small LT margin OR heuristic disagreement)
AND (crosses event OR release/footprint differs)
```

optional-idle 可以增加 WAIT 专属分支；work-conserving 不计算 WAIT 触发。组合规则、阈值和优先级在旧 validation 后冻结。

#### E. 等预算宽度/深度实验

做两类公平比较：

1. 固定候选宽度和深度，比较全量、selective、随机、周期的质量与调用成本；
2. 固定总 completion calls、展开状态和整图墙钟，把 selective 节省的额度用于 `width 4/depth 1` 或 `width 2/depth 2`。

只有配置实际评价了更多候选或达到更深层，才能称为“节省预算换宽/深”。配置字段和结果必须记录实际而非请求值。

#### F. 真实小图冻结验证

在 Stage 4a 的 30 个小图上只运行：LT、全量 depth 1、匹配调用量的随机/周期、冻结 selective depth 1、一个等预算加宽或加深配置，以及 Exact 标签分析。optional-idle 与 work-conserving 分开。

若冻结 selective 在真实小图上没有修复任何 LT 首动作，或改善小于计时噪声且增加明显成本，不回到真实集调阈值；结论记录为未迁移。

#### G. 中图有限检查

中图只运行：LT、冻结 selective 的最便宜配置，以及小图上唯一表现最好的等预算宽/深配置。全量 rollout 只在 1--2 个最小中图上作为成本参照，不要求覆盖全部 8 个。

中图逐例报告 completed、fallback、timeout 或 `not_run_budget_gate`。不计算排除超时后的平均收益。

## 8. 预算与中图停止规则

### 8.1 小图预算

建议初始硬预算：

| 工作 | 单位 | 硬墙钟预算 |
| --- | --- | ---: |
| 旧 benchmark 决策标签 | case × mode | 30 秒 |
| Stage 4a 小图决策标签 | case × mode | 30 秒 |
| 小图端到端配置 | case × mode × config | 15 秒 |

同时设置 Exact state limit、completion call、展开和缓存限制。预算可在正式运行前根据少量 smoke 调低，但不得因某个算法超时而单独调高。

### 8.2 中图预算闸门

中图不死磕，采用固定闸门：

1. 按 Stage 4a 已记录的基线成本和 task/communication 数选择两个较小单 channel 图做 30 秒 pilot；
2. 某配置若在较小 pilot 上硬超时，不再运行其余中图，剩余项标 `not_run_budget_gate`；
3. 通过 pilot 的冻结配置进入最多 90 秒的逐 case 硬预算，超时不重跑、不提高预算；
4. 同一配置在前四个中图中出现两次硬超时，或超时率达到 25%，停止该配置剩余中图；
5. 若某个已完成配置的 rollout wall-clock 超过 LT 的 10 倍且没有改善，停止将更宽/更深版本扩展到更大中图；
6. 固定多资源两个 2038-task 图最后运行；单 channel 冻结配置未通过闸门时，不启动更昂贵的多资源 rollout；
7. 只有基础 LT 因环境故障而失败才允许重跑一次；算法 timeout 不是环境故障，不重跑。

这些规则在运行前写入 run metadata。停止后的 `not_run_budget_gate` 与 timeout 一样保留在完整率分母中，不能静默删除。

### 8.3 预算配置组

小图主实验建议冻结少量可解释配置：

- B0：depth 0，纯 LT；
- B1：choice-only/full，width 2，depth 1；
- B2：selective，width 2，depth 1；
- B3：随机触发，匹配 B2 completion calls；
- B4：周期触发，匹配 B2 completion calls；
- B5：selective，width 4，depth 1；
- B6：selective，width 2，depth 2。

只有 B5/B6 在相同总预算内实际完成时才比较。中图默认只带 B0、B2 和小图胜出的 B5/B6 之一。

## 9. 指标与统计

### 9.1 决策级指标

- 有选择状态数、触发率和预算拒绝率；
- trigger precision/recall、weighted recall；
- 候选最优动作召回率；
- evaluator 首动作命中率；
- LT regret、漏触发 regret 和评价误判 regret；
- rollout 修复 LT、破坏 LT和并列改动作的次数；
- WAIT 触发、WAIT 被选、WAIT 实际严格改善的次数；
- 多资源集合大小、资源脚印和 active reservation 合法性。

### 9.2 端到端指标

- makespan，相对 FIFO 和 LT 的绝对/相对变化；
- 小图 Exact gap、最优率和最坏 gap；
- optional-idle 与 work-conserving 分表结果；
- completion calls、展开状态、实际深度、候选数和缓存命中；
- 总 wall-clock、峰值内存和各阶段耗时；
- completed、fallback、timeout、failed、not_run_budget_gate；
- voluntary WAIT 次数/时间、forced idle 和资源利用率；
- 最坏退化及对应 benchmark/决策原因。

除均值外报告中位数、分位数、最大值和逐样例表。旧 benchmark、真实小图和真实中图分别汇总；GPT-13B 相邻切片、Mixtral 相邻切片和 multi-job 以 source group 为统计单位补充分组结果，避免伪独立样本夸大置信度。

### 9.3 单位成本收益

至少报告：

```text
相对 LT 减少的 makespan / 额外 completion call
相对 LT 减少的 makespan / 额外 wall-clock 秒
Exact gap 减少量 / 展开状态
```

若质量完全相同，selective 相对 full 的调用和时间下降可作为成本结论，但不能写成 makespan 改善。

## 10. 测试计划

### 10.1 语义测试

- 单 channel 每个 FLOW 只产生一个连续通信区间；
- 通信执行期间的新 compute/job 事件不允许切换当前通信；
- optional-idle WAIT 只到下一个真实事件；
- work-conserving 有可启动通信时无 WAIT；
- 多资源 active communication 在每个 rollout 层保持运行和 reservation；
- 新启动集合只使用空闲资源，work-conserving 集合满足极大要求；
- forced idle 不被记录为可选 WAIT。

### 10.2 候选与深度测试

- width 0/1/2/4 的实际评价数和截断记录；
- LT 始终在候选中且并列时保留 LT；
- depth 0/1/2 的实际分支层数、completion calls 和动作 trace；
- 单个完整通信跨过多个 compute 完成时仍只算一个首动作层；
- 多资源下一事件后 active 集合正确保留；
- 候选源产生重复动作时稳定去重。

### 10.3 预算与回退测试

- completion、展开、feature transition、trigger 和缓存预算恰好用尽及差一越界；
- 预算不足时不启动下一候选；
- 某一候选估值不完整时当前决策回退 LT；
- 内部软预算触发后结果标 fallback；
- 进程硬超时不能返回 completed；
- fallback 后缀与同一 residual state 上的 frozen LT 一致；
- 事后 baseline safeguard 默认关闭。

### 10.4 标签与缓存测试

- 手算小图的各首动作 cost-to-go、并列最优和 WAIT 标签；
- optional-idle 与 work-conserving 标签分别生成；
- unknown 不归入 negative；
- equivalent 只有 residual state 独立一致时成立；
- 缓存关闭/开启得到相同动作和 makespan；
- 改变 active remaining、reservation、mode 或 depth 后不能错误命中缓存；
- timeout/partial 估值不写缓存。

### 10.5 实验合同测试

- development/validation/holdout 无 benchmark ID 和模板组泄漏；
- Stage 4a 小图不参与阈值选择；
- 随机触发 seed 可复现并匹配调用量；
- timeout 和 not_run_budget_gate 保留在结果；
- completed trace 可独立回放；
- 结果 hash、配置 hash、manifest hash 和 simulator version 齐全。

修改公共模拟器、Exact、loader 或 benchmark schema 时运行完整测试；只新增 Stage 4d 策略时至少运行不可抢占 37 个定向回归、Stage 4a 集成测试和全部 Stage 4d 新测试。

## 11. 实验入口与结果归档

建议入口：

```powershell
python -m experiments.llm_structure.nonpreemptive.stage4d_labels --manifest <split_manifest> --output <labels.jsonl>
python -m experiments.llm_structure.nonpreemptive.stage4d_decision_analysis --labels <labels.jsonl> --output <report_dir>
python -m experiments.llm_structure.nonpreemptive.stage4d_evaluate --manifest <split_manifest> --config <config.json> --output <results.jsonl>
python -m experiments.llm_structure.nonpreemptive.stage4d_medium_check --manifest benchmark/llm_structure/nonpreemptive_manifest.jsonl --config <frozen_config.json> --output <results.jsonl>
```

结果按运行批次写入：

```text
docs/nonpreemptive_docs/result_docs/
├── stage4d_labels_<date>/
├── stage4d_old_benchmark_exploration_<date>/
├── stage4d_real_small_validation_<date>/
└── stage4d_real_medium_cost_<date>/
```

每个目录保存输入 manifest、配置、run metadata、逐样例结果、决策明细、汇总、失败清单和 trace hash。旧 R3 rollout 结果如被引用，标记 `legacy_r3_full_rollout`，不与新结果混表。

## 12. 实施顺序与阶段闸门

### D1：冻结基础行为

- 为 Stage 4a 228 行基线建立对拍；
- 冻结 LT、WAIT 和多资源贪心集合版本；
- 给旧 rollout 标记 legacy，不修改研究结论。

通过条件：基础策略抽取前后 makespan、动作和 trace 一致。

### D2：实现合同、适配器和预算

- 完成动作摘要、候选接口、depth 定义、共享预算和硬超时；
- 暂时使用 `choice_only` 触发。

通过条件：手算单/多资源图和预算失败测试全部通过。

### D3：建立旧 benchmark 标签

- 冻结 75-case split；
- 生成两种动作口径的状态级 Exact 标签；
- 分离触发、候选和评价错误。

通过条件：所有标签有 hash/status，unknown 未被删除。

### D4：候选和单特征探索

- 先做候选召回—成本曲线；
- 再做单特征触发，不混入组合规则。

通过条件：明确候选瓶颈与至少一个可复核的正/负触发案例。

### D5：组合触发与等预算实验

- 在旧 development/validation 冻结组合；
- 比较 full/selective/random/periodic/no-rollout；
- 检查节省预算是否真正转化为宽度或深度。

通过条件：冻结一个主配置和最多一个宽/深配置，不把整个网格带入真实图。

### D6：Stage 4a 真实小图验证

- 在 30 个小图上运行冻结配置和 Exact 标签分析；
- 不根据结果修改阈值。

通过条件：形成迁移、未迁移或证据不足的明确判断，并报告最坏退化。

### D7：Stage 4a 中图有限检查

- 按第 8.2 节运行 pilot 和预算闸门；
- 完整保留 timeout/not_run。

通过条件：得到可解释的成本边界；不要求为了完成率增加预算。

### D8：结论与去留

- 汇总适用范围、成本、反例和失败原因；
- 判断算法候选、成本控制层、分析工具或否定结论。

## 13. 退出条件

只有同时满足以下条件，Stage 4d 才可结束：

1. 所有 rollout 首动作和后续分支复用不可抢占公共状态转移；
2. WAIT、完整通信、完整新启动集合和 active reservation 语义有专项测试；
3. baseline、候选、触发、evaluator、completion policy 和预算可以分别消融；
4. depth、width、completion calls、展开状态和缓存限制真实生效并完整记录；
5. 既有小 benchmark 具有决策级 Exact 标签或明确 unknown；
6. full、selective、random、periodic 和 no-rollout 在相同预算合同下比较；
7. optional-idle 与 work-conserving 的标签、动作、结果和结论分开；
8. 冻结配置在 Stage 4a 的 30 个真实小图上完成验证，不用真实结果返调阈值；
9. 中图按固定预算闸门运行，timeout 和 not_run_budget_gate 未被排除；
10. 节省的预算若声称用于更宽/更深，实际候选数和实际深度提供证据；
11. 报告净 makespan、Exact gap、单位成本收益、完整率和最坏退化；
12. 明确结果适用的 workload、资源模型、WAIT mode、规模和预算。

若收益只存在于旧反例、小图上无法迁移、真实图 LT 已经足够、候选成本超过收益，或中图普遍触发预算闸门，应将 selective rollout 降级为离线分析工具或形成否定结论。代码已经实现不是继续扩展或进入未来综合算法的理由。
