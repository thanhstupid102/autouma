import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'

import Dashboard from './Dashboard'
import type { ActionHistoryRow, RunnerStatus } from '@/api/types'

const dashboardMocks = vi.hoisted(() => ({
  runner: {
    running: true,
    paused: false,
    turn: 12,
    steps: 40,
    action_history: [
      { turn: 12, action: 'train', facility: 'speed', detail: 'training speed' },
    ] as ActionHistoryRow[],
  } as RunnerStatus,
  loadScenarios: vi.fn(),
}))

vi.mock('@/hooks/useSession', () => ({
  useSession: vi.fn(() => ({
    data: {
      success: true,
      account: { career: { active: true } },
    },
    isPending: false,
  })),
}))

vi.mock('@/hooks/useRunner', () => ({
  useRunner: vi.fn(() => ({
    data: { runner: dashboardMocks.runner },
    failureCount: 0,
  })),
}))

vi.mock('@/stores/runSettings', () => ({
  useRunSettings: vi.fn(() => ({
    burnClocks: false,
    runCount: 1,
    twoPalDeck: false,
    sparkReroll: false,
    scenarioId: 4,
    scenarios: [{ id: 4, label: 'URA Finale' }],
    setScenarioId: vi.fn(),
    setDevCareer: vi.fn(),
    loadScenarios: dashboardMocks.loadScenarios,
  })),
}))

vi.mock('@/stores/selection', () => ({
  useSelection: vi.fn(() => ({
    deck: { id: 1, name: 'A very long complete deck name that must remain readable', cards: [] },
    friend: null,
    trainee: null,
    veterans: [],
    rental: null,
    event: { enabled: false, level: 1, boost: false },
  })),
}))

vi.mock('@/api/career', () => ({
  pauseRunner: vi.fn(),
  resumeRunner: vi.fn(),
  deleteCareer: vi.fn(),
  runCareer: vi.fn(),
}))

vi.mock('@/components/dashboard/RunOptions', () => ({
  RunOptions: () => <div data-testid="run-options" />,
}))

function renderDashboard() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/account/test/dashboard']}>
        <Dashboard />
      </MemoryRouter>
    </QueryClientProvider>
  )
}

describe('Dashboard mobile live controls', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    Object.assign(dashboardMocks.runner, {
      running: true,
      paused: false,
      turn: 12,
      steps: 40,
      last_error: undefined,
      action_history: [
        { turn: 12, action: 'train', facility: 'speed', detail: 'training speed' },
      ],
    })
  })

  it('keeps Run, Pause, and Delete in the mobile sticky region while history scrolls', () => {
    renderDashboard()

    const controls = screen.getByTestId('run-controls')
    expect(controls).toHaveClass('sticky', 'top-0', 'md:static')
    fireEvent.scroll(screen.getByTestId('action-history-scroll'))

    expect(within(controls).getByRole('button', { name: 'PAUSE' })).toBeInTheDocument()
    expect(within(controls).getByRole('button', { name: 'DELETE' })).toBeInTheDocument()
    expect(within(controls).getByRole('button', { name: 'RESUME CAREER' })).toBeInTheDocument()
  })

  it('wraps a long raw runner error rather than widening the status panel', () => {
    const longError = `runner-error:${'x'.repeat(240)}`
    Object.assign(dashboardMocks.runner, {
      running: false,
      paused: false,
      turn: undefined,
      steps: undefined,
      last_error: longError,
      action_history: [],
    })

    renderDashboard()

    const status = screen.getByTestId('runner-status-text')
    expect(status).toHaveTextContent(longError)
    expect(status).toHaveClass('[overflow-wrap:anywhere]', 'whitespace-pre-wrap')
  })

  it('shows the full team name in a touch-sized link', () => {
    renderDashboard()

    const link = screen.getByRole('link', {
      name: 'A very long complete deck name that must remain readable',
    })
    expect(link).toHaveClass('min-h-11', 'md:min-h-0', '[overflow-wrap:anywhere]')
    expect(link).not.toHaveClass('truncate')
  })
})
