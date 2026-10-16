/**
 * Tests for Task 8 dashboard run controls.
 *
 * Coverage:
 *   1. runCountHint: -1 → SP dump stop, 0 → infinite, 1 → "1 career", n → "n careers"
 *   2. getStartMissingReason: disabled when preset missing / selection incomplete;
 *      enabled when activeCareer + preset
 *   3. buildRunBody: pure function, both active and new-career branches
 *   4. RunOptions: hydrates No CD / delay values from the backend on mount
 *   5. RunOptions: live burn-clocks success, rollback failures, and idle behavior
 */

import { beforeEach, describe, it, expect, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { RunOptions } from './RunOptions'
import {
  runCountHint,
  getStartMissingReason,
  getParentSelectionError,
} from './runRules'
import { buildRunBody } from './runBody'
import type {
  DeckInfo,
  FriendInfo,
  TraineeInfo,
  ParentInfo,
  RunCareerResumeBody,
  RunCareerNewBody,
} from '@/api/types'

// ---------------------------------------------------------------------------
// Component mocks
// ---------------------------------------------------------------------------

const componentMocks = vi.hoisted(() => {
  const runSettings = {
    delayMin: 1.6,
    delayMax: 3.7,
    noCd: false,
    runCount: 1,
    eventEnabled: false,
    eventLevel: 1,
    eventBoost: false,
    burnClocks: false,
    twoPalDeck: false,
    sparkReroll: false,
    setDelay: vi.fn(),
    setNoCd: vi.fn(),
    setRunCount: vi.fn(),
    setEvent: vi.fn(),
    setBurnClocks: vi.fn(),
    setTwoPalDeck: vi.fn(),
    setSparkReroll: vi.fn(),
  }
  const selection = { setEvent: vi.fn() }
  const useRunSettings = Object.assign(vi.fn(() => runSettings), {
    getState: vi.fn(() => runSettings),
  })

  return {
    runSettings,
    selection,
    useRunSettings,
    useSelection: vi.fn(() => selection),
    useSession: vi.fn(),
    useRunner: vi.fn(),
    getTurnDelay: vi.fn(),
    saveTurnDelay: vi.fn(),
    getEventInfo: vi.fn(),
    apiBurnClocks: vi.fn(),
    toastError: vi.fn(),
  }
})

vi.mock('@/stores/runSettings', () => ({
  useRunSettings: componentMocks.useRunSettings,
}))

vi.mock('@/stores/selection', () => ({
  useSelection: componentMocks.useSelection,
}))

vi.mock('@/hooks/useSession', () => ({
  useSession: componentMocks.useSession,
}))

vi.mock('@/hooks/useRunner', () => ({
  useRunner: componentMocks.useRunner,
}))

vi.mock('@/api/settings', () => ({
  getTurnDelay: componentMocks.getTurnDelay,
  saveTurnDelay: componentMocks.saveTurnDelay,
}))

vi.mock('@/api/career', () => ({
  getEventInfo: componentMocks.getEventInfo,
  setBurnClocks: componentMocks.apiBurnClocks,
}))

vi.mock('sonner', () => ({
  toast: { error: componentMocks.toastError },
}))

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const deck: DeckInfo = {
  id: 7,
  name: 'Test Deck',
  cards: [
    { id: '10001' },
    { id: '10002' },
    { id: '10003' },
    { id: '10004' },
    { id: '10005' },
    { id: '10006' },
  ],
}

const friend: FriendInfo = {
  viewer_id: 1234567,
  support_card_id: 30165,
  support_name: 'Test Friend',
}

const trainee: TraineeInfo = {
  id: '100101',
  name: 'Test Trainee',
}

const vet1: ParentInfo = {
  instance_id: 111,
  card_id: 100201,
  tree: {
    self: { card_id: 100201 },
  },
}

const vet2: ParentInfo = {
  instance_id: 222,
  card_id: 100301,
  tree: {
    self: { card_id: 100301 },
  },
}

// ---------------------------------------------------------------------------
// runCountHint tests
// ---------------------------------------------------------------------------

describe('runCountHint', () => {
  it('returns SP dump stop hint for -1', () => {
    expect(runCountHint(-1)).toBe('SP dump stop (no finish submit)')
  })

  it('returns ∞ (infinite) for 0', () => {
    expect(runCountHint(0)).toBe('∞ (infinite)')
  })

  it('returns "1 career" for 1', () => {
    expect(runCountHint(1)).toBe('1 career')
  })

  it('returns "n careers" for n > 1', () => {
    expect(runCountHint(3)).toBe('3 careers')
    expect(runCountHint(10)).toBe('10 careers')
    expect(runCountHint(99)).toBe('99 careers')
  })
})

// ---------------------------------------------------------------------------
// getStartMissingReason tests
// ---------------------------------------------------------------------------

describe('getStartMissingReason', () => {
  const fullSelection = {
    selectedPreset: 'MyPreset',
    activeCareer: false,
    deck,
    friend,
    trainee,
    veterans: [vet1, vet2],
  }

  it('does NOT require a preset — returns empty when preset is empty but all team selected', () => {
    expect(
      getStartMissingReason({ ...fullSelection, selectedPreset: '' })
    ).toBe('')
  })

  it('returns empty when activeCareer (no selection needed at all)', () => {
    expect(
      getStartMissingReason({
        ...fullSelection,
        activeCareer: true,
        deck: null,
        friend: null,
        trainee: null,
        veterans: [],
      })
    ).toBe('')
  })

  it('returns "Select a deck" when deck is missing', () => {
    expect(
      getStartMissingReason({ ...fullSelection, deck: null })
    ).toBe('Select a deck')
  })

  it('returns "Select a friend support" when friend is missing', () => {
    expect(
      getStartMissingReason({ ...fullSelection, friend: null })
    ).toBe('Select a friend support')
  })

  it('returns "Select a trainee" when trainee is missing', () => {
    expect(
      getStartMissingReason({ ...fullSelection, trainee: null })
    ).toBe('Select a trainee')
  })

  it('returns "Select two parents" when fewer than 2 veterans', () => {
    expect(
      getStartMissingReason({ ...fullSelection, veterans: [vet1] })
    ).toBe('Select two parents')
  })

  it('returns "Direct parent is trainee" when a parent card_id matches trainee', () => {
    const matchingVet: ParentInfo = {
      instance_id: 333,
      card_id: Number(trainee.id),
      tree: {
        self: { card_id: Number(trainee.id) },
      },
    }
    expect(
      getStartMissingReason({ ...fullSelection, veterans: [matchingVet, vet2] })
    ).toBe('Direct parent is trainee')
  })

  it('returns empty string when all conditions met', () => {
    expect(getStartMissingReason(fullSelection)).toBe('')
  })
})

// ---------------------------------------------------------------------------
// buildRunBody tests
// ---------------------------------------------------------------------------

describe('buildRunBody — resume (activeCareer=true)', () => {
  it('builds correct resume body with exact field values', () => {
    const body = buildRunBody({
      activeCareer: true,
      selectedPreset: 'SpeedPreset',
      burnClocks: true,
      twoPalDeck: true,
      sparkReroll: true,
      runCount: 5,
    }) as RunCareerResumeBody

    expect(body.preset_name).toBe('SpeedPreset')
    expect(body.max_steps).toBe(2500)
    expect(body.burn_clocks).toBe(true)
    expect(body.two_pal_deck).toBe(true)
    expect(body.spark_reroll).toBe(true)
    expect(body.run_count).toBe(5)
    // Should NOT have card_id (new career field)
    expect((body as unknown as Record<string, unknown>).card_id).toBeUndefined()
  })

  it('build with burnClocks=false and run_count=0 (infinite)', () => {
    const body = buildRunBody({
      activeCareer: true,
      selectedPreset: 'AnyPreset',
      burnClocks: false,
      twoPalDeck: false,
      sparkReroll: false,
      runCount: 0,
    }) as RunCareerResumeBody

    expect(body.burn_clocks).toBe(false)
    expect(body.two_pal_deck).toBe(false)
    expect(body.spark_reroll).toBe(false)
    expect(body.run_count).toBe(0)
  })

  it('passes run_count=-1 for SP dump stop mode', () => {
    const body = buildRunBody({
      activeCareer: true,
      selectedPreset: 'AnyPreset',
      burnClocks: false,
      twoPalDeck: false,
      sparkReroll: false,
      runCount: -1,
    }) as RunCareerResumeBody

    expect(body.run_count).toBe(-1)
  })
})

describe('buildRunBody — new career (activeCareer=false)', () => {
  const baseArgs = {
    activeCareer: false,
    selectedPreset: 'SpeedPreset',
    burnClocks: false,
    twoPalDeck: false,
    sparkReroll: false,
    runCount: 1,
    trainee,
    deck,
    friend,
    veterans: [vet1, vet2],
    rental: null,
  }

  it('builds correct new-career body with all required fields as numbers', () => {
    const body = buildRunBody(baseArgs) as RunCareerNewBody

    expect(body.card_id).toBe(100101)
    expect(typeof body.card_id).toBe('number')

    expect(body.support_card_ids).toEqual([10001, 10002, 10003, 10004, 10005, 10006])
    expect(body.support_card_ids.every((x) => typeof x === 'number')).toBe(true)

    expect(body.friend_viewer_id).toBe(1234567)
    expect(body.friend_card_id).toBe(30165)

    expect(body.parent_id_1).toBe(111)
    expect(body.parent_id_2).toBe(222)

    expect(body.deck_id).toBe(7)

    // Constant fields
    expect(body.scenario_id).toBe(4)
    expect(body.use_tp).toBe(30)
    expect(body.difficulty_id).toBe(0)
    expect(body.difficulty).toBe(0)
    expect(body.is_boost).toBe(0)
    expect(body.boost_story_event_id).toBe(0)

    expect(body.preset_name).toBe('SpeedPreset')
    expect(body.max_steps).toBe(2500)
    expect(body.burn_clocks).toBe(false)
    expect(body.two_pal_deck).toBe(false)
    expect(body.spark_reroll).toBe(false)
    expect(body.run_count).toBe(1)
    expect(body.rental_friend_viewer_id).toBe(0)
  })

  it('includes non-zero rental_friend_viewer_id when rental is set', () => {
    const body = buildRunBody({ ...baseArgs, rental: 9876543 }) as RunCareerNewBody
    expect(body.rental_friend_viewer_id).toBe(9876543)
  })

  it('builds Unity Cup new-career body with 30 TP', () => {
    const body = buildRunBody({ ...baseArgs, scenarioId: 2 }) as RunCareerNewBody
    expect(body.scenario_id).toBe(2)
    expect(body.use_tp).toBe(30)
  })

  it('builds Grand Live new-career body', () => {
    const body = buildRunBody({ ...baseArgs, scenarioId: 3 }) as RunCareerNewBody
    expect(body.scenario_id).toBe(3)
  })

  it('passes the scenario id straight through', () => {
    // buildRunBody does not validate: the store's setScenarioId /
    // normalizeScenarioId is the single validation point (see
    // runSettings.test.ts), so anything reaching here is already a runnable id.
    const body = buildRunBody({ ...baseArgs, scenarioId: 99 }) as RunCareerNewBody
    expect(body.scenario_id).toBe(99)
  })

  it('throws when selection is incomplete', () => {
    expect(() =>
      buildRunBody({ ...baseArgs, trainee: null })
    ).toThrow('Incomplete selection')
  })
})

// ---------------------------------------------------------------------------
// runRules: getParentSelectionError edge cases
// ---------------------------------------------------------------------------

describe('getParentSelectionError', () => {
  it('returns empty when no trainee', () => {
    expect(getParentSelectionError({ trainee: null, veterans: [vet1, vet2] })).toBe('')
  })

  it('returns empty when fewer than 2 veterans', () => {
    expect(getParentSelectionError({ trainee, veterans: [vet1] })).toBe('')
  })

  it('returns "Direct parent is trainee" when parent tree.self.card_id equals trainee id', () => {
    const matchingVet: ParentInfo = {
      instance_id: 999,
      tree: { self: { card_id: Number(trainee.id) } },
    }
    expect(
      getParentSelectionError({ trainee, veterans: [matchingVet, vet2] })
    ).toBe('Direct parent is trainee')
  })
})

// ---------------------------------------------------------------------------
// RunOptions component tests
// ---------------------------------------------------------------------------

describe('RunOptions component', () => {
  function renderRunOptions() {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    return render(
      <QueryClientProvider client={queryClient}>
        <RunOptions />
      </QueryClientProvider>
    )
  }

  async function waitForMountEffects() {
    await waitFor(() => {
      expect(componentMocks.getTurnDelay).toHaveBeenCalledTimes(1)
      expect(componentMocks.getEventInfo).toHaveBeenCalledTimes(1)
      expect(screen.queryByText('No event is currently active.')).not.toBeInTheDocument()
    })
  }

  beforeEach(() => {
    vi.clearAllMocks()
    Object.assign(componentMocks.runSettings, {
      delayMin: 1.6,
      delayMax: 3.7,
      noCd: false,
      runCount: 1,
      eventEnabled: false,
      eventLevel: 1,
      eventBoost: false,
      burnClocks: false,
      twoPalDeck: false,
      sparkReroll: false,
    })
    componentMocks.useRunSettings.mockReturnValue(componentMocks.runSettings)
    componentMocks.useRunSettings.getState.mockReturnValue(componentMocks.runSettings)
    componentMocks.useSelection.mockReturnValue(componentMocks.selection)
    componentMocks.useSession.mockReturnValue({ data: { success: true } })
    componentMocks.useRunner.mockReturnValue({
      data: { runner: { running: false, burn_clocks: false } },
    })
    componentMocks.getTurnDelay.mockResolvedValue({
      disabled: false,
      min: 1.6,
      max: 3.7,
    })
    componentMocks.saveTurnDelay.mockResolvedValue({
      disabled: false,
      min: 1.6,
      max: 3.7,
    })
    componentMocks.getEventInfo.mockResolvedValue({
      success: true,
      available: true,
      max_level: 1,
    })
    componentMocks.apiBurnClocks.mockResolvedValue({ success: true })
  })

  it('hydrates No CD from the backend disabled state on mount', async () => {
    componentMocks.getTurnDelay.mockResolvedValueOnce({
      disabled: true,
      min: 0,
      max: 0,
    })

    renderRunOptions()

    await waitForMountEffects()
    await waitFor(() => {
      expect(componentMocks.runSettings.setNoCd).toHaveBeenCalledWith(true)
    })
    expect(componentMocks.runSettings.setDelay).not.toHaveBeenCalled()
  })

  it('hydrates backend delay values on mount when No CD is disabled', async () => {
    componentMocks.getTurnDelay.mockResolvedValueOnce({
      disabled: false,
      min: 2.5,
      max: 6,
    })

    renderRunOptions()

    await waitForMountEffects()
    await waitFor(() => {
      expect(componentMocks.runSettings.setDelay).toHaveBeenCalledWith(2.5, 6)
    })
    expect(componentMocks.runSettings.setNoCd).not.toHaveBeenCalled()
  })

  it('renders boolean options as TouchControlRows whose labels activate the controls', async () => {
    renderRunOptions()
    await waitForMountEffects()

    const labels = [
      'No CD (zero delays)',
      'Burn Clocks',
      '2Pal Deck',
      'Spark Reroll (30 TP)',
      'Event Mode',
    ]
    for (const label of labels) {
      expect(screen.getByText(label).closest('[data-slot="touch-control-row"]')).toBeInTheDocument()
    }

    fireEvent.click(screen.getByText('No CD (zero delays)'))
    expect(componentMocks.runSettings.setNoCd).toHaveBeenCalledWith(true)
  })

  it('shows an event disabled reason as visible text without a hover title', async () => {
    componentMocks.getEventInfo.mockResolvedValueOnce({
      success: true,
      available: false,
      max_level: 0,
    })

    renderRunOptions()

    const reason = await screen.findByText('No event is currently active.')
    const row = screen.getByText('Event Mode').closest('[data-slot="touch-control-row"]')
    expect(reason).toBeVisible()
    expect(row).toHaveAttribute('data-disabled', 'true')
    expect(screen.getByText('Event Mode')).not.toHaveAttribute('title')
  })

  it('uses a TouchControlRow for the event boost checkbox', async () => {
    componentMocks.runSettings.eventEnabled = true
    renderRunOptions()
    await waitForMountEffects()

    const boostLabel = screen.getByText('Boost')
    expect(boostLabel.closest('[data-slot="touch-control-row"]')).toBeInTheDocument()
    fireEvent.click(boostLabel)
    expect(componentMocks.runSettings.setEvent).toHaveBeenCalledWith({
      enabled: true,
      level: 1,
      boost: true,
    })
  })

  it('posts burn clocks without reverting or toasting while the runner is running', async () => {
    componentMocks.useRunner.mockReturnValue({
      data: { runner: { running: true, burn_clocks: false } },
    })

    renderRunOptions()
    await waitForMountEffects()

    fireEvent.click(screen.getByRole('switch', { name: 'Burn Clocks' }))

    await waitFor(() => {
      expect(componentMocks.apiBurnClocks).toHaveBeenCalledWith({ burn_clocks: true })
    })
    await act(async () => {
      await Promise.resolve()
    })
    expect(componentMocks.runSettings.setBurnClocks).toHaveBeenCalledTimes(1)
    expect(componentMocks.runSettings.setBurnClocks).toHaveBeenCalledWith(true)
    expect(componentMocks.toastError).not.toHaveBeenCalled()
  })

  it('reverts burn clocks and toasts when the live API rejects', async () => {
    componentMocks.useRunner.mockReturnValue({
      data: { runner: { running: true, burn_clocks: false } },
    })
    componentMocks.apiBurnClocks.mockRejectedValueOnce(new Error('offline'))

    renderRunOptions()
    await waitForMountEffects()

    fireEvent.click(screen.getByRole('switch', { name: 'Burn Clocks' }))

    await waitFor(() => {
      expect(componentMocks.apiBurnClocks).toHaveBeenCalledWith({ burn_clocks: true })
      expect(componentMocks.toastError).toHaveBeenCalledWith('offline')
      expect(componentMocks.runSettings.setBurnClocks).toHaveBeenNthCalledWith(1, true)
      expect(componentMocks.runSettings.setBurnClocks).toHaveBeenNthCalledWith(2, false)
    })
    expect(componentMocks.runSettings.setBurnClocks).toHaveBeenCalledTimes(2)
  })

  it('reverts burn clocks and toasts when the live API reports failure', async () => {
    componentMocks.useRunner.mockReturnValue({
      data: { runner: { running: true, burn_clocks: false } },
    })
    componentMocks.apiBurnClocks.mockResolvedValueOnce({
      success: false,
      detail: 'nope',
    })

    renderRunOptions()
    await waitForMountEffects()

    fireEvent.click(screen.getByRole('switch', { name: 'Burn Clocks' }))

    await waitFor(() => {
      expect(componentMocks.apiBurnClocks).toHaveBeenCalledWith({ burn_clocks: true })
      expect(componentMocks.toastError).toHaveBeenCalledWith('nope')
      expect(componentMocks.runSettings.setBurnClocks).toHaveBeenNthCalledWith(1, true)
      expect(componentMocks.runSettings.setBurnClocks).toHaveBeenNthCalledWith(2, false)
    })
    expect(componentMocks.runSettings.setBurnClocks).toHaveBeenCalledTimes(2)
  })

  it('updates burn clocks locally without calling the API when the runner is idle', async () => {
    renderRunOptions()
    await waitForMountEffects()

    fireEvent.click(screen.getByRole('switch', { name: 'Burn Clocks' }))

    expect(componentMocks.runSettings.setBurnClocks).toHaveBeenCalledTimes(1)
    expect(componentMocks.runSettings.setBurnClocks).toHaveBeenCalledWith(true)
    expect(componentMocks.apiBurnClocks).not.toHaveBeenCalled()
    expect(componentMocks.toastError).not.toHaveBeenCalled()
  })
})
