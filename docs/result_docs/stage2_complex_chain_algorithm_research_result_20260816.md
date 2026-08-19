# Stage 2 一般 DAG 算法研究结果

> 后续定位修正：Beam-8/32 仅为实验上界和对照，不是部署候选，不主张鲁棒性，固定宽度反例未穷尽且不再继续搜索。大图评价以 LT→Rollout 的 primal 改善为主，lower bound 只用于 `[LB,best feasible]` 知识区间。

日期：2026-08-16

## 1. 研究问题与数据边界

本报告只研究单 channel、单个联合一般 DAG、communication 在 task event 可暂停/恢复、compute 自动且不可抢占、零切换开销、无主动 WAIT、最小化 makespan。

正式套件共 45 图。一般 DAG 主汇总排除 7 个无 fork/join 的 Stage 1 compatibility 图，因此主算法分母为 38；compatibility 结果单列。38 图包含 20 个 legacy structural regression、5 个新 structural adversarial、10 个 layered general random、3 个 LLM structured motif。

Exact 预算为 `500,000 states / 10 s`，45/45 返回 `optimal`。44 图有固定 `100,000 states / 5 s` reference sidecar；`pm_complex_random_009` 在 5 秒 reference 预算内未完成，因此不生成 sidecar，但正式 10 秒运行在约 5.74 秒完成。

原始逐例结果：

- `docs/result_docs/stage2_complex_chain_experiment_20260816.json`

## 2. Exact 第一版边界

| 指标 | 结果 |
|---|---:|
| solved | 45/45 |
| mean explored states | 279.04 |
| max explored states | 4,471 |
| mean solver runtime | 331.41 ms |
| max solver runtime | 5,736.85 ms |
| mean lower-bound prunes | 88.18 |

最难的三个图为 `pm_complex_random_009`、`pm_complex_random_008`、`pm_complex_random_001`，探索 4,471、3,251、2,280 states。节点数不是充分难度指标；eligible communication 数、join overlap、barrier 层次和近似对称分支需要进入后续 scaling 横轴。

当前边界仍偏小，不能据此认为一般 DAG Exact 可扩展到中图。下一轮应运行时扫描 width/depth/fork/join 密度，而不是继续增加固定 JSON。

## 3. 基础 priority

一般 DAG 主集合 38 图结果：

| 算法 | observed optimal | mean ratio | P95 ratio | observed max |
|---|---:|---:|---:|---:|
| Longest-tail | 84.21% | 1.010315 | 1.090909 | 1.095238 |
| Join-aware | 76.32% | 1.013806 | 1.090909 | 1.100000 |
| Longest-delay | 78.95% | 1.013879 | 1.095238 | 1.111111 |
| LRPT | 78.95% | 1.014729 | 1.095238 | 1.100000 |
| SPT | 65.79% | 1.028256 | 1.210526 | 1.222222 |
| FIFO | 63.16% | 1.037470 | 1.214286 | 1.222222 |
| LPT | 39.47% | 1.090519 | 1.300000 | 1.625000 |

结论：

1. residual Longest-tail 仍是当前最强、最简单的 completion baseline。
2. Immediate release gain 没有稳定胜过 residual tail；局部释放 work 会忽略 join slack、shared downstream 和未来 channel demand。
3. Direct-last-blocker Join-aware 在目标图上可改变决策，但总体略差于 Longest-tail。它适合作为候选多样性，不适合作为未经反事实评价的主 priority。
4. LRPT 把候选自身 remaining 纳入 path，在部分图中会过度偏向大通信；它和 Longest-tail 必须保持独立名称与统计。

## 4. Rollout 的主要新结论

固定反例 `pm_stage2_rollout_depth`：

| 算法 | makespan | gap |
|---|---:|---:|
| Exact | 21 | 0 |
| Longest-tail | 23 | +2 |
| Rollout top-2 depth-1 | 22 | +1 |
| Rollout top-4 depth-1 | 22 | +1 |
| Rollout top-2 depth-2 | 21 | 0 |

这是本轮最明确的算法结论：增加 `k` 只扩大当前候选集合，增加 `depth` 才能观察跨多个 communication decision 的 barrier 投资。两者不能合并成“搜索更大”一个参数。

一般 DAG 38 图：

| 算法 | observed optimal | mean ratio | observed max | mean runtime |
|---|---:|---:|---:|---:|
| top-2 depth-1 | 97.37% | 1.001253 | 1.047619 | 9.64 ms |
| top-2 depth-2 | 100% | 1.000000 | 1.000000 | 14.61 ms |
| top-2 depth-3 | 100% | 1.000000 | 1.000000 | 20.06 ms |
| top-4 depth-2 | 100% | 1.000000 | 1.000000 | 22.30 ms |
| Join top-2 depth-2 | 100% | 1.000000 | 1.000000 | 14.48 ms |
| Hybrid top-4 depth-2 | 100% | 1.000000 | 1.000000 | 22.76 ms |

