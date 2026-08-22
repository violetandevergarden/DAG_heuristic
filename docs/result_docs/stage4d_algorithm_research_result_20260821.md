# Stage 4d Selective Rollout 算法研究完整结果（2026-08-21）

## 1. 研究问题与最终回答

Stage 4d 研究的不是“能否调用 rollout”，而是三个更严格的问题：

1. 哪些通信决策中 LT 真的会选错，且错误会影响最终 makespan；
2. 能否用明显低于 rollout 成本的特征识别这些决策；
3. 在相同调用、展开或墙钟预算下，选择性搜索节省的预算能否转化为更宽或更深的搜索收益。

本轮结论是：

- 小图上确实存在少量 LT 首动作错误，候选生成能够覆盖这些错误，深度二可修复一个深度一误判；
- 现有低成本触发器 precision 较低，仍会在大量无收益状态触发；
- 40 节点 control 可完整执行 rollout，但所有方法 makespan 相同；
- 1536 和 2204 节点真实 AICB 图的端到端调度能完成，但 1 秒单决策/8 秒总搜索预算内没有完成任何一次 rollout 候选比较，最终 trace 全部等于 LT；
- 一张 2680 节点图中只有 FIFO 在 35 秒完成，LT 与所有 LT-completion-based rollout 均硬超时；
- 因此 selective rollout 当前只适合作为小图诊断工具，不具备进入 Stage 4g 默认算法的真实净收益证据。

## 2. 问题与算法定义

### 2.1 公共调度语义

研究使用仓库公共可抢占模拟器：DAG 依赖为 finish-to-start；compute ready 后自动开始且不可抢占；communication 可在离散事件处暂停和恢复；有 eligible communication 时禁止主动等待；单通道动作选择一个通信；多资源动作选择资源互不冲突且 inclusion-maximal 的通信集合。所有 rollout 分支和最终 trace 都调用公共模型的状态转移。

基础目标是单 job makespan。本轮真实实验只使用单通道 AICB DAG；多资源 selective rollout 完成了代码和合法性回归，但没有把 Stage 4c packing 质量变化混入本轮真实收益数字。

### 2.2 LT baseline

在当前状态 `s` 上，对每个 eligible communication 计算 residual Longest Tail。LT 选择排序第一的通信；相同分数使用稳定且不读取答案的 task ID tie-break。所有未触发、预算不足、评价不完整和估值并列状态都执行该 LT 动作。

### 2.3 候选生成

单通道候选按以下来源稳定去重：

1. LT 首选；
2. LRPT 首选；
3. FIFO 首选；
4. join-aware 首选；
5. 按 LT 排名补足到 `max_candidates`。

候选宽度是实际保留的动作数，不是只用于命名的参数。宽度 2 与宽度 4 均始终保留 LT baseline。多资源候选使用 Stage 4c 的有界多起点极大集合构造。

### 2.4 触发器

研究的触发器如下：

| 名称 | 定义 |
| --- | --- |
| choice | 当前有两个以上真实不同动作时触发 |
| margin | LT 前两名规范化 tail 分差不超过 0.25 |
| disagreement | LT 与 LRPT 的真实首选不同 |
| unlock | 分差不超过 0.25，且 LT/挑战候选的立即 compute release 不同 |
| join | 分差不超过 0.25，且两候选的最后 join 缺口影响不同 |
| combined | disagreement，或“小分差且 release/join 影响不同” |
| periodic | 每 4 个 choice state 触发一次 |
| random | 概率 0.25，使用固定 seed 0、1、2 |

`combined` 在真实替代 holdout 运行前冻结。它只使用当前 residual state，不使用 benchmark ID、类别或结果标签。

### 2.5 搜索深度、宽度和终端估值

- 深度 0：关闭 rollout，直接执行 LT；
- 深度 1：执行候选首动作，再以 residual LT 完成到终态；
- 深度 2：首动作后在下一个通信决策层继续按候选宽度分支，再以 LT 完成叶子；
- 叶子的 LT completion 是 terminal evaluator，不计入搜索深度，其公共状态转移计入 expansion。

评价器必须完整得到当前候选集合的全部值。若任一候选不完整，则该决策不比较部分值，直接执行 LT。完整值相同时也保留 LT；只有候选严格降低估值才改变动作。

### 2.6 冻结预算

