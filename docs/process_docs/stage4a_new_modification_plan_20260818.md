# Stage 4a 继续推进与建议修正方案

日期：2026-08-18  
依据：`stage4a_new_review_20260818.md`、`docs/plan_docs/stage4a_benchmark.md`、`docs/plan_docs/stage4_LLM_search.md`。  
目标：在不重写公共模拟器、不改变已确定执行语义的前提下，把当前“真实输入和候选语料已建立”推进到“竞争准入和实验输入可审计”。

## 1. 修正原则

1. 先修正状态、清单、发布和证据定义，再扩充语料或运行昂贵算法。
2. 所有调度动作继续交给公共 simulator；probe、基线和 heuristic 不得自己推进时间、释放依赖或管理资源。
3. 将“静态资源相交”“某条基线轨迹观察到竞争”“小图可达状态证明存在选择”分成三个字段，禁止压缩成一个 competition 数字。
4. fast probe 只用于筛选和恢复，不产生“无竞争”结论；完整回放、超时和状态上限都必须保留。
5. DP rewrite、route-frozen topology、统一 channel 和多 iteration 分别报告，不能用样例数量合并成一个“真实效果”。
6. 先完成 R-P/R-S/R-C 的小规模代表集和 holdout，再考虑全量 72 个样例或更大图。

## 2. P0：立即修正文档和状态名称

### 2.1 统一当前事实

修正 `benchmark/llm_structure/README.md`：

- 将 44 改为当前活动 72，并注明 72 是候选/活动 corpus 的文件数，不等于 72 个已认证有竞争样例；
- 将不存在的 `benchmark_generate.stage4` 命令替换为：

```powershell
python -m benchmark_generate.llm.corpus --mode generate --output benchmark
python -m benchmark_generate.llm.corpus --mode probe --output benchmark --fast
python -m benchmark_generate.llm.corpus --mode publish --output benchmark
```

- 说明 `fast_prefix` 最多 8 个决策，`stage4e_census` 是独立的 bounded census，二者都不是全图竞争证明；
- 把两个 `simai_examples` 明确标为 control/example，不计入正式真实 multi-job 覆盖；
- 加入当前 corpus 的生成时间、manifest 哈希、SimAI checkout commit 和 dirty 状态字段。

修正 `AGENTS.md`、`benchmark_generate/README.md` 和相关历史结果的引用，使阶段编号以实际文档为准。旧结果不覆盖，只在新文档中注明 superseded 边界。

### 2.2 重新定义 manifest 状态

建议保留已有错误状态，同时把成功状态改为可区分的值：

```text
generated                 已生成并通过格式验证，尚未 probe
sampled_prefix            fast probe 已完成，但只覆盖前缀
certified_small           小图有界可达检查完成
completed                 完整竞争回放和 trace 验证完成
timeout                   达到时间上限
state_limit               达到状态或决策上限
failed                    运行异常
no-contention-observed    完整 probe 未发现竞争
excluded                  明确排除并有原因
```

`probed` 不再作为包含不同证据等级的总称。每行增加 `probe_scope`、`probe_config_hash`、`termination_reason`、`complete_trace` 和 `canonical_eligible`。只有 `completed` 或经过明确规则筛选的 `certified_small` 才能进入正式有竞争算法集；`sampled_prefix` 只能进入候选集。

## 3. P1：修正 probe 合同和可恢复执行

### 3.1 分离三个竞争指标

每个 benchmark 的报告至少包含：

```text
static_resource_overlap       # 任务资源集合图上的相交关系
baseline_replay_competition   # 一条或多条指定基线轨迹观察到的选择窗口
certified_reachable_choice    # 小图可达状态搜索证明存在合法选择
```

同时记录 `eligible_count`、`legal_action_count`、`maximal_set_size`、资源冲突对、首次竞争时间、竞争持续时间、暂停/恢复次数、ready-set 增量和 forced-idle 时间。没有观察到某个指标时写 `null` 或 `none_observed_under_<scope>`，不能写 0 后让人误以为已经证明不存在。

### 3.2 增加时间、状态和枚举预算

修改 `benchmark_generate/llm/corpus.py` 的 probe 接口，增加每 case 的：

- `--time-limit-s`；
- `--max-decisions`；
- `--max-states`；
- 多资源 maximal-set `--enumeration-limit`；
- fast 模式的 `--horizon`。

