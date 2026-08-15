"""Load and write canonical DAG benchmark JSON files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from benchmark.model import Benchmark, Resource, SchedulingSemantics, Task
from benchmark.validator import BenchmarkValidationError, validate_benchmark


def benchmark_from_dict(payload: dict[str, Any]) -> Benchmark:
    required = {
        "schema_version", "id", "scenario", "family", "category", "objective",
        "time_unit", "semantics", "resources", "tasks",
    }
    missing = required - payload.keys()
    if missing:
        raise BenchmarkValidationError(f"missing top-level fields: {sorted(missing)}")
    version = str(payload["schema_version"])
    raw_semantics = payload["semantics"]
    if not isinstance(raw_semantics, dict):
        raise BenchmarkValidationError("semantics must be an object")
    semantics = _parse_semantics(version, raw_semantics)
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
            semantics=semantics,
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
        "semantics": _semantics_to_dict(benchmark),
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


def _parse_semantics(version: str, payload: dict[str, Any]) -> SchedulingSemantics:
    if version == "1.0":
        expected = {
            "preemptive": False,
            "decision_epoch": "task_completion",
            "optional_idle": True,
            "compute_model": "unbounded_parallel",
            "resource_model": "exclusive",
        }
        if payload != expected:
            raise BenchmarkValidationError("unsupported v1 scheduling semantics")
        return SchedulingSemantics()
    if version == "2.0":
        expected_keys = {
            "preemption", "decision_epoch", "optional_idle", "compute_model",
            "resource_model", "preemption_cost", "minimum_quantum",
        }
        if set(payload) != expected_keys:
            raise BenchmarkValidationError(
                f"invalid v2 semantics fields: expected {sorted(expected_keys)}"
            )
        if not isinstance(payload["optional_idle"], bool):
            raise BenchmarkValidationError("optional_idle must be boolean")
        for field in ("preemption_cost", "minimum_quantum"):
            if not isinstance(payload[field], int) or isinstance(payload[field], bool):
                raise BenchmarkValidationError(f"{field} must be an integer")
        try:
            return SchedulingSemantics(
                preemption=payload["preemption"],
                decision_epoch=payload["decision_epoch"],
                # Early v2 snapshots incorrectly wrote optional_idle=true.
                # The versioned loader accepts those files only as a migration
                # input and normalizes them to the sole production contract.
                optional_idle=False,
                compute_model=payload["compute_model"],
                resource_model=payload["resource_model"],
                preemption_cost=int(payload["preemption_cost"]),
                minimum_quantum=int(payload["minimum_quantum"]),
            )
        except (TypeError, ValueError) as error:
            raise BenchmarkValidationError(f"invalid v2 semantics: {error}") from error
    raise BenchmarkValidationError(f"unsupported schema_version: {version}")


def _semantics_to_dict(benchmark: Benchmark) -> dict[str, Any]:
    semantics = benchmark.semantics
    if benchmark.schema_version == "1.0":
        if semantics != SchedulingSemantics():
            raise BenchmarkValidationError("v1 supports only non-preemptive semantics")
        return {
            "preemptive": False,
            "decision_epoch": "task_completion",
            "optional_idle": True,
            "compute_model": "unbounded_parallel",
            "resource_model": "exclusive",
        }
    if benchmark.schema_version == "2.0":
        return {
            "preemption": semantics.preemption,
            "decision_epoch": semantics.decision_epoch,
            "optional_idle": semantics.optional_idle,
            "compute_model": semantics.compute_model,
            "resource_model": semantics.resource_model,
            "preemption_cost": semantics.preemption_cost,
            "minimum_quantum": semantics.minimum_quantum,
        }
    raise BenchmarkValidationError(
        f"unsupported schema_version: {benchmark.schema_version}"
    )
