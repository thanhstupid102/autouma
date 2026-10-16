import { describe, it, expect } from 'vitest'
import { deriveActionHistory, normalizeHistoryAction } from './actionHistory'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
type LogItem = { action: string; turn?: number; detail?: string }

function log(...items: LogItem[]) {
  return items
}

// ---------------------------------------------------------------------------
// deriveActionHistory — filtering
// ---------------------------------------------------------------------------
describe('deriveActionHistory — filtering', () => {
  it('includes command, race, race_progress, finish, api_delay, turn_delay, complex_delay', () => {
    const items = log(
      { action: 'command', turn: 1, detail: 'training speed' },
      { action: 'race', turn: 2 },
      { action: 'race_progress', turn: 3 },
      { action: 'finish', turn: 4 },
      { action: 'api_delay', turn: 5 },
      { action: 'turn_delay', turn: 6 },
      { action: 'complex_delay', turn: 7 },
    )
    expect(deriveActionHistory(items)).toHaveLength(7)
  })

  it('filters out actions not in the allowed set', () => {
    const items = log(
      { action: 'unknown_action', turn: 1 },
      { action: 'skill', turn: 2 },
      { action: 'event', turn: 3 },
      { action: 'command', turn: 4, detail: 'training speed' },
    )
    const result = deriveActionHistory(items)
    expect(result).toHaveLength(1)
    expect(result[0].action).toBe('train')
  })
})

// ---------------------------------------------------------------------------
// deriveActionHistory — command branch: training
// ---------------------------------------------------------------------------
describe('deriveActionHistory — training branch', () => {
  it('maps "training speed" → action=train, facility="speed"', () => {
    const result = deriveActionHistory(log({ action: 'command', turn: 10, detail: 'training speed' }))
    expect(result[0]).toMatchObject({ turn: 10, action: 'train', facility: 'speed', detail: 'training speed' })
  })

  it('maps "training stamina" → action=train, facility="stamina"', () => {
    const result = deriveActionHistory(log({ action: 'command', turn: 5, detail: 'training stamina' }))
    expect(result[0]).toMatchObject({ action: 'train', facility: 'stamina' })
  })
})

// ---------------------------------------------------------------------------
// deriveActionHistory — command branch: rest
// ---------------------------------------------------------------------------
describe('deriveActionHistory — rest branch', () => {
  it('maps "rest 401" → action=rest, facility="401"', () => {
    const result = deriveActionHistory(log({ action: 'command', turn: 2, detail: 'rest 401' }))
    expect(result[0]).toMatchObject({ action: 'rest', facility: '401' })
  })

  it('maps "rest 301" → action=recreation (facility in recreation set)', () => {
    const result = deriveActionHistory(log({ action: 'command', turn: 3, detail: 'rest 301' }))
    expect(result[0]).toMatchObject({ action: 'recreation', facility: '301' })
  })

  it('maps "rest 302" → action=recreation', () => {
    const result = deriveActionHistory(log({ action: 'command', turn: 3, detail: 'rest 302' }))
    expect(result[0]).toMatchObject({ action: 'recreation', facility: '302' })
  })

  it('maps "rest 303" → action=recreation', () => {
    const result = deriveActionHistory(log({ action: 'command', turn: 4, detail: 'rest 303' }))
    expect(result[0]).toMatchObject({ action: 'recreation', facility: '303' })
  })

  it('maps "rest 304" → action=recreation', () => {
    const result = deriveActionHistory(log({ action: 'command', turn: 4, detail: 'rest 304' }))
    expect(result[0]).toMatchObject({ action: 'recreation', facility: '304' })
  })

  it('maps "rest 305" → action=recreation', () => {
    const result = deriveActionHistory(log({ action: 'command', turn: 4, detail: 'rest 305' }))
    expect(result[0]).toMatchObject({ action: 'recreation', facility: '305' })
  })

  it('maps "rest 390" → action=recreation', () => {
    const result = deriveActionHistory(log({ action: 'command', turn: 5, detail: 'rest 390' }))
    expect(result[0]).toMatchObject({ action: 'recreation', facility: '390' })
  })
})

// ---------------------------------------------------------------------------
// deriveActionHistory — command branch: challenge
// ---------------------------------------------------------------------------
describe('deriveActionHistory — challenge branch', () => {
  it('maps "challenge 100" → action=rest, facility="100"', () => {
    const result = deriveActionHistory(log({ action: 'command', turn: 6, detail: 'challenge 100' }))
    expect(result[0]).toMatchObject({ action: 'rest', facility: '100' })
  })

  it('maps "challenge xyz" → action=rest', () => {
    const result = deriveActionHistory(log({ action: 'command', turn: 7, detail: 'challenge xyz' }))
    expect(result[0]).toMatchObject({ action: 'rest', facility: 'xyz' })
  })
})

// ---------------------------------------------------------------------------
// deriveActionHistory — command branch: recreation
// ---------------------------------------------------------------------------
describe('deriveActionHistory — recreation branch', () => {
  it('maps "recreation summer" → action=recreation, facility="summer"', () => {
    const result = deriveActionHistory(log({ action: 'command', turn: 8, detail: 'recreation summer' }))
    expect(result[0]).toMatchObject({ action: 'recreation', facility: 'summer' })
  })
})

