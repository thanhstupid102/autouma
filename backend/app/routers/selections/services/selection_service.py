import logging

from uma_api.session import Session
from backend.app.context import AppContext
from backend.app.domain.jsonstore import JsonFileStore


log = logging.getLogger(__name__)


class SelectionService:
    def __init__(self, session: Session, ctx: AppContext):
        self.session = session
        self.ctx = ctx

    def update(self, selection: dict):
        self.session.selection = selection
        # Remember the team per account so it's restored on re-open / restart (the
        # read side is account_store.load_selection, replayed by AuthService.login).
        # Matches account_store.save_selection exactly: same subdir ("selections"),
        # same default (selection or {}), same collapse_dot_runs (JsonFileStore
        # default True). Only the base_dir differs -- this one is request-scoped
        # (self.ctx.base_dir), account_store's is the module-global Settings.BASE_DIR.
        try:
            JsonFileStore(self.ctx.state_root, "selections").save(
                self.session.name, selection or {}
            )
        # JsonFileStore.save(): path building (TypeError), mkdir/write_text
        # (OSError, UnicodeEncodeError) and json.dumps (TypeError on an
        # unserializable selection value, ValueError on a circular reference).
        except (OSError, TypeError, ValueError) as exc:
            log.warning(
                f"Failed to save selection for '{self.session.name}': {type(exc).__name__}"
            )
        return {"success": True}
