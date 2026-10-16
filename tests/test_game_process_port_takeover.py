import logging
from types import SimpleNamespace

import integrations.game_process.gameproc as gameproc


def test_windows_takeover_stops_only_verified_application_listener(monkeypatch):
    stopped = []
    settled = []

    monkeypatch.setattr(gameproc, "_platform_name", lambda: "nt")
    monkeypatch.setattr(gameproc, "_windows_listener_pids", lambda _port: {321})
    monkeypatch.setattr(
        gameproc, "_windows_is_application_process", lambda _pid: True,
    )
    monkeypatch.setattr(gameproc, "_terminate_windows_process", stopped.append)
    monkeypatch.setattr(
        gameproc, "dna_sleep", lambda low, high: settled.append((low, high)),
    )

    gameproc.kill_listeners_on_port(1616)

    assert stopped == [321]
    assert settled == [(0.5, 0.5)]


def test_takeover_refuses_unidentified_listener(monkeypatch, caplog):
    stopped = []
    caplog.set_level(logging.ERROR, logger=gameproc.__name__)
    monkeypatch.setattr(gameproc, "_platform_name", lambda: "nt")
    monkeypatch.setattr(gameproc, "_windows_listener_pids", lambda _port: {654})
    monkeypatch.setattr(
        gameproc, "_windows_is_application_process", lambda _pid: False,
    )
    monkeypatch.setattr(gameproc, "_terminate_windows_process", stopped.append)

    gameproc.kill_listeners_on_port(1616)

    assert stopped == []
    assert "Port 1616 is held by PID 654" in caplog.text
    assert "leaving it running" in caplog.text


def test_posix_takeover_terminates_verified_application_listener(monkeypatch):
    terminated = []
    monkeypatch.setattr(gameproc, "_platform_name", lambda: "posix")
    monkeypatch.setattr(
        gameproc, "_posix_listener_pids", lambda _port: ({987}, set()),
    )
    monkeypatch.setattr(
        gameproc, "_posix_is_application_process", lambda _pid: True,
    )
    monkeypatch.setattr(gameproc, "_terminate_posix_process", terminated.append)

    gameproc.kill_listeners_on_port(1616)

    assert terminated == [987]


def test_windows_termination_escalates_graceful_taskkill_to_force(monkeypatch):
    taskkills = []
    waits = iter((False, True))
    wait_calls = []

    monkeypatch.setattr(
        gameproc,
        "_taskkill_windows_process",
        lambda pid, *, force: taskkills.append((pid, force)),
    )

    def wait_for_exit(pid, timeout):
        wait_calls.append((pid, timeout))
        return next(waits)

    monkeypatch.setattr(
        gameproc, "_wait_for_windows_process_exit", wait_for_exit,
    )
    monkeypatch.setattr(
        gameproc, "_windows_is_application_process", lambda _pid: True,
    )

    gameproc._terminate_windows_process(776)

    assert taskkills == [(776, False), (776, True)]
    assert wait_calls == [
        (776, gameproc._WINDOWS_TERM_TIMEOUT_SEC),
        (776, gameproc._WINDOWS_KILL_TIMEOUT_SEC),
    ]


def test_windows_taskkill_command_adds_force_only_for_escalation(monkeypatch):
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(gameproc.subprocess, "run", run)

    gameproc._taskkill_windows_process(776, force=False)
    gameproc._taskkill_windows_process(776, force=True)

    assert commands == [
        ["taskkill", "/PID", "776"],
        ["taskkill", "/PID", "776", "/F"],
    ]


def test_windows_escalation_refuses_a_reused_pid(monkeypatch):
    taskkills = []
    monkeypatch.setattr(
        gameproc,
        "_taskkill_windows_process",
        lambda pid, *, force: taskkills.append((pid, force)),
    )
    monkeypatch.setattr(
        gameproc,
        "_wait_for_windows_process_exit",
        lambda _pid, _timeout: False,
    )
    monkeypatch.setattr(
        gameproc, "_windows_is_application_process", lambda _pid: False,
    )

    gameproc._terminate_windows_process(779)

    assert taskkills == [(779, False)]


