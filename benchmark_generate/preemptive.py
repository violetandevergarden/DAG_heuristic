"""Generate v2 snapshots by lifting v1 DAGs into preemptive semantics."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from benchmark import SchedulingSemantics, write_benchmark
from benchmark_generate.export import current_cases


PREEMPTIVE_SEMANTICS = SchedulingSemantics(
    preemption="communication_resume",
    decision_epoch="task_event",
    optional_idle=False,
    compute_model="unbounded_parallel",
    resource_model="exclusive_fixed_set",
    preemption_cost=0,
    minimum_quantum=0,
)


def export_preemptive_suite(
    root: Path,
    *,
    samples: int = 10,
    seed: int = 260819,
) -> list[Path]:
    """Write fixed random/adversarial DAGs under ``benchmark/preemptive``."""

    written: list[Path] = []
    for item in current_cases(samples=samples, seed=seed):
        benchmark = item.benchmark
        if benchmark.category not in {"random", "adversarial"}:
            continue
        lifted = replace(
            benchmark,
            benchmark_id=f"pm_{benchmark.benchmark_id}",
            schema_version="2.0",
            semantics=PREEMPTIVE_SEMANTICS,
            metadata={
                **benchmark.metadata,
                "lifted_from": benchmark.benchmark_id,
                "preemptive_generator_seed": seed,
            },
        )
        if benchmark.scenario == "single_channel":
            relative = Path("preemptive") / "single_channel" / benchmark.family / benchmark.category / f"{lifted.benchmark_id}.json"
        else:
            relative = Path("preemptive") / "muti_channel" / benchmark.category / f"{lifted.benchmark_id}.json"
        target = root / relative
        write_benchmark(lifted, target)
        written.append(target)
    return written
