from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCHERS = ("run-linux.sh", "run-windows.cmd")
ROOT_NODE_INSTALLS = {
    "run-linux.sh": "npm ci --ignore-scripts --omit=dev",
    "run-windows.cmd": "npm.cmd ci --ignore-scripts --omit=dev",
}
MAIN_INVOCATIONS = {
    "run-linux.sh": 'exec "$venv_python" "$SCRIPT_DIR/main.py" "$@"',
    "run-windows.cmd": '"%VENV_PY%" main.py%MAIN_ARGS%',
}


def _read_launcher(name: str, root: Path = REPO_ROOT) -> str:
    path = root / name
    assert path.is_file(), f"missing launcher: {name}"
    return path.read_text(encoding="utf-8")


def _assert_no_re_requirements(text: str) -> None:
    assert "requirements-re.txt" not in text


def _assert_safe_root_node_install(name: str, text: str) -> None:
    assert ROOT_NODE_INSTALLS[name] in text


def _assert_supported_entrypoint(name: str, text: str) -> None:
    assert MAIN_INVOCATIONS[name] in text
    assert "uvicorn" not in text.lower()


def _assert_ui_output_check(text: str) -> None:
    assert "frontend/dist/index.html" in text


@pytest.mark.parametrize("launcher", LAUNCHERS)
def test_launcher_exists(launcher):
    _read_launcher(launcher)


@pytest.mark.parametrize("launcher", LAUNCHERS)
def test_launcher_never_installs_reverse_engineering_requirements(launcher):
    _assert_no_re_requirements(_read_launcher(launcher))


@pytest.mark.parametrize("launcher", LAUNCHERS)
def test_launcher_root_node_install_disables_lifecycle_scripts(launcher):
    _assert_safe_root_node_install(launcher, _read_launcher(launcher))


@pytest.mark.parametrize("launcher", LAUNCHERS)
def test_launcher_uses_supported_python_entrypoint(launcher):
    _assert_supported_entrypoint(launcher, _read_launcher(launcher))


@pytest.mark.parametrize("launcher", LAUNCHERS)
def test_launcher_checks_the_served_ui_output(launcher):
    _assert_ui_output_check(_read_launcher(launcher))