正式真实配置统一使用：

| 预算 | 数值 |
| --- | ---: |
| 最大接受触发数 | 16 |
| 最大 completion calls | 32 |
| 最大 expansions | 100,000 |
| 单决策协作式时间 | 1 秒 |
| 整图搜索协作式时间 | 8 秒 |
| 每算法父进程硬墙钟 | 35 秒 |
| 最大 DAG 节点数 | 3000 |

标准配置为宽度 2、深度 1。同总上限对照将 combined 改成宽度 4、深度 1，或宽度 2、深度 2；三者保持相同 completion/expansion/trigger 上限。

## 3. 数据集、划分和证据等级

### 3.1 小型精确集

45 张 checked-in single-channel complex DAG：

| 类别 | 图数 | 节点范围 |
| --- | ---: | ---: |
| adversarial | 22 | 4–24 |
| random | 20 | 4–24 |
| real-derived | 3 | 7–13 |
| 合计 | 45 | 4–24 |

小图沿 LT 访问路径标注全部存在多个合法首动作的状态。每个动作使用未压缩 Exact 后缀，单首动作预算为 100,000 states、1 秒。搜索未完成的状态标 unknown，不当作 negative。

### 3.2 Stage 4a 真实集

| 角色 | benchmark | task | comm | 竞争证据 |
| --- | --- | ---: | ---: | --- |
| control | `simai_example_single_job_1to1` | 40 | 16 | `certified_choice_exists` |
| development | `mixtral8x7b_ws8_tp2_pp4_ep1_dp1_gbs2_mbs1` | 1536 | 504 | `sampled_prefix` |
| 替代 holdout | `mixtral8x7b_ws4_tp2_pp2_ep1_dp1_gbs2_mbs1` | 2204 | 680 | `sampled_prefix` |
| 成本边界 | `mixtral8x7b_ws8_tp2_pp4_ep1_dp1_gbs16_mbs4` | 2680 | 880 | `sampled_prefix` |

2204 节点图原在冻结清单中标作 validation；在两张 2680 节点原 holdout 因成本停止后、且尚未查看 2204 结果前，将它指定为 substitute holdout。该调整、原因、source 和内容 hash 均写入最终 JSON。它来自不同 AICB workload 配置，没有参与阈值选择。

两张 2680 节点图按用户指示不再新增实验：其中 gbs16/mbs4 图保留已有完整尝试作为成本边界；gbs8/mbs2 图不补跑。不能据此形成 2680 节点层的质量均值。

Stage 4a 的 `sampled_prefix` 证据没有被升级为全图竞争认证；真实结果只说明冻结算法在这些输入上的实际回放行为。

## 4. 小图决策级 Exact 结果

### 4.1 标签分布

共标注 181 个实际选择状态：

| 类别 | negative | positive | unknown | 合计 |
| --- | ---: | ---: | ---: | ---: |
| adversarial | 57 | 5 | 1 | 63 |
| random | 98 | 3 | 13 | 114 |
| real-derived | 4 | 0 | 0 | 4 |
| 合计 | 159 | 8 | 14 | 181 |

32 个首动作 Exact 分支因 1 秒 `time_limit` 未完成，导致 14 个状态为 unknown。unknown 没有进入 precision、recall、候选召回或“LT 正确率”分母。

8 个 positive 分布在 7 张图：`pm_longest_tail_counterexample`、`pm_random_join_30`、`pm_random_join_40`、`pm_stage2_rollout_depth`（2 个状态）、`pm_complex_random_003`、`pm_complex_random_005`、`pm_complex_random_006`。每个状态 LT 相对最优首动作的绝对 makespan 损失为 1 或 2；8 个状态合计可恢复改善为 9。

### 4.2 触发准确性

| 触发器 | TP | FP | FN | precision | recall | 漏掉改善总量 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| choice | 8 | 159 | 0 | 4.79% | 100% | 0 |
| margin | 8 | 112 | 0 | 6.67% | 100% | 0 |
| disagreement | 2 | 44 | 6 | 4.35% | 25.0% | 7 |
| unlock | 7 | 41 | 1 | 14.58% | 87.5% | 1 |
| join | 1 | 11 | 7 | 8.33% | 12.5% | 8 |
| combined | 7 | 75 | 1 | 8.54% | 87.5% | 1 |

结论：

