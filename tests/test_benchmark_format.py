from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmark import BenchmarkValidationError, benchmark_from_dict, load_benchmark
from registry import solve


ROOT = Path(__file__).resolve().parents[1]


def benchmark_files() -> list[Path]:
    return sorted(
        path
        for path in (ROOT / "benchmark").rglob("*.json")
        if "schema" not in path.parts and "reference_results" not in path.parts
    )


def test_every_committed_benchmark_loads() -> None:
    files = benchmark_files()
    loaded = [load_benchmark(path) for path in files]
    counts: dict[tuple[str, str, str], int] = {}
    for item in loaded:
        key = (item.schema_version, item.scenario, item.family, item.category)
        counts[key] = counts.get(key, 0) + 1
    assert counts == {
        ("1.0", "single_channel", "parallel_chain", "adversarial"): 13,
        ("1.0", "single_channel", "parallel_chain", "random"): 10,
        ("1.0", "single_channel", "parallel_chain", "real"): 2,
        ("1.0", "single_channel", "complex_chain", "adversarial"): 16,
        ("1.0", "single_channel", "complex_chain", "random"): 10,
        ("1.0", "single_channel", "complex_chain", "real"): 7,
        ("1.0", "muti_channel", "complex_chain", "adversarial"): 4,
        ("1.0", "muti_channel", "complex_chain", "random"): 10,
        ("1.0", "muti_channel", "complex_chain", "real"): 3,
        ("2.0", "single_channel", "parallel_chain", "adversarial"): 13,
        ("2.0", "single_channel", "parallel_chain", "random"): 10,
        ("2.0", "single_channel", "complex_chain", "adversarial"): 17,
        ("2.0", "single_channel", "complex_chain", "random"): 10,
        ("2.0", "muti_channel", "complex_chain", "adversarial"): 4,
        ("2.0", "muti_channel", "complex_chain", "random"): 10,
    }
    assert {item.scenario for item in loaded} == {"single_channel", "muti_channel"}
    assert {item.category for item in loaded} == {"random", "adversarial", "real"}


def test_benchmark_files_use_lf_line_endings() -> None:
    files = list((ROOT / "benchmark").rglob("*.json"))
    files.append(ROOT / "benchmark/index.jsonl")
    assert files
    for path in files:
        assert b"\r" not in path.read_bytes(), f"{path} must use LF line endings"


def test_index_matches_files_and_hashes() -> None:
    import hashlib

    rows = [json.loads(line) for line in (ROOT / "benchmark/index.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) == len(benchmark_files())
    for row in rows:
        path = ROOT / "benchmark" / row["path"]
        assert path.exists()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == row["sha256"]


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


def test_reference_results_recompute_with_exact_oracle() -> None:
    for reference in sorted((ROOT / "benchmark/reference_results").rglob("*.json")):
        payload = json.loads(reference.read_text(encoding="utf-8"))
        problem = ROOT / "benchmark" / reference.relative_to(
            ROOT / "benchmark/reference_results"
        )
        result = solve(load_benchmark(problem), payload["oracle"])
        assert result.makespan == payload["optimal_makespan"]


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
