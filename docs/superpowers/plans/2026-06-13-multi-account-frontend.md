# Multi-Account on Frontend — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the single-account-per-process server into one multi-tenant server that runs many accounts' careers in parallel, adds accounts from the UI (Steam QR or frida capture), and imports/exports passphrase-encrypted account bundles between machines.

**Architecture:** Bundle the per-account module globals in `main.py` into a `Session` object, managed by a `SessionManager`. Every request selects its account via an `X-Account` header resolved by a FastAPI dependency. Shared data maps and the preset stores stay module-level. The frontend gets an account zustand store that injects the header, an Overview grid, a sidebar switcher, and an Add/Import/Export account modal.

**Tech Stack:** Python 3.10+, FastAPI, `frida`, `pycryptodome` (already a dep — AES-GCM), `threading`; React + TypeScript + Vite + TanStack Query + zustand + shadcn/ui; vitest + pytest.

**Spec:** `docs/superpowers/specs/2026-06-13-multi-account-frontend-design.md`

> **Reconciliation note (2026-06-14).** Audited against current HEAD after the recent
> delay/runner/events commits. Three corrections were folded in below:
> 1. **turn-delay is shared, not per-account, and lives in `career_bot/delay`.** The
>    delay logic (`ZERO_DELAY_ENDPOINTS`, `ENDPOINT_DELAY_MULT = {"gain_skills": 0.5}`,
>    `turn_delay` now always returns 0) is module-level in `career_bot/delay.py`. The
>    `turn_delay_*` names at `main.py:203-207` are now vestigial but still sit *inside*
>    the globals block (185-214) — do **not** sweep them out with the per-account globals.
> 2. **Career-log filenames are built in `career_bot/report.py`, not `runner.py`** — see
>    the corrected Task 19.
> 3. **Verified current line anchors** (main.py is at HEAD, 2577 lines). Anchors below were
>    refreshed; treat all `~NNN` as approximate — the executor should `grep` to confirm.

---

## File Structure

**Backend (new):**
- `uma_api/session.py` — `Session` dataclass + `SessionManager` (registry, lazy login, snapshot_all, add/remove, add-account lock).
- `uma_api/account_io.py` — account bundle export/import: PBKDF2 + AES-GCM encrypt/decrypt, file read/write, collision handling.
- `tests/test_session_manager.py`, `tests/test_account_io.py`.

**Backend (modified):**
- `main.py` — replace per-account globals with `Session`; add `get_session` dependency; migrate 52 endpoints; new endpoints (`/api/accounts`, add/remove/export/import); per-session capture/backoff/logs.
- `career_bot/report.py` — `write_report` gains an `account` arg for account-scoped `career_log_<account>_<ts>.json` + `latest_career_log_<account>.json` (Task 19).
- `career_bot/runner.py` — `CareerRunner.start` captures the run's account and passes it to `write_report` (Task 19).

**Frontend (new):**
- `frontend/src/stores/account.ts` — zustand store: account list, `selectedAccount`, setters.
- `frontend/src/api/accounts.ts` — typed calls for the new endpoints.
- `frontend/src/hooks/useAccounts.ts` — polls `/api/accounts`.
- `frontend/src/pages/Overview.tsx` — account grid (landing).
- `frontend/src/components/accounts/AccountCard.tsx` — one grid card.
- `frontend/src/components/accounts/AddAccountDialog.tsx` — QR + frida tabs.
- `frontend/src/components/accounts/ImportExportControls.tsx` — export/import w/ passphrase.
- `frontend/src/components/accounts/AccountSwitcher.tsx` — sidebar list.
- Tests: `account.test.ts`, `AddAccountDialog.test.tsx`.

**Frontend (modified):**
- `frontend/src/api/client.ts` — inject `X-Account` header.
- `frontend/src/App.tsx` — add `/` Overview route, move dashboard to `/account/:name`.
- `frontend/src/components/layout/Sidebar.tsx` — mount `AccountSwitcher`.

---

## Phase 1 — Backend Session model

### Task 1: `Session` dataclass

**Files:**
- Create: `uma_api/session.py`
- Test: `tests/test_session_manager.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_session_manager.py
from uma_api.session import Session

def test_session_defaults():
    s = Session(name="acc1")
    assert s.name == "acc1"
    assert s.client is None
    assert s.account is None
    assert s.dashboard_data is None
    assert s.start_state == {}
    assert s.parent_cards == {}
    assert s.parent_rank_points == {}
    assert s.raw_load_index_response is None
    assert s.selection == {"deck": None, "friend": None, "trainee": None, "veterans": []}
    assert s.runner is not None            # own CareerRunner instance
    assert s.loop_thread is None
    assert s.loop_stop is False
    assert s.active_preset is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_session_manager.py::test_session_defaults -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'uma_api.session'`

- [ ] **Step 3: Write minimal implementation**

```python
# uma_api/session.py
import threading
from dataclasses import dataclass, field
from typing import Any, Optional

from career_bot.runner import CareerRunner


def _default_selection() -> dict:
    return {"deck": None, "friend": None, "trainee": None, "veterans": []}


@dataclass
class Session:
    """All per-account runtime state. One per Uma account."""
    name: str
    base_dir: str = "."
    client: Any = None
    account: Optional[dict] = None
    dashboard_data: Optional[dict] = None
    start_state: dict = field(default_factory=dict)
    parent_cards: dict = field(default_factory=dict)
    parent_rank_points: dict = field(default_factory=dict)
    selection: dict = field(default_factory=_default_selection)
    raw_load_index_response: Any = None
    pending_game_auth_config: dict = field(default_factory=dict)
    # run loop
    runner: CareerRunner = None
    loop_thread: Optional[threading.Thread] = None
    loop_stop: bool = False
    active_preset: Optional[str] = None
    # capture status (per-account)
    capture_status: dict = field(default_factory=lambda: {
        "capturing": False, "ok": None, "message": "idle", "viewer_id": None})
    capture_lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self):
        if self.runner is None:
            self.runner = CareerRunner(self.base_dir)

    def reset_runtime(self):
        """Clear logged-in state (mirrors the login() global reset)."""
        self.client = None
        self.account = None
        self.dashboard_data = None
        self.start_state = {}
        self.parent_cards = {}
        self.parent_rank_points = {}
        self.raw_load_index_response = None
        self.selection = _default_selection()

    def loop_active(self) -> bool:
        return bool(self.loop_thread and self.loop_thread.is_alive())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_session_manager.py::test_session_defaults -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add uma_api/session.py tests/test_session_manager.py
git commit -m "feat(session): add per-account Session dataclass"
```

