"""Semantic-neutral manifest validation and row helpers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from benchmark_generate.io import FileHashCache, read_jsonl, sha256_file, write_jsonl_atomic


COMMON_MANIFEST_FIELDS = frozenset({"benchmark_id", "path"})


def validate_manifest(
    rows: Iterable[Mapping[str, Any]],
    *,
    root: Path | None = None,
    hash_field: str | None = None,
    cache: FileHashCache | None = None,
) -> list[dict[str, Any]]:
    """Validate common id/path/hash invariants without imposing semantics."""
    materialized = [dict(row) for row in rows]
    ids: set[str] = set()
    paths: set[str] = set()
    hasher = cache or FileHashCache()
    for row in materialized:
        benchmark_id = row.get("benchmark_id")
        relative = row.get("path")
        if not isinstance(benchmark_id, str) or not benchmark_id:
            raise ValueError("manifest row has an empty benchmark_id")
        if not isinstance(relative, str) or not relative:
            raise ValueError(f"manifest row {benchmark_id} has an empty path")
        normalized = Path(relative)
        if normalized.is_absolute() or ".." in normalized.parts:
            raise ValueError(f"manifest path escapes its root: {relative}")
        if benchmark_id in ids or relative in paths:
            raise ValueError(f"duplicate benchmark_id or path: {benchmark_id} / {relative}")
        ids.add(benchmark_id)
        paths.add(relative)
        if hash_field is not None:
            expected = row.get(hash_field)
            if root is None or not isinstance(expected, str):
                raise ValueError(f"manifest row has no usable {hash_field}: {benchmark_id}")
            target = root / normalized
            if not target.is_file() or hasher.get(target) != expected:
                raise ValueError(f"manifest hash mismatch: {relative}")
    return materialized


def rebuild_manifest_index(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    write_jsonl_atomic(path, sorted(rows, key=lambda row: str(row.get("benchmark_id", ""))))


__all__ = [
    "COMMON_MANIFEST_FIELDS",
    "FileHashCache",
    "read_jsonl",
    "rebuild_manifest_index",
    "sha256_file",
    "validate_manifest",
    "write_jsonl_atomic",
]
