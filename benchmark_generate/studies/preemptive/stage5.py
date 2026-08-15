"""Reproducible synthetic repetition and symmetry study for v2."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from llm_structured.repetition import (
    build_exchangeable_replicas,
    build_pp_dp_repetition,
    exact_oracle_component_symmetry,
    schedule_coupling_aware,
    schedule_role_copy,
)
from single_channel.complex_chain.preemptive.solver import exact_oracle


def run_study() -> dict:
    repetition = []
    for periods in (1, 2, 4, 8, 16):
        dag = build_pp_dp_repetition(periods)
        repetition.append(
            {
                "periods": periods,
                "exact_makespan": exact_oracle(dag).makespan,
                "independent_copy_makespan": schedule_role_copy(dag, "DP").makespan,
                "boundary_aware_makespan": schedule_coupling_aware(dag).makespan,
            }
        )
    symmetry = []
    for replicas in (3, 4, 5, 6, 7):
        dag, components = build_exchangeable_replicas(replicas)
        compressed = exact_oracle_component_symmetry(
            dag, components, max_states=100_000
        )
        generic = exact_oracle(dag, max_states=100_000)
        symmetry.append(
            {
                "replicas": replicas,
                "makespan": compressed.makespan,
                "compressed_states": compressed.explored_states,
                "generic_states": generic.explored_states,
            }
        )
    return {
        "model": {
            "preemption": "communication_resume",
            "decision_epoch": "task_event",
            "work_conserving": True,
            "preemption_cost": 0,
            "minimum_quantum": 0,
            "objective": "makespan",
        },
        "synthetic_repetition": repetition,
        "exchangeable_symmetry": symmetry,
        "scope": "synthetic fixed motifs; no SimAI/AICB workload is included",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run_study()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"wrote stage-5 study to {args.output}")


if __name__ == "__main__":
    main()
