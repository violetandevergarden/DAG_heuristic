"""Stage 2 algorithms for single-channel communication-preemptive DAGs.

Every policy and search routine delegates event progression to
``PreemptiveDAGModel.step``.  This module only ranks legal communications or
searches the resulting public event states.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, replace
from time import perf_counter

from core.dag import BenchmarkDAG, topological_order
from core.execution.preemptive import (
    Action,
    PreemptiveDAGModel,
    PreemptiveScheduleResult,
    ScheduleState,
    result_from_trace,
)
from core.trace.preemptive import assert_preemptive_trace
from llm_structured.barrier import (
    build_context,
    has_barrier_signal,
    priority_key,
)

PriorityName = str
StateKey = tuple[object, ...]


@dataclass
class _SearchStats:
    explored: int = 0
    generated: int = 0
    duplicates: int = 0
    incumbent_prunes: int = 0
    lower_bound_prunes: int = 0
    peak_states: int = 0
    expanded_nodes: int = 0
    evaluated_candidates: int = 0
    fallback_count: int = 0


class _BudgetExceeded(RuntimeError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def validate_complex_chain(dag: BenchmarkDAG) -> None:
    """Validate the Stage 2 internal family contract.

    Stage 2 deliberately accepts raw general DAGs, including same-kind edges
    and multiple weak components.  Components are concurrent parts of one
    makespan instance, not separate jobs.  No canonicalization or silent
    chainification is performed.
    """

    errors = dag.validate()
    if not dag.tasks:
        errors.append("complex_chain requires at least one task")
    for task in dag.tasks:
        if task.kind == "comm" and task.duration <= 0:
            errors.append(f"{task.task_id}: communication work must be positive")
    if errors:
        raise ValueError(f"invalid complex_chain DAG {dag.name}: {errors}")


def schedule_longest_tail(dag: BenchmarkDAG) -> PreemptiveScheduleResult:
    """Schedule the largest exclusive residual downstream tail first."""

    return schedule_priority(dag, "longest_tail")


def schedule_barrier_policy(
    dag: BenchmarkDAG,
    mode: str = "tail_barrier",
    *,
    trigger: str | None = None,
) -> PreemptiveScheduleResult:
    """Run an explicit barrier-score ablation on the public simulator.

    ``mode`` is one of ``barrier_only``, ``unlock_only``, ``tail``,
    ``tail_unlock``, ``tail_barrier`` or ``tail_unlock_barrier``.  The context
    is built once per stable decision state and the simulator remains the sole
    owner of legality and time advancement.  When ``trigger`` is set, the
    barrier score is evaluated only for states with a residual barrier or
    unlock signal; other states use the LT choice.
    """

    validate_complex_chain(dag)
    model = PreemptiveDAGModel(dag)
    state = model.initial_state()
    actions: list[Action] = []
    while not model.is_finished(state):
        eligible = model.eligible_communications(state)
        if not eligible:
            action = Action.wait()
        else:
            context = build_context(model, state, roots=eligible)
            snapshots = {item: priority_key(context, item, mode) for item in eligible}
            selected = min(eligible, key=lambda item: snapshots[item])
            if trigger is not None:
                if trigger not in {"barrier_only", "barrier_or_unlock"}:
                    raise ValueError(f"unsupported barrier trigger: {trigger}")
                triggered = (
                    priority_key(context, selected, "barrier_only")[0] < 0
                    if trigger == "barrier_only"
                    else has_barrier_signal(context, selected)
                )
                if not triggered:
                    selected = _baseline_choice(model, state, "longest_tail")
            action = Action.run(selected)
        actions.append(action)
        state = model.step(state, action).after
    return _result(model, actions)


def schedule_barrier_safeguarded(
    dag: BenchmarkDAG,
    *,
    mode: str = "tail_barrier",
    trigger: str = "barrier_or_unlock",
    max_rollouts: int | None = None,
) -> PreemptiveScheduleResult:
    """Run a triggered barrier candidate and protect the LT incumbent.

    Longest-tail is the incumbent and is returned whenever the complete
    candidate run is not strictly better.  ``trigger`` limits barrier scoring
    to residual barrier/unlock states; ``max_rollouts`` is retained as an
    explicit budget option for callers and currently permits zero candidate
    evaluation as a conservative mode.  Both schedules use public simulator
    transitions; no second event model is introduced.

    This is deliberately a protected candidate policy, not a claim that the
    barrier score dominates longest-tail.  A final whole-schedule comparison
    is retained because a locally better LT suffix is not a global proof.
    """

    if mode not in {"barrier_only", "tail_barrier", "tail_unlock_barrier"}:
        raise ValueError(f"unsupported safeguarded barrier mode: {mode}")
    if trigger not in {"barrier_only", "barrier_or_unlock"}:
        raise ValueError(f"unsupported barrier trigger: {trigger}")
    if max_rollouts is not None and max_rollouts < 0:
        raise ValueError("max_rollouts must be non-negative or None")

    validate_complex_chain(dag)
    baseline = schedule_longest_tail(dag)
    if max_rollouts == 0:
        candidate_result = baseline
    else:
        candidate_result = schedule_barrier_policy(dag, mode, trigger=trigger)
    fallback_reasons: list[str] = []
    if candidate_result.makespan < baseline.makespan:
        return replace(
            candidate_result,
            fallback_count=0,
            fallback_reasons=tuple(fallback_reasons),
        )
    fallback_reasons.append("complete_candidate_not_better_than_longest_tail")
    return replace(
        baseline,
        fallback_count=1,
        fallback_reasons=tuple(fallback_reasons),
    )


def schedule_selective_barrier_rollout(
    dag: BenchmarkDAG,
    *,
    max_triggers: int = 8,
    time_limit_s: float | None = 2.0,
) -> PreemptiveScheduleResult:
    """Enhance LT only at barrier states using a one-action rollout.

    At a triggered state the planner compares the LT first action with the
    strongest barrier/unlock candidate.  Each action is followed by the same
    LT completion policy in the public simulator.  The candidate is committed
    only on strict residual-cost improvement.  This is an online, state-level
    safeguard; it does not run two complete candidate policies and select one
    after observing their final makespans.
    """

    if max_triggers < 0:
        raise ValueError("max_triggers must be non-negative")
    if time_limit_s is not None and time_limit_s < 0:
        raise ValueError("time_limit_s must be non-negative or None")
    validate_complex_chain(dag)
    model = PreemptiveDAGModel(dag)
    state = model.initial_state()
    actions: list[Action] = []
    started = perf_counter()
    decisions = triggered = improvements = completion_calls = fallback_count = 0
    fallback_reasons: list[str] = []

    def completion_cost(after: ScheduleState) -> int:
        nonlocal completion_calls
        completion_calls += 1
        suffix = _complete_actions(model, after, "longest_tail")
        return _apply_actions(model, after, suffix).time

    while not model.is_finished(state):
        eligible = model.eligible_communications(state)
        if not eligible:
            action = Action.wait()
        else:
            decisions += 1
            baseline_id = _baseline_choice(model, state, "longest_tail")
            context = build_context(model, state, roots=eligible)
            candidate_id = min(
                eligible, key=lambda item: priority_key(context, item, "barrier_only")
            )
            has_signal = has_barrier_signal(context, candidate_id)
            budget_ok = triggered < max_triggers and (
                time_limit_s is None or perf_counter() - started < time_limit_s
            )
            selected = baseline_id
            if candidate_id != baseline_id and has_signal and budget_ok:
                triggered += 1
                baseline_after = model.step(state, Action.run(baseline_id)).after
                candidate_after = model.step(state, Action.run(candidate_id)).after
                baseline_cost = completion_cost(baseline_after)
                candidate_cost = completion_cost(candidate_after)
                if candidate_cost < baseline_cost:
                    selected = candidate_id
                    improvements += 1
            elif candidate_id != baseline_id and has_signal and not budget_ok:
                fallback_count += 1
                reason = (
                    "selective_trigger_limit"
                    if triggered >= max_triggers
                    else "selective_time_limit"
                )
                if reason not in fallback_reasons:
                    fallback_reasons.append(reason)
            action = Action.run(selected)
        actions.append(action)
        state = model.step(state, action).after
    result = _result(model, actions)
    return replace(
        result,
        runtime_ms=(perf_counter() - started) * 1000,
        evaluated_candidates=completion_calls,
        fallback_count=fallback_count,
        fallback_reasons=tuple(fallback_reasons),
        planner_decisions=decisions,
        planner_triggered=triggered,
        planner_improvements=improvements,
        completion_calls=completion_calls,
    )


def schedule_priority(
    dag: BenchmarkDAG,
    priority: PriorityName = "longest_tail",
) -> PreemptiveScheduleResult:
    """Run a deterministic work-conserving Stage 2 priority policy.

    FIFO is history-aware: the first event time at which a communication is
    eligible is retained across later pauses.  All other policies are
    memoryless functions of the current residual state.  Ties use task ID.
    """

    if priority in {
        "barrier_only",
        "unlock_only",
        "tail_unlock",
        "tail_barrier",
        "tail_unlock_barrier",
    }:
        return schedule_barrier_policy(dag, priority)
    validate_complex_chain(dag)
    model = PreemptiveDAGModel(dag)
    state = model.initial_state()
    actions: list[Action] = []
    first_eligible: dict[str, int] = {}
    while not model.is_finished(state):
        eligible = model.eligible_communications(state)
        for task_id in eligible:
            first_eligible.setdefault(task_id, state.time)
        if not eligible:
            action = Action.wait()
        else:
            tail = residual_tail(model, state, eligible)
            if priority == "fifo":
                selected = min(eligible, key=lambda item: (first_eligible[item], item))
            else:
                selected = min(
                    eligible,
                    key=lambda item: _priority_key(model, state, item, priority, tail),
                )
            action = Action.run(selected)
        actions.append(action)
        state = model.step(state, action).after
    return _result(model, actions)


def schedule_rollout(
    dag: BenchmarkDAG,
    *,
    top_k: int | None = 2,
    depth: int = 1,
    candidate_mode: str = "longest_tail",
    completion_priority: str = "longest_tail",
    max_expansions: int | None = None,
    time_limit_s: float | None = None,
    use_memo: bool = True,
) -> PreemptiveScheduleResult:
    """Receding-horizon event rollout with an explicit decision depth.

    ``depth`` counts communication decisions only; forced-idle transitions do
    not consume depth.  The completion-policy action is always retained in a
    finite shortlist, so an unexhausted search has a baseline incumbent.
    Deterministic expansion and wall-clock budgets fall back to the completion
    policy and are reported in the result.
    """

    validate_complex_chain(dag)
    if depth < 1:
        raise ValueError("rollout depth must be at least one")
    if top_k is not None and top_k < 1:
        raise ValueError("rollout top_k must be positive or None")
    model = PreemptiveDAGModel(dag)
    state = model.initial_state()
    actions: list[Action] = []
    stats = _SearchStats()
    started = perf_counter()
    termination_reason: str | None = None
    memo: dict[tuple[int, StateKey], int] = {}

    def check_budget() -> None:
        if max_expansions is not None and stats.expanded_nodes >= max_expansions:
            raise _BudgetExceeded("node_expansion_limit")
        if time_limit_s is not None and perf_counter() - started >= time_limit_s:
            raise _BudgetExceeded("time_limit")

    def evaluate(current: ScheduleState, remaining_depth: int) -> int:
        """Return residual completion cost, not an absolute finish time.

        The normalized key intentionally omits absolute time.  Caching a
        residual cost therefore preserves the future-equivalence proof,
        whereas caching an absolute makespan would not.
        """

        forced_state, _forced = _advance_forced_idle(model, current)
        forced_elapsed = forced_state.time - current.time
        if model.is_finished(forced_state):
            return forced_elapsed
        memo_key = (remaining_depth, normalized_state_key(forced_state))
        if use_memo:
            cached = memo.get(memo_key)
            if cached is not None:
                stats.duplicates += 1
                return forced_elapsed + cached
        if remaining_depth == 0:
            suffix = _complete_actions(model, forced_state, completion_priority)
            residual = _apply_actions(model, forced_state, suffix).time - forced_state.time
            if use_memo:
                memo[memo_key] = residual
            return forced_elapsed + residual
        check_budget()
        stats.expanded_nodes += 1
        eligible = model.eligible_communications(forced_state)
        tail = residual_tail(model, forced_state, eligible)
        ranked = _rank_candidates(
            model,
            forced_state,
            eligible,
            tail,
            top_k,
            candidate_mode,
            completion_priority,
        )
        best = float("inf")
        for task_id in ranked:
            check_budget()
            stats.evaluated_candidates += 1
            after = model.step(forced_state, Action.run(task_id)).after
            elapsed = after.time - forced_state.time
            best = min(best, elapsed + evaluate(after, remaining_depth - 1))
        residual = int(best)
        if use_memo:
            memo[memo_key] = residual
        return forced_elapsed + residual

    while not model.is_finished(state):
        eligible = model.eligible_communications(state)
        if not eligible:
            action = Action.wait()
        elif termination_reason is not None:
            action = Action.run(_baseline_choice(model, state, completion_priority))
        else:
            tail = residual_tail(model, state, eligible)
            ranked = _rank_candidates(
                model,
                state,
                eligible,
                tail,
                top_k,
                candidate_mode,
                completion_priority,
            )
            candidates: list[tuple[int, str]] = []
            try:
                for task_id in ranked:
                    check_budget()
                    stats.evaluated_candidates += 1
                    after = model.step(state, Action.run(task_id)).after
                    candidates.append(
                        (after.time - state.time + evaluate(after, depth - 1), task_id)
                    )
            except _BudgetExceeded as error:
                termination_reason = error.reason
                stats.fallback_count += 1
            selected = (
                min(candidates)[1]
                if candidates
                else _baseline_choice(model, state, completion_priority)
            )
            action = Action.run(selected)
        actions.append(action)
        state = model.step(state, action).after
    result = _result(model, actions)
    return replace(
        result,
        runtime_ms=(perf_counter() - started) * 1000,
        deduplicated_states=stats.duplicates,
        peak_states=len(memo),
        termination_reason=termination_reason,
        expanded_nodes=stats.expanded_nodes,
        evaluated_candidates=stats.evaluated_candidates,
        fallback_count=stats.fallback_count,
    )


def beam_search(
    dag: BenchmarkDAG,
    *,
    width: int = 8,
    horizon: int | None = None,
    max_expansions: int | None = None,
    time_limit_s: float | None = None,
) -> PreemptiveScheduleResult:
    """Decision-depth beam using the proven normalized Exact key.

    Equal normalized states are future-equivalent under the Stage 2 contract;
    the earlier representative therefore time-dominates the later one.  The
    Longest-tail completion schedule is retained as an incumbent, including
    when a horizon or budget truncates search.
    """

    validate_complex_chain(dag)
    if width < 1:
        raise ValueError("beam width must be positive")
    if horizon is not None and horizon < 1:
        raise ValueError("beam horizon must be positive or None")
    model = PreemptiveDAGModel(dag)
    initial = model.initial_state()
    incumbent_actions = _complete_actions(model, initial, "longest_tail")
    incumbent_finish = _apply_actions(model, initial, incumbent_actions).time
    frontier: list[tuple[ScheduleState, tuple[Action, ...]]] = [(initial, ())]
    stats = _SearchStats()
    started = perf_counter()
    decision_depth = 0
    termination_reason: str | None = None

    def budget_exhausted() -> str | None:
        if max_expansions is not None and stats.expanded_nodes >= max_expansions:
            return "node_expansion_limit"
        if time_limit_s is not None and perf_counter() - started >= time_limit_s:
            return "time_limit"
        return None

    while frontier and (horizon is None or decision_depth < horizon):
        children: dict[StateKey, tuple[ScheduleState, tuple[Action, ...]]] = {}
        for raw_state, raw_prefix in frontier:
            reason = budget_exhausted()
            if reason is not None:
                termination_reason = reason
                break
            state, forced = _advance_forced_idle(model, raw_state)
            prefix = (*raw_prefix, *forced)
            if model.is_finished(state):
                if state.time < incumbent_finish:
                    incumbent_finish, incumbent_actions = state.time, prefix
                continue
            stats.expanded_nodes += 1
            for task_id in model.eligible_communications(state):
                stats.evaluated_candidates += 1
                action = Action.run(task_id)
                after = model.step(state, action).after
                after, forced_after = _advance_forced_idle(model, after)
                candidate_prefix = (*prefix, action, *forced_after)
                suffix = _complete_actions(model, after, "longest_tail")
                predicted = _apply_actions(model, after, suffix).time
                if predicted < incumbent_finish:
                    incumbent_finish = predicted
                    incumbent_actions = (*candidate_prefix, *suffix)
                key = normalized_state_key(after)
                old = children.get(key)
                candidate = (after, candidate_prefix)
                if old is None or after.time < old[0].time:
                    if old is not None:
                        stats.duplicates += 1
                    children[key] = candidate
                else:
                    stats.duplicates += 1
        if termination_reason is not None:
            stats.fallback_count += 1
            break
        scored: list[tuple[int, int, tuple[Action, ...], ScheduleState]] = []
        for state, prefix in children.values():
            suffix = _complete_actions(model, state, "longest_tail")
            predicted = _apply_actions(model, state, suffix).time
            scored.append((predicted, state.time, prefix, state))
        scored.sort(key=lambda item: (item[0], item[1], _action_key(item[2])))
        frontier = [(item[3], item[2]) for item in scored[:width]]
        stats.peak_states = max(stats.peak_states, len(frontier))
        decision_depth += 1

    result = _result(model, incumbent_actions)
    return replace(
        result,
        runtime_ms=(perf_counter() - started) * 1000,
        deduplicated_states=stats.duplicates,
        peak_states=stats.peak_states,
        termination_reason=termination_reason,
        expanded_nodes=stats.expanded_nodes,
        evaluated_candidates=stats.evaluated_candidates,
        fallback_count=stats.fallback_count,
    )


def exact_oracle(
    dag: BenchmarkDAG,
    *,
    max_states: int = 500_000,
    time_limit_s: float | None = None,
    normalized: bool = True,
    bound_mode: str = "combined",
    use_memo: bool = True,
    use_incumbent: bool = True,
) -> PreemptiveScheduleResult:
    """Branch-and-bound Exact over public event transitions.

    Completed enumeration returns ``status='optimal'``.  A state or time
    budget returns the Longest-tail incumbent as ``status='feasible'`` with a
    structured ``termination_reason``; callers must not treat it as ground
    truth.  ``normalized=False`` selects the full audit key.
    """

    validate_complex_chain(dag)
    if bound_mode not in {"none", "communication", "path", "combined"}:
        raise ValueError(
            "bound_mode must be one of: none, communication, path, combined"
        )
    if max_states < 1:
        raise ValueError("max_states must be positive")
    model = PreemptiveDAGModel(dag)
    initial = model.initial_state()
    started = perf_counter()
    stats = _SearchStats()
    memo: dict[StateKey, tuple[int, tuple[Action, ...]]] = {}
    key_fn: Callable[[ScheduleState], StateKey] = (
        normalized_state_key if normalized else audit_state_key
    )
    # The reported certificate remains the strongest proven bound even when
    # an ablation disables it for pruning.
    root_lower_bound = remaining_lower_bound(model, initial, mode="combined")
    incumbent_actions = _complete_actions(model, initial, "longest_tail")

    def check_budget() -> None:
        if stats.explored >= max_states:
            raise _BudgetExceeded("state_limit")
        if time_limit_s is not None and perf_counter() - started >= time_limit_s:
            raise _BudgetExceeded("time_limit")

    def search(state: ScheduleState) -> tuple[int, tuple[Action, ...]]:
        state_key = key_fn(state)
        if use_memo:
            cached = memo.get(state_key)
            if cached is not None:
                stats.duplicates += 1
                return cached
        check_budget()
        stats.explored += 1
        stats.peak_states = max(stats.peak_states, len(memo) + 1)
        if model.is_finished(state):
            result = (0, ())
            if use_memo:
                memo[state_key] = result
            return result

        completion = _complete_actions(model, state, "longest_tail")
        incumbent_cost = (
            _apply_actions(model, state, completion).time - state.time
            if use_incumbent
            else float("inf")
        )
        best: tuple[int, tuple[str, str], tuple[Action, ...]] | None = None
        for action in model.legal_actions(state):
            transition = model.step(state, action)
            stats.generated += 1
            elapsed = transition.after.time - state.time
            child_bound = remaining_lower_bound(
                model, transition.after, mode=bound_mode
            )
            # Equality is still explored so Exact preserves the stable
            # lexicographically smallest optimal action trace used by existing
            # downstream teachers.  Only a strict bound proves the branch
            # cannot improve that deterministic optimum tuple.
            if bound_mode != "none" and elapsed + child_bound > incumbent_cost:
                stats.incumbent_prunes += 1
                stats.lower_bound_prunes += 1
                continue
            child_cost, suffix = search(transition.after)
            candidate = elapsed + child_cost
            candidate_entry = (
                candidate,
                (action.kind, action.task_id or ""),
                (action, *suffix),
            )
            if best is None or candidate_entry[:2] < best[:2]:
                best = candidate_entry
            incumbent_cost = min(incumbent_cost, candidate)
        if best is None:
            raise RuntimeError("unfinished state has no exact successor")
        result = (best[0], best[2])
        if use_memo:
            memo[state_key] = result
        return result

    try:
        _cost, actions = search(initial)
    except _BudgetExceeded as error:
        result = _result(model, incumbent_actions)
        return replace(
            result,
            explored_states=stats.explored,
            generated_transitions=stats.generated,
            deduplicated_states=stats.duplicates,
            pruned_states=stats.lower_bound_prunes,
            incumbent_prunes=stats.incumbent_prunes,
            lower_bound_prunes=stats.lower_bound_prunes,
            peak_states=stats.peak_states,
            lower_bound=root_lower_bound,
            runtime_ms=(perf_counter() - started) * 1000,
            status="feasible",
            termination_reason=error.reason,
        )

    result = _result(model, actions)
    return replace(
        result,
        explored_states=stats.explored,
        generated_transitions=stats.generated,
        deduplicated_states=stats.duplicates,
        pruned_states=stats.lower_bound_prunes,
        incumbent_prunes=stats.incumbent_prunes,
        lower_bound_prunes=stats.lower_bound_prunes,
        peak_states=stats.peak_states,
        lower_bound=root_lower_bound,
        runtime_ms=(perf_counter() - started) * 1000,
        status="optimal",
    )


def exact_oracle_uncompressed(
    dag: BenchmarkDAG,
    *,
    max_states: int = 500_000,
    time_limit_s: float | None = None,
    bound_mode: str = "combined",
    use_memo: bool = True,
    use_incumbent: bool = True,
) -> PreemptiveScheduleResult:
    """Audit Exact retaining absolute time and every runtime field in its key."""

    return exact_oracle(
        dag,
        max_states=max_states,
        time_limit_s=time_limit_s,
        normalized=False,
        bound_mode=bound_mode,
        use_memo=use_memo,
        use_incumbent=use_incumbent,
    )


def monte_carlo(
    dag: BenchmarkDAG,
    *,
    samples: int = 64,
    seed: int = 0,
) -> PreemptiveScheduleResult:
    """Historical reproducible sampler, retained outside the active registry."""

    validate_complex_chain(dag)
    model = PreemptiveDAGModel(dag)
    rng = random.Random(seed)
    candidates: list[PreemptiveScheduleResult] = [schedule_longest_tail(dag)]
    for _ in range(samples):
        state = model.initial_state()
        actions: list[Action] = []
        while not model.is_finished(state):
            eligible = model.eligible_communications(state)
            if not eligible:
                action = Action.wait()
            else:
                tail = residual_tail(model, state, eligible)
                ranked = sorted(eligible, key=lambda item: (-tail[item], item))
                pool = ranked[: max(1, min(3, len(ranked)))] if rng.random() < 0.7 else ranked
                action = Action.run(rng.choice(pool))
            actions.append(action)
            state = model.step(state, action).after
        candidates.append(_result(model, actions))
    return min(candidates, key=lambda result: (result.makespan, result.dispatches))


def audit_state_key(state: ScheduleState) -> StateKey:
    """Full event-state key used by the audit Exact."""

    return (state.time, state.tasks, state.last_communication)


def normalized_state_key(state: ScheduleState) -> StateKey:
    """Future-equivalent Stage 2 key under zero-cost, no-external-time semantics."""

    return tuple((runtime.status, runtime.remaining) for runtime in state.tasks)


def remaining_lower_bound(
    model: PreemptiveDAGModel,
    state: ScheduleState,
    *,
    mode: str = "combined",
) -> int:
    """Return a selectable safe residual lower bound for Exact ablation."""

    if mode not in {"none", "communication", "path", "combined"}:
        raise ValueError(f"unknown lower-bound mode: {mode}")

    tasks = model.task_map
    communication_work = sum(
        _own_remaining(model, state, task_id)
        for task_id in model.task_ids
        if tasks[task_id].kind == "comm"
    )
    longest_path = max(residual_tail(model, state).values(), default=0)
    if mode == "none":
        return 0
    if mode == "communication":
        return communication_work
    if mode == "path":
        return longest_path
    return max(communication_work, longest_path)


def residual_tail(
    model: PreemptiveDAGModel,
    state: ScheduleState,
    roots: tuple[str, ...] | list[str] | None = None,
) -> dict[str, int]:
    """Longest residual path including each unfinished task's own work."""

    children = model.children
    if roots is None:
        order = model.task_ids
    else:
        reachable = set(roots)
        pending = list(roots)
        while pending:
            current = pending.pop()
            for child in children[current]:
                if child not in reachable:
                    reachable.add(child)
                    pending.append(child)
        order = tuple(sorted(reachable, key=model.index.__getitem__))
    tail: dict[str, int] = {}
    for task_id in reversed(order):
        tail[task_id] = _own_remaining(model, state, task_id) + max(
            (tail[child] for child in children[task_id]), default=0
        )
    return tail


