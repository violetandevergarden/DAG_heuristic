# Stage 4 LLM 结构化搜索修正与推进方案

日期：2026-08-16  
对应审查：`stage4_llm_search_review_20260816.md`  
性质：详细实施建议；本轮不执行代码修改

## 1. 推进原则

1. 先修 Stage 4a 的语义与证据链，再允许 Stage 4b 使用这些 benchmark 得出结论。
2. Stage 4 复用 Stage 3 公共 fixed-multi-resource simulator、trace validator 和 exact 状态转移，不另写 LLM 专用时间推进器。
3. `experiments/` 仅保留参数装配、调用、落盘和汇总；可复用转换、分析、算法和 fixture 分别回到 `benchmark_generate/`、`src/`、`tests/`。
4. 不整体重写。按契约、测试、最小迁移、重新生成结果的顺序做有边界修正。
5. 旧不可抢占和历史结果继续保留，但显式标记语义/版本，不能作为当前 ground truth。

## 2. 建议里程碑

| 优先级 | 里程碑 | 完成标志 |
|---|---|---|
| P0 | 修正导出语义与 integration 覆盖 | 任一 Stage 4 输出都显式为目标可抢占语义，并由公共 simulator/trace 测试 |
| P1 | 建立五层 benchmark 与 conversion manifest | 五层均有可枚举清单；每个样本有来源、hash、转换和等价性记录 |
| P2 | 整理结构分析边界 | 分析逻辑离开 `experiments/`；描述性重复与可证明等价分开 |
| P3 | 建立正式结构目录 | repeat、semantic、multi-job 均有条目、证据、反例和方向判决 |
| P4 | 受控验证 exact/压缩 | paired exact 只改变 key；固定多资源小图交叉验证 |
| P5 | 推进算法方向 | 只开放有证据的方向；补齐冲突图 packing 债务 |
| P6 | 重跑与结果治理 | 所有结果带 manifest、状态、预算、版本；旧结果完成迁移标注 |

## 3. P0：先消除语义阻断

### 3.1 给 Stage 4 导出器设置显式目标 semantics

对 `benchmark_generate/simai/export.py::to_benchmark()` 做最小修改：

- 明确构造 v2 可抢占 semantics，而不是依赖 `Benchmark` 默认值；
- communication 使用 resume/remaining-work 语义；
- decision event 为 task event；
- optional idle/主动 WAIT 为 false；
- 单资源或固定多资源均使用 exclusive、atomic fixed resource set；
- metadata 记录 semantic contract 版本。

不要同时删除旧 non-preemptive 转换需求。如仍需兼容，建立显式 `semantics` 参数或不同命名入口，并要求调用者选择；禁止“函数名相同、靠默认值决定历史/当前语义”。

### 3.2 增加最小端到端回归样例

至少加入以下转换后执行测试：

1. 一条通信被新 ready 的关键通信抢占，恢复后剩余工作守恒。
2. 两条资源不冲突通信必须并行进入 maximal-compatible action。
3. 需要两个资源的通信只能原子取得二者，不能部分启动。
4. 无 eligible communication 时 forced idle；有 eligible 时 scheduler 不能 WAIT。
5. 同一时刻 compute/communication 完成事件原子处理后再决策。

测试必须调用公共模拟器和独立 trace validator，不能只断言 JSON 能被 schema 接受。

### 3.3 让 integration 测试“明确运行或明确跳过”

- CI/审查命令安装 `.[dev,integration]` 或等价依赖。
- 缺依赖时输出显式 skip/error 统计，不再静默 `collect_ignore_glob` 后显示为普通全绿。
- 增加一个测试断言本次收集到预期的 integration test 数量，防止目录整体消失。

P0 完成前，不生成新的 `reference_results`，也不做 LLM heuristic 排名。

## 4. P1：建立 Stage 4a 五层 benchmark

### 4.1 不急于扩展公共 `category`，先增加受 schema 约束的层标签

为减少对旧 benchmark 的破坏，可以保留 `random/adversarial/real` 公共 category，同时在 metadata 或独立 Stage 4 manifest 中新增受枚举约束的 `stage4_layer`：

```text
synthetic_motif
structured_projection
real_derived
adversarial
compatibility
```

约束：

