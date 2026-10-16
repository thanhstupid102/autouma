import { fireEvent, render, screen, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ImportExportControls from './ImportExportControls'
import { useAccountStore } from '@/stores/account'
import type { AccountSnapshot } from '@/stores/account'

vi.mock('sonner', () => ({
  toast: { error: vi.fn(), info: vi.fn(), success: vi.fn() },
}))

function makeAccount(index: number): AccountSnapshot {
  return {
    name: `account-${index}`,
    logged_in: true,
    running: false,
    loop_active: false,
    account: {},
    runner: null,
  }
}

function renderControls() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <ImportExportControls />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  useAccountStore.setState({
    accounts: Array.from({ length: 20 }, (_, index) => makeAccount(index + 1)),
    selected: '',
  })
})

describe('ImportExportControls export dialog', () => {
  it('keeps a 20-account list in DialogBody with the footer outside the scroll container', () => {
    renderControls()
    fireEvent.click(screen.getByRole('button', { name: /export/i }))

    const dialog = screen.getByRole('dialog')
    const body = dialog.querySelector<HTMLElement>('[data-slot="dialog-body"]')
    const footer = dialog.querySelector<HTMLElement>('[data-slot="dialog-footer"]')

    expect(body).not.toBeNull()
    expect(footer).not.toBeNull()
    expect(body).toHaveClass('overflow-y-auto')
    expect(within(body!).getAllByRole('checkbox')).toHaveLength(20)
    expect(within(body!).getByText('account-20')).toBeInTheDocument()
    expect(body!.contains(footer)).toBe(false)
    expect(body!.nextElementSibling).toBe(footer)
  })
})
