"""Transactional non-preemptive Stage 4a corpus workflow."""

from __future__ import annotations

import argparse
import multiprocessing
import os
import queue
from datetime import UTC, datetime
from pathlib import Path

from benchmark import load_benchmark, write_benchmark
from benchmark_generate.io import (
    FileHashCache,
    canonical_sha256,
    read_jsonl,
    sha256_file,
    write_json_atomic,
    write_jsonl_atomic,
)
from benchmark_generate.llm.nonpreemptive.catalog import source_catalog, topology_catalog
from benchmark_generate.llm.nonpreemptive.contention_audit import contention_audit
from benchmark_generate.llm.common.multi_job import compose_real_jobs
from benchmark_generate.llm.nonpreemptive.corpus_publication import publish
from benchmark_generate.llm.nonpreemptive.corpus_selection import (
    benchmark_id as _benchmark_id,
)
from benchmark_generate.llm.nonpreemptive.corpus_selection import (
    selected_specs as _selected_specs,
)
from benchmark_generate.llm.nonpreemptive.slice import causal_closure_slice
from benchmark_generate.llm.common.config import (
    AICB_ROOT,
    TOPO_ROOT,
    TOPOLOGIES,
)
from benchmark_generate.llm.common.conversion import export_case
from benchmark_generate.simai.nonpreemptive_export import to_nonpreemptive_benchmark

MANIFEST_VERSION = "llm-nonpreemptive-corpus-v1"
PUBLICATION_RUN_VERSION = "stage4a-nonpreemptive-publication-v1"


def _export_worker(spec: dict, benchmark_id: str, temporary: str, output) -> None:
    try:
        benchmark = export_case(
            spec,
            benchmark_id=benchmark_id,
            renderer=to_nonpreemptive_benchmark,
        )
        write_benchmark(benchmark, temporary)
        output.put({"status": "completed"})
    except Exception as error:  # noqa: BLE001 - parent preserves the failure
        output.put({"status": "failed", "error": f"{type(error).__name__}: {error}"})


def _export_with_budget(
    spec: dict,
    benchmark_id: str,
    destination: Path,
    *,
    time_limit_s: float,
):
    context = multiprocessing.get_context("spawn")
    output = context.Queue(maxsize=1)
    temporary = destination.with_suffix(destination.suffix + ".candidate")
    temporary.parent.mkdir(parents=True, exist_ok=True)
    process = context.Process(
        target=_export_worker,
        args=(spec, benchmark_id, str(temporary), output),
    )
    process.start()
    process.join(time_limit_s)
    if process.is_alive():
        process.terminate()
        process.join()
        temporary.unlink(missing_ok=True)
        raise TimeoutError(f"conversion exceeded process wall limit {time_limit_s}s")
    try:
        result = output.get_nowait()
    except queue.Empty as error:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"conversion worker exited {process.exitcode} without result") from error
    if result["status"] != "completed":
        temporary.unlink(missing_ok=True)
        raise RuntimeError(result["error"])
    os.replace(temporary, destination)
    return load_benchmark(destination)


def _tier(task_count: int) -> str:
    if task_count <= 300:
        return "small"
    return "medium_candidate"


def _manifest_row(benchmark, relative: Path, run_id: str, spec: dict) -> dict:
    parameter_hash = canonical_sha256(spec)
    source = benchmark.metadata.get("provenance", {}).get("source", {})
    topology = benchmark.metadata.get("provenance", {}).get("topology", {})
    return {
        "manifest_version": MANIFEST_VERSION,
        "publication_run_id": run_id,
        "benchmark_id": benchmark.benchmark_id,
        "path": (Path("nonpreemptive") / relative).as_posix(),
        "conversion_status": "valid",
        "contention_classification": "unknown",
        "contention_evidence_level": "not_run",
        "publication_status": "staged",
        "baseline_status": "not_run",
        "baseline_result": None,
        "exact_optional_status": "not_run",
        "exact_optional_result": None,
        "exact_work_conserving_status": "not_run",
        "exact_work_conserving_result": None,
        "size_tier": _tier(len(benchmark.tasks)),
        "task_count": len(benchmark.tasks),
        "communication_count": sum(task.kind == "communication" for task in benchmark.tasks),
        "source_id": source.get("name"),
        "source_hash": source.get("content_hash"),
        "topology_hash": topology.get("content_hash"),
        "parameter_hash": parameter_hash,
        "content_hash": None,
        "contention_report": None,
        "contention_report_hash": None,
        "spec": spec,
    }


