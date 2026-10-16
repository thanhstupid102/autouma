/**
 * libraryRules.ts — pure helpers for the Library page.
 *
 * Ported faithfully from:
 *   app.js:2448-2454  isValidDeck
 *   app.js:1067-1085  friendKey / normalizedCardName / friendAllowed
 *   app.js:1647-1668  getRentalFriends / rentalQuotaExhausted
 *   app.js:2422-2434  selectParent (toggleParent reducer)
 *   app.js:765-770    rankMap
 */

import type { DeckInfo, FriendInfo, TraineeInfo, ParentInfo, RentalParent, RentalQuota } from '@/api/types'

// ---------------------------------------------------------------------------
// rankMap — legacy app.js:765-770
// ---------------------------------------------------------------------------
// Ids 19-98 are the U-ranks: each letter has 10 steps (UG, UG1..UG9, then
// UF, UF1..UF9, ...). 18 base ranks + 8 letters x 10 steps = 98, exactly the
// id count of master.mdb single_mode_rank. The old map treated 20/21/22 as
// UF/UE/UD, mislabelling what are really UG1/UG2/UG3.
export const RANK_MAP: Record<number, string> = {
  1: 'G', 2: 'G+', 3: 'F', 4: 'F+', 5: 'E', 6: 'E+',
  7: 'D', 8: 'D+', 9: 'C', 10: 'C+', 11: 'B', 12: 'B+',
  13: 'A', 14: 'A+', 15: 'S', 16: 'S+', 17: 'SS', 18: 'SS+',
}
'GFEDCBAS'.split('').forEach((letter, i) => {
  const base = 19 + i * 10
  RANK_MAP[base] = `U${letter}`
  for (let step = 1; step <= 9; step++) RANK_MAP[base + step] = `U${letter}${step}`
})

// ---------------------------------------------------------------------------
// isValidDeck — app.js:2448-2454
// ---------------------------------------------------------------------------
export function isValidDeck(deck: DeckInfo): boolean {
  return deck.cards.every(card => {
    const id = String(card.id ?? '')
    const name = String(card.name ?? '')
    return !id.includes('{') && !id.includes('-') && !name.includes('Unknown')
  })
}

// ---------------------------------------------------------------------------
// normalizedCardName — app.js:1070-1072
// lowercase, strip parenthetical groups, strip non-alphanumeric
// ---------------------------------------------------------------------------
export function normalizedCardName(value: string | number | null | undefined): string {
  return String(value ?? '')
    .toLowerCase()
    .replace(/\([^)]*\)/g, '')
    .replace(/[^a-z0-9]+/g, '')
}

// ---------------------------------------------------------------------------
// friendKey — app.js:1067-1069
// ---------------------------------------------------------------------------
export function friendKey(friend: Pick<FriendInfo, 'viewer_id' | 'support_card_id'>): string {
  return `${friend.viewer_id}:${friend.support_card_id}`
}

// ---------------------------------------------------------------------------
// friendAllowed — app.js:1073-1085
// Exclude friend if:
//   1. Its support_card_id is in the selected deck's card ids
//   2. Its normalized support_name matches a deck card name
//   3. Its normalized support_name matches the trainee name
// ---------------------------------------------------------------------------
export function friendAllowed(
  friend: FriendInfo | null | undefined,
  deck: DeckInfo | null | undefined,
  trainee: TraineeInfo | null | undefined,
): boolean {
  if (!friend) return false
  const friendId = String(friend.support_card_id ?? '')
  const friendName = normalizedCardName(friend.support_name)

  if (deck) {
    const deckIds = new Set(deck.cards.map(card => String(card.id ?? '')))
    if (deckIds.has(friendId)) return false
    const deckNames = new Set(deck.cards.map(card => normalizedCardName(card.name)))
    if (friendName && deckNames.has(friendName)) return false
  }

  if (trainee && friendName && normalizedCardName(trainee.name) === friendName) return false

  return true
}

// ---------------------------------------------------------------------------
// getRentalFriends — app.js:1647-1650
// Friends that carry a rental_parent with trained_chara_id
// ---------------------------------------------------------------------------
export interface RentalFriend extends FriendInfo {
  rental_parent: RentalParent
}

export function getRentalFriends(friends: FriendInfo[]): RentalFriend[] {
  return friends.filter(
    (f): f is RentalFriend =>
      !!(f as RentalFriend).rental_parent?.trained_chara_id,
  )
}

// ---------------------------------------------------------------------------
// rentalQuotaExhausted — app.js:1658-1661
// ---------------------------------------------------------------------------
export function rentalQuotaExhausted(quota: RentalQuota | null | undefined): boolean {
  return !!quota && quota.remaining <= 0
}

// ---------------------------------------------------------------------------
// toggleParent — reducer porting app.js:2422-2433
// max 2 veterans; clicking a selected one removes it; clicking when full → no-op
// ---------------------------------------------------------------------------
export function toggleParent(veterans: ParentInfo[], parent: ParentInfo): ParentInfo[] {
  const idx = veterans.findIndex(
    v => String(v.instance_id) === String(parent.instance_id),
  )
  if (idx !== -1) {
    // already selected — remove
    return veterans.filter((_, i) => i !== idx)
  }
  if (veterans.length >= 2) {
    // full — no-op (legacy: ignored when vet-full)
    return veterans
  }
  return [...veterans, parent]
}
