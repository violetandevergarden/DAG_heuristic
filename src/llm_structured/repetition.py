"""Algorithms and small fixtures for studying repeated LLM-like DAG motifs.

The algorithms in this module are research prototypes for the active
communication-resume mainline. They do not change the maintenance-only
non-preemptive registry or benchmark semantics.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from functools import cache
from time import perf_counter

from core.dag import DAG, Task
from core.execution.preemptive import (
    Action,
    PreeSingleModel,
    PreemptiveScheduleResult,
    ScheduleState,
    result_from_trace,
)
from core.trace.pree_single import assert_preemptive_trace
from single_channel.complex_chain.preemptive.solver import residual_tail


def build_pp_dp_repetition(
    periods: int,
    *,
    pp_work: int = 1,
    dp_work: int = 1,
    release_gap: int = 1,
    dp_tail: int = 1,
) -> DAG:
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
    tasks: list[Task] = []
    previous_backbone: str | None = None
    for period in range(periods):
        release = f"release_{period}"
        tasks.append(Task(
            release,
            "compute",
            0 if period == 0 else release_gap,
            () if previous_backbone is None else (previous_backbone,), labels=(("task_role", "RELEASE"),),
        ))
        pp = f"pp_{period}"
        dp = f"dp_{period}"
        backbone = f"backbone_{period}"
        tasks.extend((
            Task(pp, "comm", pp_work, (release,), labels=(("task_role", "PP"),)),
            Task(dp, "comm", dp_work, (release,), labels=(("task_role", "DP"),)),
            Task(backbone, "compute", 0, (pp,), labels=(("task_role", "BACKBONE"),)),
            Task(f"dp_tail_{period}", "compute", dp_tail, (dp,), labels=(("task_role", "DP_TAIL"),)),
        ))
        previous_backbone = backbone
    return DAG(
        f"pp_dp_repeat_{periods}",
        tuple(tasks),
        context=(("category", "adversarial"), ("description", "Repeated PP release backbone with deferred DP side work.")),
        parameters=(("periods", str(periods)),),
    )


def schedule_role_copy(
    dag: DAG,
    first_role: str,
) -> PreemptiveScheduleResult:
    """Copy one fixed local role preference at every repeated unit."""

    model = PreeSingleModel(dag)
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
                    task_map[task_id].label_map().get("task_role", "") != first_role,
                    task_id,
                ),
            ))
        actions.append(action)
        state = model.step(state, action).after
    trace = model.run(actions)
    assert_preemptive_trace(model, trace)
    return result_from_trace(trace)


def schedule_coupling_aware(dag: DAG) -> PreemptiveScheduleResult:
    """Use the repeat boundary while it matters, then fall back to tail.

    PP communication is advanced when it unlocks another not-yet-released PP
    unit.  At the final unit (or outside this recognized pattern), dynamic
    residual tail decides.  Thus the policy is a state rule, not a copied task
    timetable, and duration perturbations cannot make its schedule infeasible.
    """

    model = PreeSingleModel(dag)
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
                and task.label_map().get("task_role", "").startswith("PP")
                and model.task_runtime(state, task.task_id).status != "completed"
                for task in model.tasks
            )
            eligible_pp = [
                task_id for task_id in eligible
                if task_map[task_id].label_map().get("task_role", "").startswith("PP")
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


def build_exchangeable_replicas(replicas: int) -> tuple[DAG, tuple[tuple[str, ...], ...]]:
    """Create identical, independent replica components sharing one channel."""

    if replicas < 1:
        raise ValueError("replicas must be positive")
    tasks: list[Task] = []
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
            Task(ids[0], "compute", 1, (), labels=(("task_role", "RELEASE"),)),
            Task(ids[1], "comm", 2, (ids[0],), labels=(("task_role", "DP_RS"),)),
            Task(ids[2], "compute", 2, (ids[1],), labels=(("task_role", "B"),)),
            Task(ids[3], "comm", 1, (ids[2],), labels=(("task_role", "DP_AG"),)),
            Task(ids[4], "compute", 1, (ids[3],), labels=(("task_role", "OPT"),)),
        ))
        components.append(ids)
    return (
        DAG(
            f"exchangeable_replicas_{replicas}",
            tuple(tasks),
            context=(("category", "synthetic"), ("description", "Identical DP replica motifs for exact symmetry compression.")),
        ),
        tuple(components),
    )


def exact_oracle_paired(
    dag: DAG,
    components: Sequence[Sequence[str]],
    *,
    quotient: bool,
    resources: dict[str, frozenset] | None = None,
    max_states: int = 500_000,
    time_limit_s: float | None = None,
) -> PreemptiveScheduleResult:
    """Exact event search with two memo keys that differ ONLY in the symmetry key.

    ``quotient=False`` keys each state by instance identity (task index ->
    runtime status/remaining); ``quotient=True`` additionally sorts the
    runtime vectors of the certified identical components.  Transitions,
    action enumeration order, budget checks and the extraction loop are
    byte-identical between the two modes, so the difference in explored /
    generated states isolates the symmetry quotient's contribution instead of
    comparing two different exact implementations.
    """

    model = PreeSingleModel(dag)
    aligned = _validate_exchangeable_components(model, components, resources)
    covered = {index for component in aligned for index in component}
    fixed = tuple(index for index in range(len(model.tasks)) if index not in covered)
    representatives: dict[tuple, ScheduleState] = {}
    started = perf_counter()
    explored = 0
    generated_transitions = 0

    def runtime_key(state: ScheduleState, index: int) -> tuple[str, int]:
        runtime = state.tasks[index]
        return runtime.status, runtime.remaining

    def key(state: ScheduleState) -> tuple:
        if quotient:
            component_states = tuple(sorted(
                tuple(runtime_key(state, index) for index in component)
                for component in aligned
            ))
            fixed_state = tuple((index, runtime_key(state, index)) for index in fixed)
            return component_states, fixed_state
        return tuple(
            (index, runtime_key(state, index)) for index in range(len(model.tasks))
        )

    @cache
    def value(state_key: tuple) -> int:
        nonlocal explored, generated_transitions
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
            generated_transitions += 1
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
    return result_from_trace(trace).with_stats(
        explored_states=explored,
        generated_transitions=generated_transitions,
        deduplicated_states=value.cache_info().hits,
        memo_hits=value.cache_info().hits,
        status="optimal",
        termination_reason="complete_enumeration",
    )


def exact_oracle_component_symmetry(
    dag: DAG,
    components: Sequence[Sequence[str]],
    *,
    max_states: int = 500_000,
    time_limit_s: float | None = None,
) -> PreemptiveScheduleResult:
    """Symmetry-quotient exact (kept for backward compatibility).

    New experiments should prefer :func:`exact_oracle_paired` so the generic
    and quotient runs share one implementation; the pair isolates the key's
    contribution.
    """

    return exact_oracle_paired(
        dag,
        components,
        quotient=True,
        max_states=max_states,
        time_limit_s=time_limit_s,
    )


def adversarial_packing_trap() -> DAG:
    """Wide communication A owns both resources; B and C own one each.

    A longest-remaining-flow-first seed (A, 8) serializes B and C and yields
    18, while packing {B, C} in parallel yields 13.  The trap targets seed
    selection that ignores conflict structure, not the maximal-completion
    semantics itself.
    """

    return DAG('packing_trap', (Task('a', 'comm', 8, (), labels=(('task_role', 'WIDE'), ('parallelism_dimension', 'wide'))), Task('a1', 'compute', 1, ('a',), labels=(('task_role', 'TAIL'),)), Task('b', 'comm', 4, (), labels=(('task_role', 'NARROW'), ('parallelism_dimension', 'b'))), Task('b1', 'compute', 6, ('b',), labels=(('task_role', 'TAIL'),)), Task('c', 'comm', 4, (), labels=(('task_role', 'NARROW'), ('parallelism_dimension', 'c'))), Task('c1', 'compute', 6, ('c',), labels=(('task_role', 'TAIL'),))), context=(('category', 'adversarial'), ('description', 'Packing trap: flow-size-first seed gives 18; parallel {b, c} seed gives 13.')), parameters=(('structure', 'packing_trap'),))


def _validate_exchangeable_components(
    model: PreeSingleModel,
    components: Sequence[Sequence[str]],
    resources: dict[str, frozenset] | None = None,
) -> tuple[tuple[int, ...], ...]:
    """Certify that component permutation preserves every scheduling-relevant fact.

    The certificate covers: disjoint equal-width components; identical
    (kind, duration, role, labels) per position; identical intra-component
    dependency shape with no cross-component edges; and, when ``resources``
    is given (fixed multi-resource lift), identical resource sets per
    position.  Under these conditions component permutation is an automorphism
    of the labelled DAG plus resource mapping, so sorting component runtime
    vectors is an exact quotient rather than a heuristic hash.
    """

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
            if (task.kind, task.duration, task.label_map().get("task_role", ""), task.labels) != (
                expected.kind,
                expected.duration,
                expected.label_map().get("task_role", ""),
                expected.labels,
            ):
                raise ValueError("component task labels are not identical")
            if resources is not None:
                own = resources.get(task.task_id, frozenset())
                expected_set = resources.get(expected.task_id, frozenset())
                if own != expected_set:
                    raise ValueError("component resource sets are not identical")
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
