# Stage 4e Barrier 感知调度代码审查

## 1. 审查范围与总体结论

本审查依据 `docs/plan_docs/stage4_LLM_search.md` 和 `docs/plan_docs/stage4e_barrier_scheduling.md`，检查 barrier 的结构定义、剩余状态特征、单通道和固定多资源策略、测试、实验入口及当前证据。`docs/old_docs/stage4研究` 中的记录仅用于复核历史问题，不作为当前正确性的来源。

总体判断：**现有 Stage 4e 已形成可运行的 barrier 特征与受控实验骨架，但没有满足正式阶段要求。** 可以保留公共模拟器衔接、直接 last-missing、立即 compute 释放、共享下游去重的部分实现和 motif 回归；但若干特征名称与实际含义不一致，完整双日程 safeguard 使用部署时不可获得的事后信息，真实 census、决策级因果标签、条件修正、统一消融和 holdout 均未完成。因此当前状态应为“特征原型和诊断工具可用，在线算法与真实结论未验收”。

本次未修改代码、benchmark 或实验结果，只新增审查和修正建议文档。

## 2. 检查对象与验证结果

主要检查：

- `src/llm_structured/barrier.py`
- `src/single_channel/complex_chain/preemptive/solver.py`
- `src/muti_channel/preemptive/solver.py`
- `experiments/llm_structure/barrier_evaluation.py`
- `experiments/llm_structure/barrier_continuation.py`
- `experiments/llm_structure/barrier_motif_evaluation.py`
- `benchmark_generate/llm/barrier_motifs.py`
- 单通道、多资源和 barrier 特征测试
- Stage 4a manifest 与旧 Stage 4e 研究记录

验证结果：

- barrier 定向测试：12 passed；
- 完整测试：175 passed，耗时 132.03 秒；
- 受控 motif 的 Exact 与 trace 检查通过；
- 在当前多资源 motif 的两个合法极大动作上，`packing_complementarity` 都为 0；
- 当前 `docs/result_docs` 中没有可作为 Stage 4e 正式 holdout 证据的冻结结果目录。

测试通过说明现有受测路径稳定，不证明特征含义、在线信息边界或真实收益符合新分纲。

## 3. 已基本满足的部分

### 3.1 公共模拟器和动作合法性

barrier 模块只读取状态，不直接推进时间。单通道策略通过 `PreemptiveDAGModel.step` 执行动作；多资源集合评分先检查 eligible、资源兼容和包含极大性。相关 trace 使用公共 validator，未发现 barrier 模块自行修改依赖、剩余工作或资源占用。

### 3.2 基础 residual 特征

`remaining_work` 使用运行时剩余量，已完成任务计为 0；tail 根据当前状态重新计算。结构判断不依赖任务名称，`label_hint` 只作为标签提示，当前主要排序没有用它改变结构结果。特征快照也为估计量和部分结构量保存了 `quantity_modes`。

### 3.3 直接 last-missing 和立即释放

`_last_missing_joins` 能识别候选是直接多前驱 child 的最后未完成前驱；`_immediate_compute_release` 在假设候选完成后处理零时长 compute 闭包，再统计新满足依赖的 compute。这两个定义范围有限，但在直接 join 小图上可手工核对。

### 3.4 多资源下游并集

`action_features` 先对整个动作求后代并集，因此 `shared_downstream_count` 能揭示逐通信累加的重复。`score_sets` 只接受合法极大集合，符合 Stage 4c 的基本动作边界。

### 3.5 受控 motif 与 Exact 骨架

单通道和多资源 motif 具有 Exact 状态标签，测试区分 optimal 与 feasible。barrier-only、tail、tail+barrier 等模式可作为诊断消融入口继续使用，但目前的 motif 不能证明真实 LLM 频率或收益。

## 4. 特征定义和实现问题

### 4.1 “可达 compute”不是“可释放 compute”

