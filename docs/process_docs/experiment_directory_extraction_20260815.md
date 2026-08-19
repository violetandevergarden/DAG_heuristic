# 实验目录独立化决策（2026-08-15）

## 决策

离线实验 runner 和实验专用分析器统一放入仓库顶层 `experiments/`，不再放在
`benchmark_generate/`。`benchmark_generate` 只负责构造、转换、写出 benchmark
以及生成 reference/index；`src` 只负责模型、模拟器、Oracle 和调度算法。

目标依赖方向为：

```text
experiments -> benchmark_generate -> src/public benchmark model
experiments -> src algorithms
src -X-> experiments
src -X-> benchmark_generate
```

SimAI 实验只通过 `benchmark_generate.simai.export` 的公开转换层访问可选 SimAI
能力，不在 `src` 中引入 SimAI 依赖。

## 文件迁移

```text
benchmark_generate/studies/preemptive/stage0_4.py
  -> experiments/preemptive/stage0_4.py
benchmark_generate/studies/preemptive/stage5.py
  -> experiments/preemptive/stage5.py
benchmark_generate/studies/preemptive/stage6.py
  -> experiments/preemptive/stage6.py
benchmark_generate/simai/multi_job_study.py
  -> experiments/simai/multi_job_study.py
benchmark_generate/simai/repetition_study.py
  -> experiments/simai/repetition_study.py
benchmark_generate/simai/repetition.py
  -> experiments/simai/repetition.py
```

## Generator 收敛

删除 `benchmark_generate/preemptive.py`。两种语义统一通过：

```python
export_semantic_suite(..., semantics="preemptive")
export_semantic_suite(..., semantics="nonpreemptive")
```

CLI 不再提供单独的 `preemptive` command；统一使用：

```powershell
python -m benchmark_generate all --semantics preemptive
python -m benchmark_generate all --semantics nonpreemptive
```

仓库不保留隐式代表 nonpreemptive 的 `export_suite()` 兼容入口。
