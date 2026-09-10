"""Canonical paths for the published LLM benchmark corpora."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

Semantics = Literal["preemptive", "nonpreemptive"]


def llm_root(root: Path) -> Path:
    return root / "llm_structure"


def corpus_root(root: Path, semantics: Semantics) -> Path:
    return llm_root(root) / semantics


def manifest_path(root: Path, semantics: Semantics) -> Path:
    return corpus_root(root, semantics) / "manifest.jsonl"


def provenance_root(root: Path, semantics: Semantics) -> Path:
    return corpus_root(root, semantics) / "provenance"


def provenance_path(root: Path, semantics: Semantics, name: str) -> Path:
    return provenance_root(root, semantics) / name


def published_benchmark_path(root: Path, semantics: Semantics, relative: str | Path) -> Path:
    return corpus_root(root, semantics) / Path(relative)


def collection_for_path(semantics: Semantics, relative: str | Path, task_count: int) -> str:
    """Classify a corpus entry without inspecting or loading its full DAG."""

    parts = Path(relative).parts
    if "examples" in parts:
        return "example"
    if "multi_iteration" in parts:
        return "scale"
    if semantics == "nonpreemptive" and "multi_job" in parts:
        return "canonical"
    if task_count > 12000:
        return "scale"
    return "canonical"


def normalize_corpus_relative(path: str | Path, semantics: Semantics) -> Path:
    """Convert a legacy or canonical manifest path to corpus-relative form."""

    value = Path(path)
    parts = value.parts
    if parts and parts[0] == semantics:
        value = Path(*parts[1:])
    if parts and parts[0] == "llm_structure":
        value = Path(*parts[1:])
        if value.parts and value.parts[0] == semantics:
            value = Path(*value.parts[1:])
    return value


__all__ = [
    "Semantics",
    "corpus_root",
    "collection_for_path",
    "llm_root",
    "manifest_path",
    "normalize_corpus_relative",
    "provenance_path",
    "provenance_root",
    "published_benchmark_path",
]
