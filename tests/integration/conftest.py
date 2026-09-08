"""Gate optional SimAI integration tests with explicit, auditable visibility.

When the optional dependencies (``jsonschema`` plus a SimAI checkout) are
missing, the integration directory is excluded from collection 鈥?but the
exclusion is now announced through a visible pytest warning and a dedicated
skip in ``tests/test_integration_coverage.py`` instead of silently showing up
as an ordinary all-green run.
"""

from __future__ import annotations

import os
import importlib.util
from pathlib import Path
import sys
import warnings


ROOT = Path(__file__).resolve().parents[2]
candidates = []
if configured := os.environ.get("SIMAI_FLOW_SCHEDULER_ROOT"):
    candidates.append(Path(configured))
candidates.extend(
    (
        ROOT / "third_party/simai-flow-scheduler",
        ROOT.parent / "simai-flow-scheduler",
    )
)


def integration_dependencies_missing() -> list[str]:
    missing = []
    if importlib.util.find_spec("jsonschema") is None:
        missing.append("jsonschema (pip install -e '.[integration]')")
    checkout = next(
        (
            candidate.resolve()
            for candidate in candidates
            if (candidate / "src/workload_format/schema.py").is_file()
        ),
        None,
    )
    if checkout is None:
        missing.append(
            "SimAI checkout (third_party/simai-flow-scheduler or SIMAI_FLOW_SCHEDULER_ROOT)"
        )
    else:
        # Match the converter bootstrap and verify the actual import contract.
        # A filesystem-only check used to collect the suite and fail later when
        # this repository's ``src`` namespace shadowed the SimAI package.
        sys.path.insert(0, str(checkout))
        try:
            if importlib.util.find_spec("src.static_analysis") is None:
                missing.append("SimAI Python package src.static_analysis")
        finally:
            sys.path.remove(str(checkout))
    return missing


_missing = integration_dependencies_missing()
if _missing:
    warnings.warn(
        "tests/integration excluded from collection; missing: "
        + "; ".join(_missing)
        + ". Integration coverage is therefore NOT certified by this run.",
        stacklevel=2,
    )
    collect_ignore_glob = ["test_*.py"]
