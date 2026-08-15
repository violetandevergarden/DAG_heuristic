from pathlib import Path

from benchmark import load_benchmark
from benchmark_generate.export import build_index, export_semantic_suite


def _payloads(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*.json")
    }


def test_random_generation_is_seeded_and_language_neutral(tmp_path: Path) -> None:
    left = tmp_path / "left"
    right = tmp_path / "right"
    export_semantic_suite(
        left,
        semantics="nonpreemptive",
        samples=2,
        seed=7,
        categories={"random"},
    )
    export_semantic_suite(
        right,
        semantics="nonpreemptive",
        samples=2,
        seed=7,
        categories={"random"},
    )
    build_index(left)
    build_index(right)

    assert _payloads(left) == _payloads(right)
    files = sorted(left.rglob("*.json"))
    assert len(files) == 6
    assert all(load_benchmark(path).category == "random" for path in files)


def test_both_semantics_use_the_same_export_path(tmp_path: Path) -> None:
    export_semantic_suite(
        tmp_path,
        semantics="nonpreemptive",
        samples=2,
        seed=7,
        categories={"random"},
    )
    export_semantic_suite(
        tmp_path,
        semantics="preemptive",
        samples=2,
        seed=7,
        categories={"random"},
    )
    rows = build_index(tmp_path)

    assert len(rows) == 12
    assert {row["semantics"] for row in rows} == {"preemptive", "nonpreemptive"}
    for row in rows:
        assert row["semantics"] in Path(row["path"]).parts
