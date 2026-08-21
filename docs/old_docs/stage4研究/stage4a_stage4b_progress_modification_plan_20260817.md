# Stage 4a / Stage 4b 修正与继续推进计划

日期：2026-08-17  
对应审查：`stage4a_stage4b_progress_review_20260817.md`  
性质：修改与研究推进方案；本轮不执行代码修改

## 1. 优先级摘要

先后顺序必须是：

```text
P0 生成事务与索引一致性
  → P1 provenance/DP/competition 契约
  → P2 real-production 覆盖扩展
  → P3 Stage 4b 真实结构扫描
  → P4 多资源理论和算法方向
```

在 P0/P1 完成前，不应继续批量生成更多 JSON；否则只会扩大无法认证的半成品集合。在 P2/P3 完成前，不应把 synthetic 目录结论升级为真实 LLM 结论。

## 2. P0：修复生成闭环

### 2.1 使用 staging + atomic promote

禁止生成器启动时直接删除正式 `benchmark/llm_structure/preemptive/`。建议：

1. 在 workspace 内建立明确的 staging 目录；
2. 在 staging 中写 benchmark、per-case report、manifest 和 index candidate；
3. 每个文件写完即校验 hash/schema；
4. 全套必要步骤成功后，再用可恢复的目录切换发布；
5. 失败时保留旧正式 corpus，不产生磁盘/index 分裂；
6. 删除旧 staging 前验证绝对路径严格位于预期目录。

若 atomic directory replace 在 Windows 上不可行，使用 versioned corpus 目录加一个小型 active manifest 指针，不做先删后写。

### 2.2 分离快速生成与慢速竞争审计

拆成三个显式命令/阶段：

```text
generate     只解析、转换、写文件、schema 校验
probe        按 case 竞争回放，可 resume，可并行
publish      验证所有必需状态后写最终 manifest/index
```

`generate` 不应等待数小时 probe 才让 index 一致。未 probe 的文件可以进入 candidate manifest，但不能进入 canonical informative set。

### 2.3 Per-case checkpoint 和状态

每个 case 生成独立 report，例如：

```text
status: generated | probing | probed | timeout | failed | excluded
generation_runtime
probe_runtime
probe_algorithm/config
competition report
error type/message
benchmark hash
```

rerun 时按 benchmark hash + probe-config hash 复用已完成报告。不要把 root 下的 `llm_probe_log.jsonl` 当作唯一恢复机制。

### 2.4 立即恢复仓库一致性

修复完成后的最低验证：

```powershell
python -m pytest -q tests/test_benchmark_format.py tests/test_semantics_layout.py
```

必须达到：

- 磁盘 benchmark 数等于 index 行数；
- 每个 index hash 匹配；
- README 声明的 manifest 实际存在；
- manifest 中每个路径存在且 hash 匹配；
- skipped/failed case 也有审计条目。

## 3. P1：修正 Stage 4a 数据契约

### 3.1 明确 suite 与真实性的两个维度

不要只用 `category=real`。增加机器可读字段：

```text
workload_origin:
  real_aicb | simai_example | synthetic

topology_origin:
  production | experimental | unified_relaxation

suite:
  R-P | R-S | R-C | control | compatibility
```

分类示例：

- 原始 AICB + Alibaba route：`real_aicb / production / R-P`；
- AICB + DP rewrite + DCN route：`real_aicb / production / R-C`；
- AICB + Cassini route：`real_aicb / experimental / R-S`；
- AICB + channel:0：`real_aicb / unified_relaxation / R-C`；
- SimAI example：`simai_example / ... / control`。

### 3.2 修正 DP/world-size provenance 和命名

每个 case 保存：

```text
source_world_size
source_dp
requested_dp
effective_dp
effective_world_size
tp / pp / ep
dp_rewrite: true|false
```

实例 ID 不再用含混 `ws8_dp4`。可以写：

```text
sourcews8_effectivews32_tp4_pp2_ep1_dp4_...
```

或在 ID 中只写 effective world size，并在 provenance 保存 source。`projection_relation` 增加 `parallelism_rewrite_projection`，可与 route freezing 组合，不要只用单字符串覆盖多个转换事实。

### 3.3 补完整 parameter/placement/route hash

现有 `canonical_parameter_hash()` 应真正用于 corpus。manifest 记录：

