import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

import core.runtime_paths as runtime_paths
from core.settings import Settings
from uma_api import steam_auth


def test_get_ticket_executes_the_steam_script_by_path(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(steam_auth, "check_deps", lambda: None)
    data_dir = tmp_path / "steam-user"
    monkeypatch.setattr(steam_auth, "_steam_user_data_dir", lambda: data_dir)
    monkeypatch.setattr(
        steam_auth,
        "get_steam_machine_name",
        lambda: "DESKTOP-ABCDEFG",
    )

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        seen["kwargs"] = kwargs
        return SimpleNamespace(
            stdout='diagnostic\n{"steam_id":"1","session_ticket":"ABC","refresh_token":"R"}\n',
            stderr="",
            returncode=0,
        )

    monkeypatch.setattr(steam_auth.subprocess, "run", fake_run)

    assert steam_auth.get_ticket(refresh_token="saved-token") == ("1", "ABC", "R")
    expected = Settings.JS_STEAM_TICKET_GEN
    assert seen["cmd"] == [
        "node", str(expected), "--",
        "--data-directory", str(data_dir),
        "--machine-name", "DESKTOP-ABCDEFG",
        "--refresh-token", "saved-token",
    ]
    assert seen["kwargs"]["cwd"] == steam_auth.DIR


@pytest.mark.parametrize("returncode, message", [
    (2, "STEAM_GUARD_REQUIRED"),
    (4, "TOKEN_INVALID"),
])
def test_get_ticket_preserves_exit_code_contract(
    tmp_path, monkeypatch, returncode, message,
):
    monkeypatch.setattr(steam_auth, "check_deps", lambda: None)
    monkeypatch.setattr(
        steam_auth,
        "_steam_user_data_dir",
        lambda: tmp_path / "steam-user",
    )
    monkeypatch.setattr(
        steam_auth,
        "get_steam_machine_name",
        lambda: "DESKTOP-ABCDEFG",
    )
    monkeypatch.setattr(
        steam_auth.subprocess, "run",
        lambda *args, **kwargs: SimpleNamespace(stdout="", stderr="failure", returncode=returncode),
    )

    with pytest.raises(Exception, match=message):
        steam_auth.get_ticket("user", "password")


def test_steam_user_data_directory_is_private_under_state_root(
    tmp_path, monkeypatch,
):
    state_root = (tmp_path / "selected-state").resolve()
    chmod_calls = []
    monkeypatch.setenv("UMA_RUNTIME_DIR", str(state_root))
    monkeypatch.setattr(runtime_paths, "_posix_permissions", lambda: True)
    monkeypatch.setattr(
        runtime_paths.os,
        "chmod",
        lambda path, mode: chmod_calls.append((Path(path).resolve(), mode)),
    )

    data_dir = steam_auth._steam_user_data_dir()

    assert data_dir == state_root / "steam-user"
    assert data_dir.is_dir()
    assert (state_root, 0o700) in chmod_calls
    assert (data_dir, 0o700) in chmod_calls


def _write_steam_library_stub(path):
    path.write_text(
        """
const Module = require("module");
const EventEmitter = require("events");
const os = require("os");

os.platform = () => process.env.TEST_NODE_PLATFORM || "win32";
os.release = () => process.env.TEST_NODE_RELEASE || "10.0.26100";

function capture(kind, value) {
  process.stderr.write("CAPTURE:" + JSON.stringify({kind, ...value}) + "\\n");
}

class SteamUserStub extends EventEmitter {
  constructor(options) {
    super();
    capture("steam-user-constructor", {options});
    this.steamID = {getSteamID64: () => "76561198000000000"};
  }

  logOn(options) {
    capture("steam-user-logon", {options});
    setImmediate(() => this.emit("loggedOn"));
  }

  createAuthSessionTicket(appid, callback) {
    capture("steam-user-ticket", {appid});
    callback(null, Buffer.from([0xab, 0xcd]));
  }
}
SteamUserStub.EOSType = {Win11: 20};

class LoginSessionStub extends EventEmitter {
  constructor(platformType, options) {
    super();
    capture("steam-session-constructor", {platformType, options});
    this.refreshToken = "qr-refresh-token";
    this.steamID = {getSteamID64: () => "76561198000000000"};
  }

  async startWithQR() {
    setImmediate(() => this.emit("authenticated"));
    return {qrChallengeUrl: "https://example.invalid/qr"};
  }
}

const originalLoad = Module._load;
Module._load = function(request, parent, isMain) {
  if (request === "steam-user") {
    return SteamUserStub;
  }
  if (request === "steam-session") {
    return {
      LoginSession: LoginSessionStub,
      EAuthTokenPlatformType: {SteamClient: 7},
    };
  }
  return originalLoad.call(this, request, parent, isMain);
};
""".lstrip(),
        encoding="utf-8",
    )


def _run_stubbed_steam_script(preload, script, platform_name, args=()):
    env = os.environ.copy()
    env["TEST_NODE_PLATFORM"] = platform_name
    env["TEST_NODE_RELEASE"] = (
        "10.0.26100" if platform_name == "win32" else "6.8.0"
    )
    command = ["node", "-r", str(preload), str(script)]
    if args:
        command.extend(["--", *args])
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=5,
        cwd=Settings.BASE_DIR,
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return [
        json.loads(line.removeprefix("CAPTURE:"))
        for line in result.stderr.splitlines()
        if line.startswith("CAPTURE:")
    ]


@pytest.mark.parametrize(
    ("auth_args", "expected_auth"),
    [
        (
            ("--refresh-token", "saved-token"),
            {"refreshToken": "saved-token"},
        ),
        (
            (
                "--username", "alice", "--password", "secret",
                "--code", "123456",
            ),
            {
                "accountName": "alice",
                "password": "secret",
                "twoFactorCode": "123456",
            },
        ),
    ],
)
def test_steam_user_profile_options_are_host_independent(
    tmp_path, auth_args, expected_auth,
):
    preload = tmp_path / "steam_library_stub.js"
    _write_steam_library_stub(preload)
    data_dir = tmp_path / "managed-state" / "steam-user"
    args = (
        *auth_args,
        "--data-directory", str(data_dir),
        "--machine-name", "DESKTOP-ABCDEFG",
    )

    captures = [
        _run_stubbed_steam_script(
            preload,
            Settings.JS_STEAM_TICKET_GEN,
            platform_name,
            args,
        )
        for platform_name in ("win32", "linux")
    ]

    assert captures[0] == captures[1]
    assert captures[0][0] == {
        "kind": "steam-user-constructor",
        "options": {"dataDirectory": str(data_dir)},
    }
    assert captures[0][1] == {
        "kind": "steam-user-logon",
        "options": {
            **expected_auth,
            "clientOS": 20,
            "machineName": "DESKTOP-ABCDEFG",
        },
    }


def test_steam_qr_profile_options_are_host_independent(tmp_path):
    preload = tmp_path / "steam_library_stub.js"
    _write_steam_library_stub(preload)

    captures = [
        _run_stubbed_steam_script(
            preload,
            Settings.JS_STEAM_QR_LOGIN,
            platform_name,
            ("--machine-name", "DESKTOP-ABCDEFG"),
        )
        for platform_name in ("win32", "linux")
    ]

    assert captures[0] == captures[1]
    assert captures[0][0] == {
        "kind": "steam-session-constructor",
        "platformType": 7,
        "options": {"machineFriendlyName": "DESKTOP-ABCDEFG"},
    }


class _ProcessSpy:
    def __init__(self, wait_results=None, poll_results=None):
        self.events = []
        self.wait_results = list(wait_results or [0])
        self.poll_results = list(poll_results or [None])

    def poll(self):
        self.events.append("poll")
        result = self.poll_results.pop(0) if self.poll_results else None
        if isinstance(result, BaseException):
            raise result
        return result

    def terminate(self):
        self.events.append("terminate")

    def wait(self, timeout):
        self.events.append(("wait", timeout))
        result = self.wait_results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result

    def kill(self):
        self.events.append("kill")


def test_qr_terminate_waits_after_terminate():
    qr = steam_auth.QrLoginSession()
    proc = _ProcessSpy()
    qr.proc = proc

    qr._terminate_locked()

    assert proc.events == [
        "poll",
        "terminate",
        ("wait", steam_auth._PROCESS_STOP_TIMEOUT_SECONDS),
    ]


def test_qr_terminate_kills_and_waits_again_after_timeout():
    qr = steam_auth.QrLoginSession()
    timeout = steam_auth.subprocess.TimeoutExpired("node", 2)
    proc = _ProcessSpy(wait_results=[timeout, 0])
    qr.proc = proc

    qr._terminate_locked()

    assert proc.events == [
        "poll",
        "terminate",
        ("wait", steam_auth._PROCESS_STOP_TIMEOUT_SECONDS),
        "kill",
        ("wait", steam_auth._PROCESS_STOP_TIMEOUT_SECONDS),
    ]


def test_qr_terminate_never_raises_when_process_disappears():
    qr = steam_auth.QrLoginSession()
    proc = _ProcessSpy(
        wait_results=[ChildProcessError("already reaped")],
        poll_results=[None, 0],
    )
    qr.proc = proc

    qr._terminate_locked()

    assert proc.events == [
        "poll",
        "terminate",
        ("wait", steam_auth._PROCESS_STOP_TIMEOUT_SECONDS),
        "poll",
    ]


def test_qr_stop_cannot_leave_a_stale_pending_snapshot():
    qr = steam_auth.QrLoginSession()
    qr.proc = _ProcessSpy()
    qr.status = "pending"

    qr.stop()

    assert qr.snapshot() == {
        "status": "error",
        "challenge_url": "",
        "steam_id": "",
        "error": "QR login stopped",
    }


def test_take_refresh_token_is_non_destructive_for_persistence_retry():
    qr = steam_auth.QrLoginSession()
    qr.refresh_token = "retryable-token"

    assert qr.take_refresh_token() == "retryable-token"
    assert qr.take_refresh_token() == "retryable-token"

