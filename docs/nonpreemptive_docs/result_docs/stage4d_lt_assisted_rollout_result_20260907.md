# Stage 4d：以 LT 为主的有限前瞻修正实验结果

日期：2026-09-07  
状态：计划已执行；机制实验完成，正式推广因预算门槛和新来源缺口未准入

本报告对应 [执行计划](../process_docs/stage4d_lt_assisted_rollout_test_plan_20260906.md)，证据入口为 [结果目录](stage4d_lt_assisted_rollout_20260907/) 和 [机器汇总](stage4d_lt_assisted_rollout_20260907/summary.json)。所有输入都是不可抢占 Stage 4f 多 job 图，optional-idle 与 work-conserving 始终分开运行。

## 1. 结论

当前 D1 不能进入 Stage 4g 综合算法。

- M0 的补全硬截止问题已经修复：同一决策的默认动作和挑战动作共享绝对单调时钟截止，补全每个公共决策循环检查截止；超时为 unknown、不得缓存或胜出，并回退冻结 LT。外层仍使用可终止独立进程。
- 两个小型真实结构图上的 40 个“配置×图×模式”全部完成且 trace 合法。D1a、D1b 和深度 2 均未改善 LT；只有周期触发在 `micro_four_burst` 的 optional-idle 上把 makespan 从 589446 降至 588103，改善 1343（0.228%），其他三个“图×模式”持平。
- 该局部收益没有达到 1% 门槛，也只来自一个已暴露来源组。D1 配置的中位耗时约 3.51--3.63 秒，而 D0 为 0.61 秒，中位倍数约 5.8，超过 3 倍门槛。
- 大图正式门禁失败：在 90 秒外层硬预算下，`gpt13_two_hom_50pct` 的 D0 通用 rollout 路径在两种模式均超时。这说明当前框架连冻结 LT 的大图成本都不合格，不能继续解释 D1 的质量。
- 没有取得三个未参与设计的新独立来源组，所以 M4 按计划未运行。现有图全部标为 `design_exposed`，不宣称 holdout 收益。
- D2 WAIT 仍暂停：Stage 4b 的 576 个状态中可靠未来释放覆盖为零。两张 routed 图不运行单通信 D1，继续属于 4c 集合修正范围。

因此分层结论为：尚不能证明 D1 稳定修复 D0；不能证明超过简单强基线；当前额外成本不值得。代码保留为机制分析和后续性能优化对象，而不是正式候选算法。

## 2. 实现与语义

本轮只修改不可抢占公共运行时和 4d 模块：

- `runtime.complete` 接受绝对截止时间，并在每个完整动作前检查；通信仍由公共模拟器完整连续执行。
- 单 channel 候选支持两种冻结方式：`lt_top_two` 只比较 LT 前两名；`full_cross_job` 再按 shortest-remaining-job、FIFO、job-aware LT 的固定顺序补充跨 job 动作，总宽度不超过 3。
- tail 阈值为 0.05、0.15、0.20；`duration ratio >= 2` 仅作为消融。
- 深度 2 只经公共完整动作推进到下一决策事件，不按 tick 展开，不移除 active 通信。
- 实例内前瞻预算耗尽后，后续决策跳过候选和特征计算，直接执行 D0。这个修复避免反复支付已不可能产生选择的特征成本。
- 多资源的既有公共接口保持兼容，但本轮正式 manifest 不包含 routed 图，避免把单通信选择与 4c 集合动作混在一起。

新增回归覆盖绝对截止、候选宽度、LT 前两名模式、合法 WAIT、work-conserving 禁止主动等待、active reservation、打平回退 D0 和深度 2 公共事件推进。

## 3. 实验输入与预算

设计 manifest 有 7 个单 channel Stage 4f 图、4 个来源组；它们均已被 Stage 4b/4f 查看，只用于设计和成本诊断。正式小图机制矩阵选取同一真实切片组合而成的 4-job 与 8-job 图，共一个来源组、两种模式、10 个配置、40 次运行。

每个 D1 配置使用 3 秒实例内共享截止、0.5 秒单决策截止和最多 3 个候选；外层小图为 15 秒可终止进程。首轮 10 秒试跑的 140 项中只有 40 项完成、100 项超时，保存在 [pilot_10s_results.jsonl](stage4d_lt_assisted_rollout_20260907/pilot_10s_results.jsonl)，只作为预算诊断。随后对大图 D0 使用计划规定的 90 秒外层预算，两种模式均严格超时，记录在 [design_results.jsonl](stage4d_lt_assisted_rollout_20260907/design_results.jsonl)。

