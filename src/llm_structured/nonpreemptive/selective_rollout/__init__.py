"""Budgeted selective rollout for non-preemptive communication scheduling."""

from .contracts import RolloutConfig, RolloutResult
from .policy import schedule

__all__ = ["RolloutConfig", "RolloutResult", "schedule"]
