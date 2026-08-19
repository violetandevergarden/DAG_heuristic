# Stage 4a/4b 代码修正结果

日期：2026-08-16  
对应审查：`docs/process_docs/stage4_llm_search_review_20260816.md`  
对应修正方案：`docs/process_docs/stage4_llm_search_review_modification_plan_20260816.md`  
性质：本轮执行了有边界的代码修正，未整体重写；旧不可抢占代码与历史结果未改动。

## 附记（同日稍晚）：`llm_structure` 重组与真实语料扩充

应后续评审意见，对上一版的组织做了定向重组，并以 SimAI 真实语料替换合成五层：

- **目录改名**：`benchmark/stage4/` → `benchmark/llm_structure/`（`preemptive/` 存放全部问题，
  `nonpreemptive/` 留空占位）。内容按来源编排：`unified/`（统一瓶颈单通道 28 个）、
  `routed/<topology_tag>/`（路由冻结多资源 11 个）、`multi_iteration/`（多 iteration 单 job 3 个）、
  `simai_examples/`（SimAI 示例 workload 1:1 投影 2 个），共 **44 个真实派生 benchmark**。
- **语料**：`third_party/simai-flow-scheduler/inputs/aicb-workload/` 中 936 个真实 AICB 文件
  （Mixtral-8x7B / GPT-13B/175B/22B/7B / Llama-405B）里选取 A100-Mixtral-8x7B 的代表性配置；
  拓扑来自 `inputs/topologies/` 的 6 个真实拓扑，按生产/实验分级
  （production：AlibabaHPN_16g、Spectrum-X_16g、DCN+DualToR_64g；
  experimental：Cassini_24g/64g、Hermod_32g）。
- **DP 重写**：Mixtral 网格原生 `dp = all_gpus/(tp*pp) = 1`；带 `_dpN` 后缀的 benchmark 通过重写
  astra-sim header 的 `all_gpus` 字段（world size = tp*pp*dp）把同一份真实逐层数据投射到更大
  世界规模，操作写入 provenance/transform_log。
- **多 iteration**：`repeat_iterations()` 按 rank 的 sink→source 连边重复单 iteration，保留 1F1B
  跨 iteration 流水重叠（单 job 领域）。
- **竞争检测**：`competition_report()` 用公共模拟器单遍完整回放（多资源单遍组装 trace 后由
  `assert_multi_resource_trace` 独立验证，与 `model.run` 对拍一致），对每个文件记录
  decisions / contended_decisions / max_eligible / conflict_pairs / competition_level /
  feasible_makespan，写入 `benchmark/llm_structure/manifest.jsonl`。
- **命名融入**：`benchmark_generate/stage4*.py` → `benchmark_generate/llm_structure.py` +
  `__main__.py` 的 `llm` 子命令；`simai/analysis.py` → `simai/projection.py`；
  `src/llm_structured/analysis/` 拆为 `signatures.py`（描述性结构签名与四级证据分级）与
  `perturb.py`；`stage4_layer` 枚举字段与 validator 契约删除，`semantic_contract_version`
  改为 `llm-v1`；`experiments/preemptive/stage4_structure_experiment.py` 保留
  （该目录沿用 stage 编号风格），其引用改为代码内 fixture。
- **竞争结论（重要）**：单通道统一瓶颈变体竞争普遍为 high（如 ws8 tp4 pp2 gbs2：4725 决策中
  4406 有竞争、max eligible 10、52k 冲突对）；而生产拓扑 + dp=1 的多资源变体几乎无竞争
  （AlibabaHPN_16g/Spectrum-X_16g 上 ~4500 决策仅 3 个有冲突对）——印证"DP 过小/链路充足时
  多资源图没有竞争"的预判，多资源竞争需依赖 dp>1 重写与实验拓扑集中链路。所有文件即使
  competition_level=none 也保留导出，manifest 中明确标注，供对比与选样。

---

## 1. 基线与本轮状态

