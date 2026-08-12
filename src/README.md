# 调度算法代码

`src/` 保存可以脱离 SimAI 独立运行的调度模型、Exact Oracle 和 heuristic。这里不再增加 `dag_heuristic/` 包装层，目录名直接对应问题场景。

## 目录结构

```text
src/
├── benchmark/
│   ├── model.py               # Benchmark、Task、Resource 数据类
│   ├── loader.py              # JSON 读取、写出和字典转换
│   └── validator.py           # DAG、资源和场景语义校验
├── core/
│   ├── dag.py                 # 内部 DAG、节点和拓扑工具
│   ├── model.py               # 单通道不可抢占事件状态机与时间线
│   ├── oracle.py              # 一般单通道小图 Exact Oracle
│   ├── resource.py            # 多资源实例表示
│   ├── conversion.py          # Benchmark 到三类内部输入的转换
│   └── interface.py           # 公共轻量接口
├── single_channel/
│   ├── parallel_chain/
│   │   ├── interface.py       # 并行链算法输入/输出约定
│   │   └── solver.py          # 并行链算法和精确方法
│   └── complex_chain/
│       ├── interface.py       # 复杂 DAG 算法输入/输出约定
│       └── solver.py          # fork/join DAG heuristic
├── muti_channel/
│   ├── interface.py           # 多通道算法输入/输出约定
│   └── solver.py              # 固定多资源路径上的调度算法
├── preemptive/
│   ├── core/model.py          # 通信暂停/恢复事件状态机、Trace 和校验
│   ├── single_channel/        # 可抢占接口与 Longest-tail baseline
│   └── muti_channel/          # 后续多资源扩展接口（尚无实现）
├── registry.py                # 按场景注册并选择算法
└── cli.py                     # 面向 benchmark 文件的统一入口
```

`muti_channel` 是本项目约定的目录名，表示通信可以占用不同的固定资源集合，不表示算法会动态选路。

## 三类算法

### `single_channel/parallel_chain`

输入为 `tuple[ParallelChain, ...]`。每条链包含通信时长 `comm`、通信后的计算时长 `compute` 和首次通信前的 `initial_delay`。

主要实现：

- `longest_tail`：选择剩余计算尾部最长的 ready flow；
- `rollout_flow2`：尝试两个候选 flow，用基线补全后选择较好者；
- `rollout_wait2`：在 flow 候选之外加入主动等待；
- `beam_wait8/32`：保留有限个较优部分状态；
- `exact_dp` 以及用于交叉验证的二分判定、分支限界方法。

### `single_channel/complex_chain`

输入为 `BenchmarkDAG`，支持 fork、join、多层依赖和不同通信角色。所有通信仍共享唯一 channel。

主要实现包括 residual Longest-tail、Join bonus、Rollout-flow、Rollout-WAIT、两层候选搜索、Beam 和小图 Exact Oracle。

### `muti_channel`

输入为 `MultiResourceInstance`。每条通信关联固定 resource set，执行期间同时独占集合中的全部资源；资源集合不相交的通信可以并行。

主要实现：

- `longest_tail_pack`：按 Longest-tail 排序并启动兼容任务；
- `resource_pack`：结合剩余资源负载排序；
- `bottleneck_pack`：优先处理瓶颈资源任务；
- `rollout_maximal2`：比较最大兼容启动集合；
- `rollout_optional2`：允许非最大启动集合和主动等待；
- 多资源小图 Exact Oracle。

### `preemptive/single_channel`

输入仍为一般 `BenchmarkDAG`，执行则由独立的 `PreemptiveDAGModel` 定义。通信运行到下一个任务事件时保存剩余工作，算法随后可以继续它或切换通信。当前只提供动态 residual Longest-tail 作为最小 baseline；Exact Oracle、Rollout、Beam 和多资源版本留待后续实现。

## 从 JSON 运行

安装项目后：

```powershell
dag-schedule benchmark/single_channel/parallel_chain/adversarial/tight_optional_wait_m20.json --algorithm longest_tail
dag-schedule benchmark/preemptive/single_channel/complex_chain/adversarial/preemption_unlock.json --algorithm longest_tail
```

不安装也可以从仓库根目录运行：

```powershell
$env:PYTHONPATH="src;."
python src/cli.py benchmark/single_channel/complex_chain/adversarial/random_join_30.json --algorithm rollout_wait2
```

列出可用算法或写出结果：

```powershell
python src/cli.py path/to/case.json --list-algorithms
python src/cli.py path/to/case.json --algorithm exact_optional --output result.json
```

Python 调用：

```python
from benchmark import load_benchmark
from registry import solve

case = load_benchmark("benchmark/single_channel/parallel_chain/random/random_chain_0.json")
result = solve(case, "longest_tail")
print(result.makespan)
```

也可以直接导入对应场景的 `solver.py` 并传入内部数据类型，但处理公开 benchmark 时优先使用 Loader 和 registry。

## 添加新算法

1. 根据问题类型选择 `parallel_chain`、`complex_chain` 或 `muti_channel`。
2. 阅读同目录的 `interface.py`。算法必须接受该场景的标准输入，并返回带整数 `makespan` 的结果。
3. 在 `solver.py` 中实现；代码较大时可以新建含义明确的文件，不要增加无意义的包层。
4. 在 `src/registry.py` 注册公开名称、适用场景、说明、WAIT 和 exact 能力。
5. 在对应 `tests/` 目录添加回归测试，并选择至少一个能区分新算法与已有 baseline 的固定 benchmark。
6. 新发现的稳定反例应保存到 `benchmark/**/adversarial/`，不要只藏在动态测试函数里。

算法不得从 metadata 读取最优答案。有限 benchmark 上全部最优不能替代理论近似比证明。

### 添加可抢占算法

可抢占算法放在 `preemptive/` 下，并复用 `PreemptiveDAGModel.step` 推进状态，不得自行按 tick 改写另一套依赖语义。稳定决策状态由 `ScheduleState` 表示；合法动作是运行/恢复一个 eligible communication 或 WAIT。算法结果使用 `PreemptiveScheduleResult`，Trace 必须通过 `assert_preemptive_trace`。

当前 `preemptive.single_channel.solver.schedule_longest_tail` 在每个任务事件重新计算 residual critical tail，是一般 DAG 的初始 work-conserving baseline，不具有已证明的最优性或常数近似保证。新增算法后在 `registry.py` 的可抢占注册表中登记，并用 v2 benchmark 与状态机测试验证。

## 重要语义和限制

- v1 中 communication 和 compute 都不可抢占，开始后必须运行到完成。
- 调度器只在任务完成事件后重新决策，channel 空闲时允许主动等待。
- ready compute 自动开始；有限 GPU 串行约束必须预先编码为 DAG 边。
- 多通道算法不重新选路，资源集合已经包含在输入中。
- 当前不模拟连续带宽比例共享；通信在完整持续时间内独占所需资源。
- Exact Oracle 只适合小图，用于标注、反例验证和 heuristic 对照。
- v2 当前只允许单通道 communication 在任务事件处零代价暂停/原资源恢复；compute 仍不可抢占，多资源状态机和可抢占 Exact Oracle 尚未实现。
- `src/` 禁止导入 `benchmark_generate`、SimAI 或修改 `sys.path`。

## 测试

```powershell
$env:PYTHONPATH="src;."
python -m pytest tests/core_logic tests/single_channel tests/muti_channel -q
python -m pytest tests/test_file_algorithms.py tests/test_benchmark_format.py -q
```

完整测试运行 `python -m pytest -q`。集成测试只有在能够发现 SimAI checkout 时才执行。
