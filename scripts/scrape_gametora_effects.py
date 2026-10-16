"""
scrape_gametora_effects.py — build the COMPLETE EN (Global) training-event
database from gametora's static data: event name, owning card / trainee, and
the label + reward effect of every choice.

This supersedes scrape_gametora_events.py (which only captured choice *counts*
and owner names). The output is keyed by story_id and is a drop-in for
career_bot.events.catalog.attach_effects() / career_bot.events.EventManager,
which already read data/event_effects_scraped.json with this shape:

    {
      "<story_id>": {
        "event_name": "Hope She'll Like It...",
        "owner":      "Kitasan Black (...)",   # NEW: card / trainee name (EN)
        "source":     "shared",                # char|char_card|ssr|sr|group|
                                               # friend|scenario|shared
        "source_url": "https://gametora.com/umamusume/training-event-helper",
        "choices": {
          "1": {"label": "A Page About Cloudy Weather", "effect": "Bond +5, Power +20"},
          "2": {"label": "Full-Power Muscles!",          "effect": "Skill hint +1, Power +20"}
        }
      },
      ...
    }

HOW GAMETORA STORES THIS (all under https://gametora.com)
  /data/manifests/umamusume.json          logical-name -> content-hash
  /data/umamusume/<key>.<hash>.json        the data file for <key>

  training_events/<src> files are a list of groups:
      [ owner_id, [ event, event, ... ] ]
  each event is a nested tuple:
      [ internal_id, [ [choiceTextId, [rewardId, ...]], ... ], story_id, *history ]
  - story_id   : the in-game id the bot logs / master.mdb uses  (the dict key)
  - choiceTextId -> EN label   via the choice-text dict (auto-detected below)
  - rewardId     -> EN effect  via dict/evrew  (pre-formatted strings)
  - event name   via dict/te_names_by_id_en (per-story override) then
                    dict/te_names_en (flat, by internal_id)

EN / GLOBAL ONLY
  - Text comes from the *_en dictionaries and characters/support-cards EN fields.
  - --global-only drops events whose owning card/trainee is not yet on Global
    (release_en / active_en / playable_en). Shared/scenario/common events are
    always kept (they are base-game).

The script self-validates: after building, it compares against the existing
data/event_effects_scraped.json (if present) and prints name/label/effect match
rates so any change in gametora's dict layout is caught immediately. If a live
dict cannot be decoded, choices fall back to the existing file so the output
never regresses.

Usage:
    python scripts/scrape_gametora_effects.py            # writes data/event_effects_scraped.json
    python scripts/scrape_gametora_effects.py --global-only
    python scripts/scrape_gametora_effects.py --dry-run  # validate, don't write
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

_PLACEHOLDER_RE = re.compile(r"Choice \d+\Z")

BASE = "https://gametora.com"
MANIFEST = "/data/manifests/umamusume.json"
SOURCE_URL = "https://gametora.com/umamusume/training-event-helper"
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "json" / "event_effects_scraped.json"

# Owner kind per training-event source file.
#   char       -> owner_id is char_id           (trainee)
#   char_card  -> owner_id is card_id           (trainee variant; char_id = id[:4])
#   ssr/sr/group -> owner_id is support_id      (support card)
#   friend     -> owner_id is support_id        (friend / NPC support)
#   scenario/shared -> no single owner          (common / scenario events)
EVENT_SOURCES = {
    "training_events/char": "char",
    "training_events/char_card": "char_card",
    "training_events/ssr": "ssr",
    "training_events/sr": "sr",
    "training_events/group": "group",
    "training_events/friend": "friend",
    "training_events/scenario": "scenario",
    "training_events/shared": "shared",
}


# ---------------------------------------------------------------------------
# Fetch helpers
# ---------------------------------------------------------------------------

def _get(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def _resolve_key(manifest: dict, key: str, prefer_en: bool = True) -> str | None:
    """Return the manifest key to use, preferring the /en variant for Global."""
    en = f"en/{key}"
    if prefer_en and en in manifest:
        return en
    if key in manifest:
        return key
    if en in manifest:
        return en
    return None


def _fetch_asset(manifest: dict, key: str, prefer_en: bool = True) -> Any:
    rk = _resolve_key(manifest, key, prefer_en)
    if rk is None:
        return None
    path = urllib.parse.quote(rk, safe="/")
    url = f"{BASE}/data/umamusume/{path}.{manifest[rk]}.json"
    return _get(url)


# ---------------------------------------------------------------------------
# Dictionary normalisation (handle list-indexed OR {str(id): val} shapes)
# ---------------------------------------------------------------------------

def _as_id_map(data: Any) -> dict:
    """Normalise a gametora dict file to {int_id: value}.

    gametora ships these as either a JSON array (index == id) or an object
    keyed by stringified id. We accept both so a layout flip doesn't break us.
    """
    out: dict[int, Any] = {}
    if isinstance(data, list):
        for i, v in enumerate(data):
            if v is not None and v != "":
                out[i] = v
    elif isinstance(data, dict):
        for k, v in data.items():
            try:
                out[int(k)] = v
            except (TypeError, ValueError):
                continue
    return out


def _label_from_entry(entry: Any) -> str:
    """Pull a human label out of a choice-text dict entry (str or list)."""
    if isinstance(entry, str):
        return entry
    if isinstance(entry, list):
        for x in entry:
            if isinstance(x, str) and x:
                return x
    return ""


# ---------------------------------------------------------------------------
# Text decryption (gametora obfuscates its EN text dictionaries)
# ---------------------------------------------------------------------------
# gametora ships te_names_en / choice-label dicts as base64 of a repeating-key
# XOR over the UTF-8 bytes (keystream resets per string). As of 2026-06 the key
# is the 4-byte ASCII string below; it is auto-detected each run (with this as a
# fallback) so a key rotation does not silently break the scrape.
_DEFAULT_XOR_KEY = b"k106"


def _xor_decode(b64: str, key: bytes) -> str:
    """base64-decode then XOR with the repeating key → UTF-8 text. "" on failure."""
    if not isinstance(b64, str) or not b64:
        return ""
    try:
        raw = base64.b64decode(b64)
    except Exception:
        return ""
    klen = len(key) or 1
    try:
        return bytes(raw[i] ^ key[i % klen] for i in range(len(raw))).decode("utf-8")
    except Exception:
        return ""


def _printable_rate(idmap: dict, key: bytes, sample: int = 500) -> float:
    """Fraction of a dict's values that XOR-decode to mostly-printable text."""
    vals = [v for v in idmap.values() if isinstance(v, str) and v][:sample]
    if not vals:
        return 0.0
    ok = 0
    for v in vals:
        t = _xor_decode(v, key)
        if t and sum(1 for c in t if 32 <= ord(c) < 127 or ord(c) > 0x2000) >= len(t) * 0.9:
            ok += 1
    return ok / len(vals)


