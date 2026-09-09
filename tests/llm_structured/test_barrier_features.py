from __future__ import annotations

import pytest

from benchmark_generate.llm.preemptive.barrier_motifs import (
    label_motif,
    multi_resource_motifs,
    single_channel_motifs,
)
from core.dag import DAG, Task
from core.oracle.pree_multi import exact_oracle as multi_exact_oracle
from core.execution.preemptive import MultiResourceAction, PreeMultiModel
from core.execution.preemptive import Action, PreeSingleModel
from llm_structured.preemptive.barrier.analysis import (
    action_features,
    build_context,
    feature_snapshot,
    safe_barrier_prescreen,
    score_snapshot,
)
from llm_structured.preemptive.barrier.multi import schedule_barrier_set_policy
from core.trace.pree_multi import assert_multi_resource_trace
from tests.oracles.preemptive.tiny_oracle import tiny_tick_optimum


def _join_dag() -> DAG:
    return DAG('barrier_feature_test', (Task('release', 'compute', 1), Task('candidate', 'comm', 2, ('release',)), Task('other', 'compute', 0), Task('join', 'compute', 3, ('candidate', 'other')), Task('sink', 'compute', 2, ('join',)), Task('independent', 'comm', 1)), context=(('category', 'test'),))


def test_barrier_snapshot_uses_residual_state_and_deduplicates_downstream() -> None:
    model = PreeSingleModel(_join_dag())
    state = model.step(model.initial_state(), Action.run("independent")).after
    context = build_context(model, state)
    snapshot = feature_snapshot(context, "candidate")
    assert snapshot.remaining_work == 2
    assert snapshot.direct_last_missing_join_count == 1
    assert snapshot.direct_last_missing_join_ids == ("join",)
    assert snapshot.downstream_join_tail == 5
    assert snapshot.newly_ready_compute_work == 3
    assert snapshot.newly_ready_compute_ids == ("join",)
    assert snapshot.reachable_descendant_compute_work == 5
    assert snapshot.estimated_candidate_branch_arrival == 2
    assert snapshot.estimated_arrival_spread == 2
    assert dict(snapshot.quantity_modes)["estimated_arrival_spread"] == "heuristic_estimate"


def test_barrier_label_does_not_change_structural_feature() -> None:
    dag = _join_dag()
    labelled = DAG(
        dag.name,
        tuple(
            Task(
                task.task_id,
                task.kind,
                task.duration,
                task.deps,
                labels=tuple((*task.labels, ("collective_type", "allreduce"))),
            )
            if task.task_id == "candidate"
            else task
            for task in dag.tasks
        ),
        context=dag.context,
    )
    first = PreeSingleModel(dag)
    second = PreeSingleModel(labelled)
    first_state = first.step(first.initial_state(), Action.run("independent")).after
    second_state = second.step(second.initial_state(), Action.run("independent")).after
    first_snapshot = feature_snapshot(build_context(first, first_state), "candidate")
    second_snapshot = feature_snapshot(build_context(second, second_state), "candidate")
    assert first_snapshot == second_snapshot


def test_action_features_count_shared_downstream_once() -> None:
    dag = DAG('shared_action_features', (Task('a', 'comm', 1), Task('b', 'comm', 1), Task('left', 'compute', 2, ('a',)), Task('right', 'compute', 2, ('b',)), Task('join', 'compute', 3, ('left', 'right'))), context=(('category', 'test'),))
    model = PreeMultiModel(
        dag, {"a": frozenset({"r1"}), "b": frozenset({"r2"})}
    )
    state = model.initial_state()
    context = build_context(model, state)
    features = action_features(context, ("a", "b"))
    assert features.newly_ready_compute_work == 4
    assert features.newly_ready_compute_ids == ("left", "right")
    assert features.reachable_descendant_compute_work == 7
    assert features.shared_downstream_count == 1
    assert schedule_barrier_set_policy(
        dag, {"a": frozenset({"r1"}), "b": frozenset({"r2"})}
    ).makespan >= 0


def test_newly_ready_does_not_count_reachable_compute_before_its_other_predecessor() -> None:
    dag = DAG('reachable_is_not_release', (Task('candidate', 'comm', 1), Task('blocked', 'comm', 1), Task('join', 'compute', 9, ('candidate', 'blocked'))), context=(('category', 'test'),))
    model = PreeSingleModel(dag)
    snapshot = feature_snapshot(build_context(model, model.initial_state()), "candidate")
    assert snapshot.newly_ready_compute_work == 0
    assert snapshot.newly_ready_compute_ids == ()
    assert snapshot.reachable_descendant_compute_work == 9


def test_zero_duration_compute_closure_is_processed_once_before_new_release() -> None:
    dag = DAG('zero_closure_release', (Task('candidate', 'comm', 1), Task('zero', 'compute', 0, ('candidate',)), Task('released', 'compute', 5, ('zero',))), context=(('category', 'test'),))
    model = PreeSingleModel(dag)
    snapshot = feature_snapshot(build_context(model, model.initial_state()), "candidate")
    assert snapshot.newly_ready_compute_ids == ("released",)
    assert snapshot.newly_ready_compute_work == 5


def test_direct_only_prescreen_keeps_lt_and_all_candidates() -> None:
    model = PreeSingleModel(_join_dag())
    state = model.initial_state()
    context = build_context(model, state)
    eligible = model.eligible_communications(state)
    assert safe_barrier_prescreen(context, eligible, "independent") == eligible


def test_score_modes_are_deterministic_and_reject_unknown() -> None:
    model = PreeSingleModel(_join_dag())
    state = model.initial_state()
    snapshot = feature_snapshot(build_context(model, state), "independent")
    assert score_snapshot(snapshot, "barrier_only") == score_snapshot(snapshot, "barrier_only")
    with pytest.raises(ValueError):
        score_snapshot(snapshot, "unknown")


def test_barrier_motif_evidence_has_exact_certificate_for_each_channel() -> None:
    """P0/G1 evidence must distinguish feasible baselines from Exact labels."""

    for motif in single_channel_motifs():
        report = label_motif(motif)
        assert report["exact"]["status"] == "optimal"
        assert report["exact"]["makespan"] == report["baseline_makespan"]

    motif = multi_resource_motifs()[0]
    report = label_motif(motif)
    assert report["exact"]["status"] == "optimal"
    assert report["exact"]["makespan"] == tiny_tick_optimum(
        motif.dag, motif.resources
    )
    result = multi_exact_oracle(motif.dag, motif.resources, max_states=100_000)
    assert result.trace is not None
    assert_multi_resource_trace(motif.dag, motif.resources, result.trace)
