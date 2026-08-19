# Stage 3 `muti_channel/preemptive` 修正与推进计划

日期：2026-08-16

## 1. 目标与边界

本计划针对 `docs/process_docs/stage3_muti_channel_review_20260816.md` 中识别的问题，目标是把旧的固定多资源原型推进为满足 `stage3_muti_channel.md` 验收门槛的 Stage 3 实现。

边界如下：

- 保留公开目录和 schema 名 `muti_channel`，不单独做拼写迁移；
- 不推进 `muti_channel/nonpreemptive`，只在兼容或隔离需要时触碰；
- 不引入动态路由、迁移、部分资源获取、比例带宽、切换开销或多 job 目标；
- 不重写整个项目，优先提升现有多资源状态机、trace 和 benchmark 生成器；
- `experiments/` 继续是薄入口，模拟、Exact、算法和统计均留在 `src/`；
- 先完成语义和 Oracle 可信链，再评价 heuristic；旧 14 图仅作为回归材料，不作为新算法定型依据。

## 2. 优先级总览

| 优先级 | 工作包 | 退出结果 |
|---|---|---|
| P0 | 公共固定资源执行语义与 forced-idle 边界 | 算法只返回合法 compatible set，forced idle 由 simulator 自动推进 |
| P0 | Trace 与最小语义回归 | 原子资源获取、暂停恢复、同刻闭包、maximal 合法性均有独立回放防线 |
| P0 | 未压缩 Exact、normalized key 证明和结果状态 | reference 只接受明确 `optimal` 的 Stage 3 Oracle |
| P1 | 安全 lower bound、set 枚举与 Exact 规模统计 | 小图 Exact 有可审计剪枝、分支和内存数据 |
| P1 | 稳定 baseline 与集合互补策略 | priority 和 packing 可以分开消融 |
| P1 | 有预算 Set-Rollout | baseline action 保留、预算耗尽确定回退、统计完整 |
| P1 | Stage 3 benchmark 重建 | random/adversarial/structured/compatibility 四层齐全 |
| P2 | small-Exact 与 large-primal 双层实验 | 分类结果、逐资源指标、知识区间与风险结构齐全 |
| P2 | 旧结果迁移说明 | 旧数值可追溯，失效解释不再被当成当前结论 |

## 3. P0：修正公共模拟器边界

### 3.1 最小改造路线

不重新设计所有状态类型。建议以当前 `PreemptiveMultiResourceModel` 为迁移源，完成以下边界调整：

1. 在 `src/core/execution/preemptive.py` 或相邻公共模块建立 fixed-resource-set 执行模型；
2. 将 `TaskState`、规范运行状态、set action、合法性验证、compute closure、事件推进和 trace 原始记录移入公共层；
3. 单通道适配为所有 communication 使用 `channel:0` 的特例，或至少让单/多资源调用同一事件推进器与闭包；
4. `src/muti_channel/preemptive/solver.py` 只保留：
   - LT/resource priority；
   - compatible-set 构造；
   - Rollout/Exact search；
   - 从公共结果到场景结果的薄封装；
5. `src/muti_channel/preemptive/trace.py` 依赖公共 trace 数据类，不再反向导入 `solver.MultiTrace`。

迁移过程中保持当前合法 schedule 的 makespan 和 trace 不变，先加 characterization tests，再移动代码。

### 3.2 forced idle 不再是动作

公共 simulator 应提供类似以下稳定接口：

- 若存在 eligible communication，返回 scheduler view 并要求 `RUN_SET`；
- 若不存在 eligible、但有 active compute/future event，内部自动推进并记录 `ForcedIdleInterval`；
- 若无 eligible 且无未来事件但未完成，抛出 `DeadlockError`；
- forced idle 不进入 scheduler actions，不增加 communication decision count，也不命名为 WAIT。

需要决定并固定统计口径：

- `event_count`：所有任务事件批次数；
- `decision_count`：真正请求通信集合的次数；
- `forced_idle_count/time`：依赖造成的自动空闲；
- `preemption_count`：一个未完成通信从上个运行集合退出，且之后可能恢复的次数。

### 3.3 公共不变量

