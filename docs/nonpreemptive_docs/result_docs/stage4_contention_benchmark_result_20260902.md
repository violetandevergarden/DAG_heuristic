# Stage 4 冲突 Benchmark 审计结果

日期：2026-09-02

## 实现与数据分层

- source 选择不再只取最小配置，候选上限为 32 个 source 加两个固定 topology 投影；明确保留 GA=1 负对照，并覆盖 GA 4/8、PP 1/2/4 和 Mixtral EP 1/2/4/8。
- contention audit 新增 SPT、LPT、固定 seed 随机策略，与 FIFO、固定顺序和 residual LT 一起记录；同时给出动作、策略、状态三层冲突计数。质量冲突若未计算，明确写 `not_run`。
- 自然真实、真实组合和受控投影使用独立来源字段；本轮没有发布新的正式 corpus，也没有修改现有 benchmark/index/reference result。

## 小图 census

对当前 real-derived 目录全部 26 个图执行至多 128 个决策的轻量审计：

- 24/26 个图观察到动作冲突；共 149 个状态；
- 24/26 个图观察到简单策略分歧；共 74 个状态；
- 24/26 个图观察到非等价 immediate successor；共 149 个状态；
- census 本身没有重新求 Exact Q-value，因此质量冲突字段为 `not_run`。

已有、且内容哈希仍对应的 real-small Exact 标签可作为独立质量证据：243 个标签中 94 个标签、覆盖 23 个 benchmark，存在非零 action cost spread，最大 spread 为 3636；但 residual LT regret 为正的标签数为 0。也就是说，这些真实派生小图存在“动作质量不同”，却没有证明 LT 在这些状态犯错。

## 准入判断

- 4b：可进入“为什么有选择但 LT regret 为零”的结构解释。
- 4c：尚未形成足够的真实 routed active-reservation 集合分歧覆盖，不重新开放复杂 packing。
- 4d：真实小图 LT regret 仍为零，不重新训练 selective trigger。
- 4e：继续仅保留 barrier 作为 LT 修正/触发信号，不恢复 barrier-only。
- 4f：已有真实派生 WAIT 正例，可优先继续 arrival、JCT 和 starvation；但本轮未生成新的 2/4-job 比例错峰 corpus。

P3/P4 的全部退出条件尚未满足：没有新自然中图的冻结 completion value spread，也没有通过保持首动作排序验证的新 residual decision window。因此不进入 Stage 4g，不宣称已得到真实中图最终算法。

