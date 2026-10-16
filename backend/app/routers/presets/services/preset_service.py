from backend.app.context import AppContext


class PresetService:
    def __init__(self, ctx: AppContext, kind: str = "skill"):
        self.kind = kind
        self.store = (
            ctx.race_preset_store if kind == "race" else ctx.preset_store
        )

    def get_all(self):
        return {"success": True, "presets": self.store.read_all()}

    def save(self, preset: dict):
        return {"success": True, "preset": self.store.write(preset)}

    def delete(self, name: str):
        return {"success": self.store.delete(name)}

    def save_races(self, preset_name: str, races: list[int]):
        preset = self.store.read_one(preset_name)
        if not preset:
            if self.kind != "race":
                return {
                    "success": False,
                    "detail": f"{preset_name} preset missing",
                }
            preset = {"name": preset_name, "extra_race_list": []}
        preset["extra_race_list"] = races
        self.store.write(preset)
        return {"success": True}
