# Stage 4c 不可抢占冲突图与启动集合：代码实现结果

## 1. 实现范围

本次实现只处理不可抢占固定多资源状态中的“新启动集合”。已经运行的 communication 始终由公共模拟器保留到完成，packing 代码无权停止或替换它。实现没有修改可抢占 packing，也没有引入新的时间推进逻辑。

主要代码位于：

- `src/llm_structured/nonpreemptive/packing/`：不可抢占 Stage 4c 专属实现；
- `src/muti_channel/nonpreemptive/solver.py`：补充非枚举式动作查询和校验接口；
- `experiments/llm_structure/nonpreemptive/stage4c_evaluate.py`：可复现实验及外部硬超时；
- `tests/llm_structured/nonpreemptive/packing/test_stage4c_packing.py`：Stage 4c 专项测试。

## 2. 公共模拟器接口

`NonPreemptiveMultiResourceDAG` 新增四个接口：

- `startable_flows`：返回 ready 且不与 active reservation 冲突的 communication；
- `has_future_event`：判断 WAIT 是否能到达真实运行任务完成事件；
- `is_maximal_start`：线性检查新启动集合是否为包含意义下的极大集合；
- `validate_action`：按 optional-idle 或 work-conserving 口径校验一个给定动作。

这些接口不调用 `start_subsets`，因此中图动作校验不需要指数枚举。原 `legal_actions`、`step` 和 Exact 动作空间未改变。小图测试逐项对拍了新校验接口与原完整枚举。

## 3. Packing 实现

### 3.1 冲突图

冲突图先删除与 active reservation 冲突的 ready communication，再以资源到任务的倒排表生成边。快照记录 vertices、edges、active、occupied resources、blocked-by-active、密度、最大度、连通分量及截断状态。active communication 从不成为候选顶点。

### 3.2 候选构造

实现了固定顺序、FIFO、residual LT、长/短 duration、热点、冲突度和固定 seed 随机顺序补全；在 LT 集合上实现有界一换一和一换二；optional-idle 另加入合法 WAIT 和 LT 非极大前缀。所有集合规范化、去重，并保留 LT 合法回退动作。

### 3.3 整集合特征

集合特征使用资源并集、下游可达任务并集、下一事件实际释放并集、被排除任务的最大 tail、完整 duration、启动后 active 数及留空资源。共享后继只计一次。下一事件状态只能通过公共 `step` 获得。

### 3.4 选择与预算

提供静态整集合词典序选择和有限完整动作加 LT 后缀选择。每决策预算覆盖 packing 操作、交换、下游访问、候选数、completion call 和软时间；预算未能完整评价全部候选时回退 LT。完整日程实验另由父进程实施硬墙钟超时。

## 4. 测试与检查

- Stage 4c 与不可抢占多资源定向测试：`21 passed`；
- 新代码 Ruff：通过；
- 全仓测试：`233 passed, 2 failed`，耗时 114.50 秒。

两个全仓失败均来自 `tests/test_semantics_layout.py` 中固定写死的旧数量 `243`，而当前 Stage 4a 已发布 benchmark 与 `benchmark/index.jsonl` 均为 `281`。两项断言都观察到 281，未出现索引与文件数量不一致；该失败与本次 Stage 4c 代码无关，本次没有为通过测试而改写用户的 Stage 4a benchmark 或布局测试。

## 5. 已知实现边界

- 当前集合静态评分是研究用候选，不注册为默认公共算法；
- optional-idle 静态评分不会把 WAIT 当作默认动作，WAIT 只有经完整动作反事实才可能被选择；
- P4 与 Stage 4d rollout 成本接近，只保留为小图分析接口；
- 当前没有从两个 routed 中图成功提取保持多资源选择的正式 real-derived slice；
- 实验脚本属于过渡性入口，`src/` 不导入它。

