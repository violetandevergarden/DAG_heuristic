# Stage 2：single-channel complex chain 修正与推进方案

日期：2026-08-16

## 1. 目标与原则

本方案只修正和推进 `single_channel/complex_chain/preemptive`。目标是在现有公共可抢占 simulator 上建立可信的一般 DAG 研究闭环，不重写项目，也不提前混入多 channel、multi-job 或 LLM 特化算法。

实施原则：

- simulator 继续唯一负责时间推进、compute 自动闭包、依赖释放、communication 暂停/恢复和动作合法性；
- Stage 2 solver 只选择合法 communication 或搜索公共 transition；
- 先建立未压缩可信基线，再证明并启用压缩；
- 先用成对反例验证单个结构信息，再做组合和加权；
- `experiments/` 始终保持薄，只做调用、预算配置、逐例记录和汇总；
- 旧 benchmark、reference 和结果保留为历史版本，不覆盖；
- Stage 1 compatibility 结果与 Stage 2 一般 DAG 正式结果分开。

## 2. 修正优先级总览

| 优先级 | 工作 | 目的 |
|---|---|---|
| P0 | 冻结 Stage 2 contract 和历史结论边界 | 避免继续在含糊模型上产出结果 |
| P1 | 补 fork/join/barrier/同刻事件定向测试 | 固定一般 DAG 公共语义 |
| P2 | 建立未压缩 Exact、修正 status 和统计 | 获得可信 ground truth |
| P3 | 重定义基础 priority 和 join/barrier 特征 | 使算法名称、实现和研究问题一致 |
| P4 | 重做 Rollout/Beam 候选、深度和预算 | 研究有限前瞻而非单一原型 |
| P5 | 重建 Stage 2 benchmark/reference | 覆盖真正的一般 DAG 机制 |
| P6 | 建立薄的 Stage 2 独立实验报告 | 形成可复现、可分层证据 |
| P7 | 整理理论与阶段迁移结论 | 撤回错误外推并明确可推广部分 |

## 3. P0：冻结 family contract 和历史结论

### P0.1 明确“交替标准形式”的工程含义

先在 Stage 2 文档中做一个明确选择：

**方案 A：公开 benchmark 强制交替。**

- 相邻同类节点必须经语义保持的合并或显式 normalization；
- 合并不安全时，使用有清晰类型和零 work 规则的 dummy 表示；
- public validator 拒绝未规范化输入；
- 需要迁移当前 15 个含同类边的 benchmark 和全部 reference hash。

**方案 B：公开 benchmark 允许原始一般 DAG，交替只作为理论规范形式。**

- validator 允许同类边；
- 文档明确何时可合并、何时不可合并；
- 理论证明若依赖交替形式，必须给出语义保持转换；
- benchmark metadata 标注 raw/canonical form。

从当前真实/结构投影需求看，建议采用方案 B：保留原始依赖最安全，避免为形式交替插入零 communication 后又违反正 work 约束。但无论选哪一种，都必须消除目前“计划写交替、实现接受任意 DAG”的模糊状态。

### P0.2 建立 complex-chain family validator/interface

建议增加 Stage 2 专用 validation boundary，至少保证：

- DAG 无环、依赖存在、任务 ID 唯一；
- communication work 为正；
- single-channel resource 唯一且固定；
- family 允许 fork/join，不静默链化；
- 若要求单个联合 DAG，检查弱连通性；若允许多个 component，明确它们是同一 makespan 实例而非多 job；
- canonical/raw form 与 P0.1 选择一致。

public interface、registry、CLI 和实验均经过同一 validator。不要把 Stage 2 约束塞进通用 `BenchmarkDAG.validate()`。

### P0.3 立即更正历史结论状态

不删除旧文档，在新的阶段说明或勘误中明确：

- 一般 DAG 的 `T <= P+Q <= 2OPT` 当前未经证明；
- 旧 27 图只是一组历史复现集；
- Rollout 的 baseline-action 包含关系当前未由实现保证；
- Join-Rollout 与 Rollout 同结果只说明局部特征在该集合无独立贡献；
- Stage 1 的 observed optimal、链对称和 compact key 不迁移。

在新证明和新结果出现前，不继续引用这些说法作为 Stage 2 前提。

