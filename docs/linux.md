# Linux operations

Linux is supported for run-only deployments on Ubuntu 22.04 or newer and
Debian 12 or newer with glibc. `x86_64` is supported; `aarch64` is best-effort.
Windows remains the primary, best-tested platform, and the Windows-only
reverse-engineering and local-game inspection scripts are outside Linux scope.

## First-run setup

Install Python 3.11 and Node.js `^20.19.0 || >=22.12.0` using the appropriate
packages for the host, then run these commands from the repository root:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt

# Provision the locked Steam runtime packages without running root postinstall.
npm ci --ignore-scripts --omit=dev

# Install and build the dashboard reproducibly.
npm --prefix frontend ci
npm --prefix frontend run build
```

`uma_api.device.check_deps()` runs only when Steam authentication is needed. It
checks that `node` is on `PATH` and that root `node_modules` contains
`steam-user` and `steam-session`; it never installs anything. That is why the
root `npm ci --ignore-scripts --omit=dev` step is provisioning, not an optional
build convenience. For an interactive run, `bash ./run-linux.sh` performs this
setup, rebuilds a missing or stale dashboard, and starts the supported entrypoint.

Linux cannot create encrypted account state until a passphrase is configured.
Keep it in a root- or user-readable credential file outside the checkout, mode
`0600`, and point the process at it:

```bash
export UMA_SECRET_PASSPHRASE_FILE=/secure/path/manhattancafe-passphrase
.venv/bin/python main.py
```

A fresh install uses `${XDG_STATE_HOME:-~/.local/state}/manhattancafe-uma-auto`
as its state root unless `UMA_RUNTIME_DIR`, `settings.json` `runtime.state_root`,
or an already-existing checkout-local `uma_runtime` selects another location.
If the renamed platform default does not exist but the legacy
`mcqueen-uma-auto` directory does, that legacy directory is selected in place.

The first production run exercises these outbound network paths:

- The game service and Apple's public App Store version endpoint use
  `curl_cffi`. The unauthenticated pre-download call discovers the current game
  CDN base and resource version.
- The master manifests and `master.mdb.lz4` payload are downloaded from that
  CDN with Python's standard-library `urllib` transport.
- Steam QR, password/Guard, refresh-token login, and app-3224770 ticket minting
  use Node's own transport through `steam-session` and `steam-user`.

These are three independent HTTP stacks. None currently selects an application
CA bundle, and standard proxy-variable behavior has not been verified across
all three. A custom corporate CA or mandatory proxy is therefore still an open
operator validation item; test each stack before relying on such a network.

## systemd service

The example assumes a root-owned checkout at `/opt/ManhattanCafe-uma-auto`, the venv
and Node dependencies provisioned as described above, and a dedicated
`manhattancafe` system user and group. Put the passphrase and API token in separate
root-owned `0600` files under `/etc/manhattancafe/`. `LoadCredential=` copies them into
the service credential directory; the environment contains only file paths,
never either secret value.

```ini
[Unit]
Description=ManhattanCafe Uma automation service
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=manhattancafe
Group=manhattancafe
WorkingDirectory=/opt/ManhattanCafe-uma-auto
ExecStart=/opt/ManhattanCafe-uma-auto/.venv/bin/python /opt/ManhattanCafe-uma-auto/main.py
Restart=on-failure
RestartSec=5s
TimeoutStopSec=30s
KillSignal=SIGTERM

LoadCredential=uma-secret-passphrase:/etc/manhattancafe/uma-secret-passphrase
LoadCredential=uma-api-token:/etc/manhattancafe/uma-api-token
Environment=UMA_SECRET_PASSPHRASE_FILE=%d/uma-secret-passphrase
Environment=UMA_API_TOKEN_FILE=%d/uma-api-token
Environment=UMA_RUNTIME_DIR=/var/lib/manhattancafe-uma-auto

StateDirectory=manhattancafe-uma-auto
StateDirectoryMode=0700
UMask=0077

ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/manhattancafe-uma-auto
PrivateTmp=true
PrivateDevices=true
NoNewPrivileges=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
LockPersonality=true
CapabilityBoundingSet=
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6

