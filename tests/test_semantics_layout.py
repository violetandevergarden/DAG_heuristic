from __future__ import annotations

import json
from pathlib import Path

from benchmark import load_benchmark

ROOT = Path(__file__).resolve().parents[1]


def _problem_files() -> list[Path]:
    return [
        path
        for path in (ROOT / "benchmark").rglob("*.json")
        if "schema" not in path.parts
        and "reference_results" not in path.parts
        and ".staging" not in path.parts
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
    rows = [
        json.loads(line)
        for line in (ROOT / "benchmark/index.jsonl").read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]
    assert rows
    for row in rows:
        assert row["semantics"] in Path(row["path"]).parts


def test_preemptive_multi_channel_names_do_not_keep_nonpreemptive_suffix() -> None:
    root = ROOT / "benchmark/muti_channel/preemptive/adversarial"
    files = sorted(root.glob("*.json"))
    assert len(files) == 9
    for path in files:
        benchmark = load_benchmark(path)
        assert not path.stem.endswith("_np")
        assert not benchmark.benchmark_id.endswith("_np")


def test_index_and_path_manifest_are_complete_and_auditable() -> None:
    rows = [
        json.loads(line)
        for line in (ROOT / "benchmark/index.jsonl").read_text(encoding="utf-8-sig").splitlines()
    ]
    indexed_paths = [row["path"] for row in rows]
    indexed_keys = [(row["semantics"], row["id"]) for row in rows]
    problem_paths = [path.relative_to(ROOT / "benchmark").as_posix() for path in _problem_files()]
    assert len(indexed_paths) == len(set(indexed_paths))
    assert len(indexed_keys) == len(set(indexed_keys))
    assert set(indexed_paths) == set(problem_paths)
    assert {row["layout_version"] for row in rows} == {"2"}
    assert {row["semantics"] for row in rows} == {"preemptive", "nonpreemptive"}

    published = [
        json.loads(line)
        for line in (ROOT / "benchmark/llm_structure/nonpreemptive/manifest.jsonl")
        .read_text(encoding="utf-8-sig")
        .splitlines()
    ]
    published_paths = {
        f"llm_structure/nonpreemptive/{row['path']}"
        for row in published
        if row["publication_status"] == "published"
    }
    indexed_nonpreemptive_stage4 = {
        path for path in indexed_paths if path.startswith("llm_structure/nonpreemptive/")
    }
    assert indexed_nonpreemptive_stage4 == published_paths

    for semantics in ("preemptive", "nonpreemptive"):
        manifest = ROOT / f"benchmark/llm_structure/{semantics}/manifest.jsonl"
        rows = [json.loads(line) for line in manifest.read_text(encoding="utf-8-sig").splitlines()]
        assert all(not row["path"].startswith(("preemptive/", "nonpreemptive/")) for row in rows)
        assert all((manifest.parent / row["path"]).is_file() for row in rows if row.get("path"))
