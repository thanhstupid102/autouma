/**
 * Tests for Task 9 — dashboard live view components and pure helpers.
 *
 * Coverage:
 *   1. formatStatsDetail — with stats → exact string; without → row.detail fallback
 *   2. deriveRunnerStatusText — each branch (cases 1/3/4/5 + null cases)
 *   3. ActionHistoryTable — renders one row per input, correct normalized action pill
 *   4. StatsRow — hidden when no stats; shows HP/max and stat values when present
 *   5. BackoffBanner — visibility driven by circuit_tripped flag
 */

import { describe, it, expect, vi } from 'vitest'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { formatStatsDetail, deriveRunnerStatusText } from './runnerView'
import { ActionHistoryTable } from './ActionHistoryTable'
import { StatsRow } from './StatsRow'
import { BackoffBanner } from './BackoffBanner'
import type { ActionHistoryRow, RunnerStatus } from '@/api/types'

// ---------------------------------------------------------------------------
// Mocks (needed by components that import hooks or stores)
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeQC() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } })
}

function wrap(ui: React.ReactElement) {
  return render(
    <QueryClientProvider client={makeQC()}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>
  )
}

// ---------------------------------------------------------------------------
// 1. formatStatsDetail
// ---------------------------------------------------------------------------

describe('formatStatsDetail', () => {
  it('returns row.detail when stats is empty object', () => {
    const row: ActionHistoryRow = { turn: 1, action: 'train', facility: 'speed', detail: 'training speed', stats: {} }
    expect(formatStatsDetail(row)).toBe('training speed')
  })

  it('returns empty string when stats is absent and detail is empty', () => {
    const row: ActionHistoryRow = { turn: 1, action: 'finish', facility: '', detail: '' }
    expect(formatStatsDetail(row)).toBe('')
  })

  it('returns full stats string when stats has keys', () => {
    const row: ActionHistoryRow = {
      turn: 5,
      action: 'train',
      facility: 'speed',
      detail: '',
      stats: {
        hp: 80,
        max_hp: 100,
        motivation: 3,
        speed: 400,
        stamina: 300,
        power: 250,
        guts: 200,
        wit: 150,
        skill_point: 500,
      },
    }
    expect(formatStatsDetail(row)).toBe(
      'HP 80/100 | MOOD 3 | SPD 400 STA 300 PWR 250 GUT 200 WIT 150 SP 500'
    )
  })

  it('uses 0 defaults for missing stat keys', () => {
    const row: ActionHistoryRow = {
      turn: 1,
      action: 'train',
      facility: 'speed',
      detail: '',
      stats: { hp: 50 }, // only hp provided — everything else defaults to 0/100
    }
    const result = formatStatsDetail(row)
    expect(result).toContain('HP 50/100')
    expect(result).toContain('MOOD 0')
    expect(result).toContain('SPD 0')
  })

  it('ignores row.detail when stats has keys', () => {
    const row: ActionHistoryRow = {
      turn: 1,
      action: 'train',
      facility: 'speed',
      detail: 'should be ignored',
      stats: { hp: 10, max_hp: 100 },
    }
    expect(formatStatsDetail(row)).not.toContain('should be ignored')
    expect(formatStatsDetail(row)).toContain('HP 10/100')
  })
})

// ---------------------------------------------------------------------------
// 2. deriveRunnerStatusText
// ---------------------------------------------------------------------------

