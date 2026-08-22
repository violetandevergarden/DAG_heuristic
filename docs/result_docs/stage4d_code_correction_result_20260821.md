# Stage 4d Selective Rollout 代码修复完整结果（2026-08-21）

## 1. 修复结论

本轮按照 `stage4d_code_review_correction_plan_20260821.md` 修正了 selective rollout 的核心执行契约，并以新的 `stage4d-selective-rollout-v2` 实验链路重新验证。代码层已经关闭审查中最关键的错误：深度 0 不再搜索、候选宽度真实生效、触发特征不再人为制造分歧或受第三候选污染、缓存键包含历史相关输入、completion/展开预算采用原子预留、未完成评价不参与比较、多资源候选复用 Stage 4c 的合法极大集合。

工程结论与算法结论需要分开：代码契约已经可审计，但真实中图的 completion evaluator 在冻结时间预算内没有完成任何一次完整候选比较。因此，本轮修复不等于 selective rollout 已经成为有效的大图算法；它只说明实现错误已被关闭，失败和回退现在能够被准确记录。

## 2. 修改范围与未修改边界

本轮修改集中在以下模块：

- `src/llm_structured/selective_rollout.py`：公共预算、候选、特征、触发和评价结果契约；
- `src/single_channel/complex_chain/preemptive/selective_rollout.py`：单通道候选生成、触发特征、宽深搜索和调度循环；
- `src/single_channel/complex_chain/preemptive/solver.py`：任意公共状态上的未压缩 Exact 后缀；
- `src/muti_channel/preemptive/selective_rollout.py`：固定多资源 selective rollout；
- `src/core/execution/preemptive.py` 与 `src/muti_channel/preemptive/solver.py`：结果统计字段；
- `experiments/llm_structure/selective_rollout_evaluation.py`：Stage 4d v2 标签、对照、硬超时和增量输出；
- Stage 4d 定向测试文件。

没有修改 DAG finish-to-start 依赖、compute 自动且不可抢占、communication 暂停/恢复、固定资源集合、无主动等待等公共语义；没有修改旧不可抢占实现，也没有让算法自行推进另一套时间状态。

## 3. P0 修复：深度和候选宽度

### 3.1 深度的正式定义

旧实现把 `rollout_depth <= 1` 都送入深度一评价，导致 depth 0 仍执行两次 completion。新接口使用 `RolloutBudget.search_depth`，定义如下：

- `search_depth=0`：关闭 rollout，直接返回 LT 调度，completion call 为 0；
- `search_depth=1`：对各首动作执行一次公共模拟器转移，再用相同 LT terminal evaluator 完成；
- `search_depth=2`：首动作后在下一个通信决策层继续按候选宽度分支，再进入 LT terminal evaluator；
- terminal completion 不计入搜索深度，但其每次模拟转移计入 expansion。

因此当前 depth 是真实的“分支通信决策层数”，不再是旧实现中仅沿 LT 延长的固定前缀。结果记录实际达到的 `max_actual_depth`。

### 3.2 候选生成器

单通道候选生成器返回稳定、去重且有来源的动作列表：

1. residual LT 首选，始终作为 baseline；
2. LRPT 的真实首选；
3. FIFO 的真实首选；
4. join-aware 的真实首选；
5. 若仍未达到宽度，则按 LT 排名补入其他 eligible communication。

`max_candidates=0/1/2/4` 分别得到 0/1/至多 2/至多 4 个真实候选。候选结果保存可用动作数、保留数、来源、是否截断和截断原因。`max_candidates<2` 与 depth 0 一样直接执行 LT，不把“只有 baseline”记成完成过 rollout。

固定多资源实现调用 Stage 4c 的 `multi_seed` 构造器，以 LT 极大兼容集合作为 baseline，候选仍由公共多资源模拟器验证 eligible、资源兼容和 inclusion-maximal。算法不能返回非极大集合以主动闲置资源。

### 3.3 四层职责分离

实现现在明确区分：

- baseline：从当前 residual state 产生 LT 动作；
- candidate generator：仅产生候选并记录来源，不决定最终执行动作；
- trigger：仅根据当前特征判断是否分配搜索预算；
- evaluator：只对完整候选树估值并返回 selected、各候选值、完整状态和失败原因。

未触发、候选不足、预算拒绝和完整评价后持平在统计中是不同事件。

## 4. P0 修复：共享预算和安全采用

### 4.1 原子预算账户

