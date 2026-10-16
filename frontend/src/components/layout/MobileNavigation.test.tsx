import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { storeApiToken } from '@/api/apiToken'
import { useAccountStore } from '@/stores/account'
import MobileNavigation from './MobileNavigation'

vi.mock('@/hooks/useAccounts', () => ({
  useAccounts: vi.fn(),
}))

vi.mock('@/api/auth', () => ({
  leaveSession: vi.fn().mockResolvedValue({ success: true }),
  refreshSession: vi.fn().mockResolvedValue({ success: true }),
}))

vi.mock('@/lib/theme', () => ({
  getTheme: () => 'light',
  toggleTheme: () => 'dark',
}))

vi.mock('sonner', () => ({
  toast: { error: vi.fn(), info: vi.fn(), success: vi.fn() },
}))

function LocationProbe() {
  return <span data-testid="location">{useLocation().pathname}</span>
}

function renderNavigation(initialEntry = '/account/Yuko/setup') {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <MobileNavigation />
        <LocationProbe />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  useAccountStore.setState({
    selected: 'Yuko',
    accounts: [
      {
        name: 'Yuko',
        logged_in: true,
        running: true,
        loop_active: true,
        account: null,
        runner: null,
      },
      {
        name: 'Special Week',
        logged_in: true,
        running: false,
        loop_active: false,
        account: null,
        runner: null,
      },
    ],
  })
  storeApiToken('operator-secret')
})

describe('MobileNavigation', () => {
  it('keeps the four mid-session routes in the bottom bar and the remaining routes in the drawer', () => {
    renderNavigation()

    const primaryNav = screen.getByRole('navigation', { name: 'Mobile primary navigation' })
    expect(within(primaryNav).getByRole('link', { name: 'Dashboard' })).toBeInTheDocument()
    expect(within(primaryNav).getByRole('link', { name: 'Setup' })).toBeInTheDocument()
    expect(within(primaryNav).getByRole('link', { name: 'Library' })).toBeInTheDocument()
    expect(within(primaryNav).getByRole('link', { name: 'Events' })).toBeInTheDocument()
    expect(within(primaryNav).queryByRole('link', { name: 'Settings' })).not.toBeInTheDocument()

    fireEvent.click(within(primaryNav).getByRole('button', { name: 'More' }))

    const drawer = screen.getByRole('dialog')
    expect(within(drawer).getByRole('link', { name: 'Accounts' })).toBeInTheDocument()
    expect(within(drawer).getByRole('link', { name: 'Bot Configuration' })).toBeInTheDocument()
    expect(within(drawer).getByRole('link', { name: 'Settings' })).toBeInTheDocument()
    expect(within(drawer).getByRole('link', { name: 'Yuko' })).toBeInTheDocument()
    expect(within(drawer).getByRole('link', { name: 'Special Week' })).toBeInTheDocument()
  })

  it('shows visible, accessible labels for every account-footer action in the drawer', () => {
    renderNavigation()
    fireEvent.click(screen.getByRole('button', { name: 'More' }))

    const drawer = screen.getByRole('dialog')
    for (const label of [
      'Switch to dark mode',
      'Refresh session',
      'Forget API token',
      'Leave session',
    ]) {
      const action = within(drawer).getByRole('button', { name: label })
      expect(action).toHaveTextContent(label)
    }
  })

  it('navigates from both surfaces and closes the drawer after drawer navigation', async () => {
    renderNavigation()

    fireEvent.click(screen.getByRole('link', { name: 'Events' }))
    expect(screen.getByTestId('location')).toHaveTextContent('/account/Yuko/events')

    fireEvent.click(screen.getByRole('button', { name: 'More' }))
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('link', { name: 'Settings' }))

    expect(screen.getByTestId('location')).toHaveTextContent('/account/Yuko/settings')
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('gives every bottom-bar and drawer control the 44px touch-height contract', () => {
    renderNavigation()

    const primaryNav = screen.getByRole('navigation', { name: 'Mobile primary navigation' })
    for (const control of primaryNav.querySelectorAll('a, button')) {
      expect(control).toHaveClass('min-h-11')
    }

    fireEvent.click(within(primaryNav).getByRole('button', { name: 'More' }))
    const drawer = screen.getByRole('dialog')
    for (const control of drawer.querySelectorAll('a, button')) {
      expect(control).toHaveClass('min-h-11')
    }
  })
})
