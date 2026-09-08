  还剩两个小问题。

  1. 部分调用方没有传 mode

  以下调用仍然只验证公共不可抢占语义，无法检查 work-conserving 是否违规：

  - parallel_chain solver (src/single_channel/parallel_chain/nonpreemptive/solver.py:674)
  - complex_chain solver (src/single_channel/complex_chain/nonpreemptive/solver.py:274)
  - complex_chain test (tests/single_channel/complex_chain/nonpreemptive/test_complex_chain.py:32)

  如果这些入口明确知道运行模式，建议传入 mode。如果算法固定属于 optional-idle，也应显式写 "optional_idle"，避免以后误以
  为已经验证了 work-conserving 约束。

  2. 独立 replay 中有重复构造索引

  src/core/trace/nonpreemptive.py:295 的 _ready_flows() 和 src/core/trace/nonpreemptive.py:318 的 _advance_state() 会反
  复构造：

  index = {task_id: position for position, task_id in enumerate(task_ids)}

  一次 trace 有很多 transition 时，会重复做 O(N) 工作。可以在 replay_nonpreemptive_trace() 开头创建一次 index，传给辅助
  函数。不过 trace 验证不是求解热路径，这只是低优先级性能整理。

  本次已完成：

  - parallel-chain、complex-chain 及对应测试的不可抢占 replay 校验均显式传入 `mode="optional_idle"`。
  - `replay_nonpreemptive_trace()` 现在只在入口构造一次 task index，并传给 replay 辅助函数。
  - 单/多资源模型统一使用 `NonPreeSingleModel`、`NonPreeMultiModel`、`PreeSingleModel` 和 `PreeMultiModel`；旧兼容别名已删除。
  - `src/core/trace/common.py` 已更名为 `src/core/trace/contracts.py`，所有代码引用已迁移。
