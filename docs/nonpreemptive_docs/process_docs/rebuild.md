# `experiments/` 与 `tests/` 精简整理计划

> 状态：已完成（2026-09-10）
>
> 范围：删除确定冗余的实验与测试资产，调整目录和命名，减少默认完整测试时间。
>
> 本轮不优化算法或业务实现，不拆分 `src` 代码，不修改模拟器、Exact、trace 或调度语义，不修改 `src/core`。允许为文件移动、删除兼容入口、测试分组和路径更新进行最小导入及配置修改。

## 1. 整理前基线

### 1.1 当前规模

`experiments/` 当前同时包含：

- 可抢占 Stage 0--3 历史实验；
- 位于 `llm_structure/` 根目录的可抢占 Stage 4 实验；
- 不可抢占 Stage 4 foundation、4a--4f 实验；
- 可抢占 Stage 4g、4h 以及旧 Stage 5、Stage 6 入口；
- SimAI 独立研究入口；
- 多层实验 manifest 和大量本地 `__pycache__`。

`tests/` 已大致按 `core`、`single_channel`、`muti_channel`、`llm_structured`、`integration` 分类，但 benchmark、生成器、架构约束和注册表测试仍平铺在根目录，部分发布级数据审计混在默认单元回归中。

### 1.2 当前测试耗时

2026-09-10 执行：

```powershell
python -m pytest -q --durations=30
```

结果为 `2 failed, 283 passed in 222.36s`。最慢部分为：

| 测试 | 时间 | 判断 |
| --- | ---: | --- |
| `test_every_committed_benchmark_loads` | 56.41s | 发布级全语料校验，不应与另一全量扫描重复 |
| `test_every_problem_path_explicitly_matches_json_semantics` | 54.65s | 再次解析同一批大图，职责与格式校验重叠 |
| `test_thirty_real_small_graphs_match_frozen_result_makespan_and_trace_hash` | 49.14s | 大样本冻结实验回放，不适合作为每次默认回归 |
| `test_reference_results_recompute_with_exact_oracle` | 24.55s | 发布级 Exact/reference 审计 |

四项约占 185 秒，是默认测试时间的主要来源。目标不是优化实现速度，而是消除重复覆盖并把发布级重检与日常回归分开。

### 1.3 整理前失败必须先处理

本次基线中有两个失败：

1. `np_stage4f_micro_four_burst.json` 被读取为空内容，导致 selective rollout 测试失败；
2. `test_index_matches_files_and_hashes` 检测到实际文件 hash 与 index 不一致。

开始整理前必须先确认这是否是并行写入、未完成迁移或工作树损坏，并恢复一致基线。不得删除失败测试、放宽 hash 断言或把失败标成慢测试来掩盖问题。该修复属于已有 benchmark 整理的收尾，不计入实验/测试结构优化。

## 2. 总体原则

1. `experiments/` 只保存仍能复现实验结论的入口、配置与输入清单；稳定算法实现继续位于 `src`，实验不得成为 `src` 的依赖。
2. 目录按语义和研究阶段组织，不把可抢占与不可抢占入口平铺在同一层。
3. 结果已归档但脚本仍是唯一复现入口的，不因“历史”直接删除。
4. 只有纯兼容转发、无调用且无结果引用的临时脚本、可再生成缓存、重复 manifest 才可删除。
5. 测试按被测职责组织；不按文件长度拆分，也不为目录整齐制造空包装。
6. 删除重复测试时必须保留原断言能力：合并到唯一测试、转为发布级审计，或由更强测试覆盖。
7. 默认回归应快速、确定、不依赖 SimAI submodule、不完整解析全部 1.77 GB LLM 数据，也不运行大规模 Exact。
8. 发布级数据完整性、全语料 schema 和 reference 重算必须继续存在，但通过独立标记和命令显式运行。

## 3. `experiments/` 目标结构

```text
experiments/
├── README.md
├── preemptive/
│   ├── stage0_3/
│   └── llm_structure/
│       ├── stage4a/
│       ├── stage4c/
│       ├── stage4d/
│       ├── stage4e/
│       ├── stage4f/
│       ├── stage4g/
│       └── stage4h/
├── nonpreemptive/
│   └── llm_structure/
│       ├── foundation/
│       ├── stage4a/
│       ├── stage4b/
│       ├── stage4c/
│       ├── stage4d/
│       ├── stage4e/
│       └── stage4f/
├── shared/
│   └── benchmark_layout_audit.py
└── simai/
```

