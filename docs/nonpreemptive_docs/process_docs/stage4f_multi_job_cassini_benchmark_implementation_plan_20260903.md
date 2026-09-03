# 不可抢占 Stage 4f：以 Multi-job 为主、有限使用 Cassini 的 Benchmark 实施计划

日期：2026-09-03

## 1. 目的与本轮决策

本轮把不可抢占 Stage 4 的 benchmark 建设重点转向 multi-job。原因不是简单地增加任务数量，而是让来自不同 job 的通信在同一固定资源上形成持续竞争，从而更容易出现会改变最终 makespan、Job Completion Time（JCT）或公平性的调度选择。

Cassini 拓扑更容易让多条通信路线共享少数链路，因此适合用来制造固定多资源冲突。但 routed 图的模拟成本明显高于单 channel，当前两个 4078-task routed 双 job 图完整 LT 回放约为 119--121 秒，已经超过 90 秒准入预算。因此本轮采用以下原则：

1. multi-job 是主要输入方向；
2. 单 channel multi-job 是低成本主实验；
3. Cassini 只用于少量、成对、经过竞争筛选的多资源样例；
4. 不通过无限复制完整大图提高冲突，而通过 job 数、到达时间和共享瓶颈提高单位任务数的有效冲突；
5. 只有动作差异进一步造成目标值差异的样例，才进入算法质量实验；
6. optional-idle 与 work-conserving 始终分开生成结果和结论；
7. 本轮只属于不可抢占 Stage 4，不修改可抢占 benchmark、模拟器和算法。

## 2. 已有证据与尚未解决的问题

### 2.1 已有运行证据

第二轮基础实验已经得到：

- 640--2038-task 的 8 个中图，`bare`、`validated` 和受限观测路径各重复 3 次，全部完成；
- 2038-task 单 channel 的 validated LT 中位数约为 7.6 秒；
- 2038-task routed 图的 validated LT 中位数约为 15.5--15.6 秒；
- 1282--2564-task 单 channel multi-job 图的完整验证约为 4.2--16.8 秒；
- 4078-task routed 双 job 图虽然 trace 合法，但完整验证约为 119--121 秒，超出 90 秒预算。

这说明中型输入已经可用于正式实验，但不能把两个 2000-task routed 父图直接合并后用于大量算法和参数组合。

### 2.2 已有竞争证据

现有 multi-job 图中已经观察到大量合法动作和简单策略分歧，但这还不是算法收益证据：

- 两个已检查的单 channel 组合中图，首个策略分歧状态的冻结 LT completion value spread 都为 0；
- 既有小图 Exact 标签存在非零 action value spread，但 LT regret 仍为 0；
- 当前 routed 正式图太少，active reservation 下的多资源启动集合质量差异不足。

因此本轮 benchmark 的核心目标不是继续统计“有几个可选动作”，而是找到并冻结“不同动作确实改变最终目标”的状态和完整输入。

## 3. Benchmark 总体分层

### 3.1 小型机制与标注集

建议规模：每图约 30--400 task。

用途：

- 手算或 Exact 验证不可抢占语义；
- 验证跨 job 队头阻塞、WAIT、饥饿和目标冲突；
- 对策略分歧状态计算首动作 value；
- 为 selective rollout 和 job-aware 策略提供标签。

输入优先来自真实 AICB 图的因果闭包或可验证决策窗口。人工小图只用于隔离机制和固定反例，不得冒充真实 AICB multi-job 证据。

### 3.2 中型主实验集

建议总规模：每图约 800--2500 task。

这是本轮完整基线、算法对照、消融和 holdout 的主体。优先构造：

- 2-job 中型组合；
- 4-job 小父图组合；
- 同构与异构；
- 同时、错峰和突发到达；
- 单 channel 为主；
- 少量 Cassini routed 图。

每个正式中图应在 90 秒内至少完成 FIFO、LT 和一个简单 job-aware 基线的独立 trace 验证。无法满足者降为成本诊断集。

### 3.3 大型成本诊断集

建议总规模：约 3000--6000 task，只保留 2--4 个代表样例。

用途仅限：

- 运行时间和内存趋势；
- 30/90/180 秒预算下的完成状态；
- 受限前缀竞争观测；
- 检查回退策略是否可执行。

大型图不参与大量参数搜索，不要求 Exact，不把 timeout 解释为算法质量差。

## 4. Cassini 的有限使用规则

