import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { toast } from 'sonner'
import App from './App'
import { apiJson } from './api/client'
import { API_TOKEN_STORAGE_KEY, storeApiToken } from './api/apiToken'

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock('./api/auth', () => ({
  getSession: vi.fn(),
  refreshSession: vi.fn(),
  leaveSession: vi.fn(),
  login: vi.fn(),
  qrStart: vi.fn(),
  qrPoll: vi.fn(),
  transitionCodeChain: vi.fn(),
}))

vi.mock('./api/accounts', () => ({
  listAccounts: vi.fn().mockResolvedValue({ success: true, accounts: [] }),
  deleteAccount: vi.fn(),
  exportAccounts: vi.fn(),
  importAccounts: vi.fn(),
}))

vi.mock('./api/authGate', () => ({
  getAuthGateStatus: vi.fn(),
}))

import * as authModule from './api/auth'
import * as accountsModule from './api/accounts'
import * as authGateModule from './api/authGate'

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function renderApp() {
  const qc = makeQueryClient()
  return render(
    <QueryClientProvider client={qc}>
      <App />
    </QueryClientProvider>
  )
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  vi.mocked(authGateModule.getAuthGateStatus).mockResolvedValue({ gate_required: false })
})

describe('App routing (no global login gate)', () => {
  it('renders Overview (Accounts heading) at "/" regardless of session state', async () => {
    // Even when session returns success:false, the Overview should be shown
    vi.mocked(authModule.getSession).mockResolvedValue({ success: false })

    renderApp()

    // The index route renders Overview which has an "Accounts" heading.
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /accounts/i })).toBeInTheDocument()
    })

    expect(screen.getByTestId('overview-header')).toHaveClass('flex-col', 'sm:flex-row')
    expect(screen.getByTestId('overview-actions')).toHaveClass(
      'w-full',
      'flex-wrap',
      'sm:w-auto',
    )
  })

  it('also renders Overview when session returns success:true', async () => {
    vi.mocked(authModule.getSession).mockResolvedValue({
      success: true,
      account: {
        tp: { current: 100, max: 120 },
        carrots: { total: 50 },
        gold: 9999,
        clocks: 3,
        career: { active: false },
      },
    })

    renderApp()

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /accounts/i })).toBeInTheDocument()
    })
  })

  it('uses mutually exclusive responsive shell navigation and reserves safe-area space on mobile', async () => {
    vi.mocked(authModule.getSession).mockResolvedValue({ success: false })

    renderApp()

    await screen.findByRole('heading', { name: /accounts/i })
    const shell = screen.getByTestId('app-shell')
    const sidebar = screen.getByTestId('desktop-sidebar')
    const mobileNavigation = screen.getByTestId('mobile-navigation')
    const main = shell.querySelector('main')

    expect(shell).toHaveClass('h-dvh')
    expect(sidebar).toHaveClass('hidden', 'md:flex', 'h-dvh')
    expect(mobileNavigation).toHaveClass('md:hidden')
    expect(main).toHaveClass(
      'min-w-0',
      'w-full',
      'pb-[calc(4rem+env(safe-area-inset-bottom))]',
      'md:w-auto',
      'md:pb-0',
    )
  })
})

