# Stage 1：single-channel parallel chain 建议推进方案

日期：2026-08-16

## 1. 目标与约束

本方案只推进 `single_channel/parallel_chain/preemptive`。目标不是重写公共模拟器，也不是提前进入 complex chain，而是在已有公共可抢占状态转移之上，把 Stage 1 做成定义清楚、可交叉验证、可独立报告的研究基线。

推进过程中保持以下边界：

- 公共 simulator 继续拥有时间推进、依赖释放、抢占/恢复和合法性判定；
- parallel-chain 算法只从 simulator 给出的合法 communication 中选择；
- `experiments/` 始终是薄 runner，不承载算法和另一套执行逻辑；
- 不借修正一阶段之机重构不可抢占、complex-chain 或多 channel 代码；
- 旧结果保留为历史基线，新语义/算法产生新的版本化结果。

## 2. 建议优先级

### P0：冻结一阶段输入与算法定义

这是后续 Exact、benchmark 和实验可信的前提，应最先完成。

#### P0.1 建立中立的 ParallelChain 规范表示

建议在 parallel-chain family 或公共 benchmark model 中定义中立结构，不从 `nonpreemptive/solver.py` 导入当前研究所需的数据类或转换函数。

它至少应表达：

- 多条互不相连的简单路径；
- 每条路径 compute/communication 严格交替；
- 可以 compute 或 communication 开始；
- 可以 compute 或 communication 结束；
- compute duration 可为 0；
- communication work 必须为正；
- 单 channel communication resource 规范一致。

需要先决定并记录：对于“路径合法但未交替”的输入，是严格拒绝，还是由一个显式、可追踪的 normalization 转换。建议 benchmark 和公开 family 入口默认严格拒绝，避免悄悄改变研究实例。

同步修改范围：family validator、benchmark validator/schema 约束或补充语义校验、loader/generator，以及对应错误信息。不要修改公共 DAG validator 去强加一阶段特有约束。

#### P0.2 冻结四类 baseline 的数学定义

建议在代码 docstring、阶段文档补充说明和测试中使用同一组定义：

- FIFO：按 communication 第一次进入 eligible 集合的时间排序，ID 稳定 tie-break；暂停后恢复仍保留原 arrival time。
- Longest-delay：明确为“当前 communication 完成后首先解锁的连续 compute delay”或另一确定的局部定义；若无法给出独立且有研究意义的定义，先从公开矩阵移除，不保留伪独立别名。
- Longest-tail：当前 communication 完成之后的 residual downstream tail，不包含当前 communication 剩余工作。
- LRPT：包含当前 communication 剩余工作的 residual path。

对零时长 compute、以 communication 结束的链、相同分数和暂停后剩余量定义 tie-break。

#### P0.3 固定 Rollout/Beam 的候选语义

明确记录：

- shortlist 是按 Longest-tail、LRPT 还是其他分数构造；
- completion policy 是什么；
- baseline 首选动作是否强制进入候选集；
- horizon、beam width、重复状态去重和 tie-break；
- timeout/limit 时如何报告，是否允许 fallback。

修正当前 `mode="tail"` 名称与实际 inclusive-tail 排序不一致的问题。若选择保留现有行为，应改名为 LRPT shortlist 并重跑相应结果，而不是只改注释。

### P1：先补最小回归测试，再修算法入口

#### P1.1 family 合法性测试

至少覆盖：

- compute 开始/compute 结束；
- communication 开始/communication 结束；
- 零时长 compute；
- 连续 compute、连续 communication 被拒绝；
- fork、join、跨链依赖被拒绝；
- 零 work communication 被拒绝；
- 合法图在 loader、family interface 和 solver 三处判定一致。

#### P1.2 算法区分测试

把本次发现的最小证据固化：

- 早到的 `z` 与晚到的 `a`，验证 FIFO 按首次 eligible 时间而非静态 ID；
- 构造 Longest-delay、Longest-tail、LRPT 首选动作至少两两不同的图；
- 构造 shortlist 定义会改变 Rollout 首选项的图；
- 验证暂停/恢复不改变 FIFO arrival time，tail 使用当前 remaining work；
- 所有同分情况按公开规则稳定选择。

