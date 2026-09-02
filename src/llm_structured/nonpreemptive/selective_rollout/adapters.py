"""Compatibility imports; canonical adapters live in ``nonpreemptive.runtime``."""

from llm_structured.nonpreemptive.runtime.adapters import MultiAdapter, SingleAdapter, make_adapter
from llm_structured.nonpreemptive.runtime.contracts import ReplaySummary

__all__ = ["MultiAdapter", "SingleAdapter", "ReplaySummary", "make_adapter"]
