import { describe, it, expect, vi, beforeEach } from 'vitest'
import { usePresets } from './presets'
import type { Preset } from '@/api/types'

// ---------------------------------------------------------------------------
// Mock the API layer so no real HTTP calls are made
// ---------------------------------------------------------------------------
vi.mock('@/api/presets', () => ({
  getPresets: vi.fn(),
  savePreset: vi.fn(),
  deletePreset: vi.fn(),
}))

import { getPresets, savePreset, deletePreset } from '@/api/presets'

const mockGetPresets = vi.mocked(getPresets)
const mockSavePreset = vi.mocked(savePreset)
const mockDeletePreset = vi.mocked(deletePreset)

// ---------------------------------------------------------------------------
// Fixture presets
// ---------------------------------------------------------------------------
const PRESET_A: Preset = {
  name: 'Alpha',
  running_style: 1,
  learn_skill_list: [],
  learn_skill_blacklist: [],
  extra_race_list: [],
  learn_skill_threshold: 888,
}
const PRESET_B: Preset = {
  name: 'Beta',
  running_style: 2,
  learn_skill_list: [],
  learn_skill_blacklist: [],
  extra_race_list: [],
  learn_skill_threshold: 500,
}

// ---------------------------------------------------------------------------
// Reset state before each test
// ---------------------------------------------------------------------------
beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
  usePresets.setState({ presets: [], selectedName: '' })
})

// ---------------------------------------------------------------------------
// load()
// ---------------------------------------------------------------------------
describe('presets store — load()', () => {
  it('sets list and selects first preset when no localStorage key', async () => {
    mockGetPresets.mockResolvedValueOnce({ success: true, presets: [PRESET_A, PRESET_B] })

    await usePresets.getState().load()

    const s = usePresets.getState()
    expect(s.presets).toHaveLength(2)
    expect(s.selectedName).toBe('Alpha')
    expect(localStorage.getItem('uma_selected_preset__default')).toBe('Alpha')
  })

  it('honours localStorage key when it matches a preset', async () => {
    localStorage.setItem('uma_selected_preset__default', 'Beta')
    mockGetPresets.mockResolvedValueOnce({ success: true, presets: [PRESET_A, PRESET_B] })

    await usePresets.getState().load()

    expect(usePresets.getState().selectedName).toBe('Beta')
    expect(localStorage.getItem('uma_selected_preset__default')).toBe('Beta')
  })

  it('falls back to first preset when localStorage key is stale', async () => {
    localStorage.setItem('uma_selected_preset__default', 'Stale')
    mockGetPresets.mockResolvedValueOnce({ success: true, presets: [PRESET_A, PRESET_B] })

    await usePresets.getState().load()

    expect(usePresets.getState().selectedName).toBe('Alpha')
    expect(localStorage.getItem('uma_selected_preset__default')).toBe('Alpha')
  })

  it('clears list and removes localStorage key when server returns no presets', async () => {
    localStorage.setItem('uma_selected_preset__default', 'Alpha')
    mockGetPresets.mockResolvedValueOnce({ success: true, presets: [] })

    await usePresets.getState().load()

    const s = usePresets.getState()
    expect(s.presets).toHaveLength(0)
    expect(s.selectedName).toBe('')
    expect(localStorage.getItem('uma_selected_preset__default')).toBeNull()
  })

  it('clears state on API error', async () => {
    localStorage.setItem('uma_selected_preset__default', 'Alpha')
    mockGetPresets.mockRejectedValueOnce(new Error('Network error'))

    await usePresets.getState().load()

    expect(usePresets.getState().presets).toHaveLength(0)
    expect(usePresets.getState().selectedName).toBe('')
    expect(localStorage.getItem('uma_selected_preset__default')).toBeNull()
  })
})

// ---------------------------------------------------------------------------
// select()
// ---------------------------------------------------------------------------
describe('presets store — select()', () => {
  it('updates selectedName and writes localStorage', () => {
    usePresets.setState({ presets: [PRESET_A, PRESET_B], selectedName: 'Alpha' })

    usePresets.getState().select('Beta')

    expect(usePresets.getState().selectedName).toBe('Beta')
    expect(localStorage.getItem('uma_selected_preset__default')).toBe('Beta')
  })
})

