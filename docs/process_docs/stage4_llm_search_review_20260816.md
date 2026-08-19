# Stage 4 LLM 结构化搜索实现与理论审查

日期：2026-08-16  
性质：只读审查；本轮未修改实现、benchmark、schema、测试或历史结果  
审查范围：`outline.md`、`stage4_LLM_search.md`、`stage4a_benchmark.md`、`stage4b_structure_theory.md` 所定义的 Stage 4；旧文档和论文只作为证据来源，不作为当前语义的事实来源。

## 1. 结论摘要

当前 Stage 4 **尚不能认定完成，也还不具备开展可靠 LLM 专用算法比较的输入基础**。

- Stage 4a：已有 SimAI/AICB 读取、拓扑路由冻结、若干合成 motif 和转换测试等可复用部件，但输出仍默认落入旧不可抢占语义，缺少五层 benchmark、完整 provenance、转换删改日志和等价性声明。因此不能把现有导出称为目标可抢占 Stage 4 benchmark。
- Stage 4b：已有重复结构扫描、严格独立同构分量压缩、重复结构反例、多 job 小图 exact/heuristic 等原型，但没有计划要求的正式结构目录，也没有在固定多资源可抢占主模型上完成证据闭环。
- 历史结论中，“重复 motif 本身不足以保证局部策略好”和“严格独立同构分量可安全做对称压缩”可以在收窄适用范围后保留；旧的多资源 `K=1` 对 `K=2` 反例在当前 maximal-compatible-set 语义下已经失效，应撤回；真实 LLM 图 94%–99% 重复率等数字因缺少原始输入、哈希和可重放产物，只能作为待复核线索。
- 现有 125 个单元测试全部通过，但 SimAI integration 测试因本地缺少 `jsonschema` 被测试配置静默排除。这一结果不能证明 Stage 4a 转换链已被测试。

## 2. 判定依据与目标边界

Stage 4 必须继承 Stage 3 的固定多资源可抢占语义：compute 自动开始且不可抢占；communication 保存剩余工作并可在离散任务事件暂停/恢复；启动或恢复时原子获取固定资源集合；兼容通信可并行；动作必须 work-conserving；算法无主动 WAIT；目标默认仍是单 job makespan。多 job JCT、weighted completion time 和 fairness 是另立目标，不能混为 Stage 4 主结论。

据此，本审查不接受以下替代证据：

1. 不可抢占导出能通过旧 validator，不能证明其符合 Stage 4。
2. 合成 motif 上的效果，不能证明真实 LLM training DAG 上有效。
3. 单 channel 结论，不能直接推广到固定多资源集合。
4. 不同 exact 实现的状态数，不能直接作为某项压缩的净收益。
5. 实验最优率或局部 score，不能替代理论保证。

## 3. 当前实现资产盘点

| 资产 | 当前状态 | 可复用性 | Stage 4 缺口 |
|---|---|---:|---|
| `benchmark_generate/simai/bootstrap.py` | 可生成合成输入并连接外部 workload 入口 | 中 | 合成输入与真实来源边界没有在输出类别中固化 |
| `benchmark_generate/simai/export.py` | 可把拓扑路径冻结为固定有向 link/NIC 资源 | 高 | `to_benchmark()` 未显式设置可抢占 v2 semantics；provenance 和转换日志不足 |
| `experiments/simai/repetition.py` | 有局部签名、周期和冲突统计 | 中 | 分析实现位于 thin runner 目录；周期证据不足以证明未来等价或可压缩 |
| `experiments/simai/repetition_study.py` | 有 placement/扰动/扫描逻辑 | 中 | 同样把研究实现放入 `experiments/`；没有冻结输入与结果 lineage |
| `src/llm_structured/repetition.py` | 有重复 fixture、反例、独立分量对称 exact | 中到高 | 仅单 channel；代码混合 fixture、算法和验证；状态数比较非同构实验 |
| `src/llm_structured/multi_job.py` | 有单 channel 多 job exact、heuristic 和多资源层级候选原型 | 中 | 多 job 不是当前主目标；文件职责过多；多资源 K 已不再表示严格候选限制 |
| `experiments/preemptive/stage5.py`、`stage6.py` | 能复跑部分历史研究 | 低到中 | runner 包含案例/研究逻辑；无统一预算、状态和版本清单；Stage 5 全量复跑超时 |
| `src/registry.py` / 公共转换层 | 提供稳定算法入口 | 中 | 没有 LLM 结构算法注册；内部 DAG 丢失 phase、micro-batch、collective、stage 等标签 |

