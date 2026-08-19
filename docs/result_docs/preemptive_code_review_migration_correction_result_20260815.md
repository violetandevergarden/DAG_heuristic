# 可抢占代码审查迁移修正实施结果（2026-08-15）

## 1. 结论

已按 `docs/process_docs/preemptive_code_review_migration_correction_20260815.md` 完成 P0--P7。此次修改只迁移目录、公开入口、生成路径和测试组织，没有修改 v1/v2 调度状态转移或 benchmark 问题内容。

最终状态：

- preemptive 与 nonpreemptive 在 core、三个 family、benchmark、reference 和 tests 中均为显式平级语义；
- `src/preemptive/`、`src/core/model.py` 和三个 family 根目录下的旧 `solver.py/interface.py` 已移除；
- 139 个 benchmark 与 66 个 reference 完成布局 v2 迁移，逐文件 SHA-256 与迁移前一致；
- 生成器、reference、registry、CLI 和 study runner 均根据 JSON semantics 路由，不再从旧路径或文件名前缀猜测语义；
- 全量测试为 `78 passed`。

## 2. 基线

- base commit：`bb6cdc7f3f77649421a586b38c910c6e721b22be`
- Python：3.14.6
- 固定生成参数：`samples=10`、`seed=260819`
- stage 6：`samples=50`、`seed=260815`
- 迁移前：139 个 benchmark、66 个 reference、72 项测试全部通过

## 3. 源码迁移

### 3.1 Core

- v1 状态机从 `src/core/model.py` 迁入 `src/core/execution/nonpreemptive.py`；
- v1 trace 校验入口迁入 `src/core/trace/nonpreemptive.py`；
- `core.execution` 与 `core.trace` 现在都显式提供 preemptive/nonpreemptive；
- `core.oracle`、conversion、generator 和 tests 已全部改用新 import；
- 临时 `core.model` shim 在仓库内部引用清零后删除。

### 3.2 Family

三个 v1 实际实现已物理迁入：

- `src/single_channel/parallel_chain/nonpreemptive/`
- `src/single_channel/complex_chain/nonpreemptive/`
- `src/muti_channel/nonpreemptive/`

与既有三个 `preemptive/` sibling 对称。family 根 `__init__.py` 不再 wildcard 导出任何一种语义。

### 3.3 旧兼容层退出

以下路径已不存在：

- `src/preemptive/`
- `src/core/model.py`
- `src/single_channel/{parallel_chain,complex_chain}/{solver,interface}.py`
- `src/muti_channel/{solver,interface}.py`

`pyproject.toml` 也已删除 `preemptive*` 旧包匹配。结构回归测试会阻止这些入口重新出现。

## 4. Benchmark 与 reference 布局 v2

规范路径为：

```text
benchmark/single_channel/<family>/<semantics>/<category>/<id>.json
benchmark/muti_channel/<semantics>/<category>/<id>.json
benchmark/reference_results/<上述相对路径>
```

迁移统计：

| 类型 | 数量 | 校验 |
|---|---:|---|
| benchmark | 139 | 迁移前后原始字节 SHA-256 相同 |
| reference | 66 | 迁移前后原始字节 SHA-256 相同 |
| 合计映射 | 205 | old path 唯一、new path 唯一、无冲突 |

语义分布：

| family | nonpreemptive | preemptive |
|---|---:|---:|
| single_channel/parallel_chain | 25 | 23 |
| single_channel/complex_chain | 33 | 27 |
| muti_channel | 17 | 14 |
| 合计 | 75 | 64 |

机器可读映射位于 `benchmark/path_migration_v1_to_v2.jsonl`，字段为 `layout_version`、`kind`、`semantics`、`old_path`、`new_path` 和 `sha256`。`benchmark/index.jsonl` 已重建，并为全部 139 行增加 `semantics` 与 `layout_version=2`。

历史 benchmark ID 和文件名保持不变，包括已有 `pm_`、`_np` 以及没有 `pm_` 前缀的 `preemption_unlock.json`。

## 5. Generator、registry 与 CLI

