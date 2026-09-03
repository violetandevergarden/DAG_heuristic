# Stage 4 运行成本诊断与优化结果

日期：2026-09-02

## 已落地产物

- 冻结 8 个中图及其内容哈希：`experiments/llm_structure/nonpreemptive/manifests/stage4_foundation/runtime_cases.jsonl`。
- 新增统一硬预算 runner：`experiments/llm_structure/nonpreemptive/stage4_runtime_breakdown.py`。
- `bare`、`validated`、`instrumented` 均使用同一公共不可抢占状态机和同一动作摘要；`bare` 不重放 trace，`validated` 重放并验证，`instrumented` 额外统计合法候选和简单策略分歧。
- 分项记录加载/转换、策略与状态转移、trace 重放和验证，并记录峰值内存。子进程显式继承仓库 `src`，避免导入失败被误记为 timeout。
- depth=0 和 barrier LT 已在前一轮收尾中改为直接走公共基础 LT，不再构造未使用的 rollout/barrier 特征。

## 实测证据

本轮先完成 918-task 单 channel 的一次 30 秒诊断，原始数据位于 `stage4_runtime_diagnosis_20260902/results.jsonl`。这是入口验收，不冒充计划要求的 8 case × 3 次完整矩阵。

| 路径 | makespan | 动作摘要 | 策略/转移 | 重放/验证 | 总时间 | 峰值内存 |
|---|---:|---|---:|---:|---:|---:|
| bare | 2,178,018 | `316d9b…2d32` | 5.710 s | 0 | 5.762 s | 2.31 MB |
| validated | 2,178,018 | `316d9b…2d32` | 5.708 s | 2.036 s | 7.796 s | 8.87 MB |
| instrumented | 2,178,018 | `316d9b…2d32` | 23.740 s | 3.658 s | 27.452 s | 8.87 MB |

三条路径的 makespan 和动作摘要一致。instrumented/validated 总时间为 3.52 倍；额外成本主要来自每个决策重复构造候选并计算 FIFO、固定顺序和 LT 分歧，而不是基础状态转移。按计划停止继续改写公共模拟器，后续应优化观测器。

## 门槛判断

- F0 的入口、清单、硬预算和分项统计已建立。
- 918-task validated 低于 10 秒；但 640/838/2038 的三次重复矩阵本轮未执行，不能宣称 P1 的全部机器性能门槛通过。
- 30 秒超时已能区分为硬子进程预算，并可由分项定位；当前样例说明 instrumented 路径本身足以把可完成的基础 LT 推近 30 秒。
- 未修改 WAIT、通信连续执行、active reservation、Exact 状态空间或 trace 验证语义。

