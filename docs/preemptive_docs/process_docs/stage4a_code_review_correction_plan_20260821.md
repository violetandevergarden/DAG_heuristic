# Stage 4a 代码修正建议

日期：2026-08-21

对应审查：`docs/process_docs/stage4a_code_review_20260821.md`

本建议按证据依赖排序。先修正状态合同、认证含义、发布和预算，再补转换对拍与受控实验。不要先扩大 corpus，也不要为了保留旧结果修改目标语义。

## 1. P0：冻结 manifest v3 的三类状态

为每个生成 attempt 保存独立字段：

- `conversion_status`：`not_run`、`valid`、`explained_delta`、`mismatch`、`invalid`；
- `contention_classification`：纲领规定的八类正式分类；
- `contention_evidence_level`：`not_run`、`static_only`、`sampled_prefix`、`bounded_search`、`completed_replay`、`certified_choice_exists`、`certified_no_choice`；
- `publication_status`：`staged`、`published`、`excluded`、`superseded`；
- 独立 `baseline_status`、`exact_status` 只放结果引用，不复用上述状态。

保留旧 `status` 只用于读取 v2，发布 v3 时不再写入。实现机器可读 sidecar schema，校验枚举、必填字段、null 语义和旧版迁移。

验收：任意一行 manifest 能同时表达“转换有效、已发布、只做前缀、竞争未知”；下游无需推断 `status` 含义。

## 2. P0：修正“认证有选择”的定义

把 `_certified_reachable_choice()` 拆成两级：

1. `multiple_legal_actions_exists`：只证明某可达状态有多个合法动作；
2. `certified_non_equivalent_choice_exists`：执行候选动作，比较所有影响未来的 residual state；若使用对称归一化，必须先有等价性证明和未压缩小图对拍。

多资源要比较不同极大兼容集合执行后的状态，不能只比较集合文本。若预算耗尽，返回 `bounded_search/state_limit`，不得返回 certified。为“多个动作但未来等价”的对称小图增加反例测试。

验收：只有第二级证据可以映射到 `informative-certified`；当前两个示例先降级为有界合法动作存在性，重新认证后再升级。

## 3. P0：实现活动快照的原子发布与回滚

发布前在临时快照目录完成：

- candidate JSON 全量枚举与 manifest 一一对应；
- benchmark ID/path 非空且唯一；
- benchmark hash、schema、sidecar schema、状态枚举和报告 hash 校验；
- source catalog、topology catalog、run metadata、manifest、index 同属一个 `publication_run_id`；
- 在临时根构建 index，并验证只引用该快照文件。

全部通过后再用一个活动指针或目录级切换发布。若平台无法一次替换多个文件，使用 versioned snapshot 加单一 pointer；不要先移动 active 后再逐个写 sidecar。失败自动保留旧指针和 staging。

至少增加：JSON 截断、manifest 少行/多行、重复 ID、hash 错、sidecar 缺失、index 构建失败、替换中断的故障注入测试。

验收：每一种注入失败后，旧 corpus、manifest、index 和 sidecar 的 hash 全部不变。

## 4. P0：让时间预算成为严格且可解释的预算

当前进程内轮询不能中断耗时的单次状态转移。建议每个 `case × rule` 使用独立子进程，父进程按墙钟截止终止并保存最近一次已落盘 checkpoint。Windows 下使用显式进程管理，不依赖循环内软检查。

同时拆分计时：加载、特征预计算、调度循环、trace 重建、独立验证。预算必须说明包含哪些阶段。若 trace 验证使用独立预算，也要单列，不得把验证超时混成调度超时。

旧结果保留原 run ID，并标记 `cooperative_timeout_v1`；新结果使用 `process_wall_timeout_v2`，不能静默覆盖。修正文档中 90s/120s 的解释。

验收：构造一个故意在单次 step 中阻塞的测试，实际墙钟不超过预算加固定清理容差；completed 结果的墙钟不得显著超过预算。

## 5. P1：完成转换层逐项对拍

为代表 workload 和 pipeline mode 保存：

- 稳定原始任务 ID 到导出 ID 的映射；
- 原始边、serializer 新增边、重复边和无法解释边；
- 任务类型、duration、rank/stage/micro-batch/iteration 标签；
- communication endpoint、route 和固定资源集合；
- 可比事件的开始/完成顺序；
- 对拍状态 `matched`、`explained_delta`、`mismatch`、`not_supported`、`not_run`。

驱动 SimAI dynamic executor 完成至少一个原生 N-iteration 对拍。若执行器无法稳定导出所需信息，记录 `not_supported` 和具体缺口，多 iteration 继续标为投影，不用复制结果替代认证。

验收：代表性 1F1B 及至少一种其他 pipeline mode 的差异逐项可解释；原生 multi-iteration 有明确 matched/mismatch/not_supported 报告。

## 6. P1：建立完整 workload/topology/环境清单

新增 topology catalog，保存相对路径、内容 hash、节点/链路层级、带宽单位、路由规则、资源粒度、双向链路容量含义、来源类别和来源证据。来源未核实的名称标 `unverified`，不直接称 production。

run metadata 补充主仓库和 SimAI commit/dirty/bundle hash、Python 和关键依赖、操作系统、命令、seed、转换器版本、全部参数及其 hash。禁止发布 JSON 中出现本机绝对路径。

验收：只依靠 snapshot sidecar 即可确定输入内容、代码内容和生成参数；README 不再超出来源证据命名 topology。

## 7. P1：统一竞争审计工具和报告合同

