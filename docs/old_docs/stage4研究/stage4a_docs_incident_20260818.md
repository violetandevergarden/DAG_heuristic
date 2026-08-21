# docs/ 目录内容丢失事故记录

日期：2026-08-18（发现于本日后续会话；恢复补充于同日）

## 1. 事故描述

`docs/` 目录下全部子目录（`plan_docs/`、`process_docs/`、`result_docs/`、`old_docs/`、`paper/`）的文件内容全部丢失，仅剩空目录骨架（子目录时间戳 2026-08-18 20:41:41，被 pytest 重建）。

## 2. 根因

在调试 pytest 临时目录权限问题时，执行了：

```powershell
python -m pytest -q --basetemp docs tests\test_generators.py
```

pytest 对显式 `--basetemp` 目录的处理是 `ensure_reset_dir`：如果目录已存在，会先 `rmtree` 整个目录再重建（`_pytest/pathlib.py::ensure_reset_dir`）。该命令随后因 `docs/.pytest-tmp-4a`（上一次失败运行留下的 0o700 权限目录）无法删除而报 PermissionError，但在此之前 `docs/` 下可删除的内容已被清空。

这是操作失误：**不应把 `docs/`（或任何非临时目录）用作 pytest `--basetemp`**。

## 3. 丢失内容范围

- `docs/plan_docs/`：outline.md、simulator.md、stage4_LLM_search.md、stage4a–stage4g 等全部计划文档。
- `docs/process_docs/`：stage1–stage4 全部审查/修改计划文档。
- `docs/result_docs/`：stage1–stage4 全部历史实验结果与报告（stage4e_census_full/checkpoints/smoke、barrier、packing、selective rollout、multi-job 等）。
- `docs/old_docs/`：旧文档。
- `docs/paper/`：论文材料。

## 4. 恢复情况

### 4.1 来源一：git 历史（7 个旧文档）

`dd76ae4^` 中曾被跟踪的 7 个文件已恢复至 `docs/old_docs_recovered/`（260804 组会、260810 组会、heuristic 反例/工作进度对齐/总结/规划/进度）。

### 4.2 来源二：VS Code 本地历史（13 个文件，本次新增）

`%APPDATA%\Code\User\History` 中保留了用户用 VS Code 编辑过的文件快照。恢复并合并回 `docs/` 的 13 个文件（原始快照保留在 `docs_recovered_from_vscode/`）：

| 文件 | 版本数 | 恢复的最新时间 | 大小 | 说明 |
| --- | --- | --- | ---: | --- |
| plan_docs/outline.md | 50 | 08-15 20:55 | 9779B | 完整 |
| plan_docs/simulator.md | 7 | 08-15 20:45 | 18209B | 完整 |
| plan_docs/stage1_parallel_chain.md | 20 | 08-16 00:16 | 20200B | 完整 |
| plan_docs/stage2_complex_chain.md | 6 | 08-16 09:42 | 846B | 完整（该文件本身较小） |
| plan_docs/stage3_muti_channel.md | 7 | 08-16 12:54 | 925B | 完整（该文件本身较小） |
| plan_docs/stage4_LLM_search.md | 22 | 08-16 18:41 | 2711B | **仅早期版本**；丢失前为 14443B，08-16 后扩展内容不可恢复 |
| plan_docs/stage4e_selective_rollout.md | 1 | 08-17 11:17 | 8356B | 完整 |
| plan_docs/stage4f_conflict_graph_packing.md | 1 | 08-17 11:17 | 9002B | 完整 |
| process_docs/stage4_collaboration_progress_20260818.md | 32 | 08-18 20:36 | 12547B | 丢失前几分钟的版本，完整 |
| process_docs/stage1_parallel_chain_review_modification_plan_20260816.md | 1 | 08-16 00:40 | 12577B | 完整 |
| process_docs/stage2_complex_chain_review_modification_plan_20260816.md | 1 | 08-16 10:03 | 20383B | 完整 |
| old_docs/llm_probe_log.jsonl | 2 | 08-17 23:42 | 1968B | 完整 |
| preemptive研究/preemptive规划.md | 1 | 08-12 22:13 | 13555B | 完整 |

### 4.3 来源三：本会话对话历史逐字重建（4 个文件）

依据本会话中完整读过的原文重建：

| 文件 | 说明 |
| --- | --- |
| plan_docs/stage4a_benchmark.md | 与原始大小 4318B 仅差 1 字节（行尾差异），内容一致 |
| process_docs/stage4a_new_review_20260818.md | 完整原文重建 |
| process_docs/stage4a_new_modification_plan_20260818.md | 完整原文重建 |
| result_docs/stage4a_repair_result_20260818.md | 完整原文重建 |

### 4.4 来源四：runner 重跑（实验数据）

| 内容 | 状态 |
| --- | --- |
| stage4e_census_full（72 case） | 重跑恢复，35 个有非等价选择，与原始一致 |
| stage4a 基线/DP/multi-job/scaling/exact-slice 结果 JSON | 重跑恢复，结论与首次一致（baselines small 为 36 完成/3 超时） |
| stage4a_remaining_steps_result_20260818.md | 重建（本轮产物） |

### 4.5 未受影响

`benchmark/`、`experiments/`、`.artifacts/`、`src/`、`benchmark_generate/`、`tests/`、AGENTS.md、.gitignore 均未受影响。

### 4.6 仍不可恢复（需用户侧确认备份）

- `stage4_LLM_search.md` 08-16 之后扩展的约 11.7KB 内容（总纲最新版）
- 未在 VS Code 历史中的 process/result 文档（如 stage1–3 各轮 review/plan 的大多数、stage4d/4e/4f/4h 的结果 JSON、stage4a 相关历史结果）
- `docs/paper/` 全部内容
- stage4b/stage4c/stage4d/stage4g 计划文档（VS Code 历史中未见）

## 5. 教训与防护

1. 任何 pytest 运行不得把非临时目录设为 `--basetemp`；临时目录应使用 `$env:TEMP` 下的专用路径。
2. `docs/` 是 gitignore 的本地研究资产，建议定期备份或纳入独立版本管理。
3. 恢复/重建的文档在文件头注明"recovered/rebuilt"，避免与原始内容混淆。
4. VS Code 本地历史是有效恢复来源（本次恢复 13 个文件）；但只有用 VS Code 编辑过的文件才有历史，且不保证最新内容。

## 6. 责任人

本事故由本会话上一轮的操作造成，已如实记录，不掩盖、不推诿。
