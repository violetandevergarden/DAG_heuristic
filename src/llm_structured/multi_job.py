"""Hierarchical scheduling for multiple communication-resume DAG jobs.

This is a research module for the active v2 mainline. A multi-job
instance is represented as a disjoint union of prefixed DAGs.  Jobs never gain
cross-job precedence edges; they interact only through the shared channel.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache
from statistics import mean
from time import perf_counter
from typing import Literal, Mapping, Sequence

from core.dag import BenchmarkDAG, BenchTask
from core.execution.preemptive import (
    Action,
    PreemptiveDAGModel,
    PreemptiveScheduleResult,
    ScheduleState,
    result_from_trace,
)
from core.trace.preemptive import assert_preemptive_trace
from single_channel.complex_chain.preemptive.solver import exact_oracle, residual_tail
from muti_channel.preemptive.solver import (
    MultiAction,
    MultiResult,
    PreemptiveMultiResourceModel,
)


CandidateMode = Literal["tail", "semantic_diverse"]
GlobalMode = Literal["priority", "rollout", "shortest_job", "attained_service"]
ExactObjective = Literal["makespan", "weighted_jct"]


@dataclass(frozen=True)
class JobSpec:
    job_id: str
    dag: BenchmarkDAG
    arrival: int = 0
    weight: float = 1.0

    def __post_init__(self) -> None:
        if not self.job_id or "::" in self.job_id:
            raise ValueError("job_id must be non-empty and may not contain '::'")
        if self.arrival < 0:
            raise ValueError("arrival must be non-negative")
        if self.weight <= 0:
            raise ValueError("weight must be positive")


@dataclass(frozen=True)
class MultiJobInstance:
    dag: BenchmarkDAG
    jobs: tuple[JobSpec, ...]
    task_job: Mapping[str, str]
    original_task: Mapping[str, str]


@dataclass(frozen=True)
class JobOutcome:
    job_id: str
    arrival: int
    completion: int
    jct: int
    weight: float
    slowdown: float | None


@dataclass(frozen=True)
class MultiJobResult:
    schedule: PreemptiveScheduleResult
    jobs: tuple[JobOutcome, ...]
    weighted_jct: float
    mean_jct: float
    max_slowdown: float | None
    candidate_evaluations: int = 0
    candidate_counts: tuple[int, ...] = ()

    @property
    def makespan(self) -> int:
        return self.schedule.makespan


@dataclass(frozen=True)
class MultiResourceJobResult:
    schedule: MultiResult
    jobs: tuple[JobOutcome, ...]
    weighted_jct: float
    mean_jct: float
    max_slowdown: float | None
    jain_slowdown_fairness: float | None

    @property
    def makespan(self) -> int:
        return self.schedule.makespan


@dataclass(frozen=True)
class JobSummary:
    job_id: str
    remaining_communication: int
    residual_critical_path: int
    ready_count: int
    active_compute_count: int
    attained_service: int
    service_vacation: int


def compose_jobs(specs: Sequence[JobSpec]) -> MultiJobInstance:
    """Prefix and combine jobs while encoding arrival as a release compute."""

    jobs = tuple(specs)
    if not jobs:
        raise ValueError("at least one job is required")
    if len({job.job_id for job in jobs}) != len(jobs):
        raise ValueError("job IDs must be unique")
    tasks: list[BenchTask] = []
    task_job: dict[str, str] = {}
    original_task: dict[str, str] = {}
    for job in jobs:
        errors = job.dag.validate()
        if errors:
            raise ValueError(f"invalid job DAG {job.job_id}: {errors}")
        release = f"{job.job_id}::__arrival__"
        tasks.append(BenchTask(release, "compute", job.arrival, role="JOB_ARRIVAL"))
        task_job[release] = job.job_id
        original_task[release] = "__arrival__"
        for task in job.dag.tasks:
            task_id = _prefixed(job.job_id, task.task_id)
            dependencies = tuple(_prefixed(job.job_id, dep) for dep in task.deps)
            if not task.deps:
                dependencies = (release,)
            tasks.append(BenchTask(
                task_id,
                task.kind,
                task.duration,
                dependencies,
                role=task.role,
                cut=task.cut,
            ))
            task_job[task_id] = job.job_id
            original_task[task_id] = task.task_id
    dag = BenchmarkDAG(
        "multi_job__" + "__".join(job.job_id for job in jobs),
        "multi_job",
        tuple(tasks),
        "Disjoint job DAGs coupled only by the shared communication channel.",
        tuple((f"arrival:{job.job_id}", str(job.arrival)) for job in jobs),
    )
    errors = dag.validate()
    if errors:
        raise ValueError(f"invalid composed DAG: {errors}")
    return MultiJobInstance(dag, jobs, task_job, original_task)


def evaluate_schedule(
    instance: MultiJobInstance,
    schedule: PreemptiveScheduleResult,
    *,
    solo_completion: Mapping[str, int] | None = None,
    candidate_evaluations: int = 0,
    candidate_counts: Sequence[int] = (),
) -> MultiJobResult:
    """Compute per-job completion, JCT, weighted JCT, and slowdown."""

    model = PreemptiveDAGModel(instance.dag)
    outcomes: list[JobOutcome] = []
    by_id = {job.job_id: job for job in instance.jobs}
    for job_id, job in by_id.items():
        task_ids = [
            task_id
            for task_id, owner in instance.task_job.items()
            if owner == job_id and instance.original_task[task_id] != "__arrival__"
        ]
        completion = max(
            model.task_runtime(schedule.trace.final_state, task_id).completed_at or 0
            for task_id in task_ids
        )
        jct = completion - job.arrival
        denominator = solo_completion.get(job_id) if solo_completion else None
        slowdown = jct / denominator if denominator else None
        outcomes.append(JobOutcome(
            job_id,
            job.arrival,
            completion,
            jct,
            job.weight,
            slowdown,
        ))
    outcomes.sort(key=lambda item: item.job_id)
    total_weight = sum(item.weight for item in outcomes)
    slowdowns = [item.slowdown for item in outcomes if item.slowdown is not None]
    return MultiJobResult(
        schedule,
        tuple(outcomes),
        sum(item.weight * item.jct for item in outcomes) / total_weight,
        mean(item.jct for item in outcomes),
        max(slowdowns) if slowdowns else None,
        candidate_evaluations,
        tuple(candidate_counts),
    )


def exact_makespan(
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


def exact_hierarchical(
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
    model = PreemptiveDAGModel(instance.dag)
    initial = model.initial_state()
    representatives: dict[tuple, ScheduleState] = {}
    started = perf_counter()
    explored = 0

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
        return tuple(Action.run(task_id) for task_id in nominees)

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

    @lru_cache(maxsize=None)
    def value(state_key: tuple) -> float:
        nonlocal explored
        explored += 1
        if explored > max_states:
            raise RuntimeError("hierarchical exact oracle exceeded state limit")
        if time_limit_s is not None and perf_counter() - started > time_limit_s:
            raise TimeoutError("hierarchical exact oracle exceeded time limit")
        state = representatives[state_key]
        if model.is_finished(state):
            return 0
        best: float | None = None
        for action in exposed_actions(state):
            after = model.step(state, action).after
            child = key(after)
            representatives.setdefault(child, after)
            elapsed = after.time - state.time
            immediate = elapsed if objective == "makespan" else elapsed * active_weight(state)
            candidate = immediate + value(child)
            best = candidate if best is None else min(best, candidate)
        if best is None:
            raise RuntimeError("unfinished state has no exposed action")
        return best

    state = initial
    root = key(state)
    representatives[root] = state
    value(root)
    actions: list[Action] = []
    candidate_counts: list[int] = []
    while not model.is_finished(state):
        legal = exposed_actions(state)
        candidate_counts.append(sum(action.kind == "run" for action in legal))
        candidates = []
        for action in legal:
            after = model.step(state, action).after
            child = key(after)
            representatives.setdefault(child, after)
            elapsed = after.time - state.time
            immediate = elapsed if objective == "makespan" else elapsed * active_weight(state)
            candidates.append((
                immediate + value(child),
                action.kind,
                action.task_id or "",
                action,
                after,
            ))
        _cost, _kind, _task_id, action, state = min(candidates)
        actions.append(action)
    trace = model.run(actions)
    assert_preemptive_trace(model, trace)
    result = replace(result_from_trace(trace), explored_states=explored)
    return evaluate_schedule(
        instance,
        result,
        candidate_evaluations=explored,
        candidate_counts=candidate_counts,
    )


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
    model = PreemptiveDAGModel(instance.dag)
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
    model = PreemptiveDAGModel(instance.dag)
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


def job_summaries(
    instance: MultiJobInstance,
    model: PreemptiveDAGModel,
    state: ScheduleState,
    *,
    attained_service: Mapping[str, int] | None = None,
    last_service: Mapping[str, int] | None = None,
) -> tuple[JobSummary, ...]:
    tail = residual_tail(model, state)
    attained_service = attained_service or {}
    last_service = last_service or {}
    eligible = set(model.eligible_communications(state))
    summaries = []
    for job in instance.jobs:
        task_ids = [task_id for task_id, owner in instance.task_job.items() if owner == job.job_id]
        unfinished = [
            task_id for task_id in task_ids
            if model.task_runtime(state, task_id).status != "completed"
        ]
        comm_work = sum(
            model.task_runtime(state, task_id).remaining
            or model.task_map[task_id].duration
            for task_id in unfinished
            if model.task_map[task_id].kind == "comm"
        )
        critical = max((tail[task_id] for task_id in unfinished), default=0)
        active_compute = sum(
            model.task_map[task_id].kind == "compute"
            and model.task_runtime(state, task_id).status == "running"
            for task_id in task_ids
        )
        last = last_service.get(job.job_id, job.arrival)
        summaries.append(JobSummary(
            job.job_id,
            comm_work,
            critical,
            sum(task_id in eligible for task_id in task_ids),
            active_compute,
            attained_service.get(job.job_id, 0),
            max(0, state.time - last),
        ))
    return tuple(summaries)


def solo_optimal_jct(
    instance: MultiJobInstance,
    *,
    max_states: int = 500_000,
    time_limit_s: float | None = None,
) -> dict[str, int]:
    """Return each original Job's isolated optimal duration, excluding arrival."""

    return {
        job.job_id: exact_oracle(
            job.dag,
            max_states=max_states,
            time_limit_s=time_limit_s,
        ).makespan
        for job in instance.jobs
    }


