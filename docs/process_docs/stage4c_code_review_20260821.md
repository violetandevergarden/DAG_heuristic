# Stage 4c 固定多资源冲突图打包代码审查

## 1. 审查范围与结论

本审查依据 `docs/plan_docs/stage4_LLM_search.md` 和 `docs/plan_docs/stage4c_conflict_graph_packing.md`，检查当前固定多资源冲突图与兼容集合选择实现。用户任务中的“stage4a 代码”按上下文解释为 Stage 4c 代码；Stage 4a 仅作为真实输入准入边界检查。`docs/old_docs/stage4研究` 中的旧审查用于定位历史问题，不作为当前结论依据。

总体判断：**当前实现只完成了合法极大集合、确定性 Longest Tail 贪心、候选生成骨架和六个受控 motif 的最小验证；没有满足 Stage 4c 的阶段退出要求，状态应为“开发中”。** 旧审查指出的三个最高风险问题仍存在：高级构造器生成的候选没有在非 rollout 模式下被选择执行；有界枚举仍先全量枚举；完成评估预算仍可能越界。

本次未修改代码或实验结果，只记录审查结论和修正建议。

## 2. 已核对资产

- 动作与冲突图：`src/muti_channel/preemptive/packing.py`
- 多起点、一次交换和枚举：`src/muti_channel/preemptive/constructors.py`
- 调度、集合评分、Exact：`src/muti_channel/preemptive/solver.py`
- 结构特征：`src/llm_structured/packing_features.py`
- 受控样例：`benchmark_generate/llm/packing_motifs.py`
- 实验入口：`experiments/llm_structure/packing_evaluation.py`
- 相关测试：`tests/muti_channel/preemptive/`、`tests/llm_structured/test_packing_features.py`
- Stage 4a 活动 manifest 与历史 Stage 4 研究记录

验证结果：

- 定向测试：4 passed；
- 完整测试：175 passed，耗时 129.48 秒；
- 六个 motif 的轨迹验证均通过，Exact 均返回 optimal；
- `path_future_value` 和 `exchange_repairs_lt` 中，Longest Tail 贪心 makespan 为 16，带深度一完成评估的多起点方法为 14；非 rollout 的多起点、交换和枚举仍为 16。

实验模块在未设置项目源码路径时会因 `from benchmark import load_benchmark` 导入失败；设置 `PYTHONPATH=src;.` 后可以运行。这表明实验入口的独立可运行性也尚未冻结。

## 3. 已基本满足的部分

### 3.1 动作合法性骨架

`validate_maximal_action` 检查动作非空、任务有资格、稳定排序、无重复、资源不冲突和包含极大性。`complete_maximal` 会按同一顺序补全到极大集合。冲突图只基于当前 eligible communication 和固定资源交集建立，符合当前状态冲突图的定义。

### 3.2 公共模拟器边界

构造器只读取状态并返回动作，时间推进仍由 `PreemptiveMultiResourceModel.step` 完成。实验中的轨迹使用公共验证器检查。现有小图测试支持“未另造状态转移”的判断，但尚没有覆盖 Stage 4c 计划列出的全部暂停、零时长闭包和预算失败路径。

### 3.3 最小受控样例

现有六个 motif 覆盖团、空冲突图、宽通信与窄通信组合、路径、一次交换和多资源热点等部分机制，并能用 Exact 核对最终 makespan。这些样例适合作为回归材料，但不能替代随机小图、真实切片或真实 holdout。

### 3.4 基于剩余状态的基础评分

Longest Tail 评分由当前模拟状态计算。`packing_features.py` 的冲突数量、密度、最大度、资源数量和资源脚印也来自当前 eligible 集合，没有直接读取答案或 reference result。现有特征仍很有限，尚未形成计划要求的完整 residual 集合评分。

## 4. 必须修正的实现问题

### 4.1 高级构造器的候选没有在非 rollout 模式下被执行