def immediate_release_gain(
    model: PreemptiveDAGModel,
    state: ScheduleState,
    task_id: str,
) -> int:
    """Sum work immediately released if ``task_id`` were completed now.

    The hypothetical closure includes zero-duration compute nodes, matching
    the simulator's automatic compute closure.  Multiple newly ready positive
    tasks are aggregated by sum; this is a local release score, not a path
    length or an end-to-end benefit claim.
    """

    tasks = model.task_map
    completed = {
        item
        for item in model.task_ids
        if model.task_runtime(state, item).status == "completed"
    }
    completed.add(task_id)
    already_ready = set(model.eligible_communications(state)) | set(model.active_computes(state))
    changed = True
    while changed:
        changed = False
        for item in model.task_ids:
            task = tasks[item]
            runtime = model.task_runtime(state, item)
            if item in completed or runtime.status != "pending":
                continue
            if task.kind == "compute" and task.duration == 0 and set(task.deps) <= completed:
                completed.add(item)
                changed = True
    released = []
    for item in model.task_ids:
        if item in completed or item in already_ready:
            continue
        task = tasks[item]
        runtime = model.task_runtime(state, item)
        if runtime.status == "pending" and set(task.deps) <= completed:
            released.append(task.duration)
    return sum(released)


def immediate_compute_delay(
    model: PreemptiveDAGModel,
    state: ScheduleState,
    task_id: str,
) -> int:
    """Longest compute delay made ready immediately by candidate completion.

    Zero-duration compute closure is traversed, but communication work and the
    breadth/sum of newly ready tasks are deliberately excluded.  The latter is
    the separate ``immediate_release_gain`` feature.
    """

    tasks = model.task_map
    completed = {
        item
        for item in model.task_ids
        if model.task_runtime(state, item).status == "completed"
    }
    completed.add(task_id)
    already_active = set(model.active_computes(state))
    changed = True
    while changed:
        changed = False
        for item in model.task_ids:
            task = tasks[item]
            runtime = model.task_runtime(state, item)
            if item in completed or runtime.status != "pending":
                continue
            if task.kind == "compute" and task.duration == 0 and set(task.deps) <= completed:
                completed.add(item)
                changed = True
    return max(
        (
            task.duration
            for item, task in tasks.items()
            if item not in completed
            and item not in already_active
            and task.kind == "compute"
            and model.task_runtime(state, item).status == "pending"
            and set(task.deps) <= completed
        ),
        default=0,
    )


