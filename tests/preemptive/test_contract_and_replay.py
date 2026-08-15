"""Contract, independent replay, and cross-Oracle regressions for v2."""

from __future__ import annotations

from dataclasses import replace
import random

import pytest

from core.dag import BenchmarkDAG, BenchTask
from benchmark import benchmark_from_dict, benchmark_to_dict
from core.execution.preemptive import Action, ExecutionInterval, PreemptiveDAGModel
from core.trace.preemptive import assert_preemptive_trace
from muti_channel.preemptive.solver import (
    MultiAction,
    PreemptiveMultiResourceModel,
    exact_oracle as multi_exact,
)
from muti_channel.preemptive.trace import assert_multi_resource_trace
from single_channel.complex_chain.preemptive.solver import exact_oracle
from single_channel.parallel_chain.preemptive.interface import validate_parallel_chain
from tests.helpers.tiny_preemptive_oracle import tiny_tick_optimum


def _release_dag() -> BenchmarkDAG:
    return BenchmarkDAG(
        "release",
        "test",
        (
            BenchTask("release_b", "compute", 2),
            BenchTask("a", "comm", 4),
            BenchTask("b", "comm", 1, ("release_b",)),
            BenchTask("tail", "compute", 4, ("b",)),
        ),
    )


def test_single_channel_rejects_voluntary_wait_and_allows_forced_idle() -> None:
    model = PreemptiveDAGModel(_release_dag())
    state = model.initial_state()
    assert Action.wait() not in model.legal_actions(state)
    with pytest.raises(ValueError, match="voluntary WAIT"):
        model.step(state, Action.wait())

    trace = model.run(
        (Action.run("a"), Action.run("b"), Action.run("a"), Action.wait())
    )
    assert_preemptive_trace(model.dag, trace)


def test_independent_single_trace_rejects_missing_events_and_transitions() -> None:
    model = PreemptiveDAGModel(_release_dag())
    trace = model.run(
        (Action.run("a"), Action.run("b"), Action.run("a"), Action.wait())
    )
    with pytest.raises(AssertionError, match="events"):
        assert_preemptive_trace(model.dag, replace(trace, events=()))
    with pytest.raises(AssertionError, match="transition"):
        assert_preemptive_trace(model.dag, replace(trace, transitions=()))


def test_independent_single_trace_rejects_interval_corruption() -> None:
    model = PreemptiveDAGModel(_release_dag())
    trace = model.run(
        (Action.run("a"), Action.run("b"), Action.run("a"), Action.wait())
    )
    comm = next(span for span in trace.intervals if span.task_id == "b")
    with pytest.raises(AssertionError, match="kind mismatch"):
        assert_preemptive_trace(
            model.dag,
            replace(
                trace,
                intervals=tuple(
                    replace(span, kind="compute") if span == comm else span
                    for span in trace.intervals
                ),
            ),
        )
    with pytest.raises(AssertionError, match="duration mismatch"):
        assert_preemptive_trace(
            model.dag,
            replace(
                trace,
                intervals=tuple(
                    replace(span, end=span.end + 1) if span == comm else span
                    for span in trace.intervals
                ),
            ),
        )
    compute = next(span for span in trace.intervals if span.task_id == "tail")
    split = (
        ExecutionInterval("tail", "compute", compute.start, compute.start + 1),
        ExecutionInterval("tail", "compute", compute.start + 1, compute.end),
    )
    with pytest.raises(AssertionError, match="continuous interval"):
        assert_preemptive_trace(
            model.dag,
            replace(
                trace,
                intervals=tuple(span for span in trace.intervals if span != compute) + split,
            ),
        )
    with pytest.raises(AssertionError, match="precedence"):
        assert_preemptive_trace(
            model.dag,
            replace(
                trace,
                intervals=tuple(
                    replace(span, start=1, end=2) if span == comm else span
                    for span in trace.intervals
                ),
            ),
        )


def test_multi_resource_rejects_nonmaximal_wait_duplicate_and_zero_duration() -> None:
    dag = BenchmarkDAG(
        "two_resources",
        "test",
        (BenchTask("a", "comm", 2), BenchTask("b", "comm", 2)),
    )
    resources = {"a": frozenset({"left"}), "b": frozenset({"right"})}
    model = PreemptiveMultiResourceModel(dag, resources)
    state = model.initial_state()
    assert model.legal_actions(state) == (MultiAction(("a", "b")),)
    with pytest.raises(ValueError, match="not inclusion-maximal"):
        model.step(state, MultiAction(("a",)))
    with pytest.raises(ValueError, match="voluntary WAIT"):
        model.step(state, MultiAction())
    with pytest.raises(ValueError, match="duplicate"):
        model.step(state, MultiAction(("a", "a")))

    zero = BenchmarkDAG("zero", "test", (BenchTask("z", "comm", 0),))
    with pytest.raises(ValueError, match="positive communication"):
        PreemptiveMultiResourceModel(zero, {"z": frozenset({"r"})})


