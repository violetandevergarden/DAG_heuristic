"""Run the preemptive LLM repetition study and emit a machine-readable report."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import random
from statistics import mean
from time import perf_counter

from benchmark import Benchmark, Task
from benchmark_generate.simai.export import (
    AicbParser,
    BuiltWorkload,
    build_synthetic_input,
    build_workload,
    to_benchmark,
)
from benchmark_generate.simai.repetition import scan_repetition
from core.dag import BenchmarkDAG
from core.conversion import to_internal_dag
from llm_structured.repetition import (
    build_exchangeable_replicas,
    build_pp_dp_repetition,
    exact_oracle_component_symmetry,
    schedule_coupling_aware,
    schedule_role_copy,
)
from single_channel.complex_chain.preemptive.solver import (
    exact_oracle,
    schedule_longest_tail,
    schedule_rollout,
)


PIPELINE_MODES = ("1f1b", "interleaved_1f1b", "zero_bubble")


def run_study(aicb_root: Path | None = None) -> dict:
    synthetic = _scan_synthetic_grid()
    real, real_errors = _scan_real_aicb(aicb_root) if aicb_root else ([], [])
    return {
        "model": {
            "communication_preemption": "resume",
            "preemption_cost": 0,
            "minimum_quantum": 0,
            "decision_epoch": "task_event",
            "zero_bubble_semantics": (
                "Raw Zero Bubble data dependencies fork B and W from shared "
                "readiness. Exported benchmarks additionally encode the "
                "serializer-owned single-GPU compute order."
            ),
        },
        "structure": {
            "synthetic_grid": synthetic,
            "real_aicb": real,
            "real_errors": real_errors,
            "summary": _structure_summary(synthetic, real),
            "placement_probe": _placement_probe(),
        },
        "period_extension": _period_extension(),
        "pipeline_scheduler_probe": _pipeline_scheduler_probe(),
        "symmetry_exact": _symmetry_experiment(),
        "runtime_scaling": _runtime_scaling(),
        "duration_robustness": _duration_robustness(),
    }


def _scan_synthetic_grid() -> list[dict]:
    rows = []
    for mode in PIPELINE_MODES:
        for pp in (2, 4):
            for multiplier in (1, 2, 4):
                ga = pp * multiplier
                header, items = build_synthetic_input(
                    pp=pp, tp=1, dp=1, ga=ga, layers=4,
                )
                built = build_workload(mode, header, items, vpp=2)
                benchmark = to_benchmark(
                    built,
                    f"synthetic_{mode}_pp{pp}_ga{ga}",
                )
                report = scan_repetition(benchmark).to_dict()
                report["parallelism"] = benchmark.metadata["parallelism"]
                report["ga"] = ga
                report["raw_data_b_to_w_edges"] = _raw_b_to_w_edges(built)
                report["usable_for_scheduling_conclusion"] = (
                    mode != "zero_bubble"
                    or report["raw_data_b_to_w_edges"] == 0
                )
                rows.append(report)
    # Mixed parallel dimensions on a fixed 1F1B skeleton.
    for tp, dp, pp, ga in ((2, 1, 4, 8), (1, 2, 4, 8), (2, 2, 4, 8)):
        header, items = build_synthetic_input(
            pp=pp, tp=tp, dp=dp, ga=ga, layers=4,
        )
        benchmark = to_benchmark(
            build_workload("1f1b", header, items),
            f"synthetic_3d_tp{tp}_dp{dp}_pp{pp}",
        )
        report = scan_repetition(benchmark).to_dict()
        report["parallelism"] = benchmark.metadata["parallelism"]
        report["ga"] = ga
        report["usable_for_scheduling_conclusion"] = True
        rows.append(report)
    header, items = build_synthetic_input(
        pp=4, tp=2, dp=4, ep=2, ga=8, layers=4,
    )
    benchmark = to_benchmark(
        build_workload("1f1b", header, items),
        "synthetic_4d_tp2_dp4_pp4_ep2",
    )
    report = scan_repetition(benchmark).to_dict()
    report["parallelism"] = benchmark.metadata["parallelism"]
    report["ga"] = 8
    report["usable_for_scheduling_conclusion"] = True
    rows.append(report)
    return rows


def _scan_real_aicb(root: Path) -> tuple[list[dict], list[dict]]:
    selectors = (
        ("gpt_pp2_ga4", "*gpt_13B*pp2*ep1*gbs4-mbs1*"),
        ("gpt_pp4_ga4", "*gpt_13B*pp4*ep1*gbs4-mbs1*"),
        ("mixtral_ep2_pp2_ga4", "*Mixtral_8x7B*pp2*ep2*gbs4-mbs1*"),
    )
    rows: list[dict] = []
    errors: list[dict] = []
    for label, pattern in selectors:
        matches = sorted(root.glob(pattern))
        if not matches:
            errors.append({"profile": label, "error": f"no file matched {pattern}"})
            continue
        path = matches[0]
        header, items = AicbParser().parse(path)
        modes = PIPELINE_MODES if "gpt" in label else ("1f1b",)
        for mode in modes:
            try:
                built = build_workload(mode, header, items, vpp=2)
                benchmark = to_benchmark(
                    built,
                    f"{label}_{mode}",
                )
                report = scan_repetition(benchmark).to_dict()
                report["source_file"] = path.name
                report["parallelism"] = benchmark.metadata["parallelism"]
                report["ga"] = header.ga
                report["raw_data_b_to_w_edges"] = _raw_b_to_w_edges(built)
                report["usable_for_scheduling_conclusion"] = (
                    mode != "zero_bubble"
                    or report["raw_data_b_to_w_edges"] == 0
                )
                rows.append(report)
            except Exception as error:  # audit must preserve unsupported profiles
                errors.append({
                    "profile": label,
                    "mode": mode,
                    "error": f"{type(error).__name__}: {error}",
                })
    return rows, errors


def _structure_summary(synthetic: list[dict], real: list[dict]) -> dict:
    def summarize(rows: list[dict]) -> dict:
        if not rows:
            return {}
        fields = (
            "structural_repetition",
            "resource_repetition",
            "timing_repetition",
            "cross_microbatch_dependency_fraction",
            "cross_microbatch_conflict_fraction",
            "communication_conflict_density",
            "conservative_exchangeable_task_fraction",
        )
        return {
            field: {
                "mean": mean(row[field] for row in rows),
                "min": min(row[field] for row in rows),
                "max": max(row[field] for row in rows),
            }
            for field in fields
        }
    return {"synthetic": summarize(synthetic), "real": summarize(real)}


def _raw_b_to_w_edges(built: BuiltWorkload) -> int:
    """Count data-DAG B -> W edges before compute-order serialization."""
    task_by_id = {task.task_id: task for task in built.workload.tasks}
    count = 0
    for task_id, info in built.task_info.items():
        if getattr(info, "task_role", None) != "W":
            continue
        task = task_by_id[task_id]
        if any(
            getattr(built.task_info.get(parent), "task_role", None) == "B"
            and getattr(built.task_info.get(parent), "b_task_id", None)
            == getattr(info, "b_task_id", None)
            for parent in task.deps
        ):
            count += 1
    return count


def _project_resources(benchmark: Benchmark, placement: str) -> Benchmark:
    def resource_for(task: Task) -> tuple[str, ...]:
        if task.kind != "communication":
            return ()
        comm_type = str(task.metadata.get("comm_type", "unknown"))
        dimension = comm_type.split("_", 1)[0]
        if placement == "isolated_dimensions":
            return (f"fabric:{dimension}",)
        if placement == "pp_dp_shared_uplink":
            if dimension in {"pp", "dp"}:
                return ("uplink:shared", f"fabric:{dimension}")
            return (f"fabric:{dimension}",)
        return ("channel:global",)
    return replace(
        benchmark,
        benchmark_id=f"{benchmark.benchmark_id}_{placement}",
        scenario="muti_channel",
        tasks=tuple(replace(task, resources=resource_for(task)) for task in benchmark.tasks),
        metadata={**benchmark.metadata, "placement_probe": placement},
    )


def _placement_probe() -> list[dict]:
    header, items = build_synthetic_input(pp=4, tp=2, dp=2, ga=8, layers=4)
    base = to_benchmark(build_workload("1f1b", header, items), "placement_base")
    rows = []
    for placement in ("global_channel", "isolated_dimensions", "pp_dp_shared_uplink"):
        report = scan_repetition(_project_resources(base, placement)).to_dict()
        report["placement"] = placement
        rows.append(report)
    return rows


def _period_extension() -> list[dict]:
    rows = []
    for periods in (1, 2, 4, 8, 16):
        dag = build_pp_dp_repetition(periods)
        exact = exact_oracle(dag, time_limit_s=10) if periods <= 8 else None
        results = {
            "independent_copy": schedule_role_copy(dag, "DP"),
            "boundary_aware": schedule_coupling_aware(dag),
            "longest_tail": schedule_longest_tail(dag),
            "rollout2": schedule_rollout(dag),
        }
        optimal = exact.makespan if exact else results["rollout2"].makespan
        rows.append({
            "periods": periods,
            "teacher": "exact" if exact else "rollout2",
            "teacher_makespan": optimal,
            "methods": {
                name: {
                    "makespan": result.makespan,
                    "ratio": result.makespan / optimal,
                    "preemptions": result.preemptions,
                }
                for name, result in results.items()
            },
        })
    return rows


def _pipeline_scheduler_probe() -> list[dict]:
    """Check the structure rule on pipeline DAGs not designed for that rule."""

    rows = []
    for mode in PIPELINE_MODES:
        for ga in (2, 4):
            header, items = build_synthetic_input(pp=2, ga=ga, layers=2)
            built = build_workload(mode, header, items)
            benchmark = to_benchmark(
                built,
                f"scheduler_probe_{mode}_ga{ga}",
                bandwidth_gbps=0.01,
            )
            dag = to_internal_dag(benchmark)
            methods = {
                "coupling_aware": schedule_coupling_aware,
                "longest_tail": schedule_longest_tail,
                "rollout2": schedule_rollout,
            }
            results = {}
            for name, method in methods.items():
                started = perf_counter()
                result = method(dag)
                results[name] = {
                    "makespan": result.makespan,
                    "runtime_ms": (perf_counter() - started) * 1000,
                    "preemptions": result.preemptions,
                }
            if ga == 2:
                exact = exact_oracle(dag, max_states=500_000, time_limit_s=10)
                teacher = exact.makespan
                teacher_name = "exact"
            else:
                teacher = results["rollout2"]["makespan"]
                teacher_name = "rollout2"
            for values in results.values():
                values["ratio"] = values["makespan"] / teacher
            rows.append({
                "pipeline_mode": mode,
                "ga": ga,
                "task_count": len(dag.tasks),
                "teacher": teacher_name,
                "teacher_makespan": teacher,
                "raw_data_b_to_w_edges": _raw_b_to_w_edges(built),
                "usable_for_scheduling_conclusion": (
                    mode != "zero_bubble"
                    or _raw_b_to_w_edges(built) == 0
                ),
                "methods": results,
            })
    return rows


def _symmetry_experiment() -> list[dict]:
    rows = []
    for replicas in (2, 3, 4, 5, 6, 7):
        dag, components = build_exchangeable_replicas(replicas)
        generic = _timed_exact(lambda: exact_oracle(
            dag, max_states=1_000_000, time_limit_s=10,
        ))
        compressed = _timed_exact(lambda: exact_oracle_component_symmetry(
            dag, components, max_states=1_000_000, time_limit_s=10,
        ))
        rows.append({"replicas": replicas, "generic": generic, "compressed": compressed})
    return rows


def _timed_exact(call) -> dict:
    started = perf_counter()
    try:
        result = call()
        return {
            "status": "ok",
            "makespan": result.makespan,
            "explored_states": result.explored_states,
            "runtime_ms": (perf_counter() - started) * 1000,
        }
    except (TimeoutError, RuntimeError) as error:
        return {
            "status": "timeout_or_limit",
            "error": str(error),
            "runtime_ms": (perf_counter() - started) * 1000,
        }


def _runtime_scaling() -> list[dict]:
    rows = []
    methods = {
        "coupling_aware": schedule_coupling_aware,
        "longest_tail": schedule_longest_tail,
        "rollout2": schedule_rollout,
    }
    for periods in (16, 32, 64):
        dag = build_pp_dp_repetition(periods)
        row = {"periods": periods, "methods": {}}
        for name, method in methods.items():
            started = perf_counter()
            result = method(dag)
            row["methods"][name] = {
                "makespan": result.makespan,
                "runtime_ms": (perf_counter() - started) * 1000,
            }
        rows.append(row)
    return rows


def _perturb(dag: BenchmarkDAG, magnitude: float, seed: int) -> BenchmarkDAG:
    rng = random.Random(seed)
    tasks = []
    for task in dag.tasks:
        if task.duration == 0:
            tasks.append(task)
            continue
        factor = 1.0 + rng.uniform(-magnitude, magnitude)
        tasks.append(replace(task, duration=max(1, round(task.duration * 10 * factor))))
    return replace(dag, name=f"{dag.name}_jitter{magnitude}_{seed}", tasks=tuple(tasks))


def _duration_robustness() -> list[dict]:
    rows = []
    base = build_pp_dp_repetition(4, pp_work=3, dp_work=3, release_gap=3, dp_tail=3)
    for magnitude in (0.05, 0.10, 0.20):
        for seed in range(20):
            dag = _perturb(base, magnitude, seed)
            exact = exact_oracle(dag, max_states=500_000, time_limit_s=5)
            aware = schedule_coupling_aware(dag)
            rollout = schedule_rollout(dag)
            rows.append({
                "magnitude": magnitude,
                "seed": seed,
                "exact": exact.makespan,
                "coupling_aware": aware.makespan,
                "coupling_aware_ratio": aware.makespan / exact.makespan,
                "rollout2": rollout.makespan,
                "rollout2_ratio": rollout.makespan / exact.makespan,
            })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--aicb-root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run_study(args.aicb_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"wrote repetition study to {args.output}")


if __name__ == "__main__":
    main()
