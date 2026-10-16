import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import BotConfiguration from './BotConfiguration'

const mocks = vi.hoisted(() => ({
  store: {
    config: { version: 1, scenarios: { '4': {} } },
    defaultConfig: { version: 1, scenarios: { '4': {} } },
    scenarios: [{ scenario_id: 4, name: 'Trackblazer', description: 'Scenario guidance' }],
    fields: {
      '4': [
        {
          key: 'enable_recovery',
          label: 'Use recovery',
          description: 'Allow recovery skills when stamina is low.',
          kind: 'boolean',
          default: false,
          category: 'Scoring',
        },
        {
          key: 'stamina_blue_purple_soul_stack_bonus_step',
          label: 'Weights JSON',
          description: 'A long description that remains readable on a phone instead of being clamped.',
          kind: 'object',
          default: { speed: 1 },
          category: 'Scoring',
        },
        {
          key: 'strategy_name',
          label: 'Strategy name',
          description: 'Decision strategy label.',
          kind: 'string',
          default: 'balanced',
          category: 'Decision',
        },
      ],
    },
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
}))

vi.mock('@/stores/botConfig', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/stores/botConfig')>()
  return { ...actual, useBotConfig: () => mocks.store }
})

beforeEach(() => {
  mocks.store.loading = false
  mocks.store.saving = false
  mocks.store.error = ''
  mocks.store.load.mockReset().mockResolvedValue(undefined)
  mocks.store.save.mockReset().mockResolvedValue(undefined)
  mocks.store.reset.mockReset().mockResolvedValue(undefined)
  mocks.store.selectScenario.mockReset()
  mocks.store.updateField.mockReset()
  mocks.store.isDirty.mockReset().mockReturnValue(false)
})

describe('BotConfiguration responsive form', () => {
  it('renders mobile accordion controls while every desktop section remains flat and available', async () => {
    render(<BotConfiguration />)
    await waitFor(() => expect(mocks.store.load).toHaveBeenCalled())

    const sections = screen.getByTestId('bot-config-sections')
    const scenario = screen.getByRole('combobox', { name: 'Scenario' })
    const scoring = screen.getByRole('button', { name: /Scoring/ })
    const decision = screen.getByRole('button', { name: /Decision/ })
    const scoringPanel = document.getElementById(scoring.getAttribute('aria-controls')!)!
    const decisionPanel = document.getElementById(decision.getAttribute('aria-controls')!)!

    expect(sections).toHaveAttribute('data-mobile-layout', 'accordion')
    expect(sections).toHaveAttribute('data-desktop-layout', 'flat')
    expect(sections.contains(scenario)).toBe(false)
    expect(scenario).toHaveClass('w-full', 'md:w-[280px]')
    expect(scoring).toHaveClass('md:hidden')
    expect(scoring).toHaveAttribute('aria-expanded', 'true')
    expect(scoringPanel).toHaveClass('block', 'md:block')
    expect(decisionPanel).toHaveClass('hidden', 'md:block')
    expect(within(scoringPanel).getByLabelText('Use recovery')).toBeInTheDocument()
    expect(within(decisionPanel).getByLabelText('Strategy name')).toBeInTheDocument()

    fireEvent.click(decision)
    expect(scoring).toHaveAttribute('aria-expanded', 'false')
    expect(decision).toHaveAttribute('aria-expanded', 'true')
    expect(scoringPanel).toHaveClass('hidden', 'md:block')
    expect(decisionPanel).toHaveClass('block', 'md:block')
    expect(screen.getByRole('combobox', { name: 'Scenario' })).toBeInTheDocument()
  })

  it('toggles boolean controls from their TouchControlRow label and exposes disabled reasons as text', () => {
    const { rerender } = render(<BotConfiguration />)
    const touchRow = document.querySelector<HTMLElement>('[data-slot="touch-control-row"]')!
    const checkbox = within(touchRow).getByRole('checkbox', { name: 'Use recovery' })

    fireEvent.click(within(touchRow).getByText('Use recovery'))
    expect(mocks.store.updateField).toHaveBeenCalledWith('enable_recovery', true)

    mocks.store.saving = true
    rerender(<BotConfiguration />)
    const disabledRow = document.querySelector<HTMLElement>('[data-slot="touch-control-row"]')!
    expect(within(disabledRow).getByText('Saving is in progress.')).toBeInTheDocument()
    expect(within(disabledRow).getByRole('checkbox', { name: 'Use recovery' })).toBeDisabled()
    expect(disabledRow).not.toHaveAttribute('title')
    expect(checkbox).not.toHaveAttribute('title')
  })

  it('keeps JSON text at 16px on mobile and wraps mobile metadata/default actions only', () => {
    render(<BotConfiguration />)

    const jsonInput = screen.getByRole('textbox', { name: 'Weights JSON' })
    const longKey = screen.getByText('stamina_blue_purple_soul_stack_bonus_step')
    const fieldRow = longKey.closest<HTMLElement>('[data-slot="bot-config-field-row"]')!
    const editorActions = fieldRow.lastElementChild as HTMLElement

    expect(jsonInput).toHaveClass('text-base', 'md:text-xs')
    expect(longKey).toHaveClass('break-all', 'md:break-normal')
    expect(within(fieldRow).getByText(/A long description/)).toHaveClass('md:line-clamp-3')
    expect(editorActions).toHaveClass('flex-col', 'md:flex-row')
    expect(within(fieldRow).getByRole('button', { name: 'Default' })).toHaveClass('w-full', 'md:w-auto')
  })
})
