# Stage 4b：LLM 结构理论探索结果与算法方向判定

日期：2026-08-16  
机器可读目录：`docs/result_docs/stage4_structure_catalog_20260816.json`  
实验证据：`docs/result_docs/stage4_structure_experiment_20260816.json`（git `101c7b7`，Python 3.13.13）  
执行语义：stage4-v1（communication_resume、task_event、无主动 WAIT、exclusive fixed resource set、零抢占开销）。所有结论只在其声明的模型范围内成立。

## 附记（同日稍晚）：真实语料竞争结构实测

在真实 Mixtral-8x7B AICB 语料（936 个文件）与 6 个真实拓扑上生成了
`benchmark/llm_structure/` 语料（44 个可抢占 benchmark，见代码修正结果附记），
每个文件都经过公共模拟器完整回放并量化了调度竞争（`manifest.jsonl` 的 `competition`
字段）。这轮实测对结构理论有三个直接修正/确认：

1. **DP 维度决定多资源竞争的存在性（用户预判被证实）**：原生 Mixtral 网格
   `dp = all_gpus/(tp*pp) = 1`。生产拓扑 + dp=1 的多资源图几乎无竞争
   （AlibabaHPN_16g / Spectrum-X_16g 上 ~4500 个决策点仅 3 个存在资源冲突对，
   competition_level=low/none）；同样的 workload 在单通道统一瓶颈下竞争为
   high（93% 决策点有竞争、max eligible 10、5.2 万个冲突对）。结论：**多资源算法
   评估必须使用 dp>1（或链路集中型拓扑）的案例；单通道与多资源的竞争结构必须分开
   报告**，不能用一个数字混过去。
2. **拓扑分级有效**：小规模实验拓扑（Cassini 24g/64g、Hermod 32g）用于集中链路冲突、
   生产拓扑（AlibabaHPN/Spectrum-X/DCN）用于真实评估的分级方式可行；各文件
   provenance 记录拓扑 tier，实验结论按 tier 分组引用。
3. **精确 reference 的适用边界**：语料最小图（数千通信）也超出当前 exact 的预算，
   且 oracle 的下界预处理与时间轴长度成正比（makespan 百万微秒级），5 秒预算在
   预处理阶段即失效。本轮所有文件的 `reference_optimal_makespan` 为空，算法评价
   以 manifest 的可行回放基线与竞争指标为准；exact 可解缩小版是独立后续工作。

结构目录五个正式条目（R1/R2/S1/M1/P1）的判定不变；其中 benchmark 文件引用改为
代码内 fixture + 测试 + 实验 JSON 引用（见目录 JSON 的 `fixture_note`）。

## 1. 结论摘要

1. **R1（重复 motif 不推出局部策略有效）成立**：单 channel 反例上 copy-local 为 `3n-1`、最优为 `2n`，比值趋于 1.5。
2. **R2（严格独立同构分量置换压缩）限制开放**：配对 exact 证明排序分量 runtime 向量是精确商；7 副本时状态数 99207 → 203（约 489 倍），makespan 全程一致；多资源推广以证书字段（资源集合一致）和负测试为条件。
3. **S1（静态语义角色优先级不足）被否决**：固定 PP/DP 优先规则在全部 6 个合成 pipeline 骨架上严格差于 longest_tail/rollout2，在 R1 反例上恶化到 1.5 倍。
4. **M1（多 job 目标分离）成立**：同一实例 makespan 最优的 weighted JCT 为 10.5，weighted JCT 最优为 6.0（makespan 均为 11）。
5. **P1（packing 债务）基线落地**：三个已部署 greedy 基线在 trap 与 Stage 3 兼容样例上全最优；按流量大小选 seed 在冻结 trap 上 18 vs 最优 13；旧 K=1/K=2 反例（25 vs 18）确认撤回。
6. 预注册候选清单给出首个有证据判定：否决 1 项（静态优先级）、限制开放 1 项（对称压缩）、开放 1 项（packing）、独立轨道 1 项（multi-job）、待定 1 项（selective rollout）。

## 2. 结构目录（正式条目）

### 2.1 R1：重复 motif 不推出局部策略有效 —— 已证实（否决 copy-local）

- **定义**：对 n 个重复单元组成的 DAG，逐单元复制"孤立单元内最优"的动作不能保证全局最优；单元边界的释放耦合放大局部误差。
- **证据**（`stage4_structure_experiment_20260816.json` r1 段，冻结反例 hash `694abcef…`）：

| periods | optimum | copy_dp_local | copy_pp_static | longest_tail / rollout2 / coupling-aware |
|---:|---:|---:|---:|---:|
| 1 | 2 | 2 | 3 | 2 |
| 2 | 4 | 5 | 5 | 4 |
| 4 | 8 | 11 | 9 | 8 |
| 8 | 16 | 23 | 17 | 16 |

