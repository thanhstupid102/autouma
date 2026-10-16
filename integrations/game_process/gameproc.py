import csv
import json
import logging
import os
import re
import shlex
import signal
import subprocess
import time
from pathlib import Path

from core.settings import Settings
from career_bot.delay import dna_sleep


log = logging.getLogger(__name__)

_APP_ROOT = Path(__file__).resolve().parents[2]
_APP_ENTRY_POINT = _APP_ROOT / "main.py"
_APP_VENV = _APP_ROOT / ".venv"
_PROC_ROOT = Path("/proc")
_WINDOWS_TERM_TIMEOUT_SEC = 1.0
_WINDOWS_KILL_TIMEOUT_SEC = 1.0
_POSIX_TERM_TIMEOUT_SEC = 1.0
_POSIX_KILL_TIMEOUT_SEC = 1.0
_POSIX_POLL_INTERVAL_SEC = 0.05
_SIGTERM = getattr(signal, "SIGTERM", 15)
_SIGKILL = getattr(signal, "SIGKILL", 9)


def set_console_topmost():
    if os.name != 'nt':
        return
    try:
        import ctypes
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if not hwnd:
            return
        ctypes.windll.user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002)
    except Exception:
        pass

def _platform_name():
    return os.name


def _port_from_local_address(address):
    try:
        return int(str(address).rsplit(":", 1)[1])
    except (IndexError, TypeError, ValueError):
        return None


def _windows_listener_pids(port):
    try:
        proc = subprocess.run(
            ['netstat', '-ano'],
            capture_output=True,
            text=True,
            timeout=5
        )
    except Exception as exc:
        log.warning(
            "Could not inspect port %s with netstat: %s",
            port,
            type(exc).__name__,
        )
        return set()

    current_pid = os.getpid()
    pids = set()
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        local_addr = parts[1]
        state = parts[3].upper() if len(parts) >= 5 else ''
        pid_text = parts[-1]
        if _port_from_local_address(local_addr) != port or state != 'LISTENING':
            continue
        try:
            pid = int(pid_text)
        except ValueError:
            continue
        if pid and pid != current_pid:
            pids.add(pid)
    return pids


def _windows_process_image(pid):
    try:
        proc = subprocess.run(
            ['tasklist', '/FI', f'PID eq {pid}', '/FO', 'CSV', '/NH'],
            capture_output=True,
            text=True,
            timeout=5,
        )
        row = next(csv.reader(proc.stdout.splitlines()), [])
        if len(row) < 2 or row[1].strip() != str(pid):
            return ""
        return row[0].strip()
    except Exception:
        return ""


def _windows_process_details(pid):
    image = _windows_process_image(pid)
    if not _is_python_image(image):
        return image, "", []
    command = (
        "$p = Get-CimInstance Win32_Process -Filter "
        f"'ProcessId = {int(pid)}'; "
        "if ($null -ne $p) { "
        "$p | Select-Object ExecutablePath,CommandLine | "
        "ConvertTo-Json -Compress }"
    )
    try:
        proc = subprocess.run(
            ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
            capture_output=True,
            text=True,
            timeout=5,
        )
        details = json.loads(proc.stdout.strip() or "{}")
        executable = str(details.get("ExecutablePath") or "")
        command_line = str(details.get("CommandLine") or "")
        argv = [part.strip('"\'') for part in shlex.split(command_line, posix=False)]
        return image, executable, argv
    except Exception:
        return image, "", []


def _is_python_image(image):
    name = Path(str(image or "")).name.lower()
    if name.endswith(".exe"):
        name = name[:-4]
    return re.fullmatch(r"(?:pythonw?|pypy)(?:\d+(?:\.\d+)*)?|py", name) is not None


def _same_path(left, right, *, case_insensitive=False):
    try:
        left_text = str(Path(left).resolve(strict=False))
        right_text = str(Path(right).resolve(strict=False))
    except (OSError, TypeError, ValueError):
        return False
    if case_insensitive:
        return left_text.casefold() == right_text.casefold()
    return left_text == right_text


def _path_is_within(path, parent, *, case_insensitive=False):
    try:
        path_text = str(Path(path).resolve(strict=False))
        parent_text = str(Path(parent).resolve(strict=False))
        if case_insensitive:
            path_text = path_text.casefold()
            parent_text = parent_text.casefold()
        return os.path.commonpath((path_text, parent_text)) == parent_text
    except (OSError, TypeError, ValueError):
        return False


def _python_invocation(argv):
    index = 1
    while index < len(argv):
        arg = str(argv[index])
        if arg == "-m":
            module = str(argv[index + 1]) if index + 1 < len(argv) else ""
            return "module", module
        if arg == "-c":
            return "code", ""
        if arg in {"-W", "-X", "--check-hash-based-pycs"}:
            index += 2
            continue
        if arg.startswith(("-W", "-X")) or arg.startswith("-"):
            index += 1
            continue
        return "script", arg
    return "", ""