def _detect_xor_key(te_idmap: dict, known_pairs: list | None = None) -> bytes:
    """Return the XOR key for gametora's text dicts.

    Prefers a key recovered from known plaintext — pairs of (cipher_bytes,
    old_label) from the previously-scraped file — by folding the keystream mod 4
    and majority-voting each byte; this is ground truth and survives a key
    rotation. Falls back to the known default when there is no usable plaintext."""
    if known_pairs:
        cols = [Counter() for _ in range(4)]
        for cipher, plain in known_pairs:
            pb = plain.encode("utf-8")
            for i in range(min(len(cipher), len(pb))):
                cols[i % 4][cipher[i] ^ pb[i]] += 1
        if all(cols):
            key = bytes(c.most_common(1)[0][0] for c in cols)
            if _printable_rate(te_idmap, key) >= 0.90:
                return key
    return _DEFAULT_XOR_KEY


def _decrypt_idmap(idmap: dict, key: bytes) -> dict:
    """Return {id: plaintext} from {id: base64-xor-blob}."""
    return {k: _xor_decode(v, key) if isinstance(v, str) else "" for k, v in idmap.items()}


def _detect_id_offset(te_decoded: dict, known_id_text: list, default: int = 1) -> int:
    """gametora's te_names_en list carries a phantom leading null, so a name/label
    id N actually resolves to ``te_decoded[N + 1]``. Recover that offset from known
    (id, old_text) pairs; fall back to ``default`` when there is nothing to match."""
    votes = Counter()
    for tid, text in known_id_text:
        if not text:
            continue
        for d in (1, 0, 2, -1):
            if te_decoded.get(tid + d) == text:
                votes[d] += 1
                break
    return votes.most_common(1)[0][0] if votes else default


# ---------------------------------------------------------------------------
# Reward (effect) formatting — evrew now ships [code, amount, skill_id?] tuples
# ---------------------------------------------------------------------------
# gametora used to publish pre-formatted effect strings ("Bond +5, Power +20");
# it now ships shorthand stat codes. This map (derived by aligning the codes
# against the previously-scraped effect strings) turns them back into the same
# readable form, which career_bot.events.scoring.parse_effect_string then scores.
_STAT_NAMES = {
    "sp": "Speed", "st": "Stamina", "po": "Power", "gu": "Guts", "in": "Wisdom",
    "bo": "Bond", "en": "Energy", "mo": "Motivation", "me": "Max Energy",
    "pt": "Skill points", "sk": "Skill hint", "sr": "Skill hint", "brp": "Skill hint",
    "5s": "All stats", "rs": "Random stats", "he": "Energy", "hp": "Energy",
}


