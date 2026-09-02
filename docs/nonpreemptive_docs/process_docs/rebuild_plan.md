现在做一次小范围重构。不需要全仓重写，也不建议现在大规模移动可抢占代码。

  ## 最需要解决的问题

  ### 1. 公共 LT/WAIT 逻辑有两套实现

  Stage 4a 实验层自己实现了：

  - residual tail；
  - FIFO/固定顺序/LT；
  - optional-idle WAIT；
  - 单通道和多资源回放。

  见 experiments/llm_structure/nonpreemptive/runtime.py:27。

  Stage 4d 又实现了一套冻结 LT：

  - src/llm_structured/nonpreemptive/selective_rollout/baseline.py:6
  - src/llm_structured/nonpreemptive/selective_rollout/adapters.py:1

  这已经不是单纯的代码重复。之前 Stage 4d 漏掉 Stage 4a 的 WAIT 规则，产生过829 tick伪收益，说明它会直接破坏研究结论。

  建议提取为：

  src/llm_structured/nonpreemptive/runtime/
  ├── contracts.py       # Mode、ActionSignature
  ├── adapters.py        # 单通道/多资源统一适配
  ├── policies.py        # FIFO、固定顺序、LT、SPT、LPT
  ├── completion.py      # 用冻结策略完成 residual state
  ├── replay.py          # 动作执行、trace、统计
  └── features.py        # 共享 residual tail 等基础量

  然后：

  - Stage 4a 实验调用这里；
  - Stage 4d 调用这里；
  - Stage 4e 调用这里；
  - 后续 4f 也调用这里；
  - 实验代码不再拥有独立调度语义。

  这是最高优先级重构。

  ### 2. Barrier 反向依赖 Selective Rollout

  当前 barrier 直接导入：

  - selective_rollout.adapters；
  - selective_rollout.baseline；
  - selective_rollout.contracts.Mode；
  - selective_rollout.contracts.ActionSignature。

  见：

  - src/llm_structured/nonpreemptive/barrier/policies.py:8
  - src/llm_structured/nonpreemptive/barrier/contracts.py:8

  这意味着名义上的 4e 依赖 4d，而它真正依赖的是不可抢占公共运行接口。

  正确关系应该是：

                 nonpreemptive/runtime
                    ↑       ↑       ↑
                packing  rollout  barrier

  而不是：

  barrier → selective_rollout → simulator

  把 adapter、LT、completion 和公共动作合同移到 runtime/ 后，这个问题自然解决。

  ### 3. Stage 4e 的基础 LT 和特征计算没有分开

  现在 barrier.schedule(method="lt") 仍会：

  - 建 barrier 图；
  - 计算 baseline 特征；
  - 遍历 challenger；
  - 计算 descendant；
  - 执行特征状态转移。

  所以 B0 并不是真正的纯 LT。这既造成性能混淆，也使实验职责不清。

  建议分成：

  runtime.schedule_baseline(...)
  barrier.analyze_decision(...)
  barrier.schedule_corrected(...)

  纯 LT 不应该导入 barrier 模块。Barrier 模块只负责：

  - 构造结构；
  - 计算修正候选；
  - 在明确启用时改变动作。

  ### 4. 多资源 solver.py 职责太多

  src/muti_channel/nonpreemptive/solver.py 约791行，同时包含：

  - 状态和动作；
  - 公共模拟器；
  - legal action；
  - Exact；
  - lower bound；
  - greedy policy；
  - rollout；
  - trace 重放与验证。

  Stage 4 代码还导入了私有函数 _replay。公共模块依赖另一个模块的下划线私有函数，是比较明确的结构问题。

  理想结构是：

  src/muti_channel/nonpreemptive/
  ├── model.py          # 状态、动作、合法性、step
  ├── replay.py         # schedule/trace 重放与验证
  ├── policies.py       # greedy 基线
  ├── oracle.py         # Exact 和 lower bound
  ├── rollout.py        # 历史 R4 rollout
  ├── interface.py
  └── solver.py         # 兼容旧 import 的薄转发层

  不过这个迁移风险较高。建议先补行为锁定测试，再逐块拆，不要与性能优化同时大改状态表示。

  ### 5. corpus.py 过于集中

  benchmark_generate/llm/nonpreemptive/corpus.py 约548行，当前同时负责：

  - source 选择；
  - 子进程转换；
  - benchmark 命名；
  - manifest；
  - 小图切片；
  - multi-job 组合；
  - contention audit；
  - candidate 校验；
  - 发布、备份和回滚；
  - CLI。

  接下来还要增加高 GA/PP/EP 选样、困难度准入和三类数据分组，再继续往里面加会明显失控。

  建议拆成：

  benchmark_generate/llm/nonpreemptive/
  ├── selection.py       # source 分层与候选选择
  ├── generation.py      # 单个 spec 的生成编排
  ├── contention.py
  ├── slice.py
  ├── multi_job.py
  ├── publication.py     # manifest 校验、发布、回滚、index
  └── corpus.py          # 只保留工作流编排和 CLI

  现有 catalog.py、contention.py、slice.py 和 multi_job.py 已经是不错的基础。

  ## 次要问题

  ### 1. 可抢占与不可抢占命名仍不完全对称

  目前：

  src/llm_structured/*.py

  实际上主要是可抢占旧实现，而不可抢占放在：

  src/llm_structured/nonpreemptive/

  这在概念上不够清楚，理想状态应是：

  src/llm_structured/
  ├── preemptive/
  └── nonpreemptive/

  但移动可抢占代码会影响大量 import、registry 和历史实验。当前不可抢占任务不需要为目录好看而迁移另一条线。

  建议：

  - 现在不移动；
  - 不再向 src/llm_structured/ 顶层增加新的语义专属代码；
  - 将来单独制定兼容迁移，通过旧模块转发到 preemptive/；
  - 不与当前性能和 benchmark 工作混在一次提交中。

  ### 2. experiments 目录开始变得扁平

  experiments/llm_structure/nonpreemptive/ 已有十几个 stage4*.py。但这些入口与历史文档已经绑定，批量移动对研究复现帮助不大。

  建议保留现有 4a–4e runner 不动，新基础工作放入：

  experiments/llm_structure/nonpreemptive/foundation/
  ├── runtime_diagnosis.py
  ├── conversion_fidelity.py
  ├── contention_census.py
  └── hard_slice_validation.py

  这样既不破坏历史入口，也不会继续增加顶层文件。

  ### 3. 公共元数据有少量陈旧内容

  例如：

  - src/llm_structured/__init__.py:1 仍写着只处理 communication-resume；
  - pyproject.toml:9 的项目描述仍只有 Preemptive；
  - 非抢占 registry 项没有明确填写 semantics，默认值还是 "none"；
  - Stage 4c/d/e 有稳定源码，但没有统一标识它们是研究工具、否定结果还是可部署算法。

  这些修改风险较低，可以在结构重构后顺手修正。

  ### 4. egg-info 和 __pycache__ 不是架构问题

  当前存在：

  - src/dag_heuristic.egg-info/
  - 多处 __pycache__/

  它们是安装和运行 Python 生成的临时产物，已经被 Git 忽略。可以清理，但不会解决职责混乱。

  ## 推荐重构顺序

  ### 第一阶段：必须做

  1. 新建 src/llm_structured/nonpreemptive/runtime/。
  2. 移入公共 adapter、Mode、ActionSignature、冻结 LT、WAIT 和 completion。
  3. Stage 4a、4d、4e 全部改用同一实现。
  4. 用30个真实小图做 makespan 和 trace hash 对拍。
  5. 固定一次“只有一个基线实现”的测试。

  ### 第二阶段：为新 benchmark 工作做准备

  1. 拆分 corpus.py 的 selection 和 publication。
  2. 新增 foundation/ 实验入口。
  3. 建立 bare/validated/instrumented 三条回放路径。
  4. 统一实验结果字段和 timeout 表达。

  ### 第三阶段：条件性拆分

  1. 在测试充分后拆多资源 solver.py。
  2. 暂不移动可抢占顶层模块。
  3. 暂不重排已有实验文件。
  4. 不把 packing/barrier/selective 强行合成一个综合包。

  总体上，我的判断是：

  > 当前代码的算法隔离基本合格，src 也没有反向导入 experiments 或 benchmark_generate；真正需要修的是不可抢占公共运行能力放错目录、基线重复实现和 corpus 职责过重。做一次小而集中的重构很有必要。