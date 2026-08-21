# Stage 4a 真实 LLM DAG 基准审查结果

日期：2026-08-18  
审查范围：`docs/plan_docs/outline.md`、`docs/plan_docs/stage4_LLM_search.md`、`docs/plan_docs/stage4a_benchmark.md`，以及当前转换器、事务流程、活动语料、测试和已有普查结果。  
审查目标：判断 Stage 4a 是否达到退出条件，并区分已经证明的工程事实、有限实验观察和仍然缺少的研究证据。

## 1. 总体结论

当前 Stage 4a 已经完成了相当一部分基础工程，但尚未完成本阶段研究任务。真实 AICB 输入能够经过 SimAI 转换链生成项目自己的 schema-v2 固定资源 DAG，生成过程有 staging、候选清单和哈希，公共模拟器和 trace 检查也有测试保护。这些工作足以把仓库从“只有手工 motif”推进到“有真实来源的候选语料库”。

但是，`stage4a_benchmark.md` 的退出条件不是“生成了很多 JSON”。它要求每个正式样例都有可解释的竞争报告，并且要用 DP 增加、job 混合、规模和耗时实验说明哪些样例值得后续算法使用。当前活动清单的 72 行全部是 `probed`，但其 probe 只采样最多 8 个决策点；大多数样例没有完成可达状态认证，且没有把 FIFO、Longest Tail 和固定顺序作为统一基线进行完整比较。因此，当前正确的阶段判断是：

> 转换链、语料覆盖和文件审计已基本建立；竞争准入、完整普查、基线曲线、真实多 job 和小图 reference 仍未完成。Stage 4a 不能标记为完成，也不能把 72 个样例直接作为“已认证有竞争”的算法测试集。

## 2. 对照计划的已完成部分

### 2.1 真实来源与转换链

`benchmark_generate/simai/export.py` 负责把 AICB workload 转成项目的预抢占 schema-v2 benchmark。它保留任务依赖、计算顺序、通信类型、端点、阶段和通信资源；有 topology 时用 SimAI 的路由结果生成固定 directed-link、NIC 资源集合，没有 topology 时明确退化为 `channel:0`。导出的语义字段包含通信可暂停恢复、task-event、无主动 WAIT 和固定排他资源集合。`tests/integration/test_simai_export.py` 与 `test_simai_semantics_e2e.py` 覆盖了格式、抢占后工作量守恒、资源原子取得、强制空闲和同刻事件。

`benchmark_generate/llm/catalog.py` 能扫描 AICB 文件并记录源内容哈希，选择逻辑按模型和 topology 做确定性抽样，不是无界地复制所有输入。当前测试确认可解析输入覆盖 Mixtral、GPT 7B/13B/22B/175B 和 Llama 405B 六个模型族，拓扑选择也覆盖生产和实验两类。

### 2.2 当前活动语料规模

直接读取 `benchmark/llm_structure/manifest.jsonl` 得到：

| 指标 | 当前值 |
| --- | ---: |
| 样例数 | 72 |
| 总任务数 | 1,295,870 |
| 总通信数 | 991,568 |
| 单 channel | 32 |
| 固定多资源 | 40 |
| 最小/最大任务数 | 40 / 157,056 |
| DP 重写样例 | 10 |
| 多 iteration 样例 | 3 |
| 控制示例 | 2 |

语料包含 R-C 39 个、R-P 16 个、R-S 17 个。它不是只剩旧版文档中所说的 44 个 Mixtral 文件，实际覆盖面已经扩大；但扩大数量本身不等于竞争质量已经得到证明。

### 2.3 文件和语义审计

本轮实际核验了活动 manifest 与 `benchmark/index.jsonl` 的内容哈希，未发现清单哈希或索引哈希不一致；完整测试为 `169 passed`。生成器、格式、公共执行模型、trace、LLM 特征和可选 integration 测试均通过。这个结果证明当前提交的文件没有明显的格式损坏或公共模拟器回归。

