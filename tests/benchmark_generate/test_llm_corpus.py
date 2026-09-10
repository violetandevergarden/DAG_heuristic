from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from benchmark import Benchmark, Resource, SchedulingSemantics, Task, write_benchmark
from benchmark_generate.llm.preemptive.corpus import (
    _certified_reachable_choice,
    _fast_contention_audit,
    _migrate_manifest_row,
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
    from core.execution.preemptive import PreeMultiModel

    def forbidden(*_args, **_kwargs):
        raise AssertionError("fast probe enumerated maximal sets")

    monkeypatch.setattr(PreeMultiModel, "legal_actions", forbidden)
    monkeypatch.setattr(
        "benchmark_generate.llm.preemptive.corpus._certified_reachable_choice",
        lambda *_args, **_kwargs: {
            "status": "not_run_test",
            "multiple_legal_actions_exists": None,
            "certified_non_equivalent_choice_exists": None,
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


def test_manifest_v3_separates_conversion_contention_and_publication() -> None:
    row = _migrate_manifest_row({
        "schema_version": "llm-corpus-v2",
        "benchmark_id": "case",
        "path": "preemptive/case.json",
        "status": "sampled_prefix",
        "probe": {"probe_status": "sampled_prefix", "contended_decisions_sampled": 0},
    }, published=True)
    assert "status" not in row
    assert row["conversion_status"] == "valid"
    assert row["contention_evidence_level"] == "sampled_prefix"
    assert row["contention_classification"] == "no-contention-observed"
    assert row["publication_status"] == "published"


def test_choice_certificate_compares_residual_states() -> None:
    compatible = _certified_reachable_choice(_parallel_multi_resource())
    assert compatible["status"] == "certified_no_choice"
    assert compatible["certified_non_equivalent_choice_exists"] is False

    benchmark = Benchmark(
        "conflicting_choices", "muti_channel", "complex_chain", "real",
        (
            Task("a", "communication", 1, resources=("r",)),
            Task("b", "communication", 1, resources=("r",)),
        ),
        (Resource("r", "link"),), semantics=_semantics(), schema_version="2.0",
    )
    conflicting = _certified_reachable_choice(benchmark)
    assert conflicting["status"] == "certified_choice_exists"
    assert conflicting["multiple_legal_actions_exists"] is True
    assert conflicting["certified_non_equivalent_choice_exists"] is True


def test_publish_rejects_hash_mismatch_before_replacing_active() -> None:
    root = Path("tests/.tmp_llm_publish") / "benchmark"
    shutil.rmtree(root.parent, ignore_errors=True)


def test_publish_rolls_back_after_index_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    root = Path("tests/.tmp_llm_publish_rollback") / "benchmark"
    shutil.rmtree(root.parent, ignore_errors=True)
    llm_root = root / "llm_structure"
    active = llm_root / "preemptive"
    active.mkdir(parents=True)
    marker = active / "active-marker.txt"
    marker.write_text("old-corpus", encoding="utf-8")
    (llm_root / "preemptive" / "manifest.jsonl").write_text("old-manifest\n", encoding="utf-8")
    (root / "index.jsonl").write_text("old-index\n", encoding="utf-8")

    staging = llm_root / ".staging" / "run-test"
    candidate = staging / "preemptive" / "case.json"
    candidate.parent.mkdir(parents=True)
    benchmark = _parallel_multi_resource()
    write_benchmark(benchmark, candidate)
    row = {
        "benchmark_id": benchmark.benchmark_id,
        "path": "case.json",
        "benchmark_content_hash": hashlib.sha256(candidate.read_bytes()).hexdigest(),
        "status": "generated",
    }
    (staging / "candidate_manifest.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    for name in ("source_catalog.jsonl", "topology_catalog.jsonl", "run_metadata.jsonl"):
        (staging / name).write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr("benchmark_generate.llm.preemptive.corpus.build_index", lambda *_args: (_ for _ in ()).throw(RuntimeError("injected index failure")))
    with pytest.raises(RuntimeError, match="injected index failure"):
        publish(root, staging=staging, replace_active=True)
    assert marker.read_text(encoding="utf-8") == "old-corpus"
    assert (llm_root / "preemptive" / "manifest.jsonl").read_text(encoding="utf-8") == "old-manifest\n"
    assert (root / "index.jsonl").read_text(encoding="utf-8") == "old-index\n"
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
        "path": "case.json",
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
