"""Baseline scheduling, replay validation, and uniform experiment records."""

from __future__ import annotations

import hashlib
import json
import time

from .adapters import make_adapter
from .contracts import Mode, PolicyName
from .policies import baseline_action

RULES = ("fifo", "fixed_order", "longest_tail")
MODES = ("optional_idle", "work_conserving")


def _digest(actions) -> str:
    return hashlib.sha256(json.dumps(actions, sort_keys=True).encode()).hexdigest()


def action_digest(adapter, actions) -> str:
    """Return the stable public digest used by all replay paths."""
    payload = [
        (action.kind, action.task_id)
        if adapter.resource_model == "single_channel"
        else (action.kind, action.starts)
        for action in actions
    ]
    return _digest(payload)


def _job_metrics(benchmark, completions):
    records = benchmark.metadata.get("multi_job")
    if not records:
        return None
    result = []
    for record in records:
        members = [
            task.task_id
            for task in benchmark.tasks
            if task.metadata.get("job_id") == record["job_id"]
        ]
        completion = max((completions[item] for item in members), default=None)
        arrival = int(record.get("arrival", 0))
        result.append(
            {
                "job_id": record["job_id"],
                "arrival": arrival,
                "completion": completion,
                "jct": None if completion is None else completion - arrival,
            }
        )
    return result


def run_baseline_loop(
    benchmark,
    rule: PolicyName = "longest_tail",
    mode: Mode = "optional_idle",
    *,
    observe: bool = False,
    observation_limit: int | None = None,
    progress=None,
    adapter=None,
    metrics: dict | None = None,
):
    """Run only policy selection and simulator transitions, without trace replay."""
    if rule not in {"fifo", "fixed_order", "longest_tail", "spt", "lpt"} or mode not in MODES:
        raise ValueError(f"unsupported replay configuration: {rule}/{mode}")
    adapter = make_adapter(benchmark) if adapter is None else adapter
    state = adapter.initial_state()
    actions = []
    first_seen = {}
    candidates = divergences = 0
    context_seconds = policy_seconds = observation_seconds = step_seconds = 0.0
    while not adapter.is_finished(state):
        phase_started = time.perf_counter()
        context = adapter.decision_context(state, mode)
        context_seconds += time.perf_counter() - phase_started
        ready = context.ready
        for item in ready:
            first_seen.setdefault(item, (state.time, adapter.model.index[item]))
        observing = observe and (observation_limit is None or len(actions) < observation_limit)
        phase_started = time.perf_counter()
        action = baseline_action(adapter, state, mode, rule, first_seen, context)
        policy_seconds += time.perf_counter() - phase_started
        if observing:
            phase_started = time.perf_counter()
            candidates += len(context.legal_actions)
            choices = [
                baseline_action(adapter, state, mode, name, first_seen, context) for name in RULES
            ]
            divergences += len({adapter.signature(state, item) for item in choices}) > 1
            observation_seconds += time.perf_counter() - phase_started
        actions.append(action)
        phase_started = time.perf_counter()
        state = adapter.step(state, action).after
        step_seconds += time.perf_counter() - phase_started
        if progress is not None:
            progress(len(actions), state.time)
    if metrics is not None:
        metrics.update(
            {
                "decision_context": context_seconds * 1000,
                "policy_sorting": policy_seconds * 1000,
                "observation": observation_seconds * 1000,
                "state_transition": step_seconds * 1000,
            }
        )
    return adapter, state, tuple(actions), candidates, divergences


def schedule_baseline(
    benchmark,
    rule: PolicyName = "longest_tail",
    mode: Mode = "optional_idle",
) -> dict:
    started = time.perf_counter()
    adapter, state, actions, candidates, divergences = run_baseline_loop(benchmark, rule, mode)
    summary = adapter.replay(actions)
    result = {
        "status": "completed",
        "termination_reason": None,
        "rule": rule,
        "mode": mode,
        "makespan": summary.makespan,
        "decisions": len(actions),
        "candidate_actions": candidates,
        "action_divergences": divergences,
        "voluntary_waits": summary.voluntary_waits,
        "voluntary_wait_time": summary.voluntary_wait_time,
        "forced_waits": summary.forced_waits,
        "forced_wait_time": summary.forced_wait_time,
        "trace_hash": action_digest(adapter, actions),
        "trace_valid": summary.trace_valid,
        "runtime_ms": (time.perf_counter() - started) * 1000,
    }
    completions = {
        task.task_id: state.tasks[index].completed_at or 0
        for index, task in enumerate(adapter.model.tasks)
    }
    jobs = _job_metrics(benchmark, completions)
    if jobs is not None:
        result["jobs"] = jobs
    return result


replay = schedule_baseline
