/**
 * PresetPanel / NewPresetDialog.
 *
 * Scenario is deliberately NOT editable here: the scenario a run uses is picked
 * per-run in RunBar and sent in the career body. Presets still round-trip a
 * `scenario_id` server-side (career_bot/planning/presets.py) — that is what
 * stops a read-mutate-write from silently downgrading a non-MANT preset to
 * MANT — but no field in this UI writes it. These tests pin:
 *
 *   * the NEW dialog hands the typed name straight to presets.create();
 *   * the shared dialog shell keeps its name-only shape (no scenario field).
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'

import { PresetPanel } from './PresetPanel'
import { NewPresetDialog } from './NewPresetDialog'
import type { Preset } from '@/api/types'

// ---------------------------------------------------------------------------
// Mocks — stores and side-effecting modules
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
  savePreset: vi.fn(),
  toastError: vi.fn(),
  toastSuccess: vi.fn(),
}))

vi.mock('@/stores/presets', () => ({ usePresets: () => mocks.presetsStore }))
vi.mock('@/api/presets', () => ({ savePreset: mocks.savePreset }))
// The skill editor pulls in the whole skill catalogue; irrelevant here.
vi.mock('./SkillEditorDialog', () => ({ SkillEditorDialog: () => null }))
vi.mock('sonner', () => ({
  toast: { error: mocks.toastError, success: mocks.toastSuccess },
}))

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------
/** Shape the server hands back for a legacy preset written before scenario_id. */
const LEGACY_PRESET: Preset = {
  name: 'Legacy',
  running_style: 1,
  learn_skill_list: [],
  learn_skill_blacklist: [],
  extra_race_list: [],
  learn_skill_threshold: 888,
}

/** A preset the server stored with a non-MANT scenario — the field still
 *  round-trips even though nothing in this UI edits it. */
const UNITY_PRESET: Preset = { ...LEGACY_PRESET, name: 'Unity run', scenario_id: 2, scenario: 2 }

function setActive(preset: Preset | undefined) {
  mocks.presetsStore.presets = preset ? [preset] : []
  mocks.presetsStore.selectedName = preset?.name ?? ''
  mocks.presetsStore.getActive.mockReturnValue(preset)
}

beforeEach(() => {
  vi.clearAllMocks()
  setActive(UNITY_PRESET)
  mocks.presetsStore.create.mockResolvedValue(undefined)
  mocks.presetsStore.remove.mockResolvedValue(undefined)
})

// ---------------------------------------------------------------------------
// NewPresetDialog through PresetPanel — create carries the typed name
// ---------------------------------------------------------------------------
describe('PresetPanel — NEW preset dialog', () => {
  function openNewDialog() {
    render(<PresetPanel />)
    fireEvent.click(screen.getByRole('button', { name: 'NEW' }))
    return screen.getByRole('dialog')
  }

  it('creates the preset with the typed name', async () => {
    const dialog = openNewDialog()
    fireEvent.change(within(dialog).getByLabelText('Preset name'), {
      target: { value: 'Speed build' },
    })

    fireEvent.click(within(dialog).getByRole('button', { name: 'Create' }))

    await waitFor(() => expect(mocks.presetsStore.create).toHaveBeenCalledWith('Speed build'))
  })

  it('keeps the preset config fields collapsed below sm', () => {
    render(<PresetPanel />)

    const card = screen.getByText('Preset Config').closest('[data-slot="card"]')
    const content = card?.querySelector('[data-slot="card-content"]')
    expect(content).toHaveClass('grid-cols-1', 'sm:grid-cols-2')
  })

  it('keeps delete actions reachable and deletes the selected preset', async () => {
    render(<PresetPanel />)
    fireEvent.click(screen.getByRole('button', { name: 'DEL' }))

    const dialog = screen.getByRole('dialog')
    const body = dialog.querySelector<HTMLElement>('[data-slot="dialog-body"]')
    const footer = dialog.querySelector<HTMLElement>('[data-slot="dialog-footer"]')
    expect(within(dialog).getByRole('button', { name: 'Cancel' })).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: 'Delete' })).toBeInTheDocument()
    expect(body).not.toBeNull()
    expect(body?.nextElementSibling).toBe(footer)

    fireEvent.click(within(dialog).getByRole('button', { name: 'Delete' }))
    await waitFor(() => expect(mocks.presetsStore.remove).toHaveBeenCalledWith('Unity run'))
  })
})

// ---------------------------------------------------------------------------
// Shared shell — the dialog is name-only
// ---------------------------------------------------------------------------
describe('NewPresetDialog — shared shell', () => {
  const shellProps = {
    open: true,
    onOpenChange: vi.fn(),
    title: 'New Race Preset',
    label: 'Race preset name',
    inputId: 'new-race-preset-name',
    placeholder: 'e.g. G1 focus',
    errorFallback: 'Failed to save new race preset.',
  }

  it('renders no scenario field', () => {
    render(<NewPresetDialog {...shellProps} create={vi.fn()} />)
    const dialog = screen.getByRole('dialog')
    const body = dialog.querySelector<HTMLElement>('[data-slot="dialog-body"]')
    const footer = dialog.querySelector<HTMLElement>('[data-slot="dialog-footer"]')
    expect(within(dialog).queryByLabelText('Scenario')).toBeNull()
    expect(within(dialog).getByLabelText('Race preset name')).toBeInTheDocument()
    expect(body).not.toBeNull()
    expect(body?.nextElementSibling).toBe(footer)
    expect(within(dialog).getByRole('button', { name: 'Cancel' })).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: 'Create' })).toBeInTheDocument()
  })

  it('calls create with the name only', async () => {
    const create = vi.fn().mockResolvedValue(undefined)
    render(<NewPresetDialog {...shellProps} create={create} />)
    const dialog = screen.getByRole('dialog')

    fireEvent.change(within(dialog).getByLabelText('Race preset name'), {
      target: { value: 'G1 focus' },
    })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Create' }))

    await waitFor(() => expect(create).toHaveBeenCalledWith('G1 focus'))
  })
})
