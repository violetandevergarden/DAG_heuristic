# Stage 3 → Stage 4 可迁移性清单

日期：2026-08-16

## 1. 使用方式

本文回答 Stage 3 `muti_channel/preemptive` 的哪些成果可以进入 Stage 4 真实 LLM training DAG 结构特化研究。Stage 4 以 `docs/plan_docs/stage4_LLM_search.md` 为当前提纲，重点研究：

- 选择性 Rollout：普通决策使用低开销 baseline，只在关键点前瞻；
- 利用 micro-batch、pipeline phase 和重复子图做压缩或摊销；
- 在单联合 DAG makespan 之外，单独研究 multi-job 目标与调度；
- 从真实或可追溯的 LLM workload/topology 中识别 PP、TP、DP、EP、collective、barrier 和重复结构。

清单分为三类：

- **直接复用**：在 Stage 4 继续采用相同固定资源抽象和单 DAG makespan 目标时，正确性不依赖 LLM 专用结构；
- **复用框架但必须重新实现或证明**：Stage 3 提供接口、实验纪律或候选特征，但 LLM 结构、重复压缩、多 job 或真实网络会改变适用条件；
- **禁止外推**：Stage 3 的有限样本、固定资源集合或单 DAG 结论不能直接写成 LLM training 结论。

目录名 `muti_channel` 是当前公开 benchmark 格式与 Python 包名，Stage 4 不在没有迁移方案时顺手改名。现有 `src/llm_structured/` 和历史实验只能作为审查材料，不是 Stage 4 目标语义的事实来源。

## 2. Stage 3 当前完成状态

Stage 3 已形成以下受控基础：

- 公共 fixed-resource-set event simulator；
- work-conserving maximal compatible-set 动作；
- communication 暂停/恢复与完整资源原子获取；
- simulator-owned forced idle；
- 独立逐资源 Trace 回放；
- normalized Exact、uncompressed audit Exact 与独立 tick/set Oracle 三方核验；
- `max(L,max_r D_r)` 基础安全下界；
- task scoring、set scoring 与 set construction 的函数级拆分；
- LT greedy-fill baseline；
- 有 node/set/time budget、memo、LT candidate inclusion 和确定性 fallback 的 Set-Rollout；
- random、adversarial、structured、compatibility 与 large-primal 分层实验。

Stage 3 仍有一个不能在迁移时自动关闭的算法缺口：

> `stage3_muti_channel.md` §2.3.3 第 2 类“加权独立集 / 有预算冲突图选择”尚未实现。当前只有 task-score greedy-fill、完整 maximal-set 枚举后的 direct set ranking 和跨事件 Set-Rollout；接口 slot 已建立不等于 §3.1.6 的集合互补方法已经覆盖。

该缺口可以在 Stage 4 前补齐，也可以作为 Stage 4 的一般 packing baseline 并行推进，但必须在报告中继续单列，不能由 LLM 结构特化结果反向掩盖。

## 3. 可直接复用

