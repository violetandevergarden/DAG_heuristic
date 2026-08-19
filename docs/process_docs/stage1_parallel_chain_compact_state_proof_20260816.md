# Stage 1 compact frontier state 的 future-equivalence 证明草稿

日期：2026-08-16

## 1. 结论

对严格独立交替链、task-event 决策、communication 零开销暂停/恢复、compute 自动且不可抢占、单 channel work-conserving、目标为 makespan 的 Stage 1 模型，在任一稳定决策事件上，每条链的

$$
(\text{frontier position},\ \text{frontier remaining work})
$$

与静态链定义共同构成无损状态。两个状态若该向量相同，则它们具有一一对应的合法未来调度，且对应调度的 residual makespan 相同。绝对时间只产生整体平移。

## 2. 依赖的假设

证明只在以下条件同时满足时成立：

1. 输入是若干互不依赖的简单路径；每条路径严格 compute/communication 交替；
2. 依赖是 finish-to-start；
3. compute ready 后立即启动，跨链无限并行，一旦启动不可暂停；
4. communication 只有一个固定单位容量 channel，任一时刻至多服务一个；
5. communication 可在 task event 暂停/恢复，已完成工作守恒；
6. 抢占、恢复和切换开销为零，没有 minimum quantum；
7. 有 eligible communication 时禁止主动 WAIT；
8. duration、依赖和资源集合静态，调度目标只依赖最终完成时间；
9. 算法不以首次 eligible 时间、历史抢占次数或 task metadata 改变 Exact 的可行动作或目标。

若引入非零恢复开销、history-dependent objective、动态路由、job JCT/fairness、跨链边或主动 WAIT，该 key 不再由本文保证无损。

## 3. 单链前缀性质

对任一严格路径 $P=(v_1,\ldots,v_n)$，finish-to-start 依赖保证已完成任务必为一个前缀。设第一个未完成任务为 $v_i$：

- 若 $v_i$ 是 compute，则公共 simulator 的自动闭包保证它已经 running；其未来只需要 remaining work；
- 若 $v_i$ 是 communication，则其前驱已经完成，所以它是 pending-eligible 或 suspended-eligible；零恢复开销下这两个历史状态的未来服务要求都只等于 remaining work；
- $v_{i+1},\ldots,v_n$ 均尚未开始，其 kind、duration 和顺序由静态链定义确定；
- 若不存在 $v_i$，链已经完成，用终止 position 和 remaining=0 表示。

因此单链不需要保存完整 task status 数组、started timestamp、completed timestamp 或“该 communication 是否曾运行过”。

## 4. 单步转移由 compact state 唯一确定

给定所有链的 frontier 向量：

1. frontier 为 communication 的链恰好给出当前 eligible 集合；
2. frontier 为 compute 的链恰好给出当前 active compute 集合；
3. 若 eligible 非空，合法动作恰好是选择其中一个 communication；否则若存在 active compute，唯一合法动作是 forced idle；
4. 选择 communication $c$ 后，下一个事件间隔为 $c$ 的 remaining 与全部 active compute remaining 的最小值；forced idle 时为 active compute remaining 的最小值；
5. 从所有 active compute 和所选 communication 的 remaining 中减去该间隔；完成的 frontier 向后推进，并递归执行零时长 compute 自动闭包。

以上每一步只使用 compact vector 和静态链，不读取被删去的历史字段。因此相同 compact state 的两个完整 simulator state 有相同动作集合；对任一对应动作，经过相同 residual 时间后到达相同 compact successor。

## 5. Future-equivalence

对未来决策步数归纳。

- 基础情形：全部链到达终止 position 时，两状态均完成，residual makespan 为 0。
- 归纳步骤：由第 4 节，两状态合法动作集合相同；每个动作的 elapsed 相同，successor compact state 相同。由归纳假设，从 successor 开始的全部未来调度及 residual cost 一一对应。因此当前状态的全部 action path 及总 residual cost 也一一对应，最优 residual makespan 相同。

绝对时刻 $t$ 不进入 transition duration 或合法动作判定。若两个等价状态绝对时间相差 $\Delta$，任一对应 suffix 的完成时刻也只相差 $\Delta$；其 residual cost 相同。这证明 Exact memo key 可以省略绝对时间。

`last_communication` 也不影响结论，因为当前模型没有切换/恢复开销，公共 simulator 不以它限制合法动作。

## 6. 同构链对称压缩

若两条链的完整 `(kind, duration)` 序列相同，交换两条链的身份是实例的自同构：依赖、资源、合法动作和每个 transition duration 均保持不变。因而同一类型链的 frontier state 可以按 multiset 排序，而不按原 chain index 保存。

canonical key 只用于 residual optimal cost DP。不能直接复用某个 canonical representative 的 task-ID suffix，因为另一个排列下这些 ID 可能不是合法 frontier。当前实现因此分两步：

1. 在 canonical multiset key 上只求最优 residual cost；
2. 从真实初始 state 出发，对当前实际合法 task ID 逐步寻找满足

   $$
   \Delta(s,a)+V(K(f(s,a)))=V(K(s))
   $$

   的动作并回放。

这样既利用对称 cost equivalence，又保证最终 action path 对实际 simulator state 合法。最终 trace 仍由公共 simulator 生成，并由独立 validator 回放。

## 7. Beam 的时间支配

Beam 使用未做链身份置换的 ordered compact key。若两个 prefix 到达相同 ordered key，但绝对时间分别为 $t_1<t_2$，第 5 节表明任一 suffix 的 residual cost相同，因此从 $t_1$ 出发的完成时刻严格不晚于从 $t_2$ 出发。保留较早 representative 是安全的时间支配剪枝；只有在绝对时间相等时才使用 action signature 取得确定性 representative。

注意：这只证明同 key 内的支配删除安全，不证明固定 beam width 丢弃不同 key 时仍保持最优。

## 8. 验证证据与证明边界

形式证明之外，仓库测试还执行：

- 200 个固定 seed 严格交替小图：compact Exact、未压缩通用 event Exact、独立 tick Oracle 三方一致；
- communication/compute 任意起止、零 compute、同时事件和暂停/恢复回放；
- 对称链实例：启用/禁用 symmetry reduction 的 makespan 一致，启用后 explored states 严格减少；
- 所有 Exact action path 通过独立 trace validator。

这些对拍是实现证据，不替代上述 future-equivalence 证明；证明也不替代对代码错误的回归测试。
