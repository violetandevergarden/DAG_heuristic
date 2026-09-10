"""Public algorithm boundary for non-preemptive parallel chains."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol

from core.dag import DAG
from core.oracle.nonpree_single import exact_oracle
from single_channel.parallel_chain.nonpreemptive import solver
from single_channel.parallel_chain.structure import parse_parallel_chain

Mode = Literal["optional_idle", "work_conserving"]


class Result(Protocol):
    makespan: int


@dataclass(frozen=True)
class AlgorithmSpec:
    run: Callable[[DAG, Mode, dict[str, object]], Result]


def validate_parallel_chain(dag: DAG) -> None:
    parse_parallel_chain(dag)


def _priority(dag: DAG, options: dict[str, object], policy: str) -> Result:
    if options:
        raise ValueError(f"algorithm does not accept options: {sorted(options)}")
    return solver.schedule_priority(solver.chains_from_dag(dag), policy)


def _rollout(dag: DAG, mode: Mode, options: dict[str, object], *, wait: bool, top_k: int = 2) -> Result:
    values = {"top_k": top_k, "allow_wait": mode == "optional_idle" and wait}
    values.update(options)
    values["allow_wait"] = mode == "optional_idle" and wait
    return solver.schedule_rollout(solver.chains_from_dag(dag), **values)  # type: ignore[arg-type]


def _beam(dag: DAG, mode: Mode, options: dict[str, object], width: int = 8) -> Result:
    values = {"width": width, "allow_wait": mode == "optional_idle"}
    values.update(options)
    values["allow_wait"] = mode == "optional_idle"
    return solver.beam_search(solver.chains_from_dag(dag), **values)  # type: ignore[arg-type]


def _exact(dag: DAG, mode: Mode, options: dict[str, object]) -> Result:
    return exact_oracle(dag, mode=mode, **options)  # type: ignore[arg-type]


_ALGORITHMS: dict[str, AlgorithmSpec] = {
    "fifo": AlgorithmSpec(lambda dag, _mode, options: _priority(dag, options, "fifo")),
    "spt": AlgorithmSpec(lambda dag, _mode, options: _priority(dag, options, "spt")),
    "lpt": AlgorithmSpec(lambda dag, _mode, options: _priority(dag, options, "lpt")),
    "longest_delay": AlgorithmSpec(lambda dag, _mode, options: _priority(dag, options, "longest_delay")),
    "longest_tail": AlgorithmSpec(lambda dag, _mode, options: _priority(dag, options, "dynamic_tail")),
    "rollout2": AlgorithmSpec(lambda dag, mode, options: _rollout(dag, mode, options, wait=False)),
    "rollout4": AlgorithmSpec(lambda dag, mode, options: _rollout(dag, mode, options, wait=False, top_k=4)),
    "beam8": AlgorithmSpec(_beam),
    "beam32": AlgorithmSpec(lambda dag, mode, options: _beam(dag, mode, options, width=32)),
    "exact": AlgorithmSpec(_exact),
}


def solve(
    dag: DAG,
    algorithm: str = "longest_tail",
    *,
    mode: Mode = "optional_idle",
    **options: object,
) -> Result:
    validate_parallel_chain(dag)
    if mode not in {"optional_idle", "work_conserving"}:
        raise ValueError(f"unknown non-preemptive mode: {mode}")
    try:
        implementation = _ALGORITHMS[algorithm]
    except KeyError as error:
        raise ValueError(f"unknown non-preemptive parallel-chain algorithm: {algorithm}") from error
    return implementation.run(dag, mode, dict(options))


__all__ = ["AlgorithmSpec", "Mode", "Result", "solve", "validate_parallel_chain"]
