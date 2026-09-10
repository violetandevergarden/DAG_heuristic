# 调度算法代码

`src/` 保存可脱离 SimAI 独立运行的 benchmark loader、公共执行模型、Exact Oracle 和 heuristic。preemptive 是当前 active 主线，nonpreemptive 是 maintenance baseline；两者在目录和公开入口中均显式出现，不共享状态转移实现。

## 目录结构

```text
src/
├── benchmark/                  # JSON 数据类、loader 与 validator
├── core/
│   ├── execution/{preemptive,nonpreemptive}.py
│   ├── trace/{preemptive,nonpreemptive}.py
│   ├── dag.py
│   ├── conversion.py
│   └── oracle.py               # nonpreemptive 一般 DAG Exact
├── single_channel/
│   ├── parallel_chain/{preemptive,nonpreemptive}/
│   └── complex_chain/{preemptive,nonpreemptive}/
├── muti_channel/{preemptive,nonpreemptive}/
├── llm_structured/
├── registry.py                 # 只根据 JSON semantics 路由
└── cli.py
```

family 根目录不默认导出任何执行语义。导入实现时必须包含 `.preemptive` 或 `.nonpreemptive`；旧的 `src/preemptive`、`core.model` 以及 family 根目录 `solver.py/interface.py` 已移除。

## 执行语义

- preemptive：communication 在 task event 处可暂停/恢复，保留剩余工作；无主动 WAIT；多资源动作必须 work-conserving。
- nonpreemptive：历史 v1 maintenance baseline；communication 一旦启动便运行到完成，并保留其 optional-idle/WAIT 研究合同。
- 两种语义均使用 finish-to-start 依赖、自动且不可抢占的 compute，以及固定排他通信资源。

## 运行

```powershell
dag-schedule benchmark/single_channel/complex_chain/preemptive/adversarial/preemption_unlock.json --algorithm longest_tail
dag-schedule benchmark/single_channel/complex_chain/nonpreemptive/adversarial/random_join_30.json --algorithm rollout_wait2
```

未安装入口时：

```powershell
$env:PYTHONPATH="src;."
python src/cli.py benchmark/muti_channel/nonpreemptive/adversarial/nonmaximal_start_np.json --algorithm rollout_optional2
```

直接调用 Python 实现时，应从对应语义目录导入，例如：

```python
from single_channel.complex_chain.preemptive import solver
from single_channel.parallel_chain.nonpreemptive import solver as legacy_solver
```

新增算法时必须选择明确的 `family/semantics` 目录，在 `registry.py` 注册，并在镜像的测试目录下添加回归。算法不得从 metadata 或 reference result 读取答案，也不得自行实现另一套时间推进语义。
