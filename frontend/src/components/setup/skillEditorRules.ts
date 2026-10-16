/**
 * skillEditorRules — pure, side-effect-free functions for the skill editor.
 *
 * All functions operate on plain data and return new data; no DOM, no React,
 * no Zustand. This makes them unit-testable without any UI harness.
 *
 * Data model (from legacy app.js):
 *   learn_skill_list     = string[][]  — tiers, each tier is an array of skill names
 *   learn_skill_blacklist = string[]   — flat array of skill names
 *
 * Skills are always tracked by name (string), never by id.
 */

import type { SkillEntry } from '@/api/types'
import { compareDisplayText } from '@/lib/locale'

// ---------------------------------------------------------------------------
// Filter constants — ported EXACTLY from app.js:1381-1399
// ---------------------------------------------------------------------------

export interface AffinityFilter {
  id: number | 'turf'
  label: string
}

export interface ColorFilter {
  id: string
  label: string
  color: string
  iconPrefixes: string[]
}

export const SKILL_FILTERS: AffinityFilter[] = [
  { id: 101, label: 'Front' },
  { id: 102, label: 'Pace' },
  { id: 103, label: 'Late' },
  { id: 104, label: 'End' },
  { id: 201, label: 'Short' },
  { id: 202, label: 'Mile' },
  { id: 203, label: 'Medium' },
  { id: 204, label: 'Long' },
  { id: 502, label: 'Dirt' },
  { id: 'turf', label: 'Turf' },
]

export const COLOR_FILTERS: ColorFilter[] = [
  { id: 'green',  label: 'Green',  color: '#4ade80', iconPrefixes: ['1001', '1002', '1003', '1004', '1005', '1006'] },
  { id: 'blue',   label: 'Blue',   color: '#60a5fa', iconPrefixes: ['2002'] },
  { id: 'yellow', label: 'Yellow', color: '#fbbf24', iconPrefixes: ['2001', '2004', '2005', '2006', '2009'] },
  { id: 'red',    label: 'Red',    color: '#f87171', iconPrefixes: ['3001', '3002', '3004', '3005', '3007'] },
]

/**
 * Unique skills are character-signature skills. The `rarity` field comes from
 * the game master DB (uma_data/legacy_json.py synthesize_skill_data →
 * skill_data table). Observed in data/skill_data.json: rarity 1 = normal,
 * 2 = rare (gold), and 3/4/5 are the unique tiers — e.g. rarity 3 "Red Ace" /
 * "Xceleration", rarity 4 "Resplendent Red Ace" / "Cut and Drive!" (evolved),
 * rarity 5 "Sky-High Teio Step" / "Shooting Star" (scenario/special). All gold
 * non-unique skills stay at rarity 2, so "unique" = rarity >= 3.
 */
export const UNIQUE_RARITY_MIN = 3

export function isUniqueSkill(skill: DedupedSkill): boolean {
  return skill.rarity >= UNIQUE_RARITY_MIN
}

// ---------------------------------------------------------------------------
// Deduplicated skill entry (tags always number[])
// ---------------------------------------------------------------------------

export interface DedupedSkill {
  name: string
  rarity: number
  tags: number[]
  icon_id?: string | number
}

/**
 * dedupeSkills — app.js:1401-1422
 *
 * Accepts the raw skills record from GET /api/skills.
 * Deduplicates by name: keeps first occurrence but raises rarity to the max
 * seen and unions tags across all entries with that name.
 * Result is sorted by the pinned display locale.
 */
export function dedupeSkills(
  skillsRecord: Record<string, SkillEntry>,
): DedupedSkill[] {
  const map = new Map<string, DedupedSkill>()

  for (const [, s] of Object.entries(skillsRecord)) {
    const name = s.name
    const rarity = typeof s.rarity === 'number' ? s.rarity : 0
    const tags = (s.tags ?? []).filter((t): t is number => typeof t === 'number')

    if (!map.has(name)) {
      const iconId = s.icon_id as string | number | undefined
      map.set(name, {
        name,
        rarity,
        tags: [...tags],
        icon_id: iconId,
      })
    } else {
      const existing = map.get(name)!
      if (rarity > existing.rarity) existing.rarity = rarity
      for (const t of tags) {
        if (!existing.tags.includes(t)) existing.tags.push(t)
      }
    }
  }

  return Array.from(map.values()).sort(
    (a, b) => compareDisplayText(a.name, b.name),
  )
}

// ---------------------------------------------------------------------------
// Filtering — app.js:1475-1506
// ---------------------------------------------------------------------------

/**
 * skillColorMatches — check whether a skill's icon_id starts with any of a
 * color filter's iconPrefixes.
 */
