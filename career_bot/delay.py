import logging
import math
import random
import time
import hashlib
import threading
from pathlib import Path

from core.runtime_paths import create_private_text_once, resolve_state_root

log = logging.getLogger(__name__)

_SQUARE_ENDPOINT_DELAY = (4.00, 37.00, 10.26)

_BASE_DELAYS = {
    'load_index': (1.16, 14.69, 5.26),
    'load_career': (0.62, 7.64, 2.56),
    'pre_single_mode': (1.80, 25.95, 2.03),
    'start_career': (1.58, 6.23, 1.98),
    'start_session': (0.62, 4.55, 1.06),
    'pre_signup': (0.62, 4.55, 1.06),
    'signup': (0.62, 4.55, 1.06),
    'check_event': (1.11, 3.90, 1.88),
    'continue': (0.96, 4.82, 3.05),
    'exec_command': (2.86, 17.68, 4.82),
    'finish_career': (3.05, 15.49, 3.54),
    'gain_skills': (7.02, 99.37, 54.62),
    'read_info': (1.16, 14.69, 5.26),
    'recovery_trainer_point': (0.62, 4.55, 1.06),
    'multi_item_exchange': (4.20, 13.79, 8.29),
    'multi_item_use': (2.99, 9.87, 5.67),
    'minigame_end': (1.11, 3.90, 1.88),
    'race_end': (1.85, 3.90, 2.01),
    'race_entry': (0.73, 4.94, 0.78),
    'change_running_style': (0.73, 4.94, 0.78),
    'reserve_race': (2.78, 9.26, 4.90),
    'race_out': (2.20, 9.91, 3.79),
    'race_start': (1.93, 10.36, 3.46),
    # Grand Live (scenario 3). One square-endpoint profile was measured from the
    # 2026-07-26 manual capture and is shared by all three square verbs. Its max
    # is the p95 rather than the raw max, which held a single AFK outlier.
    # _pacing_name keys by verb, so single_mode_live/start|load|finish already
    # share the career profiles above -- only these four names are new.
    'master_square': _SQUARE_ENDPOINT_DELAY,
    'live_start': (1.00, 21.00, 12.50),
    'reserve_square': _SQUARE_ENDPOINT_DELAY,
    'lottery_square': _SQUARE_ENDPOINT_DELAY,
}

_seed_lock = threading.Lock()
_timing_dna_path: Path | None = None
_legacy_timing_dna_path: Path | None = None
_dna_seed: int | None = None
_default_dna: "TimingDNA | None" = None


def configure_timing_dna(state_root, source_root=None) -> None:
    """Select the state-root seed file without creating it."""
    global _timing_dna_path, _legacy_timing_dna_path, _dna_seed, _default_dna
    path = Path(state_root).resolve() / ".timing_dna"
    if source_root is None:
        from core.settings import Settings

        source_root = Settings.BASE_DIR
    legacy_path = Path(source_root).resolve() / "career_bot" / ".timing_dna"
    with TimingDNA._registry_lock:
        with _seed_lock:
            if (
                path == _timing_dna_path
                and legacy_path == _legacy_timing_dna_path
            ):
                return
            _timing_dna_path = path
            _legacy_timing_dna_path = legacy_path
            _dna_seed = None
            _default_dna = None
            TimingDNA._registry.clear()


def _installation_seed() -> int:
    global _timing_dna_path, _legacy_timing_dna_path, _dna_seed
    with _seed_lock:
        if _dna_seed is not None:
            return _dna_seed
        if _timing_dna_path is None:
            from core.settings import Settings

            _timing_dna_path = resolve_state_root(Settings.BASE_DIR).timing_dna_path
            _legacy_timing_dna_path = (
                Settings.BASE_DIR / "career_bot" / ".timing_dna"
            )
        seed_text = str(random.randint(1000000, 9999999))
        migrated_from = None
        if (
            not _timing_dna_path.exists()
            and _legacy_timing_dna_path is not None
            and _legacy_timing_dna_path.is_file()
        ):
            try:
                seed_text = _legacy_timing_dna_path.read_text(
                    encoding="utf-8",
                ).strip()
                int(seed_text)
                migrated_from = _legacy_timing_dna_path
            except (OSError, UnicodeError, ValueError) as exc:
                log.warning(
                    "Could not import legacy timing DNA seed from %s: %s",
                    _legacy_timing_dna_path,
                    exc,
                )
        created = create_private_text_once(_timing_dna_path, seed_text)
        if created and migrated_from is not None:
            log.info(
                "Imported legacy timing DNA seed from %s to %s",
                migrated_from,
                _timing_dna_path,
            )
        _dna_seed = int(_timing_dna_path.read_text(encoding="utf-8").strip())
        return _dna_seed

