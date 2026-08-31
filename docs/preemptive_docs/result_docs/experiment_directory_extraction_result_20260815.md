# 实验目录独立化实施结果（2026-08-15）

## 完成情况

- 顶层新增 `experiments/preemptive/` 和 `experiments/simai/`；
- 六份实验文件已从 `benchmark_generate` 物理迁出；
- 删除旧 `benchmark_generate/studies/`；
- 删除 `benchmark_generate/preemptive.py`；
- 两种 semantics 统一由 `benchmark_generate.export.export_semantic_suite` 显式导出；
- 删除隐式 nonpreemptive 的 `export_suite()`；
- 删除旧 `preemptive` generator command，改用统一 `--semantics` 参数；
- integration test 已改用 `experiments.simai` 路径；
- 新增结构测试，禁止旧实验路径和专用 exporter 回归；
- 新增边界测试，禁止 `src` 导入 `experiments` 或 `benchmark_generate`。

## 验证

- 双语义临时生成：84 个文件，索引同时包含 preemptive/nonpreemptive；
- generator/结构定向测试：5 passed；
- core 边界、generator、结构测试：6 passed；
- 迁移后的 stage 5 实际运行成功，生成 5 个 repetition 和 5 个 symmetry 结果；
- 本次涉及文件 Ruff：全部通过；
- 可选 SimAI runner 需要安装 `.[integration]`，当前无 `jsonschema` 环境不执行其运行时实验。
- 9 个 experiment Python 模块完成无落盘语法编译；
- 最终完整测试：`79 passed in 18.03s`。
