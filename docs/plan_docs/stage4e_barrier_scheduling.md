# Stage 4e：Barrier 感知调度研究

## 1. 阶段定位

Barrier 指 LLM training DAG 中由 pipeline、DP/TP/EP collective、optimizer join 或多个分支汇合形成的同步屏障。Barrier 感知用于识别最终屏障的延后原因，帮助 Longest Tail 减少无关候选，不是以“距离 barrier 最近”替代 Longest Tail。

## 2. 问题定义与特征

对当前状态和候选通信，研究其完成后是否减少 barrier 未完成前驱、释放计算或通信，并最终缩短联合 DAG makespan。必须区分局部完成、下一个 barrier 到达和最终 makespan。

从 residual state 计算 barrier 未完成前驱及剩余工作、候选是否最后缺口、完成后递归释放的任务、各分支 residual tail 和 slack、新增 ready 任务、暂停当前通信的尾部增量，以及多个候选是否共享同一 barrier 后继。不能用初始 DAG 静态时间替代 remaining work。

## 3. 算法探索

先排除完成后不会减少当前重要 barrier 缺口、也不会释放关键计算的候选；判断不确定时保留候选，再对剩余候选按 Longest Tail 排序。当 Longest Tail 分数接近时，优先能减少最后缺口、释放关键计算且不占用热点资源的候选。新通信 ready 时，只有暂停后的公共 transition 严格改善且不会延长关键尾部才允许抢占，否则继续当前通信。

## 4. 实验、反例和退出条件

构造 barrier 最后缺口、分支 slack 不同、局部提前完成但最终由另一分支支配、靠近 barrier 但工作量很小、暂停长关键通信反而变差以及多个 barrier 互相竞争的样例。比较 FIFO、Longest Tail、只按 barrier 距离、筛选后 Longest Tail、影响修正和 barrier 加 rollout。小图用 Exact 标注首动作和抢占价值，大图分层报告完成时间、barrier 到达时间、运行开销、抢占和最坏退化。

每个正面结果都要解释哪个最后缺口支配最终完成，每个负面结果都要说明 slack、共享后继或抢占后尾部增加的原因。只有 barrier 信息在多类真实 DAG 上稳定减少错误候选且成本可接受，才进入 4g；否则保留否定结论。