### Task 2: `SessionManager`

**Files:**
- Modify: `uma_api/session.py`
- Test: `tests/test_session_manager.py`

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_session_manager.py
from uma_api.session import Session, SessionManager

def test_manager_get_creates_lazily():
    mgr = SessionManager(base_dir=".")
    s = mgr.get("acc1")
    assert isinstance(s, Session)
    assert mgr.get("acc1") is s          # same instance on second call

def test_manager_list_and_remove():
    mgr = SessionManager(base_dir=".")
    mgr.get("a"); mgr.get("b")
    assert set(mgr.names()) == {"a", "b"}
    mgr.remove("a")
    assert set(mgr.names()) == {"b"}

def test_manager_snapshot_all_shape():
    mgr = SessionManager(base_dir=".")
    mgr.get("a")
    snaps = mgr.snapshot_all()
    assert isinstance(snaps, list)
    assert snaps[0]["name"] == "a"
    assert "running" in snaps[0]
    assert "logged_in" in snaps[0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_session_manager.py -v`
Expected: FAIL — `ImportError: cannot import name 'SessionManager'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to uma_api/session.py
import os
import glob


class SessionManager:
    """Owns every Session. Serializes add-account operations."""

    def __init__(self, base_dir: str = "."):
        self.base_dir = base_dir
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()
        self.add_lock = threading.Lock()   # frida/QR add-account serialization

    def accounts_dir(self) -> str:
        return os.path.join(self.base_dir, "uma_runtime", "accounts")

    def known_account_names(self) -> list[str]:
        """Account names persisted on disk (<name>.json, excluding .steam.json)."""
        pattern = os.path.join(self.accounts_dir(), "*.json")
        names = []
        for path in glob.glob(pattern):
            base = os.path.basename(path)
            if base.endswith(".steam.json"):
                continue
            names.append(base[:-len(".json")])
        return sorted(names)

    def get(self, name: str) -> Session:
        with self._lock:
            s = self._sessions.get(name)
            if s is None:
                s = Session(name=name, base_dir=self.base_dir)
                self._sessions[name] = s
            return s

    def names(self) -> list[str]:
        with self._lock:
            return sorted(self._sessions.keys())

    def remove(self, name: str):
        with self._lock:
            s = self._sessions.pop(name, None)
        if s is not None:
            s.loop_stop = True
            try:
                s.runner.stop()
            except Exception:
                pass

    def snapshot_all(self) -> list[dict]:
        with self._lock:
            sessions = dict(self._sessions)
        out = []
        # Union of in-memory sessions and on-disk accounts not yet loaded.
        names = set(sessions) | set(self.known_account_names())
        for name in sorted(names):
            s = sessions.get(name)
            if s is None:
                out.append({"name": name, "logged_in": False, "running": False,
                            "loop_active": False, "account": None, "runner": None})
                continue
            snap = s.runner.snapshot()
            out.append({
                "name": name,
                "logged_in": s.client is not None,
                "running": bool(snap.get("running")),
                "loop_active": s.loop_active(),
                "account": s.account,
                "runner": snap,
            })
        return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_session_manager.py -v`
Expected: PASS (3 manager tests + Session test)

- [ ] **Step 5: Commit**

```bash
git add uma_api/session.py tests/test_session_manager.py
git commit -m "feat(session): add SessionManager with registry and snapshot_all"
```

---

## Phase 2 — Header routing dependency + endpoint migration

> This phase rewrites `main.py`. The crux: replace the per-account module globals
> (`active_client`, `active_account`, `active_dashboard_data`, `active_start_state`,
> `active_parent_cards`, `active_parent_rank_points`, `active_selection`,
> `raw_load_index_response`, `pending_game_auth_config`, `qr_login_session`,
> `auth_capture_status`/`auth_capture_lock`, `backend_loop_thread`/`backend_loop_stop`,
> single `career_runner`) with fields on the request's `Session`.

### Task 3: Instantiate the manager and the `get_session` dependency

**Files:**
- Modify: `main.py` (globals block near line 185-214; add dependency below the `app = FastAPI()` line)

- [ ] **Step 1: Add the manager + dependency**

Replace the per-account globals declaration region (`active_client = None` … `career_runner = CareerRunner(DIR)` around `main.py:185-214`) so the **shared** items stay and the **per-account** ones move into the manager. Add:

```python
# main.py — near the other globals
from fastapi import Header
from uma_api.session import Session, SessionManager

session_manager = SessionManager(base_dir=str(DIR))

# Default account from CLI/env preserves single-account launch (back-compat).
DEFAULT_ACCOUNT = os.environ.get("SWEEPY_ACCOUNT") or ""


def get_session(x_account: str = Header(default="")) -> Session:
    name = x_account or DEFAULT_ACCOUNT
    if not name:
        raise HTTPException(status_code=400, detail="No account selected (missing X-Account header)")
    return session_manager.get(name)
```

Keep shared module globals: `chara_map`, `support_map`, `skill_data`, `factor_map`,
`race_map`, `succession_*`, `preset_store`, `race_preset_store`, `master_data`. **Delete**
the per-account globals listed in the Phase 2 note (they now live on `Session`).

> ⚠️ **Preserve the turn-delay globals.** `turn_delay_min_sec`, `turn_delay_max_sec`,
> `turn_delay_restore_min_sec`, `turn_delay_restore_max_sec`, `turn_delay_disabled` sit at
> `main.py:203-207` — *inside* the 185-214 globals block but they are **shared settings,
> not per-account state**. Do not delete them when removing the per-account globals.
> Leave the helpers `normalize_turn_delay` (~263), `set_turn_delay` (~273),
> `get_turn_delay` (~284) and the endpoints at `~921-927` unchanged — none take a session;
> `set/get_turn_delay` mutate `career_bot.delay` module attributes. (They are largely
> vestigial now that `career_bot/delay.py` owns the live delay logic, but removing them is
> a separate, deliberate cleanup — out of scope here.)

- [ ] **Step 2: Verify import + boot**

Run: `python -c "import main"`
Expected: no `NameError`/`ImportError`. (Endpoints still reference old globals → they will be fixed task-by-task next; do this step only to confirm the new symbols import.)

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat(api): add SessionManager instance and get_session dependency"
```

### Task 4: Convert shared helpers to take an explicit `session`

**Files:**
- Modify: `main.py` — helper functions that currently read/write per-account globals: `get_account_status` (line ~742), `update_start_state` (~295), `start_career_from_request` (~1100), `apply_career_result` (~1382), `manage_career_loop` (~1792). 

- [ ] **Step 1: Apply the conversion pattern to each helper**

For every helper that touched a per-account global, add a `session: Session` parameter and replace the global with the field. Pattern (real example — `update_start_state`):

```python
# BEFORE
def update_start_state(data):
    global active_start_state
    active_start_state = {...}

# AFTER
def update_start_state(session: Session, data):
    session.start_state = {...}
```

Pattern for `get_account_status` (reads `active_client`):

```python
# BEFORE
def get_account_status(data, career_data=None):
    tp_info = data.get('tp_info') or (active_client.tp_info if active_client else {})
    ...
# AFTER
def get_account_status(session: Session, data, career_data=None):
    client = session.client
    tp_info = data.get('tp_info') or (client.tp_info if client else {})
    ...
```

Update every call site of these helpers to pass `session`.

- [ ] **Step 2: Verify import**

Run: `python -c "import main"`
Expected: no error.

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "refactor(api): thread Session through shared helpers"
```

### Task 5: Migrate the simple read/status endpoints

**Files:**
- Modify: `main.py` — endpoints that only read per-account state, e.g. `/api/session` (GET), `/api/session/refresh`, `/api/career/friends`, dashboard/status getters. (Group A.)

- [ ] **Step 1: Apply the endpoint conversion pattern**

For each endpoint, add `session: Session = Depends(get_session)` and replace globals. Real example (`/api/career/friends`, currently `main.py:2030`):

```python
# BEFORE
@app.post("/api/career/friends")
async def get_friend_list(req: FriendListRequest):
    global active_client, active_dashboard_data, active_account
    if not active_client:
        return {"success": False, "detail": "Not logged in"}
    if active_account and active_account.get("career") ...
        ...
    result = active_client.pre_single_mode(req.exclude_viewer_ids)
    ...

# AFTER
@app.post("/api/career/friends")
async def get_friend_list(req: FriendListRequest, session: Session = Depends(get_session)):
    if not session.client:
        return {"success": False, "detail": "Not logged in"}
    if session.account and session.account.get("career") and session.account["career"].get("active"):
        ...
    result = session.client.pre_single_mode(req.exclude_viewer_ids)
    update_start_state(session, result.get('data', {}))
    ...
```

Rule: `active_client→session.client`, `active_account→session.account`,
`active_dashboard_data→session.dashboard_data`, `active_start_state→session.start_state`,
`active_parent_cards→session.parent_cards`, `active_parent_rank_points→session.parent_rank_points`,
`active_selection→session.selection`, `raw_load_index_response→session.raw_load_index_response`.
Delete the `global` declarations.

- [ ] **Step 2: Verify import + a smoke request**

Run: `python -c "import main"` then start the server and:
`curl -s -H "X-Account: lewpie" http://127.0.0.1:1616/api/session | head -c 200`
Expected: JSON (not a 500 from a `NameError`).

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "refactor(api): migrate read/status endpoints to Session"
```

### Task 6: Migrate the career-run endpoints + per-session loop

**Files:**
- Modify: `main.py` — `/api/career/run` (~1869), `/api/career/runner` (~1959), `/api/career/runner/stop|pause|resume` (~1980-1996), `manage_career_loop` (~1792), `start_career_from_request` (~1100). (Group B.)

- [ ] **Step 1: Move the loop thread + runner onto the session**

`manage_career_loop` uses `backend_loop_stop`/`active_client`/`career_runner`. Convert it to operate on a passed `session`:

```python
# AFTER (shape)
def manage_career_loop(session: Session, req, preset, initial_result):
    runner = session.runner
    current_result = initial_result
    runs_done = 0
    target = ...  # unchanged logic, but read session.loop_stop instead of global
    while not session.loop_stop:
        runner.set_loop_info(runs_done + 1, target)
        runner.start(session.client, preset, current_result, max_steps,
                     burn_clocks=req.burn_clocks, dev_mode=True, account=session.name)
        while runner.snapshot().get("running"):
            if session.loop_stop:
                runner.stop()
                break
            time.sleep(0.5)
        ...
```

`/api/career/run` starts the thread on the session:

```python
@app.post("/api/career/run")
async def run_career(req: RunCareerRequest, session: Session = Depends(get_session)):
    if session.runner.snapshot().get("running") or session.loop_active():
        return {"success": False, "detail": "Already running"}
    ...
    session.loop_stop = False
    session.loop_thread = threading.Thread(
        target=manage_career_loop, args=(session, req, preset, result), daemon=True)
    session.loop_thread.start()
    return {"success": True, "account": account, "runner": session.runner.snapshot()}
```

stop/pause/resume:

```python
@app.post("/api/career/runner/stop")
async def runner_stop(session: Session = Depends(get_session)):
    session.loop_stop = True
    session.runner.stop()
    return {"success": True, "runner": session.runner.snapshot()}
```

- [ ] **Step 2: Verify two accounts run in parallel**

Start the server, then (with two real captured accounts):
```bash
curl -s -XPOST -H "X-Account: lewpie" http://127.0.0.1:1616/api/career/run -d '{"runs":1}'
curl -s -XPOST -H "X-Account: yuko"   http://127.0.0.1:1616/api/career/run -d '{"runs":1}'
curl -s -H "X-Account: lewpie" http://127.0.0.1:1616/api/career/runner
curl -s -H "X-Account: yuko"   http://127.0.0.1:1616/api/career/runner
```
Expected: both report `running: true` independently.

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "refactor(api): per-session career loop, parallel runs"
```

### Task 7: Migrate login / QR / recapture to per-session

**Files:**
- Modify: `main.py` — `/api/login` (~1447), `/api/logout`, `/api/steam/qr/start|poll` (~1407-1445), `/api/auth/recapture` + `_run_recapture` + `auth_capture_status` (~2007-2046). (Group C.)

- [ ] **Step 1: Convert login + logout**

`login` resets globals → call `session.reset_runtime()` and set `session.client`/`session.account` instead. Load saved config with `load_account_config(session.name)`. Replace `os.environ.get("SWEEPY_ACCOUNT")` with `session.name`. `save_steam_token(session.name, ...)` unchanged (already name-keyed).

- [ ] **Step 2: Convert QR + recapture to per-session, hold the manager add-lock**

```python
@app.post("/api/steam/qr/start")
async def steam_qr_start(session: Session = Depends(get_session)):
    from uma_api.client import QrLoginSession
    if not session_manager.add_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Another account add is in progress")
    try:
        session._qr = getattr(session, "_qr", None) or QrLoginSession()
        session._qr.start()
        ...  # same poll-for-challenge loop
    finally:
        # released on poll-confirm/expiry; for start, release immediately after kicking off
        session_manager.add_lock.release()
```

Recapture: drop the global gate that blocks while *any* run is active; instead block
only the **target** session's own run:

```python
@app.post("/api/auth/recapture")
async def recapture_auth(session: Session = Depends(get_session)):
    if session.runner.snapshot().get("running") or session.loop_active():
        return {"success": False, "detail": "Stop THIS account's run first — re-capture closes the game."}
    with session.capture_lock:
        if session.capture_status.get("capturing"):
            return {"success": False, "detail": "Already capturing.", "capture": dict(session.capture_status)}
        session.capture_status = {"capturing": True, "ok": None,
            "message": "Launching game — switch to your target Uma account and reach home (<=180s).",
            "viewer_id": None}
    threading.Thread(target=_run_recapture, args=(session,), daemon=True).start()
    return {"success": True, "capture": dict(session.capture_status)}
```

`_run_recapture(session)` writes `session.capture_status` and `session.pending_game_auth_config`.

- [ ] **Step 3: Verify import + login one account**

Run: `python -c "import main"`, start server, login an existing account via the UI or curl; confirm `/api/session` returns it.
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "refactor(api): per-session login, QR, recapture"
```

### Task 8: Sweep — confirm no per-account globals remain

**Files:**
- Modify: `main.py` (any stragglers in the remaining endpoints — presets/skills/events/discord stay shared and need no `session`).

- [ ] **Step 1: Grep for leftover references**

Run:
```bash
grep -nE "\b(active_client|active_account|active_dashboard_data|active_start_state|active_parent_cards|active_parent_rank_points|active_selection|raw_load_index_response|backend_loop_thread|backend_loop_stop)\b" main.py
```
Expected: **zero matches** (all now `session.*`). Fix any remaining hit using the Task 5 rule.

- [ ] **Step 2: Verify import + full pytest**

Run: `python -c "import main" && python -m pytest tests/ -q`
Expected: import OK; existing tests pass.

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "refactor(api): remove all per-account globals"
```

---

## Phase 3 — Account management endpoints

### Task 9: `GET /api/accounts` overview

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Add the endpoint**

```python
@app.get("/api/accounts")
async def list_accounts():
    return {"success": True, "accounts": session_manager.snapshot_all()}
```

- [ ] **Step 2: Verify**

Run: start server, `curl -s http://127.0.0.1:1616/api/accounts`
Expected: `{"success": true, "accounts": [{"name": "...", "logged_in": ...}, ...]}` listing on-disk accounts.

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat(api): GET /api/accounts overview"
```

### Task 10: `DELETE /api/accounts/{name}`

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Add the endpoint**

```python
@app.delete("/api/accounts/{name}")
async def delete_account(name: str):
    session_manager.remove(name)
    accounts_dir = session_manager.accounts_dir()
    removed = []
    for suffix in (".json", ".steam.json"):
        path = os.path.join(accounts_dir, name + suffix)
        if os.path.exists(path):
            os.remove(path); removed.append(os.path.basename(path))
    return {"success": True, "removed": removed}
```

- [ ] **Step 2: Verify**

Run: create a throwaway `uma_runtime/accounts/zzz.json`, `curl -XDELETE http://127.0.0.1:1616/api/accounts/zzz`
Expected: `{"success": true, "removed": ["zzz.json"]}` and file gone.

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat(api): DELETE /api/accounts/{name}"
```

---

## Phase 4 — Import / Export (encrypted)

### Task 11: `account_io` crypto round-trip

**Files:**
- Create: `uma_api/account_io.py`
- Test: `tests/test_account_io.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_account_io.py
import json
from uma_api.account_io import encrypt_bundle, decrypt_bundle, BadPassphrase
import pytest

def test_roundtrip():
    payload = {"acc1": {"game": {"viewer_id": 1, "auth_key": "k"},
                        "steam": {"refresh_token": "t", "steam_id": "s"}}}
    blob = encrypt_bundle(payload, "hunter2")
    assert isinstance(blob, (bytes, bytearray))
    out = decrypt_bundle(blob, "hunter2")
    assert out == payload

def test_wrong_passphrase_raises():
    blob = encrypt_bundle({"a": {"game": {}, "steam": {}}}, "right")
    with pytest.raises(BadPassphrase):
        decrypt_bundle(blob, "wrong")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_account_io.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'uma_api.account_io'`

- [ ] **Step 3: Write the implementation**

```python
# uma_api/account_io.py
import json
import os
import struct
from Crypto.Cipher import AES
from Crypto.Protocol.KDF import PBKDF2
from Crypto.Hash import SHA256

MAGIC = b"UMAACCT1"
_PBKDF2_ITERS = 200_000
_SALT_LEN = 16
_NONCE_LEN = 12
_KEY_LEN = 32


class BadPassphrase(Exception):
    pass


def _derive(passphrase: str, salt: bytes) -> bytes:
    return PBKDF2(passphrase.encode("utf-8"), salt, dkLen=_KEY_LEN,
                  count=_PBKDF2_ITERS, hmac_hash_module=SHA256)


def encrypt_bundle(payload: dict, passphrase: str) -> bytes:
    raw = json.dumps(payload).encode("utf-8")
    salt = os.urandom(_SALT_LEN)
    nonce = os.urandom(_NONCE_LEN)
    key = _derive(passphrase, salt)
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    ct, tag = cipher.encrypt_and_digest(raw)
    # MAGIC | salt | nonce | tag(16) | ciphertext
    return MAGIC + salt + nonce + tag + ct


def decrypt_bundle(blob: bytes, passphrase: str) -> dict:
    if blob[:len(MAGIC)] != MAGIC:
        raise BadPassphrase("Not a valid account bundle")
    off = len(MAGIC)
    salt = blob[off:off + _SALT_LEN]; off += _SALT_LEN
    nonce = blob[off:off + _NONCE_LEN]; off += _NONCE_LEN
    tag = blob[off:off + 16]; off += 16
    ct = blob[off:]
    key = _derive(passphrase, salt)
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    try:
        raw = cipher.decrypt_and_verify(ct, tag)
    except ValueError:
        raise BadPassphrase("Wrong passphrase or corrupted bundle")
    return json.loads(raw.decode("utf-8"))


def read_account_files(accounts_dir: str, name: str) -> dict:
    """Return {'game': <name>.json, 'steam': <name>.steam.json or None}."""
    out = {}
    game_path = os.path.join(accounts_dir, name + ".json")
    steam_path = os.path.join(accounts_dir, name + ".steam.json")
    if not os.path.exists(game_path):
        raise FileNotFoundError(f"Account '{name}' not found")
    with open(game_path, "r", encoding="utf-8") as f:
        out["game"] = json.load(f)
    if os.path.exists(steam_path):
        with open(steam_path, "r", encoding="utf-8") as f:
            out["steam"] = json.load(f)
    else:
        out["steam"] = None
    return out


def write_account_files(accounts_dir: str, name: str, data: dict):
    os.makedirs(accounts_dir, exist_ok=True)
    with open(os.path.join(accounts_dir, name + ".json"), "w", encoding="utf-8") as f:
        json.dump(data["game"], f)
    if data.get("steam") is not None:
        with open(os.path.join(accounts_dir, name + ".steam.json"), "w", encoding="utf-8") as f:
            json.dump(data["steam"], f)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_account_io.py -v`
Expected: PASS (both tests)

- [ ] **Step 5: Commit**

```bash
git add uma_api/account_io.py tests/test_account_io.py
git commit -m "feat(account-io): AES-GCM account bundle encrypt/decrypt"
```

### Task 12: Export / Import endpoints

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Add the models + endpoints**

```python
from fastapi import UploadFile, File, Form
from fastapi.responses import Response
from uma_api import account_io

class ExportRequest(BaseModel):
    names: list[str]
    passphrase: str

@app.post("/api/accounts/export")
async def export_accounts(req: ExportRequest):
    accounts_dir = session_manager.accounts_dir()
    payload = {}
    for name in req.names:
        payload[name] = account_io.read_account_files(accounts_dir, name)
    blob = account_io.encrypt_bundle(payload, req.passphrase)
    return Response(content=blob, media_type="application/octet-stream",
                    headers={"Content-Disposition": 'attachment; filename="accounts.umaacct"'})

@app.post("/api/accounts/import")
async def import_accounts(passphrase: str = Form(...), overwrite: bool = Form(False),
                          file: UploadFile = File(...)):
    blob = await file.read()
    try:
        payload = account_io.decrypt_bundle(blob, passphrase)
    except account_io.BadPassphrase as e:
        raise HTTPException(status_code=400, detail=str(e))
    accounts_dir = session_manager.accounts_dir()
    imported, skipped = [], []
    for name, data in payload.items():
        exists = os.path.exists(os.path.join(accounts_dir, name + ".json"))
        if exists and not overwrite:
            skipped.append(name); continue
        account_io.write_account_files(accounts_dir, name, data)
        imported.append(name)
    return {"success": True, "imported": imported, "skipped": skipped}
```

- [ ] **Step 2: Verify round-trip over HTTP**

Run: start server,
```bash
curl -s -XPOST http://127.0.0.1:1616/api/accounts/export -H "Content-Type: application/json" \
  -d '{"names":["lewpie"],"passphrase":"pw"}' -o /tmp/accounts.umaacct
curl -s -XPOST http://127.0.0.1:1616/api/accounts/import \
  -F passphrase=pw -F overwrite=false -F file=@/tmp/accounts.umaacct
```
Expected: export writes a binary file; import returns `{"success": true, "imported": [], "skipped": ["lewpie"]}` (already exists). Delete + re-import → `"imported": ["lewpie"]`.

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat(api): encrypted account export/import endpoints"
```

---

## Phase 5 — Frontend: account store + header injection

### Task 13: Inject `X-Account` header

**Files:**
- Modify: `frontend/src/api/client.ts`
- Create: `frontend/src/stores/account.ts`
- Test: `frontend/src/stores/account.test.ts`

- [ ] **Step 1: Write the failing store test**

```typescript
// frontend/src/stores/account.test.ts
import { describe, it, expect, beforeEach } from 'vitest'
import { useAccountStore, getSelectedAccount } from './account'

describe('account store', () => {
  beforeEach(() => useAccountStore.setState({ accounts: [], selected: '' }))

  it('selects an account and exposes it to the api layer', () => {
    useAccountStore.getState().setSelected('lewpie')
    expect(useAccountStore.getState().selected).toBe('lewpie')
    expect(getSelectedAccount()).toBe('lewpie')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/stores/account.test.ts`
Expected: FAIL — cannot resolve `./account`.

- [ ] **Step 3: Write the store**

```typescript
// frontend/src/stores/account.ts
import { create } from 'zustand'

export interface AccountSnapshot {
  name: string
  logged_in: boolean
  running: boolean
  loop_active: boolean
  account: unknown | null
  runner: unknown | null
}

interface AccountStore {
  accounts: AccountSnapshot[]
  selected: string
  setAccounts: (a: AccountSnapshot[]) => void
  setSelected: (name: string) => void
}

export const useAccountStore = create<AccountStore>()((set) => ({
  accounts: [],
  selected: '',
  setAccounts: (accounts) => set({ accounts }),
  setSelected: (selected) => set({ selected }),
}))

/** Read the current selection outside React (used by the api client). */
export function getSelectedAccount(): string {
  return useAccountStore.getState().selected
}
```

- [ ] **Step 4: Inject the header in `apiJson`**

```typescript
// frontend/src/api/client.ts — modify the init builder
import { getSelectedAccount } from '../stores/account'

export async function apiJson<T = any>(url: string, opts: Opts = {}): Promise<T> {
  const init: RequestInit = { method: opts.method ?? 'GET' }
  const headers: Record<string, string> = {}
  const account = getSelectedAccount()
  if (account) headers['X-Account'] = account
  if (opts.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    init.body = JSON.stringify(opts.body)
  }
  init.headers = headers
  const res = await fetch(url, init)
  let data: any = null
  try { data = await res.json() } catch { /* non-JSON */ }
  if (!res.ok) throw new ApiError(data?.detail ?? data?.message ?? `HTTP ${res.status}`, res.status)
  if (res.ok && data === null) throw new ApiError('Non-JSON response', res.status)
  return data as T
}
```

- [ ] **Step 5: Run tests**

Run: `cd frontend && npx vitest run src/stores/account.test.ts src/api/client.test.ts`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/stores/account.ts frontend/src/stores/account.test.ts frontend/src/api/client.ts
git commit -m "feat(fe): account store + X-Account header injection"
```

### Task 14: Accounts API + `useAccounts` hook

**Files:**
- Create: `frontend/src/api/accounts.ts`, `frontend/src/hooks/useAccounts.ts`

- [ ] **Step 1: Write the API module**

```typescript
// frontend/src/api/accounts.ts
import { apiJson } from './client'
import type { AccountSnapshot } from '../stores/account'

export const listAccounts = () =>
  apiJson<{ success: boolean; accounts: AccountSnapshot[] }>('/api/accounts')

export const deleteAccount = (name: string) =>
  apiJson<{ success: boolean; removed: string[] }>(`/api/accounts/${encodeURIComponent(name)}`, { method: 'DELETE' })

export async function exportAccounts(names: string[], passphrase: string): Promise<Blob> {
  const res = await fetch('/api/accounts/export', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ names, passphrase }),
  })
  if (!res.ok) throw new Error(`Export failed: HTTP ${res.status}`)
  return res.blob()
}

