"""Semantic-neutral Stage 4 analysis utilities."""

from .perturb import perturb_durations
from .signatures import classify_repetition_evidence

__all__ = ["classify_repetition_evidence", "perturb_durations"]