`multi_seed`、`one_exchange` 和 `enumerate_bounded` 都将 `PackingResult.selected` 设为 Longest Tail 贪心 baseline。`schedule_bounded_packing` 默认直接执行 `packed.selected`，只有 `rollout=True` 才在候选间选择。因此：

- `lt_multi_seed`、`lt_exchange`、`lt_enumeration` 实际执行同一基线；
- 当前实验不能比较三个构造器的调度质量；
- motif 名称 `exchange_repairs_lt` 不能证明“一次交换本身修复 LT”，实际改进来自额外的完成评估；
- `evaluated_candidates` 只是生成候选数，不代表候选被评分或执行。

这与计划要求的“候选生成与候选评分分离”和“逐层评价构造器”不符。

### 4.2 `max_sets` 不是生成过程的硬上限

`enumerate_bounded` 先调用 `model.maximal_actions(state)` 生成全部极大动作，再对结果切片。候选数量呈指数增长时，时间和内存已经在切片前消耗。`b_pack`、`time_limit_s` 也没有参与此枚举过程。因此它不是计划要求的“有界极大集合枚举”，大图上可能失控。

### 4.3 `b_eval` 不是严格预算

外层只检查 `calls < budget.b_eval`，随后 `choose_by_depth1_longest_tail` 会一次完成 baseline 和全部替代候选的模拟。若剩余预算小于候选数，完成调用数会超过 `b_eval`。该函数也不接收共享截止时间，不能在候选之间按墙钟停止。

### 4.4 时间预算只约束部分构造路径

`time_limit_s` 只在多起点和交换循环的若干位置检查；贪心补全、全量枚举、候选完成模拟和整图调度没有共享墙钟限制。达到时间预算后也没有统一状态字段。因此不能支持“单决策和整图墙钟预算严格受控”的结论。

### 4.5 零预算与统计语义不完整

当 `max_sets=0` 时，多起点构造会在加入 baseline 后才判断集合预算，候选数仍可为 1；枚举构造则回退到 baseline。行为可保持合法，但“禁用额外候选”和“预算耗尽”的含义没有统一。`planner_triggered=int(calls > 0)` 仍是布尔值，不是触发次数；构造耗时、操作数、交换数、逐次 fallback 原因没有汇总到 `MultiResult`。

### 4.6 fallback 原因没有完整上传

`PackingStats` 记录局部原因，但 `schedule_bounded_packing` 只累加 `budget_exhausted`，没有把具体原因传到最终 `fallback_reason`，也没有区分每个决策的回退。实验结果只保存 `fallback_count`，无法判断是集合数、构造操作、时间还是评价预算耗尽。

### 4.7 实验入口仍是旧编号和旧口径

模块说明、输出 schema 仍写作 `Stage 4f` / `stage4f-packing-v1`，与当前正式 Stage 4c 编号不一致。实验只比较 LT 系列，没有固定顺序、FIFO、随机补全；没有输入 hash、代码版本、环境、完整预算配置、超时状态和逐决策动作。直接从仓库运行还依赖手工设置 `PYTHONPATH`。

### 4.8 真实样例选择没有遵守 Stage 4a 竞争准入

runner 仅按 `scenario == "muti_channel"` 和 manifest 顺序取前 N 个样例，没有检查转换状态、竞争审计等级、是否存在多个极大集合、策略是否分歧，也没有按模型、topology、DP/TP/PP、规模分层。Stage 4a 当前大量样例仅有 sampled prefix 证据，因此不能将其直接称为正式 Stage 4c 质量集。

### 4.9 真实回放缺少统一硬预算

真实分支直接完整运行 `schedule_pack` 和 `schedule_bounded_packing`，没有墙钟、内存或任务规模保护。Stage 4a 已证明大图完整回放可能远超名义预算，因此该 runner 可能在遇到大图时长时间阻塞，也不能如实生成 timeout/fallback 行。

## 5. 测试和研究证据缺口

现有测试主要证明基本合法性和代码自洽，缺少：