def _command_runs_this_application(
    image, argv, *, cwd=None, executable="", windows=False,
):
    if not _is_python_image(image) or not argv:
        return False
    kind, target = _python_invocation(argv)
    if kind == "module":
        if target != "main":
            return False
        if cwd is not None:
            return _same_path(cwd, _APP_ROOT, case_insensitive=windows)
        return _path_is_within(
            executable, _APP_VENV, case_insensitive=windows,
        )
    if kind != "script" or not target:
        return False
    target_path = Path(target)
    if target_path.is_absolute():
        return _same_path(
            target_path, _APP_ENTRY_POINT, case_insensitive=windows,
        )
    if cwd is not None:
        return _same_path(
            Path(cwd) / target_path,
            _APP_ENTRY_POINT,
            case_insensitive=windows,
        )
    return target_path.name.lower() == "main.py" and _path_is_within(
        executable, _APP_VENV, case_insensitive=windows,
    )


def _windows_is_application_process(pid):
    image, executable, argv = _windows_process_details(pid)
    return _command_runs_this_application(
        image,
        argv,
        executable=executable,
        windows=True,
    )


def _taskkill_windows_process(pid, *, force):
    command = ['taskkill', '/PID', str(pid)]
    if force:
        command.append('/F')
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=5,
    )


def _windows_process_exists(pid):
    return bool(_windows_process_image(pid))


def _wait_for_windows_process_exit(pid, timeout):
    deadline = time.monotonic() + max(0.0, timeout)
    while _windows_process_exists(pid):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(_POSIX_POLL_INTERVAL_SEC, remaining))
    return True


def _terminate_windows_process(pid):
    try:
        _taskkill_windows_process(pid, force=False)
    except Exception as exc:
        log.warning(
            "Could not request graceful stop for PID %s: %s",
            pid,
            type(exc).__name__,
        )
    if _wait_for_windows_process_exit(pid, _WINDOWS_TERM_TIMEOUT_SEC):
        return
    if not _windows_is_application_process(pid):
        log.error(
            "PID %s changed identity after graceful taskkill; refusing to force it",
            pid,
        )
        return
    log.warning("PID %s ignored graceful taskkill; escalating to /F", pid)
    try:
        _taskkill_windows_process(pid, force=True)
    except Exception as exc:
        log.warning(
            "Could not force taskkill PID %s: %s",
            pid,
            type(exc).__name__,
        )
        return
    if not _wait_for_windows_process_exit(pid, _WINDOWS_KILL_TIMEOUT_SEC):
        log.error("PID %s is still running after forced taskkill wait", pid)


def _take_over_windows_port(port):
    verified = []
    for pid in sorted(_windows_listener_pids(port)):
        if _windows_is_application_process(pid):
            verified.append(pid)
            continue
        log.error(
            "Port %s is held by PID %s, but it is not a verified instance of "
            "this application; leaving it running. Stop it or choose another port.",
            port,
            pid,
        )

    if not verified:
        return
    log.warning(
        "Port %s already has stale application listener PID(s): %s; stopping them",
        port,
        ", ".join(map(str, verified)),
    )
    for pid in verified:
        try:
            if not _windows_is_application_process(pid):
                log.error(
                    "PID %s changed identity before taskkill; leaving it running",
                    pid,
                )
                continue
            _terminate_windows_process(pid)
        except Exception:
            pass
    dna_sleep(0.5, 0.5)


def _linux_listening_socket_inodes(port, proc_root=_PROC_ROOT):
    inodes = set()
    tables_read = 0
    for relative_path in ("net/tcp", "net/tcp6"):
        try:
            lines = (proc_root / relative_path).read_text(
                encoding="ascii", errors="replace",
            ).splitlines()
            tables_read += 1
        except OSError:
            continue
        for line in lines[1:]:
            parts = line.split()
            if len(parts) < 10 or parts[3].upper() != "0A":
                continue
            local_address = parts[1]
            try:
                local_port = int(local_address.rsplit(":", 1)[1], 16)
            except (IndexError, ValueError):
                continue
            if local_port == port:
                inodes.add(parts[9])
    if tables_read == 0:
        raise OSError("/proc/net/tcp and /proc/net/tcp6 are unavailable")
    return inodes


def _posix_listener_pids(port, proc_root=_PROC_ROOT):
    inodes = _linux_listening_socket_inodes(port, proc_root)
    if not inodes:
        return set(), set()
    current_pid = os.getpid()
    pids: set[int] = set()
    mapped_inodes: set[str] = set()
    try:
        process_dirs = list(proc_root.iterdir())
    except OSError:
        return pids, inodes
    for process_dir in process_dirs:
        if not process_dir.name.isdigit():
            continue
        pid = int(process_dir.name)
        if pid == current_pid:
            continue
        try:
            descriptors = list((process_dir / "fd").iterdir())
        except OSError:
            continue
        for descriptor in descriptors:
            try:
                target = os.readlink(descriptor)
            except OSError:
                continue
            if not target.startswith("socket:[") or not target.endswith("]"):
                continue
            inode = target[8:-1]
            if inode in inodes:
                pids.add(pid)
                mapped_inodes.add(inode)
    return pids, inodes - mapped_inodes


