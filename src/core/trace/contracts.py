"""Trace contracts shared by single- and multi-resource execution."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResourceInterval:
    resource_id: str
    task_id: str
    start: int
    end: int


@dataclass(frozen=True)
class ForcedIdleInterval:
    start: int
    end: int


@dataclass(frozen=True)
class ReplaySummary:
    makespan: int
    started_at: dict[str, int]
    completed_at: dict[str, int]
    service: dict[str, int]
