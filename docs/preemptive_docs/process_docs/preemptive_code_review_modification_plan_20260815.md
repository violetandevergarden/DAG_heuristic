# 可抢占调度代码详细修改计划（2026-08-15）

## 1. 计划前提

本计划对应 `preemptive_code_review_20260815.md` 的发现，只描述后续修改，不表示本轮已经实施。

根据 2026-08-15 确认的项目方向，本计划前提是：

- communication 可暂停恢复的 v2 正式成为仓库主线；
- 不可抢占 v1 降为历史模型，但仍是有用、受维护的 baseline，不使用 `old/legacy` 目录贬低或隐藏它；
- 不再把新增可抢占功能集中放在 `src/preemptive/`，而是同时按 DAG 家族和执行语义组织；
- 不重写现有算法，先修合同、验证器、测试和结果产物；
- 所有主线结论仍需写明 `communication_resume`、`task_event`、零开销、零 quantum，避免与历史 v1 或未来有限粒度模型混淆；
- 不修改 `muti_channel` 公开拼写，不修改 SimAI 子模块，除非另开有权限和独立提交的任务。

这次调整是目录和合同迁移，不是整体重写。第一步只移动/封装已经通过回归的状态机与算法，保持 makespan、action 序列和 Exact 值不变；正确性修复分后续独立提交进行。

## 2. 修改优先级

| 阶段 | 目标 | 对应审查项 | 是否阻塞重新发布 v2 结果 |
|---|---|---|---|
| M0 | 冻结可抢占主线合同并迁移目录 | R1、R2、R10 | 是 |
| M1 | 修正输入和动作验证 | R2、R5 | 是 |
| M2 | 建立独立单通道 Trace validator | R3 | 是 |
| M3 | 为多资源补 Trace 与回放验证 | R4 | 是 |
| M4 | 用独立小图 Oracle 交叉校验 Exact | R7 | 是 |
| M5 | 补测试依赖和性质测试 | R9 | 是 |
| M6 | 重建 reference 与实验产物链 | R8、R10 | 是 |
| M7 | 小步整理架构和重复实现 | R6、R10 | 否 |

M0--M4 完成前，不更新旧报告中的性能结论强度；M0--M6 完成后再生成新的正式 v2 审计报告。

## 3. M0：冻结可抢占主线并迁移目录

### 3.1 需要形成的决定

建立一张 v1/v2 合同表，至少明确：

| 项目 | 历史 v1 | 当前主线 v2 |
|---|---|---|
| communication | 不可抢占，单连续区间 | 仅任务事件处暂停恢复 |
| scheduler WAIT | 允许 optional idle | 有 eligible 时禁止；无 eligible 时 forced idle |
| 单通道动作 | START/WAIT | 恰好选择一个 eligible comm |
| 多资源动作 | 可选兼容子集/WAIT | inclusion-maximal compatible set |
| preemption cost/quantum | 不适用 | 均为 0 |
| 目标 | makespan | makespan；multi-job weighted JCT 另列 |

主线 v2 的 `optional_idle` 目前与上述合同冲突。推荐不要复用历史 v1 的含义：

1. v2 schema 将其改为 `optional_idle=false`，或在新 schema minor version 中改为更明确的 `work_conserving=true`；
2. loader 保留对旧 v2 文件的迁移读取，但规范化后的内部语义只能有一个解释；
3. reference hash 会因此变化，必须在 M6 统一重建，不能手工局部改 sidecar。

若研究者仍希望比较“理论上被支配的 voluntary WAIT”，应把它做成 Oracle 的实验 mode，不应让模拟器默认把 WAIT 当成合法生产动作。

### 3.2 目标代码结构

目录必须表达两个正交维度：

1. 问题家族：`parallel_chain`、`complex_chain`、`muti_channel`；
2. 执行语义：`preemptive`、`nonpreemptive`。

推荐目标结构如下：

```text
src/
├── core/
│   ├── execution/
│   │   ├── common.py
│   │   ├── preemptive.py
│   │   └── nonpreemptive.py
│   ├── trace/
│   │   ├── common.py
│   │   ├── preemptive.py
│   │   └── nonpreemptive.py
│   └── ...                       # DAG、conversion、resource、公共接口
├── single_channel/
│   ├── parallel_chain/
│   │   ├── preemptive/
│   │   │   ├── interface.py
│   │   │   └── solver.py
│   │   └── nonpreemptive/
│   │       ├── interface.py
│   │       └── solver.py
│   └── complex_chain/
│       ├── preemptive/
│       │   ├── interface.py
│       │   └── solver.py
│       └── nonpreemptive/
│           ├── interface.py
│           └── solver.py
├── muti_channel/
│   ├── preemptive/
│   │   ├── interface.py
│   │   └── solver.py
│   └── nonpreemptive/
│       ├── interface.py
│       └── solver.py
└── llm_structured/
    ├── repetition.py
    └── multi_job.py
```

