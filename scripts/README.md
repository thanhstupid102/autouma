# `scripts/` — operator, reverse-engineering & dev tooling

These are command-line tools, not part of the bot's runtime. `main.py` / the
FastAPI app never import from here at request time. Most are developer or
reverse-engineering tools; `portable_keyring.py` is an operator migration tool.

Frida is optional and never needed to log in or run the bot. Install it only for
the 🎣 tools with `.venv\Scripts\python.exe -m pip install -r requirements-re.txt`.

> **Two exceptions where app code *does* touch `scripts/`** (do not move/rename these
> without fixing the importer):
> - The events service (`backend/app/routers/events/services/event_service.py`) does
>   `from scripts import scrape_gametora_effects` to rebuild the training-event effect
>   database. (`tests/test_client_version.py` likewise imports `publish_client_version`.)
> - Comments in `uma_api/client_version.py`, `uma_api/update_guard.py` and
>   `backend/app/app.py` point operators at **`scripts/publish_client_version.py`**.

## Conventions

- Run everything **from the repo root** with the project venv active
  (`.venv\Scripts\python.exe scripts\<name>.py`). A few resolve their own paths via
  `Path(__file__).parents[..]`, but root-cwd is the safe default.
- **Frida tools** (marked 🎣) attach to the live game process
  `UmamusumePrettyDerby.exe` by name and inject a JS hook. Only **one** Frida client
  may attach at a time — stop any other sniffer first, then launch the real game
  and reach the screen the script's docstring asks for.
- **Live-API tools** (marked 🌐) talk to the game servers directly through
  `uma_api.client.UmaClient` using a saved account session — no Frida, but a real
  account and network are required.
- **Offline tools** (marked ⚙) need neither Frida, the game, nor the network.

Most sniff/capture tools write to `uma_runtime/` (git-ignored). None of these are
*run* by the test suite, but `scripts/` is inside the flake8 gate
(`python -m flake8 ... scripts`) and two modules are imported by it — see the two
exceptions above — so a syntax/import break here does fail the gates.

---

## Capture — Frida → decrypted request/response JSONL (for offline diffing)

| Script | 🎣/🌐/⚙ | What it does | Run |
|---|---|---|---|
| `capture_boot.py` | 🎣 | Dumps the decrypted **boot sequence** (`start_session`/`load`/`index`/`read_info`) with their `APP-VER`/`RES-VER`, to diagnose stale-version login failures after a game update. Manual: after it attaches, go Menu → Return to Title → re-enter Home. Writes `uma_runtime/capture_boot.jsonl`. | `python scripts/capture_boot.py` |
| `capture_rental.py` | 🎣 | Records every outgoing request (AES/msgpack-decoded) to diff the real client's **friend-parent "rental"** flow against the bot's. Writes `uma_runtime/rental_capture_<ts>.jsonl`. | `python scripts/capture_rental.py` |
| `capture_outing_ids.py` | 🎣 | Sniffs `single_mode_free/exec_command` for the **Sirius/Throne "group outing"** command (type 3, id/group 390). Manual: reach turn 51/58/59, then click the outing in-game. Writes `uma_runtime/outing_capture_<ts>.jsonl`. | `python scripts/capture_outing_ids.py` |
| `capture_resource_urls.py` | 🎣 | Phase-1 of the master.mdb refresh RE: captures the **manifest + `master.mdb.lz4` URLs** at the title screen (hook `integrations/frida/js/uma_resource_urls.js`). Feeds `probe_master_download.py`. | `python scripts/capture_resource_urls.py` |
| `capture_native_urls.py` | 🎣 | Hunts the **root-manifest** URL (`root.manifest.bsv.lz4?r=`) through the **native** HTTP APIs (hook `integrations/frida/js/native_http_urls.js`), writing de-duplicated resource-looking URLs to `uma_runtime/native_urls.jsonl`. It waits for the game to launch (never launches it) — rename the local `meta` DB away first to force a manifest re-fetch, then go to TITLE only. | `python scripts/capture_native_urls.py` |
| `record_traffic.py` | 🎣 | Taps msgpack **pre-encrypt / post-decrypt** (hook `integrations/frida/js/uma_full_traffic.js`), logging the whole session's requests **and** responses to `raw.jsonl`. No AES key needed. | `python scripts/record_traffic.py [--out DIR] [--attach-timeout SEC]` |

## Sniff / probe — live inspection

| Script | 🎣/🌐/⚙ | What it does | Run |
|---|---|---|---|
| `sniff_endpoint.py` | 🎣 | Real-time print of each endpoint's decoded request payload + sanitized response hints; positional args are case-insensitive endpoint substring filters. | `python scripts/sniff_endpoint.py [filter ...] [--no-responses]` |
| `sniff_unity_cup.py` | 🎣 | Captures one manually-played **Unity Cup** run to sanitized JSONL (builds on `sniff_endpoint`). `--self-check` runs offline sanitize asserts only. | `python scripts/sniff_unity_cup.py [filters ...] [--all] [--responses] [--out PATH] [--self-check]` |
| `hook_rankpoint.py` | 🎣 | Decodes `single_mode_free/team` **start** requests to read ground-truth `current_succession_rank_point` + parent `trained_chara_id`s (career-start RE). | `python scripts/hook_rankpoint.py` |
| `sniff_spark_reroll.py` | 🌐 | Drives the live `factor_select`/`factor_lottery`/`load`/`finish` endpoints to RE the **spark-reroll (factor lottery)** flow. Needs `uma_runtime/accounts/<name>.json`. | `python scripts/sniff_spark_reroll.py {select\|reroll\|inspect\|finish [1\|2]} [--account NAME]` |

## Native memory dump / disassembly

