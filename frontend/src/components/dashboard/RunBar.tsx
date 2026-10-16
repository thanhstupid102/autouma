/**
 * RunBar — top card of Dashboard.
 *
 * STATUS PILL logic (app.js refreshRunnerStatus):
 *   RUNNING  : runner.running
 *   PAUSED   : runner.paused
 *   FINISHED : runner.finished && !runner.last_error
 *   BACKOFF  : runner.circuit_tripped
 *   IDLE     : default
 *
 * PAUSE/RESUME: visible when runner.running || runner.loop_active.
 *
 * FORCE DELETE: shown when activeCareer is true (career exists server-side).
 *
 * Summary: "Turn N" when runner.turn is defined.
 *   Fields intentionally omitted (not in RunnerStatus type):
 *     - current run index vs total (no field exists — only runCount from settings)
 *     - elapsed time (no start_timestamp field in RunnerStatus)
 */
import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogClose,
} from '@/components/ui/dialog'

import { pauseRunner, resumeRunner, deleteCareer, runCareer } from '@/api/career'
import type { RunnerStatus } from '@/api/types'
import { useRunSettings } from '@/stores/runSettings'
import { useSelection } from '@/stores/selection'
import { useSession } from '@/hooks/useSession'
import { useRunner } from '@/hooks/useRunner'
import { accountKey } from '@/lib/accountKey'

import { RunConfirmDialog } from './RunConfirmDialog'
import { buildRunBody } from './runBody'
import { getStartMissingReason } from './runRules'

// ---------------------------------------------------------------------------
// Active preset helpers
// ---------------------------------------------------------------------------
/**
 * readActivePreset — reads the ACCOUNT-SCOPED active preset key
 * (`uma_selected_preset__<account>`). The preset store writes the scoped key on
 * every select/create, so this stays in sync with the selected account.
 *
 * Plain localStorage read, not a hook — no React state/lifecycle involved.
 */
function readActivePreset(): string {
  return localStorage.getItem(accountKey('uma_selected_preset')) ?? ''
}

/**
 * readActiveRacePreset — reads the account-scoped race preset key
 * (`uma_selected_race_preset__<account>`).
 *
 * Plain localStorage read, not a hook — no React state/lifecycle involved.
 */
function readActiveRacePreset(): string {
  return localStorage.getItem(accountKey('uma_selected_race_preset')) ?? ''
}

// ---------------------------------------------------------------------------
// Status pill
// ---------------------------------------------------------------------------

type RunStatus = 'RUNNING' | 'PAUSED' | 'FINISHED' | 'RETRY WAIT' | 'BACKOFF' | 'IDLE'

function deriveStatus(runner: RunnerStatus | undefined): RunStatus {
  if (!runner) return 'IDLE'
  if (runner.running) return 'RUNNING'
  if (runner.paused) return 'PAUSED'
  if (runner.retry_waiting) return 'RETRY WAIT'
  if (runner.finished && !runner.last_error) return 'FINISHED'
  if (runner.circuit_tripped) return 'BACKOFF'
  return 'IDLE'
}

const STATUS_STYLES: Record<RunStatus, string> = {
  RUNNING: 'bg-green-500/15 text-green-700 border-green-500/30',
  PAUSED: 'bg-yellow-500/15 text-yellow-700 border-yellow-500/30',
  FINISHED: 'bg-blue-500/15 text-blue-700 border-blue-500/30',
  'RETRY WAIT': 'bg-orange-500/15 text-orange-700 border-orange-500/30',
  BACKOFF: 'bg-amber-500/15 text-amber-700 border-amber-500/30',
  IDLE: 'bg-muted/80 text-muted-foreground border-border',
}

// ---------------------------------------------------------------------------
// RunBar component
// ---------------------------------------------------------------------------

