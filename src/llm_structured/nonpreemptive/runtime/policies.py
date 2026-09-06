"""Frozen shared baseline policies, including the declared WAIT rule."""

from __future__ import annotations

from .contracts import Mode, PolicyName


def _job_id(adapter, task_id: str) -> str:
    task = adapter.model.tasks[adapter.model.index[task_id]]
    labels = dict(getattr(task, "labels", ()))
    return labels.get("job_id", task_id.split("::", 1)[0] if "::" in task_id else "job0")


def _job_rank_data(adapter, state, tails):
    residual: dict[str, int] = {}
    longest_tail: dict[str, int] = {}
    arrivals: dict[str, int] = {}
    for index, task in enumerate(adapter.model.tasks):
        job = _job_id(adapter, task.task_id)
        runtime = state.tasks[index]
        remaining = (
            0
            if runtime.status == "completed"
            else runtime.remaining if runtime.status == "running" else task.duration
        )
        residual[job] = residual.get(job, 0) + remaining
        longest_tail[job] = max(longest_tail.get(job, 0), tails[task.task_id])
        if task.task_id.endswith("::__arrival__"):
            arrivals[job] = task.duration
    return residual, longest_tail, arrivals


def _rank(
    adapter,
    state,
    actions,
    policy: PolicyName,
    first_seen=None,
    tails=None,
    policy_state=None,
):
    tails = adapter.tail(state) if tails is None else tails
    first_seen = first_seen or {}

    residual, job_tails, arrivals = _job_rank_data(adapter, state, tails)
    policy_state = policy_state or {}
    available_jobs = sorted(
        {_job_id(adapter, item) for action in actions for item in (
            (action.task_id,) if adapter.resource_model == "single_channel" else action.starts
        )}
    )
    last_job = policy_state.get("last_job")
    rr_order = (
        available_jobs
        if last_job not in available_jobs
        else available_jobs[available_jobs.index(last_job) + 1 :] + available_jobs[: available_jobs.index(last_job) + 1]
    )
    rr_rank = {job: len(rr_order) - index for index, job in enumerate(rr_order)}
    last_served = policy_state.get("last_served", {})

    def key(action):
        ids = (action.task_id,) if adapter.resource_model == "single_channel" else action.starts
        jobs = tuple(sorted({_job_id(adapter, item) for item in ids}))
        if policy == "fifo":
            oldest = min(
                first_seen.get(item, (state.time, adapter.model.index[item])) for item in ids
            )
            return (-oldest[0], -oldest[1], ids)
        if policy == "fixed_order":
            return tuple(-adapter.model.index[item] for item in ids)
        durations = [
            adapter.model.remaining(state, adapter.model.index[item])
            if adapter.resource_model != "single_channel"
            else adapter.model.tasks[adapter.model.index[item]].duration
            for item in ids
        ]
        if policy == "spt":
            return (-sum(durations), ids)
        if policy == "lpt":
            return (sum(durations), ids)
        if policy == "job_fixed_order":
            return (tuple(-available_jobs.index(job) for job in jobs), sum(tails[item] for item in ids), ids)
        if policy == "job_round_robin":
            return (max(rr_rank[job] for job in jobs), sum(tails[item] for item in ids), ids)
        if policy == "job_age":
            return (-min(arrivals.get(job, 0) for job in jobs), sum(tails[item] for item in ids), ids)
        if policy == "shortest_remaining_job":
            return (-min(residual[job] for job in jobs), sum(tails[item] for item in ids), ids)
        if policy == "job_aware_longest_tail":
            return (max(job_tails[job] for job in jobs), sum(tails[item] for item in ids), ids)
        if policy == "starvation_safeguard":
            return (
                max(state.time - last_served.get(job, arrivals.get(job, 0)) for job in jobs),
                sum(tails[item] for item in ids),
                ids,
            )
        return (sum(tails[item] for item in ids), len(ids), ids)

    return max(actions, key=key)


def should_wait(adapter, state, selected, tails, active=None, next_event=None) -> bool:
    active = adapter.model.active_computes(state) if active is None else active
    if not active:
        return False
    next_event = (
        next_event
        if next_event is not None
        else (
            min(adapter.model.task_runtime(state, item).remaining for item in active)
            if adapter.resource_model == "single_channel"
            else min(state.tasks[adapter.model.index[item]].remaining for item in active)
        )
    )
    if adapter.resource_model != "single_channel":
        return next_event < min(
            adapter.model.remaining(state, adapter.model.index[item]) for item in selected.starts
        )
    duration = adapter.model.tasks[adapter.model.index[selected.task_id]].duration
    for compute in active:
        index = adapter.model.index[compute]
        if adapter.model.task_runtime(state, compute).remaining == next_event and any(
            tails[adapter.model.tasks[child].task_id] > tails[selected.task_id]
            for child, parents in enumerate(adapter.model.deps)
            if index in parents
        ):
            return next_event < duration
    return False


def _multi_greedy(adapter, state, policy, first_seen, tails, policy_state):
    from muti_channel.nonpreemptive.solver import ResourceAction

    remaining = list(adapter.model.startable_flows(state))
    selected = []
    used = set(adapter.model.occupied_resources(state))
    while remaining:
        singletons = [ResourceAction.start((item,)) for item in remaining]
        chosen = _rank(
            adapter,
            state,
            singletons,
            policy,
            first_seen,
            tails,
            policy_state,
        )
        task_id = chosen.starts[0]
        resources = adapter.model.resources[adapter.model.index[task_id]]
        if not used & resources:
            selected.append(task_id)
            used.update(resources)
        remaining.remove(task_id)
    return ResourceAction.start(tuple(sorted(selected))) if selected else None


def baseline_action(
    adapter,
    state,
    mode: Mode,
    policy: PolicyName = "longest_tail",
    first_seen=None,
    context=None,
    policy_state=None,
):
    context = context or adapter.decision_context(state, mode)
    legal = context.legal_actions
    if not legal:
        raise RuntimeError("unfinished state has no legal action")
    if adapter.resource_model != "single_channel":
        selected = _multi_greedy(
            adapter, state, policy, first_seen, context.tails, policy_state
        )
        if selected is None:
            return next(action for action in legal if action.kind == "wait")
        adapter.model.validate_action(state, selected, mode)
        if mode == "optional_idle" and should_wait(
            adapter,
            state,
            selected,
            context.tails,
            context.active_computes,
            context.next_event_distance,
        ):
            return next(action for action in legal if action.kind == "wait")
        return selected
    starts = [action for action in legal if action.kind != "wait"]
    if not starts:
        return legal[0]
    selected = _rank(
        adapter, state, starts, policy, first_seen, context.tails, policy_state
    )
    if mode == "optional_idle" and should_wait(
        adapter,
        state,
        selected,
        context.tails,
        context.active_computes,
        context.next_event_distance,
    ):
        return next(action for action in legal if action.kind == "wait")
    return selected


def longest_tail_action(adapter, state, mode, context=None):
    return baseline_action(adapter, state, mode, "longest_tail", context=context)