describe('API token gate', () => {
  it('shows token entry instead of the dashboard when the gate is active and no token is stored', async () => {
    vi.mocked(authGateModule.getAuthGateStatus).mockResolvedValue({ gate_required: true })

    renderApp()

    expect(await screen.findByText('API token required')).toBeInTheDocument()
    expect(screen.getByRole('main')).toHaveClass('min-h-dvh')
    expect(screen.getByLabelText('API token')).toHaveAttribute('type', 'text')
    expect(screen.getByLabelText('API token')).toHaveAttribute('autocomplete', 'new-password')
    expect(screen.getByLabelText('API token')).toHaveAttribute('id', 'dashboard-access-code')
    expect(screen.getByLabelText('API token')).toHaveAttribute('name', 'dashboard-access-code')
    expect(screen.getByLabelText('API token')).toHaveClass(
      'h-11',
      'md:h-8',
      'text-base',
      'md:text-sm',
      '[-webkit-text-security:disc]',
    )
    expect(screen.getByLabelText('API token')).not.toHaveClass('text-transparent', 'caret-foreground')
    expect(screen.getByRole('button', { name: 'Show API token' })).toHaveClass(
      'size-11',
      'md:size-8',
    )
    expect(screen.getByRole('button', { name: 'Unlock dashboard' })).toHaveClass(
      'h-11',
      'md:h-8',
    )
    expect(accountsModule.listAccounts).not.toHaveBeenCalled()
  })

  it('reveals and masks the token with a keyboard-reachable stateful toggle', async () => {
    vi.mocked(authGateModule.getAuthGateStatus).mockResolvedValue({ gate_required: true })
    renderApp()

    const input = await screen.findByLabelText('API token')
    const toggle = screen.getByRole('button', { name: 'Show API token' })
    fireEvent.change(input, { target: { value: 'operator-secret' } })

    expect(input).toHaveClass('[-webkit-text-security:disc]')
    expect(input).not.toHaveClass('text-transparent', 'caret-foreground')
    expect(input.parentElement?.children).toHaveLength(2)
    expect(screen.queryByText('***************')).not.toBeInTheDocument()
    expect(toggle).toHaveAttribute('aria-pressed', 'false')
    toggle.focus()
    expect(toggle).toHaveFocus()

    fireEvent.click(toggle)

    expect(input).not.toHaveClass('[-webkit-text-security:disc]', 'text-transparent', 'caret-foreground')
    expect(screen.getByRole('button', { name: 'Hide API token' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.queryByText('***************')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Hide API token' }))

    expect(input).toHaveClass('[-webkit-text-security:disc]')
    expect(input).not.toHaveClass('text-transparent', 'caret-foreground')
    expect(screen.getByRole('button', { name: 'Show API token' })).toHaveAttribute('aria-pressed', 'false')
    expect(screen.queryByText('***************')).not.toBeInTheDocument()
  })

  it('trims a pasted trailing newline before unlocking and sending the token', async () => {
    vi.mocked(authGateModule.getAuthGateStatus).mockResolvedValue({ gate_required: true })
    vi.mocked(authModule.getSession).mockResolvedValue({ success: false })
    renderApp()

    fireEvent.change(await screen.findByLabelText('API token'), {
      target: { value: 'operator-secret\n' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Unlock dashboard' }))

    expect(await screen.findByRole('heading', { name: /accounts/i })).toBeInTheDocument()
    expect(localStorage.getItem(API_TOKEN_STORAGE_KEY)).toBe('operator-secret')

    const fetchMock = vi.fn().mockResolvedValue(new Response('{"success":true}'))
    vi.stubGlobal('fetch', fetchMock)
    await act(async () => {
      await apiJson('/api/probe')
    })
    expect(fetchMock).toHaveBeenCalledWith('/api/probe', expect.objectContaining({
      headers: { Authorization: 'Bearer operator-secret' },
    }))

    fireEvent.click(screen.getByRole('button', { name: 'Forget API token' }))

    expect(await screen.findByText('API token required')).toBeInTheDocument()
    expect(localStorage.getItem(API_TOKEN_STORAGE_KEY)).toBeNull()
  })

  it('leaves whitespace-only input at the token screen without reporting a rejection', async () => {
    vi.mocked(authGateModule.getAuthGateStatus).mockResolvedValue({ gate_required: true })
    const toastError = vi.spyOn(toast, 'error')
    renderApp()

    fireEvent.change(await screen.findByLabelText('API token'), {
      target: { value: ' \n\t ' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Unlock dashboard' }))

    expect(screen.getByText('API token required')).toBeInTheDocument()
    expect(localStorage.getItem(API_TOKEN_STORAGE_KEY)).toBeNull()
    expect(toastError).toHaveBeenCalledWith('Enter the API token configured on the server.')
    expect(toastError).not.toHaveBeenCalledWith('The API token was rejected. Enter it again.')
  })

  it('ignores a non-gate 401, then clears a gate-rejected token and returns to token entry without retrying', async () => {
    storeApiToken('stale-secret')
    vi.mocked(authGateModule.getAuthGateStatus).mockResolvedValue({ gate_required: true })
    vi.mocked(authModule.getSession).mockResolvedValue({ success: false })
    renderApp()
    expect(await screen.findByRole('heading', { name: /accounts/i })).toBeInTheDocument()

    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ success: false, detail: 'Rejected' }), { status: 401 }),
    ))
    await act(async () => {
      await apiJson('/api/probe').catch(() => undefined)
    })
    expect(screen.queryByText('API token required')).not.toBeInTheDocument()
    expect(localStorage.getItem(API_TOKEN_STORAGE_KEY)).toBe('stale-secret')

    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ success: false, detail: 'Rejected' }),
        { status: 401, headers: { 'WWW-Authenticate': 'Bearer' } },
      ),
    ))
    await act(async () => {
      await apiJson('/api/probe').catch(() => undefined)
    })

    expect(await screen.findByText('API token required')).toBeInTheDocument()
    expect(localStorage.getItem(API_TOKEN_STORAGE_KEY)).toBeNull()
    expect(authGateModule.getAuthGateStatus).toHaveBeenCalledTimes(1)
  })
})
