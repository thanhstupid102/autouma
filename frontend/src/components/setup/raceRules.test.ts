import { describe, it, expect } from 'vitest'
import {
  raceKeys,
  raceSelected,
  getYearSlots,
  toggleRaceInSlot,
  raceBadge,
  syncFromPreset,
  YEAR_LABELS,
} from './raceRules'
import type { Race } from './raceRules'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeRace(overrides: Partial<Race> = {}): Race {
  return {
    id: 1,
    name: 'Test Race',
    date: 'Junior Year Early Jan',
    type: 'G1',
    terrain: 'Turf',
    distance: 1600,
    ...overrides,
  }
}

// ---------------------------------------------------------------------------
// raceKeys
// ---------------------------------------------------------------------------

describe('raceKeys', () => {
  it('returns [id] when no legacy_ids', () => {
    const race = makeRace({ id: 42 })
    expect(raceKeys(race)).toEqual([42])
  })

  it('includes legacy_ids as ints', () => {
    const race = makeRace({ id: 10, legacy_ids: [20, '30'] })
    expect(raceKeys(race)).toEqual([10, 20, 30])
  })

  it('drops non-finite values (NaN, Infinity)', () => {
    const race = makeRace({ id: 'bad', legacy_ids: [NaN, Infinity, 5] })
    expect(raceKeys(race)).toEqual([5])
  })

  it('parses string ids', () => {
    const race = makeRace({ id: '99', legacy_ids: ['100'] })
    expect(raceKeys(race)).toEqual([99, 100])
  })

  it('drops non-numeric strings', () => {
    const race = makeRace({ id: 1, legacy_ids: ['abc', 2] })
    expect(raceKeys(race)).toEqual([1, 2])
  })
})

// ---------------------------------------------------------------------------
// raceSelected
// ---------------------------------------------------------------------------

describe('raceSelected', () => {
  it('returns true when race id is in selectedRaces', () => {
    const race = makeRace({ id: 5 })
    expect(raceSelected(race, [5, 10])).toBe(true)
  })

  it('returns true when a legacy_id is in selectedRaces', () => {
    const race = makeRace({ id: 5, legacy_ids: [99] })
    expect(raceSelected(race, [99])).toBe(true)
  })

  it('returns false when no key matches', () => {
    const race = makeRace({ id: 5 })
    expect(raceSelected(race, [10, 20])).toBe(false)
  })

  it('returns false on empty selectedRaces', () => {
    const race = makeRace({ id: 1 })
    expect(raceSelected(race, [])).toBe(false)
  })
})

// ---------------------------------------------------------------------------
// getYearSlots / slot filtering
// ---------------------------------------------------------------------------

describe('getYearSlots', () => {
  it('returns 24 slots for each year', () => {
    expect(getYearSlots(0, [])).toHaveLength(24)
    expect(getYearSlots(1, [])).toHaveLength(24)
    expect(getYearSlots(2, [])).toHaveLength(24)
  })

  it('first slot is "Early Jan"', () => {
    const slots = getYearSlots(0, [])
    expect(slots[0].label).toBe('Early Jan')
    expect(slots[0].period).toBe('Early')
    expect(slots[0].month).toBe('Jan')
  })

  it('second slot is "Late Jan"', () => {
    const slots = getYearSlots(0, [])
    expect(slots[1].label).toBe('Late Jan')
  })

  it('last slot is "Late Dec"', () => {
    const slots = getYearSlots(0, [])
    expect(slots[23].label).toBe('Late Dec')
  })

  it('places a race with date "Classic Year Early Apr" in Classic Year slot 6', () => {
    // yearIdx=1 (Classic Year), month order: Jan,Feb,Mar,Apr → index 3, period Early → slot index 6
    const race = makeRace({ date: 'Classic Year Early Apr', id: 7 })
    const slots = getYearSlots(1, [race])

    // Early Apr in Classic Year → month index 3, period Early → slot 3*2+0 = 6
    const earlyAprSlot = slots.find((s) => s.label === 'Early Apr')
    expect(earlyAprSlot).toBeDefined()
    expect(earlyAprSlot!.races).toContain(race)
  })

  it('does NOT place the race in a different year slot', () => {
    const race = makeRace({ date: 'Classic Year Early Apr', id: 7 })
    const slots = getYearSlots(0, [race]) // Junior Year — should not match
    const earlyAprSlot = slots.find((s) => s.label === 'Early Apr')
    expect(earlyAprSlot!.races).toHaveLength(0)
  })

  it('does NOT place the race in Late Apr', () => {
    const race = makeRace({ date: 'Classic Year Early Apr', id: 7 })
    const slots = getYearSlots(1, [race])
    const lateAprSlot = slots.find((s) => s.label === 'Late Apr')
    expect(lateAprSlot!.races).toHaveLength(0)
  })

  it('yearIdx corresponds to the correct YEAR_LABELS entry', () => {
    const raceJunior = makeRace({ date: 'Junior Year Late Jun', id: 1 })
    const raceSenior = makeRace({ date: 'Senior Year Early Mar', id: 2 })

    const juniorSlots = getYearSlots(0, [raceJunior, raceSenior])
    const seniorSlots = getYearSlots(2, [raceJunior, raceSenior])

    expect(juniorSlots.find((s) => s.label === 'Late Jun')!.races).toContain(raceJunior)
    expect(juniorSlots.find((s) => s.label === 'Late Jun')!.races).not.toContain(raceSenior)
    expect(seniorSlots.find((s) => s.label === 'Early Mar')!.races).toContain(raceSenior)
  })
})

