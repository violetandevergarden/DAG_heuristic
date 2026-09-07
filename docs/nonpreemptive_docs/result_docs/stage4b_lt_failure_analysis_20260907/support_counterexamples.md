# Stage 4b：LT 特征支持例与反例

日期：2026-09-07

本文只解释本轮冻结状态中的条件补全结果。`conditional_improvement` 表示：在同一个 LT 可达状态更换一个完整动作，之后恢复冻结 LT，最终 makespan 小于原 LT 完整回放。它不是全局最优证书。

## 1. Tail 相对差距

支持例：`np_stage4f_gpt13_two_hom_50pct`，optional-idle，决策 598。挑战动作为 LT 第二名，条件改善 84,411 us；两动作 tail 打平，持续时间比约 30.18。该例说明 tail 相同不能保证完整启动动作等价。

反例：`np_stage4f_alibaba_slice_heter_1pct`，optional-idle，决策 13。tail 相对差距为 0，LT makespan 为 613,088 us，最好挑战为 613,089 us，LT 仍好 1 us。全部可评价状态中，tail 差距不超过 0.15 的状态有 413 个，其中仅 22 个可修复、55 个挑战更差、336 个平局。小差距适合作为扩大候选的过滤条件，不能直接触发换动作。

另一个边界是 `np_stage4f_gpt13_gpt7_sim` optional-idle 决策 143：tail 相对差距约 0.186，挑战仍改善 1,678 us。因此 0.15 不是完整覆盖阈值。

## 2. 完整通信持续时间差异

支持例仍为 `np_stage4f_gpt13_two_hom_50pct` optional-idle 决策 598：持续时间比约 30.18，LT 第二名挑战改善 84,411 us。

反例：`np_stage4f_cassini_slice_heter_1pct` optional-idle 决策 14，持续时间比为 2，最好挑战反而使 makespan 增加 672 us。持续时间比至少 2 的 100 个可评价状态中，14 个改善、37 个变差、49 个平局。它能提高候选浓度，但不能单独决定动作。

## 3. 可靠未来释放与 WAIT

576 个采样状态中没有出现计划定义的可靠未来释放：默认通信执行期间，某个 active compute 确定完成，且会单独释放资源冲突通信。本轮因覆盖为零，既没有真实支持例，也不能把未观察到解释为机制无效。

相应反例边界仍成立：未来释放的通信如果没有长下游，等待会延后当前关键链。该机制需在 D2 的手算/Exact 支持例和新增真实来源中先验证，本轮不准入真实在线 WAIT 实验。

## 4. 多资源脚印和集合替换

Cassini/Alibaba 两个 routed 图中发现 8 个条件改善状态，全部位于 work-conserving；但本轮实际可评价的替代集合与 LT 集合占用相同的资源并集，没有观察到“一个 LT 通信同时阻挡两个资源互补通信”的完整脚印结构。因此这些结果证明集合成员/顺序可能重要，没有证明计划中的 one-for-two packing 机制。

反例边界：同一资源并集上的集合变化也可能平局或变差。本轮 routed 可评价记录中，除 8 个改善外还有 7 个未改善记录。4c 需要专门候选构造和机制图，不能直接把这 8 个状态当作脚印特征支持例。

## 5. Last-missing barrier

共评价 61 个由 last-missing 提出的挑战动作：53 个与 LT 平局，8 个更差，0 个改善。默认动作自身是 last-missing 的状态也同时包含平局、变差和 11 个由其他挑战动作取得的改善，说明“当前接近 barrier”不能识别应该换向哪个动作。

这组真实样本提供了否定反例：提前解除直接 join 并不保证降低最终 makespan。当前没有满足 4e 准入条件的真实支持例。

## 6. Job 边界和剩余量

全部 23 个条件改善都将动作切换到另一个 job，说明跨 job 选择是当前最稳定的共同现象。具体支持例：

- `np_stage4f_gpt22_two_hom_1pct` optional-idle 决策 51，shortest-remaining-job 挑战从 job1 切到 job0，条件改善 3,021 us；当时残余工作为 job0 4,950,456、job1 4,990,549。
- 同图 work-conserving 决策 29 和 156 分别改善 2,459 和 1,007 us。
- `np_stage4f_alibaba_slice_heter_1pct` optional-idle 决策 73，job-aware LT 挑战改善 72 us。

反例来自总体命中率：有简单策略动作分歧的 328 个可评价状态中，仅 13 个条件改善、56 个变差、259 个平局。job 剩余量适合作为候选/触发信息，不能直接取代 LT。

## 7. 一步修正与完整策略差异

`np_stage4f_gpt13_gpt7_1pct` work-conserving 的 32 个采样状态没有条件改善：20 个平局、3 个变差、9 个无不同挑战；但既有完整基线中，固定 job 顺序 makespan 为 1,878,580 us，LT 为 1,978,450 us。`gpt13_gpt7_2pct` 的同模式也没有采样到一步改善，而固定 job 顺序为 1,877,322 us，LT 为 1,976,527 us。

这两个实例说明完整策略优势可能来自连续多次 job 服务决策，有限状态采样和一步 LT 后续不能保证捕获。因此 4d 必须同时报告局部条件修复与端到端结果，不能用任一层替代另一层。

## 8. Exact 控制

复用并核对此前单 job 真实切片：60 个“图×模式”Exact 全部 optimal；243 个 LT 路径决策标签也全部 optimal，LT 正 regret 为 0，其中 157 个为 LT 位于最优并列集合。来源和 SHA-256 见 `control_evidence.json`。

这组控制与本轮 multi-job 条件改善共同支持一个受限结论：当前观察到的可修复 LT 失误集中在多 job 场景，不能据此推断单 job LT 已在所有真实图上最优。
