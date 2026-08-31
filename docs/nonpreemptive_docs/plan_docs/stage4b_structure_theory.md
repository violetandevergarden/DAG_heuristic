# Stage 4b：不可抢占 LLM DAG 结构探索

## 1. 阶段定位

本阶段只使用 Stage 4a 发布或明确标注的真实、real-derived 输入，研究哪些 LLM training 结构会改变不可抢占通信的启动选择。合成 motif 只用于解释机制和构造反例。

不可抢占决策具有不可撤销性：通信启动后不能因新事件重新选择。因此核心问题不是“何时暂停”，而是“启动前能否预测连续占用造成的释放收益和阻塞风险”。

## 2. 研究对象

- micro-batch、iteration 与 warmup/steady/cooldown 重复；
- pipeline stage、forward/backward、B/W 分离；
- TP、DP、PP、EP communication；
- collective completion、join、optimizer 和 barrier；
- 通信长度、固定资源脚印与热点；
- 同构/异构 multi-job 及 arrival；
- 当前运行通信结束前可能释放的未来关键通信。

结构定义应来自任务、依赖、资源和来源 sidecar，不依赖不稳定任务名称。来源标签是辅助证据，在线算法只能读取公开输入和当前状态。

## 3. 必须重新验证的问题

每条候选结构结论需要回答：

1. 如何从 DAG 与当前不可抢占状态定义；
2. 在哪些真实 workload、topology 和并行配置中出现；
3. 是否出现在有多个合法启动动作的状态；
4. 是否改变 compute、join/barrier 或后续通信的释放时间；
5. 当前通信的连续占用是否覆盖了这些未来事件；
6. 是否改变最终 makespan，而非只提前局部节点；
7. optional-idle 是否改变该结构的价值；
8. 有哪些反例和失效条件；
9. 适合进入 packing、rollout、barrier 或 multi-job 的哪一环。

## 4. 不可抢占特有特征

除 residual tail、slack、last blocker 等通用特征外，重点统计：

- 候选完整 duration；
- 候选执行区间内预计发生的 compute/job arrival 事件；
- 这些事件可能释放的通信及其 tail、资源和 barrier 作用；
- 候选对热点资源的连续占用时间；
- 候选完成后新增的 ready communication；
- 立即启动相对 WAIT 的机会成本；
- 多资源中 active reservation 对候选集合的限制。

预计释放时间依赖未来竞争时必须标为启发式估计，不得写成精确事实。

## 5. 方法

1. 在 4a manifest 上做结构 census，并区分完整回放与 sampled prefix。
2. 只在真实启动决策点统计策略分歧，避免把无选择状态算作证据。
3. 在 Exact 可完成的小图上枚举首动作，标记结构信号是否命中最优动作。
4. 对真实图提取可追溯切片，保留边界 release 和资源占用。
5. 为每条假设构造最小支持例和最小反例。
6. 使用相同 completion policy 做反事实回放；只有 Exact 完成时才称为因果最优。

## 6. 旧 R5 的使用边界

旧 R5 中的 backbone/deferred work、optimizer deadline、周期缓存和 frontier 标签可作为候选假设与实现材料，但必须：

- 核对其是否真正使用最终不可抢占语义；
- 在新的 4a manifest 上重算；
- 与 residual Longest Tail、FIFO 和固定顺序比较；
- 报告无分歧、无收益和退化样例；
- 不把旧 motif 收益写成真实 corpus 结论。

## 7. 产物与退出条件

产物包括真实结构目录、特征定义、出现频率、策略分歧统计、Exact 小图标签、反例和面向 4c--4f 的候选清单。

只有满足以下条件才可结束：

1. 所有正式结论来自 4a 输入或可追溯 real-derived slice；
2. 特征区分结构精确量、状态精确量、启发式估计和来源标签；
3. 至少覆盖 pipeline、barrier、重复、资源热点和 multi-job；
4. 报告结构出现、动作分歧、局部释放和 makespan 影响四个层次；
5. 每个拟进入后续阶段的特征都有支持例、反例、成本和适用范围；
6. optional-idle 与 work-conserving 的差异被单独报告；
7. 没有稳定信息的结构形成否定或受限结论。
