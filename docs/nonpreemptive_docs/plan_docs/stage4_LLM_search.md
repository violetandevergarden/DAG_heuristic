# Stage 4：不可抢占真实 LLM Training DAG 研究总纲

## 1. 文档定位

Stage 4 研究如何利用真实 LLM training DAG 中的训练结构改进不可抢占通信调度。目标不是为旧 R5 实现补充解释，也不是从现有代码反推问题定义，而是先明确真实输入、完整通信动作、主动等待、固定资源占用、评价方法和退出条件，再据此审查代码、benchmark 与历史结论。

不可抢占 R0--R4 已经覆盖公共执行语义、Exact、单 channel 并行链、单 channel 一般 DAG 和固定多资源 DAG，对应当前可抢占研究的 Stage 1--3。本阶段不重做这些基础研究，而将其作为回归、Exact 和受控反例基线。

本文负责说明 4a--4f 的共同语义、阶段依赖和证据要求。具体问题、实验与退出条件以对应分纲领为准：

- `stage4a_benchmark.md`：真实不可抢占 benchmark 构建与竞争准入；
- `stage4b_structure_theory.md`：真实 DAG 结构探索与不可撤销启动风险；
- `stage4c_conflict_graph_packing.md`：保留运行中通信后的新启动集合选择；
- `stage4d_selective_rollout.md`：只在关键启动决策点进行完整动作前瞻；
- `stage4e_barrier_scheduling.md`：barrier 信息对 Longest Tail 的筛选或修正；
- `stage4f_multi_job_scheduling.md`：多 job 的资源竞争与独立优化目标。

Stage 4g 及后续综合方向本轮不定义。只有 4a--4f 形成统一输入、基线、消融、反例、成本和 holdout 证据后，才决定是否需要综合算法及其范围。

## 2. 研究问题

Stage 4 回答以下问题：

1. SimAI/AICB 训练任务能否可靠转换为自包含的不可抢占 DAG，而不改变依赖、duration 和固定资源含义；
2. 真实训练 DAG 中是否存在不可抢占启动选择、合法等待选择或多个启动集合，竞争出现在哪些 workload、并行配置、topology 和 job 组合中；
3. micro-batch、pipeline、collective、同步、重复结构和 job 边界中，哪些信息能在启动前预测完整通信的释放收益与阻塞风险；
4. 单 channel 选择一个完整通信或 WAIT、多资源保留 active reservation 后选择新启动集合时，哪些方法能优于 FIFO 和 residual Longest Tail；
5. optional idle 在哪些状态有价值，收益来自等待未来关键通信还是只是改变 tie-break；
6. Selective Rollout 应在哪些不可撤销的启动决策点触发，节省预算用于更宽或更深搜索后是否有净收益；
7. barrier 信息能否减少 Longest Tail 的错误，而不因连续占用阻塞后续更关键通信；
8. multi-job 下是否出现队头阻塞、饥饿和目标冲突，是否需要 job-aware 策略。

基础优化目标是最小化 makespan。平均或加权完成时间、最大 JCT、slowdown 和公平性是 multi-job 的独立目标；每个实验必须预先声明目标，不能混用结论。

## 3. 不可改变的公共语义

本阶段沿用不可抢占 R0--R4 的最终模型。转换器、算法、搜索和实验脚本不得另行解释：

- DAG 依赖采用 finish-to-start；节点只有在全部前驱完成后才 ready；
- compute ready 后自动开始并连续运行到完成，不可抢占；默认 compute 可并行，也可与 communication 重叠；
- communication 一旦启动，必须连续运行到完成；运行期间发生的 compute 或 job 事件只能更新等待候选，不能中断当前通信；
- 单 channel 任意时刻至多运行一个 communication，被选通信独占全部 channel；
- channel 空闲时可以启动一个 ready communication；存在真实未来 compute/job 事件时，也可以主动 `WAIT` 到下一个事件；
- 无 ready communication 时到下一事件的空闲是 forced idle，不是主动动作；没有未来事件时不得枚举无意义 WAIT；
- 固定多资源场景中，communication 启动时同时取得预先指定的全部资源，并持续占有到完成；
- task 完成事件处必须保留全部 active communication，只能在剩余空闲资源上启动新的兼容集合或合法等待；
- 不允许动态选路、迁移、部分获取资源或按比例共享带宽；
- 模拟器负责合法动作和状态转移，算法只从合法完整通信、启动集合或 WAIT 中选择。

