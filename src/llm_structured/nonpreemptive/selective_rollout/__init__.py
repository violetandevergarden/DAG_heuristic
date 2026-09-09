"""Budgeted selective rollout for non-preemptive communication scheduling."""

from .contracts import RolloutConfig, RolloutResult
from .solver import schedule

__all__ = ["RolloutConfig", "RolloutResult", "schedule"]
