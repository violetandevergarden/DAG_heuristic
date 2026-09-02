# Stage 4d 有效 selective rollout：代码实现结果

日期：2026-09-01

## 1. 实现范围

本轮只修改不可抢占 Stage 4d 模块与离线实验入口，没有修改公共模拟器、Exact、loader、schema、benchmark，也没有修改可抢占实现。

稳定代码位于 `src/llm_structured/nonpreemptive/selective_rollout/`：

- `cheap_policies.py`：在完整合法动作空间上分别计算 residual LT、FIFO、固定顺序、SPT、LPT、单通道 release-fit 和多资源 hotspot 的首动作；
- `features.py`：实现 v2 特征合同，保存 `policy_name -> ActionSignature`，LT 分差只比较可启动通信；记录关键释放、释放收益差异、WAIT 条件和资源脚印差异；
- `evaluator.py`：复用 feature lookahead 已执行的首层 transition；
- `triggers.py`：保留旧失败触发器，并新增 C1 策略分歧、C2 宽松组合和 C3 严格组合；
- `contracts.py`：特征和候选版本升级到 v2，决策记录增加可审计特征；
- `adapters.py`：只增加只读的下一事件、ready communication 和固定资源查询，所有动作仍由原不可抢占模拟器执行。

`legacy_failed_trigger_v1` 被单独保留，没有与新触发器混表。

## 2. 实验入口

新增：

- `experiments/llm_structure/nonpreemptive/stage4d_effective_selective.py`：沿冻结 LT 轨迹连接 Exact 标签，输出候选召回和七类单特征统计；
- `stage4d_effective_summary.py`：合并冻结 holdout 与匹配预算对照；
- `stage4d_evaluate.py --split`：允许只运行冻结 split，不改变原有默认行为；
- `effective_validation_configs.json` 与 `effective_holdout_controls.json`：保存 C1--C3 和 H2/H4/H5 配置。

结果归档：

- `stage4d_effective_selective_features_20260901/`：配置 hash、逐决策特征、候选召回、单特征统计和 Stage 4a LT 对拍；
- `stage4d_effective_selective_validation_20260901/`：H0/H1 与 C1--C3 的逐样例结果；
- `stage4d_effective_selective_holdout_20260901/`：冻结 holdout 对照、逐样例结果与汇总。

## 3. 语义保证

- 单通道动作仍是完整 `FLOW` 或合法 `WAIT`；
- 多资源动作仍是保留 active reservation 后的完整新启动集合或合法 `WAIT`；
- work-conserving 不生成主动 WAIT；
- feature transition 和 rollout completion 分别计数；
- evaluator 复用首层 feature transition，不重复推进；
- timeout、fallback、unknown 均保留；本轮端到端 750 + 42 行全部 completed，fallback 为 0；
- H7 只保留为离线 Exact 标签上限。LT 轨迹标签无法在动作偏离后定义可部署的端到端 oracle，因此没有伪造 H7 schedule。

## 4. 验证

- Stage 4d 专项测试：10 passed；新增覆盖候选不同但策略一致、FIFO/LT/SPT 真实分歧和 feature transition 计数/复用；
- 当前 Stage 4a `real_small.jsonl` 含 30 个样例，因此实际可重跑对拍为 60 个 mode-row，不是续研方案沿用旧口径写出的 76 行；结果为 makespan 60/60、trace hash 60/60 一致；
- 未改公共执行语义，因此不重新生成 reference result。

## 5. 已知边界

关键释放特征只使用一次合法完整 transition 后可观测到的 ready communication 与固定资源交集，不尝试在算法层复制事件推进。join/barrier 的静态缺口没有另建第二套状态机。这样保证语义单一，但也使该信号在旧图上很稀疏。