- 主仓库 converter commit + dirty/diff hash；
- SimAI submodule commit；
- source/topology content hash；
- 完整 generation parameter hash；
- placement policy、seed 和 placement mapping hash；
- route algorithm/config 和 frozen resource-set hash；
- duration model/version；
- semantic contract version。

不要让调用方传入的 provenance 覆盖 exporter 默认参数，导致 bandwidth、vpp、NIC 选项丢失；应做结构化深合并或明确分层字段。

### 3.4 修正 competition report 的语义名称

近期先将当前指标改名为：

```text
baseline_replay_competition
```

并记录 baseline action rule。它可以用于快速筛选，但不能证明全局 no-contention。

增加两个等级：

1. **fast probe**：沿多个确定性基线（例如 first、longest-tail、resource-aware、不同 seed）回放，报告并集/交集；
2. **certified probe**：仅对小图枚举 reachable states 或合法 action，证明是否存在多个选择。

正式 `informative` 准入至少需要：

- 某条可复现基线轨迹出现多个 eligible/合法 maximal action；或
- 小图 certified probe 证明存在；
- 并记录 action-set count、集合差异、资源 footprint 和 unlock 差异。

`none` 改为 `none_observed_under_probes`，除非完成可达性证明。

### 3.5 为 probe 增加规模可用性

- per-case `time_limit` 和 `status`；
- fast sampling 模式，只扫描前 N 决策或结构事件；
- 完整回放作为 slow suite；
- 多 case 并行执行，但每个结果独立落盘；
- 避免 `legal_actions()` 在大 eligible set 上枚举所有 maximal set，仅为找最大 cardinality；使用确定性合法 constructor。

报告 probe runtime 与 task/comm/resource 数，建立成本模型后再决定 canonical 覆盖。

### 3.6 校验 multi-iteration 语义

优先调用 `simai-flow-scheduler` 原生 multi-iteration 构造路径，或把当前 `repeat_iterations()` 与 native 输出逐项对拍：

- task/edge 数；
- iteration boundary；
- optimizer/barrier；
- rank 与通信端点；
- 首尾 iteration 的 overlap；
- 公共 trace。

在验证前把这些 case 标为 `structured_projection`，删除“standard boundary”的强断言。至少增加：

- DP>1 routed multi-iteration；
- warmup/steady/cooldown 分段指标；
- 单 iteration 与 N iteration 的结构一致性测试。

### 3.7 多 Job 仅保留 example smoke test，另建正式 R-P/R-S

按 `stage4h_multi_job_scheduling.md` 生成真实 AICB 多 job：

- homogeneous / heterogeneous；
- 同步/错峰 arrival；
- per-job DP/TP/PP/EP；
- 生产/实验 topology；
- 显式 weight 和 primary objective。

当前 `simai_example_multi_job_1to1` 改标 control/example，不计入 Stage 4h 覆盖。

## 4. P2：扩展 real-first 覆盖

### 4.1 先扩模型 family，再扩重复组合

当前 42 个 AICB 派生文件全是 Mixtral。下一批优先覆盖：

- GPT 7B；
- GPT 13B；
- GPT 22B；
- GPT 175B；
- Llama 405B；
- Mixtral 8x7B。

每个 family 先选择少量代表 shape，完成三个生产 topology 与 DP 梯度；不要先为 Mixtral 继续增加大量 GBS/MBS 近邻组合。

### 4.2 每个生产 topology 建立最低覆盖矩阵

每个生产 topology 至少包含：

```text
多个 model family
多个 TP/PP shape
DP1 控制 + 至少两个 informative DP 档
单 job single iteration
单 job multi iteration
至少一个正式 multi-job 组合
至少一个 placement 配对
```

数量不必做完整笛卡尔积，但 Spectrum-X 当前只有 1 个 routed case，必须优先补齐。

### 4.3 R-P / R-S / R-C 分别冻结

- R-P：优先原始并行配置；DP rewrite 只作为清楚标记的子组；
- R-S：相同 workload 映射 Cassini/Hermod，形成生产—压力配对；
- R-C：固定 workload，仅改变 DP/topology/placement/job/iteration 单一因素。

主表按 topology 和 suite 分层，不允许 28 个 unified case 在数量上淹没 7 个 production route case。

### 4.4 建立小图 exact 切片

“所有真实 case 都太大”不应导致 Stage 4 永久没有真实来源 ground truth。对真实 workload 做有记录的窗口/投影：

