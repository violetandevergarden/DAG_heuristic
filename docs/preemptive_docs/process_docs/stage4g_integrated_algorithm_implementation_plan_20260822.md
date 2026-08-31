# Stage 4g 综合算法具体实现与探索规划

日期：2026-08-22  
性质：基于现有实验结果形成的实施规划，不是已完成算法或收益结论。

## 1. 目的与边界

本文把 `docs/plan_docs/stage4g_integrated_algorithm.md` 转成可以直接执行的代码与实验任务。依据是 Stage 4 总纲、公共模拟器语义，以及 `docs/result_docs/` 中截至 2026-08-22 已完成的 Stage 1--4e 结果。

Stage 4g 当前不应以“把 4c、4d、4e、4f 全部打开”为目标，而应采用“最小有证据组合”：先建立一个可复现、可审计、始终合法的 Longest Tail（LT）综合入口，再让候选组件逐项通过准入门槛。没有独立净收益的组件不进入默认路径。

本规划遵守以下固定边界：

- DAG 为 finish-to-start；compute ready 后自动开始且不可抢占；
- communication 只在公共模拟器允许的离散事件处暂停和恢复；
- 有 eligible communication 时不存在主动 WAIT；
- 多资源动作必须是资源兼容、非空且 inclusion-maximal 的集合；
- 算法只选择动作，不维护第二套时间、依赖、剩余工作量或资源状态；
- 单作业主目标为 makespan；multi-job 的 JCT、slowdown 和公平性单独研究；
- 正式开发与筛选以 Stage 1--3 既有基准为主，冻结验证使用 100--1000 节点的随机、攻击和可追溯 real-derived 图；只用 1--2 个中大图检查逐例成本和安全降级，不要求全量真实 LLM DAG 实验，也不从少量中大图外推总体收益。

## 2. 现有证据对组件的约束

### 2.1 可直接作为综合算法基础的部分

| 组件 | 当前证据 | 4g 处理 |
| --- | --- | --- |
| 单通道 residual LT | Stage 1--2 中明显强于 FIFO 等简单基线；Stage 4a 可完成样例中通常不差于 FIFO | 作为单通道默认动作和所有失败路径的回退 |
| 多资源 LT 贪心极大集合 | Stage 3 公共语义和 Trace 已验证；Stage 4c 最终建议明确保留 | 作为多资源默认动作和回退 |
| 公共模拟器与 Trace | 单/多资源状态转移、抢占、forced idle 和合法性已有回归 | 继续作为唯一执行与验证事实来源 |
| Stage 4c 有界构造合同 | 候选、最终选择、共享预算、流式枚举和回退已拆分 | 只复用接口和审计能力，不默认启用高级选择器 |
| Stage 4d 触发、候选、预算拆分 | 小图上可解释，且不完整评价能安全回退 LT | 复用为实验框架；默认关闭搜索 |
| Stage 4e barrier 特征 | direct last-missing、新释放 compute 和离线审计语义已修正 | 只保留诊断字段，不参与默认选择 |

### 2.2 暂不准入默认算法的部分

1. **Stage 4c 高级 packing 选择器**：简单集合评分在受控反例中有退化，在两张可完成真实单作业图上没有稳定优于 FIFO/LT；深度一完整后续评价两图均在 600 秒超时。因此 `set_score` 和 `depth1_completion` 只保留为实验候选。
2. **Stage 4d 当前中图 rollout**：在 Stage 1--2 的 74 个小图上，完整 w2/d2 Rollout 相对 LT 为 11 胜、63 平、0 负；冻结 Selective 保留 19/20 的已观察改善，并减少 52% completion 调用。这证明机制值得继续研究。但在 1536/2204 节点图上一次候选的完整 LT completion 都不能在预算内完成，所有决策实际回退 LT，所以不能进入 4g 默认在线路径。
3. **Stage 4e barrier 修正**：margin tie-break 在 74 个小图上为 1 胜、65 平、8 负，在 100、300、600、1000 节点冻结图以及 1500 节点成本图上全部差于 LT。direct barrier trigger 也明显弱于 choice-only 和周期对照。因此 barrier-only、margin tie-break 和 direct barrier trigger 均排除；barrier 只作解释和后续候选估值输入。
4. **Stage 4f job-aware 组件**：当前 `result_docs` 没有足以完成目标分离和冻结验证的正式 Stage 4f 结果。multi-job 先作为独立扩展，不进入单作业综合算法，也不在 4g 中顺带调参。
5. **重复结构压缩**：严格独立同构分量的 Exact 对称压缩已有条件性正面结果，但它是求解/分析加速，不等于在线调度策略收益。只有满足同构与资源证书时才用于小图 Oracle 或缓存研究，不改变默认调度动作。

