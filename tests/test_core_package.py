import ast
import importlib.util
import sys
from pathlib import Path

import pytest


CORE_ROOT = Path(__file__).resolve().parents[1] / "core"
FORBIDDEN_IMPORT_ROOTS = {
    "backend",
    "career_bot",
    "uma_api",
    "uma_data",
    "integrations",
    "scripts",
}


def _imported_modules(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from ((alias.name, node.lineno) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.module, node.lineno
        elif (
            isinstance(node, ast.Call)
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
            and (
                (isinstance(node.func, ast.Name) and node.func.id == "__import__")
                or (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr == "import_module"
                )
            )
        ):
            yield node.args[0].value, node.lineno


def test_core_package_remains_a_leaf():
    violations = []
    for path in sorted(CORE_ROOT.glob("*.py")):
        for module, line in _imported_modules(path):
            if module.split(".", 1)[0] in FORBIDDEN_IMPORT_ROOTS:
                violations.append(f"{path.name}:{line}: {module}")

    assert not violations, "core must remain a leaf package:\n" + "\n".join(violations)


def test_core_init_is_empty():
    assert (CORE_ROOT / "__init__.py").read_bytes() == b""


@pytest.mark.parametrize("module_name", ("settings", "runtime_paths", "operational_time"))
def test_old_top_level_module_is_not_importable(module_name):
    assert module_name not in sys.modules
    assert importlib.util.find_spec(module_name) is None
