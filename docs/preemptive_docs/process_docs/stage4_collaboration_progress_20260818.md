# 当前研究进度

## 1. 总览

当前算法主线是分层处理：

```text
当前 residual state
    -> Longest Tail 默认方向
    -> 多资源时构造合法 maximal compatible set
    -> 使用LLM training DAG特征识别少量高不确定性/高潜在收益状态
    -> 必要时调用受预算 rollout
    -> 严格优于 Longest Tail 才接受，否则回退
```

因此，Longest Tail、packing、barrier 和 rollout 分别承担不同职责。

## 2. Longest Tail

### 2.1 算法是什么

在当前事件状态中，对每个合法通信计算 tail：从该通信完成后仍未完成的后继开始，计算最长的剩余因果工作路径。

单 channel 选择 tail 最大的通信；固定多 channel 时先选择 tail 最大的通信作为 seed，再按确定性顺序加入资源集合不冲突的通信，直到集合按包含关系极大。

Longest Tail 的作用是低成本地把通信资源给当前最可能影响最终尾部的任务。它不尝试完整预测未来，也不直接判断 barrier、job 公平性或所有兼容集合的全局价值。

### 2.2 已有表现

在平行链的 26 个有精确解的样例上，Longest Tail 的 mean ratio 为 1.016，observed optimal rate 为 88.46%，明显优于 FIFO、SPT、LPT 和 Longest-delay。它的平均运行时间约 1.8 ms，远低于 rollout 和 Beam。

在 38 个正式一般 DAG 样例上，Longest Tail 的 observed optimal rate 为 84.21%，mean ratio 为 1.010315，observed max ratio 为 1.095238。它的失败主要出现在 join、barrier、嵌套 fork/join 或需要连续多个选择才能体现价值的结构。

在固定多 channel 小图中，Longest Tail greedy-fill 是当前最稳定的低开销 packing baseline。它在两个 random 图上分别为 19 对 18、28 对 27，说明它不是一般最优算法。

### 2.3 当前判断

Longest Tail 仍是所有新算法的默认参照和 fallback。当前研究重点不是替换它，而是识别它可能犯错的少量状态，并用有限额外计算修复这些状态。

## 3. Rollout：已经确认有效，但完整调用成本高

### 3.1 算法是什么

Rollout 在一个选择点枚举若干候选首动作。每个候选都通过公共 simulator 执行一次，然后从新状态使用相同的 Longest Tail completion policy 推进。比较候选完成时间，只有完整搜索并且严格优于 Longest Tail 的候选才被采用；平局、超时、状态上限或异常都回退 Longest Tail。

Rollout 的基本参数有：候选宽度 top-k、搜索深度、候选生成方式和状态/时间预算。depth-1 只比较首动作；depth-2 会在首动作之后再展开一个合法通信决策，但不改变执行语义。

### 3.2 已有表现

平行链的 26 个有精确解的样例中，Rollout-2、Beam-8 和 Beam-32 都取得 100% observed optimal；Rollout-2 平均运行时间约 12.3 ms，约为 Longest Tail 的 6--7 倍，Beam 更慢但没有额外质量收益。

在 38 个一般 DAG 小图样例中，top-2/depth-2 rollout 取得 100% observed optimal，平均运行时间约 15.45 ms；top-2/depth-1 为 97.37%，mean ratio 1.001253。相对 Longest Tail，rollout 在 6 个样例上改善、32 个持平、没有观察到退化，最大改善约 8.696%。

在参数化大图上，rollout 的收益很稀疏，10--100 节点的压力集中只在少数图上改善，100 节点时平均运行时间已经达到秒级。因此 rollout 的结论是“对困难选择有价值”，不是“默认对所有大图全量调用”。

固定多 channel 的 Set-Rollout 也说明了集合级前瞻的价值：在一个反例中，LT-greedy、multi-seed 和 exchange 都为 16，Exact 为 14；加入 depth-1 set rollout 后达到 14，改善 12.5%。这表明收益来自比较集合动作的未来影响，而不是简单选择更大的集合或提高静态资源分数。

## 4. 多 channel 的通信集合选择

### 4.1 问题和当前默认方法

多 channel 场景中，一次动作不是一个通信，而是一个资源互不冲突的通信集合。集合必须是合法、非空、work-conserving 且 inclusion-maximal。资源集合相交的通信在冲突图中连边，合法集合对应极大独立集。