`muti_channel` 的公开拼写继续保持不变。`study.py`、`multi_job_study.py` 等实验 runner 不应继续与核心 solver 混放；可迁到 `benchmark_generate/studies/preemptive/` 或独立 `experiments/`，具体位置在移动前统一决定。`llm_structured` 当前只推进可抢占模型时不必再加一层重复的 `preemptive/`；文件本身和 registry metadata 写明语义即可，未来真有非抢占结构算法时再对称拆分。

推荐路径是 `single_channel.parallel_chain.preemptive`、`single_channel.parallel_chain.nonpreemptive`、`single_channel.complex_chain.preemptive`、`single_channel.complex_chain.nonpreemptive`。这比 `single_channel_preemptive` 等扁平包更能保留研究问题的层次，也避免只按“是否抢占”分包后再次丢失 parallel/complex 的区别。

两种语义在命名上平等，在项目状态上不同：

- `preemptive`：`active`，当前新增算法、Oracle、benchmark 和理论的落点；
- `nonpreemptive`：`maintenance`，继续修复正确性、运行历史 benchmark、保留反例和比较，但默认不新增研究算法；
- 不使用 `old`、`legacy`、`deprecated` 作为包名；
- README、registry metadata 或 capability 字段表达 development status，不把状态差异编码进 import path。

parallel-chain 与 complex-chain 的可抢占模块必须有独立入口。初始迁移允许它们共享 `core.execution.preemptive`、Trace validator 和通用 Exact，但不能只给同一个 generic solver 建两个无内容的别名：

- parallel-chain interface 要验证无 fork/join，并为链状态压缩、链尾、周期/对称算法保留专用数据结构；
- complex-chain interface 接受一般 DAG，保留 fork/join、last blocker、residual DAG 等算法；
- registry 分别列出两类算法能力；
- 实验分别报告，不能把 parallel-chain 的结构特化收益并入 general DAG 总表。

两种语义的关系应采用“共享合同、分离状态转移”，而不是互相复制或在一个大类中遍布 `if preemptive`：

- 共享：immutable DAG、benchmark loader、task/resource 基础类型、scheduler protocol、结果字段、hash、通用 Trace event 类型；
- 分离：合法动作、事件推进、running/suspended 状态、不抢占资源保留、Exact memo key、语义相关下界；
- 可复用但不强求统一：residual-tail、候选排序、rollout/beam 外壳；只有确认输入状态含义一致时才抽公共 helper；
- 禁止让 preemptive solver 调用 nonpreemptive transition，或反过来把一种语义当另一种的特殊 flag；两者都实现同一个上层 protocol。

算法注册项的唯一身份应是 `(semantics, scenario, family, algorithm_name)`。因此两个版本都可以叫 `longest_tail`，不会为了避开命名冲突制造 `old_longest_tail` 或 `preemptive_longest_tail_v2`；CLI 已知输入 benchmark 后按前三个维度选择正确实现。

benchmark 的公开路径已经存在外部兼容性，本轮不随代码目录一起大搬迁。先依靠 JSON `semantics` 和 `benchmark/index.jsonl` 明确区分；若以后也要改成 `{family}/{preemptive,nonpreemptive}/{category}` 的完全对称布局，应提供单独的版本化迁移和 reference path 映射。

迁移顺序必须保持行为不变：

1. 先创建对称目标 package 和 compatibility import；
2. 用 `git mv` 将现有不可抢占 parallel/complex 实现放进各自 `nonpreemptive/`，将现有可抢占 generic solver 拆出明确的 parallel/complex 入口；
3. 更新 registry、benchmark generator 和 tests 的 import；
4. `src/preemptive/` 暂时只保留转发旧 import 的 shim；
5. 一个兼容周期后删除 shim，禁止新代码再依赖旧路径；
6. 不再把不可抢占实现整体移动到 `old/` 或 `legacy/`；它始终与可抢占实现作为 sibling package 共存。

### 3.3 涉及文件

