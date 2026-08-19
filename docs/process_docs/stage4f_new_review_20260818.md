# Stage 4f 多作业调度审查

## 1. 范围和编号迁移

正式 Stage 4f 面向多 job 的到达、独立目标和公平性扩展。历史文档中的 `stage4h_multi_job` 对应本阶段。基础模拟语义仍是无主动 WAIT：到达由依赖链上的自动计算释放表达；job 之间共享固定资源。

## 2. 当前实现和结果

核心在 `src/llm_structured/multi_job.py`，工作负载生成在 `benchmark_generate/llm/multi_job_workloads.py`，实验在两个 multi-job runner。J0-J6 是 7 个固定资源控制 fixture，比较 flat LT、shortest remaining、weighted LT、FCFS 和 attained service。结果字段 `makespan_wins`、`weighted_jct_wins` 表示所比较策略中的最好者（含并列），不是 Exact 最优。历史结论写成“7/7 optimal makespan”不准确，应改为“7/7 在比较策略中达到最好或并列最好”。

SimAI pipeline probe 只有 4 个合成 builder 案例，方法 makespan 相同，而 rollout 约慢 40 倍；它不是实际 AICB 多作业数据。当前没有 Stage 4a 真实多作业留出集。

## 3. 实现风险

`compose_jobs` 用自动 compute release 表达 arrival，符合公共语义；但重建 `BenchTask` 时保留 role/cut 却丢弃 labels，真实 phase、collective、microbatch 信息会丢失。`exact_makespan` 调用有界 Exact 后直接返回结果，没有暴露 status；`solo_optimal_jct` 也直接把 bounded Exact 的 makespan 当分母，超时得到的可行上界可能被错误称为最优，进而污染 slowdown。

`evaluate_multi_resource_schedule` 从 trace interval 推断完成时间，而不是使用最终任务完成事件；零时长最终计算或没有普通 interval 的任务可能被漏算。J0-J6 每个 family 只有一个手工实例，没有随机/攻击/真实分层、来源和 hash manifest。结果对象没有明确保存 primary objective。

`weighted_lt` 使用负的 local 值乘 weight，实际偏向大权重长尾通信，名称和目标关系需要说明并做消融。多个通信并行时 `attained_service` 和 `last_service` 对每个选中 job 加整段 wall-clock 时间，而不是资源时间；公平性解释不明确。`exact_hierarchical` 达到限制时抛异常，没有机器可读的不完整状态。状态 key 虽可能足够于零成本 makespan/JCT，仍需未压缩 Exact 交叉验证和到达状态证明。

## 4. 测试与结论

已有测试验证命名空间、目标切换、K=1 反例、极大多资源完成和指标分离，说明原型结构可靠；未覆盖零时长完成、Exact timeout 进入 slowdown、labels 保留、并行 service 计量和多 job 到达边界。完整测试 169 passed，但不能支持历史“最优”措辞。

结论是：多 job 语义原型和指标分离值得继续，策略优劣和真实适用性尚未建立。先修正 Exact 状态传播、完成时间和标签保留，再生成真实多 job 集合；在此之前不应把任何策略称为最优或公平性更好。

## 5. 多作业边界核对

到达事件只能通过已完成依赖释放，不能增加一个需要算法主动选择的 WAIT；job 之间没有隐含的固定顺序。makespan 是所有 job 完成的最后时刻，JCT 从各自到达释放时刻计算；weighted JCT 只在明确权重后汇总。slowdown 的 solo 分母必须来自同一语义下已证明最优的单 job 运行。

资源统计要区分通信占用、compute 时间和被依赖阻塞时间。并行通信时，一个 job 的 wall-clock 服务和资源时间可能不同，报告中必须说明采用哪一种。公平性指标不能反过来解释为 makespan 最优。

## 6. 按文件审查记录

`multi_job.py` 同时承担组合 workload、策略选择、Exact 包装和指标计算，职责较多但目前不必整体重写。最先应隔离的是 oracle status：任何包装层都不能只返回一个数值而丢掉最优性状态。组合任务时的命名空间处理已通过测试，应保留；labels 丢失属于局部复制字段遗漏。

