"""Compatibility imports for the canonical frozen baseline."""

from llm_structured.nonpreemptive.runtime.completion import complete
from llm_structured.nonpreemptive.runtime.policies import longest_tail_action

__all__ = ["complete", "longest_tail_action"]
