import { describe, it, expect } from 'vitest'
import {
  dedupeSkills,
  matchesFilters,
  isUniqueSkill,
  UNIQUE_RARITY_MIN,
  skillColorMatches,
  buildGroupSiblings,
  addSkillToFocus,
  deleteSkillFromTier,
  deleteSkillFromBlacklist,
  deleteTier,
  addAllVisible,
  removeAllVisible,
  blacklistAllVisible,
  clearBlacklist,
  COLOR_FILTERS,
  SKILL_FILTERS,
} from './skillEditorRules'
import type { DedupedSkill, SkillLists, ColorFilter } from './skillEditorRules'
import type { SkillEntry } from '@/api/types'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeLists(
  tiers: string[][] = [],
  blacklist: string[] = [],
): SkillLists {
  return { learn_skill_list: tiers, learn_skill_blacklist: blacklist }
}

// ---------------------------------------------------------------------------
// buildGroupSiblings + group-aware tier moves
// ---------------------------------------------------------------------------
describe('buildGroupSiblings', () => {
  // group 20033: white "Corner Adept ○" (r1) + gold "Professor of Curvature" (r2);
  // group 20154: 3 tiers; a unique (r3) must stay on its own.
  const record: Record<string, SkillEntry> = {
    '200332': { name: 'Corner Adept ○', rarity: 1, group_id: 20033 },
    '200331': { name: 'Professor of Curvature', rarity: 2, group_id: 20033 },
    '201542': { name: 'Late Surger Savvy ○', rarity: 1, group_id: 20154 },
    '201541': { name: 'Late Surger Savvy ◎', rarity: 1, group_id: 20154 },
    '201543': { name: 'Late Surger Master', rarity: 2, group_id: 20154 },
    '900001': { name: 'Red Ace', rarity: 3, group_id: 90000 },
  }

  it('maps every tier name to all names sharing its group; uniques stand alone', () => {
    const s = buildGroupSiblings(record)
    expect(new Set(s['Professor of Curvature'])).toEqual(
      new Set(['Corner Adept ○', 'Professor of Curvature']),
    )
    expect(new Set(s['Corner Adept ○'])).toEqual(
      new Set(['Corner Adept ○', 'Professor of Curvature']),
    )
    expect(new Set(s['Late Surger Savvy ◎'])).toEqual(
      new Set(['Late Surger Savvy ○', 'Late Surger Savvy ◎', 'Late Surger Master']),
    )
    expect(s['Red Ace']).toBeUndefined() // unique not grouped
  })

  it('adding a higher tier to a priority tier pulls every lower tier', () => {
    const s = buildGroupSiblings(record)
    const result = addSkillToFocus(makeLists([[]]), 'Professor of Curvature', 0, s)
    expect(new Set(result.learn_skill_list[0])).toEqual(
      new Set(['Corner Adept ○', 'Professor of Curvature']),
    )
  })

  it('adding any tier to the blacklist blacklists the whole group', () => {
    const s = buildGroupSiblings(record)
    const result = addSkillToFocus(makeLists(), 'Corner Adept ○', null, s)
    expect(new Set(result.learn_skill_blacklist)).toEqual(
      new Set(['Corner Adept ○', 'Professor of Curvature']),
    )
  })

  it('deleting from the blacklist removes ONLY the clicked name, keeping siblings', () => {
    const lists = makeLists([], ['Corner Adept ○', 'Professor of Curvature', 'Unrelated'])
    const result = deleteSkillFromBlacklist(lists, 'Professor of Curvature')
    // High tier removed, low tier (group sibling) stays put.
    expect(result.learn_skill_blacklist).toEqual(['Corner Adept ○', 'Unrelated'])
  })

  it('deleting from a tier removes ONLY the clicked name, keeping the low tier', () => {
    const lists = makeLists([['Corner Adept ○', 'Professor of Curvature', 'Keep']], [])
    const result = deleteSkillFromTier(lists, 0, 'Professor of Curvature')
    expect(result.learn_skill_list[0]).toEqual(['Corner Adept ○', 'Keep'])
  })

  it('without a siblings map, behaviour is unchanged (single skill only)', () => {
    const result = addSkillToFocus(makeLists(), 'Corner Adept ○', null)
    expect(result.learn_skill_blacklist).toEqual(['Corner Adept ○'])
  })
})

