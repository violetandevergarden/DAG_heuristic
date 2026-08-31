# 可抢占调度代码审查过程与结果（2026-08-15）

## 1. 审查边界

本轮只做审查、复现实验和记录，没有修改 `src/`、`tests/`、`benchmark/`、`benchmark_generate/` 或 SimAI 子模块中的实现与数据。

审查输入为：

- `docs/plan_docs/outline.md`：理想可抢占通信模型与研究路线；
- `docs/plan_docs/simulator.md`：事件模拟器、合法动作、Trace 和验证器的目标架构；
- `src/preemptive/`、`tests/preemptive/`、v2 benchmark、reference sidecar 和历史可抢占研究文档；
- 当前仓库根协作说明中尚未同步更新的不可抢占历史语义。

根据 2026-08-15 的进一步确认，项目现在全面转向 communication 可暂停恢复的 v2 模型；不可抢占 v1 只作为历史模型和对照实现保留。以下代码正确性判断以 `outline.md` 和 `simulator.md` 的可抢占语义为准。根协作说明、现有目录和部分 README 尚未完成这次主线切换，是需要修正的仓库状态，而不是继续把 v2 限制为旁支的依据。

## 2. 审查方法与实际执行

审查依次完成了：

1. 对照两份规划文档整理 compute、communication、事件、WAIT、固定资源、Trace 和 Oracle 的目标语义；
2. 阅读单通道状态机、单通道算法/Exact、多资源状态机/Exact、多 Job、重复结构、benchmark loader/validator、registry 和 reference generator；
3. 检查所有 v2 benchmark、index 和 reference hash；
4. 运行现有核心测试和全仓库非 SimAI 测试；
5. 用当前代码重跑阶段 0--4 汇总实验、阶段 5 的反例与对称压缩、阶段 6 的 40 个双 Job 实验；
6. 编写只读探针验证 WAIT、非 maximal 集合、零时长通信和 Trace validator 的实际行为。

实际测试结果：

- `tests/preemptive` 中不依赖 SimAI 的 12 项测试通过；
- 跳过 `tests/preemptive/test_repetition.py` 和 `tests/integration` 后，全仓库 60 项测试通过；
- 139 个 committed benchmark 均可加载，index/hash 一致；
- 54 个现有 reference 均与 benchmark hash 一致，且当前 Exact 重算值一致；其中 v2 reference 为 21 个；
- 完整 `tests/preemptive` 在收集 `test_repetition.py` 时因环境缺少 `jsonschema` 失败。该失败发生在 SimAI 子模块导入阶段，不是调度断言失败。

## 3. 总体判断

现有 v2 代码不是需要整体重写的废弃原型。单通道事件推进、remaining work 守恒、compute 自动执行、通信在 compute 事件处暂停、单/多资源 Exact 的主要数值，以及阶段 5/6 的代表性结论均能复现。

但它还没有达到 `simulator.md` 所要求的“可独立审计的模拟器”标准。最重要的缺口不是 heuristic，而是主线切换尚未落实到目录与公开接口、动作验证不完整、Trace validator 与状态机不独立、多资源完全没有 Trace，以及历史结果缺少原始机器可读产物。当前 v2 Exact 数值可作为同一实现体系内的强回归证据，但还不能视作经过独立执行器/验证器双重校验的最终 ground truth。

## 4. 发现的问题

### R1（高）：可抢占主线尚未落实到仓库结构和公开合同

项目决策已经明确：通信可暂停恢复的 v2 是当前主线，不可抢占 v1 是历史模型。但根协作说明、主目录结构和部分 README 仍把 v1 写成公开主线；可抢占实现则整体放在 `src/preemptive/` 下，单通道、多资源、multi-job、重复结构和 study 混在一个语义前缀包中。

这不是某个函数的局部 bug，而是主线迁移没有完成。继续把新实现放在 `src/preemptive/` 会使核心代码长期看起来像附属实验，同时 registry、测试和 benchmark 仍需绕一层语义分派，后续单/多通道公共模型也难以自然融合。

