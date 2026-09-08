"""Neutral structural contract for the Stage 1 parallel-chain family."""

from __future__ import annotations

from dataclasses import dataclass

from core.dag import DAG, DAGBuilder


@dataclass(frozen=True)
class ParallelChain:
    """Generator-friendly ``compute?-(communication-compute)*`` chain."""

    comm: tuple[int, ...]
    compute: tuple[int, ...]
    initial_delay: int = 0

    def __post_init__(self) -> None:
        if not self.comm or len(self.comm) != len(self.compute):
            raise ValueError("comm and compute must have the same positive length")
        if any(value <= 0 for value in self.comm):
            raise ValueError("communication durations must be positive")
        if self.initial_delay < 0 or any(value < 0 for value in self.compute):
            raise ValueError("compute durations must be non-negative")


def to_benchmark_dag(
    chains: tuple[ParallelChain, ...],
) -> tuple[DAG, dict[tuple[int, int], str]]:
    """Build a neutral internal DAG for generator and cross-Oracle use."""

    builder = DAGBuilder("parallel_chains", context=(("category", "parallel_chain"), ("description", "Compact-chain replay DAG.")))
    flow_ids: dict[tuple[int, int], str] = {}
    for chain_index, chain in enumerate(chains):
        previous = None
        if chain.initial_delay:
            previous = builder.add(f"c{chain_index}_release", "compute", chain.initial_delay)
        for operation, (comm, compute) in enumerate(zip(chain.comm, chain.compute, strict=True)):
            flow_id = builder.add(
                f"c{chain_index}_flow{operation}",
                "comm",
                comm,
                () if previous is None else (previous,),
            )
            flow_ids[chain_index, operation] = flow_id
            previous = builder.add(
                f"c{chain_index}_compute{operation}",
                "compute",
                compute,
                (flow_id,),
            )
    return builder.finish(), flow_ids


@dataclass(frozen=True)
class ParallelChainInstance:
    """A DAG partitioned into independent, strictly alternating paths.

    The representation preserves task identities and does not normalize or
    merge user input.  A singleton task is a valid (trivially alternating)
    chain.  Communication work must be positive; compute duration may be zero.
    """

    dag: DAG
    chains: tuple[tuple[str, ...], ...]

    @property
    def task_to_chain_position(self) -> dict[str, tuple[int, int]]:
        return {
            task_id: (chain_index, position)
            for chain_index, chain in enumerate(self.chains)
            for position, task_id in enumerate(chain)
        }


def parse_parallel_chain(dag: DAG) -> ParallelChainInstance:
    """Validate and return the strict Stage 1 representation.

    Path-shaped but non-alternating input is rejected instead of being
    silently normalized.  Forks, joins, cycles, and cross-chain dependencies
    are rejected by the same traversal.
    """

    errors = dag.validate()
    if errors:
        raise ValueError(f"invalid benchmark DAG {dag.name}: {errors}")
    tasks = dag.task_map()
    children: dict[str, list[str]] = {task_id: [] for task_id in tasks}
    for task in dag.tasks:
        if task.kind == "comm" and task.duration <= 0:
            raise ValueError(f"parallel-chain communication {task.task_id} must have positive work")
        for parent in task.deps:
            children[parent].append(task.task_id)

    degree_offenders = sorted(
        task.task_id for task in dag.tasks if len(task.deps) > 1 or len(children[task.task_id]) > 1
    )
    if degree_offenders:
        raise ValueError(f"parallel-chain DAG contains fork/join nodes: {degree_offenders}")

    roots = sorted(task.task_id for task in dag.tasks if not task.deps)
    visited: set[str] = set()
    chains: list[tuple[str, ...]] = []
    for root in roots:
        chain: list[str] = []
        current = root
        while True:
            if current in visited:
                raise ValueError(f"parallel-chain components merge at {current}")
            visited.add(current)
            chain.append(current)
            next_items = children[current]
            if not next_items:
                break
            child = next_items[0]
            if tasks[current].kind == tasks[child].kind:
                raise ValueError(
                    "parallel-chain tasks must strictly alternate compute and "
                    f"communication: {current} -> {child}"
                )
            current = child
        chains.append(tuple(chain))

    if visited != set(tasks):
        missing = sorted(set(tasks) - visited)
        raise ValueError(f"parallel-chain graph is not a root-partitioned path set: {missing}")
    return ParallelChainInstance(dag, tuple(chains))
