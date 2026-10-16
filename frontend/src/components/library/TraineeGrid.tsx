/**
 * TraineeGrid — renders session.umas thumbnails; toggle-selectable.
 *
 * Legacy ref: app.js:2539-2547 renderTrainees, app.js:2409-2421 selectTrainee
 */

import { useState } from 'react'
import { GridCard } from './GridCard'
import { GridSearch } from './GridSearch'
import type { TraineeInfo } from '@/api/types'

interface TraineeGridProps {
  trainees: TraineeInfo[]
  selected: TraineeInfo | null
  onSelect: (t: TraineeInfo | null) => void
}

export function TraineeGrid({ trainees, selected, onSelect }: TraineeGridProps) {
  const [search, setSearch] = useState('')

  const filtered = search.trim()
    ? trainees.filter(t =>
        (t.name ?? '').toLowerCase().includes(search.toLowerCase()),
      )
    : trainees

  function handleClick(t: TraineeInfo) {
    const isSelected = selected && String(selected.id) === String(t.id)
    onSelect(isSelected ? null : t)
  }

  return (
    <div className="flex flex-col gap-2">
      {trainees.length > 8 && (
        <div className="flex justify-end">
          <GridSearch value={search} onChange={setSearch} placeholder="Search trainees…" />
        </div>
      )}

      {filtered.length === 0 && (
        <p className="text-sm text-muted-foreground">No trainees found.</p>
      )}

      <div className="grid grid-cols-3 gap-2 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-6">
        {filtered.map(t => {
          const isSelected = selected && String(selected.id) === String(t.id)
          return (
            <GridCard
              key={String(t.id)}
              imgId={t.id ?? '100101'}
              name={t.name ?? 'Unknown'}
              selected={!!isSelected}
              onClick={() => handleClick(t)}
              testId={`trainee-card-${t.id}`}
            />
          )
        })}
      </div>
    </div>
  )
}
