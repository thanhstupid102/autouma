/**
 * ParentGrid — renders session.parents; supports selecting up to 2 veterans.
 *
 * - Rank badge via RANK_MAP
 * - Image /api/images/{card_id}.png
 * - Kicker "ID: {instance_id}"
 * - Non-selected cards are disabled (vet-full) when 2 are already chosen
 * - Hover tooltip shows spark lineage (self/p1/p2 factors) — minimal version
 * - Name + spark filters, plus veteran delete actions for owned parents
 *
 * Legacy ref:
 *   app.js:2518-2537 renderParents
 *   app.js:2422-2434 selectParent
 *   app.js:1005-1014 updateVetSelectability
 *   app.js:765-770   rankMap
 */

import { useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { CheckSquare, CircleX, Filter, Lock, RefreshCw, Settings, Trash2, X } from 'lucide-react'
import { toast } from 'sonner'

import { RANK_MAP, toggleParent } from './libraryRules'
import { GridCard } from './GridCard'
import { GridSearch } from './GridSearch'
import { SparkTooltip, type SparkTree } from './SparkTooltip'
import { SparkFilterBar } from './SparkFilterBar'
import { AutoDeleteSettingsPanel } from './AutoDeleteSettingsPanel'
import { useSparkFilterableGrid } from './useSparkFilterableGrid'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { deleteParents } from '@/api/career'
import type { ParentInfo } from '@/api/types'

interface ParentGridProps {
  parents: ParentInfo[]
  veterans: ParentInfo[]
  onVeteransChange: (vets: ParentInfo[]) => void
  loading?: boolean
  onRefresh?: () => void
  careerActive?: boolean
}

function getParentName(p: ParentInfo): string {
  // 'name' is not in the typed ParentInfo shape but is present at runtime;
  // card_id/instance_id are the fallback identifiers when it's missing.
  return String((p as Record<string, unknown>).name ?? p.card_id ?? p.instance_id ?? 'Unknown')
}

function identityParent(p: ParentInfo): ParentInfo {
  return p
}

function parentMatchesSearchTerm(p: ParentInfo, term: string): boolean {
  return getParentName(p).toLowerCase().includes(term)
}

function getRankBadge(p: ParentInfo): string {
  const rank = (p as Record<string, unknown>).rank
  if (typeof rank === 'number') return RANK_MAP[rank] ?? '??'
  return '??'
}

function isLocked(p: ParentInfo): boolean {
  return Number((p as { is_locked?: number }).is_locked) === 1
}

function getParentId(p: ParentInfo): string {
  return String(p.instance_id ?? '')
}

function parentIds(parents: ParentInfo[]): Set<string> {
  return new Set(parents.map(getParentId).filter(Boolean))
}

export function ParentGrid({
  parents,
  veterans,
  onVeteransChange,
  loading = false,
  onRefresh,
  careerActive = false,
}: ParentGridProps) {
  const queryClient = useQueryClient()
  const {
    search,
    setSearch,
    sparkFilterOpen,
    setSparkFilterOpen,
    sparkFilter,
    setSparkFilter,
    sparkOptions,
    filtered,
    showFilteredCount,
  } = useSparkFilterableGrid({
    items: parents,
    getSparkSubject: identityParent,
    matchesSearch: parentMatchesSearchTerm,
  })
  const [autoDeleteOpen, setAutoDeleteOpen] = useState(false)
  const [selectMode, setSelectMode] = useState(false)
  const [checkedIds, setCheckedIds] = useState<Set<string>>(() => new Set())
  const [deleteTargetIds, setDeleteTargetIds] = useState<string[]>([])
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [deleting, setDeleting] = useState(false)

  const validParentIds = useMemo(() => parentIds(parents), [parents])
  const parentsById = useMemo(
    () => new Map(parents.map((parent) => [getParentId(parent), parent] as const)),
    [parents],
  )

  // Derive (don't sync via effect) the checked ids that still map to a present
  // parent — stale ids that linger after `parents` changes are ignored for the
  // count and delete action; checkboxes only render for visible parents anyway.
  const validCheckedIds = useMemo(
    () => new Set([...checkedIds].filter((id) => validParentIds.has(id))),
    [checkedIds, validParentIds],
  )

  const full = veterans.length >= 2

  function handleClick(p: ParentInfo) {
    if (selectMode) {
      toggleChecked(getParentId(p))
      return
    }
    const next = toggleParent(veterans, p)
    onVeteransChange(next)
  }

  function isSelected(p: ParentInfo): boolean {
    return veterans.some(v => String(v.instance_id) === String(p.instance_id))
  }

  function toggleChecked(id: string, forced?: boolean) {
    if (!id) return
    setCheckedIds((previous) => {
      const next = new Set(previous)
      const checked = forced ?? !next.has(id)
      if (checked) next.add(id)
      else next.delete(id)
      return next
    })
  }

  function openDeleteConfirm(ids: string[]) {
    const uniqueIds = Array.from(new Set(ids.filter((id) => id && parentsById.has(id))))
    if (uniqueIds.length === 0) return
    setDeleteTargetIds(uniqueIds)
    setConfirmOpen(true)
  }

  function handleSelectMode() {
    setSelectMode((current) => {
      const next = !current
      if (!next) setCheckedIds(new Set())
      return next
    })
  }

  async function confirmDelete() {
    const targets = deleteTargetIds
      .map((id) => parentsById.get(id))
      .filter((parent): parent is ParentInfo => !!parent)
    const instanceIds = targets.map((parent) => parent.instance_id)
    if (instanceIds.length === 0) return

    // Clicking Delete in the dialog (which shows the lock warning) is the user's
    // consent to unlock locked (memo) veterans before removing them.
    const unlockLocked = targets.some(isLocked)

    setDeleting(true)
    try {
      const response = await deleteParents({ instance_ids: instanceIds, unlock_locked: unlockLocked })
      if (!response.success) {
        throw new Error(response.detail ?? 'Delete failed')
      }

      const deletedRaw = response.deleted ?? instanceIds
      const deletedIds = new Set(deletedRaw.map((id) => String(id)))
      const requestedIds = new Set(instanceIds.map((id) => String(id)))
      const remainingVeterans = veterans.filter((veteran) => !deletedIds.has(String(veteran.instance_id)))
      if (remainingVeterans.length !== veterans.length) {
        onVeteransChange(remainingVeterans)
      }

      setCheckedIds(new Set())
      setSelectMode(false)
      setConfirmOpen(false)
      setDeleteTargetIds([])
      void queryClient.invalidateQueries({ queryKey: ['session'] })

      if (deletedIds.size < requestedIds.size) {
        toast.warning(response.detail ?? `Deleted ${deletedIds.size} of ${requestedIds.size} veterans`)
      } else {
        toast.success(`Deleted ${deletedIds.size} veteran${deletedIds.size === 1 ? '' : 's'}`)
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Delete failed'
      toast.error(message)
    } finally {
      setDeleting(false)
    }
  }

  const checkedCount = validCheckedIds.size
  const deleteTargets = deleteTargetIds
    .map((id) => parentsById.get(id))
    .filter((parent): parent is ParentInfo => !!parent)
  const lockedTargetCount = deleteTargets.filter(isLocked).length

  return (
    <div className="flex flex-col gap-2">
      <div
        className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-sky-500/30 bg-sky-500/10 px-3 py-2.5"
        data-testid="career-parent-selection-control"
      >
        <div>
          <p className="text-xs font-semibold text-sky-700 dark:text-sky-300">
            Career start parent slots
          </p>
          <p className="text-xs text-muted-foreground">
            Selection only - no veterans will be deleted from your roster.
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={veterans.length === 0}
          onClick={() => onVeteransChange([])}
          data-testid="clear-career-parent-selection"
        >
          <CircleX />
          {veterans.length > 0 ? `Clear career slots (${veterans.length})` : 'Career slots empty'}
        </Button>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          {onRefresh && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={onRefresh}
              disabled={loading || careerActive}
              aria-label="Refresh parent roster"
            >
              <RefreshCw className={loading ? 'animate-spin' : ''} />
              {loading ? 'Loading...' : 'Refresh roster'}
            </Button>
          )}
          <Button
            type="button"
            variant="outline"
            size="xs"
            onClick={() => setSparkFilterOpen((open) => !open)}
            aria-expanded={sparkFilterOpen}
            data-testid="spark-filter-toggle"
          >
            <Filter />
            Spark filters
          </Button>
          <Button
            type="button"
            variant="outline"
            size="xs"
            onClick={() => setAutoDeleteOpen((open) => !open)}
            aria-expanded={autoDeleteOpen}
            data-testid="auto-delete-settings-toggle"
          >
            <Settings />
            Auto-delete rules
          </Button>
          {careerActive && (
            <span className="text-xs text-muted-foreground">Refresh paused during active career</span>
          )}
        </div>

        <div className="flex flex-wrap items-center justify-end gap-2">
          {parents.length > 8 && (
            <GridSearch value={search} onChange={setSearch} placeholder="Search parents..." />
          )}
          <Button
            type="button"
            variant={selectMode ? 'secondary' : 'outline'}
            size="xs"
            onClick={handleSelectMode}
            data-testid="parent-select-mode"
          >
            {selectMode ? <X /> : <CheckSquare />}
            {selectMode ? 'Cancel' : 'Select'}
          </Button>
          {selectMode && checkedCount > 0 && (
            <Button
              type="button"
              variant="destructive"
              size="xs"
              onClick={() => openDeleteConfirm([...validCheckedIds])}
              data-testid="parent-delete-selected"
            >
              <Trash2 />
              Delete selected ({checkedCount})
            </Button>
          )}
        </div>
      </div>

      {sparkFilterOpen && (
        <SparkFilterBar
          value={sparkFilter}
          onChange={setSparkFilter}
          options={sparkOptions}
          conditionLimits={{ blue: 3, pink: 3, green: 3 }}
        />
      )}

      {autoDeleteOpen && <AutoDeleteSettingsPanel options={sparkOptions} />}

      {filtered.length === 0 && (
        <p className="text-sm text-muted-foreground">
          {parents.length === 0
            ? 'No veterans in the current game roster.'
            : 'No parents match the current filters.'}
        </p>
      )}

      {showFilteredCount && filtered.length > 0 && (
        <p className="text-xs text-muted-foreground">
          Showing {filtered.length} of {parents.length} parents.
        </p>
      )}

      <div className="grid min-w-0 max-w-full grid-cols-3 gap-2 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-6">
        {filtered.map(p => {
          const id = getParentId(p)
          const sel = isSelected(p)
          const disabled = !selectMode && full && !sel
          return (
            <SparkTooltip
              key={id}
              tree={p.tree as SparkTree | undefined}
              label={`Spark details for ${getParentName(p)}`}
            >
              <div>
                <GridCard
                  imgId={p.card_id ?? '100101'}
                  name={getParentName(p)}
                  kicker={`ID: ${p.instance_id ?? '?'}`}
                  rankBadge={getRankBadge(p)}
                  selected={sel}
                  disabled={disabled}
                  onClick={() => handleClick(p)}
                  testId={`parent-card-${id}`}
                >
                  {isLocked(p) && (
                    <span
                      className="absolute left-1 top-6 z-20 rounded-md bg-amber-500/90 p-0.5 text-white shadow-sm"
                      title="Locked (memo) — will be unlocked before delete"
                      data-testid={`parent-locked-${id}`}
                      aria-label="Locked"
                    >
                      <Lock className="size-3" />
                    </span>
                  )}
                  {selectMode ? (
                    <div
                      className="absolute right-1 top-1 z-20 rounded-md bg-background/90 p-1 shadow-sm"
                      onClick={(event) => event.stopPropagation()}
                    >
                      <Checkbox
                        data-testid={`parent-checkbox-${id}`}
                        aria-label={`Select ${getParentName(p)}`}
                        checked={checkedIds.has(id)}
                        onCheckedChange={(checked) => toggleChecked(id, checked === true)}
                      />
                    </div>
                  ) : (
                    <Button
                      type="button"
                      variant="destructive"
                      size="icon-xs"
                      className="absolute right-1 top-1 z-20 bg-background/90 shadow-sm"
                      data-testid={`parent-delete-${id}`}
                      aria-label={`Delete ${getParentName(p)}`}
                      onClick={(event) => {
                        event.stopPropagation()
                        openDeleteConfirm([id])
                      }}
                    >
                      <Trash2 />
                    </Button>
                  )}
                </GridCard>
              </div>
            </SparkTooltip>
          )
        })}
      </div>

      {full && (
        <p className="text-xs text-muted-foreground">
          2 parents selected for career start. Use Clear career slots if one is no longer in the roster.
        </p>
      )}

      <Dialog open={confirmOpen} onOpenChange={(open) => {
        if (!deleting) setConfirmOpen(open)
      }}>
        <DialogContent showCloseButton={!deleting}>
          <DialogHeader>
            <DialogTitle>
              Delete {deleteTargets.length} veteran{deleteTargets.length === 1 ? '' : 's'}?
            </DialogTitle>
            <DialogDescription>
              This cannot be undone.
            </DialogDescription>
          </DialogHeader>

          {lockedTargetCount > 0 && (
            <div
              data-testid="parent-delete-locked-warning"
              className="flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 p-2 text-xs text-amber-600 dark:text-amber-400"
            >
              <Lock className="mt-0.5 size-3.5 shrink-0" />
              <span>
                {lockedTargetCount} of these {lockedTargetCount === 1 ? 'is' : 'are'} locked
                (memo). {lockedTargetCount === 1 ? 'It' : 'They'} will be unlocked first, then
                deleted.
              </span>
            </div>
          )}

          <div className="max-h-44 overflow-y-auto rounded-md border border-border bg-muted/30 p-2">
            <ul className="space-y-1 text-sm">
              {deleteTargets.map((parent) => (
                <li key={getParentId(parent)} className="flex items-center gap-1.5 truncate">
                  {isLocked(parent) && <Lock className="size-3 shrink-0 text-amber-500" />}
                  <span className="truncate">{getParentName(parent)}</span>
                  <span className="ml-auto shrink-0 text-xs text-muted-foreground">ID: {parent.instance_id}</span>
                </li>
              ))}
            </ul>
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={deleting}
              onClick={() => setConfirmOpen(false)}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              disabled={deleting || deleteTargets.length === 0}
              onClick={() => void confirmDelete()}
              data-testid="parent-delete-confirm"
            >
              <Trash2 />
              {deleting ? 'Deleting...' : 'Delete'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
