import asyncio
import sys as _sys

from backend.app.context import AppContext


class EventService:
    def __init__(self, ctx: AppContext):
        self.ctx = ctx

    def get_catalog(self):
        from career_bot.events.catalog import load_catalog, attach_effects
        try:
            catalog = load_catalog(self.ctx.base_dir, self.ctx.state_root)
            attach_effects(catalog, self.ctx.base_dir)
            return {"success": True, "events": list(catalog.values())}
        except Exception as e:
            return {"success": False, "detail": str(e), "events": []}

    def rebuild(self):
        from career_bot.events.catalog import build_catalog_from_logs
        try:
            catalog = build_catalog_from_logs(
                self.ctx.base_dir,
                self.ctx.state_root,
            )
            return {"success": True, "count": len(catalog)}
        except Exception as e:
            return {"success": False, "detail": str(e), "count": 0}

    async def update_database(self):
        # Re-scrape gametora for the full EN training-event effect DB (event names,
        # owning card/trainee, and every choice's label + reward effect), then rebuild
        # the catalog so the new data shows immediately. Network-bound (~30-60s).
        #
        # scrape_gametora_effects decrypts gametora's obfuscated text dictionaries
        # (XOR key auto-recovered) and refuses to overwrite the committed effect DB
        # with garbage if that decode ever fails (raises → handled below). It also
        # merges non-destructively, preserving any existing real labels/names.
        from career_bot.events.catalog import build_catalog_from_logs
        scripts_dir = self.ctx.base_dir / "scripts"
        if str(scripts_dir) not in _sys.path:
            _sys.path.insert(0, str(scripts_dir))
        try:
            from scripts import scrape_gametora_effects as scraper
            result = await asyncio.to_thread(scraper.scrape, self.ctx.base_dir)
            catalog = build_catalog_from_logs(
                self.ctx.base_dir,
                self.ctx.state_root,
            )
            return {"success": True, "events": result.get("events", 0),
                    "multi": result.get("multi", 0), "count": len(catalog)}
        except Exception as e:
            return {"success": False, "detail": str(e)}

    def get_prefs(self):
        from career_bot.events.catalog import load_prefs
        try:
            prefs = load_prefs(self.ctx.base_dir, self.ctx.state_root)
            return {"success": True, "prefs": prefs}
        except Exception as e:
            return {"success": False, "detail": str(e), "prefs": {}}

    def set_prefs(self, prefs: dict):
        from career_bot.events.catalog import save_prefs
        try:
            save_prefs(self.ctx.base_dir, self.ctx.state_root, prefs)
            return {"success": True}
        except Exception as e:
            return {"success": False, "detail": str(e)}
