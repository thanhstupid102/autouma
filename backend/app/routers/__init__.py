from fastapi import FastAPI

from .accounts.controllers import router as accounts_router
from .auth.controllers import router as auth_router
from .assets.controllers import router as assets_router
from .bot_config.controllers import router as bot_config_router
from .careers.controllers import router as careers_router
from .debug.controllers import router as debugs_router
from .events.controllers import router as events_router
from .master_data.controllers import router as master_data_router
from .others.controllers import router as others_router
from .parents.controllers import router as parents_router
from .presets.controllers import router as presets_router
from .scenarios.controllers import router as scenarios_router
from .selections.controllers import router as selections_router
from .sessions.controllers import router as sessions_router
from .settings.controllers import router as settings_router
from .skills.controllers import router as skills_router
from .steam.controllers import router as steams_router


# Single source of truth for domains registered under the "/api" prefix.
# assets (empty prefix) and others (SPA catch-all, via include_catchall) are
# the two documented exceptions registered outside this tuple, guarded by
# tests/test_router_registry.py.
_API_ROUTERS = (
    accounts_router,
    auth_router,
    master_data_router,
    settings_router,
    bot_config_router,
    careers_router,
    events_router,
    parents_router,
    presets_router,
    selections_router,
    sessions_router,
    skills_router,
    scenarios_router,
    steams_router,
    debugs_router,
)


class NormalRouter:
    def __init__(self, app: FastAPI, prefix: str = "/api"):
        self.app = app
        self.prefix = prefix

        # Initialize routers
        self._init_routers_include_prefix()

    def _init_routers_include_prefix(self):
        for router in _API_ROUTERS:
            self.app.include_router(router, prefix=self.prefix)
        # assets_router carries full literal paths (a mix of "/api/..." and
        # bare-root paths, e.g. /sweep.png) -- include with an empty prefix,
        # not self.prefix, or every path would get an extra "/api" glued on.
        self.app.include_router(assets_router, prefix="")

    def include_catchall(self):
        """Register the SPA router ("/" and the "/{full_path:path}" catch-all)
        LAST -- after every other domain router AND after any app.mount()
        calls (e.g. the /static mount in backend/app/app.py), or the
        catch-all would shadow /api/* routes and mounted static assets.
        Call this explicitly, after all other setup, instead of from
        __init__.
        """
        self.app.include_router(others_router, prefix="")
