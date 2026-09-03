"""Bounded, deterministic source selection for the Stage 4a corpus."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from benchmark_generate.llm_structure import TOPOLOGIES


def canonical_hash(value) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def spec(source: dict, *, topology: str | None = None) -> dict:
    return {
        "source_name": Path(source["path"]).name,
        "model": source["model"],
        "ws": source["world_size"],
        "tp": source["tp"],
        "pp": source["pp"],
        "ep": source["ep"],
        "gbs": source["gbs"],
        "mbs": source["mbs"],
        **({"topology": topology} if topology else {}),
    }


def selected_specs(rows: list[dict], *, max_sources: int = 32) -> list[dict]:
    """Select a bounded structural cross-section instead of only minimum shapes."""
    available = [row for row in rows if row.get("status") == "available" and row["world_size"] > 1]
    if max_sources < 1:
        return []

    def ga(row: dict) -> int:
        return int(row["gbs"]) // int(row["mbs"])

    eligible = [row for row in available if ga(row) in {1, 4, 8} and row["pp"] in {1, 2, 4}]
    strata: dict[tuple, list[dict]] = {}
    for row in eligible:
        moe = "mixtral" in row["model"].lower()
        ep = row["ep"] if moe and row["ep"] in {1, 2, 4, 8} else 1
        key = ("moe" if moe else "dense", ga(row), row["pp"], ep)
        strata.setdefault(key, []).append(row)

    selected: list[dict] = []
    selected_paths: set[str] = set()

    def add(row: dict) -> None:
        if row["path"] not in selected_paths and len(selected) < max_sources:
            selected.append(row)
            selected_paths.add(row["path"])

    # Freeze explicit negative controls and retain every available model family.
    for target_ga in (1, 4, 8):
        controls = [row for row in eligible if ga(row) == target_ga]
        if controls:
            add(min(controls, key=lambda row: (row["world_size"], row["path"])))
    for model in sorted({row["model"] for row in eligible}):
        family = [row for row in eligible if row["model"] == model]
        add(min(family, key=lambda row: (row["world_size"], row["path"])))
    # GA 4/8 are the overlap strata; GA 1 remains as a negative control.
    priority = {4: 0, 8: 1, 1: 2}
    for key in sorted(strata, key=lambda item: (priority[item[1]], item)):
        candidates = sorted(
            strata[key],
            key=lambda row: (row["world_size"], row["tp"], row["model"], row["path"]),
        )
        for row in candidates[:2]:
            add(row)
            if len(selected) >= max_sources:
                break
        if len(selected) >= max_sources:
            break

    specs = [spec(row) for row in selected]
    route_sources = sorted(selected, key=lambda row: (row["world_size"], row["path"]))
    for topology in sorted(TOPOLOGIES)[:2]:
        if route_sources:
            specs.append(spec(route_sources[0], topology=topology))
    unique = {canonical_hash(item): item for item in specs}
    return [unique[key] for key in sorted(unique)]


def benchmark_id(specification: dict) -> str:
    model = "".join(ch.lower() for ch in str(specification["model"]) if ch.isalnum())
    value = f"np_{model}_ws{specification['ws']}_tp{specification['tp']}_pp{specification['pp']}_ep{specification['ep']}_gbs{specification['gbs']}_mbs{specification['mbs']}"
    return value + (f"_route_{specification['topology']}" if specification.get("topology") else "")
