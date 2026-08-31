# Stage 4e：不可抢占 Barrier 感知调度

## 1. 阶段定位

Barrier 信息只作为 residual Longest Tail 的筛选、有限修正、平局规则或 rollout 触发信号，不作为替代 Longest Tail 的独立主策略。不可抢占下尤其需要检查：为了提前局部 barrier 启动的通信，是否因连续占用而阻塞更关键工作。

## 2. Barrier 定义

Barrier 必须由当前 DAG 和 residual state 定义，包括多前驱 join、collective completion、optimizer join 和 pipeline 汇合。需要区分：

- 未完成前驱及其 remaining work；
- last-missing communication；
- 各分支预计到达时间与 slack；
- barrier 下游 residual tail；
- barrier 是否位于最终关键链；
- 候选完成是否立即减少真实缺口。

共享下游按并集计数。来源 role 可辅助解释，不能替代依赖结构。

## 3. 不可抢占修正

评价候选时额外考虑：

- 完整 duration；
- 执行期间无法响应的新 barrier 缺口；
- 对热点资源的连续占用；
- WAIT 后可能出现的更关键 last-missing；
- 多资源 active reservation；
- 提前当前 barrier 与延迟后续 barrier 的权衡。

所有 remaining、slack 和占用量来自当前状态；原始 duration 不能冒充剩余状态。

## 4. 候选方法

- barrier-only：仅作诊断和反例基线；
- Longest Tail + last-missing tie-break；
- Longest Tail + 有界 barrier 修正；
- Longest Tail 前的安全初筛；
- barrier challenger 与基础动作的一步完整通信反事实；
- barrier 触发 selective rollout；
- 多资源整集合 barrier 评分。

若使用权重，必须说明归一化、调参集、敏感性和 holdout；优先使用词典序或有界规则。

## 5. 实验与消融

先在 R2--R4 benchmark 和受控反例验证机制，再在 100--1000 节点随机、攻击和 real-derived slice 上冻结验证，最后只在少量 4a 中大图检查成本。

至少比较 FIFO、固定顺序、Longest Tail、barrier-only、三类 Longest Tail 加强、相同调用率的随机/周期 rollout，以及小图 Exact。

消融包括 last-missing、立即 compute 释放、下游 tail、slack、完整 duration、热点占用、WAIT、共享下游去重、单通信与整集合评分。

## 6. 指标与反例

报告 barrier ready/complete 时间、makespan、Exact gap、LT 修复/破坏次数、信号出现与实际分歧数、主动 WAIT、forced idle、资源利用率、wall-clock 和最坏退化。

必须覆盖：局部 barrier 非最终瓶颈、last-missing 后仍有长尾、短通信阻塞长关键通信、多个候选共享下游、错误到达估计、当前 barrier 提前但后续 barrier 延迟、多资源高分候选互相冲突。

## 7. 退出条件

1. barrier、last-missing、slack 和层级不依赖不稳定命名；
2. 精确量与启发式估计明确区分；
3. 单 channel 与多资源动作均符合不可抢占模拟器；
4. 小图验证局部 barrier 与最终 makespan 的关系；
5. 完成统一基线、消融、反例和成本报告；
6. optional-idle 与 work-conserving 分组；
7. barrier 触发与 rollout 本身的收益分开；
8. 在冻结验证集报告净收益、完整率和最坏退化；
9. 若只能降低成本或仅适合 tie-break，明确受限结论；
10. 无稳定收益时不进入后续综合算法。
