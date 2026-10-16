/**
 * RacePickerDialog — shadcn Dialog for selecting races in a single time slot.
 *
 * Ported from app.js:1252-1319 (openSlotPopup).
 * Scenario is hardcoded to 'Mant' (the active path).
 */

import {
  Dialog,
  DialogBody,
  DialogClose,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'

import { raceKeys, raceBadge, YEAR_LABELS } from './raceRules'
import type { Race, Slot } from './raceRules'

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface RacePickerDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  slot: Slot | null
  selectedRaces: number[]
  onToggle: (race: Race, slotIds: number[]) => void
}

// ---------------------------------------------------------------------------
// Scenario — hardcoded to Mant (the active path per task spec)
// ---------------------------------------------------------------------------
const SCENARIO = 'Mant'

// ---------------------------------------------------------------------------
// RacePickerDialog
// ---------------------------------------------------------------------------

export function RacePickerDialog({
  open,
  onOpenChange,
  slot,
  selectedRaces,
  onToggle,
}: RacePickerDialogProps) {
  if (!slot) return null

  const yearLabel = YEAR_LABELS[slot.yearIdx]
  const title = `${yearLabel} - ${slot.label}`

  // Compute slotIds = all raceKeys across all races in this slot
  const slotIds = slot.races.flatMap((r) => raceKeys(r))

  // Which selected ids belong to this slot
  const selectedInSlot = selectedRaces.filter((id) => slotIds.includes(id))

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg md:max-h-[80vh]">
        <DialogHeader className="sticky top-0 z-10 shrink-0 bg-popover pr-10 md:static md:z-auto md:bg-transparent md:pr-0">
          <DialogTitle className="text-sm font-semibold">{title}</DialogTitle>
        </DialogHeader>

        <DialogBody className="py-1 md:py-0">
          {slot.races.length === 0 ? (
            <p className="py-4 text-center text-sm text-muted-foreground">
              No races available
            </p>
          ) : (
            <div className="flex min-w-0 flex-col gap-1">
              {slot.races.map((race) => {
                const myIds = raceKeys(race)
                const selIndex = selectedInSlot.findIndex((id) => myIds.includes(id))
                const isSelected = selIndex !== -1
                const badgeText = isSelected
                  ? raceBadge(selIndex, selectedInSlot.length, SCENARIO)
                  : null

                return (
                  <button
                    key={race.id}
                    type="button"
                    onClick={() => onToggle(race, slotIds)}
                    className={[
                      'flex min-w-0 max-w-full items-center gap-3 overflow-hidden rounded-md px-3 py-2 text-left transition-colors',
                      'hover:bg-accent/50 cursor-pointer',
                      isSelected
                        ? 'bg-accent border border-primary/30'
                        : 'bg-card border border-border/40',
                    ].join(' ')}
                  >
                    {/* Race image — legacy: 80×50 (aspect ~161/80) */}
                    <div className="relative w-20 h-[50px] flex-shrink-0 rounded overflow-hidden bg-muted flex items-center justify-center">
                      <RaceImage name={race.name} fallback="/broom.png" width={80} height={50} />
                    </div>

                    {/* Info */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1.5 flex-wrap">
                        <GradeBadge type={race.type} />
                        <span className="text-sm font-medium truncate">{race.name}</span>
                      </div>
                      <div className="flex items-center gap-2 mt-0.5">
                        <span
                          className={[
                            'text-xs capitalize',
                            race.terrain.toLowerCase() === 'turf'
                              ? 'text-green-600 dark:text-green-400'
                              : 'text-amber-600 dark:text-amber-400',
                          ].join(' ')}
                        >
                          {race.terrain}
                        </span>
                        <span className="text-xs text-muted-foreground">{race.distance}</span>
                      </div>
                    </div>

                    {/* Selection badge */}
                    {isSelected && badgeText && (
                      <SelectionBadge text={badgeText} />
                    )}
                    {!isSelected && (
                      <span className="text-muted-foreground/40 text-sm">✓</span>
                    )}
                  </button>
                )
              })}
            </div>
          )}
        </DialogBody>

        <DialogFooter className="md:hidden">
          <DialogClose asChild>
            <Button size="sm">Done</Button>
          </DialogClose>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function RaceImage({
  name,
  fallback,
  width,
  height,
}: {
  name: string
  fallback: string
  width: number
  height: number
}) {
  return (
    <img
      src={`/races/${encodeURIComponent(name)}.png`}
      alt={name}
      width={width}
      height={height}
      className="object-cover w-full h-full"
      onError={(e) => {
        const img = e.currentTarget
        if (img.src !== window.location.origin + fallback) {
          img.src = fallback
        }
      }}
    />
  )
}

function GradeBadge({ type }: { type: string }) {
  const cls = `badge-${type.toLowerCase().replace(/-/g, '')}`
  return (
    <Badge
      variant="secondary"
      className={`text-[10px] px-1.5 py-0 h-auto font-bold ${cls}`}
    >
      {type}
    </Badge>
  )
}

function SelectionBadge({ text }: { text: string }) {
  const isMain = text === 'MAIN'
  const isRival = text.startsWith('RIVAL')
  return (
    <span
      className={[
        'shrink-0 text-[10px] font-bold px-2 py-0.5 rounded-full',
        isMain
          ? 'bg-primary/20 text-primary border border-primary/30'
          : isRival
          ? 'bg-muted text-muted-foreground border border-border'
          : 'bg-primary/10 text-primary',
      ].join(' ')}
    >
      {text}
    </span>
  )
}
