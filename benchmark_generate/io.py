"""Deterministic, streaming file primitives used by benchmark generation.

This module intentionally has no dependency on the benchmark model or on a
scheduling implementation.  Keeping the byte-level rules here makes hashes
and sidecars independent of which semantic adapter produced them.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from typing import Any


JSON_KWARGS = {
    "ensure_ascii": False,
    "sort_keys": True,
    "separators": (",", ":"),
}


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, **JSON_KWARGS).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_sha256(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def canonical_object_sha256(value: Any) -> str:
    """Hash a normalized JSON object, distinct from a file-content hash."""
    return canonical_sha256(value)


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


class FileHashCache:
    """Small per-run hash cache keyed by the file identity and size."""

    def __init__(self) -> None:
        self._values: dict[tuple[str, int, int], str] = {}

    def get(self, path: Path) -> str:
        path = path.resolve()
        stat = path.stat()
        key = (os.fspath(path), stat.st_size, stat.st_mtime_ns)
        value = self._values.get(key)
        if value is None:
            value = sha256_file(path)
            self._values[key] = value
        return value


def iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline=None) as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"JSONL row {line_number} is not an object: {path}")
            yield value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return list(iter_jsonl(path))


def write_jsonl_atomic(
    path: Path,
    rows: Iterable[Mapping[str, Any]],
    *,
    indent: int | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, indent=indent))
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_json_atomic(path: Path, value: Any, *, indent: int = 2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, sort_keys=True, indent=indent) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
