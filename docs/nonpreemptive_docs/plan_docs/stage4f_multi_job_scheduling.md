# Stage 4f：不可抢占 Multi-job 调度

## 1. 阶段定位

本阶段研究多个独立 AICB training DAG 在同一固定资源系统中的不可抢占通信调度。job 之间没有依赖边，只通过共享通信资源耦合。长通信的不可撤销占用可能造成明显的跨 job 队头阻塞，因此不能直接套用单 job makespan 结论。

## 2. 输入

正式输入由 Stage 4a 组合并发布，至少覆盖：

- 同构与异构 workload；
- 同时与错峰 arrival；
- 不同 tp/pp/dp/ep 和 iteration；
- 单 channel 与固定多资源；
- 共享热点不同的 topology；
- 单 job 对照和无竞争负对照。

组合规则必须保证 job 命名空间独立、无跨 job 依赖、arrival 明确、资源真实共享，并保存每个源 benchmark 的 hash。合成复制只能用于机制实验，不能替代真实 AICB multi-job 证据。

## 3. 优化目标

每次实验预先声明且分别报告：

- 联合 makespan；
- 平均、加权和最大 Job Completion Time；
- slowdown；
- fairness 或 starvation；
- 每个 job 的 arrival、start、completion 和 JCT。

改善一个目标但恶化其他目标必须完整呈现，不能笼统称为性能改善。

## 4. 基线与候选策略

- 全局 FIFO；
- 全局 residual Longest Tail；
- 固定 job 顺序；
- round-robin 或年龄优先；
- shortest/longest remaining job；
- job-aware Longest Tail；
- starvation safeguard；
- WAIT-aware 策略；
- selective rollout；
- 多资源合法启动集合策略；
- 小图按目标定义的 Exact。

策略分数必须使用当前 residual job 和 DAG 状态。不得用单 job makespan 分数解释 JCT 或 fairness。

## 5. 研究问题

1. multi-job 是否显著增加真实启动选择和策略分歧；
2. 全局 Longest Tail 是否已经足够；
3. 长通信连续占用何时造成跨 job 队头阻塞；
4. optional idle 能否等待即将到来的高价值 job 通信；
5. job-aware 规则何时改善 JCT、何时恶化 makespan；
6. 同构/异构和同时/错峰 arrival 是否改变结论；
7. 单 job pipeline、barrier 和重复特征在混合后是否仍有效；
8. 是否出现 starvation，以及保护规则的成本。

## 6. 实验设计

先用可由 Exact 或手算验证的双 job 小图分离目标，再在真实双 job/多 job manifest 上比较。开发、validation 和 holdout 按源 workload/topology 分组，避免同一来源的复制或相邻切片泄漏。

对每个 multi-job case 同时运行对应单 job，分解收益或退化来自资源竞争、arrival 还是策略。optional-idle 与 work-conserving 使用相同输入但独立报告。

## 7. 指标与失败模式

除目标指标外，报告每 job 通信等待时间、热点资源占用、主动 WAIT、forced idle、资源利用率、策略切换、starvation 事件、wall-clock、超时和 fallback。

重点反例包括：大 job 垄断、短 job 优先导致总 makespan 恶化、Longest Tail 饥饿小 job、公平保护延迟关键 barrier、错峰 arrival 被长通信遮蔽，以及多资源局部公平但全局低效。

## 8. 退出条件

1. 正式 benchmark 来自可追溯真实 job，组合语义通过验证；
2. 目标函数在算法、Exact 和报告中一致；
3. 同构/异构、同时/错峰、单/多资源均有覆盖；
4. 单 job 对照、FIFO、Longest Tail、简单 job-aware 和候选算法统一比较；
5. 小图按各目标取得 Exact 或明确 unknown；
6. 报告逐 job JCT、slowdown、fairness、makespan 和成本；
7. starvation、目标冲突和最坏退化有固定反例；
8. 在未参与调参的真实 holdout 上验证；
9. 若简单策略已经足够，或专门算法只交换目标而无稳定净收益，形成受限或否定结论。

Stage 4g 不在本轮规划范围内。只有 4a--4f 中通过统一输入、基线、消融、反例和成本验证的组件，未来才可考虑综合。