每次 transition 前后断言：

- stable decision state 无 active communication resource ownership；
- running compute 从开始到完成连续；
- selected communication 全部 eligible；
- selected resources 两两不交且每个任务完整获取自身集合；
- selected set inclusion-maximal；
- 所有 active task 以同一 delta 推进；
- remaining 非负，completed remaining 为零；
- 同刻全部完成先处理，再执行零时长 compute closure；
- 未完成状态必有合法 set 或未来非通信事件。

## 4. P0：补齐语义与 Trace 回归

### 4.1 必须新增的手工最小图

每个图只验证一个机制，并给出手算时间线：

1. **disjoint parallel**：`a:{r0}`、`b:{r1}` 同时完成；
2. **shared conflict**：`a:{r0}`、`b:{r0}` 不能并行；
3. **atomic acquire**：`a:{r0,r1}` 与分别占 `r0/r1` 的通信形成两个不同 maximal sets；
4. **maximal not maximum**：同时存在大小 1 和大小 2 的 maximal sets，二者均合法；
5. **pause/release/resume**：多资源通信因 compute event 暂停，两个资源同时释放，恢复时同时重新获取；
6. **same-time batch**：两个 communication 和一个 compute 同刻完成，只产生一个后续 decision；
7. **forced idle**：无 eligible 时自动跳到 compute completion，动作序列中没有空 set；
8. **future join coupling**：当前冲突图分量分离、未来在 join/barrier 汇合；
9. **single-resource degeneration**：同一 DAG 全部映射到共享资源，与 Stage 2 trace/makespan 一致。

### 4.2 错误 trace mutation

独立 validator 必须分别拒绝：

- 多资源通信只记录部分 resource intervals；
- 同一资源两个通信重叠；
- 暂停期间仍减少 service；
- 恢复时更换资源集合；
- communication 在前驱完成前开始；
- compute 被拆成两段；
- selected set compatible 但不 maximal；
- 同刻事件被拆成两个决策；
- forced idle 期间其实存在可运行通信；
- trace makespan 与最后完成事件不一致。

### 4.3 独立 tick/set Oracle 扩展

保留 `tests/oracles/preemptive/tiny_oracle.py` 的独立实现，但扩展为固定 seed 的 100--300 个小图，并覆盖：

- 2--4 个资源；
- `{r0}`、`{r1}`、`{r0,r1}`、`{r1,r2}` 等非层次需求；
- 单资源与多资源通信混合；
- 冲突图从空、稀疏到高密；
- fork、join、零时长 compute 和同刻完成。

随机测试失败时必须缩小并保存成手工 regression，而不是只更换 seed。

## 5. P0：建立可信 Exact 合同

### 5.1 先实现未压缩 audit Exact

新增只用于极小图审计的 uncompressed set-event Exact，key 至少包含：

- absolute time；
- 每任务完整 runtime 字段；
- running computes 及其 remaining/completion 信息；
- 当前 active communication set；
- resource owner 映射；
- 已完成/未到达等未来释放所需字段。

即使稳定决策边界使 active set 和 occupancy 恒为空，也先显式保留，用它与 normalized Exact、独立 tick Oracle 三方对拍。audit Exact 不追求速度，不进入大规模正式 runner。

### 5.2 normalized key 逐字段证明

书面证明至少回答：

1. 为什么绝对时间只产生平移，不改变 future action/cost；
2. 为什么 task `(status,remaining)` 唯一决定 predecessor completion 条件；
3. 为什么 running compute 和下一 compute event 可由状态恢复；
4. 为什么 stable decision boundary 上 active communications 与 resource occupancy 为空；
5. 为什么 resumed communication 的固定资源集来自不可变问题模型；
6. 为什么同 key 状态拥有相同 eligible set、maximal actions、transition delta 和 successor keys；
7. 将来加入 arrival、deadline、preemption cost 或 minimum quantum 后，哪些证明立即失效。

证明文档放在 `docs/process_docs/`，并由 normalized/uncompressed property tests 支撑。

### 5.3 Exact 结果类型

统一返回结构至少包含：

