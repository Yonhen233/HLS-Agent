"""Enforce repository-wide Python documentation coverage.

The checks keep module and callable documentation from regressing after this
readability pass. They intentionally inspect project source, developer scripts,
and tests because all three are part of the interview-facing repository.
"""

from __future__ import annotations

import ast
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOTS = ("src", "scripts", "tests")


def _python_files() -> list[Path]:
    """Collect the Python files governed by the documentation policy.

    Returns:
        Sorted source, script, and test paths from the current repository.
    """

    files: list[Path] = []
    for root_name in PYTHON_ROOTS:
        files.extend((REPOSITORY_ROOT / root_name).rglob("*.py"))
    return sorted(files)


def test_every_python_module_has_a_docstring() -> None:
    """Require every governed Python file to explain its module-level role."""

    missing: list[str] = []
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if ast.get_docstring(tree) is None:
            missing.append(str(path.relative_to(REPOSITORY_ROOT)))
    assert not missing, f"Modules without docstrings: {missing}"


def test_every_class_and_function_has_a_docstring() -> None:
    """Require classes, functions, async functions, and methods to be documented."""

    missing: list[str] = []
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if ast.get_docstring(node) is None:
                relative = path.relative_to(REPOSITORY_ROOT)
                missing.append(f"{relative}:{node.lineno}:{node.name}")
    assert not missing, f"Callables without docstrings: {missing}"
