# Stage 4d Selective Rollout 修正与验证建议

## 1. 修正目标

本方案针对 `stage4d_code_review_20260821.md` 的发现。修正顺序是：先使深度、候选和预算配置真实生效；再修正触发特征与缓存；随后建立决策级标签和统一实验协议；最后用 Stage 4a 分层真实输入做等预算 holdout。不要在错误信号和软预算上继续调阈值。

## 2. P0：修正配置与执行契约

### 2.1 明确定义深度

建议统一为：

- depth 0：不进行 rollout，直接 LT，零 completion call；
- depth 1：比较不同首动作后使用同一末端估值；
- depth 2 及以上：明确每一层是通信决策层还是事件层，并记录实际展开深度；
- 完整 LT completion 单独作为 terminal evaluator，不混入“深度”计数。

若当前只支持 LT 固定前缀，应把参数更名为 `prefix_decisions`，不要称为通用搜索深度。增加 depth 0/1/2 的动作、调用、展开和 trace 回归测试。

### 2.2 实现真实候选宽度

候选生成器应返回稳定排序、去重的动作列表，至少包含 LT baseline，并记录：

- 可用动作总数；
- 截断前后候选数；
- 候选来源和排序；
- 是否包含 Exact 最优首动作；
- 截断原因。

`max_candidates=0` 定义为关闭 rollout，`1` 定义为仅 baseline，`2+` 才评价额外候选。单通道候选是通信；多资源候选必须由 Stage 4c 提供合法极大集合。任何候选都由公共模拟器再次验证。

### 2.3 分开四个接口

将以下职责明确拆开：

1. `baseline(state) -> action`；
2. `candidate_generator(state, limit) -> candidates`；
3. `trigger(features) -> decision`；
4. `evaluator(state, candidates, budget) -> outcome`。

结果同时保存 baseline、候选、触发决定、实际评价候选和 selected。未触发时不能把“有候选”记为“已评价”；预算拒绝也不能记为正常持平。

## 3. P0：建立严格共享预算

### 3.1 原子预留与逐层检查

`BudgetAccount` 增加 `try_reserve_completion`、`try_expand` 和 deadline 检查。每次启动候选 completion 前先预留一次调用；每展开一个通信决策或事件后检查展开和时间。LT 与 challenger 使用同一账户，禁止完成后才发现越界。

第二个候选完成后必须再次检查 expansion 和时间状态。任何不完整估值不得参与大小比较，直接执行 LT 并记录 `incomplete_evaluation` 及具体原因。

### 3.2 单决策与整图墙钟

协作式检查只能作为软预算。正式真实回放增加进程级整图硬超时，由父进程标记 timeout 并保留输入、配置和已完成统计。若单次 completion 无法安全中止，启动前采用保守上限，并明确报告软超时可能超出的实际时长。

### 3.3 统一统计

至少区分：

- trigger positives；
- 完整 rollout evaluations；
- budget-rejected triggers；
- generated/evaluated candidates；
- completion calls；
- expanded decisions/events；
- fallback 次数及逐原因；
- 特征、候选、评价和总耗时。

验收要求包括 `completion_calls <= max_completion_calls`、`expanded <= max_expansions`；硬超时结果不能标记为 completed。

## 4. P0：修正触发特征和缓存

### 4.1 修正启发式分歧

分别运行两个完整、确定性的便宜策略，比较它们各自的首选动作。只有首选不同才设置 disagreement。保存策略名称、首选和排序分数，不能通过“找一个不同任务”制造分歧。

### 4.2 特征绑定被比较动作

将释放和 join 特征改为逐候选字段，例如：

- baseline/challenger 完成后的新增 ready compute；
- baseline/challenger 是否为某个 join 的最后未完成前驱；
- 两动作释放量差；
- 暂停当前通信对下一竞争窗口的差异。

全局是否存在某类任务可作为独立 context 字段，不能冒充当前候选的因果信号。

### 4.3 修正 delta 和缓存

若保留现有含义，将 `ready_set_delta` 更名为 `eligible_comm_delta`；若计划确需 ready task 变化，就从公共状态计算真正的 ready task 集合。任何依赖前序集合的特征要么从缓存值中移除，要么把前序集合稳定摘要加入缓存键。

增加反例：同一归一化当前状态由两个不同 previous eligible 集合到达，缓存开关必须产生相同的正确特征和动作。

### 4.4 版本化特征

修正后升级 `FEATURE_VERSION`，旧标签和旧结果保持 legacy。结果保存所有原始特征和最终触发规则，避免只保存布尔值。

## 5. P1：补齐正确性和失败模式测试

至少增加：

- depth 0/1/2 的明确行为；
- max_candidates 0/1/2/4 的实际候选数量；
- completion 和 expansion 恰好用尽、差 1 和超限；
- LT completion 已超时，不再启动 challenger；
- challenger 完成导致 expansion 超限时回退 LT；
- 总时间在一次 completion 中耗尽；
- 第三候选触发释放但 LT/challenger 不触发的污染反例；
- 两个启发式首选相同但排序后部不同，不应标为分歧；
- 缓存历史量隔离；
- 候选估值并列时稳定保留 LT；
- 单通道和多资源候选始终合法；
- fallback trace 与纯 LT trace 一致；
- forced idle 不成为算法可选 WAIT。

对缓存增加对照：关闭缓存、正确缓存和未缓存基准在随机小图上动作及 makespan 一致。