目标结构应同时表达“DAG 家族”和“执行语义”两个维度。公共事件状态、Trace 和动作合同进入 `src/core/`；单通道分别使用 `src/single_channel/parallel_chain/{preemptive,nonpreemptive}/` 和 `src/single_channel/complex_chain/{preemptive,nonpreemptive}/`；固定多资源使用 `src/muti_channel/{preemptive,nonpreemptive}/`。两套实现是对等的语义版本，不使用 `old/legacy` 路径；区别只在于可抢占版本是当前 active development，非抢占版本进入 maintenance-only 状态。迁移期间可保留旧 import compatibility shim，但不再从顶层 `src/preemptive/` 发展新功能。

当前 `src/preemptive/single_channel/solver.py` 同时接受 parallel-chain 和 general DAG，却没有在包、接口、注册表能力和研究算法上体现两类问题的区别。这会掩盖 parallel-chain 的结构特化机会，也使实验难以判断收益来自一般 residual-DAG 策略还是链结构。即使初期两类实现共享同一个事件引擎或 Exact，公开模块和算法入口也应分开。

### R2（高）：合法动作实现不符合 `simulator.md` 的 work-conserving 合同

单通道 `PreemptiveDAGModel.legal_actions()` 在存在 eligible communication 且仍有 active compute 时同时返回 `RUN` 和 `WAIT`。只读探针在同一状态得到：

```text
(RUN a, WAIT)
```

多资源 `PreemptiveMultiResourceModel.step()` 只检查 eligible 和资源兼容，不检查 inclusion-maximal。两个使用不同资源、应同时运行的通信处于 eligible 时，`maximal_actions()` 只返回 `(a,b)`，但 `step((a,))` 仍被接受。只要存在 active compute，空集合 WAIT 也可在有 eligible communication 时通过。

现有 Exact 和内置 heuristic 会在上层主动过滤 WAIT，且多资源 Exact 只枚举 maximal actions，因此已报告数值通常未利用这些额外动作；但模拟器核心没有兑现“非法动作必须拒绝”的合同，外部 scheduler 可以生成规划文档定义下非法的轨迹。

同时，v2 schema/loader 强制 `optional_idle=true`，`benchmark/README.md` 又明确写可主动 WAIT，与 `outline.md` 的“主动等待不可能更好”和 `simulator.md` 的强制 work-conserving 合同不一致。必须先统一字段含义，再改动作验证。

### R3（高）：单通道 Trace validator 不是独立回放验证器

`assert_preemptive_trace()` 主要检查最终状态和 interval 总时长。它使用 `trace.final_state` 中的完成时间检查依赖，没有从输入和 Trace 独立重建完成时间；也不核对：

- `trace.transitions` 与 intervals/events 是否一致；
- events 是否缺失、重复或顺序错误；
- interval 的 task kind 是否与 DAG 一致；
- 最后完成事件是否等于 makespan；
- started/paused/resumed/completed 事件是否与状态变化一致；
- 每个任务是否恰好完成一次。

实测把一个合法 Trace 的 `events` 和 `transitions` 全部清空后，validator 仍然通过。这会形成共同失效模式：状态机生成错误的 final state 时，validator 可能用同一错误状态为其 interval 背书。它不满足 `simulator.md` 第 6.9 节要求的独立性。

### R4（高）：多资源实现没有 Trace、回放验证或资源占用审计

`PreemptiveMultiResourceModel` 只返回 `MultiState`，`MultiResult` 只保存 action 序列、makespan 和计数。没有 compute/communication interval、暂停恢复事件、资源占用区间或独立 validator。

因此多资源的 14 个 Exact 值虽然能由同一状态机稳定重算，但不能从结果文件独立证明每段服务量、固定资源同时获取、暂停释放、依赖时序和 makespan 一致。历史报告中“多资源核心、Exact 闭环已建立”的表述应收紧为“搜索器与自身状态转移闭环已建立，独立 Trace 审计尚未建立”。

### R5（中）：单/多资源输入防线不一致

单通道 `PreemptiveDAGModel` 明确拒绝 duration 小于等于 0 的 communication；多资源模型只验证资源集合，不做相同检查。直接构造零时长通信时，多资源 `step()` 会以 `delta=0` 在时间 0 将其完成。

公开 benchmark validator 会拒绝这类输入，所以 committed v2 benchmark 未受影响；但核心模型可被 Python 调用者绕过 loader 后置于不一致状态。统一核心不变量应在模型边界再次验证。

### R6（中）：模拟器和 scheduler/search 尚未按目标架构解耦

