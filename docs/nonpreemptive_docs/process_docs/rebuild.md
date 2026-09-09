# `llm_structured/common` 与 `llm_structured/nonpreemptive` 优化计划

> 编写日期：2026-09-09
>
> 状态：已完成
>
> 范围：`src/llm_structured/common/`、`src/llm_structured/nonpreemptive/` 及其仓库内调用者；允许为修正 common 归属而迁移文件到 `preemptive/` 并更新导入
>
> 明确排除：独立开展 `src/llm_structured/preemptive/` 的结构调整、算法修改或性能优化

## 一、基本约定

本轮不独立重构或优化 preemptive。当前 preemptive 结构已经合适，在新的需求、错误或性能证据出现前保持稳定。但如果清理 `common` 或修改 `nonpreemptive` 必然波及 preemptive，允许进行最小必要修改，包括接收从 common 迁入的 preemptive-only 文件、更新导入、更新包导出和调整对应测试。此类修改不得顺带改变 preemptive 算法、数据结构、动作选择或性能实现。

本轮不以文件行数作为拆分依据。是否修改只看：职责是否混杂、依赖方向是否正确、是否存在多个实现真源、名称是否准确，以及是否存在可测量的重复计算。文件较长但职责单一可以不动；文件很短但只是无价值转发也可以删除。

不得改变不可抢占语义：通信启动后连续完成，active communication 保留资源，optional-idle 与 work-conserving 分开。时间推进、依赖释放和资源占用由 `core.execution.nonpreemptive` 判定，trace 合法性由 `core.trace.nonpreemptive` 判定。

## 二、当前结构判断

### 2.1 `common`

```text
common/
├── __init__.py
├── barrier_features.py
├── packing_features.py
├── perturb.py
├── rollout_contracts.py
└── signatures.py
```

- `perturb.py` 是纯 DAG duration 扰动，归属合理；
- `signatures.py` 围绕重复结构扫描和证据分类，职责相关，不因文件较长强制拆分；
- `barrier_features.py` 虽然是只读分析，但当前调用者和所适配的状态接口都属于 preemptive barrier；
- `rollout_contracts.py` 的当前调用者属于 preemptive rollout，不是两条语义共享合同；
- `packing_features.py` 直接依赖 `muti_channel.preemptive.packing`，明确属于 preemptive；
- `common/__init__.py` 与各子模块的公开方式不完全一致。

### 2.2 `nonpreemptive`

```text
nonpreemptive/
├── barrier/
├── packing/
├── runtime/
└── selective_rollout/
```

方向划分基本合理，主要问题是：

1. `runtime` 容易被误解为另一套执行架构；
2. `runtime/replay.py` 实际是 baseline runner、指标组装和最终回放，不只是 replay；
3. `runtime/policies.py` 实际是基础算法选择，更接近 `solver.py`；
4. `selective_rollout/adapters.py` 和 `baseline.py` 只是兼容转发；
5. job id、job residual 和成员关系在多个模块重复解析；
6. barrier、packing、rollout 可能在同一决策点重复计算合法动作、tail、transition 和候选特征；
7. `selective_rollout/exact.py` 自行实现 residual-state 穷举，需要重新确认 Exact 归属；
8. 部分 experiments 直接导入内部文件或下划线函数，增加更名成本。

## 三、`common` 优化

### 3.1 common 准入标准

只有以下内容属于 common：

- 不实现某种抢占语义的动作选择；
- 不包含调度循环，不调用 `step` 推进状态；
- 不依赖具体语义 solver；
- 是语义中立的数据合同、DAG/benchmark 纯分析，或已被两条语义稳定复用的工具。

### 3.2 保留 `perturb.py`

只检查：随机种子可复现；零时长标记不变；依赖、任务类型、资源和 metadata 不变；大输入耗时保持线性。不做结构重构。

### 3.3 保留并优化 `signatures.py`

不因行数拆分。优先优化：

1. 一次扫描统一建立 task 索引、parents/children、role、micro-batch 和标签缓存；
2. 避免 local signature、twin groups 和 cross-dependency 重复解析 metadata；
3. conflict pair 继续受预算限制，明确 exact、sampled、truncated；
4. 给可能的二次复杂度路径增加计数或耗时测试；
5. 只有剖析证明内部阶段需要独立复用时才拆分。

内部命名可将 `_mb` 改为 `_micro_batch_index`；`_formal_labels` 只有在“formal”没有专门定义时才改为 `_semantic_labels`。

