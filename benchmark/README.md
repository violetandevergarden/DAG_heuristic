# DAG Benchmark 数据集

`benchmark/` 保存可由 Python、C++ 或其它语言直接读取的调度问题。每个 JSON 都是完整、自包含的 DAG；使用数据不需要安装本仓库的算法，也不需要 SimAI。

本 README 同时是数据集说明和格式规范。v1 描述不可抢占模型，v2 描述通信可暂停恢复模型；机器可读约束分别见 `schema/dag-benchmark-v1.schema.json` 和 `schema/dag-benchmark-v2.schema.json`。

## 目录结构

```text
benchmark/
├── index.jsonl
├── schema/
│   ├── dag-benchmark-v1.schema.json
│   └── dag-benchmark-v2.schema.json
├── single_channel/
│   ├── parallel_chain/
│   │   ├── random/
│   │   ├── adversarial/
│   │   └── real/
│   └── complex_chain/
│       ├── random/
│       ├── adversarial/
│       └── real/
├── muti_channel/
│   ├── random/
│   ├── adversarial/
│   └── real/
├── preemptive/
│   └── single_channel/
│       └── complex_chain/{random,adversarial,real}/
└── reference_results/
    ├── single_channel/
    │   ├── parallel_chain/adversarial/
    │   └── complex_chain/adversarial/
    └── muti_channel/adversarial/
```

`muti_channel` 不再增加 `complex_chain` 中间目录。其 JSON 中的 `family` 仍为 `complex_chain`，因为它允许一般 fork/join DAG。

## 三种问题场景

### `single_channel/parallel_chain`

多条独立的计算—通信交替链共享一个 channel。每个节点的入度和出度都不超过 1，没有跨链 fork/join，可以使用紧凑 DP、二分判定和专用 heuristic。

### `single_channel/complex_chain`

一般单通道 DAG，可以包含 fork、join、多层依赖、PP/TP/DP 角色和 optimizer barrier。所有 communication 都使用 `channel:0`；计算节点可以并行，除非 DAG 边显式限制它们。

### `muti_channel`

一般 DAG 中的 communication 可以占用一个或多个固定排他资源，例如 link、NIC 或共享上行链路。资源集合不相交的通信可以并行；一条通信开始后持续占用全部所需资源直到完成。

### `preemptive/single_channel`

使用 v2 语义的单通道 DAG。目录内部仍按 `parallel_chain` 和 `complex_chain` 区分结构；当前只提交一个用于验证暂停、切换和恢复的 complex-chain 小图。该目录与 v1 数据物理隔离，避免只看路径时误用执行语义。

## 数据分类

- `random`：未经过结果筛选的固定 seed 随机样例，用于平均表现和健壮性测试。每个场景提交约 10 个，更多样例由使用者生成。
- `adversarial`：手工构造或从随机实验中筛出的困难实例，用于攻击特定贪心、WAIT、Rollout 或 Beam 决策。
- `real`：从 LLM pipeline DAG、collective 结构或小型真实拓扑转换、缩减、投影得到的固定快照。

“由随机生成器产生”不一定属于 `random`。如果某个随机实例因为能够击败某种算法而被挑选出来，它应放在 `adversarial`。

## 当前数据规模

当前共有 76 个问题：

| 场景 | random | adversarial | real | 合计 |
|---|---:|---:|---:|---:|
| `single_channel/parallel_chain` | 10 | 13 | 2 | 25 |
| `single_channel/complex_chain` | 10 | 16 | 7 | 33 |
| `muti_channel` | 10 | 4 | 3 | 17 |
| `preemptive/single_channel/complex_chain` | 0 | 1 | 0 | 1 |
| 总计 | 30 | 34 | 12 | 76 |

能够从历史实验精确恢复的代表性反例已经固化，包括：

- Longest-tail、LRPT double-count、5/4 和 tight-2 构造；
- 固定 Beam 反例；
- `random_chain_14/52/60/70/77/86/98`；
- `random_join_23/30/40/46/60`；
- `combined_chain_14/70/86`；
- 多资源下的 disjoint/shared route、非最大启动和 active reservation。

没有保存原始结构、无法由 seed 或历史 fixture 确定复现的临时样例没有被猜测性重建。

## JSON 核心字段