正式研究保留两种口径：

- `optional_idle`：允许合法主动 WAIT 或非极大启动集合，是不可抢占主模型；
- `work_conserving`：存在可启动通信时不主动闲置可用资源，用于 WAIT 消融和与可抢占模型的受控比较。

两种口径拥有不同动作空间和最优值，必须分别运行 Exact、基线和候选算法，不能合并统计。

## 4. 研究证据与审查原则

### 4.1 旧资产不是新结论

现有不可抢占 R0--R5 代码、benchmark 和历史实验可以用于回归、复现、候选生成和反例定位。R0--R4 的语义与算法基础无需重做，但旧 R5 的 backbone/deferred、deadline、周期和 frontier cache 仍属于 Stage 4 待复核资产，不能替代真实 AICB 输入和当前统一预算下的结论。

若代码行为与本总纲或不可抢占公共模拟器冲突，应先用手算小图定位，再修正公共模块并增加回归测试。不得为了保留旧结果而改变完整通信或 WAIT 语义，也不要无理由重写另一条可抢占研究线。

### 4.2 计划、观察和结论分离

研究文档明确区分：

- 计划：尚未执行的工作；
- 假设：有待实验或证明的机制解释；
- 观察：限定输入、目标和预算下记录的现象；
- 结论：经过基线、消融、反例、成本和适用范围检查后仍成立的判断；
- 未知：因超时、样本不足、转换未核对或 Exact 未完成而无法判断的事项。

Exact 只有明确返回 optimal 才能提供最优证书。大图相对某个 heuristic 更好不能称为最优，也不能把 optional-idle 的结果解释为 work-conserving 结论。

### 4.3 真实图与受控样例分工

主要结构和收益结论必须来自 Stage 4a 发布的 SimAI/AICB DAG。受控图和合成 motif 只用于手工核对语义、隔离机制、构造反例和生成 Exact 小图。从真实 DAG 截取或缩减的小图必须记录来源 hash、边界 release、截取规则、删除的外部依赖和结构变化。

## 5. SimAI 输入与使用边界

`third_party/simai-flow-scheduler` 只作为真实训练任务输入来源。算法运行时不得依赖 SimAI。转换优先复用已经审查过的可抢占输入链，但不得把现有 JSON 只修改 `semantics` 后当作不可抢占正式 benchmark。

### 5.1 Workload 变量

生成清单显式记录模型、world size、TP、PP、EP、DP、micro-batch、pipeline schedule、iteration、job 数和 arrival。不得靠文件名猜测参数。

一个 workload 可以展开多个 iteration；多个相同或不同 workload 可以赋予独立 job 标识和 arrival 并共享固定通信资源。不同 job 之间不得添加训练依赖边。

### 5.2 Topology 变量

每个 topology 记录来源、设备和链路含义、固定 route-resource 映射，以及属于真实来源、公开示例还是人为冲突拓扑。SimAI 中动态路径、协议共享或 collective 内部同步若未被固定资源 DAG 表达，必须在转换报告中标明，不能留给算法推断。

### 5.3 可追溯发布

每个自包含 JSON 及 manifest 至少保存：

- 源 workload、topology 和输入内容 hash；
- 完整生成参数、转换器版本和执行语义；
- 原任务到导出任务的稳定映射；
- 依赖边来源和 serializer 新增边原因；
- communication duration 与固定资源集合的换算；
- job、iteration 和 arrival；
- optional/work-conserving 实验口径；
- 内容 hash、生成、验证和竞争审计状态；
- 与可抢占同源样例的配对标识，但不共享 reference result。

## 6. 竞争是 benchmark 准入的前提

