# Stage 4a：真实 LLM Training DAG Benchmark 构建与审查纲领

## 1. 阶段定位

Stage 4a 是整个 Stage 4 的输入基础。本阶段的任务不是简单地把 SimAI workload 转成 JSON，也不是以 benchmark 文件数量衡量进度，而是建立一套来源可追溯、语义可核对、竞争证据明确、规模可运行的真实 LLM training DAG 语料。

后续 4b--4g 对训练结构、兼容集合、Selective Rollout、barrier、multi-job 和综合算法的研究，都依赖 4a 对以下问题给出可信回答：

1. 输入是否真实来自指定的 AICB workload 和 topology；
2. 转换是否保留了训练任务、依赖和固定资源含义；
3. benchmark 中是否真的存在需要调度算法选择的通信竞争；
4. 样例能否在统一预算下完成所需审计和基线回放；
5. 无竞争、超时或证据不足的样例应如何保留和标记。

本阶段以 `stage4_LLM_search.md`、`outline.md` 和 `simulator.md` 的目标语义为依据。现有生成器、语料、实验脚本和历史结果只是待审查资产，可以帮助复现和定位问题，但不能反向定义正确行为。

## 2. 本阶段不研究的内容

为了防止输入审查和算法研究相互污染，4a 暂不负责：

- 证明某个训练结构能够改进调度；
- 设计 barrier、packing 或 rollout 的最终算法；
- 根据候选算法的收益挑选 benchmark；
- 为大图寻找近似最优调度；
- 修改公共模拟语义以适配 SimAI 输出；
- 复刻 SimAI 的协议级网络、动态路由或带宽共享细节；
- 把 metadata 中的训练标签作为算法可见答案提示；
- 用合成 motif 代替真实 workload 的结构和竞争证据。

4a 可以运行 FIFO、Longest Tail 和固定顺序等简单策略，但其目的主要是验证可运行性、发现策略分歧和建立后续统一基线，不是在本阶段宣称最终算法收益。

## 3. 研究问题

### 3.1 输入真实性

需要确认每个候选样例究竟来自哪个 workload、哪个 topology、哪些生成参数和哪个 SimAI 版本。文件名、目录名或 topology 名称本身不能证明其来源和生产真实性。

需要回答：

- workload 是 AICB 原始输入、人工编辑版本还是生成器内置示例；
- topology 是真实来源、公开示例、实验性拓扑还是人为冲突拓扑；
- TP、PP、EP、DP、world size、micro-batch、global batch、pipeline schedule 和 iteration 分别从何处取得；
- 哪些参数来自文件，哪些由命令补充，哪些由转换器推导；
- 输入文件和 submodule 版本是否足以复现同一 DAG。

### 3.2 转换正确性

需要确认 SimAI/AICB 任务转换成项目固定资源 DAG 后，是否保持研究所需的因果语义：

- compute 和 communication 分类是否正确；
- 原始依赖是否全部保留，新增依赖是否有明确理由；
- 是否遗漏、重复或错误合并任务；
- compute 顺序是否由依赖显式表达，而不是被模拟器暗中串行化；
- communication duration 或工作量换算是否确定且可复现；
- route 如何投影为固定且非空的资源集合；
- collective 内部语义保留到何种粒度，丢失了哪些信息；
- 单 iteration、多 iteration 和 multi-job 是否具有正确边界；
- 转换结果能否由公共模拟器执行并由独立 trace validator 回放。

### 3.3 竞争有效性

需要确认样例中是否存在真实的调度选择，而不只是任务很多或通信很多：

- 可达状态中是否同时存在多个 eligible communication；
- 这些通信是否争用相同资源；
- 多资源下是否存在不止一个合法的极大兼容集合；
- 不同动作是否会产生非等价未来状态；
- 简单策略实际发生分歧的决策点有多少；
- DP、job、arrival 和 topology 变化是否增强了有效竞争；
- 未观察到竞争是完整结论、有限前缀观察还是因超时未知。

### 3.4 可运行性与代表性

