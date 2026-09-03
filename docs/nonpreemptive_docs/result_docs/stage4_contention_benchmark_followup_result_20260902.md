# 不可抢占 Stage 4 竞争与 benchmark 第二轮结果

日期：2026-09-02

## 竞争审计

E4 已完成。38 个当前 Stage 4 benchmark 分别按 optional-idle 和 work-conserving 审计，共 76 个 case×mode；全部在“最多 128 个决策或 30 秒”双门槛内稳定结束，0 timeout，其中 60 个完整回放、16 个因决策上限停止。

四层冲突彼此独立：

| 层次 | 状态数 | 涉及 case×mode |
|---|---:|---:|
| 动作冲突 | 1101 | 67 |
| 简单策略分歧 | 720 | 66 |
| immediate successor 分歧 | 1101 | 67 |
| 已有 Exact 质量冲突 | 89 | 26 |

质量层来自按 benchmark hash、mode、decision index 和 state hash 接入的既有 exact 标签，不是本轮根据动作差异推断。243 个既有标签中，94 个标签、23 个 benchmark 有非零 action value spread，最大 3636；LT regret 为正的标签仍为 0。

多资源审计先读取 active reservation 和剩余空闲资源，再以 8 种简单策略构造完整合法启动集合。高 ready 数时不调用完整幂集枚举；仅在 startable≤10 且预计集合数不超上限时枚举，并记录 `enumeration_skipped`。当前正式集只有 2 个 routed 中图（两个 mode 共 4 行），没有观察到多资源质量冲突或足够的 active-reservation 集合分歧，因此 4c 继续受限。

## staging 多作业压力图

E5 在 staging 构造了 8 个可追溯组合：2/4-job、同构/异构、同时到达和按单 job validated LT makespan 的 10%/25%/50% 错峰；其中 6 个单 channel 组合在 90 秒内完成独立 trace 验证，规模 1282--2564 task，运行 4.24--16.76 秒。两个 4078-task routed 组合也通过 trace 验证，但耗时 119.11--121.31 秒，超过冻结的 90 秒准入预算，只作为 over-budget 诊断，不作为质量实验。

组合图均保留 job 命名空间、父图 hash、冻结 arrival、各 job completion/JCT，并标记 `staging_only`。没有跨 job 依赖；竞争只来自共享固定资源。审计观察到大量动作和策略分歧；routed 同时到达样例观察到 set choice。主 census 的组合图质量字段仍为 `not_run`；随后另对两个单 channel 组合的首个策略分歧状态逐一执行了所有合法首动作加同一冻结 LT completion，所有完整 trace 合法，但两个状态的 value spread 都为 0，不能据此声称 LT 出错或算法有收益。

DP=2/4 因 E3 的 builder 约束保持 `not_supported`。带宽投影和 route 重写没有在缺少逐项 SimAI 对拍的情况下人工生成。新 residual window 也未发布：既有小图虽有 value spread，但 LT regret 全为零；两个已检查的组合中图分歧状态连冻结 completion value spread 也为零，尚无状态同时满足首动作集合、LT 排名、下一真实事件和 value 排序保真条件。拒绝记录及逐动作结果见 `stage4_hard_slices_20260902/`。

## E5 与 4b--4f 再准入

E5 得到的是“有限正面输入 + 否定算法证据”：已形成来源可追溯、LT 可运行且有动作/策略冲突的组合中图，既有小图也有非零 value spread；但没有发现稳定 LT regret，且没有足够覆盖形成 development/validation/holdout 三组困难输入。因此不宣称 E5 的完整正面退出，也不把未执行变量写成覆盖充分的完整否定结论。

- 4b：具备继续解释“value spread 非零但 LT 正确”的条件。
- 4c：不具备重开复杂 packing 的条件；真实 routed active-reservation 质量分歧不足。
- 4d：不具备重训/冻结 selective trigger 的条件；LT regret 仍为零。
- 4e：只保留为 LT 修正或触发信号，不恢复 barrier-only。
- 4f：优先级最高；已有冻结 arrival、per-job JCT 和 staging 组合，但仍需独立目标基线与 holdout 后才能形成收益结论。
- 4g：不进入。

对应原始产物为 `stage4_contention_census_v2_20260902/`、`stage4_real_composed_stress_20260902/` 和 `stage4_hard_slices_20260902/`。现有正式 benchmark、index 和 reference result 未被修改。
