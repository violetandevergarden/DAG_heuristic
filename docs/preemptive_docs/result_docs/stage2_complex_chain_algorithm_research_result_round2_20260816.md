# Stage 2 一般 DAG 第二轮算法研究结果（2026-08-16）

> **Beam 定位**：Beam-8/32 只作为实验上界和离线对照，不是部署候选，不主张鲁棒性；固定宽度反例没有穷尽，后续不再把搜索 Beam-8 反例作为 Stage 2 退出条件。

## 1. 正式 45 图复跑

45 个仓库 Stage 2 图在 `500,000 states / 10s` 下全部由 Exact 完成；去掉 7 个 Stage 1 compatibility 后，正式一般 DAG 分母为 38。

| 算法 | observed optimal | mean ratio | observed max ratio | mean runtime |
|---|---:|---:|---:|---:|
| Rollout tail k2 d2 | 100.00% | 1.000000 | 1.000000 | 15.45 ms |
| Beam-8 full（实验上界/仅对照） | 100.00% | 1.000000 | 1.000000 | 89.64 ms |
| Rollout tail k2 d1 | 97.37% | 1.001253 | 1.047619 | 11.19 ms |
| downstream demand | 92.11% | 1.006512 | 1.111111 | 1.53 ms |
| Longest-tail | 84.21% | 1.010315 | 1.095238 | 1.51 ms |
| shared downstream | 84.21% | 1.010732 | 1.111111 | 1.60 ms |
| Longest-delay（修正后） | 81.58% | 1.010955 | 1.095238 | 1.73 ms |
| release gain（第一轮旧实现） | 78.95% | 1.013879 | 1.111111 | 1.73 ms |
| barrier aware | 55.26% | 1.085985 | 1.625000 | 1.92 ms |
| structure aware | 50.00% | 1.096950 | 1.625000 | 2.11 ms |

结论是：downstream communication demand 是值得保留的独立候选信息，在当前集上比 LT 有更高命中率和更低 mean ratio；但它的 worst observed ratio 更差，不能替代 LT。shared-downstream 总 work 只有微弱差异。barrier urgency 的当前定义以及未经学习的字典序堆叠显著失败，证明确实不能把多个看似合理的局部量直接相加或排序后宣称“structure-aware 更强”。

结构候选用于 Rollout shortlist 也没有改善：`rollout_structure_k2_d2` 为 37/38，max ratio 1.055556，而 tail k2 d2 为 38/38。因此本轮不推广该 shortlist。

从部署问题的 primal 口径看，Rollout k2 d2 相对 LT 在 6/38 图上改善、32/38 持平、0 图退化；平均相对改善 0.963%，最大改善 8.696%。Beam-8 得到相同 primal 数字，但只解释为当前实验上界，不能据此提升为部署候选。

## 2. 参数化规模压力实验

运行时生成 10/20/30/50/100 节点，分别使用 sparse、dense、每两层 barrier 三种 profile，每 cell 3 个固定 seed，共 45 图。图按 compute/communication 层交替，从 compute release 开始，duration 范围相同，以避免 root communication 使 P 平凡主导。

| 节点 | 图数 | Rollout 改善/持平/退化 | mean/max primal 改善 | `[LB,best]` mean/max 相对宽度 | Rollout mean/max runtime |
|---:|---:|---:|---:|---:|---:|
| 10 | 9 | 0 / 9 / 0 | 0 / 0 | 7.89% / 21.74% | 3.68 / 4.96 ms |
| 20 | 9 | 0 / 9 / 0 | 0 / 0 | 21.85% / 31.91% | 36.70 / 48.75 ms |
| 30 | 9 | 1 / 8 / 0 | 0.463% / 4.167% | 18.35% / 27.91% | 109.87 / 141.18 ms |
| 50 | 9 | 1 / 8 / 0 | 0.271% / 2.439% | 13.04% / 18.67% | 535.51 / 700.92 ms |
| 100 | 9 | 2 / 7 / 0 | 0.221% / 1.333% | 8.30% / 11.43% | 5809.38 / 6426.60 ms |

