# 可抢占主线目录迁移勘误与修正计划（2026-08-15）

## 1. 文档目的

本文是对以下文档及其后续实施结果的补充勘误：

- `preemptive_code_review_20260815.md`；
- `preemptive_code_review_modification_plan_20260815.md`；
- `docs/result_docs/preemptive_migration_implementation_result_20260815.md`。

上一轮实施已经完成 v2 work-conserving 合同、单/多资源 Trace 回放、独立极小图 Oracle、benchmark/reference 重建和实验复核，但目录迁移只完成了一部分。上一轮结果报告将 M0--M6 描述为已经完整完成，这一表述不准确。

准确状态应为：

- v2 核心语义修复和正确性防线已经完成；
- v2 实际实现已经进入新的场景目录；
- nonpreemptive 实际实现、测试和 benchmark 仍有旧布局残留；
- `src/preemptive/` 和 family 根目录仍存在兼容层或旧实现；
- 因此“双语义平等的最终目录迁移”尚未完成。

本文解释这些偏差的原因，并给出后续只改变目录和公开合同、不改变调度数值的修正计划。本文不覆盖原审查材料，也不否定已经通过回归的 v2 语义修复。

## 2. 当前问题与原因

### 2.1 `core/execution` 和 `core/trace` 缺少 nonpreemptive

当前目录只有：

```text
src/core/execution/
├── common.py
└── preemptive.py

src/core/trace/
├── common.py
└── preemptive.py
```

历史 v1 状态机、Trace 数据和相关逻辑仍主要位于：

```text
src/core/model.py
src/core/oracle.py
```

这与原修改计划明确列出的目标结构不同：

```text
src/core/execution/{common,preemptive,nonpreemptive}.py
src/core/trace/{common,preemptive,nonpreemptive}.py
```

偏差原因是实施时错误地把“v1 是 maintenance”解释成“v1 可以继续留在旧位置”。正确解释应当是：preemptive 和 nonpreemptive 在目录、接口和身份上平等，只在 registry metadata 中分别标记 `active` 与 `maintenance`。

这属于未完成的结构迁移，不是合理的最终架构。

### 2.2 family 根目录仍承载旧 v1 实现

当前三个 family 仍存在根目录实现：

```text
src/single_channel/parallel_chain/{interface.py,solver.py}
src/single_channel/complex_chain/{interface.py,solver.py}
src/muti_channel/{interface.py,solver.py}
```

现有 `nonpreemptive/` 实际上反向转发到这些根目录文件。例如：

```text
parallel_chain/nonpreemptive/solver.py
    -> parallel_chain/solver.py
```

这只建立了表面上的 sibling package，没有把实际实现迁入 `nonpreemptive/`。正确关系应当是：

```text
parallel_chain/nonpreemptive/solver.py   # v1 真正实现
parallel_chain/preemptive/solver.py      # v2 真正实现
```

family 根目录最多只能在明确兼容期内保存转发 shim，最终不应承载任何一种执行语义的实际 solver 或 interface。

偏差原因是上一轮为了降低一次性移动量，先创建了 wrapper，却没有继续完成实际文件移动和 wrapper 删除。这是半迁移状态。

### 2.3 `src/preemptive/` 仍然存在

原修改计划允许：

1. 先保留 `src/preemptive/` 作为旧 import 的 compatibility shim；
2. 一个兼容周期后删除；
3. 禁止新代码继续依赖旧路径。

当前 `src/preemptive/` 已基本只保存转发，但没有定义兼容对象、兼容周期、移除版本或删除条件。与此同时，上一轮结果报告已经把目录迁移描述为完成。

因此问题不在于“曾经保留 shim”，而在于：

- 没有把 shim 明确标记成有截止条件的临时状态；
- 没有确认仓库内部 import 清零后立即删除；
- 在 shim 尚未退出时提前宣布完成。

当前仓库内部已经没有继续发展 `src/preemptive/` 实际逻辑的理由。完成公开 import、测试和文档迁移后，应删除整个目录。

### 2.4 benchmark、generator 和 tests 未形成双语义对称结构

当前 benchmark 布局是：

```text
benchmark/single_channel/...       # 隐式 nonpreemptive v1
benchmark/muti_channel/...         # 隐式 nonpreemptive v1
benchmark/preemptive/...           # 显式 preemptive v2
```

当前 tests 布局类似：

