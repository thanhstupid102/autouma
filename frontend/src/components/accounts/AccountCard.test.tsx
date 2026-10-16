import { fireEvent, render, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, useLocation } from 'react-router-dom'
import AccountCard from './AccountCard'
import type { AccountSnapshot } from '@/stores/account'
import { useAccountStore } from '@/stores/account'

vi.mock('sonner', () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}))

function makeAccount(overrides: Partial<AccountSnapshot> = {}): AccountSnapshot {
  return {
    name: 'main',
    logged_in: true,
    running: false,
    loop_active: false,
    account: {},
    runner: null,
    ...overrides,
  }
}

function LocationProbe() {
  const location = useLocation()
  return (
    <div data-testid="location">
      {location.pathname}|{JSON.stringify(location.state)}
    </div>
  )
}

function renderCard(acc = makeAccount()) {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <AccountCard acc={acc} />
        <LocationProbe />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  useAccountStore.setState({ selected: '' })
})

describe('AccountCard re-establish', () => {
  it('routes to the account re-establishment check', () => {
    renderCard()

    fireEvent.click(screen.getByRole('button', { name: /re-establish/i }))

    expect(useAccountStore.getState().selected).toBe('main')
    expect(screen.getByTestId('location')).toHaveTextContent(
      '/account/main|{"forceSteamLogin":true}',
    )
  })

  it('shows a shared active-run reason once beneath the controls', () => {
    renderCard(makeAccount({ running: true }))

    const actions = screen.getByTestId('account-actions')
    const reasons = screen.getByTestId('account-blocked-reasons')

    expect(screen.getByRole('button', { name: /re-establish/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /remove uma link/i })).toBeDisabled()
    expect(reasons).toHaveTextContent('Stop the run before changing this account.')
    expect(reasons.querySelectorAll('p')).toHaveLength(1)
    expect(reasons.previousElementSibling).toBe(actions)
    expect(within(actions).queryByText(/stop the run before/i)).not.toBeInTheDocument()
    expect(reasons.querySelector('p')).not.toHaveAttribute('title')
  })

  it('keeps distinct disabled reasons when more than one condition applies', () => {
    renderCard(makeAccount({ running: true, logged_in: false }))

    const reasons = screen.getByTestId('account-blocked-reasons')

    expect(reasons).toHaveTextContent('Stop the run before changing this account.')
    expect(reasons).toHaveTextContent('Log in before removing the Uma link.')
    expect(reasons.querySelectorAll('p')).toHaveLength(2)
  })

  it('keeps Steam actions available when an advisory unbind marker exists', () => {
    renderCard(makeAccount({ steam_unbound_at: 1234567890 }))

    expect(screen.getByText('Uma link removed; reauth to check')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /re-establish/i })).toBeEnabled()
    expect(screen.getByRole('button', { name: /remove uma link/i })).toBeEnabled()
  })
})

describe('AccountCard mobile actions', () => {
  it('places every account action in a full-width responsive action section', () => {
    renderCard()

    const actions = screen.getByTestId('account-actions')
    expect(actions).toHaveClass('grid', 'w-full', 'grid-cols-1', 'sm:flex', 'sm:flex-wrap')
    expect(within(actions).getByRole('button', { name: /^open/i })).toBeInTheDocument()
    expect(within(actions).getByRole('button', { name: /re-establish/i })).toBeInTheDocument()
    expect(within(actions).getByRole('button', { name: /remove uma link/i })).toBeInTheDocument()
    expect(within(actions).getByRole('button', { name: /delete main/i })).toBeInTheDocument()
    expect(within(actions).getByRole('button', { name: /^open/i })).toHaveClass('w-full', 'sm:w-24')

    const card = screen.getByText('main').closest('[data-slot="card"]')
    const content = card?.querySelector('[data-slot="card-content"]')
    expect(card).toHaveClass('h-full')
    expect(content).toHaveClass('h-full')
  })

  it('does not navigate the card when destructive or secondary actions are activated', () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    renderCard()

    fireEvent.click(screen.getByRole('button', { name: /delete main/i }))
    expect(screen.getByTestId('location')).toHaveTextContent('/|null')

    fireEvent.click(screen.getByRole('button', { name: /remove uma link/i }))
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByTestId('location')).toHaveTextContent('/|null')
  })
})

describe('AccountCard leading action', () => {
  it.each([
    ['Open', makeAccount()],
    ['Pause', makeAccount({ running: true })],
    ['Resume', makeAccount({ loop_active: true })],
  ])('uses the outline presentation for %s', (label, acc) => {
    const { unmount } = renderCard(acc)

    expect(screen.getByRole('button', { name: new RegExp(`^${label}`, 'i') }))
      .toHaveAttribute('data-variant', 'outline')

    unmount()
  })
})
