import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ParentInfo, SessionData } from '@/api/types'
import { useAccountStore } from '@/stores/account'
import { useSelection } from '@/stores/selection'
import { resetParentRosterRefreshThrottleForTests } from '@/lib/parentRosterRefresh'
import Library from './Library'

const mocks = vi.hoisted(() => ({
  useSession: vi.fn(),
  getFriends: vi.fn(),
  refreshParents: vi.fn(),
  deleteParents: vi.fn(),
  getAutoDeleteConfig: vi.fn(),
  setAutoDeleteConfig: vi.fn(),
  syncSelection: vi.fn(),
}))

vi.mock('@/hooks/useSession', () => ({ useSession: mocks.useSession }))
vi.mock('@/api/career', () => ({
  getFriends: mocks.getFriends,
  refreshParents: mocks.refreshParents,
  deleteParents: mocks.deleteParents,
  getAutoDeleteConfig: mocks.getAutoDeleteConfig,
  setAutoDeleteConfig: mocks.setAutoDeleteConfig,
  syncSelection: mocks.syncSelection,
}))
vi.mock('@/components/dashboard/TeamPanel', () => ({ TeamPanel: () => <div /> }))
vi.mock('@/components/library/DeckList', () => ({ DeckList: () => <div /> }))
vi.mock('@/components/library/FriendGrid', () => ({ FriendGrid: () => <div /> }))
vi.mock('@/components/library/TraineeGrid', () => ({ TraineeGrid: () => <div /> }))
vi.mock('@/components/library/FriendParentGrid', () => ({ FriendParentGrid: () => <div /> }))
vi.mock('@/components/library/CardGrid', () => ({ CardGrid: () => <div /> }))
vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    warning: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
  },
}))

const parentOne = {
  instance_id: 1,
  card_id: '100101',
  name: 'Parent One',
  rank: 10,
} as ParentInfo

const parentTwo = {
  instance_id: 2,
  card_id: '100102',
  name: 'Parent Two',
  rank: 10,
} as ParentInfo

const vanishedParent = {
  instance_id: 999,
  card_id: '100999',
  name: 'Vanished Parent',
  rank: 10,
} as ParentInfo

function sessionData(careerActive: boolean, parents = [parentOne, parentTwo]): SessionData {
  return {
    success: true,
    parents,
    decks: [],
    umas: [],
    supports: [],
    account: { career: { active: careerActive } },
  } as SessionData
}

function renderLibrary(data: SessionData) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  mocks.useSession.mockReturnValue({ data, isLoading: false })
  return render(
    <QueryClientProvider client={queryClient}>
      <Library />
    </QueryClientProvider>,
  )
}

describe('Library parent roster controls', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    resetParentRosterRefreshThrottleForTests()
    useSelection.getState().clear()
    useAccountStore.setState({ selected: 'account-a' })
    mocks.getFriends.mockResolvedValue({ success: true, friends: [] })
    mocks.refreshParents.mockResolvedValue({ success: true, parents: [parentOne, parentTwo] })
    mocks.syncSelection.mockResolvedValue({ success: true })
  })

  it('clears stale career parent slots through the selection store without deleting the roster', async () => {
    useSelection.setState({ veterans: [vanishedParent] })
    renderLibrary(sessionData(true))

    expect(screen.getByText('Parent One')).toBeInTheDocument()
    expect(screen.getByText('Parent Two')).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('clear-career-parent-selection'))

    await waitFor(() => expect(useSelection.getState().veterans).toEqual([]))
    expect(mocks.syncSelection).toHaveBeenCalledWith({
      selection: expect.objectContaining({ veterans: [] }),
    })
    expect(mocks.deleteParents).not.toHaveBeenCalled()
    expect(screen.getByText('Parent One')).toBeInTheDocument()
    expect(screen.getByText('Parent Two')).toBeInTheDocument()
  })

  it('disables the clear control when no career parent slot is selected', () => {
    renderLibrary(sessionData(true))

    expect(screen.getByTestId('clear-career-parent-selection')).toBeDisabled()
  })

  it('auto-refreshes only once across Library entries inside the staleness window', async () => {
    const first = renderLibrary(sessionData(false))
    await waitFor(() => expect(mocks.refreshParents).toHaveBeenCalledTimes(1))
    first.unmount()

    renderLibrary(sessionData(false))
    await waitFor(() => expect(mocks.refreshParents).toHaveBeenCalledTimes(1))
  })

  it('disables parent roster refresh while a career is active', () => {
    renderLibrary(sessionData(true))

    expect(screen.getByRole('button', { name: 'Refresh parent roster' })).toBeDisabled()
    expect(mocks.refreshParents).not.toHaveBeenCalled()
  })

  it('drops a vanished parent from the frontend selection after refresh', async () => {
    useSelection.setState({ veterans: [parentOne, vanishedParent] })
    mocks.refreshParents.mockResolvedValue({
      success: true,
      parents: [parentOne],
      selection: { veterans: [parentOne] },
      removed_veteran_ids: [999],
    })

    renderLibrary(sessionData(false))

    await waitFor(() => expect(useSelection.getState().veterans).toEqual([parentOne]))
    expect(mocks.syncSelection).toHaveBeenCalledWith({
      selection: expect.objectContaining({ veterans: [parentOne] }),
    })
  })
})
