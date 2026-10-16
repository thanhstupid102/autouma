import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import Events from './Events'

// ---------------------------------------------------------------------------
// Mock api/events
// ---------------------------------------------------------------------------

vi.mock('@/api/events', () => ({
  getEventCatalog: vi.fn(),
  getEventPrefs: vi.fn(),
  saveEventPrefs: vi.fn(),
  rebuildEventCatalog: vi.fn(),
  updateEventDatabase: vi.fn(),
}))

import * as eventsApi from '@/api/events'

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const MULTI_CHOICE_EVENT = {
  story_id: 'story_001',
  chara_id: 1,
  support_card_id: 10,
  n_choices: 3,
  select_indexes: [0, 1, 2],
  source: 'support' as const,
  label: 'Multi Choice Event',
  name: 'Named Multi Choice Event',
  seen_count: 5,
  choice_effects: [
    { select_index: 0, label: 'Choice A', effect: 'Speed +10' },
    { select_index: 1, label: 'Choice B', effect: 'Stamina +10' },
    { select_index: 2, label: 'Choice C', effect: 'Power +10' },
  ],
  recommended_choice: 1,
}

const SINGLE_CHOICE_EVENT = {
  story_id: 'story_002',
  chara_id: 2,
  support_card_id: 20,
  n_choices: 1,
  select_indexes: [0],
  source: 'chara' as const,
  label: 'Single Choice Event',
  seen_count: 2,
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeQC() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
}

function renderEvents(qc?: QueryClient) {
  const client = qc ?? makeQC()
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/events']}>
        <Events />
      </MemoryRouter>
    </QueryClientProvider>
  )
}

async function waitForEventPresentations() {
  await waitFor(() => {
    expect(screen.getByTestId('event-row-story_001')).toBeInTheDocument()
    expect(screen.getByTestId('event-card-story_001')).toBeInTheDocument()
  })

  return {
    mobile: screen.getByTestId('events-mobile'),
    desktop: screen.getByTestId('events-desktop'),
  }
}

async function selectChoice(
  presentation: HTMLElement,
  storyId: string,
  choiceLabel: string,
) {
  fireEvent.click(
    within(presentation).getByRole('combobox', { name: `Choice for ${storyId}` })
  )

  const option = await screen.findByRole('option', { name: new RegExp(`^${choiceLabel}`) })
  fireEvent.click(option)
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks()

  vi.mocked(eventsApi.getEventCatalog).mockResolvedValue({
    success: true,
    events: [MULTI_CHOICE_EVENT, SINGLE_CHOICE_EVENT],
  })

  vi.mocked(eventsApi.getEventPrefs).mockResolvedValue({
    success: true,
    prefs: {},
  })

  vi.mocked(eventsApi.saveEventPrefs).mockResolvedValue({ success: true })
  vi.mocked(eventsApi.rebuildEventCatalog).mockResolvedValue({ success: true, count: 2 })
  vi.mocked(eventsApi.updateEventDatabase).mockResolvedValue({
    success: true,
    events: 100,
    multi: 80,
    count: 100,
  })
})

