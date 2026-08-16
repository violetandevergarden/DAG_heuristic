"""Pure generators for random and adversarial benchmark scenarios."""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import replace
from itertools import pairwise

from core.dag import BenchmarkDAG, BenchTask, _Builder, topological_order
from core.resource import MultiResourceInstance
from single_channel.parallel_chain.model import ParallelChain, to_benchmark_dag


def random_parallel_chains(
    rng: random.Random,
    *,
    min_chains: int = 2,
    max_chains: int = 5,
    max_operations: int = 3,
    max_comm: int = 4,
    max_delay: int = 6,
) -> tuple[ParallelChain, ...]:
    return tuple(
        ParallelChain(
            tuple(rng.randint(1, max_comm) for _ in range(operations)),
            tuple(rng.randint(0, max_delay) for _ in range(operations)),
        )
        for operations in (
            rng.randint(1, max_operations) for _ in range(rng.randint(min_chains, max_chains))
        )
    )


def tight_optional_wait_family(magnitude: int) -> tuple[ParallelChain, ...]:
    return (
        ParallelChain((magnitude,), (0,)),
        ParallelChain((1,), (magnitude,), initial_delay=1),
    )


def scaled_five_four_family(scale: int) -> tuple[ParallelChain, ...]:
    return (
        ParallelChain((2 * scale, 2 * scale), (3 * scale + 1, 0)),
        ParallelChain((scale, 3 * scale), (2 * scale, 0)),
    )


def fixed_beam_counterexample() -> tuple[ParallelChain, ...]:
    return (
        ParallelChain((6,), (6,)),
        ParallelChain((8,), (1,)),
        ParallelChain((1, 6, 4, 1), (8, 12, 9, 3)),
        ParallelChain((3,), (3,)),
        ParallelChain((2, 1), (2, 9)),
        ParallelChain((2, 1, 8), (1, 7, 8)),
    )


def rollout_depth_counterexample() -> tuple[ParallelChain, ...]:
    """Fixed case where depth two beats both rollout2 and wider rollout4.

    Discovered as index 100 of a fixed-seed search (seed 26081601,
    max_chains=6, max_operations=4, max_comm=8, max_delay=12).  Compact Exact
    gives makespan 47; rollout2, rollout4, and rollout2-depth2 give 49, 48,
    and 47 respectively.
    """

    return (
        ParallelChain((7, 4, 6), (7, 11, 2)),
        ParallelChain((1, 4, 3, 7), (0, 4, 10, 1)),
        ParallelChain((2, 4, 5, 2), (10, 5, 9, 6)),
    )


def classic_parallel_counterexamples() -> list[tuple[str, tuple[ParallelChain, ...]]]:
    """Small hand-written chain cases used in the original experiments."""
    return [
        (
            "large_flow_vs_long_tail",
            (
                ParallelChain((1, 1), (8, 0)),
                ParallelChain((8,), (0,)),
            ),
        ),
        (
            "longest_tail_counterexample",
            (
                ParallelChain((2, 1), (3, 1)),
                ParallelChain((1, 2), (2, 1)),
            ),
        ),
        (
            "lrpt_double_count",
            (
                ParallelChain((3, 1), (1, 5)),
                ParallelChain((1, 2), (4, 0)),
                ParallelChain((2,), (2,)),
            ),
        ),
    ]


def historical_wait_hard_chains() -> list[tuple[str, tuple[ParallelChain, ...]]]:
    """Exactly reproduce the seven fixed-seed WAIT-hard chains from R1."""
    wanted = {14, 52, 60, 70, 77, 86, 98}
    rng = random.Random(260813)
    result = []
    for index in range(max(wanted) + 1):
        chains = random_parallel_chains(rng)
        if index in wanted:
            result.append((f"random_chain_{index}", chains))
    return result


