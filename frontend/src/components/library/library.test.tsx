/**
 * Tests for Task 10 — Library pure helpers + ParentGrid render/selection.
 *
 * Coverage:
 *   1. isValidDeck — valid, invalid (id with '{', id with '-', name 'Unknown')
 *   2. normalizedCardName — lowercase, strip parens, strip non-alphanum
 *   3. friendKey — correct string shape
 *   4. friendAllowed — all three exclusion cases + allowed case
 *   5. getRentalFriends — only friends with rental_parent.trained_chara_id
 *   6. rentalQuotaExhausted — null quota, remaining > 0, remaining <= 0
 *   7. toggleParent — add, remove, ignore-when-full (max 2)
 *   8. ParentGrid — renders one card per parent with rank badge; click selects/deselects
 */

import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import {
  isValidDeck,
  normalizedCardName,
  friendKey,
  friendAllowed,
  getRentalFriends,
  rentalQuotaExhausted,
  toggleParent,
  RANK_MAP,
} from './libraryRules'
import { ParentGrid } from './ParentGrid'
import { DeckList } from './DeckList'
import { GridSearch } from './GridSearch'
import type { DeckInfo, FriendInfo, TraineeInfo, ParentInfo, RentalQuota } from '@/api/types'

// ---------------------------------------------------------------------------
// Mocks for components that import hooks/stores
// ---------------------------------------------------------------------------

vi.mock('@/hooks/useSession', () => ({
  useSession: vi.fn(() => ({ data: undefined })),
}))