```text
tests/single_channel/...           # 隐式 v1
tests/muti_channel/...             # 隐式 v1
tests/preemptive/...               # 显式 v2
```

`benchmark_generate` 也仍通过两套不对称路径工作：v1 导出使用 family 根目录实现和旧路径，v2 使用单独的 preemptive 导出逻辑。

其中需要区分两件事：

1. tests 和 generator 的不对称不符合原修改计划中“tests 镜像二维目录”和“双语义平等”的要求，属于迁移未完成；
2. benchmark 路径暂不移动是原修改计划明确记录的兼容决定。原计划要求，如果以后改成完全对称布局，必须提供单独的版本化迁移和 reference path 映射。

因此，保留旧 benchmark 路径不是当时的局部实现错误，但它只能被描述为过渡兼容状态，不能与“最终平等结构已经完成”同时成立。既然当前目标进一步明确为结构平等，就应执行独立、可审计的 benchmark 路径迁移。

## 3. 修正原则

后续修正遵循以下原则：

1. preemptive 和 nonpreemptive 是两个平等的执行语义维度；
2. `active` 与 `maintenance` 只通过 metadata、README 和 registry capability 表达，不编码成旧目录、隐式目录或贬义名称；
3. 目录迁移不得改变任何合法 schedule、Exact makespan 或 historical reference；
4. 不在一个提交中同时移动文件和修正算法语义；
5. benchmark 路径属于公开格式，必须提供版本化映射，不能静默搬迁；
6. compatibility shim 必须有明确移除条件，不能无限期存在；
7. tests 必须镜像生产代码的 family × semantics 二维结构；
8. registry、generator 和 CLI 只能根据显式 semantics 路由，不能根据旧路径或命名前缀猜测；
9. 不修改 `muti_channel` 的现有公开拼写；
10. 不重写已经通过回归的 v1/v2 算法。

## 4. 最终目标结构

### 4.1 源码

```text
src/
├── core/
│   ├── execution/
│   │   ├── common.py
│   │   ├── preemptive.py
│   │   └── nonpreemptive.py
│   ├── trace/
│   │   ├── common.py
│   │   ├── preemptive.py
│   │   └── nonpreemptive.py
│   └── ...
├── single_channel/
│   ├── parallel_chain/
│   │   ├── preemptive/
│   │   │   ├── interface.py
│   │   │   └── solver.py
│   │   └── nonpreemptive/
│   │       ├── interface.py
│   │       └── solver.py
│   └── complex_chain/
│       ├── preemptive/
│       │   ├── interface.py
│       │   └── solver.py
│       └── nonpreemptive/
│           ├── interface.py
│           └── solver.py
├── muti_channel/
│   ├── preemptive/
│   │   ├── interface.py
│   │   ├── solver.py
│   │   └── trace.py
│   └── nonpreemptive/
│       ├── interface.py
│       └── solver.py
└── llm_structured/
    ├── repetition.py
    └── multi_job.py
```

最终不再存在：

```text
src/preemptive/
src/single_channel/parallel_chain/solver.py
src/single_channel/parallel_chain/interface.py
src/single_channel/complex_chain/solver.py
src/single_channel/complex_chain/interface.py
src/muti_channel/solver.py
src/muti_channel/interface.py
```

family 根目录只保留 package 文档或最小 `__init__.py`，不默认导出某一种语义。

### 4.2 Benchmark

建议采用与源码一致的 family → semantics 结构：

```text
benchmark/
├── single_channel/
│   ├── parallel_chain/
│   │   ├── preemptive/{random,adversarial,real}/
│   │   └── nonpreemptive/{random,adversarial,real}/
│   └── complex_chain/
│       ├── preemptive/{random,adversarial,real}/
│       └── nonpreemptive/{random,adversarial,real}/
├── muti_channel/
│   ├── preemptive/{random,adversarial,real}/
│   └── nonpreemptive/{random,adversarial,real}/
├── reference_results/          # 完全镜像上述相对路径
└── schema/
```

现有 benchmark ID、文件名和 JSON 内容在路径迁移阶段保持不变。历史 `pm_`、`_np` 前后缀暂不改名，避免把目录迁移、ID 迁移和实验引用迁移混成一次破坏性变更。

### 4.3 Tests

```text
tests/
├── core/
│   ├── execution/
│   │   ├── preemptive/
│   │   └── nonpreemptive/
│   └── trace/
│       ├── preemptive/
│       └── nonpreemptive/
├── single_channel/
│   ├── parallel_chain/{preemptive,nonpreemptive}/
│   └── complex_chain/{preemptive,nonpreemptive}/
├── muti_channel/{preemptive,nonpreemptive}/
├── llm_structured/
└── integration/
```