export function skillColorMatches(
  iconId: string | number | undefined,
  colorFilter: ColorFilter,
): boolean {
  const id = String(iconId ?? '')
  return colorFilter.iconPrefixes.some((prefix) => id.startsWith(prefix))
}

/**
 * matchesFilters — returns true if a skill should be shown given the current
 * search query, affinity filter, and color filter.
 */
export function matchesFilters(
  skill: DedupedSkill,
  query: string,
  affinityFilter: number | 'turf' | null,
  colorFilter: ColorFilter | null,
  uniqueOnly = false,
): boolean {
  // Search query
  if (query && !skill.name.toLowerCase().includes(query.toLowerCase())) {
    return false
  }

  // Unique-only filter — show only character-signature (unique) skills
  if (uniqueOnly && !isUniqueSkill(skill)) {
    return false
  }

  // Affinity filter
  if (affinityFilter !== null) {
    if (affinityFilter === 'turf') {
      // Turf = NOT Dirt (tag 502)
      if (skill.tags.includes(502)) return false
    } else {
      if (!skill.tags.includes(affinityFilter)) return false
    }
  }

  // Color filter
  if (colorFilter !== null) {
    if (!skillColorMatches(skill.icon_id, colorFilter)) return false
  }

  return true
}

// ---------------------------------------------------------------------------
// Mutation reducers — operate on {learn_skill_list, learn_skill_blacklist}
// ---------------------------------------------------------------------------

export interface SkillLists {
  learn_skill_list: string[][]
  learn_skill_blacklist: string[]
}

/**
 * buildGroupSiblings — map every skill NAME to all NAMES sharing its skill
 * group (group_id from data/skill_data.json). A group is the tier ladder of one
 * skill — white ○, ◎, and the gold (often a different name, e.g. "Corner Adept ○"
 * → "Professor of Curvature"). Some groups have 3 tiers. Selecting any tier in the
 * editor should move the WHOLE group, so blacklisting/prioritising a skill covers
 * every tier (and the bot never buys a lower tier of a group it already owns).
 *
 * Uniques (rarity >= 3) are character-signature lines and are NOT grouped — each
 * stays on its own so a unique never pulls unrelated tiers.
 */
export function buildGroupSiblings(
  skillsRecord: Record<string, SkillEntry>,
): Record<string, string[]> {
  const byGroup = new Map<number, Set<string>>()
  const nameToGroup = new Map<string, number>()
  for (const s of Object.values(skillsRecord)) {
    const gid = Number((s as { group_id?: unknown }).group_id) || 0
    const rarity = typeof s.rarity === 'number' ? s.rarity : 0
    if (!gid || !s.name || rarity >= UNIQUE_RARITY_MIN) continue
    if (!byGroup.has(gid)) byGroup.set(gid, new Set())
    byGroup.get(gid)!.add(s.name)
    nameToGroup.set(s.name, gid)
  }
  const out: Record<string, string[]> = {}
  for (const [name, gid] of nameToGroup) {
    out[name] = Array.from(byGroup.get(gid)!)
  }
  return out
}

/** Expand a skill name to every name in its group (itself if no group/siblings). */
function expandGroup(name: string, siblings?: Record<string, string[]>): string[] {
  const group = siblings?.[name]
  return group && group.length ? group : [name]
}

/**
 * addSkillToFocus — app.js:1611-1629
 *
 * If activeEditTier === null → add to blacklist (if not already present).
 * Otherwise → ensure the tier array exists and add (if not already present).
 */
export function addSkillToFocus(
  lists: SkillLists,
  name: string,
  activeEditTier: number | null,
  siblings?: Record<string, string[]>,
): SkillLists {
  const names = expandGroup(name, siblings)

  if (activeEditTier === null) {
    const bl = lists.learn_skill_blacklist
    const toAdd = names.filter((n) => !bl.includes(n))
    if (toAdd.length === 0) return lists
    return { ...lists, learn_skill_blacklist: [...bl, ...toAdd] }
  }

  const tiers = [...lists.learn_skill_list]
  // Ensure tier exists
  while (tiers.length <= activeEditTier) tiers.push([])
  const tier = tiers[activeEditTier]
  const toAdd = names.filter((n) => !tier.includes(n))
  if (toAdd.length === 0) return lists
  tiers[activeEditTier] = [...tier, ...toAdd]
  return { ...lists, learn_skill_list: tiers }
}

/**
 * deleteSkillFromTier — app.js:1596-1607
 *
 * Remove ONLY the exact clicked skill name from a tier. Each tier renders one chip
 * per name, so deleting a high tier (e.g. the gold "Professor of Curvature") must
 * leave its lower tier ("Corner Adept ○") in place. Adding still pulls the whole
 * group (addSkillToFocus), but delete is exact-name only — never group-expanded,
 * so this deliberately takes no group-siblings map.
 */
