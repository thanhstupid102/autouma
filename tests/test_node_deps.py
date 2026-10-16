import subprocess

import pytest

from uma_api import device
from uma_api.errors import NodeDependenciesError


def _set_dependency_root(monkeypatch, tmp_path):
    monkeypatch.setattr(device, "DIR", str(tmp_path))
    monkeypatch.setattr(device.shutil, "which", lambda executable: "node")


def _write_package(root, package):
    package_dir = root / "node_modules" / package
    package_dir.mkdir(parents=True)
    (package_dir / "package.json").write_text("{}", encoding="utf-8")


def _forbid_subprocess(*args, **kwargs):
    raise AssertionError("check_deps must not spawn a subprocess")


def _forbid_subprocesses(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _forbid_subprocess)
    monkeypatch.setattr(subprocess, "Popen", _forbid_subprocess)


def test_check_deps_requires_supported_node_on_path(monkeypatch, tmp_path):
    monkeypatch.setattr(device, "DIR", str(tmp_path))
    monkeypatch.setattr(device.shutil, "which", lambda executable: None)

    with pytest.raises(NodeDependenciesError) as exc_info:
        device.check_deps()

    message = str(exc_info.value)
    assert "Node.js" in message
    assert "20.19.0" in message
    assert 'Run "npm install"' in message


def test_check_deps_reports_absent_node_modules_without_spawning(monkeypatch, tmp_path):
    _set_dependency_root(monkeypatch, tmp_path)
    _forbid_subprocesses(monkeypatch)

    with pytest.raises(NodeDependenciesError) as exc_info:
        device.check_deps()

    assert "steam-user, steam-session" in str(exc_info.value)
    assert 'Run "npm install"' in str(exc_info.value)


@pytest.mark.parametrize(
    ("present", "missing"),
    (("steam-user", "steam-session"), ("steam-session", "steam-user")),
)
def test_check_deps_names_each_missing_runtime_package(
        monkeypatch, tmp_path, present, missing,
):
    _set_dependency_root(monkeypatch, tmp_path)
    _write_package(tmp_path, present)

    with pytest.raises(NodeDependenciesError) as exc_info:
        device.check_deps()

    message = str(exc_info.value)
    assert missing in message
    assert present not in message


def test_check_deps_rejects_empty_package_directory(monkeypatch, tmp_path):
    _set_dependency_root(monkeypatch, tmp_path)
    (tmp_path / "node_modules" / "steam-user").mkdir(parents=True)
    _write_package(tmp_path, "steam-session")

    with pytest.raises(NodeDependenciesError, match="steam-user"):
        device.check_deps()


def test_check_deps_accepts_installed_runtime_packages_without_spawning(
        monkeypatch, tmp_path,
):
    _set_dependency_root(monkeypatch, tmp_path)
    _write_package(tmp_path, "steam-user")
    _write_package(tmp_path, "steam-session")
    _forbid_subprocesses(monkeypatch)

    device.check_deps()


def test_auth_login_returns_node_dependency_error_detail(monkeypatch, tmp_path):
    from tests._helpers import make_client
    from uma_api import client as client_module

    message = 'Missing Node dependencies: steam-session. Run "npm install" in /app.'

    def raise_dependency_error(*args, **kwargs):
        raise NodeDependenciesError(message)

    monkeypatch.setattr(client_module, "get_ticket", raise_dependency_error)
    _app, client = make_client(tmp_path)

    response = client.post(
        "/api/auth/login",
        json={"username": "steam-user", "password": "steam-password"},
        headers={"X-Account": "tester"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "success": False,
        "state": "failed",
        "detail": message,
    }
