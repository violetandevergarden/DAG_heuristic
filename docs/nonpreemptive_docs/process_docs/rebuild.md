# `muti_channel/preemptive` 最终收尾计划

> 编写日期：2026-09-09
>
> 状态：已完成
>
> 范围：只整理 `src/muti_channel/preemptive/` 的算法模块、命名和调用入口，不修改公共模拟语义

## 一、当前状态

当前 `src/muti_channel/preemptive/` 已经只剩以下实现文件：

```text
completion.py
constructors.py
interface.py
packing.py
solver.py
```

此前讨论的以下薄文件或 Stage 4 文件已经从该目录移除：

```text
trace.py
result.py
selective_rollout.py
barrier.py
features.py
```

对应职责已经或应当由以下位置承担：

- trace 合法性验证：`core.trace.pree_multi`；
- Exact：`core.oracle.pree_multi`；
- barrier：`llm_structured.preemptive`；
- selective rollout：`llm_structured.preemptive.multi_selective_rollout`；
- Stage 4 结构特征：`llm_structured`；
- family 通用结果：直接使用正式结果合同，不再增加只有一个别名的包装文件。

目前主要问题已经不再是错误的目录归属，而是剩余文件的名称和职责仍不够清楚：

1. `solver.py` 仍然过重，混合基础策略、集合评分、搜索、Exact 兼容转发、结果回放和指标统计；
2. `constructors.py` 名称过宽，看不出它只负责 packing 候选集合构造；
3. `completion.py` 单独存在虽然合理，但如果目标是减少文件数量，可以与基础策略合并，不能重新塞回过重的 `solver.py`；
4. `interface.py` 仍通过 solver 间接取得所有算法，新代码没有直接依赖职责明确的模块；
5. tests、experiments、benchmark generator 和 `llm_structured` 仍有不少代码直接导入 `muti_channel.preemptive.solver`。

## 二、目标结构

建议将最终目录整理为：

```text
src/muti_channel/preemptive/
├── __init__.py
├── interface.py
├── solver.py
├── search.py
├── packing.py
└── packing_constructors.py
```

各模块职责如下。

### `interface.py`

只负责：

- 保存通用多资源可抢占算法注册表；
- 校验算法名称和参数；
- 调用 `solver.py`、`search.py` 或 `core.oracle.pree_multi`；
- 保持现有公开算法名称稳定。

不得负责：

- 重新实现 Exact；
- 状态推进；
- Stage 4 barrier、selective rollout 或综合算法；
- 动态导入 `llm_structured`。

### `solver.py`

负责通用、确定性的 family 策略和评分：

- `schedule_pack`；
- `schedule_set_policy`；
- `score_tasks`；
- `score_sets`；
- `select_best_scored_set`；
- `greedy_fill_from_task_scores`；
- `complete_pack`；
- `CompletionCache`；
- 这些函数直接依赖的 residual tail、resource load、reachable 等内部辅助函数。

`completion.py` 的内容合并到这里。这样可以减少一个文件，同时避免 `constructors → solver` 的循环依赖。

### `search.py`

负责通用多资源搜索：

- `rollout_sets`；
- 搜索预算异常；
- rollout 状态缓存；
- fallback 和搜索统计；
- 如仍决定把 bounded packing 作为通用 family 算法保留，则暂时包括 `schedule_bounded_packing`。

需要特别审查 `schedule_bounded_packing`。它的注释和配置仍使用 Stage 4c 名称。如果它只服务 Stage 4c 实验，应移到：

```text
src/llm_structured/preemptive/multi_packing.py
```

如果它已成为不读取 LLM 结构、适用于任意 fixed-resource DAG 的通用有界 packing 算法，可以留在 `search.py`，但要删除 Stage 4c 专属注释和配置命名。不能同时在两个目录保存实现。

### `packing.py`

继续负责 packing 的基础合同和合法性工具：

- `PackingBudget`；
- `DecisionBudget`；
- `PackingStats`；
- `PackingResult`；
- `ConflictGraph`；
- `build_conflict_graph`；
- `validate_maximal_action`；
- `complete_maximal`；
- `iter_maximal_actions`。

这个文件名与当前职责相符，不需要更名。

### `packing_constructors.py`

由当前 `constructors.py` 更名而来，只负责有界 packing 候选构造：

