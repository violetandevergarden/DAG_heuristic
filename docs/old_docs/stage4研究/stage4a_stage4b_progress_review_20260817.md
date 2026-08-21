# Stage 4a 实现与 Stage 4b 结构理论进展审查

日期：2026-08-17  
性质：只读审查；本轮未修改代码、benchmark、结果或计划文档  
范围：当前工作区中尚未提交的 Stage 4a/4b 实现、`benchmark/llm_structure/`、测试、生成日志、`stage4b_structure_theory.md` 及 2026-08-16 的 Stage 4 结果文档。

## 1. 总体结论

这轮推进有实质进展，不是空壳：可抢占导出语义、LLM 标签保留、真实 AICB 生成入口、生产/实验 topology 分级、配对 symmetry exact、结构目录和 integration 可见性都已出现。但当前状态仍是**实现中间态**，不能认定 Stage 4a 或 Stage 4b 完成。

- **Stage 4a**：44 个 schema-v2 可抢占 benchmark 已经写出且能通过现有文件/语义检查，但生成流程在竞争回放阶段未完成，`manifest.jsonl` 不存在，index 未纳入这些文件，测试已因此失败。语料仅使用 Mixtral 8x7B，生产 topology 路由样例只有 7 个，真实多 job 尚未生成，覆盖远未达到新 real-first 计划。
- **Stage 4b**：R1/R2/S1/M1/P1 五个目录条目和候选方向判决已经形成，达到了旧计划“有目录”的最低形式要求。R1、单 channel R2 和 M1 的小图结论基本可信；但大部分证据仍来自 synthetic/code fixture，没有在新真实语料上完成结构扫描和验证。R2 多资源化、P1 真正的 packing、selective rollout 和真实 semantic/barrier 规律仍未完成。
- **结果治理**：当前 Stage 4 结果记录使用 HEAD commit `101c7b7`，但所有关键实现都还在 dirty worktree 中，结果 JSON 没有 dirty 标志或源码内容 hash；若仅凭 commit 无法重建当时代码。部分结果文档还保留了已经过时的“五层 benchmark 通过”“14/14 可行回放”等结论。

因此建议将当前状态标记为：

```text
Stage 4a：生成链和首批语料已建立，冻结/覆盖/竞争认证未完成
Stage 4b：最小结构目录已建立，真实 workload 证据和多资源理论未完成
```

## 2. 本轮已完成且值得保留的部分

### 2.1 导出语义已从旧不可抢占模型纠正

`benchmark_generate/simai/export.py` 现在显式构造：

- `preemption=communication_resume`；
- `decision_epoch=task_event`；
- `optional_idle=False`；
- `compute_model=unbounded_parallel`；
- `resource_model=exclusive_fixed_set`；
- `preemption_cost=0`；
- `minimum_quantum=0`；
- `schema_version=2.0`。

这修复了上一轮审查中最严重的“SimAI 输出默认 non-preemptive”问题。调用者必须显式给 category，synthetic bootstrap 不再默认伪装成 real。

### 2.2 正式算法输入保留了 Stage 4 标签

`src/core/conversion.py` 与 `src/core/dag.py` 新增只读 labels，保留：

```text
phase
microbatch_id
pipeline_stage
parallelism_dimension
collective_type
layer_or_block_id
repetition_group
task_role
```

这使后续 LLM-aware 算法可以从正式 DAG 输入读取特征，不必访问答案型 metadata。该接口设计应保留。

### 2.3 Topology 分级与 route freezing 已落地

`benchmark_generate/llm_structure.py` 正确区分：

- production：AlibabaHPN、Spectrum-X、DCN+DualToR；
- experimental：Cassini 24g、Cassini 64g、Hermod 32g。

路由被冻结为 directed link 与 NIC 固定资源集合，满足当前不动态选路、原子获取资源的模型边界。每个路由 benchmark 中保存 topology 名称、tier 和内容 hash。

### 2.4 Integration 缺失不再静默伪装为全绿

