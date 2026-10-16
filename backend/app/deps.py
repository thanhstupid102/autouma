"""FastAPI dependency providers shared across the domain routers.

Moved out of uma_api/session.py (§13.1 B2 first step): request-scoped
dependency wiring belongs to the web layer, so the transport layer no longer
imports FastAPI. Session/SessionManager themselves stay in uma_api.session —
only the HTTP-facing provider lives here.
"""

from fastapi import Header, HTTPException

from core.settings import Settings
from uma_api.account_io import safe_account_name
from uma_api.session import Session, get_session_manager


def get_session(x_account: str = Header(default="")) -> Session:
    name = x_account or Settings.SWEEP_ACCOUNT
    if not name:
        raise HTTPException(
            status_code=400,
            detail="No account selected (missing X-Account header)"
        )
    # Key the in-memory session by the SAME sanitized name used for the on-disk
    # files (account_store_path / save_account_config). Otherwise a name with a
    # space / diacritic / special char keys a session under the raw name while its
    # file is saved under the safe name -> snapshot_all() unions both and the
    # account shows up TWICE. safe_account_name is idempotent on already-clean
    # names (e.g. "lewpie"), so existing accounts are unaffected.
    name = safe_account_name(name)
    return get_session_manager().get(name)
