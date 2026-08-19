# Zero Bubble B/W 语义修复记录与后续研究报告

## 一、结论摘要

Zero Bubble workload 的同层 `B -> W` 数据依赖已经修复。修复只作用于
`ZeroBubblePipelineWorkloadBuilder`，不会改变 1F1B、GPipe、Interleaved 等公共 builder
的既有语义。

修复后的原始数据 DAG 为：

```text
saved activation_i -------+
                           +--> B_i --> B_{i-1}
incoming grad_output_i ----+
                           +--> W_i --> DP_i

all W/DP terminals ------------------> optimizer
```

更精确地说，同层 B 和 W 共享开始条件：

$$
\operatorname{pred}(B_i)=\operatorname{pred}(W_i)=\{A_i,G_i\},
$$

其中 $A_i$ 是本层保存的 activation 条件，$G_i$ 是来自下一层或下一 pipeline stage
的输出梯度条件。修复并不是简单令 `F_i -> W_i`；只依赖前向会错误地允许 W 在
`grad_output` 到达前执行。

需要注意，导出的 benchmark 还会把 `ZeroBubbleSerializer` 给出的单 GPU compute order
编码成依赖边。这些边表达资源执行顺序，不是 B/W 的数据依赖。因此报告和审计现在分别统计：

- raw data DAG 中的同层 `B -> W`；
- serializer 加入 compute order 后的 effective DAG 顺序。

## 二、原问题与修复范围

公共 `WorkloadBuilder._wire_backward_chain()` 对所有 pipeline 模式建立两类边：

```text
B_i -> W_i
B_i -> B_{i-1}
```

这个公共实现是一种保守的普通反向执行顺序。Zero Bubble builder 原来完整复用了它，
只额外建立 W/DP terminal 到 optimizer 的 barrier，因此原始数据 DAG 中保留了同层
`B_i -> W_i`。

本次没有修改公共 `_wire_backward_chain()`。原因是公共修改会同时改变其他 pipeline
策略和已有测试，而当前语义修复仅由 Zero Bubble 需要。

## 三、实现方法

### 3.1 子模块中的核心改动

修改文件：

- `third_party/simai-flow-scheduler/src/workload_generator/builders/zero_bubble_pipeline_builder.py`
- `third_party/simai-flow-scheduler/tests/test_zero_bubble_pipeline_builder.py`

Zero Bubble builder 先让公共 builder 完成全部构图，包括 PP send/recv 依赖；随后记录 B/W
配对 sidecar，最后执行 `_decouple_backward_weight()`：

```python
workload = super().build_from_aicb(...)
self._record_task_info(workload)
self._decouple_backward_weight(workload)
```

对于每个 W，使用 sidecar 找到同层、同 micro-batch、同 rank 的 B，并执行：

```python
w_task.deps = deduplicate(b_task.deps)
```

选择在完整构图后复制 `B.deps` 很重要。此时 B 的前驱已经包含：

- pipeline 边界处收到的 PP gradient；
- interior layer 中来自下一层 B/TP backward collective 的梯度；
- 本 micro-batch 已经完成相应 forward activation 的条件。

因此 W 与 B 同时 ready，但二者互不构成祖先关系。W 自己到 DP flow 的边，以及所有 W/DP
terminal 到 optimizer 的 gating 均未改变。

实现还加入了两个防御检查：每个 W 必须找到配对 B，并且 B/W 必须位于同一个 node。

### 3.2 DAG heuristic 仓库中的审计修正

修改文件：

- `benchmark_generate/simai/repetition.py`
- `benchmark_generate/simai/repetition_study.py`
- `tests/preemptive/test_repetition.py`

旧的 `direct_b_to_w_edges` 指标只要发现 W 的直接父节点中存在任意 B 就计数。这会把合法的
`B_{i+1} -> W_i` 梯度传播误判成错误的同层 `B_i -> W_i`。现在利用 sidecar 的
`b_task_id` 精确判断是否属于同一个 B/W pair；没有 sidecar 时才退化到
`iteration/layer/item/stage` 匹配。

