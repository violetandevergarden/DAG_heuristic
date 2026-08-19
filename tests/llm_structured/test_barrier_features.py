from __future__ import annotations

import pytest

from core.dag import BenchmarkDAG, BenchTask
from core.execution.multi_resource import MultiResourceAction, PreemptiveMultiResourceModel
from core.execution.preemptive import Action, PreemptiveDAGModel
from llm_structured.barrier import (
    action_features,
    build_context,
    feature_snapshot,
    score_snapshot,
)
from muti_channel.preemptive.solver import score_sets
from benchmark_generate.llm.barrier_motifs import (
    label_motif,
    multi_resource_motifs,
    single_channel_motifs,
)
from muti_channel.preemptive.solver import exact_oracle as multi_exact_oracle
from muti_channel.preemptive.trace import assert_multi_resource_trace
from tests.oracles.preemptive.tiny_oracle import tiny_tick_optimum


def _join_dag() -> BenchmarkDAG:
    return BenchmarkDAG(
        "barrier_feature_test",
        "test",
        (
            BenchTask("release", "compute", 1),
            BenchTask("candidate", "comm", 2, ("release",)),
            BenchTask("other", "compute", 0),
            BenchTask("join", "compute", 3, ("candidate", "other")),
            BenchTask("sink", "compute", 2, ("join",)),
            BenchTask("independent", "comm", 1),
        ),
    )


def test_barrier_snapshot_uses_residual_state_and_deduplicates_downstream() -> None:
    model = PreemptiveDAGModel(_join_dag())
    state = model.step(model.initial_state(), Action.run("independent")).after
    context = build_context(model, state)
    snapshot = feature_snapshot(context, "candidate")
    assert snapshot.remaining_work == 2
    assert snapshot.last_missing_join_count == 1
    assert snapshot.local_last_missing_count + snapshot.global_last_missing_count == 1
    assert snapshot.downstream_join_tail == 5
    assert snapshot.immediate_compute_release == 3
    assert snapshot.quantity_modes[-2][1] == "heuristic_estimate"


def test_barrier_label_does_not_change_structural_feature() -> None:
    dag = _join_dag()
    labelled = BenchmarkDAG(
        dag.name,
        dag.category,
        tuple(
            BenchTask(
                task.task_id,
                task.kind,
                task.duration,
                task.deps,
                task.role,
                task.cut,
                (("collective_type", "allreduce"),),
            )
            if task.task_id == "candidate"
            else task
            for task in dag.tasks
        ),
    )
    first = PreemptiveDAGModel(dag)
    second = PreemptiveDAGModel(labelled)
    first_state = first.step(first.initial_state(), Action.run("independent")).after
    second_state = second.step(second.initial_state(), Action.run("independent")).after
    first_snapshot = feature_snapshot(build_context(first, first_state), "candidate")
    second_snapshot = feature_snapshot(build_context(second, second_state), "candidate")
    assert first_snapshot.__dict__ | {"label_hint": second_snapshot.label_hint} == second_snapshot.__dict__


def test_action_features_count_shared_downstream_once() -> None:
    dag = BenchmarkDAG(
        "shared_action_features",
        "test",
        (
            BenchTask("a", "comm", 1),
            BenchTask("b", "comm", 1),
            BenchTask("left", "compute", 2, ("a",)),
            BenchTask("right", "compute", 2, ("b",)),
            BenchTask("join", "compute", 3, ("left", "right")),
        ),
    )
    model = PreemptiveMultiResourceModel(
        dag, {"a": frozenset({"r1"}), "b": frozenset({"r2"})}
    )
    state = model.initial_state()
    context = build_context(model, state)
    features = action_features(context, ("a", "b"))
    assert features.union_released_compute == 7
    assert features.shared_downstream_count == 1
    scored = score_sets(model, state, (MultiResourceAction(("a", "b")),), "barrier_union")
    assert scored


def test_score_modes_are_deterministic_and_reject_unknown() -> None:
    model = PreemptiveDAGModel(_join_dag())
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
