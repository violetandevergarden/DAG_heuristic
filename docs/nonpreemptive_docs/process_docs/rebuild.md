# `benchmark/` 目录与 LLM 语料整理计划

> 状态：待执行
>
> 范围：整理 `benchmark/` 中的迁移记录、索引、说明文档，以及 `benchmark/llm_structure/` 的语义目录、清单和来源记录。
>
> 只调整数据集目录、清单、生成路径和验证规则，不改变 DAG、任务时长、依赖、资源集合、调度语义、实验划分和研究结论；不修改 `src/core`。

## 1. 上一轮重构验收

上一轮 `benchmark_generate` LLM 入口与命名重构已经完成：

- `benchmark_generate/llm_structure.py` 已删除，活动代码中没有旧模块导入；
- `llm/nonpreemptive/multi_job.py` 薄转发已删除，组合实现统一位于 `llm/common/multi_job.py`；
- `contention_audit.py`、`corpus_selection.py`、`corpus_publication.py`、`multi_job_suite.py` 和 `synthetic_multi_job.py` 等新名称已经生效；
- 旧名称只存在于本地 `__pycache__`，不属于源码或兼容入口；
- `compileall` 通过，相关定向测试 `20 passed`，完整回归 `285 passed in 128.76s`；
- 没有修改 `src/core`。

旧计划因此删除，下面只保留新的 benchmark 整理计划。

## 2. 当前审查结论

### 2.1 完整性现状

当前 `benchmark/index.jsonl` 有 290 条记录，仓库中也恰好有 290 个应作为 benchmark 读取的 JSON：

- 没有未进入公共索引的 benchmark JSON；
- 没有公共索引指向不存在的文件；
- 没有残留 `.staging`、临时文件或隐藏生成目录；
- `llm_structure` 当前有 72 个可抢占和 47 个不可抢占 benchmark。

所以问题不是大量无主 benchmark，而是正式输入、语义清单、来源目录、运行记录和历史迁移表混在同一层，部分目录名称也没有稳定表达数据性质。

### 2.2 不得误删的内容

- `pm_*.json` 和 `np_*.json` 是两种语义下的正式样例，不是简单副本；
- 两种语义下同名或结构相近的文件是受控配对及回归资产；
- `schema` 中 v1 至 v3 是格式版本，不是临时文件；
- `reference_results` 只保存取得有效 Exact 结果的样例，目录不完全对称是允许的。

任何删除都必须依据清单、引用和研究用途，不能依据前缀、文件数量或名称相似程度。

### 2.3 主要问题

1. `path_migration_v1_to_v2.jsonl` 是一次性迁移记录，却仍由生成器产生并由测试强制保留；
2. `manifest.jsonl` 与 `nonpreemptive_manifest.jsonl` 命名不对称，并都位于语义目录外；
3. 两种语义的 source catalog、topology catalog 和 run metadata 平铺在 `llm_structure` 根目录；
4. `unified`、`routed`、`real_derived` 混用了资源模型、转换来源和派生方式三种分类；
5. `benchmark/README.md` 仍记录旧的 215 个问题，`llm_structure/README.md` 仍把不可抢占目录描述为空占位；
6. 公共 index、语义 corpus manifest 与实验 manifest 的角色不清；
7. 可抢占 LLM JSON 约 1.77 GB，但常规回归、规模样例和示例投影的加载边界不够明确。

## 3. 整理原则

### 3.1 三种清单各司其职

- `benchmark/index.jsonl`：所有可加载 benchmark 的库存索引，只负责路径、格式、语义和哈希完整性；
- 语义目录的 `manifest.jsonl`：对应 Stage 4 corpus 的来源、转换、竞争证据、发布状态和准入信息；
- `experiments/**/manifests/*.jsonl`：某次实验的输入选择和数据划分。

进入公共 index 不等于已经通过竞争准入，也不等于应参加所有实验。runner 必须显式读取语义或实验 manifest，不能通过递归目录形成实验集合。

### 3.2 只迁移路径，不修改内容

本轮迁移前后，每个 benchmark 的内容哈希必须保持不变。格式化、字段补充或语义修正应作为独立数据迁移，不能夹带在目录整理中。

迁移期间不得长期保存新旧两份 JSON。正式发布后只保留一个物理文件，短期路径映射只用于核对引用。

## 4. 目标目录

