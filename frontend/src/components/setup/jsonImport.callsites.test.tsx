/**
 * useJsonImport — the three call sites, pinned to their EXACT toast strings.
 *
 * `handleImportFile` used to be copy-pasted into PresetPanel, RacePresetPanel
 * and BotConfiguration; it now lives in `@/hooks/useJsonImport`. The messages
 * and the validation semantics are user-visible, so every branch of every call
 * site asserts the literal string it produced before the extraction.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, waitFor } from '@testing-library/react'

import { PresetPanel } from './PresetPanel'
import { RacePresetPanel } from './RacePresetPanel'
import BotConfiguration from '@/pages/BotConfiguration'

// ---------------------------------------------------------------------------
// Mocks — stores, API, toasts, and the heavy children we do not exercise here
// ---------------------------------------------------------------------------
const mocks = vi.hoisted(() => ({
  presetsStore: {
    presets: [] as unknown[],
    selectedName: '',
    select: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
    getActive: vi.fn(),
    load: vi.fn(),
  },
  racePresetsStore: {
    presets: [] as unknown[],
    selectedName: '',
    select: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
    saveRaces: vi.fn(),
    getActive: vi.fn(),
    load: vi.fn(),
  },
  botConfigStore: {
    config: undefined as unknown,
    defaultConfig: undefined as unknown,
    scenarios: [] as unknown[],
    fields: {} as Record<string, unknown[]>,
    selectedScenarioId: '4',
    loading: false,
    saving: false,
    error: '',
    load: vi.fn(),
    save: vi.fn(),
    reset: vi.fn(),
    selectScenario: vi.fn(),
    updateField: vi.fn(),
    isDirty: vi.fn(),
  },
  savePreset: vi.fn(),
  saveRacePreset: vi.fn(),
  toastError: vi.fn(),
  toastSuccess: vi.fn(),
}))

vi.mock('@/stores/presets', () => ({ usePresets: () => mocks.presetsStore }))
vi.mock('@/stores/racePresets', () => ({ useRacePresets: () => mocks.racePresetsStore }))
vi.mock('@/stores/botConfig', () => ({
  useBotConfig: () => mocks.botConfigStore,
  botConfigValueAt: () => undefined,
}))
vi.mock('@/api/presets', () => ({
  savePreset: mocks.savePreset,
  saveRacePreset: mocks.saveRacePreset,
}))
// Heavy children — irrelevant to the import path.
vi.mock('./SkillEditorDialog', () => ({ SkillEditorDialog: () => null }))
vi.mock('./RaceSchedule', () => ({ RaceSchedule: () => null }))
vi.mock('sonner', () => ({
  toast: { error: mocks.toastError, success: mocks.toastSuccess },
}))

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function jsonFile(text: string): File {
  return new File([text], 'import.json', { type: 'application/json' })
}

/** Render `ui`, drop `text` into its hidden file input, resolve when settled. */
async function importInto(ui: React.ReactElement, text: string) {
  const { container } = render(ui)
  const input = container.querySelector('input[type="file"]') as HTMLInputElement
  expect(input).not.toBeNull()

  fireEvent.change(input, { target: { files: [jsonFile(text)] } })

  await waitFor(() =>
    expect(mocks.toastError.mock.calls.length + mocks.toastSuccess.mock.calls.length).toBe(1),
  )
  return input
}

beforeEach(() => {
  vi.clearAllMocks()
  mocks.presetsStore.getActive.mockReturnValue(undefined)
  mocks.racePresetsStore.getActive.mockReturnValue(undefined)
  mocks.botConfigStore.isDirty.mockReturnValue(false)
  // Every panel calls its store's load() once on mount — so a store load() count
  // of 1 means "mount only", and 2 means "the import's onDone reloaded too".
  mocks.presetsStore.load.mockResolvedValue(undefined)
  mocks.racePresetsStore.load.mockResolvedValue(undefined)
  mocks.botConfigStore.load.mockResolvedValue(undefined)
})

