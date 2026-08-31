# Stage 4a 不可抢占真实 benchmark 实现方案

日期：2026-08-31

对应纲领：`docs/nonpreemptive_docs/plan_docs/stage4a_benchmark.md`

状态：待实施

## 1. 方案定位

本方案用于从零建立不可抢占 Stage 4a 的真实输入、发布、竞争审计和基础实验链。它不是对现有不可抢占 Stage 4a 代码的修正或审查；当前 `benchmark/llm_structure/nonpreemptive/` 没有正式样例，因此不能从旧结果反推实现，也不能把旧 R5 资产当作真实 LLM 证据。

真实训练任务只来自 `third_party/simai-flow-scheduler/inputs/aicb-workload/` 中的 AICB 文件，并由 `third_party/simai-flow-scheduler` 的 parser、workload builder、pipeline builder、serializer、topology loader 和固定路由产生原始任务、依赖及资源映射。禁止自行编造训练层、通信、同步边或通信量。

本阶段允许复用已经核对过的公共转换思路和不依赖动作语义的代码，但必须新增不可抢占导出与验证入口。不能读取一个可抢占 JSON 后只替换 `semantics`，也不能复用可抢占 reference result。可抢占语料只能用于同源图结构对拍，不能充当不可抢占实验结果。

本阶段先保证真实、小而可验证，再扩大覆盖。正式语料以小图为主，中图控制在约 10 个，大图目标为 3 个且最多 3 个；不再生成大规模 source × topology × 并行配置的笛卡尔积。

## 2. 已核对的输入事实与实现前置问题

### 2.1 AICB 输入现状

2026-08-31 对现有目录按规范文件名进行只读盘点，共发现 936 个可解析候选，覆盖 6 个模型族：GPT-7B、GPT-13B、GPT-22B、GPT-175B、Llama-405B 和 Mixtral-8x7B，world size 覆盖 1、2、4、8、16、32、64、128。

这只是候选目录盘点，不是发布清单。实现时必须使用 SimAI `AicbParser` 读取文件头，并交叉检查文件名、header 和 builder 实际值。TP、PP、EP、DP、global batch、micro batch、sequence length 等字段不得只从文件名猜测。无法一致解析的文件进入隔离清单，不参与生成。

`inputs/aicb-workload/e2e-guide.md` 明确说明：AICB 文件描述一个训练 iteration；标准训练链为 AICB parser → `WorkloadBuilder` → topology/static analysis → executor。多 iteration 应通过 SimAI 的重复构建与 `JobMerger` 或动态展开能力实现，不得在本项目中直接复制 JSON 任务冒充原生展开。

### 2.2 当前仓库接口缺口

当前 `benchmark_generate/simai/export.py` 的输出语义固定为可抢占 v2，`benchmark_generate/llm/corpus.py` 的活动目录也固定为 `preemptive/`。这些代码可以提供转换层对拍依据，但不能直接作为不可抢占发布入口。

当前 benchmark schema 还有一个必须先处理的合同缺口：

- schema v1 能表达不可抢占和 optional idle，但语义字段只写 `resource_model=exclusive`，不能明确表达固定多资源集合；
- schema v2 被当前 loader/validator 保留给可抢占语义，并会把 `optional_idle` 归一为 `false`；
- 因此，正式的不可抢占固定多资源真实图不能靠现有版本完整表达目标合同。

实现前应新增一个明确版本的不可抢占 schema，例如 v3。它至少表达：`preemption=none`、`decision_epoch=task_completion`、`optional_idle=true`、`compute_model=unbounded_parallel`、单 channel 的 `exclusive` 或多资源的 `exclusive_fixed_set`、零抢占开销和零最小粒度。旧 v1 benchmark 保持可读，不批量迁移；v2 可抢占文件的读取和哈希不得改变。

`work_conserving` 是同一个不可抢占问题上的动作空间消融，不应再复制一份 benchmark JSON。正式 JSON 声明 optional idle 主模型；manifest 和实验配置记录该样例必须分别运行 `optional_idle` 与 `work_conserving`。

