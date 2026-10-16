/**
 * ChoiceSelect — dropdown for selecting a choice or "Auto" for one event.
 *
 * Value contract:
 *   - "auto"      → no preference stored (bot uses default logic)
 *   - "0", "1", … → 0-based index stored in prefs; displayed as "Choice 1", "Choice 2", …
 */

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import type { ChoiceEffect } from '@/api/types'

interface ChoiceSelectProps {
  storyId: string
  nChoices: number
  /** Current 0-based pref index, or undefined when no pref (Auto). */
  value: number | undefined
  onChange: (storyId: string, value: number | undefined) => void
  disabled?: boolean
  choiceEffects?: ChoiceEffect[]
  /** 0-based POSITION the bot would auto-pick (matches the stored pref), or null. */
  recommendedChoice?: number | null
  /** Presentation-only width/layout override for the trigger. */
  triggerClassName?: string
}

export function ChoiceSelect({
  storyId,
  nChoices,
  value,
  onChange,
  disabled = false,
  choiceEffects,
  recommendedChoice,
  triggerClassName,
}: ChoiceSelectProps) {
  const selectValue = value !== undefined ? String(value) : 'auto'
  const selectedLabel = value !== undefined ? `Choice ${value + 1}` : 'Auto'

  function handleChange(raw: string) {
    if (raw === 'auto') {
      onChange(storyId, undefined)
    } else {
      onChange(storyId, Number(raw))
    }
  }

  return (
    <Select value={selectValue} onValueChange={handleChange} disabled={disabled}>
      <SelectTrigger
        size="sm"
        className={triggerClassName ?? 'w-28'}
        aria-label={`Choice for ${storyId}`}
      >
        <SelectValue>{selectedLabel}</SelectValue>
      </SelectTrigger>
      <SelectContent className="min-w-72 max-w-[calc(100vw-2rem)] sm:max-w-md">
        <SelectItem value="auto">Auto</SelectItem>
        {Array.from({ length: nChoices }, (_, i) => {
          // Choices are displayed, stored (pref), and picked by 0-based POSITION.
          // choice_effects is in the same (select_index-sorted) order, so index by
          // position; the "bot pick" star marks the position the bot auto-picks.
          const choice = choiceEffects?.[i]
          const effectText = choice?.effect || choice?.label
          const isRecommended = recommendedChoice === i

          return (
            <SelectItem key={i} value={String(i)} textValue={`Choice ${i + 1}`}>
              {effectText ? (
                <span className="flex min-w-0 items-start gap-2">
                  <span className="shrink-0 font-medium">{`Choice ${i + 1}`}</span>
                  <span className="min-w-0 whitespace-normal break-words text-muted-foreground">
                    {`— ${effectText}`}
                    {isRecommended && (
                      <span className="ml-1 whitespace-nowrap font-medium text-green-600 dark:text-green-400">
                        ★ bot pick
                      </span>
                    )}
                  </span>
                </span>
              ) : (
                <span className="flex min-w-0 items-center gap-2">
                  <span>{`Choice ${i + 1}`}</span>
                  {isRecommended && (
                    <span className="whitespace-nowrap text-xs font-medium text-green-600 dark:text-green-400">
                      ★ bot pick
                    </span>
                  )}
                </span>
              )}
            </SelectItem>
          )
        })}
      </SelectContent>
    </Select>
  )
}