在多资源图上，超过枚举上限时只用确定性的 greedy constructor 产生一个合法最大集合，并把 `legal_action_count` 标为未知、`enumeration_truncated=true`。不能调用完整 `legal_actions()` 后再声称 fast。每次 case 结束立即写 checkpoint，checkpoint 至少包含 benchmark hash、配置 hash、已处理决策数、trace 前缀 hash、状态和终止原因。

### 3.3 基线必须统一

对能够完整完成的样例，至少回放以下三种规则：

1. FIFO 或按稳定任务编号的固定顺序；
2. 基础 Longest Tail；
3. 一个不含研究特征的固定顺序基线。

单 channel 记录首次动作是否不同、makespan、抢占次数、forced-idle 和资源利用率。多资源记录合法兼容集合、并行通信数、集合变化和 makespan。任何基线未完成都保留 `timeout` 或 `partial`，不可当作失败或最优。

## 4. P1：修正发布事务和 provenance

### 4.1 发布前逐文件验证

在 `publish(staging=...)` 移动目录前：

1. 读取 candidate manifest；
2. 对每个有 path 的 JSON 执行 `load_benchmark` 和 `validate_benchmark`；
3. 重新计算 benchmark content hash，与 candidate manifest 比较；
4. 检查 benchmark_id 唯一、path 唯一、所有资源引用存在、manifest 与 index 预期一致；
5. 对失败或缺失行停止发布，不替换 active corpus。

发布采用临时 active 目录 + 同目录元数据写入 + 最后一次原子替换。旧 active 目录只在新目录和 manifest/index 全部验证后改名备份；任何异常都保留旧 active，不要求人工恢复。

### 4.2 元数据一起发布

`source_catalog.jsonl`、`run_metadata.jsonl`、candidate manifest、probe 配置和 corpus manifest hash 必须作为同一 run 的产物写入活动目录或明确的 run 记录。发布不能只移动 `preemptive/`，否则 benchmark 文件和来源清单可能来自不同 run。

### 4.3 删除本机绝对路径

`benchmark_generate/simai/export.py` 中公开 benchmark 的 `metadata["topology"]` 改为 topology 文件名或稳定的相对来源标识；公开 provenance 保留名称、内容 hash、topology tier、route/resource hash。绝对路径仅写入不提交的运行日志。增加测试：读取提交后的 JSON 时不允许出现当前工作区盘符路径。

## 5. P2：冻结一套可完成的 canonical v1

不要马上对 72 个大图做完整回放。先建立小而完整的矩阵：

| 组别 | 建议数量 | 必需覆盖 |
| --- | ---: | --- |
| R-P | 每个生产拓扑至少 2 个模型/shape | DP=1 控制、至少一个可比较 DP |
| R-S | 每个实验拓扑至少 2 个代表 | 资源冲突密集和资源相对分散 |
| R-C | 少量统一 channel 与 DP rewrite | 只改变一个因素的 DP 配对 |
| multi-iteration | 2--3 个 | native 对拍前标为 projection |
| control | 2 个 | single-job 与 example multi-job |
| large | 约 10 个 | 仅作耗时、内存和扩展性报告 |

canonical v1 每个正式样例都必须有：来源和拓扑 hash、转换器 commit、duration model、语义版本、probe 配置 hash、状态、竞争报告、基线结果或明确未完成原因。重复 iteration 和同一源的多 topology 映射必须记录 unique source，不得按文件数代替来源覆盖。

## 6. P2：完成 DP 竞争曲线

从同一个 AICB source 选择 DP=1、DP=2、DP=4（容量允许时）配对；如果使用 header rewrite，suite 固定为 R-C，并在标题和结果中写 projection。每个配对运行相同 topology、相同 pipeline mode 和相同基线，报告：

- task/communication 数变化；
- static resource overlap；
- 首次和累计 baseline competition 窗口；
- 非等价动作数；
- pause/resume 和 ready-set unlock 次数；
- 三种基线的 makespan、runtime、forced-idle、资源利用率。

如果增加 DP 只增加任务数量而没有增加可选动作，必须记录为“无效扩展”，不要把它纳入有竞争主表。

## 7. P2：建立真实 multi-job 输入

新增离线生成器，使用至少两个真实 AICB source，给每个 job 独立命名空间和 arrival；job 之间只共享固定资源，不添加跨 job DAG 边。最低覆盖：

