"""Discover real AICB inputs and select an auditable LLM suite.

The catalog records every parseable input.  Canonical selection is deliberately
smaller than the catalog: it covers every model family and every supported
topology without constructing an uncontrolled source x topology x DP product.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Iterable


_AICB_NAME = re.compile(
    r"^(?P<hardware>[^-]+)-(?P<model>.+?)_ws(?P<ws>\d+)_pp(?P<pp_tag>\d+)"
    r"-world_size(?P<world_size>\d+)-tp(?P<tp>\d+)-pp(?P<pp>\d+)"
    r"-ep(?P<ep>\d+)-gbs(?P<gbs>\d+)-mbs(?P<mbs>\d+)"
    r"-seq(?P<sequence_length>\d+)-MOE-(?P<moe>True|False)"
    r"-GEMM-(?P<gemm>True|False)-flash_attn-(?P<flash_attention>True|False)\.txt$"
)


@dataclass(frozen=True)
class WorkloadSource:
    path: str
    filename: str
    content_hash: str
    hardware: str
    model: str
    world_size: int
    tp: int
    pp: int
    ep: int
    dp: int
    gbs: int
    mbs: int
    sequence_length: int
    moe: bool
    gemm: bool
    flash_attention: bool

    @property
    def model_id(self) -> str:
        return re.sub(r"[^a-z0-9]+", "", self.model.lower())


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_aicb_source(path: Path, *, root: Path) -> WorkloadSource | None:
    match = _AICB_NAME.match(path.name)
    if match is None:
        return None
    values = match.groupdict()
    world_size = int(values["world_size"])
    tp, pp, ep = int(values["tp"]), int(values["pp"]), int(values["ep"])
    denominator = tp * pp
    if denominator <= 0 or world_size % denominator:
        return None
    return WorkloadSource(
        path=path.relative_to(root).as_posix(),
        filename=path.name,
        content_hash=_sha256(path),
        hardware=values["hardware"],
        model=values["model"],
        world_size=world_size,
        tp=tp,
        pp=pp,
        ep=ep,
        dp=world_size // denominator,
        gbs=int(values["gbs"]),
        mbs=int(values["mbs"]),
        sequence_length=int(values["sequence_length"]),
        moe=values["moe"] == "True",
        gemm=values["gemm"] == "True",
        flash_attention=values["flash_attention"] == "True",
    )


def scan_aicb_catalog(root: Path) -> tuple[list[WorkloadSource], list[dict[str, str]]]:
    rows: list[WorkloadSource] = []
    quarantine: list[dict[str, str]] = []
    for path in sorted(root.glob("*.txt")):
        source = parse_aicb_source(path, root=root)
        if source is None:
            quarantine.append({"path": path.name, "reason": "unrecognized_or_inconsistent_name"})
        else:
            rows.append(source)
    return rows, quarantine


def write_source_catalog(
    catalog_path: Path,
    sources: Iterable[WorkloadSource],
    quarantine: Iterable[dict[str, str]] = (),
) -> None:
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    records = [
        {"status": "available", **asdict(source)}
        for source in sorted(sources, key=lambda item: item.filename)
    ]
    records.extend(
        {"status": "quarantined", **entry}
        for entry in sorted(quarantine, key=lambda item: item["path"])
    )
    catalog_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in records),
        encoding="utf-8",
        newline="\n",
    )


def canonical_routed_specs(
    sources: Iterable[WorkloadSource],
    topology_capacities: dict[str, int],
) -> list[dict[str, object]]:
    """Select model x topology coverage plus a bounded DP gradient.

    One low-work source is selected independently for each model/topology.
    Production topologies additionally receive a medium/high DP projection
    when capacity permits.  This yields broad deterministic coverage while
    retaining the full catalog for extended sweeps.
    """

    source_list = list(sources)
    models = sorted({source.model for source in source_list})
    specs: list[dict[str, object]] = []
    for topology, capacity in sorted(topology_capacities.items()):
        production = topology in {
            "alibaba_hpn_16g",
            "spectrum_x_16g",
            "dcn_dual_tor_64g",
        }
        for model in models:
            candidates = [
                source
                for source in source_list
                if source.model == model
                and source.world_size <= capacity
                and source.pp >= 2
                and source.ep == 1
            ]
            if not candidates:
                continue
            target_world = 16 if capacity <= 24 else 32
            source = min(
                candidates,
                key=lambda item: (
                    abs(item.world_size - target_world),
                    item.gbs,
                    item.mbs,
                    -item.pp,
                    item.filename,
                ),
            )
            base = {
                "source_name": source.filename,
                "model": source.model,
                "ws": source.world_size,
                "tp": source.tp,
                "pp": source.pp,
                "ep": source.ep,
                "gbs": source.gbs,
                "mbs": source.mbs,
                "topology": topology,
            }
            specs.append(base)
            max_dp = capacity // (source.tp * source.pp)
            if production and max_dp > source.dp:
                # Add at most two effective-DP tiers.  DP=1 remains an explicit
                # control and is excluded from informative-only summaries.
                tiers = sorted({min(max_dp, max(2, source.dp * 2)), max_dp})
                for dp in tiers:
                    if dp != source.dp:
                        specs.append({**base, "dp": dp})
    return specs