### 3.4 将三个 preemptive-only 模块移出 common

根据当前调用关系和动作语义，以下三个模块都不是真正跨语义：

```text
common/packing_features.py
common/barrier_features.py
common/rollout_contracts.py
```

迁移映射：

```text
common/packing_features.py
    -> preemptive/packing_features.py

common/barrier_features.py
    -> preemptive/barrier/analysis.py

common/rollout_contracts.py
    -> preemptive/selective_rollout/contracts.py
```

采用这些名称的原因：

- `packing_features.py` 当前只是 Stage 4 可抢占 packing 的轻量特征，尚不足以单独建立新的 packing 包；
- barrier 的 `analysis.py` 表示单候选的只读结构分析，与现有多资源动作集合 `features.py` 区分；
- rollout 的合同、预算记账和触发器目前共同服务同一个可抢占 rollout 框架，先整体迁入 `contracts.py`，不为了文件行数拆分。

迁移只允许：

1. 移动这三个文件；
2. 更新 preemptive、tests、experiments 和 benchmark generator 的导入；
3. 更新 `preemptive/barrier/__init__.py`、`preemptive/selective_rollout/__init__.py` 的必要导出；
4. 删除 common 中的旧实现，不保留两个真源；
5. 添加导入路径和动作结果回归测试。

迁移不允许：

- 修改 preemptive 的评分公式、候选集合或 rollout 预算；
- 顺便拆分 preemptive policy；
- 改变可抢占动作序列、makespan 或 trace；
- 让 nonpreemptive 导入这些模块。

迁移后，`common` 收敛为：

```text
common/
├── __init__.py
├── perturb.py
└── signatures.py
```

目录较小不是问题；这里只保存真正语义中立的 DAG/benchmark 分析工具。

### 3.5 迁移时保留原有分析职责

文件迁入 preemptive 后不进行独立性能优化。本轮只允许在 common 清理所必需的范围内保持或验证以下行为：

- barrier context、snapshot、action features 和路径估计仍是只读分析；
- rollout budget、trigger 和统计合同的字段及默认值不变；
- packing features 继续调用现有可抢占 conflict graph；
- 所有既有公开算法结果保持不变。

barrier descendants、arrival estimate 或 rollout trigger 的后续性能优化不属于本轮；只有它们阻碍 common 迁移正确性时才处理。

### 3.6 收敛 `common/__init__.py`

- 只再导出稳定、语义中立的公共工具；
- 大型分析通过明确子模块导入；
- 不把所有函数都提升到包顶层；
- 为现有公开符号增加导入测试；
- 不长期保留新旧名称双入口；
- 删除 barrier、rollout 和 packing 的 common 顶层再导出。

## 四、不可抢占目录命名优化

### 4.1 `runtime` 改为 `baseline`

`runtime` 容易暗示执行语义所有权。建议改为：

```text
nonpreemptive/baseline/
├── adapters.py
├── contracts.py
├── features.py
├── solver.py
├── completion.py
└── runner.py
```

对应迁移：

```text
runtime/policies.py -> baseline/solver.py
runtime/replay.py   -> baseline/runner.py
```

- solver 只选择基础动作；
- completion 从 residual state 用基础策略补全；
- runner 执行完整 baseline、计时、委托 trace 回放并组装指标；
- adapters 只能薄转发 core 模型。

先更新 src、tests、experiments，再删除旧目录。若没有正式仓库外兼容要求，不保留整个 runtime 兼容包。

### 4.2 统一 solver 命名

完整调度算法入口优先使用 `solver.py`：

- `runtime/policies.py` 改为 `baseline/solver.py`；
- `runtime/replay.py` 改为 `baseline/runner.py`；
- `barrier/policies.py` 可改为 `barrier/solver.py`；
- `packing/policy.py` 可改为 `packing/solver.py`；
- `selective_rollout/policy.py` 可改为 `selective_rollout/solver.py`。

`runner.py` 只做运行、计时和结果组装，不定义新策略。更名必须一次性迁移调用者，不复制实现。

## 五、删除薄转发

当前以下文件只有再导出：

```text
nonpreemptive/selective_rollout/adapters.py
nonpreemptive/selective_rollout/baseline.py
```

调用者改为从新的 `nonpreemptive.baseline` 正式入口导入，然后删除这两个文件。删除前用 `rg` 检查 tests 和 experiments，不在其他位置重新创建相同转发。

