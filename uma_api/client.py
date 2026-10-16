import base64
import binascii
import logging
import sys
import time
import uuid
from collections.abc import Iterator, Mapping
from curl_cffi import requests
import collections
import threading
from pathlib import Path
from typing import Any
from core.runtime_paths import resolve_state_root
from uma_api.timing import AccountPacingPolicy, TransportRetryPolicy
# These five names are the client's TIMING HOOKS, not ordinary helpers: the default
# retry/pacing policies resolve them by name on this module at call time, so they are
# used at runtime even though nothing references them lexically any more (§13.2 B3).
# Keeping them here also keeps the long-standing
# `monkeypatch.setattr(uma_api.client, "backoff_sleep", ...)` seam -- which 8 test
# modules rely on -- working unchanged. They now forward into career_bot.delay from
# INSIDE the call, so importing uma_api.client no longer imports the decision engine.
from uma_api.timing import (  # noqa: F401
    backoff_sleep,
    dna_sleep,
    dna_uniform,
    jittered_sleep,
    server_sleep,
)
from uma_api import client_version as _client_version
from uma_api import update_guard as _update_guard

from core.settings import Settings
from uma_api import account_state, api_warehouse, diagnostics, identity, race_telemetry
from uma_api.diagnostics import (  # noqa: F401
    SENSITIVE_ERROR_KEYS,
    format_api_error,
    redact_for_console,
)
from uma_api.routes import ApiRoutes, derive_exchange_get_list_time
from uma_api.crypto import *  # noqa: F401,F403
from uma_api.crypto import (  # noqa: F401
    HEAD,
    SALT,
    _decrypt_body,
    gen_key,
    get_iv,
    get_raw_udid,
    make_sid,
    next_sid,
    pack,
    sm5,
    unpack,
    unpack_request,
)
from uma_api.device import *  # noqa: F401,F403
from uma_api.device import check_deps, get_gpu, get_hwid, get_ip, get_os  # noqa: F401
from uma_api.errors import (
    ApiError,
    GameAuthRequiredError,
    SteamAccountRemoveChainedError,
    UnsupportedScenarioError,
    api_error_result_code,
)
from uma_api.steam_auth import *  # noqa: F401,F403
from uma_api.steam_auth import QrLoginSession, get_ticket  # noqa: F401
from uma_api.trace import TraceLog, runtime_output_root  # noqa: F401


log = logging.getLogger(__name__)


# --- Auto-backoff circuit breaker -------------------------------------------
# If the game server rejects this many API calls within the rolling window
# (seconds), the client trips its breaker. The runner polls `circuit_tripped`
# and stops cleanly instead of hammering a server that is clearly unhappy
# (e.g. throttling / temporary restriction). Tunable via env vars.

class StateRecoveryError(Exception):
    pass

BASE_URL = 'https://api.games.umamusume.com/umamusume/'
# The state-root client_version.json is authoritative. These only keep a fresh or
# partially copied install usable before that shared runtime file is published.
DEFAULT_APP_VER = '1.32.9'
DEFAULT_RES_VER = '10006800'
CIRCUIT_ERROR_THRESHOLD = Settings.SWEEPY_CIRCUIT_THRESHOLD
DIR = str(Path(__file__).resolve().parent.parent)
LAST_TICKET_GEN_RESULT = None
ALARM_CLOCK_ITEM_ID = 95
ALARM_CLOCK_EXCHANGE_ID = 9001
# Fallback only: the Alarm Clock price is master data and can change.
ALARM_CLOCK_CARAT_PRICE = 10
_CARAT_ITEM_ID = 43


def default_retry_policy():
    """Seam (a) default: today's transport retry/backoff waits, unchanged."""
    return TransportRetryPolicy(sys.modules[__name__])


def default_pacing_policy():
    """Seam (b) default: today's per-account TimingDNA pacing, unchanged."""
    return AccountPacingPolicy(sys.modules[__name__])


class _LazyDeviceProfile(Mapping[str, str]):
    """Load and memoize hardware identity only when a missing field needs it."""

    def __init__(self, seed: Any):
        self._seed = seed
        self._profile: dict[str, str] | None = None

    def _load(self) -> dict[str, str]:
        if self._profile is None:
            self._profile = get_hwid(self._seed)
        return self._profile

    def __getitem__(self, key: str) -> str:
        return self._load()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._load())

    def __len__(self) -> int:
        return len(self._load())