需要在覆盖范围和实验成本之间建立可解释的平衡：哪些规模能完成竞争审计、三基线和 Exact；哪些大图只适合转换、加载、前缀审计和内存测试；语料是否覆盖不同模型族、pipeline、并行度、topology、资源模型与 job 组合；是否因只保留可完成样例而造成选择偏差。

## 4. 不可改变的转换后语义

所有导出 benchmark 必须符合公共模型：

- 依赖为 finish-to-start；节点仅在全部前驱完成后 ready；
- compute ready 后自动开始、不可抢占并连续运行至完成；
- communication 可在离散调度事件处暂停和恢复，保留已完成工作；
- 有 eligible communication 时不得主动等待；
- 单 channel 任意时刻最多运行一个 communication；
- 固定多资源 communication 必须同时取得全部预先指定资源；
- 资源互不冲突的 communication 可以并行；
- 多资源动作必须是极大兼容集合；
- 不允许动态选路、迁移、部分获取资源或按比例共享带宽；
- 抢占和恢复暂不计额外开销。

SimAI 原生语义若比上述模型更复杂，应明确说明投影规则和信息损失。不能通过向导出 DAG 加入无依据的依赖边，使复杂网络行为表面上符合固定资源模型。

## 5. 输入资产盘点

### 5.1 Workload 清单

扫描可用 AICB workload，为每个文件记录：

- 相对路径、文件大小和内容 hash；
- 模型名称、来源及是否经过人工修改；
- world size、TP、PP、EP 和其他可直接获得的并行参数；
- global batch、micro-batch、sequence length、层数等展开参数；
- collective 类型和 pipeline schedule；
- 解析成功、字段缺失、格式异常或暂不支持状态。

无法解析或语义不完整的输入进入 quarantine 清单，不能静默跳过，也不能与正式输入混在一起。

### 5.2 Topology 清单

为每个 topology 记录相对路径、内容 hash、节点与链路层级、标称带宽及单位、route 确定方式、投影后资源粒度、来源类别，以及是否专门用于人为增强冲突。

原草稿中关于 Cassini、Hermod 及其他 topology 是否为生产拓扑的判断，在来源核查完成前只作为待验证信息。人为冲突 topology 必须单独标记，不能与真实来源 topology 合并报告。

### 5.3 版本与环境

每次正式生成保存主仓库与 SimAI submodule 的 commit/dirty 状态、转换器版本或源码 bundle hash、Python 与关键依赖版本、操作系统、生成命令、随机 seed 和全部参数。dirty worktree 不必禁止实验，但必须保存足以区分源码变化的信息。

## 6. 参数空间与候选矩阵

候选矩阵考虑：模型族与规模、pipeline schedule、TP/PP/EP/DP、batch 与 iteration、单/多资源、topology、单/multi-job、同构/异构 job、同时/错峰到达以及图规模。

不做无控制的笛卡尔积。第一轮以覆盖为目标，为重要维度保留代表样例和成对对照；第二轮只补充竞争不足、转换可疑或覆盖缺口。

每个参数实验尽量只改变一个主变量。例如 DP 曲线固定 source、TP、PP、topology、batch 和 iteration；arrival 实验固定 job 内容，只改变到达时间。多个变量同时变化时，不得把结果归因给单一变量。

## 7. 转换与发布流程

### 7.1 生成、审计和发布分离

正式语料采用三阶段流程：

1. `generate`：在独立 staging 目录生成 benchmark 和候选 manifest；
2. `audit`：检查输入、hash、DAG、资源、转换对拍和竞争证据；
3. `publish`：只把状态明确的候选发布到活动 corpus，并原子更新 manifest/index。

生成不等于发布，发布也不等于存在竞争。竞争审计未完成的文件可以保留在 staging，但不得用含糊的 success/probed 状态进入正式算法样本。

### 7.2 任务与依赖转换

对每个原始任务记录原始/导出 ID、job、iteration、micro-batch、stage、任务角色、类型、原始前驱、导出前驱、新增边来源、duration 换算和 route-resource 映射。

