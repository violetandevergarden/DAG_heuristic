# 不可抢占 Stage 4 性能、转换保真与高冲突 Benchmark 推进计划

日期：2026-09-02

## 1. 文档目的

本计划集中解决当前不可抢占 Stage 4 的三个基础问题：

1. 中图运行成本究竟来自公共模拟器、实验包装、时间预算还是算法本身，并把可优化的成本降到能够稳定开展中图实验的水平；
2. 核对 `third_party/simai-flow-scheduler` 的 AICB workload 经 builder、serializer 和项目转换器导出后，哪些信息保持一致，哪些属于明确的性能模型投影，哪些仍缺少 SimAI 动态执行器对拍；
3. 在不修改真实训练因果依赖、不伪造真实来源的前提下，构建具有足够多“有效冲突”的自然真实、真实组合和受控压力 benchmark，使后续 packing、selective rollout、barrier 和 multi-job 研究有可辨别的改善空间。

本计划是 Stage 4a 基础设施的补强，也是 4b--4f 后续研究的重新准入门槛。它不直接预设某个复杂算法必须有效，也不恢复已清理的大图。正式实验以小图和中图为主；超出当前回放能力的输入只保留生成和审计记录，不进入质量比较。

## 2. 当前证据与问题判断

### 2.1 中图不是统一意义上的“完全跑不动”

Stage 4a 归档的 90 秒统一基线中，当前 8 个中图的 FIFO、固定顺序和 residual Longest Tail 均完成：

- 640-task 图约 3.2--3.6 秒；
- 838-task 图约 5.7--5.9 秒；
- 2038-task 单 channel 图约 32--46 秒；
- 2038-task routed 图约 42--46 秒。

Stage 4c--4e 的 30 秒 pilot 出现大量 timeout，但这些路径不完全等同于 Stage 4a 的纯基线：

- Stage 4d 还会执行候选生成、决策记录、特征合同和最终重放；
- Stage 4e 即使配置名为 B0 LT，也会构造 barrier 图并计算候选特征；
- Stage 4c routed 路径可能枚举合法启动子集并执行额外 census；
- 各阶段使用独立子进程和不同运行负载，归档 wall-clock 不是硬件无关的规模下界。

当前代码抽查还显示，640-task 纯 LT、Stage 4d depth-0 LT 和 Stage 4e B0 在当前环境均可低于 30 秒完成。因此，后续报告必须把“纯模拟器成本”“实验观测成本”和“算法额外成本”分开，不能再用一个 timeout 统一解释。

### 2.2 转换层已完成静态代表性对拍，但不是无损执行器复刻

现有 GPT-13B 代表样例对拍结果为：

- SimAI builder：918 个任务、1282 条原始依赖边；
- serializer：追加 364 条 compute-order 边；
- 不可抢占导出：918 个任务、1646 条有效边；
- 没有缺边或无法解释的附加边；
- 可抢占和不可抢占导出的任务与固定资源一致，差异只在各自语义合同。

但当前尚未完成以下验证：

- 多模型、多 pipeline 配置的批量静态对拍；
- SimAI 动态 executor 的 ready、start、finish 事件对拍；
- topology 各链路带宽、hop latency、collective 协议与当前 nominal duration 的一致性；
- 原生 N-iteration 静态 DAG 或动态执行对拍；
- native multi-job 执行时间线对拍。

因此当前导出应定义为“静态任务图基本保真、执行性能模型明确投影”，不能描述为 SimAI 原生执行的无损快照。

### 2.3 当前正式输入的结构变量过弱

虽然 source catalog 有 936 个可用 AICB 条目，并覆盖 GA 1/2/4/8、PP 1/2/4、多个 TP 档位和 Mixtral EP 1/2/4/8，但当前 8 个正式 base case 全部为：

- `gbs=1, mbs=1`，即 GA=1；
- DP=1；
- EP=1；
- 只有少量 PP=2；
- routed 样例仍来自 GA=1、EP=1 的同一小配置。