如果移动现有 `experiments/llm_structure/nonpreemptive` 会造成大量历史命令失效，可以保留 `experiments/llm_structure/` 作为一级领域目录，但其下一层必须先分 `preemptive/` 和 `nonpreemptive/`。不得继续让根目录文件靠名称猜测语义。

## 4. `experiments/` 具体整理

### 4.1 明确归类

- 当前 `experiments/llm_structure/` 根目录的 barrier、packing、selective rollout、multi-job 和 Stage 4a 系列，根据实际语义移入 `preemptive/`；
- 当前 `experiments/llm_structure/nonpreemptive/` 的 `stage4a_*` 至 `stage4f_*` 分别进入对应阶段目录；
- `stage4g_integrated_evaluation.py`、`stage4h_local_frontier_evaluation.py` 与其 manifests 进入可抢占语义目录，不与不可抢占 4a--4f 混放；
- `benchmark_layout_audit.py` 是跨语义数据发布工具，放入 `shared/`，不归入某个算法阶段；
- `experiments/preemptive/stage0_4.py` 至 `stage3_*` 归入 `stage0_3/`，但保持脚本名称与历史命令可追踪。

### 4.2 foundation 与批量入口

`foundation/contention_census.py`、`conversion_fidelity.py`、`hard_slice_validation.py` 是可复用的单项检查；外层 `stage4_contention_census.py`、`stage4_conversion_fidelity.py`、`stage4_runtime_breakdown.py` 包含批量、预算和结果输出逻辑，并非简单重复。

处理方式：

- 保留确有调用的基础检查与批量入口；
- 将批量入口放入 `foundation/runners/` 或以明确名称与基础函数并置；
- 若基础模块只被一个 runner 调用且没有测试或交互用途，可以把基础函数并回 runner 后删除小模块；
- 不得仅因文件短而删除或合并。

`experiments/llm_structure/nonpreemptive/runtime.py` 是对 `src/llm_structured` runner 的纯兼容重导出，应先迁移所有活动导入，然后删除，不在新目录重新创建同样的兼容层。

### 4.3 manifest 精简

对每个 JSON/JSONL 清单建立引用表，分为：

- `active`：当前 runner 默认或正式命令使用；
- `reproduction`：结果文档明确引用，用于复现实验；
- `intermediate`：可由 manifest 生成器重建；
- `obsolete`：无代码、测试、文档和结果引用。

执行规则：

- `active` 和 `reproduction` 随所属语义、阶段移动；
- `intermediate` 不再提交，改为运行输出；
- `obsolete` 删除；
- 名为 `old_benchmarks.jsonl` 的文件不能凭名称删除，必须先检查它是否是 Stage 4d 的正式受控旧基线；
- 同一组 case 同时出现在多个清单时，保留一个基础清单，其他清单只保存差异、split 或配置引用；
- 完成实验的输出不放入 `experiments/`，继续归档到相应语义的 `docs/*/result_docs/`。

### 4.4 可删除候选

只有完成引用审计后才执行：

- 所有 `__pycache__/` 和 `.pyc`；
- 无活动调用的纯兼容模块；
- 已被正式 runner 完全替代、且没有独立结果引用的早期临时入口；
- 可从源清单确定性生成的派生 manifest；
- 空目录和仅为旧路径保留的空 `__init__.py`。若移除 `__init__.py` 会影响模块执行，则保留。

`stage5.py`、`stage6.py` 以及超出当前正式计划的入口必须逐个检查内容与结果引用：若只是占位或旧阶段编号迁移产物则删除；若对应已归档实验，则移入 `legacy/` 或按真实研究阶段改名。不能把未完成设想伪装成当前正式阶段。

## 5. `tests/` 目标结构

```text
tests/
├── architecture/
│   ├── test_core_independence.py
│   ├── test_registry.py
│   └── test_integration_coverage.py
├── benchmark/
│   ├── test_loader_and_schema.py
│   ├── test_index.py
│   ├── test_layout.py
│   └── full_corpus/                 # 发布级慢测试
├── benchmark_generate/
│   ├── test_cases.py
│   ├── test_io.py
│   ├── test_recovery.py
│   ├── test_llm_catalog.py
│   └── test_llm_corpus.py
├── core/{execution,trace}/<semantics>/
├── single_channel/<family>/<semantics>/
├── muti_channel/<semantics>/
├── llm_structured/
│   ├── common/
│   ├── preemptive/
│   ├── nonpreemptive/
│   ├── integrated/
│   └── local_frontier/
├── integration/
└── support/                         # 共享 fixture/helper，不以 test_ 命名
```