# These are now only DEFAULT SEEDS for a fresh TimingDNA / the default DNA. The live
# per-turn values are per-account instance attrs on TimingDNA (self.turn_delay_min/max,
# self.delays_disabled); the Web UI sets them per account via set_turn_delay ->
# Session.apply_delay_to_dna -> TimingDNA.set_delay_config, so parallel accounts no
# longer clobber each other's pacing.
# Per-turn pause (between turns). Default OFF (0s, no cooldown) -- the human-pacing
# turn delay made a full career take ~30-37 min, which the user does not want.
# Re-enable + tune from the Web UI ("No CD" toggle / delay inputs); the restore
# values below are the bounds used when the user turns the delay back on.
TURN_DELAY_MIN = 0.0
TURN_DELAY_MAX = 0.0
TURN_DELAY_RESTORE_MIN = 1.6
TURN_DELAY_RESTORE_MAX = 3.7
GLOBAL_DELAYS_DISABLED = True

# Per-action ("button press") delay scale. 1.0 = realistic human pacing,
# >1 = slower, <1 = faster (0.5 = 2x faster). Set to 0.8 so that, together with
# the turn delay above, a full career lands around ~30-37 min. Keeps the
# human-like variation/jitter. Only affects simulate_delay, NOT the turn delay.
ACTION_DELAY_SCALE = 0.8

# Endpoints that NEVER delay, even when delays are globally enabled (No CD off).
# These are passive navigation / read / session calls that don't change game
# state, so pausing on them only slows runs with no anti-detection value.
ZERO_DELAY_ENDPOINTS = {"start_session", "load_index", "read_info", "load_career", "pre_single_mode"}

# Per-endpoint multiplier on the realistic delay (when delays are enabled).
# gain_skills' real profile averages ~54s (reading the skill screen); halve it.
ENDPOINT_DELAY_MULT = {"gain_skills": 0.5}