// ---------------------------------------------------------------------------
// dedupeSkills
// ---------------------------------------------------------------------------
describe('dedupeSkills', () => {
  it('two entries with same name → one entry, max rarity, unioned tags', () => {
    const record: Record<string, SkillEntry> = {
      '1': { name: 'Overdrive', rarity: 2, tags: [101, 201], icon_id: '1001001' },
      '2': { name: 'Overdrive', rarity: 3, tags: [201, 202], icon_id: '1001002' },
    }
    const result = dedupeSkills(record)
    expect(result).toHaveLength(1)
    expect(result[0].rarity).toBe(3)
    expect(result[0].tags).toEqual(expect.arrayContaining([101, 201, 202]))
    expect(result[0].tags).toHaveLength(3)
  })

  it('preserves first entry icon_id', () => {
    const record: Record<string, SkillEntry> = {
      '1': { name: 'A', rarity: 1, tags: [], icon_id: '1001001' },
      '2': { name: 'A', rarity: 2, tags: [], icon_id: '9999999' },
    }
    const result = dedupeSkills(record)
    expect(result[0].icon_id).toBe('1001001')
  })

  it('sorted by name.localeCompare', () => {
    const record: Record<string, SkillEntry> = {
      '1': { name: 'Zzz', rarity: 1, tags: [] },
      '2': { name: 'Aaa', rarity: 1, tags: [] },
      '3': { name: 'Mmm', rarity: 1, tags: [] },
    }
    const result = dedupeSkills(record)
    expect(result.map((s) => s.name)).toEqual(['Aaa', 'Mmm', 'Zzz'])
  })

  it('distinct names kept as separate entries', () => {
    const record: Record<string, SkillEntry> = {
      '1': { name: 'Speed Boost', rarity: 1, tags: [101] },
      '2': { name: 'Late Rush', rarity: 2, tags: [103] },
    }
    const result = dedupeSkills(record)
    expect(result).toHaveLength(2)
  })

  it('empty record → empty array', () => {
    expect(dedupeSkills({})).toEqual([])
  })

  it('handles missing tags and rarity gracefully', () => {
    const record: Record<string, SkillEntry> = {
      '1': { name: 'NoInfo' },
    }
    const result = dedupeSkills(record)
    expect(result).toHaveLength(1)
    expect(result[0].rarity).toBe(0)
    expect(result[0].tags).toEqual([])
  })
})

// ---------------------------------------------------------------------------
// skillColorMatches
// ---------------------------------------------------------------------------
describe('skillColorMatches', () => {
  const greenFilter: ColorFilter = COLOR_FILTERS.find((f) => f.id === 'green')!
  const yellowFilter: ColorFilter = COLOR_FILTERS.find((f) => f.id === 'yellow')!

  it('returns true when icon_id starts with a matching prefix', () => {
    expect(skillColorMatches('1001001', greenFilter)).toBe(true)
    expect(skillColorMatches('2001999', yellowFilter)).toBe(true)
  })

  it('returns false when icon_id does not match any prefix', () => {
    expect(skillColorMatches('9999999', greenFilter)).toBe(false)
    expect(skillColorMatches('2002001', yellowFilter)).toBe(false) // 2002 is blue
  })

  it('handles undefined icon_id → false', () => {
    expect(skillColorMatches(undefined, greenFilter)).toBe(false)
  })

  it('handles numeric icon_id', () => {
    expect(skillColorMatches(1001001, greenFilter)).toBe(true)
  })
})

