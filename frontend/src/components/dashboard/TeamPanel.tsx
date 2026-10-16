/**
 * TeamPanel — displays the current career selection (deck, trainee, friend,
 * parents, rental) and active preset name.
 *
 * Reads from useSelection (Zustand) + useSession (account) + localStorage.
 * Each row links to /library or /setup as appropriate.
 */
import { Link } from 'react-router-dom'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useSelection } from '@/stores/selection'
import { useSession } from '@/hooks/useSession'
import { useAccountStore } from '@/stores/account'
import { accountKey } from '@/lib/accountKey'
import type { ParentInfo } from '@/api/types'

// ---------------------------------------------------------------------------
// Active-preset helper (mirrors RunBar's readActivePreset — same localStorage key)
// ---------------------------------------------------------------------------

function readActivePreset(): string {
  return localStorage.getItem(accountKey('uma_selected_preset')) ?? ''
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Return a human-readable name for a parent (veteran) entry. */
function parentName(p: ParentInfo | undefined): string {
  if (!p) return '—'
  // 'name' is present at runtime but not part of the typed ParentInfo shape;
  // card_id/instance_id are the fallback identifiers when it's missing.
  return String(
    (p as Record<string, unknown>).name ?? p.card_id ?? p.instance_id ?? '—'
  )
}

// ---------------------------------------------------------------------------
// Row component
// ---------------------------------------------------------------------------

interface TeamRowProps {
  label: string
  value: React.ReactNode
  to?: string
}

function TeamRow({ label, value, to }: TeamRowProps) {
  return (
    <div className="flex items-stretch gap-2 text-sm md:items-baseline md:py-1">
      <span className="flex w-20 shrink-0 items-center text-[11px] font-semibold uppercase tracking-wide text-muted-foreground md:block">
        {label}
      </span>
      {to ? (
        <Link
          to={to}
          className="flex min-h-11 min-w-0 flex-1 items-center [overflow-wrap:anywhere] font-medium text-primary underline-offset-2 hover:underline md:min-h-0"
        >
          {value || 'select…'}
        </Link>
      ) : (
        <span className="min-w-0 flex-1 py-3 [overflow-wrap:anywhere] font-medium text-foreground md:py-0">
          {value || '—'}
        </span>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function TeamPanel() {
  const sel = useSelection()
  const sessionQuery = useSession()
  const account = sessionQuery.data?.account
  const preset = readActivePreset()
  // Account-scoped links so "Preset"/"Deck"/… jump to THIS account's pages.
  const selected = useAccountStore((s) => s.selected)
  const base = selected ? `/account/${encodeURIComponent(selected)}` : ''

  // Veteran names
  const vet0 = sel.veterans?.[0]
  const vet1 = sel.veterans?.[1]

  // Deck name — DeckInfo always carries `name` per types.ts
  const deckName = sel.deck?.name ?? null

  // Trainee name — TraineeInfo.name is optional; falls back to id when unset
  const traineeName = sel.trainee?.name ?? (sel.trainee ? String(sel.trainee.id) : null)

  // Friend name — support_name is the human-readable field in FriendInfo
  const friendName =
    sel.friend?.support_name ?? (sel.friend ? String(sel.friend.viewer_id) : null)

  // Rental — stored as viewer_id number
  const rentalDisplay = sel.rental ? String(sel.rental) : null

  // Account TP / clocks for quick glance
  const tp = account?.tp ? `${account.tp.current}/${account.tp.max}` : null
  const clocks = account?.clocks !== undefined ? String(account.clocks) : null

  return (
    <Card>
      <CardHeader>
        <CardTitle>Team</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col divide-y divide-border">
        <TeamRow label="Preset" value={preset || '—'} to={`${base}/setup`} />
        <TeamRow label="Deck" value={deckName || 'select…'} to={`${base}/library`} />
        <TeamRow label="Trainee" value={traineeName || 'select…'} to={`${base}/library`} />
        <TeamRow label="Friend" value={friendName || 'select…'} to={`${base}/library`} />
        <TeamRow label="Parent 1" value={parentName(vet0)} to={`${base}/library`} />
        <TeamRow label="Parent 2" value={parentName(vet1)} to={`${base}/library`} />
        {sel.rental !== null && sel.rental !== undefined && (
          <TeamRow label="Rental" value={rentalDisplay} />
        )}
        {tp && <TeamRow label="TP" value={tp} />}
        {clocks !== null && <TeamRow label="Clocks" value={clocks} />}
      </CardContent>
    </Card>
  )
}