### 2.3 当前应冻结的第一个算法版本

`integrated_v0` 定义如下：

```text
输入：公共 simulator 的当前只读决策状态

若为单通道：
    选择 residual Longest Tail 最大的 eligible communication
    相同分数按稳定 task ID 处理

若为固定多资源：
    按 residual Longest Tail 降序排列 eligible communication
    按顺序贪心加入资源兼容通信
    补全为 inclusion-maximal compatible set

任何可选组件关闭、预算不足、异常或评价不完整：
    返回上述 LT 动作
```

该版本不是新算法收益主张，而是 4g 后续所有增量实验的共同基线和安全落点。

## 3. 目标代码结构

### 3.1 新增综合层，不复制现有求解器

建议新增：

```text
src/llm_structured/integrated/
├── __init__.py
├── config.py       # 版本化配置、模式和预算
├── policy.py       # 单/多资源统一编排，只调用现有动作构造与 simulator
├── decision.py     # 决策输入、组件建议、最终动作和原因
├── accounting.py   # 共享预算、分项计时、fallback 和组件贡献计数
└── safeguards.py   # 合法性、最大集合、输入规模和超时前检查
```

综合层不得导入 `experiments/`、`benchmark_generate/`、reference result 或答案 metadata。它可以调用：

- `single_channel.complex_chain.preemptive` 的 residual LT 基线；
- `muti_channel.preemptive.solver.score_tasks` 与合法极大集合构造；
- `muti_channel.preemptive.constructors` 的有界候选构造；
- `llm_structured.selective_rollout` 的预算和触发合同；
- `llm_structured.barrier` 的只读诊断特征；
- 公共 simulator 的状态转移与 Trace 结果构造。

不要让 `policy.py` 通过先跑多份完整日程再选择最小 makespan 来伪装在线算法。完整双日程比较只能存在于实验层，并明确标为离线上界。

### 3.2 配置合同

在 `config.py` 定义不可变的 `IntegratedConfig`，至少包含：

- `config_version`；
- `resource_mode = single | fixed_multi`，应由输入公开资源模型确定；
- `packing_mode = lt_greedy | bounded_candidate`；
- `rollout_mode = off | truncated_experimental`；
- `barrier_mode = diagnostics_only | off`；
- packing 的 `k_seed/b_pack/max_sets`；
- search 的候选数、深度、展开数、估值步数、每决策与全图时间；
- `large_graph_safe_threshold` 与安全配置；
- 稳定 tie-break 版本；
- 是否收集详细审计记录。

首批配置固定为：

| 配置名 | 单通道 | 多资源 | 搜索 | barrier | 用途 |
| --- | --- | --- | --- | --- | --- |
| `integrated_v0` | LT | LT greedy maximal | 关闭 | 仅诊断 | 默认与回退 |
| `integrated_p_exp` | LT | 有界候选，但需实验选择器 | 关闭 | 仅诊断 | 4c 重新准入实验 |
| `integrated_r_exp` | LT | LT greedy maximal | 截断估值实验 | 可作为估值字段，不作硬触发 | 4d 后续探索 |
| `integrated_safe_large` | LT | LT greedy maximal | 关闭 | 关闭或抽样诊断 | 1--2 个中大图成本检查 |

在单独实验通过前，不创建默认开启 `P+R+B` 的配置。

### 3.3 决策与审计记录

在 `decision.py` 定义统一记录，每个真实 scheduler 决策至少保存：

- 当前时间、状态稳定指纹、eligible IDs；
- LT 基线动作及分数；
- 多资源候选集合、构造器、截断与构造预算；
- trigger 是否运行及原因；
- 终端估值是否完整、每个候选的值和置信边界；
- barrier 特征是否只作诊断；
- 最终动作、改变 LT 的组件和稳定 tie-break；
- 特征、构造、搜索、模拟的分项时间；
- completion/expansion/候选计数；
- fallback 原因。

“组件建议改变了动作”与“该动作最终改善 makespan”必须分开。后者只能由整图消融或反事实实验确认。

### 3.4 共享预算

