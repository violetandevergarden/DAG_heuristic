from __future__ import annotations

import random
from dataclasses import replace

import pytest

from benchmark import (
    Benchmark,
    Resource,
    SchedulingSemantics,
    Task,
    validate_benchmark,
    write_benchmark,
)
from benchmark.validator import BenchmarkValidationError
from core.dag import BenchmarkDAG, BenchTask
from core.execution.preemptive import PreemptiveDAGModel
from core.trace.preemptive import assert_preemptive_trace
from experiments.preemptive.stage1_parallel_chain import run_stage1
from single_channel.complex_chain.preemptive.solver import exact_oracle as generic_exact
from single_channel.parallel_chain.model import (
    ParallelChain,
    parse_parallel_chain,
    to_benchmark_dag,
)
from single_channel.parallel_chain.preemptive import solver as stage1_solver
from single_channel.parallel_chain.preemptive.interface import (
    solve,
    validate_parallel_chain,
)
from single_channel.parallel_chain.preemptive.solver import (
    exact_oracle,
    schedule_priority,
    schedule_rollout,
)
from tests.oracles.preemptive.tiny_oracle import tiny_tick_optimum


def _first_run(result) -> str:
    return next(
        transition.action.task_id
        for transition in result.trace.transitions
        if transition.action.kind == "run"
    )


def _v2(tasks: tuple[Task, ...]) -> Benchmark:
    return Benchmark(
        benchmark_id="contract",
        scenario="single_channel",
        family="parallel_chain",
        category="adversarial",
        tasks=tasks,
        resources=(Resource("channel:0", "channel"),),
        semantics=SchedulingSemantics(
            preemption="communication_resume",
            decision_epoch="task_event",
            optional_idle=False,
            resource_model="exclusive_fixed_set",
        ),
        schema_version="2.0",
    )


def test_preemptive_parallel_chain_has_an_explicit_family_entry() -> None:
    dag = BenchmarkDAG(
        "parallel_preemptive_smoke",
        "test",
        (
            BenchTask("a", "comm", 2),
            BenchTask("a_tail", "compute", 1, ("a",)),
            BenchTask("b", "comm", 1),
        ),
    )

    assert solve(dag, "exact").makespan == 3


@pytest.mark.parametrize(
    "tasks",
    [
        (BenchTask("c", "compute", 0),),
        (BenchTask("m", "comm", 1),),
        (BenchTask("c", "compute", 1), BenchTask("m", "comm", 1, ("c",))),
        (BenchTask("m", "comm", 1), BenchTask("c", "compute", 0, ("m",))),
    ],
)
def test_contract_accepts_both_start_and_end_types_and_zero_compute(tasks) -> None:
    dag = BenchmarkDAG("valid", "test", tasks)
    validate_parallel_chain(dag)
    result = exact_oracle(dag)
    assert_preemptive_trace(PreemptiveDAGModel(dag), result.trace)


@pytest.mark.parametrize(
    ("tasks", "message"),
    [
        (
            (BenchTask("a", "comm", 1), BenchTask("b", "comm", 1, ("a",))),
            "strictly alternate",
        ),
        (
            (BenchTask("a", "compute", 1), BenchTask("b", "compute", 1, ("a",))),
            "strictly alternate",
        ),
        (
            (
                BenchTask("a", "comm", 1),
                BenchTask("b", "compute", 1, ("a",)),
                BenchTask("c", "compute", 1, ("a",)),
            ),
            "fork/join",
        ),
        ((BenchTask("a", "comm", 0),), "positive work"),
    ],
)
def test_contract_rejects_non_stage1_shapes(tasks, message) -> None:
    with pytest.raises(ValueError, match=message):
        validate_parallel_chain(BenchmarkDAG("invalid", "test", tasks))


def test_public_benchmark_validator_enforces_the_same_alternation() -> None:
    benchmark = _v2(
        (
            Task("a", "communication", 1, resources=("channel:0",)),
            Task(
                "b",
                "communication",
                1,
                dependencies=("a",),
                resources=("channel:0",),
            ),
        )
    )
    with pytest.raises(BenchmarkValidationError, match="strictly alternate"):
        validate_benchmark(benchmark)


