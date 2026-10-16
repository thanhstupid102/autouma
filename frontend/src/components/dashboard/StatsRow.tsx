/**
 * StatsRow — 8 compact stat cards fed by the last action_history row that has stats.
 *
 * HP shows hp/max_hp with a progress bar.
 * MOOD shows motivation.
 * SPD/STA/PWR/GUT/WIT/SP show corresponding stat values.
 *
 * Hidden entirely when no stats data is available.
 */
import type { ActionHistoryRow } from '@/api/types'
import { formatNumber } from '@/lib/locale'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Find the last row that has at least one stats key.
 * Module-local: a component file must export components only
 * (react-refresh/only-export-components).
 */
function findLastStats(
  rows: ActionHistoryRow[]
): ActionHistoryRow['stats'] | undefined {
  for (let i = rows.length - 1; i >= 0; i--) {
    const s = rows[i].stats
    if (s && Object.keys(s).length > 0) return s
  }
  return undefined
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

interface StatCardProps {
  label: string
  value: React.ReactNode
}

function StatCard({ label, value }: StatCardProps) {
  return (
    <div className="flex min-w-[72px] flex-col items-center gap-1 rounded-lg border border-border bg-card px-3 py-2">
      <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
        {label}
      </span>
      <span className="text-sm font-semibold tabular-nums text-foreground">{value}</span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface StatsRowProps {
  rows: ActionHistoryRow[]
}

export function StatsRow({ rows }: StatsRowProps) {
  const stats = findLastStats(rows)
  if (!stats) return null

  const hp = stats.hp ?? 0
  const maxHp = stats.max_hp ?? 100
  const hpPct = maxHp > 0 ? Math.min(100, Math.round((hp / maxHp) * 100)) : 0

  return (
    <div
      data-testid="stats-row"
      className="flex flex-wrap gap-2"
    >
      {/* HP — with progress bar */}
      <div className="flex min-w-[96px] flex-col items-center gap-1 rounded-lg border border-border bg-card px-3 py-2">
        <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
          HP
        </span>
        <span className="text-sm font-semibold tabular-nums text-foreground">
          {formatNumber(hp)}/{formatNumber(maxHp)}
        </span>
        <div className="h-1 w-full overflow-hidden rounded-full bg-muted">
          <div
            data-testid="hp-bar"
            className="h-full rounded-full bg-rose-500"
            style={{ width: `${hpPct}%` }}
          />
        </div>
      </div>

      {/* MOOD */}
      <StatCard label="MOOD" value={formatNumber(stats.motivation ?? 0)} />

      {/* Main stats */}
      <StatCard label="SPD" value={formatNumber(stats.speed ?? 0)} />
      <StatCard label="STA" value={formatNumber(stats.stamina ?? 0)} />
      <StatCard label="PWR" value={formatNumber(stats.power ?? 0)} />
      <StatCard label="GUT" value={formatNumber(stats.guts ?? 0)} />
      <StatCard label="WIT" value={formatNumber(stats.wit ?? 0)} />
      <StatCard label="SP" value={formatNumber(stats.skill_point ?? 0)} />
    </div>
  )
}
