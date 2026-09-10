"""Canonical non-preemptive Stage 4 runtime surface."""

from .adapters import MultiAdapter, SingleAdapter, make_adapter
from .completion import complete
from .contracts import ActionSignature, DecisionContext, JobIndex, Mode, PolicyName, ReplaySummary
from .solver import baseline_action, longest_tail_action
from .runner import (
    ALL_RULES,
    MODES,
    MULTI_JOB_RULES,
    RULES,
    action_digest,
    job_metrics_from_state,
    replay,
    run_baseline_loop,
    schedule_baseline,
)

__all__ = [
    "ALL_RULES",
    "MODES",
    "MULTI_JOB_RULES",
    "RULES",
    "ActionSignature",
    "DecisionContext",
    "JobIndex",
    "Mode",
    "MultiAdapter",
    "PolicyName",
    "ReplaySummary",
    "SingleAdapter",
    "action_digest",
    "baseline_action",
    "complete",
    "job_metrics_from_state",
    "longest_tail_action",
    "make_adapter",
    "replay",
    "run_baseline_loop",
    "schedule_baseline",
]