def test_fifo_uses_first_eligibility_and_keeps_arrival_after_pause() -> None:
    dag = BenchmarkDAG(
        "fifo_arrival",
        "test",
        (
            BenchTask("release_z", "compute", 1),
            BenchTask("z", "comm", 20, ("release_z",)),
            BenchTask("release_a", "compute", 10),
            BenchTask("a", "comm", 2, ("release_a",)),
        ),
    )
    result = schedule_priority(dag, "fifo")
    decisions = [
        (transition.before.time, transition.action.task_id)
        for transition in result.trace.transitions
        if transition.action.kind == "run"
    ]
    assert decisions[:2] == [(1, "z"), (10, "z")]


def test_delay_tail_and_lrpt_have_distinct_definitions() -> None:
    delay_vs_tail = BenchmarkDAG(
        "delay_vs_tail",
        "test",
        (
            BenchTask("a", "comm", 1),
            BenchTask("a_delay", "compute", 5, ("a",)),
            BenchTask("b", "comm", 10),
            BenchTask("b_delay", "compute", 1, ("b",)),
            BenchTask("b_second", "comm", 10, ("b_delay",)),
            BenchTask("b_tail", "compute", 1, ("b_second",)),
        ),
    )
    assert _first_run(schedule_priority(delay_vs_tail, "longest_delay")) == "a"
    assert _first_run(schedule_priority(delay_vs_tail, "longest_tail")) == "b"

    tail_vs_lrpt = BenchmarkDAG(
        "tail_vs_lrpt",
        "test",
        (
            BenchTask("a", "comm", 10),
            BenchTask("a_tail", "compute", 5, ("a",)),
            BenchTask("b", "comm", 1),
            BenchTask("b_tail", "compute", 6, ("b",)),
        ),
    )
    assert _first_run(schedule_priority(tail_vs_lrpt, "longest_tail")) == "b"
    assert _first_run(schedule_priority(tail_vs_lrpt, "lrpt")) == "a"


def test_rollout_candidate_mode_is_explicit_and_deterministic() -> None:
    dag = BenchmarkDAG(
        "rollout_modes",
        "test",
        (
            BenchTask("a", "comm", 8),
            BenchTask("a_tail", "compute", 2, ("a",)),
            BenchTask("b", "comm", 1),
            BenchTask("b_tail", "compute", 7, ("b",)),
            BenchTask("c", "comm", 2),
            BenchTask("c_tail", "compute", 6, ("c",)),
        ),
    )
    for mode in ("longest_tail", "lrpt"):
        first = schedule_rollout(dag, top_k=2, candidate_mode=mode)
        second = schedule_rollout(dag, top_k=2, candidate_mode=mode)
        assert first.trace == second.trace
    with pytest.raises(ValueError, match="candidate_mode"):
        schedule_rollout(dag, candidate_mode="tail")


def test_residual_tail_is_computed_once_per_priority_decision(monkeypatch) -> None:
    dag = BenchmarkDAG(
        "tail_snapshot",
        "test",
        tuple(
            task
            for index in range(8)
            for task in (
                BenchTask(f"c{index}", "comm", index + 1),
                BenchTask(f"p{index}", "compute", 8 - index, (f"c{index}",)),
            )
        ),
    )
    original = stage1_solver.residual_tail
    calls = 0

    def counted(model, state):
        nonlocal calls
        calls += 1
        return original(model, state)

    monkeypatch.setattr(stage1_solver, "residual_tail", counted)
    result = schedule_priority(dag, "longest_tail")
    run_decisions = sum(transition.action.kind == "run" for transition in result.trace.transitions)
    assert calls == run_decisions

    calls = 0
    schedule_priority(dag, "fifo")
    assert calls == 0


