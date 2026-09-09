# Benchmark 生成工具

`benchmark_generate/` 负责把随机实例、历史反例和 SimAI workload 转换成 `benchmark/` 下的语言无关 JSON。生成器只在离线准备数据时使用；调度算法运行时不应导入本模块。

## 目录结构

```text
benchmark_generate/
├── __main__.py                 # `python -m benchmark_generate` 入口（all/random/reference/llm）
├── export.py                   # 统一导出两种 semantics 并生成索引
├── layout.py                   # 两种语义共享的规范路径构造
├── cases.py                    # 随机、反例、LLM motif 和小拓扑 route 样例
├── convert.py                  # 内部 DAG/链/资源实例转成公开 Benchmark
├── reference.py                # 调用 Exact Oracle 生成最优值 sidecar
├── llm/                         # LLM Stage 4 generation and corpus workflows
├── llm/
│   ├── catalog.py             # AICB 源文件目录与确定性 case 选择
│   ├── corpus.py              # 真实 LLM corpus generate/audit/publish 事务流
│   └── barrier_motifs.py      # barrier 参数化小图与 teacher label
└── simai/
    ├── bootstrap.py            # 查找可选 SimAI checkout
    ├── export.py               # AICB/pipeline workload 转标准 benchmark
    └── projection.py           # 导出后资源重标记与示例 workload 1:1 投影
```

顶层生成代码不依赖 SimAI。只有 `simai/` 可以导入外部模拟器。

## 生成默认集合

从仓库根目录运行：

```powershell
$env:PYTHONPATH="src;."
python -m benchmark_generate all --samples 10 --seed 260819 --output benchmark
```

`all` 同时生成 preemptive 与 nonpreemptive 两套数据。可用
`--semantics preemptive` 或 `--semantics nonpreemptive` 只生成一种语义；
两种语义都通过 `export.py::export_semantic_suite` 导出，并通过 `layout.py`
构造 `family/semantics/category` 路径，不再设置 preemptive 专用 exporter。

只生成一种语义时仍使用统一命令，例如：

```powershell
python -m benchmark_generate all --semantics preemptive --output benchmark
python -m benchmark_generate all --semantics nonpreemptive --output benchmark
```

该命令会生成：

- 每个场景 10 个固定 seed random 样例；
- 已登记的 adversarial 样例；
- 已整理进固定集合的 real/LLM motif；
- `benchmark/index.jsonl` 及问题文件 SHA-256。

`--samples` 是每个随机场景的数量，不是全仓库随机样例总数。目前有三个随机场景，因此默认总计 30 个 random 文件。

只生成随机数据：

```powershell
python -m benchmark_generate random --samples 30 --seed 1234 --output my_benchmark
```

临时大规模随机实验应写到新目录，不要覆盖仓库中用于回归的固定 10 个样例。

## 生成精确参考答案

```powershell
python -m benchmark_generate reference --output benchmark
python -m benchmark_generate reference --category random --output benchmark
python -m benchmark_generate reference --category real --output benchmark
```

默认命令遍历 `category=adversarial` 的问题；`--category` 可以显式选择
`random`、`real` 或 `all`。v1 调用 `exact_optional`，v2 调用
work-conserving `exact`，在 `benchmark/reference_results/` 写出：

- `benchmark_id`；
- 原问题文件 SHA-256；
- Oracle 名称；
- `optimal_makespan`。

Exact Oracle 对大图可能产生指数级开销。只有规模可控、可以在测试中重复
求解的小图才应生成 reference；不要给大型真实 DAG 或超时结果标记“精确最优”。
Stage 1 当前还为 9 个可解 random 和 5 个 structured/real-projection 样例保存
sidecar；`pm_fixed_beam_counterexample` 和 `pm_random_chain_6` 在固定预算内超时，
因此没有 sidecar。

## 固定 seed 与历史反例

- 默认 random suite：seed `260819`，不同场景使用确定性的派生 seed。
- R1 WAIT-hard 并行链：seed `260813` 的索引 `14/52/60/70/77/86/98`。
- R1–R3 random-join 反例：seed `260817` 的索引 `23/30/40/46/60`。
- combined-hard：seed `260813` 的 `combined_chain_14/70/86`。

这些样例虽然来自随机序列，但因为经过筛选、用于暴露特定失败模式，所以写入 `adversarial/`；普通未筛选样例才属于 `random/`。