def build_top1_counterexample() -> MultiJobInstance:
    """A fixed two-job instance where local top-1 removes an optimal action."""

    job_a = build_parallel_chain_job(
        "top1_job_a",
        (
            (1, (1, 4), (3, 5)),
            (1, (1, 3), (5, 5)),
        ),
    )
    job_b = build_parallel_chain_job(
        "top1_job_b",
        (
            (0, (2, 1), (3, 2)),
            (1, (1, 1), (5, 5)),
        ),
    )
    return compose_jobs((JobSpec("A", job_a), JobSpec("B", job_b)))


def build_top1_attack_suite() -> tuple[MultiJobInstance, ...]:
    """Fixed strict K=1 attacks found by seeded search and verified by Exact."""

    shapes = (
        (
            (
                (1, (1, 4), (3, 5)),
                (1, (1, 3), (5, 5)),
            ),
            (
                (0, (2, 1), (3, 2)),
                (1, (1, 1), (5, 5)),
            ),
        ),
        (
            (
                (2, (1, 2), (5, 2)),
                (2, (1, 3), (1, 0)),
            ),
            (
                (0, (3, 1), (4, 4)),
                (1, (1, 2), (3, 2)),
            ),
        ),
        (
            (
                (0, (3, 3), (2, 1)),
                (1, (1, 1), (2, 0)),
            ),
            (
                (2, (3, 4), (5, 3)),
                (2, (1, 2), (3, 4)),
            ),
        ),
        (
            (
                (0, (2, 1), (1, 1)),
                (1, (1, 3), (5, 2)),
            ),
            (
                (2, (1, 4), (5, 5)),
                (2, (1, 4), (2, 5)),
            ),
        ),
    )
    return tuple(
        compose_jobs((
            JobSpec("A", build_parallel_chain_job(f"attack_{index}_a", first)),
            JobSpec("B", build_parallel_chain_job(f"attack_{index}_b", second)),
        ))
        for index, (first, second) in enumerate(shapes)
    )


