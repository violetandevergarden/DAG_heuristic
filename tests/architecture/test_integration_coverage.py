"""Guard that the optional integration suite is really collected and counted.

A silent ``collect_ignore_glob`` previously turned a missing integration
directory into an ordinary all-green run.  This test turns that failure mode
into an explicit, countable skip and verifies the expected test inventory when
the dependencies are present.
"""

from __future__ import annotations

import importlib
import importlib.util
import inspect

import pytest


EXPECTED_INTEGRATION_TESTS = {
    "tests.integration.test_simai_export": 2,
    "tests.integration.test_repetition_export": 2,
    "tests.integration.test_simai_semantics_e2e": 5,
}


def test_integration_suite_is_present_and_collectable() -> None:
    if importlib.util.find_spec("jsonschema") is None:
        pytest.skip("integration coverage not certified: jsonschema not installed")

    conftest = importlib.import_module("tests.integration.conftest")
    missing = conftest.integration_dependencies_missing()
    assert missing == [], f"integration dependencies missing: {missing}"

    for module_name, minimum in EXPECTED_INTEGRATION_TESTS.items():
        module = importlib.import_module(module_name)
        found = sum(
            name.startswith("test_") and callable(value)
            for name, value in vars(module).items()
            if inspect.isfunction(value)
        )
        assert found >= minimum, (
            f"{module_name} exposes {found} test functions; expected at least {minimum}. "
            "The integration directory may have disappeared or been renamed."
        )