def test_rollout_depth_is_explicit_and_depth_one_is_backward_stable() -> None:
    dag = BenchmarkDAG(
        "rollout_depth",
        "test",
        (
            BenchTask("a", "comm", 4),
            BenchTask("a_tail", "compute", 5, ("a",)),
            BenchTask("b", "comm", 1),
            BenchTask("b_tail", "compute", 2, ("b",)),
            BenchTask("b_second", "comm", 3, ("b_tail",)),
            BenchTask("c", "comm", 2),
            BenchTask("c_tail", "compute", 4, ("c",)),
        ),
    )
    legacy = schedule_rollout(dag, top_k=2)
    explicit = schedule_rollout(dag, top_k=2, depth=1)
    depth_two = schedule_rollout(dag, top_k=2, depth=2)
    assert legacy.trace == explicit.trace
    assert depth_two.trace == schedule_rollout(dag, top_k=2, depth=2).trace
    with pytest.raises(ValueError, match="depth"):
        schedule_rollout(dag, depth=0)


def test_rollout_depth_two_closes_fixed_depth_counterexample() -> None:
    chains = (
        ParallelChain((7, 4, 6), (7, 11, 2)),
        ParallelChain((1, 4, 3, 7), (0, 4, 10, 1)),
        ParallelChain((2, 4, 5, 2), (10, 5, 9, 6)),
    )
    dag, _ = to_benchmark_dag(chains)

    assert schedule_rollout(dag, top_k=2, depth=1).makespan == 49
    assert schedule_rollout(dag, top_k=4, depth=1).makespan == 48
    assert schedule_rollout(dag, top_k=2, depth=2).makespan == 47
    assert exact_oracle(dag).makespan == 47


def test_identical_chain_symmetry_reduction_preserves_optimum_and_replay() -> None:
    chains = tuple(ParallelChain((2, 1), (1, 2), 0) for _ in range(5))
    dag, _ = to_benchmark_dag(chains)
    ordered = exact_oracle(dag, symmetry_reduction=False)
    symmetric = exact_oracle(dag, symmetry_reduction=True)

    assert symmetric.makespan == ordered.makespan == tiny_tick_optimum(dag)
    assert symmetric.explored_states < ordered.explored_states
    assert_preemptive_trace(PreemptiveDAGModel(dag), symmetric.trace)


def test_compact_exact_matches_tick_and_generic_oracles_for_fixed_random_suite() -> None:
    rng = random.Random(260816)
    for index in range(200):
        chains = tuple(
            ParallelChain(
                tuple(rng.randint(1, 3) for _ in range(operations)),
                tuple(rng.randint(0, 2) for _ in range(operations)),
                rng.randint(0, 2),
            )
            for operations in (rng.randint(1, 2) for _ in range(rng.randint(1, 3)))
        )
        dag, _ = to_benchmark_dag(chains)
        compact = exact_oracle(dag)
        assert compact.makespan == tiny_tick_optimum(dag), index
        assert compact.makespan == generic_exact(dag).makespan, index
        assert compact.status == "optimal"
        assert compact.lower_bound <= compact.makespan
        assert_preemptive_trace(PreemptiveDAGModel(dag), compact.trace)


def test_parser_preserves_user_task_identity_without_normalization() -> None:
    dag = BenchmarkDAG(
        "identity",
        "test",
        (
            BenchTask("start_compute", "compute", 0),
            BenchTask("end_comm", "comm", 2, ("start_compute",)),
        ),
    )
    assert parse_parallel_chain(dag).chains == (("start_compute", "end_comm"),)


def test_stage1_runner_emits_auditable_raw_and_grouped_metrics(tmp_path) -> None:
    benchmark = _v2(
        (
            Task("a", "communication", 2, resources=("channel:0",)),
            Task("tail", "compute", 2, dependencies=("a",)),
            Task("b", "communication", 1, resources=("channel:0",)),
        )
    )
    benchmark = replace(benchmark, metadata={"stage1_group": "structured", "seed": 7})
    target = tmp_path / "single_channel/parallel_chain/preemptive/real/case.json"
    write_benchmark(benchmark, target)
    report = run_stage1(tmp_path, algorithms=("fifo", "longest_tail"))

    assert len(report["instances"]) == 1
    row = report["instances"][0]
    assert row["sha256"]
    assert row["exact"]["status"] == "optimal"
    assert row["results"]["fifo"]["forced_idle"] >= 0
    assert "structured" in report["summary"]