# Reward codes that grant a skill hint; their entry carries the skill id(s).
_HINT_CODES = {"sk", "sr", "brp"}


def _strip_circle(name: str) -> str:
    """Drop gametora's gold/white rarity glyphs so skill variants collapse into one."""
    return name.replace("◎", "").replace("○", "").replace("◯", "").strip()


def _hint_skill_label(entry: list, skill_name: dict) -> str:
    """Resolve the EN skill name(s) a hint reward grants ("" if unknown).

    ``entry[2]`` is the skill id (int) for ``"sk"``, or a list of
    ``{"d": skill_id, "v": amount}`` for ``"sr"``/``"brp"``. The two ``d`` ids
    are usually the same skill's normal/gold variants, so we strip the rarity
    glyph and dedupe → a single name (matches gametora's "Name hint +1/+3")."""
    if not skill_name or len(entry) < 3:
        return ""
    ids = []
    third = entry[2]
    if isinstance(third, int):
        ids.append(third)
    elif isinstance(third, list):
        for item in third:
            if isinstance(item, dict) and isinstance(item.get("d"), int):
                ids.append(item["d"])
    seen = []
    for sid in ids:
        nm = skill_name.get(sid)
        if not nm:
            continue
        nm = _strip_circle(str(nm))
        if nm and nm not in seen:
            seen.append(nm)
    return "/".join(seen)


def _format_reward(entry: Any, skill_name: dict | None = None) -> str:
    """Format one evrew entry. ``["bo","+5"]`` → "Bond +5"; pass strings through.
    Unknown/special codes (status effects, scenario-specific) yield ""."""
    if isinstance(entry, str):
        return entry
    if not isinstance(entry, list) or not entry or not isinstance(entry[0], str):
        return ""
    name = _STAT_NAMES.get(entry[0])
    if not name:
        return ""
    # Name the specific skill a hint grants ("Long Straightaways hint +1/+3")
    # rather than a generic "Skill hint", when the skill id resolves.
    if entry[0] in _HINT_CODES and skill_name:
        label = _hint_skill_label(entry, skill_name)
        if label:
            name = f"{label} hint"
    raw_amt = entry[1] if len(entry) >= 2 else ""
    amt = "" if raw_amt is None else str(raw_amt).strip()
    if not amt:
        vals = []
        if len(entry) >= 3 and isinstance(entry[2], list):
            for item in entry[2]:
                if isinstance(item, dict) and item.get("v"):
                    vals.append(str(item["v"]).strip())
        vals = [v if v.startswith(("+", "-")) else f"+{v}" for v in vals if v]
        if vals:
            unique_vals = []
            for v in vals:
                if v not in unique_vals:
                    unique_vals.append(v)
            amt = "/".join(unique_vals)
    if amt:
        if amt[0] not in "+-":
            amt = "+" + amt
        return f"{name} {amt}"
    return name


# ---------------------------------------------------------------------------
# Owner-name resolution
# ---------------------------------------------------------------------------

def _support_name(card: dict) -> str:
    title = card.get("title_en") or card.get("title_en_gl") or card.get("title") or ""
    name = card.get("char_name") or card.get("name_en") or card.get("name_jp") or ""
    title = str(title).strip().strip("[]")
    name = str(name).strip()
    return f"{name} ({title})".strip() if title else name


def _is_global(record: dict) -> bool:
    return bool(
        record.get("release_en")
        or record.get("active_en")
        or record.get("playable_en")
        or record.get("release_en_date")
    )


def _scenario_names(scenarios: list) -> dict[int, str]:
    out: dict[int, str] = {}
    for s in scenarios or []:
        if not isinstance(s, dict):
            continue
        sid = s.get("id")
        nm = s.get("name_en") or s.get("name_en_full") or s.get("name_en_old") or s.get("name_ja")
        if sid is not None and nm:
            out[int(sid)] = str(nm)
    return out


