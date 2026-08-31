"""End-to-end Stage 4d policy and auditable fallback behavior."""

from __future__ import annotations

from dataclasses import asdict
import hashlib, json, random
from time import perf_counter

from .adapters import make_adapter
from .baseline import longest_tail_action
from .candidates import generate
from .contracts import BudgetLedger, DecisionRecord, RolloutConfig, RolloutResult, TriggerDecision
from .evaluator import BudgetExhausted, evaluate
from .features import compute
from .triggers import decide


def schedule(benchmark, config: RolloutConfig = RolloutConfig()) -> RolloutResult:
    started = perf_counter(); adapter = make_adapter(benchmark); state = adapter.initial_state()
    ledger = BudgetLedger(); records = []; actions = []; cache = {}; rng = random.Random(config.random_seed)
    fallback_count = 0
    while not adapter.is_finished(state):
        base = longest_tail_action(adapter, state, config.mode)
        candidates, generated_count, truncated = generate(adapter, state, config.mode, config.max_candidates_per_decision)
        if config.search_depth == 0 or config.max_candidates_per_decision < 2:
            candidates, generated_count, truncated = (base,), 1, False
            features = {"choice_count": 1, "lt_margin": None, "lt_margin_ratio": None, "duration_spread_ratio": 0.0,
                        "heuristic_disagreement": False, "crosses_event": False, "wait_available": base.kind == "wait", "resource_footprints": []}
        else:
            features = compute(adapter, state, candidates, ledger, config)
        trigger = decide(config.trigger, features, config, len(records), rng)
        record = DecisionRecord(len(records), state.time, adapter.signature(state, base), len(adapter.legal_actions(state, config.mode)), tuple(adapter.signature(state, x) for x in candidates), trigger=trigger)
        action = base
        if config.search_depth == 0 or config.max_candidates_per_decision < 2:
            record.fallback_reason = "rollout_disabled"
        elif trigger.triggered:
            if not ledger.reserve("triggered_decisions", config.max_triggered_decisions):
                record.trigger = TriggerDecision(False, trigger.reasons, trigger.score, True); record.fallback_reason = "trigger_budget"
            else:
                try:
                    selected, scored = evaluate(adapter, state, candidates, config.search_depth, config.mode, ledger, config, cache, started)
                    action = selected
                    record.evaluated = tuple(adapter.signature(state, x[1]) for x in scored)
                    record.values = {str(adapter.signature(state, x[1])): x[0] for x in scored}
                    record.actual_depth = max(x[2] for x in scored)
                except BudgetExhausted as error:
                    record.fallback_reason = str(error); fallback_count += 1
        if truncated and record.fallback_reason is None: record.fallback_reason = "candidate_truncated"
        record.selected = adapter.signature(state, action); records.append(record); actions.append(action)
        state = adapter.step(state, action).after
    replay = adapter.replay(actions)
    signatures = tuple(record.selected for record in records if record.selected is not None)
    trace_payload = (
        [(action.kind, action.task_id) for action in actions]
        if adapter.resource_model == "single_channel"
        else [(action.kind, action.starts) for action in actions]
    )
    trace_hash = hashlib.sha256(json.dumps(trace_payload, sort_keys=True).encode()).hexdigest()
    metrics = {**asdict(ledger), "fallback_decisions": fallback_count, "wall_clock_ms": (perf_counter()-started)*1000,
               "voluntary_waits": replay.voluntary_waits, "voluntary_wait_time": replay.voluntary_wait_time,
               "forced_waits": replay.forced_waits, "forced_wait_time": replay.forced_wait_time}
    return RolloutResult("completed", replay.makespan, config.mode, asdict(config), signatures, tuple(asdict(x) for x in records), metrics, trace_hash, replay.trace_valid)