`tests/integration/conftest.py` 会在缺少 `jsonschema` 或 SimAI checkout 时发出明确警告；`tests/test_integration_coverage.py` 把 integration 覆盖变成可计数的 skip。这比旧版静默 `collect_ignore_glob` 明显更可靠。

当前环境仍没有安装 `jsonschema`，所以 integration 尚未真正执行，但“没有执行”现在是可见的。

### 2.5 `experiments/` 边界得到部分修正

结构签名和扰动逻辑已经移至：

```text
src/llm_structured/signatures.py
src/llm_structured/perturb.py
```

`experiments/simai/repetition.py` 变为兼容 shim。`repetition_study.py` 仍负责研究编排和汇总，这是合理的 experiment 职责；核心可复用签名不再蜗居在 experiments 中。

### 2.6 R2 使用 paired exact，较旧比较更可信

`exact_oracle_paired()` 的 identity/quotient 两种模式共用 transition、action enumeration、递归、预算和 trace 提取，只改变 memo key。这解决了旧版“拿两个不同 exact 的状态数比较后归因于 symmetry”的主要缺陷。

当前配对结果：

| replicas | identity states | quotient states | makespan |
|---:|---:|---:|---:|
| 2 | 13 | 8 | 9 |
| 3 | 66 | 16 | 11 |
| 4 | 501 | 38 | 14 |
| 5 | 3163 | 73 | 17 |
| 6 | 18134 | 126 | 20 |
| 7 | 99207 | 203 | 23 |

所有 pair 的 makespan 一致并标记 optimal。跨分量边、时长差异和资源集合差异的负测试也已经加入。

## 3. Stage 4a 代码与语料审查

### 3.1 阻断：生成没有事务闭环，仓库当前不一致

当前目录已经有 44 个 `benchmark/llm_structure/**/*.json`，但：

- `benchmark/llm_structure/manifest.jsonl` 不存在；
- `benchmark/index.jsonl` 没有完整纳入新语料；
- `llm_generate_stdout.log` 只显示竞争回放进行到第 8 个 unified case；
- `llm_probe_log.jsonl` 只记录 3 个 routed case；
- README 却已经声称 manifest 和完整竞争报告存在。

针对性测试结果：

```text
22 passed, 1 skipped, 2 failed
```

失败项：

```text
tests/test_benchmark_format.py::test_index_matches_files_and_hashes
tests/test_semantics_layout.py::test_index_and_path_manifest_are_complete_and_auditable
```

具体为 index 185 行，而磁盘上共有 215 个 benchmark 文件。

根因是生成器先递归删除 `benchmark/llm_structure/preemptive/`，再写 44 个文件，最后串行执行非常耗时的完整回放；只有全部回放结束后才写 manifest 和重建 index。任何中断都会留下“新文件存在、manifest/index 仍旧”的半生成状态。本次已经实际触发这个失败模式。

### 3.2 真实覆盖规模仍明显不足

当前 44 个文件的组成：

| 分组 | 数量 |
|---|---:|
| unified single-channel | 28 |
| multi-iteration | 3 |
| routed production | 7 |
| routed Cassini/Hermod | 4 |
| SimAI example | 2 |

源 workload 分布：

- 42 个文件全部来自 Mixtral 8x7B；
- 2 个是 SimAI 自带 example；
- 没有 GPT 7B/13B/22B/175B、Llama 405B 等现有 AICB family；
- 没有 real AICB 多 job 组合。

DP 分布按文件名统计：

| DP | 数量 |
|---:|---:|
| 1 | 34 |
| 2 | 3 |
| 4 | 5 |
| example/未编码 | 2 |

三个生产 topology 的 routed 数量分别约为 Alibaba 2、Spectrum-X 1、DCN 4。这是可用的 smoke/首批样例，不符合新 Stage 4a 要求的“大规模 real-production 主体”。

### 3.3 当前 corpus 主体仍是统一瓶颈而非真实 topology

44 个文件中 28 个是统一 `channel:0` 投影，另有 3 个 multi-iteration 也是统一瓶颈。它们可以研究真实 workload DAG 结构，但资源模型是 relaxation，不是生产 topology fixed-route 结果。