def _build_owner_resolvers(characters: list, support_cards: list, scenarios: list | None = None):
    scenario_name = _scenario_names(scenarios or [])
    char_name: dict[int, str] = {}
    char_global: dict[int, bool] = {}
    for c in characters or []:
        if not isinstance(c, dict):
            continue
        cid = c.get("char_id")
        nm = c.get("en_name") or c.get("name_en")
        if cid is not None and nm:
            char_name[int(cid)] = str(nm)
            char_global[int(cid)] = _is_global(c)

    support_name: dict[int, str] = {}
    support_global: dict[int, bool] = {}
    for s in support_cards or []:
        if not isinstance(s, dict):
            continue
        sid = s.get("support_id")
        if sid is None:
            continue
        support_name[int(sid)] = _support_name(s)
        support_global[int(sid)] = _is_global(s)

    def resolve(kind: str, owner_id: Any) -> tuple[str, bool]:
        """Return (owner_name, is_global). is_global=True for ownerless events."""
        try:
            oid = int(owner_id)
        except (TypeError, ValueError):
            return "", True
        if kind == "char":
            return char_name.get(oid, ""), char_global.get(oid, False)
        if kind == "char_card":
            cid = int(str(oid)[:4]) if len(str(oid)) >= 4 else oid
            return char_name.get(cid, ""), char_global.get(cid, False)
        if kind in ("ssr", "sr", "group", "friend"):
            return support_name.get(oid, ""), support_global.get(oid, False)
        if kind == "scenario":
            # group id is the scenario id; label the event with the scenario name
            return scenario_name.get(oid, "Scenario"), True
        # shared: common base-game events, no single owner
        return "", True

    return resolve


# ---------------------------------------------------------------------------
# Core decode
# ---------------------------------------------------------------------------

def _event_name(internal_id: Any, story_id: Any, te_by_id: dict, te_flat: dict) -> str:
    sid = str(story_id)
    # per-story override dict is keyed by story_id (string)
    if isinstance(te_by_id, dict):
        v = te_by_id.get(sid) or te_by_id.get(story_id)
        if v:
            return str(v)
    try:
        iid = int(internal_id)
    except (TypeError, ValueError):
        return ""
    v = te_flat.get(iid)
    return str(v) if v else ""


def _effect_string(reward_ids: Any, evrew: dict, skill_name: dict | None = None) -> str:
    if not isinstance(reward_ids, list):
        return ""
    parts = []
    for rid in reward_ids:
        entry = evrew.get(_safe_int(rid))
        if entry is None:
            continue
        formatted = _format_reward(entry, skill_name)
        if formatted:
            parts.append(formatted)
    # gametora joins multi-reward strings with ", "
    return ", ".join(parts)


def _effect_string_from_entries(entries: Any, skill_name: dict | None = None) -> str:
    if not isinstance(entries, list):
        return ""
    parts = []
    for entry in entries:
        formatted = _format_reward(entry, skill_name)
        if formatted:
            parts.append(formatted)
    return ", ".join(parts)


def _decode_choices(
    choices: Any,
    evrew: dict,
    choice_texts: dict,
    materialized_event: Any = None,
    reward_ref_map: dict | None = None,
    skill_name: dict | None = None,
) -> dict:
    out: dict[str, dict] = {}
    if not isinstance(choices, list):
        return out
    materialized_choices = (
        materialized_event[1]
        if _looks_materialized_event(materialized_event) and isinstance(materialized_event[1], list)
        else []
    )
    for pos, ch in enumerate(choices, start=1):
        if not isinstance(ch, list) or len(ch) < 2:
            continue
        text_id, reward_ids = ch[0], ch[1]
        materialized_choice = (
            materialized_choices[pos - 1]
            if pos - 1 < len(materialized_choices) and isinstance(materialized_choices[pos - 1], list)
            else None
        )
        label = ""
        effect = ""
        if materialized_choice and len(materialized_choice) >= 2:
            label = str(materialized_choice[0] or f"Choice {pos}")
            effect = _effect_string_from_entries(materialized_choice[1], skill_name)
        if not label:
            label = _label_from_entry(choice_texts.get(_safe_int(text_id)))
        if not effect and reward_ref_map:
            mapped = [reward_ref_map.get(_safe_int(rid)) for rid in reward_ids or []]
            effect = _effect_string_from_entries(
                [entry for entry in mapped if entry is not None], skill_name)
        if not effect:
            effect = _effect_string(reward_ids, evrew, skill_name)
        out[str(pos)] = {
            "label": label,
            "effect": effect,
        }
    return out


def _safe_int(v: Any):
    try:
        return int(v)
    except (TypeError, ValueError):
        return v


def _looks_event(x: Any) -> bool:
    """An event tuple is [internal_id, choices_list, story_id(>=1e6), *history]."""
    return (
        isinstance(x, list) and len(x) >= 3
        and isinstance(x[1], list)
        and isinstance(x[2], (int, str))
        and str(x[2]).isdigit() and int(str(x[2])) >= 1_000_000
    )