## 4. P1：建立 Stage 2 最小语义测试

### P1.1 结构契约测试

至少加入：

- 最小 fork：一个前驱释放两个后继；
- 最小 join：两个前驱共同释放一个后继；
- fork–join diamond；
- 两层 nested fork/join；
- shared downstream；
- 弱连通/多 component 的预期处理；
- cycle、未知依赖、零 communication、资源错误；
- P0.1 所选 raw/canonical form 的正反例。

### P1.2 ready 与同刻原子性测试

构造能区分错误事件顺序的样例：

- 同一时刻一个 communication 和多个 compute 完成；
- join 的最后两个前驱同刻完成；
- 零时长 compute 在 join 后形成多步自动闭包；
- fork 释放多个 compute，其中部分零时长并继续释放 communication；
- 当前 communication 在 compute event 处暂停，事件闭包后重新进入 eligible；
- barrier 只有全部分支完成后才 ready。

断言同刻事件顺序、ready/eligible 集合、remaining work 和下一合法动作，而不只断言最终 makespan。

### P1.3 trace 回放测试

对上述图使用至少两种合法策略和 Exact，分别验证：

- 依赖 finish-to-start；
- compute 单段连续；
- communication 多段工作量守恒；
- 单 channel 排他；
- forced idle 不是调度选择；
- 所有节点最终完成。

将当前 Stage 2 测试文件中的多 channel 测试迁回对应 multi-channel 测试目录；不删除测试，只修正归属。

### P1.4 独立 Oracle 固化

把本次 30 个严格交替 fork/join 图的对拍思路固化为固定 seed 测试，并扩充到：

- raw same-kind 安全样例（若 P0 允许）；
- nested join；
- 同时事件；
- 多次 preemption；
- shared successor；
- 局部相似但外部连接不同。

建议先达到至少 100–300 个极小图 `event Exact == tick Oracle`，并把失败 seed 直接固化。

## 5. P2：重建可信 Stage 2 Exact

### P2.1 先实现审计型未压缩 Exact

未压缩版本应显式保存或由完整 state 表示：

- 每个 task status/remaining；
- running compute；
- suspended/eligible communication；
- 所有多前驱完成信息；
- 当前 event time；
- 若字段可推导，也先在审计版本中保留或逐项断言推导一致。

它可以慢，但必须直接调用公共 `model.step`。目标是成为 compact key、Beam key 和 reference generator 的审计基线。

### P2.2 逐字段证明当前 normalized key

对 `(status, remaining)` key 分别说明：

- task ID 顺序固定，因此位置不会混淆节点；
- predecessor completion 可从 status 推导；
- eligible/suspended 可从 status、deps 推导；
- 决策事件后没有未记录的正在运行 communication；
- 无外部 wall-clock release、deadline、preemption cost 时，绝对时间只产生整体平移；
- `last_communication` 不影响未来成本或合法动作；
- started/completed timestamps 不影响 makespan remainder；
- 较早到达相同 normalized state 的时间支配只在上述条件下成立。

随后用未压缩 Exact、normalized Exact 和 tick Oracle 三方对拍。若未来引入时间相关成本或外部事件，key 必须失效保护，而不能静默继续使用。

### P2.3 修正 Exact 完成状态和失败接口

建议统一：

- 完整穷举并证明最优：`status='optimal'`；
- 可行但未完成：`status='feasible'`，同时给 incumbent/lower bound；
- timeout/state limit：结构化 reason，不生成 optimal sidecar；
- runtime、budget、states 写入结果；
- reference generator 强制检查 `status == 'optimal'`。

不要只依赖函数名 `exact_oracle` 或 registry 的 `exact=True` 推断最优。

### P2.4 Exact 统计

至少填充：

- explored states；
- generated transitions；
- memo/cache hits 或 deduplicated states；
- incumbent prunes；
- lower-bound prunes；
- peak frontier/cache size；
- 近似峰值内存或进程内存测量；
- runtime；
- timeout/state-limit；
- root lower bound、incumbent 和最终 gap。

### P2.5 审查并引入安全 lower bound

按顺序进行：

