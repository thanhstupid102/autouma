/**
 * selection store — mirrors the legacy app.js selection object.
 *
 * Legacy shape (app.js:772):
 *   { deck, friend, trainee, veterans: [], rental, event: { enabled, level, boost } }
 *
 * POST payload (app.js:774-789, syncSelectionToServer):
 *   { selection: { deck, friend, trainee, veterans, event } }
 *   NOTE: `rental` is intentionally excluded from the POST body — the legacy
 *   syncSelectionToServer function does not include it. The rental value is used
 *   locally to build the RunCareerNewBody (rental_friend_viewer_id) when starting
 *   a career run, but is never synced to /api/selection.
 *
 * clear() does NOT POST to /api/selection — leaving the session resets server-side
 * state via its own endpoint; a client-side clear should not emit an extra POST.
 */

import { create } from 'zustand'
import { syncSelection } from '../api/career'
import type { DeckInfo, FriendInfo, TraineeInfo, ParentInfo, EventSelection, Selection } from '../api/types'

// -------------------------------------------------------------------------
// Store types
// -------------------------------------------------------------------------
export interface SelectionState {
  deck: DeckInfo | null
  friend: FriendInfo | null
  trainee: TraineeInfo | null
  veterans: ParentInfo[]
  /** rental viewer_id — kept locally, never POSTed to /api/selection */
  rental: number | string | null
  event: EventSelection
}

export interface SelectionActions {
  setDeck: (deck: DeckInfo | null) => Promise<void>
  setFriend: (friend: FriendInfo | null) => Promise<void>
  setTrainee: (trainee: TraineeInfo | null) => Promise<void>
  setVeterans: (veterans: ParentInfo[]) => Promise<void>
  setRental: (viewerId: number | string | null) => Promise<void>
  setEvent: (event: EventSelection) => Promise<void>
  /** Load a saved selection from the server WITHOUT re-POSTing it (restore on open). */
  hydrate: (selection: Selection) => void
  clear: () => void
}

export type SelectionStore = SelectionState & SelectionActions

// -------------------------------------------------------------------------
// Initial / leave-session reset shape.
// -------------------------------------------------------------------------
const INITIAL_STATE: SelectionState = {
  deck: null,
  friend: null,
  trainee: null,
  veterans: [],
  rental: null,
  event: { enabled: false, level: 1, boost: false },
}

// -------------------------------------------------------------------------
// Helper — build the POST payload matching legacy syncSelectionToServer
// -------------------------------------------------------------------------
function toPayload(s: SelectionState) {
  return {
    deck: s.deck,
    friend: s.friend,
    trainee: s.trainee,
    veterans: s.veterans,
    event: s.event,
    // rental intentionally omitted — see module comment
  }
}

// -------------------------------------------------------------------------
// Store
// -------------------------------------------------------------------------
export const useSelection = create<SelectionStore>()((set, get) => ({
  ...INITIAL_STATE,

  async setDeck(deck) {
    set({ deck })
    await syncSelection({ selection: toPayload(get()) }).catch(() => { /* fire-and-forget like legacy */ })
  },

  async setFriend(friend) {
    set({ friend })
    await syncSelection({ selection: toPayload(get()) }).catch(() => {})
  },

  async setTrainee(trainee) {
    set({ trainee })
    await syncSelection({ selection: toPayload(get()) }).catch(() => {})
  },

  async setVeterans(veterans) {
    set({ veterans })
    await syncSelection({ selection: toPayload(get()) }).catch(() => {})
  },

  async setRental(viewerId) {
    set({ rental: viewerId })
    // Legacy setRentalChoice calls syncSelectionToServer after setting rental
    await syncSelection({ selection: toPayload(get()) }).catch(() => {})
  },

  async setEvent(event) {
    set({ event })
    await syncSelection({ selection: toPayload(get()) }).catch(() => {})
  },

  hydrate(selection) {
    // Restore the remembered team from the server. No POST (would loop) and no rental
    // (the server never stores it — see module comment).
    set({
      deck: selection.deck ?? null,
      friend: selection.friend ?? null,
      trainee: selection.trainee ?? null,
      veterans: selection.veterans ?? [],
      event: selection.event ?? INITIAL_STATE.event,
    })
  },

  clear() {
    set({ ...INITIAL_STATE })
    // No POST — leave-session resets server state via its own auth endpoint.
  },
}))
