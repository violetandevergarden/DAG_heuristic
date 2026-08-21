# Stage 4a 修正与重新验收结果（2026-08-21）

## 结论

本轮完成了会直接污染后续证据的 P0 修正，但按
`stage4a_code_review_correction_plan_20260821.md` 的重新验收标准，**Stage 4a 仍不能标记为完成**。
12 项退出条件中 1 项满足、8 项部分满足、3 项未满足。机器可读判定见
`acceptance.json`。

这不是措辞上的保留：原生 SimAI 多 iteration 对拍、严格预算下的全量三基线、四类受控
曲线、完整 Exact/规模字段和可交给 4b--4g 的冻结证据分层仍然缺失。把当前状态写成
“完成”会违反总纲关于前缀证据、超时和原生对拍的约束。

## 本轮已经完成

1. manifest 升级到 `llm-corpus-v3`，删除新写入行中含义混杂的 `status`，分开保存
   `conversion_status`、`contention_classification`、`contention_evidence_level`、
   `publication_status`、`baseline_status` 和 `exact_status`。
2. 72 个活动 benchmark 均迁移为 `valid + published + sampled_prefix`。前缀观察到直接竞争
   33 个，前缀未观察到 39 个；后 39 个没有被写成全图无竞争证书。
3. 小图认证分别报告“多个合法动作”和“动作后 residual state 不同”。认证会实际执行候选
   动作并比较未压缩公共模拟器状态；达到状态上限不会返回证书。兼容通信只有一个极大集合、
   冲突通信产生不同 residual state 的两个回归样例已加入测试。
4. 发布前增加候选 JSON 与 manifest 一一对应、非空唯一 ID/path、hash 和 benchmark 校验；
   sidecar 或 index 构建失败会恢复旧活动目录、manifest、index 与 sidecar。
5. 基线结果合同升级为 `stage4a-baselines-v2`。每个 `case × rule` 在独立子进程执行，父进程
   使用 `process_wall_timeout_v2` 强制墙钟截止，不再把循环内软检查解释为严格预算。
6. 新增 topology catalog，来源证据不足的 topology 一律标为 `unverified`；README 不再直接
   称其为生产拓扑，并修正旧基线 28/39 为实际归档的 36/39。

## 验证结果

- 完整测试：`175 passed in 81.57s`，包括发布切换后 index 失败的故障注入回滚测试。
- 严格预算 smoke：两个最小样例、三种基线、每项 10 秒，6 次回放全部完成且独立 trace
  校验通过。结果在 `baselines_smoke/`。
- 当前 manifest hash：
  `8bbc2879d924a32fed800b75941edcd434918e3caa4dd170ba0101839b761daf`。

严格预算 smoke 只验证新截止机制和结果合同可运行，不能替代 72-case 正式重跑，也不能
升级当前竞争证据等级。

## 当前证据边界

当前活动清单只能支持：真实 AICB 到自包含 DAG 的转换链可运行；72 个文件通过格式和公共
模拟器回归；有限前缀中 33 个样例观察到直接竞争；进程级严格预算入口可运行。

当前不能支持：72 个样例全图均有或均无竞争；39 个 `no-contention-observed` 样例不存在未来
竞争；DP 稳定增强有效竞争；多 iteration 与 SimAI 原生执行一致；历史 90/120 秒数据属于
严格截止；当前清单可直接作为 4b--4g 的正式收益样本。

## 剩余阻塞项

1. 驱动 SimAI dynamic executor，给代表性 1F1B、另一 pipeline mode 和原生 N-iteration
   生成 `matched/mismatch/not_supported` 逐项报告。
2. 在 `process_wall_timeout_v2` 下全量重跑三基线，补分阶段时间、峰值内存、可重放动作和
   逐资源利用率。
3. 补齐 DP、topology、iteration、1/2/3/4-job 单变量曲线，并把超时与竞争未知分开。
4. 补齐 Exact 上下界、最优首动作、峰值内存，以及约 5--10 个大图的分步骤规模表。
5. 基于上述证据再冻结 4b--4g 输入清单；在此之前不发布“Stage 4a 完成”结论。