这是因为当前选样规则优先选择每个模型最小 world size、最小 gbs 和最小 mbs。当前小图切片又只保留 0--2 层后继，可能删除决定动作长期质量的 barrier、optimizer 和公共汇合点。现有错峰 multi-job 的 arrival=10 微秒，相对数万至数百万微秒的日程也通常接近同时到达。

这些设计适合先完成转换与语义验证，但不足以支撑困难调度研究。

## 3. 总体原则

### 3.1 语义边界

- 只修改不可抢占线或两条线共同使用且确有转换必要的公共输入层；不顺带改写可抢占调度算法。
- communication 启动后必须连续运行到完成；任何性能优化不得改变这一点。
- optional-idle 与 work-conserving 独立运行、独立 Exact、独立统计。
- 多资源 active communication 始终保留资源；候选只能使用剩余空闲资源。
- 算法不实现自己的时间推进；所有真实转移仍经过公共不可抢占模拟器。
- 受控 DP、带宽、placement 和 multi-job 组合必须记录变换，不能冒充未修改真实样例。

### 3.2 证据分层

本计划统一使用四层冲突定义：

1. **动作冲突**：同一决策点有两个以上合法动作；
2. **策略冲突**：FIFO、固定顺序、LT、SPT、LPT、热点等简单规则选择不同动作；
3. **状态冲突**：不同动作产生不同 residual state；
4. **质量冲突**：不同动作的 Exact cost-to-go 或统一 completion cost 确实不同。

只有第四层能说明存在可优化空间。前三层用于筛选和解释，不能直接作为算法收益证据。

### 3.3 数据分组

后续 benchmark 分成三组，不混表：

- `natural_real`：不修改 AICB 任务、依赖、并行配置和来源参数；
- `real_composed_stress`：组合真实 job、选择合法 arrival、topology 和 placement，但保持每个 job 内部 DAG 不变；
- `controlled_projection`：DP 扩展、名义带宽曲线或其他明确压力投影。

另保留无选择或选择不影响 makespan 的负对照，避免只保留容易产生收益的样例。

## 4. 工作包 P0：冻结诊断入口与输入

### 4.1 目标

先建立不会因实验包装变化而失去可比性的性能和语义基线。

### 4.2 输入清单

冻结当前 8 个中图作为性能诊断集：

- 640、838、918、1078、1200 task 单 channel；
- 2038-task 单 channel；
- 两个 2038-task routed 图。

冻结以下小图作为语义回归集：

- 当前 30 个 real-derived/real-composed Exact 小图；
- Stage 1--3 中 WAIT、非极大启动、active reservation 和 LT 失败反例；
- Stage 4c--4e 已定位的失败样例。

每个清单保存 benchmark content hash、代码 commit、Python 版本、机器 CPU/内存、进程数和当时系统负载摘要。

### 4.3 新增统一运行口径

同一输入提供三条独立路径：

1. `bare_replay`：只执行策略与公共状态转移，不收集研究特征；
2. `validated_replay`：执行策略并生成、验证 trace；
3. `instrumented_replay`：增加候选、特征、决策记录和研究统计。

三者必须得到相同 makespan 和动作 hash。性能报告分别给出三者的时间和内存，禁止以后用 instrumented timeout 代替 bare simulator 结论。

### 4.4 预算

对每个输入依次运行 10、30、90 秒硬预算；不在同一表中用不同预算替换超时。每个配置至少重复 3 次，报告中位数、最大值和波动范围。

### 4.5 产物

- `experiments/llm_structure/nonpreemptive/stage4_runtime_breakdown.py`；
- `experiments/llm_structure/nonpreemptive/manifests/stage4_foundation/runtime_cases.jsonl`；
- `docs/nonpreemptive_docs/result_docs/stage4_runtime_diagnosis_<date>/`；
- 性能诊断结果文档。

### 4.6 退出条件

- 三条路径的 makespan 和动作 hash 全部一致；
- 每个 timeout 明确属于模型构造、策略循环、特征、重放还是验证；
- 能分别回答 640/838/2038-task 图在纯 LT 和各算法包装下的成本。

## 5. 工作包 P1：公共模拟器与基础 LT 性能优化

