"""
Mine career_log_*.json files for event metadata and manage per-event choice
preferences.

Catalog  -> <state_root>/event_catalog.json  (regenerable)
Prefs    -> <state_root>/event_prefs.json    (seeded from the shipped asset)
"""

import json
import logging
import sqlite3
from pathlib import Path

from core.runtime_paths import (
    atomic_write_private_text,
    create_private_text_once,
    resolve_master_json_path,
    resolve_state_root,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _walk(o, sink):
    """Recursively walk any JSON structure, calling sink(ev) for every item
    found inside a full response or a capped-body event summary."""
    if isinstance(o, dict):
        for ev in (o.get("unchecked_event_array") or []):
            if ev:
                sink(ev)
        for ev in (o.get("event_catalog_shape") or []):
            if ev:
                sink(ev)
        for v in o.values():
            _walk(v, sink)
    elif isinstance(o, list):
        for v in o:
            _walk(v, sink)


def _career_log_paths(log_dir):
    try:
        entries = list(Path(log_dir).iterdir())
    except OSError:
        return []
    paths = []
    for path in entries:
        name = path.name.casefold()
        if not name.startswith("career_log_") or not name.endswith(".json"):
            continue
        try:
            if path.is_file():
                paths.append(path)
        except OSError:
            continue
    return sorted(paths, key=lambda path: (path.name.casefold(), path.name))


def _load_name_maps(base_dir: Path, state_root=None):
    """Return (support_map, chara_map) with graceful fallback to empty dicts."""
    support_map = {}
    chara_map = {}

    support_path = resolve_master_json_path(
        base_dir, "support_list.json", state_root,
    )
    try:
        support_map = json.loads(support_path.read_text(encoding="utf-8"))
    # read_text -> OSError / UnicodeDecodeError(ValueError); json.loads -> ValueError.
    except (OSError, ValueError) as exc:
        log.warning(f"Event catalog support map load failed: {exc}")
        pass

    chara_path = resolve_master_json_path(
        base_dir, "chara_list.json", state_root,
    )
    try:
        chara_map = json.loads(chara_path.read_text(encoding="utf-8"))
    # read_text -> OSError / UnicodeDecodeError(ValueError); json.loads -> ValueError.
    except (OSError, ValueError) as exc:
        log.warning(f"Event catalog character map load failed: {exc}")
        pass

    return support_map, chara_map


def _load_master_meta(base_dir: Path):
    """Return (names, story_meta) from master.mdb:
      names      = {story_id_str: event_name}        (text_data cat 181)
      story_meta = {story_id_str: (support_card_id, card_id)}  (single_mode_story_data)
    Graceful fallback to empty dicts if master.mdb is missing/unreadable."""
    names: dict[str, str] = {}
    story_meta: dict[str, tuple] = {}
    try:
        import uma_data as _md
        mdb = _md.configured_master_mdb_path(base_dir)
        if not mdb or not Path(mdb).exists():
            return names, story_meta
        con = sqlite3.connect(str(mdb))
        try:
            cur = con.cursor()
            cur.execute('SELECT "index", text FROM text_data WHERE category = 181')
            for idx, text in cur.fetchall():
                if idx is not None and text:
                    names[str(idx)] = text
            cur.execute('SELECT story_id, support_card_id, card_id FROM single_mode_story_data WHERE story_id > 0')
            for sid, scid, cid in cur.fetchall():
                story_meta[str(sid)] = (int(scid or 0), int(cid or 0))
        finally:
            con.close()
    except Exception as exc:
        log.warning(f"Event catalog master metadata load failed: {exc}")
        pass
    return names, story_meta


def _load_bundled_choices(base_dir: Path) -> dict:
    """Read committed data/event_choices.json → {story_id_str: n_choices}.
    Ships choice counts (scraped from gametora) so the catalog is populated
    on any machine even before that machine has logged any events."""
    path = base_dir / "data" / "json" / "event_choices.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return {str(k): int(v) for k, v in raw.items()}
    # read_text -> OSError / UnicodeDecodeError(ValueError); json.loads -> ValueError;
    # raw.items() on a non-mapping -> AttributeError; int(v) over untrusted values ->
    # TypeError / ValueError.
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        log.warning(f"Event catalog bundled choices load failed: {exc}")
        return {}


def _load_owners(base_dir: Path) -> dict:
    """Read committed data/event_owners.json → {story_id_str: owner_name}
    (the support card / character the event belongs to, scraped from gametora)."""
    path = base_dir / "data" / "json" / "event_owners.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in raw.items() if v}
    # read_text -> OSError / UnicodeDecodeError(ValueError); json.loads -> ValueError;
    # raw.items() on a non-mapping -> AttributeError (str() cannot fail here).
    except (OSError, ValueError, AttributeError) as exc:
        log.warning(f"Event catalog owners load failed: {exc}")
        return {}


def _load_scraped_meta(base_dir: Path) -> dict:
    """Read data/event_effects_scraped.json → {story_id_str: {n_choices, name, source}}.

    This is the full EN training-event database scraped from gametora
    (scripts/scrape_gametora_effects.py). It is used to seed catalog rows for
    events this machine has neither logged nor present in the bundled choice-count
    map, so the *entire* event database is configurable in the UI — not just the
    ~2700 events with prior coverage. Graceful fallback to {} when absent."""
    path = base_dir / "data" / "json" / "event_effects_scraped.json"
    out: dict[str, dict] = {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    # read_text -> OSError / UnicodeDecodeError(ValueError); json.loads -> ValueError.
    except (OSError, ValueError) as exc:
        log.warning(f"Event catalog scraped metadata load failed: {exc}")
        return out
    if not isinstance(raw, dict):
        return out
    for sid, row in raw.items():
        if not isinstance(row, dict):
            continue
        choices = row.get("choices") or {}
        out[str(sid)] = {
            "n_choices": len(choices) if isinstance(choices, dict) else 0,
            "name": row.get("event_name") or "",
            "source": row.get("source") or "",
        }
    return out


def _classify(story_id, support_card_id, card_id, chara_id, support_map, chara_map,
              scraped_source=""):
    """Return (source, label) from explicit ids (master meta preferred, log fallback).

    ``scraped_source`` is gametora's own source taxonomy for the event
    (char|char_card|ssr|sr|group|friend|scenario|shared). It is consulted as a
    fallback — ahead of the bare story_id prefix guess — when there is no
    explicit support/chara id to classify from, since it is more reliable."""
    support_card_id = int(support_card_id or 0)
    card_id = int(card_id or 0)
    chara_id = int(chara_id or 0)
    story_id = str(story_id)

    if support_card_id > 0:
        support_info = support_map.get(str(support_card_id)) or {}
        label = support_info.get("name") or f"Support {support_card_id}"
        return "support", label

    if story_id.startswith("4"):
        return "scenario", "Scenario"

    chara_key = card_id or chara_id
    if chara_key > 0:
        label = chara_map.get(str(chara_key)) or f"Chara {chara_key}"
        return "chara", label

    # gametora's source taxonomy is more reliable than a bare story_id prefix
    # when we lack an explicit support/chara id. Map it onto our 4 UI buckets.
    scs = str(scraped_source or "").lower()
    if scs in ("char", "char_card"):
        return "chara", "Trainee event"
    if scs in ("ssr", "sr", "group", "friend"):
        return "support", "Support event"
    if scs == "scenario":
        return "scenario", "Scenario"
    if scs == "shared":
        return "other", "Common event"

    # Prefix fallback when master/log ids are absent (most 5xx/8xx events carry
    # no support_card_id/card_id in single_mode_story_data):
    #   5xx = trainee/chara story events, 8xx = support-card events.
    if story_id.startswith("5"):
        return "chara", "Trainee event"
    if story_id.startswith("8"):
        return "support", "Support event"

    return "other", f"Event {story_id}"


# ---------------------------------------------------------------------------
# Catalog build / load
# ---------------------------------------------------------------------------

def build_catalog_from_logs(base_dir, state_root=None, include_master=True) -> dict:
    """
    Build the event catalog: master.mdb events (names + source, all machines) +
    bundled choice counts + this machine's captured logs.

    Pass include_master=False to skip master.mdb (used in tests for isolation,
    since master.mdb resolves to a global default path outside base_dir).

    Glob <state_root>/bot_logs/career_log_*.json and walk every unchecked_event_array.
    item, and build a catalog dict keyed by story_id (str).

    Each entry:
        {
            story_id       : str,
            chara_id       : int,
            support_card_id: int,
            n_choices      : int,
            select_indexes : [int, ...],   # unique select_index values seen
            source         : "support"|"scenario"|"chara"|"other",
            label          : str,
            seen_count     : int,
        }

    Writes the result to <state_root>/event_catalog.json and returns the dict.
    A single bad log file never aborts the whole build.
    """
    base_dir = Path(base_dir)
    runtime_root = (
        Path(state_root).resolve()
        if state_root is not None
        else resolve_state_root(base_dir).root
    )
    support_map, chara_map = _load_name_maps(base_dir, runtime_root)
    if include_master:
        event_names, story_meta = _load_master_meta(base_dir)
    else:
        event_names, story_meta = {}, {}
    bundled_choices = _load_bundled_choices(base_dir)
    owners_map = _load_owners(base_dir)
    scraped_meta = _load_scraped_meta(base_dir)

    catalog: dict[str, dict] = {}

    def _ensure(story_id: str):
        if story_id in catalog:
            return catalog[story_id]
        entry = {
            "story_id": story_id,
            "chara_id": 0,
            "support_card_id": 0,
            "n_choices": 0,
            "select_indexes": [],
            "source": "other",
            "label": "",
            "name": event_names.get(story_id, ""),
            "seen_count": 0,
        }
        catalog[story_id] = entry
        return entry

    # 1) Seed from the bundled choice-count map (committed data/event_choices.json)
    #    only when another Global source confirms the story_id. The bundled map
    #    can contain JP-only ids; the EN scrape and Global master.mdb are the
    #    allowlist for pre-logged catalog rows. Live logs below are also Global.
    global_seed_ids = set(scraped_meta) | set(event_names) | set(story_meta)
    for story_id, n in bundled_choices.items():
        if story_id not in global_seed_ids:
            continue
        _ensure(story_id)["n_choices"] = int(n or 0)

    # 1.5) Seed from the scraped EN effect DB (data/event_effects_scraped.json) —
    #      the full gametora training-event database. Ensures every scraped event,
    #      including the ~950 not present in the bundled count map or local logs,
    #      gets a catalog row so its choices/effects are configurable in the UI.
    #      attach_effects() later overlays the per-choice effect text + bot pick.
    for story_id, meta in scraped_meta.items():
        entry = _ensure(story_id)
        if int(meta.get("n_choices") or 0) > entry["n_choices"]:
            entry["n_choices"] = int(meta["n_choices"])
        if not entry["name"] and meta.get("name"):
            entry["name"] = meta["name"]

    # 2) Overlay live logs (this machine's actual encounters): real choice counts,
    #    select indexes, seen counts, and ids for classification.
    log_files = _career_log_paths(runtime_root / "bot_logs")

    def _ingest(ev):
        story_id = str(ev.get("story_id", ""))
        if not story_id:
            return
        ci = ev.get("event_contents_info") or {}
        choice_array = ci.get("choice_array") or []
        n_choices = len(choice_array)
        select_indexes = sorted({
            int(c.get("select_index", 0))
            for c in choice_array if isinstance(c, dict)
        })
        entry = _ensure(story_id)
        entry["seen_count"] += 1
        if n_choices > entry["n_choices"]:
            entry["n_choices"] = n_choices
        entry["select_indexes"] = sorted(set(entry["select_indexes"]) | set(select_indexes))
        if not entry["support_card_id"]:
            entry["support_card_id"] = int(ci.get("support_card_id") or 0)
        if not entry["chara_id"]:
            entry["chara_id"] = int(ev.get("chara_id") or 0)

    for log_path in log_files:
        try:
            data = json.loads(log_path.read_text(encoding="utf-8"))
            _walk(data, _ingest)
        except Exception as exc:
            # A single bad log must not abort the whole build
            log.warning(f"Event catalog log load failed for {log_path}: {exc}")
            pass

    # Fill bundled choice counts for already-allowed rows, including rows that
    # were created from live logs after the initial bundled seed pass.
    for story_id, n in bundled_choices.items():
        entry = catalog.get(story_id)
        if entry is not None and int(n or 0) > entry["n_choices"]:
            entry["n_choices"] = int(n or 0)

    # 3) Resolve name + source/label for every entry. Prefer master.mdb metadata
    #    (single_mode_story_data) for support/card ids; fall back to log-derived ids.
    for story_id, entry in catalog.items():
        meta_scid, meta_cid = story_meta.get(story_id, (0, 0))
        support_card_id = meta_scid or entry["support_card_id"]
        card_id = meta_cid
        scs = scraped_meta.get(story_id, {}).get("source", "")
        source, label = _classify(
            story_id, support_card_id, card_id, entry["chara_id"], support_map, chara_map, scs
        )
        entry["source"] = source
        # Prefer the specific owner (support card / character) from gametora over
        # the generic prefix-based label ("Trainee event" / "Support event").
        entry["label"] = owners_map.get(story_id) or label
        if support_card_id and not entry["support_card_id"]:
            entry["support_card_id"] = int(support_card_id)
        if not entry["name"]:
            entry["name"] = event_names.get(story_id, "")

    # 4) GLOBAL-ONLY: keep only events whose NAME exists in master.mdb (text_data
    #    category 181). The user plays the Global server and does not want JP-only
    #    / unreleased training events (which have a Japanese name or none at all in
    #    the Global master.mdb) showing up or being scored. Gated on include_master
    #    so the master-less test path (include_master=False) is unaffected.
    if include_master and event_names:
        catalog = {sid: e for sid, e in catalog.items() if sid in event_names}

    # Write output
    out_path = runtime_root / "event_catalog.json"
    try:
        atomic_write_private_text(
            out_path,
            json.dumps(catalog, ensure_ascii=False, indent=2),
        )
    # mkdir/write_text -> OSError, or UnicodeEncodeError(ValueError) when a scraped
    # name carries an unencodable code point. json.dumps cannot fail: the catalog
    # only ever holds str/int/list values built above.
    except (OSError, ValueError):
        pass

    return catalog


def attach_effects(catalog: dict, base_dir) -> dict:
    """Overlay scraped gametora choice effects onto catalog rows (in place).

    For every event present in data/event_effects_scraped.json, adds:
      - ``choice_effects``: [{select_index, label, effect}, ...] sorted by index
      - ``recommended_choice``: 0-based POSITION (index into ``choice_effects``)
        the bot would auto-pick — matches the choice_number the bot sends
      - ``owner``: owning card / trainee name (EN) when the scraped DB has it
    Best-effort: a missing/corrupt DB leaves the catalog untouched.
    """
    from career_bot.events import scoring as es

    path = Path(base_dir) / "data" / "json" / "event_effects_scraped.json"
    try:
        scraped = json.loads(path.read_text(encoding="utf-8"))
    # read_text -> OSError / UnicodeDecodeError(ValueError); json.loads -> ValueError.
    except (OSError, ValueError) as exc:
        log.warning(f"Event catalog scraped effects attach failed: {exc}")
        return catalog
    if not isinstance(scraped, dict):
        return catalog
    for story_id, entry in catalog.items():
        if not isinstance(entry, dict):
            continue
        row = scraped.get(str(story_id))
        if not isinstance(row, dict):
            continue
        # Surface the owning card/trainee name from the scraped DB. Prefer it
        # over a generic/empty label so each event shows who it belongs to.
        owner = row.get("owner")
        if owner:
            entry["owner"] = owner
            cur = entry.get("label", "")
            if not cur or cur in ("Trainee event", "Support event") or str(cur).startswith("Event "):
                entry["label"] = owner
        choices = row.get("choices")
        if not isinstance(choices, dict) or not choices:
            continue
        effects = []
        for sel in sorted(choices.keys(), key=lambda s: int(s) if str(s).isdigit() else 0):
            info = choices.get(sel) or {}
            effects.append({
                "select_index": int(sel) if str(sel).isdigit() else sel,
                "label": info.get("label", ""),
                "effect": info.get("effect", ""),
            })
        entry["choice_effects"] = effects
        entry["recommended_choice"] = es.recommended_choice_position(row)
    return catalog


def load_catalog(base_dir, state_root=None) -> dict:
    """
    Load <state_root>/event_catalog.json.
    If missing (first run or gitignored), trigger build_catalog_from_logs.
    Returns empty dict if everything fails.
    """
    base_dir = Path(base_dir)
    runtime_root = (
        Path(state_root).resolve()
        if state_root is not None
        else resolve_state_root(base_dir).root
    )
    path = runtime_root / "event_catalog.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        # read_text -> OSError / UnicodeDecodeError(ValueError); json.loads -> ValueError.
        except (OSError, ValueError) as exc:
            log.warning(f"Event catalog load failed: {exc}")
            pass
    # Missing or corrupt — rebuild
    try:
        return build_catalog_from_logs(base_dir, runtime_root)
    except Exception as exc:
        log.warning(f"Event catalog build failed: {exc}")
        return {}


# ---------------------------------------------------------------------------
# Prefs helpers
# ---------------------------------------------------------------------------

def _event_prefs_path(base_dir, state_root=None) -> Path:
    source_root = Path(base_dir)
    runtime_root = (
        Path(state_root).resolve()
        if state_root is not None
        else resolve_state_root(source_root).root
    )
    path = runtime_root / "event_prefs.json"
    if not path.exists():
        seed = source_root / "data" / "json" / "event_prefs.json"
        try:
            if seed.exists():
                create_private_text_once(
                    path,
                    seed.read_text(encoding="utf-8"),
                )
        except (OSError, ValueError) as exc:
            log.warning(f"Event catalog preferences seed failed: {exc}")
    return path


def load_prefs(base_dir, state_root=None) -> dict:
    """
    Load runtime event preferences as {story_id_str: choice_index_int}.
    Returns empty dict if file is missing or unreadable.
    Silently drops any entries that are not (str key, non-negative int value).
    """
    path = _event_prefs_path(base_dir, state_root)
    raw: dict = {}
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        # read_text -> OSError / UnicodeDecodeError(ValueError); json.loads -> ValueError.
        except (OSError, ValueError) as exc:
            log.warning(f"Event catalog preferences load failed: {exc}")
            pass

    result: dict[str, int] = {}
    for k, v in raw.items():
        if isinstance(k, str) and isinstance(v, int) and v >= 0:
            result[k] = v
    return result


def save_prefs(base_dir, state_root, prefs: dict) -> None:
    """
    Write preferences to <state_root>/event_prefs.json.
    Validates: keys must be str, values must be non-negative int.
    Silently ignores junk entries; silently ignores write failures.
    """
    clean: dict[str, int] = {}
    for k, v in prefs.items():
        if isinstance(k, str) and isinstance(v, int) and v >= 0:
            clean[k] = v

    path = _event_prefs_path(base_dir, state_root)
    try:
        atomic_write_private_text(
            path,
            json.dumps(clean, ensure_ascii=False, indent=2),
        )
    # mkdir/write_text -> OSError, or UnicodeEncodeError(ValueError) on an
    # unencodable key. `clean` is validated {str: int}, so json.dumps cannot fail.
    except (OSError, ValueError):
        pass
