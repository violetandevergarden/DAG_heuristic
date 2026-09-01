# Stage 4e 不可抢占 Barrier 感知调度实现与算法探索计划

日期：2026-08-31

对应纲领：

- `docs/nonpreemptive_docs/plan_docs/stage4_LLM_search.md`
- `docs/nonpreemptive_docs/plan_docs/stage4e_barrier_scheduling.md`

状态：待实施

## 1. 阶段定位

本阶段研究 barrier 信息能否减少 residual Longest Tail 的错误。barrier 只允许作为：

- Longest Tail 的平局规则；
- Longest Tail 附近候选的有界修正；
- 有证据边界的初筛；
- 一步完整动作反事实的 challenger 来源；
- Selective Rollout 的触发信号。

barrier 不作为替代 Longest Tail 的独立主策略。`barrier-only` 只用于诊断、消融和构造反例，不能因局部 barrier 更早 ready 就解释为端到端 makespan 更好。

本计划同时覆盖：

1. **代码实现**：不可抢占 residual barrier 的定义、特征、动作评分、策略、预算、trace 指标和实验入口；
2. **算法探索**：先隔离每个 barrier 信号的有效性和失败条件，再研究 tie-break、有界修正、一步反事实和 rollout 触发，最后在 Stage 4a 真实图上冻结验证。

所有状态转移必须由不可抢占公共模拟器执行。通信一旦启动便连续运行到完成；多资源 active communication 不得被 barrier 策略移除；optional-idle 与 work-conserving 始终分开。

## 2. 当前基础与边界

### 2.1 可用输入

当前可以按三层使用输入：

| 层级 | 输入 | 用途 |
| --- | --- | --- |
| 机制层 | 既有 75 个不可抢占 R2--R4 benchmark，以及少量手工 barrier 反例 | 手算、语义验证、Exact 标签、单特征和失败模式探索 |
| 真实小图层 | Stage 4a 的 30 个 6--38 task real-derived/real-composed 小图 | 冻结后的真实结构、首动作和 Exact gap 验证 |
| 真实中图层 | Stage 4a 的 8 个 640--2038 task 中图，其中 2 个固定多资源 | 有限成本和完整率检查 |

Stage 4a 大图已退出正式范围，本阶段不恢复大图，也不以生成更多大图作为 4e 的完成条件。

### 2.2 Stage 4a 对 4e 的约束

Stage 4a 的 30 个小图在两种动作口径下均有 optimal 证书，适合检查 barrier 信号是否命中最优首动作。8 个中图的简单基线最大 wall-clock 已约 46.5 秒，因此中图只运行冻结后的少量在线方法；超时不反复加预算。

Stage 4a 基线中 Longest Tail 相对 FIFO 的已观察最大改善约 1.23%，多数样例差异较小。4e 必须接受三种可能结果：

1. barrier 在少数 Exact 小图上修复 LT，并能迁移到真实 holdout；
2. barrier 只适合作为平局或 rollout 触发信号，降低搜索成本但不直接改善 makespan；
3. barrier 对真实图没有稳定净收益，应作为诊断特征或否定方向结项。

### 2.3 现有 barrier 资产的使用边界

`src/llm_structured/barrier.py` 已包含 direct last-missing、立即 compute 释放、下游 tail、共享后继去重和多资源集合特征等思路，但其 context 适配、测试和在线调用目前基于可抢占模型。它不能直接视为不可抢占 Stage 4e 实现。

旧实验还存在需要避免的做法：

- 把 barrier-only 当成候选主算法；
- 把可达全部后继工作误称为“立即释放收益”；
- 用两个完整 schedule 事后取较优值，却不计第二次调度成本；
- 把 direct-child join 称为一般 barrier 链；
- 把 contention-free 到达估计当作实际完成时间；
- 只报告局部 barrier 时间而不报告最终 makespan 和后续 barrier 退化。

因此，新实现放入不可抢占语义专属模块。可抢占模块只作为字段、测试方法和历史反例参考；除非抽取完全中立的 DAG 图工具且两条线回归均通过，不修改其在线行为。

## 3. Barrier 的正式定义

### 3.1 结构 barrier

结构 barrier 从 DAG 依赖定义，不依赖任务名称：

- **direct join**：当前节点的直接前驱数大于 1；
- **collective completion join**：多个 collective flow 或其完成节点汇入同一后继；
- **optimizer/pipeline join**：只有当公开 DAG 依赖确实形成汇合时才成立；metadata role 只辅助命名；
- **barrier chain**：一个 barrier 的后继区域继续通向另一个结构 join；
- **job-local barrier**：全部前驱属于同一 job；
- **cross-job shared resource interaction**：不是 DAG barrier，因为 job 间没有依赖，只能作为资源竞争上下文。