copy-local 序列为 `3n-1`，最优为 `2n`，比值单调趋于 1.5。
- **判定**：**否决**"仅凭重复率/单元内最优采用逐副本局部调度"。不否决携带 boundary/coupling 信息的方法（coupling-aware 在该构造上达到最优，但见 S1：它不构成通用收益）。
- 依据 benchmark：`s4_adv_copy_local.json`（reference 16）、`s4_adv_static_role_priority.json`（reference 8）。

### 2.2 R2：严格独立同构分量的置换压缩 —— 限制开放

- **定义**：分量两两不相交、每位置 (kind, duration, role, labels, resources) 相同、分量内依赖形状相同且无跨分量边时，分量置换是带资源映射的标签 DAG 自同构，排序分量 runtime 向量是**精确商**。
- **配对证据**（同一搜索体仅换 memo key；身份 key 状态数恰好复现历史数字 66/501/3163/18134/99207，说明旧数字来自同一枚举顺序的身份 key）：

| replicas | identity states | quotient states | 缩减倍数 | makespan |
|---:|---:|---:|---:|---|
| 2 | 13 | 8 | 1.6× | 一致 |
| 3 | 66 | 16 | 4.1× | 一致 |
| 4 | 501 | 38 | 13.2× | 一致 |
| 5 | 3163 | 73 | 43.3× | 一致 |
| 6 | 18134 | 126 | 143.9× | 一致 |
| 7 | 99207 | 203 | 488.7× | 一致（均 optimal） |

- **负测试**（`tests/llm_structured/test_paired_symmetry.py`）：跨分量边、单分量时长扰动、单分量资源集合不同，均被证书拒绝（`ValueError`）；冻结守卫样例 `s4_adv_symmetry_merge_guard.json`。
- **多资源义务**：证书增加资源集合一致检查；多资源 normalized 与 uncompressed exact 在小图交叉验证一致（packing_trap 13、atomic_acquire 9、maximal_not_maximum 9，均 optimal）。仍待证明的字段（占用状态、同时刻事件集、maximal action 集）列入 proof obligations。
- **判定**：**restricted** —— 仅证书检查通过时启用；一般周期块、跨 micro-batch 共享同步、非同构 stage、pipeline carry 保持 pending，不得自动压缩。

### 2.3 S1：静态语义角色优先级不足 —— 否决

- **证据**：6 个合成 pipeline 骨架（1F1B / interleaved / zero-bubble × ga 2/4）上，固定 PP 或 DP 优先规则的 ratio 均为 1.000–1.002 且严格差于 longest_tail/rollout2（ga=2 三例中后者达到 exact 最优，如 1F1B ga=2 最优 3361697）；同一条规则在 R1 反例上达 1.5 倍。
- **判定**：**否决**固定全局 "PP > EP > DP" 类角色优先级（也修正论文表述：Hermod 初步结果把 EP 与 PP 整体置于 DP 之前，具体顺序依结构而定）。保留 residual-criticality + phase + barrier proximity + 资源冲突的**条件**评分研究，并要求分层消融。

### 2.4 M1：多 job 目标分离 —— 已证实（独立轨道）

- **证据**：两 job 实例 makespan 均为 11；makespan 最优调度的 weighted JCT = 10.5，weighted JCT 最优调度 = 6.0。candidate-width=1 截断在 top1 反例上 19 vs 完整 18。
- **判定**：多 job 是独立实验轨道，objective/arrival/weight 单列；不得用 weighted JCT 收益论证单 job makespan 算法。当前仅冻结 `s4_real_multi_job_1to1.json` 快照，多 job benchmark 层是后续 4a 增量。

### 2.5 P1：conflict-graph packing 基线 —— 基线落地 + 反例冻结

- **事实**：maximal-compatible-set 的 maximalizer 属于模拟器合法性；seed 打分决定集合构造。三个已部署基线（longest_tail_pack / resource_pack / bottleneck_pack）在冻结 trap 与 Stage 3 兼容样例上全部达到最优（13/9/9）。
- **反例**：`s4_adv_packing_trap.json` 冻结"按流量大小选 seed"的失败——18 vs 最优 13（ratio 1.385）；该 trap 守护的是 seed 打分必须携带冲突结构信息，而不是 maximal 语义本身。
- **K 语义**：旧 `K=1`（25）vs `K=2`（18）反例**撤回**（当前语义下 K=1/K=2/flat 首动作同为 `{A::private, B::shared}`、makespan 均 18）。K 只能按 `K_seed`（seed 排名宽度）/ `B_pack`（集合搜索预算）/ `K_score`（昂贵打分预算）定义后再比较。
- **判定**：**开放**受预算的加权 packing / local exchange / 精确集合搜索研究；先统一预算定义，再做消融与反例。

## 3. 预注册候选方向的判定

