import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as careerApi from '@/api/career'
import type { ParentInfo } from '@/api/types'
import { ParentGrid } from './ParentGrid'

vi.mock('@/api/career', () => ({
  deleteParents: vi.fn(),
  getAutoDeleteConfig: vi.fn(),
  setAutoDeleteConfig: vi.fn(),
}))

vi.mock('@/hooks/useSession', () => ({
  useSession: vi.fn(() => ({ data: undefined })),
}))

vi.mock('@/stores/selection', () => ({
  useSelection: vi.fn(() => ({
    deck: null,
    friend: null,
    trainee: null,
    veterans: [],
    rental: null,
    event: { enabled: false, level: 1, boost: false },
  })),
}))

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    warning: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
  },
}))

function makeQC() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } })
}

function wrap(ui: React.ReactElement) {
  const client = makeQC()
  const invalidateQueries = vi.spyOn(client, 'invalidateQueries')
  return {
    ...render(
      <QueryClientProvider client={client}>
        <MemoryRouter>{ui}</MemoryRouter>
      </QueryClientProvider>,
    ),
    invalidateQueries,
  }
}

const parent1: ParentInfo = {
  instance_id: 'inst-1',
  card_id: '200001',
  rank: 15,
  name: 'Parent Alpha',
} as unknown as ParentInfo

const parent2: ParentInfo = {
  instance_id: 'inst-2',
  card_id: '200002',
  rank: 13,
  name: 'Parent Beta',
} as unknown as ParentInfo

describe('ParentGrid delete UI', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(careerApi.deleteParents).mockResolvedValue({
      success: true,
      deleted: ['inst-1'],
      parents: [],
    })
  })

  it('bulk deletes checked parents and invalidates the session query', async () => {
    const onVeteransChange = vi.fn()
    const { invalidateQueries } = wrap(
      <ParentGrid parents={[parent1, parent2]} veterans={[parent1]} onVeteransChange={onVeteransChange} />,
    )

    fireEvent.click(screen.getByTestId('parent-select-mode'))
    fireEvent.click(screen.getByTestId('parent-checkbox-inst-1'))
    fireEvent.click(screen.getByTestId('parent-delete-selected'))
    fireEvent.click(screen.getByTestId('parent-delete-confirm'))

    await waitFor(() => {
      expect(careerApi.deleteParents).toHaveBeenCalledWith({ instance_ids: ['inst-1'], unlock_locked: false })
    })
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: ['session'] })
    expect(onVeteransChange).toHaveBeenCalledWith([])
  })

  it('single-card delete uses the same confirm flow', async () => {
    vi.mocked(careerApi.deleteParents).mockResolvedValue({
      success: true,
      deleted: ['inst-2'],
      parents: [],
    })

    const { invalidateQueries } = wrap(
      <ParentGrid parents={[parent1, parent2]} veterans={[]} onVeteransChange={vi.fn()} />,
    )

    fireEvent.click(screen.getByTestId('parent-delete-inst-2'))
    expect(screen.getByText(/Delete 1 veteran/)).toBeInTheDocument()

    fireEvent.click(screen.getByTestId('parent-delete-confirm'))

    await waitFor(() => {
      expect(careerApi.deleteParents).toHaveBeenCalledWith({ instance_ids: ['inst-2'], unlock_locked: false })
    })
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: ['session'] })
  })

  it('warns about locked (memo) veterans and deletes with unlock_locked', async () => {
    vi.mocked(careerApi.deleteParents).mockResolvedValue({
      success: true,
      deleted: ['inst-3'],
      parents: [],
    })
    const lockedParent: ParentInfo = {
      instance_id: 'inst-3',
      card_id: '200003',
      rank: 11,
      name: 'Locked One',
      is_locked: 1,
    } as unknown as ParentInfo

    wrap(<ParentGrid parents={[lockedParent]} veterans={[]} onVeteransChange={vi.fn()} />)

    // The card shows a lock badge.
    expect(screen.getByTestId('parent-locked-inst-3')).toBeInTheDocument()

    fireEvent.click(screen.getByTestId('parent-delete-inst-3'))
    // The confirm dialog warns about the locked veteran.
    expect(screen.getByTestId('parent-delete-locked-warning')).toBeInTheDocument()

    fireEvent.click(screen.getByTestId('parent-delete-confirm'))

    await waitFor(() => {
      expect(careerApi.deleteParents).toHaveBeenCalledWith({ instance_ids: ['inst-3'], unlock_locked: true })
    })
  })
})
