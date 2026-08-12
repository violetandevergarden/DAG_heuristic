"""Algorithms and small fixtures for studying repeated LLM-like DAG motifs.

The algorithms in this module are research prototypes for the explicitly
preemptive branch.  They do not change the repository's non-preemptive public
registry or benchmark semantics.
"""

from __future__ import annotations

from dataclasses import replace
from functools import lru_cache
from time import perf_counter
from typing import Sequence

from core.dag import BenchmarkDAG, BenchTask
from preemptive.core.model import (
    Action,
    PreemptiveDAGModel,
    PreemptiveScheduleResult,
    ScheduleState,
    assert_preemptive_trace,
    result_from_trace,
)
from preemptive.single_channel.solver import residual_tail


def build_pp_dp_repetition(
    periods: int,
    *,
    pp_work: int = 1,
    dp_work: int = 1,
    release_gap: int = 1,
    dp_tail: int = 1,
) -> BenchmarkDAG:
    """Build a repeated PP-backbone plus deferred-DP-side-work fixture.

    In one isolated period, DP first is strictly optimal with the defaults.
    Across periods, PP unlocks the next repeated unit, so copying that local
    decision delays every later release.  This is the smallest strict example
    we found for the period-boundary effect.
    """

    if periods < 1 or min(pp_work, dp_work, release_gap, dp_tail) < 0:
        raise ValueError("period counts and durations must be non-negative")
    if pp_work == 0 or dp_work == 0:
        raise ValueError("communication work must be positive")
    tasks: list[BenchTask] = []
    previous_backbone: str | None = None
    for period in range(periods):
        release = f"release_{period}"
        tasks.append(BenchTask(
            release,
            "compute",
            0 if period == 0 else release_gap,
            () if previous_backbone is None else (previous_backbone,),
            role="RELEASE",
        ))
        pp = f"pp_{period}"
        dp = f"dp_{period}"
        backbone = f"backbone_{period}"
        tasks.extend((
            BenchTask(pp, "comm", pp_work, (release,), role="PP"),
            BenchTask(dp, "comm", dp_work, (release,), role="DP"),
            BenchTask(backbone, "compute", 0, (pp,), role="BACKBONE"),
            BenchTask(f"dp_tail_{period}", "compute", dp_tail, (dp,), role="DP_TAIL"),
        ))
        previous_backbone = backbone
    return BenchmarkDAG(
        f"pp_dp_repeat_{periods}",
        "adversarial",
        tuple(tasks),
        "Repeated PP release backbone with deferred DP side work.",
        (("periods", str(periods)),),
    )


def schedule_role_copy(
    dag: BenchmarkDAG,
    first_role: str,
) -> PreemptiveScheduleResult:
    """Copy one fixed local role preference at every repeated unit."""

    model = PreemptiveDAGModel(dag)
    task_map = dag.task_map()
    state = model.initial_state()
    actions: list[Action] = []
    while not model.is_finished(state):
        eligible = model.eligible_communications(state)
        if not eligible:
            action = Action.wait()
        else:
            action = Action.run(min(
                eligible,
                key=lambda task_id: (
                    task_map[task_id].role != first_role,
                    task_id,
                ),
            ))
        actions.append(action)
        state = model.step(state, action).after
    trace = model.run(actions)
    assert_preemptive_trace(model, trace)
    return result_from_trace(trace)


def schedule_coupling_aware(dag: BenchmarkDAG) -> PreemptiveScheduleResult:
    """Use the repeat boundary while it matters, then fall back to tail.

    PP communication is advanced when it unlocks another not-yet-released PP
    unit.  At the final unit (or outside this recognized pattern), dynamic
    residual tail decides.  Thus the policy is a state rule, not a copied task
    timetable, and duration perturbations cannot make its schedule infeasible.
    """

    model = PreemptiveDAGModel(dag)
    task_map = dag.task_map()
    state = model.initial_state()
    actions: list[Action] = []
    while not model.is_finished(state):
        eligible = model.eligible_communications(state)
        if not eligible:
            action = Action.wait()
        else:
            unfinished_pp = sum(
                task.kind == "comm"
                and task.role.startswith("PP")
                and model.task_runtime(state, task.task_id).status != "completed"
                for task in model.tasks
            )
            eligible_pp = [
                task_id for task_id in eligible
                if task_map[task_id].role.startswith("PP")
            ]
            if unfinished_pp > 1 and eligible_pp:
                selected = min(eligible_pp)
            else:
                tail = residual_tail(model, state)
                selected = min(eligible, key=lambda item: (-tail[item], item))
            action = Action.run(selected)
        actions.append(action)
        state = model.step(state, action).after
    trace = model.run(actions)
    assert_preemptive_trace(model, trace)
    return result_from_trace(trace)


