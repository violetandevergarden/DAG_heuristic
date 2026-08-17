"""Transactional Stage 4a corpus workflow.

The older ``benchmark_generate.llm_structure`` entry point bundled generation,
slow contention replay and index publication into one destructive command.  This
module keeps those operations explicit:

``generate`` -> write a versioned staging corpus and candidate manifest
``probe``    -> resume per-case competition reports
``publish``  -> validate hashes, then publish manifest/index

The workflow is deliberately usable without running the expensive probe.  A
generated-but-unprobed case is auditable, but it is not part of the canonical
informative set until its probe status is recorded.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from benchmark import load_benchmark, validate_benchmark
from benchmark_generate.export import build_index

STAGE4_VERSION = "stage4a-v2"
STATUSES = {
    "generated",
    "probing",
    "probed",
    "timeout",
    "failed",
    "excluded",
    "invalid",
    "no-contention-observed",
}


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _git_state(root: Path) -> dict[str, Any]:
    """Return reproducibility metadata without requiring a clean worktree."""

    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
            text=True, check=True,
        ).stdout.strip()
        diff = subprocess.run(
            ["git", "diff", "--binary", "--no-ext-diff"], cwd=root,
            capture_output=True, text=True, encoding="utf-8", errors="replace", check=True,
        ).stdout
        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"], cwd=root,
            capture_output=True, text=True, encoding="utf-8", errors="replace", check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return {"commit": None, "dirty": None, "diff_or_source_bundle_hash": None}
    bundle = ((diff or "") + "\n" + (untracked or "")).encode()
    return {
        "commit": commit,
        "dirty": bool(diff or untracked),
        "diff_or_source_bundle_hash": _sha256_bytes(bundle),
    }


def canonical_parameter_hash(parameters: dict[str, Any]) -> str:
    encoded = json.dumps(parameters, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return _sha256_bytes(encoded)


def _stage4_layer(benchmark) -> str:
    metadata = benchmark.metadata
    explicit = metadata.get("stage4_layer")
    if explicit:
        return str(explicit)
    if metadata.get("provenance", {}).get("workload_origin") == "real_aicb":
        return "real_derived"
    if metadata.get("training_iterations", 1) > 1:
        return "structured_projection"
    return "compatibility"


def _suite(benchmark) -> str:
    return str(benchmark.metadata.get("suite") or benchmark.metadata.get("provenance", {}).get("suite") or "control")


def _row_for(
    benchmark,
    path: Path,
    *,
    root: Path,
    status: str = "generated",
    probe: dict[str, Any] | None = None,
    error: str | None = None,
    generation_parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if status not in STATUSES:
        raise ValueError(f"unknown Stage 4 case status: {status}")
    metadata = benchmark.metadata
    provenance = metadata.get("provenance", {})
    source = provenance.get("source", {})
    topology = provenance.get("topology", {})
    parameters = generation_parameters or provenance.get("parameters", {})
    base = root / "llm_structure"
    if not base.exists():
        base = root
    rel = path.relative_to(base).as_posix()
    path_parts = Path(rel).parts
    effective_parallelism = metadata.get("parallelism") if isinstance(metadata.get("parallelism"), dict) else {}
    filename_match = re.search(r"(?:sourcews|ws)(\d+)", path.name)
    inferred_source_ws = int(filename_match.group(1)) if filename_match else None
    inferred_effective_dp = provenance.get("effective_dp", metadata.get("effective_dp", effective_parallelism.get("dp")))
    inferred_tp = effective_parallelism.get("tp")
    inferred_pp = effective_parallelism.get("pp")
    inferred_source_dp = provenance.get("source_dp")
    if inferred_source_dp is None and inferred_source_ws and inferred_tp and inferred_pp:
        inferred_source_dp = inferred_source_ws // (int(inferred_tp) * int(inferred_pp))
    inferred_effective_ws = provenance.get("effective_world_size", metadata.get("effective_world_size"))
    if inferred_effective_ws is None and inferred_tp and inferred_pp and inferred_effective_dp:
        inferred_effective_ws = int(inferred_tp) * int(inferred_pp) * int(inferred_effective_dp)
    is_routed = "routed" in path_parts
    topology_tier = topology.get("tier")
    if topology_tier is None and is_routed:
        topology_tier = "production" if path_parts[path_parts.index("routed") + 1] in {
            "alibaba_hpn_16g", "spectrum_x_16g", "dcn_dual_tor_64g"
        } else "experimental"
    inferred_layer = metadata.get("stage4_layer")
    if inferred_layer is None:
        inferred_layer = "structured_projection" if "multi_iteration" in path_parts else "control" if "simai_examples" in path_parts else "real_derived" if source.get("name") else "compatibility"
    inferred_origin = provenance.get("workload_origin", metadata.get("workload_origin")) or ("real_aicb" if source.get("name") else "simai_example" if "simai_examples" in path_parts else "synthetic")
    inferred_topology_origin = provenance.get("topology_origin", metadata.get("topology_origin")) or (topology_tier or "unified_relaxation")
    inferred_topology_name = topology.get("name")
    if inferred_topology_name is None and is_routed:
        inferred_topology_name = path_parts[path_parts.index("routed") + 1]
    inferred_suite = _suite(benchmark)
    if inferred_suite == "control":
        inferred_suite = "R-S" if topology_tier == "experimental" else "R-P" if topology_tier == "production" else "R-C" if source.get("name") else "control"
    row: dict[str, Any] = {
        "schema_version": STAGE4_VERSION,
        "benchmark_id": benchmark.benchmark_id,
        "path": rel,
        "suite": inferred_suite,
        "stage4_layer": inferred_layer,
        "status": status,
        "scenario": benchmark.scenario,
        "category": benchmark.category,
        "task_count": len(benchmark.tasks),
        "communication_count": sum(task.kind == "communication" for task in benchmark.tasks),
        "training_iterations": metadata.get("training_iterations", 1),
        "source": {
            "name": source.get("name"),
            "content_hash": source.get("content_hash"),
        },
        "workload_origin": inferred_origin,
        "topology": {
            "name": inferred_topology_name,
            "tier": topology_tier,
            "content_hash": topology.get("content_hash"),
        },
        "topology_origin": inferred_topology_origin,
        "parallelism": metadata.get("parallelism"),
        "source_world_size": provenance.get("source_world_size", metadata.get("source_world_size")) or inferred_source_ws,
        "source_dp": inferred_source_dp,
        "requested_dp": provenance.get("requested_dp"),
        "effective_dp": inferred_effective_dp,
        "effective_world_size": inferred_effective_ws,
        "tp": inferred_tp,
        "pp": inferred_pp,
        "ep": effective_parallelism.get("ep"),
        "dp_rewrite": bool(provenance.get("dp_rewrite", metadata.get("dp_rewrite", False)) or (inferred_source_dp is not None and inferred_effective_dp is not None and inferred_source_dp != inferred_effective_dp)),
        "projection_relation": metadata.get("projection_relation"),
        "projection_relations": metadata.get("projection_relations", [metadata.get("projection_relation")]),
        "route_resource_hash": _sha256_bytes("\n".join(
            f"{task.task_id}:{','.join(task.resources)}" for task in benchmark.tasks if task.kind == "communication"
        ).encode()),
        "duration_model": {
            "name": "nominal_bandwidth_ceil_bytes_per_us",
            "bandwidth_gbps": metadata.get("bandwidth_gbps"),
            "time_unit": benchmark.time_unit,
        },
        "semantic_contract_version": metadata.get("semantic_contract_version"),
        "converter": {
            "commit": provenance.get("tool_version_or_commit"),
            "name": provenance.get("converter", {}).get("name"),
            "version": provenance.get("converter", {}).get("version"),
        },
        "generation_parameters": parameters,
        "generation_parameter_hash": canonical_parameter_hash(parameters),
        "benchmark_content_hash": _sha256_file(path),
        "probe": probe or {},
        "error_or_exclusion_reason": error,
    }
    return row


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
        newline="\n",
    )


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def _manifest_path(llm_root: Path) -> Path:
    return llm_root / "manifest.jsonl"


def _fast_probe(benchmark, *, horizon: int = 8) -> dict[str, Any]:
    """Sample a bounded public-simulator prefix without claiming full replay."""

    from core.conversion import to_internal_dag, to_multi_resource_instance
    from core.execution.multi_resource import PreemptiveMultiResourceModel
    from core.execution.preemptive import Action, PreemptiveDAGModel

    decisions = 0
    contended = 0
    max_eligible = 0
    action_counts: list[int] = []
    if benchmark.scenario == "single_channel":
        model = PreemptiveDAGModel(to_internal_dag(benchmark))
        state = model.initial_state()
        while not model.is_finished(state) and decisions < horizon:
            while not model.is_finished(state) and not model.eligible_communications(state):
                state = model.step(state, Action.wait()).after
            if model.is_finished(state):
                break
            eligible = model.eligible_communications(state)
            decisions += 1
            max_eligible = max(max_eligible, len(eligible))
            action_counts.append(len(eligible))
            if len(eligible) > 1:
                contended += 1
            state = model.step(state, Action.run(min(eligible))).after
        rule = "first_eligible"
    else:
        instance = to_multi_resource_instance(benchmark)
        resources = {task_id: frozenset(values) for task_id, values in instance.resources.items()}
        model = PreemptiveMultiResourceModel(instance.dag, resources)
        state = model.initial_state()
        while not model.finished(state) and decisions < horizon:
            while not model.finished(state) and not model.eligible(state):
                state, _interval = model.advance_forced_idle(state)
            if model.finished(state):
                break
            eligible = model.eligible(state)
            legal = model.legal_actions(state)
            pairs = sum(
                not resources[left].isdisjoint(resources[right])
                for index, left in enumerate(eligible)
                for right in eligible[index + 1:]
            )
            decisions += 1
            max_eligible = max(max_eligible, len(eligible))
            action_counts.append(len(legal))
            if pairs:
                contended += 1
            state = model.step(state, max(legal, key=lambda action: (len(action.communications), action.communications)))
        rule = "max_cardinality_maximal_set"
    fraction = contended / decisions if decisions else 0.0
    certified = _certified_reachable_choice(benchmark) if len(benchmark.tasks) <= 500 else {
        "status": "not_run_size_limit",
        "exists_multiple_legal_actions": None,
        "explored_states": 0,
    }
    return {
        "probe_kind": "fast_prefix",
        "probe_status": "sampled_prefix",
        "baseline_action_rule": rule,
        "horizon_decisions": horizon,
        "decisions_sampled": decisions,
        "contended_decisions_sampled": contended,
        "max_eligible_sampled": max_eligible,
        "action_set_count_max": max(action_counts, default=0),
        "contention_fraction_sampled": round(fraction, 4),
        "none_observed_under_probes": decisions > 0 and contended == 0,
        "certified_reachable_choice": certified["exists_multiple_legal_actions"],
        "certified_probe_status": certified["status"],
        "certified_probe_states": certified["explored_states"],
    }


def _certified_reachable_choice(benchmark, *, max_states: int = 2_000) -> dict[str, Any]:
    """Bounded exhaustive choice existence check for small snapshots."""

    from collections import deque

    from core.conversion import to_internal_dag, to_multi_resource_instance
    from core.execution.multi_resource import PreemptiveMultiResourceModel
    from core.execution.preemptive import PreemptiveDAGModel

    if benchmark.scenario == "single_channel":
        model = PreemptiveDAGModel(to_internal_dag(benchmark))
        initial = model.initial_state()
        def key(state): return state
        def legal(state): return model.legal_actions(state)
        def advance(state, action): return model.step(state, action).after
        def idle(state): return model.step(state, model.legal_actions(state)[0]).after
        def finished(state): return model.is_finished(state)
        # Single-channel WAIT is the only legal action before a communication
        # becomes eligible; the BFS below never treats it as a choice.
        def eligible(state): return model.eligible_communications(state)
    else:
        instance = to_multi_resource_instance(benchmark)
        resources = {task_id: frozenset(values) for task_id, values in instance.resources.items()}
        model = PreemptiveMultiResourceModel(instance.dag, resources)
        initial = model.initial_state()
        def key(state): return state
        def legal(state): return model.legal_actions(state)
        def advance(state, action): return model.step(state, action)
        def idle(state): return model.advance_forced_idle(state)[0]
        def finished(state): return model.finished(state)
        def eligible(state): return model.eligible(state)

    queue = deque([initial])
    seen = {key(initial)}
    while queue and len(seen) <= max_states:
        state = queue.popleft()
        while not finished(state) and not eligible(state):
            next_state = idle(state)
            if key(next_state) == key(state):
                break
            state = next_state
        if finished(state):
            continue
        actions = tuple(legal(state))
        if len(actions) > 1:
            return {"status": "certified", "exists_multiple_legal_actions": True, "explored_states": len(seen)}
        for action in actions:
            child = advance(state, action)
            child_key = key(child)
            if child_key not in seen:
                seen.add(child_key)
                queue.append(child)
    complete = len(seen) <= max_states and not queue
    return {
        "status": "certified" if complete else "state_limit",
        "exists_multiple_legal_actions": False if complete else None,
        "explored_states": len(seen),
    }


def generate(root: Path, *, run_id: str | None = None) -> Path:
    """Generate into a versioned staging directory without touching active data."""

    root = root.resolve()
    from benchmark_generate.llm_structure import build_corpus, write_corpus

    llm_root = root / "llm_structure"
    run_id = run_id or datetime.now(UTC).strftime("run-%Y%m%dT%H%M%SZ")
    staging = llm_root / ".staging" / run_id
    if staging.exists():
        raise FileExistsError(f"staging run already exists: {staging}")
    cases, target, skipped = build_corpus()
    preemptive_root = staging / "preemptive"
    written = write_corpus(cases, target, preemptive_root)
    rows = []
    by_id = {case.benchmark_id: case for case in cases}
    for benchmark_id, relative in target.items():
        path = preemptive_root / relative
        benchmark = by_id[benchmark_id]
        validate_benchmark(benchmark)
        rows.append(_row_for(benchmark, path, root=staging))
    for entry in skipped:
        rows.append({
            "schema_version": STAGE4_VERSION,
            "benchmark_id": entry["benchmark_id"],
            "status": "failed",
            "stage4_layer": "unknown",
            "suite": "unknown",
            "error_or_exclusion_reason": entry["error"],
            "spec": entry["spec"],
        })
    _write_jsonl(staging / "candidate_manifest.jsonl", sorted(rows, key=lambda row: row["benchmark_id"]))
    (staging / "run_metadata.json").write_text(
        json.dumps({"stage4_version": STAGE4_VERSION, "generated_at": datetime.now(UTC).isoformat(), "case_count": len(written), "git": _git_state(root)}, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return staging


def probe(root: Path, *, manifest: Path | None = None, limit: int | None = None, fast: bool = False, force: bool = False) -> Path:
    """Resume probes one case at a time and write independent checkpoints."""

    root = root.resolve()
    competition_report = None
    if not fast:
        from benchmark_generate.llm_structure import competition_report as _competition_report
        competition_report = _competition_report

    llm_root = root / "llm_structure"
    manifest = manifest or _manifest_path(llm_root)
    rows = _read_jsonl(manifest)
    # Probe checkpoints are audit artifacts, not benchmark inputs.  Keep them
    # outside ``benchmark/`` so repository-wide ``*.json`` enumeration cannot
    # mistake a report for a problem instance.
    artifact_root = root.parent if root.name == "benchmark" else root
    reports_root = artifact_root / "stage4_probe"
    changed = 0
    for row in rows:
        if limit is not None and changed >= limit:
            break
        if not force and row.get("status") in {"probed", "no-contention-observed", "timeout"}:
            continue
        relative = row.get("path")
        if not relative:
            continue
        path = llm_root / relative
        if not path.exists():
            row["status"] = "invalid"
            row["error_or_exclusion_reason"] = "benchmark path missing"
            changed += 1
            continue
        started = time.perf_counter()
        try:
            benchmark = load_benchmark(path)
            report = _fast_probe(benchmark) if fast else competition_report(benchmark)
            elapsed = (time.perf_counter() - started) * 1000.0
            report["probe_runtime_ms"] = round(elapsed, 3)
            if not fast:
                report["probe_status"] = "completed"
            row["probe"] = report
            row["status"] = "probed"
            row["error_or_exclusion_reason"] = None
            if not fast and report.get("competition_level") == "none":
                row["status"] = "no-contention-observed"
            reports_root.mkdir(parents=True, exist_ok=True)
            (reports_root / f"{benchmark.benchmark_id}.jsonl").write_text(
                json.dumps(report, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
            )
        except Exception as error:  # noqa: BLE001 - checkpoint the failure
            row["status"] = "failed"
            row["error_or_exclusion_reason"] = f"{type(error).__name__}: {error}"
        changed += 1
        _write_jsonl(manifest, rows)
    return manifest


def publish(
    root: Path,
    *,
    staging: Path | None = None,
    replace_active: bool = False,
) -> tuple[Path, int]:
    """Publish a validated candidate, or reconcile the current active corpus."""

    root = root.resolve()
    llm_root = root / "llm_structure"
    active = llm_root / "preemptive"
    if staging is not None:
        staging = staging.resolve()
        candidate = staging / "preemptive"
        if not candidate.is_dir():
            raise FileNotFoundError(f"staging corpus missing: {candidate}")
        if active.exists() and not replace_active:
            raise FileExistsError("active corpus exists; pass replace_active explicitly")
        if active.exists():
            # Keep the rollback copy outside ``benchmark/``; otherwise the
            # repository indexer would mistake the backup for another corpus.
            backup_root = root.parent if root.name == "benchmark" else root
            backup = backup_root / f"stage4_previous-{int(time.time())}"
            os.replace(active, backup)
        os.replace(candidate, active)
        source_manifest = staging / "candidate_manifest.jsonl"
        rows = _read_jsonl(source_manifest)
    else:
        previous = {row.get("benchmark_id"): row for row in _read_jsonl(_manifest_path(llm_root))}
        rows = []
        for path in sorted(active.rglob("*.json")):
            benchmark = load_benchmark(path)
            validate_benchmark(benchmark)
            row = _row_for(benchmark, path, root=root)
            old = previous.get(benchmark.benchmark_id)
            if old and old.get("benchmark_content_hash") == row["benchmark_content_hash"]:
                row["status"] = old.get("status", row["status"])
                row["probe"] = old.get("probe", row["probe"])
                row["error_or_exclusion_reason"] = old.get("error_or_exclusion_reason")
            rows.append(row)
    rows.sort(key=lambda row: row.get("benchmark_id", ""))
    _write_jsonl(_manifest_path(llm_root), rows)
    index_rows = build_index(root)
    # Keep the active pointer in the JSONL manifest itself.  A standalone
    # ``*.json`` file under ``benchmark/`` would be mistaken for a benchmark by
    # the repository-wide format/index tests.
    return _manifest_path(llm_root), len(index_rows)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("generate", "probe", "publish"), required=True)
    parser.add_argument("--output", type=Path, default=Path("benchmark"))
    parser.add_argument("--run-id")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--staging", type=Path)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--replace-active", action="store_true")
    parser.add_argument("--fast", action="store_true", help="sample a bounded public-simulator prefix")
    parser.add_argument("--force", action="store_true", help="rerun an existing checkpoint")
    args = parser.parse_args(argv)
    if args.mode == "generate":
        print(generate(args.output, run_id=args.run_id))
    elif args.mode == "probe":
        print(probe(args.output, manifest=args.manifest, limit=args.limit, fast=args.fast, force=args.force))
    else:
        manifest, count = publish(args.output, staging=args.staging, replace_active=args.replace_active)
        print(f"published {count} index rows: {manifest}")


if __name__ == "__main__":
    main()
