# ManhattanCafe Uma Auto

ManhattanCafe is a local, web-controlled automation bot for career scenarios in
*Umamusume: Pretty Derby*. Windows is the primary and best-tested platform.
Linux support is for running the bot on glibc-based systems; live-account parity
is not claimed where it remains unverified.

> [!WARNING]
> Automating gameplay may violate the game's Terms of Service and can get an
> account flagged or restricted. This project is for personal and educational
> use at your own risk.

## Windows

From the repository root, run:

```powershell
.\run-windows.cmd
```

The launcher creates or reuses `.venv`, installs the locked Python and Steam
runtime dependencies, builds the dashboard when needed, and starts `main.py`.
It uses `npm.cmd`, so PowerShell's script execution policy does not block npm.

Windows launcher options must come before the bot arguments:

```powershell
.\run-windows.cmd --force-ui 1616 --account A
.\run-windows.cmd --skip-ui -- --host 127.0.0.1 --debug
```

## Linux

From the repository root, run:

```bash
bash ./run-linux.sh
```

The Linux launcher performs the same setup and stale-dashboard check, then runs
the supported `python main.py` entrypoint from `.venv`:

```bash
bash ./run-linux.sh --force-ui 1616 --account A
bash ./run-linux.sh --skip-ui -- --host 127.0.0.1 --debug
```

Linux is run-only support on Debian 12+ or Ubuntu 22.04+ with glibc. `x86_64` is
supported and `aarch64` is best-effort. See the [Linux operations guide](docs/linux.md)
for systemd, reverse-proxy, credentials, migration, and hardening guidance.

## Docker

Build the private image locally, then run it through `compose.yaml`:

```bash
docker build -t manhattancafe-uma-auto .
docker compose up -d
```

Before starting Compose, create `secrets/uma_api_token` and
`secrets/uma_secret_passphrase`, each containing only its secret value. Compose
delivers them as files through `UMA_API_TOKEN_FILE` and
`UMA_SECRET_PASSPHRASE_FILE`; never put either secret directly in an environment
literal. The container has a read-only root filesystem and exactly one writable
persistent volume, mounted at `/state`.

**Nothing issues the API token — you choose it.** It is a shared secret compared
against what the client presents, so generate a random value yourself:

```bash
mkdir -p secrets && openssl rand -base64 32 | tr -d '\n' > secrets/uma_api_token
```

```bash
openssl rand -base64 32 | tr -d '\n' > secrets/uma_secret_passphrase
```

```bash
chmod 600 secrets/uma_api_token secrets/uma_secret_passphrase
```

On Windows, run these from the repository root in PowerShell 7:

```powershell
New-Item -ItemType Directory -Force secrets | Out-Null
```

```powershell
$b=[byte[]]::new(32); [System.Security.Cryptography.RandomNumberGenerator]::Fill($b); [IO.File]::WriteAllText("$PWD\secrets\uma_api_token", [Convert]::ToBase64String($b))
```

```powershell
$b=[byte[]]::new(32); [System.Security.Cryptography.RandomNumberGenerator]::Fill($b); [IO.File]::WriteAllText("$PWD\secrets\uma_secret_passphrase", [Convert]::ToBase64String($b))
```

Each file should be exactly 44 bytes — base64 of 32 random bytes, with no BOM and
no trailing newline. Check one:

```powershell
[IO.File]::ReadAllBytes("$PWD\secrets\uma_api_token").Length
```

`[IO.File]::WriteAllText` is deliberate: `>` and `Out-File` can prepend a UTF-8
BOM, which becomes part of the secret and produces a 401 that reads like a wrong
token rather than a malformed file. One trailing newline is tolerated; a BOM is
not.

The two secrets are not equivalent. The API token only guards the HTTP boundary,
so rotate it freely — rewrite the file, `docker compose restart`, then use
**Forget API token** in the UI so the browser stops sending the old one. The
passphrase wraps the state's master key, so changing it against an existing
`/state` volume leaves every stored account undecryptable. Keep it.