def build_candidate_compression_case() -> MultiJobInstance:
    """Three ready chains per Job; K=2 preserves optimum with fewer states."""

    first = (
        (0, (2, 1), (0, 3)),
        (0, (3, 2), (0, 3)),
        (1, (2, 2), (1, 0)),
    )
    second = (
        (0, (1, 2), (0, 0)),
        (0, (3, 1), (0, 2)),
        (1, (3, 1), (1, 1)),
    )
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
    model = PreemptiveMultiResourceModel(instance.dag, dict(resources))
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
    from muti_channel.preemptive.trace import assert_multi_resource_trace

    assert_multi_resource_trace(model.dag, model.resources, trace)
    return MultiResult(
        state.time,
        tuple(actions),
        len(actions),
        _count_multi_preemptions(model, actions),
        trace=trace,
    )


def evaluate_multi_resource_schedule(
    instance: MultiJobInstance,
    schedule: MultiResult,
    *,
    solo_completion: Mapping[str, int] | None = None,
) -> MultiResourceJobResult:
    if schedule.trace is None:
        raise ValueError("multi-resource schedule must retain a trace")
    completed_at = {
        interval.task_id: interval.end for interval in schedule.trace.intervals
    }
    outcomes = []
    for job in instance.jobs:
        task_ids = [
            item for item, owner in instance.task_job.items()
            if owner == job.job_id and instance.original_task[item] != "__arrival__"
        ]
        completion = max(completed_at.get(item, 0) for item in task_ids)
        jct = completion - job.arrival
        denominator = solo_completion.get(job.job_id) if solo_completion else None
        outcomes.append(JobOutcome(job.job_id, job.arrival, completion, jct, job.weight, jct / denominator if denominator else None))
    outcomes.sort(key=lambda item: item.job_id)
    total_weight = sum(item.weight for item in outcomes)
    slowdowns = [item.slowdown for item in outcomes if item.slowdown is not None]
    fairness = None
    if slowdowns and sum(value * value for value in slowdowns):
        fairness = sum(slowdowns) ** 2 / (len(slowdowns) * sum(value * value for value in slowdowns))
    return MultiResourceJobResult(
        schedule,
        tuple(outcomes),
        sum(item.weight * item.jct for item in outcomes) / total_weight,
        mean(item.jct for item in outcomes),
        max(slowdowns) if slowdowns else None,
        fairness,
    )