在当前套件上，top-2 depth-2 是更合适的默认研究基线：它修复唯一 depth-1 gap，平均开销低于扩大 k 或增加到 depth-3。该选择是经验性基线，不是最优性或近似界。

Join/Hybrid shortlist 没有改善 top-2 depth-2 的 makespan，因为后者已经全中；这不能证明 join 信息无用，只说明当前集合无法区分这些 depth-2 variants。下一轮需要构造 baseline top-2 omission、但 join/slack candidate 能修复的独立反例。

## 5. Beam

| 算法 | observed optimal | mean runtime |
|---|---:|---:|
| Beam width-8 horizon-3 | 100% | 19.74 ms |
| Beam width-8 full horizon | 100% | 90.23 ms |

Horizon-3 在当前 38 图与 full horizon 结果相同，平均运行时间约为后者的 22%。但尚未找到需要超过三个 communication decisions 或会被 width-8 截断的反例，因此不能把 horizon-3/width-8 固化为普适设置。

Beam 的 normalized-key 去重已具备书面 future-equivalence 依据；“相同 key 保留较早时刻”是 time-dominance，而不是仅凭局部形状相似合并。局部相似但外部连接不同的子图不会因 task status tuple 相似而交换 task identity。

## 6. 分层观察

### 6.1 Structural adversarial（5 图）

- Longest-tail：80% optimal，mean 1.01905，max 1.09524；
- top-2 depth-1：80% optimal，唯一 gap 为 depth 反例；
- top-2 depth-2 与 Beam variants：5/5 observed optimal。

### 6.2 General random（10 图）

- Longest-tail：10/10 observed optimal；
- LRPT：80% optimal，max 1.07692；
- Longest-delay 与 Join-aware：各 90% optimal，max 1.03030。

这批 layered random 对 Longest-tail 仍偏容易，后续 generator 应定向提高同时 eligible、join slack 差异与 shared downstream overlap。

### 6.3 Structured（3 图）

所有 priority/search 均为 3/3 observed optimal。样本太少且是 synthetic motif，只能作为结构与执行回归，不能说明 LLM workload 上算法无差异。

### 6.4 Stage 1 compatibility（7 图，附表）

未混入一般 DAG 主分母。Longest-tail 为 85.71% optimal、max 1.125；Rollout/Beam variants 为 7/7 observed optimal。这些结果只验证迁移兼容性。

## 7. 理论结论

本轮确认的安全理论内容只有：

- Stage 1 是 Stage 2 的受限子类，因此 Stage 2 至少继承其困难性方向；
- `P_rem`、`L_rem` 和 `max(P_rem,L_rem)` 是安全 residual lower bound；
- normalized key 在当前无外部时间、零切换成本、纯 makespan 模型下 future-equivalent；
- 相同 normalized state 的较早到达时间支配较晚到达时间。

没有得到一般 DAG 的新常数近似界。Stage 1 的 `P+Q` charging、2-bound、chain frontier 和链对称压缩均未外推。

## 8. 下一步研究计划

优先级顺序：

1. 自动搜索并固化 top-k omission、fixed-width Beam 和 horizon>3 反例。
2. 分别实现 join distance/slack、barrier urgency、shared-downstream 去重和 downstream communication demand；每项先做单特征目标反例与关闭/启用消融。
3. 运行参数化 Exact scaling：nodes/comms、width/depth、fork/join density、barrier layers、eligible peak、duration ratio、近似对称性。
4. 对 lower-bound 做消融，比较无 bound、P、L、max(P,L) 的 states/runtime；再决定是否研究 window bound。
5. 从 SimAI/AICB 生成少量真实 snapshot，并明确 collective 可抢占粒度；不要把当前 synthetic motif 当真实结果。
6. 若 depth-2 在更强攻击集上仍稳定，再研究 adaptive depth/budget，而不是直接增加混合权重。

## 9. 阶段状态

Stage 2 已从“旧 27 图可复现的原型”推进到“contract、Exact、reference、分层 benchmark、独立 runner 和第一批反例闭环可用”。但 fixed-width 反例、结构特征完整消融、scaling boundary 和真实 workload 仍缺失，因此当前状态应记为“Stage 2 第一轮代码修正与算法研究完成”，不能记为“Stage 2 退出条件全部满足”。
