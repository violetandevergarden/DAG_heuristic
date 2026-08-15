from pathlib import Path

from benchmark import load_benchmark
from registry import solve


ROOT = Path(__file__).resolve().parents[1]


def _load(relative: str):
    return load_benchmark(ROOT / "benchmark" / relative)


def test_parallel_chain_file_reproduces_longest_tail() -> None:
    benchmark = _load("single_channel/parallel_chain/nonpreemptive/adversarial/tight_optional_wait_m20.json")
    assert solve(benchmark, "longest_tail").makespan == 41


def test_complex_chain_file_reproduces_rollout() -> None:
    benchmark = _load("single_channel/complex_chain/nonpreemptive/adversarial/longest_tail_counterexample.json")
    assert solve(benchmark, "rollout_wait2").makespan == 8


def test_muti_channel_file_reproduces_optional_rollout() -> None:
    benchmark = _load("muti_channel/nonpreemptive/adversarial/nonmaximal_start_np.json")
    assert solve(benchmark, "rollout_optional2").makespan == 8