def random_join_dag(rng: random.Random, index: int) -> BenchmarkDAG:
    builder = _Builder(
        f"random_join_{index}",
        "random_general",
        "Random small DAG with branch releases, second flows and a final join.",
    )
    endpoints: list[str] = []
    branches = rng.randint(2, 5)
    for branch in range(branches):
        release = builder.add(f"r{branch}", "compute", rng.randint(0, 3), role="release")
        first = builder.add(
            f"c{branch}_0",
            "comm",
            rng.randint(1, 4),
            (release,),
            role=rng.choice(("pp", "tp", "dp")),
        )
        compute = builder.add(
            f"x{branch}_0",
            "compute",
            rng.randint(1, 6),
            (first,),
            role="backbone" if branch == 0 else "side",
        )
        if rng.random() < 0.7:
            endpoints.append(
                builder.add(
                    f"c{branch}_1",
                    "comm",
                    rng.randint(1, 4),
                    (compute,),
                    role=rng.choice(("pp", "dp")),
                )
            )
        else:
            endpoints.append(compute)
    if branches >= 3 and rng.random() < 0.6:
        nested = builder.add(
            "nested_join",
            "compute",
            rng.randint(1, 3),
            tuple(endpoints[:2]),
            role="join",
        )
        endpoints = [nested, *endpoints[2:]]
    join = builder.add(
        "optimizer_join",
        "compute",
        rng.randint(1, 3),
        tuple(endpoints),
        role="optimizer",
    )
    if rng.random() < 0.7:
        final = builder.add("final_comm", "comm", rng.randint(1, 3), (join,), role="pp")
        builder.add("sink", "compute", rng.randint(1, 4), (final,), role="sink")
    return builder.finish(branches=branches)


def last_blocker_overboost_counterexample() -> BenchmarkDAG:
    builder = _Builder(
        "last_blocker_overboost",
        "adversarial",
        "Directly adding join last-blocker urgency over-prioritizes a long flow.",
    )
    r0 = builder.add("r0", "compute", 3)
    c00 = builder.add("c0_0", "comm", 3, (r0,))
    x00 = builder.add("x0_0", "compute", 4, (c00,))
    c01 = builder.add("c0_1", "comm", 1, (x00,))
    r1 = builder.add("r1", "compute", 1)
    c10 = builder.add("c1_0", "comm", 3, (r1,))
    x10 = builder.add("x1_0", "compute", 1, (c10,))
    r2 = builder.add("r2", "compute", 2)
    c20 = builder.add("c2_0", "comm", 4, (r2,))
    x20 = builder.add("x2_0", "compute", 2, (c20,))
    c21 = builder.add("c2_1", "comm", 1, (x20,))
    nested = builder.add("nested_join", "compute", 2, (c01, x10), role="join")
    optimizer = builder.add("optimizer_join", "compute", 1, (nested, c21), role="optimizer")
    final = builder.add("final_comm", "comm", 1, (optimizer,))
    builder.add("sink", "compute", 4, (final,))
    return builder.finish()


def historical_random_join_counterexamples() -> list[BenchmarkDAG]:
    """Reproduce ordering/WAIT/Beam failures recorded by the R1-R3 studies."""
    wanted = {23, 30, 40, 46, 60}
    rng = random.Random(260817)
    result = []
    for index in range(max(wanted) + 1):
        dag = random_join_dag(rng, index)
        if index in wanted:
            result.append(replace(dag, category="adversarial"))
    return result


def combined_chain_probes() -> list[BenchmarkDAG]:
    wanted = {14, 70, 86}
    rng = random.Random(260813)
    result = []
    for index in range(max(wanted) + 1):
        chains = random_parallel_chains(rng)
        if index in wanted:
            dag, _flow_ids = to_benchmark_dag(chains)
            result.append(replace(dag, name=f"combined_chain_{index}", category="combined_probe"))
    return result


def multi_resource_motifs() -> list[MultiResourceInstance]:
    result = []
    builder = _Builder("disjoint_routes_np", "r4_motif", "disjoint overlap")
    left = builder.add("left", "comm", 4)
    right = builder.add("right", "comm", 4)
    builder.add("left_tail", "compute", 3, (left,))
    builder.add("right_tail", "compute", 3, (right,))
    result.append(
        MultiResourceInstance(
            builder.finish(), {"left": frozenset({"r0"}), "right": frozenset({"r1"})}
        )
    )

    builder = _Builder("shared_route_np", "r4_motif", "shared bottleneck")
    left = builder.add("left", "comm", 4)
    right = builder.add("right", "comm", 4)
    builder.add("left_tail", "compute", 3, (left,))
    builder.add("right_tail", "compute", 3, (right,))
    result.append(
        MultiResourceInstance(
            builder.finish(), {"left": frozenset({"shared"}), "right": frozenset({"shared"})}
        )
    )

    builder = _Builder(
        "nonmaximal_start_np", "r4_motif", "Non-maximal start protects a future critical flow."
    )
    release = builder.add("release_c", "compute", 1)
    builder.add("a", "comm", 4)
    builder.add("b", "comm", 5)
    c = builder.add("c", "comm", 1, (release,))
    builder.add("c_tail", "compute", 6, (c,))
    result.append(
        MultiResourceInstance(
            builder.finish(),
            {"a": frozenset({"r0"}), "b": frozenset({"r1"}), "c": frozenset({"r1"})},
        )
    )

    builder = _Builder(
        "active_reservation_np", "r4_motif", "An active flow keeps its route reserved."
    )
    builder.add("a", "comm", 4)
    b = builder.add("b", "comm", 1)
    builder.add("c", "comm", 1, (b,))
    result.append(
        MultiResourceInstance(
            builder.finish(),
            {"a": frozenset({"shared"}), "b": frozenset({"other"}), "c": frozenset({"shared"})},
        )
    )
    return result