class UmaClient(ApiRoutes):

    ALARM_CLOCK_ITEM_ID = ALARM_CLOCK_ITEM_ID
    ALARM_CLOCK_EXCHANGE_ID = ALARM_CLOCK_EXCHANGE_ID
    ALARM_CLOCK_CARAT_PRICE = ALARM_CLOCK_CARAT_PRICE

    # Monotonic timestamp of the last raw wire call, used by _call_locked's inter-request
    # pacing. It is created lazily INSIDE _call_locked (seeded `0`, then set from
    # time.monotonic()), which is pinned wire code -- declaring the type here instead
    # of there keeps the int seed and the float updates consistent for the
    # checker. A bare annotation binds no class attribute, so _call_locked's
    # `hasattr(self, '_last_raw_call_ts')` seeding guard is unaffected.
    _last_raw_call_ts: float

    def __init__(self, cfg, trace_enabled=True, trace_log=None,
                 state_root=None,
                 retry_policy=None, pacing_policy=None):
        # Two SEPARATE timing seams (§13.2 B3) -- a retry/backoff policy and an
        # account-pacing policy. They are never merged: re-timing a retry must not
        # be able to move live request pacing (anti-detection), or vice versa.
        self.retry_policy = retry_policy if retry_policy is not None else default_retry_policy()
        self.pacing_policy = pacing_policy if pacing_policy is not None else default_pacing_policy()
        self.state_root = (
            Path(state_root).resolve()
            if state_root is not None
            else resolve_state_root(Settings.BASE_DIR).root
        )

        profile = _LazyDeviceProfile(cfg.get('steam_password_seed', 'default'))

        self.viewer_id = cfg.get('viewer_id', 0)
        self.udid_str = cfg.get('udid') or profile['udid']
        self.auth_key_hex = cfg.get('auth_key', '')
        self.auth_key_rotated = False
        self.last_attest = None
        self.last_attest_nonce = None
        self.steam_id = str(cfg.get('steam_id', ''))
        self.steam_ticket = cfg.get('steam_session_ticket', '')
        
        # Which device fingerprint this account presents is a live-behaviour
        # decision (it gates the friend-parent rental feature); the precedence
        # rules and the evidence for them live in uma_api.identity.
        fingerprint = identity.resolve_device_identity(cfg, profile)
        self.device_id = fingerprint['device_id']
        self.device_name = fingerprint['device_name']
        self.graphics_device = fingerprint['graphics_device_name']
        self.ip_address = fingerprint['ip_address']
        self.platform_os = fingerprint['platform_os_version']
        self.locale = cfg.get('locale', 'JPN')
        self.account_name = str(cfg.get('account_name') or cfg.get('name') or '').strip()

        self.unity_ver = cfg.get('unity_ver', '2022.3.62f2')
        # APP-VER/RES-VER are global client state, not captured account auth. A
        # shared runtime value must therefore override stale imported configs.
        _cv = _client_version.load_client_version(self.state_root)
        self.app_ver, self.res_ver = _client_version.resolve_versions(
            _cv, cfg, DEFAULT_APP_VER, DEFAULT_RES_VER,
        )
        # CDN base for the headless master.mdb updater (uma_data.master_updater).
        # Not part of resolve_versions()'s precedence chain -- it is server-derived
        # only (surfaced on tool/start_session, see _refresh_resource_version below)
        # and has no per-account/config override, so just seed it from the last
        # value this shared runtime file saw.
        self.resource_server = _client_version.get_resource_server(self.state_root) or ""

        self.sid = bytes(16)
        self.cached_load_data = {}
        self.tp_info = {}
        self.coin_info = {}
        self.item_map = {}
        self.current_scenario_id = None
        self.last_servertime = 0
        # Auto-backoff: rolling window of recent server-error timestamps. When it
        # fills past CIRCUIT_ERROR_THRESHOLD, `circuit_tripped` flips True and the
        # runner stops to avoid hammering a throttled/unhappy server.
        self.circuit_tripped = False
        self._err_window: collections.deque[float] = collections.deque()
        self._call_lock = threading.RLock()
        self.session = requests.Session()
        self.update_headers()
        self.api_jitter = self.pacing_policy.dna_uniform(-0.02, 0.02)
        self.api_warehouse_base_dir = None
        self.api_warehouse_account = ""

        self.on_api_log = None
        self._trace_log = trace_log if trace_enabled else None
        self.trace_file = None
        if trace_enabled:
            self._init_trace_log()

    # --- the two timing seams -------------------------------------------------
    # Properties, not plain attributes, so a client built via `UmaClient.__new__`
    # (the whole offline test harness does this -- __init__ needs the Windows
    # registry) still resolves today's defaults instead of raising AttributeError.
    # Assignable and constructor-injectable; both default to exactly the behaviour
    # the module-level career_bot.delay primitives had before §13.2 B3.

    @property
    def retry_policy(self):
        """(a) Transport retry/backoff waits. Server-mandated, not human pacing."""
        policy = self.__dict__.get('_retry_policy')
        if policy is None:
            policy = default_retry_policy()
            self.__dict__['_retry_policy'] = policy
        return policy

    @retry_policy.setter
    def retry_policy(self, policy):
        self.__dict__['_retry_policy'] = policy

    @property
    def pacing_policy(self):
        """(b) Per-account human pacing. ⚠️ This is live anti-detection behaviour."""
        policy = self.__dict__.get('_pacing_policy')
        if policy is None:
            policy = default_pacing_policy()
            self.__dict__['_pacing_policy'] = policy
        return policy

    @pacing_policy.setter
    def pacing_policy(self, policy):
        self.__dict__['_pacing_policy'] = policy

    @property
    def state_root(self) -> Path:
        root = self.__dict__.get("_state_root")
        if root is None:
            root = resolve_state_root(Settings.BASE_DIR).root
            self.__dict__["_state_root"] = root
        return root

    @state_root.setter
    def state_root(self, value) -> None:
        self.__dict__["_state_root"] = Path(value).resolve()

    def bind_api_warehouse(self, state_root, account):
        self.state_root = state_root
        self.api_warehouse_base_dir = self.state_root
        self.api_warehouse_account = account or ""
        if account:
            self.account_name = str(account)
        return self

    def _store_api_response(self, ep, res):
        # The reads are inside the guard on purpose: a partially constructed
        # client (tests build one via __new__) has no warehouse attributes yet,
        # and warehousing must never disturb the call it observed.
        try:
            return api_warehouse.store_success_response(
                self.api_warehouse_base_dir,
                self.api_warehouse_account,
                ep,
                res,
            )
        except Exception:
            return None

    def _init_trace_log(self):
        if self._trace_log is None:
            self._trace_log = TraceLog(self.state_root / "trace_logs")
        self._trace_log.initialize()
        self.trace_file = self._trace_log.trace_file

    def api_log(self, direction, ep, data, req_id=None):
        data_bytes = None
        if callable(self.on_api_log):
            try:
                callback_result = self.on_api_log(direction, ep, data, req_id)
                if isinstance(
                    callback_result,
                    (bytes, diagnostics.PayloadSerializationFailure),
                ):
                    data_bytes = callback_result
            except Exception:
                pass
        
        if self._trace_log:
            self._trace_log.write(
                direction,
                ep,
                data,
                req_id,
                data_bytes=data_bytes,
            )

    def api_payload_summary(self, ep, payload):
        return diagnostics.api_payload_summary(ep, payload)

    def safe_payload(self, payload):
        return diagnostics.safe_payload(payload)

    def response_summary(self, res):
        return diagnostics.response_summary(res)

    def auth_bytes(self):
        if not self.auth_key_hex or self.auth_key_hex == 'YOUR_AUTH_KEY_HERE':
            return b''
        return bytes.fromhex(self.auth_key_hex)

    def _adopt_start_session_response(self, response: Any) -> bool:
        """Retain the identity fields surfaced by ``tool/start_session``."""
        self.auth_key_rotated = False
        data = response.get("data") if isinstance(response, dict) else None
        if not isinstance(data, dict):
            return False

        self.last_attest = data.get("attest")
        self.last_attest_nonce = data.get("nonce")

        encoded_auth_key = data.get("auth_key")
        if not isinstance(encoded_auth_key, str) or not encoded_auth_key:
            return False
        try:
            decoded_auth_key = base64.b64decode(encoded_auth_key, validate=True)
        except (binascii.Error, ValueError):
            return False
        if not decoded_auth_key:
            return False

        auth_key_hex = decoded_auth_key.hex()
        rotated = auth_key_hex != getattr(self, "auth_key_hex", "")
        self.auth_key_hex = auth_key_hex
        self.auth_key_rotated = rotated
        return rotated

    def has_game_auth(self):
        from uma_api.bootstrap import has_game_auth_config

        return has_game_auth_config({
            "viewer_id": self.viewer_id,
            "udid": self.udid_str,
            "auth_key": self.auth_key_hex,
        })

    _ITEM_LIST_KEYS = account_state.ITEM_LIST_KEYS
    _ITEM_COUNT_KEYS = account_state.ITEM_COUNT_KEYS

    def _find_item_rows(self, data):
        return account_state.find_item_rows(data, self._ITEM_LIST_KEYS)

    def _item_count(self, item):
        return account_state.item_count(item, self._ITEM_COUNT_KEYS)

    def refresh_cached_account_state(self, data):
        account_state.refresh_account_state(
            self, data, self._ITEM_LIST_KEYS, self._ITEM_COUNT_KEYS,
        )

    def regen_sid(self):
        self.sid = make_sid(self.viewer_id, self.udid_str)

    def common(self):
        return identity.common_payload(
            self.viewer_id,
            self.device_id,
            self.device_name,
            self.graphics_device,
            self.ip_address,
            self.platform_os,
            self.locale,
            self.steam_id,
            self.steam_ticket,
        )

    def _apply_race_out_click_payload(self, payload):
        race_telemetry.apply_race_out_button_info(
            payload, self.viewer_id, self.current_scenario_id,
        )

    def update_headers(self):
        self.session.headers.update(identity.unity_headers(self.unity_ver))

    def _refresh_resource_version(self, data_headers):
        """Adopt Gallop.DataHeader.resource_version when the server surfaces it.

        Also best-effort captures data_headers.server_list.resource_server (the
        CDN base master_updater.fetch_master_mdb needs) whenever a response
        carries it -- normally only tool/start_session. Both are persisted to the
        shared state-root client_version.json so game_service.login's post-login
        master.mdb ensure (uma_data.master_updater.ensure_current) can act on
        them without a second network round-trip.
        """
        previous = self.res_ver
        changed = False
        try:
            current = _client_version.update_res_ver_from_headers(
                self.state_root, previous, data_headers,
            )
            if current != previous:
                self.res_ver = current
                changed = True
        except Exception:
            # Version persistence is a convenience; never break a valid API call.
            pass
        try:
            server_list = (data_headers or {}).get("server_list") or {}
            resource_server = server_list.get("resource_server")
            if isinstance(resource_server, str) and resource_server.strip():
                resource_server = resource_server.strip()
                if resource_server != self.resource_server:
                    self.resource_server = resource_server
                    _client_version.set_resource_server(
                        self.state_root, resource_server, source="server",
                    )
        except Exception:
            # Same best-effort contract as the res_ver branch above.
            pass
        return changed

    def reset_circuit(self):
        """Clear auto-backoff state for a fresh, deliberate run. If the server is
        still throttling, the breaker simply re-trips within the next window."""
        self.circuit_tripped = False
        self._err_window.clear()

    def _note_api_error(self, ep, rc):
        """Record a surfaced server error and trip the circuit breaker if too
        many happen within the rolling window. Sets `self.circuit_tripped` so the
        runner can stop; does NOT raise (the normal API error still propagates)."""
        now = time.monotonic()
        win = self._err_window
        win.append(now)
        cutoff = now - Settings.SWEEPY_CIRCUIT_WINDOW_SEC
        while win and win[0] < cutoff:
            win.popleft()
        if len(win) >= Settings.SWEEPY_CIRCUIT_THRESHOLD and not self.circuit_tripped:
            self.circuit_tripped = True
            log.warning(
                f"CIRCUIT BREAKER TRIPPED: {len(win)} server errors within "
                f"{int(Settings.SWEEPY_CIRCUIT_WINDOW_SEC)}s (last: {rc} on {ep}). "
                f"Auto-backoff -- the server is likely throttling. Stopping soon."
            )

    def call(self, ep, args=None, retry_208=6, retry_205=3, retry_500=3, _ver_retry=False):
        if not hasattr(self, '_call_lock'):
            self._call_lock = threading.RLock()
        with self._call_lock:
            return self._call_locked(
                ep, args, retry_208=retry_208, retry_205=retry_205,
                retry_500=retry_500, _ver_retry=_ver_retry,
            )

    def _call_locked(self, ep, args=None, retry_208=6, retry_205=3, retry_500=3, _ver_retry=False):
        if not hasattr(self, '_last_raw_call_ts'):
            self._last_raw_call_ts = 0
        while True:

            el = time.monotonic() - self._last_raw_call_ts
            if el < 0.14:
                self.pacing_policy.dna_sleep(0.14 - el, 0.14 - el)

            self._last_raw_call_ts = time.monotonic()

            req_id = str(uuid.uuid4())[:8]
            payload = args or {}
            payload.update(self.common())

            if ep.endswith('/race_out'):
                self._apply_race_out_click_payload(payload)

            body = pack(self.sid, get_raw_udid(self.udid_str), self.auth_bytes(), payload, self.udid_str)
            headers = {
                'SID': self.sid.hex(), 'Device': '4', 'Device-SubType': '1',
                'ViewerID': str(self.viewer_id),
                'APP-VER': self.app_ver, 'RES-VER': self.res_ver,
            }


            max_retries = 8
            for attempt in range(max_retries):
                wire_attempt = attempt + 1
                self.api_log("REQ", ep, {
                    "payload": payload,
                    "wire_attempt": wire_attempt,
                    "wire_attempt_limit": max_retries,
                }, req_id)
                try:
                    resp = self.session.post(BASE_URL + ep, data=body, headers=headers, timeout=30)
                except Exception as e:
                    retrying = attempt < max_retries - 1
                    self.api_log("ERR", ep, {
                        "error": str(e),
                        "wire_attempt": wire_attempt,
                        "wire_attempt_limit": max_retries,
                        "retrying": retrying,
                    }, req_id)
                    if retrying:
                        self.retry_policy.backoff_sleep(attempt, base=1.0, cap=15.0)
                        continue
                    raise Exception(f'Network error on {ep}: {e}')
                if resp.status_code != 200:
                    body_preview = resp.text[:500] if resp.text else ""
                    retrying = (
                        500 <= resp.status_code < 600
                        and attempt < max_retries - 1
                    )
                    self.api_log("ERR", ep, {
                        "http_status": resp.status_code,
                        "body": body_preview,
                        "wire_attempt": wire_attempt,
                        "wire_attempt_limit": max_retries,
                        "retrying": retrying,
                    }, req_id)
                # Transient server-side errors (HTTP 5xx, e.g. a 500 on race_end) are
                # retried with backoff instead of crashing the whole career/loop.
                if 500 <= resp.status_code < 600 and attempt < max_retries - 1:
                    log.warning(f"HTTP {resp.status_code} on {ep}, retrying... (attempt {attempt + 1})")
                    self.retry_policy.backoff_sleep(attempt, base=1.0, cap=15.0)
                    continue
                break

            if resp.status_code != 200:
                body_preview = resp.text[:500] if resp.text else ""
                log.error(f"HTTP error on {ep}: status={resp.status_code} body={body_preview}")
                raise Exception(f'HTTP {resp.status_code} on {ep}: {body_preview}')

            res = unpack(resp.text.strip(), self.udid_str)
            dh = res.get('data_headers', {})
            try:
                server_time = int(dh["servertime"])
                if server_time > 0:
                    self.last_servertime = server_time
            except (KeyError, TypeError, ValueError, OverflowError):
                pass
            rc = dh.get('result_code', 0)

            self.api_log("RES", ep, res, req_id)
            # DataHeader.resource_version is sparse (normally start_session/change
            # responses only). Adopt it whenever present; 214 can then retry with the
            # server-provided value without inventing a separate resource endpoint.
            res_ver_changed = self._refresh_resource_version(dh)
            if rc == 1:
                self._store_api_response(ep, res)

            data = res.get('data', {})
            if isinstance(data, dict):
                self.refresh_cached_account_state(data)
                self._remember_scenario_from_data(data)

            # The server advances SID even on API-level errors (102/205/etc.).
            # Keep local SID in sync before raising so recovery/retry calls are not
            # signed with the stale SID that produced the error response.
            if dh.get('sid') and isinstance(dh['sid'], str) and dh['sid'].strip():
                self.sid = next_sid(dh['sid'])

            if rc == 709:
                raise SteamAccountRemoveChainedError(709, ep, format_api_error(ep, rc, res))
            if rc != 1:
                if rc == 500 and retry_500 > 0:
                    attempt = max(0, 3 - retry_500)
                    log.warning(f"API error 500 on {ep}, backing off and retrying... ({retry_500} left)")
                    self.retry_policy.backoff_sleep(attempt, base=1.0, cap=15.0)
                    retry_500 -= 1
                    continue

                if rc == 205 and retry_205 > 0:
                    log.warning(f"205 on {ep}, retrying... ({retry_205} left)")
                    self.retry_policy.server_sleep(0.3, 0.7)
                    retry_205 -= 1
                    continue

                if rc == 208 and retry_208 > 0:
                    if ep.endswith("/gain_skills") or ep.endswith("/multi_item_exchange") or ep.endswith("/multi_item_use"):
                        # ROOT CAUSE of the 201 bursts: a 208 ("server busy") response on
                        # these batch endpoints carries NO data_headers.sid, so the SID
                        # hash-chain (self.sid = next_sid(server_sid)) cannot advance to
                        # follow the server -- yet the server consumed the request and
                        # advanced ITS sid. The old `return res` limped on with that stale
                        # sid, so the very next call (exec_command/race_entry/load) 201s,
                        # and every call after it 201s until a relogin. Instead raise a
                        # recoverable "208": the skill/item layer flags a recovery and the
                        # runner relogins (re-syncing the sid) BEFORE the next call, so the
                        # 201 burst never happens. Raised here, before _note_api_error, so
                        # it does not count toward the circuit breaker either.
                        raise ApiError(208, ep, message=f'API error 208 (server busy, sid resync needed) on {ep}')

                    if retry_208 < 6:
                        attempt = max(0, 6 - retry_208)
                        log.warning(f"API error 208 (SERVER BUSY) on {ep}, backing off and retrying... (attempts left: {retry_208-1})")
                        self.retry_policy.backoff_sleep(attempt, base=1.0, cap=15.0)
                    retry_208 -= 1
                    continue
                err_detail = format_api_error(ep, rc, res)
                err_msg = f'API error {rc} on {ep}: {err_detail}'
                # Errors the bot recovers from BY DESIGN must not trip the career-stopping
                # circuit breaker (which is meant for genuine server throttling) -- otherwise
                # one transient session-desync burst, which the bot relogins through and
                # finishes, gets the career killed. They also just add console noise:
                #  - 102 on race_end/race_out: expected "already done" race condition.
                #  - single_mode_free/load: the recovery reload probe discovering a desync
                #    that the gameplay call which triggered recovery ALREADY counted -- don't
                #    double-count one desync as two breaker hits.
                #  - single_mode_free/gain_skills: optional skill buy; a rejected skill is
                #    just skipped, not a throttle signal (208 on it already early-returns).
                # A real throttle still trips the breaker via exec_command/race_*/etc.
                recovered_by_design = (
                    (rc == 102 and (ep.endswith("/race_end") or ep.endswith("/race_out") or ep.endswith("/factor_select")))
                    or ep.endswith("/load")
                    or ep.endswith("/gain_skills")
                )

                diagnosis, remedy = _update_guard.classify_result_code(rc)
                account = (
                    getattr(self, 'api_warehouse_account', '')
                    or getattr(self, 'account_name', '')
                )
                alert_extra = f"result_code={rc} endpoint={ep}"

                if diagnosis == _update_guard.Diagnosis.VERSION_STALE:
                    if not _ver_retry:
                        previous_app_ver = self.app_ver
                        try:
                            from uma_api import appstore_version as _appstore

                            response_headers = res.get("data_headers", {})
                            response_data = res.get("data", {})
                            store_url = (
                                response_headers.get("store_url")
                                if isinstance(response_headers, dict)
                                else None
                            )
                            if not store_url and isinstance(response_data, dict):
                                store_url = response_data.get("store_url")
                            _appstore.ensure_app_ver_headless(
                                self.state_root, store_url=store_url,
                            )
                        except Exception:
                            pass
                        fresh = _client_version.get_app_ver(self.state_root)
                        if fresh and fresh != previous_app_ver:
                            log.info(
                                "APP-VER refreshed after 204: "
                                f"{previous_app_ver} -> {fresh}"
                            )
                            self.app_ver = fresh
                        else:
                            log.info(
                                "APP-VER refresh after 204 yielded no change; "
                                f"retrying {ep} once with {self.app_ver}"
                            )
                        _ver_retry = True
                        continue
                    _update_guard.alert_once(
                        self.state_root, account, diagnosis, remedy, extra=alert_extra,
                    )
                    raise _update_guard.ClientVersionError(f"{err_msg} {remedy}", result_code=rc, endpoint=ep)

                if diagnosis == _update_guard.Diagnosis.RESOURCE_STALE:
                    if res_ver_changed and not _ver_retry:
                        log.info(f"RES-VER refreshed after 214; retrying {ep} once")
                        _ver_retry = True
                        continue
                    _update_guard.alert_once(
                        self.state_root, account, diagnosis, remedy, extra=alert_extra,
                    )
                    # Normal/recoverable error: the runner's relogin path performs
                    # start_session + load, where resource_version can surface.
                    raise ApiError(rc, ep, err_detail, message=err_msg)

                # 102/202 are overloaded session/auth responses. Only a non-zero
                # guest/mismatched viewer identifies a re-registered auth pair.
                auth_dead = (
                    diagnosis == _update_guard.Diagnosis.AUTH_INVALIDATED
                    or (
                        rc in (102, 202)
                        and _update_guard.is_reregistration_signature(self.viewer_id, dh)
                    )
                )
                if auth_dead and not (rc == 102 and recovered_by_design):
                    if diagnosis != _update_guard.Diagnosis.AUTH_INVALIDATED:
                        diagnosis, remedy = _update_guard.classify_result_code(203)
                    remedy = remedy.format(account=account or "<unknown>")
                    _update_guard.alert_once(
                        self.state_root, account, diagnosis, remedy, extra=alert_extra,
                    )
                    raise _update_guard.AuthInvalidatedError(f"{err_msg} {remedy}", result_code=rc, endpoint=ep)

                if diagnosis == _update_guard.Diagnosis.ACCOUNT_UDID_CONFLICT:
                    _update_guard.alert_once(
                        self.state_root, account, diagnosis, remedy, extra=alert_extra,
                    )

                if diagnosis == _update_guard.Diagnosis.MAINTENANCE:
                    _update_guard.alert_once(
                        self.state_root, account, diagnosis, remedy, extra=alert_extra,
                    )

                if not recovered_by_design:
                    self._note_api_error(ep, rc)
                    log.error(err_msg)
                raise ApiError(rc, ep, err_detail, message=err_msg)
            return res

    def hard_reset(self):
        self.sid = bytes(16)
        self.regen_sid()
        self.session.close()
        self.session = requests.Session()
        self.update_headers()
        try:
            start_session = self.call('tool/start_session', {'attestation_type': 0, 'device_token': None})
            self._adopt_start_session_response(start_session)
            res = self.call('load/index', {
                'adid': ''
            })
            data = res.get('data', {})
            self.refresh_cached_account_state(data)
            # read_info/index removed from boot in the 1.32.x update (see read_info()).

            try:
                sm_res = self.call(self._single_mode_ep('load'), {})
                chara = sm_res.get('data', {}).get('chara_info')
                if not chara:
                    raise StateRecoveryError("No chara_info returned in single-mode load after hard reset.")
            except _update_guard.AuthInvalidatedError:
                # A re-registered account cannot heal headlessly; blind retries
                # only repeat writes against the wrong/guest viewer state.
                raise
            except UnsupportedScenarioError:
                # There is no routed finish endpoint for this career, so recovery
                # cannot safely continue or dismiss the terminal diagnosis.
                raise
            except Exception as e:
                if isinstance(e, StateRecoveryError):
                    raise
                if api_error_result_code(e) in (201, 102):
                    raise StateRecoveryError(f"Cannot recover training state: {e}")
                log.warning(f"single-mode load during hard_reset failed: {e}")

            return res
        except UnsupportedScenarioError:
            raise
        except StateRecoveryError:
            raise
        except Exception as e:
            log.error(f"Hard Reset Failure: {e}")
            raise

    def login(self, max_retries=3):
        if not self.has_game_auth():
            raise GameAuthRequiredError()

        old_h = dict(self.session.headers)
        self.session.close()
        self.session = requests.Session()
        self.session.headers.update(old_h)

        for attempt in range(max_retries + 1):
            try:
                self.regen_sid()
                start_session = self.call('tool/start_session', {'attestation_type': 0, 'device_token': None})
                self._adopt_start_session_response(start_session)
                res = self.call('load/index', {'adid': ''})
                data = res.get('data', {})
                self.refresh_cached_account_state(data)
                # Boot is start_session + load/index only since the 1.32.x update
                # (read_info/index was removed; see read_info()). Don't call it here.
                return res
            except _update_guard.AuthInvalidatedError:
                # Re-registration cannot heal in this retry loop; surface the
                # typed failure so the runner can stop without another API call.
                raise
            except Exception as e:
                err = str(e)
                if '394' in err and attempt < max_retries:
                    self.retry_policy.jittered_sleep(2.5)
                    continue
                if '202' in err and attempt < max_retries:
                    self.retry_policy.jittered_sleep(4.15)
                    continue
                raise

    def recovery_tp(self, count=1):
        total_jewels = self.coin_info.get("fcoin", 0) + self.coin_info.get("coin", 0)
        result = self.call("user/recovery_trainer_point", {
            "count": count,
            "client_own_num": total_jewels,
        })
        data = result.get("data", {})
        tp = data.get("tp_info", {})
        if tp:
            self.tp_info = tp
        coin = data.get("coin_info", {})
        if coin:
            self.coin_info = coin
        return tp

    def alarm_clock_carat_price(self):
        """Resolve exchange 9001's current carat cost from master.mdb."""
        from uma_data import configured_master_mdb_path, load_item_exchange

        try:
            master_path = configured_master_mdb_path(
                Settings.BASE_DIR,
                getattr(self, "state_root", None),
            )
            exchange = load_item_exchange(
                Settings.BASE_DIR,
                self.ALARM_CLOCK_EXCHANGE_ID,
                master_mdb_path=master_path,
            )
        except Exception:
            exchange = None
        if (
            isinstance(exchange, dict)
            and int(exchange.get("change_item_id") or 0) == self.ALARM_CLOCK_ITEM_ID
            and int(exchange.get("change_item_num") or 0) == 1
            and int(exchange.get("pay_item_id") or 0) == _CARAT_ITEM_ID
            and int(exchange.get("pay_item_num") or 0) > 0
        ):
            return int(exchange["pay_item_num"])
        return self.ALARM_CLOCK_CARAT_PRICE

    def buy_alarm_clock(self, account_data=None):
        """Refresh carats, then buy one Alarm Clock through item exchange 9001."""
        if not hasattr(self, '_call_lock'):
            self._call_lock = threading.RLock()
        with self._call_lock:
            if account_data is None:
                info = self.read_info()
                data = (info or {}).get("data", {})
            else:
                data = account_data
            if not isinstance(data, dict):
                raise ValueError("load/index returned no account data")
            self.refresh_cached_account_state(data)

            coin_info = self.coin_info or {}
            if not isinstance(coin_info, dict) or not any(
                key in coin_info for key in ("fcoin", "coin")
            ):
                raise ValueError("load/index returned no coin_info")
            current_num = int(coin_info.get("fcoin") or 0) + int(
                coin_info.get("coin") or 0
            )
            before_count = None
            item_map = self.item_map if isinstance(self.item_map, dict) else {}
            for key in (self.ALARM_CLOCK_ITEM_ID, str(self.ALARM_CLOCK_ITEM_ID)):
                if key not in item_map:
                    continue
                try:
                    before_count = max(int(item_map.get(key) or 0), 0)
                except (TypeError, ValueError):
                    before_count = None
                break

            show_response = self.show_exchange()
            get_list_time = derive_exchange_get_list_time(show_response)
            result = self.exchange_item(
                self.ALARM_CLOCK_EXCHANGE_ID,
                1,
                current_num,
                get_list_time,
            )
            result_data = (result or {}).get("data", {})
            if isinstance(result_data, dict):
                rows = self._find_item_rows(result_data)
                returned_clock = account_state.rows_report_item(
                    rows,
                    self.ALARM_CLOCK_ITEM_ID,
                    self._ITEM_COUNT_KEYS,
                )
                self.refresh_cached_account_state(result_data)
                if not returned_clock and before_count is not None:
                    # A successful exchange is an authoritative +1 delta, but
                    # only when the pre-purchase owned count was known.
                    self.item_map[self.ALARM_CLOCK_ITEM_ID] = before_count + 1
            return result

    # TP_BOTTLE_ITEM_ID is the plain "Toughness 30" TP bottle (master item_data id
    # 32, +30 TP). The Valentine handmade chocolates (10001-10068) share the same
    # +30 TP effect but are rare collectibles -- never spend those automatically.
    TP_BOTTLE_ITEM_ID = 32

    def use_recovery_item(self, item_id=TP_BOTTLE_ITEM_ID, item_num=1):
        """Consume a home-screen TP recovery item (e.g. a TP bottle) to restore
        TP without spending carats. Payload captured from the live client:
        item/use_recovery_item {item_id, item_num, client_own_num}."""
        item_id = int(item_id)
        own = max(int(self.item_map.get(item_id, 0) or 0), 0)
        use_num = min(int(item_num or 0), own)
        if use_num < 1:
            raise ValueError("No recovery item available")
        result = self.call("item/use_recovery_item", {
            "item_id": item_id,
            "item_num": use_num,
            "client_own_num": int(own),
        })
        data = result.get("data", {})
        rows = self._find_item_rows(data)
        has_item_rows = rows is not None
        returned_item = False
        if has_item_rows:
            returned_item = account_state.rows_report_item(
                rows, item_id, self._ITEM_COUNT_KEYS,
            )
            self.refresh_cached_account_state(data)
        # A partial response may omit the item it just consumed. In that case
        # keep the local cache accurate using the request's known quantity.
        if not returned_item:
            self.item_map[item_id] = max(own - use_num, 0)
        tp = data.get("tp_info", {})
        if tp:
            self.tp_info = tp
        return tp

    def single_mode_use_tp(self, scenario_id=None, base=30):
        """DEPRECATED: use uma_data.single_mode_career_start_tp().

        Thin shim kept so out-of-tree scripts that still reach the policy through the
        client keep working. The policy and its master-data caching moved to
        uma_data/tp_cost.py; this only supplies the client-side inputs
        (server clock, active scenario). Career START cost only -- the spark-reroll
        factor_lottery cost is a flat 30 and must not go through here.
        """
        from uma_data import tp_cost as _tp_cost

        sid = scenario_id if scenario_id is not None else getattr(self, "current_scenario_id", None)
        return _tp_cost.single_mode_career_start_tp(
            scenario_id=sid,
            base=base,
            server_time=getattr(self, "last_servertime", 0),
        )

    def auth_config_snapshot(self) -> dict[str, Any]:
        return {
            "viewer_id": self.viewer_id,
            "udid": self.udid_str,
            "auth_key": self.auth_key_hex,
            "steam_id": self.steam_id,
            "steam_session_ticket": self.steam_ticket,
            "device_id": self.device_id,
            "device_name": self.device_name,
            "graphics_device_name": self.graphics_device,
            "ip_address": self.ip_address,
            "platform_os_version": self.platform_os,
        }