def generate(
    root: Path,
    *,
    run_id: str | None = None,
    max_base_cases: int | None = None,
    generation_time_limit_s: float = 60.0,
) -> Path:
    root = root.resolve()
    llm_root = root / "llm_structure"
    run_id = run_id or datetime.now(UTC).strftime("np-run-%Y%m%dT%H%M%SZ")
    staging = llm_root / ".staging" / run_id
    resuming = staging.exists()
    hash_cache = FileHashCache()
    sources = source_catalog(AICB_ROOT, hash_cache=hash_cache)
    topologies = topology_catalog(TOPOLOGIES, TOPO_ROOT, hash_cache=hash_cache)
    write_jsonl_atomic(staging / "source_catalog.jsonl", sources)
    write_jsonl_atomic(staging / "topology_catalog.jsonl", topologies)
    specs = _selected_specs(sources)
    if max_base_cases is not None:
        specs = specs[:max_base_cases]
    rows: list[dict] = (
        read_jsonl(staging / "candidate_manifest.jsonl")
        if resuming and (staging / "candidate_manifest.jsonl").is_file()
        else []
    )
    base_cases: list[tuple[object, Path, dict]] = []
    small_cases: list[tuple[object, Path, dict]] = []
    output = staging / "nonpreemptive"
    existing_ids = {row.get("benchmark_id") for row in rows}
    for row in rows:
        if row.get("conversion_status") != "valid" or not row.get("path"):
            continue
        path = staging / row["path"]
        if not path.is_file():
            continue
        benchmark = load_benchmark(path)
        record = (benchmark, path, row.get("spec", {}))
        if row.get("size_tier") == "small":
            small_cases.append(record)
        elif "real_derived" not in Path(row["path"]).parts:
            base_cases.append(record)

    def checkpoint() -> None:
        write_jsonl_atomic(
            staging / "candidate_manifest.jsonl", sorted(rows, key=lambda row: row["benchmark_id"])
        )

    for spec in specs:
        benchmark_id = _benchmark_id(spec)
        if benchmark_id in existing_ids:
            continue
        try:
            relative = (
                Path("routed" if spec.get("topology") else "single_channel")
                / f"{benchmark_id}.json"
            )
            path = output / relative
            benchmark = _export_with_budget(
                spec,
                benchmark_id,
                path,
                time_limit_s=generation_time_limit_s,
            )
            row = _manifest_row(benchmark, relative, run_id, spec)
            row["content_hash"] = hash_cache.get(path)
            rows.append(row)
            base_cases.append((benchmark, path, spec))

            # Only observed decision tasks may anchor real-derived slices.
            if sum(row.get("size_tier") == "small" for row in rows) >= 26:
                checkpoint()
                continue
            audit = contention_audit(benchmark, max_decisions=16)
            anchor_groups: list[tuple[str, ...]] = []
            for decision in audit["decisions"]:
                ready = tuple(decision["ready_communications"])
                anchor_groups.extend((item,) for item in ready)
                if len(ready) >= 2:
                    anchor_groups.append(tuple(ready[:2]))
            seen_anchors = set()
            for index, anchors in enumerate(anchor_groups):
                if anchors in seen_anchors:
                    continue
                seen_anchors.add(anchors)
                try:
                    sliced = causal_closure_slice(
                        benchmark,
                        anchors=anchors,
                        max_tasks=300,
                        successor_depth=index % 3,
                        suffix=f"decision_slice_{index:02d}",
                    )
                except ValueError:
                    continue
                slice_relative = Path("real_derived") / f"{sliced.benchmark_id}.json"
                slice_path = output / slice_relative
                write_benchmark(sliced, slice_path)
                slice_spec = {**spec, "slice": sliced.metadata["slice_relation"]}
                slice_row = _manifest_row(sliced, slice_relative, run_id, slice_spec)
                slice_row["content_hash"] = hash_cache.get(slice_path)
                rows.append(slice_row)
                small_cases.append((sliced, slice_path, slice_spec))
                if sum(row.get("size_tier") == "small" for row in rows) >= 26:
                    break
        except Exception as error:  # noqa: BLE001 - preserve failed candidate
            conversion_status = "timeout" if isinstance(error, TimeoutError) else "invalid"
            rows.append(
                {
                    "manifest_version": MANIFEST_VERSION,
                    "publication_run_id": run_id,
                    "benchmark_id": benchmark_id,
                    "path": None,
                    "conversion_status": conversion_status,
                    "contention_classification": (
                        "unknown_timeout" if conversion_status == "timeout" else "invalid"
                    ),
                    "contention_evidence_level": "not_run",
                    "publication_status": "excluded",
                    "baseline_status": "not_run",
                    "exact_optional_status": "not_run",
                    "exact_work_conserving_status": "not_run",
                    "error": f"{type(error).__name__}: {error}",
                    "spec": spec,
                }
            )
        checkpoint()
    single_bases = [item for item in small_cases if item[0].scenario == "single_channel"]
    if len(single_bases) >= 2:
        combinations = (
            (single_bases[0], single_bases[0], 0, "homogeneous_simultaneous"),
            (single_bases[0], single_bases[0], 10, "homogeneous_staggered"),
            (single_bases[0], single_bases[1], 0, "heterogeneous_simultaneous"),
            (single_bases[0], single_bases[1], 10, "heterogeneous_staggered"),
        )
        for left, right, arrival, label in combinations:
            benchmark_id = f"np_multi_job_{label}"
            if benchmark_id in existing_ids:
                continue
            composed = compose_real_jobs(
                [("job0", left[0], 0), ("job1", right[0], arrival)],
                benchmark_id=benchmark_id,
                source_paths=[left[1], right[1]],
            )
            relative = Path("multi_job") / f"{benchmark_id}.json"
            path = output / relative
            write_benchmark(composed, path)
            spec = {
                "composition": label,
                "arrival": [0, arrival],
                "sources": [left[0].benchmark_id, right[0].benchmark_id],
            }
            row = _manifest_row(composed, relative, run_id, spec)
            row["content_hash"] = hash_cache.get(path)
            rows.append(row)
        checkpoint()
    write_jsonl_atomic(
        staging / "run_metadata.jsonl",
        [
            {
                "publication_run_id": run_id,
                "workflow_version": PUBLICATION_RUN_VERSION,
                "generated_at": datetime.now(UTC).isoformat(),
                "multi_iteration": {
                    "status": "not_supported",
                    "reason": "SimAI exposes no verified static native N-iteration DAG export API",
                    "projected_repetition_is_formal_evidence": False,
                },
                "case_count": sum(row.get("conversion_status") == "valid" for row in rows),
                "generation_time_limit_s": generation_time_limit_s,
                "audit_manifest_checkpoint_batch": 16,
            }
        ],
    )
    return staging


