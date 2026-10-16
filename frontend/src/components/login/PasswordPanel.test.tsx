import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import PasswordPanel from './PasswordPanel'

vi.mock('@/api/auth', () => ({ login: vi.fn() }))

import * as authModule from '@/api/auth'

function renderPanel(
  account?: string,
  props: Partial<React.ComponentProps<typeof PasswordPanel>> = {},
) {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <PasswordPanel onBackToQr={vi.fn()} account={account} {...props} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.restoreAllMocks()
  vi.clearAllMocks()
  localStorage.clear()
})

describe('PasswordPanel', () => {
  it('uses the shared touch-sized button for returning to QR login', () => {
    renderPanel()

    expect(screen.getByRole('button', { name: /back to qr/i })).toHaveClass(
      'h-11',
      'md:h-8',
      'w-full',
    )
  })

  it('clears the legacy password and never persists submitted credentials', async () => {
    vi.mocked(authModule.login).mockResolvedValue({ success: true, state: 'authenticated' })
    localStorage.setItem('saved_username', 'remembered-user')
    localStorage.setItem('saved_password', 'legacy-password')
    const setItem = vi.spyOn(Storage.prototype, 'setItem')

    renderPanel()

    expect(screen.getByLabelText(/username/i)).toHaveValue('remembered-user')
    expect(screen.getByLabelText(/^password$/i)).toHaveValue('')
    expect(localStorage.getItem('saved_password')).toBeNull()

    fireEvent.change(screen.getByLabelText(/^password$/i), { target: { value: 'new-password' } })
    fireEvent.submit(screen.getByLabelText(/username/i).closest('form')!)

    await waitFor(() => expect(authModule.login).toHaveBeenCalled())
    expect(setItem).not.toHaveBeenCalled()
    expect(localStorage.getItem('saved_password')).toBeNull()
  })

  it('forwards only typed Steam fields and the target account', async () => {
    vi.mocked(authModule.login).mockResolvedValue({ success: false, state: 'failed' })
    renderPanel('new_acct')

    fireEvent.change(screen.getByLabelText(/username/i), { target: { value: 'steam-user' } })
    fireEvent.change(screen.getByLabelText(/^password$/i), { target: { value: 'steam-pass' } })
    fireEvent.submit(screen.getByLabelText(/username/i).closest('form')!)

    await waitFor(() => expect(authModule.login).toHaveBeenCalledWith({
      username: 'steam-user',
      password: 'steam-pass',
      code: undefined,
    }, 'new_acct'))
    expect(screen.queryByText(/recapture|captured auth/i)).not.toBeInTheDocument()
  })

  it('reveals Steam Guard for the discriminated state', async () => {
    vi.mocked(authModule.login).mockResolvedValue({
      success: false,
      state: 'needs_steam_guard',
    })
    renderPanel()

    fireEvent.submit(screen.getByLabelText(/username/i).closest('form')!)

    expect(await screen.findByLabelText(/steam guard code/i)).toBeInTheDocument()
  })

  it('hands transition-link state to the parent flow', async () => {
    const onNeedsTransitionLink = vi.fn()
    vi.mocked(authModule.login).mockResolvedValue({
      success: false,
      state: 'needs_transition_link',
    })
    renderPanel(undefined, { onNeedsTransitionLink })

    fireEvent.submit(screen.getByLabelText(/username/i).closest('form')!)

    await waitFor(() => expect(onNeedsTransitionLink).toHaveBeenCalledOnce())
  })
})
