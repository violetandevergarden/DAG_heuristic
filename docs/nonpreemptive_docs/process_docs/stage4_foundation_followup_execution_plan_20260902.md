# 不可抢占 Stage 4 基础问题第二轮执行计划

日期：2026-09-02

## 1. 计划目的

本计划是 `stage4_performance_fidelity_and_contention_benchmark_plan_20260902.md` 的第二轮执行方案，针对第一轮实现和复核中确认的缺口继续推进。它不覆盖原计划，也不把已经完成的入口建设重复记为研究结论。

第二轮集中完成四件事：

1. 把基础调度、正式验证、冲突观测和性能分析彻底分开，去掉默认内存跟踪、观测器重复计算和搜索内部的二次回放；
2. 在固定中图上完成可信的三次重复性能验收，明确 30 秒超时究竟发生在哪个阶段；
3. 补齐 SimAI 静态转换审计的结构覆盖和逐字段对拍，修正当前 `matched` 证据过宽的问题；
4. 在真实来源、真实组合和受控投影三类输入中寻找质量冲突，形成真正可用于后续算法研究的小图和中图，或者形成明确的否定结论。

本计划仍不恢复超大图完整质量实验，不提前进入 Stage 4g，也不因为基础性能已经改善就自动重新开放 4c--4e 的复杂算法。

## 2. 第一轮复核后的基线

### 2.1 已经确认有效的部分

- 已冻结 8 个中图清单，当前文件内容 hash 与清单全部一致；
- `bare`、`validated`、`instrumented` 已经具有不同职责，三者在已测 918-task 图上得到相同 makespan 和动作摘要；
- 中图公共不可抢占运行层能够完成基础 LT；
- 34 个 source 候选池能够覆盖 6 个模型、GA 1/4/8、PP 1/2/4、多个 TP、Mixtral EP 1/2/4/8 和两个 topology；
- 10 个已经完成的静态转换样例没有发现无法解释的依赖缺失或新增；
- 旧 real-small Exact 标签的统计可复算：243 个标签中 94 个存在非零动作代价差异，覆盖 23 个 benchmark，最大差异为 3636，LT regret 为正的标签为 0；
- 本轮直接修改范围 Ruff 通过，定向测试通过；完整测试只剩两项旧的固定总数断言失败。

### 2.2 尚不能作为正式结论的部分

- 当前三条运行路径全部启用 `tracemalloc`，计时被明显放大；
- 8 个中图尚未完成固定口径的三次重复；
- timeout 只记录为硬预算终止，不能指出最后完成的阶段；
- 当前运行记录只保存 commit，没有保存工作区是否有未提交改动和 diff 摘要；
- 静态转换实际运行的前 12 个样例只覆盖 5 个模型、PP 1/2 和 EP=1，没有满足原计划的分层要求；
- `matched` 尚未逐字段核对 builder 与导出 task 的 id、kind、src/dst、size、duration 和结构 metadata；
- 冲突 census 只运行了 26 个旧单 channel real-derived 小图；
- 多资源审计仍可能先完整枚举合法集合，再执行数量截断；
- `time_limit_s` 尚未真正限制冲突审计运行时间；
- 没有新增自然困难中图、真实组合压力图或保持首动作排序的 residual decision window。

### 2.3 本轮抽查性能，只作为方向判断

在当前机器、单进程、关闭 `tracemalloc`、使用公共 LT 和最终一次独立回放的条件下，单次抽查结果为：

| 输入 | task 数 | validated 总时间 |
|---|---:|---:|
| GPT-13B PP=2 | 640 | 0.87 s |
| GPT-7B | 838 | 1.57 s |
| Mixtral 单 channel | 2038 | 6.31 s |
| Mixtral routed Alibaba | 2038 | 14.54 s |

同一 918-task 图在启用 `tracemalloc` 时记录为约 7.80 秒，关闭后约 1.74 秒。这说明下一步应先修正测量方法和观测器，而不是直接重写公共模拟器。上述数字只有一次运行，不替代后续三次重复的正式结果。

## 3. 不可改变的边界