FIFO 如需记忆首次 eligible 时间，应把它作为 policy 的显式运行状态或由 simulator 提供只读历史字段，不能通过修改时间推进逻辑实现。

#### P1.3 收紧一阶段 registry

registry 只暴露一阶段确有定义和测试的算法。建议：

- 暂时移除或标记 `join_rollout2` 不适用于 parallel chain；
- 将 `monte_carlo64` 放入 historical/experimental 显式命名空间，而非核心算法矩阵；
- 在 Longest-delay 有独立实现前去掉该别名或改名说明兼容关系；
- 保留通用实现复用，但 public entry 必须经过 parallel-chain validator。

### P2：实现 compact chain-specific Exact

这是一阶段最关键的实现任务，但仍应复用公共 simulator 的单步转移。

#### P2.1 状态表示建议

以每条链的 frontier 为核心，保存所有影响未来的量：

- 每条链当前完成位置；
- frontier compute 的剩余/完成事件信息；
- frontier communication 的剩余工作；
- 当前 channel 上运行的 communication（若状态语义需要）；
- 当前时刻或可安全归一化的相对事件时间；
- 任何会影响 FIFO 等有历史策略的字段不应混入 Exact 状态，除非 Exact 的目标本身依赖它。

先做无损 compact key，再考虑同构链对称性。每一种压缩都要说明为什么不会使两个未来不等价的状态合并。

#### P2.2 搜索与 lower bound

建议按可验证顺序推进：

1. 无压缩/少压缩的 chain-frontier 枚举；
2. 与现有通用 Exact 逐例交叉验证；
3. 集成 `max(P_remaining, Q_remaining, residual critical path)` 一类可证明 admissible 的 lower bound；
4. 增加 incumbent、branch-and-bound 和重复状态去重；
5. 最后再加入同构链对称性、dominance 或 A*/best-first 优化。

不得为了加速丢掉影响未来 compute release 或 communication remaining work 的信息。

#### P2.3 Oracle 交叉验证门槛

把本次临时的 30 图核验扩成固定测试/生成式测试：

- 严格交替的小图；
- 包含零 compute、communication 起止、同时事件、重复抢占；
- compact Exact vs 独立 tick Oracle；
- compact Exact vs 现有通用 event Exact；
- schedule 再由独立 trace validator 回放。

建议在提交 compact Exact 前达到至少数百个固定 seed 小图无差异。出现 timeout 必须是明确状态，不可输出 optimal 标记。

#### P2.4 规模报告

对链数、每链段数、duration 范围分别扩展，报告：

- solved/timeout/state-limit；
- runtime、展开状态数、去重状态数；
- lower-bound pruning 数；
- compact 与 generic Exact 的相对规模；
- 最终 makespan 一致性。

这才足以支撑“compact Exact 比通用 Exact 更适合阶段一”的结论。

### P3：重建一阶段 benchmark 证据链

#### P3.1 保留但重新标注历史 lift 样例

不删除旧样例。为从 v1/不可抢占探索 lift 的文件补充清晰 metadata 或伴随清单：

- historical origin；
- 原先攻击对象；
- 在当前可抢占、无 WAIT 语义下是否仍有意义；
- 若仍是 adversarial，说明它攻击的算法与机制；
- 若只是回归样例，移至合适类别或标为 legacy regression，而不是继续暗示当前理论反例。

不要依赖算法可读取的 metadata 暗示答案。

#### P3.2 建设解释充分的 adversarial family

分别为以下对象建立参数化小族并给出机制说明：

- eligibility FIFO；
- SPT/LPT；
- Longest-delay；
- Longest-tail；
- LRPT；
- 固定 shortlist Rollout；
- 固定宽度 Beam；
- 需要多次暂停/恢复才能达到最优的样例。

先用 compact Exact 自动核验，再挑少量代表实例固化到仓库。每个反例必须说明适用模型和 gap，不能只靠文件名。

#### P3.3 补 structured 与 real/projection

建议的 structured 维度：链数、通信/计算比、长短链不均衡、同步释放波次、相同链对称性、近 channel-bound/compute-bound 两端。

real/projection 应明确说明从 LLM training DAG 投影成 independent chains 时删除或编码了哪些依赖。若原 DAG 含 join/cross-chain dependency，就不能在没有说明的情况下放入 Stage 1，应留给 complex-chain 阶段。