## 添加随机或手工生成器

1. 在 `cases.py` 中添加函数，显式接收 `random.Random` 或其它生成参数。
2. 保证相同代码版本、seed 和参数产生相同任务、依赖和时长。
3. 在 `export.py::current_cases` 中决定是否加入固定集合。
4. 使用 `convert.py` 转成公开 `Benchmark`，不要让 JSON 包含 Python 专用对象。
5. 写出后通过公共 Loader/Validator。
6. 在 `tests/test_generators.py` 添加固定 seed 可复现测试。
7. 若属于算法反例，记录攻击对象和来源；若属于 random，仓库通常只保留约 10 个代表样例。

`export_semantic_suite` 只写入调用者显式选择的 semantics；随后由 `build_index`
把输出目录中的合法问题纳入索引。生成器不会自动判断旧文件是否应该删除，改变固定集合后必须检查是否存在过期文件。

## 真实 LLM corpus 事务工作流

真实 LLM 语料不再使用“先删除正式目录、再生成和回放”的单一命令。请使用：

```powershell
python -m benchmark_generate.llm.preemptive.corpus --mode generate --output benchmark
python -m benchmark_generate.llm.preemptive.corpus --mode probe --output benchmark --fast
python -m benchmark_generate.llm.preemptive.corpus --mode publish --output benchmark
```

`benchmark_generate.llm.preemptive.corpus` 和 `benchmark_generate.llm.nonpreemptive.corpus` 分别提供两种语义的正式工作流。`generate` 写入 `benchmark/llm_structure/.staging/<run-id>/`；`probe` 执行 contention audit，并为每个 case 写可恢复 checkpoint；`publish` 校验后更新 manifest 和公共 index。未完成 audit 的 case 可以留在 candidate manifest，但不能被解释为 canonical informative case。

## 从 SimAI 生成真实 DAG

SimAI 查找顺序为：

1. 环境变量 `SIMAI_FLOW_SCHEDULER_ROOT`；
2. `third_party/simai-flow-scheduler/`；
3. 开发环境中与本仓库同级的 `simai-flow-scheduler/`。

独立发布时推荐固定 submodule：

```powershell
git submodule update --init --recursive
```

`simai/common_export.py` 只负责解析、建图、固定路由和时长换算；`preemptive_export.py` 与 `nonpreemptive_export.py` 分别写入各自的 Schema 和调度语义。communication 时长按 `ceil(size_bytes / bandwidth)` 转成整数微秒。

导出单通道 benchmark：

```powershell
python -m benchmark_generate.simai.preemptive_export `
  --aicb path/to/workload.txt `
  --mode zero_bubble `
  --id zb_example `
  --output my_benchmark.json
```

增加 `--topology` 后，导出器会通过 SimAI 的 BFS 路由把每条 flow 转成固定 directed-link 和 NIC resource set，并生成 `muti_channel` benchmark：

```powershell
python -m benchmark_generate.simai.preemptive_export `
  --aicb path/to/workload.txt `
  --mode 1f1b `
  --topology path/to/topology.json `
  --id routed_example `
  --output routed_example.json
```

省略 `--aicb` 会使用一个很小的确定性输入，适合检查环境。支持的模式为 `1f1b`、`interleaved_1f1b`、`zero_bubble`、`bidirectional` 和 `dualpipe`。

生成完成后，使用者不应再需要 SimAI。提交 real benchmark 时应记录 workload、pipeline mode、带宽和 topology 来源，但不要提交私有输入或大型原始 trace。

## 格式注意事项

- `duration` 必须转换为整数时间单位，communication duration 必须大于零。
- task ID 必须唯一，依赖必须存在且无环。
- 单通道通信必须且只能使用 `channel:0`。
- 多通道通信必须列出完整固定资源集合，包括需要建模的 link/NIC 冲突。
- route 只在生成阶段计算，算法阶段不会重新选路。
- 不得把抢占或连续带宽比例共享偷偷编码进 v1 数据。
- 修改已提交问题后必须更新 `index.jsonl` 和对应 reference hash。

## 验证

```powershell
$env:PYTHONPATH="src;."
python -m pytest tests/test_generators.py tests/test_benchmark_format.py -q
python -m pytest tests/integration -q
```

第二条命令需要可用的 SimAI checkout；纯随机、固定反例和参考答案生成不需要 SimAI。