- `status`: `optimal | timeout | state_limit | feasible | infeasible/error`；
- `makespan` 与 incumbent actions；
- `lower_bound`；
- `runtime_ms`；
- `explored_states`、`generated_transitions`；
- `deduplicated_states`、`pruned_states`；
- `compatible_sets_generated`、每状态 mean/P95/max branch；
- `set_enumeration_ms`；
- `peak_memory_bytes` 或明确不可用；
- `termination_reason` 和实际 budget。

预算耗尽时可以返回 incumbent，但状态必须是 feasible，不允许进入 optimal 分母或 reference sidecar。

### 5.4 reference 生成纪律

修改 `benchmark_generate/reference.py` 的多资源分支：

- 必须检查 `result.status == "optimal"`；
- sidecar 保存 benchmark SHA256、Oracle 版本/名称、budget、runtime、states、lower bound 和 optimum；
- random/adversarial/structured 小图按明确白名单生成；
- benchmark 或语义变化后不沿用旧 sidecar；
- 旧 4 个 sidecar 迁移前保留，但标注 `legacy_optimal`，不能与新证书混用。

## 6. P1：安全 lower bound 与 Exact 扩展

### 6.1 第一版安全下界

实现并独立测试：

$$
LB_0(s)=\max\left(L(s),\max_{r\in\mathcal R}D_r(s)\right),
$$

其中：

- `L(s)` 使用当前 remaining 的 precedence longest path；
- `D_r(s)` 对所有未完成且需要资源 `r` 的 communication 计入完整 remaining；
- 多资源 communication 在每个需要资源上分别计入，但最终取资源最大值，不跨资源求和。

对所有 tiny state 验证 `LB_0 <= audit_exact_residual_optimum`。证明和测试完成前不得用于剪枝。

### 6.2 B&B 与 set 枚举

在纯 memo Exact 基础上小步加入：

1. 以 LT greedy-fill 生成初始 incumbent；
2. 按 rollout/lower-bound 希望值排序 branch；
3. 用 `elapsed + LB >= incumbent` 做安全剪枝；
4. 直接回溯生成 maximal compatible sets，不先生成全部子集；
5. 缓存同一 eligible/resource footprint 的 set enumeration；
6. 记录而不是隐藏 set 枚举成本；
7. 仅在有证明时研究冲突图连通分量分解和 dominance。

每项优化都必须与 audit Exact 对拍，不能以更快但结果相同于旧 14 图作为正确性证明。

### 6.3 规模扫描

运行时生成，不大量提交 JSON。正交改变：

- resource count；
- eligible peak；
- conflict density；
- resource-set width；
- maximal-set count；
- DAG depth/width 和 join/barrier 层级。

报告 states、transitions、branch distribution、set enumeration time、memory、runtime 和 timeout frontier。

## 7. P1：重建 heuristic 研究矩阵

### 7.1 把 priority 与 packing 分开

所有单任务 priority 使用同一 greedy-fill 构造，至少包括：

- FIFO eligibility time，而非静态 task ID；
- SPT/LPT remaining；
- residual tail（明确 inclusive/exclusive）；
- Stage 2 downstream demand；
- resource-aware downstream demand。

这样先回答“同一个 packing 下哪个 task score 更好”。随后固定 LT score，比较不同 set construction，避免两个维度同时变化。

### 7.2 第一批资源感知特征

一次只引入一种：

1. 候选下游逐资源 residual demand 向量；
2. 下游最大热点 load；
3. 候选自身 footprint 与下游热点重合；
4. 完成候选后释放的不同 join 分支资源；
5. shared downstream 联合可达子图去重；
6. 预计新增 ready compute/communication；
7. 资源碎片和未使用资源数量。

每个特征必须有配对反例：一个显示收益，一个显示误用会退化。只在 mean 改善但 worst 变差时，定位为候选信息而非默认 priority。

### 7.3 Compatible-set 构造阶梯

依次比较：

- priority greedy-fill；
- greedy set 的 `remove 1 -> add 2+` 局部交换；
- 带权冲突图独立集的有预算近似；
- 直接 set score，使用下游子图并集而非任务分数求和；
- exact maximal-set ranking（仅小 frontier teacher）。

