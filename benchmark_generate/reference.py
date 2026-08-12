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
        exact = algorithms_for(benchmark).get("exact_optional")
        if exact is None or not exact.exact:
            # A benchmark is not ground truth until its execution semantics
            # have a matching exact solver.  In particular, the initial v2
            # preemptive framework deliberately ships without an Oracle.
            continue
        result = solve(benchmark, "exact_optional")
        makespan = getattr(result, "makespan", None)
        if not isinstance(makespan, int):
            raise TypeError(f"exact result for {benchmark.benchmark_id} has no integer makespan")
        relative = source.relative_to(benchmark_root)
        target = benchmark_root / "reference_results" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "benchmark_id": benchmark.benchmark_id,
                    "benchmark_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                    "oracle": "exact_optional",
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
