# Stage 4e Barrier 感知调度修正与验证建议

> 2026-08-22 口径更新：不再以完整真实 LLM corpus 为主实验集，改用 Stage 1--3 旧 benchmark、100--1000 节点小图和 1--2 个中大图的三层方案。

## 1. 修正目标

本方案针对 `stage4e_code_review_20260821.md`。修正重点不是继续增加 barrier 优先级，而是让每个特征名称与实际 residual 含义一致，严格隔离在线策略和离线上界，并用决策级标签验证“局部 barrier 推进—barrier 时间变化—最终 makespan”三层关系。

## 2. P0：冻结并修正特征定义

### 2.1 建立特征定义表

为每个字段记录：输入状态、计算节点范围、单位、是否包含候选自身、是否经过零时长闭包、证据等级、在线可用性和不能推出的结论。建议将证据等级统一为：

- `residual_exact`：公共状态直接给出；
- `structural_exact`：按明确图定义精确计算；
- `heuristic_estimate`：忽略未来竞争或依赖 completion policy；
- `source_label`：仅供分层；
- `offline_label`：Exact/反事实评价，禁止在线读取。

`structural_exact` 必须注明“结构定义精确，不代表时间或 makespan 因果精确”。

### 2.2 分开新增释放与可达总量

保留两个互斥概念：

- `newly_ready_compute_work`：假设候选或动作完成、处理同刻零时长闭包后，此前未 ready 而现在 ready 的 compute 工作；
- `reachable_descendant_compute_work`：结构可达的全部未完成 compute 工作，仅作规模描述。

`completion_gain` 删除或改成不带收益含义的名称。禁止把 immediate 再加到包含它的 descendant 总量。多资源动作按节点并集计算新增 ready，保存具体节点 ID 用于审计。

验收：共享后代图、多个前驱未完成图和零时长 compute 链上，手工结果与实现一致且无重复。

### 2.3 明确 direct 与 indirect barrier

将当前字段改名为 `direct_last_missing_join_count`。若实现间接 barrier，使用有界的自动 compute/依赖链传播，并明确：

- 搜索深度或访问预算；
- 首次汇合与所有可达 barrier 的区别；
- 局部、iteration 和全局层级；
- 共享 barrier 去重；
- 截断和 unknown 状态。

没有来源对拍前，不根据任务名称或 role 决定结构 barrier。

### 2.4 修正 arrival 与 slack

到达当前 barrier 的估计应沿“候选分支到 barrier”的方向累计剩余工作，而不是使用 dependency 到 sink 的 tail。明确处理 active compute、暂停通信和未来资源竞争；忽略竞争的结果标为 heuristic estimate。

至少输出最晚分支、次晚分支、候选分支估计、slack 和预计跨度变化。用手工双分支图验证方向和单位。

### 2.5 修正暂停通信字段

从公共状态明确取得上一次/当前可继续通信及其剩余工作。若稳定决策状态没有 active communication，就把字段定义为“切换离上次通信的机会代价估计”；多资源按当前/上次集合处理。无法给出可靠定义时先删除 `paused_tail_penalty`，不要读取 active compute 冒充通信。

### 2.6 删除恒定 packing 字段

从 barrier set score 删除 `packing_complementarity`。若需要资源互补，定义能在不同合法极大动作之间变化的量，例如动作资源覆盖、被阻塞候选的 residual 负载或互补分支释放，并通过两个极大动作结果不同的小图验证。

## 3. P0：隔离在线算法与离线上界

### 3.1 重命名完整双日程选择

将 `schedule_barrier_safeguarded` 和多资源对应函数移出在线算法注册，或重命名为 `offline_best_of_lt_and_barrier`。输出明确：

- `online=false`；
- `full_schedule_runs=2`；
- 使用最终 makespan 做事后选择；
- runtime 包含两次完整回放。

它只能用于估计候选策略组合的离线上界，不能与在线方法按同成本胜负比较。

### 3.2 保留 LT 的在线安全边界

在线方法以 LT 为基础，只允许三种明确增强：

1. 可审计初筛，但永远保留 LT 动作；
2. LT 分差在冻结 margin 内时用 barrier 打破或有限修正；
3. barrier 只作为 Stage 4d rollout trigger，评价不完整则回退 LT。