### 5.1 先测量，不先重写

性能拆分至少包括：

- benchmark 加载与转换；
- 模型构造与 DAG 校验；
- ready/active 查询；
- residual tail；
- legal action 构造；
- `step` 状态转移；
- compute completion 与新 compute 启动；
- 动作记录；
- trace 重放；
- trace 验证；
- 多资源兼容集合枚举。

使用函数调用次数、累计时间、决策数、每决策扫描任务数、状态复制字节数和峰值内存定位瓶颈。不能仅凭 wall-clock 猜测。

### 5.2 第一批低风险优化

优先处理不改变状态合同的重复工作：

1. 在模型构造时缓存 children、拓扑序、compute/communication 索引；
2. 同一决策内共享 ready、active、legal action 和 tail 结果；
3. `_should_wait` 不再重复扫描全部依赖与 active compute；
4. 多资源贪心路径使用 `startable_flows`、`is_maximal_start` 和 `validate_action`，不调用完整 `start_subsets`；
5. 研究 runner 不在同一配置内重复构造模型；
6. 将 trace 生成和 trace 独立验证分开计时，但正式结果仍必须通过验证；
7. Stage 4d depth=0 不生成 rollout 候选或计算无用特征；
8. Stage 4e method=LT 不为未使用的 barrier challenger 计算完整特征。

### 5.3 第二批增量优化

只有低风险优化仍不能达到门槛时，才进行：

- 增量维护未完成前驱数和 ready 集；
- 增量维护 active compute 最小完成事件；
- 为 residual tail 建立受版本控制的缓存或脏节点传播；
- 使用共享不可变静态图与紧凑运行状态，减少每次复制；
- barrier descendants 使用位图或编号集合；
- 多资源占用使用资源位集。

这些修改会影响公共状态实现，必须与未优化版本在全部小图和随机残余状态上逐步对拍。

### 5.4 禁止的“优化”

- 不删除合法 WAIT；
- 不跳过通信完整执行区间；
- 不把多资源动作改成逐通信依次启动；
- 不省略 compute completion 事件；
- 不用静态原始 tail 替代 residual tail；
- 不为节省时间关闭正式 trace 合法性检查；
- 不改变 Exact 状态空间或 reference result 来配合优化。

### 5.5 测试

至少新增：

- 优化/参考模型逐动作 successor state 对拍；
- optional-idle 与 work-conserving 动作集合对拍；
- 同刻事件、零时长 compute、长通信覆盖多个 compute completion；
- active reservation 下多资源校验；
- residual tail 缓存失效测试；
- 完整 trace hash、makespan、WAIT、forced-idle 和资源利用率对拍；
- 小图 Exact 最优值对拍。

### 5.6 性能目标

在固定机器、单进程、关闭无关后台任务的条件下：

- 640/838-task `validated_replay` LT 中位数不超过 10 秒；
- 2038-task 单 channel 和 routed `validated_replay` LT 中位数不超过 30 秒；
- `instrumented_replay` 必须报告相对 `validated_replay` 的倍数；
- depth=0 Stage 4d 与 bare LT 的额外时间不超过 50%；
- Stage 4e LT 观测路径若仍超过 bare LT 3 倍，必须继续拆分基础动作与结构诊断入口。

如果 2038-task routed 在完成低风险优化后仍无法稳定低于 30 秒，可保留 90 秒预算，但必须说明其成本来自哪一模块；不能继续把复杂算法放入同一 30 秒质量表。

## 6. 工作包 P2：SimAI 转换保真审计

### 6.1 静态 IR 批量对拍

从 source catalog 分层选择至少 12 个输入，覆盖：

- 不同模型族；
- GA 1/4/8；
- PP 1/2/4；
- 多个 TP；
- Mixtral EP 1/2/4/8；
- 单 channel 与两个公开 topology。

逐例比较：

- task id、kind、src/dst、size 和 compute duration；
- SimAI raw dependencies；
- serializer compute-order；
- 合并后的 effective dependencies；
- 导出 dependencies；
- communication route 和资源；
- metadata 中 iteration、micro-batch、stage、phase 和并行维度；
- preemptive/nonpreemptive paired task/resource equality。

