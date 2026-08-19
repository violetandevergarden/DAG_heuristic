# 可抢占阶段 5：LLM 重复结构研究结果与结论

> **2026-08-13 勘误：** 本文实验时使用的 Zero Bubble 原始数据 DAG 确实保留了错误的
> 同层 `B -> W` 依赖，因此下文对 ZB 的黑名单在当时成立。该依赖现已在
> `ZeroBubblePipelineWorkloadBuilder` 中修复，修复记录和重跑结果见
> `Zero Bubble B-W语义修复记录与后续研究报告.md`。下文其余重复结构、周期耦合和
> 对称压缩结论仍然有效；“当前不能研究 ZB”的表述应按这条勘误理解为历史限制。

## 一、结论先行

本阶段已经得到明确结论：

1. **LLM training DAG 的重复性非常高，但“重复”不等于“可以把一个周期的静态调度原样复制”。** 在 6 个可成功构建的真实 AICB/pipeline 图中，结构重复率为 94.35%--99.72%，连同时长也相同的重复率为 92.34%--99.44%；但在单 channel 投影中，约 78.65%--79.08% 的通信冲突发生在不同 micro-batch 之间，保守意义下可直接交换的任务比例为 0。
2. **简单 Independent-copy 不安全，而且误差可以随周期数持续积累。** 在严格反例中，单周期独立最优是 DP 优先，makespan 为 2；复制到 2/4/8/16 个周期后，相对最优比依次为 1.25、1.375、1.4375、1.46875，极限趋近 1.5。
3. **重复结构目前最可靠、已经严格成立的用途是对称状态压缩。** 对完全同构、无跨副本依赖的 6 个 replica，普通 Exact 搜索 18,134 个状态，压缩后只需 126 个，最优 makespan 都为 20；7 个 replica 时普通搜索 10 秒超时，压缩搜索 203 个状态、约 68 ms 得到最优值 23。
4. **边界感知规则能修复专门反例，但还不能宣称为通用 LLM 调度算法。** 在 1F1B 和 Interleaved 1F1B 的 SimAI 小图上，该规则比 Rollout-2 快很多，却比 Longest-tail/Rollout-2 差约 0.047%--0.168%。它没有满足“相对等预算 generic search 有独立收益”的退出条件。
5. **固定周期规则对时长漂移不够稳健。** 在 4 周期反例上施加 ±5%/±10%/±20% 独立扰动，边界规则的平均 gap 分别为 0.59%、1.73%、2.75%，最大 gap 约 11%--12%；Rollout-2 在这 60 个小图中均达到 Exact。因此真实运行时必须使用事件反馈和安全回退，不能只执行离线时间表。
6. **当前不能对真实 ZB 和真实 EP 作完整算法结论。** Zero Bubble builder 仍保留 `B→W` 依赖，真实图中直接 `B→W` 边有数百到上千条；现有被抽样的 EP=2 AICB 文件又出现 `dp=1`，不满足当前 rank grouper 的 `dp % ep = 0` 要求。ZB 只能用于结构对照，EP 结论目前来自合法的受控 4D 探针，不来自这些不合法的真实配置。

因此，阶段 5 的最终判断不是“周期调度已经成功”，而是：

> 应优先把 LLM 重复性用于**精确的搜索状态商化、候选去重和小窗口 teacher 加速**；若要复用调度决策，必须把 carry-in、跨周期依赖、资源冲突和 deadline/slack 纳入边界状态，并以通用 Rollout 作为回退。当前证据不支持直接复制局部顺序，也不支持用一个简单 PP 优先级替换 Longest-tail/Rollout。

## 二、研究范围与模型

本阶段研究的是独立的理想可抢占分支：

- compute 自动开始且不可抢占；
- communication 可在任务事件处暂停并保留进度；
- 单 channel 每时刻只服务一个 flow；
- 切换成本为 0、最小服务粒度为 0；
- 目标为最小化 makespan。

它不改变仓库公开的不可抢占主线语义。结果 JSON 中明确写入了上述模型，避免与主 benchmark 混淆。

## 三、L0：数据与语义审计

### 3.1 实际可扫描的 pipeline

SimAI 生成侧目前支持：1F1B、Interleaved 1F1B、Zero Bubble、Bidirectional/Chimera 和 DualPipe。本轮按照计划重点扫描前三种，另在源码审计中确认后两种具有 replica、方向和 stage sidecar，可用于下一轮扩展。

为避免导出后丢失结构，本阶段补充保留了：

```text
task_role, microbatch_id, physical_stage_id, model_chunk_id,
module_replica_id, direction, item_id, chunk_id, num_chunks,
comm_type, src, dst, size_bytes, TP/DP/PP/EP, GA
```