def _looks_current_event_record(x: Any) -> bool:
    """Current compact event tuple, including no-choice rows used for alignment."""
    return (
        isinstance(x, list) and len(x) >= 3
        and (isinstance(x[1], list) or x[1] == "no")
        and isinstance(x[2], (int, str))
        and str(x[2]).isdigit() and int(str(x[2])) >= 1_000_000
    )


def _looks_materialized_event(x: Any) -> bool:
    """Old/materialized event tuple from ``training_events - Copy/*``."""
    return (
        isinstance(x, list) and len(x) >= 2
        and isinstance(x[0], str)
        and (isinstance(x[1], list) or x[1] == "no")
    )


def _event_sections(group: Any, pred) -> list[list]:
    """Return the per-section event lists from either compact or materialized groups."""
    out: list[list] = []
    if not isinstance(group, list):
        return out
    for sub in group[1:]:
        if not isinstance(sub, list):
            continue
        if pred(sub):
            out.append([sub])
            continue
        events = [ev for ev in sub if pred(ev)]
        if events:
            out.append(events)
    return out


def _materialized_event_name(event: Any) -> str:
    if not _looks_materialized_event(event):
        return ""
    # Translation rows are stored as [101, ko], [102, zh_tw], [103, en].
    for item in event[2:]:
        if isinstance(item, list) and len(item) >= 2 and item[0] == 103 and item[1]:
            return str(item[1])
    return str(event[0] or "")


def _build_materialized_lookups(raw_sources: dict[str, Any], materialized_sources: dict[str, Any]):
    """Align compact live events with gametora's materialized copy tables.

    The compact ``training_events/*`` reward ids are not ``dict/evrew`` indices.
    gametora still publishes ``training_events - Copy/*`` with the same
    source/owner/section/event order and fully-expanded reward tuples.  Aligning
    those rows gives the authoritative reward tuple for each choice.  A
    high-confidence reward-ref map is also derived for live-only rows that have
    no materialized counterpart.
    """
    by_story: dict[str, Any] = {}
    reward_votes: dict[Any, Counter] = {}
    aligned_events = aligned_rewards = 0
    section_mismatches = event_mismatches = 0

    for key in EVENT_SOURCES:
        compact = raw_sources.get(key) or []
        mat_key = key.replace("training_events/", "training_events - Copy/")
        materialized = materialized_sources.get(mat_key) or []
        materialized_by_owner = {
            group[0]: group for group in materialized
            if isinstance(group, list) and group
        }
        for group in compact:
            if not isinstance(group, list) or not group:
                continue
            materialized_group = materialized_by_owner.get(group[0])
            if materialized_group is None:
                continue
            compact_sections = _event_sections(group, _looks_current_event_record)
            materialized_sections = _event_sections(materialized_group, _looks_materialized_event)
            if len(compact_sections) != len(materialized_sections):
                section_mismatches += 1
            for compact_section, materialized_section in zip(compact_sections, materialized_sections):
                if len(compact_section) != len(materialized_section):
                    event_mismatches += 1
                for compact_event, materialized_event in zip(compact_section, materialized_section):
                    if not isinstance(compact_event[1], list) or not isinstance(materialized_event[1], list):
                        continue
                    sid = str(compact_event[2])
                    by_story[sid] = materialized_event
                    aligned_events += 1
                    for compact_choice, materialized_choice in zip(compact_event[1], materialized_event[1]):
                        if not (
                            isinstance(compact_choice, list)
                            and len(compact_choice) >= 2
                            and isinstance(compact_choice[1], list)
                            and isinstance(materialized_choice, list)
                            and len(materialized_choice) >= 2
                            and isinstance(materialized_choice[1], list)
                        ):
                            continue
                        for rid, reward in zip(compact_choice[1], materialized_choice[1]):
                            key_id = _safe_int(rid)
                            reward_votes.setdefault(key_id, Counter())[json.dumps(
                                reward, ensure_ascii=False, sort_keys=True
                            )] += 1
                            aligned_rewards += 1

    reward_ref_map: dict[Any, Any] = {}
    conflicted = 0
    for rid, votes in reward_votes.items():
        total = sum(votes.values())
        reward_json, count = votes.most_common(1)[0]
        if len(votes) == 1 or (total and count / total >= 0.90):
            reward_ref_map[rid] = json.loads(reward_json)
        else:
            conflicted += 1

    stats = {
        "events": aligned_events,
        "rewards": aligned_rewards,
        "reward_refs": len(reward_ref_map),
        "conflicted_refs": conflicted,
        "section_mismatches": section_mismatches,
        "event_mismatches": event_mismatches,
    }
    return by_story, reward_ref_map, stats