1. 证明 communication remaining total `P_rem` 是单 channel 下界；
2. 证明当前剩余状态的无竞争最长加权因果路径 `L_rem` 是下界；
3. 使用 `max(P_rem, L_rem)`；
4. 再研究 release/demand window；
5. 对 `Q/window/cut` 等历史字段逐项审查，不安全或无独立作用的字段不进入 Stage 2 Exact。

每个 bound 先在独立 tick Oracle 全状态上验证 `LB <= OPT_remaining`，再用于剪枝。实验分别关闭 memo、incumbent 和各 bound 做消融。

### P2.6 可解边界矩阵

生成器独立控制：

- 节点数、communication 数；
- width/depth；
- fork/join 密度；
- 最大入度/出度；
- barrier 层数；
- 同时 eligible 数；
- duration 范围；
- 关键路径重叠；
- 对称与近似对称子图。

报告 solved fraction、runtime、states、memory 和 timeout，而不是只在 27 个全部容易样例上给平均值。

## 6. P3：重定义 heuristic

### P3.1 修正简单 baseline

- FIFO：记录 communication 第一次进入 eligible 集合的事件时间；暂停后保留原 arrival，ID tie-break。
- SPT/LPT：使用当前 remaining communication work，增加暂停后选择测试。
- 所有 policy 使用相同稳定 tie-break，并把 tie-break 写入实验配置。

FIFO 所需 arrival history 是 policy 状态，不应修改 simulator 时间推进。若实验要比较 memoryless policy 与 history-aware FIFO，结果中明确标注。

### P3.2 冻结三个 residual 定义

建议先实现互不重叠的基础定义：

- Longest-delay：候选完成后**立即新增 ready** 的 compute/communication 所带来的局部 release value；若没有立即 release，值为 0。需明确多后继聚合方式。
- Longest-tail：候选完成后的最长 residual downstream path，不含候选当前 remaining。
- LRPT：包含候选当前 remaining 的最长 residual path。

为三者构造至少两个成对图：一个 fork release 图、一个 join/slack 图，使首选动作可区分。不要保留 Longest-delay 作为兼容别名。

### P3.3 分别实现结构特征，不先混合

建议按单特征函数建立：

1. immediate release gain；
2. fork release breadth 与关键 compute gain；
3. direct last blocker；
4. join distance/slack；
5. barrier urgency；
6. shared downstream 去重；
7. critical-path multiplicity；
8. downstream communication demand。

每个特征必须有：目标反例、失败机制、单独启用结果、关闭结果、运行开销。只有单特征能解释性修复目标错误且不在独立验证集系统退化，才进入组合。

### P3.4 组合纪律

优先使用可解释字典序，例如：

```text
(barrier urgency, last-blocker gain, residual tail, stable task ID)
```

若使用权重：

- 从独立 training set 或规则推导；
- validation/test 集只用于一次最终评估；
- 保存权重、seed 和调参空间；
- 报告每个特征的消融；
- 不把 metadata 中的 attack target 提供给算法。

## 7. P4：重做 Rollout 与 Beam

### P4.1 统一候选分数口径

`candidate_mode='longest_tail'` 必须与 completion baseline 的 Longest-tail 定义完全一致。若使用 inclusive tail，应命名 `lrpt`。

无论 shortlist 使用何种结构分数，都显式把 baseline 首选动作并入候选，之后再截断或保留一个 baseline slot。增加 regression：有限 shortlist 的 rollout makespan 不差于 baseline。

### P4.2 明确 depth

depth 只计 communication 决策，不计 forced idle。实现并比较：

- depth 1 / 2 / 3；
- top-k 2 / 4 / all；
- Longest-tail、LRPT、join-aware、hybrid shortlist；
- Longest-tail 与 Stage 2 结构 priority completion。

不要把“扩大 k”和“增加 depth”混为一个参数。

### P4.3 预算和 fallback

支持两类预算：

- deterministic node-expansion budget，适合可复现实验；
- wall-clock budget，适合运行环境评估。

预算耗尽时返回明确 `feasible/fallback` 信息，并保证 baseline incumbent 可用。记录 expanded nodes、evaluated candidates 和 fallback 次数。

### P4.4 Beam key 和评分审计

Beam 去重使用与 Exact 相同的、已证明安全的 normalized key。分别研究：

