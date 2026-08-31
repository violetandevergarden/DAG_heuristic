# Stage 4c 修正计划完整验证记录（2026-08-21）

本文件是本轮完整验证新建的记录，不覆盖任何既有过程文档或既有结果文件。

## 运行范围

- 小图：10 个受控 motif，固定顺序、FIFO、Longest Tail、固定种子随机、多起点集合评分、深度一完成评估，全部运行。
- 真实质量集：Stage 4a manifest 中两个 `informative-observed`、`sampled_prefix`、2184 任务的单 job 样例；第一个作为 development，第二个作为 workload/topology holdout。
- control：160 任务、`certified_choice_exists` 的 AICB multi-job 样例，独立报告，不混入单 job 聚合。
- 普通完整回放墙钟：180 秒/算法；深度一完成评估单独放宽到 600 秒/算法。
- 所有结果使用同一转换输入、公共多资源模拟器、统一 tie-break 和 `stage4c-packing-v2` 预算；超时行保留，未用 fallback makespan 冒充候选算法结果。

## 结果摘要

### 受控小图

10 个 motif 的全部极大首动作都完成未压缩 Exact 后续对拍。`path_future_value` 与 `exchange_repairs_lt` 中 LT 为 16、Exact 为 14；深度一完成评估得到 14。集合评分在 `star_wide_vs_pair`、`hyperedge_hotspot` 和反向路径中出现退化。该结果完成了候选覆盖、评分、反例和 Exact 交叉验证，但不代表真实图频率。

### 两张真实单 job 图

| 样例 | FIFO | 固定顺序 | LT | 随机 | 集合评分 | 深度一完成评估 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| gpt13b / Cassini 24g（development） | 452638 | 452638 | 452638 | 475486 | 452638 | 600 秒超时 |
| gpt7b / Cassini 24g（holdout） | 402495 | 402495 | 403678 | 411909 | 403678 | 600 秒超时 |

两张图的 FIFO、固定顺序、LT、随机和集合评分 trace 均有效。相对 FIFO，LT 和集合评分在 holdout 均退化约 0.29%，随机退化约 2.34%；development 中 LT/集合评分与 FIFO 持平，随机退化约 5.05%。因此没有观察到候选 packing 相对简单基线的稳定净收益。

深度一完成评估两张图均达到 600 秒进程级墙钟上限，未产生 makespan；这不是被提前停止，而是独立重复的硬超时证据。

### 认证 control

160 任务 control 的六种算法均完成且 trace 有效：

| 算法 | makespan | wall-clock |
| --- | ---: | ---: |
| FIFO | 108900 | 0.08 s |
| 固定顺序 | 108900 | 0.08 s |
| Longest Tail | 108672 | 0.08 s |
| 随机 | 108900 | 0.03 s |
| 多起点 + 集合评分 | 108672 | 0.21 s |
| 多起点 + 深度一完成评估 | 108672 | 11.41 s |

该 control 证明选择差异和候选执行链路有效，但它是 multi-job control，不能替代单 job 真实 holdout 结论。

## Stage 4a 分层 census

新冻结清单包含 manifest 中全部 40 个固定多资源样例：37 个 `cost_only`、2 个 `quality_candidate`、1 个 `control_only`；规模为 1 个 small、24 个 medium、15 个 large。37 个 cost-only 样例的 sampled-prefix 证据没有被升级为全图无竞争或全图唯一集合；它们仅用于成本/审计分层。

两个 quality candidate 的前 8 个决策冲突边总数均为 0，完整质量结果因此只支持“这些输入的当前审计前缀没有观察到可选集合”，不支持所有真实图无竞争。

## 修正计划逐项验收

| 项目 | 状态 | 证据 |
| --- | --- | --- |
| C1 候选与最终选择分离 | 完成 | `PackingResult` 保存 baseline/candidates/selected；非 baseline selector 有执行测试 |
| C2 流式有界枚举 | 完成 | 操作数和集合数硬上限测试；不再先全量枚举后切片 |
| C3 共享预算 | 完成 | `DecisionBudget`；`b_eval=0/1/2` 与每决策最大调用数测试 |
| C4 fallback、超时、结果字段 | 完成 | 进程级 timeout、逐原因统计、trace/hash/内存/资源利用率输出 |
| C5 小图 Exact 首动作真值 | 完成 | 10 个 motif 全部极大首动作未压缩 Exact 后续完成 |
| C6 Stage 4a manifest/census | 完成（证据分层） | 40 条冻结清单；quality/control/cost-only 明确分开 |
| C7 基线、构造、评分、holdout | 完成（负面结果） | 两张真实单 job + control 的统一算法对照；深度一独立 600 秒超时 |
| C8 适用范围和失败案例 | 完成 | 普通 packing 无稳定净收益；深度一成本不可接受；10 个反例已记录 |

## 退出判断

Stage 4c 的代码和实验修正任务已完成，但“高级构造器作为已验证组件进入 Stage 4g”的条件不满足：

1. 集合评分在真实 development/holdout 上没有稳定优于 FIFO/LT；
2. 深度一完成评估在两个真实单 job 样例上均无法在 600 秒内完成；
3. 真实质量样例目前只有两个，且前 8 个决策没有观察到冲突边；
4. 复杂 packing 的额外成本没有得到真实净收益补偿。

因此 Stage 4c 应以受限/否定结论收尾：Longest Tail 或 FIFO 已足以覆盖当前可完成的单 job 真实样例；集合评分可保留为审计工具，深度一完成评估不得作为 Stage 4g 默认组件。该判断不是“提前退出”，而是已完成计划要求的基线、消融、holdout、成本、反例和失败模式验证后的退出判断。

## 新建产物

- [完整 180 秒对照](/D:/Code/SimAI/DAG_heuristic/docs/result_docs/stage4c_full_validation_20260821.json)
- [深度一 600 秒扩展对照](/D:/Code/SimAI/DAG_heuristic/docs/result_docs/stage4c_depth1_extended_20260821.json)
- [全量冻结分层清单](/D:/Code/SimAI/DAG_heuristic/docs/result_docs/stage4c_frozen_manifest_20260821.jsonl)
- [认证 control 对照](/D:/Code/SimAI/DAG_heuristic/docs/result_docs/stage4c_control_comparison_20260821.json)

## 算法解释

采用“当前剩余 Longest Tail 排序 + 贪心补全极大兼容集合”（LT-packing）作为默认方法。

具体流程：

  1. 在当前状态计算每个 eligible communication 的 residual Longest Tail。
  2. 按 LT 降序排序，task ID 作为确定性 tie-break。
  3. 依次加入资源互不冲突的通信。
  4. 直到没有通信可以再加入，保证得到 work-conserving 的 inclusion-maximal 集合。
  5. 预算不足或异常时仍返回这个 LT 集合作为安全 fallback。