# 可抢占主线迁移与实现结果（2026-08-15）

## 1. 结论

本轮已按 `outline.md`、`simulator.md`、代码审查和详细修改计划完成 M0--M6 的迁移与正确性修复，并完成 M7 中不改变算法结果的最小架构整理。communication 可暂停恢复的 v2 现在是 active mainline；不可抢占 v1 作为 maintenance baseline 保留，历史 v1 benchmark、reference 和数值未改变。

核心合同现在统一为：finish-to-start DAG；ready compute 自动、连续、可并行执行；communication 仅在 task event 处零开销暂停恢复；存在 eligible communication 时禁止 voluntary WAIT；多资源动作必须是 inclusion-maximal compatible set；无 eligible 时的空闲由模拟器自动推进，属于 forced idle。

## 2. 迁移结果

### M0：目录和公开合同

- 单通道公共事件状态机迁入 `src/core/execution/preemptive.py`，独立回放迁入 `src/core/trace/preemptive.py`。
- v2 场景入口拆为：
  - `src/single_channel/parallel_chain/preemptive/`；
  - `src/single_channel/complex_chain/preemptive/`；
  - `src/muti_channel/preemptive/`。
- v1 通过对应 `nonpreemptive/` sibling package 暴露，registry 标记为 `maintenance`；v2 registry 标记为 `active`，身份包含 semantics、scenario、family 和 algorithm name。
- repetition 和 multi-job 实现迁入 `src/llm_structured/`；实验 runner 迁入 `benchmark_generate/studies/preemptive/`。
- `src/preemptive/` 保留一个兼容周期的 import/CLI shim，不再承载新的核心逻辑。
- parallel-chain 入口会独立验证节点入度/出度，不接受一般 fork/join DAG；其算法当前复用经过验证的公共事件引擎，为后续链状态压缩保留边界。

### M1：输入与动作验证

- 单通道 `legal_actions()` 在 eligible 非空时只返回 `RUN`；只有无 eligible 且 compute 活动时才返回 forced `WAIT`。
- 单通道和多资源非法动作现在使用稳定的 `IllegalActionError` / `DeadlockError`，错误包含 time、action、eligible 和 active compute。
- 多资源 `legal_actions()` 与 `step()` 使用同一 maximal compatible-set 合同；拒绝 voluntary WAIT、非 maximal 子集、重复 ID、非稳定排序、未知通信和资源冲突。
- 单/多资源核心都拒绝 duration 小于等于 0 的 communication。
- v2 schema、规范化内部模型、validator、generator 和 64 个 benchmark 统一为 `optional_idle=false`。loader 仅为迁移兼容接受早期 v2 文件中的 `true`，并立即规范化为 `false`；该字段表示禁止 scheduler 主动等待，forced idle 仍由模拟器自动发生。

### M2--M3：独立 Trace 与回放

- 单通道 validator 不调用状态转移，也不信任 `final_state.completed_at`；它从 DAG 和 intervals 独立重建 service、开始/完成时间、依赖、单通道排他、事件序列、transition 链、makespan 和 final state。
- 删除 events、删除 transitions、改变 kind、少/多服务、拆分 compute、提前执行等故障均有负面测试。
- 多资源 `MultiResult` 新增完整 `MultiTrace`：decision interval、task interval、start/pause/resume/complete event、resource interval、forced-idle interval 和 final state。
- 多资源独立 validator 检查完整固定资源同时获取、共享资源排他、暂停释放、恢复原资源集、每个决策点 maximal、服务守恒、依赖、compute 连续性和 makespan。

### M4--M5：独立 Oracle 与测试边界

- 新增 test-only 整数 tick exhaustive Oracle；它不导入事件 `step()`，逐 tick 自动推进 compute，并分别枚举单通道动作和多资源 maximal compatible set。
- 固定 seed 的 20 个单通道极小随机 DAG、12 个多资源极小随机 DAG与事件 Exact 全部一致。
- 增加 task 输入顺序不变性、parallel-chain 结构拒绝、动作合法性和 Trace 故障测试。
- SimAI repetition/ZB 测试移到 `tests/integration/`；`pyproject.toml` 增加 `integration` extra。纯 v2 单元测试不再因可选 SimAI 导入而收集失败。

### M6：benchmark、reference 和实验产物

- 保持 139 个 benchmark：v1 75 个，v2 64 个。
- reference 从 54 个增至 66 个：v1 33 个保持不变，v2 从 21 个补至 33 个。
- 34 个 v2 adversarial 中只有 `pm_fixed_beam_counterexample` 在 `100000 states / 5 s` 固定预算内超时，因此不写伪 optimum sidecar。
- `benchmark/index.jsonl`、全部 v2 benchmark hash、reference hash 和 README 计数已同步。