研究脚本也不再黑名单 ZB，而是显式输出 `raw_data_b_to_w_edges`。只有 ZB 原始数据图中该值
为零时，ZB 行才允许用于调度结论。

## 四、验证结果

### 4.1 依赖语义探针

在以下三组受控配置中检查全部 B/W pair：

| PP/TP/DP | GA | layers | B/W pair | 无同层 B→W | B/W 前驱完全相同 |
|---|---:|---:|---:|---:|---:|
| 2/1/1 | 4 | 2 | 20 | 20 | 20 |
| 2/2/2 | 4 | 2 | 80 | 80 | 80 |
| 4/1/1 | 8 | 4 | 136 | 136 | 136 |

结果说明所检查的 236 个 pair 全部实现了共享 readiness。

合成结构网格覆盖 PP=2/4、GA=2 到 16。所有 ZB 行均满足：

```text
raw_data_b_to_w_edges = 0
usable_for_scheduling_conclusion = true
```

serializer 生效后的 effective benchmark 仍可能含同层 B→W 顺序。例如 PP=2 的受控图有 4 条，
PP=4 有 8 条。这是每个 stage 的本地 compute order，不表示修复失败。

### 4.2 测试

子模块定向测试：

```text
tests/test_zero_bubble_pipeline_builder.py             7 passed
tests/test_workload_builder.py + serializer tests     45 passed
```

子模块完整测试：

```text
784 passed, 9 skipped, 18 errors
```

18 个 error 全部发生在 topology/routing fixture 初始化阶段，原因是本地缺少
`astra-sim-alibabacloud/inputs/topo/Spectrum-X_...` 文件，不涉及此次修改。

DAG heuristic 主仓库完整测试：

```text
66 passed
```

修复后的完整重复结构实验输出：

- `docs/preemptive研究/preemptive阶段5_ZB语义修复后实验结果.json`

ZB 小型调度探针中，GA=2 时 Exact 与 Longest-tail/Rollout-2 makespan 相同；GA=4 时
Longest-tail 与 Rollout-2 相同。当前 coupling-aware 策略分别差约 0.186% 和 0.093%。这说明
语义修复解除了研究障碍，但现有简单的 role priority 仍没有表现出独立收益。

## 五、修复后能说明什么、不能说明什么

现在可以可靠研究：

- W 相对 B 的延后自由度；
- DP 通信的 slack 和 optimizer deadline；
- micro-batch 间 W/DP 与 PP backbone 通信的冲突；
- 对称压缩或周期模板对 ZB 通信调度的作用。

当前仍不能宣称 heuristic 会自动发现完整 Zero Bubble schedule。原因是 DAG heuristic 的
现有导出模型仍固定 serializer 的 GPU compute order，调度器只决定通信服务。修复只分离了
真实数据依赖，没有把 GPU compute 也变成可选调度资源。

因此需要区分两个研究问题：

1. **固定 ZB compute schedule 下优化通信。** 当前模型已经可以做，这是近期主线。
2. **联合决定 F/B/W compute 与通信顺序。** 需要显式 GPU compute resource 和新的联合 Oracle，
   属于后续更大的模型扩展。

## 六、下一步研究方案（已被结构化 DAG 算法总计划取代）

本节是完成 B/W 修复时针对 Zero Bubble 局部问题拟定的初步方案，范围过窄，也容易把固定
pipeline compute order 与网络 flow 调度混在一起。后续研究不再以本节作为执行计划。

新的主计划仍基于 `260804组会.md` 的 DAG 抽象，见：

- `preemptive阶段7_LLM结构化DAG调度算法研究计划.md`

新计划固定训练 DAG 和计算执行，只研究 ready communication 的组合排序、状态压缩、动态规划、
Rollout/Beam 与多 Job/多资源推广；ZB 仅作为具有 B/W 分叉和 barrier side branch 的一类 DAG。