因此当前语料应表述为：

```text
真实 AICB workload 派生 DAG 为主体，资源侧以统一瓶颈投影为多数；
生产 topology route-frozen 样本仍是少量首批验证。
```

不能表述为“真实 workload + 真实 topology 的大规模 benchmark 已建成”。

### 3.4 DP override 是受控投影，不是原始真实配置

当前 Mixtral 网格原始 `dp=1`。生成器通过修改 AICB header 的 `all_gpus`，把相同逐层输入投影到 DP 2/4。这是合理的 R-C 控制实验手段，但存在四个问题：

1. benchmark ID 中 `ws8_dp4` 的 `ws` 仍表示源文件名中的 world size，而 effective world size 已变为 32，命名有歧义；
2. provenance 只写一个 `dp`，没有明确拆分 source/requested/effective DP 和 source/effective world size；
3. `projection_relation` 仍只写 `route_frozen_projection` 或 `relaxation_unified_channel`，没有表达 parallelism/header rewrite；
4. 这些 case 与未改写的真实配置都标 category real，只有 transform log 能看出差别。

因此 DP rewrite case 应归入 real-controlled/projection，而不是无条件进入 real-production 原始配置组。

### 3.5 竞争预检不是算法无关的完整判定

`competition_report()` 只沿一条确定性基线轨迹运行：

- 单 channel 总选第一个 eligible communication；
- 多资源总选通信数最多的合法 maximal action。

它统计的是**该基线轨迹上**的竞争，不是整个 reachable state space 的竞争。另一首动作可能进入新的 ready/eligible 状态，所以当前报告不能安全证明：

- `competition_level=none` 的实例在所有合法调度下都无竞争；
- 当前 contention fraction 是实例固有量；
- 一个被判为 weak 的图没有算法区分度。

此外，新计划的 informative 条件要求“至少两个不同合法 maximal set/具有资源或解锁差异”，当前 report 没有记录合法 action 数、集合多样性、解锁差异或不同基线间稳定性。`none/low/medium/high` 仅由一条轨迹的 contended fraction 阈值决定。

报告应改名为 baseline-replay contention，或增加多策略/小图可达性审计后才承担准入职责。

### 3.6 竞争探针成本过高，无法支持“大量真实 benchmark”

路由实例的单次竞争回放日志显示约 29 秒至 597 秒。生成 44 个文件后串行完整回放会耗费很长时间，而且没有 per-case checkpoint、resume 或 time/status limit。当前设计会使扩展到数百真实 case 不可操作。

README 的单条“生成 + 竞争检测 + index”命令把快速生成和慢速审计绑在一起，也没有 fast/slow suite 区分。

### 3.7 Manifest 契约即使完成也仍不完整

当前 `write_manifest()` 计划记录 source hash、topology tier、competition 和 benchmark hash，这是进步；但还缺：

- canonical suite：R-P / R-S / R-C / control；
- source/requested/effective DP 与 world size；
- placement policy、placement seed/hash；
- route policy/resource abstraction hash；
- 主仓库 converter commit/dirty 状态；
- canonical parameter hash（已有函数但未用于 corpus）；
- invalid/no-contention/skipped 条目；
- benchmark 生成/回放 status、runtime 和失败原因。

`_try_add()` 捕获失败后只打印 skipped，不进入最终 manifest；`errors=[]` 变量也没有被填充。若生成完成，失败组合仍缺机器可读审计链。

### 3.8 多 iteration 语义尚未被真实生成器验证

`repeat_iterations()` 在导出后的 benchmark 上复制任务，并把每个 rank 的所有 sink 连接到下一 iteration 的 source。代码注释称这是“standard per-rank iteration boundary”，但没有与 `simai-flow-scheduler` 的 native multi-iteration builder 或已知 trace 对拍。

风险包括：