- synthetic bootstrap 永远不能标 `real`；
- `real_derived` 必须存在真实输入 hash 与转换 lineage；
- `structured_projection` 必须说明保留/删除了什么，及属于等价、上/下界、松弛还是 motif；
- `compatibility` 指向 Stage 3 样本与预期结果版本，不复制并悄悄改语义。

### 4.2 定义 conversion manifest

建议每个输出 JSON 内嵌最小 provenance，并由集合级 manifest 汇总。字段至少包括：

```text
source.kind / source.name / source.content_hash
source.tool_version_or_commit
topology.name / topology.content_hash
converter.version_or_commit
converter.parameters / parameter_hash
semantic_contract_version
transform_log[]
projection_relation
benchmark_content_hash
parent_benchmark_hash (如适用)
```

`transform_log` 要能列出：删除节点、删除边、合并/收缩、通信拆分、路由冻结、compute serializer 边、单位转换和默认参数。路径仅作人类提示，认证使用内容 hash。

### 4.3 分开记录依赖来源

边至少在转换 manifest 中区分：

- workload 数据依赖；
- 固定计算顺序/资源序列化依赖；
- collective/同步 barrier；
- 转换器补边。

公共 DAG 即使暂时只有统一 edge，也必须能从 manifest 追溯来源。对 Zero Bubble 样本同时验证显式 B/W 数据依赖和 serializer 边，避免“修了数据边但有效次序仍由隐式补边决定”。

### 4.4 每层先做最小冻结集

不要一次生成大量随机文件。建议首批：

- synthetic motif：每种 PP/TP/DP/EP 与 barrier motif 各 1–2 个手算样例；
- structured projection：3–5 个由同一 workload 产生、转换规则不同但关系清楚的样例；
- real-derived：至少 2 个不同并行结构、可合法共享的冻结快照；
- adversarial：重复局部策略反例、错误 symmetry merge 反例、资源 packing 反例各至少 1 个；
- compatibility：从 Stage 3 选择单资源退化、资源不冲突并行、部分冲突和多资源原子获取样例。

每个小图都附手工 trace 或 exact reference；真实大图不强求 exact，但必须有可行 trace 和完整转换记录。

### 4.5 修正正式算法输入中的 LLM 标签

先定义稳定的只读特征结构，例如：

```text
phase, microbatch_id, pipeline_stage,
parallelism_dimension, collective_type,
layer_or_block_id, repetition_group
```

公共 loader/内部 DAG 必须保留这些字段，registry 算法只能从正式输入读取，不能读 `metadata` 中的答案提示。缺失标签允许为 `None`，以保持 Stage 1–3 compatibility。

## 5. P2：整理结构分析实现边界

### 5.1 从 `experiments/` 迁出研究逻辑

建议最小拆分，而非重写：

- `benchmark_generate/simai/`：原始 workload 解析、projection、route freezing、manifest；
- `src/llm_structured/analysis/`：signature、periodicity、conflict、boundary/interface 分析；
- `src/llm_structured/`：真正调度算法和经证明的状态压缩；
- `tests/fixtures` 或 benchmark generator：研究 fixture；
- `experiments/`：CLI 参数、调用上述 API、结果序列化。

已有函数可以直接搬迁并保留兼容 import 一段时间，不需要整体改写。

### 5.2 建立四级证据术语

禁止继续把“重复”当作单一概念。统一分为：

1. **描述性 motif 相似**：局部标签/邻域相似，只能用于统计或 heuristic feature。
2. **接口等价**：重复块的输入输出依赖、资源接口和边界状态一致，可用于分块分析。
3. **图 automorphism**：存在保持任务属性、依赖和资源映射的置换。
4. **未来等价状态**：置换后的 simulator state 拥有相同合法动作和未来代价，才允许 exact memo 合并。

每个分析 API 返回证据级别和未验证条件，不能只返回一个 `period` 数字。

## 6. P3：建立 Stage 4b 正式结构目录

### 6.1 条目模板

建议把目录同时维护为人类可读 Markdown 和机器可读 YAML/JSON。每个条目至少包括：

```text
id / name / status
formal_definition
model_scope
required_labels
positive_evidence
counterexample
proof_or_test_obligations
benchmark_links_and_hashes
algorithm_direction
decision: open | restricted | reject | pending
```