## 3. 回归与实验结果

### 测试

- `python -m pytest -q`：76 passed，0 failed。
- benchmark loader/index/hash/reference 重算测试：通过。
- v2 CLI `preemption_unlock + longest_tail`：makespan 15。
- v1 CLI `random_join_30 + longest_tail`：makespan 24；其历史 Exact reference 仍为 22，未因迁移改变。
- `git diff --check`：通过。
- 当前环境未安装 `ruff` 模块，因此没有把 lint 结果伪装为已执行；pytest、独立 replay 和双 Oracle 是本轮 correctness gate。

### 阶段 0--4

Exact 预算为 `150000 states / 5 s`。得到 48 个单通道和 14 个多资源 Exact；跳过 `pm_fixed_beam_counterexample` 与 random 类的 `pm_random_chain_6`。

| 算法 | 图数 | mean ratio | max ratio | optimal rate | mean runtime |
|---|---:|---:|---:|---:|---:|
| 单通道 Longest-tail | 48 | 1.015809 | 1.212121 | 83.33% | 2.29 ms |
| 单通道 Rollout-2 | 48 | 1.000000 | 1.000000 | 100% | 14.65 ms |
| 多资源 Longest-tail-pack | 14 | 1.006614 | 1.055556 | 85.71% | 3.79 ms |
| 多资源 Set-Rollout-2 | 14 | 1.002646 | 1.037037 | 92.86% | 13.45 ms |

这些是当前机器、有限样本的 observed 指标，不是理论保证。`longest_delay` 已明确为 `longest_tail` 兼容别名，并从实验表中移除，避免重复计为独立算法。

### 阶段 5

- periods 1/2/4/8/16：Exact 为 2/4/8/16/32；Independent-copy 为 2/5/11/23/47；Boundary-aware 为 2/4/8/16/32。
- replicas 3/4/5/6/7：makespan 为 11/14/17/20/23；对称 Exact 状态数为 16/38/73/126/203；普通 Exact 状态数为 66/501/3163/18134/99207。
- 因此“局部周期最优不可机械复制”和“严格自同构状态商保持最优值”继续成立。该结果只覆盖合成固定 motif，不代表未重跑的真实 AICB/ZB workload。

### 阶段 6

- 40 个双 Job 小图：Exact-K1 mean/max ratio 1.005952/1.071429，optimal rate 90%；Exact-K2、Rollout-K2、Semantic-K2 和 Adaptive-K 在该有限集合上为 100%。
- teacher candidate recall K=1/2/4：87.04% / 99.83% / 100%。
- weighted-JCT probe 继续证明 makespan 与 weighted JCT 不能混用：`weighted_short` 中 makespan-optimal 轨迹的 weighted-JCT ratio 为 4.0625。
- 历史“多资源 top-1 候选隐藏 compatible flow，K1/K2/Exact=25/18/18”不再是合法 v2 结果。收紧核心后 candidate width 只控制排序候选，提交动作会补齐 maximal set；K1、K2、flat 和 Exact 均为 18，首动作均为 `A::private + B::shared`。旧 25 依赖模拟器接受非 maximal action，应撤销而不是继续引用。

## 4. 产物

- `preemptive_stage0_4_20260815.json`：阶段 0--4 逐实例结果与汇总。
- `preemptive_stage5_20260815.json`：合成重复结构和对称压缩结果。
- `preemptive_stage6_20260815.json`：40 个双 Job、objective probe 和修正后的多资源 probe。
- `preemptive_migration_manifest_20260815.json`：base commit、环境、命令、seed、预算、benchmark/reference/test 计数。

## 5. 保留边界和后续事项

- `src/preemptive/` compatibility shim 尚未删除；应在一个明确兼容周期后移除，并在此之前禁止新代码依赖旧路径。
- v1 的实际实现文件仍保留在 family 根目录，新的 `nonpreemptive/` 为明确 maintenance 入口。若下一轮物理移动 v1，实现只能做 import/path 迁移，必须继续保持全部 v1 reference 不变。
- 多 Job 目前仍通过规范化联合 DAG 表示 arrival/release；显式 workload/job-arrival 事件层属于后续扩展。
- 本轮没有新增真实 `real` v2 benchmark，也没有修改 SimAI 子模块；因此不能新增真实 LLM workload 性能结论。
- runtime 只用于当前 Windows/Python 3.13.13 环境量级比较；不与旧机器运行时间做逐字等价声明。
