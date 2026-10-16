import base64
import os

from fastapi import HTTPException

from uma_api import account_io, game_service

from backend.app.context import AppContext
import backend.app.domain.account_store as account_store


class AccountService:
    def __init__(self, ctx: AppContext):
        self.ctx = ctx

    def list_all(self):
        accounts = self.ctx.session_manager.snapshot_all()
        for account in accounts:
            cfg = account_store.load_account_config(account["name"]) or {}
            account["steam_unbound_at"] = cfg.get("steam_unbound_at")
        return {"success": True, "accounts": accounts}

    def delete(self, name: str):
        safe = account_io.safe_account_name(name)
        self.ctx.session_manager.remove(safe)
        accounts_dir = self.ctx.session_manager.accounts_dir()
        removed = []
        for suffix in (".json", ".steam.json"):
            path = os.path.join(accounts_dir, safe + suffix)
            if os.path.exists(path):
                os.remove(path)
                removed.append(os.path.basename(path))
        game_service.clear_account_cache(self.ctx.state_root, safe)
        return {"success": True, "deleted": removed}

    def export(self, names: list[str], passphrase: str):
        if not passphrase:
            raise HTTPException(status_code=400, detail="Passphrase required")
        accounts_dir = self.ctx.session_manager.accounts_dir()
        payload = {}
        for name in names:
            safe = account_io.safe_account_name(name)   # prevent path-traversal reads
            try:
                payload[safe] = account_io.read_account_files(
                    accounts_dir,
                    self.ctx.state_root,
                    safe,
                )
            except FileNotFoundError:
                raise HTTPException(status_code=404, detail=f"Account '{name}' not found")
        if not payload:
            raise HTTPException(status_code=400, detail="No accounts to export")
        return account_io.encrypt_bundle(payload, passphrase)

    def import_bundle(self, bundle_b64: str, passphrase: str, overwrite: bool):
        try:
            blob = base64.b64decode(bundle_b64)
        # b64decode rejects bad padding/alphabet with binascii.Error and non-ASCII
        # text with UnicodeEncodeError -- both ValueError subclasses; TypeError
        # covers a non-str/bytes payload.
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid bundle encoding")
        try:
            payload = account_io.decrypt_bundle(blob, passphrase)
        except account_io.BadPassphrase as e:
            raise HTTPException(status_code=400, detail=str(e))
        accounts_dir = self.ctx.session_manager.accounts_dir()
        imported, skipped = [], []
        for name, data in payload.items():
            safe = account_io.safe_account_name(name)
            exists = os.path.exists(os.path.join(accounts_dir, safe + ".json"))
            if exists and not overwrite:
                skipped.append(safe); continue
            account_io.write_account_files(
                accounts_dir,
                self.ctx.state_root,
                safe,
                data,
            )
            imported.append(safe)
        return {"success": True, "imported": imported, "skipped": skipped}