## 4. Stage 4a：benchmark 与转换链审查

### 4.1 阻断问题：导出仍是旧不可抢占语义

`benchmark_generate/simai/export.py` 的说明和 `to_benchmark()` 返回值均表明它在投影到旧 non-preemptive model。构造 `Benchmark` 时没有显式传入目标 semantics，因此采用模型默认值：`preemption=none`、`decision_event=task_completion`、允许 optional idle。它与 Stage 4 要求的 `communication_resume`、task-event、无主动 WAIT 不一致。

现有 integration 测试主要验证“能被 validator 接受”，没有逐字段断言 Stage 4 语义，也没有用公共模拟器回放 pause/resume、原子固定资源和 maximal-compatible action。因此这是语义错误，不是文档措辞问题。

### 4.2 路由冻结是可保留的核心部件

导出器会将通信路径展开为有向 link，并可附加 NIC，通信持有固定资源集合。这符合“不动态选路、不迁移、不部分获取资源”的目标边界，应该保留。

但通信时长目前使用全局 `bandwidth_gbps` 折算，而非拓扑中逐 link 容量。它可以作为抽象模型存在，前提是转换契约明确说明这是统一瓶颈带宽近似，并把参数、单位和版本写入 provenance；否则相同 workload 在不同拓扑文件上的数值含义不透明。

### 4.3 五层 benchmark 尚未形成

计划要求的五层现状如下：

| 层 | 现状 | 判定 |
|---|---|---|
| synthetic motif | 有若干 generator 和 3 个可抢占 motif 导出入口 | 部分存在，但分类混乱 |
| structured projection | 有少量人工投影快照 | 不足，缺转换 lineage 与等价性说明 |
| real-derived | 仓库没有可核验的固定真实派生样本 | 未完成 |
| adversarial | 有代码内反例 fixture | 未形成 Stage 4 自包含 benchmark 层 |
| compatibility | Stage 3 benchmark 可复用 | 未建立 Stage 4 兼容清单和验收记录 |

尤其是，`to_benchmark()` 无论使用合成输入还是真实输入都写 `category="real"`；另一转换路径还会把 `llm_motif` 映射为 `real`。这会把“真实来源”与“LLM 风格合成结构”混在一起，使实验分组失真。

### 4.4 provenance 与可追溯性不够

现有 metadata 能记录部分并行度、带宽、拓扑路径和模式，但仍缺少：

- workload/AICB 原文件标识、版本和内容 hash；
- SimAI/AICB 代码版本或 commit；
- topology 内容 hash，而不是仅存本地路径；
- 转换器版本、完整参数和转换配置 hash；
- 节点/边的删除、合并、收缩、序列化依赖添加日志；
- 投影性质：严格等价、上界、下界、松弛，或仅是 motif 启发；
- 输出 benchmark hash 与转换 manifest 的绑定。

当前 CLI 虽知道 `--aicb` 输入，却没有把该来源稳定写入输出。旧结果 JSON 也缺少源码 commit、环境、benchmark hash 和转换 manifest，语义变化后无法认证为同一实验对象。

### 4.5 依赖类型没有完整保真

