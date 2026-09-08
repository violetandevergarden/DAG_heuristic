from dataclasses import replace
from pathlib import Path

import pytest

from benchmark import load_benchmark
from core.dag import DAG, Task
from muti_channel.preemptive.solver import (
    MultiAction,
    PreeMultiModel,
    exact_oracle,
    exact_oracle_uncompressed,
    greedy_fill_from_task_scores,
    remaining_lower_bound,
    rollout_sets,
    schedule_pack,
    schedule_set_policy,
    score_sets,
    score_tasks,
    select_best_scored_set,
    uncompressed_state_key,
)
from muti_channel.preemptive.trace import assert_multi_resource_trace
from registry import algorithms_for

ROOT = Path(__file__).resolve().parents[3]


def test_preemptive_multi_channel_has_an_explicit_family_entry() -> None:
    dag = DAG('multi_preemptive_smoke', (Task('left', 'comm', 2), Task('right', 'comm', 3)), context=(('category', 'test'),))
    resources = {
        "left": frozenset({"left"}),
        "right": frozenset({"right"}),
    }

    assert exact_oracle(dag, resources).makespan == 3


def test_stage3_registry_exposes_one_stable_surface() -> None:
    benchmark = load_benchmark(
        ROOT
        / "benchmark/muti_channel/preemptive/adversarial/pm_stage3_atomic_acquire.json"
    )
    algorithms = algorithms_for(benchmark)
    assert {
        "longest_tail_pack",
        "resource_downstream_pack",
        "union_downstream_set",
        "rollout_sets2d2",
        "exact",
        "exact_uncompressed",
    } <= set(algorithms)
    assert "stable deployment baseline" in algorithms[
        "longest_tail_pack"
    ].description.lower()
    assert "mean and worst" in algorithms["resource_downstream_pack"].description
    assert algorithms["exact"].exact


def _multi_instance():
    dag = DAG('multi_overlap', (Task('a', 'comm', 4), Task('a_tail', 'compute', 3, ('a',)), Task('b', 'comm', 4), Task('b_tail', 'compute', 3, ('b',)), Task('c', 'comm', 2)), context=(('category', 'test'),))
    resources = {
        "a": frozenset({"left"}),
        "b": frozenset({"right"}),
        "c": frozenset({"left", "right"}),
    }
    return dag, resources


def test_multi_resource_model_runs_disjoint_flows_concurrently() -> None:
    dag, resources = _multi_instance()
    model = PreeMultiModel(dag, resources)
    actions = model.maximal_actions(model.initial_state())

    assert {action.communications for action in actions} == {("a", "b"), ("c",)}
    optimum = exact_oracle(dag, resources)
    assert optimum.makespan == 7
    assert schedule_pack(dag, resources).makespan >= optimum.makespan
    assert rollout_sets(dag, resources).makespan >= optimum.makespan


def test_maximal_set_oracle_matches_single_resource_serial_work() -> None:
    dag = DAG('shared', (Task('a', 'comm', 2), Task('b', 'comm', 3)), context=(('category', 'test'),))
    resources = {"a": frozenset({"r"}), "b": frozenset({"r"})}
    assert exact_oracle(dag, resources).makespan == 5


def test_forced_idle_is_simulator_owned_and_not_a_decision() -> None:
    dag = DAG('forced_idle', (Task('release', 'compute', 2), Task('flow', 'comm', 1, ('release',))), context=(('category', 'test'),))
    resources = {"flow": frozenset({"r"})}
    result = schedule_pack(dag, resources)
    assert result.trace is not None
    assert result.decision_count == 1
    assert tuple((item.start, item.end) for item in result.trace.forced_idle) == ((0, 2),)
    assert all(decision.action.communications for decision in result.trace.decisions)
    with pytest.raises(AssertionError, match="timeline"):
        assert_multi_resource_trace(
            dag, resources, replace(result.trace, forced_idle=())
        )