当前单通道状态机已相对集中，但还没有只读 `SchedulerView`、独立动作验证器、独立依赖闭包器和明确 deadlock 类型。多资源状态机、算法与动作枚举耦合更紧。算法通常先用 `step()` 生成 actions，再调用 `model.run(actions)` 完整重放一次；这在当前确定性实现下可行，但会增加两条执行路径未来漂移的风险。

这属于增量整理问题，不需要重写所有算法。优先抽出合同和验证层即可。

### R7（中）：Exact 缺少独立小图 Oracle 的交叉验证

单通道 Exact 和所有 heuristic 共用 `PreemptiveDAGModel`；多资源 Exact 也与 heuristic 共用同一个 `step()`。memoization key 包含每个任务的 status/remaining，当前审查未发现遗漏 active compute remaining 的错误，历史值也可复现；但现有“Exact”证据仍依赖同一转移实现。

应增加一个仅用于极小整数图、实现路径独立的 tick/exhaustive Oracle 或约束模型，并在随机性质测试中逐图比较最优值。独立 Oracle 不需要用于生产，也不需要替换现有高效事件 DP。

### R8（中）：历史实验的原始机器可读结果缺失，reference 覆盖不完整

历史文档引用了以下 JSON，但当前工作区没有这些文件：

- `preemptive实验结果.json`；
- `preemptive阶段5_实验结果.json`；
- `preemptive阶段5_ZB语义修复后实验结果.json`；
- `preemptive阶段6_实验结果.json`；
- `preemptive阶段6_pipeline实验结果.json`。

当前 v2 有 34 个 adversarial benchmark，只有 21 个 reference sidecar。缺少的 13 个全部位于 parallel-chain adversarial；其中多数在当前阶段 0--4 runner 的较高预算下可解，只有两个图稳定超时。因此“没有 sidecar”不能统一解释为“Oracle 不可解”，也包含历史生成不完整。

结果表可以由代码重跑，但无法核对当时机器、commit、逐实例记录和运行时分布。运行时间类结论只能视为当前机器上的重测，不是对旧原始文件的逐字校验。

### R9（中）：测试依赖边界不完整

`pyproject.toml` 的 dev 依赖只有 pytest 和 ruff；`tests/preemptive/test_repetition.py` 在导入时经过 SimAI 子模块需要 `jsonschema`。这使默认开发环境不能收集完整测试，也违反“只有 integration 才依赖 SimAI”的当前仓库边界预期。

应选择其一：把真正的 SimAI 测试移入 `tests/integration/` 并显式 skip；或把必要依赖放入明确的 integration extra。不能让纯 preemptive 单元测试因可选子模块依赖在收集阶段失败。

### R10（低）：文档与算法命名存在漂移

- `benchmark/README.md` 一处仍称 preemptive 目录“当前只提交一个图”，实际已有 64 个 v2 benchmark；
- README 的“当前 33 个 adversarial reference”只对应 v1，未清楚说明另有 21 个 v2 sidecar；
- `longest_delay` 与 `longest_tail` 在 `schedule_priority()` 中使用完全相同的评分 `tail-current_remaining`，阶段 runner 把它们作为两个名字运行，但并不是两个独立算法；
- 多处旧报告说已经形成 Trace 闭环，而多资源结果没有 Trace。

这些不会改变数值，但会误导算法比较和完成度判断。

## 5. 对过去结果的再审视

### 5.1 阶段 0--4 汇总结果：数值可复现，证据等级需收紧

当前代码重跑得到 48 个单通道 Exact 图和 14 个多资源 Exact 图，仍跳过 `pm_fixed_beam_counterexample`、`pm_random_chain_6` 两个超时图。核心质量指标与历史文档一致：

| 结果 | 历史值 | 本次重跑 |
|---|---:|---:|
| 单通道 Longest-tail mean ratio | 1.01581 | 1.015809 |
| 单通道 Longest-tail observed max | 1.21212 | 1.212121 |
| 单通道 Longest-tail 最优率 | 83.33% | 83.33% |
| 单通道 Rollout-2 最优率 | 100% | 100% |
| 多资源 Longest-tail-pack mean ratio | 1.00661 | 1.006614 |
| 多资源 Set-Rollout-2 observed max | 1.03704 | 1.037037 |
| 多资源 Set-Rollout-2 最优率 | 92.86% | 92.86% |