[Install]
WantedBy=multi-user.target
```

`StateDirectory=` creates `/var/lib/manhattancafe-uma-auto` for the service user, and
`ProtectSystem=strict` plus `ReadWritePaths=` leaves that state root as the only
persistent writable application path. The empty `CapabilityBoundingSet=` drops
all Linux capabilities; the allowed address families still permit local IPC,
IPv4, and IPv6 network access.

The sample `ExecStart` does not pass `--host`, so the application keeps its
default loopback bind even though an API-token credential is present. A local-
only operator may remove the API-token `LoadCredential=` and matching
`Environment=` line. Add a non-loopback `--host` only while a readable token
credential remains configured; otherwise the startup interlock refuses the
bind.

The `%d` credential-directory specifier requires systemd 251 or newer (Debian
12 ships 252). Ubuntu 22.04's stock systemd 249 supports `LoadCredential=` but
not `%d`. On that version, remove the two `%d` `Environment=` lines and replace
`ExecStart=` with the following documented `$CREDENTIALS_DIRECTORY` expansion:

```ini
ExecStart=/usr/bin/env UMA_SECRET_PASSPHRASE_FILE=${CREDENTIALS_DIRECTORY}/uma-secret-passphrase UMA_API_TOKEN_FILE=${CREDENTIALS_DIRECTORY}/uma-api-token /opt/ManhattanCafe-uma-auto/.venv/bin/python /opt/ManhattanCafe-uma-auto/main.py
```

Keep the separate `Environment=UMA_RUNTIME_DIR=/var/lib/manhattancafe-uma-auto` line.

## API token and remote access

The server still binds `127.0.0.1` by default. Use `--host HOST` (or
`SWEEPY_HOST`) only when another machine or network namespace must reach it.
Every non-loopback bind requires an API token. Point at a credential file
instead of copying the secret into the environment:

```bash
export UMA_API_TOKEN_FILE=/run/credentials/manhattancafe-api-token
.venv/bin/python main.py --host 0.0.0.0
```

`UMA_API_TOKEN` takes precedence when both forms are set. The file may have one
trailing newline. A missing, unreadable, or non-UTF-8 file stops startup with an
actionable error. The UI stores the operator-entered token in browser local
storage and sends `Authorization: Bearer <token>`; `X-Api-Token` is supported
for non-browser clients.

### Choosing the token

Nothing generates or issues this token: the server only compares the presented
value against the configured one, in constant time, with no length or strength
requirement. That makes its strength entirely your choice, so generate a random
value rather than inventing a memorable one:

```bash
openssl rand -base64 32 | tr -d '\n' > /run/credentials/manhattancafe-api-token
```

Write the raw value with no BOM. One trailing newline is stripped, so `echo` is
safe, but a UTF-8 BOM becomes part of the token and yields a 401 that reads like
a wrong token rather than a malformed file.

### Browser token troubleshooting

If "API token saved in this browser." is immediately followed by "The API token
was rejected.", test the configured file against any gated `/api/...` path other
than `/api/auth-gate`:

```bash
token="$(tr -d '\r\n' < /path/to/uma-api-token)"
curl -i -H "Authorization: Bearer $token" http://127.0.0.1:1616/api/accounts
```

A `404` still proves the token passed the gate; a `401` does not. If `curl`
succeeds but the browser fails, the pasted value carried whitespace. Copy a
clean value with `(Get-Content -Raw secrets/uma_api_token).Trim() |
Set-Clipboard` in Windows PowerShell, or `tr -d '\r\n' <
secrets/uma_api_token | wl-copy` on Linux Wayland (`xclip -selection clipboard`
is the X11 equivalent).

An autofill highlight on the field, or a value longer than the configured token,
points instead to a saved login for the dashboard origin. Some browsers refill
that saved value after the page has loaded. Delete the saved login for that
origin (`about:logins` in Firefox, or the equivalent in another browser) and
try again. A private window is a quick way to confirm that a saved credential or
extension is responsible. For the fastest way back in, set
`localStorage.uma_api_token` to the clean token in the browser console and
reload; that bypasses the entry form entirely.

`secrets/` is wired only by Compose and the Dockerfile. A native run must set
`UMA_API_TOKEN_FILE` explicitly; a loopback-only bind needs no token.

Rotating the token is cheap because it only guards the HTTP boundary: rewrite the
file, restart the service, and clear the stale value from the browser with
**Forget API token** — otherwise the UI keeps presenting the old token and is
rejected. This is unlike `UMA_SECRET_PASSPHRASE`, which wraps the state's master
key and cannot be changed without re-wrapping it (see
[the portable-keyring procedure](#move-an-existing-install-from-windows)).

Startup refuses `0.0.0.0`, `::`, LAN/public addresses, and all hostnames other
than `localhost` when no token is configured. Fix the refusal by setting one of
the token variables, or keep the bind on loopback. Literal `127.0.0.0/8`, `::1`,
and `localhost` are loopback; other hostnames are deliberately not DNS-resolved
and fail safe as non-loopback.

Use `.venv/bin/python main.py` as the supported entrypoint. Launching
`uvicorn main:app` directly bypasses the CLI bind interlock; the application-
level peer guard still blocks unauthenticated API requests from non-loopback TCP
clients, which keeps that bypass from exposing the API directly.

**Before exposing a same-host nginx proxy, set `UMA_API_TOKEN_FILE`.** A reverse
proxy does not replace API authentication.
The Python server remains bound to loopback, so the CLI interlock cannot see
that nginx publishes it:

```bash
export UMA_API_TOKEN_FILE=/run/credentials/manhattancafe-api-token
.venv/bin/python main.py
```

The application-level peer guard cannot protect this proxy shape either. nginx
connects from loopback, making its requests indistinguishable from local clients
at the socket level; the token is the only access control here. Terminate TLS at
the proxy and preserve both supported authentication headers:

```nginx
server {
    listen 443 ssl;
    server_name manhattancafe.example.com;

    ssl_certificate     /etc/letsencrypt/live/manhattancafe.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/manhattancafe.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:1616;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header Authorization $http_authorization;
        proxy_set_header X-Api-Token $http_x_api_token;
    }
}
```

Do not expose the token-bearing UI over plain HTTP. TLS protects the bearer
token in transit, but it does not authenticate callers by itself.

## CI availability

`.github/workflows/ci.yml` runs three `ubuntu-latest` jobs — Python 3.11, frontend,
and a container build — on every branch push, plus `workflow_dispatch` for a manual
retry. All three are green: `1392 passed, 5 skipped`, flake8 and mypy clean over 161
source files, 482 frontend tests, and `docker build` in about a minute.

The Python job also proves the things that cannot be checked from Windows: `x86_64`
runtime wheels resolve with no source build, `from main import app` works on Linux,
real POSIX `0700`/`0600` mode bits are asserted rather than skipped, and the app
imports with a **genuinely read-only checkout** (non-root, write bits stripped, a
write probe proving it, state redirected elsewhere).

If a run ever completes in 0s with `startup_failure` and `path: BuildFailed`, check
the account's **billing** before suspecting the workflow — a locked account produces
exactly that, and it reads like a malformed workflow file. This is a private
repository, so runs consume the account's Actions minutes.

## Container deployment

Build the private image locally. The normal workflow has no registry and no
push step:

```bash
docker build -t manhattancafe-uma-auto .
```

The image uses Debian 12's glibc and Python 3.11 on the Node 22 Bookworm base.
The locked `steam-user` and `steam-session` modules and the compiled
`frontend/dist` are baked during the build; nothing installs at startup.

Create `secrets/uma_api_token` and `secrets/uma_secret_passphrase` outside
source control, with only the secret value and an optional final newline in
each file. Neither is issued by the application — generate both yourself, as
described under [Choosing the token](#choosing-the-token):

```bash
mkdir -p secrets && openssl rand -base64 32 | tr -d '\n' > secrets/uma_api_token
```

```bash
openssl rand -base64 32 | tr -d '\n' > secrets/uma_secret_passphrase
```

`secrets/` is already ignored by both git and Docker's build context, so neither
file reaches a commit or the image.

The Compose example exposes them only as files under `/run/secrets`.
Its file-backed secrets must be readable by the container's default uid/gid,
`10001:10001`; keep the files otherwise restricted. Then start the local image:

```bash
docker compose up -d
```

The container deliberately binds `0.0.0.0:1616`; the API token is therefore
mandatory, and the existing startup interlock rejects a missing token. Compose
publishes port `1616`, makes the root filesystem read-only, supplies an
ephemeral `/tmp`, drops all capabilities, and mounts exactly one persistent
writable volume at `/state`. `UMA_RUNTIME_DIR=/state` means `/state` itself is
the state root, with no extra `uma_runtime` directory.

The named volume is initialized as mode `0700` for uid/gid `10001:10001`. For
an existing bind-mounted state directory owned by another uid, either grant
that uid write access or run the image with the matching numeric `--user`.
The root-owned application and dependency files remain readable by an
arbitrary non-root uid. Best-effort chmod prevents foreign ownership alone from
aborting startup, but normal filesystem write permission is still required.

Use the Compose limit of 256 MiB where possible; 128 MiB is the measured hard
minimum. Stop the service before backing up, then archive the entire volume:

```bash
docker compose stop manhattancafe
umask 077
docker run --rm --read-only \
  --mount type=volume,src=manhattancafe-uma-state,dst=/state,readonly \
  --entrypoint tar manhattancafe-uma-auto -C /state -czf - . \
  > manhattancafe-uma-state.tgz