## 六、不可抢占性能优化

### 6.1 每个决策只建立一次 context

adapter 已有 `DecisionContext`，但部分 barrier、packing、rollout 路径仍重复请求 legal actions、tail、ready/startable、active、resources 和 next event。

优化：

1. 每个真实决策只构造一次 context；
2. baseline solver、barrier features、packing candidates 和 rollout trigger 接受可选 context；
3. context 同时保存稳定 tuple 与查询 frozenset；
4. 不跨状态复用动态 context；
5. observation 关闭时不计算只用于审计的字段。

验收：开关 metrics/observation 不改变动作序列和 makespan。

### 6.2 建立 `JobIndex`

当前 job 信息在 baseline solver、runner 和 rollout candidates 重复解析。adapter 初始化时建立：

```text
task_to_job
job_to_tasks
job_arrival
job_weight
job_order
```

动态 residual 和 job tail 仍按状态计算，但通过索引聚合，不再重复拆 task id 或扫描 metadata。`_job_rank_data` 可改为 `build_job_state_features`，`_job_id` 收敛为 `JobIndex.job_of`。

### 6.3 packing 特征复用

`packing/features.py::set_features` 当前对每个候选调用 residual features，并可能为每个候选执行 step。

优化：

- 一个决策点预先计算 tails、startable、occupied/all resources；
- 同一 action signature 缓存 transition 和 released；
- shared downstream 使用集合并集去重；
- 预算在昂贵操作前 reserve；
- 截断时回退合法 LT 并记录原因。

不得改变 active reservation、work-conserving 极大集合、optional-idle WAIT/非极大 challenger 和固定资源冲突判定。

### 6.4 selective rollout transition 复用

- feature 和 evaluator 使用同一个单次决策 transition cache；
- feature lookahead 已执行的第一跳直接交给 evaluator；
- completion cache key 包含 state、mode、policy 和版本；
- `max_cache_entries` 达限后停止写入；
- timeout 使用绝对 deadline；
- depth、width、completion calls、expanded states、feature transitions 分别记账。

### 6.5 barrier 复用 context

`BarrierGraph` 每实例只构造一次。baseline 和候选共享当前 context、tail、barrier descendants、已计算特征与 counterfactual completion，避免先求 baseline 后再次独立获取 legal actions。

### 6.6 runner 与指标成本

分开记录 context、solver、observation、simulator step、final trace validation 和 job metrics。`job_metrics_from_state` 使用 `JobIndex`，不再为每个 job 扫描全部任务。最终 trace 验证保留，但与算法耗时分开。

## 七、Exact 边界

`nonpreemptive/selective_rollout/exact.py::cost_to_go` 自行实现 residual-state 穷举。它只调用合法动作和 step，没有自建模拟语义，但 Exact 按约定应归 `core.oracle`。

本轮先：

1. 对拍初始状态上的 core Oracle 最优值；
2. 测试 state limit、time limit、无合法动作和确定性最优首动作；
3. 检查现有 core 是否已有 residual-state 接口；
4. 设计单 channel、多资源和两种 idle mode 的统一调用边界。

如需修改 core，必须先单独请示。未经批准不修改 `core.oracle`、不复制新 Exact，也不扩大该文件功能。

## 八、不做的修改

- 不独立重构或优化 `llm_structured/preemptive`；
- 除接收三个 preemptive-only 模块、更新导入与导出外，不修改 preemptive；
- 不因为文件较长拆分 signatures 或 barrier；
- 不为目录对称创建空模块；
- 不把 Stage 4 指标移入 core；
- 不让 family 目录反向依赖 `llm_structured`；
- 不改变不可抢占 packing 动作语义；
- 不在无剖析数据时增加跨状态缓存；
- 不修改 `muti_channel` 拼写。

## 九、实施顺序

### 阶段 1：基线与 common 归属迁移

1. 运行不可抢占专项和完整测试；
2. 保存公开导入清单；
3. 将 common 中的 packing、barrier、rollout 三个 preemptive-only 模块按第 3.4 节迁移；
4. 更新 src、tests、experiments 和 benchmark generator 的导入；
5. 验证 preemptive 动作、makespan 和 trace 不变；
6. 收敛 `common/__init__.py`；
7. 运行导入检查、preemptive 相关回归和 `llm_structured` 专项测试。

### 阶段 2：不可抢占命名迁移

