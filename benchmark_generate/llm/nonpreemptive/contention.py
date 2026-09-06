"""Contention audit driven exclusively by the non-preemptive state machines."""

from __future__ import annotations

import hashlib
import json
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


def _stable_random_key(task_id: str) -> str:
    return hashlib.sha256(f"stage4-contention-v1:{task_id}".encode()).hexdigest()


def _digest_state(state) -> str:
    return hashlib.sha256(json.dumps(state, sort_keys=True, default=str).encode()).hexdigest()


def _job_id(task_id: str) -> str:
    return task_id.split("::", 1)[0] if "::" in task_id else "job0"


def _single_audit(
    benchmark: Benchmark, max_decisions: int, deadline: float | None, mode: str
) -> dict:
    model = NonPreemptiveDAGModel(to_internal_dag(benchmark))
    state = model.initial_state()
    first_seen: dict[str, tuple[int, int]] = {}
    decisions = []
    actions = []
    timed_out = False
    order = {task_id: index for index, task_id in enumerate(model.task_ids)}
    children = [[] for _ in model.tasks]
    for child, parents in enumerate(model.deps):
        for parent in parents:
            children[parent].append(child)
    while not model.is_finished(state) and len(decisions) < max_decisions:
        if deadline is not None and time.perf_counter() >= deadline:
            timed_out = True
            break
        ready = model.ready_flows(state)
        for task_id in ready:
            first_seen.setdefault(task_id, (state.time, order[task_id]))
        legal = model.legal_actions(state)
        if mode == "work_conserving" and ready:
            legal = tuple(action for action in legal if action.kind != "wait")

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
        shortest = min(ready, key=lambda item: (remaining(order[item]), item)) if ready else None
        longest_processing = (
            max(ready, key=lambda item: (remaining(order[item]), item)) if ready else None
        )
        random_choice = min(ready, key=_stable_random_key) if ready else None
        successors = {
            (action.kind, action.task_id): _state_key(model.step(state, action).after)
            for action in legal
        }
        decisions.append(
            {
                "time": state.time,
                "decision_index": len(decisions),
                "state_hash": _digest_state(state),
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
                    "spt": shortest,
                    "lpt": longest_processing,
                    "random_seed_0": random_choice,
                },
                "policy_divergence": len(
                    {
                        item
                        for item in (
                            fifo,
                            fixed,
                            longest,
                            shortest,
                            longest_processing,
                            random_choice,
                        )
                        if item is not None
                    }
                )
                >= 2,
                "cross_job_ready_conflict": len({_job_id(item) for item in ready}) >= 2,
                "active_reservation_cross_job_block": False,
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
        "time_truncated": timed_out,
    }


def _greedy_set(model, state, ordered: list[str]) -> tuple[str, ...]:
    occupied = set(model.occupied_resources(state))
    selected = []
    for task_id in ordered:
        resources = model.resources[model.index[task_id]]
        if occupied & resources:
            continue
        selected.append(task_id)
        occupied.update(resources)
    return tuple(sorted(selected))


