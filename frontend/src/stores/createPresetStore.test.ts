/**
 * createPresetStore — the invariants the shared factory could plausibly break.
 *
 * presets.test.ts and racePresets.test.ts already pin each store's own
 * behaviour end-to-end and stay the real safety net. This file only covers what
 * became newly possible once both stores were built from one factory:
 *
 *   * two stores built from one factory must not share state or a key;
 *   * actions must keep stable identities (components pass them as props);
 *   * accountKey() must still be resolved per call, not captured at module load;
 *   * the race template must stay name + races (no scenario — see 535e1e2).
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'

// ---------------------------------------------------------------------------
// Mock the API layer so no real HTTP calls are made
// ---------------------------------------------------------------------------
vi.mock('@/api/presets', () => ({
  getPresets: vi.fn(),
  savePreset: vi.fn(),
  deletePreset: vi.fn(),
  getRacePresets: vi.fn(),
  saveRacePreset: vi.fn(),
  deleteRacePreset: vi.fn(),
  saveRacesToRacePreset: vi.fn(),
}))

import { getPresets, getRacePresets, saveRacePreset } from '@/api/presets'
import { usePresets } from './presets'
import { useRacePresets } from './racePresets'
import { useAccountStore } from './account'
import type { Preset, RacePreset } from '@/api/types'

const mockGetPresets = vi.mocked(getPresets)
const mockGetRacePresets = vi.mocked(getRacePresets)
const mockSaveRacePreset = vi.mocked(saveRacePreset)

const SKILL_A: Preset = {
  name: 'Alpha',
  running_style: 1,
  learn_skill_list: [],
  learn_skill_blacklist: [],
  extra_race_list: [],
  learn_skill_threshold: 888,
}
const RACE_A: RacePreset = { name: 'Races', extra_race_list: [1, 2] }

beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
  useAccountStore.setState({ selected: '' })
  usePresets.setState({ presets: [], selectedName: '' })
  useRacePresets.setState({ presets: [], selectedName: '' })
})

// ---------------------------------------------------------------------------
// Store isolation
// ---------------------------------------------------------------------------
describe('createPresetSlice — the two stores stay independent', () => {
  it('does not share state between the skill and race stores', async () => {
    mockGetPresets.mockResolvedValueOnce({ success: true, presets: [SKILL_A] })

    await usePresets.getState().load()

    expect(usePresets.getState().selectedName).toBe('Alpha')
    // The race store must be untouched by the skill store's load
    expect(useRacePresets.getState().presets).toHaveLength(0)
    expect(useRacePresets.getState().selectedName).toBe('')
  })

  it('writes only its own localStorage key on load', async () => {
    mockGetPresets.mockResolvedValueOnce({ success: true, presets: [SKILL_A] })

    await usePresets.getState().load()

    expect(localStorage.getItem('uma_selected_preset__default')).toBe('Alpha')
    expect(localStorage.getItem('uma_selected_race_preset__default')).toBeNull()
  })

  it('calls only its own API module', async () => {
    mockGetRacePresets.mockResolvedValueOnce({ success: true, presets: [RACE_A] })

    await useRacePresets.getState().load()

    expect(mockGetRacePresets).toHaveBeenCalledTimes(1)
    expect(mockGetPresets).not.toHaveBeenCalled()
  })
})

// ---------------------------------------------------------------------------
// Action identity — DeletePresetDialog / NewPresetDialog take these as props
// ---------------------------------------------------------------------------
describe('createPresetSlice — action identity is stable', () => {
  it('keeps the same action references across state updates (skill store)', async () => {
    const before = usePresets.getState()
    mockGetPresets.mockResolvedValueOnce({ success: true, presets: [SKILL_A] })

    await usePresets.getState().load()
    usePresets.getState().select('Alpha')

    const after = usePresets.getState()
    expect(after.load).toBe(before.load)
    expect(after.select).toBe(before.select)
    expect(after.create).toBe(before.create)
    expect(after.remove).toBe(before.remove)
    expect(after.update).toBe(before.update)
    expect(after.getActive).toBe(before.getActive)
  })

  it('keeps the same action references across state updates (race store)', async () => {
    const before = useRacePresets.getState()
    mockGetRacePresets.mockResolvedValueOnce({ success: true, presets: [RACE_A] })

    await useRacePresets.getState().load()

    const after = useRacePresets.getState()
    expect(after.load).toBe(before.load)
    expect(after.select).toBe(before.select)
    expect(after.create).toBe(before.create)
    expect(after.remove).toBe(before.remove)
    expect(after.update).toBe(before.update)
    expect(after.getActive).toBe(before.getActive)
    expect(after.saveRaces).toBe(before.saveRaces)
  })

  it('gives the two stores DIFFERENT action instances', () => {
    expect(useRacePresets.getState().load).not.toBe(usePresets.getState().load)
  })
})

// ---------------------------------------------------------------------------
// accountKey() must still be resolved per call
// ---------------------------------------------------------------------------
describe('createPresetSlice — localStorage key is account-scoped per call', () => {
  it('follows the selected account across a switch', () => {
    useAccountStore.setState({ selected: 'lewpie' })
    usePresets.getState().select('Alpha')
    expect(localStorage.getItem('uma_selected_preset__lewpie')).toBe('Alpha')

    useAccountStore.setState({ selected: 'yuko' })
    usePresets.getState().select('Beta')

    expect(localStorage.getItem('uma_selected_preset__yuko')).toBe('Beta')
    // The previous account's saved choice survives untouched
    expect(localStorage.getItem('uma_selected_preset__lewpie')).toBe('Alpha')
  })
})

// ---------------------------------------------------------------------------
// Templates — the two stores POST genuinely different objects
// ---------------------------------------------------------------------------
describe('createPresetSlice — per-store new-preset template', () => {
  it('POSTs name + extra_race_list ONLY for a new race preset (no scenario)', async () => {
    mockSaveRacePreset.mockResolvedValueOnce({
      success: true,
      preset: { name: 'Gamma', extra_race_list: [] },
    })
    mockGetRacePresets.mockResolvedValue({ success: true, presets: [] })

    await useRacePresets.getState().create('Gamma')

    const [body] = mockSaveRacePreset.mock.calls[0]
    expect(Object.keys(body.preset).sort()).toEqual(['extra_race_list', 'name'])
    expect(body.preset).not.toHaveProperty('scenario')
    expect(body.preset).not.toHaveProperty('scenario_id')
  })
})
