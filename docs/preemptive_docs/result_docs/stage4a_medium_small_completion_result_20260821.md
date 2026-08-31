# Stage 4a 中小图收尾结果（2026-08-21）

## 收尾范围

本次按最终指示停止扩展实验，只整理已经生成的真实语料、转换对拍和中小图严格基线。不再新增样例，不再补跑多 job、大图规模、DP、拓扑、iteration 曲线或新的 Exact 实验。因此，本文是 **Stage 4a 中小图范围的收尾结果**，不是对原计划中大图和多 job 退出条件的完成声明。

## 可复现输入与竞争审计

- 当前活动语料共 72 个自包含 benchmark，合计 1,295,870 个任务；其中单 channel 32 个、固定多资源 40 个。
- 72 个样例的转换状态均为 `valid`，活动清单为 `llm-corpus-v3`。
- 竞争分类为：`informative-certified` 2 个、`informative-observed` 33 个、`no-contention-observed` 37 个。
- 证据等级为：2 个 `certified_choice_exists`，70 个 `sampled_prefix`。后 70 个只表示有界前缀观测，不能解释为全图竞争或全图无竞争证明。
- 中小图严格基线绑定的 manifest 内容哈希为 `96e510751f359513b285b79f60ffb8ec5e21d46393d6981aafd3856c947e1c47`。

## 转换对拍结果

转换对拍结果保存在 `stage4a_conversion_pairing_20260821.json`。

- 三个代表性 1F1B workload 均实现任务一一对应，任务字段不一致数为 0；原生依赖无缺失、导出额外边均可由 serializer 补充的 rank 内 compute 顺序解释。
- 一个 `interleaved_1f1b` workload 同样匹配，字段不一致数为 0。
- 原生 N=2 展开与项目展开的任务数均为 14,192，跨 iteration 边数均为 2,567,448。
- 总边数分别为原生 2,595,048、导出 2,599,592；差值来自项目在每份 iteration 副本中保留的 serializer compute-order 边，已单独解释，不是未知依赖差异。
- SimAI `AnalyticalExecutor` 返回策略相关时间，但没有可稳定映射到本项目固定资源 trace 的公开事件轨迹，因此动态执行事件逐项对拍标记为 `not_supported`。这不影响上述静态任务、依赖和原生 iteration 边界对拍结论。

## 中小图严格基线

严格基线结果保存在 `stage4a_baselines_strict_20260821.json`。纳入标准为任务数不超过 12,000，共 39 个样例：单 channel 14 个、固定多资源 25 个，任务数范围为 40～11,152。

每个“样例 × 规则”都在独立子进程中执行，90 秒墙钟预算覆盖 benchmark 加载、调度和验证；超时后由父进程终止，不依赖算法主动检查超时。

- 39 个样例中，36 个的 FIFO、Longest Tail、固定顺序三种基线全部完成；3 个至少有一种规则超时；没有执行失败。
- 按规则统计：FIFO 完成 37、超时 2；Longest Tail 完成 36、超时 3；固定顺序完成 37、超时 2。
- 在三种规则均完成的 36 个样例中，Longest Tail 相对 FIFO：13 个更优、16 个相同、7 个更差。
- Longest Tail 相对固定顺序：16 个更优、16 个相同、4 个更差。
- 39 个样例中三种规则的首动作均相同，因此这些结果不能证明“首个通信选择”已经利用了结构差异；差异来自后续决策序列。
- 未完整完成的三个样例为：
  - `mixtral8x7b_ws8_tp4_pp2_ep1_dp1_gbs2_mbs1`（7,096 任务）：FIFO 和固定顺序完成，Longest Tail 超时。
  - `mixtral8x7b_ws16_tp4_pp4_ep1_dp1_gbs16_mbs4`（8,688 任务）：三种规则均超时。
  - `mixtral8x7b_ws16_tp4_pp4_ep1_dp1_gbs8_mbs2`（8,688 任务）：三种规则均超时。

## 可以支持的结论

1. SimAI/AICB 到项目 benchmark 的静态转换链在代表性 1F1B、交错流水和 N=2 iteration 展开上已经完成任务与依赖层面对拍。
2. 当前 72-case 语料的清单、转换状态和竞争证据已经分开记录；有界前缀观测不再冒充全图证明。
3. 严格进程预算下，任务数不超过 12,000 的 39 个样例中有 36 个可完成统一三基线回放，可作为后续 Stage 4 研究的中小图输入集。
4. Longest Tail 在该完成子集上并非稳定支配 FIFO：既有收益，也有退化案例。后续算法必须保留 FIFO、固定顺序和运行成本对照，不能仅报告平均改善。

## 不支持的结论

- 不声称全部 72 个样例均存在经过全图认证的有效竞争。
- 不声称 Longest Tail 在真实 LLM DAG 上稳定优于 FIFO。
- 不声称大图、多 job、DP 扩展或不同拓扑已经完成统一实验。
- 不把超时记为算法质量劣于已完成规则，也不把未完成回放写成有效 makespan。
- 不声称动态 SimAI executor 事件轨迹已完成逐项对拍。

## 收尾状态

按最终缩减后的范围，Stage 4a 的中小图结果整理完成。正式保留的本轮结果文件只有：

- `stage4a_baselines_strict_20260821.json`
- `stage4a_conversion_pairing_20260821.json`
- 本文 `stage4a_medium_small_completion_result_20260821.md`

已停止遗留实验进程，并删除 `.artifacts`、`benchmark/llm_structure/.staging` 以及两份 `llm_corpus_previous-*` 临时发布备份。中断的 multi-job 产物未纳入结果。
