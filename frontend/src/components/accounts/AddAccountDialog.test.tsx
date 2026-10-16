import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import AddAccountDialog from './AddAccountDialog'

vi.mock('qrcode', () => ({
  default: { toDataURL: vi.fn().mockResolvedValue('data:image/png;base64,MOCK') },
}))

vi.mock('@/api/auth', () => ({
  login: vi.fn().mockResolvedValue({ success: false, state: 'failed' }),
  qrStart: vi.fn().mockResolvedValue({ challenge_url: 'steam://x' }),
  qrPoll: vi.fn().mockResolvedValue({ status: 'pending' }),
  transitionCodeChain: vi.fn(),
}))

import * as authModule from '@/api/auth'

function renderDialog() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <AddAccountDialog />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('AddAccountDialog', () => {
  it('offers only Steam QR or password entry and no capture UI', () => {
    renderDialog()
    fireEvent.click(screen.getByRole('button', { name: /add account/i }))

    expect(screen.getByLabelText(/account name/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /use steam qr/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /use steam password/i })).toBeInTheDocument()
    expect(screen.queryByText(/capture|launch the game|viewer_id/i)).not.toBeInTheDocument()
  })

  it('starts typed Steam login for the sanitized target account', async () => {
    renderDialog()
    fireEvent.click(screen.getByRole('button', { name: /add account/i }))
    fireEvent.change(screen.getByLabelText(/account name/i), {
      target: { value: 'main acct!' },
    })
    fireEvent.click(screen.getByRole('button', { name: /use steam password/i }))
    fireEvent.change(screen.getByLabelText(/username/i), { target: { value: 'steam-user' } })
    fireEvent.change(screen.getByLabelText(/^password$/i), { target: { value: 'steam-pass' } })

    await act(async () => {
      fireEvent.submit(screen.getByLabelText(/username/i).closest('form')!)
    })

    expect(authModule.login).toHaveBeenCalledWith({
      username: 'steam-user',
      password: 'steam-pass',
      code: undefined,
    }, 'main_acct_')
  })

  it('moves from Steam QR to the Trainer-ID panel when linking is required', async () => {
    vi.useFakeTimers()
    vi.mocked(authModule.qrPoll).mockResolvedValue({ status: 'confirmed' })
    vi.mocked(authModule.login).mockResolvedValue({
      success: false,
      state: 'needs_transition_link',
    })
    renderDialog()
    fireEvent.click(screen.getByRole('button', { name: /add account/i }))
    fireEvent.change(screen.getByLabelText(/account name/i), { target: { value: 'alt' } })
    fireEvent.click(screen.getByRole('button', { name: /use steam qr/i }))

    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
      await vi.advanceTimersByTimeAsync(2000)
    })

    expect(screen.getByText(/link an existing trainer account/i)).toBeInTheDocument()
  })
})