任何 mismatch 必须保存完整差异，不只保存前 20 条摘要。

### 6.2 Serializer 边审计

对每类 pipeline serializer 分别回答：

- 增加了哪些 rank 内 compute 顺序；
- 是否存在与 raw DAG 重复的边；
- 是否意外增加跨 rank 或跨 job 边；
- 是否把本可重叠的 B/W、不同 stream 或 pipeline phase 强制串行；
- task 改名后序列化结果是否不变。

如果无法与 SimAI dynamic executor 对拍，结论只能写为“serializer 合同一致”，不能写成“原生执行一致”。

### 6.3 通信 duration 审计

分别记录并比较：

- 当前 nominal bandwidth 公式；
- topology 路径最窄链路带宽；
- hop 数和是否缺少固定 latency；
- NIC 是否成为共享资源；
- collective 在 SimAI builder 中的 P2P 展开方式和固定 `ring` 假设；
- 同一 flow 在 single-channel 与 routed 投影中的 duration 是否合理。

本阶段不直接把复杂真实网络模型加入调度器。先形成误差来源表，再决定是否新增一个版本化 duration model。旧模型和新模型不能混用 content hash 或 reference result。

### 6.4 动态事件小规模对拍

选择 2--4 个很小的输入，尝试驱动 SimAI executor 输出 task start/finish 事件。对拍分为两层：

1. 不依赖资源策略的必然关系：依赖前驱先完成、task 只执行一次、compute-order、任务计数；
2. 依赖执行模型的时间关系：ready、start、finish 和 makespan。

如果 SimAI executor 使用带宽共享、动态路由或与本项目不同的抢占模型，第二层允许不相等，但必须把差异归因到具体模型，而不是标记为转换 bug。

### 6.5 Multi-iteration 与 multi-job

- 原生 N-iteration 对拍未完成前继续标记 `not_supported`；
- 不用简单复制冒充 native multi-iteration；
- real-composed multi-job 继续保留无跨 job 依赖、独立命名空间和 arrival release；
- 尝试与 SimAI example/native multi-job 的任务数、job 边界和到达语义对拍，但不强求不同资源模型下 makespan 相同。

### 6.6 结果分类

每项结论标为：

- `matched`：逐项一致；
- `explained_transform`：存在差异，但由 serializer、投影或语义合同解释；
- `model_mismatch`：静态 DAG 一致，动态资源或时间模型不同；
- `conversion_bug`：无合同依据的缺失或新增；
- `not_supported`：当前工具链不能验证；
- `unknown_timeout`：预算内未完成。

### 6.7 退出条件

- 静态批量对拍覆盖预定结构分层；
- 每个导出 transform 都能追溯到代码版本和参数；
- duration、route、serializer 和 dynamic event 的证据边界分别报告；
- 任何 conversion bug 修复后同步更新 schema/loader/生成器测试和受影响 benchmark hash；
- 最终能明确回答哪些结果只适用于项目固定资源模型，哪些可映射回 SimAI 输入事实。

## 7. 工作包 P3：高冲突 Benchmark 构建

### 7.1 改写 source 选择逻辑

不再只选择每个模型的最小配置。先建立有上限的候选分层：

- GA：1 作为负对照，4 和 8 作为主要重叠层；
- PP：1、2、4；
- TP：选择低、中两个代表档；
- EP：Mixtral 至少覆盖 1、2、4，资源允许时加入 8；
- 模型：至少覆盖 dense 与 MoE；
- world size：优先选择在当前中图预算可处理的较小实例。

不做完整笛卡尔积。第一轮每个结构层最多选 2 个 source，总候选控制在 24--36 个；通过便宜审计后再生成正式 benchmark。

### 7.2 多策略冲突审计

当前只沿有限 LT 前缀审计。新审计至少沿以下轨迹分别运行：

- FIFO；
- 固定顺序；
- residual LT；
- SPT；
- LPT；
- 多资源 hotspot/资源互补；
- 固定 seed 随机负对照。

