"""Run algorithms on language-independent benchmark files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import perf_counter

from benchmark import load_benchmark
from registry import algorithms_for, solve


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("benchmark", type=Path)
    parser.add_argument("--algorithm")
    parser.add_argument("--list-algorithms", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    benchmark = load_benchmark(args.benchmark)
    algorithms = algorithms_for(benchmark)
    if args.list_algorithms:
        for name, algorithm in sorted(algorithms.items()):
            print(f"{name}: {algorithm.description}")
        return
    if not args.algorithm:
        parser.error("--algorithm is required unless --list-algorithms is used")
    started = perf_counter()
    result = solve(benchmark, args.algorithm)
    makespan = getattr(result, "makespan", None)
    if not isinstance(makespan, int):
        raise TypeError("algorithm result must expose integer makespan")
    report = {
        "benchmark_id": benchmark.benchmark_id,
        "semantics": benchmark.semantics.preemption,
        "algorithm": args.algorithm,
        "makespan": makespan,
        "runtime_ms": (perf_counter() - started) * 1000,
    }
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")


if __name__ == "__main__":
    main()
