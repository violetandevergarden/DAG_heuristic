# Stage 4f 修正与继续推进方案

## 1. P0：Exact 和指标必须诚实

让 `exact_makespan` 返回 status、是否达到状态/时间限制、上界和下界；只有 `status=optimal` 才允许作为 oracle。`solo_optimal_jct` 遇到非最优结果必须返回缺失或明确的 upper-bound 标记，slowdown 不得使用未经验证的分母。`exact_hierarchical` 不抛裸异常，改为机器可读的 incomplete result，并由 runner 单独统计。

## 2. P0：保留 workload 语义并修正完成时间

重建 `BenchTask` 时完整保留 labels、phase、microbatch 和 collective 标记，增加 round-trip 测试。多 job 结果应从最终完成事件或任务 runtime 状态计算 JCT；trace interval 仅作交叉检查。加入零时长 final compute、到达时刻恰好相等、job 无通信和并行通信的测试。

明确 service 定义：若目标是资源占用，按每个资源实际占用时间计；若目标是 wall-clock attained service，应改名并在文档中说明并行时如何计量。`weighted_lt` 重新命名为能反映权重方向的策略，或提供正值分数公式，并做权重反转消融。结果对象和 schema 增加 `primary_objective`，禁止把 makespan、weighted JCT、slowdown 混成一个结论。

## 3. P1：Exact 状态和基准集

为状态 key 写出未来等价说明，至少保留到达、剩余工作、运行任务和资源占用等影响因素；在小图上与未压缩状态搜索交叉核验。为每个 fixture 记录类别、来源、seed、benchmark hash 和是否真实。J0-J6 继续作为控制集，但新增随机、针对策略的攻击集和真实 AICB/Stage 4a 快照。

## 4. P2：实验推进

冻结 primary objective 后分开评估 makespan、加权 JCT、slowdown 和 fairness。Exact 只用于可完成的小图，大图报告可行上界及运行时间。比较五种现有策略和简单基线，报告每类 wins/ties/losses、平均/最大差距、到达等待、资源利用率、抢占次数和 service 统计。SimAI probe 只能作为转换链路检查，不能替代真实 workload。

## 5. 继续/停止条件

所有 bounded Exact 都有清晰状态；slowdown 分母经过最优性核验；标签和完成时间回归通过；真实多 job 集合至少覆盖不同到达重叠和资源冲突。若某策略在独立真实集上稳定改善且公平性代价可解释，才进入 Stage 4g 集成；若仅在单个手工 fixture 获胜，则结项为指标和语义验证，不扩展更多启发式名称。

## 6. 交付物和审计要求

每个 workload 保存 job id、到达依赖、权重、资源需求、phase/labels、来源、seed 和 hash。每次策略运行保存 primary objective、所有辅助指标、Exact status、运行限制、trace hash 和版本。汇总表同时提供单 job 基线和多 job 结果，不能只保留胜负计数。

建议先完成 7 个控制 fixture 的结果迁移，修正“optimal”措辞并重新运行；随后加入至少一组到达重叠的随机集和一组真实派生集。任何策略若只在控制 fixture 改善，应归档为反例或教学样例，不作为 Stage 4g 默认策略。

## 7. 实施任务

F1 传播 Exact status 和上下界；F2 修正 solo denominator 与 slowdown；F3 从完成事件计算 JCT；F4 保留全部任务标签；F5 定义两类 service；F6 建立分类数据集；F7 重新实验。F1-F4 是正确性门槛，未完成前暂停比较策略胜场。

## 8. 数据生成要求

随机集覆盖 job 数、到达间隔、权重、通信/计算比例和资源冲突程度；攻击集分别针对 FCFS、shortest remaining、weighted LT 和 attained service；真实集从完整 workload 以可说明的规则缩减。相同来源的切片放在同一数据分区，避免泄漏。每类固定约十个代表 seed，大规模测试由生成器运行，不无限提交 JSON。

真实多 job 组合必须说明是否来自同一模型的并发训练、不同模型共享网络，或人为错峰。若拓扑文件缺失则明确为单/固定资源投影，不声称真实多通道。SimAI 依赖仍只允许出现在转换层和 integration tests。

## 9. 指标契约

每个 job 保存 arrival、completion、JCT、weight、solo optimum status、slowdown 和 service。汇总保存 makespan、sum/weighted JCT、平均/最大 slowdown、公平性指标及 primary objective。缺少可靠 solo optimum 时 slowdown 为 null 并附原因，不能用 1 或可行上界替代。

service 若按资源时间计，应对每个占用资源的区间积分；若按 wall-clock 计，只对 job 有通信运行的时间并集积分。两种结果分别命名，禁止在策略内部用一种、报告中解释成另一种。

## 10. 验收矩阵

| 项目 | 通过标准 |
|---|---|
| oracle | optimal/feasible/timeout 可区分 |
| slowdown | 仅可靠分母产生数值 |
| 完成时间 | 与最终任务事件一致 |
| labels | compose 前后无损 |
| 到达 | 无主动 WAIT，依赖释放正确 |
| 多资源 | 动作包含极大且资源不冲突 |
| 目标 | primary objective 明确且不混用 |

## 11. 实验与决策门槛

先用 Exact 小图验证五个策略，再在中图比较运行时间和差距。随机、攻击、真实三表分开，wins 表述为“比较方法中最好”；只有 Exact optimal 才计算 optimal rate。若策略改善 weighted JCT 但损害 makespan，应呈现 Pareto 关系和明确选择目标，不宣布总体胜出。

进入 Stage 4g 前至少要求一个正式真实多 job 集、全部正确性测试通过、主目标冻结、候选策略在留出集有可复现改善且最坏退化受控。否则 Stage 4g 只接入 flat LT 基线和多指标评估接口。

## 12. 兼容迁移方案

旧 `stage4h` 文件和 J0-J6 结果不删除，新文档引用时标注为 Stage 4f 历史资产。API 可先为 status 增加字段并保持 makespan 属性，给旧调用者迁移期；一旦结果用于 slowdown，必须强制检查 status。labels 修复只补字段，不改变任务 id 和依赖，减少 benchmark hash 之外的无关变化。

## 13. 最小发布单元

第一发布单元只包含 oracle/status、slowdown 和完成时间测试；第二单元包含标签及 service 定义；第三单元生成分类数据；第四单元运行策略实验。这样若实验结果变化，可以定位是指标修复、数据变化还是策略本身。

## 14. 失败处理

Exact 超时返回 feasible 加上下界；solo 不最优则不计算 slowdown；job 未完成则整个 schedule 标为 incomplete；资源配置缺失则 loader 拒绝；真实转换丢标签则样例不得进入 real 汇总。实验 runner 最终退出码和 JSON 状态应一致，避免终端显示失败但结果文件写成成功。

## 15. 最终说明应包含

正式编号迁移、workload 来源、到达模型、primary objective、策略定义、Exact 完成率、分类结果、最坏反例、运行成本和未解决限制。结论只描述当前数据支持的范围，不把“比较策略中最好”替换为“全局最优”。