integration 仍按外部依赖隔离，但测试名和 fixture 必须明确使用的执行语义。

## 5. 分阶段修正计划

### P0：冻结当前基线并发布勘误

工作：

1. 将本文作为上一轮迁移报告的正式勘误；
2. 保存当前 76 项测试、139 个 benchmark、66 个 reference 和所有 Exact 数值；
3. 输出当前路径到目标路径的机器可读映射草案；
4. 记录当前 base commit、dirty 状态、Python、seed、state/time budget；
5. 标记上一轮结果为“语义修复完成、目录迁移未完成”。

验收：

- 迁移前 v1/v2 的 benchmark hash、reference、makespan 和关键 action 序列均有可重放基线；
- 后续每个阶段都能与该基线逐项比较。

### P1：迁移 nonpreemptive core

工作：

1. 将 `src/core/model.py` 中的 v1 状态转移迁入 `src/core/execution/nonpreemptive.py`；
2. 将 v1 Trace 数据、断言和回放入口整理到 `src/core/trace/nonpreemptive.py`；
3. 只把确实跨语义共享的数据结构放入 `common.py`；
4. 更新 `core/oracle.py`、conversion、registry 和测试 import；
5. 迁移阶段允许 `core/model.py` 短期转发，仓库内部 import 清零后删除；
6. 本阶段不改变 v1 的合法动作、optional idle、资源保留或 Exact 状态定义。

验收：

- v1 全部 historical Exact/reference 不变；
- preemptive transition 不导入 nonpreemptive transition，反向也不导入；
- 两者实现共同的只读 scheduler/result protocol；
- `core/execution` 和 `core/trace` 同时具有两个显式语义模块。

### P2：物理迁移三个 family 的 v1 实现

执行真实文件移动：

| 当前实际实现 | 目标实际实现 |
|---|---|
| `single_channel/parallel_chain/solver.py` | `single_channel/parallel_chain/nonpreemptive/solver.py` |
| `single_channel/parallel_chain/interface.py` | `single_channel/parallel_chain/nonpreemptive/interface.py` |
| `single_channel/complex_chain/solver.py` | `single_channel/complex_chain/nonpreemptive/solver.py` |
| `single_channel/complex_chain/interface.py` | `single_channel/complex_chain/nonpreemptive/interface.py` |
| `muti_channel/solver.py` | `muti_channel/nonpreemptive/solver.py` |
| `muti_channel/interface.py` | `muti_channel/nonpreemptive/interface.py` |

随后更新：

- registry；
- benchmark generator；
- conversion 和 fixture；
- tests；
- README 和 CLI 示例。

验收：

- `nonpreemptive/` 中保存真实实现，不再反向导入 family 根目录 solver；
- family 根目录不再隐式代表 v1；
- v1 benchmark 和 Exact 数值不变。

### P3：退出旧源码兼容层

工作：

1. 更新所有仓库内部 import 到新路径；
2. 检查是否存在明确记录的仓库外消费者；
3. 若没有必须保留的外部兼容合同，删除整个 `src/preemptive/`；
4. 删除 family 根目录临时 solver/interface shim；
5. family `__init__.py` 不再 wildcard 导出某一种语义；
6. 增加结构测试，禁止旧 import 路径重新出现。

验收命令：

```powershell
rg "from preemptive|import preemptive" src tests benchmark_generate
rg "from single_channel\.(parallel_chain|complex_chain)\.solver" src tests benchmark_generate
rg "from muti_channel\.solver" src tests benchmark_generate
```

三组检查均无结果，且旧目录/文件不存在。

### P4：版本化迁移 benchmark 和 reference 路径

工作：

1. 确定新的 benchmark layout version；JSON schema version 继续表达执行语义，不与路径版本混用；
2. 按第 4.2 节移动全部 139 个 benchmark；
3. `reference_results` 完全镜像新路径；
4. 新增机器可读 old-path → new-path migration manifest；
5. `benchmark/index.jsonl` 增加显式 `semantics` 和 layout version；
6. 更新 README、CLI 示例、study runner 和文档引用；
7. 不保留重复旧副本，防止一次实验重复读取同一图；
8. 不在本阶段重命名 benchmark ID 或历史文件名。

验收：

