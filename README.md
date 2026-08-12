# DAG scheduling benchmark and algorithms

这个仓库研究大模型训练 DAG 的通信调度，同时维护不可抢占主线和通信可暂停恢复的实验模型。两种模型共享语言无关的 DAG benchmark 和依赖语义，但使用不同状态机、算法与结果校验，不能混用结论。

Benchmark 使用普通 JSON，Python 和 C++ 都可以直接读取。算法代码不依赖 SimAI；只有从 AICB workload 导出真实 DAG 时才需要可选的 SimAI checkout。

## 目录

```text
benchmark/
  single_channel/
    parallel_chain/{random,adversarial,real}/
    complex_chain/{random,adversarial,real}/
  muti_channel/{random,adversarial,real}/
  preemptive/single_channel/... # v2 通信可暂停恢复样例
  reference_results/          # 小型 adversarial 样例的精确最优值
  schema/                     # JSON Schema

benchmark_generate/           # 随机、固定反例和真实 DAG 的生成工具
src/
  benchmark/                  # JSON loader 和 validator
  core/                       # 公共状态机、转换和精确 Oracle
  single_channel/
    parallel_chain/           # 并行链算法与接口
    complex_chain/            # 含 fork/join 的单通道算法与接口
  muti_channel/               # 固定多资源路径的算法与接口
  preemptive/                 # 可抢占状态机、接口和初始算法
  registry.py                 # 文件场景到算法的注册表
  cli.py                      # 统一运行入口
tests/                        # 与上述结构对应的测试
docs/                         # 研究记录、证明和实验总结
third_party/                  # 可选 SimAI submodule 位置
```

`muti_channel` 保留项目约定的目录名。它表示通信可以占用不同的固定资源集合；资源集合不相交的通信可以并行。

## 当前场景和限制

| 路径 | 问题 |
|---|---|
| `single_channel/parallel_chain` | 多条互相独立的计算—通信交替链共享一个 channel |
| `single_channel/complex_chain` | 带 fork、join 和多层依赖的 DAG 共享一个 channel |
| `muti_channel` | 一般 DAG 中的通信占用一个或多个固定 link/NIC 资源 |

v1 不可抢占模型的限制：

- 任务不可抢占；
- 依赖是 finish-to-start；
- ready compute 自动开始，计算资源约束需要预先写成 DAG 边；
- 通信在持续时间内独占其全部资源；
- 不在算法中重新选路，也不模拟按比例共享带宽；
- 时间是整数，目标是最小化 makespan；
- 精确 Oracle 面向小图，不适合作为大图在线调度器。

v2 可抢占模型中 compute 仍不可抢占；communication 可在任务事件处暂停、释放资源，并从剩余进度恢复。当前抢占代价和最小时间片均为零。单通道提供 priority、Rollout、Beam、Monte Carlo 和小图 Exact；多资源提供 compatible packing、set rollout 和小图 Exact。路由与资源集合固定，不模拟真实 collective 的 chunk 同步或恢复开销。

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
dag-schedule benchmark/preemptive/single_channel/complex_chain/adversarial/preemption_unlock.json --algorithm longest_tail
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

完整 JSON 约定见 [benchmark/README.md](benchmark/README.md)，机器可读约束见 `benchmark/schema/dag-benchmark-v1.schema.json` 和 `dag-benchmark-v2.schema.json`。

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

当前固定集合共 139 个问题：75 个既有不可抢占问题和 64 个 v2 可抢占问题。reference results 包含 33 个不可抢占 adversarial 与 21 个在预算内完成 Exact 的可抢占 adversarial；Exact 超时的实例不会生成最优标签。

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
