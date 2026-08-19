# Stage 4f：Multi-job 调度研究

## 1. 阶段定位

Multi-job 指不同训练 job 在同一集群中同时运行。研究重点不是复制单 job 后只求一个总 makespan，而是观察 job 之间的资源竞争、完成时间和结构是否改变调度规律。

## 2. 问题定义与目标

每个 job 有独立 DAG、来源 workload、到达和完成时间；job 之间没有依赖边，只共享固定通信资源。基础目标可以是联合 makespan，但必须另外报告每个 job completion time、平均/最大 completion time、slowdown 和公平性。每种策略先声明目标，不能混用结论。

## 3. Benchmark 与算法

使用 4a 的真实 AICB workload 构造同一 workload 多副本、不同模型混合、不同 DP/PP 配置混合三类集合，至少测试 2、3、4 个 job，并保留单 job 对照。

FIFO 按 job 到达和通信 ready 时间排队；flat Longest Tail 忽略 job 边界，对所有候选统一按 residual tail 排序；job-aware Longest Tail 先计算每个 job 的剩余工作、最长尾部、barrier 缺口和等待时间，再在 job 内按 Longest Tail 选通信；weighted JCT 或公平性策略必须明确声明目标。所有策略都使用公共 maximal-action transition。

## 4. 实验与退出条件

先在小型混合图上用 Exact 或首动作穷举判断 job-level 选择是否值得，再在真实中型图比较专用规则，最后在少量大图测成本。检查单 job phase 是否消失、flat 策略是否已足够、优先短 job 是否使总体 makespan 变差、一个 job 是否长期饥饿，以及不同目标是否冲突。

报告总体 makespan、每个 job completion time、平均/最大 completion time、slowdown/公平性、运行时间、抢占、forced-idle 和利用率。必须给出多 job 是否更混乱、简单策略是否足够、job-aware 规则何时有效及最坏退化；没有跨 workload 的稳定证据时停止复杂策略。

