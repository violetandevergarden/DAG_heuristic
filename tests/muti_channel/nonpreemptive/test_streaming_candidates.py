from benchmark_generate.cases import multi_resource_motifs
from core.execution.nonpreemptive import NonPreeMultiModel
from muti_channel.nonpreemptive.solver import context_for
from muti_channel.nonpreemptive.solver import _iter_compatible_subsets


def test_streaming_optional_subsets_match_materialized_small_state() -> None:
    model = NonPreeMultiModel(multi_resource_motifs()[2])
    state = model.initial_state()
    streamed = tuple(
        _iter_compatible_subsets(
            model, state, maximal_only=False, operation_limit=10_000
        )
    )
    assert set(streamed) == set(model.start_subsets(state, maximal_only=False))


def test_streaming_maximal_subsets_match_materialized_small_state() -> None:
    model = NonPreeMultiModel(multi_resource_motifs()[2])
    state = model.initial_state()
    streamed = tuple(
        _iter_compatible_subsets(
            model, state, maximal_only=True, operation_limit=10_000
        )
    )
    assert set(streamed) == set(model.start_subsets(state, maximal_only=True))


def test_streaming_candidate_budget_is_hard() -> None:
    model = NonPreeMultiModel(multi_resource_motifs()[2])
    state = model.initial_state()
    candidates = tuple(
        _iter_compatible_subsets(
            model, state, maximal_only=False, operation_limit=2
        )
    )
    assert len(candidates) <= 2


def test_priority_context_is_reused_for_same_decision_state() -> None:
    model = NonPreeMultiModel(multi_resource_motifs()[2])
    state = model.initial_state()
    cache = {}
    first = context_for(model, state, cache)
    second = context_for(model, state, cache)
    assert first is second
