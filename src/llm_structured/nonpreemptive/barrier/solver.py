"""B0--B5 barrier policies layered on the frozen residual LT baseline."""

from __future__ import annotations

from dataclasses import asdict
from time import perf_counter

from llm_structured.nonpreemptive.baseline import longest_tail_action, make_adapter, schedule_baseline

from .contracts import BarrierBudget, BarrierConfig, BarrierDecision, BarrierResult
from .counterfactual import compare
from .features import action_features
from .graph import BarrierGraph


def schedule(benchmark, config: BarrierConfig | None = None) -> BarrierResult:
    config = BarrierConfig() if config is None else config
    if config.method == "lt":
        baseline = schedule_baseline(benchmark, "longest_tail", config.mode)
        return BarrierResult(
            "completed", baseline["makespan"], config.mode, config.method,
            BarrierResult.config_dict(config), (), (),
            {"decision_count": baseline["decisions"], "divergences_from_lt": 0,
             "fallbacks": 0, "voluntary_waits": baseline["voluntary_waits"],
             "voluntary_wait_time": baseline["voluntary_wait_time"],
             "forced_waits": baseline["forced_waits"], "forced_wait_time": baseline["forced_wait_time"],
             "barrier_count": 0, "graph_truncated": False,
             "wall_time_s": baseline["runtime_ms"] / 1000}, True,
        )
    started = perf_counter(); adapter = make_adapter(benchmark); graph = BarrierGraph.build(benchmark, max_barriers=config.max_tracked_barriers)
    state = adapter.initial_state(); actions = []; decisions = []; budget = BarrierBudget(); divergences = 0; fallbacks = 0
    try:
        while not adapter.is_finished(state):
            if perf_counter() - started > config.per_instance_soft_time_s: raise TimeoutError("soft instance budget")
            context = adapter.decision_context(state, config.mode)
            baseline = longest_tail_action(adapter, state, config.mode, context)
            legal = context.legal_actions
            starts = [item for item in legal if item.kind != "wait"]
            baseline_features = action_features(adapter, graph, state, baseline, config, budget, context)
            candidates = [(action_features(adapter, graph, state, item, config, budget, context), item) for item in starts if item != baseline]
            challenger_pair = max(candidates, key=lambda pair: (pair[0].barrier_key, pair[0].signature), default=None)
            challenger_features, challenger = challenger_pair if challenger_pair else (None, None)
            selected = baseline; reason = "lt"; ratio = None; values = {}
            if challenger is not None and not challenger_features.truncated:
                ratio = (baseline_features.tail - challenger_features.tail) / max(baseline_features.tail, 1)
                if config.method == "barrier_only": selected, reason = challenger, "barrier_only"
                elif config.method == "last_missing_tie" and challenger_features.tail == baseline_features.tail and challenger_features.barrier_key > baseline_features.barrier_key:
                    selected, reason = challenger, "last_missing_tie"
                elif config.method in {"margin", "counterfactual"} and ratio <= config.tail_margin_ratio and challenger_features.barrier_key > baseline_features.barrier_key:
                    if config.method == "margin": selected, reason = challenger, "margin"
                    else:
                        values = compare(adapter, state, (baseline, challenger), config.mode, budget, config, context)
                        if values is None: fallbacks += 1; reason = "counterfactual_budget_fallback"
                        elif values[str(adapter.signature(state, challenger))] < values[str(adapter.signature(state, baseline))]: selected, reason = challenger, "counterfactual"
            signature = adapter.signature(state, selected)
            if selected != baseline: divergences += 1
            decisions.append(asdict(BarrierDecision(len(decisions), state.time, adapter.signature(state, baseline),
                                                     None if challenger is None else adapter.signature(state, challenger), signature, reason, ratio,
                                                     baseline_features, challenger_features, values)))
            actions.append(signature); state = adapter.step(state, selected).after
        replay = adapter.replay(tuple(adapter.action_from_signature(item) for item in actions))
        return BarrierResult("completed", replay.makespan, config.mode, config.method, BarrierResult.config_dict(config), tuple(actions), tuple(decisions),
                             {**asdict(budget), "decision_count": len(decisions), "divergences_from_lt": divergences, "fallbacks": fallbacks,
                              "voluntary_waits": replay.voluntary_waits, "voluntary_wait_time": replay.voluntary_wait_time,
                              "forced_waits": replay.forced_waits, "forced_wait_time": replay.forced_wait_time,
                              "barrier_count": len(graph.barriers), "graph_truncated": len(graph.barriers) >= config.max_tracked_barriers,
                              "wall_time_s": perf_counter() - started}, True)
    except (TimeoutError, RuntimeError, ValueError, AssertionError) as error:
        return BarrierResult("timeout" if isinstance(error, TimeoutError) else "failed", None, config.mode, config.method,
                             BarrierResult.config_dict(config), tuple(actions), tuple(decisions), {**asdict(budget), "wall_time_s": perf_counter()-started}, False,
                             f"{type(error).__name__}: {error}")

