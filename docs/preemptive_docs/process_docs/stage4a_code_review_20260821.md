# Stage 4a 代码实现审查结果

日期：2026-08-21

审查依据：`docs/plan_docs/stage4_LLM_search.md`、`docs/plan_docs/stage4a_benchmark.md`、`docs/plan_docs/outline.md`、`docs/plan_docs/simulator.md`。旧记录仅用于了解实现迁移过程，不作为当前正确性依据。

审查范围：真实输入盘点、SimAI 转换、语料生成与发布、竞争审计、真实 multi-job、真实切片、统一基线、DP 曲线、转换对拍、规模实验、活动 manifest/index、相关测试和 2026-08-18 结果资产。本轮只审查和记录，没有修改 Stage 4a 代码、benchmark 或历史结果。

## 1. 总体结论

当前 Stage 4a 应评为“部分满足”，不能标记为完成。

实现已经建立可运行的真实输入链：AICB workload 可转换为自包含 schema-v2 DAG；活动 corpus 有 72 个样例；manifest 与 index 均覆盖 72 个文件；真实 multi-job 组合、统一三基线、DP 投影曲线、top-10 规模报告和 real-derived Exact 切片均已有代码与结果。完整测试本轮为 `172 passed in 84.33s`。

但研究合同仍有几项关键缺口：

1. 活动 manifest 没有独立的 `conversion_status`、`contention_status` 和 `publication_status`，72 行都只有顶层 `status=sampled_prefix`；没有按正式枚举给出竞争分类。
2. 70 个样例只做最多 8 个决策点的前缀采样，另外 2 个小示例只证明存在多个合法动作，尚未证明动作在未来意义下非等价。
3. 发布不是覆盖活动目录、manifest、index 和 sidecar 的单一原子事务，失败时可能形成新旧资产混合。
4. 原生动态 multi-iteration 对拍仍缺失；现有转换对拍只比较任务数和边数，尚未覆盖稳定任务映射、duration、资源、标签和事件顺序。
5. DP、topology、iteration 和 multi-job 四类受控证据只完成了一部分。DP 报告主要是规模与回放成本，缺少纲领要求的动态竞争强度；topology 和 iteration 没有正式配对报告。
6. 基线的时间预算不是严格墙钟上限。一个标称 90 秒的 FIFO 运行在约 894 秒后才返回 timeout；另有标称 120 秒的运行在约 169--173 秒完成并被记为 completed。

因此，现有资产足以支持继续修正 4a 基础设施、做受限结构探索和小图校准，但不足以把全部 72 个样例当作已通过竞争准入的正式算法测试集，也不足以声称 Stage 4a 已完成。

## 2. 已满足或已有可靠基础的部分

### 2.1 公共调度语义

`benchmark_generate/simai/export.py` 显式导出 `communication_resume`、`task_event`、无主动等待、compute 无界并行和固定排他资源集合。单 channel 使用统一资源，多资源通信绑定固定非空资源集合。算法和实验通过公共模拟器推进状态，没有在 Stage 4a runner 中另写一套时间语义。

集成测试覆盖五种 pipeline builder 的有效导出、固定路由资源、暂停恢复、资源原子取得、forced idle 和同刻事件。该部分满足“先服从公共模拟器语义”的要求。

### 2.2 真实输入和自包含导出

`benchmark_generate/llm/catalog.py` 能扫描 AICB 文件、解析主要并行参数、计算内容 hash，并把无法识别的文件放入 quarantine。`benchmark_generate/simai/export.py` 保存源文件、topology、参数和转换器来源，导出结果不要求算法运行时加载 SimAI。

当前活动 corpus 有 72 个文件，覆盖 32 个单 channel 和 40 个固定多资源样例。活动 manifest 与 `benchmark/index.jsonl` 均有 72 个 LLM 条目；仓库格式测试会核对活动文件、manifest 和 index 的一致性。

### 2.3 真实 multi-job 组合语义

`benchmark_generate/llm/real_multi_job.py` 为每个 job 建立稳定命名空间，只给各 job 的源节点增加本 job arrival 释放节点，不添加跨 job 训练依赖，并复用全局同名固定资源。三个真实 AICB 组合实验分别覆盖同构单通道、异构多资源同时到达和错峰到达，报告 makespan 与逐 job JCT，目标没有混写。

需要注意，这三个 case 属于结果目录中的实验资产，尚未进入活动 corpus 的正式 manifest 和竞争分类流程。

### 2.4 Exact 切片

`benchmark_generate/llm/slice.py` 明确把切片描述为投影，记录源 hash、保留范围、被切断边和资源。三个切片中两个多资源切片得到 `optimal`，单 channel 切片如实保留 `feasible`。未把未完成枚举写成最优，这一点符合证据要求。

### 2.5 结果中的前缀和未完成状态

当前 manifest 的 72 个 probe 都明确写为 `fast_prefix`、`sampled_prefix`、`complete_trace=false`，并带 `probe_config_hash` 和 `contention-audit-v2`。70 个大图是 `not_run_size_limit`，2 个小例为有界认证。规模报告和 Exact 报告也保留 timeout、feasible 和未测量状态，没有用当前模拟时间冒充完整 makespan。

