import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import RemoveUmaLinkDialog from './RemoveUmaLinkDialog'

vi.mock('sonner', () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}))

function response(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

function renderDialog(account = 'yuko') {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <RemoveUmaLinkDialog account={account} />
    </QueryClientProvider>,
  )
}

function openConfirmation() {
  fireEvent.click(screen.getByRole('button', { name: 'Remove Uma link' }))
  fireEvent.click(screen.getByRole('button', { name: /i understand/i }))
}

function dialog() {
  return within(screen.getByRole('dialog'))
}

beforeEach(() => {
  vi.restoreAllMocks()
  localStorage.clear()
})

describe('RemoveUmaLinkDialog', () => {
  it('uses the Remove Uma link label and explains the consequences', () => {
    renderDialog()

    expect(screen.getByRole('button', { name: 'Remove Uma link' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Remove Uma link' }))

    expect(dialog().getByRole('heading', { name: 'Remove Uma link' })).toBeInTheDocument()
    expect(dialog().getByText(/this removes the link between this steam account/i)).toBeInTheDocument()
    expect(dialog().getByText(/plain steam login will not find this account/i)).toBeInTheDocument()
    expect(dialog().queryByLabelText(/data link password/i)).not.toBeInTheDocument()
    expect(dialog().queryByRole('button', { name: /verify recovery path/i })).not.toBeInTheDocument()
  })

  it('enables confirmation only for the exact account name and persists nothing', () => {
    const setItem = vi.spyOn(Storage.prototype, 'setItem')
    vi.stubGlobal('fetch', vi.fn())
    renderDialog()
    openConfirmation()

    const finalButton = dialog().getByRole('button', { name: 'Remove Uma link' })
    expect(finalButton).toBeDisabled()

    fireEvent.change(dialog().getByLabelText(/type yuko to confirm/i), {
      target: { value: 'Yuko' },
    })
    expect(dialog().getByText(/account name must match exactly/i)).toBeInTheDocument()
    expect(finalButton).toBeDisabled()

    fireEvent.change(dialog().getByLabelText(/type yuko to confirm/i), {
      target: { value: 'yuko' },
    })
    expect(finalButton).toBeEnabled()
    expect(setItem).not.toHaveBeenCalled()
  })

  it('sends only the name confirmation to the unchanged unbind route', async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({
      success: true,
      state: 'unbound',
      recovery_verified: 'not_checked',
      steam_unbound_at: 123,
    }))
    vi.stubGlobal('fetch', fetchMock)
    renderDialog()
    openConfirmation()

    fireEvent.change(dialog().getByLabelText(/type yuko to confirm/i), {
      target: { value: 'yuko' },
    })
    fireEvent.click(dialog().getByRole('button', { name: 'Remove Uma link' }))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    expect(fetchMock.mock.calls[0][0]).toBe('/api/auth/steam/unbind')
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({
      confirm_account_name: 'yuko',
    })
  })
})
