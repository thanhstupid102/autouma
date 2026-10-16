import { Badge } from '@/components/ui/badge'
import type { EventCatalogEntry, EventSource } from '@/api/types'

import { ChoiceSelect } from './ChoiceSelect'

const SOURCE_STYLES: Record<EventSource, string> = {
  support: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300',
  scenario: 'bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300',
  chara: 'bg-pink-100 text-pink-700 dark:bg-pink-900/40 dark:text-pink-300',
  other: 'bg-muted text-muted-foreground',
}

interface EventCardProps {
  entry: EventCatalogEntry
  prefValue: number | undefined
  onChoiceChange: (storyId: string, value: number | undefined) => void
}

export function EventCard({ entry, prefValue, onChoiceChange }: EventCardProps) {
  const sourceStyle = SOURCE_STYLES[entry.source] ?? SOURCE_STYLES.other
  const singleChoice = entry.n_choices <= 1

  return (
    <article
      className="min-w-0 overflow-hidden rounded-xl border border-border bg-card p-4"
      data-testid={`event-card-${entry.story_id}`}
    >
      <div className="flex min-w-0 items-start justify-between gap-3">
        <span
          className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium capitalize ${sourceStyle}`}
        >
          {entry.source}
        </span>
        <span className="shrink-0 text-xs text-muted-foreground">
          <span className="sr-only">Seen </span>
          {entry.seen_count}×
        </span>
      </div>

      <div className="mt-3 min-w-0">
        <h2 className="text-sm font-medium [overflow-wrap:anywhere]">
          {entry.name || entry.label}
        </h2>
        <div className="mt-1 min-w-0 space-y-1 text-xs text-muted-foreground">
          {entry.name && entry.label && entry.label !== entry.name && (
            <p className="[overflow-wrap:anywhere]">{entry.label}</p>
          )}
          <p
            className="min-w-0 font-mono [overflow-wrap:anywhere]"
            data-testid={`event-card-story-id-${entry.story_id}`}
          >
            {entry.story_id}
          </p>
        </div>
      </div>

      <div className="mt-4 flex min-h-11 min-w-0 items-center justify-between gap-3 border-t border-border pt-3">
        <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Choice
        </span>
        <div className="min-w-0 flex-1">
          {singleChoice ? (
            <div className="flex justify-end">
              <Badge variant="outline" className="text-xs text-muted-foreground">
                Single
              </Badge>
            </div>
          ) : (
            <ChoiceSelect
              storyId={entry.story_id}
              nChoices={entry.n_choices}
              value={prefValue}
              onChange={onChoiceChange}
              choiceEffects={entry.choice_effects}
              recommendedChoice={entry.recommended_choice}
              triggerClassName="w-full"
            />
          )}
        </div>
      </div>

      {entry.choice_effects && entry.choice_effects.length > 0 && (
        <details className="group mt-1" data-testid={`event-card-effects-${entry.story_id}`}>
          <summary className="flex min-h-11 cursor-pointer items-center text-xs font-semibold uppercase tracking-wide text-muted-foreground marker:text-primary">
            Choice effects ({entry.choice_effects.length})
          </summary>
          <div className="space-y-2 border-t border-border pt-3">
            {entry.choice_effects.map((choice, choiceIndex) => {
              const isRecommended = entry.recommended_choice === choiceIndex
              return (
                <div key={choiceIndex} className="flex min-w-0 items-start gap-2 text-xs">
                  <span
                    className={`inline-flex h-5 min-w-5 shrink-0 items-center justify-center rounded px-1 font-mono text-[10px] font-medium ${
                      isRecommended
                        ? 'bg-green-600 text-white'
                        : 'bg-muted text-muted-foreground'
                    }`}
                  >
                    {choiceIndex + 1}
                  </span>
                  <span
                    className={`min-w-0 [overflow-wrap:anywhere] ${
                      isRecommended ? 'text-foreground' : 'text-muted-foreground'
                    }`}
                  >
                    {choice.effect || choice.label || '—'}
                    {isRecommended && (
                      <span className="ml-1 font-medium text-green-600 dark:text-green-400">
                        ★ bot pick
                      </span>
                    )}
                  </span>
                </div>
              )
            })}
          </div>
        </details>
      )}
    </article>
  )
}
