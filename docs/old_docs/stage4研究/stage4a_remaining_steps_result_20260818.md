# Stage 4a 剩余修复与研究步骤完成结果

日期：2026-08-18
依据：`stage4a_benchmark.md`、`stage4a_new_review_20260818.md`、`stage4a_new_modification_plan_20260818.md`、`stage4a_repair_result_20260818.md`。

本报告记录本轮完成的 Stage 4a 剩余步骤：统一基线、DP 配对、真实 multi-job、大图规模报告、real-derived exact slice、probe 配置刷新，以及逐条退出条件对照。所有运行使用公共模拟器，trace 均经独立 validator 验证；所有超时/未完成结果按 `timeout`/`feasible` 如实记录，不冒充最优或完整。

**恢复说明（2026-08-18 晚）**：本文件最初于 2026-08-18 创建，后因一次 pytest `--basetemp` 误操作导致 `docs/` 目录被清空，本文件已按当时内容重建；实验 JSON 结果由对应 runner 重新运行生成。重跑时机器负载较低，小/中规模基线中 36 个 case 三个基线全部完成（首次运行时为 28 个），DP 曲线、multi-job、scaling、exact slices、census 结论与首次一致。参见 `docs/process_docs/stage4a_docs_incident_20260818.md`。

## 1. 新增与修改的代码

| 文件 | 内容 |
| --- | --- |
| `experiments/llm_structure/stage4a_baselines.py` | 统一基线 runner：FIFO / Longest Tail / 固定顺序，per-case 时间预算、断点恢复、trace 验证、makespan/preemptions/forced-idle/utilization/trace-hash 指标；支持 `--case-files` 处理 manifest 之外的样例；multi-job 时输出 per-job JCT |
| `experiments/llm_structure/stage4a_dp_curve.py` | DP 配对曲线：从同一真实 AICB source 以固定 tp/pp 生成 dp=1/2/4（缺失的 dp2 现场导出），复用基线 runner |
| `benchmark_generate/llm/real_multi_job.py` | 真实 multi-job 组合器：job 命名空间前缀、arrival 编码为 release compute、无跨 job DAG 边、资源宇宙合并 |
| `experiments/llm_structure/stage4a_multi_job.py` | multi-job 实验：3 个 case（同构单通道、异构多资源同时到达、异构多资源错峰到达），报告 makespan 与 per-job JCT |
| `experiments/llm_structure/stage4a_scaling.py` | 大图规模报告：top-10 任务数样例的 probe/基线耗时、fast probe tracemalloc 峰值内存、小大图的转换耗时 |
| `benchmark_generate/llm/slice.py` | real-derived slice：按 micro-batch/layer 窗口裁剪并保留窗口内依赖闭包，切掉的边界边计数记录 |
| `experiments/llm_structure/stage4a_exact_slices.py` | 切片 Exact：预算内 Exact + 明确状态（optimal/feasible+time_limit） |
| `experiments/llm_structure/stage4a_conversion_pairing.py` | 转换层对拍：SimAI 原生 builder 任务/边数 vs 导出 benchmark，serializer 追加边单独计数 |

## 2. 统一基线（FIFO / Longest Tail / 固定顺序）

### 2.1 小/中规模代表集（manifest 中 task_count ≤ 12000，39 个 case）

命令：`stage4a_baselines --max-tasks 12000 --time-limit-s 90 --sort-ascending`

- 39 个 case 全部执行；重跑后 36 个三个基线均完成，3 个至少一个基线超时（`timeout`，90s 预算）。首次运行时为 28 个完成、11 个超时；两次运行结论一致（LT 不差于 FIFO 且多次严格更优），差异来自机器负载。
- 超时集中在：单通道 large 形状（ws16 tp4 pp4 gbs8/16、ws8 dp1 7096 任务、ws2 gbs8/16）和 hermod_32g / cassini_64g 拓扑的 ws32 多资源形状；其中超时的通常是 Longest Tail 回放（FIFO/固定顺序多数能完成）。
- 完整结果：`docs/result_docs/stage4a_baselines_small_20260818/`（per-case JSON + summary.json）。