### 4.1 使用比例

候选阶段可以生成较多 Cassini 组合以便筛选，但正式中型质量集建议控制为：

- 单 channel：8--12 个；
- Cassini routed：4--6 个；
- Alibaba 或其他低冲突 routed 对照：2--4 个；
- routed 大图成本诊断：最多 2 个。

Cassini 不超过正式质量集约三分之一。这个比例是初始成本控制值，不是固定研究结论；若后续 Cassini 样例没有形成目标值差异，应继续缩减。

### 4.2 成对控制

Cassini 结果必须尽量与同源控制成对：

1. 相同 AICB workload；
2. 相同 job 数和 arrival；
3. 相同通信大小及 DAG 依赖；
4. 只改变 topology、route、resource 和由固定瓶颈带宽推导的 duration；
5. 同时保存 Cassini 与控制拓扑的文件 hash。

不能把不同 workload 上的 Cassini 和 Alibaba 结果直接归因于拓扑。

### 4.3 Cassini 候选准入

生成后先做静态路线检查。至少报告：

- 不同 job 通信使用同一资源的任务数和比例；
- 每个资源被多少 job 使用；
- 资源负载最高的前若干项；
- 同时 ready 且争用同一资源的跨 job 通信次数；
- active communication 保留资源时，可启动集合是否改变；
- 最大 ready communication 数和最大 startable 数。

只有观察到跨 job 共享瓶颈的候选，才进入完整模拟。仅仅标记为 Cassini、但实际 route 基本分离的图不进入 Cassini 主集。

### 4.4 不修改路由来制造结论

本轮不手工改写 SimAI 导出的单条通信 route，不人工删除资源来制造瓶颈。若要进行带宽缩放或热点强化，必须满足：

- 单独归类为受控压力实验；
- 保存原 topology hash 和变换参数；
- 与未变换样例配对；
- 不写成原生 Cassini 结论。

## 5. Multi-job 组合矩阵

### 5.1 job 数量

第一轮候选覆盖：

- 2-job：主要质量输入；
- 4-job：用于提高竞争密度，父图必须较小；
- 8-job：只选微型父图，作为突发流量和公平性压力实验；
- 不生成两个完整 2038-task routed 父图以外的更大常规组合。

在总 task 数接近时，优先比较“较多小 job”和“较少大 job”，判断收益来自 job 数还是图规模。

### 5.2 workload 组合

至少包含：

- 同构：检查对称性和 round-robin；
- 长 job + 短 job：检查队头阻塞和短作业延迟；
- 通信密集 + 计算密集：检查 overlap；
- dense + MoE：在转换配置合法时检查通信形状差异；
- 相同 DAG、不同 arrival：隔离到达时间影响。

完全同构、同时到达的图可能因为对称性而没有 value spread。这类图保留为公平性或负对照，不作为主要算法收益输入。

### 5.3 到达方式

arrival 以每个父 job 的冻结 validated LT makespan 为尺度，不使用未经记录的绝对常数。候选包括：

- 同时到达：`0%`；
- 轻度错峰：`10%`；
- 中度错峰：`25%`；
- 大幅错峰：`50%`；
- 长 job 运行中途到达一个短 job；
- 3--6 个短 job 在同一时刻突发到达；
- 4-job 采用 `0/10/25/50%` 到达。

每条记录保存绝对 arrival、比例、比例所依据的父图 makespan、父图策略和父结果 hash。

### 5.4 组合语义验证

每个组合必须通过：

- job id 唯一，task id 使用 job 命名空间；
- job 之间没有依赖边；
- 每个 job 的根节点受自己的 arrival release 约束；
- 所有 job 共享同一固定资源定义；
- 父图 scenario、semantics、time unit 兼容；
- active communication 在完成前持续保留全部资源；
- trace 中不得出现通信暂停、切换或部分资源获取；
- 父图路径和 content hash 完整保存。

## 6. 有效冲突的四级准入

对候选依次执行，上一层不满足时不进入更昂贵的下一层。

### 6.1 静态资源重叠

至少存在两个不同 job 的通信使用同一个资源。routed 图还应报告热点资源上的跨 job 通信数量。如果没有静态重叠，作为无竞争负对照或直接排除。

### 6.2 动态动作冲突

在最多前 128 个决策或 30 秒内，至少观察到一次：