- `greedy`；
- `multi_seed`；
- `one_exchange`；
- `enumerate_bounded`；
- `choose_by_depth1_longest_tail`。

名称改为 `packing_constructors.py`，避免将来与 DAG 构造器、benchmark 构造器或其他算法构造器混淆。

## 三、具体迁移映射

建议按下表迁移当前 `solver.py` 内容：

| 当前内容 | 目标位置 | 说明 |
|---|---|---|
| `schedule_pack` | `solver.py` | 通用 greedy packing 基线 |
| `schedule_set_policy` | `solver.py` | 通用集合评分策略，只保留非 barrier mode |
| `score_tasks` | `solver.py` | 只允许通用 fixed-resource 分数 |
| `score_sets` | `solver.py` | 只允许通用集合分数 |
| `greedy_fill_from_task_scores` | `solver.py` | 通用极大集合填充 |
| residual tail/resource load/reachable | `solver.py` | 作为内部只读辅助函数 |
| `remaining_lower_bound` | `solver.py` 或 core Oracle | heuristic 使用则留在 solver；Exact 专用则只留 core |
| `rollout_sets` | `search.py` | 通用有预算搜索 |
| `schedule_bounded_packing` | `search.py` 或 `llm_structured` | 先按是否通用作一次明确判断 |
| `_BudgetExceeded`、搜索统计 | `search.py` | 不暴露为 family 公共接口 |
| `multi_resource_statistics` | `metrics.py` 或调用方 | 若只有 experiments 使用，直接移到实验/结构化指标模块 |
| `result_from_actions` | `solver.py` | 通用动作回放与结果组装；合法性仍调用 core trace |
| Exact 三个转发函数 | `interface.py` 或临时兼容层 | 正式实现只在 `core.oracle.pree_multi` |
| 状态 key 兼容函数 | core Oracle 或测试审计入口 | family 不保留第二套 Exact key 语义 |

迁移 `completion.py`：

| 当前内容 | 目标位置 |
|---|---|
| `CompletionCache` | `solver.py` |
| `complete_pack` | `solver.py` |
| completion cache 测试 | 改为测试 `solver.py` 的公开接口 |

迁移 `constructors.py`：

| 当前路径 | 新路径 |
|---|---|
| `muti_channel.preemptive.constructors` | `muti_channel.preemptive.packing_constructors` |

## 四、推荐实施顺序

## 阶段 1：建立收尾前测试基线

先运行：

```powershell
python -m pytest -q tests/muti_channel/preemptive --disable-warnings
python -m pytest -q tests/core/trace/preemptive --disable-warnings
python -m pytest -q tests/llm_structured --disable-warnings
python -m pytest -q
```

记录：

- 测试数量和耗时；
- 现有算法名称；
- 固定小图的 makespan、动作序列和 trace；
- Exact compressed/uncompressed 结果；
- completion cache hit/miss；
- packing 候选数和 fallback。

本阶段不修改任何代码。

## 阶段 2：收敛 `solver.py`

1. 保留 `solver.py` 作为通用多资源可抢占基础算法的正式实现模块。
2. 将 rollout、bounded search、Exact 转发和仅供实验使用的指标从 `solver.py` 移出，只留下基础评分、greedy packing、set policy、completion 和结果组装。
3. 将 `completion.py` 的 `CompletionCache`、`complete_pack` 合并到 `solver.py`。
4. `packing_constructors`、`search` 和 `llm_structured` 统一从 `solver.py` 导入所需的通用基础算法。
5. 删除 `completion.py`。
6. 更新 completion cache 测试导入路径。

验收要求：

- `solver.py` 不导入 `search.py` 或 `packing_constructors.py`；
- `complete_pack` 仍只调用公共模拟器推进；
- cache 开关前后的最终状态、动作序列和 makespan 一致；
- completion cache key 继续只在已证明未来等价的稳定状态上使用；
- 定向测试通过。

## 阶段 3：更名 packing 构造器

1. 将 `constructors.py` 更名为 `packing_constructors.py`。
2. 更新 `search.py`、`llm_structured`、tests 和 experiments 的导入。
3. 确认新模块只构造候选动作，不拥有时间推进语义。
4. 确认 `choose_by_depth1_longest_tail` 通过 `solver.complete_pack` 完成后缀评估。
5. 删除旧文件，不同时保留两个实现。

验收要求：

