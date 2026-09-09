from benchmark_generate.llm.preemptive.barrier_motifs import multi_resource_motifs
from core.execution.preemptive import PreeMultiModel
from muti_channel.preemptive.solver import CompletionCache, complete_pack


def test_completion_cache_replays_same_suffix_and_records_hit() -> None:
    motif = multi_resource_motifs()[0]
    model = PreeMultiModel(motif.dag, motif.resources or {})
    initial = model.initial_state()
    cache = CompletionCache()

    first, first_actions = complete_pack(model, initial, cache=cache)
    second, second_actions = complete_pack(model, model.initial_state(), cache=cache)

    assert first.time == second.time
    assert first_actions == second_actions
    assert cache.misses == 1
    assert cache.hits == 1