- 通信 task 用 src rank 归属，可能不能准确表示接收端/collective 的 iteration 边界；
- “所有 sink → 所有 source”可能增加真实 workload 中不存在的序列化；
- optimizer/barrier 的真实完成条件可能没有被显式识别；
- 当前三个 multi-iteration case 均为 DP1 + unified channel，不能验证多资源跨 iteration 竞争。

在完成对拍前，它们应标为 structured projection，而不是严格 1:1 real iteration trace。

### 3.9 多 Job 目前只有 example，不是 Stage 4h 输入

`simai_example_multi_job_1to1.json` 来自示例文件，并把各通信按 parallelism dimension 放到隔离 fabric。它没有完整表达 Stage 4h 要求的 arrival、weight、primary objective、真实共享 topology placement，也不是 AICB real-workload 多 job 组合。

它适合作为转换/多 job task-id 隔离测试，不应计入正式 multi-job benchmark 覆盖。

### 3.10 Duration 与 topology 真实性边界仍需收紧

route-frozen benchmark 的 duration 使用 topology 级单一名义 bandwidth 折算，而不是逐 link capacity、拥塞或 collective protocol 时序。固定资源冲突结构可用于当前抽象模型，但 makespan 不能解释为真实系统 runtime。

生产 topology 只能支持“在生产拓扑结构投影下的模拟调度结果”，不能写成 measured production performance。

## 4. Stage 4b 结构理论进展审查

### 4.1 对旧计划最低交付物的完成度

| Stage 4b 要求 | 当前状态 | 判定 |
|---|---|---|
| 正式结构目录 | 有 Markdown 结果 + JSON catalog | 形式完成 |
| repeat 条目 | R1、R2 | 完成特殊情形 |
| semantic 条目 | S1 静态角色优先级反例 | 部分完成 |
| multi-job 条目 | M1 目标分离 | 完成最小反例 |
| 每条有方向判断 | 有 reject/restricted/open/pending | 完成 |
| 旧阶段 5/6/7 复核 | 有保留/降级/撤回表 | 基本完成 |
| 真实 LLM 结构证据 | 尚未使用新 44 文件形成正式结果 | 未完成 |
| 跨副本 future-equivalence | 仅严格独立单 channel R2 | 部分完成 |
| 多 schedule/并行配置语义规律 | 仅少量 synthetic 1F1B/interleaved/ZB | 未达到强证据 |

结论：Stage 4b 已达到“目录骨架和最小反例建立”，还没有达到“真实 LLM 结构规律得到稳定利用结论”。

### 4.2 R1 可以保留

R1 的构造和 exact 结果支持：copy-local 为 `3n-1`、optimum 为 `2n`，比值趋近 1.5。它足以否决“仅凭重复率复制单副本局部调度”的普遍命题。

适用范围必须继续保持为：单 channel、合成构造、单 job makespan、零抢占开销。它不是“真实 LLM 上 copy-local 一定差 1.5”的证据。

### 4.3 R2 单 channel 配对证据较强，但理论记录还不完整

identity/quotient 使用同一个搜索体，是本轮最扎实的改进。当前证书检查：

- 分量不重叠且等宽；
- 每位置 kind/duration/role/labels 相同；
- 分量内依赖形状相同；
- 无跨分量边；
- 传入 resources 时每位置资源集合相同。

但仍有以下问题：

1. solver 仍是 `PreemptiveDAGModel` 单 channel；传入 resource map 只增加证书检查，不会执行多资源 transition，所以“接受相同 resource set”测试不是多资源 quotient 验证；
2. catalog 已把带 resources 的定义写成正式定义，但 model scope 又说多资源待验证，表述容易被误读；
3. 没有独立书面证明逐项覆盖运行资源占用、同刻事件和 maximal action 双射；
4. `generated_transitions=len(representatives)` 实际是代表状态数，不是生成的 transition 数；
5. `deduplicated_states=cache_info().hits` 是缓存命中次数，不等于独立“被去重状态数”。

因此 R2 可以保持 `restricted`，但当前 488.7× 应表述为 identity-vs-quotient memo-state reduction；其他统计字段需更名后重跑。

