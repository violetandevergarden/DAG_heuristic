"""Generate the llm_structure benchmark corpus from real AICB workloads.

Inputs live in the SimAI checkout under ``inputs/aicb-workload/`` and
``inputs/topologies/``.  Every exported benchmark is a schema-v2 preemptive
fixed-resource instance with provenance (source content hash, topology hash
and tier) and a competition report computed by driving the public simulator.

Competition report (per file, recorded in the manifest):
- ``decisions``            number of scheduling decision points
- ``contended_decisions``  decisions where more than one communication is
                           eligible (single channel) or where some eligible
                           pair conflicts on a resource (multi resource)
- ``max_eligible``         largest eligible set observed
- ``conflict_pairs``       eligible pairs competing for the same resource,
                           summed over all decisions
- ``competition_level``    none / low / medium / high
- ``feasible_makespan``    makespan of the deterministic baseline replay
                           (validated by the independent trace validator)

DP note: the Mixtral AICB grid ships with dp = all_gpus / (tp * pp) = 1.
``dp_override`` rewrites the ``all_gpus`` header field (astra-sim semantics:
world size = tp * pp * dp) so the same real per-layer data projects onto a
larger world; the rewrite is recorded in the provenance and transform log.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import replace
from pathlib import Path
import re
from collections.abc import Callable

from benchmark import Benchmark, write_benchmark
from benchmark_generate.llm.common.catalog import canonical_routed_specs, scan_aicb_catalog
from benchmark_generate.simai.bootstrap import SIMAI_ROOT
from benchmark_generate.simai.common_export import (
    AicbParser,
    build_workload,
    content_sha256,
    git_commit,
)
from benchmark_generate.simai.preemptive_export import to_preemptive_benchmark
from benchmark_generate.simai.projection import example_cases

AICB_ROOT = SIMAI_ROOT / "inputs" / "aicb-workload"
TOPO_ROOT = SIMAI_ROOT / "inputs" / "topologies"

TOPOLOGIES = {
    # tag: (file name, tier, nic bandwidth gbps)
    "alibaba_hpn_16g": (
        "AlibabaHPN_16g_8gps_DualToR_DualPlane_200Gbps_A100", "production", 200.0
    ),
    "spectrum_x_16g": ("Spectrum-X_16g_8gps_400Gbps_H100", "production", 400.0),
    "dcn_dual_tor_64g": ("DCN+DualToR_64g_8gps_200Gbps_A100", "production", 200.0),
    "cassini_24g": ("Cassini_24g_l1-6_l2-4_l3-3_400Gbps_A100", "experimental", 400.0),
    "cassini_64g": ("Cassini_64g_l1-16_l2-14_l3-12_400Gbps_A100", "experimental", 400.0),
    "hermod_32g": ("Hermod_32g_4server_2nic_4sn3700_100Gbps_A100", "experimental", 100.0),
}

TOPOLOGY_CAPACITIES = {
    "alibaba_hpn_16g": 16,
    "spectrum_x_16g": 16,
    "dcn_dual_tor_64g": 64,
    "cassini_24g": 24,
    "cassini_64g": 64,
    "hermod_32g": 32,
}


def aicb_filename(ws: int, tp: int, pp: int, ep: int, gbs: int, mbs: int) -> str:
    return (
        f"A100-Mixtral_8x7B_ws{ws}_pp{pp}-world_size{ws}-tp{tp}-pp{pp}-ep{ep}"
        f"-gbs{gbs}-mbs{mbs}-seq4096-MOE-True-GEMM-True-flash_attn-True.txt"
    )


def unified_cases() -> list[dict]:
    """Representative single-channel grid: every (ws, tp, pp) shape with a
    small and a large gradient-accumulation tier."""

    rows = []
    shapes = (
        (2, 2, 1), (4, 2, 2), (4, 4, 1),
        (8, 4, 2), (8, 2, 4),
        (16, 8, 2), (16, 4, 4),
        (32, 8, 4),
    )
    for ws, tp, pp in shapes:
        for gbs, mbs in ((2, 1), (8, 2), (16, 4)):
            rows.append({"ws": ws, "tp": tp, "pp": pp, "ep": 1, "gbs": gbs, "mbs": mbs})
    return rows


def dp_override_cases() -> list[dict]:
    """DP-rich variants: the same real layer data projected to a larger world
    via the astra-sim ``all_gpus`` header field (dp = all_gpus/(tp*pp)).

    Sizes are kept replayable for the competition probe (roughly <= 50k
    tasks); larger dp rewrites belong to a slow regeneration suite."""

    return [
        {"ws": 8, "tp": 4, "pp": 2, "ep": 1, "gbs": 2, "mbs": 1, "dp": 4},
        {"ws": 16, "tp": 8, "pp": 2, "ep": 1, "gbs": 2, "mbs": 1, "dp": 2},
        {"ws": 16, "tp": 4, "pp": 4, "ep": 1, "gbs": 2, "mbs": 1, "dp": 4},
        {"ws": 32, "tp": 8, "pp": 4, "ep": 1, "gbs": 2, "mbs": 1, "dp": 2},
    ]


def routed_cases() -> list[dict]:
    """Route-frozen multi-resource variants.

    Production topologies carry the production-evaluation load; the smaller
    Cassini/Hermod topologies are used to concentrate link conflicts
    deliberately.  A topology may host a workload smaller than its GPU count
    (sub-graph routing); that is recorded per file.
    """

    sources, _quarantine = scan_aicb_catalog(AICB_ROOT)
    return canonical_routed_specs(sources, TOPOLOGY_CAPACITIES)


def multi_iteration_cases() -> list[dict]:
    return [
        {"ws": 8, "tp": 4, "pp": 2, "ep": 1, "gbs": 2, "mbs": 1, "iterations": 2},
        {"ws": 8, "tp": 4, "pp": 2, "ep": 1, "gbs": 2, "mbs": 1, "iterations": 4},
        {"ws": 16, "tp": 8, "pp": 2, "ep": 1, "gbs": 2, "mbs": 1, "iterations": 2},
    ]


def export_case(
    spec: dict,
    *,
    benchmark_id: str,
    renderer=to_preemptive_benchmark,
) -> Benchmark:
    ws = spec["ws"]
    tp, pp, ep = spec["tp"], spec["pp"], spec["ep"]
    gbs, mbs = spec["gbs"], spec["mbs"]
    path = AICB_ROOT / spec.get("source_name", aicb_filename(ws, tp, pp, ep, gbs, mbs))
    if not path.exists():
        raise FileNotFoundError(f"AICB case missing: {path.name}")
    header, items = AicbParser().parse(path)

    source_world_size = header.all_gpus
    source_dp = header.all_gpus // (header.tp * header.pp)
    dp = source_dp
    dp_override = spec.get("dp")
    header_rewritten = None
    if dp_override is not None and dp_override != dp:
        header_rewritten = replace(header, all_gpus=header.tp * header.pp * dp_override)
        dp = dp_override
    effective_world_size = header.tp * header.pp * dp
    if ep > 1 and dp % ep != 0:
        raise ValueError(f"dp={dp} is not divisible by ep={ep} for Megatron rank grouping")

    topology_tag = spec.get("topology")
    topology_path = None
    bandwidth = 200.0
    if topology_tag is not None:
        filename, _tier, bandwidth = TOPOLOGIES[topology_tag]
        topology_path = TOPO_ROOT / filename
        if not topology_path.exists():
            raise FileNotFoundError(f"topology missing: {topology_path}")

    built = build_workload(
        "1f1b",
        header_rewritten or header,
        items,
        vpp=2,
    )
    transform_log = [
        "workload compute/flow tasks mapped 1:1 with compute serializer order edges",
        "1F1B pipeline schedule",
        (
            f"communication duration = ceil(size_bytes / (bandwidth_gbps*125)) us "
            f"with bandwidth_gbps={bandwidth}"
        ),
    ]
    if header_rewritten is not None:
        transform_log.append(
            f"astra-sim all_gpus header rewritten {header.all_gpus} -> "
            f"{header_rewritten.all_gpus} (dp {dp_override}, world size = tp*pp*dp)"
        )
    if topology_path is not None:
        transform_log.append(
            "routes frozen to directed link resources plus per-endpoint nic_tx/nic_rx"
        )
    else:
        transform_log.append("all communications share the unified bottleneck channel:0")

    source_hash = content_sha256(path)
    provenance = {
        "source": {"kind": "aicb_workload", "name": path.name, "content_hash": source_hash},
        "tool_version_or_commit": git_commit(SIMAI_ROOT),
        "parameters": {
            "source_world_size": source_world_size,
            "effective_world_size": effective_world_size,
            "source_dp": source_dp,
            "requested_dp": dp_override,
            "effective_dp": dp,
            "ws": ws, "tp": tp, "pp": pp, "ep": ep, "dp": dp,
            "gbs": gbs, "mbs": mbs, "mode": "1f1b",
        },
        "source_world_size": source_world_size,
        "source_dp": source_dp,
        "requested_dp": dp_override,
        "effective_dp": dp,
        "effective_world_size": effective_world_size,
        "dp_rewrite": header_rewritten is not None,
    }
    if topology_path is not None:
        filename, tier, _bandwidth = TOPOLOGIES[topology_tag]
        provenance["topology"] = {
            "name": filename,
            "tier": tier,
            "content_hash": content_sha256(topology_path),
        }
    topology_origin = None
    suite = "R-C" if header_rewritten is not None else "R-P"
    workload_origin = "real_aicb"
    if topology_path is None:
        topology_origin = "unified_relaxation"
        suite = "R-C"
    elif TOPOLOGIES[topology_tag][1] == "experimental":
        topology_origin = "experimental"
        suite = "R-S"
    else:
        topology_origin = "production"
    benchmark = renderer(
        built,
        benchmark_id,
        bandwidth_gbps=bandwidth,
        topology_path=topology_path,
        category="real",
        projection_relation=(
            "parallelism_rewrite_projection+route_frozen_projection"
            if topology_path and header_rewritten is not None
            else "parallelism_rewrite_projection"
            if header_rewritten is not None
            else "route_frozen_projection"
            if topology_path
            else "relaxation_unified_channel"
        ),
        transform_log=tuple(transform_log),
        provenance=provenance,
        suite=suite,
        workload_origin=workload_origin,
        topology_origin=topology_origin,
        source_world_size=source_world_size,
        source_dp=source_dp,
        effective_world_size=effective_world_size,
        dp_rewrite=header_rewritten is not None,
    )
    iterations = spec.get("iterations", 1)
    if iterations > 1:
        benchmark = repeat_iterations(benchmark, iterations)
    return benchmark


def repeat_iterations(benchmark: Benchmark, iterations: int) -> Benchmark:
    """Repeat one training iteration into a single-job multi-iteration DAG.

    Within each copy, dependencies are kept.  Between consecutive copies,
    every rank links its iteration-i sinks (its last compute / source-side
    communication) to its iteration-(i+1) sources (its first compute), which
    is the standard per-rank iteration boundary of 1F1B training: a rank may
    start the next iteration as soon as its own optimizer step finished, so
    cross-iteration pipeline overlap is preserved.
    """

    if iterations < 2:
        raise ValueError("iterations must be at least 2")
    raw_dependencies = {
        task.task_id: tuple(str(parent) for parent in task.metadata.get(
            "simai_raw_dependencies", task.dependencies,
        ))
        for task in benchmark.tasks
    }
    children: dict[str, list[str]] = {task.task_id: [] for task in benchmark.tasks}
    for task in benchmark.tasks:
        for parent in raw_dependencies[task.task_id]:
            children[parent].append(task.task_id)

    task_by_id = {task.task_id: task for task in benchmark.tasks}

    def ranks_of(task) -> set[int]:
        if task.kind == "compute":
            value = task.metadata.get("rank")
            return {int(value)} if value is not None else set()
        return {
            int(value) for value in (task.metadata.get("src"), task.metadata.get("dst"))
            if value is not None
        }

    # Match SimAI's native ``_find_boundary_tasks`` definition: a task is a
    # source/sink for each rank it touches when it has no predecessor/successor
    # touching that same rank.  Communication endpoints therefore participate
    # on both ranks; using only ``src`` silently lost most iteration barriers.
    sinks: dict[int, list[str]] = {}
    sources: dict[int, list[str]] = {}
    for task in benchmark.tasks:
        for rank in ranks_of(task):
            has_rank_pred = any(
                rank in ranks_of(task_by_id[parent]) for parent in raw_dependencies[task.task_id]
            )
            has_rank_succ = any(
                rank in ranks_of(task_by_id[child]) for child in children[task.task_id]
            )
            if not has_rank_succ:
                sinks.setdefault(rank, []).append(task.task_id)
            if not has_rank_pred:
                sources.setdefault(rank, []).append(task.task_id)

    tasks = []
    for it in range(iterations):
        renamed = [
            replace(
                task,
                task_id=f"{task.task_id}@it{it}",
                dependencies=tuple(f"{parent}@it{it}" for parent in task.dependencies),
                metadata={**task.metadata, "iteration_index": it},
            )
            for task in benchmark.tasks
        ]
        if it > 0:
            boundary_by_source: dict[str, set[str]] = {}
            for rank, sink_ids in sinks.items():
                for source_id in sources.get(rank, ()):
                    boundary_by_source.setdefault(f"{source_id}@it{it}", set()).update(
                        f"{sink_id}@it{it - 1}" for sink_id in sink_ids
                    )
            renamed = [
                replace(
                    task,
                    dependencies=tuple(sorted({
                        *task.dependencies,
                        *boundary_by_source.get(task.task_id, ()),
                    })),
                )
                for task in renamed
            ]
        tasks.extend(renamed)
    return replace(
        benchmark,
        benchmark_id=f"{benchmark.benchmark_id}_it{iterations}",
        tasks=tuple(tasks),
        metadata={
            **benchmark.metadata,
            "training_iterations": iterations,
            "stage4_layer": "structured_projection",
            "suite": "R-C",
            "projection_relation": "structured_projection",
            "projection_relations": [
                *benchmark.metadata.get("projection_relations", []),
                "iteration_boundary_projection",
            ],
            "transform_log": [
                *benchmark.metadata.get("transform_log", []),
                (
                    f"one AICB iteration repeated {iterations} times; per-rank "
                    "sink -> source edges preserve 1F1B cross-iteration overlap"
                ),
            ],
        },
    )


def competition_report(benchmark: Benchmark) -> dict:
    """Drive the public simulator and measure scheduling contention."""

    from core.conversion import to_dag, to_muti_resourse
    from core.execution.preemptive import PreeMultiModel
    from core.execution.preemptive import (
        Action,
        PreeSingleModel,
        ScheduleTrace,
    )
    from core.trace.pree_single import assert_preemptive_trace
    from core.trace.pree_multi import assert_preemptive_multi_trace

    decisions = 0
    contended = 0
    max_eligible = 0
    conflict_pairs = 0
    if benchmark.scenario == "single_channel":
        model = PreeSingleModel(to_dag(benchmark))
        state = model.initial_state()
        transitions = []
        events = list(model.initial_events(state))
        intervals = list(model.initial_intervals(state))
        while not model.is_finished(state):
            eligible = model.eligible_communications(state)
            if eligible:
                decisions += 1
                max_eligible = max(max_eligible, len(eligible))
                if len(eligible) > 1:
                    contended += 1
                    conflict_pairs += len(eligible) * (len(eligible) - 1) // 2
                action = Action.run(eligible[0])
            else:
                action = Action.wait()
            transition = model.step(state, action)
            transitions.append(transition)
            events.extend(transition.events)
            intervals.extend(transition.intervals)
            state = transition.after
        # Assemble the trace directly from the recorded transitions instead of
        # re-running the model a second time.
        trace = ScheduleTrace(
            state,
            tuple(transitions),
            tuple(model._sort_events(events)),
            tuple(intervals),
            model.task_ids,
        )
        assert_preemptive_trace(model, trace)
        makespan = trace.makespan
    else:
        from core.execution.preemptive import (
            ExecutionInterval,
            MultiResourceDecision,
            MultiResourceTrace,
            _complete_zero_compute_intervals,
            _events_from_intervals,
            _merge_intervals,
        )

        instance = to_muti_resourse(benchmark)
        resources = {
            task_id: frozenset(str(resource) for resource in values)
            for task_id, values in instance.resources.items()
        }
        model = PreeMultiModel(instance.dag, resources)
        state = model.initial_state()
        trace_decisions = []
        raw_intervals: list[ExecutionInterval] = []
        forced_idle = []
        # Single-pass replay: decisions, contention stats and raw intervals are
        # recorded while driving the public simulator once; the assembled
        # trace is then replayed by the independent validator, so nothing
        # second-guesses the simulator's state transitions.
        while not model.finished(state):
            while not model.finished(state) and not model.eligible(state):
                before_idle = state
                active_ids = tuple(
                    model.tasks[index].task_id for index in model.active_computes(before_idle)
                )
                state, interval = model.advance_forced_idle(before_idle)
                assert interval is not None
                forced_idle.append(interval)
                for task_id in active_ids:
                    raw_intervals.append(
                        ExecutionInterval(task_id, "compute", before_idle.time, state.time)
                    )
            if model.finished(state):
                break
            eligible = model.eligible(state)
            decisions += 1
            max_eligible = max(max_eligible, len(eligible))
            pairs = sum(
                1
                for first in range(len(eligible))
                for second in range(first + 1, len(eligible))
                if not resources[eligible[first]].isdisjoint(resources[eligible[second]])
            )
            conflict_pairs += pairs
            if pairs:
                contended += 1
            legal = model.legal_actions(state)
            action = max(legal, key=lambda item: len(item.communications))
            before = state
            active_ids = tuple(
                model.tasks[index].task_id for index in model.active_computes(before)
            )
            state = model.step(before, action)
            trace_decisions.append(MultiResourceDecision(before.time, state.time, action))
            for task_id in active_ids:
                raw_intervals.append(
                    ExecutionInterval(task_id, "compute", before.time, state.time)
                )
            for task_id in action.communications:
                raw_intervals.append(
                    ExecutionInterval(task_id, "comm", before.time, state.time)
                )
        intervals = _complete_zero_compute_intervals(
            model, _merge_intervals(raw_intervals)
        )
        from core.trace.contracts import ResourceInterval

        resource_intervals = tuple(
            ResourceInterval(resource, interval.task_id, interval.start, interval.end)
            for interval in intervals
            if interval.kind == "comm"
            for resource in sorted(resources[interval.task_id])
        )
        trace = MultiResourceTrace(
            state,
            tuple(trace_decisions),
            _events_from_intervals(intervals),
            intervals,
            resource_intervals,
            tuple(forced_idle),
            model.task_ids,
        )
        assert_preemptive_multi_trace(instance.dag, resources, trace)
        makespan = trace.makespan

    fraction = contended / decisions if decisions else 0.0
    if fraction >= 0.10:
        level = "high"
    elif fraction >= 0.02:
        level = "medium"
    elif fraction > 0:
        level = "low"
    else:
        level = "none"
    return {
        "decisions": decisions,
        "contended_decisions": contended,
        "contention_fraction": round(fraction, 4),
        "max_eligible": max_eligible,
        "conflict_pairs": conflict_pairs,
        "competition_level": level,
        "feasible_makespan": makespan,
    }


def _id(spec: dict) -> str:
    ws, tp, pp, ep = spec["ws"], spec["tp"], spec["pp"], spec["ep"]
    gbs, mbs = spec["gbs"], spec["mbs"]
    dp = spec.get("dp", ws // (tp * pp))
    source_dp = ws // (tp * pp)
    model_id = re.sub(r"[^a-z0-9]+", "", str(spec.get("model", "mixtral8x7b")).lower())
    if "dp" in spec and dp != source_dp:
        base = (
            f"{model_id}_sourcews{ws}_effectivews{tp * pp * dp}"
            f"_tp{tp}_pp{pp}_ep{ep}_dp{dp}_gbs{gbs}_mbs{mbs}"
        )
    else:
        base = f"{model_id}_ws{ws}_tp{tp}_pp{pp}_ep{ep}_dp{dp}_gbs{gbs}_mbs{mbs}"
    if spec.get("topology"):
        base += f"_route_{spec['topology']}"
    return base


def build_corpus(
    *,
    catalog_routed_only: bool = False,
    on_case: Callable[[Benchmark, Path], None] | None = None,
    on_error: Callable[[dict], None] | None = None,
) -> tuple[list[Benchmark], dict[str, Path], list[dict]]:
    cases: list[Benchmark] = []
    target: dict[str, Path] = {}
    skipped: list[dict] = []
    if not catalog_routed_only:
        for spec in unified_cases():
            _try_add(cases, target, skipped, spec, on_case, on_error)
        for spec in dp_override_cases():
            _try_add(cases, target, skipped, spec, on_case, on_error)
    for spec in routed_cases():
        _try_add(cases, target, skipped, spec, on_case, on_error)
    if not catalog_routed_only:
        for spec in multi_iteration_cases():
            _try_add(cases, target, skipped, spec, on_case, on_error)
        for benchmark in example_cases().values():
            cases.append(benchmark)
            relative = Path("simai_examples") / f"{benchmark.benchmark_id}.json"
            target[benchmark.benchmark_id] = relative
            if on_case is not None:
                on_case(benchmark, relative)
    return cases, target, skipped


def _try_add(
    cases: list[Benchmark],
    target: dict[str, Path],
    skipped: list[dict],
    spec: dict,
    on_case: Callable[[Benchmark, Path], None] | None = None,
    on_error: Callable[[dict], None] | None = None,
) -> None:
    benchmark_id = _id(spec)
    print(f"  generate {benchmark_id}", flush=True)
    try:
        benchmark = export_case(spec, benchmark_id=benchmark_id)
    except Exception as error:  # noqa: BLE001 - corpus generation must skip, not die
        entry = {
            "benchmark_id": benchmark_id,
            "spec": spec,
            "error": f"{type(error).__name__}: {error}",
        }
        skipped.append(entry)
        if on_error is not None:
            on_error(entry)
        return
    actual_id = benchmark.benchmark_id
    cases.append(benchmark)
    if spec.get("topology"):
        relative = Path("routed") / spec["topology"] / f"{actual_id}.json"
    elif spec.get("iterations", 1) > 1:
        relative = Path("multi_iteration") / f"{actual_id}.json"
    else:
        relative = Path("unified") / f"{actual_id}.json"
    target[actual_id] = relative
    if on_case is not None:
        on_case(benchmark, relative)


def write_corpus(
    cases: list[Benchmark],
    target: dict[str, Path],
    root: Path,
) -> list[Path]:
    written = []
    for benchmark in cases:
        path = root / target[benchmark.benchmark_id]
        path.parent.mkdir(parents=True, exist_ok=True)
        write_benchmark(benchmark, path)
        written.append(path)
    return written


def write_manifest(
    cases: list[Benchmark],
    target: dict[str, Path],
    root: Path,
    reference_root: Path,
) -> tuple[Path, dict[str, dict]]:
    manifest = root / "manifest.jsonl"
    rows = []
    reports: dict[str, dict] = {}
    for benchmark in cases:
        path = root / "preemptive" / target[benchmark.benchmark_id]
        report = competition_report(benchmark)
        reports[benchmark.benchmark_id] = report
        print(
            f"  replay {benchmark.benchmark_id}: {report['competition_level']} "
            f"({report['contended_decisions']}/{report['decisions']} contended, "
            f"makespan {report['feasible_makespan']})"
        )
        reference = (
            reference_root
            / "reference_results"
            / "llm_structure"
            / "preemptive"
            / target[benchmark.benchmark_id]
        )
        optimal = None
        if reference.exists():
            optimal = json.loads(reference.read_text(encoding="utf-8")).get("optimal_makespan")
        provenance = benchmark.metadata.get("provenance", {})
        source = provenance.get("source", {})
        topology = provenance.get("topology", {})
        rows.append({
            "benchmark_id": benchmark.benchmark_id,
            "path": str(target[benchmark.benchmark_id].as_posix()),
            "scenario": benchmark.scenario,
            "category": benchmark.category,
            "task_count": len(benchmark.tasks),
            "communication_count": sum(task.kind == "communication" for task in benchmark.tasks),
            "parallelism": benchmark.metadata.get("parallelism"),
            "training_iterations": benchmark.metadata.get("training_iterations", 1),
            "source": {"name": source.get("name"), "content_hash": source.get("content_hash")},
            "topology": {"name": topology.get("name"), "tier": topology.get("tier")},
            "projection_relation": benchmark.metadata.get("projection_relation"),
            "semantic_contract_version": benchmark.metadata.get("semantic_contract_version"),
            "competition": report,
            "reference_optimal_makespan": optimal,
            "benchmark_content_hash": hashlib.sha256(path.read_bytes()).hexdigest(),
        })
    manifest.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
        newline="\n",
    )
    return manifest, reports


def main(argv: list[str] | None = None) -> None:
    """Compatibility shim for the old entry point.

    It now delegates to the transactional workflow and therefore never removes
    the active corpus. Use ``python -m benchmark_generate.llm.preemptive.corpus`` directly
    when selecting probe/publish options.
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("benchmark"))
    parser.add_argument("--mode", choices=("generate", "probe", "publish"), default="generate")
    parser.add_argument("--run-id")
    parser.add_argument("--staging", type=Path)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--fast", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--replace-active", action="store_true")
    parser.add_argument("--skip-reference", action="store_true", help="kept for CLI compatibility; references are a separate step")
    args = parser.parse_args(argv)
    from benchmark_generate.llm.preemptive.corpus import generate, probe, publish
    if args.mode == "generate":
        print(generate(args.output, run_id=args.run_id))
    elif args.mode == "probe":
        print(probe(args.output, limit=args.limit, fast=args.fast, force=args.force))
    else:
        manifest, count = publish(args.output, staging=args.staging, replace_active=args.replace_active)
        print(f"published {count} index rows: {manifest}")


if __name__ == "__main__":
    main()

