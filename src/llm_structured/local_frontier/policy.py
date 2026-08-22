"""Online local-frontier diagnostic and safeguarded experimental policy."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from core.dag import BenchmarkDAG
from core.execution.preemptive import Action, PreemptiveDAGModel, PreemptiveScheduleResult
from single_channel.complex_chain.preemptive import solver

from .accounting import FrontierBudget
from .audit import LocalSearchDecision
from .candidates import candidate_pair
from .config import LocalFrontierConfig, diagnostic_config
from .evaluator import evaluate_pair
from .region import build_local_region


@dataclass(frozen=True)
class LocalFrontierResult:
    schedule: PreemptiveScheduleResult
    decisions: tuple[LocalSearchDecision, ...]
    evaluations: int
    changed_actions: int
    complete_evaluations: int
    fallback_count: int
    region_p95_nodes: int
    runtime_ms: float


def schedule_local_frontier(
    dag: BenchmarkDAG,
    config: LocalFrontierConfig | None = None,
) -> LocalFrontierResult:
    config = config or diagnostic_config()
    solver.validate_complex_chain(dag)
    model = PreemptiveDAGModel(dag)
    state = model.initial_state()
    actions: list[Action] = []
    audits: list[LocalSearchDecision] = []
    region_sizes: list[int] = []
    started = perf_counter()
    total_deadline = started + config.total_time_limit_s
    permanently_disabled = len(dag.tasks) > config.max_graph_tasks
    while not model.is_finished(state):
        eligible = model.eligible_communications(state)
        if not eligible:
            action = Action.wait()
        else:
            pair = candidate_pair(model, state)
            final = pair.baseline
            reason = "candidate_pair"
            region = None
            evaluation = None
            fallback = None
            triggered = pair.challenger is not None
            if permanently_disabled:
                triggered = False
                fallback = "graph_size_limit"
            elif perf_counter() >= total_deadline:
                permanently_disabled = True
                triggered = False
                fallback = "total_time_limit"
            elif pair.normalized_tail_margin is not None and pair.normalized_tail_margin > config.max_normalized_tail_margin:
                triggered = False
                reason = "tail_margin_gate"
            if triggered and pair.challenger is not None:
                region = build_local_region(
                    model, state, pair.baseline, pair.challenger,
                    max_nodes=config.max_local_nodes,
                )
                region_sizes.append(region.node_count)
                if not region.complete:
                    fallback = region.truncation_reason
                else:
                    now = perf_counter()
                    budget = FrontierBudget(
                        config.max_expansions,
                        now + config.per_decision_time_limit_s,
                        total_deadline,
                    )
                    evaluation = evaluate_pair(
                        model, state, region, depth=config.decision_depth, budget=budget,
                    )
                    if not evaluation.complete:
                        fallback = evaluation.fallback_reason
                    elif (
                        config.adoption_mode == "risk_controlled"
                        and evaluation.recommended_action == pair.challenger
                        and evaluation.proxy_gain >= config.min_proxy_gain
                    ):
                        final = pair.challenger
            audits.append(LocalSearchDecision(
                state.time, pair.baseline, pair.challenger, triggered, reason,
                region, evaluation, config.adoption_mode,
                evaluation.recommended_action if evaluation else pair.baseline,
                final, final != pair.baseline, fallback,
            ))
            action = Action.run(final)
        actions.append(action)
        state = model.step(state, action).after
    schedule = solver._result(model, actions)
    ordered = sorted(region_sizes)
    p95 = ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))] if ordered else 0
    return LocalFrontierResult(
        schedule, tuple(audits), sum(item.evaluation is not None for item in audits),
        sum(item.changed_lt for item in audits),
        sum(item.evaluation is not None and item.evaluation.complete for item in audits),
        sum(item.fallback_reason is not None for item in audits), p95,
        (perf_counter() - started) * 1000,
    )