若 serializer 新增 compute-order 边导致入度增加，报告中必须区分原始依赖与 serializer 边来源。算法可以使用公开 DAG 的有效依赖，但研究解释不能把 serializer 串行化自动称为训练同步。

### 3.2 Residual barrier 状态

对每个 barrier `b`，当前状态至少保存：

- 已完成、运行中和未开始的前驱；
- 每个未完成分支的 residual work；
- 当前 latest/second-latest branch arrival 估计；
- barrier 缺口数；
- barrier 下游 residual tail；
- barrier 后是否还有其他更长分支或后续 barrier；
- barrier 是否位于当前 residual critical path 的一种估计；
- 相关通信使用的固定资源及其 active reservation。

`last-missing communication` 只在以下条件成立时使用：候选通信是某个 direct join 当前唯一未完成的直接前驱，并且候选当前合法可启动。若候选还需经过中间节点才能到达 join，则标为 indirect branch candidate，不能使用 direct last-missing 名称。

### 3.3 Slack 与到达时间

对 barrier 分支的到达量分为三类：

1. **状态精确量**：当前 task status、active remaining、已完成前驱和公共 transition 后真实发生的事件；
2. **结构量**：DAG residual path、后继并集、direct last-missing 和下游 tail；
3. **启发式估计**：忽略未来通信竞争或采用 frozen completion policy 的 branch arrival、slack 和 barrier ready time。

slack 的符号和基准固定记录。建议定义：

```text
candidate_slack = latest_other_branch_eta - candidate_branch_eta
```

正值表示候选分支按当前估计可更晚到达而不延迟该 barrier，负值表示候选分支可能成为瓶颈。该量只有在所有分支 ETA 使用同一估计方法时才可比较，不得称为精确 deadline。

### 3.4 Barrier 时间指标

trace 中分别记录：

- barrier 所有前驱完成的时间；
- barrier compute 自动开始/完成时间；
- barrier 后第一个 communication ready 时间；
- job/iteration 局部完成时间；
- 最终 makespan。

局部 barrier 提前但 makespan 不变只说明局部时序改变；当前 barrier 提前而后续 barrier 或 makespan 变差必须记为破坏案例。

## 4. 不可抢占特有的候选风险

Barrier 特征不能只看候选完成后释放什么，还必须评价候选连续执行期间失去的响应机会。

### 4.1 单 channel

对 `FLOW(i)` 至少记录：

- 完整 duration；
- 完整执行区间内将发生的 compute/job 事件；
- 这些事件可能释放的更高 tail 或 last-missing communication；
- 候选完成后的新增 ready compute/communication；
- 立即启动相对合法 WAIT 的机会成本；
- 候选对当前 barrier 和后续 barrier 的方向是否一致。

执行期间出现更关键通信并不允许切换当前通信，只作为启动前风险。

### 4.2 固定多资源

对 `START(set)` 至少记录：

- 当前 active communication 和已占资源；
- 新集合占用的资源并集；
- 集合内各通信 duration 和下一真实完成事件；
- 下一事件后仍 active 的新通信及其持续 reservation；
- 被集合排除的 ready communication；
- 对未来 last-missing 分支所需资源的连续阻塞；
- 集合成员共享 downstream 时的去重结果。

整集合评分不能简单相加成员的后继工作或 barrier tail。共享后继、共享 join 和共享资源分别按集合并集统计。

### 4.3 WAIT

optional-idle 下，只有公共模拟器返回 WAIT 合法时才评价：

- 下一个真实事件距离；
- 事件是否释放新的 last-missing/barrier challenger；
- WAIT 后 LT 首选是否变化；
- WAIT 时间与立即启动通信 duration 的关系；
- WAIT 是否只是延迟所有工作而无候选变化。

work-conserving 不生成主动 WAIT。无 ready communication 时的 forced idle 不属于 barrier 策略动作。

## 5. 代码实现计划

### 5.1 模块布局

建议新增：

```text
src/llm_structured/nonpreemptive/barrier/
├── contracts.py       # 特征、数量类型、策略配置和结果合同
├── adapters.py        # 单 channel/多资源只读状态适配
├── graph.py           # 仅从公开 DAG 建立 join、barrier chain 和后继并集
├── context.py         # 当前 residual barrier 上下文
├── features.py        # 单通信、WAIT 和整集合特征
├── policies.py        # barrier-only、tie-break、有界修正、初筛
├── counterfactual.py  # 一步完整动作 + 同一 LT completion
├── rollout_trigger.py # 与 Stage 4d evaluator 的可选桥接
└── metrics.py         # barrier ready/complete 与后续 barrier 追踪

experiments/llm_structure/nonpreemptive/
├── stage4e_census.py
├── stage4e_labels.py
├── stage4e_ablation.py
├── stage4e_evaluate.py
└── stage4e_medium_check.py
```