## 3. 最终产物

完成后至少形成以下产物：

1. `benchmark/llm_structure/nonpreemptive/` 下的自包含真实图和 real-derived 小图；
2. 独立的不可抢占 source catalog、topology catalog、候选 manifest、活动 manifest、公共 index 和 run metadata；
3. 每个样例的转换报告、竞争审计摘要及其详细报告哈希；
4. 小图两种动作口径的 Exact 结果，未完成项保留真实终止状态；
5. 中图统一基线报告和 3 个大图的分步骤成本报告；
6. 至少一个原生小 workload 的逐任务对拍，以及 multi-iteration、multi-job 的来源和组合报告；
7. 供 Stage 4b--4f 使用的冻结分层清单，明确每组能支持和不能支持的结论。

算法运行时只读取自包含 benchmark，不依赖 SimAI、生成脚本、metadata 中的审计答案、manifest 中的竞争分类或任何 reference result。

## 4. 语料规模与分层

### 4.1 总量控制

首次正式发布采用以下目标范围：

| 层级 | 目标数量 | 主要用途 |
| --- | ---: | --- |
| 小图 | 30--40 | 手工核对、两种动作口径 Exact、动作非等价和 WAIT 反例定位 |
| 中图 | 8--10 | FIFO、固定顺序、residual Longest Tail 和候选策略的完整回放 |
| 大图 | 2--3，目标 3 | 转换、加载、静态特征、有限前缀、内存和超时边界 |

最终总量约 41--53 个，小图至少占三分之二。中图可以因有效候选不足少于 10 个，但不得为了凑数重复同一结构；大图不超过 3 个。扩展语料先写到临时实验目录，不直接进入正式快照。

图的层级不只按任务数划分，而以可完成的工作为准：

- 小图：优先控制在 30--300 个任务，并要求可手工复核，或在统一预算内对至少一个动作口径取得 Exact 证书；两种口径都应运行，未完成的一侧保留 `time_limit` 或 `state_limit`。
- 中图：候选任务数初步放在 300--12000，但只有在每个基线的严格预算内可完成回放才正式归为中图。
- 大图：从任务数、边密度、通信比例和资源冲突强度中选择 3 个不同压力来源，不只取任务数最大的 3 个。

任务数阈值只用于首轮筛选。若实际 wall-clock 与上述范围不符，应按测得成本重新分层，并在 manifest 中保存分层规则版本，不能移动超时行来美化中图结果。

### 4.2 小图必须来自真实图

小图优先使用两类来源：

1. SimAI builder 能直接生成且规模足够小的完整 AICB workload；
2. 从完整真实 DAG 中提取的 `real_derived` 因果闭包切片。

切片不得自行拼写 motif。选取步骤为：先在完整图回放或审计中定位一个真实不可抢占启动决策点，再围绕该点选择到自然 join、barrier 或局部终点的后继区域，并递归补齐所有被保留节点的前驱。若补齐后超过小图上限，则放弃该切片，不删除外部依赖、不伪造 release task，也不修改 duration、通信资源和任务类型。

每个切片记录源 benchmark hash、锚点决策状态、选择规则、保留/删除任务数、边界后继、结构变化和切片目标。切片 Exact 只能说明该局部自包含问题，不能被写成完整训练图最优结论。

### 4.3 覆盖矩阵

在有限总量内采用分层抽样，而不是全排列。正式清单至少覆盖：

- 6 个已有模型族；
- TP、PP、DP 的低/中层级以及 Mixtral 可用的 EP 变化；
- 单 channel 投影与至少两类经核实来源的固定 topology；
- 单 job、multi-iteration 和 multi-job；
- 有排序选择、有集合选择、有 WAIT 选择、有延迟阻塞和无选择负对照；
- 同源 workload 的少量单变量配对，如 DP 或 topology 配对。

单 channel 是对同一真实任务 DAG 的资源模型投影，必须标记为 `controlled_projection`；固定多资源样例才使用 topology 与固定路由结果。topology 的来源证据不足时标记 `unverified` 或 `public_example`，不使用“生产拓扑”等超过证据的称呼。

