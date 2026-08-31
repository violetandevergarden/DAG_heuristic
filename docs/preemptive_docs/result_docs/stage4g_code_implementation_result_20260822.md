# Stage 4g 综合算法代码实现结果

日期：2026-08-22

## 1. 完成结论

已完成 `stage4g_integrated_algorithm_implementation_plan_20260822.md` 中可进入正式代码路径的任务，并形成公开算法 `integrated_v0`。该算法不是把 Stage 4c--4f 的实验模块全部打开，而是严格执行计划中的“最小有证据组合”：

- 单通道使用当前状态的 residual Longest Tail；
- 固定多资源使用 residual Longest Tail 排序后构造合法的极大兼容集合；
- barrier 只保留诊断合同，不参与选择；
- 完整 rollout、中高成本 packing 和 multi-job 规则未通过准入，不进入正式路径；
- 任何实验配置、预算不足或不可恢复为完整比较的情况都不能覆盖 LT 基础动作。

最终代码复用公共可抢占模拟器，没有实现第二套时间推进、依赖释放、抢占或资源占用逻辑。

## 2. 新增代码

新增 `src/llm_structured/integrated/`：

| 文件 | 作用 |
| --- | --- |
| `config.py` | 不可变、版本化配置；区分单通道/固定多资源、正式/实验模式和预算 |
| `policy.py` | 单通道与多资源综合入口，只负责选择合法动作并调用公共模拟器 |
| `decision.py` | 记录状态指纹、eligible、LT 基础动作、候选、最终动作、成本和 fallback |
| `accounting.py` | 综合层共享预算；操作、completion 和 expansion 均先预留后执行 |
| `safeguards.py` | 稳定状态指纹和多资源 inclusion-maximal 合法性检查 |
| `__init__.py` | 只导出冻结配置、结果合同和两个正式调度入口 |

新增统一实验入口：

- `experiments/llm_structure/stage4g_integrated_evaluation.py`
- schema：`stage4g-integrated-v1`
- 输出：[stage4g_integrated_evaluation_20260822.json](/D:/Code/SimAI/DAG_heuristic/docs/result_docs/stage4g_integrated_evaluation_20260822.json)

runner 对冻结图使用独立子进程硬墙钟；超时或错误时保留 `makespan=null`，不会以 LT 结果填充候选算法。机器可读结果保存输入 hash、环境、完整配置、状态、makespan、wall-clock、峰值内存、抢占、forced idle、利用率、Trace hash、Trace 验证、Exact 状态/gap 和组件审计。

## 3. 配置合同

首批配置已经固定：

| 配置 | 状态 | 定义 |
| --- | --- | --- |
| `integrated_v0` | 正式、已注册 | 单通道 LT；多资源 LT 贪心极大集合；搜索关闭 |
| `integrated_safe_large` | 正式安全配置 | 同一动作语义，关闭详细审计和 barrier 诊断 |
| `integrated_p_exp` | 实验配置 | 有界 packing 候选，仅能由实验层调用 |
| `integrated_r_exp` | 实验配置 | 截断估值参数合同，不是已准入调度器 |

非法组合会直接拒绝，例如单通道启用 packing、把 barrier 设为独立策略、搜索关闭但暗中保留 expansion 工作量、截断搜索缺少正候选数或估值步数。

公开 `policy.py` 明确拒绝实验组件。这样不会发生“配置名是正式算法，但内部悄悄运行未验证搜索”的情况。

## 4. 算法等价性修复

首次冻结实验暴露了一个实现错误：综合层曾按“包含当前通信自身剩余量的 tail”排序，而现有 Longest Tail 定义排除当前通信自身工作量。该错误在一个定向样例上碰巧不改变结果，却在其他图上改变了动作。

修复后的单通道分数为：

```text
exclusive_tail(c) = residual_tail_including_self(c) - remaining_comm_work(c)
key(c) = (-exclusive_tail(c), 0, task_id(c))
```

新增三个能稳定暴露该差异的回归样例。最终验收为：

- 74 个单通道开发样例：`integrated_v0` 与 LT 的 makespan 和 Trace hash 全部相同；
- 22 个固定多资源开发样例：全部相同；
- 100、300、600、1000 节点冻结图：全部相同；
- 1500 节点成本图：全部相同。

## 5. 多资源合法性

多资源入口在每个稳定决策状态：

1. 调用已有 `score_tasks(..., "longest_tail")`；
2. 调用已有 `greedy_fill_from_task_scores`；
3. 使用 `validate_maximal_action` 再检查非空、eligible、资源兼容和 inclusion-maximal；
4. 将完整集合交给公共 `PreemptiveMultiResourceModel.step`。

算法不会先选一个通信再静默补全，也不会返回非极大集合或主动空闲。

## 6. 审计与安全降级

详细审计记录包含当前时间、状态指纹、eligible IDs、LT 分数、基础动作、候选集合、最终动作、组件修改来源、fallback、completion/expansion 和分项成本。

当前正式版本的组件调用统计为：

- 单通道 packing：0；
- rollout：0；
- barrier 选择调用：0；
- 多资源 packing：每个真实调度决策一次 LT 极大集合构造；
- fallback：正常路径为 0。

当任务数超过冻结阈值 1000 时，算法一次性切换为安全模式：保留完全相同的 LT 动作，只关闭详细逐决策审计；之后不周期性重试实验组件。1500 节点图验证了降级后的 Trace 仍与 LT 相同。

## 7. 清单与输入隔离

runner 生成并校验以下固定清单：

- `experiments/llm_structure/manifests/stage4g_development.jsonl`
- `experiments/llm_structure/manifests/stage4g_validation.jsonl`
- `experiments/llm_structure/manifests/stage4g_cost.jsonl`
- `experiments/llm_structure/manifests/stage4g_components.json`

开发清单保存 benchmark 路径与文件 SHA-256；生成验证图保存固定生成器、节点数、seed 和由完整任务定义计算的 SHA-256。算法代码不导入 `experiments`、`benchmark_generate`、reference result 或 benchmark metadata。

组件准入状态为：`lt=admitted`、`packing_advanced=experimental/excluded_default`、`rollout_completion=excluded_online`、`truncated_rollout=experimental_not_admitted`、`barrier=diagnostics_only`、`job_aware=deferred`。

## 8. 测试结果

- integrated 专项测试：9 项全部通过；
- 完整测试：202 项全部通过，耗时 128.38 秒；
- 本次修改范围 Ruff：全部通过；
- `git diff --check`：无补丁格式错误，只有 Windows 换行格式提示；
- 全仓库 Ruff 仍有 86 个历史告警，分布在本次未修改的旧模块和测试中，没有作为 Stage 4g 顺手重构。

专项测试覆盖配置拒绝、共享预算原子预留、单/多资源 LT Trace 等价、exclusive-tail 回归、多资源极大集合以及大图安全降级不改变 Trace。

## 9. 公开入口

`integrated_v0` 已加入：

- 单通道 preemptive interface；
- 固定多资源 preemptive interface；
- `src/registry.py` 的可抢占 general-DAG 注册表。

实验配置没有进入 registry。调用公开名称得到的是冻结在线策略，不是离线跑多份完整日程后选择最小 makespan。

算法定义、实验和最终适用范围见 [Stage 4g 算法研究结果](/D:/Code/SimAI/DAG_heuristic/docs/result_docs/stage4g_algorithm_research_result_20260822.md)。
