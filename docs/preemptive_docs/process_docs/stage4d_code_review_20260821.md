# Stage 4d Selective Rollout 代码审查

> 2026-08-22 口径更新：全量真实 LLM DAG 不再是主实验或退出条件，改用 Stage 1--3 旧 benchmark、100--1000 节点冻结验证和 1--2 个中大图逐例检查。

## 1. 审查范围与总体结论

本审查依据 `docs/plan_docs/stage4_LLM_search.md` 和 `docs/plan_docs/stage4d_selective_rollout.md`，检查当前 selective rollout 的公共契约、单通道实现、多资源相关实现、测试、实验入口和证据。`docs/old_docs/stage4研究` 中的历史材料仅用于定位旧问题，不替代当前代码检查。

总体判断：**当前 Stage 4d 是能够运行并安全保留 Longest Tail 的单通道研究原型，但不满足正式阶段要求，不能作为已验证组件进入 Stage 4g。** 现有代码完成了基础触发接口、部分剩余状态特征、调用/展开计数和合法轨迹回退；候选宽度、深度、触发语义、缓存、严格预算、决策级标签、Stage 1--3 主实验、100--1000 节点冻结验证和等预算实验均未完成。

2026-08-18 旧审查列出的核心问题在当前代码中仍可复现。本次仅新增审查文档，没有修改代码、benchmark 或实验结果。

## 2. 检查对象与验证结果

主要检查文件：

- `src/llm_structured/selective_rollout.py`
- `src/single_channel/complex_chain/preemptive/selective_rollout.py`
- `src/muti_channel/preemptive/solver.py` 中的 barrier selective rollout
- `experiments/llm_structure/selective_rollout_evaluation.py`
- `tests/llm_structured/test_selective_rollout_features.py`
- `tests/single_channel/complex_chain/preemptive/test_selective_rollout.py`
- 现有 45 个 complex-chain benchmark、Stage 1--3 数据入口、Stage 4a 少量迁移样例边界和旧 Stage 4 记录

实际验证：

- selective rollout 定向测试：7 passed；
- 完整测试：175 passed，耗时 130.48 秒；
- 最小复现中配置 `rollout_depth=0`，结果仍触发 1 次 rollout、执行 2 次 completion call，makespan 为 11；
- runner 默认数据集包含 45 个旧单通道 complex-chain 样例；
- 当前 `docs/result_docs` 中没有可作为正式 Stage 4d 结果的冻结目录。

完整测试通过说明现有接口没有被回归测试否定，不说明实现符合新分纲中的研究契约。

## 3. 已基本满足的部分

### 3.1 复用公共模拟器

单通道实现使用 `PreemptiveDAGModel.step` 生成 rollout 分支和最终轨迹，没有自行释放依赖或推进通信剩余工作。最终动作由公共模拟器执行，测试也使用公共 trace validator。多资源 barrier 版本同样调用公共固定资源模型。

### 3.2 Longest Tail 安全基线

未触发、候选非法、候选不严格更优或部分预算不足时，单通道实现选择 Longest Tail。比较值相同时稳定保留 LT，避免无收益地改变动作。零触发和零 completion 预算已有回归测试，并能得到与 LT 相同的轨迹。

### 3.3 初步接口分层

共享模块定义了 `RolloutBudget`、`TriggerFeatures`、`TriggerDecision`、`EvaluationOutcome` 和 `BudgetAccount`；单通道模块分出 choice gate、特征、候选评价和调度循环。结果中已有触发数、completion calls、展开数、fallback 和部分耗时字段。这是后续修正可以保留的骨架。

### 3.4 部分剩余状态特征

LT tail、当前通信剩余量和 eligible 集合从当前模拟状态计算，没有读取 benchmark metadata 或 reference result。缓存开关测试证明当前简单样例中开关缓存不改变动作，但尚不能证明缓存键在一般路径上安全。

## 4. 实现不满足要求的问题

### 4.1 深度 0 实际执行深度 1

`evaluate_rollout` 对 `depth <= 1` 一律调用 `evaluate_depth1`。因此 `rollout_depth=0` 不是“关闭 rollout”，而是进行两次完整 LT completion。最小复现已确认 depth 0 产生 2 次 completion call。配置、统计和实验标签不真实。

### 4.2 候选宽度参数没有真实生效

`max_candidates < 2` 时整图回退 LT，但大于 2 的任何值都没有改变行为。`cheap_features` 只保留一个 challenger，评价器始终只比较 LT 与该 challenger。计划要求的宽度比较、候选召回率和“节省预算用于更宽搜索”尚无实现基础。

### 4.3 “启发式分歧”不是两个策略的首选分歧