`reachable_compute_release` 汇总候选全部未完成 compute 后代的剩余工作，不要求候选完成后这些 compute 立即或确定地 ready。它是“可达后代 compute 总量”，不是释放量。`compatible_completion_gain` 又把 `immediate_compute_release` 加到该值上，而立即释放的 compute 本来就在后代集合中，存在重复计分。

多资源 `union_released_compute` 同样统计所选动作全部未完成 compute 后代，而不是动作完成后新增 ready 的 compute。该字段在 `_barrier_set_score` 中处于第一排序位，会把结构规模误当作实际释放收益。

### 4.2 `last_missing_join` 只覆盖直接 child

`_last_missing_joins` 只检查候选的直接后继是否是多前驱 join。经自动 compute 链后到达的间接 barrier、首次汇合、嵌套 barrier 和 iteration 末端层级没有表示。当前字段名称容易被理解成一般 last-missing，应限定为 `direct_last_missing_join` 或增加明确的有界 barrier 链分析。

### 4.3 arrival spread 的方向不符合到达时间含义

`_arrival_spread` 对 join 的每个 dependency 使用 `context.tails[dependency]`。tail 表示该依赖到最终下游的最长剩余路径，不是该分支“到达当前 join”的剩余时间。它可以作为某种下游结构差异估计，但不能解释成 barrier 分支到达跨度，也不能用于证明某分支最晚到达。

### 4.4 paused tail penalty 没有读取暂停通信

单通道 `build_context` 将 `active` 设置为 `active_computes(state)`；多资源分支则为空。`paused_tail_penalty` 随后从这个集合计算并排除候选。因此它实际上读取运行 compute 的 tail，或在多资源中恒为空，没有比较“继续当前通信”和“暂停当前通信”。字段含义与实现不一致。

### 4.5 特征证据等级过强

`residual_tail`、`reachable_compute_release`、`downstream_join_tail`、`compatible_completion_gain` 和 `exclusive_tail` 被标为 `structural_exact`。这些量至多是“按当前实现定义可精确计算的结构量”，并不精确表示 barrier 到达、资源竞争后的完成时间或 makespan 收益。尤其 `compatible_completion_gain` 名称带有收益含义，容易被误读为因果标签。

### 4.6 `packing_complementarity` 对极大动作恒为零

该字段统计未选 eligible 通信中与已占资源不相交的数量。若动作已经 inclusion-maximal，就不存在还能加入的兼容通信，因此该值必为 0。本次在多资源 motif 的两个合法极大动作上均复现为 0。它仍被 `_barrier_set_score` 使用，既没有区分力，也会掩盖集合互补尚未被正确定义的问题。

### 4.7 barrier 层级和去重定义不完整

当前只按直接 join 集合去重；没有最近 barrier、全局 barrier、iteration barrier、共享 barrier 层级和筛选预算。`global_last_missing_count` 通过 residual sinks 包含关系分类，不能替代训练语义中的全局同步定义，也没有真实 workload 对拍。

### 4.8 immediate release 只返回总 duration

实现不保存具体新增 ready 节点、零时长闭包路径或释放后的 barrier 标识，实验无法核对是否重复、是否属于目标 barrier，也无法报告“barrier 提前但 makespan 不变”的因果链。

## 5. 策略和信息边界问题

### 5.1 完整双日程 safeguard 不是在线算法

`schedule_barrier_safeguarded` 完整运行 LT 和 barrier candidate，再按最终 makespan 返回较短结果；多资源版本也完整运行 LT packing 与 barrier set policy。它使用整条备选日程的事后结果，天然保证不差于两者中的较好者，但部署时无法在一次在线调度中免费获得该信息。

这类函数只能标为“离线二选一上界”，运行成本应包含两次完整回放。当前它们仍出现在单通道和多资源公开 interface 的算法列表中，名称又是 `safeguarded`，存在被误用为在线保护策略的高风险。

### 5.2 缺少正式初筛方法