## 6. P1：建立决策级真值

### 6.1 标签定义

对小图每个有实际选择的状态，枚举全部合法首动作，并用未压缩 Exact 求最优后续值。标签分为：

- positive：至少一个非 LT 首动作严格改善；
- negative：LT 属于全部最优首动作且 rollout 无质量价值；
- equivalent：不同动作未来状态经独立证明等价；
- unknown：Exact 超时、状态上限或候选未完整覆盖。

unknown 不得当作负例。保存 benchmark hash、状态摘要、全部首动作值、并列最优集合和 Exact status。

### 6.2 分离三个错误来源

分别报告：

- 触发错误：该搜未搜或不该搜却搜；
- 候选错误：触发但最优动作不在候选中；
- 评价错误：最优动作已在候选中但估值未选中。

precision/recall 之外，按漏掉的 makespan 改善和误触发额外成本加权，避免把所有决策视为同等重要。

## 7. P2：重建 Stage 4d 实验协议

### 7.1 正式编号与结果契约

runner 和新 schema 使用 Stage 4d，例如 `stage4d-selective-rollout-v2`。旧 `stage4e-selective-evaluation-v1` 结果不删除，标记为 legacy，注明 depth、候选、特征和预算缺陷。

结果至少保存 benchmark/hash、manifest/转换版本、数据类别、工作负载和 topology、算法配置、seed、触发原因、候选、实际深度、预算前后、状态、makespan、Exact gap、抢占、通信区间、forced idle、利用率、内存、分项时间、trace hash 和环境。

### 7.2 数据分层与划分

数据分别报告：

- 随机小图；
- 攻击图；
- real-derived Exact slice；
- Stage 4a 中型真实图；
- 大图压力集。

按原始模板或 workload 分组划分开发、验证和 holdout，禁止同一模板不同 seed 或同一真实 workload 的相邻切片跨组。阈值只在开发/验证集选择；holdout 冻结后只运行最终配置。

正式真实样例必须记录 Stage 4a 转换和竞争证据等级。sampled prefix 未观察到分歧只能标 unknown，不能判为负例。

### 7.3 完整对照

至少比较：

- 纯 LT；
- choice-only 全量 rollout；
- 随机触发；
- 周期触发；
- 各单一触发信号；
- 冻结的组合触发器。

做两类公平实验：一类固定候选/深度看触发节省；另一类固定总墙钟、调用或展开预算，把节省额度用于更宽或更深搜索。随机触发使用多个固定 seed 并报告分布。

## 8. P2：质量—成本和 holdout

每个配置报告：

- makespan 相对 FIFO 和 LT 的变化；
- 小图 Exact gap、最优率、首动作命中；
- trigger precision/recall、误触发、漏触发及质量损失；
- 候选召回率和评价误判率；
- 触发率、候选数、completion calls 和展开数；
- 总及分项 wall-clock、峰值内存；
- 完整率、超时、fallback 和逐原因；
- 抢占、通信区间、forced idle 和资源利用率；
- 中位数、分位数、最坏退化和逐样例表。

不能删除无改善、超时或 fallback 样例后计算收益。若真实 holdout 只有成本下降而质量相同，应将其结论限定为成本控制层；若没有稳定净收益或最坏退化不可接受，则记录为小图分析工具，不进入 Stage 4g。

## 9. 推荐实施顺序

1. D1：冻结当前代码和旧 45-case 结果为 legacy；
2. D2：修复 depth 与 max_candidates，建立显式候选列表；
3. D3：实现共享预算预留、逐层检查和硬超时；
4. D4：修正 disagreement、候选释放/join 特征、delta 和缓存键；
5. D5：补边界、缓存和预算失败测试；
6. D6：建立小图全部首动作 Exact 标签；
7. D7：冻结 Stage 4d v2 manifest、开发/验证/holdout 和结果 schema；
8. D8：运行触发、候选、评价和宽深等预算消融；
9. D9：执行真实 holdout 和大图压力实验；
10. D10：形成适用范围、成本和失败案例结论，决定是否进入 Stage 4g。

每项只改最小必要模块。公共模拟器、Exact、benchmark 或 schema 变化后运行完整测试，并重生成受影响标签和结果，旧文件保留但停止作为当前证据引用。

## 10. 再验收标准

| 验收项 | 通过标准 |
|---|---|
| 深度 | 0/1/2 含义、实际展开和输出记录一致 |
| 宽度 | max_candidates 严格限制真实候选并报告截断 |
| 调用预算 | completion calls 永不超过配置 |
| 展开预算 | 每条分支逐层检查，最终计数不超限 |
| 时间预算 | 软/硬预算分开标记，硬超时不冒充完成 |
| 回退 | 任一不完整评价执行 LT并保留具体原因 |
| 特征 | 分歧来自真实策略首选差异，释放/join 绑定候选 |
| 缓存 | 所有影响特征的量进入键，开关缓存结果一致 |
| 决策标签 | positive/negative/equivalent/unknown 可独立复核 |
| 错误归因 | 触发、候选召回和评价误判分别统计 |
| 等预算实验 | 节省预算确实用于更宽或更深配置并公平比较 |
| 真实 holdout | 参数冻结，报告完整率、最坏退化和全部成本 |
| 阶段结论 | 能回答哪些真实决策值得搜索及净收益是否值得 |

上述条件全部满足前，Stage 4d 保持“研究原型”状态，不进入 Stage 4g 默认组合。
