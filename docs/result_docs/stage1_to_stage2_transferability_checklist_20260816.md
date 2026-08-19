# Stage 1 → Stage 2 可迁移性清单

日期：2026-08-16

## 1. 使用方式

本文回答 Stage 1 `single_channel/parallel_chain/preemptive` 的哪些成果可以进入 Stage 2 `single_channel/complex_chain/preemptive`。Stage 2 增加 fork、join、多前驱释放、同步屏障和跨路径依赖，但仍保持单 channel、communication 可在 task event 暂停/恢复、compute 自动且不可抢占、零抢占开销、无主动 WAIT 和 makespan 目标。

清单分为三类：

- **直接复用**：结构变化不影响正确性，可作为 Stage 2 起点；
- **复用框架但必须重做证明或实现**：研究方法可迁移，Stage 1 的具体状态或结论不可照搬；
- **禁止外推**：依赖独立严格链，进入一般 DAG 后不成立。

`stage2_complex_chain.md` 当前仍是提纲，本文只定义迁移边界，不替代 Stage 2 的详细研究计划和审查文档。

## 2. 可直接复用

| 项目 | 可迁移内容 | Stage 2 使用要求 | 状态 |
|---|---|---|---|
| 公共执行语义 | `PreemptiveDAGModel` 的事件原子化、compute 自动闭包、communication remaining、forced idle | complex-chain 算法只选择合法通信，不自行推进时间 | 可直接复用 |
| Trace 验证 | 工作量守恒、依赖、compute 连续性、channel 排他、最终完成 | 所有 Exact/heuristic/search 输出必须再次独立回放 | 可直接复用 |
| 无主动 WAIT | eligible communication 非空时必须运行一个通信 | fork/join 不改变单 channel 下的 work-conserving 要求 | 可直接复用 |
| 强 NP-hardness 下界 | Stage 1 是 Stage 2 的受限子类 | Stage 2 在相同事件语义和目标下至少 strong NP-hard | 可直接继承 |
| 实验纪律 | random/adversarial/real 分层、timeout 不记 optimal、逐例 hash、raw→summary | 新结果不得混入 Stage 1 benchmark 或旧 hash | 可直接复用 |
| 指标 | makespan、ratio、runtime、preemption、forced idle、utilization | Exact 未完成时只对安全 lower bound 报告 gap | 可直接复用 |
| 反例驱动循环 | 搜索、缩小、解释、固化、全套回归 | 反例必须含 fork/join 或一般 DAG 机制，避免重复研究纯链 | 可直接复用 |
| priority 定义纪律 | 明确是否包含当前通信 remaining，稳定 ID tie-break | Stage 2 中继续区分 longest-delay、longest-tail、LRPT | 可直接复用 |

## 3. 可迁移框架，但必须重新实现或证明

### 3.1 Residual score

- 可复用“每个决策状态只计算一次 residual 信息，再供所有候选查表”的缓存方式。
- 不能复用“候选所在唯一链的后缀”定义。一般 DAG 中一个 communication 可能通向多条分支，也可能受 join 的其他前驱限制。
- Stage 2 需要分别定义并消融：最长 residual path、join-aware release、同步屏障 slack、候选完成后真正新增的 ready/critical 结构。
- 分数必须从当前 remaining state 计算，不能把初始静态 critical path 当作 residual 值。

### 3.2 Exact

- 可复用“所有分支调用同一个公共 simulator transition”“cost DP 与实际 task-ID trace 重建分离”“明确 timeout/state limit”的架构。
- 状态至少要保留每个 task 的 remaining/status、正在运行的 compute、eligible/suspended communication，以及所有影响未来依赖释放的信息。
- 任何 Stage 2 compact key 都必须重新给出 future-equivalence 证明，并与未压缩 event Exact/独立小图 Oracle 对拍。
- Stage 1 的 chain frontier key 不能作为一般 DAG Exact key。

### 3.3 Rollout 与 Beam

- top-k、depth、baseline completion、确定性 tie-break 和预算矩阵可以复用。
- shortlist 必须由 Stage 2 residual score 重新生成；Stage 1 的 longest-tail shortlist 不能默认有效。
- forced idle 仍不消耗通信选择深度。
- Beam 的时间支配只在“完整保留未来信息的同一 Stage 2 key”内成立；若 key 丢失 join 前驱状态，较早时刻也不能证明支配。
- Stage 1 的 rollout2/depth2/beam8 数字不能作为 Stage 2 性能基线，只能作为配置候选。

### 3.4 Lower bound 与剪枝

