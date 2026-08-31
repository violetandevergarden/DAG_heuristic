# Stage 4a：不可抢占真实 benchmark 构建

## 1. 阶段定位

本阶段为不可抢占 Stage 4 的输入门槛。目标是复用已经核对过的 SimAI/AICB 转换链，发布采用不可抢占通信语义的自包含真实 DAG，并重新审计竞争、可选择性、回放成本和 Exact 可解范围。

不可抢占 R0--R4 已经覆盖执行语义、Exact、并行链、一般 DAG 和固定多资源，不在本阶段重做。旧 R5 的 LLM motif 和结构策略只作为历史材料，不能替代真实输入证据。

## 2. 固定语义

- 依赖为 finish-to-start；全部前驱完成后节点才 ready。
- compute ready 后自动开始，连续运行到完成，可以相互并行并与通信重叠。
- communication 一旦启动，必须连续运行到完成；期间新释放的通信只能等待。
- 单 channel 中运行通信独占 channel；固定多资源通信同时占有全部所需资源。
- 不允许动态选路、迁移、部分获取资源或带宽按比例共享。
- channel 或部分资源空闲时，允许主动等待到下一个真实任务或 job 事件；WAIT 必须由模拟器判定合法。
- 基础目标为 makespan；multi-job 指标单独定义。

正式实验同时保留 `optional_idle` 和 `work_conserving` 两种口径。前者是不可抢占主模型，后者用于 WAIT 消融和与可抢占结果的受控比较，二者不得合并统计。

## 3. 输入复用与发布边界

优先复用 `benchmark_generate.llm` 与 `benchmark_generate.simai` 中已经核对的 workload、topology、任务和依赖转换。不得把已有可抢占 JSON 只修改 `semantics` 字段后发布；必须通过不可抢占 loader、validator 和 trace 语义检查。

同一来源的成对样例应共享稳定的 `source_id`，并分别记录：

- 来源 workload、topology 和生成参数；
- tp、pp、dp、ep、iteration、job 数和 arrival；
- 任务数、边数、通信资源集合和内容哈希；
- 不可抢占 schema、WAIT 模式和转换版本；
- 与可抢占对应样例的关系，但不共享 reference result。

发布继续采用 staging、候选 manifest、校验和原子发布流程。算法运行时不得依赖 SimAI、metadata 中的答案或可抢占结果。

## 4. 不可抢占竞争审计

可抢占的事件前缀不能证明不可抢占场景存在选择。审计至少区分：

- 启动决策点：没有运行通信，且存在至少一个可启动通信；
- 排序选择：单 channel 中同时有两个以上 ready communication；
- 集合选择：多资源中存在两个以上不同的合法启动集合；
- 等待选择：立即启动与 WAIT 都合法；
- 延迟阻塞：当前启动的长通信会阻塞稍后释放的关键通信；
- 无选择：合法动作在 tie-break 后唯一。

多资源审计必须保留正在运行且不可移除的通信，只在剩余空闲资源上构造新启动集合。`sampled_prefix`、完整回放、静态扫描和有界动作存在性检查分别标记，不能互相替代。

## 5. benchmark 分层

- 小图：手工可核对或可由不可抢占 Exact 给出证书。
- 中图：能在统一预算内完成 FIFO、Longest Tail、固定顺序和候选策略。
- 大图：用于转换、加载、特征、回放、内存和超时测量。

语料覆盖单 job/multi-job、单 channel/固定多资源、不同模型族、并行配置、topology 和规模。无竞争样例作为负对照保留，但不能稀释正式收益统计。

## 6. 统一基线与指标

每个可运行样例至少比较：

- FIFO；
- 输入固定顺序；
- residual Longest Tail；
- work-conserving Longest Tail；
- optional-idle Longest Tail；
- 小图 Exact，分别报告 optional-idle 和 work-conserving 最优值。

报告 makespan、wall-clock、峰值内存、完成状态、状态数、主动 WAIT 次数和时间、forced idle、资源利用率、候选数、动作分歧数和 fallback。超时与 state limit 保留为 unknown。

## 7. 验证

1. 选择至少一个小型 AICB workload，逐任务核对原生 builder、导出 DAG 和不可抢占 trace。
2. 验证每个正时长 communication 只有一个连续执行区间。
3. 验证通信运行期间的 compute 完成只释放候选，不中断通信。
4. 验证多资源占用在通信完成前持续保留。
5. 对成对输入核对任务、依赖和资源映射，允许差异只能来自明确记录的语义字段或 serializer 边。
6. benchmark 或转换变化后重算内容哈希和 reference result。

## 8. 退出条件

只有同时满足以下条件，Stage 4a 才可结束：

1. 已发布可追溯、自包含的不可抢占真实 DAG 和分层 manifest；
2. 转换与至少一个原生小 workload 完成逐任务对拍；
3. 正式样例具有明确的不可抢占竞争审计等级；
4. 普通规模样例完成统一基线，失败与超时未被排除；
5. 小图具有 Exact 证书或明确的未完成状态；
6. optional-idle 与 work-conserving 分组报告；
7. 大图转换、加载、回放、内存和退化边界有成本报告；
8. multi-iteration 和 multi-job 的来源、组合规则及缺口被记录。

当前状态为“计划开始”：R0--R4 可作为回归基线，但 `benchmark/llm_structure/nonpreemptive` 尚无正式样例，旧 R5 不能满足本阶段退出条件。