`accounting.py` 应把 4c 的 `DecisionBudget` 与 4d 的 `BudgetAccount` 统一为综合层只读汇总或上层总账，避免两个组件各自认为仍有完整预算。要求：

1. 先预留再调用，任何操作不得先超额执行后才记账；
2. 同一决策的候选构造、特征、估值和 simulator 展开共享墙钟截止时间；
3. 全图总预算和单决策预算同时生效；
4. 时间超限、调用上限、展开上限和候选不足分别记录；
5. 任一候选评价不完整时，不比较部分结果，执行 LT；
6. wall-clock 硬隔离由实验 runner 的子进程负责，库内使用协作式预算。

## 4. 分阶段代码实施

### M0：冻结证据和清单

目标：在写综合策略前固定输入、配置和当前组件判定。

- 新建机器可读 `experiments/llm_structure/manifests/stage4g_*.jsonl`，或沿用项目已有 manifest 位置规范；
- 分开保存 development、冻结 100--1000 验证和 1--2 个中大图成本清单；
- 每行保存 benchmark 路径、内容 hash、来源类别、节点数、资源模式、竞争证据等级和用途；
- 同源切片、相同 seed 派生图不得跨 development/validation；
- 建立组件准入表：`lt=admitted`、`packing_advanced=experimental`、`rollout_completion=excluded_online`、`barrier=diagnostics_only`、`job_aware=deferred`。

验收：清单 hash 可重复，输入不存在时显式失败，不自动换图；不根据实验结果重新标角色。

### M1：实现 `integrated_v0`

目标：建立最小综合入口，不改变现有调度语义。

- 新建 `src/llm_structured/integrated/`；
- 单通道直接复用 residual LT 动作选择；
- 多资源复用 `score_tasks(..., "longest_tail")` 和贪心极大集合；
- 在综合层调用 simulator step，不能调用另一套推进函数；
- 所有配置关闭时，trace 与现有 LT 基线逐事件完全一致；
- 给结果附加 `config_version`、分项成本和零组件调用统计。

建议暂不立即加入 `src/registry.py`。先通过独立实验入口稳定配置和返回合同；只有 `integrated_v0` 回归通过且名字冻结后，再注册 `integrated_v0`，状态标为稳定基线。实验配置 `integrated_p_exp`、`integrated_r_exp` 不进入稳定公开注册表。

验收测试：

- 单通道 `integrated_v0` 与 `schedule_longest_tail` makespan、action path、trace hash 相同；
- 多资源与 LT greedy packing 相同，且每个动作通过 `validate_maximal_action`；
- forced idle 不形成算法动作或搜索深度；
- tie-break 在输入顺序扰动后不变；
- 算法不读取 metadata/reference；
- 异常和零预算均回退为同一 LT 动作。

### M2：建立统一实验 runner

新增 `experiments/llm_structure/stage4g_integrated_evaluation.py`，只负责加载、隔离运行、聚合和写结果，不被 `src/` 导入。输出建议使用 `stage4g-integrated-v1` schema，至少包括：

- 输入 hash、代码版本、Python/机器环境、配置全量参数；
- `completed | timeout | error`，未完成时 `makespan=null`；
- makespan、wall-clock、峰值内存；
- 抢占数、communication 区间数、forced-idle、总体与逐资源利用率；
- 每组件调用、建议改变、最终采用、fallback 和分项时间；
- trace validation 状态与 trace hash；
- Exact 状态、gap 和首动作标签仅在 reference hash 匹配且 Exact 完成时填写。

父进程对每个“样例 × 算法”实施硬墙钟。随机和周期对照使用固定 seed，不能复用候选算法的结果作为超时 fallback 值。

### M3：4c packing 的重新准入探索

当前默认仍为 LT greedy maximal。只在多资源 development 集按以下顺序研究：

1. 固定同一 residual LT task score，只改变集合构造；
2. 比较 LT greedy、multi-seed、one-exchange、bounded enumeration；
3. 先报告候选覆盖：Exact 最优首动作是否在候选中；
4. 再报告选择质量：固定选择器能否选中它；
5. 构造与选择使用同一共享预算，分别记录成本；
6. 保留 `star_wide_vs_pair`、`hyperedge_hotspot`、共享下游和抢占无收益反例；
7. 不再把完整 LT completion 作为 100--1000 节点的默认集合选择器。

优先探索低成本、可审计的选择器：