// ---------------------------------------------------------------------------
// matchesFilters
// ---------------------------------------------------------------------------
describe('matchesFilters', () => {
  const baseSkill: DedupedSkill = {
    name: 'Sprint Burst',
    rarity: 2,
    tags: [101, 201],      // Front, Short
    icon_id: '1001001',    // green
  }

  it('null filters + empty query → always passes', () => {
    expect(matchesFilters(baseSkill, '', null, null)).toBe(true)
  })

  it('query match — case-insensitive', () => {
    expect(matchesFilters(baseSkill, 'sprint', null, null)).toBe(true)
    expect(matchesFilters(baseSkill, 'SPRINT', null, null)).toBe(true)
    expect(matchesFilters(baseSkill, 'xyz', null, null)).toBe(false)
  })

  it('numeric affinity filter — skill must include tag', () => {
    expect(matchesFilters(baseSkill, '', 101, null)).toBe(true)   // has Front
    expect(matchesFilters(baseSkill, '', 102, null)).toBe(false)  // no Pace
  })

  it("turf filter — skill must NOT include tag 502 (Dirt)", () => {
    const dirtSkill: DedupedSkill = { ...baseSkill, tags: [502] }
    const turfSkill: DedupedSkill = { ...baseSkill, tags: [101] }
    expect(matchesFilters(dirtSkill, '', 'turf', null)).toBe(false) // has Dirt → not turf
    expect(matchesFilters(turfSkill, '', 'turf', null)).toBe(true)  // no Dirt → turf
  })

  it('color filter — matches icon prefix', () => {
    const greenFilter = COLOR_FILTERS.find((f) => f.id === 'green')!
    const blueFilter = COLOR_FILTERS.find((f) => f.id === 'blue')!
    expect(matchesFilters(baseSkill, '', null, greenFilter)).toBe(true)   // icon starts 1001
    expect(matchesFilters(baseSkill, '', null, blueFilter)).toBe(false)   // icon doesn't start 2002
  })

  it('all filters combined — must satisfy all', () => {
    const greenFilter = COLOR_FILTERS.find((f) => f.id === 'green')!
    // query ✓, tag 101 ✓, green ✓
    expect(matchesFilters(baseSkill, 'sprint', 101, greenFilter)).toBe(true)
    // query ✓, tag 102 ✗
    expect(matchesFilters(baseSkill, 'sprint', 102, greenFilter)).toBe(false)
  })

  it('uniqueOnly defaults to false — non-unique skills still pass', () => {
    // baseSkill.rarity = 2 (rare, not unique); omitting the arg keeps it visible
    expect(matchesFilters(baseSkill, '', null, null)).toBe(true)
    expect(matchesFilters(baseSkill, '', null, null, false)).toBe(true)
  })

  it('uniqueOnly=true — hides non-unique (rarity < 3) skills', () => {
    const normal: DedupedSkill = { ...baseSkill, rarity: 1 }
    const rare: DedupedSkill = { ...baseSkill, rarity: 2 }
    expect(matchesFilters(normal, '', null, null, true)).toBe(false)
    expect(matchesFilters(rare, '', null, null, true)).toBe(false)
  })

  it('uniqueOnly=true — shows unique (rarity >= 3) skills', () => {
    for (const r of [3, 4, 5]) {
      const unique: DedupedSkill = { ...baseSkill, rarity: r }
      expect(matchesFilters(unique, '', null, null, true)).toBe(true)
    }
  })

  it('uniqueOnly combines with other filters (AND)', () => {
    const greenFilter = COLOR_FILTERS.find((f) => f.id === 'green')!
    const uniqueGreen: DedupedSkill = { ...baseSkill, rarity: 3 } // green icon, tag 101
    // unique ✓ + green ✓ + tag 101 ✓
    expect(matchesFilters(uniqueGreen, '', 101, greenFilter, true)).toBe(true)
    // unique ✓ but wrong affinity tag
    expect(matchesFilters(uniqueGreen, '', 102, greenFilter, true)).toBe(false)
  })
})

