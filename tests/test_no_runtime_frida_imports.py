import ast
import os
from dataclasses import dataclass
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SOURCE_ROOTS = (
    "backend",
    "career_bot",
    "core",
    "uma_api",
    "uma_data",
    "integrations",
)
RUNTIME_ENTRY_FILES = ("main.py",)
ALLOWED_SCRIPT_MODULES = frozenset({"scripts.scrape_gametora_effects"})
_INDEX_EXCLUDED_TOP_LEVEL = {
    ".agents",
    ".claude",
    ".codegraph",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".venv",
    "frontend",
    "node_modules",
    "tests",
    "uma_runtime",
}


@dataclass(frozen=True, order=True)
class ImportReference:
    module: str
    line: int
    kind: str


@dataclass(frozen=True, order=True)
class ImportViolation:
    path: str
    line: int
    module: str
    reason: str

    def __str__(self):
        return f"{self.path}:{self.line}: {self.reason}: {self.module}"


def _module_name(project_root, path):
    relative = path.relative_to(project_root).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _runtime_source_paths(
    project_root,
    runtime_roots=RUNTIME_SOURCE_ROOTS,
    entry_files=RUNTIME_ENTRY_FILES,
):
    paths = set()
    state_root = (project_root / "uma_runtime").resolve(strict=False)
    for entry_file in entry_files:
        path = project_root / entry_file
        if path.is_file():
            paths.add(path)
    for source_root in runtime_roots:
        root = project_root / source_root
        if not root.is_dir():
            continue
        for path in root.rglob("*.py"):
            relative = path.relative_to(project_root)
            if relative.parts[:2] == ("integrations", "frida"):
                continue
            try:
                path.resolve(strict=False).relative_to(state_root)
            except ValueError:
                paths.add(path)
    return sorted(paths)


def _local_module_index(project_root):
    index = {}
    for directory, dirnames, filenames in os.walk(project_root):
        directory_path = Path(directory)
        relative = directory_path.relative_to(project_root)
        if not relative.parts:
            dirnames[:] = [
                name for name in dirnames
                if name not in _INDEX_EXCLUDED_TOP_LEVEL
            ]
        else:
            dirnames[:] = [name for name in dirnames if name != "__pycache__"]
        for filename in filenames:
            if not filename.endswith(".py"):
                continue
            path = directory_path / filename
            module = _module_name(project_root, path)
            if module:
                index[module] = path
    return index


def _package_name(module, path):
    if path.name == "__init__.py":
        return module
    return module.rpartition(".")[0]


def _resolve_from_base(node, module, path):
    if node.level == 0:
        return node.module or ""
    package_parts = _package_name(module, path).split(".")
    if package_parts == [""]:
        package_parts = []
    parents_to_drop = node.level - 1
    if parents_to_drop > len(package_parts):
        return node.module or ""
    prefix = package_parts[:len(package_parts) - parents_to_drop]
    if node.module:
        prefix.extend(node.module.split("."))
    return ".".join(prefix)