- `rg` 不再找到 `muti_channel.preemptive.constructors`；
- 构造器生成的每个动作都通过 core 模型合法性检查；
- 操作、集合和 completion 预算仍为硬上限；
- packing 合同测试通过。

## 阶段 4：建立 `search.py`

1. 从 `solver.py` 移入 `rollout_sets` 和相关搜索统计、预算异常。
2. 判断 `schedule_bounded_packing` 是通用 family 算法还是 Stage 4c 算法：
   - 通用：移入 `search.py`，删除 Stage 4c 专属命名；
   - Stage 4c：移入 `llm_structured/preemptive/multi_packing.py`。
3. `search.py` 只组合 `solver`、`packing` 和 `packing_constructors`。
4. rollout 必须继续保留确定性 LT fallback。
5. 不得将 barrier 或 selective rollout 搬回通用 search。

验收要求：

- `search.py` 不导入 `llm_structured`；
- `solver.py` 不反向导入 `search.py`；
- 搜索预算、候选数、completion calls 和 fallback 统计保持原口径；
- 相同输入、相同预算下动作序列和 makespan 不变。

## 阶段 5：收敛 interface 和 Exact 入口

1. 将 `interface.py` 的注册表直接绑定到：
   - `solver.schedule_pack`；
   - `solver.schedule_set_policy`；
   - `search.rollout_sets`；
   - 通用或 Stage 4 所属位置的 bounded packing；
   - `core.oracle.pree_multi.exact_oracle`；
   - `core.oracle.pree_multi.exact_oracle_uncompressed`。
2. registry 继续只调用 interface，不直接调用具体 solver。
3. benchmark reference 生成器的 Exact 入口改为 core Oracle 或 family interface。
4. experiments 应优先通过 interface 或明确的公开算法模块调用，不依赖兼容 solver。
5. Stage 4 算法继续通过 `llm_structured.preemptive.multi_interface` 注册。

验收要求：

- `interface.py` 不导入整个 `solver` 模块；
- registry 不直接调用 multi-channel solver Exact；
- 通用算法列表中没有 barrier 和 selective rollout；
- CLI 和现有公开算法名称保持不变。

## 阶段 6：收敛 `solver.py` 的公开职责

先用 `rg` 列出所有仍直接导入 `muti_channel.preemptive.solver` 的调用方，并分三类处理：

### 仓库内部正式代码

`src/` 内调用必须迁移到职责明确的模块：

- 基础策略导入 `solver`；
- 搜索导入 `search`；
- Exact 导入 `core.oracle.pree_multi`；
- Stage 4 算法导入 `llm_structured`。

### tests、benchmark generator 和 experiments

- 测试应测试正式所有者，不再用 solver 聚合入口掩盖归属；
- reference generator 使用 core Oracle；
- Stage 3 实验使用 family interface、solver 或 search；
- Stage 4 实验使用 `llm_structured`。

### 外部兼容

`solver.py` 继续作为基础策略的正式模块，不再计划删除。历史调用方如果从
`solver.py` 导入 rollout 或 Exact，可在迁移期保留薄转发；薄转发只能指向
`search.py` 或 `core.oracle.pree_multi`，不能在 solver 中保留第二份实现。
内部调用方迁移完成后，再删除这些非基础策略的兼容转发。

验收要求：

- `solver.py` 只实现通用基础策略、评分、completion 和结果组装；
- 不通过函数内 import 隐藏循环依赖；
- 不出现 `solver → search` 或 `solver → packing_constructors`；
- `packing_constructors`、`search` 和 `llm_structured` 可以单向复用 solver 的基础策略，但不能让 solver 反向依赖它们；
- `src/` 中不再通过 solver 调用 Exact、rollout 或 Stage 4 聚合入口。

## 阶段 7：指标归属收尾

审查 `multi_resource_statistics` 的真实调用方：

- 如果属于 Stage 3 通用评估，可放入 `muti_channel/preemptive/metrics.py`；
- 如果只被 experiments 使用，移到对应实验公共工具；
- 如果 Stage 4 算法需要，放入 `llm_structured` 的指标模块；
- 不要仅为一个无调用函数创建新文件。

family 可以收集自己算法的候选数、cache hit、fallback 等指标，但公共 trace 合法性仍只由 `core.trace` 判定。

## 阶段 8：最终验证和停止

运行：

