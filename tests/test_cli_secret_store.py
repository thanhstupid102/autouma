from fastapi import FastAPI
import pytest

from backend.app import cli, context
from backend.app.domain import account_store
from backend.app import logging_setup
import integrations.game_process.gameproc as gameproc
from uma_api import secret_store


class _SessionManager:
    def get(self, _account):
        return object()


def test_account_startup_secret_error_is_one_line_and_actionable(monkeypatch):
    monkeypatch.setattr(
        gameproc,
        "parse_cli_args",
        lambda _args: (1717, "linux-account", False, "127.0.0.1"),
    )
    monkeypatch.setattr(gameproc, "set_console_topmost", lambda: None)
    monkeypatch.setattr(gameproc, "kill_listeners_on_port", lambda _port: None)
    monkeypatch.setattr(logging_setup, "configure_console_logging", lambda: None)
    monkeypatch.setattr(context, "session_manager", _SessionManager())

    def fail_load(_account):
        raise secret_store.SecretStoreUnavailableError(
            "set UMA_SECRET_PASSPHRASE or UMA_SECRET_PASSPHRASE_FILE",
        )

    monkeypatch.setattr(account_store, "load_account_config", fail_load)

    with pytest.raises(SystemExit) as caught:
        cli.run(FastAPI())

    message = str(caught.value)
    assert "linux-account" in message
    assert "UMA_SECRET_PASSPHRASE" in message
    assert "UMA_SECRET_PASSPHRASE_FILE" in message
    assert "\n" not in message
