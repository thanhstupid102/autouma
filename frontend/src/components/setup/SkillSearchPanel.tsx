/**
 * SkillSearchPanel — right panel of the skill editor dialog.
 *
 * Renders:
 *   - Search input
 *   - Affinity filter chips (row 1) + Color filter chips (row 2), single-select toggles
 *   - Filtered skill list (click to add to focused area)
 *   - Bulk action buttons: ADD ALL VISIBLE / BLACKLIST ALL VISIBLE / REMOVE ALL VISIBLE
 */

import { ScrollArea } from '@/components/ui/scroll-area'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import {
  SKILL_FILTERS,
  COLOR_FILTERS,
  matchesFilters,
} from './skillEditorRules'
import type { DedupedSkill, AffinityFilter, ColorFilter } from './skillEditorRules'

interface SkillSearchPanelProps {
  skills: DedupedSkill[]
  query: string
  affinityFilter: number | 'turf' | null
  colorFilter: ColorFilter | null
  uniqueOnly: boolean
  onQueryChange: (q: string) => void
  onAffinityFilterChange: (id: number | 'turf' | null) => void
  onColorFilterChange: (filter: ColorFilter | null) => void
  onUniqueOnlyChange: (uniqueOnly: boolean) => void
  onSkillClick: (name: string) => void
  onAddAllVisible: (visibleNames: string[]) => void
  onBlacklistAllVisible: (visibleNames: string[]) => void
  onRemoveAllVisible: (visibleNames: string[]) => void
}

export function SkillSearchPanel({
  skills,
  query,
  affinityFilter,
  colorFilter,
  uniqueOnly,
  onQueryChange,
  onAffinityFilterChange,
  onColorFilterChange,
  onUniqueOnlyChange,
  onSkillClick,
  onAddAllVisible,
  onBlacklistAllVisible,
  onRemoveAllVisible,
}: SkillSearchPanelProps) {
  // Compute visible skills
  const visible = skills.filter((s) =>
    matchesFilters(s, query, affinityFilter, colorFilter, uniqueOnly),
  )
  const visibleNames = visible.map((s) => s.name)

  function toggleAffinity(filter: AffinityFilter) {
    if (affinityFilter === filter.id) onAffinityFilterChange(null)
    else onAffinityFilterChange(filter.id)
  }

  function toggleColor(filter: ColorFilter) {
    if (colorFilter?.id === filter.id) onColorFilterChange(null)
    else onColorFilterChange(filter)
  }

  return (
    <div className="flex flex-col gap-2 h-full min-h-0">
      {/* Search input */}
      <Input
        placeholder="Search skills…"
        value={query}
        onChange={(e) => onQueryChange(e.target.value)}
        className="shrink-0"
      />

      {/* Affinity filter chips */}
      <div className="shrink-0 flex flex-wrap gap-1">
        {SKILL_FILTERS.map((f) => {
          const isActive = affinityFilter === f.id
          return (
            <button
              key={String(f.id)}
              data-slot="skill-filter"
              type="button"
              onClick={() => toggleAffinity(f)}
              aria-pressed={isActive}
              className={cn(
                'min-h-11 rounded-full border px-3 py-1 text-sm font-bold transition-colors md:min-h-0 md:px-2.5 md:py-0.5 md:text-xs',
                isActive
                  ? 'bg-primary/15 border-primary text-primary'
                  : 'bg-muted/40 border-transparent text-muted-foreground hover:border-muted-foreground/40',
              )}
            >
              {f.label}
            </button>
          )
        })}
      </div>

      {/* Color filter chips + Unique toggle */}
      <div className="shrink-0 flex flex-wrap items-center gap-1">
        {COLOR_FILTERS.map((f) => {
          const isActive = colorFilter?.id === f.id
          return (
            <button
              key={f.id}
              data-slot="skill-filter"
              type="button"
              onClick={() => toggleColor(f)}
              aria-pressed={isActive}
              style={{
                color: f.color,
                borderColor: isActive ? f.color : 'transparent',
                backgroundColor: isActive ? `${f.color}22` : undefined,
              }}
              className={cn(
                'min-h-11 rounded-full border px-3 py-1 text-sm font-bold transition-colors md:min-h-0 md:px-2.5 md:py-0.5 md:text-xs',
                !isActive && 'bg-muted/40 hover:border-muted-foreground/40',
              )}
            >
              {f.label}
            </button>
          )
        })}

        {/* Divider before the rarity-based Unique filter */}
        <span className="mx-0.5 h-3.5 w-px bg-border" aria-hidden="true" />

        <button
          data-slot="skill-filter"
          type="button"
          onClick={() => onUniqueOnlyChange(!uniqueOnly)}
          aria-pressed={uniqueOnly}
          className={cn(
            'min-h-11 rounded-full border px-3 py-1 text-sm font-bold transition-colors md:min-h-0 md:px-2.5 md:py-0.5 md:text-xs',
            uniqueOnly
              ? 'border-amber-400 bg-amber-400/15 text-amber-500'
              : 'bg-muted/40 border-transparent text-muted-foreground hover:border-muted-foreground/40',
          )}
        >
          ★ Unique
        </button>
      </div>

      {/* Skill list */}
      <ScrollArea className="flex-1 min-h-0 rounded-lg border bg-muted/20">
        <div className="flex flex-col gap-px p-1">
          {visible.length === 0 ? (
            <div className="p-3 text-xs text-muted-foreground">No skills found.</div>
          ) : (
            visible.map((s) => (
              <button
                key={s.name}
                data-slot="skill-result"
                type="button"
                onClick={() => onSkillClick(s.name)}
                className="min-h-11 w-full rounded px-3 py-2 text-left text-sm transition-colors hover:bg-muted/60 md:min-h-0 md:truncate md:px-2 md:py-1 md:text-xs"
              >
                {s.name}
              </button>
            ))
          )}
        </div>
      </ScrollArea>

      {/* Bulk action buttons */}
      <div className="shrink-0 flex flex-col gap-1.5">
        <Button
          size="sm"
          variant="outline"
          className="w-full text-xs"
          onClick={() => onAddAllVisible(visibleNames)}
          disabled={visibleNames.length === 0}
        >
          ADD ALL VISIBLE
        </Button>
        <Button
          size="sm"
          variant="outline"
          className="w-full text-xs text-destructive border-destructive/40 hover:bg-destructive/10"
          onClick={() => onBlacklistAllVisible(visibleNames)}
          disabled={visibleNames.length === 0}
        >
          BLACKLIST ALL VISIBLE
        </Button>
        <Button
          size="sm"
          variant="outline"
          className="w-full text-xs"
          onClick={() => onRemoveAllVisible(visibleNames)}
          disabled={visibleNames.length === 0}
        >
          REMOVE ALL VISIBLE
        </Button>
      </div>
    </div>
  )
}