def _constant_string(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _constant_string(node.left)
        right = _constant_string(node.right)
        if left is not None and right is not None:
            return left + right
    return None


def _static_import_references(tree, module, path):
    references = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            references.extend(
                ImportReference(alias.name, node.lineno, "static import")
                for alias in node.names
            )
            continue
        if not isinstance(node, ast.ImportFrom):
            continue
        base = _resolve_from_base(node, module, path)
        if base == "scripts":
            for alias in node.names:
                imported = (
                    "scripts" if alias.name == "*"
                    else f"scripts.{alias.name}"
                )
                references.append(
                    ImportReference(imported, node.lineno, "static import")
                )
            continue
        if base:
            references.append(
                ImportReference(base, node.lineno, "static import")
            )
        if base == "integrations":
            for alias in node.names:
                if alias.name == "frida":
                    references.append(
                        ImportReference(
                            "integrations.frida", node.lineno, "static import",
                        )
                    )
    return references


def _dynamic_import_references(tree):
    importlib_modules = {"importlib"}
    import_module_functions = set()
    builtins_modules = {"builtins"}
    builtin_import_functions = {"__import__"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "importlib":
                    importlib_modules.add(alias.asname or alias.name)
                elif alias.name == "builtins":
                    builtins_modules.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module == "importlib":
                for alias in node.names:
                    if alias.name == "import_module":
                        import_module_functions.add(alias.asname or alias.name)
            elif node.module == "builtins":
                for alias in node.names:
                    if alias.name == "__import__":
                        builtin_import_functions.add(alias.asname or alias.name)

    references = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        function = node.func
        is_dynamic_import = (
            isinstance(function, ast.Name)
            and function.id in import_module_functions | builtin_import_functions
        ) or (
            isinstance(function, ast.Attribute)
            and isinstance(function.value, ast.Name)
            and (
                (
                    function.value.id in importlib_modules
                    and function.attr == "import_module"
                )
                or (
                    function.value.id in builtins_modules
                    and function.attr == "__import__"
                )
            )
        )
        if not is_dynamic_import:
            continue
        imported = _constant_string(node.args[0])
        if imported:
            references.append(
                ImportReference(imported, node.lineno, "dynamic import")
            )
    return references


def _forbidden_reason(module):
    if module == "frida" or module.startswith("frida."):
        return "runtime imports Frida"
    if module == "integrations.frida" or module.startswith("integrations.frida."):
        return "runtime imports the excluded Frida integration"
    if module == "scripts" or module.startswith("scripts."):
        if module in ALLOWED_SCRIPT_MODULES:
            return None
        return "runtime imports a non-whitelisted scripts module"
    return None


def _source_violations(project_root, path, module):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    references = _static_import_references(tree, module, path)
    references.extend(_dynamic_import_references(tree))
    relative = path.relative_to(project_root).as_posix()
    violations = set()
    for reference in references:
        reason = _forbidden_reason(reference.module)
        if reason:
            violations.add(
                ImportViolation(
                    relative,
                    reference.line,
                    reference.module,
                    f"{reason} via {reference.kind}",
                )
            )
    return violations


def scan_runtime_sources(
    project_root,
    runtime_roots=RUNTIME_SOURCE_ROOTS,
    entry_files=RUNTIME_ENTRY_FILES,
):
    violations = set()
    for path in _runtime_source_paths(project_root, runtime_roots, entry_files):
        module = _module_name(project_root, path)
        violations.update(_source_violations(project_root, path, module))
    return sorted(violations)


def _local_dependencies(tree, module, path, module_index):
    dependencies = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in module_index:
                    dependencies.add(alias.name)
            continue
        if not isinstance(node, ast.ImportFrom):
            continue
        base = _resolve_from_base(node, module, path)
        if base in module_index:
            dependencies.add(base)
        for alias in node.names:
            if alias.name == "*":
                continue
            candidate = f"{base}.{alias.name}" if base else alias.name
            if candidate in module_index:
                dependencies.add(candidate)
    for reference in _dynamic_import_references(tree):
        if reference.module in module_index:
            dependencies.add(reference.module)
    return dependencies


def scan_main_import_graph(project_root):
    module_index = _local_module_index(project_root)
    pending = ["main"] if "main" in module_index else []
    visited = set()
    violations = set()
    while pending:
        module = pending.pop()
        if module in visited:
            continue
        visited.add(module)
        path = module_index[module]
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        violations.update(_source_violations(project_root, path, module))
        for dependency in _local_dependencies(tree, module, path, module_index):
            reason = _forbidden_reason(dependency)
            if reason and dependency not in ALLOWED_SCRIPT_MODULES:
                continue
            if dependency not in visited:
                pending.append(dependency)
    return sorted(violations), visited


def _assert_clean(violations):
    assert not violations, "\n" + "\n".join(map(str, violations))


def test_runtime_source_guard_covers_all_runtime_roots():
    scanned = {
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in _runtime_source_paths(PROJECT_ROOT)
    }
    assert {
        "main.py",
        "core/settings.py",
        "core/runtime_paths.py",
        "backend/app/app.py",
        "career_bot/delay.py",
        "uma_api/client.py",
        "uma_data/loaders.py",
        "integrations/discord/notify.py",
        "integrations/game_process/gameproc.py",
    } <= scanned
    assert not any(path.startswith("scripts/") for path in scanned)
    assert not any(path.startswith("integrations/frida/") for path in scanned)
    assert not any(path.startswith("uma_runtime/") for path in scanned)


def test_all_runtime_sources_are_frida_free():
    _assert_clean(scan_runtime_sources(PROJECT_ROOT))


def test_main_local_import_graph_is_frida_free_and_follows_scraper():
    violations, visited = scan_main_import_graph(PROJECT_ROOT)
    _assert_clean(violations)
    assert "scripts.scrape_gametora_effects" in visited


@pytest.mark.parametrize(
    "source",
    (
        "import frida\n",
        "import importlib\nimportlib.import_module('frida.core')\n",
        "__import__('fri' + 'da')\n",
    ),
)
def test_guard_self_test_detects_direct_and_dynamic_frida_imports(
    tmp_path, source,
):
    runtime_package = tmp_path / "runtime_package"
    runtime_package.mkdir()
    (runtime_package / "__init__.py").write_text("", encoding="utf-8")
    (runtime_package / "bad.py").write_text(source, encoding="utf-8")

    violations = scan_runtime_sources(
        tmp_path,
        runtime_roots=("runtime_package",),
        entry_files=(),
    )

    assert any(violation.module.startswith("frida") for violation in violations)


def test_guard_rejects_every_non_whitelisted_scripts_import(tmp_path):
    runtime_package = tmp_path / "runtime_package"
    runtime_package.mkdir()
    (runtime_package / "bad.py").write_text(
        "from scripts import record_traffic\n",
        encoding="utf-8",
    )

    violations = scan_runtime_sources(
        tmp_path,
        runtime_roots=("runtime_package",),
        entry_files=(),
    )

    assert [violation.module for violation in violations] == [
        "scripts.record_traffic",
    ]


def test_guard_self_test_follows_a_two_hop_local_import(tmp_path):
    runtime_package = tmp_path / "runtime_package"
    runtime_package.mkdir()
    (tmp_path / "main.py").write_text(
        "from runtime_package import bridge\n",
        encoding="utf-8",
    )
    (runtime_package / "bridge.py").write_text(
        "from runtime_package import leaf\n",
        encoding="utf-8",
    )
    (runtime_package / "leaf.py").write_text("import frida\n", encoding="utf-8")

    violations, visited = scan_main_import_graph(tmp_path)

    assert "runtime_package.leaf" in visited
    assert any(
        violation.path == "runtime_package/leaf.py"
        and violation.module == "frida"
        for violation in violations
    )
