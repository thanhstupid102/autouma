# Architecture — ownership & dependency directions

Short reference (§12.6 Docs). Full history/archaeology lives in `REFACTOR_PLAN.md`,
`docs/scenarios/` and `docs/superpowers/plans/`.

## Layers & ownership

| Layer | Owns | Must NOT own |
|---|---|---|
| `core/settings.py` | static config (paths, env) | anything importing project code |
| `integrations/` — **outbound adapters** (tier varies per subpackage, see below) | `discord/notify` (webhook client + `LiveMonitor`; **stdlib-only**, zero project imports, config in gitignored `uma_runtime/discord.json`), `game_process/gameproc` (port cleanup, CLI arg parsing, console placement, trace enabling), `frida/js/*.js` (optional RE/diagnostic instrumentation sources — **not** Git hooks; resolved via `Settings.PATH["hooks"]`) | engine decisions, wire framing, FastAPI wiring, route handlers |
| `uma_data/` — **shared game-data infra** (peer of `career_bot`/`uma_api`) | master.mdb access (`settings` path/settings.json, `loaders`, `legacy_json` generators, `tp_cost` policy) re-exported from the package `__init__`, plus `master_updater` (headless CDN refresh) | decisions, HTTP handling, per-account session state |
| `uma_api/` — **transport** | wire protocol (`client.py` retry core + AES/MsgPack `crypto.py` + SID chain), `session.py` per-account transport state + process-singleton `SessionManager`, `api_warehouse`, `client_version`/`update_guard`/`appstore_version`, `timing` (the two injected policy seams), `log_context` (L2 field factory), facade slices (`routes`, `identity`, `diagnostics`, `trace`, `account_state`, `race_telemetry`) | application policy (TP costs → `uma_data`), master-data orchestration (→ `backend/app/services/game_login`), FastAPI wiring (→ `backend/app/deps`), runner/loop state (→ `backend/app/runner_state`) |
| `career_bot/` — **decision engine** | `engine/` (CareerRunner + mixins), `scenarios/` (MANT, Unity Cup), `skills/`, `events/`, `planning/` (presets, races, factors, spark), `bot_config/` (typed defaults = source of truth), `delay` (pacing DNA), `game_calendar`, `state_merge` | HTTP handling, FastAPI, process/Frida management, master-data infra (→ `uma_data`), outbound integrations (Discord webhook → `integrations/discord`) |
| `backend/app/` — **web layer + app runtime glue** (one package since §11 Phase 6) | `app.py` (`create_app`) + `cli.py` + `logging_setup.py` (console = operator run log), `context.py` (`configure_runtime` — rebinds module state at runtime, see stale-binding note), `deps.py` (FastAPI DI), `runner_state.py`, `services/` (cross-domain app services, e.g. `game_login`), `schemas/envelope.py` (`ApiResponse`), `domain/` (`account_store`/`account_status`/`career_selection`/`preset_runtime`/`jsonstore`, `rank_point/` = formula + probe + lineage), `routers/<domain>/{controllers,services,schemas}` | wire framing, engine decisions, game-process/Frida management (→ `integrations/game_process`), master-data infra (→ `uma_data`) |
| `frontend/` | React SPA (built `dist/` mounted by `create_app`) | — |

**Generated data** (never hand-edit): `data/json/*` + `assets/data/*` come from
master.mdb via `uma_data`; `data/bot_config/default.json` from
`scripts/gen_default_bot_config.py` (drift alarm: `tests/test_bot_config_default_sync.py`).

**Local state** (never in git): one resolved state root containing accounts,
auth, master.mdb, traces, and reports. A fresh POSIX install defaults to
`${XDG_STATE_HOME:-~/.local/state}/manhattancafe-uma-auto`. If that renamed
default does not exist but the legacy `mcqueen-uma-auto` directory does, the
legacy directory wins. An existing checkout's `uma_runtime/` still has higher
precedence when that directory already exists.

## Login ownership