```powershell
python -m pytest -q tests/muti_channel/preemptive --disable-warnings
python -m pytest -q tests/core --disable-warnings
python -m pytest -q tests/llm_structured --disable-warnings
python -m pytest -q
```

另外执行依赖检查：

```powershell
rg -n "from llm_structured|import llm_structured" src/muti_channel
rg -n "muti_channel\.preemptive\.solver" src tests benchmark_generate experiments
rg -n "muti_channel\.preemptive\.(completion|constructors)" src tests benchmark_generate experiments
```

最终验收标准：

- `muti_channel` 不导入 `llm_structured`；
- Exact 和 trace 继续分别只有 `core.oracle`、`core.trace` 中的一份正式实现；
- barrier 和 selective rollout 只存在于 `llm_structured`；
- `completion.py` 已并入 `solver.py`；
- `constructors.py` 已明确更名为 `packing_constructors.py`；
- `solver.py` 已收敛为通用基础策略模块，不再混合搜索、Exact 和 Stage 4 逻辑；
- 没有模块循环依赖；
- 原有算法名称、动作序列、makespan 和 trace 合法性没有非预期变化；
- completion cache、搜索预算和 fallback 统计仍可观察；
- 完整测试通过。

达到以上标准后应停止本轮重构。不要继续为了让文件数量完全对称而拆分 `packing.py`，也不要在没有真实调用证据时新增抽象层。

## 五、风险和注意事项

### 1. 合并 `completion.py` 前先拆出搜索职责

`completion.py` 可以并入 `solver.py`，但必须先把 `schedule_bounded_packing`、
`rollout_sets` 及其对 packing constructors 的依赖移到 `search.py`。最终依赖只能是
`packing_constructors/search → solver`，不能保留 `solver → packing_constructors` 的反向边。

### 2. 不要把 Stage 4c 名称留在通用算法中

`schedule_bounded_packing` 的归属必须明确。通用算法不应使用 Stage 4c 配置版本；Stage 4c 特化实现也不应留在通用 family interface。

### 3. 不要通过复制实现维持旧导入

兼容入口只能再导出正式实现。复制 `complete_pack`、评分或 Exact 会重新产生两套行为。

### 4. 不要修改 core 语义

本轮剩余工作原则上不需要修改 `core.execution`、`core.oracle` 或 `core.trace`。如果整理过程中发现必须修改 core，应停止并单独请示，修改后报告影响和完整测试结果。

### 5. 不要顺便更名 `muti_channel`

该名称虽然拼写不标准，但已经是公开包名和 benchmark scenario。本轮只调整其内部文件，不进行顶层包迁移。

## 六、实施记录模板

每完成一个阶段，在本节追加：

```text
阶段：
日期：
修改文件：
删除文件：
调用方迁移：
语义影响：
兼容影响：
定向测试：
完整测试：
未完成事项：
```

## 七、实施结果（2026-09-09）

- `completion.py` 已合并到 `solver.py`，缓存测试改用正式接口。
- `constructors.py` 已更名为 `packing_constructors.py`，旧路径已删除。
- 新增 `search.py`，承载 `rollout_sets` 和 bounded packing；`solver.py` 保留通用基础策略、评分、completion 和结果组装。
- `metrics.py` 承载 `multi_resource_statistics`，不再把实验指标混入 solver。
- `interface.py` 直接绑定基础策略、search 和 `core.oracle.pree_multi`，不再导入整个 solver 模块，也不注册 barrier/selective rollout。
- Exact、trace、barrier 和 Stage 4 selective rollout 的正式实现位置保持在各自职责目录。

依赖检查通过：`src/muti_channel` 不导入 `llm_structured`，旧的 `completion.py`、`constructors.py` 及其他已删除路径无残留引用。定向测试 117 项通过；完整测试：`274 passed in 131.43s`。

本轮收尾已完成，停止继续拆分。`packing.py` 未因文件数量对称而继续拆分，`muti_channel` 包名也未修改。

## 八、不可抢占目录的轻量合并计划（重新确认）

本节于 2026-09-09 再次写入并确认，内容专门对应 `result.py`、`priorities.py`、`solver.py` 和 `replay.py` 的合并与依赖清理。

> 状态：已完成
>
> 范围：`src/muti_channel/nonpreemptive/result.py`、`priorities.py`、`solver.py` 和 `replay.py`
>
> 目标：删除没有独立价值的包装文件，保留决策上下文缓存，同时消除 replay 对 solver 的反向类型依赖

