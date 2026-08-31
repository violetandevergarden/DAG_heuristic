# Stage 3 normalized state key 与基础下界证明草稿

日期：2026-08-16

## 1. 适用范围

本文只适用于当前 Stage 3 模型：单个联合 DAG、finish-to-start、整数 duration、compute ready 后自动且不可抢占、communication 仅在 task event 暂停/恢复、零切换开销、无最小粒度、固定非空资源集合、完整资源原子获取、无动态路由、work-conserving maximal compatible set，以及 makespan 目标。

一旦加入 job arrival、deadline、绝对时间相关代价、抢占开销、minimum quantum、资源速率随时间变化、动态路由或决策边界上的持久资源预留，本文结论不再自动成立。

## 2. 规范决策边界

公共执行模型只在以下稳定状态请求 scheduler 动作：

- 同一时刻的全部 compute/communication 完成已原子处理；
- 零时长 compute 依赖闭包已经完成；
- 未完成 communication 只保存 `suspended + remaining`，不持有资源；
- 当前运行 compute 以 `running + remaining` 表示；
- 若没有 eligible communication，simulator 已自动推进 forced idle，直到完成或出现下一决策；
- 因而每个真正的 scheduler action 都是非空 maximal compatible set。

规范 key 为按固定拓扑顺序排列的：

```text
((task_0.status, task_0.remaining), ..., (task_n.status, task_n.remaining))
```

## 3. Future-equivalence

设两个稳定决策状态 `s`、`s'` 具有相同 normalized key。

1. **依赖完成条件相同。** 每个节点及其前驱的 `completed` 状态逐项相同，所以两状态下 ready compute 与 eligible communication 相同。
2. **运行 compute 可恢复。** `running` compute 的剩余时间逐项相同；compute 不可抢占，因此下一 compute completion 的相对时间相同。初始开始时刻不影响未来 makespan 增量。
3. **communication 进度相同。** pending communication 从不可变模型取得初始 duration；suspended communication 的 remaining 在 key 中；completed communication remaining 为零。
4. **资源占用相同。** 稳定边界上 active communication set 与 resource-owner map 按定义均为空。下一动作的资源需求从不可变 `resources[task_id]` 恢复，不依赖历史路由或占用。
5. **合法动作相同。** eligible 集与固定资源集合相同，因此冲突图及全部 inclusion-maximal compatible sets 相同。
6. **下一事件增量相同。** 给定同一合法 set，所有 active compute remaining 与 selected communication remaining 相同，最小正事件增量相同。
7. **后继 key 相同。** 同一增量同步减少相同任务的 remaining；同刻完成集合、依赖闭包和下一 eligible 集相同，所以得到相同 normalized successor key。
8. **残余代价相同。** 对上述动作归纳，两个状态拥有同构的全部未来动作树及相同的每条相对时间长度。因此最优 residual makespan 相同。绝对时间只对最终 makespan 添加常数平移。

由此，在当前假设下 normalized key 是 future-equivalent。`MultiResourceState` 显式保存 `active_allocations` 与 `resource_owners`；`exact_oracle_uncompressed()` 从 state 读取 `(absolute time, full runtime tuple, active allocations, resource owners)`，不再把后两项硬编码为空。当前 simulator 在每次稳定边界 transition 前断言两个字段为空，因此未来若引入持久预留而没有同步修改 transition/key，会立即失败，不会被 audit key 静默合并。normalized Exact、uncompressed Exact 与独立 tick/set Oracle 的固定随机小图对拍是实现证据，不替代上述论证。

## 4. 基础下界

定义：

```text
LB0(s) = forced_idle_prefix(s) + max(L(s'), max_r D_r(s'))
```

其中 `s'` 是 simulator 从 `s` 自动推进 forced idle 后的下一稳定决策状态；`L` 是忽略资源竞争、使用当前 remaining 的 residual precedence longest path；`D_r` 是所有尚未完成且固定资源集合包含 `r` 的 communication remaining 之和。

安全性如下：

- forced-idle prefix 在当前状态下没有任何合法 communication 可执行，是所有 schedule 必经的时间；
- 任一 finish-to-start path 上的任务必须按依赖顺序完成，忽略资源冲突只能提前完成，因此 `L` 不超过 residual optimum；
- 同一资源 `r` 容量为 1，所有需要 `r` 的未完成 communication 都必须在持有完整资源集时获得其全部 remaining service，所以这些区间在 `r` 上不能重叠，完成它们至少需要 `D_r`；
- 多资源 communication 在每个所需资源上分别计入，但只对资源负载取最大值，不跨资源相加，因此不会把可并行工作错误串行化；
- 两个安全下界取最大值仍安全。

所以 `LB0(s)` 不超过从 `s` 开始的最优 residual makespan。它可以用于 Exact 的安全剪枝和 `[LB,best feasible]` 知识区间，但不能被解释为 heuristic gap 或理论近似比。

## 5. 实现防线

- `tests/muti_channel/preemptive/test_preemptive_muti_channel.py` 对 normalized/uncompressed Exact、基础下界、forced idle 和预算状态做手工回归；
- `tests/core/trace/preemptive/test_contract_and_replay.py` 使用 3 资源非层次固定集合随机图，与独立 tick/set Oracle 对拍；
- Exact 只有 `status == "optimal"` 才能进入 reference sidecar；预算耗尽返回 deterministic LT feasible incumbent，并标明 `state_limit` 或 `time_limit`；
- 任何修改稳定边界或 runtime 字段的变更，都必须重新审查本证明并运行三方对拍。