- 保留一个或两个 micro-batch；
- 保留一个 barrier 邻域；
- 保留一个资源 hotspot 的相关通信；
- 明确删边/收缩和 projection relation；
- 由 exact 生成 reference。

这些是 real-derived exact slices，不与完整大图混称严格等价；用于验证 heuristic 首动作和结构假设。

## 5. P3：修正并推进 Stage 4b

### 5.1 先更新 `stage4b_structure_theory.md`

计划文档需同步 real-first 路线：

- 将“依赖 Stage 4a 最小 motif”改为“主要使用 R-P/R-C/R-S，motif 只做证明/反例”；
- 更正固定“PP > EP > DP”的论文概括；
- 要求正式 LLM observation 绑定 manifest/hash；
- 将结构条目分为 theorem、real observation、algorithm judgment；
- 加入 DP、topology、job、iteration 和 competition level 的适用范围。

### 5.2 修复 labelled automorphism 分类

为 `signatures.py` 明确两套概念：

1. execution automorphism：保持 simulator 会读取的 kind/duration/dependency/resources；
2. feature-labelled automorphism：额外保持所有算法可见 labels。

如果结构目录声称“labelled graph automorphism”，key 必须包含正式 labels。增加负测试：两个 literal twins 的 phase/role/collective 不同，feature-labelled 分类必须拒绝。

`interface_equivalent` 与 `future_equivalent` 继续只由显式证书授予，描述扫描不得升级。

### 5.3 修复 perturbation

将 duration jitter 改为真正的：

```text
max(1, round(duration * factor))
```

如果需要固定点精度，应先明确 time-unit 转换并同步所有基线。增加 magnitude=0、范围边界和均值无 10× 漂移测试。所有使用旧 perturb 函数的 robustness 结果标记过时并重跑。

### 5.4 收紧 R2 范围和指标

短期：

- catalog formal definition 明确标为 single-channel theorem；
- resources 参数只称“静态证书预检”，不称多资源验证；
- `generated_transitions` 改为真实 transition counter；
- cache hits 改名 `memo_hits`，不要称 deduplicated states；
- 把 paired solver 的完整 future-equivalence 证明写入独立文档。

中期多资源推广：

- 使用 `PreemptiveMultiResourceModel`；
- identity/quotient 共用同一 multi-resource exact；
- 证明/测试 active resource occupancy、同刻事件、forced idle、maximal action 集双射；
- 对资源相同、资源置换、资源差异和外部资源引用分别做正/负测试。

只有这一阶段完成后，R2 scope 才能扩展为 fixed multi-resource。

### 5.5 用真实 corpus 重做结构 observation

在完成 manifest 后，对 R-P/R-C/R-S 运行：

- structural/resource/timing repetition；
- cross-microbatch dependency；
- baseline-replay temporal conflict；
- barrier/join 分类；
- phase/collective/resource footprint 分布；
- warmup/steady/cooldown 差异；
- DP 梯度与 topology 配对差异。

静态“任意两通信资源相交”指标与运行时同时 eligible 冲突必须分开。每个汇总按 source family、topology tier、DP、job、iteration 分层，并报告 unique source 数，不能把重复 iteration 当独立样本。

### 5.6 重写结构目录证据层级

建议每个条目包含：

```text
theorem/counterexample evidence
real observation evidence
model scope
topology/DP/job/iteration scope
failed conditions
algorithm decision
confidence: proved | exact-small | observed-real | synthetic-only | pending
```

当前条目建议状态：

| 条目 | 当前建议 |
|---|---|
| R1 | proved counterexample，single-channel synthetic scope |
| R2 | restricted，single-channel exact quotient |
| S1 | reject universal static priority；真实平均价值 pending |
| M1 | proved objective separation；真实 multi-job structure pending |
| P1 | baseline established/open；packing 未完成 |

### 5.7 真实语义/barrier 条目优先于新增静态标签

下一条正式 semantic entry 应来自真实 R-C 配对，例如：

- DP 增加何时产生新的同时 eligible 冲突；
- barrier 最后缺口何时改变最优首动作；
- production 与 stress topology 是否改变同一 workload 的 packing 结构；
- iteration steady state 是否比 warmup 具有更多可交换接口。

找不到可复现规律就记录 pending，不为了填目录发明固定优先级。

