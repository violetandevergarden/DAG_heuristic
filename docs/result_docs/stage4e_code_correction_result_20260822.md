# Stage 4e：代码修复结果（2026-08-22）

## 完成状态

已完成 `stage4e_code_review_correction_plan_20260821.md` 中可由当前公共模拟器和 Stage 1--3 数据验证的代码修复。修复没有改动 DAG、时间推进、资源占用或 Exact 的公共语义；调度器仍只从公共模拟器给出的合法通信或极大兼容集合中选择动作。

本轮新建了结果，不覆盖历史 Stage 4e 文档。离线双日程比较已不再作为公开在线算法。

## P0：特征语义修复

| 原问题 | 修复后定义 | 证据等级 / 在线用途 |
|---|---|---|
| `reachable_compute_release` 把可达下游冒充立即释放 | `newly_ready_compute_work` 和 `newly_ready_compute_ids` 只计“候选通信完成 + 同时刻零时长 compute 闭包”后，原先 pending 而新 ready 的 compute；`reachable_descendant_compute_work` 单独保留为结构规模量 | 前者 `residual_exact`，后者 `structural_exact`；只有前者可作在线信号 |
| `last_missing_join_count` 没有说明范围 | 改为 `direct_last_missing_join_count` / `direct_last_missing_join_ids`：候选必须是 join 唯一未完成前驱 | `structural_exact`；未实现 indirect barrier，明确标记 `not_computed` |
| 使用 dependency 到 sink 的 tail 解释 arrival/slack | 提供 direct join 的候选分支到 join 估计：最晚、次晚、候选分支、slack、spread；估计忽略未来通信竞争 | `heuristic_estimate`，不写作真实到达时间或 makespan 因果量 |
| `paused_tail_penalty` 从 active compute 推断暂停通信 | 删除。单通道稳定决策状态只保留真实的 `last_communication`；多资源稳定边界没有 active allocation，因而不虚构该字段 | 不再参与特征或评分 |
| `compatible_completion_gain` 重复相加立即释放与可达总量 | 删除 | 无误导性“收益”字段 |
| `packing_complementarity` 在动作间不具可解释变化 | 删除；多资源 set score 仅使用节点并集的新 ready、直接 join 和下游量 | packing 构造与 barrier 评分保持正交 |

`src/llm_structured/barrier.py` 仍是只读分析模块：没有时钟推进、动作合法性或日程选择。完整审计快照保留可达后代量；在线比较改用 `online_barrier_inputs`，只计算实际使用的 direct join、真实新 ready、tail 字段，避免每个候选都做整个可达子图扫描。

## 在线与离线边界

原 `schedule_barrier_safeguarded` 及多资源对应函数会运行两份完整日程、再按最终 makespan 选择，不能称为在线算法。现已改为：

- 单通道：`offline_best_of_lt_and_barrier`；
- 多资源：`offline_best_of_lt_and_barrier`；
- 返回对象固定标明 `online=false`、`full_schedule_runs=2`、baseline、candidate、selected policy 和总 runtime；
- 两者均已从两个 preemptive public interface 的算法注册表删除。

替代的单通道在线方法是 `schedule_barrier_margin_tiebreak`：先取得 residual LT 动作；只在 challenger 与 LT 的 exclusive residual-tail 归一化差距不超过冻结阈值 `0.25` 时，以 direct last-missing、真实 newly-ready compute、direct-join downstream tail、task ID 的词典序决定是否改选。阈值外严格保留 LT。该方法不调用完整备选日程，也不读取 Exact、reference result、metadata 或离线标签。

计划要求的初筛也已实现为 `schedule_barrier_prescreen`。在只识别 direct barrier 的前提下，未观察到 direct 信号不能证明“没有 indirect barrier 影响”，所以它明确保留所有 eligible 候选和 LT，错误过滤率为零、候选缩减也为零。这是可审计的安全 no-op，不把“不知道”伪装成可删候选。

多资源没有被伪造为“在线 barrier 修正”：动作继续由 Stage 4c 的固定合法极大集合构造器产生；本轮只保留 `barrier_union` 诊断分数。缺少经验证的、低成本的整集合 trigger 前，不给出多资源 Stage 4e 质量结论。

## 新增或更新验证

- 新增 newly-ready 与 reachable 总量分离测试；
- 新增共享后代并集只计一次测试；
- 新增零时长 compute 闭包测试；
- 新增 direct last-missing、label/role 不改变结构判定测试；
- 新增离线比较对象的 `online=false`、两次完整日程断言；
- 新增 margin 阈值外保持 LT trace 的断言；
- 既有单/多资源 motif 继续验证 trace 合法性、Exact 标签和极大兼容集合。

针对性回归为 13 项，全部通过。随后执行完整 `python -m pytest -q`，193 项全部通过。静态检查与编译也通过：

```powershell
python -m ruff check src/llm_structured/barrier.py src/single_channel/complex_chain/preemptive/solver.py src/muti_channel/preemptive/solver.py experiments/preemptive/stage4e_barrier_evaluation.py
python -m py_compile experiments/preemptive/stage4e_barrier_evaluation.py
```

## 可复现实验入口

- [stage4e_barrier_evaluation.py](/D:/Code/SimAI/DAG_heuristic/experiments/preemptive/stage4e_barrier_evaluation.py)
- [最终逐样例数据](/D:/Code/SimAI/DAG_heuristic/docs/result_docs/stage4e_barrier_evaluation_v2_20260822.json)

该 runner 在子进程中执行冻结验证和中图探针，记录 hard timeout、峰值内存、trace 可行性、fallback 与 feature runtime；不会把 timeout 从分母删除。