导出器会加入 compute serializer 顺序边，这有助于表达固定计算顺序；但一般输出没有区分数据依赖、计算资源序列化边和转换补边。Zero Bubble 的历史修复证明 B/W 数据依赖曾被纠正，但 serializer 边仍可能产生同样的有效次序。若不分别记录，后续理论无法判断某个 barrier 是模型固有结构还是转换人工约束。

### 4.6 公共接口会丢失 Stage 4 标签

公共内部 DAG 转换目前主要保留 task role/cut，phase、micro-batch、pipeline stage、collective、parallelism dimension 等 Stage 4 特征没有完整进入算法状态；`src/registry.py` 也没有 LLM structured 算法入口。结果是：直接研究原型可以读取部分标签，但通过正式 CLI/registry 运行时，计划中的 LLM-specific score 无法获得相同信息。

### 4.7 integration 测试实际上未运行

本地执行：

```text
python -m pytest -q tests/llm_structured tests/integration \
  tests/test_semantics_layout.py tests/test_benchmark_format.py
19 passed

python -m pytest -q
125 passed
```

检查测试配置后确认：缺少可选依赖 `jsonschema` 时，`tests/integration/conftest.py` 会通过 `collect_ignore_glob` 静默忽略 integration 目录，因此上述数量不包含 SimAI 导出、拓扑和 Zero Bubble 集成测试。测试通过本身是真实的，但覆盖结论必须降级。

另有轻微文档漂移：当前固定 benchmark 数量由测试统计为 171，而 README 仍写 144。它不影响语义，但说明 benchmark 清单尚未由机器生成的 manifest 管理。

## 5. Stage 4b：结构理论与算法方向审查

### 5.1 正式结构目录不存在

计划要求 repeat、semantic、multi-job 至少各有一个形式化条目，每个条目包含定义、适用假设、正证据、反例和对算法方向的开放/否决判断。当前这些内容分散在代码、旧计划和结果 JSON 中，没有统一目录，也没有与 4a benchmark 双向链接，因此 Stage 4b 的核心交付物尚未出现。

### 5.2 重复扫描只能作为描述性统计

`experiments/simai/repetition.py` 的局部签名和 `_detect_period()` 主要比较规范化标签计数。它没有验证跨周期依赖接口、carry state、资源映射、同步边或未来可行动作等价。因此：

- “检测到周期”不等于图 automorphism；
- automorphism 也不自动等于 exact 状态可合并；
- 高重复率不等于局部策略会接近最优。

其中 conservative exchangeability 检查字面 graph twins，可作为安全的下界型诊断，但不是完整的对称群检测器。

### 5.3 严格独立同构分量压缩可保留，但范围很窄

`src/llm_structured/repetition.py` 的 component symmetry exact 会检查分量任务标签、时长、依赖位置相同，且拒绝外部/跨分量依赖，再将分量 runtime state 排序作为 quotient key。在“单 channel、严格独立、同构分量、共享 channel”假设下，这一压缩具有明确的未来等价基础，是当前最可信的正面理论原型。

它尚不能覆盖：固定多资源映射、跨 micro-batch barrier、共享 collective、非同构 stage、资源标签置换或真实 pipeline carry。因此应称为特殊情形定理/验证原型，而不是 LLM 重复结构的一般结论。

### 5.4 状态压缩收益的旧比较不受控

历史结果把自定义压缩 exact 与 Stage 2 通用 branch-and-bound exact 的状态数相比。两者的分支顺序、下界、去重和剪枝并不相同，所以差值不能全部归因于 symmetry key。

当前受控程度仍不足，但重新运行得到：

| replicas | compressed makespan / states | generic makespan / states |
|---:|---:|---:|
| 3 | 11 / 16 | 11 / 30 |
| 4 | 14 / 38 | 14 / 361 |
| 5 | 17 / 73 | 17 / 2853 |
| 6 | 20 / 126 | 20 / 10710 |
| 7 | 23 / 203 | 23 / 9455 |