// ---------------------------------------------------------------------------
// isUniqueSkill
// ---------------------------------------------------------------------------
describe('isUniqueSkill', () => {
  const mk = (rarity: number): DedupedSkill => ({ name: 'x', rarity, tags: [] })

  it('UNIQUE_RARITY_MIN is 3', () => {
    expect(UNIQUE_RARITY_MIN).toBe(3)
  })

  it('rarity 1 and 2 are not unique', () => {
    expect(isUniqueSkill(mk(0))).toBe(false)
    expect(isUniqueSkill(mk(1))).toBe(false)
    expect(isUniqueSkill(mk(2))).toBe(false)
  })

  it('rarity 3, 4, 5 are unique', () => {
    expect(isUniqueSkill(mk(3))).toBe(true)
    expect(isUniqueSkill(mk(4))).toBe(true)
    expect(isUniqueSkill(mk(5))).toBe(true)
  })
})

// ---------------------------------------------------------------------------
// SKILL_FILTERS and COLOR_FILTERS constants
// ---------------------------------------------------------------------------
describe('filter constants', () => {
  it('SKILL_FILTERS has 10 entries with correct ids', () => {
    expect(SKILL_FILTERS).toHaveLength(10)
    const ids = SKILL_FILTERS.map((f) => f.id)
    expect(ids).toContain(101)
    expect(ids).toContain(502)
    expect(ids).toContain('turf')
  })

  it('COLOR_FILTERS has green, blue, yellow, red', () => {
    const ids = COLOR_FILTERS.map((f) => f.id)
    expect(ids).toContain('green')
    expect(ids).toContain('blue')
    expect(ids).toContain('yellow')
    expect(ids).toContain('red')
  })
})

// ---------------------------------------------------------------------------
// addSkillToFocus
// ---------------------------------------------------------------------------
describe('addSkillToFocus', () => {
  it('adds to tier when activeEditTier is a number', () => {
    const lists = makeLists([['Skill A']], [])
    const result = addSkillToFocus(lists, 'Skill B', 0)
    expect(result.learn_skill_list[0]).toEqual(['Skill A', 'Skill B'])
    expect(result.learn_skill_blacklist).toEqual([])
  })

  it('does not add duplicate to tier', () => {
    const lists = makeLists([['Skill A']], [])
    const result = addSkillToFocus(lists, 'Skill A', 0)
    expect(result.learn_skill_list[0]).toEqual(['Skill A'])
  })

  it('creates tier array if it does not exist yet', () => {
    const lists = makeLists([], [])
    const result = addSkillToFocus(lists, 'Skill A', 2) // tier index 2 on empty list
    expect(result.learn_skill_list[2]).toEqual(['Skill A'])
  })

  it('adds to blacklist when activeEditTier is null', () => {
    const lists = makeLists([['Skill A']], [])
    const result = addSkillToFocus(lists, 'Skill B', null)
    expect(result.learn_skill_blacklist).toEqual(['Skill B'])
    expect(result.learn_skill_list).toEqual([['Skill A']]) // unchanged
  })

  it('does not add duplicate to blacklist', () => {
    const lists = makeLists([], ['Skill A'])
    const result = addSkillToFocus(lists, 'Skill A', null)
    expect(result.learn_skill_blacklist).toEqual(['Skill A'])
  })
})

// ---------------------------------------------------------------------------
// deleteTier
// ---------------------------------------------------------------------------
describe('deleteTier', () => {
  const lists = makeLists([['S1'], ['S2'], ['S3']], [])

  it('deletes the correct tier', () => {
    const { lists: result } = deleteTier(lists, 1, 0)
    expect(result.learn_skill_list).toHaveLength(2)
    expect(result.learn_skill_list[0]).toEqual(['S1'])
    expect(result.learn_skill_list[1]).toEqual(['S3'])
  })

  it('resets activeEditTier to null when === idx', () => {
    const { newActiveEditTier } = deleteTier(lists, 1, 1)
    expect(newActiveEditTier).toBeNull()
  })

  it('decrements activeEditTier when > idx', () => {
    const { newActiveEditTier } = deleteTier(lists, 0, 2)
    expect(newActiveEditTier).toBe(1)
  })

  it('leaves activeEditTier unchanged when < idx', () => {
    const { newActiveEditTier } = deleteTier(lists, 2, 0)
    expect(newActiveEditTier).toBe(0)
  })

  it('leaves activeEditTier null unchanged', () => {
    const { newActiveEditTier } = deleteTier(lists, 1, null)
    expect(newActiveEditTier).toBeNull()
  })
})

