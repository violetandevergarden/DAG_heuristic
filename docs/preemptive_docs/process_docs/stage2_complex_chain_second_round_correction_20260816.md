# Stage 2 一般 DAG 第二轮修正记录（2026-08-16）

## 1. 本轮问题与处理边界

本轮针对第一轮的四个明确缺口继续修正：Rollout 递归缺少 transposition memo、Longest-delay 与 release gain 混用、Exact 缺少可控 bound/search-component 消融、Stage 2 结构特征与规模压力实验不足。另建立 fixed-width Beam 反例自动搜索器，但只有经过 Exact 明确返回 `optimal` 的图才允许固化为反例。

模拟语义没有变化：所有动作仍经 `PreemptiveDAGModel.legal_actions/step`，没有主动 WAIT、私有时间推进或第二套 ready 语义。

## 2. Rollout memoization 的安全口径

`normalized_state_key` 不含绝对时间，所以不能缓存 `evaluate` 原先返回的绝对完成时刻。修正后的递归返回“从当前事件状态到完成的剩余代价”，并使用

```text
(remaining_decision_depth, normalized_state_key(state))
```

作为 key。forced idle 的已流逝时间在查表前后显式加回。该口径依赖与 Exact normalized key 相同的 future-equivalence 假设：无外部 release clock、零抢占/恢复开销、task-event 决策、目标仅为单 DAG makespan。memo 跨 receding-horizon 决策复用，不改变候选、tie-break 或 simulator transition。

新增 `use_memo=False` 仅用于消融。四个独立 communication 的手工 transposition 图验证 memo on/off makespan 都为 10，且 memo 版本发生实际命中并减少候选评价。

## 3. Longest-delay 与 release gain 分离

第一轮把 Longest-delay 实现为“所有立即新增 ready task 的 duration 之和”，这实际是计划 §2.3.2 的 release gain。

本轮冻结为：

- Longest-delay：候选完成并展开零时长 compute closure 后，立即新增 ready 的正时长 compute 中最大 duration；不计 communication，不按 fork breadth 求和。
- release gain：同一 hypothetical completion 后，全部新增 ready 正 work（compute 和 communication）的 duration 之和。
- Longest-tail：不含当前 communication remaining 的最大 residual downstream path。
- LRPT：包含当前 communication remaining 的最大 residual path。

成对图中，两个 3-tick compute 的 fork 使 release gain 取 6，而单个 5-tick compute 使 Longest-delay 取 5，二者首选动作不同。

## 4. Exact 消融接口

`exact_oracle` 新增：

- `bound_mode = none | communication | path | combined`，分别对应 0、P、L、max(P,L)；
- `use_memo`；
- `use_incumbent`，关闭时不使用 Longest-tail completion 作为初始上界，但搜索得到第一个完整分支后仍可形成搜索内 incumbent。

无论 pruning 使用哪一档，结果字段 `lower_bound` 始终报告最强的已证明 `max(P,L)` certificate。小图测试把四档 bound、memo off、initial incumbent off 全部与独立 tick Oracle 对齐。

## 5. 独立结构特征

新增而未混淆为理论下界的实验特征：

- `barrier_urgency`：每个可达多前驱节点只计一次 residual barrier tail，并按候选到 barrier 的 residual distance 折减；
- `unique_downstream_work`：候选可达子 DAG 的 residual work 按节点集合去重；
- `downstream_communication_demand`：可达 communication residual work 按节点集合去重；
- `structure_aware`：barrier、communication demand、unique work、exclusive tail 的字典序实验组合。

`pm_stage2_shared_downstream` 对应的单元图验证共享 communication 只计一次。正式消融显示 barrier-only 与直接组合明显退化，因此这些组合没有进入稳定 registry；函数和实验入口保留用于后续反例驱动研究。release gain 作为计划内基础对照进入 registry。

## 6. Beam 定位与停止条件

`experiments/preemptive/stage2_beam_counterexample_search.py` 先以更宽 Beam 做廉价筛选，再调用 Exact teacher。接受条件为：

1. width-8 使用 full decision horizon；
2. Exact 在预算内返回 `status=optimal`；
3. width-8 makespan 严格大于 Exact。

搜索器在 seed 26081623、index 374 的 random-join 图上成功检出 width-1 控制反例（Exact 18，Beam-1 19），说明搜索与判据能发现剪枝失败。但 Beam 不进入部署路线，因此停止继续搜索 width-8 反例。“反例未穷尽”作为鲁棒性边界保留，不再作为 Stage 2 退出条件。Beam-8/32 在 registry 中标为 `experimental`：仅实验上界/对照、非部署候选、不主张鲁棒性。

## 7. 验证

- `python -m pytest -q`：117 passed；
- 本轮相关 Python 文件 Ruff：通过；
- 第二轮正式矩阵：45/45 Exact optimal；
- scaling 原始结果、bound 消融和未命中 Beam 搜索账本均保存到 `docs/result_docs/`。
