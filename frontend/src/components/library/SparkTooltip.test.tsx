import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { SparkTooltip } from './SparkTooltip'

function setFinePointer(matches: boolean) {
  const mediaQuery = {
    matches,
    media: '(hover: hover) and (pointer: fine)',
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  } satisfies MediaQueryList
  vi.stubGlobal('matchMedia', vi.fn(() => mediaQuery))
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('SparkTooltip', () => {
  it('opens explicit spark details on touch and renders only the parent lineage', () => {
    setFinePointer(false)
    render(
      <SparkTooltip tree={{
        self: { name: 'Oguri Cap', factors: [{ name: 'Stamina', stars: 3, category: 'stat' }] },
        p1: { name: 'Gold Ship', factors: [{ name: 'Medium', stars: 2, category: 'aptitude' }] },
        p2: { name: 'Tokai Teio', factors: [{ name: 'Triumphant Pulse', stars: 2, category: 'unique' }] },
        gp1: { name: 'Hidden Grandparent', factors: [{ name: 'Speed', stars: 3, category: 'stat' }] },
      }}>
        <button type="button">Parent</button>
      </SparkTooltip>,
    )

    const trigger = screen.getByRole('button', { name: 'Spark details' })
    expect(trigger.closest('[data-mode="touch"]')).toBeInTheDocument()
    fireEvent.click(trigger)

    const panel = screen.getByRole('dialog', { name: 'Spark details' })
    expect(panel).toBeInTheDocument()
    expect(panel).toHaveClass('bg-popover', 'p-0')
    expect(panel).not.toHaveClass('border', 'p-4', 'shadow-lg')
    expect(screen.getByText('Self: Oguri Cap')).toBeInTheDocument()
    expect(screen.getByText('Parent 1: Gold Ship')).toBeInTheDocument()
    expect(screen.getByText('Parent 2: Tokai Teio')).toBeInTheDocument()
    expect(screen.getByText('Stamina')).toBeInTheDocument()
    expect(screen.getByText('Medium')).toBeInTheDocument()
    expect(screen.getByText('Triumphant Pulse')).toBeInTheDocument()
    expect(screen.queryByText('Grandparent 1: Hidden Grandparent')).not.toBeInTheDocument()
    expect(screen.getByText('★★★')).toBeInTheDocument()
  })

  it('does not show false No spark data rows for identity-only parent nodes', () => {
    setFinePointer(false)
    render(
      <SparkTooltip tree={{
        self: { name: 'Self Uma', factors: [{ name: 'Speed', stars: 3, category: 'stat' }] },
        p1: { card_id: 200001, name: 'Parent One', factors: [] },
        p2: { card_id: 200002, name: 'Parent Two' },
        gp1: { card_id: 300001, name: 'Grandparent One', factors: [] },
      }}>
        <button type="button">Parent</button>
      </SparkTooltip>,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Spark details' }))

    expect(screen.getByText('Parent 1: Parent One')).toBeInTheDocument()
    expect(screen.getByText('Parent 2: Parent Two')).toBeInTheDocument()
    expect(screen.queryByText('Grandparent 1: Grandparent One')).not.toBeInTheDocument()
    expect(screen.queryByText('No spark data')).not.toBeInTheDocument()
  })

  it('keeps the wrapped card as the working tooltip trigger on a fine pointer', async () => {
    setFinePointer(true)
    render(
      <SparkTooltip tree={{
        self: { name: 'Oguri Cap', factors: [{ name: 'Stamina', stars: 3, category: 'stat' }] },
      }}>
        <button type="button">Parent</button>
      </SparkTooltip>,
    )

    const card = screen.getByRole('button', { name: 'Parent' })
    expect(card.closest('[data-mode="fine"]')).toBeInTheDocument()
    expect(card).toHaveAttribute('data-slot', 'tooltip-trigger')
    expect(screen.queryByRole('button', { name: 'Spark details' })).not.toBeInTheDocument()

    fireEvent.pointerMove(card, { pointerType: 'mouse' })
    const tooltip = await screen.findByRole('tooltip')
    const tooltipContent = document.querySelector('[data-slot="tooltip-content"]')!
    expect(tooltip).toHaveTextContent('Self: Oguri Cap')
    expect(tooltipContent).toHaveClass('bg-popover', 'p-0', 'text-popover-foreground')
    expect(tooltipContent).not.toHaveClass('bg-foreground', 'px-3', 'py-1.5')
  })
})
