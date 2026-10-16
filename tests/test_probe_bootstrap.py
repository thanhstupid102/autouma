import base64

from scripts import probe_bootstrap
from uma_api import bootstrap


class _Client:
    def __init__(self):
        self.session = self
        self.closed = False

    def close(self):
        self.closed = True


def _pre_signup_response():
    return {
        "data_headers": {"result_code": 1, "viewer_id": 0},
        "data": {
            "enable_steam_account": True,
            "attest": False,
            "nonce": "",
            "country_list": ["CA", "US"],
        },
    }


def _result(*, state, signup_response=None):
    client = _Client()
    return bootstrap.SteamBootstrapResult(
        state=state,
        client=client,
        config={
            "viewer_id": 123456789,
            "udid": "generated-device",
            "auth_key": "ab" * 48,
            "steam_id": "sensitive-steam-id",
            "steam_session_ticket": "sensitive-ticket",
        },
        signup_response=signup_response,
        pre_signup_response=_pre_signup_response(),
        enable_steam_account=True,
        attest=False,
        nonce="",
    )


def _install_stored_credentials(monkeypatch):
    monkeypatch.setattr(
        probe_bootstrap,
        "load_steam_token",
        lambda account: {"refresh_token": "sensitive-refresh-token"},
    )
    monkeypatch.setattr(
        probe_bootstrap.steam_auth,
        "get_ticket",
        lambda *, refresh_token: ("sensitive-steam-id", "sensitive-ticket", ""),
    )


def test_probe_without_confirmation_only_runs_pre_signup(monkeypatch, capsys):
    _install_stored_credentials(monkeypatch)
    calls = []
    writes = []

    def fake_bootstrap(**kwargs):
        calls.append(kwargs)
        return _result(state=bootstrap.BootstrapState.PRE_SIGNUP_COMPLETE)

    monkeypatch.setattr(probe_bootstrap.bootstrap, "bootstrap_steam_account", fake_bootstrap)
    monkeypatch.setattr(
        probe_bootstrap.secret_store,
        "save_json",
        lambda path, payload, state_root: writes.append(
            (path, payload, state_root)
        ),
    )

    assert probe_bootstrap.run_probe(account="owner", allow_signup=False) == 0

    output = capsys.readouterr().out
    assert calls == [{
        "steam_id": "sensitive-steam-id",
        "steam_session_ticket": "sensitive-ticket",
        "trace_enabled": False,
        "state_root": probe_bootstrap.RUNTIME_DIR,
        "perform_signup": False,
    }]
    assert writes == []
    assert "tool/signup NOT CALLED" in output
    for secret in (
        "sensitive-refresh-token",
        "sensitive-steam-id",
        "sensitive-ticket",
        "generated-device",
        "ab" * 48,
        "123456789",
    ):
        assert secret not in output


def test_probe_with_confirmation_runs_signup_and_reports_match(monkeypatch, capsys):
    _install_stored_credentials(monkeypatch)
    signup_response = {
        "data_headers": {"result_code": 1, "viewer_id": 123456789},
        "data": {"auth_key": base64.b64encode(b"k" * 48).decode("ascii")},
    }
    calls = []

    def fake_bootstrap(**kwargs):
        calls.append(kwargs)
        return _result(
            state=bootstrap.BootstrapState.AUTHENTICATED,
            signup_response=signup_response,
        )

    monkeypatch.setattr(probe_bootstrap.bootstrap, "bootstrap_steam_account", fake_bootstrap)
    monkeypatch.setattr(
        probe_bootstrap,
        "load_account_config",
        lambda account: {"viewer_id": 123456789},
    )

    assert probe_bootstrap.run_probe(account="owner", allow_signup=True) == 0

    output = capsys.readouterr().out
    assert calls[0]["perform_signup"] is True
    assert "signup.data.auth_key_present: True" in output
    assert "signup.data.auth_key_decoded_byte_length: 48" in output
    assert "matches_existing_account: true" in output


def test_save_path_outside_runtime_is_rejected_before_probe(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        probe_bootstrap.steam_auth,
        "get_ticket",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("network attempted")),
    )

    assert probe_bootstrap.main([
        "--account", "owner", "--save-to", str(tmp_path / "outside.json"),
    ]) == 2

    assert "--save-to must be under the selected state root" in capsys.readouterr().out
    assert list(tmp_path.iterdir()) == []


def test_explicit_save_uses_secret_store(monkeypatch):
    _install_stored_credentials(monkeypatch)
    result = _result(state=bootstrap.BootstrapState.PRE_SIGNUP_COMPLETE)
    saved = []
    save_path = probe_bootstrap.RUNTIME_DIR / "probe-bootstrap-test.json"

    monkeypatch.setattr(
        probe_bootstrap.bootstrap,
        "bootstrap_steam_account",
        lambda **kwargs: result,
    )
    monkeypatch.setattr(
        probe_bootstrap.secret_store,
        "save_json",
        lambda path, payload, state_root: saved.append(
            (path, payload, state_root)
        ),
    )

    assert probe_bootstrap.run_probe(
        account="owner",
        allow_signup=False,
        save_to=save_path,
    ) == 0

    assert saved == [(save_path, result.config, probe_bootstrap.RUNTIME_DIR)]
    assert result.client.closed is True