docker compose start manhattancafe
```

Back up and restore the volume as one unit. It contains the keyring, encrypted
account files, settings, generated data, logs, and Steam's
`<state-root>/steam-user` data, including a Steam Guard machine token. Treat
the volume and every backup archive as secret-bearing material.

## Move an existing install from Windows

The encrypted `UMAENC1` account files are already portable. Convert only the
state root's master-key wrapper before copying the directory:

1. On the original Windows box, set a passphrase and convert the keyring:

   ```powershell
   $env:UMA_SECRET_PASSPHRASE_FILE = "C:\secure\manhattancafe-passphrase"
   .venv\Scripts\python.exe scripts\portable_keyring.py --to passphrase --apply
   ```

   The command prints the resolved state root, verifies the replacement against
   a real account file, and writes a timestamped `.keyring.backup-*` beside the
   original before replacing it.

2. Copy the complete state root printed by the command to the Linux box.

3. Set the same passphrase on Linux. `UMA_SECRET_PASSPHRASE_FILE` may be used
   instead when a service or container supplies the secret as a file.

   ```bash
   export UMA_SECRET_PASSPHRASE_FILE=/run/credentials/manhattancafe-passphrase
   export UMA_RUNTIME_DIR=/path/to/copied/state-root
   ```

4. Start the application normally. Every copied account decrypts as-is, and its
   registered `udid` and `device_id` remain unchanged.

If step 1 is skipped and the directory is copied directly, the encrypted
payloads are intact but the DPAPI keyring cannot be unwrapped away from that
Windows user, so nothing decrypts. Go back to the original Windows box and run
the conversion; re-authentication is not the fix.

If the original Windows box is gone, `UMAACCT1` export/import remains the
per-account alternative, using a bundle exported while that account was still
accessible. The dashboard's account import/export controls create and consume
those passphrase-encrypted bundles.

To remove passphrase startup requirements after settling permanently on one
Windows user, run the reverse conversion with `--to dpapi --apply`.

## Parity-sensitive runtime settings

Race-out telemetry uses a canonical logical height of `864` on every operating
system, independent of the host's physical display. Set
`UMA_RACE_TELEMETRY_HEIGHT` only when an operator deliberately wants another
logical height; doing so makes the generated coordinates diverge from the
cross-platform default again.

`steam-user` keeps its server list and Steam Guard machine token under
`<state-root>/steam-user`, whose POSIX permissions are tightened like the rest
of the managed state root. Older releases used the library's OS-specific app
data directory. That old cache is not imported automatically, so the first
password login after upgrading may require one additional Guard challenge.
After that login, copying the complete state root carries the managed token to
the new host.
