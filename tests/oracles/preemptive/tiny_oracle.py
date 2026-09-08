"""Independent tick-exhaustive Oracle for tiny integer-duration regressions."""

from __future__ import annotations

from functools import lru_cache
from itertools import combinations

from core.dag import DAG


def tiny_tick_optimum(
    dag: DAG,
    resources: dict[str, frozenset[str]] | None = None,
) -> int:
    """Return the v2 work-conserving optimum without using event transitions."""

    errors = dag.validate()
    if errors:
        raise ValueError(errors)
    order = tuple(dag.topological_order())
    tasks = dag.task_map()
    index = {task_id: position for position, task_id in enumerate(order)}
    deps = tuple(tuple(index[parent] for parent in tasks[item].deps) for item in order)
    comm_ids = tuple(item for item in order if tasks[item].kind == "comm")
    if resources is None:
        resources = {item: frozenset({"channel:0"}) for item in comm_ids}
    if set(resources) != set(comm_ids) or any(not value for value in resources.values()):
        raise ValueError("every communication requires a fixed non-empty resource set")

    durations = tuple(tasks[item].duration for item in order)

    def close(
        remaining: tuple[int, ...], started: int, completed: int
    ) -> tuple[tuple[int, ...], int, int]:
        values = list(remaining)
        changed = True
        while changed:
            changed = False
            for position, task_id in enumerate(order):
                bit = 1 << position
                if completed & bit or started & bit:
                    continue
                if not all(completed & (1 << parent) for parent in deps[position]):
                    continue
                if tasks[task_id].kind == "compute":
                    started |= bit
                    if values[position] == 0:
                        completed |= bit
                    changed = True
        return tuple(values), started, completed

    initial = close(durations, 0, 0)
    full = (1 << len(order)) - 1

    def compatible(items: tuple[str, ...]) -> bool:
        used: set[str] = set()
        for task_id in items:
            if used & resources[task_id]:
                return False
            used.update(resources[task_id])
        return True

    @lru_cache(maxsize=None)
    def search(remaining: tuple[int, ...], started: int, completed: int) -> int:
        remaining, started, completed = close(remaining, started, completed)
        if completed == full:
            return 0
        eligible = tuple(
            task_id
            for task_id in comm_ids
            if not completed & (1 << index[task_id])
            and all(completed & (1 << parent) for parent in deps[index[task_id]])
        )
        if eligible:
            compatible_sets = [
                subset
                for size in range(1, len(eligible) + 1)
                for subset in combinations(eligible, size)
                if compatible(subset)
            ]
            actions = tuple(
                subset
                for subset in compatible_sets
                if not any(set(subset) < set(other) for other in compatible_sets)
            )
        else:
            active_compute = any(
                tasks[task_id].kind == "compute"
                and started & (1 << position)
                and not completed & (1 << position)
                for position, task_id in enumerate(order)
            )
            if not active_compute:
                raise RuntimeError("unfinished tiny state has no future event")
            actions = ((),)

        best: int | None = None
        for selected in actions:
            values = list(remaining)
            next_started = started
            next_completed = completed
            selected_set = set(selected)
            for position, task_id in enumerate(order):
                bit = 1 << position
                if completed & bit:
                    continue
                active_compute = (
                    tasks[task_id].kind == "compute" and started & bit
                )
                active_comm = task_id in selected_set
                if not active_compute and not active_comm:
                    continue
                if active_comm:
                    next_started |= bit
                values[position] -= 1
                if values[position] < 0:
                    raise AssertionError("tiny Oracle produced negative remaining work")
                if values[position] == 0:
                    next_completed |= bit
            candidate = 1 + search(tuple(values), next_started, next_completed)
            best = candidate if best is None else min(best, candidate)
        assert best is not None
        return best

    return search(*initial)