class TimingDNA:
    """A self-contained, thread-safe "timing personality".

    Each account gets its own instance (seeded from its viewer_id) so two
    accounts never share an identical timing fingerprint, and two runner
    threads never touch the same RNG state at the same time.
    """

    _registry: dict[int, "TimingDNA"] = {}
    _registry_lock = threading.Lock()

    def __init__(self, seed):
        self.seed = int(seed)
        self.lock = threading.RLock()
        self.rng = random.Random(self.seed)
        r = self.rng
        # Persona is derived in this exact draw order so the default instance
        # reproduces the historical single-account timing stream byte-for-byte.
        self.sigma = r.uniform(0.45, 0.75)
        self.speed_shift = r.uniform(0.92, 1.08)
        self.distraction_chance = r.uniform(0.015, 0.065)
        self.distraction_min = r.uniform(1.5, 3.5)
        self.distraction_max = r.uniform(7.0, 14.0)
        self.endpoint_shifts = {ep: r.uniform(0.85, 1.15) for ep in _BASE_DELAYS}
        # Per-account pacing config (turn-pause range + master No-CD toggle). Seeded
        # from the module-level defaults so the default DNA / unbound threads keep the
        # historical single-account behavior. The Web UI overrides these PER ACCOUNT
        # via set_delay_config (main.set_turn_delay -> Session.apply_delay_to_dna), so
        # two accounts running in parallel never clobber each other's pacing -- unlike
        # the old module-global TURN_DELAY_MIN/MAX/GLOBAL_DELAYS_DISABLED.
        self.delays_disabled = GLOBAL_DELAYS_DISABLED
        self.turn_delay_min = TURN_DELAY_MIN
        self.turn_delay_max = TURN_DELAY_MAX

    def set_delay_config(self, turn_delay_min=None, turn_delay_max=None, disabled=None):
        """Set this account's pacing live (thread-safe). Only provided values change."""
        with self.lock:
            if turn_delay_min is not None:
                self.turn_delay_min = max(0.0, float(turn_delay_min))
            if turn_delay_max is not None:
                self.turn_delay_max = max(0.0, float(turn_delay_max))
            if disabled is not None:
                self.delays_disabled = bool(disabled)

    @classmethod
    def for_account(cls, viewer_id):
        """Return the stable, distinct personality for a given account.

        The seed mixes the per-install seed with the viewer_id, so the same
        account always gets the same rhythm while different accounts diverge.
        """
        key = int(viewer_id or 0)
        with cls._registry_lock:
            dna = cls._registry.get(key)
            if dna is None:
                mixed = hashlib.sha256(
                    f"{_installation_seed()}:{key}".encode()
                ).hexdigest()
                dna = cls(int(mixed[:12], 16))
                cls._registry[key] = dna
            return dna

    # ---- thread-safe RNG primitives ----
    def uniform(self, a, b):
        with self.lock:
            return self.rng.uniform(a, b)

    def gauss(self, mean, stddev):
        with self.lock:
            return self.rng.gauss(mean, stddev)

    def randint(self, a, b):
        with self.lock:
            return self.rng.randint(a, b)

    def _lognorm(self, mu, sigma):
        with self.lock:
            return self.rng.lognormvariate(mu, sigma)

    def _chance(self):
        with self.lock:
            return self.rng.random()

    # ---- sleeps ----
    def sleep(self, min_val, max_val, mean=None, stddev=None):
        if self.delays_disabled:
            return 0.0
        if mean is not None and stddev is not None:
            dt = max(min_val, min(max_val, self.gauss(mean, stddev)))
        else:
            dt = self.uniform(min_val, max_val)
        time.sleep(dt)
        return dt

    def jittered_sleep(self, seconds, spread=0.3):
        """Sleep around `seconds` with +/- `spread` random jitter so two retries
        never wait for an identical duration (an obvious bot fingerprint)."""
        if self.delays_disabled:
            return 0.0
        seconds = max(0.0, float(seconds))
        spread = min(0.95, max(0.0, float(spread)))
        dt = max(0.0, self.uniform(seconds * (1.0 - spread), seconds * (1.0 + spread)))
        time.sleep(dt)
        return dt

    def backoff_sleep(self, attempt, base=1.0, cap=15.0, factor=2.0):
        """Exponential backoff with "equal jitter": grows with `attempt` up to
        `cap`, always at least half the exponential target, never identical.

        Deliberately not gated on delays_disabled: this is used for
        server-mandated waits, not human pacing.
        """
        attempt = max(0, int(attempt))
        base = max(0.0, float(base))
        cap = max(base, float(cap))
        target = min(cap, base * (factor ** attempt))
        half = target / 2.0
        dt = min(cap, max(0.0, half + self.uniform(0.0, half)))
        time.sleep(dt)
        return dt

    def simulate_delay(self, endpoint, client=None):
        if self.delays_disabled or endpoint in ZERO_DELAY_ENDPOINTS:
            log.info(f"Endpoint: {endpoint} | Delay: 0.000s")
            return 0.0

        if endpoint not in _BASE_DELAYS:
            target_delay = 0.3 * self.speed_shift
            mu = math.log(target_delay) - (self.sigma ** 2) / 2.0
            dt = self._lognorm(mu, self.sigma)
            dt = max(0.08, min(1.2, dt))
        else:
            real_min, real_max, real_avg = _BASE_DELAYS[endpoint]
            ep_shift = self.endpoint_shifts[endpoint]
            target_delay = real_avg * self.speed_shift * ep_shift
            shifted_min = real_min * self.speed_shift * ep_shift
            shifted_max = real_max * self.speed_shift * ep_shift
            mu = math.log(target_delay) - (self.sigma ** 2) / 2.0
            dt = self._lognorm(mu, self.sigma)
            dt = max(shifted_min, min(shifted_max, dt))

        if self._chance() < self.distraction_chance:
            dt += self.uniform(self.distraction_min, self.distraction_max)

        dt *= ACTION_DELAY_SCALE
        dt *= ENDPOINT_DELAY_MULT.get(endpoint, 1.0)

        log.info(f"Endpoint: {endpoint} | Delay: {dt:.3f}s")

        if client is not None and hasattr(client, '_last_raw_call_ts'):
            elapsed = time.monotonic() - client._last_raw_call_ts
            actual_sleep = dt - elapsed
            if actual_sleep > 0:
                time.sleep(actual_sleep)
        else:
            time.sleep(dt)
        return dt

    def simulate_turn_delay(self):
        # Per-turn pause: a clean uniform random in the user-set [min, max] range
        # (set from the Web UI via set_turn_delay). When "No CD" is on
        # (this account's delays_disabled) or the range is zero, it's skipped.
        if self.delays_disabled:
            log.info("Endpoint: turn_delay | Delay: 0.000s")
            return 0.0
        lo = max(0.0, min(self.turn_delay_min, self.turn_delay_max))
        hi = max(0.0, max(self.turn_delay_min, self.turn_delay_max))
        if hi <= 0.0:
            log.info("Endpoint: turn_delay | Delay: 0.000s")
            return 0.0
        dt = self.uniform(lo, hi)
        log.info(f"Endpoint: turn_delay | Delay: {dt:.3f}s")
        time.sleep(dt)
        return dt