模块只能读取公共 benchmark 和模拟器状态。`features.py` 不推进正式调度；需要 transition 的反事实字段通过显式 evaluator 调用，并计入成本。`policies.py` 只从模拟器给出的合法动作中选择。

### 5.2 统一状态适配器

不可抢占单 channel 与多资源模型当前字段不同，因此先定义只读适配接口：

```text
task_ids
task(task_id)
status(task_id)
remaining(task_id)
dependencies(task_id)
children(task_id)
ready_communications()
active_communications()
resources(task_id)
occupied_resources()
legal_actions(mode)
preview(action)
```

`preview(action)` 必须调用公共 `step` 得到 immutable child state 和事件，不自己计算时间推进。适配器不得把 active communication 伪装成 ready candidate。

### 5.3 数量类型和版本

每个特征字段携带 `quantity_mode`：

- `state_exact`：由当前状态直接得到；
- `transition_exact`：由一次公共合法 transition 得到；
- `structural_exact`：由当前 residual DAG 关系精确得到，但不表示时间收益；
- `heuristic_estimate`：依赖无竞争或 frozen policy 假设；
- `source_metadata`：只用于解释，不参与默认在线动作；
- `not_available`：当前输入不能可靠提供。

特征 schema、barrier 定义、到达估计和策略配置分别版本化。任何字段含义变化后旧结果保持 legacy，不静默复用。

### 5.4 Barrier 图索引

加载 benchmark 时一次性建立：

- parents/children；
- direct join 列表；
- 每个 task 可达的最近若干 barrier；
- barrier 层级和 barrier-to-barrier 后继关系；
- 下游节点并集所需的位图或稳定集合；

在线图索引只读取 benchmark 公开问题字段，不读取 provenance 或 sidecar。原始边与 serializer 边来源若可用，只由实验 census 在算法运行后关联到解释报告；缺失时标 `not_available`，不能影响候选和动作。

在线状态只更新 completed/active/remaining，不重复遍历整图。层级深度、最大追踪 barrier 数和后继集合缓存设硬上限；超过时标 `truncated`，不能把不完整结果当成无 barrier。

### 5.5 单候选特征

每个 ready communication 至少生成：

- residual tail 和 tail after candidate；
- own duration/remaining；
- direct last-missing join 数和 ID；
- candidate 完成后立即新增 ready compute/communication；
- 最近 barrier 的下游 residual tail；
- branch ETA、slack 和 arrival spread，明确为估计；
- candidate 区间内跨过的真实事件数；
- 区间内可能出现的更关键 barrier 缺口；
- 资源数、热点冲突度和连续占用时间；
- 当前 barrier 与下一 barrier 的预计方向。

“立即新增 ready”必须使用公共 transition 前后集合差计算。结构可达的全部 compute work 另存 `reachable_descendant_compute_work`，不得与 immediate release 相加或共用名称。

### 5.6 整集合特征

对多资源 action：

- 先由公共模拟器确认 action 合法；
- 对 selected communication、descendants、join、resources 做集合并集；
- 记录 shared-downstream 去重前后差；
- 记录完成当前 direct joins 的并集，不重复计数同一 join；
- 记录下一事件后 remaining active set；
- 记录 excluded ready candidates 及它们与 future barrier 的资源冲突；
- 分别保存集合最短/最长 duration，而不是只保存总和。

optional-idle 非极大集合与 work-conserving 极大集合分开调用和统计。

### 5.7 特征缓存

静态 DAG 索引可按 benchmark hash 缓存。Residual 特征缓存键至少包含：完整任务 status/remaining、active set、resource reservation、mode、barrier depth、估计器版本和 action signature。

只包含“已完成集合”而忽略 active remaining 的 key 不合法。缓存开关必须在小图上产生相同动作和 makespan；truncated、timeout 或 partial 反事实不进入可复用缓存。

### 5.8 结果和独立验证

每个算法结果保存：