- width；
- search depth/horizon；
- score；
- node/time budget；
- duplicate handling；
- incumbent safeguard。

构造需要跨多个 event 才显现收益的图和大量近似对称但外部连接不同的图，检查固定 width 与错误合并。

### P4.5 Monte Carlo 降级

从 Stage 2 active registry 和正式主矩阵移除 `monte_carlo64`，代码可保留为 historical/experimental。若未来用于多样化候选或离线反例搜索，再以新用途和独立预算重新进入实验，不继续沿用“采样后取最好”作为核心算法。

## 8. P5：重建 benchmark 与 reference

### P5.1 分类现有 27 图

不删除旧图。建立清单：

- Stage 1 compatibility：7 个无 fork/join 图；
- Stage 2 structural regression：确实含一般 DAG 机制且仍有当前意义的图；
- historical regression：来源于不可抢占/旧分数、但当前不再攻击目标算法的图；
- random smoke：10 个固定 seed 图。

正式 Stage 2 汇总排除 compatibility 集，或单独列出，不让纯链样例提高一般 DAG optimal rate。

### P5.2 第一批解释性 adversarial

每个样例至少包含 fork/join/barrier/shared downstream 之一，并记录：

- attack target；
- 首个错误决策；
- 失败机制；
- Exact makespan；
- heuristic makespan/gap；
- 最优首选动作或关键 trace；
- 参数化扩展方式；
- 是否严格交替/raw canonical 状态。

优先构造：

1. fork 后短通信立即释放多个长 compute；
2. join starvation；
3. barrier slack 不均；
4. static vs residual critical path；
5. shared downstream 重复计权；
6. Longest-tail 与 LRPT 各自反例；
7. last-blocker 过度加权反例；
8. release-count 反例；
9. top-k omission；
10. depth-d rollout；
11. fixed-width beam；
12. 相似但非对称模块错误合并。

### P5.3 参数化 random generator

不要只生成 branch-to-final-join。增加可独立设置的 layered/general-DAG generator，输出结构统计到实验 raw row。仓库保留约 10 个代表 seed；规模曲线运行时生成，不无限提交 JSON。

### P5.4 建立 preemptive real/structured

先审计 communication 可抢占粒度，再导出少量固定快照。metadata 记录：

- 原 workload/模板；
- collective 或 point-to-point 的切分单位；
- 删除、合并、收缩的节点和边；
- 保留的 micro-batch/phase/barrier/cross-path 关系；
- 投影是等价、上/下界还是仅结构类比；
- topology 被投影成单 channel 的含义。

可以先从 `llm_motif_cases()` 选 2–3 个经过审计的 structured 图，而不是一次性把 7 个 nonpreemptive motif 机械 lift。

### P5.5 reference 规则

reference 只接受：

- benchmark hash 匹配；
- solver status 为 `optimal`；
- 未触发 timeout/state limit；
- trace 回放通过；
- Oracle 版本和预算已记录。

对一部分 adversarial/random/structured 小图保存 sidecar。benchmark 或语义改变后生成新 hash，不覆盖历史结果文档。

## 9. P6：薄的 Stage 2 实验入口

### P6.1 新增 Stage 2 专用 runner/config

建议新增 `experiments/preemptive/stage2_complex_chain.py`，但保持薄：

- 只加载 Stage 2 benchmark；
- 通过 stable registry/public interface 调用；
- 配置算法、top-k、depth、width 和预算；
- 写逐例 raw rows；
- 从 raw rows 生成 summary。

禁止把 residual score、candidate expansion、simulator transition 或 Exact 搜索写进 runner。

### P6.2 逐例字段

每行至少包含：

- path、id、hash、category、structure class；
- nodes/comms、depth/width、fork/join/barrier、max degree、eligible peak；
- algorithm 与完整参数；
- makespan、runtime、status；
- Exact/lower bound、ratio/gap；
- preemptions、dispatches；
- forced-idle time、channel busy time/utilization；
- explored/deduplicated/pruned states、peak memory；
- timeout/state-limit/fallback reason；
- seed、代码版本、benchmark suite version。

### P6.3 汇总纪律

分别报告：

- random；
- adversarial；
- real/structured；
- Stage 1 compatibility（单独附表）。

