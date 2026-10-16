/**
 * Pure helpers for the dashboard live view.
 *
 * Exported as plain functions so they can be unit-tested without React.
 */

import type { ActionHistoryRow, RunnerStatus } from '@/api/types'

// ---------------------------------------------------------------------------
// formatStatsDetail — ported 1:1 from app.js:2269-2277
// ---------------------------------------------------------------------------

/**
 * Formats the stats detail string for an action history row.
 *
 * If the row has no stats keys, falls back to `row.detail || ''`.
 * If stats are present, returns a pipe-separated summary:
 *   HP 100/100 | MOOD 100 | SPD 100 STA 100 PWR 100 GUT 100 WIT 100 SP 100
 */
export function formatStatsDetail(row: ActionHistoryRow): string {
  const stats = row.stats || {}
  if (!Object.keys(stats).length) return row.detail || ''
  return [
    `HP ${stats.hp ?? 0}/${stats.max_hp ?? 100}`,
    `MOOD ${stats.motivation ?? 0}`,
    `SPD ${stats.speed ?? 0} STA ${stats.stamina ?? 0} PWR ${stats.power ?? 0} GUT ${stats.guts ?? 0} WIT ${stats.wit ?? 0} SP ${stats.skill_point ?? 0}`,
  ].join(' | ')
}

// ---------------------------------------------------------------------------
// deriveRunnerStatusText — pure text for status line cases 1/3/4/5
// ---------------------------------------------------------------------------

/**
 * Returns the status text to show when there are no action history rows,
 * or null when a table / banner takes visual priority (circuit_tripped).
 *
 * Precedence mirrors app.js:2228-2260.
 *
 * Cases:
 *   1. runner.running            → "Turn N / action / steps"
 *   2. runner.circuit_tripped    → null (BackoffBanner takes over — always shows)
 *   3. runner.last_error         → the error string
 *   4. runner.finished           → loop restart or finish text
 *   5. runner.steps              → "Runner stopped after N steps"
 *   6. no career at all          → null (caller shows empty state)
 */
export function deriveRunnerStatusText(runner: RunnerStatus | undefined | null): string | null {
  if (!runner) return null

  if (runner.running) {
    return `Turn ${runner.turn || '?'} / ${runner.last_action || 'running'} / ${runner.steps || 0}`
  }

  // circuit_tripped: BackoffBanner always shows — no status text needed here
  if (runner.circuit_tripped) return null

  if (runner.last_error) {
    return runner.last_error as string
  }

  if (runner.finished && !runner.last_error) {
    return runner.loop_active ? 'Career finished! Restarting...' : 'Career finished!'
  }

  if (runner.steps) {
    return `Runner stopped after ${runner.steps} steps`
  }

  return null
}
