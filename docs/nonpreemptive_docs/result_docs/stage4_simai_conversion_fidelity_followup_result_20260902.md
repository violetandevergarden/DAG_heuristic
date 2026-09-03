# 不可抢占 Stage 4 SimAI 转换保真第二轮结果

日期：2026-09-02

## 结论

E3 已按“清单覆盖”和“实际执行状态”分开完成。显式清单含 13 个条目，声明覆盖 6 个模型、GA 1/4/8、PP 1/2/4、TP 1/2/8/16、Mixtral EP 1/2/4/8、单 channel 及 Alibaba/Cassini 两类拓扑；覆盖检查无缺项。实际 10 秒硬预算结果为：8 个 `matched`、3 个 `not_supported`、2 个 `unknown_timeout`、0 个 `conversion_bug`。

因此不能把“清单覆盖 EP 2/4/8”写成“EP 2/4/8 已成功转换”。这三个 Mixtral 条目被 SimAI `MegatronRankGrouper` 拒绝，原因是所选 source 的 DP=1 不能被 EP=2/4/8 整除；现有 catalog 中没有满足该约束的对应 source，本轮没有手写 rank group 或依赖边。

## 逐字段对拍

8 个完成样例均逐 task 核对 id、kind、src/dst、size、duration，以及 iteration、micro-batch、phase/layer 等规定元数据；逐 edge 核对 raw dependency、serializer compute-order 边及去重结果；routed 样例另核对固定 route/resource。差异文件不截断。完成样例没有 task 字段差异、未解释缺边或未解释附加边。

serializer 统计已修正为 attempted/new/duplicate-raw/effective 四类。例如 GPT-13B 918-task 样例有 1282 条 raw edge，serializer 尝试 556 条 compute-order 边，其中 364 条为新增、192 条与 raw edge 重复，最终为 1646 条 effective edge。

每条记录保存 source、topology、参数和输出 hash，以及 SimAI commit。两个超大模型在独立 10 秒子进程预算内终止并保留为 `unknown_timeout`，未以更长预算覆盖原状态。

## 简化边界

| 项目 | 状态 | 边界 |
|---|---|---|
| 静态 task/dependency/规定 metadata | `matched`（8 例） | 支持已完成样例 |
| serializer compute-order | `explained_transform` | 项目序列化追加，不等于 SimAI 原生时间线 |
| 单 channel duration | `explained_transform` | size / 名义独占带宽 |
| routed duration/resource | `explained_transform` | 固定 BFS route 的瓶颈带宽与固定排他资源；不含固定 hop latency |
| Mixtral EP 2/4/8 | `not_supported` | 当前 source 的 DP/EP 约束不成立 |
| dynamic ready/start/finish | `not_supported` | 未驱动 SimAI native executor |
| native N-iteration | `not_supported` | 未用静态复制冒充原生多迭代 |
| native multi-job timeline | `not_supported` | 只验证项目组合器合同 |

原始产物位于 `stage4_conversion_fidelity_v2_20260902/`。静态转换没有未处理 bug，但动态执行关系和上述 EP 配置仍不能作为已验证能力。