真实来源不自动表示存在可优化的不可抢占选择。若每次只能启动唯一通信、合法集合唯一、WAIT 不会改变未来，或所有策略动作相同，该样例只能作为无竞争对照或转换回归。

### 6.1 不可抢占竞争现象

审计至少区分：

- 单 channel 同时有两个以上 ready communication；
- optional-idle 下立即启动与 WAIT 都合法；
- 多资源中保留 active reservation 后存在多个不同启动集合；
- work-conserving 下存在多个极大新启动集合；
- optional-idle 下非极大集合或空集具有真实未来事件；
- 不同简单策略是否选择不同完整动作；
- 当前通信连续执行期间是否释放了无法响应的关键通信；
- 动作差异是否改变 compute、barrier、后续通信或 job completion。

只扫描前若干决策点是 sampled prefix，不能认证全图有竞争或无竞争。静态扫描、抽样、完整回放和有界动作存在性检查分别标注。

### 6.2 构造更强竞争

若原始 workload 缺少竞争，可以受控增加 DP、同时 job 数、改变 arrival 或更换 topology。每次只改变少量变量，比较扩展前后的任务数、决策数、合法 WAIT、集合分歧、连续阻塞和回放成本，确认增加的是有效选择而不只是规模。

不得为制造收益修改训练依赖、隐式串行化 compute 或引入固定资源模型之外的共享方式。人为冲突 topology 与真实来源 topology 分组报告。

## 7. Benchmark 规模与分层

正式集合覆盖单 job/multi-job、单 channel/固定多资源、不同模型族、并行配置、topology 和规模：

- 小图：可手工核对或由 optional/work-conserving Exact 提供 ground truth；
- 中图：统一预算内能够完成 FIFO、Longest Tail 和候选策略，是主要收益比较对象；
- 大图：测量生成、加载、特征、回放、内存和超时，不要求 Exact；
- 超大图：严格控制在约 5--10 个代表样例；若完整回放均不可行，只作为压力测试。

manifest 分别记录来源真实性、竞争等级、规模、WAIT 模式和各实验完成状态。不能只保留容易运行但没有选择的图，也不能因图真实而隐瞒算法无法完成。

## 8. 统一基线与实验规范

### 8.1 基线

正式实验至少包含：

- FIFO；
- 输入固定顺序；
- residual Longest Tail；
- work-conserving Longest Tail；
- optional-idle Longest Tail；
- 与候选成本相当的随机或周期对照；
- 小图 optional-idle Exact、work-conserving Exact 或有界首动作枚举。

多资源基线必须保留 active reservation。work-conserving 只能补成对剩余空闲资源极大的新启动集合；optional-idle 允许合法等待或非极大集合。不同集合补全规则分别报告。

### 8.2 公平比较

同一实验固定输入 hash、模拟器版本、目标、tie-break、seed、机器环境、时间和内存预算、超时处理与 fallback。超时、状态上限、只完成前缀和异常必须保留，不能只统计成功样例。

阈值和权重只在开发或 validation 集选择，在未参与设计的 workload/topology holdout 上冻结。高度相似的 iteration、配置和相邻切片不得跨集合泄漏。

### 8.3 指标

基础报告至少包括：

- makespan，以及相对 FIFO 和 Longest Tail 的变化；
- 小图相对对应 Exact 的 gap、最优率和首动作命中率；
- optional idle 相对 work-conserving 的收益与最坏退化；
- wall-clock、峰值内存、展开状态、完整率、超时和 fallback；
- 主动 WAIT 次数与时间、forced-idle 时间；
- 每个通信一个连续区间的 trace 检查结果；
- 总体和逐资源利用率、active reservation、候选数和动作分歧；
- multi-job 的逐 job completion、JCT、slowdown 和声明目标所需的公平性指标。

均值之外报告分布、分位数、最坏退化和失败样例。不得通过排除超时或无收益样例得到质量结论。

## 9. Stage 4a：真实 benchmark 构建

4a 是后续阶段的输入门槛。它复用并核对 SimAI/AICB 转换链，发布不可抢占自包含 DAG，重新审计完整通信、WAIT、active reservation、竞争和可运行性。

主要工作包括：

