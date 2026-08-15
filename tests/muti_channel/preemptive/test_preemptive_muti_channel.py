from core.dag import BenchmarkDAG, BenchTask
from muti_channel.preemptive.solver import exact_oracle


def test_preemptive_multi_channel_has_an_explicit_family_entry() -> None:
    dag = BenchmarkDAG(
        "multi_preemptive_smoke",
        "test",
        (BenchTask("left", "comm", 2), BenchTask("right", "comm", 3)),
    )
    resources = {
        "left": frozenset({"left"}),
        "right": frozenset({"right"}),
    }

    assert exact_oracle(dag, resources).makespan == 3