所有方法最终必须补全为 inclusion-maximal；补全由公共合法性层验证，不能静默修正非法返回。

## 8. P1：重新实现有预算 Set-Rollout

### 8.1 正确候选合同

第一版必须保证：

- LT greedy baseline set 总是在候选中；
- top-k 的 set score 与 completion baseline 定义明确；
- shared downstream 不简单重复求和；
- forced idle 不消耗 rollout depth；
- depth 表示经历的真实 compatible-set decisions；
- 相同 residual state 使用已证明的 Stage 3 key 缓存。

### 8.2 预算与 fallback

同时支持：

- expanded-node budget；
- compatible-set generation budget；
- wall-clock budget；
- depth、top-k；
- deterministic tie-break。

预算耗尽时返回当前 best feasible；若没有完整 candidate，则返回 baseline set。结果记录 `completed_search`、`fallback_reason`、expanded nodes、completion calls 和 cache hits。

### 8.3 消融矩阵

至少比较：

- depth 1/2/3；
- top-k 2/4/8；
- single-task shortlist 后组合 vs 直接 set shortlist；
- 相同 node budget 下的 greedy、local exchange、Rollout；
- small Exact ratio 与 large candidate→baseline primal 改善。

Beam 如保留，只作为 experimental teacher，使用同一 key/budget 统计，不进入 Stage 3 退出条件。

## 9. P1：重建 Stage 3 benchmark

### 9.1 重新分类旧 14 图

- `pm_disjoint_routes`、`pm_shared_route`：转为基础语义/compatibility regression；
- `pm_nonmaximal_start`：保留为历史不可抢占语义回归，metadata 明确“当前可抢占模型禁止该动作”；
- `pm_active_reservation`：保留为暂停释放资源的对照，重写当前 semantic role，不再声称 active route 持续保留；
- 10 个 random：保留 seed regression，但增加结构统计，不作为完整 random 设计空间。

不要求移动文件即可先通过 metadata 和报告分组隔离；若后续移动，必须同步 index/hash/reference migration manifest。

### 9.2 新 adversarial 最小族

至少新增并手算：

1. 高 tail 多资源任务阻塞两个次高 tail 互补任务；
2. greedy 首选导致差的 maximal set；
3. maximal cardinality 与最优 makespan 不一致；
4. 多资源原子获取错误会产生虚假 schedule；
5. join 两分支落在不同热点资源；
6. barrier urgency 与资源 load 冲突；
7. set tail 求和重复计算 shared downstream；
8. resource downstream demand 改善 mean 但制造 worst regression；
9. 当前利用率更高却延迟关键同步；
10. top-k omission；
11. depth-1 看不到、depth-2 可看到的集合投资；
12. 当前冲突图可分、未来 join 耦合；
13. normalized key active/occupancy 碰撞探针。

metadata 至少包括 `attack_target`、`mechanism`、`semantic_scope`、`parameters`、`expected_gap_role`。

### 9.3 参数化 random

生成器显式接收：

- seed、task count、DAG depth/width；
- fork/join/barrier density；
- resource count；
- 单/多资源 communication 比例；
- resource-set size 分布；
- target conflict density/hotspot skew；
- tail-hotspot correlation；
- communication/compute ratio。

仓库固定约 10 个代表 seed；大规模扫描运行时生成，并在 result 中保存全部参数。

### 9.4 real/structured 投影

不要直接解除当前 preemptive real 过滤。先审计 `manual_route_cases()` 或 SimAI 转换：

- topology 来源和 hash；
- route 如何冻结成 resource set；
- NIC、link、switch/bottleneck 抽象；
- collective 的可抢占逻辑单元；
- 是否为等价投影、松弛、上界或 synthetic motif；
- 节点、边、资源的删除/合并记录。

无法满足真实来源时，分类为 `structured` 或 synthetic topology motif，不标为 real。

## 10. P2：Stage 3 专属薄实验入口

新增 `experiments/preemptive/stage3_muti_channel.py`，只负责：

- 选择 benchmark/运行时生成配置；
- 调用 registry 或 `src` 稳定接口；
- 保存 raw rows；
- 调用 `src` 统计结果做分层 summary。

