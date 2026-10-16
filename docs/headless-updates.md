# Headless game updates

The bot keeps global client versions separate from saved account auth. A
headless machine therefore does not need the game installed for ordinary data
or version updates, login, or bot execution.

| Update class | Required action |
| --- | --- |
| Data-only update | None. Server/master data continues to work with the current client flow. |
| `app_ver` bump | Usually none: startup publishes an installed game's version when available, otherwise it queries Apple's public App Store lookup endpoint and updates shared state best-effort. Manual publish/sync remains an override or recovery path. |
| Boot-flow/protocol change | Update the bot code; a version-file change cannot add or remove API calls. |
| Auth invalidation (`203`) or account/UDID conflict (`703`) | Sign in again from the web UI with Steam. The bot bootstraps with a fresh `udid`. If the server disables Steam account creation, the fresh device cannot start the Trainer ID chain; import an existing account bundle or link the account in the official game client. |

`102`/`202` are **not** classified as auth invalidation — `update_guard`
classifies them as transient auth/session overload and leaves the normal
retry/recovery path alone. A guest viewer_id alongside one of those codes means
the saved auth is invalid and the account must sign in again through the same
Steam-only bootstrap; `201`/`217` are a plain expired session (relogin), `101`
is maintenance.

Frida is not part of login or update recovery. It remains available only for
optional RE/diagnostic scripts through `requirements-re.txt`.

## Shared version contract

`<state-root>/client_version.json` has this shape:

```json
{
  "app_ver": "1.32.9",
  "res_ver": "10006900",
  "updated_at": "2026-07-17T12:34:56+00:00",
  "source": "publisher"
}
```

Shared values override stale `app_ver`/`res_ver` fields in every imported
account. On startup, an installed game's Unity `bundleVersion` is authoritative.
Without a local game, the bot queries Apple's public iTunes lookup API and saves
the returned version when valid. If that lookup fails, `UmaClient` falls back in
order to an existing shared value, the account's captured value, and finally the
hardcoded `1.32.9` default in `uma_api/client.py`. `res_ver` is not published from
disk: the bot updates it opportunistically when the server supplies
`data_headers.resource_version` during login or a change.

## Optional manual publish and sync

On the machine with Steam and the game installed:

```powershell
python scripts/publish_client_version.py
```

Use `--game-dir PATH` if Steam auto-detection cannot find app `3224770`, or
`--dry-run` to inspect the detected version without writing. Copy/sync only
the printed `<state-root>/client_version.json` to the selected state root on the
headless machine and restart its bot process. Do not copy account credentials as
part of this step.

Result-code diagnoses are also written to `<state-root>/update_status.json` and
sent once per account/diagnosis to the configured Discord webhook.