- 两个相同 workload 的 homogeneous 组合；
- 两个不同模型或 shape 的 heterogeneous 组合；
- 同时到达和错峰到达；
- 资源相同与资源部分不冲突两种 topology 映射；
- 显式 primary objective（makespan、平均 JCT 或 weighted completion time 只能选一个作为主目标）。

多 job 结果单独存放，不能把 JCT/fairness 混进单 job makespan 表。完成前，`simai_examples` 只能作为 smoke test。

## 8. P2：校验多 iteration 和 duration 模型

多 iteration 先调用 SimAI 原生展开路径，或对当前 `repeat_iterations()` 与 native 输出逐项比较：任务数、边数、iteration boundary、optimizer/barrier、rank、首尾 overlap。验证前所有样例保留 `structured_projection` 标记。

duration 结果增加 `duration_model_version`、单位、带宽参数、是否逐链路、是否含 NIC 资源和参数 hash。若未来改成逐链路容量或协议模型，创建新的 semantic contract 和 reference 版本，不覆盖当前名义带宽结果。

## 9. P3：真实小图切片和 reference

从真实 AICB DAG 生成有记录的 real-derived exact slice：保留一个或两个 micro-batch、一个 barrier/join 邻域和一个资源热点，记录删边、收缩和投影关系。对切片运行 Exact，保存 benchmark hash、切片关系、optimal makespan、最优首动作和运行预算。切片不得与完整大图混称严格等价，只用于校准 heuristic 和验证首动作。

大图没有 Exact 时统一报告 `unknown` 或 `not_run_size_limit`，不能把 Longest Tail 的可行 makespan写成最优。所有 timeout、state limit、fallback 和 partial 都进入结果表。

## 10. 推荐实现顺序

### 批次 A：文档和状态

- 更新 README 和命令；
- 增加 manifest 状态和证据字段；
- 标出当前 72 个样例的 `sampled_prefix`；
- 写 supersession note，不覆盖历史文档。

验收：读者只看 README 和 manifest 就能知道哪些是候选、哪些完成、哪些超时。

### 批次 B：probe 和发布安全

- 加 per-case 时间/决策/状态/枚举预算；
- 避免 fast probe 枚举所有 maximal sets；
- 完成发布前验证和失败保留旧 active；
- 移除公开 JSON 的绝对路径。

验收：人为破坏一个 candidate JSON、manifest hash 或 probe 中途终止时，active corpus 不变，checkpoint 可恢复且状态准确。

### 批次 C：canonical v1 和基线

- 选取可在预算内完整完成的 R-P/R-S/R-C 小图；
- 运行 FIFO、Longest Tail 和固定顺序；
- 生成竞争报告、运行时间和资源利用率表；
- 单独保留 partial/timeout/无竞争样例。

验收：每个 canonical case 都有完整 trace 或明确终止原因，基线输入和预算完全相同。

### 批次 D：DP、multi-job、multi-iteration

- 完成 DP 配对曲线；
- 生成真实 AICB multi-job；
- 对拍 native multi-iteration；
- 生成约 10 个 large case 的耗时和内存报告。

验收：Stage 4a 五个退出条件全部有机器可读证据；没有把 projection、control 或 timeout 混入正式算法效果表。

### 批次 E：real-derived exact slice 与后续算法入口

- 生成少量真实来源 Exact slice；
- 以非等价选择状态为 choice gate；
- 只在有竞争且基线有差异的样例上运行 selective rollout/packing；
- 形成 holdout，不把训练和筛选样例混用。

验收：后续 Stage 4b--4h 的每个结构或算法结论都能回到冻结 manifest、公共 simulator、统一基线和独立 trace。

## 11. 建议的数据合同

### 11.1 corpus manifest 最小字段

每个生成 attempt 不论成功与否都保留一行：

```text
case_id, benchmark_id, suite, stage4_layer, status
path, benchmark_content_hash, schema_version, semantic_contract_version
source_name, source_content_hash, workload_origin
source_world_size, source_dp, requested_dp, effective_dp, effective_world_size
tp, pp, ep, gbs, mbs, training_iterations
topology_name, topology_origin, topology_content_hash, route_resource_hash
converter_commit, converter_dirty, source_bundle_hash
generation_parameter_hash, duration_model, duration_model_version
probe_schema_version, probe_config_hash, probe_status, termination_reason
canonical_eligible, exclusion_reason
```