- benchmark/manifest/config/simulator hash；
- mode、方法、feature/barrier/estimator 版本；
- makespan、trace hash、完成状态和终止原因；
- 每次与 LT 分歧的状态、LT 动作、barrier challenger、特征和选择原因；
- barrier ready/complete 时间及后续 barrier 变化；
- 修复 LT、破坏 LT、局部提前但 makespan 不变的次数；
- voluntary WAIT、forced idle、资源利用率和 active reservation；
- 特征、反事实、completion 和总 wall-clock；
- 峰值内存、缓存、截断、fallback 和 timeout。

completed trace 必须独立验证依赖、compute 连续性、每个通信单一区间、单 channel 排他和多资源 reservation。

## 6. 候选算法

### 6.1 B0：Residual Longest Tail

冻结的主基线。所有加强方法在无 barrier 信号、预算不足、特征截断或候选不合法时回退 B0。

### 6.2 B1：Barrier-only 诊断

按 last-missing、下游 barrier tail、立即释放等排序，但不使用 LT 作为第一关键字。它只用于证明 barrier 局部信号可能失败，并估计“完全替代 LT”的风险；不进入最终推荐候选。

### 6.3 B2：LT + last-missing tie-break

只有 residual LT 主分数严格相同或在整数定义上完全并列时，才按：

1. direct last-missing；
2. transition-exact immediate release；
3. downstream barrier tail；
4. 稳定 task ID；

进行 tie-break。该方法最保守，先于任何 margin 或加权方案验证。

### 6.4 B3：LT + 有界 barrier 修正

先由 LT 确定 baseline，仅允许 tail 损失处于冻结 margin 内的 challenger 参与 barrier 比较：

```text
tail_loss = LT_tail - challenger_tail
normalized_tail_loss = tail_loss / max(LT_tail, 1)
```

首轮优先使用词典序规则，不把多个量直接加权：direct last-missing → immediate release → downstream barrier tail → 较短 duration/较低热点占用。margin 只在开发集选择，真实 holdout 不返调。

该方法不是“安全”算法；即使 tail loss 小也可能退化，必须报告最坏案例。

### 6.5 B4：Barrier 初筛

初筛只删除能由当前依赖和合法性事实证明不应选择的动作。仅凭“没有 direct barrier 信号”不能删除候选，因为可能存在 indirect barrier 或更长下游。

第一版允许初筛是可审计 no-op。只有形成明确的支配条件并在未压缩小图中证明/对拍后，才启用删除。过滤后为空必须回退 LT，不能制造 WAIT。

### 6.6 B5：一步完整动作反事实

从 LT baseline 和一个 barrier challenger 出发：

1. 分别执行一个完整合法动作；
2. 对 child state 使用同一个 frozen LT completion；
3. 比较 `transition elapsed + completion cost`；
4. 并列保留 LT；
5. 任一评价超时或不完整时回退 LT。

单 channel FLOW 连续运行到完成。多资源 START(set) 推进到下一真实事件，未完成通信继续 active；不能在 child state 移除它们。

该方法的 completion call、展开和 wall-clock 全部计入结果。它是在线有限反事实，不等同 Exact。

### 6.7 B6：Barrier 触发 Selective Rollout

如果 Stage 4d 的不可抢占 evaluator 已通过语义和预算测试，barrier 只作为 trigger 输入：

- 比较 `choice_only rollout` 与 `barrier-triggered rollout`；
- 候选生成、深度、completion policy 和总预算保持相同；
- 用相同调用率的随机/周期 trigger 对照；
- 分开统计 barrier trigger 的增量收益与 rollout evaluator 本身的收益。

若 Stage 4d 尚未提供稳定接口，4e 先完成 B0--B5，不在 4e 内复制一套 rollout。

### 6.8 B7：多资源整集合修正

以 Stage 4c 或冻结的合法 LT packing 为 baseline，在多个合法集合中比较 barrier union 特征。active reservation 始终固定。work-conserving 只比较极大新启动集合；optional-idle 可比较有限非极大集合或 WAIT，但必须受候选上限约束。

不使用“成员 barrier 分数求和”。一个高分成员若与另一个更关键通信冲突，必须通过集合合法性和 excluded candidate 风险体现。

## 7. Exact 标签与反事实标签

### 7.1 小图 Exact 标签

使用不可抢占 Exact 从 reachable decision state 求 cost-to-go。若 Stage 4d 已增加 `solve_from_state`，4e 直接复用；否则将该接口作为公共 Exact 的共享前置工作，不在 barrier 实验脚本中复制搜索。

对每个有选择状态、每种 mode 保存：

- 全部合法首动作的最优 cost-to-go；
- Exact 最优动作集合；
- LT 动作和 regret；
- barrier challenger 和 regret；
- barrier signal 是否存在；
- 当前/后续 barrier ready time；
- optimal、time_limit、state_limit 或 unknown。