1. `runtime` 更名为 `baseline`；
2. `policies.py`、`replay.py` 更名为 `solver.py`、`runner.py`；
3. 更新 src、tests、experiments；
4. 删除 rollout 的两个薄转发；
5. 运行不可抢占导入检查和专项测试。

### 阶段 3：context 与静态索引

1. 建立 `JobIndex`；
2. runner、solver、rollout 共用索引；
3. 每个决策只建立一次 context；
4. barrier 与 rollout 接受已有 context；
5. 验证 observation 开关不改变动作。

### 阶段 4：候选特征复用

1. packing 复用 tails、startable 和 resources；
2. 缓存同一候选 transition；
3. rollout 共享 feature/evaluator 第一跳；
4. barrier 复用 baseline/challenger 特征；
5. 保持预算和 fallback 可审计。

### 阶段 5：common 收尾

1. 优化 signatures 单次扫描索引；
2. 确认 common 只剩语义中立工具；
3. 检查三个旧 common 导入路径无残留；
4. 不因 signatures 的文件长度继续拆分；
5. 不对已迁入 preemptive 的模块继续重构或优化。

### 阶段 6：Exact 迁移设计

1. 给 cost-to-go 增加对拍和预算失败测试；
2. 检查现有 core residual-state 能力；
3. 需要 core 修改则提交方案并请示；
4. 获批后实施、完整测试并报告；
5. 未获批则明确记录待迁移并停止扩展。

### 阶段 7：真实性能验证

选择小图、中图、真实图和 multi-job，记录 benchmark id/hash、mode、算法、seed、预算、makespan、trace hash、分项耗时、候选/transition/cache/fallback/timeout 和峰值内存。只有动作或结果等价时比较优化前后性能。

## 十、测试与验收

```powershell
python -m pytest -q tests/llm_structured/test_barrier_features.py --disable-warnings
python -m pytest -q tests/llm_structured/test_selective_rollout_features.py --disable-warnings
python -m pytest -q tests/llm_structured/test_packing_features.py --disable-warnings
python -m pytest -q tests/single_channel/complex_chain/preemptive/test_selective_rollout.py --disable-warnings
python -m pytest -q tests/muti_channel/preemptive/test_multi_selective_rollout.py --disable-warnings
python -m pytest -q tests/llm_structured/nonpreemptive --disable-warnings
python -m pytest -q tests/llm_structured/nonpreemptive/packing --disable-warnings
python -m pytest -q tests/llm_structured/nonpreemptive/barrier --disable-warnings
python -m pytest -q tests/llm_structured --disable-warnings
python -m pytest -q
```

依赖检查：

```powershell
rg -n "llm_structured\.nonpreemptive\.runtime" src tests experiments benchmark_generate
rg -n "selective_rollout\.(adapters|baseline)" src tests experiments benchmark_generate
rg -n "from llm_structured|import llm_structured" src/core src/single_channel src/muti_channel
rg -n "muti_channel\.preemptive" src/llm_structured/common
rg -n "llm_structured\.common\.(packing_features|barrier_features|rollout_contracts)" src tests experiments benchmark_generate
```

验收条件：

- preemptive 只发生 common 归属迁移所需的文件接收、导入、导出和测试修改；
- preemptive 算法、评分、候选、预算、动作、makespan 和 trace 未改变；
- common 每个模块都有明确准入理由；
- common 不再包含 preemptive-only packing、barrier 或 rollout 模块；
- `runtime` 不再造成第二套执行架构的误解；
- baseline solver、runner、adapter、completion、指标职责清楚；
- 无价值转发删除；
- job 信息不在多个热路径重复解析；
- 单次决策 context、tail、transition 得到复用；
- optional-idle/work-conserving 行为不变；
- trace、makespan、确定性动作和指标通过回归；
- 性能改善有固定输入、分项耗时和内存证据；
- Exact 迁移遵守 core 请示和报告要求；
- 专项与完整测试通过。

## 十一、停止条件

满足第十节后结束本轮维护。不继续为了行数、目录外观或抽象一致性拆分文件。

以下情况允许保留现状并记录原因：文件较长但职责单一；拆分会引入循环依赖或多个真源；剖析没有显示热点；需要对 preemptive 进行超出 common 归属迁移的修改；需要修改 core 但尚未批准。

## 十二、实施记录模板

