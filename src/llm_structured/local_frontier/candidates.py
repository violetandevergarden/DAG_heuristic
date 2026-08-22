"""Low-cost, deterministic width-two candidate construction."""

from __future__ import annotations

from dataclasses import dataclass

from core.execution.preemptive import PreemptiveDAGModel, ScheduleState
from single_channel.complex_chain.preemptive import solver


@dataclass(frozen=True)
class CandidatePair:
    baseline: str
    challenger: str | None
    normalized_tail_margin: float | None


def candidate_pair(model: PreemptiveDAGModel, state: ScheduleState) -> CandidatePair:
    eligible = model.eligible_communications(state)
    if not eligible:
        raise ValueError("candidate construction requires an eligible communication")
    tails = solver.residual_tail(model, state, eligible)
    exclusive = {
        item: tails[item] - solver._own_remaining(model, state, item)
        for item in eligible
    }
    ordered = sorted(eligible, key=lambda item: (-exclusive[item], item))
    baseline = ordered[0]
    challenger = ordered[1] if len(ordered) > 1 else None
    margin = None
    if challenger is not None:
        margin = (exclusive[baseline] - exclusive[challenger]) / max(exclusive[baseline], 1)
    return CandidatePair(baseline, challenger, margin)
