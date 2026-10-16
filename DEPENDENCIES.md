# Dependencies & Setup

Everything required to run this bot. Login and bot execution use the game API;
the game does not need to be installed or running.

## System requirements

- **Windows** — the primary, best-tested runtime. DPAPI remains the deliberate
  default for protecting the local master key.
- **Linux** — run-only support on Ubuntu 22.04+ or Debian 12+ with glibc.
  `x86_64` is supported and `aarch64` is best-effort. Linux uses the
  passphrase-derived key wrapper described in [`docs/linux.md`](docs/linux.md).
- **Python 3.11+** and **Node.js `^20.19.0 || >=22.12.0`**.
- A **Steam account** that owns the game, plus your own **Uma Musume account**.
  If the Steam identity is not bound yet, the UI falls back to Trainer ID + link
  password.

## 1. Node.js (do this first)

On Windows, install Node and provision the root packages with:

```powershell
winget install -e --id OpenJS.NodeJS
.\run-windows.cmd
```

On Linux, install a Node release in the supported range, then use the locked
root install. The platform launchers perform these steps automatically.
`check_deps()` only verifies Node and the two Steam packages; it never installs
them:

```bash
npm ci --ignore-scripts --omit=dev
npm --prefix frontend ci
npm --prefix frontend run build
```

Use `run-windows.cmd --force-ui` or `bash ./run-linux.sh --force-ui` to force a
dashboard rebuild as part of a normal launch.

Root runtime packages:

| Package | Version | Purpose |
|---|---|---|
| `steam-user` | ^5.0.0 | Fetches a fresh Steam session ticket for login |
| `steam-session` | ^1.7.2 | Steam QR / refresh-token login flow (`qr_login.js`) |

> `package.json` also pins an override of `protobufjs` to `^7.5.8` (transitive
> dependency of the two Steam packages).

## 2. Python

Python 3.11 is the supported floor, the interpreter configured for CI, and the
interpreter used by local validation. Create a runtime environment with the
platform-appropriate path.

Windows:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Linux:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

| Package | Version | Purpose |
|---|---|---|
| `fastapi` | 0.136.1 | Web UI / API server |
| `uvicorn` | 0.18.2 | ASGI server that runs FastAPI |
| `curl_cffi` | 0.7.4 | Game API requests with a real-client TLS fingerprint |
| `msgpack` | 1.2.0 | Encode/decode the game API's msgpack payloads |
| `lz4` | 4.4.5 | Decompress LZ4-framed game API payloads |
| `pycryptodome` | 3.19.1 | Request encryption (imported in code as `Crypto`) |
| `pydantic` | 2.13.4 | Request body models |

> Standard-library modules used (no install needed): `gzip`, `uuid`, `json`,
> `threading`, `asyncio`, `pathlib`, `sqlite3`, etc.

### Optional reverse-engineering tools

[Frida](https://frida.re) is used only by the manual RE/diagnostic scripts in
`scripts/` and the hook sources in `integrations/frida/`. It is never needed to
log in or run the bot. Install that optional toolchain with:

```bash
pip install -r requirements-re.txt
```

Those scripts may require the game to be installed and running; the bot runtime
does not.

## 3. Run

Windows:

```powershell
.venv\Scripts\python.exe main.py
```

Linux:

```bash
.venv/bin/python main.py
```
- Default port: **1616** → open **http://127.0.0.1:1616**
- Plain `main.py` starts in multi-account mode; add accounts from the
  dashboard. `main.py <port> --account NAME` binds one account at startup,
  loads saved game auth when present, and can mint a fresh Steam ticket from its
  saved refresh token. If neither exists, the server still starts and the web UI
  performs the Steam-only bootstrap.
- For client/resource version changes, follow `docs/headless-updates.md`; no auth
  capture is involved.

The login sequence is:

```text
Steam login on the web UI (QR or username + password + Guard code)
  -> mint a Steam session ticket
  -> saved game auth: tool/start_session + load/index
  -> no saved game auth: tool/pre_signup + tool/signup with a fresh udid
       bound Steam identity -> server returns viewer_id + auth_key
       no bound account -> Trainer ID + link password fallback
  -> persist portable AES-256-GCM UMAENC1 payloads under one 32-byte master key
       versioned key wrapper: DPAPI by default on Windows
       passphrase-derived scrypt KEK elsewhere
```

The payload format is unchanged across platforms; only `.keyring` wrapping is
platform-specific. `scripts/portable_keyring.py` converts an existing master
key between DPAPI and passphrase wrapping without rewriting account files.

## Notes

- Credentials, webhooks and logs live under the resolved state root, which is
  outside the checkout by default on a fresh install. An existing checkout's
  legacy `uma_runtime/` remains supported and gitignored.
- Pass `<port>` after `main.py` to use a different port. One server hosts **all**
  accounts (each request is routed by its `X-Account` header), so multi-account
  does *not* need one process per account — see the README.

## Development & testing

The pytest + Vitest suites and the FastAPI route-characterization net need test-only
deps that aren't required at runtime. Install both requirement files into an
isolated Python 3.11 venv.

Windows:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt
```

Linux:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt -r requirements-dev.txt
```

Run the five project gates from the repo root. Windows PowerShell:

```powershell
$env:SWEEPY_SKIP_STARTUP_GEN = "1"
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m flake8
.venv\Scripts\python.exe -m mypy career_bot backend uma_api uma_data integrations main.py core
npm --prefix frontend test
npm --prefix frontend run build
```

Linux uses the same gates with `.venv/bin/python`:

```bash
SWEEPY_SKIP_STARTUP_GEN=1 .venv/bin/python -m pytest -q
.venv/bin/python -m flake8
.venv/bin/python -m mypy career_bot backend uma_api uma_data integrations main.py core
npm --prefix frontend test
npm --prefix frontend run build
```

Current local baseline: **1395 passed, 2 skipped on CPython 3.11.9**;
flake8 clean; mypy clean over 161 source files; Vitest 482 passed across 41
files; production frontend build green.

`requirements-dev.txt` pins the development deps (`pytest`, `httpx`, `flake8`,
`mypy`); `.venv/` is gitignored. Pytest config (`pythonpath = ["."]`) and the
mypy config both live in `pyproject.toml`; flake8 keeps its own `.flake8`
(it has no native pyproject support).

## Lint & type baseline

Run the Python quality gates from the repo root:

```powershell
.venv\Scripts\python.exe -m flake8
.venv\Scripts\python.exe -m mypy career_bot backend uma_api uma_data integrations main.py core
```

Flake8 is a correctness gate for pyflakes, syntax errors, and the complexity
ratchet (`max-complexity` in `.flake8`); cosmetic pycodestyle rules remain
intentionally unenforced, and the constants facades intentionally use star
imports. Mypy is non-strict *globally* — untyped function bodies are unchecked —
but §12.6 added a **typing floor** (`check_untyped_defs = true` for
`career_bot.*`, `backend.*`, `uma_api.*`, `uma_data.*`, `integrations.*`, `main`
and `settings`), so in practice every project package is checked; `scripts/` is
explicitly excluded (`ignore_errors`) and tests are outside the invocation.
Both gates are green: **flake8 0 · mypy Success (161 source files)**.
