"""Coverage for the automatic (boot/login-wired) master.mdb update path.

fetch_master_mdb() itself (the CDN manifest walk) is already covered offline in
tests/test_master_updater.py -- these tests exercise the gating logic around it
and the guest version lookup that feeds it. UmaClient and fetch_master_mdb are
always monkeypatched to stubs; nothing here touches the live CDN or master.mdb.
"""

import logging
from pathlib import Path

import pytest

from uma_api import client_version
from uma_data import master_updater
import uma_data


# --- client_version.json: resource_server + master_res_ver marker round-trips ---


def test_resource_server_round_trips(tmp_path):
    assert client_version.get_resource_server(tmp_path) is None

    assert client_version.set_resource_server(
        tmp_path, "https://assets-umamusume-en.akamaized.net/dl/vertical/",
    )
    assert client_version.get_resource_server(tmp_path) == (
        "https://assets-umamusume-en.akamaized.net/dl/vertical/"
    )


def test_master_res_ver_round_trips(tmp_path):
    assert client_version.get_master_res_ver(tmp_path) is None

    assert client_version.set_master_res_ver(tmp_path, "10006800")
    assert client_version.get_master_res_ver(tmp_path) == "10006800"

    # A later write updates it in place (mirrors set_res_ver's behavior).
    assert client_version.set_master_res_ver(tmp_path, "10006900", source="master-updater")
    assert client_version.get_master_res_ver(tmp_path) == "10006900"


# --- unauthenticated pre-download resource-version lookup ---


def test_fetch_version_info_headless_persists_response(tmp_path, monkeypatch):
    calls = []

    class StubUmaClient:
        def __init__(self, config):
            calls.append(("init", config))

        def regen_sid(self):
            calls.append(("regen_sid",))

        def call(self, endpoint, payload):
            calls.append(("call", endpoint, payload))
            return {
                "data_headers": {
                    "server_list": {
                        "resource_server": (
                            "assets-umamusume-en.akamaized.net/dl/vertical/"
                        )
                    }
                },
                "data": {"resource_version": "10006910"},
            }

    monkeypatch.setattr("uma_api.client.UmaClient", StubUmaClient)

    result = master_updater.fetch_version_info_headless(
        tmp_path,
        app_ver="1.32.9",
        state_root=tmp_path,
    )

    assert result == (
        "assets-umamusume-en.akamaized.net/dl/vertical/",
        "10006910",
    )
    assert calls[0][0] == "init"
    assert calls[0][1]["app_ver"] == "1.32.9"
    assert calls[0][1]["udid"]
    # The guest must NOT carry an explicit fingerprint: UmaClient resolves one
    # from this machine, so every install presents a distinct device_id.
    assert not {
        "device_id",
        "device_name",
        "graphics_device_name",
        "ip_address",
        "platform_os_version",
    } & set(calls[0][1])
    assert calls[1:] == [
        ("regen_sid",),
        ("call", "tool/get_pre_download_resource_version", {}),
    ]
    assert client_version.get_resource_server(tmp_path) == (
        "assets-umamusume-en.akamaized.net/dl/vertical/"
    )
    assert client_version.get_res_ver(tmp_path) == "10006910"
    assert client_version.load_client_version(tmp_path)["source"] == "predownload"


def test_fetch_version_info_headless_swallows_client_error(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.INFO)

    class StubUmaClient:
        def __init__(self, config):
            pass

        def regen_sid(self):
            pass

        def call(self, endpoint, payload):
            raise RuntimeError("network is down")

    monkeypatch.setattr("uma_api.client.UmaClient", StubUmaClient)

    assert master_updater.fetch_version_info_headless(
        tmp_path,
        state_root=tmp_path,
    ) == (None, None)
    assert not client_version.client_version_path(tmp_path).exists()
    assert "headless resource version fetch skipped" in caplog.text


def test_ensure_current_headless_forwards_resolved_pair(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        master_updater,
        "fetch_version_info_headless",
        lambda base_dir, app_ver=None, **kwargs: (
            "https://cdn.example/",
            "10006910",
        ),
    )

    def stub_ensure_current(base_dir, resource_server, res_ver, **kwargs):
        calls.append((base_dir, resource_server, res_ver))
        return True

    monkeypatch.setattr(master_updater, "ensure_current", stub_ensure_current)

    assert master_updater.ensure_current_headless(
        tmp_path,
        "9.9.9",
        state_root=tmp_path,
    ) is True
    assert calls == [(tmp_path, "https://cdn.example/", "10006910")]


def test_ensure_current_headless_skips_without_version_info(tmp_path, monkeypatch):
    monkeypatch.setattr(
        master_updater,
        "fetch_version_info_headless",
        lambda base_dir, app_ver=None, **kwargs: (None, None),
    )

    def unexpected_ensure_current(*args, **kwargs):
        pytest.fail("ensure_current must not be called without both version fields")

    monkeypatch.setattr(
        master_updater, "ensure_current", unexpected_ensure_current
    )

    assert master_updater.ensure_current_headless(
        tmp_path,
        state_root=tmp_path,
    ) is False