## 5. 代码组织与依赖边界

建议按以下最小边界实现，不重写 R0--R4，也不改动另一条语义的算法：

```text
benchmark_generate/
├── simai/
│   ├── common_export.py                 # 中立的 SimAI 任务、依赖、duration、route 提取
│   └── nonpreemptive_export.py          # 新增不可抢占 benchmark 序列化入口
└── llm/nonpreemptive/
    ├── catalog.py                       # source/topology 清单与候选选择
    ├── corpus.py                        # generate -> audit -> publish
    ├── slice.py                         # 因果闭包小图提取
    ├── contention.py                    # 不可抢占竞争审计
    └── multi_job.py                     # job 命名空间、arrival 和共享资源组合

experiments/llm_structure/nonpreemptive/
├── stage4a_baselines.py
├── stage4a_exact.py
└── stage4a_scaling.py
```

实际文件可以在实现时合并，但必须保持以下依赖方向：

```text
third_party/SimAI
        ↓ 仅离线生成
benchmark_generate/simai
        ↓ 中立 Benchmark
benchmark_generate/llm/nonpreemptive
        ↓ 自包含 JSON
src/benchmark + 不可抢占公共模拟器
        ↓
experiments/llm_structure/nonpreemptive
```

`src/` 不得导入 `benchmark_generate`、`experiments` 或 SimAI。实验 runner 不得自己实现时间推进、WAIT、通信连续执行或资源释放；它只选择公共模拟器返回的合法动作。

## 6. 实施步骤

### P0：冻结不可抢占输入合同

1. 新增不可抢占真实图所需 schema 版本及 JSON Schema。
2. 更新 model、loader、writer、validator，显式区分单 channel 和固定多资源合同。
3. 保持 v1/v2 读取行为及已发布文件 hash 不变。
4. 增加 schema 往返、非法字段、固定资源缺失、错误 optional idle、错误 preemption 和跨版本回归测试。
5. 固定“一个 benchmark、两种实验动作口径”的规则，禁止为 work-conserving 复制问题文件。

验收标准：同一不可抢占固定多资源 JSON 能被 loader 无损读取，validator 能拒绝动态资源、空资源集和抢占字段；旧 R0--R4 与可抢占测试不回退。

### P1：抽取中立 SimAI 转换层

1. 复用 `AicbParser` 和相应 pipeline builder 生成原生 workload。
2. 复用 serializer 追加 GPU compute-order 边，并把原始边与 serializer 新增边分开记录。
3. 无 topology 时将所有 communication 映射到 `channel:0`；有 topology 时由 SimAI topology loader 和固定 BFS route 产生完整 directed-link/NIC 资源集。
4. communication duration 继续使用有版本的整数换算规则，并保存原始 `size_bytes`、带宽、舍入方式和结果。
5. 中立层只产生任务、依赖、duration、资源和 provenance，不携带可抢占或不可抢占调度结果。
6. 可抢占原入口改为调用中立层后，应通过金丝雀样例证明输出不变；不可抢占入口从同一中立结果重新构造正式 JSON。

验收标准：同一来源、同一 pipeline mode、同一 topology 的成对输出具有相同任务、依赖、duration 和资源映射；差异只出现在明确记录的 schema/semantics 字段和内容 hash 中。

### P2：建立来源清单和小规模候选池

1. 扫描全部 AICB 文件，保存相对路径、内容 hash、文件名解析值、header 实值和一致性状态。
2. 为 topology 保存相对路径、内容 hash、GPU/交换机/链路数、带宽单位、双向容量含义、路由规则、资源粒度和来源类别。
3. 先选择每个模型族的最小有效配置，再补 PP、DP、EP 和 topology 的单变量配对。
4. 每个候选先只运行 parser、builder、转换和静态统计，不立即发布。
5. 根据真实任务数和分步骤成本选择完整小图、中图和 3 个大图；再从存在真实决策的完整图提取小图。

