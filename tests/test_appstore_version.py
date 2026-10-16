import importlib
import logging

import pytest

from uma_api import appstore_version
from uma_api import client_version


def test_fetch_app_ver_from_store_parses_version(monkeypatch):
    requested = []

    def fake_get(url, timeout):
        requested.append((url, timeout))
        return {
            "resultCount": 1,
            "results": [{"version": " 1.33.0 "}],
        }

    monkeypatch.setattr(appstore_version, "_http_get_json", fake_get)

    assert appstore_version.fetch_app_ver_from_store() == "1.33.0"
    assert requested == [
        (
            "https://itunes.apple.com/lookup?id=6480433538&country=us",
            appstore_version.DEFAULT_TIMEOUT,
        )
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {"resultCount": 0, "results": []},
        {"resultCount": 1, "results": [{}]},
        {"resultCount": 1, "results": [{"version": "abc"}]},
        {"resultCount": 1, "results": [{"version": "1.2"}]},
        {"resultCount": 1, "results": [{"version": "22.3.62f2"}]},
    ],
)
def test_fetch_app_ver_from_store_rejects_invalid_payloads(
    payload, monkeypatch
):
    monkeypatch.setattr(
        appstore_version,
        "_http_get_json",
        lambda *_args, **_kwargs: payload,
    )

    assert appstore_version.fetch_app_ver_from_store() is None


def test_fetch_app_ver_from_store_swallows_http_helper_error(monkeypatch):
    def raise_network_error(*_args, **_kwargs):
        raise OSError("network is down")

    monkeypatch.setattr(
        appstore_version, "_http_get_json", raise_network_error
    )

    assert appstore_version.fetch_app_ver_from_store() is None


@pytest.mark.parametrize(
    ("store_url", "expected"),
    [
        (
            "https://apps.apple.com/us/app/id6480433538",
            "6480433538",
        ),
        (
            "https://store.steampowered.com/app/3224770/",
            None,
        ),
        ("not a store URL", None),
    ],
)
def test_parse_app_id_from_store_url(store_url, expected):
    assert appstore_version.parse_app_id_from_store_url(store_url) == expected


def test_ensure_app_ver_headless_persists_store_version(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        appstore_version,
        "fetch_app_ver_from_store",
        lambda *_args, **_kwargs: "9.9.9",
    )

    assert appstore_version.ensure_app_ver_headless(tmp_path) == "9.9.9"
    assert client_version.get_app_ver(tmp_path) == "9.9.9"
    assert client_version.load_client_version(tmp_path)["source"] == "appstore"


def test_ensure_app_ver_headless_keeps_existing_version_on_fetch_failure(
    tmp_path, monkeypatch
):
    assert client_version.set_app_ver(
        tmp_path, "1.2.3", source="publisher"
    )
    before = client_version.client_version_path(tmp_path).read_text(
        encoding="utf-8"
    )
    monkeypatch.setattr(
        appstore_version,
        "fetch_app_ver_from_store",
        lambda *_args, **_kwargs: None,
    )

    assert appstore_version.ensure_app_ver_headless(tmp_path) is None
    assert client_version.get_app_ver(tmp_path) == "1.2.3"
    assert (
        client_version.client_version_path(tmp_path).read_text(encoding="utf-8")
        == before
    )


def test_local_and_app_store_version_disagreement_logs_both_values(
    tmp_path, monkeypatch, caplog,
):
    app_module = importlib.import_module("backend.app.app")
    published = []
    monkeypatch.setattr(
        app_module.client_version,
        "read_app_ver_from_game",
        lambda: "1.33.0",
    )
    monkeypatch.setattr(
        app_module.client_version,
        "set_app_ver",
        lambda *args, **kwargs: published.append((args, kwargs)) or True,
    )
    monkeypatch.setattr(
        appstore_version,
        "fetch_app_ver_from_store",
        lambda: "1.34.0",
    )
    monkeypatch.setattr(
        appstore_version,
        "ensure_app_ver_headless",
        lambda *_args, **_kwargs: pytest.fail(
            "a local build must remain authoritative"
        ),
    )
    caplog.set_level(logging.WARNING)

    app_module._publish_startup_app_ver(tmp_path)

    assert published == [((tmp_path, "1.33.0"), {"source": "auto-startup"})]
    assert "local game build 1.33.0" in caplog.text
    assert "App Store version 1.34.0" in caplog.text
    assert "continuing with the local game build" in caplog.text
