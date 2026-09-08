"""Semantic-specific exact schedulers.

The package-level alias preserves the historical non-preemptive import.
New callers should import the semantic-specific name explicitly.
"""

from core.oracle.nonpreemptive import exact_oracle as nonpreemptive_exact_oracle
from core.oracle.nonpreemptive import branch_and_bound_oracle, compare_oracles
from core.oracle.preemptive import exact_oracle as preemptive_exact_oracle

exact_oracle = nonpreemptive_exact_oracle

__all__ = [
    "exact_oracle",
    "branch_and_bound_oracle",
    "compare_oracles",
    "nonpreemptive_exact_oracle",
    "preemptive_exact_oracle",
]