- 根 `AGENTS.md` 或等价协作说明：明确 v2 是当前主线、v1 是历史模型；
- `docs/plan_docs/outline.md`、`docs/plan_docs/simulator.md`：作为主线语义依据并消除 optional idle 冲突；
- `benchmark/README.md`、`benchmark/schema/dag-benchmark-v2.schema.json`；
- `src/benchmark/model.py`、`src/benchmark/loader.py`、`src/benchmark/validator.py`；
- `src/registry.py` 的 capability/semantics 描述。
- `src/preemptive/` 到 `src/core/execution/`、`src/core/trace/`、两个 `src/single_channel/*/preemptive/`、`src/muti_channel/preemptive/` 和 `src/llm_structured/` 的迁移；
- 现有不可抢占代码从 family 目录根部移入对应 `nonpreemptive/`，只改 import 和 registry，不改行为；
- tests 镜像上述二维目录，单独保留 shared core tests。

### 3.4 验收条件

- 任一 benchmark 仅凭 schema、path 和 semantics 即能判断 v1/v2；
- 同一 `optional_idle/work_conserving` 字段在 README、schema、loader、model 和 tests 中含义一致；
- 历史 v1 benchmark 和 reference 完全不变；
- registry 默认面向 v2 主线，历史 v1 算法通过明确的 `nonpreemptive` semantics 路由；
- 主线实现不再从 `src/preemptive/` 加载实际逻辑；
- 纯目录迁移提交前后，全部 v2 benchmark 的 algorithm makespan、Exact 值和 reference hash 不变。
- CLI 对 v2 benchmark 继续使用稳定算法名；历史 v1 benchmark 依靠输入 semantics 路由到 nonpreemptive registry，不让同名算法跨模型混算。

## 4. M1：修正核心输入和动作验证

### 4.1 单通道

目录迁移完成后，在 `src/core/execution/preemptive.py` 中小步修改：

1. `legal_actions()`：有 eligible communication 时只返回 `RUN`；只有 eligible 为空且 active compute 非空时返回 forced `WAIT`；
2. `step()`：明确区分非法 voluntary WAIT、无未来事件 deadlock 和普通非法 task；
3. 增加稳定的错误类型或至少结构化错误消息，包含 time、action、eligible、active compute；
4. 保持现有 `_dispatch()` 的事件推进逻辑，不改 heuristic；
5. 明确连续选择同一通信是否合并 interval。推荐 Trace 层合并连续区间，preemption 只统计真正不连续服务或切换。

### 4.2 多资源

在 `src/muti_channel/preemptive/solver.py` 中增加防线：

1. 构造时拒绝 communication duration 小于等于 0；
2. 验证 resource map 的 key、非空集合和 task kind；
3. 提供 `legal_actions()`，返回所有 inclusion-maximal compatible sets，forced idle 时才返回空集合；
4. `step()` 必须验证 action 是 legal action，而不只是兼容子集；
5. 重复 ID、非稳定排序、零 delta 和无未来事件分别报错；
6. 保留 `maximal_actions()` 作为兼容别名，避免一次性重写 solver。

若 M0 最终决定 v2 允许非 maximal 实验动作，则应显式增加 `action_mode="optional"`，且 Exact/结果必须携带 mode；不能让一个 `step()` 静默接受两套合同。

### 4.3 测试

新增或加强：

- eligible 存在时 WAIT 被拒绝；
- 只有 compute 活动时 forced WAIT 合法；
- 无 eligible、无 active compute、未完成时报告 deadlock；
- 单通道恢复保持 remaining work；
- 多资源非 maximal 子集被拒绝；
- 多资源 maximal 集合接受；
- 共享任一资源即冲突；
- 零时长通信在两个模型中一致拒绝；
- 同时 compute/comm completion 只形成一个稳定决策边界。

### 4.4 验收条件

- `legal_actions()` 与 `step()` 接受集合完全一致；
- 内置 heuristic 和 Exact 的历史 makespan 在合同未改变的图上保持不变；
- 非法动作不会被静默修正；
- 所有错误包含可复现上下文。

## 5. M2：独立单通道 Trace validator

### 5.1 实现原则

不要调用 `PreemptiveDAGModel.step()`，也不要相信 `trace.final_state.completed_at`。validator 只读 immutable DAG 和 Trace，从零重建：

1. 校验所有 task/event/interval ID 和 kind；
2. 按时间批次扫描 intervals；
3. 独立累计每个任务服务量；
4. 检查 compute 恰好一个连续 interval；
5. 检查 communication interval 互不重叠、总长度等于 duration；
6. 由 interval 终点独立推导完成时间，再检查 finish-to-start；
7. 检查单通道任意开区间内至多一个通信；
8. 检查 event 与 interval 边界一一对应；
9. 检查 pause/resume/complete 状态序列；
10. 检查最后完成时间、final state 和 makespan 三者一致；
11. 检查每个任务恰好 start/complete 一次，communication 的 pause/resume 数匹配。

