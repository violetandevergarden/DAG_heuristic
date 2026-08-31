"""Contention audit driven exclusively by the non-preemptive state machines."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import asdict

from benchmark import Benchmark
from core.conversion import to_internal_dag, to_multi_resource_instance
from core.execution.nonpreemptive import Action, NonPreemptiveDAGModel
from muti_channel.nonpreemptive.solver import (
    NonPreemptiveMultiResourceDAG,
    ResourceAction,
)

EVIDENCE_LEVELS = {
    "not_run",
    "static_only",
    "sampled_prefix",
    "completed_replay",
    "bounded_search",
    "certified_choice_exists",
    "certified_no_choice",
}


def _tail_scores(tasks, children, remaining) -> dict[str, int]:
    values: dict[str, int] = {}
    for index in reversed(range(len(tasks))):
        task = tasks[index]
        values[task.task_id] = remaining(index) + max(
            (values[tasks[child].task_id] for child in children[index]), default=0
        )
    return values


def _state_key(state) -> tuple:
    return tuple((item.status, item.remaining) for item in state.tasks)


def _single_audit(benchmark: Benchmark, max_decisions: int) -> dict:
    model = NonPreemptiveDAGModel(to_internal_dag(benchmark))
    state = model.initial_state()
    first_seen: dict[str, tuple[int, int]] = {}
    decisions = []
    actions = []
    order = {task_id: index for index, task_id in enumerate(model.task_ids)}
    children = [[] for _ in model.tasks]
    for child, parents in enumerate(model.deps):
        for parent in parents:
            children[parent].append(child)
    while not model.is_finished(state) and len(decisions) < max_decisions:
        ready = model.ready_flows(state)
        for task_id in ready:
            first_seen.setdefault(task_id, (state.time, order[task_id]))
        legal = model.legal_actions(state)

        def remaining(index: int, decision_state=state) -> int:
            runtime = model.task_runtime(decision_state, model.tasks[index].task_id)
            if runtime.status == "running":
                return runtime.remaining
            if runtime.status == "completed":
                return 0
            return model.tasks[index].duration

        tails = _tail_scores(
            model.tasks,
            children,
            remaining,
        )
        fifo = min(ready, key=lambda item: (*first_seen[item], item)) if ready else None
        fixed = min(ready, key=lambda item: order[item]) if ready else None
        longest = max(ready, key=lambda item: (tails[item], item)) if ready else None
        successors = {
            (action.kind, action.task_id): _state_key(model.step(state, action).after)
            for action in legal
        }
        decisions.append(
            {
                "time": state.time,
                "ready_communications": list(ready),
                "ready_communication_count": len(ready),
                "active_communication_count": 0,
                "free_resources": ["channel:0"],
                "legal_start_action_count": len(ready),
                "work_conserving_maximal_set_count": len(ready),
                "wait_legal": any(action.kind == "wait" for action in legal),
                "next_real_event": (
                    state.time
                    + min(
                        model.task_runtime(state, item).remaining
                        for item in model.active_computes(state)
                    )
                    if model.active_computes(state)
                    else None
                ),
                "ordering_choice": len(ready) >= 2,
                "set_choice": False,
                "wait_choice": bool(ready and model.active_computes(state)),
                "multiple_legal_actions": len(legal) >= 2,
                "non_equivalent_immediate_successors": len(set(successors.values())) >= 2,
                "policy_actions": {
                    "fifo": fifo,
                    "fixed_order": fixed,
                    "residual_longest_tail": longest,
                },
                "policy_divergence": len(
                    {item for item in (fifo, fixed, longest) if item is not None}
                )
                >= 2,
            }
        )
        if ready:
            action = Action.flow(longest or ready[0])
        elif legal:
            action = Action.wait()
        else:
            raise RuntimeError("unfinished single-channel graph has no legal action")
        actions.append(action)
        state = model.step(state, action).after
    return {
        "scenario": benchmark.scenario,
        "decisions": decisions,
        "decision_count": len(decisions),
        "completed": model.is_finished(state),
        "partial_simulation_time": state.time,
        "action_trace": [asdict(item) for item in actions],
    }


def _multi_audit(benchmark: Benchmark, max_decisions: int, enumeration_limit: int) -> dict:
    model = NonPreemptiveMultiResourceDAG(to_multi_resource_instance(benchmark))
    state = model.initial_state()
    resource_universe = {item.resource_id for item in benchmark.resources}
    decisions = []
    actions = []
    while not model.is_finished(state) and len(decisions) < max_decisions:
        ready = model.ready_flows(state)
        active = model.active_flows(state)
        optional = model.legal_actions(state, "optional_idle")
        maximal = model.start_subsets(state, maximal_only=True)
        if len(optional) > enumeration_limit:
            optional = optional[:enumeration_limit]
        path, tail = model.residual_features(state)
        ranked = sorted(
            ready,
            key=lambda item: (-tail[model.index[item]], -path[model.index[item]], item),
        )
        preferred = tuple(ranked_item for ranked_item in ranked)
        starts = [action for action in optional if action.starts]
        chosen = (
            max(
                starts,
                key=lambda action: (
                    sum(path[model.index[item]] for item in action.starts),
                    len(action.starts),
                    tuple(reversed(action.starts)),
                ),
            )
            if starts
            else ResourceAction.wait()
        )
        successor_keys = {_state_key(model.step(state, action).after) for action in optional}
        occupied = model.occupied_resources(state)
        decisions.append(
            {
                "time": state.time,
                "ready_communications": list(ready),
                "ready_communication_count": len(ready),
                "active_communication_count": len(active),
                "active_communications": list(active),
                "free_resources": sorted(resource_universe - set(occupied)),
                "legal_start_action_count": len(starts),
                "work_conserving_maximal_set_count": len(maximal),
                "wait_legal": any(not action.starts for action in optional),
                "next_real_event": state.time
                + min(runtime.remaining for runtime in state.tasks if runtime.status == "running")
                if any(runtime.status == "running" for runtime in state.tasks)
                else None,
                "ordering_choice": len(ready) >= 2,
                "set_choice": len({action.starts for action in starts}) >= 2,
                "wait_choice": bool(starts and any(not action.starts for action in optional)),
                "multiple_legal_actions": len(optional) >= 2,
                "non_equivalent_immediate_successors": len(successor_keys) >= 2,
                "residual_longest_tail_order": preferred,
                "conflict_resources": sorted(occupied),
                "enumeration_truncated": len(model.legal_actions(state, "optional_idle"))
                > enumeration_limit,
            }
        )
        actions.append(chosen)
        state = model.step(state, chosen).after
    return {
        "scenario": benchmark.scenario,
        "decisions": decisions,
        "decision_count": len(decisions),
        "completed": model.is_finished(state),
        "partial_simulation_time": state.time,
        "action_trace": [{"kind": item.kind, "starts": list(item.starts)} for item in actions],
    }


def contention_audit(
    benchmark: Benchmark,
    *,
    max_decisions: int = 8,
    enumeration_limit: int = 256,
    time_limit_s: float | None = None,
) -> dict:
    """Replay a bounded residual-LT path and classify only observed evidence."""

    started = time.perf_counter()
    report = (
        _single_audit(benchmark, max_decisions)
        if benchmark.scenario == "single_channel"
        else _multi_audit(benchmark, max_decisions, enumeration_limit)
    )
    decisions = report["decisions"]
    report.update(
        {
            "audit_schema_version": "nonpreemptive-contention-audit-v1",
            "evidence_level": "completed_replay" if report["completed"] else "sampled_prefix",
            "termination_reason": "completed" if report["completed"] else "decision_limit",
            "ordering_choice_observed": any(item["ordering_choice"] for item in decisions),
            "set_choice_observed": any(item["set_choice"] for item in decisions),
            "wait_choice_observed": any(item["wait_choice"] for item in decisions),
            "non_equivalent_choice_observed": any(
                item["non_equivalent_immediate_successors"] for item in decisions
            ),
            "policy_divergence_observed": any(
                item.get("policy_divergence", False) for item in decisions
            ),
            "runtime_ms": round((time.perf_counter() - started) * 1000, 3),
            "time_limit_s": time_limit_s,
        }
    )
    return report


def bounded_choice_search(
    benchmark: Benchmark,
    *,
    mode: str = "optional_idle",
    max_states: int = 2_000,
    time_limit_s: float = 10.0,
) -> dict:
    """Certify existence/no-existence only when the bounded graph is exhausted."""

    multi = benchmark.scenario == "muti_channel"
    model = (
        NonPreemptiveMultiResourceDAG(to_multi_resource_instance(benchmark))
        if multi
        else NonPreemptiveDAGModel(to_internal_dag(benchmark))
    )
    initial = model.initial_state()
    queue = deque([initial])
    seen = {_state_key(initial)}
    started = time.perf_counter()
    while queue:
        if len(seen) >= max_states or time.perf_counter() - started >= time_limit_s:
            return {
                "status": "unknown",
                "evidence_level": "bounded_search",
                "explored_states": len(seen),
            }
        state = queue.popleft()
        if model.is_finished(state):
            continue
        actions = model.legal_actions(state, mode) if multi else model.legal_actions(state)
        if not multi and mode == "work_conserving" and model.ready_flows(state):
            actions = tuple(action for action in actions if action.kind != "wait")
        successors = [(action, model.step(state, action).after) for action in actions]
        if len({_state_key(child) for _action, child in successors}) >= 2:
            return {
                "status": "certified_choice_exists",
                "evidence_level": "certified_choice_exists",
                "explored_states": len(seen),
                "decision_time": state.time,
            }
        for _action, child in successors:
            key = _state_key(child)
            if key not in seen:
                seen.add(key)
                queue.append(child)
    return {
        "status": "certified_no_choice",
        "evidence_level": "certified_no_choice",
        "explored_states": len(seen),
    }