| 指标 | 修正前 | 修正后 |
|---|---|---|
| 全量单元/集成测试 | 126 passed + 3 errors | **137 passed** + 同样的 3 个环境 errors |
| integration 测试是否被收集 | 审查时被静默排除 | **实际收集并全绿**（jsonschema 4.26 已装、SimAI checkout 存在） |
| benchmark 文件数 / index 行数 | 171（README 仍写 139） | **185**（README 同步，由 `build_index` 机器生成） |
| Stage 4 基准层 | 零散、默认 non-preemptive | 五层 14 个冻结文件 + 9 个精确 reference |

3 个 errors 全部是 `tests/test_generators.py` 与 `tests/single_channel/parallel_chain/preemptive` 中使用 `tmp_path` fixture 的既有测试：本执行环境（DSH Windows 沙箱）禁止枚举 `tempfile.mkdtemp` 创建的目录（`PermissionError: WinError 5`），与代码无关；在基线提交上同样失败，本轮未触碰这些测试。同一限制也导致工作区根下 4 个探针目录（`.tmp_pytest`、`tmp_probe2`、`tmp_pytest2`、`tmp_pytest_base`）无法从沙箱内删除；它们未被 git 跟踪、不影响仓库内容，需在宿主机上清理。

## 2. P0：语义阻断修正

### 2.1 exporter 显式可抢占语义（P0-1）

`benchmark_generate/simai/export.py`：

- `to_benchmark()` 现在显式构造 schema-v2 可抢占语义：`preemption=communication_resume`、`decision_epoch=task_event`、`optional_idle=False`、`resource_model=exclusive_fixed_set`、零抢占开销/零最小粒度，`schema_version="2.0"`，并在 metadata 记录 `semantic_contract_version="stage4-v1"`。
- 新增必填参数 `category` 与 `stage4_layer`，禁止靠默认值决定语义或来源：未显式传入即 `ValueError`。契约检查：`synthetic_motif`/`structured_projection` 永远不能标 `real`；`real_derived` 必须标 `real`。
- 新增 provenance 组装：`source.kind/name/content_hash`、本仓库与 SimAI 的 git commit（`git_commit()`）、converter 名称/版本、参数、`topology.name/content_hash`、`transform_log[]`、`projection_relation`；CLI 增加 `--category/--layer/--projection-relation/--manifest`。
- 任务 metadata 补齐正式结构标签：`pipeline_stage`、`parallelism_dimension`、`collective_type`、`layer_or_block_id`。
- 调用点同步修正：`experiments/simai/repetition_study.py` 6 处、`tests/integration/test_simai_export.py`、`tests/integration/test_repetition_export.py`；synthetic bootstrap 不再写 `category="real"`。

### 2.2 五个最小端到端回归测试（P0-2）

新文件 `tests/integration/test_stage4_export_semantics.py`，全部经由真实转换链导出 benchmark 后驱动公共模拟器并用独立 trace validator 回放：

1. **抢占与剩余工作守恒**：`bandwidth_gbps=0.001` 的 1F1B 导出使通信长于计算，round-robin 驱动产生真实暂停/恢复；断言 `preemptions > 0` 且每个通信的各区间长度之和等于原时长。
2. **资源不冲突通信进入 maximal-compatible 动作**：`isolated_dimensions` 投影后逐状态断言每个合法动作是包含极大集（被省略的 eligible 通信必与某成员冲突），且任意不冲突对都出现在某个极大动作中。
3. **两资源通信原子获取**：route-frozen 导出中，每个通信在其全部资源上的占用区间集合逐一相等（同时获取、同时释放）。
4. **forced idle 归模拟器、无主动 WAIT**：单 channel 下 eligible 非空时 `WAIT` 抛 `IllegalActionError`（"voluntary WAIT is forbidden"）；多资源模型根本没有 WAIT 动作，idle 由 `normalize_decision_state` 推进。
5. **同一时刻事件原子处理**：导出图存在 ≥2 个同时 compute 完成；断言任何稳定决策点都已反映该时刻的全部完成，决策不可能插在两个同时完成之间。

