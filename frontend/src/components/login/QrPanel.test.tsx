import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, act, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import QrPanel from './QrPanel'

// ---------------------------------------------------------------------------
// Module-level mocks
// ---------------------------------------------------------------------------

vi.mock('@/api/auth', () => ({
  qrStart: vi.fn(),
  qrPoll: vi.fn(),
  login: vi.fn(),
}))

vi.mock('qrcode', () => ({
  default: {
    toDataURL: vi.fn().mockResolvedValue('data:image/png;base64,FAKE'),
  },
}))

import * as authModule from '@/api/auth'

let clipboardWriteText: ReturnType<typeof vi.fn>

function makeQC() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } })
}

function renderPanel(account?: string, onNeedsTransitionLink = vi.fn()) {
  return render(
    <QueryClientProvider client={makeQC()}>
      <QrPanel
        onUsePassword={vi.fn()}
        onNeedsTransitionLink={onNeedsTransitionLink}
        account={account}
      />
    </QueryClientProvider>
  )
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('QrPanel — transient poll error resilience', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.clearAllMocks()
    clipboardWriteText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText: clipboardWriteText },
    })

    // qrStart always succeeds
    vi.mocked(authModule.qrStart).mockResolvedValue({ challenge_url: 'https://s.team/q/1/FAKE' })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('offers same-device open and copy actions while keeping the QR responsive', async () => {
    const challengeUrl = 'https://s.team/q/1/FAKE'

    renderPanel()

    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(screen.getByRole('link', { name: /open in steam/i })).toHaveAttribute(
      'href',
      challengeUrl,
    )
    expect(screen.getByRole('img', { name: /steam qr code/i })).toHaveClass('max-w-full')

    fireEvent.click(screen.getByRole('button', { name: /copy link/i }))
    await act(async () => {
      await Promise.resolve()
    })

    expect(clipboardWriteText).toHaveBeenCalledWith(challengeUrl)
    expect(screen.getByRole('button', { name: /copied/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /use password instead/i })).toHaveClass(
      'h-11',
      'md:h-8',
      'w-full',
    )
  })

  it('keeps polling after a transient qrPoll() rejection and shows pending status', async () => {
    // First call throws a network error; second call resolves with 'pending'
    vi.mocked(authModule.qrPoll)
      .mockRejectedValueOnce(new Error('Network Error'))
      .mockResolvedValue({ status: 'pending' })

    renderPanel()

    // Wait for qrStart + QRCode.toDataURL to resolve (microtasks)
    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })

    // Tick the first poll interval — throws
    await act(async () => {
      vi.advanceTimersByTime(2000)
      await Promise.resolve()
    })

    // After the transient error the status must NOT be an error message
    expect(screen.queryByText(/Poll error/i)).toBeNull()
    expect(screen.queryByText(/New QR/i)).toBeNull()

    // Tick the second poll interval — resolves with 'pending'
    await act(async () => {
      vi.advanceTimersByTime(2000)
      await Promise.resolve()
    })

    // Now we should see the 'pending' status text
    expect(screen.getByText('Waiting for phone confirmation...')).toBeInTheDocument()
  })

  it('stops after three consecutive poll rejections and shows an error', async () => {
    vi.mocked(authModule.qrPoll).mockRejectedValue(new Error('fetch failed'))

    renderPanel()

    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })

    await act(async () => {
      await vi.advanceTimersByTimeAsync(6000)
    })

    expect(authModule.qrPoll).toHaveBeenCalledTimes(3)
    expect(screen.getByText(/Could not check QR status after 3 attempts/)).toBeInTheDocument()
    expect(screen.getByText('New QR')).toBeInTheDocument()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10000)
    })
    expect(authModule.qrPoll).toHaveBeenCalledTimes(3)
  })

  it('surfaces a terminal server error and stops polling', async () => {
    const serverMessage = 'Secure storage is unavailable. Configure the secret store.'
    vi.mocked(authModule.qrPoll).mockResolvedValue({
      status: 'error',
      error: serverMessage,
    })

    renderPanel()

    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000)
    })

    expect(screen.getByText(`${serverMessage} - tap New QR.`)).toBeInTheDocument()
    expect(screen.getByText('New QR')).toBeInTheDocument()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10000)
    })
    expect(authModule.qrPoll).toHaveBeenCalledOnce()
  })

  it('passes the target account when QR confirmation performs login', async () => {
    vi.mocked(authModule.qrPoll).mockResolvedValue({ status: 'confirmed' })
    vi.mocked(authModule.login).mockResolvedValue({ success: false, state: 'failed' })

    renderPanel('new_acct')

    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })

    await act(async () => {
      vi.advanceTimersByTime(2000)
      await Promise.resolve()
    })

    expect(authModule.login).toHaveBeenCalledWith({}, 'new_acct')
  })

  it('surfaces needs_transition_link after QR confirmation', async () => {
    const onNeedsTransitionLink = vi.fn()
    vi.mocked(authModule.qrPoll).mockResolvedValue({ status: 'confirmed' })
    vi.mocked(authModule.login).mockResolvedValue({
      success: false,
      state: 'needs_transition_link',
    })

    renderPanel('new_acct', onNeedsTransitionLink)

    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000)
    })

    expect(onNeedsTransitionLink).toHaveBeenCalledOnce()
    expect(screen.queryByText(/login failed after scan/i)).not.toBeInTheDocument()
  })
})
