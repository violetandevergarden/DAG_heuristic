# Stage 3 `muti_channel/preemptive` 代码修正结果

日期：2026-08-16

## 1. 结果概览

本轮按 `stage3_muti_channel_review_20260816.md` 与其修正计划完成了固定多资源可抢占实现的边界修正。核心结果是：**多资源 event transition、合法动作和 forced idle 已从算法文件提升到公共执行层；solver 只保留 priority、compatible-set policy、Rollout 和 Exact。**

同时建立了 normalized/uncompressed/独立 tick Oracle 的可信链、机器可读 Exact 状态、基础安全下界、有硬预算的 Set-Rollout、Stage 3 独立 benchmark 与薄实验入口。完整测试结果为 `125 passed`（最终验证见第 8 节）。

目录名 `muti_channel` 作为当前公开格式保持不变；`muti_channel/nonpreemptive` 未被推进或重构。

## 2. 公共执行模型

新增 `src/core/execution/multi_resource.py`，公共层现在拥有：

- `MultiRuntimeTask`、`MultiResourceState`、`MultiResourceAction` 和 `MultiResourceTrace`；
- 固定非空资源集合验证；
- complete-set 原子资源获取语义；
- eligible、兼容性和 inclusion-maximal 合法性检查；
- active compute 与 selected communications 的同一事件增量推进；
- 同刻完成后的 compute/零时长闭包；
- simulator-owned forced idle；
- 从动作序列构建 task/resource interval 与事件 trace。

稳定决策边界上没有 active communication resource ownership。未完成 communication 保存 remaining，下一动作重新选择它表示继续或恢复。算法不维护第二套资源占用或时间推进逻辑。

旧实现把空 `MultiAction()` 当作 forced idle。现在：

- `legal_actions()` 只返回非空 maximal compatible sets；
- 空 scheduler action 会被明确拒绝，并提示 forced idle 由 simulator 管理；
- `normalize_decision_state()` 在无 eligible communication 时自动推进到下一 compute event；
- `decision_count` 只统计真实通信集合决策；
- forced idle 只记录在 `trace.forced_idle`。

## 3. Compatible-set 枚举

旧 `maximal_actions()` 先生成全部非空子集，再过滤兼容性与 maximal 性。新实现把 eligible communication 建成兼容图，并用确定性 Bron--Kerbosch 直接生成 maximal cliques，即资源冲突图的 maximal independent sets。

这项修改没有改变合法动作定义：合法集合仍是 inclusion-maximal，不要求 maximum cardinality，也不直接代表 makespan 最优集合。Exact 与 Rollout 记录 compatible-set 生成数、mean/max branch 和 set enumeration runtime。

## 4. Trace 独立回放

`src/muti_channel/preemptive/trace.py` 改为依赖公共 trace 数据类型，不再反向导入 solver 类型。validator 独立检查：

- 每个任务 service 等于 duration；
- compute 只有一个连续区间；
- finish-to-start 依赖；
- communication 每一段同时拥有完整固定资源集合；
- 每个资源上的区间互斥；
- 每个 decision 的 selected set eligible、兼容且 maximal；
- forced idle 时没有 eligible communication 且存在运行 compute；
- decision 与 forced-idle segments 无缝、无重叠覆盖 `[0,makespan]`；
- 同刻事件稳定排序、最终状态与 makespan 一致。

新增手工回归覆盖 disjoint parallel、shared conflict、原子多资源获取、大小不同的合法 maximal sets、多资源暂停/释放/恢复、同刻 communication+compute 完成和 forced idle 非动作。错误 trace mutation 覆盖缺失资源区间、non-maximal decision 和缺失 forced-idle segment。

## 5. Exact 与下界合同

### 5.1 两种 Exact

- `exact_oracle()`：使用 normalized key 的正式小图 Oracle；
- `exact_oracle_uncompressed()`：保留 absolute time、完整 runtime tuple，并从 state 读取真实 active allocation/resource owners 的 audit Oracle；公共 simulator 另行断言当前稳定边界上二者为空。

两者均只通过公共 simulator 生成后继。独立 `tests/oracles/preemptive/tiny_oracle.py` 继续按 tick/set 穷举，不调用 event transition。

随机交叉核验扩展为 30 个 2--3 资源小图，资源集合覆盖 `{r0}`、`{r1}`、`{r0,r1}`、`{r1,r2}` 等非层次组合。三种 Oracle makespan 一致；基础下界逐图不超过 tick optimum。

normalized key 与基础下界证明另见 `docs/process_docs/stage3_normalized_key_and_lower_bound_proof_20260816.md`。

### 5.2 结果状态与预算

`MultiResult` 新增：

- `status = optimal | feasible`；
- `termination_reason`、`runtime_ms` 和 `lower_bound`；
- states、transitions、dedup/prune；
- compatible-set 数、mean/max branch、set enumeration runtime；
- peak state count；Python 对象级 peak memory bytes 当前显式为 `null`；
- Rollout expanded/evaluated/cache/fallback 统计。

state/time budget 耗尽时，Exact 返回确定性的 LT feasible incumbent，不再抛异常后由上层猜测结果性质，也不标为 optimal。`benchmark_generate/reference.py` 对所有 preemptive 场景统一要求 `status == "optimal"`，并把预算、runtime、states、下界、set 统计和终止原因写入 sidecar。

基础下界为：

```text
max(residual precedence longest path, maximum per-resource residual load)
```

forced-idle prefix 单独计入。多资源 communication 在每个所需资源上分别计入完整 remaining，但不跨资源求和。

## 6. 算法与稳定入口

`src/muti_channel/preemptive/interface.py` 与 `src/registry.py` 现在共享以下公开算法面：