计划要求研究 LT 前的候选初筛并统计误删最佳动作。当前没有独立 filter 接口、被过滤候选日志或错误过滤率。`trigger` 只决定当前已选 barrier candidate 是否回退 LT，不是对候选集合进行可审计初筛。

### 5.3 条件修正只覆盖严格 tail 词典序平局

`tail_barrier` 把 exclusive tail 放在第一排序位，barrier 只在 tail 完全相同后打破平局。这是一种安全的精确 tie-break 雏形，但没有实现“归一化 LT margin 小于阈值时有限修正”，也没有阈值、敏感性和 holdout 冻结。

### 5.4 barrier-only 仍作为在线候选广泛运行

barrier-only 可作为诊断对照保留，但正式真实 runner 把它作为 `barrier_candidate` 与 LT并列汇总。它没有明确标成诊断失败基线，容易把少量胜场解释为推荐算法。当前 Stage 4 总纲已经规定 barrier 不应替代 LT。

### 5.5 selective barrier rollout 混合了 barrier 与额外搜索

在线 selective 版本用 barrier-only 产生 challenger，再对 LT 与 challenger 分别做完整 LT completion。若改善，收益同时来自候选信号和额外前瞻，不能归因于 barrier 本身。当前实验缺少相同调用率随机/周期触发和无 barrier 候选对照。

### 5.6 selective 时间预算仍是软门槛

`time_limit_s` 只在触发前检查；一旦开始，两次完整 LT completion 可远超限制。没有 completion call、展开、内存和进程级墙钟上限。该问题在单通道和多资源版本都存在。

### 5.7 抢占条件没有显式建模

策略没有明确比较当前暂停通信的剩余工作、切换是否发生及其对 barrier 窗口的影响。虽然模型设定零切换开销，频繁切换仍可能改变后续释放和执行区间；当前只在最终结果中统计 preemptions，没有形成条件规则或失败分析。

## 6. 实验与证据缺口

### 6.1 Stage 4a 输入筛选仍不严格

`barrier_evaluation.py` 已能读取 Stage 4a manifest、保存 manifest hash、代码 revision 并按模型、topology、DP 和 contention 分组，这是比旧 runner 更好的基础。但它仍依赖单一顶层 `status`，接受 sampled-prefix/旧状态，没有独立验证转换、竞争、发布状态，也没有只选择 barrier 信号和策略分歧明确的正式质量集。

### 6.2 没有开发/验证/holdout 划分

真实 runner 按 manifest 顺序和 `limit/max_tasks` 选样例，没有冻结 workload/topology holdout。阈值、规则、motif 和最终报告边界没有机器可读清单，无法判断结构泄漏。

### 6.3 基线和三类加强不齐

正式 runner 只比较 LT、barrier-only candidate 和 barrier selective rollout。缺 FIFO、固定顺序、LT 初筛、margin 条件修正、纯 tie-break、相同调用率随机/周期 rollout。`barrier_continuation.py` 虽包含更多旧策略，但使用旧 benchmark 集和离线 safeguard，不能合并成正式统一对照。

### 6.4 缺少 barrier 时间标签

Exact motif 只保存最终 makespan，没有逐决策全部首动作、目标 barrier ready/complete 时间、后续 barrier 时间及局部提前与全局变化的对应关系。因此无法回答“barrier 提前是否导致 makespan 改善”。

### 6.5 缺少真实 census

没有按完整回放、sampled prefix、真实切片分别统计 barrier 类型、层级、last-missing、LT 分歧、动作后 barrier 时间变化和最终 makespan变化。不能从现有 runner 推出 barrier 在真实 72-case corpus 中的频率或价值。

### 6.6 成本和失败状态不完整

真实 runner 记录总 runtime、部分利用率和 fallback，但没有 context/单候选/整集合特征分项、访问节点边数、缓存、峰值内存和严格 timeout。异常被保存为 error 是合理的，但没有进程级超时，超大图仍可能阻塞整个运行。

### 6.7 历史结果的适用范围有限

