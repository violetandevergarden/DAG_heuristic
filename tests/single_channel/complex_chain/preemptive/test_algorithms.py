from __future__ import annotations

import random

import pytest

from benchmark import benchmark_from_dict
from benchmark_generate.cases import stage2_structural_adversarial_cases
from core.dag import DAG, Task
from core.execution.preemptive import Action, PreeSingleModel
from core.oracle.pree_single import (
    exact_oracle,
    exact_oracle_uncompressed,
    remaining_lower_bound,
)
from core.trace.pree_single import assert_preemptive_trace
from registry import algorithms_for
from llm_structured.preemptive.barrier import barrier_urgency
from single_channel.complex_chain.preemptive.interface import validate_complex_chain
from single_channel.complex_chain.preemptive.solver import (
    beam_search,
    downstream_communication_demand,
    schedule_longest_tail,
    schedule_priority,
    schedule_rollout,
    unique_downstream_work,
)
from tests.oracles.preemptive.tiny_oracle import tiny_tick_optimum


def _first_communication(result) -> str:
    return next(span.task_id for span in result.trace.intervals if span.kind == "comm")


def _parallel_counterexample() -> DAG:
    return DAG('tail_counterexample', (Task('a1', 'comm', 2), Task('a_gap', 'compute', 3, ('a1',)), Task('a2', 'comm', 1, ('a_gap',)), Task('a_tail', 'compute', 1, ('a2',)), Task('b1', 'comm', 1), Task('b_gap', 'compute', 2, ('b1',)), Task('b2', 'comm', 2, ('b_gap',)), Task('b_tail', 'compute', 1, ('b2',))), context=(('category', 'test'),))


def test_stage2_searches_are_feasible_and_keep_baseline_incumbent() -> None:
    dag = _parallel_counterexample()
    optimum = exact_oracle(dag)
    baseline = schedule_longest_tail(dag)

    assert optimum.status == "optimal"
    assert optimum.makespan == 8
    assert baseline.makespan == 9
    assert schedule_rollout(dag, top_k=2).makespan == 8
    assert schedule_rollout(dag, top_k=2, depth=2).makespan <= baseline.makespan
    assert beam_search(dag, width=8).makespan == 8


def test_raw_general_dag_contract_accepts_same_kind_edges_and_components() -> None:
    raw = DAG('raw', (Task('c0', 'compute', 1), Task('c1', 'compute', 1, ('c0',)), Task('x', 'comm', 1)), context=(('category', 'test'),))
    validate_complex_chain(raw)
    assert exact_oracle(raw).status == "optimal"

    with pytest.raises(ValueError, match="communication work must be positive"):
        validate_complex_chain(DAG('zero', (Task('z', 'comm', 0),), context=(('category', 'test'),)))


def test_fork_zero_compute_closure_and_preemption_are_atomic() -> None:
    dag = DAG('fork_atomic', (Task('root', 'comm', 1), Task('slow', 'compute', 3, ('root',)), Task('zero', 'compute', 0, ('root',)), Task('released', 'comm', 1, ('zero',))), context=(('category', 'test'),))
    model = PreeSingleModel(dag)
    transition = model.step(model.initial_state(), Action.run("root"))
    assert model.active_computes(transition.after) == ("slow",)
    assert model.eligible_communications(transition.after) == ("released",)
    assert [(event.kind, event.task_id) for event in transition.events[-4:]] == [
        ("compute_completed", "zero"),
        ("communication_completed", "root"),
        ("compute_started", "slow"),
        ("compute_started", "zero"),
    ]

    preempt = DAG('pause_at_compute', (Task('release', 'compute', 2), Task('long', 'comm', 4), Task('new', 'comm', 1, ('release',))), context=(('category', 'test'),))
    model = PreeSingleModel(preempt)
    transition = model.step(model.initial_state(), Action.run("long"))
    assert transition.after.time == 2
    assert model.task_runtime(transition.after, "long").remaining == 2
    assert model.eligible_communications(transition.after) == ("long", "new")


def test_join_requires_all_simultaneous_predecessors() -> None:
    dag = DAG('simultaneous_join', (Task('left', 'compute', 2), Task('right', 'compute', 2), Task('barrier', 'comm', 1, ('left', 'right'))), context=(('category', 'test'),))
    model = PreeSingleModel(dag)
    transition = model.step(model.initial_state(), Action.wait())
    completed = [
        event.task_id for event in transition.events if event.kind == "compute_completed"
    ]
    assert completed == ["left", "right"]
    assert model.eligible_communications(transition.after) == ("barrier",)