## 6. P4：继续算法方向的准入条件

### 6.1 Conflict-graph packing

在 P1 基线后按 `stage4f_conflict_graph_packing.md` 推进：

- 统一 conflict graph；
- 定义 `K_score/K_seed/B_pack/B_eval`；
- greedy/multi-seed/1-exchange；
- 小图全 maximal-set enumeration；
- score × constructor 消融；
- 在 R-S 中检验，在 R-P 中确认可迁移。

### 6.2 Selective rollout

保持 pending，直到 real/stress corpus 中出现：

- cheap heuristic 严格退化；
- rollout 能修复；
- 退化状态具有在线可见信号。

否则不开发复杂 trigger。

### 6.3 Barrier-aware score

只使用 residual tail、unlock、barrier last-missing、arrival spread 和 resource footprint。先在 real-derived exact slice 上验证，再在完整 R-P/R-S 上评价。

### 6.4 Multi-job

先完成 arrival/objective/schema 和真实多 job生成。M1 只负责目标分离，不为 hierarchical heuristic 提供收益保证。

## 7. 结果与历史文档治理

### 7.1 新结果必须绑定 dirty 状态

结果 environment 至少写：

```text
git_commit
worktree_dirty
diff_or_source_bundle_hash
python/dependencies/platform
benchmark_manifest_hash
fixture hashes
algorithm config hash
```

如果 dirty，不得只写 HEAD commit 后称可复现。

### 7.2 Code fixture 必须冻结或哈希

R1/R2/P1 的正式反例有两种选择：

- 导出为自包含 adversarial benchmark 并记录 benchmark hash；或
- 在结果中记录 fixture 函数源码 hash、参数和生成输出 hash。

当前无法追踪的 `694abcef…` 表述应删除或补齐来源。

### 7.3 标记旧 Stage 4 结果为历史状态

不要覆盖 2026-08-16 文档。在其旁新增 supersession note：

- 五层均衡计划已被 real-first 替代；
- 14-case 结果不是当前 44-case corpus 完成证明；
- 当前 integration 状态依环境而定；
- 新 corpus manifest/index 尚待完成。

## 8. 推荐执行批次

### 批次 1：恢复一致性

- staging/publish；
- manifest checkpoint；
- index 完整；
- 两个失败测试转绿。

### 批次 2：契约修正

- suite/origin；
- source/requested/effective DP/world size；
- placement/route/converter hash；
- competition report 改名和 status。

### 批次 3：小规模可完成 corpus

- 先挑每个模型 family 1–2 个 shape；
- 三个生产 topology 各覆盖；
- fast probe 全完成；
- 冻结 canonical v1。

### 批次 4：Stage 4b correctness

- labelled automorphism；
- perturb bug；
- R2 指标和证明；
- catalog scope 修正。

### 批次 5：真实结构分析

- R-P/R-C/R-S scan；
- DP/topology/iteration 配对；
- 新 semantic/barrier 条目；
- 方向判断更新。

### 批次 6：扩展与算法

- extended sweep；
- packing；
- real-derived exact slices；
- selective rollout/multi-job 仅在证据满足时开启。

## 9. 验收条件

### Stage 4a 下一检查点

1. 正式 corpus 不会因中断进入半生成状态；
2. manifest/index/hash 全部一致；
3. fast probe 有 status、可 resume；
4. 至少覆盖六个主要 workload family；
5. 三个生产 topology 均有多 shape、多 DP 的 informative case；
6. R-P/R-S/R-C 和 control 可机器筛选；
7. DP rewrite、multi-iteration、多 job 的 projection 边界清楚；
8. integration 实际收集并通过。

### Stage 4b 下一检查点

1. labelled automorphism 分类无误；
2. perturbation 不再系统放大 duration；
3. R2 单 channel proof/metrics 完整，多资源仍未完成时不越界表述；
4. 结构目录每条标出证据等级；
5. 至少一个正式 semantic observation 来自带 manifest/hash 的 R-P/R-C；
6. 真实 observation 按 DP/topology/job/iteration 分层；
7. P1 仍明确为 baseline/open，直到 weighted packing/local exchange 完成；
8. 旧结果的 superseded 边界已记录。

达到这两个检查点后，才适合把 Stage 4 从“首批实现与目录骨架”推进到“真实 workload 上的结构化算法研究”。