export async function importAccounts(file: File, passphrase: string, overwrite: boolean) {
  const fd = new FormData()
  fd.append('file', file)
  fd.append('passphrase', passphrase)
  fd.append('overwrite', String(overwrite))
  const res = await fetch('/api/accounts/import', { method: 'POST', body: fd })
  const data = await res.json().catch(() => null)
  if (!res.ok) throw new Error(data?.detail ?? `Import failed: HTTP ${res.status}`)
  return data as { success: boolean; imported: string[]; skipped: string[] }
}
```

- [ ] **Step 2: Write the hook**

```typescript
// frontend/src/hooks/useAccounts.ts
import { useQuery } from '@tanstack/react-query'
import { useEffect } from 'react'
import { listAccounts } from '../api/accounts'
import { useAccountStore } from '../stores/account'

export function useAccounts() {
  const setAccounts = useAccountStore((s) => s.setAccounts)
  const q = useQuery({ queryKey: ['accounts'], queryFn: listAccounts, refetchInterval: 3000 })
  useEffect(() => {
    if (q.data?.accounts) setAccounts(q.data.accounts)
  }, [q.data, setAccounts])
  return q
}
```

- [ ] **Step 3: Verify build**

Run: `cd frontend && npx tsc --noEmit`
Expected: no type errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/accounts.ts frontend/src/hooks/useAccounts.ts
git commit -m "feat(fe): accounts api + useAccounts polling hook"
```