`case_id` 表示一次来源和参数组合，`benchmark_id` 表示成功产出的 benchmark；失败行允许后者为空。不要把错误 spec 丢进另一种临时结构。`canonical_eligible` 只由公开准入规则计算，算法不得读取该字段。

### 11.2 probe report 最小字段

```text
benchmark_id, benchmark_hash, config_hash
status, termination_reason, runtime_ms, peak_memory_mb
decision_count, complete_trace, trace_hash
forced_idle_time, preemption_count, utilization
static_overlap_summary
baseline_rule, baseline_makespan
choice_state_count, non_equivalent_choice_count
first_choice_time, contended_duration
enumeration_exact, enumeration_limit, enumeration_truncated
certified_status, certified_states
```

choice state 的明细放在独立可压缩文件中，manifest 只保留汇总和内容 hash。避免把几万个状态直接塞进一行 JSONL，导致每次 publish 都重写大文件。

### 11.3 baseline report 最小字段

每个 `case × algorithm × config` 一行，至少记录：

```text
benchmark_hash, algorithm_name, algorithm_config_hash
status, makespan, runtime_ms, preemptions
forced_idle_time, resource_utilization, trace_hash
fallback_count, timeout_s, error
git_commit, dirty, source_bundle_hash
```

同一表中只比较完全相同 benchmark hash 和语义版本。缺失值使用 null 并配合 status，不能用 0 表示没运行。

## 12. 建议的测试计划

### 12.1 单元测试

为 corpus workflow 新增：

- manifest status 合法值和状态转移；
- probe config canonical hash；
- candidate hash 不符时 publish 拒绝；
- benchmark_id/path 重复时 publish 拒绝；
- source catalog/run metadata 缺失时 publish 拒绝或明确降级；
- 公开 metadata 的 topology 标识不含绝对路径；
- fast probe 超过 enumeration limit 时设置 truncated 且仍产生合法 action；
- timeout 后写 checkpoint，下一 case 继续；
- benchmark hash 相同但 config hash 不同时不复用旧 probe。

### 12.2 小型端到端测试

构造四个不依赖大型 SimAI 文件的极小输入：

1. 无竞争：任意时刻只有一个 communication eligible；
2. 有 eligible 但资源互不冲突：只有一个 maximal action；
3. 两个通信争用同一资源：存在两个合法 maximal action；
4. 抢占后释放不同 compute/join：FIFO 与 Longest Tail 首动作不同。

对每个输入检查 fast probe、完整 probe、certified probe 和三个 baseline 的字段区别。尤其要验证“无观察”不会升级为“证明没有”。

### 12.3 SimAI integration

- AICB 解析 task 数、原始 edge 数和 serializer-added edge 数快照；
- 所有 pipeline mode 的 rank compute order；
- DP rewrite 前后 rank、collective endpoint 和资源数关系；
- production/experimental topology 的 route 非空和资源 hash 稳定；
- multi-iteration native 对拍；
- multi-job namespace、arrival 和无跨 job DAG edge；
- 导出后在公共 simulator 上运行并由独立 trace validator 回放。

### 12.4 发布故障注入

在临时目录模拟：候选 JSON 截断、manifest 少行、hash 错误、index 写失败、active 已存在和 publish 中断。每次都断言原 active 文件、manifest 和 index 不变。这个测试比只检查成功 publish 更重要，因为 Stage 4 真实生成耗时很长。

### 12.5 性能回归

选择 tiny/small/medium/large 各一个固定 benchmark，记录 fast probe 的决策吞吐和内存。性能阈值只用于发现数量级退化，不应过窄；关键断言是 fast 模式不会调用无限 maximal-set enumeration，单 case 时间上限能够生效。

## 13. 结果目录和迁移规则

建议使用：

```text
benchmark/llm_structure/manifest.jsonl
benchmark/llm_structure/source_catalog.jsonl
benchmark/llm_structure/run_metadata.jsonl
docs/result_docs/stage4a_canonical_v1_*/summary.json
docs/result_docs/stage4a_canonical_v1_*/per_case/*.json
docs/result_docs/stage4a_dp_curve_*.json
docs/result_docs/stage4a_multi_job_*.json
docs/result_docs/stage4a_scaling_*.json
```