# --- ensure_current() gating ---


def _stub_fetch(calls, *, raise_exc=None, write_bytes=b"stub-master-mdb"):
    def _fetch(resource_server_base, res_ver, dest_path, **kwargs):
        calls.append((resource_server_base, res_ver, Path(dest_path)))
        if raise_exc is not None:
            raise raise_exc
        Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
        Path(dest_path).write_bytes(write_bytes)
    return _fetch


def test_ensure_current_false_without_resource_server_or_res_ver(tmp_path, monkeypatch):
    dest = tmp_path / "master.mdb"
    monkeypatch.setattr(uma_data, "configured_master_mdb_path", lambda base_dir, state_root=None, dest=dest: dest)

    assert master_updater.ensure_current(tmp_path, "", "10006800") is False
    assert master_updater.ensure_current(tmp_path, "https://cdn.example/", "") is False
    assert not dest.exists()


def test_ensure_current_fetches_when_master_mdb_missing(tmp_path, monkeypatch):
    dest = tmp_path / "master.mdb"
    state_root = tmp_path / "state"
    resolved = []
    monkeypatch.setattr(
        uma_data,
        "configured_master_mdb_path",
        lambda base_dir, state_root=None: resolved.append(
            (base_dir, state_root)
        ) or dest,
    )
    calls = []
    monkeypatch.setattr(master_updater, "fetch_master_mdb", _stub_fetch(calls))

    assert not dest.exists()
    result = master_updater.ensure_current(
        tmp_path,
        "https://cdn.example/",
        "10006800",
        state_root=state_root,
    )

    assert result is True
    assert resolved == [(tmp_path, state_root.resolve())]
    assert calls == [("https://cdn.example/", "10006800", dest)]
    assert dest.read_bytes() == b"stub-master-mdb"
    assert client_version.get_master_res_ver(state_root) == "10006800"


def test_ensure_current_fetches_when_res_ver_changed(tmp_path, monkeypatch):
    dest = tmp_path / "master.mdb"
    dest.write_bytes(b"stale-master-mdb")
    monkeypatch.setattr(uma_data, "configured_master_mdb_path", lambda base_dir, state_root=None, dest=dest: dest)
    client_version.set_master_res_ver(tmp_path, "10006700")
    calls = []
    monkeypatch.setattr(master_updater, "fetch_master_mdb", _stub_fetch(calls))

    result = master_updater.ensure_current(
        tmp_path,
        "https://cdn.example/",
        "10006800",
        state_root=tmp_path,
    )

    assert result is True
    assert calls == [("https://cdn.example/", "10006800", dest)]
    assert client_version.get_master_res_ver(tmp_path) == "10006800"


def test_ensure_current_no_fetch_when_res_ver_unchanged(tmp_path, monkeypatch):
    dest = tmp_path / "master.mdb"
    dest.write_bytes(b"current-master-mdb")
    monkeypatch.setattr(uma_data, "configured_master_mdb_path", lambda base_dir, state_root=None, dest=dest: dest)
    client_version.set_master_res_ver(tmp_path, "10006800")
    calls = []
    monkeypatch.setattr(master_updater, "fetch_master_mdb", _stub_fetch(calls))

    result = master_updater.ensure_current(
        tmp_path,
        "https://cdn.example/",
        "10006800",
        state_root=tmp_path,
    )

    assert result is False
    assert calls == []
    assert dest.read_bytes() == b"current-master-mdb"


def test_ensure_current_force_refetches_even_when_unchanged(tmp_path, monkeypatch):
    dest = tmp_path / "master.mdb"
    dest.write_bytes(b"current-master-mdb")
    monkeypatch.setattr(uma_data, "configured_master_mdb_path", lambda base_dir, state_root=None, dest=dest: dest)
    client_version.set_master_res_ver(tmp_path, "10006800")
    calls = []
    monkeypatch.setattr(master_updater, "fetch_master_mdb", _stub_fetch(calls))

    result = master_updater.ensure_current(
        tmp_path,
        "https://cdn.example/",
        "10006800",
        force=True,
        state_root=tmp_path,
    )

    assert result is True
    assert calls == [("https://cdn.example/", "10006800", dest)]


def test_ensure_current_swallows_fetch_exception_and_returns_false(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    dest = tmp_path / "master.mdb"
    monkeypatch.setattr(uma_data, "configured_master_mdb_path", lambda base_dir, state_root=None, dest=dest: dest)
    calls = []
    monkeypatch.setattr(
        master_updater,
        "fetch_master_mdb",
        _stub_fetch(calls, raise_exc=master_updater.DownloadError("network is down")),
    )

    result = master_updater.ensure_current(
        tmp_path,
        "https://cdn.example/",
        "10006800",
        state_root=tmp_path,
    )

    assert result is False
    assert calls  # the fetch WAS attempted...
    assert not dest.exists()  # ...but never left a partial/dummy file behind
    assert client_version.get_master_res_ver(tmp_path) is None  # ...nor recorded success
    assert "master.mdb auto-update skipped" in caplog.text