def test_multi_resource_trace_audits_resources_and_maximal_decisions() -> None:
    dag = BenchmarkDAG(
        "multi_trace",
        "test",
        (
            BenchTask("release", "compute", 1),
            BenchTask("a", "comm", 3),
            BenchTask("b", "comm", 2, ("release",)),
            BenchTask("tail", "compute", 2, ("b",)),
        ),
    )
    resources = {"a": frozenset({"r"}), "b": frozenset({"r"})}
    result = multi_exact(dag, resources)
    assert result.trace is not None
    assert_multi_resource_trace(dag, resources, result.trace)
    with pytest.raises(AssertionError, match="resource intervals"):
        assert_multi_resource_trace(
            dag, resources, replace(result.trace, resource_intervals=())
        )


def test_multi_replay_rejects_nonmaximal_recorded_decision() -> None:
    dag = BenchmarkDAG(
        "multi_nonmax_trace",
        "test",
        (BenchTask("a", "comm", 2), BenchTask("b", "comm", 2)),
    )
    resources = {"a": frozenset({"left"}), "b": frozenset({"right"})}
    result = multi_exact(dag, resources)
    assert result.trace is not None
    first = result.trace.decisions[0]
    corrupted = replace(
        result.trace,
        decisions=(replace(first, action=MultiAction(("a",))), *result.trace.decisions[1:]),
    )
    with pytest.raises(AssertionError, match="not inclusion-maximal"):
        assert_multi_resource_trace(dag, resources, corrupted)


def test_v2_loader_normalizes_historical_optional_idle_contract() -> None:
    payload = {
        "schema_version": "2.0",
        "id": "old_v2_contract",
        "scenario": "single_channel",
        "family": "complex_chain",
        "category": "adversarial",
        "objective": "makespan",
        "time_unit": "tick",
        "semantics": {
            "preemption": "communication_resume",
            "decision_epoch": "task_event",
            "optional_idle": True,
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
    benchmark = benchmark_from_dict(payload)
    assert benchmark.semantics.work_conserving
    assert benchmark_to_dict(benchmark)["semantics"]["optional_idle"] is False


def _random_tiny_dag(rng: random.Random, index: int) -> BenchmarkDAG:
    tasks: list[BenchTask] = []
    for node in range(rng.randint(2, 6)):
        kind = "comm" if rng.random() < 0.55 else "compute"
        duration = rng.randint(1, 3) if kind == "comm" else rng.randint(0, 3)
        parents = tuple(
            tasks[parent].task_id
            for parent in range(node)
            if rng.random() < 0.22
        )
        tasks.append(BenchTask(f"t{node}", kind, duration, parents))
    if not any(task.kind == "comm" for task in tasks):
        tasks[0] = BenchTask(tasks[0].task_id, "comm", max(1, tasks[0].duration))
    return BenchmarkDAG(f"tiny_{index}", "random_test", tuple(tasks))


def test_event_exact_matches_independent_tiny_tick_oracle() -> None:
    rng = random.Random(260815)
    for index in range(20):
        dag = _random_tiny_dag(rng, index)
        assert exact_oracle(dag).makespan == tiny_tick_optimum(dag)


def test_parallel_chain_entry_rejects_general_dag_and_task_order_is_irrelevant() -> None:
    fork = BenchmarkDAG(
        "fork",
        "test",
        (
            BenchTask("a", "comm", 1),
            BenchTask("b", "compute", 1, ("a",)),
            BenchTask("c", "compute", 1, ("a",)),
        ),
    )
    with pytest.raises(ValueError, match="fork/join"):
        validate_parallel_chain(fork)

    dag = _random_tiny_dag(random.Random(19), 0)
    reordered = replace(dag, tasks=tuple(reversed(dag.tasks)))
    assert exact_oracle(dag).makespan == exact_oracle(reordered).makespan


def test_multi_event_exact_matches_independent_tiny_tick_oracle() -> None:
    rng = random.Random(260816)
    resource_pool = ("r0", "r1", "r2")
    for index in range(12):
        dag = _random_tiny_dag(rng, index)
        resources = {
            task.task_id: frozenset(
                resource_pool[position]
                for position in range(rng.randint(1, 2))
            )
            for task in dag.tasks
            if task.kind == "comm"
        }
        assert multi_exact(dag, resources).makespan == tiny_tick_optimum(dag, resources)
