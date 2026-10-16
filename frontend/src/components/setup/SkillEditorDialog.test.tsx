import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { SkillEditorDialog } from './SkillEditorDialog'

const mocks = vi.hoisted(() => ({
  active: {
    name: 'Mobile preset',
    learn_skill_list: [['Existing']],
    learn_skill_blacklist: ['Blocked'],
  },
  getSkills: vi.fn(),
  getActive: vi.fn(),
  update: vi.fn(),
}))

vi.mock('@/api/presets', () => ({ getSkills: mocks.getSkills }))
vi.mock('@/stores/presets', () => ({
  usePresets: () => ({ getActive: mocks.getActive, update: mocks.update }),
}))

const skills = [
  { id: 1, name: 'Alpha', rarity: 1, tags: [101], icon_id: '1001001' },
  { id: 2, name: 'Beta', rarity: 2, tags: [102], icon_id: '2002001' },
]

beforeEach(() => {
  mocks.active = {
    name: 'Mobile preset',
    learn_skill_list: [['Existing']],
    learn_skill_blacklist: ['Blocked'],
  }
  mocks.getSkills.mockReset().mockResolvedValue({ success: true, skills })
  mocks.getActive.mockReset().mockImplementation(() => mocks.active)
  mocks.update.mockReset().mockImplementation((preset) => {
    mocks.active = preset
    return Promise.resolve()
  })
})

async function openCatalogue() {
  fireEvent.click(within(screen.getByRole('tablist')).getByRole('tab', { name: 'Catalogue' }))
  await screen.findByRole('button', { name: 'Alpha' })
}

describe('SkillEditorDialog responsive presentation', () => {
  it('uses mobile tabs that preserve catalogue state and desktop split-view classes', async () => {
    render(<SkillEditorDialog open onOpenChange={vi.fn()} />)

    const tablist = screen.getByRole('tablist', { name: 'Skill editor panels' })
    const listsTab = within(tablist).getByRole('tab', { name: 'Skill Lists' })
    const catalogueTab = within(tablist).getByRole('tab', { name: 'Catalogue' })
    const listsPanel = screen.getByTestId('skill-editor-lists-panel')
    const cataloguePanel = screen.getByTestId('skill-editor-catalogue-panel')

    expect(tablist).toHaveClass('md:hidden')
    expect(listsTab).toHaveAttribute('aria-selected', 'true')
    expect(listsPanel).toHaveClass('flex', 'md:flex', 'md:w-[44%]')
    expect(cataloguePanel).toHaveClass('hidden', 'md:flex')
    expect(
      document.querySelector('[data-slot="separator"][data-orientation="vertical"]'),
    ).toHaveClass('hidden', 'md:block')

    fireEvent.click(catalogueTab)
    const search = await screen.findByPlaceholderText('Search skills…')
    fireEvent.change(search, { target: { value: 'alp' } })
    fireEvent.click(screen.getByRole('button', { name: 'Front' }))

    fireEvent.click(listsTab)
    expect(listsPanel).toHaveClass('flex')
    expect(cataloguePanel).toHaveClass('hidden')

    fireEvent.click(catalogueTab)
    expect(screen.getByPlaceholderText('Search skills…')).toHaveValue('alp')
    expect(screen.getByRole('button', { name: 'Front' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('keeps add, remove, blacklist, clear, and tier flows working through the tabs', async () => {
    render(<SkillEditorDialog open onOpenChange={vi.fn()} />)
    await openCatalogue()

    fireEvent.click(screen.getByRole('button', { name: 'Alpha' }))
    expect(mocks.active.learn_skill_list[0]).toEqual(['Existing', 'Alpha'])

    fireEvent.click(screen.getByRole('button', { name: 'ADD ALL VISIBLE' }))
    expect(mocks.active.learn_skill_list[0]).toEqual(['Existing', 'Alpha', 'Beta'])

    fireEvent.click(screen.getByRole('button', { name: 'BLACKLIST ALL VISIBLE' }))
    expect(mocks.active.learn_skill_blacklist).toEqual(['Blocked', 'Alpha', 'Beta'])

    fireEvent.click(screen.getByRole('button', { name: 'REMOVE ALL VISIBLE' }))
    expect(mocks.active.learn_skill_list[0]).toEqual(['Existing'])

    fireEvent.click(within(screen.getByRole('tablist')).getByRole('tab', { name: 'Skill Lists' }))
    fireEvent.click(screen.getByRole('button', { name: 'Remove Existing' }))
    fireEvent.click(screen.getByRole('button', { name: 'Remove Blocked' }))
    expect(mocks.active.learn_skill_list[0]).toEqual([])
    expect(mocks.active.learn_skill_blacklist).toEqual(['Alpha', 'Beta'])

    fireEvent.click(screen.getByRole('button', { name: 'CLEAR' }))
    expect(mocks.active.learn_skill_blacklist).toEqual([])

    fireEvent.click(screen.getByRole('button', { name: '+ TIER' }))
    expect(mocks.active.learn_skill_list).toHaveLength(2)
    await waitFor(() => expect(screen.getAllByRole('button', { name: 'DEL' })).toHaveLength(2))
    fireEvent.click(screen.getAllByRole('button', { name: 'DEL' })[1])
    expect(mocks.active.learn_skill_list).toHaveLength(1)
  })

  it('gives tier, chip, filter, result, removal, and bulk controls mobile hit areas', async () => {
    render(<SkillEditorDialog open onOpenChange={vi.fn()} />)

    expect(document.querySelector('[data-slot="skill-tier"]')).toHaveClass('min-h-11', 'md:min-h-0')
    expect(document.querySelector('[data-slot="skill-chip"]')).toHaveClass('min-h-11', 'md:min-h-0')
    expect(screen.getByRole('button', { name: 'Remove Existing' })).toHaveClass('size-11', 'md:size-4')

    await openCatalogue()
    expect(document.querySelector('[data-slot="skill-filter"]')).toHaveClass('min-h-11', 'md:min-h-0')
    expect(document.querySelector('[data-slot="skill-result"]')).toHaveClass('min-h-11', 'md:min-h-0')
    expect(screen.getByRole('button', { name: 'ADD ALL VISIBLE' })).toHaveClass('h-11', 'md:h-7')
  })
})