// ---------------------------------------------------------------------------
// PresetPanel — skill presets
// ---------------------------------------------------------------------------
describe('PresetPanel — import', () => {
  it('rejects JSON without a "name" string', async () => {
    await importInto(<PresetPanel />, JSON.stringify({ running_style: 1 }))

    expect(mocks.toastError).toHaveBeenCalledWith(
      'Import failed: JSON must have a "name" string field.',
    )
    expect(mocks.savePreset).not.toHaveBeenCalled()
  })

  it('rejects an empty "name"', async () => {
    await importInto(<PresetPanel />, JSON.stringify({ name: '' }))

    expect(mocks.toastError).toHaveBeenCalledWith(
      'Import failed: JSON must have a "name" string field.',
    )
  })

  it('accepts a preset with only a name (no extra_race_list needed)', async () => {
    mocks.savePreset.mockResolvedValueOnce({ success: true })

    await importInto(<PresetPanel />, JSON.stringify({ name: 'Speed build' }))

    expect(mocks.savePreset).toHaveBeenCalledWith({ preset: { name: 'Speed build' } })
    // mount load + the import's reload
    expect(mocks.presetsStore.load).toHaveBeenCalledTimes(2)
    expect(mocks.presetsStore.select).toHaveBeenCalledWith('Speed build')
    expect(mocks.toastSuccess).toHaveBeenCalledWith('Imported skill preset "Speed build"')
  })

  it('surfaces the server detail when the save is rejected', async () => {
    mocks.savePreset.mockResolvedValueOnce({ success: false, detail: 'name taken' })

    await importInto(<PresetPanel />, JSON.stringify({ name: 'Dupe' }))

    expect(mocks.toastError).toHaveBeenCalledWith('name taken')
    // mount load only — the reject branch returns before onDone
    expect(mocks.presetsStore.load).toHaveBeenCalledTimes(1)
    expect(mocks.presetsStore.select).not.toHaveBeenCalled()
  })

  it('falls back to the panel message when the server gives no detail', async () => {
    mocks.savePreset.mockResolvedValueOnce({ success: false })

    await importInto(<PresetPanel />, JSON.stringify({ name: 'Dupe' }))

    expect(mocks.toastError).toHaveBeenCalledWith('Import failed: server rejected the preset.')
  })

  it('surfaces a parse error from the file itself', async () => {
    await importInto(<PresetPanel />, 'not json {{{')

    expect(mocks.toastError).toHaveBeenCalledWith('Invalid JSON in file')
  })

  it('clears the file input so the same file can be re-imported', async () => {
    mocks.savePreset.mockResolvedValueOnce({ success: true })

    const input = await importInto(<PresetPanel />, JSON.stringify({ name: 'Again' }))

    expect(input.value).toBe('')
  })
})

// ---------------------------------------------------------------------------
// RacePresetPanel — race presets
// ---------------------------------------------------------------------------
describe('RacePresetPanel — import', () => {
  it('rejects JSON missing extra_race_list', async () => {
    await importInto(<RacePresetPanel />, JSON.stringify({ name: 'G1 focus' }))

    expect(mocks.toastError).toHaveBeenCalledWith(
      'Import failed: JSON must have a "name" string and "extra_race_list" array.',
    )
    expect(mocks.saveRacePreset).not.toHaveBeenCalled()
  })

  it('rejects JSON missing a name', async () => {
    await importInto(<RacePresetPanel />, JSON.stringify({ extra_race_list: [1] }))

    expect(mocks.toastError).toHaveBeenCalledWith(
      'Import failed: JSON must have a "name" string and "extra_race_list" array.',
    )
  })

  it('saves, reloads, selects and toasts on success', async () => {
    mocks.saveRacePreset.mockResolvedValueOnce({ success: true })

    await importInto(
      <RacePresetPanel />,
      JSON.stringify({ name: 'G1 focus', extra_race_list: [1, 2] }),
    )

    expect(mocks.saveRacePreset).toHaveBeenCalledWith({
      preset: { name: 'G1 focus', extra_race_list: [1, 2] },
    })
    // mount load + the import's reload
    expect(mocks.racePresetsStore.load).toHaveBeenCalledTimes(2)
    expect(mocks.racePresetsStore.select).toHaveBeenCalledWith('G1 focus')
    expect(mocks.toastSuccess).toHaveBeenCalledWith('Imported race preset "G1 focus"')
  })

  it('falls back to the race-panel message when the server gives no detail', async () => {
    mocks.saveRacePreset.mockResolvedValueOnce({ success: false })

    await importInto(
      <RacePresetPanel />,
      JSON.stringify({ name: 'G1 focus', extra_race_list: [] }),
    )

    expect(mocks.toastError).toHaveBeenCalledWith(
      'Import failed: server rejected the race preset.',
    )
  })
})

// ---------------------------------------------------------------------------
// BotConfiguration — the third call site (no isImporting; save() throws)
// ---------------------------------------------------------------------------
describe('BotConfiguration — import', () => {
  const VALID_DOC = { version: 1, scenarios: { '4': {} } }

  it('rejects JSON that is not a bot-config document', async () => {
    await importInto(<BotConfiguration />, JSON.stringify({ name: 'nope' }))

    expect(mocks.toastError).toHaveBeenCalledWith(
      'Import failed: JSON must contain version and scenarios fields.',
    )
    expect(mocks.botConfigStore.save).not.toHaveBeenCalled()
  })

  it('saves and toasts on success', async () => {
    mocks.botConfigStore.save.mockResolvedValueOnce(undefined)

    await importInto(<BotConfiguration />, JSON.stringify(VALID_DOC))

    expect(mocks.botConfigStore.save).toHaveBeenCalledWith(VALID_DOC)
    expect(mocks.toastSuccess).toHaveBeenCalledWith('Bot configuration imported and saved.')
  })

  it('surfaces a thrown save error message', async () => {
    mocks.botConfigStore.save.mockRejectedValueOnce(new Error('schema mismatch'))

    await importInto(<BotConfiguration />, JSON.stringify(VALID_DOC))

    expect(mocks.toastError).toHaveBeenCalledWith('schema mismatch')
  })

  it('uses its own fallback when the thrown value is not an Error', async () => {
    mocks.botConfigStore.save.mockRejectedValueOnce('plain string')

    await importInto(<BotConfiguration />, JSON.stringify(VALID_DOC))

    expect(mocks.toastError).toHaveBeenCalledWith('Failed to import bot configuration.')
  })
})