```text
阶段：
日期：
修改/删除/更名文件：
公开导入迁移：
preemptive 修改：无 / 仅 common 归属迁移（列出文件和导入）
执行语义影响：无 / 说明
core 修改批准：不涉及 / 待批准 / 已批准
定向测试：
完整测试：
性能样例与分项结果：
未完成事项：
```

## 十三、本轮实施记录（2026-09-09）

阶段 1--7 已完成；第十四节记录了后续复核项及本轮收尾结果。

- `common/packing_features.py`、`common/barrier_features.py`、`common/rollout_contracts.py` 已分别迁移到 `preemptive/` 对应目录；`common` 仅保留 `perturb.py` 和 `signatures.py`，顶层导出已收敛。
- `nonpreemptive/runtime` 已迁移为 `nonpreemptive/baseline`；`policies.py`、`replay.py` 分别更名为 `solver.py`、`runner.py`；调用者已更新，两个 selective rollout 薄转发已删除。
- barrier、packing、selective rollout 的不可抢占策略入口已统一为各自的 `solver.py`。
- baseline adapter 增加共享的 `JobIndex`，job 成员、到达时间、权重和顺序不再在热路径重复解析；单次决策继续复用 `DecisionContext` 中的 legal actions、tail、active、资源和 transition/completion cache。
- 未修改不可抢占执行、等待、资源占用或 trace 判定语义；未独立调整 preemptive 算法。
- 依赖检查：旧 `runtime`、旧 selective rollout 转发、旧 common 三个导入路径均无残留；core、single_channel、muti_channel 未反向导入 `llm_structured`。
- 定向测试：不可抢占及相关专项 `48 passed`；`llm_structured` 专项和迁移回归通过；编译检查通过。
- 阶段 6：`core.oracle.nonpree_single` 和 `core.oracle.nonpree_multi` 新增 residual-state Exact 入口；`selective_rollout/exact.py` 仅负责模型分派和结果转换，不再自行实现搜索。单通道、多资源及 optional-idle/work-conserving 均完成 family/core 对拍。
- 阶段 6 回归：新增 4 个 residual Exact 对拍测试；完整测试 `278 passed`。

## 十四、后续复核发现的未完成事项（2026-09-09）

### 14.1 当前可确认结果

以下工作已经完成，不需要重复实施：

- `common` 已只保留 `perturb.py` 与 `signatures.py`；
- 三个 preemptive-only 模块已经迁入 `preemptive`，旧 common 导入无残留；
- `nonpreemptive/runtime` 已迁移为 `nonpreemptive/baseline`；
- baseline、barrier、packing、selective rollout 的 solver/runner 命名已经收敛；
- selective rollout 的两个薄转发已经删除；
- `selective_rollout/exact.py` 已成为 core residual Exact 的薄分派层；
- 最新独立定向测试为 `68 passed in 0.83s`；
- 最新独立完整测试为 `278 passed in 226.88s`。

因此剩余工作只针对未完成的性能与边界收尾，不再调整已经稳定的目录结构。

### 14.2 `JobIndex` 尚未在所有热路径统一使用

`baseline/contracts.py` 已建立 `JobIndex`，baseline solver 的 `_job_id` 也已经委托 `adapter.job_index.job_of`。但是：

- `selective_rollout/candidates.py::_job_id` 仍然重新读取 task labels，并再次拆分 `task_id`；
- `_job_rank_data` 仍在每次排序前扫描 `adapter.model.tasks`；
- `job_arrival`、`job_order` 已进入 `JobIndex`，但排序逻辑仍重新构造 arrivals 和 available job 顺序；
- `JobIndex.job_weight` 当前统一写为 `1.0`，需要确认真实 multi-job metadata 的 weight 是否应在此处载入；如果权重只属于 runner 指标，应删除该未使用字段，避免产生错误含义。

需要完成：

1. 删除 rollout candidates 中独立的 `_job_id`，统一调用 `adapter.job_index.job_of`；
2. `generate` 接收已有 `DecisionContext`，避免重新调用 legal actions、tail 和 baseline context；
3. 将 `_job_rank_data` 改为通过 `job_to_tasks` 聚合，或在单次决策内只计算一次 `JobStateFeatures`；
4. `_multi_greedy` 在选择多个兼容任务时复用同一份 job residual、job tail 和 arrival，而不是每轮重新扫描全图；
5. 明确 `job_weight` 数据来源和唯一用途；
6. 添加测试，证明不同 job 命名、labels 优先级和无 job metadata 时的行为不变。