- 只做一层有界事件推进后的截断残余下界/上界；
- 从 LT 集合出发的 `remove 1 -> add 2+` 局部交换，并要求严格改善冻结代理值才采用；
- 候选动作资源覆盖和新释放 compute 只作为独立字段，不直接无约束相加；
- 若没有选择器能在冻结验证中抵消候选构造成本，保留 LT greedy 并结束 4c 组合探索。

`P` 的准入门槛：开发集上先通过 Exact 首动作、反例和等预算消融；冻结 100--1000 节点集相对 LT 必须有正的总体净收益、无不可接受的最坏退化，且候选构造加调度总 wall-clock 在预算内。否则 `integrated_p_exp` 不升级。

### M4：4d 的有界终端估值探索

现有完整 LT completion 在中图上不可用，下一步不再先调 trigger 阈值，而先替换 terminal evaluator。按成本从低到高探索：

1. **固定事件数截断**：候选动作后只推进 `h` 个通信决策，值为已用时间加冻结 residual lower/upper proxy；
2. **固定展开数截断**：不同候选共享相同 expansion 上限；
3. **边界比较**：只有候选的乐观/悲观区间能够严格区分 LT 时才改变动作，否则回退 LT；
4. **小图校准**：以未压缩 Exact 首动作标签测候选召回、估值排序准确率和错误损失；
5. **深度与估值正交**：先固定 width=2，只比较 d1/d2；确认估值有效后才增加宽度；
6. **触发器复核**：估值成本降下来以后再比较 choice、combined、unlock、周期和随机；保留 `pm_random_join_40` 作为漏触发反例。

禁止把训练标签、benchmark ID 或 reference result 放入在线特征。若以后使用学习型估值器，训练、校准、冻结验证必须按来源分组切分，并同时保留无学习的截断基线。

`R` 的准入门槛：

- Stage 1--2 Exact 小图中相对 LT 保留明确收益，且估值错误和最坏损失有报告；
- 与周期/随机触发在相同 completion、expansion 和 wall-clock 下比较；
- 100--1000 节点冻结验证中实际完成非零次候选评价，并实际改变非零次动作；
- 总体端到端净收益为正，最坏退化在预注册阈值内；
- 1--2 个中大图能按规则自动降级，不能出现大量失败搜索后才等价于 LT。

未满足上述条件时，Rollout 继续只作小图诊断工具。

### M5：barrier 的处理

Stage 4e 已给出足够的否定证据，因此 4g 不再对 current direct barrier 做默认组合矩阵。实现上：

- `barrier_mode=diagnostics_only` 时允许记录 direct last-missing、新释放 compute 和估计 slack；
- 不用 barrier 删除候选，不用它打破 LT 平局，不单独触发 rollout；
- 默认成本统计必须能证明关闭 barrier 后不再计算昂贵 descendant census；
- 只在 M4 的截断估值研究中，把 barrier 字段作为一个可关闭的输入做正交消融；
- 若有新 barrier 定义，必须以新版本和新实验重新准入，不能复用 0.25 阈值的旧结果。

### M6：安全配置和注册表

只有保留组件全部通过冻结验证后，才形成候选 `integrated_v1`。模式选择只能依据公开输入属性：资源模式、节点/边/通信数、eligible 宽度和已消耗预算，不能依据样例身份或哪个方法在验证集上更好。

建议安全规则：

- 单通道默认 LT；
- 多资源默认 LT greedy maximal；
- 没有真实选择（单通道只有一个 eligible，或多资源候选动作等价）时跳过全部附加特征；
- 达到预注册规模、单决策耗时或 fallback 比例阈值时，余下日程切换为 `integrated_safe_large`；
- 降级后不再周期性重试昂贵组件；
- 注册表只暴露冻结版本，实验性组合继续由 runner 的显式配置调用。

## 5. 测试规划

### 5.1 单元与合同测试

新增建议：

```text
tests/llm_structured/integrated/
├── test_config.py
├── test_single_policy.py
├── test_multi_policy.py
├── test_budget_accounting.py
├── test_component_audit.py
└── test_safe_fallback.py
```

覆盖：

- 配置非法组合拒绝，例如 barrier 作为默认独立策略；
- 单/多资源 LT 等价回归；
- 候选集合合法、兼容、非空和 inclusion-maximal；
- 同刻事件与零时长 compute 闭包；
- communication 剩余工作量在暂停期间不变化；
- 无 eligible 时由 simulator forced idle；
- 每一种预算在边界前后均不超额；
- 部分候选估值、异常、超时、空候选和缓存 miss 均回退 LT；
- 审计记录与实际调用数一致；
- metadata、reference 和实验目录依赖隔离；
- 关闭组件时不产生该组件成本。