当前默认方法是 LT-greedy：

1. 计算每个 eligible communication 的 residual Longest Tail；
2. 按分数从高到低尝试加入通信；
3. 与已选通信资源冲突的候选跳过；
4. 扫描结束后确认没有仍兼容的候选；
5. 将集合交给公共 simulator 执行。

还尝试了 multi-seed、一次交换和有限集合枚举，但它们都必须保留 LT 集合作为 fallback。

### 4.2 实验表现

固定多资源的基础 contract 已经通过：冲突图边、资源原子获取、暂停释放和 trace replay 均能独立检查；错误的非 maximal 集合和资源冲突集合会被拒绝。

在 packing trap 中，静态 seed 分数会得到 makespan 18，而 Exact 为 13；简单 greedy、multi-seed 和 exchange 在另一个 future-value trap 中都为 16，只有 set-level depth-1 rollout 达到 Exact 的 14。由此当前结论是：

- deterministic LT-greedy 是稳定默认 packing；
- multi-seed 适合作为受预算的候选生成器；
- 静态资源负载、集合大小或 union downstream 分数不能单独代表集合的端到端价值；
- 真正有希望的是 set-level future-value comparison。

在 72 个真实 LLM 派生 benchmark 的受限前缀扫描中，40 个多资源样例只有 3 个样例、共 7 个状态观察到多个可认证的非等价集合选择。因此昂贵的集合枚举不能默认施加到全部大图，应先经过 choice gate。

## 5. Barrier：单独使用收益不稳定

### 5.1 算法是什么

Barrier 指 LLM training DAG 中由训练同步关系形成的同步屏障。Barrier 特征从当前 residual state 计算：barrier 尚未完成的前驱、某候选是否为最后缺口、完成候选后立即或递归释放的计算、各分支到 barrier 的剩余 tail 和 slack，以及暂停当前通信可能造成的尾部增加。

已经尝试过三类使用方式：

- 直接按 barrier proximity 或 barrier score 排序；
- 先筛掉明显不会影响当前 barrier 的候选，再用 Longest Tail；
- 将 barrier 候选加入 rollout 的 challenger 集合，由完整候选比较决定是否采用。

### 5.2 实验表现

在 45 个 single channel 一般 DAG 上，纯 barrier candidate 只有 1 胜、44 平、0 负；平均改善很小。受保护的 barrier + rollout 有 6 胜、39 平、0 负：按全部 45 个样例计算，平均相对改善约 0.847%；在 6 个胜例中，平均改善约 6.35%，最大改善约 11.11%。额外运行时间平均约 9.67 ms，而 Longest Tail 约 1.95 ms。

在 9 个特别构造的 barrier 小型 DAG 上，barrier 规则没有超过 Longest Tail。多资源的 barrier union 没有胜例，裸策略出现退化；加入 Longest Tail safeguard 后保持不退化，但也没有观察到改善。

### 5.3 当前判断

Barrier proximity 不是可靠的全局 priority，不能替代 Longest Tail。当前保留方向是把 barrier 作为 rollout 的增强特征：当 Longest Tail margin 小、候选是 join/barrier 的最后缺口，或候选会立即释放关键计算时，提高它进入 challenger 的概率；最终动作仍由受预算 rollout 和严格 safeguard 决定。

## 6. Selective Rollout：当前最有价值的方向

### 6.1 算法是什么

Selective rollout 在 Longest Tail 默认策略之上增加一个低成本 choice gate。只有同时满足“存在真实非等价选择”和“状态具有较高潜在 regret”时，才调用 rollout。

当前最佳触发规则是：

```text
immediate unlock
AND normalized Longest Tail margin <= 0.25
```

其中 immediate unlock 表示候选完成后会立即释放计算或关键 join；normalized margin 表示 Longest Tail 第一候选与第二候选的相对分数差。触发后生成一个 challenger，与 Longest Tail 候选使用相同 completion policy 比较。任何平局、异常、预算耗尽、状态限制或非严格改善都回退 Longest Tail。

### 6.2 45 图结果

在现有 45 个 single-channel complex DAG 上：