- `longest_tail_pack`：稳定 LT greedy-fill baseline；
- `resource_pack`：资源负载 tie-break 消融；
- `bottleneck_pack`：负面 research baseline；
- `resource_downstream_pack`：逐资源 downstream-demand 候选；
- `union_downstream_set`：按可达子图并集给整个 maximal set 打分，shared downstream 只计一次；
- `rollout_sets2d2`：top-2、depth-2、有 node/set/time budget 的 receding-horizon Rollout；
- `exact` 与 `exact_uncompressed`。

内部算法实现进一步拆成两个正交轴，没有引入继承体系：

- 打分函数：`score_tasks()` 与 `score_sets()`；
- 用分数构造动作：`greedy_fill_from_task_scores()` 与 `select_best_scored_set()`。

因此 `LT × greedy-fill`、`resource-downstream × greedy-fill` 和 `union-set-score × best-maximal-set` 是显式函数组合。Rollout 在集合搜索层复用 set score 做 shortlist，并复用 `LT × greedy-fill` 做 baseline/completion/fallback。测试证明替换 task score 可以在不修改 greedy constructor 的情况下选择不同合法 maximal set。

这里必须区分“接口 slot 已建立”和“算法类别已实现”：`score_sets()` 当前只支持 `union_downstream`，packing/construction 当前只有 task-score greedy-fill 与“完整枚举 maximal sets 后取最低 set score”。`stage3_muti_channel.md` §2.3.3 第 2 类“加权独立集 / 有预算冲突图选择”尚未实现；当前没有 bounded weighted-independent-set、局部 `remove 1 -> add 2+`、近似 MWIS 或不完整冲突图搜索 constructor。Bron--Kerbosch 只负责完整枚举合法 maximal sets，不是加权独立集 heuristic。Set-Rollout 是跨事件的 set-action 前瞻，也不填补这个静态 packing slot。因此，函数拆分只让该 slot 可以后续接入，不能作为 §3.1.6 集合互补方法已经覆盖的证据。

Rollout 的合同包括：LT baseline set 必须进入候选、forced idle 不消耗 depth、normalized state memo、deterministic tie-break，以及预算耗尽回退到 LT set。测试显式验证极小 node budget 会触发回退且最终 makespan 与 LT baseline 相同。

已删除 `_exact()` 中只写不读的 `representatives` 历史遗留；Stage 3 递归直接携带 state，memo 保存 residual result，不需要 Stage 1 式 key→state 重建表。

`resource_downstream` 当前仍会对每个 eligible candidate 分别执行一次 downstream reachability。该项已记录为 scaling 前性能债务；本轮按研究边界没有加入 children/reachability cache，以免与接口拆分同时改变性能实现。

Beam 与 Monte Carlo 没有进入 Stage 3 公开矩阵。Stage 2 的 Beam 仍保持 experimental upper-bound 定位，不是 Stage 3 部署候选或退出条件。

## 7. Benchmark、reference 与实验入口

新增 5 个自包含 Stage 3 adversarial JSON：

- `pm_stage3_atomic_acquire`；
- `pm_stage3_maximal_not_maximum`；
- `pm_stage3_join_hotspots`；
- `pm_stage3_shared_downstream`；
- `pm_stage3_depth2_investment`。

它们的 metadata 包含 attack target、mechanism 和 semantic scope。旧 4 个 lifted adversarial 文件仍保留路径兼容，但正式实验将它们归为 compatibility/semantic regression，不再称为当前算法攻击集。

新增 3 个 structured 固定路由 JSON。每个文件明确记录：透明手工 topology fixture、TopologyLoader-compatible BFS 路由冻结、directed-link 与 endpoint NIC resource set、communication node 作为可恢复逻辑传输，以及“synthetic topology snapshot，不是 measured runtime trace”。因此本轮没有把它们写成真实网络性能结论。

9 个 adversarial 和 3 个 structured 文件均生成了新的 `oracle_status=optimal` reference sidecar。`benchmark/index.jsonl` 已重建，当前包含 171 个 benchmark 文件。

新增薄入口 `experiments/preemptive/stage3_muti_channel.py`。算法、transition、trace 和统计均来自 `src/`；runner 只选择 committed/runtime suite、调用算法并保存 raw/summary。结果写入 `docs/result_docs/stage3_muti_channel_experiment_20260816.json`。

## 8. 验证结果

执行：

```text
python -m pytest -q
```

最终结果：

```text
125 passed
```

同时执行了修改范围 Ruff 检查和 `git diff --check`。Stage 3 专属实验可复现命令为：

```powershell
$env:PYTHONPATH='src;.'
python -m experiments.preemptive.stage3_muti_channel
```

## 9. 保留边界

本轮修正完成了固定资源集合抽象下的公共语义、Exact、benchmark 和首轮实验闭环，但 Stage 3 算法矩阵仍有明确缺口。以下内容没有被伪装成已解决：

- `peak_memory_bytes` 目前显式不可用，只报告 peak state count；
- structured 路由是透明 synthetic topology snapshot，不是 measured SimAI/cluster runtime trace；
- dynamic routing、migration、partial acquire、congestion control、collective 内部协议和多 job 目标均不在本阶段；
- resource-downstream 与直接 set score 的实验 worst regression 明显，不能注册成稳定部署默认；
- §2.3.3 第 2 类加权独立集/有预算冲突图 packing 尚未实现，§3.1.6 不能据“已拆分接口”判定完成；
- 两个 32/33 节点 primal 图在 0.25 秒 Exact 预算下只返回 feasible，未进入 optimal 分母；
- 本轮没有形成一般多资源 approximation ratio，也没有外推 Stage 2 的 `P` 下界、2-bound 或 observed optimal rate。