unknown 不作为 barrier 无效的负例。

### 7.2 中图条件反事实

中图没有 Exact 时，只使用“执行完整首动作 + 同一 frozen LT completion”的条件反事实。它回答 challenger 在该 completion policy 下是否更好，不能称为最优标签或因果最优收益。

### 7.3 错误分类

分开记录：

- barrier 信号存在但 LT 已最优；
- barrier challenger 不在 Exact 最优集合；
- tie-break 修复/破坏 LT；
- margin 纳入了错误 challenger；
- immediate release 正确但后续 tail 更差；
- 当前 barrier 提前但下一 barrier/makespan 退化；
- 到达估计排序错误；
- 多资源共享后继重复奖励或资源冲突导致误判。

## 8. 数据划分与执行顺序

### 8.1 第一层：既有 R2--R4 benchmark

先建立 development、validation、holdout manifest，按生成模板和反例机制分组，避免同一反例变体跨组。旧 benchmark 用于：

- 手工核对 direct/indirect barrier；
- Exact 首动作标签；
- 单特征、tie-break、margin 和反例探索；
- 单 channel 与多资源语义回归。

合成/受控结果只能解释机制，不能替代真实 LLM 结论。

### 8.2 第二层：受控 100--1000 节点压力图

使用现有一般 DAG generator 在临时实验目录按 100/250/500/1000 节点生成 sparse、join-heavy、multi-barrier 和 hotspot profile，每个 cell 少量固定 seed。它们用于测量：

- barrier census 和特征成本；
- 后继并集/层级缓存是否退化；
- 在线 tie-break/margin 的可运行性；
- 一步反事实的预算边界。

这些图不进入仓库固定 benchmark，也不支持真实 LLM 收益结论。超时和失败完整保留。

### 8.3 第三层：Stage 4a 真实小图

30 个真实小图作为冻结验证集。阈值、词典序、barrier depth、候选上限和预算在进入该层前冻结。按共同 source group 报告 GPT-13B、Mixtral 和 multi-job，不把相邻切片视为完全独立 workload。

### 8.4 第四层：Stage 4a 中图

8 个中图只运行 B0、B2、冻结 B3 和小图上表现最好的 B5/B6 之一；B1 barrier-only 只在 1--2 个较小中图做诊断，B4 没有证明时保持 no-op。两个 2038-task 多资源图最后运行。

中图不参与调参，不要求所有方法完成。

## 9. 算法探索问题与轮次

### 9.1 研究假设

- H1：direct last-missing 只在候选 tail 接近时适合作为 LT tie-break；
- H2：transition-exact immediate release 比可达后继总量更能预测局部收益，但仍不足以保证 makespan；
- H3：候选完整 duration 跨过未来关键 barrier release 是 barrier challenger 退化的重要原因；
- H4：当前 barrier 的价值取决于 downstream tail 和下一 barrier，而不是缺口数本身；
- H5：多资源集合必须使用后继并集与资源冲突，成员分数相加会重复奖励；
- H6：optional-idle 中 barrier 信号只有在 WAIT 会释放更关键 last-missing 时才可能支持主动等待；
- H7：barrier 更可能适合作为 rollout 触发器或诊断指标，而不是在线独立排序。

### 9.2 E0：Barrier census

在旧 benchmark 和 Stage 4a 小图的 LT/FIFO 路径上统计：

- direct join、barrier 层数和 last-missing 出现频率；
- 信号出现时是否存在两个以上合法动作；
- LT 与 barrier challenger 分歧数；
- 当前 barrier、下一 barrier 和 makespan 是否发生变化；
- optional-idle 与 work-conserving 的差异。

sampled path 只作为 observed，不证明其他路径无 barrier。

### 9.3 E1：单特征诊断

分别只启用 last-missing、immediate release、downstream tail、slack、duration、hotspot、WAIT 和 shared-downstream 去重。每项必须给出：支持例、最小反例、出现次数、首动作命中、运行成本和不能推出的结论。

先判断信号是否有信息，再组合；不直接堆叠全部词典序字段。

### 9.4 E2：保守在线方法

按 B2 tie-break → B3 小 margin → B3 较大 margin 的顺序探索。画出 margin 与：

- 触发/改选率；
- Exact 首动作命中；
- makespan 改善/退化；
- 最坏 gap；
- wall-clock；

的关系。只保留 validation 上最坏退化可接受的最小 margin 配置。

### 9.5 E3：不可抢占风险消融

在同一 barrier challenger 上逐步加入：

1. 完整 duration；
2. 跨事件风险；
3. 热点连续占用；
4. 下一 barrier；
5. WAIT 后新候选；
6. active reservation。