def test_priority_definitions_choose_distinct_first_actions() -> None:
    dag = DAG('three_scores', (Task('release', 'comm', 1), Task('release_left', 'compute', 3, ('release',)), Task('release_right', 'compute', 3, ('release',)), Task('tail', 'comm', 1), Task('tail_compute', 'compute', 1, ('tail',)), Task('tail_second', 'comm', 8, ('tail_compute',)), Task('tail_sink', 'compute', 1, ('tail_second',)), Task('inclusive', 'comm', 12), Task('inclusive_compute', 'compute', 2, ('inclusive',))), context=(('category', 'test'),))
    assert _first_communication(schedule_priority(dag, "longest_delay")) == "release"
    assert _first_communication(schedule_priority(dag, "longest_tail")) == "tail"
    assert _first_communication(schedule_priority(dag, "lrpt")) == "inclusive"


def test_longest_delay_is_not_total_release_gain() -> None:
    dag = DAG('delay_vs_release_gain', (Task('breadth', 'comm', 1), Task('breadth_a', 'compute', 3, ('breadth',)), Task('breadth_b', 'compute', 3, ('breadth',)), Task('delay', 'comm', 1), Task('delay_compute', 'compute', 5, ('delay',))), context=(('category', 'test'),))
    assert _first_communication(schedule_priority(dag, "longest_delay")) == "delay"
    assert _first_communication(schedule_priority(dag, "release_gain")) == "breadth"


def test_structural_features_deduplicate_shared_nodes_and_score_barriers() -> None:
    dag = DAG('shared_feature', (Task('candidate', 'comm', 1), Task('left', 'compute', 1, ('candidate',)), Task('right', 'compute', 1, ('candidate',)), Task('shared_comm', 'comm', 4, ('left', 'right')), Task('shared_sink', 'compute', 2, ('shared_comm',)), Task('other', 'comm', 1)), context=(('category', 'test'),))
    model = PreeSingleModel(dag)
    state = model.initial_state()
    assert downstream_communication_demand(model, state, "candidate") == 4
    assert unique_downstream_work(model, state, "candidate") == 8
    assert barrier_urgency(model, state, "candidate") > 0


def test_fifo_retains_first_eligible_time_across_pause() -> None:
    dag = DAG('fifo_arrival', (Task('release', 'compute', 1), Task('z_old', 'comm', 3), Task('a_new', 'comm', 1, ('release',))), context=(('category', 'test'),))
    result = schedule_priority(dag, "fifo")
    comms = [span.task_id for span in result.trace.intervals if span.kind == "comm"]
    assert comms[:2] == ["z_old", "z_old"]


def test_direct_join_feature_is_independently_observable() -> None:
    dag = DAG('join_feature', (Task('done', 'compute', 0), Task('join_candidate', 'comm', 1), Task('barrier_tail', 'compute', 6, ('done', 'join_candidate')), Task('path_candidate', 'comm', 1), Task('path_tail', 'compute', 8, ('path_candidate',))), context=(('category', 'test'),))
    assert _first_communication(schedule_priority(dag, "longest_tail")) == "path_candidate"
    assert _first_communication(schedule_priority(dag, "join_aware")) == "join_candidate"


def _random_tiny_general_dag(rng: random.Random, index: int) -> DAG:
    tasks: list[Task] = []
    for node in range(rng.randint(2, 6)):
        kind = "comm" if rng.random() < 0.55 else "compute"
        duration = rng.randint(1, 3) if kind == "comm" else rng.randint(0, 3)
        parents = tuple(
            tasks[parent].task_id for parent in range(node) if rng.random() < 0.3
        )
        tasks.append(Task(f"t{node}", kind, duration, parents))
    if not any(task.kind == "comm" for task in tasks):
        tasks[0] = Task(tasks[0].task_id, "comm", max(1, tasks[0].duration))
    return DAG(f'stage2_tiny_{index}', tuple(tasks), context=(('category', 'test'),))


def test_normalized_audit_and_tick_oracles_match_on_fixed_suite() -> None:
    rng = random.Random(260816)
    for index in range(100):
        dag = _random_tiny_general_dag(rng, index)
        normalized = exact_oracle(dag)
        audit = exact_oracle_uncompressed(dag)
        tick = tiny_tick_optimum(dag)
        assert normalized.status == audit.status == "optimal"
        assert normalized.makespan == audit.makespan == tick
        assert normalized.lower_bound <= tick


def test_exact_budget_failure_is_not_reported_as_optimal() -> None:
    result = exact_oracle(_parallel_counterexample(), max_states=1)
    assert result.status == "feasible"
    assert result.termination_reason == "state_limit"
    assert result.lower_bound <= result.makespan


