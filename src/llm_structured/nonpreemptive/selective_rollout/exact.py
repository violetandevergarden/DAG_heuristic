"""Exact cost-to-go for simulator-produced non-preemptive residual states."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from time import perf_counter


@dataclass(frozen=True)
class CostToGoResult:
    status: str
    cost: int | None
    optimal_actions: tuple
    explored_states: int
    termination_reason: str | None = None


def cost_to_go(adapter, state, mode, *, max_states=100_000, time_limit_s=30.0) -> CostToGoResult:
    """Solve a stable reachable state using only adapter legal_actions/step."""
    if getattr(state, "time", None) is None:
        raise ValueError("state must be produced by a non-preemptive simulator")
    started=perf_counter(); explored=0

    @lru_cache(maxsize=None)
    def solve(current):
        nonlocal explored
        explored += 1
        if explored > max_states: raise RuntimeError("state_limit")
        if perf_counter()-started > time_limit_s: raise TimeoutError("time_limit")
        if adapter.is_finished(current): return 0
        values=[]
        for action in adapter.legal_actions(current,mode):
            transition=adapter.step(current,action); values.append(transition.after.time-current.time+solve(transition.after))
        if not values: raise RuntimeError("no_legal_action")
        return min(values)
    try:
        optimum=solve(state); best=[]
        for action in adapter.legal_actions(state,mode):
            transition=adapter.step(state,action)
            if transition.after.time-state.time+solve(transition.after)==optimum: best.append(action)
        return CostToGoResult("optimal",optimum,tuple(best),explored)
    except (RuntimeError,TimeoutError) as error:
        return CostToGoResult("unknown",None,(),explored,str(error))