- 只处理不可抢占 Stage 4 运行层、实验入口和生成审计代码；不顺带重构可抢占算法。
- communication 启动后连续执行到完成，不新增暂停、恢复或切换。
- optional-idle 与 work-conserving 分开运行和报告。
- 多资源 active communication 持续保留全部资源，新动作只使用剩余空闲资源。
- 算法、观测器和性能分析器都不得自行实现时间推进。
- 快速运行可以不做独立回放，但不能把其结果标记为 `trace_valid=true` 或直接发布为正式质量结论。
- 正式入表的完整调度结果必须至少经过一次独立 trace 回放验证。
- 内存跟踪、函数性能分析和冲突特征不得混入基础运行时间。
- 自然真实、真实组合、受控投影继续分组，不混表。
- 不发布超出当前中图处理能力的大图质量结果。

## 4. 工作包 E0：修正运行职责和证据来源

### 4.1 四种运行职责

将当前入口明确拆成四种职责，而不是让一条路径同时承担所有工作。

#### A. `bare`

用途：基础性能、快速筛选、rollout 内部 completion。

只执行：

- benchmark 加载和模型构造；
- 策略选择；
- 公共模拟器状态转移；
- 最终 makespan、动作数和动作摘要。

默认不执行：

- `tracemalloc`；
- 函数性能分析；
- 多策略观测；
- 独立 trace 回放；
- trace 合法性声明。

`trace_valid` 必须为 `null`，不能因为模拟器正常结束就写成 `true`。

#### B. `validated`

用途：正式基线、候选算法最终结果、发布前验收。

执行 `bare` 的全部内容，并在完整动作序列结束后执行一次独立回放，验证：

- DAG 依赖；
- compute 连续执行；
- communication 连续执行；
- 单 channel 或固定多资源排他；
- active reservation；
- 最终完成状态；
- makespan 与首次执行一致。

不得在 rollout 的每个候选、每个深度和每个中间状态执行二次回放。搜索内部只走公共状态转移；搜索选出的最终完整调度再走一次 `validated`。

#### C. `instrumented`

用途：冲突 census、特征消融和算法成本解释。

在不启用 `tracemalloc` 的前提下记录：

- ready、active、合法动作数；
- 各简单策略动作；
- 策略分歧；
- WAIT 和非极大动作合法性；
- 多资源占用；
- 必要的结构标签。

同一决策点的 ready、active、legal action、tail 和下一事件只计算一次。观测器从统一决策上下文读取结果，不允许为 FIFO、固定顺序、LT、SPT、LPT 和随机对照分别重算全部特征。

中图默认只观测前 64 或 128 个决策。只有轻量观测已经完成且有必要时，才执行完整轨迹观测。

#### D. `profiled`

用途：内存和函数热点诊断。

它与前三种质量路径分开执行，分为：

- `memory_profile`：单独启用 `tracemalloc`；
- `cpu_profile`：单独启用函数性能分析；
- `allocation_profile`：只有前两者仍无法定位时才启用。

性能报告必须把 `profiled` 标记为带测量扰动的数据，不得与 `bare` 或 `validated` 的 wall-clock 放在同一列求均值。

### 4.2 代码调整位置

优先修改：

- `experiments/llm_structure/nonpreemptive/foundation/runtime_diagnosis.py`；
- `experiments/llm_structure/nonpreemptive/stage4_runtime_breakdown.py`；
- `src/llm_structured/nonpreemptive/runtime/contracts.py`；
- `src/llm_structured/nonpreemptive/runtime/replay.py`；
- `src/llm_structured/nonpreemptive/runtime/policies.py`；
- `src/llm_structured/nonpreemptive/runtime/features.py`。

如需统一决策上下文，可在 runtime 中新增小型只读数据类，包含：

- 当前 state；
- ready communication；
- active compute/communication；
- 合法动作；
- residual tail；
- 第一次 ready 的时间；
- 下一真实事件；
- 空闲与占用资源。

不要让该数据类拥有 `step` 或时间推进能力。

### 4.3 运行来源记录

每次正式运行新增 `run_config.json`，至少保存：

- 运行编号和开始/结束时间；
- 命令行参数；
- manifest hash；
- benchmark content hash；
- git commit；
- 工作区是否有未提交改动；
- 若有未提交改动，保存受影响文件清单和 diff hash，不在结果中复制完整源码；
- Python 版本；
- CPU 型号、逻辑核心数、物理内存；
- 单进程或并发进程数；
- 运行前系统负载摘要；
- 是否启用内存跟踪或函数性能分析。

