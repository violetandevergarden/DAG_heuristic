# Stage 2 一般 DAG 第二轮代码修正结果（2026-08-16）

## 完成项

1. `schedule_rollout` 改为缓存 residual completion cost，key 为 `(remaining_depth, normalized_state_key)`；新增 memo hit、memo states 统计和 `use_memo` 消融开关。
2. Longest-delay 改为最长立即释放 compute delay；原总新增 ready work 独立为 `release_gain`。
3. Exact 增加 `none/P/L/max(P,L)` bound 模式、memo 开关和 initial-incumbent 开关；所有模式仍复用公共 simulator。
4. 新增 barrier urgency、shared-downstream 去重、downstream communication demand 及实验组合；表现不佳的结构组合未加入稳定 registry。
5. layered generator 增加 `barrier_every` 与 `alternating_layers`，用于运行时参数化压力实验，不向仓库无限增加固定 JSON。
6. 新增 Stage 2 primal/scaling runner；Beam teacher 搜索器转为历史实验工具，不再属于活跃退出条件。
7. registry 新增 `downstream_demand`，明确标注“mean 改善、observed worst 变差”；Beam-8/32 标为 `experimental`、仅实验上界/对照、非部署候选。

## 主要文件

- `src/single_channel/complex_chain/preemptive/solver.py`
- `src/single_channel/complex_chain/preemptive/interface.py`
- `src/registry.py`
- `benchmark_generate/cases.py`
- `experiments/preemptive/stage2_complex_chain.py`
- `experiments/preemptive/stage2_scaling.py`
- `experiments/preemptive/stage2_beam_counterexample_search.py`
- `tests/single_channel/complex_chain/preemptive/test_algorithms.py`

## 回归验证

完整测试为 `117 passed in 43.75s`。新增测试覆盖：delay/release-gain 首选差异、rollout memo on/off 等价与实际命中、shared node 去重、barrier feature 可观察性、四档 Exact bound 与 memo/incumbent 消融保持独立 Oracle 最优值。

## Beam 边界

Beam-8 固定宽度反例没有穷尽，但该项不再是 Stage 2 退出条件。Beam 只作为实验上界/对照，不是部署候选，不主张鲁棒性；没有把 Exact timeout 的可行 incumbent 标成最优反例。