// ---------------------------------------------------------------------------
// toggleRaceInSlot
// ---------------------------------------------------------------------------

describe('toggleRaceInSlot', () => {
  const race = makeRace({ id: 10, legacy_ids: [11] })
  const slotIds = [10, 11, 20, 21]

  describe('MANT add (not currently selected)', () => {
    it('pushes race.id without clearing other slot selections', () => {
      const before = [20]
      const after = toggleRaceInSlot(before, race, slotIds, 'Mant')
      expect(after).toContain(20)
      expect(after).toContain(10)
    })

    it('does not duplicate if called twice', () => {
      // Second call: race is now selected — removes it
      const after1 = toggleRaceInSlot([], race, slotIds, 'Mant')
      const after2 = toggleRaceInSlot(after1, race, slotIds, 'Mant')
      expect(after2).not.toContain(10)
    })
  })

  describe('MANT remove (currently selected)', () => {
    it('removes race.id and all legacy_ids', () => {
      const before = [10, 11, 20]
      const after = toggleRaceInSlot(before, race, slotIds, 'Mant')
      expect(after).not.toContain(10)
      expect(after).not.toContain(11)
      expect(after).toContain(20) // other slot race untouched
    })

    it('removes by legacy_id match too', () => {
      const before = [11, 30] // only legacy_id present
      const after = toggleRaceInSlot(before, race, slotIds, 'Mant')
      expect(after).not.toContain(11)
      expect(after).toContain(30)
    })
  })

  describe('non-MANT add', () => {
    it('clears all slotIds before adding', () => {
      const before = [20, 21, 99]
      const after = toggleRaceInSlot(before, race, slotIds, 'Other')
      expect(after).not.toContain(20)
      expect(after).not.toContain(21)
      expect(after).toContain(99) // outside slot — kept
      expect(after).toContain(10)
    })
  })
})

// ---------------------------------------------------------------------------
// raceBadge
// ---------------------------------------------------------------------------

describe('raceBadge', () => {
  it('returns "✓" when selIndex is -1 (not selected)', () => {
    expect(raceBadge(-1, 0, 'Mant')).toBe('✓')
  })

  it('returns "MAIN" for selIndex 0 in Mant scenario', () => {
    expect(raceBadge(0, 1, 'Mant')).toBe('MAIN')
  })

  it('returns "RIVAL OVERWRITE 1" for selIndex 1 in Mant', () => {
    expect(raceBadge(1, 2, 'Mant')).toBe('RIVAL OVERWRITE 1')
  })

  it('returns "RIVAL OVERWRITE 2" for selIndex 2 in Mant', () => {
    expect(raceBadge(2, 3, 'Mant')).toBe('RIVAL OVERWRITE 2')
  })

  it('returns "✓" in non-Mant scenario when selected', () => {
    expect(raceBadge(0, 1, 'Other')).toBe('✓')
  })
})

// ---------------------------------------------------------------------------
// syncFromPreset
// ---------------------------------------------------------------------------

describe('syncFromPreset', () => {
  it('converts string ids to ints', () => {
    expect(syncFromPreset(['1', '2', '3'])).toEqual([1, 2, 3])
  })

  it('drops non-finite entries', () => {
    expect(syncFromPreset(['abc', NaN, undefined as unknown as number, 5])).toEqual([5])
  })

  it('returns [] for undefined', () => {
    expect(syncFromPreset(undefined)).toEqual([])
  })

  it('handles mixed number/string array', () => {
    expect(syncFromPreset([1, '2', 3])).toEqual([1, 2, 3])
  })
})

// ---------------------------------------------------------------------------
// YEAR_LABELS export
// ---------------------------------------------------------------------------

describe('YEAR_LABELS', () => {
  it('has 3 entries', () => {
    expect(YEAR_LABELS).toHaveLength(3)
  })

  it('entries are Junior, Classic, Senior', () => {
    expect(YEAR_LABELS[0]).toBe('Junior Year')
    expect(YEAR_LABELS[1]).toBe('Classic Year')
    expect(YEAR_LABELS[2]).toBe('Senior Year')
  })
})