def direct_last_blocker_gain(
    model: PreemptiveDAGModel,
    state: ScheduleState,
    task_id: str,
    tail: dict[str, int] | None = None,
) -> int:
    """Residual tails of direct joins for which the candidate is last blocker."""

    tails = tail if tail is not None else residual_tail(model, state, [task_id])
    tasks = model.task_map
    gain = 0
    for child in _children(model)[task_id]:
        if len(tasks[child].deps) < 2:
            continue
        others = (item for item in tasks[child].deps if item != task_id)
        if all(model.task_runtime(state, item).status == "completed" for item in others):
            gain += tails[child]
    return gain


def unique_downstream_work(
    model: PreemptiveDAGModel,
    state: ScheduleState,
    task_id: str,
) -> int:
    """Residual work in the candidate's reachable sub-DAG, counted once.

    This is the explicit shared-downstream de-duplication feature: a node
    reached through several fork/join paths contributes once, not once per
    path.
    """

    descendants = _descendants(model, task_id)
    return sum(_own_remaining(model, state, item) for item in descendants)


def downstream_communication_demand(
    model: PreemptiveDAGModel,
    state: ScheduleState,
    task_id: str,
) -> int:
    """Unique residual channel demand downstream of a candidate."""

    tasks = model.task_map
    return sum(
        _own_remaining(model, state, item)
        for item in _descendants(model, task_id)
        if tasks[item].kind == "comm"
    )