- choice 和 margin 不漏正例，但大量误触发，不能有效节省昂贵 completion；
- disagreement 与 join 调用少，但漏掉多数可恢复改善；
- unlock 的 precision 在当前信号中最高，但仍只有 14.58%；
- combined 比 choice 减少误触发，却没有优于 unlock，并漏掉一个正例。

这组数字来自 4–24 节点小图，只能说明触发机制，不代表真实 AICB 中的正例频率。

### 4.3 候选召回和评价误判分离

| 配置 | positive 数 | 最优动作进入候选 | evaluator 选中最优 | 评价误判 |
| --- | ---: | ---: | ---: | ---: |
| width 2 / depth 1 | 8 | 8 | 7 | 1 |
| width 4 / depth 1 | 8 | 8 | 7 | 1 |
| width 2 / depth 2 | 8 | 8 | 8 | 0 |

宽度 2 已覆盖全部 8 个正例；扩大到宽度 4 没有修复唯一误判，证明该错误不是候选遗漏。深度二修复了 `pm_stage2_rollout_depth` 中的深度一错误，说明后续竞争变化确实可能需要第二个通信决策层才能看到。

这也是本轮最清楚的正面结论：真实宽度参数和第二层分支在受控小图上有可解释作用。但它尚未转化为真实中图端到端收益。

## 5. 40 节点 control

40 节点 certified control 的 FIFO、LT 和 12 个 rollout 配置全部完成，trace 全部合法，makespan 均为 44,460。基础 trace 统计为 35 个通信区间、0 次抢占、forced idle 2 次/1500 时间单位、channel utilization 0.9663。

代表配置的搜索成本：

| 配置 | trigger positives | 完整评价 | completion calls | fallback | wall-clock |
| --- | ---: | ---: | ---: | ---: | ---: |
| choice w2/d1 | 16 | 16 | 32 | 17 | 0.123 s |
| disagreement w2/d1 | 14 | 14 | 28 | 0 | 0.057 s |
| unlock w2/d1 | 2 | 2 | 4 | 0 | 0.041 s |
| combined w2/d1 | 16 | 16 | 32 | 0 | 0.296 s |
| combined w4/d1 | 16 | 8 | 32 | 8 | 0.082 s |
| combined w2/d2 | 16 | 8 | 32 | 8 | 0.088 s |

宽度 4 或深度 2 在同一 32-call 上限下，每次完整评价需要更多叶子，因此只能完成 8 次评价；标准宽度 2/深度 1 可完成 16 次。三者 makespan 相同，节省调用没有转化为 control 上的质量改善。

## 6. 1536 节点 development

### 6.1 基线质量

- FIFO：3,370,062，3.33 秒；
- LT：3,331,609，采样运行 14.27 秒；
- LT 相对 FIFO 改善 38,453，即约 1.14%。

FIFO trace 为 604 个通信区间、0 次抢占、forced idle 3,074,318；LT trace 为 587 个通信区间、62 次抢占、forced idle 3,035,865。LT 用更多抢占换取更早释放关键计算，并降低 makespan。

LT 的该次 wall-clock 含 `tracemalloc`，峰值 13.18 MiB，不能直接与未启用内存采样的 FIFO 或其他方法作严格时间比例比较。

### 6.2 Selective rollout

除 `combined_w2_d1` 在内存采样扰动下达到 35 秒硬超时外，其余配置端到端完成，makespan 均为 3,331,609。但这些相同结果不是完成评价后“选择 LT”的质量证据：

- 所有完成的 selective 配置 `completed_rollout_evaluations=0`；
- 每个配置只启动 7–8 次 completion，随后触及单决策或总搜索时间；
- choice 的 budget-rejected/fallback 为 357；combined 宽/深对照为 183；disagreement 为 29；unlock 为 41；
- 所有完成配置的 trace hash 与纯 LT 相同。

因此 development 只证明安全回退正确，并给出 completion 成本边界；不能用它评价触发器在真实决策上的 precision 或候选质量。

## 7. 2204 节点替代 holdout

### 7.1 基线

| 方法 | makespan | wall-clock | 抢占 | 通信区间 | forced idle time | utilization |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| FIFO | 2,664,078 | 6.99 s | 0 | 796 | 2,164,174 | 0.1876 |
| LT | 2,623,977 | 6.80 s | 99 | 821 | 2,124,073 | 0.1905 |

