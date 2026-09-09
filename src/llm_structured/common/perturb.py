"""Deterministic duration perturbation for robustness studies."""

from __future__ import annotations

import random
from dataclasses import replace

from core.dag import DAG


def perturb_durations(
    dag: DAG,
    magnitude: float,
    seed: int,
) -> DAG:
    """Return a copy with each positive duration jittered by ``卤magnitude``.

    Zero-duration structural nodes (release/backbone markers) are kept
    unchanged, and every result is rounded to a positive integer so the
    perturbed DAG remains a legal benchmark.  This is a research probe for
    robustness, not a benchmark generator.
    """

    if not 0.0 <= magnitude < 1.0:
        raise ValueError("magnitude must be in [0, 1)")
    rng = random.Random(seed)
    tasks = []
    for task in dag.tasks:
        if task.duration == 0:
            tasks.append(task)
            continue
        factor = 1.0 + rng.uniform(-magnitude, magnitude)
        # ``duration`` is already expressed in the DAG's integer time unit.
        # Do not multiply by ten here: the old implementation silently changed
        # a jitter probe into a ten-fold workload scaling experiment.
        tasks.append(replace(task, duration=max(1, round(task.duration * factor))))
    return replace(dag, name=f"{dag.name}_jitter{magnitude}_{seed}", tasks=tuple(tasks))


__all__ = ["perturb_durations"]
