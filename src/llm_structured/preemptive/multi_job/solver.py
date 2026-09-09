"""Hierarchical scheduling for multiple communication-resume DAG jobs.

This is a research module for the active v2 mainline. A multi-job
instance is represented as a disjoint union of prefixed DAGs.  Jobs never gain
cross-job precedence edges; they interact only through the shared channel.
"""

from __future__ import annotations

from dataclasses import replace
from time import perf_counter
from typing import Literal, Mapping, Sequence

from core.dag import DAG, Task
from core.execution.preemptive import (
    Action,
    PreeSingleModel,
    PreemptiveScheduleResult,
    ScheduleState,
    result_from_trace,
)
from core.trace.pree_single import assert_preemptive_trace
from core.oracle.pree_single import bounded_event_search, exact_oracle
from single_channel.complex_chain.preemptive.solver import residual_tail
from muti_channel.preemptive.solver import (
    MultiAction,
    PreeMultiModel,
)
from core.oracle.pree_multi import MultiOracleResult as MultiResult
from .contracts import (
    JobSpec,
    MultiJobInstance,
    MultiJobResult,
    MultiResourceJobResult,
)
from .compose import build_parallel_chain_job, compose_jobs
from .metrics import evaluate_multi_resource_schedule, evaluate_schedule, job_summaries, solo_optimal_jct


CandidateMode = Literal["tail", "semantic_diverse"]
GlobalMode = Literal["priority", "rollout", "shortest_job", "attained_service"]
ExactObjective = Literal["makespan", "weighted_jct"]


def _makespan_search(
    instance: MultiJobInstance,
    *,
    max_states: int = 500_000,
    time_limit_s: float | None = None,
) -> MultiJobResult:
    result = exact_oracle(
        instance.dag,
        max_states=max_states,
        time_limit_s=time_limit_s,
    )
    return evaluate_schedule(instance, result)


def _hierarchical_search(
    instance: MultiJobInstance,
    *,
    candidate_width: int | None,
    candidate_mode: CandidateMode = "tail",
    objective: ExactObjective = "makespan",
    max_states: int = 500_000,
    time_limit_s: float | None = None,
) -> MultiJobResult:
    """Exact search inside the action space exposed by the per-job interface."""

    if candidate_width is not None and candidate_width < 1:
        raise ValueError("candidate_width must be positive or None")
    if objective not in {"makespan", "weighted_jct"}:
        raise ValueError(f"unknown exact objective: {objective}")
    model = PreeSingleModel(instance.dag)
    candidate_counts: dict[tuple, int] = {}

    def key(state: ScheduleState) -> tuple:
        return tuple((runtime.status, runtime.remaining) for runtime in state.tasks)

    def exposed_actions(state: ScheduleState) -> tuple[Action, ...]:
        eligible = model.eligible_communications(state)
        if not eligible:
            return (Action.wait(),)
        tail = residual_tail(model, state)
        nominees = []
        for _job_id, task_ids in sorted(_eligible_by_job(instance, eligible).items()):
            nominees.extend(_nominate(
                model,
                state,
                instance,
                task_ids,
                tail,
                candidate_width,
                candidate_mode,
            ))
        actions = tuple(Action.run(task_id) for task_id in nominees)
        candidate_counts[key(state)] = len(actions)
        return actions

    def active_weight(state: ScheduleState) -> float:
        value = 0.0
        for job in instance.jobs:
            release = f"{job.job_id}::__arrival__"
            if model.task_runtime(state, release).status != "completed":
                continue
            original = [
                task_id
                for task_id, owner in instance.task_job.items()
                if owner == job.job_id
                and instance.original_task[task_id] != "__arrival__"
            ]
            if any(
                model.task_runtime(state, task_id).status != "completed"
                for task_id in original
            ):
                value += job.weight
        return value

    def transition_cost(before: ScheduleState, _action: Action, after: ScheduleState) -> float:
        elapsed = after.time - before.time
        return elapsed if objective == "makespan" else elapsed * active_weight(before)

    result = bounded_event_search(
        model,
        exposed_actions,
        key,
        max_states=max_states,
        time_limit_s=time_limit_s,
        transition_cost=transition_cost,
    )
    return evaluate_schedule(
        instance,
        result,
        candidate_evaluations=result.stats.explored_states,
        candidate_counts=tuple(candidate_counts.values()),
    )


