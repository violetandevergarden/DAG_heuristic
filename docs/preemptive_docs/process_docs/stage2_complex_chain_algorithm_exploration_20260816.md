# Stage 2 一般 DAG 算法探索记录

> 后续定位修正：Beam 只保留为实验上界/对照，非部署候选，不主张鲁棒性；不再把穷尽 fixed-width Beam-8 反例作为阶段退出条件。

日期：2026-08-16

## 1. 基础 priority 的冻结定义

本轮冻结以下互不等价的定义，全部基于当前 residual state，tie-break 均为稳定 task ID：

- FIFO：communication 第一次进入 eligible 集合的事件时刻；暂停后保留首次 arrival。
- SPT/LPT：当前 remaining communication work。
- Longest-delay：假设候选完成后，立即新 ready 的正 work task 总量；零时长 compute 按公共 simulator 的自动 closure 展开；多个新 ready task 以 sum 聚合，再以 exclusive tail 打破平局。
- Longest-tail：候选完成后的最长 residual downstream path，不含候选自身 remaining。
- LRPT：包含候选自身 remaining 的最长 residual path。
- Join-aware：直接 child 是 join、且其他 predecessor 均完成时，使用该 child residual tail 作为 direct-last-blocker gain；随后以 Longest-tail 打破平局。

成对测试已构造一个 fork-release 图，使 Longest-delay、Longest-tail、LRPT 分别首选三个不同 communication；另有 direct join 图使 Join-aware 与 Longest-tail 首选不同。

## 2. 结构特征消融结论

Direct-last-blocker 是可观察特征，但不能单独升级为主 priority。在排除 7 个 Stage 1 compatibility 图后的 38 个 Exact 已解一般 DAG 上：

| Priority | optimal rate | mean ratio | observed max |
|---|---:|---:|---:|
| Longest-tail | 84.21% | 1.010315 | 1.095238 |
| Longest-delay | 78.95% | 1.013879 | 1.111111 |
| LRPT | 78.95% | 1.014729 | 1.100000 |
| Join-aware | 76.32% | 1.013806 | 1.100000 |

因此“当前是直接 join 的最后阻塞者”有时有用，但会过度提升局部 barrier，忽略更远的 critical compute 或未来 channel demand。它适合进入 Rollout shortlist 以增加候选多样性，不适合作为未经反事实评价的首要字典序字段。release gain 也存在类似问题：立即释放 work 不等于端到端边际收益，shared downstream 和 join slack 会改变其价值。

本轮未把 fork breadth、join distance/slack、critical-path multiplicity、shared-downstream 去重和 downstream communication demand 混成加权分数。它们需要各自的目标反例与独立消融，避免在当前小集合上调权重。

## 3. Rollout

新的 Rollout 明确区分：

- `top_k`：2、4 或 all；
- `depth`：1、2、3，只计 communication decision，不计 forced idle；
- candidate mode：Longest-tail、LRPT、Join-aware、Hybrid；
- completion priority：默认 Longest-tail；
- deterministic node-expansion budget 与 wall-clock budget；
- budget fallback、expanded nodes 和 evaluated candidates。

有限 shortlist 总是显式保留 completion baseline 的首选动作。因此未耗尽预算时，候选评价至少包含 baseline continuation；预算耗尽后也返回 baseline incumbent，并把结果标记为 fallback，而不是伪装成完整搜索。

固定 seed `26081622` 的 layered general-DAG 搜索找到 index 129：

| 方法 | makespan |
|---|---:|
| Exact | 21 |
| Longest-tail | 23 |
| Rollout top-2 depth-1 | 22 |
| Rollout top-4 depth-1 | 22 |
| Rollout top-2 depth-2 | 21 |

该图已经固定为 `pm_stage2_rollout_depth`。它证明“扩大候选数”和“增加决策深度”不是同一参数：depth-1 即使扩大到 top-4 仍看不到跨两个决策后才兑现的 join 投资，depth-2 才闭合 gap。

正式 38 图一般 DAG 子集上，top-2 depth-1 为 37/38 observed optimal；唯一 gap 即上述反例，ratio 为 `22/21 = 1.047619`。top-2 depth-2、depth-3、top-4 depth-2、Join/Hybrid depth-2 在当前已解集均为 38/38。该结果只说明 depth-2 是当前更强基线，不构成一般 DAG 最优性结论。

## 4. Beam

Beam 使用与 normalized Exact 相同的 key，并按“相同 normalized state 保留较早时刻”做 time-dominance。新增：

- width；
- communication-decision horizon；
- node/time budget；
- Longest-tail incumbent safeguard；
- duplicate、expanded nodes、evaluated candidates 和 fallback 统计。

Width-8 full horizon 和 width-8 horizon-3 在当前 38 图均命中 Exact；horizon-3 平均运行时间约 19.7 ms，full horizon 约 90.2 ms。当前 benchmark 仍没有击穿 fixed width=8；这应解释为待搜索的反例空缺，而不是 Beam-8 的正确性保证。

## 5. Exact 可解边界的第一版观察

45 个仓库 Stage 2 图在 `500,000 states / 10 s` 预算下全部返回 optimal。Exact 平均探索约 279 states，最大 4,471；平均 solver runtime 约 331 ms，最大约 5.74 s。最难的三个图仍是旧 `random_join` 类实例，说明节点数本身不能描述难度，eligible communication 数、join overlap 和近似对称分支更关键。

本轮矩阵仍不足以给出完整 scaling boundary：layered fixed suite 规模较小，且没有独立扫描 width/depth/fork density/barrier layers 的 solved-fraction 曲线。后续应在运行时生成规模矩阵，不继续无限提交 JSON。

## 6. Benchmark 与实验纪律

新套件包含：

- 7 个 Stage 1 compatibility，仅单列附表；
- 20 个 legacy structural regression；
- 5 个解释性 structural adversarial；
- 10 个参数化 layered general random；
- 3 个审计过的 LLM structured motif。

三个 structured motif 把每个 communication 节点解释为一个可暂停/恢复的逻辑 transfer，并把所有 transfer 投影到一个 unit-capacity channel。它们是结构保持的 synthetic motif，不是测量 trace，也不声称真实 collective 任意内部粒度可抢占。

结果按 structure group 分层。Exact 未完成时不得进入 optimal-rate 分母；本轮正式 10 秒矩阵为 45/45 完成。reference sidecar 为 44/45，缺失的 `pm_complex_random_009` 在 reference 固定 5 秒预算内未完成，但在正式 10 秒预算内以 4,471 states、约 5.74 秒完成；没有用正式实验结果反向伪造 5 秒 reference。

## 7. 当前不能声称的结论

1. 不声称 Longest-tail、Join-aware、Rollout depth-2 或 Beam-8 在一般 DAG 上有新的近似比。
2. 不把 38/38 observed optimal 外推到更大、更宽或更深 DAG。
3. 不把 direct-last-blocker 的退化解释成 join 信息无用；只能说明该局部定义不足。
4. 不把 synthetic LLM motif 当作真实训练 workload 性能证据。
5. 不沿用 Stage 1 的链 compact key、链对称或 2-bound。