为显式表达 compute 顺序而添加的边必须与原始依赖分开记录，并证明它只是显式化原语义。不能只报告总 edge delta。

### 7.3 Duration 与资源换算

换算规范至少说明输入通信量及单位、有效带宽、资源相关速率、多资源 duration 规则、模拟器时间单位、浮点规范化、舍入、零时长和极小值处理。相同输入与参数应得到确定的 JSON。

单 channel 投影应让所有 communication 使用同一资源。固定多资源投影应绑定非空资源集合，并检查资源 ID 稳定性、双向链路处理、route 重叠、错误折叠、collective 资源和映射 hash。

### 7.4 Multi-iteration

必须区分 SimAI 原生动态执行产生的多 iteration 与导出层复制单 iteration。核对 iteration 边界依赖、optimizer/同步后的释放、命名空间、duration、资源以及原生 N-iteration 与导出结果的任务、边和 trace。

若 SimAI 没有静态 N-iteration 展开接口，动态 executor 对拍就是明确缺口，不能用单 iteration 复制结果替代认证。

### 7.5 Multi-job

组合器只做 workload 层组合：每个 job 保留独立 DAG 和来源；ID 使用稳定命名空间；job 间不增加依赖；所有 job 共享同一组全局固定资源；arrival 作为显式事件或规范化等价表达；输出全局和 per-job 信息。

组合前的单 job 必须能独立加载和回放。合并文件保存所有源 benchmark 的内容 hash，不能只保留合并后文件。

## 8. 分层正确性验证

### 8.1 格式与静态不变量

对全部候选运行 schema/loader 验证，检查 ID、依赖引用、DAG 无环、duration、非空资源、compute 不占通信资源、job/iteration 字段和 manifest hash。静态验证通过不代表转换语义正确或存在竞争。

### 8.2 极小样例语义核对

手工样例覆盖初始 compute、communication 释放 compute、新通信产生抢占机会、暂停恢复与工作量守恒、fork/join、零时长闭包、同时完成事件、单 channel 排他、多资源兼容、multi-job arrival 和 iteration 边界。

这些样例验证转换与模拟器契约，不用于证明真实 LLM 结构规律。

### 8.3 原生 builder/执行与导出对拍

选择代表 workload，比较任务总数与分类、稳定任务对应、原始边/新增边/无法对应边、duration、stage/micro-batch/iteration 标签、route-resource 映射及可比条件下的事件顺序。

对拍状态至少区分 `matched`、`explained_delta`、`mismatch`、`not_supported` 和 `not_run`。存在无法解释差异的组合不能获得完整转换认证。

### 8.4 独立 Trace 回放

对代表样例运行公共模拟器，再由独立 validator 检查工作量守恒、依赖、compute 连续性、暂停期间工作量、资源排他与完整获取、work-conserving、最终完成和 makespan。转换器自身不能是 trace 合法性的唯一检查者。

## 9. 竞争定义与证据等级

### 9.1 操作性定义

在稳定决策状态中：

- `eligible_count >= 2` 只说明有多个候选；
- 候选资源集合相交才说明有直接资源竞争；
- 单 channel 中多个候选天然冲突；
- 多资源中存在多个不同极大兼容集合才说明有集合级选择；
- 不同动作导致未来 residual state 不等价，才构成具有潜在调度价值的选择。

静态资源相交不等于可达竞争。策略分歧也不等于存在收益，因为动作可能未来等价或 makespan 相同。

### 9.2 逐样例指标

至少记录扫描状态、决策点数与终止原因、多个 eligible/资源冲突决策点数、极大集合数量或有界估计、非等价动作存在性、三基线分歧次数、候选数与冲突边分布、热点资源、首次/最后竞争时间，以及是否观察到抢占机会或 compute/barrier 释放。

### 9.3 证据等级

竞争证据明确分级：