1. 盘点 workload、topology 和生成参数；
2. 核对单/multi-iteration、DP 扩展和 multi-job；
3. 发布不可抢占 JSON 与分层 manifest；
4. 建立启动、等待和集合选择的竞争审计等级；
5. 对普通规模运行统一基线，对大图测量成本；
6. 从真实图提取少量 optional/work-conserving Exact 切片；
7. 与同源可抢占输入核对任务、依赖和资源，但分别生成结果；
8. 记录转换失败、超时和原生对拍缺口。

当前 `benchmark/llm_structure/nonpreemptive/` 没有正式样例，因此 4a 状态是“计划开始”。文件生成成功不等于本阶段完成。

## 10. Stage 4b：LLM Training DAG 结构探索

4b 研究 micro-batch、iteration、pipeline phase、forward/backward、TP/DP/PP/EP、join、optimizer、barrier、资源热点和 multi-job 结构。

不可抢占下重点不是事件发生后切换通信，而是启动前判断：完整 duration 内会出现哪些未来事件；候选会连续阻塞哪些资源；完成后释放什么；WAIT 是否值得。

每条候选结构结论必须回答定义、真实出现范围、是否位于有选择的启动状态、局部释放与最终 makespan 的关系、optional/work-conserving 差异、反例、成本和后续用途。旧 R5 只提供候选假设，必须在 4a manifest 上重验。

## 11. Stage 4c：冲突图与新启动集合

固定多资源状态由 active communication、eligible communication 和 free resources 构成。active communication 已经启动，必须保留到完成；冲突图只在与 active reservation 兼容的 eligible communication 上构造。

work-conserving 动作是在剩余空闲资源上选择 inclusion-maximal 的新启动集合；optional-idle 还允许合法空集或非极大集合。候选方法可以包含 FIFO/LT 补全、冲突图贪心、多起点、局部交换和小图枚举，但必须受候选数、状态数和墙钟硬预算限制。

研究重点是长通信连续阻塞多个短通信、多个小通信覆盖不同关键分支、为未来 arrival 保留资源是否值得，以及整集合下游重复计分。若简单 Longest Tail 补全已足够，应形成受限或否定结论。

## 12. Stage 4d：Selective Rollout

Rollout 首动作必须是完整通信、完整新启动集合或合法 WAIT，并由不可抢占模拟器推进。不得执行一个 tick 后假装可以切换。

触发信号包括 LT 分差、简单策略分歧、duration 和资源脚印差异、完整执行期间的关键 arrival、热点连续占用、WAIT 与立即启动接近、barrier 缺口和 multi-job starvation 风险。

在相同总预算下比较全量、selective、随机、周期和无 rollout，并检验节省预算能否换取更宽或更深搜索。预算到达后必须安全回退，记录 fallback。若只在旧小图有效，应降级为分析工具。

## 13. Stage 4e：Barrier 感知调度

Barrier 只作为 residual Longest Tail 的初筛、有限修正、平局规则或 rollout 触发信号，不作为独立主策略。

除 last-missing、slack、下游 tail 和立即释放外，不可抢占评价还必须考虑候选完整 duration、执行期间无法响应的更关键缺口、热点资源连续占用、WAIT 后的新候选和 active reservation。

必须用反例检查局部 barrier 不是最终瓶颈、共享下游重复计分、短通信阻塞长关键通信，以及提前当前 barrier 却延迟后续 barrier。barrier 时间提前不能直接解释为 makespan 改善。

## 14. Stage 4f：Multi-job 场景

Multi-job 由多个无跨 job 依赖的真实训练 DAG 组成，共享固定通信资源。正式输入覆盖同构/异构、同时/错峰 arrival、不同并行配置和单/多资源。

重点研究长通信造成的跨 job 队头阻塞、全局 Longest Tail 是否足够、optional idle 是否值得等待新 job 关键通信、job-aware 规则是否造成饥饿，以及 makespan、JCT、slowdown 和公平性之间的冲突。

每个策略只能按预先声明的目标评价。必须同时报告对应单 job 对照和逐 job 结果；合成复制只能解释机制，不能替代真实 AICB multi-job 证据。

