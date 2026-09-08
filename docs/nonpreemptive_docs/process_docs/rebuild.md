不可抢占的 interface.py 目前只有两个 Protocol，几乎没有形成真正的
  family 边界；算法名称、参数绑定和 solver 调用全堆在 src/registry.py 里，导致全局注册表过重。

  建议改成两层职责：

  - 各 family 的 interface.py
      - 校验该 family 的输入。
      - 保存该 family 的算法名称到实现的映射。
      - 处理算法参数。
      - 提供统一的 solve(...)。
      - 输入应是内部 DAG、ParallelChain 或多资源实例，不直接处理 Benchmark。

  - registry.py
      - 根据 benchmark 的语义、场景和 family 选择对应 interface。
      - 完成 Benchmark -> DAG/多资源实例 的转换。
      - 保存描述、是否 Exact、是否支持 WAIT、开发状态等全局元数据。
      - 调用 interface.solve()，不再直接调用具体 solver。

  例如 complex-chain 不可抢占可以形成：

  def solve(
      dag: DAG,
      algorithm: str = "longest_tail",
      *,
      mode: Mode = "optional_idle",
      **options: object,
  ) -> Result:
      validate_complex_chain(dag)

      algorithms = {
          "longest_tail": ...,
          "join_bonus": ...,
          "rollout_flow2": ...,
          "rollout_wait2": ...,
          "depth2_wait2": ...,
          "beam_wait8": ...,
          "exact_optional": ...,
      }

      ...

  然后 registry.py 只保留类似：

  lambda benchmark: interface.solve(
      to_dag(benchmark),
      "longest_tail",
      mode="optional_idle",
  )

  不过不建议直接照抄当前可抢占 interface 的所有细节，因为它也有两个问题：

  - 算法字典在每次 solve() 时重新创建。
  - options 依靠多个 if algorithm == ... 单独分派，算法多了以后仍会膨胀。

  更稳妥的是在各 interface 中建立模块级的算法规格表，例如同时记录实现、允许参数、默认模式。这样算法映射只有一
  份，registry.py 只补充面向 CLI 的描述信息。

  还有两个边界需要保持：

  1. 不可抢占必须明确区分 optional_idle 和 work_conserving，不能仅靠算法名称含有 wait 来推断完整语义。
  2. Exact 实现仍然属于 core.oracle。interface 可以注册和调用 Exact，但不能把 Exact 实现搬回 family 目录。

  建议这次同时整理以下三个不可抢占入口：

  - single_channel/parallel_chain/nonpreemptive/interface.py
  - single_channel/complex_chain/nonpreemptive/interface.py
  - muti_channel/nonpreemptive/interface.py

  然后让 registry.py 只承担顶层索引和 Benchmark 适配。整个修改不需要触碰 src/core，符合刚加入的模块边界约定。


## 完成记录

- 三个不可抢占 family interface 已提供统一的 `solve(...)` 入口和模块级算法规格表。
- `optional_idle` 与 `work_conserving` 作为显式 `mode` 传入；Exact 仍调用
  `core.oracle`，没有复制到 family 目录。
- `registry.py` 现在只负责 Benchmark 转换、算法元数据和调用对应 interface，
  不再直接调用不可抢占 solver。
- 定向回归通过：95 passed。
