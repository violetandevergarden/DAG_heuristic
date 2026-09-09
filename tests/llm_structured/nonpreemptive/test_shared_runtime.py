from pathlib import Path

from benchmark import load_benchmark
from experiments.llm_structure.nonpreemptive.foundation.runtime_diagnosis import run
from llm_structured.nonpreemptive.baseline import replay

ROOT = Path(__file__).resolve().parents[3]


def test_stage4_compatibility_modules_reexport_the_only_baseline_implementation():
    from llm_structured.nonpreemptive.baseline.solver import longest_tail_action as canonical
    from llm_structured.nonpreemptive.baseline.solver import (
        longest_tail_action as rollout,
    )

    assert rollout is canonical


def test_thirty_real_small_graphs_match_frozen_result_makespan_and_trace_hash():
    import json

    result_path = (
        ROOT / "docs/nonpreemptive_docs/result_docs/stage4a_baselines_20260831/results.jsonl"
    )
    expected = {
        (row["benchmark_id"], row["rule"], row["mode"]): row
        for row in (
            json.loads(line) for line in result_path.read_text(encoding="utf-8").splitlines()
        )
        if row["status"] == "completed"
    }
    paths = sorted((ROOT / "benchmark/llm_structure/nonpreemptive").rglob("*.json"))[:30]
    assert len(paths) >= 30
    comparisons = 0
    for path in paths:
        benchmark = load_benchmark(path)
        for rule in ("fifo", "fixed_order", "longest_tail"):
            for mode in ("optional_idle", "work_conserving"):
                frozen = expected.get((benchmark.benchmark_id, rule, mode))
                if frozen is None:
                    continue
                current = replay(benchmark, rule, mode)
                comparisons += 1
                assert current["makespan"] == frozen["makespan"]
                assert current["trace_hash"] == frozen["trace_hash"]
    assert comparisons >= 30


def test_foundation_replay_paths_have_distinct_responsibilities():
    path = ROOT / (
        "benchmark/single_channel/complex_chain/nonpreemptive/adversarial/"
        "longest_tail_counterexample.json"
    )
    bare = run(path, "longest_tail", "optional_idle", "bare")
    validated = run(path, "longest_tail", "optional_idle", "validated")
    instrumented = run(path, "longest_tail", "optional_idle", "instrumented")
    profiled = run(path, "longest_tail", "optional_idle", "memory_profile", profile_target="bare")
    assert {bare["makespan"], validated["makespan"], instrumented["makespan"]} == {bare["makespan"]}
    assert bare["policy_loop_only"] and bare["trace_valid"] is None
    assert bare["trace_hash"] == validated["trace_hash"] == instrumented["trace_hash"]
    assert validated["trace_valid"] and not validated["features_observed"]
    assert instrumented["trace_valid"] and instrumented["features_observed"]
    assert instrumented["peak_memory_bytes"] is None
    assert profiled["measurement_perturbed"] and profiled["peak_memory_bytes"] is not None


def test_legacy_multi_replay_is_a_thin_compatible_forwarder():
    from core.conversion import to_muti_resourse
    from muti_channel.nonpreemptive.replay import replay_actions
    from muti_channel.nonpreemptive.solver import (
        NonPreeMultiModel,
        _replay,
    )

    benchmark = load_benchmark(
        ROOT / "benchmark/muti_channel/nonpreemptive/adversarial/nonmaximal_start_np.json"
    )
    model = NonPreeMultiModel(to_muti_resourse(benchmark))
    state = model.initial_state()
    actions = []
    while not model.is_finished(state):
        action = model.legal_actions(state, "work_conserving")[0]
        actions.append(action)
        state = model.step(state, action).after
    public = replay_actions(model, actions, runtime_ms=0.0)
    legacy = _replay(model, actions, runtime_ms=0.0)
    assert public == legacy


def test_corpus_only_imports_publication_ownership():
    import ast

    path = ROOT / "benchmark_generate/llm/nonpreemptive/corpus.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    definitions = {
        node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))
    }
    assert "publish" not in definitions
    assert "_validate_candidate" not in definitions


def test_decision_context_reuses_one_tail_for_all_policy_observations(monkeypatch):
    from llm_structured.nonpreemptive.baseline import make_adapter
    from llm_structured.nonpreemptive.baseline.solver import baseline_action

    benchmark = load_benchmark(
        ROOT
        / "benchmark/single_channel/complex_chain/nonpreemptive/adversarial/longest_tail_counterexample.json"
    )
    adapter = make_adapter(benchmark)
    state = adapter.initial_state()
    calls = 0
    original = adapter.tail

    def counted(current):
        nonlocal calls
        calls += 1
        return original(current)

    monkeypatch.setattr(adapter, "tail", counted)
    context = adapter.decision_context(state, "optional_idle")
    for policy in ("fifo", "fixed_order", "longest_tail", "spt", "lpt"):
        baseline_action(adapter, state, "optional_idle", policy, context=context)
    assert calls == 1
