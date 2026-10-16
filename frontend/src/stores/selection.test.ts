import { describe, it, expect, vi, beforeEach } from 'vitest'
import { useSelection } from './selection'
import type { DeckInfo, FriendInfo, TraineeInfo, ParentInfo } from '../api/types'

// Stub fetch globally so syncSelectionToServer does not make real HTTP calls
const mockFetch = vi.fn()
beforeEach(() => {
  vi.stubGlobal('fetch', mockFetch.mockResolvedValue(new Response(JSON.stringify({ success: true }))))
  // Reset store to defaults before each test
  useSelection.getState().clear()
  mockFetch.mockClear()
})

const deck: DeckInfo = { id: 1, name: 'Deck 1', cards: [{ id: '10001', name: 'Card A' }] }
const friend: FriendInfo = { viewer_id: 42, support_card_id: 10002, support_name: 'Alice', type: 'Speed', limit_break_count: 4 }
const trainee: TraineeInfo = { id: 100101, name: 'Uma-chan' }
const vet1: ParentInfo = { instance_id: 1001, card_id: 200101 }
const vet2: ParentInfo = { instance_id: 1002, card_id: 200102 }

describe('selection store', () => {
  it('initialises to the leave-session reset shape', () => {
    const s = useSelection.getState()
    expect(s.deck).toBeNull()
    expect(s.friend).toBeNull()
    expect(s.trainee).toBeNull()
    expect(s.veterans).toEqual([])
    expect(s.rental).toBeNull()
    expect(s.event).toEqual({ enabled: false, level: 1, boost: false })
  })

  it('setDeck updates state and POSTs /api/selection', async () => {
    await useSelection.getState().setDeck(deck)
    expect(useSelection.getState().deck).toEqual(deck)
    expect(mockFetch).toHaveBeenCalledWith('/api/selection', expect.objectContaining({
      method: 'POST',
      body: expect.stringContaining('"deck"'),
    }))
    // Verify full payload shape
    const body = JSON.parse((mockFetch.mock.calls[0][1] as RequestInit).body as string)
    expect(body).toEqual({
      selection: {
        deck,
        friend: null,
        trainee: null,
        veterans: [],
        event: { enabled: false, level: 1, boost: false },
      },
    })
  })

  it('hydrate restores team from the server WITHOUT POSTing back', () => {
    useSelection.getState().hydrate({
      deck,
      friend,
      trainee,
      veterans: [vet1, vet2],
      event: { enabled: true, level: 3, boost: true },
    })
    const s = useSelection.getState()
    expect(s.deck).toEqual(deck)
    expect(s.friend).toEqual(friend)
    expect(s.trainee).toEqual(trainee)
    expect(s.veterans).toEqual([vet1, vet2])
    expect(s.event).toEqual({ enabled: true, level: 3, boost: true })
    // Critical: hydration must not echo back to the server (would loop).
    expect(mockFetch).not.toHaveBeenCalled()
  })

  it('hydrate fills missing fields with defaults', () => {
    useSelection.getState().hydrate({ deck })
    const s = useSelection.getState()
    expect(s.deck).toEqual(deck)
    expect(s.friend).toBeNull()
    expect(s.veterans).toEqual([])
    expect(s.event).toEqual({ enabled: false, level: 1, boost: false })
    expect(mockFetch).not.toHaveBeenCalled()
  })

  it('setFriend updates state and POSTs /api/selection', async () => {
    await useSelection.getState().setFriend(friend)
    expect(useSelection.getState().friend).toEqual(friend)
    const body = JSON.parse((mockFetch.mock.calls[0][1] as RequestInit).body as string)
    expect(body.selection.friend).toEqual(friend)
  })

  it('setTrainee updates state and POSTs /api/selection', async () => {
    await useSelection.getState().setTrainee(trainee)
    expect(useSelection.getState().trainee).toEqual(trainee)
    const body = JSON.parse((mockFetch.mock.calls[0][1] as RequestInit).body as string)
    expect(body.selection.trainee).toEqual(trainee)
  })

  it('setVeterans updates state and POSTs /api/selection', async () => {
    await useSelection.getState().setVeterans([vet1, vet2])
    expect(useSelection.getState().veterans).toEqual([vet1, vet2])
    const body = JSON.parse((mockFetch.mock.calls[0][1] as RequestInit).body as string)
    expect(body.selection.veterans).toEqual([vet1, vet2])
  })

  it('setRental updates state and POSTs /api/selection', async () => {
    // Legacy: selection.rental = viewerId (number) or null
    // rental is NOT part of the syncSelectionToServer payload (not included in the legacy POST)
    await useSelection.getState().setRental(99)
    expect(useSelection.getState().rental).toBe(99)
    // rental is still synced (setRentalChoice calls syncSelectionToServer in legacy)
    expect(mockFetch).toHaveBeenCalled()
  })

  it('setEvent updates state and POSTs /api/selection', async () => {
    await useSelection.getState().setEvent({ enabled: true, level: 2, boost: true })
    const s = useSelection.getState()
    expect(s.event).toEqual({ enabled: true, level: 2, boost: true })
    const body = JSON.parse((mockFetch.mock.calls[0][1] as RequestInit).body as string)
    expect(body.selection.event).toEqual({ enabled: true, level: 2, boost: true })
  })

  it('POST body omits rental (legacy syncSelectionToServer only sends deck/friend/trainee/veterans/event)', async () => {
    await useSelection.getState().setRental(42)
    const body = JSON.parse((mockFetch.mock.calls[0][1] as RequestInit).body as string)
    // rental is stored on client but not sent to /api/selection to match legacy syncSelectionToServer
    expect(body.selection).not.toHaveProperty('rental')
  })

  it('clear() resets to the leave-session shape without POSTing', () => {
    // Pre-load some state
    useSelection.setState({ deck, friend, trainee, veterans: [vet1], rental: 5 })
    mockFetch.mockClear()
    useSelection.getState().clear()
    const s = useSelection.getState()
    expect(s.deck).toBeNull()
    expect(s.friend).toBeNull()
    expect(s.trainee).toBeNull()
    expect(s.veterans).toEqual([])
    expect(s.rental).toBeNull()
    // clear() does NOT POST — client-side reset only (leave-session resets server state).
    expect(mockFetch).not.toHaveBeenCalled()
  })
})
