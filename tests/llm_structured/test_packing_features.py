from core.dag import BenchmarkDAG, BenchTask
from core.execution.multi_resource import PreemptiveMultiResourceModel
from llm_structured.packing_features import cheap_packing_features


def test_packing_features_report_conflict_and_llm_role_diversity():
    dag = BenchmarkDAG("features", "test", (
        BenchTask("tp", "comm", 1, role="TP"),
        BenchTask("dp", "comm", 1, role="DP"),
    ))
    model = PreemptiveMultiResourceModel(dag, {
        "tp": frozenset({"r0"}), "dp": frozenset({"r0", "r1"})
    })
    features = cheap_packing_features(model, model.initial_state())
    assert features.eligible_count == 2
    assert features.conflict_edges == 1
    assert features.maximum_footprint == 2
    assert features.llm_role_diversity == 2