审计范围分为：

- 小图完整轨迹；
- 中图前 64/128 个决策与固定 wall-clock 双门槛；
- 若纯 LT 已达到性能目标，对中图增加完整轻量轨迹统计。

记录轨迹状态的稳定摘要，避免保存完整大状态导致 I/O 成为主要成本。

### 7.3 冲突和困难度指标

每个 case × mode 至少报告：

- 总通信启动决策数；
- ready communication 数分布；
- 合法动作数与截断状态；
- WAIT 合法次数；
- 非极大启动合法次数；
- 多资源 active communication 数；
- active reservation 下多个 startable/多个极大集合的次数；
- 简单策略分歧次数和比例；
- 不同动作的 immediate successor 是否不同；
- 小图 Exact Q-value spread；
- 中图冻结 LT completion value spread；
- LT regret、最佳/最差动作 gap；
- 冲突发生的 phase、micro-batch、barrier、optimizer 和 job。

`contention_score` 只用于排序，不能替代逐项统计。初始建议由选择密度、策略分歧、active-aware 集合分歧和 value spread 四部分构成，权重只在 pilot 后冻结。

### 7.4 自然真实输入

从 AICB 原始 source 中优先寻找：

- GA 4/8 的多个 micro-batch wave；
- PP 2/4 的 warmup、steady、cooldown；
- TP 与 PP 同时大于 1；
- Mixtral EP 与 TP/PP 同时存在；
- optimizer/gradient communication 与后续计算接近的输入。

自然真实输入不得修改 header、任务、依赖、duration 或 placement。无冲突结果同样保留，不能只发布高分图。

### 7.5 Real-composed multi-job

以已经通过单 job 转换与 trace 验证的真实 DAG 为原子，构造：

- 2-job 与 4-job；
- 同构与异构；
- 同时到达；
- 按单 job makespan 的 10%、25%、50% 错峰；
- 事件对齐 arrival：长通信开始前、刚开始后、关键 barrier 前；
- 共享同一热点与资源互补两类 topology/placement。

不再使用固定 10 微秒作为主要错峰。arrival 必须来自预先冻结的单 job baseline 事件或比例，不得根据候选算法收益返调。

每个组合同时保留两个单 job 对照，并记录逐 job completion/JCT。基础 makespan 与 JCT/fairness 目标分开评价。

### 7.6 固定多资源 topology 与 placement

固定使用已经审计的 topology 文件和 BFS route 版本，设计少量可解释 placement：

- 低共享负对照；
- 多个 TP/PP/EP flow 穿过同一上行链路；
- 两组 route 部分冲突、部分互补；
- 长多资源 flow 与多个关键短 flow 竞争；
- active reservation 存在时仍有多个合法新启动集合。

每种 placement 保存 rank 到设备映射、route hash、热点资源和预期机制。人为热点 placement 标为 `real_composed_stress`，不能归入自然 topology 结论。

### 7.7 DP 扩展

当前 AICB source catalog 的原生 DP 都为 1。若构造 DP=2/4，必须作为 `controlled_projection`：

- 重新构建 rank group 和 DP collective；
- 不只修改 metadata；
- 记录 source world size/DP 与 effective world size/DP；
- 写入 `dp_rewrite=true` 和完整 transform log；
- 与 DP=1 成对；
- 分别检查任务数、依赖、collective 数和资源热点是否按预期变化。

如果当前 SimAI builder 无法可靠执行 DP rewrite，则停止该分支，不手写未经对拍的 DP 边。

### 7.8 带宽压力曲线

同一真实 DAG 可生成少量版本化带宽层：

- compute-dominated；
- compute/communication 平衡；
- communication-dominated。

带宽值优先来自 topology 或公开配置；人为倍率必须记录。该曲线用于寻找冲突开始影响 makespan 的临界点，不作为原始硬件结论。

每条曲线检查：

- 通信利用率；
- ready 队列增长；
- 策略分歧；
- value spread；
- 是否因通信过长反而只剩唯一串行顺序。

### 7.9 困难 real-derived slice