#### P3.4 多 job 映射

单独记录何时多个 job 可以被表示为互不依赖的 parallel chains，以及优化目标仍为全局 makespan 的限制。JCT、weighted completion time、slowdown 和 fairness 不应混入一阶段 makespan 结论。

### P4：保持 experiments 为薄接口，建立 Stage 1 独立报告

`experiments/` 不增加算法实现。建议只做以下接口性调整：

- parallel-chain case 通过 `single_channel.parallel_chain.preemptive` 稳定入口调用；
- 提供 Stage 1 专用选择器/配置，而不是只给多个 family 的总表；
- 输出 benchmark path/hash、category、seed、算法参数和 commit/版本信息；
- Exact timeout、state-limit、fallback 分开记录；
- 按 random/adversarial/structured/real 分组报告；
- 增加 runtime、optimal rate、mean/max gap、抢占次数、forced-idle 时间、channel 利用率；
- 保存逐例结果，汇总表由逐例结果派生。

不得在 runner 中复制 simulator 循环、tail 计算、合法动作判断或 Exact 搜索。

### P5：补齐当前模型下的理论材料

理论工作应与实现修正并行，但每个结论必须独立成可审查稿：

1. 精确定义 Stage 1 模型、事件语义、目标和符号；
2. 审查/重写 NP-hardness reduction，确保可抢占、无 WAIT、交替链条件都满足；
3. 正式证明或否定 `T_H <= P+Q <= 2OPT`，明确 `H` 是哪些 work-conserving schedule；
4. 证明 `max(P,Q,L)` 各项 lower bound 的适用前提；
5. 给出受限情形的最优规则或反例；
6. 用 Exact 搜索小图寻找证明漏洞和最小反例，但不把穷举实验当作证明。

如果某个上界只适用于独立交替链，应在文档和代码实验标题中写明，不能推广到 complex DAG。

### P6：在语义稳定后继续 heuristic/search 探索

等 P0–P3 稳定后再比较新算法，否则会继续积累不可解释的表格。建议路线：

- 以 compact Exact 作为 teacher，收集决策分歧而非只收最终 gap；
- 分析 Longest-tail 的两个现有反例及其参数化扩展；
- 自动搜索 FIFO/SPT/LPT/Longest-delay/Longest-tail/LRPT 的最小反例；
- 评估 Rollout shortlist 大小、completion policy 和 horizon 的独立贡献；
- 对 Beam 报告 width–quality–runtime 曲线；
- Monte Carlo 保留为历史对照，只有在定义和可复现性稳定后才重新进入主表。

## 3. 建议的提交拆分

为避免一次性改动过大，建议按以下边界提交：

1. `stage1 contract`：中立 chain model、严格 validator、合法性测试；
2. `stage1 policies`：FIFO/tail/delay 定义修正、Rollout shortlist、policy 测试；
3. `stage1 compact exact`：基础实现与 generic/tick Oracle 交叉验证；
4. `stage1 exact pruning`：lower bound、去重、性能测试；
5. `stage1 benchmarks`：新攻击族、structured/real projection、reference results；
6. `stage1 reporting`：薄 runner 路由和完整指标；
7. `stage1 theory`：证明、反例和适用边界文档。

每个提交尽量只改变一个可验证结论。benchmark 或语义变化后同步更新 hash/reference result，但保留旧结果文档，不覆盖历史材料。

## 4. 完成定义

建议只有同时满足以下条件，才将 Stage 1 标为完成：

- 所有公开输入都满足明确的独立交替链契约；
- FIFO、Longest-delay、Longest-tail、LRPT 和 Rollout 名称与代码一致；
- compact Exact 与独立 tick Oracle、通用 Exact 在固定小图集上完全一致；
- Exact 的 timeout/state-limit 不会被报告为 optimal；
- 理论结论有当前模型下的正式证明或被明确降级为 conjecture；
- random、adversarial、structured、real/projection 分组都有可解释的代表数据；
- 新 reference result 带正确 hash，旧结果保留为历史版本；
- Stage 1 独立实验报告包含 runtime、gap、最优率、抢占、forced idle 和利用率；
- `experiments/` 仍只负责调用和汇总；
- 所有 schedule 均通过公共 simulator 产生并由独立 trace validator 回放。