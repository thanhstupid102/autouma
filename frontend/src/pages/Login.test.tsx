import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import Login from './Login'
import type { SessionData } from '@/api/types'

vi.mock('qrcode', () => ({
  default: { toDataURL: vi.fn().mockResolvedValue('data:image/png;base64,MOCK') },
}))

vi.mock('@/api/auth', () => ({
  login: vi.fn(),
  qrStart: vi.fn(),
  qrPoll: vi.fn(),
  transitionCodeChain: vi.fn(),
}))

import * as authModule from '@/api/auth'

function makeQueryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } })
}

function renderLogin(queryClient = makeQueryClient(), forceSteamLogin = false) {
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/account/main']}>
        <Login forceSteamLogin={forceSteamLogin} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  vi.mocked(authModule.qrStart).mockResolvedValue({ challenge_url: 'steam://x' })
  vi.mocked(authModule.qrPoll).mockResolvedValue({ status: 'pending' })
})

describe('Login state routing', () => {
  it('shows Steam entry choices only after needs_steam_login', async () => {
    let resolveLogin!: (result: SessionData) => void
    vi.mocked(authModule.login).mockReturnValue(new Promise((resolve) => {
      resolveLogin = resolve
    }))

    renderLogin()

    const checkingMessage = screen.getByText(/checking the saved steam session/i)
    expect(checkingMessage).toBeInTheDocument()
    expect(checkingMessage.closest('.min-h-dvh')).toBeInTheDocument()
    expect(authModule.login).toHaveBeenCalledWith({})
    expect(authModule.qrStart).not.toHaveBeenCalled()

    await act(async () => resolveLogin({
      success: false,
      state: 'needs_steam_login',
    }))

    await waitFor(() => expect(authModule.qrStart).toHaveBeenCalledOnce())
    expect(await screen.findByText(/scan with the steam mobile app/i)).toBeInTheDocument()
  })

  it('invalidates the session for authenticated state', async () => {
    const queryClient = makeQueryClient()
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries')
    vi.mocked(authModule.login).mockResolvedValue({
      success: true,
      state: 'authenticated',
    })

    renderLogin(queryClient)

    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ['session'] }))
    expect(authModule.qrStart).not.toHaveBeenCalled()
  })

  it('renders the Trainer-ID panel for needs_transition_link', async () => {
    vi.mocked(authModule.login).mockResolvedValue({
      success: false,
      state: 'needs_transition_link',
    })

    renderLogin()

    expect(await screen.findByText(/link an existing trainer account/i)).toBeInTheDocument()
    expect(authModule.qrStart).not.toHaveBeenCalled()
  })

  it('passes removed-link reason and stored viewer id into the Trainer-ID panel', async () => {
    vi.mocked(authModule.login).mockResolvedValue({
      success: false,
      state: 'needs_transition_link',
      reason: 'steam_link_removed',
      viewer_id: '229594617236',
    })

    renderLogin(makeQueryClient(), true)

    expect(await screen.findByText(/uma link removed/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/trainer id/i)).toHaveValue('229594617236')
    expect(authModule.qrStart).not.toHaveBeenCalled()
  })

  it('reveals the Guard field for needs_steam_guard', async () => {
    vi.mocked(authModule.login).mockResolvedValue({
      success: false,
      state: 'needs_steam_guard',
    })

    renderLogin()

    expect(await screen.findByLabelText(/steam guard code/i)).toBeInTheDocument()
  })

  it('maps a failed symbolic code without offering Steam entry panels', async () => {
    vi.mocked(authModule.login).mockResolvedValue({
      success: false,
      state: 'failed',
      error_code: 'PC_ACCOUNT_LIMIT_ERROR',
      detail: 'raw detail',
    })

    renderLogin()

    expect(await screen.findByText(/reached the PC account link limit/i)).toBeInTheDocument()
    expect(screen.queryByText(/use password instead/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/scan with steam mobile/i)).not.toBeInTheDocument()
    expect(authModule.qrStart).not.toHaveBeenCalled()
  })

  it('explains when Steam account creation is disabled', async () => {
    vi.mocked(authModule.login).mockResolvedValue({
      success: false,
      state: 'steam_signup_disabled',
    })

    renderLogin()

    expect(await screen.findByText(
      /a new account cannot be created here/i,
    )).toBeInTheDocument()
    expect(screen.getByText(/import an existing account bundle/i)).toBeInTheDocument()
    expect(screen.getByText(/official game client/i)).toBeInTheDocument()
    expect(authModule.qrStart).not.toHaveBeenCalled()
  })

  it('checks the saved session during re-establishment before showing QR', async () => {
    let resolveLogin!: (result: SessionData) => void
    vi.mocked(authModule.login).mockReturnValue(new Promise((resolve) => {
      resolveLogin = resolve
    }))

    renderLogin(makeQueryClient(), true)

    expect(screen.getByText(/checking the saved steam session/i)).toBeInTheDocument()
    expect(authModule.login).toHaveBeenCalledWith({})
    expect(authModule.qrStart).not.toHaveBeenCalled()

    await act(async () => resolveLogin({
      success: false,
      state: 'needs_steam_login',
    }))
    await waitFor(() => expect(authModule.qrStart).toHaveBeenCalledOnce())
  })
})

describe('Login Steam entry points', () => {
  async function reachQr() {
    vi.mocked(authModule.login).mockResolvedValueOnce({
      success: false,
      state: 'needs_steam_login',
    })
    renderLogin()
    await screen.findByText(/use password instead/i)
  }

  it('switches from QR to typed Steam credentials', async () => {
    await reachQr()

    fireEvent.click(screen.getByText(/use password instead/i))

    expect(screen.getByLabelText(/username/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/^password$/i)).toBeInTheDocument()
  })

  it('submits no prefer_password remnant and handles typed Guard state', async () => {
    await reachQr()
    fireEvent.click(screen.getByText(/use password instead/i))
    vi.mocked(authModule.login).mockResolvedValue({
      success: false,
      state: 'needs_steam_guard',
    })
    fireEvent.change(screen.getByLabelText(/username/i), { target: { value: 'steam-user' } })
    fireEvent.change(screen.getByLabelText(/^password$/i), { target: { value: 'steam-pass' } })

    fireEvent.submit(screen.getByLabelText(/username/i).closest('form')!)

    await waitFor(() => expect(authModule.login).toHaveBeenLastCalledWith({
      username: 'steam-user',
      password: 'steam-pass',
      code: undefined,
    }, undefined))
    expect(await screen.findByLabelText(/steam guard code/i)).toBeInTheDocument()
  })

  it('moves typed Steam login into transition linking when requested', async () => {
    await reachQr()
    fireEvent.click(screen.getByText(/use password instead/i))
    vi.mocked(authModule.login).mockResolvedValue({
      success: false,
      state: 'needs_transition_link',
    })

    fireEvent.submit(screen.getByLabelText(/username/i).closest('form')!)

    expect(await screen.findByText(/link an existing trainer account/i)).toBeInTheDocument()
  })
})