现有“锚点 + 0--2 层后继 + 完整前驱闭包”继续作为语义小图，但不再作为主要困难切片方法。新增 residual decision window：

1. 从完整真实轨迹中找到简单策略分歧或 value spread 非零状态；
2. 保存该时刻 active compute、active communication、ready 候选、资源占用和下一事件；
3. 沿候选后继保留到下一个公共 barrier、optimizer 或可解释 sink；
4. 为窗口外已完成/将到达前驱建立明确 boundary release；
5. 保留候选使用的全部固定资源；
6. 切片前后对拍候选集合、tail 排名、下一事件和首动作 value 排序；
7. 若无法保持这些性质，拒绝切片，不修改依赖来强行通过。

目标规模为 100--1000 task。小于 300 的优先运行完整 Exact；更大的先运行首动作有界 Exact 或统一 completion 标签。

### 7.10 Benchmark 准入与切分

正式 corpus 分为：

- 转换/无冲突负对照；
- 自然选择但 value spread 为零；
- 自然困难；
- real-composed multi-job；
- fixed-route hotspot；
- controlled DP/bandwidth stress。

困难集初始准入建议：

- 基础 LT 在统一预算内完成；
- 至少 20 个有选择状态，或选择密度达到 pilot 冻结阈值；
- 至少 5 个简单策略分歧状态；
- 至少 1 个经过 Exact 或冻结 completion 证实的非零 value spread；
- 多资源困难图至少出现 1 个 active reservation 下多个合法集合状态；
- WAIT 研究集至少出现 1 个 WAIT 与立即启动 value 不同的状态。

这些数值只作为第一轮 pilot 建议。正式阈值必须在开发集冻结，并把未通过样例保留在自然 corpus，不可删除后重新计算成功率。

development/validation/holdout 按 source workload、topology 和组合父图分组。同一 source 的 GA 邻近配置、同一完整图的相邻切片、同一 multi-job 父图不得跨 split。

## 8. 工作包 P4：算法重新准入

### 8.1 前置条件

只有同时满足以下条件，才重新运行复杂算法：

- P1 中图基础 LT 性能门槛满足，或明确采用可完成的独立预算；
- P2 没有未处理的任务/依赖 conversion bug；
- P3 形成至少一组 value spread 非零的自然或明确受控困难样例；
- 输入、阈值和 holdout 已冻结。

### 8.2 统一基线

所有后续实验至少包含：

- FIFO；
- 固定顺序；
- residual LT；
- SPT/LPT；
- 与候选调用量匹配的随机和周期对照；
- optional-idle/work-conserving；
- 小图 Exact 或明确 unknown。

### 8.3 各方向优先级

1. **Stage 4f multi-job 优先**：已经存在真实派生 WAIT 正例，先研究 arrival、JCT 和 starvation；
2. **Stage 4b 结构解释**：分析为什么某些真实状态虽有选择但 value spread 为零；
3. **Stage 4c packing 条件恢复**：只有 active reservation 下集合分歧达到统计覆盖才运行；
4. **Stage 4d selective 条件恢复**：只在真实 LT regret 存在时重新训练/冻结触发器；
5. **Stage 4e barrier 条件恢复**：barrier 只作 LT 修正或触发信号，不恢复 barrier-only 主策略。

### 8.4 不继续堆叠的方向

在准入条件满足前，不进行：

- 更深或更宽 full rollout；
- packing 一换三及更大邻域；
- barrier 权重和 margin 大网格；
- 只在旧 75 图上训练复杂分类器；
- 恢复大图完整质量实验；
- 未经单组件验证的综合算法。

## 9. 实施顺序和阶段门槛

| 阶段 | 工作 | 通过后进入 | 失败处理 |
|---|---|---|---|
| F0 | 冻结输入、三条运行路径和环境记录 | F1 | 修正 runner，不动算法结论 |
| F1 | 性能拆分和低风险优化 | F2/F3 | 保留 90 秒基线，缩小中图质量范围 |
| F2 | 静态批量转换对拍 | F3 | conversion bug 优先修复并重建 hash |
| F3 | 多策略冲突 census | F4 | 若自然冲突仍弱，进入真实组合而非改依赖 |
| F4 | multi-job/topology/带宽/DP 受控构造 | F5 | 明确哪个变量没有增加质量冲突 |
| F5 | 困难 residual slice 与 Exact 标签 | F6 | 无法保持 value 排序的切片拒绝发布 |
| F6 | 4b/4c/4d/4e/4f 条件重验 | 阶段结果 | 无稳定收益则形成否定结论 |