旧记录中的 45 个单通道样例、9 个 motif 和 22 个多资源样例可以作为开发背景。barrier-only/原始 union 的退化是重要负面证据；完整 safeguard 不退化是由事后选择直接保证；带 rollout 的改善主要证明前瞻有价值。它们都不能证明真实 holdout 上 barrier 信息有独立净收益。

## 7. 对十五项退出条件的判断

| 退出条件 | 判断 | 主要依据 |
|---|---|---|
| 1. barrier、residual、last-missing 和层级定义明确 | 部分满足 | 直接 join 有定义；间接、层级和训练语义未完成 |
| 2. 精确特征来自 residual，估计单列 | 部分满足 | remaining 正确；多个名称和证据等级过强或含义错误 |
| 3. 单/多资源动作服从公共契约 | 基本满足 | 公共 step 与极大集合校验已用；forced-idle 历史表示仍存在 |
| 4. 小图验证局部 barrier 与 makespan 关系 | 部分满足 | 有 motif Exact 最终值；缺首动作和 barrier 时间标签 |
| 5. 正式真实输入按证据和规模分层 | 未满足 | 有 manifest runner，但准入与固定分层不足 |
| 6. 完整统一基线与三类加强对照 | 未满足 | 正式 runner 只有三种方法 |
| 7. 初筛、修正、tie-break、trigger 消融 | 未满足 | 各入口零散且信息/预算不一致 |
| 8. barrier 提前与 makespan 不一致均报告 | 未满足 | 没有 barrier ready/complete 时间 |
| 9. 主要失败模式有反例 | 部分满足 | motif 有部分负例，缺共享、slack、远端、抢占和成本系统分析 |
| 10. 真实 workload/topology holdout | 未满足 | 没有冻结划分和最终报告 |
| 11. wall-clock、内存、超时和 fallback 完整 | 未满足 | 有部分 runtime/fallback，无硬超时、内存和特征分项 |
| 12. 明确适用范围 | 未满足 | 缺真实因果和分层证据 |
| 13. 等质量低成本结论 | 未满足 | 没有正式初筛成本实验 |
| 14. 无稳定收益时形成受限/否定结论 | 部分满足 | 总纲有谨慎背景，尚无新协议下的结论实验 |
| 15. 同预算真实净收益才进入 Stage 4g | 未满足 | 当前没有合格组件 |

第 3 项接近实现层面的基本满足；第 1、2、4、9、14 项仅部分满足；其余未满足。Stage 4e 不能结束。

## 8. 可保留与不可引用的结论

可以保留：

- barrier 特征只读 residual state 并复用公共模拟器的总体架构；
- 直接 child join 的 last-missing 和零时长闭包后的立即 compute 释放；
- 多资源合法极大动作及共享后代并集的基本检查；
- barrier-only 作为诊断和反例基线；
- barrier 信息目前证据较弱，应只作为 LT 条件特征、筛选或 rollout 触发的研究方向；
- 旧原始策略退化和 motif 无稳定胜场的负面观察。

不能引用：

- `reachable_compute_release`、`union_released_compute` 或 `compatible_completion_gain` 是真实释放收益；
- 当前 arrival spread 表示分支到达 barrier 的时间差；
- `packing_complementarity` 能区分合法极大动作；
- 完整 schedule safeguard 是可部署在线算法或低成本保护；
- barrier selective rollout 的全部收益来自 barrier 信号；
- 现有真实 runner 已完成统一预算、holdout 和完整成本验证；
- Stage 4e 组件可以进入 Stage 4g。

## 9. 最终结论

当前 Stage 4e 应记录为：**直接 barrier 特征和受控回归骨架已建立；特征语义、在线策略边界和正式证据链未完成。** 优先修正释放量、arrival/slack、暂停通信和多资源恒定字段，隔离离线 safeguard；随后建立 barrier 时间与首动作标签、真实 census 和统一消融；最后才在冻结 holdout 上判断 barrier 应作为 tie-break、过滤器、rollout trigger，还是仅保留为诊断信息。
