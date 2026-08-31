# Stage 4c 修正、短时验证与结论（2026-08-21）

## 完成范围

本次完成了 `stage4c_code_review_correction_plan_20260821.md` 的实现、回归、受控小图真值、Stage 4a 输入分层、短时真实图 census 和统一对照入口。结果 JSON 使用 `stage4c-packing-v2`；旧 `stage4f-packing-v1` 没有覆盖或引用为新结论。

代码版本：`e3353b1ee6b6c5d22a1f4cdf40a8163584bb63d2`（工作区含本次未提交修改）。

## 修正结果

- `PackingResult` 现在分别保存 LT `baseline`、额外 `candidates`、实际 `selected`、构造器、选择器、版本、截断和回退原因；非 rollout 的 `set_score` 可以实际执行非基线集合。
- `enumerate_bounded` 改为流式回溯。每个访问节点先消耗构造额度，不再调用全量 `maximal_actions()` 后切片；`max_sets=0` 不生成额外集合，LT 基线不占候选名额。
- 每个决策共享 `DecisionBudget`。构造操作、保留候选、完整完成评估与单决策截止时间统一记账；完成评估先预留调用额度。结果同时记录总调用数和每决策最大调用数，后者在本次所有受控运行中均不超过 `b_eval=2`。
- 调度器显式使用 `baseline`、`set_score` 或 `depth1_completion` 选择器，统计实际触发次数、生成/评估数以及逐原因回退计数。新增固定顺序、FIFO、固定种子随机补全基线。
- 实验入口改为 Stage 4c，并以 `python -m experiments.llm_structure.packing_evaluation` 运行；真实完整回放由父进程实施墙钟超时，超时不使用 fallback makespan 冒充完成结果。

## 小图真值与反例

保留原有六个 motif，并补充同冲突图不同下游、共享下游、热点不在最终关键路径、频繁抢占无收益四类反例。10 个 motif 的所有极大首动作均以未压缩 Exact 后续求值，全部完成。

| 观察 | 数量/结果 |
| --- | --- |
| 受控 motif | 10 |
| 全部首动作 Exact 完成 | 10/10 |
| LT 非最优 | `path_future_value`、`exchange_repairs_lt`（16 对 14） |
| 深度一完成评估修复 | 上述两例（14） |
| `set_score` 退化 | `star_wide_vs_pair` 10→12；`hyperedge_hotspot` 8→10；反向路径 18→21 |
| 无净收益的反例 | 团、空图、共享下游、热点、抢占 motif |

这证明候选覆盖、集合评分和完整评估必须分开报告：当前简单 `set_score` 没有稳定收益；带额外完成评估只在两个开发 motif 有局部收益，不能归因于纯 packing，也不能推广到真实 LLM DAG。

## 真实图分层与短时实验

从 Stage 4a 活动 manifest 只读派生两个输入：转换状态均为 `valid`、固定资源映射明确、`informative-observed` sampled-prefix 证据、2184 个任务、Cassini 24g、TP=4/PP=4/DP=1。前者为开发、后者为 workload holdout。它们不是全图竞争认证样例。

- 两图均做了 8 个 LT 前缀决策的低成本 census；观察到的冲突边均为 0，首状态极大集合下界为 1。
- 将完整回放预算放宽到 20 秒后，固定顺序、FIFO、LT、随机、`multi_seed:set_score`、`multi_seed:depth1_completion` 共 12 次真实单 job 回放中仍有 11 次超时；唯一完成的随机回放不作为质量结论。所有超时行保留在结果中，未完成行 `makespan=null`。
- 另对 160 任务、`certified_choice_exists` 的 AICB multi-job control 完成了六种算法的统一对照：LT/集合评分/深度一均为 108672，FIFO/固定顺序/随机均为 108900；六条 trace 均通过验证。该 control 单独保存，不能外推为单 job 结论。

因此当前短时预算下没有合格的真实“集合可选且完整可回放”质量集。它不能支持真实端到端收益、最坏退化或 holdout 泛化结论；这是一项成本和准入的负面结果，而不是算法失败或成功的量化结论。

## 验证与产物

- 定向回归：`python -m pytest -q tests/muti_channel/preemptive tests/llm_structured/test_packing_features.py`，21 passed。
- 机器可读结果：[stage4c_packing_evaluation_20260821.json](/D:/Code/SimAI/DAG_heuristic/docs/result_docs/stage4c_packing_evaluation_20260821.json)
- 认证 control 对照：[stage4c_control_comparison_20260821.json](/D:/Code/SimAI/DAG_heuristic/docs/result_docs/stage4c_control_comparison_20260821.json)
- control 清单：[stage4c_control_manifest_20260821.jsonl](/D:/Code/SimAI/DAG_heuristic/docs/result_docs/stage4c_control_manifest_20260821.jsonl)
- 冻结的只读实验清单：[stage4c_manifest_20260821.jsonl](/D:/Code/SimAI/DAG_heuristic/docs/result_docs/stage4c_manifest_20260821.jsonl)

## 阶段判断

修正计划中的代码和验证任务已完成；Stage 4c 本身仍为“开发中”，不进入 Stage 4g。原因不是实现契约，而是 Stage 4a 允许的真实中图在本次严格短时预算内没有完成回放，且已观察前缀没有集合选择。后续只有找到经竞争证据分层、能在统一预算完成的真实集合可选样例，才能冻结参数并重新进行真实质量/holdout 比较；若仍长期缺少这类样例，应形成“LT 足够或真实集合选择稀少”的受限否定结论。