### 8.1 当前判断

`result.py` 目前只有一个类型别名：

```python
from core.oracle.nonpree_multi import (
    MultiResourceOracleResult as ResourceSchedule,
)
```

它没有自己的字段、行为或兼容转换，不构成独立的 family 结果合同，可以完全删除。

`priorities.py` 不是空包装，它包含：

- `ResourceDecisionContext`；
- `build_context`；
- `context_for`；
- residual path、tail、ready flow 和 resource load 的状态级复用。

但是当前只有 `solver.py` 和对应测试直接使用这些内容，尚未形成多个实现模块共享的公共边界；而且文件名叫 `priorities.py`，实际主要承担“决策状态上下文缓存”，并不完整负责优先级算法。以当前规模，将它合并进 `solver.py` 更直接。

### 8.2 目标目录

合并后建议保留：

```text
src/muti_channel/nonpreemptive/
├── __init__.py
├── interface.py
├── solver.py
└── replay.py
```

职责划分：

- `interface.py`：算法名称、模式和参数绑定；
- `solver.py`：通用 greedy、rollout、决策上下文、候选生成和 Exact 兼容转发；
- `replay.py`：通过公共模型回放动作，组装 family 指标；
- Exact 正式实现继续位于 `core.oracle.nonpree_multi`；
- trace 合法性正式实现继续位于 `core.trace.nonpree_multi`。

### 8.3 删除 `result.py`

实施步骤：

1. 在 `solver.py` 中直接导入：

```python
from core.oracle.nonpree_multi import (
    MultiResourceOracleResult as ResourceSchedule,
    exact_oracle as core_exact_oracle,
)
```

2. 在 `replay.py` 中直接从 `core.oracle.nonpree_multi` 导入 `MultiResourceOracleResult`，需要保留现有名称时可以在导入处使用 `as ResourceSchedule`。
3. 更新所有仍导入 `muti_channel.nonpreemptive.result` 的测试或调用方。
4. 删除 `src/muti_channel/nonpreemptive/result.py`。
5. 不新建另一个只包含同一别名的包装文件。

兼容影响：

- `ResourceSchedule` 的实际类型不变；
- makespan、actions、intervals、等待统计和 fallback 字段不变；
- 只删除仓库内部的间接导入路径；
- 如果确认该路径属于外部公开接口，应先在 `nonpreemptive/__init__.py` 提供一次兼容再导出，否则直接迁移内部调用方。

### 8.4 将 `priorities.py` 合并进 `solver.py`

迁移以下内容：

```text
ResourceDecisionContext
build_context
context_for
```

建议把它们放在 `residual_resource_loads` 之后、`_ranked_ready` 之前，使代码顺序成为：

```text
residual_resource_loads
ResourceDecisionContext
build_context
context_for
lower_bounds
_ranked_ready
greedy_action
complete
schedule_greedy
候选生成和 rollout
```

合并时必须消除重复 resource-load 扫描。`build_context` 应复用现有 `residual_resource_loads`：

```python
def build_context(model, state):
    path, tail = model.residual_features(state)
    return ResourceDecisionContext(
        ready=tuple(model.ready_flows(state)),
        path=path,
        tail=tail,
        loads=residual_resource_loads(model, state),
    )
```

不能把 `priorities.py` 中的 resource-load 循环原样复制进 solver，同时又保留 `residual_resource_loads`，否则只是减少文件，没有减少重复逻辑。

后续步骤：

1. 更新 `solver.py` 内部导入和类型标注；
2. 将 `tests/muti_channel/nonpreemptive/test_streaming_candidates.py` 改为从 solver 导入 `context_for`；
3. 检查其他调用方是否真正需要直接使用 `ResourceDecisionContext`；
4. 删除 `src/muti_channel/nonpreemptive/priorities.py`；
5. 保留现有 context cache 行为和命中测试。

### 8.5 同时消除 replay 对 solver 的反向类型导入

当前 `replay.py` 从 solver 导入：

```python
from .solver import NonPreeMultiModel, ResourceAction
```

这两个类型属于公共执行模型，不属于 family solver。应改为：

```python
from core.execution.nonpreemptive import (
    NonPreeMultiModel,
    ResourceAction,
    ResourceInterval,
)
```