def barrier_urgency(
    model: PreemptiveDAGModel,
    state: ScheduleState,
    task_id: str,
    tail: dict[str, int] | None = None,
) -> int:
    """Residual urgency of distinct reachable joins/barriers.

    Each reachable multi-predecessor node contributes its residual tail once.
    A direct last-blocker gets the same contribution, while a more distant
    branch is discounted by its residual distance to the barrier.  This is a
    deterministic structural feature, not a proven lower bound.
    """

    tails = tail if tail is not None else residual_tail(model, state, [task_id])
    tasks = model.task_map
    children = _children(model)
    distance: dict[str, int] = {task_id: 0}
    for current in topological_order(model.dag):
        if current not in distance:
            continue
        for child in children[current]:
            candidate = distance[current] + (
                0 if current == task_id else _own_remaining(model, state, current)
            )
            distance[child] = max(distance.get(child, 0), candidate)
    return sum(
        max(0, tails[item] - distance[item])
        for item in distance
        if item != task_id and len(tasks[item].deps) > 1
    )


def _priority_key(
    model: PreemptiveDAGModel,
    state: ScheduleState,
    task_id: str,
    priority: str,
    tail: dict[str, int],
) -> tuple[object, ...]:
    remaining = _own_remaining(model, state, task_id)
    exclusive_tail = tail[task_id] - remaining
    if priority == "spt":
        return (remaining, 0, task_id)
    if priority == "lpt":
        return (-remaining, 0, task_id)
    if priority == "longest_delay":
        return (-immediate_compute_delay(model, state, task_id), -exclusive_tail, task_id)
    if priority == "release_gain":
        return (-immediate_release_gain(model, state, task_id), -exclusive_tail, task_id)
    if priority == "longest_tail":
        return (-exclusive_tail, 0, task_id)
    if priority == "lrpt":
        return (-tail[task_id], 0, task_id)
    if priority == "join_aware":
        return (
            -direct_last_blocker_gain(model, state, task_id, tail),
            -exclusive_tail,
            task_id,
        )
    if priority == "barrier_aware":
        return (-barrier_urgency(model, state, task_id, tail), -exclusive_tail, task_id)
    if priority == "shared_downstream":
        return (-unique_downstream_work(model, state, task_id), -exclusive_tail, task_id)
    if priority == "downstream_demand":
        return (
            -downstream_communication_demand(model, state, task_id),
            -exclusive_tail,
            task_id,
        )
    if priority == "structure_aware":
        return (
            -barrier_urgency(model, state, task_id, tail),
            -downstream_communication_demand(model, state, task_id),
            -unique_downstream_work(model, state, task_id),
            -exclusive_tail,
            task_id,
        )
    raise ValueError(f"unknown preemptive priority: {priority}")