运行开始前重新计算每个 benchmark hash。任何不一致必须标记为 `input_hash_mismatch` 并停止该 case，不能继续运行后沿用清单中的旧 hash。

### 4.4 timeout 阶段定位

子进程在运行目录写入轻量阶段标记：

1. `loading`；
2. `model_build`；
3. `policy_loop`；
4. `observation`；
5. `trace_replay`；
6. `trace_validation`；
7. `completed`。

阶段标记只在阶段切换时原子更新，不在每个决策写磁盘。父进程终止超时子进程后读取最后阶段，并记录：

- `termination_reason=hard_subprocess_budget`；
- `last_completed_phase`；
- 已完成决策数；
- 最后模拟时间；
- 是否进入回放和验证。

若无法安全获得决策数，允许为 `null`，但不能猜测超时模块。

### 4.5 E0 退出条件

- 四种职责在代码和输出字段中明确区分；
- `bare`、`validated`、`instrumented` 默认均不启用 `tracemalloc`；
- `profiled` 结果明确标记测量扰动；
- 三条调度路径在小图和至少一个中图上 makespan、动作摘要一致；
- timeout 可以给出最后阶段；
- 输入 hash、commit 和工作区状态可追溯。

## 5. 工作包 E1：消除观测器重复计算

### 5.1 当前需要处理的重复工作

第一轮代码中至少存在以下重复：

- 单 channel residual tail 每个调用重新构造 children；
- 一个动作选择中，排序和 WAIT 判断可能分别计算 tail；
- instrumented 路径为多个简单策略分别调用完整基线动作函数；
- 策略选择和 `step` 合法性检查可能分别构造合法动作；
- active compute 和下一事件在同一决策中被多次扫描；
- 多资源观测可能先构造完整合法集合，再执行截断。

### 5.2 低风险处理顺序

1. 在单 channel 模型构造时缓存 children、compute 索引和 communication 索引；
2. 在每个决策点只构造一次决策上下文；
3. `_rank`、WAIT 判断和观测器统一接收同一 tail、active 和 legal action；
4. FIFO/固定顺序/SPT/LPT/随机策略只做不同排序，不重复查询状态；
5. Stage 4d depth=0、Stage 4e method=LT 继续直接使用基础 LT；
6. 多资源先取得 startable flow 和空闲资源，再由各贪心策略构造一个合法集合；
7. 只有 ready flow 数低于冻结阈值时，才允许枚举全部或极大集合。

不在本轮优先修改公共状态表示、Exact state key 或事件推进逻辑。只有完成三次性能验收后仍不达标，才重新评估增量 ready 集和紧凑状态等高风险优化。

### 5.3 缓存失效要求

- 静态 children、拓扑序和任务分类只与模型绑定；
- residual tail、ready、active 和 legal action 只与一个不可变 state 绑定；
- `step` 后不得复用旧 state 的动态缓存；
- optional-idle 与 work-conserving 的合法动作缓存必须分开；
- active reservation 变化后必须重新计算空闲资源和 startable flow。

### 5.4 E1 测试

新增或加强：

- 同一 state 共享上下文前后的策略动作一致；
- optional-idle/work-conserving 动作集合一致；
- WAIT 判断前后结果一致；
- residual tail 缓存值与无缓存参考实现逐状态一致；
- 30 个 real-small 图上 FIFO、固定顺序、LT 的 makespan 和动作摘要不变；
- Stage 1--3 WAIT、非极大启动和 active reservation 反例不变；
- 小图 Exact 最优 makespan 和首动作集合不变；
- 多资源贪心集合经过模拟器 `validate_action`，不依赖观测器自行判断合法性。

### 5.5 E1 退出条件

- 单决策 tail 的实际计算次数为 1；
- ready、active、legal action 不因策略数量线性重复；
- instrumented 相对 bare 的额外时间可以归因到新增统计，而不是重复状态扫描；
- 所有动作、trace 和 Exact 回归一致。

## 6. 工作包 E2：中图正式性能验收