| 方法 | 胜/平/负 | 胜例中的平均相对 Longest Tail 改善 | 触发次数 | completion calls |
|---|---:|---:|---:|---:|
| 全量 depth-1 rollout | 7/38/0 | 6.19% | 175 | 350 |
| unlock + margin 0.25 | 7/38/0 | 6.19% | 67 | 134 |
| 等调用随机触发 | 3/42/0 | 7.05% | 68 | 136 |
| 近似周期触发 | 5/40/0 | 6.89% | 76 | 152 |
| last-missing join + margin | 1/44/0 | 4.35% | 17 | 34 |

Selective rollout 相比全量 rollout 减少约 61.7% completion calls，同时保留了全量 rollout 在这 45 个图上的全部观察收益。相近调用率下，它优于随机触发和周期触发。所有 trace replay 通过，平局、异常和预算失败均正确回退，没有观察到退化。

### 6.3 为什么这个结果重要

这个结果说明 rollout 的收益并不是来自“对所有状态都搜索”，而是集中在一小类具有两个特征的状态：

1. Longest Tail 对当前选择不够确定；
2. 某个候选完成后会立即改变后续可执行结构。

这为在线算法提供了明确方向：保留 Longest Tail 的低成本主路径，只把额外计算用于可能产生局部 regret 的事件。节省的预算还可以用于 top-4、depth-2 或 set-level rollout。

### 6.4 证据边界

45 图结果主要来自 random、adversarial 和少量 real-derived complex DAG。72 个真实 AICB 派生 benchmark 当前因为完整模拟耗时较长，只完成受限前缀：每个样例最多 32 个决策或 5 秒，共观察到 435 个非等价 choice state。样例因此属于部分验证，不能视为完整结果。因此当前结论是“在已有困难图上效果很强，值得优先继续验证”。

### 6.5 下一步

优先完成真实 corpus 的完整或分层 choice census；冻结 trigger 和预算，在未参与规则设计的 workload/topology holdout 上复现；比较 top-2/depth-1、top-4/depth-1、top-2/depth-2 和 set-level rollout；报告触发 precision、regret recall、漏触发、运行时间和 fallback 覆盖率。

## 7. Multi-job 场景的简单探索

### 7.1 算法是什么

Multi-job benchmark 由多个 job 的 AICB workload 混合得到。job 之间没有 DAG 依赖，只共享通信资源。当前比较了：

- flat Longest Tail：忽略 job 边界，对所有候选通信统一排序；
- weighted Longest Tail：在通信分数中加入 job 权重；
- shortest remaining：优先剩余工作量较少的 job；
- attained service：考虑 job 已获得的服务量，避免长期饥饿；
- flat rollout：对 job-level 候选做有限前瞻。

所有策略都使用公共 maximal-action transition，并分别报告 makespan、per-job completion、JCT、slowdown 和公平性。

### 7.2 受控实验结果

在 J0--J6 的 7 个固定多 job 结构样例中：

| 策略 | 最优 makespan | 最优 weighted JCT |
|---|---:|---:|
| flat Longest Tail | 7/7 | 3/7 |
| weighted Longest Tail | 7/7 | 4/7 |
| shortest remaining | 3/7 | 5/7 |
| attained service | 3/7 | 4/7 |

shortest remaining 对 weighted JCT 更有帮助，但会牺牲 makespan；因此不能把它作为单 job makespan 的改进。multi-job rollout 在 4 个 SimAI pipeline probe 中没有改善 makespan，而 priority 约 29.2 ms，flat rollout 约 1154.5 ms，约 40 倍开销。当前不支持把 flat rollout 作为 multi-job 默认策略。

### 7.3 当前判断

最稳定的 multi-job makespan 基线是 flat Longest Tail + maximal packing。


## 8. 下一步计划

1. 完成大图实验和真实竞争统计。优先把当前尚未完成的真实大图和 AICB 派生 benchmark 分层跑完，目前大图跑不完的原因是图的规模本身过大，连基础算法也难以跑完，现在正在调整。

2. 研究多个方法的组合收益，在单独结果已经明确的基础上，按组件逐步组合。

3. 深入研究 Selective Rollout 的成本和收益。Selective Rollout 是当前最值得继续投入的方向。接下来研究能否减少触发次数、能否减少单次 rollout 成本、能否把节省的预算用于更有价值的状态。

4. 之前尝试过利用 LLM training DAG 的周期性和对称性进行调度策略的压缩，但是发现虽然图看起来是重复的，但是实际上不同的板块之间有较强的关联，同时它们之间细微的不同其实对结果也有较大影响，难以得到较好的策略。
