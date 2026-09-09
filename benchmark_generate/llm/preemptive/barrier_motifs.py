"""Small barrier motifs and bounded Exact labels.

The generator is intentionally separate from the runtime algorithms.  It
creates self-contained DAGs, drives the public simulators, and can write
representative JSON files or a machine-readable motif report.  Intermediate
parameter-grid cases are not written unless explicitly requested.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from benchmark import SchedulingSemantics, write_benchmark
from benchmark_generate.convert import dag_to_benchmark, multi_resource_to_benchmark
from core.dag import DAG, Task
from core.execution.preemptive import MultiResourceAction, PreeMultiModel
from core.execution.preemptive import Action, PreeSingleModel
from core.oracle.pree_single import exact_oracle
from llm_structured.preemptive.barrier.analysis import action_features, build_context, feature_snapshot
from llm_structured.preemptive.barrier.policy import schedule_barrier_policy
from muti_channel.preemptive.solver import schedule_set_policy
from core.oracle.pree_multi import exact_oracle as multi_exact_oracle
from single_channel.complex_chain.preemptive.solver import (
    schedule_longest_tail,
)


@dataclass(frozen=True)
class BarrierMotif:
    name: str
    dag: DAG
    resources: dict[str, frozenset[str]] | None = None
    description: str = ""


def single_channel_motifs() -> tuple[BarrierMotif, ...]:
    """Return B0--B8 controlled single-channel motifs."""

    def base(name: str, extra: tuple[Task, ...], description: str) -> BarrierMotif:
        tasks = (
            Task("release", "compute", 2),
            Task("R", "comm", 6),
            Task("N", "comm", 1, ("release",)),
            *extra,
        )
        return BarrierMotif(name, DAG(name, tasks, context=(('category', 'adversarial'),)), description=description)

    return (
        base("barrier_B0_no_unlock", (), "N has no downstream release or join."),
        base(
            "barrier_B1_unlock",
            (Task("unlock_compute", "compute", 5, ("N",)),),
            "N immediately releases overlapable compute.",
        ),
        base(
            "barrier_B2_local_short",
            (
                Task("done", "compute", 0),
                Task("local_join", "compute", 1, ("N", "done")),
            ),
            "N is last missing predecessor of a short local join.",
        ),
        base(
            "barrier_B3_local_long",
            (
                Task("done", "compute", 0),
                Task("local_join", "compute", 1, ("N", "done")),
                Task("local_tail", "compute", 8, ("local_join",)),
            ),
            "N is last missing predecessor of a long local tail.",
        ),
        base(
            "barrier_B4_global_join",
            (
                Task("done", "compute", 0),
                Task("global_join", "compute", 1, ("N", "done")),
                Task("R_after", "compute", 2, ("R",)),
                Task("global_tail", "compute", 10, ("global_join", "R_after")),
            ),
            "N is the last missing predecessor of a join that feeds the only residual sink.",
        ),
        base(
            "barrier_B5_R_longer_tail",
            (
                Task("R_tail", "compute", 12, ("R",)),
                Task("unlock_compute", "compute", 1, ("N",)),
            ),
            "R has the longer residual critical tail; switching is a negative control.",
        ),
        base(
            "barrier_B6_same_static_tail_remaining_diff",
            (
                Task("N_tail", "compute", 4, ("N",)),
                Task("R_tail", "compute", 4, ("R",)),
            ),
            "Static downstream shape is similar while current remaining work differs.",
        ),
        BarrierMotif(
            "barrier_B7_same_labels_different_structure",
            DAG('barrier_B7_same_labels_different_structure', (Task('release', 'compute', 2), Task('R', 'comm', 6, labels=(('collective_type', 'allreduce'),)), Task('N', 'comm', 1, ('release',), labels=(('collective_type', 'allreduce'),)), Task('local_join', 'compute', 1, ('N', 'R')), Task('other', 'comm', 2, labels=(('collective_type', 'allreduce'),)), Task('other_tail', 'compute', 9, ('other',))), context=(('category', 'adversarial'), ('description', 'Same label hint, different residual downstream structure.'))),
            description="Same labels must not force a fixed priority.",
        ),
        BarrierMotif(
            "barrier_B8_serializer_like",
            DAG('barrier_B8_serializer_like', (Task('release', 'compute', 2), Task('R', 'comm', 6, labels=(('task_role', 'serializer'),)), Task('N', 'comm', 1, ('release',), labels=(('task_role', 'serializer'),)), Task('serialized', 'compute', 2, ('R', 'N'), labels=(('task_role', 'serializer'),)), Task('sink', 'compute', 5, ('serialized',))), context=(('category', 'adversarial'), ('description', 'Serializer-shaped join is classified structurally without changing legality.'))),
            description="Serializer provenance is diagnostic only.",
        ),
    )


def multi_resource_motifs() -> tuple[BarrierMotif, ...]:
    """Return fixed-resource packing motifs with the same residual barrier core."""

    dag = DAG('barrier_multi_packing', (Task('release', 'compute', 3), Task('R', 'comm', 5), Task('N', 'comm', 1, ('release',)), Task('side', 'comm', 6), Task('join_other', 'compute', 0), Task('join', 'compute', 1, ('N', 'join_other')), Task('tail', 'compute', 7, ('join', 'R', 'side'))), context=(('category', 'adversarial'), ('description', 'N is a barrier last-missing candidate while side can pack on a disjoint resource.')))
    resources = {"R": frozenset({"hot"}), "N": frozenset({"hot"}), "side": frozenset({"cool"})}
    return (
        BarrierMotif(
            "barrier_multi_packing",
            dag,
            resources,
            dag.context_map().get("description", ""),
        ),
    )


def _exact_from_state(model: Any, state: Any, memo: dict[tuple, tuple[int, tuple[Any, ...]]]) -> tuple[int, tuple[Any, ...]]:
    """Tiny public-transition Exact used only for controlled motif labels."""

    forced_elapsed = 0
    if hasattr(model, "normalize_decision_state"):
        original_time = state.time
        state, _idle = model.normalize_decision_state(state)
        forced_elapsed = state.time - original_time
        key = ("multi", tuple((item.status, item.remaining) for item in state.tasks))
        actions = model.legal_actions(state)
    else:
        while not model.is_finished(state) and not model.eligible_communications(state):
            before = state.time
            state = model.step(state, Action.wait()).after
            forced_elapsed += state.time - before
        key = ("single", tuple((item.status, item.remaining) for item in state.tasks))
        actions = model.legal_actions(state)
    if key in memo:
        cached = memo[key]
        return forced_elapsed + cached[0], cached[1]
    if model.is_finished(state) if hasattr(model, "is_finished") else model.finished(state):
        return (forced_elapsed, ())
    best: tuple[int, tuple[Any, ...]] | None = None
    for action in actions:
        after = model.step(state, action)
        if hasattr(after, "after"):
            after = after.after
        child_cost, child_actions = _exact_from_state(model, after, memo)
        elapsed = after.time - state.time
        candidate = (elapsed + child_cost, (action, *child_actions))
        if best is None or (candidate[0], tuple(repr(x) for x in candidate[1])) < (
            best[0], tuple(repr(x) for x in best[1])
        ):
            best = candidate
    if best is None:
        raise RuntimeError("motif state has no legal successor")
    memo[key] = best
    return forced_elapsed + best[0], best[1]


def _optimal_first_actions(model: Any, state: Any) -> tuple[int, tuple[Any, ...]]:
    """Enumerate all tied optimal first actions at one scripted state."""

    if hasattr(model, "normalize_decision_state"):
        state, _idle = model.normalize_decision_state(state)
        actions = model.legal_actions(state)
    else:
        while not model.is_finished(state) and not model.eligible_communications(state):
            state = model.step(state, Action.wait()).after
        actions = model.legal_actions(state)
    scored: list[tuple[int, Any]] = []
    for action in actions:
        after = model.step(state, action)
        if hasattr(after, "after"):
            after = after.after
        child_cost, _suffix = _exact_from_state(model, after, {})
        scored.append((after.time - state.time + child_cost, action))
    if not scored:
        raise RuntimeError("motif state has no legal first action")
    best = min(value for value, _action in scored)
    return best, tuple(action for value, action in scored if value == best)


def _first_action_costs(model: Any, state: Any) -> dict[str, int]:
    """Return every legal first action's residual cost-to-go."""

    if hasattr(model, "normalize_decision_state"):
        state, _idle = model.normalize_decision_state(state)
        actions = model.legal_actions(state)
    else:
        while not model.is_finished(state) and not model.eligible_communications(state):
            state = model.step(state, Action.wait()).after
        actions = model.legal_actions(state)
    result: dict[str, int] = {}
    for action in actions:
        after = model.step(state, action)
        if hasattr(after, "after"):
            after = after.after
        child_cost, _suffix = _exact_from_state(model, after, {})
        result[repr(action)] = after.time - state.time + child_cost
    return result