describe('deriveRunnerStatusText', () => {
  it('returns null for undefined runner', () => {
    expect(deriveRunnerStatusText(undefined)).toBeNull()
  })

  it('returns null for null runner', () => {
    expect(deriveRunnerStatusText(null)).toBeNull()
  })

  // Case 1: running
  it('returns turn/action/steps text when running', () => {
    const runner: RunnerStatus = { running: true, turn: 12, last_action: 'train', steps: 45 }
    expect(deriveRunnerStatusText(runner)).toBe('Turn 12 / train / 45')
  })

  it('uses fallbacks when turn/last_action/steps are absent', () => {
    const runner: RunnerStatus = { running: true }
    expect(deriveRunnerStatusText(runner)).toBe('Turn ? / running / 0')
  })

  // Case 2: circuit_tripped → null (BackoffBanner takes over)
  it('returns null when circuit_tripped (banner takes over)', () => {
    const runner: RunnerStatus = { running: false, circuit_tripped: true }
    expect(deriveRunnerStatusText(runner)).toBeNull()
  })

  // Case 3: last_error
  it('returns last_error string when present (not running, not tripped)', () => {
    const runner: RunnerStatus = { running: false, last_error: 'Network timeout' }
    expect(deriveRunnerStatusText(runner)).toBe('Network timeout')
  })

  // Case 4: finished
  it('returns "Career finished!" when finished and loop_active is false', () => {
    const runner: RunnerStatus = { running: false, finished: true, loop_active: false }
    expect(deriveRunnerStatusText(runner)).toBe('Career finished!')
  })

  it('returns "Career finished! Restarting..." when finished and loop_active', () => {
    const runner: RunnerStatus = { running: false, finished: true, loop_active: true }
    expect(deriveRunnerStatusText(runner)).toBe('Career finished! Restarting...')
  })

  // Case 5: steps (stopped)
  it('returns stopped-after-N text when steps present', () => {
    const runner: RunnerStatus = { running: false, steps: 100 }
    expect(deriveRunnerStatusText(runner)).toBe('Runner stopped after 100 steps')
  })

  // Empty runner — no meaningful state
  it('returns null for empty runner object', () => {
    const runner: RunnerStatus = { running: false }
    expect(deriveRunnerStatusText(runner)).toBeNull()
  })
})

// ---------------------------------------------------------------------------
// 3. ActionHistoryTable
// ---------------------------------------------------------------------------

