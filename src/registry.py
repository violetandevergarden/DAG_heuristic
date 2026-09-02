"""Stable algorithm registry operating on public Benchmark objects."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

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
        "longest_tail": Algorithm(
            "longest_tail",
            "single_channel",
            "parallel_chain",
            lambda b: solver.schedule_priority(convert(b), "dynamic_tail"),
            "Dynamic residual longest-tail priority.",
        ),
        "rollout_flow2": Algorithm(
            "rollout_flow2",
            "single_channel",
            "parallel_chain",
            lambda b: solver.schedule_rollout(convert(b), top_k=2, allow_wait=False),
            "Two whole-flow rollout candidates.",
        ),
        "rollout_wait2": Algorithm(
            "rollout_wait2",
            "single_channel",
            "parallel_chain",
            lambda b: solver.schedule_rollout(convert(b), top_k=2, allow_wait=True),
            "Two whole-flow candidates plus WAIT.",
            supports_wait=True,
        ),
        "beam_wait8": Algorithm(
            "beam_wait8",
            "single_channel",
            "parallel_chain",
            lambda b: solver.beam_search(convert(b), width=8, allow_wait=True),
            "Beam width 8 with optional idle.",
            supports_wait=True,
        ),
        "beam_wait32": Algorithm(
            "beam_wait32",
            "single_channel",
            "parallel_chain",
            lambda b: solver.beam_search(convert(b), width=32, allow_wait=True),
            "Beam width 32 with optional idle.",
            supports_wait=True,
        ),
        "exact_optional": Algorithm(
            "exact_optional",
            "single_channel",
            "parallel_chain",
            lambda b: solver.exact_dp(convert(b), optional_idle=True),
            "Exact small-instance DP.",
            exact=True,
            supports_wait=True,
        ),
    }


def _complex_registry() -> dict[str, Algorithm]:
    from core.oracle import exact_oracle
    from single_channel.complex_chain.nonpreemptive import solver

    convert = to_internal_dag
    return {
        "longest_tail": Algorithm(
            "longest_tail",
            "single_channel",
            "complex_chain",
            lambda b: solver.schedule_priority(convert(b)),
            "Dynamic residual longest-tail priority.",
        ),
        "join_bonus": Algorithm(
            "join_bonus",
            "single_channel",
            "complex_chain",
            lambda b: solver.schedule_priority(convert(b), "raw_join"),
            "Longest tail plus optimistic join bonus.",
        ),
        "rollout_flow2": Algorithm(
            "rollout_flow2",
            "single_channel",
            "complex_chain",
            lambda b: solver.schedule_rollout(convert(b), top_k=2, allow_wait=False),
            "Two whole-flow rollout candidates.",
        ),
        "rollout_wait2": Algorithm(
            "rollout_wait2",
            "single_channel",
            "complex_chain",
            lambda b: solver.schedule_rollout(convert(b), top_k=2, allow_wait=True),
            "Two whole-flow candidates plus WAIT.",
            supports_wait=True,
        ),
        "depth2_wait2": Algorithm(
            "depth2_wait2",
            "single_channel",
            "complex_chain",
            lambda b: solver.schedule_rollout(
                convert(b), top_k=2, allow_wait=True, candidate_mode="hybrid", depth=2
            ),
            "Depth-2 hybrid rollout with WAIT.",
            supports_wait=True,
        ),
        "beam_wait8": Algorithm(
            "beam_wait8",
            "single_channel",
            "complex_chain",
            lambda b: solver.beam_search(convert(b), width=8),
            "Beam width 8 with optional idle.",
            supports_wait=True,
        ),
        "exact_optional": Algorithm(
            "exact_optional",
            "single_channel",
            "complex_chain",
            lambda b: exact_oracle(convert(b), mode="optional_idle"),
            "Exact small-instance oracle.",
            exact=True,
            supports_wait=True,
        ),
    }


def _muti_registry() -> dict[str, Algorithm]:
    from muti_channel.nonpreemptive import solver

    convert = to_multi_resource_instance
    return {
        "longest_tail_pack": Algorithm(
            "longest_tail_pack",
            "muti_channel",
            "complex_chain",
            lambda b: solver.schedule_greedy(convert(b), "dynamic_tail"),
            "Compatible packing in longest-tail order.",
        ),
        "resource_pack": Algorithm(
            "resource_pack",
            "muti_channel",
            "complex_chain",
            lambda b: solver.schedule_greedy(convert(b), "resource_tail"),
            "Residual resource-load tie breaking.",
        ),
        "bottleneck_pack": Algorithm(
            "bottleneck_pack",
            "muti_channel",
            "complex_chain",
            lambda b: solver.schedule_greedy(convert(b), "bottleneck_first"),
            "Remaining bottleneck resource first.",
        ),
        "rollout_maximal2": Algorithm(
            "rollout_maximal2",
            "muti_channel",
            "complex_chain",
            lambda b: solver.schedule_rollout(convert(b), top_k=2, optional_actions=False),
            "Roll out maximal compatible sets.",
        ),
        "rollout_optional2": Algorithm(
            "rollout_optional2",
            "muti_channel",
            "complex_chain",
            lambda b: solver.schedule_rollout(convert(b), top_k=2, optional_actions=True),
            "Roll out optional compatible sets and WAIT.",
            supports_wait=True,
        ),
        "exact_optional": Algorithm(
            "exact_optional",
            "muti_channel",
            "complex_chain",
            lambda b: solver.exact_oracle(convert(b), mode="optional_idle"),
            "Exact small-instance resource oracle.",
            exact=True,
            supports_wait=True,
        ),
    }


def _preemptive_registry(benchmark: Benchmark) -> dict[str, Algorithm]:
    if benchmark.scenario == "muti_channel":
        from muti_channel.preemptive import interface as multi_interface
        from muti_channel.preemptive import solver as multi_solver

        def convert_multi(item: Benchmark):
            instance = to_multi_resource_instance(item)
            resources = {
                task_id: frozenset(str(resource) for resource in values)
                for task_id, values in instance.resources.items()
            }
            return instance.dag, resources

        return _active_v2(
            {
                "longest_tail_pack": Algorithm(
                    "longest_tail_pack",
                    "muti_channel",
                    benchmark.family,
                    lambda b: multi_interface.solve(*convert_multi(b), "longest_tail_pack"),
                    "Stable deployment baseline: greedy maximal packing in residual-tail order.",
                ),
                "resource_pack": Algorithm(
                    "resource_pack",
                    "muti_channel",
                    benchmark.family,
                    lambda b: multi_interface.solve(*convert_multi(b), "resource_pack"),
                    "Research ablation: residual-tail packing with resource-load tie break.",
                ),
                "bottleneck_pack": Algorithm(
                    "bottleneck_pack",
                    "muti_channel",
                    benchmark.family,
                    lambda b: multi_interface.solve(*convert_multi(b), "bottleneck_pack"),
                    "Research baseline: bottleneck-load-first packing; not a deployment candidate.",
                ),
                "integrated_v0": Algorithm(
                    "integrated_v0",
                    "muti_channel",
                    benchmark.family,
                    lambda b: multi_interface.solve(*convert_multi(b), "integrated_v0"),
                    "Frozen Stage 4g baseline: residual-LT greedy maximal packing.",
                ),
                "resource_downstream_pack": Algorithm(
                    "resource_downstream_pack",
                    "muti_channel",
                    benchmark.family,
                    lambda b: multi_interface.solve(*convert_multi(b), "resource_downstream_pack"),
                    "Resource-vector downstream-demand candidate; mean and worst must both be audited.",
                ),
                "union_downstream_set": Algorithm(
                    "union_downstream_set",
                    "muti_channel",
                    benchmark.family,
                    lambda b: multi_interface.solve(*convert_multi(b), "union_downstream_set"),
                    "Whole-set candidate using the union of reachable downstream nodes.",
                ),
                "rollout_sets2d2": Algorithm(
                    "rollout_sets2d2",
                    "muti_channel",
                    benchmark.family,
                    lambda b: multi_interface.solve(*convert_multi(b), "rollout_sets2d2"),
                    "Budgeted top-2 depth-2 compatible-set Rollout with deterministic LT fallback.",
                ),
                "exact": Algorithm(
                    "exact",
                    "muti_channel",
                    benchmark.family,
                    lambda b: multi_solver.exact_oracle(
                        *convert_multi(b), max_states=300_000, time_limit_s=5.0
                    ),
                    "Budgeted normalized Exact; only status=optimal is a certificate.",
                    exact=True,
                ),
                "exact_uncompressed": Algorithm(
                    "exact_uncompressed",
                    "muti_channel",
                    benchmark.family,
                    lambda b: multi_solver.exact_oracle_uncompressed(
                        *convert_multi(b), max_states=100_000, time_limit_s=5.0
                    ),
                    "Audit Exact retaining absolute event-state fields.",
                    exact=True,
                ),
            }
        )
    if benchmark.scenario != "single_channel":
        raise ValueError(f"unsupported preemptive scenario: {benchmark.scenario}")
    if benchmark.family == "parallel_chain":
        from single_channel.parallel_chain.preemptive import solver

        convert = to_internal_dag
        return _active_v2(
            {
                "fifo": Algorithm(
                    "fifo",
                    "single_channel",
                    benchmark.family,
                    lambda b: solver.schedule_priority(convert(b), "fifo"),
                    "First-eligible-time FIFO with stable task-ID ties.",
                ),
                "spt": Algorithm(
                    "spt",
                    "single_channel",
                    benchmark.family,
                    lambda b: solver.schedule_priority(convert(b), "spt"),
                    "Shortest remaining communication first.",
                ),
                "lpt": Algorithm(
                    "lpt",
                    "single_channel",
                    benchmark.family,
                    lambda b: solver.schedule_priority(convert(b), "lpt"),
                    "Longest remaining communication first.",
                ),
                "longest_delay": Algorithm(
                    "longest_delay",
                    "single_channel",
                    benchmark.family,
                    lambda b: solver.schedule_priority(convert(b), "longest_delay"),
                    "Largest immediately unlocked compute segment.",
                ),
                "lrpt": Algorithm(
                    "lrpt",
                    "single_channel",
                    benchmark.family,
                    lambda b: solver.schedule_priority(convert(b), "lrpt"),
                    "Longest residual path including current communication.",
                ),
                "longest_tail": Algorithm(
                    "longest_tail",
                    "single_channel",
                    benchmark.family,
                    lambda b: solver.schedule_longest_tail(convert(b)),
                    "Longest residual downstream tail excluding current communication.",
                ),
                "rollout2": Algorithm(
                    "rollout2",
                    "single_channel",
                    benchmark.family,
                    lambda b: solver.schedule_rollout(
                        convert(b), top_k=2, candidate_mode="longest_tail"
                    ),
                    "Top-2 Longest-tail shortlist with one-event rollout and Longest-tail completion.",
                ),
                "rollout4": Algorithm(
                    "rollout4",
                    "single_channel",
                    benchmark.family,
                    lambda b: solver.schedule_rollout(
                        convert(b), top_k=4, candidate_mode="longest_tail", depth=1
                    ),
                    "Top-4 Longest-tail shortlist with depth-1 event rollout.",
                ),
                "rollout2_depth2": Algorithm(
                    "rollout2_depth2",
                    "single_channel",
                    benchmark.family,
                    lambda b: solver.schedule_rollout(
                        convert(b), top_k=2, candidate_mode="longest_tail", depth=2
                    ),
                    "Top-2 Longest-tail shortlist with depth-2 event rollout.",
                ),
                "beam8": Algorithm(
                    "beam8",
                    "single_channel",
                    benchmark.family,
                    lambda b: solver.beam_search(convert(b), width=8),
                    "Experimental upper bound/comparison only; not a deployment candidate, no robustness claim, counterexamples not exhausted.",
                    development_status="experimental",
                ),
                "beam32": Algorithm(
                    "beam32",
                    "single_channel",
                    benchmark.family,
                    lambda b: solver.beam_search(convert(b), width=32),
                    "Experimental upper bound/comparison only; not a deployment candidate, no robustness claim, counterexamples not exhausted.",
                    development_status="experimental",
                ),
                "exact": Algorithm(
                    "exact",
                    "single_channel",
                    benchmark.family,
                    lambda b: solver.exact_oracle(convert(b)),
                    "Exact compact chain-frontier Oracle for small instances.",
                    exact=True,
                ),
            }
        )
    if benchmark.family == "complex_chain":
        from single_channel.complex_chain.preemptive import solver
    else:
        raise ValueError(f"unsupported preemptive family: {benchmark.family}")

    convert = to_internal_dag
    return _active_v2(
        {
            "fifo": Algorithm(
                "fifo",
                "single_channel",
                benchmark.family,
                lambda b: solver.schedule_priority(convert(b), "fifo"),
                "FIFO work-conserving priority.",
            ),
            "spt": Algorithm(
                "spt",
                "single_channel",
                benchmark.family,
                lambda b: solver.schedule_priority(convert(b), "spt"),
                "Shortest remaining communication first.",
            ),
            "lpt": Algorithm(
                "lpt",
                "single_channel",
                benchmark.family,
                lambda b: solver.schedule_priority(convert(b), "lpt"),
                "Longest remaining communication first.",
            ),
            "longest_delay": Algorithm(
                "longest_delay",
                "single_channel",
                benchmark.family,
                lambda b: solver.schedule_priority(convert(b), "longest_delay"),
                "Longest immediately released compute delay, then residual tail.",
            ),
            "release_gain": Algorithm(
                "release_gain",
                "single_channel",
                benchmark.family,
                lambda b: solver.schedule_priority(convert(b), "release_gain"),
                "Research baseline: total immediately released ready work; observed weaker than Longest-tail.",
            ),
            "downstream_demand": Algorithm(
                "downstream_demand",
                "single_channel",
                benchmark.family,
                lambda b: solver.schedule_priority(convert(b), "downstream_demand"),
                "Deployment candidate: observed mean improves over Longest-tail, while observed worst case degrades.",
            ),
            "lrpt": Algorithm(
                "lrpt",
                "single_channel",
                benchmark.family,
                lambda b: solver.schedule_priority(convert(b), "lrpt"),
                "Longest remaining path including current communication.",
            ),
            "longest_tail": Algorithm(
                "longest_tail",
                "single_channel",
                benchmark.family,
                lambda b: solver.schedule_longest_tail(to_internal_dag(b)),
                "Event-driven residual longest-tail with communication pause/resume.",
            ),
            "integrated_v0": Algorithm(
                "integrated_v0",
                "single_channel",
                benchmark.family,
                lambda b: __import__(
                    "single_channel.complex_chain.preemptive.interface",
                    fromlist=["solve"],
                ).solve(convert(b), "integrated_v0"),
                "Frozen Stage 4g baseline: online residual Longest Tail.",
            ),
            "join_aware": Algorithm(
                "join_aware",
                "single_channel",
                benchmark.family,
                lambda b: solver.schedule_priority(convert(b), "join_aware"),
                "Direct last-blocker gain, then residual longest-tail.",
            ),
            "rollout2": Algorithm(
                "rollout2",
                "single_channel",
                benchmark.family,
                lambda b: solver.schedule_rollout(convert(b), top_k=2),
                "Top-2 depth-1 Longest-tail rollout with baseline safeguard.",
            ),
            "rollout2_depth2": Algorithm(
                "rollout2_depth2",
                "single_channel",
                benchmark.family,
                lambda b: solver.schedule_rollout(convert(b), top_k=2, depth=2),
                "Top-2 depth-2 Longest-tail rollout.",
            ),
            "rollout4_depth2": Algorithm(
                "rollout4_depth2",
                "single_channel",
                benchmark.family,
                lambda b: solver.schedule_rollout(convert(b), top_k=4, depth=2),
                "Top-4 depth-2 Longest-tail rollout.",
            ),
            "join_rollout2": Algorithm(
                "join_rollout2",
                "single_channel",
                benchmark.family,
                lambda b: solver.schedule_rollout(convert(b), top_k=2, candidate_mode="hybrid"),
                "Top-2 rollout with tail and last-join-blocker candidates.",
            ),
            "beam8": Algorithm(
                "beam8",
                "single_channel",
                benchmark.family,
                lambda b: solver.beam_search(convert(b), width=8),
                "Experimental upper bound/comparison only; not a deployment candidate, no robustness claim, counterexamples not exhausted.",
                development_status="experimental",
            ),
            "beam32": Algorithm(
                "beam32",
                "single_channel",
                benchmark.family,
                lambda b: solver.beam_search(convert(b), width=32),
                "Experimental upper bound/comparison only; not a deployment candidate, no robustness claim, counterexamples not exhausted.",
                development_status="experimental",
            ),
            "exact": Algorithm(
                "exact",
                "single_channel",
                benchmark.family,
                lambda b: solver.exact_oracle(convert(b)),
                "Normalized branch-and-bound Exact for small general DAGs.",
                exact=True,
            ),
            "exact_uncompressed": Algorithm(
                "exact_uncompressed",
                "single_channel",
                benchmark.family,
                lambda b: solver.exact_oracle_uncompressed(convert(b)),
                "Audit Exact retaining absolute event-state fields.",
                exact=True,
            ),
        }
    )


def _active_v2(algorithms: dict[str, Algorithm]) -> dict[str, Algorithm]:
    return {
        name: replace(
            algorithm,
            semantics="communication_resume",
            supports_wait=False,
            development_status=(
                "active"
                if algorithm.development_status == "maintenance"
                else algorithm.development_status
            ),
        )
        for name, algorithm in algorithms.items()
    }


def _active_nonpreemptive(algorithms: dict[str, Algorithm]) -> dict[str, Algorithm]:
    return {
        name: replace(
            algorithm,
            semantics="communication_nonpreemptive",
            development_status=(
                "active"
                if algorithm.development_status == "maintenance"
                else algorithm.development_status
            ),
        )
        for name, algorithm in algorithms.items()
    }


def algorithms_for(benchmark: Benchmark) -> dict[str, Algorithm]:
    if benchmark.semantics.is_preemptive:
        return _preemptive_registry(benchmark)
    if benchmark.scenario == "muti_channel":
        return _active_nonpreemptive(_muti_registry())
    if benchmark.family == "parallel_chain":
        return _active_nonpreemptive(_parallel_registry())
    if benchmark.family == "complex_chain":
        return _active_nonpreemptive(_complex_registry())
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
