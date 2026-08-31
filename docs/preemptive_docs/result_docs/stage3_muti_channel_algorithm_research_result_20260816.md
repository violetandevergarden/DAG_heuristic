# Stage 3 固定多资源算法研究结果

日期：2026-08-16

## 1. 研究问题与口径

本轮研究回答三个问题：

1. Stage 2 的 residual Longest-tail 作为单任务 priority，在 greedy maximal-set packing 下是否仍是稳定 baseline；
2. 逐资源 downstream demand 和 shared-downstream 去重的直接 set score 能否稳定改善 LT；
3. 带 LT safeguard 与硬预算的 compatible-set depth-2 Rollout，是否能修复部分 LT 失败而不制造本轮 observed regression。

实现与消融按两个正交轴组织：第一轴只给 eligible communication 或完整 maximal set 打分；第二轴把 task scores greedy-fill 成 maximal set，或从 whole-set scores 中选一个集合。LT/resource-downstream 属于 task-score 分支，union-downstream 属于 set-score 分支，greedy-fill/best-scored-set/Set-Rollout 属于集合构造或搜索分支。LT safeguard 不是新分数，而是 Rollout 强制保留 `LT × greedy-fill` 候选并在预算耗尽时回退到它。

这次拆分只建立了新的组合接口，没有填满全部算法矩阵。当前 `score_sets()` 只有 union-downstream；`best-scored-set` 依赖完整 maximal-set 枚举；没有实现 §2.3.3 第 2 类加权独立集/有预算冲突图选择。Set-Rollout 搜索的是跨 task-event 的 set-action 序列，不等同于一个 bounded conflict-graph packing constructor。因此本报告不把接口拆分、union direct ranking 或 Set-Rollout 解释为 §3.1.6 的集合互补方法已经完整覆盖。

大图不使用 lower bound 给 heuristic 排名。主指标是 candidate 相对 LT 的 primal 改善/持平/退化；`[max(L,max_r D_r), best feasible]` 只表示未知区间。所有 optimal rate 只以 `Exact.status == optimal` 为分母。

完整 raw rows、逐资源 busy/utilization、set size、forced idle、Exact 分支和预算统计见 `stage3_muti_channel_experiment_20260816.json`。

## 2. 实验集合

正式 runner 共评估 36 图：

| 分层 | 数量 | 来源与定位 |
|---|---:|---|
| adversarial | 5 | 新增固定 Stage 3 资源冲突、集合互补、join/shared-downstream/depth probe |
| random | 10 | 已提交固定 seed 多资源一般 DAG |
| structured | 3 | 透明手工 topology + 固定 BFS route 的 synthetic snapshot，不是 measured runtime trace |
| compatibility | 12 | 4 个旧多资源 semantic regression + 8 个 Stage 2 单资源退化图 |
| large-primal | 6 | 运行时参数化 26--33 节点一般 DAG，4--6 个资源、混合 resource-set width 与 hotspot |

前四层 30 图全部得到 `status=optimal`。large-primal 中 4 图在 0.25 秒/5,000 state 预算内完成 Exact；32 和 33 节点的两图因 `time_limit` 返回 feasible，未进入 optimal 分母。

## 3. 小图 Exact 结果

### 3.1 Longest-tail greedy-fill baseline

| 分层 | observed optimal | mean ratio | observed max |
|---|---:|---:|---:|
| adversarial | 5/5 | 1.000000 | 1.000000 |
| random | 8/10 | 1.009259 | 1.055556 |
| structured | 3/3 | 1.000000 | 1.000000 |
| compatibility | 10/12 | 1.016270 | 1.100000 |

LT 在正式多资源 random 集的两个失败图仍是旧的：

- `pm_muti_random_003`：LT 19，OPT 18；
- `pm_muti_random_008`：LT 28，OPT 27。

新 5 个 adversarial 上 LT 全部最优。这只能说明当前手工攻击集尚未击中 LT，不表示 LT 在一般 fixed-resource DAG 上鲁棒，也不构成近似保证。攻击集的主要价值是分离 atomic acquire、maximal-not-maximum、join hotspots 和 shared downstream 机制。

### 3.2 资源向量 downstream demand

