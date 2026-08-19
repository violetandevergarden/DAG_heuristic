from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from benchmark import Benchmark, Resource, SchedulingSemantics, Task, write_benchmark
from benchmark_generate.llm.corpus import (
    _fast_contention_audit,
    _normalized_status,
    publish,
)


def _semantics() -> SchedulingSemantics:
    return SchedulingSemantics(
        preemption="communication_resume",
        decision_epoch="task_event",
        optional_idle=False,
        resource_model="exclusive_fixed_set",
    )


def _parallel_multi_resource() -> Benchmark:
    return Benchmark(
        "bounded_enumeration",
        "muti_channel",
        "complex_chain",
        "real",
        (
            Task("a", "communication", 1, resources=("r:a",)),
            Task("b", "communication", 1, resources=("r:b",)),
        ),
        (Resource("r:a", "link"), Resource("r:b", "link")),
        semantics=_semantics(),
        schema_version="2.0",
    )


def test_fast_probe_truncates_maximal_set_enumeration(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.execution.multi_resource import PreemptiveMultiResourceModel

    def forbidden(*_args, **_kwargs):
        raise AssertionError("fast probe enumerated maximal sets")

    monkeypatch.setattr(PreemptiveMultiResourceModel, "legal_actions", forbidden)
    monkeypatch.setattr(
        "benchmark_generate.llm.corpus._certified_reachable_choice",
        lambda *_args, **_kwargs: {
            "status": "not_run_test",
            "exists_multiple_legal_actions": None,
            "explored_states": 0,
        },
    )
    report = _fast_contention_audit(
        _parallel_multi_resource(), horizon=1, enumeration_limit=1
    )
    assert report["enumeration_truncated"] is True
    assert report["complete_trace"] is False
    assert report["termination_reason"] == "horizon"


def test_legacy_probe_status_is_migrated_by_evidence_scope() -> None:
    assert _normalized_status({
        "status": "probed",
        "probe": {"probe_status": "sampled_prefix"},
    }) == "sampled_prefix"
    assert _normalized_status({"status": "probed", "probe": {}}) == "probed"


def test_publish_rejects_hash_mismatch_before_replacing_active() -> None:
    root = Path("tests/.tmp_llm_publish") / "benchmark"
    shutil.rmtree(root.parent, ignore_errors=True)
    active = root / "llm_structure" / "preemptive"
    active.mkdir(parents=True)
    marker = active / "active-marker.txt"
    marker.write_text("unchanged", encoding="utf-8")

    staging = root / "llm_structure" / ".staging" / "run-test"
    candidate = staging / "preemptive" / "case.json"
    candidate.parent.mkdir(parents=True)
    benchmark = _parallel_multi_resource()
    write_benchmark(benchmark, candidate)
    row = {
        "benchmark_id": benchmark.benchmark_id,
        "path": "preemptive/case.json",
        "benchmark_content_hash": "0" * 64,
        "status": "generated",
    }
    (staging / "candidate_manifest.jsonl").write_text(
        json.dumps(row) + "\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="hash mismatch"):
        publish(root, staging=staging, replace_active=True)
    assert marker.read_text(encoding="utf-8") == "unchanged"
    assert hashlib.sha256(candidate.read_bytes()).hexdigest() != "0" * 64
    shutil.rmtree(root.parent, ignore_errors=True)
