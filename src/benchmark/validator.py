"""Semantic validation not expressible in JSON Schema."""

from __future__ import annotations

from collections import defaultdict, deque

from benchmark.model import Benchmark


class BenchmarkValidationError(ValueError):
    """Raised when a benchmark violates the versioned scheduling contract."""


def validation_errors(benchmark: Benchmark) -> list[str]:
    errors: list[str] = []
    if benchmark.schema_version not in {"1.0", "2.0"}:
        errors.append(f"unsupported schema_version: {benchmark.schema_version}")
    if benchmark.objective != "makespan":
        errors.append(f"unsupported objective: {benchmark.objective}")
    semantics = benchmark.semantics
    if not isinstance(semantics.optional_idle, bool):
        errors.append("optional_idle must be boolean")
    elif benchmark.schema_version == "1.0" and not semantics.optional_idle:
        errors.append("historical schema v1 requires optional_idle=true")
    elif benchmark.schema_version == "2.0" and semantics.optional_idle:
        errors.append("preemptive schema v2 forbids voluntary idle")
    if benchmark.schema_version == "1.0" and semantics.is_preemptive:
        errors.append("schema v1 does not support preemption")
    if semantics.preemption not in {"none", "communication_resume"}:
        errors.append(f"unsupported preemption mode: {semantics.preemption}")
    if semantics.decision_epoch not in {"task_completion", "task_event"}:
        errors.append(f"unsupported decision epoch: {semantics.decision_epoch}")
    if semantics.compute_model != "unbounded_parallel":
        errors.append(f"unsupported compute model: {semantics.compute_model}")
    if semantics.resource_model not in {"exclusive", "exclusive_fixed_set"}:
        errors.append(f"unsupported resource model: {semantics.resource_model}")
    if semantics.preemption_cost < 0 or semantics.minimum_quantum < 0:
        errors.append("preemption cost and minimum quantum must be non-negative")
    if semantics.is_preemptive:
        if benchmark.schema_version != "2.0":
            errors.append("preemptive benchmarks require schema v2")
        if semantics.decision_epoch != "task_event":
            errors.append("communication preemption requires decision_epoch=task_event")
        if semantics.resource_model != "exclusive_fixed_set":
            errors.append("communication preemption requires fixed resource sets")
        if semantics.preemption_cost != 0 or semantics.minimum_quantum != 0:
            errors.append(
                "the current preemptive core supports only zero-cost, zero-quantum preemption"
            )
    elif benchmark.schema_version == "2.0":
        errors.append("schema v2 is currently reserved for communication_resume benchmarks")
    task_ids = [task.task_id for task in benchmark.tasks]
    resource_ids = [resource.resource_id for resource in benchmark.resources]
    if len(task_ids) != len(set(task_ids)):
        errors.append("duplicate task id")
    if len(resource_ids) != len(set(resource_ids)):
        errors.append("duplicate resource id")
    known_tasks = set(task_ids)
    known_resources = set(resource_ids)
    for task in benchmark.tasks:
        if task.duration < 0:
            errors.append(f"{task.task_id}: negative duration")
        if task.kind == "communication" and task.duration <= 0:
            errors.append(f"{task.task_id}: communication duration must be positive")
        if task.kind not in {"compute", "communication"}:
            errors.append(f"{task.task_id}: unknown task kind {task.kind}")
        missing_deps = set(task.dependencies) - known_tasks
        if missing_deps:
            errors.append(f"{task.task_id}: unknown dependencies {sorted(missing_deps)}")
        if task.task_id in task.dependencies:
            errors.append(f"{task.task_id}: self dependency")
        if len(task.dependencies) != len(set(task.dependencies)):
            errors.append(f"{task.task_id}: duplicate dependency")
        missing_resources = set(task.resources) - known_resources
        if missing_resources:
            errors.append(f"{task.task_id}: unknown resources {sorted(missing_resources)}")
        if len(task.resources) != len(set(task.resources)):
            errors.append(f"{task.task_id}: duplicate resource")
        if task.kind == "compute" and task.resources:
            errors.append(f"{task.task_id}: compute task cannot reserve resources")
        if task.kind == "communication" and not task.resources:
            errors.append(f"{task.task_id}: communication task needs a resource")
    if not errors:
        errors.extend(_cycle_errors(benchmark))
    if benchmark.scenario == "single_channel":
        if resource_ids != ["channel:0"]:
            errors.append("single_channel must define exactly channel:0")
        for task in benchmark.tasks:
            if task.kind == "communication" and task.resources != ("channel:0",):
                errors.append(f"{task.task_id}: single-channel communication must use channel:0")
    if benchmark.family == "parallel_chain":
        errors.extend(_parallel_chain_errors(benchmark))
    if benchmark.scenario == "muti_channel" and benchmark.family != "complex_chain":
        errors.append("muti_channel requires family=complex_chain")
    return errors


def validate_benchmark(benchmark: Benchmark) -> None:
    errors = validation_errors(benchmark)
    if errors:
        raise BenchmarkValidationError("; ".join(errors))


def _cycle_errors(benchmark: Benchmark) -> list[str]:
    indegree = {task.task_id: len(task.dependencies) for task in benchmark.tasks}
    children: dict[str, list[str]] = defaultdict(list)
    for task in benchmark.tasks:
        for dependency in task.dependencies:
            children[dependency].append(task.task_id)
    ready = deque(sorted(task_id for task_id, degree in indegree.items() if degree == 0))
    visited = 0
    while ready:
        task_id = ready.popleft()
        visited += 1
        for child in children[task_id]:
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
    return [] if visited == len(indegree) else ["task dependencies contain a cycle"]


def _parallel_chain_errors(benchmark: Benchmark) -> list[str]:
    indegree = {task.task_id: len(task.dependencies) for task in benchmark.tasks}
    outdegree = {task.task_id: 0 for task in benchmark.tasks}
    for task in benchmark.tasks:
        for dependency in task.dependencies:
            outdegree[dependency] += 1
    errors = []
    for task_id, degree in indegree.items():
        if degree > 1 or outdegree[task_id] > 1:
            errors.append(f"{task_id}: parallel_chain nodes must have degree at most one")
    tasks = benchmark.task_map()
    for task in benchmark.tasks:
        for parent in task.dependencies:
            if tasks[parent].kind == task.kind:
                errors.append(
                    f"{parent} -> {task.task_id}: parallel_chain tasks must strictly "
                    "alternate compute and communication"
                )
    return errors