describe('ActionHistoryTable', () => {
  const rows: ActionHistoryRow[] = [
    { turn: 1, action: 'train', facility: 'speed', detail: 'training speed' },
    { turn: 2, action: 'race', facility: 'track_a', detail: '' },
    { turn: 3, action: 'rest', facility: '301', detail: 'rest 301' }, // normalizes to recreation
    { turn: 4, action: 'medic', facility: '', detail: '' },
    { turn: 5, action: 'finish', facility: '', detail: '' },
  ]

  it('renders one row per input row', () => {
    wrap(<ActionHistoryTable rows={rows} />)
    const pills = screen.getAllByTestId(/^action-pill-/)
    expect(pills).toHaveLength(rows.length)
  })

  it('shows correct action text in each pill', () => {
    wrap(<ActionHistoryTable rows={rows} />)
    expect(screen.getByTestId('action-pill-0')).toHaveTextContent('train')
    expect(screen.getByTestId('action-pill-1')).toHaveTextContent('race')
    // rest + facility 301 → normalizeHistoryAction → recreation
    expect(screen.getByTestId('action-pill-2')).toHaveTextContent('recreation')
    expect(screen.getByTestId('action-pill-3')).toHaveTextContent('medic')
    expect(screen.getByTestId('action-pill-4')).toHaveTextContent('finish')
  })

  it('shows stats detail when stats are present', () => {
    const rowsWithStats: ActionHistoryRow[] = [
      {
        turn: 1,
        action: 'train',
        facility: 'speed',
        detail: '',
        stats: { hp: 80, max_hp: 100, motivation: 3, speed: 400, stamina: 300, power: 250, guts: 200, wit: 150, skill_point: 500 },
      },
    ]
    wrap(<ActionHistoryTable rows={rowsWithStats} />)
    expect(screen.getAllByText(/HP 80\/100/)).toHaveLength(2)
  })

  it('renders empty table body when rows array is empty', () => {
    wrap(<ActionHistoryTable rows={[]} />)
    expect(screen.queryAllByTestId(/^action-pill-/)).toHaveLength(0)
  })

  it('renders stacked cards below md and the existing table at md and above with every field', () => {
    const row: ActionHistoryRow = {
      turn: 7,
      action: 'train',
      facility: 'speed_lab',
      detail: 'Speed training completed',
    }
    render(<ActionHistoryTable rows={[row]} />)

    const mobile = screen.getByTestId('action-history-mobile')
    const desktop = screen.getByTestId('action-history-desktop')
    expect(mobile).toHaveClass('md:hidden')
    expect(desktop).toHaveClass('hidden', 'md:block')

    for (const presentation of [mobile, desktop]) {
      expect(within(presentation).getByText('7')).toBeInTheDocument()
      expect(within(presentation).getByText('train')).toBeInTheDocument()
      expect(within(presentation).getByText('speed_lab')).toBeInTheDocument()
      expect(within(presentation).getByText('Speed training completed')).toBeInTheDocument()
    }
  })

  it('expands full detail in the stacked presentation', () => {
    const detail = 'HP 80/100 | MOOD 3 | SPD 400 STA 300 PWR 250 GUT 200 WIT 150 SP 500'
    render(
      <ActionHistoryTable
        rows={[{ turn: 1, action: 'train', facility: 'speed', detail }]}
      />
    )

    const details = screen.getByTestId('action-history-detail-0')
    expect(details).not.toHaveAttribute('open')
    fireEvent.click(within(details).getByText('Detail'))
    expect(details).toHaveAttribute('open')
    expect(within(details).getByText(detail)).toBeInTheDocument()
  })

  it('wraps long mobile detail instead of widening the history container', () => {
    const detail = `failure:${'x'.repeat(200)}`
    render(
      <ActionHistoryTable
        rows={[{ turn: 1, action: 'train', facility: 'speed', detail }]}
      />
    )

    expect(within(screen.getByTestId('action-history-detail-0')).getByText(detail)).toHaveClass(
      '[overflow-wrap:anywhere]'
    )
  })

  it('autoscrolls new rows when already within 48px of the bottom', () => {
    const initialRows = rows.slice(0, 1)
    const { rerender } = render(<ActionHistoryTable rows={initialRows} />)
    const viewport = screen.getByTestId('action-history-scroll')
    Object.defineProperties(viewport, {
      scrollTop: { configurable: true, value: 720, writable: true },
      scrollHeight: { configurable: true, value: 1000, writable: true },
      clientHeight: { configurable: true, value: 240 },
    })
    fireEvent.scroll(viewport)

    Object.defineProperty(viewport, 'scrollHeight', {
      configurable: true,
      value: 1200,
      writable: true,
    })
    rerender(<ActionHistoryTable rows={[...initialRows, rows[1]]} />)

    expect(viewport.scrollTop).toBe(1200)
    expect(screen.queryByRole('button', { name: 'Jump to latest' })).not.toBeInTheDocument()
  })

  it('does not autoscroll while reading older rows and offers a jump to latest action', () => {
    const initialRows = rows.slice(0, 1)
    const { rerender } = render(<ActionHistoryTable rows={initialRows} />)
    const viewport = screen.getByTestId('action-history-scroll')
    Object.defineProperties(viewport, {
      scrollTop: { configurable: true, value: 200, writable: true },
      scrollHeight: { configurable: true, value: 1000, writable: true },
      clientHeight: { configurable: true, value: 240 },
    })
    fireEvent.scroll(viewport)

    expect(screen.getByRole('button', { name: 'Jump to latest' })).toBeInTheDocument()
    Object.defineProperty(viewport, 'scrollHeight', {
      configurable: true,
      value: 1200,
      writable: true,
    })
    rerender(<ActionHistoryTable rows={[...initialRows, rows[1]]} />)

    expect(viewport.scrollTop).toBe(200)
    fireEvent.click(screen.getByRole('button', { name: 'Jump to latest' }))
    expect(viewport.scrollTop).toBe(1200)
    expect(screen.queryByRole('button', { name: 'Jump to latest' })).not.toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// 4. StatsRow
// ---------------------------------------------------------------------------

describe('StatsRow', () => {
  it('renders nothing when no rows have stats', () => {
    const rows: ActionHistoryRow[] = [
      { turn: 1, action: 'train', facility: 'speed', detail: 'training speed' },
    ]
    const { container } = wrap(<StatsRow rows={rows} />)
    expect(container.firstChild).toBeNull()
  })

  it('renders nothing when rows array is empty', () => {
    const { container } = wrap(<StatsRow rows={[]} />)
    expect(container.firstChild).toBeNull()
  })

  it('shows HP and max_hp from the last row with stats', () => {
    const rows: ActionHistoryRow[] = [
      {
        turn: 1,
        action: 'train',
        facility: 'speed',
        detail: '',
        stats: { hp: 60, max_hp: 100 },
      },
    ]
    wrap(<StatsRow rows={rows} />)
    expect(screen.getByTestId('stats-row')).toBeInTheDocument()
    expect(screen.getByText('60/100')).toBeInTheDocument()
  })

  it('shows HP bar width proportional to hp/max_hp', () => {
    const rows: ActionHistoryRow[] = [
      {
        turn: 1,
        action: 'train',
        facility: 'speed',
        detail: '',
        stats: { hp: 50, max_hp: 100 },
      },
    ]
    wrap(<StatsRow rows={rows} />)
    const bar = screen.getByTestId('hp-bar')
    expect(bar).toHaveStyle({ width: '50%' })
  })

  it('shows stat values for SPD/STA/PWR/GUT/WIT/SP', () => {
    const rows: ActionHistoryRow[] = [
      {
        turn: 1,
        action: 'train',
        facility: 'speed',
        detail: '',
        stats: { hp: 80, max_hp: 100, motivation: 3, speed: 400, stamina: 300, power: 250, guts: 200, wit: 150, skill_point: 500 },
      },
    ]
    wrap(<StatsRow rows={rows} />)
    expect(screen.getByText('400')).toBeInTheDocument() // SPD
    expect(screen.getByText('300')).toBeInTheDocument() // STA
    expect(screen.getByText('250')).toBeInTheDocument() // PWR
    expect(screen.getByText('200')).toBeInTheDocument() // GUT
    expect(screen.getByText('150')).toBeInTheDocument() // WIT
    expect(screen.getByText('500')).toBeInTheDocument() // SP
  })

  it('uses the LAST row with stats (not the first)', () => {
    const rows: ActionHistoryRow[] = [
      {
        turn: 1,
        action: 'train',
        facility: 'speed',
        detail: '',
        stats: { hp: 50, max_hp: 100 },
      },
      {
        turn: 2,
        action: 'train',
        facility: 'stamina',
        detail: '',
        stats: { hp: 90, max_hp: 100 },
      },
    ]
    wrap(<StatsRow rows={rows} />)
    // Should show 90 (last), not 50 (first)
    expect(screen.getByText('90/100')).toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// 5. BackoffBanner
// ---------------------------------------------------------------------------

describe('BackoffBanner', () => {
  it('renders the backoff message', () => {
    render(<BackoffBanner />)
    expect(screen.getByTestId('backoff-banner')).toBeInTheDocument()
    expect(screen.getByText(/Auto-backoff/)).toBeInTheDocument()
    expect(screen.getByText(/protect your account/)).toBeInTheDocument()
  })

  it('is rendered when circuit_tripped is true (consumer decision — verify text)', () => {
    // BackoffBanner itself is pure; Dashboard controls visibility.
    // Just verify the message content is correct.
    render(<BackoffBanner />)
    expect(screen.getByText(/intentional, not a crash/)).toBeInTheDocument()
  })

  it('shows the pending automatic resume attempt during cooldown', () => {
    render(
      <BackoffBanner
        retryWaiting
        retryAttempt={2}
        retryLimit={3}
        retryWaitSeconds={900}
      />,
    )

    expect(screen.getByText(/waiting 15 minutes/i)).toBeInTheDocument()
    expect(screen.getByText(/attempt 2\/3/i)).toBeInTheDocument()
    expect(screen.getByText(/Stop remains available/i)).toBeInTheDocument()
  })
})