### 6.1 固定输入

继续使用当前 8 个冻结中图：640、838、918、1078、1200、2038 单 channel，以及两个 2038 routed。

不得在性能验收完成前替换图或修改其内容。若 manifest hash 不一致，先修正清单或恢复输入，并单独说明原因。

### 6.2 运行矩阵

每个输入按以下矩阵运行：

| 路径 | 重复次数 | 硬预算 | 内存跟踪 | 独立回放 |
|---|---:|---:|---|---|
| bare LT | 3 | 90 s | 否 | 否 |
| validated LT | 3 | 90 s | 否 | 是 |
| instrumented LT，前 128 决策 | 3 | 90 s | 否 | 最终结果需要时一次 |
| memory_profile bare | 1 | 90 s | 是 | 否 |
| memory_profile validated | 1 | 90 s | 是 | 是 |

不再把同一配置分别在 10、30、90 秒下重复三遍。统一使用 90 秒硬上限，并根据实际完成时间同时标记是否通过 10 秒和 30 秒门槛。只有研究算法有独立预算时，才另外执行相应硬预算。

运行顺序按 case 轮换，避免所有第三次重复都受到相同的系统热状态影响。正式计时期间不并行运行其他实验进程。

### 6.3 分项时间

每次至少记录：

- 加载；
- 模型构造与 DAG 校验；
- 决策上下文；
- 策略排序；
- 状态转移；
- 观测统计；
- 动作摘要；
- trace 重放；
- trace 验证；
- 总时间。

对 timeout 只报告已经完成阶段，未完成阶段不填写估算值。

### 6.4 性能门槛

- 640/838 validated LT 三次中位数不超过 10 秒；
- 2038 单 channel 和两个 routed validated LT 三次中位数不超过 30 秒；
- 三次波动范围同时报告，不以最小值代替中位数；
- instrumented/validated 倍数单独报告；
- depth=0 Stage 4d 相对 bare LT 的额外时间不超过 50%；
- Stage 4e method=LT 与公共 validated LT 的时间差不超过 50%，且动作摘要一致；
- 开启 `tracemalloc` 的倍数只作为测量扰动记录，不作为模拟器性能结论。

如果干净的 validated 已通过门槛，则停止公共模拟器性能重写。后续只优化具体算法的特征、候选和搜索调用量。

### 6.5 E2 结果产物

- 新运行目录使用独立 run id，不覆盖第一轮 `stage4_runtime_diagnosis_20260902/`；
- 建议目录：`stage4_runtime_diagnosis_v2_20260902/`；
- 汇总文档：`stage4_runtime_optimization_followup_result_20260902.md`；
- 文档同时保存正常计时和带内存跟踪计时，但明确分表。

## 7. 工作包 E3：补齐 SimAI 静态转换保真

### 7.1 冻结显式审计清单

候选池和正式审计清单分开：

- `selected_specs(..., max_sources=32)` 只负责产生候选池；
- 新增 `conversion_cases.jsonl` 显式冻结正式样例；
- 不再通过候选池的前 `N` 个代替覆盖设计。

清单至少覆盖：

- 6 个模型各至少 1 个；
- GA 1/4/8；
- PP 1/2/4；
- 至少两个 TP 档位；
- Mixtral EP 1/2/4/8；
- dense 与 MoE；
- 单 channel；
- Alibaba 和 Cassini 两个 routed 投影。

一个样例可以同时满足多个覆盖项。清单生成后输出覆盖矩阵；任何必需格为空时，runner 在执行前失败，而不是运行后才由人工发现。

### 7.2 task 逐字段对拍

不能只比较 preemptive/nonpreemptive 最终 task 是否相等。对 builder、serializer 和导出层建立可追溯映射，逐 task 检查：

- 原始 id 与导出 id；
- kind；
- src/dst；
- communication size；
- compute duration；
- raw dependencies；
- serializer 新增 dependencies；
- effective dependencies；
- 导出 dependencies；
- iteration、micro-batch、pipeline stage、phase；
- TP/PP/EP/DP 维度；
- route 与固定资源；
- nominal duration 的计算输入和结果。

若一个 builder collective 展开成多个 P2P task，保存完整展开映射，不能只依赖最终 task 数相等。