这样依赖方向变成：

```text
core.execution / core.oracle / core.trace
                    ↓
          solver        replay
                    ↓
                 interface
```

`solver.py` 可以在 `_replay()` 内调用 `replay_actions`，但 `replay.py` 不再反向依赖 solver。若没有其他循环原因，也可以评估是否取消函数内延迟导入；没有必要仅为追求顶层导入而扩大改动。

### 8.6 不迁移 Stage 4c packing

本次合并不在 `muti_channel/nonpreemptive` 新建与可抢占目录对称的 `packing.py`。当前较复杂的不可抢占 packing 位于：

```text
src/llm_structured/nonpreemptive/packing/
```

它包含 optional-idle challenger、局部交换、集合特征、completion selector 和 Stage 4 预算，属于 Stage 4c 研究算法。保持在 `llm_structured` 符合当前职责边界。

只需要顺手修正其中不合理的类型导入：

```python
from muti_channel.nonpreemptive.solver import (
    NonPreeMultiModel,
    ResourceAction,
    ResourceState,
)
```

应改为直接从 `core.execution.nonpreemptive` 导入这些公共类型。真正的 family 策略 `complete` 仍可从 `muti_channel.nonpreemptive.solver` 导入。

是否把通用 conflict graph 或候选构造器下沉到 `muti_channel`，应等它们被证明适用于任意 fixed-resource DAG 并成为稳定通用算法后再决定；本轮不为了目录对称复制代码。

### 8.7 实施顺序

1. 运行不可抢占多资源定向测试并记录基线；
2. 修改 `replay.py`，让公共模型类型直接来自 core；
3. 删除 `result.py` 包装并更新导入；
4. 将 decision context 合并进 `solver.py`，复用 `residual_resource_loads`；
5. 删除 `priorities.py` 并更新测试；
6. 修正 `llm_structured/nonpreemptive/packing` 对公共模型类型的导入；
7. 运行依赖检查、定向测试和完整测试；
8. 在本节追加真实实施记录，未执行前不得标记完成。

### 8.8 验收条件

执行：

```powershell
python -m pytest -q tests/muti_channel/nonpreemptive --disable-warnings
python -m pytest -q tests/llm_structured/nonpreemptive --disable-warnings
python -m pytest -q tests/core/trace/nonpreemptive --disable-warnings
python -m pytest -q
```

依赖检查：

```powershell
rg -n "muti_channel\.nonpreemptive\.(result|priorities)" src tests benchmark_generate experiments
rg -n "from \.solver import.*NonPreeMultiModel|from \.solver import.*ResourceAction" src/muti_channel/nonpreemptive
```

最终必须满足：

- `result.py` 和 `priorities.py` 已删除；
- `ResourceSchedule` 的实际类型和字段没有变化；
- context cache 仍能复用相同不可变状态的分析结果；
- resource load 只保留一份计算逻辑；
- replay 不再从 solver 导入公共执行类型；
- Exact 和 trace 的正式实现位置不变；
- optional-idle/work-conserving 动作空间不变；
- Stage 4c packing 仍位于 `llm_structured`，没有为了目录对称复制实现；
- 定向测试和完整测试全部通过。

### 8.9 停止条件

完成以上合并后即可停止不可抢占目录的本轮轻量整理。`replay.py` 有独立的回放和指标组装职责，不需要继续并入 solver；`interface.py` 也应保持独立。后续只有在真实调用和性能证据支持时，才考虑进一步拆分 rollout 或提取通用 packing。

### 8.10 实施结果（2026-09-09）

- 删除 `src/muti_channel/nonpreemptive/result.py` 和 `priorities.py`。
- `ResourceSchedule` 直接使用 `core.oracle.nonpree_multi.MultiResourceOracleResult`，字段和行为保持不变。
- `ResourceDecisionContext`、`build_context`、`context_for` 已合并到 `solver.py`，并复用唯一的 `residual_resource_loads` 实现。
- `replay.py` 直接从 `core.execution.nonpreemptive` 导入公共模型、动作和区间类型，不再反向依赖 solver。
- Stage 4c packing 仍保留在 `llm_structured/nonpreemptive/packing/`，没有新增 family 对称实现。
- 依赖检查无残留旧导入；不可抢占定向测试 53 项通过；完整测试 `274 passed in 144.20s`。

第八节任务已完成，达到停止条件。