- 新增 `benchmark_generate/layout.py`，v1/v2 exporter 共用唯一规范路径函数；
- `python -m benchmark_generate all` 现在同时生成两种语义；
- 新增 `--semantics {all,preemptive,nonpreemptive}` 过滤；
- reference generator 只依据反序列化后的 JSON semantics 选择 Exact；
- index 由统一扫描函数生成；
- stage 0--4 runner 扫描规范布局并根据 JSON semantics 过滤；
- registry 继续根据 `benchmark.semantics.is_preemptive` 显式路由；
- CLI 输出新增实际采用的 `semantics` 字段。

CLI 双路由实测：

| 输入 | 算法 | semantics | makespan |
|---|---|---|---:|
| preemptive `preemption_unlock.json` | longest_tail | communication_resume | 15 |
| nonpreemptive `random_join_30.json` | rollout_wait2 | none | 22 |

## 6. Tests 镜像迁移

现有测试已迁入：

- `tests/core/{execution,trace}/{preemptive,nonpreemptive}/`
- `tests/single_channel/{parallel_chain,complex_chain}/{preemptive,nonpreemptive}/`
- `tests/muti_channel/{preemptive,nonpreemptive}/`
- `tests/llm_structured/`
- `tests/oracles/preemptive/`

新增回归覆盖：

- 已删除兼容路径不得重新出现；
- 每个 benchmark 路径 semantics 必须与 JSON semantics 一致；
- index 必须覆盖 139 个问题并显式包含双语义和布局版本；
- 205 条迁移映射的目标文件必须存在且哈希匹配；
- nonpreemptive trace、preemptive parallel-chain 和 preemptive multi-resource 显式入口。

## 7. 重建与验证

执行结果：

```text
python -m benchmark_generate all --samples 10 --seed 260819 --output benchmark
=> 139 benchmark files

python -m benchmark_generate reference --output benchmark
=> 66 exact reference files

python -m pytest -q
=> 78 passed in 18.27s

python -m ruff check <本次新增或实质修改文件>
=> All checks passed
```

三组旧 import 搜索均无结果；旧源码目录和 family 根 solver/interface 数量均为 0。reference 重建后，结构测试再次核对全部 205 个迁移后文件的 SHA-256 并通过。

## 8. 实验复核

### Stage 0--4

- Exact 完成：单通道 48 个，多资源 14 个；
- 明确超时且未标最优：`pm_fixed_beam_counterexample`、`pm_random_chain_6`；
- 单通道 `longest_tail`：optimal fraction 0.8333，mean ratio 1.0158，max ratio 1.2121；
- 多资源 `longest_tail_pack`：optimal fraction 0.8571，mean ratio 1.0066，max ratio 1.0556；
- 多资源 `rollout_sets2`：optimal fraction 0.9286，mean ratio 1.0026，max ratio 1.0370。

### Stage 5

- boundary-aware 在 periods 1/2/4/8/16 上均匹配 Exact；
- independent-copy 在 periods 2/4/8/16 上分别为 5/11/23/47，而 Exact 为 4/8/16/32；
- 7 replicas 时 symmetry compression 将探索状态从 99,207 降至 203，makespan 保持 23。

### Stage 6

- 共 60 个 multi-job case；
- candidate recall：k=1 为 0.8837，k=2 为 0.9989，k=4 为 1.0；
- `adaptive_k1_4`、`rollout_flat`、`rollout_k2/k4`、`semantic_k2` 均达到 optimal fraction 1.0；
- `exact_k1` 与 `priority_k1/k2` 的 optimal fraction 为 0.9333，max ratio 为 1.0714。

原始结果：

- `docs/result_docs/migration_correction_stage0_4_20260815.json`
- `docs/result_docs/migration_correction_stage5_20260815.json`
- `docs/result_docs/migration_correction_stage6_20260815.json`

## 9. 验收结论

修正文档列出的四个结构问题均已消除。v2 仍是唯一 active mainline，v1 仍是 maintenance baseline；这种研究状态差异只通过 registry/README metadata 表达，不再编码为不平等的目录、隐式入口或测试/benchmark 布局。