| Script | 🎣/🌐/⚙ | What it does | Run |
|---|---|---|---|
| `dump_gameassembly_memory.py` | 🎣 | Reports the live PE/range map, then dumps readable **`GameAssembly.dll`** pages with 1 MiB reads and 4 KiB failure isolation. Writes a flat `.bin` plus `.coverage.json`; marks `<90%` `il2cpp` coverage as `.partial.bin`. | `python scripts/dump_gameassembly_memory.py --report-only` first, then `python scripts/dump_gameassembly_memory.py` |
| `dump_url_builder_mem.py` | 🎣 | Dumps the raw machine-code bytes of the resource **URL-builder methods** (by fixed RVA) for offline disassembly. | `python scripts/dump_url_builder_mem.py` |
| `resolve_url_literals.py` | 🎣 | Disassembles the dumped URL-builder bytes (capstone), resolves RIP-relative globals, and reads the live process to decode `Il2CppString` **URL literals**. Run after `dump_url_builder_mem.py`. | `python scripts/resolve_url_literals.py` |

## Master data — download / build `master.mdb` + JSON assets

| Script | 🎣/🌐/⚙ | What it does | Run |
|---|---|---|---|
| `probe_master_download.py` | 🌐 | Downloads a captured/explicit `master.mdb.lz4` (or manifest) URL and reports whether the payload is plain LZ4-SQLite or LZ4-wrapped **encrypted** data. | `python scripts/probe_master_download.py [--capture-file P] [--manifest-url U] [--master-url U] [--res-ver N] [--dry-run]` |
| `update_master_mdb.py` | 🌐 | Resolves the resource server/version, downloads + LZ4-decompresses + integrity-checks the current `master.mdb`, and replaces the local copy. `--headless` uses a guest client to self-resolve the version. | `python scripts/update_master_mdb.py --headless` (or `--base/--res-ver` / `--start-session-response`, `--dry-run`) |
| `generate_master_data.py` | ⚙ | Reads `master.mdb` (SQLite) and synthesizes the Sweepy JSON assets (`skill_data`, `chara_list`, `support_list`, `race_map`, `factor_map`, browser-facing race data). **Run as a module.** | `python -m scripts.generate_master_data [--db-path PATH]` |
| `gen_default_bot_config.py` | ⚙ | Regenerates the committed `data/bot_config/default.json` from the typed defaults in `career_bot/bot_config/defaults.py` (the single source of truth). `tests/test_bot_config_default_sync.py` fails if the two drift, so run this after changing the defaults. | `python scripts/gen_default_bot_config.py` |

## Scrape — gametora.com web scrapers (pure stdlib, network only)

| Script | 🎣/🌐/⚙ | What it does | Run |
|---|---|---|---|
| `scrape_gametora_effects.py` | 🌐 | Rebuilds `data/json/event_effects_scraped.json` (EN training-event names/owners/choice labels/effects). **Imported by app code** as `scripts.scrape_gametora_effects.scrape(...)`. | `python scripts/scrape_gametora_effects.py [--global-only] [--force] [--dry-run] [--out PATH]` |
| `scrape_gametora_events.py` | 🌐 | Scrapes each single-mode event's **choice count + owning chara/support/friend** (not effects/names) and merges into local JSON. | `python scripts/scrape_gametora_events.py` |

## Publish / account

| Script | 🎣/🌐/⚙ | What it does | Run |
|---|---|---|---|
| `portable_keyring.py` | ⚙ | Dry-runs or safely converts the resolved state root's existing master-key wrapper between DPAPI and passphrase protection. It verifies against a real encrypted account, creates a timestamped backup, and never rewrites account payloads. | `python scripts/portable_keyring.py --to passphrase [--apply]` |
| `publish_client_version.py` | ⚙ | Finds the installed Steam client, parses `bundleVersion` from `globalgamemanagers`, and writes `app_ver` into `uma_runtime/client_version.json` for the headless bot. Game installed, not running. | `python scripts/publish_client_version.py [--game-dir PATH] [--dry-run]` |

## Offline self-checks (no game / no network — plain `assert` scripts)

| Script | 🎣/🌐/⚙ | What it does | Run |
|---|---|---|---|
| `check_item_policy.py` | ⚙ | Exercises `MantItemManager` item-use/buy policy against hand-built fake state + a mock client; prints `item policy self-check ok` or raises on first failing assert. | `python scripts/check_item_policy.py` |
| `check_sirius_throne_early.py` | ⚙ | Asserts `MantStrategy`'s turn 1–25 Sirius/Throne `two_pal_deck` group-card / outing / recovery / race-skip logic against fake API state. ⚠️ **Currently fails** on its last check — see the note below. | `python scripts/check_sirius_throne_early.py` |
| `manual_checks/check_notify_spark_reroll.py` | ⚙ | Asserts the Discord webhook embed renders the spark-reroll original/rerolled/bot-choice block (`integrations.discord.notify._build_embed`). Silent + exit 0 on success. | `python scripts/manual_checks/check_notify_spark_reroll.py` |

> **Known failure — `check_sirius_throne_early.py`**: the final check,
> `check_auto_races_skip_summer_camp_but_user_scheduled_and_forced_races_run`,
> asserts the bot *skips* an auto-picked race during summer camp. That
> summer-camp auto-race guard was **deliberately deleted** in `eb140a6`
> ("remove auto fan-farming, races come from presets only") because
> `RacePlanner.choose` no longer invents races — it only returns user-preset
> ones, which that path always allowed through. The check's fake `Planner`
> still returns a program from `choose()` unconditionally, which real code no
> longer does, so the assertion is testing a contract that no longer exists.
> The other 12 checks in the file pass. Not a reorg breakage; left for the
> owner to decide whether to drop that sub-check or reshape the fake planner.
