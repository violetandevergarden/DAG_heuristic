"""Conservative local difference-region extraction from two legal first actions."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from hashlib import sha256

from core.oracle.pree_single import normalized_state_key
from time import perf_counter

from core.execution.preemptive import Action, PreeSingleModel, ScheduleState
from single_channel.complex_chain.preemptive import solver


@dataclass(frozen=True)
class LocalRegion:
    state_fingerprint: str
    baseline_action: str
    challenger_action: str
    task_ids: tuple[str, ...]
    difference_ids: tuple[str, ...]
    boundary_ids: tuple[str, ...]
    node_count: int
    edge_count: int
    communication_count: int
    resource_count: int
    complete: bool
    truncation_reason: str | None
    build_ms: float


def _fingerprint(state: ScheduleState) -> str:
    return sha256(repr(normalized_state_key(state)).encode()).hexdigest()[:16]


def build_local_region(
    model: PreeSingleModel,
    state: ScheduleState,
    baseline: str,
    challenger: str,
    *,
    max_nodes: int,
) -> LocalRegion:
    """Build dependency closure without reading metadata or answer files."""

    started = perf_counter()
    left = model.step(state, Action.run(baseline)).after
    right = model.step(state, Action.run(challenger)).after
    differences = {
        task_id for task_id, a, b in zip(model.task_ids, left.tasks, right.tasks, strict=True)
        if (a.status, a.remaining) != (b.status, b.remaining)
    }
    differences.update((baseline, challenger))
    def descendants(root: str) -> set[str]:
        found: set[str] = set()
        pending = deque((root,))
        while pending:
            current = pending.popleft()
            for child in model.children[current]:
                if child not in found:
                    found.add(child)
                    pending.append(child)
        return found

    common = descendants(baseline) & descendants(challenger)
    # The first common nodes form a cut: no common suffix is expanded beyond it.
    first_common = {
        item for item in common
        if not any(parent in common for parent in model.task_map[item].deps)
    }
    included = set(differences)
    queue = deque(sorted(differences))
    boundary: set[str] = set()
    truncated = False
    while queue:
        current = queue.popleft()
        for child in model.children[current]:
            if child in included:
                continue
            if child in first_common:
                boundary.add(child)
                if len(included) < max_nodes:
                    included.add(child)
                else:
                    truncated = True
                continue
            if len(included) >= max_nodes:
                truncated = True
                boundary.add(child)
                continue
            included.add(child)
            queue.append(child)
    # Dependency closure is required for every retained node.
    changed = True
    while changed and not truncated:
        changed = False
        for task_id in tuple(included):
            for parent in model.task_map[task_id].deps:
                runtime = model.task_runtime(state, parent)
                if runtime.status == "completed" or parent in included:
                    continue
                if len(included) >= max_nodes:
                    truncated = True
                    break
                included.add(parent)
                changed = True
            if truncated:
                break
    edges = sum(
        parent in included
        for task_id in included
        for parent in model.task_map[task_id].deps
    )
    communications = sum(model.task_map[item].kind == "comm" for item in included)
    return LocalRegion(
        _fingerprint(state), baseline, challenger, tuple(sorted(included)),
        tuple(sorted(differences)), tuple(sorted(boundary)), len(included), edges,
        communications, int(communications > 0), not truncated,
        "local_node_limit" if truncated else None,
        (perf_counter() - started) * 1000,
    )