```text
benchmark/
├── README.md
├── index.jsonl
├── schema/
├── single_channel/
├── muti_channel/
├── reference_results/
└── llm_structure/
    ├── README.md
    ├── preemptive/
    │   ├── manifest.jsonl
    │   ├── provenance/{source_catalog,topology_catalog,run_metadata}.jsonl
    │   ├── single_channel/
    │   ├── fixed_multi_resource/<topology_tag>/
    │   ├── multi_iteration/
    │   └── examples/
    └── nonpreemptive/
        ├── manifest.jsonl
        ├── provenance/{source_catalog,topology_catalog,run_metadata}.jsonl
        ├── single_channel/
        ├── fixed_multi_resource/
        ├── decision_slices/
        └── multi_job/
```

`provenance` 是数据集发布记录，不是调度输入。算法不得读取；生成器和审计工具可以使用，普通 loader 只按 index 或 manifest 中的 benchmark 路径加载 JSON。

## 5. 具体迁移

### 5.1 清单与来源记录

| 当前路径 | 目标路径 |
| --- | --- |
| `llm_structure/manifest.jsonl` | `llm_structure/preemptive/manifest.jsonl` |
| `llm_structure/source_catalog.jsonl` | `llm_structure/preemptive/provenance/source_catalog.jsonl` |
| `llm_structure/topology_catalog.jsonl` | `llm_structure/preemptive/provenance/topology_catalog.jsonl` |
| `llm_structure/run_metadata.jsonl` | `llm_structure/preemptive/provenance/run_metadata.jsonl` |
| `llm_structure/nonpreemptive_manifest.jsonl` | `llm_structure/nonpreemptive/manifest.jsonl` |
| `llm_structure/nonpreemptive_source_catalog.jsonl` | `llm_structure/nonpreemptive/provenance/source_catalog.jsonl` |
| `llm_structure/nonpreemptive_topology_catalog.jsonl` | `llm_structure/nonpreemptive/provenance/topology_catalog.jsonl` |
| `llm_structure/nonpreemptive_run_metadata.jsonl` | `llm_structure/nonpreemptive/provenance/run_metadata.jsonl` |

生成器、恢复、审计、发布、回滚、实验和测试必须通过统一布局函数取得路径，不再散布字符串拼接。

### 5.2 benchmark 子目录

| 当前路径 | 建议路径 | 理由 |
| --- | --- | --- |
| `preemptive/unified` | `preemptive/single_channel` | `unified` 没有表达资源模型 |
| `preemptive/routed/<tag>` | `preemptive/fixed_multi_resource/<tag>` | 固定多资源是稳定执行性质，route 只是产生资源集合的方式 |
| `preemptive/simai_examples` | `preemptive/examples` | 明确示例投影，不与正式真实语料混称 |
| `nonpreemptive/routed` | `nonpreemptive/fixed_multi_resource` | 与可抢占统一资源模型命名 |
| `nonpreemptive/real_derived` | `nonpreemptive/decision_slices` | 当前内容是从真实 DAG 提取的决策切片 |

`multi_iteration` 与 `multi_job` 不合并：前者是单 job 多轮展开，后者是多个 job 的组合，优化目标和到达事件不同。

可抢占方向不进行算法或性能重构；这里对它的修改仅用于统一数据布局。如果大文件路径迁移风险过高，可先完成 manifest 下沉和 provenance 归位，再单独执行目录改名。

### 5.3 退出历史迁移表

`path_migration_v1_to_v2.jsonl` 当前仍被 `benchmark_generate/export.py` 生成，并被 `tests/test_semantics_layout.py` 检查，不能先删文件再处理调用方。

1. 确认 loader、CLI、实验和发布流程均不读取它；
2. 将长期有价值的迁移结论记录到 process document，逐文件映射继续由 Git 历史保存；
3. 删除 `export.py` 中再次生成旧迁移表的逻辑；
4. 把测试改为检查当前规范布局、路径语义和 index 完整性；
5. 最后删除 `benchmark/path_migration_v1_to_v2.jsonl`。

本轮 LLM 路径调整可以产生一次性核对表，但应放在执行结果目录，不再成为永久 benchmark 文件。

## 6. 大文件与正式语料边界

语义 manifest 应规范以下字段：

- `publication_status`；
- `collection`：例如 `canonical`、`scale`、`example`；
- `size_tier`、`task_count`；
- `contention_evidence_level` 和竞争分类；
- `source_group`、`topology_tag`、iteration/job 数；
- `content_hash`。

并遵守：

- 格式测试可检查所有文件，但不得完整回放全部大图；
- 常规算法回归只读取明确的小型 canonical 子集；
- 大图只能由规模实验或显式参数选入；
- examples 可以进入库存 index，但不能混入真实语料结论；
- 是否移除大图必须依据 Stage 4 计划、实验引用和可再现性单独决定；
- 本计划不直接删除现有 72 个可抢占或 47 个不可抢占 LLM benchmark。