def test_atomic_multi_resource_pause_release_and_resume() -> None:
    dag = DAG('atomic_resume', (Task('release', 'compute', 1), Task('wide', 'comm', 3), Task('urgent', 'comm', 1, ('release',))), context=(('category', 'test'),))
    resources = {
        "wide": frozenset({"r0", "r1"}),
        "urgent": frozenset({"r0"}),
    }
    model = PreeMultiModel(dag, resources)
    trace = model.run(
        (MultiAction(("wide",)), MultiAction(("urgent",)), MultiAction(("wide",)))
    )
    assert_multi_resource_trace(dag, resources, trace)
    wide_resources = [item for item in trace.resource_intervals if item.task_id == "wide"]
    assert {(item.start, item.end, item.resource_id) for item in wide_resources} == {
        (0, 1, "r0"),
        (0, 1, "r1"),
        (2, 4, "r0"),
        (2, 4, "r1"),
    }
    with pytest.raises(AssertionError, match="complete fixed resource acquisition"):
        assert_multi_resource_trace(
            dag,
            resources,
            replace(
                trace,
                resource_intervals=tuple(
                    item
                    for item in trace.resource_intervals
                    if not (item.task_id == "wide" and item.resource_id == "r1")
                ),
            ),
        )


def test_same_time_completion_batch_produces_one_followup_decision() -> None:
    dag = DAG('same_time', (Task('release', 'compute', 2), Task('a', 'comm', 2), Task('b', 'comm', 2), Task('c', 'comm', 1, ('release', 'a', 'b'))), context=(('category', 'test'),))
    resources = {
        "a": frozenset({"r0"}),
        "b": frozenset({"r1"}),
        "c": frozenset({"r0", "r1"}),
    }
    model = PreeMultiModel(dag, resources)
    trace = model.run((MultiAction(("a", "b")), MultiAction(("c",))))
    assert tuple(item.start for item in trace.decisions) == (0, 2)
    assert sum(item.time == 2 and item.kind.endswith("completed") for item in trace.events) == 3


def test_exact_contract_bound_and_uncompressed_audit_agree() -> None:
    dag, resources = _multi_instance()
    normalized = exact_oracle(dag, resources)
    audit = exact_oracle_uncompressed(dag, resources)
    model = PreeMultiModel(dag, resources)
    assert normalized.status == audit.status == "optimal"
    assert normalized.makespan == audit.makespan
    assert normalized.lower_bound == remaining_lower_bound(model, model.initial_state())
    assert normalized.lower_bound <= normalized.makespan
    limited = exact_oracle(dag, resources, max_states=1)
    assert limited.status == "feasible"
    assert limited.termination_reason == "state_limit"


def test_uncompressed_key_reads_real_allocation_fields_and_stable_model_rejects_them() -> None:
    dag, resources = _multi_instance()
    model = PreeMultiModel(dag, resources)
    state = model.initial_state()
    occupied = replace(
        state,
        active_allocations=("a",),
        resource_owners=(("left", "a"),),
    )
    assert uncompressed_state_key(occupied) != uncompressed_state_key(state)
    with pytest.raises(AssertionError, match="stable decision state"):
        model.step(occupied, MultiAction(("a", "b")))


def test_task_scoring_and_set_construction_are_independent_axes() -> None:
    dag, resources = _multi_instance()
    model = PreeMultiModel(dag, resources)
    state = model.initial_state()
    legal = model.maximal_actions(state)

    lt_scores = score_tasks(model, state, "longest_tail")
    assert greedy_fill_from_task_scores(model, state, lt_scores) == MultiAction(("a", "b"))

    prefer_wide = {task_id: (task_id != "c", task_id) for task_id in model.eligible(state)}
    assert greedy_fill_from_task_scores(model, state, prefer_wide) == MultiAction(("c",))

    set_scores = score_sets(model, state, legal, "union_downstream")
    assert set(set_scores) == set(legal)
    assert select_best_scored_set(set_scores) in legal


def test_resource_and_union_downstream_candidates_remain_feasible() -> None:
    dag, resources = _multi_instance()
    optimum = exact_oracle(dag, resources).makespan
    resource = schedule_pack(dag, resources, "resource_downstream")
    union = schedule_set_policy(dag, resources)
    rollout = rollout_sets(dag, resources, depth=2, node_budget=100)
    assert resource.makespan >= optimum
    assert union.makespan >= optimum
    assert rollout.makespan >= optimum
    assert rollout.fallback_count == 0
    limited = rollout_sets(dag, resources, depth=2, node_budget=1)
    baseline = schedule_pack(dag, resources)
    assert limited.makespan == baseline.makespan
    assert limited.fallback_count > 0
    assert limited.completed_search is False
    assert limited.fallback_reason == "expanded_node_budget"