在新增 runner 前先统一公开算法面：`src/muti_channel/preemptive/interface.py` 与 `src/registry.py` 使用同一算法配置表；CLI 和实验均通过该稳定入口调用。solver 内部函数可以保留用于单元测试，但不再形成第三套实验 API。所有 Exact 调用必须显式提供 state/time budget。

每个 raw row 至少保存：

- benchmark ID/path/category/hash；
- task/resource/conflict 结构统计；
- algorithm 配置和预算；
- makespan、runtime、preemptions、forced idle；
- set size mean/P95/max；
- 逐资源 busy/utilization、热点 idle、碎片；
- Exact status/LB/states/transitions/branch/memory；
- 相对 OPT ratio，或相对 baseline primal delta；
- fallback/timeout 原因。

summary 必须分开 random、adversarial、real/structured、compatibility，并报告：

- mean/P50/P95/observed max ratio；
- optimal rate，仅对 status=optimal 的分母；
- candidate→baseline 改善/持平/退化率和 worst regression；
- runtime 与预算完成率；
- `[LB,best feasible]` 只作为知识区间，不称为 heuristic gap。

## 11. P2：旧文档与结果迁移

完成新闭环后新增一份迁移说明，不覆盖历史文档：

- 旧 14 图原始 ratio 数值已复现；
- 四个旧 adversarial 的当前角色已改变；
- 旧 sidecar 属于 legacy certificate；
- 新 benchmark/hash/reference 从哪一版本开始生效；
- old `preemptive进度.md` 中 optional-idle、nonmaximal start、active reservation 和“闭环”措辞只代表历史阶段；
- 新报告以 Stage 3 分类结果为正式结论。

## 12. 建议提交拆分

为降低审查风险，建议按以下独立提交推进：

1. `test(stage3): freeze fixed-resource event semantics`；
2. `refactor(core): promote multi-resource transition to shared execution`；
3. `fix(core): make forced idle simulator-owned`；
4. `test(stage3): expand trace mutations and tick oracle coverage`；
5. `feat(stage3-exact): add uncompressed audit oracle and status contract`；
6. `docs(stage3): prove normalized key and base lower bound`；
7. `feat(stage3-exact): add safe bounds and maximal-set enumeration stats`；
8. `feat(stage3): separate task priority from compatible-set construction`；
9. `feat(stage3): add budgeted set rollout with baseline fallback`；
10. `data(stage3): rebuild adversarial/random/structured suites`；
11. `data(stage3): regenerate certified references`；
12. `exp(stage3): add thin classified runner and result report`；
13. `docs(stage3): migrate historical conclusions`。

每个提交都应保持完整测试通过；涉及公共模型、转换层或 Oracle 时运行全套测试。

## 13. 完成定义

只有同时满足以下条件，才能把 Stage 3 标为完成：

1. fixed-resource simulator 位于公共执行层，算法不维护第二套 transition；
2. forced idle 不再是 scheduler action；
3. 最小语义图和错误 trace mutation 全部通过；
4. normalized、uncompressed 和 independent tick/set Oracle 在扩展小图集一致；
5. normalized key 与 `LB_0` 有书面证明和 property tests；
6. Exact 明确报告 optimal/timeout/state-limit，reference 只接受 optimal；
7. 至少一条稳定 LT set baseline 和一条真正处理集合互补/资源下游信息的候选完成消融；
8. Set-Rollout 有硬预算、baseline safeguard、确定性 fallback 和统计；
9. random/adversarial/real-or-structured/compatibility 四层齐全且分别报告；
10. 小图报告 Exact ratio，中大图报告 candidate→baseline primal 与知识区间；
11. 逐资源利用率、热点 idle、碎片、set size、抢占和 forced idle 指标齐全；
12. 旧 14 图数值、失效解释和新正式结论之间有明确迁移记录；
13. 没有把单通道 `P`、2-bound、单任务 observed rate 或旧 Rollout 复杂度外推到多资源。

在这些条件满足前，可以继续称当前代码为“Stage 3 固定多资源原型”，不应称为“Stage 3 已完成实现”。