运行环境为 Python 3.14.6；开始工作时 Git HEAD 为 `f377126a70777a304793100777bb4aaffc3f755e`。冻结配置和 manifest 分别见 [frozen_configs.json](stage4d_lt_assisted_rollout_20260907/frozen_configs.json)、[design_manifest.jsonl](stage4d_lt_assisted_rollout_20260907/design_manifest.jsonl) 和 [mechanism_manifest.jsonl](stage4d_lt_assisted_rollout_20260907/mechanism_manifest.jsonl)。

## 4. 机制矩阵结果

| 配置 | 完成/总数 | 相对 D0 改善 | 相对 D0 退化 | 中位耗时 | 说明 |
|---|---:|---:|---:|---:|---|
| D0 LT | 4/4 | 0 | 0 | 0.61 s | 冻结基线 |
| D1a，g=0.05 | 4/4 | 0 | 0 | 3.58 s | 全部持平 |
| D1a，g=0.15 | 4/4 | 0 | 0 | 3.58 s | 全部持平 |
| D1a，g=0.20 | 4/4 | 0 | 0 | 3.58 s | 全部持平 |
| D1a，g=0.15 且 r>=2 | 4/4 | 0 | 0 | 3.63 s | 持续时间过滤无收益 |
| D1b 跨 job 池 | 4/4 | 0 | 0 | 3.56 s | 全部持平 |
| D1c 深度 2 | 4/4 | 0 | 0 | 3.57 s | 全部持平，预算回退更多 |
| 全量触发，深度 1 | 4/4 | 0 | 0 | 3.56 s | 全部持平 |
| 周期 4，深度 1 | 4/4 | 1 | 0 | 3.51 s | 仅 optional-idle 小幅改善 |
| 随机 25%，深度 1 | 4/4 | 0 | 0 | 3.56 s | 全部持平 |

逐次原始结果见 [mechanism_results.jsonl](stage4d_lt_assisted_rollout_20260907/mechanism_results.jsonl)。其中周期触发的唯一改善发生在 4-job optional-idle；同图 work-conserving 持平，8-job 两种模式也持平。D1b 在 4-job 图完成了 20/23 个候选评价，但在 8-job 图频繁碰到共享截止；深度 2 没有把额外展开转化为 makespan 收益。

Stage 4f 已表明这两个 micro 图上 FIFO、固定顺序、LT 和多种 job 策略的 makespan 相同。因此本轮 0.228% 的单点改善虽严格超过这些冻结简单基线，却远低于准入幅度，且没有独立来源复现。

## 5. 验收逐项判断

| 条件 | 结果 |
|---|---|
| 完成 schedule 的 trace 全合法 | 通过，40/40 |
| 无新增实例 timeout | 小图通过；大图 D0 失败 |
| 新来源组平均改善至少 1% | 未满足；没有新来源，设计池最大仅 0.228% |
| 至少两个独立来源组严格改善 | 未满足 |
| 最坏逐图退化不超过 1% | 小图通过，未观察到退化 |
| 相对 D0 中位调度时间不超过 3 倍 | 未满足，约 5.8 倍 |

M1--M3 因此只能支持“候选与深度机制可合法执行”，不能支持质量准入。M4 的先决条件同时缺少新来源和合格冻结配置，按预先规则不运行，避免结果后调参。

## 6. 失败解释与后续边界

Stage 4b 的 23 个条件改善证明某些单状态可被修复，但在线多次局部选择会改变后续轨迹，而且每次完整 LT 补全成本很高。本轮结果说明“局部标签存在”不能自动转化为端到端稳定收益。GPT13/GPT7 work-conserving 中固定 job 服务顺序优于 LT、但采样的一步修正没有改善的现象也没有被深度 2 弥补；收益若存在，可能要求更长的 job 服务承诺，而不是继续把 rollout 深度从 2 任意加大。

若以后重启 4d，应先优化 D0 通用调度路径，使 7 个设计图两种模式均在 90 秒内完成，并把小图中位成本压到 3 倍以内；然后获取至少三个按父 workload 分组的新来源，再冻结一次配置进行 M4。达到这些条件前，不继续扩大深度，不重新准入 barrier，也不把 D2 或 4c 混入本结论。

## 7. 验证

- 定向回归：38 passed；全量回归：260 passed（140.49 秒）。
- Ruff：本轮修改文件全部通过。
- 机制实验：40/40 completed，40/40 trace valid，0 timeout。
- 大图预算门禁：2/2 process wall timeout（每项 90 秒），如实保留。

复现命令：

```powershell
$env:PYTHONPATH='src'
python -m experiments.llm_structure.nonpreemptive.stage4d_evaluate --manifest experiments/llm_structure/nonpreemptive/manifests/stage4d/lt_assisted_mechanism.jsonl --config experiments/llm_structure/nonpreemptive/manifests/stage4d/lt_assisted_configs.json --output <output.jsonl> --time-limit-s 15
```