challenger 被定义为 LRPT 排序中第一个不同于 LT 的任务；找不到时再从 join-aware 排序中取不同任务。只要能找到不同任务，`heuristic_disagreement=bool(challenger and challenger != lt)` 就为真。这没有比较两个完整启发式各自的首选，因此会把“人为挑了不同候选”误写为“策略发生分歧”。

### 4.4 释放和 join 信号会被无关候选污染

`immediate_compute_release` 和 `last_missing_join` 使用 `any(... for item in eligible)`。第三个未参与 LT/challenger 比较的通信满足条件时，也会让当前二候选评价触发。触发原因不能归因于被比较动作，precision 和误触发分析会失真。

### 4.5 `ready_set_delta` 名称与实际含义不符

调度器传入的是“当前 eligible communication 相对上一决策新增的数量”，不是 ready task 集合变化。文档、字段名和实际数据含义不一致，容易把通信资格变化误解释为 compute 或全部任务 ready 变化。

### 4.6 缓存键遗漏影响特征的历史量

缓存键只有归一化状态和特征版本，但缓存值包含由 `previous_eligible` 计算的 `ready_set_delta`。相同归一化状态若从不同前序 eligible 集合到达，可能错误复用历史相关特征。现有缓存测试只覆盖一张简单 DAG 的端到端一致性，没有构造此反例。

### 4.7 时间预算不是硬边界

总时间只在进入触发逻辑前检查；单决策时间在完整计算 LT completion 后才再次检查。底层 `_complete_actions` 不能在事件或展开过程中接收截止时间，一次调用可能远超预算。挑战者 completion 完成后也没有再次检查单决策或总时间。`total_time_limit_s` 因而只是下一次触发前的软门槛，不是整图墙钟上限。

### 4.8 展开预算可能被突破

代码在 LT completion 后累计展开数并检查 `>` 上限；挑战者 completion 后继续累计，却不再检查是否超限。因此最终 `expanded_nodes` 可以超过配置，仍返回正常比较结果。即使第一条分支已耗尽预算，也只能在完成整个分支后发现。

### 4.9 触发数与成功评价混在一起

`account.triggers` 在调用评价器前递增。随后若 completion、展开或时间预算不足，该次仍计为触发，但没有单独的“触发后成功完整评价”计数。正式报告无法区分触发器行为、预算拒绝和实际 rollout 次数。

### 4.10 当前“深度”不是通用搜索树深度

depth 大于 1 时，每个分支后续动作都由 LT 唯一决定，最后再完整 LT completion；没有在后续层展开多个候选。它是“固定 LT 前缀长度”，不是宽度与深度都可配置的 rollout 树。深度 1 和深度 2仍各使用两次 completion call，但展开事件更多；当前接口不足以进行计划要求的宽度—深度等预算研究。

### 4.11 多资源实现未复用 Stage 4d 公共契约

多资源只有 `schedule_selective_barrier_rollout`，它是 Stage 4e barrier 特定候选：没有使用 `RolloutBudget`、通用 Trigger、ChoiceSummary 或 BudgetAccount，也没有 completion/展开硬上限。其 `time_limit_s` 同样只在触发前检查，两次完整 completion 可能越界。当前不能证明 Stage 4d 对多资源合法动作、候选集合和统一预算具有完整支持。

### 4.12 forced idle 仍表示为 WAIT 动作

单通道 selective 调度器在没有 eligible communication 时显式追加 `Action.wait()`。公共模型只在存在 active compute 时允许它，实际是 forced idle，而非主动等待；但这仍与当前总纲“forced idle 不是调度动作”的目标接口不一致。该问题属于公共单通道模拟器的历史表示债务，Stage 4d 不应自行修另一套推进逻辑，但正式验收前需统一迁移或明确兼容边界。

## 5. 实验与证据缺口

### 5.1 runner 仍使用旧阶段编号

实验模块说明为 Stage 4e，输出 schema 是 `stage4e-selective-evaluation-v1`，与当前正式 Stage 4d 编号不一致。旧结果必须作为 legacy 保存，不能直接作为新阶段证据。

### 5.2 数据没有按新的三层实验口径冻结

runner 默认扫描 45 个 `benchmark/single_channel/complex_chain/preemptive` 样例，这与“先用 Stage 1--3 旧 benchmark”的新方向一致；但同一批数据同时用于多个阈值和最终汇总，没有冻结开发/validation 子集，也没有独立的 100--1000 节点验证集或 1--2 个中大图压力清单。因此缺口不再是“没有跑全量 Stage 4a”，而是旧 benchmark 主实验和后续两层没有形成可复现边界。

### 5.3 缺少决策级标签和触发准确性

runner 只给整图 Exact 和最终 makespan，没有为每个决策保存全部首动作的 Exact 后续值，也没有区分正例、负例和 unknown。因此不能计算 trigger precision、recall、漏触发、误触发及其质量代价。

