from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmark import (
    BenchmarkValidationError,
    benchmark_from_dict,
    benchmark_to_dict,
    load_benchmark,
)
from registry import solve

ROOT = Path(__file__).resolve().parents[1]


def benchmark_files() -> list[Path]:
    return sorted(
        path
        for path in (ROOT / "benchmark").rglob("*.json")
        if "schema" not in path.parts
        and "reference_results" not in path.parts
        and ".staging" not in path.parts
    )


def test_every_committed_benchmark_loads() -> None:
    index_rows = [
        json.loads(line)
        for line in (ROOT / "benchmark/index.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    # The public inventory covers every file through streaming hashes. Model
    # construction is limited to small representative inputs so this format
    # test cannot materialize the multi-gigabyte LLM corpus.
    selected = [
        ROOT / "benchmark" / row["path"]
        for row in index_rows
        if not row["path"].startswith("llm_structure/")
        or (ROOT / "benchmark" / row["path"]).stat().st_size <= 2_000_000
    ]
    loaded = [load_benchmark(path) for path in selected]
    counts: dict[tuple[str, str, str], int] = {}
    for item in loaded:
        key = (item.schema_version, item.scenario, item.family, item.category)
        counts[key] = counts.get(key, 0) + 1
    expected: dict[tuple[str, str, str], int] = {}
    for row in index_rows:
        path = ROOT / "benchmark" / row["path"]
        if not row["path"].startswith("llm_structure/") or path.stat().st_size <= 2_000_000:
            key = (row["schema_version"], row["scenario"], row["family"], row["category"])
            expected[key] = expected.get(key, 0) + 1
    assert counts == expected
    assert len(loaded) == sum(expected.values())
    assert {item.scenario for item in loaded} == {"single_channel", "muti_channel"}
    assert {item.category for item in loaded} == {"random", "adversarial", "real"}


def test_benchmark_files_use_lf_line_endings() -> None:
    files = list((ROOT / "benchmark").rglob("*.json"))
    files.append(ROOT / "benchmark/index.jsonl")
    assert files
    for path in files:
        assert b"\r" not in path.read_bytes(), f"{path} must use LF line endings"


def test_index_matches_files_and_hashes() -> None:
    from benchmark_generate.io import sha256_file

    rows = [
        json.loads(line)
        for line in (ROOT / "benchmark/index.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(rows) == len(benchmark_files())
    for row in rows:
        path = ROOT / "benchmark" / row["path"]
        assert path.exists()
        assert sha256_file(path) == row["sha256"]


def test_reference_results_match_problem_hashes() -> None:
    import hashlib

    references = sorted((ROOT / "benchmark/reference_results").rglob("*.json"))
    assert references
    for reference in references:
        payload = json.loads(reference.read_text(encoding="utf-8"))
        relative = reference.relative_to(ROOT / "benchmark/reference_results")
        problem = ROOT / "benchmark" / relative
        assert problem.exists()
        assert payload["benchmark_sha256"] == hashlib.sha256(problem.read_bytes()).hexdigest()


@pytest.mark.oracle_full
def test_reference_results_recompute_with_exact_oracle() -> None:
    for reference in sorted((ROOT / "benchmark/reference_results").rglob("*.json")):
        payload = json.loads(reference.read_text(encoding="utf-8"))
        problem = ROOT / "benchmark" / reference.relative_to(ROOT / "benchmark/reference_results")
        result = solve(load_benchmark(problem), payload["oracle"])
        assert result.makespan == payload["optimal_makespan"]


def test_stage2_references_record_completed_optimal_status() -> None:
    root = ROOT / "benchmark/reference_results/single_channel/complex_chain/preemptive"
    references = sorted(root.rglob("*.json"))
    assert references
    for reference in references:
        payload = json.loads(reference.read_text(encoding="utf-8"))
        assert payload["oracle_status"] == "optimal"
        assert payload["oracle_budget"] == {"max_states": 100_000, "time_limit_s": 5.0}


def test_historical_counterexample_values_are_preserved() -> None:
    expected = {
        "combined_chain_14": 21,
        "combined_chain_70": 18,
        "combined_chain_86": 24,
        "random_chain_14": 21,
        "random_chain_52": 20,
        "random_chain_60": 15,
        "random_chain_70": 18,
        "random_chain_77": 26,
        "random_chain_86": 24,
        "random_chain_98": 17,
        "random_join_23": 17,
        "random_join_30": 22,
        "random_join_40": 21,
        "random_join_46": 22,
        "random_join_60": 24,
    }
    actual = {}
    for reference in (ROOT / "benchmark/reference_results").rglob("*.json"):
        payload = json.loads(reference.read_text(encoding="utf-8"))
        if payload["benchmark_id"] in expected:
            actual[payload["benchmark_id"]] = payload["optimal_makespan"]
    assert actual == expected


def test_cycle_is_rejected() -> None:
    payload = {
        "schema_version": "1.0",
        "id": "cycle",
        "scenario": "single_channel",
        "family": "complex_chain",
        "category": "adversarial",
        "objective": "makespan",
        "time_unit": "tick",
        "semantics": {
            "preemptive": False,
            "decision_epoch": "task_completion",
            "optional_idle": True,
            "compute_model": "unbounded_parallel",
            "resource_model": "exclusive",
        },
        "resources": [{"id": "channel:0", "kind": "channel"}],
        "tasks": [
            {"id": "a", "kind": "compute", "duration": 1, "dependencies": ["b"], "resources": []},
            {"id": "b", "kind": "compute", "duration": 1, "dependencies": ["a"], "resources": []},
        ],
    }
    with pytest.raises(BenchmarkValidationError, match="cycle"):
        benchmark_from_dict(payload)


def _v3_payload(*, scenario: str = "muti_channel") -> dict:
    resource_model = "exclusive_fixed_set" if scenario == "muti_channel" else "exclusive"
    resources = (
        [{"id": "link:0->1", "kind": "directed_link"}]
        if scenario == "muti_channel"
        else [{"id": "channel:0", "kind": "channel"}]
    )
    resource_id = resources[0]["id"]
    return {
        "schema_version": "3.0",
        "id": "v3_nonpreemptive",
        "scenario": scenario,
        "family": "complex_chain",
        "category": "real",
        "objective": "makespan",
        "time_unit": "us",
        "semantics": {
            "preemption": "none",
            "decision_epoch": "task_completion",
            "optional_idle": True,
            "compute_model": "unbounded_parallel",
            "resource_model": resource_model,
            "preemption_cost": 0,
            "minimum_quantum": 0,
        },
        "resources": resources,
        "tasks": [
            {
                "id": "comm",
                "kind": "communication",
                "duration": 1,
                "dependencies": [],
                "resources": [resource_id],
            }
        ],
    }


def test_v3_nonpreemptive_fixed_resource_round_trip() -> None:
    payload = _v3_payload()
    benchmark = benchmark_from_dict(payload)
    assert benchmark_to_dict(benchmark) == payload
    assert benchmark.semantics.optional_idle
    assert not benchmark.semantics.is_preemptive


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("preemption", "communication_resume", "forbids communication preemption"),
        ("decision_epoch", "task_event", "requires decision_epoch"),
        ("optional_idle", False, "requires optional_idle"),
        ("resource_model", "exclusive", "requires exclusive_fixed_set"),
    ],
)
def test_v3_rejects_wrong_semantic_contract(field, value, message) -> None:
    payload = _v3_payload()
    payload["semantics"][field] = value
    with pytest.raises(BenchmarkValidationError, match=message):
        benchmark_from_dict(payload)


def test_v3_rejects_empty_fixed_resource_set() -> None:
    payload = _v3_payload()
    payload["tasks"][0]["resources"] = []
    with pytest.raises(BenchmarkValidationError, match="needs a resource"):
        benchmark_from_dict(payload)
