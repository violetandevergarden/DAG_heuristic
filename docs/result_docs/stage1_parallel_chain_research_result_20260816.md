# Stage 1 parallel-chain 研究结果

日期：2026-08-16

> 增补说明：本报告保留首次 Stage 1 基线。其 NP-hardness、rollout 深度和对称压缩结论已由 `stage1_parallel_chain_continued_research_result_20260816.md` 更新；后者为当前结论。

## 1. 实验口径

本轮只研究 preemptive single-channel independent alternating chains，目标为联合 makespan。数据由：

- adversarial 13 个；
- random 10 个（固定 seed）；
- structured 3 个；
- real-projection 2 个。

共 28 个固定样例。Exact 预算为 500,000 states / 10 s；完成 26 个，`pm_fixed_beam_counterexample` 和 `pm_random_chain_6` timeout。所有 ratio、optimal rate 和以下表格都只以 26 个 Exact 完成样例为分母，timeout 没有被当作最优结果或 fallback。

运行 revision 为 `ffea123377c3cd58308899e534f58ffa329917b3`，报告明确记录 `worktree_dirty=true`，因此 revision 只是基线指针，逐例 benchmark hash 与本结果文档对应的工作树才是本轮的完整复现标识。原始逐例数据位于 `stage1_parallel_chain_experiment_20260816.json`。

## 2. 总体结果

| 算法 | Exact 样例数 | mean ratio | P95 | observed max | optimal rate | mean runtime (ms) | mean preemptions | mean forced idle | mean utilization |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| FIFO | 26 | 1.163294 | 1.391304 | 1.863636 | 23.08% | 1.863 | 0.000 | 6.615 | 0.7166 |
| SPT | 26 | 1.164552 | 1.461538 | 1.521739 | 23.08% | 1.876 | 0.346 | 6.423 | 0.7135 |
| LPT | 26 | 1.221087 | 1.800000 | 1.863636 | 11.54% | 1.777 | 0.692 | 7.500 | 0.6825 |
| Longest-delay | 26 | 1.072529 | 1.222222 | 1.300000 | 46.15% | 1.880 | 0.769 | 4.538 | 0.7698 |
| Longest-tail | 26 | 1.016171 | 1.125000 | 1.212121 | 88.46% | 1.810 | 0.615 | 3.654 | 0.8129 |
| LRPT | 26 | 1.023608 | 1.125000 | 1.212121 | 73.08% | 1.823 | 0.846 | 3.808 | 0.8062 |
| Rollout-2 | 26 | 1.000000 | 1.000000 | 1.000000 | 100% | 12.286 | 0.962 | 3.308 | 0.8254 |
| Beam-8 | 26 | 1.000000 | 1.000000 | 1.000000 | 100% | 78.175 | 0.692 | 3.308 | 0.8254 |
| Beam-32 | 26 | 1.000000 | 1.000000 | 1.000000 | 100% | 191.545 | 0.577 | 3.308 | 0.8254 |

运行时间是本机单次观测，不应跨机器直接比较；ratio 和行为指标由同一批逐例结果计算。

## 3. 分组观察

### 3.1 Adversarial（12 个 Exact 完成）

- Longest-tail：mean 1.028093，max 1.212121，optimal 10/12；
- LRPT：mean 1.034922，max 1.212121，optimal 8/12；
- Rollout-2、Beam-8/32：本组 observed 12/12 optimal；
- FIFO 最差为 `pm_tight_optional_wait_m20`，41 vs 22，ratio 1.863636；该文件名来自历史 WAIT 探索，但当前解释是 work-conserving priority regression，不是主动 WAIT 证据；
- Longest-delay 最差为 `pm_lrpt_double_count`，13 vs 10，ratio 1.3；
- Longest-tail 与 LRPT 的 observed 最差均为 `pm_scaled_five_four_s4`，40 vs 33，ratio 1.212121。

### 3.2 Random（9 个 Exact 完成）

