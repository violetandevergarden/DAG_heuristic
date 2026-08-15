"""Stable algorithm registry operating on public Benchmark objects."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable

from benchmark import Benchmark
from core.conversion import (
    to_internal_dag,
    to_multi_resource_instance,
    to_parallel_chains,
)


@dataclass(frozen=True)
class Algorithm:
    name: str
    scenario: str
    family: str
    solve: Callable[[Benchmark], object]
    description: str
    exact: bool = False
    supports_wait: bool = False
    semantics: str = "none"
    development_status: str = "maintenance"


def _parallel_registry() -> dict[str, Algorithm]:
    from single_channel.parallel_chain.nonpreemptive import solver

    convert = to_parallel_chains
    return {
        "longest_tail": Algorithm("longest_tail", "single_channel", "parallel_chain", lambda b: solver.schedule_priority(convert(b), "dynamic_tail"), "Dynamic residual longest-tail priority."),
        "rollout_flow2": Algorithm("rollout_flow2", "single_channel", "parallel_chain", lambda b: solver.schedule_rollout(convert(b), top_k=2, allow_wait=False), "Two whole-flow rollout candidates."),
        "rollout_wait2": Algorithm("rollout_wait2", "single_channel", "parallel_chain", lambda b: solver.schedule_rollout(convert(b), top_k=2, allow_wait=True), "Two whole-flow candidates plus WAIT.", supports_wait=True),
        "beam_wait8": Algorithm("beam_wait8", "single_channel", "parallel_chain", lambda b: solver.beam_search(convert(b), width=8, allow_wait=True), "Beam width 8 with optional idle.", supports_wait=True),
        "beam_wait32": Algorithm("beam_wait32", "single_channel", "parallel_chain", lambda b: solver.beam_search(convert(b), width=32, allow_wait=True), "Beam width 32 with optional idle.", supports_wait=True),
        "exact_optional": Algorithm("exact_optional", "single_channel", "parallel_chain", lambda b: solver.exact_dp(convert(b), optional_idle=True), "Exact small-instance DP.", exact=True, supports_wait=True),
    }


def _complex_registry() -> dict[str, Algorithm]:
    from single_channel.complex_chain.nonpreemptive import solver
    from core.oracle import exact_oracle

    convert = to_internal_dag
    return {
        "longest_tail": Algorithm("longest_tail", "single_channel", "complex_chain", lambda b: solver.schedule_priority(convert(b)), "Dynamic residual longest-tail priority."),
        "join_bonus": Algorithm("join_bonus", "single_channel", "complex_chain", lambda b: solver.schedule_priority(convert(b), "raw_join"), "Longest tail plus optimistic join bonus."),
        "rollout_flow2": Algorithm("rollout_flow2", "single_channel", "complex_chain", lambda b: solver.schedule_rollout(convert(b), top_k=2, allow_wait=False), "Two whole-flow rollout candidates."),
        "rollout_wait2": Algorithm("rollout_wait2", "single_channel", "complex_chain", lambda b: solver.schedule_rollout(convert(b), top_k=2, allow_wait=True), "Two whole-flow candidates plus WAIT.", supports_wait=True),
        "depth2_wait2": Algorithm("depth2_wait2", "single_channel", "complex_chain", lambda b: solver.schedule_rollout(convert(b), top_k=2, allow_wait=True, candidate_mode="hybrid", depth=2), "Depth-2 hybrid rollout with WAIT.", supports_wait=True),
        "beam_wait8": Algorithm("beam_wait8", "single_channel", "complex_chain", lambda b: solver.beam_search(convert(b), width=8), "Beam width 8 with optional idle.", supports_wait=True),
        "exact_optional": Algorithm("exact_optional", "single_channel", "complex_chain", lambda b: exact_oracle(convert(b), mode="optional_idle"), "Exact small-instance oracle.", exact=True, supports_wait=True),
    }


def _muti_registry() -> dict[str, Algorithm]:
    from muti_channel.nonpreemptive import solver

    convert = to_multi_resource_instance
    return {
        "longest_tail_pack": Algorithm("longest_tail_pack", "muti_channel", "complex_chain", lambda b: solver.schedule_greedy(convert(b), "dynamic_tail"), "Compatible packing in longest-tail order."),
        "resource_pack": Algorithm("resource_pack", "muti_channel", "complex_chain", lambda b: solver.schedule_greedy(convert(b), "resource_tail"), "Residual resource-load tie breaking."),
        "bottleneck_pack": Algorithm("bottleneck_pack", "muti_channel", "complex_chain", lambda b: solver.schedule_greedy(convert(b), "bottleneck_first"), "Remaining bottleneck resource first."),
        "rollout_maximal2": Algorithm("rollout_maximal2", "muti_channel", "complex_chain", lambda b: solver.schedule_rollout(convert(b), top_k=2, optional_actions=False), "Roll out maximal compatible sets."),
        "rollout_optional2": Algorithm("rollout_optional2", "muti_channel", "complex_chain", lambda b: solver.schedule_rollout(convert(b), top_k=2, optional_actions=True), "Roll out optional compatible sets and WAIT.", supports_wait=True),
        "exact_optional": Algorithm("exact_optional", "muti_channel", "complex_chain", lambda b: solver.exact_oracle(convert(b), mode="optional_idle"), "Exact small-instance resource oracle.", exact=True, supports_wait=True),
    }


def _preemptive_registry(benchmark: Benchmark) -> dict[str, Algorithm]:
    if benchmark.scenario == "muti_channel":
        from muti_channel.preemptive import solver as multi_solver

        def convert_multi(item: Benchmark):
            instance = to_multi_resource_instance(item)
            resources = {
                task_id: frozenset(str(resource) for resource in values)
                for task_id, values in instance.resources.items()
            }
            return instance.dag, resources

        return _active_v2({
            "longest_tail_pack": Algorithm("longest_tail_pack", "muti_channel", benchmark.family, lambda b: multi_solver.schedule_pack(*convert_multi(b), "longest_tail"), "Preemptive compatible packing in residual-tail order.", semantics="preemptive", development_status="active"),
            "resource_pack": Algorithm("resource_pack", "muti_channel", benchmark.family, lambda b: multi_solver.schedule_pack(*convert_multi(b), "resource_tail"), "Residual-tail packing with resource-load tie break.", semantics="preemptive", development_status="active"),
            "bottleneck_pack": Algorithm("bottleneck_pack", "muti_channel", benchmark.family, lambda b: multi_solver.schedule_pack(*convert_multi(b), "bottleneck"), "Bottleneck-load-first compatible packing.", semantics="preemptive", development_status="active"),
            "rollout_sets2": Algorithm("rollout_sets2", "muti_channel", benchmark.family, lambda b: multi_solver.rollout_sets(*convert_multi(b), top_k=2), "Top-2 maximal compatible-set rollout.", semantics="preemptive", development_status="active"),
            "exact": Algorithm("exact", "muti_channel", benchmark.family, lambda b: multi_solver.exact_oracle(*convert_multi(b)), "Exact small-state maximal-set Oracle.", exact=True, semantics="preemptive", development_status="active"),
        })
    if benchmark.scenario != "single_channel":
        raise ValueError(f"unsupported preemptive scenario: {benchmark.scenario}")
    if benchmark.family == "parallel_chain":
        from single_channel.parallel_chain.preemptive import solver
    elif benchmark.family == "complex_chain":
        from single_channel.complex_chain.preemptive import solver
    else:
        raise ValueError(f"unsupported preemptive family: {benchmark.family}")

    convert = to_internal_dag
    return _active_v2({
        "fifo": Algorithm("fifo", "single_channel", benchmark.family, lambda b: solver.schedule_priority(convert(b), "fifo"), "FIFO work-conserving priority.", semantics="preemptive"),
        "spt": Algorithm("spt", "single_channel", benchmark.family, lambda b: solver.schedule_priority(convert(b), "spt"), "Shortest remaining communication first.", semantics="preemptive"),
        "lpt": Algorithm("lpt", "single_channel", benchmark.family, lambda b: solver.schedule_priority(convert(b), "lpt"), "Longest remaining communication first.", semantics="preemptive"),
        "longest_delay": Algorithm("longest_delay", "single_channel", benchmark.family, lambda b: solver.schedule_priority(convert(b), "longest_delay"), "Compatibility alias of longest_tail; do not count as an independent algorithm.", semantics="preemptive", development_status="active"),
        "lrpt": Algorithm("lrpt", "single_channel", benchmark.family, lambda b: solver.schedule_priority(convert(b), "lrpt"), "Longest remaining path including current communication.", semantics="preemptive"),
        "longest_tail": Algorithm(
            "longest_tail",
            "single_channel",
            benchmark.family,
            lambda b: solver.schedule_longest_tail(to_internal_dag(b)),
            "Event-driven residual longest-tail with communication pause/resume.",
            supports_wait=False,
            semantics="preemptive",
            development_status="active",
        ),
        "rollout2": Algorithm("rollout2", "single_channel", benchmark.family, lambda b: solver.schedule_rollout(convert(b), top_k=2), "Top-2 one-event rollout with Longest-tail completion.", semantics="preemptive", development_status="active"),
        "join_rollout2": Algorithm("join_rollout2", "single_channel", benchmark.family, lambda b: solver.schedule_rollout(convert(b), top_k=2, candidate_mode="hybrid"), "Top-2 rollout with tail and last-join-blocker candidates.", semantics="preemptive"),
        "beam8": Algorithm("beam8", "single_channel", benchmark.family, lambda b: solver.beam_search(convert(b), width=8), "Width-8 event-state beam with Longest-tail incumbent.", semantics="preemptive"),
        "beam32": Algorithm("beam32", "single_channel", benchmark.family, lambda b: solver.beam_search(convert(b), width=32), "Width-32 event-state beam with Longest-tail incumbent.", semantics="preemptive"),
        "monte_carlo64": Algorithm("monte_carlo64", "single_channel", benchmark.family, lambda b: solver.monte_carlo(convert(b), samples=64, seed=0), "64 reproducible work-conserving schedule samples.", semantics="preemptive"),
        "exact": Algorithm("exact", "single_channel", benchmark.family, lambda b: solver.exact_oracle(convert(b)), "Exact memoized event-state Oracle for small DAGs.", exact=True, semantics="preemptive", development_status="active"),
    })


def _active_v2(algorithms: dict[str, Algorithm]) -> dict[str, Algorithm]:
    return {
        name: replace(
            algorithm,
            semantics="communication_resume",
            supports_wait=False,
            development_status="active",
        )
        for name, algorithm in algorithms.items()
    }


def algorithms_for(benchmark: Benchmark) -> dict[str, Algorithm]:
    if benchmark.semantics.is_preemptive:
        return _preemptive_registry(benchmark)
    if benchmark.scenario == "muti_channel":
        return _muti_registry()
    if benchmark.family == "parallel_chain":
        return _parallel_registry()
    if benchmark.family == "complex_chain":
        return _complex_registry()
    raise ValueError(f"unsupported benchmark family: {benchmark.family}")


def solve(benchmark: Benchmark, algorithm_name: str) -> object:
    algorithms = algorithms_for(benchmark)
    try:
        algorithm = algorithms[algorithm_name]
    except KeyError as error:
        raise ValueError(
            f"unknown algorithm {algorithm_name}; available: {', '.join(sorted(algorithms))}"
        ) from error
    return algorithm.solve(benchmark)