---

## Phase 6 — Frontend: Overview, switcher, add/import/export UI

### Task 15: `AccountCard` + `Overview` page

**Files:**
- Create: `frontend/src/components/accounts/AccountCard.tsx`, `frontend/src/pages/Overview.tsx`

- [ ] **Step 1: Write `AccountCard`**

```tsx
// frontend/src/components/accounts/AccountCard.tsx
import { useNavigate } from 'react-router-dom'
import { Play, Pause } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useAccountStore, type AccountSnapshot } from '@/stores/account'
import { runCareer, stopRunner } from '@/api/career'   // existing endpoints

export default function AccountCard({ acc }: { acc: AccountSnapshot }) {
  const navigate = useNavigate()
  const setSelected = useAccountStore((s) => s.setSelected)
  const dot = acc.running ? 'bg-green-500' : acc.loop_active ? 'bg-yellow-500' : 'bg-muted-foreground'

  function open() { setSelected(acc.name); navigate(`/account/${encodeURIComponent(acc.name)}`) }

  return (
    <div className="border border-border rounded-lg p-3 cursor-pointer hover:border-primary" onClick={open}>
      <div className="flex items-center justify-between mb-2">
        <span className="flex items-center gap-2 font-medium">
          <span className={`h-2 w-2 rounded-full ${dot}`} />{acc.name}
        </span>
        <Button size="icon" variant="ghost" className="h-7 w-7"
          onClick={(e) => { e.stopPropagation(); acc.running ? stopRunner() : runCareer({ runs: 1 }) }}>
          {acc.running ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
        </Button>
      </div>
      <div className="text-xs text-muted-foreground">
        {acc.logged_in ? (acc.running ? 'Running' : 'Idle') : 'Not logged in'}
      </div>
    </div>
  )
}
```

