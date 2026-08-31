# Stage 4h 局部关键前沿搜索代码实现结果

日期：2026-08-22

## 1. 结论

Stage 4h 已完成单通道局部关键前沿的可运行实现、专项测试、批量实验入口和安全回退。实现严格复用公共可抢占模拟器，没有自行推进时间、释放依赖或处理抢占。

代码层面可以作为诊断工具和后续研究基础使用，但本轮冻结实验没有满足正式算法准入条件，因此没有注册 `integrated_v1`，也没有把实验性动作替换加入公开 registry。固定多资源推广按照计划的 M6 前置条件停止：单通道估值和冻结收益尚未通过，继续实现多资源版本没有证据基础。

## 2. 新增代码

新增 `src/llm_structured/local_frontier/`：

- `config.py`：版本化的 tiny、small、medium 和诊断预算；
- `accounting.py`：在执行前原子预留展开和模拟步预算；
- `candidates.py`：确定性的 LT 与第二名候选，初版固定宽度为 2；
- `region.py`：执行两个合法首动作后提取差异，沿依赖向后扩展，并在最近共同汇合边界停止；
- `frontier.py`：只用完整归一化公共状态判断真正汇合；
- `evaluator.py`：使用公共 `PreemptiveDAGModel.step` 做有界前瞻，报告已推进时间、安全剩余下界、代理值、不确定性和停止原因；
- `audit.py`：逐决策记录触发、区域、建议、最终动作和回退原因；
- `policy.py`：诊断模式始终保持 LT；实验性受控模式只在两侧完整评价且代理改善达到门槛时改变动作；
- `__init__.py`：稳定导出研究接口。

新增离线实验入口：

- `experiments/llm_structure/stage4h_local_frontier_evaluation.py`；
- `experiments/llm_structure/manifests/stage4h_development.jsonl`；
- `experiments/llm_structure/manifests/stage4h_calibration.jsonl`；
- `experiments/llm_structure/manifests/stage4h_validation.jsonl`。

清单按输入文件哈希固定拆分，同源文件不会在一次运行中被自动替换。每行保存路径、输入哈希、类别、任务数和资源模式；文件缺失或哈希变化时实验直接失败。

## 3. 算法与模拟器边界

每次存在至少两个 eligible communication 时：

1. 用当前剩余状态的 exclusive residual tail 选出 LT；
2. 用同一排序的第二名作为唯一 challenger；
3. 分别通过公共模拟器执行两个首动作；
4. 比较 resulting state 中任务状态和剩余工作，只从实际差异向下游扩展；
5. 到最近共同汇合节点停止，不把汇合后的共同后缀重复纳入；
6. 在局部范围内继续调用公共 `step`，forced idle 只调用模拟器提供的兼容 WAIT 动作；
7. 任一分支区域不完整、前瞻不完整、预算不足或超出规模范围，最终动作回退 LT；
8. 诊断模式即使建议 challenger，也不改变 LT。

没有读取 benchmark metadata、reference result、样例名称或实验目录来做决策。Exact 只在离线 runner 中生成小图标签，不进入 `src/` 策略。

## 4. 安全行为

已实现并验证：

- 没有候选、单一 eligible、区域为空或截断时回退；
- 任一候选未完成评价时回退；
- 决策时间、总时间、展开次数和全图规模限制；
- 1000 节点以内执行研究配置，1500 节点自动一次性关闭局部搜索；
- 只在归一化公共状态完全相同的情况下标记汇合；
- 区域候选交换保持节点集合对称；
- 诊断模式与 LT trace 完全一致；
- 实验性模式在固定 8 节点反例上把 makespan 从 9 修复到 Exact 最优的 8；
- 所有输出 trace 经独立 `assert_preemptive_trace` 回放验证。

## 5. 测试

专项测试覆盖：

- 诊断模式与 LT trace 一致；
- 深度足够时修复固定 LT 反例；
- 单侧不完整和零预算安全回退；
- 区域对称、节点上限和显式截断；
- 最近共同 join 截止，共同后缀不重复计数；
- 到达同类节点但剩余状态不同不得错误合并；
- 单候选和大图自动关闭；
- trace 合法性。

验证结果：

- Stage 4h 专项：8 passed；
- 公共模拟器与 trace 联合回归：21 passed（修正前执行）；
- 全仓库：210 passed in 129.26s；
- Stage 4h 源码、测试和实验入口 Ruff：通过。

## 6. 未进入正式接口的原因

冻结验证 18 图为 0 胜、18 平、0 负，总 makespan 改善为 0；区域占剩余 DAG 比例的 p95 为 1.0。虽然开发集 medium 配置出现收益，但该收益没有在冻结集复现，且 Exact 根选择估值准确率仍只有 80%。根据计划的准入门槛和停止条件，不能发布 `integrated_v1`。

这不是代码未完成或模拟器缺口。它是当前“最近汇合局部区域 + 下界代理估值”定义未通过算法准入。实现保留为诊断资产，正式调度继续使用 `integrated_v0` / Longest Tail。

## 7. 产物

- 机器可读实验结果：`docs/result_docs/stage4h_local_frontier_evaluation_20260822.json`；
- 算法研究结论：`docs/result_docs/stage4h_algorithm_research_result_20260822.md`。
