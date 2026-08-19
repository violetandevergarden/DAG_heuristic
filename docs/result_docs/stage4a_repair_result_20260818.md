# Stage 4a 修复结果

日期：2026-08-18

依据：`stage4_LLM_search.md`、`stage4a_benchmark.md`、`stage4a_new_review_20260818.md` 和 `stage4a_new_modification_plan_20260818.md`。

## 1. 结论

本轮完成了 Stage 4a 审查中可以在当前仓库内独立验证的 P0/P1 修复：probe 证据状态不再全部折叠为 `probed`，fast probe 增加了可配置预算和配置哈希，多资源 fast 路径避免无界枚举极大兼容集合，公共多资源动作验证改为直接检查 work-conserving 极大性，公开 SimAI benchmark 不再写入本机 topology 绝对路径，candidate 发布在替换 active 前执行格式和内容哈希校验，生成运行的未跟踪源码内容也进入 provenance hash。

本轮没有把现有 72 个样例重新宣称为“已认证有竞争”，也没有伪造 DP 曲线、真实 multi-job、native multi-iteration 对拍或大图成本报告。活动 manifest 仍有 72 行旧状态 `probed`，这是未重新运行昂贵 probe 的历史资产；重新 reconcile 或使用新 probe 配置时会按 evidence scope 映射为 `sampled_prefix`，而不是把它解释为完整回放。

因此当前阶段判断仍为：**转换和审计基础设施已修复并通过回归；Stage 4a 五项研究退出条件尚未全部满足。**

## 2. 已完成修改

### 2.1 Probe 状态与可复现配置

`benchmark_generate/llm/corpus.py` 新增并接受以下状态：`sampled_prefix`、`certified_small`、`completed`、`state_limit`，同时保留旧 `probed` 以便读取历史 manifest。旧行只有在其 probe 明确标记 `sampled_prefix` 时才会迁移为该状态；不会把旧的模糊状态升级为完成。

每次 probe 将 `fast`、时间上限、决策上限、状态上限和极大集枚举上限规范化后计算 `probe_config_hash`，只有 benchmark hash 和 probe 配置都相同才复用旧报告。报告新增 `probe_schema_version`、`termination_reason`、`complete_trace`、`trace_hash`、`enumeration_limit`、`enumeration_exact` 和 `enumeration_truncated` 等字段。

fast probe 仍然只是前缀抽样，不产生全图无竞争结论。新增的静态资源汇总按资源使用计数线性计算，并明确标记资源成员对数是上界；轨迹竞争和可达选择认证分别保留，避免把三个不同证据压成一个布尔值。

### 2.2 大图枚举成本

多资源 fast probe 在 eligible 数量超过 `enumeration_limit` 时使用确定性的贪心构造一个合法极大兼容集合，并记录 `enumeration_truncated=true`。公共 `PreemptiveMultiResourceModel.step()` 不再通过枚举全部合法集合验证动作，而是直接检查：通信均 eligible、资源集合互斥、集合非空且对每个未选 eligible 通信都不可加入。这与原极大兼容集合合同一致，但避免了验证阶段再次触发指数枚举。

小图认证仍使用有界搜索；大图仍标记为 `not_run_size_limit`，不会把 fast 轨迹当作 Exact 或完整竞争证明。

### 2.3 发布与 provenance

`publish(staging=...)` 在任何 active 替换前逐行检查 candidate benchmark 是否存在、可由 loader 读取、通过 validator、benchmark id/path 不重复且内容哈希与 candidate manifest 一致。损坏 candidate 会直接拒绝，旧 active 不会被移动。source catalog 与 run metadata 在成功发布时随同一 staging run 复制到活动目录。

未跟踪文件不再只按文件名参与 git dirty hash，而是按相对路径和文件内容 hash 参与 source bundle hash。probe 报告路径移出 benchmark 输入树，避免被公共 benchmark index 当成问题文件。

SimAI 导出 metadata 的 `topology` 现在只保存 topology 文件名；内容 hash、topology tier 和 route/resource hash 仍用于追溯，绝对路径不进入公开 JSON。duration 记录增加 `duration_model_version`，corpus 行同时记录是否逐链路以及是否包含 NIC 资源。

### 2.4 文档与测试

`benchmark/llm_structure/README.md` 已更新为当前 72 个候选文件的事实，明确候选数量不等于竞争认证数量，替换不存在的 `benchmark_generate.stage4` 入口，并说明 fast prefix 与 bounded census 的证据边界。

新增 `tests/test_llm_corpus.py`，覆盖：

- fast probe 超过枚举上限时不调用完整 `legal_actions()`；
- 旧 `probed` 状态按 evidence scope 迁移；
- candidate 哈希错误在 active 替换前被拒绝；
- active 标记文件在失败发布后保持不变。

## 3. 验证结果

### 3.1 定向验证

- LLM corpus、公共 trace、固定多资源测试：`24 passed`。
- SimAI export 和语义端到端测试：`7 passed`。
- `python -m py_compile benchmark_generate/llm/corpus.py src/core/execution/multi_resource.py`：通过。
- `git diff --check`：通过。

### 3.2 完整回归

命令：

```powershell
python -m pytest -q --basetemp .test-tmp
```

结果：`172 passed`，仅有 pytest cache 写入权限警告；测试生成的 `.test-tmp` 已清理。默认临时目录在当前受限环境不可访问，未将该环境问题误报为代码失败。

### 3.3 当前活动 corpus 事实

直接读取 `benchmark/llm_structure/manifest.jsonl`：

| 项目 | 数量 |
| --- | ---: |
| manifest 行数 | 72 |
| R-C | 39 |
| R-P | 16 |
| R-S | 17 |
| 当前旧 status=`probed` | 72 |

这 72 行保留历史 probe 内容，不能据此宣称完整 probe、全图竞争认证或 canonical v1 已冻结。重新运行新接口后，状态会带有新配置哈希和明确终止原因。

## 4. 尚未完成的退出条件

以下工作需要真实 SimAI 输入、昂贵回放或新的实验资产，本轮没有以合成结果替代：

1. 每个正式样例的完整竞争准入、统一 FIFO/Longest Tail/固定顺序基线及可回放 trace。
2. 同一真实 AICB source 的 DP=1/2/4 竞争强度和成本曲线。现有 DP rewrite 仍只能作为投影实验。
3. 至少两个真实 AICB source 的 multi-job 混合，包含独立命名空间、arrival、无跨 job DAG 边和明确主目标。
4. 当前多 iteration 投影与 SimAI 原生展开的逐项对拍。
5. 约 10 个大图的生成、转换、probe、基线运行时间和峰值内存报告。
6. real-derived exact slice 与 reference sidecar。

这些缺口仍按 `generated`、`sampled_prefix`、`timeout`、`state_limit`、`failed` 或 `excluded` 记录，不能写成算法最优或阶段完成。

## 5. 后续执行顺序

1. 用新 probe 配置先对 R-P/R-S/R-C 的小规模代表集运行可恢复 bounded probe，并生成三种基线报告。
2. 从同一来源建立 DP 配对曲线，明确 `projection` 标签和无效扩展。
3. 生成真实 multi-job corpus，并独立报告 makespan 与 per-job JCT/目标。
4. 完成 native multi-iteration 对拍和少量真实 exact slice。
5. 最后才把通过准入的样例组成 canonical v1 holdout，供 4b--4h 使用。

在上述证据完成前，Stage 4a 仍是“可审计候选真实语料基础设施”，不是已经冻结的后续算法输入集。