## 3. 主要问题

### 3.1 高：manifest 没有实现三类状态分离

纲领要求分别保存转换状态、竞争状态和发布状态。当前 `benchmark_generate/llm/corpus.py` 仍用一个 `STATUSES` 集合和顶层 `status` 混合表示 generated、sampled_prefix、completed、timeout、failed、excluded 等不同维度。活动 manifest 也没有 `conversion_status`、`contention_status`、`publication_status`、正式竞争分类、报告 hash 和发布 run ID。

影响：

- 无法只看 manifest 判断文件是否转换通过、是否发布、竞争证据达到哪一级；
- `sampled_prefix` 同时承担流程状态和证据范围，无法表达“已发布但竞争未知”等组合；
- 后续 4b--4g 难以按 `informative-certified`、`informative-observed`、`unknown-timeout` 等类别稳定选样。

### 3.2 高：小图“认证”没有检查动作未来非等价

`_certified_reachable_choice()` 在发现 `len(legal_actions) > 1` 时立即返回 `certified`。它没有执行各动作并比较 residual state，也没有处理对称状态或未来等价。因此当前字段实际证明的是“存在多个合法动作”，不是纲领定义的“存在多个非等价合法动作”。

影响：活动 manifest 中两个 `certified_reachable_choice=true` 不能直接升级为 `informative-certified`。它们最多是有界的合法动作存在性证据。

### 3.3 高：发布流程不满足原子发布合同

`publish()` 会先校验 candidate manifest 中列出的文件，然后把旧 `preemptive` 目录移到备份，再把 candidate 目录移入活动位置，之后才复制 source catalog/run metadata、写活动 manifest 并调用 `build_index()`。

仍缺少：

- 校验 candidate manifest 是否完整覆盖 candidate 下所有 JSON；
- 强制每行有路径、合法 schema/status 和唯一非空 benchmark ID；
- 把 source catalog、run metadata、manifest 和 index 与 corpus 一起形成一致快照；
- manifest/index 写失败时自动回滚旧 active；
- 发布中断和 index 写失败的故障注入测试。

因此“发布前的单文件校验”已有，但“整个活动快照原子替换”未实现。

### 3.4 高：基线时间预算不是严格上限

`stage4a_baselines.py` 只在外层决策循环开始处检查时间。一次 `model.step()`、状态规范化、Longest Tail 打分、完成后的二次 `model.run(actions)` 和独立 trace 验证均不能被预算中断。

当前结果已有直接证据：

- `mixtral8x7b_ws8_tp2_pp4_ep1_dp1_gbs16_mbs4` 的 FIFO 标称预算 90 秒，约 894 秒后才记录 timeout；
- DP 曲线中一个标称 120 秒的 dp=2 样例，FIFO/固定顺序分别约 173/169 秒完成并记为 completed。

影响：统一预算的完成率和运行成本不能按“严格 90s/120s 截止”解释；AGENTS 当前摘要中“dp>=2 三基线完整回放全部超过 120s 预算”的表述也应理解为成本证据，而不是严格进程级超时实验。

### 3.5 高：转换对拍不足以获得完整转换认证

`stage4a_conversion_pairing.py` 只比较三个 Mixtral 配置的 builder/export 任务数、flow 数、总边数和 serializer compute-order 边数。现有数据证明任务数 1:1，边差来自 compute-order 显式化的一部分，但尚未逐项保存：

- 原始任务到导出任务的稳定对应；
- 原始边、真正新增边、重复边和无法对应边；
- duration、stage、micro-batch、iteration 标签；
- route-resource 映射；
- 可比条件下的事件顺序；
- SimAI 动态 executor 的原生多 iteration 结果。

所以退出条件 3 仍是部分满足，多 iteration 只能保持 `structured_projection`。

### 3.6 中：竞争审计缺少正式分类和完整逐样例指标

fast probe 的边界标注是正确的，但只沿一条确定前缀运行。多资源在 eligible 数不超过 256 时仍可能枚举全部极大集合；超过阈值时只构造一个集合。报告没有非等价动作数、首次/最后竞争时间、竞争持续时间、策略分歧、抢占机会、compute/barrier 释放和热点资源等完整指标。

`experiments/llm_structure/contention_census.py` 提供了更丰富的有界扫描原型，但仍只沿单条轨迹，且没有作为 4a 的统一审计合同写回 manifest。当前没有全量 `informative-*`、`no-choice-*`、`unknown-*` 分类表。

### 3.7 中：受控曲线只完成一部分

- DP：有 dp=1/2/4 投影和三基线成本，但报告缺少静态相交、动态证据等级、竞争次数、抢占、forced idle、利用率和步骤成本，不能判断 DP 是否增加了有效竞争。
- Topology：活动 corpus 有同源多 topology 文件，但没有按单变量固定条件形成正式 topology 配对报告，也未分离 duration 改变和资源冲突改变。
- Iteration：有 2/4 iteration 投影，但原生对拍未完成，不能开展正式 iteration 趋势结论。
- Multi-job：三个组合验证了组合语义和 JCT 输出，但没有 1/2/3/4 job 曲线，也没有进入统一竞争审计和发布清单。

