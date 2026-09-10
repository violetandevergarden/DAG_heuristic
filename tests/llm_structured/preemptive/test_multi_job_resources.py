from benchmark_generate.llm.preemptive.synthetic_multi_job import multi_job_workloads
from llm_structured.preemptive.multi_job.solver import schedule_multi_resource_policy, solo_optimal_jct


def test_j0_j6_workloads_are_distinct_jobs_and_all_policies_remain_maximal():
    rows = multi_job_workloads()
    assert [row.family for row in rows] == [f"J{i}" for i in range(7)]
    for row in rows:
        assert all("::" in task_id for task_id in row.instance.task_job)
        solo = solo_optimal_jct(row.instance, max_states=100_000)
        for policy in ("flat_lt", "shortest_remaining", "weighted_lt", "fcfs", "attained_service"):
            result = schedule_multi_resource_policy(row.instance, row.resources, job_policy=policy, solo_completion=solo)
            assert result.schedule.trace is not None
            assert len(result.jobs) == len(row.instance.jobs)
            assert 0 < (result.jain_slowdown_fairness or 0) <= 1


def test_weighted_and_makespan_metrics_are_reported_separately():
    row = multi_job_workloads()[-1]
    flat = schedule_multi_resource_policy(row.instance, row.resources, job_policy="flat_lt")
    weighted = schedule_multi_resource_policy(row.instance, row.resources, job_policy="weighted_lt")
    assert flat.weighted_jct != flat.makespan
    assert weighted.weighted_jct <= flat.weighted_jct