### 7.3 serializer 统计修正

分别记录：

- `raw_edge_count`；
- `serializer_attempted_edge_count`；
- `serializer_new_edge_count`；
- `serializer_duplicate_raw_edge_count`；
- `effective_edge_count`；
- `missing_edge_count`；
- `unexplained_edge_count`。

不能把所有保留下来的 raw edge 计为“重复边”。如果当前 `_effective_dependencies` 无法区分 serializer 尝试新增的边，需要在生成层增加只读审计返回值，而不是根据集合交集猜测。

### 7.4 mismatch 保存

每个不一致结果保存完整差异文件，包括：

- task 字段差异；
- 缺边；
- 附加边；
- route/resource 差异；
- metadata 差异；
- 对应 source hash、topology hash、参数 hash 和代码版本。

摘要文件只保存计数和差异文件路径。若差异文件过大，可以压缩，但不能只截取前 20 条。

### 7.5 预算与状态

先按每例 10 秒运行。timeout 仍保留在 10 秒结果中标为 `unknown_timeout`。如需追加 30/90 秒诊断，写入单独结果表，不能用长预算结果覆盖短预算状态。

分类继续使用：

- `matched`；
- `explained_transform`；
- `model_mismatch`；
- `conversion_bug`；
- `not_supported`；
- `unknown_timeout`。

只有 task、dependency、route/resource 和规定 metadata 均完成逐项核对的样例，才可标记完整静态 `matched`。只完成依赖核对的样例应标为 `dependency_matched` 或在分项状态中说明，不使用过宽结论。

### 7.6 动态边界

本轮优先完成静态审计。以下项目如果仍无法驱动，继续如实标记：

- dynamic ready/start/finish：`not_supported`；
- native N-iteration：`not_supported`；
- native multi-job timeline：`not_supported`。

不得为了消除 `not_supported` 而用项目自己的回放冒充 SimAI native executor。

### 7.7 E3 退出条件

- 正式审计清单覆盖矩阵无缺项；
- 至少 12 个样例完成或如实记录独立 timeout；
- 每个已完成样例具备逐 task、逐 edge、逐 route/resource 的结果；
- 所有 mismatch 有完整差异文件；
- 没有未处理的 task/dependency conversion bug；
- duration、route、NIC、latency 和 collective 协议的简化边界独立成表。

## 8. 工作包 E4：修正冲突审计器

### 8.1 真正执行 wall-clock 门槛

当前 `time_limit_s` 不能只写进结果。每个 case 使用独立子进程执行，父进程实施硬预算，并保留：

- 决策上限；
- wall-clock 上限；
- 最后阶段；
- 已完成决策数；
- 是否完成整图；
- 是否因动作集合过大提前停止。

中图默认采用“前 128 个决策或 30 秒，先到者停止”。timeout 不解释为无冲突。

### 8.2 多资源路径禁止先全枚举后截断

多资源轻量 census 改为：

1. 查询 active communication 和 occupied resources；
2. 计算剩余空闲资源；
3. 查询 startable flows；
4. 各简单策略构造一个合法启动集合；
5. 使用模拟器公开校验接口验证动作；
6. 记录不同策略集合是否分歧。

只有同时满足以下条件才允许完整集合枚举：

- ready/startable 数不超过冻结阈值；
- 预计集合数不超过上限；
- 当前 case 仍有剩余时间预算。

超过阈值时记录 `enumeration_skipped=true`，不能先调用 `legal_actions()` 或 `start_subsets()` 生成完整幂集后再截断。

### 8.3 多资源简单策略定义

每个策略都必须返回一个完整、合法的启动集合，而不是只返回排序第一的 flow：

- FIFO；
- 固定顺序；
- residual LT；
- SPT；
- LPT；
- hotspot 避让；
- 资源互补贪心；
- 固定 seed 随机顺序。

对 work-conserving，返回集合必须是极大集合；对 optional-idle，可以保留合法非极大集合和 WAIT，但两种模式分开记录。

### 8.4 指标补齐

case × mode 至少汇总：

