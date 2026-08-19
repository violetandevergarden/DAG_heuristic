# LLM 结构化 benchmark 语料（真实 AICB + 真实拓扑）

本目录冻结由真实 LLM 训练 workload 生成的预抢占 DAG benchmark。全部文件为
schema-v2 语义（`communication_resume`、task-event、无主动 WAIT、固定排他资源集合）。
共同语义与全局边界见 `docs/plan_docs/stage4_LLM_search.md`。

## 来源

- workload：`third_party/simai-flow-scheduler/inputs/aicb-workload/` 中的真实逐层
  AICB 文件。当前活动 corpus 包含 72 个候选 case；这表示文件数量，不等于 72 个
  已认证存在竞争的样例。每个 benchmark 的 manifest
  记录源文件内容 hash 与 SimAI checkout commit。
- 拓扑：`third_party/simai-flow-scheduler/inputs/topologies/`。分级：
  - **production**：AlibabaHPN_16g、Spectrum-X_16g、DCN+DualToR_64g —— 用于真实评估；
  - **experimental**：Cassini_24g/64g、Hermod_32g —— 小型实验拓扑，链路共享集中，
    用于人为制造冲突。
- 多 iteration：单 job 领域内，把同一 AICB iteration 重复 N 次，iteration 之间按
  rank 的 sink→source 依赖连接，保留 1F1B 的跨 iteration 流水重叠。
- DP 重写：Mixtral AICB 网格原生 `dp = all_gpus/(tp*pp) = 1`。带 `_dpN` 后缀的
  benchmark 通过重写 astra-sim header 的 `all_gpus` 字段（world size = tp*pp*dp）
  把同一份真实逐层数据投射到更大世界规模；重写操作记录在 provenance/transform_log。
- `simai_examples/`：SimAI 自带示例 workload 的 1:1 投影（标注为 example，非生产 trace）。

## 布局

```text
llm_structure/
├── README.md
├── manifest.jsonl                # 每文件 lineage + probe 状态 + hash
├── preemptive/
│   ├── unified/                  # 单通道统一瓶颈变体
│   ├── routed/<topology_tag>/    # 路由冻结多资源变体（含生产/实验拓扑分级）
│   ├── multi_iteration/          # 多 iteration 单 job 变体
│   └── simai_examples/
└── nonpreemptive/                # 留空占位
```

文件命名：`mixtral8x7b_ws16_tp8_pp2_ep1_dp1_gbs8_mbs2.json`（可选
`_dp4`、`_it2`、`_route_alibaba_hpn_16g` 后缀）。

## 竞争 probe（manifest 字段 probe）

当前 72 个候选文件已完成新配置（`probe_config_hash`、`contention-audit-v2`）的最多 8 个
决策点 `fast_prefix` 公共模拟器采样；这不是完整回放，也不是全局无竞争证明。小型 SimAI
example 另有 bounded certified choice existence 检查。slow full replay 应按 case
恢复，并保留独立 checkpoint。

- `decisions` / `contended_decisions`：决策点数与存在竞争的决策点数
  （单通道：eligible>1；多资源：存在资源冲突的 eligible 对）；
- `max_eligible`、`conflict_pairs`、`contention_fraction`；
- `probe_kind`、`probe_status`、`baseline_action_rule`；
- `decisions_sampled`、`contended_decisions_sampled`、`action_set_count_max`；
- `certified_probe_status` 与 `certified_reachable_choice`（仅小图）。

`none_observed_under_probes` 只表示采样轨迹没有发现竞争；除非 certified probe 完成，
不能写成全局 none，也不能用它作为算法合理性结论。

## 基线与规模结果（2026-08-18）

统一 FIFO / Longest Tail / 固定顺序基线、DP 配对曲线、真实 multi-job、大图规模报告、
real-derived exact slice 与转换层对拍的结果归档在
`docs/result_docs/stage4a_remaining_steps_result_20260818.md` 及其引用目录
（`stage4a_baselines_small_*`、`stage4a_dp_curve_*`、`stage4a_multi_job_*`、
`stage4a_scaling_*`、`stage4a_exact_slices_*`）。要点：

- 小/中规模（≤12000 任务）39 个 case 中 28 个三个基线完整回放成功；其余至少一个
  基线在 90s 预算内超时。多资源真实切片（300 任务）已有 Exact 最优证书。
- 同一 source 的 DP 从 1 增加到 2 只翻倍任务数，却使完整回放全部超过 120s 预算；
  dp≥2 与大图（≥30k 任务）的完整回放当前不可行，竞争状态未定。
- 真实 AICB multi-job（同构单通道、异构多资源同时/错峰）3 个 case 已生成，
  报告 makespan 与 per-job JCT。

## 精确 reference

小图由 `benchmark_generate/reference.py` 在预算内尝试生成
（`benchmark/reference_results/llm_structure/...`），未在预算内完成完整枚举的
文件不生成 sidecar，manifest 中 `reference_optimal_makespan` 为空。

## 重新生成

```powershell
python -m benchmark_generate.llm.corpus --mode generate --output benchmark
python -m benchmark_generate.llm.corpus --mode probe --output benchmark --fast
python -m benchmark_generate.llm.corpus --mode publish --output benchmark
```

事务入口在 `benchmark_generate/llm/corpus.py`；转换逻辑在 `benchmark_generate/llm_structure.py`。
不要手工编辑本目录 JSON；要改就改生成器后重新冻结。