`BudgetAccount` 统一维护：

- 接受的 trigger positives；
- 完整 rollout evaluations；
- budget-rejected triggers；
- completion calls；
- expanded states/events；
- generated/evaluated candidates；
- 实际最大深度；
- 首次及累计预算原因。

每个候选 completion 启动前调用 `try_reserve_completion`；每次公共模型转移前调用 `try_expand`。若下一个操作会超过上限，操作不会发生，计数保持在上限以内。最终实验数据再次检查了所有 completed 行，没有发现 completion 或 expansion 越界。

### 4.2 时间边界

搜索内部采用协作式检查：

- 每个决策 1 秒；
- 整图搜索时间 8 秒；
- 最多 16 次接受触发；
- 最多 32 次 completion；
- 最多 100,000 次 expansion。

协作式检查不能保证杀死不可中断的 Python 过程，因此真实实验额外使用父进程 35 秒硬墙钟。父进程终止后结果只记录 `timeout` 和实际墙钟，不保存 makespan、不声称 trace 完成，也不以 LT 结果填充候选算法行。

### 4.3 不完整评价回退

评价器只有在当前触发的全部候选树完整时才比较值。任一分支出现 completion、expansion、单决策时间或整图搜索时间不足，整次评价标为不完整，当前决策执行 LT。候选仅在完整值严格小于 baseline 值时采用；并列稳定保留 LT。

真实中图验证了该契约：1536 和 2204 节点图的端到端 selective 调度能够完成，但冻结预算内完整 rollout evaluation 数均为 0，所有候选决策都安全回退到 LT。结果没有把这些回退误记为“候选与 LT 持平”。

## 5. P0 修复：特征和缓存

### 5.1 启发式分歧

旧代码先在 LRPT 排名中寻找一个不同于 LT 的任务，因此只要有第二个任务就容易把“候选不同”误写成“策略首选分歧”。v2 分别完整计算 LT 和 LRPT 排序，只有两者第一名不同才设置 `heuristic_disagreement=True`，并保存 `lt_action`、`lrpt_action`、`fifo_action` 及对应 tail 信息。

### 5.2 候选绑定的释放和 join 信号

旧 `any(... for item in eligible)` 会让第三个、未被比较的通信污染 LT/challenger 特征。v2 分别记录：

- baseline/challenger 的立即 compute release；
- 两者 release 差值；
- baseline/challenger 是否为 join 的最后未完成前驱；
- 两者 join 影响是否不同。

触发器使用的是被比较动作之间的差异，全局是否存在某类任务不再冒充候选因果信号。

### 5.3 eligible delta 和缓存

原字段 `ready_set_delta` 实际表示新增 eligible communication 数，现更名为 `eligible_comm_delta`。特征缓存键由“规范化当前状态 + 特征版本”扩展为“规范化当前状态 + `single-channel-selective-v2` + previous eligible 稳定摘要”。同一当前状态由不同 previous eligible 集合到达时不会错误复用历史相关特征。

## 6. P1 修复：Exact 标签和错误归因

新增 `exact_completion_from_state_uncompressed(model, state, ...)`：

- 输入是公共模拟器的任意稳定状态；
- 对该状态的所有合法动作继续使用公共 `step`；
- key 保留绝对时间、全部 runtime 字段和 last communication；
- 完成枚举才标 `optimal`；
- time/state limit 返回 `feasible` 和明确 termination reason，不生成伪最优标签。

Stage 4d runner 沿 LT 访问路径收集每个实际选择状态，对每个合法首动作执行未压缩 Exact 后缀，输出 action value、并列最优集合和状态 hash。标签分为 positive、negative、equivalent、unknown；本轮没有观察到被归为 equivalent 的状态，14 个不完整状态全部保留为 unknown。

结果分别计算：

- 触发错误：false positive、false negative 及漏掉的 makespan 改善；
- 候选错误：最优首动作是否进入宽度 2/4 候选；
- 评价错误：最优动作已进入候选后，深度一/二 evaluator 是否选中。

## 7. P2 修复：实验协议和结果契约

新 runner 的 schema 为 `stage4d-selective-rollout-v2`。每行保存：

- benchmark ID、内容 hash、task/communication 数、来源和划分；
- 特征版本、trigger、width、depth、seed 和完整预算；
- makespan、状态、硬超时、trace validity/hash；
- 触发、候选、completion、expansion、实际深度和 fallback 明细；
- choice gate、特征、候选生成、completion 和总 wall-clock；
- preemption、communication intervals、forced idle 和 channel utilization；
- 代表性 `tracemalloc` 峰值内存与测量范围；
- Python 和平台信息。