这些字段只在 `benchmark_generate/simai/` 使用，调度算法仍只依赖独立 benchmark/内部 DAG，不反向依赖 SimAI。

### 3.2 数据黑名单

| 数据 | 问题 | 本阶段处理 |
|---|---|---|
| Zero Bubble DAG | 基础 builder 仍建立同层 `B→W`，不符合 ZB 中 B/W 可独立就绪的目标语义 | 可做结构对照；不用于声明 ZB 调度收益 |
| 抽样 Mixtral EP=2 AICB | `tp=8, pp=2, world=16` 推出 `dp=1`，但 `ep=2`，违反 `dp % ep = 0` | 记录构图失败；另建合法 `(TP,DP,PP,EP)=(2,4,4,2)` 探针 |
| submodule 内 AICB 目录 | 只含 `.gitignore`，真实 workload 实际来自本机相邻 SimAI checkout | 报告记录文件名；实验可在无真实输入时只跑合成部分 |

## 四、L1--L2：重复结构与耦合扫描

### 4.1 三种重复率

对 micro-batch 内任务构造规范化局部签名。签名保留任务角色、phase、stage、chunk、layer、replica/direction、相对 micro-batch 依赖和前后继接口，并依次定义：

$$
R_{struct}=\frac{\#\{v: \sigma_{struct}(v)\text{ 跨至少两个 micro-batch 出现}\}}{\#\{v:mb(v)\ge 0\}},
$$

$$
R_{resource}=R(\sigma_{struct}, resource\ set),
\qquad
R_{timing}=R(\sigma_{resource}, duration).
$$

这样不会把“同一 micro-batch 内许多 TP rank 恰好相同”误报成跨 micro-batch 重复。

### 4.2 扫描范围

- 18 组 pipeline 网格：3 种 mode × `PP={2,4}` × `GA/PP={1,2,4}`；
- 3 组 TP/DP/PP 混合配置；
- 1 组合法 4D EP 探针 `(2,4,4,2)`；
- 6 个成功构建的真实 AICB/pipeline 图，任务数 4,416--25,632；
- 3 种 placement/resource 投影。

### 4.3 主要结果

| 数据组 | $R_{struct}$ | $R_{resource}$ | $R_{timing}$ | 跨 MB 依赖占比 | 跨 MB 冲突占冲突对比例 |
|---|---:|---:|---:|---:|---:|
| 22 个合成/混合图，平均 | 88.34% | 88.34% | 88.34% | 10.53% | 84.22% |
| 6 个真实 AICB 图，平均 | 97.71% | 97.71% | 96.74% | 1.19% | 78.77% |
| 真实图范围 | 94.35%--99.72% | 同左 | 92.34%--99.44% | 0.13%--2.95% | 78.65%--79.08% |

这里“跨 MB 依赖少”不能推出“MB 独立”。原因是单 channel 下所有通信互相冲突；即使没有 DAG 边，它们仍通过资源顺序强耦合。placement 探针也显示，按 TP/DP/PP 分离 fabric 后通信冲突密度从 1.0 降至 0.8286，但仍远非独立；PP/DP 共用 uplink 时为 0.8307。

合法 EP 探针含 7,168 个任务，其中 EP flow 1,024 个，结构和时序重复率均为 98.53%。这只能说明**受控固定流量下 EP 结构高度重复**；尚未覆盖 token routing 漂移。

### 4.4 可利用的规律

1. micro-batch 的节点角色和局部依赖模板高度稳定；
2. TP/EP collective 的 rank 展开制造大量标签对称性；
3. PP 的少量跨 MB 边负责传递 release，而大量无边的任务仍通过 channel/NIC 竞争；
4. warmup/cooldown 的差异集中在模板接口和跨 MB 边，不应与 steady 模板混为一类；
5. 真实图中严格 graph twin 比例为 0，说明只按“相同角色计数”合并并不安全，必须验证图自同构或使用带边界的等价关系。

## 五、L3：重复单元能否直接扩展

### 5.1 严格反例

第 $m$ 个周期含两个同时 ready 的单位通信：

```text
release_m -> PP_m -> backbone_m -> release_(m+1)
          \-> DP_m -> tail_m
```

严格写成依赖边是：`release_m→PP_m`、`release_m→DP_m`、`PP_m→backbone_m`、`backbone_m→release_(m+1)`、`DP_m→tail_m`；非首周期的 release compute 时长为 1，DP tail 时长为 1。

单周期时：

- `DP→PP`：DP tail 与 PP 重叠，makespan 为 2；
- `PP→DP`：DP tail 最后结束，makespan 为 3。

所以局部严格最优是 DP first。若把这个顺序复制到 $n$ 个周期，每个中间周期都先做 DP，因而把下一周期 release 推迟 1；实验得到：

| 周期数 | Exact/teacher | Independent-copy | 比值 | Boundary-aware |
|---:|---:|---:|---:|---:|
| 1 | 2 | 2 | 1.0000 | 2 |
| 2 | 4 | 5 | 1.2500 | 4 |
| 4 | 8 | 11 | 1.3750 | 8 |
| 8 | 16 | 23 | 1.4375 | 16 |
| 16 | 32 | 47 | 1.4688 | 32 |

事实上 $C_{copy}(n)=3n-1$，而 $C^*(n)=2n$，所以比值趋近 $3/2$。这证明“每块独立最优后复制”即使在完全相同、极小的重复结构上也会失败。

### 5.2 什么时候复制才成立

如果重复单元 $G_i$ 之间同时满足：

1. 没有跨单元 precedence；
2. 没有跨单元共享资源，或各单元固定占用互不相交资源；
3. 没有跨单元 barrier/deadline；
4. 周期结束时无 carry-in remaining work；

那么目标可分离，完整 makespan 由各资源上的独立子问题组合得到，复制局部最优不会改变其它单元的 release 或资源可行域。LLM pipeline 通常至少违反前两项，因此该充分条件只适合少量完全隔离的 replica/fabric。

## 六、L4：对称压缩与边界算法

### 6.1 对称 Exact 的正确性

设有 $k$ 个 component $G_1,\dots,G_k$，存在保持以下内容的任意 component 置换：

- 任务 kind、duration、role；
- component 内相对依赖位置；
- 无跨 component 依赖；
- 所有 communication 使用同一单 channel。

这种置换是 DAG 与转移系统的自同构。若两个状态只差 component 编号置换，则它们具有一一对应的合法 action 和相同 transition duration，后继仍处于同一等价类。由 Bellman 最优性递归归纳，两状态的最优剩余 makespan 相同。因此可将每个 component 的 runtime vector 排序后作为 quotient-state key；该压缩保持 Exact 值。

实现中先验证上述结构条件，验证失败就拒绝压缩，不做启发式猜测。

| Replica 数 | 普通 Exact 状态 | 压缩 Exact 状态 | 普通时间 | 压缩时间 | makespan |
|---:|---:|---:|---:|---:|---:|
| 3 | 66 | 16 | 约 4.9 ms | 约 2.4 ms | 11 |
| 4 | 501 | 38 | 约 54 ms | 约 6 ms | 14 |
| 5 | 3,163 | 73 | 约 0.54 s | 约 14 ms | 17 |
| 6 | 18,134 | 126 | 约 4.3 s | 约 52 ms | 20 |
| 7 | 10 s 超时 | 203 | 约 68 ms | 约 68 ms | 23 |

运行时间会随机器波动，状态数和最优值是更稳定的结论。

### 6.2 Coupling-aware 规则

受控反例上实现了最小边界规则：只要仍有后续 PP 单元未释放，优先推进能解锁下一单元的 PP；最后一个周期回退 residual Longest-tail。它在 1--16 周期反例上都达到 Exact/teacher。

但它在非量身定做的 SimAI pipeline 小图上出现负结果：

| mode | GA | Coupling-aware gap | Longest-tail gap | Rollout-2 gap |
|---|---:|---:|---:|---:|
| 1F1B | 2 | 0.168% | 0 | 0 |
| 1F1B | 4 | 0.084% | 0 | 0 |
| Interleaved | 2 | 0.075% | 0 | 0 |
| Interleaved | 4 | 0.047% | 0 | 0 |

ZB 行也有同样趋势，但因语义黑名单不用于结论。这说明“识别 PP”还不够，真实策略至少还需区分 activation/gradient、stage、phase、当前 remaining、DP slack 和 downstream join。

### 6.3 复杂度收益

在 16/32/64 周期受控图上，Coupling-aware 与 Rollout-2 makespan 相同；一次代表性运行时间分别约为：

| 周期数 | Coupling-aware | Longest-tail | Rollout-2 |
|---:|---:|---:|---:|
| 16 | 12 ms | 15 ms | 0.31 s |
| 32 | 42 ms | 51 ms | 2.35 s |
| 64 | 0.17 s | 0.24 s | 17.9 s |

因此结构规则确实能避免 Rollout 的反复完整补全，但目前只在受控 family 上保持同等解质量，尚未迁移为通用 pipeline 收益。

## 七、L5：迁移与鲁棒性

### 7.1 时长扰动

对 4 周期图中所有非零 task duration 放大 10 倍后施加独立均匀扰动，20 个 seed/幅度：

| 扰动 | Coupling-aware 平均 gap | 最大 gap | 最优率 | Rollout-2 最优率 |
|---:|---:|---:|---:|---:|
| ±5% | 0.59% | 11.07% | 85% | 100% |
| ±10% | 1.73% | 12.34% | 70% | 100% |
| ±20% | 2.75% | 12.15% | 55% | 100% |

所有策略都通过同一事件状态机生成，因而即使 profile 漂移也保持可行；差别只在 makespan。这支持“状态规则 + 回退”，不支持固定绝对时间表。

### 7.2 iteration 边界

SimAI 当前一次 AICB 展开对应一个训练 iteration/GA 集合，optimizer/post 是显式 barrier；本轮没有把完整大图复制成 epoch。由模型可知：只有在 optimizer 后所有 communication remaining 为 0、所有 compute 完成、资源空闲时，下一 iteration 才具有复位状态。若允许跨 iteration overlap，必须把 unfinished DP/optimizer slack 加入边界状态，不能沿用本轮的空状态复制。

因此本阶段对跨 iteration 的结论是条件式的：**严格 barrier 可复用策略结构；允许 overlap 时必须滚动重规划。** 真实多 iteration trace 尚未提供，不能宣称已经验证 epoch 级收益。

### 7.3 有限抢占约束

本轮状态机只实现零成本、零最小粒度的理想可抢占模型，尚未实现非零切换成本、最小 chunk 或最大抢占次数。因此“有限抢占约束下仍安全回退”的退出条件没有满足，应留给单独的模型扩展，不能从当前 preemption count 外推。

## 八、计划退出条件检查

| 退出条件 | 状态 | 证据/原因 |
|---|---|---|
| 至少 3 种 PP、3 组 GA/PP、3 组混合配置 | 完成 | 3×2×3 pipeline 网格，另有 TP/DP/PP 和 EP 探针 |
| 区分结构/资源/时序重复并自动统计 | 完成 | scanner 与 JSON 报告 |
| Exact 证明对称压缩不改最优值 | 完成 | 自同构证明；2--6 replica 数值一致 |
| 定量说明何时可复制、何时失败 | 完成 | 充分条件与趋近 1.5 的严格反例 |
| 结构算法优于等预算 generic search，或同质显著降状态 | 部分完成 | 对称 Exact 显著降状态；周期 priority 未优于 Rollout |
| 相对 Rollout-2 的独立收益出现在两种 PP/placement | 未满足 | 1F1B/Interleaved 上略差，明确负结论 |
| 时长扰动和有限抢占下安全回退 | 部分完成 | 时长扰动始终可行；有限抢占模型未实现 |

阶段可以结束，因为未满足项已经通过实验形成明确的“当前方案不成立/模型尚不支持”的结论，而不是仍缺一次相同类型的实验。

## 九、下一步建议

优先级从高到低：

1. **把对称 quotient 用进 Beam/Rollout 的 transposition table。** 这是已有严格保证且收益最大的方向，不需要冒险设计新的局部 bonus。
2. **用 Exact/Beam teacher 学 phase-conditioned 候选排序，而不是手写 PP first。** 至少加入 `(phase, PP_ACT/PP_GRAD, stage, mb offset, remaining, residual tail, DP slack, current continuation)`。
3. **只在检测到等价边界状态时启用周期缓存。** cache key 应含 ready motif counts、remaining multiset、活动 phase 和 optimizer slack；不匹配就回退 Rollout。
4. **先修复或隔离 ZB `B→W` 语义，再比较 ZB。** 否则结构算法无法利用真正的 W 延迟自由度。
5. **获得合法的 EP trace。** 需要 `dp % ep = 0` 且包含随 iteration 变化的 token/bytes；比较复用策略结构与复用固定时序的差别。
6. **新增有限抢占状态机。** 显式加入 switching cost、minimum quantum 和 preemption budget，再检查结构策略的摊销收益。

不建议下一步继续堆叠简单角色优先级。现有结果已经说明，LLM 标签最有价值的地方是识别严格对称和缩小搜索，而不是直接代替端到端评价。

## 十、产物和复现

代码：

- `benchmark_generate/simai/repetition.py`：结构、资源、时序重复和耦合扫描；
- `benchmark_generate/simai/repetition_study.py`：完整实验入口；
- `src/preemptive/repetition.py`：复制反例、边界规则、对称 Exact；
- `tests/preemptive/test_repetition.py`：正确性与回归测试。

原始结果：`docs/preemptive研究/preemptive阶段5_实验结果.json`。

复现命令：

```powershell
$env:PYTHONPATH="src;."
$env:SIMAI_FLOW_SCHEDULER_ROOT="D:\Code\SimAI\simai-flow-scheduler"
python -m benchmark_generate.simai.repetition_study `
  --aicb-root "D:\Code\SimAI\simai-flow-scheduler\inputs\aicb-workload" `
  --output "docs\preemptive研究\preemptive阶段5_实验结果.json"
```

不提供 `--aicb-root` 时仍可完成合成网格、反例、压缩、pipeline probe 和扰动实验，只跳过真实 AICB 行。
