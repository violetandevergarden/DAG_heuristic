# Stage 4g 综合算法研究结果

日期：2026-08-22

## 1. 最终结论

Stage 4g 的最终可用算法是 **`integrated_v0`**。它是一个统一、在线、确定、可审计的 residual Longest Tail 调度器：

- 单通道选择 exclusive residual tail 最大的 eligible communication；
- 固定多资源按相同 residual LT 分数排序，贪心构造 inclusion-maximal compatible set；
- 同分使用稳定 task ID；
- 不主动 WAIT；forced idle 只由模拟器推进；
- 大于 1000 节点时关闭详细审计，但调度动作不变。

本阶段没有证据支持把高级 packing、完整或截断 rollout、direct barrier 或 job-aware 规则加入默认路径。因此最终版本不是 `P+R+B+J`，也不宣称相对 LT 有新质量收益。它的价值是把已有最可靠的 LT 骨架形成一个资源模式统一、带配置/预算/审计/降级合同的正式入口，并清楚结束没有通过准入的组合探索。

## 2. 算法定义

### 2.1 单通道

对当前状态的每个 eligible communication `c`，计算包含节点自身的 residual longest path，再减去 `c` 当前剩余通信工作量：

```text
exclusive_tail(c) = residual_tail_including_self(c) - remaining_comm_work(c)
```

选择键最小者：

```text
(-exclusive_tail(c), 0, task_id(c))
```

这意味着 tail 更大者优先，完全相同则按 task ID。通信只运行到公共模拟器的下一个离散事件，之后可以继续、暂停或恢复。

### 2.2 固定多资源

先按同一 residual LT 规则排列 eligible communications。依次扫描：若某通信与已选通信资源集合不冲突，就加入动作。扫描结束得到非空、资源兼容且 inclusion-maximal 的集合，随后再由公共模拟器验证和执行。

该规则优化的是集合构造的确定性和合法性，不保证最大基数，也没有理论近似比声明。

### 2.3 安全模式

公开输入任务数超过 1000 时，算法进入 `integrated_safe_large` 行为：停止详细逐决策审计和任何可选诊断，继续使用完全相同的 LT 动作。降级依据只有公开规模属性，不读取样例身份、metadata 或答案。

## 3. 为什么最终算法没有更多组件

### 3.1 高级 packing（P）

固定 task score，只把 LT greedy 改为有界 `one_exchange + set_score`。在 22 个 Stage 3 多资源开发图上结果为：

| 方法 | 胜 / 平 / 负（相对 LT） | 总 makespan 改善 | 最大退化 |
| --- | ---: | ---: | ---: |
| one-exchange 实验 packing | 0 / 19 / 3 | -5 | 3 |

它没有任何胜例，并出现三个退化，未达到“冻结验证正净收益、最坏退化可接受”的准入门槛。Stage 4c 既有完整 completion 选择器在真实中图上又存在 600 秒级超时证据，因此没有继续把它扩展到 100--1000 节点集。最终保留 LT greedy maximal。

### 3.2 Rollout（R）

Stage 4d 已证明完整 rollout 在旧小图上能修复部分 LT 决策，但在 1536/2204 节点图上一次候选的完整 LT completion 都难以在预算内完成。实施计划要求的新截断估值只有在候选上下界能严格区分时才允许改动作。

本阶段建立了 `integrated_r_exp` 的冻结配置和共享预算合同，但没有得到一个语义可靠、可证明区分候选的 residual 上下界。用任意局部代理强行排序会把“代理更好”误写成“makespan 更好”，违反准入规则。因此：

- 完整 completion 明确排除在线默认路径；
- 截断估值保留为 `experimental_not_admitted`；
- 正式策略不运行失败搜索后再回退，而是从一开始直接使用 LT；
- 旧小图 rollout 的正面机制证据仍成立，但不能外推为当前中图可部署组件。

这属于规划允许的停止条件，不是遗漏一个已经验证有效的组件。

### 3.3 Barrier（B）

Stage 4e 已有冻结否定证据：direct barrier margin 修正在 74 个小图上为 1 胜、65 平、8 负，并在 100--1500 节点验证图上全部差于 LT。因此本阶段不重复组合矩阵：

- 不删除候选；
- 不打破 LT 平局；
- 不单独触发 rollout；
- 正式路径 barrier 调用数为 0；
- 只保留 `diagnostics_only` 配置和特征接口。

### 3.4 Multi-job（J）

Stage 4f 尚无按 makespan、JCT、slowdown 或 fairness 分离并冻结的正式证据。将 job-aware 规则加入单作业 makespan 算法会混合目标，因此状态保持 `deferred`，不进入本阶段最终算法。

## 4. 实验设计

### 第一层：Stage 1--3 开发与筛选

- 74 个单通道 Stage 1--2 benchmark；
- 22 个固定多资源 Stage 3 benchmark；
- 类别保留 random、adversarial 和 real；
- 比较 FIFO、固定顺序、LT、`integrated_v0`，多资源另比较有界 one-exchange packing；
- 83 个样例存在 hash 匹配且状态为 optimal 的 Exact reference。

### 第二层：冻结 100--1000 节点验证

