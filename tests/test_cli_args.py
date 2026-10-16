import os

from core.settings import Settings
import integrations.game_process.gameproc as gameproc


def test_parse_cli_args_defaults_debug_off_and_port_1616(monkeypatch):
    monkeypatch.setattr(Settings, "SWEEPY_PORT", None)
    monkeypatch.setattr(Settings, "SWEEPY_HOST", None)

    port, _account, debug, host = gameproc.parse_cli_args([])

    assert port == 1616
    assert debug is False
    assert host == "127.0.0.1"


def test_parse_cli_args_enables_debug():
    _port, _account, debug, _host = gameproc.parse_cli_args(["--debug"])

    assert debug is True


def test_parse_cli_args_combines_all_options():
    assert gameproc.parse_cli_args(
        ["1717", "--account", "yuko", "--host", "0.0.0.0", "--debug"]
    ) == (1717, "yuko", True, "0.0.0.0")


def test_parse_cli_args_uses_host_env_and_flag_precedence(monkeypatch):
    monkeypatch.setattr(Settings, "SWEEPY_HOST", "192.168.1.20")

    assert gameproc.parse_cli_args([])[3] == "192.168.1.20"
    assert gameproc.parse_cli_args(["--host", "::1"])[3] == "::1"


def test_parse_cli_args_no_longer_recognizes_reauth(monkeypatch):
    monkeypatch.setattr(Settings, "SWEEPY_PORT", None)
    monkeypatch.setattr(Settings, "SWEEPY_HOST", None)
    monkeypatch.setattr(Settings, "SWEEP_ACCOUNT", None)

    assert gameproc.parse_cli_args(["--reauth"]) == (
        1616, None, False, "127.0.0.1",
    )


def test_enable_api_trace_sets_environment_and_setting(monkeypatch):
    monkeypatch.setenv("UMA_TRACE", "0")
    monkeypatch.setattr(Settings, "UMA_TRACE", "0")

    gameproc.enable_api_trace()

    assert os.environ["UMA_TRACE"] == "1"
    assert Settings.UMA_TRACE == "1"