def test_posix_termination_escalates_sigterm_to_sigkill(monkeypatch):
    signals = []
    waits = iter((False, True))
    wait_calls = []

    monkeypatch.setattr(
        gameproc.os, "kill", lambda pid, sig: signals.append((pid, sig)),
    )

    def wait_for_exit(pid, timeout):
        wait_calls.append((pid, timeout))
        return next(waits)

    monkeypatch.setattr(gameproc, "_wait_for_process_exit", wait_for_exit)
    monkeypatch.setattr(
        gameproc, "_posix_is_application_process", lambda _pid: True,
    )

    gameproc._terminate_posix_process(777)

    assert signals == [(777, gameproc._SIGTERM), (777, gameproc._SIGKILL)]
    assert wait_calls == [
        (777, gameproc._POSIX_TERM_TIMEOUT_SEC),
        (777, gameproc._POSIX_KILL_TIMEOUT_SEC),
    ]


def test_posix_escalation_refuses_a_reused_pid(monkeypatch):
    signals = []
    monkeypatch.setattr(
        gameproc.os, "kill", lambda pid, sig: signals.append((pid, sig)),
    )
    monkeypatch.setattr(gameproc, "_wait_for_process_exit", lambda _pid, _timeout: False)
    monkeypatch.setattr(
        gameproc, "_posix_is_application_process", lambda _pid: False,
    )

    gameproc._terminate_posix_process(778)

    assert signals == [(778, gameproc._SIGTERM)]


def test_cleanup_never_raises_when_process_is_gone_or_port_is_free(monkeypatch):
    def gone(_pid, _signal):
        raise ProcessLookupError

    monkeypatch.setattr(gameproc.os, "kill", gone)
    gameproc._terminate_posix_process(123)

    monkeypatch.setattr(gameproc, "_platform_name", lambda: "posix")
    monkeypatch.setattr(
        gameproc, "_posix_listener_pids", lambda _port: (set(), set()),
    )
    gameproc.kill_listeners_on_port(1616)

    monkeypatch.setattr(
        gameproc,
        "_posix_listener_pids",
        lambda _port: (_ for _ in ()).throw(RuntimeError("inspection failed")),
    )
    gameproc.kill_listeners_on_port(1616)


def test_linux_proc_tables_map_listener_inode_to_pid(tmp_path, monkeypatch):
    proc_root = tmp_path / "proc"
    net_dir = proc_root / "net"
    fd_dir = proc_root / "456" / "fd"
    net_dir.mkdir(parents=True)
    fd_dir.mkdir(parents=True)
    header = "sl local_address rem_address st tx_queue tr retrnsmt uid timeout inode\n"
    listener = (
        "0: 0100007F:0650 00000000:0000 0A 00000000:00000000 "
        "00:00000000 00000000 1000 0 4242\n"
    )
    (net_dir / "tcp").write_text(header + listener, encoding="ascii")
    (net_dir / "tcp6").write_text(header, encoding="ascii")
    descriptor = fd_dir / "7"
    descriptor.write_text("", encoding="ascii")

    monkeypatch.setattr(
        gameproc.os,
        "readlink",
        lambda path: "socket:[4242]" if path == descriptor else "",
    )

    assert gameproc._linux_listening_socket_inodes(1616, proc_root) == {"4242"}
    assert gameproc._posix_listener_pids(1616, proc_root) == ({456}, set())


def test_application_identity_rule_is_strict_about_the_entry_point():
    entry = str(gameproc._APP_ENTRY_POINT)
    other = str(gameproc._APP_ROOT / "other.py")
    venv_python = str(gameproc._APP_VENV / "Scripts" / "python.exe")

    assert gameproc._command_runs_this_application(
        "python3.11", ["/usr/bin/python3.11", entry], cwd="/tmp",
    )
    assert gameproc._command_runs_this_application(
        "python.exe", [venv_python, "main.py"], executable=venv_python,
        windows=True,
    )
    assert not gameproc._command_runs_this_application(
        "python3.11", ["/usr/bin/python3.11", other], cwd=str(gameproc._APP_ROOT),
    )
    assert not gameproc._command_runs_this_application(
        "node.exe", ["node.exe", entry], cwd=str(gameproc._APP_ROOT),
    )