阈值和算法冻结后生成四张图：100、300、600、1000 节点，seed 为 61--64。固定层宽、边概率、skip edge 和 barrier 周期。该集合只验证迁移、等价性和成本，不参与选组件。

### 第三层：中大图成本边界

使用一张 1500 节点、seed 71 的图，90 秒子进程硬墙钟。该图只支持逐例成本和安全降级结论，不支持真实 LLM DAG 总体收益结论。

所有输入和生成定义均有 SHA-256；所有完成 Trace 均通过公共 validator。没有 timeout 或 error，也没有用 fallback makespan 填充未完成算法。

## 5. 开发集结果

### 5.1 简单基线

在 74 个单通道图上：

| 方法 | 胜 / 平 / 负（相对 LT） | 总 makespan 改善 | 最大退化 |
| --- | ---: | ---: | ---: |
| FIFO | 2 / 36 / 36 | -152 | 19 |
| 固定顺序 | 1 / 38 / 35 | -177 | 19 |
| LT | 0 / 74 / 0 | 0 | 0 |

这里“负”表示 makespan 大于 LT。结果再次支持 LT 作为当前基础策略，但不是理论最优证明。

### 5.2 `integrated_v0` 等价性

在全部 96 个开发样例上：

| 指标 | 结果 |
| --- | ---: |
| makespan 与 LT 相同 | 96 / 96 |
| Trace hash 与 LT 相同 | 96 / 96 |
| 胜 / 平 / 负 | 0 / 96 / 0 |
| 总变化 | 0 |
| 最大退化 | 0 |

83 个 Exact 完成样例中，`integrated_v0` 有 72 个达到最优，最优率 86.75%；平均绝对 makespan gap 为 0.241，最大 gap 为 7。它与 LT 完全相同，因此这些数字说明 LT 骨架的小图质量，而不是综合层带来了额外收益。

## 6. 冻结规模结果

| 节点数 | LT makespan | `integrated_v0` makespan | LT wall-clock | integrated wall-clock | integrated 峰值内存 | 状态 |
| ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 100 | 132 | 132 | 71.0 ms | 102.3 ms | 0.37 MB | completed |
| 300 | 372 | 372 | 551.2 ms | 787.0 ms | 1.44 MB | completed |
| 600 | 775 | 775 | 2312.2 ms | 3006.5 ms | 3.94 MB | completed |
| 1000 | 1282 | 1282 | 6567.0 ms | 8547.9 ms | 8.71 MB | completed |
| 1500 | 1958 | 1958 | 14986.3 ms | 14375.2 ms | 16.17 MB | completed、安全降级 |

100--1000 节点时综合入口启用了详细审计，因此相对直接 LT 有额外 Python 记录成本；这不是搜索成本，也没有带来 makespan 改善。1500 节点超过阈值后关闭详细审计，综合入口成本恢复到与 LT 同一量级。本次逐例测量受进程负载影响，不能把 1500 节点的一次更快解释为算法加速。

所有五张图的 makespan 和 Trace hash 均与 LT 完全相同，验证了安全降级不改变调度语义。

## 7. 最坏失败案例与限制

1. **LT 不是 Exact**：83 个 Exact 完成小图中有 11 个未达到最优，最大绝对 gap 7。`integrated_v0` 继承该限制。
2. **高级 packing 可退化**：one-exchange 实验选择器最大退化 3，不能按“候选更多必然更好”理解。
3. **详细审计有成本**：100--1000 节点逐决策记录使 wall-clock 增加；部署时若不需要诊断，应使用安全模式或关闭详细审计。
4. **没有真实大图总体证明**：冻结图为受控生成图，1500 节点只有一例。结果不能越过 Stage 4a 的真实竞争认证和大图回放边界。
5. **没有近似比**：实验最优率不等于理论近似界。
6. **不适用于其他语义**：结论只适用于 finish-to-start、compute 自动不可抢占、communication 事件点可抢占、无主动 WAIT、固定资源、多资源 work-conserving 和单作业 makespan。
7. **multi-job 目标未覆盖**：不能把该结论写成 JCT、slowdown 或 fairness 改善。

## 8. 最终使用建议

可以直接使用 `integrated_v0` 作为 Stage 4g 当前正式算法：

- 单通道一般 DAG：`integrated_v0` 等价于 residual LT；
- 固定多资源 DAG：`integrated_v0` 等价于 LT greedy maximal packing；
- 大于 1000 节点：自动关闭详细审计，保持相同动作；
- 需要研究新组件时：通过显式实验配置运行，不修改公开默认算法。

不应默认启用：`integrated_p_exp`、`integrated_r_exp`、barrier tie-break、barrier rollout trigger 或 job-aware 规则。它们只有在新的开发、冻结验证和成本检查全部通过后，才能形成新版本 `integrated_v1`；不能复用本次验证集调参后仍称为冻结结果。

代码实现与测试详情见 [Stage 4g 代码实现结果](/D:/Code/SimAI/DAG_heuristic/docs/result_docs/stage4g_code_implementation_result_20260822.md)，逐例机器数据见 [Stage 4g 统一实验 JSON](/D:/Code/SimAI/DAG_heuristic/docs/result_docs/stage4g_integrated_evaluation_20260822.json)。