候选池只保存一次生成记录。相同 source、参数、pipeline mode、topology 和转换器版本必须得到相同 `source_id` 与 `parameter_hash`。

### P3：实现不可抢占竞争审计

审计必须直接调用不可抢占单 channel 或多资源公共状态机。多资源状态保留所有 active communication 及其剩余时间和资源占用，只在空闲资源上枚举新启动集合。

每个决策状态至少记录：

- ready communication 数、active communication 数和空闲资源；
- 合法启动动作或启动集合数；
- work-conserving 极大集合数；
- WAIT 是否合法及其下一个真实事件；
- 是否存在排序选择、集合选择、等待选择和延迟阻塞；
- FIFO、固定顺序和 residual Longest Tail 是否发生动作分歧；
- 决策时间、候选分布、冲突资源和终止原因。

证据等级分开保存：`not_run`、`static_only`、`sampled_prefix`、`completed_replay`、`bounded_search`、`certified_choice_exists`、`certified_no_choice`。完整回放只证明该策略路径上的观察，不证明所有路径；前缀扫描不能写成全图竞争认证；搜索耗尽预算只能返回 unknown。

“有多个动作”和“存在非等价选择”必须分开。若要认证非等价，应分别执行候选完整启动动作，并比较所有影响未来的 residual state；使用对称归一化前必须有等价证明和未压缩小图对拍。

### P4：生成小图、multi-iteration 和 multi-job

小图提取器按第 4.2 节执行，并先在手工可核对的真实小 workload 上验证。不能为了 Exact 可解而改短 duration、删除资源冲突或补造同步边。

multi-iteration 首先驱动 SimAI 提供的重复构建、`JobMerger` 或动态 executor。每个 iteration 使用稳定命名空间，iteration 间的边必须来自原生展开规则。若当前 SimAI 不能导出可核对的原生 N-iteration DAG，则该项标记 `not_supported`；允许把重复投影用于转换性能测试，但不能进入“真实多 iteration 结构”结论。

multi-job 通过 SimAI `JobMerger` 或等价的中立组合层完成：

- 每个 job 保留独立命名空间和原始 job 内依赖；
- 不同 job 之间不增加训练依赖边；
- arrival 只通过真实 job 事件表达；
- 多个 job 共享同一固定资源命名空间和 topology；
- 同构/异构、同时/错峰到达分别标注；
- 4a 的主目标仍为 makespan，同时单列 per-job completion/JCT，不作公平性策略结论。

首次发布只保留少量 multi-job：小图 4--6 个、中图 1--2 个；它们计入第 4.1 节总量，不额外膨胀 corpus。

### P5：staging、审计和原子发布

命令入口保持三个显式阶段：

```powershell
python -m benchmark_generate.llm.nonpreemptive.corpus --mode generate --output benchmark
python -m benchmark_generate.llm.nonpreemptive.corpus --mode audit --output benchmark --manifest <candidate_manifest>
python -m benchmark_generate.llm.nonpreemptive.corpus --mode publish --output benchmark --staging <run_dir>
```

`generate` 只写 versioned staging，不接触活动快照；`audit` 可断点恢复并把详细结果写到 artifact 目录；`publish` 在临时快照完成全部校验后，只切换一个活动指针或一个完整版本目录。

发布前必须检查：文件与 manifest 一一对应、ID/path 唯一、schema 合法、benchmark hash 一致、报告 hash 一致、sidecar 同属一个 `publication_run_id`、index 只引用本次快照。JSON 截断、重复 ID、缺行、多行、hash 错、sidecar 缺失和 index 构建失败时，旧活动快照必须保持不变。

manifest 至少分开保存：

- `conversion_status`；
- `contention_classification`；
- `contention_evidence_level`；
- `publication_status`；
- `baseline_status` 与结果引用；
- `exact_optional_status`、`exact_work_conserving_status` 与结果引用；
- `size_tier`、`source_id`、`source_hash`、`topology_hash`、`parameter_hash` 和 `content_hash`。

不能用一个模糊 `status` 同时表示转换、竞争、发布和实验完成情况。

### P6：逐任务转换对拍