- 决策数；
- ready 数分布；
- active communication 数分布；
- WAIT 合法和实际选择次数；
- 非极大动作合法次数；
- startable 数；
- 极大集合数或未枚举状态；
- active reservation 下集合分歧；
- 策略分歧次数；
- immediate successor 分歧；
- quality evidence 来源；
- phase、micro-batch、barrier、optimizer、job 标签；
- 完成、决策截断、时间截断和集合截断状态。

动作冲突、策略冲突、状态冲突和质量冲突分别报告，不能由一个总分代替。

### 8.5 旧 Exact 标签接入

允许按 benchmark content hash、mode、decision index 和 state hash 连接已有 243 个标签，但必须：

- 校验 hash 全部一致；
- 保留标签来源路径和 schema version；
- 不把旧标签数量写成新一轮重新计算；
- `quality_evidence` 明确标为 `existing_exact_label`；
- 没有标签的状态继续为 `not_run`，不能根据 immediate successor 不同推断质量不同。

### 8.6 E4 测试

- 时间预算能够终止故意阻塞的审计；
- 中止结果保留最后阶段；
- 多资源高 ready 数测试不会调用完整集合枚举；
- 每个简单策略动作都由模拟器判定合法；
- optional-idle/work-conserving 分开；
- active reservation 下不会使用已占资源；
- 固定 seed 随机结果稳定；
- quality conflict 不会从动作或状态冲突自动推导。

### 8.7 E4 退出条件

- 小图完整轨迹和中图有界轨迹均能稳定结束；
- wall-clock 和决策双门槛真实生效；
- 多资源轻量审计不依赖完整幂集；
- 单 channel 与多资源均覆盖规定简单策略；
- 输出能够按四层冲突独立统计。

## 9. 工作包 E5：构建有效冲突 benchmark

### 9.1 先在 staging 生成，不直接发布

从 E3 已通过静态对拍的 source 中选择 12--24 个中等规模候选，优先覆盖：

- GA 4/8；
- PP 2/4；
- TP 与 PP 同时大于 1；
- Mixtral EP 2/4/8；
- dense 与 MoE；
- 单 channel 与固定 routed 投影。

候选先写入 staging。超出当前 90 秒基础 LT 能力的图只保留转换和轻量 census，不进入质量实验，也不恢复大图集合。

### 9.2 第一层：自然真实

不修改 source 的 header、任务、依赖、duration 或 placement。对每个候选运行：

- bare LT；
- validated LT；
- 有界多策略 census；
- 负对照统计。

自然图即使没有冲突或 value spread 为零也保留结果。不得只发布高分图。

### 9.3 第二层：真实组合 multi-job

只使用已通过单 job 转换和 trace 验证的真实 DAG，构造：

- 2-job、4-job；
- 同构、异构；
- 同时到达；
- 按单 job LT makespan 的 10%、25%、50% 错峰；
- 长通信开始前、开始后和关键 barrier 前的事件对齐到达。

每组 arrival 在运行候选算法前冻结。不得根据算法收益回调 arrival。结果分别报告 makespan、各 job completion/JCT、WAIT、starvation，不把 JCT 改善等同于 makespan 改善。

### 9.4 第三层：固定 route 与 placement 压力

保持 job 内 DAG 不变，只改变明确记录的 topology/placement：

- 低共享负对照；
- 单热点；
- 两组部分冲突、部分互补 route；
- 长多资源 flow 与多个关键短 flow 竞争；
- active reservation 下仍有多个合法新启动集合。

保存 topology hash、route hash、rank-device 映射和热点资源。全部归入 `real_composed_stress`。

### 9.5 第四层：带宽与 DP 受控投影

带宽只选少量冻结档位，用于寻找 compute/communication 平衡区间。若降低带宽只形成唯一长队列而不增加策略或质量分歧，停止继续降低。

DP=2/4 只有在 SimAI builder 能重新构建 rank group 和 collective，并通过 E3 静态对拍时才生成。否则保留 `not_supported`，不手写依赖边。

### 9.6 residual decision window

不再把“锚点加 0--2 层后继”作为困难切片主方法。新切片流程：