### 3.8 中：基线结果合同不完整

基线 runner 会调用独立 trace validator，这是优点；但归档结果没有保存可重放动作/trace，只保存 hash。报告还缺少峰值内存、逐资源利用率、通信区间数、规则版本或配置 hash、run ID 和源码 bundle hash。多资源三基线使用一致的贪心补全思路，但 FIFO 是 runner 内单独实现，固定顺序/Longest Tail 调用 solver helper，缺少显式的共同 packing 版本字段。

### 3.9 中：资产盘点和文档仍不完全一致

`source_catalog.jsonl` 只盘点 workload，没有独立 topology 清单和来源核查记录。`run_metadata.jsonl` 保存 commit、dirty 和 bundle hash，但没有 Python、依赖、操作系统、生成命令、seed、SimAI dirty 状态等完整环境。

`benchmark/llm_structure/README.md` 仍写“小/中规模 39 个中 28 个完整成功”，当前 summary 实际为 36 个完整、3 个不完整；README 还把若干 topology 直接称为 production，但仓库内没有随附的来源认证清单。文档链接虽存在，数字已经过期。

### 3.10 中：规模报告未覆盖纲领要求的全部分步骤

top-10 报告保存文件大小、8 决策 probe 时间和 Python 峰值内存、三基线状态；但只对两个不超过 40k 任务的样例重测转换，其他为 `not_measured_size_limit`。没有分别测量解析、SimAI builder、JSON 写出、schema/loader、静态扫描、完整 census、trace 验证，也没有按高边密度、高通信比例或高冲突补充困难样例。

## 4. 12 项退出条件评估

| 编号 | 状态 | 审查判断 |
| --- | --- | --- |
| 1 | 部分满足 | workload 清单和 hash 已有；topology 来源清单、完整环境与命令信息不足。 |
| 2 | 部分满足 | 任务、资源、multi-job 等有实现和测试；duration 规范、iteration 原生语义和完整字段映射测试不足。 |
| 3 | 未满足 | 只有任务/边计数对拍，原生执行、资源、duration、标签、事件顺序和 multi-iteration 对拍缺失。 |
| 4 | 部分满足 | 当前 corpus/manifest/index 数量和 hash 有测试保护；从 staging 可复现及整体原子发布未证明。 |
| 5 | 未满足 | 每例没有独立的转换、竞争分类、证据等级和发布状态。 |
| 6 | 部分满足 | 前缀与完整/有界字段大体分开；小图认证仍把“多个合法动作”当成选择证据。 |
| 7 | 未满足 | DP 和 multi-job 有初步结果；topology、iteration 正式配对和有效竞争指标缺失。 |
| 8 | 部分满足 | 39 个样例中 36 个三基线完成，未完成状态保留；预算不严格，输出字段不完整。 |
| 9 | 部分满足 | 两个最优证书和一个 feasible 已如实保存；报告缺上下界、最优首动作和内存。 |
| 10 | 部分满足 | 有 top-10 probe/内存/基线报告；分步骤测量不完整。 |
| 11 | 未满足 | 没有按正式类别保存无竞争、未观察、未知、无效和排除清单。 |
| 12 | 未满足 | 尚未形成供 4b--4g 使用的冻结分层清单及结论边界。 |

## 5. 可支持与不可支持的当前结论

当前可以支持：

- 真实 AICB 输入到项目自包含 DAG 的转换链可运行；
- 当前 72 个活动文件通过格式与公共模拟器回归测试；
- 最多 8 个决策点的前缀 probe 对大图可运行，但它不是全图认证；
- 一部分不超过 12000 任务的样例可以完成三基线；
- DP 扩展和大图明显增加当前 Python 回放成本；
- 三个真实 AICB multi-job 组合能按独立 namespace、arrival 和共享资源运行；
- 两个真实来源多资源切片有 Exact 最优证书。

当前不能支持：

- 72 个正式样例全部存在可利用竞争；
- 前缀未观察到竞争等于全图无竞争；
- 两个小例已经证明存在未来非等价动作；
- DP 增大稳定增加有效竞争；
- 某类 topology 的收益或真实性已经得到验证；
- 多 iteration 已与 SimAI 原生执行一致；
- 90s/120s 是严格、可公平比较的墙钟截止；
- Stage 4a 已完成，或当前 72-case corpus 可不加筛选地交给 4b--4g 做正式收益结论。

## 6. 测试核验

本轮运行：

```text
python -m pytest -q
172 passed in 84.33s
```

测试通过证明当前已有合同没有显式回归，不代表退出条件自动满足。缺失测试主要集中在发布故障注入、三类状态 schema、动作非等价认证、严格超时、原生动态 multi-iteration 对拍、topology 清单和完整 Stage 4a 端到端流程。