至少选一个任务量最小、含正时长通信的 AICB workload，逐项比较：

- 原始任务 ID 与导出 ID；
- task kind、duration、rank、stage、micro-batch、iteration；
- 原始依赖边、serializer 新增边、重复边和无法解释边；
- communication endpoint、size、route 和固定资源集；
- builder 任务数与导出任务数；
- 可比较的开始/完成事件顺序。

随后使用公共不可抢占模拟器分别验证：每个正时长通信只有一个连续区间；通信期间 compute 完成只释放等待候选；单 channel 不重叠通信；多资源 reservation 保留到通信完成；完成后所有任务和工作量守恒。

原生 SimAI executor 与本项目模拟器的资源共享模型不同，因此 makespan 不要求相等。对拍重点是输入任务、依赖、duration、资源映射和可解释的 serializer 差异；不能拿 SimAI 默认调度结果作为本项目 Oracle。

### P7：统一基线与严格预算

每个正式可运行样例使用同一个公共模拟器和同一套 tie-break，运行 FIFO、输入固定顺序和 residual Longest Tail。三种优先级尽量都在 `optional_idle` 与 `work_conserving` 下运行，至少保证分纲要求的 work-conserving Longest Tail 与 optional-idle Longest Tail 分开报告。

optional-idle 策略只有在模拟器返回 WAIT 为合法动作时才能选择 WAIT；work-conserving 模式在存在可启动通信时不得主动闲置。多资源策略只能从保留 active reservation 后的合法新启动集合中选择，不能移除运行中的通信，也不能强制 optional-idle 动作为极大集合。

建议首轮预算：

| 工作 | 单项墙钟预算 | 说明 |
| --- | ---: | --- |
| 小图单个 Exact、单种口径 | 60 秒 | 另设 state limit；只有 `optimal` 写证书 |
| 中图单个基线、单种口径 | 90 秒 | 每个 case × rule × mode 独立进程 |
| 大图每个转换/加载/审计步骤 | 60 秒 | 分步骤计时，不要求完整回放 |
| 大图可选基线 | 60 秒 | 超时即记录，不自动重跑到完成 |

父进程按墙钟终止子进程并保存最近 checkpoint。计时拆分为 parse、builder、route、serialize、load、feature、schedule、trace rebuild 和 independent validation；不能用循环内软检查冒充严格预算。

每行结果保存 completed/timeout/failed、终止原因、makespan 或 partial simulation time、wall-clock、峰值内存、状态数、决策数、主动 WAIT 次数和时间、forced idle、逐资源利用率、候选数、动作分歧数、fallback、动作 trace hash 和独立验证状态。timeout 行不得进入 makespan 优劣汇总。

### P8：Exact、规模报告和冻结清单

小图分别运行 optional-idle Exact 与 work-conserving Exact，保存上下界、最优首动作、状态数、峰值内存、终止原因和预算。只对 `status=optimal` 的结果生成 reference result；feasible、time_limit、state_limit 和 failed 均不得标成最优。

3 个大图分别偏向：任务数高、边/通信比例高、资源冲突强。报告每个处理阶段的完成、超时或未运行状态，并给出退化边界。大图只用于成本证据，不进入 Exact 最优率，也不因基线超时而从 manifest 删除。

最终冻结清单至少分为：

- 已认证有非等价选择的小图；
- 策略路径上观察到选择的中图；
- 无选择或无竞争负对照；
- 证据不足或超时；
- 3 个规模压力图；
- real-derived Exact 切片；
- multi-iteration 和 multi-job 专用样例；
- invalid、excluded 和 superseded。

Stage 4b--4f 的 runner 只能按不可变 manifest hash 选择输入，传给算法时剥离 provenance、竞争分类和 Exact 答案。

## 7. 测试计划

### 7.1 单元测试