### 4.4 结构签名的 graph-automorphism 等级存在正确性漏洞

`classify_repetition_evidence()` 将 literal twin group 升级为 `graph_automorphism`，但 `_twin_groups()` 的 key 只包含：

```text
kind, duration, parents, children, resources
```

它没有包含 role、phase、microbatch、pipeline stage、collective type 等“labelled graph”属性。因此两个依赖和资源完全相同但语义标签不同的节点会被计为 labelled-graph automorphism，与模块 docstring 和 catalog 术语不一致。

保守做法是：

- 将当前结果称为 unlabeled execution-graph twin；或
- 把所有会进入正式 DAG labels/影响算法可见状态的字段加入 key；
- 若标签不影响 simulator 但影响算法，必须区分“执行 future-equivalence”和“标签保持 automorphism”。

在修正前，任何基于 `highest_certified_level=graph_automorphism` 的结构目录结论都不应发布。

### 4.5 S1 足以否决固定优先级的普遍最优性，但不足以完成 semantic 理论

6 个 synthetic pipeline probe 中静态 PP/DP 规则均略差于 longest-tail/rollout；R1 上还能达到 1.5 gap。单个严格反例已经足够否决“固定全局角色优先级总是好/最优”。

但以下表述需收窄：

- GA=4 的 teacher 是 best observed，不是 exact；
- 6 个 probe 全是 synthetic，且任务数 40–84；
- 退化幅度多数为 0.05%–0.19%，不能据此说明静态标签在真实 workload 上毫无平均价值；
- static PP 和 static DP 在这些 probe 上结果完全相同，说明 probe 可能没有真正区分两种优先级，或候选/tie-break 让差异消失。

所以 S1 的可靠结论是：**拒绝固定角色优先级作为普遍规则或理论结论**。Stage 4b 的“语义与阻塞原因”仍未完成，barrier、residual tail、DP/TP/PP/EP 和真实 topology 的条件规律仍是 open。

### 4.6 M1 可以保留，但只是目标分离定理的最小实例

M1 清楚展示 makespan 与 weighted JCT 目标不同。这一结论不依赖真实 LLM workload，可以作为多 job 研究的基础边界。

它尚未证明：

- 多 job fixed-resource simulator 已与单 job公共语义统一；
- hierarchical policy 有稳定收益；
- arrival/weight/fairness 已进入 benchmark；
- 真实 LLM 多 job 具有可利用结构。

因此 `independent_track` 判定正确，但不能写成 multi-job Stage 4h 已完成。

### 4.7 P1 只完成基线和反例，没有完成 conflict-graph packing

packing trap 可靠地说明 flow-size-first seed 可能得到 18，而更好的兼容集合得到 13；旧 25 vs 18 K 反例也已正确撤回。

当前已部署的 longest_tail/resource/bottleneck pack 在 3 个极小样例上都最优，只能证明接口和基线存在。尚未实现或验证：

- 统一 conflict graph 数据结构；
- `K_seed/B_pack/K_score/B_eval`；
- weighted packing；
- 1-exchange/2-exchange；
- 小图全 maximal-set recall；
- score × constructor 二维消融。

因此 P1 的准确状态是 `open / baseline established`，不是 packing 债务完成。

### 4.8 Selective rollout 保持 pending 是合理的

当前没有发现 longest-tail 退化而 rollout 修复的稳定窗口，保持 pending 比勉强开发 trigger 更稳妥。新 real-production/stress 语料尚未完成竞争认证，在此之前不应训练或调 trigger。

### 4.9 扰动实现有一个独立缺陷

`src/llm_structured/perturb.py::perturb_durations()` 使用：

```text
round(task.duration * 10 * factor)
```

这会在加入 ±magnitude jitter 的同时把所有正 duration 系统性放大约 10 倍。若目的是保持一位小数精度，应同时调整单位或除回；当前函数说明只称“±magnitude”，与实现不一致。

它没有进入当前 R1/R2/S1/M1/P1 正式证据，但会污染后续 robustness 结论，需在继续使用前修正并重跑历史 perturbation 结果。