| 项目 | 可迁移内容 | Stage 4 使用要求 | 状态 |
|---|---|---|---|
| DAG 基础语义 | finish-to-start、同刻事件原子处理、compute ready 后自动开始且不可抢占 | LLM DAG 转换不得用 metadata 暗中改变 ready 或 compute 顺序 | 可直接复用 |
| communication remaining | task-event 暂停/恢复、零开销、无 minimum quantum | collective 被映射为 communication node 时必须说明这一粒度是否合理 | 条件直接复用 |
| 固定资源集合 | 启动/恢复时原子获得全部资源，暂停/完成时全部释放 | 只适用于路由已冻结且无迁移、无部分获取的抽象 | 条件直接复用 |
| work-conserving 动作 | scheduler 选择 non-empty maximal compatible set，simulator 验证合法性 | LLM 专用算法只能选择动作，不能维护第二套资源占用 | 可直接复用 |
| forced idle | 无合法 communication 时由 simulator 自动推进，不计 scheduler action/depth | job arrival 引入后必须扩展未来事件来源，不能复用当前“只有 compute”判定 | 单 DAG 可直接复用 |
| Trace | 工作量、依赖、compute 连续性、逐资源排他、完整资源获取、时间线覆盖 | Stage 4 新事件/目标需增加验证，不得削弱现有检查 | 框架直接复用 |
| Exact 纪律 | timeout/state limit 只返回 feasible；reference 只接受 `status=optimal` | LLM 压缩 Exact 仍须与未压缩小图和独立 Oracle 对拍 | 可直接复用 |
| Residual 纪律 | 分数从当前 status/remaining 计算；稳定 tie-break；不读答案 metadata | phase/micro-batch 标签可作为输入特征，但不得暗示 reference | 可直接复用 |
| 实验纪律 | random/adversarial/structured/compatibility 分层；raw 与 summary 分离 | 真实 LLM 结果必须再按 workload、parallelism、topology 和规模分层 | 可直接复用 |
| 大图口径 | candidate→baseline primal 改善/持平/退化；`[LB,best]` 只表示未知 | 不用宽松下界给 heuristic 排名，不把区间宽度称为算法 gap | 可直接复用 |
| Beam 定位 | experimental upper bound/offline comparison；非部署候选；不主张鲁棒性 | Stage 4 不把固定宽度 Beam 反例搜索作为退出条件 | 可直接复用 |

## 4. 可迁移框架，但必须重新实现或证明

### 4.1 LLM workload 到 DAG 的转换

Stage 3 simulator 可以消费转换后的 DAG，但不能决定如何把 LLM training workload 转成节点、依赖和资源。Stage 4 必须单独冻结转换合同：

- micro-batch、layer、pipeline stage、forward/backward/weight-gradient phase 如何映射为 compute；
- PP send/recv、TP collective、DP gradient synchronization、EP all-to-all 等如何映射为 communication；
- rank/collective 内部同步是保留、聚合还是松弛；
- pipeline schedule、activation/gradient dependency 和 optimizer barrier 如何保留；
- topology route 如何冻结为 NIC、link、switch port 或抽象 bottleneck resource set；
- 节点合并、删除、缩减和重复模板展开的完整记录；
- 转换结果是等价模型、上界、下界、松弛还是 synthetic motif。

没有上述记录时，只能称为 LLM-shaped synthetic DAG，不能称为真实 LLM 调度结论。

### 4.2 固定资源抽象

可以复用固定 resource set simulator，但必须重新验证真实 collective/网络是否满足：

- 一个 communication 在整个 resumable 区间需要同一资源集合；
- 全部资源必须同时获取；
- 暂停时全部释放，恢复时重新获取同一集合；
- duration 不随并发、拥塞、协议 phase 或 route 改变；
- 不存在动态选路、部分 rank 先行、chunk pipeline 或按比例共享带宽。

如果真实系统不满足，Stage 4 应新增输入适配或扩展模型，并重新审查 simulator、state key、Trace 和算法，不得把差异塞进 metadata。

### 4.3 Task score 与 set construction

Stage 3 已把两个轴拆成普通函数：

- `score_tasks()` / `score_sets()`：只负责打分；
- `greedy_fill_from_task_scores()` / `select_best_scored_set()`：把分数变成动作。

Stage 4 可以在不改 simulator 的前提下增加 LLM 特征：

- pipeline bubble/critical micro-batch；
- phase、stage 和方向；
- optimizer/iteration barrier slack；
- PP/TP/DP/EP downstream demand；
- collective family、资源 footprint 与热点重合；
- 重复模板中的相对位置；
- 当前 iteration 或 wave 的剩余副本数。

但 Stage 3 的负面结果必须保留：resource downstream 和 union-downstream direct ranking 都出现明显 worst regression。新特征必须分别在相同 constructor 下消融，不能同时改变 score、packing 和预算后把全部收益归因于 LLM 特征。

### 4.4 未完成的 conflict-graph packing slot

Stage 4 仍需实现至少一种真正位于“set construction”轴的方法，例如：