vi.mock('@/stores/selection', () => ({
  useSelection: vi.fn(() => ({
    deck: null, friend: null, trainee: null, veterans: [], rental: null,
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
// Fixtures
// ---------------------------------------------------------------------------

const validDeck: DeckInfo = {
  id: 1,
  name: 'Test Deck',
  cards: [
    { id: '10001', name: 'Speed Up' },
    { id: '10002', name: 'Stamina Boost' },
  ],
}

const invalidDeckBraceId: DeckInfo = {
  id: 2,
  name: 'Bad Deck',
  cards: [{ id: '{10001}', name: 'Speed Up' }],
}

const invalidDeckDashId: DeckInfo = {
  id: 3,
  name: 'Bad Deck 2',
  cards: [{ id: '10001-a', name: 'Speed Up' }],
}

const invalidDeckUnknownName: DeckInfo = {
  id: 4,
  name: 'Bad Deck 3',
  cards: [{ id: '10001', name: 'Unknown Card' }],
}

const friend1: FriendInfo = {
  viewer_id: 111,
  support_card_id: '10001',
  support_name: 'Speed Up',
}

const trainee1: TraineeInfo = { id: 900, name: 'Uma Chan' }

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

const parent3: ParentInfo = {
  instance_id: 'inst-3',
  card_id: '200003',
  rank: 11,
  name: 'Parent Gamma',
} as unknown as ParentInfo

// ---------------------------------------------------------------------------
// 1. isValidDeck
// ---------------------------------------------------------------------------

describe('isValidDeck', () => {
  it('returns true for a valid deck', () => {
    expect(isValidDeck(validDeck)).toBe(true)
  })

  it('returns false when a card id contains "{"', () => {
    expect(isValidDeck(invalidDeckBraceId)).toBe(false)
  })

  it('returns false when a card id contains "-"', () => {
    expect(isValidDeck(invalidDeckDashId)).toBe(false)
  })

  it('returns false when a card name includes "Unknown"', () => {
    expect(isValidDeck(invalidDeckUnknownName)).toBe(false)
  })

  it('returns true for an empty deck (no cards)', () => {
    const emptyDeck: DeckInfo = { id: 5, name: 'Empty', cards: [] }
    expect(isValidDeck(emptyDeck)).toBe(true)
  })
})

// ---------------------------------------------------------------------------
// 2. normalizedCardName
// ---------------------------------------------------------------------------

describe('normalizedCardName', () => {
  it('lowercases the input', () => {
    expect(normalizedCardName('SPEED')).toBe('speed')
  })

  it('strips parenthetical groups', () => {
    expect(normalizedCardName('Speed Up (Special)')).toBe('speedup')
  })

  it('strips non-alphanumeric characters', () => {
    expect(normalizedCardName('Speed-Up!')).toBe('speedup')
  })

  it('handles null/undefined gracefully', () => {
    expect(normalizedCardName(null)).toBe('')
    expect(normalizedCardName(undefined)).toBe('')
  })

  it('handles numeric values', () => {
    expect(normalizedCardName(12345)).toBe('12345')
  })
})

// ---------------------------------------------------------------------------
// 3. friendKey
// ---------------------------------------------------------------------------

describe('friendKey', () => {
  it('returns "viewer_id:support_card_id" string', () => {
    expect(friendKey({ viewer_id: 111, support_card_id: 10001 })).toBe('111:10001')
  })

  it('works with string ids', () => {
    expect(friendKey({ viewer_id: 'abc', support_card_id: 'def' })).toBe('abc:def')
  })
})

// ---------------------------------------------------------------------------
// 4. friendAllowed
// ---------------------------------------------------------------------------

describe('friendAllowed', () => {
  it('returns false for null friend', () => {
    expect(friendAllowed(null, null, null)).toBe(false)
  })

  it('returns true when no deck and no trainee', () => {
    expect(friendAllowed(friend1, null, null)).toBe(true)
  })

  // Case A: support_card_id matches a deck card id
  it('returns false when support_card_id is in deck card ids', () => {
    const f: FriendInfo = { viewer_id: 1, support_card_id: '10001', support_name: 'Other Name' }
    expect(friendAllowed(f, validDeck, null)).toBe(false)
  })

  // Case B: normalized support_name matches a deck card name
  it('returns false when normalized support_name matches a deck card name', () => {
    const f: FriendInfo = {
      viewer_id: 2,
      support_card_id: '99999', // not in deck
      support_name: 'Speed Up (Alt)',  // normalizes to 'speedup' — matches 'Speed Up'
    }
    expect(friendAllowed(f, validDeck, null)).toBe(false)
  })

  // Case C: normalized support_name matches the trainee name
  it('returns false when support_name matches trainee name', () => {
    const f: FriendInfo = {
      viewer_id: 3,
      support_card_id: '99998',
      support_name: 'Uma Chan',  // normalizes to 'umachan'
    }
    const trainee: TraineeInfo = { id: 999, name: 'Uma Chan' }
    expect(friendAllowed(f, null, trainee)).toBe(false)
  })

  it('returns true when friend name does not conflict with deck or trainee', () => {
    const f: FriendInfo = {
      viewer_id: 4,
      support_card_id: '99997',
      support_name: 'Power Boost',
    }
    expect(friendAllowed(f, validDeck, trainee1)).toBe(true)
  })

  it('returns true when friend name is empty (no match possible)', () => {
    const f: FriendInfo = { viewer_id: 5, support_card_id: '99996', support_name: '' }
    expect(friendAllowed(f, validDeck, trainee1)).toBe(true)
  })
})

// ---------------------------------------------------------------------------
// 5. getRentalFriends
// ---------------------------------------------------------------------------

describe('getRentalFriends', () => {
  it('returns only friends with rental_parent.trained_chara_id', () => {
    const friends: FriendInfo[] = [
      { viewer_id: 1, support_card_id: 1 }, // no rental
      {
        viewer_id: 2,
        support_card_id: 2,
        rental_parent: { trained_chara_id: 9001, card_id: 200001 },
      } as unknown as FriendInfo,
      { viewer_id: 3, support_card_id: 3, rental_parent: {} } as unknown as FriendInfo, // no trained_chara_id
    ]
    const result = getRentalFriends(friends)
    expect(result).toHaveLength(1)
    expect(result[0].viewer_id).toBe(2)
  })

  it('returns empty array when no rental friends', () => {
    expect(getRentalFriends([{ viewer_id: 1, support_card_id: 1 }])).toHaveLength(0)
  })
})

// ---------------------------------------------------------------------------
// 6. rentalQuotaExhausted
// ---------------------------------------------------------------------------

describe('rentalQuotaExhausted', () => {
  it('returns false for null quota', () => {
    expect(rentalQuotaExhausted(null)).toBe(false)
  })

  it('returns false when remaining > 0', () => {
    const q: RentalQuota = { used: 1, max: 3, remaining: 2 }
    expect(rentalQuotaExhausted(q)).toBe(false)
  })

  it('returns true when remaining is 0', () => {
    const q: RentalQuota = { used: 3, max: 3, remaining: 0 }
    expect(rentalQuotaExhausted(q)).toBe(true)
  })

  it('returns true when remaining is negative', () => {
    const q: RentalQuota = { used: 4, max: 3, remaining: -1 }
    expect(rentalQuotaExhausted(q)).toBe(true)
  })
})

// ---------------------------------------------------------------------------
// 7. toggleParent
// ---------------------------------------------------------------------------

describe('toggleParent', () => {
  it('adds a parent when list is empty', () => {
    const result = toggleParent([], parent1)
    expect(result).toHaveLength(1)
    expect(result[0].instance_id).toBe('inst-1')
  })

  it('adds a second parent when one is already selected', () => {
    const result = toggleParent([parent1], parent2)
    expect(result).toHaveLength(2)
  })

  it('removes a parent when it is already selected', () => {
    const result = toggleParent([parent1, parent2], parent1)
    expect(result).toHaveLength(1)
    expect(result[0].instance_id).toBe('inst-2')
  })

  it('ignores (no-op) when list is full (2) and parent is not selected', () => {
    const result = toggleParent([parent1, parent2], parent3)
    expect(result).toHaveLength(2)
    expect(result).not.toContainEqual(expect.objectContaining({ instance_id: 'inst-3' }))
  })

  it('does not mutate the input array', () => {
    const original = [parent1]
    toggleParent(original, parent2)
    expect(original).toHaveLength(1)
  })
})

// ---------------------------------------------------------------------------
// 8. ParentGrid — render + selection
// ---------------------------------------------------------------------------

describe('ParentGrid', () => {
  const mockParents = [parent1, parent2, parent3]

  it('renders one card per parent', () => {
    const onVets = vi.fn()
    wrap(<ParentGrid parents={mockParents} veterans={[]} onVeteransChange={onVets} />)

    expect(screen.getByTestId('parent-card-inst-1')).toBeInTheDocument()
    expect(screen.getByTestId('parent-card-inst-2')).toBeInTheDocument()
    expect(screen.getByTestId('parent-card-inst-3')).toBeInTheDocument()
  })

  it('shows rank badge text for a parent with known rank', () => {
    const onVets = vi.fn()
    wrap(<ParentGrid parents={[parent1]} veterans={[]} onVeteransChange={onVets} />)
    // parent1 rank = 15 → 'S'
    expect(screen.getByText(RANK_MAP[15])).toBeInTheDocument() // 'S'
  })

  it('clicking a parent calls onVeteransChange with the parent added', () => {
    const onVets = vi.fn()
    wrap(<ParentGrid parents={mockParents} veterans={[]} onVeteransChange={onVets} />)

    fireEvent.click(screen.getByTestId('parent-card-inst-1'))
    expect(onVets).toHaveBeenCalledWith([parent1])
  })

  it('clicking a selected parent removes it (deselect)', () => {
    const onVets = vi.fn()
    wrap(<ParentGrid parents={mockParents} veterans={[parent1]} onVeteransChange={onVets} />)

    fireEvent.click(screen.getByTestId('parent-card-inst-1'))
    expect(onVets).toHaveBeenCalledWith([])
  })

  it('does not call onVeteransChange for a non-selected card when full (2 selected)', () => {
    const onVets = vi.fn()
    wrap(<ParentGrid parents={mockParents} veterans={[parent1, parent2]} onVeteransChange={onVets} />)

    // parent3 is not selected and list is full — card is disabled, click should be ignored entirely
    fireEvent.click(screen.getByTestId('parent-card-inst-3'))
    expect(onVets).not.toHaveBeenCalled()
  })

  it('shows "2 parents selected" hint when full', () => {
    const onVets = vi.fn()
    wrap(<ParentGrid parents={mockParents} veterans={[parent1, parent2]} onVeteransChange={onVets} />)
    expect(screen.getByText(/2 parents selected/)).toBeInTheDocument()
  })
})

describe('library mobile layout contracts', () => {
  it('renders deck contents in three phone columns and restores five at md', () => {
    const deck: DeckInfo = {
      id: 7,
      name: 'Mobile Deck',
      cards: Array.from({ length: 5 }, (_, index) => ({
        id: `1000${index + 1}`,
        name: `Card ${index + 1}`,
      })),
    }

    render(<DeckList decks={[deck]} selectedDeck={null} onSelect={vi.fn()} />)

    const grid = screen.getByTestId('deck-card-grid-7')
    expect(grid).toHaveClass('grid-cols-3', 'md:grid-cols-5', 'min-w-0', 'max-w-full')
    expect(grid).not.toHaveClass('w-screen', 'min-w-max')
    for (const image of screen.getAllByRole('img')) {
      expect(image).toHaveClass('max-w-full', 'object-cover')
    }
  })

  it('keeps GridSearch full-width and 16px on phones, then restores its compact md size', () => {
    render(<GridSearch value="" onChange={vi.fn()} placeholder="Search library" />)

    expect(screen.getByRole('searchbox', { name: 'Search library' })).toHaveClass(
      'w-full',
      'text-base',
      'md:h-7',
      'md:w-40',
      'md:text-xs',
    )
  })

  it('keeps the parent grid constrained to its section without changing its phone columns', () => {
    wrap(<ParentGrid parents={[parent1]} veterans={[]} onVeteransChange={vi.fn()} />)

    const grid = screen.getByTestId('parent-card-inst-1').closest('.grid')
    expect(grid).toHaveClass('grid-cols-3', 'min-w-0', 'max-w-full')
    expect(grid).not.toHaveClass('w-screen', 'min-w-max')
  })
})