每次只增加一项，判断改善来自 barrier 还是不可抢占阻塞风险修正。

### 9.6 E4：一步反事实

比较 B3 静态修正与 B5 一步完整动作反事实，检查额外 completion cost 是否确实修复静态误判。分别报告：

- challenger 生成质量；
- 一步评价修复/破坏数；
- 单位 completion call 的收益；
- 预算不足 fallback。

### 9.7 E5：Barrier 触发 rollout

只有 Stage 4d 接口可用时运行。固定同一候选、深度和 completion policy，比较 choice-only、barrier trigger、随机和周期。若 barrier 只降低调用量且 makespan 相同，结论限定为成本控制；不能将 rollout 的全部收益归因于 barrier。

### 9.8 E6：多资源集合

先在 17 个旧多资源小图上用 Exact/枚举验证 union 特征，再进入 2 个真实 topology 中图。比较：LT packing、barrier member-sum 负面对照、barrier union、资源风险修正和一步反事实。

member-sum 仅为证明重复计数风险，不作为推荐策略。

### 9.9 E7：冻结真实验证

在 Stage 4a 30 个小图上运行冻结 B0/B1/B2/B3/B5，以及可用时的 B6。B1 只作诊断。结果出来后不返调 margin 或权重。

随后按中图预算闸门运行极少数配置，形成迁移、受限或否定结论。

## 10. 基线、消融与公平比较

正式比较至少包含：

- FIFO；
- 输入固定顺序；
- residual LT；
- barrier-only 诊断；
- LT + last-missing tie-break；
- LT + frozen margin barrier 修正；
- barrier challenger 一步完整动作反事实；
- 可用时 barrier-triggered selective rollout；
- 相同调用率的随机/周期 rollout；
- 小图对应 mode 的 Exact。

关键消融：

- direct last-missing；
- transition-exact immediate compute/communication release；
- downstream tail；
- slack/arrival estimate；
- full duration；
- cross-event risk；
- hotspot occupancy；
- WAIT；
- next barrier；
- shared-downstream union；
- active reservation；
- 单通信评分与整集合评分。

同一对照固定 benchmark hash、simulator、LT tie-break、mode、seed、预算和机器环境。offline best-of-two 若保留，单独列为“两个完整日程较优值”，成本包含两次调度，不进入在线质量排名。

## 11. 预算与中图停止规则

### 11.1 预算建议

| 工作 | 单位 | 初始硬墙钟预算 |
| --- | --- | ---: |
| 旧小图 Exact/标签 | case × mode | 30 秒 |
| Stage 4a 小图算法 | case × mode × method | 15 秒 |
| 100--1000 节点特征/在线方法 | case × method | 30 秒 |
| 中图在线 tie-break/margin | case × mode × method | 90 秒 |
| 中图一步反事实/rollout | case × mode × method | 90 秒 |

每个进程还限制 feature transitions、completion calls、barrier depth、后继集合节点数、缓存项和峰值内存。内部软预算负责回退，外部独立进程负责硬超时。

### 11.2 中图闸门

1. 先在 640-task 和 838-task 单 channel 图上做 30 秒 pilot；
2. 某方法在任一较小 pilot 硬超时，不扩展到其余中图；
3. 通过 pilot 后使用最多 90 秒正式预算，超时不重跑、不提高预算；
4. 同一方法在前四个中图中出现两次超时或超时率达到 25%，剩余行标 `not_run_budget_gate`；
5. 在线 barrier 方法若比 LT 慢 5 倍以上且没有任何动作分歧，停止更复杂版本；
6. 一步反事实/rollout 若比 LT 慢 10 倍以上且没有改善，不进入更大的图；
7. 两个固定多资源中图最后运行，旧多资源小图语义或集合特征未通过时不启动；
8. 算法 timeout 不是环境失败，不允许用增加预算重跑掩盖。

timeout 和 `not_run_budget_gate` 保留在完整率分母中。

## 12. 必须构造和保留的反例

受控反例只能解释机制，但以下类型必须覆盖：

1. **局部 barrier 非最终瓶颈**：提前它不改变 makespan；
2. **last-missing 后仍有长尾**：完成 join 后下游不关键，LT 另一分支更重要；
3. **短 barrier 通信阻塞长关键通信**：局部释放更快但连续占用造成更大损失；
4. **共享下游重复计数**：多个候选汇入同一后继，成员求和错误放大；
5. **到达估计错误**：忽略通信竞争后 slack 排序与实际相反；
6. **当前 barrier 提前、下一 barrier 延迟**；
7. **多资源高分候选互相冲突**：逐成员高分不能组成合法/优质集合；
8. **active reservation 误移除**：新集合不得抢占已运行通信；
9. **WAIT 假收益**：等待没有释放新候选，只延迟现有工作；
10. **名称误导**：修改 role/name 后结构特征和动作不应改变。

