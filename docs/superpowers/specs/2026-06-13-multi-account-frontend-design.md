# Multi-Account on Frontend — Design

**Date:** 2026-06-13
**Branch:** frontend-redesign
**Status:** Approved, pending implementation plan

## Goal

Replace the current "one process per account on its own port" model with a **single multi-tenant server** that manages all accounts from one frontend. The dashboard runs multiple accounts' careers **simultaneously**, lets the user **add accounts** via a capture-auth button (Steam QR or in-game frida capture), and **import/export** accounts (passphrase-encrypted) to move them between machines.

## Background — current architecture

- `main.py` (~100 KB, FastAPI) is a single-process server bound to one account, selected at launch via `--account NAME` / `SWEEPY_ACCOUNT` env var.
- All per-account state is module-global: `active_client` (64 refs), `active_account` (33 refs), `active_dashboard_data` (34 refs), plus `active_start_state`, `active_parent_cards`, `active_parent_rank_points`, `active_selection`, `raw_load_index_response`, `pending_game_auth_config`.
- A single global `career_runner` (`career_bot/runner.py::CareerRunner`, already per-instance with its own lock/thread) + `backend_loop_thread` / `backend_loop_stop` drive the run loop.
- 52 HTTP endpoints operate on these globals.
- Accounts persist as two files in `uma_runtime/accounts/`:
  - `<name>.json` — game session: `viewer_id`, `udid`, `auth_key`, encrypted `body`, `app_ver`, `res_ver`, `endpoint`.
  - `<name>.steam.json` — `refresh_token` (long-lived Steam credential), `steam_id`, `saved_at`.
- Two auth paths exist: **frida in-game capture** (`JS_CODE` + `_run_recapture`, attaches to the running game, grabs Steam ticket) and **Steam QR login** (`qr_login.js` → `refresh_token` → `get_ticket`).
- Running a career talks to the game API over HTTP using the saved ticket — **the game does not need to be open**. Capture is the only step that needs the live game.

## Decisions (from brainstorm)

| Decision | Choice |
|---|---|
| Run model | Accounts run **simultaneously** (parallel careers) |
| Architecture | **B — single multi-tenant process** (refactor globals into per-account sessions), one real port |
| Capture mechanism | **Both** frida in-game capture and Steam QR login, exposed in the add-account UI |
| Preset/settings scope | **Shared preset store, per-account active selection + run options**; delay/webhook shared |
| Dashboard UX | **Combine** overview grid (landing) + persistent sidebar switcher + drill-in full dashboard |
| Import/export | Yes; **passphrase-encrypted** bundle (AES-GCM via existing `pycryptodome`) |

## Architecture

### Backend — Session model + manager

**`Session`** (one per account) bundles everything currently global:
- `client` (UmaClient), `account` status, `dashboard_data`, `start_state`, `parent_cards`, `parent_rank_points`, `selection`, `raw_load_index_response`, `pending_game_auth_config`
- its **own** `CareerRunner` instance + loop thread + `stop`/`pause` flags
- per-account run state: active preset name, run options (`max_steps`, `burn_clocks`, …)
- per-session auth-capture status and per-session auto-backoff circuit breaker

**`SessionManager`** (single global, replaces the scattered globals):
- `sessions: dict[str, Session]`
- account registry = scan `uma_runtime/accounts/*.json`
- `get(name)` lazy-creates / logs in a session
- `snapshot_all()` → aggregate status for the overview grid
- a manager-level lock serializes add-account operations (frida is single-game; `qr_login.js` is "one per process")

**Stays module-level shared** (read-only or rarely written): `chara_map`, `support_map`, `skill_data`, `factor_map`, `race_map`, `succession_*`, `preset_store`, `race_preset_store`, `master_data`, `turn_delay_*`, discord webhook. Preset/race-preset **file writes** are guarded by a lock (rare; concurrent careers may read during a save).

**Concurrency:** each session runs its own career loop thread → N accounts run in parallel. Shared data maps are read-only after load, so no contention.

### API — routing + new endpoints

**Routing:** an `X-Account` request header selects the account. FastAPI dependency `get_session(x_account: str = Header(...))` resolves `SessionManager.get(name)` and injects the `Session`. Existing endpoint paths/shapes stay identical (frontend adds one header); the ~64 global references are rewritten to `session.client` / `session.account` / etc.

