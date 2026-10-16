import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { FriendInfo } from '@/api/types'
import { FriendParentGrid } from './FriendParentGrid'

const f = (name: string, stars: number, category: string) => ({ name, stars, category })

const strongRentalFriend: FriendInfo = {
  viewer_id: 'strong',
  name: 'Strong Friend',
  support_card_id: 30107,
  rental_parent: {
    trained_chara_id: 987654321,
    card_id: 100601,
    name: 'Strong Rental',
    rank: 15,
    tree: { self: { factors: [f('Speed', 3, 'stat'), f('Stamina', 3, 'stat')] } },
  },
} as unknown as FriendInfo

const weakRentalFriend: FriendInfo = {
  viewer_id: 'weak',
  name: 'Weak Friend',
  support_card_id: 30108,
  rental_parent: {
    trained_chara_id: 987654322,
    card_id: 100602,
    name: 'Weak Rental',
    rank: 11,
    tree: { self: { factors: [f('Speed', 2, 'stat')] } },
  },
} as unknown as FriendInfo

function renderFriendParents(friends: FriendInfo[]) {
  return render(
    <FriendParentGrid
      friends={friends}
      loading={false}
      source="initial"
      selectedRental={null}
      onRentalSelect={vi.fn()}
      onRefresh={vi.fn()}
      careerActive={false}
      quota={null}
    />,
  )
}

describe('FriendParentGrid spark filter', () => {
  it('renders friend parents and narrows them by spark total', () => {
    renderFriendParents([strongRentalFriend, weakRentalFriend])

    expect(screen.getByTestId('rental-card-strong')).toBeInTheDocument()
    expect(screen.getByTestId('rental-card-weak')).toBeInTheDocument()

    fireEvent.change(screen.getByTestId('spark-minBlue'), { target: { value: '5' } })

    expect(screen.getByTestId('rental-card-strong')).toBeInTheDocument()
    expect(screen.queryByTestId('rental-card-weak')).not.toBeInTheDocument()
    expect(screen.getByText('Showing 1 of 2 rental parents.')).toBeInTheDocument()
  })
})
