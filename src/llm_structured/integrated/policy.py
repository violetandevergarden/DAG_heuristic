"""Online Stage 4g policy with residual-LT as the safe deployment path."""

from __future__ import annotations

from dataclasses import dataclass, replace
from time import perf_counter

from core.dag import DAG
from core.execution.preemptive import PreeMultiModel
from core.execution.preemptive import Action, PreeSingleModel, PreemptiveScheduleResult
from llm_structured.integrated.config import IntegratedConfig
from llm_structured.integrated.decision import ComponentCost, IntegratedDecision
from llm_structured.integrated.safeguards import require_maximal, state_fingerprint
from muti_channel.preemptive import solver as multi_solver
from single_channel.complex_chain.preemptive import solver as single_solver


@dataclass(frozen=True)
class IntegratedSingleResult:
    schedule: PreemptiveScheduleResult
    config: IntegratedConfig
    decisions: tuple[IntegratedDecision, ...]
    component_calls: tuple[tuple[str, int], ...]
    fallback_count: int
    degraded_to_safe: bool


@dataclass(frozen=True)
class IntegratedMultiResult:
    schedule: multi_solver.MultiResult
    config: IntegratedConfig
    decisions: tuple[IntegratedDecision, ...]
    component_calls: tuple[tuple[str, int], ...]
    fallback_count: int
    degraded_to_safe: bool


def _check_deployment_config(config: IntegratedConfig, expected: str) -> None:
    if config.resource_mode != expected:
        raise ValueError(f"config resource_mode must be {expected}")
    if config.packing_mode != "lt_greedy" or config.rollout_mode != "off":
        raise ValueError("experimental components must be invoked by the experiment layer")


def schedule_single(dag: DAG, config: IntegratedConfig) -> IntegratedSingleResult:
    """Run the frozen single-channel integrated policy (residual LT)."""

    _check_deployment_config(config, "single")
    single_solver.validate_complex_chain(dag)
    model = PreeSingleModel(dag)
    audit_enabled = config.detailed_audit and len(dag.tasks) <= config.large_graph_safe_threshold
    degraded = config.detailed_audit and not audit_enabled
    state = model.initial_state()
    actions: list[Action] = []
    records: list[IntegratedDecision] = []
    started = perf_counter()
    while not model.is_finished(state):
        eligible = model.eligible_communications(state)
        if not eligible:
            action = Action.wait()
        else:
            tails = single_solver.residual_tail(model, state, eligible)
            scores = {
                item: (
                    -(
                        tails[item]
                        - (
                            model.task_runtime(state, item).remaining
                            or model.task_map[item].duration
                        )
                    ),
                    0,
                    item,
                )
                for item in eligible
            }
            selected = min(eligible, key=scores.__getitem__)
            action = Action.run(selected)
            if audit_enabled:
                records.append(
                    IntegratedDecision(
                        state.time,
                        state_fingerprint(state),
                        tuple(sorted(eligible)),
                        (selected,),
                        tuple((item, scores[item]) for item in sorted(eligible)),
                        ((selected,),),
                        "residual_lt",
                        False,
                        True,
                        (),
                        (selected,),
                        None,
                        None,
                        0,
                        0,
                        ComponentCost(),
                    )
                )
        actions.append(action)
        state = model.step(state, action).after
    result = single_solver._result(model, actions).with_stats(
        runtime_ms=(perf_counter() - started) * 1000,
    )
    return IntegratedSingleResult(
        result,
        config,
        tuple(records),
        (("packing", 0), ("rollout", 0), ("barrier", 0)),
        0,
        degraded,
    )


def schedule_multi(
    dag: DAG,
    resources: dict[str, frozenset[str]],
    config: IntegratedConfig,
) -> IntegratedMultiResult:
    """Run residual-LT greedy maximal packing on the public simulator."""

    _check_deployment_config(config, "fixed_multi")
    model = PreeMultiModel(dag, resources)
    audit_enabled = config.detailed_audit and len(dag.tasks) <= config.large_graph_safe_threshold
    degraded = config.detailed_audit and not audit_enabled
    state = model.initial_state()
    actions = []
    records: list[IntegratedDecision] = []
    started = perf_counter()
    while not model.finished(state):
        state, _idle = model.normalize_decision_state(state)
        if model.finished(state):
            break
        scores = multi_solver.score_tasks(model, state, "longest_tail")
        action = multi_solver.greedy_fill_from_task_scores(model, state, scores)
        require_maximal(model, state, action)
        if audit_enabled:
            records.append(
                IntegratedDecision(
                    state.time,
                    state_fingerprint(state),
                    tuple(sorted(model.eligible(state))),
                    action.communications,
                    tuple((item, scores[item]) for item in sorted(scores)),
                    (action.communications,),
                    "lt_greedy_maximal",
                    False,
                    True,
                    (),
                    action.communications,
                    None,
                    None,
                    0,
                    0,
                    ComponentCost(),
                )
            )
        actions.append(action)
        state = model.step(state, action)
    result = multi_solver._result(
        model,
        actions,
        runtime_ms=(perf_counter() - started) * 1000,
        lower_bound=multi_solver.remaining_lower_bound(model, model.initial_state()),
    )
    return IntegratedMultiResult(
        result,
        config,
        tuple(records),
        (("packing", len(records)), ("rollout", 0), ("barrier", 0)),
        0,
        degraded,
    )
