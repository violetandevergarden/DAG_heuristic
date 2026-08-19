"""Transactional real-LLM corpus workflow.

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
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from benchmark import load_benchmark, validate_benchmark
from benchmark_generate.export import build_index

CORPUS_MANIFEST_VERSION = "llm-corpus-v2"
STATUSES = {
    "generated",
    "probing",
    "sampled_prefix",
    "certified_small",
    "completed",
    "state_limit",
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
    untracked_entries = []
    for relative in (untracked or "").splitlines():
        candidate = root / relative
        if candidate.is_file():
            untracked_entries.append(f"{relative}\0{_sha256_file(candidate)}")
    bundle = ((diff or "") + "\n" + "\n".join(untracked_entries)).encode()
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
        raise ValueError(f"unknown LLM corpus case status: {status}")
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
        "schema_version": CORPUS_MANIFEST_VERSION,
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
            "version": metadata.get("duration_model_version", "v1"),
            "bandwidth_gbps": metadata.get("bandwidth_gbps"),
            "time_unit": benchmark.time_unit,
            "per_link_capacity": False,
            "includes_nic_resources": any(
                resource.resource_id.startswith(("nic_tx:", "nic_rx:"))
                for resource in benchmark.resources
            ),
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


def _normalized_status(row: dict[str, Any]) -> str:
    """Map the ambiguous v1 success status to its recorded evidence scope."""

    status = row.get("status", "generated")
    if status == "probed" and (row.get("probe") or {}).get("probe_status") == "sampled_prefix":
        return "sampled_prefix"
    return status


def _static_overlap_summary(benchmark) -> dict[str, Any]:
    communications = [task for task in benchmark.tasks if task.kind == "communication"]
    users: dict[str, int] = {}
    for task in communications:
        for resource in task.resources:
            users[resource] = users.get(resource, 0) + 1
    return {
        "communication_count": len(communications),
        "shared_resource_count": sum(count > 1 for count in users.values()),
        "resource_membership_pair_count": sum(count * (count - 1) // 2 for count in users.values()),
        "pair_count_is_upper_bound": True,
    }


def _fast_contention_audit(
    benchmark,
    *,
    horizon: int = 8,
    enumeration_limit: int = 256,
    time_limit_s: float | None = None,
    max_states: int = 2_000,
) -> dict[str, Any]:
    """Sample a bounded public-simulator prefix without claiming full replay."""

    from core.conversion import to_internal_dag, to_multi_resource_instance
    from core.execution.multi_resource import MultiResourceAction, PreemptiveMultiResourceModel
    from core.execution.preemptive import Action, PreemptiveDAGModel

    decisions = 0
    contended = 0
    max_eligible = 0
    action_counts: list[int] = []
    enumeration_truncated = False
    started = time.perf_counter()
    if benchmark.scenario == "single_channel":
        model = PreemptiveDAGModel(to_internal_dag(benchmark))
        state = model.initial_state()
        while not model.is_finished(state) and decisions < horizon:
            if time_limit_s is not None and time.perf_counter() - started >= time_limit_s:
                break
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
            if time_limit_s is not None and time.perf_counter() - started >= time_limit_s:
                break
            while not model.finished(state) and not model.eligible(state):
                state, _interval = model.advance_forced_idle(state)
            if model.finished(state):
                break
            eligible = model.eligible(state)
            if len(eligible) <= enumeration_limit:
                legal = model.legal_actions(state)
            else:
                selected: list[str] = []
                for item in sorted(eligible):
                    if model.compatible((*selected, item)):
                        selected.append(item)
                legal = (MultiResourceAction(tuple(selected)),)
                enumeration_truncated = True
            if len(eligible) <= enumeration_limit:
                pairs = sum(
                    not resources[left].isdisjoint(resources[right])
                    for index, left in enumerate(eligible)
                    for right in eligible[index + 1:]
                )
            else:
                resource_users: dict[str, int] = {}
                for item in eligible:
                    for resource in resources[item]:
                        resource_users[resource] = resource_users.get(resource, 0) + 1
                pairs = sum(count * (count - 1) // 2 for count in resource_users.values())
            decisions += 1
            max_eligible = max(max_eligible, len(eligible))
            action_counts.append(len(legal))
            if pairs:
                contended += 1
            state = model.step(state, max(legal, key=lambda action: (len(action.communications), action.communications)))
        rule = "max_cardinality_maximal_set"
    fraction = contended / decisions if decisions else 0.0
    certified = _certified_reachable_choice(benchmark, max_states=max_states) if len(benchmark.tasks) <= 500 else {
        "status": "not_run_size_limit",
        "exists_multiple_legal_actions": None,
        "explored_states": 0,
    }
    return {
        "benchmark_id": benchmark.benchmark_id,
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
        "complete_trace": False,
        "trace_hash": None,
        "static_resource_overlap": _static_overlap_summary(benchmark),
        "baseline_replay_competition": {
            "choice_state_count": contended,
            "scope": "sampled_prefix",
        },
        "enumeration_limit": enumeration_limit,
        "enumeration_exact": not enumeration_truncated,
        "enumeration_truncated": enumeration_truncated,
        "termination_reason": (
            "time_limit"
            if time_limit_s is not None and time.perf_counter() - started >= time_limit_s
            else "horizon" if decisions >= horizon else "completed"
        ),
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
    from benchmark_generate.llm.catalog import scan_aicb_catalog, write_source_catalog
    from benchmark_generate.llm_structure import AICB_ROOT, build_corpus

    llm_root = root / "llm_structure"
    run_id = run_id or datetime.now(UTC).strftime("run-%Y%m%dT%H%M%SZ")
    staging = llm_root / ".staging" / run_id
    if staging.exists():
        raise FileExistsError(f"staging run already exists: {staging}")
    sources, quarantine = scan_aicb_catalog(AICB_ROOT)
    write_source_catalog(staging / "source_catalog.jsonl", sources, quarantine)
    preemptive_root = staging / "preemptive"
    rows: list[dict[str, Any]] = []

    def checkpoint() -> None:
        _write_jsonl(
            staging / "candidate_manifest.jsonl",
            sorted(rows, key=lambda row: row["benchmark_id"]),
        )

    def write_case(benchmark, relative: Path) -> None:
        path = preemptive_root / relative
        validate_benchmark(benchmark)
        path.parent.mkdir(parents=True, exist_ok=True)
        from benchmark import write_benchmark
        write_benchmark(benchmark, path)
        rows.append(_row_for(benchmark, path, root=staging))
        checkpoint()

    def write_error(entry: dict[str, Any]) -> None:
        rows.append({
            "schema_version": CORPUS_MANIFEST_VERSION,
            "benchmark_id": entry["benchmark_id"],
            "status": "failed",
            "stage4_layer": "unknown",
            "suite": "unknown",
            "error_or_exclusion_reason": entry["error"],
            "spec": entry["spec"],
        })
        checkpoint()

    cases, _target, _skipped = build_corpus(on_case=write_case, on_error=write_error)
    checkpoint()
    (staging / "run_metadata.jsonl").write_text(
        json.dumps({"corpus_manifest_version": CORPUS_MANIFEST_VERSION, "generated_at": datetime.now(UTC).isoformat(), "case_count": len(cases), "git": _git_state(root)}, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return staging


def probe(
    root: Path,
    *,
    manifest: Path | None = None,
    limit: int | None = None,
    fast: bool = False,
    force: bool = False,
    time_limit_s: float | None = None,
    max_decisions: int = 8,
    max_states: int = 2_000,
    enumeration_limit: int = 256,
) -> Path:
    """Resume probes one case at a time and write independent checkpoints."""

    root = root.resolve()
    competition_report = None
    if not fast:
        from benchmark_generate.llm_structure import competition_report as _competition_report
        competition_report = _competition_report

    active_llm_root = root / "llm_structure"
    manifest = (manifest or _manifest_path(active_llm_root)).resolve()
    # A candidate manifest is rooted at its staging run; the active manifest
    # remains rooted at benchmark/llm_structure.
    llm_root = manifest.parent if manifest.name == "candidate_manifest.jsonl" else active_llm_root
    rows = _read_jsonl(manifest)
    # Contention-audit checkpoints are not benchmark inputs. Keep them
    # outside ``benchmark/`` so repository-wide ``*.json`` enumeration cannot
    # mistake a report for a problem instance.
    artifact_root = root.parent if root.name == "benchmark" else root
    reports_root = artifact_root / ".artifacts" / "llm_structure" / "contention_audit"
    changed = 0
    config = {
        "fast": fast,
        "time_limit_s": time_limit_s,
        "max_decisions": max_decisions,
        "max_states": max_states,
        "enumeration_limit": enumeration_limit,
    }
    config_hash = canonical_parameter_hash(config)
    for row in rows:
        if limit is not None and changed >= limit:
            break
        old_probe = row.get("probe") or {}
        if not force and row.get("status") in {
            "sampled_prefix", "certified_small", "completed", "probed",
            "no-contention-observed", "timeout", "state_limit",
        } and old_probe.get("probe_config_hash") == config_hash:
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
            report = _fast_contention_audit(
                benchmark,
                horizon=max_decisions,
                enumeration_limit=enumeration_limit,
                time_limit_s=time_limit_s,
                max_states=max_states,
            ) if fast else competition_report(benchmark)
            elapsed = (time.perf_counter() - started) * 1000.0
            report["probe_runtime_ms"] = round(elapsed, 3)
            report["probe_config_hash"] = config_hash
            report["probe_schema_version"] = "contention-audit-v2"
            if not fast:
                report["probe_status"] = "completed"
            row["probe"] = report
            row["status"] = (
                "timeout"
                if report.get("termination_reason") == "time_limit"
                else "sampled_prefix" if fast else "completed"
            )
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
        source_manifest = staging / "candidate_manifest.jsonl"
        rows = _read_jsonl(source_manifest)
        seen_ids: set[str] = set()
        seen_paths: set[str] = set()
        for row in rows:
            relative = row.get("path")
            if not relative:
                continue
            benchmark_id = row.get("benchmark_id")
            if benchmark_id in seen_ids or relative in seen_paths:
                raise ValueError("candidate manifest contains duplicate benchmark_id or path")
            seen_ids.add(benchmark_id)
            seen_paths.add(relative)
            path = (staging / relative).resolve()
            try:
                path.relative_to(staging)
            except ValueError as error:
                raise ValueError(f"candidate path escapes staging: {relative}") from error
            if not path.is_file():
                raise ValueError(f"candidate benchmark missing: {relative}")
            benchmark = load_benchmark(path)
            validate_benchmark(benchmark)
            if row.get("benchmark_content_hash") != _sha256_file(path):
                raise ValueError(f"candidate benchmark hash mismatch: {relative}")
        if active.exists() and not replace_active:
            raise FileExistsError("active corpus exists; pass replace_active explicitly")
        if active.exists():
            # Keep the rollback copy outside ``benchmark/``; otherwise the
            # repository indexer would mistake the backup for another corpus.
            backup_root = root.parent if root.name == "benchmark" else root
            backup = backup_root / f"llm_corpus_previous-{int(time.time())}"
            os.replace(active, backup)
        os.replace(candidate, active)
        for name in ("source_catalog.jsonl", "run_metadata.jsonl"):
            source = staging / name
            if source.exists():
                shutil.copy2(source, llm_root / name)
    else:
        previous = {row.get("benchmark_id"): row for row in _read_jsonl(_manifest_path(llm_root))}
        rows = []
        for path in sorted(active.rglob("*.json")):
            benchmark = load_benchmark(path)
            validate_benchmark(benchmark)
            row = _row_for(benchmark, path, root=root)
            old = previous.get(benchmark.benchmark_id)
            if old and old.get("benchmark_content_hash") == row["benchmark_content_hash"]:
                row["status"] = _normalized_status(old)
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
    parser.add_argument("--time-limit-s", type=float)
    parser.add_argument("--max-decisions", type=int, default=8)
    parser.add_argument("--max-states", type=int, default=2000)
    parser.add_argument("--enumeration-limit", type=int, default=256)
    args = parser.parse_args(argv)
    if args.mode == "generate":
        print(generate(args.output, run_id=args.run_id))
    elif args.mode == "probe":
        print(probe(
            args.output,
            manifest=args.manifest,
            limit=args.limit,
            fast=args.fast,
            force=args.force,
            time_limit_s=args.time_limit_s,
            max_decisions=args.max_decisions,
            max_states=args.max_states,
            enumeration_limit=args.enumeration_limit,
        ))
    else:
        manifest, count = publish(args.output, staging=args.staging, replace_active=args.replace_active)
        print(f"published {count} index rows: {manifest}")


if __name__ == "__main__":
    main()
