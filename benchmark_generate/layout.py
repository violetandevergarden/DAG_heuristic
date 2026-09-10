"""Canonical benchmark layout shared by all generators."""

from __future__ import annotations

from pathlib import Path

from benchmark import Benchmark

LAYOUT_VERSION = "2"


def semantics_name(benchmark: Benchmark) -> str:
    return "preemptive" if benchmark.semantics.is_preemptive else "nonpreemptive"


def benchmark_relative_path(benchmark: Benchmark) -> Path:
    semantics = semantics_name(benchmark)
    filename = f"{benchmark.benchmark_id}.json"
    if benchmark.scenario == "muti_channel":
        return Path(benchmark.scenario) / semantics / benchmark.category / filename
    return (
        Path(benchmark.scenario)
        / benchmark.family
        / semantics
        / benchmark.category
        / filename
    )
