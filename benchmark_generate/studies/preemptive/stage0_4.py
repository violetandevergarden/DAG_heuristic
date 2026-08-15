"""Reproducible stage 0-4 runner for the communication-resume mainline."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean
from time import perf_counter

from benchmark import load_benchmark
from core.conversion import to_internal_dag, to_multi_resource_instance
from muti_channel.preemptive import solver as multi
from single_channel.complex_chain.preemptive import solver as single


def run_study(root: Path) -> dict:
    single_rows = []
    multi_rows = []
    skipped = []
    for path in sorted(root.rglob("*.json")):
        if "schema" in path.parts or "reference_results" in path.parts:
            continue
        benchmark = load_benchmark(path)
        if not benchmark.semantics.is_preemptive:
            continue
        if benchmark.scenario == "single_channel":
            dag = to_internal_dag(benchmark)
            try:
                exact = single.exact_oracle(dag, max_states=150_000, time_limit_s=5.0)
            except (RuntimeError, TimeoutError) as error:
                skipped.append({"id": benchmark.benchmark_id, "reason": type(error).__name__})
                continue
            methods = {
                "fifo": lambda dag=dag: single.schedule_priority(dag, "fifo"),
                "spt": lambda dag=dag: single.schedule_priority(dag, "spt"),
                "lpt": lambda dag=dag: single.schedule_priority(dag, "lpt"),
                "longest_tail": lambda dag=dag: single.schedule_longest_tail(dag),
                "lrpt": lambda dag=dag: single.schedule_priority(dag, "lrpt"),
                "rollout2": lambda dag=dag: single.schedule_rollout(dag, top_k=2),
                "join_rollout2": lambda dag=dag: single.schedule_rollout(dag, top_k=2, candidate_mode="hybrid"),
                "beam8": lambda dag=dag: single.beam_search(dag, width=8),
                "beam32": lambda dag=dag: single.beam_search(dag, width=32),
                "monte_carlo64": lambda dag=dag: single.monte_carlo(dag, samples=64, seed=260812),
            }
            results = {}
            for name, solve in methods.items():
                started = perf_counter()
                result = solve()
                results[name] = {
                    "makespan": result.makespan,
                    "ratio": result.makespan / exact.makespan,
                    "runtime_ms": (perf_counter() - started) * 1000,
                    "preemptions": result.preemptions,
                }
            single_rows.append({
                "id": benchmark.benchmark_id,
                "family": benchmark.family,
                "category": benchmark.category,
                "opt": exact.makespan,
                "results": results,
            })
        else:
            instance = to_multi_resource_instance(benchmark)
            resources = {
                key: frozenset(str(value) for value in values)
                for key, values in instance.resources.items()
            }
            try:
                exact = multi.exact_oracle(
                    instance.dag, resources, max_states=150_000, time_limit_s=5.0
                )
            except (RuntimeError, TimeoutError) as error:
                skipped.append({"id": benchmark.benchmark_id, "reason": type(error).__name__})
                continue
            methods = {
                "longest_tail_pack": lambda instance=instance, resources=resources: multi.schedule_pack(instance.dag, resources, "longest_tail"),
                "resource_pack": lambda instance=instance, resources=resources: multi.schedule_pack(instance.dag, resources, "resource_tail"),
                "bottleneck_pack": lambda instance=instance, resources=resources: multi.schedule_pack(instance.dag, resources, "bottleneck"),
                "rollout_sets2": lambda instance=instance, resources=resources: multi.rollout_sets(instance.dag, resources, top_k=2),
            }
            results = {}
            for name, solve in methods.items():
                started = perf_counter()
                result = solve()
                results[name] = {
                    "makespan": result.makespan,
                    "ratio": result.makespan / exact.makespan,
                    "runtime_ms": (perf_counter() - started) * 1000,
                    "preemptions": result.preemptions,
                }
            multi_rows.append({
                "id": benchmark.benchmark_id,
                "category": benchmark.category,
                "opt": exact.makespan,
                "results": results,
            })
    return {
        "model": {
            "preemption": "communication_resume",
            "decision_epoch": "task_event",
            "preemption_cost": 0,
            "minimum_quantum": 0,
            "work_conserving": True,
        },
        "single_channel": {
            "instances": single_rows,
            "summary": _summarize(single_rows),
        },
        "muti_channel": {
            "instances": multi_rows,
            "summary": _summarize(multi_rows),
        },
        "skipped_exact": skipped,
    }


def _summarize(rows: list[dict]) -> dict:
    values: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        for method, result in row["results"].items():
            values[method].append(result)
    return {
        method: {
            "instances": len(results),
            "mean_ratio": mean(item["ratio"] for item in results),
            "max_ratio": max(item["ratio"] for item in results),
            "optimal_fraction": mean(item["ratio"] == 1.0 for item in results),
            "mean_runtime_ms": mean(item["runtime_ms"] for item in results),
            "mean_preemptions": mean(item["preemptions"] for item in results),
        }
        for method, results in values.items()
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark-root", type=Path, default=Path("benchmark"))
    parser.add_argument("--output", type=Path, default=Path("docs/preemptive实验结果.json"))
    args = parser.parse_args()
    report = run_study(args.benchmark_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps({
        "single_exact": len(report["single_channel"]["instances"]),
        "multi_exact": len(report["muti_channel"]["instances"]),
        "skipped": len(report["skipped_exact"]),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