def _multi_audit(
    benchmark: Benchmark,
    max_decisions: int,
    enumeration_limit: int,
    deadline: float | None,
    mode: str,
) -> dict:
    model = NonPreemptiveMultiResourceDAG(to_multi_resource_instance(benchmark))
    state = model.initial_state()
    resource_universe = {item.resource_id for item in benchmark.resources}
    decisions = []
    actions = []
    first_seen: dict[str, tuple[int, int]] = {}
    timed_out = False
    while not model.is_finished(state) and len(decisions) < max_decisions:
        if deadline is not None and time.perf_counter() >= deadline:
            timed_out = True
            break
        ready = model.ready_flows(state)
        for task_id in ready:
            first_seen.setdefault(task_id, (state.time, model.index[task_id]))
        active = model.active_flows(state)
        startable = model.startable_flows(state)
        path, tail = model.residual_features(state)
        ranked = sorted(
            startable,
            key=lambda item: (-tail[model.index[item]], -path[model.index[item]], item),
        )
        preferred = tuple(ranked_item for ranked_item in ranked)
        resource_loads = {
            resource: sum(
                model.remaining(state, index)
                for index, resources in enumerate(model.resources)
                if resource in resources
            )
            for resource in resource_universe
        }
        orderings = {
            "fifo": sorted(startable, key=lambda item: (*first_seen[item], item)),
            "fixed_order": sorted(startable, key=lambda item: model.index[item]),
            "residual_longest_tail": ranked,
            "spt": sorted(
                startable, key=lambda item: (model.tasks[model.index[item]].duration, item)
            ),
            "lpt": sorted(
                startable, key=lambda item: (-model.tasks[model.index[item]].duration, item)
            ),
            "hotspot_avoidance": sorted(
                startable,
                key=lambda item: (
                    max(
                        (
                            resource_loads[resource]
                            for resource in model.resources[model.index[item]]
                        ),
                        default=0,
                    ),
                    item,
                ),
            ),
            "resource_complement": sorted(
                startable,
                key=lambda item: (
                    len(model.resources[model.index[item]]),
                    -tail[model.index[item]],
                    item,
                ),
            ),
            "random_seed_0": sorted(startable, key=_stable_random_key),
        }
        policy_actions = {
            name: _greedy_set(model, state, order) for name, order in orderings.items()
        }
        policy_objects = {
            name: ResourceAction.start(items) if items else ResourceAction.wait()
            for name, items in policy_actions.items()
        }
        for action in policy_objects.values():
            model.validate_action(state, action, mode)
        chosen = policy_objects["residual_longest_tail"]
        enumeratable = len(startable) <= 10 and (1 << len(startable)) - 1 <= enumeration_limit
        maximal = model.start_subsets(state, maximal_only=True) if enumeratable else ()
        all_starts = (
            model.start_subsets(state, maximal_only=mode == "work_conserving")
            if enumeratable
            else ()
        )
        representative = tuple(dict.fromkeys(policy_objects.values()))
        if mode == "optional_idle" and model.has_future_event(state):
            representative = (*representative, ResourceAction.wait())
        successor_keys = {_state_key(model.step(state, action).after) for action in representative}
        occupied = model.occupied_resources(state)
        cross_job_ready_conflict = any(
            _job_id(left) != _job_id(right)
            and model.resources[model.index[left]] & model.resources[model.index[right]]
            for position, left in enumerate(ready)
            for right in ready[position + 1 :]
        )
        active_reservation_cross_job_block = any(
            _job_id(blocked) != _job_id(running)
            and model.resources[model.index[blocked]] & model.resources[model.index[running]]
            for blocked in ready
            if blocked not in startable
            for running in active
        )
        decisions.append(
            {
                "time": state.time,
                "decision_index": len(decisions),
                "state_hash": _digest_state(state),
                "ready_communications": list(ready),
                "ready_communication_count": len(ready),
                "active_communication_count": len(active),
                "active_communications": list(active),
                "free_resources": sorted(resource_universe - set(occupied)),
                "startable_count": len(startable),
                "legal_start_action_count": len(all_starts) if enumeratable else None,
                "work_conserving_maximal_set_count": len(maximal) if enumeratable else None,
                "wait_legal": mode == "optional_idle" and model.has_future_event(state),
                "next_real_event": state.time
                + min(runtime.remaining for runtime in state.tasks if runtime.status == "running")
                if any(runtime.status == "running" for runtime in state.tasks)
                else None,
                "ordering_choice": len(ready) >= 2,
                "set_choice": len(set(policy_actions.values())) >= 2,
                "wait_choice": bool(
                    startable and mode == "optional_idle" and model.has_future_event(state)
                ),
                "multiple_legal_actions": len(set(policy_actions.values())) >= 2
                or bool(startable and mode == "optional_idle" and model.has_future_event(state)),
                "non_equivalent_immediate_successors": len(successor_keys) >= 2,
                "residual_longest_tail_order": preferred,
                "conflict_resources": sorted(occupied),
                "enumeration_skipped": not enumeratable,
                "enumeration_truncated": False,
                "policy_actions": policy_actions,
                "policy_divergence": len(set(policy_actions.values())) >= 2,
                "cross_job_ready_conflict": cross_job_ready_conflict,
                "active_reservation_cross_job_block": active_reservation_cross_job_block,
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
        "time_truncated": timed_out,
    }


def contention_audit(
    benchmark: Benchmark,
    *,
    max_decisions: int = 8,
    enumeration_limit: int = 256,
    time_limit_s: float | None = None,
    mode: str = "optional_idle",
) -> dict:
    """Replay a bounded residual-LT path and classify only observed evidence."""

    started = time.perf_counter()
    deadline = None if time_limit_s is None else started + time_limit_s
    report = (
        _single_audit(benchmark, max_decisions, deadline, mode)
        if benchmark.scenario == "single_channel"
        else _multi_audit(benchmark, max_decisions, enumeration_limit, deadline, mode)
    )
    decisions = report["decisions"]
    choice_count = sum(item["multiple_legal_actions"] for item in decisions)
    divergence_count = sum(item.get("policy_divergence", False) for item in decisions)
    state_conflict_count = sum(item["non_equivalent_immediate_successors"] for item in decisions)
    report.update(
        {
            "audit_schema_version": "nonpreemptive-contention-audit-v1",
            "evidence_level": "completed_replay" if report["completed"] else "sampled_prefix",
            "termination_reason": "completed"
            if report["completed"]
            else "time_limit"
            if report["time_truncated"]
            else "decision_limit",
            "mode": mode,
            "ordering_choice_observed": any(item["ordering_choice"] for item in decisions),
            "set_choice_observed": any(item["set_choice"] for item in decisions),
            "wait_choice_observed": any(item["wait_choice"] for item in decisions),
            "non_equivalent_choice_observed": any(
                item["non_equivalent_immediate_successors"] for item in decisions
            ),
            "policy_divergence_observed": any(
                item.get("policy_divergence", False) for item in decisions
            ),
            "cross_job_ready_conflict_count": sum(
                item.get("cross_job_ready_conflict", False) for item in decisions
            ),
            "active_reservation_cross_job_block_count": sum(
                item.get("active_reservation_cross_job_block", False) for item in decisions
            ),
            "conflict_counts": {
                "action": choice_count,
                "policy": divergence_count,
                "state": state_conflict_count,
                "quality": None,
            },
            "quality_evidence": "not_run",
            "choice_density": choice_count / len(decisions) if decisions else 0.0,
            "policy_divergence_rate": divergence_count / len(decisions) if decisions else 0.0,
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