1. `not_run`：尚未审计；
2. `static_only`：只做静态结构与资源扫描；
3. `sampled_prefix`：只回放有限决策前缀；
4. `bounded_search`：在状态或时间上限内搜索可达选择；
5. `completed_replay`：某个确定策略完成全图回放并记录沿途竞争；
6. `certified_choice_exists`：证明至少一个可达状态存在多个非等价合法动作；
7. `certified_no_choice`：穷尽全部可达状态并证明不存在非等价选择，仅适用于小图。

前缀中没有观察到竞争，只能写“在已扫描前缀中未观察到”。一个策略的完整回放也只覆盖该策略路径，不能证明所有动作路径无竞争。

### 9.4 正式分类

不再使用“满足若干条件即可认为有竞争”的宽松准入规则。样例分为：

- `informative-certified`：有可达非等价选择证书；
- `informative-observed`：完整回放或明确前缀观察到直接竞争和选择，但无全状态证书；
- `contention-structural`：静态潜在冲突，动态可达性未确认；
- `no-choice-certified`：小图已证明没有非等价选择；
- `no-contention-observed`：有限审计未观察到竞争；
- `unknown-timeout`：因时间、内存或状态上限无法判断；
- `invalid`：输入或转换验证失败；
- `excluded`：有明确排除原因。

算法主实验优先使用前两类并分开报告；其他类别仍保留，用作回归、负面对照、规模或待补证据研究。

## 10. 竞争增强实验

### 10.1 DP 曲线

固定 source、TP、PP、EP、batch、iteration 和 topology，比较 dp=1/2/4 等配置。记录 world size、任务/边/资源数、静态相交、动态证据等级、竞争指标、三基线状态、makespan、抢占、forced-idle、利用率和各步骤成本。

若 DP 只增加任务数而未增加可达竞争，标为无效竞争扩展；若更高 DP 因超时无法审计，只能得出成本上升、竞争未知。

### 10.2 Topology 对照

同一 workload 使用不同 topology 或固定投影，比较资源数、热点、route 重叠与动态竞争。真实来源和人为冲突 topology 分组报告。若 topology 同时改变 duration 和冲突，分别分析两种作用。

### 10.3 Multi-job 曲线

比较 1、2、3、4 个 job，覆盖同构副本、异构 workload、同时到达和错峰到达。4a 只验证组合、竞争增强和成本，同时报告 per-job JCT；专门目标与算法留给 4f。

### 10.4 Iteration 曲线

在原生多 iteration 对拍可信后，再比较 iteration 数量，检查是否产生新的跨 iteration 竞争或只是重复局部选择。在此之前，多 iteration 只能标为转换层受控输入。

## 11. 规模分层与抽样

规模不能只看 task count，还要结合 edge、communication、resource、决策点和回放耗时：

- 极小图：人工可核对或可穷举全部状态；
- 小图：在固定 Exact 预算内有机会获得最优证书；
- 中图：三基线可在统一预算内完整回放；
- 大图：至少可完成加载、静态审计和有界 probe；
- 超大图：只保留约 5--10 个规模压力样例。

正式阈值在预实验后固定并保存配置 hash。样本覆盖主要模型、pipeline、topology、资源模型、DP 和 job 组合；保留竞争与无竞争对照及超时样例；大图按规模和来源选择，不按候选算法收益选择；限制同一 source 的近重复样例数量。

## 12. 统一基线回放

### 12.1 基线

每个可运行样例至少比较 FIFO、基于当前 residual state 的基础 Longest Tail、按稳定 task ID 的固定顺序。多资源下三者使用明确且一致的极大集合补全规则；不同 packing 的比较留给 4c。

### 12.2 输出

每个 case × rule 保存完成/超时/失败状态、终止原因、makespan 或当前模拟时间、wall-clock、峰值内存、决策数、trace 或前缀 hash、抢占次数、通信区间、forced-idle、资源利用率、per-job completion/JCT、benchmark hash、规则版本和预算。

超时结果不能用当前模拟时间与完整 makespan 比较。不同预算或环境的重跑保留独立 run 标识，不静默覆盖。

### 12.3 用途边界

基线用于验证可执行性、发现策略分歧、建立后续参照、测量规模成本和发现非法动作。转换与 trace 未通过审查前，基线差异不能直接写成算法结论。