- task weights 下的有预算 weighted independent-set 近似；
- 从 LT greedy set 出发的 `remove 1 -> add 2+` 局部交换；
- 固定 expanded-node/set-count 的冲突图局部搜索；
- 利用 LLM 重复资源 footprint 的模板化 packing table。

验收时必须固定 task/set score 和预算，与以下方法分开比较：

- greedy-fill；
- 完整 maximal-set ranking（仅小 frontier teacher）；
- conflict-graph bounded packing；
- 跨事件 Set-Rollout。

Bron--Kerbosch 完整枚举不是 weighted independent-set heuristic；Set-Rollout 也不是静态 packing constructor。

### 4.5 选择性 Rollout

Stage 3 可复用的只有框架：compatible-set 分支、normalized memo、hard budget、baseline inclusion、deterministic fallback，以及 forced idle 不消耗 depth。Stage 4 必须重新研究 trigger：

- **score ambiguity**：top-1/top-2 task 或 set score 接近；
- **packing ambiguity**：多个 maximal sets 的分数或资源覆盖接近；
- **barrier proximity**：join/barrier slack 小或 last-blocker 身份不确定；
- **phase transition**：PP wave、backward/weight phase 或 optimizer boundary；
- **hotspot transition**：关键 collective 即将进入共享资源；
- **periodic/template trigger**：重复结构中只在代表位置 Rollout，其余复用策略。

必须报告 trigger precision/coverage、被触发决策比例、节省的 runtime、漏掉的改善和新增 regression。Stage 3 top-2 depth-2 在 large-primal 上约为 LT 的 12 倍且无改善，不能默认每个事件都调用。

### 4.6 重复结构压缩与摊销

Stage 3 normalized key 只证明当前一般 DAG 固定资源状态的 future-equivalence，不能直接证明两个 micro-batch、layer 或 iteration 副本可合并。Stage 4 若利用重复性，必须证明：

- 被合并副本的内部 DAG、duration、资源集合和外部依赖接口相同；
- phase、pipeline stage、剩余副本数和跨副本 barrier 不会区分未来；
- 对称交换不改变合法 compatible sets 和 makespan residual cost；
- 模板 policy/cache key 保留所有影响未来 release 与资源占用的信息；
- 压缩 Exact/搜索与未压缩小副本实例完全一致。

可以复用 Stage 3 audit 方法，但必须为 repetition/template key 重新写 future-equivalence 证明。

### 4.7 Exact 与 lower bound

可以复用 normalized/uncompressed/tick 三方核验、预算状态和 branch 统计。不能直接复用的内容包括：

- 新增 phase、iteration、arrival、job 或模板计数后，normalized key 必须加入相应信息或证明可恢复；
- `max(L,max_r D_r)` 在相同固定资源、单联合 DAG makespan 下仍是安全基础候选；引入 job arrival 或其他目标后必须重新定义；
- LLM barrier、pipeline cut、collective clique 或重复 demand 可形成更强 bound，但必须独立证明；
- state compression 的收益必须与 bound、branch ordering 和 symmetry 分开消融。

### 4.8 Multi-job

Stage 3 是单联合 DAG makespan。Stage 4 的 multi-job 不能通过简单给多个 job 加一个总 sink 就混用结论。需要显式 workload 层：

- job ID、arrival、weight 和独立 DAG；
- job 间只通过共享资源耦合，除非输入明确给跨 job 依赖；
- 目标分别研究 global makespan、mean/weighted JCT、slowdown 和 fairness；
- scheduler view、trace 和统计同时保留 global/per-job 信息；
- job arrival 是显式事件，forced idle 与 key 随之扩展；
- 每种目标重新建立 Exact 小图、baseline 和反例。

Stage 3 的 LT、Rollout 和 lower bound 只能作为 makespan baseline 组件，不能解释为 JCT/fairness 策略。

## 5. 禁止直接外推

