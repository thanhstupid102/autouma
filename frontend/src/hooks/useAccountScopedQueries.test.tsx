import type { ReactNode } from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { useAccountStore } from '../stores/account'
import { useSession } from './useSession'
import { useRunner } from './useRunner'
import * as authModule from '../api/auth'
import * as careerModule from '../api/career'
import type { RunnerStatus, SessionData } from '../api/types'

vi.mock('../api/auth', () => ({
  getSession: vi.fn(),
}))

vi.mock('../api/career', () => ({
  getRunner: vi.fn(),
}))

function makeWrapper() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  }
  return Wrapper
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

beforeEach(() => {
  vi.clearAllMocks()
  useAccountStore.setState({ accounts: [], selected: 'A' })
})

describe('account-scoped session and runner queries', () => {
  it('fetches session with the selected account from the query key', async () => {
    vi.mocked(authModule.getSession).mockResolvedValue({ success: true } as SessionData)

    renderHook(() => useSession(), { wrapper: makeWrapper() })

    await waitFor(() => {
      expect(authModule.getSession).toHaveBeenCalledWith('A')
    })

    act(() => {
      useAccountStore.getState().setSelected('B')
    })

    await waitFor(() => {
      expect(authModule.getSession).toHaveBeenCalledWith('B')
    })
  })

  it('fetches runner with the selected account and clears stale running data on switch', async () => {
    const pendingB = deferred<{ success: boolean; runner?: RunnerStatus }>()
    vi.mocked(careerModule.getRunner).mockImplementation((account?: string) => {
      if (account === 'A') {
        return Promise.resolve({ success: true, runner: { running: true } })
      }
      if (account === 'B') {
        return pendingB.promise
      }
      return Promise.resolve({ success: true })
    })

    const { result } = renderHook(() => useRunner(true), { wrapper: makeWrapper() })

    await waitFor(() => {
      expect(result.current.data?.runner?.running).toBe(true)
    })
    expect(careerModule.getRunner).toHaveBeenCalledWith('A')

    act(() => {
      useAccountStore.getState().setSelected('B')
    })

    await waitFor(() => {
      expect(careerModule.getRunner).toHaveBeenCalledWith('B')
    })
    await waitFor(() => {
      expect(result.current.data).toBeUndefined()
    })

    await act(async () => {
      pendingB.resolve({ success: true, runner: { running: false } })
      await pendingB.promise
    })

    await waitFor(() => {
      expect(result.current.data?.runner?.running).toBe(false)
    })
  })
})
