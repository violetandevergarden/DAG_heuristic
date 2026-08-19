# Stage 4d：Selective Rollout 研究

## 1. 阶段定位与问题定义

Rollout 可以提前看到一个通信选择对后续事件的影响，但全量 rollout 在真实 DAG 上可能太慢。本阶段研究如何找出真正值得前瞻的决策点，用较少调用保持收益，并利用节省预算尝试更宽或更深搜索。

在状态 $s$ 中，若有多个合法通信，基线 rollout 对每个候选执行公共 transition，再使用固定 Longest Tail completion 推进到完成或预算耗尽。只有搜索完整且严格改善基线才采用候选，否则回退基线。Selective rollout 增加触发器，未触发时直接执行 Longest Tail。

## 2. 关键节点假设

分别检验：Longest Tail 前两名差距小；候选会立即释放 compute、join 或 barrier 前驱；候选资源冲突强且释放路径资源热点不同；不同简单策略给出不同首动作；当前通信剩余工作较大且暂停会改变竞争窗口。每个信号记录命中率、误触发率、漏触发率和实际 makespan 收益。

## 3. 探索过程

先在小图和受控真实图运行全量 rollout，保存每个选择点的候选、基线动作、最好首动作、收益差、是否需要抢占、展开状态数和耗时。未完成标签只能记为未知。

随后先测试单一阈值，再测试少量有明确含义的组合。阈值只在 validation 选择，在 holdout 固定。无候选、特征异常、超时或状态上限都回退 Longest Tail；筛选器不能自行推进时间。

在相同墙钟和调用预算下比较 top-2/depth-1、top-4/depth-1、top-2/depth-2、top-4/depth-2。forced idle 不消耗搜索深度。必须分清收益来自触发器还是增加搜索预算，并构造低 margin 但不应 rollout、barrier 临近但不值得抢占、短期释放不改变最终尾部、以及必须跨两个事件才能体现收益的反例。

## 4. 实验与退出条件

主实验使用 4a 真实竞争 DAG，按 workload、topology、DP、job 数和规模分组。对照包括 FIFO、Longest Tail、全量 rollout、Selective rollout 和相同预算的随机/周期触发。报告 makespan、调用率、展开状态数、运行时间、完整率、抢占、forced-idle 和最坏退化。

只有真实 DAG、受控冲突集和 holdout 都支持成本下降且没有不可接受最坏退化，才进入综合阶段；否则明确降级为小图工具或否定该方向。