### 5.4 候选问题与评价问题没有分离

只保存一个 challenger，没有最优首动作是否进入候选、候选召回率、候选已覆盖但评价选错等字段。最终胜负无法归因于触发、候选生成还是 completion 估值。

### 5.5 没有真正的同预算比较

不同触发器共享参数上限，但实际使用的 completion calls、展开数和墙钟不同；节省的预算没有重新分配给更宽候选或更深搜索。没有相同搜索配置比较全量与选择性，也没有相同总预算比较更深/更宽配置。

### 5.6 报告字段不足

缺少输入 hash、代码/模拟器版本、环境、配置快照、触发原因分布、候选数、实际深度、展开数、特征分项耗时、超时状态、峰值内存、抢占、通信区间、forced idle、利用率和最坏退化。fallback 只保存计数，不保存逐决策原因和最后状态。

### 5.7 旧数字只能作为历史观察

旧记录的 45 例中 7 胜、38 平、0 负，以及 134 对 350 completion calls，可保留为 Stage 1--3 开发期观察。但数据同时参与阈值设计和报告，也没有在冻结的 100--1000 节点验证集上复验。因此这些数字不能证明收益能够跨规模或迁移到 LLM 派生小图。

## 6. 对十四项退出条件的判断

| 退出条件 | 判断 | 依据 |
|---|---|---|
| 1. 分支复用公共模拟器且动作合法 | 部分满足 | 单通道和 barrier 多资源使用公共 step；forced-idle 表示和通用多资源支持仍有缺口 |
| 2. LT、候选、触发、预算接口独立明确 | 部分满足 | 有初步类型分层，但宽度、触发统计和预算语义不真实 |
| 3. 小图 Exact/首动作标签且 unknown 分离 | 未满足 | 只有整图 Exact，没有决策级标签 |
| 4. 与 choice-only、随机、周期、全量统一对照 | 部分满足 | 旧 runner 含这些变体，但数据和预算协议未冻结 |
| 5. precision、recall、误触发、漏触发及损失 | 未满足 | 无决策级真值 |
| 6. 候选召回与评价误判分离 | 未满足 | 只有单 challenger，无覆盖率 |
| 7. 深度、宽度、触发和调用同预算比较 | 未满足 | max_candidates 不生效，depth 语义有限 |
| 8. 所有不完整评价回退 LT并完整记录 | 部分满足 | 多数路径回退 LT；时间/展开可越界且状态记录不足 |
| 9. 100--1000 节点冻结验证和有限中大图报告 | 未满足 | 当前 runner 只有未拆分的旧 45-case 数据 |
| 10. 特征和搜索开销纳入 wall-clock | 部分满足 | 总 runtime 包含大部分开销，但无硬上限和完整分项/内存 |
| 11. 计划列出的失败模式有反例 | 未满足 | 缺分差、无关释放、缓存、深度不足和预算不对称的系统反例 |
| 12. 明确适用范围 | 未满足 | 没有跨旧 benchmark、100--1000 节点和有限中大图的证据 |
| 13. 无收益时形成受限/否定结论 | 未满足 | 目前只能判为证据不足 |
| 14. 同预算净收益组件才进入 Stage 4g | 未满足 | 尚无合格配置 |

没有任何一项达到完整验收；第 1、2、4、8、10 项仅部分满足，其余未满足。

## 7. 可保留和不可引用的结论

可以保留：

- 基于公共模拟器的 LT 与单 challenger 完成评估骨架；
- 未触发或不严格改善时保留 LT 的安全原则；
- RolloutBudget、Trigger 和结果统计的初步接口；
- 旧 45-case 上减少 completion calls 且未观察到 makespan 退化的限定观察；
- selective rollout 值得继续验证，但尚未成为正式算法。

不能引用：

- depth 0、候选宽度和时间/展开预算已按配置严格执行；
- `heuristic_disagreement`、释放或 join 信号具有准确语义；
- 触发器已经取得可靠 precision/recall；
- 节省的预算已转化为更深或更宽搜索收益；
- 已在冻结的 100--1000 节点验证集上复现净收益，或能据此外推完整真实 LLM corpus；
- 当前 Stage 4d 可以进入 Stage 4g。

## 8. 最终结论

Stage 4d 当前状态应记录为：**单通道原型可运行，LT 回退骨架可复用；深度、候选、触发特征、缓存和预算契约待修；决策级标签、等预算曲线和冻结验证未开始。** 应先关闭可复现的实现缺陷，再在 Stage 1--3 旧 benchmark 上建立主实验和决策级真值，随后用 100--1000 节点小图冻结验证，最后只用 1--2 个中大图逐例检查可执行性与成本。