The image is private: there is no registry and no push workflow. Build it on the
machine that will run it. `compose.yaml` limits memory to 256 MiB; 128 MiB is the
measured hard minimum. Container operations and backup details are in the
[Linux operations guide](docs/linux.md#container-deployment).

## Prerequisites

- Python 3.11 or newer.
- Node.js `^20.19.0 || >=22.12.0` with npm.
- Outbound network access on first run for the App Store version lookup, the
  `master.mdb` CDN, and Steam authentication.

The game does not need to be installed or running. The launchers install only
`requirements.txt`; `requirements-re.txt` is optional Windows reverse-engineering
tooling and is never installed by default or supported as a Linux runtime
dependency.

The dashboard is served at <http://127.0.0.1:1616> by default. Both launchers
skip its build when `frontend/dist/index.html` is newer than the UI sources and
configuration. Use `--force-ui` to rebuild or `--skip-ui` to bypass the build.
All remaining arguments are passed to `main.py`, including the port,
`--host`, `--account`/`-a`, and `--debug`.

> [!IMPORTANT]
> Binding to anything other than loopback requires an API token from
> `UMA_API_TOKEN` or `UMA_API_TOKEN_FILE`; startup refuses the bind otherwise.
> The web UI prompts for the token and sends it with API requests.

## What it does

- Runs full careers through the game API without requiring the game client.
- Supports MANT / Trackblazer (the default and most tuned scenario) and Unity Cup.
- Scores training with friendship, stat-target, hint, skill-point, energy, and
  recovery awareness.
- Manages deck-aware shop purchases and saves climax-race items for their best use.
- Supports pause/resume, no-cooldown mode, multi-run loops, multi-account sessions,
  account-safety backoff, and Discord completion notifications.
- Logs in through Steam QR or username/password plus Steam Guard.

One server hosts all configured accounts. The dashboard tags requests with an
`X-Account` header, while each account keeps isolated credentials, sessions, and
run state.

## Career report API body cap

`UMA_MAX_CAREER_API_BODY_BYTES` limits each API request or response body retained
in career reports. It defaults to `2048` bytes (2 KiB). A body over the cap is
replaced with a metadata marker, so the full body is unavailable in the report
(while endpoint, direction, size, hash, and event-catalog summary remain). Set
the variable to `0` or a negative value to disable capping and retain bodies
instead of markers when debugging a payload. Valid JSON bodies are still
snapshotted when logged, so later state mutations cannot rewrite the report.
The full body is retained in the gzip crash sidecar; report-body omission only
matters when that sidecar is disabled or its storage guard has stopped writes.

## Career API crash sidecar

`UMA_CAREER_API_TRACE` controls a separate, run-scoped API sidecar and defaults
to `1` (enabled). Each career gets one private `*_payloads.jsonl.gz` file under
the runtime `trace_logs/api_payloads/` directory. It stores full, unredacted
request and response bodies by streaming JSONL through one gzip compressor; it
records every physical wire attempt, including transport failures and HTTP 5xx
retries, with a request ID and attempt number. It does not raise the
career-report cap or rewrite previously captured data. Set it
to `0` to turn the sidecar off. On the supplied 916-record career, the sidecar
took a median 51.7 ms total (0.056 ms per record) and produced about 672.8 KiB.
The compressor uses `Z_SYNC_FLUSH` every 20 records without `fsync`; the
checkpoints add about 350 bytes (0.052%) versus closing only at the end while
leaving a readable prefix after a killed writer.

`UMA_TRACE=1` remains the broader debug-tracing switch. During a career, the
run-scoped sidecar replaces any active debug trace writer so two compressors do
not capture the same calls; the original writer object remains open and is
reattached after notification completes. Outside a career, `UMA_TRACE` keeps its existing
behavior. `UMA_MAX_TRACE_LOGS` still defaults to `20` and prunes the oldest
closed sidecars. `UMA_CAREER_API_TRACE_MAX_BYTES` defaults to `268435456` (256
MiB) per active file, and `UMA_CAREER_API_TRACE_MIN_FREE_BYTES` defaults to
`536870912` (512 MiB). Reaching either limit stops further writes for that trace,
warns once, and never raises into the career; set either variable to `0` to
disable that individual guard. Active parallel runs and just-closed files being
uploaded are never pruned mid-use.

When a career ends with `error`, its sidecar is redacted once and attached to
the Discord webhook as `multipart/form-data`. Normal finished, stopped, and
paused careers send the existing embed only. `UMA_DISCORD_CAREER_TRACE_MAX_BYTES`
sets the attachment ceiling and defaults to `10485760` bytes (10 MiB). If the
redacted gzip is larger, the upload contains the newest records that fit plus a
`discord_trace_tail` marker stating how many earlier records were dropped. The
local file remains unredacted. Redaction is an exact, case-sensitive structural
key denylist for known credential fields. It does not inspect secrets embedded
inside strings (including `error`, `body`, or URL text), HTTP headers,
attachment metadata, or separately constructed Discord embed fields. A future
game patch can also introduce a new key that is not covered, so treat the
Discord channel as sensitive and do not share it with people who should not see
account diagnostics.

## Encrypted authentication

Saved authentication uses AES-256-GCM with a versioned key wrap: DPAPI on
Windows and a passphrase-derived scrypt KEK elsewhere. Only the key-wrap format
is platform-specific; encrypted account payloads remain portable. Follow the
[Linux move procedure](docs/linux.md#move-an-existing-install-from-windows)
before moving existing Windows state to Linux.

Frida is not part of login or normal bot operation. For game-patch handling on
machines without the game installed, see the
[headless update guide](docs/headless-updates.md).

## Credits

Based on the Sweepy decision engine and extended with the training, shop,
safety, multi-account, and Steam login features described here.
