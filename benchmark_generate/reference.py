"""Generate exact reference sidecars for small committed benchmark files."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from benchmark import load_benchmark
from registry import algorithms_for, solve


def generate_reference_results(
    benchmark_root: Path,
    *,
    category: str | None = "adversarial",
    relative_prefix: Path | None = None,
) -> list[Path]:
    written = []
    search_root = benchmark_root / relative_prefix if relative_prefix else benchmark_root
    for source in sorted(search_root.rglob("*.json")):
        if "schema" in source.parts or "reference_results" in source.parts:
            continue
        benchmark = load_benchmark(source)
        if category is not None and benchmark.category != category:
            continue
        exact_name = "exact" if benchmark.semantics.is_preemptive else "exact_optional"
        exact = algorithms_for(benchmark).get(exact_name)
        if exact is None or not exact.exact:
            # A benchmark is not ground truth until its execution semantics
            # have a matching exact solver.  In particular, the initial v2
            # preemptive framework deliberately ships without an Oracle.
            continue
        try:
            if benchmark.semantics.is_preemptive:
                if benchmark.scenario == "single_channel":
                    from core.conversion import to_dag

                    if benchmark.family == "parallel_chain":
                        from single_channel.parallel_chain.preemptive.solver import exact_oracle
                    else:
                        from single_channel.complex_chain.preemptive.solver import exact_oracle

                    result = exact_oracle(
                        to_dag(benchmark), max_states=100_000, time_limit_s=5.0
                    )
                else:
                    from core.conversion import to_muti_resourse
                    from muti_channel.preemptive.solver import exact_oracle

                    instance = to_muti_resourse(benchmark)
                    result = exact_oracle(
                        instance.dag,
                        {
                            key: frozenset(str(value) for value in values)
                            for key, values in instance.resources.items()
                        },
                        max_states=100_000,
                        time_limit_s=5.0,
                    )
            else:
                result = solve(benchmark, exact_name)
        except (RuntimeError, TimeoutError):
            # A timed-out result is not an optimum certificate.  Keep the
            # benchmark but deliberately omit its reference sidecar.
            continue
        makespan = getattr(result, "makespan", None)
        if not isinstance(makespan, int):
            raise TypeError(f"exact result for {benchmark.benchmark_id} has no integer makespan")
        if benchmark.semantics.is_preemptive and getattr(result, "status", None) != "optimal":
            # Stage 2/3 reference results require a machine-readable completed
            # enumeration certificate. A feasible budget fallback is not an
            # optimum even if its incumbent matches a historical sidecar.
            continue
        relative = source.relative_to(benchmark_root)
        target = benchmark_root / "reference_results" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(
                {
                    "schema_version": benchmark.schema_version,
                    "benchmark_id": benchmark.benchmark_id,
                    "benchmark_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                    "oracle": exact_name,
                    "oracle_status": getattr(result, "status", "legacy_optimal"),
                    "oracle_runtime_ms": getattr(result, "runtime_ms", None),
                    "oracle_explored_states": getattr(result, "explored_states", None),
                    "oracle_generated_transitions": getattr(
                        result, "generated_transitions", None
                    ),
                    "oracle_lower_bound": getattr(result, "lower_bound", None),
                    "oracle_compatible_sets_generated": getattr(
                        result, "compatible_sets_generated", None
                    ),
                    "oracle_peak_states": getattr(result, "peak_states", None),
                    "oracle_peak_memory_bytes": getattr(
                        result, "peak_memory_bytes", None
                    ),
                    "oracle_termination_reason": getattr(
                        result, "termination_reason", None
                    ),
                    "oracle_budget": {"max_states": 100_000, "time_limit_s": 5.0},
                    "optimal_makespan": makespan,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        written.append(target)
    return written
