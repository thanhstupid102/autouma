import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

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

function makeQC() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } })
}

function wrap(ui: React.ReactElement) {
  return render(
    <QueryClientProvider client={makeQC()}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  )
}

function setFinePointer(matches: boolean) {
  const mediaQuery = {
    matches,
    media: '(hover: hover) and (pointer: fine)',
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  } satisfies MediaQueryList
  vi.stubGlobal('matchMedia', vi.fn(() => mediaQuery))
}

const f = (name: string, stars: number, category: string) => ({ name, stars, category })

const strongBlue: ParentInfo = {
  instance_id: 'strong',
  card_id: '200001',
  name: 'Strong',
  rank: 15,
  tree: { self: { factors: [f('Speed', 3, 'stat'), f('Stamina', 3, 'stat')] } },
} as unknown as ParentInfo

const weakBlue: ParentInfo = {
  instance_id: 'weak',
  card_id: '200002',
  name: 'Weak',
  rank: 11,
  tree: { self: { factors: [f('Speed', 2, 'stat')] } },
} as unknown as ParentInfo

const grandparentBlue: ParentInfo = {
  instance_id: 'gp-blue',
  card_id: '200003',
  name: 'Grandparent Blue',
  rank: 12,
  tree: { gp4: { factors: [f('Speed', 3, 'stat')] } },
} as unknown as ParentInfo

describe('ParentGrid spark filter', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('hides parents whose blue total is below the chosen minimum', () => {
    wrap(<ParentGrid parents={[strongBlue, weakBlue]} veterans={[]} onVeteransChange={vi.fn()} />)

    expect(screen.getByTestId('parent-card-strong')).toBeInTheDocument()
    expect(screen.getByTestId('parent-card-weak')).toBeInTheDocument()

    fireEvent.change(screen.getByTestId('spark-minBlue'), { target: { value: '5' } })

    expect(screen.getByTestId('parent-card-strong')).toBeInTheDocument()
    expect(screen.queryByTestId('parent-card-weak')).not.toBeInTheDocument()
  })

  it('clear restores all parents', () => {
    wrap(<ParentGrid parents={[strongBlue, weakBlue]} veterans={[]} onVeteransChange={vi.fn()} />)

    fireEvent.change(screen.getByTestId('spark-minBlue'), { target: { value: '5' } })
    expect(screen.queryByTestId('parent-card-weak')).not.toBeInTheDocument()

    fireEvent.click(screen.getByTestId('spark-clear'))
    expect(screen.getByTestId('parent-card-weak')).toBeInTheDocument()
  })

  it('does not count sparks that exist only on grandparents', () => {
    wrap(<ParentGrid parents={[grandparentBlue, strongBlue]} veterans={[]} onVeteransChange={vi.fn()} />)

    fireEvent.change(screen.getByTestId('spark-minBlue'), { target: { value: '3' } })

    expect(screen.queryByTestId('parent-card-gp-blue')).not.toBeInTheDocument()
    expect(screen.getByTestId('parent-card-strong')).toBeInTheDocument()
  })

  it('opens touch spark details without selecting or starting deletion', () => {
    setFinePointer(false)
    const onVeteransChange = vi.fn()
    wrap(
      <ParentGrid
        parents={[strongBlue]}
        veterans={[]}
        onVeteransChange={onVeteransChange}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Spark details for Strong' }))

    expect(screen.getByRole('dialog', { name: 'Spark details for Strong' })).toBeInTheDocument()
    expect(onVeteransChange).not.toHaveBeenCalled()
    expect(careerApi.deleteParents).not.toHaveBeenCalled()
    expect(screen.queryByTestId('parent-delete-confirm')).not.toBeInTheDocument()
  })
})
