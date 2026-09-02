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


def selected_specs(rows: list[dict]) -> list[dict]:
    available = [row for row in rows if row.get("status") == "available" and row["world_size"] > 1]
    specs = []
    for model_index, model in enumerate(sorted({row["model"] for row in available})):
        candidates = [row for row in available if row["model"] == model]
        smallest = min(
            candidates, key=lambda row: (row["world_size"], row["gbs"], row["mbs"], row["path"])
        )
        specs.append(spec(smallest))
        pipeline = [row for row in candidates if row["pp"] >= 2]
        if pipeline and model_index < 2:
            paired = min(
                pipeline, key=lambda row: (row["world_size"], row["gbs"], row["mbs"], row["path"])
            )
            if paired["path"] != smallest["path"]:
                specs.append(spec(paired))
    route_sources = sorted(available, key=lambda row: (row["world_size"], row["path"]))
    for topology in sorted(TOPOLOGIES)[:2]:
        if route_sources:
            specs.append(spec(route_sources[0], topology=topology))
    unique = {canonical_hash(item): item for item in specs}
    return [unique[key] for key in sorted(unique)]


def benchmark_id(specification: dict) -> str:
    model = "".join(ch.lower() for ch in str(specification["model"]) if ch.isalnum())
    value = f"np_{model}_ws{specification['ws']}_tp{specification['tp']}_pp{specification['pp']}_ep{specification['ep']}_gbs{specification['gbs']}_mbs{specification['mbs']}"
    return value + (f"_route_{specification['topology']}" if specification.get("topology") else "")
