"""End-to-end preemptive semantics checks on SimAI-exported benchmarks.

Every test drives the public simulator on a benchmark that went through the
real conversion chain and then replays it with the independent trace
validator.  The five scenarios: preemption/resume conservation,
maximal-compatible parallelism, atomic fixed resource acquisition,
simulator-owned forced idle (no WAIT), and atomic handling of same-time
completion events.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from benchmark import Benchmark
from benchmark_generate.simai.projection import project_resources
from benchmark_generate.simai.export import (
    build_synthetic_input,
    build_workload,
    to_benchmark,
)
from core.conversion import to_internal_dag, to_multi_resource_instance
from core.dag import BenchmarkDAG
from core.execution.preemptive import Action, PreemptiveDAGModel, result_from_trace
from core.execution.multi_resource import PreemptiveMultiResourceModel
from core.trace.preemptive import assert_preemptive_trace
from muti_channel.preemptive.trace import assert_multi_resource_trace


def _exported_1f1b(*, pp=2, ga=2, bandwidth_gbps=200.0) -> Benchmark:
    header, items = build_synthetic_input(pp=pp, tp=1, dp=1, ep=1, ga=ga, layers=1)
    built = build_workload("1f1b", header, items)
    return to_benchmark(
        built,
        f"e2e_1f1b_pp{pp}_ga{ga}",
        bandwidth_gbps=bandwidth_gbps,
        category="random",
    )


def _run_single_channel(dag: BenchmarkDAG):
    model = PreemptiveDAGModel(dag)
    state = model.initial_state()
    actions = []
    rounds = 0
    while not model.is_finished(state) and rounds < 10_000:
        eligible = model.eligible_communications(state)
        if eligible:
            # Round-robin switching so a paused communication is not always
            # the one resumed.
            actions.append(Action.run(eligible[rounds % len(eligible)]))
        else:
            actions.append(Action.wait())
        state = model.step(state, actions[-1]).after
        rounds += 1
    trace = model.run(actions)
    assert_preemptive_trace(model, trace)
    return model, trace


def _run_multi_channel(benchmark: Benchmark):
    instance = to_multi_resource_instance(benchmark)
    resources = {
        task_id: frozenset(str(resource) for resource in values)
        for task_id, values in instance.resources.items()
    }
    model = PreemptiveMultiResourceModel(instance.dag, resources)
    state = model.initial_state()
    actions = []
    while not model.finished(state):
        state, _idle = model.normalize_decision_state(state)
        if model.finished(state):
            break
        legal = model.legal_actions(state)
        action = max(legal, key=lambda item: len(item.communications))
        actions.append(action)
        state = model.step(state, action)
    trace = model.run(tuple(actions))
    assert_multi_resource_trace(instance.dag, resources, trace)
    return model, trace, resources


def test_1_preemption_preserves_remaining_work() -> None:
    # A tiny bandwidth makes communications much longer than compute, so the
    # round-robin driver really pauses and resumes them.
    benchmark = _exported_1f1b(bandwidth_gbps=0.001)
    dag = to_internal_dag(benchmark)
    model, trace = _run_single_channel(dag)
    result = result_from_trace(trace)

    assert result.preemptions > 0
    spans_by_task: dict[str, list] = defaultdict(list)
    for span in trace.intervals:
        if span.kind == "comm":
            spans_by_task[span.task_id].append(span)
    for task in dag.tasks:
        if task.kind != "comm":
            continue
        spans = spans_by_task[task.task_id]
        assert spans, f"{task.task_id} must run"
        assert sum(span.end - span.start for span in spans) == task.duration
        # Every span but the last must have been paused (remaining work kept).
        assert all(span.end - span.start > 0 for span in spans)


def test_2_disjoint_communications_enter_maximal_actions() -> None:
    header, items = build_synthetic_input(pp=2, tp=2, dp=2, ep=1, ga=2, layers=1)
    built = build_workload("1f1b", header, items)
    benchmark = to_benchmark(
        built,
        "e2e_parallel",
        category="random",
        projection_relation="relaxation_isolated_dimensions",
    )
    projected = project_resources(benchmark, "isolated_dimensions")
    model, _trace, resources = _run_multi_channel(projected)

    seen_parallel_pair = False
    state = model.initial_state()
    while not model.finished(state):
        state, _idle = model.normalize_decision_state(state)
        if model.finished(state):
            break
        eligible = model.eligible(state)
        legal = model.legal_actions(state)
        # Every legal action must be an inclusion-maximal compatible set:
        # an omitted eligible communication must conflict with some member.
        for action in legal:
            for other in eligible:
                if other in action.communications:
                    continue
                assert any(
                    not resources[other].isdisjoint(resources[member])
                    for member in action.communications
                ), f"non-maximal action {action.communications} omits compatible {other}"
        for first in eligible:
            for second in eligible:
                if first >= second:
                    continue
                if not resources[first].isdisjoint(resources[second]):
                    continue
                seen_parallel_pair = True
                # {first, second} is a compatible set, so some maximal action
                # must contain both of them.
                assert any(
                    first in action.communications and second in action.communications
                    for action in legal
                ), f"compatible pair {first}/{second} missing from every maximal action"
        state = model.step(state, max(legal, key=lambda item: len(item.communications)))
    assert seen_parallel_pair, "probe never reached two disjoint eligible communications"


def test_3_two_resource_communication_acquires_atomically() -> None:
    topology = Path(__file__).parent / "fixtures/two_gpu_topology.txt"
    header, items = build_synthetic_input(pp=2, tp=1, dp=1, ep=1, ga=2, layers=1)
    built = build_workload("1f1b", header, items)
    benchmark = to_benchmark(
        built,
        "e2e_atomic",
        topology_path=topology,
        category="random",
        projection_relation="route_frozen_projection",
    )
    _model, trace, resources = _run_multi_channel(benchmark)

    intervals_by_task: dict[str, dict[str, set]] = defaultdict(lambda: defaultdict(set))
    for item in trace.resource_intervals:
        intervals_by_task[item.task_id][item.resource_id].add((item.start, item.end))
    for task_id, resource_set in resources.items():
        spans = intervals_by_task[task_id]
        assert set(spans) == set(resource_set), (
            f"{task_id} must occupy every one of its resources, not a subset"
        )
        first = None
        for resource in resource_set:
            if first is None:
                first = spans[resource]
            assert spans[resource] == first, (
                f"{task_id} acquires/releases its resources non-atomically"
            )


def test_4_forced_idle_is_simulator_owned_and_wait_is_forbidden() -> None:
    benchmark = _exported_1f1b()
    dag = to_internal_dag(benchmark)

    # Single channel: WAIT is only legal when no communication is eligible.
    model = PreemptiveDAGModel(dag)
    state = model.initial_state()
    if model.eligible_communications(state):
        from core.execution.common import IllegalActionError

        try:
            model.step(state, Action.wait())
        except IllegalActionError as error:
            assert "voluntary WAIT is forbidden" in str(error)
        else:
            raise AssertionError("voluntary WAIT while eligible must be rejected")

    # Multi resource: the simulator owns forced idle; the model has no WAIT
    # action at all and idle intervals appear in the trace.
    topology = Path(__file__).parent / "fixtures/two_gpu_topology.txt"
    header, items = build_synthetic_input(pp=2, tp=1, dp=1, ep=1, ga=1, layers=1)
    built = build_workload("1f1b", header, items)
    multi = to_benchmark(
        built,
        "e2e_forced_idle",
        topology_path=topology,
        category="random",
        projection_relation="route_frozen_projection",
    )
    instance = to_multi_resource_instance(multi)
    resources = {
        task_id: frozenset(str(resource) for resource in values)
        for task_id, values in instance.resources.items()
    }
    model = PreemptiveMultiResourceModel(instance.dag, resources)
    state = model.initial_state()
    if not model.eligible(state):
        advanced, idle = model.normalize_decision_state(state)
        assert advanced.time > state.time
        assert idle is not None
    else:
        # The export starts with eligible communications only when no compute
        # precedes them; in that case the no-WAIT contract is that every
        # legal action is a non-empty communication set.
        assert all(action.communications for action in model.legal_actions(state))


def test_5_same_time_events_are_processed_atomically() -> None:
    benchmark = _exported_1f1b(ga=2)
    dag = to_internal_dag(benchmark)
    model, trace = _run_single_channel(dag)

    completions: dict[int, list[str]] = defaultdict(list)
    for event in trace.events:
        if event.kind == "compute_completed":
            completions[event.time].append(event.task_id)
    shared = {time: ids for time, ids in completions.items() if len(ids) >= 2}
    assert shared, "probe never produced two same-time compute completions"

    # Every stable decision state at time t already reflects ALL tasks that
    # completed at time t; the decision can never interleave between them.
    for transition in trace.transitions:
        time = transition.after.time
        for task_id in completions.get(time, ()):
            runtime = model.task_runtime(transition.after, task_id)
            assert runtime.status == "completed", (
                f"decision at t={time} interleaves before same-time completion "
                f"of {task_id}"
            )
