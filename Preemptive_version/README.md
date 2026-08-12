该文件夹内考虑研究可抢占的 DAG 通信调度。暂时仅考虑单个 channel 的情况。

文件夹中 old 部分为旧版代码，主要使用 c++ 。由于不想写文档，以及为了统一，应该是弃用了吧（？

由于个人习惯，主要算法部分可能会使用 c++ 。会尽可能做好与 python 对接。

除上方区别外，尽可能与不可抢占式的保持一致。（但暂时可能会先补齐个人使用部分内容）

（以及是不是不应该把 readme 当留言板用？）

# DAG scheduling benchmark and algorithms

所有代码默认在当前目录运行。

这个目录研究可抢占 DAG 通信调度。每个计算节点在就绪时会立即开始计算；每个通讯节点在开始后可以被其他通信节点打断，没有额外的打断惩罚，后续可以从被打断位置继续通讯；调度器输出通信节点的处理优先级，~~由 `docs/proove` 证明根据优先级，可以确定一个较优解~~（还没写，可在 `old/docs` 里找到之前的证明）。

暂时只考虑 单channel 的情况。

Benchmark 使用普通 JSON，Python 和 C++ 都可以直接读取。

## 目录

```text
benchmark/
  single_channel/
    parallel_chain/{random,adversarial,real}/
    complex_chain/{random,adversarial,real}/
  reference_results/          # 小型样例的精确最优值
  schema/                     # JSON Schema
  index.jsonl                 # 数据点列表

src/
  benchmark/                  # JSON loader 和 validator
  core/                       # 根据优先级序列计算耗时代码 和 精确 Oracle
  single_channel/             # 单channel 问题下的算法
  build_index.py              # 重新生成 ./benchmark/index.jsonl
  test.py                     # 运行算法代码，并将其与已有的reference_results对比（目前测试内容硬编码，待修改）
  reference.py                # 尝试为 ./benchmark/single_channel 中的所有测试点生成 reference_results
docs/                         # 研究记录、证明和实验总结（暂无）
```

## 当前场景和限制

| 路径 | 问题 |
|---|---|
| `single_channel/parallel_chain` | 多条互相独立的计算—通信交替链共享一个 channel |
| `single_channel/complex_chain` | 带 fork、join 和多层依赖的 DAG 共享一个 channel |

共同限制：

- 任务可抢占；
- 依赖是 finish-to-start；
- ready compute 自动开始，计算资源约束需要预先写成 DAG 边；
- 通信在持续时间内独占其全部资源；
- 不在算法中重新选路，也不模拟按比例共享带宽；
- 时间是整数，目标是最小化 makespan；
- 精确 Oracle 面向小图，不适合作为大图在线调度器。

# 以下复制自不可抢占部分，暂未修改，可能有误

## 使用

安装开发环境：

```powershell
python -m pip install -e ".[dev]"
```

这一步足以加载已有 benchmark、开发和运行调度算法，但不包含可选的 SimAI
转换依赖。若要从 AICB/SimAI workload 生成真实 DAG，请先初始化 submodule，
并额外安装其 Python 项目：

```powershell
git submodule update --init --recursive
python -m pip install -e "./third_party/simai-flow-scheduler"
```

SimAI 当前要求 Python 3.13，并在自己的 `pyproject.toml` 中声明
`jsonschema`、`matplotlib`、`pyyaml` 等额外依赖；该文件是这部分依赖的事实来源。

运行算法：

```powershell
dag-schedule benchmark/single_channel/parallel_chain/adversarial/tight_optional_wait_m20.json --algorithm longest_tail
dag-schedule benchmark/muti_channel/adversarial/nonmaximal_start_np.json --algorithm rollout_optional2
```

不安装命令行入口也可以运行：

```powershell
$env:PYTHONPATH="src;."
python src/cli.py benchmark/single_channel/complex_chain/adversarial/random_join_30.json --algorithm rollout_wait2
```

列出某个问题支持的算法：

```powershell
dag-schedule path/to/case.json --list-algorithms
```

Python 加载 benchmark：

```python
from benchmark import load_benchmark

case = load_benchmark("benchmark/single_channel/parallel_chain/random/random_chain_0.json")
```

完整 JSON 约定见 [benchmark/README.md](benchmark/README.md)，机器可读约束见 `benchmark/schema/dag-benchmark-v1.schema.json`。

## 增加算法

1. 在 `src/single_channel/parallel_chain`、`src/single_channel/complex_chain` 或 `src/muti_channel` 中选择对应场景。
2. 阅读 `src/README.md` 和对应场景的 `interface.py`，实现接受相同输入并返回含整数 `makespan` 的结果。
3. 在 `src/registry.py` 注册算法名称。
4. 在对应的 `tests/` 子目录添加回归测试。
5. 若算法针对一种失败模式，把固定样例放入相应的 `adversarial/`，并更新精确参考结果。

算法不得从 metadata 读取答案，也不得依赖 `benchmark_generate` 或 SimAI。

## 增加 Benchmark

- `random`：仓库每种场景只保留约 10 个固定 seed 样例；更多样例由使用者自行生成。
- `adversarial`：保存手工反例和历史实验中可精确复现的失败样例。
- `real`：保存从 LLM DAG 或实际拓扑缩减、投影得到的固定快照。

重新生成默认集合：

```powershell
$env:PYTHONPATH="src;."
python -m benchmark_generate all --samples 10 --seed 260819 --output benchmark
python -m benchmark_generate reference --output benchmark
```

仓库通过 `.gitattributes` 强制 `benchmark/` 中的 JSON/JSONL 使用 LF，生成器也会
显式写入 LF。reference result 中的 SHA-256 是对 benchmark 原始字节计算的，因此
不要用会擅自改写换行符的工具保存这些文件；遵守该规则后，不同平台上的哈希应保持一致。

当前固定集合共 75 个问题：每个场景各有 10 个 random，另有 33 个带精确最优值的 adversarial 和 12 个 real 快照。

## 测试

```powershell
$env:PYTHONPATH="src;."
python -m pytest -q
```

`tests/integration/` 会在找不到 SimAI 时跳过；Loader、Oracle 和算法测试不需要 SimAI。

## SimAI 集成

需要从 SimAI 生成新 benchmark 时，推荐连同 submodule 一起克隆：

```powershell
git clone --recurse-submodules https://github.com/violetandevergarden/DAG_heuristic.git
```

如果已经完成普通 clone，再执行：

```powershell
git submodule update --init --recursive
```

独立仓库中的可选位置是 `third_party/simai-flow-scheduler/`。只有 `benchmark_generate/simai/` 和对应集成测试允许依赖它。生成出来的 JSON 必须独立可读，使用算法和已有数据时无需初始化 submodule。

SimAI 的 `inputs/topologies/` 默认忽略具体拓扑文件。仓库集成测试使用自身携带的最小拓扑；导出真实多通道 benchmark 时，需要通过 `--topology` 指定使用者本地的拓扑文件。
