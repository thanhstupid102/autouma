/**
 * Events page — per-event choice configuration.
 *
 * Shows all captured events from the catalog.  Each event has a choice
 * selector (Auto | Choice 1 … Choice N).  Changes are held locally until
 * the SAVE button is clicked.
 *
 * The event list (~2000–3700 rows) is paged rather than rendered all at
 * once: PAGE_SIZE rows are sliced from the filtered set at a time, since
 * each row has a heavy Radix Select and rendering thousands of them at once
 * is what caused the lag. See the "Pagination" section below.
 */

import { useState, useMemo, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { RefreshCw, Search, Database } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { TouchControlRow } from '@/components/ui/touch-control-row'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { EventRow } from '@/components/events/EventRow'
import { EventCard } from '@/components/events/EventCard'

import {
  getEventCatalog,
  rebuildEventCatalog,
  getEventPrefs,
  saveEventPrefs,
  updateEventDatabase,
} from '@/api/events'
import type { EventSource } from '@/api/types'

// ---------------------------------------------------------------------------
// Source filter options
// ---------------------------------------------------------------------------

const SOURCE_OPTIONS: Array<'all' | EventSource> = [
  'all',
  'support',
  'scenario',
  'chara',
  'other',
]

// ---------------------------------------------------------------------------
// Events page
// ---------------------------------------------------------------------------

export default function Events() {
  const qc = useQueryClient()

  // -------------------------------------------------------------------------
  // Remote data
  // -------------------------------------------------------------------------

  const catalogQuery = useQuery({
    queryKey: ['events-catalog'],
    queryFn: getEventCatalog,
  })

  const prefsQuery = useQuery({
    queryKey: ['events-prefs'],
    queryFn: getEventPrefs,
  })

  // -------------------------------------------------------------------------
  // Local working prefs (dirty state)
  // -------------------------------------------------------------------------

  const [localPrefs, setLocalPrefs] = useState<Record<string, number> | null>(null)

  // Derived: effective prefs = local override if set, else server prefs
  const serverPrefs = prefsQuery.data?.prefs ?? {}
  const workingPrefs = localPrefs ?? serverPrefs

  // Whether there are unsaved local changes
  const isDirty = localPrefs !== null

  function handleChoiceChange(storyId: string, value: number | undefined) {
    setLocalPrefs(prev => {
      const base = prev ?? serverPrefs
      const next = { ...base }
      if (value === undefined) {
        delete next[storyId] // Auto → remove key
      } else {
        next[storyId] = value
      }
      return next
    })
  }

  // -------------------------------------------------------------------------
  // Save mutation
  // -------------------------------------------------------------------------

  const saveMutation = useMutation({
    mutationFn: () => saveEventPrefs(workingPrefs),
    onSuccess: () => {
      setLocalPrefs(null)
      qc.invalidateQueries({ queryKey: ['events-prefs'] })
      toast.success('Event preferences saved')
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : 'Failed to save preferences')
    },
  })

  // -------------------------------------------------------------------------
  // Rebuild mutation
  // -------------------------------------------------------------------------

  const rebuildMutation = useMutation({
    mutationFn: rebuildEventCatalog,
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ['events-catalog'] })
      toast.success(`Catalog rebuilt — ${data.count} events found`)
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : 'Rebuild failed')
    },
  })

  // -------------------------------------------------------------------------
  // Update Event Database mutation (re-scrapes gametora, ~10 s)
  // -------------------------------------------------------------------------

  const updateDbMutation = useMutation({
    mutationFn: updateEventDatabase,
    onSuccess: (data) => {
      if (data.success === false) {
        toast.error(data.detail ?? 'Update failed')
        return
      }
      qc.invalidateQueries({ queryKey: ['events-catalog'] })
      toast.success(
        `Updated — ${data.events ?? 0} events, ${data.multi ?? 0} configurable`
      )
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : 'Update failed')
    },
  })

  // -------------------------------------------------------------------------
  // Filters
  // -------------------------------------------------------------------------

  const [sourceFilter, setSourceFilter] = useState<'all' | EventSource>('all')
  const [searchQuery, setSearchQuery] = useState('')
  // Show all events by default (incl. single-choice) so the count matches the
  // catalog total; the toggle lets the user hide non-configurable single-choice ones.
  const [showSingleChoice, setShowSingleChoice] = useState(true)

  // Memoised so the `?? []` fallback does not hand `filteredEvents` a fresh
  // array identity on every render (react-hooks/exhaustive-deps).
  const catalogEvents = catalogQuery.data?.events
  const allEvents = useMemo(() => catalogEvents ?? [], [catalogEvents])

  const filteredEvents = useMemo(() => {
    return allEvents.filter(entry => {
      if (!showSingleChoice && entry.n_choices <= 1) return false
      if (sourceFilter !== 'all' && entry.source !== sourceFilter) return false
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase()
        if (
          !(entry.name ?? '').toLowerCase().includes(q) &&
          !entry.label.toLowerCase().includes(q) &&
          !entry.story_id.toLowerCase().includes(q)
        ) {
          return false
        }
      }
      return true
    })
  }, [allEvents, sourceFilter, searchQuery, showSingleChoice])

  // -------------------------------------------------------------------------
  // Pagination — render one page of rows at a time (each row has a heavy Radix
  // Select, so windowing thousands of them is what caused the lag).
  // -------------------------------------------------------------------------

  const PAGE_SIZE = 50
  const [page, setPage] = useState(0)
  const pageCount = Math.max(1, Math.ceil(filteredEvents.length / PAGE_SIZE))

  // Reset to the first page whenever the filtered set changes (filter/search/toggle).
  useEffect(() => {
    setPage(0)
  }, [sourceFilter, searchQuery, showSingleChoice, allEvents.length])

  const safePage = Math.min(page, pageCount - 1)
  const pageEvents = filteredEvents.slice(safePage * PAGE_SIZE, safePage * PAGE_SIZE + PAGE_SIZE)

  // -------------------------------------------------------------------------
  // Loading / error states
  // -------------------------------------------------------------------------

  const isLoading = catalogQuery.isPending || prefsQuery.isPending

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------

  return (
    <div
      className="mx-auto min-w-0 max-w-4xl space-y-5 p-4 md:p-6"
      data-testid="events-page"
    >
      {/* Page header */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold">Event Choices</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Configure which choice the bot picks for each captured event.
          </p>
        </div>

        {/* Action buttons */}
        <div
          className="flex w-full flex-wrap items-center gap-2 md:w-auto"
          data-testid="events-actions"
        >
          {isDirty && (
            <span className="text-xs text-amber-600 dark:text-amber-400 font-medium">
              ● Unsaved
            </span>
          )}

          {/* Update Event Database */}
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => updateDbMutation.mutate()}
                  disabled={updateDbMutation.isPending}
                >
                  <Database
                    className={`h-3.5 w-3.5 mr-1.5 ${updateDbMutation.isPending ? 'animate-pulse' : ''}`}
                  />
                  {updateDbMutation.isPending ? 'Updating…' : 'Update Event Database'}
                </Button>
              </TooltipTrigger>
              <TooltipContent side="bottom">
                <p>Fetches latest event data from gametora. May take ~10 s.</p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>

          <Button
            size="sm"
            variant="outline"
            onClick={() => rebuildMutation.mutate()}
            disabled={rebuildMutation.isPending}
          >
            <RefreshCw
              className={`h-3.5 w-3.5 mr-1.5 ${rebuildMutation.isPending ? 'animate-spin' : ''}`}
            />
            {rebuildMutation.isPending ? 'Rebuilding…' : 'Rebuild'}
          </Button>
          <Button
            size="sm"
            onClick={() => saveMutation.mutate()}
            disabled={saveMutation.isPending || !isDirty}
          >
            {saveMutation.isPending ? 'Saving…' : 'Save'}
          </Button>
        </div>
      </div>

      {/* Filters row */}
      <div className="flex min-w-0 flex-wrap items-stretch gap-3 md:items-center">
        {/* Source filter */}
        <div
          className="flex w-full min-w-0 flex-wrap items-center gap-1 md:w-auto"
          role="group"
          aria-label="Event source filter"
        >
          {SOURCE_OPTIONS.map(src => (
            <Button
              key={src}
              type="button"
              size="xs"
              variant="ghost"
              onClick={() => setSourceFilter(src)}
              aria-pressed={sourceFilter === src}
              className={`rounded-md px-2.5 capitalize ${
                sourceFilter === src
                  ? 'bg-primary/10 text-primary'
                  : 'text-muted-foreground hover:bg-muted hover:text-foreground'
              }`}
            >
              {src}
            </Button>
          ))}
        </div>

        {/* Search */}
        <div className="relative w-full min-w-0 md:w-auto md:min-w-[180px] md:max-w-xs md:flex-1">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground pointer-events-none" />
          <Input
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            placeholder="Search label or story_id…"
            aria-label="Search events"
            className="pl-8 text-base md:h-7 md:text-xs"
          />
        </div>

        {/* Count + show-single-choice toggle */}
        <div className="flex w-full items-center justify-between gap-3 md:ml-auto md:w-auto">
          <span className="text-xs text-muted-foreground">
            {filteredEvents.length} / {allEvents.length} events
          </span>
          <TouchControlRow
            className="w-auto p-0 text-xs text-muted-foreground md:min-h-0"
            label="Show single-choice"
            control={(
              <Switch
                id="show-single"
                size="sm"
                checked={showSingleChoice}
                onCheckedChange={setShowSingleChoice}
              />
            )}
          />
        </div>
      </div>

      {/* Responsive event list */}
      {isLoading ? (
        <div className="rounded-xl border border-border bg-card">
          <div className="py-12 text-center text-sm text-muted-foreground">Loading events…</div>
        </div>
      ) : allEvents.length === 0 ? (
        <div className="rounded-xl border border-border bg-card">
          <div className="py-12 text-center text-sm text-muted-foreground">
            No events captured yet. Run a career or click{' '}
            <button
              type="button"
              className="underline underline-offset-2 hover:text-foreground"
              onClick={() => rebuildMutation.mutate()}
              disabled={rebuildMutation.isPending}
            >
              Rebuild
            </button>{' '}
            to scan logs.
          </div>
        </div>
      ) : filteredEvents.length === 0 ? (
        <div className="rounded-xl border border-border bg-card">
          <div className="py-12 text-center text-sm text-muted-foreground">
            No events match the current filters.
          </div>
        </div>
      ) : (
        <>
          <div
            className="min-w-0 space-y-3 md:hidden"
            data-testid="events-mobile"
          >
            {pageEvents.map(entry => (
              <EventCard
                key={entry.story_id}
                entry={entry}
                prefValue={workingPrefs[entry.story_id]}
                onChoiceChange={handleChoiceChange}
              />
            ))}
          </div>

          <div
            className="hidden overflow-hidden rounded-xl border border-border bg-card md:block"
            data-testid="events-desktop"
          >
            <div className="grid grid-cols-[96px_1fr_48px_128px] border-b border-border bg-muted/30">
              <div className="px-3 py-2 text-left text-xs font-medium text-muted-foreground">
                Source
              </div>
              <div className="px-3 py-2 text-left text-xs font-medium text-muted-foreground">
                Event
              </div>
              <div className="px-3 py-2 text-right text-xs font-medium text-muted-foreground">
                Seen
              </div>
              <div className="px-3 py-2 text-right text-xs font-medium text-muted-foreground">
                Choice
              </div>
            </div>

            {/* One page of rows (light — no thousands of mounted Selects) */}
            {pageEvents.map(entry => (
              <EventRow
                key={entry.story_id}
                entry={entry}
                prefValue={workingPrefs[entry.story_id]}
                onChoiceChange={handleChoiceChange}
              />
            ))}
          </div>
        </>
      )}

      {/* Pagination + count */}
      {!isLoading && filteredEvents.length > 0 && (
        <div
          className="flex flex-col items-stretch gap-3 md:flex-row md:items-center md:justify-between"
          data-testid="events-pagination"
        >
          <p className="text-xs text-muted-foreground">
            {filteredEvents.length} event{filteredEvents.length !== 1 ? 's' : ''}
            {isDirty ? ' · unsaved changes' : ''}
          </p>
          {pageCount > 1 && (
            <div className="flex w-full items-center justify-between gap-2 md:w-auto">
              <Button
                size="sm"
                variant="outline"
                onClick={() => setPage(p => Math.max(0, p - 1))}
                disabled={safePage <= 0}
              >
                Prev
              </Button>
              <span className="text-xs text-muted-foreground tabular-nums">
                Page {safePage + 1} / {pageCount}
              </span>
              <Button
                size="sm"
                variant="outline"
                onClick={() => setPage(p => Math.min(pageCount - 1, p + 1))}
                disabled={safePage >= pageCount - 1}
              >
                Next
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
