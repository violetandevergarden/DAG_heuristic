# Stage 4g：综合算法与总体实验研究

## 1. 阶段定位

综合阶段根据 4a–4f 的实验结果形成一套可执行、可解释、成本可控的总体算法。目标不是把所有组件都接入，而是保留确实解决已知失败模式的组件，并给出完整的正面和负面结论。

## 2. 综合算法定义

默认动作是 Longest Tail：在当前合法通信中计算 residual downstream tail，选择最高者；多资源时以该通信为种子，按 4c 规则补成极大兼容集合。综合流程可以依次加入 barrier 筛选、冲突图 packing、selective rollout 和 multi-job job-aware 规则。每个组件只能读取公共 simulator residual state，不能维护第二套状态。

## 3. 研究过程

依次比较 FIFO、Longest Tail、加 packing、加 barrier、加 selective rollout、multi-job 专用策略和最终组合。每次只增加一个组件，固定输入、seed、tie-break、时间预算和超时规则，区分收益来自排序、集合构造还是额外搜索。

小图报告 optimal makespan、首动作命中率、gap、状态数和运行时间。大图没有 Exact 时统一比较 FIFO、基础 Longest Tail 和候选算法，报告完成时间、相对改善、运行/内存、rollout 调用、利用率、抢占、forced-idle、超时和未完成状态。阈值和权重在 validation 固定，在未参与设计的 workload/topology holdout 上检验。

## 4. 理论解释与退出条件

说明 packing 是否减少资源碎片，barrier 是否减少无关候选，selective rollout 是否只在高不确定性状态增加计算，以及 job-aware 规则是否改善声明的目标。检查组件相互抵消、成本超过收益、某类 topology 系统性退化和复杂算法退化为基础 Longest Tail 的情况。经验最优率不能写成理论近似比。

Stage 4g 结束必须有完整算法定义、逐组件消融、真实 holdout、Exact 小图对照、FIFO/Longest Tail 大图对照、最坏案例、运行和内存成本、超时报告、适用边界和否定结论。不能以代码完成或单个 benchmark 胜出作为退出依据。
