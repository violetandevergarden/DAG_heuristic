from __future__ import annotations

from llm_structured.integrated.accounting import SharedBudget


def test_shared_budget_reserves_before_limit() -> None:
    budget = SharedBudget(2, 1, 1, 0.0, None)
    assert budget.reserve("operation", 2)
    assert not budget.reserve("operation")
    assert budget.operations == 2
    assert budget.reserve("completion")
    assert not budget.reserve("completion")
    assert budget.completion_calls == 1
