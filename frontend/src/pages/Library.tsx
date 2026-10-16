/**
 * Library — six collapsible grids + team selection.
 *
 * Grids:
 *   1. Decks          — session.validDecks (filtered by isValidDeck)
 *   2. Friend Supports — loaded via getFriends; REFRESH button
 *   3. Trainees        — session.umas
 *   4. Parents         — session.parents (up to 2 veterans)
 *   5. Friend Parents  — rental_parent cards from friends; quota display
 *   6. Owned Cards     — session.supports (display only)
 *
 * Selection goes through useSelection (Zustand → POST /api/selection).
 *
 * Data source:
 *   session.validDecks  → DeckList
 *   session.umas        → TraineeGrid
 *   session.parents     → ParentGrid
 *   session.supports    → CardGrid
 *   getFriends()        → FriendGrid + FriendParentGrid
 */

import { useState, useEffect, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { useSession } from '@/hooks/useSession'
import { useSelection } from '@/stores/selection'
import { useAccountStore } from '@/stores/account'
import { isValidDeck } from '@/components/library/libraryRules'
import { DeckList } from '@/components/library/DeckList'
import { TeamPanel } from '@/components/dashboard/TeamPanel'
import { FriendGrid } from '@/components/library/FriendGrid'
import { TraineeGrid } from '@/components/library/TraineeGrid'
import { ParentGrid } from '@/components/library/ParentGrid'
import { FriendParentGrid } from '@/components/library/FriendParentGrid'
import { CardGrid } from '@/components/library/CardGrid'
import { getFriends, refreshParents } from '@/api/career'
import { requestParentRosterRefresh } from '@/lib/parentRosterRefresh'
import type { FriendInfo, RentalQuota, DeckInfo, TraineeInfo, ParentInfo, SessionData } from '@/api/types'

// ---------------------------------------------------------------------------
// Section wrapper — collapsible
// ---------------------------------------------------------------------------

interface SectionProps {
  title: string
  badge?: string | number
  defaultOpen?: boolean
  children: React.ReactNode
}

function Section({ title, badge, defaultOpen = true, children }: SectionProps) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="min-w-0 max-w-full overflow-hidden rounded-xl border border-border bg-card">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="flex w-full items-center justify-between px-4 py-3 text-left hover:bg-muted/50 transition-colors"
      >
        <span className="flex items-center gap-2">
          <span className="text-sm font-semibold">{title}</span>
          {badge !== undefined && (
            <span className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
              {badge}
            </span>
          )}
        </span>
        {open ? (
          <ChevronDown className="size-4 text-muted-foreground" />
        ) : (
          <ChevronRight className="size-4 text-muted-foreground" />
        )}
      </button>
      {open && <div className="px-4 pb-4">{children}</div>}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Library page
// ---------------------------------------------------------------------------

export default function Library() {
  const queryClient = useQueryClient()
  const selectedAccount = useAccountStore((state) => state.selected)
  const sessionQuery = useSession()
  const session = sessionQuery.data

  const sel = useSelection()

  // Derived library data from session
  const rawDecks = (session?.validDecks ?? session?.decks ?? []) as DeckInfo[]
  const validDecks = rawDecks.filter(isValidDeck)
  const umas = (session?.umas ?? []) as TraineeInfo[]
  const parents = (session?.parents ?? []) as ParentInfo[]
  const supports = (session?.supports ?? []) as { id: string | number; name?: string; type?: string; rarity?: number | string }[]
  const initialExcludeIds = (session?.friend_exclude_ids ?? []) as (number | string)[]
  const careerActive = !!(session?.account as { career?: { active?: boolean } } | undefined)?.career?.active

  // Friends state — lifted here so data loads on Library mount regardless of
  // whether the Friend Supports section is collapsed. FriendParentGrid shares it.
  const [friends, setFriends] = useState<FriendInfo[]>([])
  const [rentalQuota, setRentalQuota] = useState<RentalQuota | null>(null)
  const [friendSource, setFriendSource] = useState<string>('')
  const [friendsLoading, setFriendsLoading] = useState(false)
  const [friendExcludeIds, setFriendExcludeIds] = useState<(number | string)[]>(initialExcludeIds)
  const friendsLoadedRef = useRef(false)
  const [parentsLoading, setParentsLoading] = useState(false)
  const parentLoadTokenRef = useRef(0)

  // Load friends on Library mount — initial fetch (exclude_viewer_ids: [])
  useEffect(() => {
    if (friendsLoadedRef.current) return
    friendsLoadedRef.current = true
    void loadFriends(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // load/index is large and paced, so automatic refresh is shared across mounts
  // and limited to one attempt per account per five-minute staleness window.
  useEffect(() => {
    if (!session?.success || !selectedAccount || careerActive) return
    void loadParents(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedAccount, session?.success, careerActive])

  async function loadFriends(refresh: boolean) {
    if (friendsLoading) return
    setFriendsLoading(true)
    const ids = refresh ? friendExcludeIds : []
    try {
      const data = await getFriends({ exclude_viewer_ids: ids })
      if (!data.success) throw new Error((data as { detail?: string }).detail ?? 'Friend load failed')
      const loaded = data.friends ?? []
      setFriends(loaded)
      setFriendSource(data.source === 'initial' ? 'initial' : 'refresh')
      setRentalQuota(data.rental_quota ?? null)
      // Merge exclude ids (mirroring appendSeenFriendIds)
      const newExcludeIds = data.exclude_viewer_ids ?? []
      setFriendExcludeIds(prev => {
        const seen = new Set(prev)
        newExcludeIds.forEach(id => { if (id) seen.add(id) })
        return Array.from(seen)
      })
    } catch (e) {
      toast.error((e as Error).message ?? 'Friend load failed')
      setFriendSource('error')
    } finally {
      setFriendsLoading(false)
    }
  }

  function refreshFriends() {
    void loadFriends(true)
  }

  async function loadParents(force: boolean) {
    const requestAccount = selectedAccount
    const pending = requestParentRosterRefresh(
      requestAccount,
      () => refreshParents(requestAccount),
      { force },
    )
    if (!pending) return

    const loadToken = ++parentLoadTokenRef.current
    setParentsLoading(true)
    try {
      const data = await pending
      if (!data.success) throw new Error(data.detail ?? 'Parent roster refresh failed')

      const loadedParents = data.parents ?? []
      queryClient.setQueryData<SessionData>(['session', requestAccount], (current) => (
        current
          ? {
              ...current,
              parents: loadedParents,
              selection: data.selection ?? current.selection,
            }
          : current
      ))

      if (useAccountStore.getState().selected !== requestAccount) return

      const parentsById = new Map(
        loadedParents.map((parent) => [String(parent.instance_id), parent] as const),
      )
      const currentVeterans = useSelection.getState().veterans
      const reconciledVeterans = currentVeterans
        .map((veteran) => parentsById.get(String(veteran.instance_id)))
        .filter((veteran): veteran is ParentInfo => !!veteran)
      const removedCount = currentVeterans.length - reconciledVeterans.length
      if (removedCount > 0) {
        await useSelection.getState().setVeterans(reconciledVeterans)
        toast.info(
          `Removed ${removedCount} unavailable career parent${removedCount === 1 ? '' : 's'} from the selection`,
        )
      }
    } catch (error) {
      if (useAccountStore.getState().selected === requestAccount) {
        toast.error(error instanceof Error ? error.message : 'Parent roster refresh failed')
      }
    } finally {
      if (parentLoadTokenRef.current === loadToken) {
        setParentsLoading(false)
      }
    }
  }

  function refreshParentRoster() {
    void loadParents(true)
  }

  // Selection handlers — all go through useSelection
  async function handleDeckSelect(deck: DeckInfo | null) {
    await sel.setDeck(deck)
  }

  async function handleTraineeSelect(t: TraineeInfo | null) {
    await sel.setTrainee(t)
  }

  async function handleFriendSelect(f: FriendInfo | null) {
    await sel.setFriend(f)
  }

  async function handleVeteransChange(vets: ParentInfo[]) {
    await sel.setVeterans(vets)
  }

  async function handleRentalSelect(viewerId: number | string | null) {
    await sel.setRental(viewerId)
  }

  if (sessionQuery.isLoading) {
    return (
      <div className="p-8 text-sm text-muted-foreground">Loading library…</div>
    )
  }

  if (!session?.success) {
    return (
      <div className="p-8 text-sm text-muted-foreground">
        Not logged in. Please log in to view your library.
      </div>
    )
  }

  return (
    <div className="p-4 md:p-6">
      <h1 className="mb-4 text-xl font-semibold">Library</h1>

      {/* Left: sticky team panel (track selection) · Right: grids */}
      <div className="grid items-start gap-4 lg:grid-cols-[280px_1fr]">
        <aside className="lg:sticky lg:top-4">
          <TeamPanel />
        </aside>

        <div className="flex min-w-0 flex-col gap-4">
      {/* 1. Decks */}
      <Section title="Decks" badge={validDecks.length}>
        {validDecks.length === 0 ? (
          <p className="text-sm text-muted-foreground">No valid decks found in session.</p>
        ) : (
          <DeckList
            decks={validDecks}
            selectedDeck={sel.deck}
            onSelect={handleDeckSelect}
          />
        )}
      </Section>

      {/* 2. Friend Supports */}
      <Section title="Friend Supports" defaultOpen={false}>
        <FriendGrid
          friends={friends}
          loading={friendsLoading}
          source={friendSource}
          selectedDeck={sel.deck}
          selectedTrainee={sel.trainee}
          selectedFriend={sel.friend}
          onFriendSelect={handleFriendSelect}
          onRefresh={refreshFriends}
          careerActive={careerActive}
        />
      </Section>

      {/* 3. Trainees */}
      <Section title="Trainees" badge={umas.length}>
        {umas.length === 0 ? (
          <p className="text-sm text-muted-foreground">No trainees found.</p>
        ) : (
          <TraineeGrid
            trainees={umas}
            selected={sel.trainee}
            onSelect={handleTraineeSelect}
          />
        )}
      </Section>

      {/* 4. Parents */}
      <Section title="Parents" badge={parents.length}>
        <ParentGrid
          parents={parents}
          veterans={sel.veterans}
          onVeteransChange={handleVeteransChange}
          loading={parentsLoading}
          onRefresh={refreshParentRoster}
          careerActive={careerActive}
        />
      </Section>

      {/* 5. Friend Parents (rental) */}
      <Section title="Friend Parents" defaultOpen={false}>
        <FriendParentGrid
          friends={friends}
          loading={friendsLoading}
          source={friendSource}
          selectedRental={sel.rental}
          onRentalSelect={handleRentalSelect}
          onRefresh={refreshFriends}
          careerActive={careerActive}
          quota={rentalQuota}
        />
      </Section>

      {/* 6. Owned Cards */}
      <Section title="Owned Cards" badge={supports.length} defaultOpen={false}>
        {supports.length === 0 ? (
          <p className="text-sm text-muted-foreground">No owned cards found.</p>
        ) : (
          <CardGrid cards={supports} />
        )}
      </Section>
        </div>
      </div>
    </div>
  )
}