## 7. README 与命名规则

必须修正两份 README 中的过期数量、不可抢占空占位描述、旧路径和旧生成入口，并解释三种 manifest 的边界。

README 不再手工维护容易过期的细分数量。统计应由审计命令从 index 和 manifest 生成，README 只记录统计日期和生成命令。

现有稳定 benchmark ID 和文件名暂不批量改写，避免破坏实验追踪。以后新增文件遵守：

- 语义由父目录表达；
- ID 不包含 `stage4a`、`stage4f` 等会变化的研究阶段，阶段归属写入 manifest；
- 多 job 名称表达 job 数、同构或异构、到达方式和资源模型；
- 决策切片保留 source ID 和稳定 slice ID；
- 未经认证的拓扑不得在名称或文档中描述成生产真实拓扑。

## 8. 实施批次

### 批次 A：建立审计基线

1. 保存当前 290 条 index 路径、内容哈希和语义分布；
2. 保存两个 LLM manifest 的 ID、路径、hash、发布状态和实验引用；
3. 扫描源码、测试、实验和 README 中的硬编码路径；
4. 增加实际 JSON、公共 index、语义 manifest 三方一致性审计；
5. 检查 reference result 的 `benchmark_hash` 仍能找到对应输入。

### 批次 B：下沉清单和来源记录

1. 扩展统一布局函数；
2. 修改生成、resume、audit、publish 和 rollback 路径；
3. 移动两个 manifest 与 provenance；
4. 更新实验和测试；
5. 验证失败发布不会破坏活动 corpus 和公共 index。

### 批次 C：迁移 LLM benchmark 目录

1. 建立第 5.2 节的新目录；
2. 只移动文件，不重新序列化 JSON；
3. 更新语义 manifest、公共 index、实验 manifest 和固定 fixture 路径；
4. 验证迁移前后 ID 集合与内容 hash 完全相同；
5. 删除空旧目录，不保留双份 benchmark。

### 批次 D：退出历史迁移机制并更新文档

1. 停止生成 `path_migration_v1_to_v2.jsonl`；
2. 改写依赖它的测试并删除文件；
3. 清理只为旧路径存在的兼容逻辑；
4. 更新两份 README。

### 批次 E：增加加载保护

1. 规范 collection 和 size 字段；
2. 常规 runner 必须显式选择集合，不得递归目录作为默认语料；
3. 大图测试使用流式清单检查，避免无意加载约 1.77 GB；
4. 输出 canonical、scale、example、decision slice 和 multi-job 的统计；
5. 只列出可能缩减的候选，不在本轮自动删除正式语料。

## 9. 验证要求

```powershell
python -m compileall -q benchmark_generate experiments tests
python -m pytest -q tests/test_benchmark_format.py tests/test_semantics_layout.py
python -m pytest -q tests/test_llm_catalog.py tests/test_llm_corpus.py
python -m pytest -q tests/integration/test_nonpreemptive_stage4a.py
python -m pytest -q
```

还必须生成机器可检查的迁移报告，证明：

- 整理前后 benchmark 数量和 ID 集合一致；
- 每个移动文件的 SHA-256 不变；
- index 没有重复路径、重复 ID、漏项或悬空项；
- 两个语义 manifest 只引用本语义目录；
- manifest 的 `content_hash` 与实际文件一致；
- 实验 manifest 的路径全部可解析；
- reference result 仍对应相同内容；
- examples 不会被误选为真实 corpus；
- 常规测试不会默认加载全部大图；
- staging、resume、publish 和 rollback 保持原子性；
- 没有改变任何 benchmark 的 DAG、语义或资源内容；
- 没有修改 `src/core`。

## 10. 完成条件

1. 历史迁移表已退出正式 benchmark 根目录，生成器和测试不再依赖；
2. 两种语义的 LLM manifest 均位于各自目录；
3. catalog 与 run metadata 已按语义集中；
4. 子目录一致表达单 channel、固定多资源、决策切片、多 iteration、多 job 和 example；
5. 两份 README 与当前数据和入口一致；
6. 公共 index、语义 manifest、实验 manifest 的职责明确分离；
7. 迁移报告证明 290 个 benchmark 没有丢失、复制或内容变化；
8. 定向测试与完整回归通过；
9. 未经单独审查，没有删除正式大图、语义配对样例或 reference result；
10. 没有修改 `src/core`。如确需修改，必须停止并先取得用户明确同意。
