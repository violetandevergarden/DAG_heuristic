from __future__ import annotations

import hashlib
import json
from pathlib import Path

from benchmark import load_benchmark

ROOT = Path(__file__).resolve().parents[1]


def _problem_files() -> list[Path]:
    return [
        path
        for path in (ROOT / "benchmark").rglob("*.json")
        if "schema" not in path.parts and "reference_results" not in path.parts
    ]


def test_removed_compatibility_paths_do_not_reappear() -> None:
    removed = (
        "src/preemptive",
        "src/core/model.py",
        "src/single_channel/parallel_chain/solver.py",
        "src/single_channel/parallel_chain/interface.py",
        "src/single_channel/complex_chain/solver.py",
        "src/single_channel/complex_chain/interface.py",
        "src/muti_channel/solver.py",
        "src/muti_channel/interface.py",
        "benchmark_generate/preemptive.py",
        "benchmark_generate/studies",
        "benchmark_generate/simai/multi_job_study.py",
        "benchmark_generate/simai/repetition_study.py",
        "benchmark_generate/simai/repetition.py",
    )
    assert not [relative for relative in removed if (ROOT / relative).exists()]
    assert not list((ROOT / "tests/preemptive").glob("*.py"))
    assert (ROOT / "experiments/preemptive/stage0_4.py").is_file()
    assert (ROOT / "experiments/simai/repetition_study.py").is_file()


def test_every_problem_path_explicitly_matches_json_semantics() -> None:
    files = _problem_files()
    assert len(files) == 171
    for path in files:
        benchmark = load_benchmark(path)
        branch = "preemptive" if benchmark.semantics.is_preemptive else "nonpreemptive"
        assert branch in path.relative_to(ROOT / "benchmark").parts


def test_preemptive_multi_channel_names_do_not_keep_nonpreemptive_suffix() -> None:
    root = ROOT / "benchmark/muti_channel/preemptive/adversarial"
    files = sorted(root.glob("*.json"))
    assert len(files) == 9
    for path in files:
        benchmark = load_benchmark(path)
        assert not path.stem.endswith("_np")
        assert not benchmark.benchmark_id.endswith("_np")


def test_index_and_path_manifest_are_complete_and_auditable() -> None:
    rows = [json.loads(line) for line in (ROOT / "benchmark/index.jsonl").read_text(encoding="utf-8-sig").splitlines()]
    assert len(rows) == 171
    assert {row["layout_version"] for row in rows} == {"2"}
    assert {row["semantics"] for row in rows} == {"preemptive", "nonpreemptive"}

    moves = [json.loads(line) for line in (ROOT / "benchmark/path_migration_v1_to_v2.jsonl").read_text(encoding="utf-8-sig").splitlines()]
    assert len(moves) == 205
    for move in moves:
        assert not (ROOT / "benchmark" / move["old_path"]).exists()
        target = ROOT / "benchmark" / move["new_path"]
        assert target.is_file()
        assert hashlib.sha256(target.read_bytes()).hexdigest() == move["sha256"]
