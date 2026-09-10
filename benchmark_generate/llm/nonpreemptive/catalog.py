"""Cross-checked AICB and topology catalogs for non-preemptive Stage 4a."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from benchmark_generate.io import FileHashCache, sha256_file, write_jsonl_atomic
from benchmark_generate.llm.common.catalog import scan_aicb_catalog
from benchmark_generate.simai.common_export import AicbParser, TopologyLoader


def source_catalog(root: Path, *, hash_cache: FileHashCache | None = None) -> list[dict]:
    sources, quarantine = scan_aicb_catalog(root, hash_cache=hash_cache)
    rows: list[dict] = []
    for source in sources:
        path = root / source.path
        row = {"status": "available", **asdict(source)}
        try:
            header, _items = AicbParser().parse(path)
            header_values = {
                "world_size": int(header.all_gpus),
                "tp": int(header.tp),
                "pp": int(header.pp),
                "ep": int(header.ep),
                "gradient_accumulation": int(header.ga),
            }
            comparable = ("world_size", "tp", "pp", "ep")
            expected = {key: row[key] for key in comparable}
            observed = {key: header_values[key] for key in comparable}
            row["header"] = header_values
            row["consistency"] = "matched" if observed == expected else "mismatch"
            if row["consistency"] != "matched":
                row["status"] = "quarantined"
                row["reason"] = {"filename": expected, "header": observed}
        except Exception as error:  # noqa: BLE001 - catalog keeps parse failures
            row["status"] = "quarantined"
            row["consistency"] = "parse_failed"
            row["reason"] = f"{type(error).__name__}: {error}"
        rows.append(row)
    rows.extend({"status": "quarantined", **item} for item in quarantine)
    return sorted(rows, key=lambda row: row["path"])


def topology_catalog(
    topologies: dict, topology_root: Path, *, hash_cache: FileHashCache | None = None
) -> list[dict]:
    rows = []
    for name, (filename, tier, bandwidth_gbps) in sorted(topologies.items()):
        path = topology_root / filename
        row = {
            "topology_id": name,
            "relative_path": path.relative_to(topology_root).as_posix(),
            "content_hash": (
                (hash_cache or FileHashCache()).get(path)
                if path.is_file() and hash_cache
                else sha256_file(path) if path.is_file() else None
            ),
            "status": "available" if path.is_file() else "missing",
            "source_class": "public_example"
            if tier == "experimental"
            else "verified_repository_input",
            "declared_tier": tier,
            "bandwidth_gbps": bandwidth_gbps,
            "routing": "fixed_bfs",
            "resource_granularity": "directed_link_and_endpoint_nic",
            "bandwidth_unit": "Gbps",
            "directed_capacity_semantics": True,
        }
        if path.is_file():
            topology = TopologyLoader().load(path)
            row.update(
                {
                    "gpu_count": topology.gpu_count,
                    "switch_count": topology.switch_count,
                    "directed_link_count": len(topology.links),
                    "gpu_type": topology.gpu_type,
                    "link_bandwidth_gbps": sorted(
                        {link.bandwidth_gbps for link in topology.links.values()}
                    ),
                }
            )
        rows.append(row)
    return rows


def write_jsonl(path: Path, rows: list[dict]) -> None:
    """Compatibility wrapper; all writes now use the atomic common writer."""
    write_jsonl_atomic(path, rows)
