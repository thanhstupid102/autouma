import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { leaveSession } from '@/api/auth'
import AccountFooter from './AccountFooter'

vi.mock('@/api/auth', () => ({
  leaveSession: vi.fn().mockResolvedValue({ success: true }),
  refreshSession: vi.fn().mockResolvedValue({ success: true }),
}))

vi.mock('@/lib/theme', () => ({
  getTheme: () => 'light',
  toggleTheme: () => 'dark',
}))

vi.mock('sonner', () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}))

function LocationProbe() {
  return <span data-testid="location">{useLocation().pathname}</span>
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('AccountFooter leave session', () => {
  it('calls the renamed leave-session action and returns to login', async () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={['/account/yuko']}>
          <AccountFooter />
          <LocationProbe />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    expect(screen.getByRole('button', { name: 'Switch to dark mode' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Refresh session' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Leave session' }))

    await waitFor(() => expect(leaveSession).toHaveBeenCalledTimes(1))
    await waitFor(() => {
      expect(screen.getByTestId('location')).toHaveTextContent('/login')
    })
  })
})