每次决策保存 baseline、被过滤候选、margin、barrier 原始特征、是否抢占、最终动作和 fallback。

### 3.3 严格预算

barrier selective rollout 复用修正后的 Stage 4d `RolloutBudget` 和共享账户，限制候选数、completion calls、展开、单决策和整图墙钟。100--1000 节点完整验证和 1--2 个中大图检查使用进程级硬超时。任何未完整评价的 challenger 不参与比较。

## 4. P1：实现三类 LT 增强

### 4.1 初筛

过滤器只删除能从当前事实证明无 barrier 影响且无关键立即释放的候选，同时保留 LT。记录过滤前后数量、被过滤最佳已知动作和错误过滤率。若无法证明，宁可保留。

### 4.2 tie-break 与 margin 修正

保留现有严格 tail tie-break 作为最小版本。增加归一化 residual tail margin：只有 LT 与 challenger 差距不超过开发集冻结阈值时，才允许 last-missing、slack 或新增 ready compute 改选。处理并列、零分母和部分完成通信。

优先使用词典序和有界规则；若使用权重，保存归一化、开发集敏感性和冻结值。

### 4.3 rollout trigger

固定候选生成、深度和预算，只改变触发信号。比较 barrier trigger、LT margin、choice-only、随机和周期触发。这样才能把 barrier 的增量价值与 rollout 本身分开。

### 4.4 多资源整集合评分

所有动作由 Stage 4c 已验证构造器生成，并保持相同 packing 规则。整集合特征对后代、barrier 和新增释放按节点并集去重；barrier 评分实验不能同时改变集合构造。若 Stage 4c 尚未验收，多资源 Stage 4e 质量结论保持 blocked/unknown，而不是绕过依赖。

## 5. P1：补齐最小反例和测试

至少增加：

- 直接 last-missing 的正例；
- 经零时长/非零 compute 链到达远端 barrier；
- 候选可达大量 compute 但完成后一个也不新增 ready；
- 两候选共享同一后代，动作并集不重复；
- 局部 barrier 提前但最终 sink 不变；
- 最后缺口不在最慢分支；
- 最近 barrier 与后续全局 barrier 给出相反选择；
- 高 barrier 分短通信抢占长关键通信并退化；
- barrier 数量多但 slack 很大；
- future resource competition 使 arrival estimate 失准；
- 静态 duration 与抢占后的 remaining 排序不同；
- 两个合法极大动作，新的资源特征确有区分；
- metadata/role 改变不影响结构判断；
- 在线策略不调用完整备选日程；
- 特征超预算时无声修改动作被禁止。

每个反例同时保存 LT、barrier 方法、Exact/首动作状态和 trace，明确预期机制。

## 6. P1：建立 barrier 因果标签

对 Exact 可完成的小图，在每个有选择状态保存：

- 全部合法首动作及最优后续值；
- LT 和 barrier 候选是否属于最优集合；
- 目标 barrier ready/complete 时间；
- 下一个重要 barrier 时间；
- 最终 makespan；
- 抢占和资源变化；
- Exact status、状态数、runtime 和内存。

分开统计：修复 LT 错误、破坏 LT 正确选择、barrier 提前且 makespan 改善、提前但持平、提前却退化。heuristic completion 结果标为条件观察，不冒充 Exact 因果标签。

## 7. P2：冻结三层数据与 barrier 统计

### 7.1 Stage 4e 三层清单

建立固定清单：第一层为 Stage 1--3 旧 benchmark 主实验，第二层为 100--1000 节点随机图、攻击图和少量可追溯 real-derived slice，第三层只预选 1--2 个中大图。real-derived 样例仍记录转换状态、固定资源映射、竞争证据和来源 hash；sampled prefix 未观察到 barrier 或分歧不能写成全图不存在。

### 7.2 分层 barrier 统计

在 Stage 1--3 主集合和 100--1000 节点验证集逐样例、逐决策统计：

