from __future__ import annotations

from benchmark import Benchmark, SchedulingSemantics, Task
from core.dag import BenchmarkDAG, BenchTask
from llm_structured.perturb import perturb_durations
from llm_structured.signatures import classify_repetition_evidence


def test_duration_perturbation_preserves_scale_and_zero_markers() -> None:
    dag = BenchmarkDAG(
        "jitter",
        "synthetic",
        (
            BenchTask("compute", "compute", 10),
            BenchTask("marker", "compute", 0),
        ),
    )
    perturbed = perturb_durations(dag, 0.0, seed=7)
    assert [task.duration for task in perturbed.tasks] == [10, 0]


def test_feature_label_difference_blocks_labelled_twin_certificate() -> None:
    benchmark = Benchmark(
        "label_guard",
        "single_channel",
        "complex_chain",
        "real",
        (
            Task("a", "compute", 1, metadata={"phase": "forward", "task_role": "F"}),
            Task("b", "compute", 1, metadata={"phase": "backward", "task_role": "B"}),
        ),
        (),
        semantics=SchedulingSemantics(
            preemption="communication_resume",
            decision_epoch="task_event",
            optional_idle=False,
            resource_model="exclusive_fixed_set",
        ),
        schema_version="2.0",
    )
    evidence = classify_repetition_evidence(benchmark)
    assert evidence.highest_certified_level == "descriptive_motif"

