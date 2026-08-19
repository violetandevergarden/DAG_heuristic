# Stage 1 parallel-chain 代码实现结果

日期：2026-08-16

> 增补说明：本报告保留首次代码基线。缓存优化、depth-2 rollout、相同链对称压缩和 registry 清理由 `stage1_parallel_chain_continued_implementation_result_20260816.md` 续记；后者为当前工程状态。

## 1. 范围

本报告只记录 `single_channel/parallel_chain/preemptive` 的代码维护与工程验收。算法效果、理论结论和实验观察另见 `stage1_parallel_chain_research_result_20260816.md`；逐例机器可读结果见 `stage1_parallel_chain_experiment_20260816.json`。

实现遵循以下边界：公共 `PreemptiveDAGModel` 仍是时间推进、compute 自动启动、通信暂停/恢复和动作合法性的唯一实现；parallel-chain 模块只解析 family 契约、从合法通信中选择动作，并搜索公共转移产生的状态。未改写不可抢占、complex-chain 或多 channel 状态机。

## 2. 已完成的代码维护

### 2.1 中立 ParallelChain 契约

新增 `src/single_channel/parallel_chain/model.py`：

- 将输入无损解析成互不相连的简单路径，不合并或静默 normalization；
- 严格要求 compute/communication 交替；
- 允许任一类型开始或结束；
- 允许零时长 compute，拒绝非正 communication work；
- 拒绝 fork、join、跨链合并和非根路径分区；
- 保留 task ID，并提供 task 到 chain/frontier position 的稳定映射。

`src/benchmark/validator.py` 同步增加公开 benchmark 的交替性语义校验。family interface、solver、Loader/Validator 对同一非法结构给出一致拒绝。生成器改为从中立 family model 导入 `ParallelChain`，不再从不可抢占 solver 获取当前生成所需的数据结构。

### 2.2 Stage 1 policy 定义冻结

`src/single_channel/parallel_chain/preemptive/solver.py` 不再把 Stage 1 priority/Exact 全部转发给 general DAG solver。当前定义为：

- FIFO：按首次进入 eligible 集合的事件时间，ID 稳定同分；暂停后保留首次 arrival；
- SPT/LPT：按当前 communication remaining work；
- Longest-delay：当前 communication 完成后立即解锁的下一段 compute duration；若以 communication 结束则为 0；
- Longest-tail：当前 communication 完成后的 residual downstream tail，不含当前 communication remaining；
- LRPT：包含当前 communication remaining 的 residual path；
- Rollout-2：按 Longest-tail 生成 top-2 shortlist，强制保留 baseline 首选动作，以 Longest-tail 补全；`candidate_mode="lrpt"` 是显式替代配置，旧的模糊 `"tail"` 名称被拒绝；
- Beam-8/32：用 compact key 去重，Longest-tail 为 incumbent/completion policy。

所有策略均使用公共 model 的 `legal_actions/step/run`，没有主动 WAIT 候选。

### 2.3 compact chain-specific Exact

新增 Stage 1 专用 Exact：

- 每条链只保存第一个未完成 frontier 的位置和剩余工作；
- 完成前缀和未来 pending 后缀由严格路径结构唯一确定；
- 绝对时间、started timestamp、eligible communication 是否曾执行过，在零恢复开销且目标只依赖未来完成时间时不影响未来，因而从 key 中安全移除；
- 实际转移和最终 action path 仍由公共 simulator 产生；
- 使用 residual `max(P,Q,L)` 下界、Longest-tail 可行 incumbent、memoization、重复 key 去重和安全剪枝；
- 返回 `status=optimal`、explored/deduplicated/pruned states、lower bound 和 runtime；timeout/state-limit 继续抛出明确异常，不生成 optimal result。

Exact 结果再次通过独立 trace validator 回放。

### 2.4 registry 与稳定入口

parallel-chain 可抢占 registry 现在只公开已有独立定义和测试的：

`fifo`、`spt`、`lpt`、`longest_delay`、`longest_tail`、`lrpt`、`rollout2`、`beam8`、`beam32`、`exact`。

与 Stage 1 无关的 `join_rollout2` 已从该 family 移除；Monte Carlo 只保留为未注册 historical 函数。complex-chain registry 未借机收紧。

### 2.5 benchmark、reference 与实验入口

- 13 个历史 adversarial 文件保留路径，但补充 attack target、historical origin、当前语义角色和机制说明；WAIT 来源样例明确降为 legacy regression，而不是当前主动 WAIT 反例；
- 保留 10 个固定 seed random；
- 新增 3 个 structured 和 2 个 LLM pipeline pattern projection，规范 category 仍为 `real`，由 `metadata.stage1_group` 分成 `structured` 与 `real_projection`；projection 明确声明未表示 fork/join/cross-chain dependency，不声称与一般 LLM DAG 等价；
- benchmark 总数从 139 增至 144，index 和路径迁移审计 hash 已同步；
- Stage 1 reference 现覆盖 12 个可解 adversarial、9 个可解 random 和 5 个 structured/real-projection；两个预算内 timeout 样例没有 optimal sidecar；
- `benchmark_generate reference` 新增 `--category adversarial|random|real|all`；
- 新增薄 runner `experiments/preemptive/stage1_parallel_chain.py`。它只调用稳定 family 入口，输出逐例 path/hash、category/group/seed、算法参数、revision/dirty 状态、Exact 状态与搜索规模、runtime、ratio、preemption、forced idle 和 utilization，再从逐例数据派生分组汇总；
- `stage0_4.py` 遇到 parallel-chain 时也改经稳定 family 入口，不再绕到 general solver。

## 3. 测试与验收

新增/扩展测试覆盖：

- compute/communication 任意起止、零 compute；
- 连续 compute、连续 communication、fork/join、零 communication work 的拒绝；
- benchmark validator 与 family parser 一致；
- FIFO 首次 eligible 和暂停后 arrival 保留；
- Longest-delay、Longest-tail、LRPT 的可区分首选动作；
- Rollout shortlist 名称、确定性和非法旧名称；
- 200 个固定 seed 严格交替小图：compact Exact、通用 event Exact、独立 tick Oracle 三方 makespan 完全一致，并逐例通过独立 trace replay；
- Stage 1 runner 的逐例审计字段和 grouped summary。

最终验证：

```text
python -m pytest -q
94 passed in 27.38s

python -m ruff check <本次涉及的 Python 文件>
All checks passed!

git -c core.safecrlf=false diff --check
passed
```

## 4. 尚未关闭的工程边界

- `pm_fixed_beam_counterexample` 和 `pm_random_chain_6` 在 500,000 states / 10 s 的正式实验预算下 timeout；它们没有被标成 optimal，也没有 reference sidecar。
- compact key 已做固定小图交叉验证，但本轮没有实现同构链计数压缩、peak-memory 采集或外部 CP-SAT/MILP Oracle。
- 当前 structured/real-projection 是 Stage 1 结构证据，不是 SimAI 原始 workload 的等价缩减证明。

因此本轮完成了 Stage 1 可维护、可审计的代码基线；上述边界保留给后续 Exact scaling 和真实投影验证，不应被隐藏在成功率统计中。
