# Stage 1 后续审查项处理记录

日期：2026-08-16

## 本轮立即修正

1. residual tail 从“每候选一次完整拓扑遍历”改为“每决策事件一个 immutable snapshot”；候选 key 只查表。FIFO/SPT/LPT/Longest-delay 不计算 tail。
2. compact frontier future-equivalence、同构链 multiset 压缩及 Beam 时间支配分别形成书面证明，见 `stage1_parallel_chain_compact_state_proof_20260816.md`。
3. preemptive registry entry 中会被 `_active_v2` 覆写的 `semantics`、`development_status`、`supports_wait=False` 已删除；canonical active-v2 字段只在 `_active_v2` 一处设置。
4. Rollout 增加显式 depth；正式矩阵加入 top-4/depth-1 与 top-2/depth-2，用于分离候选数和搜索深度贡献。
5. compact Exact 增加相同 `(kind,duration)` 链的对称 multiset key，并采用 value-DP 后按实际 ID 重建最优 trace。

## 保留到 Stage 2 的遗留

- complex-chain registry 的 `longest_delay` 当前仍是 Longest-tail 兼容别名，其描述只适用于该尚未复核的实现；不能据此解释 Stage 1 的独立 Longest-delay。
- complex-chain registry 仍保留 `monte_carlo64`。Stage 1 已将 Monte Carlo 从正式矩阵移除；Stage 2 审查时再决定其历史命名空间和维护状态。

本轮不借 Stage 1 优化修改 complex-chain 算法定义，以免在 Stage 2 语义审查前混入未经验证的行为变化。