makespan 一致支持“小图答案未被破坏”，但 generic 状态数已经与旧 JSON 中的 66、501、3163、18134、99207 不同，说明结果依赖 exact 版本；不能继续原样引用旧状态缩减倍数。下一步应使用除 key 外完全相同的 paired solver。

### 5.5 重复结构反例仍成立

重新运行独立副本反例：

| copies | optimum | copy-local | boundary-aware |
|---:|---:|---:|---:|
| 1 | 2 | 2 | 2 |
| 2 | 4 | 5 | 4 |
| 4 | 8 | 11 | 8 |
| 8 | 16 | 23 | 16 |

该构造中 copy-local 为 `3n-1`，最优为 `2n`，比值趋近 `1.5`。它可以支持一个严格的否定结论：**重复 motif 本身不足以证明逐副本局部调度好**。但它是单 channel 合成反例，不能单独证明真实 LLM pipeline 中某种策略必然差，也不能替代多资源反例。

### 5.6 语义标签优先级尚无正证据

现有 coupling-aware/PP role 规则是 fixture 特化的手工优先级，历史 pipeline 样例中相对 longest-tail/rollout 还出现轻微退化。因此目前只能得出：简单静态角色优先级不足。不能由此否定所有 LLM-aware score，也不能宣称已有有效的 LLM 专用 score。

### 5.7 多资源 K 结论已经改变

当前多资源 hierarchical 选择器先提名 top-K，随后为满足 maximal-compatible-set 语义遍历全部 eligible flow 补全动作。因此 K 不再是“调度器只能看到/选择 K 个候选”的严格限制。

重新运行固定 Stage 6 probe，`K=1`、`K=2`、flat 均为 makespan 18，首次动作都是兼容的 `{A::private, B::shared}`。旧文档中的多资源 `K=1` 得 25、`K=2` 得 18 的反例依赖旧的非 maximal 动作语义，必须撤回。若继续研究 K，应先明确定义它限制的是 seed、打分预算、组合搜索预算还是可见动作空间。

### 5.8 多 job 原型属于独立扩展

`src/llm_structured/multi_job.py` 对小图验证了 makespan 与 weighted JCT 可能选择不同调度，这个“目标不可混用”的结论可以保留。但主体实现仍偏单 channel，且把模型、exact、heuristic、fixture 混在一个约 950 行文件中。它不是 Stage 4 单 job 固定多资源主线已完成的证据。

### 5.9 `experiments/` 边界被突破

`experiments/simai/repetition.py` 和 `repetition_study.py` 内含签名定义、周期检测、placement 投影、扰动生成和指标计算；这些是可复用分析/算法逻辑，而不是薄 orchestration。Stage 5/6 runner 也承担部分案例构建和研究逻辑。它会使测试、版本化和公共复用变困难，与当前仓库约定不符。

### 5.10 Stage 5 全量 runner 不具备稳健复现条件

直接调用当前 `run_study()` 在 120 秒内未完成。runner 对 period 16 和通用 exact 等调用没有统一 time/state limit，也没有明确的 optimal/timeout/fallback 状态。因而旧 JSON 即使存在，也无法仅靠 runner 可靠复现和认证。

## 6. 论文证据与适用边界

本轮只将论文用于校正研究问题和特征设计，不把论文结果当作本仓库实现正确性的证据。

- **Hermod: Coflow Scheduling for LLM Training**：论文使用 micro-batch ID、coflow type、layer ID 等语义特征，能支持 Stage 4 保留结构标签的方向。但其表述是 EP 与 PP 总体高于 DP，具体优先级依 case/factor 决定；当前计划中的固定“PP > EP > DP”概括过强，应更正。论文为短篇初步模拟结果，不能支撑本项目的理论保证。
- **Crux**：研究多租户 GPU 利用率、job 级 intensity/path/priority，与本项目单 DAG 固定路由通信选择的动作和目标不同，只能启发 job-level 特征。
- **Cassini**：主要研究多 job placement 和 time-shift affinity，不是固定 DAG 内的可抢占通信调度。适用于多 job 扩展动机，不适用于主线 exact/heuristic 结论。
- **Puppeteer**：集中式离线网络规划、动态 route/rate 与 QoS 联合优化，超出当前“不动态选路、不按比例分带宽”边界。其可预测 workload 思路可启发转换契约。
- **Coda**：面向多租户 JCT，以流量时移和拥塞控制优先级为动作，也超出当前模型。可作为未来扩展对照，不能混入 Stage 4 makespan 结论。

