"""Reproducible phase-6 experiments for hierarchical multi-job scheduling."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import random
from statistics import mean
from time import perf_counter

from benchmark_generate.cases import llm_motif_cases
from preemptive.multi_job import (
    JobSpec,
    MultiJobInstance,
    build_candidate_compression_case,
    build_multi_resource_top1_counterexample,
    build_parallel_chain_job,
    build_top1_attack_suite,
    compose_jobs,
    exact_hierarchical,
    exact_makespan,
    schedule_hierarchical,
    schedule_multi_resource_hierarchical,
    solo_optimal_jct,
    teacher_candidate_recall,
)


def run_study(*, samples: int = 30, seed: int = 260812) -> dict:
    cases = _make_cases(samples, seed)
    rows = [_evaluate_case(case_id, family, instance) for case_id, family, instance in cases]
    return {
        "model": {
            "jobs": "disjoint DAGs sharing one communication channel",
            "communication_preemption": "resume",
            "preemption_cost": 0,
            "minimum_quantum": 0,
            "primary_objective": "makespan",
            "secondary_reported_metrics": ["per_job_jct", "slowdown"],
        },
        "cases": rows,
        "summary": _summarize(rows),
        "objective_probe": _objective_probe(),
        "multi_resource_probe": _multi_resource_probe(),
    }


def _make_cases(
    samples: int,
    seed: int,
) -> list[tuple[str, str, MultiJobInstance]]:
    rng = random.Random(seed)
    cases = [
        (f"top1_attack_{index}", "adversarial", instance)
        for index, instance in enumerate(build_top1_attack_suite())
    ]
    cases.append((
        "candidate_compression",
        "adversarial_compression",
        build_candidate_compression_case(),
    ))
    motifs = {dag.name: dag for dag in llm_motif_cases()}
    motif_pairs = (
        ("pp_forward_wave", "pp_backward_wave"),
        ("one_f_one_b", "w_dp_optimizer_join"),
        ("one_f_one_b", "tp_collective_plus_pp"),
        ("one_f_one_b", "zb_bw_fork"),
        ("w_dp_optimizer_join", "tp_collective_plus_pp"),
    )
    cases.extend(
        (
            f"llm_motif_{index}",
            "llm_motif_mix",
            compose_jobs((
                JobSpec("A", motifs[first]),
                JobSpec("B", motifs[second]),
            )),
        )
        for index, (first, second) in enumerate(motif_pairs)
    )
    families = ("same_profile", "heterogeneous", "staggered_arrival")
    for index in range(samples):
        family = families[index % len(families)]
        first_shape = _random_shape(rng)
        if family == "same_profile":
            second_shape = first_shape
            arrival = 0
        elif family == "heterogeneous":
            second_shape = _random_shape(rng)
            arrival = 0
        else:
            second_shape = _random_shape(rng)
            arrival = rng.randint(1, 4)
        first = build_parallel_chain_job(f"job_a_{index}", first_shape)
        second = build_parallel_chain_job(f"job_b_{index}", second_shape)
        instance = compose_jobs((
            JobSpec("A", first),
            JobSpec("B", second, arrival=arrival),
        ))
        cases.append((f"random_{index:02d}", family, instance))
    return cases


def _random_shape(
    rng: random.Random,
) -> tuple[tuple[int, tuple[int, ...], tuple[int, ...]], ...]:
    return tuple(
        (
            rng.randint(0, 2),
            tuple(rng.randint(1, 4) for _ in range(2)),
            tuple(rng.randint(0, 5) for _ in range(2)),
        )
        for _ in range(2)
    )


def _evaluate_case(
    case_id: str,
    family: str,
    instance: MultiJobInstance,
) -> dict:
    exact_started = perf_counter()
    teacher = exact_makespan(instance, max_states=1_000_000, time_limit_s=20)
    exact_runtime = (perf_counter() - exact_started) * 1000
    solo = solo_optimal_jct(instance, max_states=500_000, time_limit_s=10)
    recall = teacher_candidate_recall(instance, teacher.schedule, (1, 2, 4))
    methods = {}

    for width in (1, 2):
        label = "exact_flat" if width is None else f"exact_k{width}"
        started = perf_counter()
        result = exact_hierarchical(
            instance,
            candidate_width=width,
            max_states=1_000_000,
            time_limit_s=20,
        )
        methods[label] = _result_row(
            result,
            teacher.makespan,
            (perf_counter() - started) * 1000,
            solo,
        )
    # K=4 exposes every ready flow in this study (at most three chains/job),
    # so it is exactly the flat teacher without a redundant second search.
    teacher_row = _result_row(teacher, teacher.makespan, exact_runtime, solo)
    methods["exact_k4"] = teacher_row
    methods["exact_flat"] = teacher_row

    heuristic_configs = (
        ("priority_k1", 1, "tail", False, "priority"),
        ("priority_k2", 2, "semantic_diverse", False, "priority"),
        ("rollout_k1", 1, "tail", False, "rollout"),
        ("rollout_k2", 2, "tail", False, "rollout"),
        ("rollout_k4", 4, "tail", False, "rollout"),
        ("rollout_flat", None, "tail", False, "rollout"),
        ("semantic_k2", 2, "semantic_diverse", False, "rollout"),
        ("adaptive_k1_4", 1, "semantic_diverse", True, "rollout"),
    )
    for label, width, candidate_mode, adaptive, global_mode in heuristic_configs:
        started = perf_counter()
        result = schedule_hierarchical(
            instance,
            candidate_width=width,
            candidate_mode=candidate_mode,
            global_mode=global_mode,
            adaptive=adaptive,
            max_adaptive_width=4,
        )
        methods[label] = _result_row(
            result,
            teacher.makespan,
            (perf_counter() - started) * 1000,
            solo,
        )

    solo_top1_ratios = []
    for job in instance.jobs:
        solo_instance = compose_jobs((JobSpec(job.job_id, job.dag),))
        solo_full = exact_makespan(solo_instance, time_limit_s=10)
        solo_k1 = exact_hierarchical(
            solo_instance,
            candidate_width=1,
            time_limit_s=10,
        )
        solo_top1_ratios.append(solo_k1.makespan / solo_full.makespan)
    return {
        "id": case_id,
        "family": family,
        "task_count": len(instance.dag.tasks),
        "arrival": {job.job_id: job.arrival for job in instance.jobs},
        "teacher": {
            "makespan": teacher.makespan,
            "explored_states": teacher.schedule.explored_states,
            "runtime_ms": exact_runtime,
            "jobs": [asdict(job) for job in teacher.jobs],
        },
        "teacher_candidate_recall": {str(key): value for key, value in recall.items()},
        "solo_top1_ratio_mean": mean(solo_top1_ratios),
        "methods": methods,
    }


def _result_row(result, optimum: int, runtime_ms: float, solo: dict[str, int]) -> dict:
    jobs = []
    for job in result.jobs:
        denominator = solo[job.job_id]
        jobs.append({
            **asdict(job),
            "slowdown": job.jct / denominator,
        })
    return {
        "makespan": result.makespan,
        "ratio": result.makespan / optimum,
        "runtime_ms": runtime_ms,
        "explored_states": result.schedule.explored_states,
        "candidate_evaluations": result.candidate_evaluations,
        "mean_candidates": (
            mean(result.candidate_counts) if result.candidate_counts else 0.0
        ),
        "weighted_jct": result.weighted_jct,
        "max_slowdown": max(job["slowdown"] for job in jobs),
        "jobs": jobs,
    }


def _summarize(rows: list[dict]) -> dict:
    labels = tuple(rows[0]["methods"])
    method_summary = {}
    for label in labels:
        values = [row["methods"][label] for row in rows]
        method_summary[label] = {
            "mean_ratio": mean(value["ratio"] for value in values),
            "max_ratio": max(value["ratio"] for value in values),
            "optimal_fraction": mean(value["ratio"] == 1.0 for value in values),
            "mean_runtime_ms": mean(value["runtime_ms"] for value in values),
            "mean_candidates": mean(value["mean_candidates"] for value in values),
            "mean_candidate_evaluations": mean(
                value["candidate_evaluations"] for value in values
            ),
            "mean_max_slowdown": mean(value["max_slowdown"] for value in values),
        }
    by_family = {}
    for family in sorted({row["family"] for row in rows}):
        selected = [row for row in rows if row["family"] == family]
        by_family[family] = {
            label: {
                "mean_ratio": mean(row["methods"][label]["ratio"] for row in selected),
                "max_ratio": max(row["methods"][label]["ratio"] for row in selected),
            }
            for label in labels
        }
    return {
        "case_count": len(rows),
        "methods": method_summary,
        "by_family": by_family,
        "candidate_recall": {
            width: mean(row["teacher_candidate_recall"][width] for row in rows)
            for width in ("1", "2", "4")
        },
        "solo_top1_ratio_mean": mean(row["solo_top1_ratio_mean"] for row in rows),
        "colocated_exact_k1_ratio_mean": mean(
            row["methods"]["exact_k1"]["ratio"] for row in rows
        ),
    }


def _objective_probe() -> list[dict]:
    long_job = build_parallel_chain_job("long", ((0, (10,), (0,)),))
    short_job = build_parallel_chain_job("short", ((0, (1,), (0,)),))
    medium_job = build_parallel_chain_job("medium", ((0, (3,), (0,)),))
    cases = (
        (
            "long_short_same_arrival",
            (JobSpec("long", long_job), JobSpec("short", short_job)),
        ),
        (
            "short_arrives_during_long",
            (JobSpec("long", long_job), JobSpec("short", short_job, arrival=3)),
        ),
        (
            "three_staggered",
            (
                JobSpec("long", long_job),
                JobSpec("medium", medium_job, arrival=2),
                JobSpec("short", short_job, arrival=4),
            ),
        ),
        (
            "weighted_short",
            (
                JobSpec("long", long_job),
                JobSpec("short", short_job, weight=5.0),
            ),
        ),
        (
            "weighted_long",
            (
                JobSpec("long", long_job, weight=20.0),
                JobSpec("short", short_job),
            ),
        ),
    )
    rows = []
    for case_id, specs in cases:
        instance = compose_jobs(specs)
        makespan_optimum = exact_hierarchical(
            instance,
            candidate_width=None,
            objective="makespan",
        )
        jct_optimum = exact_hierarchical(
            instance,
            candidate_width=None,
            objective="weighted_jct",
        )
        methods = {
            "exact_makespan": makespan_optimum,
            "exact_weighted_jct": jct_optimum,
            "critical_priority": schedule_hierarchical(
                instance,
                candidate_width=1,
                global_mode="priority",
            ),
            "shortest_job": schedule_hierarchical(
                instance,
                candidate_width=1,
                global_mode="shortest_job",
            ),
            "attained_service": schedule_hierarchical(
                instance,
                candidate_width=1,
                global_mode="attained_service",
            ),
        }
        rows.append({
            "id": case_id,
            "optimal_makespan": makespan_optimum.makespan,
            "optimal_weighted_jct": jct_optimum.weighted_jct,
            "methods": {
                label: {
                    "makespan": result.makespan,
                    "makespan_ratio": result.makespan / makespan_optimum.makespan,
                    "weighted_jct": result.weighted_jct,
                    "weighted_jct_ratio": result.weighted_jct / jct_optimum.weighted_jct,
                    "completion": {
                        job.job_id: job.completion for job in result.jobs
                    },
                }
                for label, result in methods.items()
            },
        })
    return rows


def _multi_resource_probe() -> dict:
    from preemptive.muti_channel.solver import exact_oracle as multi_exact

    instance, resources = build_multi_resource_top1_counterexample()
    exact = multi_exact(instance.dag, resources)
    methods = {
        "hierarchical_k1": schedule_multi_resource_hierarchical(
            instance,
            resources,
            candidate_width=1,
        ),
        "hierarchical_k2": schedule_multi_resource_hierarchical(
            instance,
            resources,
            candidate_width=2,
        ),
        "flat": schedule_multi_resource_hierarchical(
            instance,
            resources,
            candidate_width=None,
        ),
    }
    return {
        "exact_makespan": exact.makespan,
        "description": (
            "K=1 hides Job A's private-link candidate while Job B uses the "
            "shared uplink, leaving a compatible resource idle."
        ),
        "methods": {
            label: {
                "makespan": result.makespan,
                "ratio": result.makespan / exact.makespan,
                "first_action": list(result.actions[0].communications),
            }
            for label, result in methods.items()
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--seed", type=int, default=260812)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run_study(samples=args.samples, seed=args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"wrote multi-job study to {args.output}")


if __name__ == "__main__":
    main()