def build_exchangeable_replicas(replicas: int) -> tuple[BenchmarkDAG, tuple[tuple[str, ...], ...]]:
    """Create identical, independent replica components sharing one channel."""

    if replicas < 1:
        raise ValueError("replicas must be positive")
    tasks: list[BenchTask] = []
    components: list[tuple[str, ...]] = []
    for replica in range(replicas):
        prefix = f"rep{replica}"
        ids = (
            f"{prefix}_release",
            f"{prefix}_reduce",
            f"{prefix}_compute",
            f"{prefix}_gather",
            f"{prefix}_tail",
        )
        tasks.extend((
            BenchTask(ids[0], "compute", 1, (), role="RELEASE"),
            BenchTask(ids[1], "comm", 2, (ids[0],), role="DP_RS"),
            BenchTask(ids[2], "compute", 2, (ids[1],), role="B"),
            BenchTask(ids[3], "comm", 1, (ids[2],), role="DP_AG"),
            BenchTask(ids[4], "compute", 1, (ids[3],), role="OPT"),
        ))
        components.append(ids)
    return (
        BenchmarkDAG(
            f"exchangeable_replicas_{replicas}",
            "synthetic",
            tuple(tasks),
            "Identical DP replica motifs for exact symmetry compression.",
        ),
        tuple(components),
    )


def exact_oracle_component_symmetry(
    dag: BenchmarkDAG,
    components: Sequence[Sequence[str]],
    *,
    max_states: int = 500_000,
    time_limit_s: float | None = None,
) -> PreemptiveScheduleResult:
    """Exact event search modulo permutations of proven-identical components.

    Validation requires identical labels/durations and identical dependency
    positions with no edge crossing between components.  Under that condition,
    component permutation is a DAG automorphism, so sorting component runtime
    vectors is an exact quotient, not a heuristic hash collision.
    """

    model = PreemptiveDAGModel(dag)
    aligned = _validate_exchangeable_components(model, components)
    covered = {index for component in aligned for index in component}
    fixed = tuple(index for index in range(len(model.tasks)) if index not in covered)
    representatives: dict[tuple, ScheduleState] = {}
    started = perf_counter()
    explored = 0

    def runtime_key(state: ScheduleState, index: int) -> tuple[str, int]:
        runtime = state.tasks[index]
        return runtime.status, runtime.remaining

    def key(state: ScheduleState) -> tuple:
        component_states = tuple(sorted(
            tuple(runtime_key(state, index) for index in component)
            for component in aligned
        ))
        fixed_state = tuple((index, runtime_key(state, index)) for index in fixed)
        return component_states, fixed_state

    @lru_cache(maxsize=None)
    def value(state_key: tuple) -> int:
        nonlocal explored
        explored += 1
        if explored > max_states:
            raise RuntimeError("symmetry oracle exceeded state limit")
        if time_limit_s is not None and perf_counter() - started > time_limit_s:
            raise TimeoutError("symmetry oracle exceeded time limit")
        state = representatives[state_key]
        if model.is_finished(state):
            return 0
        actions = list(model.legal_actions(state))
        if model.eligible_communications(state):
            actions = [action for action in actions if action.kind == "run"]
        best: int | None = None
        for action in actions:
            after = model.step(state, action).after
            child = key(after)
            representatives.setdefault(child, after)
            candidate = after.time - state.time + value(child)
            best = candidate if best is None else min(best, candidate)
        if best is None:
            raise RuntimeError("unfinished state has no legal action")
        return best

    state = model.initial_state()
    root = key(state)
    representatives[root] = state
    value(root)
    actions: list[Action] = []
    while not model.is_finished(state):
        legal = list(model.legal_actions(state))
        if model.eligible_communications(state):
            legal = [action for action in legal if action.kind == "run"]
        candidates = []
        for action in legal:
            after = model.step(state, action).after
            child = key(after)
            representatives.setdefault(child, after)
            candidates.append((
                after.time - state.time + value(child),
                action.kind,
                action.task_id or "",
                action,
                after,
            ))
        _cost, _kind, _task_id, action, state = min(candidates)
        actions.append(action)
    trace = model.run(actions)
    assert_preemptive_trace(model, trace)
    return replace(result_from_trace(trace), explored_states=explored)


def _validate_exchangeable_components(
    model: PreemptiveDAGModel,
    components: Sequence[Sequence[str]],
) -> tuple[tuple[int, ...], ...]:
    if not components:
        raise ValueError("at least one symmetry component is required")
    normalized = tuple(
        tuple(model.index[task_id] for task_id in component)
        for component in components
    )
    if len({index for component in normalized for index in component}) != sum(map(len, normalized)):
        raise ValueError("symmetry components overlap")
    width = len(normalized[0])
    if width == 0 or any(len(component) != width for component in normalized):
        raise ValueError("symmetry components must have equal positive size")
    owner = {
        index: (group, position)
        for group, component in enumerate(normalized)
        for position, index in enumerate(component)
    }
    reference = normalized[0]
    for component in normalized:
        for position, index in enumerate(component):
            task = model.tasks[index]
            expected = model.tasks[reference[position]]
            if (task.kind, task.duration, task.role) != (
                expected.kind,
                expected.duration,
                expected.role,
            ):
                raise ValueError("component task labels are not identical")
            relative_deps = []
            for parent in model.deps[index]:
                location = owner.get(parent)
                if location is None or location[0] != owner[index][0]:
                    raise ValueError("exchangeable components may not have cross-component edges")
                relative_deps.append(location[1])
            expected_deps = [reference.index(parent) for parent in model.deps[reference[position]]]
            if sorted(relative_deps) != sorted(expected_deps):
                raise ValueError("component dependency shapes differ")
    return normalized