describe('Events page', () => {
  it('renders multi-choice event rows from catalog', async () => {
    renderEvents()

    const { mobile, desktop } = await waitForEventPresentations()

    expect(within(mobile).getByText('story_001')).toBeInTheDocument()
    expect(within(desktop).getByText('story_001')).toBeInTheDocument()
  })

  it('shows single-choice events by default', async () => {
    renderEvents()

    const { mobile, desktop } = await waitForEventPresentations()

    expect(within(mobile).getByText('Single Choice Event')).toBeInTheDocument()
    expect(within(desktop).getByText('Single Choice Event')).toBeInTheDocument()
  })

  it('hides single-choice events when toggle is disabled', async () => {
    renderEvents()

    const { mobile, desktop } = await waitForEventPresentations()

    const toggle = screen.getByRole('switch', { name: /single/i })
    fireEvent.click(toggle)

    await waitFor(() => {
      expect(screen.queryByText('Single Choice Event')).not.toBeInTheDocument()
    })
    expect(within(mobile).getByText('Named Multi Choice Event')).toBeInTheDocument()
    expect(within(desktop).getByText('Named Multi Choice Event')).toBeInTheDocument()
  })

  it('changing a choice to "Choice 2" then Save calls saveEventPrefs with {story_id: 1}', async () => {
    renderEvents()

    const { desktop } = await waitForEventPresentations()
    await selectChoice(desktop, 'story_001', 'Choice 2')

    const saveBtn = screen.getByRole('button', { name: /^save$/i })
    fireEvent.click(saveBtn)

    await waitFor(() => {
      expect(eventsApi.saveEventPrefs).toHaveBeenCalledWith({ story_001: 1 })
    })
  })

  it('submits the same 0-based choice value from the card and table presentations', async () => {
    const desktopRender = renderEvents()
    const { desktop } = await waitForEventPresentations()
    await selectChoice(desktop, 'story_001', 'Choice 2')
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))

    await waitFor(() => expect(eventsApi.saveEventPrefs).toHaveBeenCalledTimes(1))
    const desktopPayload = vi.mocked(eventsApi.saveEventPrefs).mock.calls[0][0]
    desktopRender.unmount()

    vi.mocked(eventsApi.saveEventPrefs).mockClear()
    vi.mocked(eventsApi.saveEventPrefs).mockResolvedValue({ success: true })

    renderEvents()
    const { mobile } = await waitForEventPresentations()
    await selectChoice(mobile, 'story_001', 'Choice 2')
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))

    await waitFor(() => expect(eventsApi.saveEventPrefs).toHaveBeenCalledTimes(1))
    const mobilePayload = vi.mocked(eventsApi.saveEventPrefs).mock.calls[0][0]

    expect(desktopPayload.story_001).toBe(1)
    expect(mobilePayload.story_001).toBe(desktopPayload.story_001)
  })

  it('selecting "Auto" removes the story_id from the saved payload', async () => {
    // Pre-populate prefs with story_001 = 2 (Choice 3)
    vi.mocked(eventsApi.getEventPrefs).mockResolvedValue({
      success: true,
      prefs: { story_001: 2 },
    })

    renderEvents()

    const { desktop } = await waitForEventPresentations()

    await selectChoice(desktop, 'story_001', 'Auto')

    // Click Save
    const saveBtn = screen.getByRole('button', { name: /^save$/i })
    fireEvent.click(saveBtn)

    await waitFor(() => {
      // story_001 must NOT be present in the saved prefs (Auto = delete key)
      const callArg = vi.mocked(eventsApi.saveEventPrefs).mock.calls[0][0]
      expect(callArg).not.toHaveProperty('story_001')
    })
  })

  it('shows empty state when catalog has no events', async () => {
    vi.mocked(eventsApi.getEventCatalog).mockResolvedValue({
      success: true,
      events: [],
    })

    renderEvents()

    await waitFor(() => {
      expect(screen.getByText(/no events captured yet/i)).toBeInTheDocument()
    })
  })

  // ---------------------------------------------------------------------------
  // Update Event Database button
  // ---------------------------------------------------------------------------

  it('renders the Update Event Database button', async () => {
    renderEvents()

    await waitForEventPresentations()

    expect(
      screen.getByRole('button', { name: /update event database/i })
    ).toBeInTheDocument()
  })

  it('clicking Update Event Database calls updateEventDatabase', async () => {
    renderEvents()

    await waitForEventPresentations()

    const btn = screen.getByRole('button', { name: /update event database/i })
    fireEvent.click(btn)

    await waitFor(() => {
      expect(eventsApi.updateEventDatabase).toHaveBeenCalledTimes(1)
    })
  })

  it('Update Event Database button shows Updating… while pending', async () => {
    // Never resolve so it stays pending
    vi.mocked(eventsApi.updateEventDatabase).mockImplementation(
      () => new Promise(() => {})
    )

    renderEvents()

    await waitForEventPresentations()

    const btn = screen.getByRole('button', { name: /update event database/i })
    fireEvent.click(btn)

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /updating/i })).toBeInTheDocument()
    })
  })

  it('invalidates events-catalog after successful update', async () => {
    const qc = makeQC()
    const invalidateSpy = vi.spyOn(qc, 'invalidateQueries')

    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={['/events']}>
          <Events />
        </MemoryRouter>
      </QueryClientProvider>
    )

    await waitForEventPresentations()

    fireEvent.click(screen.getByRole('button', { name: /update event database/i }))

    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith(
        expect.objectContaining({ queryKey: ['events-catalog'] })
      )
    })
  })

  it('renders complete cards below md and the unchanged table at md and above', async () => {
    renderEvents()
    const { mobile, desktop } = await waitForEventPresentations()

    expect(mobile).toHaveClass('md:hidden')
    expect(desktop).toHaveClass('hidden', 'md:block')

    for (const presentation of [mobile, desktop]) {
      expect(within(presentation).getByText('support')).toBeInTheDocument()
      expect(within(presentation).getByText('Named Multi Choice Event')).toBeInTheDocument()
      expect(within(presentation).getAllByText(/Multi Choice Event/)).toHaveLength(2)
      expect(within(presentation).getByText('story_001')).toBeInTheDocument()
      expect(within(presentation).getByText('5×')).toBeInTheDocument()
      expect(within(presentation).getByText('Speed +10')).toBeInTheDocument()
      expect(within(presentation).getByText('Stamina +10')).toBeInTheDocument()
      expect(
        within(presentation).getByRole('combobox', { name: 'Choice for story_001' })
      ).toBeInTheDocument()
    }

    const effects = within(mobile).getByTestId('event-card-effects-story_001')
    expect(effects).not.toHaveAttribute('open')
    fireEvent.click(within(effects).getByText('Choice effects (3)'))
    expect(effects).toHaveAttribute('open')
  })

  it('keeps the phone layout contained without an intentionally wide region', async () => {
    renderEvents()
    const { mobile, desktop } = await waitForEventPresentations()
    const page = screen.getByTestId('events-page')

    expect(page).toHaveClass('min-w-0')
    expect(mobile).toHaveClass('min-w-0', 'md:hidden')
    expect(desktop).toHaveClass('hidden', 'overflow-hidden', 'md:block')
    for (const card of within(mobile).getAllByRole('article')) {
      expect(card).toHaveClass('min-w-0', 'overflow-hidden')
    }
    expect(page.querySelector('[data-slot="overflow-frame"]')).toBeNull()
  })

  it('keeps search at 16px on mobile and inherits 44px touch controls', async () => {
    renderEvents()
    const { mobile } = await waitForEventPresentations()

    expect(screen.getByRole('textbox', { name: 'Search events' })).toHaveClass(
      'text-base',
      'md:text-xs',
    )

    for (const filter of within(
      screen.getByRole('group', { name: 'Event source filter' })
    ).getAllByRole('button')) {
      expect(filter).toHaveClass('h-11', 'md:h-6')
    }

    expect(
      within(mobile).getByRole('combobox', { name: 'Choice for story_001' })
    ).toHaveClass('h-11', 'md:data-[size=sm]:h-7')
    expect(document.querySelector('[data-slot="touch-control-row"]')).toHaveClass('min-h-11')
  })

  it('breaks a long story_id inside the card instead of widening it', async () => {
    const longStoryId = `story_${'x'.repeat(180)}`
    vi.mocked(eventsApi.getEventCatalog).mockResolvedValue({
      success: true,
      events: [{ ...MULTI_CHOICE_EVENT, story_id: longStoryId }],
    })

    renderEvents()
    await waitFor(() => expect(screen.getByTestId(`event-card-${longStoryId}`)).toBeInTheDocument())

    expect(screen.getByTestId(`event-card-story-id-${longStoryId}`)).toHaveClass(
      'min-w-0',
      '[overflow-wrap:anywhere]',
    )
  })

  it('keeps pagination and save reachable alongside the card presentation', async () => {
    const events = Array.from({ length: 51 }, (_, index) => ({
      ...MULTI_CHOICE_EVENT,
      story_id: `story_${String(index + 1).padStart(3, '0')}`,
      label: `Event ${index + 1}`,
      name: undefined,
    }))
    vi.mocked(eventsApi.getEventCatalog).mockResolvedValue({ success: true, events })

    renderEvents()
    await waitFor(() => expect(screen.getByTestId('event-card-story_001')).toBeInTheDocument())

    const actions = screen.getByTestId('events-actions')
    const pagination = screen.getByTestId('events-pagination')
    const save = within(actions).getByRole('button', { name: 'Save' })

    expect(actions).toHaveClass('w-full', 'md:w-auto')
    expect(pagination).not.toHaveClass('hidden')
    expect(save).toBeVisible()
    expect(within(pagination).getByRole('button', { name: 'Prev' })).toBeDisabled()

    fireEvent.click(within(pagination).getByRole('button', { name: 'Next' }))
    expect(await screen.findByTestId('event-card-story_051')).toBeInTheDocument()
  })
})