### 阶段 A：固定 ZB compute order 的通信调度

1. 从 AICB 导出不同 PP、GA、TP、DP 的修复后 ZB 图。
2. 按 micro-batch/stage 提取 PP backbone、W、DP 和 optimizer milestone。
3. 对 W/DP 定义动态 slack，而不是静态 role bonus：

$$
s_i(t)=d_i(t)-t-p_i-r_i(t),
$$

其中 $d_i$ 是不延误 optimizer 或下一关键 milestone 的 latest finish，$p_i$ 是当前通信剩余量，
$r_i$ 是其后续必要尾长。
4. 生成候选时同时保留：最长 residual tail、最小 slack、即将释放 PP gradient、以及资源互补集合。
5. 用 Rollout 对候选做端到端评价，避免把局部 ZB bonus 直接当作 makespan 收益。

首要问题是验证：W/DP 是否真的存在可利用 slack，以及这种 slack 是否跨 micro-batch 稳定重复。

### 阶段 B：重复结构作为状态压缩，而不是固定复制顺序

将同 `(stage, phase, layer, collective_step)` 的任务归一为 motif，状态记录：

```text
(phase, microbatch frontier, active PP wave, W backlog, DP backlog,
 resource occupancy, optimizer slack)
```

只在边界状态等价时合并对称 micro-batch。跨 micro-batch 存在依赖或资源冲突时，不能复制单周期
最优顺序。阶段 5 已经证明严格独立复制可以达到渐近 1.5 倍，因此周期模板必须带 carry-in/
carry-out state。

### 阶段 C：单 Job 与多 Job 分层结合

每个 Job 内部用 ZB 语义产生少量候选：

- PP backbone critical candidate；
- 最小 optimizer slack 的 W/DP candidate；
- 与其他候选资源互补的 candidate。

全局层只接收候选及粗粒度 summary，再按 makespan、weighted JCT 或 fairness 做端到端 rollout。
优先在 2 Job Exact 小窗中校准 K=1/2/4，然后扩展到 3--4 Job。

### 阶段 D：联合 compute/communication 调度，可作为独立后续方向

若要让算法自主发现 `B, F, W` 排布，需要：

- 为每个 GPU 建立容量为 1 的 compute resource；
- compute 和 communication 都成为可选择启动的任务；
- 数据依赖只保留真实依赖；
- serializer 仅作为 baseline 或 warm start，不再写入 DAG；
- Exact/Beam 状态同时记录 GPU 与网络资源占用。

这一扩展的搜索空间显著更大，建议先完成阶段 A--C，确认通信侧收益上限后再决定是否投入。

## 七、同步到 SimAI 原仓库的方法

本次真正属于 SimAI 子模块、需要在原仓库提交的只有两个文件：

```text
src/workload_generator/builders/zero_bubble_pipeline_builder.py
tests/test_zero_bubble_pipeline_builder.py
```

建议在 `third_party/simai-flow-scheduler` 中创建独立分支并提交，例如：

```powershell
cd third_party/simai-flow-scheduler
git switch -c fix/zero-bubble-bw-dependency
git add src/workload_generator/builders/zero_bubble_pipeline_builder.py
git add tests/test_zero_bubble_pipeline_builder.py
git commit -m "Fix Zero Bubble B/W data dependencies"
git push -u origin fix/zero-bubble-bw-dependency
```

合并并推送 SimAI 原仓库后，回到 DAG heuristic 仓库更新 gitlink：

```powershell
cd ../..
git add third_party/simai-flow-scheduler
git commit -m "Update SimAI submodule for Zero Bubble B/W semantics"
```

不要把 DAG heuristic 的本地 `docs/` 提交到远端。`benchmark_generate/simai/repetition*.py`
和 `tests/preemptive/test_repetition.py` 属于 DAG heuristic 仓库，不应放进 SimAI 原仓库提交。