```json
{
  "schema_version": "1.0",
  "id": "example",
  "scenario": "single_channel",
  "family": "complex_chain",
  "category": "adversarial",
  "objective": "makespan",
  "time_unit": "tick",
  "semantics": {
    "preemptive": false,
    "decision_epoch": "task_completion",
    "optional_idle": true,
    "compute_model": "unbounded_parallel",
    "resource_model": "exclusive"
  },
  "resources": [{"id": "channel:0", "kind": "channel"}],
  "tasks": [
    {
      "id": "flow0",
      "kind": "communication",
      "duration": 3,
      "dependencies": [],
      "resources": ["channel:0"]
    }
  ]
}
```

### 顶层字段

| 字段 | 类型 | 必需 | 含义 |
|---|---|---:|---|
| `schema_version` | string | 是 | 当前固定为 `1.0` |
| `id` | string | 是 | 数据集内稳定且唯一的问题 ID |
| `scenario` | string | 是 | `single_channel` 或 `muti_channel` |
| `family` | string | 是 | `parallel_chain` 或 `complex_chain` |
| `category` | string | 是 | `random`、`adversarial` 或 `real` |
| `objective` | string | 是 | 当前固定为 `makespan` |
| `time_unit` | string | 是 | 通常为 `tick`，也可以记录 `us` |
| `semantics` | object | 是 | v1 的执行语义，取值由 Schema 固定 |
| `resources` | array | 是 | communication 可以独占的资源 |
| `tasks` | array | 是 | DAG 节点 |
| `metadata` | object | 否 | 来源、seed 和生成参数等非语义信息 |

v1 不允许未知顶层字段。增加可选 metadata 不需要提高 major version；增加必需字段或改变执行语义必须发布新的 major version。

### Resource

```json
{"id": "channel:0", "kind": "channel"}
```

- `id` 必须是非空且在问题内唯一的字符串。
- 算法应把资源 ID 当作不透明字符串，不依赖命名规则推断冲突。
- `kind` 用于分析和展示，不改变排他占用语义。
- resource 可以包含可选 `metadata`，但算法正确性不能依赖非标准 metadata。

### Task

```json
{
  "id": "flow_0",
  "kind": "communication",
  "duration": 5,
  "dependencies": ["release_0"],
  "resources": ["channel:0"],
  "metadata": {"role": "pp"}
}
```

- `id` 必须在问题内唯一。
- `kind` 只能是 `compute` 或 `communication`。
- `duration` 必须是整数；compute 可以为零，communication 必须大于零。
- `dependencies` 中的 ID 必须存在，不能包含自身、重复项或形成环。
- compute 的 `resources` 必须为空。
- communication 必须至少引用一个已定义资源，且同一资源不能重复。
- `metadata` 可以记录 PP/TP/DP role、phase、layer 等辅助信息，但不改变依赖和资源语义。

### 场景附加约束

- `single_channel`：问题必须恰好定义 `channel:0`，每个 communication 必须恰好使用 `["channel:0"]`。
- `parallel_chain`：每个节点入度和出度均不超过 1，每个弱连通分量应为一条 compute/communication 交替链。
- `muti_channel`：可以定义任意数量的排他资源，一条 communication 可以同时占用多个资源；其 `family` 固定为 `complex_chain`。

其它语言实现 Loader 时至少检查：

- task/resource ID 唯一；
- dependency 引用存在且 DAG 无环；
- communication duration 为正；
- compute 不占用通信资源；
- communication 引用的资源存在；
- 单通道问题严格使用唯一 `channel:0`；
- `parallel_chain` 节点入度和出度不超过 1。

## 调度语义

### v1：不可抢占

- compute 和 communication 都不可抢占，开始后必须连续执行到完成。
- `dependencies` 是 finish-to-start 依赖。
- ready compute 自动开始；有限 GPU 串行关系应已经表示为 DAG 边。
- communication 在整个持续时间内独占 `resources` 列出的全部资源。
- 调度器只在任务完成事件后选择新的通信动作。
- 资源空闲时允许主动等待到未来的释放事件。
- 目标固定为最小化 DAG makespan。
- v1 使用整数时间；compute 可以为零，communication 必须大于零。

这里研究的是任务开始顺序，不是可抢占带宽分片，也不是连续带宽比例分配。

### v2：通信暂停与恢复