> Note: the per-card RUN/PAUSE must target that card's account. Since `apiJson` reads the
> global selection, set `setSelected(acc.name)` before calling, or extend `runCareer`/`stopRunner`
> to accept an explicit account and pass `X-Account` directly. Use the explicit-account variant
> to avoid races when several cards act at once:

```typescript
// frontend/src/api/career.ts — add overloads that pin the account
export const runCareerFor = (name: string, body: RunCareerBody) =>
  apiJson('/api/career/run', { method: 'POST', body, account: name })
```
Add an optional `account?: string` to `Opts` in `client.ts` that overrides `getSelectedAccount()` for that one call.

- [ ] **Step 2: Write `Overview`**

```tsx
// frontend/src/pages/Overview.tsx
import { useAccounts } from '@/hooks/useAccounts'
import { useAccountStore } from '@/stores/account'
import AccountCard from '@/components/accounts/AccountCard'
import AddAccountDialog from '@/components/accounts/AddAccountDialog'
import ImportExportControls from '@/components/accounts/ImportExportControls'

export default function Overview() {
  useAccounts()
  const accounts = useAccountStore((s) => s.accounts)
  return (
    <div className="p-4">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-lg font-bold">Accounts</h1>
        <div className="flex gap-2"><ImportExportControls /><AddAccountDialog /></div>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        {accounts.map((a) => <AccountCard key={a.name} acc={a} />)}
      </div>
    </div>
  )
}
```

