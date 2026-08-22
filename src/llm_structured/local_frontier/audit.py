"""Stable audit records for local-frontier decisions."""

from __future__ import annotations

from dataclasses import dataclass

from .evaluator import PairEvaluation
from .region import LocalRegion


@dataclass(frozen=True)
class LocalSearchDecision:
    time: int
    baseline_action: str
    challenger_action: str | None
    triggered: bool
    trigger_reason: str
    region: LocalRegion | None
    evaluation: PairEvaluation | None
    adoption_mode: str
    suggested_action: str
    final_action: str
    changed_lt: bool
    fallback_reason: str | None