- 两个不同 job 的 ready communication 争用同一资源；或
- active reservation 导致一个 job 的通信暂时不可启动；或
- 至少两个不同的完整合法启动集合。

timeout 只能标为 unknown，不能标为没有冲突。

### 6.3 策略分歧

在同一状态上，FIFO、LT、短通信优先、job round-robin、年龄优先等至少两个基线选择不同动作。只比较完整合法动作，不把通信排序差异误当作启动集合差异。

### 6.4 目标值差异

冻结分歧状态，对代表性首动作逐个执行，然后使用同一冻结后续策略完成，分别计算：

- 联合 makespan；
- 平均 JCT；
- 最大 JCT；
- 加权完成时间；
- slowdown；
- 是否出现 starvation。

只有至少一个预先声明的目标出现非零 value spread，才标为 `quality_informative`。如果只满足前三层，则标为 `choice_only`，可用于性能和语义测试，但不进入算法收益主表。

## 7. 控制实验成本

### 7.1 三段式流水线

1. **廉价筛选**：静态资源重叠 + 最多 128 决策的受限观测；
2. **局部质量检查**：只在策略分歧状态执行代表性首动作 completion；
3. **完整实验**：只对 `quality_informative` 和少量负对照运行全部基线和候选算法。

候选数量可以较多，但完整实验输入必须少而稳定。

### 7.2 运行职责

- `bare`：快速候选筛选，不默认启用内存跟踪，不声明 trace 合法；
- `instrumented`：共享同一 decision context，只观测受限前缀；
- `validated`：正式结果运行一次独立 trace 回放和合法性验证；
- `profiled`：单独测量内存或 CPU，并标记测量扰动。

不得在每个策略、每个首动作内部重复启动 `tracemalloc`。同一状态的 ready、active、legal action、tail 和下一事件应复用公共 decision context。

### 7.3 硬预算

建议初始预算：

| 工作 | 决策/时间上限 | 超限后的处理 |
|---|---:|---|
| 静态路线检查 | 10 秒 | `unknown_timeout` |
| 动态前缀观测 | 128 决策或 30 秒 | 保留已完成前缀 |
| 单个局部首动作 completion | 30 秒 | 该 action value 为 unknown |
| 中图单次完整基线 | 90 秒 | 从质量主表降级 |
| 大图成本诊断 | 180 秒 | 如实记录最后阶段 |

预算由父进程实施，不允许只把 `time_limit_s` 写入结果而实际不终止。

### 7.4 避免多资源动作爆炸

多资源前缀观测和普通 heuristic 不先枚举完整幂集。使用 FIFO、LT、SPT、LPT、job round-robin、年龄优先、热点优先和互补资源优先构造若干完整合法启动集合。只有 startable 数量较小且预计集合数不超过冻结上限时，才允许完整枚举。

## 8. 基线、候选算法与目标

### 8.1 第一轮基线

每个正式中图至少运行：

- 全局 FIFO；
- 全局 residual Longest Tail；
- 固定 job 顺序；
- job round-robin；
- job 年龄优先；
- shortest remaining job；
- job-aware Longest Tail；
- starvation safeguard。

多资源图的每个策略输出完整合法启动集合，并保留 active reservation。

### 8.2 暂缓项

在没有足够 `quality_informative` 输入前，不进行：

- selective trigger 重新训练；
- 大规模 rollout 深度/宽度搜索；
- 复杂 packing 分数叠加；
- barrier 特征组合搜索。

找到 LT regret 或明确的多资源启动集合 regret 后，再分别重新准入 4c、4d 和 4e。

### 8.3 分开报告的目标

每次实验必须预先声明主目标，至少分别报告：

- 联合 makespan；
- 每个 job 的 arrival、start、completion 和 JCT；
- 平均、加权和最大 JCT；
- slowdown；
- starvation 次数或最长连续等待；
- 公平性；
- 主动 WAIT、forced idle 和资源利用率；
- wall-clock、timeout 和 fallback。

改善平均 JCT 但恶化 makespan 或公平性时，报告为目标交换，不笼统写成算法改善。

## 9. 数据划分与防止泄漏

development、validation 和 holdout 必须按父 workload 分组，而不是把同一父图的不同 arrival 随机拆开。同一 AICB source 的：

- 单 channel 投影；
- Cassini 投影；
- Alibaba 投影；
- 2-job/4-job 复制；
- 相邻 arrival；
- 派生决策窗口；

