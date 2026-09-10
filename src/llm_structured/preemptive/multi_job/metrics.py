"""Per-job completion and fairness metrics for multi-job schedules."""

from __future__ import annotations

from statistics import mean
from typing import Mapping, Sequence

from core.execution.preemptive import PreeSingleModel, PreemptiveScheduleResult, ScheduleState
from core.oracle.pree_multi import MultiOracleResult as MultiResult
from core.oracle.pree_single import exact_oracle
from single_channel.complex_chain.preemptive.solver import residual_tail

from .contracts import JobOutcome, JobSummary, MultiJobInstance, MultiJobResult, MultiResourceJobResult


def evaluate_schedule(instance: MultiJobInstance, schedule: PreemptiveScheduleResult, *,
                      solo_completion: Mapping[str, int] | None = None,
                      candidate_evaluations: int = 0,
                      candidate_counts: Sequence[int] = ()) -> MultiJobResult:
    model = PreeSingleModel(instance.dag)
    outcomes = []
    for job in instance.jobs:
        task_ids = [task_id for task_id, owner in instance.task_job.items()
                    if owner == job.job_id and instance.original_task[task_id] != "__arrival__"]
        completion = max(model.task_runtime(schedule.trace.final_state, task_id).completed_at or 0
                         for task_id in task_ids)
        jct = completion - job.arrival
        denominator = solo_completion.get(job.job_id) if solo_completion else None
        outcomes.append(JobOutcome(job.job_id, job.arrival, completion, jct, job.weight,
                                   jct / denominator if denominator else None))
    outcomes.sort(key=lambda item: item.job_id)
    total_weight = sum(item.weight for item in outcomes)
    slowdowns = [item.slowdown for item in outcomes if item.slowdown is not None]
    return MultiJobResult(schedule, tuple(outcomes),
                          sum(item.weight * item.jct for item in outcomes) / total_weight,
                          mean(item.jct for item in outcomes),
                          max(slowdowns) if slowdowns else None,
                          candidate_evaluations, tuple(candidate_counts))


def job_summaries(instance: MultiJobInstance, model: PreeSingleModel, state: ScheduleState, *,
                  attained_service: Mapping[str, int] | None = None,
                  last_service: Mapping[str, int] | None = None) -> tuple[JobSummary, ...]:
    tail = residual_tail(model, state)
    attained_service = attained_service or {}
    last_service = last_service or {}
    eligible = set(model.eligible_communications(state))
    summaries = []
    for job in instance.jobs:
        task_ids = [task_id for task_id, owner in instance.task_job.items() if owner == job.job_id]
        unfinished = [task_id for task_id in task_ids
                      if model.task_runtime(state, task_id).status != "completed"]
        comm_work = sum(model.task_runtime(state, task_id).remaining or model.task_map[task_id].duration
                        for task_id in unfinished if model.task_map[task_id].kind == "comm")
        active_compute = sum(model.task_map[task_id].kind == "compute"
                             and model.task_runtime(state, task_id).status == "running"
                             for task_id in task_ids)
        summaries.append(JobSummary(
            job.job_id, comm_work, max((tail[task_id] for task_id in unfinished), default=0),
            sum(task_id in eligible for task_id in task_ids), active_compute,
            attained_service.get(job.job_id, 0),
            max(0, state.time - last_service.get(job.job_id, job.arrival)),
        ))
    return tuple(summaries)


def solo_optimal_jct(instance: MultiJobInstance, *, max_states: int = 500_000,
                     time_limit_s: float | None = None) -> dict[str, int]:
    return {job.job_id: exact_oracle(job.dag, max_states=max_states,
                                     time_limit_s=time_limit_s).makespan
            for job in instance.jobs}


def evaluate_multi_resource_schedule(instance: MultiJobInstance, schedule: MultiResult, *,
                                     solo_completion: Mapping[str, int] | None = None
                                     ) -> MultiResourceJobResult:
    if schedule.trace is None:
        raise ValueError("multi-resource schedule must retain a trace")
    completed_at = {interval.task_id: interval.end for interval in schedule.trace.intervals}
    outcomes = []
    for job in instance.jobs:
        task_ids = [item for item, owner in instance.task_job.items()
                    if owner == job.job_id and instance.original_task[item] != "__arrival__"]
        completion = max(completed_at.get(item, 0) for item in task_ids)
        jct = completion - job.arrival
        denominator = solo_completion.get(job.job_id) if solo_completion else None
        outcomes.append(JobOutcome(job.job_id, job.arrival, completion, jct, job.weight,
                                   jct / denominator if denominator else None))
    outcomes.sort(key=lambda item: item.job_id)
    total_weight = sum(item.weight for item in outcomes)
    slowdowns = [item.slowdown for item in outcomes if item.slowdown is not None]
    fairness = (sum(slowdowns) ** 2 / (len(slowdowns) * sum(value * value for value in slowdowns))
                if slowdowns and sum(value * value for value in slowdowns) else None)
    return MultiResourceJobResult(schedule, tuple(outcomes),
                                  sum(item.weight * item.jct for item in outcomes) / total_weight,
                                  mean(item.jct for item in outcomes),
                                  max(slowdowns) if slowdowns else None, fairness)