目录只按被测模块和语义组织。`tests/oracles/preemptive/tiny_oracle.py` 若是测试辅助实现，应移到 `tests/support/oracles/`；如果已经没有测试使用则删除。

## 6. `tests/` 精简与提速

### 6.1 合并重复的全语料扫描

当前 `test_every_committed_benchmark_loads` 和 `test_every_problem_path_explicitly_matches_json_semantics` 分别完整解析同一批大图，共约 111 秒。

调整为：

1. 默认测试只读取 `index.jsonl` 和两个语义 manifest，检查路径、ID、语义目录、schema 版本和已保存 hash；
2. 选取每种 schema、语义、场景和 LLM 子目录至少一个代表文件进行实际 loader 校验；
3. 只保留一个发布级 `full_corpus` 测试完整加载全部 290 个 benchmark，并在一次加载中同时验证格式与路径语义；
4. 不在两个测试中重复读取约 1.77 GB JSON；
5. 发布 benchmark 或修改 schema 时显式运行 `full_corpus`。

### 6.2 分离冻结实验回放

`test_thirty_real_small_graphs_match_frozen_result_makespan_and_trace_hash` 约 49 秒，更接近实验结果复核而非单元测试。

- 默认回归保留少量具有代表性的单通道、多资源、WAIT 和 multi-job 样例；
- 30 图完整矩阵移入发布级或 `experiment_reproduction` 标记；
- 不删除冻结结果和 trace hash 校验能力；
- 代表样例必须覆盖曾发现的失败模式，不能只选最快文件。

### 6.3 分离 Exact/reference 全量复核

`test_reference_results_recompute_with_exact_oracle` 约 25 秒：

- 默认回归保留每个 Oracle/语义/场景的代表 reference；
- 所有 reference 的 hash、输入存在性和状态字段继续做轻量检查；
- 全量 Exact 重算标为 `oracle_full`，在 Oracle、执行语义、benchmark 或 reference 变化时运行；
- 不通过删除难例、降低状态空间或改变 Exact 参数来缩短时间。

### 6.4 删除真正重复的测试

为每个待删测试记录其断言集合及替代测试。只有以下情况可以删除：

- 相同输入、相同动作和相同断言已被另一测试完全覆盖；
- 只验证已删除兼容导入或旧路径；
- 只是实验脚本可运行性，而正式 runner 已有更强集成测试；
- fixture 已不再被任何测试使用。

不得删除语义边界、状态转移、trace 合法性、Exact 对拍、optional-idle/work-conserving 隔离或抢占/不可抢占隔离测试来换取速度。

### 6.5 pytest 分组

建议定义：

- 默认：单元、轻量集成和代表性回归；
- `integration`：需要跨模块或外部 fixture；
- `simai`：需要可选 SimAI submodule；
- `full_corpus`：完整 benchmark 解析和布局验证；
- `oracle_full`：完整 reference 重算；
- `experiment_reproduction`：冻结实验矩阵复核。

默认 `python -m pytest -q` 是否排除后三类，必须在 `pyproject.toml` 和 README 中明确。如果继续把默认命令称为“完整测试”，则另设 `python -m pytest -q -m all_validation` 不够清晰；建议名称固定为“默认回归”和“发布验收”，避免把未运行慢测试说成完整通过。

## 7. 实施顺序

### 批次 A：冻结清单与恢复基线

1. 解决当前空 benchmark/hash 不一致，恢复无失败基线；
2. 保存全部实验脚本、manifest、测试用例和 pytest node ID 清单；
3. 保存 `pytest --durations` 报告；
4. 建立源码、测试、文档和结果对实验入口及 manifest 的引用表。

### 批次 B：清理明确垃圾

1. 清除缓存和空目录；
2. 删除无引用纯兼容入口；
3. 删除确认可再生成且没有复现用途的中间 manifest；
4. 每项删除记录理由和替代入口。

### 批次 C：整理 experiments

