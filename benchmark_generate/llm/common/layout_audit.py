"""Machine-checkable audit for the published benchmark layout."""

from __future__ import annotations

import json
from pathlib import Path

from benchmark_generate.io import read_jsonl, sha256_file
from benchmark_generate.llm.common.layout import corpus_root, manifest_path


def audit(root: Path) -> dict:
    root = root.resolve()
    benchmark_root = root / "benchmark"
    index = read_jsonl(benchmark_root / "index.jsonl")
    report = {
        "index_count": len(index),
        "index_ids": sorted(row["id"] for row in index),
        "index_paths": sorted(row["path"] for row in index),
        "index_duplicate_ids_same_semantics": [],
        "index_duplicate_ids_across_semantics": [],
        "index_duplicate_paths": [],
        "manifest_counts": {},
        "manifest_ids": {},
        "manifest_paths": {},
        "manifest_errors": [],
        "files": {},
    }
    keys = [(row["semantics"], row["id"]) for row in index]
    report["index_duplicate_ids_same_semantics"] = sorted(
        {key for key in keys if keys.count(key) > 1}
    )
    raw_ids = [row["id"] for row in index]
    report["index_duplicate_ids_across_semantics"] = sorted(
        {value for value in raw_ids if raw_ids.count(value) > 1}
    )
    paths = [row["path"] for row in index]
    report["index_duplicate_paths"] = sorted(
        {value for value in paths if paths.count(value) > 1}
    )
    for row in index:
        target = benchmark_root / row["path"]
        report["files"][row["path"]] = {
            "id": row["id"],
            "sha256": sha256_file(target) if target.is_file() else None,
            "index_sha256": row.get("sha256"),
            "exists": target.is_file(),
        }
    for semantics in ("preemptive", "nonpreemptive"):
        path = manifest_path(benchmark_root, semantics)
        rows = read_jsonl(path)
        report["manifest_counts"][semantics] = len(rows)
        report["manifest_ids"][semantics] = sorted(row.get("benchmark_id") for row in rows)
        report["manifest_paths"][semantics] = sorted(row.get("path") for row in rows)
        expected_prefix = f"llm_structure/{semantics}/"
        for row in rows:
            relative = Path(row["path"])
            target = corpus_root(benchmark_root, semantics) / relative
            if not target.is_file():
                report["manifest_errors"].append({"semantics": semantics, "path": row["path"], "error": "missing"})
                continue
            if row.get("content_hash") and row["content_hash"] != sha256_file(target):
                report["manifest_errors"].append({"semantics": semantics, "path": row["path"], "error": "content_hash"})
            if f"{expected_prefix}{relative.as_posix()}" not in report["index_paths"]:
                report["manifest_errors"].append({"semantics": semantics, "path": row["path"], "error": "not_indexed"})
    return report


def write_report(root: Path, destination: Path) -> Path:
    report = audit(root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return destination


__all__ = ["audit", "write_report"]