- Longest-tail、Rollout-2、Beam-8/32 在这 9 个样例上 observed 全部 optimal；
- LRPT mean 1.012378，max 1.076923；
- FIFO mean 1.111044，SPT mean 1.212523，LPT mean 1.175684；
- `pm_random_chain_6` timeout，未进入上述统计。

### 3.3 Structured（3 个）

- Longest-tail、LRPT、Rollout-2、Beam-8/32 observed 全部 optimal；
- FIFO mean 1.018519；Longest-delay mean 1.047619；
- 样例覆盖对称链、channel-bound 和 compute-bound 三种结构，但数量仍小，只能作为结构化回归，不代表分布统计。

### 3.4 Real-projection（2 个）

- Rollout-2、Beam-8/32 observed 全部 optimal；
- Longest-tail 与 LRPT mean 均为 1.041667，max 1.083333；
- FIFO mean 1.104167；Longest-delay mean 1.083333。

这两个实例是由 1F1B/zero-bubble pipeline pattern 参数化得到的 independent-chain projection。它们没有保留一般 LLM DAG 的 fork/join、collective barrier 或跨链依赖，因此只能支持“候选链抽象值得继续验证”，不能支持端到端适用性声明。

## 4. Exact 观察

26 个完成实例中：

- explored states：平均 324.5，最大 3,678；
- Exact runtime：平均 281.354 ms，最大 3,314.336 ms；
- 重复 compact key 命中合计 3,980 次；
- lower-bound pruning 合计 3,053 次；
- 200 个固定 seed 小图上，compact Exact、通用 event Exact、独立 tick Oracle 完全一致。

这支持“frontier key 在已测 Stage 1 小图上无损且适合作为专用 Oracle”的工程结论，但两个 timeout 表明当前实现仍未覆盖全部固定中小图；本轮也没有给出内存边界或与 CP-SAT 的独立规模曲线。

## 5. 理论结果

已形成当前模型下的可审查记录 `docs/process_docs/stage1_parallel_chain_theory_20260816.md`：

1. 对任意 work-conserving 调度，最后完成链在每个 forced-idle 时刻必有 compute 运行，因此 forced idle 不超过该链 compute 总量，得到

   $$C_H=P+I_H\le P+Q\le2OPT.$$

2. `max(P,Q,L)` 是当前独立交替链模型的安全 lower bound；compact Exact 使用 residual 版本安全剪枝。
3. compute 全为零时任意 work-conserving 调度均以 $P$ 完成。
4. 每链一次、全部通信在 $t=0$ eligible 时，按后续 delivery compute tail 非增排序最优。
5. 多 job 只有在 job 内固定全序、job 间仅通过单 channel 耦合、arrival 可显式编码且目标仍为联合 makespan 时，才可能等价映射为 independent chains。

旧 NP-hardness 规约尚未证明可抢占不改变构造实例最优值，本轮明确将“一般 Stage 1 NP-hard”降级为待审查 conjecture，没有用实验枚举替代理论证明。

## 6. 结论与下一步

本轮最稳健的经验结论是：在当前 26 个 Exact 完成样例中，动态 residual Longest-tail 明显优于简单 FIFO/SPT/LPT，并以约 6–7 倍 Longest-tail 平均运行时间的 Rollout-2 消除了本集合中的 observed gap；更宽 Beam 在该集合没有带来额外质量，却显著增加运行时间。

以下内容不能从本轮推出：

- Rollout-2 或 Beam 具有一般最优性；
- Longest-tail 的一般近似比小于 2；
- 两个 projection 代表一般 LLM training DAG；
- 尚未完成 Exact 的两个样例上的算法优劣；
- 一般 Stage 1 已正式证明 NP-hard。

下一轮研究优先级应为：扩大 compact Exact 可解边界；自动寻找 Rollout-2/固定 Beam 的最小反例；把 Longest-tail/LRPT 反例参数化；从可追踪 workload 生成真正的 real projection 并说明删边/收缩关系；完成当前抢占事件模型下的 NP-hardness 规约审查。