def test_exact_bound_and_search_component_ablation_preserve_optimum() -> None:
    dag = _parallel_counterexample()
    expected = tiny_tick_optimum(dag)
    for mode in ("none", "communication", "path", "combined"):
        assert exact_oracle(dag, bound_mode=mode).makespan == expected
    assert exact_oracle(dag, use_memo=False).makespan == expected
    assert exact_oracle(dag, use_incumbent=False).makespan == expected


def test_rollout_and_beam_report_budget_fallbacks() -> None:
    dag = _parallel_counterexample()
    rollout = schedule_rollout(dag, depth=3, max_expansions=1)
    beam = beam_search(dag, width=8, max_expansions=1)
    baseline = schedule_longest_tail(dag)
    assert rollout.fallback_count == 1
    assert rollout.termination_reason == "node_expansion_limit"
    assert rollout.makespan <= baseline.makespan
    assert beam.fallback_count == 1
    assert beam.termination_reason == "node_expansion_limit"
    assert beam.makespan <= baseline.makespan


def test_depth_two_closes_fixed_stage2_rollout_counterexample() -> None:
    dag = next(
        item
        for item in stage2_structural_adversarial_cases()
        if item.name == "stage2_rollout_depth"
    )
    assert exact_oracle(dag).makespan == 21
    assert schedule_rollout(dag, top_k=2, depth=1).makespan == 22
    assert schedule_rollout(dag, top_k=4, depth=1).makespan == 22
    assert schedule_rollout(dag, top_k=2, depth=2).makespan == 21


def test_rollout_normalized_memo_preserves_result_and_hits_transposition() -> None:
    dag = DAG('rollout_transposition', tuple((Task(f'c{index}', 'comm', index + 1) for index in range(4))), context=(('category', 'test'),))
    memoized = schedule_rollout(dag, top_k=4, depth=3)
    tree = schedule_rollout(dag, top_k=4, depth=3, use_memo=False)
    assert memoized.makespan == tree.makespan == 10
    assert memoized.deduplicated_states > 0
    assert memoized.evaluated_candidates < tree.evaluated_candidates


def test_stage2_registry_excludes_historical_monte_carlo() -> None:
    benchmark = benchmark_from_dict(
        {
            "schema_version": "2.0",
            "id": "registry_stage2",
            "scenario": "single_channel",
            "family": "complex_chain",
            "category": "adversarial",
            "objective": "makespan",
            "time_unit": "tick",
            "semantics": {
                "preemption": "communication_resume",
                "decision_epoch": "task_event",
                "optional_idle": False,
                "compute_model": "unbounded_parallel",
                "resource_model": "exclusive_fixed_set",
                "preemption_cost": 0,
                "minimum_quantum": 0,
            },
            "resources": [{"id": "channel:0", "kind": "channel"}],
            "tasks": [
                {
                    "id": "a",
                    "kind": "communication",
                    "duration": 1,
                    "dependencies": [],
                    "resources": ["channel:0"],
                }
            ],
        }
    )
    names = algorithms_for(benchmark)
    assert "monte_carlo64" not in names
    assert {
        "downstream_demand",
        "join_aware",
        "rollout2_depth2",
        "exact_uncompressed",
    } <= names.keys()
    assert names["beam8"].development_status == "experimental"
    assert "not a deployment candidate" in names["beam8"].description
    assert "worst case degrades" in names["downstream_demand"].description


def test_stage2_traces_replay_for_priorities_rollout_beam_and_exact() -> None:
    dag = DAG('diamond', (Task('fork', 'comm', 1), Task('left', 'compute', 2, ('fork',)), Task('right', 'compute', 3, ('fork',)), Task('left_comm', 'comm', 2, ('left',)), Task('right_comm', 'comm', 1, ('right',)), Task('join', 'compute', 2, ('left_comm', 'right_comm'))), context=(('category', 'test'),))
    results = [
        schedule_priority(dag, "longest_tail"),
        schedule_priority(dag, "join_aware"),
        schedule_rollout(dag, depth=2),
        beam_search(dag, width=4),
        exact_oracle(dag),
    ]
    for result in results:
        assert_preemptive_trace(dag, result.trace)
        assert result.trace.final_state.time == result.makespan


def test_remaining_lower_bound_is_defined_on_reachable_preempted_state() -> None:
    dag = DAG('bound_state', (Task('release', 'compute', 2), Task('long', 'comm', 4), Task('short', 'comm', 1, ('release',)), Task('tail', 'compute', 3, ('short',))), context=(('category', 'test'),))
    model = PreeSingleModel(dag)
    state = model.step(model.initial_state(), Action.run("long")).after
    optimum_remainder = exact_oracle(
        DAG('equivalent_root_check', (Task('long', 'comm', 2), Task('short', 'comm', 1), Task('tail', 'compute', 3, ('short',))), context=(('category', 'test'),))
    ).makespan
    assert remaining_lower_bound(model, state) <= optimum_remainder