1. 在完整或有界真实轨迹中定位策略分歧状态；
2. 用统一 completion 或 Exact 检查首动作是否有非零 value spread；
3. 保存原状态的 active compute、active communication、ready、occupied resources 和下一事件；
4. 保留到下一个公共 barrier、optimizer 或可解释 sink；
5. 显式建立窗口边界释放，不伪造已完成依赖；
6. 切片前后核对合法动作集合；
7. 核对 LT 排名；
8. 核对下一真实事件；
9. 核对首动作 value 排序；
10. 任一关键关系不一致则拒绝发布。

目标为 100--1000 task。小于 300 优先完整 Exact；其余使用有界首动作 Exact 或冻结统一 completion 标签。

### 9.7 困难准入

第一轮困难集建议同时满足：

- validated LT 在统一预算内完成；
- 至少 20 个有选择状态，或选择密度达到开发集冻结阈值；
- 至少 5 个简单策略分歧状态；
- 至少 1 个 Exact 或冻结 completion 证明的非零 value spread；
- 多资源图至少 1 个 active reservation 下集合分歧状态；
- WAIT 研究图至少 1 个 WAIT 与立即启动 value 不同的状态。

阈值只在 development 上确定。相同 source、相邻 GA/PP/EP、同一父图切片和同一 multi-job 父组合不得跨 development/validation/holdout。

### 9.8 E5 退出条件

满足以下两种结果之一即可结束，不强求正面收益：

#### 正面结果

- 形成来源可追溯、基础 LT 可运行、value spread 非零的小图和中图；
- 自然真实、真实组合和受控投影分别归档；
- 至少一个方向具有开发、验证、holdout 三组输入。

#### 否定结果

- 分层自然输入和规定受控变量均已完成；
- 没有发现稳定 LT regret 或算法改善空间；
- 能说明哪些变量只增加规模、哪些只增加动作冲突、哪些没有增加质量冲突；
- 明确记录“当前固定资源模型和来源范围内基础 LT 已足够”，停止继续调参制造收益。

## 10. 工作包 E6：4b--4f 重新准入

只有 E2、E3、E4 完成，并且 E5 得到质量冲突证据后，才重新运行复杂算法。

### 10.1 Stage 4b

可以优先进入。研究重点是解释：

- 为什么旧小图有动作代价差异但 LT regret 为零；
- 哪些 barrier、micro-batch、pipeline 或 optimizer 结构使 LT 恰好正确；
- 哪些结构变量只增加冲突数量而不增加调度难度。

### 10.2 Stage 4c

只有真实 routed 图出现 active reservation 下多个合法集合，并且简单 packing 策略产生质量分歧时重新开放。否则维持受限结论。

### 10.3 Stage 4d

只有真实或明确受控 holdout 中出现 LT regret 时，才重新训练或冻结 selective 触发器。rollout 内部使用 bare completion，最终入表结果使用 validated。

### 10.4 Stage 4e

barrier 继续只作为 LT 修正或触发信号。没有稳定条件收益时，不恢复 barrier-only 主策略。

### 10.5 Stage 4f

优先级最高。使用冻结 arrival 的真实组合 multi-job，分别研究 makespan、JCT 和 starvation。三种目标分开报告。

## 11. 测试与代码质量

### 11.1 必须通过的测试层级

1. runtime 决策上下文与缓存单元测试；
2. 三种调度路径动作摘要一致测试；
3. timeout 阶段记录测试；
4. 转换覆盖矩阵测试；
5. builder/export 逐字段对拍测试；
6. 多资源非枚举审计测试；
7. residual decision window 保真测试；
8. 不可抢占 Stage 1--3 定向回归；
9. 不可抢占 Stage 4a--4e 定向回归；
10. 完整 `python -m pytest -q`。

### 11.2 当前两项完整测试失败

`tests/test_semantics_layout.py` 仍写死 problem 和 index 总数为 243，而当前两者均为 281。处理前先确认新增 38 个不可抢占 Stage 4 benchmark 均属于预期发布结果，然后：

- 删除过期的固定 243 断言，或更新为可追溯的发布清单断言；
- 继续保留 problem path 集合与 index path 集合完全相等；
- 继续逐文件检查路径语义与 JSON semantics 一致；
- 不仅为了让测试变绿而把 281 直接改成另一个没有来源的固定数字。

### 11.3 Ruff 范围