export function RunBar() {
  const qc = useQueryClient()
  const sessionQuery = useSession()
  const session = sessionQuery.data
  const account = session?.account
  const activeCareer = !!(account?.career?.active)

  // Runner polling — only when logged in
  const runnerQuery = useRunner(!!session?.success)
  const runner = runnerQuery.data?.runner
  const isRunning = !!runner?.running

  // Settings
  const {
    burnClocks,
    runCount,
    twoPalDeck,
    sparkReroll,
    scenarioId,
    scenarios,
    setScenarioId,
    setDevCareer,
    loadScenarios,
  } = useRunSettings()
  const selection = useSelection()
  const selectedPreset = readActivePreset()
  const selectedRacePreset = readActiveRacePreset()

  // Local UI state
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [isStarting, setIsStarting] = useState(false)
  const [isPauseLoading, setIsPauseLoading] = useState(false)
  const [isDeleting, setIsDeleting] = useState(false)

  useEffect(() => {
    void loadScenarios()
  }, [loadScenarios])

  // Derived
  const status = deriveStatus(runner)
  const missingReason = getStartMissingReason({
    selectedPreset,
    activeCareer,
    deck: selection.deck,
    friend: selection.friend,
    trainee: selection.trainee,
    veterans: selection.veterans,
  })
  const canRun = !missingReason && !isStarting
  // Keep PAUSE/RESUME visible after a save-and-exit pause (runner not running, but paused
  // and the career is still active server-side) so the user can RESUME it.
  const showPause = !!(runner && (runner.running || runner.loop_active || runner.paused))

  // ---------------------------------------------------------------------------
  // Start career
  // ---------------------------------------------------------------------------
  async function handleConfirmRun() {
    if (!canRun) return
    setIsStarting(true)
    try {
      const body = buildRunBody({
        activeCareer,
        selectedPreset,
        racePresetName: selectedRacePreset || undefined,
        burnClocks,
        twoPalDeck,
        sparkReroll,
        scenarioId,
        runCount,
        trainee: selection.trainee,
        deck: selection.deck,
        friend: selection.friend,
        veterans: selection.veterans,
        rental: selection.rental,
      })
      const data = await runCareer(body)
      if (!data.success) {
        toast.error(data.detail || 'Start failed')
        return
      }
      toast.success('Career runner started')
      await qc.invalidateQueries({ queryKey: ['runner'] })
      await qc.invalidateQueries({ queryKey: ['session'] })
      await qc.invalidateQueries({ queryKey: ['accounts'] })
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Start failed'
      toast.error(msg)
      // Exact port of app.js:2158-2160 — turn off devCareer on error
      setDevCareer(false)
    } finally {
      setIsStarting(false)
    }
  }

  // ---------------------------------------------------------------------------
  // Pause / Resume
  // ---------------------------------------------------------------------------
  async function handlePauseResume() {
    if (isPauseLoading) return
    setIsPauseLoading(true)
    try {
      const isPaused = !!(runner?.paused)
      if (isPaused) {
        await resumeRunner()
      } else {
        await pauseRunner()
      }
      await qc.invalidateQueries({ queryKey: ['runner'] })
      await qc.invalidateQueries({ queryKey: ['session'] })
      await qc.invalidateQueries({ queryKey: ['accounts'] })
    } catch {
      // Silently swallow — consistent with legacy togglePause
    } finally {
      setIsPauseLoading(false)
    }
  }

  // ---------------------------------------------------------------------------
  // Force delete
  // ---------------------------------------------------------------------------
  async function handleDelete() {
    if (isDeleting) return
    setIsDeleting(true)
    try {
      const currentTurn = runner?.turn ?? 0
      const data = await deleteCareer({ current_turn: currentTurn })
      if (!data.success) {
        toast.error(data.detail || 'Delete failed')
      } else {
        toast.success('Career deleted')
        setDeleteOpen(false)
        await qc.invalidateQueries({ queryKey: ['runner'] })
        await qc.invalidateQueries({ queryKey: ['session'] })
        await qc.invalidateQueries({ queryKey: ['accounts'] })
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Delete failed'
      toast.error(msg)
    } finally {
      setIsDeleting(false)
    }
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------
  const runBtnLabel = isStarting ? 'RUNNING...' : activeCareer ? 'RESUME CAREER' : 'RUN CAREER'

  // Build summary string — only use fields confirmed in RunnerStatus type
  const turnSummary =
    runner?.turn !== undefined ? `Turn ${runner.turn}` : null
  // Steps is also present in RunnerStatus
  const stepsSummary =
    runner?.steps !== undefined ? `/ ${runner.steps} steps` : null
  const summary =
    status !== 'IDLE' && turnSummary ? `${turnSummary}${stepsSummary ? ` ${stepsSummary}` : ''}` : null

  return (
    <>
      <div
        data-testid="run-controls"
        className="sticky top-0 z-30 -mx-4 bg-background/95 px-4 py-2 backdrop-blur md:static md:mx-0 md:bg-transparent md:p-0 md:backdrop-blur-none"
      >
        <Card>
          <CardContent className="flex flex-wrap items-center gap-3 py-3">
            {/* Status pill */}
            <span
              className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold ${STATUS_STYLES[status]}`}
            >
              {status}
            </span>

            {/* Scenario selector — visible beside status, used only for new careers */}
            <Select
              value={String(scenarioId)}
              disabled={isRunning || activeCareer}
              onValueChange={(val) => setScenarioId(Number(val))}
            >
              <SelectTrigger size="sm" aria-label="Scenario" className="w-full md:w-44">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {scenarios.map((scenario) => (
                  <SelectItem key={scenario.id} value={String(scenario.id)}>
                    {scenario.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            {/* Summary */}
            {summary && (
              <span className="text-xs text-muted-foreground">{summary}</span>
            )}

            {/* Spacer */}
            <div className="flex-1" />

            <div className="grid w-full grid-cols-2 gap-2 md:contents">
              {/* PAUSE / RESUME */}
              {showPause && (
                <Button
                  size="sm"
                  variant="outline"
                  className="w-full md:w-auto"
                  disabled={isPauseLoading}
                  onClick={handlePauseResume}
                >
                  {runner?.paused ? 'RESUME' : 'PAUSE'}
                </Button>
              )}

              {/* FORCE DELETE — show when an active career exists */}
              {activeCareer && (
                <Button
                  size="sm"
                  variant="destructive"
                  className="w-full md:w-auto"
                  onClick={() => setDeleteOpen(true)}
                >
                  DELETE
                </Button>
              )}

              {/* RUN CAREER / RESUME CAREER */}
              <div className="col-span-2 flex flex-col items-stretch gap-1 md:items-end">
                <Button
                  size="sm"
                  className="w-full md:w-auto"
                  disabled={!canRun}
                  onClick={() => setConfirmOpen(true)}
                >
                  {runBtnLabel}
                </Button>
                {missingReason && !isStarting && (
                  <span className="text-xs text-muted-foreground">{missingReason}</span>
                )}
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Run confirm dialog */}
      <RunConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        runCount={runCount}
        activeCareer={activeCareer}
        onConfirm={handleConfirmRun}
      />

      {/* Force-delete confirm dialog */}
      <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <DialogContent showCloseButton={false}>
          <DialogHeader>
            <DialogTitle>Delete Career?</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            This will force-delete the ongoing career.
          </p>
          <DialogFooter>
            <DialogClose asChild>
              <Button variant="outline" size="sm" disabled={isDeleting}>
                Cancel
              </Button>
            </DialogClose>
            <Button
              size="sm"
              variant="destructive"
              disabled={isDeleting}
              onClick={handleDelete}
            >
              {isDeleting ? 'DELETING...' : 'DELETE'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