代表性 makespan（us）：

| case | FIFO | Longest Tail | 固定顺序 |
| --- | ---: | ---: | ---: |
| simai_example_single_job_1to1 | 44460 | 44460 | 47775 |
| simai_example_multi_job_1to1 | 108672 | 108672 | 108900 |
| gpt7b_ws16_tp4_pp4_alibaba | 445288 | 439131 | 439131 |
| gpt13b_ws16_tp4_pp4_alibaba | 506605 | 500332 | 500332 |
| mixtral_ws4_tp2_pp2_gbs8 | 3024796 | 2933306 | 3164119 |
| mixtral_ws16_tp4_pp4_gbs2 (4992 任务) | 1340983 | 1195599 | 1353860 |

观察：在完成样例中 LT 通常不差于 FIFO，且多次严格更优；固定顺序最差的情况更多。这是统一预算下的直接比较，不是最优性证明。

### 2.2 multi-iteration 样例（3 个，90s 预算）

`mixtral_ws8_tp4_pp2_it2`（14192 任务）、`it4`（28384）、`ws16_tp8_pp2_it2`（49888）三个基线全部 `timeout`（90s 内未完成完整回放）。已如实记录，不参与基线比较。

## 3. DP 配对曲线

同一真实 Mixtral AICB source、固定 tp/pp，通过 header `all_gpus` rewrite 构造 dp=1/2/4（projection，suite R-C）。缺失的 dp2 样例现场导出（`docs/result_docs/stage4a_dp_curve_20260818/cases/`，含 provenance）。

| source (tp, pp) | dp | 任务数 | FIFO makespan | LT makespan | 固定顺序 makespan | 状态 |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| ws8 (tp4 pp2) | 1 | 7096 | 1880593 | 1801988 | 1892454 | 完成 |
| ws8 (tp4 pp2) | 2 | 14224 | — | — | — | 三个基线均 timeout（120s） |
| ws8 (tp4 pp2) | 4 | 28576 | — | — | — | 三个基线均 timeout（120s） |
| ws16 (tp4 pp4) | 1 | 4992 | 1340983 | 1195599 | 1353860 | 完成 |
| ws16 (tp4 pp4) | 2 | 10048 | — | — | — | 三个基线均 timeout（120s） |
| ws16 (tp4 pp4) | 4 | 20352 | — | — | — | 三个基线均 timeout（120s） |
| ws16 (tp8 pp2) | 1 | 24944 | — | — | — | timeout |
| ws16 (tp8 pp2) | 2 | 49952 | — | — | — | timeout |
| ws32 (tp8 pp4) | 1 | 17664 | — | — | — | timeout |
| ws32 (tp8 pp4) | 2 | 35456 | — | — | — | timeout |

**结论（受限但明确）**：同一 source 下 dp 从 1 增加到 2 只把任务数翻倍，却使三个基线的完整回放全部超过 120s 预算。dp1 的两个可完成形状显示 LT 优于 FIFO 和固定顺序（ws8: -4.2%/-4.8%；ws16: -10.8%/-11.7%）。DP 扩展在增加通信任务数的同时显著抬高回放成本；在本预算下 dp≥2 的形状无法获得统一 makespan 基线，应视为"受成本限制未完成"，不能作为无竞争证据。

## 4. 真实 multi-job

组合器把两个真实 AICB 导出合并为一个 DAG：`{job_id}::` 前缀命名空间、arrival 编码为 release compute、无跨 job 边、共享固定资源宇宙（同 topology 路由时链路资源自然重叠）。

| case | 内容 | 场景 | makespan FIFO/LT/固定 | 说明 |
| --- | --- | --- | --- | --- |
| mj1_simultaneous | mixtral ws8 × 2（同构） | 单通道 | 3203064 / timeout / 3301551 | LT 90s 预算未完成 |
| mj2_simultaneous | gpt7b ws16 + mixtral ws16（alibaba 拓扑） | 多资源 | 661942 / 645209 / 688923 | 80 个链路资源两 job 全部重叠；LT 优于 FIFO -2.5%、固定 -6.3% |
| mj3_staggered | 同上，job B arrival = A 的 solo LT makespan 一半 | 多资源 | 864774 / 864774 / 864774 | 三基线同值；job B JCT 645209（= LT solo makespan，无额外拖累） |