def audit(
    root: Path,
    *,
    manifest: Path,
    max_decisions: int = 8,
    enumeration_limit: int = 256,
    limit: int | None = None,
) -> Path:
    root = root.resolve()
    manifest = manifest.resolve()
    staging = manifest.parent
    rows = read_jsonl(manifest)
    processed = 0
    reports = staging / "artifacts" / "contention"
    try:
        for row in rows:
            if limit is not None and processed >= limit:
                break
            if (
                row.get("conversion_status") != "valid"
                or row.get("contention_evidence_level") != "not_run"
            ):
                continue
            path = staging / row["path"]
            report = contention_audit(
                load_benchmark(path),
                max_decisions=max_decisions,
                enumeration_limit=enumeration_limit,
            )
            # JSONL keeps audit answers out of repository-wide ``*.json`` problem
            # discovery while remaining machine-readable and hash-addressed.
            report_path = reports / f"{row['benchmark_id']}.jsonl"
            write_json_atomic(report_path, report)
            row["contention_evidence_level"] = report["evidence_level"]
            row["contention_classification"] = (
                "non_equivalent_choice_observed"
                if report["non_equivalent_choice_observed"]
                else "choice_observed"
                if any(
                    report[key]
                    for key in (
                        "ordering_choice_observed",
                        "set_choice_observed",
                        "wait_choice_observed",
                    )
                )
                else "no_choice_observed"
            )
            row["contention_report"] = report_path.relative_to(staging).as_posix()
            row["contention_report_hash"] = sha256_file(report_path)
            processed += 1
            if processed % 16 == 0:
                write_jsonl_atomic(manifest, rows)
    finally:
        # Persist the partial batch on interruption as well; at most 15 rows
        # need to be replayed after recovery.
        write_jsonl_atomic(manifest, rows)
    return manifest


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("generate", "audit", "publish"), required=True)
    parser.add_argument("--output", type=Path, default=Path("benchmark"))
    parser.add_argument("--run-id")
    parser.add_argument("--staging", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--max-base-cases", type=int)
    parser.add_argument("--generation-time-limit-s", type=float, default=60.0)
    parser.add_argument("--max-decisions", type=int, default=8)
    parser.add_argument("--enumeration-limit", type=int, default=256)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args(argv)
    if args.mode == "generate":
        print(
            generate(
                args.output,
                run_id=args.run_id,
                max_base_cases=args.max_base_cases,
                generation_time_limit_s=args.generation_time_limit_s,
            )
        )
    elif args.mode == "audit":
        if args.manifest is None:
            parser.error("--manifest is required for audit")
        print(
            audit(
                args.output,
                manifest=args.manifest,
                max_decisions=args.max_decisions,
                enumeration_limit=args.enumeration_limit,
                limit=args.limit,
            )
        )
    else:
        if args.staging is None:
            parser.error("--staging is required for publish")
        path, count = publish(args.output, staging=args.staging)
        print(f"published snapshot and rebuilt {count} index rows: {path}")


if __name__ == "__main__":
    main()