## 13. Real-derived Exact 切片

从真实 benchmark 提取少量可求解切片，保存源 hash、选取规则、保留/删除节点、截断边处理、边界节点、资源和 duration、竞争状态。优先覆盖单/多资源、barrier 和 multi-job 的代表结构。

Exact 报告保存状态、上下界、makespan、最优首动作、状态数、时间、内存和预算。只有 `optimal` 能生成最优证书；`feasible`、`time_limit` 和 `state_limit` 只能表示可行或未知。

## 14. 性能与规模实验

对大图分别测量输入解析、SimAI builder、DAG 转换、JSON 写出、schema/loader、静态扫描、有界 probe、完整 census、三基线、trace 验证、内存和文件大小。

除 task count 最大样例外，还应覆盖高 edge density、高 communication ratio 或高 resource conflict 的困难样例。每一步使用独立预算。前缀 probe 快不能推出完整回放或算法可扩展。

## 15. Manifest 与发布规则

### 15.1 必备信息

manifest 至少记录稳定 ID/路径、schema 和语义版本、suite、job/资源模型、规模层级、workload/topology/参数及 hash、仓库/SimAI/转换器版本、任务与资源统计、route-resource hash、benchmark hash、转换状态、竞争分类与证据等级、probe 配置 hash、报告路径、发布状态、排除原因和 run ID。

详细指标放在独立报告，manifest 保存摘要和报告 hash，避免重复维护不一致数据。

### 15.2 状态分离

分别保存：

- `conversion_status`：转换和语义验证；
- `contention_status`：竞争分类与证据；
- `publication_status`：staged、published、excluded、superseded 等。

不能用一个 `status=probed/completed` 同时表示文件有效、存在竞争和完整回放成功。旧格式需要迁移说明与兼容测试。

### 15.3 原子发布

发布前检查重复 ID/路径、文件存在、内容 hash、schema、已知状态枚举和 index 引用，在临时位置形成一致快照后再替换活动指针。失败时保留 staging 与错误报告，不留下部分发布语料。

## 16. 现有代码审查顺序

现有入口按以下顺序审查，文件名不代表实现已经正确：

1. `benchmark_generate/llm/catalog.py`：输入盘点与 quarantine；
2. `benchmark_generate/simai/export.py`、`projection.py`：任务、依赖、duration 和资源转换；
3. `benchmark_generate/llm/corpus.py`：staging、probe、manifest 状态与发布；
4. `benchmark_generate/llm/real_multi_job.py`：命名空间、arrival、共享资源与来源；
5. `benchmark_generate/llm/slice.py`：切片边界语义；
6. 集成测试：原生 builder/执行、导出结果与公共模拟器对拍；
7. `contention_census.py`：竞争定义、覆盖和超时语义；
8. `stage4a_baselines.py`：基线、合法动作、trace 和超时；
9. DP、multi-job、conversion pairing、Exact slice 和 scaling runner；
10. manifest、index、benchmark 与历史结果的 hash 一致性。

发现偏差后先建立最小复现和失败测试，再修改最小必要模块。公共转换语义变化后，重新生成受影响 benchmark、更新 hash，并判断旧基线与 reference result 是否失效。

## 17. 测试规划

### 17.1 单元测试

覆盖 AICB 字段、topology 映射、duration 单位与舍入、原始/新增边、iteration 命名空间、multi-job 无跨 job 边、arrival、共享资源、canonical hash、状态迁移和发布失败。

### 17.2 性质与回归测试

检查转换后仍为 DAG、通信资源非空、映射确定、compose 前后单 job 子图一致、重复生成字节级一致、job ID 不改变 job 内依赖、projection 只改变允许字段、hash 能检测内容变化。

### 17.3 端到端测试

用小型真实 workload 完成资产盘点、staging、审计、发布、加载、三基线、trace 验证和报告关联。覆盖单 channel、多资源、multi-job，并包含故意失败的发布或转换案例。

## 18. 实施步骤