输出采用增量写入，长实验中断时不会丢失已经完成的方法。两张 2680 节点图停止新增实验后，runner 支持在不覆盖已完成行的情况下追加 2204 节点替代 holdout，并记录划分调整原因。

旧 `stage4e-selective-evaluation-v1` 的 45-case 数字保持 legacy，不与 v2 标签和结论混合。

## 8. 测试与验证

新增/更新的 Stage 4d 测试共覆盖以下关键行为：

| 类别 | 回归点 |
| --- | --- |
| 深度 | depth 0 零调用；depth 1/2 实际深度和展开差异 |
| 宽度 | `max_candidates=0/1/2/4` 的真实保留数 |
| 预算 | completion/expansion 恰好用尽后拒绝，计数不越界 |
| 回退 | 零触发、零 completion、expansion 不足时 trace 与纯 LT 一致 |
| 特征 | LT/LRPT 首选相同不报分歧；第三候选不污染 release |
| 缓存 | previous eligible 不同产生不同 cache key |
| 选择 | 候选估值并列稳定保留 LT |
| Exact | 每个合法首动作都获得未压缩 Exact 后缀值 |
| forced idle | 仅 eligible 为空时使用公共 WAIT 兼容动作 |
| 多资源 | 候选均为合法极大集合；预算不足回退 LT |

完整测试结果：`189 passed in 128.48s`。`git diff --check` 除 Windows 下 LF/CRLF 转换提示外无空白错误。

## 9. 审查问题关闭情况

| 审查问题 | 状态 | 证据 |
| --- | --- | --- |
| depth 0 实际执行 depth 1 | 已关闭 | depth 0 返回纯 LT、零 completion 测试 |
| max_candidates 不生效 | 已关闭 | 0/1/2/4 候选数量测试和结果字段 |
| 人为制造 heuristic disagreement | 已关闭 | 比较 LT/LRPT 真实首选 |
| release/join 被第三候选污染 | 已关闭 | 逐候选字段和污染反例 |
| ready_set_delta 命名错误 | 已关闭 | 更名 `eligible_comm_delta` |
| 缓存遗漏历史量 | 已关闭 | previous eligible 摘要进入 key |
| completion/展开预算越界 | 已关闭 | 原子预留、逐转移检查、实验审计 |
| 触发数与完成评价混用 | 已关闭 | trigger/complete/rejected 三类计数 |
| depth 不是搜索树深度 | 已关闭 | 通信决策层分支搜索 |
| 多资源未复用公共契约 | 已关闭（代码层） | Stage 4c 极大集合 + 公共多资源模型测试 |
| forced idle 表示为 WAIT | 兼容边界 | 仍由公共单通道 API 表示，但有 eligible 时绝不选择 |
| runner 阶段编号和 schema 旧 | 已关闭 | Stage 4d v2 runner/result |
| 无决策级标签和错误归因 | 已关闭 | 181 个状态及 trigger/candidate/evaluator 分离 |
| 无真实 bounded holdout | 已关闭但证据受限 | 2204 节点替代 holdout 完整回放；rollout 评价均未完成 |

## 10. 再验收判断

代码语义、接口、预算、标签、对照和失败记录已经达到可审计状态。需要特别区分两种“完成”：

- 工程修正完成：配置和统计真实、动作合法、预算不越界、失败会回退或标 timeout；
- 算法成功未达到：真实中图没有一次完整 rollout evaluation，更没有同预算净收益。

因此 Stage 4d 可以以“修正完成、算法受限/否定”退出，但不能以“已验证 selective rollout 组件”进入 Stage 4g。

## 11. 产物

- [最终实验数据](/D:/Code/SimAI/DAG_heuristic/docs/result_docs/stage4d_selective_rollout_final_20260821.json)
- [Stage 4d 冻结清单](/D:/Code/SimAI/DAG_heuristic/docs/result_docs/stage4d_manifest_v2_20260821.jsonl)
- [算法研究完整结果](/D:/Code/SimAI/DAG_heuristic/docs/result_docs/stage4d_algorithm_research_result_20260821.md)

中断过程数据 `stage4d_selective_rollout_evaluation_v2_20260821.json` 仅用于追溯实验追加过程；正式引用以最终实验数据为准。