| Stage 3 成果 | 不能迁移的原因 | Stage 4 处理 |
|---|---|---|
| LT 在 5/5 新 adversarial、8/10 random 上 observed optimal | 样本很小且没有完整 LLM phase/collective/repetition 机制 | 只作为稳定 baseline，重新按 LLM workload 分层 |
| Set-Rollout 本轮无 observed regression | 只是有限样本；LT safeguard 不是理论支配证明 | 报告触发率、fallback、改善与 worst regression |
| large-primal 上 Rollout 与 LT 6/6 持平 | synthetic general DAG 不代表 LLM 关键点分布 | 用它支持“需要选择性触发”，不支持“Rollout 无价值” |
| resource downstream / union set | Stage 3 已出现 20%--37.5% worst regression | 只作特征和负面消融，不作 Stage 4 默认分数 |
| 接口已拆成 score × constructor | 拆分只建立 slot，没有实现 weighted independent-set/bounded graph packing | 在 Stage 4 单列补齐，不能标为已覆盖 |
| Bron--Kerbosch maximal-set 枚举 | 完整枚举成本组合爆炸，也不是加权 packing heuristic | 仅用于小 frontier teacher/Exact；大图使用有预算 constructor |
| `max(L,max_r D_r)` | 只对当前固定资源、单 DAG makespan 安全 | 新资源语义、多 job 目标或 arrival 后重新证明 |
| normalized key 证明 | 不包含 job arrival、phase/template counters 或持久 allocation | 每次扩展 state 都重审 key |
| 3 个 structured route snapshot | 是透明 synthetic topology snapshot，不是 measured runtime trace | 只作转换/trace regression，不能证明真实网络收益 |
| 固定 resource set | 不表达动态路由、拥塞、chunk collective 和协议速率变化 | 明确抽象误差或扩展模型 |
| 平均资源利用率 | 可能掩盖热点、碎片和关键 barrier 延迟 | 继续报告逐资源和端到端 makespan/JCT |
| 单 DAG makespan 结论 | 与 multi-job JCT、slowdown、fairness 目标不同 | 分目标建立新实验和结论 |

## 6. Stage 4 Benchmark 与评价口径

### 6.1 数据分层

Stage 4 至少分开：

- **synthetic LLM motif**：PP wave、1F1B、zero-bubble、TP/DP/EP collective 与 optimizer barrier；
- **structured projection**：来自明确 workload 和 topology 的可追溯缩减/投影；
- **real-derived snapshot**：保留来源、版本、配置、route 和转换 hash；
- **adversarial**：攻击 trigger、template compression、packing、phase score 和 multi-job fairness；
- **compatibility**：Stage 3 一般 DAG、单资源退化和固定路由语义回归。

不能用大量重复 micro-batch 副本稀释少数 topology、barrier 或 fairness regression。

### 6.2 单 DAG 小图

- Exact status、runtime、states、compatible-set branch、set enumeration 和 memory；
- heuristic/search 相对 OPT 的 optimal rate、mean/P50/P95/observed max gap；
- 按 PP/TP/DP/EP、phase、barrier、resource footprint 和重复度分层；
- 抢占、forced idle、逐资源利用率和 compatible-set size；
- compressed/template solver 与未压缩结果逐例一致。

### 6.3 单 DAG 中大图

- candidate→LT baseline 的 primal better/equal/worse、mean improvement、worst regression；
- selective Rollout 的 trigger count/rate、saved completion calls、fallback 和 runtime；
- `[LB,best feasible]` 只作为知识区间；
- 对 Stage 3 风险信号单列：join/barrier、future release、hotspot、maximal-set ambiguity、top-k omission；
- 对 LLM 新风险单列：pipeline bubble、collective phase、optimizer boundary 和跨 micro-batch coupling。

### 6.4 Multi-job

每个目标独立报告：

- global makespan；
- mean/P95/weighted JCT；
- slowdown 分布；
- fairness 指标与 starvation case；
- per-job completion、service、preemption 和 resource share；
- candidate 相对相同目标 baseline 的改善与 worst regression。

不得用 global makespan 改善代替 JCT/fairness 结论。

## 7. Stage 4 首轮实施顺序

