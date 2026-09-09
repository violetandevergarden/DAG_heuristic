from dataclasses import replace

from core.dag import DAG, Task
from core.execution.preemptive import Action, PreeSingleModel
from core.trace.pree_single import assert_preemptive_trace
from llm_structured.local_frontier import (
    LocalFrontierConfig,
    build_local_region,
    candidate_pair,
    diagnostic_config,
    schedule_local_frontier,
)
from llm_structured.local_frontier.frontier import states_merged
from single_channel.complex_chain.preemptive.solver import schedule_longest_tail


def _counterexample() -> DAG:
    return DAG('local_frontier_counterexample', (Task('a1', 'comm', 2), Task('a_gap', 'compute', 3, ('a1',)), Task('a2', 'comm', 1, ('a_gap',)), Task('a_tail', 'compute', 1, ('a2',)), Task('b1', 'comm', 1), Task('b_gap', 'compute', 2, ('b1',)), Task('b2', 'comm', 2, ('b_gap',)), Task('b_tail', 'compute', 1, ('b2',))), context=(('category', 'adversarial'),))


def test_diagnostic_is_trace_identical_to_lt() -> None:
    dag = _counterexample()
    baseline = schedule_longest_tail(dag)
    actual = schedule_local_frontier(dag, diagnostic_config())
    assert actual.schedule.trace == baseline.trace
    assert actual.changed_actions == 0
    assert_preemptive_trace(dag, actual.schedule.trace)


def test_complete_local_search_repairs_fixed_lt_counterexample() -> None:
    config = LocalFrontierConfig(
        adoption_mode="risk_controlled", decision_depth=8,
        max_expansions=1000, per_decision_time_limit_s=1,
        total_time_limit_s=5,
    )
    result = schedule_local_frontier(_counterexample(), config)
    assert result.schedule.makespan == 8
    assert result.changed_actions == 1
    assert result.complete_evaluations == 1


def test_incomplete_branch_falls_back_to_lt() -> None:
    dag = _counterexample()
    config = LocalFrontierConfig(
        adoption_mode="risk_controlled", max_expansions=1,
        per_decision_time_limit_s=1,
    )
    result = schedule_local_frontier(dag, config)
    assert result.schedule.trace == schedule_longest_tail(dag).trace
    assert result.fallback_count > 0


def test_region_is_symmetric_and_reports_truncation() -> None:
    model = PreeSingleModel(_counterexample())
    state = model.initial_state()
    pair = candidate_pair(model, state)
    assert pair.challenger is not None
    left = build_local_region(model, state, pair.baseline, pair.challenger, max_nodes=64)
    right = build_local_region(model, state, pair.challenger, pair.baseline, max_nodes=64)
    assert left.task_ids == right.task_ids
    limited = build_local_region(model, state, pair.baseline, pair.challenger, max_nodes=2)
    assert not limited.complete
    assert limited.truncation_reason == "local_node_limit"


def test_region_stops_at_first_common_join_and_excludes_shared_suffix() -> None:
    dag = DAG('join', (Task('a', 'comm', 1), Task('b', 'comm', 1), Task('join', 'compute', 1, ('a', 'b')), Task('shared', 'comm', 1, ('join',)), Task('tail', 'compute', 1, ('shared',))), context=(('category', 'test'),))
    model = PreeSingleModel(dag)
    region = build_local_region(model, model.initial_state(), "a", "b", max_nodes=10)
    assert region.boundary_ids == ("join",)
    assert "join" in region.task_ids
    assert "shared" not in region.task_ids
    assert "tail" not in region.task_ids


def test_same_reached_node_does_not_imply_state_merge() -> None:
    model = PreeSingleModel(_counterexample())
    state = model.initial_state()
    left = model.step(state, Action.run("a1")).after
    right = model.step(state, Action.run("b1")).after
    assert not states_merged(left, right)
    altered = replace(left, time=left.time + 10)
    # Normalization intentionally removes only a uniform time shift.
    assert states_merged(left, altered)


def test_single_choice_and_large_graph_guard_do_not_search() -> None:
    one = DAG('one', (Task('c', 'comm', 1),), context=(('category', 'test'),))
    result = schedule_local_frontier(one)
    assert result.evaluations == 0
    guarded = schedule_local_frontier(
        _counterexample(), LocalFrontierConfig(max_graph_tasks=1)
    )
    assert guarded.schedule.trace == schedule_longest_tail(_counterexample()).trace
    assert all(item.fallback_reason == "graph_size_limit" for item in guarded.decisions)


def test_zero_depth_and_zero_expansion_are_safe() -> None:
    dag = _counterexample()
    config = LocalFrontierConfig(
        decision_depth=0, max_expansions=0,
        adoption_mode="risk_controlled",
    )
    result = schedule_local_frontier(dag, config)
    assert result.schedule.trace == schedule_longest_tail(dag).trace
