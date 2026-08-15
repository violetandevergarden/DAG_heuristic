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
    category: str = "adversarial",
) -> list[Path]:
    written = []
    for source in sorted(benchmark_root.rglob("*.json")):
        if "schema" in source.parts or "reference_results" in source.parts:
            continue
        benchmark = load_benchmark(source)
        if benchmark.category != category:
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
                    from core.conversion import to_internal_dag
                    if benchmark.family == "parallel_chain":
                        from single_channel.parallel_chain.preemptive.solver import exact_oracle
                    else:
                        from single_channel.complex_chain.preemptive.solver import exact_oracle

                    result = exact_oracle(
                        to_internal_dag(benchmark), max_states=100_000, time_limit_s=5.0
                    )
                else:
                    from core.conversion import to_multi_resource_instance
                    from muti_channel.preemptive.solver import exact_oracle

                    instance = to_multi_resource_instance(benchmark)
                    result = exact_oracle(
                        instance.dag,
                        {key: frozenset(str(value) for value in values) for key, values in instance.resources.items()},
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
