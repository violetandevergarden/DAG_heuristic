# Stage 4e 不可抢占 Barrier 感知调度代码实现结果

日期：2026-09-01

## 实现范围

新增 `src/llm_structured/nonpreemptive/barrier/`，与可抢占 barrier 代码隔离，并复用不可抢占公共模拟器和 Stage 4d 的只读 adapter：

- `contracts.py`：版本化配置、数量来源、特征、决策、预算和结果合同；
- `graph.py`：只按公开 DAG 依赖识别 direct join、最近 barrier 和 barrier 层级，不读取 task 名称或 metadata；
- `features.py`：计算 direct last-missing、公共 transition 前后立即释放、下游 barrier、后继并集、资源并集和 excluded ready；
- `counterfactual.py`：执行一个完整合法动作，再用同一 residual LT 完成；
- `policies.py`：B0 LT、B1 barrier-only 诊断、B2 LT 真并列修正、B3 冻结 10% margin、B5 一步完整动作反事实；
- `__init__.py`：稳定导出。

多资源动作始终来自公共 `legal_actions(mode)`，`step` 保留运行中通信和资源占用。整集合使用 descendants、barriers 和 resources 的并集，不使用成员分数求和。optional-idle 与 work-conserving 分开配置和统计。

新增统一实验入口 `experiments/llm_structure/nonpreemptive/stage4e_evaluate.py`。每个 case × mode × method 在独立进程中执行，外部硬超时不转换为 completed。配置和 manifest 位于 `experiments/llm_structure/nonpreemptive/manifests/stage4e/`。

## 测试

新增 `tests/llm_structured/nonpreemptive/barrier/test_stage4e_barrier.py`，覆盖：

- task 改名不改变结构 barrier；
- direct last-missing 与 transition-exact immediate release 分离；
- 单 channel 通信完整连续执行且 trace 可验证；
- 多资源集合按 union 计数并保持动作合法；
- 特征预算为零时回退 LT，不制造非法 WAIT 或 START。

专项测试为 5 passed，Ruff 检查通过。完整回归结果见最终交付说明。

## 实现边界

- B1 仅为负面对照，没有注册为推荐公共算法。
- B4 初筛保持 no-op：当前没有足够的支配证明可安全删除动作。
- B6 没有复制 Stage 4d rollout；本轮真实小图没有 barrier 修复空间，中图基础回放又全部超时，暂不增加 trigger 组合。
- B7 已实现并测试集合 union 和 active reservation 语义，但两个真实多资源中图位于更大的 2038-task 层；由于 640/838-task 单 channel pilot 已全部触发预算门槛，未启动它们。
- 当前后继集合使用稳定 Python set，并设访问预算；尚未引入位图优化。中图结果表明在进一步优化基础回放前，不应扩大复杂 barrier 方法。