主状态机 validator 可继续保留为快速断言，但正式结果必须再通过独立 replay validator。

### 5.2 负面 Trace 测试

手工构造并要求逐一失败：

- 删除全部 events；
- 删除 transitions；
- 修改 task kind；
- 少服务/多服务 1 tick；
- compute 拆成两段；
- communication 提前于 predecessor 完成启动；
- 两个通信重叠；
- paused 区间仍减少 remaining；
- 重复 complete；
- 连续 resume 被错误统计为抢占；
- makespan 大于/小于最后完成事件；
- final state 与回放结果不一致。

### 5.3 验收条件

- 当前合法单通道 v2 结果全部通过；
- 上述每种故障至少有一个定位明确的失败测试；
- 把合法 Trace 的 events/transitions 清空不再可能通过；
- validator 代码不导入状态转移函数。

## 6. M3：多资源 Trace 和独立回放

### 6.1 最小增量方案

不重写多资源算法。给 `MultiState.step()` 返回 transition 信息，并让 `MultiResult` 增加 Trace：

- decision time 和 selected set；
- compute intervals；
- 每个 communication 的 start/pause/resume/complete；
- communication 每段 service；
- 每个固定 resource 的占用 interval；
- forced-idle interval；
- final task completion times。

solver 仍然保存 action 序列，但最终结果由同一序列重放生成完整 Trace。

### 6.2 独立 validator

在不调用多资源 `step()` 的前提下检查：

- 同一 communication 每段同时持有完整固定资源集合；
- 任意共享资源的通信区间不重叠；
- 暂停立即释放全部资源；
- 恢复仍用原集合；
- selected set 在每个决策点 maximal；
- 服务量、依赖、compute 连续性和 makespan 正确。

### 6.3 验收条件

- 14 个现有多资源 Exact 图和所有 heuristic trace 通过独立 validator；
- 人工资源重叠、部分获取、错误恢复路径、非 maximal set 均被拒绝；
- 历史 makespan 不变；
- `MultiResult` 可以不重新运行 scheduler 而完整回放。

## 7. M4：独立极小图 Oracle 交叉验证

### 7.1 测试 Oracle

新增一个仅供测试的整数 tick exhaustive solver，代码路径不得复用事件 `step()`：

- 状态只含每个任务独立推导的 remaining/status；
- 每 tick 自动推进 active compute；
- 单通道选择一个 eligible communication；
- 多资源选择 maximal compatible set；
- 只支持总 duration/节点数很小的图；
- 返回最优 makespan，不追求性能。

也可使用小型 MILP/CP-SAT，但会引入额外依赖；优先选择无第三方依赖的 test-only exhaustive solver。

### 7.2 交叉验证矩阵

- 手工 fork/join、多个同时完成、零时长 compute；
- 随机 2--7 节点单通道 DAG；
- 随机 2--6 节点、1--3 资源多资源 DAG；
- 每个随机图比较 event Exact 与 tick Exact；
- 对同一图重排 task 输入顺序，最优值必须不变；
- 对称 component 版本与普通 Exact 值一致。

另外枚举极小图实证检查 v2 前提下 voluntary WAIT 和非 maximal set 的支配性。该枚举是证明的回归护栏，不替代理论证明。

### 7.3 验收条件

- 固定 seed 的全部小图两种 Oracle 一致；
- 任何不一致都保存成 adversarial regression，而不是放宽断言；
- reference 只由通过双 Oracle 校验的规模生成，或显式记录仅通过 event Exact。

## 8. M5：测试依赖与性质测试

### 8.1 隔离 SimAI

推荐将依赖 SimAI 的 repetition scanner/ZB exporter 测试移到 `tests/integration/`；`tests/preemptive/test_repetition.py` 只保留不导入 SimAI 的纯调度反例和对称压缩测试。

在 `pyproject.toml` 增加明确的 `integration` extra（包括 `jsonschema` 等 SimAI 实际导入依赖），integration fixture 在 submodule 或 extra 缺失时给出 skip reason，而不是 collection error。

### 8.2 性质测试

至少覆盖：

- time 单调、remaining 非负；
- completed remaining 为 0；
- compute 不被拆分；
- communication service 守恒；
- 资源两两排他；
- task 输入顺序不影响结果；
- 同时事件原子处理；
- `run(actions)` 与逐步 `step()` 最终规范状态一致；
- result preemption 计数与 Trace 不连续区间一致。

### 8.3 验收条件

