import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import { PresetPanel } from './PresetPanel'
import { RacePresetPanel } from './RacePresetPanel'
import BotConfiguration from '@/pages/BotConfiguration'

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
    remove: vi.fn(),
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
vi.mock('./SkillEditorDialog', () => ({ SkillEditorDialog: () => null }))
vi.mock('./RaceSchedule', () => ({ RaceSchedule: () => null }))
vi.mock('sonner', () => ({
  toast: { error: mocks.toastError, success: mocks.toastSuccess },
}))

function jsonFile(name: string, value: unknown): File {
  return new File([JSON.stringify(value)], name, { type: 'application/json' })
}

function textFile(name: string, text: string): File {
  return new File([text], name, { type: 'application/json' })
}

async function importFiles(ui: React.ReactElement, files: File[], load: () => unknown) {
  const result = render(ui)
  const input = result.container.querySelector('input[type="file"]') as HTMLInputElement
  expect(input).not.toBeNull()
  await waitFor(() => expect(load).toHaveBeenCalledTimes(1))
  fireEvent.change(input, { target: { files } })
  return { ...result, input }
}

async function waitForSummary() {
  await waitFor(() =>
    expect(mocks.toastError.mock.calls.length + mocks.toastSuccess.mock.calls.length).toBe(1),
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  mocks.savePreset.mockResolvedValue({ success: true })
  mocks.saveRacePreset.mockResolvedValue({ success: true })
  mocks.presetsStore.presets = []
  mocks.presetsStore.getActive.mockReturnValue(undefined)
  mocks.presetsStore.load.mockResolvedValue(undefined)
  mocks.racePresetsStore.presets = []
  mocks.racePresetsStore.getActive.mockReturnValue(undefined)
  mocks.racePresetsStore.load.mockResolvedValue(undefined)
  mocks.botConfigStore.isDirty.mockReturnValue(false)
  mocks.botConfigStore.load.mockResolvedValue(undefined)
})