实验 checkpoint 不放入 `benchmark/**/*.json`。如果保存在 `docs/result_docs`，结果文件中记录 manifest hash；如果放临时目录，最终 summary 必须把失败、超时和排除行一起归档。

迁移当前 72 行时不重新运行算法也可以先完成状态修正：把现有 `probed + sampled_prefix` 映射为 `sampled_prefix`，保留原 probe 字段和 hash；把 Stage 4e full census 作为独立 `bounded_census_v1` 结果引用，不写回 canonical complete 字段。后续完整 probe 产生新 report schema，不覆盖旧 JSON。

旧 44-case 文档保留，并增加说明：其输入覆盖、命令和 probe 结论已被 72-case corpus 替代；旧 hash 不能用于当前结果。已有 72-case barrier/packing/selective/multi-job 探索也要标清使用的是哪一版 manifest 和 bounded 状态。

## 14. 算法阶段的准入门槛

Stage 4a 完成前允许继续的工作：公共 simulator 回归、probe 成本优化、real-derived exact slice、失败模式测试、现有结果的证据分级。

需要等待 canonical v1 的工作：真实结构频率结论、生产/实验 topology 迁移性、真实 DP 趋势、默认 selective rollout 触发率、真实 packing 收益和正式 multi-job policy。

算法实验只消费 benchmark 的任务、依赖、duration 和资源，不读取 suite、source model、topology tier、canonical_eligible 或 probe 答案。实验 runner 可以用 manifest 选择文件，但传给算法前必须只加载公开问题字段。若算法确实需要 phase、collective 或 job label，必须把它们列为正式可见特征并建立消融，不能偷偷读取 provenance。

## 15. 预期完成报告的结构

Stage 4a 最终结果文档至少分为：

1. 输入资产和转换契约；
2. corpus 分层与 unique source 覆盖；
3. 无竞争、观察到竞争、认证有选择、超时和失败清单；
4. DP 曲线；
5. multi-job 构造与竞争曲线；
6. multi-iteration 对拍；
7. FIFO/Longest Tail/固定顺序基线；
8. tiny/small/medium/large 的时间和内存；
9. Exact slice 与未知最优边界；
10. 可进入 Stage 4b--4h 的 canonical manifest hash。

每张表都报告样例数、unique source 数、完成数和超时数。平均值旁同时给最大值或分位数，避免少数大图被平均掩盖。生产 topology、实验 topology、统一 channel 和 DP rewrite 分开，不做一个总平均。

## 16. Stage 4a 重新验收标准

重新验收必须同时满足：

1. 活动 corpus 与 manifest/index/source catalog/run metadata 属于同一发布 run，所有 hash 一致；
2. 每个 canonical case 的 probe 状态明确是完整、bounded、timeout、failed 或 excluded；
3. 至少一套 R-P/R-S/R-C 配对完成统一 FIFO、Longest Tail 和固定顺序基线；
4. competition 报告同时区分静态相交、轨迹观察和小图认证；
5. DP 配对有竞争强度与成本曲线；
6. 至少两个真实 AICB job 的 multi-job case 有独立命名空间、arrival 和 objective；
7. 多 iteration 有 native 对拍结果，未通过者继续标为 projection；
8. 普通规模与约 10 个大图有生成、转换、probe、基线 runtime 和内存记录；
9. 真实小图切片或示例有明确 Exact 状态，未完成者不能标最优；
10. README、AGENTS、manifest 和结果文档不再使用旧 44-case 或不存在的入口。

达到这些条件后，Stage 4a 才能从“候选真实语料基础设施”提升为“可供 Stage 4b--4h 正式实验使用的冻结输入”。在此之前，算法收益只可作为探索性结果报告。

## 17. 不建议现在做的事情

- 不要继续无上限增加同一 Mixtral shape 的近重复 JSON；
- 不要因为 probe 前缀出现多个 eligible 就宣称整图有稳定竞争；
- 不要把 R-C 的 DP rewrite 当作生产 DP 结论；
- 不要把 single-job repeated iteration 当作 multi-job；
- 不要在真实大图上默认枚举所有合法 maximal set；
- 不要在没有统一 baseline、time budget 和 trace 的情况下推进新的全局 priority；
- 不要删除旧过程文档或重写历史结果，只新增当前审查和 supersession 说明。