- 纯路径移动前后每个 benchmark 原始字节 hash 不变；
- 每个 reference 的 `benchmark_sha256` 继续对应同一问题文件；
- old-path → new-path 映射覆盖全部移动文件；
- 任一 benchmark 仅从路径和 JSON semantics 都能确定执行语义；
- v1/v2 不再有隐式默认路径。

### P5：统一 benchmark generator

工作：

1. 增加唯一的路径构造函数，输入为 `(semantics, scenario, family, category, id)`；
2. v1/v2 exporter 都调用该函数，不再分别手写路径；
3. `all` 命令可生成两套语义，另提供 semantics 过滤参数；
4. reference generator 只读取 JSON semantics，不根据目录或文件名前缀猜测；
5. index generator 输出相同的 semantics/layout 字段；
6. study runner 继续位于 `benchmark_generate/studies/`，调度算法不得导入生成器。

验收：

- 同一 benchmark 只存在一条规范输出路径；
- v1/v2 使用同一套目录构造和 index 逻辑；
- generator 的固定 seed 输出与迁移后的 committed suite 一致。

### P6：镜像迁移 tests

工作：

1. 将现有 `tests/preemptive/` 拆到对应 family 的 `preemptive/` 目录；
2. 将现有 v1 family 测试移入 `nonpreemptive/`；
3. shared execution/trace 测试放入 `tests/core/`；
4. tiny tick Oracle 移入明确的 test-only oracle/helper 目录；
5. repetition 和 multi-job 测试移入 `tests/llm_structured/`；
6. integration 继续隔离 SimAI，但文件名和 fixture 标注语义；
7. 添加结构测试，拒绝隐式 semantics 目录和旧 import。

验收：

- tests 目录与 src 的 family × semantics 结构一致；
- 纯单元测试不依赖 SimAI；
- v1/v2 回归可以分别运行，也可以一次完整运行；
- 测试数量变化仅来自文件拆分或新增结构断言，不丢失现有覆盖。

### P7：全量重建、实验复核和结果勘误

工作：

1. 重新生成 index 和 reference；
2. 重跑全部 v1/v2 Exact reference；
3. 重跑阶段 0--4、阶段 5、阶段 6；
4. 分别报告 random、adversarial、real；
5. 检查 CLI 对同名算法是否根据 semantics 正确路由；
6. 检查旧 import、旧目录和重复 benchmark 是否全部清零；
7. 在 `docs/result_docs/` 新增修正后的最终迁移报告，不覆盖旧历史报告。

最终验收：

- v2 是唯一默认 active mainline；
- v1 是显式、平等目录下的 maintenance baseline；
- `src/preemptive/` 不存在；
- family 根目录不存在隐式 v1 solver/interface；
- core、src、benchmark、generator 和 tests 都显式表达 semantics；
- 历史 v1 和当前 v2 的 Exact 数值均未因目录迁移改变；
- 全部 benchmark/reference hash、index 和路径映射一致；
- `python -m pytest -q`、`git diff --check` 和可用的 lint 检查全部通过。

## 6. 建议提交拆分

为避免再次产生无法审查的半迁移，建议使用以下独立提交：

1. `docs: correct the incomplete semantics-directory migration status`；
2. `refactor(core): move nonpreemptive execution and trace into semantic modules`；
3. `refactor(single-channel): move v1 implementations under nonpreemptive packages`；
4. `refactor(muti-channel): move v1 implementation under nonpreemptive package`；
5. `refactor: remove obsolete preemptive and family-root compatibility paths`；
6. `data: migrate benchmarks and references to symmetric semantics paths`；
7. `refactor(generator): unify semantics-aware export and index paths`；
8. `test: mirror family and semantics directory structure`；
9. `docs: publish final symmetric-migration verification results`。

每个代码移动提交都先运行对应语义的小测试；P1--P5 涉及公共模型、Oracle、转换、schema/index 或 reference 时必须运行完整测试。任何数值差异都应先停止迁移并保存逐实例对比，不能把差异解释成普通路径变化。

## 7. 本次勘误结论

上一轮已经完成的 v2 行为修复和实验复核仍然有效，但不能再把当前仓库描述为已经完成双语义平等迁移。下一轮工作的首要目标不是继续增加 heuristic，而是把现有半迁移状态收敛为明确、对称、无旧路径依赖的最终结构，并用不变的 v1/v2 Exact 结果证明这次目录修正没有改变研究语义。
