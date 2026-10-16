import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import TransitionLinkPanel from './TransitionLinkPanel'
import { TRANSITION_LINK_ERROR_MESSAGES } from './transitionLinkErrors'

interface RenderPanelOptions {
  reason?: 'steam_link_removed'
  initialTrainerId?: number | string
  onBackToSteam?: () => void
}

function renderPanel(account = 'linked-account', options: RenderPanelOptions = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <TransitionLinkPanel
        account={account}
        reason={options.reason}
        initialTrainerId={options.initialTrainerId}
        onBackToSteam={options.onBackToSteam}
      />
    </QueryClientProvider>,
  )
}

function fillForm(trainerId = '123456789', password = 'LinkPass9') {
  fireEvent.change(screen.getByLabelText(/trainer id/i), {
    target: { value: trainerId },
  })
  fireEvent.change(screen.getByLabelText(/link password/i), {
    target: { value: password },
  })
}

function response(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

beforeEach(() => {
  vi.restoreAllMocks()
  localStorage.clear()
})

describe('TransitionLinkPanel recovery context', () => {
  it('uses the shared touch-sized button for returning to Steam login', () => {
    renderPanel('linked-account', { onBackToSteam: vi.fn() })

    expect(screen.getByRole('button', { name: /back to steam login/i })).toHaveClass(
      'h-11',
      'md:h-8',
      'w-full',
    )
  })

  it('explains a removed Uma link, prefills Trainer ID, and writes no localStorage', () => {
    const setItem = vi.spyOn(Storage.prototype, 'setItem')
    const removeItem = vi.spyOn(Storage.prototype, 'removeItem')

    renderPanel('linked-account', {
      reason: 'steam_link_removed',
      initialTrainerId: '229594617236',
    })

    expect(screen.getByText(/uma link removed/i)).toBeInTheDocument()
    expect(screen.getByText(/trainer id and link password.*way back in/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/trainer id/i)).toHaveValue('229594617236')
    expect(setItem).not.toHaveBeenCalled()
    expect(removeItem).not.toHaveBeenCalled()
  })
})

describe('TransitionLinkPanel validation', () => {
  it.each([
    ['12345678', 'LinkPass9', /9 to 12 digits/i],
    ['1234567890123', 'LinkPass9', /9 to 12 digits/i],
    ['12345678a', 'LinkPass9', /ASCII digits only/i],
    ['123456789', 'Short1A', /8 to 16 characters/i],
    ['123456789', 'WayTooLongPass123A', /8 to 16 characters/i],
    ['123456789', 'PasswordA', /include a digit/i],
    ['123456789', 'PASSWORD9', /include a lowercase/i],
    ['123456789', 'password9', /include an uppercase/i],
    ['123456789', 'Link-Pass9', /ASCII letters and digits only/i],
  ])('rejects invalid input without a request', (trainerId, password, message) => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    renderPanel()
    fillForm(trainerId, password)

    fireEvent.click(screen.getByRole('button', { name: /verify account/i }))

    expect(screen.getByText(message)).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
    expect(screen.queryByText(password)).not.toBeInTheDocument()
  })

  it.each([
    ['123456789', 'Abcdefg1'],
    ['123456789012', 'Abcdefghijklmno1'],
  ])('accepts the validation boundaries', async (trainerId, password) => {
    const fetchMock = vi.fn().mockResolvedValue(response({
      success: true,
      state: 'verified',
      name: 'Boundary Trainer',
    }))
    vi.stubGlobal('fetch', fetchMock)
    renderPanel()
    fillForm(trainerId, password)

    fireEvent.click(screen.getByRole('button', { name: /verify account/i }))

    await screen.findByText('Boundary Trainer')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})

describe('TransitionLinkPanel two-step link', () => {
  it('previews first, shows the trainer name, and commits only after explicit confirmation', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response({
        success: true,
        state: 'verified',
        name: 'Rice Shower',
        request_user_name: 'Steam Owner',
      }))
      .mockResolvedValueOnce(response({ success: true, state: 'authenticated' }))
    vi.stubGlobal('fetch', fetchMock)
    renderPanel('alt-account')
    fillForm()

    fireEvent.click(screen.getByRole('button', { name: /verify account/i }))

    expect(await screen.findByText('Rice Shower')).toBeInTheDocument()
    expect(screen.getByText(/cannot be undone from the app/i)).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledTimes(1)

    const firstRequest = fetchMock.mock.calls[0]
    expect(firstRequest[0]).toBe('/api/auth/transition-code/chain')
    expect(firstRequest[1]).toMatchObject({
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Account': 'alt-account',
      },
    })
    expect(JSON.parse(String(firstRequest[1]?.body))).toEqual({
      input_viewer_id: '123456789',
      password: 'LinkPass9',
      verify_only: true,
    })

    fireEvent.click(screen.getByRole('button', { name: /link this account/i }))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
    expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body))).toEqual({
      input_viewer_id: '123456789',
      password: 'LinkPass9',
      verify_only: false,
    })
  })

  it('does not write Trainer ID or password data to localStorage', async () => {
    const setItem = vi.spyOn(Storage.prototype, 'setItem')
    const removeItem = vi.spyOn(Storage.prototype, 'removeItem')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({
      success: true,
      state: 'verified',
      name: 'No Storage Trainer',
    })))
    renderPanel()
    fillForm()

    fireEvent.click(screen.getByRole('button', { name: /verify account/i }))
    await screen.findByText('No Storage Trainer')

    expect(setItem).not.toHaveBeenCalled()
    expect(removeItem).not.toHaveBeenCalled()
  })
})

describe('TransitionLinkPanel error mapping', () => {
  it('keeps a distinct readable message for every known symbolic code', () => {
    expect(new Set(Object.values(TRANSITION_LINK_ERROR_MESSAGES)).size).toBe(
      Object.keys(TRANSITION_LINK_ERROR_MESSAGES).length,
    )
  })

  it.each(Object.entries(TRANSITION_LINK_ERROR_MESSAGES))(
    'renders %s without falling back to server detail',
    async (errorCode, expectedMessage) => {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({
        success: false,
        state: 'failed',
        error_code: errorCode,
        detail: 'raw server detail',
      })))
      renderPanel()
      fillForm()

      fireEvent.click(screen.getByRole('button', { name: /verify account/i }))

      expect(await screen.findByText(expectedMessage)).toBeInTheDocument()
      expect(screen.queryByText('raw server detail')).not.toBeInTheDocument()
    },
  )

  it('falls back to server detail for an unknown code', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({
      success: false,
      state: 'failed',
      error_code: 'FUTURE_LINK_ERROR',
      detail: 'Future server explanation',
    })))
    renderPanel()
    fillForm()

    fireEvent.click(screen.getByRole('button', { name: /verify account/i }))

    expect(await screen.findByText('Future server explanation')).toBeInTheDocument()
  })
})
