"""Validation and transactional publication for a staged corpus."""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

from benchmark import load_benchmark, validate_benchmark
from benchmark_generate.export import build_index
from benchmark_generate.io import FileHashCache, read_jsonl, sha256_file, write_jsonl_atomic
from benchmark_generate.manifest import validate_manifest


def sha256(path: Path) -> str:
    return sha256_file(path)


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
    validate_manifest(rows)
    cache = FileHashCache()
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
        if cache.get(path) != row.get("content_hash"):
            raise ValueError(f"benchmark hash mismatch: {relative}")
        report = row.get("contention_report")
        if not report or cache.get(staging / report) != row.get("contention_report_hash"):
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
        write_jsonl_atomic(sidecars[0], [{**row, "publication_status": "published"} for row in rows])
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


def publish_selected(
    root: Path,
    *,
    staging: Path,
    selection: Path,
) -> tuple[Path, int]:
    """Add an admitted Stage 4f selection without replacing the active corpus."""
    root, staging, selection = root.resolve(), staging.resolve(), selection.resolve()
    rows = read_jsonl(selection)
    if not 8 <= len(rows) <= 12:
        raise ValueError("Stage 4f publication requires 8--12 frozen cases")
    ids = {row["benchmark_id"] for row in rows}
    if len(ids) != len(rows):
        raise ValueError("Stage 4f selection contains duplicate benchmark ids")
    for row in rows:
        source = staging / row["path"]
        benchmark = load_benchmark(source)
        validate_benchmark(benchmark)
        if benchmark.benchmark_id != row["benchmark_id"]:
            raise ValueError(f"benchmark id mismatch: {source}")
        if benchmark.semantics.is_preemptive or benchmark.schema_version != "3.0":
            raise ValueError(f"not a v3 non-preemptive benchmark: {source}")
        if sha256_file(source) != row["content_hash"]:
            raise ValueError(f"content hash mismatch: {source}")
        if row.get("baseline_status") != "completed_validated":
            raise ValueError(f"baseline gate is incomplete: {benchmark.benchmark_id}")
        if row.get("publication_class") not in {
            "quality_informative",
            "choice_only",
            "no_dynamic_conflict_control",
        }:
            raise ValueError(f"invalid admission class: {benchmark.benchmark_id}")

    llm_root = root / "llm_structure"
    manifest = llm_root / "nonpreemptive_manifest.jsonl"
    index = root / "index.jsonl"
    old_manifest = manifest.read_bytes() if manifest.exists() else None
    old_index = index.read_bytes() if index.exists() else None
    existing = read_jsonl(manifest) if manifest.exists() else []
    existing_ids = {row["benchmark_id"] for row in existing}
    overlap = existing_ids & ids
    if overlap:
        raise ValueError(f"published benchmark ids already exist: {sorted(overlap)}")
    created = []
    try:
        for row in rows:
            relative = Path(row["path"])
            if relative.parts[0] != "nonpreemptive":
                raise ValueError(f"selection path escapes nonpreemptive tree: {relative}")
            target = llm_root / relative
            if target.exists():
                raise ValueError(f"publication target already exists: {target}")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(staging / relative, target)
            created.append(target)
        write_jsonl_atomic(
            manifest,
            [
                *existing,
                *[{**row, "publication_status": "published"} for row in rows],
            ],
        )
        count = len(build_index(root))
    except Exception:
        for target in created:
            target.unlink(missing_ok=True)
        if old_manifest is None:
            manifest.unlink(missing_ok=True)
        else:
            manifest.write_bytes(old_manifest)
        if old_index is None:
            index.unlink(missing_ok=True)
        else:
            index.write_bytes(old_index)
        raise
    return manifest, count


def refresh_selected_records(root: Path, *, selection: Path) -> Path:
    """Refresh sidecar metadata only when published ids and hashes are unchanged."""
    root, selection = root.resolve(), selection.resolve()
    manifest = root / "llm_structure" / "nonpreemptive_manifest.jsonl"
    existing = read_jsonl(manifest)
    updates = {row["benchmark_id"]: row for row in read_jsonl(selection)}
    found = set()
    refreshed = []
    for row in existing:
        update = updates.get(row["benchmark_id"])
        if update is None:
            refreshed.append(row)
            continue
        if row["content_hash"] != update["content_hash"]:
            raise ValueError(f"cannot refresh changed content: {row['benchmark_id']}")
        target = root / "llm_structure" / update["path"]
        if sha256_file(target) != update["content_hash"]:
            raise ValueError(f"published file hash mismatch: {row['benchmark_id']}")
        refreshed.append({**update, "publication_status": "published"})
        found.add(row["benchmark_id"])
    if found != set(updates):
        raise ValueError(f"selection includes unpublished ids: {sorted(set(updates) - found)}")
    write_jsonl_atomic(manifest, refreshed)
    return manifest