- 新 schema 的合法/非法组合和跨版本读取；
- duration 整数换算、零通信拒绝和固定 route 资源完整性；
- 因果闭包切片不丢失任何保留节点的前驱；
- 单 channel 通信连续且互斥；
- 多资源 active reservation 不被新动作移除；
- WAIT 只推进到真实 compute/job/communication 完成事件；
- optional-idle 与 work-conserving 动作集合不同且结果不混用；
- 多动作但未来等价的反例不能升级为“非等价选择认证”；
- multi-job 无跨 job 依赖且共享资源确实发生冲突；
- manifest 枚举、null 语义、hash 和状态字段校验。

### 7.2 集成测试

- 用 SimAI 自带的小 AICB workload 完成 parser → builder → 导出 → loader → 不可抢占回放；
- 对一个单 channel 和一个固定多资源样例逐任务对拍；
- 对至少一种 pipeline mode 做 serializer 边差异解释；
- 测试 staging 生成、审计断点恢复、发布和回滚；
- 故障注入后活动 manifest、index、sidecar 和 benchmark hash 不变；
- 子进程中故意阻塞的单步操作能被严格墙钟预算终止。

### 7.3 回归测试

先运行不可抢占 R0--R4 的 37 个定向回归，再运行 benchmark、公共模拟器和 trace 测试；若修改公共 model/loader/validator 或转换公共层，运行完整测试。可抢占同源金丝雀输出和已有 v2 加载测试也必须通过，防止抽取中立层时改变另一条研究线。

## 8. 实验与文档归档

实现过程记录到 `docs/nonpreemptive_docs/process_docs/`，结果按独立 run ID 写到 `docs/nonpreemptive_docs/result_docs/`。不要覆盖计划文档、旧 R5 材料或可抢占结果。

建议至少形成：

- `stage4a_source_and_topology_catalog_<date>/`；
- `stage4a_conversion_pairing_<date>/`；
- `stage4a_contention_audit_<date>/`；
- `stage4a_baselines_<date>/`；
- `stage4a_exact_small_<date>/`；
- `stage4a_scaling_<date>/`；
- `stage4a_multi_iteration_multi_job_<date>/`。

每份报告明确输入 manifest hash、代码版本、SimAI commit/dirty 状态、命令、预算、完成/超时数量和不能支持的结论。观察、假设、结论和未知分开书写。

## 9. 推荐执行顺序

1. 新 schema 与旧版本回归；
2. 中立 SimAI 转换层和不可抢占 exporter；
3. AICB/topology catalog 及最小原生 workload 对拍；
4. 候选池生成与真实成本预筛；
5. 不可抢占竞争审计；
6. real-derived 小图与两种口径 Exact；
7. 选择 8--10 个中图并运行统一基线；
8. 固定 3 个大图并完成分步骤规模报告；
9. 补 multi-iteration 与少量 multi-job；
10. 原子发布并冻结 4b--4f 输入清单。

不得先批量生成大图再倒推小图，也不得在竞争状态未知时直接进入 4b 算法收益实验。

## 10. Stage 4a 完成判定

只有以下各项都有机器可读证据，才建议把不可抢占 Stage 4a 标为完成：

1. 发布了以 30--40 个小图为主、8--10 个中图和 2--3 个大图组成的可追溯快照，大图目标为 3 个且不得超过 3 个；若中图少于 8 个或大图少于 3 个，必须记录没有足够合格真实候选的原因；
2. 至少一个原生小 AICB workload 完成逐任务转换对拍；
3. 每个正式样例都有明确的不可抢占竞争分类和证据等级；
4. 中图统一基线在严格预算下完成或如实保留超时/失败；
5. 小图两种动作口径均有 Exact 证书或明确未完成状态；
6. optional-idle 与 work-conserving 的动作、Exact 和结果完全分组；
7. 3 个大图具有转换、加载、审计、回放、内存和退化边界报告；
8. multi-iteration、multi-job 的真实来源、组合规则、对拍状态和缺口均已记录；
9. 发布失败不会破坏旧活动快照；
10. 不可抢占定向回归、转换集成测试和受影响的完整测试通过。

完成 Stage 4a 只表示真实输入和评估门槛建立，不表示 Stage 4b--4f 的结构假设或算法收益已经成立。
