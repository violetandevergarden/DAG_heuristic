### 1. corpus.py 还有重复发布实现

  当前 corpus.py 中旧的 publish() 和 candidate 校验代码仍存在，文件末尾又重新导入了新 publication.publish。

  Ruff 已经报告：

  - publish 重复定义；
  - import alias 无意义；
  - import 顺序问题。

  所以目前 publication 是“新模块已经建立，但旧职责还没真正删干净”。

  需要删除 corpus.py 中旧的：

  - _validate_candidate；
  - publish；
  - 相关发布辅助逻辑。

  只保留兼容导入和 CLI 编排。

  ### 2. 新 runtime 代码格式比较仓促

  不少代码压成了一行，例如 adapter、policy 和 publication。功能可以运行，但可读性不够，也不利于后续性能分析。

  Ruff 当前13项问题主要包括：

  - import 顺序；
  - 未使用 import；
  - __all__ 排序；
  - corpus 重复定义；
  - 局部格式问题。

  这批问题应全部清零后，才能称为结构重构完成。

  ### 3. Foundation 入口目前只是骨架

  例如 runtime_diagnosis.py 虽然接受：

  - bare；
  - validated；
  - instrumented；

  但三种路径实际上都调用同一个 replay()。目前只有 instrumented 多开了 tracemalloc，并没有真正把：

  - 裸策略循环；
  - trace 生成与验证；
  - 特征观测；

  拆成三条不同执行路径。

  因此基础诊断入口已经有目录，但 P0 性能定责能力还没有完成。

  ### 4. 多资源 solver.py 还没有真正拆分

  现在只是：

  公开 replay_actions
      ↓
  旧 solver._replay

  下一步可以再把 replay 实现移动出来，但不建议立刻同时拆状态机、Exact、lower bound 和 rollout。先把 _replay 的实际代码迁
  入公开模块、旧函数反向兼容转发即可。