- [ ] **Step 3: Verify build**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors (after Tasks 16-17 create the referenced dialogs; stub them now if building this task alone).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/accounts/AccountCard.tsx frontend/src/pages/Overview.tsx frontend/src/api/career.ts frontend/src/api/client.ts
git commit -m "feat(fe): account overview grid + per-account run controls"
```

### Task 16: `AddAccountDialog` (QR + frida tabs)

**Files:**
- Create: `frontend/src/components/accounts/AddAccountDialog.tsx`
- Test: `frontend/src/components/accounts/AddAccountDialog.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// AddAccountDialog.test.tsx
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import AddAccountDialog from './AddAccountDialog'

describe('AddAccountDialog', () => {
  it('shows QR and Capture tabs when opened', () => {
    render(<AddAccountDialog />)
    fireEvent.click(screen.getByRole('button', { name: /add account/i }))
    expect(screen.getByRole('tab', { name: /qr/i })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /capture/i })).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/accounts/AddAccountDialog.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the component** (reuses existing `QrPanel` + recapture flow)

```tsx
// frontend/src/components/accounts/AddAccountDialog.tsx
import { useState } from 'react'
import { Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogTrigger, DialogTitle } from '@/components/ui/dialog'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import QrPanel from '@/components/login/QrPanel'

export default function AddAccountDialog() {
  const [open, setOpen] = useState(false)
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm"><Plus className="h-4 w-4 mr-1" />Add account</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogTitle>Add account</DialogTitle>
        <Tabs defaultValue="qr">
          <TabsList>
            <TabsTrigger value="qr">QR login</TabsTrigger>
            <TabsTrigger value="capture">In-game capture</TabsTrigger>
          </TabsList>
          <TabsContent value="qr"><QrPanel /></TabsContent>
          <TabsContent value="capture">
            <p className="text-sm text-muted-foreground mb-2">
              Open the game, switch to the target Uma account, then start capture.
            </p>
            {/* reuse the recapture()/recaptureStatus() polling flow */}
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  )
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/accounts/AddAccountDialog.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/accounts/AddAccountDialog.tsx frontend/src/components/accounts/AddAccountDialog.test.tsx
git commit -m "feat(fe): add-account dialog with QR + capture tabs"
```

### Task 17: `ImportExportControls`

**Files:**
- Create: `frontend/src/components/accounts/ImportExportControls.tsx`

- [ ] **Step 1: Write the component**

```tsx
// frontend/src/components/accounts/ImportExportControls.tsx
import { useRef, useState } from 'react'
import { Download, Upload } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { exportAccounts, importAccounts } from '@/api/accounts'
import { useAccountStore } from '@/stores/account'

export default function ImportExportControls() {
  const accounts = useAccountStore((s) => s.accounts)
  const fileRef = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)

  async function doExport() {
    const pw = window.prompt('Passphrase to encrypt the export (REQUIRED — bundle contains live Steam credentials):')
    if (!pw) return
    setBusy(true)
    try {
      const blob = await exportAccounts(accounts.map((a) => a.name), pw)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a'); a.href = url; a.download = 'accounts.umaacct'; a.click()
      URL.revokeObjectURL(url)
    } catch (e) { toast.error(String(e)) } finally { setBusy(false) }
  }

  async function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]; if (!file) return
    const pw = window.prompt('Passphrase to decrypt the bundle:')
    if (!pw) return
    setBusy(true)
    try {
      const r = await importAccounts(file, pw, false)
      toast.success(`Imported: ${r.imported.join(', ') || 'none'}${r.skipped.length ? ` · skipped: ${r.skipped.join(', ')}` : ''}`)
    } catch (e) { toast.error(String(e)) } finally { setBusy(false); if (fileRef.current) fileRef.current.value = '' }
  }

  return (
    <div className="flex gap-2">
      <Button size="sm" variant="outline" disabled={busy} onClick={doExport}><Download className="h-4 w-4 mr-1" />Export</Button>
      <Button size="sm" variant="outline" disabled={busy} onClick={() => fileRef.current?.click()}><Upload className="h-4 w-4 mr-1" />Import</Button>
      <input ref={fileRef} type="file" accept=".umaacct" className="hidden" onChange={onFile} />
    </div>
  )
}
```

- [ ] **Step 2: Verify build**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/accounts/ImportExportControls.tsx
git commit -m "feat(fe): account import/export controls with passphrase"
```

### Task 18: Routing + sidebar switcher

**Files:**
- Modify: `frontend/src/App.tsx`, `frontend/src/components/layout/Sidebar.tsx`
- Create: `frontend/src/components/accounts/AccountSwitcher.tsx`

- [ ] **Step 1: Add the Overview route + per-account dashboard route**

In `App.tsx`, inside the authenticated `<Route path="/" element={<AppShell />}>` block:

```tsx
<Route index element={<Overview />} />
<Route path="account/:name" element={<Dashboard />} />
<Route path="setup" element={<Setup />} />
{/* ...existing library/settings/events... */}
```

Add a small wrapper so `Dashboard` reads `:name` and calls `setSelected(name)` on mount:

```tsx
// inside Dashboard.tsx, top of component
import { useParams } from 'react-router-dom'
import { useAccountStore } from '@/stores/account'
const { name } = useParams()
const setSelected = useAccountStore((s) => s.setSelected)
useEffect(() => { if (name) setSelected(name) }, [name, setSelected])
```

- [ ] **Step 2: Write `AccountSwitcher` and mount it in the sidebar**

```tsx
// frontend/src/components/accounts/AccountSwitcher.tsx
import { NavLink } from 'react-router-dom'
import { useAccounts } from '@/hooks/useAccounts'
import { useAccountStore } from '@/stores/account'
import { cn } from '@/lib/utils'

export default function AccountSwitcher() {
  useAccounts()
  const accounts = useAccountStore((s) => s.accounts)
  const setSelected = useAccountStore((s) => s.setSelected)
  return (
    <div className="px-2 py-2 border-t border-border">
      <div className="text-[10px] uppercase text-muted-foreground px-2 mb-1">Accounts</div>
      {accounts.map((a) => {
        const dot = a.running ? 'bg-green-500' : a.loop_active ? 'bg-yellow-500' : 'bg-muted-foreground'
        return (
          <NavLink key={a.name} to={`/account/${encodeURIComponent(a.name)}`}
            onClick={() => setSelected(a.name)}
            className={({ isActive }) => cn('flex items-center gap-2 px-2 py-1.5 rounded-md text-sm',
              isActive ? 'bg-primary/10 text-primary' : 'hover:bg-sidebar-accent')}>
            <span className={`h-2 w-2 rounded-full ${dot}`} />{a.name}
          </NavLink>
        )
      })}
    </div>
  )
}
```

In `Sidebar.tsx`, render `<AccountSwitcher />` above `<AccountFooter />`.

- [ ] **Step 3: Verify build + manual smoke**

Run: `cd frontend && npx tsc --noEmit && npm run build`
Then `python main.py 1616 --account lewpie`, open `http://127.0.0.1:1616`:
Expected: Overview grid at `/`, sidebar lists accounts, clicking one opens its dashboard.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/App.tsx frontend/src/components/layout/Sidebar.tsx frontend/src/components/accounts/AccountSwitcher.tsx frontend/src/pages/Dashboard.tsx
git commit -m "feat(fe): overview route + sidebar account switcher"
```

---

## Phase 7 — Per-account logs, backoff, integration

### Task 19: Account-labelled career logs + per-session backoff

**Files:**
- Modify: `career_bot/report.py` (the filename is built **here**, not in runner.py), `career_bot/runner.py` (sole caller passes the account), and confirm the auto-backoff circuit breaker reads/writes session-local state (not a module global).

- [ ] **Step 1: Add the account label in `career_bot/report.py`**

The career-log filename is built in `career_bot/report.py::write_report` (NOT runner.py). At HEAD:
- `report.py:131` — `def write_report(report, output_dir):`
- `report.py:134` — `stamp = datetime.now().strftime("%Y%m%d_%H%M%S")`
- `report.py:135` — `path = output_dir / f"career_log_{stamp}.json"`
- `report.py:145` — `latest = output_dir / "latest_career_log.json"`  ← **shared, not account-scoped → collides across parallel accounts**

`runner.py` only *calls* it once, at `runner.py:411` — `out = write_report(self.report, root_trace_dir)`. The account label is already available in the runtime as the `SWEEPY_ACCOUNT` env var (read at `runner.py:193` and `runner.py:460` as `os.environ.get("SWEEPY_ACCOUNT") or ""`). **In the multi-tenant server, `SWEEPY_ACCOUNT` only reflects the CLI default account — so set it per career run** (Task 6: `os.environ["SWEEPY_ACCOUNT"] = session.name` before `runner.start(...)`, or pass `session.name` explicitly down to `write_report`). Plan below uses an explicit argument (race-safe; env is process-global and unsafe under parallel runs).

Edit `report.py` (`re` is already imported there):

```python
# report.py — write_report
def write_report(report, output_dir, account=""):
    ...
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", str(account or "").strip())
    path = output_dir / (f"career_log_{safe}_{stamp}.json" if safe else f"career_log_{stamp}.json")
    ...
    latest = output_dir / (f"latest_career_log_{safe}.json" if safe else "latest_career_log.json")
```

> The `career_log_*.json` glob in `career_bot/event_catalog.py` (lines ~172, ~227) still
> matches the new `career_log_<account>_<ts>.json` names, so log mining is unaffected.

Thread the account from the runner. `CareerRunner.start(...)` (runner.py:109) stores it, and the call at `runner.py:411` passes it:

```python
# runner.py — start(): capture the account for this run (default from env)
def start(self, client, preset, initial_result, max_steps=2500, burn_clocks=False, dev_mode=False, account=None):
    self._account = account if account is not None else (os.environ.get("SWEEPY_ACCOUNT") or "")
    ...
# runner.py:411 — pass it through
out = write_report(self.report, root_trace_dir, account=self._account)
```

In Task 6, `run_career` passes `account=session.name` into `session.runner.start(...)`.

- [ ] **Step 2: Confirm backoff is per-session**

Grep for the circuit-breaker state used by the backoff guard. If it lives on the `UmaClient` instance (which is per-session), no change is needed — note that in the commit. If it's a module global in `main.py`, move it onto the `Session`.

Run: `grep -niE "backoff|circuit|throttl" main.py uma_api/client.py | head`
Expected: identify the owner; fix only if global.

- [ ] **Step 3: Verify**

Run: start two accounts running careers; confirm two distinct `career_log_<name>_*.json` files appear and backoff on one account does not stop the other.

- [ ] **Step 4: Commit**

```bash
git add career_bot/report.py career_bot/runner.py main.py
git commit -m "feat: per-account career logs + per-session backoff"
```

### Task 20: Full regression + manual integration

- [ ] **Step 1: Backend + frontend test suites**

Run: `python -m pytest tests/ -q && cd frontend && npx vitest run && npx tsc --noEmit`
Expected: all green.

- [ ] **Step 2: Manual end-to-end**

1. `python main.py 1616 --account lewpie` → Overview shows lewpie.
2. Add a second account via QR; it appears in the grid.
3. RUN both from their cards; both show `running`. Open each dashboard; live data is per-account.
4. Capture a third account mid-run; the two running careers keep going.
5. Export all (passphrase) → delete one → import → it returns.

- [ ] **Step 3: Commit any fixes + final**

```bash
git add -A
git commit -m "test: multi-account integration pass"
```

---

## Self-Review Notes (coverage vs spec)

- Session model + manager → Tasks 1-2. ✔
- `X-Account` routing across 52 endpoints → Tasks 3-8 (grep gate in Task 8). ✔
- Parallel careers (per-session loop/runner) → Tasks 1, 6. ✔
- Overview grid + sidebar + drill-in → Tasks 15, 18. ✔
- Add account (QR + frida) → Tasks 7 (backend), 16 (frontend). ✔
- Remove account → Task 10. ✔
- Shared presets / per-account active selection → preset stores stay module-level (Task 3); `session.active_preset` field (Task 1); run options live on the session via `run_career` (Task 6). ✔
- Import/export, passphrase-encrypted (no new dep) → Tasks 11-12 (backend), 14, 17 (frontend). ✔
- Security: `/uma_runtime` + `.superpowers/` already gitignored; export encrypted; UI warns on export → Task 17 prompt copy. ✔
- Back-compat CLI `--account` → `DEFAULT_ACCOUNT` fallback in `get_session` (Task 3). ✔
- Per-account logs + per-session backoff → Task 19. ✔
