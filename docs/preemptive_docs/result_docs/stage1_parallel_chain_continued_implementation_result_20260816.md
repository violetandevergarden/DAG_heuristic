# Stage 1 parallel-chain 继续实现结果

日期：2026-08-16

## 1. 范围与结论

本轮只继续维护 `single_channel/parallel_chain/preemptive` 及其生成、注册、测试和实验入口，没有修改 Stage 2 的 complex-chain 算法语义，也没有继续推进 nonpreemptive。完成了 residual tail 缓存、可配置 rollout 深度、相同链对称 Exact、registry 字段清理和固定反例固化。

## 2. 性能修正

`schedule_priority`、rollout/beam 的候选排序和补全现在都在一个决策状态上只计算一次 `residual_tail(model, state)`，再把同一份 tail snapshot 传给 `_priority_key`。FIFO、SPT、LPT 和 longest-delay 不再触发无用的拓扑遍历。

回归测试通过 monkeypatch 直接统计调用次数：Longest-tail 每个通信决策一次，FIFO 为零。因而修正的是调用复杂度，而不是依赖单次墙钟时间的偶然加速。

## 3. rollout 深度

`schedule_rollout` 新增显式 `depth`：

- depth 计数通信选择，不把 forced idle 计入深度；
- `depth=1` 与旧 rollout2 trace 完全兼容；
- 新增 registry 算法 `rollout4` 和 `rollout2_depth2`；
- 非正 depth 明确拒绝；
- 递归 residual cost 按 `(depth, ordered compact key)` 记忆化。

固定攻击样例 `pm_rollout_depth_counterexample` 只属于 preemptive 语义，不反向生成 nonpreemptive 副本。其 metadata 记录发现 seed、序号、攻击目标和机制，reference hash 与最优 makespan 47 已生成。

## 4. compact Exact 与对称压缩

Exact 新增 `symmetry_reduction=True`。只有完整 `(task kind, duration)` 序列完全相同的链才分组；组内 frontier 状态以排序多重集编码。搜索改为缓存 cost-to-go，再用原 task ID 按 Bellman 等式重建路径，避免从对称代表状态复用非法 task ID。

Beam 仍使用有序链 key；其同 frontier 只保留最早绝对时间的逻辑已在 docstring 中明确为“时间支配剪枝”，不是普通集合去重。形式证明见 `docs/process_docs/stage1_parallel_chain_compact_state_proof_20260816.md`。

## 5. registry 清理与 Stage 2 边界

`_active_v2` 继续集中写入 `semantics="communication_resume"`、`supports_wait=False`、`development_status="active"`；各 preemptive entry 中会被无条件覆盖的同名字段已经删除，不再保留死配置。

以下问题只记录、不在本轮越界修改：complex-chain 的 longest-delay 仍带过时 alias 注释；complex-chain registry 仍有 `monte_carlo64`。二者在 Stage 2 复核。

## 6. 可复现实验入口

- 正式分层报告：`experiments/preemptive/stage1_parallel_chain.py`
- 相同链规模曲线：`experiments/preemptive/stage1_exact_symmetry_scaling.py`
- 正式 raw：`docs/result_docs/stage1_parallel_chain_experiment_continued_20260816.json`
- 对称曲线 raw：`docs/result_docs/stage1_exact_symmetry_scaling_20260816.json`

正式集合当前为 145 个仓库问题文件，其中 29 个是 Stage 1 preemptive；27 个在 500,000 states / 10 s 内 Exact 完成且都有 hash 匹配的 reference sidecar。`pm_fixed_beam_counterexample` 与 `pm_random_chain_6` 仍明确报告 timeout，不伪装为最优。