def label_motif(motif: BarrierMotif) -> dict[str, Any]:
    """Produce bounded labels and policy observations for one motif."""

    if motif.resources is None:
        model = PreeSingleModel(motif.dag)
        initial = model.initial_state()
        scripted = model.step(initial, Action.run("R")).after
        context = build_context(model, scripted)
        candidates = tuple(model.eligible_communications(scripted))
        labels = _optimal_first_actions(model, scripted)
        policy = {
            mode: schedule_barrier_policy(motif.dag, mode).makespan
            for mode in ("barrier_only", "unlock_only", "tail", "tail_barrier", "tail_unlock_barrier")
        }
        baseline = schedule_longest_tail(motif.dag)
        oracle = exact_oracle(motif.dag, max_states=100_000, time_limit_s=2.0)
        return {
            "name": motif.name,
            "channel": "single",
            "candidates_at_scripted_state": list(candidates),
            "features": {item: feature_snapshot(context, item).__dict__ for item in candidates},
            "scripted_action_cost_to_go": labels[0],
            "scripted_action_costs": _first_action_costs(model, scripted),
            "scripted_optimal_actions": [repr(item) for item in labels[1]],
            "baseline_makespan": baseline.makespan,
            "exact": {"status": oracle.status, "makespan": oracle.makespan, "states": oracle.explored_states},
            "policy_makespans": policy,
            "description": motif.description,
        }
    model = PreeMultiModel(motif.dag, motif.resources)
    initial = model.initial_state()
    scripted = model.step(initial, MultiResourceAction(("R", "side")))
    context = build_context(model, scripted)
    candidates = tuple(model.eligible(scripted))
    sets = model.maximal_actions(scripted)
    labels = _optimal_first_actions(model, scripted)
    union = {str(action.communications): action_features(context, action.communications).__dict__ for action in sets}
    baseline = schedule_set_policy(motif.dag, motif.resources)
    oracle = multi_exact_oracle(
        motif.dag, motif.resources, max_states=100_000, time_limit_s=2.0
    )
    return {
        "name": motif.name,
        "channel": "multi",
        "candidates_at_scripted_state": list(candidates),
        "features": {item: feature_snapshot(context, item).__dict__ for item in candidates},
        "maximal_actions": [list(action.communications) for action in sets],
        "action_features": union,
        "scripted_action_cost_to_go": labels[0],
        "scripted_action_costs": _first_action_costs(model, scripted),
        "scripted_optimal_actions": [repr(item) for item in labels[1]],
        "baseline_makespan": baseline.makespan,
        "exact": {
            "status": oracle.status,
            "makespan": oracle.makespan,
            "states": oracle.explored_states,
        },
        "description": motif.description,
    }


