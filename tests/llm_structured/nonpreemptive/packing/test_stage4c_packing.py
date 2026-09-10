from __future__ import annotations

import pytest

from benchmark_generate.cases import multi_resource_motifs
from llm_structured.nonpreemptive.packing import (
    PackingBudget,
    PackingConfig,
    build_conflict_graph,
    choose_action,
    schedule_packing,
)
from llm_structured.nonpreemptive.packing.constructors import construct_candidates
from llm_structured.nonpreemptive.packing.contracts import DecisionBudget
from llm_structured.nonpreemptive.packing.features import set_features
from muti_channel.nonpreemptive.solver import (
    NonPreeMultiModel,
    ResourceAction,
    exact_oracle,
)


def test_non_enumerating_legality_matches_small_exact_action_space() -> None:
    for instance in multi_resource_motifs():
        model = NonPreeMultiModel(instance)
        state = model.initial_state()
        for mode in ("optional_idle", "work_conserving"):
            legal = model.legal_actions(state, mode)
            for action in legal:
                model.validate_action(state, action, mode)
            starts = model.start_subsets(state, maximal_only=False)
            for selected in starts:
                action = ResourceAction.start(selected)
                if mode == "work_conserving" and not model.is_maximal_start(state, selected):
                    with pytest.raises(ValueError): model.validate_action(state, action, mode)


def test_conflict_graph_excludes_active_reservation() -> None:
    model = NonPreeMultiModel(multi_resource_motifs()[3])
    state = model.step(model.initial_state(), ResourceAction.start(("a", "b"))).after
    graph = build_conflict_graph(model, state)
    assert graph.active == ("a",)
    assert graph.vertices == ()
    assert graph.blocked_by_active == ("c",)


def test_work_conserving_candidates_are_maximal_and_deterministic() -> None:
    model = NonPreeMultiModel(multi_resource_motifs()[1])
    state = model.initial_state()
    config = PackingConfig(mode="work_conserving")
    first = construct_candidates(model, state, config, DecisionBudget(config.budget))
    second = construct_candidates(model, state, config, DecisionBudget(config.budget))
    assert [item.signature for item in first] == [item.signature for item in second]
    assert first
    assert all(model.is_maximal_start(state, item.action.starts) for item in first)


def test_optional_idle_candidates_include_nonmaximal_and_wait() -> None:
    model = NonPreeMultiModel(multi_resource_motifs()[2])
    state = model.initial_state()
    config = PackingConfig(mode="optional_idle")
    candidates = construct_candidates(model, state, config, DecisionBudget(config.budget))
    assert any(item.action.kind == "wait" for item in candidates)
    assert any(item.action.starts == ("a",) for item in candidates)


def test_set_features_deduplicate_shared_downstream_nodes() -> None:
    model = NonPreeMultiModel(multi_resource_motifs()[0])
    state = model.initial_state(); action = ResourceAction.start(("left", "right"))
    budget = DecisionBudget(PackingBudget())
    features = set_features(model, state, action, budget)
    reachable_individual = []
    for task_id in action.starts:
        reachable_individual.append(set())
        stack = [model.index[task_id]]
        while stack:
            index = stack.pop()
            if index in reachable_individual[-1]: continue
            reachable_individual[-1].add(index); stack.extend(model.children[index])
    assert features.reachable_union_size == len(set.union(*reachable_individual))


def test_budget_exhaustion_falls_back_to_legal_lt_action() -> None:
    model = NonPreeMultiModel(multi_resource_motifs()[1])
    config = PackingConfig(
        mode="work_conserving", selector="completion",
        budget=PackingBudget(max_pack_operations=1, max_completion_calls=0),
    )
    decision = choose_action(model, model.initial_state(), config)
    assert decision.fallback
    assert decision.selected == decision.baseline
    model.validate_action(model.initial_state(), decision.selected, config.mode)


def test_packing_schedule_keeps_nonpreemptive_trace_and_exact_lower_bound() -> None:
    for instance in multi_resource_motifs():
        optimum = exact_oracle(instance, mode="work_conserving").makespan
        result = schedule_packing(instance, PackingConfig(mode="work_conserving"))
        assert result.makespan >= optimum
        comms = [item for item in result.intervals if item.kind == "comm"]
        assert len(comms) == len({item.task_id for item in comms})
