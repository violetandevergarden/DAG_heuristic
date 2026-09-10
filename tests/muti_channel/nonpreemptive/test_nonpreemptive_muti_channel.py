from __future__ import annotations

import random
from pathlib import Path

from benchmark_generate.cases import multi_resource_motifs, random_multi_resource_instance
from muti_channel.nonpreemptive.solver import (
    NonPreeMultiModel,
    ResourceAction,
    exact_oracle,
    schedule_greedy,
    schedule_rollout,
)
from benchmark import load_benchmark
from core.conversion import to_muti_resourse
from core.oracle.nonpree_multi import (
    exact_oracle as core_exact_oracle,
    exact_oracle_uncompressed,
)


ROOT = Path(__file__).resolve().parents[3]


def test_disjoint_routes_run_concurrently_without_preemption() -> None:
    instance = multi_resource_motifs()[0]
    result = exact_oracle(instance)

    assert result.makespan == 7
    assert result.actions[0].starts == ("left", "right")
    comms = [interval for interval in result.intervals if interval.kind == "comm"]
    assert {(item.task_id, item.start, item.end) for item in comms} == {
        ("left", 0, 4),
        ("right", 0, 4),
    }


def test_shared_route_serializes_whole_flows() -> None:
    result = exact_oracle(multi_resource_motifs()[1])
    comms = sorted(
        (interval for interval in result.intervals if interval.kind == "comm"),
        key=lambda item: item.start,
    )

    assert result.makespan == 11
    assert comms[0].end <= comms[1].start


def test_nonmaximal_start_and_wait_can_beat_every_maximal_start() -> None:
    instance = multi_resource_motifs()[2]
    optional = exact_oracle(instance, mode="optional_idle")
    work_conserving = exact_oracle(instance, mode="work_conserving")

    assert optional.makespan == 8
    assert work_conserving.makespan == 12
    assert optional.actions[0].starts == ("a",)
    assert ("a",) not in NonPreeMultiModel(
        instance
    ).start_subsets(
        NonPreeMultiModel(instance).initial_state(),
        maximal_only=True,
    )


def test_compressed_and_uncompressed_exact_audit_match() -> None:
    instance = multi_resource_motifs()[2]
    compressed = core_exact_oracle(instance, mode="optional_idle")
    uncompressed = exact_oracle_uncompressed(instance, mode="optional_idle")

    assert compressed.status == uncompressed.status == "optimal"
    assert compressed.makespan == uncompressed.makespan == 8
    assert compressed.exact_stats is not None
    assert uncompressed.exact_stats is not None
    assert compressed.exact_stats.lower_bounds == uncompressed.exact_stats.lower_bounds


def test_active_flow_keeps_route_reserved_at_intermediate_event() -> None:
    instance = multi_resource_motifs()[3]
    model = NonPreeMultiModel(instance)
    state = model.initial_state()
    state = model.step(state, ResourceAction.start(("a", "b"))).after

    assert state.time == 1
    assert model.active_flows(state) == ("a",)
    assert model.ready_flows(state) == ("c",)
    assert not model.compatible(state, ("c",))
    assert model.legal_actions(state, "optional_idle") == (ResourceAction.wait(),)


def test_optional_set_rollout_repairs_nonmaximal_motif() -> None:
    instance = multi_resource_motifs()[2]

    assert schedule_greedy(instance).makespan == 12
    assert schedule_rollout(
        instance, top_k=2, optional_actions=False
    ).makespan == 12
    assert schedule_rollout(
        instance, top_k=2, optional_actions=True
    ).makespan == 8


def test_real_route_snapshots_preserve_resource_conflicts() -> None:
    root = ROOT / "benchmark/muti_channel/nonpreemptive/real"
    single = to_muti_resourse(load_benchmark(root / "manual_route_single_switch_np.json"))
    two_rack = to_muti_resourse(load_benchmark(root / "manual_route_two_rack_np.json"))
    four_rack = to_muti_resourse(load_benchmark(root / "manual_route_four_rack_core_np.json"))

    assert not (single.resources["f1"] & single.resources["f2"])
    assert "link:8->9" in two_rack.resources["f1"] & two_rack.resources["f2"]
    assert "link:8->12" in four_rack.resources["f1"] & four_rack.resources["f2"]
    assert not (four_rack.resources["f1"] & four_rack.resources["f3"])


def test_enhanced_schedules_keep_dynamic_incumbent_and_exact_lower_bound() -> None:
    rng = random.Random(260819)
    for index in range(5):
        instance = random_multi_resource_instance(rng, index)
        optimum = exact_oracle(instance, max_states=300_000).makespan
        dynamic = schedule_greedy(instance).makespan
        for result in (
            schedule_greedy(instance, "resource_tail"),
            schedule_greedy(instance, "bottleneck_first"),
            schedule_rollout(instance, top_k=2, optional_actions=False),
            schedule_rollout(instance, top_k=2, optional_actions=True),
        ):
            assert result.makespan >= optimum
        assert schedule_rollout(
            instance, top_k=2, optional_actions=True
        ).makespan <= dynamic
