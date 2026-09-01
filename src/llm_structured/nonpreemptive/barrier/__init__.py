"""Non-preemptive Stage 4e barrier-aware scheduling."""

from .contracts import ActionFeatures, BarrierConfig, BarrierResult
from .graph import BarrierGraph
from .policies import schedule

__all__ = ["ActionFeatures", "BarrierConfig", "BarrierGraph", "BarrierResult", "schedule"]