验收指标：记录每个决策的 task 扫描次数；multi-resource greedy 不应随已选择任务数量重复执行全图 job 聚合。

### 14.3 单次 `DecisionContext` 尚未贯通全部算法

baseline runner 已经复用 `DecisionContext`，但以下路径仍可能独立计算相同状态信息：

- selective rollout candidates 单独调用 `adapter.legal_actions`、`adapter.tail` 和 `baseline_action`；
- barrier solver 先调用 longest-tail，再单独获取 legal actions；
- packing solver/feature 没有统一接收包含 tails、startable 和资源信息的决策上下文。

需要完成：

1. selective rollout solver 每个真实决策建立一次 context，并传给 candidates、trigger、feature 和 baseline；
2. barrier solver 建立一次 context，并同时用于 LT baseline 和 challenger 特征；
3. packing 建立轻量 `PackingDecisionContext`，保存 tails、startable flows、occupied resources 和 all resources；
4. context 只在当前不可变 state 使用，不建立跨状态全局缓存；
5. observation/metrics 关闭时不计算审计专属数据；
6. 添加计数测试，验证每个决策的 residual tail 与 legal-action 构造次数。

验收要求：启用或关闭 observation、metrics 后，动作序列、makespan 和 trace hash 不变。

### 14.4 packing transition 与特征复用尚未落地

当前 `packing/features.py::set_features` 仍可能对每个候选：

- 重新调用 `model.residual_features(state)`；
- 重新获取 `startable_flows`；
- 执行 `model.step` 计算 released tasks；
- 重新计算 all resources、occupied resources 和 downstream union。

需要完成：

1. tails 从 `PackingDecisionContext` 传入；
2. action signature 到 transition/released 的缓存限定在单次决策；
3. candidate constructor 和 feature evaluator 共享 startable、occupied 与 resource universe；
4. shared downstream 先做集合去重；
5. 真正执行 step 或 descendants 遍历前进行预算 reserve；
6. 缓存未命中、命中、拒绝和 fallback 进入 `PackingDecision` 或结果 metrics。

不得改变 active reservation、optional-idle WAIT、非极大 challenger、work-conserving 极大集合和固定资源冲突判定。

### 14.5 barrier 特征复用尚未完全落地

需要完成：

1. `BarrierGraph` 保持每 benchmark 只构造一次；
2. baseline 与 challenger 使用同一个 `DecisionContext`；
3. baseline action 的 feature 不重复计算；
4. 同一候选的 counterfactual completion 按 action signature 在当前决策内复用；
5. descendants/reachable 结构量保存在 `BarrierGraph` 或单次实例静态缓存；
6. feature budget 在实际遍历和 completion 之前扣减。

如果剖析显示 barrier 路径不是实际热点，可只完成 context 贯通与计数，不增加复杂缓存。

### 14.6 阶段 7 的真实性能验证尚未形成结果

仓库已有 2026-09-02 的 runtime diagnosis/result，也已有 `stage4_runtime_breakdown.py` runner，但没有找到本轮重构对应的 2026-09-09 性能结果文件。测试总耗时不能代替算法性能验证，因此阶段 7 不能标记为完成。

需要运行固定矩阵，至少覆盖：

- 小型单 channel optional-idle/work-conserving；
- 中型固定多资源 optional-idle/work-conserving；
- 一个真实 multi-job；
- 一个已知大图或超时样例，用于确认成本上界。

每个 case 至少记录：

- benchmark id、content hash；
- git commit、dirty diff hash、Python 与机器信息；
- mode、policy、seed、预算和重复次数；
- makespan、trace hash、trace_valid；
- decisions、candidate actions、completion/feature transitions；
- context、solver、observation、step、trace validation、job metrics 分项耗时；
- 峰值内存、timeout、fallback、最后完成阶段；
- 是否启用 tracemalloc，以及测量是否受扰动。

结构优化前后的性能比较必须使用同一 manifest、同一预算和同一输入 hash。若缺少优化前原始数据，应先在可恢复的旧版本或等价基线路径上补测，不能拿不同日期、不同输入的历史表直接比较。

### 14.7 core residual Exact 修改仍需确认和报告

本轮实际修改了：

```text
src/core/oracle/__init__.py
src/core/oracle/nonpree_single.py
src/core/oracle/nonpree_multi.py
```

新增单 channel 和固定多资源的 `exact_completion_from_state`。实现方向符合 Exact 归 core 的约定，且当前 4 个对拍测试和完整测试通过。

