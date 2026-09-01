"""Dependency-only barrier index; task names and metadata are deliberately ignored."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BarrierGraph:
    parents: dict[str, tuple[str, ...]]
    children: dict[str, tuple[str, ...]]
    barriers: tuple[str, ...]
    barrier_level: dict[str, int]
    nearest_barriers: dict[str, tuple[str, ...]]

    @classmethod
    def build(cls, benchmark, *, max_barriers: int = 256) -> BarrierGraph:
        parents = {task.task_id: tuple(task.dependencies) for task in benchmark.tasks}
        mutable = {task.task_id: [] for task in benchmark.tasks}
        for child, deps in parents.items():
            for parent in deps:
                mutable[parent].append(child)
        children = {key: tuple(sorted(value)) for key, value in mutable.items()}
        all_barriers = tuple(task.task_id for task in benchmark.tasks if len(task.dependencies) > 1)
        barriers = all_barriers[:max_barriers]
        barrier_set = set(barriers)
        nearest: dict[str, tuple[str, ...]] = {}
        for root in parents:
            seen = {root}; frontier = [root]; found = []
            while frontier and not found:
                nxt = []
                for item in frontier:
                    for child in children[item]:
                        if child in seen: continue
                        seen.add(child)
                        if child in barrier_set: found.append(child)
                        else: nxt.append(child)
                frontier = nxt
            nearest[root] = tuple(sorted(set(found)))
        level: dict[str, int] = {}
        for barrier in barriers:
            upstream = [b for b in barriers if b != barrier and barrier in _descendants(children, b)]
            level[barrier] = 1 + max((level.get(x, 1) for x in upstream), default=0)
        return cls(parents, children, barriers, level, nearest)

    @property
    def truncated(self) -> bool:
        return any(len(value) > 1 for value in self.parents.values()) and not self.barriers


def _descendants(children, root):
    result = set(); stack = list(children[root])
    while stack:
        item = stack.pop()
        if item in result: continue
        result.add(item); stack.extend(children[item])
    return result
