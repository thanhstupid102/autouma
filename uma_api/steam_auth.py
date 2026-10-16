import json
import logging
import subprocess
import threading
from typing import Any

from core.runtime_paths import ensure_private_dir, resolve_state_root
from core.settings import Settings
from uma_api.device import DIR, check_deps, get_steam_machine_name


log = logging.getLogger(__name__)

__all__ = ["get_ticket", "QrLoginSession"]

LAST_TICKET_GEN_RESULT = None
_PROCESS_STOP_TIMEOUT_SECONDS = 2
_STEAM_USER_DATA_DIRNAME = "steam-user"


def _steam_user_data_dir():
    state_root = resolve_state_root(Settings.BASE_DIR).root
    return ensure_private_dir(state_root / _STEAM_USER_DATA_DIRNAME)


def get_ticket(u='', p='', c='', refresh_token=''):
    global LAST_TICKET_GEN_RESULT
    check_deps()
    script = str(Settings.JS_STEAM_TICKET_GEN)
    data_dir = _steam_user_data_dir()
    machine_name = get_steam_machine_name()
    cmd = [
        'node', script, '--', '--data-directory', str(data_dir),
        '--machine-name', machine_name,
    ]
    if refresh_token:
        cmd += ['--refresh-token', refresh_token]
    else:
        cmd += ['--username', u, '--password', p]
        if c:
            cmd += ['--code', c]

    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, cwd=DIR)
    LAST_TICKET_GEN_RESULT = {
        'stdout': proc.stdout,
        'stderr': proc.stderr,
        'returncode': proc.returncode,
    }
    if proc.returncode == 2:
        raise Exception('STEAM_GUARD_REQUIRED')
    if proc.returncode == 4:
        raise Exception('TOKEN_INVALID')

    out = proc.stdout.strip()
    if not out or proc.returncode != 0:
        error_msg = proc.stderr.strip() or 'fail'
        raise Exception(error_msg)

    line = out.split('\n')[-1].strip()
    line = line.removesuffix('\\n')
    try:
        d = json.loads(line)
        return d['steam_id'], d['session_ticket'], d.get('refresh_token', '')
    except Exception as e:
        log.error(f"[get_ticket] Failed to parse JSON: {e}. Output: {line}")
        raise Exception('bad json')

class QrLoginSession:
    """Runs qr_login.js and tracks its latest state. One per process."""

    def __init__(self):
        self.proc = None
        self.thread = None
        self.status = "idle"        # idle|starting|pending|confirmed|expired|error
        self.challenge_url = ""
        self.refresh_token = ""
        self.steam_id = ""
        self.error = ""
        self._lock = threading.Lock()
        self._gen = 0

    def start(self):
        check_deps()
        with self._lock:
            self._terminate_locked()
            self._gen += 1
            gen = self._gen
            self.status = "starting"
            self.challenge_url = ""
            self.refresh_token = ""
            self.steam_id = ""
            self.error = ""
        script = str(Settings.JS_STEAM_QR_LOGIN)
        machine_name = get_steam_machine_name()
        self.proc = subprocess.Popen(
            ['node', script, '--', '--machine-name', machine_name],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, cwd=DIR,
        )
        self.thread = threading.Thread(target=self._read_loop, args=(gen,), daemon=True)
        self.thread.start()

    def _read_loop(self, gen):
        # start() assigns self.proc (text-mode Popen, stdout=PIPE) on the line
        # directly above the Thread that runs this, so neither the handle nor
        # its stdout is ever None here -- an invariant mypy cannot see across
        # the thread hand-off. Typed Any rather than guarded, because a guard
        # would be a runtime change, not a typing one.
        proc: Any = self.proc
        try:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                # `line` is always a str (text-mode pipe + .strip()), so a bad
                # frame can only surface as JSONDecodeError (a ValueError).
                except ValueError:
                    continue
                kind = msg.get("type")
                with self._lock:
                    if self._gen != gen:
                        continue
                    if kind == "challenge":
                        self.challenge_url = msg.get("url", "")
                        self.status = "pending"
                    elif kind == "authenticated":
                        self.refresh_token = msg.get("refresh_token", "")
                        self.steam_id = msg.get("steam_id", "")
                        self.status = "confirmed"
                    elif kind == "error":
                        self.error = msg.get("message", "error")
                        self.status = "expired" if "timed out" in self.error.lower() else "error"
        finally:
            with self._lock:
                if self._gen == gen and self.status in ("starting", "pending"):
                    self.status = "error"
                    if not self.error:
                        self.error = "qr process ended"

    def snapshot(self):
        with self._lock:
            return {
                "status": self.status,
                "challenge_url": self.challenge_url,
                "steam_id": self.steam_id,
                "error": self.error,
            }

    def take_refresh_token(self):
        with self._lock:
            return self.refresh_token

    def _terminate_locked(self):
        proc = self.proc
        if proc is None:
            return
        try:
            if proc.poll() is not None:
                return
        except Exception:
            pass
        try:
            proc.terminate()
        except Exception:
            pass
        try:
            proc.wait(timeout=_PROCESS_STOP_TIMEOUT_SECONDS)
            return
        except subprocess.TimeoutExpired:
            pass
        except Exception:
            try:
                if proc.poll() is not None:
                    return
            except Exception:
                pass
        try:
            proc.kill()
        except Exception:
            pass
        try:
            proc.wait(timeout=_PROCESS_STOP_TIMEOUT_SECONDS)
        except Exception:
            pass

    def stop(self):
        with self._lock:
            self._terminate_locked()
            self._gen += 1
            if self.status in ("starting", "pending"):
                self.status = "error"
                if not self.error:
                    self.error = "QR login stopped"