**New / changed endpoints:**
- `GET /api/accounts` — list + aggregate status of all sessions (name, run/pause/idle, career turn/progress, TP, last result). Drives the overview grid.
- `POST /api/accounts/add` — start add-account flow (QR or frida); returns a job id. Serialized by manager lock.
- `GET /api/accounts/add/status` — poll add progress (reuses existing QR-poll + frida capture-status patterns).
- `DELETE /api/accounts/{name}` — remove account (delete its files, kill session if running).
- `GET /api/accounts/{name}/export` — passphrase-encrypted bundle (see below).
- `POST /api/accounts/import` — upload + decrypt bundle, write files, register session.
- Existing `/api/career/run|pause|resume|stop`, `/api/auth/recapture`, status endpoints, etc. → all become per-session via the header.

**Capture safety:** capturing/QR for a new account does **not** disturb running accounts (their careers run off saved API tickets, not the live game). The current "stop run before recapture" guard is relaxed to per-session — it only blocks the *target* account's own active run.

### Frontend

**State:** new `accountStore` (zustand) holds the account list + `selectedAccount`. `api/client.ts` injects `X-Account: selectedAccount` on every request. New `useAccounts()` query polls `GET /api/accounts` for the grid.

**Pages / nav:**
- **Overview** (new landing `/`): grid of account cards — status dot, career progress bar, TP, inline RUN/PAUSE per card, `＋ Add account` card, Export/Import controls. Click a card → drill into that account's dashboard.
- **Sidebar** (always visible): account list with run/pause dots, doubles as switcher; `＋ Add account` at bottom; sets `selectedAccount`.
- **Dashboard** (existing): unchanged internally, now scoped to `selectedAccount` via the header. RunBar / StatsRow / TeamPanel / logs work unchanged once routing is in place.
- **Add-account modal:** tabs **QR** (reuse `QrPanel`) and **Frida capture** (reuse recapture flow + `PasswordPanel`). On success the account appears in list/grid.
- `AccountFooter` resource summary becomes per-selected-account; the `/login` route folds into the add-account modal (first account = add account).

### Import / Export

**Bundle format:** one `.umaacct` file = `{<name>.json, <name>.steam.json}` for one account (zip/JSON array for multiple). The bundle is **encrypted**:
- Export prompts for a passphrase → PBKDF2-HMAC-SHA256 derives a key → **AES-GCM** encrypts the payload (salt + nonce + ciphertext + tag stored in the bundle). Uses the already-present `pycryptodome` dependency — **no new dependency**.
- Import prompts for the passphrase → decrypts → writes `<name>.json` + `<name>.steam.json` into `uma_runtime/accounts/` → registers the session. Name-collision prompt (overwrite / rename).
- On the destination machine the account logs in via its `refresh_token` — no game or QR needed.

**Security:**
- The decrypted payload contains the Steam `refresh_token` and game `auth_key` — live credentials granting full account control. The UI must state this plainly on export.
- `uma_runtime/` (account files) and `.superpowers/` are already in `.gitignore`, so credentials are not committed. Exported bundles are encrypted at rest.

## Migration & back-compat

- CLI `python main.py 1616 --account A` still works → boots `SessionManager` with that one account pre-selected.
- Legacy `public/` fallback untouched.
- Old per-port multi-process usage still runs (now redundant).

## Risks / watch-outs

- **High-volume mechanical rewrite** — 64+ global refs across 52 endpoints. Do it endpoint-group by endpoint-group, testing each.
- **Shared preset-file writes** — guard `preset_store` / `race_preset_store` saves with a lock.
- **Add-account serialization** — frida + QR must hold the manager lock; running careers unaffected.
- **Per-account career logs** — currently timestamp-named globally; add an account label to filenames to avoid mixing concurrent runs.
- **N parallel API clients** — more game-server traffic; keep the auto-backoff circuit breaker **per session**.

## Testing

- **Backend unit:** SessionManager (create/get/remove, lazy login), `get_session` header dependency, export/import round-trip (encrypt → decrypt → files identical), passphrase failure, collision handling.
- **Frontend unit:** account store + header injection, Overview grid render, Add-modal tabs.
- **Manual integration:** two accounts running careers in parallel + capture a third mid-run; export on machine A → import on machine B → run.
