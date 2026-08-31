# Stage 2 family contract、Exact 状态等价与安全下界

日期：2026-08-16

## 1. 结论

本轮采用修正方案 P0.1 的方案 B：Stage 2 的公开输入允许 raw general DAG。相邻同类节点、fork、join、shared downstream、多层 barrier 和多个弱连通 component 均可出现；多个 component 仍属于同一个 makespan 实例，不解释成多个 job。实现不会为了复用 Stage 1 算法而静默链化、合并节点或插入 dummy communication。

`validate_complex_chain()` 的工程边界为：DAG 非空、task ID 唯一、依赖存在、无环、communication work 严格为正。公开 benchmark 层继续由通用 validator 保证 single-channel communication 只使用固定 `channel:0`、compute 不占通信资源以及 v2 可抢占语义。理论若使用交替规范形，必须另外证明转换保持 ready 条件、总通信工作、compute release 和 makespan；当前实现不假定该转换存在。

## 2. 两个 Exact key

审计型未压缩 key 为：

```text
(absolute time, every RuntimeTask(status, remaining, started_at, completed_at),
 last_communication)
```

normalized key 为按固定拓扑 task ID 顺序排列的：

```text
((status_1, remaining_1), ..., (status_n, remaining_n))
```

两种 Exact 都只枚举 `PreemptiveDAGModel.legal_actions()`，并只用 `model.step()` 产生 successor。未压缩版本是审计基线，normalized 版本用于正式小图 ground truth 和 Beam 去重。

## 3. normalized key 的未来等价证明草稿

### 3.1 假设

证明依赖以下全部条件：

1. DAG、task kind、原始 duration 和依赖在求解过程中固定；task 在 key 中的位置由固定拓扑顺序唯一确定。
2. 依赖为 finish-to-start；没有外部 wall-clock release、deadline、周期事件或其他绝对时间约束。
3. compute ready 后自动开始、不可抢占；communication 只在 task event 决策，暂停保留 remaining。
4. 单 channel、零暂停/恢复开销、无最小 quantum；`last_communication` 不改变合法动作或未来成本。
5. 目标只为从当前状态到全部完成的剩余 makespan；started/completed timestamp 不进入第二目标或成本。

### 3.2 可推导字段

- task ID：由 tuple 位置和固定拓扑顺序确定。
- predecessor completion：每个 predecessor 的 `status == completed` 可直接读取。
- pending task 是否 ready：由 predecessor status 与 task kind 推导。
- eligible communication：所有 suspended communication，加上 predecessor 已完成的 pending communication。
- active compute：`kind == compute and status == running`。
- compute 的下一个完成间隔：由所有 running compute 的 remaining 最小值确定。
- communication 的下一个完成间隔：由被选中 communication 的 remaining 确定。
- 同刻自动 compute closure：由 pending compute、依赖完成情况和原始 duration 唯一确定。

决策稳定态不存在未记录的 running communication；一次 dispatch 在下一个 task event 处返回 suspended 或 completed 状态。因此 key 不需要另外记录 channel owner。

### 3.3 一步等价

设两个稳定态 `s`、`s'` 具有相同 normalized key，绝对时刻分别为 `t`、`t'`。由 3.2，两者的 eligible communication、active compute 和合法动作完全相同。

对任一相同合法动作：

- 若为 forced idle，推进量均为 active compute remaining 的同一最小值；
- 若为 dispatch，推进量均为被选通信 remaining 与下一个 compute completion 的同一最小值；
- 完成集合、暂停后的 communication remaining、running compute remaining 和自动 closure 均相同。

所以两个 successor 仍具有相同 normalized key，且时间增量相同；所有 event timestamp 只相差常数 `t'-t`。

### 3.4 归纳与目标保持

对剩余决策数归纳，一步等价保证任意合法 action suffix 在两个状态中均合法，并产生相同的剩余 makespan。反向亦然，因此两个状态的最优剩余 makespan 相同，最优 action 集相同。删除 absolute time、started/completed timestamp 和 `last_communication` 是安全的。

同一 normalized key 若在 `t_1 < t_2` 到达，前者的任一未来 suffix 都比后者早 `t_2-t_1` 完成。在只优化 makespan 的当前假设下，较早状态 time-dominates 较晚状态；Beam 可只保留较早 representative。

若以后加入外部 release、deadline、切换成本、缓存热度、连续运行奖励、JCT/fairness 或任何依赖历史的目标，本证明立即失效，key 必须显式版本保护并重新证明。

## 4. 三方交叉验证

固定 seed `260816` 的 100 个 2–6 节点 raw general DAG 已固化为测试。每个实例比较：

1. normalized event Exact；
2. full audit event Exact；
3. tests 中独立的 tick Oracle。

三者 100/100 makespan 一致，且两种 event Exact 都返回 `status='optimal'`。测试包含零时长 compute、same-kind edge、fork、join、shared predecessor/successor 和多个 component。该结果是实现证据，不替代上述证明；失败 seed 今后应直接固化。

## 5. 安全下界

对任一决策稳定态定义：

- `P_rem`：所有未完成 communication 的 remaining work 总和；pending communication 使用原始 duration。
- `L_rem`：把当前 remaining work 作为节点权重、忽略 channel 冲突后，剩余 DAG 中最长加权因果路径。

### 5.1 `P_rem` 安全性

单 channel 任意时刻至多服务一个 communication，服务速率为 1。全部剩余 communication work 最终都必须被服务，compute overlap 不能减少这部分 channel work，所以剩余 makespan 至少为 `P_rem`。

### 5.2 `L_rem` 安全性

任意有向因果路径上的节点必须按 finish-to-start 顺序完成。即使移除所有其他 communication 竞争，该路径仍至少需要其节点剩余权重之和。因此真实剩余 makespan至少为所有剩余因果路径长度的最大值 `L_rem`。

### 5.3 组合与剪枝

`max(P_rem, L_rem)` 是安全下界。Exact 对 action successor 使用：

```text
elapsed(action) + max(P_rem(child), L_rem(child))
```

只有该值严格大于当前 incumbent 时才剪枝。相等分支仍搜索，以保留历史接口要求的字典序最小最优 trace；这不影响 makespan 最优性。

历史 `Q/window/cut` 没有在本轮进入 Stage 2 Exact。它们若要使用，必须重新证明在多前驱、shared downstream 和当前 residual state 下安全，并先对独立 Oracle 的可达状态验证 `LB <= OPT_remaining`。

## 6. Exact 完成与失败契约

- 完成全部必要枚举：`status='optimal'`，记录 runtime、explored/generated/deduplicated、incumbent/lower-bound prunes、peak states 和 root lower bound。
- state/time budget 耗尽：返回 Longest-tail incumbent，`status='feasible'`，并设置 `termination_reason='state_limit'` 或 `'time_limit'`。
- reference generator 对 Stage 2 强制检查 `status == 'optimal'`；feasible incumbent 即使数值碰巧等于旧 reference，也不能生成 sidecar。

## 7. 理论边界勘误

Stage 1 的 chain frontier、同构链计数压缩和 `P+Q` charging 证明没有迁移到一般 DAG。特别是一般 DAG 的 `T <= P+Q <= 2OPT` 当前没有证明；join 可能让局部路径等待由其他分支决定，旧 charging 可能重复计费。当前 Stage 2 只主张 `max(P_rem,L_rem)` 下界，不主张统一常数近似比。
