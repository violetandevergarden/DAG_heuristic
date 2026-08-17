from __future__ import annotations

from benchmark_generate.llm.catalog import canonical_routed_specs, scan_aicb_catalog
from benchmark_generate.llm_structure import AICB_ROOT, TOPOLOGY_CAPACITIES


def test_aicb_catalog_covers_all_parseable_real_inputs() -> None:
    sources, quarantine = scan_aicb_catalog(AICB_ROOT)
    assert len(sources) >= 900
    assert not quarantine
    assert {source.model for source in sources} >= {
        "Mixtral_8x7B",
        "gpt_7B",
        "gpt_13B",
        "gpt_22B",
        "gpt_175B",
        "llama_405B",
    }


def test_canonical_real_suite_covers_models_and_topology_tiers() -> None:
    sources, _ = scan_aicb_catalog(AICB_ROOT)
    specs = canonical_routed_specs(sources, TOPOLOGY_CAPACITIES)
    assert {spec["model"] for spec in specs} == {source.model for source in sources}
    assert {spec["topology"] for spec in specs} == set(TOPOLOGY_CAPACITIES)
    assert any(spec.get("dp", 1) > 1 for spec in specs)
    assert all(
        spec["tp"] * spec["pp"] * spec.get("dp", 1)
        <= TOPOLOGY_CAPACITIES[spec["topology"]]
        for spec in specs
    )