def _baseline_choice(
    model: PreemptiveDAGModel,
    state: ScheduleState,
    priority: str,
) -> str:
    eligible = model.eligible_communications(state)
    tail = residual_tail(model, state, eligible)
    return min(eligible, key=lambda item: _priority_key(model, state, item, priority, tail))


def _complete_actions(
    model: PreemptiveDAGModel,
    state: ScheduleState,
    priority: str,
) -> tuple[Action, ...]:
    actions: list[Action] = []
    while not model.is_finished(state):
        eligible = model.eligible_communications(state)
        action = (
            Action.run(_baseline_choice(model, state, priority))
            if eligible
            else Action.wait()
        )
        actions.append(action)
        state = model.step(state, action).after
    return tuple(actions)


def _rank_candidates(
    model: PreemptiveDAGModel,
    state: ScheduleState,
    eligible: tuple[str, ...],
    tail: dict[str, int],
    top_k: int | None,
    mode: str,
    completion_priority: str,
) -> list[str]:
    if mode == "tail":
        mode = "longest_tail"
    if mode not in {
        "longest_tail",
        "lrpt",
        "join",
        "structure",
        "barrier",
        "hybrid",
        "hybrid_barrier",
    }:
        raise ValueError(f"unknown candidate mode: {mode}")
    baseline = min(
        eligible,
        key=lambda item: _priority_key(
            model, state, item, completion_priority, tail
        ),
    )
    longest = sorted(
        eligible,
        key=lambda item: _priority_key(model, state, item, "longest_tail", tail),
    )
    lrpt = sorted(
        eligible,
        key=lambda item: _priority_key(model, state, item, "lrpt", tail),
    )
    join = sorted(
        eligible,
        key=lambda item: _priority_key(model, state, item, "join_aware", tail),
    )
    structure = sorted(
        eligible,
        key=lambda item: _priority_key(model, state, item, "structure_aware", tail),
    )
    barrier = []
    if mode in {"barrier", "hybrid_barrier"}:
        barrier_context = build_context(model, state, roots=eligible)
        barrier = sorted(
            eligible,
            key=lambda item: priority_key(barrier_context, item, "tail_barrier"),
        )
    ordered = {
        "longest_tail": longest,
        "lrpt": lrpt,
        "join": join,
        "structure": structure,
        "barrier": barrier,
        "hybrid": _interleave(longest, join, structure, lrpt),
        "hybrid_barrier": _interleave(longest, barrier, join, structure, lrpt),
    }[mode]
    selected = [baseline, *(item for item in ordered if item != baseline)]
    return selected if top_k is None else selected[:top_k]


