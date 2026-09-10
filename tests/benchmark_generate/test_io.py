from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from benchmark_generate.io import (
    FileHashCache,
    canonical_object_sha256,
    read_jsonl,
    sha256_file,
    write_jsonl_atomic,
)
from benchmark_generate.manifest import validate_manifest


def test_streaming_hash_matches_hashlib_for_empty_small_and_cross_chunk(tmp_path: Path) -> None:
    for name, payload in {
        "empty": b"",
        "small": "中文\nvalue".encode("utf-8"),
        "cross-chunk": bytes(range(256)) * 8193,
    }.items():
        path = tmp_path / name
        path.write_bytes(payload)
        assert sha256_file(path, chunk_size=17) == hashlib.sha256(payload).hexdigest()


def test_canonical_object_hash_ignores_mapping_insertion_order() -> None:
    assert canonical_object_sha256({"b": 2, "a": 1}) == canonical_object_sha256({"a": 1, "b": 2})


def test_jsonl_accepts_bom_and_empty_lines_but_rejects_non_objects(tmp_path: Path) -> None:
    path = tmp_path / "rows.jsonl"
    path.write_text('\ufeff{"id": 1}\n\n{"id": 2}\n', encoding="utf-8")
    assert read_jsonl(path) == [{"id": 1}, {"id": 2}]
    path.write_text("[1, 2]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not an object"):
        read_jsonl(path)


def test_atomic_jsonl_write_failure_preserves_old_file_and_cleans_temp(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "manifest.jsonl"
    path.write_text("old\n", encoding="utf-8")

    def fail_replace(_source, _target):
        raise OSError("injected replace failure")

    monkeypatch.setattr("benchmark_generate.io.os.replace", fail_replace)
    with pytest.raises(OSError, match="injected"):
        write_jsonl_atomic(path, [{"id": "new"}])
    assert path.read_text(encoding="utf-8") == "old\n"
    assert not list(tmp_path.glob(".manifest.jsonl.tmp-*"))


def test_manifest_rejects_paths_duplicates_and_hash_errors(tmp_path: Path) -> None:
    target = tmp_path / "case.json"
    target.write_text("{}\n", encoding="utf-8")
    good = {
        "benchmark_id": "case",
        "path": "case.json",
        "content_hash": sha256_file(target),
    }
    assert validate_manifest([good], root=tmp_path, hash_field="content_hash")[0]["benchmark_id"] == "case"
    cases = (
        {**good, "benchmark_id": ""},
        [good, {**good, "benchmark_id": "other"}],
        [good, {**good, "path": "other.json"}],
        {**good, "path": "../case.json"},
        {**good, "path": str(target)},
        {**good, "content_hash": "0" * 64},
    )
    for invalid in cases:
        with pytest.raises(ValueError):
            validate_manifest(invalid if isinstance(invalid, list) else [invalid], root=tmp_path, hash_field="content_hash")


def test_hash_cache_recomputes_after_file_identity_changes(tmp_path: Path) -> None:
    path = tmp_path / "input.bin"
    path.write_bytes(b"one")
    cache = FileHashCache()
    first = cache.get(path)
    path.write_bytes(b"two")
    second = cache.get(path)
    assert first != second