把 `contention_census.py` 中有用的预算、checkpoint 和选择状态摘要迁移到 4a 审计模块，避免 fast probe、旧 `competition_report()` 和实验 census 三套字段继续分叉。

逐样例至少保存：决策数、终止原因、多个 eligible、直接资源冲突、不同极大集合、多个合法动作、非等价动作、三基线分歧、候选/冲突分布、热点资源、首次/最后竞争时间、抢占机会、compute/barrier 释放、枚举是否精确。详细状态放独立压缩报告，manifest 只存摘要与 hash。

前缀、单策略完整回放、有界搜索和全状态证书分别映射证据等级。完整回放不能自动证明其他路径无竞争。

验收：能自动生成八类正式分类表，并保留无竞争、未观察、未知、无效、失败和排除样例。

## 8. P1：补齐基线结果合同

每个 `case × rule × config` 保存：

- benchmark/manifest/模拟器/规则配置 hash 和 run ID；
- completed/timeout/failed、明确终止原因和严格预算；
- makespan 或 partial simulation time，二者字段分开；
- wall-clock 分阶段时间和峰值内存；
- 决策数、抢占数、通信区间数、forced idle；
- 总体及逐资源利用率；
- 可独立重放的动作 trace 或压缩 trace，及其 hash；
- multi-job completion/JCT；
- fallback、枚举截断和验证状态。

三种多资源基线调用同一个带版本的“按分数排序后贪心补成极大集合”函数，只替换排序分数，避免实现差异混入结论。

验收：结果可由独立进程只读取 benchmark 和动作 trace 完成回放；timeout 行绝不进入 makespan 比较。

## 9. P2：按单变量补齐四类受控曲线

### 9.1 DP

固定 source、TP、PP、EP、batch、iteration 和 topology，报告 dp=1/2/4 的任务/边/资源、静态相交、证据等级、竞争指标、三基线、抢占、forced idle、利用率和分阶段成本。高 DP 超时就标竞争未知，不把任务翻倍写成有效竞争增强。

### 9.2 Topology

同一 workload 做统一 channel、至少两个真实来源 topology 和受控冲突 topology 配对。分别说明 duration 改变和资源相交改变；来源类别分组汇总。

### 9.3 Iteration

只在原生 N-iteration 对拍完成后进入正式曲线。在此之前保留 1/2/4 iteration 为转换层投影和性能测试，不作真实迭代结构结论。

### 9.4 Multi-job

把真实组合 case 纳入 versioned benchmark snapshot 和 manifest，覆盖 1/2/3/4 job、同构/异构、同时/错峰到达。4a 只报告组合正确性、竞争和成本，目标固定为 makespan，并单列 JCT；策略研究留给 4f。

验收：四类曲线均有成对输入 hash、固定变量说明、相同预算和“有效竞争/竞争未知/无效扩展”判断。

## 10. P2：完善 Exact 切片与规模实验

Exact 明细补充下界、上界、最优首动作、状态数、峰值内存、终止原因和预算。只有 `optimal` 写证书；切片文件与报告进入 versioned result manifest，但不必混入完整图 corpus。

规模实验除 top task count 外，补高 edge density、高通信比例和高冲突样例。分别测量解析、builder、转换、写 JSON、schema/loader、静态扫描、有界 probe、完整 census、三基线和 trace 验证。每一步使用独立预算，未测量项说明原因。

验收：约 5--10 个大图有完整的分步骤成本表；不能运行的步骤明确是 not_run/timeout，而不是空值。

## 11. P2：形成供 4b--4g 使用的冻结分层清单

最终清单至少分为：

- 正式竞争样例：`informative-certified` 与 `informative-observed` 分开；
- 负面对照：`no-choice-certified`、`no-contention-observed`；
- 待补证据：结构冲突、bounded、timeout；
- 规模压力样例；
- invalid/excluded/superseded；
- real-derived Exact 切片；
- multi-job 专用样例。

每组说明允许支持和不能支持的结论。算法 runner 可以用清单选择输入，但传给算法时只加载公开问题字段，不能读取竞争答案或 provenance 暗示。

验收：4b--4g 的每次实验都能引用一个不可变 manifest hash，且不会把前缀、证书、单 job 和 multi-job 目标混用。

## 12. 推荐实施顺序

1. manifest v3、sidecar schema 和旧版迁移；
2. 动作非等价认证；
3. 原子快照发布和故障注入；
4. 进程级严格预算与结果 schema v2；
5. 转换逐项对拍和原生 multi-iteration；
6. 统一竞争审计与正式分类；
7. DP/topology/iteration/multi-job 曲线；
8. Exact/规模报告补全；
9. 冻结 4b--4g 分层清单并更新 README。

前四项会改变状态和结果合同，应先完成，再重跑正式实验。旧结果只增加 superseded/legacy 说明，不删除、不覆盖。

## 13. 重新验收标准

只有下列条件同时成立，才建议把 Stage 4a 标为完成：

1. 12 项退出条件逐项有机器可读证据；
2. manifest 三类状态和正式竞争分类齐全；
3. 发布故障不会改变旧活动快照；
4. 严格预算下重跑三基线，超时和完成状态可信；
5. 代表性原生转换及 multi-iteration 差异可解释；
6. DP、topology、iteration、multi-job 的受控证据齐全；
7. Exact 与规模报告字段完整；
8. 形成冻结的 4b--4g 输入清单与结论边界；
9. README、AGENTS 摘要、manifest 和结果数字一致；
10. 完整测试及新增故障/超时/认证测试通过。

