# 可抢占 DAG heuristic 研究总结

## 本轮做了什么

按照旧可抢占规划重新实现并实验，但使用当前明确的 v2 语义和事件驱动状态机，不沿用旧脚本或旧数字。研究推进到：

```text
模型与 Exact Oracle
  -> 单通道并行链
  -> 单通道一般 DAG
  -> 固定多资源拓扑
  -> LLM 特殊结构研究方案（暂不实现）
```

代码包括单/多资源状态机、Exact Oracle、priority、Rollout、Beam、Monte Carlo、benchmark 生成器、reference results 和统一实验 runner。原始机器可读结果位于 `docs/preemptive实验结果.json`。

## 最重要的结论

1. **理想比例带宽分配可以用极化可抢占调度研究。** 在线性、零开销、可保存进度的假设下，只需在任务事件处把全部带宽交给一个 flow；无事件区间内无需任意切换。
2. **主动 WAIT 在当前可抢占模型中被支配。** 有 eligible 通信时可以先推进它，到下一事件再决定；这与不可抢占模型中“等待短关键流、避免启动长流”的逻辑不同。
3. **单通道任意 work-conserving 策略有 2-近似安全界，且对任意 priority 类基本紧。** 但这不证明 Longest-tail 自身的 tight ratio 为 2。
4. **Longest-tail 是合适的廉价基线，但不是 exact。** 48 个精确单通道图上 mean ratio=1.01581、observed max=1.21212、最优率=83.33%。
5. **Event Rollout-2 很有价值。** 当前 48 个精确图全部命中最优，修复全部 8 个 Longest-tail hard instances，平均原型耗时约 10.47 ms。但有限样本 100% 不是理论保证。
6. **Beam 和 Monte Carlo 当前没有显示超过 Rollout-2 的解质量。** 它们同样全部最优，但平均开销约 74--194 ms 和 82 ms，暂时更适合作为离线 teacher。
7. **Join 候选没有独立效果。** Hybrid Join-Rollout 与普通 Rollout 在全部图上完全相同。应研究 optimizer latest-start 和 join 后关键尾，而不是 raw bonus。
8. **多资源必须调度兼容集合。** 14 个精确图上 Longest-tail pack mean ratio=1.00661，Set Rollout-2=1.00265；纯 Bottleneck 策略明显更差。
9. **多资源不能继承单通道 2-bound。** 正确下界转为 `max(critical path, max resource load)`；进一步理论需要利用 route/conflict graph 的结构。
10. **LLM 特化暂不实现是合理的。** 先审计真实 collective 的抢占粒度、同步和代价，否则理想 fluid 收益无法映射到 NCCL/RDMA。

## 当前推荐算法层级

```text
即时决策：Residual Longest-tail
约 10 ms 小图预算：Event Rollout-2
离线 teacher：Beam-8/32 或 Monte Carlo-64
小窗口 ground truth：Exact Oracle
多资源：Longest-tail compatible pack + Set Rollout-2
```

## 结果适用边界

- duration 为整数；
- communication 可保留进度并零代价恢复；
- compute 不可抢占；
- 单通道总服务率恒为 1；
- 多资源每条通信占固定排他资源集合；
- 不包含异构带宽、连续 max-min sharing、collective rank 同步、最小 chunk 和迁移；
- 只有 48 个单通道与 14 个多资源精确小图，不能据此声明 Rollout/Beam 为 exact 或具有小于 2 的一般近似比。

## 下一步

先不要继续堆通用 priority。更值得做的是：

1. 为 Exact Oracle 加对称状态压缩，解决当前 2 个超时图；
2. 自动搜索 Rollout-2、Beam-8/32 的反例，厘清它们相对 Longest-tail 的理论下界；
3. 加入切换开销、最小 chunk 和抢占次数限制，画收益衰减曲线；
4. 审计 NCCL/RDMA/SimAI 中 collective 的真实抢占单位；
5. 再按照 `preemptive阶段5_LLM结构规划.md` 开展真实 LLM 特化。

## 参考文献与关系说明

1. L. Schrage, “Solving Resource-Constrained Network Problems by Implicit Enumeration,” *Operations Research*, 18(2), 1970, pp. 263–278。经典 preemptive Schrage 思想与本研究“新任务释放后按 tail 重选”的基础子问题相邻，但本文多轮 DAG release 由先前通信决策内生决定，不能直接宣称整个 DAG 被 Schrage 精确求解。
2. J. R. Jackson, “Scheduling a Production Line to Minimize Maximum Tardiness,” Management Science Research Project, UCLA, 1955。单 flow、共同 release 的 non-increasing delivery-tail 规则对应本文 restricted result 的交换论证。
3. P. Brucker, *Scheduling Algorithms*, Springer。用于单机 release/delivery-tail、抢占与 list scheduling 的标准记号和复杂性背景。
4. A. Munier and C. Potts 等关于 precedence delays/coupled tasks 的研究说明链间 delay 问题即使外形简单也可能困难；这些模型常含不可抢占或 exact delay，与本文零代价可抢占 fluid 模型不同，因此只作复杂性背景，不直接移植近似界。

本文的事件点充分性、work-conserving 2-bound、WAIT 支配性和多资源 maximal-set 支配性均已在对应阶段文档中给出针对当前模型的自包含论证，不依赖把相邻论文结论直接套用。
