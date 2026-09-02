# 不可抢占 Stage 4 小范围重构结果（2026-09-02）

## 结论

本次完成了 `rebuild_plan.md` 中最高优先级的公共运行层收口，并完成第二阶段的基础目录和 corpus 职责拆分。重构没有移动可抢占代码，没有合并 packing、selective rollout 与 barrier，也没有改变不可抢占模拟器的完整通信、主动 WAIT 或 active reservation 语义。

多资源 `solver.py` 的整体拆分属于计划中的条件性工作。本次先提取了公开 replay 入口并消除了 Stage 4 对私有 `_replay` 的依赖；状态、Exact、lower bound 和历史 rollout 暂不迁移，避免在一次提交中同时改变高风险状态表示。

## 已完成工作

### 1. 建立唯一的不可抢占 Stage 4 公共运行层

新增 `src/llm_structured/nonpreemptive/runtime/`：

- `contracts.py`：统一 `Mode`、`PolicyName`、`ActionSignature` 和 replay 摘要；
- `adapters.py`：统一单 channel 与固定多资源适配器；
- `features.py`：统一 residual tail；
- `policies.py`：统一 FIFO、固定顺序、LT、SPT、LPT 与既有 optional-idle WAIT 规则；
- `completion.py`：使用冻结公共策略完成 residual state；
- `replay.py`：统一基线调度、回放校验、trace hash 和实验记录入口。

Stage 4a 实验入口现在只转发到公共 runtime。Stage 4d 的旧 `adapters.py` 和 `baseline.py` 只保留兼容导入；4d policy 直接使用公共 runtime。Stage 4e 不再导入 selective rollout 的合同、adapter、LT 或 completion。

新增测试固定“只有一个 LT 实现”：兼容路径导出的函数对象必须与公共 runtime 中的函数相同。

### 2. 分离纯 LT 与 barrier 特征计算

`barrier.schedule(method="lt")` 现在直接调用公共 `schedule_baseline`，不构造 barrier 图，不遍历 challenger，也不执行 barrier 特征状态转移。只有明确启用 barrier 修正方法时，才构造结构并计算修正候选。

因此 B0 的时间现在只表示公共 residual LT 回放，不再混入 Stage 4e 特征成本。

### 3. 消除 Stage 4 对多资源私有 replay 的依赖

新增 `src/muti_channel/nonpreemptive/replay.py` 的公开 `replay_actions` 入口。公共 runtime、Stage 4c packing 和 4c 实验入口均改用该入口，不再直接导入 `_replay`。

这一步只建立安全迁移缝，没有重写状态或 Exact。完整拆分 `solver.py` 仍需在更多 Exact 与 trace 锁定测试后单独进行。

### 4. 拆分 corpus 的选择与发布职责

新增：

- `benchmark_generate/llm/nonpreemptive/selection.py`：source 分层、候选选择、spec 与 benchmark 命名；
- `benchmark_generate/llm/nonpreemptive/publication.py`：candidate 校验、内容 hash、事务发布、备份、回滚和 index 重建。

`corpus.py` 的生成工作流使用独立 selection，并将公开 `publish` 入口转发到 publication 模块。既有 CLI 和历史调用路径保持不变。

### 5. 新增 foundation 实验入口

新增 `experiments/llm_structure/nonpreemptive/foundation/`：

- `runtime_diagnosis.py`；
- `conversion_fidelity.py`；
- `contention_census.py`；
- `hard_slice_validation.py`。

新入口统一使用 `status`、`termination_reason`、`wall_clock_ms`、`timeout_s` 和 `completed` 等字段；既有 4a--4e runner 没有批量移动。

### 6. 修正低风险公共元数据

- `src/llm_structured/__init__.py` 不再声称只包含 communication-resume 算法；
- `pyproject.toml` 项目描述同时覆盖两种通信语义；
- registry 返回的不可抢占算法明确标记 `communication_nonpreemptive`，不再沿用 `none`。

## 行为对拍

对 `benchmark/llm_structure/nonpreemptive/` 中排序后的 30 个真实小图执行公共 replay，并与 `stage4a_baselines_20260831/results.jsonl` 的冻结结果比较。

- 策略：FIFO、固定顺序、residual LT；
- 模式：optional-idle、work-conserving；
- 有冻结结果的比较：156 组；
- makespan 不一致：0；
- trace hash 不一致：0。

对拍已写为回归测试，不把仅有 makespan 相同视为足够。

## 测试结果

- 新增公共 runtime 对拍测试：`2 passed`；
- 4a/4c/4d/4e、registry 和 catalog 定向测试：`33 passed`；
- 完整测试：`241 passed, 2 failed`，耗时约 101 秒。

两项失败均来自 `tests/test_semantics_layout.py` 的固定数量断言：测试仍写死 243，而当前工作区 problem JSON 和 `benchmark/index.jsonl` 都是 281。两边数量一致，失败不是本次重构造成的语义或索引缺失。本次没有把真实数量改回 243，也没有在缺少 corpus 迁移依据时擅自更新历史数量断言。

## 明确保留的边界

- 未移动 `src/llm_structured/` 顶层可抢占旧模块；
- 未重排既有实验文件；
- 未清理 egg-info 或 `__pycache__` 来冒充架构修复；
- 未把三种研究方法包装成未经验证的综合算法；
- 未执行多资源 solver 的高风险整体拆分；本次只完成公开 replay 边界，后续拆分必须保持 Exact 结果和 trace 完全一致。

本报告只说明结构重构和行为保持证据，不构成 Stage 4a--4f 已完成或真实大图算法收益成立的研究结论。

## 后续收尾（依据 `rebuild_plan2.md`）

后续审查指出的四项缺口已经完成：

1. `corpus.py` 中旧 `_validate_candidate`、旧 `publish` 及发布辅助代码已删除；兼容导入位于正常 import 区，CLI 只负责编排。
2. 新增 runtime、publication、selection、foundation 和 multi-resource replay 已统一格式化；对本次收尾涉及目录运行 Ruff，结果为 `All checks passed!`。
3. foundation 的三种路径已经具有不同职责：
   - `bare` 只运行策略循环和模拟器状态转移，不生成或验证 trace；
   - `validated` 生成 trace，并检查完整通信连续性及资源排他；
   - `instrumented` 在 validated 基础上启用 tracemalloc，并显式记录观测状态。
4. 多资源 replay 实现和 route-reservation 检查已迁入公开 `replay.py`；旧 `solver._replay` 与 `_assert_route_reservations` 只保留薄兼容转发。状态机、Exact、lower bound 和 rollout 未在本次继续拆分。

新增回归测试覆盖三种 foundation 路径的职责差异、公开 replay 与旧入口结果一致，以及 `corpus.py` 不再定义发布函数。

收尾后的验证结果：

- 收尾范围 Ruff：0 项问题；
- 定向测试：43 passed；
- 完整测试：246 passed，2 failed，耗时约 195 秒；
- 两项失败仍是 `tests/test_semantics_layout.py` 写死 243，而当前 problem JSON 与 index 均为 281；没有发现新的功能或语义回归。