需要注意“测试通过”的边界：测试主要检查转换契约和小型端到端语义，不证明大图的完整可运行性，也不证明每个样例有多于一个合法动作，更不证明某个 heuristic 在真实图上优于基线。

## 3. 竞争准入审查

### 3.1 活动 manifest 的 fast probe 证据不足

`benchmark_generate/llm/corpus.py::_fast_contention_audit` 明确是 `fast_prefix`，最多处理 8 个通信决策。单 channel 只用 `eligible` 数量判断是否存在竞争；多资源只统计当前 eligible 通信之间的资源相交对，并选择一个最大基数的合法集合继续回放。它没有覆盖完整轨迹，也没有记录暂停/恢复是否改变 ready 集合、FIFO 与 Longest Tail 是否选出不同动作、竞争持续时间和释放了多少计算。

因此，manifest 中的 `none_observed_under_probes` 只能解释为“这条 8 决策前缀没有观察到竞争”。大图多数 `certified_probe_status` 是 `not_run_size_limit`，不是“没有竞争”。当前报告把所有 case 的顶层 `status` 都写成 `probed`，虽然内部有 `probe_status=sampled_prefix`，但很容易被下游脚本误读为完整 probe。建议将状态拆成 `sampled_prefix`、`certified_small`、`completed`、`timeout`、`failed` 等互斥状态。

### 3.2 受限普查说明真实选择存在，但尚不足以完成 4a

`docs/result_docs/stage4e_census_full_20260818/summary.json` 是更有信息的已有结果。72 个样例中 47 个在决策上限前停止，25 个达到时间上限；没有一个样例完整结束。受限轨迹中有 35 个样例观察到非等价选择状态。这个结果有两个明确含义：

1. 真实 AICB 派生图确实不是全部无竞争，后续研究有可用的选择状态；
2. 目前的计算成本已经足以阻止“每个大图完整回放”作为默认流程，必须先做分层和可恢复的选择状态抽取。

这份普查仍然不是 4a 退出证据，因为它缺少完整样例的终态、统一的 baseline makespan、每个样例的竞争窗口汇总和失败/超时的可比报告。它应被归档为探索性 bounded census，而不是 canonical competition report。

### 3.3 probe 实现的成本风险

多资源 fast probe 在每个决策调用 `model.legal_actions(state)`，该接口可能枚举所有极大兼容集合。真实大图的 eligible 集合和资源冲突图变大后，这一步的开销可能远高于只构造一个确定性的最大基数集合。计划文档已经要求大图避免无意义地枚举所有 maximal set，但当前 fast probe 仍没有独立的枚举上限、超时、采样策略或 `enumeration_truncated` 字段。

有界认证函数 `_certified_reachable_choice` 也只对不超过 500 个任务的图运行。这个限制本身是合理的，但结果必须明确标记为“在状态上限内完成”或“因规模未运行”，不能与真实大图混在一个布尔字段中。

## 4. 来源、投影和真实性边界

### 4.1 DP 重写不是原生训练运行

`benchmark_generate/llm_structure.py` 的 DP 扩展通过重写 AICB header 的 `all_gpus`，把原来 `dp=1` 的逐层数据投射到更大的 world size。文件记录了 `source_dp`、`requested_dp`、`effective_dp` 和 `dp_rewrite`，这是好的审计做法；但它仍是 parallelism rewrite projection，不是从一个原生 DP>1 workload 获得的任务序列。R-C 样例可用于研究“固定转换模型下 DP 变化如何影响资源冲突”，不能直接写成原生生产 DP 运行结论。

### 4.2 多 iteration 仍是结构投影

当前有 3 个多 iteration 文件，但活动语料字段把它们标为 `structured_projection`，且计划中已指出需要和 SimAI 原生展开逐项对拍。没有对拍前，只能研究当前重复和连接规则产生的结构；不能声称它已经复现 SimAI 的 warmup、steady state、cooldown、optimizer/barrier 边界。

### 4.3 duration 与 topology 的含义