大图评价不再用 `LT/max(P,L)` 排名 heuristic。首要问题是 Rollout 相对 LT 的纯 primal 改善；`[max(P,L), best feasible]` 只表达知识区间，其宽度表示尚未排除的改进空间，不是任何算法的 approximation ratio。当前压力集上的 Rollout 改善很稀疏，且 100 节点平均代价已到秒级，因此不能仅凭“不退化”把它当默认在线策略。

正式小图中 LT 的 6 个失败实例全部含 join 或 barrier；其中 5 个是低 fork、同步收口型结构，另一个是需要跨两次决策投资的嵌套 fork/join。迁移到大图时应检查这些同步、多层 barrier、fork-join 交互是否存在；存在时将 LT 标为风险，而不是借助松下界给它背书。该模式是 observed warning signal，不是因果定理。

现有压力集中，10 节点有 7/9 图出现上述 join/barrier 或 fork-join 告警，20/30/50/100 节点均为 9/9；多 barrier 在对应五档分别为 6/9、9/9、9/9、9/9、9/9。因此大图确实落在 LT 应警惕的结构域中。但 Rollout 只在 4/45 个压力图上改善，说明“风险结构存在”不是“Rollout 必然获益”的充分条件；后续真实 DAG 必须逐层报告，而不能只凭标签选择算法。

LT 本身保持约毫秒级 priority 开销，而 top-2 depth-2 Rollout 从 10 节点约 3.7 ms 增长到 100 节点约 5.8 s。memoization 避免了重复子树，但没有改变每个 receding-horizon 决策仍需多次 baseline completion 的主要复杂度；100 节点结果表明它不能默认作为在线大图算法，需要 completion cache/增量 residual 或明确预算 fallback。

## 3. Exact bound 与 search-component 消融

在 10/20 节点、三个 profile 的 6 图上做四档下界；其中同一个 20-node sparse 图在所有模式下均触发 1s timeout，因此各档都是 5/6 完成。

| bound | mean states | mean runtime | lower-bound prunes |
|---|---:|---:|---:|
| none | 250.5 | 186.6 ms | 0 |
| P | 244.2 | 186.0 ms | 0 |
| L | 233.7 | 182.8 ms | 259 |
| max(P,L) | 231.2 | 187.8 ms | 259 |

当前样本中 P 没有产生严格剪枝，L 提供主要作用，combined 只再减少少量 states；runtime 差异低于墙钟噪声，不能声称 combined 更快。该消融只服务于小图 Exact teacher，不再作为大图 heuristic 评价主线。大图只保留 lower bound 到 best-feasible 的知识区间。

## 4. Beam 的最终定位

Beam-8/32 定位为实验上界和离线对照，不作为部署候选，不主张鲁棒性。已有反例搜索没有穷尽固定宽度失败空间，但由于后续实际路线不使用 Beam，不再继续投入 Beam-8 反例搜索，也不把它列为 Stage 2 退出条件。registry 使用 `development_status=experimental` 明确这一边界。

## 5. 原始产物与下一步

- `stage2_complex_chain_experiment_round2_20260816.json`：正式 45 图逐实例结果；
- `stage2_complex_chain_scaling_20260816.json`：压力、bound 和 component 消融；
- `stage2_primal_comparison_20260816.json`：从既有 raw 结果重算的 primal、知识区间和 LT 风险结构；
- `stage2_beam8_search_20260816.json`：停止搜索前的历史审计账本，不再作为活跃研究任务。

下一步最有价值的工作是：优化 Rollout baseline completion 的增量复用；在真实 DAG 上报告 LT→Rollout 的 primal 改善和稳定性；把小图 LT 失败结构映射到大图风险标签；进入 Stage 3 后研究资源兼容集合的互补性。Beam 不进入部署路线。
