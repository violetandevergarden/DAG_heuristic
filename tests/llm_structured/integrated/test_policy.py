from __future__ import annotations

import pytest

from benchmark import load_benchmark
from core.conversion import to_dag, to_muti_resourse
from llm_structured.preemptive.integrated import (
    IntegratedConfig,
    integrated_v0,
    schedule_multi,
    schedule_single,
)
from muti_channel.preemptive import solver as multi_solver
from single_channel.complex_chain.preemptive import solver as single_solver


def test_single_integrated_v0_is_trace_equivalent() -> None:
    benchmark = load_benchmark(
        "benchmark/single_channel/complex_chain/preemptive/adversarial/preemption_unlock.json"
    )
    dag = to_dag(benchmark)
    expected = single_solver.schedule_longest_tail(dag)
    actual = schedule_single(dag, integrated_v0("single"))
    assert actual.schedule.makespan == expected.makespan
    assert actual.schedule.trace == expected.trace
    assert actual.component_calls == (("packing", 0), ("rollout", 0), ("barrier", 0))


@pytest.mark.parametrize(
    "path",
    [
        "benchmark/single_channel/parallel_chain/preemptive/adversarial/pm_fixed_beam_counterexample.json",
        "benchmark/single_channel/complex_chain/preemptive/adversarial/pm_random_join_40.json",
        "benchmark/single_channel/complex_chain/preemptive/random/pm_stage2_layered_002.json",
    ],
)
def test_single_integrated_v0_uses_exclusive_tail(path: str) -> None:
    dag = to_dag(load_benchmark(path))
    expected = single_solver.schedule_longest_tail(dag)
    actual = schedule_single(dag, integrated_v0("single")).schedule
    assert actual.trace == expected.trace


def test_multi_integrated_v0_is_trace_equivalent_and_maximal() -> None:
    benchmark = load_benchmark(
        "benchmark/muti_channel/preemptive/adversarial/pm_stage3_maximal_not_maximum.json"
    )
    instance = to_muti_resourse(benchmark)
    expected = multi_solver.schedule_pack(instance.dag, instance.resources)
    actual = schedule_multi(
        instance.dag, instance.resources, integrated_v0("fixed_multi")
    )
    assert actual.schedule.makespan == expected.makespan
    assert actual.schedule.trace == expected.trace
    assert all(record.final_action for record in actual.decisions)


def test_large_graph_threshold_disables_detailed_audit_without_changing_trace() -> None:
    dag = to_dag(
        load_benchmark(
            "benchmark/single_channel/complex_chain/preemptive/adversarial/preemption_unlock.json"
        )
    )
    config = IntegratedConfig(
        name="threshold_test", resource_mode="single", large_graph_safe_threshold=0
    )
    actual = schedule_single(dag, config)
    assert actual.degraded_to_safe
    assert not actual.decisions
    assert actual.schedule.trace == single_solver.schedule_longest_tail(dag).trace