// ---------------------------------------------------------------------------
// addAllVisible (ADD ALL VISIBLE)
// ---------------------------------------------------------------------------
describe('addAllVisible', () => {
  it('adds all visible names to the focused tier', () => {
    const lists = makeLists([['Existing']], [])
    const result = addAllVisible(lists, ['New A', 'New B'], 0)
    expect(result.learn_skill_list[0]).toEqual(['Existing', 'New A', 'New B'])
  })

  it('adds all visible names to blacklist when activeEditTier is null', () => {
    const lists = makeLists([], [])
    const result = addAllVisible(lists, ['A', 'B'], null)
    expect(result.learn_skill_blacklist).toEqual(['A', 'B'])
  })

  it('does not create duplicates', () => {
    const lists = makeLists([['A', 'B']], [])
    const result = addAllVisible(lists, ['A', 'C'], 0)
    expect(result.learn_skill_list[0]).toEqual(['A', 'B', 'C'])
  })
})

// ---------------------------------------------------------------------------
// removeAllVisible (REMOVE ALL VISIBLE)
// ---------------------------------------------------------------------------
describe('removeAllVisible', () => {
  it('removes visible names from focused tier', () => {
    const lists = makeLists([['A', 'B', 'C']], [])
    const result = removeAllVisible(lists, ['A', 'C'], 0)
    expect(result.learn_skill_list[0]).toEqual(['B'])
  })

  it('removes visible names from blacklist when activeEditTier is null', () => {
    const lists = makeLists([], ['A', 'B', 'C'])
    const result = removeAllVisible(lists, ['A', 'C'], null)
    expect(result.learn_skill_blacklist).toEqual(['B'])
  })

  it('does nothing when no visible names match', () => {
    const lists = makeLists([['A', 'B']], [])
    const result = removeAllVisible(lists, ['X', 'Y'], 0)
    expect(result.learn_skill_list[0]).toEqual(['A', 'B'])
  })
})

// ---------------------------------------------------------------------------
// blacklistAllVisible (BLACKLIST ALL VISIBLE)
// ---------------------------------------------------------------------------
describe('blacklistAllVisible', () => {
  it('adds visible names to blacklist', () => {
    const lists = makeLists([], [])
    const result = blacklistAllVisible(lists, ['A', 'B'])
    expect(result.learn_skill_blacklist).toEqual(['A', 'B'])
  })

  it('does not add duplicates already in blacklist', () => {
    const lists = makeLists([], ['A'])
    const result = blacklistAllVisible(lists, ['A', 'B'])
    expect(result.learn_skill_blacklist).toEqual(['A', 'B'])
  })

  it('returns same reference when nothing new to add', () => {
    const lists = makeLists([], ['A', 'B'])
    const result = blacklistAllVisible(lists, ['A', 'B'])
    expect(result).toBe(lists) // same reference — nothing changed
  })

  it('does not modify learn_skill_list', () => {
    const lists = makeLists([['X']], [])
    const result = blacklistAllVisible(lists, ['Y'])
    expect(result.learn_skill_list).toEqual([['X']])
  })
})

// ---------------------------------------------------------------------------
// clearBlacklist
// ---------------------------------------------------------------------------
describe('clearBlacklist', () => {
  it('empties the blacklist', () => {
    const lists = makeLists([], ['A', 'B', 'C'])
    const result = clearBlacklist(lists)
    expect(result.learn_skill_blacklist).toEqual([])
  })

  it('does not modify learn_skill_list', () => {
    const lists = makeLists([['X', 'Y']], ['A'])
    const result = clearBlacklist(lists)
    expect(result.learn_skill_list).toEqual([['X', 'Y']])
  })
})