def manual_route_cases() -> list[MultiResourceInstance]:
    """Small fixed-route snapshots derived from three transparent topologies."""
    routes = {
        "manual_route_single_switch_np": (
            (0, 8, 1),
            (2, 8, 3),
            (4, 8, 5),
            (6, 8, 7),
        ),
        "manual_route_two_rack_np": (
            (0, 8, 9, 4),
            (1, 8, 9, 5),
            (2, 8, 3),
            (6, 9, 7),
        ),
        "manual_route_four_rack_core_np": (
            (0, 8, 12, 10, 4),
            (1, 8, 12, 10, 5),
            (2, 9, 12, 11, 6),
            (3, 9, 12, 11, 7),
        ),
    }
    result = []
    for name, paths in routes.items():
        builder = _Builder(
            name,
            "real",
            "Small route instance produced through TopologyLoader-compatible BFS.",
        )
        resources = {}
        for index, (path, flow_duration, tail_duration) in enumerate(
            zip(paths, (4, 3, 2, 1), (5, 4, 3, 2), strict=True),
            start=1,
        ):
            flow = builder.add(f"f{index}", "comm", flow_duration)
            builder.add(f"tail{index}", "compute", tail_duration, (flow,))
            resource_set = {
                *pairwise(path),
                ("nic_tx", path[0]),
                ("nic_rx", path[-1]),
            }
            resources[flow] = frozenset(resource_set)
        result.append(MultiResourceInstance(builder.finish(), resources))
    return result


def random_multi_resource_instance(rng: random.Random, index: int) -> MultiResourceInstance:
    dag = random_join_dag(rng, index)
    resources = {}
    fabrics = ("pp-fabric", "dp-fabric", "tp-fabric")
    for position, task in enumerate(task for task in dag.tasks if task.kind == "comm"):
        role_index = {"pp": 0, "dp": 1, "tp": 2}.get(task.role, position % 3)
        values = {f"nic-{rng.randrange(3)}", fabrics[role_index]}
        if rng.random() < 0.35:
            values.add("shared-uplink")
        resources[task.task_id] = frozenset(values)
    return MultiResourceInstance(dag, resources)


def _chain_dag(
    name: str,
    chains: tuple[tuple[tuple[int, ...], tuple[int, ...]], ...],
    description: str,
) -> BenchmarkDAG:
    builder = _Builder(name, "adversarial", description)
    for chain_index, (comms, computes) in enumerate(chains):
        previous: str | None = None
        for operation, (comm, compute) in enumerate(zip(comms, computes, strict=True)):
            flow = builder.add(
                f"c{chain_index}_flow{operation}",
                "comm",
                comm,
                () if previous is None else (previous,),
                role="chain_flow",
            )
            previous = builder.add(
                f"c{chain_index}_compute{operation}",
                "compute",
                compute,
                (flow,),
                role="chain_compute",
            )
    return builder.finish(chains=len(chains))