但按照 AGENTS.md，修改 core 必须事先请示、修改后报告。当前文档记录了测试结果，但本次复核可见的对话中没有找到针对这三个不可抢占 core 文件的明确批准记录。

需要完成：

1. 由用户确认是否批准保留上述 residual Exact 修改；
2. 若批准，补充修改报告，列出新接口、状态约束、两种 idle mode、预算终止和返回状态；
3. 确认单 channel 只接受合法决策状态，多资源状态 key 保留 active reservation 和全部未来相关信息；
4. 保留 initial-state Oracle 与 residual-state Oracle 的小图对拍；
5. 测试 state limit、time limit、非法参数和 unknown 状态，确保预算终止不会标成 optimal；
6. 若未批准，不继续扩展 core 接口，先讨论保留或迁回方案。

在授权确认前，不能仅因测试通过就把本项标记为合规完成。

### 14.8 推荐继续顺序

1. 先确认 core residual Exact 修改是否获准保留；
2. 完成 `JobIndex` 热路径统一，消除 rollout candidates 的重复 job 解析；
3. 贯通 selective rollout 和 barrier 的单次 `DecisionContext`；
4. 为 packing 建立单次决策 context，并复用 tail、资源与 transition；
5. 增加调用次数和动作等价性测试；
6. 运行第 14.6 节真实性能矩阵；
7. 只根据剖析证据决定是否继续增加 barrier/packing 缓存；
8. 运行不可抢占专项、相关 preemptive 导入回归和完整测试；
9. 追加真实实施记录与性能结果路径。

### 14.9 最终停止条件

只有满足以下条件，才能重新把文档顶部状态改为“已完成”：

- rollout、baseline 和 runner 统一使用 `JobIndex`；
- multi-resource greedy 不在一次动作构造中重复扫描全部任务计算相同 job 特征；
- selective rollout 与 barrier 每个真实决策只建立一次公共 context；
- packing 在单次决策内复用 tail、资源摘要和已执行 transition；
- 所有 cache 都有明确作用域、容量或自然生命周期，不跨不等价状态；
- 指标/观察开关不改变动作、makespan 或 trace hash；
- 有本轮固定 manifest 的真实性能结果和分项耗时；
- core 修改得到确认并按约定报告，或者形成用户批准的替代处理；
- 不可抢占专项、`llm_structured` 专项和完整测试全部通过；
- preemptive 除 common 归属迁移所需改动外没有被重构或优化。

在这些条件满足前，当前结果应表述为：目录和命名重构完成，Exact 调用边界已实现且测试通过，但性能优化与合规收尾仍在进行。

### 14.10 本轮十四项收尾记录（2026-09-09）

用户已明确允许继续实施阶段 6，本轮新增事项已完成：

- `JobIndex` 已贯通 baseline、rollout candidates 和 job-aware 排序；job labels 优先级、命名空间 fallback、arrival/order 和 metadata weight 均有唯一来源。
- selective rollout、barrier 和 packing 均在真实决策点建立并复用单次上下文；上下文只绑定当前 state，不跨 state 保留。
- packing 增加 `PackingDecisionContext`，共享 tail、startable、资源摘要和当前决策内 transition cache；cache 命中、未命中和 fallback 计入决策结果。
- barrier 复用同一 context、transition 和 completion cache；descendant 遍历仍受 budget 限制。
- observation、metrics、instrumented 路径保持动作序列、makespan 和 trace hash 不变；既有共享 runtime 回归覆盖该约束。
- 性能矩阵已生成于 `docs/nonpreemptive_docs/result_docs/rebuild_performance_20260909/`，包含 918-task 单 channel、16-task 真实 multi-job、bare/validated/instrumented 和 tracemalloc 路径；所有 validated trace 合法，记录 content hash、dirty diff hash、分项耗时、峰值内存和预算信息。
- 性能结果是本轮固定 manifest 的基线记录，不将不同日期或不同输入的历史耗时宣称为优化前后差异；后续若需要严格 speedup，应在同一 commit 对该 manifest 做成对重复测量。
- `core.oracle` residual Exact 修改已按用户授权保留，并补充了接口、状态约束、两种 idle mode、预算终止和 unknown 返回状态的测试与记录。
- 最终验证：`python -m compileall -q src benchmark_generate experiments tests` 通过；完整测试 `278 passed in 260.52s`。
