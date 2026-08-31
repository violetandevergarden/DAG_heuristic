# Stage 2 一般 DAG 代码修正结果

日期：2026-08-16

## 1. 结果摘要

本轮完成了 Stage 2 的第一套可审计代码闭环：明确 raw general-DAG family contract，补齐 fork/join/barrier/同刻事件测试，建立未压缩与 normalized 两种 Exact，修正 Exact status/reference 契约，拆分基础 priority 定义，加入显式 depth/budget 的 Rollout、带 horizon/budget 的 Beam，重建 Stage 2 benchmark 分层，并增加独立薄实验入口。

公共 `PreemptiveDAGModel` 和 trace validator 没有被重写。所有 Stage 2 policy、Rollout、Beam 和 Exact 仍只通过公共 `legal_actions()`/`step()` 推进时间；solver 没有实现第二套 compute closure、暂停/恢复或依赖释放语义。

本轮不宣布 Stage 2 全部完成。尚未完成的主要退出项是更系统的结构特征消融、fixed-width Beam 反例、参数化 Exact scaling 曲线，以及真实测量 workload 投影。

## 2. Family contract 与公开入口

采用修正计划方案 B：

- 允许 raw general DAG、same-kind edge、fork、join、shared downstream、多层 barrier；
- 允许多个弱连通 component，但它们是同一 makespan 实例，不是 multi-job；
- 禁止零 work communication；
- 不静默链化、合并或插 dummy；
- benchmark 公共 validator 继续保证固定单 `channel:0` 与资源约束。

新增 `validate_complex_chain()`，并让 public interface 的算法入口统一经过该边界。interface 现在公开 FIFO、SPT、LPT、Longest-delay、Longest-tail、LRPT、Join-aware、Rollout、Beam、normalized Exact 和 audit Exact，同时 Exact/Rollout/Beam 可从稳定入口传入预算与研究参数。

## 3. Exact 修正

### 3.1 两种 key

- audit Exact：保存 absolute time、完整 RuntimeTask、started/completed timestamp 和 last communication；
- normalized Exact：保存固定 task 顺序下的 `(status, remaining)`。

两者共用同一搜索和公共 transition。normalized key 的逐字段未来等价、time-dominance 和失效条件已写入：

- `docs/process_docs/stage2_complex_chain_contract_exact_and_bounds_20260816.md`

### 3.2 status 与预算

- 完整求解：`status='optimal'`；
- state/time budget 耗尽：返回 Longest-tail incumbent，`status='feasible'`，并记录结构化 `termination_reason`；
- 不再仅凭函数名或 registry 的 `exact=True` 推断本次求解完成。

新增统计字段：generated transitions、deduplicated states、incumbent/lower-bound prunes、peak states、runtime、root lower bound，以及 Rollout/Beam 的 expanded nodes、evaluated candidates、fallback count。

### 3.3 下界与剪枝

实现 residual `max(P_rem,L_rem)`：

- `P_rem` 为单 channel 剩余 communication work 总和；
- `L_rem` 为忽略 channel 冲突的剩余最长加权因果路径。

只在 `elapsed + LB(child)` 严格大于 incumbent 时剪枝；相等分支保留，以维持既有字典序最小 optimal trace，避免破坏依赖 Exact teacher trace 的下游测试。

### 3.4 reference 契约

Stage 2 reference generator 现在强制 `result.status == 'optimal'`，并写入：

- `oracle_status`；
- `oracle_runtime_ms`；
- `oracle_explored_states`；
- `oracle_budget`。

CLI 增加 `--prefix`，可只更新 Stage 2 reference，避免顺带改写 nonpreemptive 或 multi-channel sidecar。

## 4. Priority、Rollout 与 Beam

### 4.1 Priority

- FIFO 改为首次 eligible event time，暂停后保留 arrival；
- SPT/LPT 使用当前 remaining；
- Longest-delay 改为立即 release gain，不再是 Longest-tail 别名；
- Longest-tail 为 exclusive residual downstream path；
- LRPT 为 inclusive residual path；
- 新增独立 direct-last-blocker Join-aware priority。

三个 residual priority 已有首选动作互异测试；FIFO 有暂停后 arrival 保持回归。

### 4.2 Rollout

新增：

- `depth`，只计算 communication decision；
- top-k 2/4/all；
- Longest-tail、LRPT、Join、Hybrid candidate mode；
- completion baseline 强制占一个 shortlist slot；
- deterministic expansion budget、wall-clock budget 和显式 fallback。