转换器用 `ceil(size_bytes / (bandwidth_gbps * 125))` 得到整数微秒，并在 topology 模式中把 route 冻结为资源集合。这是一个清楚、可复现的模拟时长模型，但不是逐链路动态拥塞、collective 协议分段速率或生产测量数据。生产 topology 的结果应称为“生产拓扑结构投影下的模拟结果”，不能称为生产网络性能。

代码中 `metadata["topology"]` 来自 `str(topology_path)`；源码上会把本机绝对路径写入导出 benchmark 的 metadata。即使当前 manifest 使用了拓扑名称和内容哈希，直接分发 JSON 仍可能带有不可重建的路径。路径应改为来源文件名或相对标识，绝对路径只保留在运行元数据中。

## 5. 规模、失败和可重现性

### 5.1 规模分布不等于规模实验

当前 72 个样例中只有 4 个超过 50,000 个任务，46 个处于 5,000--50,000 任务区间；这可以作为规模分布，但没有对应的生成耗时、转换耗时、probe 耗时、内存峰值和各基线运行时间报告。计划要求约 10 个超大 DAG 的专门规模观察，目前应判定为未完成。

### 5.2 事务流程尚未达到真正的发布原子性

`benchmark_generate/llm/corpus.py::publish` 在提供 staging 时先把活动 `preemptive` 目录移到备份，再把 candidate 目录移入活动目录，但在移动前没有逐文件重新 `load_benchmark`、`validate_benchmark` 和核验 candidate manifest 哈希；如果后续写 manifest 或构建 index 失败，旧目录已被移动，恢复需要人工处理。`source_catalog.jsonl` 和 staging 的 `run_metadata.jsonl` 也没有随 candidate 一起以同一事务替换活动元数据。现有活动文件没有因此损坏，但该实现不能称为完整的发布事务。

### 5.3 dirty 状态已记录，但缺少发布时的强制检查

活动 `run_metadata.jsonl` 记录了生成时的 HEAD、dirty 标记和 diff hash，这是正确方向。不过生成时间的 commit 与当前 HEAD 不同，且工作区有用户修改；后续结果若只引用当前 HEAD，会无法重建当时的 corpus。发布和实验入口应强制写入 git 状态、未跟踪文件清单哈希、SimAI checkout commit、转换器版本和 benchmark manifest hash，并在结果中明确 dirty。

## 6. Benchmark 分层和覆盖缺口

### 6.1 生产、实验和统一资源样例已经区分，但主表仍需分层

manifest 有 R-P、R-S、R-C 和 topology tier 字段，这使后续筛选成为可能。然而当前 39 个 R-C 统一资源或 DP rewrite 样例数量较多，容易在汇总时掩盖只有 16 个 R-P 和 17 个 R-S 的真实路由结果。结果表必须按 topology tier、model family、DP、iteration 和 suite 分层，并同时报告 unique source 数，不能把同一 workload 的投影和重复 iteration 当作独立真实来源。

### 6.2 multi-job 仍然缺失

活动 corpus 的两个 `simai_examples` 是控制样例，不是 AICB 多 job 混合；从真实活动 JSON 中没有形成两个以上独立 job 的正式 case。因此 4a 的 job 增加实验和 4f/4h 的真实多任务输入尚未开始。不能把单 job DP rewrite 或重复 iteration 当作多 job 竞争。

### 6.3 reference result 缺失是可接受的，但必须显式记录

当前没有 `benchmark/reference_results/llm_structure` 的正式 reference 文件。这对 157,056 任务的大图是合理的，不能强行运行 Exact；但小图真实切片、两个 SimAI 示例和未来的资源 hotspot 切片应有明确的“无 reference / 待生成 / 超预算”状态。否则下游容易把没有 sidecar 误解为忘记生成或把 heuristic 结果当作最优。

## 7. 文档和入口不一致

`benchmark/llm_structure/README.md` 仍写着“当前冻结的 44 个 case”，并使用不存在的 `benchmark_generate.stage4` 命令；当前事务入口实际是 `python -m benchmark_generate.llm.corpus --mode generate|probe|publish`。这会直接阻碍复现，也会让读者误判当前语料范围。README、`benchmark_generate/README.md`、manifest 字段说明和过程文档必须统一到 72-case 当前事实，并明确 fast-prefix、bounded census、canonical case 的区别。