- barrier 类型、前驱数、层级、共享和嵌套；
- direct/indirect last-missing 次数；
- eligible 候选中各信号比例；
- 与 LT 分歧次数；
- 分歧后 barrier 时间和 makespan 变化；
- 特征访问节点/边、runtime、内存和截断状态。

第一层和第二层分别汇总；1--2 个中大图逐例报告。real-derived slice 的完整回放、sampled prefix 和有界分析继续明确区分。

### 7.3 防止数据泄漏

Stage 1--3 按模板划分开发和 validation，同模板不同 seed 不跨组。margin、权重和筛选规则只在第一层选择，100--1000 节点验证集不参与调参。相同来源的 real-derived 相邻切片不得跨边界造成泄漏。

## 8. P2：统一实验与结果契约

正式对照至少包括 FIFO、固定顺序、residual LT、barrier-only 诊断、LT 初筛、严格 tie-break、margin 修正、barrier trigger rollout、相同调用率随机/周期 rollout，以及小图 Exact。

新 schema 使用正式 Stage 4e 编号，并保存：

- benchmark/hash、manifest/转换版本、数据分层；
- 代码/模拟器版本、环境、seed 和完整配置；
- online/offline、完整 schedule 运行数和信息范围；
- makespan、FIFO/LT gap、Exact status/gap；
- barrier ready/complete 和动作分歧；
- 修复、破坏、提前但无收益/退化计数；
- 决策、信号、候选、过滤和 rollout 调用；
- 抢占、通信区间、forced idle、总体/逐资源利用率；
- context、特征、评分、搜索和总 wall-clock；
- 访问节点边、缓存、峰值内存、timeout、fallback 和 unknown；
- trace hash 和验证状态。

报告平均、中位、分位数、最坏退化和逐样例结果。超时、无改善和 fallback 不能从分母删除。

## 9. 推荐实施顺序

1. E1：冻结旧结果并标明 online/offline 和历史编号；
2. E2：完成特征定义表，重命名 direct/reachable 字段；
3. E3：修复新增 ready、arrival/slack、暂停通信和恒定 packing 字段；
4. E4：隔离完整双日程上界，收窄公开在线入口；
5. E5：实现初筛、严格 tie-break 和 margin 修正；
6. E6：接入 Stage 4d 严格预算 trigger；
7. E7：补齐反例、手工检查和全部首动作/barrier 时间标签；
8. E8：冻结 Stage 1--3 主集合、100--1000 节点验证集和 1--2 个中大图，完成分层统计；
9. E9：运行单通道、多资源、消融、冻结验证和有限中大图成本实验；
10. E10：形成适用范围和正面、受限或否定结论。

公共模拟器、Exact、schema 或 benchmark 变化后运行完整测试，重新生成受影响标签和结果；旧结果保留为 legacy，不覆盖。

## 10. 再验收标准

| 验收项 | 通过标准 |
|---|---|
| 特征命名 | 每个字段与实际节点范围、单位和证据等级一致 |
| 新增释放 | 只计候选完成后新增 ready，零时长闭包正确且无重复 |
| barrier 范围 | direct、indirect、局部和全局定义及截断明确 |
| arrival/slack | 方向是分支到 barrier，并标明未来竞争估计误差 |
| 暂停影响 | 读取真实通信剩余状态，不使用 active compute 冒充 |
| 多资源集合 | 合法极大、节点并集去重、评分与 packing 构造正交 |
| 在线边界 | 在线方法不使用完整备选日程最终 makespan |
| 离线上界 | 明确两次完整回放和不可部署信息范围 |
| 初筛 | 永远保留 LT并报告错误过滤率 |
| 条件修正 | margin 冻结，阈值外严格保持 LT |
| trigger | 与相同调用率随机、周期和非 barrier 对照 |
| 小图标签 | 首动作、barrier 时间和最终 makespan 可独立复核 |
| 冻结验证 | 参数在 Stage 1--3 确定，100--1000 节点完整报告最坏退化 |
| 成本 | 特征、搜索、内存、超时和 fallback 全部计入 |
| 阶段结论 | 明确 barrier 应作为何种组件，或形成否定结论 |

所有条件满足前，Stage 4e 继续保持“特征原型/诊断工具”状态，不作为 Stage 4g 默认组件。