- 非 rollout 构造器实际执行不同于 baseline 的动作；
- 流式枚举达到 `max_sets` 后立即停止；
- `b_eval`、操作数和墙钟在任何路径都不超限；
- 单 channel 退化、暂停恢复、零时长释放和 forced idle 的 Stage 4c 专项回归；
- 随机小冲突图的全部极大集合交叉验证与候选覆盖率；
- 每个极大首动作的 Exact 后续值与并列最优首动作集合；
- 共享下游重复计分、热点误导、频繁抢占、极大但非最大数量等完整反例；
- 固定顺序、FIFO、LT、随机、多起点、交换和集合评分的正交消融；
- 真实切片、中型真实 holdout、大图成本与内存报告。

六个 motif 中两个 16 到 14 的改善只能说明“候选加完整 LT 完成评估在这两个开发样例上有效”。不能推出多起点、交换或枚举独立有效，也不能推出真实 LLM DAG 上有收益。

## 6. 对十二项退出条件的判断

| 退出条件 | 判断 | 主要依据 |
|---|---|---|
| 1. 动作契约与公共模拟器一致 | 部分满足 | 基本合法性和小图 trace 已覆盖；专项事件边界仍不完整 |
| 2. 构造器合法、确定、只读且预算降级可靠 | 未满足 | 枚举和评价不是硬预算，零预算语义不统一 |
| 3. 小图枚举、模拟器与 Exact 交叉验证 | 部分满足 | 六个 motif 有最终 Exact；缺全首动作值、随机图覆盖和截断验证 |
| 4. 正式真实输入按竞争证据和规模分层 | 未满足 | runner 只按 manifest 顺序取前 N 个多资源样例 |
| 5. 固定顺序、FIFO、LT 与候选统一对照 | 未满足 | 当前仅 LT 派生项，且非 rollout 高级项实际等同 LT |
| 6. 生成与评分贡献通过覆盖率和消融分离 | 未满足 | 没有候选覆盖率和正交消融 |
| 7. 真实 holdout 收益和退化报告 | 未满足 | 无冻结 holdout 和正式结果 |
| 8. 质量与完整成本指标共同报告 | 未满足 | 缺内存、利用率、forced idle、区间数和逐资源指标等 |
| 9. 主要失败模式有反例分析 | 部分满足 | 有宽对窄、路径、交换、热点雏形；共享下游和抢占退化等缺失 |
| 10. 明确适用范围 | 未满足 | 没有真实分层证据可支持范围结论 |
| 11. 形成稳定正面或否定结论 | 未满足 | 当前仅开发 motif 观察 |
| 12. 合格组件才进入 Stage 4g | 未满足 | 现有候选组件尚未达到准入标准 |

没有任何一项足以支持 Stage 4c 结束；第 1、3、9 项仅部分满足，其余未满足。

## 7. 可安全保留与不能引用的结论

可以保留：

- 固定资源冲突图与包含极大动作的基本数据结构；
- 确定性 Longest Tail 顺序贪心 baseline；
- 六个 motif 及其 Exact/trace 回归价值；
- “同一个当前冲突图不足以单独决定长期最优集合”的研究方向；
- 两个 motif 上完整 LT 完成评估可把 makespan 从 16 降到 14 的限定观察。

不能引用：

- 多起点、一次交换或有界枚举在非 rollout 模式下优于 LT；
- `max_sets`、`b_eval` 或 `time_limit_s` 已构成严格预算；
- 复杂 packing 在真实 72-case corpus 上有效或泛化；
- 当前真实 runner 已建立公平、分层、可复现的 Stage 4c 对照；
- Stage 4c 已完成，或其组件可直接进入 Stage 4g。

## 8. 最终结论

现有 Stage 4c 代码是一个可继续修正的研究原型，不是已验收算法。最优先工作不是扩大实验，而是修正候选选择契约、流式有界枚举和共享预算记账；随后补齐小图首动作真值及 Stage 4a 竞争分层，最后才运行真实 holdout、消融和成本实验。旧审查中的核心风险截至本次检查仍未关闭。