def schedule_multi_resource_policy(
    instance: MultiJobInstance,
    resources: Mapping[str, frozenset[str]],
    *,
    job_policy: Literal["flat_lt", "shortest_remaining", "weighted_lt", "fcfs", "attained_service"] = "flat_lt",
    solo_completion: Mapping[str, int] | None = None,
) -> MultiResourceJobResult:
    """Choose a job-aware ordering, then maximal-complete across every job."""

    model = PreemptiveMultiResourceModel(instance.dag, dict(resources))
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
    from muti_channel.preemptive.trace import assert_multi_resource_trace
    assert_multi_resource_trace(model.dag, model.resources, trace)
    schedule = MultiResult(state.time, tuple(actions), len(actions), _count_multi_preemptions(model, actions), trace=trace)
    return evaluate_multi_resource_schedule(instance, schedule, solo_completion=solo_completion)


def build_multi_resource_top1_counterexample(
) -> tuple[MultiJobInstance, dict[str, frozenset[str]]]:
    """K=1 hides a private-link flow and leaves that link idle."""

    job_a = BenchmarkDAG(
        "resource_job_a",
        "multi_job_fixture",
        (
            BenchTask("shared", "comm", 4, role="PP"),
            BenchTask("shared_tail", "compute", 10, ("shared",), role="PP_TAIL"),
            BenchTask("private", "comm", 8, role="DP"),
            BenchTask("private_tail", "compute", 9, ("private",), role="DP_TAIL"),
        ),
    )
    job_b = BenchmarkDAG(
        "resource_job_b",
        "multi_job_fixture",
        (
            BenchTask("shared", "comm", 4, role="PP"),
            BenchTask("shared_tail", "compute", 11, ("shared",), role="PP_TAIL"),
        ),
    )
    instance = compose_jobs((JobSpec("A", job_a), JobSpec("B", job_b)))
    resources = {
        "A::shared": frozenset({"uplink"}),
        "A::private": frozenset({"private"}),
        "B::shared": frozenset({"uplink"}),
    }
    return instance, resources


def _nominate(
    model: PreemptiveDAGModel,
    state: ScheduleState,
    instance: MultiJobInstance,
    task_ids: Sequence[str],
    tail: Mapping[str, int],
    width: int | None,
    mode: CandidateMode,
) -> tuple[str, ...]:
    if width is None or width >= len(task_ids):
        return tuple(sorted(task_ids))
    tail_ranked = sorted(
        task_ids,
        key=lambda task_id: (
            -_tail_score(model, state, tail, task_id),
            task_id,
        ),
    )
    if mode == "tail":
        return tuple(tail_ranked[:width])
    if mode != "semantic_diverse":
        raise ValueError(f"unknown candidate mode: {mode}")
    selected: list[str] = []

    def add(task_id: str) -> None:
        if task_id not in selected and len(selected) < width:
            selected.append(task_id)

    add(tail_ranked[0])
    continuation = [
        task_id for task_id in tail_ranked
        if model.task_runtime(state, task_id).status == "suspended"
    ]
    if continuation:
        add(continuation[0])
    by_role: dict[str, str] = {}
    for task_id in tail_ranked:
        role = model.task_map[task_id].role or "OTHER"
        by_role.setdefault(role, task_id)
    for _role, task_id in sorted(
        by_role.items(),
        key=lambda item: (-_tail_score(model, state, tail, item[1]), item[0]),
    ):
        add(task_id)
    for task_id in tail_ranked:
        add(task_id)
    return tuple(selected)