def _interleave(*rankings: list[str]) -> list[str]:
    result: list[str] = []
    for index in range(max((len(items) for items in rankings), default=0)):
        for items in rankings:
            if index < len(items) and items[index] not in result:
                result.append(items[index])
    return result


def _advance_forced_idle(
    model: PreemptiveDAGModel,
    state: ScheduleState,
) -> tuple[ScheduleState, tuple[Action, ...]]:
    actions: list[Action] = []
    while (
        not model.is_finished(state)
        and not model.eligible_communications(state)
    ):
        action = Action.wait()
        actions.append(action)
        state = model.step(state, action).after
    return state, tuple(actions)


def _apply_actions(
    model: PreemptiveDAGModel,
    state: ScheduleState,
    actions: tuple[Action, ...],
) -> ScheduleState:
    for action in actions:
        state = model.step(state, action).after
    return state


def _own_remaining(
    model: PreemptiveDAGModel,
    state: ScheduleState,
    task_id: str,
) -> int:
    runtime = model.task_runtime(state, task_id)
    if runtime.status == "completed":
        return 0
    if runtime.status in {"running", "suspended"}:
        return runtime.remaining
    return model.task_map[task_id].duration


def _children(model: PreemptiveDAGModel) -> dict[str, list[str]]:
    return model.children


def _descendants(model: PreemptiveDAGModel, task_id: str) -> set[str]:
    children = _children(model)
    result: set[str] = set()
    pending = list(children[task_id])
    while pending:
        item = pending.pop()
        if item in result:
            continue
        result.add(item)
        pending.extend(children[item])
    return result


def _result(
    model: PreemptiveDAGModel,
    actions: tuple[Action, ...] | list[Action],
) -> PreemptiveScheduleResult:
    trace = model.run(actions)
    assert_preemptive_trace(model, trace)
    return result_from_trace(trace)


def _action_key(actions: tuple[Action, ...]) -> tuple[tuple[str, str], ...]:
    return tuple((action.kind, action.task_id or "") for action in actions)