LT 相对 FIFO 改善 40,101，即约 1.51%。

### 7.2 全部 selective 配置

14 个方法全部在 35 秒硬墙钟内完成。12 个 selective 配置 makespan 全部为 2,623,977，trace hash、抢占、通信区间、forced idle 和 utilization 与 LT 完全一致。

| 配置 | wall-clock | 接受触发 | 完整评价 | completion calls | fallback/rejected |
| --- | ---: | ---: | ---: | ---: | ---: |
| choice w2/d1 | 25.48 s | 8 | 0 | 8 | 461 |
| margin w2/d1 | 25.72 s | 8 | 0 | 8 | 453 |
| disagreement w2/d1 | 21.33 s | 5 | 0 | 5 | 34 |
| unlock w2/d1 | 23.45 s | 6 | 0 | 6 | 106 |
| join w2/d1 | 24.67 s | 8 | 0 | 8 | 184 |
| combined w2/d1 | 23.25 s | 8 | 0 | 8 | 273 |
| periodic w2/d1 | 23.63 s | 7 | 0 | 7 | 116 |
| random seed 0 | 22.17 s | 6 | 0 | 6 | 105 |
| random seed 1 | 23.01 s | 7 | 0 | 7 | 120 |
| random seed 2 | 22.68 s | 7 | 0 | 7 | 109 |
| combined w4/d1 | 23.35 s | 8 | 0 | 8 | 273 |
| combined w2/d2 | 23.40 s | 8 | 0 | 8 | 273 |

所有触发后的候选比较都在单决策或总搜索时间边界前未完整完成，因此严格采用规则从未选择非 LT 动作。最便宜的 disagreement 配置仍比 LT 慢约 3.14 倍；choice 最慢约 3.75 倍。

所以 holdout 结论不是“各触发器质量相同”，而是“以完整 LT completion 作 terminal evaluator 时，中图上没有可完成的 rollout 决策；不同触发器只改变了失败前消耗多少预算”。

## 8. 2680 节点成本边界

在 gbs16/mbs4 图上：

- FIFO 在 11.68 秒完成，makespan 为 3,080,625；
- LT 达到 35 秒父进程上限，没有完整 makespan/trace；
- choice、所有结构触发器、随机/周期、宽度 4 和深度 2均达到 35 秒上限；
- 超时行没有使用 FIFO 或 LT makespan 填充。

由于 LT 基线本身未完成，不能对该图计算 selective 相对 LT 的质量变化。另一张 2680 节点图按用户指示不运行。这一层只支持“当前 Python residual-LT/completion 回放在该规模可能超过 35 秒”，不支持“大于某节点数理论上不可调度”。

## 9. 同预算宽度—深度分析

小图上，同预算加深到 depth 2 修复了 1 个 depth 1 误判；width 4 没有额外候选召回收益。control 上 width 4 和 depth 2 都把完整评价数从 16 降到 8，makespan 不变。

1536/2204 节点图中三种配置都没有完整评价：

- w2/d1：叶子少，但一次 LT completion 已超过单决策预算；
- w4/d1：需要更多叶子，不能利用选择性节省的预算；
- w2/d2：多一层分支，同样在 terminal completion 前耗尽时间。

因此本轮没有观察到“减少触发后把预算用于更宽或更深，从而改善真实 makespan”的证据。节省的调用上限是形式上的可用预算，实际瓶颈是一次完整 completion 的墙钟成本。

## 10. 质量、成本和失败来源归因

### 10.1 小图

- 触发错误：现有规则在 recall 和 precision 之间没有良好平衡；
- 候选错误：8 个 positive 均被 width 2 覆盖，没有候选遗漏；
- 评价错误：depth 1 误判 1 个，depth 2 修复；
- unknown：14 个状态因 Exact 超时，未参与结论。

### 10.2 真实中图

- 触发错误：没有 Exact/完整 rollout 标签，不能计算真实 precision/recall；
- 候选错误：评价未完成，不能判断最佳候选是否被覆盖；
- 评价错误：没有完整候选值，不能判断排序是否正确；
- 主要失败：terminal LT completion 超出单决策/总搜索预算；
- 安全性：所有不完整评价回退 LT，trace 与 LT 完全一致；
- 净成本：2204 节点图增加约 14.5–18.9 秒算法墙钟，没有 makespan 改善。

