from __future__ import annotations
"""Load and write canonical DAG benchmark JSON files."""
"""相较于原版loader，新增了将一个dag输出到控制台的部分，用于与 c++ 部分代码交流。"""
import json
from pathlib import Path
from typing import Any

try:
    from src.benchmark.model import Benchmark, Resource, Task
except:
    try:
        from benchmark.model import Benchmark, Resource, Task
    except:
        from model import Benchmark, Resource, Task
try:
    from src.benchmark.validator import BenchmarkValidationError, validate_benchmark
except:
    try:
        from benchmark.validator import BenchmarkValidationError, validate_benchmark
    except:
        from validator import BenchmarkValidationError, validate_benchmark


def benchmark_from_dict(payload: dict[str, Any]) -> Benchmark:
    required = {
        "schema_version", "id", "scenario", "family", "category", "objective",
        "time_unit", "semantics", "resources", "tasks",
    }
    missing = required - payload.keys()
    if missing:
        raise BenchmarkValidationError(f"missing top-level fields: {sorted(missing)}")
    expected_semantics = {
        "preemptive": True,
        "decision_epoch": "task_completion",
        "optional_idle": True,
        "compute_model": "unbounded_parallel",
        "resource_model": "exclusive",
    }
    if payload["semantics"] != expected_semantics:
        raise BenchmarkValidationError("unsupported scheduling semantics")
    try:
        benchmark = Benchmark(
            benchmark_id=str(payload["id"]),
            scenario=payload["scenario"],
            family=str(payload["family"]),
            category=str(payload["category"]),
            tasks=tuple(
                Task(
                    task_id=str(task["id"]),
                    kind=task["kind"],
                    duration=int(task["duration"]),
                    dependencies=tuple(task.get("dependencies", ())),
                    resources=tuple(task.get("resources", ())),
                    metadata=dict(task.get("metadata", {})),
                )
                for task in payload["tasks"]
            ),
            resources=tuple(
                Resource(
                    resource_id=str(resource["id"]),
                    kind=str(resource["kind"]),
                    metadata=dict(resource.get("metadata", {})),
                )
                for resource in payload["resources"]
            ),
            time_unit=str(payload["time_unit"]),
            metadata=dict(payload.get("metadata", {})),
            schema_version=str(payload["schema_version"]),
            objective=str(payload["objective"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise BenchmarkValidationError(f"invalid benchmark fields: {error}") from error
    validate_benchmark(benchmark)
    return benchmark


def benchmark_to_dict(benchmark: Benchmark) -> dict[str, Any]:
    validate_benchmark(benchmark)
    return {
        "schema_version": benchmark.schema_version,
        "id": benchmark.benchmark_id,
        "scenario": benchmark.scenario,
        "family": benchmark.family,
        "category": benchmark.category,
        "objective": benchmark.objective,
        "time_unit": benchmark.time_unit,
        "semantics": {
            "preemptive": True,
            "decision_epoch": "task_completion",
            "optional_idle": True,
            "compute_model": "unbounded_parallel",
            "resource_model": "exclusive",
        },
        "resources": [
            {"id": item.resource_id, "kind": item.kind, **({"metadata": item.metadata} if item.metadata else {})}
            for item in benchmark.resources
        ],
        "tasks": [
            {
                "id": task.task_id,
                "kind": task.kind,
                "duration": task.duration,
                "dependencies": list(task.dependencies),
                "resources": list(task.resources),
                **({"metadata": task.metadata} if task.metadata else {}),
            }
            for task in benchmark.tasks
        ],
        **({"metadata": benchmark.metadata} if benchmark.metadata else {}),
    }


def load_benchmark(path: str | Path) -> Benchmark:
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BenchmarkValidationError(f"cannot read {source}: {error}") from error
    if not isinstance(payload, dict):
        raise BenchmarkValidationError("benchmark root must be a JSON object")
    return benchmark_from_dict(payload)


def write_benchmark(benchmark: Benchmark, path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(benchmark_to_dict(benchmark), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )

def print_dag(data: dict[str, Any]) -> None:
    """读取 dict，按规范格式打印 DAG 信息到标准输出。

    要求：
    - 检查 resources 是否仅有一种 kind，否则报错。
    - 第一行输出：任务数量 依赖总数
    - 将任务从 1 开始顺序编号（按 tasks 列表顺序）。
    - 每个任务一行：类型（c 表示计算节点，t 表示通信节点） 时长
    - 每个依赖一行：前置任务编号 后继任务编号
    """

    # 1. 检查 resources
    resources = data.get("resources", [])
    if not resources:
        raise ValueError("至少需要一个资源")
    resource_kinds = {r["kind"] for r in resources}
    if len(resource_kinds) != 1:
        raise ValueError(f"resources 种类必须唯一，当前存在: {resource_kinds}")

    # 2. 获取任务列表
    tasks = data.get("tasks", [])
    if not tasks:
        print("0 0")
        return

    # 3. 建立 原始id -> 新编号 的映射（按任务列表顺序，从1开始）
    id_to_num: dict[str, int] = {}
    for idx, task in enumerate(tasks, start=1):
        task_id = task["id"]
        if task_id in id_to_num:
            raise ValueError(f"重复的任务 id: {task_id}")
        id_to_num[task_id] = idx

    # 4. 计算依赖总数
    total_deps = sum(len(task.get("dependencies", [])) for task in tasks)

    # 5. 输出第一行
    print(f"{len(tasks)} {total_deps}")

    # 6. 输出每个任务的类型和时长
    for task in tasks:
        kind = task["kind"]
        if kind == "compute":
            type_char = "c"
        elif kind == "communication":
            type_char = "t"
        else:
            raise ValueError(f"不支持的任务类型: {kind}（仅支持 compute 和 communication）")
        duration = task["duration"]
        print(f"{type_char} {duration}")

    # 7. 输出所有依赖关系（u 必须在 v 开始前完成，即 u -> v）
    for task in tasks:
        v_num = id_to_num[task["id"]]
        for dep_id in task.get("dependencies", []):
            u_num = id_to_num[dep_id]
            print(f"{u_num} {v_num}")

from typing import List, Dict, Any

def convert_simple_to_json(
    simple_str: str,
    id: str,
    category: str = "adversarial",
    family: str = "complex_chain"
) -> Dict[str, Any]:
    """
    将简化表述的图转换为标准 DAG 调度 JSON 结构。

    参数:
        simple_str (str): 符合格式的多行字符串
        id (str): 任务的标识符
        category (str): 类别，默认 "adversarial"
        family (str): 家族，默认 "complex_chain"

    返回:
        dict: 符合 JSON Schema 的完整结构

    异常:
        ValueError: 输入格式错误时抛出
    """
    # 去除首尾空白，并按行分割，忽略空行
    lines = [line.strip() for line in simple_str.strip().splitlines() if line.strip()]
    if not lines:
        raise ValueError("输入为空")

    # 解析第一行：n m
    first = lines[0].split()
    if len(first) != 2:
        raise ValueError("第一行必须包含两个整数：n 和 m")
    try:
        n, m = map(int, first)
    except ValueError:
        raise ValueError("第一行必须为整数")

    if len(lines) < 1 + n + m:
        raise ValueError(f"输入行数不足：需要 {1+n+m} 行，实际 {len(lines)} 行")

    # 解析节点信息（第2～1+n行）
    node_types = []   # 存储每个节点的类型字符 'c' 或 't'
    node_durations = []  # 存储每个节点的时长
    for i in range(1, 1 + n):
        parts = lines[i].split()
        if len(parts) != 2:
            raise ValueError(f"第 {i+1} 行必须包含类型和时长两个字段")
        typ, dur_str = parts[0], parts[1]
        if typ not in ('c', 't'):
            raise ValueError(f"类型只能是 'c' 或 't'，得到 '{typ}'")
        try:
            dur = int(dur_str)
        except ValueError:
            raise ValueError(f"时长必须是整数，得到 '{dur_str}'")
        node_types.append(typ)
        node_durations.append(dur)

    # 解析依赖边（第2+n～1+n+m行）
    # 使用列表存储每个节点的前驱依赖（用字符串 id 表示）
    dependencies: List[List[str]] = [[] for _ in range(n)]
    for i in range(1 + n, 1 + n + m):
        parts = lines[i].split()
        if len(parts) != 2:
            raise ValueError(f"依赖行 {i+1} 必须包含 u 和 v 两个整数")
        try:
            u, v = map(int, parts)
        except ValueError:
            raise ValueError(f"依赖行 {i+1} 必须为整数")
        if u < 1 or v < 1 or u > n or v > n:
            raise ValueError(f"节点编号超出范围 (1~{n})，得到 u={u}, v={v}")
        # 将前驱节点 u 加入 v 的依赖列表（v 依赖于 u）
        dependencies[v-1].append(str(u))

    # 构建 tasks 列表
    tasks = []
    for idx in range(n):
        typ = node_types[idx]
        dur = node_durations[idx]
        task_id = str(idx + 1)          # 节点编号作为 id
        kind = "compute" if typ == 'c' else "communication"
        # 通信任务需要 channel:0 资源，计算任务无资源需求
        resources = ["channel:0"] if kind == "communication" else []
        task = {
            "id": task_id,
            "kind": kind,
            "duration": dur,
            "dependencies": dependencies[idx],
            "resources": resources
        }
        tasks.append(task)

    # 构造完整的 JSON 结构（固定字段与样例保持一致）
    result = {
        "schema_version": "1.0",
        "id": id,
        "scenario": "single_channel",
        "family": family,
        "category": category,
        "objective": "makespan",
        "time_unit": "tick",
        "semantics": {
            "preemptive": True,
            "decision_epoch": "task_completion",
            "optional_idle": True,
            "compute_model": "unbounded_parallel",
            "resource_model": "exclusive"
        },
        "resources": [
            {"id": "channel:0", "kind": "channel"}
        ],
        "tasks": tasks,
        "metadata": {
            "description": "",
            "generator": "",
            "parameters": {},
            "seed": None
        }
    }
    return result


# # ===== 使用示例 =====
# if __name__ == "__main__":
#     simple_input = """8 6
# t 2
# c 3
# t 1
# c 1
# t 1
# c 2
# t 2
# c 1
# 1 2
# 2 3
# 3 4
# 5 6
# 6 7
# 7 8"""
#     result = convert_simple_to_json(simple_input, id="example_graph")
#     # 输出格式化的 JSON（便于查看）
#     print(json.dumps(result, indent=2, ensure_ascii=False))