def _posix_process_details(pid, proc_root=_PROC_ROOT):
    try:
        raw = (proc_root / str(pid) / "cmdline").read_bytes()
        argv = [part.decode(errors="replace") for part in raw.split(b"\0") if part]
        cwd = os.readlink(proc_root / str(pid) / "cwd")
        image = Path(argv[0]).name if argv else ""
        return image, argv, cwd
    except OSError:
        return "", [], ""


def _posix_is_application_process(pid):
    image, argv, cwd = _posix_process_details(pid)
    return _command_runs_this_application(image, argv, cwd=cwd)


def _process_exists(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True


def _wait_for_process_exit(pid, timeout):
    deadline = time.monotonic() + max(0.0, timeout)
    while _process_exists(pid):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(_POSIX_POLL_INTERVAL_SEC, remaining))
    return True


def _terminate_posix_process(pid):
    try:
        os.kill(pid, _SIGTERM)
    except ProcessLookupError:
        return
    except OSError as exc:
        log.warning("Could not send SIGTERM to PID %s: %s", pid, type(exc).__name__)
        return
    if _wait_for_process_exit(pid, _POSIX_TERM_TIMEOUT_SEC):
        return
    if not _posix_is_application_process(pid):
        log.error(
            "PID %s changed identity after SIGTERM; refusing to send SIGKILL",
            pid,
        )
        return
    log.warning("PID %s ignored SIGTERM; escalating to SIGKILL", pid)
    try:
        os.kill(pid, _SIGKILL)
    except ProcessLookupError:
        return
    except OSError as exc:
        log.warning("Could not send SIGKILL to PID %s: %s", pid, type(exc).__name__)
        return
    if not _wait_for_process_exit(pid, _POSIX_KILL_TIMEOUT_SEC):
        log.error("PID %s is still running after SIGKILL wait", pid)


def _take_over_posix_port(port):
    try:
        pids, unmapped_inodes = _posix_listener_pids(port)
    except OSError as exc:
        log.warning(
            "Could not inspect POSIX listeners on port %s: %s",
            port,
            str(exc),
        )
        return
    for inode in sorted(unmapped_inodes):
        log.error(
            "Port %s has listener socket inode %s, but its PID could not be "
            "identified; leaving it running. Stop it or choose another port.",
            port,
            inode,
        )
    for pid in sorted(pids):
        if not _posix_is_application_process(pid):
            log.error(
                "Port %s is held by PID %s, but it is not a verified instance of "
                "this application; leaving it running. Stop it or choose another port.",
                port,
                pid,
            )
            continue
        log.warning(
            "Port %s already has stale application listener PID %s; stopping it",
            port,
            pid,
        )
        _terminate_posix_process(pid)


def kill_listeners_on_port(port):
    """Best-effort stop stale instances of this app that own ``port``.

    Unknown processes are never killed. Inspection and termination failures are
    logged and swallowed so uvicorn can report the eventual bind failure.
    """
    try:
        if _platform_name() == 'nt':
            _take_over_windows_port(port)
        elif _platform_name() == 'posix':
            _take_over_posix_port(port)
    except Exception as exc:
        log.warning(
            "Port %s cleanup failed before bind: %s",
            port,
            type(exc).__name__,
        )


def parse_cli_args(argv):
    # Usage: python main.py [PORT] [--host HOST] [--account NAME] [--debug]
    # --account NAME selects the startup account whose saved credentials and
    # Steam refresh token should be loaded before the UI starts.
    # --debug traces every API request/response under the selected state root.
    port = None
    host = None
    account = Settings.SWEEP_ACCOUNT
    debug = False
    args = list(argv)
    i = 0
    while i < len(args):
        a = str(args[i]).strip()
        if a in ("--account", "-a") and i + 1 < len(args):
            account = str(args[i + 1]).strip() or account
            i += 2
            continue
        if a == "--host" and i + 1 < len(args):
            host = str(args[i + 1]).strip() or host
            i += 2
            continue
        if a == "--debug":
            debug = True
        elif a.isdigit() and port is None and 1 <= int(a) <= 65535:
            port = int(a)
        i += 1
    if port is None:
        env = Settings.SWEEPY_PORT
        port = int(env) if env is not None and env.isdigit() and 1 <= int(env) <= 65535 else 1616
    if host is None:
        env_host = Settings.SWEEPY_HOST
        host = str(env_host).strip() if env_host is not None and str(env_host).strip() else "127.0.0.1"
    return port, account, debug, host


def enable_api_trace():
    """Turn on full API request/response tracing (--debug / UMA_TRACE=1).

    Settings.UMA_TRACE is snapshotted from the env at import time, so a CLI
    flag arriving later must overwrite the class attribute (make_client
    checks Settings.UMA_TRACE at client-creation time) as well as the env
    (so any child process / re-import sees it too).
    """
    os.environ["UMA_TRACE"] = "1"
    Settings.UMA_TRACE = "1"
    from core.runtime_paths import resolve_state_root

    trace_dir = resolve_state_root(Settings.BASE_DIR).trace_logs_dir
    log.info(
        f"--debug: tracing all API requests/responses to "
        f"{trace_dir / 'api_payloads'}"
    )
