from __future__ import annotations

from pathlib import Path

import pytest

from benchmark import Benchmark, Resource, SchedulingSemantics, Task, write_benchmark
from benchmark_generate.io import read_jsonl, sha256_file, write_jsonl_atomic
from benchmark_generate.llm.nonpreemptive.corpus import audit


def _benchmark(name: str) -> Benchmark:
    return Benchmark(
        name,
        "single_channel",
        "complex_chain",
        "real",
        (Task("flow", "communication", 2, resources=("channel:0",)),),
        (Resource("channel:0", "channel"),),
        semantics=SchedulingSemantics(
            preemption="none",
            decision_epoch="task_completion",
            optional_idle=True,
            resource_model="exclusive",
        ),
        schema_version="3.0",
    )


def _row(root: Path, name: str) -> dict:
    target = root / "nonpreemptive" / f"{name}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    write_benchmark(_benchmark(name), target)
    return {
        "benchmark_id": name,
        "path": f"nonpreemptive/{name}.json",
        "conversion_status": "valid",
        "contention_evidence_level": "not_run",
        "content_hash": sha256_file(target),
    }


def test_audit_persists_partial_batch_on_interruption(tmp_path: Path, monkeypatch) -> None:
    first = _row(tmp_path, "first")
    second = _row(tmp_path, "second")
    manifest = tmp_path / "candidate_manifest.jsonl"
    write_jsonl_atomic(manifest, [first, second])
    report = {
        "evidence_level": "completed_replay",
        "non_equivalent_choice_observed": False,
        "ordering_choice_observed": False,
        "set_choice_observed": False,
        "wait_choice_observed": False,
    }
    calls = 0

    def interrupted(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected audit failure")
        return report

    monkeypatch.setattr("benchmark_generate.llm.nonpreemptive.corpus.contention_audit", interrupted)
    with pytest.raises(RuntimeError, match="injected audit failure"):
        audit(tmp_path, manifest=manifest)
    persisted = {row["benchmark_id"]: row for row in read_jsonl(manifest)}
    assert persisted["first"]["contention_evidence_level"] == "completed_replay"
    assert persisted["second"]["contention_evidence_level"] == "not_run"
