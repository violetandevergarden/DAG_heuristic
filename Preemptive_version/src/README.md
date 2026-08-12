# 调度算法代码

`src/` 保存调度模型、Exact Oracle 和 heuristic。这里不再增加 `dag_heuristic/` 包装层，目录名直接对应问题场景。

## 目录结构

```text
src
├─ README.md                # 本文档
├─ build_index.py           # 重新生成 ./benchmark/index.jsonl
├─ reference.py             # 尝试为 ./benchmark/single_channel 中的所有测试点生成 reference_results
├─ test.py                  # 运行算法代码，并将其与已有的reference_results对比（目前测试内容硬编码，待修改）
│  
├─ benchmark                
│  ├─ loader.py             # JSON 读取、写出和字典转换，新增了将字典转换为仅内容的格式。
│  ├─ model.py              # Benchmark、Task、Resource 数据类
│  └─ validator.py          # DAG、资源和场景语义校验
│          
├─ core
│  ├─ counter.cpp           # 复杂度 O(n \log n)。根据图和优先级顺序，计算耗时。用于验证算法效果。
│  ├─ counter.exe
│  ├─ oracle.cpp            # 极限复杂度 O(n_t!) 但大多时候运行优秀。一般单通道小图 Exact Oracle，默认输出到命令行。运算过久时会自动退出，函数会返回 1。
│  └─ oracle.exe
│      
└─ single_channel
   ├─ …….cpp     # 算法代码
   └─ …….exe
```

## 算法

输入格式：
```text
n m                             # 任务数，依赖数
type[1]{'c','t'} duration[1]    # 第一个节点的类型，持续时长
……                              # ……

u[1] v[1]                       # 第一条依赖
……                              # ……
```

可通过 `benchmark/loader` 将字典转换为当前输入格式。

后续计划用 python 脚本重新封装 c++ 写的算法

主要实现：

- `longest_tail`：复杂度 O(n \log n)。最长尾链，不包含当前节点。
- `longest_tail2`：复杂度 O(n \log n)。最长尾链，包含当前节点。
- `rollout_1`：复杂度 O(n^3 \log n)。将最长尾链做法的结果作为参考值，每次枚举所有就绪任务，取参考值最小的拓展。（不知道如何命名，待重命名）（由于实现问题，现在的复杂度是 O(n^4)）

## 从 JSON 运行

Python 调用：

（待补充）

```python

```

## 添加新算法

1. 根据问题类型选择 `parallel_chain`、`complex_chain`。
2. 待补充

算法不得从 metadata 读取最优答案。有限 benchmark 上全部最优不能替代理论近似比证明。

## 重要语义和限制

- communication 可抢占，开始后必须运行到完成。
- ready compute 自动开始；有限 GPU 串行约束必须预先编码为 DAG 边。
- 暂不支持多通道问题不重新选路。
- 当前不模拟连续带宽比例共享；通信在完整持续时间内独占所需资源。
- Exact Oracle 只适合小图，用于标注、反例验证和 heuristic 对照。
- `src/` 禁止导入 `benchmark_generate`、SimAI 或修改 `sys.path`。

## 测试

```powershell
python ./src/test.py
```

