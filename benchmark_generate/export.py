"""Materialize the current fixed and seeded research suites as JSON files."""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from benchmark import Benchmark, SchedulingSemantics, load_benchmark, write_benchmark
from benchmark_generate.convert import (
    dag_to_benchmark,
    multi_resource_to_benchmark,
    parallel_chains_to_benchmark,
)
from benchmark_generate.layout import (
    LAYOUT_VERSION,
    benchmark_relative_path,
    semantics_name,
)


@dataclass(frozen=True)
class ExportedCase:
    benchmark: Benchmark
    relative_path: Path


SemanticVariant = Literal["preemptive", "nonpreemptive"]

PREEMPTIVE_SEMANTICS = SchedulingSemantics(
    preemption="communication_resume",
    decision_epoch="task_event",
    optional_idle=False,
    compute_model="unbounded_parallel",
    resource_model="exclusive_fixed_set",
    preemption_cost=0,
    minimum_quantum=0,
)


def current_cases(*, samples: int, seed: int) -> list[ExportedCase]:
    from benchmark_generate.cases import (
        classic_parallel_counterexamples,
        combined_chain_probes,
        complex_adversarial_cases,
        fixed_beam_counterexample,
        historical_random_join_counterexamples,
        historical_wait_hard_chains,
        last_blocker_overboost_counterexample,
        llm_motif_cases,
        manual_route_cases,
        multi_resource_motifs,
        random_join_dag,
        random_multi_resource_instance,
        random_parallel_chains,
        rollout_depth_counterexample,
        scaled_five_four_family,
        tight_optional_wait_family,
    )
    from single_channel.parallel_chain.model import ParallelChain

    exported: list[ExportedCase] = []
    parallel_rng = random.Random(seed)
    complex_rng = random.Random(seed + 1)
    muti_rng = random.Random(seed + 2)
    parallel_cases = {
        "adversarial": [
            ("tight_optional_wait_m20", tight_optional_wait_family(20)),
            ("scaled_five_four_s4", scaled_five_four_family(4)),
            ("fixed_beam_counterexample", fixed_beam_counterexample()),
            ("rollout_depth_counterexample", rollout_depth_counterexample()),
            *classic_parallel_counterexamples(),
            *historical_wait_hard_chains(),
        ],
        "random": [
            (f"random_chain_{index}", random_parallel_chains(parallel_rng))
            for index in range(samples)
        ],
        "real": [
            (
                "structured_symmetric",
                (
                    ParallelChain((2, 2), (2, 2), 0),
                    ParallelChain((2, 2), (2, 2), 0),
                    ParallelChain((2, 2), (2, 2), 0),
                ),
            ),
            (
                "structured_channel_bound",
                (
                    ParallelChain((6, 5), (1, 1), 0),
                    ParallelChain((5, 6), (1, 1), 1),
                    ParallelChain((7,), (1,), 0),
                ),
            ),
            (
                "structured_compute_bound",
                (
                    ParallelChain((1, 1), (8, 7), 0),
                    ParallelChain((1, 1), (7, 8), 1),
                    ParallelChain((1,), (10,), 2),
                ),
            ),
            (
                "1f1b_chain_projection",
                (
                    ParallelChain((2, 2, 1), (3, 2, 1), 0),
                    ParallelChain((1, 2, 2), (2, 3, 1), 1),
                    ParallelChain((2, 1, 2), (2, 2, 2), 2),
                ),
            ),
            (
                "zero_bubble_chain_projection",
                (
                    ParallelChain((2, 1, 1), (3, 1, 2), 0),
                    ParallelChain((1, 1, 2), (2, 2, 1), 1),
                    ParallelChain((1, 2), (1, 3), 2),
                ),
            ),
        ],
    }
    for category, cases in parallel_cases.items():
        for name, instance in cases:
            benchmark = parallel_chains_to_benchmark(
                name,
                category,
                instance,
                metadata=_parallel_case_metadata(name, category, seed),
            )
            exported.append(_case(benchmark, "single_channel", "parallel_chain", category))
    complex_cases = {
        "adversarial": [
            *complex_adversarial_cases(),
            last_blocker_overboost_counterexample(),
            *historical_random_join_counterexamples(),
            *combined_chain_probes(),
        ],
        "random": [random_join_dag(complex_rng, index) for index in range(samples)],
        "real": llm_motif_cases(),
    }
    for category, cases in complex_cases.items():
        for index, dag in enumerate(cases):
            benchmark = dag_to_benchmark(
                dag,
                category,
                metadata={
                    "generator": "complex_chain",
                    "seed": seed + 1 if category == "random" else None,
                },
            )
            if category == "random":
                benchmark = _with_id(benchmark, f"complex_random_{index:03d}")
            exported.append(_case(benchmark, "single_channel", "complex_chain", category))
    muti_cases = {
        "adversarial": multi_resource_motifs(),
        "random": [random_multi_resource_instance(muti_rng, index) for index in range(samples)],
        "real": manual_route_cases(),
    }
    for category, cases in muti_cases.items():
        for index, instance in enumerate(cases):
            benchmark = multi_resource_to_benchmark(
                instance,
                category,
                metadata={
                    "generator": "muti_channel",
                    "seed": seed + 2 if category == "random" else None,
                },
            )
            if category == "random":
                benchmark = _with_id(benchmark, f"muti_random_{index:03d}")
            exported.append(_case(benchmark, "muti_channel", "complex_chain", category))
    return exported


