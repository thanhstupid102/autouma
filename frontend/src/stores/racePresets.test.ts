import { describe, it, expect, vi, beforeEach } from 'vitest'
import { useRacePresets } from './racePresets'
import type { RacePreset } from '@/api/types'

// ---------------------------------------------------------------------------
// Mock the API layer so no real HTTP calls are made
// ---------------------------------------------------------------------------
vi.mock('@/api/presets', () => ({
  getRacePresets: vi.fn(),
  saveRacePreset: vi.fn(),
  deleteRacePreset: vi.fn(),
  // keep existing fns so other imports from the same module don't break
  getPresets: vi.fn(),
  savePreset: vi.fn(),
  deletePreset: vi.fn(),
  saveRacesToRacePreset: vi.fn(),
}))

import { getRacePresets, saveRacePreset, deleteRacePreset } from '@/api/presets'

const mockGetRacePresets = vi.mocked(getRacePresets)
const mockSaveRacePreset = vi.mocked(saveRacePreset)
const mockDeleteRacePreset = vi.mocked(deleteRacePreset)

// ---------------------------------------------------------------------------
// Fixture presets
// ---------------------------------------------------------------------------
const PRESET_A: RacePreset = { name: 'Alpha', extra_race_list: [1, 2, 3] }
const PRESET_B: RacePreset = { name: 'Beta', extra_race_list: [4, 5] }

// ---------------------------------------------------------------------------
// Reset state before each test
// ---------------------------------------------------------------------------
beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
  useRacePresets.setState({ presets: [], selectedName: '' })
})

// ---------------------------------------------------------------------------
// load()
// ---------------------------------------------------------------------------
describe('racePresets store — load()', () => {
  it('sets list and selects first preset when no localStorage key', async () => {
    mockGetRacePresets.mockResolvedValueOnce({ success: true, presets: [PRESET_A, PRESET_B] })

    await useRacePresets.getState().load()

    const s = useRacePresets.getState()
    expect(s.presets).toHaveLength(2)
    expect(s.selectedName).toBe('Alpha')
    expect(localStorage.getItem('uma_selected_race_preset__default')).toBe('Alpha')
  })

  it('honours localStorage key when it matches a preset', async () => {
    localStorage.setItem('uma_selected_race_preset__default', 'Beta')
    mockGetRacePresets.mockResolvedValueOnce({ success: true, presets: [PRESET_A, PRESET_B] })

    await useRacePresets.getState().load()

    expect(useRacePresets.getState().selectedName).toBe('Beta')
    expect(localStorage.getItem('uma_selected_race_preset__default')).toBe('Beta')
  })

  it('falls back to first preset when localStorage key is stale', async () => {
    localStorage.setItem('uma_selected_race_preset__default', 'Stale')
    mockGetRacePresets.mockResolvedValueOnce({ success: true, presets: [PRESET_A, PRESET_B] })

    await useRacePresets.getState().load()

    expect(useRacePresets.getState().selectedName).toBe('Alpha')
    expect(localStorage.getItem('uma_selected_race_preset__default')).toBe('Alpha')
  })

  it('clears list and removes localStorage key when server returns no presets', async () => {
    localStorage.setItem('uma_selected_race_preset__default', 'Alpha')
    mockGetRacePresets.mockResolvedValueOnce({ success: true, presets: [] })

    await useRacePresets.getState().load()

    const s = useRacePresets.getState()
    expect(s.presets).toHaveLength(0)
    expect(s.selectedName).toBe('')
    expect(localStorage.getItem('uma_selected_race_preset__default')).toBeNull()
  })

  it('clears state on API error', async () => {
    localStorage.setItem('uma_selected_race_preset__default', 'Alpha')
    mockGetRacePresets.mockRejectedValueOnce(new Error('Network error'))

    await useRacePresets.getState().load()

    expect(useRacePresets.getState().presets).toHaveLength(0)
    expect(useRacePresets.getState().selectedName).toBe('')
    expect(localStorage.getItem('uma_selected_race_preset__default')).toBeNull()
  })
})

// ---------------------------------------------------------------------------
// select()
// ---------------------------------------------------------------------------
describe('racePresets store — select()', () => {
  it('updates selectedName and writes localStorage', () => {
    useRacePresets.setState({ presets: [PRESET_A, PRESET_B], selectedName: 'Alpha' })

    useRacePresets.getState().select('Beta')

    expect(useRacePresets.getState().selectedName).toBe('Beta')
    expect(localStorage.getItem('uma_selected_race_preset__default')).toBe('Beta')
  })
})