def _iter_events(source_data: Any):
    """Yield (owner_id, internal_id, choices, story_id) for a source file.

    Structure-agnostic: a group is [owner_id, ...sublists...]. Older files put
    the events at group[1]; newer trainee (char) / group files spread them across
    group[2], group[3], …, with group[1] holding metadata. We scan every sublist
    of the group and yield anything event-shaped, so both layouts work."""
    if not isinstance(source_data, list):
        return
    for group in source_data:
        if not isinstance(group, list) or not group:
            continue
        owner_id = group[0]
        for sub in group[1:]:
            if not isinstance(sub, list):
                continue
            for ev in sub:
                if _looks_event(ev):
                    yield owner_id, ev[0], ev[1], ev[2]


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def build(global_only: bool = False, old: dict | None = None) -> dict:
    old = old or {}
    print("Fetching manifest ...")
    man = _get(BASE + MANIFEST)

    print("Fetching reference data (characters, support cards, dictionaries) ...")
    characters = _fetch_asset(man, "characters") or []
    support_cards = _fetch_asset(man, "support-cards") or []
    scenarios = _fetch_asset(man, "scenarios") or []
    evrew = _as_id_map(_fetch_asset(man, "dict/evrew"))
    # skills: {skill_id: EN name} so hint rewards name the actual skill granted.
    skill_name = {}
    for s in (_fetch_asset(man, "skills") or []):
        if isinstance(s, dict) and s.get("id") is not None:
            nm = s.get("name_en") or s.get("enname")
            if nm:
                skill_name[int(s["id"])] = str(nm)
    # te_names_by_id_en is a tiny per-story override dict and ships in plaintext.
    te_by_id = _fetch_asset(man, "dict/te_names_by_id_en") or {}
    # te_names_en holds BOTH event titles (by internal_id) and choice labels (by
    # choiceTextId); it is XOR-obfuscated and carries a phantom leading null.
    te_flat_raw = _as_id_map(_fetch_asset(man, "dict/te_names_en"))

    resolve_owner = _build_owner_resolvers(characters, support_cards, scenarios)

    # first pass: gather known-plaintext (cipher bytes + old label) to recover the
    # XOR key, and (id, old_text) pairs to recover the list offset.
    raw_sources: dict[str, Any] = {}
    materialized_sources: dict[str, Any] = {}
    known_pairs: list = []
    known_id_text: list = []
    for key, kind in EVENT_SOURCES.items():
        try:
            data = _fetch_asset(man, key)
        except Exception as e:
            print(f"  ! failed {key}: {e}")
            data = None
        raw_sources[key] = data
        copy_key = key.replace("training_events/", "training_events - Copy/")
        try:
            materialized_sources[copy_key] = _fetch_asset(man, copy_key, prefer_en=False)
        except Exception as e:
            print(f"  ! failed {copy_key}: {e}")
            materialized_sources[copy_key] = None
        for _owner, internal_id, choices, story_id in _iter_events(data):
            old_row = old.get(str(story_id)) or {}
            old_name = old_row.get("event_name")
            if old_name:
                known_id_text.append((_safe_int(internal_id), old_name))
            old_choices = old_row.get("choices") or {}
            for pos, ch in enumerate(choices, start=1):
                if not (isinstance(ch, list) and ch):
                    continue
                tid = _safe_int(ch[0])
                old_label = (old_choices.get(str(pos)) or {}).get("label")
                if not old_label:
                    continue
                known_id_text.append((tid, old_label))
                blob = te_flat_raw.get(tid)
                if isinstance(blob, str) and blob:
                    try:
                        known_pairs.append((base64.b64decode(blob), old_label))
                    except Exception:
                        pass

    # Decrypt gametora's obfuscated text dict (auto-detect / recover the key),
    # then correct the phantom-leading-null offset so id N -> te[N].
    xor_key = _detect_xor_key(te_flat_raw, known_pairs)
    te_decoded = _decrypt_idmap(te_flat_raw, xor_key)
    offset = _detect_id_offset(te_decoded, known_id_text)
    te_flat = {i - offset: v for i, v in te_decoded.items()}
    choice_texts = te_flat  # labels and titles live in the same dict
    print(f"  text XOR key: {xor_key!r} (decode rate "
          f"{_printable_rate(te_flat_raw, xor_key)*100:.0f}%), id offset {offset:+d}")

    materialized_by_story, reward_ref_map, materialized_stats = _build_materialized_lookups(
        raw_sources, materialized_sources
    )
    print("  materialized reward join: "
          f"{materialized_stats['events']} events, {materialized_stats['rewards']} reward refs, "
          f"{materialized_stats['reward_refs']} fallback ids "
          f"({materialized_stats['conflicted_refs']} conflicted ids skipped)")

    out: dict[str, dict] = {}
    for key, kind in EVENT_SOURCES.items():
        data = raw_sources.get(key)
        if data is None:
            continue
        added = 0
        for owner_id, internal_id, choices, story_id in _iter_events(data):
            sid = str(story_id)
            owner_name, is_global = resolve_owner(kind, owner_id)
            if global_only and not is_global:
                continue
            materialized_event = materialized_by_story.get(sid)
            row = {
                "event_name": (
                    _materialized_event_name(materialized_event)
                    or _event_name(internal_id, story_id, te_by_id, te_flat)
                ),
                "owner": owner_name,
                "source": kind,
                "source_url": SOURCE_URL,
                "choices": _decode_choices(
                    choices, evrew, choice_texts, materialized_event,
                    reward_ref_map, skill_name
                ),
            }
            # keep the richest record if a story_id appears twice
            if sid not in out or len(row["choices"]) >= len(out[sid].get("choices", {})):
                out[sid] = row
            added += 1
        print(f"  {key}: {added} events (running total {len(out)})")

    if not out:
        raise RuntimeError("No events decoded — gametora layout may have changed.")
    return out