_active = threading.local()


def _default_timing_dna() -> TimingDNA:
    global _default_dna
    if _default_dna is None:
        seed = _installation_seed()
        with _seed_lock:
            if _default_dna is None:
                _default_dna = TimingDNA(seed)
    assert _default_dna is not None
    return _default_dna


def use_dna(dna):
    """Bind `dna` as the active personality for the current thread.

    Each account's runner runs in its own thread, so binding once makes every
    subsequent bare delay call in that thread use the right account's timing.
    """
    _active.dna = dna


def current_dna():
    return getattr(_active, "dna", None) or _default_timing_dna()


def simulate_delay(endpoint, client=None):
    return current_dna().simulate_delay(endpoint, client)


def simulate_turn_delay():
    return current_dna().simulate_turn_delay()


def dna_randint(min_val, max_val):
    return current_dna().randint(min_val, max_val)


def dna_sleep(min_val, max_val, mean=None, stddev=None):
    return current_dna().sleep(min_val, max_val, mean, stddev)


def server_sleep(min_val, max_val):
    """Sleep for a server-mandated delay, ignoring all No-CD toggles."""
    dt = max(0.0, random.uniform(float(min_val), float(max_val)))
    time.sleep(dt)
    return dt


def dna_uniform(min_val, max_val):
    return current_dna().uniform(min_val, max_val)


def dna_gauss(mean, stddev):
    return current_dna().gauss(mean, stddev)


def jittered_sleep(seconds, spread=0.3):
    return current_dna().jittered_sleep(seconds, spread)


def backoff_sleep(attempt, base=1.0, cap=15.0, factor=2.0):
    return current_dna().backoff_sleep(attempt, base=base, cap=cap, factor=factor)


class GateKeeper:
    def __init__(self, client, dna=None):
        super().__setattr__('_client', client)
        raw_call = getattr(client, '_gatekeeper_raw_call', None)
        if raw_call is None:
            raw_call = client.call
            setattr(client, '_gatekeeper_raw_call', raw_call)
        super().__setattr__('_raw_call', raw_call)
        if dna is None:
            viewer_id = getattr(client, 'viewer_id', 0)
            dna = TimingDNA.for_account(viewer_id) if viewer_id else _default_timing_dna()
        super().__setattr__('_dna', dna)
        use_dna(dna)
        client.call = self._paced_call

    def wait_turn_delay(self):
        use_dna(self._dna)
        self._dna.simulate_turn_delay()

    def __setattr__(self, name, value):
        if name in ('_client', '_raw_call', '_dna'):
            super().__setattr__(name, value)
        else:
            setattr(self._client, name, value)

    def _pacing_name(self, ep):
        # Endpoints whose bare verb suffix is ambiguous (several end in /index) stay
        # keyed by full path.
        full_path_map = {
            'load/index': 'load_index',
            'read_info/index': 'read_info',
            'pre_single_mode/index': 'pre_single_mode',
            'tool/start_session': 'start_session',
            'user/recovery_trainer_point': 'recovery_trainer_point',
        }
        if ep in full_path_map:
            return full_path_map[ep]
        # single_mode_*/<verb>: key by verb so any scenario prefix maps identically.
        # Unity previously gave start/load/pre/race_continue/finish generic delays;
        # it now shares the same pacing profile as MANT.
        verb = ep.split('/')[-1]
        verb_map = {
            'start': 'start_career',
            'check_event': 'check_event',
            'exec_command': 'exec_command',
            'read_info': 'load_index',
            'pre': 'pre_single_mode',
            'race_continue': 'continue',
            'continue': 'continue',
            'gain_skills': 'gain_skills',
            'multi_item_exchange': 'multi_item_exchange',
            'multi_item_use': 'multi_item_use',
            'minigame_end': 'minigame_end',
            'race_end': 'race_end',
            'race_entry': 'race_entry',
            'change_running_style': 'change_running_style',
            'reserve_race': 'reserve_race',
            'race_out': 'race_out',
            'race_start': 'race_start',
            'load': 'load_career',
            'finish': 'finish_career',
        }
        return verb_map.get(verb, verb)

    def _paced_call(self, ep, *args, **kwargs):
        use_dna(self._dna)
        self._dna.simulate_delay(self._pacing_name(ep), self._client)
        return self._raw_call(ep, *args, **kwargs)

    def __getattr__(self, name):
        attr = getattr(self._client, name)
        return attr