describe('preset batch import', () => {
  it('imports all valid files in sorted filename order and reloads once', async () => {
    const { input } = await importFiles(<PresetPanel />, [
      jsonFile('zeta.json', { name: 'Zeta' }),
      jsonFile('alpha.json', { name: 'Alpha' }),
      jsonFile('middle.json', { name: 'Middle' }),
    ], mocks.presetsStore.load)

    await waitForSummary()

    expect(input.multiple).toBe(true)
    expect(mocks.savePreset.mock.calls).toEqual([
      [{ preset: { name: 'Alpha' } }],
      [{ preset: { name: 'Middle' } }],
      [{ preset: { name: 'Zeta' } }],
    ])
    // One mount load and one batch-complete load; not one load per file.
    expect(mocks.presetsStore.load).toHaveBeenCalledTimes(2)
    expect(mocks.presetsStore.select).toHaveBeenCalledWith('Zeta')
    expect(mocks.toastSuccess).toHaveBeenCalledWith('Imported 3 skill presets.')
  })

  it('continues after an invalid file and names its validation failure', async () => {
    await importFiles(<PresetPanel />, [
      jsonFile('a-valid.json', { name: 'One' }),
      jsonFile('b-invalid.json', { running_style: 1 }),
      jsonFile('c-valid.json', { name: 'Two' }),
    ], mocks.presetsStore.load)

    await waitForSummary()

    expect(mocks.savePreset).toHaveBeenCalledTimes(2)
    expect(mocks.presetsStore.load).toHaveBeenCalledTimes(2)
    expect(mocks.presetsStore.select).toHaveBeenCalledWith('Two')
    expect(mocks.toastError).toHaveBeenCalledWith(
      'Imported 2 of 3 skill presets. Failed: b-invalid.json (Import failed: JSON must have a "name" string field).',
    )
  })

  it('reports every invalid file without saving or changing the selection', async () => {
    await importFiles(<PresetPanel />, [
      jsonFile('a-invalid.json', { running_style: 1 }),
      textFile('b-invalid.json', 'not valid JSON'),
      jsonFile('c-invalid.json', { name: '' }),
    ], mocks.presetsStore.load)

    await waitForSummary()

    expect(mocks.savePreset).not.toHaveBeenCalled()
    expect(mocks.presetsStore.load).toHaveBeenCalledTimes(1)
    expect(mocks.presetsStore.select).not.toHaveBeenCalled()
    expect(mocks.toastError).toHaveBeenCalledWith(
      'Imported 0 of 3 skill presets. Failed: a-invalid.json (Import failed: JSON must have a "name" string field); b-invalid.json (Invalid JSON in file); c-invalid.json (Import failed: JSON must have a "name" string field).',
    )
  })

  it('treats a server rejection as one failed file instead of aborting the batch', async () => {
    mocks.savePreset
      .mockResolvedValueOnce({ success: true })
      .mockResolvedValueOnce({ success: false, detail: 'server says no' })
      .mockResolvedValueOnce({ success: true })

    await importFiles(<PresetPanel />, [
      jsonFile('a.json', { name: 'Accepted first' }),
      jsonFile('b.json', { name: 'Rejected' }),
      jsonFile('c.json', { name: 'Accepted last' }),
    ], mocks.presetsStore.load)

    await waitForSummary()

    expect(mocks.savePreset).toHaveBeenCalledTimes(3)
    expect(mocks.presetsStore.select).toHaveBeenCalledWith('Accepted last')
    expect(mocks.toastError).toHaveBeenCalledWith(
      'Imported 2 of 3 skill presets. Failed: b.json (server says no).',
    )
  })

  it('surfaces duplicate race-preset names while preserving the later overwrite', async () => {
    const { input } = await importFiles(<RacePresetPanel />, [
      jsonFile('a-first.json', { name: 'Shared', extra_race_list: [1] }),
      jsonFile('b-second.json', { name: 'Shared', extra_race_list: [2] }),
    ], mocks.racePresetsStore.load)

    await waitForSummary()

    expect(input.multiple).toBe(true)
    expect(mocks.saveRacePreset).toHaveBeenCalledTimes(2)
    expect(mocks.racePresetsStore.select).toHaveBeenCalledWith('Shared')
    expect(mocks.toastSuccess).toHaveBeenCalledWith(
      'Imported 2 race presets. Name collisions: "Shared" overwrites the earlier import "Shared".',
    )
  })

  it('surfaces an overwrite of an existing preset without changing the upsert', async () => {
    mocks.presetsStore.presets = [{ name: 'Stored' }]

    await importFiles(
      <PresetPanel />,
      [jsonFile('stored.json', { name: 'Stored' }), jsonFile('new.json', { name: 'New' })],
      mocks.presetsStore.load,
    )

    await waitForSummary()

    expect(mocks.savePreset).toHaveBeenCalledTimes(2)
    expect(mocks.toastSuccess).toHaveBeenCalledWith(
      'Imported 2 skill presets. Name collisions: "Stored" overwrites the existing preset "Stored".',
    )
  })

  it('keeps Import disabled for the whole batch, including when every file fails', async () => {
    const { input } = await importFiles(<PresetPanel />, [
      jsonFile('a-invalid.json', { running_style: 1 }),
      jsonFile('b-invalid.json', { name: '' }),
    ], mocks.presetsStore.load)

    expect(input.value).toBe('')
    expect(screen.getByRole('button', { name: 'Importing…' })).toBeDisabled()
    await waitForSummary()
    expect(screen.getByRole('button', { name: 'Import' })).not.toBeDisabled()
  })
})

describe('BotConfiguration import', () => {
  it('keeps its input single-file and its single-file import behavior unchanged', async () => {
    const { container } = render(<BotConfiguration />)
    const input = container.querySelector('input[type="file"]') as HTMLInputElement

    expect(input.multiple).toBe(false)
    fireEvent.change(input, {
      target: { files: [jsonFile('configuration.json', { version: 1, scenarios: { '4': {} } })] },
    })

    await waitForSummary()

    expect(mocks.botConfigStore.save).toHaveBeenCalledWith({ version: 1, scenarios: { '4': {} } })
    expect(mocks.toastSuccess).toHaveBeenCalledWith('Bot configuration imported and saved.')
  })
})
