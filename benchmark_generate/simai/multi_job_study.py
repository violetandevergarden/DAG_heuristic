"""Probe hierarchical multi-job scheduling on small SimAI pipeline DAGs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean
from time import perf_counter

from benchmark_generate.simai.export import (
    build_synthetic_input,
    build_workload,
    to_benchmark,
)
from core.conversion import to_internal_dag
from llm_structured.multi_job import (
    JobSpec,
    compose_jobs,
    schedule_hierarchical,
    teacher_candidate_recall,
)


def run_pipeline_probe() -> dict:
    profiles = {
        mode: _pipeline_job(mode)
        for mode in ("1f1b", "interleaved_1f1b")
    }
    configurations = (
        ("same_1f1b", "1f1b", "1f1b", 0),
        ("mixed", "1f1b", "interleaved_1f1b", 0),
        ("same_interleaved", "interleaved_1f1b", "interleaved_1f1b", 0),
        ("mixed_staggered", "1f1b", "interleaved_1f1b", 1_000_000),
    )
    rows = []
    for case_id, first, second, arrival in configurations:
        instance = compose_jobs((
            JobSpec("A", profiles[first]),
            JobSpec("B", profiles[second], arrival=arrival),
        ))
        methods = {}
        settings = (
            ("priority_k1", 1, "tail", False, "priority"),
            ("priority_k2", 2, "semantic_diverse", False, "priority"),
            ("rollout_k1", 1, "tail", False, "rollout"),
            ("rollout_k2", 2, "tail", False, "rollout"),
            ("rollout_k4", 4, "tail", False, "rollout"),
            ("rollout_flat", None, "tail", False, "rollout"),
            ("semantic_k2", 2, "semantic_diverse", False, "rollout"),
            ("adaptive_k1_4", 1, "semantic_diverse", True, "rollout"),
        )
        results = {}
        for label, width, candidate_mode, adaptive, global_mode in settings:
            started = perf_counter()
            result = schedule_hierarchical(
                instance,
                candidate_width=width,
                candidate_mode=candidate_mode,
                global_mode=global_mode,
                adaptive=adaptive,
                max_adaptive_width=4,
            )
            results[label] = result
            methods[label] = {
                "makespan": result.makespan,
                "runtime_ms": (perf_counter() - started) * 1000,
                "candidate_evaluations": result.candidate_evaluations,
                "mean_candidates": mean(result.candidate_counts),
            }
        teacher = results["rollout_flat"]
        for values in methods.values():
            values["ratio_to_flat_rollout"] = values["makespan"] / teacher.makespan
        rows.append({
            "id": case_id,
            "first_mode": first,
            "second_mode": second,
            "second_arrival": arrival,
            "task_count": len(instance.dag.tasks),
            "teacher_candidate_recall": {
                str(width): value
                for width, value in teacher_candidate_recall(
                    instance,
                    teacher.schedule,
                    (1, 2, 4),
                ).items()
            },
            "methods": methods,
        })
    return {
        "model": {
            "source": "small synthetic inputs expanded by SimAI pipeline builders",
            "warning": "Flat Rollout is a teacher, not a proof of optimality.",
        },
        "cases": rows,
        "summary": {
            label: {
                "mean_ratio_to_flat_rollout": mean(
                    row["methods"][label]["ratio_to_flat_rollout"] for row in rows
                ),
                "max_ratio_to_flat_rollout": max(
                    row["methods"][label]["ratio_to_flat_rollout"] for row in rows
                ),
                "mean_candidate_evaluations": mean(
                    row["methods"][label]["candidate_evaluations"] for row in rows
                ),
                "mean_runtime_ms": mean(
                    row["methods"][label]["runtime_ms"] for row in rows
                ),
            }
            for label in rows[0]["methods"]
        },
    }


def _pipeline_job(mode: str):
    header, items = build_synthetic_input(pp=2, ga=2, layers=2)
    benchmark = to_benchmark(
        build_workload(mode, header, items),
        f"multi_job_probe_{mode}",
        bandwidth_gbps=0.01,
    )
    return to_internal_dag(benchmark)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run_pipeline_probe()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"wrote pipeline multi-job probe to {args.output}")


if __name__ == "__main__":
    main()
