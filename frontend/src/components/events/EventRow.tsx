/**
 * EventRow — single row in the events table (div-grid layout).
 *
 * Renders as a grid row div so the parent can be a scrollable div-container.
 */

import { Badge } from '@/components/ui/badge'
import { ChoiceSelect } from './ChoiceSelect'
import type { EventCatalogEntry, EventSource } from '@/api/types'

// ---------------------------------------------------------------------------
// Source badge colours
// ---------------------------------------------------------------------------

const SOURCE_STYLES: Record<EventSource, string> = {
  support:  'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300',
  scenario: 'bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300',
  chara:    'bg-pink-100 text-pink-700 dark:bg-pink-900/40 dark:text-pink-300',
  other:    'bg-muted text-muted-foreground',
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface EventRowProps {
  entry: EventCatalogEntry
  prefValue: number | undefined
  onChoiceChange: (storyId: string, value: number | undefined) => void
  /** Optional style override (used by virtualizer for positioning). */
  style?: React.CSSProperties
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function EventRow({ entry, prefValue, onChoiceChange, style }: EventRowProps) {
  const sourceStyle = SOURCE_STYLES[entry.source] ?? SOURCE_STYLES.other
  const singleChoice = entry.n_choices <= 1

  return (
    <div
      style={style}
      className="border-b border-border last:border-0"
      data-testid={`event-row-${entry.story_id}`}
    >
      {/* Main row */}
      <div className="grid grid-cols-[96px_1fr_48px_128px] items-center hover:bg-muted/30 transition-colors">
        {/* Source badge */}
        <div className="px-3 py-2.5">
          <span
            className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium capitalize ${sourceStyle}`}
          >
            {entry.source}
          </span>
        </div>

        {/* Event name + story_id + per-choice effects */}
        <div className="px-3 py-2.5 min-w-0">
          <span className="text-sm font-medium line-clamp-2">
            {entry.name || entry.label}
          </span>
          <span className="block text-xs text-muted-foreground mt-0.5">
            {entry.name && entry.label && entry.label !== entry.name && (
              <span>{entry.label} · </span>
            )}
            <span className="font-mono [overflow-wrap:anywhere]">{entry.story_id}</span>
          </span>

          {entry.choice_effects && entry.choice_effects.length > 0 && (
            <div className="mt-1.5 space-y-0.5">
              {entry.choice_effects.map((choice, ci) => {
                // Display/star by 0-based POSITION (matches the bot's pick + the
                // stored pref); select_index is unreliable as a choice ordinal.
                const isRec = entry.recommended_choice === ci
                return (
                  <div
                    key={ci}
                    className="flex items-start gap-1.5 text-xs"
                  >
                    <span
                      className={`mt-px inline-flex h-4 min-w-4 items-center justify-center rounded px-1 font-mono text-[10px] font-medium ${
                        isRec
                          ? 'bg-green-600 text-white'
                          : 'bg-muted text-muted-foreground'
                      }`}
                    >
                      {ci + 1}
                    </span>
                    <span className={isRec ? 'text-foreground' : 'text-muted-foreground'}>
                      {choice.effect || choice.label || '—'}
                      {isRec && (
                        <span className="ml-1 font-medium text-green-600 dark:text-green-400">
                          ★ bot pick
                        </span>
                      )}
                    </span>
                  </div>
                )
              })}
            </div>
          )}
        </div>

        {/* Seen count */}
        <div className="px-3 py-2.5 text-right">
          <span className="text-xs text-muted-foreground">{entry.seen_count}×</span>
        </div>

        {/* Choice selector */}
        <div className="px-3 py-2.5 text-right">
          {singleChoice ? (
            <Badge variant="outline" className="text-xs text-muted-foreground">
              Single
            </Badge>
          ) : (
            <ChoiceSelect
              storyId={entry.story_id}
              nChoices={entry.n_choices}
              value={prefValue}
              onChange={onChoiceChange}
              choiceEffects={entry.choice_effects}
              recommendedChoice={entry.recommended_choice}
            />
          )}
        </div>
      </div>
    </div>
  )
}