因此，论文能说明“LLM 标签、重复和跨层同步值得研究”，但没有一篇直接证明当前的 fixed-resource、task-event、zero-overhead preemption 模型或现有算法。

## 7. 历史结论的重新分级

### 7.1 可保留，但必须收窄表述

1. 重复 motif 不足以保证 copy-local 调度优良；上述单 channel 反例成立。
2. 严格独立同构分量可在单 channel 特例中进行安全的 permutation quotient；小图 makespan 与通用 exact 一致。
3. makespan 与 weighted JCT 是不同目标；小图可出现最优顺序分离。
4. Zero Bubble 的 B/W 数据依赖修复是必要的，但需同时审计 serializer 边造成的有效顺序。

### 7.2 降级为待复核线索

1. 6 个 AICB 图中 94%–99% 重复率。
2. 78.65%–79.08% 的跨 micro-batch 冲突比例。
3. 历史 symmetry 状态缩减倍数。
4. placement jitter、拓扑扰动或 coupling-aware 的旧收益表。

原因是缺少冻结原始输入、版本、转换 manifest、benchmark hash 或同版本 runner；这些数字不能进入当前正式结论表。

### 7.3 应撤回或明确标记过时

1. 多资源场景 `K=1` makespan 25、`K=2` makespan 18 所支持的候选宽度结论。
2. 将合成 SimAI bootstrap 输出称为 `real` benchmark。
3. 将当前 exporter 输出称为 Stage 4 可抢占 benchmark。
4. 将“检测到周期”直接解释为可做 exact 状态合并。
5. 固定声称 Hermod 给出“PP > EP > DP”。

## 8. 对 Stage 4 验收项的逐项判定

| 验收项 | 判定 | 主要原因 |
|---|---|---|
| 五层 benchmark | 未通过 | 只有零散 motif/投影，real-derived、adversarial、compatibility 清单缺失 |
| 自包含且固定资源 | 部分通过 | 路由冻结可用；转换语义和 provenance 不合格 |
| 可抢占公共模拟语义 | 未通过 | SimAI exporter 默认 non-preemptive |
| 转换可追溯、可重放 | 未通过 | 缺输入/拓扑/工具 hash 和删改日志 |
| 正式结构目录 | 未通过 | 没有统一条目和方向判决 |
| 至少一个 repeat 正/反证据 | 部分通过 | 有单 channel 特例和反例，未迁移到 Stage 4 主模型 |
| semantic 结构结论 | 未通过 | 只有描述性标签和一个退化的手工规则 |
| multi-job 条目 | 部分通过 | 有目标分离小图，但属于单独扩展且未接固定多资源主线 |
| 冲突图 packing 债务 | 未通过 | 仍未形成计划中的 weighted packing/local exchange 实现与证据 |
| 结果可复现 | 未通过 | integration 未执行；历史结果缺 manifest；runner 无统一预算状态 |

## 9. 最终判断

Stage 4 当前应回到“输入契约与证据建账”阶段，而不是继续增加 LLM heuristic。最值得保留的是固定路由资源导出、独立同构分量的安全检查、重复结构负例和多 job 目标分离 fixture；最需要先修的是 exporter 语义、五层分类/provenance、integration 覆盖和结构目录。只有这些完成后，selective rollout、LLM score、symmetry compression、conflict-graph packing 或多 job 扩展的比较才有可解释性。

