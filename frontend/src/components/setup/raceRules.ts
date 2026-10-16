/**
 * raceRules.ts — pure race-schedule logic (no React, no state).
 *
 * Ported from app.js:1171-1319.
 * All functions are pure and unit-tested in raceRules.test.ts.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface Race {
  id: number | string
  name: string
  date: string
  type: string
  terrain: string
  distance: number | string
  legacy_ids?: (number | string)[]
}

export interface Slot {
  label: string   // e.g. "Early Jan"
  period: string  // e.g. "Early"
  month: string   // e.g. "Jan"
  races: Race[]
  yearIdx: number
}

export type ScenarioType = 'Mant' | string

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const YEAR_LABELS = ['Junior Year', 'Classic Year', 'Senior Year'] as const
export const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'] as const
export const PERIODS = ['Early', 'Late'] as const

// ---------------------------------------------------------------------------
// raceKeys — app.js:1196-1199
// Returns all numeric ids for a race (id + legacy_ids), drops non-finite.
// ---------------------------------------------------------------------------
export function raceKeys(race: Race): number[] {
  const keys: (number | string)[] = [race.id, ...(race.legacy_ids ?? [])]
  return keys
    .map((id) => parseInt(String(id), 10))
    .filter((id) => Number.isFinite(id))
}

// ---------------------------------------------------------------------------
// raceSelected — app.js:1201-1203
// True if any of the race's keys are in selectedRaces.
// ---------------------------------------------------------------------------
export function raceSelected(race: Race, selectedRaces: number[]): boolean {
  return raceKeys(race).some((id) => selectedRaces.includes(id))
}

// ---------------------------------------------------------------------------
// getYearSlots — app.js:1180-1194
// Returns 24 slots for one year (12 months × 2 periods).
// Slot order: Early Jan, Late Jan, Early Feb, Late Feb, …
// ---------------------------------------------------------------------------
export function getYearSlots(yearIdx: number, raceData: Race[]): Slot[] {
  const yearLabel = YEAR_LABELS[yearIdx]
  const slots: Slot[] = []
  for (const month of MONTHS) {
    for (const period of PERIODS) {
      const label = `${period} ${month}`
      const datePrefix = `${yearLabel} ${label}`
      const races = raceData.filter((r) => r.date.includes(datePrefix))
      slots.push({ label, period, month, races, yearIdx })
    }
  }
  return slots
}

// ---------------------------------------------------------------------------
// raceBadge — app.js:1272-1277
// Returns the badge text for a race row in the picker.
//   selIndex === -1    → not selected → "✓" (un-selected state shown differently)
//   selIndex === 0     → MAIN (Mant)
//   selIndex > 0       → RIVAL OVERWRITE {selIndex} (Mant)
// For non-Mant: just "✓" when selected.
// ---------------------------------------------------------------------------
export function raceBadge(
  selIndex: number,
  selectedInSlotLength: number,
  scenario: ScenarioType,
): string {
  if (selIndex === -1) return '✓'
  if (scenario === 'Mant' && selectedInSlotLength > 0) {
    if (selIndex === 0) return 'MAIN'
    return `RIVAL OVERWRITE ${selIndex}`
  }
  return '✓'
}

// ---------------------------------------------------------------------------
// toggleRaceInSlot — app.js:1298-1313
// Pure toggle: returns new selectedRaces array.
//   isSelected  → remove this race's keys from selectedRaces
//   !isSelected, Mant  → push race.id (keep other slot selections)
//   !isSelected, other → clear slotIds first, then push race.id
// ---------------------------------------------------------------------------
export function toggleRaceInSlot(
  selectedRaces: number[],
  race: Race,
  slotIds: number[],
  scenario: ScenarioType,
): number[] {
  const myIds = raceKeys(race)
  const isSelected = myIds.some((id) => selectedRaces.includes(id))

  if (isSelected) {
    return selectedRaces.filter((id) => !myIds.includes(id))
  }

  if (scenario !== 'Mant') {
    // Non-MANT: clear all slot selections first
    const cleared = selectedRaces.filter((id) => !slotIds.includes(id))
    return [...cleared, parseInt(String(race.id), 10)]
  }

  // MANT: just push, keep others
  return [...selectedRaces, parseInt(String(race.id), 10)]
}

// ---------------------------------------------------------------------------
// syncFromPreset — app.js:1171-1178
// Maps extra_race_list to a clean number[] (drops non-finite).
// ---------------------------------------------------------------------------
export function syncFromPreset(extraRaceList: (number | string)[] | undefined): number[] {
  return (extraRaceList ?? [])
    .map((id) => parseInt(String(id), 10))
    .filter((id) => Number.isFinite(id))
}
