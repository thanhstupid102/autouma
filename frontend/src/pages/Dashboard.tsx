/**
 * Dashboard — Task 8: run bar, run options, confirm/pause/delete.
 *             Task 9: stats row, action history table, team panel, banners.
 */
import { RunBar } from '@/components/dashboard/RunBar'
import { RunOptions } from '@/components/dashboard/RunOptions'
import { StatsRow } from '@/components/dashboard/StatsRow'
import { ActionHistoryTable } from '@/components/dashboard/ActionHistoryTable'
import { TeamPanel } from '@/components/dashboard/TeamPanel'
import { BackoffBanner } from '@/components/dashboard/BackoffBanner'
import { OfflineBanner } from '@/components/dashboard/OfflineBanner'
import { deriveRunnerStatusText } from '@/components/dashboard/runnerView'
import { deriveActionHistory } from '@/lib/actionHistory'
import { useRunner } from '@/hooks/useRunner'
import { useSession } from '@/hooks/useSession'
import Login from './Login'
import Splash from '@/components/layout/Splash'
import type { ActionHistoryRow } from '@/api/types'
import { useLocation } from 'react-router-dom'

export default function Dashboard() {
  const location = useLocation()
  const forceSteamLogin = (
    location.state as { forceSteamLogin?: boolean } | null
  )?.forceSteamLogin === true
  // Account is bound by the parent AccountLayout route (/account/:name).
  const sessionQuery = useSession()
  const session = sessionQuery.data
  const loggedIn = !!session?.success

  // Rules of Hooks: every hook must run unconditionally and in the same order on
  // every render. useRunner MUST be called before any early return below —
  // gate its polling with `enabled` (false when not logged in) instead. Calling
  // it after the returns made the hook count change when the session flipped,
  // throwing React error #310 and blanking the page.
  const runnerQuery = useRunner(loggedIn)

  // Show splash while the session check is in flight for the first time
  if (sessionQuery.isPending) return <Splash />

  // Per-account login gate: if this account is not logged in, show the login UI.
  // useSession sends X-Account:name (because setSelected ran above), so this
  // check is scoped to the selected account.
  if (!loggedIn || forceSteamLogin) {
    return <Login forceSteamLogin={forceSteamLogin} />
  }

  const runner = runnerQuery.data?.runner
  const isOffline = runnerQuery.failureCount >= 3

  // Rows source: action_history if available, else derive from log (app.js:2226)
  const rows: ActionHistoryRow[] =
    runner?.action_history?.length
      ? runner.action_history
      : deriveActionHistory(runner?.log || [])

  const hasRows = rows.length > 0

  // Status text (cases 1/3/4/5) — null when banner/table takes over
  const statusText = hasRows ? null : deriveRunnerStatusText(runner)

  // Is last_error present (for red text styling)
  const isError = !runner?.running && !!runner?.last_error && !hasRows

  return (
    <div className="flex flex-col gap-4 p-4 md:p-6">
      <h1 className="text-xl font-semibold">Dashboard</h1>

      {/* Run bar — status pill, pause/resume, force-delete, run/resume button */}
      <RunBar />

      {/* Run options — delay, run count, no-cd, burn clocks, event */}
      <RunOptions />

      {/* Offline banner (server unreachable — distinct from backoff) */}
      {isOffline && <OfflineBanner />}

      {/* Backoff banner — always visible when circuit_tripped, even with table */}
      {runner?.circuit_tripped && (
        <BackoffBanner
          retryWaiting={runner.retry_waiting}
          retryAttempt={runner.retry_attempt}
          retryLimit={runner.retry_limit}
          retryWaitSeconds={runner.retry_wait_seconds}
        />
      )}

      {/* Stats row — hidden when no stats data */}
      {hasRows && <StatsRow rows={rows} />}

      {/* Main live area: history table (left ~2fr) + team panel (right ~1fr) */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[2fr_1fr]">
        {/* Action history table OR status text OR empty state */}
        <div>
          {hasRows ? (
            <ActionHistoryTable rows={rows} />
          ) : statusText ? (
            <div
              data-testid="runner-status-text"
              className={`whitespace-pre-wrap rounded-xl border border-border px-4 py-3 text-sm [overflow-wrap:anywhere] ${
                isError ? 'text-destructive' : 'text-muted-foreground'
              }`}
            >
              {statusText}
            </div>
          ) : runner ? null : (
            <div
              data-testid="career-empty"
              className="rounded-xl border border-dashed border-border px-4 py-6 text-center text-sm text-muted-foreground"
            >
              No career running.
            </div>
          )}
        </div>

        {/* Team panel */}
        <TeamPanel />
      </div>
    </div>
  )
}