运行时间随机器变化，本次单通道 Rollout-2 平均约 10.52 ms，Beam-8/32 约 75.13/191.91 ms，Monte Carlo-64 约 91.06 ms；这些只用于量级核对。

结论修订：

- “当前样本上 Rollout-2 全部命中 Exact”仍成立；仍不能解释为算法 exact 或理论保证；
- Longest-tail 的经验表现仍成立；`longest_delay` 与其实现相同，不应算作独立佐证；
- 多资源结果仍可复现，但在独立 Trace validator 完成前只能标为“状态机内复核的 Exact”；
- random、adversarial、real 仍需分开报告。阶段总表混合 random/adversarial，不能代表真实 LLM DAG 效果。

### 5.2 2-bound、WAIT 支配和 maximal-set 支配

本轮没有发现历史证明与“理想、零开销、事件级可抢占、线性单位服务、单 makespan”前提直接矛盾的代码证据。它们仍可作为 v2 理论命题保留，但必须显式附带全部前提。

这些命题是当前可抢占主线的基础理论，但不能外推到历史不可抢占模型、非零切换开销、minimum quantum、共享带宽、动态路由或 weighted JCT。动作验证器尚未强制这些合同，因此“理论动作空间”和“核心 API 可接受动作空间”目前并不相同。

### 5.3 阶段 5：重复结构负面结论和对称压缩可复现

本次重跑得到：

- 周期数 1/2/4/8/16 时，Exact makespan 为 2/4/8/16/32；Independent-copy 为 2/5/11/23/47；Boundary-aware 为 2/4/8/16/32；
- 3/4/5/6/7 个可交换 replica 的对称 Exact 状态数为 16/38/73/126/203，makespan 为 11/14/17/20/23。

因此“局部周期最优不能机械复制”和“严格自同构下的状态商压缩保持最优值”两项核心结论仍成立。真实 AICB/ZB/EP 的统计表因原始 JSON 和本地 workload 不在当前工作区，不能在本轮独立复核；应保留旧文档已经写明的数据来源限制。

### 5.4 阶段 6：双 Job 核心结果可复现，泛化范围不变

用 `samples=30, seed=260812` 重跑得到 40 个 case：

- Exact-K1 mean/max ratio 为 1.005952/1.071429，最优率 90%；
- Exact-K2、Rollout-K2、Semantic-K2、Adaptive-K 全部在这 40 图上达到 100%；
- teacher candidate recall：K=1/2/4 为 87.04%/99.83%/100%；
- 多资源 top-1 反例 K1/K2/Exact makespan 为 25/18/18；
- weighted-JCT 的 4.0625 倍和约 4.74% 反例仍可复现。

这些仍只是当前双 Job 小图和一个多资源反例上的结果。K=2 不能据此宣称对一般多 Job 安全；3--4 Job、真实窗口、placement、fairness bound 和有限 quantum 仍未完成。

### 5.5 Zero Bubble 修复结果

现有测试源和历史报告均显示 B/W 修复后会检查 raw data 中同层 `B→W` 边，并把 SimAI 依赖限制在生成/集成路径。本轮由于缺少 `jsonschema`，没有完成该 SimAI 测试链的重跑；因此不新增关于真实 ZB 调度收益的结论。

## 6. 可继续信任与暂缓引用的结论

可以继续作为当前 v2 主线的回归基线：

- 单通道事件状态机的已覆盖暂停/恢复样例；
- 现有 21 个 v2 reference 的 hash 和当前 Exact 值；
- 阶段 0--4 的汇总质量指标；
- 重复周期反例、严格 replica 对称压缩；
- 阶段 6 的 40 个双 Job 小图和固定多资源反例。

在修复独立验证和产物链之前应暂缓强化引用：

- “多资源已形成完整 Trace/回放闭环”；
- “全部 v2 adversarial 都有 ground truth sidecar”；
- “Rollout-2/K=2 是一般意义 exact”；
- 任何把 v2 2-bound、WAIT/maximal 支配结论用于历史不可抢占模型的说法；
- 无原始 JSON 支撑的历史运行时间、真实 workload 汇总和环境相关统计。

## 7. 本轮产物

本文件记录审查过程与结果。详细修改顺序、涉及文件、测试矩阵和验收条件独立写在 `preemptive_code_review_modification_plan_20260815.md`。本轮未执行该修改计划。