- 本轮直接修改文件必须 0 项问题；
- 新增 runner、runtime、selection、contention 和测试必须 0 项问题；
- 旧 Stage 4c/4d/4e 的 18 项格式和未使用导入可作为独立小清理完成，但不与算法修改混在同一补丁；
- 不对无关可抢占代码做批量格式化。

## 12. 推荐实施顺序

| 顺序 | 工作 | 通过门槛 | 未通过处理 |
|---|---|---|---|
| S0 | 四种运行职责、来源记录、timeout 阶段 | E0 全部退出条件 | 只修 runner，不改算法 |
| S1 | 决策上下文与观测器去重 | 动作/trace/Exact 全部一致 | 回退缓存，定位具体 state |
| S2 | 8 中图三次性能验收 | 640/838 ≤10s，2038 ≤30s | 先分析具体阶段，再决定是否优化模拟器 |
| S3 | 显式转换清单和逐字段对拍 | 覆盖无缺项、无未处理 conversion bug | 暂停新 corpus 发布 |
| S4 | 有硬预算、非全枚举的冲突 census | 小图完整、中图有界均稳定结束 | 缩小观测，不提高无界预算 |
| S5 | 自然真实候选 | 保留正负样例并获得质量标签 | 进入真实组合，不修改真实依赖 |
| S6 | multi-job、route、带宽、可选 DP | 至少一组非零 value spread 或完整否定证据 | 停止无效变量扩展 |
| S7 | residual window 和 split 冻结 | 切片保持动作与 value 排序 | 拒绝该切片 |
| S8 | 4b--4f 条件重验 | 各方向独立满足退出条件 | 写受限或否定结论 |

S0--S2 完成前，不运行新的复杂算法网格。S3 排除转换 bug 前，不发布新自然 corpus。S4 修正全枚举问题前，不在 routed 中图上运行完整冲突审计。

## 13. 建议结果产物

不覆盖第一轮结果，新增：

- `docs/nonpreemptive_docs/result_docs/stage4_runtime_diagnosis_v2_20260902/`；
- `docs/nonpreemptive_docs/result_docs/stage4_conversion_fidelity_v2_20260902/`；
- `docs/nonpreemptive_docs/result_docs/stage4_contention_census_v2_20260902/`；
- `docs/nonpreemptive_docs/result_docs/stage4_real_composed_stress_20260902/`；
- `docs/nonpreemptive_docs/result_docs/stage4_hard_slices_20260902/`；
- `stage4_runtime_optimization_followup_result_20260902.md`；
- `stage4_simai_conversion_fidelity_followup_result_20260902.md`；
- `stage4_contention_benchmark_followup_result_20260902.md`。

每份结果文档必须区分：

- 已实现；
- 已运行；
- 已通过；
- 未支持；
- timeout；
- 尚未执行。

不得把“候选池覆盖”写成“实际审计覆盖”，不得把“动作或状态不同”写成“质量不同”，不得把带 `tracemalloc` 的运行时间写成基础模拟器时间。

## 14. 总退出条件

本计划结束时必须能用可重复结果回答：

1. 正常 bare、validated、instrumented 和带测量扰动的 profiled 分别花费多少；
2. 640、838、918、1078、1200 和 2038-task 图的三次中位数、最大值和波动范围；
3. 任何 30/90 秒 timeout 最后停在哪个阶段；
4. 观测器相对基础 LT 的额外成本来自哪些统计；
5. SimAI 分层清单是否真实覆盖 6 模型、GA、PP、TP、EP 和 topology；
6. builder、serializer 和导出 task/edge/route/resource 的逐项结果；
7. 哪些动态执行关系仍为 `not_supported`；
8. 旧图和新候选中四层冲突各有多少；
9. 是否形成来源可追溯、LT 可运行、value spread 非零的困难输入；
10. 4b、4c、4d、4e、4f 哪些具备重新实验条件；
11. 若没有有效复杂算法，是否已形成覆盖充分的否定结论；
12. 完整测试是否通过，若仍有失败，是否有明确且与本轮无关的证据。

在以上条件满足前，不进入 Stage 4g，不恢复大图完整质量实验，也不宣称不可抢占 Stage 4 已得到真实中图上的最终算法。