每个反例保存手算时间线、LT 动作、barrier 动作、Exact 或完整反事实、局部 barrier 时间和最终 makespan。

## 13. 指标与报告

### 13.1 结构和信号指标

- barrier 数、层级、direct/indirect 数；
- last-missing 出现数及位于有选择状态的比例；
- slack、arrival spread 和下游 tail 分布；
- 信号出现、与 LT 分歧、实际改选和 Exact 改善四个层次；
- shared-downstream 去重比例；
- 多资源 barrier 集合与冲突类型。

### 13.2 质量指标

- makespan，相对 FIFO/固定顺序/LT 的变化；
- Exact gap、最优率和首动作命中；
- LT 修复、LT 破坏、并列改选；
- 当前 barrier ready/complete 时间变化；
- 下一 barrier、job completion 和 makespan 变化；
- optional-idle 相对 work-conserving 的收益和最坏退化；
- barrier trigger 相对相同 rollout evaluator 的增量收益。

### 13.3 成本和可靠性

- feature、union、arrival estimate、反事实和 completion wall-clock；
- completion calls、feature transitions、访问后继节点数；
- 峰值内存、缓存项和命中率；
- completed、fallback、timeout、failed、not_run_budget_gate；
- voluntary WAIT、forced idle 和资源利用率；
- 最坏退化样例及第一处分歧状态。

均值之外报告中位数、分位数、最大值和逐样例表。旧 benchmark、受控压力图、真实小图和真实中图分开，不能合并成一个胜率。

## 14. 测试计划

### 14.1 结构定义测试

- barrier 仅由依赖识别，改名不改变结果；
- direct join、indirect branch 和 barrier chain 正确区分；
- 原始边/serializer 边来源可追踪；
- 多个 barrier 层级和共享后继不重复计数；
- 已完成前驱从 residual 缺口中移除。

### 14.2 Residual 特征测试

- pending 使用 duration，running 使用 remaining，completed 为零；
- direct last-missing 只命中唯一未完成直接前驱；
- immediate release 等于公共 transition 前后 ready 集差；
- reachable descendant work 不冒充 immediate release；
- slack 的符号、零分母、并列和估计模式正确；
- 当前 barrier 与 next barrier 指标分开；
- 特征截断标记不被解释为无信号。

### 14.3 不可抢占动作测试

- 单 channel barrier challenger 连续执行完整通信；
- 通信期间 release 不产生切换动作；
- 多资源 START 后未完成通信继续 active；
- active reservation 不进入候选也不被释放；
- work-conserving 集合极大，optional-idle 非极大/WAIT 只在合法时出现；
- forced idle 不记作主动 barrier WAIT。

### 14.4 策略和反事实测试

- B2 仅在 LT 真并列时改选；
- B3 只在 frozen margin 内允许 challenger；
- B4 无支配证明时保持 no-op；
- B5 两个动作使用同一 LT completion；
- 任一不完整估值回退 LT；
- 并列保留 LT；
- offline best-of-two 默认不注册为在线算法；
- barrier trigger 与 rollout evaluator 收益可分开统计。

### 14.5 多资源集合测试

- action descendants、joins 和 resources 使用并集；
- shared-downstream 只计一次；
- excluded candidate 和热点冲突正确；
- member-sum 反例能暴露重复奖励；
- 资源标签置换下合法性和 makespan 不变。

### 14.6 缓存、预算和实验合同

- 缓存开关动作/makespan 一致；
- active remaining、reservation、mode、depth 变化不会误命中；
- feature/completion/cache 预算到达前预留，最终不超限；
- 硬超时不返回 completed；
- timeout/not_run 不被汇总过滤；
- development/validation/holdout 和 source group 无泄漏；
- Stage 4a 真实验证结果不用于返调阈值；
- completed trace 可独立回放。

至少运行不可抢占 37 个定向回归、Stage 4a 集成测试和全部 Stage 4e 新测试。修改公共模拟器、Exact、loader 或 benchmark 时运行完整测试。

## 15. 实验入口与产物

建议入口：

