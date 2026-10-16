/**
 * DeckList — renders valid decks, each showing a header (name + slot id)
 * and a row of card thumbnails.
 *
 * Selection: toggle (click selected → deselect, click other → select).
 * Selected deck gets ring-2 ring-primary on the deck container.
 *
 * Legacy ref: app.js:2460-2479 renderDecks, app.js:2397-2408 selectDeck
 */

import { useState } from 'react'
import { cn } from '@/lib/utils'
import { GridCard } from './GridCard'
import { GridSearch } from './GridSearch'
import type { DeckInfo } from '@/api/types'

interface DeckListProps {
  decks: DeckInfo[]
  selectedDeck: DeckInfo | null
  onSelect: (deck: DeckInfo | null) => void
}

export function DeckList({ decks, selectedDeck, onSelect }: DeckListProps) {
  const [search, setSearch] = useState('')

  const filtered = search.trim()
    ? decks.filter(d => d.name.toLowerCase().includes(search.toLowerCase()))
    : decks

  function handleClick(deck: DeckInfo) {
    // Toggle: deselect if already selected
    const isSelected = selectedDeck && String(selectedDeck.id) === String(deck.id)
    onSelect(isSelected ? null : deck)
  }

  return (
    <div className="flex flex-col gap-2">
      {decks.length > 4 && (
        <div className="flex justify-end">
          <GridSearch value={search} onChange={setSearch} placeholder="Search decks…" />
        </div>
      )}

      {filtered.length === 0 && (
        <p className="text-sm text-muted-foreground">No decks found.</p>
      )}

      {/* Two columns on wide screens, one column otherwise */}
      <div className="grid grid-cols-1 gap-2 xl:grid-cols-2">
        {filtered.map(deck => {
          const isSelected = selectedDeck && String(selectedDeck.id) === String(deck.id)
          return (
            <div
              key={deck.id}
              role="button"
              tabIndex={0}
              aria-pressed={!!isSelected}
              data-testid={`deck-container-${deck.id}`}
              onClick={() => handleClick(deck)}
              onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') handleClick(deck) }}
              className={cn(
                'rounded-xl border border-border bg-card p-3 cursor-pointer',
                'hover:border-primary/50 transition-all select-none',
                isSelected && 'ring-2 ring-primary border-primary',
              )}
            >
              {/* Deck header */}
              <div className="mb-2 flex items-center justify-between">
                <span className="text-sm font-semibold uppercase tracking-wide text-foreground">
                  {deck.name.toUpperCase()}
                </span>
                <span className="text-xs text-muted-foreground opacity-80">
                  SLOT {deck.id}
                </span>
              </div>

              {/* Card thumbnails */}
              <div
                data-testid={`deck-card-grid-${deck.id}`}
                className="grid min-w-0 max-w-full grid-cols-3 gap-1 md:grid-cols-5"
              >
                {deck.cards.map((card, i) => (
                  <GridCard
                    key={String(card.id ?? i)}
                    imgId={card.id ?? '10001'}
                    name={card.name}
                    kicker={`${card.type ?? '?'} | ${card.rarity ?? '?'}`}
                  />
                ))}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