def _tail_score(
    model: PreemptiveDAGModel,
    state: ScheduleState,
    tail: Mapping[str, int],
    task_id: str,
) -> int:
    runtime = model.task_runtime(state, task_id)
    own = runtime.remaining or model.task_map[task_id].duration
    return tail[task_id] - own


def _global_priority_key(
    model: PreemptiveDAGModel,
    state: ScheduleState,
    instance: MultiJobInstance,
    tail: Mapping[str, int],
    task_id: str,
    attained: Mapping[str, int],
    last_service: Mapping[str, int],
) -> tuple[int, int, int, str]:
    owner = instance.task_job[task_id]
    vacation = state.time - last_service.get(owner, 0)
    return (
        -_tail_score(model, state, tail, task_id),
        -vacation,
        attained.get(owner, 0),
        task_id,
    )


def _complete_flat_longest_tail(
    model: PreemptiveDAGModel,
    state: ScheduleState,
) -> ScheduleState:
    while not model.is_finished(state):
        eligible = model.eligible_communications(state)
        if not eligible:
            action = Action.wait()
        else:
            tail = residual_tail(model, state)
            selected = min(
                eligible,
                key=lambda task_id: (
                    -_tail_score(model, state, tail, task_id),
                    task_id,
                ),
            )
            action = Action.run(selected)
        state = model.step(state, action).after
    return state


def _eligible_by_job(
    instance: MultiJobInstance,
    eligible: Sequence[str],
) -> dict[str, tuple[str, ...]]:
    values: dict[str, list[str]] = {}
    for task_id in eligible:
        values.setdefault(instance.task_job[task_id], []).append(task_id)
    return {job_id: tuple(task_ids) for job_id, task_ids in values.items()}


def _prefixed(job_id: str, task_id: str) -> str:
    return f"{job_id}::{task_id}"


def _multi_residual_tail(model, state) -> dict[str, int]:
    children = {task_id: [] for task_id in model.task_ids}
    for task in model.tasks:
        for dependency in task.deps:
            children[dependency].append(task.task_id)
    tail: dict[str, int] = {}
    for task_id in reversed(model.task_ids):
        runtime = state.tasks[model.index[task_id]]
        own = (
            0
            if runtime.status == "completed"
            else runtime.remaining or model.tasks[model.index[task_id]].duration
        )
        tail[task_id] = own + max(
            (tail[child] for child in children[task_id]),
            default=0,
        )
    return tail


def _multi_tail_score(model, state, tail: Mapping[str, int], task_id: str) -> int:
    runtime = state.tasks[model.index[task_id]]
    own = runtime.remaining or model.tasks[model.index[task_id]].duration
    return tail[task_id] - own


def _count_multi_preemptions(
    model: PreemptiveMultiResourceModel,
    actions: Sequence[MultiAction],
) -> int:
    count = 0
    previous: set[str] = set()
    state = model.initial_state()
    for action in actions:
        state, _forced_idle = model.normalize_decision_state(state)
        current = set(action.communications)
        after = model.step(state, action)
        count += sum(
            after.tasks[model.index[task_id]].status != "completed"
            for task_id in previous - current
        )
        previous = current
        state = after
    return count


def build_parallel_chain_job(
    name: str,
    chains: Sequence[tuple[int, Sequence[int], Sequence[int]]],
) -> BenchmarkDAG:
    tasks: list[BenchTask] = []
    for chain_index, (release, communications, computes) in enumerate(chains):
        if len(communications) != len(computes):
            raise ValueError("communication and compute sequences must align")
        previous: str | None = None
        if release:
            previous = f"c{chain_index}_release"
            tasks.append(BenchTask(previous, "compute", release, role="RELEASE"))
        for operation, (communication, compute) in enumerate(
            zip(communications, computes, strict=True)
        ):
            flow = f"c{chain_index}_flow{operation}"
            tasks.append(BenchTask(
                flow,
                "comm",
                communication,
                () if previous is None else (previous,),
                role=f"CHAIN_{chain_index}_COMM",
            ))
            previous = f"c{chain_index}_compute{operation}"
            tasks.append(BenchTask(
                previous,
                "compute",
                compute,
                (flow,),
                role=f"CHAIN_{chain_index}_COMPUTE",
            ))
    return BenchmarkDAG(name, "multi_job_fixture", tuple(tasks))
