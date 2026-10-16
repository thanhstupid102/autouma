# Linux run-only support — plan

**Date:** 2026-07-30 · **Base:** `main` @ `ea60691` · **Goal:** run the bot + backend + built UI on Linux.

**In scope:** career automation loop, FastAPI backend, serving `frontend/dist`, Steam login, config/state persistence.

**Out of scope (stays Windows-only, deliberately):** everything under `scripts/` that uses Frida, il2cpp/memory dumping, traffic capture, local game-install inspection. `requirements-re.txt` is never installed on Linux.

Evidence below comes from a 10-agent Codex census of the tree (7 surface probes + 2 adversarial verifiers + 1 completeness critic). Every `file:line` was read by an agent, not inferred.

Sections 0–9 preserve the initial census and problem statement as of the base
commit; their present-tense blocker descriptions are historical. Sections
10–13 and the task notes record the implementation that superseded them.

> **Implementation complete:** T1–T19 are done. Start at
> [§13 Plan closure](#13-plan-closure) for the remaining operator-only work.

---

## 0. Headline: how much did dropping Frida buy us?

A lot, but it did not buy the two things that actually block a Linux run.

**Confirmed clean:**

- **No `FATAL-IMPORT` anywhere.** `python main.py` and `from main import app` import cleanly on Linux with only `requirements.txt` installed. Every `winreg` import is function-local and `ImportError`-guarded; `ctypes.wintypes` loads no DLL.
- **Frida is genuinely confined.** All direct `import frida` live under `scripts/`. The one runtime edge into `scripts/` is `backend/app/routers/events/services/event_service.py:42` → `scripts/scrape_gametora_effects.py:59`, which is stdlib-only. An adversarial sweep specifically hunting lazy imports, `importlib`/`__import__`, plugin discovery, and error-recovery branches found no counterexample. Routers are a static list (`backend/app/routers/__init__.py:26`); the CLI accepts only port/account/debug (`integrations/game_process/gameproc.py:67`). **No HTTP route or CLI flag exposes RE tooling.**
- **No local game install or game process is needed on the happy path.** `master.mdb` comes from the CDN (`uma_data/master_updater.py:482`); `app_ver` comes from Apple's public App Store API (`uma_api/appstore_version.py:114`) with `uma_runtime/client_version.json` and a hardcoded fallback behind it (`uma_api/client.py:143`). The startup registry probe at `backend/app/app.py:45` is best-effort and returns `None` on Linux.
- **Steam login needs no Steam desktop client.** `integrations/steam/steam_ticket_gen.js:25/36/60` logs into Steam over the network via `steam-user` and requests the app-3224770 ticket; `integrations/steam/qr_login.js:13/35` uses `steam-session` QR. No registry, DLL, `ssfn`, VDF, or active-user lookup anywhere in that chain. `uma_api/steam_auth.py:22` spawns PATH-resolved `node` with `pathlib` paths, an arg list, no `shell=True`, no Windows spawn flags. Node + outbound network are the only prerequisites.
- **All 7 direct runtime Python deps have manylinux wheels** — `fastapi`, `lz4`, `msgpack`, `pycryptodome`, `pydantic`, `uvicorn`, `curl_cffi`. The census also found `Requests==2.33.1` declared but never imported by any runtime or script module; T19 removes that dead entry.
- **Node deps are clean.** `steam-user@5.3.0` / `steam-session@1.9.4` have no OS restriction; `lzma-native` is an optional peer so no compiler is needed. The frontend lock ships Linux GNU/musl binaries for Rolldown and Tailwind Oxide.
- **Nothing else Windows-shaped in the runtime.** No `msvcrt`, pywin32, `pythoncom`, `wmi`, `pymem`, `sys.platform` branch, `os.startfile`, `shell=True`, Windows subprocess flags, `SIGBREAK`/`CTRL_C_EVENT`, event-loop policy, or multiprocessing start-method selection. Threads only (`career_bot/engine/runner.py:293`), stop is a lock-protected flag checked at a loop boundary (`:296`). Atomic writes use `os.replace()` (`career_bot/engine/report.py:175`). Discord is stdlib HTTP (`integrations/discord/notify.py:372`). QR renders as a browser data URL (`frontend/src/components/login/QrPanel.tsx:65`) — no display server needed.
- **Harmless Windows calls that already degrade correctly:** `uma_api/race_telemetry.py:25` (`ctypes.windll.user32` → falls back to height 864), `uma_api/client_version.py:201` (`winreg` → `None`), `integrations/game_process/gameproc.py:13` (guarded by `os.name != "nt"`).

**So the answer is: yes, simpler — but two hard blockers remain, and neither has anything to do with Frida.** Both are in the auth/identity layer that the recent Steam-only work touched.

---

## 1. The two blockers

### B1 — Every `UmaClient` eagerly probes Windows hardware

`uma_api/client.py:117` calls `get_hwid()` unconditionally in `__init__`, **before** consulting saved or captured fingerprint fields. `uma_api/device.py:55` raises `RuntimeError` on any non-Windows OS.

Blast radius: password login and bootstrap (`uma_api/bootstrap.py:105` ← `backend/app/routers/auth/services/auth_service.py:751`), the career loop (client is passed in from `backend/app/routers/careers/services/career_run.py:100`), and the headless master download (`uma_data/master_updater.py:557`, whose failure is swallowed at `:591`).

**Crucially, the identity itself is already portable** — the adversarial verifier downgraded the naive "udid is Windows-derived, so accounts can't move" claim to OVERSTATED:

- `udid` is generated as UUID4 at `uma_api/bootstrap.py:70` — *not* derived from `MachineGuid`.
- `uma_api/client.py:777` snapshots `udid` plus every fingerprint field on successful auth.
- `uma_api/identity.py:59` already gives persisted values precedence over derived hardware values.
- `device_id` derives from BIOS product + `MachineGuid` + seed (`uma_api/device.py:83`) only when *generating a new* identity.

So an existing account keeps its exact identity across an OS move. Only the eager probe stands in the way.

**Fix:**
1. `uma_api/client.py:117` — resolve explicit/persisted fingerprint fields first; call hardware discovery only when a field is genuinely missing. An existing account must never probe the new host.
2. `uma_api/device.py:52` — add a non-Windows provider for *new/incomplete* identities: stable machine material (`/etc/machine-id`) + the existing seed, generated UDID, and PC-shaped device/GPU/OS strings matching the Windows shape. Honour explicit `UMA_DEVICE_*` overrides. Keep the registry path Windows-only.
3. `uma_api/identity.py:107` — legacy `steam_password_seed` configs materialize missing fields through `get_hwid()`; route that through the same portable provider or it still fails after (1).
4. `uma_data/master_updater.py:557` — give the guest updater a complete synthetic fingerprint so master discovery never touches hardware discovery.
5. `uma_api/device.py:46` — IP discovery opens an IPv4 UDP socket and connects to `8.8.8.8` with **no exception handling**, and the socket is closed only on success. Fails on IPv6-only or UDP-filtered hosts even when HTTPS works. Make it best-effort with cleanup, a stable fallback, and an override.

**Open risk:** whether the game server accepts a Linux-synthesized fingerprint is **unverified**. Settle with a disposable-account bootstrap before trusting it on a real account.

### B2 — Secrets at rest are wrapped with Windows DPAPI only

`uma_api/secret_store.py:197` loads-or-creates one random 32-byte master key; `:205` unwraps it via DPAPI; `:212` refuses to create it where DPAPI is unavailable. The payload layer is fine and portable: AES-GCM, format `UMAENC1 | 16B salt | 12B nonce | 16B tag | ciphertext` (`:231`). **Only the key-wrap is Windows.**

Blast radius — everything that persists or loads auth:

| site | what breaks |
|---|---|
| `backend/app/routers/auth/services/auth_service.py:723` | password login saves the Steam refresh token *before* building the client → dies even earlier than B1 |
| `backend/app/routers/steam/services/steam_service.py:54` | QR confirm saves the token → 500 |
| `backend/app/cli.py:36` | `--account NAME` loads encrypted files **before** uvicorn starts → backend won't boot |
| `uma_api/account_io.py:82-90` | passphrase-bundle import decrypts portably, then writes through the DPAPI store → migration can't complete |
| `backend/app/domain/jsonstore.py:55` | `save_json()` raises |

**Migration path already exists:** `uma_api/account_io.py:36` `UMAACCT1` bundles use PBKDF2-SHA256 + AES-GCM and carry both game config and Steam token — OS-independent. **Export on Windows → import on Linux.** Copying the DPAPI `.keyring` file can never work.

**Fix:** keep the AES-GCM payload format byte-identical; introduce a **versioned master-key backend** at `_master_key()`. DPAPI stays the Windows backend.

**DECIDED: Linux uses a passphrase-derived KEK.** scrypt or Argon2id over a passphrase supplied out-of-band (`UMA_SECRET_PASSPHRASE` env var, or a systemd `LoadCredential`). No raw key is ever written next to the ciphertext. Consequences to design for:

- The passphrase must be present at every start, including unattended restarts — the systemd unit in Phase 6 must show the credential wiring, not just `Environment=`.
- `backend/app/cli.py:36` loads encrypted files *before* uvicorn, so a missing/wrong passphrase must fail with a clear, actionable error there rather than a `RuntimeError` traceback.
- Wrap-format must be version-tagged so a future backend swap doesn't orphan existing state.
- Rejected alternatives, recorded: OS keyring/libsecret (needs Secret Service + DBUS, absent on headless servers, extra runtime dep) and a `0600` key file (raw key beside the ciphertext, only as strong as filesystem perms).

Never fall back to plaintext — preserve today's fail-closed behaviour.

---

## 2. Second tier — imports fine, real usage breaks

| # | site | problem | fix |
|---|---|---|---|
| B3 | `backend/app/routers/steam/services/steam_service.py:54` + `frontend/src/components/login/QrPanel.tsx:109` | QR confirm never returns the token — it must persist first. On persistence failure the UI treats the 500 as transient and **polls forever**. Platform-independent bug. | expose `confirmed` only after persistence succeeds; make the panel stop on non-transient 5xx |
| B4 | `uma_api/device.py:95-98` | login runs `npm install` when `node_modules` is missing; root `postinstall` (`package.json:7`) then builds the whole frontend. Login therefore needs a **writable checkout + registry access**. | make the dependency check non-mutating with an actionable prerequisite error; install Node deps at provisioning time from the lockfile |
| B5 | `career_bot/delay.py:38-40` | creates `.timing_dna` **beside the Python source, at import time**. Reached via `backend/app/context.py:12` → `backend/app/domain/rank_point/__init__.py:9`. A read-only checkout fails before serving. | move the seed to the state root; create atomically |
| B6 | `uma_api/trace.py:14`, `career_bot/engine/runner.py:117` honour `UMA_RUNTIME_DIR`; `backend/app/domain/jsonstore.py:48`, `career_bot/planning/presets.py:175`, `career_bot/bot_config/store.py:27`, `integrations/discord/notify.py:22` do **not** | state is scattered across the checkout; can't relocate coherently | one writable state-root abstraction; route every mutable store through it |
| B7 | `uma_data/mdb_config.py:37` | Linux default `master.mdb` path is `~/AppData/LocalLow/Cygames/Umamusume/...` | `${XDG_DATA_HOME:-~/.local/share}/manhattancafe-uma-auto/master/master.mdb`, falling back to the existing legacy `mcqueen-uma-auto` directory only when the renamed directory is absent; keep the Windows default and `settings.json` override. Align the dead duplicate at `core/settings.py:47` |
| B8 | `uma_data/master_updater.py:557` → B1 → caught at `:591` | first run silently gets **no master data**. `uma_data/loaders.py:31` then returns empty defaults: mandatory route objectives empty (`career_bot/scenarios/objectives.py:62`), Unity Cup aptitudes fall back (`career_bot/scenarios/unity_cup/team_roster.py:46`), TP discount falls back to 30 (`uma_data/tp_cost.py:62`). **Silently wrong decisions, not a crash.** | fixed by B1; then make missing master data **block career start** with an actionable error instead of running on empty data |
| B9 | `integrations/discord/notify.py:22/39` writes the webhook (a bearer secret) with plain `write_text` at process umask; `uma_api/trace.py:79` writes full API responses at default perms | local secret/PII exposure on multi-user Linux hosts | owner-only atomic writes; state dirs `0700`, files `0600` on POSIX; assert the mode in a Linux test |
| B10 | `uma_api/steam_auth.py:141` | `terminate()` without `wait()`; `uma_api/session.py:349` stops only the career runner → zombies on repeated QR attempts | terminate → wait → kill; invoke on account removal and app shutdown |
| B11 | `uma_api/client.py:411`, `career_bot/delay.py:225`, `career_bot/engine/reporting.py:141` | elapsed time measured with `time.time()`; a clock correction skews the 140 ms pacing floor | `time.monotonic()` for durations; keep `time.time()` for persisted/displayed timestamps |
| B12 | `integrations/game_process/gameproc.py:24-25` | Windows `netstat`+`taskkill` port takeover no-ops on Linux, so a busy port surfaces later as a uvicorn bind error | platform-neutral port preflight with a clean diagnostic (`psutil.net_connections()` if a dep is acceptable) |

### 2b. Filesystem paths, case sensitivity, line endings — almost entirely clear

The usual silent Linux killers were audited exhaustively and **came back clean**:

- **Case sensitivity: zero mismatches.** 503 frontend relative/`@/` imports, 535 runtime Python module imports, 402 race-image references, and 786 numeric `data/images/*.png` names were each compared against real on-disk spelling. All match. Nothing will break on a case-sensitive filesystem.
- **No production Windows absolute paths.** The only drive-letter strings in the tree are test fixtures — `tests/test_dump_gameassembly_memory.py:146` (`C:\game\GameAssembly.dll`) and `frontend/src/components/settings/settings.test.tsx:102` (`C:\\games\\master.mdb`). No UNC literal, no production `C:\`/`D:\`.
- **Line endings are a non-issue.** No `.sh` or `.ps1` entrypoint exists; the app is launched as `python main.py`. Tracked blobs are LF (the CRLF in this worktree is `core.autocrlf`). There is no `.gitattributes`, but nothing needs one today — add one only if a shell entrypoint ships later.
- **Atomic writes are portable.** No `os.rename`-over-existing-file anywhere. Secret store (`uma_api/secret_store.py:189`), API warehouse (`uma_api/api_warehouse.py:63`), master MDB (`uma_data/master_updater.py:510`), and career reports (`career_bot/engine/report.py:184`) all use same-directory temp + `os.replace`. Some plain JSON `write_text` calls are non-atomic, but equally so on Windows — not a portability item.

Three real items this surfaced, all cosmetic-to-minor:

| site | problem | fix |
|---|---|---|
| `frontend/src/components/settings/MasterDataCard.tsx:128` | input placeholder hardcodes `C:\path\to\master.mdb`; the API accepts a Linux path fine | `/path/to/master.mdb` |
| `build-ui.bat:14` | the only named UI-build helper is a `.bat`, and holds the sole runtime-adjacent backslash literal (`frontend\dist`) | document/ship `npm run build:ui` as the helper; label the `.bat` Windows-only |
| `frontend/.gitignore:11` + `backend/app/routers/others/controllers.py:20` | `frontend/dist` is untracked, so a fresh clone serves "Dashboard not built" until a build runs | bake `dist` into the Linux/container artifact (already required by Phase 5) |

This also sharpens **B6**: `UMA_RUNTIME_DIR` relocates *logs only*. Everything else is rooted in the checkout — account/token/keyring, selections, auto-delete, API warehouse, version/update state, Discord config, and event catalog under `<repo>/uma_runtime`; bot config, presets, event prefs, and generated JSON under `<repo>/data`. There is no `HOME`/XDG state root and no filesystem lockfile. Either make `UMA_RUNTIME_DIR` apply consistently or replace it with a single state-dir override — a partial fix is worse than none, because it splits state across two roots.

Minor open question: `master.mdb` should land under `${XDG_DATA_HOME:-~/.local/share}` (it is re-downloadable app data), not `XDG_STATE_HOME`. Pick one and use it consistently for B7.

---

## 3. Test suite on Linux

97 test files, 1021 test functions. **No** Windows path literals in assertions, no `\\` expectations, no platform `skipif`, no PowerShell/`.exe` shell-outs, no CRLF assertions. `tests/conftest.py:15` already skips its Windows permission workaround on Linux.

**Every Linux failure traces to B2 (DPAPI), ~15 tests:**
`tests/test_json_stores.py:42,49,76,217,246` · `tests/test_routes_accounts.py:25` · `tests/test_routes_auth_steam.py:133` · `tests/test_steam_unbind.py:80,148,186,213,240,275,294,316`

`tests/test_secret_store.py:11` skips its three DPAPI tests on Linux → **the Linux backend would land with zero coverage.** Parameterize over key backends instead of skipping.

**`tests/test_no_runtime_frida_imports.py:6` does not prove what its name claims** (verifier verdict: REFUTED as proof). It scans four roots only — omitting `main.py`, `core/settings.py`, `uma_data/`, `integrations/discord/` — inspects only direct `Import`/`ImportFrom` nodes, never follows the import graph, and never sees `importlib`/`__import__`. Swapping the whitelisted `from scripts import scrape_gametora_effects` for a Frida-bearing script would still pass. An independent full-source sweep confirms the tree *is* clean today; the guard just doesn't hold the line. Widen it: all runtime roots + `main.py` + `core/settings.py`, reject any non-whitelisted `scripts` import, follow the local import graph from `main.py`, catch constant-string dynamic imports.

---

## 4. Docs, CI, packaging

**Initial census:** there was no CI, Dockerfile, Compose file, distribution
metadata (`pyproject.toml` is tooling-only), PyInstaller spec, or systemd unit.
T17 has since added the container definition and T18 has added
`.github/workflows/ci.yml`, which now runs green on `ubuntu-latest` (see §10). A
systemd unit ships in `docs/linux.md` (T19); there is still no PyInstaller spec or
distribution metadata, neither of which the run-only goal needs.

Windows-only doc surfaces found by the initial census were `README.md`,
`DEPENDENCIES.md`, `docs/headless-updates.md`, `docs/architecture.md`, and
`build-ui.bat`; T19 forks or corrects each one, and T24 replaced `build-ui.bat` outright with the `run-linux.sh` / `run-windows.cmd` launchers. `scripts/README.md` remains
Windows-only because it documents deliberately out-of-scope RE tooling.

At the census, `package.json` declared no `engines` even though the locked Vite
build requires Node `^20.19.0 || >=22.12.0`, and the docs still advertised
Python 3.10+. T13f established Python 3.11 as the tested floor; T19 makes both
runtime constraints explicit in packaging and operator docs.

---

## 5. Decisions

**1. Linux secret backend — DECIDED: passphrase-derived KEK.** See §1 B2 for the implications.

**2. Container support — DECIDED: yes, with an auth boundary.** This is the larger of the two decisions, because the current unauthenticated surface becomes reachable the moment the bind address opens up. Required work, all of it new scope:

- `backend/app/cli.py:60` — make the bind address and port configurable (flag + env), default staying `127.0.0.1` so bare-host runs don't silently start listening publicly.
- **`backend/app/routers/settings/services/discord.py:31` leaks the full Discord webhook URL — a bearer secret — on an unauthenticated route.** This must be fixed *before* any non-loopback bind ships. Either stop returning the secret (return a redacted/`is_configured` shape) or put it behind the auth boundary. Audit the other `settings` and `accounts` routes for the same class of leak while in there.
- Introduce the auth boundary itself: a shared-secret/token gate on the API plus documented reverse-proxy (TLS-terminating) deployment. Decide whether the React UI authenticates against it or is only ever served behind the proxy.
- Container image: non-root user, checkout read-only, one writable state volume (depends on Phase 2 B6), Node deps + `frontend/dist` baked at build time (depends on B4), passphrase injected as a secret not an env literal.
- The memory ceiling in Phase 3 stops being theoretical — a container gets a hard limit.

**3. Supported matrix — DECIDED:**

| axis | value | why |
|---|---|---|
| distro | Ubuntu 22.04 LTS or newer, Debian 12 or newer (glibc) | what the manylinux wheels target |
| libc | glibc only | musl/Alpine is explicitly **untested**; `curl_cffi` and `pydantic-core` musl wheels exist but nothing here has exercised them |
| arch | `x86_64` supported, `aarch64` best-effort | all 7 direct runtime deps publish aarch64 manylinux wheels, but no aarch64 run has happened |
| Python | **3.11** minimum | code needs 3.10+ (`str \| Path`), mypy already targets 3.11; pin the floor at what is actually type-checked |
| Node | `^20.19.0 \|\| >=22.12.0` | forced by the locked Vite build; CI runs 22 |

Add the Node range to `package.json` `engines` (Phase 7) so the constraint stops being implicit.

**4. Migration policy — UPDATED BY T13b: re-wrap the whole state-root keyring.**
The original decision made per-account `UMAACCT1` export/import the only
supported path, but the shipped implementation supersedes it.
`scripts/portable_keyring.py --to passphrase --apply` unwraps the existing
32-byte master key with DPAPI and re-wraps that same key with the portable
passphrase backend, without changing any `UMAENC1` payload. Copying an
unconverted DPAPI keyring still cannot work away from the original Windows
user. `UMAACCT1` remains the per-account fallback when a bundle was exported
while the source account was still accessible.

---

## 6. Phases

**Phase 0 — decide. ✅ DONE.** All four decisions in §5 are locked. State-root and permissions policy: **one** writable state root (single override env var, XDG-aware default), directories `0700` and files `0600` on POSIX, no state left in the checkout.

**Phase 1 — unblock login (the two fatals). ✅ DONE.** B1 portable device identity (incl. `identity.py:107` legacy path and the `8.8.8.8` IP probe) and B2 versioned key backend. The disposable-account server-acceptance check remains operator-only.

**Phase 2 — make run-only deployment sane. ✅ DONE.** B4 non-mutating Node check, B5 import-time source write, B6 state-root unification, B7 mdb path.

**Phase 3 — data bootstrap correctness. ✅ DONE.** Missing master data blocks career start and T7 measured the bootstrap at 77.84 MiB peak RSS, yielding the documented 128 MiB hard minimum and 256 MiB preferred limit. A live Linux CDN run remains operator-only.

**Phase 4 — hardening & parity. ✅ DONE.** B3 QR dead-end, B9 file modes, B10 child-process cleanup, B11 monotonic clocks, B12 port preflight, the widened Frida guard, backend coverage, and T13b–T13f parity/floor work are complete.

**Phase 5 — auth boundary & container. ✅ DONE** *(new scope, from decision 2)*. The completed order was:
1. **First, close the leak.** Redact or gate `backend/app/routers/settings/services/discord.py:31`, and audit `settings`/`accounts` routes for the same class of secret-in-response. Nothing else in this phase may merge before this does.
2. Configurable bind address/port at `backend/app/cli.py:60`, defaulting to `127.0.0.1`.
3. The auth gate itself + documented TLS-terminating reverse proxy; decide whether the React UI authenticates or is only served behind the proxy.
4. Container image: non-root, read-only checkout, single writable state volume (needs Phase 2 B6), Node deps and `frontend/dist` baked at build time (needs B4), passphrase injected as a secret.

Gate status: the auth boundary and non-loopback bind refusal are covered by the
local suite. Live container start/restart remains in the operator Linux list.

**Phase 6 — validate. ⚠️ PARTIAL.** Ubuntu smoke: import → serve UI → QR login → password login → restart persistence → master download → one career start. Plus a **corporate-CA / proxy** run and a **read-only-root** run. The three HTTP stacks are independent and none selects a CA bundle or has verified proxy behavior: `curl_cffi` (`uma_api/client.py`, `uma_api/appstore_version.py`), `urllib` (`uma_data/master_updater.py`, `integrations/discord/notify.py`), and Node's own transport (`integrations/steam/steam_ticket_gen.js`). T18 defines an `ubuntu-latest` workflow for Python 3.11, Node 22, binary-wheel resolution, imports, POSIX modes, read-only checkout, frontend gates, and a build-only container check. The account's billing is locked, so GitHub starts no run and none of that hosted evidence exists. The live account/CDN/proxy smoke remains operator-only even once runs work.

**Phase 7 — docs. ✅ DONE.** `docs/linux.md` now covers first-run provisioning, network stacks, credential-backed systemd, API/reverse-proxy operation, containers, and migration. The Windows/Linux doc forks, App Store fallback, portable secret design, Node engines, Windows-only batch label, and dead `Requests` removal are complete in T19.

**Deliberately deferred / refused:** Frida, traffic capture, memory dumping, local game inspection, any Linux RE tooling; multi-worker uvicorn; public container binding without an auth boundary.

---

## 7. Honest caveat — three recovery paths still say "do it in the game client"

These are not Linux bugs, but they hit a Linux-only user harder, because that user has no game client at all:

- `uma_api/errors.py:60` — an active scenario with no automation strategy must be finished or abandoned in-game (`uma_api/routes.py:48`, `career_bot/engine/recovery.py:79`).
- `backend/app/routers/careers/services/career_start.py:430` — career start `102` with resume and rank-point probing both exhausted → "return to the main menu in-game".
- `backend/app/routers/auth/services/auth_service.py:860-923` — the Trainer-ID chain requires complete game auth, while signup-disabled Steam identities cannot bootstrap that auth on a fresh install. The web UI reports the supported remedies: import an existing account bundle or link in the official game client.

Making these headless needs captured request/payload for the game's "return to main menu" and for unsupported-scenario load/force-finish — **that capture is Windows RE work**, so it can't be done from Linux. Until then, a Linux deployment should be documented as **needing a Windows/game machine on standby** for these three cases. Also worth fixing regardless: `frontend/src/components/accounts/RemoveUmaLinkDialog.tsx:53` unbinds without a link password while `_preflight_steam_recovery` (`backend/app/routers/auth/services/auth_service.py:1073`) is optional — a user can strand an account without ever proving headless Trainer-ID recovery works.

---

## 8. Risk ranking (hardest first)

1. **Portable device identity** — must stay stable *and* be accepted by the game service.
2. **Auth boundary before the bind opens** — the webhook disclosure that motivated this entry is closed (T14), but the audit it triggered found a worse one: `POST /api/accounts/export` returns a bundle encrypted under a **caller-supplied** passphrase, i.e. full account exfiltration including the Steam refresh token, and `DELETE /api/accounts/{name}` is unauthenticated destruction. Neither can be redacted; only the gate fixes them. Still the highest-consequence item, and now the reason T15 and T16 may not be split.
3. **Linux secret storage + Windows migration** — passphrase lifecycle (unattended restart, wrong-passphrase diagnostics at `backend/app/cli.py:36`), permissions, export/re-auth, failure semantics.
3. **Clean-install Steam auth** — Node availability, the login-time `npm install`, Steam reachability, QR lifecycle; each fails independently.
4. **Writable-state architecture** — import-time source mutation and fragmented state paths break read-only/rootless deploys.
5. **Headless master bootstrap** — blocked today by B1; missing data silently degrades decisions; memory unmeasured.
6. **TLS / proxy / DNS / IPv4 assumptions** — probably fine on ordinary internet, currently unverified across three transports.
7. **Validation & packaging** — the matrix and workflow now exist, but hosted Linux evidence remains unavailable while the account's billing is locked.

---

## 9. Where the census disagreed with itself

| dispute | source-backed answer |
|---|---|
| Failed headless master acquisition: fatal or degraded? | **Startup is best-effort; career start is blocked.** T7 kept boot tolerant of network failure but added the explicit missing/stale-master career gate. |
| Linux port-listener cleanup: OK or degraded? | **Resolved by T12.** POSIX now identifies a listener through `/proc`, stops only a positively identified instance of this app, and leaves unknown owners untouched with an actionable bind failure. |
| Startup game-install probe: OK or degraded? | **OK.** Best-effort and caught (`backend/app/app.py:44`), App Store fallback follows (`:55`). |
| Does the Frida test confirm a Frida-free runtime? | **It did not at the census; T13 widened it.** The guard now scans all runtime roots, catches constant dynamic imports, follows the local import graph, and rejects non-whitelisted `scripts` imports. |

---

## 10. Linux validation status

**Observed on `ubuntu-latest` / Python 3.11, CI run `30605108220`, 2026-07-31 — all three jobs green:**
Python `1392 passed, 5 skipped` · flake8 clean · mypy `Success: no issues found in 161 source files` ·
Frontend `482 passed` across 41 files + build · Container build 1m5s.

| status outside the operator smoke | evidence |
|---|---|
| Peak RSS / temp disk for the master bootstrap | T7 measured the real payload and the app-resident cold bootstrap: 77.84 MiB peak RSS, leading to the 128 MiB hard minimum / 256 MiB preferred limit. |
| ✅ **Observed** — Python 3.11 runtime wheels on supported `x86_64` | `pip download --only-binary=:all: -r requirements.txt` succeeded, so no runtime dependency needs a source build. `aarch64` is still unclaimed. |
| ✅ **Observed** — `from main import app` on Linux | Dedicated step, passed. |
| ✅ **Observed** — import with a genuinely read-only checkout | Ran as the non-root runner (`test "$(id -u)" -ne 0`), stripped every write bit, **proved a write probe fails**, redirected `UMA_RUNTIME_DIR`/XDG/HOME to a temp dir, and imported from an unrelated cwd with `SWEEPY_SKIP_STARTUP_GEN` cleared. This is the shape T17's image runs in, and it had never been tried before. |
| ✅ **Observed** — real POSIX `0700` directories and `0600` files | `test_private_helpers_create_0700_directories_and_0600_files` executes on Linux instead of skipping. Note the *keyring* mode assertion in `test_posix_writes_use_owner_only_modes` had never run on any platform until T20 — see its notes. |
| ✅ **Observed** — the container definition builds | `docker build` succeeded in 1m5s in CI, unqualified local tag, no login/registry/push. Also built and **run** locally, see below. |
| ✅ **Observed** — **Phase 5's exit gate, executed against a live container** | See §10a. |

## 10a. The container was actually run — Phase 5's exit gate, executed

The owner installed WSL2 + Docker Desktop on the Windows box on 2026-07-31, so the image was built
(743 MB) and run for the first time. Linux containers, Docker 29.6.2. Startup to serving: **~6 s**.

Phase 5's gate — *"with the container published on a LAN address, an unauthenticated request must not
be able to read any secret, and the bot must survive a restart"* — had never been executed. It now
passes, against a live container with `--read-only`, a `tmpfs /tmp`, one `/state` volume, both secrets
as files, `--cap-drop ALL`, `--security-opt no-new-privileges`, `--memory 256m`:

| check | result |
|---|---|
| no API token mounted → refuses to start | exit 1, message naming `UMA_API_TOKEN`, **no traceback** |
| `GET /api/accounts`, `POST /api/accounts/export`, `GET /api/settings/discord-webhook`, `DELETE /api/accounts/{n}` — no token | all **401**, and the body carries no `auth_key`/`refresh_token`/`viewer_id`/`udid` |
| `Authorization: Bearer` and `X-Api-Token` over the published port | 200; wrong token 401 |
| ungated surfaces | `/` 200 (`<title>ManhattanCafeAuto</title>`, so `frontend/dist` really was baked), `/api/auth-gate` 200 → `{"gate_required": true}` |
| non-root | uid/gid **10001** |
| read-only application layer at runtime | `touch /app/...` → *Read-only file system* |
| state volume | `/state` mode **700**, owner 10001:10001, every file `0600`, directories `0700`, **no nested `uma_runtime`** |
| secrets are files, not env literals | `UMA_API_TOKEN` / `UMA_SECRET_PASSPHRASE` **unset**; only the `_FILE` forms present. Neither value appears in `env`, `docker inspect`, or the logs |
| **survives a restart** | back up in ~4 s, state listing identical, gate still enforced, authenticated access still 200 |

**B2's whole purpose, verified in the deployed shape for the first time.** Writing through the secret
store inside the container produced a `UMAENC1` payload with the plaintext absent,
`keyring_backend == "passphrase"` (not DPAPI), `/state/.keyring` at mode `0600` — and it still
decrypted **after a restart**, by re-deriving the KEK from the mounted passphrase file.

**Two things the plan had listed as needing a real box turned up in the startup logs:**
`APP-VER refreshed from App Store: None -> 1.33.0` (the App Store fallback works on Linux) and
`master.mdb refreshed headlessly (pre-download resource version)` — i.e. **the live CDN master
download works on Linux**, with no account, landing at
`/state/.local/share/<app>/master/master.mdb` on the state volume.

**Re-verified after the T23 rename**, by rebuilding as `manhattancafe-uma-auto:local` and re-running
the whole set: the user is now `manhattancafe` but **uid/gid are still 10001**, `/state` is still
`0700` owned by `10001:10001`, the gate still refuses without a token and serves with one, artwork
still loads unauthenticated, and the SPA still serves. This also settled the one item T23 had to flag
as unproven: the renamed wire-visible User-Agent (`ManhattanCafeMasterUpdater/1.0`) completed a **live
CDN master download**, landing at `/state/.local/share/manhattancafe-uma-auto/master/master.mdb`. So
the new vendor token is known-good, not merely assumed.

**Still not verified, and not claimed: the foreign-uid bind mount.** The first attempt appeared to
pass and was wrong. A named volume cannot simulate it: Docker **re-initialises an empty named volume
from the image's directory**, so a `chown 99:99` applied via a helper container came back as
`10001:10001` inside the app container — measured, not assumed. Windows bind mounts also synthesise
ownership, so this genuinely needs a real Linux Docker host.

### How that evidence was finally obtained, and what it immediately caught

Getting a run to execute took three attempts, and the intermediate failure is worth
recording because it wastes a lot of time if you meet it cold. T18 landed while
GitHub Actions was **disabled** for the repository, so that push triggered nothing.
Actions was then enabled — and the run still died in 0s, because **the account's
billing was locked**. GitHub starts no workflow in that state, and it reports the
situation as `conclusion: startup_failure` with the workflow recorded as
`{"name": "", "path": "BuildFailed", "state": "deleted"}`, while `gh run view`
volunteers "This run likely failed because of a workflow file issue." None of that was
true. Verified clean before the cause was known: YAML structure, LF line endings,
pure-ASCII bytes, no tabs/BOM/trailing whitespace, and all three pinned action SHAs
resolving upstream. **Check billing before suspecting the workflow.** (`workflow_dispatch`
was added afterwards, because a `startup_failure` run cannot be re-run and retrying
otherwise needs an empty commit.)

**The first executable run found two real Linux defects that six phases of Windows-only
gates could not have caught** — both instances of the same disease as T13f: a result that
depends on *who ran it*.

1. **The suite had never passed on Linux** — `16 failed, 1376 passed`. Fixed in T20.
2. **mypy was host-dependent** — 25 Windows-only-API errors on Linux, clean on Windows.
   Fixed by pinning mypy's analysis platform; see the T21 notes.

Both were fixed before the green run above. The lesson generalises: for the four phases
before this, "green" meant "green on Windows", and nothing in the process distinguished
the two. That is the value CI added on day one.

Because this is a private repository, runs consume the account's Actions minutes — three
jobs per push, one of which builds the container image.

**Still operator-only (verbatim scope):**

- Server acceptance of a Linux-synthesized device fingerprint (disposable account).
- Live Steam login on Linux without a desktop client — QR *and* password + Steam Guard — and whether app 3224770 must already be attached.
- Live master download from the game's CDN, restart persistence, and one career start with a real account.
- The three HTTP stacks (`curl_cffi`, `urllib`, Node) under a custom CA and standard proxy variables.

The census is now complete — all seven surfaces plus both verifiers and the critic reported. The filesystem-path / case-sensitivity surface (§2b) was the last to land and cleared.

---

## 11. Pre-existing bug found in passing (not Linux, not in this plan's scope)

`frontend/src/components/setup/RacePickerDialog.tsx:152` and `frontend/src/components/setup/RaceSchedule.tsx:314` both build `/races/<race name>.png`. Of 402 references in `assets/data/uma_race_data.json`, **26 (18 unique names) have no matching file at all** — the UI silently falls back to broom/type text:

Zen-Nippon Junior Yushun · Marine Cup · Kanto Oaks · Sparking Lady Cup · Mercury Cup · Cluster Cup · Sazanka TV Hai · M.C. Nambu Hai · Ladies' Prelude · Tokyo Hai · Queen Sho · TCK Jo-o Hai · Kawasaki Kinen · Empress Hai · Diolite Kinen · Tokyo Sprint · Kashiwa Kinen

Broken identically on Windows today. Either add the 18 PNGs under `assets/races` or stop requesting images for names with no asset. Tracked separately — do not fold into the Linux work.

---

## 12. Progress log

Branch: `feat/linux-support` (from `main` @ `ea60691`). T1–T18 are committed and
pushed. T19 is complete in the working tree and deliberately uncommitted and
unpushed per the task instruction.

| # | task | phase | status |
|---|---|---|---|
| T0 | census + plan + Phase 0 decisions | 0 | ✅ done |
| T1 | B1 portable device identity | 1 | ✅ done |
| T2 | B2 passphrase-derived KEK secret backend | 1 | ✅ done — **Phase 1 complete** |
| T3 | B4 non-mutating Node dependency check | 2 | ✅ done |
| T4+T5+T6 | B6 single state root, B7 XDG `master.mdb`, B5 no import-time source writes | 2 | ✅ done — **Phase 2 complete** (merged: the cutover cannot be partial, and the exit gate cannot pass without B5) |
| T7 | master bootstrap verified + block career start on missing master (B8) | 3 | ✅ done — **Phase 3 complete** |
| T8+T10 | B3 QR poll dead-end, B10 QR child-process reaping | 4 | ✅ done |
| T9 | B9 file modes 0700/0600 | 4 | ✅ done — already satisfied by T2 and T5, no new work needed |
| T11+T12+T13 | B11 monotonic clocks, B12 port preflight, widen the Frida guard | 4 | ✅ done |
| T13b | portable keyring: one command to make the state root OS-independent | 4 | ✅ done |
| T13c | Windows/Linux **feature-parity** matrix | 4 | ✅ done |
| T13d | close the **wire-visible** parity gaps | 4 | ✅ done |
| T13e | close the determinism/consistency parity gaps | 4 | ✅ done — **Phase 4 complete** |
| T13f | restore the declared Python 3.11 floor (gates had only ever run on 3.12+) | 4 | ✅ done |
| T14 | close the Discord webhook leak (`discord.py:31`) + settings/accounts leak audit | 5 | ✅ done |
| T15+T16 | configurable bind address/port **+** auth gate + reverse-proxy contract | 5 | ✅ done — landed as one commit, see [T14 notes](#t14-notes--the-webhook-was-not-the-worst-of-it) |
| T17 | container image | 5 | ✅ done — **and now actually built green in CI** (1m5s) |
| T18 | automatable Linux smoke + first CI | 6 | ✅ done — CI **observed green** on `ubuntu-latest`; operator-only Phase 6 smoke still remains |
| T19 | docs (`docs/linux.md`, README/DEPENDENCIES fork, `engines`, drop `Requests`) | 7 | ✅ done |
| T20 | make the suite actually pass on Linux (16 CI failures) | 6 | ✅ done |
| T21 | pin mypy's analysis platform so its verdict is host-independent | 6 | ✅ done — **Linux CI fully green** |

**Defined by T18 but not yet evidenced:** the supported `x86_64` binary-wheel
check, explicit Linux app import, non-root read-only-checkout import with
external state, real POSIX mode-bit test, and build-only container job. Actions
is disabled for the repository, so push and PR events currently trigger
nothing. T7 independently settled master-bootstrap peak RSS.

**Still operator-only (verbatim scope):** server acceptance of a Linux-synthesized device fingerprint (disposable account); live Steam login on Linux without a desktop client — QR *and* password + Steam Guard — and whether app 3224770 must already be attached; live master download from the game's CDN, restart persistence, and one career start with a real account; the three HTTP stacks (`curl_cffi`, `urllib`, Node) under a custom CA and standard proxy variables.

---

## 13. Plan closure

T1–T19 are complete. The implementation now has a Python 3.11 floor, portable
run-only Linux paths, a versioned secret-key wrapper with DPAPI deliberately
remaining the Windows default, one writable state root, parity hardening, an
authenticated bind boundary, private container packaging, CI definitions, and
operator documentation. Windows remains the primary and best-tested platform.

One repository setting remains outside the implementation: GitHub Actions is
disabled. The owner must enable it before T18 can produce hosted evidence for
Linux wheel resolution, import, read-only checkout, POSIX modes, frontend gates,
or the container build. Because the repository is private, those runs consume
the account's Actions minutes.

**The exact work still requiring an operator's supported Linux box is:**

1. Start and restart the bare-host/systemd service with file-backed passphrase
   credentials and confirm the UI is served from loopback.
2. Prove server acceptance of a fresh Linux-synthesized fingerprint with a
   disposable account. A state root moved with T13b keeps its Windows-registered
   identity and does not exercise this risk.
3. Exercise both live Steam paths without a desktop client: QR and
   username/password plus Guard, including whether app 3224770 must already be
   attached to the Steam account.
4. Complete a live headless master download from the game CDN, restart with
   persisted state, and start one career with a real account.
5. Exercise `curl_cffi`, `urllib`, and Node independently with a custom CA and
   standard proxy variables; no cross-stack CA/proxy contract is currently
   claimed.
6. Start and restart the private container, including a real foreign-uid bind
   mount. T18's job is build-only even after Actions is enabled.

The Windows-only RE and capture scripts remain deliberately out of scope and
still use checkout-local `uma_runtime` paths. They do not participate in Linux
startup or account discovery.

### Running the gates

Run them on Python 3.11; see the T13f notes for why a newer interpreter is not
acceptable evidence for the floor.

```bash
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m flake8
.venv/Scripts/python.exe -m mypy career_bot backend uma_api uma_data integrations main.py core
npm --prefix frontend test
npm --prefix frontend run build
```

### T1 notes

`uma_api/device.py` grew a non-Windows branch (DMI product/vendor → `/etc/machine-id` → the unchanged `sha1(device_name_machineid_seed)` formula) plus five `UMA_DEVICE_*` overrides that win on **both** platforms — that env escape hatch is what an operator reaches for if the server rejects a synthesized fingerprint, so it is load-bearing, not a convenience.

Two things worth remembering:

- **`get_os()` was a live wire-leak.** It built `f"Windows 11  ({platform.version()}) 64bit"`, so on Linux the kernel version string would have gone straight onto the wire while the client claims to be the Steam/Windows build. Now pinned off-Windows, and every synthesized string is filtered so it can never contain "linux".
- **Probing is lazy via short-circuit, not a rewrite.** `uma_api/client.py` passes a `Mapping` whose `__getitem__` calls `get_hwid()` once and memoizes. Both consumers were already `x or y or profile[k]`, so a complete saved identity never touches hardware — asserted by a test that makes `get_hwid` fail outright. `uma_api/identity.py` needed no logic change; it was already lazy.
- `uma_data/master_updater.py`'s guest client deliberately passes **no** explicit fingerprint. A shared constant there would have given every install an identical `device_id` and a fake `127.0.0.1`, and would have changed what Windows sends today.

Gate: 1224 passed (from 1213), flake8 clean, mypy clean over 159 files. Note `mypy .` fails on vendored RE dumps under the gitignored `uma_runtime/` — the real target is the package list.

### T2 notes

Keyring file is now `UMAKEY1` + a one-byte backend discriminator. The passphrase body is `kdf_id | N,r,p,dklen | salt | nonce | tag | wrapped_key` (105 bytes), with the whole header as GCM associated data, so the stored parameters cannot be edited without breaking the tag. scrypt is `N=2**16, r=8, p=1` — 64 MiB, ~125 ms.

- **The pre-existing `.keyring` is a bare DPAPI blob with no header at all**, so the reader still accepts that exact shape. Existing Windows installs need no migration and notice nothing. A blob starting with `UMAKEY` but not `UMAKEY1` is rejected rather than guessed at, so a future `UMAKEY2` can never be misread as a DPAPI blob.
- Reads dispatch on the file's own format; only *creation* consults the selection rules (`UMA_SECRET_BACKEND` → passphrase if configured → DPAPI on Windows → typed error). A set passphrase therefore never silently re-wraps an existing DPAPI keyring.
- Passphrase comes from `UMA_SECRET_PASSPHRASE` **or** `UMA_SECRET_PASSPHRASE_FILE`. The file form is not a convenience: systemd `LoadCredential` and Docker secrets both deliver secrets as a file, never as an environment variable, so Phase 5 depends on it.
- Wrong passphrase raises `SecretStorePassphraseError` (a `SecretStoreKeyError`, so existing catches still work) with a message that does **not** claim corruption — GCM failure is indistinguishable between a wrong key and a damaged file, so the message names the far likelier cause.
- Keyring and secret files are `0600`, their directory `0700`, on POSIX.

Three defects were found while reviewing the first pass and fixed before the commit:

1. **scrypt was re-derived on every read and write** (~125 ms each). `list_all()` loads every account's config, and one auth path loads both config and Steam token per account, so ten accounts cost ~1.27 s. Master keys are now memoized on `(resolved path, st_mtime_ns, st_size, st_ino, sha256(passphrase))`, with `clear_key_cache()` exposed for rotation and test isolation. Cold 127 ms → warm 0.7 ms; the ten-account listing 1271 ms → 135 ms.
   Caching would have quietly **voided** two of the new tests — parameter-durability and wrong-passphrase both write a keyring then reopen it — so the test module clears the cache around every test, and the durability test was confirmed to still fail when stored-parameter handling is deliberately broken.
2. **Wrapping `OSError` in a typed error changed failure semantics repo-wide.** `backend/app/domain/account_store.py:16` deliberately treats `OSError` as best-effort (return `False`) while letting typed secret-store errors propagate. Wrapping disk-full / read-only-filesystem failures flipped four `save_*` functions from returning `False` to raising. `_atomic_write` propagates `OSError` again; the file-descriptor leak fix and the permission work were kept.
3. **The parent-directory `chmod` could abort an otherwise-valid write.** On a container bind mount owned by another uid it fails permanently. Now best-effort; the `chmod` of the freshly created temp file stays strict, since that one guards the secret and cannot fail for ownership reasons.

Gate: 1257 passed (from 1224), flake8 clean, mypy clean over 159 files.

### T3 notes

`check_deps()` had four defects, not one. Beyond mutating the checkout mid-login, **`npm install` at the repo root fires the root `postinstall`, which builds the entire React frontend** — so a first Steam login could silently become a multi-minute UI build inside the request. It also only checked that a `node_modules` directory existed, so a pruned or partial install passed and then failed deep inside the Node script; and it raised a bare `Exception('node missing')`.

Now it verifies and never installs: `node` on `PATH`, then `steam-user` and `steam-session` individually, each requiring an actual `package.json` so an empty leftover directory does not pass. Failures raise `NodeDependenciesError` naming exactly which packages are missing and the command to run. `subprocess` is no longer imported by the module at all, and a test fails if any subprocess is spawned. The auth layer already surfaced `str(exc)` as the API `detail`, so no call-chain change was needed — a route-level test pins that.

**Consequence to carry into Phase 5:** the root `postinstall` still builds the frontend on any explicit `npm install`, so there is no root-level way to install *only* the runtime Node packages. A run-only or container provisioning step must bake `dist` at image-build time rather than expect a lightweight runtime install.

Gate: 1264 passed (from 1257), flake8 clean, mypy clean over 159 files.

### T4+T5+T6 notes — single state root

`core/runtime_paths.py` is the one resolver: `resolve_state_root(source_root) -> StatePaths`. Precedence is `UMA_RUNTIME_DIR` → `settings.json` `runtime.state_root` → **`<source_root>/uma_runtime` if it already exists** → platform default. The renamed default is `$XDG_STATE_HOME/manhattancafe-uma-auto` or `~/.local/state/manhattancafe-uma-auto` on POSIX and `%LOCALAPPDATA%\ManhattanCafe-uma-auto` on Windows. At that final layer, an existing renamed directory wins; otherwise an existing legacy `mcqueen-uma-auto` / `Mcqueen-uma-auto` directory wins untouched; otherwise the renamed path is returned for a fresh install. `base_dir` now strictly means the source/assets root; `AppContext` carries `state_root` and `state_paths` separately.

**A design pass proposed a transactional migration engine — lock, staging tree, journal, hash verification, source-manifest stability checks, `StateRootConflictError` — and that was deliberately rejected.** Legacy state only exists on already-working Windows installs; a fresh Linux install and a container both start empty, and the container sets the root explicitly. The whole engine would therefore exist only to relocate state that currently works, manufacturing the exact risk we were trying to avoid. Instead: **legacy-wins-if-present**, so an existing install keeps using the directory it already uses, with no migration, no marker, and no lock. The "state in both locations" case cannot arise, so no conflict detection is needed either. Relocation is opt-in and manual. The existence test uses `is_dir()`, so a fresh install never creates `<repo>/uma_runtime` and cannot latch onto it later.

- **The keyring heuristic was the trap.** `_keyring_path_for` walked ancestors looking for a directory *named* `uma_runtime`, falling back to the secret file's own parent — so once the root could move, the keyring and the ciphertext it unwraps could resolve to different roots and every account would become undecryptable. It now takes an explicit `state_root`, always returns `<state_root>/.keyring`, and raises a typed error for any payload outside the root, so a stray `.keyring` cannot be created beside an account file.
- **Account discovery was the second trap.** `uma_api/session.py` scans for account names independently of the stores; had it kept scanning the old directory, accounts would have stayed invisible with their files perfectly intact. `SessionManager` now takes the state root and scans only `<state_root>/accounts`, still excluding `*.steam.json`, with no legacy fallback.
- State the first census missed and this task covers: `event_catalog.json`, runtime `event_prefs.json` writes, `rankpoint_probes.jsonl`, `crash_trace.txt`, `bot_config/active.json`, `presets/`, `race_presets/`, `discord.json`.
- Shipped assets stay put: `data/bot_config/default.json` (`ensure()` no longer rewrites it), `data/json/event_prefs.json` as a read-only seed, the five master-derived JSON files, tracked event data, `data/images/`, `assets/data/uma_race_data.json`.
- `.timing_dna` moved to `<state_root>/.timing_dna` and is created lazily and atomically — never at import.

**T5b — a regression caught in review.** The first pass removed **both** automatic regenerations of the five master-derived JSON files, because they wrote into the tracked `data/json/`. But the exit gate only constrains *import* time, so dropping the post-login trigger was never required. The original called it "auto-updated + hot-reloaded": after a game update, `master.mdb` refreshed and the derived data followed. Without it, `master.mdb` updates while the JSON the bot actually reads goes stale **silently** — self-inflicted B8. The real problem was only the write destination, so the fix moves it: generation now targets `<state_root>/master_json/`, reads go through one `resolve_master_json_path()` helper (state root first, tracked seed fallback, per-file), both triggers are restored — startup only when output is missing or older than `master.mdb`, keeping the pre-existing `SWEEPY_SKIP_STARTUP_GEN` hatch — and a stale state that cannot regenerate now logs a warning naming `scripts/generate_master_data.py`. The five tracked files are byte- and mtime-identical.

**Phase 2 exit gate** (`tests/test_source_tree_exit_gate.py`): snapshots every file under the source tree as `(size, st_mtime_ns)`, sets `PYTHONDONTWRITEBYTECODE=1`, redirects `UMA_RUNTIME_DIR` / `XDG_STATE_HOME` / `XDG_DATA_HOME` / `LOCALAPPDATA` / `USERPROFILE` to temporary directories, runs `from main import app` as a subprocess from an unrelated cwd, and asserts the snapshot is unchanged. It deliberately clears `SWEEPY_SKIP_STARTUP_GEN` so the escape hatch cannot mask the regression it exists to catch. Runs unconditionally on Windows and POSIX.

Deferred: the RE/capture scripts (`capture_*`, `dump_*`, `hook_rankpoint`, `probe_data_link`, `probe_master_download`, `record_traffic`, `resolve_url_literals`, `sniff_*`) still use `<repo>/uma_runtime` directly. They are Windows-only, out of Linux scope, and take no part in production startup or account discovery.

Gate: 1290 passed (from 1264), 1 skipped (POSIX-only permission-bit assertion, skipped on Windows), flake8 clean, mypy clean over 159 files.

**T18 follow-up:** the real POSIX mode-bit assertion and the non-root read-only-checkout import are now explicit Linux CI steps. A real foreign-uid container bind mount is not claimed by the build-only container job.

### T7 notes — data bootstrap correctness

The complete first-run path is platform-neutral after T1 and T4+T5+T6: the
guest pre-download call needs no account/authentication, the CDN walk selects
the Windows asset branch but uses only HTTP + LZ4 + SQLite, and both
`master.mdb` and generated JSON land under the resolved state/data roots. An
offline integration test now walks the real manifest/decompression/write/
generation chain; no test contacts the live CDN.

Career start now preflights only fatal consumer dependencies. Unity Cup requires
`single_mode_route_race`, `single_mode_race_group`, and
`single_mode_scout_chara`; MANT does not inspect those tables. A present generated
JSON file that is older than `master.mdb` blocks every runner scenario because
it shadows the shipped seed and can skew race planning, skill purchases, spark
filters, or Unity support scoring. TP campaigns, card-to-character mapping, and
succession/G1 rank-point tables retain their existing fallbacks and do not block.
Both fresh start and active-career resume log and return the same actionable
diagnostic.

Memory was measured offline with the installed production `master.mdb`
(16,150,528 bytes; LZ4 object 6,122,494 bytes). Peak RSS for download +
decompress + atomic write + JSON generation fell from 63.38 MiB to 44.86 MiB
after streaming the master download/decompression and iterating SQLite cursors
without `fetchall()`. With the backend application modules already resident,
the streamed bootstrap peaked at 77.84 MiB. Container work should treat 128 MiB
as the hard minimum and prefer 256 MiB for database growth and allocator/runtime
headroom.

**The OOM risk turned out to be overstated, and that is worth recording plainly.** The census flagged the buffered download, the whole-database hold, and `fetchall()` as an unmeasured container hazard. Measured, `master.mdb` is only ~16 MB and the whole cold bootstrap peaked at 78 MiB with the app resident. The streaming work was still worth doing — 63 → 45 MiB, and it scales with future database growth rather than against it — but no container was ever going to OOM on this. One speculative risk closed with a number instead of a guess.

**One assumption to re-check, not verified by test:** the classification rests on MANT (scenario 4) never reading `single_mode_route_race` / `single_mode_race_group`, so a MANT career is blocked only by stale generated JSON. That came from reading the consumers, and it is the right call if true. If MANT careers ever show empty or wrong mandatory objectives, this table is the first place to look — the earlier `route_race condition_id` incident killed a career at turn 69, so the failure mode is real even if the scenario mapping here is correct.

Gate: 1300 passed (from 1290), 1 skipped, flake8 clean, mypy clean over 160 files. A separate full run with `USERPROFILE` redirected to an empty profile also passed (1297 passed, 4 skipped), confirming the suite does not quietly depend on this machine's installed game database.

### T8+T10 notes — QR login lifecycle

**B3 was two silent dead-ends, not one.** `qr_poll` persisted the refresh token and returned the snapshot:

1. **Persistence raised.** `save_steam_token` catches only `(OSError, TypeError, ValueError)` and deliberately lets typed secret-store failures propagate, so the exact error a Linux box with no passphrase produces escaped as an HTTP 500 — and `QrPanel.tsx` caught *every* poll error and kept going ("Transient network error — keep polling"). The user scanned successfully, the token was dropped, and the panel said "Waiting for phone confirmation…" forever.
2. **Persistence returned `False`.** `confirmed` was still reported as success, so the client went on to `login()` and failed for a reason unrelated to what actually broke.

`confirmed` now means *persisted*. Both failure modes return a terminal `error` **in the response body** rather than raising — the frontend already stops on `status === 'error'`, so this fixes the dead-end without inventing a new client contract. The message names `UMA_SECRET_PASSPHRASE` / `UMA_SECRET_PASSPHRASE_FILE` so the operator can act without reading logs. The missing-token case gets its own message. `take_refresh_token()` turns out **not** to clear the token despite its name, which is now documented and tested — so a later poll can retry a failed persistence rather than having consumed it.

The frontend still tolerates transient transport failures but stops after three *consecutive* ones; a success resets the counter, so a single dropped request cannot kill a valid QR session.

**B10:** `terminate()` with no `wait()` left a zombie per attempt, and `start()` terminates before respawning, so repeated QR attempts accumulated them. Now terminate → bounded wait → kill → bounded wait, never raising. Reaping also runs on account removal and on application shutdown — there was no existing lifespan hook, so the app factory registers `SessionManager.shutdown()` on the router's shutdown event. `stop()` additionally bumps the generation counter and clears a `starting`/`pending` status, so a stopped session cannot report stale `pending` forever.

Gate: 1309 passed (from 1300), 1 skipped, flake8 clean, mypy clean over 160 files. Frontend — **not covered by the Python gate**, so run explicitly: vitest 471 passed across 38 files, and `npm run build` (which runs `tsc -b`) green.

### T13c/T13d/T13e notes — feature parity, not just "it starts"

The owner reframed the goal mid-Phase-4: **Linux must behave like Windows, feature by feature.** Everything up to that point had optimised for "Linux runs", which is a weaker property. A four-area audit (auth/accounts, career loop, data/updates, ops/UI) re-examined every user-facing feature under that lens, classifying each `IDENTICAL` / `DIFFERS` / `UNAVAILABLE` / `UNKNOWN`.

The framing that mattered: **a fallback that "degrades gracefully" but sends a different value to the server is a parity defect, not a success.** The original census had marked `race_telemetry` as "OK, degrades correctly" for exactly that reason.

**Wire-visible differences found and closed (T13d):**

- **`race_out` telemetry.** `screen_height()` probed the physical display on Windows and returned a hardcoded 864 elsewhere; that value quantizes into `button_info.ClickPosX/Y`. The audit's own numbers settled the risk question: reference point `(991,144)` gives `(9888888,1422222)` at 864 and `(9892586,1423393)` at 1080 — so **two Windows machines with different displays already send different values**, meaning the server tolerates a range and a fixed value cannot be out-of-range in principle. 864 is now canonical on every platform (`UMA_RACE_TELEMETRY_HEIGHT` overrides). The telemetry is synthesised and a bot host may be headless, so the probe bought nothing and cost determinism — and a rejected `race_out` can corrupt a career into a permanent playing-state lock.
- **Result-204 retry asymmetry.** Windows could switch a locally parsed version to the App Store version and retry once; a Linux host already on the App Store version raised immediately. Same server rejection, different attempt counts. Now source-independent. Local-game publishing stays authoritative, but a local-vs-App-Store mismatch logs both values instead of differing silently by platform.
- **Steam saw `LinuxUnknown`.** Both Node scripts now pin `clientOS` to Win11, matching what the real game client presents, with the option names verified against the installed packages.
- **`steam-user` wrote its Guard machine token outside the state root**, into OS-specific Node app-data. This directly undercut the T13b move procedure: convert the keyring, copy the state root, and you would *still* get a Guard challenge because the token lived elsewhere. Its `dataDirectory` is now `<state-root>/steam-user`. Migration note: tokens already in OS app-data are **not** carried over, so the first password login after upgrading may prompt once.

**Deliberately rejected.** The audit also proposed generating fresh-account fingerprints from one OS-independent synthetic profile on both platforms. That reaches parity by making Windows *worse*: real hardware is what the real client reports, and Linux synthesizes only because it has no choice. New-account fingerprint provenance stays a documented platform difference. T13d's initial pass also pinned the Steam `machineName` to a single literal constant; that over-corrected a value which already varied between two Windows hosts, and would have given every install of this bot an identical Steam device name — T13e replaced it with a per-install derivation in the same `DESKTOP-XXXXXXX` shape.

**Determinism gaps found and closed (T13e):**

- **Staleness was decided from raw `st_mtime_ns`.** NTFS and common Linux filesystems have different timestamp resolutions, so the same pair of files could be judged stale on one host and current on another — and T7 had just made staleness **block career start**, turning this into a career-start flake. This was a consequence of T7 that the census could not have caught. Freshness now comes from recorded provenance: a SHA-256 of `master.mdb` in `<state-root>/master_json/.provenance.json`. Existing generated files with no provenance are stale exactly once; a *missing* file still falls back to the shipped seed without blocking, preserving T7's policy.
- **Career-log discovery depended on filesystem case sensitivity.** Windows globs case-insensitively, Linux does not, so a differently-cased log filename produced **different catalog rows** — which feed user-facing event preferences. Two OSes would make different event decisions from the same data. Now explicitly case-insensitive.
- **Master-path overrides wrote into the source tree's `settings.json`**, which fails on the read-only checkout Phase 5 targets. Overrides now persist at `<state-root>/settings.json`; precedence is state overlay → shipped `settings.json` → platform default. This is the minimal version of the overlay deliberately deferred during the state-root cutover, now justified by a concrete requirement.
- **Generated data was not byte-identical across platforms** — `Path.write_text()` emits CRLF on Windows and LF on Linux. Both the generated master JSON and the Gametora scraper output are now explicit UTF-8/LF, which is also what makes the provenance hash above meaningful.
- Operational timestamps (trace and report filenames, report fields, Discord embeds, live clocks, crash traces) standardised on **UTC**, so two hosts in different timezones produce identically named and stamped artefacts. Values compared against the server are untouched.
- Frontend number formatting and skill/factor collation pinned to `en-US`; the Windows-only `C:\path\to\master.mdb` placeholder made platform-neutral.
- Windows stale-instance takeover now attempts `taskkill /PID`, waits, re-validates identity, then escalates to `/F` — matching the POSIX `SIGTERM`→`SIGKILL` escalation, so a stale instance gets the chance to run the shutdown reaping T10 added.

Gates: T13d 1345 passed; T13e **1357 passed**, 1 skipped, flake8 clean, mypy clean over 160 files, vitest 473 passed across 39 files, frontend build green.

### T11+T12+T13 notes — platform hygiene

**B11:** durations now come from `time.monotonic()` in the pacing floor, the circuit-breaker window, `career_bot/delay.py` and `career_bot/engine/reporting.py`. A wall clock stepping backwards (NTP, DST, a container syncing after start) could silently *shorten* the inter-request floor, and that floor is anti-detection behaviour, so the silent-shortening case was the dangerous one. `_last_raw_call_ts` turned out never to be persisted, logged or serialised — only pacing and `TimingDNA` read it — so its basis changed and its comment was corrected rather than splitting the field. Wall-clock is deliberately kept everywhere a value is persisted or displayed (warehouse, traces, reports, account store, auth) and everywhere it is compared against the server (TP campaign time, the manifest cache-buster, race telemetry `ClickServerTime`). Eleven RE scripts had the same elapsed-from-`time.time()` bug in their timeout loops and were fixed too — Windows-only and out of Linux scope, but the same defect class.

**B12 was also a pre-existing safety bug, not just a parity gap.** `kill_listeners_on_port` no-op'd off Windows, so a leftover instance turned into a raw uvicorn bind failure on Linux while Windows restarted cleanly — a real behaviour difference. But the Windows path `taskkill /F`-ed **whatever** was LISTENING on the port without checking what it was, so anything else legitimately holding 1616 got force-killed. Porting that logic to Linux unchanged would have duplicated the footgun.

Now it only stops a process it can positively identify as an instance of *this* application, on both platforms. POSIX maps the listening TCP/TCP6 socket inode through `/proc/<pid>/fd`, then checks `cmdline` and cwd; Windows checks the image via `tasklist` and only escalates to a CIM command-line lookup when the image is already a Python interpreter, so the expensive call is gated and every subprocess is bounded at 5s. Identity means Python/PyPy running this repo's `main.py` (or `-m main` from the repo root). **Unknown ownership is never killed** — it logs the port and PID and lets the bind fail with an actionable error, which is precisely what makes it safe to add the behaviour on Linux at all. POSIX escalates `SIGTERM` → bounded wait → `SIGKILL`, matching T10's reaping discipline, and both platforms re-check identity before force-killing to reduce PID-reuse risk. The trade is deliberate: a stale instance launched in an unrecognised shape now gets a clear diagnostic instead of a silent kill.

**T13:** the guard now scans 166 files across every runtime root plus `main.py`, `core/settings.py` and `core/runtime_paths.py`, permits exactly one script module (`scripts.scrape_gametora_effects`) instead of allowing `scripts` wholesale, walks the 162 modules reachable from `main.py` so a Frida import two hops down is caught, and detects aliased `importlib.import_module`, `__import__`, and constant string concatenation. Self-tests prove it **fires** — direct import, both dynamic forms, a non-whitelisted script, and a two-hop import. A guard with no failing case was the actual problem; the tree was already clean.

Gate: 1338 passed (from 1319), 1 skipped, flake8 clean, mypy clean over 160 files. No frontend change.

### T13b notes — the state root is now OS-independent on demand

This closes the gap §5 decision 4 left open. The old answer to "move an account to Linux" was `UMAACCT1` export/import, per account. But the encrypted payloads were **never** the problem: account configs and Steam tokens are AES-GCM `UMAENC1` blobs, byte-identical on every OS. **Only the 32-byte master key was locked to Windows**, because DPAPI wraps it for one Windows user.

So the whole install moves by re-wrapping one key. `scripts/portable_keyring.py --to passphrase --apply` unwraps the master key with DPAPI and re-wraps it with the passphrase KEK, touching no payload. Copy the state root, set the same passphrase, and every account decrypts **with its registered `udid` and `device_id` intact** — no re-authentication, no server round-trip. The reverse direction exists too, for someone settling permanently onto one Windows box who wants the passphrase friction gone.

**Policy: DPAPI stays the Windows default.** Portability is one deliberate command away rather than a tax every Windows user pays up front. Note this also means the "server may reject a synthesized Linux fingerprint" risk does **not** apply to a moved install — that risk only exists for accounts created fresh on Linux.

The keyring is the one file where a mistake is unrecoverable — a bad re-wrap makes every account permanently undecryptable — so conversion refuses to be optimistic. It stages the candidate to a private temp file, clears the key cache, re-reads it **through the production dispatcher**, compares the recovered key byte-for-byte, and then decrypts a real existing account file end to end. Only then does it write a timestamped `.keyring.backup-<UTC>` and atomically replace the live file. Rollback is pre-commit: any failure discards the staging file and leaves the live keyring untouched, which a test proves by injecting a verify-step failure and asserting byte-identical contents plus a non-zero exit. Default mode is a dry run that reports the state root, keyring path, current backend, and how many files it protects while modifying nothing. Neither the key nor the passphrase is ever printed, including on failure paths.

Five minimal helpers were exposed from `uma_api/secret_store.py` rather than duplicating format logic, and the shared pieces were **factored out** of the existing functions instead of copied — so the cache and validation paths still have one implementation. None of them widens the containment guarantee: that exists to stop *production* code writing a stray `.keyring` beside an account file, and `save_json`/`load_json` still route through `_master_key` → `_keyring_path_for`.

Procedure documented in [docs/linux.md](linux.md), linked from `README.md`, including what happens if someone copies the directory **without** converting (payloads intact, keyring unopenable, and the fix is to go back and convert — not to re-authenticate).

Gate: 1319 passed (from 1309), 1 skipped, flake8 clean, mypy clean over 160 files. Note `scripts/` is excluded from the mypy target and configured `ignore_errors`, so the script is covered by pytest and flake8 only.

### T17 notes — private, immutable application image with one state volume

`node:22-bookworm-slim` supplies a supported Node 22 runtime on Debian 12/glibc;
Debian's `python3` and `python3-venv` supply Python 3.11. The build asserts both
version floors, creates a locked Python virtual environment, installs the root
Steam packages with `npm ci --ignore-scripts --omit=dev`, and builds
`frontend/dist` separately from `frontend/package-lock.json`. An isolated npm
probe installed both Steam packages, returned `ignore-scripts=true`, and did not
create a frontend directory, so the root `postinstall` did not run.

The runtime defaults to uid/gid `10001:10001`, uses `python main.py`, binds
`0.0.0.0:1616`, and points both secret variables at `/run/secrets` files.
`UMA_RUNTIME_DIR=/state` makes the declared volume the exact state root. The
application and dependency trees are root-owned with write bits removed;
Compose adds `read_only: true`, one named state volume, and an ephemeral `/tmp`.
The named volume starts owned by the runtime uid. A foreign-uid bind mount can
instead run with its owning numeric uid/gid; best-effort chmod does not replace
the filesystem write permission that mount still needs.

`.dockerignore` removes source-control metadata, dependency trees, caches,
`uma_runtime`, secret files, and local state while retaining all shipped runtime
seeds and the runtime-imported scraper. The packaging test models ordered
negations and excluded parent directories. Teeth probes failed as intended when
`scripts/` was added and, separately, when `data/` was added.

The documented happy path is the local-only
`docker build -t manhattancafe-uma-auto .`; there is no registry or push step. Compose
uses file-backed API-token and passphrase secrets, a 256 MiB limit, a read-only
root, and the single `/state` volume. The docs identify the volume and its
backups as secret-bearing because they include the keyring, account files, and
Steam Guard machine token.

Gate: **1395 passed**, 2 skipped, flake8 clean, mypy clean over 161 files,
vitest 482 passed across 41 files, frontend build green. Docker is not installed
on this host. T18 defines the image build, POSIX mode-bit assertion, and non-root
read-only-checkout import on `ubuntu-latest`, but the account's billing is locked so those
jobs have not produced evidence. Image startup and a real foreign-uid bind mount
are not claimed by the build-only container job in any case.

### T19 notes — documentation and packaging close the plan

The Linux guide now documents the actual first-run split: Python 3.11 venv,
root `npm ci --ignore-scripts` for the two Steam runtime packages because
`check_deps()` verifies and never installs, and a locked frontend install/build.
It names the independent `curl_cffi`, `urllib`, and Node transports and keeps
custom-CA/proxy behavior explicitly open. Its systemd example uses
`LoadCredential=` for both secrets, `%d/<id>` file paths, a dedicated user,
`StateDirectory=`, and a strict single writable state root while retaining the
loopback bind by default.
The primary unit targets systemd 251+ because that is where `%d` was added;
the guide includes the documented `$CREDENTIALS_DIRECTORY` `ExecStart=` form
for Ubuntu 22.04's stock systemd 249.

The auth docs now match `uma_api/secret_store.py`: portable AES-256-GCM
`UMAENC1` payloads use one random 32-byte master key; only the versioned
`.keyring` wrapper varies. DPAPI remains the intentional Windows default,
passphrase mode derives a scrypt KEK elsewhere, and
`scripts/portable_keyring.py` re-wraps that key without rewriting payloads.
The headless update guide records local-game → App Store → shared/captured →
hardcoded `1.32.9` behavior rather than requiring a copied version file.

Both root and frontend package manifests declare Node
`^20.19.0 || >=22.12.0`. The frontend declaration is intentional because
`npm --prefix frontend ci` and the frontend gates are valid direct entrypoints
that do not consult the root manifest; the range comes from locked Vite 8. The
root lockfile and frontend lockfile carry the same metadata.

The dead `Requests==2.33.1` pin is removed. A shipped-path import search found
only `from curl_cffi import requests` in `uma_api/appstore_version.py` and
`uma_api/client.py`; no module imports the separate PyPI `requests` package.

The repository Actions API returns `{"enabled": false}`, so T18 evidence is
unavailable rather than pending. `docs/linux.md` carries the operator note
because repository enablement and private-repository minutes are deployment
facts an operator needs before relying on the documented CI.

Gate on local CPython 3.11.9: **1395 passed**, 2 skipped, flake8 clean, mypy
clean over 161 source files, Vitest 482 passed across 41 files, frontend build
green. Root and frontend `npm ci` succeeded. A real container build remains
unavailable on this host because no Docker-compatible engine is installed and
no hosted run can start while billing is locked; Dockerfile compatibility is limited to the static
packaging tests and the fact that its Node 22 base satisfies the declared range.

### T18 notes — the 3.11 floor finally has a Linux gate

`.github/workflows/ci.yml` is the first repository CI. It has three independent
`ubuntu-latest` jobs so Python, frontend, and container failures remain visible
instead of masking one another. Every action is pinned to a verified commit:
checkout v4.2.2, setup-python v5.6.0, and setup-node v4.4.0. Python is explicitly
3.11 and Node is explicitly 22.

The Python job is defined to install only `requirements.txt` and
`requirements-dev.txt`, plus
the locked root Node runtime packages with lifecycle scripts disabled. It never
installs `requirements-re.txt`. Its pip cache is keyed by the two Python
requirement files; the root npm cache is keyed by `package-lock.json`. It then:

1. downloads every runtime requirement with `--only-binary=:all:` into runner
   temp space, which would prove the supported Ubuntu `x86_64`/Python 3.11
   combination needs no source build;
2. imports `main.app` in a dedicated fast step;
3. selects the POSIX permission test directly, then runs the full `pytest -q`,
   flake8, and the documented mypy package list;
4. makes the whole checkout non-writable, proves a write probe fails, redirects
   all state outside the checkout, and imports from an unrelated cwd.

The read-only step first asserts `id -u != 0`; it never uses `sudo`, and the
Python import is the same non-root runner process. Root therefore cannot make
the write probe or the import pass by ignoring mode bits. A trap restores owner
write permission afterward so checkout's post-job credential cleanup can still
update `.git/config`.

On Linux the dedicated permission selector cannot skip: its only skip condition
is `os.name == "nt"`. At the current 1397-test collection, a clean hosted Linux
runner is expected to report **1392 passed, 5 skipped** in the full suite. The
five expected environmental skips are the installed-game parser, real DPAPI,
two local-`master.mdb` Unity team assertions, and the live-master route-group
assertion; the POSIX permission test moves from the Windows skip column to pass.
That expectation was **subsequently confirmed**: CI run `30605108220` reported exactly
`1392 passed, 5 skipped` on `ubuntu-latest` (§10).

One precision point for anyone re-reading this later: that run predates the last few
commits on this branch, which added container/launcher packaging tests. `HEAD` now
collects 1422 on Windows (1421 passed, 1 skipped) against the 1397 this paragraph was
written for, so the ~25 newest tests have never been executed on a hosted Linux runner.
Re-run CI at `HEAD` to restore an exact hosted count.

The frontend job caches from `frontend/package-lock.json`, uses `npm ci`, and
runs vitest plus the production build. ESLint is deliberately not a gate: the
four known pre-existing `react-hooks/set-state-in-effect` errors would make the
first CI red without detecting a T18 regression.

The container job is defined to run only
`docker build -t manhattancafe-uma-auto:ci -f Dockerfile .`. The tag is local and
unqualified; there is no registry login, credential, namespace, or push step.
Once Actions is enabled, the workflow is configured for pushes on every branch
and for fork pull requests; same-repository PR jobs skip the duplicate event
because the same commit is covered by its branch push.

The workflow remains unexecuted because the account's billing is locked, which
presents as `startup_failure` / `path: BuildFailed` rather than as a billing
error. T18 validation on
this host consists of action-SHA verification, workflow syntax/static
validation, inspection of all skip sites, and the five documented Windows gates
on Python 3.11 / local Node.

### T20 notes — the suite had never passed on Linux

The first executable CI run reported `16 failed, 1376 passed, 5 skipped` on
`ubuntu-latest`, against `1395 passed, 2 skipped` on Windows. §3 of this plan predicted
exactly this ("every Linux failure traces to B2, ~15 tests") and it stayed unverified for
six phases because there was no Linux runner.

Fifteen failures were one error: `SecretStoreUnavailableError: No portable secret-store
backend is configured`. T2 gave *production* a passphrase-derived KEK, so a real Linux
operator is fine — but the **tests** never configured one, so on POSIX
`_creation_backend()` correctly refused and everything that persists auth died: 5 in
`test_json_stores`, 8 in `test_steam_unbind`, 1 in `test_routes_accounts`, and
`test_login_recovery` downstream, where a failed token write turned `"authenticated"` into
`"failed"`.

`tests/conftest.py` now supplies a passphrase **only when DPAPI is genuinely
unavailable**, mirroring production's own selection rules. The obvious fix — `setenv` the
passphrase globally — was a trap: `_creation_backend()` prefers a configured passphrase
**over** DPAPI, so it would have silently switched Windows to the passphrase backend and
deleted DPAPI coverage on the platform where DPAPI is the shipped default. Two assertions
now make that impossible to do by accident:
`test_account_config_serialized_as_encrypted_bytes` asserts the on-disk keyring backend is
`dpapi` exactly when DPAPI is available, and `test_real_dpapi_round_trip_when_available`
calls `_creation_backend()` **unforced** and asserts it chose `dpapi` with no passphrase
(previously it forced `UMA_SECRET_BACKEND=dpapi`, so it proved strictly less).

**The 16th failure was a test bug, not a production one.**
`test_posix_writes_use_owner_only_modes` asserted a keyring at
`<state_root>/secrets/.keyring`, but `_keyring_path_for()` returns `<state_root>/.keyring`
by construction — which is exactly what the T4+T5+T6 cutover made explicit, so a keyring
and the ciphertext it unwraps can never resolve to different roots. The whole assertion
block was guarded by `os.name != "nt"`, so this POSIX branch had **never executed on any
platform**. It now checks the real location and keeps every `0700`/`0600` assertion.

Cost: a fresh `tmp_path` per test means a fresh keyring and a fresh scrypt derivation, so
the fixture also lowers the KDF cost for tests (~2.0s saved across the affected files). To
stop that leaking into production, `test_stored_scrypt_parameters_survive_default_changes`
now asserts the real defaults are exactly `(2**16, 8, 1, 32)` before writing with them.
`test_secret_store.py` opts out via a registered marker, since it manages its own
environment and KDF parameters and holds the tests that deliberately assert the
*unconfigured* behaviour.

### T21 notes — mypy's verdict must not depend on the host

With the suite green, Linux CI still failed mypy: 25 `Module has no attribute` errors for
`winreg`, `ctypes.windll` and `ctypes.FormatError`, all of which typeshed marks
Windows-only. The same code is clean on Windows. So mypy's answer depended on who ran it —
the same host-dependence as T13f, and it would have left CI permanently red.

Per-line `# type: ignore` was not available: `warn_unused_ignores = true`, so every ignore
Linux needed would itself error on Windows.

mypy now analyses as `win32` on every host. **This costs no POSIX coverage, and that was
verified rather than assumed:** the codebase gates platform behaviour on `os.name`, which
mypy does not narrow (it narrows `sys.platform`), so no branch is pruned. Injecting a
deliberate type error into `_posix_listener_pids` — POSIX-only code, unreachable on Windows
at runtime — is still reported (`gameproc.py:343`, "Incompatible types in assignment"). The
only POSIX-only API in use is already reached defensively as
`getattr(signal, "SIGKILL", 9)`, so it needs no platform-specific typing.

### T15+T16 notes — the bind opens, behind a gate that cannot be launcher-dependent

Landed as one commit for the reason recorded in the T14 notes: `POST /api/accounts/export` means a
commit that permits a non-loopback bind without the gate would put LAN-reachable account
exfiltration into history.

**Bind.** `--host` / `SWEEPY_HOST`, default `127.0.0.1`, following the existing `SWEEPY_PORT`
convention. Port behaviour is untouched. `parse_cli_args` now returns
`(port, account, debug, host)` — `host` appended so the first three positions stay put. The
"Access the Web UI at" line reports the host actually bound, and prints something usable for a
wildcard bind rather than a URL that may not resolve.

**Token.** `UMA_API_TOKEN` or `UMA_API_TOKEN_FILE`, env winning. The file form is not a
convenience — systemd `LoadCredential` and Docker secrets both deliver secrets as files — and it
follows T2's passphrase conventions, including tolerating exactly one trailing newline and treating
whitespace-only as absent. An unreadable or non-UTF-8 file fails startup with an actionable line.

**Enforcement is middleware, not a per-router dependency**, because a dependency has to be attached
to every router and the next router added would silently escape. It keys off the path prefix and
gates `/api` exactly as well as `/api/…`. Constant-time compare. `Authorization: Bearer` is
canonical; `X-Api-Token` is consulted only when `Authorization` is absent, so a malformed
`Authorization` cannot be rescued by the second header. Ungated by design: `/`, the SPA catch-all,
`/static`, `/assets/*`, and `GET /api/auth-gate` — the last so the UI can discover whether to
prompt. `tests/test_api_auth.py` enumerates every registered `/api/` route, materialises path
params, fires every registered method uncredentialed, and asserts the non-401 set is exactly
`{/api/auth-gate}`; that is what stops a future router escaping. (Its filter is
`startswith("/api/")`, so a route at bare `/api` would not be enumerated even though the middleware
does gate that path — a gap in the guard's reach, not in the protection.)

Probed for bypasses beyond the tests: uppercase `/API/`, `//api/`, `///api/`, `%2F`-encoded,
dot-segments, `;`-parameters, a trailing dot, and a Cyrillic homoglyph. Every one either 401s or
404s; none returns data.

**The interlock cannot live only in the CLI.** `require_token_for_bind()` refuses a non-loopback
host with no token configured — correct classification via `ipaddress` (all of `127.0.0.0/8`, `::1`,
and the name `localhost` are loopback; unresolvable names and a bracketed `[::1]` fail safe as
non-loopback), and deliberately no bypass flag. But it is called from `cli.run()`, so
`uvicorn main:app --host 0.0.0.0` skipped it entirely and served everything. So the guarantee is now
**also a property of the app**: when no token is configured, gated `/api/*` paths serve loopback
peers only. Peer classification uses `request.client` and never a forwarded header — those are
attacker-controlled, and trusting one would restore the exact bypass this removes. A `None` or
non-IP peer counts as local, which is semantically right rather than a test concession: uvicorn takes
TCP peers from `socket.getpeername()` and so always reports a numeric IP, while an absent or non-IP
peer means a Unix socket or a test harness. That rule is also why all 38 existing test files needed
no edits.

**The two 401s mean different things, and the frontend must not conflate them.** The token challenge
carries `WWW-Authenticate: Bearer`; the loopback-only refusal deliberately does not, because there
is no token to re-enter. This matters because the first implementation cleared the stored token on
*any* 401 — including `auth_service.py:684`'s "Game login failed" and any 401 from a reverse proxy —
which would have thrown away a correct token and pointed the operator at the wrong problem. The
frontend now clears only on a 401 whose challenge names the `Bearer` scheme.

**Frontend.** Operator-entered token in localStorage, sent as `Authorization: Bearer` on every
request. `apiJson` is the choke point, but `frontend/src/api/accounts.ts` uses a raw `fetch` for the
binary export and had to be wired separately — the one bypass in the tree; `RaceSchedule`'s fetch of
`/assets/data/uma_race_data.json` is public and stays ungated. On a gate 401 the token is cleared and
the entry screen returns, without a retry loop.

**Known limit, stated plainly:** a same-host reverse proxy connects *from* loopback, so it is
indistinguishable from a local client at the socket level. Neither the interlock nor the peer guard
can cover that shape — the token is the only protection there, and `docs/linux.md` says so next to
the nginx recipe rather than in a distant paragraph. The first draft of that recipe proxied `443` to
`127.0.0.1:1616` with no authentication anywhere, which would have published the whole
unauthenticated API over TLS; TLS is transport protection, not access control.

Also fixed while here: the new `App.tsx` gate effect called `setState` in its body, adding a
`react-hooks/set-state-in-effect` error to a file that had none. The reset moved into the retry
callback, which is the only path that needs it — behaviour-identical, one fewer cascading render.
Frontend lint is still not gated (Phase 6) and 4 pre-existing errors of that same rule remain
elsewhere.

Gate: **1386 passed** (from 1358), 2 skipped, flake8 clean, mypy clean over 161 files, vitest 482
passed across 41 files (from 474/39), frontend build green.

### T14 notes — the webhook was not the worst of it

`GET /api/settings/discord-webhook` no longer returns the token. The response is now
`configured` plus `webhook_preview`, and the `webhook_url` key is **gone** rather than masked —
a stale frontend must not be able to mistake a mask for a usable URL. Redaction keeps the
non-secret webhook **id** and replaces the token with a fixed-length `••••••••`, so the mask
never discloses the real token's length. `redact_webhook_url()` lives in the router service, not
`integrations/discord/notify.py`, because redaction is an HTTP presentation policy while `notify`
owns storing and using the real credential.

The helper fails closed: anything that is not an `https` URL on an allow-listed Discord host with
a `/api[/vN]/webhooks/<numeric-id>/<token>` path collapses to the bare generic mask, so an
operator-supplied custom value is never echoed back. Query string and fragment are dropped rather
than passed through, and credentials-in-userinfo or an explicit port also fall back to the generic
mask. Verified against a lookalike host (`discord.com.evil.io`), `http://`, a non-numeric id, a
tokenless path, and an unparseable IPv6 authority — none leak.

`set_webhook_url` and `test_webhook` were checked and already return no secret. So was the one
log site: `notify.py:558` logs `Discord webhook failed: {exc}`, and neither `HTTPError` nor
`URLError` stringifies to include the request URL, so the webhook does not reach the log.

**The audit found something worse than the item the plan sent us here for.**

| route | finding | severity |
|---|---|---|
| `POST /api/accounts/export` | re-encrypts the bundle under a **caller-supplied** passphrase, so the response is decryptable by whoever asked for it. It carries `viewer_id`, `udid`, `auth_key`, device identity and the Steam `refresh_token`. | **critical** |
| `DELETE /api/accounts/{name}` | unauthenticated and destructive — stops the session and deletes both credential files | high |
| `GET /api/accounts` | active-career snapshots expose rental/friend viewer ids; runner `last_error` can carry server-returned viewer ids. No bearer token. | low |

`/accounts/export` **cannot be redacted** — exporting secrets is the endpoint's entire purpose.
Only the auth gate can fix it. That falsifies this section's original ordering premise, which had
T14 closing "the leak" and T15 then safely opening the bind address:

> **T15 and T16 must land as a single commit.** A commit that adds a non-loopback bind without the
> auth gate would expose full account exfiltration to the LAN, so no such commit may exist in
> history — not even transiently. This is the same reasoning that merged T4+T5+T6 ("the cutover
> cannot be partial"). Concretely: a non-loopback host must be **refused at startup** unless the
> gate is configured, and the default stays `127.0.0.1`.

Frontend: the input no longer pre-fills, because pre-filling a mask meant clicking **Save Webhook**
would persist the mask string as the webhook — a data-loss bug introduced by redaction if left
unhandled. The card now shows `Configured: <preview>` as status text, refuses an empty Save with a
message pointing at the new destructive **Remove webhook** button, and only offers that button when
something is configured. Clearing is still possible, but only deliberately.

Teeth-verified independently of the implementer: re-adding `webhook_url=url` to the GET response
fails three tests, and making `redact_webhook_url` return the stored value verbatim fails three
(including the direct helper test). On the frontend, an untouched configured form asserts
`saveDiscordWebhook` is **not** called.

Gate: **1358 passed** (from 1356), 2 skipped, flake8 clean, mypy clean over 160 files, vitest 474
passed across 39 files (from 473), frontend build green.

### T13f notes — the 3.11 floor was never actually gated

Picking Phase 5 up on a fresh clone, the documented gate command did not run at all: `pytest`
aborted during collection. Two defects, both invisible to a 3.12+ interpreter, and both
pre-dating this branch's own gates:

1. **`scripts/probe_bootstrap.py:183` could not be parsed by Python 3.11.** It used a PEP 701
   multi-line expression inside an f-string, which is 3.12+ syntax. `tests/test_probe_bootstrap.py`
   imports the module, so a single unparseable script took down the **entire** suite at collection,
   not just its own test. Rewritten to hoist the expression into a local and reuse the module's
   existing `_bool_text()` helper, which is already `str(...).lower()` — same output, and the same
   idiom as the neighbouring probe prints. A tree-wide `ast.parse` sweep under 3.11 confirms this
   was the only unparseable file.
2. **`tests/test_secret_store.py` simulated a non-Windows host by patching the real `os` module's
   `name`.** That also changes what `pathlib.Path()` constructs, and on Python ≤3.12 instantiating
   the foreign flavour raises `NotImplementedError`. So `save_json`'s `Path(path)` blew up, two
   tests failed — and because pytest's own `_repr_failure_py` calls `Path(os.getcwd())`, the
   reporter crashed while formatting those failures and emitted an `INTERNALERROR` that hid which
   test had failed. Python 3.13 dropped the instantiation guard, which is exactly why a 3.14 run
   looked green.

The fix is a patchable predicate rather than a global mutation: `uma_api/secret_store.py` grew
`_is_windows()`, now the module's **only** platform gate (all three `os.name` checks route through
it), and the tests patch that function instead of `os`. Both directions were converted, which
matters because the two `os.name = "nt"` patches were the same bug in reverse — on Linux they
would have made `Path()` build a `WindowsPath` and raise, and one of them
(`test_legacy_headerless_dpapi_keyring_is_read_on_any_platform`) calls `load_json`, so it would
have failed on the very platform its name claims to cover.

Both repaired tests were teeth-verified: deleting the non-Windows refusal in `_creation_backend()`
fails the destination-untouched test, and making `is_available()` ignore the forced backend fails
the backend-awareness test.

**Lesson for Phase 6 CI:** pin the CI interpreter to 3.11 as §5 decided. Had CI existed, neither
defect could have reached a handoff.

Gate (Python 3.11.9): **1356 passed, 2 skipped**, flake8 clean, mypy clean over 160 files. The two
skips are environmental — `test_client_version.py:97` needs an installed game, and
`test_state_root_invariants.py:183` asserts POSIX mode bits.

### T9 notes — already done

B9 needed no new work: T2 put the keyring and secret files at `0600` with their directory `0700`, and the T5 cutover routed `uma_api/trace.py` through `append_private_text` / `ensure_private_dir` and `integrations/discord/notify.py` through `atomic_write_private_text`. The Discord webhook — a bearer secret that was previously written at the process umask — is covered by that. Marked done on evidence rather than re-done.