都属于同一个 source group，必须进入同一 split。这样可以防止算法记住同一 DAG 的重复结构。

建议先冻结 development 候选；只有准入规则、指标和算法参数冻结后，才运行 holdout。失败样例和 timeout 不能从 holdout 中静默删除。

## 10. 代码实施位置

### 10.1 长期生成接口

在 `benchmark_generate/llm/nonpreemptive/` 中保持以下职责：

- `multi_job.py`：只负责合法、可追溯的 job 组合；
- 新增或扩展独立的 multi-job case specification 模块：只负责 source、topology、job 数和 arrival 清单；
- `contention.py`：负责四级准入观测，不负责算法质量结论；
- `publication.py`：只发布通过语义、hash 和准入检查的冻结输入。

公共生成代码不导入 `experiments/`。可抢占和不可抢占的组合入口保持对称目录，但语义实现和发布清单分离。

### 10.2 实验入口

建议新增：

- `experiments/llm_structure/nonpreemptive/stage4f_multi_job_candidates.py`：生成候选清单与 staging；
- `stage4f_multi_job_admission.py`：执行四级准入；
- `stage4f_multi_job_baselines.py`：运行完整基线；
- `stage4f_multi_job_quality.py`：对冻结分歧状态执行首动作 value 检查；
- `stage4f_multi_job_report.py`：汇总目标、成本和失败状态。

实验脚本必须通过命令行接收 manifest、staging 和 output，不再把 `np-foundation-followup-20260902` 写死在模块常量中。

### 10.3 稳定算法接口

只有被正式基线或后续算法复用的策略、状态特征和回放接口进入 `src/llm_structured/nonpreemptive/`。候选 sweep、临时报表和数据选择不进入 `src/`。

## 11. Manifest 与可追溯信息

每个候选至少保存：

- benchmark id、path 和 content hash；
- 每个父图 id、path 和 content hash；
- source workload hash；
- topology name 和 hash；
- route/duration 变换版本；
- job 数、job id 和 arrival；
- arrival 比例及其基准结果 hash；
- task/communication/resource 数量；
- static overlap、dynamic conflict、policy divergence 和 quality 状态；
- optional-idle/work-conserving mode；
- generation/audit/baseline 的预算与结束原因；
- commit、dirty 状态和 diff hash；
- `staged`、`excluded`、`published` 或 `diagnostic_only` 状态。

结果表通过 benchmark content hash 连接输入，不能只依赖文件名。

## 12. `.staging` 生命周期与本次清理方案

### 12.1 当前状态

当前目录：

`benchmark/llm_structure/.staging/np-foundation-followup-20260902/`

包含 8 个 multi-job JSON，共约 12.2 MB。它们均标记为 `staging_only`，没有进入正式 benchmark/index，因此从发布语义上看属于临时产物。

其中两个 routed 组合当前使用的是 Alibaba HPN 父图，不是 Cassini；因此这批 staging 只能作为已有 multi-job 成本与流程证据，不能当作本计划的 Cassini multi-job 结果。

但现在不应立即删除，原因是：

- `stage4_real_composed_stress.py` 仍向该固定目录写入；
- `stage4_medium_quality_probe.py` 直接从该目录读取两个图；
- `stage4_real_composed_stress_20260902/results.jsonl` 保存了这些路径和 hash；
- 其中 6 个单 channel 图是当前 multi-job 成本与竞争结论的原始输入。

立即删除不会破坏正式 benchmark，但会破坏这轮结果的本地复查链。

### 12.2 迁移后清理

按以下顺序处理：

1. 从旧实验脚本抽出确定性的 case specification；
2. 保存父图 hash、arrival、组合器版本和输出 hash 的冻结 manifest；
3. 让新 runner 支持 `--staging` 和按 manifest 重建，不依赖固定日期目录；
4. 对 8 个图执行一次重建 hash 对拍；
5. 把仍有研究价值的图标为新候选，只有通过正式准入者才发布；
6. 确认结果目录已经保存所有必要摘要和拒绝原因；
7. 再删除旧 `np-foundation-followup-20260902` staging 目录。

旧目录删除后可以通过冻结 manifest 确定性重建。若重建 hash 不一致，先保留旧输入并调查转换或序列化变化。

### 12.3 自动清理规则

后续每个 staging run 保存 `created_at`、`workflow_version` 和 `publication_status`。建议提供只读 `list-staging` 和显式 `clean-staging --run-id`，但不在生成或测试结束时自动递归删除。清理前检查：