### 4.10 结构目录尚未消费新的真实语料

新 44 个 benchmark 没有完整 manifest，也没有正式的 repetition/barrier/conflict scan 结果。当前结构目录的 R1/R2/S1/P1 主要引用 code fixture 和 synthetic pipeline；M1 引用多 job 小图。

这没有违反“合成结论需收窄”的底线，但意味着 Stage 4b 的 LLM 名称目前主要来自结构动机，而不是 real-first 证据。需要把结构目录拆成：

- theorem/counterexample：不需要真实数据，但 scope 严格；
- real observation：来自 R-P/R-C/R-S，有 manifest/hash；
- algorithm judgment：说明由哪类证据支持。

## 5. 结果文档与可复现性问题

### 5.1 结果绑定了错误粒度的代码版本

`stage4_structure_experiment_20260816.json` 记录 git commit `101c7b7`，但当前 Stage 4 实现均是未提交修改或 untracked 文件。commit 只能指向修改前的仓库状态，无法重建生成结果。

至少还需要：

- dirty worktree 标志；
- `git diff` hash 或 source bundle hash；
- fixture/code hash；
- benchmark content hash；
- algorithm config hash。

### 5.2 “冻结反例 hash”与 code-only fixture 矛盾

结果 Markdown 声称 R1 使用“冻结反例 hash `694abcef…`”，但当前 catalog 明确说明反例只存在于 code fixture，benchmark corpus 仅含 real-derived case；实验 JSON 也没有该 hash 字段。

这个 hash 无法从正式产物中追踪，应删除该表述，或把 fixture 导出成自包含 adversarial benchmark 并在结果 JSON 中记录完整 hash。

### 5.3 旧 Stage 4 完成度表已经过时

`stage4_algorithm_theory_result_20260816.md` 仍称：

- 五层 benchmark 通过；
- 14 冻结文件；
- 14/14 可行回放；
- integration 实际收集；
- 结果带 commit/hash。

当前 real-first 改造后：

- 五层已不再是 Stage 4a 的主结构；
- 44 文件没有完成 manifest/index；
- integration 在本环境明确未收集；
- commit 不能重建 dirty 实现。

旧文档应保留为历史阶段结果，但加 superseded/partial 标记，不能继续作为当前完成度事实来源。

## 6. 测试与验证记录

执行命令：

```powershell
python -m pytest -q tests/llm_structured tests/integration `
  tests/test_integration_coverage.py tests/test_benchmark_format.py `
  tests/test_semantics_layout.py
```

结果：

```text
22 passed, 1 skipped, 2 failed
```

- 通过：LLM structure 现有单元测试、paired symmetry 小规模检查、新 benchmark 的大部分格式/语义检查；
- 跳过：integration coverage，原因是缺少 `jsonschema`；
- 失败：index 与磁盘文件不一致，185 vs 215。

没有重新运行耗时数小时的完整 44-case competition replay，因为本轮是审查且已有日志证明流程尚未完成。

## 7. 最终判定

### Stage 4a

**部分完成，存在 P0 冻结阻断。**

可保留：显式可抢占导出、Topology 分级、route freezing、LLM labels、44-case 首批 corpus、竞争回放原型。  
未完成：原子/可恢复生成、manifest/index、全量竞争认证、多模型覆盖、生产 topology 大规模覆盖、真实多 job、可信 multi-iteration、完整 DP provenance。

### Stage 4b

**最小目录完成，真实结构理论未闭环。**

可保留：R1、单 channel R2 restricted、M1 目标分离、静态 priority 普遍性反例、packing trap、候选方向状态表。  
未完成：真实 workload 结构扫描、多资源 symmetry proof、labelled automorphism 修正、barrier/semantic 条件规律、真正 packing、selective rollout 触发证据、真实 multi-job 条目。

当前最合理的下一步不是增加更多 heuristic，而是先让 real-first corpus 可冻结、可恢复、可分层，再用它重做 Stage 4b 的 observation/evidence 层。