def complex_adversarial_cases() -> list[BenchmarkDAG]:
    """Hand-written fork/join and priority failures used by the fixed suite."""
    result = [
        _chain_dag(
            "large_flow_vs_long_tail",
            (((1, 1), (8, 0)), ((8,), (0,))),
            "A short flow unlocks a long compute tail while a large flow competes.",
        ),
        _chain_dag(
            "longest_tail_counterexample",
            (((2, 1), (3, 1)), ((1, 2), (2, 1))),
            "Small counterexample where static longest-tail is not optimal.",
        ),
        _chain_dag(
            "lrpt_double_count",
            (((3, 1), (1, 5)), ((1, 2), (4, 0)), ((2,), (2,))),
            "Large current flow can be counted twice by LRPT-style scores.",
        ),
    ]

    builder = _Builder(
        "join_false_critical",
        "adversarial",
        "Two apparently critical branches meet a join; only the last arrival gates it.",
    )
    a = builder.add("a_flow", "comm", 2, role="join_input")
    a_tail = builder.add("a_compute", "compute", 5, (a,))
    b = builder.add("b_flow", "comm", 3, role="join_input")
    join = builder.add("join", "compute", 1, (a_tail, b), role="join")
    builder.add("sink", "compute", 2, (join,))
    result.append(builder.finish())

    builder = _Builder(
        "fork_multi_unlock",
        "adversarial",
        "One small flow releases several compute branches before a final join.",
    )
    root = builder.add("fork_flow", "comm", 1, role="fork")
    branches = [builder.add(f"branch{i}", "compute", 3 + i, (root,)) for i in range(3)]
    side = builder.add("large_side_flow", "comm", 6)
    builder.add("join", "compute", 1, (*branches, side), role="join")
    result.append(builder.finish())

    builder = _Builder(
        "deferred_w_competition",
        "adversarial",
        "Several W/DP side jobs compete with a PP flow that unlocks backbone compute.",
    )
    pp = builder.add("pp", "comm", 1, role="pp")
    backbone = builder.add("backbone", "compute", 7, (pp,), role="backbone")
    dps = []
    for index, duration in enumerate((2, 3, 2)):
        w = builder.add(f"w{index}", "compute", 1, role="w")
        dps.append(builder.add(f"dp{index}", "comm", duration, (w,), role="dp"))
    builder.add("optimizer", "compute", 1, (backbone, *dps), role="optimizer")
    result.append(builder.finish())

    builder = _Builder(
        "optimizer_dp_burst",
        "adversarial",
        "A concentrated set of DP flows forms the optimizer barrier.",
    )
    dps = []
    for index in range(4):
        w = builder.add(f"w{index}", "compute", index % 2 + 1, role="w")
        dps.append(builder.add(f"dp{index}", "comm", 2, (w,), role="dp"))
    builder.add("optimizer", "compute", 2, dps, role="optimizer")
    result.append(builder.finish())
    return result


def _pp_wave(direction: str, stages: int = 3, microbatches: int = 2) -> BenchmarkDAG:
    builder = _Builder(
        f"pp_{direction}_wave",
        "llm_motif",
        f"Parameterized PP {direction} wave.",
    )
    stage_order = range(stages) if direction == "forward" else range(stages - 1, -1, -1)
    for microbatch in range(microbatches):
        previous = None
        for position, stage in enumerate(stage_order):
            compute = builder.add(
                f"mb{microbatch}_s{stage}_{direction}",
                "compute",
                2,
                () if previous is None else (previous,),
                role=direction,
            )
            if position + 1 < stages:
                previous = builder.add(
                    f"mb{microbatch}_s{stage}_{direction}_pp",
                    "comm",
                    1,
                    (compute,),
                    role="pp",
                )
            else:
                previous = compute
    return builder.finish(stages=stages, microbatches=microbatches)


def _one_f_one_b(stages: int = 2, microbatches: int = 3) -> BenchmarkDAG:
    builder = _Builder("one_f_one_b", "llm_motif", "Small 1F1B wave.")
    forward: dict[tuple[int, int], str] = {}
    backward: dict[tuple[int, int], str] = {}
    for mb in range(microbatches):
        for stage in range(stages):
            deps = ()
            if stage:
                deps = (
                    builder.add(
                        f"fpp_{mb}_{stage - 1}",
                        "comm",
                        1,
                        (forward[mb, stage - 1],),
                        role="pp",
                    ),
                )
            forward[mb, stage] = builder.add(f"f_{mb}_{stage}", "compute", 2, deps, role="f")
        for stage in reversed(range(stages)):
            deps = (forward[mb, stage],)
            if stage + 1 < stages:
                deps = (
                    builder.add(
                        f"bpp_{mb}_{stage + 1}",
                        "comm",
                        1,
                        (backward[mb, stage + 1],),
                        role="pp",
                    ),
                )
            backward[mb, stage] = builder.add(
                f"b_{mb}_{stage}",
                "compute",
                3,
                deps,
                role="b",
            )
            builder.add(f"w_{mb}_{stage}", "compute", 1, (backward[mb, stage],), role="w")
    topo = topological_order(builder.finish())
    rank = {task_id: index for index, task_id in enumerate(topo)}
    extra: dict[str, list[str]] = defaultdict(list)
    for stage in range(stages):
        sequence = [forward[mb, stage] for mb in range(min(stages - stage, microbatches))]
        sequence += [
            item for mb in range(microbatches) for item in (forward[mb, stage], backward[mb, stage])
        ]
        unique = list(dict.fromkeys(sequence))
        for left, right in pairwise(unique):
            if rank[left] < rank[right]:
                extra[right].append(left)
    builder.tasks = [
        BenchTask(
            task.task_id,
            task.kind,
            task.duration,
            tuple(dict.fromkeys((*task.deps, *extra[task.task_id]))),
            task.role,
            task.cut,
        )
        for task in builder.tasks
    ]
    return builder.finish(stages=stages, microbatches=microbatches)