```powershell
python -m experiments.llm_structure.nonpreemptive.stage4e_census --manifest <manifest> --output <report.jsonl>
python -m experiments.llm_structure.nonpreemptive.stage4e_labels --manifest <small_manifest> --output <labels.jsonl>
python -m experiments.llm_structure.nonpreemptive.stage4e_ablation --manifest <split_manifest> --config <config.json> --output <results.jsonl>
python -m experiments.llm_structure.nonpreemptive.stage4e_evaluate --manifest benchmark/llm_structure/nonpreemptive_manifest.jsonl --config <frozen_config.json> --output <results.jsonl>
python -m experiments.llm_structure.nonpreemptive.stage4e_medium_check --manifest benchmark/llm_structure/nonpreemptive_manifest.jsonl --config <frozen_config.json> --output <results.jsonl>
```

结果归档：

```text
docs/nonpreemptive_docs/result_docs/
├── stage4e_barrier_census_<date>/
├── stage4e_barrier_labels_<date>/
├── stage4e_controlled_ablation_<date>/
├── stage4e_real_small_validation_<date>/
└── stage4e_real_medium_cost_<date>/
```

每个目录保存 manifest/config hash、环境、预算、逐样例结果、分歧状态、反例、汇总和失败清单。旧可抢占 barrier 结果不与不可抢占结果混表。

## 16. 实施顺序与闸门

### E1：冻结 LT 与语义适配

- 建立不可抢占 adapter；
- 对拍 Stage 4a LT 基线；
- 验证单/多资源 action 与 trace。

通过条件：adapter 不改变模拟器动作和 228 行基线结果。

### E2：Barrier 定义和 census

- 实现图索引、quantity mode、direct/indirect/barrier chain；
- 在旧 benchmark 与真实小图上只读扫描。

通过条件：名称置换、共享后继和 residual 状态测试通过，形成出现/分歧目录。

### E3：Exact 标签和单特征

- 生成 reachable state 首动作标签；
- 分别验证 last-missing、release、tail、slack、duration、热点和 WAIT。

通过条件：每个保留信号有支持例、反例、成本和适用范围。

### E4：在线 tie-break 与 margin

- 先 B2，再 B3；
- 冻结最小有用 margin，不直接做加权大网格。

通过条件：validation 上报告净收益和最坏退化，配置在进入真实图前冻结。

### E5：不可抢占风险与一步反事实

- 完成 duration/cross-event/hotspot/next-barrier 消融；
- 运行 B5 并记录完整成本。

通过条件：明确静态 barrier 修正与完整动作反事实各自贡献。

### E6：多资源与 rollout 触发

- 先旧多资源小图；
- Stage 4d 可用时接 barrier trigger，否则只做 B7。

通过条件：active reservation、集合并集和调用率公平对照通过。

### E7：真实小图冻结验证

- 运行 30 个 Stage 4a 小图；
- 不返调配置；
- 按 source group 报告。

通过条件：形成可迁移、只限 tie-break/trigger、无收益或证据不足判断。

### E8：中图有限检查

- 使用固定闸门和极少数配置；
- 超时不追加预算。

通过条件：给出真实中图完整率、成本和停止原因，不要求强行跑完。

## 17. 退出条件

只有同时满足以下条件，Stage 4e 才可结束：

1. barrier、last-missing、slack 和层级由 DAG/residual state 定义，不依赖不稳定命名；
2. state exact、transition exact、structural exact、heuristic estimate 和 source metadata 明确区分；
3. 单 channel FLOW、optional WAIT、多资源 START(set) 和 active reservation 全部复用不可抢占模拟器；
4. immediate release、reachable descendants 和 shared-downstream union 含义及测试正确；
5. barrier-only 只作诊断，LT tie-break、有界修正、一步反事实和 trigger 可分别消融；
6. 小图 Exact 说明局部 barrier、最优首动作和最终 makespan 的关系；
7. 当前 barrier 提前但后续 barrier/makespan 退化的反例被保留；
8. optional-idle 与 work-conserving 的动作、WAIT、Exact 和收益分组报告；
9. barrier trigger 的贡献与 rollout evaluator 本身的贡献分开；
10. 旧 benchmark、受控压力图、Stage 4a 真实小图和中图分别报告；
11. 冻结真实验证包含净收益、完整率、成本和最坏退化；
12. 中图 timeout/not_run_budget_gate 未被排除或通过追加预算隐藏；
13. 明确 barrier 最终是 tie-break、有限修正、初筛、trigger、诊断指标或否定方向。

如果 barrier 只能降低 rollout 调用成本，就按成本控制层结项；如果只在真并列时安全有用，就保留为 tie-break；如果只解释 LT 失败而不能稳定改进，就保留为诊断工具；如果真实 holdout 无稳定收益或成本不值得，则不进入未来综合算法。