# ---------------------------------------------------------------------------
# Fallback + validation against the existing file
# ---------------------------------------------------------------------------

def _is_placeholder(label: Any) -> bool:
    """True for an empty label or a generic 'Choice N' stand-in."""
    if not isinstance(label, str) or not label.strip():
        return True
    return bool(_PLACEHOLDER_RE.match(label.strip()))


def _merge_preserving(new: dict, old: dict) -> dict:
    """Overlay the freshly-decoded ``new`` with any real value the committed
    ``old`` already had, so a re-scrape never regresses previously-good data:

      - keep an old non-placeholder choice label only when the new one is empty
        or a placeholder;
      - keep an old event name only when the new one is empty / placeholder;
      - keep an old effect only when the new build lost it.

    ``new`` is the base (it is the superset that recovered char/group events and
    owners). Mutates and returns ``new``; also reports counts."""
    kept_labels = kept_names = kept_effects = 0
    for sid, nrow in new.items():
        orow = old.get(sid)
        if not isinstance(orow, dict):
            continue
        oname = orow.get("event_name")
        if oname and _is_placeholder(nrow.get("event_name")):
            nrow["event_name"] = oname
            kept_names += 1
        ochoices = orow.get("choices") or {}
        for k, nc in (nrow.get("choices") or {}).items():
            oc = ochoices.get(k) or {}
            olabel = oc.get("label")
            if not _is_placeholder(olabel) and not nc.get("label"):
                nc["label"] = olabel
                kept_labels += 1
            if not nc.get("effect") and oc.get("effect"):
                nc["effect"] = oc["effect"]
                kept_effects += 1
    return {"labels": kept_labels, "names": kept_names, "effects": kept_effects}


def _validate(new: dict, old: dict) -> None:
    common = set(new) & set(old)
    if not common:
        print("Validation: no overlap with existing file (fresh build).")
        return
    name_ok = label_ok = eff_ok = label_n = eff_n = 0
    for sid in common:
        if new[sid].get("event_name") == old[sid].get("event_name"):
            name_ok += 1
        for k, oc in (old[sid].get("choices") or {}).items():
            nc = (new[sid].get("choices") or {}).get(k) or {}
            if oc.get("label"):
                label_n += 1
                label_ok += int(nc.get("label") == oc.get("label"))
            if oc.get("effect"):
                eff_n += 1
                eff_ok += int(nc.get("effect") == oc.get("effect"))
    print("Validation vs existing data/json/event_effects_scraped.json:")
    print(f"  overlap events : {len(common)}")
    print(f"  event_name match: {name_ok}/{len(common)} ({name_ok/len(common)*100:.1f}%)")
    if label_n:
        print(f"  choice label match: {label_ok}/{label_n} ({label_ok/label_n*100:.1f}%)")
    if eff_n:
        print(f"  choice effect match: {eff_ok}/{eff_n} ({eff_ok/eff_n*100:.1f}%)")
    print(f"  NEW owner names populated: "
          f"{sum(1 for r in new.values() if r.get('owner'))}/{len(new)}")