1. 先按语义归位，再按 stage 归位；
2. 移动 manifest 并更新 runner 默认路径；
3. 处理 foundation 与批量入口关系；
4. 更新 README 和结果文档中的活动命令，不批量重写历史原始记录；
5. 验证所有保留入口至少能执行 `--help` 或最小 dry-run。

### 批次 D：整理 tests

1. 移动根目录测试到 architecture、benchmark、benchmark_generate；
2. 将 LLM 测试按 common/preemptive/nonpreemptive 归类；
3. 将 helper 与 fixture 移出测试收集命名；
4. 合并重复断言；
5. 建立默认回归和发布验收标记。

### 批次 E：测试时间验收

1. 运行默认回归并保存耗时；
2. 分别运行 `full_corpus`、`oracle_full`、`experiment_reproduction`；
3. 运行包含全部标记的发布验收；
4. 对比整理前 node ID，解释每个减少或移动的测试；
5. 确认耗时降低来自去重和分组，而不是跳过失败或弱化语义断言。

## 8. 目标与验收

整理完成后应满足：

1. `experiments` 的每个活动入口能从目录判断语义和阶段；
2. 没有活动代码依赖旧实验路径或纯兼容转发；
3. 每个保留 manifest 都有活动入口或结果文档引用；
4. 没有提交缓存、临时输出、可再生成中间清单和无引用 fixture；
5. `tests` 镜像被测职责，根目录不再堆放不同领域测试；
6. 默认回归不依赖 SimAI，不完整解析全部大图，不全量重算 Exact；
7. 全语料、全 reference 和冻结实验的验证能力仍由发布验收保留；
8. 当前两个失败已在整理前解决，而不是通过删除或分组隐藏；
9. 默认回归目标控制在 60 秒以内；若受环境影响未达到，必须报告慢项，不修改算法实现追求该数字；
10. 发布验收全部通过，并提供测试数量、标记分布和耗时；
11. 未修改 benchmark 内容、研究算法、执行语义或 `src/core`；
12. 对删除、移动和保留的争议文件形成机器可读或表格化记录。

## 9. 建议命令

具体 marker 名称以实施后的 pytest 配置为准，建议形成以下固定入口：

```powershell
# 默认回归
python -m pytest -q

# 完整数据集与 reference 发布验收
python -m pytest -q -m "full_corpus or oracle_full"

# 冻结实验复核
python -m pytest -q -m experiment_reproduction

# 所有已收集测试（包括发布级和冻结实验）
python -m pytest -q -o addopts=""
```

最终 README 已明确每条命令覆盖范围，不能只报告默认回归通过而遗漏发布级验证。

## 10. 本轮完成记录

- `experiments/llm_structure/` 已按 `preemptive/`、`nonpreemptive/`、`shared/` 分层；两条语义下的 Stage 4a--4h/f 入口按阶段归位；可抢占 Stage 0--3 入口归入 `experiments/preemptive/stage0_3/`，超出当前正式计划的入口归入 `legacy/`。
- 不可抢占 foundation 的基础检查、批量 runner、manifest 已分开；纯兼容 `runtime.py` 已删除。活动导入、默认路径和 README 已同步，未在新目录重建兼容层。
- 根目录测试已归入 `architecture/`、`benchmark/`、`benchmark_generate/`；独立 tiny Oracle 归入 `tests/support/oracles/`，并补齐必要包边界。
- `tests/llm_structured/` 根目录已清空测试文件：通用审计放入 `common/`，可抢占结构测试放入 `preemptive/`，并保留 `nonpreemptive/`、`integrated/`、`local_frontier/` 五类职责边界。
- `full_corpus`、`oracle_full`、`experiment_reproduction` 标记和默认排除配置保留；默认回归不再重复完整语料扫描、Exact 重算和冻结矩阵。
- 验收结果：默认回归 `283 passed, 2 deselected`（41.10s）；发布级 `1 passed, 284 deselected`（23.83s）；冻结实验复核 `1 passed, 284 deselected`（46.72s）。全量命令使用 `python -m pytest -q -o addopts=""`，避免 PowerShell 将空的 `-m ""` 解析为缺少参数。
- 已清理 `experiments/` 与 `tests/` 下的 `__pycache__`、`.pyc`；未修改 benchmark 内容、算法、执行语义或 `src/core`。
