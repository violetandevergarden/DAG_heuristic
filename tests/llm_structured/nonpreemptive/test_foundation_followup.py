import json
from pathlib import Path

from experiments.llm_structure.nonpreemptive.stage4_conversion_fidelity import coverage

ROOT = Path(__file__).resolve().parents[3]


def test_explicit_conversion_manifest_has_complete_declared_coverage():
    path = (
        ROOT
        / "experiments/llm_structure/nonpreemptive/manifests/stage4_foundation/conversion_cases.jsonl"
    )
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) >= 12
    assert coverage(rows)["complete"]