- `python -m pip install -e ".[dev]"` 后纯单元测试可完整收集；
- 未安装 integration extra 时只有 integration 被明确 skip；
- 安装 extra 且 submodule 可用时完整测试通过；
- 不再需要通过忽略 test 文件获得绿色结果。

## 9. M6：reference 和实验产物重建

### 9.1 Reference

在 M0 schema 决定和 M1--M4 验证完成后：

1. 固定 commit、Python 版本、seed、state/time budget；
2. 重建 v2 adversarial sidecar；
3. 对可解的 13 个缺失 parallel-chain adversarial 补 reference；
4. 超时图继续无 sidecar，并在 manifest 记录 timeout 类型与预算；
5. 更新 `benchmark/index.jsonl` 和 README 计数；
6. 运行 hash 与 Exact 重算测试。

不要为了补齐数量把超时 incumbent 写成 optimum。

### 9.2 实验 JSON

重新生成并保留：

- 阶段 0--4 逐实例结果；
- 阶段 5 合成重复/对称结果；
- ZB 修复结果（只有 integration 环境满足时）；
- 阶段 6 逐 case、多资源和 objective probe；
- 环境 manifest：commit、dirty 状态、命令、seed、Python、依赖、机器和时间。

结果路径可继续放在 gitignored `docs/process_docs`，但报告必须引用实际存在的相对路径；若需要长期可审计，应另行决定是否提交小型 JSON summary。

### 9.3 报告规则

- random、adversarial、real 分表；
- 单通道、多资源、多 Job 分表；
- makespan 与 weighted JCT 分表；
- observed 100% 明确写“有限样本”；
- runtime 报机器和重复次数；
- Exact timeout 不进入 ratio 分母，并单列；
- v1/v2 结果绝不混表。

### 9.4 验收条件

- 报告引用的每个 JSON 均存在且可由记录命令重建；
- 所有 sidecar hash 正确；
- 当前可复现的核心历史数值保持一致，差异有逐实例解释；
- 新报告将多资源 Exact 标记为已通过独立 Trace 回放。

## 10. M7：非阻塞的小步架构整理

在主线目录迁移和正确性防线完成后再做，不一次性重写：

1. 提取 immutable problem model 和只读 scheduler view；
2. 把动作验证、事件推进、compute closure 分成内部函数/类；
3. 单/多资源共享事件、interval、错误和统计数据结构；
4. solver 只依赖公开 view/transition 接口，不直接修改 runtime；
5. 取消 `longest_delay`/`longest_tail` 的重复命名，或明确一个是兼容 alias，实验表只计一次；
6. 让算法单次执行直接累积 Trace，减少“先 step 决策、再 run 重放”的双路径；
7. preemption/dispatch/decision 三种计数给出稳定定义。

验收重点是历史合法结果不变、接口更清楚，不以文件移动量或代码行数为目标。

## 11. 建议提交拆分

为降低审查风险，建议按以下独立提交：

1. `docs: make communication-resume the main scheduling contract`；
2. `refactor: move preemptive core and solvers into scenario packages`；
3. `fix(preemptive): enforce work-conserving legal actions`；
4. `test(preemptive): add independent single-channel trace replay`；
5. `feat(preemptive): add multi-resource trace and replay`；
6. `test(preemptive): cross-check event exact with tiny tick oracle`；
7. `test: isolate optional SimAI integration dependencies`；
8. `data: regenerate audited v2 references and manifests`；
9. `refactor(preemptive): introduce scheduler view and shared trace types`。

每个提交都先运行相关小测试；修改 Oracle、转换、schema 或 reference 的提交必须运行完整测试。不得在同一提交中顺便改 v1 算法或删除本地 `docs/`。

## 12. 最终退出条件

完成本计划需要同时满足：

1. v2 可抢占合同成为唯一默认主线，历史 v1 有明确 `nonpreemptive` 语义和 `maintenance` 状态；
2. 核心拒绝 voluntary WAIT、非 maximal set 和非法零时长通信；
3. 单/多资源都有不复用状态转移的独立 Trace validator；
4. 事件 Exact 与独立极小图 Oracle 在固定随机集上完全一致；
5. 纯单元测试不依赖 SimAI，integration 依赖可选且可诊断；
6. v2 reference、index、README 计数和 hash 一致；
7. 历史核心数值重跑一致，所有差异有逐实例记录；
8. 新结果明确区分模型、数据类别、目标函数和结论强度；
9. 历史不可抢占模型的 exact 值和回归测试没有变化；
10. 没有整体重写现有算法，所有改动均可逐步审查和回滚。
