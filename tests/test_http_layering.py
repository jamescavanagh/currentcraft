"""AST-based architectural boundary tests (including function-local imports)."""

from __future__ import annotations

import ast
from pathlib import Path
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
APP_ROOT = SRC_ROOT / "app"


def _resolve_relative_import(py_file: Path, node: ast.ImportFrom) -> str:
    if node.level == 0:
        return node.module or ""
    rel_parts = list(py_file.relative_to(SRC_ROOT).with_suffix("").parts)
    if rel_parts and rel_parts[-1] == "__init__":
        rel_parts = rel_parts[:-1]
    ascend = node.level - 1
    base_parts = rel_parts[: max(0, len(rel_parts) - ascend)]
    if node.module:
        base_parts.extend(node.module.split("."))
    return ".".join(base_parts)


def _collect_all_imports(py_file: Path) -> list[str]:
    """Walk full AST (including inside functions/methods) and return imported module paths."""
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            resolved = _resolve_relative_import(py_file, node)
            if resolved:
                modules.append(resolved)
            for alias in node.names:
                if resolved:
                    modules.append(f"{resolved}.{alias.name}")
                else:
                    modules.append(alias.name)
    return modules


class TestHttpLayering(unittest.TestCase):
    def test_web_framework_imports_exist_only_under_interfaces(self) -> None:
        web_prefixes = ("fastapi", "starlette", "uvicorn")
        for py_file in APP_ROOT.rglob("*.py"):
            rel = py_file.relative_to(APP_ROOT)
            if rel.parts[0] == "interfaces":
                continue
            for mod in _collect_all_imports(py_file):
                self.assertFalse(
                    mod == "fastapi"
                    or mod == "starlette"
                    or mod == "uvicorn"
                    or mod.startswith(tuple(f"{p}." for p in web_prefixes)),
                    f"{rel} must not import web framework module '{mod}'",
                )

    def test_application_and_domain_never_import_interfaces(self) -> None:
        for layer in ("domain", "application"):
            layer_dir = APP_ROOT / layer
            if not layer_dir.is_dir():
                continue
            for py_file in layer_dir.rglob("*.py"):
                rel = py_file.relative_to(APP_ROOT)
                for mod in _collect_all_imports(py_file):
                    self.assertFalse(
                        mod == "app.interfaces"
                        or mod.startswith("app.interfaces.")
                        or mod == "interfaces"
                        or mod.startswith("interfaces."),
                        f"{rel} must not import interfaces module '{mod}'",
                    )

    def test_only_http_wiring_imports_infrastructure_within_interfaces(self) -> None:
        interfaces_dir = APP_ROOT / "interfaces"
        wiring_rel = Path("interfaces/http/wiring.py")
        for py_file in interfaces_dir.rglob("*.py"):
            rel = py_file.relative_to(APP_ROOT)
            if rel == wiring_rel:
                continue
            for mod in _collect_all_imports(py_file):
                self.assertFalse(
                    mod == "app.infrastructure"
                    or mod.startswith("app.infrastructure.")
                    or mod == "infrastructure"
                    or mod.startswith("infrastructure."),
                    f"{rel} must not import infrastructure module '{mod}'",
                )

    def test_no_numpy_or_torch_imports_in_interfaces(self) -> None:
        interfaces_dir = APP_ROOT / "interfaces"
        for py_file in interfaces_dir.rglob("*.py"):
            rel = py_file.relative_to(APP_ROOT)
            for mod in _collect_all_imports(py_file):
                self.assertFalse(
                    mod == "numpy"
                    or mod.startswith("numpy.")
                    or mod == "torch"
                    or mod.startswith("torch."),
                    f"{rel} must not import numerical/ML library '{mod}'",
                )