1. 冻结字段、状态、竞争等级、规模层级、时间单位、资源投影与报告格式；
2. 盘点输入，使用极小图和代表性真实输入审查转换；
3. 修复后在 staging 重新生成语料，核对 hash 再发布；
4. 先做静态/前缀审计，再对可完成样例做完整 census 或有界搜索；
5. 由小到大运行三基线，保存所有超时和失败；
6. 分别完成 DP、topology、multi-job 和 iteration 受控曲线；
7. 生成少量 Exact 切片与大图分步骤规模报告；
8. 整理正式算法样本、负面对照、规模样本和待补证据样本，移交 4b--4g。

## 19. 研究产物

- workload/topology 资产目录；
- 转换语义规范和字段映射表；
- 原生 builder/执行与导出 DAG 对拍报告；
- 极小语义样例和回归测试；
- staging、发布和 manifest 状态规范；
- 活动 corpus 及 hash 一致的 index；
- 全量竞争分类表和逐样例报告；
- DP、topology、iteration 和 multi-job 曲线；
- 三个统一基线；
- real-derived Exact slice 与最优证书/未完成记录；
- 大图转换、扫描、回放、内存与超时报告；
- 无竞争、未观察到竞争、未知、无效、失败和排除清单；
- 供 4b--4g 使用的分层输入清单及限制；
- 审查问题、修复、迁移影响和剩余缺口记录。

## 20. 当前审查起点

截至 2026-08-18，仓库已有 72 个活动样例、约 129 万任务，并已有统一基线、DP 曲线、三个真实 multi-job case、top-10 规模报告和三个 real-derived Exact slice。这些资产说明已有流程可以运行，但不代表 4a 已完成。

当前证据边界包括：

- 72 个样例的现有 probe 主要覆盖最多 8 个决策点，属于 `sampled_prefix`；
- 只有极少数小图执行过有界选择存在性检查；
- 39 个不超过 12000 任务的样例中，大部分但并非全部能在既定预算完成三基线；
- dp>=2 的配对样例回放成本明显上升，其全图竞争状态未确定；
- top-10 大图三基线在紧预算内未完成，但前缀 probe 和部分转换测量可运行；
- 两个多资源真实切片有 Exact 最优证书，单 channel 切片仍为 time limit；
- 原生 builder 与导出任务数已有部分对拍，native multi-iteration 动态对拍仍缺失。

重新审查时需核对这些结果的输入 hash、代码版本和预算。若结果变化，以新证据更新过程文档，不能为了维护旧数字而调整定义。

## 21. 退出条件

Stage 4a 只有在以下条件全部满足后才能结束：

1. workload、topology、生成参数和版本来源有完整清单；
2. 任务、依赖、duration、固定资源、iteration 和 multi-job 转换均有规范与回归测试；
3. 代表性真实输入完成原生构建/执行与导出对拍，所有差异可解释；
4. 活动 corpus、manifest 和 index 的 hash 一致，发布可从 staging 复现；
5. 每个正式样例都有独立的转换状态、竞争分类和证据等级；
6. 前缀、完整回放、有界搜索和证书没有被混写；
7. DP、topology、iteration 和 multi-job 对竞争及成本有受控配对证据；
8. 主要中图能在统一预算完成三基线，不能完成者有明确状态；
9. 小型真实切片提供若干 Exact 证书，未完成 Exact 如实保留；
10. 约 5--10 个大图/超大图有分步骤耗时、内存与超时报告；
11. 无竞争、未观察到竞争、未知、无效和排除样例均保留；
12. 已形成供 4b--4g 使用的分层清单，并说明能支持和不能支持的结论。

阶段状态按“未开始、进行中、部分满足、完成”逐项评估。代码完成、生成大量文件或跑过一次基线，都不能单独把 4a 标为完成。

如果真实单 job DAG 大量缺少可利用竞争，这本身是重要结论：后续应转向能够产生竞争的 DP、topology 或 multi-job 条件，而不是在无选择样例上比较复杂算法。如果大图完整回放成本始终不可接受，也应明确后续算法的规模适用边界，或先单独研究不改变语义的性能优化。