## 8. 逐模块实现审查

### 8.1 `benchmark_generate/llm/catalog.py`

优点：文件名解析采用明确正则，world size 与 `tp*pp` 不整除时拒绝输入；source catalog 记录内容哈希；canonical 选择按模型和拓扑容量确定，结果可重复。测试要求六个模型族和全部已登记拓扑都有覆盖，避免语料继续停留在 Mixtral 单一来源。

限制：`dp` 的解析只使用 `world_size/(tp*pp)`，没有把 EP 是否独立占用并行维度写进验证公式。当前输入和生成器又限制 `ep==1`，所以没有立即产生错误，但 source catalog 会给人“已覆盖 EP”的错觉。后续引入 EP>1 前必须根据 SimAI/AICB 的实际 rank grouping 写清 DP、TP、PP、EP 的关系，而不是延用文件名推断。

`canonical_routed_specs` 为每个 model/topology 选取一个低工作量 source，并在生产拓扑上增加有限 DP 档。这对控制数量有效，但不是按竞争强度抽样。选择键偏向低 gbs/mbs 和较大 PP，可能系统性偏向启动阶段长、稳态短或通信形状相似的实例。canonical v1 应先用当前规则生成候选，再根据独立 probe 结果决定准入，不能让选择规则本身使用算法结果或 metadata 中暗示答案的字段。

### 8.2 `benchmark_generate/simai/export.py`

依赖处理使用 `_effective_dependencies()`，在 SimAI 任务原始依赖之外加入 serializer 给出的 compute order。这样做符合“有限计算顺序必须由 DAG 边表达”的项目语义，也避免 simulator 另建计算资源。集成测试已经检查不同 pipeline mode 能输出有效 DAG。

需要补的关键对拍是：加入的 compute order 边是否和 SimAI 原始执行顺序逐 rank 一致，是否会在 zero-bubble、interleaved、dualpipe 等模式中添加过强依赖。当前测试更多检查输出合法，不逐项比较原始 task/edge 和 effective DAG。Stage 4a 正式结论应保留 raw dependency count、serializer-added edge count 和按模式的对拍摘要。

资源映射方面，BFS route 被固定成 directed link 加 endpoint NIC，满足不动态选路、不部分取得资源的目标语义。仍需增加两类失败测试：route 缺失或空路径时必须拒绝有正工作量的通信；topology 中同一物理瓶颈若由两个方向或多个逻辑 link 表达，转换器必须说明是否共享容量。当前 `directed_link` 会把反向链路视为独立资源，这是模型选择，不一定是物理事实，应写入 topology contract。

duration 对所有 route 只使用一个 topology 级带宽参数，没有根据每条 link 的容量变化。这种简化已经在 metadata 中部分说明，但 `duration_model.name` 应包含版本，且转换器不能因为 topology 文件里存在不同链路属性就让读者误以为都被使用。

### 8.3 `benchmark_generate/llm_structure.py`

`unified_cases()`、`dp_override_cases()`、`routed_cases()` 和 `multi_iteration_cases()` 清楚分开，输出路径也分层保存。这比把所有文件放在一个 real 目录更利于审计。`_try_add()` 会保留生成失败信息，长时间生成时由 corpus 的 `on_case` 每例写盘和 checkpoint，减少全批次失败损失。

主要问题是该模块同时保留旧 `write_manifest()`/`competition_report()` 路径和新 `llm.corpus` 事务路径。旧函数会完整回放并写另一种 manifest 结构，新路径写 `probe` 字段；两套字段和状态不一致，后续维护者可能调用旧函数得到不同证据。兼容入口应只保留明确 deprecated 的薄封装，旧 manifest writer 至少要从公开文档移除，或者重构为调用同一 report/schema 实现。

`build_corpus()` 返回 skipped 列表，但 active publish reconciliation 只扫描成功 JSON；如果失败记录没有来自 staging candidate manifest，就可能在重新 reconcile 时消失。失败、invalid、timeout 和 excluded 是 corpus 的一部分，应保存在独立 attempt manifest，而不是只依赖当前成功文件重建。

