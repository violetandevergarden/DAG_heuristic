# 不可抢占 Stage 4a 结果（2026-08-31）

## 1. 结论

不可抢占 Stage 4a 已建立可发布、可审计、可回放的真实 AICB 输入链，并发布 38 个正式样例。根据本轮实测和后续决定，正式快照只保留小图与中图；大图即使 FIFO 也不能在统一预算内完成，因此大图生成入口、规模实验入口、三张候选图和对应临时结果均已移除。

当前结果可以支持 Stage 4b--4f 在这 38 个样例上继续研究，但不能外推到超大训练 DAG，也不能声称已经完成原计划中的大图成本退出条件。

## 2. 正式快照

- 发布位置：`benchmark/llm_structure/nonpreemptive/`。
- 清单：`benchmark/llm_structure/nonpreemptive_manifest.jsonl`。
- 总计 38 个：30 个小图、8 个中图；36 个单 channel、2 个固定多资源。
- 真实来源覆盖 GPT-7B、GPT-13B、GPT-22B、Mixtral-8x7B；另含 4 个由真实 AICB 图组合出的 multi-job 样例。
- 固定多资源样例覆盖 Alibaba HPN 16G 与 Cassini 24G 两种公开 topology 投影。
- 竞争审计中，36 个样例观察到非等价选择，2 个样例在有限前缀内未观察到选择。所有结论均是有限前缀证据，不解释为全图竞争证明。
- 每个 JSON 自包含任务、依赖、整数 duration、固定资源和 provenance；发布前逐文件通过 Schema v3、不可抢占语义、内容哈希和审计报告哈希校验。

大图清理不是对超时行的选择性隐藏：两次正式 FIFO 大图尝试均超过 90 秒，原始 230 条基线记录中只有这两条未完成。调整研究范围后，这两条记录连同三张大图候选一起退出正式结果；保留的 228 条小中图结果全部完成。

## 3. 转换层对拍

转换代码已拆成三层：

- `benchmark_generate/simai/common_export.py`：AICB 解析、pipeline builder、依赖、duration 和固定路由；不选择调度语义。
- `benchmark_generate/simai/preemptive_export.py`：Schema v2 与可抢占语义渲染。
- `benchmark_generate/simai/nonpreemptive_export.py`：Schema v3 与不可抢占语义渲染。

`benchmark_generate/llm/` 同样按 `common/`、`preemptive/`、`nonpreemptive/` 分层，不再出现不可抢占代码有目录而可抢占代码散落在外层的情况。

真实输入对拍结果为 `matched`：SimAI builder 有 918 个任务、1282 条原始边；serializer 合理追加 364 条 compute-order 边；不可抢占导出仍为 918 个任务、1646 条有效边，没有缺边或无法解释的附加边。可抢占与不可抢占输出的任务和资源完全相同，只由各自 renderer 写入不同 Schema 与动作语义。详细结果见 `stage4a_conversion_pairing_20260831/result.json`。

## 4. 统一基线

结果文件：`stage4a_baselines_20260831/results.jsonl`。

- 38 case × 3 条规则 × 2 种动作口径，共 228 行，全部 `completed` 且 trace 校验通过。
- 规则为 FIFO、固定顺序、residual Longest Tail；`optional_idle` 与 `work_conserving` 分表保存，没有合并结果。
- 相对 FIFO，固定顺序在 76 个 case-mode 组合中严格更好 11 次、相同 44 次；Longest Tail 严格更好 17 次、相同 59 次。观察到的最大改善分别为 1.13% 和 1.23%，收益总体较小。
- 只有 3 个 case 在至少一种规则下出现两种动作口径的 makespan 差异，共 9 行发生主动 WAIT、216 次。大部分真实图上 optional-idle 没有改变基线动作。
- 单行 wall-clock 中位数约 153 ms，最大约 46.5 s，均低于 90 s 预算。

这些数据说明 Longest Tail 可继续作为基础对照，但不足以宣称它在真实不可抢占图上有稳定的大幅收益。

## 5. Exact 小图

结果文件：`stage4a_exact_small_20260831/results.jsonl`。

- 30 个 real-derived 小图分别运行 optional-idle 与 work-conserving Exact，共 60 行，全部获得 `optimal` 证书。
- 搜索状态数中位数为 3、最大为 49；单行 wall-clock 中位数约 224 ms、最大约 1.31 s。
- 29 个切片的两种口径最优 makespan 相同。唯一差异来自 `np_multi_job_heterogeneous_staggered` 切片：optional-idle 为 67174，work-conserving 为 68003，最优解包含一次主动 WAIT。

Exact 只证明这些因果闭包切片的最优性，不代表完整训练图最优。

## 6. Multi-job 与边界

正式快照包含同构/异构、同时/错峰到达四种真实派生 multi-job 输入。基线结果同时记录 makespan、逐 job 完成时间、主动等待和 forced idle，后续 Stage 4f 可以直接使用；当前 Stage 4a 不对 JCT、slowdown 或公平性作算法结论。

仍有两个明确边界：

1. SimAI 没有经过验证的静态 N-iteration DAG 导出接口，因此原生多 iteration 对拍仍标记为 `not_supported`，不能用投影重复冒充原生证据。
2. 本轮明确取消大图范围。原实现计划中的“大图转换、加载、回放、内存和退化边界报告”不再作为本阶段交付；若以后恢复大图研究，应新建独立预算和运行入口，不能把本轮超时结果解释成算法优劣。

## 7. 清理与可复现入口

已清理三组 smoke 目录、发布 staging、发布备份、孤立后台进程、旧 scaling runner 与 scaling 结果。正式数据只通过候选清单校验后发布，`benchmark/index.jsonl` 已随 38 个新样例重建。

主要入口：

```powershell
python -m benchmark_generate.llm.nonpreemptive.corpus --mode generate --output benchmark
python -m benchmark_generate.llm.nonpreemptive.corpus --mode audit --output benchmark --manifest <candidate_manifest>
python -m benchmark_generate.llm.nonpreemptive.corpus --mode publish --output benchmark --staging <staging_dir>
python -m experiments.llm_structure.nonpreemptive.stage4a_baselines --manifest benchmark/llm_structure/nonpreemptive_manifest.jsonl --output <results.jsonl>
python -m experiments.llm_structure.nonpreemptive.stage4a_exact --manifest benchmark/llm_structure/nonpreemptive_manifest.jsonl --output <results.jsonl>
```