export function deleteSkillFromTier(
  lists: SkillLists,
  tierIdx: number,
  name: string,
): SkillLists {
  const tiers = lists.learn_skill_list.map((t, i) =>
    i === tierIdx ? t.filter((s) => s !== name) : t,
  )
  return { ...lists, learn_skill_list: tiers }
}

/**
 * deleteSkillFromBlacklist — app.js:1599-1601
 *
 * Remove ONLY the exact clicked skill name from the blacklist (no group expansion,
 * same rationale as deleteSkillFromTier — hence no group-siblings map).
 */
export function deleteSkillFromBlacklist(
  lists: SkillLists,
  name: string,
): SkillLists {
  return {
    ...lists,
    learn_skill_blacklist: lists.learn_skill_blacklist.filter((s) => s !== name),
  }
}

/**
 * addTier — app.js:1780-1788
 *
 * Push an empty tier. Returns new lists AND the new activeEditTier index.
 */
export function addTier(lists: SkillLists): { lists: SkillLists; newTierIdx: number } {
  const tiers = [...lists.learn_skill_list, []] as string[][]
  return {
    lists: { ...lists, learn_skill_list: tiers },
    newTierIdx: tiers.length - 1,
  }
}

/**
 * deleteTier — app.js:1584-1593
 *
 * Splice out tier at `idx`. Adjusts `activeEditTier`:
 *   === idx → null (the focused tier was deleted)
 *   >  idx  → idx - 1 (shift down)
 *   <  idx  → unchanged
 */
export function deleteTier(
  lists: SkillLists,
  idx: number,
  activeEditTier: number | null,
): { lists: SkillLists; newActiveEditTier: number | null } {
  const tiers = lists.learn_skill_list.filter((_, i) => i !== idx)

  let newActiveEditTier: number | null = activeEditTier
  if (activeEditTier === idx) {
    newActiveEditTier = null
  } else if (typeof activeEditTier === 'number' && activeEditTier > idx) {
    newActiveEditTier = activeEditTier - 1
  }

  return { lists: { ...lists, learn_skill_list: tiers }, newActiveEditTier }
}

/**
 * addAllVisible — app.js:1790-1817 (ADD ALL VISIBLE)
 *
 * Add all visibleNames to the focused area (tier or blacklist).
 */
export function addAllVisible(
  lists: SkillLists,
  visibleNames: string[],
  activeEditTier: number | null,
  siblings?: Record<string, string[]>,
): SkillLists {
  let result = lists
  for (const name of visibleNames) {
    result = addSkillToFocus(result, name, activeEditTier, siblings)
  }
  return result
}

/**
 * removeAllVisible — app.js:1819-1845 (REMOVE ALL VISIBLE)
 *
 * Remove all visibleNames from the focused area (tier or blacklist).
 */
export function removeAllVisible(
  lists: SkillLists,
  visibleNames: string[],
  activeEditTier: number | null,
): SkillLists {
  // Exact visible names only — no group expansion (delete must never pull sibling
  // tiers; visible lower tiers are already in visibleNames if shown).
  const nameSet = new Set<string>(visibleNames)

  if (activeEditTier === null) {
    return {
      ...lists,
      learn_skill_blacklist: lists.learn_skill_blacklist.filter((s) => !nameSet.has(s)),
    }
  }

  const tiers = lists.learn_skill_list.map((tier, i) =>
    i === activeEditTier ? tier.filter((s) => !nameSet.has(s)) : tier,
  )
  return { ...lists, learn_skill_list: tiers }
}

/**
 * blacklistAllVisible — app.js:1847-1866 (BLACKLIST ALL VISIBLE)
 *
 * Add all visibleNames to the blacklist (regardless of focused area).
 */
export function blacklistAllVisible(
  lists: SkillLists,
  visibleNames: string[],
  siblings?: Record<string, string[]>,
): SkillLists {
  const existing = new Set(lists.learn_skill_blacklist)
  const toAdd: string[] = []
  for (const name of visibleNames) {
    for (const n of expandGroup(name, siblings)) {
      if (!existing.has(n) && !toAdd.includes(n)) toAdd.push(n)
    }
  }
  if (toAdd.length === 0) return lists
  return {
    ...lists,
    learn_skill_blacklist: [...lists.learn_skill_blacklist, ...toAdd],
  }
}

/**
 * clearBlacklist — app.js:1867-1874
 */
export function clearBlacklist(lists: SkillLists): SkillLists {
  return { ...lists, learn_skill_blacklist: [] }
}