每组报告 count、solved count、mean/P50/P95/observed max ratio、optimal rate、runtime 分位数、preemption、forced idle、utilization。Exact 未完成的图不能进入 observed optimal 分母；只能相对安全 lower bound 报告区间或 bound gap。

### P6.4 复现旧结果

保留一份 `legacy_stage2_27` 配置，能复现本文的 27 图表格。新 contract/算法/benchmark 使用新 suite name，避免新旧表格同名。

## 10. P7：理论与阶段总结

### P7.1 安全下界

形成可独立审查的短证明：

- `P`：单 channel 上剩余 communication 总 work；
- `L`：忽略 channel 竞争的剩余最长加权因果路径；
- `max(P,L)`；
- 若 window/release-demand 更强，单独证明多前驱/共享后继下仍必要。

### P7.2 一般 DAG 近似界

先把 Stage 1 的 `P+Q` charging 明确标为不适用。若重新研究 work-conserving 上界：

- 从最后完成 sink 反向选择实际阻塞前驱；
- 检查 join 切换是否会重复收费；
- 明确 forced-idle 区间能否注入一条合法因果链；
- 用 Exact 自动搜索小反例，但不把有限枚举当证明。

没有证明时只报告 conjecture/empirical observation。

### P7.3 特殊结构

优先选择能帮助实现的可控类别：

- 单层 fork-join；
- in-tree/out-tree；
- 共同 barrier；
- 固定 width layered DAG；
- shared downstream 受限形式。

每个规则写明 DAG 类、事件语义、是否可抢占、目标和证明边界。

### P7.4 Stage 1 → Stage 2 迁移总结

最终按三类记录：

- 直接迁移：公共 simulator、trace、无 WAIT、实验纪律；
- 只迁移框架：residual computation、Rollout/Beam、Exact 搜索方法；
- 被否定或未证明：chain frontier、链对称、Stage 1 2-bound、observed optimal rate。

## 11. 建议提交拆分

建议按以下独立提交推进：

1. `stage2-contract-tests`：family contract、fork/join/barrier/同刻测试；
2. `stage2-uncompressed-exact`：审计 Exact 和三方 Oracle 对拍；
3. `stage2-exact-contract`：optimal status、structured limits、统计和 reference 检查；
4. `stage2-exact-bounds`：P/L bound、B&B 和消融；
5. `stage2-priority-baselines`：FIFO、Longest-delay、Longest-tail、LRPT；
6. `stage2-structural-features`：join/release/barrier 单特征与反例；
7. `stage2-rollout-beam`：候选口径、depth、budget、fallback；
8. `stage2-benchmarks`：分类旧图、新 adversarial/random/structured 和 reference；
9. `stage2-reporting`：薄 runner 与分层报告；
10. `stage2-theory-summary`：下界、历史勘误和迁移结论。

每个提交只改变一个可验证结论，避免同时改变 simulator、算法定义、数据集和结果表而无法定位差异。


## 12. Stage 2 完成定义

只有同时满足以下条件，才建议宣布 Stage 2 完成：

- complex-chain family contract 清晰且有正反例；
- fork/join/barrier/同刻事件由最小测试固定；
- 所有算法只通过公共 simulator，所有 trace 独立回放；
- 未压缩 Exact、normalized Exact、tick/独立 Oracle 在固定小图完全一致；
- 每个 key 压缩、时间支配和 lower bound 有安全说明；
- Exact 正确区分 optimal、feasible、timeout 和 state-limit；
- Longest-delay、Longest-tail、LRPT 有独立定义、决策差异测试和反例；
- 至少一种 join-aware 或 barrier-aware 特征完成独立消融；
- Rollout/Beam 明确 shortlist、depth、budget、fallback 和 incumbent；
- random/adversarial/real/structured 三层结果均存在；
- 主要 heuristic 有可解释、可回放的一般 DAG 失败实例；
- reference hash、optimal status 和 trace 完整匹配；
- Stage 2 有独立逐例/分层报告，不以 Stage 1 或整体 48 图均值代替；
- Stage 1 的 2-bound、链对称和 observed optimal 没有被外推；
- 已形成可进入多 channel 阶段的公共方法清单，以及仍依赖单 channel 的结论清单。
