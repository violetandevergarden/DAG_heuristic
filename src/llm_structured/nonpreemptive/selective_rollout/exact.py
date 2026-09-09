"""Exact cost-to-go for simulator-produced non-preemptive residual states."""

from __future__ import annotations

from dataclasses import dataclass

from core.execution.nonpreemptive import NonPreeMultiModel, NonPreeSingleModel
from core.oracle.nonpree_multi import exact_completion_from_state as exact_multi_completion
from core.oracle.nonpree_single import exact_completion_from_state as exact_single_completion


@dataclass(frozen=True)
class CostToGoResult:
    status: str
    cost: int | None
    optimal_actions: tuple
    explored_states: int
    termination_reason: str | None = None


def cost_to_go(adapter, state, mode, *, max_states=100_000, time_limit_s=30.0) -> CostToGoResult:
    """Solve a stable reachable state through the semantic core oracle."""
    if getattr(state, "time", None) is None:
        raise ValueError("state must be produced by a non-preemptive simulator")
    model = adapter.model
    if isinstance(model, NonPreeSingleModel):
        result = exact_single_completion(
            model, state, mode=mode, max_states=max_states, time_limit_s=time_limit_s
        )
    elif isinstance(model, NonPreeMultiModel):
        result = exact_multi_completion(
            model, state, mode=mode, max_states=max_states, time_limit_s=time_limit_s
        )
    else:
        raise TypeError("adapter model is not a non-preemptive core model")
    return CostToGoResult(
        result.status,
        result.cost,
        result.optimal_actions,
        result.explored_states,
        result.termination_reason,
    )