- [ ] 冻结 Stage 4 family contract：单 DAG 结构特化与 multi-job 扩展分开定义。
- [ ] 审计现有 `src/llm_structured/`，区分可复用代码、历史目标和与当前语义冲突的实现。
- [ ] 建立可追溯 workload→DAG→fixed-resource-set 转换记录；没有 topology 的样例标为 synthetic/structured。
- [ ] 用最小 PP wave、1F1B、TP/DP/EP、optimizer barrier 和重复 micro-batch 图复核 simulator/Trace。
- [ ] 先以 `LT score × greedy-fill` 作为统一 baseline，不把 Stage 3 resource/union score 升级为默认。
- [ ] 在现有组合接口补一个有硬预算的 conflict-graph packing，并与 greedy-fill/完整 set ranking 分开消融。
- [ ] 定义选择性 Rollout trigger：score ambiguity、barrier proximity、phase transition 和 periodic/template 四类至少各一项。
- [ ] 固定相同 Rollout budget，比较 always-on、triggered 和 never-rollout；报告漏益与节省。
- [ ] 识别重复模板，先建立未压缩小副本 Exact，再证明并实现 template/symmetry key。
- [ ] 为 repetition compression 记录 cache hit、state reduction、runtime 和结果一致性。
- [ ] 建立 LLM motif、structured/real-derived、adversarial 和 compatibility 四层单 DAG suite。
- [ ] 单独设计 multi-job workload/event/state/objective，不把多个 job 静默拼成一个 makespan DAG。
- [ ] 为每个 multi-job 目标建立小图 Oracle、稳定 baseline、starvation/fairness adversarial。
- [ ] 完成 single-DAG small-Exact、large-primal、selective Rollout 与 multi-job 分目标报告。

## 8. Stage 4 验收门槛

进入 Stage 4 正式结论前至少满足：

1. LLM workload、DAG、communication 粒度、topology route 和 fixed-resource-set 的转换可追溯；
2. PP/TP/DP/EP、micro-batch、phase、collective 和 barrier 的输入语义明确，不依赖答案 metadata；
3. 公共 simulator/Trace 仍是唯一 transition 与审计事实来源；
4. 新增 phase/template/job 字段后，normalized key 已重新证明并与 uncompressed/独立 Oracle 对拍；
5. `LT × greedy-fill` 作为稳定 baseline 在全部分层报告；
6. 至少一个 LLM 特化 score 在固定 constructor 下完成 mean/worst 消融；
7. 至少一个有预算 conflict-graph packing 填补 Stage 3 空 slot，并在固定 score/budget 下独立消融；
8. selective Rollout 明确 trigger、hard budget、baseline inclusion、fallback、触发率和 runtime 收益；
9. repetition/template compression 有 future-equivalence 说明和未压缩小图一致性；
10. structured/real-derived 结果与 synthetic motif 分开，未把透明投影写成 measured runtime；
11. 大图以 primal improvement/regression 为主，知识区间不被称为 heuristic gap；
12. multi-job 的 arrival、state、trace 和目标单独定义，makespan/JCT/slowdown/fairness 不混用；
13. Stage 3 的 observed optimal、固定资源抽象、resource/union 负面候选和 Rollout 无退化没有被外推为 LLM 普遍结论。

满足以上条件后，Stage 3 的一般固定资源研究框架才算受控迁移到 Stage 4。仅给任务添加 `phase/micro_batch/collective` 标签，或在全部事件无条件运行 Stage 3 Rollout，不构成 LLM training 结构特化。

## 9. 迁移结论

Stage 3 最值得带入 Stage 4 的不是某个已经定型的资源分数，而是四项基础能力：

1. 可信的 fixed-resource simulator/Trace/Exact；
2. `score × set construction` 的可组合接口；
3. LT baseline 与有预算、可回退的 Rollout 框架；
4. 分层实验、反例驱动和不把下界/observed rate 误写成保证的研究纪律。

Stage 4 的主要新增价值应来自真实 LLM 结构：关键 phase、同步 slack、collective/resource footprint、重复模板和 job 目标。Stage 3 中未完成的 conflict-graph packing slot、真实 topology 证据和 multi-job 语义必须继续显式保留，不能因进入下一阶段而默认完成。
