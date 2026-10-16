import asyncio

from fastapi import HTTPException

import backend.app.domain.account_store as account_store
from uma_api.client import QrLoginSession
from uma_api.secret_store import SecretStoreError
from uma_api.session import Session, get_session_manager


QR_TOKEN_PERSIST_ERROR = (
    "Steam QR was confirmed, but the refresh token could not be saved because "
    "secure storage is unavailable or the state directory is not writable. "
    "Configure UMA_SECRET_PASSPHRASE or UMA_SECRET_PASSPHRASE_FILE, verify the "
    "state directory, then request a new QR code."
)


class SteamService:
    """Full-move (verbatim) handlers for the Steam QR login routes."""

    def __init__(self, session: Session):
        self.session = session

    async def qr_start(self):
        session = self.session
        session_manager = get_session_manager()
        # Serialize Steam QR add-account kickoffs across sessions.
        if not session_manager.add_lock.acquire(blocking=False):
            raise HTTPException(status_code=409, detail="Another account add is in progress")
        try:
            qr = getattr(session, "_qr", None)
            if qr is None:
                qr = QrLoginSession()
                session._qr = qr
            qr.start()
            # Give the script a moment to emit the challenge URL.
            for _ in range(50):
                snap = qr.snapshot()
                if snap["challenge_url"] and snap["status"] == "pending":
                    break
                if snap["status"] in ("error", "expired"):
                    break
                await asyncio.sleep(0.1)
            snap = qr.snapshot()
            if not snap["challenge_url"] and snap["status"] not in ("pending",):
                raise HTTPException(status_code=500, detail=snap.get("error") or "QR start failed")
            return {"status": snap["status"], "challenge_url": snap["challenge_url"]}
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))
        finally:
            # Release immediately after kicking off; polling is independent per session.
            session_manager.add_lock.release()

    def qr_poll(self):
        session = self.session
        qr = getattr(session, "_qr", None)
        if qr is None:
            return {"status": "idle"}
        snap = qr.snapshot()
        if snap["status"] == "confirmed":
            account_name = session.name
            # Despite its name, this accessor is non-destructive. Keep the token
            # in memory so another poll can retry a failed persistence attempt.
            token = qr.take_refresh_token()
            if not account_name or not token:
                return {
                    **snap,
                    "status": "error",
                    "error": "Steam QR confirmation did not include a refresh token. "
                             "Request a new QR code.",
                }
            try:
                saved = account_store.save_steam_token(
                    account_name,
                    token,
                    snap.get("steam_id", ""),
                )
            except SecretStoreError:
                saved = False
            if not saved:
                return {
                    **snap,
                    "status": "error",
                    "error": QR_TOKEN_PERSIST_ERROR,
                }
        return snap
