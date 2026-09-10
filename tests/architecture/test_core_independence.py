from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_IMPORT_ROOTS = ("src", "DAG_heuristic", "experiments", "benchmark_generate")


def _is_forbidden_import(name: str) -> bool:
    return any(name == root or name.startswith(f"{root}.") for root in FORBIDDEN_IMPORT_ROOTS)


def test_core_has_no_simai_or_legacy_package_imports() -> None:
    violations = []
    for path in (ROOT / "src").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module
                and _is_forbidden_import(node.module)
            ):
                violations.append(f"{path.relative_to(ROOT)}:{node.lineno}: {node.module}")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if _is_forbidden_import(alias.name):
                        violations.append(f"{path.relative_to(ROOT)}:{node.lineno}: {alias.name}")
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Attribute)
                and node.func.value.attr == "path"
                and node.func.attr == "insert"
            ):
                violations.append(f"{path.relative_to(ROOT)}:{node.lineno}: sys.path.insert")
    assert violations == []
