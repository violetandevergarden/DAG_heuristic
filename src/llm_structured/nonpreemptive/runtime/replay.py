"""Baseline scheduling, replay validation, and uniform experiment records."""

from __future__ import annotations

import hashlib
import json
import time

from .adapters import make_adapter
from .contracts import Mode, PolicyName
from .policies import baseline_action

RULES = ("fifo", "fixed_order", "longest_tail")
MULTI_JOB_RULES = (
    "job_fixed_order",
    "job_round_robin",
    "job_age",
    "shortest_remaining_job",
    "job_aware_longest_tail",
    "starvation_safeguard",
)
ALL_RULES = (*RULES, "spt", "lpt", *MULTI_JOB_RULES)
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


def _job_metrics(benchmark, completions, starts):
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
                "start": min((starts[item] for item in members if item in starts), default=None),
                "source_benchmark_id": record.get("source_benchmark_id"),
                "isolated_makespan": record.get("isolated_makespan"),
            }
        )
    return result


def job_metrics_from_state(benchmark, adapter, state):
    """Return per-job and aggregate metrics from one completed simulator state."""
    completions = {
        task.task_id: state.tasks[index].completed_at or 0
        for index, task in enumerate(adapter.model.tasks)
    }
    starts = {
        task.task_id: completions[task.task_id] - task.duration
        for task in benchmark.tasks
        if task.task_id in completions and not task.task_id.endswith("::__arrival__")
    }
    jobs = _job_metrics(benchmark, completions, starts)
    if jobs is None:
        return None, None
    jcts = [item["jct"] for item in jobs if item["jct"] is not None]
    slowdowns = [
        item["jct"] / item["isolated_makespan"]
        for item in jobs
        if item["jct"] is not None and item.get("isolated_makespan")
    ]
    aggregate = {
        "mean_jct": sum(jcts) / len(jcts),
        "max_jct": max(jcts),
        "weighted_completion_time": sum(
            item["completion"] * float(record.get("weight", 1.0))
            for item, record in zip(jobs, benchmark.metadata["multi_job"], strict=True)
        ),
        "mean_slowdown": sum(slowdowns) / len(slowdowns) if slowdowns else None,
        "max_slowdown": max(slowdowns) if slowdowns else None,
        "jain_fairness_slowdown": (
            (sum(slowdowns) ** 2)
            / (len(slowdowns) * sum(value * value for value in slowdowns))
            if slowdowns and any(slowdowns)
            else None
        ),
    }
    return jobs, aggregate


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
    if rule not in ALL_RULES or mode not in MODES:
        raise ValueError(f"unsupported replay configuration: {rule}/{mode}")
    adapter = make_adapter(benchmark) if adapter is None else adapter
    state = adapter.initial_state()
    actions = []
    first_seen = {}
    policy_state = {"last_job": None, "last_served": {}}
    ready_since = {}
    max_job_ready_wait = 0
    previous_jobs = frozenset()
    job_switches = 0
    candidates = divergences = 0
    context_seconds = policy_seconds = observation_seconds = step_seconds = 0.0
    while not adapter.is_finished(state):
        phase_started = time.perf_counter()
        context = adapter.decision_context(state, mode)
        context_seconds += time.perf_counter() - phase_started
        ready = context.ready
        for item in ready:
            first_seen.setdefault(item, (state.time, adapter.model.index[item]))
        for job in {
            item.split("::", 1)[0] if "::" in item else "job0" for item in ready
        }:
            ready_since.setdefault(job, state.time)
        observing = observe and (observation_limit is None or len(actions) < observation_limit)
        phase_started = time.perf_counter()
        action = baseline_action(
            adapter, state, mode, rule, first_seen, context, policy_state
        )
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
        selected_ids = (
            ()
            if action.kind == "wait"
            else (action.task_id,)
            if adapter.resource_model == "single_channel"
            else action.starts
        )
        selected_jobs = {
            item.split("::", 1)[0] if "::" in item else "job0" for item in selected_ids
        }
        if selected_jobs:
            max_job_ready_wait = max(
                max_job_ready_wait,
                max(state.time - ready_since.get(job, state.time) for job in selected_jobs),
            )
            if previous_jobs and frozenset(selected_jobs) != previous_jobs:
                job_switches += 1
            previous_jobs = frozenset(selected_jobs)
            policy_state["last_job"] = max(selected_jobs)
            for job in selected_jobs:
                policy_state["last_served"][job] = state.time
                ready_since.pop(job, None)
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
                "job_switches": job_switches,
                "max_job_ready_wait": max_job_ready_wait,
            }
        )
    return adapter, state, tuple(actions), candidates, divergences


def schedule_baseline(
    benchmark,
    rule: PolicyName = "longest_tail",
    mode: Mode = "optional_idle",
) -> dict:
    started = time.perf_counter()
    behavior = {}
    adapter, state, actions, candidates, divergences = run_baseline_loop(
        benchmark, rule, mode, metrics=behavior
    )
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
        "job_switches": behavior["job_switches"],
        "max_job_ready_wait": behavior["max_job_ready_wait"],
    }
    jobs, aggregate = job_metrics_from_state(benchmark, adapter, state)
    if jobs is not None:
        result["jobs"] = jobs
        result["job_metrics"] = aggregate
    return result


replay = schedule_baseline