5 项全部通过。

### 2.3 integration 可见性（P0-3）

- `tests/integration/conftest.py`：缺依赖时不再静默 `collect_ignore_glob`，改为显式 pytest warning（列出缺失项与"coverage 未被认证"声明）。
- 新文件 `tests/test_integration_coverage.py`：缺 `jsonschema` 时显式 skip（计入统计）；否则导入两个 integration 测试模块并断言测试函数数量 ≥ 预期，防止目录整体消失却不被察觉。

## 3. P1：五层 benchmark 与转换合同

### 3.1 目录与内容

新目录 `benchmark/stage4/preemptive/`（路径含 `preemptive` 段以通过布局测试）：

| 层 | 文件 | 场景 | reference |
|---|---|---|---|
| synthetic_motif | pp_wave / tp_allreduce / dp_allreduce / optimizer_barrier / ep_alltoall | 4 单通道 + 1 多资源 | 全部 5 个 optimal |
| structured_projection | unified_channel / per_dimension_fabrics / route_frozen（同一 synthetic 1F1B workload 的三种转换规则） | 1 单通道 + 2 多资源 | 无（超出 100k/5s 预算，有可行回放） |
| real_derived | single_job_1to1 / multi_job_1to1（SimAI 示例 workload 文件 1:1 投影，带来源 hash） | 1 单通道 + 1 多资源 | 无（同上） |
| adversarial | copy_local / static_role_priority / symmetry_merge_guard / packing_trap | 3 单通道 + 1 多资源 | 全部 4 个 optimal |
| compatibility | `compatibility/manifest.jsonl` 指向 5 个 Stage 3 样本（含 hash 与预期 reference 值），不复制文件 | —— | —— |

- 9 个 reference sidecar 位于 `benchmark/reference_results/stage4/preemptive/`，全部 `oracle_status=optimal`；数值与手算一致（pp_wave 8、tp 6、dp 6、barrier 5、ep 4、packing_trap 13、copy_local 16=2n、static_role 8、symmetry_guard 12）。
- `preemptive/manifest.jsonl` 记录每文件的层、category、场景、投影关系、内容 hash 与可行回放基线（registry 的 longest_tail / longest_tail_pack 通过公共模拟器 + trace 验证，14/14 成功）。
- `benchmark/stage4/README.md` 固化五层契约、可追溯字段与重新生成命令。
- `benchmark/index.jsonl` 由 `build_index` 重建（185 行）；`benchmark/README.md` 规模表与 Stage 4 分层说明同步（旧表数字 139 为过时漂移，已修正）。

### 3.2 契约执行

- `src/benchmark/validator.py` 新增 `_stage4_layer_errors()`：层名枚举约束；`real_derived`↔`real` 一致性；synthetic 不得标 real；`compatibility` 只允许出现在 manifest。
- 生成器：`benchmark_generate/stage4_cases.py`（纯，无 SimAI 依赖）、`benchmark_generate/simai/stage4_export.py`（SimAI 依赖，含 `workload_to_benchmark` 1:1 投影与 8 节点 topology fixture）、`benchmark_generate/stage4.py`（编排：写文件 → 精确参考 → 重建 index）。

### 3.3 LLM 标签进入正式输入

- `src/core/dag.py::BenchTask` 增加只读 `labels: tuple[tuple[str,str], ...]` 字段（向后兼容的加尾字段）。
- `src/core/conversion.py::to_internal_dag` 把 phase / microbatch_id / pipeline_stage / parallelism_dimension / collective_type / layer_or_block_id / repetition_group / task_role 从 metadata 提取为正式输入标签；算法从 `BenchTask.labels` 读取，不读答案型 metadata。

## 4. P2：分析实现边界

