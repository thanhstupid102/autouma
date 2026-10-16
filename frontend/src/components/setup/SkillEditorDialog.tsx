/**
 * SkillEditorDialog — full-screen shadcn Dialog for editing skill tiers and blacklist.
 *
 * Data model:
 *   learn_skill_list     = string[][] — tiers of skill names
 *   learn_skill_blacklist = string[]  — flat blacklist of skill names
 *
 * Persistence: save-on-edit via presets.update() — matches legacy behaviour.
 *
 * activeEditTier: number (tier index) | null (blacklist focused)
 * Defaults to 0 on open; resets search/filters on open.
 */

import { useState, useEffect, useCallback, useRef } from 'react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogClose,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'
import { cn } from '@/lib/utils'

import { usePresets } from '@/stores/presets'
import { getSkills } from '@/api/presets'
import type { Preset } from '@/api/types'

import {
  dedupeSkills,
  buildGroupSiblings,
  addSkillToFocus,
  deleteSkillFromTier,
  deleteSkillFromBlacklist,
  addTier,
  deleteTier,
  addAllVisible,
  removeAllVisible,
  blacklistAllVisible,
  clearBlacklist,
} from './skillEditorRules'
import type { DedupedSkill, ColorFilter } from './skillEditorRules'

import { SkillTierList } from './SkillTierList'
import { SkillSearchPanel } from './SkillSearchPanel'

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface SkillEditorDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function SkillEditorDialog({ open, onOpenChange }: SkillEditorDialogProps) {
  const { getActive, update } = usePresets()

  // Skill catalogue — loaded once when dialog opens, cached across reopens
  const skillCacheRef = useRef<DedupedSkill[] | null>(null)
  // name -> every name sharing its skill group (white ○ / ◎ / gold tiers), so
  // selecting one tier moves the whole group. Built from the raw skills record.
  const siblingsRef = useRef<Record<string, string[]>>({})
  const [skills, setSkills] = useState<DedupedSkill[]>([])
  const [skillsLoading, setSkillsLoading] = useState(false)

  // Right-panel filter state
  const [query, setQuery] = useState('')
  const [affinityFilter, setAffinityFilter] = useState<number | 'turf' | null>(null)
  const [colorFilter, setColorFilter] = useState<ColorFilter | null>(null)
  const [uniqueOnly, setUniqueOnly] = useState(false)

  // Which area is focused: tier index or null (blacklist)
  const [activeEditTier, setActiveEditTier] = useState<number | null>(0)
  const [mobilePanel, setMobilePanel] = useState<'lists' | 'catalogue'>('lists')

  // Reset state when dialog opens
  useEffect(() => {
    if (!open) return

    // Reset filters
    setQuery('')
    setAffinityFilter(null)
    setColorFilter(null)
    setUniqueOnly(false)
    setActiveEditTier(0)
    setMobilePanel('lists')

    // Load skills (use cached if available)
    if (skillCacheRef.current) {
      setSkills(skillCacheRef.current)
      return
    }
    setSkillsLoading(true)
    getSkills()
      .then((res) => {
        if (res.success && res.skills) {
          // The API returns skills as an array (each carries its own id); rebuild the
          // id-keyed record the editor rules expect, so dedupeSkills/buildGroupSiblings
          // stay unchanged.
          const record = Object.fromEntries(res.skills.map((s) => [String(s.id), s]))
          const deduped = dedupeSkills(record)
          skillCacheRef.current = deduped
          siblingsRef.current = buildGroupSiblings(record)
          setSkills(deduped)
        }
      })
      .catch(() => {/* ignore — skill list stays empty */})
      .finally(() => setSkillsLoading(false))
  }, [open])

  const active = getActive()

  // ---------------------------------------------------------------------------
  // Mutation helpers — read from store, apply reducer, persist
  // ---------------------------------------------------------------------------

  const applyMutation = useCallback(
    (mutated: { learn_skill_list: string[][]; learn_skill_blacklist: string[] }) => {
      const current = getActive()
      if (!current) return
      const updated: Preset = {
        ...current,
        learn_skill_list: mutated.learn_skill_list,
        learn_skill_blacklist: mutated.learn_skill_blacklist,
      }
      update(updated)
    },
    [getActive, update],
  )

  function getLists() {
    const current = getActive()
    return {
      learn_skill_list: current?.learn_skill_list ?? [],
      learn_skill_blacklist: current?.learn_skill_blacklist ?? [],
    }
  }

  // Individual skill add (click in right panel)
  function handleSkillClick(name: string) {
    const result = addSkillToFocus(getLists(), name, activeEditTier, siblingsRef.current)
    applyMutation(result)
  }

  // × on a tier skill
  function handleDeleteSkillFromTier(tierIdx: number, name: string) {
    const result = deleteSkillFromTier(getLists(), tierIdx, name)
    applyMutation(result)
  }

  // × on a blacklist skill
  function handleDeleteSkillFromBlacklist(name: string) {
    const result = deleteSkillFromBlacklist(getLists(), name)
    applyMutation(result)
  }

  // + TIER
  function handleAddTier() {
    const { lists, newTierIdx } = addTier(getLists())
    applyMutation(lists)
    setActiveEditTier(newTierIdx)
  }

  // DEL tier
  function handleDeleteTier(idx: number) {
    const { lists, newActiveEditTier } = deleteTier(getLists(), idx, activeEditTier)
    applyMutation(lists)
    setActiveEditTier(newActiveEditTier)
  }

  // CLEAR blacklist
  function handleClearBlacklist() {
    const result = clearBlacklist(getLists())
    applyMutation(result)
  }

  // Bulk: ADD ALL VISIBLE
  function handleAddAllVisible(visibleNames: string[]) {
    const result = addAllVisible(getLists(), visibleNames, activeEditTier, siblingsRef.current)
    applyMutation(result)
  }

  // Bulk: BLACKLIST ALL VISIBLE
  function handleBlacklistAllVisible(visibleNames: string[]) {
    const result = blacklistAllVisible(getLists(), visibleNames, siblingsRef.current)
    applyMutation(result)
  }

  // Bulk: REMOVE ALL VISIBLE
  function handleRemoveAllVisible(visibleNames: string[]) {
    const result = removeAllVisible(getLists(), visibleNames, activeEditTier)
    applyMutation(result)
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  const tiers = active?.learn_skill_list ?? []
  const blacklist = active?.learn_skill_blacklist ?? []

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        size="full-screen"
        showCloseButton={false}
        aria-describedby={undefined}
        className="
          flex flex-col gap-0 p-0 overflow-hidden
          md:inset-auto md:left-1/2 md:top-1/2
          md:h-[95dvh] md:max-h-[95dvh]
          md:w-full md:max-w-none md:-translate-x-1/2 md:-translate-y-1/2
          md:rounded-xl
        "
      >
        {/* Header */}
        <DialogHeader className="flex-row items-center justify-between shrink-0 px-4 py-3 border-b">
          <DialogTitle className="text-base">
            Configure Skills
            {active ? (
              <span className="ml-2 text-sm font-normal text-muted-foreground">
                — {active.name}
              </span>
            ) : null}
          </DialogTitle>
          <DialogClose asChild>
            <Button size="sm" variant="outline">
              DONE
            </Button>
          </DialogClose>
        </DialogHeader>

        {/* No preset guard */}
        {!active ? (
          <div className="flex-1 flex items-center justify-center text-sm text-muted-foreground px-4">
            Select or create a preset first.
          </div>
        ) : (
          <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
            <div
              role="tablist"
              aria-label="Skill editor panels"
              className="grid shrink-0 grid-cols-2 gap-1 border-b bg-muted/30 p-2 md:hidden"
            >
              <Button
                id="skill-editor-lists-tab"
                type="button"
                role="tab"
                size="sm"
                variant={mobilePanel === 'lists' ? 'default' : 'ghost'}
                aria-selected={mobilePanel === 'lists'}
                aria-controls="skill-editor-lists-panel"
                onClick={() => setMobilePanel('lists')}
              >
                Skill Lists
              </Button>
              <Button
                id="skill-editor-catalogue-tab"
                type="button"
                role="tab"
                size="sm"
                variant={mobilePanel === 'catalogue' ? 'default' : 'ghost'}
                aria-selected={mobilePanel === 'catalogue'}
                aria-controls="skill-editor-catalogue-panel"
                onClick={() => setMobilePanel('catalogue')}
              >
                Catalogue
              </Button>
            </div>

            {/* Mobile tabs share these panels; md+ restores the original split view. */}
            <div className="flex min-h-0 flex-1 overflow-hidden">
              {/* LEFT — tier stack + blacklist */}
              <section
                id="skill-editor-lists-panel"
                role="tabpanel"
                aria-labelledby="skill-editor-lists-tab"
                data-testid="skill-editor-lists-panel"
                className={cn(
                  'min-w-0 flex-1 flex-col overflow-hidden p-3',
                  mobilePanel === 'lists' ? 'flex' : 'hidden',
                  'md:flex md:w-[44%] md:flex-none',
                )}
              >
                <p className="shrink-0 text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">
                  Skill Lists
                </p>
                <SkillTierList
                  tiers={tiers}
                  blacklist={blacklist}
                  activeEditTier={activeEditTier}
                  onFocusTier={setActiveEditTier}
                  onFocusBlacklist={() => setActiveEditTier(null)}
                  onDeleteTier={handleDeleteTier}
                  onDeleteSkillFromTier={handleDeleteSkillFromTier}
                  onDeleteSkillFromBlacklist={handleDeleteSkillFromBlacklist}
                  onAddTier={handleAddTier}
                  onClearBlacklist={handleClearBlacklist}
                />
              </section>

              <Separator orientation="vertical" className="hidden shrink-0 md:block" />

              {/* RIGHT — search + skill list + bulk buttons */}
              <section
                id="skill-editor-catalogue-panel"
                role="tabpanel"
                aria-labelledby="skill-editor-catalogue-tab"
                data-testid="skill-editor-catalogue-panel"
                className={cn(
                  'min-w-0 flex-1 flex-col overflow-hidden p-3',
                  mobilePanel === 'catalogue' ? 'flex' : 'hidden',
                  'md:flex',
                )}
              >
                <p className="shrink-0 text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">
                  Skill Catalogue
                  {skillsLoading && (
                    <span className="ml-2 font-normal normal-case">Loading…</span>
                  )}
                </p>
                <SkillSearchPanel
                  skills={skills}
                  query={query}
                  affinityFilter={affinityFilter}
                  colorFilter={colorFilter}
                  uniqueOnly={uniqueOnly}
                  onQueryChange={setQuery}
                  onAffinityFilterChange={setAffinityFilter}
                  onColorFilterChange={setColorFilter}
                  onUniqueOnlyChange={setUniqueOnly}
                  onSkillClick={handleSkillClick}
                  onAddAllVisible={handleAddAllVisible}
                  onBlacklistAllVisible={handleBlacklistAllVisible}
                  onRemoveAllVisible={handleRemoveAllVisible}
                />
              </section>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