def write_motifs(root: Path) -> list[Path]:
    """Write only the representative fixed motifs, with v2 semantics."""

    written: list[Path] = []
    semantics = SchedulingSemantics(
        preemption="communication_resume",
        decision_epoch="task_event",
        optional_idle=False,
        compute_model="unbounded_parallel",
        resource_model="exclusive_fixed_set",
    )
    for motif in (*single_channel_motifs(), *multi_resource_motifs()):
        if motif.resources is None:
            benchmark = dag_to_benchmark(motif.dag, "adversarial")
            target = root / "single_channel" / "complex_chain" / "preemptive" / "adversarial" / f"{motif.name}.json"
        else:
            benchmark = multi_resource_to_benchmark(motif.dag, "adversarial")
            target = root / "muti_channel" / "preemptive" / "adversarial" / f"{motif.name}.json"
        benchmark = replace(benchmark, semantics=semantics, schema_version="2.0")
        write_benchmark(benchmark, target)
        written.append(target)
    return written


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-benchmarks", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    motifs = (*single_channel_motifs(), *multi_resource_motifs())
    if args.write_benchmarks:
        write_motifs(args.write_benchmarks)
    canonical = [
        {
            "name": item.name,
            "tasks": [
                (task.task_id, task.kind, task.duration, task.deps, task.labels)
                for task in item.dag.tasks
            ],
            "resources": {
                key: sorted(values) for key, values in sorted((item.resources or {}).items())
            },
        }
        for item in motifs
    ]
    benchmark_hash = hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
        dirty = subprocess.run(["git", "diff", "--quiet"], check=False).returncode != 0
    except (OSError, subprocess.CalledProcessError):
        revision, dirty = None, None
    report = {
        "schema_version": "barrier-motif-labels-v1",
        "code_revision": revision,
        "dirty": dirty,
        "benchmark_hash": benchmark_hash,
        "motifs": [label_motif(item) for item in motifs],
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
