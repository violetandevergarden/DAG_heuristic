"""Public algorithm boundary for non-preemptive fixed resources."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol

from core.dag import DAG
from muti_channel.nonpreemptive import solver

Mode = Literal["optional_idle", "work_conserving"]


class Result(Protocol):
    makespan: int


@dataclass(frozen=True)
class AlgorithmSpec:
    run: Callable[[DAG, Mode, dict[str, object]], Result]


def validate_muti_channel(instance: DAG) -> None:
    solver.NonPreeMultiModel(instance)


def _greedy(instance: DAG, options: dict[str, object], policy: str) -> Result:
    if options:
        raise ValueError(f"algorithm does not accept options: {sorted(options)}")
    return solver.schedule_greedy(instance, policy)


def _rollout(instance: DAG, mode: Mode, options: dict[str, object], *, wait: bool) -> Result:
    values = {"top_k": 2, "optional_actions": mode == "optional_idle" and wait}
    values.update(options)
    values["optional_actions"] = mode == "optional_idle" and wait
    return solver.schedule_rollout(instance, **values)  # type: ignore[arg-type]


def _exact(instance: DAG, mode: Mode, options: dict[str, object]) -> Result:
    return solver.exact_oracle(instance, mode=mode, **options)  # type: ignore[arg-type]


_ALGORITHMS: dict[str, AlgorithmSpec] = {
    "longest_tail_pack": AlgorithmSpec(lambda instance, _mode, options: _greedy(instance, options, "dynamic_tail")),
    "resource_pack": AlgorithmSpec(lambda instance, _mode, options: _greedy(instance, options, "resource_tail")),
    "bottleneck_pack": AlgorithmSpec(lambda instance, _mode, options: _greedy(instance, options, "bottleneck_first")),
    "rollout_maximal2": AlgorithmSpec(lambda instance, mode, options: _rollout(instance, mode, options, wait=False)),
    "rollout_optional2": AlgorithmSpec(lambda instance, mode, options: _rollout(instance, mode, options, wait=True)),
    "exact": AlgorithmSpec(_exact),
}


def solve(
    instance: DAG,
    algorithm: str = "longest_tail_pack",
    *,
    mode: Mode = "optional_idle",
    **options: object,
) -> Result:
    validate_muti_channel(instance)
    if mode not in {"optional_idle", "work_conserving"}:
        raise ValueError(f"unknown non-preemptive mode: {mode}")
    try:
        implementation = _ALGORITHMS[algorithm]
    except KeyError as error:
        raise ValueError(f"unknown non-preemptive multi-resource algorithm: {algorithm}") from error
    return implementation.run(instance, mode, dict(options))


__all__ = ["AlgorithmSpec", "Mode", "Result", "solve", "validate_muti_channel"]