### 5.2 最小反例集

固定保留：

- LT 首动作错误且 depth 2 才能修复的图；
- `pm_random_join_40` 漏触发图；
- Stage 4c 的 `path_future_value`、`exchange_repairs_lt`；
- `star_wide_vs_pair`、`hyperedge_hotspot`、共享下游、热点非关键路径和频繁抢占无收益图；
- Stage 4e margin 退化图；
- 只有一个合法动作、多个表示但等价动作、预算为零和时间立即到期图；
- 多资源下候选若非极大应由 simulator/validator 拒绝的负例。

### 5.3 验证顺序

每个里程碑按风险运行：

1. 新增 integrated 定向测试；
2. `tests/single_channel/complex_chain/preemptive`；
3. `tests/muti_channel/preemptive`；
4. `tests/llm_structured`；
5. 修改公共接口、registry 或返回结构时运行完整 `python -m pytest -q`；
6. runner 做一次最小 manifest 冒烟，确认 timeout 行、空 makespan 和原子写出。

## 6. 算法探索与实验步骤

### 第 1 层：Stage 1--3 开发与筛选

目标是快速排除组合冲突，不形成真实 LLM 总体结论。

实验顺序：

1. 复跑 FIFO、固定顺序、LT 和 `integrated_v0`，确认 v0 与 LT 完全一致；
2. 单独研究 `P`，固定 task score 和预算；
3. 单独研究截断 `R`，先全量 choice trigger 测估值能力；
4. 估值成立后再研究 selective trigger；
5. barrier 只作为 `R` 的可关闭输入，完成有/无对照；
6. 只让已通过单组件门槛的 `P`、`R` 进入 `L+P+R`；
7. 做逐次增加一个组件与反向移除一个组件两类消融。

每次比较同时固定输入、候选宽度、总预算、tie-break 和 completion policy。若改变两项以上，结果只作探索，不作组件归因。

### 第 2 层：冻结的 100--1000 节点验证

组件、阈值和预算进入该层前全部冻结。验证集应分别报告：

- random；
- adversarial；
- 可追溯 real-derived slice；
- 单通道与固定多资源；
- 100、300、600、1000 等规模档位。

同源切片不得跨集合。验证后不得根据结果重新挑组件并仍称为冻结验证；若修改配置，必须形成新版本和新验证集。

正式方法至少包含：FIFO、固定顺序、LT、`integrated_v0`、每个已准入单组件、逐步综合版本、等预算周期/随机搜索对照。小图 Exact 完成时报告 optimal rate 和 gap；未完成只标 feasible/unknown。

### 第 3 层：1--2 个中大图成本边界

只检查：

- 输入加载、特征、候选构造、搜索、完整回放和 Trace 是否完成；
- wall-clock、峰值内存、每决策/每任务成本；
- fallback 频率与安全降级触发点；
- 降级前后 trace 是否仍合法；
- 未完成结果是否保持 `makespan=null`。

该层逐例报告，不计算或宣称真实总体平均收益，也不要求全量 72-case corpus。

### Multi-job 独立扩展

只有 Stage 4f 先形成按目标冻结的结果后才进入：

1. 固定单作业 `integrated_vN`，不因 multi-job 重新改变其内部语义；
2. 分别声明 global makespan、mean/weighted JCT、slowdown 或 fairness；
3. `J` 只修改 job 间选择，不把目标混入单作业 residual tail；
4. 每个目标独立建立 job-blind、job-aware、Exact 小图和饥饿反例；
5. 结果分别报告 per-job completion 和非目标退化。

在此之前，`src/llm_structured/multi_job.py` 是研究资产，不是 `integrated_v0` 的依赖。

## 7. 指标与判定规则

### 7.1 质量

- makespan 及相对 FIFO、LT 的绝对/相对变化；
- 改善/持平/退化样例数，P50/P95 和最大退化；
- Exact 完成小图的 optimal rate、平均/最大 gap 和首动作命中；
- candidate recall 与 selector accuracy 分开；
- 不用只统计完成样例的平均值掩盖 timeout。

### 7.2 行为

- 决策数、真实 choice 数、组件触发与动作改变数；
- 抢占数、communication 区间数、forced-idle 时间；
- 总体与逐资源利用率；
- packing 集合大小、候选数和截断数；
- rollout 完整评价、部分评价、实际深度和采用次数。