def export_semantic_suite(
    root: Path,
    *,
    semantics: SemanticVariant,
    samples: int = 10,
    seed: int = 260819,
    categories: set[str] | None = None,
) -> list[Path]:
    """Write one explicitly selected semantic variant through the shared layout."""

    if semantics not in {"preemptive", "nonpreemptive"}:
        raise ValueError(f"unsupported semantics: {semantics}")
    written: list[Path] = []
    for item in current_cases(samples=samples, seed=seed):
        if categories is not None and item.benchmark.category not in categories:
            continue
        if (
            semantics == "nonpreemptive"
            and item.benchmark.metadata.get("semantic_scope") == "preemptive_only"
        ):
            continue
        if semantics == "preemptive":
            if item.benchmark.category == "real" and item.benchmark.family != "parallel_chain":
                continue
            benchmark = _as_preemptive(item.benchmark, seed=seed)
        else:
            benchmark = item.benchmark
        target = root / benchmark_relative_path(benchmark)
        write_benchmark(benchmark, target)
        written.append(target)
    return written


def build_index(root: Path) -> list[dict]:
    """Rebuild the shared index without generating either semantic variant."""

    rows = []
    for target in sorted(root.rglob("*.json")):
        if "schema" in target.parts or "reference_results" in target.parts:
            continue
        relative = target.relative_to(root).as_posix()
        benchmark = load_benchmark(target)
        rows.append(
            {
                "id": benchmark.benchmark_id,
                "path": relative,
                "scenario": benchmark.scenario,
                "family": benchmark.family,
                "category": benchmark.category,
                "semantics": semantics_name(benchmark),
                "layout_version": LAYOUT_VERSION,
                "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            }
        )
    rows.sort(key=lambda row: (row["scenario"], row["family"], row["category"], row["id"]))
    (root / "index.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
        newline="\n",
    )
    return rows


def _case(benchmark: Benchmark, scenario: str, family: str, category: str) -> ExportedCase:
    if (benchmark.scenario, benchmark.family, benchmark.category) != (
        scenario,
        family,
        category,
    ):
        raise ValueError("case metadata does not match its requested path")
    return ExportedCase(benchmark, benchmark_relative_path(benchmark))


def _with_id(benchmark: Benchmark, benchmark_id: str) -> Benchmark:
    return replace(benchmark, benchmark_id=benchmark_id)


def _as_preemptive(benchmark: Benchmark, *, seed: int) -> Benchmark:
    metadata = {
        **benchmark.metadata,
        "preemptive_generator_seed": seed,
    }
    if benchmark.metadata.get("semantic_scope") == "preemptive_only":
        metadata["designed_for"] = "communication_resume"
    else:
        metadata["lifted_from"] = benchmark.benchmark_id
    return replace(
        benchmark,
        benchmark_id=f"pm_{benchmark.benchmark_id.removesuffix('_np')}",
        schema_version="2.0",
        semantics=PREEMPTIVE_SEMANTICS,
        metadata=metadata,
    )


def _parallel_case_metadata(name: str, category: str, seed: int) -> dict:
    metadata = {
        "generator": "parallel_chain",
        "seed": seed if category == "random" else None,
        "stage1_group": category,
    }
    if name == "rollout_depth_counterexample":
        metadata.update(
            {
                "semantic_scope": "preemptive_only",
                "discovery_seed": 26081601,
                "discovery_index": 100,
            }
        )
    if name.startswith("structured_"):
        metadata.update(
            {
                "stage1_group": "structured",
                "provenance": "parameterized synthetic independent chains",
                "projection_equivalence": "native Stage 1 instance; no dependencies removed",
            }
        )
        if name == "rollout_depth_counterexample":
            metadata.update(
                {
                    "historical_origin": "fixed-seed Stage 1 rollout search",
                    "mechanism": "depth two sees a release consequence hidden from depth one",
                }
            )
    elif name.endswith("_chain_projection"):
        metadata.update(
            {
                "stage1_group": "real_projection",
                "provenance": "synthetic projection parameterized from an LLM pipeline pattern",
                "projection_equivalence": (
                    "independent-chain scheduling hypothesis only; fork/join and cross-chain "
                    "dependencies are not represented"
                ),
            }
        )
    if category == "adversarial":
        targets = {
            "longest_tail_counterexample": "longest_tail",
            "lrpt_double_count": "lrpt",
            "fixed_beam_counterexample": "fixed_width_beam",
            "rollout_depth_counterexample": "finite_depth_rollout",
            "large_flow_vs_long_tail": "lpt_and_local_size",
            "scaled_five_four_s4": "longest_tail",
            "tight_optional_wait_m20": "historical_nonpreemptive_wait_baseline",
        }
        target = targets.get(name, "legacy_regression")
        metadata.update(
            {
                "attack_target": target,
                "historical_origin": "v1/nonpreemptive lift",
                "current_semantic_role": (
                    "active adversarial regression"
                    if target
                    not in {
                        "legacy_regression",
                        "historical_nonpreemptive_wait_baseline",
                    }
                    else "legacy regression; not a current WAIT counterexample"
                ),
                "mechanism": (
                    "communication size competes with delayed downstream compute release"
                ),
            }
        )
    return metadata