// ---------------------------------------------------------------------------
// deriveActionHistory — command branch: medic (command 8:)
// ---------------------------------------------------------------------------
describe('deriveActionHistory — medic branch', () => {
  it('maps "command 8:0" → action=medic, facility="" (empty)', () => {
    const result = deriveActionHistory(log({ action: 'command', turn: 9, detail: 'command 8:0' }))
    expect(result[0]).toMatchObject({ action: 'medic', facility: '' })
  })

  it('maps "command 8:something" → action=medic', () => {
    const result = deriveActionHistory(log({ action: 'command', turn: 10, detail: 'command 8:something' }))
    expect(result[0]).toMatchObject({ action: 'medic' })
  })
})

// ---------------------------------------------------------------------------
// deriveActionHistory — race_progress → race
// ---------------------------------------------------------------------------
describe('deriveActionHistory — race_progress branch', () => {
  it('maps race_progress → action=race', () => {
    const result = deriveActionHistory(log({ action: 'race_progress', turn: 11 }))
    expect(result[0]).toMatchObject({ action: 'race' })
  })
})

// ---------------------------------------------------------------------------
// deriveActionHistory — pass-through actions (race, finish, api_delay, etc.)
// ---------------------------------------------------------------------------
describe('deriveActionHistory — pass-through actions', () => {
  it('keeps finish row with action=finish', () => {
    const result = deriveActionHistory(log({ action: 'finish', turn: 20 }))
    expect(result[0]).toMatchObject({ action: 'finish', facility: '', detail: '' })
  })

  it('keeps api_delay row with action=api_delay', () => {
    const result = deriveActionHistory(log({ action: 'api_delay', turn: 21 }))
    expect(result[0]).toMatchObject({ action: 'api_delay' })
  })

  it('keeps turn_delay row with action=turn_delay', () => {
    const result = deriveActionHistory(log({ action: 'turn_delay', turn: 22 }))
    expect(result[0]).toMatchObject({ action: 'turn_delay' })
  })

  it('keeps complex_delay row with action=complex_delay', () => {
    const result = deriveActionHistory(log({ action: 'complex_delay', turn: 23 }))
    expect(result[0]).toMatchObject({ action: 'complex_delay' })
  })

  it('keeps race row with action=race', () => {
    const result = deriveActionHistory(log({ action: 'race', turn: 24 }))
    expect(result[0]).toMatchObject({ action: 'race' })
  })
})

// ---------------------------------------------------------------------------
// deriveActionHistory — undefined/missing detail
// ---------------------------------------------------------------------------
describe('deriveActionHistory — missing detail handling', () => {
  it('treats missing detail as empty string for command with no matching prefix', () => {
    const result = deriveActionHistory(log({ action: 'command', turn: 30 }))
    // No prefix matched → action stays 'command' as-is (legacy behavior)
    expect(result[0]).toMatchObject({ action: 'command', facility: '', detail: '' })
  })
})

// ---------------------------------------------------------------------------
// normalizeHistoryAction
// ---------------------------------------------------------------------------
describe('normalizeHistoryAction', () => {
  it('returns row unchanged when action is not "rest"', () => {
    const row = { turn: 1, action: 'train', facility: '303', detail: 'training speed' }
    expect(normalizeHistoryAction(row)).toEqual(row)
  })

  it('returns row unchanged when action is "rest" and facility is NOT in recreation set', () => {
    const row = { turn: 2, action: 'rest', facility: '401', detail: 'rest 401' }
    expect(normalizeHistoryAction(row)).toEqual(row)
  })

  it('converts rest+301 → recreation', () => {
    const row = { turn: 3, action: 'rest', facility: '301', detail: 'rest 301' }
    expect(normalizeHistoryAction(row)).toMatchObject({ action: 'recreation', facility: '301' })
  })

  it('converts rest+302 → recreation', () => {
    const row = { turn: 3, action: 'rest', facility: '302', detail: 'rest 302' }
    expect(normalizeHistoryAction(row)).toMatchObject({ action: 'recreation' })
  })

  it('converts rest+303 → recreation', () => {
    const row = { turn: 3, action: 'rest', facility: '303', detail: 'rest 303' }
    expect(normalizeHistoryAction(row)).toMatchObject({ action: 'recreation' })
  })

  it('converts rest+304 → recreation', () => {
    const row = { turn: 3, action: 'rest', facility: '304', detail: 'rest 304' }
    expect(normalizeHistoryAction(row)).toMatchObject({ action: 'recreation' })
  })

  it('converts rest+305 → recreation', () => {
    const row = { turn: 3, action: 'rest', facility: '305', detail: 'rest 305' }
    expect(normalizeHistoryAction(row)).toMatchObject({ action: 'recreation' })
  })

  it('converts rest+390 → recreation', () => {
    const row = { turn: 4, action: 'rest', facility: '390', detail: 'rest 390' }
    expect(normalizeHistoryAction(row)).toMatchObject({ action: 'recreation', facility: '390' })
  })

  it('does not mutate original row, returns new object', () => {
    const row = { turn: 5, action: 'rest', facility: '303', detail: 'rest 303' }
    const result = normalizeHistoryAction(row)
    expect(result).not.toBe(row)
    expect(row.action).toBe('rest') // original unchanged
  })
})
