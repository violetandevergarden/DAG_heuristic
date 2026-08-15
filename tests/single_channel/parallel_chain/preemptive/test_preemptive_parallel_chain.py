from core.dag import BenchmarkDAG, BenchTask
from single_channel.parallel_chain.preemptive.interface import solve


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
