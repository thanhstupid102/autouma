import { Plus, RotateCcw, X } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  EMPTY_SPARK_FILTER,
  MAX_TYPE_STARS,
  type SparkColour,
  type SparkColourOptions,
  type SparkConditionMode,
  type SparkFilter,
} from './sparkFilter'

interface SparkFilterBarProps {
  value: SparkFilter
  onChange: (next: SparkFilter) => void
  options: SparkColourOptions
  /** Highest star a single factor type can reach (21 for the library, 3 for self-only). */
  maxStars?: number
  /** Max number of factor rows allowed per colour (undefined = unlimited). */
  conditionLimits?: Partial<Record<SparkColour, number>>
  /** Max value of the Total-star stepper per colour (default MAX_TYPE_STARS). */
  totalMaxByColour?: Partial<Record<SparkColour, number>>
  /** Factor groups to hide while leaving their Total-star steppers visible. */
  hideFactorColours?: SparkColour[]
  /** Nodes the counts cover, shown in the Total header (default "full lineage"). */
  scopeLabel?: string
  disabled?: boolean
}

type TotalKey = 'minBlue' | 'minPink' | 'minWhite' | 'minGreen'

interface ColourMeta {
  colour: SparkColour
  totalKey: TotalKey
  label: string
  sub: string
  dot: string
}

const COLOURS: ColourMeta[] = [
  { colour: 'blue', totalKey: 'minBlue', label: 'Blue', sub: 'Stats', dot: 'bg-sky-500' },
  { colour: 'pink', totalKey: 'minPink', label: 'Pink', sub: 'Aptitude', dot: 'bg-pink-500' },
  { colour: 'green', totalKey: 'minGreen', label: 'Green', sub: 'Unique', dot: 'bg-green-500' },
  { colour: 'white', totalKey: 'minWhite', label: 'White', sub: 'Skills / Races', dot: 'bg-zinc-300 ring-1 ring-border' },
]

const MODE_LABEL: Record<SparkConditionMode, string> = {
  include: 'has',
  atleast: '≥',
  exclude: 'not',
}

const SELECT_CLASS =
  'h-11 min-w-0 w-full rounded-md border border-input bg-background px-2 text-base outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50 md:h-7 md:w-auto md:text-xs'

