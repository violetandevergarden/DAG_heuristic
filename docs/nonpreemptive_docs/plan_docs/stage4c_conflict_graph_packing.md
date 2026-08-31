# Stage 4c：不可抢占固定多资源冲突图与启动集合

## 1. 阶段定位

本阶段延续不可抢占 R4，研究固定多资源系统在任务完成事件处应启动哪些通信。它与可抢占 packing 的根本区别是：已经运行的通信必须保留到完成，不能在事件处被候选集合替换。

## 2. 动作定义

状态分为：

- `active`：已经启动、正在连续运行并占有完整资源集合的 communication；
- `eligible`：依赖已满足但尚未启动的 communication；
- `free resources`：未被 active communication 占用的资源。

合法动作只能从 eligible 中选择一个集合，使其内部资源互不冲突，且不与 active reservation 冲突。启动后集合中每个通信都运行到完成。

- optional-idle：允许不启动或只启动非极大集合，但 WAIT 必须通向真实未来事件。
- work-conserving：在当前空闲资源上启动集合必须 inclusion-maximal。

两种动作空间分别生成候选、Exact 和结果，不能用同一“极大集合”结论概括。

## 3. 冲突图

候选通信为顶点，共享任一固定资源则连边；与 active reservation 冲突的候选预先删除或显式标记。冲突图只表示当前启动兼容性，不表示启动该集合后的长期质量。

候选构造包括：

- FIFO、固定顺序和 residual Longest Tail 贪心；
- 资源热点、完整 duration 和下游释放修正；
- 多起点贪心；
- 有界一换一、一换二；
- 小图全合法集合或全极大集合枚举；
- optional-idle 下的空集、非极大 challenger；
- 固定候选数、状态数和 wall-clock 预算。

## 4. 评价重点

- 大资源长通信阻塞多个关键短通信；
- 多个小通信覆盖不同关键分支；
- 当前可填满资源但即将阻塞更关键 arrival；
- optional idle 是否值得保留空闲资源；
- active reservation 造成的候选图变化；
- 逐通信分数相加导致共享下游重复计分；
- 候选构造成本超过 makespan 收益。

整集合评分应使用下游并集、资源并集和真实启动后状态，不能简单累加局部分数。

## 5. 实验分层

1. R4 手算图、random 和 adversarial：验证合法性、Exact 和反例。
2. 100--1000 节点随机、攻击和 real-derived slice：主质量与消融实验。
3. 4a 中预先固定的少量中大图：成本、完整率和 fallback 检查。

正式基线至少包括 FIFO 补全、固定顺序补全、Longest Tail 补全、随机多起点、候选方法，以及小图 optional/work-conserving Exact。

## 6. 指标

报告 makespan、Exact gap、启动集合大小、候选集合数量、active 数量、资源利用率、主动/被动空闲、wall-clock、峰值内存、状态数、超时、fallback 和最坏退化。optional-idle 还需报告选择空集或非极大集合的次数及实际收益。

## 7. 验证与退出条件

必须通过独立 trace 检查：通信区间连续、资源排他、active 不被移除、依赖合法、同刻事件原子处理和最终完成。

Stage 4c 结束要求：

1. 动作合同明确区分 active、eligible 和 free resources；
2. optional-idle 与 work-conserving 的候选空间和 Exact 分开；
3. 构造器只选择动作，不自行推进时间；
4. R4 小图与未压缩或独立 Exact 对拍；
5. 完成分层基线、消融、反例和成本报告；
6. 真实或 real-derived 输入上报告动作分歧和完整率；
7. 所有预算是可验证的硬边界；
8. 若简单 Longest Tail packing 已足够，形成受限或否定结论。