// ---------------------------------------------------------------------------
// create()
// ---------------------------------------------------------------------------
describe('presets store — create()', () => {
  beforeEach(() => {
    // After create(), load() is called — set up that response too
    mockGetPresets.mockResolvedValue({ success: true, presets: [PRESET_A, PRESET_B] })
  })

  it('throws for empty name', async () => {
    await expect(usePresets.getState().create('')).rejects.toThrow(
      'Preset name cannot be empty.',
    )
    expect(mockSavePreset).not.toHaveBeenCalled()
  })

  it('throws for whitespace-only name', async () => {
    await expect(usePresets.getState().create('   ')).rejects.toThrow(
      'Preset name cannot be empty.',
    )
  })

  it('throws for duplicate name (case-insensitive)', async () => {
    usePresets.setState({ presets: [PRESET_A, PRESET_B], selectedName: 'Alpha' })

    await expect(usePresets.getState().create('alpha')).rejects.toThrow(
      'A preset with that name already exists.',
    )
    expect(mockSavePreset).not.toHaveBeenCalled()
  })

  it('normalizes name before duplicate check', async () => {
    usePresets.setState({ presets: [PRESET_A], selectedName: 'Alpha' })

    // 'ALPHA!!!' → normalizes to 'ALPHA' → matches 'Alpha' case-insensitively
    await expect(usePresets.getState().create('ALPHA!!!')).rejects.toThrow(
      'A preset with that name already exists.',
    )
  })

  it('POSTs with correct template on success', async () => {
    usePresets.setState({ presets: [PRESET_A], selectedName: 'Alpha' })
    mockSavePreset.mockResolvedValueOnce({
      success: true,
      preset: { name: 'Gamma', running_style: 1, learn_skill_list: [], learn_skill_blacklist: [], extra_race_list: [], learn_skill_threshold: 888 },
    })

    await usePresets.getState().create('Gamma')

    expect(mockSavePreset).toHaveBeenCalledWith({
      preset: {
        name: 'Gamma',
        running_style: 1,
        learn_skill_list: [],
        learn_skill_blacklist: [],
        extra_race_list: [],
        learn_skill_threshold: 888,
      },
    })
  })

  it('sets selectedName to the server-returned name after create', async () => {
    const PRESET_G: Preset = { name: 'Gamma', running_style: 1, learn_skill_list: [], learn_skill_blacklist: [], extra_race_list: [], learn_skill_threshold: 888 }
    usePresets.setState({ presets: [PRESET_A], selectedName: 'Alpha' })
    mockSavePreset.mockResolvedValueOnce({ success: true, preset: PRESET_G })
    // reload after create must include Gamma so the localStorage key resolves correctly
    mockGetPresets.mockResolvedValueOnce({ success: true, presets: [PRESET_A, PRESET_G] })

    await usePresets.getState().create('Gamma')

    expect(usePresets.getState().selectedName).toBe('Gamma')
    expect(localStorage.getItem('uma_selected_preset__default')).toBe('Gamma')
  })

  it('throws "Failed to save new preset." when save returns !success', async () => {
    usePresets.setState({ presets: [], selectedName: '' })
    mockSavePreset.mockResolvedValueOnce({ success: false, detail: 'Server error' })
    mockGetPresets.mockResolvedValue({ success: true, presets: [] })

    await expect(usePresets.getState().create('NewPreset')).rejects.toThrow('Server error')
  })

  it('throws "Failed to save new preset." on network error', async () => {
    usePresets.setState({ presets: [], selectedName: '' })
    mockSavePreset.mockRejectedValueOnce(new Error('timeout'))

    await expect(usePresets.getState().create('NewPreset')).rejects.toThrow(
      'Failed to save new preset.',
    )
  })
})

// ---------------------------------------------------------------------------
// remove()
// ---------------------------------------------------------------------------
describe('presets store — remove()', () => {
  it('calls deletePreset and reloads on success', async () => {
    usePresets.setState({ presets: [PRESET_A, PRESET_B], selectedName: 'Alpha' })
    mockDeletePreset.mockResolvedValueOnce({ success: true })
    mockGetPresets.mockResolvedValueOnce({ success: true, presets: [PRESET_B] })

    await usePresets.getState().remove('Alpha')

    expect(mockDeletePreset).toHaveBeenCalledWith({ name: 'Alpha' })
    // reload ran — presets should now reflect server response
    expect(usePresets.getState().presets).toHaveLength(1)
  })

  it('throws on delete failure', async () => {
    mockDeletePreset.mockResolvedValueOnce({ success: false, detail: 'Not found' })

    await expect(usePresets.getState().remove('Alpha')).rejects.toThrow('Not found')
  })

  it('throws on network error', async () => {
    mockDeletePreset.mockRejectedValueOnce(new Error('Network'))

    await expect(usePresets.getState().remove('Alpha')).rejects.toThrow(
      'Failed to delete preset.',
    )
  })
})

// ---------------------------------------------------------------------------
// update()
// ---------------------------------------------------------------------------
describe('presets store — update()', () => {
  it('optimistically updates the in-store copy', async () => {
    usePresets.setState({ presets: [PRESET_A, PRESET_B], selectedName: 'Alpha' })
    mockSavePreset.mockResolvedValueOnce({ success: true })

    const modified: Preset = { ...PRESET_A, running_style: 3 }
    await usePresets.getState().update(modified)

    const found = usePresets.getState().presets.find((p) => p.name === 'Alpha')
    expect(found?.running_style).toBe(3)
  })

  it('calls savePreset with the full preset', async () => {
    usePresets.setState({ presets: [PRESET_A], selectedName: 'Alpha' })
    mockSavePreset.mockResolvedValueOnce({ success: true })

    const modified: Preset = { ...PRESET_A, learn_skill_threshold: 500 }
    await usePresets.getState().update(modified)

    expect(mockSavePreset).toHaveBeenCalledWith({ preset: modified })
  })
})

// ---------------------------------------------------------------------------
// getActive()
// ---------------------------------------------------------------------------
describe('presets store — getActive()', () => {
  it('returns the active preset', () => {
    usePresets.setState({ presets: [PRESET_A, PRESET_B], selectedName: 'Beta' })
    expect(usePresets.getState().getActive()).toEqual(PRESET_B)
  })

  it('returns undefined when no preset selected', () => {
    usePresets.setState({ presets: [PRESET_A], selectedName: '' })
    expect(usePresets.getState().getActive()).toBeUndefined()
  })
})