v2 保持同一 DAG、finish-to-start 依赖、自动启动 compute 和固定资源集合，但只允许 communication 暂停：

- compute 一旦开始仍连续运行到完成；
- communication 被调度后运行到自身完成或下一个 compute 完成事件；
- 在事件处可继续原通信、暂停后切换到另一个 eligible 通信，或主动 WAIT；
- 暂停立即释放 channel，恢复时沿原固定资源集合继续剩余工作；
- 当前 `preemption_cost=0`、`minimum_quantum=0`，不模拟迁移、重路由或按比例共享带宽；
- 当前可执行实现只支持 `single_channel`，多资源可抢占状态机尚未实现。

```json
"semantics": {
  "preemption": "communication_resume",
  "decision_epoch": "task_event",
  "optional_idle": true,
  "compute_model": "unbounded_parallel",
  "resource_model": "exclusive_fixed_set",
  "preemption_cost": 0,
  "minimum_quantum": 0
}
```

`task_event` 在当前实现中指 communication 完成或 compute 完成形成的离散决策点。一次通信可以对应多个执行区间，但这些区间长度之和必须等于其 `duration`。

## 使用数据

Python：

```powershell
$env:PYTHONPATH="src;."
```

```python
from benchmark import load_benchmark

case = load_benchmark(
    "benchmark/single_channel/complex_chain/adversarial/random_join_30.json"
)
print(case.benchmark_id, len(case.tasks))
```

C++ 或其它语言可以直接按照本 README 和 JSON Schema 实现 Loader，无需调用 Python。

运行仓库算法：

```powershell
python src/cli.py benchmark/muti_channel/adversarial/nonmaximal_start_np.json --algorithm rollout_optional2
```

## `index.jsonl`

索引每行是一个 JSON object，包含 benchmark `id`、相对路径 `path`、`scenario`、`family`、`category` 和问题文件 SHA-256。

使用者可以读取索引遍历数据集，不必自己扫描目录。问题文件变化后必须更新索引，避免缓存或实验结果继续引用旧内容。

## 精确参考结果

`reference_results/` 镜像问题文件相对路径，只保存答案，不重复保存 DAG。当前 33 个 adversarial 小图都有 reference：

```json
{
  "schema_version": "1.0",
  "benchmark_id": "random_join_30",
  "benchmark_sha256": "...",
  "oracle": "exact_optional",
  "optimal_makespan": 22
}
```

使用 reference 前必须核对 SHA-256。哈希不一致说明问题已经变化，旧答案不能继续使用。仓库测试会重新运行 Exact Oracle 核对全部 reference，而不只是检查格式和哈希。

## 添加或修改问题

推荐通过生成模块统一序列化、校验和索引：

```powershell
$env:PYTHONPATH="src;."
python -m benchmark_generate all --samples 10 --seed 260819 --output benchmark
python -m benchmark_generate reference --output benchmark
```

手工添加 JSON 时：

1. 选择正确的场景和 category。
2. 按目标语义选择 v1 或 v2，明确时间单位、依赖和资源。
3. 用 Python Loader 验证文件。
4. 更新 `index.jsonl`。
5. adversarial 小图应重算 reference；random 和大型 real 图通常不生成 exact 标签。
6. 添加测试并说明该样例覆盖的语义或算法失败模式。

不要在问题 JSON 中写 heuristic 或最优答案，避免算法读取 metadata 获得答案；答案属于 `reference_results/`。

## 注意事项

- `real` 表示来自真实结构或拓扑的缩减/投影，不表示包含完整训练迭代。
- 当前 real 小图主要用于语义和结构回归，不能单独支持大规模性能结论。
- 多通道文件已经固定 route/resource set，算法不应改变路径。
- 大型 Exact Oracle 可能指数爆炸，超时或未完成的结果不能标记为 optimal。
- 发布后尽量保持 ID 和路径稳定；语义不兼容的格式变化应提升 schema major version。

## 格式兼容性

- reader 必须拒绝未知 major version，不能静默猜测新格式语义。
- JSON 文件统一使用 UTF-8；仓库生成器使用稳定 key 排序和 LF 换行。
- ID 比较区分大小写。
- JSON Schema 负责字段类型和枚举等机器可读约束；DAG 无环、依赖存在以及 parallel-chain 结构仍需 Loader 做语义检查。
