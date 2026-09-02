"""Validation and transactional publication for a staged corpus."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from pathlib import Path

from benchmark import load_benchmark, validate_benchmark
from benchmark_generate.export import build_index
from benchmark_generate.llm.nonpreemptive.catalog import write_jsonl


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def validate_candidate(staging: Path) -> list[dict]:
    rows = [
        row
        for row in read_jsonl(staging / "candidate_manifest.jsonl")
        if row.get("publication_status") != "excluded"
    ]
    ids, paths = set(), set()
    run_ids = {row.get("publication_run_id") for row in rows}
    if len(run_ids) != 1 or None in run_ids:
        raise ValueError("candidate sidecars do not share one publication_run_id")
    for row in rows:
        benchmark_id, relative = row.get("benchmark_id"), row.get("path")
        if not benchmark_id or not relative or benchmark_id in ids or relative in paths:
            raise ValueError("candidate contains empty or duplicate id/path")
        ids.add(benchmark_id)
        paths.add(relative)
        path = staging / relative
        benchmark = load_benchmark(path)
        validate_benchmark(benchmark)
        if benchmark.schema_version != "3.0" or benchmark.semantics.is_preemptive:
            raise ValueError(f"not a v3 non-preemptive benchmark: {relative}")
        if sha256(path) != row.get("content_hash"):
            raise ValueError(f"benchmark hash mismatch: {relative}")
        report = row.get("contention_report")
        if not report or sha256(staging / report) != row.get("contention_report_hash"):
            raise ValueError(f"contention report missing or mismatched: {relative}")
    actual = {
        path.relative_to(staging).as_posix() for path in (staging / "nonpreemptive").rglob("*.json")
    }
    if actual != {row["path"] for row in rows}:
        raise ValueError("candidate manifest/file mismatch")
    return rows


def publish(root: Path, *, staging: Path) -> tuple[Path, int]:
    root, staging = root.resolve(), staging.resolve()
    rows = validate_candidate(staging)
    llm_root = root / "llm_structure"
    active = llm_root / "nonpreemptive"
    backup_root = root.parent / ".artifacts" / "nonpreemptive_publication_backup"
    backup_root.mkdir(parents=True, exist_ok=True)
    backup = backup_root / f"snapshot-{int(time.time())}"
    sidecars = [
        llm_root / "nonpreemptive_manifest.jsonl",
        llm_root / "nonpreemptive_source_catalog.jsonl",
        llm_root / "nonpreemptive_topology_catalog.jsonl",
        llm_root / "nonpreemptive_run_metadata.jsonl",
        root / "index.jsonl",
    ]
    saved = {path: path.read_bytes() if path.exists() else None for path in sidecars}
    try:
        if active.exists():
            os.replace(active, backup)
        os.replace(staging / "nonpreemptive", active)
        for source, target in zip(
            ("source_catalog.jsonl", "topology_catalog.jsonl", "run_metadata.jsonl"), sidecars[1:4]
        ):
            shutil.copy2(staging / source, target)
        write_jsonl(sidecars[0], [{**row, "publication_status": "published"} for row in rows])
        count = len(build_index(root))
    except Exception:
        if active.exists():
            shutil.rmtree(active)
        if backup.exists():
            os.replace(backup, active)
        for path, content in saved.items():
            if content is None:
                path.unlink(missing_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
        raise
    return sidecars[0], count
