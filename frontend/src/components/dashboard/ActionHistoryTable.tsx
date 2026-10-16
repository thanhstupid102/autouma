/**
 * ActionHistoryTable — displays the action history rows for a running career.
 *
 * Desktop columns: TURN / ACTION / FACILITY / DETAIL.
 * Mobile rows reflow into stacked cards with expandable detail.
 * Auto-scroll follows new rows only while the operator is near the bottom.
 *
 * Source: app.js:2263-2303
 */
import { useEffect, useRef, useState } from 'react'

import {
  Table,
  TableHeader,
  TableHead,
  TableBody,
  TableRow,
  TableCell,
} from '@/components/ui/table'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Button } from '@/components/ui/button'
import type { ActionHistoryRow } from '@/api/types'
import { normalizeHistoryAction } from '@/lib/actionHistory'
import { formatStatsDetail } from './runnerView'

// ---------------------------------------------------------------------------
// Action pill color map
// ---------------------------------------------------------------------------

const ACTION_PILL_CLASS: Record<string, string> = {
  train: 'bg-blue-100 text-blue-800 border-blue-300 dark:bg-blue-900/30 dark:text-blue-300',
  race: 'bg-amber-100 text-amber-800 border-amber-300 dark:bg-amber-900/30 dark:text-amber-300',
  rest: 'bg-green-100 text-green-800 border-green-300 dark:bg-green-900/30 dark:text-green-300',
  recreation: 'bg-teal-100 text-teal-800 border-teal-300 dark:bg-teal-900/30 dark:text-teal-300',
  medic: 'bg-red-100 text-red-800 border-red-300 dark:bg-red-900/30 dark:text-red-300',
  finish: 'bg-gray-100 text-gray-700 border-gray-300 dark:bg-gray-800 dark:text-gray-300',
}

const DEFAULT_PILL_CLASS =
  'bg-gray-100 text-gray-700 border-gray-300 dark:bg-gray-800 dark:text-gray-300'

const NEAR_BOTTOM_THRESHOLD_PX = 48

function actionPillClass(action: string): string {
  return ACTION_PILL_CLASS[action] ?? DEFAULT_PILL_CLASS
}

interface HistoryRowView {
  turn: ActionHistoryRow['turn']
  action: string
  facility: ActionHistoryRow['facility']
  detail: string
}

function historyRowView(row: ActionHistoryRow): HistoryRowView {
  return {
    turn: row.turn,
    action: normalizeHistoryAction(row).action,
    facility: row.facility,
    detail: formatStatsDetail(row),
  }
}

function ActionPill({ action, testId }: { action: string; testId: string }) {
  return (
    <span
      data-testid={testId}
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${actionPillClass(action)}`}
    >
      {action}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface ActionHistoryTableProps {
  rows: ActionHistoryRow[]
}

export function ActionHistoryTable({ rows }: ActionHistoryTableProps) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const shouldFollowLatestRef = useRef(true)
  const [showJumpToLatest, setShowJumpToLatest] = useState(false)

  // Preserve the operator's position unless their previous position was already
  // within one small touch target of the bottom.
  useEffect(() => {
    const viewport = scrollRef.current
    if (!viewport) return

    if (shouldFollowLatestRef.current) {
      viewport.scrollTop = viewport.scrollHeight
      shouldFollowLatestRef.current = true
      setShowJumpToLatest(false)
    } else {
      setShowJumpToLatest(true)
    }
  }, [rows.length])

  function updateFollowState() {
    const viewport = scrollRef.current
    if (!viewport) return

    const distanceFromBottom =
      viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight
    const isNearBottom = distanceFromBottom <= NEAR_BOTTOM_THRESHOLD_PX
    shouldFollowLatestRef.current = isNearBottom
    setShowJumpToLatest(!isNearBottom)
  }

  function jumpToLatest() {
    const viewport = scrollRef.current
    if (!viewport) return

    viewport.scrollTop = viewport.scrollHeight
    shouldFollowLatestRef.current = true
    setShowJumpToLatest(false)
  }

  return (
    <div className="relative">
      <ScrollArea
        className="h-72 rounded-lg border border-border"
        // Pass the viewport ref via viewportRef isn't available on shadcn ScrollArea;
        // we use a directly scrollable inner wrapper instead.
      >
        <div
          ref={scrollRef}
          className="h-72 overflow-y-auto"
          data-testid="action-history-scroll"
          onScroll={updateFollowState}
        >
          <div data-testid="action-history-mobile" className="divide-y divide-border md:hidden">
            {rows.map((row, idx) => {
              const view = historyRowView(row)
              return (
                <article
                  key={idx}
                  data-testid={`action-history-card-${idx}`}
                  className="space-y-3 p-3"
                >
                  <dl className="grid grid-cols-[5rem_minmax(0,1fr)] gap-x-3 gap-y-2 text-sm">
                    <dt className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                      Turn
                    </dt>
                    <dd className="font-mono text-xs">{view.turn}</dd>
                    <dt className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                      Action
                    </dt>
                    <dd>
                      <ActionPill action={view.action} testId={`mobile-action-pill-${idx}`} />
                    </dd>
                    <dt className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                      Facility
                    </dt>
                    <dd className="min-w-0 [overflow-wrap:anywhere] text-xs text-muted-foreground">
                      {view.facility || '—'}
                    </dd>
                  </dl>
                  <details data-testid={`action-history-detail-${idx}`} className="group">
                    <summary className="min-h-11 cursor-pointer py-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground marker:text-primary">
                      Detail
                    </summary>
                    <p className="whitespace-pre-wrap [overflow-wrap:anywhere] text-xs text-muted-foreground">
                      {view.detail || '—'}
                    </p>
                  </details>
                </article>
              )
            })}
          </div>

          <div data-testid="action-history-desktop" className="hidden md:block">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-14 text-xs">TURN</TableHead>
                  <TableHead className="w-28 text-xs">ACTION</TableHead>
                  <TableHead className="w-28 text-xs">FACILITY</TableHead>
                  <TableHead className="text-xs">DETAIL</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row, idx) => {
                  const view = historyRowView(row)
                  return (
                    <TableRow key={idx}>
                      <TableCell className="font-mono text-xs">{view.turn}</TableCell>
                      <TableCell>
                        <ActionPill action={view.action} testId={`action-pill-${idx}`} />
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {view.facility}
                      </TableCell>
                      <TableCell className="max-w-xs truncate text-xs text-muted-foreground">
                        {view.detail}
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </div>
        </div>
      </ScrollArea>

      {showJumpToLatest && (
        <Button
          type="button"
          size="sm"
          className="absolute bottom-3 left-1/2 z-10 -translate-x-1/2 shadow-lg"
          onClick={jumpToLatest}
        >
          Jump to latest
        </Button>
      )}
    </div>
  )
}
