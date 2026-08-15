"""Public interface for fixed-resource muti-channel algorithms."""

from __future__ import annotations

from typing import Protocol

from core.resource import MultiResourceInstance


class Result(Protocol):
    makespan: int


class Algorithm(Protocol):
    def __call__(self, instance: MultiResourceInstance) -> Result: ...
