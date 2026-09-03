# Stage 4 SimAI 转换保真审计结果

日期：2026-09-02

## 静态批量审计

新增 `stage4_conversion_fidelity.py`，对分层 source 逐例使用独立进程和硬预算，并保存完整缺边/附加边，而不是只保留前 20 条。候选选择覆盖 936 条 catalog 中的 GA 1/4/8、PP 1/2/4、6 个模型、dense/MoE 和 Mixtral EP 1/2/4/8；首轮候选共 34 个，不做笛卡尔积。

本轮按每例 10 秒审计前 12 个：10 个 `matched`，2 个 `unknown_timeout`，没有 `conversion_bug`。原始结果在 `stage4_conversion_fidelity_20260902/`。已完成样例均满足：

- builder task 数与导出 task 数一致；
- 导出依赖恰好等于 raw dependency 与 serializer compute-order 的并集；
- 无无法解释的缺边或附加边；
- preemptive/nonpreemptive 的 task 和固定 resource 相等，差异限于语义合同。

代表性 GPT-13B 样例仍为 918 task、1282 raw edge、serializer 增加 364 edge、最终 1646 edge。

## 证据边界

| 项目 | 分类 | 结论 |
|---|---|---|
| 静态 task/dependency | `matched`（已完成 10 例） | 可映射回 SimAI builder 输入事实 |
| serializer compute-order | `explained_transform` | 合同内追加；不等同于已证明 native executor 时间线一致 |
| 单 channel duration | `explained_transform` | size / nominal exclusive bandwidth |
| routed duration | `explained_transform` | 固定 BFS route 最窄链路带宽；未加入固定 hop latency |
| NIC/resource | `explained_transform` | routed 投影把端点 NIC 与定向链路作为固定排他资源 |
| dynamic ready/start/finish | `not_supported` | 当前未驱动 SimAI executor 对拍 |
| native N-iteration | `not_supported` | 未用简单复制冒充原生多迭代 |
| native multi-job timeline | `not_supported` | 仅能验证项目组合器的 job 边界与 arrival 合同 |

因此当前准确结论仍是“静态任务图基本保真、执行性能模型为明确投影”，不是 SimAI 原生执行的无损快照。两个 10 秒超时保留为未知，未用更长预算替换同表结果。

