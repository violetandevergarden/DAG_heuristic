from core.dag import DAG, Task
from core.execution.preemptive import PreeMultiModel
from llm_structured.preemptive.packing_features import cheap_packing_features


def test_packing_features_report_conflict_and_llm_role_diversity():
    dag = DAG('features', (Task('tp', 'comm', 1, labels=(('task_role', 'TP'),)), Task('dp', 'comm', 1, labels=(('task_role', 'DP'),))), context=(('category', 'test'),))
    model = PreeMultiModel(dag, {
        "tp": frozenset({"r0"}), "dp": frozenset({"r0", "r1"})
    })
    features = cheap_packing_features(model, model.initial_state())
    assert features.eligible_count == 2
    assert features.conflict_edges == 1
    assert features.maximum_footprint == 2
    assert features.llm_role_diversity == 2