### 8.4 `benchmark_generate/llm/corpus.py`

这是当前 Stage 4a 最重要的基础设施。优点包括：生成写 versioned staging；每个 case 成功后立即验证、写文件和刷新 candidate manifest；git 状态同时记录 HEAD、dirty 和 diff/untracked 名称哈希；probe 按 case 写独立报告；active 存在时默认拒绝无意覆盖。

需要修正的细节如下：

- `_git_state()` 对未跟踪文件只哈希文件名列表，不哈希文件内容；dirty bundle hash 不能真正重建未跟踪源码。应至少哈希未跟踪的相关源码内容或保存 source bundle hash。
- `artifact_root` 被计算但没有用于 `reports_root`，实现和注释“报告在 benchmark 外”不一致。当前报告后缀是 `.jsonl`，不会被 JSON indexer 当 benchmark，但路径合同仍应修正。
- `probe()` 没有 per-case timeout。slow report 如果在一个大图上卡住，当前 Python 进程不能自己跳到下一个 case；`timeout` 状态集合存在但主流程不会主动产生该状态。
- probe checkpoint 只保存最终报告，没有可恢复的 simulator 状态或动作前缀；所谓 resume 实际是跳过已完成 case，不是从 partial case 的决策点继续。对大图应明确称为 per-case restart，或实现动作前缀重放后继续。
- fast probe 的 `probe_runtime_ms` 有记录，但 generate/export 单例耗时、peak memory 和 publish 耗时没有进入 manifest。
- publish 重新 reconcile active corpus 时会复用旧 hash 相同 case 的状态，这是合理的；但如果 probe config 改变而 benchmark hash 不变，旧 probe 仍被复用。复用条件必须同时比较 `probe_config_hash` 和 report schema version。

### 8.5 `experiments/llm_structure/contention_census.py`

该 runner 比 fast probe 更接近后续需要：有 `max_decisions`、`time_limit_s`、每例原子 checkpoint、benchmark hash、trace prefix hash、choice state 和 termination reason；多资源在 eligible 数超过阈值时不展开所有 maximal set。这些设计应回迁到 Stage 4a 公共 audit 工具，而不是只留在 Stage 4e 实验脚本中。

但它仍存在证据边界：

- 单 channel 只沿 Longest Tail 一条轨迹扫描；其他合法调度可能到达不同选择状态。
- 多资源 eligible 超过枚举阈值时 candidates 只有 LT greedy 集合，因此这类状态即使存在其他合法集合也不会被记为 choice。
- `resume` 只跳过 completed 文件，而当前 72 个都不是 completed，重跑会从头开始。
- 输出没有独立 trace replay；它保存状态和动作摘要，但完成/partial 结果没有统一调用 trace validator。
- summary 把 partial 和 timeout 合并进 `partial_count`，顶层又分别有 status，汇总字段容易掩盖两者差异。

因此这套 census 是很好的工程原型，不应直接升级为 Stage 4a canonical report。应先统一 schema、补 trace 和基线，再迁移。

### 8.6 schema、loader 和 validator

公开 benchmark 的 schema-v2 能表达语义字段和固定资源，loader/validator 检查任务、依赖、资源引用和 DAG 合法性。当前 72 个文件全部通过格式测试，index 也覆盖全部 JSON。

Stage 4a 专有的 manifest、run metadata、source catalog 和 contention report 目前没有独立 JSON Schema。字段拼写、状态取值和 null 语义只靠代码约定，旧/新 writer 已经出现 `competition` 与 `probe` 两套结构。建议为这些 sidecar 建 schema，并在 publish 与 CI 中验证。它们不是算法输入，但决定研究结果能否追踪，不能只当普通日志。

## 9. 测试覆盖审查

### 9.1 本轮实际执行