exact_makespan = _makespan_search
exact_hierarchical = _hierarchical_search


def schedule_hierarchical(
    instance: MultiJobInstance,
    *,
    candidate_width: int | None = 1,
    candidate_mode: CandidateMode = "tail",
    global_mode: GlobalMode = "rollout",
    adaptive: bool = False,
    max_adaptive_width: int = 4,
) -> MultiJobResult:
    """Run a two-level scheduler with at most ``K`` nominees per ready job.

    ``candidate_width=None`` exposes every ready flow and is the flat-search
    endpoint.  Adaptive mode expands K when the local top-two scores are close
    or when several jobs simultaneously have ready communication.
    """

    if candidate_width is not None and candidate_width < 1:
        raise ValueError("candidate_width must be positive or None")
    model = PreeSingleModel(instance.dag)
    state = model.initial_state()
    actions: list[Action] = []
    candidate_counts: list[int] = []
    evaluations = 0
    attained = {job.job_id: 0 for job in instance.jobs}
    last_service = {job.job_id: 0 for job in instance.jobs}
    while not model.is_finished(state):
        eligible = model.eligible_communications(state)
        if not eligible:
            action = Action.wait()
            candidate_counts.append(0)
        else:
            tail = residual_tail(model, state)
            by_job = _eligible_by_job(instance, eligible)
            nominees: list[str] = []
            for job_id, task_ids in sorted(by_job.items()):
                width = candidate_width
                if adaptive and width is not None:
                    scores = sorted(
                        (_tail_score(model, state, tail, task_id) for task_id in task_ids),
                        reverse=True,
                    )
                    uncertain = (
                        len(scores) >= 2
                        and scores[0] - scores[1] <= max(1, scores[0] // 10)
                    )
                    contended = len(by_job) >= 2
                    if uncertain or contended:
                        width = max_adaptive_width
                nominees.extend(_nominate(
                    model,
                    state,
                    instance,
                    task_ids,
                    tail,
                    width,
                    candidate_mode,
                ))
            candidate_counts.append(len(nominees))
            if global_mode == "priority":
                selected = min(
                    nominees,
                    key=lambda task_id: _global_priority_key(
                        model,
                        state,
                        instance,
                        tail,
                        task_id,
                        attained,
                        last_service,
                    ),
                )
            elif global_mode in {"shortest_job", "attained_service"}:
                summaries = {
                    summary.job_id: summary
                    for summary in job_summaries(
                        instance,
                        model,
                        state,
                        attained_service=attained,
                        last_service=last_service,
                    )
                }
                weights = {job.job_id: job.weight for job in instance.jobs}

                def job_key(task_id: str) -> tuple:
                    owner = instance.task_job[task_id]
                    summary = summaries[owner]
                    local = -_tail_score(model, state, tail, task_id)
                    if global_mode == "shortest_job":
                        return (
                            summary.remaining_communication,
                            summary.residual_critical_path,
                            local,
                            task_id,
                        )
                    return (
                        summary.attained_service / weights[owner],
                        -summary.service_vacation,
                        local,
                        task_id,
                    )

                selected = min(nominees, key=job_key)
            elif global_mode == "rollout":
                scored = []
                for task_id in nominees:
                    first = Action.run(task_id)
                    after = model.step(state, first).after
                    finish = _complete_flat_longest_tail(model, after).time
                    scored.append((finish, task_id))
                    evaluations += 1
                selected = min(scored)[1]
            else:
                raise ValueError(f"unknown global mode: {global_mode}")
            action = Action.run(selected)
        before_time = state.time
        transition = model.step(state, action)
        state = transition.after
        actions.append(action)
        if action.kind == "run" and action.task_id is not None:
            owner = instance.task_job[action.task_id]
            attained[owner] += state.time - before_time
            last_service[owner] = state.time
    trace = model.run(actions)
    assert_preemptive_trace(model, trace)
    result = result_from_trace(trace)
    return evaluate_schedule(
        instance,
        result,
        candidate_evaluations=evaluations,
        candidate_counts=candidate_counts,
    )


def teacher_candidate_recall(
    instance: MultiJobInstance,
    teacher: PreemptiveScheduleResult,
    widths: Sequence[int] = (1, 2, 4),
    *,
    candidate_mode: CandidateMode = "tail",
) -> dict[int, float]:
    """Fraction of teacher flow decisions retained by per-job top-K."""

    hits = {width: 0 for width in widths}
    decisions = 0
    model = PreeSingleModel(instance.dag)
    state = model.initial_state()
    for transition in teacher.trace.transitions:
        action = transition.action
        if action.kind == "run" and action.task_id is not None:
            decisions += 1
            eligible = model.eligible_communications(state)
            owner = instance.task_job[action.task_id]
            local = tuple(
                task_id for task_id in eligible
                if instance.task_job[task_id] == owner
            )
            tail = residual_tail(model, state)
            for width in widths:
                nominated = _nominate(
                    model,
                    state,
                    instance,
                    local,
                    tail,
                    width,
                    candidate_mode,
                )
                hits[width] += action.task_id in nominated
        state = model.step(state, action).after
    return {
        width: hits[width] / decisions if decisions else 1.0
        for width in widths
    }


def build_top1_counterexample() -> MultiJobInstance:
    """A fixed two-job instance where local top-1 removes an optimal action."""

    job_a = build_parallel_chain_job(
        "top1_job_a",
        ((1, (1, 4), (3, 5)), (1, (1, 3), (5, 5))),
    )
    job_b = build_parallel_chain_job(
        "top1_job_b",
        ((0, (2, 1), (3, 2)), (1, (1, 1), (5, 5))),
    )
    return compose_jobs((JobSpec("A", job_a), JobSpec("B", job_b)))


def build_top1_attack_suite() -> tuple[MultiJobInstance, ...]:
    """Fixed strict K=1 attacks found by seeded search and verified by Exact."""

    shapes = (
        (((1, (1, 4), (3, 5)), (1, (1, 3), (5, 5))), ((0, (2, 1), (3, 2)), (1, (1, 1), (5, 5)))),
        (((2, (1, 2), (5, 2)), (2, (1, 3), (1, 0))), ((0, (3, 1), (4, 4)), (1, (1, 2), (3, 2)))),
        (((0, (3, 3), (2, 1)), (1, (1, 1), (2, 0))), ((2, (3, 4), (5, 3)), (2, (1, 2), (3, 4)))),
        (((0, (2, 1), (1, 1)), (1, (1, 3), (5, 2))), ((2, (1, 4), (5, 5)), (2, (1, 4), (2, 5)))),
    )
    return tuple(
        compose_jobs((
            JobSpec("A", build_parallel_chain_job(f"attack_{index}_a", first)),
            JobSpec("B", build_parallel_chain_job(f"attack_{index}_b", second)),
        ))
        for index, (first, second) in enumerate(shapes)
    )


def build_candidate_compression_case() -> MultiJobInstance:
    """Three ready chains per job; K=2 preserves optimum with fewer states."""

    first = ((0, (2, 1), (0, 3)), (0, (3, 2), (0, 3)), (1, (2, 2), (1, 0)))
    second = ((0, (1, 2), (0, 0)), (0, (3, 1), (0, 2)), (1, (3, 1), (1, 1)))
    return compose_jobs((
        JobSpec("A", build_parallel_chain_job("compression_a", first)),
        JobSpec("B", build_parallel_chain_job("compression_b", second)),
    ))


def schedule_multi_resource_hierarchical(
    instance: MultiJobInstance,
    resources: Mapping[str, frozenset[str]],
    *,
    candidate_width: int | None = 1,
) -> MultiResult:
    """Nominate K flows per Job, then greedily build a compatible global pack."""

    if candidate_width is not None and candidate_width < 1:
        raise ValueError("candidate_width must be positive or None")
    model = PreeMultiModel(instance.dag, dict(resources))
    state = model.initial_state()
    actions: list[MultiAction] = []
    while not model.finished(state):
        state, _forced_idle = model.normalize_decision_state(state)
        if model.finished(state):
            break
        eligible = model.eligible(state)
        tail = _multi_residual_tail(model, state)
        nominees = []
        for _job_id, task_ids in sorted(_eligible_by_job(instance, eligible).items()):
            ranked = sorted(
                task_ids,
                key=lambda task_id: (
                    -_multi_tail_score(model, state, tail, task_id),
                    task_id,
                ),
            )
            nominees.extend(
                ranked if candidate_width is None else ranked[:candidate_width]
            )
        selected: list[str] = []
        for task_id in sorted(
            nominees,
            key=lambda item: (
                -_multi_tail_score(model, state, tail, item),
                item,
            ),
        ):
            if model.compatible((*selected, task_id)):
                selected.append(task_id)
        # Candidate compression may rank the pack, but the v2 execution
        # contract does not permit it to leave a compatible resource idle.
        for task_id in sorted(
            (task_id for task_id in eligible if task_id not in selected),
            key=lambda item: (
                -_multi_tail_score(model, state, tail, item),
                item,
            ),
        ):
            if model.compatible((*selected, task_id)):
                selected.append(task_id)
        action = MultiAction(tuple(sorted(selected)))
        actions.append(action)
        state = model.step(state, action)
    trace = model.run(actions)
    from core.trace.pree_multi import assert_preemptive_multi_trace

    assert_preemptive_multi_trace(model.dag, model.resources, trace)
    return MultiResult(
        state.time,
        tuple(actions),
        len(actions),
        _count_multi_preemptions(model, actions),
        trace=trace,
    )


def schedule_multi_resource_policy(
    instance: MultiJobInstance,
    resources: Mapping[str, frozenset[str]],
    *,
    job_policy: Literal["flat_lt", "shortest_remaining", "weighted_lt", "fcfs", "attained_service"] = "flat_lt",
    solo_completion: Mapping[str, int] | None = None,
) -> MultiResourceJobResult:
    """Choose a job-aware ordering, then maximal-complete across every job."""

    model = PreeMultiModel(instance.dag, dict(resources))
    state = model.initial_state()
    actions: list[MultiAction] = []
    attained = {job.job_id: 0 for job in instance.jobs}
    last_service = {job.job_id: job.arrival for job in instance.jobs}
    jobs = {job.job_id: job for job in instance.jobs}
    while not model.finished(state):
        state, _idle = model.normalize_decision_state(state)
        if model.finished(state):
            break
        eligible = model.eligible(state)
        tail = _multi_residual_tail(model, state)
        remaining = {
            job_id: sum(
                state.tasks[model.index[item]].remaining or model.task_map[item].duration
                for item, owner in instance.task_job.items()
                if owner == job_id
                and model.task_map[item].kind == "comm"
                and state.tasks[model.index[item]].status != "completed"
            )
            for job_id in jobs
        }
        def key(item: str):
            owner = instance.task_job[item]
            local = -_multi_tail_score(model, state, tail, item)
            if job_policy == "flat_lt":
                return (local, item)
            if job_policy == "shortest_remaining":
                return (remaining[owner], local, item)
            if job_policy == "weighted_lt":
                return (local * jobs[owner].weight, item)
            if job_policy == "fcfs":
                return (jobs[owner].arrival, local, item)
            if job_policy == "attained_service":
                return (attained[owner] / jobs[owner].weight, -(state.time-last_service[owner]), local, item)
            raise ValueError(f"unknown job policy: {job_policy}")
        selected = []
        for item in sorted(eligible, key=key):
            if model.compatible((*selected, item)):
                selected.append(item)
        action = MultiAction(tuple(sorted(selected)))
        before = state.time
        state = model.step(state, action)
        delta = state.time - before
        for item in action.communications:
            owner = instance.task_job[item]
            attained[owner] += delta
            last_service[owner] = state.time
        actions.append(action)
    trace = model.run(actions)
    from core.trace.pree_multi import assert_preemptive_multi_trace
    assert_preemptive_multi_trace(model.dag, model.resources, trace)
    schedule = MultiResult(state.time, tuple(actions), len(actions), _count_multi_preemptions(model, actions), trace=trace)
    return evaluate_multi_resource_schedule(instance, schedule, solo_completion=solo_completion)


def build_multi_resource_top1_counterexample(
) -> tuple[MultiJobInstance, dict[str, frozenset[str]]]:
    """K=1 hides a private-link flow and leaves that link idle."""

    job_a = DAG(
        "resource_job_a",
        (
            Task("shared", "comm", 4, labels=(("task_role", "PP"),)),
            Task("shared_tail", "compute", 10, ("shared",), labels=(("task_role", "PP_TAIL"),)),
            Task("private", "comm", 8, labels=(("task_role", "DP"),)),
            Task("private_tail", "compute", 9, ("private",), labels=(("task_role", "DP_TAIL"),)),
        ), context=(("category", "multi_job_fixture"),),
    )
    job_b = DAG(
        "resource_job_b",
        (
            Task("shared", "comm", 4, labels=(("task_role", "PP"),)),
            Task("shared_tail", "compute", 11, ("shared",), labels=(("task_role", "PP_TAIL"),)),
        ), context=(("category", "multi_job_fixture"),),
    )
    instance = compose_jobs((JobSpec("A", job_a), JobSpec("B", job_b)))
    return instance, {
        "A::shared": frozenset({"uplink"}),
        "A::private": frozenset({"private"}),
        "B::shared": frozenset({"uplink"}),
    }


def _nominate(
    model: PreeSingleModel,
    state: ScheduleState,
    instance: MultiJobInstance,
    task_ids: Sequence[str],
    tail: Mapping[str, int],
    width: int | None,
    mode: CandidateMode,
) -> tuple[str, ...]:
    if width is None or width >= len(task_ids):
        return tuple(sorted(task_ids))
    ranked = sorted(task_ids, key=lambda task_id: (-_tail_score(model, state, tail, task_id), task_id))
    if mode == "tail":
        return tuple(ranked[:width])
    if mode != "semantic_diverse":
        raise ValueError(f"unknown candidate mode: {mode}")
    selected: list[str] = []
    def add(task_id: str) -> None:
        if task_id not in selected and len(selected) < width:
            selected.append(task_id)
    add(ranked[0])
    continuation = [task_id for task_id in ranked if model.task_runtime(state, task_id).status == "suspended"]
    if continuation:
        add(continuation[0])
    by_role: dict[str, str] = {}
    for task_id in ranked:
        role = model.task_map[task_id].label_map().get("task_role", "") or "OTHER"
        by_role.setdefault(role, task_id)
    for _role, task_id in sorted(by_role.items(), key=lambda item: (-_tail_score(model, state, tail, item[1]), item[0])):
        add(task_id)
    for task_id in ranked:
        add(task_id)
    return tuple(selected)


def _tail_score(model: PreeSingleModel, state: ScheduleState, tail: Mapping[str, int], task_id: str) -> int:
    runtime = model.task_runtime(state, task_id)
    return tail[task_id] - (runtime.remaining or model.task_map[task_id].duration)


def _global_priority_key(model, state, instance, tail, task_id, attained, last_service):
    owner = instance.task_job[task_id]
    return (-_tail_score(model, state, tail, task_id), -(state.time - last_service.get(owner, 0)), attained.get(owner, 0), task_id)


def _complete_flat_longest_tail(model: PreeSingleModel, state: ScheduleState) -> ScheduleState:
    while not model.is_finished(state):
        eligible = model.eligible_communications(state)
        if not eligible:
            action = Action.wait()
        else:
            tail = residual_tail(model, state)
            action = Action.run(min(eligible, key=lambda task_id: (-_tail_score(model, state, tail, task_id), task_id)))
        state = model.step(state, action).after
    return state


def _eligible_by_job(instance: MultiJobInstance, eligible: Sequence[str]) -> dict[str, tuple[str, ...]]:
    values: dict[str, list[str]] = {}
    for task_id in eligible:
        values.setdefault(instance.task_job[task_id], []).append(task_id)
    return {job_id: tuple(task_ids) for job_id, task_ids in values.items()}


def _multi_residual_tail(model, state) -> dict[str, int]:
    children = {task_id: [] for task_id in model.task_ids}
    for task in model.tasks:
        for dependency in task.deps:
            children[dependency].append(task.task_id)
    tail: dict[str, int] = {}
    for task_id in reversed(model.task_ids):
        runtime = state.tasks[model.index[task_id]]
        own = 0 if runtime.status == "completed" else runtime.remaining or model.tasks[model.index[task_id]].duration
        tail[task_id] = own + max((tail[child] for child in children[task_id]), default=0)
    return tail


def _multi_tail_score(model, state, tail: Mapping[str, int], task_id: str) -> int:
    runtime = state.tasks[model.index[task_id]]
    return tail[task_id] - (runtime.remaining or model.tasks[model.index[task_id]].duration)


def _count_multi_preemptions(model: PreeMultiModel, actions: Sequence[MultiAction]) -> int:
    count = 0
    previous: set[str] = set()
    state = model.initial_state()
    for action in actions:
        state, _forced_idle = model.normalize_decision_state(state)
        current = set(action.communications)
        after = model.step(state, action)
        count += sum(after.tasks[model.index[task_id]].status != "completed" for task_id in previous - current)
        previous, state = current, after
    return count