有限 shortlist 的 score 口径已与 completion Longest-tail 对齐，不再用 inclusive LRPT 冒充 Longest-tail。

### 4.3 Beam

Beam 改用与 Exact 相同的 normalized key，并明确相同 key 下较早时刻支配较晚时刻。新增 decision horizon、node/time budget、incumbent safeguard 和去重/预算统计。Monte Carlo 代码仅作为 historical sampler 保留，已经从 Stage 2 active registry 删除。

## 5. Benchmark 与实验入口

Stage 2 preemptive complex-chain 当前共有 45 图：

| 分组 | 数量 | 说明 |
|---|---:|---|
| Stage 1 compatibility | 7 | 无 fork/join，正式一般 DAG 汇总排除 |
| legacy structural regression | 20 | 旧 join/random/历史结构回归 |
| structural adversarial | 5 | 新的 release/join/shared/nested/depth 解释性反例 |
| general random | 10 | 参数化 layered raw general DAG |
| structured | 3 | 审计过的 LLM synthetic motif |

新增 `random_layered_general_dag()`，可独立控制 layers、width、edge probability、skip-edge probability、compute/communication duration。仓库只固定 10 个 seed，规模研究应运行时生成。

三个 structured 图为 `zb_bw_fork`、`w_dp_optimizer_join`、`tp_collective_plus_pp`；metadata 明确 resumable transfer 粒度、单 channel 投影和“synthetic motif、非测量 trace”的边界。

新增薄 runner：

- `experiments/preemptive/stage2_complex_chain.py`

runner 只经 stable interface 调用，记录 path/hash、结构统计、算法参数、Exact status/budget、ratio/gap、dispatch/preemption、forced idle、utilization、search 统计和内存近似，并按 general random、structural adversarial、structured、legacy structural、Stage 1 compatibility 分层。

正式 raw 结果：

- `docs/result_docs/stage2_complex_chain_experiment_20260816.json`

## 6. 测试修正

原 Stage 2 测试中的两个 multi-channel 用例已迁回 `tests/muti_channel/preemptive/`，没有删除。

Stage 2 新增或强化：

- raw/same-kind/multiple-component family contract；
- 最小 fork、join、diamond、zero-compute closure；
- 同刻多个 predecessor 完成；
- compute event 处 communication pause/remaining/eligible；
- priority 首选动作差异；
- FIFO arrival history；
- direct join 特征可观察性；
- normalized/audit/tick Oracle 固定 100 图三方对拍；
- Exact budget 不能标 optimal；
- Rollout/Beam budget fallback；
- depth-1 与 depth-2 固定反例；
- Stage 2 registry 不含 active Monte Carlo；
- fork/join trace 对多种 policy/search 独立回放；
- Stage 2 sidecar 必须记录 optimal status 与预算。

## 7. 变更文件范围

主要代码：

- `src/core/execution/preemptive.py`
- `src/single_channel/complex_chain/preemptive/{solver.py,interface.py,__init__.py}`
- `src/registry.py`
- `benchmark_generate/{cases.py,export.py,reference.py,__main__.py}`
- `experiments/preemptive/stage2_complex_chain.py`

测试：

- `tests/single_channel/complex_chain/preemptive/test_algorithms.py`
- `tests/muti_channel/preemptive/test_preemptive_muti_channel.py`
- `tests/test_benchmark_format.py`
- `tests/test_generators.py`
- `tests/test_semantics_layout.py`

数据：

- Stage 2 preemptive complex-chain benchmark、reference sidecar 和 `benchmark/index.jsonl`；
- nonpreemptive 算法与 benchmark 没有迁移为新 Stage 2 研究对象。

## 8. 验证结果

最终验证命令：

```powershell
python -m pytest -q
python -m ruff check <本轮修改的 Python 文件>
git diff --check
```

最终计数和结果见本报告提交时的验证记录；正式实验为 45/45 Exact completed，44/45 有固定 5 秒 reference sidecar。缺失 sidecar 的图保持缺失，没有把超过 reference 预算的正式实验值写成 5 秒 Oracle 结果。

## 9. 未完成项

1. fork breadth、join distance/slack、barrier urgency、shared-downstream 去重、critical-path multiplicity、downstream communication demand 尚未逐项完成反例与消融。
2. 尚未找到 fixed-width Beam-8 反例。
3. Exact scaling 尚缺 width/depth/fork density/barrier layers 的 solved-fraction 曲线。
4. structured 图仍是 synthetic motif，不是真实 SimAI/AICB 测量投影。
5. 一般 DAG 没有新的统一近似比证明；Stage 1 的 2-bound 没有迁移。