### 6.2 首批四个条目

#### R1：重复 motif 不推出局部策略有效

- 范围：单 channel、独立重复副本反例。
- 证据：copy-local `3n-1`，optimum `2n`，ratio 趋近 `1.5`。
- 判断：否决“仅凭重复率采用逐副本局部调度”；不否决带 boundary/coupling 信息的方法。

#### R2：严格独立同构分量的置换压缩

- 范围：先保留单 channel 特例；固定多资源版本另立证明义务。
- 正证据：属性/依赖/外部边检查与小图 exact 一致。
- 反例：增加一条跨分量边、不同资源映射或不同 remaining work 后不得合并。
- 判断：`restricted/open`，仅允许在证书检查通过时启用。

#### S1：静态语义角色优先级不足

- 范围：当前 coupling-aware fixture 和历史小样本。
- 证据：简单 PP role 规则未稳定优于 longest-tail/rollout。
- 判断：否决固定全局 `PP > EP > DP` 规则；保留 residual-criticality + phase + resource-conflict 的条件评分研究。

#### M1：多 job 目标分离

- 范围：多 job 扩展；明确单/多资源版本。
- 证据：小图中 makespan 与 weighted JCT 最优动作不同。
- 判断：多 job 作为独立实验轨道；不得拿 weighted JCT 收益证明单 job makespan 算法。

后续至少补一个 fixed-multi-resource conflict/packing 条目，使 Stage 4 真正继承 Stage 3，而非退回单 channel。

## 7. P4：受控验证 exact 与压缩

### 7.1 paired solver 实验

为量化 symmetry 的净效果，实现或参数化同一 exact：

- transition、action enumeration、branch order、bound、incumbent 完全相同；
- baseline key 保留实例身份；
- quotient key 只去除经证明的置换身份；
- 同时报告 generated、expanded、memo-hit、pruned-by-bound、wall time 和 peak memory。

旧的 compressed-vs-generic 状态数保留为历史观察，但不再用作因果证据。

### 7.2 固定多资源推广的证明义务

若要把 R2 推广到 Stage 4 主模型，置换必须保持：

- DAG 节点属性与所有依赖；
- 每个 communication 的固定资源集合，或有明确的资源同构置换；
- 当前 remaining work、完成/运行/暂停状态；
- 正在占用资源和同一时刻事件集；
- 所有可行 maximal-compatible actions 与转移代价。

至少使用未压缩 exact 在小图穷举交叉验证，并加入故意破坏上述每项条件的负测试。

## 8. P5：算法方向的准入判断

### 8.1 selective rollout：暂缓，先定义触发证据

只有当 cheap heuristic 在某个可观测结构指标区间稳定退化，且 rollout 在同一 benchmark/hash 上修复，才开放 selective rollout。触发器必须只使用在线可见 residual state，不能读取 reference result 或答案型 metadata。

### 8.2 repetition compression：限制开放

先实现 R2 的证书化特例和 paired exact。一般周期块、pipeline stage 和跨 micro-batch 共享同步不满足独立性时保持 `pending`，不能自动压缩。

### 8.3 LLM-specific score：继续研究，但拒绝静态固定优先级

候选 score 应组合 residual critical tail、即将解锁的 compute、phase/micro-batch、资源冲突和 barrier proximity。每项做消融，并在 synthetic、adversarial、real-derived 分层报告；只在 motif mix 上全优不能算有效证据。

### 8.4 conflict-graph packing：优先偿还 Stage 3 债务

当前多资源动作需要 maximal-compatible set。先建立：

- communication 为顶点、资源交集为冲突边的 residual conflict graph；
- 权重来自统一 residual score；
- greedy seed + maximal completion 基线；
- weighted packing/local exchange 或受预算精确集合搜索；
- 明确 maximalizer 是 simulator 合法化步骤还是算法的一部分。

在此之前不要再把 K 解释为候选可见宽度。可重新定义：

- `K_seed`：参与初始 seed 排名的数量；
- `B_pack`：兼容集合搜索预算；
- `K_score`：允许计算昂贵 score 的候选数量。

然后分别做反例，不复用已失效的 25 vs 18 结论。

### 8.5 multi-job：独立轨道