per-job JCT 记录在每个 case 的 baseline JSON 的 `jobs` 字段（`docs/result_docs/stage4a_multi_job_20260818/baselines/*.json`）。**注意**：multi-job 结果与单 job makespan 结论分开报告；主目标为 makespan，JCT 为独立扩展指标。

## 5. 大图规模报告（top-10 任务数）

命令：`stage4a_scaling --count 10`（基线 60s 预算、fast probe 30s 预算）。

- 10 个大图（157056 任务 llama405b dp2 到 28576 任务 mixtral dp4）三个基线全部 60s `timeout`：完整回放对 ≥30k 任务样例在 60s 预算内不可行。
- fast probe（8 决策前缀）耗时 1.4s–10.8s（manifest `probe_runtime_ms`），tracemalloc 峰值内存 35MB–222MB（`docs/result_docs/stage4a_scaling_20260818/scaling_report.json`）。
- 转换耗时：35456 任务 34.1s、30688 任务 24.6s；≥40k 任务样例未重测转换时间（corpus 已生成，标注 `not_measured_size_limit`）。
- 结论：大图必须使用 bounded probe 或预算化回放；完整回放和 Exact 不在可行域内。

## 6. real-derived exact slice

从真实 AICB 导出按 micro-batch/layer 窗口裁剪，记录切掉的边界边（`slice_relation.cut_boundary_edges`），对切片运行预算化 Exact（300k 状态 / 60s）。

| slice | 场景 | 任务数 | Exact 状态 | 最优 makespan | 用时 |
| --- | --- | --- | --- | ---: | ---: |
| gpt7b ws16 alibaba slice (mb0, layers 0-1) | 多资源 | 300 | **optimal** | 71058 | 236ms |
| mixtral ws16 alibaba slice (mb0, layers 0-1) | 多资源 | 300 | **optimal** | 98823 | 278ms |
| mixtral ws8 slice (mb0, layers 0-3) | 单通道 | 268 | feasible (time_limit) | — | 60s 未完成 |
| mixtral ws8 slice (mb0, layers 0-1, 148 任务) | 单通道 | 148 | feasible (time_limit) | — | 120s 未完成 |

多资源真实切片两个均获得最优证书；单通道切片（即使 148 任务）在 60–120s 预算内未完成枚举，诚实记录为 `feasible + time_limit`，不标最优。完整 sidecar：`docs/result_docs/stage4a_exact_slices_20260818/`。

## 7. 转换层对拍（native builder vs 导出）

SimAI 原生展开只存在于动态 executor 的逐 iteration 路径（`JobExpander._expand_training` 只展开一个 iteration，无静态 N-iteration 展开 API），因此 full native multi-iteration 对拍需要驱动 DynamicExecutor，本轮不做。改为对拍转换层：

| source | native 任务数 | 导出任务数 | task_delta | raw edges | 导出 edges | edge_delta（= serializer compute-order 边） |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| mixtral ws8 tp4 pp2 | 7096 | 7096 | 0 | 13800 | 16072 | 2272 |
| mixtral ws16 tp8 pp2 | 24944 | 24944 | 0 | 64400 | 68944 | 4544 |
| mixtral ws16 tp4 pp4 | 4992 | 4992 | 0 | 9984 | 11456 | 1472 |

任务数 1:1 一致；edge_delta 与 `plan.compute_order` 追加的 serializer 边数吻合（3040 条 candidate 中实际生效 2272 等，取决于依赖去重）。结果：`docs/result_docs/stage4a_conversion_pairing_20260818.json`。

## 8. probe 配置刷新

