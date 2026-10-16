"""Campaign-adjusted single-mode TP cost policy.

Career START only. The "SingleUseTP" campaign (master.mdb campaign_data rows with
target_type=1 / effect_type_1=4) lowers the cost of *starting* a career (30 -> 15);
effect_value_1 is the absolute discounted cost, not a delta. The spark-reroll
factor_lottery cost is a separate, undiscounted flat 30 and must never be routed
through this resolver.

This policy used to live on UmaClient (policy + master-data caching inside the
transport class, behind a lazy upward import of career_bot). It is pure policy over
master data, so it belongs here; UmaClient.single_mode_use_tp is now a deprecated
shim that only supplies the client-side inputs (server clock, active scenario).
"""

import threading
import time

from uma_data.loaders import (
    load_single_use_tp_campaigns,
    resolve_single_mode_use_tp,
)
from core.settings import Settings
from uma_data.mdb_config import master_mdb_mtime_ns

# (base_dir key, master.mdb mtime_ns, campaign rows) -- the mtime-keyed memo that
# used to hang off every UmaClient instance as `_single_use_tp_cache`. The rows are
# derived purely from master.mdb, so a single process-wide entry is correct (and
# shared across accounts, unlike per-account pacing state).
_CACHE_LOCK = threading.Lock()
_CAMPAIGN_CACHE = None


def load_active_campaigns(base_dir=None):
    """Return the SingleUseTP campaign rows, memoised on master.mdb's mtime."""
    global _CAMPAIGN_CACHE
    root = Settings.BASE_DIR if base_dir is None else base_dir
    key = str(root)
    mtime = master_mdb_mtime_ns(root)
    with _CACHE_LOCK:
        cached = _CAMPAIGN_CACHE
    if cached is not None and cached[0] == key and cached[1] == mtime:
        return cached[2]
    campaigns = load_single_use_tp_campaigns(root)
    with _CACHE_LOCK:
        _CAMPAIGN_CACHE = (key, mtime, campaigns)
    return campaigns


def single_mode_career_start_tp(scenario_id=None, base=30, server_time=None, base_dir=None):
    """Resolve the career-START TP cost under the active SingleUseTP campaign.

    `server_time` is the server clock (UmaClient.last_servertime); it falls back to
    local time when absent/zero, and any failure falls back to `base` -- exactly the
    behaviour of the old UmaClient.single_mode_use_tp. NOT for the spark reroll,
    whose factor_lottery cost stays a flat 30.
    """
    try:
        campaigns = load_active_campaigns(base_dir)
        now = int(server_time or 0)
        if now <= 0:
            now = int(time.time())
        return resolve_single_mode_use_tp(campaigns, now, scenario_id, base)
    except Exception:
        return int(base)
