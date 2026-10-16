import json
import logging
from pathlib import Path

from career_bot.events import scoring as es
from core.runtime_paths import create_private_text_once, resolve_state_root

log = logging.getLogger(__name__)


class EventManager:
    def __init__(self, source_root, state_root=None):
        self.base_dir = Path(source_root)
        self.state_root = (
            Path(state_root).resolve()
            if state_root is not None
            else resolve_state_root(self.base_dir).root
        )
        self.outcomes = {}
        self.scraped_effects: dict = {}
        self.prefs: dict = {}
        self._prefs_mtime: float = 0.0
        self._load()
        self._load_prefs()

    def _load(self):
        path = self.base_dir / "data" / "json" / "event_outcomes.json"
        if path.exists():
            try:
                self.outcomes = json.loads(path.read_text(encoding="utf-8"))
            # read_text -> OSError / UnicodeDecodeError(ValueError); json.loads -> ValueError.
            except (OSError, ValueError) as exc:
                log.warning(f"Event outcomes load failed: {exc}")

        # gametora-scraped effect DB (story_id -> {choices: {select_index:
        # {label, effect}}}). Used to score choices when there is no curated
        # good/bad outcome, so previously-blind events get a real decision.
        scraped_path = self.base_dir / "data" / "json" / "event_effects_scraped.json"
        if scraped_path.exists():
            try:
                raw = json.loads(scraped_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    self.scraped_effects = raw
            # read_text -> OSError / UnicodeDecodeError(ValueError); json.loads -> ValueError.
            except (OSError, ValueError) as exc:
                log.warning(f"Event scraped effects load failed: {exc}")
                self.scraped_effects = {}

    def _prefs_path(self) -> Path:
        return self.state_root / "event_prefs.json"

    def _seed_prefs(self) -> None:
        path = self._prefs_path()
        if path.exists():
            return
        seed = self.base_dir / "data" / "json" / "event_prefs.json"
        try:
            if seed.exists():
                create_private_text_once(
                    path,
                    seed.read_text(encoding="utf-8"),
                )
        except (OSError, ValueError) as exc:
            log.warning(f"Event preferences seed failed: {exc}")

    def _load_prefs(self):
        """Load (or reload) state-root/event_prefs.json into self.prefs.
        Silently ignores missing file or parse errors.
        Validates: keys str, values non-negative int."""
        self._seed_prefs()
        path = self._prefs_path()
        try:
            mtime = path.stat().st_mtime if path.exists() else 0.0
        except OSError:  # stat()/exists() only ever fail with OSError
            mtime = 0.0

        self._prefs_mtime = mtime
        if not path.exists():
            self.prefs = {}
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            self.prefs = {
                k: v
                for k, v in raw.items()
                if isinstance(k, str) and isinstance(v, int) and v >= 0
            }
        # read_text -> OSError / UnicodeDecodeError(ValueError); json.loads ->
        # ValueError; raw.items() on a non-mapping payload -> AttributeError.
        except (OSError, ValueError, AttributeError):
            self.prefs = {}

    def _maybe_reload_prefs(self):
        """Reload prefs if the file has been modified since last load."""
        path = self._prefs_path()
        try:
            mtime = path.stat().st_mtime if path.exists() else 0.0
        except OSError:  # stat()/exists() only ever fail with OSError
            return
        if mtime != self._prefs_mtime:
            self._load_prefs()

    def choose(self, event, preset=None, current_turn=0, chara=None):
        # Hot-reload prefs if the file changed (picks up API edits without restart)
        self._maybe_reload_prefs()

        story_id = str(event.get("story_id", ""))
        choices = ((event.get("event_contents_info") or {}).get("choice_array") or [])

        # Internally, choices are the 0-based POSITION in choice_array
        # (0 = first option, 1 = second, ...), NOT the `select_index` field.
        # The runner converts this internal position to the game's wire
        # choice_number convention at the check_event boundary.

        # --- Per-event preference override (user explicit, highest priority) ---
        # The dashboard stores the pref as the 0-based choice position
        # ("Choice N" -> N-1), which is exactly what choose() returns.
        if story_id in self.prefs:
            idx = self.prefs[story_id]
            n = len(choices)
            if n > 0 and 0 <= idx < n:
                return idx
            # pref out of range -> fall through to normal logic

        if not choices:
            return 0

        # --- Hardcoded game-critical default from the original bot ---
        # Original bot sent wire choice_number=2 (the 2nd option) for this event.
        # Under the 1-based wire scheme that is 0-based POSITION 1; the runner
        # boundary adds +1 -> wire 2, preserving the original behavior.
        if story_id == "400004002":
            return 1

        # --- Curated good/bad outcomes (hand-tuned, high confidence) ---
        outcome_data = self.outcomes.get(story_id)

        # Fuzzy fallback: match on a 6-digit suffix and ONLY when it is unique.
        # The old 3-digit "first match wins" silently mis-scored unrelated events
        # that merely shared 3 trailing digits (e.g. 801001002 vs 830028002).
        if not outcome_data and len(story_id) >= 6:
            suffix = story_id[-6:]
            matches = [v for k, v in self.outcomes.items() if str(k).endswith(suffix)]
            if len(matches) == 1:
                outcome_data = matches[0]

        if outcome_data:
            outcomes = outcome_data.get("outcomes", {})
            for i, choice in enumerate(choices):
                select_index = str(choice.get("select_index", ""))
                if outcomes.get(select_index) == "good":
                    return i

        # --- Scraped-effect scoring (replaces the old blind "pick option 2") ---
        scored = self._score_choice_index(event, choices, preset, current_turn, chara)
        if scored is not None:
            return scored

        if len(choices) > 1:
            return 1
        return 0

    def _score_choice_index(self, event, choices, preset, current_turn, chara):
        """Pick the highest-scoring choice from the scraped effect DB, or None
        when this event has no scoreable scraped data (caller falls back)."""
        if not self.scraped_effects:
            return None
        story_id = str(event.get("story_id", ""))
        row = self.scraped_effects.get(story_id)
        if not isinstance(row, dict):
            return None
        preset = preset or {}
        stat_priority = es.stat_priority_from_targets(preset.get("expect_attribute"))
        prioritize_energy = bool(
            preset.get("prioritize_event_energy") or preset.get("prioritize_energy")
        )
        return es.best_choice_index(
            choices,
            row,
            stat_priority=stat_priority,
            chara=chara,
            turn=current_turn,
            prioritize_energy=prioritize_energy,
        )

    def describe_choice(self, event, position):
        """Return (event_name, effect_text) for the chosen 0-based POSITION, for
        logging the bot's pick. Both fall back to "" when the event is not in the
        scraped DB. The scraped `choices` are keyed by select_index ("1","2",...);
        sort them numerically so the Nth entry matches the Nth choice position."""
        story_id = str(event.get("story_id", ""))
        row = self.scraped_effects.get(story_id)
        if not isinstance(row, dict):
            return "", ""
        name = row.get("event_name") or ""
        effect = ""
        choices = row.get("choices")
        if isinstance(choices, dict) and position is not None:
            try:
                ordered = [choices[k] for k in sorted(choices, key=lambda x: int(x))]
            except (TypeError, ValueError):
                ordered = list(choices.values())
            if 0 <= position < len(ordered):
                effect = (ordered[position] or {}).get("effect") or ""
        return name, effect