本轮执行完整 `python -m pytest -q`，结果为 `169 passed`。另外单独运行了 Stage 4a 相关的格式、布局、catalog、integration、生成器和边界测试；活动 manifest/index 哈希均无不一致，benchmark_id 无重复。测试环境能够收集 SimAI integration，因此本轮不是“integration 被静默跳过”的全绿。

### 9.2 已覆盖的失败模式

- schema-v2 语义显式存在，非依赖默认值；
- communication pause/resume 的工作量守恒；
- 多资源 action 是极大兼容集合；
- communication 同时取得全部固定资源；
- eligible communication 存在时不能主动 WAIT；
- forced idle 由 simulator 推进；
- 同一时刻 compute 完成原子处理；
- 六个模型族、所有登记拓扑和 DP 容量约束；
- benchmark/index 的路径与 hash 完整性。

### 9.3 尚缺测试

- staging candidate 损坏、hash 不符、publish 中途异常时 active 不变；
- source catalog/run metadata 与 active manifest 属于同一 run；
- probe 配置变化后不得复用旧 report；
- slow probe 超时能写 `timeout` 并继续下一 case；
- fast multi-resource 不会在大 eligible set 中完整枚举；
- 公开 JSON 不含本机绝对路径；
- DP rewrite 的 rank、collective 和资源端点与预期逐项对拍；
- native multi-iteration 对拍；
- 两个真实 AICB job 混合后无跨 job DAG 边；
- report sidecar schema 和状态机；
- 真实来源小切片 Exact 与 trace replay。

## 10. 问题优先级

### 阻断 Stage 4a 退出

1. 72 个活动 case 没有完整竞争准入和统一基线结果。
2. 没有真实 AICB multi-job，job 增加实验为空。
3. 没有 DP 竞争曲线和约 10 个大图的统一成本报告。
4. fast probe/partial census 的状态容易被解释为完成。

### 发布和复现高风险

1. staging publish 未在替换 active 前逐文件验证和核验 hash，也没有自动 rollback。
2. probe 无 per-case timeout，旧报告可在 config 变化后被复用。
3. 活动 JSON 可能包含本机绝对 topology path。
4. manifest/report/source catalog 没有机器可读 schema。

### 可以后续修正

1. 清理旧 manifest writer 和兼容入口；
2. 将 Stage 4e census 的预算/checkpoint 能力迁到 Stage 4a；
3. 增加 EP>1 前明确 rank grouping；
4. 丰富 link capacity 和 collective duration 模型，但必须另立版本，不能静默改变当前结果。

## 11. 阶段判定

按 `stage4a_benchmark.md` 的五个退出条件逐项判断：

| 退出条件 | 判定 | 依据 |
| --- | --- | --- |
| 转换依赖、资源和 trace 语义经小图与端到端检查 | 基本满足 | 相关 integration 与完整测试通过；真实大图仍不是逐图证明 |
| 每个正式样例都有可解释竞争报告 | 未满足 | 活动 probe 只是 8 决策前缀；完整 census 也均 partial/timeout |
| DP 增加和 job 混合有竞争强度曲线 | 未满足 | 有 DP rewrite 样例，无系统曲线；无正式真实 multi-job |
| 普通规模和约 10 个超大样例的时间预算已测量 | 未满足 | 没有统一的生成/转换/基线/内存报告 |
| 明确哪些输入无竞争、哪些适合后续算法 | 部分满足 | bounded census 发现 35 个有非等价选择，但没有 canonical 分层准入 |

因此本阶段状态应写为“基础设施完成，研究退出条件未完成”。

## 12. 审查后的研究边界

当前可以安全使用的结论只有：真实 AICB workload 能被转换为统一 simulator 可执行的固定资源 DAG；来源和内容哈希可以追踪；在受限轨迹中确实观察到非等价通信选择；Longest Tail、packing 和 selective rollout 的后续研究有真实输入基础。

当前不能使用的结论包括：所有 72 个样例都存在调度竞争；DP rewrite 等同原生 DP 训练；多 iteration 等同 SimAI 原生流水；生产 topology 模拟等同实测性能；某一结构或算法在真实 LLM DAG 上普遍有效；或者 72 个样例已经完成 Stage 4a 验收。