| 分层 | observed optimal | mean ratio | observed max | 相对 LT better/equal/worse |
|---|---:|---:|---:|---:|
| adversarial | 2/5 | 1.124848 | 1.333333 | 0/2/3 |
| random | 3/10 | 1.069254 | 1.200000 | 0/3/7 |
| structured | 3/3 | 1.000000 | 1.000000 | 0/3/0 |
| compatibility | 9/12 | 1.051488 | 1.375000 | 1/9/2 |

这个候选在本轮应被判为**负面消融**。逐资源 demand 向量包含了 Stage 2 scalar demand 没有的热点信息，但“优先最大 downstream hotspot/total demand”会把未来资源需求误当成当前应优先服务的因果价值，且可能牺牲更直接的 compute release 或 join last-blocker。

observed worst 包括：

- `pm_stage3_maximal_not_maximum`：9 → 12，退化 33.33%；
- compatibility `pm_nonmaximal_start`：8 → 11，退化 37.50%；
- random worst regression：20%。

因此 `resource_downstream_pack` 只保留为 research candidate/反例来源，不进入稳定部署候选。

### 3.3 共享下游去重的整集合分数

| 分层 | observed optimal | mean ratio | observed max | 相对 LT better/equal/worse |
|---|---:|---:|---:|---:|
| adversarial | 3/5 | 1.088889 | 1.333333 | 0/3/2 |
| random | 8/10 | 1.014815 | 1.111111 | 0/9/1 |
| structured | 3/3 | 1.000000 | 1.000000 | 0/3/0 |
| compatibility | 10/12 | 1.017593 | 1.111111 | 1/10/1 |

`union_downstream_set` 正确避免了把同一个 shared downstream node 对集合内多个通信重复求和，但“下游并集工作量更大”本身仍不是端到端 makespan 的可靠 set value。它在 `pm_stage3_atomic_acquire` 上从 9 退化到 10，在 `pm_stage3_maximal_not_maximum` 上从 9 退化到 12。

结论是：shared-downstream 去重是必要的数据处理纪律，但不是充分的 set policy。后续若继续研究，应把 union 特征用于有 baseline safeguard 的局部比较或 learned/teacher ranking，而不是直接作为默认排序。

### 3.4 Budgeted Set-Rollout

| 分层 | observed optimal | mean ratio | observed max | 相对 LT better/equal/worse |
|---|---:|---:|---:|---:|
| adversarial | 5/5 | 1.000000 | 1.000000 | 0/5/0 |
| random | 9/10 | 1.005556 | 1.055556 | 1/9/0 |
| structured | 3/3 | 1.000000 | 1.000000 | 0/3/0 |
| compatibility | 12/12 | 1.000000 | 1.000000 | 2/10/0 |

Rollout 本轮修复了 3 图：

- `pm_muti_random_008`：28 → 27；
- `single_resource::pm_stage2_join_starvation`：11 → 10；
- `single_resource::pm_stage2_rollout_depth`：23 → 21。

它没有修复 `pm_muti_random_003`（仍为 19，OPT 18）。这说明 top-2 set shortlist 仍会遗漏有价值动作，或者 depth-2 completion 对该图的区分不足。

本轮所有正式图 `fallback_count=0`，没有 observed regression。这个“无退化”来自 LT baseline set 强制进入候选和当前 completion 评价，不是理论支配证明。极小预算回退已由测试验证，但在更大、更密的 compatible-set frontier 上仍需单独审计 fallback 频率。

## 4. Large-primal 结果

6 个运行时图为 26--33 节点。LT 与 Rollout 在全部 6 图持平；资源 downstream 在 4 图退化，union set 在 2 图退化。

| 算法 | better/equal/worse vs LT | mean primal improvement | worst regression | mean runtime |
|---|---:|---:|---:|---:|
| LT baseline | 0/6/0 | 0 | 0 | 约 6.1 ms |
| resource downstream | 0/2/4 | -5.82% | -13.51% | 约 7.3 ms |
| union downstream set | 0/4/2 | -1.71% | -7.69% | 约 9.3 ms |
| Rollout top-2 depth-2 | 0/6/0 | 0 | 0 | 约 71 ms |