def _zb_fork(microbatches: int = 3) -> BenchmarkDAG:
    builder = _Builder("zb_bw_fork", "llm_motif", "B and W fork from grad-output readiness.")
    weights = []
    previous_b = None
    for mb in reversed(range(microbatches)):
        fwd = builder.add(f"f{mb}", "compute", 2, role="f")
        grad = builder.add(
            f"grad{mb}",
            "comm",
            1,
            () if previous_b is None else (previous_b,),
            role="pp_grad",
        )
        bwd = builder.add(f"b{mb}", "compute", 3, (fwd, grad), role="b")
        weights.append(builder.add(f"w{mb}", "compute", 2, (fwd, grad), role="w"))
        previous_b = bwd
    builder.add("optimizer", "compute", 1, weights, role="optimizer")
    return builder.finish(microbatches=microbatches)


def _w_dp_optimizer(buckets: int = 3) -> BenchmarkDAG:
    builder = _Builder("w_dp_optimizer_join", "llm_motif", "W buckets feed one optimizer join.")
    dps = []
    for bucket in range(buckets):
        w = builder.add(f"w{bucket}", "compute", bucket + 1, role="w")
        dps.append(builder.add(f"dp{bucket}", "comm", 2, (w,), role="dp"))
    builder.add("optimizer", "compute", 2, dps, role="optimizer")
    return builder.finish(buckets=buckets)


def _tp_plus_pp(tp_flows: int = 3) -> BenchmarkDAG:
    builder = _Builder("tp_collective_plus_pp", "llm_motif", "TP fan-out/fan-in then PP send.")
    fwd = builder.add("f", "compute", 2, role="f")
    tp = [builder.add(f"tp{i}", "comm", 1, (fwd,), role="tp") for i in range(tp_flows)]
    join = builder.add("tp_complete", "compute", 1, tp, role="collective_join")
    pp = builder.add("pp", "comm", 2, (join,), role="pp")
    builder.add("next_stage_f", "compute", 3, (pp,), role="f")
    return builder.finish(tp_flows=tp_flows)


def _warmup_steady_cooldown(microbatches: int = 4) -> BenchmarkDAG:
    builder = _Builder("warmup_steady_cooldown", "llm_motif", "One rank's F/B/W phases.")
    sequence = []
    for mb in range(2):
        sequence.append(builder.add(f"f{mb}", "compute", 2, role="warmup_f"))
    for mb in range(2, microbatches):
        sequence.extend(
            (
                builder.add(f"f{mb}", "compute", 2, role="steady_f"),
                builder.add(f"b{mb - 2}", "compute", 3, role="steady_b"),
                builder.add(f"w{mb - 2}", "compute", 1, role="steady_w"),
            )
        )
    for mb in range(max(0, microbatches - 2), microbatches):
        sequence.extend(
            (
                builder.add(f"b{mb}", "compute", 3, role="cooldown_b"),
                builder.add(f"w{mb}", "compute", 1, role="cooldown_w"),
            )
        )
    previous = None
    rewritten = []
    by_id = {task.task_id: task for task in builder.tasks}
    for task_id in sequence:
        task = by_id[task_id]
        deps = task.deps if previous is None else (*task.deps, previous)
        rewritten.append(
            BenchTask(
                task.task_id,
                task.kind,
                task.duration,
                tuple(dict.fromkeys(deps)),
                task.role,
                task.cut,
            )
        )
        previous = task_id
    builder.tasks = rewritten
    for mb in range(microbatches):
        builder.add(f"pp_side{mb}", "comm", 1, role="pp")
    return builder.finish(microbatches=microbatches)


def llm_motif_cases() -> list[BenchmarkDAG]:
    """Small readable reductions of recurring LLM training structures."""
    return [
        _pp_wave("forward"),
        _pp_wave("backward"),
        _one_f_one_b(),
        _zb_fork(),
        _w_dp_optimizer(),
        _tp_plus_pp(),
        _warmup_steady_cooldown(),
    ]