完成单 job Stage 4a/4b 最小闭环后，再把多 job 模型迁到公共 fixed-resource simulator。结果表必须单列 objective、release time、weight 和 fairness 定义；不与主线 makespan 表格合并平均。

## 9. P6：runner 与结果治理

### 9.1 runner 统一预算和状态

所有 exact/rollout runner 接受：

```text
time_limit, state_limit, random_seed, algorithm_config
```

每个 case 输出：

```text
status = optimal | feasible | timeout | state_limit | failed
lower_bound / incumbent / certified_gap
runtime / states
preemption_count / forced_idle / resource_utilization
```

未完成 exact 不能写 `optimal=true`，fallback 结果要单独标注。Stage 5 的 period 16 和 generic symmetry 大例先放入有预算的 slow suite，避免默认 study 无界运行。

### 9.2 结果 manifest

每份结果必须绑定：

- git commit 和 dirty-worktree 标志；
- Python/依赖和平台；
- benchmark set manifest hash；
- 每个 benchmark content hash；
- semantic contract、converter 和 algorithm config 版本；
- 是否实际收集 integration tests。

历史 `preemptive_stage5_20260815.json`、`preemptive_stage6_20260815.json` 不删除，新增 migration note 标明“历史、不可认证或部分过时”，不要原地改数字冒充原实验。

### 9.3 分层报告

固定报告 synthetic、structured projection、real-derived、adversarial、compatibility 五层，不混算一个平均数。小图与 exact 比较，至少报告 runtime、optimal rate、平均/最大 gap、抢占次数、forced idle 和资源利用率。

## 10. 论文使用规则修正

1. Hermod 只作为特征设计动机；把计划中的“PP > EP > DP”改为“论文初步结果将 EP 与 PP 整体置于 DP 之前，具体顺序依结构/因子而定”。
2. Crux、Cassini、Coda 的多租户目标放入 multi-job 扩展背景，不用于单 job makespan 论证。
3. Puppeteer 的动态 route/rate 不纳入当前动作空间，只借鉴 workload 可预测性和离线规划接口。
4. 每个论文启发的特征都必须映射到当前 benchmark 中可验证、非答案泄漏的字段，并通过消融验证。

## 11. 推荐实施顺序与改动边界

建议按以下小批次推进，每批均可独立审查：

1. **语义补丁**：exporter 显式 preemptive semantics + 5 个最小端到端测试。
2. **测试补丁**：integration 依赖/收集可见性 + CI 命令。
3. **契约补丁**：`stage4_layer`、conversion manifest、依赖来源和 hash。
4. **最小数据补丁**：冻结五层首批样例，不批量扩充随机数据。
5. **分析边界补丁**：迁移 repetition/period/conflict 分析，保留兼容 import。
6. **理论目录补丁**：录入 R1、R2、S1、M1，链接到固定 hash 的样例和测试。
7. **exact 验证补丁**：paired key 实验和 fixed-resource 负测试。
8. **packing 补丁**：统一 K/预算定义后实现基线与反例。
9. **结果迁移补丁**：有预算重跑，生成新 manifest，标记旧结果状态。

本阶段不建议：整体重写 `src/llm_structured`、移动所有旧不可抢占代码、改名 `muti_channel`、初始化 SimAI submodule（除非确实需要生成 real-derived 快照）、或先增加更多 heuristic。

## 12. Stage 4 最小退出条件

只有同时满足下列条件，才建议宣布 Stage 4 基础闭环完成：

- 所有 Stage 4 benchmark 显式符合公共可抢占 fixed-resource semantics；
- 五层各有冻结清单，real-derived 与 synthetic 不混标；
- 每个样本可由 manifest 追溯并验证 hash；
- integration tests 确实被收集并通过；
- 正式结构目录至少含 R1、R2、S1、M1 和一个多资源 packing 条目；
- symmetry 的收益来自 paired exact，且多资源推广有负测试和小图交叉验证；
- 旧 K 反例及不可认证数字已标记过时/待复核；
- 至少一个算法方向被有证据地开放或限制开放，至少一个被明确否决；
- 新结果包含预算、状态、版本、benchmark hash 和分层指标。

达到这些条件后，再扩大 real-derived 数据和比较 selective rollout、LLM-specific score、packing 与 compression，所得结论才具有可复查性和研究解释力。