- 不是当前正在运行或可恢复的 run；
- 没有结果脚本仍硬编码引用；
- 已发布或已保存可确定重建的 manifest；
- 删除目标解析后仍位于 `benchmark/llm_structure/.staging/` 内。

## 13. 测试计划

至少增加以下回归：

1. 组合后无跨 job 依赖；
2. arrival release 正确阻止 job 提前 ready；
3. 相同资源 id 在 job 之间共享；
4. 不兼容 scenario、semantics 或 time unit 时拒绝组合；
5. Cassini/控制拓扑成对 case 除 route/resource/duration 外保持预期字段一致；
6. static overlap 能识别跨 job 共享资源；
7. 动态前缀能识别跨 job 同时竞争；
8. active reservation 不会被新动作移除；
9. optional-idle 和 work-conserving 动作空间分开；
10. 高 startable 数不会触发完整幂集枚举；
11. timeout 保留最后阶段和已完成决策数；
12. manifest 重建后 hash 一致；
13. staging 不进入公共 benchmark index 和仓库范围的 problem 发现；
14. 正式 validated 结果通过独立 trace 回放。

定向测试通过后运行：

```powershell
python -m pytest -q tests/llm_structured/nonpreemptive tests/integration/test_nonpreemptive_stage4a.py
python -m ruff check benchmark_generate/llm/nonpreemptive experiments/llm_structure/nonpreemptive src/llm_structured/nonpreemptive
```

修改公共 loader、validator、trace 或模拟器时，再运行完整 `python -m pytest -q`。

## 14. 推荐执行顺序

### M0：整理旧 staging

- 抽出旧 8-case specification；
- 移除实验脚本中的固定 staging 路径；
- 冻结 manifest 并完成重建 hash 对拍；
- 暂不删除旧目录，等待 M4 后统一清理。

### M1：候选生成

- 选择较小的真实父图；
- 生成 2/4/8-job 与 arrival 组合；
- 对同一 workload 生成 Cassini 与控制拓扑配对；
- 写入候选 manifest，不更新公共 index。

### M2：廉价准入

- 静态资源重叠；
- 受限动态前缀；
- 简单策略分歧；
- 按原因排除低冲突或超预算候选。

### M3：质量确认

- 冻结策略分歧状态；
- 对代表性首动作计算统一后续策略 completion；
- 找到 makespan/JCT/fairness 的非零 value spread；
- 按父 workload 划分 development/validation/holdout。

### M4：正式基线与发布

- 运行完整基线；
- 每条正式结果独立 trace 验证；
- 发布 8--12 个高价值中图和少量负对照；
- 保留 2--4 个大型图为 `diagnostic_only`；
- 迁移完成后删除旧 staging run。

### M5：算法重新准入

- 若出现 LT regret，重新进入 selective rollout；
- 若出现启动集合 value spread，重新进入 conflict-graph packing；
- 若 barrier 能预测这些失败状态，再作为 LT 修正特征；
- 若简单 job-aware 策略已经足够，形成受限或否定结论，不继续堆叠算法。

## 15. 阶段退出条件

满足以下条件后，multi-job benchmark 建设才算完成：

1. 至少覆盖 2-job、4-job、同构、异构、同时和错峰到达；
2. 有单 channel 主集和有限 Cassini routed 主集；
3. Cassini 与控制拓扑按同源 workload 成对；
4. 每个正式图有父图、source、topology、arrival 和输出 hash；
5. 每个正式质量图至少有一个非零目标 value spread；
6. 保留少量 `choice_only` 和无竞争负对照；
7. 正式中图基线在统一预算内完成并独立验证 trace；
8. makespan、JCT、slowdown、公平性和成本分开报告；
9. optional-idle 与 work-conserving 分开报告；
10. development/validation/holdout 按父 workload 隔离；
11. 大图只用于成本诊断，不主导算法结论；
12. 旧 staging 已具备确定重建清单并完成清理；
13. 只有得到相应失败状态证据的 4c/4d/4e 算法才重新进入实验。

本计划不预设复杂算法一定优于 LT。最终允许得到三种结论：multi-job 确实提供稳定调度收益、收益只存在于特定 Cassini 瓶颈和目标下，或者简单 job-aware 基线已经足够。三种结论都必须建立在统一输入、预算、合法 trace 和 holdout 上。