export function SparkFilterBar({
  value,
  onChange,
  options,
  maxStars = MAX_TYPE_STARS,
  conditionLimits,
  totalMaxByColour,
  hideFactorColours = [],
  scopeLabel = 'full lineage',
  disabled = false,
}: SparkFilterBarProps) {
  const starChoices = Array.from({ length: maxStars }, (_, i) => i + 1)
  const hiddenFactorColours = new Set<SparkColour>(hideFactorColours)
  const visibleFactorColours = COLOURS.filter((meta) => !hiddenFactorColours.has(meta.colour))

  function visibleConditions(conditions = value.conditions) {
    return conditions.filter((condition) => !hiddenFactorColours.has(condition.colour))
  }

  function totalMax(colour: SparkColour): number {
    return totalMaxByColour?.[colour] ?? MAX_TYPE_STARS
  }

  function setTotal(key: TotalKey, colour: SparkColour, n: number) {
    const max = totalMax(colour)
    const clamped = Number.isFinite(n) ? Math.max(0, Math.min(max, Math.trunc(n))) : 0
    onChange({ ...value, [key]: clamped, conditions: visibleConditions() })
  }

  function addCondition(colour: SparkColour) {
    if (hiddenFactorColours.has(colour)) return
    const first = firstUnusedOption(colour)
    if (!first) return
    onChange({
      ...value,
      conditions: [...visibleConditions(), { colour, name: first, mode: 'atleast', minStars: 1 }],
    })
  }

  function patchCondition(index: number, patch: Partial<SparkFilter['conditions'][number]>) {
    onChange({
      ...value,
      conditions: visibleConditions(
        value.conditions.map((condition, i) =>
          i === index ? { ...condition, ...patch } : condition,
        ),
      ),
    })
  }

  function removeCondition(index: number) {
    onChange({ ...value, conditions: visibleConditions(value.conditions.filter((_, i) => i !== index)) })
  }

  function usedNamesForColour(colour: SparkColour, exceptIndex?: number): Set<string> {
    const used = new Set<string>()
    value.conditions.forEach((condition, index) => {
      if (index === exceptIndex || condition.colour !== colour || hiddenFactorColours.has(condition.colour)) return
      if (condition.name) used.add(condition.name)
    })
    return used
  }

  function firstUnusedOption(colour: SparkColour): string {
    const used = usedNamesForColour(colour)
    return (options[colour] ?? []).find((name) => !used.has(name)) ?? ''
  }

  function optionsForCondition(colour: SparkColour, currentName: string, index: number): string[] {
    const usedByOtherRows = usedNamesForColour(colour, index)
    const rowOptions = (options[colour] ?? []).filter(
      (name) => name === currentName || !usedByOtherRows.has(name),
    )
    return currentName && !rowOptions.includes(currentName) ? [currentName, ...rowOptions] : rowOptions
  }

  return (
    <div
      data-testid="spark-filter"
      className="flex flex-col gap-3 rounded-lg border border-border bg-muted/30 p-3"
    >
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Spark filters
        </span>
        <Button
          type="button"
          variant="ghost"
          size="xs"
          onClick={() => onChange(EMPTY_SPARK_FILTER)}
          data-testid="spark-clear"
          disabled={disabled}
        >
          <RotateCcw />
          Clear
        </Button>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        {visibleFactorColours.map((meta) => {
          const colourOptions = options[meta.colour] ?? []
          const rows = value.conditions
            .map((condition, index) => ({ condition, index }))
            .filter((row) => row.condition.colour === meta.colour)
          const limit = conditionLimits?.[meta.colour]
          const atLimit = typeof limit === 'number' && rows.length >= limit
          const hasUnusedOption = !!firstUnusedOption(meta.colour)
          const addDisabled = disabled || colourOptions.length === 0 || atLimit || !hasUnusedOption

          return (
            <div key={meta.colour} className="flex flex-col gap-1.5 rounded-md border border-border/60 bg-background/40 p-2">
              <div className="flex items-center justify-between">
                <span className="flex items-center gap-1.5 text-xs font-medium text-foreground">
                  <span className={`size-2 rounded-full ${meta.dot}`} />
                  {meta.label}
                  <span className="font-normal text-muted-foreground">{meta.sub}</span>
                  {typeof limit === 'number' && (
                    <span className="text-[10px] text-muted-foreground">({rows.length}/{limit})</span>
                  )}
                </span>
                <Button
                  type="button"
                  variant="outline"
                  size="xs"
                  data-testid={`spark-add-${meta.colour}`}
                  onClick={() => addCondition(meta.colour)}
                  disabled={addDisabled}
                >
                  <Plus />
                  Add
                </Button>
              </div>

              {rows.length === 0 ? (
                <p className="text-[11px] text-muted-foreground">
                  {colourOptions.length === 0 ? 'None on these parents.' : 'Any'}
                </p>
              ) : (
                rows.map(({ condition, index }) => {
                  const rowOptions = optionsForCondition(meta.colour, condition.name, index)

                  return (
                    <div
                      key={index}
                      data-testid={`spark-condition-${index}`}
                      className="grid grid-cols-1 items-center gap-1.5 md:grid-cols-[1fr_auto_auto_auto]"
                    >
                      <select
                        value={condition.name}
                        data-testid={`spark-condition-name-${index}`}
                        disabled={disabled}
                        onChange={(event) => patchCondition(index, { name: event.target.value })}
                        className={SELECT_CLASS}
                      >
                        {rowOptions.map((name) => (
                          <option key={name} value={name}>
                            {name}
                          </option>
                        ))}
                      </select>
                      <select
                        value={condition.mode === 'exclude' ? 'exclude' : 'atleast'}
                        data-testid={`spark-condition-mode-${index}`}
                        disabled={disabled}
                        onChange={(event) =>
                          patchCondition(index, { mode: event.target.value as SparkConditionMode })
                        }
                        className={SELECT_CLASS}
                        aria-label="Match mode"
                      >
                        <option value="atleast">{MODE_LABEL.atleast}</option>
                        <option value="exclude">{MODE_LABEL.exclude}</option>
                      </select>
                      <select
                        value={condition.minStars}
                        data-testid={`spark-condition-stars-${index}`}
                        disabled={disabled || condition.mode === 'exclude'}
                        onChange={(event) =>
                          patchCondition(index, { minStars: Number(event.target.value) || 1 })
                        }
                        className={SELECT_CLASS}
                        aria-label="Minimum stars"
                      >
                        {starChoices.map((star) => (
                          <option key={star} value={star}>
                            {star}★
                          </option>
                        ))}
                      </select>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon-xs"
                        data-testid={`spark-condition-remove-${index}`}
                        disabled={disabled}
                        onClick={() => removeCondition(index)}
                        aria-label="Remove spark condition"
                      >
                        <X />
                      </Button>
                    </div>
                  )
                })
              )}
            </div>
          )
        })}
      </div>

      <div className="flex flex-col gap-1.5 border-t border-border/60 pt-2">
        <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          Total ★ ({scopeLabel})
        </span>
        <div className="flex flex-wrap items-center gap-3">
          {COLOURS.map((meta) => (
            <label key={meta.totalKey} className="flex items-center gap-1.5 text-xs text-foreground">
              <span className={`size-2 rounded-full ${meta.dot}`} />
              <span className="font-medium">{meta.label}</span>
              <span className="text-muted-foreground">≥</span>
              <Input
                type="number"
                min={0}
                max={totalMax(meta.colour)}
                data-testid={`spark-${meta.totalKey}`}
                value={value[meta.totalKey]}
                disabled={disabled}
                onChange={(event) => setTotal(meta.totalKey, meta.colour, Number(event.target.value))}
                className="w-16 px-2 md:h-7 md:w-12 md:text-xs"
              />
            </label>
          ))}
        </div>
      </div>
    </div>
  )
}
