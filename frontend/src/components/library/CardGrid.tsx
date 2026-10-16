/**
 * CardGrid — renders owned support cards (session.supports). Display only.
 *
 * Kicker: "${rarity} | ${type}"  (note: legacy renders rarity first for owned cards)
 *
 * Legacy ref: app.js:2548-2558 renderSupports
 */

import { useState } from 'react'
import { GridCard } from './GridCard'
import { GridSearch } from './GridSearch'
import type { SupportCard } from '@/api/types'

interface CardGridProps {
  cards: SupportCard[]
}

export function CardGrid({ cards }: CardGridProps) {
  const [search, setSearch] = useState('')

  const filtered = search.trim()
    ? cards.filter(c =>
        (c.name ?? '').toLowerCase().includes(search.toLowerCase()),
      )
    : cards

  return (
    <div className="flex flex-col gap-2">
      {cards.length > 8 && (
        <div className="flex justify-end">
          <GridSearch value={search} onChange={setSearch} placeholder="Search cards…" />
        </div>
      )}

      {filtered.length === 0 && (
        <p className="text-sm text-muted-foreground">No cards found.</p>
      )}

      <div className="grid grid-cols-3 gap-2 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-6">
        {filtered.map((card, i) => (
          <GridCard
            key={String(card.id ?? i)}
            imgId={card.id ?? '10001'}
            name={card.name ?? 'Unknown'}
            kicker={`${card.rarity ?? '?'} | ${card.type ?? '?'}`}
            testId={`card-${card.id ?? i}`}
          />
        ))}
      </div>
    </div>
  )
}
