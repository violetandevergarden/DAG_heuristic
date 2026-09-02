"""Canonical non-preemptive Stage 4 runtime surface."""

from .adapters import MultiAdapter, SingleAdapter, make_adapter
from .completion import complete
from .contracts import ActionSignature, Mode, PolicyName, ReplaySummary
from .policies import baseline_action, longest_tail_action
from .replay import MODES, RULES, replay, run_baseline_loop, schedule_baseline

__all__ = [
    "MODES",
    "RULES",
    "ActionSignature",
    "Mode",
    "MultiAdapter",
    "PolicyName",
    "ReplaySummary",
    "SingleAdapter",
    "baseline_action",
    "complete",
    "longest_tail_action",
    "make_adapter",
    "replay",
    "run_baseline_loop",
    "schedule_baseline",
]
