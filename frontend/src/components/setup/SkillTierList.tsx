/**
 * SkillTierList — left panel of the skill editor dialog.
 *
 * Renders:
 *   - Stack of tier dropzones (clickable to focus, × to delete individual skills, DEL to delete tier)
 *   - Blacklist zone (clickable to focus, × to delete, CLEAR button)
 *   - "+ TIER" button
 *
 * All mutations are lifted up to the parent via callbacks; this component
 * is purely presentational + focus management.
 */

import { ScrollArea } from '@/components/ui/scroll-area'
import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'
import { cn } from '@/lib/utils'

interface SkillTierListProps {
  tiers: string[][]
  blacklist: string[]
  activeEditTier: number | null   // null = blacklist focused
  onFocusTier: (idx: number) => void
  onFocusBlacklist: () => void
  onDeleteTier: (idx: number) => void
  onDeleteSkillFromTier: (tierIdx: number, name: string) => void
  onDeleteSkillFromBlacklist: (name: string) => void
  onAddTier: () => void
  onClearBlacklist: () => void
}

export function SkillTierList({
  tiers,
  blacklist,
  activeEditTier,
  onFocusTier,
  onFocusBlacklist,
  onDeleteTier,
  onDeleteSkillFromTier,
  onDeleteSkillFromBlacklist,
  onAddTier,
  onClearBlacklist,
}: SkillTierListProps) {
  return (
    <div className="flex flex-col gap-3 h-full min-h-0">
      <ScrollArea className="flex-1 min-h-0 pr-1">
        <div className="flex flex-col gap-2 pb-2">
          {/* Tier zones */}
          {tiers.map((tier, i) => {
            const isActive = activeEditTier === i
            return (
              <div
                key={i}
                data-slot="skill-tier"
                role="button"
                tabIndex={0}
                onClick={() => onFocusTier(i)}
                onKeyDown={(e) => e.key === 'Enter' && onFocusTier(i)}
                className={cn(
                  'min-h-11 rounded-lg border-2 p-3 cursor-pointer select-none transition-colors md:min-h-0 md:p-2',
                  isActive
                    ? 'border-primary bg-primary/5'
                    : 'border-border bg-muted/30 hover:border-muted-foreground/40',
                )}
              >
                {/* Tier header */}
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-xs font-bold tracking-wide text-muted-foreground uppercase">
                    Tier {i + 1}
                  </span>
                  <Button
                    size="xs"
                    variant="destructive"
                    onClick={(e) => {
                      e.stopPropagation()
                      onDeleteTier(i)
                    }}
                  >
                    DEL
                  </Button>
                </div>

                {/* Skill tags */}
                <div className="flex flex-wrap gap-1 min-h-[22px]">
                  {tier.length === 0 && (
                    <span className="text-xs text-muted-foreground italic">
                      (empty — click skills to add)
                    </span>
                  )}
                  {tier.map((name) => (
                    <SkillTag
                      key={name}
                      name={name}
                      onDelete={(e) => {
                        e.stopPropagation()
                        onDeleteSkillFromTier(i, name)
                      }}
                    />
                  ))}
                </div>
              </div>
            )
          })}

          {tiers.length > 0 && <Separator className="my-1" />}

          {/* Blacklist zone */}
          <div
            data-slot="skill-blacklist"
            role="button"
            tabIndex={0}
            onClick={onFocusBlacklist}
            onKeyDown={(e) => e.key === 'Enter' && onFocusBlacklist()}
            className={cn(
              'min-h-11 rounded-lg border-2 p-3 cursor-pointer select-none transition-colors md:min-h-0 md:p-2',
              activeEditTier === null
                ? 'border-destructive/60 bg-destructive/5'
                : 'border-border bg-muted/30 hover:border-muted-foreground/40',
            )}
          >
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-xs font-bold tracking-wide text-muted-foreground uppercase">
                Blacklist
              </span>
              <Button
                size="xs"
                variant="outline"
                onClick={(e) => {
                  e.stopPropagation()
                  onClearBlacklist()
                }}
              >
                CLEAR
              </Button>
            </div>

            <div className="flex flex-wrap gap-1 min-h-[22px]">
              {blacklist.length === 0 && (
                <span className="text-xs text-muted-foreground italic">
                  (none — click skills to blacklist)
                </span>
              )}
              {blacklist.map((name) => (
                <SkillTag
                  key={name}
                  name={name}
                  variant="destructive"
                  onDelete={(e) => {
                    e.stopPropagation()
                    onDeleteSkillFromBlacklist(name)
                  }}
                />
              ))}
            </div>
          </div>
        </div>
      </ScrollArea>

      {/* Add Tier button */}
      <Button size="sm" variant="outline" className="w-full mt-auto" onClick={onAddTier}>
        + TIER
      </Button>
    </div>
  )
}

// ---------------------------------------------------------------------------
// SkillTag — small pill with × button
// ---------------------------------------------------------------------------

interface SkillTagProps {
  name: string
  variant?: 'default' | 'destructive'
  onDelete: (e: React.MouseEvent) => void
}

function SkillTag({ name, variant = 'default', onDelete }: SkillTagProps) {
  return (
    <span
      data-slot="skill-chip"
      className={cn(
        'inline-flex min-h-11 items-center gap-0.5 rounded-full py-0 pl-3 pr-0 text-sm font-medium md:min-h-0 md:px-2 md:py-0.5 md:text-xs',
        variant === 'destructive'
          ? 'bg-destructive/10 text-destructive'
          : 'bg-primary/10 text-primary',
      )}
    >
      <span className="max-w-[min(14rem,calc(100vw-7rem))] truncate md:max-w-[140px]">{name}</span>
      <button
        type="button"
        aria-label={`Remove ${name}`}
        onClick={onDelete}
        className="ml-0.5 flex size-11 shrink-0 items-center justify-center rounded-full opacity-70 hover:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring md:size-4 md:opacity-60"
      >
        ×
      </button>
    </span>
  )
}
