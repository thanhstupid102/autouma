/**
 * PresetSelectorCard — the shared shell's wiring and disabled states.
 *
 * PresetPanel and RacePresetPanel used to render this row inline, so the four
 * enable/disable rules lived in two places. They are pinned here once:
 *
 *   Select  disabled ⇔ the list is empty
 *   DEL     disabled ⇔ nothing is selected
 *   Export  disabled ⇔ there is no active preset
 *   Import  disabled ⇔ an import is in flight (and its label flips)
 *
 * NEW is never disabled — you must be able to create the first preset.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'

import { PresetSelectorCard } from './PresetSelectorCard'

const handlers = {
  onSelect: vi.fn(),
  onNew: vi.fn(),
  onDelete: vi.fn(),
  onExport: vi.fn(),
  onImportFile: vi.fn(),
}

const BASE = {
  title: 'Skill Presets',
  placeholder: 'No presets — create one',
  presets: [{ name: 'Alpha' }, { name: 'Beta' }],
  selectedName: 'Alpha',
  canExport: true,
  isImporting: false,
  ...handlers,
}

beforeEach(() => vi.clearAllMocks())

function btn(name: string) {
  return screen.getByRole('button', { name })
}

describe('PresetSelectorCard — labels', () => {
  it('renders the title it is given', () => {
    render(<PresetSelectorCard {...BASE} title="Race Presets" />)
    expect(screen.getByText('Race Presets')).toBeInTheDocument()
  })

  it('shows the placeholder when the list is empty', () => {
    render(
      <PresetSelectorCard
        {...BASE}
        presets={[]}
        selectedName=""
        placeholder="No race presets — create one"
      />,
    )
    expect(screen.getByText('No race presets — create one')).toBeInTheDocument()
  })

  it('uses a two-column phone action grid and restores the desktop row at md', () => {
    render(<PresetSelectorCard {...BASE} />)

    const card = screen.getByText('Skill Presets').closest('[data-slot="card"]')
    const content = card?.querySelector<HTMLElement>('[data-slot="card-content"]')
    const select = screen.getByRole('combobox')

    expect(content).toHaveClass(
      'grid',
      'grid-cols-2',
      'md:flex',
      'md:flex-wrap',
      'md:items-center',
    )
    expect(select).toHaveClass(
      'col-span-2',
      'w-full',
      'min-w-0',
      'md:w-fit',
      'md:min-w-[180px]',
      'md:flex-1',
    )
    for (const name of ['NEW', 'DEL', 'Export', 'Import']) {
      expect(btn(name)).toHaveClass('w-full', 'md:w-auto', 'h-11', 'md:h-7')
    }
  })
})

describe('PresetSelectorCard — disabled states', () => {
  it('disables the Select only when the list is empty', () => {
    const { unmount } = render(<PresetSelectorCard {...BASE} />)
    expect(screen.getByRole('combobox')).not.toBeDisabled()
    unmount()

    render(<PresetSelectorCard {...BASE} presets={[]} />)
    expect(screen.getByRole('combobox')).toBeDisabled()
  })

  it('never disables NEW — even with no presets at all', () => {
    render(<PresetSelectorCard {...BASE} presets={[]} selectedName="" canExport={false} />)
    expect(btn('NEW')).not.toBeDisabled()
  })

  it('disables DEL only when nothing is selected', () => {
    const { unmount } = render(<PresetSelectorCard {...BASE} />)
    expect(btn('DEL')).not.toBeDisabled()
    unmount()

    render(<PresetSelectorCard {...BASE} selectedName="" />)
    expect(btn('DEL')).toBeDisabled()
  })

  it('disables Export only when there is no active preset', () => {
    const { unmount } = render(<PresetSelectorCard {...BASE} />)
    expect(btn('Export')).not.toBeDisabled()
    unmount()

    render(<PresetSelectorCard {...BASE} canExport={false} />)
    expect(btn('Export')).toBeDisabled()
  })

  it('disables Import and flips its label while importing', () => {
    const { unmount } = render(<PresetSelectorCard {...BASE} />)
    expect(btn('Import')).not.toBeDisabled()
    unmount()

    render(<PresetSelectorCard {...BASE} isImporting />)
    expect(btn('Importing…')).toBeDisabled()
    expect(screen.queryByRole('button', { name: 'Import' })).toBeNull()
  })
})

describe('PresetSelectorCard — wiring', () => {
  it('hands a selected preset back to the parent', async () => {
    render(<PresetSelectorCard {...BASE} />)

    const select = screen.getByRole('combobox')
    select.focus()
    fireEvent.keyDown(select, { key: 'ArrowDown' })
    fireEvent.click(await screen.findByRole('option', { name: 'Beta' }))

    expect(handlers.onSelect).toHaveBeenCalledWith('Beta')
  })

  it('routes NEW / DEL / Export to the parent callbacks', () => {
    render(<PresetSelectorCard {...BASE} />)

    fireEvent.click(btn('NEW'))
    fireEvent.click(btn('DEL'))
    fireEvent.click(btn('Export'))

    expect(handlers.onNew).toHaveBeenCalledTimes(1)
    expect(handlers.onDelete).toHaveBeenCalledTimes(1)
    expect(handlers.onExport).toHaveBeenCalledTimes(1)
  })

  it('clicks its own hidden file input from the Import button', () => {
    const { container } = render(<PresetSelectorCard {...BASE} />)
    const input = container.querySelector('input[type="file"]') as HTMLInputElement
    expect(input).not.toBeNull()
    expect(input.accept).toBe('application/json')
    expect(input.multiple).toBe(true)

    const click = vi.fn()
    input.click = click
    fireEvent.click(btn('Import'))

    expect(click).toHaveBeenCalledTimes(1)
  })

  it('hands change events on the file input to onImportFile', () => {
    const { container } = render(<PresetSelectorCard {...BASE} />)
    const input = container.querySelector('input[type="file"]') as HTMLInputElement

    fireEvent.change(input, {
      target: { files: [new File(['{}'], 'p.json', { type: 'application/json' })] },
    })

    expect(handlers.onImportFile).toHaveBeenCalledTimes(1)
  })
})