F1 与 F2 可并行准备，但 F3 的正式数据发布必须等待 F2 排除 conversion bug。F4 不能因为自然 corpus 冲突不足而被标为自然真实；所有压力变换单独归档。

## 10. 结果文件与文档

建议新增结果目录：

- `stage4_runtime_diagnosis_<date>/`；
- `stage4_conversion_fidelity_<date>/`；
- `stage4_contention_census_<date>/`；
- `stage4_real_composed_stress_<date>/`；
- `stage4_hard_slices_<date>/`。

最终至少形成三份结果文档：

1. `stage4_runtime_optimization_result_<date>.md`；
2. `stage4_simai_conversion_fidelity_result_<date>.md`；
3. `stage4_contention_benchmark_result_<date>.md`。

若形成新的正式 corpus，必须同步更新：

- benchmark manifest；
- source/topology catalog；
- contention report；
- benchmark index；
- 受影响的 baseline 和 Exact result；
- Stage 4a 当前状态说明。

历史结果不覆盖、不删除；新结果通过输入 hash 和版本与旧结果区分。

## 11. 风险与停止条件

### 11.1 性能方向

- 若纯 LT 已快而算法包装仍慢，停止修改公共模拟器，转向算法特征和候选成本；
- 若多资源全集合枚举是主因，停止提高预算，改为非枚举贪心和有界候选；
- 若优化改变任一小图 Exact、动作合法性或 trace，立即回退该优化并定位语义差异。

### 11.2 转换方向

- 若发现无法解释的缺边/附加边，暂停新 benchmark 发布；
- 若差异只来自 SimAI 与项目资源模型不同，记录 model mismatch，不为追求时间一致而改变项目目标语义；
- native multi-iteration 无法驱动时保持 `not_supported`，不伪造完成状态。

### 11.3 Benchmark 方向

- 若提高 GA/PP/EP 只增加任务数而不增加 value spread，停止该变量扩展；
- 若降低带宽只造成唯一长队列而不增加策略差异，停止继续降低带宽；
- 若人为 placement 需要修改训练依赖才产生收益，拒绝该样例；
- 若困难切片不能保持原状态动作和首动作排序，拒绝发布；
- 若自然真实样例仍没有 LT regret，如实形成“当前结构下简单策略足够”的结论，不继续调参制造改善。

## 12. 总退出条件

本计划完成时必须能够用可重复证据回答：

1. 640、838 和 2038-task 输入的成本分别花在模拟、策略、特征、重放和验证的哪一部分；
2. 30 秒 timeout 是基础模拟器、实验包装、算法复杂度还是运行环境造成，并给出分项比例；
3. SimAI 静态 task/dependency/serializer/route 在分层样例上的对拍结果；
4. 当前通信 duration、固定 route、NIC 和单 channel 投影相对 native 执行的已知简化；
5. 原生 multi-iteration 和 dynamic event 对拍是否完成，未完成项明确标为 unknown/not-supported；
6. 新 corpus 中动作冲突、策略冲突、状态冲突和质量冲突分别有多少；
7. 自然真实、真实组合和受控投影不混表；
8. 至少形成一组基础 LT 可运行、value spread 非零、来源可追溯的困难小/中图，或者形成“当前真实输入无法提供此类状态”的否定结论；
9. 后续 4c--4f 每个方向是否具备重新进入算法实验的条件；
10. 任何复杂算法收益同时报告 makespan、运行时间、调用数、timeout、fallback、最坏退化和适用范围。

在这些条件满足前，不进入 Stage 4g 综合算法，也不宣称不可抢占 Stage 4 已经得到真实中图上的最终调度方法。