### 7.3 成本与净收益

- 端到端 wall-clock 和峰值内存；
- 特征、packing、估值、simulator 分项时间；
- completion calls、expansions、cache hit；
- timeout、error、fallback 次数和原因；
- 单位额外算法时间对应的 makespan 改善；
- 无收益样例上的额外开销。

正式判定优先使用端到端净收益。算法内部代理分数变好不能写成 makespan 改善。

## 8. 组件准入、降级与停止条件

### 8.1 准入流程

每个组件按同一流程：

```text
代码合同与合法性
    -> 最小反例
    -> Stage 1--3 Exact/等预算开发消融
    -> 冻结配置
    -> 100--1000 节点未调参验证
    -> 1--2 中大图成本检查
    -> 决定默认、条件启用、诊断保留或删除
```

### 8.2 自动降级

出现以下任一情况，当前决策或余下日程使用 `integrated_v0`：

- 候选不足或所有候选与 LT 等价；
- 构造、估值、completion 或 expansion 预算不足；
- 任一待比较候选评价不完整；
- 组件抛出可恢复异常；
- 全图组件时间或 fallback 比例达到冻结阈值；
- 输入规模超过已验证范围；
- 多资源候选无法通过最大合法集合验证。

降级必须留下原因；不能用 LT makespan 填充已超时的候选算法结果。

### 8.3 停止探索

满足以下任一项，应形成受限或否定结论，不继续堆叠：

- 单组件在冻结验证中没有独立贡献；
- 收益只来自少数开发反例，验证集净收益不为正；
- 最坏退化超过预注册上限；
- 额外成本超过收益，或中大图频繁降级后实际等价于 LT；
- 两组件作用重复，删除更复杂者后质量不变；
- 组件只能靠答案标签、样例身份或离线完整日程选择才有效。

最终算法可以合法地停在 `integrated_v0`，也可以是 LT 加一个通过验证的条件组件；组件多不是成功标准。

## 9. 预期产物

按实施顺序产生：

1. 本文与机器可读组件准入表；
2. 固定的 development、100--1000 验证、中大图成本 manifest；
3. `src/llm_structured/integrated/` 的版本化配置、策略、预算和审计实现；
4. integrated 专项测试和保留反例；
5. `stage4g_integrated_evaluation.py` 与机器可读逐例结果；
6. `integrated_v0` 等价性与成本报告；
7. `P`、截断 `R`、可选 barrier 输入的独立准入/排除报告；
8. 只包含已准入组件的正交消融与冻结验证报告；
9. 1--2 个中大图的安全降级和成本报告；
10. 最终算法配置、适用范围、禁止使用条件和最坏失败案例；
11. 若 Stage 4f 后续具备证据，再新增独立 multi-job 扩展报告。

每份机器可读结果保存输入 hash、代码与 simulator 版本、配置、机器环境、seed、预算、完成状态、fallback 和 trace validation；输入或公共语义改变后不沿用旧缓存、reference 或汇总表。

## 10. 推荐的实际执行顺序

1. 先完成 M0 的 manifest 和组件准入表。
2. 实现 M1 `integrated_v0`，证明与现有 LT 路径逐事件等价。
3. 实现 M2 统一 runner，把质量、成本、超时和组件审计口径固定下来。
4. 仅在 Stage 1--3 开发集探索 M3 的低成本 packing 选择；不使用完整日程评价作为中图方案。
5. 实现 M4 的固定步数/展开数截断估值，先做小图 Exact 校准，再研究 trigger。
6. 按 M5 将 barrier 固定为诊断，并只作为截断估值的可关闭输入做一次正交消融。
7. 淘汰没有独立贡献的组件，冻结最多一个候选综合版本。
8. 在 100--1000 节点未调参集验证；若失败，正式回退 `integrated_v0` 并记录否定结论。
9. 对冻结版本和安全版本运行 1--2 个中大图成本检查。
10. 满足准入条件后再更新 registry；Stage 4f 结果不足期间不合入 `J`。

按现有证据，最可能的近期结果是：先发布一个工程上统一、研究上诚实的 `integrated_v0`，同时把“截断终端估值能否让 selective rollout 获得端到端净收益”作为唯一优先的高级算法探索。只有它或新的低成本 packing 选择器通过冻结验证后，才形成比 LT 更复杂的正式 Stage 4g 算法。