def _decoded_label_rate(data: dict) -> float:
    """Fraction of non-empty choice labels that look like real text rather than
    gametora's obfuscated base64 blobs.  Materialized gametora rows often carry
    JP choice labels, so CJK/kana text is considered decoded even without spaces."""
    total = decoded = 0
    for row in data.values():
        for ch in (row.get("choices") or {}).values():
            label = ch.get("label") or ""
            if not label:
                continue
            total += 1
            if _looks_real_text(label):
                decoded += 1
    return (decoded / total) if total else 0.0


def _looks_real_text(text: Any) -> bool:
    if not isinstance(text, str) or not text.strip():
        return False
    s = text.strip()
    if " " in s:
        return True
    if re.search(r"[\u3040-\u30ff\u3400-\u9fff]", s):
        return True
    if re.search(r"[A-Za-z]", s) and not re.fullmatch(r"[A-Za-z0-9+/=]{16,}", s):
        return True
    return False


def _load_existing(out_path: Path) -> dict:
    if out_path.exists():
        try:
            data = json.loads(out_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def _write_output(out_path: Path, data: dict) -> None:
    payload = json.dumps(
        data, ensure_ascii=False, indent=0, sort_keys=True,
    ).encode("utf-8")
    out_path.write_bytes(payload)


def scrape(base_dir=ROOT, global_only: bool = False, force: bool = False) -> dict:
    """Importable entry point used by the API's "Update Event Database" button.

    Builds the EN training-event effect DB (passing the existing file in so the
    XOR key can be recovered from known plaintext), repairs empty rows from the
    old file, and writes data/event_effects_scraped.json under ``base_dir``.
    Refuses to overwrite a good file with obfuscated garbage (decoded-label rate
    < 30%) unless ``force``. Returns {"events", "multi", "owners"}.
    Mirrors scrape_gametora_events.scrape() so callers can swap them."""
    base_dir = Path(base_dir)
    out_path = base_dir / "data" / "json" / "event_effects_scraped.json"
    old = _load_existing(out_path)

    new = build(global_only=global_only, old=old)
    if old:
        _merge_preserving(new, old)

    rate = _decoded_label_rate(new)
    if rate < 0.30 and not force:
        raise RuntimeError(
            f"decoded-label rate {rate*100:.0f}% too low — gametora's text dicts "
            "look obfuscated; refusing to overwrite the existing effect DB.")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    _write_output(out_path, new)
    multi = sum(1 for r in new.values() if len(r.get("choices", {})) > 1)
    owners = sum(1 for r in new.values() if r.get("owner"))
    return {"events": len(new), "multi": multi, "owners": owners}


def main() -> int:
    ap = argparse.ArgumentParser(description="Scrape gametora EN training-event effects.")
    ap.add_argument("--global-only", action="store_true",
                    help="Drop events whose owning card/trainee is not on Global.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Validate and report, but do not write the output file.")
    ap.add_argument("--force", action="store_true",
                    help="Write even if the decoded-label rate looks obfuscated "
                         "(overrides the anti-regression guard).")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    out_path = Path(args.out)
    old = _load_existing(out_path)

    try:
        new = build(global_only=args.global_only, old=old)
    except Exception as e:
        print(f"Failed: {e}")
        return 1

    if old:
        kept = _merge_preserving(new, old)
        if any(kept.values()):
            print(f"Preserved from existing file: {kept['labels']} labels, "
                  f"{kept['names']} names, {kept['effects']} effects.")
    _validate(new, old)

    if args.dry_run:
        print("Dry run — not writing.")
        return 0

    # Anti-regression guard: gametora obfuscates its training-event text dicts.
    # If the XOR key could not be recovered the labels come back as base64 blobs
    # — refuse to overwrite a good committed file with such garbage unless --force.
    rate = _decoded_label_rate(new)
    print(f"Decoded-label rate: {rate*100:.0f}% (labels containing real text)")
    if rate < 0.30 and not args.force:
        print("REFUSING to write: decoded-label rate too low — gametora's text "
              "dictionaries look obfuscated. The existing file is left untouched. "
              "Re-run with --force only if you are sure this output is correct.")
        return 2

    out_path.parent.mkdir(parents=True, exist_ok=True)
    _write_output(out_path, new)
    multi = sum(1 for r in new.values() if len(r.get("choices", {})) > 1)
    print(f"Wrote {out_path} — {len(new)} events ({multi} multi-choice), "
          f"{sum(1 for r in new.values() if r.get('owner'))} with owner.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
