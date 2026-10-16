"""Account/device identity synthesis for the request envelope.

Decides which device fingerprint an account presents and renders the two
identity-bearing shapes the transport sends: the ``common`` request block and
the UnityPlayer request headers. Pure functions over config values -- no I/O and
no wire access; ``UmaClient`` stays the owner of the resolved fields.
"""
from typing import Any

from uma_api.crypto import unpack_request
from uma_api.device import get_hwid


FINGERPRINT_FIELDS = (
    'device_id',
    'device_name',
    'graphics_device_name',
    'ip_address',
    'platform_os_version',
)


class FingerprintMaterializationError(RuntimeError):
    """A legacy seed could not be converted into persistent fingerprint fields."""


def captured_fingerprint(cfg):
    """Decode the device fingerprint saved with this account's captured auth.

    ``cfg['body']`` is the real request the game client made at capture time;
    it is encrypted with the account's udid, so both are required. A config
    without a captured body simply has no fingerprint to offer.
    """
    captured_fp: dict[str, Any] = {}
    if cfg.get('body') and cfg.get('udid'):
        try:
            captured_fp = unpack_request(cfg['body'], cfg['udid']) or {}
        except Exception:
            captured_fp = {}
    return captured_fp


def resolve_device_identity(cfg, profile):
    """Resolve the device fingerprint fields: cfg > captured body > derived hwid.

    Present the device fingerprint the account is REGISTERED with, so the server
    keeps seeing the same device it saw at registration. The registered
    fingerprint lives in cfg['body'] (the real request the game client made,
    saved at auth capture) and is encrypted with the account's udid, so decode it
    and prefer it over a locally-derived hwid. cfg's own explicit fields win
    first; the derived hwid is the last resort, for accounts with no captured
    body.

    ``profile`` may probe hardware lazily, so each fallback is reached only when
    the two higher-precedence sources came up empty.
    """
    captured_fp = captured_fingerprint(cfg)
    return {
        'device_id': cfg.get('device_id') or captured_fp.get('device_id') or profile['device_id'],
        'device_name': cfg.get('device_name') or captured_fp.get('device_name') or profile['device_name'],
        'graphics_device_name': cfg.get('graphics_device_name') or captured_fp.get('graphics_device_name') or profile['graphics_device_name'],
        'ip_address': cfg.get('ip_address') or captured_fp.get('ip_address') or profile['ip_address'],
        'platform_os_version': cfg.get('platform_os_version') or captured_fp.get('platform_os_version') or profile['platform_os_version'],
    }


def materialize_device_identity(cfg, seed):
    """Resolve every persistent fingerprint field without changing precedence.

    Hardware probing is lazy: complete explicit or captured fingerprints never
    call ``get_hwid``. When a fallback is required, the legacy seed is passed
    through unchanged so the resulting ``device_id`` stays byte-for-byte stable.
    """
    captured_fp = captured_fingerprint(cfg)
    resolved = {
        field: cfg.get(field) or captured_fp.get(field)
        for field in FINGERPRINT_FIELDS
    }
    missing = [field for field, value in resolved.items() if not value]
    if missing:
        try:
            profile = get_hwid(seed)
        except Exception as exc:
            raise FingerprintMaterializationError(
                f"Failed to materialize legacy device fingerprint: {exc}",
            ) from exc
        for field in missing:
            resolved[field] = profile.get(field)

    still_missing = [field for field, value in resolved.items() if not value]
    if still_missing:
        fields = ", ".join(still_missing)
        raise FingerprintMaterializationError(
            f"Failed to materialize legacy device fingerprint fields: {fields}",
        )
    return resolved


def prepare_account_config_for_storage(cfg):
    """Copy and sanitize an account config before persistent storage.

    A legacy password seed is removed only after its concrete device identity
    has been materialized. Failures propagate before the caller can replace the
    existing file.
    """
    stored = dict(cfg)
    if 'steam_password_seed' in stored:
        fingerprint = materialize_device_identity(
            stored, stored.get('steam_password_seed'),
        )
        stored.update(fingerprint)
    stored.pop('steam_password_seed', None)
    stored.pop('password', None)
    stored.pop('steam_session_ticket', None)
    return stored


def common_payload(
    viewer_id,
    device_id,
    device_name,
    graphics_device_name,
    ip_address,
    platform_os_version,
    locale,
    steam_id,
    steam_session_ticket,
):
    """The ``common`` identity block merged into every request payload."""
    return {
        'viewer_id': viewer_id, 'device': 4, 'device_id': device_id,
        'device_name': device_name, 'graphics_device_name': graphics_device_name,
        'ip_address': ip_address, 'platform_os_version': platform_os_version,
        'carrier': '', 'keychain': 0, 'locale': locale,
        'button_info': '', 'dmm_viewer_id': None, 'dmm_onetime_token': None,
        'steam_id': steam_id,
        'steam_session_ticket': steam_session_ticket
    }


def unity_headers(unity_ver):
    """The static UnityPlayer request headers, keyed off the Unity version."""
    return {
        'User-Agent': f'UnityPlayer/{unity_ver} (UnityWebRequest/1.0, libcurl/8.10.1-DEV)',
        'Accept': '*/*', 'Accept-Encoding': 'deflate, gzip',
        'Content-Type': 'application/x-msgpack', 'X-Unity-Version': unity_ver
    }