- 新建 `src/llm_structured/analysis/repetition.py`：从 `experiments/simai/repetition.py` 迁入 `scan_repetition` 等全部统计逻辑，并新增 `classify_repetition_evidence()` 按四级证据（descriptive_motif / interface_equivalent / graph_automorphism / future_equivalent）输出最高可认证级别与未验证条件清单；不再允许只返回一个 period 数字。
- 新建 `src/llm_structured/analysis/perturb.py`：`perturb_durations`（从 study 迁入）。
- 新建 `benchmark_generate/simai/analysis.py`：`raw_b_to_w_edges`、`project_resources`（修复了资源声明列表不重建的问题）。
- `experiments/simai/repetition.py` 与 `repetition_study.py` 保留为薄兼容层（旧 import 可用），不再内含研究逻辑。

## 5. P4：受控验证 exact 与压缩

- `src/llm_structured/repetition.py::exact_oracle_paired(quotient=...)`：同一搜索体、仅 memo key 不同（身份 key vs 分量置换商 key），`quotient=False` 为严格对照。状态预算/时间预算超限抛错，完成枚举显式标 `status="optimal"`。
- `_validate_exchangeable_components` 扩展：labels 全等 + 可选 `resources` 参数（多资源证书：每位置资源集合一致）；跨分量边/时长差异/资源差异均拒绝。
- 新测试 `tests/llm_structured/test_paired_symmetry.py`（5 项）：跨分量边、时长扰动、资源差异拒绝；相同资源接受；identity vs quotient 全程 makespan 一致且 quotient 探索状态数不超过 identity。
- 旧测试 `test_component_symmetry_is_exact_and_reduces_states` 已替换为受控配对断言（旧断言比较两个不同实现的状态数，被审查判为不受控）。

## 6. P6-lite：runner 与结果治理

- 新 runner `experiments/preemptive/stage4_structure_experiment.py`：每个 exact 调用带 `state_limit`/`time_limit_s` 并在输出中报告 `status ∈ {optimal, time_limit, state_limit}`；输出绑定 git commit、Python 版本与平台。
- 结果：`docs/result_docs/stage4_structure_experiment_20260816.json`（R1/R2/S1/M1/P1 五组证据，见算法与理论结果文档）。
- 历史结果 JSON（`preemptive_stage5/6_20260815.json` 等）未删除、未改动；旧 K 反例与不可认证数字在理论文档中显式标注撤回/降级。

## 7. 变更文件清单

修改：`benchmark_generate/simai/export.py`、`benchmark_generate/simai/analysis.py`（新建）、`benchmark_generate/stage4_cases.py`（新建）、`benchmark_generate/stage4.py`（新建）、`benchmark_generate/simai/stage4_export.py`（新建）、`benchmark_generate/simai/fixtures/eight_gpu_topology.txt`（新建）、`src/core/dag.py`、`src/core/conversion.py`、`src/benchmark/validator.py`、`src/llm_structured/analysis/{__init__,repetition,perturb}.py`（新建）、`src/llm_structured/repetition.py`、`experiments/simai/repetition.py`、`experiments/simai/repetition_study.py`、`experiments/preemptive/stage4_structure_experiment.py`（新建）、`tests/integration/conftest.py`、`tests/integration/test_simai_export.py`、`tests/integration/test_repetition_export.py`、`tests/integration/test_stage4_export_semantics.py`（新建）、`tests/test_integration_coverage.py`（新建）、`tests/llm_structured/test_repetition.py`、`tests/llm_structured/test_paired_symmetry.py`（新建）、`tests/test_benchmark_format.py`、`tests/test_semantics_layout.py`、`benchmark/README.md`、`benchmark/stage4/README.md`（新建）以及 `benchmark/stage4/**`、`benchmark/reference_results/stage4/**`、`benchmark/index.jsonl` 的冻结产物。

## 8. 验证命令

```powershell
$env:PYTHONPATH='src'
python -m pytest -q -p no:cacheprovider            # 137 passed + 3 环境 errors（见 §1）
python -m benchmark_generate.stage4                # 冻结五层 + 精确参考 + 重建 index
python -m experiments.preemptive.stage4_structure_experiment `
  --output docs/result_docs/stage4_structure_experiment_20260816.json
```