The web layer obtains a Steam session ticket through QR or username/password +
Guard. With stored game auth, transport calls `tool/start_session` then
`load/index`. Without it, `uma_api.bootstrap` calls `tool/pre_signup` and
`tool/signup` with a fresh `udid`; the server can return the Steam-bound
account's `viewer_id` and `auth_key`. The Trainer ID + link-password chain
requires that game authentication first; if `tool/pre_signup` disables Steam
account creation, a fresh install cannot start the chain. Recovery then means
importing an existing account bundle or linking in the official game client.
Account auth is stored in portable AES-256-GCM `UMAENC1`
payloads under one random 32-byte master key. The payload format does not vary
by platform; only the versioned `.keyring` wrapper does. DPAPI is deliberately
the Windows default, while other platforms use a passphrase-derived scrypt KEK.
`scripts/portable_keyring.py` converts the wrapper in either direction without
rewriting the encrypted payloads.

Frida is outside this runtime path. It is an optional dependency installed via
`requirements-re.txt` for the retained manual tools in `scripts/` and
`integrations/frida/`, and is never required to log in or run the bot.

## Dependency directions

Target: `backend/app` → (`uma_api`, `career_bot`) → `settings`; `career_bot` →
`uma_api` only for wire primitives it genuinely consumes. Transport (`uma_api`)
should sit at the bottom. `uma_data` is a peer everyone may import (bot,
transport, web, scripts); it imports only `settings` and `uma_api`
(`client_version` at module level, `client.UmaClient` call-time inside
`master_updater`'s headless refresh), never `career_bot`/`backend` (§12.5).

**Inside `backend/app` the order is strict and acyclic** (§11 Phase 6): `app.py`
→ `routers/` → `context.py` / `domain/` → (`uma_api`, `career_bot`, `uma_data`,
`settings`). `context.py` and `domain/*` must never import `routers` or `app`.
This is what let the old `backend`⇄`uma_app` cycle — and the lazy in-method
imports that worked around it — go away.

`integrations/` is a peer package of outbound adapters, entered only downward —
its two Python subpackages sit at **different** tiers on purpose:
- `integrations/discord` imports **nothing** from the project (stdlib `urllib`
  plus its own gitignored config file), so it is a true leaf. The edges into it
  — `career_bot.engine.runner`, `uma_api.update_guard._default_alert_sink`
  (call-time), `backend/app/routers/settings` — are downward and cannot cycle.
- `integrations/game_process` is app-tier startup glue. It reads `settings` and
  `career_bot.delay`; its runtime caller is `backend.app.cli`.

Nothing under `integrations/` may import `backend/app` or `career_bot.engine`.

Known inversions still tracked (deliberate, see plan):
- `uma_api/client.py` → `career_bot.delay` (pacing waits inside transport) — **B3**, deferred indefinitely.
- `uma_api/session.py` → `career_bot.engine.CareerRunner` (runner state on `Session`) — **B2 deeper**, later step.
- `uma_api/race_telemetry.py` → `career_bot.delay` — same edge as B3, moved not widened.

Deliberate non-inversions (recorded so they are not "fixed" by mistake):
- `career_bot.engine.runner` → `integrations.discord.notify` is a **direct**
  adapter call, not an injected port. `notify` is a stdlib-only leaf, so no cycle
  is reachable, and the runner needs live-monitor *lifecycle*
  (`start_live_monitor` → handle · `stop_live_monitor(handle, snapshot)` ·
  `send_career_summary`) which the one-shot
  `update_guard.alert_sink(base_dir, title, message)` does not model — reusing
  that sink would mean rewriting its contract. §12.5's "runner depends on a
  notification interface" is the follow-up to do *if* a second notification
  backend ever appears; until then this direct edge is the layering.
- `uma_api/update_guard.py` keeps its **call-time** `from integrations.discord
  import notify` even though a top-level import would no longer cycle. The
  laziness is now layering discipline (transport must not pull an integration at
  import time), and callers that own a notifier still override it via
  `alert_sink`.

## Invariants that must survive any refactor

- **Wire-format frozen**: SID hash chain, AES/MsgPack framing, event-choice
  0↔1-based conversion (`REFACTOR_PLAN.md` §1.3).
- **Account isolation**: account A's state/credentials/responses never reach account B.
- **Runner lifecycle**: no run-loop thread survives stop/logout/delete; no duplicate live API action.
- **Stale-binding trap (§8b stage 6)**: `configure_runtime` REASSIGNS module globals
  (`rank_point` maps, `account_store.base_dir`, …) at runtime — read owner state at
  call time (`rp.chara_map`), never freeze it via `from x import y`.
- **Console output**: the operator reads stdout as the live run log; logging renders
  message-only at the CLI boundary (`backend/app/logging_setup.py`).