// ---------------------------------------------------------------------------
// create()
// ---------------------------------------------------------------------------
describe('racePresets store — create()', () => {
  beforeEach(() => {
    mockGetRacePresets.mockResolvedValue({ success: true, presets: [PRESET_A, PRESET_B] })
  })

  it('throws for empty name', async () => {
    await expect(useRacePresets.getState().create('')).rejects.toThrow(
      'Race preset name cannot be empty.',
    )
    expect(mockSaveRacePreset).not.toHaveBeenCalled()
  })

  it('throws for whitespace-only name', async () => {
    await expect(useRacePresets.getState().create('   ')).rejects.toThrow(
      'Race preset name cannot be empty.',
    )
  })

  it('throws for duplicate name (case-insensitive)', async () => {
    useRacePresets.setState({ presets: [PRESET_A, PRESET_B], selectedName: 'Alpha' })

    await expect(useRacePresets.getState().create('alpha')).rejects.toThrow(
      'A race preset with that name already exists.',
    )
    expect(mockSaveRacePreset).not.toHaveBeenCalled()
  })

  it('POSTs with empty extra_race_list on create', async () => {
    useRacePresets.setState({ presets: [PRESET_A], selectedName: 'Alpha' })
    mockSaveRacePreset.mockResolvedValueOnce({
      success: true,
      preset: { name: 'Gamma', extra_race_list: [] },
    })

    await useRacePresets.getState().create('Gamma')

    expect(mockSaveRacePreset).toHaveBeenCalledWith({
      preset: { name: 'Gamma', extra_race_list: [] },
    })
  })

  it('sets selectedName to the server-returned name after create', async () => {
    const PRESET_G: RacePreset = { name: 'Gamma', extra_race_list: [] }
    useRacePresets.setState({ presets: [PRESET_A], selectedName: 'Alpha' })
    mockSaveRacePreset.mockResolvedValueOnce({ success: true, preset: PRESET_G })
    mockGetRacePresets.mockResolvedValueOnce({ success: true, presets: [PRESET_A, PRESET_G] })

    await useRacePresets.getState().create('Gamma')

    expect(useRacePresets.getState().selectedName).toBe('Gamma')
    expect(localStorage.getItem('uma_selected_race_preset__default')).toBe('Gamma')
  })

  it('throws when server returns !success', async () => {
    useRacePresets.setState({ presets: [], selectedName: '' })
    mockSaveRacePreset.mockResolvedValueOnce({ success: false, detail: 'Server error' })
    mockGetRacePresets.mockResolvedValue({ success: true, presets: [] })

    await expect(useRacePresets.getState().create('NewPreset')).rejects.toThrow('Server error')
  })

  it('throws on network error', async () => {
    useRacePresets.setState({ presets: [], selectedName: '' })
    mockSaveRacePreset.mockRejectedValueOnce(new Error('timeout'))

    await expect(useRacePresets.getState().create('NewPreset')).rejects.toThrow(
      'Failed to save new race preset.',
    )
  })
})

// ---------------------------------------------------------------------------
// remove()
// ---------------------------------------------------------------------------
describe('racePresets store — remove()', () => {
  it('calls deleteRacePreset and reloads on success', async () => {
    useRacePresets.setState({ presets: [PRESET_A, PRESET_B], selectedName: 'Alpha' })
    mockDeleteRacePreset.mockResolvedValueOnce({ success: true })
    mockGetRacePresets.mockResolvedValueOnce({ success: true, presets: [PRESET_B] })

    await useRacePresets.getState().remove('Alpha')

    expect(mockDeleteRacePreset).toHaveBeenCalledWith({ name: 'Alpha' })
    expect(useRacePresets.getState().presets).toHaveLength(1)
  })

  it('throws on delete failure', async () => {
    mockDeleteRacePreset.mockResolvedValueOnce({ success: false, detail: 'Not found' })

    await expect(useRacePresets.getState().remove('Alpha')).rejects.toThrow('Not found')
  })

  it('throws on network error', async () => {
    mockDeleteRacePreset.mockRejectedValueOnce(new Error('Network'))

    await expect(useRacePresets.getState().remove('Alpha')).rejects.toThrow(
      'Failed to delete race preset.',
    )
  })
})

// ---------------------------------------------------------------------------
// update()
// ---------------------------------------------------------------------------
describe('racePresets store — update()', () => {
  it('optimistically updates the in-store copy', async () => {
    useRacePresets.setState({ presets: [PRESET_A, PRESET_B], selectedName: 'Alpha' })
    mockSaveRacePreset.mockResolvedValueOnce({ success: true })

    const modified: RacePreset = { ...PRESET_A, extra_race_list: [99, 100] }
    await useRacePresets.getState().update(modified)

    const found = useRacePresets.getState().presets.find((p) => p.name === 'Alpha')
    expect(found?.extra_race_list).toEqual([99, 100])
  })

  it('calls saveRacePreset with the full preset', async () => {
    useRacePresets.setState({ presets: [PRESET_A], selectedName: 'Alpha' })
    mockSaveRacePreset.mockResolvedValueOnce({ success: true })

    const modified: RacePreset = { ...PRESET_A, extra_race_list: [7, 8, 9] }
    await useRacePresets.getState().update(modified)

    expect(mockSaveRacePreset).toHaveBeenCalledWith({ preset: modified })
  })
})

// ---------------------------------------------------------------------------
// getActive()
// ---------------------------------------------------------------------------
describe('racePresets store — getActive()', () => {
  it('returns the active race preset', () => {
    useRacePresets.setState({ presets: [PRESET_A, PRESET_B], selectedName: 'Beta' })
    expect(useRacePresets.getState().getActive()).toEqual(PRESET_B)
  })

  it('returns undefined when no preset selected', () => {
    useRacePresets.setState({ presets: [PRESET_A], selectedName: '' })
    expect(useRacePresets.getState().getActive()).toBeUndefined()
  })
})

// ---------------------------------------------------------------------------
// localStorage key
// ---------------------------------------------------------------------------
describe('racePresets store — localStorage key', () => {
  it('uses key uma_selected_race_preset (not uma_selected_preset)', async () => {
    mockGetRacePresets.mockResolvedValueOnce({ success: true, presets: [PRESET_A] })
    await useRacePresets.getState().load()

    expect(localStorage.getItem('uma_selected_race_preset__default')).toBe('Alpha')
    // Must NOT pollute the skill preset key
    expect(localStorage.getItem('uma_selected_preset__default')).toBeNull()
  })
})