## 15. Stage 4g 与后续边界

本轮不编写 Stage 4g 综合算法计划，也不预设最终算法必须组合 packing、rollout、barrier 和 job-aware 组件。

只有某个组件在 4a 输入边界内完成统一基线、消融、反例、成本、最坏退化和真实 holdout 验证，才可成为未来综合候选。若证据只支持 residual Longest Tail、简单 WAIT 规则或简单启动集合，同样是有效结论。

## 16. 阶段依赖与推进顺序

Stage 4 按以下依赖推进：

1. 4a 建立可信、可运行且有不可抢占竞争审计的真实输入；
2. 4b 从这些输入提取可验证的结构假设；
3. 4c 研究保留 active reservation 后的新启动集合；
4. 4d 研究选择性完整动作前瞻与预算分配；
5. 4e 将 barrier 作为 Longest Tail 的条件信息；
6. 4f 在真实 multi-job 输入上区分优化目标；
7. 完成 4a--4f 后再决定是否规划 4g。

阶段可以为修复公共语义而回退，但不能越过输入证据边界。例如，4a 只有 sampled-prefix 时，4b--4f 不能声称覆盖完整 corpus；普通规模基线未完成时，不能用少量成功样例概括大图。

## 17. 当前基线与明确缺口

截至 2026-08-31，可以确认：

- 不可抢占 R0--R4 已覆盖语义、Exact、并行链、一般 DAG 和固定多资源，当前定向回归为 37 passed；
- 固定不可抢占 benchmark 共 75 个，其中单 channel 58 个、固定多资源 17 个；
- 旧 R5 已有 LLM 结构原型和受控实验，但真实 AICB 证据不足；
- `benchmark/llm_structure/nonpreemptive/` 当前没有正式样例；
- 可抢占线已有 72-case 真实语料和转换资产，可作为不可抢占 4a 的输入链参考，但其竞争、基线、Exact 和收益结论不能直接继承；
- 当前没有不可抢占真实 corpus 的统一 baseline、holdout、规模和 multi-job 完整证据；
- 当前不能宣称不可抢占 Stage 4 已形成真实大图最终算法。

若后续复核与上述状态不一致，应记录输入 hash、代码版本、环境、预算和差异原因，不为维持旧结论修改数据。

## 18. Stage 4a--4f 总退出条件

只有同时满足以下条件，才能认为本轮不可抢占 Stage 4a--4f 研究完成：

1. 真实输入转换、duration、固定资源映射和不可抢占 trace 经过独立核对；
2. 正式 benchmark 有分层 manifest、启动/等待/集合竞争等级和可复现 hash；
3. 普通规模真实图在统一预算下完成 FIFO、Longest Tail 和候选算法对照；
4. 小图分别具有 optional-idle/work-conserving Exact 或明确标注边界的首动作 ground truth；
5. 每个正时长 communication 在 trace 中只有一个连续区间，active reservation 始终合法；
6. optional-idle 与 work-conserving 的动作、最优值、收益和成本分开报告；
7. 每个候选结构或算法均有基线、消融、反例、运行成本、最坏退化和完整率；
8. multi-job 明确区分 makespan、JCT、slowdown 和公平性目标；
9. 阈值和策略在未参与设计的真实 workload/topology holdout 上检验；
10. 超时、未完成、无竞争、无分歧和负面结果被完整保留；
11. 明确各结论适用的 workload、topology、资源模型、WAIT 模式、规模、预算和优化目标；
12. 无稳定收益、解释不足或复杂度不值得的方向形成否定或受限结论；
13. 依据 4a--4f 的证据明确决定是否需要 Stage 4g，而不是因模块已经存在就进入综合。

最终报告应回答：在哪些真实训练场景中，DAG-aware 不可抢占通信调度相对 FIFO、固定顺序和 residual Longest Tail 确实有用；收益来自排序、主动等待、启动集合、barrier、前瞻还是 job 目标；完整通信的阻塞代价是多少；何时简单策略已经足够。若没有复杂算法的稳定净收益，也应把它作为有效研究结论。