`multi_job_workloads.py` 的 J0-J6 适合用于手工核对到达、权重和资源冲突，但不是统计样本。每个 family 一个实例，且构造目的与策略比较相互可见，因此只能作为控制/攻击 fixture。生成器应支持固定 seed 的批量变化，并保留来源。

`multi_job_evaluation.py` 报告多个指标是正确方向，但 wins 字段命名需要加 `among_compared`，同时列出 Exact status。`simai/multi_job_study.py` 当前四个 synthetic builder 只能证明接口可运行，不能称作真实 SimAI 结果；约 40 倍时间差还需要注明样本和机器环境。

## 7. Exact 和 slowdown 风险链

bounded Exact 超时返回一个合法 schedule 本身没有问题；问题是上层删掉 status 后把 makespan 当作最优。这个值再进入 solo JCT，就会成为偏大的 slowdown 分母，使 slowdown 看起来偏小。最后策略汇总若据此排名，会产生连续三层误导。因此修复顺序必须从 oracle status 开始，而非只改结果文案。

状态压缩还需证明 job 到达信息是否已完全编码在任务 runtime 中，目标累积量是否能从完成时刻恢复。对于 weighted completion time，同一剩余任务状态可能已有不同已完成 job 代价；若搜索只比较未来增量，需要说明常量项如何处理。

## 8. 指标和策略解释

flat LT 优化的是局部剩余长尾，不直接优化 JCT；shortest remaining 偏向短 job；weighted LT 把权重加入局部分数，但没有理论保证；FCFS 依赖到达顺序；attained service 试图表达公平性。五者只能作为不同偏好的基线，不能由一次胜场推断总体优越。

“7/7”应逐指标展开：哪些是严格胜、哪些并列、哪些只在相比的五种方法中最好。没有 Exact 的案例不能使用 optimal 一词。makespan 与 weighted JCT 发生目标翻转正是多 job 阶段的重要结果，应保留而不强行合成综合分数。

## 9. 需要的最小测试图

一个零时长 final compute 图验证完成时间；一个 Exact 立即超时图验证 status 传递和 slowdown 缺失；一个 labels 丰富的组合图验证 round-trip；一个两资源并行图区分 wall-clock service 与 resource-time；一个同时到达并列图验证稳定 tie-break；一个 K=1 图继续验证多 job 退化为单 job 语义。

## 10. 阶段出口判断

到达表达、命名空间、基本策略和多指标输出已形成原型；oracle 完整性、真实 workload、公平性计量和统计结论尚未完成。因此 Stage 4f 不应进入 Stage 4g 默认集成，只能提供基线和接口。先修复指标可信度，再谈策略改进。

## 11. 到达建模的适用范围

用自动 compute release 表达到达能够复用公共事件系统，但该任务不应占用有限计算资源或被调度算法选择。它的 duration 和依赖必须保证到达前 job 内任务不 ready。多个 job 同时到达时要先原子处理同一时刻事件，再计算 eligible 集合，避免 job 顺序影响结果。

若未来研究外部动态到达流，需要明确是否仍能预先写入 DAG；当前实现只覆盖已知 workload 的离线到达，不应直接声称支持未知在线到达。

## 12. 结果可比性

不同 primary objective 的策略不能只按一个 wins 数排序。权重缩放会改变 weighted JCT 数值但不应改变等比例策略关系；slowdown 对短 job 很敏感；fairness 可能以 makespan 为代价。结果表应给出完整指标向量和相对于明确基线的差值。

J0-J6 的“最好”若包含并列，应分别记录 strict wins 和 ties。四个 pipeline probe 的相同 makespan 不表示 trace 相同，还需比较 JCT、抢占和资源利用率。40 倍运行时间仅是当前样本观察，不能当复杂度定律。

## 13. 审查风险排序

Exact 状态丢失和 slowdown 分母错误为最高优先级，因为会直接造成错误结论；完成时间推断和 labels 丢失为高优先级，会影响真实数据；service 定义、策略命名为中优先级；样式警告为低优先级。真实多 job 缺失是进入下一阶段前的硬证据缺口。