Rollout 在这组图上约为 LT 的 12 倍 runtime，却没有 primal 改善。因此当前证据不支持把它作为默认在线策略；更合适的定位是**有预算、可回退的研究候选或离线 teacher**。

large-primal 的 `[LB,best feasible]` 平均相对区间宽度为 14.64%，最大 23.08%。这只说明基础 bound 较松、仍有未知空间，不说明 LT 或 Rollout 的真实 gap 有这么大。两个 Exact timeout 图分别为：

- `layered_general_103`：LB 33，best feasible 39；
- `layered_general_104`：LB 31，best feasible 37。

## 5. 结构解释

本轮能支持的结构性观察是：

1. **资源负载不是 urgency。** 下游热点 demand 较大，既可能表示应该尽快释放，也可能表示该分支未来会长期竞争；只取最大 load 会混淆二者。
2. **去重是正确性纪律，不是目标函数。** shared downstream 必须只计一次，但 union work 大小仍忽略多个分支到 join 的到达差、当前 compute overlap 和 last-blocker 身份。
3. **集合互补需要看后续事件。** `maximal_not_maximum` 表明大小 1 与大小 2 都可以合法；集合 cardinality、当前利用率或资源覆盖都不能单独决定 makespan。
4. **LT 失败仍与同步和多次决策有关。** Rollout 修复 `random_008`、Stage 2 join starvation 和 depth case，但没有修复 `random_003`。这支持继续从 join/barrier、future release 和 shortlist omission 研究，而不是继续叠加静态 load bonus。
5. **structured 三图没有区分算法。** 它们主要验证固定路由/完整资源集和逐资源 trace，不足以给出真实 LLM topology 的算法排序。

上述都是 observed pattern，不是因果定理。

## 6. 资源与执行指标

raw result 对每个算法/实例记录：

- 逐资源 busy time 与 utilization；
- hotspot utilization、未使用资源数；
- mean/max compatible-set size；
- forced-idle time/count；
- preemptions 与 decision count；
- Rollout expanded nodes、cache hits、fallback；
- Exact states、transitions、prunes、compatible sets、branch 和 set-enumeration time。

这些指标用于解释 schedule，不被用作替代 makespan 的优化目标。高平均利用率可能掩盖热点与资源碎片，不能据此宣称算法更好。

## 7. Stage 3 结论与下一阶段可迁移内容

可以迁移到 LLM training 结构特化阶段：

- 公共 fixed-resource-set simulator、maximal compatible-set action 和独立 trace；
- normalized Exact/audit Exact/独立 tick 三方核验纪律；
- `max(L,max_r D_r)` 作为小图 Exact 与知识区间的基础安全 bound；
- LT greedy-fill 作为稳定、低开销 baseline；
- Rollout 的 baseline inclusion、hard budget、memo 和 deterministic fallback 框架；
- resource vector、shared-downstream union、join/barrier 与 future release 作为特征接口和风险标签。

Stage 3 仍欠缺、不能随迁移自动关闭的项目：

- 在现有函数组合 slot 中实现并消融一个有硬预算的 conflict-graph packing，例如 weighted independent-set 近似或 `remove 1 -> add 2+` 局部交换；
- 在相同 task/set score 和相同预算下，与 greedy-fill、完整 set ranking、Set-Rollout 分开比较，确认收益来自 packing 而非额外枚举或前瞻预算。

不能直接迁移为 Stage 4 结论：

- resource downstream 或 union set 是稳定优于 LT 的算法；
- 当前 Rollout 值得默认在线部署；
- structured route snapshot 代表真实 collective、拥塞或协议行为；
- 单 channel `P`、2-approximation、Stage 2 optimal rate；
- 当前 fixed resource set 结果适用于动态路由或迁移。

因此本轮最稳妥的算法结论是：**LT 保留为部署基线；带 LT safeguard 的 Set-Rollout 保留为有预算研究候选；resource downstream 与直接 union set 降级为负面消融和特征来源。** Stage 4 应利用 micro-batch、PP/TP/DP/EP、collective phase 和重复 barrier 的真实结构来缩小候选空间，而不是继续在一般 DAG 上增加无约束静态 bonus。