这一区分避免把“安全回退有效”误写成“selective rollout 成功保护质量”。

## 11. 适用范围

已验证适用范围：

- 可抢占 communication、compute 自动且不可抢占；
- 单 channel 一般 DAG 的小图决策分析；
- 固定多资源合法候选的代码级回归；
- 单 job makespan；
- 最多 2204 节点真实图的完整端到端 fallback 调度，以及 2680 节点成本边界。

未得到支持的范围：

- 真实中图上完成的候选 rollout 质量比较；
- 真实固定多资源图上的 selective rollout 收益；
- 3000 节点以上的可扩展性；
- multi-job JCT、slowdown 或 fairness；
- 理论近似比或“最优”声明。

## 12. 十四项退出条件判断

| 条件 | 判断 | 本轮证据 |
| --- | --- | --- |
| 1. 分支复用公共模拟器且动作合法 | 满足 | 单/多资源测试，trace 独立验证 |
| 2. LT、候选、触发、预算接口独立 | 满足 | v2 公共契约和四层职责 |
| 3. 小图 Exact/首动作标签，unknown 分离 | 满足 | 181 状态；159/8/14 分层 |
| 4. choice、随机、周期、全量统一对照 | 满足 | 同 runner、输入和预算字段 |
| 5. precision、recall、误触发、漏触发和损失 | 满足（小图） | 六类触发器完整表 |
| 6. 候选召回与评价误判分离 | 满足（小图） | width 2/4 recall 与 depth 1/2 误判 |
| 7. 宽度、深度、调用同预算比较 | 满足（结果为负） | w2/d1、w4/d1、w2/d2 同上限 |
| 8. 不完整评价回退 LT并记录 | 满足 | 中图零完整评价、trace 与 LT 相同 |
| 9. 未参与设计的真实 holdout | 有限满足 | 2204 substitute holdout 全方法完成，但 rollout 评价均不完整 |
| 10. 特征和搜索计入 wall-clock | 满足 | 分项与总时间、父进程硬超时；内存仅代表性采样 |
| 11. 失败模式反例 | 满足主要项 | 特征污染、缓存、预算、深度不足和小图误判测试 |
| 12. 明确适用范围 | 满足 | 见第 11 节 |
| 13. 无收益时形成受限/否定结论 | 满足 | 仅作小图分析工具 |
| 14. 同预算净收益才进入 Stage 4g | 满足退出判断 | 无合格配置，不进入 Stage 4g |

第 9 项的“有限满足”是本阶段最重要的限制：holdout 的算法进程完成，不等于 rollout 候选评价完成。由于用户明确停止两张 2680 图，并且 2204 图已经给出明确的 evaluator 成本失败，本阶段以受限/否定结果结束，而不是继续无界增加预算。

## 13. 最终算法建议

Stage 4g 默认继续使用 residual Longest Tail，不启用 Stage 4d selective rollout。理由不是 LT 在所有图上最优，而是：

- 小图正例稀少，触发 precision 低；
- 深度二只在一个受控状态显示局部价值；
- 真实 1536/2204 图没有完成一次候选评价；
- 2204 图的额外墙钟达到 LT 的约 3.1–3.8 倍；
- 2680 图上 LT completion 本身超过硬上限。

如果未来重新开启该方向，优先事项应是设计可截断、可比较且经过小图校准的 terminal estimator，或只在离线识别出的极少数高价值状态使用进程隔离的 completion；不应继续以完整 LT completion 作为中图每候选估值器，也不应仅继续调整触发阈值。

## 14. 正式产物

- [最终逐决策与真实实验数据](/D:/Code/SimAI/DAG_heuristic/docs/result_docs/stage4d_selective_rollout_final_20260821.json)
- [Stage 4d 冻结清单](/D:/Code/SimAI/DAG_heuristic/docs/result_docs/stage4d_manifest_v2_20260821.jsonl)
- [代码修复完整结果](/D:/Code/SimAI/DAG_heuristic/docs/result_docs/stage4d_code_correction_result_20260821.md)

正式结论只引用 `stage4d_selective_rollout_final_20260821.json`。中断过程文件 `stage4d_selective_rollout_evaluation_v2_20260821.json` 用于审计追加过程，不作为最终聚合结果。
