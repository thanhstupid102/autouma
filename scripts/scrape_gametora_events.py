"""
scrape_gametora_events.py — fetch event choice counts and the owning
support-card / character for every single-mode event, from gametora.

Sources (all under https://gametora.com):
  /data/manifests/umamusume.json            logical-name -> content hash
  /data/umamusume/<key>.<hash>.json         data files

training_events/* encode each event as a nested tuple
  [event_internal_id, [ [choiceTextId, [rewardId, ...]], ... ], story_id, ...]
grouped by owner:  char -> char_id, char_card -> card_id (char in first 4 digits),
group -> support_id, friend -> npc, scenario/shared -> none.

We only take the choice COUNT and the owner — not the per-choice rewards.
gametora's reward data does not match the live game closely enough to display,
so effects are intentionally not scraped. Event names come from master.mdb at
catalog-build time; this script only supplies counts + owners, keyed by story_id
so it works on any machine without local logs.

Outputs:
  data/event_choices.json   {story_id: n_choices}     (merged with existing, keep max)
  data/event_owners.json    {story_id: owner_name}     (support card / character)

Importable: scrape(base_dir) -> {"events", "multi", "owners"}
Usage:  python scripts/scrape_gametora_events.py
"""
import json
import sys
import urllib.request
from pathlib import Path

BASE = "https://gametora.com"
MANIFEST = "/data/manifests/umamusume.json"
ROOT = Path(__file__).resolve().parent.parent

# Owner source per event file. None = no single owner (scenario / shared / common).
EVENT_FILES = {
    "training_events/char": "char",
    "training_events/char_card": "char_card",
    "training_events/friend": "friend",
    "training_events/group": "group",
    "training_events/scenario": None,
    "training_events/shared": None,
}


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def _file_url(manifest, key):
    return f"{BASE}/data/umamusume/{key}.{manifest[key]}.json"


def _walk(node, owner, counts, owners):
    """Collect (count, owner) for every event story_id in a subtree."""
    if isinstance(node, list):
        if len(node) >= 3 and isinstance(node[1], list) and isinstance(node[2], (int, str)):
            sid = str(node[2])
            if sid.isdigit() and int(sid) >= 1_000_000:
                n = len(node[1])
                if n >= counts.get(sid, 0):
                    counts[sid] = n
                if owner and sid not in owners:
                    owners[sid] = owner
        for x in node:
            _walk(x, owner, counts, owners)


def scrape(base_dir=ROOT):
    base_dir = Path(base_dir)
    man = _get(BASE + MANIFEST)

    char_names = {c["char_id"]: c.get("en_name") for c in _get(_file_url(man, "characters")) if c.get("char_id") and c.get("en_name")}
    support = {}
    for s in _get(_file_url(man, "support-cards")):
        sid = s.get("support_id")
        if sid:
            nm = s.get("char_name") or ""
            title = s.get("title_en") or ""
            support[sid] = f"{nm} ({title})".strip() if title else nm

    def owner_name(kind, group_id):
        try:
            gid = int(group_id)
        except (TypeError, ValueError):
            return None
        if kind == "char":
            return char_names.get(gid)
        if kind == "char_card":
            return char_names.get(int(str(gid)[:4]))  # card id -> char id (first 4 digits)
        if kind == "group":
            return support.get(gid)
        if kind == "friend":
            return "Friend event"
        return None

    counts, owners = {}, {}
    for key, kind in EVENT_FILES.items():
        h = man.get(key)
        if not h:
            continue
        try:
            data = _get(_file_url(man, key))
        except Exception as e:
            print(f"  ! failed {key}: {e}")
            continue
        before = len(counts)
        if kind is None:
            _walk(data, None, counts, owners)
        else:
            for group in data:
                if isinstance(group, list) and group:
                    oname = owner_name(kind, group[0])
                    _walk(group, oname, counts, owners)
        print(f"  {key}: total {len(counts)} (+{len(counts) - before})")

    if not counts:
        raise RuntimeError("No events extracted — gametora layout may have changed.")

    # counts: merge with existing (keep max). owners: authoritative overwrite.
    out_counts = base_dir / "data" / "json" / "event_choices.json"
    merged = {}
    if out_counts.exists():
        try:
            merged = {str(k): int(v) for k, v in json.loads(out_counts.read_text(encoding="utf-8")).items()}
        except Exception:
            merged = {}
    for sid, n in counts.items():
        merged[sid] = max(merged.get(sid, 0), int(n))
    out_counts.write_text(json.dumps(merged, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")
    (base_dir / "data" / "json" / "event_owners.json").write_text(
        json.dumps(owners, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")

    multi = sum(1 for v in merged.values() if v > 1)
    return {"events": len(merged), "multi": multi, "owners": len(owners)}


def main():
    print("Scraping gametora event data ...")
    try:
        res = scrape()
    except Exception as e:
        print(f"Failed: {e}")
        return 1
    print(f"Done — {res['events']} events ({res['multi']} multi-choice), "
          f"{res['owners']} with owner.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
