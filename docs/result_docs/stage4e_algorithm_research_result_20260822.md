# Stage 4e：Barrier 感知调度算法与实验结果（2026-08-22）

## 结论

**Barrier 信息不应作为 Longest Tail（LT）的默认在线修正，也不应进入 Stage 4g 默认组件。**

在 74 个单通道 Stage 1--2 受控样例上，direct barrier 的 margin tie-break 相对 LT 为 **1 胜、65 平、8 负**，总 makespan 变化为 **-7**，最大单例退化为 2；barrier-only 诊断策略为 **2 胜、38 平、34 负**，总变化 **-175**，最大退化 19。在四个冻结的 100--1000 节点验证图和一个 1500 节点成本图上，margin tie-break 全部严格差于 LT。

这是否定的是“当前 direct barrier 信号可安全修正 LT”的主张，不是否定 Stage 4d rollout：相同实验中 choice-only rollout 仍有正面收益；但 direct barrier trigger 没有保留该收益，周期对照反而更好。因此不能把 rollout 的收益归因于 barrier。

## 算法定义与信息边界

所有方法采用固定单 job makespan、finish-to-start DAG、compute 自动且不可抢占、communication 在任务事件处可抢占恢复、无主动 WAIT 的公共模拟语义。

### 1. Direct residual barrier

对当前 eligible communication `c`，一个 direct barrier 是 `c` 的直接后继 join `j`，且 `j` 有至少两个前驱，并且除 `c` 外的所有前驱已经完成。该定义只读取 residual DAG 与公共状态：

```text
direct_last_missing(c) = {
  j | c -> j, indegree(j) >= 2,
      every predecessor of j except c is completed
}
```

未根据 task name、role、collective label 或 metadata 判定 barrier。间接/远端 barrier 没有实现，统一记为 `not_computed`，因而不把有限实现写成全局 barrier census。

### 2. 新释放与结构量

候选被假设完成后，先执行同刻零时长 compute 闭包；此时原先 pending、现在 ready 的非零 compute 节点构成 `newly_ready_compute_ids`，其 duration 之和为 `newly_ready_compute_work`。它不包含仅仅从候选可达但仍被其他前驱阻塞的下游。

`reachable_descendant_compute_work` 是可达未完成 compute 的去重总量，只用于规模和审计描述，不进入在线 tie-break。多资源动作对成员通信取节点并集后再计算，避免共享下游重复计数。

### 3. 到达估计

对 direct join 输出候选分支到 join 的 contention-free 残余路径估计：最晚、次晚、候选分支、slack 与 spread。它明确是忽略未来通信资源竞争的 `heuristic_estimate`，不是 barrier 实际 ready/complete 时间，也不是 makespan 收益。

### 4. 在线 LT 条件修正

冻结阈值为 `m=0.25`。令 `T(x)` 为候选 `x` 的 exclusive residual tail，LT 动作为 `b`。只有满足：

```text
(T(b) - T(x)) / max(T(b), 1) <= 0.25
```

且 `x` 有 direct last-missing 或真实 newly-ready compute 信号时，`x` 才可以挑战 `b`。挑战者按以下词典序选取：direct last-missing 数、newly-ready compute 工作、direct join 下游 tail、task ID。否则严格选择 LT。

这不是 safeguard：它不运行两份完整日程，也没有事后比较最终 makespan。因此可能退化；实验正是用来检验这种风险。

### 5. Barrier rollout trigger

保持 Stage 4d 的候选生成、宽度 2、深度 1、terminal residual LT 与“完整评价且严格改善才采用”规则不变，只把触发器改为：

```text
LT margin <= 0.25 且 LT 与 challenger 的 direct-last-missing 属性不同
```

对照组是 choice-only 全触发、周期 4 和概率 0.25 的固定 seed 随机触发。每图预算为最多 24 个 trigger、96 次 completion、10 万次展开、每决策 0.25 秒、全图 5 秒；未完整评价一律回退 LT 并计入结果。

直接 barrier 初筛同时作为安全消融：它在每个状态都保留 LT 和全部 eligible 候选。因为“不属于 direct last-missing”不能证明不存在间接 barrier 效应，当前规则不删候选；错误过滤率为零，但没有候选/运行时间缩减。

完整双日程 `offline_best_of_lt_and_barrier` 仅作为离线上界，明确 `online=false` 和 `full_schedule_runs=2`，不进入下列在线胜负比较。

## 数据与协议

| 层级 | 内容 | 作用 | 完成状态 |
|---|---|---|---|
| Tier 1 | Stage 1--2 的 74 个单通道既有 benchmark；另有 22 个 Stage 3 多资源诊断图 | 机制与基线对照 | 完成 |
| Tier 2 | 冻结后生成的 100、300、600、1000 节点层状 DAG，各一张固定 seed | 不参与阈值选择的迁移/成本验证 | 4/4 完成 |
| Tier 3 | 1500 节点固定 seed 层状 DAG | 中图成本边界 | 完成 |

Tier 1 的随机、攻击、real-derived 子集分别保留在逐样例 JSON 中。71 个单通道样例带有 benchmark hash 一致的 Exact reference；reference 只用于评价，算法不读取。Stage 3 仍使用相同的 Stage 4c 合法极大兼容集合构造，但没有冻结的多资源 barrier trigger，故仅报告 `barrier_union` 诊断，不声称质量结论。

## Tier 1：单通道主实验

