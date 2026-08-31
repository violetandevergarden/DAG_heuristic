# Stage 4d：不可抢占 Selective Rollout

## 1. 阶段定位

不可抢占通信一旦启动便无法纠正，因此前瞻可能比可抢占场景更有价值；同时，一个候选至少要模拟到完整通信结束，单次评估成本也更高。本阶段研究只在真正困难的启动决策点调用 rollout，并把节省的预算用于更宽候选或更深事件层数。

## 2. 基础定义

默认 completion policy 为 residual Longest Tail。对每个合法首动作，必须调用同一个不可抢占模拟器执行完整通信或启动集合，再按统一策略补全。不得用“执行一个 tick”近似不可抢占动作。

单 channel 候选包括 `FLOW(i)` 和合法 WAIT；多资源候选包括启动集合以及 optional-idle 下的 WAIT/非极大集合。active communication 不是可替换候选。

## 3. 触发信号

- Longest Tail 前两名差距小；
- FIFO、Longest Tail、短通信和资源热点策略分歧；
- 候选 duration 或资源脚印差异大；
- 候选执行期间预计有关键 compute、job arrival 或 barrier 事件；
- 候选会连续占用热点资源；
- WAIT 与立即启动的估计值接近；
- 候选完成后释放的 compute/join/barrier 差异大；
- multi-job 中存在 starvation 或目标冲突。

不得沿用“暂停当前通信是否有利”等可抢占专属信号。

## 4. 预算与安全回退

预算至少包含：

- 每决策候选上限；
- rollout 深度或事件层数；
- completion call 上限；
- 展开状态上限；
- 每决策和每实例 wall-clock；
- 峰值内存或缓存上限。

任何预算到达后立即回退到冻结的基础动作。fallback 结果仍需合法回放，并记录原因、发生状态和已消耗预算。

## 5. 对照实验

在相同总预算下比较：

- 无 rollout 的 Longest Tail；
- 全量 rollout；
- selective rollout；
- 周期触发；
- 随机触发；
- 相同调用次数下更宽与更深的配置；
- optional-idle 和 work-conserving；
- 小图 Exact 首动作。

阈值只在开发集确定，然后在未参与调参的 workload/topology holdout 上冻结。

## 6. 标签与指标

Exact 完成的小图记录最优首动作集合、各首动作最优后续值和触发器的命中/误触发/漏触发。大图只能用统一 completion policy 做条件反事实，不能称为最优标签。

报告 makespan、Exact gap、调用率、候选数、展开状态、completion calls、wall-clock、缓存命中、fallback、最坏退化，以及单位额外成本带来的收益。分别统计 rollout 修复基础动作和破坏基础动作的次数。

## 7. 退出条件

1. 所有 rollout 复用不可抢占公共状态转移；
2. WAIT、完整通信和多资源启动集合的首动作语义正确；
3. 触发信号、候选生成和 completion policy 可分别消融；
4. 与全量、随机、周期和无 rollout 在相同预算下比较；
5. 小图使用 Exact 标签，大图明确为条件观察；
6. 在冻结 holdout 上报告净收益、最坏退化和完整率；
7. 更宽/更深搜索确实使用了节省的预算；
8. 若收益只存在于旧小图或成本不值得，降级为分析工具或形成否定结论。