- 单 channel communication 总量 $P$ 和忽略资源竞争的最长因果路径 $L$ 仍是安全下界候选。
- Stage 1 的 $Q=\max$ 单链 compute 总量必须改为一般 DAG 上经过证明的 compute/precedence bound，不能按任意路径分解后直接套用。
- window/demand bound 若继续使用，必须检查多前驱 release 与多后继 downstream deadline 的构造是否仍为必要条件。
- 所有新增 bound 先独立验证安全性，再进入 branch-and-bound。

### 3.5 Benchmark 与真实投影

- schema、loader、reference sidecar 和 hash 规则可复用。
- Stage 2 adversarial 必须新增 fork unlock、join starvation、barrier release、多层分支和静态-tail 误导样例。
- Stage 1 的两个 pipeline projection 删除了 cross-chain dependency，只能作为候选参数来源；Stage 2 应保留并显式标注真实 fork/join/barrier。

## 4. 禁止直接外推

| Stage 1 成果 | 不能迁移的原因 | Stage 2 处理 |
|---|---|---|
| `parse_parallel_chain` 与每链唯一 frontier | fork/join 使已完成集合不再由每条链一个位置表达 | 使用一般 DAG 状态，不做静默链化 |
| `(frontier position, remaining)` future-equivalence | 多前驱、多后继和共享后继需要额外完成信息 | 重新定义 key 并证明 |
| 相同链 multiset 对称压缩 | 一般 DAG 中局部相同路径可能连接不同外部依赖 | 只按完整图自同构或经证明的模块对称合并 |
| 最后完成链导出的 $I\le Q$ 证明 | fork/join 下未完成任务不一定落在一条覆盖全部 forced idle 的独立链上 | 不宣称任意 Stage 2 work-conserving schedule 仍有同一 2-近似证明 |
| 单次 communication 的 delivery-tail 排序最优 | join 和共享后继破坏相邻交换的独立性 | 仅保留为 Stage 1 restricted theorem |
| compute 全零时的链式解释 | 结论即使可能仍成立，也需按一般 DAG ready 闭包重新证明 | 作为 Stage 2 小引理单独审查 |
| 多 job→独立链映射 | 删除 barrier/cross-job edge 会改变 ready time 和目标 | Stage 2 保留原依赖或明确它只是松弛投影 |
| Stage 1 heuristic 的 observed optimal rate | 27 个 Exact 完成样例不含一般 DAG 困难机制 | Stage 2 重新生成 ground truth 和正式报告 |

## 5. Stage 2 首轮实施顺序

- [ ] 冻结并测试一般 DAG family contract：允许 fork/join，拒绝 cycle、未知依赖和非法 communication work。
- [ ] 用最小 fork、最小 join、同时事件和 barrier 样例复核公共 simulator/trace；算法层不实现第二套闭包。
- [ ] 审查现有 complex-chain registry：修正 longest-delay alias 描述，决定 `monte_carlo64` 的历史状态。
- [ ] 建立未压缩、小图可信的 event Exact，并与独立枚举交叉验证。
- [ ] 逐字段审查 Exact key；在书面 future-equivalence 前不启用有损 compact key。
- [ ] 重新定义 longest-delay、longest-tail、LRPT，增加能区分三者的 fork/join 测试。
- [ ] 迁移 residual snapshot 缓存，加入“每状态一次、非 tail 策略零次”的调用计数测试。
- [ ] 实现 depth-1/depth-2 rollout 和至少两档 beam，但先使用 Stage 2 completion/score。
- [ ] 建立 random、adversarial、real 三层 benchmark，并为每个攻击样例记录机制。
- [ ] 生成新的 reference result；语义或 benchmark 变化后不复用 Stage 1 hash。
- [ ] 正式报告 Exact 状态规模、runtime、ratio、抢占、forced idle、utilization，并单列 timeout。
- [ ] 只有在证明成立后，才启用一般 DAG 状态压缩、对称压缩或近似界声明。

## 6. Stage 2 验收门槛

进入正式算法比较前至少满足：

1. fork/join 的 ready 语义、同刻事件原子性和 trace 回放通过最小样例；
2. Exact 与独立 Oracle 在固定小图完全一致；
3. Exact key 的每个删除字段都有 future-equivalence 说明；
4. 三种 residual priority 有独立定义和反例测试；
5. rollout/beam 不包含主动 WAIT，且只通过公共 simulator 转移；
6. reference sidecar 的 benchmark hash 全部匹配；
7. Stage 1 的 2-近似、链对称和 observed optimal 结论没有被误写为一般 DAG 结论。

满足以上条件后，Stage 1 的工程框架才算完成了向 Stage 2 的受控迁移；否则只能称为代码复用，不能称为研究结论迁移。
