import re
import struct
from datetime import datetime

import pytest

from scripts import publish_client_version
from uma_api import client_version


def _unity_string(value):
    raw = value.encode("ascii")
    return struct.pack("<i", len(raw)) + raw + (b"\x00" * (-len(raw) % 4))


def test_missing_client_version_is_empty(tmp_path):
    assert client_version.load_client_version(tmp_path) == {}
    assert client_version.get_app_ver(tmp_path) is None
    assert client_version.get_res_ver(tmp_path) is None


def test_set_app_ver_round_trips_and_preserves_res_ver(tmp_path):
    assert client_version.set_res_ver(tmp_path, "10006900", source="server")
    assert client_version.set_app_ver(tmp_path, "1.32.9")

    state = client_version.load_client_version(tmp_path)
    assert client_version.get_app_ver(tmp_path) == "1.32.9"
    assert state["res_ver"] == "10006900"
    assert state["source"] == "manual"
    assert datetime.fromisoformat(state["updated_at"])


def test_corrupt_client_version_is_empty(tmp_path):
    path = client_version.client_version_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not-json", encoding="utf-8")

    assert client_version.load_client_version(tmp_path) == {}
    assert client_version.get_app_ver(tmp_path) is None


def test_shared_version_precedence_over_captured_config(tmp_path):
    assert client_version.set_app_ver(tmp_path, "9.9.9", source="publisher")
    cv = client_version.load_client_version(tmp_path)

    app_ver, res_ver = client_version.resolve_versions(
        cv,
        {"app_ver": "1.0.0", "res_ver": "captured"},
        "default-app",
        "default-res",
    )

    assert app_ver == "9.9.9"
    assert res_ver == "captured"


def test_resource_version_self_heal_and_empty_noop(tmp_path):
    current = client_version.update_res_ver_from_headers(
        tmp_path, "10006800", {"resource_version": "10006900"},
    )
    assert current == "10006900"
    assert client_version.get_res_ver(tmp_path) == "10006900"
    before = client_version.client_version_path(tmp_path).read_text(encoding="utf-8")

    assert client_version.update_res_ver_from_headers(tmp_path, current, {}) == current
    assert client_version.update_res_ver_from_headers(
        tmp_path, current, {"resource_version": ""},
    ) == current
    assert client_version.client_version_path(tmp_path).read_text(encoding="utf-8") == before


def test_publisher_parser_extracts_bundle_version():
    blob = b"noise" + b"".join([
        _unity_string("productName"),
        _unity_string("22.3.62f2"),
        _unity_string("1.0"),
        _unity_string("1.32.9"),
    ])

    assert publish_client_version.parse_app_version(blob) == "1.32.9"


def test_publisher_parser_refuses_ambiguous_versions():
    blob = _unity_string("22.3.62f2") + _unity_string("1.32.9") + _unity_string("2.0.0")

    with pytest.raises(ValueError, match="exactly one"):
        publish_client_version.parse_app_version(blob)


_LIVE_GAME_DIR = publish_client_version.find_game_dir()
_LIVE_MANAGERS = (
    _LIVE_GAME_DIR / publish_client_version.GLOBAL_GAME_MANAGERS
    if _LIVE_GAME_DIR else None
)


@pytest.mark.skipif(
    not _LIVE_MANAGERS or not _LIVE_MANAGERS.is_file(),
    reason="installed game's globalgamemanagers is unavailable",
)
def test_publisher_parser_live_globalgamemanagers():
    version = publish_client_version.parse_app_version(_LIVE_MANAGERS.read_bytes())
    assert re.fullmatch(r"\d+\.\d+\.\d+", version)
