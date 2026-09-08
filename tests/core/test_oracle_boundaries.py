"""Regression checks for semantic-specific Oracle entry points."""

from pathlib import Path

from core.dag import DAG, Task
from core.oracle import exact_oracle as nonpreemptive_exact
from core.oracle.preemptive import exact_oracle as preemptive_exact


def test_semantic_oracles_have_explicit_and_distinct_entry_points() -> None:
    dag = DAG(
        "oracle_boundary",
        (
            Task("compute", "compute", 1),
            Task("flow", "comm", 2, ("compute",)),
            Task("tail", "compute", 1, ("flow",)),
        ),
    )

    assert nonpreemptive_exact(dag).makespan == 4
    assert preemptive_exact(dag).makespan == 4


def test_source_dependency_directions_remain_one_way() -> None:
    src = Path(__file__).resolve().parents[2] / "src"
    single_channel_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (src / "single_channel").rglob("*.py")
    )
    oracle_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (src / "core" / "oracle").rglob("*.py")
    )
    all_sources = "\n".join(
        path.read_text(encoding="utf-8") for path in src.rglob("*.py")
    )

    assert "llm_structured" not in single_channel_sources
    assert "single_channel" not in oracle_sources
    assert "llm_structured" not in oracle_sources
    assert "from experiments" not in all_sources
    assert "import experiments" not in all_sources
