# 不可抢占 Stage 4f：Multi-job 与有限 Cassini benchmark 实施结果

日期：2026-09-03

## 结论

本轮完成了计划中的 M0--M5。正式发布 9 个不可抢占 multi-job benchmark，其中 7 个单 channel、1 个 Cassini routed、1 个同源 Alibaba routed 控制；Cassini 占正式集的 1/9。正式集覆盖 2/4/8-job、同构/异构、同时/错峰到达，并按父 workload hash 隔离为 development、validation 和 holdout。

25 个候选全部存在静态跨 job 资源重叠，14 个在前 128 个决策或 30 秒内观察到动态跨 job 冲突，14 个进入局部质量检查。冻结 LT 后缀的跨 job 首动作检查得到 6 个 `quality_informative` 图；另外保留 2 个局部 `choice_only` 的 4/8-job 控制和 1 个未在受限前缀观察到动态冲突的错峰控制。

正式 9 图上的 8 个基线、2 种 idle 模式共 144 次运行全部在 90 秒内完成，144/144 trace 合法，0 timeout。最大单次墙钟约 14.4 秒。

## 输入与准入

- M0：旧 `np-foundation-followup-20260902` 的 8 个图确定性重建，文件 SHA-256 为 8/8 一致。
- M1：生成 25 个候选、合计 26,964 tasks；包含 10%/25%/50% 到达候选，以及为前缀冲突增加的 1%/2% 轻度错峰候选。
- Cassini 与 Alibaba 控制使用同一 AICB workload、相同 DAG、job 数和绝对 arrival。配对检查只允许通信 route、resource、duration 与拓扑元数据不同。
- routed 主质量图由真实父图的完整前驱闭包得到；未剪断依赖，也未手工修改 route 或资源。
- 四级准入严格区分静态重叠、动态冲突、策略分歧和目标值差异；timeout 不作为无冲突证据。
- ordinary multi-resource 策略不再枚举全部启动子集，只按策略排序构造完整合法极大集合；Exact 的动作空间未改变。

## 基线结果

基线包括 FIFO、全局 residual LT、固定 job 顺序、job round-robin、job 年龄、shortest remaining job、job-aware LT 和 starvation safeguard。

18 个 case-mode 中，LT 相对同表最佳基线出现：

- makespan 正 regret：9 个；
- 平均 JCT 正 regret：16 个；
- 最大 JCT 正 regret：10 个；
- 加权完成时间正 regret：16 个；
- 平均 slowdown 正 regret：16 个。

异构 GPT-13B/GPT-7B 三个开发图中，optional-idle 下 LT 保持最佳 makespan，但 shortest remaining job 把平均 JCT 降低 295,438 us，约为最佳值的 16.7%；work-conserving 下固定 job 顺序同时降低 makespan 和 JCT，LT makespan regret 约 99k us、平均 JCT regret 约 336k us。

GPT-22B 同构 1% 错峰 holdout 中，LT 在 optional-idle/work-conserving 下的 makespan regret 分别为 85,592/169,741 us，平均 JCT regret 分别为 650,838/860,747 us。这说明错峰 arrival 会打破同构同时到达的标签对称性。

Cassini–Alibaba 异构 1% 配对中：Cassini optional-idle 的 LT 在本表最优；Cassini work-conserving 的 LT makespan regret 为 2,015 us。Alibaba optional-idle/work-conserving 的 LT makespan regret分别为 72/2,685 us。该结果只支持“拓扑会改变策略差距”的受限结论，不能从一个配对推出一般 Cassini 优势。

optional-idle 是更大的动作空间，但当前 WAIT 规则只是启发式；其实际 schedule 有时差于 work-conserving，不能把动作空间包含关系误写成启发式质量支配关系。

## 算法重新准入

- 4d：存在真实 multi-job LT regret，可针对明确的 makespan/JCT 目标重新准入 selective rollout；不能混用两个目标的标签。
- 4c：routed work-conserving 图存在完整启动集合的非零目标差异，可在这组同源配对上重新准入 packing。
- 4e：本轮没有证明 barrier 能预测上述失败状态，因此不重新准入 barrier 特征搜索。
- 简单 job-aware 基线已经取得大部分已观察收益。后续复杂算法必须在冻结 split 上稳定超过对应的简单目标基线，而不只是超过 LT。

## 可追溯产物

- `stage4f_multi_job_20260903/candidates/`：候选 manifest、解析后的 case spec、父图/拓扑/arrival/hash 信息。
- `stage4f_multi_job_20260903/admission/`：双模式受限审计和准入原因。
- `stage4f_multi_job_20260903/quality/`：跨 job 首动作、冻结 LT completion 和各目标 spread。
- `stage4f_multi_job_20260903/baselines/`：144 条完整基线记录及汇总。
- `stage4f_multi_job_20260903/report/`：逐 case-mode 最佳规则、LT regret 和发布门槛清单。
- `stage4f_multi_job_20260903/legacy_rebuild/`：旧 8 图重建及 8/8 hash 对拍。

正式文件位于 `benchmark/llm_structure/nonpreemptive/multi_job/np_stage4f_*.json`。`benchmark/llm_structure/nonpreemptive_manifest.jsonl` 和 `benchmark/index.jsonl` 均含 9 条对应记录，最终文件、结果和 index 的内容哈希为 9/9 一致。

## 边界

局部首动作值使用冻结 LT 后缀，不是全局最优证书。4/8-job 图是从真实 AICB 决策切片组合出的机制/控制输入，不替代完整多 job 训练图。旧两个 4078-task routed 组合仍只作为成本诊断证据，不进入正式质量主表。Stage 4g 不在本轮范围内。