- `python -m benchmark_generate.llm.corpus --mode probe --fast --time-limit-s 30 --max-decisions 8` 刷新全部 72 行：`probe_config_hash`、`probe_schema_version=contention-audit-v2`、`enumeration_limit/truncated`、`static_resource_overlap`、`termination_reason` 等字段已写入（manifest 72/72 带新配置哈希）。
- `publish` reconcile 后 manifest/index 哈希一致，`benchmark/index.jsonl` 覆盖全部 JSON。
- 状态仍为 `sampled_prefix`（8 决策前缀抽样），无完整回放宣称。

## 9. 退出条件逐条对照（stage4a_benchmark.md §7）

| 退出条件 | 状态 | 本轮证据 |
| --- | --- | --- |
| 1. 真实输入转换的依赖、资源和 trace 语义经小图和端到端检查 | ✅ 基本满足 | 转换层对拍 task_delta=0、edge_delta=serializer 边；集成测试通过 |
| 2. 每个正式样例都有可解释的竞争报告 | ⚠️ 部分满足 | 72 行新配置 fast probe（前缀级）+ 39 个小中 case 统一基线（36 完成）+ 受限 census（35 个有非等价选择）；完整回放级竞争报告仅覆盖能完成的样例 |
| 3. DP 增加和 job 混合对竞争强度的影响有实验曲线 | ⚠️ 部分满足 | DP 配对表（dp1 完成 2 点、dp≥2 全部 timeout——成本结论）；真实 multi-job 3 个 case 含 JCT；**尚无 dp 竞争强度曲线（dp≥2 未完成回放）** |
| 4. 普通规模和约 10 个超大样例的时间预算已测量 | ✅ 满足 | 小/中/大三层统一预算表；10 个大图 probe/基线/转换耗时与内存报告 |
| 5. 明确哪些输入无竞争、哪些适合后续算法研究 | ⚠️ 部分满足 | 完成样例的基线差异、multi-job 竞争、census 非等价选择清单；但 dp≥2 与大图无法完整回放，其竞争状态未定 |

## 10. 仍未完成/受限制的项（如实记录）

1. **dp≥2 和大图（≥30k 任务）完整回放**：120s/60s 预算内不可行；后续应使用 budgeted census + 选择性回放，不能默认完整回放。
2. **单通道真实 slice 的 Exact 最优证书**：148–268 任务切片在 60–120s 内未完成枚举；若需要，应做更小切片或更长预算，本轮不冒充最优。
3. **native multi-iteration 对拍**：SimAI 无静态 N-iteration 展开 API，需要驱动动态 executor；本轮仅完成转换层对拍。
4. **DP 竞争强度曲线**：需要先解决 dp≥2 的回放成本（如采样或增量 census）。
5. **multi-job JCT 与 fairness 的正式策略比较**：本轮只报告基线 makespan/JCT，没有引入专用 multi-job 策略。

## 11. 结果文件位置

- `docs/result_docs/stage4a_baselines_small_20260818/`（39 case × 3 基线，含 summary.json）
- `docs/result_docs/stage4a_baselines_medium_20260818/`（3 个 multi-iteration case，全 timeout）
- `docs/result_docs/stage4a_dp_curve_20260818/`（10 配对曲线 + cases/）
- `docs/result_docs/stage4a_multi_job_20260818/`（3 case + baselines + multi_job_report.json）
- `docs/result_docs/stage4a_scaling_20260818/`（scaling_report.json + baselines/）
- `docs/result_docs/stage4a_exact_slices_20260818/`（3 slice + summary.json + cases/）
- `docs/result_docs/stage4a_conversion_pairing_20260818.json`
- `docs/result_docs/stage4a_aggregate_20260818.json`

## 12. 阶段判定

Stage 4a 的退出条件从"基础设施完成、研究退出条件未完成"推进到"**基础设施完成；竞争准入、基线和规模证据基本建立；dp≥2 与大图的完整回放成本明确受限**"。五个退出条件中两个满足、三个部分满足；dp≥2/大图的竞争状态和 native multi-iteration 对拍仍是明确缺口，不能宣称 Stage 4a 全部完成，也不能把 72 个样例或 DP 重写样例宣称为已认证有竞争。
