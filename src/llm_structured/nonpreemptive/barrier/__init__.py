"""Non-preemptive Stage 4e barrier-aware scheduling."""

from .contracts import ActionFeatures, BarrierConfig, BarrierResult
from .graph import BarrierGraph
from .solver import schedule

__all__ = ["ActionFeatures", "BarrierConfig", "BarrierGraph", "BarrierResult", "schedule"]
