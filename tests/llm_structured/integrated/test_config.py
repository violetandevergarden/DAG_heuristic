from __future__ import annotations

import pytest

from llm_structured.preemptive.integrated import IntegratedConfig, integrated_r_exp, integrated_v0


def test_config_rejects_non_diagnostic_barrier_and_single_packing() -> None:
    with pytest.raises(ValueError):
        IntegratedConfig(name="bad", barrier_mode="independent")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        IntegratedConfig(name="bad", resource_mode="single", packing_mode="bounded_candidate")


def test_disabled_search_cannot_hide_reserved_work() -> None:
    with pytest.raises(ValueError):
        IntegratedConfig(name="bad", max_expansions=1)
    assert integrated_v0("single").rollout_mode == "off"
    assert integrated_r_exp().evaluation_steps == 2
