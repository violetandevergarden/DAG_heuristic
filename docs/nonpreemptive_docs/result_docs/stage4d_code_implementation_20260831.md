# Stage 4d 不可抢占 Selective Rollout 代码实现结果

日期：2026-08-31

## 1. 实现结论

已新增语义专属的不可抢占 selective rollout 实现。实现不修改公共模拟器，不自行推进时间；单通道完整通信、合法 WAIT、固定多资源启动集合和 active reservation 均通过现有不可抢占模型的 `legal_actions` 与 `step` 执行。

旧 R3 rollout 保持原样，继续视为 `legacy_r3_full_rollout`，没有改名为 Stage 4d 正式算法，也没有把事后“与完整 LT 取较小值”的保护带入新实现。

## 2. 代码布局与职责

正式实现位于 `src/llm_structured/nonpreemptive/selective_rollout/`：

- `contracts.py`：动作摘要、配置、预算账本、触发结果、决策记录和最终结果；
- `adapters.py`：单通道与固定多资源模拟器的薄适配，只转发合法动作和状态转移；
- `baseline.py`：与 Stage 4a 对拍的 residual LT 及版本化 WAIT 规则；
- `candidates.py`：稳定去重、包含 LT、受宽度限制的候选动作；
- `features.py`：LT 分差、策略分歧、时长差异、跨事件和 WAIT 等特征；需要执行转移的特征计入预算；
- `triggers.py`：full、selective、random、periodic 和关闭触发；
- `evaluator.py`：按完整启动决策层定义 depth 0/1/2，统一 completion policy、缓存和预算；
- `exact.py`：从模拟器产生的 residual state 求最优 cost-to-go，返回 optimal 或 unknown；
- `policy.py`：端到端调度、回退、逐决策记录、trace hash 和成本统计。

实验入口位于 `experiments/llm_structure/nonpreemptive/`：

- `stage4d_manifest.py`：生成旧图、真实小图和真实中图冻结清单；
- `stage4d_baseline_pairing.py`：与 Stage 4a LT 对拍；
- `stage4d_labels.py`：生成两种动作口径的决策级 Exact 标签；
- `stage4d_decision_analysis.py`：汇总 known、unknown、LT regret；
- `stage4d_evaluate.py`：用独立子进程执行小图配置；
- `stage4d_medium_check.py`：执行 30 秒 pilot 和 90 秒逐例预算闸门。

`src/` 不导入实验模块，实验层也不依赖 SimAI 运行算法。

## 3. 关键合同

### 3.1 动作与深度

- 单通道动作是 `FLOW(task_id)` 或下一真实事件的 `WAIT`；一个 FLOW 始终连续运行到完成。
- 多资源动作是排序后的 `START(task_ids...)` 或 `WAIT`；进入下一层后仍运行的通信继续占用原资源。
- depth 按通信启动决策层计数。depth 1 为完整首动作加 LT 补全；depth 2 在下一有选择状态再次分支。
- evaluator 并列时保留 LT；任何候选估值未完成时当前决策回退 LT。

### 3.2 预算

共享账本限制候选数、触发次数、completion calls、展开状态、特征转移、缓存项、每决策和每实例软时间。实验层另用独立子进程提供硬墙钟上限。硬超时不会被内部 fallback 改写为 completed。

### 3.3 基线对拍

首次实现遗漏了 Stage 4a optional-idle LT 的 WAIT 规则，曾在一个真实 multi-job 小图上产生 829 tick 的伪收益。发现后已修正并覆盖全部标签和实验结果。

修正后，Stage 4d depth 0 LT 与 Stage 4a 归档的 76 条 `longest_tail × mode` makespan 和 trace hash 均为 76/76 一致。该事故及修正说明：Stage 4d 结论必须建立在基线动作口径对拍后，不能只比较算法名称。

## 4. 测试

新增专项测试覆盖：

- depth 0、候选宽度和 completion 预算；
- work-conserving 有可启动动作时不选 WAIT；
- 多资源 active reservation 与兼容性；
- depth 2、并列保留 LT、随机触发可复现；
- 从 initial/residual state 调用 Exact cost-to-go。

最终定向测试为 48 passed（原 47 项回归与集成测试，加 1 项 residual Exact 专项测试）。没有修改公共模拟器、loader、schema 或既有 Exact，因此未因本阶段实现触发全仓公共语义迁移。

## 5. 已知限制

- 当前透明 selective 组合过宽，在旧图和真实小图上的 completion calls 与 full 相同，尚未形成有效成本筛选器。
- 候选源完成了 LT、FIFO/固定顺序近似、SPT/LPT、合法 WAIT 和多资源合法集合覆盖，但尚未接入未来 Stage 4c 的专门 packing 候选。
- 缓存有条目和命中记录，但当前小图配置主要在 depth 1，缓存收益不明显。
- 实现适合作为可审计的离线分析和后续触发器研究基础；当前证据不支持注册为默认公共算法。