| 方法 | 相对 LT：胜 / 平 / 负（74） | makespan 总改变量 | 最大退化 | Exact 最优（71） | completion calls | fallback |
|---|---:|---:|---:|---:|---:|---:|
| FIFO | 2 / 36 / 36 | -152 | 19 | 31 | 0 | 0 |
| 固定顺序 | 1 / 38 / 35 | -177 | 19 | 33 | 0 | 0 |
| LT | 0 / 74 / 0 | 0 | 0 | 60 | 0 | 0 |
| barrier-only（诊断） | 2 / 38 / 34 | **-175** | **19** | 34 | 0 | 0 |
| LT + 安全 direct 初筛 | 0 / 74 / 0 | 0 | 0 | 60 | 0 | 0 |
| LT + margin tie-break | **1 / 65 / 8** | **-7** | 2 | 54 | 0 | 0 |
| choice-only rollout | **10 / 64 / 0** | **+17** | 0 | 69 | 684 | 0 |
| barrier-trigger rollout | **1 / 73 / 0** | **+1** | 0 | 60 | **26** | 0 |
| 周期 4 rollout | 8 / 66 / 0 | +15 | 0 | 68 | 238 | 0 |
| 随机 rollout（seed 0） | 0 / 74 / 0 | 0 | 0 | 60 | 0 | 0 |

“总改变量”是逐图 `makespan(LT)-makespan(method)` 的总和，不是百分比。所有 rollout completion 都完整完成，fallback 为零；因此 barrier-trigger 的持平不是 timeout 后的伪 LT 回退。

### 对结果的解释

1. **barrier-only 明显不成立。** 它频繁抢占较长的 residual critical communication，局部 join 信号无法补偿全局 critical tail。
2. **安全初筛没有成本收益。** direct-only 初筛为避免误删，必须保留全部候选；它与 LT 的 74 条 trace 完全相同，错误过滤率为零、缩减率也为零。
3. **margin 只能减轻而不能消除这个问题。** 八个退化样例表明，tail 接近并不意味着 barrier 字典序可安全打破平局；其 Exact 最优数从 LT 的 60/71 降到 54/71。
4. **direct barrier trigger 过于稀疏且漏掉有效 rollout 决策。** 它只花 26 次 completion，却只获得 1 单位改善；同样的阶段预算下，周期 4 获得 15 单位改善。这不支持“节省搜索是 barrier 信号带来的净收益”。
5. **rollout 本身仍是正面机制。** choice-only 在本协议下 10 胜、无负，改善 17；这与 Stage 4d 的受控结论一致，但不能被归因给 barrier。

## Stage 3 多资源诊断

22 图中，`barrier_union` 相对 LT packing 为 **0 胜、17 平、5 负**，总变化 -6、最大退化 2。该结果只表明当前 direct barrier set score 没有收益；它不评估或否定 Stage 4c packing，因为集合构造固定且本轮没有真正的低成本整集合 barrier trigger。多资源 Stage 4e 质量结论为 **unknown / 不纳入**。

## 冻结验证与成本

| 图规模 | LT | margin tie-break | 差值（LT - margin） | 总 wall-clock | feature census | 峰值内存 | 硬时限 |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 100 | 132 | 133 | -1 | 0.274 s | 21.8 ms | 0.55 MB | 30 s |
| 300 | 390 | 391 | -1 | 1.844 s | 188.1 ms | 2.27 MB | 30 s |
| 600 | 776 | 777 | -1 | 7.640 s | 735.0 ms | 6.78 MB | 30 s |
| 1000 | 1317 | 1320 | -3 | 20.768 s | 1.952 s | 15.70 MB | 30 s |
| 1500（成本图） | 1952 | 1962 | -10 | 48.157 s | 4.659 s | 32.60 MB | 60 s |

100--1000 节点的冻结验证全部完成，无 timeout。1500 节点也在 60 秒内完成。在线输入已经避免完整 descendant union 扫描，但总体成本仍随节点和决策数显著增加；加上质量退化，不存在“等质量且低成本”的肯定结论。

## 适用范围、失败模式与阶段决定

可以保留的资产：direct residual join census、newly-ready 的正确语义、零时长闭包、去重 action 特征、显式离线上界对象，以及 barrier 作为诊断字段。

不应保留为默认调度组件的资产：barrier-only 全局排序、当前 `0.25` margin tie-break、当前 direct barrier rollout trigger、以及当前 direct barrier multi-resource set score。

本轮没有发现模拟器缺口：所有完成运行均由公共 simulator 执行并经 trace validator 验证；大图没有以超时作为结论。最终的受限/否定结论来自完成的统一对照、Exact reference 评价、周期/随机控制和冻结规模验证。

后续若重新研究 barrier，必须提出不同于 direct last-missing 的、可解释的候选机制，并在独立 holdout 上证明同时满足“无系统性退化、相同预算下优于随机/周期 trigger、成本合理”。在此之前 Stage 4e 保持“特征原型/诊断工具”状态。

## 复现

```powershell
$env:PYTHONPATH='src;.'
python experiments/preemptive/stage4e_barrier_evaluation.py --output docs/result_docs/stage4e_barrier_evaluation_v2_20260822.json
```

入口：[stage4e_barrier_evaluation.py](/D:/Code/SimAI/DAG_heuristic/experiments/preemptive/stage4e_barrier_evaluation.py)；完整逐图记录：[stage4e_barrier_evaluation_v2_20260822.json](/D:/Code/SimAI/DAG_heuristic/docs/result_docs/stage4e_barrier_evaluation_v2_20260822.json)。
