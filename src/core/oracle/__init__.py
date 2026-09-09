"""Semantic-specific exact schedulers.

The package-level alias preserves the historical non-preemptive import.
New callers should import the semantic-specific name explicitly.
"""

from core.oracle.nonpree_single import exact_oracle as nonpreemptive_exact_oracle
from core.oracle.nonpree_single import exact_completion_from_state as nonpreemptive_completion_from_state
from core.oracle.nonpree_single import branch_and_bound_oracle, compare_oracles
from core.oracle.pree_single import exact_oracle as preemptive_exact_oracle
from core.oracle.pree_multi import exact_oracle as preemptive_multi_exact_oracle
from core.oracle.nonpree_multi import exact_oracle as nonpreemptive_multi_exact_oracle
from core.oracle.nonpree_multi import exact_completion_from_state as nonpreemptive_multi_completion_from_state
from core.oracle.nonpree_multi import exact_oracle_uncompressed as nonpreemptive_multi_exact_oracle_uncompressed

exact_oracle = nonpreemptive_exact_oracle

__all__ = [
    "exact_oracle",
    "branch_and_bound_oracle",
    "compare_oracles",
    "nonpreemptive_exact_oracle",
    "nonpreemptive_completion_from_state",
    "preemptive_exact_oracle",
    "preemptive_multi_exact_oracle",
    "nonpreemptive_multi_exact_oracle",
    "nonpreemptive_multi_completion_from_state",
    "nonpreemptive_multi_exact_oracle_uncompressed",
]
