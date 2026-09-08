"""Public algorithm boundary for non-preemptive general DAGs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol

from core.dag import DAG
from core.oracle.nonpreemptive import exact_oracle
from single_channel.complex_chain.nonpreemptive import solver

Mode = Literal["optional_idle", "work_conserving"]


class Result(Protocol):
    makespan: int


@dataclass(frozen=True)
class AlgorithmSpec:
    run: Callable[[DAG, Mode, dict[str, object]], Result]


def validate_complex_chain(dag: DAG) -> None:
    errors = dag.validate()
    if not dag.tasks:
        errors.append("complex_chain requires at least one task")
    if errors:
        raise ValueError(f"invalid complex_chain DAG {dag.name}: {errors}")


def _priority(dag: DAG, options: dict[str, object], policy: str) -> Result:
    if options:
        raise ValueError(f"algorithm does not accept options: {sorted(options)}")
    return solver.schedule_priority(dag, policy)


def _rollout(dag: DAG, mode: Mode, options: dict[str, object], *, wait: bool, depth: int = 1) -> Result:
    values = {"top_k": 2, "allow_wait": mode == "optional_idle" and wait, "depth": depth}
    values.update(options)
    values["allow_wait"] = mode == "optional_idle" and wait
    return solver.schedule_rollout(dag, **values)  # type: ignore[arg-type]


def _beam(dag: DAG, mode: Mode, options: dict[str, object]) -> Result:
    values = {"width": 8, "allow_wait": mode == "optional_idle"}
    values.update(options)
    values["allow_wait"] = mode == "optional_idle"
    return solver.beam_search(dag, **values)  # type: ignore[arg-type]


def _exact(dag: DAG, mode: Mode, options: dict[str, object]) -> Result:
    return exact_oracle(dag, mode=mode, **options)  # type: ignore[arg-type]


_ALGORITHMS: dict[str, AlgorithmSpec] = {
    "longest_tail": AlgorithmSpec(lambda dag, _mode, options: _priority(dag, options, "dynamic")),
    "join_bonus": AlgorithmSpec(lambda dag, _mode, options: _priority(dag, options, "raw_join")),
    "rollout_flow2": AlgorithmSpec(lambda dag, mode, options: _rollout(dag, mode, options, wait=False)),
    "rollout_wait2": AlgorithmSpec(lambda dag, mode, options: _rollout(dag, mode, options, wait=True)),
    "depth2_wait2": AlgorithmSpec(lambda dag, mode, options: _rollout(dag, mode, options, wait=True, depth=2)),
    "beam_wait8": AlgorithmSpec(_beam),
    "exact_optional": AlgorithmSpec(_exact),
}


def solve(
    dag: DAG,
    algorithm: str = "longest_tail",
    *,
    mode: Mode = "optional_idle",
    **options: object,
) -> Result:
    validate_complex_chain(dag)
    if mode not in {"optional_idle", "work_conserving"}:
        raise ValueError(f"unknown non-preemptive mode: {mode}")
    try:
        implementation = _ALGORITHMS[algorithm]
    except KeyError as error:
        raise ValueError(f"unknown non-preemptive complex-chain algorithm: {algorithm}") from error
    return implementation.run(dag, mode, dict(options))


__all__ = ["AlgorithmSpec", "Mode", "Result", "solve", "validate_complex_chain"]