| 方向（stage4_LLM_search.md §4） | 判定 | 依据 |
|---|---|---|
| 选择性 Rollout | **pending** | 未发现"关键点"可识别信号：本批探针中 rollout2 全程 ≈ longest_tail 且后者已在 ga=2 上达最优，没有出现 LT 退化而 rollout 修复的窗口。触发条件（模糊度/barrier 邻近/phase 转换）需在可观测在线特征上再验证。 |
| 重复结构压缩/摊销 | **restricted** | 仅开放 R2 证书化特例（paired solver 已实现）；周期缓存、一般 template key 因跨副本冲突保持 pending。 |
| LLM 特化 score | **部分否决 + 研究继续** | 静态固定优先级被否决（S1）；条件化 score（residual tail + phase + barrier proximity + conflict footprint）继续研究，必须分层消融。 |
| conflict-graph packing | **open（继承债务）** | 基线与反例已落地（P1）；下一步统一 K_seed/B_pack/K_score 并实现 weighted packing/local exchange。 |
| multi-job | **independent_track** | M1 证据成立；迁移到公共 fixed-resource 模拟器后单列目标报告。 |

## 4. 旧结论复核（stage4b §4.1 + 审查 §7）

| 旧结论 | 复核结果 |
|---|---|
| 旧阶段5：micro-batch 模板高度重复、跨 mb 冲突强、不能直接复制单周期调度 | **成立并收窄**（R1 反例复核；"冲突强"保留为描述性度量，不作为压缩依据） |
| 旧阶段5：严格收益来自对称状态压缩而非周期 priority | **收窄后成立**（R2 配对验证；周期缓存方向仍 pending） |
| 旧阶段6：单/多 job 分层调度初步结果 | 目标分离**复核成立**（M1）；分层收益数字**降级为待复核**（缺 lineage），不在本表使用 |
| 旧阶段7 计划 | 作为预注册清单逐项判定（见 §3），不直接继承 |
| Coflow "PP > EP > DP" | **撤回并修正**为"EP 与 PP 整体高于 DP，具体顺序依结构/因子而定" |
| 多资源 K=1=25、K=2=18 候选宽度结论 | **撤回**（当前 maximal-compatible 语义下两者均 18） |
| 6 个 AICB 图 94%–99% 重复率、78.65%–79.08% 跨 mb 冲突 | **降级待复核**（缺冻结输入/版本/转换 manifest） |
| 历史 symmetry 状态缩减倍数（66→… vs 旧 JSON） | 旧比较不受控，**不再引用**；本次给出配对对照新数字（§2.2） |

## 5. 对 Stage 4 验收项的当前状态

| 验收项 | 状态 |
|---|---|
| 五层 benchmark | 通过（14 冻结文件 + compatibility 清单 + 集合 manifest） |
| 自包含且固定资源 | 通过（资源集自包含；route 冻结保留） |
| 可抢占公共模拟语义 | 通过（exporter 显式 v2；5 个端到端语义测试） |
| 转换可追溯、可重放 | 通过（provenance/transform_log/projection_relation/内容 hash + 14/14 可行回放） |
| 正式结构目录 | 通过（R1/R2/S1/M1/P1，Markdown + JSON 双份） |
| repeat 正/反证据 | 通过（R2 配对正证据 + R1/守卫反例） |
| semantic 结构结论 | 通过（S1 否决 + 条件化方向） |
| multi-job 条目 | 通过（M1 独立轨道） |
| 冲突图 packing 债务 | 部分（基线 + 反例 + K 重定义落地；weighted packing/local exchange 实现仍为后续工作） |
| 结果可复现 | 部分（新实验带预算/状态/commit/hash；integration 实际收集；历史结果迁移标注完成） |

## 6. 下一步

1. **P1 续**：实现 weighted packing / local exchange 与受预算精确集合搜索，统一 `K_seed/B_pack/K_score` 后做 seed 消融。
2. **R2 多资源化**：把分量置换商推广到 `PreemptiveMultiResourceModel`（占用状态、事件集、maximal action 集的 future-equivalence 证明 + 未压缩交叉验证）。
3. **selective rollout 触发证据**：在五层 benchmark 上扫描 LT 的退化窗口，只用在线可见 residual 特征定义 trigger；找不到就维持 pending 并记录。
4. **多 job benchmark 层**：在 4a 增加显式 arrival/weight 的多 job 样本，接公共 fixed-resource 模拟器。
5. real_derived 扩展：在获得可合法共享的真实 AICB 输入后再扩充；当前两个 SimAI 示例快照已明确标注"example workload，非生产 trace"。

## 7. 边界声明

- 全部结论限于 stage4-v1 语义（固定资源、可抢占通信、单 job makespan）；多 job 结论单列目标。
- synthetic motif 与示例 workload 投影不构成真实网络收益证据；`structured_projection`/`real_derived` 的投影关系已在每个文件 metadata 中声明（relaxation / route-frozen）。
- 实验最优率不替代理论近似比；本目录只对 R1（严格构造比值）、R2（图自同构 + 精确商）、M1（目标分离小图）给出证明级结论，其余为证据级判断。
